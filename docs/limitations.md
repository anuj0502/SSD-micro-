# Limitations

TraceFlow is a local-first teaching and demonstration system. This page lists what it does
not do, so nothing here is mistaken for a production APM.

## Single node, single process

The collector, aggregation, sampling, batching, storage worker and API all run in one
Python process. There is no leader election, no sharding, and no coordination between
instances. Running two collectors against the same SQLite file would corrupt the index;
running them against separate files produces two unrelated systems.

Sampling state lives in that process. A restart re-evaluates new traces from scratch:
in-memory decision counters and the open-trace buffer are lost (indexed traces are not).
Deduplication survives a restart because `seen_spans` is in SQLite.

## SQLite is a metadata index, not a time-series database

Traces are stored one row each with pre-computed aggregates (`duration_ms`, `span_count`,
`has_error`, service/edge tables). Queries filter and sort in SQL over that table. There is
no columnar compression, no downsampling of old data, and no retention policy — the index
grows until you delete `data/traceflow.db`.

`/api/dashboard/overview` and `/api/dashboard/timeseries` compute percentiles by reading the matching trace rows
for the window. That is accurate, and it also means a `7d` window over a large index is a
linear scan. There is no query cache.

## Span bodies depend on the object store

Only retained traces get a body. Discarded traces keep metadata (`sampled = false`,
`decision_reason`, duration, error flag) and return an explicit "discarded" warning when
opened — this is intentional, and it is why the trace detail page can explain a decision
without inventing spans.

Retained bodies are read by fetching and decompressing the whole batch that contains the
trace. Opening a trace whose batch was deleted, or whose upload failed past the retry
budget, returns the metadata plus a warning instead of spans. `object_key` may
therefore be set on a trace whose object no longer exists; the API reports the retrieval
failure rather than hiding it.

## Fallback backends are not the real thing

When Redis or MinIO are unreachable the collector starts with `buffer_backend=memory` and
`object_store_backend=filesystem`, and `/api/health` says so. The fallbacks implement the
same interfaces (stream max length, consumer groups, pending lists, claim) but:

- the memory stream is per-process, so its "durability" is process lifetime;
- MinIO's filesystem replacement writes to local disk with no replication and no bucket
  policies;
- neither fallback is tested against real Redis/MinIO, and no integration test covers those
  clients.

Startup without Redis/MinIO retries the connections first, so readiness takes roughly 40
seconds; with the env overrides it is ready in a few seconds.

## Fault lab is in-process

Scenarios inject failures through the application's hooks: the ingestion worker is stopped
and restarted, the buffer reports itself unavailable, the object store fails uploads for a
window. This exercises the recovery code paths and produces real counters, but it does not:

- kill or restart an OS process or container,
- drop a TCP connection mid-command,
- corrupt a batch or a SQLite page,
- test network partitions between machines.

The "collector crash" scenario is the closest to a real crash: messages are delivered and
processed without acknowledgement, then reclaimed via the consumer group after the worker
restarts. Nothing is `SIGKILL`ed, so file handles and in-memory caches are not lost the way
they would be in reality.

## Benchmarks measure this machine

Load is generated from inside the same process (or over loopback to the gateway). Client and
server compete for the same CPU, GIL and disk, and percentiles come from a few hundred
samples with nearest-rank selection. Results are comparable across configurations on one
machine; they are not a capacity plan and will not reproduce on different hardware.
`gateway` mode additionally depends on the four demo services being up — `auto` silently
falls back to synthetic load, which is reported in `mode` but easy to miss.

## Not verified here

- **Docker / Compose.** `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`,
  `docker-compose.yml` and `.env.example` are written and internally consistent, but Docker
  is not installed in this environment, so `docker compose config`, image builds and a full
  stack boot were never run. Treat them as reviewed-but-unexecuted.
- **Locust.** `load_tests/locustfile.py` has not been executed; the `load` Compose profile
  is likewise unrun.
- **Browser automation.** The ten dashboard pages were verified manually in a browser
  against live data, but there is no Playwright/Cypress suite, so a future change can break
  a page without any test failing.
- **Real Redis/MinIO, multi-tenant load, long-running soak tests, clock skew, and huge
  traces** are all untested.

## Security and scope

There is no authentication, no TLS, and no per-user data isolation — the API is designed for
`127.0.0.1` only. Synthetic traffic, fault injection and benchmark endpoints additionally
return `403` for non-loopback callers, which limits accidental flooding, not determined
abuse. CORS defaults to localhost origins. Do not expose port 8000 publicly.

## Frontend

- One bundle, no code splitting: the production build is roughly 950 kB (274 kB gzipped) and
  Vite warns about the chunk size. The service map (React Flow) and charts (Recharts) are the
  bulk of it.
- Data is polled (2.5–5 s per page) plus a WebSocket snapshot for the overview; there is no
  client cache, optimistic update or offline mode.
- The dashboard assumes UTC and English formatting, and its responsive drawers are
  hand-rolled with CSS transitions rather than a component library.
- The `range` selector changes backend queries; there is no custom date-range picker beyond
  the explorer's `since`/`until`.
