from __future__ import annotations

import pytest

from app.collector.aggregation import ServiceStat, TraceSummary
from app.collector.sampling import SamplingConfig, Sampler, parse_config


def make_trace(trace_id: str = "a" * 32, duration_ms: float = 100, has_error: bool = False) -> TraceSummary:
    return TraceSummary(
        trace_id=trace_id,
        root_service="api-gateway",
        root_operation="POST /checkout",
        start_time=1_700_000_000.0,
        end_time=1_700_000_000.1,
        duration_ms=duration_ms,
        span_count=4,
        status="error" if has_error else ("slow" if duration_ms >= 500 else "success"),
        has_error=has_error,
        error_message="boom" if has_error else None,
        services=[ServiceStat("api-gateway", 1, int(has_error), duration_ms)],
        edges=[],
        spans=[],
    )


def test_errors_are_always_retained():
    sampler = Sampler(SamplingConfig(error_rate=1.0, success_rate=0.0))
    decision = sampler.decide(make_trace(has_error=True))
    assert decision.retained and decision.reason == "error"


def test_slow_traces_are_retained_above_threshold():
    sampler = Sampler(SamplingConfig(slow_threshold_ms=500, success_rate=0.0))
    assert sampler.decide(make_trace(duration_ms=800)).retained
    assert sampler.decide(make_trace(duration_ms=499, trace_id="b" * 32)).retained is False


def test_successful_traces_respect_sample_rate():
    never = Sampler(SamplingConfig(success_rate=0.0))
    always = Sampler(SamplingConfig(success_rate=1.0))
    assert never.decide(make_trace(trace_id="c" * 32)).retained is False
    assert always.decide(make_trace(trace_id="d" * 32)).retained is True


def test_deterministic_decision_is_stable():
    sampler = Sampler(SamplingConfig(success_rate=0.5, deterministic=True))
    first = sampler.decide(make_trace(trace_id="e" * 32))
    second = Sampler(SamplingConfig(success_rate=0.5, deterministic=True)).decide(
        make_trace(trace_id="e" * 32)
    )
    assert (first.retained, first.score) == (second.retained, second.score)


def test_sampling_statistics_track_retention():
    sampler = Sampler(SamplingConfig(success_rate=0.0))
    for i in range(5):
        sampler.decide(make_trace(trace_id=f"{i:032x}", has_error=i == 0))
    snapshot = sampler.snapshot()
    assert snapshot["stats"]["evaluated"] == 5
    assert snapshot["stats"]["retained"] == 1
    assert snapshot["stats"]["retention_rate"] == 20.0
    assert snapshot["stats"]["reduction_rate"] == 80.0


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        parse_config(
            {"success_rate": 1.5, "error_rate": 1.0, "slow_threshold_ms": 500, "completion_timeout_s": 5}
        )
    with pytest.raises(ValueError):
        parse_config(
            {"success_rate": 0.1, "error_rate": 1.0, "slow_threshold_ms": 500,
             "completion_timeout_s": 5, "late_policy": "explode"}
        )
