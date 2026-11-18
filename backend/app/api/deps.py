"""Shared API dependencies."""
from __future__ import annotations

import time

from fastapi import HTTPException, Request

from app.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="collector runtime is not initialised")
    return runtime


def require_ready(runtime: Runtime) -> Runtime:
    if not runtime.ready:
        raise HTTPException(status_code=503, detail="collector is still starting")
    return runtime


RANGE_SECONDS = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
}


def parse_time_range(
    range_key: str | None = "1h", since: float | None = None, until: float | None = None
) -> tuple[float, float]:
    now = until or time.time()
    if since is not None:
        return since, now
    seconds = RANGE_SECONDS.get(range_key or "1h", 3600)
    return now - seconds, now


async def local_only() -> None:
    from app.config.settings import settings

    if settings.environment.lower() not in {"local", "development", "test"}:
        raise HTTPException(
            status_code=403, detail="fault injection is only available in the local environment"
        )
