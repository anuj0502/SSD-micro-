"""Shared runtime container: wires buffers, storage, workers and counters."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.buffers.stream import StreamBuffer, create_buffer
from app.collector.aggregation import TraceAssembler
from app.collector.batching import BatchProcessor
from app.collector.deduplication import Deduplicator
from app.collector.sampling import SamplingConfig, Sampler, config_from_json
from app.config.settings import settings
from app.storage.indexing import EventLog, TraceIndex
from app.storage.object_store import ObjectStore, create_object_store
from app.storage.database import Database, db as default_db
from app.utils.logging import get_logger

log = get_logger("traceflow.runtime")


class Runtime:
    """Owns all long-lived components of the collector process."""

    def __init__(self, database: Database | None = None) -> None:
        self.db = database or default_db
        self.buffer: StreamBuffer | None = None
        self.store: ObjectStore | None = None
        self.assembler = TraceAssembler()
        self.index: TraceIndex | None = None
        self.events: EventLog | None = None
        self.dedup: Deduplicator | None = None
        self.sampler = Sampler(SamplingConfig(
            error_rate=settings.sampling_error_rate,
            slow_threshold_ms=settings.sampling_slow_threshold_ms,
            success_rate=settings.sampling_success_rate,
            completion_timeout_s=settings.sampling_completion_timeout_s,
            late_policy=settings.sampling_late_policy,
            deterministic=settings.sampling_deterministic,
        ))
        self.batch_queue: asyncio.Queue = asyncio.Queue()
        self.batcher: BatchProcessor | None = None
        self.spill_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.local_spill_maxsize)
        self.workers: dict[str, Any] = {}
        self.ready = False
        self.started_at = time.time()
        self.counters: dict[str, Any] = {
            "requests_received": 0,
            "spans_received": 0,
            "spans_invalid": 0,
            "spans_enqueued": 0,
            "buffer_unavailable": 0,
            "spans_spilled": 0,
            "spans_spill_flushed": 0,
            "spans_rejected": 0,
            "ingest_latency_ms": 0.0,
            "ingestion_batches": 0,
            "traces_indexed": 0,
            "sampling_latency_ms": 0.0,
            "buffer_high_watermark": 0,
            "backpressure_events": 0,
        }
        self._latency_ingest = _EMA()
        self._latency_sampling = _EMA()

    # -- lifecycle ---------------------------------------------------------
    async def start(self, enable_workers: bool = True) -> None:
        await self.db.connect()
        # Sampler configuration is persisted so UI changes survive restarts.
        row = await self.db.fetchone("SELECT value FROM settings WHERE key='sampling_config'")
        if row is not None:
            self.sampler.config = config_from_json(row["value"])
        row = await self.db.fetchone("SELECT value FROM settings WHERE key='batch_config'")
        if row is not None:
            import json as _json

            try:
                cfg = _json.loads(row["value"])
                settings.batch_size = int(cfg.get("batch_size", settings.batch_size))
                settings.batch_flush_interval_s = float(
                    cfg.get("flush_interval_s", settings.batch_flush_interval_s)
                )
            except Exception:  # pragma: no cover - corrupt setting
                log.warning("invalid persisted batch config, using defaults")

        self.store = await create_object_store()
        self.index = TraceIndex(self.db, self.store)
        self.events = EventLog(self.db)
        self.dedup = Deduplicator(self.db)

        from app.workers.ingestion_worker import IngestionWorker
        from app.workers.metrics_worker import MetricsWorker
        from app.workers.processing_worker import ProcessingWorker
        from app.workers.spill_worker import SpillWorker
        from app.workers.storage_worker import StorageWorker

        self.buffer = await create_buffer()
        self.batcher = BatchProcessor(on_batch=self._enqueue_batch)

        self.workers = {
            "ingestion": IngestionWorker(self),
            "processing": ProcessingWorker(self),
            "storage": StorageWorker(self),
            "spill": SpillWorker(self),
            "metrics": MetricsWorker(self),
        }
        if enable_workers:
            await self.start_workers()

        await self.events.add(
            "system",
            "Collector started",
            meta={"buffer": self.buffer.backend, "storage": self.store.backend},
        )
        self.ready = True

    async def start_workers(self) -> None:
        for name, worker in self.workers.items():
            if name == "storage":
                # storage worker must be up before batches are produced
                await worker.start()
        for name, worker in self.workers.items():
            if name != "storage":
                await worker.start()
        if self.batcher is not None:
            await self.batcher.start()

    async def stop(self) -> None:
        if self.batcher is not None:
            await self.batcher.stop()
        for worker in self.workers.values():
            await worker.stop()
        if self.buffer is not None:
            await self.buffer.close()
        if self.store is not None:
            await self.store.close()
        await self.db.close()
        self.ready = False

    async def _enqueue_batch(self, batch) -> None:
        await self.batch_queue.put(batch)

    async def mark_batch_uploaded(self, batch, attempts: int, duration_ms: float) -> None:
        """Persist a successful upload: batch status, trace index keys, spool cleanup."""
        assert self.index is not None
        await self.index.mark_batch_result(batch.batch_id, "uploaded", attempts, None, duration_ms)
        await self.index.attach_batch(batch.trace_ids, batch.batch_id, batch.object_key)
        try:
            from pathlib import Path

            Path(batch.spool_path).unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove batch spool file", extra={"batch_id": batch.batch_id})
        if self.events is not None:
            await self.events.add(
                "storage",
                f"Storage upload completed · {batch.object_key}",
                meta={"batch_id": batch.batch_id, "object_key": batch.object_key},
            )

    # -- counters ----------------------------------------------------------
    def record_ingest_latency(self, ms: float) -> None:
        self.counters["ingest_latency_ms"] = self._latency_ingest.add(ms)

    def record_sampling_latency(self, ms: float) -> None:
        self.counters["sampling_latency_ms"] = self._latency_sampling.add(ms)

    async def buffer_depth(self) -> int:
        if self.buffer is None:
            return 0
        try:
            return await self.buffer.stream_length()
        except Exception:
            return -1

    async def pending_messages(self) -> int:
        if self.buffer is None:
            return 0
        try:
            return await self.buffer.pending_count()
        except Exception:
            return -1

    # -- health ------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        buffer_ok = bool(self.buffer and await self.buffer.health())
        storage_ok = bool(self.store and await self.store.health())
        db_ok = self.db.healthy
        return {
            "status": "ok" if (buffer_ok and storage_ok and db_ok) else "degraded",
            "ready": self.ready,
            "uptime_s": round(time.time() - self.started_at, 1),
            "components": {
                "collector": {"status": "healthy" if self.ready else "starting", "workers": self.worker_states()},
                "redis": {
                    "status": "healthy" if buffer_ok else "unavailable",
                    "backend": self.buffer.backend if self.buffer else None,
                    "url": settings.redis_url if self.buffer and self.buffer.backend == "redis" else None,
                },
                "postgres": {"status": "healthy" if db_ok else "unavailable"},
                "minio": {
                    "status": "healthy" if storage_ok else "unavailable",
                    "backend": self.store.backend if self.store else None,
                    "bucket": settings.minio_bucket,
                },
            },
            "queue_depth": await self.buffer_depth(),
            "pending_messages": await self.pending_messages(),
        }

    def worker_states(self) -> dict[str, str]:
        return {name: ("running" if getattr(w, "running", False) else "stopped") for name, w in self.workers.items()}

    async def stage_snapshot(self) -> list[dict[str, Any]]:
        """Live pipeline counters used by the pipeline page."""
        self.counters["buffer_high_watermark"] = max(
            self.counters["buffer_high_watermark"], max(0, await self.buffer_depth())
        )
        depth = await self.buffer_depth()
        pending = await self.pending_messages()
        sampler_stats = self.sampler.stats
        batch_stats = self.batcher.counters if self.batcher else {}
        storage_worker = self.workers.get("storage")
        storage_stats = storage_worker.stats if storage_worker else {}
        return [
            {
                "stage": "ingestion",
                "label": "Ingestion",
                "incoming": self.counters["spans_received"],
                "processed": self.counters["spans_enqueued"],
                "pending": self.spill_queue.qsize(),
                "failed": self.counters["spans_invalid"],
                "latency_ms": self.counters["ingest_latency_ms"],
                "health": "healthy" if self.buffer is not None else "down",
            },
            {
                "stage": "buffer",
                "label": "Redis Buffer",
                "incoming": self.counters["spans_enqueued"],
                "processed": sum(w.processed_messages for w in self.workers.values() if hasattr(w, "processed_messages")),
                "pending": max(0, depth) + max(0, pending),
                "failed": self.counters["buffer_unavailable"],
                "latency_ms": 0.0,
                "health": "healthy" if self.buffer and await self.buffer.health() else "degraded",
            },
            {
                "stage": "aggregation",
                "label": "Aggregation",
                "incoming": self.counters["spans_enqueued"],
                "processed": self.assembler.counters["spans_accepted"],
                "pending": self.assembler.open_count(),
                "failed": self.assembler.counters["spans_duplicate"],
                "latency_ms": 0.0,
                "health": "healthy",
            },
            {
                "stage": "sampling",
                "label": "Tail Sampling",
                "incoming": sampler_stats["evaluated"],
                "processed": sampler_stats["retained"],
                "pending": self.assembler.open_count(),
                "failed": sampler_stats["discarded"],
                "latency_ms": self.counters["sampling_latency_ms"],
                "health": "healthy",
            },
            {
                "stage": "batching",
                "label": "Batching + gzip",
                "incoming": batch_stats.get("traces_buffered", 0),
                "processed": batch_stats.get("traces_batched", 0),
                "pending": self.batcher.buffered() if self.batcher else 0,
                "failed": 0,
                "latency_ms": 0.0,
                "health": "healthy",
            },
            {
                "stage": "storage",
                "label": "Object Storage",
                "incoming": batch_stats.get("batches_created", 0),
                "processed": storage_stats.get("uploaded", 0),
                "pending": storage_stats.get("pending", 0),
                "failed": storage_stats.get("failed", 0),
                "latency_ms": storage_stats.get("avg_upload_ms", 0.0),
                "health": "healthy" if self.store and await self.store.health() else "degraded",
            },
            {
                "stage": "indexing",
                "label": "PostgreSQL Index" if settings.database_url else "SQLite Index",
                "incoming": self.counters["traces_indexed"],
                "processed": self.counters["traces_indexed"],
                "pending": 0,
                "failed": 0,
                "latency_ms": 0.0,
                "health": "healthy" if self.db.healthy else "degraded",
            },
        ]


class _EMA:
    """Exponential moving average for stage latency displays."""

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha = alpha
        self.value: float | None = None

    def add(self, sample: float) -> float:
        if self.value is None:
            self.value = sample
        else:
            self.value = self.alpha * sample + (1 - self.alpha) * self.value
        return round(self.value, 3)


runtime = Runtime()
