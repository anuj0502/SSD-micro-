"""Order service: orchestrates payment authorisation and inventory reservation."""
from __future__ import annotations

import asyncio
import os
import random

import httpx
from fastapi import FastAPI, HTTPException, Query
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.services.common.telemetry import configure_telemetry

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8003")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8004")

app = FastAPI(title="TraceFlow Order Service", version="1.0.0")
provider = configure_telemetry("order-service", app)
client = httpx.AsyncClient(timeout=15.0)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "order-service"}


@app.post("/orders")
async def create_order(
    payload: dict,
    simulate_error: bool = Query(False),
    simulate_slow: bool = Query(False),
) -> dict:
    order_id = payload.get("order_id", "unknown")
    await asyncio.sleep(random.uniform(0.004, 0.02))

    # Reserve inventory first (parallel path in the trace graph).
    inventory_response = await client.post(
        f"{INVENTORY_SERVICE_URL}/inventory/reserve",
        json={"order_id": order_id, "sku": (payload.get("items") or [{}])[0].get("sku", "SKU-1")},
    )
    if inventory_response.status_code >= 500:
        raise HTTPException(status_code=502, detail="inventory reservation failed")

    payment_response = await client.post(
        f"{PAYMENT_SERVICE_URL}/payments/authorize",
        params={"simulate_error": simulate_error, "simulate_slow": simulate_slow},
        json={"order_id": order_id, "amount": round(random.uniform(10, 480), 2)},
    )
    if payment_response.status_code >= 500:
        raise HTTPException(status_code=502, detail="payment authorization failed")
    if payment_response.status_code == 402:
        raise HTTPException(status_code=402, detail="payment declined")

    return {"status": "confirmed", "order_id": order_id, "payment": payment_response.json()}


@app.on_event("shutdown")
async def shutdown() -> None:
    await client.aclose()
    HTTPXClientInstrumentor().uninstrument()
    provider.shutdown()
