"""H558 — per-client rate limits on Nerva's MCP write surface.

Owner's side: an external MCP client (a desktop app, an editor, another agent) can write
through the allow-listed mutating route tools and answer approval cards, but a leaked
credential or a runaway client cannot drive those writes faster than a per-client minute
and hour budget and a hub-wide minute budget. A refused write reaches nothing, says when to
retry, and leaves an audit row; another client's budget is untouched.
"""
from __future__ import annotations

import json

import pytest

from agents.core.kernel import Decision, Verdict
from agents.core.mcp.inbox_tools import APPROVAL_RESPOND, InboxBackend, InboxTools
from agents.core.mcp.route_tools import MUTATING_ROUTE_ALLOWLIST, build_mutating_route_tools
from agents.core.mcp.server import JarvisMCPServer, VerifiedMCPIdentity
from agents.core.mcp.write_quota import WriteQuota


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_quota_windows_per_caller_and_hub_wide():
    clock = Clock()
    quota = WriteQuota(per_minute=3, per_hour=5, global_per_minute=4, clock=clock)
    assert [quota.admit("a") for _ in range(3)] == [None, None, None]
    wait = quota.admit("a")
    assert wait is not None and 59 <= wait <= 60          # the minute window
    assert quota.admit("b") is None                       # another caller is untouched
    assert quota.admit("c") is not None                   # … until the hub-wide minute fills
    clock.now += 61
    assert quota.admit("a") is None and quota.admit("a") is None
    clock.now += 61
    hour_wait = quota.admit("a")                          # 5 in the hour already
    assert hour_wait is not None and hour_wait > 60
    clock.now += 3600
    assert quota.admit("a") is None


def test_refused_calls_do_not_count():
    clock = Clock()
    quota = WriteQuota(per_minute=1, per_hour=10, global_per_minute=10, clock=clock)
    assert quota.admit("a") is None
    for _ in range(20):
        assert quota.admit("a") is not None
    clock.now += 60.5
    assert quota.admit("a") is None


class _Auditor:
    def __init__(self):
        self.actions = []

    def log(self, event):
        self.actions.append(event.action_taken)


def _server(writes):
    async def invoke(args):
        writes.append(dict(args))
        return {"ok": True}

    auditor = _Auditor()
    tools = build_mutating_route_tools(
        {"memory_remember": invoke}, auditor=auditor, read_only_enabled=True,
        mutating_enabled=True, identity_check=lambda token: token in ("tok-a", "tok-b"),
        kernel=lambda action: Decision(Verdict.GRANT, reason="test"))
    assert tools and tools[0].spec in MUTATING_ROUTE_ALLOWLIST
    server = JarvisMCPServer(lambda *_: None, {}, mutating_route_tools=tools)
    server.write_quota = WriteQuota(per_minute=2, per_hour=100, global_per_minute=100)
    return server, tools[0].tool_name, auditor


@pytest.fixture(autouse=True)
def _kernel_on(monkeypatch):
    monkeypatch.setattr("agents.core.kernel.kernel_enabled", lambda: True)


async def test_mutating_route_tool_is_rate_limited_per_client():
    writes = []
    server, name, auditor = _server(writes)
    args = {"text": "remember this"}
    for _ in range(2):
        result = await server.call_tool(name, args, identity="tok-a")
        assert result["isError"] is False, result
    refused = await server.call_tool(name, args, identity="tok-a")
    assert refused["isError"] is True
    assert refused["content"][0]["text"].startswith("rate limited") and "nothing was written" in \
        refused["content"][0]["text"]
    assert len(writes) == 2
    assert any("refused-rate" in a for a in auditor.actions)
    assert (await server.call_tool(name, args, identity="tok-b"))["isError"] is False
    assert len(writes) == 3


async def test_oauth_subjects_have_their_own_budgets():
    writes = []
    server, name, _auditor = _server(writes)
    server.mutating_route_tools[name].identity_check = lambda token: True
    one, two = VerifiedMCPIdentity("alice"), VerifiedMCPIdentity("bob")
    for _ in range(2):
        assert (await server.call_tool(name, {"text": "x"}, identity=one))["isError"] is False
    assert (await server.call_tool(name, {"text": "x"}, identity=one))["isError"] is True
    assert (await server.call_tool(name, {"text": "x"}, identity=two))["isError"] is False


async def test_approval_answers_are_rate_limited_too():
    decided = []

    async def list_conversations(limit):
        return []

    async def read_conversation(sid, limit):
        return {"session_id": sid, "turns": []}

    async def list_approvals():
        return {"pending": [{"id": i, "reversible": True} for i in range(1, 10)]}

    async def decide(task_id, action, reason):
        decided.append(task_id)
        return 200, {"ok": True, "task": {"id": task_id, "status": "approved"}}

    audit = _Auditor()
    tools = InboxTools(InboxBackend(list_conversations, read_conversation, list_approvals, decide),
                       writes_enabled=lambda: True, auditor=audit)
    server = JarvisMCPServer(lambda *_: None, {}, inbox_tools=tools)
    server.write_quota = WriteQuota(per_minute=2, per_hour=100, global_per_minute=100)
    for card in (1, 2):
        out = await server.call_tool(APPROVAL_RESPOND, {"card_id": card, "decision": "approve"},
                                     identity="owner-tok", owner=True)
        assert out["isError"] is False, out
    out = await server.call_tool(APPROVAL_RESPOND, {"card_id": 3, "decision": "approve"},
                                 identity="owner-tok", owner=True)
    assert out["isError"] is True and out["content"][0]["text"].startswith("rate limited")
    assert decided == [1, 2]
    assert "mcp approval_respond (refused-rate)" in audit.actions
    # Reads are not limited.
    listed = await server.call_tool("approvals_list", {}, identity="owner-tok", owner=True)
    assert listed["isError"] is False and json.loads(listed["content"][0]["text"])
