"""OTLP parsing + normalization.

The collector accepts OTLP/HTTP in both JSON and protobuf encodings. Both are
normalized into a single internal `Span` shape; the rest of the pipeline never
needs to know which wire format produced it.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from pydantic import BaseModel, Field

_STATUS_NAMES = {0: "UNSET", 1: "OK", 2: "ERROR"}
_KIND_NAMES = {
    0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT",
    4: "PRODUCER", 5: "CONSUMER",
}


class SpanEvent(BaseModel):
    name: str = ""
    time_unix_nano: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """Normalized span used throughout the ingestion pipeline."""

    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    service: str
    kind: str = "SERVER"
    start_time_unix_nano: int
    end_time_unix_nano: int
    status: str = "UNSET"
    status_message: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)
    resource_attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def start_time(self) -> float:
        return self.start_time_unix_nano / 1e9

    @property
    def end_time(self) -> float:
        return self.end_time_unix_nano / 1e9

    @property
    def duration_ms(self) -> float:
        return round((self.end_time_unix_nano - self.start_time_unix_nano) / 1e6, 3)

    @property
    def has_error(self) -> bool:
        if self.status == "ERROR":
            return True
        code = self.attributes.get("http.status_code") or self.attributes.get("http.response.status_code")
        try:
            return int(code) >= 500  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False


def _attr_value(value: dict[str, Any]) -> Any:
    """Decode an OTLP AttributeValue object into a python primitive."""
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        try:
            return int(value["intValue"])
        except (TypeError, ValueError):
            return value["intValue"]
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return value["doubleValue"]
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        values = value["arrayValue"].get("values", [])
        return [_attr_value(v) for v in values]
    if "kvlistValue" in value:
        return {
            kv.get("key"): _attr_value(kv.get("value", {}))
            for kv in value["kvlistValue"].get("values", [])
        }
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _attributes(raw: list[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in raw or []:
        key = item.get("key")
        if key:
            out[key] = _attr_value(item.get("value", {}))
    return out


def parse_otlp_json(payload: dict[str, Any]) -> list[Span]:
    """Parse an OTLP/HTTP JSON ExportTraceServiceRequest."""
    spans: list[Span] = []
    for resource_span in payload.get("resourceSpans", []) or []:
        resource_attrs = _attributes(
            (resource_span.get("resource") or {}).get("attributes")
        )
        service = str(resource_attrs.get("service.name") or "unknown-service")
        scope_groups = resource_span.get("scopeSpans") or resource_span.get("instrumentationLibrarySpans") or []
        for scope_span in scope_groups:
            for raw in scope_span.get("spans", []) or []:
                trace_id = str(raw.get("traceId", "")).lower()
                span_id = str(raw.get("spanId", "")).lower()
                if not trace_id or not span_id:
                    continue
                status = raw.get("status") or {}
                status_code = status.get("code", 0)
                if isinstance(status_code, str):
                    status_name = status_code.upper()
                else:
                    status_name = _STATUS_NAMES.get(int(status_code), "UNSET")
                kind_raw = raw.get("kind", 1)
                kind = _KIND_NAMES.get(int(kind_raw), "INTERNAL") if not isinstance(kind_raw, str) else kind_raw
                events = [
                    SpanEvent(
                        name=event.get("name", ""),
                        time_unix_nano=int(event.get("timeUnixNano", 0) or 0),
                        attributes=_attributes(event.get("attributes")),
                    )
                    for event in raw.get("events", []) or []
                ]
                spans.append(
                    Span(
                        span_id=span_id,
                        trace_id=trace_id,
                        parent_span_id=(str(raw.get("parentSpanId")).lower() if raw.get("parentSpanId") else None),
                        name=raw.get("name", "unnamed"),
                        service=service,
                        kind=kind,
                        start_time_unix_nano=int(raw.get("startTimeUnixNano", 0) or 0),
                        end_time_unix_nano=int(raw.get("endTimeUnixNano", 0) or 0),
                        status=status_name if status_name in {"OK", "ERROR", "UNSET"} else "UNSET",
                        status_message=str(status.get("message", "") or ""),
                        attributes=_attributes(raw.get("attributes")),
                        events=events,
                        resource_attributes=resource_attrs,
                    )
                )
    return spans


def parse_otlp_protobuf(body: bytes) -> list[Span]:
    """Parse an OTLP/HTTP protobuf ExportTraceServiceRequest."""
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    payload = MessageToDict(request, preserving_proto_field_name=False)
    # protobuf bytes fields (trace/span ids) come back base64-encoded; the
    # internal representation uses lowercase hex like the OTLP/JSON path.
    for resource_span in payload.get("resourceSpans", []) or []:
        scope_groups = resource_span.get("scopeSpans") or resource_span.get("instrumentationLibrarySpans") or []
        for scope_span in scope_groups:
            for raw in scope_span.get("spans", []) or []:
                for field in ("traceId", "spanId", "parentSpanId"):
                    value = raw.get(field)
                    if not isinstance(value, str) or not value:
                        continue
                    try:
                        raw[field] = base64.b64decode(value).hex()
                    except (binascii.Error, ValueError):
                        pass
    return parse_otlp_json(payload)


def span_from_dict(data: dict[str, Any]) -> Span:
    """Rebuild a Span from its serialized JSONL representation."""
    return Span.model_validate(data)


def serialize_span(span: Span) -> dict[str, Any]:
    return span.model_dump(mode="json")
