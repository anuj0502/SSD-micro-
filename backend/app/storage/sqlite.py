"""Thin async wrapper over SQLite (aiosqlite) with WAL and a single writer lock."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Iterable, Sequence

import aiosqlite

from app.config.settings import settings
from app.storage.schema import SCHEMA_STATEMENTS
from app.utils.logging import get_logger

log = get_logger("traceflow.db")


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.sqlite_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._healthy = False

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        for statement in SCHEMA_STATEMENTS:
            await self._conn.execute(statement)
        await self._conn.commit()
        self._healthy = True
        log.info("sqlite connected", extra={"path": self.path})

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._healthy = False

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a write statement, returning affected row count."""
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            await self.conn.commit()
            return cur.rowcount

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        async with self._lock:
            cur = await self.conn.executemany(sql, [tuple(r) for r in rows])
            await self.conn.commit()
            return cur.rowcount

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, tuple(params))
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        cur = await self.conn.execute(sql, tuple(params))
        row = await cur.fetchone()
        await cur.close()
        return row

    async def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        return None if row is None else row[0]

    @asynccontextmanager
    async def transaction(self):
        """Write transaction guarded by the writer lock."""
        async with self._lock:
            try:
                yield self.conn
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise


db = Database()
