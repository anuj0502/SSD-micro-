"""API router assembly."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    batches,
    benchmarks,
    dashboard,
    events,
    faults,
    health,
    live,
    pipeline,
    sampling,
    services,
    storage,
    telemetry,
    traces,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(traces.router)
api_router.include_router(services.router)
api_router.include_router(pipeline.router)
api_router.include_router(sampling.router)
api_router.include_router(batches.router)
api_router.include_router(storage.router)
api_router.include_router(events.router)
api_router.include_router(faults.router)
api_router.include_router(benchmarks.router)
api_router.include_router(live.router)

# OTLP ingestion lives outside /api so standard exporters work unchanged.
ingest_router = APIRouter()
ingest_router.include_router(telemetry.router)
