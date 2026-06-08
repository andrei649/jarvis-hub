"""Tests for the drift-free rate scheduler (ticket H19.1.6).

Pure: the schedule is a function of (target_rate, duration_s, tick_s) only. Covers the
exact total (floor(rate*duration)), even pacing (per-tick counts differ by <= 1),
fractional rates with no long-run drift, t_offsets, and edge cases (zero rate/duration).
"""

from __future__ import annotations

import pytest

from worldview_ingest.loadtest.rate import RateSchedule, Tick, plan


def test_exact_total_integer_rate() -> None:
    """10 msg/s for 5 s = 50 messages, 5 ticks of 10."""
    ticks = plan(target_rate=10.0, duration_s=5.0, tick_s=1.0)
    assert len(ticks) == 5
    assert sum(t.count for t in ticks) == 50
    assert all(t.count == 10 for t in ticks)


def test_total_messages_property_matches_iteration() -> None:
    """RateSchedule.total_messages == sum of yielded counts, for several configs."""
    for rate, dur, tick in [(7.0, 11.0, 1.0), (2.5, 8.0, 1.0), (100.0, 60.0, 0.5)]:
        sched = RateSchedule(target_rate=rate, duration_s=dur, tick_s=tick)
        assert sum(t.count for t in sched) == sched.total_messages


def test_fractional_rate_no_drift() -> None:
    """2.5 msg/s for 4 s = 10 messages with NO accumulated rounding drift."""
    ticks = plan(target_rate=2.5, duration_s=4.0, tick_s=1.0)
    assert sum(t.count for t in ticks) == 10  # floor(2.5*4)
    # Cumulative target floor(2.5 * k): 2,5,7,10 -> deltas 2,3,2,3.
    assert [t.count for t in ticks] == [2, 3, 2, 3]
    assert [t.cumulative for t in ticks] == [2, 5, 7, 10]


def test_even_pacing_counts_differ_by_at_most_one() -> None:
    """Per-tick counts never differ by more than 1 (even pacing)."""
    ticks = plan(target_rate=3.3, duration_s=10.0, tick_s=1.0)
    counts = [t.count for t in ticks]
    assert max(counts) - min(counts) <= 1
    assert sum(counts) == 33  # floor(3.3*10)


def test_subsecond_tick_total_preserved() -> None:
    """A finer tick still totals floor(rate*duration) with even sub-second counts."""
    ticks = plan(target_rate=100.0, duration_s=2.0, tick_s=0.5)
    assert len(ticks) == 4
    assert sum(t.count for t in ticks) == 200
    assert all(t.count == 50 for t in ticks)


def test_t_offsets_are_tick_ends_clamped_to_duration() -> None:
    """t_offset = (index+1)*tick_s, clamped to duration; final tick truncated."""
    ticks = plan(target_rate=10.0, duration_s=2.5, tick_s=1.0)
    assert [t.t_offset for t in ticks] == [1.0, 2.0, 2.5]
    # Final (0.5 s) tick carries floor(10*2.5)-floor(10*2.0)=25-20=5.
    assert ticks[-1].count == 5
    assert sum(t.count for t in ticks) == 25


def test_tick_indices_sequential() -> None:
    ticks = plan(target_rate=5.0, duration_s=4.0, tick_s=1.0)
    assert [t.index for t in ticks] == [0, 1, 2, 3]


def test_zero_rate_is_empty() -> None:
    assert plan(target_rate=0.0, duration_s=10.0, tick_s=1.0) == []


def test_zero_duration_is_empty() -> None:
    assert plan(target_rate=10.0, duration_s=0.0, tick_s=1.0) == []


def test_large_run_no_drift() -> None:
    """Over a long run at a fractional rate, total stays exact (no creeping drift)."""
    sched = RateSchedule(target_rate=37.4, duration_s=300.0, tick_s=1.0)
    ticks = list(sched)
    assert sum(t.count for t in ticks) == sched.total_messages == 11220  # floor(37.4*300)
    # The running cumulative never falls behind the ideal by a full message.
    for t in ticks:
        ideal = 37.4 * t.t_offset
        assert abs(t.cumulative - ideal) < 1.0


def test_validation() -> None:
    with pytest.raises(ValueError, match="target_rate"):
        RateSchedule(target_rate=-1.0, duration_s=1.0, tick_s=1.0)
    with pytest.raises(ValueError, match="duration_s"):
        RateSchedule(target_rate=1.0, duration_s=-1.0, tick_s=1.0)
    with pytest.raises(ValueError, match="tick_s"):
        RateSchedule(target_rate=1.0, duration_s=1.0, tick_s=0.0)


def test_tick_is_frozen() -> None:
    t = Tick(index=0, t_offset=1.0, count=3, cumulative=3)
    with pytest.raises(AttributeError):
        t.count = 9  # type: ignore[misc]
