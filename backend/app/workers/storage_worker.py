"""Storage worker: uploads compressed batches with retries, then indexes them.

Durability model
----------------
* A batch is spooled to local disk *before* the upload is attempted.
* The `batches` row is written with status `pending` before the upload.
* Uploads are idempotent because the object key is derived from the unique
  batch id; re-uploading overwrites the same object with identical bytes.
* Failed uploads are retried with exponential backoff and remain recoverable
  (the spool file survives a restart).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.collector.batching import Batch
from app.collector.compression import decompress_bytes, decode_jsonl
from app.config.settings import settings
from app.storage.object_store import StorageUnavailable
from app.utils.logging import get_logger
from app.workers.base import BaseWorker

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.storage")


class StorageWorker(BaseWorker):
    name = "storage-worker"

    def __init__(self, runtime: "Runtime") -> None:
        super().__init__(runtime)
        self.stats = {
            "uploaded": 0,
            "failed": 0,
            "pending": 0,
            "retries": 0,
            "avg_upload_ms": 0.0,
            "bytes_uploaded": 0,
        }
        self._upload_times: list[float] = []

    async def loop(self) -> None:
        try:
            batch: Batch = await asyncio.wait_for(self.runtime.batch_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return
        try:
            await self.upload_batch(batch)
        finally:
            self.runtime.batch_queue.task_done()

    async def upload_batch(self, batch: Batch) -> bool:
        runtime = self.runtime
        assert runtime.store is not None and runtime.index is not None
        await runtime.index.upsert_batch(batch)
        self.stats["pending"] += 1
        if runtime.events is not None:
            await runtime.events.add(
                "batch",
                f"New batch created · {batch.trace_count} traces · {batch.compressed_bytes} B",
                meta={"batch_id": batch.batch_id, "object_key": batch.object_key},
            )

        try:
            payload = await self._payload(batch)
        except Exception as exc:
            log.error("batch payload unavailable", extra={"batch_id": batch.batch_id, "error": str(exc)})
            await runtime.index.mark_batch_result(batch.batch_id, "failed", 0, f"payload unavailable: {exc}")
            self.stats["failed"] += 1
            self.stats["pending"] = max(0, self.stats["pending"] - 1)
            return False

        attempts = 0
        last_error: str | None = None
        while attempts < settings.batch_max_attempts:
            attempts += 1
            started = time.perf_counter()
            try:
                if await runtime.store.object_exists(batch.object_key):
                    # Idempotent no-op: this batch was already persisted.
                    await runtime.mark_batch_uploaded(batch, attempts, (time.perf_counter() - started) * 1000)
                    return True
                await runtime.store.put_object(batch.object_key, payload)
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                await runtime.mark_batch_uploaded(batch, attempts, duration_ms)
                self._record_success(batch, duration_ms)
                return True
            except (StorageUnavailable, OSError, Exception) as exc:
                last_error = str(exc)
                self.stats["retries"] += 1
                await runtime.index.mark_batch_result(batch.batch_id, "pending", attempts, last_error)
                log.warning(
                    "batch upload failed, retrying",
                    extra={"batch_id": batch.batch_id, "attempt": attempts, "error": last_error},
                )
                if attempts < settings.batch_max_attempts:
                    await asyncio.sleep(min(8.0, 0.25 * (2 ** (attempts - 1))))

        self.stats["failed"] += 1
        self.stats["pending"] = max(0, self.stats["pending"] - 1)
        await runtime.index.mark_batch_result(batch.batch_id, "failed", attempts, last_error)
        if runtime.events is not None:
            await runtime.events.add(
                "storage",
                f"Batch upload failed after {attempts} attempts · {batch.batch_id}",
                level="error",
                meta={"batch_id": batch.batch_id, "error": last_error},
            )
        return False

    def _record_success(self, batch: Batch, duration_ms: float) -> None:
        self.stats["uploaded"] += 1
        self.stats["pending"] = max(0, self.stats["pending"] - 1)
        self.stats["bytes_uploaded"] += batch.compressed_bytes
        self._upload_times = (self._upload_times + [duration_ms])[-50:]
        self.stats["avg_upload_ms"] = round(sum(self._upload_times) / len(self._upload_times), 2)

    async def _payload(self, batch: Batch) -> bytes:
        spool = Path(batch.spool_path)
        if spool.exists():
            return await asyncio.to_thread(spool.read_bytes)
        if batch.entries:
            from app.collector.compression import compress_bytes, encode_jsonl

            return compress_bytes(encode_jsonl(batch.entries))
        raise FileNotFoundError(f"spool file missing for {batch.batch_id}")

    async def retry_batch(self, batch_row: dict[str, Any]) -> bool:
        """Re-queue a failed batch from its spool file (used by the API/Fault Lab)."""
        entries: list[dict[str, Any]] = []
        spool_path = Path(settings.data_dir) / "pending" / f"{batch_row['batch_id']}.jsonl.gz"
        if spool_path.exists():
            entries = decode_jsonl(decompress_bytes(await asyncio.to_thread(spool_path.read_bytes)))
        batch = Batch(
            batch_id=batch_row["batch_id"],
            created_at=batch_row["created_at"],
            trace_count=batch_row["trace_count"],
            span_count=batch_row["span_count"],
            original_bytes=batch_row["original_bytes"],
            compressed_bytes=batch_row["compressed_bytes"],
            object_key=batch_row["object_key"],
            spool_path=str(spool_path),
            entries=entries,
            trace_ids=[e.get("trace", {}).get("trace_id") for e in entries if e.get("trace")],
        )
        await self.runtime.batch_queue.put(batch)
        return True

    def status(self) -> dict:
        data = super().status()
        data.update(self.stats)
        data["queue"] = self.runtime.batch_queue.qsize()
        return data
