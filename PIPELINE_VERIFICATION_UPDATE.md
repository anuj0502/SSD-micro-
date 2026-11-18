# Telemetry Pipeline UI + end-to-end verification

- Stage cards now have fixed readable widths, 2-column stacked metric cells and horizontal scrolling.
- POST `/api/pipeline/verify` inserts one uniquely identifiable diagnostic span using the actual ingestion service. It cannot be used more than once per 20 seconds per app process.
- GET `/api/pipeline/verify/{trace_id}` checks persisted trace-index records in PostgreSQL and whether the compressed batch has been uploaded and attached to that record.
- The test uses a duration above the configured slow-trace threshold so normal tail sampling retains it. It does not change sampling configuration or inject fabricated success counts.
- UI polls every 3 seconds for up to 90 seconds, showing accepted, indexed and stored states. An inconclusive timeout is not reported as a pass.
- This verifies the TraceFlow internal pipeline, not external OpenTelemetry export from a separate process.
- Note: Public ingestion and diagnostics should have authentication / rate limits at the ingress for production use. This diagnostic only has a basic per-process cooldown.

## Update existing repo

Extract this ZIP, then copy *contents* of TraceFlow_Render into the already-cloned `SSD-micro-` repo. Keep its `.git` directory; do not delete other repository files blindly. In VS Code terminal in the repo:

```powershell
git status
git add .
git commit -m "Fix pipeline cards and add end-to-end verification"
git push origin main
```

After Render deploy completes, open `/pipeline`, click **Run pipeline test**, and observe the state progress from accepted to indexed to stored. The first result can take over 10 seconds depending on the sampling window and batch flush interval.
