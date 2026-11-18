"""Custom tail-based sampling engine.

Policy (all values configurable at runtime through the API/UI):

1. Errors are retained at ``error_rate`` (default 100%).
2. Traces whose total duration >= ``slow_threshold_ms`` are always retained.
3. Successful traces are retained at ``success_rate`` (default 10%).
4. Everything else is discarded.

Sampling happens *after* the decision window closes (see TraceAssembler), so
the decision is made with the full trace in hand.

When ``deterministic`` is enabled the success sample is decided by a stable
hash of the trace id, so a given trace always gets the same verdict. This makes
tests and benchmark comparisons repeatable.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.collector.aggregation import TraceSummary


@dataclass
class SamplingConfig:
    error_rate: float = 1.0
    slow_threshold_ms: float = 500.0
    success_rate: float = 0.10
    completion_timeout_s: float = 5.0
    late_policy: str = "drop"
    deterministic: bool = True

    def validate(self) -> None:
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError("error_rate must be between 0 and 1")
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError("success_rate must be between 0 and 1")
        if self.slow_threshold_ms < 0:
            raise ValueError("slow_threshold_ms must be >= 0")
        if not 0.1 <= self.completion_timeout_s <= 300:
            raise ValueError("completion_timeout_s must be between 0.1 and 300")
        if self.late_policy not in {"drop", "accept_if_buffered"}:
            raise ValueError("late_policy must be 'drop' or 'accept_if_buffered'")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SamplingDecision:
    retained: bool
    reason: str  # error | slow | success_sampled | success_discarded
    score: float


class Sampler:
    def __init__(self, config: SamplingConfig | None = None) -> None:
        self.config = config or SamplingConfig()
        self.stats = {
            "evaluated": 0,
            "retained": 0,
            "discarded": 0,
            "error_retained": 0,
            "slow_retained": 0,
            "success_sampled": 0,
            "success_total": 0,
            "error_total": 0,
            "slow_total": 0,
            "retained_bytes_estimate": 0,
            "total_bytes_estimate": 0,
        }
        self.recent: list[dict[str, Any]] = []

    @staticmethod
    def _hash_score(trace_id: str) -> float:
        digest = hashlib.blake2b(trace_id.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") / float(2**64)

    def score(self, trace_id: str) -> float:
        if self.config.deterministic:
            return self._hash_score(trace_id)
        return time.time_ns() % 10_000 / 10_000

    def decide(self, trace: TraceSummary) -> SamplingDecision:
        cfg = self.config
        score = self.score(trace.trace_id)
        size_estimate = trace.span_count * 900 + 400

        if trace.has_error:
            self.stats["error_total"] += 1
            retained = score < cfg.error_rate
            reason = "error" if retained else "success_discarded"
            if retained:
                self.stats["error_retained"] += 1
        elif trace.duration_ms >= cfg.slow_threshold_ms:
            self.stats["slow_total"] += 1
            retained = True
            reason = "slow"
            self.stats["slow_retained"] += 1
        else:
            self.stats["success_total"] += 1
            retained = score < cfg.success_rate
            reason = "success_sampled" if retained else "success_discarded"
            if retained:
                self.stats["success_sampled"] += 1

        self.stats["evaluated"] += 1
        self.stats["total_bytes_estimate"] += size_estimate
        if retained:
            self.stats["retained"] += 1
            self.stats["retained_bytes_estimate"] += size_estimate
        else:
            self.stats["discarded"] += 1

        self.recent.insert(
            0,
            {
                "trace_id": trace.trace_id,
                "service": trace.root_service,
                "operation": trace.root_operation,
                "duration_ms": trace.duration_ms,
                "status": trace.status,
                "retained": retained,
                "reason": reason,
                "score": round(score, 4),
                "ts": time.time(),
            },
        )
        del self.recent[25:]

        return SamplingDecision(retained=retained, reason=reason, score=score)

    # -- reporting ---------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        stats = dict(self.stats)
        evaluated = stats["evaluated"] or 1
        retained = stats["retained"]
        stats["retention_rate"] = round(retained / evaluated * 100, 2)
        stats["reduction_rate"] = round((1 - retained / evaluated) * 100, 2)
        stats["estimated_storage_reduction"] = stats["reduction_rate"]
        return {
            "config": self.config.as_dict(),
            "stats": stats,
            "recent_decisions": self.recent[:15],
        }

    def reset(self) -> None:
        for key in self.stats:
            self.stats[key] = 0
        self.recent.clear()

    def describe_policy(self) -> str:
        cfg = self.config
        return (
            f"Keep {cfg.error_rate * 100:.0f}% of error traces; keep traces slower than "
            f"{cfg.slow_threshold_ms:.0f} ms; sample {cfg.success_rate * 100:.0f}% of successful "
            f"traces after a {cfg.completion_timeout_s:.0f}s completion window."
        )


def parse_config(raw: dict[str, Any]) -> SamplingConfig:
    cfg = SamplingConfig(**{k: v for k, v in raw.items() if k in SamplingConfig.__dataclass_fields__})
    cfg.validate()
    return cfg


def config_from_json(raw: str | None) -> SamplingConfig:
    if not raw:
        return SamplingConfig()
    try:
        return parse_config(json.loads(raw))
    except Exception:
        return SamplingConfig()
