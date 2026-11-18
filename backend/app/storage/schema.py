"""SQLite schema.

SQLite is used exclusively for *searchable metadata*: trace rows, per-service
aggregates, batch manifests, events, metrics rollups and runtime settings.
Raw spans live only in compressed JSONL objects in object storage.
"""

SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS traces (
        trace_id          TEXT PRIMARY KEY,
        root_service      TEXT NOT NULL,
        root_operation    TEXT NOT NULL,
        start_time        REAL NOT NULL,
        end_time          REAL NOT NULL,
        duration_ms       REAL NOT NULL,
        span_count        INTEGER NOT NULL DEFAULT 0,
        service_count     INTEGER NOT NULL DEFAULT 0,
        status            TEXT NOT NULL,               -- success | error | slow
        has_error         INTEGER NOT NULL DEFAULT 0,
        error_message     TEXT,
        sampled           INTEGER NOT NULL DEFAULT 0,
        decision          TEXT NOT NULL,               -- retained | discarded
        decision_reason   TEXT NOT NULL,               -- error | slow | sampled | random_discard
        late_span_count   INTEGER NOT NULL DEFAULT 0,
        truncated         INTEGER NOT NULL DEFAULT 0,
        batch_id          TEXT,
        object_key        TEXT,
        created_at        REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status, start_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_traces_service ON traces(root_service, start_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_traces_batch ON traces(batch_id)",
    """
    CREATE TABLE IF NOT EXISTS trace_services (
        trace_id     TEXT NOT NULL,
        service      TEXT NOT NULL,
        span_count   INTEGER NOT NULL DEFAULT 0,
        error_count  INTEGER NOT NULL DEFAULT 0,
        duration_ms  REAL NOT NULL DEFAULT 0,
        start_time   REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (trace_id, service)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_services_service ON trace_services(service)",
    """
    CREATE TABLE IF NOT EXISTS trace_edges (
        trace_id       TEXT NOT NULL,
        parent_service TEXT NOT NULL,
        child_service  TEXT NOT NULL,
        call_count     INTEGER NOT NULL DEFAULT 1,
        error_count    INTEGER NOT NULL DEFAULT 0,
        total_ms       REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (trace_id, parent_service, child_service)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_edges_pair ON trace_edges(parent_service, child_service)",
    """
    CREATE TABLE IF NOT EXISTS seen_spans (
        span_id   TEXT PRIMARY KEY,
        trace_id  TEXT NOT NULL,
        seen_at   REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_seen_spans_seen ON seen_spans(seen_at)",
    """
    CREATE TABLE IF NOT EXISTS batches (
        batch_id         TEXT PRIMARY KEY,
        trace_count      INTEGER NOT NULL,
        span_count       INTEGER NOT NULL DEFAULT 0,
        original_bytes   INTEGER NOT NULL,
        compressed_bytes INTEGER NOT NULL,
        object_key       TEXT NOT NULL,
        status           TEXT NOT NULL,   -- pending | uploading | uploaded | failed
        attempts         INTEGER NOT NULL DEFAULT 0,
        last_error       TEXT,
        created_at       REAL NOT NULL,
        uploaded_at      REAL,
        duration_ms      REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       REAL NOT NULL,
        level    TEXT NOT NULL,
        category TEXT NOT NULL,
        message  TEXT NOT NULL,
        meta     TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)",
    """
    CREATE TABLE IF NOT EXISTS metrics (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          REAL NOT NULL,
        stage       TEXT NOT NULL,
        processed   INTEGER NOT NULL DEFAULT 0,
        failed      INTEGER NOT NULL DEFAULT 0,
        pending     INTEGER NOT NULL DEFAULT 0,
        latency_ms  REAL NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_metrics_stage_ts ON metrics(stage, ts DESC)",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS benchmark_runs (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        config     TEXT NOT NULL,
        result     TEXT,
        status     TEXT NOT NULL,
        error      TEXT,
        created_at REAL NOT NULL,
        finished_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fault_runs (
        id          TEXT PRIMARY KEY,
        scenario    TEXT NOT NULL,
        status      TEXT NOT NULL,
        details     TEXT,
        started_at  REAL NOT NULL,
        finished_at REAL
    )
    """,
]

EXPECTED_TABLES = {
    "traces", "trace_services", "trace_edges", "seen_spans", "batches",
    "events", "metrics", "settings", "benchmark_runs", "fault_runs",
}
