"""LLM spend: measured, persisted, and capped (adversarial audit 2026-07-25, ADV-078).

Three cost endpoints — GET /api/cost, GET /api/analytics/cost, GET /api/admin/apm — read
``cost_tracker`` and NOTHING wrote to it: ``record()`` had no caller outside its own
module, so all three rendered a confident 0.00 forever. The tracker was also
process-memory only, so even a fed meter reset at every boot and "what did this cost me
last month" stayed unanswerable. And no cap existed anywhere, so an unattended night-shift
loop on a cloud key had no ceiling and produced no signal until the invoice.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest

from agents.core import cost_tracker
from agents.core.llm.cost_estimator import estimate_cost


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── the meter has a producer ───────────────────────────────────────
def test_the_orchestrator_records_cost_for_every_agent_turn():
    """The producer that did not exist. Static, because the record site is one call.

    Reading the source is the honest test here: the alternative is booting a full
    orchestrator, and a mocked one would prove only that my mock calls my code.
    """
    src = (repo_root / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert "cost_tracker.record(" in src, (
        "nothing feeds cost_tracker — /api/cost and its two siblings will render a "
        "confident 0.00 over real cloud traffic"
    )


def test_recorded_spend_is_priced_per_call_and_totalled():
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")   # $2.00 in
    cost_tracker.record("athena", 0, 1_000_000, model="claude-sonnet")  # $10.00 out
    summary = cost_tracker.get_summary()
    assert summary["agents"]["stark"]["cost_usd"] == pytest.approx(2.0)
    assert summary["agents"]["athena"]["cost_usd"] == pytest.approx(10.0)
    assert summary["total_cost_usd"] == pytest.approx(12.0)


def test_a_local_turn_costs_nothing_but_is_still_counted():
    """0.00 must come from measuring zero, not from nobody counting."""
    cost_tracker.record("stark", 5000, 5000, model="local")
    summary = cost_tracker.get_summary()
    assert summary["total_cost_usd"] == 0.0
    assert summary["agents"]["stark"]["calls"] == 1
    assert summary["agents"]["stark"]["input_tokens"] == 5000


# ── it survives a restart ──────────────────────────────────────────
def test_spend_persists_across_a_restart(tmp_path, monkeypatch):
    """Process-memory only meant last month was unanswerable even once fed."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")
    assert cost_tracker.spend_today_usd() == pytest.approx(2.0)

    # simulate a reboot: drop every in-process counter, then read again
    cost_tracker._usage.clear()
    cost_tracker._daily.clear()
    cost_tracker._state["loaded"] = False

    assert cost_tracker.spend_today_usd() == pytest.approx(2.0), (
        "spend reset at boot — 'what did this cost me last month' is unanswerable"
    )
    assert cost_tracker.daily_spend(), "no per-day rollup to answer a monthly question"


# ── unpriced is not free ───────────────────────────────────────────
def test_an_unpriced_model_is_flagged_rather_than_reported_as_free():
    unpriced = estimate_cost("a-model-nobody-priced", 1000, 1000)
    assert unpriced["priced"] is False, (
        "an unpriced model reported as costing 0.00 is a confident answer to a question "
        "nobody can answer — dashboards must be able to say 'unknown'"
    )
    genuinely_free = estimate_cost("local", 1000, 1000)
    assert genuinely_free["priced"] is True and genuinely_free["total"] == 0.0
    paid = estimate_cost("gemini-2.5-pro", 1_000_000, 0)
    assert paid["priced"] is True and paid["total"] > 0


# ── the cap ────────────────────────────────────────────────────────
class _Router:
    """Minimal stand-in exercising HybridRouter's real cap logic."""

    def __init__(self, cap, available=True):
        from agents.core.llm.hybrid_router import HybridRouter

        self._cloud_available = available
        self._daily_cost_cap = cap
        self._cloud_permitted = HybridRouter._cloud_permitted.__get__(self)


def test_no_cap_by_default_leaves_behaviour_unchanged():
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")
    assert _Router(cap=0.0)._cloud_permitted() is True


def test_cloud_is_refused_once_the_daily_cap_is_reached():
    router = _Router(cap=1.0)
    assert router._cloud_permitted() is True
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")   # $3.00 > $1.00
    assert router._cloud_permitted() is False, (
        "a cloud route was permitted over the daily cap — an unattended loop still has "
        "no ceiling"
    )


def test_the_cap_does_not_apply_when_cloud_is_unavailable_anyway():
    assert _Router(cap=1.0, available=False)._cloud_permitted() is False


def test_an_unreadable_meter_does_not_silently_disable_cloud(monkeypatch):
    """Failing closed here would take the box offline over a bookkeeping error."""
    monkeypatch.setattr(cost_tracker, "spend_today_usd",
                        lambda: (_ for _ in ()).throw(RuntimeError("store gone")))
    assert _Router(cap=1.0)._cloud_permitted() is True


def test_the_cap_setting_exists_and_defaults_to_off():
    from agents.core.settings_db import DEFAULTS

    row = next((r for r in DEFAULTS
                if r["category"] == "llm" and r["key"] == "daily_cost_cap_usd"), None)
    assert row is not None, "the cap has no /admin knob, so nobody can turn it on"
    assert row["value"] == 0, "the cap must be off by default — this is not a behaviour change"
