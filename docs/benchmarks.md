# Benchmarks

The Benchmarks page is a load generator plus a result reader. A run pushes real traces
through the real ingestion path, waits for the pipeline to drain, then reads the resulting
rows out of SQLite and the batch table. Throughput and latency are therefore measured end to
end on this machine, not estimated.

> These numbers describe one laptop running collector, SQLite and a filesystem object store
> in a single process. They are useful for comparing configurations against each other on
> the same machine, and they are not a claim about production capacity.

## Running a benchmark

```bash
curl -X POST http://localhost:8000/api/benchmarks/run \
  -H 'content-type: application/json' \
  -d '{
    "config": {
      "name": "Pipeline benchmark",
      "total_requests": 120,
      "concurrency": 10,
      "duration_s": 30,
      "error_probability": 0.05,
      "slow_probability": 0.1,
      "mode": "auto"
    }
  }'

curl 'http://localhost:8000/api/benchmarks/results?limit=10'   # -> {runs: [...]}
curl http://localhost:8000/api/benchmarks/results/<run_id>
```

Runs execute asynchronously; polling the results endpoint returns `status: running` until
the drain completes. Results are persisted in `benchmark_runs`, so history survives a
restart.

## Modes

| `mode` | Behaviour |
| --- | --- |
| `auto` (default) | Probes `GET {gateway_url}/health`; uses `gateway` if the demo services are up, otherwise `synthetic` |
| `gateway` | `POST /checkout` on the API gateway with `simulate_error` / `simulate_slow` flags, so the four services emit spans over OTLP |
| `synthetic` | Builds trace fixtures in-process and calls the same `IngestionService` the OTLP receiver uses |

`gateway` measures the whole distributed path including HTTP hops; `synthetic` isolates the
collector. Both report which mode actually ran.

## Metrics

Client-side values come from the load workers; storage and trace values are read back
after draining.

| Field | Meaning |
| --- | --- |
| `total_requests_generated` | Requests/iterations actually issued (bounded by `total_requests` and `duration_s`) |
| `requests_ok` / `requests_failed` | Success/failure of the client call itself |
| `total_spans_generated` | Spans emitted by the client (4 per synthetic trace, 4 per checkout) |
| `spans_ingested` | Spans actually indexed in the window — compare with generated to see loss |
| `traces_stored` / `sampled_traces` | Trace rows created; retained (body stored) subset |
| `ingestion_throughput_spans_per_s` | Indexed spans ÷ load duration |
| `trace_throughput_per_s` | Stored traces ÷ load duration |
| `avg_processing_latency_ms`, `p50/p95/p99_latency_ms` | Percentiles of **trace duration** from the index, not HTTP latency |
| `client_p50_ms`, `client_p95_ms` | Percentiles of the client call latency (checkout round trip or ingest call) |
| `error_rate_pct` | Share of stored traces with `has_error` |
| `storage_consumed_bytes` / `storage_original_bytes` | Compressed vs raw bytes in batches created during the window |
| `compression_ratio` | compressed ÷ raw, so lower is better (`0.1224` ≈ 12% of original) |
| `storage_batches`, `write_operations`, `indexed_delta` | Object writes, batcher write ops, new trace rows |
| `load_duration_s` | Wall clock of the generation phase |

Percentiles use a nearest-rank selection over the sorted sample
(`index = round(pct/100 × n + 0.5) − 1`), not interpolation. With a few hundred samples that
is fine for comparison but coarse at the tails — a `p99` over 120 traces is effectively the
third-slowest trace.

## Comparison experiments

Set `experiments` to run variants back to back; each experiment saves the live settings,
runs both variants, and restores the original configuration in a `finally` block.

```json
{"config": {
  "name": "Sampling study",
  "total_requests": 200,
  "concurrency": 10,
  "experiments": ["sampling", "batching"],
  "success_rate": 0.1,
  "batch_size": 100
}}
```

| Experiment | Variants | Summary fields |
| --- | --- | --- |
| `sampling` | Tail sampling disabled (100%) vs enabled at `success_rate` | `traces_stored_*`, `storage_bytes_*`, `storage_reduction_pct`, `retention_pct` |
| `batching` | Batching off (one object per trace) vs on (`batch_size`) | `write_ops_*`, `write_reduction_pct`, throughput, `storage_ratio_enabled` |
| `faults` | Normal operation vs an injected storage outage (`outage_s`) | `normal_throughput`, `fault_throughput`, `recovery_time_ms`, `unrecovered_batches` |
| `concurrency` | One run per level in `concurrency_levels` (default `[1, 5, 20]`) | `levels`, `throughput[]`, `p95_latency[]` |

The sampling experiment forces `error_probability=0` and `slow_probability=0` in both
variants so the only difference is the success-rate policy; the response includes a `note`
saying so. Experiment runs are capped (`sampling` 400 requests, `batching` 500, `faults`
300, `concurrency` 300 per level) so a UI click cannot lock the collector for minutes.

## Observed results in this workspace

Measured on the development laptop (Windows, single collector process, SQLite +
filesystem store, memory stream buffer), synthetic mode:

| Run | Requests | Spans | Result |
| --- | --- | --- | --- |
| API smoke run | 40 | 160 | 3,200 spans/s ingest, 40 traces stored, `compression_ratio` 0.1224 (≈12.2% of raw) |
| "Pipeline benchmark" (from the UI) | 120 | 480 | p95 trace duration 1.34 s, sampling retained the error/slow subset |
| "UI verification run" | 120 | 480 | 11.3% compression, read from the `{runs}` response |

Treat these as a demonstration that the measurement path works, not as a performance
baseline. Numbers move with sampling rate, batch size, and how much history is already in
the index (percentiles include the whole window's traces).

## Interpreting the output

- Throughput drops when sampling retains more traces, because compression and upload are
  synchronous work on the storage worker.
- `spans_ingested < total_spans_generated` means spans were rejected or still in flight
  when the window closed; the run waits for the stream and batch queues to empty, but a
  backend that is failing will show the gap instead of hiding it.
- `compression_ratio` above 1.0 is possible for tiny batches: gzip framing and JSON
  overhead can exceed the payload. It is displayed as a percentage for that reason.
- Recovery time in the fault experiment is measured from the end of the outage window, so
  it includes the retry backoff, not just the failed request.
