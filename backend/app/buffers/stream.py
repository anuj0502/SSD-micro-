"""Ingestion buffer abstraction: Redis Streams with an in-process fallback.

Both implementations expose the same consumer-group semantics (add / read /
ack / reclaim) so the workers are identical in Docker and in a laptop run
without Redis.

Durability note: the in-process buffer is *not* durable across a collector
restart; it is a development fallback only. Redis Streams is the supported
durable buffer.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from typing import Any, Protocol

from app.config.settings import settings
from app.utils.logging import get_logger

log = get_logger("traceflow.stream")


class BufferUnavailable(RuntimeError):
    """Raised when the ingestion buffer cannot accept or serve messages."""


class StreamBuffer(Protocol):
    backend: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def add_spans(self, spans: list[dict[str, Any]]) -> str: ...
    async def read_batch(self, count: int, block_ms: int) -> list[tuple[str, list[dict[str, Any]]]]: ...
    async def ack(self, ids: list[str]) -> None: ...
    async def reclaim_pending(self, min_idle_ms: int, count: int) -> list[tuple[str, list[dict[str, Any]]]]: ...
    async def pending_count(self) -> int: ...
    async def stream_length(self) -> int: ...
    async def health(self) -> bool: ...


def _encode(spans: list[dict[str, Any]]) -> str:
    return json.dumps({"spans": spans, "enqueued_at": time.time()}, separators=(",", ":"))


def _decode(payload: str | bytes) -> list[dict[str, Any]]:
    data = json.loads(payload)
    return data.get("spans", [])


class MemoryStreamBuffer:
    """Bounded in-process stream with consumer-group-like pending tracking."""

    backend = "memory"

    def __init__(self) -> None:
        self._queue: deque[tuple[str, list[dict[str, Any]]]] = deque()
        self._pending: dict[str, tuple[list[dict[str, Any]], float]] = {}
        self._lock = asyncio.Lock()
        self._seq = 0
        self._outage_until = 0.0
        self._maxlen = settings.stream_maxlen
        self._wake = asyncio.Event()

    async def start(self) -> None:
        log.info("memory stream buffer started (Redis unavailable)")

    async def close(self) -> None:
        return None

    def simulate_outage(self, seconds: float) -> None:
        self._outage_until = time.time() + seconds

    @property
    def outage_active(self) -> bool:
        return time.time() < self._outage_until

    def _next_id(self) -> str:
        self._seq += 1
        return f"{int(time.time() * 1000)}-{self._seq}"

    async def add_spans(self, spans: list[dict[str, Any]]) -> str:
        if self.outage_active:
            raise BufferUnavailable("stream buffer is unavailable")
        async with self._lock:
            msg_id = self._next_id()
            self._queue.append((msg_id, spans))
            while len(self._queue) > self._maxlen:
                self._queue.popleft()
            self._wake.set()
            return msg_id

    async def read_batch(self, count: int, block_ms: int) -> list[tuple[str, list[dict[str, Any]]]]:
        deadline = time.monotonic() + block_ms / 1000
        while True:
            if self.outage_active:
                raise BufferUnavailable("stream buffer is unavailable")
            async with self._lock:
                if self._queue:
                    out: list[tuple[str, list[dict[str, Any]]]] = []
                    while self._queue and len(out) < count:
                        msg_id, spans = self._queue.popleft()
                        self._pending[msg_id] = (spans, time.time())
                        out.append((msg_id, spans))
                    return out
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass

    async def ack(self, ids: list[str]) -> None:
        async with self._lock:
            for msg_id in ids:
                self._pending.pop(msg_id, None)

    async def reclaim_pending(self, min_idle_ms: int, count: int) -> list[tuple[str, list[dict[str, Any]]]]:
        cutoff = time.time() - min_idle_ms / 1000
        async with self._lock:
            claimed: list[tuple[str, list[dict[str, Any]]]] = []
            for msg_id, (spans, delivered_at) in list(self._pending.items()):
                if delivered_at <= cutoff and len(claimed) < count:
                    self._pending[msg_id] = (spans, time.time())
                    claimed.append((msg_id, spans))
            return claimed

    async def pending_count(self) -> int:
        return len(self._pending)

    async def stream_length(self) -> int:
        return len(self._queue)

    async def health(self) -> bool:
        return not self.outage_active


class RedisStreamBuffer:
    """Redis Streams backed buffer using a consumer group (at-least-once)."""

    backend = "redis"

    def __init__(self) -> None:
        self._client: Any = None
        self._outage_until = 0.0

    async def start(self) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        await self._client.ping()
        try:
            await self._client.xgroup_create(
                settings.stream_key, settings.consumer_group, id="0", mkstream=True
            )
        except Exception as exc:  # BUSYGROUP -> group already exists
            if "BUSYGROUP" not in str(exc):
                raise
        log.info("redis stream buffer started", extra={"stream": settings.stream_key})

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def simulate_outage(self, seconds: float) -> None:
        self._outage_until = time.time() + seconds

    @property
    def outage_active(self) -> bool:
        return time.time() < self._outage_until

    def _guard(self) -> None:
        if self.outage_active:
            raise BufferUnavailable("stream buffer is unavailable (simulated outage)")

    async def add_spans(self, spans: list[dict[str, Any]]) -> str:
        self._guard()
        try:
            return await self._client.xadd(
                settings.stream_key,
                {"payload": _encode(spans)},
                maxlen=settings.stream_maxlen,
                approximate=True,
            )
        except Exception as exc:
            raise BufferUnavailable(str(exc)) from exc

    async def read_batch(self, count: int, block_ms: int) -> list[tuple[str, list[dict[str, Any]]]]:
        self._guard()
        response = await self._client.xreadgroup(
            settings.consumer_group,
            settings.consumer_name,
            {settings.stream_key: ">"},
            count=count,
            block=block_ms,
        )
        if not response:
            return []
        out: list[tuple[str, list[dict[str, Any]]]] = []
        for _stream, entries in response:
            for msg_id, fields in entries:
                out.append((msg_id, _decode(fields.get("payload", "{}"))))
        return out

    async def ack(self, ids: list[str]) -> None:
        if ids:
            await self._client.xack(settings.stream_key, settings.consumer_group, *ids)

    async def reclaim_pending(self, min_idle_ms: int, count: int) -> list[tuple[str, list[dict[str, Any]]]]:
        self._guard()
        result = await self._client.xautoclaim(
            settings.stream_key,
            settings.consumer_group,
            settings.consumer_name,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        # redis-py returns (next_cursor, messages[, deleted_ids])
        entries = result[1] if len(result) > 1 else []
        out: list[tuple[str, list[dict[str, Any]]]] = []
        for msg_id, fields in entries:
            if fields:
                out.append((msg_id, _decode(fields.get("payload", "{}"))))
        return out

    async def pending_count(self) -> int:
        summary = await self._client.xpending(settings.stream_key, settings.consumer_group)
        if isinstance(summary, dict):
            return int(summary.get("pending", 0))
        return int(summary or 0)

    async def stream_length(self) -> int:
        return int(await self._client.xlen(settings.stream_key))

    async def health(self) -> bool:
        if self._client is None or self.outage_active:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False


async def create_buffer() -> StreamBuffer:
    """Build the configured buffer, falling back to memory when allowed."""
    backend = settings.buffer_backend.lower()
    if backend in {"redis", "auto"}:
        redis_buffer = RedisStreamBuffer()
        try:
            await redis_buffer.start()
            return redis_buffer
        except Exception as exc:
            if backend == "redis":
                log.error("redis buffer unavailable", extra={"error": str(exc)})
                raise
            log.warning("redis unavailable, using memory stream fallback", extra={"error": str(exc)})
    buffer = MemoryStreamBuffer()
    await buffer.start()
    return buffer


def new_message_id() -> str:
    return uuid.uuid4().hex
