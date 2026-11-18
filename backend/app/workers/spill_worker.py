"""Spill worker: bounded local buffering while the ingestion buffer is down.

When Redis is unavailable, the ingestion endpoint spills spans into a bounded
in-memory queue instead of dropping them. This worker drains the queue back into
the stream as soon as it recovers. If the queue fills up, new spans are rejected
with HTTP 429 (controlled rejection / backpressure) rather than growing memory
without bound.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.utils.logging import get_logger
from app.workers.base import BaseWorker

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.spill")


class SpillWorker(BaseWorker):
    name = "spill-worker"

    async def loop(self) -> None:
        await asyncio.sleep(0.5)
        runtime = self.runtime
        if runtime.buffer is None or runtime.spill_queue.empty():
            return
        try:
            healthy = await runtime.buffer.health()
        except Exception:
            healthy = False
        if not healthy:
            if runtime.spill_queue.qsize() > settings.local_spill_maxsize * 0.5:
                runtime.counters["backpressure_events"] += 1
            return
        drained = 0
        while not runtime.spill_queue.empty() and drained < 50:
            spans = runtime.spill_queue.get_nowait()
            try:
                await runtime.buffer.add_spans(spans)
            except Exception as exc:
                # Re-queue and stop; buffer went down again.
                runtime.spill_queue.put_nowait(spans)
                self.last_error = str(exc)
                return
            finally:
                runtime.spill_queue.task_done()
            drained += 1
            runtime.counters["spans_spill_flushed"] += len(spans)
        if drained:
            runtime.counters["buffer_unavailable"] = runtime.counters["buffer_unavailable"]
