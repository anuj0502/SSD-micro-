"""Ingestion entry point: validation, backpressure and enqueue to the buffer."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from app.buffers.stream import BufferUnavailable
from app.schemas.telemetry import Span, serialize_span
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.ingest")

MAX_SPANS_PER_REQUEST = 5_000


class BufferFull(RuntimeError):
    """Raised when the buffer is down and local spill capacity is exhausted."""


class IngestionService:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime

    async def ingest(self, spans: list[Span], source: str = "otlp") -> dict[str, Any]:
        counters = self.runtime.counters
        counters["requests_received"] += 1
        if len(spans) > MAX_SPANS_PER_REQUEST:
            raise ValueError(f"payload exceeds {MAX_SPANS_PER_REQUEST} spans")

        valid: list[Span] = []
        for span in spans:
            if not span.trace_id or not span.span_id or span.end_time_unix_nano < span.start_time_unix_nano:
                counters["spans_invalid"] += 1
                continue
            valid.append(span)
        if not valid:
            return {"accepted": 0, "rejected": 0, "spilled": 0, "buffer": "n/a"}

        counters["spans_received"] += len(valid)
        payload = [serialize_span(span) for span in valid]
        started = time.perf_counter()
        buffer = self.runtime.buffer
        if buffer is None:
            raise BufferFull("ingestion buffer is not initialised")

        try:
            await buffer.add_spans(payload)
            counters["spans_enqueued"] += len(payload)
            counters["ingestion_batches"] += 1
            self.runtime.record_ingest_latency((time.perf_counter() - started) * 1000)
            return {
                "accepted": len(payload),
                "rejected": 0,
                "spilled": 0,
                "buffer": buffer.backend,
                "source": source,
            }
        except (BufferUnavailable, ConnectionError, OSError) as exc:
            counters["buffer_unavailable"] += 1
            log.warning("buffer unavailable, spilling locally", extra={"error": str(exc)})
            try:
                self.runtime.spill_queue.put_nowait(payload)
                counters["spans_spilled"] += len(payload)
                self.runtime.record_ingest_latency((time.perf_counter() - started) * 1000)
                return {
                    "accepted": 0,
                    "spilled": len(payload),
                    "rejected": 0,
                    "buffer": "unavailable",
                    "degraded": True,
                }
            except asyncio.QueueFull as full_exc:
                counters["spans_rejected"] += len(payload)
                raise BufferFull("buffer unavailable and local spill queue is full") from full_exc
