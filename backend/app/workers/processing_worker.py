"""Processing worker: closes traces, applies tail sampling and hands them to the batcher."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.utils.logging import get_logger
from app.workers.base import BaseWorker

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.processing")


class ProcessingWorker(BaseWorker):
    name = "processing-worker"

    def __init__(self, runtime: "Runtime") -> None:
        super().__init__(runtime)
        self.evaluated = 0
        self.late_merged = 0
        self.late_missed = 0

    async def loop(self) -> None:
        await asyncio.sleep(settings.processing_tick_ms / 1000)
        await self.tick()

    async def tick(self) -> dict:
        runtime = self.runtime
        if runtime.index is None or runtime.batcher is None:
            return {"evaluated": 0}
        cfg = runtime.sampler.config
        started = time.perf_counter()

        summaries = runtime.assembler.finalize_due(
            timeout_s=cfg.completion_timeout_s, slow_threshold_ms=cfg.slow_threshold_ms
        )
        retained = 0
        for summary in summaries:
            decision = runtime.sampler.decide(summary)
            await runtime.index.index_trace(summary, decision)
            runtime.counters["traces_indexed"] += 1
            self.evaluated += 1
            if decision.retained:
                retained += 1
                await runtime.batcher.add_trace(summary)

        # Late spans accepted by the assembler are merged into a still-buffered
        # batch; otherwise the trace is marked truncated because its stored
        # object can no longer be mutated.
        for trace_id in runtime.assembler.drain_late_dirty():
            summary = runtime.assembler.summary_for(trace_id, cfg.slow_threshold_ms)
            if summary is None:
                continue
            merged = await runtime.batcher.update_trace(summary)
            if merged:
                self.late_merged += 1
            else:
                self.late_missed += 1
                await runtime.index.record_late_spans(
                    trace_id, summary.late_span_count, truncated=True
                )
            if runtime.events is not None:
                await runtime.events.add(
                    "sampling",
                    f"Late spans applied to trace {trace_id[:12]}… ({'merged' if merged else 'marked truncated'})",
                    level="warning",
                    meta={"trace_id": trace_id, "late_spans": summary.late_span_count, "merged": merged},
                )

        if summaries:
            runtime.record_sampling_latency((time.perf_counter() - started) * 1000)
        return {"evaluated": len(summaries), "retained": retained}

    def status(self) -> dict:
        data = super().status()
        data.update({"evaluated": self.evaluated, "late_merged": self.late_merged, "late_missed": self.late_missed})
        return data
