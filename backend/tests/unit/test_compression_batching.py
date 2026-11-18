from __future__ import annotations

import gzip
import json

from app.collector.batching import BatchProcessor, build_object_key
from app.collector.compression import (
    compress_bytes,
    compression_ratio,
    decode_jsonl,
    decompress_bytes,
    encode_jsonl,
)


def test_gzip_roundtrip_and_ratio():
    entries = [{"trace_id": str(i), "spans": [{"name": "x" * 200}]} for i in range(50)]
    raw = encode_jsonl(entries)
    compressed = compress_bytes(raw)
    assert compressed[:2] == b"\x1f\x8b"  # gzip magic header
    assert decompress_bytes(compressed) == raw
    assert decode_jsonl(decompress_bytes(compressed)) == entries
    assert compression_ratio(len(raw), len(compressed)) < 0.5


def test_object_key_is_date_partitioned():
    key = build_object_key("batch-123", 1_760_000_000.0)  # 2025-10-09 UTC
    assert key.startswith("data/batches/2025/10/09/batch-123.jsonl.gz")


def make_summary(trace_id: str):
    from app.collector.aggregation import ServiceStat, TraceSummary

    return TraceSummary(
        trace_id=trace_id,
        root_service="api-gateway",
        root_operation="POST /checkout",
        start_time=1_700_000_000.0,
        end_time=1_700_000_000.2,
        duration_ms=200,
        span_count=2,
        status="success",
        has_error=False,
        error_message=None,
        services=[ServiceStat("api-gateway", 1)],
        edges=[],
        spans=[],
    )


async def test_size_based_flush(tmp_path):
    batches = []

    async def on_batch(batch):
        batches.append(batch)

    processor = BatchProcessor(on_batch=on_batch, batch_size=2, flush_interval_s=60, spool_dir=str(tmp_path))
    await processor.add_trace(make_summary("a"))
    assert batches == []
    await processor.add_trace(make_summary("b"))
    assert len(batches) == 1
    batch = batches[0]
    assert batch.trace_count == 2
    assert batch.compressed_bytes < batch.original_bytes
    assert gzip.decompress(open(batch.spool_path, "rb").read())  # spooled write-ahead copy
    entries = decode_jsonl(gzip.decompress(open(batch.spool_path, "rb").read()))
    assert len(entries) == 2
    assert json.loads(json.dumps(entries[0]))["trace"]["trace_id"] == "a"


async def test_disabled_batching_flushes_every_trace(tmp_path):
    batches = []

    async def on_batch(batch):
        batches.append(batch)

    processor = BatchProcessor(
        on_batch=on_batch, batch_size=100, flush_interval_s=60, spool_dir=str(tmp_path), enabled=False
    )
    await processor.add_trace(make_summary("a"))
    await processor.add_trace(make_summary("b"))
    assert len(batches) == 2
    assert processor.counters["write_ops"] == 2


async def test_late_update_merges_buffered_trace(tmp_path):
    batches = []

    async def on_batch(batch):
        batches.append(batch)

    processor = BatchProcessor(on_batch=on_batch, batch_size=10, flush_interval_s=60, spool_dir=str(tmp_path))
    summary = make_summary("x")
    await processor.add_trace(summary)
    assert await processor.update_trace(summary) is True
    assert await processor.update_trace(make_summary("unknown")) is False
    await processor.flush(reason="manual")
    entries = decode_jsonl(gzip.decompress(open(batches[0].spool_path, "rb").read()))
    assert entries[0]["trace"]["trace_id"] == "x"
