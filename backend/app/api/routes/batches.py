"""Batch inspection, retry and batching configuration."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/batches", tags=["batches"])


class BatchConfigPayload(BaseModel):
    batch_size: int = Field(..., ge=1, le=10_000)
    flush_interval_s: float = Field(..., ge=0.2, le=300)
    enabled: bool = True


@router.get("")
async def list_batches(
    status: str | None = Query(None, pattern="^(pending|uploading|uploaded|failed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    data = await runtime.index.list_batches(status=status, page=page, page_size=page_size)
    data["live"] = runtime.batcher.snapshot() if runtime.batcher else {}
    data["queue"] = runtime.batch_queue.qsize()
    return data


@router.get("/config")
async def get_batch_config(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.batcher.snapshot() if runtime.batcher else {}


@router.put("/config")
async def update_batch_config(
    payload: BatchConfigPayload, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    if runtime.batcher is None:
        raise HTTPException(status_code=503, detail="batcher not ready")
    runtime.batcher.batch_size = payload.batch_size
    runtime.batcher.flush_interval_s = payload.flush_interval_s
    runtime.batcher.enabled = payload.enabled
    await runtime.db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES ('batch_config', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (
            json.dumps(
                {
                    "batch_size": payload.batch_size,
                    "flush_interval_s": payload.flush_interval_s,
                    "enabled": payload.enabled,
                }
            ),
            time.time(),
        ),
    )
    if runtime.events is not None:
        await runtime.events.add(
            "batch",
            f"Batch policy changed · size {payload.batch_size} · flush {payload.flush_interval_s}s",
            meta=payload.model_dump(),
        )
    return runtime.batcher.snapshot()


@router.post("/flush")
async def flush_batches(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if runtime.batcher is None:
        raise HTTPException(status_code=503, detail="batcher not ready")
    batches = await runtime.batcher.flush(reason="manual")
    if runtime.events is not None:
        await runtime.events.add("batch", f"Manual flush produced {len(batches)} batch(es)")
    return {"flushed": len(batches), "batches": [b.as_dict() for b in batches]}


@router.get("/{batch_id}")
async def batch_detail(batch_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    assert runtime.index is not None
    detail = await runtime.index.batch_detail(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"batch '{batch_id}' not found")
    return detail


@router.post("/{batch_id}/retry")
async def retry_batch(batch_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    rows = await runtime.db.fetchall("SELECT * FROM batches WHERE batch_id = ?", (batch_id,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"batch '{batch_id}' not found")
    worker = runtime.workers.get("storage")
    if worker is None:
        raise HTTPException(status_code=503, detail="storage worker not ready")
    await worker.retry_batch(dict(rows[0]))
    if runtime.events is not None:
        await runtime.events.add("storage", f"Manual retry queued for {batch_id}", level="warning")
    return {"status": "queued", "batch_id": batch_id}
