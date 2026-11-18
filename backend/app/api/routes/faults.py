"""Fault injection lab endpoints (local environment only)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, local_only
from app.collector.faults import SCENARIOS
from app.runtime import Runtime

router = APIRouter(prefix="/api/faults", tags=["faults"])


class FaultRequest(BaseModel):
    traces: int | None = Field(None, ge=1, le=5000)
    copies: int | None = Field(None, ge=1, le=10)
    duration_s: float | None = Field(None, ge=0.5, le=120)
    restart_delay_s: float | None = Field(None, ge=0.5, le=60)
    concurrency: int | None = Field(None, ge=1, le=200)


def _controller(runtime: Runtime):
    controller = getattr(runtime, "faults", None)
    if controller is None:
        raise HTTPException(status_code=503, detail="fault controller not initialised")
    return controller


@router.get("/scenarios")
async def list_scenarios(runtime: Runtime = Depends(get_runtime), _local: None = Depends(local_only)) -> dict[str, Any]:
    controller = _controller(runtime)
    latest = controller.latest_by_scenario()
    return {
        "scenarios": [
            {
                "scenario": key,
                "title": value["title"],
                "expected": value["expected"],
                "last_run": latest.get(key),
                "supported": True,
            }
            for key, value in SCENARIOS.items()
        ],
        "environment": "local",
    }


@router.post("/{scenario}")
async def trigger_fault(
    scenario: str, payload: FaultRequest | None = None, runtime: Runtime = Depends(get_runtime), _local: None = Depends(local_only)
) -> dict[str, Any]:
    controller = _controller(runtime)
    options = {k: v for k, v in (payload.model_dump() if payload else {}).items() if v is not None}
    try:
        run = await controller.start(scenario, options)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if runtime.events is not None:
        await runtime.events.add(
            "fault",
            f"Fault injection triggered · {SCENARIOS[scenario]['title']}",
            level="warning",
            meta={"run_id": run["id"], "options": options},
        )
    return run


@router.get("/runs")
async def list_runs(
    scenario: str | None = None, limit: int = 20, runtime: Runtime = Depends(get_runtime), _local: None = Depends(local_only)
) -> dict[str, Any]:
    controller = _controller(runtime)
    runs = controller.list_runs(scenario=scenario, limit=limit)
    if not runs:
        rows = await runtime.db.fetchall(
            "SELECT * FROM fault_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        restored = []
        for row in rows:
            details = json.loads(row["details"] or "{}")
            restored.append(
                {
                    "id": row["id"],
                    "scenario": row["scenario"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    **details,
                }
            )
        runs = restored
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, runtime: Runtime = Depends(get_runtime), _local: None = Depends(local_only)) -> dict[str, Any]:
    controller = _controller(runtime)
    run = controller.get_run(run_id)
    if run is not None:
        return run
    row = await runtime.db.fetchone("SELECT * FROM fault_runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"fault run '{run_id}' not found")
    details = json.loads(row["details"] or "{}")
    return {
        "id": row["id"],
        "scenario": row["scenario"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        **details,
    }


# Render-specific application fault experiments. These NEVER disable the collector,
# memory buffer, workers, or database. Original infrastructure fault lab stays local.
import asyncio
import time
import uuid
import httpx
from fastapi import Request
from app.config.settings import settings

_RENDER_SCENARIOS = {
    "latency-spike": {"title": "Latency spike", "expected": "A real checkout takes longer, then the next request recovers.", "checkout": "slow"},
    "payment-failure": {"title": "Payment failure", "expected": "The checkout returns HTTP 503 and a following request succeeds.", "checkout": "error"},
    "healthy-recovery": {"title": "Healthy baseline and recovery", "expected": "Two actual healthy requests confirm the app is responsive.", "checkout": "success"},
}
_render_lock = asyncio.Lock()
_render_last_at = 0.0

def _render_enabled():
    if not settings.real_demo_enabled or settings.environment.lower() in {"local", "development", "test"}:
        raise HTTPException(status_code=404, detail="Render fault simulation requires a deployed Real HTTP Demo")

@router.get("/render/scenarios")
async def render_scenarios():
    _render_enabled()
    return {"environment": "render", "mode": "application-simulation", "scenarios": [
        {"scenario": key, "title": value["title"], "expected": value["expected"], "supported": True}
        for key, value in _RENDER_SCENARIOS.items()
    ]}

@router.get("/render/runs")
async def render_runs(runtime: Runtime = Depends(get_runtime)):
    _render_enabled()
    rows = await runtime.db.fetchall("SELECT * FROM fault_runs WHERE scenario LIKE 'render:%' ORDER BY started_at DESC LIMIT 12")
    return {"runs": [{"id": row["id"], "scenario": row["scenario"], "status": row["status"],
                      "started_at": row["started_at"], "finished_at": row["finished_at"],
                      **json.loads(row["details"] or '{}')} for row in rows]}

@router.post("/render/{scenario}")
async def run_render_scenario(scenario: str, request: Request, runtime: Runtime = Depends(get_runtime)):
    global _render_last_at
    _render_enabled()
    if scenario not in _RENDER_SCENARIOS:
        raise HTTPException(404, "Unknown Render demo scenario")
    if not runtime.ready:
        raise HTTPException(503, "Collector not ready")
    if _render_lock.locked() or time.monotonic() - _render_last_at < 8:
        raise HTTPException(429, "Only one bounded demo scenario every 8 seconds is allowed")
    async with _render_lock:
        _render_last_at = time.monotonic()
        item = _RENDER_SCENARIOS[scenario]
        run_id = uuid.uuid4().hex
        start = time.time()
        timeline = [{"ts": start, "status": "info", "message": "Started isolated checkout experiment"}]
        result = {}
        status = "completed"
        try:
            # These are real HTTP calls to the instrumented checkout API in the
            # SAME Render service, not mutations of the telemetry infrastructure.
            port = int(__import__('os').getenv('PORT', str(settings.port)))
            async with httpx.AsyncClient(timeout=8) as client:
                async def call(mode):
                    t = time.monotonic()
                    resp = await client.post(f"http://127.0.0.1:{port}/demo-app/checkout", params={"scenario": mode})
                    return resp.status_code, round((time.monotonic()-t)*1000, 1)
                response_code, duration_ms = await call(item["checkout"])
                timeline.append({"ts": time.time(), "status": "warning" if response_code >= 400 or scenario == 'latency-spike' else "info",
                                 "message": f"Injected checkout result: HTTP {response_code}, {duration_ms}ms"})
                # The checkout demo has a per-client one-second cooldown.
                await asyncio.sleep(1.15)
                recovery_code, recovery_ms = await call('success')
                timeline.append({"ts": time.time(), "status": "success" if recovery_code == 200 else "error",
                                 "message": f"Recovery request: HTTP {recovery_code}, {recovery_ms}ms"})
                result = {"http_status": response_code, "request_latency_ms": duration_ms,
                          "recovery_http_status": recovery_code, "recovery_latency_ms": recovery_ms,
                          "recovered": recovery_code == 200, "source": "real-http-request"}
                if recovery_code != 200 or (scenario == 'payment-failure' and response_code != 503) or (scenario != 'payment-failure' and response_code != 200):
                    status = "failed"
        except (httpx.HTTPError, OSError) as exc:
            status = "failed"
            result = {"error": str(exc)[:300], "recovered": False}
            timeline.append({"ts": time.time(), "status": "error", "message": "Request failed; see run details"})
        finish = time.time()
        details = {"title": item["title"], "expected": item["expected"], "timeline": timeline,
                   "result": result, "mode": "isolated-application-fault"}
        await runtime.db.execute(
            "INSERT INTO fault_runs (id, scenario, status, details, started_at, finished_at) VALUES (?,?,?,?,?,?)",
            (run_id, 'render:'+scenario, status, json.dumps(details), start, finish),
        )
        return {"id": run_id, "scenario": 'render:'+scenario, "status": status,
                "started_at": start, "finished_at": finish, **details}
