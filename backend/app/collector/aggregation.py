"""Distributed trace aggregation.

Spans arrive out of order and from many services; this module groups them by
trace id, computes the trace summary (root span, duration, services, edges),
and decides when a trace is *complete* using an inactivity timeout (the tail
sampling decision window).

A trace is considered complete only when no new span for it has arrived for
``completion_timeout_s``. Traces are held in memory while open; once decided
they move to a short-lived "closed" cache so late spans can be detected and
handled explicitly instead of being silently merged.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from app.schemas.telemetry import Span, serialize_span
from app.utils.logging import get_logger

log = get_logger("traceflow.aggregation")


class AddOutcome(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    LATE_DROPPED = "late_dropped"
    LATE_ACCEPTED = "late_accepted"


@dataclass
class ServiceStat:
    service: str
    span_count: int = 0
    error_count: int = 0
    duration_ms: float = 0.0
    start_time: float = 0.0


@dataclass
class EdgeStat:
    parent_service: str
    child_service: str
    call_count: int = 0
    error_count: int = 0
    total_ms: float = 0.0


@dataclass
class TraceSummary:
    trace_id: str
    root_service: str
    root_operation: str
    start_time: float
    end_time: float
    duration_ms: float
    span_count: int
    status: str
    has_error: bool
    error_message: str | None
    services: list[ServiceStat]
    edges: list[EdgeStat]
    spans: list[Span]
    late_span_count: int = 0
    truncated: bool = False

    @property
    def service_count(self) -> int:
        return len(self.services)

    def as_payload(self) -> dict[str, Any]:
        """Serialized form stored in compressed JSONL batches."""
        return {
            "trace_id": self.trace_id,
            "root_service": self.root_service,
            "root_operation": self.root_operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "span_count": self.span_count,
            "late_span_count": self.late_span_count,
            "truncated": self.truncated,
            "spans": [serialize_span(s) for s in self.spans],
        }


@dataclass
class AssembledTrace:
    trace_id: str
    spans: dict[str, Span] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    decided: bool = False
    decided_at: float | None = None
    decision: str | None = None
    late_spans: list[Span] = field(default_factory=list)
    late_span_count: int = 0

    def add(self, span: Span, now: float) -> bool:
        if span.span_id in self.spans:
            return False
        self.spans[span.span_id] = span
        self.last_seen = now
        return True

    def summary(self, slow_threshold_ms: float) -> TraceSummary:
        spans = list(self.spans.values())
        if not spans:
            raise ValueError("cannot summarise an empty trace")

        by_id = self.spans
        root = None
        for candidate in spans:
            pid = candidate.parent_span_id
            if not pid or pid not in by_id:
                if root is None:
                    root = candidate
        root = root or spans[0]

        start_ns = min(s.start_time_unix_nano for s in spans)
        end_ns = max(s.end_time_unix_nano for s in spans)
        duration_ms = round((end_ns - start_ns) / 1e6, 3)

        has_error = any(s.has_error for s in spans)
        status = "error" if has_error else ("slow" if duration_ms >= slow_threshold_ms else "success")

        error_message = None
        for span in spans:
            if span.has_error:
                error_message = span.status_message or (
                    f"{span.service}: {span.name} failed"
                )
                break

        services: dict[str, ServiceStat] = {}
        for span in spans:
            stat = services.setdefault(
                span.service,
                ServiceStat(service=span.service, start_time=span.start_time),
            )
            stat.span_count += 1
            stat.duration_ms = round(stat.duration_ms + span.duration_ms, 3)
            stat.start_time = min(stat.start_time, span.start_time)
            if span.has_error:
                stat.error_count += 1

        edges: dict[tuple[str, str], EdgeStat] = {}
        for span in spans:
            parent = by_id.get(span.parent_span_id or "")
            if parent is None or parent.service == span.service:
                continue
            key = (parent.service, span.service)
            edge = edges.setdefault(
                key,
                EdgeStat(parent_service=parent.service, child_service=span.service),
            )
            edge.call_count += 1
            edge.total_ms = round(edge.total_ms + span.duration_ms, 3)
            if span.has_error:
                edge.error_count += 1

        return TraceSummary(
            trace_id=self.trace_id,
            root_service=root.service,
            root_operation=root.name,
            start_time=start_ns / 1e9,
            end_time=end_ns / 1e9,
            duration_ms=duration_ms,
            span_count=len(spans),
            status=status,
            has_error=has_error,
            error_message=error_message,
            services=sorted(services.values(), key=lambda s: s.service),
            edges=sorted(edges.values(), key=lambda e: (e.parent_service, e.child_service)),
            spans=sorted(spans, key=lambda s: (s.start_time_unix_nano, s.span_id)),
            late_span_count=self.late_span_count,
            truncated=self.late_span_count > 0,
        )


class TraceAssembler:
    """Groups spans into traces and tracks the decision window."""

    def __init__(self, closed_ttl_s: float = 120.0, max_open_traces: int = 20_000) -> None:
        self._open: dict[str, AssembledTrace] = {}
        self._closed: dict[str, AssembledTrace] = {}
        self._closed_ttl = closed_ttl_s
        self._max_open = max_open_traces
        self.counters = {
            "spans_accepted": 0,
            "spans_duplicate": 0,
            "spans_late_dropped": 0,
            "spans_late_accepted": 0,
            "traces_completed": 0,
            "traces_evicted": 0,
        }
        self._late_dirty: set[str] = set()

    # -- ingestion ---------------------------------------------------------
    def add_span(self, span: Span, late_policy: str = "drop", now: float | None = None) -> AddOutcome:
        now = now or time.time()
        active = self._open.get(span.trace_id)
        if active is not None:
            if active.add(span, now):
                self.counters["spans_accepted"] += 1
                return AddOutcome.NEW if len(active.spans) == 1 else AddOutcome.ACCEPTED
            self.counters["spans_duplicate"] += 1
            return AddOutcome.DUPLICATE

        closed = self._closed.get(span.trace_id)
        if closed is not None:
            # The sampling decision was already taken for this trace.
            if late_policy == "accept_if_buffered":
                if span.span_id in closed.spans:
                    self.counters["spans_duplicate"] += 1
                    return AddOutcome.DUPLICATE
                closed.add(span, now)
                closed.late_spans.append(span)
                closed.late_span_count += 1
                closed.last_seen = now
                self._late_dirty.add(span.trace_id)
                self.counters["spans_late_accepted"] += 1
                return AddOutcome.LATE_ACCEPTED
            self.counters["spans_late_dropped"] += 1
            return AddOutcome.LATE_DROPPED

        # New trace, possibly beyond our memory bound.
        if len(self._open) >= self._max_open:
            self._evict_oldest()
        trace = AssembledTrace(trace_id=span.trace_id, first_seen=now, last_seen=now)
        trace.add(span, now)
        self._open[span.trace_id] = trace
        self.counters["spans_accepted"] += 1
        return AddOutcome.NEW

    def _evict_oldest(self) -> None:
        oldest = min(self._open.values(), key=lambda t: t.last_seen)
        self._open.pop(oldest.trace_id, None)
        self.counters["traces_evicted"] += 1
        log.warning("evicted open trace under memory pressure", extra={"trace_id": oldest.trace_id})

    def open_count(self) -> int:
        return len(self._open)

    # -- completion --------------------------------------------------------
    def finalize_due(self, timeout_s: float, slow_threshold_ms: float) -> list[TraceSummary]:
        """Return summaries of traces whose inactivity window has closed."""
        now = time.time()
        due_ids = [
            trace_id
            for trace_id, trace in self._open.items()
            if (now - trace.last_seen) >= timeout_s
        ]
        summaries: list[TraceSummary] = []
        for trace_id in due_ids:
            trace = self._open.pop(trace_id)
            trace.decided = True
            trace.decided_at = now
            self._closed[trace_id] = trace
            self.counters["traces_completed"] += 1
            summaries.append(trace.summary(slow_threshold_ms))
        self._prune_closed(now)
        return summaries

    def _prune_closed(self, now: float) -> None:
        stale = [
            trace_id
            for trace_id, trace in self._closed.items()
            if trace.last_seen + self._closed_ttl < now
        ]
        for trace_id in stale:
            self._closed.pop(trace_id, None)

    def drain_late_dirty(self) -> set[str]:
        """Trace ids that received late spans since the last drain."""
        dirty = self._late_dirty
        self._late_dirty = set()
        return dirty

    def summary_for(self, trace_id: str, slow_threshold_ms: float) -> TraceSummary | None:
        trace = self._closed.get(trace_id) or self._open.get(trace_id)
        return trace.summary(slow_threshold_ms) if trace else None

    def is_decided(self, trace_id: str) -> bool:
        return trace_id in self._closed

    def recent_decided(self, limit: int = 50) -> Iterable[AssembledTrace]:
        traces = sorted(self._closed.values(), key=lambda t: t.decided_at or 0, reverse=True)
        return traces[:limit]

    def reset(self) -> None:
        self._open.clear()
        self._closed.clear()
        self._late_dirty.clear()
