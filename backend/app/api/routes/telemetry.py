"""OTLP ingestion + manual traffic generation."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_runtime
from app.collector.ingestion import BufferFull, IngestionService
from app.config.settings import settings
from app.runtime import Runtime
from app.schemas.telemetry import parse_otlp_json, parse_otlp_protobuf
from app.services.traffic import emit_synthetic_traces
from app.utils.logging import get_logger

router = APIRouter(tags=["telemetry"])
log = get_logger("traceflow.api.telemetry")


@router.post("/v1/traces")
async def ingest_otlp(request: Request, runtime: Runtime = Depends(get_runtime)) -> Response:
    """OTLP/HTTP trace ingestion (protobuf or JSON)."""
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    spans: list = []
    try:
        if "protobuf" in content_type or content_type == "application/x-protobuf":
            spans = parse_otlp_protobuf(body)
        else:
            import json

            spans = parse_otlp_json(json.loads(body or b"{}"))
    except Exception as exc:
        log.warning("invalid OTLP payload", extra={"error": str(exc), "content_type": content_type})
        raise HTTPException(status_code=400, detail=f"invalid OTLP payload: {exc}") from exc

    service = IngestionService(runtime)
    try:
        await service.ingest(spans, source="otlp")
    except BufferFull as exc:
        return Response(
            status_code=429,
            content='{"error":"buffer_full","message":"ingestion is applying backpressure"}',
            media_type="application/json",
        )
    # OTLP/HTTP expects an ExportTraceServiceResponse body.
    return Response(content="{}", media_type="application/json", status_code=200)


class TrafficRequest(BaseModel):
    traces: int = Field(25, ge=1, le=5000)
    error_probability: float = Field(0.08, ge=0, le=1)
    slow_probability: float = Field(0.12, ge=0, le=1)


@router.post("/api/telemetry/traffic")
async def generate_traffic(payload: TrafficRequest, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    result = await emit_synthetic_traces(
        runtime,
        payload.traces,
        error_probability=payload.error_probability,
        slow_probability=payload.slow_probability,
    )
    if runtime.events is not None:
        await runtime.events.add(
            "telemetry", f"Generated {payload.traces} synthetic traces", meta=result
        )
    return result


@router.get("/api/telemetry/stats")
async def telemetry_stats(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {
        "counters": dict(runtime.counters),
        "spill_queue": {
            "depth": runtime.spill_queue.qsize(),
            "maxsize": settings.local_spill_maxsize,
        },
        "buffer": {
            "backend": runtime.buffer.backend if runtime.buffer else None,
            "depth": await runtime.buffer_depth(),
            "pending": await runtime.pending_messages(),
        },
        "workers": {name: worker.status() for name, worker in runtime.workers.items()},
    }
