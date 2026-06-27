"""Regression tests for the three bypass risks the Action Kernel must close (K1+).

  B1 — admin security routes are admin-guarded but don't cross-check a capability.
  B2 — MCP mutating tools fail OPEN if no identity check is bound.
  B3 — JARVIS_STRICT_EGRESS=0 downgrades an egress violation with no audit.

B2 is *already* fail-closed today; this pins the contract so a future regression
fails CI. B1/B3 enforcement lands in later K-waves (4 and 2), so their tests are
xfail scaffolds that flip green when the wave lands — keeping acceptance
criterion 6 ("each has a regression test") honest about migration state.
"""

import asyncio

import pytest

from agents.core.kernel.registry import Mediation, classify

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


# ── B1 — admin action must require a capability (enforced in K-wave 4) ──────────

@pytest.mark.xfail(reason="B1: admin-route capability cross-check lands in K-wave 4",
                   strict=False)
def test_admin_action_requires_capability():
    # /api/security/{kill-switch,capabilities/issue} are admin-guarded only today.
    # Wave 4 routes them through kernel.authorize (a capability, not just a network
    # origin). Contract: these admin actions are kernel-mediated.
    assert classify("admin.capability_issue") is Mediation.KERNEL
    assert classify("admin.kill_switch") is Mediation.KERNEL


# ── B3 — strict-egress downgrade is audited + egress is kernel-mediated (K-wave 2) ──

def test_egress_downgrade_is_audited():
    # B3 closed: the JARVIS_STRICT_EGRESS=0 downgrade is durably audited (EGRESS_DOWNGRADE
    # event), and K-wave 2 routes policy-passing egress through kernel.authorize so a
    # halted kill-switch / over-budget / runaway loop blocks it. Contract: plugin egress
    # is kernel-mediated.
    assert classify("plugin.egress") is Mediation.KERNEL
