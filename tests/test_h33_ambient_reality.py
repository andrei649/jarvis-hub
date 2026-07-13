from __future__ import annotations

import asyncio

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
