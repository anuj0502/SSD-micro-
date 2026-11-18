# Fault injection

The Fault Lab exists to answer one question with evidence: **when a component breaks, does
telemetry survive?** Every scenario runs inside the live collector process against the real
worker, buffer, batcher and object store. The result payload is assembled from runtime
counters, SQLite rows and object-store state read *after* the run — there are no scripted
outcomes and no "simulated: true" fields.

> Scope note: these scenarios inject faults through the application's own failure hooks
> (`buffer.simulate_outage()`, `store.fail_for()`, a stopped worker). They do not kill OS
> processes or containers. See [limitations](limitations.md#fault-lab-is-in-process).

## Scenarios

| Scenario | Slug | Injects | What is verified |
| --- | --- | --- | --- |
| Collector Crash | `collector-crash` | Stops the ingestion worker, processes a delivery without ACK, restarts after a delay | Pending messages are reclaimed, replayed spans deduplicate instead of persisting twice |
| Redis Disconnection | `redis-disconnect` | Marks the stream buffer unavailable for N seconds while traffic arrives | Spans spill into the bounded local queue, are rejected only when it is full, and drain afterwards |
| Storage Failure | `storage-failure` | Makes the object store fail uploads for N seconds | Batches are retried, the write-ahead spool survives, everything uploads after recovery |
| High Traffic | `high-traffic` | Generates a large number of traces at concurrency | Queue depth stays bounded, backpressure/rejections are counted, the pipeline returns to steady state |
| Duplicate Telemetry | `duplicate-spans` | Sends the same span set again 1–N times | Duplicates are rejected at ingest and never aggregated or persisted twice |
| Late-Arriving Spans | `late-spans` | Sends a span after the trace's completion window closed | The configured late policy is applied and counted, not silently ignored |

## Running a scenario

```bash
# Discover scenarios and their last recorded run
curl http://localhost:8000/api/faults/scenarios

# Run one (loopback only)
curl -X POST http://localhost:8000/api/faults/redis-disconnect \
  -H 'content-type: application/json' \
  -d '{"duration_s": 5, "traces": 40}'

# Poll the run, or list history
curl http://localhost:8000/api/faults/runs/<run_id>
curl http://localhost:8000/api/faults/runs
```

The same calls back the **Fault Injection** page, which renders the timeline, the result
counters and a pass/fail verdict per scenario.

Every run is persisted to the `fault_runs` table (id, scenario, status, JSON details,
start/finish timestamps), so the timeline survives a collector restart. In-memory state is
authoritative while a run executes; if SQLite is busy the persistence is retried and a
warning is logged rather than failing the scenario.

## A run's lifecycle

1. `POST /api/faults/{scenario}` validates the slug, assigns a 12-character run id and writes
   a `running` row.
2. An asyncio task executes the scenario. Each step appends a timeline entry
   (`{ts, message, status, meta}`) and re-persists, so the UI can follow progress live.
3. The scenario waits out the sampling completion timeout, flushes, and samples the
   pipeline until queues are drained.
4. `result` is filled from measured deltas, the row is marked `completed`, and a final
   timeline entry records the outcome. Exceptions mark the run `failed` with the error in
   the timeline.

## What each result actually measures

### `collector-crash`

Options: `traces` (default 20), `restart_delay_s` (default 3).

- `messages_delivered_without_ack` — stream entries handed to the worker with `ack=False`
  before the "crash", which is why they stay pending in the consumer group.
- `pending_at_crash` / `pending_after_recovery` — `XPENDING`-style counts on the buffer.
- `duplicates_suppressed` — delta of the assembler's `spans_duplicate` counter across the
  recovery `XAUTOCLAIM`.
- `spans_persisted_delta` — growth of `SUM(span_count)` in `traces`.
- `recovery_time_ms` — wall clock from restart to the end of the drain wait.
- `duplicate_persistence` — **should be `false`**; it is computed as
  `duplicates_suppressed > 0`, and the page treats `true` as a failure because it means the
  replayed delivery wrote rows that had already been indexed.

### `redis-disconnect`

Options: `duration_s` (default 5), `traces` (default 40).

- `spans_spilled` — spans redirected to the bounded local queue because `XADD` failed.
- `spans_rejected` — spans dropped because that queue was already at
  `local_spill_maxsize`. A non-zero value here is expected only under sustained overload.
- `spill_queue_depth_at_peak` / `spill_flushed` — how much was held and how much was pushed
  back into the stream after recovery.
- `spill_queue_drained` — whether the drain finished inside the scenario's polling window.
- `recovery_time_ms` — measured from the end of the outage window.

Observed in this workspace (memory buffer, 40 traces): 160 spans spilled, 160 flushed,
0 rejected, "Recovery Verified", recovery ≈ 1,985 ms, 5 timeline entries.

### `storage-failure`

Options: `duration_s` (default 7), `traces` (default 60).

- `batches_blocked` — batches in `pending`/`failed` while the store was down.
- `retry_attempts` — sum of `attempts` on those batches, i.e. real exponential-backoff
  retries, each of which logged its `last_error`.
- `spool_files` — `.jsonl.gz` files still present under `data/pending/`; the write-ahead
  spool is what makes the batch recoverable after a restart.
- `uploaded_batches_total`, `unrecovered_batches` — terminal state after retries.
- `recovery_time_ms` — from the end of the outage to the last successful upload.

### `high-traffic`

Options: `traces` (default 600), `concurrency` (default 20).

- `peak_queue_depth` / `final_queue_depth` — sampled stream length. The stream has
  `MAXLEN ≈ stream_maxlen`, so depth is capped by construction; a flat peak near that cap is
  the bounded-buffer behaviour working, not a bug.
- `throughput_spans_per_s` — emitted spans divided by the generation wall clock.
- `backpressure_events`, `spans_rejected`: counted deltas, the measured cost of the bound.
- `bounded` — the configured `stream_maxlen` at run time.

### `duplicate-spans`

Options: `traces` (default 10), `copies` (default 2).

- `spans_sent_total` vs `unique_spans` — the exact duplication factor actually sent.
- `duplicates_detected`, `duplicate_ratio` — from the deduplicator's counters.
- `persisted_trace_span_counts` — the stored `span_count` for the affected traces; it must
  equal the unique count, not the sent total.
- `duplicate_persistence_prevented` — `duplicates_detected >= unique_spans × copies`.

### `late-spans`

- `trace_decided_before_late_span` — read from the assembler after sleeping past
  `completion_timeout_s`; this proves the window was genuinely closed.
- `late_spans_dropped` / `late_spans_accepted` — which branch of `late_policy` fired.
- `late_span_count_indexed`, `truncated_flag`, `batch_id` — the trace row as persisted. Under
  `accept_if_buffered` the trace is marked `truncated` and its stored body is updated in
  place; under `drop` the counter increments and the stored body is untouched.

## Reading the verdicts

The UI labels a run `Recovery Verified` only when the measured terminal condition holds
(queue drained, no unrecovered batches, no duplicate persistence, no lost pending
messages). Everything else is shown as a warning with the measured numbers, including the
boring-but-real case where the spill queue is still draining when the observation window
ends. Nothing is rounded up to "pass".
