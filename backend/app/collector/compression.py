"""Trace batch compression (JSONL + gzip)."""
from __future__ import annotations

import gzip
import json
from typing import Any, Iterable

from app.config.settings import settings


def encode_jsonl(entries: Iterable[dict[str, Any]]) -> bytes:
    lines = [json.dumps(entry, separators=(",", ":"), default=str) for entry in entries]
    return ("\n".join(lines) + "\n").encode("utf-8")


def compress_bytes(raw: bytes, level: int | None = None) -> bytes:
    return gzip.compress(raw, compresslevel=level if level is not None else settings.gzip_level)


def decompress_bytes(blob: bytes) -> bytes:
    return gzip.decompress(blob)


def decode_jsonl(raw: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def compression_ratio(original: int, compressed: int) -> float:
    if original <= 0:
        return 0.0
    return round(compressed / original, 4)
