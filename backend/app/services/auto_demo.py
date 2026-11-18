"""Optional background demo traffic using the existing collector ingestion pipeline.

No dashboard numbers are fabricated: each trace is ingested and processed by the
normal workers. Render sleeps pause generation; it resumes on process startup.
"""
from __future__ import annotations

import asyncio

from app.config.settings import settings
from app.services.traffic import emit_synthetic_traces
from app.utils.logging import get_logger

log = get_logger("traceflow.auto_demo")


async def run_auto_demo(runtime) -> None:
    """Emit a small initial burst and then moderate, bounded recurring traffic."""
    if not settings.auto_demo_enabled:
        return

    first = True
    if runtime.events is not None:
        await runtime.events.add(
            "system", "Simulated demo telemetry enabled",
            meta={"source": "synthetic", "auto_demo": True},
        )

    while True:
        count = (settings.auto_demo_initial_traces if first
                 else settings.auto_demo_traces_per_interval)
        first = False
        try:
            if count > 0 and runtime.ready:
                result = await emit_synthetic_traces(
                    runtime,
                    count=min(count, 100),
                    error_probability=settings.auto_demo_error_probability,
                    slow_probability=settings.auto_demo_slow_probability,
                    batch_size=25,
                )
                if result["rejected"]:
                    log.warning("some demo traces rejected", extra={"result": result})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("demo traffic emission failed; continuing after interval")
        await asyncio.sleep(max(settings.auto_demo_interval_s, 1.0))
