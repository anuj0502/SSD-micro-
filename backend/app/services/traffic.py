"""Synthetic e-commerce trace generation.

Used when the demo microservices are not running (local mode) and by the fault
lab to create traffic on demand. Traces mirror the real service topology:

    api-gateway -> order-service -> payment-service
                                 -> inventory-service

Every span carries a shared trace id and correct parent/child span ids, so the
collector's aggregation, sampling and waterfall logic exercise the same paths as
real OpenTelemetry traffic.
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Any

from app.schemas.telemetry import Span, SpanEvent

SERVICES = ["api-gateway", "order-service", "payment-service", "inventory-service"]
OPERATIONS = {
    "api-gateway": ["POST /checkout", "GET /cart", "GET /catalog"],
    "order-service": ["POST /orders", "GET /orders/{id}"],
    "payment-service": ["POST /payments/authorize"],
    "inventory-service": ["POST /inventory/reserve"],
}


def _span_id() -> str:
    return uuid.uuid4().hex[:16]


def _trace_id() -> str:
    return uuid.uuid4().hex


def build_synthetic_trace(
    error_probability: float = 0.05,
    slow_probability: float = 0.08,
    clock_skew_s: float = 0.0,
) -> list[Span]:
    trace_id = _trace_id()
    now_ns = int((time.time() + clock_skew_s) * 1e9)
    is_error = random.random() < error_probability
    is_slow = random.random() < slow_probability

    gateway_ms = random.uniform(620, 1400) if is_slow else random.uniform(45, 320)
    base = now_ns

    def make(
        service: str,
        name: str,
        start_ns: int,
        duration_ms: float,
        parent: str | None,
        status: str = "OK",
        status_message: str = "",
        attributes: dict[str, Any] | None = None,
        events: list[SpanEvent] | None = None,
    ) -> Span:
        span_id = _span_id()
        return Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent,
            name=name,
            service=service,
            kind="SERVER" if parent is None else "CLIENT",
            start_time_unix_nano=start_ns,
            end_time_unix_nano=start_ns + int(duration_ms * 1e6),
            status=status,
            status_message=status_message,
            attributes={"http.route": name, "deployment.environment": "local", **(attributes or {})},
            events=events or [],
        )

    gateway_status = "ERROR" if (is_error and random.random() < 0.5) else "OK"
    gateway_events = []
    if gateway_status == "ERROR":
        gateway_events.append(
            SpanEvent(
                name="exception",
                time_unix_nano=base + int(gateway_ms * 0.9 * 1e6),
                attributes={"exception.type": "UpstreamError", "exception.message": "payment declined"},
            )
        )
    root = make(
        "api-gateway",
        random.choice(OPERATIONS["api-gateway"]),
        base,
        gateway_ms,
        None,
        status=gateway_status,
        status_message="payment declined" if gateway_status == "ERROR" else "",
        attributes={"http.status_code": 500 if gateway_status == "ERROR" else 200, "http.method": "POST"},
        events=gateway_events,
    )

    order_ms = gateway_ms * random.uniform(0.7, 0.95)
    order_start = base + int(gateway_ms * 0.02 * 1e6)
    payment_error = is_error
    order = make(
        "order-service",
        random.choice(OPERATIONS["order-service"]),
        order_start,
        order_ms,
        root.span_id,
        status="ERROR" if payment_error and random.random() < 0.7 else "OK",
        status_message="downstream payment failure" if payment_error else "",
        attributes={"http.status_code": 502 if payment_error else 201, "order.items": random.randint(1, 5)},
    )

    payment_ms = order_ms * random.uniform(0.35, 0.8)
    payment_start = order_start + int(order_ms * 0.08 * 1e6)
    payment = make(
        "payment-service",
        "POST /payments/authorize",
        payment_start,
        payment_ms,
        order.span_id,
        status="ERROR" if payment_error else "OK",
        status_message="card declined" if payment_error else "",
        attributes={
            "http.status_code": 402 if payment_error else 200,
            "payment.amount": round(random.uniform(10, 480), 2),
            "payment.provider": "stripe-sim",
        },
        events=[
            SpanEvent(
                name="payment.declined" if payment_error else "payment.authorized",
                time_unix_nano=payment_start + int(payment_ms * 0.6 * 1e6),
                attributes={"payment.status": "declined" if payment_error else "authorized"},
            )
        ],
    )

    inventory_ms = order_ms * random.uniform(0.1, 0.3)
    inventory_start = order_start + int(order_ms * 0.6 * 1e6)
    inventory = make(
        "inventory-service",
        "POST /inventory/reserve",
        inventory_start,
        inventory_ms,
        order.span_id,
        status="OK",
        attributes={"http.status_code": 200, "inventory.sku": f"SKU-{random.randint(1000, 9999)}"},
    )

    return [root, order, payment, inventory]


async def emit_synthetic_traces(
    runtime,
    count: int,
    error_probability: float = 0.05,
    slow_probability: float = 0.08,
    batch_size: int = 25,
) -> dict[str, Any]:
    """Push synthetic traces through the real ingestion path."""
    from app.collector.ingestion import IngestionService

    service = IngestionService(runtime)
    accepted = spilled = rejected = spans = 0
    for start in range(0, count, batch_size):
        chunk = min(batch_size, count - start)
        spans_batch: list[Span] = []
        for _ in range(chunk):
            spans_batch.extend(build_synthetic_trace(error_probability, slow_probability))
        try:
            result = await service.ingest(spans_batch, source="synthetic")
            accepted += result.get("accepted", 0)
            spilled += result.get("spilled", 0)
            rejected += result.get("rejected", 0)
            spans += len(spans_batch)
        except Exception:
            rejected += chunk
    return {
        "traces": count,
        "spans": spans,
        "accepted": accepted,
        "spilled": spilled,
        "rejected": rejected,
        "source": "synthetic",
    }
