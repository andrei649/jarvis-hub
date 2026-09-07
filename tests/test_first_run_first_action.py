"""S8 / GAP-0 — time to first governed action, and the ways that number is flattered.

This is the adoption metric, so every test here corresponds to a specific way of
making it look better than it is:

  · the clock starts at INSTALL, not at first launch — someone who installed on
    Monday and opened it on Friday took five days;
  · only an owner-ACCEPTED action counts; proposing quickly and being rejected has
    activated nobody, and a policy auto-approval is not the owner choosing to
    trust the product;
  · the first is the first — a later, faster action cannot improve the number;
  · never-activated is a reported state carrying how long it has been, never a
    blank and never a zero.

Hermetic: a tmp_path store and an injected clock; nothing sleeps or touches the
data root.
"""

from __future__ import annotations

import json
import types

import pytest

from agents.core.first_action import (
    SCHEMA,
    activation_state,
    infer_install_at_boot,
    mark_installed,
    record_first_action,
)

HOUR = 3_600.0
DAY = 86_400.0


@pytest.fixture
def store(tmp_path):
    return tmp_path / "activation.json"


def _task(*, decided_by="owner", decision="accept", kind="writeback", task_id=7):
    return types.SimpleNamespace(
        id=task_id, kind=kind, decided_by=decided_by, decision=decision
    )


# ── the clock starts at install ──────────────────────────────────────────────

def test_the_clock_starts_at_install_not_at_first_launch(store):
    """Starting at launch would report ninety seconds for someone who took five
    days to open it, and describe nothing about the real friction."""
    mark_installed(store, now=0.0)
    # opened five days later, activated a minute after that
    record_first_action(_task(), store, now=5 * DAY + 60)
    state = activation_state(store, now=5 * DAY + 120)
    assert state["activated"] is True
    assert state["seconds"] == pytest.approx(5 * DAY + 60)
    assert state["band"] == "over_a_week" or state["band"] == "under_a_week"


def test_marking_installed_twice_never_restarts_the_clock(store):
    first = mark_installed(store, now=0.0)
    second = mark_installed(store, now=DAY)
    assert second["installed_at"] == 0.0
    assert second["install_id"] == first["install_id"]


def test_a_boot_inferred_start_is_flagged_as_inferred(store):
    """It reports a SHORTER time than the truth, which is the honest direction to
    fail in — but a reader has to be able to tell."""
    record = infer_install_at_boot(store, now=100.0)
    assert record["inferred_at_boot"] is True
    assert activation_state(store, now=200.0)["inferred_start"] is True


def test_inferring_after_a_real_install_leaves_the_real_start_alone(store):
    mark_installed(store, now=0.0)
    record = infer_install_at_boot(store, now=DAY)
    assert record["installed_at"] == 0.0
    assert record["inferred_at_boot"] is False


# ── only an owner-accepted action counts ─────────────────────────────────────

def test_an_owner_accepted_action_activates(store):
    mark_installed(store, now=0.0)
    assert record_first_action(_task(), store, now=300.0) is not None
    state = activation_state(store, now=400.0)
    assert state["activated"] is True
    assert state["seconds"] == 300.0
    assert state["band"] == "under_10_minutes"
    assert state["decision"] == "accept by owner"


@pytest.mark.parametrize("decider", ["policy", "system", "kernel", "auto", "worker", ""])
def test_a_machine_approval_does_not_activate(store, decider):
    """Auto-approved by policy is not the owner choosing to trust the product."""
    mark_installed(store, now=0.0)
    assert record_first_action(_task(decided_by=decider), store, now=60.0) is None
    assert activation_state(store, now=60.0)["activated"] is False


@pytest.mark.parametrize("decision", ["reject", "defer", "", "maybe"])
def test_a_rejected_or_deferred_action_does_not_activate(store, decision):
    """Proposing quickly and being rejected has activated nobody."""
    mark_installed(store, now=0.0)
    assert record_first_action(_task(decision=decision), store, now=60.0) is None
    assert activation_state(store, now=60.0)["activated"] is False


def test_an_edit_counts_because_it_is_still_a_person_deciding(store):
    mark_installed(store, now=0.0)
    assert record_first_action(_task(decision="edit"), store, now=60.0) is not None


# ── the first is the first ───────────────────────────────────────────────────

def test_a_later_faster_action_cannot_improve_the_number(store):
    mark_installed(store, now=0.0)
    record_first_action(_task(task_id=1), store, now=2 * DAY)
    assert record_first_action(_task(task_id=2), store, now=2 * DAY + 1) is None
    state = activation_state(store, now=3 * DAY)
    assert state["seconds"] == pytest.approx(2 * DAY)


def test_the_recorded_action_is_identified(store):
    mark_installed(store, now=0.0)
    record_first_action(_task(task_id=42, kind="house.control"), store, now=100.0)
    stored = json.loads(store.read_text())
    assert stored["activated"]["task_id"] == 42
    assert stored["activated"]["task_kind"] == "house.control"


def test_a_reinstall_is_a_new_honest_clock(store):
    mark_installed(store, now=0.0)
    record_first_action(_task(), store, now=DAY)
    store.unlink()  # what an uninstall/reinstall leaves behind
    mark_installed(store, now=10 * DAY)
    state = activation_state(store, now=10 * DAY + 60)
    assert state["activated"] is False
    assert state["waiting_seconds"] == 60.0


# ── never-activated is a finding, not a blank ────────────────────────────────

def test_never_activated_reports_how_long_it_has_been(store):
    """"Nobody has activated, and it has been three days" is the finding; a blank
    is the same fact with the urgency removed."""
    mark_installed(store, now=0.0)
    state = activation_state(store, now=3 * DAY)
    assert state["installed"] is True
    assert state["activated"] is False
    assert state["seconds"] is None  # not zero — nothing has been measured
    assert state["waiting_seconds"] == pytest.approx(3 * DAY)
    assert state["waiting_band"] == "under_a_week"
    assert state["reason"] == "no owner-accepted governed action yet"


def test_no_install_record_reads_as_clock_not_started(store):
    state = activation_state(store, now=DAY)
    assert state["installed"] is False
    assert state["activated"] is False
    assert state["seconds"] is None
    assert "clock has not started" in state["reason"]


def test_an_activation_with_no_install_record_starts_an_inferred_clock(store):
    """Dropping the activation would lose the fact that someone activated at all;
    a ~0 elapsed time flagged as inferred is visibly wrong in the safe direction."""
    assert record_first_action(_task(), store, now=500.0) is not None
    state = activation_state(store, now=600.0)
    assert state["activated"] is True
    assert state["inferred_start"] is True
    assert state["seconds"] == pytest.approx(0.0, abs=1.0)


# ── bands ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("seconds", "band"),
    [
        (1.0, "under_10_minutes"),
        (599.0, "under_10_minutes"),
        (600.0, "under_an_hour"),
        (3_599.0, "under_an_hour"),
        (3_600.0, "under_a_day"),
        (86_399.0, "under_a_day"),
        (86_400.0, "under_a_week"),
        (604_799.0, "under_a_week"),
        (604_800.0, "over_a_week"),
    ],
)
def test_the_band_is_derived_from_the_raw_seconds(store, seconds, band):
    """The band is a convenience; the raw number is always still there."""
    mark_installed(store, now=0.0)
    record_first_action(_task(), store, now=seconds)
    state = activation_state(store, now=seconds + 1)
    assert state["band"] == band
    assert state["seconds"] == pytest.approx(seconds)


# ── durability ───────────────────────────────────────────────────────────────

def test_the_record_survives_a_restart(store):
    mark_installed(store, now=0.0)
    record_first_action(_task(), store, now=120.0)
    # a fresh read, as a new process would do
    state = activation_state(store, now=DAY)
    assert state["activated"] is True
    assert state["seconds"] == 120.0


def test_a_corrupt_store_reads_as_not_started_rather_than_raising(store):
    store.write_text("{not json")
    assert activation_state(store, now=DAY)["installed"] is False
    # and the clock can be restarted over it
    assert mark_installed(store, now=DAY)["installed_at"] == DAY


def test_a_foreign_schema_is_not_trusted(store):
    store.write_text(json.dumps({"schema": "something.else", "installed_at": 0.0}))
    assert activation_state(store, now=DAY)["installed"] is False


def test_the_stored_record_carries_its_schema(store):
    mark_installed(store, now=0.0)
    assert json.loads(store.read_text())["schema"] == SCHEMA
