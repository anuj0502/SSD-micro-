"""Fault injection lab endpoints (local environment only)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_runtime, local_only
from app.collector.faults import SCENARIOS
from app.runtime import Runtime

router = APIRouter(prefix="/api/faults", tags=["faults"], dependencies=[Depends(local_only)])


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
async def list_scenarios(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
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
    scenario: str, payload: FaultRequest | None = None, runtime: Runtime = Depends(get_runtime)
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
    scenario: str | None = None, limit: int = 20, runtime: Runtime = Depends(get_runtime)
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
async def get_run(run_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
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
