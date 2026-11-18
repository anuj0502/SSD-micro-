# TraceFlow: Render Free Deployment

## Architecture and preservation

- The original dashboard and REST/WebSocket APIs are unchanged.
- PostgreSQL replaces SQLite for **deployed trace metadata**, using `DATABASE_URL`.
- The existing gzip batch object-store contract remains: on the free demo, compressed batch objects are saved in a **separate PostgreSQL BYTEA table** instead of ephemeral files. Original MinIO remains supported via `OBJECT_STORE_BACKEND=minio`.
- Buffer defaults to the original **in-memory fallback**, because a free standalone Redis is not provisioned. This buffer is **not durable** across Render sleeps/restarts. For production-grade Redis Streams replay, configure an external Redis-compatible instance and set `BUFFER_BACKEND=redis` and `REDIS_URL`.
- The four standalone simulated microservices are still in the source but **are not deployed** by this single-service blueprint. Instead, the Render Blueprint enables **AUTO_DEMO_ENABLED=true**, a lightweight synthetic traffic generator inside the collector using the *existing ingestion pipeline*. It creates valid gateway/order/payment/inventory spans, so the dashboard indexes actual simulated trace records rather than hard-coded sample metrics. The UI labels this clearly as Demo Mode.
- Auto-demo initially emits 24 traces and then 1 trace every 15 seconds while the web service is active. It can be switched off at any time by setting `AUTO_DEMO_ENABLED=false` in Render's service Environment settings, then redeploying/restarting. Do not run the generator at this rate continuously on a quota-constrained database for long periods; monitor usage.
- Overview metrics can remain zero for several seconds after cold start: the existing tail-sampling completion timer and storage workers need to process the initial spans. After waiting and refreshing, inspect `/api/health` and `/api/dashboard/overview` if still empty.

## Deploy from GitHub

1. Unzip this archive. Keep the ORIGINAL ZIP as backup.
2. Create a new GitHub repository, and upload/commit the **contents** of the extracted folder (not the outer ZIP). Never commit `.env` or passwords.
3. Open [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**, connect the GitHub repository containing `render.yaml`, and apply the Blueprint.
4. The Blueprint provisions `traceflow-postgres` (free) and builds a single `traceflow-demo` Docker web service (free), with `DATABASE_URL` wired automatically.
5. Wait for the dashboard to show deploy **Live**, then visit `https://YOUR-SERVICE.onrender.com/`. The API docs remain at `/api/docs`, health at `/api/health`, ingestion at `/v1/traces`.
6. Verify `/api/health` reports `components.postgres.status=healthy` and `demo.enabled=true`, then open the dashboard. Give the processing pipeline time to index initial traces (typically a few seconds), refresh if necessary, and check Trace Explorer and the service map.

## Local PostgreSQL quickstart

Set `DATABASE_URL` to a local PostgreSQL database and `OBJECT_STORE_BACKEND=postgres`, `BUFFER_BACKEND=memory`, then from the `backend` directory run:

```sh
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run `npm ci && npm run dev` in `frontend` separately. Vite proxies API/WS to localhost:8000.

## Free tier limits and important caveats

- Render's free web service spins down after inactivity and has cold starts.
- Render **free Postgres expires after 30 days**; back up what you need and plan a paid database if persistence matters.
- In-memory Redis fallback has no durability; span messages still in the queue at shutdown may be lost. PostgreSQL-indexed traces and compressed objects survive web service restarts until the free database expires.
- Compressed objects use Postgres database quota. The free demo is intended for moderate project testing, not high-volume or production telemetry.
- A separate object storage service (S3/MinIO) and managed Redis are recommended for production.
- Keep one backend worker (configured in Dockerfile) so in-memory buffers and workers share the same process.
- Free sleeping instances may interrupt live WebSocket subscriptions and benchmark runs. Refresh the page to reconnect.

## Change log

- Added `backend/app/storage/postgres.py` and `backend/app/storage/database.py`.
- Added PostgreSQL object-store backend under existing object-store interface.
- Added `Dockerfile.render`, `render.yaml`, and `.dockerignore`.
- Updated SQLite-only frontend and health labels to PostgreSQL.
- SQLite module remains for existing isolated local SQLite tests; Render *always* selects PostgreSQL when `DATABASE_URL` is supplied.
- Existing microservice and local Docker Compose setups are retained as-is.

## How to update an already deployed GitHub repository

Extract the NEW ZIP in a fresh folder. If the current deployment repository is already checked out on your computer, **copy the new ZIP's contents** into that repository's root (preserve its `.git` folder), replacing files with the same names. Avoid copying an extra `TraceFlow_Render/` wrapper layer into the repo root. Never replace the repository's `.git` directory, and don't upload `.env`, credentials, or virtual environments.

Run from your repository root:

```sh
git status
git add .
git commit -m "Enable automatic demo telemetry"
git push origin main
```

Render's auto-deploy (when enabled for `main`) will rebuild the web app from the push. `render.yaml` Blueprint updates can also require **Blueprint Sync** in Render Dashboard to apply the new `AUTO_DEMO_*` environment variables; if they don't appear, add them manually to the web service's Environment section and redeploy. If you need to preserve other changes since the original ZIP, merge the changed files instead of blindly overwriting them. Existing PostgreSQL tables are not cleared by this deployment.
