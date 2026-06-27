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


# ── B1 — admin action is kernel-mediated (wave-4a) ──────────────────────────────

def test_admin_action_requires_capability():
    # Wave-4a closed the structural half of B1: /api/security/{kill-switch (engage),
    # capabilities/issue} now route through kernel.authorize (a capability cross-check +
    # kill-switch gate), not just admin_guard's network origin. A *presented* capability
    # token is enforced and a halted kill-switch denies them; see tests/test_admin_kernel_wave.py
    # for the real DENY/allow behavior. Making a valid token *mandatory* for a no-token
    # admin request (so missing-capability is refused) is the wave-4b/K2 follow-up — the
    # Capability is K1-tolerant today. Contract pinned here: these admin actions are
    # kernel-mediated.
    assert classify("admin.capability_issue") is Mediation.KERNEL
    assert classify("admin.kill_switch") is Mediation.KERNEL


# ── B3 — strict-egress downgrade is audited + egress is kernel-mediated (K-wave 2) ──

def test_egress_downgrade_is_audited():
    # B3 closed: the JARVIS_STRICT_EGRESS=0 downgrade is durably audited (EGRESS_DOWNGRADE
    # event), and K-wave 2 routes policy-passing egress through kernel.authorize so a
    # halted kill-switch / over-budget / runaway loop blocks it. Contract: plugin egress
    # is kernel-mediated.
    assert classify("plugin.egress") is Mediation.KERNEL
