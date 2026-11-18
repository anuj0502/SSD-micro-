"""Custom batch processing engine.

Retained traces accumulate in a buffer that is flushed when either:

* ``batch_size`` traces have been collected (size-based), or
* ``flush_interval_s`` seconds have elapsed since the first buffered trace
  (time-based).

On flush the traces are serialized as JSONL, gzip-compressed and written to a
local spool file before being handed to the storage worker. The spool file is
the write-ahead log that makes a crash between "batch created" and "batch
uploaded" recoverable: the storage worker can re-read it on restart.

With batching disabled (used by benchmark experiment B) every retained trace is
flushed immediately as a single-trace batch so the number of storage writes is
directly comparable.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.collector.aggregation import TraceSummary
from app.collector.compression import compress_bytes, encode_jsonl
from app.config.settings import settings
from app.utils.logging import get_logger

log = get_logger("traceflow.batching")


@dataclass
class Batch:
    batch_id: str
    created_at: float
    trace_count: int
    span_count: int
    original_bytes: int
    compressed_bytes: int
    object_key: str
    spool_path: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None

    @property
    def compression_ratio(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return round(self.compressed_bytes / self.original_bytes, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "trace_count": self.trace_count,
            "span_count": self.span_count,
            "original_bytes": self.original_bytes,
            "compressed_bytes": self.compressed_bytes,
            "compression_ratio": self.compression_ratio,
            "object_key": self.object_key,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }


def build_object_key(batch_id: str, created_at: float) -> str:
    stamp = time.gmtime(created_at)
    return time.strftime("data/batches/%Y/%m/%d/", stamp) + f"{batch_id}.jsonl.gz"


class BatchProcessor:
    def __init__(
        self,
        on_batch: Callable[[Batch], Awaitable[None]],
        batch_size: int | None = None,
        flush_interval_s: float | None = None,
        spool_dir: str | None = None,
        enabled: bool = True,
    ) -> None:
        self._on_batch = on_batch
        self.batch_size = batch_size or settings.batch_size
        self.flush_interval_s = flush_interval_s or settings.batch_flush_interval_s
        self.spool_dir = Path(spool_dir or Path(settings.data_dir) / "pending")
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self._buffer: list[dict[str, Any]] = []
        self._trace_ids: list[str] = []
        self._first_buffered_at: float | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.counters = {
            "traces_buffered": 0,
            "batches_created": 0,
            "traces_batched": 0,
            "write_ops": 0,
            "original_bytes": 0,
            "compressed_bytes": 0,
            "size_flushes": 0,
            "time_flushes": 0,
            "manual_flushes": 0,
            "late_updates_applied": 0,
            "late_updates_missed": 0,
        }

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._timer_loop(), name="batch-timer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush(reason="shutdown")

    async def _timer_loop(self) -> None:
        while True:
            await asyncio.sleep(min(0.5, self.flush_interval_s))
            try:
                async with self._lock:
                    if self._buffer and self._first_buffered_at is not None:
                        if (time.time() - self._first_buffered_at) >= self.flush_interval_s:
                            await self._flush_locked(reason="time")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                log.error("batch timer flush failed", extra={"error": str(exc)})

    async def add_trace(self, summary: TraceSummary) -> None:
        entry = {"kind": "trace", "trace": summary.as_payload()}
        async with self._lock:
            if self._first_buffered_at is None:
                self._first_buffered_at = time.time()
            self._buffer.append(entry)
            self._trace_ids.append(summary.trace_id)
            self.counters["traces_buffered"] += 1
            if not self.enabled:
                await self._flush_locked(reason="batching_disabled")
            elif len(self._buffer) >= self.batch_size:
                await self._flush_locked(reason="size")

    async def update_trace(self, summary: TraceSummary) -> bool:
        """Merge late spans into a buffered (not yet flushed) trace entry."""
        async with self._lock:
            for entry in self._buffer:
                if entry["kind"] == "trace" and entry["trace"]["trace_id"] == summary.trace_id:
                    entry["trace"] = summary.as_payload()
                    self.counters["late_updates_applied"] += 1
                    return True
        self.counters["late_updates_missed"] += 1
        return False

    async def flush(self, reason: str = "manual") -> list[Batch]:
        async with self._lock:
            return await self._flush_locked(reason=reason)

    async def _flush_locked(self, reason: str) -> list[Batch]:
        if not self._buffer:
            return []
        created_at = time.time()
        entries = self._buffer
        trace_ids = self._trace_ids
        self._buffer = []
        self._trace_ids = []
        self._first_buffered_at = None

        batch_id = f"batch-{int(created_at * 1000)}-{uuid.uuid4().hex[:6]}"
        raw = encode_jsonl(entries)
        compressed = compress_bytes(raw)
        object_key = build_object_key(batch_id, created_at)
        spool_path = self.spool_dir / f"{batch_id}.jsonl.gz"
        await asyncio.to_thread(spool_path.write_bytes, compressed)

        span_count = sum(len(entry["trace"]["spans"]) for entry in entries if entry.get("kind") == "trace")
        batch = Batch(
            batch_id=batch_id,
            created_at=created_at,
            trace_count=len(entries),
            span_count=span_count,
            original_bytes=len(raw),
            compressed_bytes=len(compressed),
            object_key=object_key,
            spool_path=str(spool_path),
            entries=entries,
            trace_ids=trace_ids,
        )
        self.counters["batches_created"] += 1
        self.counters["traces_batched"] += len(entries)
        self.counters["write_ops"] += 1
        self.counters["original_bytes"] += len(raw)
        self.counters["compressed_bytes"] += len(compressed)
        self.counters[f"{reason}_flushes" if reason in {"size", "time", "manual"} else "manual_flushes"] += 1
        log.info(
            "batch created",
            extra={
                "batch_id": batch_id,
                "traces": len(entries),
                "original_bytes": len(raw),
                "compressed_bytes": len(compressed),
                "reason": reason,
            },
        )
        await self._on_batch(batch)
        return [batch]

    def buffered(self) -> int:
        return len(self._buffer)

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "batch_size": self.batch_size,
            "flush_interval_s": self.flush_interval_s,
            "buffered_traces": len(self._buffer),
            "buffer_age_s": round(time.time() - self._first_buffered_at, 2) if self._first_buffered_at else 0,
            "counters": dict(self.counters),
        }
