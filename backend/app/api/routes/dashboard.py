"""Overview dashboard aggregates. All values are computed from indexed telemetry."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_runtime, parse_time_range, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
async def overview(
    range: str = Query("1h"),
    since: float | None = None,
    until: float | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    start, end = parse_time_range(range, since, until)
    assert runtime.index is not None
    slow_threshold = runtime.sampler.config.slow_threshold_ms
    metrics = await runtime.index.overview(start, end, slow_threshold)
    services = await runtime.index.service_stats(start, end)
    timeseries = await runtime.index.timeseries(start, end, buckets=24)
    recent = await runtime.index.search_traces(page=1, page_size=6)
    events = await runtime.events.list(limit=8) if runtime.events else []
    sampling = runtime.sampler.snapshot()
    health = await runtime.health()

    return {
        "range": {"key": range, "since": start, "until": end},
        "metrics": metrics,
        "services": services,
        "timeseries": timeseries,
        "recent_traces": recent["items"],
        "recent_events": events,
        "sampling": {
            "config": sampling["config"],
            "retention_rate": sampling["stats"]["retention_rate"],
            "evaluated": sampling["stats"]["evaluated"],
        },
        "pipeline": {
            "queue_depth": health["queue_depth"],
            "pending_messages": health["pending_messages"],
            "buffer": health["components"]["redis"]["status"],
            "storage": health["components"]["minio"]["status"],
        },
        "generated_at": end,
    }


@router.get("/timeseries")
async def timeseries(
    range: str = Query("1h"),
    buckets: int = Query(24, ge=2, le=120),
    since: float | None = None,
    until: float | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    start, end = parse_time_range(range, since, until)
    points = await runtime.index.timeseries(start, end, buckets=buckets)
    return {"range": {"since": start, "until": end, "key": range}, "points": points}
