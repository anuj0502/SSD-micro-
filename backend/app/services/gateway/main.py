"""API gateway: entry point of the simulated e-commerce flow."""
from __future__ import annotations

import asyncio
import os
import random
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Query
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.services.common.telemetry import configure_telemetry

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://localhost:8002")

app = FastAPI(title="TraceFlow API Gateway", version="1.0.0")
provider = configure_telemetry("api-gateway", app)
client = httpx.AsyncClient(timeout=15.0)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.post("/checkout")
async def checkout(
    simulate_error: bool = Query(False),
    simulate_slow: bool = Query(False),
) -> dict:
    """Place an order: gateway -> order-service -> payment/inventory."""
    order_id = uuid.uuid4().hex[:12]
    await asyncio.sleep(random.uniform(0.002, 0.012))
    try:
        response = await client.post(
            f"{ORDER_SERVICE_URL}/orders",
            params={"simulate_error": simulate_error, "simulate_slow": simulate_slow},
            json={"order_id": order_id, "items": [{"sku": f"SKU-{random.randint(1000, 9999)}", "qty": 1}]},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"order service unreachable: {exc}") from exc
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="order service failed")
    data = response.json()
    return {"order_id": order_id, "status": data.get("status"), "gateway": "api-gateway"}


@app.get("/catalog")
async def catalog() -> dict:
    await asyncio.sleep(random.uniform(0.003, 0.02))
    return {"products": [{"sku": f"SKU-{i}", "name": f"Product {i}"} for i in range(1, 6)]}


@app.on_event("shutdown")
async def shutdown() -> None:
    await client.aclose()
    HTTPXClientInstrumentor().uninstrument()
    provider.shutdown()
