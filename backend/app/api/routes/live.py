"""WebSocket live feed for dashboard updates."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.runtime import Runtime
from app.utils.logging import get_logger

router = APIRouter(tags=["live"])
log = get_logger("traceflow.live")


async def _snapshot(runtime: Runtime, range_key: str) -> dict[str, Any]:
    from app.api.deps import parse_time_range

    start, end = parse_time_range(range_key)
    assert runtime.index is not None
    overview = await runtime.index.overview(start, end, runtime.sampler.config.slow_threshold_ms)
    services = await runtime.index.service_stats(start, end)
    events = await runtime.events.list(limit=6) if runtime.events else []
    return {
        "type": "snapshot",
        "ts": time.time(),
        "overview": overview,
        "services": services,
        "sampling": {
            "retention_rate": runtime.sampler.snapshot()["stats"]["retention_rate"],
            "evaluated": runtime.sampler.stats["evaluated"],
        },
        "pipeline": {
            "queue_depth": await runtime.buffer_depth(),
            "pending_messages": await runtime.pending_messages(),
            "spill_depth": runtime.spill_queue.qsize(),
            "workers": runtime.worker_states(),
        },
        "events": events,
    }


@router.websocket("/api/ws/live")
async def live_feed(websocket: WebSocket, range: str = "1h") -> None:
    runtime: Runtime = websocket.app.state.runtime
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await _snapshot(runtime, range))
            # Read with a timeout so client disconnects are noticed promptly.
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
                if message == "ping":
                    await websocket.send_json({"type": "pong", "ts": time.time()})
                    continue
                if message.startswith("range:"):
                    range = message.split(":", 1)[1] or "1h"
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - transport level
        log.warning("live socket closed", extra={"error": str(exc)})
        try:
            await websocket.close()
        except Exception:
            pass
