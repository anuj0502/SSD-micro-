"""End-to-end pipeline: OTLP ingest -> aggregation -> sampling -> batching -> storage -> index."""
from __future__ import annotations

import json
import time

from tests.conftest import otlp_payload, wait_for, wait_for_traces


def span(span_id, trace_id, service, start_ns, dur_ms, parent=None, status="OK"):
    return {
        "spanId": span_id,
        "traceId": trace_id,
        "parentSpanId": parent or "",
        "name": f"{service}-op",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + int(dur_ms * 1e6)),
        "status": {"code": status},
        "attributes": [],
    }


def ingest_trace(client, trace_id: str, base_ns: int, duration_ms: float = 120, error: bool = False) -> None:
    root = span("r" + trace_id[:6], trace_id, "api-gateway", base_ns, duration_ms,
                status="ERROR" if error else "OK")
    child = span("c" + trace_id[:6], trace_id, "order-service", base_ns + 5_000_000,
                 duration_ms * 0.7, parent="r" + trace_id[:6])
    # Each service exports under its own OTLP resource, exactly like the real
    # instrumented services do (the resource carries service.name).
    payload = {
        "resourceSpans": [
            *otlp_payload("api-gateway", trace_id, [root])["resourceSpans"],
            *otlp_payload("order-service", trace_id, [child])["resourceSpans"],
        ]
    }
    response = client.post("/v1/traces", json=payload)
    assert response.status_code == 200


def test_otlp_json_trace_is_stored_and_retrievable(client):
    trace_id = "1a" * 16
    ingest_trace(client, trace_id, int(time.time() * 1e9))
    wait_for_traces(client, 1)

    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["trace_id"] == trace_id
    assert trace["sampled"] is True
    assert trace["span_count"] == 2
    assert trace["status"] in {"success", "slow"}

    # Eventually the batch is compressed, uploaded and the trace row gets keys.
    def object_attached():
        row = client.get(f"/api/traces/{trace_id}").json()
        return row if row["object_key"] else None

    row = wait_for(object_attached)
    assert row["object_key"].endswith(".jsonl.gz")
    assert row["object_key"].startswith("data/batches/")

    detail = client.get(f"/api/traces/{trace_id}").json()
    assert len(detail["spans"]) == 2
    assert detail["warning"] is None
    assert {s["service"] for s in detail["spans"]} == {"api-gateway", "order-service"}
    assert detail["spans"][1]["depth"] == 1


def test_otlp_protobuf_is_accepted(client):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.resource.v1.resource_pb2 import Resource
    from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span as PSpan

    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    resource_spans.resource.CopyFrom(
        Resource(attributes=[KeyValue(key="service.name", value=AnyValue(string_value="payment-service"))])
    )
    scope_spans = resource_spans.scope_spans.add()
    proto_span = scope_spans.spans.add()
    proto_span.trace_id = bytes.fromhex("2b" * 16)
    proto_span.span_id = bytes.fromhex("3c" * 8)
    proto_span.name = "POST /payments/authorize"
    proto_span.start_time_unix_nano = int(time.time() * 1e9)
    proto_span.end_time_unix_nano = proto_span.start_time_unix_nano + 50_000_000
    proto_span.status.code = 1

    response = client.post(
        "/v1/traces", content=request.SerializeToString(),
        headers={"content-type": "application/x-protobuf"},
    )
    assert response.status_code == 200
    wait_for_traces(client, 1)
    trace = client.get(f"/api/traces/{'2b' * 16}").json()
    assert trace["span_count"] == 1
    assert trace["sampled"] is True


def test_successful_traces_are_sampled_out_when_rate_is_zero(client):
    client.put(
        "/api/sampling/config",
        json={
            "error_rate": 1.0,
            "slow_threshold_ms": 5000,
            "success_rate": 0.0,
            "completion_timeout_s": 0.3,
            "late_policy": "drop",
            "deterministic": True,
        },
    )
    trace_id = "4d" * 16
    ingest_trace(client, trace_id, int(time.time() * 1e9), duration_ms=60)
    wait_for_traces(client, 1)
    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["sampled"] is False
    assert trace["decision_reason"] == "success_discarded"
    assert trace["object_key"] is None
    assert trace["spans"] == []
    assert "discarded" in (trace["warning"] or "")


def test_slow_traces_retained_and_errors_always_retained(client):
    client.put(
        "/api/sampling/config",
        json={
            "error_rate": 1.0,
            "slow_threshold_ms": 100,
            "success_rate": 0.0,
            "completion_timeout_s": 0.3,
            "late_policy": "drop",
            "deterministic": True,
        },
    )
    slow_id = "5e" * 16
    error_id = "6f" * 16
    ingest_trace(client, slow_id, int(time.time() * 1e9), duration_ms=400)
    ingest_trace(client, error_id, int(time.time() * 1e9), duration_ms=50, error=True)
    wait_for_traces(client, 2)
    assert client.get(f"/api/traces/{slow_id}").json()["decision_reason"] == "slow"
    assert client.get(f"/api/traces/{error_id}").json()["decision_reason"] == "error"


def test_service_graph_and_dashboard_reflect_ingested_data(client):
    now = int(time.time() * 1e9)
    for i in range(5):
        ingest_trace(client, f"{i:02x}" * 16, now + i * 1_000_000, duration_ms=80 + i, error=i == 0)
    wait_for_traces(client, 5)

    services = client.get("/api/services?range=1h").json()
    names = {s["service"] for s in services["services"]}
    assert {"api-gateway", "order-service"} <= names
    edges = {(e["source"], e["target"]) for e in services["edges"]}
    assert ("api-gateway", "order-service") in edges

    overview = client.get("/api/dashboard/overview?range=1h").json()
    assert overview["metrics"]["total_traces"] >= 5
    assert overview["metrics"]["error_traces"] >= 1
    assert len(overview["timeseries"]) == 24

    detail = client.get("/api/services/api-gateway?range=1h").json()
    assert detail["requests"] >= 5
    assert detail["recent_traces"]


def test_search_filters_and_pagination(client):
    now = int(time.time() * 1e9)
    for i in range(6):
        ingest_trace(client, f"{i:02d}" + "ab" * 15, now + i, duration_ms=50 + i * 100)
    wait_for_traces(client, 6)
    page = client.get("/api/traces?page_size=2&page=2&sort=duration&order=desc").json()
    assert page["total"] == 6
    assert page["pages"] == 3
    assert len(page["items"]) == 2
    slow = client.get("/api/traces?min_duration_ms=250&page_size=50").json()
    assert all(item["duration_ms"] >= 250 for item in slow["items"])
    by_service = client.get("/api/traces?service=order-service&page_size=50").json()
    assert by_service["total"] >= 6


def test_batches_are_compressed_and_uploaded(client):
    now = int(time.time() * 1e9)
    for i in range(3):
        ingest_trace(client, f"b{i}" .ljust(32, "0"), now + i, duration_ms=90)
    wait_for_traces(client, 3)
    client.post("/api/batches/flush")

    # The storage worker uploads asynchronously; wait for the terminal state.
    def uploaded_batch():
        items = client.get("/api/batches").json()["items"]
        if items and items[0]["status"] == "uploaded":
            return items[0]
        return None

    batch = wait_for(uploaded_batch)
    assert batch["compression_ratio"] < 1.0
    assert batch["compressed_bytes"] > 0

    storage = wait_for(
        lambda: (lambda s: s if s["objects"] >= 1 else None)(client.get("/api/storage/stats").json())
    )
    assert storage["objects"] >= 1
    detail = client.get(f"/api/batches/{batch['batch_id']}").json()
    assert detail["trace_count"] == batch["trace_count"]
    assert detail["traces"]

    objects = client.get("/api/storage/objects").json()
    assert objects["total"] >= 1
    inspected = client.get("/api/storage/objects/inspect", params={"key": batch["object_key"]}).json()
    assert inspected["entries"] >= 1


def test_trace_404_and_validation(client):
    assert client.get("/api/traces/does-not-exist").status_code == 404
    bad = client.put("/api/sampling/config", json={
        "error_rate": 2, "slow_threshold_ms": 500, "success_rate": 0.1,
        "completion_timeout_s": 5, "late_policy": "drop", "deterministic": True,
    })
    assert bad.status_code == 422
    assert client.post("/v1/traces", content=b"{not json", headers={"content-type": "application/json"}).status_code == 400
