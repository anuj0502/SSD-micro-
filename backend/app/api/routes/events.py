"""System event feed."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_runtime, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    limit: int = Query(40, ge=1, le=200),
    hours: float = Query(24, ge=0.1, le=720),
    category: str | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.events is not None
    events = await runtime.events.list(limit=limit, since=time.time() - hours * 3600, category=category)
    return {"items": events, "total": len(events)}


@router.get("/categories")
async def event_categories(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    rows = await runtime.db.fetchall(
        "SELECT category, COUNT(*) AS c FROM events GROUP BY category ORDER BY c DESC"
    )
    return {"categories": [{"category": row["category"], "count": row["c"]} for row in rows]}
