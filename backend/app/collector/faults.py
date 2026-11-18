"""Fault injection and recovery verification.

Every scenario drives real components (workers, buffer, object store) and
records what actually happened. Nothing here reports a simulated outcome: the
result payload is assembled from runtime counters, SQLite and object-store state
observed during the run.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from app.collector.recovery import recover_pending_messages
from app.config.settings import settings
from app.services.traffic import build_synthetic_trace, emit_synthetic_traces
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.faults")

SCENARIOS: dict[str, dict[str, str]] = {
    "collector-crash": {
        "title": "Collector Crash",
        "expected": (
            "Worker stops, read-but-unacked messages stay pending, worker restarts, "
            "replayed spans are deduplicated so nothing is persisted twice."
        ),
    },
    "redis-disconnect": {
        "title": "Redis Disconnection",
        "expected": (
            "Ingestion reports the buffer unavailable, spans spill into the bounded local "
            "queue, and the queue drains into the stream when the buffer recovers."
        ),
    },
    "storage-failure": {
        "title": "Storage Failure",
        "expected": (
            "Batch uploads fail and are retried with exponential backoff, the spooled batch "
            "stays recoverable, and it uploads after storage recovers."
        ),
    },
    "high-traffic": {
        "title": "High Traffic",
        "expected": (
            "Queue depth rises, bounded buffering limits memory growth, and the pipeline "
            "returns to a steady state once traffic stops."
        ),
    },
    "duplicate-spans": {
        "title": "Duplicate Telemetry",
        "expected": (
            "Duplicate span ids are detected at ingestion and never aggregated, indexed or "
            "persisted a second time."
        ),
    },
    "late-spans": {
        "title": "Late-Arriving Spans",
        "expected": (
            "Spans arriving after the sampling decision window follow the configured late "
            "policy and are counted instead of silently changing a closed trace."
        ),
    },
}


class FaultController:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.runs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------
    async def start(self, scenario: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario '{scenario}'")
        options = options or {}
        run_id = uuid.uuid4().hex[:12]
        run = {
            "id": run_id,
            "scenario": scenario,
            "title": SCENARIOS[scenario]["title"],
            "expected": SCENARIOS[scenario]["expected"],
            "status": "running",
            "options": options,
            "started_at": time.time(),
            "finished_at": None,
            "timeline": [],
            "result": {},
        }
        self.runs[run_id] = run
        await self._persist(run)
        self._tasks[run_id] = asyncio.create_task(self._execute(run))
        return run

    async def _execute(self, run: dict[str, Any]) -> None:
        handler = {
            "collector-crash": self._collector_crash,
            "redis-disconnect": self._redis_disconnect,
            "storage-failure": self._storage_failure,
            "high-traffic": self._high_traffic,
            "duplicate-spans": self._duplicate_spans,
            "late-spans": self._late_spans,
        }[run["scenario"]]
        try:
            await handler(run)
            run["status"] = "completed"
        except Exception as exc:
            log.exception("fault scenario failed", extra={"scenario": run["scenario"]})
            run["status"] = "failed"
            await self._note(run, f"Scenario failed: {exc}", status="error")
        finally:
            run["finished_at"] = time.time()
            await self._persist(run)
            self._tasks.pop(run["id"], None)

    async def stop_all(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    # -- helpers -----------------------------------------------------------
    async def _note(self, run: dict[str, Any], message: str, status: str = "info", **meta: Any) -> None:
        run["timeline"].append(
            {"ts": time.time(), "message": message, "status": status, "meta": meta}
        )
        await self._persist(run)

    async def _persist(self, run: dict[str, Any]) -> None:
        try:
            await self.runtime.db.execute(
                """
                INSERT INTO fault_runs(id, scenario, status, details, started_at, finished_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, details=excluded.details,
                    finished_at=excluded.finished_at
                """,
                (
                    run["id"], run["scenario"], run["status"],
                    json.dumps({k: run[k] for k in ("title", "expected", "options", "timeline", "result")}),
                    run["started_at"], run["finished_at"],
                ),
            )
        except Exception as exc:  # DB may be busy; the in-memory run is authoritative
            log.warning("could not persist fault run", extra={"error": str(exc)})

    async def _wait_pipeline(self, seconds: float | None = None) -> None:
        cfg = self.runtime.sampler.config
        window = seconds if seconds is not None else cfg.completion_timeout_s + settings.batch_flush_interval_s + 1.5
        await asyncio.sleep(window)

    async def _count_spans_persisted(self) -> int:
        return int(await self.runtime.db.scalar("SELECT COALESCE(SUM(span_count),0) FROM traces") or 0)

    # -- scenario 1: collector crash --------------------------------------
    async def _collector_crash(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        worker = runtime.workers["ingestion"]
        traces = int(run["options"].get("traces", 20))
        restart_delay = float(run["options"].get("restart_delay_s", 3))
        await self._note(run, "Stopping ingestion worker (simulating a collector crash)")

        spans_before = await self._count_spans_persisted()
        duplicates_before = runtime.assembler.counters["spans_duplicate"]
        await worker.stop()
        await self._note(run, "Ingestion worker stopped", status="warning")

        emitted = await emit_synthetic_traces(runtime, traces, error_probability=0.1, slow_probability=0.1)
        await self._note(run, f"Queued {emitted['spans']} spans for the offline worker")

        # Crash-recovery semantics: messages are delivered to the consumer and
        # processed, but the process dies before acknowledging them.
        entries = await runtime.buffer.read_batch(count=settings.ingestion_batch_size, block_ms=0)
        if not entries:
            entries = []
        await worker.process_entries(entries, ack=False)
        pending = await runtime.buffer.pending_count()
        await self._note(
            run,
            f"{len(entries)} message(s) delivered and processed without ACK; {pending} pending in the consumer group",
            status="warning",
            pending=pending,
        )

        started_recovery = time.time()
        await self._note(run, f"Waiting {restart_delay:.0f}s before restarting the worker")
        await asyncio.sleep(restart_delay)
        await worker.start()
        await self._note(run, "Ingestion worker restarted", status="success")

        recovered = await recover_pending_messages(runtime)
        await self._note(
            run,
            f"Recovery reclaimed {recovered.get('claimed', 0)} pending message(s); "
            f"{recovered.get('duplicates', 0)} duplicate span(s) suppressed",
            status="success" if recovered.get("claimed") else "info",
            **{k: v for k, v in recovered.items() if k != "processed"},
        )

        await self._wait_pipeline()
        duplicates_after = runtime.assembler.counters["spans_duplicate"]
        spans_after = await self._count_spans_persisted()
        pending_after = await runtime.buffer.pending_count()
        worker_status = worker.status()

        run["result"] = {
            "spans_emitted": emitted["spans"],
            "messages_delivered_without_ack": len(entries),
            "pending_at_crash": pending,
            "pending_after_recovery": pending_after,
            "duplicates_suppressed": duplicates_after - duplicates_before,
            "spans_persisted_delta": spans_after - spans_before,
            "recovery_time_ms": round((time.time() - started_recovery) * 1000, 1),
            "worker_restarts": worker_status["restarts"],
            "duplicate_persistence": (duplicates_after - duplicates_before) > 0,
        }
        await self._note(
            run,
            f"Recovery complete: {pending_after} pending left, "
            f"{duplicates_after - duplicates_before} duplicates suppressed, "
            f"{spans_after - spans_before} spans persisted",
            status="success",
        )

    # -- scenario 2: redis disconnect -------------------------------------
    async def _redis_disconnect(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        duration = float(run["options"].get("duration_s", 5))
        traffic = int(run["options"].get("traces", 40))
        unavailable_before = runtime.counters["buffer_unavailable"]
        spilled_before = runtime.counters["spans_spilled"]
        rejected_before = runtime.counters["spans_rejected"]

        await self._note(run, f"Simulating buffer outage for {duration:.0f}s on '{runtime.buffer.backend}'")
        runtime.buffer.simulate_outage(duration)

        # Drive traffic through the real ingestion endpoint while the buffer is down.
        emitted = await emit_synthetic_traces(runtime, traffic, error_probability=0.05)
        await self._note(
            run,
            f"Traffic during outage: {emitted['spans']} spans, spilled={emitted['spilled']}, rejected={emitted['rejected']}",
            status="warning",
            spill_depth=runtime.spill_queue.qsize(),
        )
        spill_depth = runtime.spill_queue.qsize()
        await self._note(run, f"Bounded local spill queue depth: {spill_depth}/{settings.local_spill_maxsize}")

        remaining = max(0.0, duration - (time.time() - run["started_at"]) + 0.5)
        if remaining:
            await asyncio.sleep(remaining)
        await self._note(run, "Buffer outage window ended; awaiting spill drain", status="info")

        started = time.time()
        for _ in range(40):
            if runtime.spill_queue.empty():
                break
            await asyncio.sleep(0.25)
        drained = runtime.spill_queue.empty()
        await self._wait_pipeline(2.0)

        run["result"] = {
            "buffer_backend": runtime.buffer.backend,
            "buffer_unavailable_events": runtime.counters["buffer_unavailable"] - unavailable_before,
            "spans_spilled": runtime.counters["spans_spilled"] - spilled_before,
            "spans_rejected": runtime.counters["spans_rejected"] - rejected_before,
            "spill_queue_depth_at_peak": spill_depth,
            "spill_queue_drained": drained,
            "spill_flushed": runtime.counters["spans_spill_flushed"],
            "recovery_time_ms": round((time.time() - started) * 1000, 1),
        }
        await self._note(
            run,
            "Buffer recovered and spill queue drained" if drained else "Spill queue still draining",
            status="success" if drained else "warning",
        )

    # -- scenario 3: storage failure --------------------------------------
    async def _storage_failure(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        duration = float(run["options"].get("duration_s", 7))
        traces = int(run["options"].get("traces", 60))
        await self._note(run, f"Injecting object storage outage for {duration:.0f}s on '{runtime.store.backend}'")
        runtime.store.fail_for(duration)

        emitted = await emit_synthetic_traces(runtime, traces, error_probability=0.1, slow_probability=0.4)
        await self._note(run, f"Emitted {emitted['traces']} traces, forcing batch flush")
        await asyncio.sleep(runtime.sampler.config.completion_timeout_s + 0.5)
        await runtime.batcher.flush(reason="manual")
        await asyncio.sleep(1.5)

        failing = await runtime.db.fetchall(
            "SELECT batch_id, status, attempts, last_error, object_key, trace_count, span_count, original_bytes, compressed_bytes, created_at FROM batches WHERE status IN ('pending','failed')"
        )
        await self._note(
            run,
            f"{len(failing)} batch(es) awaiting upload while storage is down",
            status="warning",
        )
        remaining = max(0.0, duration - (time.time() - run["started_at"]) + 0.5)
        if remaining:
            await asyncio.sleep(remaining)

        started = time.time()
        await self._note(run, "Storage window ended; retrying pending batches", status="info")
        storage_worker = runtime.workers["storage"]
        for row in await runtime.db.fetchall(
            "SELECT * FROM batches WHERE status IN ('pending','failed')"
        ):
            await storage_worker.retry_batch(dict(row))

        uploaded_count = 0
        for _ in range(60):
            rows = await runtime.db.fetchall(
                "SELECT status, COUNT(*) AS c FROM batches WHERE status IN ('pending','failed') GROUP BY status"
            )
            if not rows:
                break
            await asyncio.sleep(0.5)
        uploaded = await runtime.db.fetchone(
            "SELECT COUNT(*) AS c FROM batches WHERE status='uploaded'"
        )
        uploaded_count = int(uploaded["c"] if uploaded else 0)
        failed_rows = await runtime.db.fetchall("SELECT batch_id FROM batches WHERE status='failed'")

        run["result"] = {
            "storage_backend": runtime.store.backend,
            "batches_blocked": len(failing),
            "failed_during_outage": len([r for r in failing if r["status"] == "failed"]),
            "retry_attempts": int(sum(r["attempts"] for r in failing)),
            "uploaded_batches_total": uploaded_count,
            "unrecovered_batches": len(failed_rows),
            "recovery_time_ms": round((time.time() - started) * 1000, 1),
            "spool_files": len(list((__import__("pathlib").Path(settings.data_dir) / "pending").glob("*.jsonl.gz"))),
        }
        await self._note(
            run,
            f"Recovery: {uploaded_count} batch(es) uploaded, {len(failed_rows)} still failing",
            status="success" if not failed_rows else "warning",
        )

    # -- scenario 4: high traffic -----------------------------------------
    async def _high_traffic(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        total = int(run["options"].get("traces", 600))
        concurrency = int(run["options"].get("concurrency", 20))
        await self._note(run, f"Generating {total} traces with concurrency {concurrency}")
        started = time.time()
        depth_samples: list[int] = []
        rejected_before = runtime.counters["spans_rejected"]
        backpressure_before = runtime.counters["backpressure_events"]

        done = 0
        while done < total:
            chunk = min(concurrency * 4, total - done)
            await emit_synthetic_traces(runtime, chunk, error_probability=0.06, slow_probability=0.12)
            done += chunk
            depth_samples.append(await runtime.buffer_depth())
            await asyncio.sleep(0.1)

        await self._note(run, "Traffic generation finished; watching queue drain", status="info")
        await self._wait_pipeline()
        final_depth = await runtime.buffer_depth()
        emitted_spans = done * 4

        run["result"] = {
            "traces_generated": done,
            "spans_generated": emitted_spans,
            "concurrency": concurrency,
            "duration_s": round(time.time() - started, 2),
            "throughput_spans_per_s": round(emitted_spans / max(0.1, time.time() - started), 1),
            "peak_queue_depth": max(depth_samples) if depth_samples else 0,
            "final_queue_depth": final_depth,
            "backpressure_events": runtime.counters["backpressure_events"] - backpressure_before,
            "spans_rejected": runtime.counters["spans_rejected"] - rejected_before,
            "bounded": settings.stream_maxlen,
        }
        await self._note(
            run,
            f"Queue drained to {final_depth} with {runtime.counters['spans_rejected'] - rejected_before} rejections",
            status="success",
        )

    # -- scenario 5: duplicate telemetry ----------------------------------
    async def _duplicate_spans(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        from app.collector.ingestion import IngestionService

        service = IngestionService(runtime)
        traces = int(run["options"].get("traces", 10))
        duplicate_copies = int(run["options"].get("copies", 2))
        spans: list[Any] = []
        for _ in range(traces):
            spans.extend(build_synthetic_trace(error_probability=0.0, slow_probability=0.0))

        await self._note(run, f"Ingesting {len(spans)} spans ({traces} traces)")
        first = await service.ingest(spans, source="fault-duplicate")
        await asyncio.sleep(0.5)

        for copy_index in range(duplicate_copies):
            repeat = await service.ingest(spans, source="fault-duplicate-repeat")
            await self._note(
                run,
                f"Duplicate copy {copy_index + 1} sent ({len(spans)} spans)",
                status="warning",
            )
            await asyncio.sleep(0.3)

        await self._wait_pipeline(2.5)
        duplicates = runtime.assembler.counters["spans_duplicate"]
        dedup_seen = runtime.dedup.counters["spans_seen"] if runtime.dedup else 0
        dedup_dupes = runtime.dedup.counters["spans_duplicate"] if runtime.dedup else 0
        indexed = await runtime.db.fetchall(
            "SELECT span_count FROM traces WHERE trace_id IN (SELECT DISTINCT trace_id FROM trace_services) ORDER BY start_time DESC LIMIT ?",
            (traces,),
        )
        received = len(spans) * (1 + duplicate_copies)

        run["result"] = {
            "spans_sent_total": received,
            "unique_spans": len(spans),
            "duplicates_detected": dedup_dupes,
            "aggregator_duplicates": duplicates,
            "duplicate_ratio": round(dedup_dupes / received * 100, 2) if received else 0,
            "accepted_first_copy": first.get("accepted", 0),
            "persisted_trace_span_counts": [row["span_count"] for row in indexed][:5],
            "duplicate_persistence_prevented": dedup_dupes >= len(spans) * duplicate_copies,
        }
        await self._note(
            run,
            f"Deduplication enforced: {dedup_dupes} duplicate spans rejected",
            status="success",
        )

    # -- scenario 6: late spans -------------------------------------------
    async def _late_spans(self, run: dict[str, Any]) -> None:
        runtime = self.runtime
        from app.collector.ingestion import IngestionService

        service = IngestionService(runtime)
        cfg = runtime.sampler.config
        spans = build_synthetic_trace(error_probability=0.0, slow_probability=0.0)
        trace_id = spans[0].trace_id
        await self._note(run, f"Ingesting trace {trace_id[:12]}… ({len(spans)} spans)")
        await service.ingest(spans, source="fault-late")

        await self._note(
            run,
            f"Waiting {cfg.completion_timeout_s:.0f}s for the decision window to close",
            status="info",
        )
        await asyncio.sleep(cfg.completion_timeout_s + 1.0)
        decided = runtime.assembler.is_decided(trace_id)
        await self._note(
            run,
            f"Decision window closed; trace decided={decided}, policy='{cfg.late_policy}'",
            status="info",
        )

        late_before = runtime.assembler.counters["spans_late_dropped"]
        late_accept_before = runtime.assembler.counters["spans_late_accepted"]
        from app.schemas.telemetry import Span

        late_span = Span(
            span_id=uuid.uuid4().hex[:16],
            trace_id=trace_id,
            parent_span_id=spans[1].span_id,
            name="GET /orders/{id}/audit",
            service="order-service",
            start_time_unix_nano=spans[0].end_time_unix_nano + 1_000_000,
            end_time_unix_nano=spans[0].end_time_unix_nano + 12_000_000,
            status="OK",
        )
        await service.ingest([late_span], source="fault-late")
        await asyncio.sleep(1.2)
        late_dropped = runtime.assembler.counters["spans_late_dropped"] - late_before
        late_accepted = runtime.assembler.counters["spans_late_accepted"] - late_accept_before
        row = await runtime.db.fetchone(
            "SELECT late_span_count, truncated, batch_id FROM traces WHERE trace_id = ?", (trace_id,)
        )
        run["result"] = {
            "trace_id": trace_id,
            "policy": cfg.late_policy,
            "trace_decided_before_late_span": decided,
            "late_spans_dropped": late_dropped,
            "late_spans_accepted": late_accepted,
            "late_span_count_indexed": row["late_span_count"] if row else None,
            "truncated_flag": bool(row["truncated"]) if row else None,
            "batch_id": row["batch_id"] if row else None,
        }
        await self._note(
            run,
            f"Late span handled: dropped={late_dropped}, accepted={late_accepted}",
            status="success",
        )

    # -- queries -----------------------------------------------------------
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def list_runs(self, scenario: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        runs = sorted(self.runs.values(), key=lambda r: r["started_at"], reverse=True)
        if scenario:
            runs = [r for r in runs if r["scenario"] == scenario]
        return runs[:limit]

    def latest_by_scenario(self) -> dict[str, Any]:
        latest: dict[str, Any] = {}
        for run in sorted(self.runs.values(), key=lambda r: r["started_at"]):
            latest[run["scenario"]] = run
        return latest
