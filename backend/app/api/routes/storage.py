"""Object storage + PostgreSQL index statistics and object inspection."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime, require_ready
from app.runtime import Runtime

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/stats")
async def storage_stats(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_ready(runtime)
    assert runtime.index is not None
    stats = await runtime.index.storage_stats()
    try:
        objects = await runtime.store.list_objects("data/batches/")
        object_bytes = sum(o["size"] for o in objects)
        object_error = None
    except Exception as exc:
        objects = []
        object_bytes = 0
        object_error = str(exc)

    tables = {}
    for table in ("traces", "trace_services", "trace_edges", "seen_spans", "batches", "events", "metrics"):
        tables[table] = int(await runtime.db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)

    return {
        **stats,
        "objects": len(objects),
        "object_bytes": object_bytes,
        "object_store_error": object_error,
        "tables": tables,
        "indexes": [
            "traces(trace_id) PK",
            "traces(start_time DESC)",
            "traces(status, start_time DESC)",
            "traces(root_service, start_time DESC)",
            "traces(batch_id)",
            "trace_services(service)",
            "trace_edges(parent_service, child_service)",
            "seen_spans(span_id) PK",
            "batches(status, created_at DESC)",
        ],
        "retrieval_path": [
            "1. Search trace metadata in PostgreSQL (indexed trace_id / service / status / time).",
            "2. Read batch_id + object_key for the matching trace.",
            "3. Download the gzip JSONL batch from object storage.",
            "4. Decompress, parse JSONL and extract the requested trace's spans.",
        ],
    }


@router.get("/objects")
async def list_objects(
    prefix: str = Query("data/batches/"),
    limit: int = Query(50, ge=1, le=500),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_ready(runtime)
    try:
        objects = await runtime.store.list_objects(prefix)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"object storage unavailable: {exc}") from exc
    objects.sort(key=lambda o: o.get("last_modified") or 0, reverse=True)
    return {
        "backend": runtime.store.backend,
        "prefix": prefix,
        "total": len(objects),
        "objects": objects[:limit],
    }


@router.get("/objects/inspect")
async def inspect_object(
    key: str = Query(..., min_length=3),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    """Download and decode a stored batch (used by the storage page)."""
    require_ready(runtime)
    from app.collector.compression import decode_jsonl, decompress_bytes

    if not key.startswith("data/batches/"):
        raise HTTPException(status_code=400, detail="only telemetry batch objects can be inspected")
    try:
        blob = await runtime.store.get_object(key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="object not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"object storage unavailable: {exc}") from exc
    entries = decode_jsonl(decompress_bytes(blob))
    return {
        "key": key,
        "compressed_bytes": len(blob),
        "entries": len(entries),
        "sample": entries[0] if entries else None,
        "trace_ids": [e.get("trace_id") for e in entries][:50],
    }
