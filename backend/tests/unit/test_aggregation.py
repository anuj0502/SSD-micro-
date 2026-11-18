from __future__ import annotations

import time

import pytest

from app.collector.aggregation import AddOutcome, TraceAssembler
from app.storage.indexing import build_waterfall
from tests.conftest import otlp_payload, wait_for_traces


def span(span_id, trace_id, service, start_ns, dur_ms, parent=None, status="OK", code=200):
    return {
        "spanId": span_id,
        "traceId": trace_id,
        "parentSpanId": parent or "",
        "name": f"{service}-op",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + int(dur_ms * 1e6)),
        "status": {"code": status},
        "attributes": [
            {"key": "http.status_code", "value": {"intValue": code}},
        ],
    }


def assemble(client, trace_id: str, spans: list[dict], service="api-gateway"):
    response = client.post("/v1/traces", json=otlp_payload(service, trace_id, spans))
    assert response.status_code == 200


def test_spans_are_grouped_by_trace_id(client):
    trace_id = "a1" * 16
    now = int(time.time() * 1e9)
    assemble(
        client,
        trace_id,
        [
            span("s1", trace_id, "api-gateway", now, 100),
            span("s2", trace_id, "order-service", now + 5_000_000, 80, parent="s1"),
        ],
    )
    wait_for_traces(client, 1)
    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["span_count"] == 2
    assert trace["service_count"] >= 1
    assert trace["duration_ms"] >= 95


def test_error_status_detected_and_retained(client):
    trace_id = "b2" * 16
    now = int(time.time() * 1e9)
    assemble(
        client,
        trace_id,
        [
            span("e1", trace_id, "api-gateway", now, 120, status="ERROR", code=500),
        ],
    )
    wait_for_traces(client, 1)
    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["status"] == "error"
    assert trace["sampled"] is True
    assert trace["decision_reason"] == "error"


def test_waterfall_depth_and_order():
    now = 1_700_000_000_000_000_000
    trace_id = "c3" * 16
    spans = [
        span("root", trace_id, "api-gateway", now, 100),
        span("child", trace_id, "order-service", now + 5_000_000, 80, parent="root"),
        span("grand", trace_id, "payment-service", now + 10_000_000, 40, parent="child"),
    ]
    # `build_waterfall` consumes normalized spans (the shape persisted in the
    # JSONL batches), not raw OTLP JSON.
    waterfall = build_waterfall([
        {
            "span_id": s["spanId"],
            "trace_id": s["traceId"],
            "parent_span_id": s["parentSpanId"] or None,
            "name": s["name"],
            "service": s["name"].rsplit("-op", 1)[0],
            "start_time_unix_nano": int(s["startTimeUnixNano"]),
            "end_time_unix_nano": int(s["endTimeUnixNano"]),
            "status": "OK",
            "attributes": {},
            "events": [],
        }
        for s in spans
    ])
    assert [w["span_id"] for w in waterfall] == ["root", "child", "grand"]
    assert [w["depth"] for w in waterfall] == [0, 1, 2]
    assert waterfall[1]["offset_ms"] == pytest.approx(5.0, abs=0.01)
    assert waterfall[0]["width_pct"] == pytest.approx(100.0, abs=0.1)


def test_duplicate_span_is_not_double_counted(client):
    trace_id = "d4" * 16
    now = int(time.time() * 1e9)
    spans = [span("dup1", trace_id, "api-gateway", now, 50)]
    assemble(client, trace_id, spans)
    assemble(client, trace_id, spans)
    wait_for_traces(client, 1)
    trace = client.get(f"/api/traces/{trace_id}").json()
    assert trace["span_count"] == 1


def test_late_policy_drop_counts_spans():
    assembler = TraceAssembler(closed_ttl_s=60)
    from app.schemas.telemetry import Span

    base = Span(
        span_id="root0001", trace_id="f" * 32, name="root", service="api-gateway",
        start_time_unix_nano=1, end_time_unix_nano=1_000_000, status="OK",
    )
    assert assembler.add_span(base, late_policy="drop") == AddOutcome.NEW
    # force the decision window closed
    summaries = assembler.finalize_due(timeout_s=0, slow_threshold_ms=500)
    assert len(summaries) == 1
    late = Span(
        span_id="late0001", trace_id="f" * 32, name="late", service="order-service",
        start_time_unix_nano=2_000_000, end_time_unix_nano=3_000_000, status="OK",
    )
    assert assembler.add_span(late, late_policy="drop") == AddOutcome.LATE_DROPPED
    assert assembler.counters["spans_late_dropped"] == 1


def test_late_policy_accept_if_buffered():
    assembler = TraceAssembler(closed_ttl_s=60)
    from app.schemas.telemetry import Span

    base = Span(
        span_id="root0002", trace_id="e" * 32, name="root", service="api-gateway",
        start_time_unix_nano=1, end_time_unix_nano=1_000_000, status="OK",
    )
    assembler.add_span(base, late_policy="accept_if_buffered")
    assembler.finalize_due(timeout_s=0, slow_threshold_ms=500)
    late = Span(
        span_id="late0002", trace_id="e" * 32, name="late", service="order-service",
        start_time_unix_nano=2_000_000, end_time_unix_nano=3_000_000, status="OK",
    )
    assert assembler.add_span(late, late_policy="accept_if_buffered") == AddOutcome.LATE_ACCEPTED
    assert assembler.drain_late_dirty() == {"e" * 32}
    summary = assembler.summary_for("e" * 32, 500)
    assert summary.span_count == 2
    assert summary.truncated is True
