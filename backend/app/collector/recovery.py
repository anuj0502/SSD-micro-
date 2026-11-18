"""Startup and runtime recovery.

Two independent recovery paths:

1. **Stream messages**: read-but-unacked Redis entries are reclaimed from the
   consumer group and re-processed. Deduplication by span id means replayed
   spans are not persisted twice.
2. **Batches**: batches that were created but not uploaded (crash between
   spool write and upload) are re-queued from their local spool files. Batches
   whose object already exists in storage are marked uploaded without
   re-writing data.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config.settings import settings
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.recovery")


async def recover_pending_messages(runtime: "Runtime", limit: int = 500) -> dict[str, Any]:
    """XAUTOCLAIM pending stream entries and process them idempotently."""
    if runtime.buffer is None or "ingestion" not in runtime.workers:
        return {"claimed": 0, "processed": 0}
    try:
        entries = await runtime.buffer.reclaim_pending(settings.reclaim_idle_ms, limit)
    except Exception as exc:
        log.warning("pending message reclaim failed", extra={"error": str(exc)})
        return {"claimed": 0, "error": str(exc), "processed": 0}
    if not entries:
        return {"claimed": 0, "processed": 0}
    result = await runtime.workers["ingestion"].process_entries(entries)
    if runtime.events is not None:
        await runtime.events.add(
            "recovery",
            f"Recovered {len(entries)} pending stream message(s) from the consumer group",
            meta={"claimed": len(entries), **result},
        )
    return {"claimed": len(entries), "processed": result.get("spans", 0), **result}


async def recover_batches(runtime: "Runtime") -> dict[str, Any]:
    """Re-queue batches interrupted between spooling and upload."""
    if runtime.index is None or runtime.store is None:
        return {"recovered": 0, "already_stored": 0}
    rows = await runtime.index.pending_batches()
    recovered = 0
    already = 0
    failed = 0
    storage_worker = runtime.workers.get("storage")
    for row in rows:
        try:
            if await runtime.store.object_exists(row["object_key"]):
                await runtime.index.mark_batch_result(row["batch_id"], "uploaded", row["attempts"], None, 0.0)
                already += 1
                continue
        except Exception:
            pass
        spool = Path(settings.data_dir) / "pending" / f"{row['batch_id']}.jsonl.gz"
        if spool.exists() and storage_worker is not None:
            await storage_worker.retry_batch(row)
            recovered += 1
        else:
            await runtime.index.mark_batch_result(
                row["batch_id"], "failed", row.get("attempts", 0), "spool file missing after restart"
            )
            failed += 1
    if (recovered or already or failed) and runtime.events is not None:
        await runtime.events.add(
            "recovery",
            f"Batch recovery: {recovered} re-queued, {already} already stored, {failed} unrecoverable",
            level="warning" if failed else "info",
            meta={"recovered": recovered, "already_stored": already, "failed": failed},
        )
    return {"recovered": recovered, "already_stored": already, "failed": failed}


async def run_startup_recovery(runtime: "Runtime") -> dict[str, Any]:
    await asyncio.sleep(0.5)
    batches = await recover_batches(runtime)
    messages = await recover_pending_messages(runtime)
    log.info("startup recovery complete", extra={**batches, **messages})
    return {"batches": batches, "messages": messages}
