"""Inventory service: reserves stock for an order."""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI

from app.services.common.telemetry import configure_telemetry

app = FastAPI(title="TraceFlow Inventory Service", version="1.0.0")
provider = configure_telemetry("inventory-service", app)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "inventory-service"}


@app.post("/inventory/reserve")
async def reserve(payload: dict) -> dict:
    await asyncio.sleep(random.uniform(0.01, 0.05))
    return {"reserved": True, "order_id": payload.get("order_id"), "sku": payload.get("sku")}


@app.on_event("shutdown")
async def shutdown() -> None:
    provider.shutdown()
