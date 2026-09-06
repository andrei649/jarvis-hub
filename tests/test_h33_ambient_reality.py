from __future__ import annotations

import asyncio

from agents.core.observability import ambient_reality
from agents.core.observability.ambient_reality import (
    H33_AMBIENT_REALITY_CASES,
    run_ambient_reality_pack,
)
from agents.core.observability.reality_harness import CASES, run_reality


def test_ambient_reality_pack_meets_scale_and_zero_bypass_gates():
    report = asyncio.run(run_ambient_reality_pack())

    assert report["passed"] is True, report
    assert set(report["environment"]) == {
        "machine",
        "platform",
        "python",
        "sqlite",
        "timer",
    }
    assert all(report["environment"].values())
    assert [item["monitors"] for item in report["scenarios"]] == [1, 10, 100]
    for scenario in report["scenarios"]:
        assert scenario["p95_decision_ms"] <= 100
        assert scenario["incremental_memory_bytes"] <= 64 * 1024 * 1024
        assert scenario["queue_depth_peak"] <= 2_048
        assert scenario["critical_dropped"] == 0
        assert scenario["events_per_second"] >= 10
        assert scenario["sample_size"] >= 10
    assert report["attention"] == {
        "attempted": 6,
        "delivered": 4,
        "downgraded": 2,
        "remaining_after_restart": 0,
    }
    assert report["counters"]["ungoverned_actions"] == 0
    assert report["counters"]["action_calls"] == 0
    assert report["counters"]["tainted_interrupts"] == 0
    assert report["counters"]["tainted_downgrades"] == 1
    assert sum(report["counters"]["rungs"].values()) >= 111


def test_ambient_reality_cases_are_registered_and_green():
    names = {case.name for case in H33_AMBIENT_REALITY_CASES}
    assert names == {
        "ambient-scale-and-zero-bypass",
        "ambient-persistent-attention-budget",
    }
    assert names <= {case.name for case in CASES}

    result = asyncio.run(run_reality(H33_AMBIENT_REALITY_CASES, promote=False))

    assert result["passed"] == result["total"] == 2, result
    assert all(
        item["metadata"]["counters"]["ungoverned_actions"] == 0
        for item in result["results"]
    )
    assert all(item["metadata"]["environment"] for item in result["results"])


def _measurement(**overrides):
    base = {
        "monitors": 1,
        "sample_size": 10,
        "p95_decision_ms": 3.0,
        "incremental_memory_bytes": 1024,
        "queue_depth_peak": 1,
        "events_per_second": 400.0,
        "critical_dropped": 0,
        "critical_pending_after_drain": 0,
        "duplicate_status": "duplicate",
        "decisions": 10,
        "proposals": 0,
        "zero_drop_upper_95": 0.3,
    }
    base.update(overrides)
    return base


def test_timing_only_miss_is_remeasured_but_governance_misses_never_are(monkeypatch):
    """A loaded host may miss the latency gate while every governance gate holds; that
    is re-measured (bounded) and recorded. A governance miss is final on the first try."""
    calls = []

    def fake_scenario(root, count):
        calls.append((root.name, count))
        if count == 10 and len([c for c in calls if c[1] == 10]) == 1:
            return _measurement(monitors=10, p95_decision_ms=250.0), {"ignore": 10}
        if count == 100:
            return _measurement(monitors=100, critical_dropped=1), {"ignore": 100}
        return _measurement(monitors=count), {"ignore": count}

    monkeypatch.setattr(ambient_reality, "_scenario", fake_scenario)
    report = asyncio.run(ambient_reality._scale_report())

    by_monitors = {s["monitors"]: s for s in report["scenarios"]}
    assert by_monitors[1]["timing_retries"] == 0
    assert by_monitors[10]["timing_retries"] == 1
    assert by_monitors[10]["p95_decision_ms"] == 3.0
    # The governance miss was not retried and still fails the pack.
    assert by_monitors[100]["timing_retries"] == 0
    assert by_monitors[100]["critical_dropped"] == 1
    assert report["passed"] is False
    assert [c[1] for c in calls] == [1, 10, 10, 100]
    assert calls[2][0] == "timing-retry-10-1"


def test_timing_retries_are_bounded(monkeypatch):
    def always_slow(root, count):
        return _measurement(monitors=count, events_per_second=2.0), {"ignore": count}

    monkeypatch.setattr(ambient_reality, "_scenario", always_slow)
    report = asyncio.run(ambient_reality._scale_report())

    assert report["passed"] is False
    assert all(s["timing_retries"] == ambient_reality._TIMING_RETRIES for s in report["scenarios"])
