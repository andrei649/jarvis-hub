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


def _guarded_server(calls):
    agents = {"jarvis": "Prime orchestrator"}

    async def runner(agent_id, text):
        calls.append((agent_id, text))
        return "ran"

    def guard(_agent_id, text, identity):
        if text == "add event":
            return "direct skill commands are not exposed over MCP"
        return None

    return JarvisMCPServer(runner, agents, agent_request_guard=guard)


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


@pytest.mark.asyncio
async def test_agent_request_guard_refuses_hidden_skill_command_before_runner():
    calls = []
    res = await _guarded_server(calls).call_tool("ask_jarvis", {"text": "add event"})
    assert res["isError"] is True
    assert "direct skill commands" in res["content"][0]["text"]
    assert calls == []


@pytest.mark.asyncio
async def test_agent_request_guard_receives_identity_before_runner():
    seen = []

    async def runner(agent_id, text):
        seen.append(("runner", agent_id, text))
        return "ran"

    def guard(agent_id, text, identity):
        seen.append(("guard", agent_id, text, identity))
        return None if identity == "owner-token" else "owner identity required"

    srv = JarvisMCPServer(
        runner, {"jarvis": "Prime orchestrator"}, agent_request_guard=guard
    )
    refused = await srv.call_tool("ask_jarvis", {"text": "start LM Studio"})
    allowed = await srv.call_tool(
        "ask_jarvis", {"text": "start LM Studio"}, identity="owner-token"
    )

    assert refused["isError"] is True
    assert allowed["isError"] is False
    assert seen == [
        ("guard", "jarvis", "start LM Studio", None),
        ("guard", "jarvis", "start LM Studio", "owner-token"),
        ("runner", "jarvis", "start LM Studio"),
    ]


def test_complete_tool_inventory_classifies_every_exposed_tool():
    inventory = _guarded_server([]).tool_inventory()
    assert {row["name"] for row in inventory} == {"ask_jarvis"}
    assert all(row["governance"] == "governed" for row in inventory)
    assert all(row["persistent_state"] is True for row in inventory)
    assert all(row["direct_route_mutation"] is False for row in inventory)
    assert all("conversation_user_turn" in row["state_effects"] for row in inventory)
    assert all("conversation_assistant_turn" in row["state_effects"] for row in inventory)
    assert all("direct_skill_commands_refused" in row["controls"] for row in inventory)
    assert all(
        "local_model_lifecycle_identity_required" in row["controls"]
        for row in inventory
    )
    assert all(
        "local_model_lifecycle_when_explicitly_requested" in row["state_effects"]
        for row in inventory
    )


@pytest.mark.asyncio
async def test_production_mcp_runner_inventory_matches_durable_conversation_state(
    tmp_path, monkeypatch
):
    """The production builder's ``ask_*`` runner persists MCP conversation turns.

    This deliberately uses the real Orchestrator entry point and durable
    ConversationMemory, with only the LLM-facing seams replaced by hermetic
    stubs. The inventory must advertise the before/after state effect.
    """
    from types import SimpleNamespace

    from agents import web
    from agents.core.config import JarvisConfig
    from agents.core.memory import conversation, persistence
    from agents.core.orchestrator import Orchestrator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.delenv("JARVIS_MCP_ROUTE_TOOLS", raising=False)
    monkeypatch.delenv("JARVIS_MCP_MUTATING_TOOLS", raising=False)

    orch = Orchestrator(JarvisConfig())
    orch.agents = {"jarvis": SimpleNamespace(config={"name": "Jarvis", "tier": "prime"})}
    orch.session_id = await orch.memory.new_session("session_mcp_inventory")

    class _Intent:
        target_agents = ["jarvis"]
        is_general = True
        confidence = 1.0
        context = {}

    async def _classify(_text, _agents):
        return _Intent()

    async def _plugin_data(_text, _intent):
        return {}

    async def _parallel(_agent_ids, _text, _context, _plugin_data=None):
        return {"jarvis": "durable reply"}

    async def _complete(**kwargs):
        await orch.memory.add_turn(
            orch.session_id,
            "assistant",
            kwargs["synthesized"],
            agent_id=kwargs["responder_id"],
        )

    orch.router.classify = _classify
    orch._gather_plugin_data = _plugin_data
    orch._call_agents_parallel = _parallel
    orch._complete_llm_turn = _complete
    orch.llm_router.select_backend = lambda _agent, _text: (None, "", "local")
    monkeypatch.setattr(web, "orch", orch)

    server = web._build_mcp_server()
    row = next(item for item in server.tool_inventory() if item["name"] == "ask_jarvis")
    assert row["persistent_state"] is True
    assert row["state_effects"][:2] == [
        "conversation_user_turn",
        "conversation_assistant_turn",
    ]

    before = await orch.memory.get_history("session_mcp_inventory")
    result = await server.call_tool("ask_jarvis", {"text": "persist this turn"})
    after = await orch.memory.get_history("session_mcp_inventory")

    assert result["isError"] is False
    assert before == []
    assert [(turn["role"], turn["content"]) for turn in after] == [
        ("user", "persist this turn"),
        ("assistant", "durable reply"),
    ]
    snapshot = persistence.load_memory("session_mcp_inventory")
    assert [(turn["role"], turn["content"]) for turn in snapshot] == [
        ("user", "persist this turn"),
        ("assistant", "durable reply"),
    ]


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
        assert body["tool_inventory"]
        assert all(row["governance"] == "governed" for row in body["tool_inventory"])
        # RPC is gated off by default
        rpc = c.post("/api/mcp/server/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert rpc.status_code == 403


def test_rpc_transport_gate_enforces_user_token(monkeypatch):
    """With server mode on and OAuth off, the RPC transport still demands the same
    user/admin token as every other route (review F1) — not wide-open to callers."""
    from agents import web
    with TestClient(web.app) as c:
        orig = web.orch.get_setting

        def fake_get_setting(key, default=None):
            if key == "mcp.server_enabled":
                return True
            if key == "mcp.oauth_required":
                return False
            return orig(key, default)

        monkeypatch.setattr(web.orch, "get_setting", fake_get_setting)
        monkeypatch.setattr(web, "USER_TOKEN", "secret-tok")
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        # No token → 401, even though server mode is enabled.
        assert c.post("/api/mcp/server/rpc", json=body).status_code == 401
        # Valid user token → passes the gate to the JSON-RPC handler.
        ok = c.post("/api/mcp/server/rpc", json=body, headers={"x-user-token": "secret-tok"})
        assert ok.status_code == 200


def test_production_agent_guard_recognizes_direct_skill_commands(monkeypatch):
    from types import SimpleNamespace

    from agents import web

    monkeypatch.setattr(
        web,
        "orch",
        SimpleNamespace(
            skills=SimpleNamespace(
                parse_command=lambda text: ("calendar", "add_event", text)
            )
        ),
    )
    refusal = web._mcp_agent_request_guard("jarvis", "add_event tomorrow", "owner")
    assert "not exposed over MCP" in refusal


def test_production_agent_guard_requires_owner_identity_for_model_lifecycle(monkeypatch):
    from types import SimpleNamespace

    from agents import web

    old_user, old_admin = web.USER_TOKEN, web.ADMIN_TOKEN
    try:
        web.USER_TOKEN = "owner-token"
        web.ADMIN_TOKEN = "admin-token"
        monkeypatch.setattr(
            web,
            "orch",
            SimpleNamespace(skills=SimpleNamespace(parse_command=lambda _text: None)),
        )

        assert "owner identity" in web._mcp_agent_request_guard(
            "jarvis", "start LM Studio", None
        )
        assert "owner identity" in web._mcp_agent_request_guard(
            "jarvis", "ollama load qwen2.5:7b", "wrong"
        )
        assert web._mcp_agent_request_guard(
            "jarvis", "ollama load qwen2.5:7b", "owner-token"
        ) is None
        from agents.core.mcp.server import VerifiedMCPIdentity

        assert web._mcp_agent_request_guard(
            "jarvis", "start Ollama", VerifiedMCPIdentity("oauth-owner")
        ) is None
        assert "ask_jarvis" in web._mcp_agent_request_guard(
            "frigga", "start Ollama", "owner-token"
        )
    finally:
        web.USER_TOKEN, web.ADMIN_TOKEN = old_user, old_admin
