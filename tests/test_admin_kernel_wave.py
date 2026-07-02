"""ORIZONT-24 K1 wave-4a/4b — admin escalations route through the Action Kernel.

POST /api/security/kill-switch (ENGAGE) and POST /api/security/capabilities/issue now
pass kernel.authorize in addition to admin_guard, with a capability token now MANDATORY
(wave-4b). This pins the REAL behavior the action-auth matrix can't (it only proves the
kernel was *called*):

  * default-off: routes behave byte-identically when JARVIS_ACTION_KERNEL is unset;
  * clean + flag on, no token presented: the router mints its own short-lived operator
    token (the caller already passed admin_guard) → the real capability cross-check
    passes → 200 (no approval-UX regression, and no new credential for the operator);
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


# ── flag on, clean: mints its own operator token → real cross-check → allow ──────────
def test_flag_on_clean_allows_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    orch = _orch(tmp_path, "issue")
    monkeypatch.setattr(web, "orch", orch)
    # clean kill-switch, no token presented → the router mints one (wave-4b) → the
    # capability nucleus genuinely passes (not just tolerated-empty) → 200
    assert not orch.capabilities.list()
    assert _status(_run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))) == 200
    # two tokens now exist: the wave-4b operator mint (proves real enforcement ran)
    # plus the endpoint's own issued "x" capability (its actual business response).
    minted = orch.capabilities.list()
    assert len(minted) == 2
    assert any(t["capabilities"] == ["admin:capability_issue"] for t in minted)
    assert any(t["capabilities"] == ["x"] for t in minted)

    orch2 = _orch(tmp_path, "engage")
    monkeypatch.setattr(web, "orch", orch2)
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": True})))) == 200
    assert orch2.kill_switch.is_halted("global")   # the minted token allowed the engage through


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


# ── flag on, a presented VALID token → accepted, no mint needed ─────────────────────
def test_flag_on_explicitly_presented_valid_token_is_accepted(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(web, "orch", orch)
    tok = orch.capabilities.issue(["admin:capability_issue"])["id"]
    r = _run(secmod.capabilities_issue(
        _Req({"capabilities": ["x"]}, headers={"x-capability-token": tok})))
    assert _status(r) == 200
    # the presented token wins — no OPERATOR token was minted for this call (only
    # the pre-issued one we presented, plus the endpoint's own issued "x" cap).
    ids = [t["id"] for t in orch.capabilities.list()]
    assert tok in ids and len(ids) == 2
    assert all(t["capabilities"] != ["admin:capability_issue"] or t["id"] == tok
               for t in orch.capabilities.list())


# ── wave-4b backstop: capabilities=None falls back to pure K1 (unaffected) ──────────
def test_no_broker_at_all_falls_back_to_k1_kill_switch_only(tmp_path, monkeypatch):
    # kill_switch_set doesn't 503 on a missing capability broker (only a missing
    # kill-switch), unlike capabilities_issue — the right vehicle to exercise this.
    orch = _orch(tmp_path)
    orch.capabilities = None   # simulate a boot where the broker never wired
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr(web, "orch", orch)
    # authorize() sees capabilities=None → the capability system is entirely absent,
    # so it falls back to K1 kill-switch-only gating (not the wave-4b mandatory-token
    # DENY, which only applies when a broker exists but yields no token) — clean state
    # still allows through, same as pre-wave-4b behavior with no broker.
    assert _status(_run(secmod.kill_switch_set(_Req({"engage": True})))) == 200
    assert orch.kill_switch.is_halted("global")


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
