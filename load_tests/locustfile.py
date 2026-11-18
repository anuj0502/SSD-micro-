"""Locust load test for the TraceFlow demo flow.

Run against the gateway (or through Compose):

    locust -f load_tests/locustfile.py --host http://localhost:8001
    docker compose --profile load run --rm locust

Every request is instrumented with OpenTelemetry by the gateway image, so the
load shows up in the collector as real traces.
"""
from __future__ import annotations

import random

from locust import HttpUser, between, task


class Shopper(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        # Fail fast if the gateway is not reachable.
        self.client.get("/health", name="health")

    @task(5)
    def browse_catalog(self) -> None:
        self.client.get("/catalog", name="GET /catalog")

    @task(3)
    def checkout(self) -> None:
        with self.client.post("/checkout", name="POST /checkout", catch_response=True) as response:
            # Occasional 5xx responses are part of the simulated flow; record them as
            # failures without aborting the run.
            if response.status_code >= 500:
                response.failure(f"checkout returned {response.status_code}")

    @task(1)
    def checkout_degraded(self) -> None:
        params = {
            "simulate_error": random.random() < 0.2,
            "simulate_slow": random.random() < 0.3,
        }
        self.client.post("/checkout", params=params, name="POST /checkout (degraded)")


class Ingestor(HttpUser):
    """Direct synthetic ingestion, useful when the gateway is not running."""

    wait_time = between(1, 3)

    @task
    def push_traffic(self) -> None:
        self.client.post(
            "/api/telemetry/traffic",
            json={"traces": 20, "error_probability": 0.1, "slow_probability": 0.15},
            name="POST /api/telemetry/traffic",
        )
