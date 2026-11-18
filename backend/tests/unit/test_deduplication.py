from __future__ import annotations

from app.collector.deduplication import Deduplicator
from app.schemas.telemetry import Span


def make_span(span_id: str = "s1", trace_id: str = "t1"):
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        name="op",
        service="api-gateway",
        start_time_unix_nano=1_000,
        end_time_unix_nano=2_000,
        status="OK",
    )


async def test_duplicate_spans_filtered(runtime):
    await runtime.db.connect()
    dedup = Deduplicator(runtime.db)
    first, dupes = await dedup.filter_new([make_span()])
    assert len(first) == 1 and dupes == 0

    second, dupes = await dedup.filter_new([make_span()])
    assert second == [] and dupes == 1

    # A fresh deduplicator instance still sees the SQLite record (crash safety).
    dedup2 = Deduplicator(runtime.db)
    third, dupes = await dedup2.filter_new([make_span()])
    assert third == [] and dupes == 1
    await runtime.db.close()


async def test_distinct_spans_pass_through(runtime):
    await runtime.db.connect()
    dedup = Deduplicator(runtime.db)
    spans = [make_span(f"s{i}", "t1") for i in range(10)]
    accepted, dupes = await dedup.filter_new(spans)
    assert len(accepted) == 10
    assert dupes == 0
    await runtime.db.close()
