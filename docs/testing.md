# Testing

```bash
cd backend
./.venv/Scripts/python.exe -m pytest          # Windows
./.venv/bin/python -m pytest                  # macOS / Linux

cd ../frontend
npm run build                                 # production build check
```

The backend suite is the verification gate for the pipeline. It starts the real FastAPI app
(no HTTP mocks) against in-memory/filesystem fallbacks, drives spans through OTLP, and
asserts on what ends up in SQLite and the object store.

## How the fixtures work

`backend/tests/conftest.py` builds one app instance per test session with:

- `BUFFER_BACKEND=memory` — an in-process stream that implements the same
  `XADD`/consumer-group/`pending`/claim semantics as the Redis backend.
- `OBJECT_STORE_BACKEND=filesystem` — writes gzip batches to a temp directory instead of
  MinIO.
- A temp `SQLITE_PATH`, short sampling windows and a small batch size so tests finish in
  seconds instead of waiting on production timings.

This is deliberate: the fallbacks are production code paths (they are what runs when Redis
or MinIO are absent), so exercising them exercises the same interfaces the real backends
implement. What it does **not** prove is Redis or MinIO protocol behaviour — see
[limitations](limitations.md).

Helpers used by the tests:

| Helper | Purpose |
| --- | --- |
| `otlp_payload(service, trace_id, spans)` | Builds an OTLP/JSON `resourceSpans` payload with `service.name` on the resource |
| `wait_for(fn, timeout=…)` | Polls until `fn()` returns a truthy value, then returns it (used for asynchronous uploads) |
| `wait_for_traces(client, n)` | Polls `/api/traces` until at least `n` traces are indexed |

Polling is used instead of arbitrary `sleep()` because batching and upload are asynchronous
by design. Every wait has a timeout and fails loudly.

## What is covered

### `tests/integration/test_pipeline.py` — the end-to-end path

| Test | Asserts |
| --- | --- |
| `test_otlp_json_trace_is_stored_and_retrievable` | A two-span trace ingested under two OTLP resources is aggregated, decided, compressed, uploaded, indexed, and readable with `spans[]`, depth and no warning |
| `test_otlp_protobuf_is_accepted` | Binary OTLP with base64/bytes trace IDs decodes to the same hex ID the search API uses |
| `test_successful_traces_are_sampled_out_when_rate_is_zero` | `success_rate=0` discards the body (`object_key is None`, `spans == []`, warning mentions "discarded") but still indexes metadata |
| `test_slow_traces_retained_and_errors_always_retained` | `decision_reason` is `slow` above the threshold and `error` regardless of sampling |
| `test_service_graph_and_dashboard_reflect_ingested_data` | `/api/services` reports both services and the parent→child edge; `/api/dashboard/overview` counts traces/errors and returns 24 timeseries buckets |
| `test_search_filters_and_pagination` | Sorting, `page`/`pages`, `min_duration_ms` and the "any service in trace" filter all behave server-side |
| `test_batches_are_compressed_and_uploaded` | A flushed batch is gzip (`compression_ratio < 1`), appears in storage stats, is downloadable, and object inspection returns its entries |
| `test_trace_404_and_validation` | Unknown trace → 404, out-of-range sampling config → 422, malformed body → 400 |

### `tests/unit/test_aggregation.py` — trace assembly and waterfall

Grouping by trace id, error detection from HTTP status, waterfall depth/order/offset/width,
duplicate spans not double-counted, and both late policies (`drop` increments
`spans_late_dropped`; `accept_if_buffered` merges, marks `truncated`, and queues the trace
for a body update).

### `tests/unit/test_sampling.py` — policy

Errors always retained; slow traces retained only above the threshold; `success_rate` 0 and
1 behave as absolutes; deterministic decisions are stable across sampler instances; counters
report `retention_rate`/`reduction_rate`; invalid rates and unknown `late_policy` raise.

### `tests/unit/test_deduplication.py` — idempotency

A span inserted twice is rejected the second time, and a **new** `Deduplicator` instance
still rejects it because the record lives in SQLite — the crash-safety property the fault
lab depends on.

### `tests/unit/test_compression_batching.py` — storage layer

gzip magic bytes, byte-for-byte roundtrip, JSONL decode, ratio < 0.5 on compressible data,
date-partitioned object keys, size-triggered flush with a readable spool file, disabled
batching writing one object per trace, and late updates merging only into still-buffered
traces.

## Frontend verification

`npm run build` is the automated check (Vite + Tailwind + JSX compile). There is no browser
test suite. Runtime behaviour was verified manually in a real browser against the running
collector: Overview, Live Traces, Explorer, Trace detail, Service Map, Pipeline, Sampling,
Storage, Fault Injection and Benchmarks were each opened with live data, and a Redis
disconnection scenario and a benchmark run were driven through the UI. Console output
contained no application errors — only React Router v7 future-flag warnings and a
StrictMode double-mount WebSocket close.

## Not covered

- No Redis or MinIO integration tests; only the fallback backends are exercised.
- No Docker build or Compose test — Docker is not installed in this environment, so
  `docker-compose.yml` is authored but unvalidated.
- No Locust run; `load_tests/locustfile.py` has not been executed.
- No automated browser/E2E tests, and no visual regression tests.
- No multi-process or multi-node test; every scenario is single-process.

These are tracked in [limitations](limitations.md) rather than quietly assumed to work.
