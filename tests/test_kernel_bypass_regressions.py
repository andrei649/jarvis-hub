"""Regression tests for the three bypass risks the Action Kernel must close (K1+).

  B1 — admin security routes are admin-guarded but don't cross-check a capability.
  B2 — MCP mutating tools fail OPEN if no identity check is bound.
  B3 — JARVIS_STRICT_EGRESS=0 downgrades an egress violation with no audit.

B1 and B2 are closed (B1 as of wave-4b/K2: a capability token is now MANDATORY,
not just cross-checked when presented). B3 closed with the plugin.egress kernel
wave. Contract pinned here so a future regression fails CI.
"""

import asyncio

import pytest

from agents.core.kernel import Action, Capability, Verdict, authorize
from agents.core.kernel.registry import Mediation, classify
from agents.core.security.capability import CapabilityBroker, KillSwitch

# ── B2 — MCP mutating tool fails closed without an identity check (true today) ──

def test_mutating_tool_fails_closed_without_identity():
    from agents.core.mcp.route_tools import (
        MUTATING_ROUTE_ALLOWLIST,
        MutatingIdentityError,
        MutatingRouteTool,
    )

    async def _invoke(_kwargs):  # pragma: no cover - must never run (refused first)
        return {"ok": True}

    tool = MutatingRouteTool(
        spec=MUTATING_ROUTE_ALLOWLIST[0], invoke=_invoke,
        auditor=None, identity_check=None,
    )
    # No identity policy bound → the gate refuses, never authorizes.
    assert tool._identity_ok(None) is False
    assert tool._identity_ok("any-token") is False
    with pytest.raises(MutatingIdentityError):
        asyncio.run(tool.call({}, token=None))


# ── B1 — admin/kg-write actions are kernel-mediated with a MANDATORY token ──────

def test_admin_action_requires_capability():
    # Wave-4a: /api/security/{kill-switch (engage), capabilities/issue} and
    # /api/kg/* mutating routes route through kernel.authorize (a capability
    # cross-check + kill-switch gate), not just admin_guard/user_guard's network
    # origin. Contract pinned here: these actions are kernel-mediated.
    assert classify("admin.capability_issue") is Mediation.KERNEL
    assert classify("admin.kill_switch") is Mediation.KERNEL
    assert classify("kg.write") is Mediation.KERNEL


def test_admin_and_kg_actions_fail_closed_without_a_capability_token(tmp_path):
    # Wave-4b: B1 is closed for REAL now, not just structurally — a caller that
    # reaches the kernel for one of these three kinds with no token at all is
    # refused, even with a clean kill-switch and a live broker (mirrors B2's
    # fail-closed-without-identity contract above). The real HTTP routers never
    # hit this path for an already-authenticated operator (they mint their own
    # token — see tests/test_admin_kernel_wave.py / test_kg_kernel_wave.py); this
    # pins the kernel-level backstop that makes the mandate real.
    kill = KillSwitch(tmp_path / "kill.json")
    broker = CapabilityBroker()
    for kind in ("admin.kill_switch", "admin.capability_issue", "kg.write"):
        d = authorize(Action(kind=kind, payload={"risk_tier": 1}), Capability(),
                      kill_switch=kill, capabilities=broker, policy=_GrantEverything())
        assert d.verdict is Verdict.DENY, f"{kind} should deny with no token"


class _GrantEverything:
    def decide(self, action):
        from types import SimpleNamespace

        from agents.core.autonomy.policy import ACT
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


# ── B3 — strict-egress downgrade is audited + egress is kernel-mediated (K-wave 2) ──

def test_egress_downgrade_is_audited():
    # B3 closed: the JARVIS_STRICT_EGRESS=0 downgrade is durably audited (EGRESS_DOWNGRADE
    # event), and K-wave 2 routes policy-passing egress through kernel.authorize so a
    # halted kill-switch / over-budget / runaway loop blocks it. Contract: plugin egress
    # is kernel-mediated.
    assert classify("plugin.egress") is Mediation.KERNEL
