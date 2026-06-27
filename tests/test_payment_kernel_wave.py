"""ORIZONT-24 K1 — payment micro-wave: PaymentBroker routes an admissible request
through kernel.authorize.

The mandate's hard caps still gate admissibility *first*; the kernel adds a hard
**deny** capability on top (kill-switch engaged / over-budget / runaway loop) that
refuses a payment before it can become pending. GRANT/QUEUE fall through to the
existing always-approval pending flow — the kernel can't relax that rule.

Default-off behind JARVIS_ACTION_KERNEL: with the flag unset the hook is skipped and
the path is byte-identical to before, even when a kernel is bound.
"""
from pathlib import Path

import pytest

from agents.core.kernel import Action, Decision, Verdict
from agents.core.payments import PENDING, PaymentBroker


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, **kw):
        self.records.append(kw)


class _SpyKernel:
    """Records the Action and returns a fixed verdict (stands in for the bound
    kernel.authorize the orchestrator/web.py injects)."""

    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls = []
        self._verdict, self._reason = verdict, reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._verdict, reason=self._reason)


def _broker(tmp_path: Path, *, kernel=None, audit=None) -> PaymentBroker:
    return PaymentBroker(path=str(tmp_path / "pay.json"), audit=audit, kernel=kernel)


def _mandate(b: PaymentBroker):
    return b.create_mandate(["acme"], per_payment_cap=100, total_cap=100, currency="EUR")


# ── default-off ────────────────────────────────────────────────────────────────
def test_flag_off_skips_kernel_even_when_bound(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    spy = _SpyKernel(verdict=Verdict.DENY)        # would refuse — but must not be called
    b = _broker(tmp_path, kernel=spy)
    out = b.request_payment(_mandate(b)["id"], "acme", 10)
    assert out["ok"] is True and out["payment"]["status"] == PENDING
    assert spy.calls == []                          # kernel never consulted while off


# ── flag-on routing ──────────────────────────────────────────────────────────────
def test_kernel_deny_refuses_before_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.DENY, reason="kill-switch engaged for scope 'global'")
    audit = _Audit()
    b = _broker(tmp_path, kernel=spy, audit=audit)
    out = b.request_payment(_mandate(b)["id"], "acme", 10)
    assert out == {"ok": False, "reason": "kernel_denied",
                   "detail": "kill-switch engaged for scope 'global'"}
    assert spy.calls and spy.calls[-1].kind == "payment"
    assert b.list_payments() == []                  # nothing became pending
    assert any(r["action"] == "deny_payment" and "kernel:" in r["why"] for r in audit.records)


def test_kernel_grant_falls_through_to_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.GRANT)
    b = _broker(tmp_path, kernel=spy)
    out = b.request_payment(_mandate(b)["id"], "acme", 10)
    assert out["ok"] is True and out["payment"]["status"] == PENDING   # still approval-gated
    assert spy.calls[-1].payload["amount"] == 10.0


def test_kernel_queue_still_only_pending_never_auto_settles(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.QUEUE)
    b = _broker(tmp_path, kernel=spy)
    out = b.request_payment(_mandate(b)["id"], "acme", 10)
    assert out["ok"] is True and out["payment"]["status"] == PENDING
    # QUEUE doesn't settle anything; the payment must still pass through owner approval.
    assert [p["status"] for p in b.list_payments()] == [PENDING]


def test_inadmissible_request_never_reaches_kernel(tmp_path, monkeypatch):
    """A request the mandate's hard caps reject is denied at creation — the kernel is
    not even consulted (admissibility is checked first)."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.GRANT)
    b = _broker(tmp_path, kernel=spy)
    out = b.request_payment(_mandate(b)["id"], "acme", 999)   # over per_payment_cap
    assert out == {"ok": False, "reason": "over_per_payment_cap"}
    assert spy.calls == []


# ── integration: the *real* bound kernel + real KillSwitch (simulate the rail) ──────
def test_real_bound_kernel_halt_blocks_then_release_allows(tmp_path, monkeypatch):
    """Bind the production kernel.authorize (make_action_kernel) over a real
    AutonomyPolicy + real KillSwitch and prove a halted switch denies a payment, while
    a released switch lets the admissible payment proceed to pending."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    kill = KillSwitch(tmp_path / "kill.json")

    class _Orch:                       # minimal stand-in the binding reads via getattr
        autonomy_policy = AutonomyPolicy()
        kill_switch = kill
        capabilities = CapabilityBroker()
        intent_log = None

    b = _broker(tmp_path, kernel=make_action_kernel(_Orch()))
    mid = _mandate(b)["id"]

    kill.engage("global", reason="test")
    denied = b.request_payment(mid, "acme", 10)
    assert denied["ok"] is False and denied["reason"] == "kernel_denied"
    assert b.list_payments() == []                 # halt → no pending payment

    kill.disengage("global")
    ok = b.request_payment(mid, "acme", 10)
    assert ok["ok"] is True and ok["payment"]["status"] == PENDING
