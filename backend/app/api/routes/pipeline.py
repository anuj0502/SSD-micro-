"""Telemetry pipeline health and stage-by-stage statistics."""
from __future__ import annotations

import time
import uuid
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_runtime, require_ready
from app.runtime import Runtime
from app.collector.ingestion import IngestionService, BufferFull
from app.schemas.telemetry import Span

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/stats")
async def pipeline_stats(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_ready(runtime)
    stages = await runtime.stage_snapshot()
    health = await runtime.health()
    degraded = [s["stage"] for s in stages if s["health"] not in {"healthy"}]
    history = await runtime.db.fetchall(
        """
        SELECT stage, ts, processed, failed, pending, latency_ms FROM metrics
        WHERE ts >= ? ORDER BY ts ASC
        """,
        (time.time() - 900,),
    )
    history_by_stage: dict[str, list[dict[str, Any]]] = {}
    for row in history:
        history_by_stage.setdefault(row["stage"], []).append(
            {
                "ts": row["ts"],
                "processed": row["processed"],
                "failed": row["failed"],
                "pending": row["pending"],
                "latency_ms": row["latency_ms"],
            }
        )
    return {
        "stages": stages,
        "health": "degraded" if degraded else "healthy",
        "degraded_stages": degraded,
        "deployment": {"buffer_backend": runtime.buffer.backend if runtime.buffer else "unknown",
                       "storage_backend": runtime.store.backend if runtime.store else "unknown",
                       "database_backend": runtime.db.backend if hasattr(runtime.db, "backend") else "sqlite"},
        "totals": {"spans_received": runtime.counters["spans_received"],
                   "spans_enqueued": runtime.counters["spans_enqueued"],
                   "traces_indexed": runtime.counters["traces_indexed"],
                   "traces_evaluated": runtime.sampler.stats["evaluated"]},
        "queue": {
            "stream_depth": health["queue_depth"],
            "pending_messages": health["pending_messages"],
            "spill_depth": runtime.spill_queue.qsize(),
            "batch_queue": runtime.batch_queue.qsize(),
            "batcher_buffer": runtime.batcher.buffered() if runtime.batcher else 0,
        },
        "workers": {name: worker.status() for name, worker in runtime.workers.items()},
        "history": history_by_stage,
        "components": health["components"],
    }


# Keep the public diagnostic route bounded. A diagnostic sends exactly one
# span and does not modify sampling rules, queues, or collector configuration.
_verify_guard = asyncio.Lock()
_verify_last_started = 0.0


@router.post("/verify", status_code=202)
async def start_pipeline_verification(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Submit one identifiable trace through normal ingestion and worker paths."""
    global _verify_last_started
    require_ready(runtime)
    async with _verify_guard:
        now = time.monotonic()
        if now - _verify_last_started < 20:
            raise HTTPException(status_code=429, detail="Allow 20 seconds between pipeline tests")
        # A slow diagnostic trace is retained by the ordinary tail-sampling
        # policy even when the configured successful-sample rate is zero.
        duration_ms = max(1000.0, float(runtime.sampler.config.slow_threshold_ms) + 100.0)
        end_ns = time.time_ns()
        span = Span(
            trace_id=uuid.uuid4().hex,
            span_id=uuid.uuid4().hex[:16],
            name="pipeline-verification",
            service="traceflow-pipeline-check",
            kind="INTERNAL",
            start_time_unix_nano=end_ns - int(duration_ms * 1_000_000),
            end_time_unix_nano=end_ns,
            status="OK",
            attributes={"traceflow.diagnostic": True, "test.kind": "pipeline-end-to-end"},
        )
        try:
            result = await IngestionService(runtime).ingest([span], source="pipeline-check")
        except BufferFull as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if result.get("accepted") != 1:
            raise HTTPException(status_code=503, detail="Diagnostic span was not accepted by ingestion")
        _verify_last_started = now
    return {
        "trace_id": span.trace_id,
        "state": "accepted",
        "indexed": False,
        "stored": False,
        "message": "Diagnostic span accepted into the ingestion buffer. Awaiting tail sampling and indexing.",
    }


@router.get("/verify/{trace_id}")
async def pipeline_verification_status(trace_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_ready(runtime)
    if len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        raise HTTPException(status_code=400, detail="Invalid trace ID")
    row = await runtime.db.fetchone(
        "SELECT trace_id, root_service, root_operation, sampled, decision, batch_id, object_key "
        "FROM traces WHERE trace_id=?", (trace_id,),
    )
    # Only report success for an actual diagnostic trace. No inferred success
    # from global metrics, process counters or unrelated indexed traces.
    if row is None:
        return {"trace_id": trace_id, "state": "accepted", "indexed": False, "stored": False,
                "message": "Waiting for ingestion worker and the tail-sampling completion window."}
    if row["root_service"] != "traceflow-pipeline-check" or row["root_operation"] != "pipeline-verification":
        raise HTTPException(status_code=404, detail="Not a pipeline diagnostic trace")
    indexed = True
    stored = bool(row["batch_id"] and row["object_key"])
    if row["decision"] == "discarded":
        state, message = "discarded", "Trace indexed but discarded by sampling policy; verify the active sampling configuration."
    elif stored:
        state, message = "stored", "Diagnostic trace indexed in PostgreSQL and its compressed batch was uploaded and linked."
    else:
        state, message = "indexed", "Diagnostic trace indexed in PostgreSQL; waiting for compressed batch upload."
    return {"trace_id": trace_id, "state": state, "indexed": indexed, "stored": stored,
            "sampled": bool(row["sampled"]), "message": message}
