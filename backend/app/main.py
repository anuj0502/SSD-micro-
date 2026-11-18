"""TraceFlow collector entry point.

The collector is one FastAPI application that exposes:

* OTLP/HTTP ingestion (``POST /v1/traces``)
* the dashboard REST API (``/api/*``)
* a live WebSocket feed (``/api/ws/live``)

Background workers (ingestion, processing, storage, spill, metrics) run inside
the same process; they are supervised tasks, not extra containers, so a crash
of the process is a crash of the collector.
"""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from app.api.router import api_router, ingest_router
from app.api.routes import telemetry as telemetry_routes  # noqa: F401  (route registration order)
from app.collector.faults import FaultController
from app.collector.recovery import run_startup_recovery
from app.config.settings import settings
from app.runtime import Runtime, runtime as global_runtime
from app.services.benchmarks import BenchmarkRunner
from app.utils.logging import configure_logging, get_logger

configure_logging()
log = get_logger("traceflow.main")


def create_app(
    enable_workers: bool = True,
    runtime_override: Runtime | None = None,
    run_recovery: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime: Runtime = app.state.runtime
        await runtime.start(enable_workers=enable_workers)
        runtime.faults = FaultController(runtime)
        runtime.benchmarks = BenchmarkRunner(runtime)
        recovery_task = None
        if run_recovery:
            recovery_task = asyncio.create_task(run_startup_recovery(runtime), name="startup-recovery")
        log.info(
            "collector ready",
            extra={
                "buffer_backend": runtime.buffer.backend if runtime.buffer else None,
                "object_store_backend": runtime.store.backend if runtime.store else None,
                "workers": enable_workers,
            },
        )
        try:
            yield
        finally:
            if recovery_task is not None:
                recovery_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await recovery_task
            if getattr(runtime, "faults", None):
                await runtime.faults.stop_all()
            if getattr(runtime, "benchmarks", None):
                await runtime.benchmarks.stop_all()
            await runtime.stop()
            log.info("collector stopped")

    app = FastAPI(
        title="TraceFlow — Distributed Tracing & Telemetry Intelligence Platform",
        version="1.0.0",
        description=(
            "Custom OTLP collector with trace aggregation, tail-based sampling, "
            "batched gzip storage and PostgreSQL trace indexing."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runtime = runtime_override or global_runtime
    app.state.enable_workers = enable_workers

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    app.include_router(ingest_router)

    @app.get("/", include_in_schema=False)
    async def root():
        frontend_index = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return {
            "service": "TraceFlow Collector",
            "status": "running",
            "docs": "/api/docs",
            "ingest": "POST /v1/traces (OTLP/HTTP)",
        }

    # Render serves the prebuilt React SPA from the same origin as HTTP and WS APIs.
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.is_dir():
        @app.get("/{full_path:path}", include_in_schema=False)
        async def react_app(full_path: str):
            requested = (frontend_dist / full_path).resolve()
            if requested.is_file() and frontend_dist.resolve() in requested.parents:
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "detail": str(exc)})

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
