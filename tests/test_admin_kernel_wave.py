"""ORIZONT-24 K1 wave-4a — admin escalations route through the Action Kernel.

POST /api/security/kill-switch (ENGAGE) and POST /api/security/capabilities/issue now
pass kernel.authorize in addition to admin_guard. This pins the REAL behavior the
action-auth matrix can't (it only proves the kernel was *called*):

  * default-off: routes behave byte-identically when JARVIS_ACTION_KERNEL is unset;
  * clean + flag on: an unknown admin kind classifies high-risk → policy QUEUE, which we
    treat as **allow-through** (we honor only a hard DENY) → 200 (no approval-UX regression);
  * halted: engage + issue are DENIED (403) — BUT **disengage bypasses the kernel** so the
    operator can always release a halt (no bootstrap lock-out), then re-credential;
  * a *presented* capability token that grants nothing is DENIED (the real cross-check);
  * each handler emits its own distinct action kind.
"""
import asyncio

import agents.web as web
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Decision, Verdict
from agents.core.routers import security as secmod
from agents.core.security.capability import CapabilityBroker, KillSwitch


def _orch(tmp_path, name="a"):
    class _Orch:
        kill_switch = KillSwitch(tmp_path / f"{name}.json")
        capabilities = CapabilityBroker()
        autonomy_policy = AutonomyPolicy()
        intent_log = None
    return _Orch()


class _Req:
    def __init__(self, body, headers=None):
        self._b, self.headers = body, (headers or {})

    async def json(self):
        return self._b


def _status(resp):
    return getattr(resp, "status_code", 200)


def _run(coro):
    return asyncio.run(coro)


# ── default-off: byte-identical ───────────────────────────────────────────────────
def test_flag_off_admin_routes_unmediated(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))) == 200
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": True})))) == 200
    assert orch.kill_switch.is_halted("global")
    # even while halted, with the flag OFF a mint is unmediated → 200 (unchanged behavior)
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["y"]})))) == 200
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": False})))) == 200


# ── flag on, clean: QUEUE allows through (no approval-UX regression) ─────────────────
def test_flag_on_clean_allows_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(web, "orch", _orch(tmp_path, "issue"))
    # clean kill-switch, no token presented → policy QUEUE → allow-through → mints
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))) == 200

    orch2 = _orch(tmp_path, "engage")
    monkeypatch.setattr(web, "orch", orch2)
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": True})))) == 200
    assert orch2.kill_switch.is_halted("global")   # QUEUE allowed the engage through


# ── flag on, halted: engage/issue denied, but disengage ALWAYS recovers ─────────────
def test_flag_on_halt_blocks_but_disengage_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch = _orch(tmp_path)
    monkeypatch.setattr(web, "orch", orch)
    orch.kill_switch.engage("global", "out-of-band halt")

    # while halted, both escalations are kernel-DENIED
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": True})))) == 403
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))) == 403

    # the bootstrap fix: DISENGAGE bypasses the kernel → always works → releases the halt
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": False})))) == 200
    assert not orch.kill_switch.is_halted("global")

    # recovered → mint works again (no permanent lock-out)
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))) == 200


# ── flag on, a presented token granting nothing → real capability cross-check DENY ──
def test_flag_on_invalid_capability_token_denied(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(web, "orch", _orch(tmp_path))
    r = _run(secmod.capabilities_issue(
        _Req({"capabilities": ["x"]}, headers={"x-capability-token": "bogus"})))
    assert _status(r) == 403   # nucleus: "no valid capability token for this action"


# ── each handler mediates its OWN kind ─────────────────────────────────────────────
def test_handlers_emit_distinct_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(web, "orch", _orch(tmp_path))
    seen = []

    def _spy(action, capability=None, budget=None):
        seen.append(action.kind)
        return Decision(Verdict.GRANT, reason="spy")

    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda o: _spy)
    _run(secmod.kill_switch_set(_Req({"engage": True})))
    _run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))
    assert seen == ["admin.kill_switch", "admin.capability_issue"]
