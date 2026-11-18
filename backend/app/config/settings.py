"""Application configuration.

All values are overridable through environment variables so the same image can
run against Docker services or the local fallbacks (memory stream + filesystem
object store).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TraceFlow"
    environment: str = "local"
    log_level: str = "INFO"

    # --- API ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

    # --- storage ---
    data_dir: str = "./data"
    sqlite_path: str = "./data/traceflow.db"  # legacy local/test mode
    database_url: str | None = None  # Render managed Postgres URL

    # auto -> try MinIO, fall back to the filesystem store
    object_store_backend: str = "auto"  # auto | minio | filesystem | postgres
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "traceflow"
    minio_secret_key: str = "traceflow123"
    minio_bucket: str = "traceflow-telemetry"
    minio_secure: bool = False

    # auto -> try Redis, fall back to the in-process stream
    buffer_backend: str = "auto"  # auto | redis | memory
    redis_url: str = "redis://localhost:6379/0"
    stream_key: str = "traceflow:spans"
    consumer_group: str = "traceflow-processors"
    consumer_name: str = "collector-1"
    stream_maxlen: int = 200_000
    reclaim_idle_ms: int = 15_000

    # --- ingestion ---
    local_spill_maxsize: int = 5_000
    ingestion_batch_size: int = 200
    ingestion_block_ms: int = 1_000

    # --- sampled processing defaults (persisted, mutable at runtime) ---
    sampling_error_rate: float = 1.0
    sampling_slow_threshold_ms: float = 500.0
    sampling_success_rate: float = 0.10
    sampling_completion_timeout_s: float = 5.0
    sampling_late_policy: str = "drop"  # drop | accept_if_buffered
    sampling_deterministic: bool = True

    # --- batching defaults (persisted, mutable at runtime) ---
    batch_size: int = 100
    batch_flush_interval_s: float = 5.0
    batch_max_attempts: int = 5
    gzip_level: int = 6

    # --- worker timings ---
    processing_tick_ms: int = 250
    metrics_interval_s: float = 5.0
    worker_restart_delay_s: float = 2.0
    trace_retention_hours: float = 72.0

    # --- optional bounded demo telemetry (off outside the Render demo) ---
    auto_demo_enabled: bool = False
    auto_demo_initial_traces: int = 24
    auto_demo_traces_per_interval: int = 1
    auto_demo_interval_s: float = 15.0
    auto_demo_error_probability: float = 0.12
    auto_demo_slow_probability: float = 0.15

    # --- e-commerce simulation ---
    gateway_url: str = "http://localhost:8001"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
