"""Ingestion worker: consumes spans from the buffer and aggregates them.

Redis consumer-group semantics give at-least-once delivery: a message is only
acknowledged after its spans have been deduplicated and added to the trace
assembler. Messages read but not acked (worker crash) stay pending and are
reclaimed by the recovery pass.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from app.collector.aggregation import AddOutcome
from app.config.settings import settings
from app.schemas.telemetry import Span
from app.utils.logging import get_logger
from app.workers.base import BaseWorker

if TYPE_CHECKING:  # pragma: no cover
    from app.runtime import Runtime

log = get_logger("traceflow.ingestion")


class IngestionWorker(BaseWorker):
    name = "ingestion-worker"

    def __init__(self, runtime: "Runtime") -> None:
        super().__init__(runtime)
        self.processed_messages = 0
        self.processed_spans = 0
        self.acked_messages = 0
        self.duplicates = 0
        self.invalid_spans = 0

    async def loop(self) -> None:
        buffer = self.runtime.buffer
        if buffer is None:
            await asyncio.sleep(1)
            return
        try:
            entries = await buffer.read_batch(
                count=settings.ingestion_batch_size, block_ms=settings.ingestion_block_ms
            )
        except Exception as exc:
            # Buffer outage (simulated or real): back off and retry, do not crash.
            self.last_error = str(exc)
            self.runtime.counters["buffer_unavailable"] += 1
            await asyncio.sleep(0.5)
            return
        if not entries:
            return
        await self.process_entries(entries)

    async def process_entries(
        self, entries: list[tuple[str, list[dict[str, Any]]]], ack: bool = True
    ) -> dict[str, int]:
        """Deduplicate + aggregate a batch of stream messages, then ack them."""
        buffer = self.runtime.buffer
        assembler = self.runtime.assembler
        dedup = self.runtime.dedup
        if buffer is None or dedup is None:
            return {"messages": 0, "spans": 0, "duplicates": 0}

        late_policy = self.runtime.sampler.config.late_policy
        ack_ids: list[str] = []
        result = {"messages": 0, "spans": 0, "duplicates": 0, "late_accepted": 0, "late_dropped": 0}

        for msg_id, raw_spans in entries:
            parsed: list[Span] = []
            for raw in raw_spans:
                try:
                    parsed.append(Span.model_validate(raw))
                except Exception:
                    self.invalid_spans += 1
                    self.runtime.counters["spans_invalid"] += 1

            new_spans, duplicates = await dedup.filter_new(parsed)
            self.duplicates += duplicates
            result["duplicates"] += duplicates

            for span in new_spans:
                outcome = assembler.add_span(span, late_policy=late_policy)
                if outcome == AddOutcome.LATE_ACCEPTED:
                    result["late_accepted"] += 1
                elif outcome == AddOutcome.LATE_DROPPED:
                    result["late_dropped"] += 1

            self.processed_spans += len(new_spans)
            result["spans"] += len(new_spans)
            result["messages"] += 1
            self.processed_messages += 1
            ack_ids.append(msg_id)

        if ack and ack_ids:
            await buffer.ack(ack_ids)
            self.acked_messages += len(ack_ids)
        return result

    def status(self) -> dict:
        data = super().status()
        data.update(
            {
                "processed_messages": self.processed_messages,
                "processed_spans": self.processed_spans,
                "acked_messages": self.acked_messages,
                "duplicates": self.duplicates,
            }
        )
        return data
