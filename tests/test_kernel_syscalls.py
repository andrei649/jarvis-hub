"""K4 — kill-switch + credential-quarantine kernel syscalls.

Pure composition of the existing primitives (passed in), so the tests use small fakes for
the kill-switch / secret-broker / audit and one real kernel.authorize integration to prove
"halt halts new grants".
"""

from types import SimpleNamespace

from agents.core import kernel
from agents.core.autonomy.policy import ACT
from agents.core.kernel import Action, Verdict, syscalls


class _FakeKill:
    def __init__(self):
        self._h = {}

    def engage(self, scope="global", reason=""):
        self._h[scope] = {"scope": scope, "reason": reason}
        return self._h[scope]

    def disengage(self, scope="global"):
        return self._h.pop(scope, None) is not None

    def is_halted(self, scope="global"):
        return "global" in self._h or scope in self._h


class _FakeBroker:
    """Mirrors SecretBroker.inject's contract: approved=False blocks all handles."""
    def inject(self, text, approved=False):
        if approved:
            return {"text": text.replace("{{secret:k}}", "VALUE"), "injected": ["k"], "blocked": []}
        return {"text": text.replace("{{secret:k}}", "[blocked]"), "injected": [], "blocked": ["k"]}


class _Audit:
    def __init__(self):
        self.records = []

    def record(self, **kw):
        self.records.append(kw)


# ── halt / release ──────────────────────────────────────────────────────────
def test_halt_quarantines_then_release_resumes():
    kill, audit = _FakeKill(), _Audit()
    out = syscalls.halt(kill, reason="panic", audit=audit)
    assert out["halted"] is True
    assert syscalls.is_quarantined(kill) is True
    assert any(r["action"] == "kernel.halt" for r in audit.records)

    rel = syscalls.release(kill, audit=audit)
    assert rel["released"] is True
    assert syscalls.is_quarantined(kill) is False
    assert any(r["action"] == "kernel.release" for r in audit.records)


# ── credential quarantine ─────────────────────────────────────────────────────
def test_injection_blocked_while_halted_even_if_approved():
    kill, broker, audit = _FakeKill(), _FakeBroker(), _Audit()
    syscalls.halt(kill)
    res = syscalls.inject_guarded(broker, kill, "use {{secret:k}}", approved=True, audit=audit)
    assert res["quarantined"] is True
    assert res["injected"] == [] and res["blocked"] == ["k"]   # forced block
    assert any(r["action"] == "kernel.quarantine" for r in audit.records)


def test_injection_allowed_when_not_halted_and_approved():
    kill, broker = _FakeKill(), _FakeBroker()
    res = syscalls.inject_guarded(broker, kill, "use {{secret:k}}", approved=True)
    assert res["quarantined"] is False
    assert res["injected"] == ["k"]


def test_injection_blocked_when_unapproved_regardless():
    kill, broker = _FakeKill(), _FakeBroker()
    res = syscalls.inject_guarded(broker, kill, "use {{secret:k}}", approved=False)
    assert res["blocked"] == ["k"]


# ── integration: halt halts new grants (via kernel.authorize) ──────────────────
class _GrantPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


def test_halt_denies_new_grants_through_authorize():
    kill = _FakeKill()
    # not halted → grant
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy(), kill_switch=kill)
    assert d.verdict is Verdict.GRANT
    # halt → deny
    syscalls.halt(kill)
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy(), kill_switch=kill)
    assert d.verdict is Verdict.DENY and "kill-switch" in d.reason.lower()
