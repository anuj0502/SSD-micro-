# API reference

Base URL: `http://localhost:8000`. Interactive docs: `/api/docs`, schema: `/api/openapi.json`.
The dashboard calls these same endpoints through its `/api` proxy.

All timestamps are Unix seconds (floats). Times are UTC.

## Ingestion

| Method | Path | Description |
| --- | --- | --- |
| POST | `/v1/traces` | OTLP/HTTP receiver. `application/json` or `application/x-protobuf`. Returns `{accepted, rejected}` |
| POST | `/api/telemetry/traffic` | Synthetic traffic generator (local only). Body `{traces, error_probability, slow_probability}` |
| GET | `/api/telemetry/stats` | Ingest counters, spill queue depth, buffer backend/depth, per-worker state |

The generator is guarded by `local_only`: it refuses non-loopback clients so a shared
deployment cannot be flooded from outside.

## Health

`GET /api/health` returns readiness plus component states:

```json
{
  "status": "ok",
  "ready": true,
  "uptime_s": 42.7,
  "components": {
    "collector": {"status": "healthy", "workers": {"ingestion": "running", "...": "running"}},
    "redis": {"status": "healthy", "backend": "memory", "url": null},
    "sqlite": {"status": "healthy", "path": "./data/traceflow.db"},
    "object_store": {"status": "healthy", "backend": "filesystem", "bucket": "..."}
  },
  "telemetry": {"traces_indexed": 270, "spans_indexed": 1080}
}
```

`backend` reports which implementation is actually in use — `memory` and `filesystem` mean the
fallbacks are active, not that Redis or MinIO are healthy.

## Dashboard

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/dashboard/overview?range=1h` | Metrics, service health, timeseries, recent traces/events, sampling and pipeline summaries |
| GET | `/api/dashboard/timeseries?range=1h&buckets=24` | Bucketed requests, errors, latency, throughput |
| GET | `/api/services?range=1h` | Per-service requests, errors, error rate, latency, health |
| GET | `/api/services/{service_name}` | Detail incl. top operations and inbound/outbound edges |

Ranges: `15m`, `1h`, `6h`, `24h`, `7d`. Percentiles are computed from the indexed traces in
the window, not estimated from averages.

## Traces

`GET /api/traces`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `trace_id` | string | – | Exact or prefix match |
| `service` | string | – | Root service, or any service in the trace |
| `operation` | string | – | Root operation substring |
| `status` | `success`/`error`/`slow` | – | Status filter |
| `range` | string | `1h` | Convenience window |
| `since`, `until` | float | – | Explicit window (overrides `range`) |
| `min_duration_ms` | float | – | Duration floor |
| `only_sampled` | bool | false | Retained traces only |
| `sort` | `start_time`/`duration_ms`/`span_count` | `start_time` | Sort field |
| `order` | `asc`/`desc` | `desc` | Sort direction |
| `page`, `page_size` | int | 1, 25 | `page_size` max 200 |

Response: `{items, total, page, page_size, pages}`. Each item carries the trace summary plus
`decision`, `decision_reason`, `late_span_count`, `truncated`, `batch_id` and `object_key`.

`GET /api/traces/{trace_id}` adds `spans[]` (waterfall geometry, attributes, events),
`services[]`, `sampling`, and `warning` when the trace has no stored body. Unknown IDs return
`404` with a message.

## Pipeline, sampling, batches

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/pipeline/stats` | Per-stage `incoming/processed/pending/failed/latency_ms`, queue tiles, workers, components |
| GET | `/api/sampling/config` | Current policy |
| PUT | `/api/sampling/config` | Full policy replacement (every field required); out-of-range values and unknown `late_policy` are rejected with `422` |
| GET | `/api/sampling/stats` | Decisions, retention/reduction rates, storage estimates, recent decisions |
| POST | `/api/sampling/reset-stats` | Clears decision counters (policy unchanged) |
| GET | `/api/batches` | Batch list with `live` counters and `queue` depth |
| GET | `/api/batches/config` / PUT | Batching policy `{batch_size, flush_interval_s, enabled}` |
| POST | `/api/batches/flush` | Flush the current buffer immediately |
| POST | `/api/batches/{batch_id}/retry` | Re-upload a failed batch |
| GET | `/api/batches/{batch_id}` | Batch detail incl. its traces |

Sampling config keys: `error_rate`, `slow_threshold_ms`, `success_rate`,
`completion_timeout_s`, `late_policy` (`drop` | `accept_if_buffered`), `deterministic`.

## Storage

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/storage/stats` | Object count/bytes, compressed vs raw bytes, compression ratio, tables, indexes, retrieval path |
| GET | `/api/storage/objects` | Objects with size and last-modified |
| GET | `/api/storage/objects/inspect?key=...` | Download, decompress and sample a stored object |

## Events, faults, benchmarks

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/events?limit=&hours=` | Activity feed (also accepts `category`) |
| GET | `/api/events/categories` | Available categories |
| GET | `/api/faults/scenarios` | Scenario metadata with `last_run` |
| POST | `/api/faults/{scenario}` | Run a scenario (local only); body takes flat options `traces`, `copies`, `duration_s`, `restart_delay_s`, `concurrency`; returns the persisted run |
| GET | `/api/faults/runs`, `/api/faults/runs/{run_id}` | History and full timeline |
| POST | `/api/benchmarks/run` | Start a measured run; body `{"config": {...}}` |
| GET | `/api/benchmarks/results?limit=` | `{runs: [...]}` newest first |
| GET | `/api/benchmarks/results/{run_id}` | One run with config, result and status |

Benchmark config: `name`, `total_requests`, `concurrency`, `duration_s`,
`error_probability`, `slow_probability`, `mode` (`auto`/`gateway`/`synthetic`),
`experiments` (`sampling`/`batching`/`faults`/`concurrency`), `success_rate`, `batch_size`,
`outage_s`, `concurrency_levels`.

## WebSocket

`ws://localhost:8000/api/ws/live?range=1h` — on connect and roughly every 3 seconds the
server sends:

```json
{"type": "snapshot", "overview": {...}, "services": [...], "sampling": {...}, "pipeline": {...}, "events": [...]}
```

The shape matches the REST overview, so the dashboard can seed from REST and then apply
snapshots without a separate parser.

## Errors

Failures return `{"detail": "..."}` with `400` (bad input), `404` (unknown trace/batch/run),
`422` (Pydantic validation) or `503` (collector not ready). Fault and synthetic-traffic
endpoints additionally return `403` when called from a non-loopback address.
