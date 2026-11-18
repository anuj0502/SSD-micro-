"""Trace indexing, search and retrieval.

Trace *metadata* lives in SQLite; the raw spans live in gzip JSONL objects in
MinIO. Retrieval joins the two: search SQLite, locate the batch object, download
and decompress it, and extract the requested trace.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.collector.aggregation import TraceSummary
from app.collector.compression import decode_jsonl, decompress_bytes
from app.collector.sampling import SamplingDecision
from app.storage.object_store import ObjectStore, StorageUnavailable
from app.storage.database import Database
from app.utils.logging import get_logger

log = get_logger("traceflow.indexing")


def _row_to_trace(row: Any) -> dict[str, Any]:
    return {
        "trace_id": row["trace_id"],
        "root_service": row["root_service"],
        "root_operation": row["root_operation"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "duration_ms": row["duration_ms"],
        "span_count": row["span_count"],
        "service_count": row["service_count"],
        "status": row["status"],
        "has_error": bool(row["has_error"]),
        "error_message": row["error_message"],
        "sampled": bool(row["sampled"]),
        "decision": row["decision"],
        "decision_reason": row["decision_reason"],
        "late_span_count": row["late_span_count"],
        "truncated": bool(row["truncated"]),
        "batch_id": row["batch_id"],
        "object_key": row["object_key"],
    }


class TraceIndex:
    def __init__(self, db: Database, store: ObjectStore) -> None:
        self.db = db
        self.store = store

    # -- write path --------------------------------------------------------
    async def index_trace(self, summary: TraceSummary, decision: SamplingDecision) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO traces (
                    trace_id, root_service, root_operation, start_time, end_time, duration_ms,
                    span_count, service_count, status, has_error, error_message, sampled,
                    decision, decision_reason, late_span_count, truncated, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    end_time=excluded.end_time, duration_ms=excluded.duration_ms,
                    span_count=excluded.span_count, service_count=excluded.service_count,
                    status=excluded.status, has_error=excluded.has_error,
                    error_message=excluded.error_message, late_span_count=excluded.late_span_count,
                    truncated=excluded.truncated
                """,
                (
                    summary.trace_id, summary.root_service, summary.root_operation,
                    summary.start_time, summary.end_time, summary.duration_ms,
                    summary.span_count, summary.service_count, summary.status,
                    int(summary.has_error), summary.error_message, int(decision.retained),
                    "retained" if decision.retained else "discarded", decision.reason,
                    summary.late_span_count, int(summary.truncated), time.time(),
                ),
            )
            await conn.executemany(
                """
                INSERT INTO trace_services(trace_id, service, span_count, error_count, duration_ms, start_time)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(trace_id, service) DO UPDATE SET
                    span_count=excluded.span_count, error_count=excluded.error_count,
                    duration_ms=excluded.duration_ms, start_time=excluded.start_time
                """,
                [
                    (summary.trace_id, s.service, s.span_count, s.error_count, s.duration_ms, s.start_time)
                    for s in summary.services
                ],
            )
            await conn.executemany(
                """
                INSERT INTO trace_edges(trace_id, parent_service, child_service, call_count, error_count, total_ms)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(trace_id, parent_service, child_service) DO UPDATE SET
                    call_count=excluded.call_count, error_count=excluded.error_count,
                    total_ms=excluded.total_ms
                """,
                [
                    (summary.trace_id, e.parent_service, e.child_service, e.call_count, e.error_count, e.total_ms)
                    for e in summary.edges
                ],
            )

    async def record_late_spans(self, trace_id: str, late_count: int, truncated: bool) -> None:
        await self.db.execute(
            "UPDATE traces SET late_span_count=?, truncated=? WHERE trace_id=?",
            (late_count, int(truncated), trace_id),
        )

    async def attach_batch(self, trace_ids: list[str], batch_id: str, object_key: str) -> None:
        if not trace_ids:
            return
        for start in range(0, len(trace_ids), 400):
            chunk = trace_ids[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            await self.db.execute(
                f"UPDATE traces SET batch_id=?, object_key=? WHERE trace_id IN ({placeholders})",
                [batch_id, object_key, *chunk],
            )

    # -- search ------------------------------------------------------------
    async def search_traces(
        self,
        trace_id: str | None = None,
        service: str | None = None,
        operation: str | None = None,
        status: str | None = None,
        since: float | None = None,
        until: float | None = None,
        min_duration_ms: float | None = None,
        only_sampled: bool | None = None,
        sort: str = "start_time",
        order: str = "desc",
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        if trace_id:
            where.append("trace_id LIKE ?")
            params.append(f"%{trace_id}%")
        if service:
            where.append(
                "trace_id IN (SELECT trace_id FROM trace_services WHERE service = ?)"
            )
            params.append(service)
        if operation:
            where.append("root_operation LIKE ?")
            params.append(f"%{operation}%")
        if status:
            where.append("status = ?")
            params.append(status)
        if since:
            where.append("start_time >= ?")
            params.append(since)
        if until:
            where.append("start_time <= ?")
            params.append(until)
        if min_duration_ms:
            where.append("duration_ms >= ?")
            params.append(min_duration_ms)
        if only_sampled is not None:
            where.append("sampled = ?")
            params.append(int(only_sampled))

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sort_col = {
            "start_time": "start_time",
            "duration": "duration_ms",
            "span_count": "span_count",
        }.get(sort, "start_time")
        direction = "DESC" if order.lower() != "asc" else "ASC"
        offset = max(0, (page - 1) * page_size)

        total = await self.db.scalar(f"SELECT COUNT(*) FROM traces {where_sql}", params)
        rows = await self.db.fetchall(
            f"SELECT * FROM traces {where_sql} ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        )
        return {
            "items": [_row_to_trace(row) for row in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "pages": max(1, -(-int(total or 0) // page_size)),
        }

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
        if row is None:
            return None
        trace = _row_to_trace(row)
        spans: list[dict[str, Any]] = []
        warning = None
        if trace["object_key"]:
            try:
                blob = await self.store.get_object(trace["object_key"])
                for entry in decode_jsonl(decompress_bytes(blob)):
                    if entry.get("trace_id") == trace_id or entry.get("trace", {}).get("trace_id") == trace_id:
                        spans = entry.get("spans") or entry.get("trace", {}).get("spans", [])
                        break
            except FileNotFoundError:
                warning = "batch object not found in object storage"
            except StorageUnavailable as exc:
                warning = f"object storage unavailable: {exc}"
            except Exception as exc:  # corrupt object / decode errors
                warning = f"could not decode batch object: {exc}"
        elif not trace["sampled"]:
            warning = "trace was discarded by the tail sampler; only metadata was retained"
        else:
            warning = "trace has not been assigned to a storage batch yet"

        services = await self.db.fetchall(
            "SELECT service, span_count, error_count, duration_ms FROM trace_services WHERE trace_id = ? ORDER BY service",
            (trace_id,),
        )
        trace["services"] = [
            {
                "service": s["service"],
                "span_count": s["span_count"],
                "error_count": s["error_count"],
                "duration_ms": round(s["duration_ms"], 3),
            }
            for s in services
        ]
        trace["spans"] = build_waterfall(spans)
        trace["warning"] = warning
        return trace

    # -- aggregates --------------------------------------------------------
    async def overview(self, since: float, until: float, slow_threshold_ms: float) -> dict[str, Any]:
        window = [since, until]
        total = int(await self.db.scalar(
            "SELECT COUNT(*) FROM traces WHERE start_time BETWEEN ? AND ?", window) or 0)
        errors = int(await self.db.scalar(
            "SELECT COUNT(*) FROM traces WHERE has_error=1 AND start_time BETWEEN ? AND ?", window) or 0)
        sampled = int(await self.db.scalar(
            "SELECT COUNT(*) FROM traces WHERE sampled=1 AND start_time BETWEEN ? AND ?", window) or 0)
        slow = int(await self.db.scalar(
            "SELECT COUNT(*) FROM traces WHERE duration_ms >= ? AND start_time BETWEEN ? AND ?",
            [slow_threshold_ms, *window]) or 0)
        avg_latency = float(await self.db.scalar(
            "SELECT COALESCE(AVG(duration_ms),0) FROM traces WHERE start_time BETWEEN ? AND ?", window) or 0)
        span_total = int(await self.db.scalar(
            "SELECT COALESCE(SUM(span_count),0) FROM traces WHERE start_time BETWEEN ? AND ?", window) or 0)
        durations = await self.db.fetchall(
            "SELECT duration_ms FROM traces WHERE start_time BETWEEN ? AND ? ORDER BY duration_ms", window)
        values = [r["duration_ms"] for r in durations]
        p95 = _percentile(values, 95)
        p50 = _percentile(values, 50)
        p99 = _percentile(values, 99)
        duration_s = max(1.0, until - since)
        # Ingestion throughput is a *current* rate: spans indexed in the last 60s.
        recent = time.time() - 60
        recent_spans = int(await self.db.scalar(
            "SELECT COALESCE(SUM(span_count),0) FROM traces WHERE start_time >= ?", (recent,)) or 0)
        recent_traces = int(await self.db.scalar(
            "SELECT COUNT(*) FROM traces WHERE start_time >= ?", (recent,)) or 0)
        return {
            "total_traces": total,
            "error_rate": round(errors / total * 100, 2) if total else 0.0,
            "error_traces": errors,
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95, 1),
            "p50_latency_ms": round(p50, 1),
            "p99_latency_ms": round(p99, 1),
            "slow_traces": slow,
            "sampling_rate": round(sampled / total * 100, 2) if total else 0.0,
            "retained_traces": sampled,
            "total_spans": span_total,
            "throughput_spans_per_s": round(recent_spans / 60, 2),
            "trace_rate_per_min": recent_traces,
            "recent_spans_60s": recent_spans,
            "window_seconds": round(duration_s, 1),
        }

    async def timeseries(self, since: float, until: float, buckets: int = 24) -> list[dict[str, Any]]:
        if buckets < 2:
            buckets = 2
        width = max(1.0, (until - since) / buckets)
        rows = await self.db.fetchall(
            """
            SELECT CAST((start_time - ?) / ? AS INTEGER) AS bucket,
                   COUNT(*) AS requests,
                   SUM(CASE WHEN has_error=1 THEN 1 ELSE 0 END) AS errors,
                   AVG(duration_ms) AS avg_ms,
                   SUM(span_count) AS spans
            FROM traces
            WHERE start_time >= ? AND start_time <= ?
            GROUP BY bucket ORDER BY bucket
            """,
            (since, width, since, until),
        )
        # Return every bucket in the range so the chart shows zeros instead of gaps
        # for periods without telemetry instead of collapsing the x-axis.
        by_bucket: dict[int, Any] = {}
        for row in rows:
            bucket_index = int(row["bucket"] or 0)
            if 0 <= bucket_index < buckets:
                by_bucket[bucket_index] = row

        out = []
        for bucket_index in range(buckets):
            ts = since + bucket_index * width
            row = by_bucket.get(bucket_index)
            spans = int(row["spans"] or 0) if row is not None else 0
            out.append(
                {
                    "ts": ts,
                    "label": time.strftime("%H:%M", time.localtime(ts)),
                    "requests": int(row["requests"] or 0) if row is not None else 0,
                    "errors": int(row["errors"] or 0) if row is not None else 0,
                    "latency_ms": round(float(row["avg_ms"] or 0), 1) if row is not None else 0,
                    "spans": spans,
                    "throughput": round(spans / width, 2),
                }
            )
        return out

    async def service_stats(self, since: float, until: float) -> list[dict[str, Any]]:
        """Aggregate per-service metrics from indexed trace metadata."""
        rows = await self.db.fetchall(
            """
            SELECT ts.service AS service,
                   COUNT(*) AS requests,
                   SUM(ts.error_count) AS errors,
                   AVG(ts.duration_ms) AS avg_ms,
                   MAX(ts.start_time) AS last_seen,
                   SUM(ts.span_count) AS spans
            FROM trace_services ts
            JOIN traces t ON t.trace_id = ts.trace_id
            WHERE t.start_time BETWEEN ? AND ?
            GROUP BY ts.service
            ORDER BY requests DESC
            """,
            (since, until),
        )
        out = []
        for row in rows:
            requests = int(row["requests"] or 0)
            errors = int(row["errors"] or 0)
            out.append(
                {
                    "service": row["service"],
                    "requests": requests,
                    "errors": errors,
                    "error_rate": round(errors / requests * 100, 2) if requests else 0.0,
                    "avg_latency_ms": round(float(row["avg_ms"] or 0), 1),
                    "total_duration_ms": round(float(row["avg_ms"] or 0) * requests, 1),
                    "spans": int(row["spans"] or 0),
                    "last_seen": row["last_seen"],
                    "health": _health(errors / requests if requests else 0, float(row["avg_ms"] or 0)),
                }
            )
        return out

    async def service_edges(self, since: float, until: float) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT e.parent_service AS source, e.child_service AS target,
                   SUM(e.call_count) AS calls, SUM(e.error_count) AS errors,
                   AVG(e.total_ms) AS avg_ms
            FROM trace_edges e
            JOIN traces t ON t.trace_id = e.trace_id
            WHERE t.start_time BETWEEN ? AND ?
            GROUP BY e.parent_service, e.child_service
            ORDER BY calls DESC
            """,
            (since, until),
        )
        out = []
        for row in rows:
            calls = int(row["calls"] or 0)
            errors = int(row["errors"] or 0)
            error_rate = (errors / calls * 100) if calls else 0.0
            out.append(
                {
                    "source": row["source"],
                    "target": row["target"],
                    "calls": calls,
                    "errors": errors,
                    "error_rate": round(error_rate, 2),
                    "avg_latency_ms": round(float(row["avg_ms"] or 0), 1),
                    "health": "healthy" if error_rate < 2 else ("warning" if error_rate < 15 else "error"),
                }
            )
        return out

    async def service_detail(self, service: str, since: float, until: float) -> dict[str, Any] | None:
        stats = await self.service_stats(since, until)
        match = next((s for s in stats if s["service"] == service), None)
        if match is None:
            return None
        operations = await self.db.fetchall(
            """
            SELECT t.root_operation AS operation, COUNT(*) AS requests, AVG(t.duration_ms) AS avg_ms
            FROM traces t JOIN trace_services ts ON ts.trace_id = t.trace_id
            WHERE ts.service = ? AND t.start_time BETWEEN ? AND ?
            GROUP BY t.root_operation ORDER BY requests DESC LIMIT 10
            """,
            (service, since, until),
        )
        inbound = await self.service_edges(since, until)
        match["operations"] = [
            {"operation": r["operation"], "requests": int(r["requests"]), "avg_latency_ms": round(float(r["avg_ms"] or 0), 1)}
            for r in operations
        ]
        match["inbound_edges"] = [e for e in inbound if e["target"] == service]
        match["outbound_edges"] = [e for e in inbound if e["source"] == service]
        return match

    # -- batches -----------------------------------------------------------
    async def upsert_batch(self, batch: Any) -> None:
        await self.db.execute(
            """
            INSERT INTO batches(batch_id, trace_count, span_count, original_bytes, compressed_bytes,
                                object_key, status, attempts, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(batch_id) DO UPDATE SET
                status=excluded.status, attempts=excluded.attempts
            """,
            (
                batch.batch_id, batch.trace_count, batch.span_count, batch.original_bytes,
                batch.compressed_bytes, batch.object_key, batch.status, batch.attempts, batch.created_at,
            ),
        )

    async def mark_batch_result(
        self, batch_id: str, status: str, attempts: int, error: str | None, duration_ms: float | None = None
    ) -> None:
        await self.db.execute(
            """
            UPDATE batches SET status=?, attempts=?, last_error=?, uploaded_at=?, duration_ms=?
            WHERE batch_id=?
            """,
            (
                status, attempts, error,
                time.time() if status == "uploaded" else None,
                duration_ms, batch_id,
            ),
        )

    async def list_batches(self, status: str | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        where = "WHERE status = ?" if status else ""
        params: list[Any] = [status] if status else []
        total = await self.db.scalar(f"SELECT COUNT(*) FROM batches {where}", params)
        rows = await self.db.fetchall(
            f"SELECT * FROM batches {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, max(0, (page - 1) * page_size)],
        )
        items = []
        for row in rows:
            items.append(
                {
                    "batch_id": row["batch_id"],
                    "trace_count": row["trace_count"],
                    "span_count": row["span_count"],
                    "original_bytes": row["original_bytes"],
                    "compressed_bytes": row["compressed_bytes"],
                    "compression_ratio": round(row["compressed_bytes"] / row["original_bytes"], 4)
                    if row["original_bytes"] else 0,
                    "object_key": row["object_key"],
                    "status": row["status"],
                    "attempts": row["attempts"],
                    "last_error": row["last_error"],
                    "created_at": row["created_at"],
                    "uploaded_at": row["uploaded_at"],
                    "duration_ms": row["duration_ms"],
                }
            )
        return {"items": items, "total": int(total or 0), "page": page, "page_size": page_size}

    async def batch_detail(self, batch_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM batches WHERE batch_id = ?", (batch_id,))
        if row is None:
            return None
        traces = await self.db.fetchall(
            "SELECT trace_id, root_service, root_operation, duration_ms, status, start_time FROM traces WHERE batch_id = ? ORDER BY start_time",
            (batch_id,),
        )
        data = {k: row[k] for k in row.keys()}
        data["compression_ratio"] = round(row["compressed_bytes"] / row["original_bytes"], 4) if row["original_bytes"] else 0
        data["traces"] = [dict(t) for t in traces]
        return data

    async def pending_batches(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM batches WHERE status IN ('pending','uploading','failed') ORDER BY created_at"
        )
        return [dict(row) for row in rows]

    async def storage_stats(self) -> dict[str, Any]:
        row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS batches, COALESCE(SUM(trace_count),0) AS traces,
                   COALESCE(SUM(span_count),0) AS spans,
                   COALESCE(SUM(original_bytes),0) AS original,
                   COALESCE(SUM(compressed_bytes),0) AS compressed,
                   SUM(CASE WHEN status='uploaded' THEN 1 ELSE 0 END) AS uploaded,
                   SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
            FROM batches
            """
        )
        original = int(row["original"] or 0)
        compressed = int(row["compressed"] or 0)
        db_size = 0
        if getattr(self.db, "backend", "sqlite") == "postgres":
            db_size = int(await self.db.scalar("SELECT pg_database_size(current_database())") or 0)
        else:
            try:
                from pathlib import Path
                from app.config.settings import settings as _s
                db_size = Path(_s.sqlite_path).stat().st_size if Path(_s.sqlite_path).exists() else 0
            except OSError:
                pass
        return {
            "batches": int(row["batches"] or 0),
            "uploaded_batches": int(row["uploaded"] or 0),
            "pending_batches": int(row["pending"] or 0),
            "failed_batches": int(row["failed"] or 0),
            "traces": int(row["traces"] or 0),
            "spans": int(row["spans"] or 0),
            "original_bytes": original,
            "compressed_bytes": compressed,
            "compression_ratio": round(compressed / original, 4) if original else 0,
            "space_saved_bytes": max(0, original - compressed),
            "sqlite_bytes": db_size,
            "object_store_backend": self.store.backend,
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return float(ordered[index])


def _health(error_rate: float, avg_ms: float) -> str:
    if error_rate >= 0.15:
        return "error"
    if error_rate >= 0.02 or avg_ms >= 800:
        return "warning"
    return "healthy"


def build_waterfall(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add depth, relative offsets and parent links; sort for waterfall display."""
    if not spans:
        return []
    by_id = {span["span_id"]: span for span in spans}
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for span in spans:
        parent = span.get("parent_span_id")
        if parent and parent in by_id:
            children.setdefault(parent, []).append(span["span_id"])
        else:
            roots.append(span["span_id"])

    trace_start = min(int(span["start_time_unix_nano"]) for span in spans)
    trace_end = max(int(span["end_time_unix_nano"]) for span in spans)
    total = max(1, trace_end - trace_start)

    depth_of: dict[str, int] = {}
    order: list[str] = []
    stack = [(rid, 0) for rid in roots] if roots else [(span["span_id"], 0) for span in spans]
    seen: set[str] = set()
    while stack:
        span_id, depth = stack.pop(0)
        if span_id in seen:
            continue
        seen.add(span_id)
        depth_of[span_id] = depth
        order.append(span_id)
        for child in children.get(span_id, []):
            stack.append((child, depth + 1))
    for span in spans:  # orphan safety net
        if span["span_id"] not in seen:
            order.append(span["span_id"])
            depth_of[span["span_id"]] = 0

    index_of = {span_id: idx for idx, span_id in enumerate(order)}
    ordered = sorted(
        spans,
        key=lambda s: (index_of.get(s["span_id"], 0)),
    )
    out = []
    for span in ordered:
        start = int(span["start_time_unix_nano"])
        end = int(span["end_time_unix_nano"])
        out.append(
            {
                "span_id": span["span_id"],
                "parent_span_id": span.get("parent_span_id"),
                "trace_id": span["trace_id"],
                "name": span["name"],
                "service": span["service"],
                "kind": span.get("kind", "SERVER"),
                "status": span.get("status", "UNSET"),
                "status_message": span.get("status_message", ""),
                "start_time": span["start_time_unix_nano"] / 1e9,
                "duration_ms": round((end - start) / 1e6, 3),
                "offset_ms": round((start - trace_start) / 1e6, 3),
                "offset_pct": round((start - trace_start) / total * 100, 3),
                "width_pct": max(0.4, round((end - start) / total * 100, 3)),
                "depth": depth_of.get(span["span_id"], 0),
                "attributes": span.get("attributes", {}),
                "events": span.get("events", []),
            }
        )
    return out


class EventLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, category: str, message: str, level: str = "info", meta: dict[str, Any] | None = None) -> None:
        await self.db.execute(
            "INSERT INTO events(ts, level, category, message, meta) VALUES (?,?,?,?,?)",
            (time.time(), level, category, message, json.dumps(meta or {})),
        )
        log.info(message, extra={"category": category, "level": level, **(meta or {})})

    async def list(self, limit: int = 40, since: float | None = None, category: str | None = None) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if since:
            where.append("ts >= ?")
            params.append(since)
        if category:
            where.append("category = ?")
            params.append(category)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = await self.db.fetchall(
            f"SELECT * FROM events {where_sql} ORDER BY ts DESC LIMIT ?", [*params, limit]
        )
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "level": row["level"],
                "category": row["category"],
                "message": row["message"],
                "meta": json.loads(row["meta"] or "{}"),
            }
            for row in rows
        ]
