"""Trace search and detail retrieval."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime, parse_time_range, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(
    trace_id: str | None = None,
    service: str | None = None,
    operation: str | None = None,
    status: str | None = Query(None, pattern="^(success|error|slow)$"),
    range: str = Query("6h"),
    since: float | None = None,
    until: float | None = None,
    min_duration_ms: float | None = Query(None, ge=0),
    only_sampled: bool | None = None,
    sort: str = Query("start_time", pattern="^(start_time|duration|span_count)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    start, end = parse_time_range(range, since, until)
    return await runtime.index.search_traces(
        trace_id=trace_id,
        service=service,
        operation=operation,
        status=status,
        since=start,
        until=end,
        min_duration_ms=min_duration_ms,
        only_sampled=only_sampled,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/{trace_id}")
async def get_trace(trace_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    trace = await runtime.index.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"trace '{trace_id}' not found")
    trace["sampling"] = runtime.sampler.snapshot()["config"]
    return trace
