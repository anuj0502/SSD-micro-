"""Span-level deduplication.

Duplicate telemetry is expected in an at-least-once pipeline: a worker crash
causes Redis pending messages to be reclaimed and replayed, and clients may
retry exports. We therefore deduplicate on span id at ingestion time using a
durable database table of recently seen span ids (plus a bounded in-memory cache
for the hot path).

The guarantee this provides is *idempotent persistence* for spans: a span is
accepted by the pipeline at most once. It is not a global exactly-once
guarantee for arbitrary side effects.
"""
from __future__ import annotations

import time
from collections import OrderedDict

from app.schemas.telemetry import Span
from app.storage.database import Database
from app.utils.logging import get_logger

log = get_logger("traceflow.dedup")

_CHUNK = 400


class Deduplicator:
    def __init__(self, db: Database, cache_size: int = 50_000) -> None:
        self.db = db
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._cache_size = cache_size
        self.counters = {"spans_seen": 0, "spans_duplicate": 0}

    def _remember(self, span_id: str, now: float) -> None:
        self._cache[span_id] = now
        self._cache.move_to_end(span_id)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def filter_new(self, spans: list[Span]) -> tuple[list[Span], int]:
        """Return (new_spans, duplicate_count)."""
        if not spans:
            return [], 0
        self.counters["spans_seen"] += len(spans)
        now = time.time()

        # Fast path: anything already in the local cache is a duplicate.
        candidates: list[Span] = []
        duplicates = 0
        for span in spans:
            if span.span_id in self._cache:
                duplicates += 1
            else:
                candidates.append(span)
        if not candidates:
            self.counters["spans_duplicate"] += duplicates
            return [], duplicates

        existing: set[str] = set()
        ids = [s.span_id for s in candidates]
        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start : start + _CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = await self.db.fetchall(
                f"SELECT span_id FROM seen_spans WHERE span_id IN ({placeholders})", chunk
            )
            existing.update(row["span_id"] for row in rows)

        new_spans: list[Span] = []
        for span in candidates:
            if span.span_id in existing:
                duplicates += 1
                self._remember(span.span_id, now)
            else:
                new_spans.append(span)

        if new_spans:
            await self.db.executemany(
                "INSERT OR IGNORE INTO seen_spans(span_id, trace_id, seen_at) VALUES (?, ?, ?)",
                [(s.span_id, s.trace_id, now) for s in new_spans],
            )
            for span in new_spans:
                self._remember(span.span_id, now)

        self.counters["spans_duplicate"] += duplicates
        return new_spans, duplicates

    async def prune(self, older_than_seconds: float = 6 * 3600) -> int:
        cutoff = time.time() - older_than_seconds
        return await self.db.execute("DELETE FROM seen_spans WHERE seen_at < ?", (cutoff,))
