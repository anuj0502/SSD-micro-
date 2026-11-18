"""Base worker with supervision, structured status and graceful shutdown."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.worker")


class BaseWorker:
    name = "worker"
    auto_restart = True

    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.running = False
        self.task: asyncio.Task | None = None
        self.last_error: str | None = None
        self.restarts = 0
        self.started_at: float | None = None

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.started_at = time.time()
        self.task = asyncio.create_task(self._runner(), name=self.name)

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _runner(self) -> None:
        while self.running:
            try:
                await self.loop()
                # loops must block; if one returns immediately yield to avoid a busy spin
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let a transient failure kill the worker
                self.last_error = str(exc)
                self.restarts += 1
                log.error(
                    "worker error",
                    extra={"worker": self.name, "error": str(exc), "restarts": self.restarts},
                )
                if not self.auto_restart:
                    break
                await asyncio.sleep(settings.worker_restart_delay_s)

    async def loop(self) -> None:  # pragma: no cover - overridden
        await asyncio.sleep(1)

    def status(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "restarts": self.restarts,
            "last_error": self.last_error,
            "uptime_s": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }
