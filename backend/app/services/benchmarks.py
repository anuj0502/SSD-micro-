"""Load and benchmark engine.

All metrics come from actual executed load: client-side measurements plus
aggregates read back from the collector's PostgreSQL index after the pipeline has
been drained. Comparison experiments temporarily change live pipeline settings
and restore them afterwards.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from app.collector.ingestion import IngestionService
from app.config.settings import settings
from app.services.traffic import build_synthetic_trace
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.benchmarks")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return round(float(ordered[idx]), 1)


class BenchmarkRunner:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.runs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # -- public API --------------------------------------------------------
    async def start(self, config: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:12]
        run = {
            "id": run_id,
            "name": config.get("name") or "Benchmark run",
            "status": "running",
            "config": config,
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        self.runs[run_id] = run
        await self.runtime.db.execute(
            "INSERT INTO benchmark_runs(id, name, config, status, created_at) VALUES (?,?,?,?,?)",
            (run_id, run["name"], json.dumps(config), "running", run["started_at"]),
        )
        self._tasks[run_id] = asyncio.create_task(self._execute(run))
        return run

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return sorted(self.runs.values(), key=lambda r: r["started_at"], reverse=True)[:limit]

    async def stop_all(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    # -- execution ---------------------------------------------------------
    async def _execute(self, run: dict[str, Any]) -> None:
        try:
            config = run["config"]
            experiments = config.get("experiments") or []
            if experiments:
                run["result"] = {"experiments": [], "mode": None}
                for name in experiments:
                    result = await self._run_experiment(name, config)
                    run["result"]["experiments"].append(result)
                    run["result"]["mode"] = config.get("mode", "auto")
                    await self._persist(run)
            else:
                run["result"] = await self._single_run(config)
            run["status"] = "completed"
        except asyncio.CancelledError:
            run["status"] = "cancelled"
            raise
        except Exception as exc:
            log.exception("benchmark failed")
            run["status"] = "failed"
            run["error"] = str(exc)
        finally:
            run["finished_at"] = time.time()
            await self._persist(run)
            self._tasks.pop(run["id"], None)

    async def _persist(self, run: dict[str, Any]) -> None:
        try:
            await self.runtime.db.execute(
                "UPDATE benchmark_runs SET status=?, result=?, error=?, finished_at=? WHERE id=?",
                (
                    run["status"],
                    json.dumps(run["result"]) if run["result"] is not None else None,
                    run["error"],
                    run["finished_at"],
                    run["id"],
                ),
            )
        except Exception as exc:
            log.warning("benchmark persist failed", extra={"error": str(exc)})

    # -- experiments -------------------------------------------------------
    async def _run_experiment(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        if name == "sampling":
            return await self._experiment_sampling(config)
        if name == "batching":
            return await self._experiment_batching(config)
        if name == "faults":
            return await self._experiment_faults(config)
        if name == "concurrency":
            return await self._experiment_concurrency(config)
        raise ValueError(f"unknown experiment '{name}'")

    async def _experiment_sampling(self, config: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        original = runtime.sampler.config.as_dict()
        variants = []
        requests = min(int(config.get("total_requests", 120)), 400)
        try:
            runtime.sampler.config.success_rate = 1.0
            runtime.sampler.config.error_rate = 1.0
            disabled = await self._single_run(
                {**config, "total_requests": requests, "error_probability": 0.0, "slow_probability": 0.0}
            )
            variants.append({"label": "Sampling disabled (100%)", "metrics": disabled})

            runtime.sampler.config.success_rate = float(config.get("success_rate", 0.1))
            enabled = await self._single_run(
                {**config, "total_requests": requests, "error_probability": 0.0, "slow_probability": 0.0}
            )
            variants.append({"label": f"Sampling enabled ({runtime.sampler.config.success_rate:.0%})", "metrics": enabled})
        finally:
            runtime.sampler.config = type(runtime.sampler.config)(**original)

        base = variants[0]["metrics"]
        sampled = variants[1]["metrics"]
        return {
            "name": "sampling",
            "title": "Experiment A · Tail sampling disabled vs enabled",
            "variants": variants,
            "summary": {
                "traces_stored_disabled": base.get("traces_stored", 0),
                "traces_stored_enabled": sampled.get("traces_stored", 0),
                "storage_bytes_disabled": base.get("storage_consumed_bytes", 0),
                "storage_bytes_enabled": sampled.get("storage_consumed_bytes", 0),
                "storage_reduction_pct": round(
                    (1 - sampled.get("storage_consumed_bytes", 0) / base["storage_consumed_bytes"]) * 100, 2
                )
                if base.get("storage_consumed_bytes")
                else 0.0,
                "retention_pct": round(
                    sampled.get("traces_stored", 0) / base["traces_stored"] * 100, 2
                )
                if base.get("traces_stored")
                else 0.0,
            },
            "note": "Both variants use identical synthetic traffic with zero errors and no slow traces.",
        }

    async def _experiment_batching(self, config: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        if runtime.batcher is None:
            raise RuntimeError("batcher not ready")
        original = (runtime.batcher.enabled, runtime.batcher.batch_size, runtime.batcher.flush_interval_s)
        requests = min(int(config.get("total_requests", 200)), 500)
        variants = []
        try:
            runtime.batcher.enabled = False
            write_before = runtime.batcher.counters["write_ops"]
            unbatched = await self._single_run({**config, "total_requests": requests})
            unbatched["write_operations"] = runtime.batcher.counters["write_ops"] - write_before
            variants.append({"label": "Batching disabled (1 trace / object)", "metrics": unbatched})

            runtime.batcher.enabled = True
            runtime.batcher.batch_size = int(config.get("batch_size", 100))
            runtime.batcher.flush_interval_s = float(config.get("flush_interval_s", 2.0))
            write_before = runtime.batcher.counters["write_ops"]
            batched = await self._single_run({**config, "total_requests": requests})
            batched["write_operations"] = runtime.batcher.counters["write_ops"] - write_before
            variants.append({"label": f"Batching enabled ({runtime.batcher.batch_size} traces)", "metrics": batched})
        finally:
            runtime.batcher.enabled, runtime.batcher.batch_size, runtime.batcher.flush_interval_s = original

        a, b = variants[0]["metrics"], variants[1]["metrics"]
        return {
            "name": "batching",
            "title": "Experiment B · Batching disabled vs enabled",
            "variants": variants,
            "summary": {
                "write_ops_disabled": a.get("write_operations", 0),
                "write_ops_enabled": b.get("write_operations", 0),
                "write_reduction_pct": round(
                    (1 - b.get("write_operations", 0) / a["write_operations"]) * 100, 2
                )
                if a.get("write_operations")
                else 0.0,
                "throughput_disabled": a.get("ingestion_throughput_spans_per_s", 0),
                "throughput_enabled": b.get("ingestion_throughput_spans_per_s", 0),
                "storage_ratio_enabled": b.get("compression_ratio", 0),
            },
            "note": "Batching disabled writes one object per retained trace; enabled groups traces by size/time.",
        }

    async def _experiment_faults(self, config: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        requests = min(int(config.get("total_requests", 120)), 300)
        normal = await self._single_run({**config, "total_requests": requests})

        outage_s = float(config.get("outage_s", 4))
        runtime.store.fail_for(outage_s)
        fault_started = time.time()
        faulty = await self._single_run({**config, "total_requests": requests})
        outage_ended = fault_started + outage_s
        # Wait for the retry loop to persist everything that was spooled.
        recovery_start = time.time()
        for _ in range(120):
            rows = await runtime.db.fetchall(
                "SELECT COUNT(*) AS c FROM batches WHERE status IN ('pending','failed')"
            )
            pending = int(rows[0]["c"]) if rows else 0
            if pending == 0:
                break
            await asyncio.sleep(0.5)
        recovery_ms = round((time.time() - outage_ended) * 1000, 1) if time.time() > outage_ended else 0.0
        faulty["recovery_time_ms"] = recovery_ms
        faulty["recovery_wait_ms"] = round((time.time() - recovery_start) * 1000, 1)
        faulty["unrecovered_batches"] = int(
            (await runtime.db.scalar("SELECT COUNT(*) FROM batches WHERE status='failed'")) or 0
        )
        return {
            "name": "faults",
            "title": "Experiment C · Normal operation vs storage fault",
            "variants": [
                {"label": "Normal operation", "metrics": normal},
                {"label": f"Storage outage ({outage_s:.0f}s)", "metrics": faulty},
            ],
            "summary": {
                "normal_throughput": normal.get("ingestion_throughput_spans_per_s", 0),
                "fault_throughput": faulty.get("ingestion_throughput_spans_per_s", 0),
                "recovery_time_ms": recovery_ms,
                "unrecovered_batches": faulty["unrecovered_batches"],
            },
            "note": "The storage outage is injected through the same fault-injection hook used by the Fault Lab.",
        }

    async def _experiment_concurrency(self, config: dict[str, Any]) -> dict[str, Any]:
        levels = config.get("concurrency_levels") or [1, 5, 20]
        requests = min(int(config.get("total_requests", 100)), 300)
        variants = []
        for level in levels:
            metrics = await self._single_run(
                {**config, "total_requests": requests, "concurrency": level}
            )
            variants.append({"label": f"Concurrency {level}", "metrics": metrics})
        return {
            "name": "concurrency",
            "title": "Experiment D · Throughput and latency vs concurrency",
            "variants": variants,
            "summary": {
                "levels": levels,
                "throughput": [v["metrics"].get("ingestion_throughput_spans_per_s", 0) for v in variants],
                "p95_latency": [v["metrics"].get("p95_latency_ms", 0) for v in variants],
            },
            "note": "Each level replays the same number of traces with a different number of concurrent producers.",
        }

    # -- single load run ---------------------------------------------------
    async def _single_run(self, config: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        mode = await self._resolve_mode(config.get("mode", "auto"))
        total = int(config.get("total_requests", 100))
        concurrency = int(config.get("concurrency", 10))
        duration_limit = float(config.get("duration_s", 30))
        error_probability = float(config.get("error_probability", 0.05))
        slow_probability = float(config.get("slow_probability", 0.1))

        write_ops_before = runtime.batcher.counters["write_ops"] if runtime.batcher else 0
        indexed_before = int(await runtime.db.scalar("SELECT COUNT(*) FROM traces") or 0)

        started = time.time()
        load = await self._generate_load(
            mode=mode,
            total=total,
            concurrency=concurrency,
            duration_limit=duration_limit,
            error_probability=error_probability,
            slow_probability=slow_probability,
        )
        load_duration = max(0.05, time.time() - started)
        window_start = started
        await self._drain()

        metrics = await self._collect_metrics(
            window_start=window_start,
            window_end=time.time(),
            load=load,
            load_duration=load_duration,
            write_ops_before=write_ops_before,
            indexed_before=indexed_before,
        )
        metrics["mode"] = mode
        metrics["concurrency"] = concurrency
        metrics["requested_requests"] = total
        metrics["error_probability"] = error_probability
        metrics["slow_probability"] = slow_probability
        return metrics

    async def _resolve_mode(self, requested: str) -> str:
        if requested in {"gateway", "synthetic"}:
            return requested
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                response = await client.get(f"{settings.gateway_url}/health")
                if response.status_code == 200:
                    return "gateway"
        except Exception:
            pass
        return "synthetic"

    async def _generate_load(
        self,
        mode: str,
        total: int,
        concurrency: int,
        duration_limit: float,
        error_probability: float,
        slow_probability: float,
    ) -> dict[str, Any]:
        if mode == "gateway":
            return await self._gateway_load(
                total, concurrency, duration_limit, error_probability, slow_probability
            )
        return await self._synthetic_load(
            total, concurrency, duration_limit, error_probability, slow_probability
        )

    async def _gateway_load(
        self, total: int, concurrency: int, duration_limit: float, error_probability: float, slow_probability: float
    ) -> dict[str, Any]:
        latencies: list[float] = []
        ok = failed = 0
        spans_generated = 0
        lock = asyncio.Lock()
        deadline = time.time() + duration_limit
        semaphore = asyncio.Semaphore(concurrency)
        counter = {"issued": 0}

        async with httpx.AsyncClient(timeout=30.0) as client:
            async def worker() -> None:
                nonlocal ok, failed, spans_generated
                while True:
                    async with lock:
                        if counter["issued"] >= total or time.time() >= deadline:
                            return
                        counter["issued"] += 1
                    async with semaphore:
                        started = time.perf_counter()
                        try:
                            response = await client.post(
                                f"{settings.gateway_url}/checkout",
                                params={
                                    "simulate_error": random.random() < error_probability,
                                    "simulate_slow": random.random() < slow_probability,
                                },
                            )
                            elapsed = (time.perf_counter() - started) * 1000
                            latencies.append(elapsed)
                            if response.status_code < 500:
                                ok += 1
                            else:
                                failed += 1
                        except Exception:
                            failed += 1
                        spans_generated += 4

            await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))

        return {
            "mode": "gateway",
            "requests_attempted": counter["issued"],
            "requests_ok": ok,
            "requests_failed": failed,
            "latencies_ms": latencies,
            "client_spans_estimate": spans_generated,
        }

    async def _synthetic_load(
        self, total: int, concurrency: int, duration_limit: float, error_probability: float, slow_probability: float
    ) -> dict[str, Any]:
        runtime = self.runtime
        service = IngestionService(runtime)
        latencies: list[float] = []
        ok = failed = 0
        spans_generated = 0
        deadline = time.time() + duration_limit
        lock = asyncio.Lock()
        counter = {"issued": 0}

        async def worker() -> None:
            nonlocal ok, failed, spans_generated
            while True:
                async with lock:
                    if counter["issued"] >= total or time.time() >= deadline:
                        return
                    counter["issued"] += 1
                spans = build_synthetic_trace(error_probability, slow_probability)
                started = time.perf_counter()
                try:
                    await service.ingest(spans, source="benchmark")
                    ok += 1
                except Exception:
                    failed += 1
                latencies.append((time.perf_counter() - started) * 1000)
                spans_generated += len(spans)
                await asyncio.sleep(0)

        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
        return {
            "mode": "synthetic",
            "requests_attempted": counter["issued"],
            "requests_ok": ok,
            "requests_failed": failed,
            "latencies_ms": latencies,
            "client_spans_estimate": spans_generated,
        }

    async def _drain(self) -> None:
        """Wait until traces have closed, batches uploaded and queues are empty."""
        runtime = self.runtime
        cfg = runtime.sampler.config
        await asyncio.sleep(cfg.completion_timeout_s + 0.6)
        if runtime.batcher is not None:
            await runtime.batcher.flush(reason="manual")
        for _ in range(60):
            pending_stream = await runtime.pending_messages()
            pending_batches = int(
                (await runtime.db.scalar("SELECT COUNT(*) FROM batches WHERE status IN ('pending','failed')")) or 0
            )
            if runtime.batch_queue.empty() and pending_stream == 0 and pending_batches == 0:
                break
            await asyncio.sleep(0.3)

    async def _collect_metrics(
        self,
        window_start: float,
        window_end: float,
        load: dict[str, Any],
        load_duration: float,
        write_ops_before: int,
        indexed_before: int,
    ) -> dict[str, Any]:
        rows = await self.runtime.db.fetchall(
            "SELECT duration_ms, span_count, has_error, sampled, status FROM traces WHERE start_time >= ?",
            (window_start - 1.0,),
        )
        durations = [float(r["duration_ms"]) for r in rows]
        spans = sum(int(r["span_count"]) for r in rows)
        sampled = sum(1 for r in rows if r["sampled"])
        errors = sum(1 for r in rows if r["has_error"])
        batch_row = await self.runtime.db.fetchone(
            "SELECT COALESCE(SUM(compressed_bytes),0) AS bytes, COALESCE(SUM(original_bytes),0) AS original, "
            "COUNT(*) AS batches FROM batches WHERE created_at >= ?",
            (window_start - 1.0,),
        )
        stored_bytes = int(batch_row["bytes"] or 0) if batch_row else 0
        original_bytes = int(batch_row["original"] or 0) if batch_row else 0
        client_latencies = load.get("latencies_ms") or []

        return {
            "total_requests_generated": load["requests_attempted"],
            "requests_ok": load["requests_ok"],
            "requests_failed": load["requests_failed"],
            "total_spans_generated": load["client_spans_estimate"],
            "spans_ingested": spans,
            "traces_stored": len(rows),
            "sampled_traces": sampled,
            "load_duration_s": round(load_duration, 2),
            "ingestion_throughput_spans_per_s": round(spans / load_duration, 1),
            "trace_throughput_per_s": round(len(rows) / load_duration, 1),
            "avg_processing_latency_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "p50_latency_ms": _percentile(durations, 50),
            "p95_latency_ms": _percentile(durations, 95),
            "p99_latency_ms": _percentile(durations, 99),
            "error_rate_pct": round(errors / len(rows) * 100, 2) if rows else 0.0,
            "client_p50_ms": _percentile(client_latencies, 50),
            "client_p95_ms": _percentile(client_latencies, 95),
            "storage_consumed_bytes": stored_bytes,
            "storage_original_bytes": original_bytes,
            "compression_ratio": round(stored_bytes / original_bytes, 4) if original_bytes else 0.0,
            "storage_batches": int(batch_row["batches"] or 0) if batch_row else 0,
            "write_operations": (
                self.runtime.batcher.counters["write_ops"] - write_ops_before
                if self.runtime.batcher
                else 0
            ),
            "indexed_delta": int(await self.runtime.db.scalar("SELECT COUNT(*) FROM traces") or 0)
            - indexed_before,
        }
