"""Pure, clock-controlled sustained channel failure episodes (H083)."""

from __future__ import annotations

from agents.core.channels.escalation import (
    FAILURE_AFTER,
    HEALTHY_AFTER,
    MONITOR_INTERVAL,
    FailureEscalation,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _retry(failures=1):
    return {"state": "retrying", "failures": failures}


def _observe(tracker, adapter, snapshot, *, revision=1, eligible=True):
    return tracker.observe("telegram", adapter, revision, snapshot, eligible)


def test_constants_and_confirmed_failure_threshold_spend_before_next_sample():
    assert (MONITOR_INTERVAL, FAILURE_AFTER, HEALTHY_AFTER) == (10, 300, 60)
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER - 0.001)
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(0.001)
    assert _observe(tracker, adapter, _retry()) is True
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(10 * FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is False


def test_unconfirmed_and_unreadable_rows_never_count_or_rearm():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    for snapshot in (_retry(0), _retry(True), _retry(1.0),
                     {"state": "unknown", "failures": 99},
                     {"state": "running", "failures": 99},
                     None, ["retrying"], {"state": "retrying"}):
        assert _observe(tracker, adapter, snapshot) is False
        clock.advance(FAILURE_AFTER + 1)
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is True
    assert _observe(tracker, adapter, {"state": "unknown"}) is False
    clock.advance(HEALTHY_AFTER * 2)
    assert _observe(tracker, adapter, _retry()) is False


def test_ineligible_and_unknown_break_pending_failure_duration():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER - 1)
    assert _observe(tracker, adapter, _retry(), eligible=False) is False
    clock.advance(100)
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER - 1)
    assert _observe(tracker, adapter, {"state": "unknown"}) is False
    clock.advance(100)
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is True


def test_stable_healthy_rearms_but_a_flap_or_unknown_does_not():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is True
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    clock.advance(HEALTHY_AFTER - 1)
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is False
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    clock.advance(HEALTHY_AFTER - 1)
    assert _observe(tracker, adapter, {"state": "unknown"}) is False
    clock.advance(HEALTHY_AFTER + 1)
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    clock.advance(HEALTHY_AFTER)
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is True


def test_fatal_callback_and_projected_fatal_share_one_latch():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    assert tracker.fatal("discord", adapter, 1) is True
    assert tracker.fatal("discord", adapter, 1) is False
    assert tracker.observe("discord", adapter, 1, {"state": "fatal"}, True) is False
    assert tracker.observe("discord", adapter, 1, {"state": "healthy"}, True) is False
    clock.advance(HEALTHY_AFTER)
    assert tracker.observe("discord", adapter, 1, {"state": "healthy"}, True) is False
    assert tracker.observe("discord", adapter, 1, {"state": "fatal"}, True) is True
    assert tracker.fatal("discord", adapter, 1) is False

    second = object()
    assert tracker.observe("slack", second, 2, {"state": "fatal"}, True) is True
    assert tracker.fatal("slack", second, 2) is False


def test_sustained_notice_suppresses_later_fatal_until_stable_recovery():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    adapter = object()
    assert _observe(tracker, adapter, _retry()) is False
    clock.advance(FAILURE_AFTER)
    assert _observe(tracker, adapter, _retry()) is True
    assert tracker.fatal("telegram", adapter, 1) is False
    assert _observe(tracker, adapter, {"state": "fatal"}) is False
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    clock.advance(HEALTHY_AFTER)
    assert _observe(tracker, adapter, {"state": "healthy"}) is False
    assert tracker.fatal("telegram", adapter, 1) is True


def test_exact_adapter_identity_revision_retire_prune_and_reset():
    clock = Clock()
    tracker = FailureEscalation(clock=clock)
    old, new = object(), object()
    assert tracker.fatal("telegram", old, 1) is True
    assert tracker.observe("telegram", new, 2, {"state": "fatal"}, True) is True
    assert tracker.fatal("telegram", old, 1) is False
    assert tracker.fatal("telegram", new, 2) is False
    tracker.prune({"telegram": (new, 2)})
    assert tracker.fatal("telegram", new, 2) is False
    assert tracker.observe("telegram", new, 3, {"state": "fatal"}, True) is True
    assert tracker.fatal("telegram", new, 2) is False
    tracker.prune({"telegram": (old, 2)})
    assert tracker.fatal("telegram", new, 3) is True
    tracker.retire("telegram")
    assert tracker.fatal("telegram", new, 3) is True
    tracker.reset()
    assert tracker.fatal("telegram", new, 3) is True


def test_equal_adapters_do_not_share_an_episode():
    class Equal:
        def __eq__(self, other):
            return isinstance(other, Equal)

        def __hash__(self):
            return 1

    tracker = FailureEscalation(clock=Clock())
    first, second = Equal(), Equal()
    assert first == second and first is not second
    assert tracker.fatal("slack", first, 1) is True
    assert tracker.observe("slack", second, 1, {"state": "fatal"}, True) is True
    assert tracker.fatal("slack", first, 1) is False
