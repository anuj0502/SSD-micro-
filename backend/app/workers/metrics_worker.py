"""Metrics worker: periodic pipeline snapshots + retention housekeeping."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.utils.logging import get_logger
from app.workers.base import BaseWorker

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.metrics")


class MetricsWorker(BaseWorker):
    name = "metrics-worker"

    def __init__(self, runtime: "Runtime") -> None:
        super().__init__(runtime)
        self._last_prune = 0.0

    async def loop(self) -> None:
        import asyncio

        await asyncio.sleep(settings.metrics_interval_s)
        runtime = self.runtime
        if runtime.db is None or not runtime.db.healthy:
            return
        ts = time.time()
        try:
            stages = await runtime.stage_snapshot()
            await runtime.db.executemany(
                "INSERT INTO metrics(ts, stage, processed, failed, pending, latency_ms) VALUES (?,?,?,?,?,?)",
                [
                    (ts, s["stage"], int(s["processed"]), int(s["failed"]), int(s["pending"]), float(s["latency_ms"]))
                    for s in stages
                ],
            )
        except Exception as exc:
            log.warning("metrics snapshot failed", extra={"error": str(exc)})

        # Housekeeping every 5 minutes.
        if ts - self._last_prune > 300:
            self._last_prune = ts
            cutoff = ts - settings.trace_retention_hours * 3600
            try:
                await runtime.db.execute("DELETE FROM metrics WHERE ts < ?", (ts - 24 * 3600,))
                await runtime.db.execute("DELETE FROM events WHERE ts < ?", (ts - 7 * 24 * 3600,))
                await runtime.db.execute(
                    "DELETE FROM trace_services WHERE trace_id IN (SELECT trace_id FROM traces WHERE start_time < ?)",
                    (cutoff,),
                )
                await runtime.db.execute(
                    "DELETE FROM trace_edges WHERE trace_id IN (SELECT trace_id FROM traces WHERE start_time < ?)",
                    (cutoff,),
                )
                await runtime.db.execute("DELETE FROM traces WHERE start_time < ?", (cutoff,))
                if runtime.dedup is not None:
                    await runtime.dedup.prune(24 * 3600)
            except Exception as exc:
                log.warning("retention cleanup failed", extra={"error": str(exc)})
