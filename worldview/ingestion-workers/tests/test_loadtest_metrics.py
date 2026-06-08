"""Tests for the pure latency statistics + SLO verdict (ticket H19.1.6).

Exhaustive percentile math on hand-computed vectors (inclusive linear interpolation),
plus edge cases (empty / single / all-equal) and SLO pass/fail/boundary behaviour.
"""

from __future__ import annotations

import pytest

from worldview_ingest.loadtest.metrics import (
    LatencyRecorder,
    SloBreach,
    Stats,
    percentile,
    slo_check,
)

# ---- percentile() math -----------------------------------------------------------


def test_percentile_median_even() -> None:
    """p50 of [1,2,3,4] = rank 1.5 -> 2 + 0.5*(3-2) = 2.5."""
    assert percentile([1.0, 2.0, 3.0, 4.0], 50.0) == 2.5


def test_percentile_median_odd() -> None:
    """p50 of [1,2,3] = rank 1.0 -> 2.0 exactly."""
    assert percentile([1.0, 2.0, 3.0], 50.0) == 2.0


def test_percentile_min_max_endpoints() -> None:
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 0.0) == 10.0
    assert percentile(data, 100.0) == 50.0


def test_percentile_p95_hand_computed() -> None:
    """p95 of 0..100 (101 samples): rank = 0.95*100 = 95 -> value 95.0."""
    data = [float(i) for i in range(101)]
    assert percentile(data, 95.0) == 95.0
    assert percentile(data, 99.0) == 99.0
    assert percentile(data, 50.0) == 50.0


def test_percentile_interpolation_nontrivial() -> None:
    """p95 of [0..9] (n=10): rank=0.95*9=8.55 -> 8 + 0.55*(9-8)=8.55."""
    data = [float(i) for i in range(10)]
    assert percentile(data, 95.0) == pytest.approx(8.55)
    # p99: rank=0.99*9=8.91 -> 8.91.
    assert percentile(data, 99.0) == pytest.approx(8.91)


def test_percentile_single_sample() -> None:
    for p in (0.0, 50.0, 95.0, 99.0, 100.0):
        assert percentile([7.5], p) == 7.5


def test_percentile_all_equal() -> None:
    data = [3.0, 3.0, 3.0, 3.0]
    for p in (0.0, 50.0, 95.0, 99.0, 100.0):
        assert percentile(data, p) == 3.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50.0)


def test_percentile_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="in \\[0, 100\\]"):
        percentile([1.0], 101.0)
    with pytest.raises(ValueError, match="in \\[0, 100\\]"):
        percentile([1.0], -1.0)


# ---- Stats -----------------------------------------------------------------------


def test_stats_from_known_vector() -> None:
    """Full stats on 1..100 (n=100): p50=50.5, p95=95.05, p99=99.01, max=100, mean=50.5."""
    data = [float(i) for i in range(1, 101)]
    s = Stats.from_samples(data)
    assert s.count == 100
    assert s.p50 == pytest.approx(50.5)
    assert s.p95 == pytest.approx(95.05)
    assert s.p99 == pytest.approx(99.01)
    assert s.max == 100.0
    assert s.mean == pytest.approx(50.5)


def test_stats_unsorted_input_is_sorted() -> None:
    """from_samples sorts internally — order of input doesn't matter."""
    a = Stats.from_samples([4.0, 1.0, 3.0, 2.0])
    b = Stats.from_samples([1.0, 2.0, 3.0, 4.0])
    assert a == b
    assert a.max == 4.0


def test_stats_empty() -> None:
    s = Stats.from_samples([])
    assert s == Stats.empty()
    assert s.count == 0
    assert s.p50 is None and s.p95 is None and s.p99 is None
    assert s.max is None and s.mean is None
    assert s.to_dict() == {
        "count": 0, "p50": None, "p95": None, "p99": None, "max": None, "mean": None
    }


def test_stats_single() -> None:
    s = Stats.from_samples([0.25])
    assert s.count == 1
    assert s.p50 == s.p95 == s.p99 == s.max == s.mean == 0.25


# ---- LatencyRecorder -------------------------------------------------------------


def test_recorder_accumulates_and_stats() -> None:
    rec = LatencyRecorder()
    for v in [0.1, 0.2, 0.3, 0.4]:
        rec.record(v)
    assert len(rec) == 4
    assert rec.stats().p50 == pytest.approx(0.25)


def test_recorder_rejects_negative() -> None:
    rec = LatencyRecorder()
    with pytest.raises(ValueError, match="latency must be >= 0"):
        rec.record(-0.1)


# ---- slo_check -------------------------------------------------------------------


def _stats(p95: float, *, p50: float = 0.0, p99: float = 0.0) -> Stats:
    return Stats(count=10, p50=p50, p95=p95, p99=p99, max=p99, mean=p50)


def test_slo_pass_when_under_threshold() -> None:
    res = slo_check(_stats(p95=0.3), {"p95": 0.5})
    assert res.passed
    assert res.breaches == []
    assert res.to_dict() == {"passed": True, "breaches": []}


def test_slo_boundary_equal_passes() -> None:
    """value == threshold passes (SLO is strict '<' breach, so '==' is OK)."""
    res = slo_check(_stats(p95=0.5), {"p95": 0.5})
    assert res.passed


def test_slo_breach_when_over_threshold() -> None:
    res = slo_check(_stats(p95=0.7), {"p95": 0.5})
    assert not res.passed
    assert res.breaches == [SloBreach(metric="p95", value=0.7, threshold=0.5)]


def test_slo_multiple_thresholds_partial_breach() -> None:
    s = Stats(count=10, p50=0.1, p95=0.6, p99=0.9, max=0.9, mean=0.2)
    res = slo_check(s, {"p50": 0.5, "p95": 0.5, "p99": 1.0})
    assert not res.passed
    assert [b.metric for b in res.breaches] == ["p95"]


def test_slo_empty_stats_is_a_breach() -> None:
    """No samples -> every configured threshold breaches with value inf."""
    res = slo_check(Stats.empty(), {"p95": 0.5})
    assert not res.passed
    assert len(res.breaches) == 1
    assert res.breaches[0].metric == "p95"
    assert res.breaches[0].value == float("inf")


def test_slo_unknown_metric_raises() -> None:
    with pytest.raises(ValueError, match="unknown SLO metric"):
        slo_check(_stats(p95=0.1), {"p999": 0.5})


def test_slo_no_thresholds_passes() -> None:
    """An empty threshold map vacuously passes (nothing to violate)."""
    res = slo_check(_stats(p95=9.9), {})
    assert res.passed
    assert res.breaches == []
