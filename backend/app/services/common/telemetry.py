"""OpenTelemetry setup shared by the demo microservices.

Uses the standard OTel SDK, FastAPI/HTTPX instrumentation and the OTLP/HTTP
exporter. Trace context propagates automatically between services through the
W3C traceparent header injected by the HTTPX instrumentation.
"""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_telemetry(service_name: str, app=None) -> TracerProvider:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:8000")
    traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", f"{endpoint.rstrip('/')}/v1/traces")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "local"),
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=traces_endpoint, timeout=10)
    # Short delay keeps the demo responsive; real deployments would batch larger.
    provider.add_span_processor(
        BatchSpanProcessor(exporter, max_export_batch_size=256, schedule_delay_millis=400)
    )
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    if app is not None:
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=provider, excluded_urls="health,metrics"
        )
    return provider


def shutdown_telemetry(provider: TracerProvider) -> None:
    provider.shutdown()
