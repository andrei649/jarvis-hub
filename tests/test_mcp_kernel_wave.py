"""ORIZONT-24 K1 wave-3 (mcp.mutating slice) — MCP mutating tools route through the
Action Kernel.

The per-identity gate proves *who*; the kernel decides *whether the write may run now*
(a halted kill-switch / over-budget / runaway loop blocks it). The kernel runs AFTER
identity and BEFORE the write; a DENY is audited (``refused-kernel``) and raises
``MutatingKernelError`` — no write happens. Default-off behind ``JARVIS_ACTION_KERNEL``.
"""
import asyncio

import pytest

from agents.core.kernel import Action, Decision, Verdict
from agents.core.mcp.route_tools import (
    MUTATING_ROUTE_ALLOWLIST,
    MutatingIdentityError,
    MutatingKernelError,
    MutatingRouteTool,
    build_mutating_route_tools,
)

SPEC = MUTATING_ROUTE_ALLOWLIST[0]


class _Audit:
    def __init__(self):
        self.outcomes = []

    def log(self, event):
        self.outcomes.append(getattr(event, "action_taken", ""))


class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls, self._v, self._r = [], verdict, reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._v, reason=self._r)


def _tool(*, kernel=None, auditor=None, identity=lambda _t: True, invoked=None):
    async def _invoke(kwargs):
        if invoked is not None:
            invoked.append(kwargs)
        return {"ok": True}
    return MutatingRouteTool(spec=SPEC, invoke=_invoke, auditor=auditor,
                             identity_check=identity, kernel=kernel)


# ── default-off ────────────────────────────────────────────────────────────────
def test_flag_off_skips_kernel_even_when_bound(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    spy = _SpyKernel(verdict=Verdict.DENY)        # would block — but flag is off
    invoked = []
    out = asyncio.run(_tool(kernel=spy, invoked=invoked).call({"text": "hi"}, token="ok"))
    assert out == {"ok": True} and invoked            # the write ran
    assert spy.calls == []                            # kernel never consulted while off


def test_no_kernel_bound_writes(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    invoked = []
    asyncio.run(_tool(kernel=None, invoked=invoked).call({"text": "hi"}, token="ok"))
    assert invoked                                    # unchanged behavior when no kernel


# ── flag-on routing ──────────────────────────────────────────────────────────────
def test_kernel_deny_blocks_write_and_audits(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.DENY, reason="kill-switch engaged for scope 'global'")
    audit, invoked = _Audit(), []
    tool = _tool(kernel=spy, auditor=audit, invoked=invoked)
    with pytest.raises(MutatingKernelError, match="blocked by kernel: kill-switch engaged"):
        asyncio.run(tool.call({"text": "hi"}, token="ok"))
    assert invoked == []                              # the write never ran
    assert spy.calls and spy.calls[-1].kind == "mcp.mutating"
    assert spy.calls[-1].origin == "external"
    assert any("refused-kernel" in a for a in audit.outcomes)


def test_kernel_grant_allows_write(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.GRANT)
    invoked = []
    asyncio.run(_tool(kernel=spy, invoked=invoked).call({"text": "hi"}, token="ok"))
    assert invoked and spy.calls                      # mediated, then written


def test_identity_failure_precedes_kernel(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.GRANT)
    tool = _tool(kernel=spy, identity=lambda _t: False)
    with pytest.raises(MutatingIdentityError):
        asyncio.run(tool.call({"text": "hi"}, token=None))
    assert spy.calls == []                            # identity refused before the kernel


# ── builder threads the kernel ───────────────────────────────────────────────────
def test_builder_threads_kernel():
    spy = _SpyKernel()

    async def _inv(_k):
        return {"ok": True}
    tools = build_mutating_route_tools(
        {SPEC.name: _inv}, auditor=_Audit(), read_only_enabled=True,
        mutating_enabled=True, identity_check=lambda _t: True, kernel=spy)
    assert tools and tools[0].kernel is spy


# ── integration: the *real* bound kernel + real KillSwitch ─────────────────────────
def test_real_bound_kernel_halt_blocks_write(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    kill = KillSwitch(tmp_path / "kill.json")

    class _Orch:
        autonomy_policy = AutonomyPolicy()
        kill_switch = kill
        capabilities = CapabilityBroker()
        intent_log = None

    invoked = []
    tool = _tool(kernel=make_action_kernel(_Orch()), invoked=invoked)

    kill.engage("global", reason="test")
    with pytest.raises(MutatingKernelError, match="blocked by kernel"):
        asyncio.run(tool.call({"text": "hi"}, token="ok"))
    assert invoked == []                              # halt → no write

    kill.disengage("global")
    asyncio.run(tool.call({"text": "hi"}, token="ok"))
    assert invoked                                    # released → write ran
