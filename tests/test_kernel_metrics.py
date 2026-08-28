"""ORIZONT-24 — kernel decision metrics (observability over the complete Gate-K surface).

``kernel.authorize`` tallies every grant/deny/queue into the in-process ``KERNEL_METRICS``
meter (via ``_emit_audit``, the universal decision exit), surfaced at ``GET /api/metrics/kernel``.
"""
import asyncio
import json
from types import SimpleNamespace

from agents.core.autonomy.policy import ACT, ASK
from agents.core.kernel import Action, Verdict, authorize
from agents.core.kernel.metrics import KERNEL_METRICS, KernelMetrics
from agents.core.security.capability import KillSwitch


class _GrantPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


class _AskPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=3, outcome=ASK, reason="needs approval")


# ── the meter unit ─────────────────────────────────────────────────────────────
def test_record_and_snapshot():
    m = KernelMetrics()
    m.record("payment", "grant")
    m.record("payment", "deny", "kill-switch engaged for scope 'global'")
    m.record("kg.write", "queue")
    snap = m.snapshot()
    assert snap["total"] == 3
    assert snap["by_verdict"] == {"grant": 1, "deny": 1, "queue": 1}
    assert snap["by_kind"]["payment"] == {"grant": 1, "deny": 1, "queue": 0}
    assert snap["deny_rate"] == round(1 / 3, 4)
    assert snap["recent_denials"][0]["kind"] == "payment"
    assert "kill-switch" in snap["recent_denials"][0]["reason"]


def test_reset_and_unknown_verdict():
    m = KernelMetrics()
    m.record("x", "grant")
    m.record("x", "weird")               # unknown verdict is ignored
    assert m.snapshot()["total"] == 1
    m.reset()
    snap = m.snapshot()
    enabled = snap.pop("enabled")
    assert isinstance(enabled, bool)
    assert snap == {"total": 0, "by_verdict": {"grant": 0, "deny": 0, "queue": 0},
                     "by_kind": {}, "ungoverned_by_kind": {}, "ungoverned_actions": 0,
                     "deny_rate": 0.0, "recent_denials": []}


# ── A8-iv: the live ungoverned-actions meter must be interpretable ──────────────
def test_snapshot_reports_enabled_so_a_zero_is_interpretable(monkeypatch):
    """`ungoverned_actions == 0` proves nothing if the kernel was never mediating
    anything to begin with (docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md)."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    assert KernelMetrics().snapshot()["enabled"] is False
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    assert KernelMetrics().snapshot()["enabled"] is True


def test_ungoverned_actions_is_the_live_total_across_kinds():
    m = KernelMetrics()
    m.record_ungoverned("draft_email")
    m.record_ungoverned("draft_email")
    m.record_ungoverned("channel.reply")
    snap = m.snapshot()
    assert snap["ungoverned_by_kind"] == {"channel.reply": 1, "draft_email": 2}
    assert snap["ungoverned_actions"] == 3


def test_denials_ring_is_bounded():
    m = KernelMetrics(max_denials=3)
    for i in range(5):
        m.record("x", "deny", f"r{i}")
    recent = m.snapshot()["recent_denials"]
    assert [d["reason"] for d in recent] == ["r4", "r3", "r2"]   # newest-first, capped at 3


# ── the kernel records every decision via authorize ──────────────────────────────
def test_authorize_tallies_grant_queue_deny(tmp_path):
    KERNEL_METRICS.reset()
    authorize(Action(kind="writeback.x"), policy=_GrantPolicy())          # grant
    authorize(Action(kind="kg.write"), policy=_AskPolicy())               # queue
    kill = KillSwitch(tmp_path / "k.json")
    kill.engage("global", "test")
    d = authorize(Action(kind="payment"), policy=_GrantPolicy(), kill_switch=kill)  # deny
    assert d.verdict is Verdict.DENY

    snap = KERNEL_METRICS.snapshot()
    assert snap["by_kind"]["writeback.x"]["grant"] == 1
    assert snap["by_kind"]["kg.write"]["queue"] == 1
    assert snap["by_kind"]["payment"]["deny"] == 1
    assert snap["total"] == 3
    assert any("kill-switch" in dn["reason"] for dn in snap["recent_denials"])


# ── the endpoint ─────────────────────────────────────────────────────────────────
def test_metrics_kernel_endpoint():
    from agents.core.routers.analytics import metrics_kernel
    KERNEL_METRICS.reset()
    authorize(Action(kind="social.post"), policy=_GrantPolicy())
    body = json.loads(asyncio.run(metrics_kernel()).body)
    assert body["by_kind"].get("social.post", {}).get("grant") == 1
    assert body["total"] == 1
