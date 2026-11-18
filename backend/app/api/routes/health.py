"""Collector health and system status."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.config.settings import settings
from app.runtime import Runtime

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    data = await runtime.health()
    stats = await runtime.db.fetchone(
        "SELECT COUNT(*) AS traces, COALESCE(SUM(span_count),0) AS spans FROM traces"
    )
    return {
        **data,
        "service": settings.app_name,
        "version": "1.0.0",
        "environment": settings.environment,
        "demo": {"enabled": settings.auto_demo_enabled, "source": "synthetic" if settings.auto_demo_enabled else None},
        "timestamp": time.time(),
        "real_demo": {"enabled": settings.real_demo_enabled, "endpoint": "/demo-app/checkout" if settings.real_demo_enabled else None},
        "telemetry": {
            "traces_indexed": int(stats["traces"] or 0) if stats else 0,
            "spans_indexed": int(stats["spans"] or 0) if stats else 0,
            "config": {
                "buffer_backend": runtime.buffer.backend if runtime.buffer else None,
                "object_store_backend": runtime.store.backend if runtime.store else None,
            },
        },
    }
