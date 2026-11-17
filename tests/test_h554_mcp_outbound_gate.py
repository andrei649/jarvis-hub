"""H554 — the outbound gate for a write-capable MCP tool, end to end through ToolRPC.

Owner's side: on a server the owner trusts with writes (``full``), a tool the server did not
declare ``readOnlyHint: true`` becomes an approval card in the governed queue and nothing
reaches the server until the owner approves; if the queue cannot take the card, the call is
refused (never run); an Action Kernel DENY refuses before any frame is written; each call
leaves an audit row; and a policy refusal tells the model not to retry. On a ``read-only``
server such a tool is never offered, and a trust spelling the client does not know fails
closed to read-only.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.mcp.client import MCPManager, MCPServer  # noqa: E402
from agents.core.mcp.model_bridge import MCPBridgeError, MCPModelBridge  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402

TOOLS = [
    {"name": "read", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
    {"name": "send", "inputSchema": {"type": "object", "properties": {"to": {"type": "string"}}}},
    {"name": "truthy", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": "yes"}},
]


class Audit:
    def __init__(self):
        self.rows = []

    def record(self, *, actor, action, why, metadata):
        self.rows.append((action, why))


def _manager(trust="full", calls=None):
    srv = MCPServer("mail", command="mail-mcp", trust=trust)

    async def fake_send(message):
        if message["method"] == "tools/list":
            return {"result": {"tools": TOOLS}}
        if calls is not None:
            calls.append(message["params"])
        return {"result": {"content": [{"type": "text", "text": "sent"}]}}

    srv._send = fake_send
    asyncio.run(srv._list_tools())
    mgr = MCPManager()
    mgr.register(srv)
    return mgr


def _rpc(mgr, **kw):
    rpc = ToolRPCServer(**kw)
    asyncio.run(MCPModelBridge(rpc, lambda: mgr).sync())
    return rpc


def test_write_capable_tool_queues_a_card_and_sends_nothing():
    calls, cards = [], []
    audit = Audit()

    def enqueue(agent, kind, title, **kwargs):
        cards.append((kind, kwargs["payload"], kwargs.get("autonomy_level")))
        return 11

    rpc = _rpc(_manager(calls=calls), enqueue=enqueue, audit=audit)
    gated = {row["name"]: row["gated"] for row in rpc.tools()}
    # A missing annotation and a truthy non-bool both count as write-capable.
    assert gated == {"mcp__mail__read": False, "mcp__mail__send": True, "mcp__mail__truthy": True}
    out = asyncio.run(rpc.handle({"tool": "mcp__mail__send", "args": {"to": "x"}}))
    assert out["reason"] == "approval_required" and out["task_id"] == 11
    assert calls == []
    [(kind, payload, level)] = cards
    assert kind == "toolrpc.mcp__mail__send" and level == "ask" and payload["args"] == {"to": "x"}
    assert ("toolrpc.gated", "mcp__mail__send") in audit.rows


def test_an_approval_system_failure_blocks_rather_than_allows():
    calls = []

    def broken(agent, kind, title, **kwargs):
        raise RuntimeError("queue down")

    rpc = _rpc(_manager(calls=calls), enqueue=broken)
    out = asyncio.run(rpc.handle({"tool": "mcp__mail__send", "args": {"to": "x"}}))
    assert out["ok"] is False and out["reason"] == "enqueue_failed" and calls == []
    no_queue = _rpc(_manager(calls=calls))
    out = asyncio.run(no_queue.handle({"tool": "mcp__mail__send", "args": {"to": "x"}}))
    assert out["ok"] is False and out["reason"] == "approval_required" and calls == []


def test_a_kernel_deny_refuses_before_the_frame(monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.kernel.kernel_enabled", lambda: True)
    asked = []

    def kernel(action):
        asked.append(action)
        return Decision(Verdict.DENY, "owner policy: no mail")

    rpc = _rpc(_manager(calls=calls), enqueue=lambda *a, **k: 1, kernel=kernel)
    out = asyncio.run(rpc.handle({"tool": "mcp__mail__send", "args": {"to": "x"}}))
    assert out["reason"] == "kernel_denied" and calls == []
    assert asked and asked[0].payload["tool"] == "mcp__mail__send"
    assert asked[0].payload["args_keys"] == ["to"]          # keys, never values


def test_a_read_only_tool_runs_and_is_audited():
    calls = []
    audit = Audit()
    rpc = _rpc(_manager(calls=calls), audit=audit)
    out = asyncio.run(rpc.handle({"tool": "mcp__mail__read", "args": {}}))
    assert out["ok"] is True and calls == [{"name": "read", "arguments": {}}]
    assert ("toolrpc.call", "mcp__mail__read") in audit.rows


def test_read_only_tier_never_offers_a_write_and_unknown_tiers_fail_closed():
    rpc = _rpc(_manager(trust="read-only"))
    assert [row["name"] for row in rpc.tools()] == ["mcp__mail__read"]
    with pytest.raises(ValueError):
        MCPServer("x", command="x", trust="trusted-ish")
    mgr = MCPManager()
    mgr.load_from_config([{"name": "x", "command": "x", "trust": "TRUSTED"}])
    assert mgr.servers["x"].trust == "read-only"


def test_a_policy_refusal_tells_the_model_not_to_retry():
    mgr = _manager(trust="read-only")
    bridge = MCPModelBridge(ToolRPCServer(), lambda: mgr)
    handler = bridge._handler("mcp__mail__send", "mail")
    with pytest.raises(MCPBridgeError) as exc:
        asyncio.run(handler({"to": "x"}))
    assert "do not retry" in str(exc.value) and str(exc.value).startswith("trust_denied")
    rpc = _rpc(_manager(), enqueue=lambda *a, **k: 1)
    rpc.register_tool("probe", handler, gated=False)
    out = asyncio.run(rpc.handle({"tool": "probe", "args": {"to": "x"}}))
    assert out["reason"] == "tool_error" and "do not retry" in out["error"]
