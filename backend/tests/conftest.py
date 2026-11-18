from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.runtime import Runtime
from app.storage.sqlite import Database


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Isolated runtime: filesystem object store + in-memory stream + temp SQLite."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "traceflow.db"))
    monkeypatch.setattr(settings, "buffer_backend", "memory")
    monkeypatch.setattr(settings, "object_store_backend", "filesystem")
    monkeypatch.setattr(settings, "batch_flush_interval_s", 0.5)
    monkeypatch.setattr(settings, "batch_size", 100)
    monkeypatch.setattr(settings, "batch_max_attempts", 3)
    monkeypatch.setattr(settings, "reclaim_idle_ms", 500)
    monkeypatch.setattr(settings, "processing_tick_ms", 100)
    monkeypatch.setattr(settings, "environment", "test")
    rt = Runtime(Database(str(tmp_path / "traceflow.db")))
    return rt


@pytest.fixture
def client(runtime):
    from app.main import create_app

    app = create_app(enable_workers=True, runtime_override=runtime, run_recovery=False)
    with TestClient(app) as test_client:
        # Short decision window / flush interval keep the tests fast.
        test_client.put(
            "/api/sampling/config",
            json={
                "error_rate": 1.0,
                "slow_threshold_ms": 500,
                "success_rate": 1.0,
                "completion_timeout_s": 0.3,
                "late_policy": "drop",
                "deterministic": True,
            },
        )
        test_client.put(
            "/api/batches/config", json={"batch_size": 100, "flush_interval_s": 0.4, "enabled": True}
        )
        yield test_client


def wait_for(predicate, timeout: float = 8.0, interval: float = 0.15):
    """Poll until predicate() is truthy; returns the value or raises."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s (last={last!r})")


def wait_for_traces(client, count: int, timeout: float = 10.0) -> dict:
    def predicate():
        data = client.get("/api/traces?page_size=1").json()
        return data if data["total"] >= count else None

    return wait_for(predicate, timeout=timeout)


def otlp_payload(service: str, trace_id: str, spans: list[dict]) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
                "scopeSpans": [
                    {
                        "scope": {"name": "test"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }
