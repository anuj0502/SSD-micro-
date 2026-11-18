"""Telemetry pipeline health and stage-by-stage statistics."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime, require_ready
from app.runtime import Runtime

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
