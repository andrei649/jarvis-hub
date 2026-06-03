"""Tests for H10.5 — MCP Server Mode.

The JSON-RPC server core is transport-agnostic and takes an injected runner,
so it's tested fully offline (no orchestrator). Also asserts the governed
HTTP surface (status + RPC gated off by default).
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.mcp.server import JarvisMCPServer, PROTOCOL_VERSION


def _server(allowed=None, calls=None):
    agents = {"jarvis": "Prime orchestrator", "frigga": "Family (local-only)"}

    async def runner(agent_id, text):
        if calls is not None:
            calls.append((agent_id, text))
        return f"[{agent_id}] {text}"

    return JarvisMCPServer(runner, agents, allowed_agents=allowed)


# ── tool listing ────────────────────────────────────────────────────────────

def test_list_tools_one_per_agent():
    tools = _server().list_tools()
    names = {t["name"] for t in tools}
    assert names == {"ask_jarvis", "ask_frigga"}
    for t in tools:
        assert t["inputSchema"]["required"] == ["text"]


def test_allowlist_restricts_exposed_agents():
    srv = _server(allowed=["jarvis"])
    assert {t["name"] for t in srv.list_tools()} == {"ask_jarvis"}
    assert "frigga" not in srv.status()["exposed_agents"]


# ── tool calls ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_tool_routes_to_runner():
    calls = []
    srv = _server(calls=calls)
    res = await srv.call_tool("ask_jarvis", {"text": "hello"})
    assert res["isError"] is False
    assert res["content"][0]["text"] == "[jarvis] hello"
    assert calls == [("jarvis", "hello")]


@pytest.mark.asyncio
async def test_call_unknown_tool_is_error():
    res = await _server().call_tool("ask_nobody", {"text": "hi"})
    assert res["isError"] is True


@pytest.mark.asyncio
async def test_call_blocked_agent_is_error():
    srv = _server(allowed=["jarvis"])
    res = await srv.call_tool("ask_frigga", {"text": "hi"})
    assert res["isError"] is True
    assert "not exposed" in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_call_missing_text_is_error():
    res = await _server().call_tool("ask_jarvis", {})
    assert res["isError"] is True


@pytest.mark.asyncio
async def test_runner_exception_does_not_leak():
    async def boom(agent_id, text):
        raise RuntimeError("kaboom")

    srv = JarvisMCPServer(boom, {"jarvis": "x"})
    res = await srv.call_tool("ask_jarvis", {"text": "hi"})
    assert res["isError"] is True
    assert "agent error" in res["content"][0]["text"]


# ── JSON-RPC dispatch ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize_handshake():
    res = await _server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert res["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in res["result"]["capabilities"]


@pytest.mark.asyncio
async def test_tools_list_via_rpc():
    res = await _server().handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(res["result"]["tools"]) == 2


@pytest.mark.asyncio
async def test_tools_call_via_rpc():
    res = await _server().handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "ask_jarvis", "arguments": {"text": "ping"}},
    })
    assert res["result"]["content"][0]["text"] == "[jarvis] ping"


@pytest.mark.asyncio
async def test_notification_returns_none():
    res = await _server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert res is None


@pytest.mark.asyncio
async def test_unknown_method_errors():
    res = await _server().handle({"jsonrpc": "2.0", "id": 9, "method": "bogus"})
    assert res["error"]["code"] == -32601


# ── governed HTTP surface ───────────────────────────────────────────────────

def test_mcp_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        status = c.get("/api/mcp/server")
        assert status.status_code == 200
        body = status.json()
        assert body["enabled"] is False           # disabled by default
        assert body["lan_only"] is True
        # RPC is gated off by default
        rpc = c.post("/api/mcp/server/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert rpc.status_code == 403
