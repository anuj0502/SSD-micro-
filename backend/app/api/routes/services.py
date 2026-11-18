"""Observed service catalog, dependency graph and per-service metrics."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime, parse_time_range, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("")
async def list_services(
    range: str = Query("1h"),
    since: float | None = None,
    until: float | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    start, end = parse_time_range(range, since, until)
    services = await runtime.index.service_stats(start, end)
    edges = await runtime.index.service_edges(start, end)
    return {
        "range": {"since": start, "until": end, "key": range},
        "services": services,
        "edges": edges,
        "total_services": len(services),
    }


@router.get("/{service_name}")
async def service_detail(
    service_name: str,
    range: str = Query("1h"),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    start, end = parse_time_range(range)
    detail = await runtime.index.service_detail(service_name, start, end)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"service '{service_name}' has no observed telemetry")
    traces = await runtime.index.search_traces(service=service_name, since=start, until=end, page_size=8)
    detail["recent_traces"] = traces["items"]
    return detail
