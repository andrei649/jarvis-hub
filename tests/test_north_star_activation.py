"""The activation metric on the north-star: S8 / GAP-0, and what it must not claim.

`compute_north_star` reports a trailing window; activation is the one field in it
that is a property of the INSTALL instead. That difference is what these tests
pin, because getting it wrong is how an adoption number becomes meaningless:

  · activation does not change when the window slides — it is not a weekly rate;
  · a never-activated install reports how long it has been waiting, never a blank
    and never a zero;
  · a metric read that fails degrades the FIELD, not the whole report — the rest
    of the north-star still computes.
"""

from __future__ import annotations

import types

import pytest

from agents.core.first_action import mark_installed, record_first_action
from agents.core.observability.north_star import compute_north_star

DAY = 86_400.0


def _task(decided_by="owner", decision="accept"):
    return types.SimpleNamespace(id=1, kind="writeback",
                                 decided_by=decided_by, decision=decision)


def test_activation_is_reported_on_the_north_star():
    out = compute_north_star(
        None,
        activation_state={"installed": True, "activated": True, "seconds": 420.0,
                          "band": "under_10_minutes"},
    )
    assert out["activation"]["seconds"] == 420.0
    assert out["activation"]["band"] == "under_10_minutes"


def test_activation_does_not_move_when_the_window_slides():
    """It is a property of the install, not a weekly rate. A 7-day and a 30-day
    report describe the same activation, because there was only one."""
    state = {"installed": True, "activated": True, "seconds": 420.0}
    weekly = compute_north_star(None, days=7, activation_state=state)
    monthly = compute_north_star(None, days=30, activation_state=state)
    assert weekly["activation"] == monthly["activation"]
    assert weekly["days"] != monthly["days"]


def test_a_never_activated_install_reports_the_wait_not_a_blank():
    out = compute_north_star(
        None,
        activation_state={"installed": True, "activated": False, "seconds": None,
                          "waiting_seconds": 3 * DAY, "waiting_band": "under_a_week",
                          "reason": "no owner-accepted governed action yet"},
    )
    activation = out["activation"]
    assert activation["activated"] is False
    assert activation["seconds"] is None  # not 0.0
    assert activation["waiting_seconds"] == 3 * DAY
    assert activation["reason"]


def test_the_real_store_feeds_the_metric(tmp_path, monkeypatch):
    """End to end over the real module rather than an injected dict."""
    import agents.core.first_action as fa

    store = tmp_path / "activation.json"
    monkeypatch.setattr(fa, "store_path", lambda p=None: store)
    mark_installed(store, now=0.0)
    record_first_action(_task(), store, now=300.0)

    out = compute_north_star(None, now=DAY)
    assert out["activation"]["activated"] is True
    assert out["activation"]["seconds"] == pytest.approx(300.0)
    assert out["activation"]["band"] == "under_10_minutes"


def test_a_failing_activation_read_degrades_only_that_field(monkeypatch):
    """A metric write must never take down the report it is one field of."""
    import agents.core.first_action as fa

    def _boom(**_kw):
        raise OSError("data root gone")

    monkeypatch.setattr(fa, "activation_state", _boom)
    out = compute_north_star(None)
    assert out["activation"]["activated"] is False
    assert "unavailable" in out["activation"]["reason"]
    # the rest of the report is intact
    assert out["period"] == "weekly"
    assert "north_star" in out and "counter_metrics" in out
