"""ORIZONT-24 K1 wave-3 (tool.rpc slice) — gated Tool-RPC calls route through the
Action Kernel.

A gated (external/mutating) Tool-RPC call already enqueues an ask-tier approval task
instead of running from the sandbox. The kernel adds a veto *before* the enqueue: a
DENY (halted kill-switch / over-budget / runaway loop) refuses the call outright. Read-
only (inline) tools are unaffected. Default-off behind ``JARVIS_ACTION_KERNEL``.
"""
import asyncio

import pytest

from agents.core.kernel import Action, Decision, Verdict
from agents.core.tool_rpc import ToolRPCServer


class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls, self._v, self._r = [], verdict, reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._v, reason=self._r)


def _server(*, kernel=None, enqueued=None):
    def _enqueue(*a, **k):
        if enqueued is not None:
            enqueued.append((a, k))
        return 42

    async def _ro(args):
        return {"echo": args}

    async def _gated(args):
        return {"did": "write"}

    srv = ToolRPCServer(enqueue=_enqueue, kernel=kernel)
    srv.register_tool("read", _ro, gated=False)
    srv.register_tool("danger", _gated, gated=True)
    return srv


# ── default-off ────────────────────────────────────────────────────────────────
def test_flag_off_skips_kernel_even_when_bound(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    spy = _SpyKernel(verdict=Verdict.DENY)        # would block — but flag is off
    enq = []
    out = asyncio.run(_server(kernel=spy, enqueued=enq).handle({"tool": "danger", "args": {}}))
    assert out["reason"] == "approval_required" and out["task_id"] == 42   # enqueued as before
    assert spy.calls == []


# ── flag-on routing ──────────────────────────────────────────────────────────────
def test_kernel_deny_blocks_before_enqueue(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.DENY, reason="kill-switch engaged for scope 'global'")
    enq = []
    out = asyncio.run(_server(kernel=spy, enqueued=enq).handle({"tool": "danger", "args": {"k": "v"}}))
    assert out["ok"] is False and out["reason"] == "kernel_denied"
    assert "kill-switch engaged" in out["detail"]
    assert enq == []                              # never reached the approval queue
    assert spy.calls and spy.calls[-1].kind == "tool.rpc"
    assert spy.calls[-1].payload["args_keys"] == ["k"]   # keys only, no values


def test_kernel_grant_still_enqueues(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.GRANT)
    enq = []
    out = asyncio.run(_server(kernel=spy, enqueued=enq).handle({"tool": "danger", "args": {}}))
    assert out["reason"] == "approval_required" and enq        # mediated, then enqueued
    assert spy.calls and spy.calls[-1].kind == "tool.rpc"


def test_readonly_tool_never_consults_kernel(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.DENY)        # would block a gated call
    out = asyncio.run(_server(kernel=spy).handle({"tool": "read", "args": {"x": 1}}))
    assert out["ok"] is True and out["result"] == {"echo": {"x": 1}}   # read-only ran inline
    assert spy.calls == []                        # the kernel only gates the gated path


# ── integration: the *real* bound kernel + real KillSwitch ─────────────────────────
def test_real_bound_kernel_halt_blocks_gated_tool(tmp_path, monkeypatch):
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

    enq = []
    srv = _server(kernel=make_action_kernel(_Orch()), enqueued=enq)

    kill.engage("global", reason="test")
    denied = asyncio.run(srv.handle({"tool": "danger", "args": {}}))
    assert denied["reason"] == "kernel_denied" and enq == []   # halt → not enqueued

    kill.disengage("global")
    ok = asyncio.run(srv.handle({"tool": "danger", "args": {}}))
    assert ok["reason"] == "approval_required" and enq         # released → enqueued
