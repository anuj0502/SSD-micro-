# Render Fault Injection + Pipeline update

## Fault Injection
- Production Render page now offers isolated latency-spike, payment-failure and recovery experiments using genuine checkout HTTP calls.
- Run results and recovery status persist in PostgreSQL `fault_runs` under `render:*` keys.
- Original local infrastructure scenarios remain restricted to local/dev/test and are untouched.
- Strict one-at-a-time execution plus an 8-second cooldown to limit public demo load. Public visitors can still run bounded demos: use authentication before real-world production exposure.
- The collector, PostgreSQL, workers, buffer, and object store are not intentionally disrupted in these Render scenarios.

## Telemetry Pipeline
- Zero queue backlog is expected with fast processing; it is not zero ingestion. The screenshot already shows hundreds of spans processed.
- Buffer label derives from real runtime backend (memory on Render, Redis locally with Docker).
- Pipeline page now displays received/enqueued/indexed totals since process startup, plus backing storage mode.
- Stage counters differ in units (spans / traces / batches). These are not expected to equal one another.
- No database schema migrations are necessary; uses existing `fault_runs` table.

## Deployment
Copy all files into the root of your existing Git checkout, `git add .`, `git commit -m "Render fault simulation and clearer pipeline"`, `git push origin main`. Let the Blueprint deploy latest commit. `REAL_DEMO_ENABLED=true` already set in render.yaml. Existing `AUTO_DEMO_ENABLED=true` unchanged.

## Verification
1. Open `/faults`, run Payment failure. Expect HTTP 503 then recovery HTTP 200.
2. Open Trace Explorer after a few seconds: locate error-span telemetry (sampling may impact visibility).
3. Open `/pipeline`: span totals should increase after scenarios or auto-demo intervals. All four queues may stay zero during healthy operation.
4. Refresh `/faults`: persisted test history should remain; after free-tier service restarts the history remains as long as the PostgreSQL database exists.
