"""Load tests and comparison experiments."""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_runtime
from app.runtime import Runtime

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

Experiment = Literal["sampling", "batching", "faults", "concurrency"]


class BenchmarkConfig(BaseModel):
    name: str = Field("Benchmark run", max_length=120)
    total_requests: int = Field(100, ge=1, le=5000)
    concurrency: int = Field(10, ge=1, le=200)
    duration_s: float = Field(30, ge=1, le=300)
    error_probability: float = Field(0.05, ge=0, le=1)
    slow_probability: float = Field(0.1, ge=0, le=1)
    mode: Literal["auto", "gateway", "synthetic"] = "auto"
    experiments: list[Experiment] = Field(default_factory=list)
    success_rate: float = Field(0.1, ge=0, le=1)
    batch_size: int = Field(100, ge=1, le=5000)
    outage_s: float = Field(4, ge=0.5, le=60)
    concurrency_levels: list[int] = Field(default_factory=lambda: [1, 5, 20])


class BenchmarkRequest(BaseModel):
    config: BenchmarkConfig


@router.post("/run")
async def run_benchmark(
    payload: BenchmarkRequest, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    runner = getattr(runtime, "benchmarks", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="benchmark runner not initialised")
    if not runtime.ready:
        raise HTTPException(status_code=503, detail="collector is still starting")

    config = payload.config.model_dump()
    if not config["experiments"]:
        config["experiments"] = []
    if config["experiments"]:
        # Experiments manage their own traffic volume per variant.
        config["total_requests"] = min(config["total_requests"], 300)
    run = await runner.start(config)
    if runtime.events is not None:
        await runtime.events.add(
            "benchmark",
            f"Benchmark started · {run['name']}",
            meta={"run_id": run["id"], "experiments": config["experiments"]},
        )
    return run


@router.get("/results")
async def list_results(limit: int = 20, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    runner = getattr(runtime, "benchmarks", None)
    items = runner.list(limit=limit) if runner else []
    if not items:
        rows = await runtime.db.fetchall(
            "SELECT * FROM benchmark_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        items = [
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "config": json.loads(row["config"] or "{}"),
                "result": json.loads(row["result"]) if row["result"] else None,
                "error": row["error"],
                "started_at": row["created_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]
    return {"runs": items}


@router.get("/results/{run_id}")
async def get_result(run_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    runner = getattr(runtime, "benchmarks", None)
    run = runner.get(run_id) if runner else None
    if run is not None:
        return run
    row = await runtime.db.fetchone("SELECT * FROM benchmark_runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"benchmark '{run_id}' not found")
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "config": json.loads(row["config"] or "{}"),
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "started_at": row["created_at"],
        "finished_at": row["finished_at"],
    }
