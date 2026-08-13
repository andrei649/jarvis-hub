import json

import pytest

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.mcp import route_tools as route_tools_mod
from agents.core.mcp.route_tools import build_mutating_route_tools
from agents.core.mcp.server import JarvisMCPServer


async def _runner(agent_id: str, text: str) -> str:
    return f"{agent_id}: {text}"


class _FakeEvent:
    def __init__(self, event):
        self.event_type = getattr(event.event_type, "value", str(event.event_type))
        self.action_taken = event.action_taken
        self.content_preview = event.content_preview


class _FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(_FakeEvent(event))


def _fake_remember_invoker():
    calls = []

    async def _invoke(args):
        calls.append(dict(args))
        return {"ok": True, "id": "m-123"}

    return _invoke, calls


def _denying_contract(reason: str = "mcp_route_blocked") -> ContractTemplate:
    return ContractTemplate(
        kind="mcp.route.mutating",
        constraints=(predicate("deny", lambda view, now: False, reason=reason),),
    )


@pytest.mark.asyncio
async def test_mcp_mutating_route_contract_denial_blocks_write_and_audits(monkeypatch):
    monkeypatch.setattr(
        route_tools_mod,
        "MCP_MUTATING_ROUTE_CONTRACT",
        _denying_contract(),
        raising=False,
    )
    invoke, calls = _fake_remember_invoker()
    auditor = _FakeAuditor()
    tools = build_mutating_route_tools(
        {"memory_remember": invoke},
        auditor=auditor,
        read_only_enabled=True,
        mutating_enabled=True,
        identity_check=lambda _token: True,
    )
    server = JarvisMCPServer(
        _runner,
        {"jarvis": "Jarvis"},
        mutating_route_tools=tools,
    )

    result = await server.call_tool(
        "route_memory_remember",
        {"text": "private body", "metadata": {"source": "test"}, "evil": "DROP"},
    )

    assert result["isError"] is True
    assert "contract denied: mcp_route_blocked" in result["content"][0]["text"]
    assert calls == []
    assert len(auditor.events) == 1
    assert auditor.events[0].action_taken.endswith("(refused-contract)")
    assert "private body" not in auditor.events[0].content_preview
    assert "source" not in auditor.events[0].content_preview


@pytest.mark.asyncio
async def test_mcp_mutating_route_contract_allows_existing_success_path(monkeypatch):
    from agents.core.kernel import Decision, Verdict

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    invoke, calls = _fake_remember_invoker()
    auditor = _FakeAuditor()
    tools = build_mutating_route_tools(
        {"memory_remember": invoke},
        auditor=auditor,
        read_only_enabled=True,
        mutating_enabled=True,
        identity_check=lambda _token: True,
        kernel=lambda _action: Decision(Verdict.GRANT, reason="test grant"),
    )
    server = JarvisMCPServer(
        _runner,
        {"jarvis": "Jarvis"},
        mutating_route_tools=tools,
    )

    result = await server.call_tool("route_memory_remember", {"text": "buy milk"})

    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"ok": True, "id": "m-123"}
    assert calls == [{"text": "buy milk"}]
    assert len(auditor.events) == 1
    assert auditor.events[0].action_taken.endswith("(ok)")
