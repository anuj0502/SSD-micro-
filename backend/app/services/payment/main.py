"""Payment service: simulated payment authorisation with failure injection."""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI, HTTPException, Query

from app.services.common.telemetry import configure_telemetry

app = FastAPI(title="TraceFlow Payment Service", version="1.0.0")
provider = configure_telemetry("payment-service", app)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "payment-service"}


@app.post("/payments/authorize")
async def authorize(
    payload: dict,
    simulate_error: bool = Query(False),
    simulate_slow: bool = Query(False),
) -> dict:
    delay = random.uniform(0.65, 1.25) if simulate_slow else random.uniform(0.03, 0.22)
    await asyncio.sleep(delay)
    if simulate_error or random.random() < 0.03:
        raise HTTPException(status_code=402, detail="card declined")
    return {
        "authorized": True,
        "order_id": payload.get("order_id"),
        "amount": payload.get("amount"),
        "provider": "stripe-sim",
    }


@app.on_event("shutdown")
async def shutdown() -> None:
    provider.shutdown()
