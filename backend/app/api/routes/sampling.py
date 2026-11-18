"""Tail-based sampling policy management and statistics."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, require_ready
from app.collector.sampling import SamplingConfig
from app.runtime import Runtime

router = APIRouter(prefix="/api/sampling", tags=["sampling"])


class SamplingConfigPayload(BaseModel):
    error_rate: float = Field(..., ge=0, le=1)
    slow_threshold_ms: float = Field(..., ge=0, le=600_000)
    success_rate: float = Field(..., ge=0, le=1)
    completion_timeout_s: float = Field(..., ge=0.1, le=300)
    late_policy: str = Field(..., pattern="^(drop|accept_if_buffered)$")
    deterministic: bool = True


@router.get("/config")
async def get_config(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {"config": runtime.sampler.config.as_dict(), "policy": runtime.sampler.describe_policy()}


@router.put("/config")
async def update_config(
    payload: SamplingConfigPayload, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    previous = runtime.sampler.config.as_dict()
    try:
        new_config = SamplingConfig(**payload.model_dump())
        new_config.validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    runtime.sampler.config = new_config
    await runtime.db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES ('sampling_config', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (json.dumps(new_config.as_dict()), time.time()),
    )
    if runtime.events is not None:
        await runtime.events.add(
            "sampling",
            f"Sampling policy changed · success {new_config.success_rate * 100:.0f}% · "
            f"slow ≥ {new_config.slow_threshold_ms:.0f} ms",
            meta={"previous": previous, "current": new_config.as_dict()},
        )
    return {"config": new_config.as_dict(), "policy": runtime.sampler.describe_policy()}


@router.get("/stats")
async def sampling_stats(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_ready(runtime)
    snapshot = runtime.sampler.snapshot()

    # Persisted impact: how much storage was avoided by discarding traces.
    totals = await runtime.db.fetchone(
        """
        SELECT COUNT(*) AS evaluated,
               SUM(CASE WHEN sampled=1 THEN 1 ELSE 0 END) AS retained,
               SUM(CASE WHEN has_error=1 THEN 1 ELSE 0 END) AS errors,
               SUM(CASE WHEN has_error=1 AND sampled=1 THEN 1 ELSE 0 END) AS errors_retained,
               SUM(CASE WHEN status='slow' THEN 1 ELSE 0 END) AS slow,
               SUM(CASE WHEN status='slow' AND sampled=1 THEN 1 ELSE 0 END) AS slow_retained,
               SUM(CASE WHEN status='success' AND sampled=1 THEN 1 ELSE 0 END) AS success_sampled,
               SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_total
        FROM traces
        """
    )
    storage = await runtime.db.fetchone(
        "SELECT COALESCE(SUM(compressed_bytes),0) AS compressed, COALESCE(SUM(trace_count),0) AS traces FROM batches WHERE status='uploaded'"
    )
    persisted = {k: int(totals[k] or 0) for k in totals.keys()} if totals else {}
    compressed = int(storage["compressed"] or 0) if storage else 0
    stored_traces = int(storage["traces"] or 0) if storage else 0
    per_trace = (compressed / stored_traces) if stored_traces else 0
    evaluated = persisted.get("evaluated", 0)

    return {
        **snapshot,
        "persisted": persisted,
        "storage": {
            "compressed_bytes": compressed,
            "stored_traces": stored_traces,
            "avg_bytes_per_trace": round(per_trace, 1),
            "estimated_bytes_without_sampling": round(per_trace * evaluated, 1),
            "estimated_bytes_saved": round(per_trace * (evaluated - stored_traces), 1),
            "reduction_pct": round((1 - stored_traces / evaluated) * 100, 2) if evaluated else 0,
        },
        "workers": runtime.workers["processing"].status() if "processing" in runtime.workers else {},
    }


@router.post("/reset-stats")
async def reset_stats(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    runtime.sampler.reset()
    if runtime.events is not None:
        await runtime.events.add("sampling", "Sampling statistics reset")
    return {"status": "ok"}
