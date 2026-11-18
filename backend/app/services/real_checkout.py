"""An actual HTTP application instrumented with OpenTelemetry.

This mounted FastAPI app runs inside the same Render web instance as the
collector, but is a separate ASGI app. Every real /checkout HTTP request
records server and business spans, exported as OTLP protobuf to /v1/traces.
No synthetic spans are manufactured by this module.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# DO NOT set a global provider or instrument the collector. That would make
# exporting telemetry recursively generate more telemetry.
port = int(os.getenv("PORT", "8000"))
provider = TracerProvider(resource=Resource.create({
    "service.name": "real-checkout-api",
    "deployment.environment": os.getenv("ENVIRONMENT", "local"),
    "telemetry.source": "real-http-request",
}))
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint=f"http://127.0.0.1:{port}/v1/traces", timeout=8),
    schedule_delay_millis=300,
    max_export_batch_size=64,
))
tracer = provider.get_tracer("traceflow.real_checkout", "1.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        provider.shutdown()


checkout_app = FastAPI(title="TraceFlow Real Checkout API", lifespan=lifespan)
# Instrument ONLY this mounted application, not the parent collector.
FastAPIInstrumentor.instrument_app(checkout_app, tracer_provider=provider, excluded_urls="health")

# Low cost guard for public demo: one request per second per client per process.
_last_request: dict[str, float] = {}


@checkout_app.get("/health")
async def demo_health():
    return {"status": "ok", "type": "genuine-http-instrumented", "service": "real-checkout-api"}


@checkout_app.post("/checkout")
async def checkout(request: Request, scenario: str = Query("success", pattern="^(success|slow|error)$")):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    if now - _last_request.get(ip, 0.0) < 1.0:
        raise HTTPException(status_code=429, detail="Please allow a second between demo requests")
    if len(_last_request) > 2048:
        _last_request.clear()
    _last_request[ip] = now

    order_id = uuid.uuid4().hex[:10]
    # The spans below time ACTUAL Python work and sleeps in response to an
    # incoming browser HTTP request. They are not randomly fabricated timestamps.
    with tracer.start_as_current_span("validate-cart") as span:
        span.set_attribute("demo.scenario", scenario)
        span.set_attribute("demo.order_id", order_id)
        await asyncio.sleep(0.012)

    with tracer.start_as_current_span("reserve-inventory") as span:
        span.set_attribute("inventory.item_count", 2)
        await asyncio.sleep(0.035)

    with tracer.start_as_current_span("process-payment") as span:
        if scenario == "slow":
            await asyncio.sleep(0.75)
        else:
            await asyncio.sleep(0.055)
        if scenario == "error":
            span.set_status(Status(StatusCode.ERROR, "Demo payment declined"))
            span.set_attribute("payment.result", "declined")
            raise HTTPException(status_code=503, detail="Simulated checkout failure: payment declined")
        span.set_attribute("payment.result", "approved")

    with tracer.start_as_current_span("confirm-order"):
        await asyncio.sleep(0.008)

    current = trace.get_current_span()
    context = current.get_span_context()
    return {
        "order_id": order_id,
        "status": "confirmed",
        "scenario": scenario,
        "source": "real-http-request",
        "service": "real-checkout-api",
        "trace_id": format(context.trace_id, "032x") if context.is_valid else None,
        "note": "OpenTelemetry will asynchronously export these measured spans to TraceFlow",
    }
