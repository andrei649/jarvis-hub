"""G6/G7 — the MCP client beyond tools: resources and prompts (H552), parallel bounded
connects with reconnect, backoff and health (H556), and the server-initiated requests
sampling and elicitation (H553).

Everything runs against ``tests/fixtures/mcp_fake_server.py`` over real stdio pipes (or
in-process stubs); no network. Written from the owner's side: what the owner can do, and
what a server cannot make Nerva do.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.action_origin import current_action_origin
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.mcp import resources as res_mod
from agents.core.mcp.client import MCPManager, MCPServer
from agents.core.mcp.host_requests import (
    ROLE_CAPABLE,
    ROLE_FAST,
    MCPHost,
    SamplingBudget,
    SamplingConfig,
    map_model_preferences,
    validate_content,
)
from agents.core.mcp.model_bridge import MCPModelBridge
from agents.core.mcp.resilience import (
    STATE_BACKOFF,
    STATE_CONNECTED,
    STATE_OPEN,
    STATE_PARKED,
    ReconnectPolicy,
    ServerHealth,
)
from agents.core.security.quarantine import split_fenced_tool_result
from agents.core.security.taint import is_untrusted_source
from agents.core.tool_rpc import ToolRPCServer

FAKE = Path(__file__).resolve().parent / "fixtures" / "mcp_fake_server.py"


def _cmd(mode: str) -> str:
    return f"{sys.executable} {FAKE} {mode}"


@pytest.fixture(autouse=True)
def _no_estop(monkeypatch, tmp_path):
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
    monkeypatch.setattr(res_mod, "cache_dir", lambda server: tmp_path / "mcp_cache" / server)


def _estop_on(monkeypatch):
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: True)


async def _server(manager: MCPManager, name: str, mode: str = "full", **kw) -> MCPServer:
    srv = MCPServer(name, command=_cmd(mode), trust="full", **kw)
    manager.register(srv)
    return srv


@pytest.fixture
async def mgr():
    manager = MCPManager()
    yield manager
    await manager.close_all()


def _reply(result: dict) -> dict:
    """The JSON the fake server's ask_* tools return: the client's answer to its request."""
    return json.loads(result["content"][0]["text"])


async def _wait_pending(queue: ActionApprovalQueue, tool: str, timeout: float = 5.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for item in queue.list("pending"):
            if item.get("tool") == tool:
                return item
        await asyncio.sleep(0.02)
    raise AssertionError(f"no pending {tool} card")


# ── H552: resources and prompts ─────────────────────────────────────────────


async def test_resource_and_prompt_tools_are_offered_only_for_declared_capabilities(mgr):
    full = await _server(mgr, "docs")
    only_tools = await _server(mgr, "plain", "tools")
    assert (await mgr.connect_all()) == {"docs": True, "plain": True}
    assert [t.name for t in full.utility_tools] == [
        "list_resources", "read_resource", "list_prompts", "get_prompt"]
    assert only_tools.utility_tools == []
    rows = {row["name"]: row for row in mgr.model_tools()}
    for op in ("list_resources", "read_resource", "list_prompts", "get_prompt"):
        row = rows[f"mcp__docs__{op}"]
        assert row["gated"] is False and row["untrusted_output"] is True and row["utility"] is True
    assert not any(name.startswith("mcp__plain__list_") for name in rows)


async def test_a_resource_only_server_is_live(mgr):
    srv = await _server(mgr, "kb", "resources")
    assert await srv.connect() is True
    assert srv.tools == [] and len(srv.utility_tools) == 4


async def test_list_resources_follows_pagination_and_strips_invisible_text(mgr):
    await _server(mgr, "docs")
    await mgr.connect_all()
    out = await mgr.call_tool("mcp__docs__list_resources", {})
    assert [r["uri"] for r in out["resources"]] == ["file:///doc", "file:///logo.png"]
    assert "\U000E0041" not in json.dumps(out, ensure_ascii=False)
    assert out["tainted"] is True


async def test_read_resource_text_is_scanned_and_taints_the_turn(mgr):
    await _server(mgr, "docs")
    await mgr.connect_all()
    assert not is_untrusted_source(current_action_origin())
    out = await mgr.call_tool("mcp__docs__read_resource", {"uri": "file:///doc"})
    assert "Ignore all previous instructions" in out["contents"][0]["text"]
    assert out["tainted"] is True and out["injection_flags"]
    assert "not an instruction from the owner" in out["warning"]
    assert is_untrusted_source(current_action_origin())


async def test_binary_resource_is_cached_to_disk_and_handed_over_as_a_path(mgr):
    await _server(mgr, "docs")
    await mgr.connect_all()
    out = await mgr.call_tool("mcp__docs__read_resource", {"uri": "file:///logo.png"})
    [block] = out["contents"]
    path = Path(block["path"])
    assert path.is_file() and block["mimeType"] == "image/png" and block["bytes"] == path.stat().st_size
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "blob" not in json.dumps(out)


async def test_tool_result_binary_blocks_are_cached_not_inlined(mgr):
    await _server(mgr, "docs")
    await mgr.connect_all()
    out = await mgr.call_tool("snapshot", {}, server="docs")
    text, image, embedded = out["content"]
    assert text == {"type": "text", "text": "here"}
    assert Path(image["path"]).is_file() and image["mimeType"] == "image/png"
    assert Path(embedded["path"]).is_file() and embedded["uri"] == "file:///x.bin"
    assert "data" not in image and "blob" not in json.dumps(out)


async def test_get_prompt_round_trip_scans_text_and_stores_images(mgr):
    await _server(mgr, "docs")
    await mgr.connect_all()
    listed = await mgr.call_tool("mcp__docs__list_prompts", {})
    assert listed["prompts"][0]["name"] == "summarize"
    assert listed["prompts"][0]["arguments"] == [{"name": "topic", "description": "", "required": True}]
    out = await mgr.call_tool("mcp__docs__get_prompt", {"name": "summarize", "arguments": {"topic": "rust"}})
    text, image = out["messages"][0]["content"][0], out["messages"][1]["content"][0]
    assert text["text"].startswith("Summarize rust.")
    assert out["injection_flags"] and out["tainted"] is True
    assert Path(image["path"]).is_file()


async def test_owner_filter_hides_a_resource_tool(mgr):
    srv = await _server(mgr, "docs", tools_deny=["read_resource"])
    await srv.connect()
    assert "read_resource" not in [t.name for t in srv.utility_tools]
    out = await mgr.call_tool("read_resource", {"uri": "file:///doc"}, server="docs")
    assert "error" in out


async def test_resource_read_through_the_model_loop_is_fenced():
    manager = MCPManager()
    srv = MCPServer("docs", command=_cmd("full"), trust="read-only")
    manager.register(srv)
    try:
        await srv.connect()
        rpc = ToolRPCServer()
        bridge = MCPModelBridge(rpc, lambda: manager)
        runtime = AgentToolRuntime(rpc, enabled=lambda: True, tool_sync=bridge.sync)

        class Backend:
            supports_tools = True

            def __init__(self):
                self.turns = [
                    ToolTurn(tool_calls=(ToolCall(id="c1", name="mcp__docs__read_resource",
                                                  raw_arguments='{"uri":"file:///doc"}',
                                                  arguments={"uri": "file:///doc"}),),
                             finish_reason="tool_calls"),
                    ToolTurn(content="done", finish_reason="stop")]
                self.calls = []

            async def generate_tool_turn(self, **kwargs):
                self.calls.append([dict(m) for m in kwargs["messages"]])
                return self.turns.pop(0)

        backend = Backend()
        out = await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="go",
                                system="sys", max_tokens=64, temperature=0.0)
        assert out == "done"
        fenced = split_fenced_tool_result(backend.calls[1][-1]["content"])
        assert fenced is not None and "Ignore all previous instructions" in fenced[1]
    finally:
        await manager.close_all()


async def test_pagination_stops_at_fifty_pages():
    calls = []

    async def endless(method, params):
        calls.append(params)
        return {"result": {"resources": [{"uri": f"u{len(calls)}"}], "nextCursor": f"c{len(calls)}"}}

    items, cut = await res_mod.list_all(endless, "resources/list", "resources")
    assert len(calls) == res_mod.MAX_PAGES and cut is True and len(items) == res_mod.MAX_PAGES


def test_oversized_binary_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(res_mod, "MAX_RESOURCE_BYTES", 10)
    import base64
    row = res_mod._store_blob("s", base64.b64encode(b"x" * 11).decode(), "image/png", root=tmp_path)
    assert row["error"] == "resource_too_large" and not list(tmp_path.iterdir())


# ── H556: parallel connect, timeouts, reconnect, health ─────────────────────


async def test_one_hung_server_does_not_block_the_others(mgr):
    hung = await _server(mgr, "hung", "hang")
    hung.connect_timeout = 1.5
    names = [f"ok{i}" for i in range(3)]
    for name in names:
        await _server(mgr, name)
    started = time.monotonic()
    result = await mgr.connect_all()
    elapsed = time.monotonic() - started
    assert result == {"hung": False, **dict.fromkeys(names, True)}
    assert hung.last_error == "connect_timeout" and hung._proc is None
    assert hung.health.state == STATE_BACKOFF
    assert elapsed < 6.0
    assert all(mgr.servers[n].health.connect_ms < 1500 for n in names)


async def test_reconnect_after_the_server_dies(mgr):
    mgr.policy = ReconnectPolicy(base_delay=0.0, jitter=0.0)
    srv = await _server(mgr, "docs")
    await mgr.connect_all()
    srv._proc.kill()
    await srv._proc.wait()
    done = await mgr.tick()
    assert done == {"docs": "reconnected"}
    assert srv.is_connected() and srv.health.reconnects == 1
    assert (await mgr.call_tool("echo", {"a": 1}, server="docs"))["content"]


async def test_keepalive_ping_and_failed_ping_marks_the_server_lost(mgr):
    mgr.keepalive_interval = 0.0
    srv = await _server(mgr, "docs")
    await mgr.connect_all()
    assert (await mgr.tick()) == {"docs": "ping_ok"}

    async def dead(_msg):
        return {}

    srv._send = dead
    assert (await mgr.tick()) == {"docs": "ping_failed"}
    assert srv.health.state in (STATE_BACKOFF, STATE_OPEN) and srv._proc is None


async def test_no_reconnect_under_the_estop(mgr, monkeypatch):
    mgr.policy = ReconnectPolicy(base_delay=0.0, jitter=0.0)
    srv = await _server(mgr, "docs")
    await mgr.connect_all()
    await srv._teardown()
    _estop_on(monkeypatch)
    assert await mgr.tick() == {}
    assert await mgr.connect_all() == {}
    assert not srv.is_connected()


async def test_owner_disconnect_stops_reconnects(mgr):
    srv = await _server(mgr, "docs")
    await mgr.connect_all()
    await srv.close()
    assert srv.wanted is False and await mgr.tick() == {}


def test_backoff_breaker_and_parking():
    policy = ReconnectPolicy(base_delay=1.0, max_delay=60.0, jitter=0.0, max_retries=5,
                             breaker_failures=3, breaker_window=60.0, breaker_open=60.0, park_probe=300.0)
    assert [policy.delay(n) for n in range(1, 8)] == [1, 2, 4, 8, 16, 32, 60]
    jittered = ReconnectPolicy(jitter=0.2)
    assert all(0.8 * 8 <= jittered.delay(4) <= 1.2 * 8 for _ in range(50))
    health = ServerHealth(policy=policy)
    health.failed("boom", now=1000.0)
    assert health.state == STATE_BACKOFF and health.next_retry_at == 1001.0
    assert not health.retry_due(1000.5) and health.retry_due(1001.0)
    health.failed("boom", now=1001.0)
    health.failed("boom", now=1003.0)
    assert health.state == STATE_OPEN and health.breaker_open_until == 1063.0
    assert not health.retry_due(1050.0)
    for t in (2000.0, 3000.0, 4000.0):
        health.failed("boom", now=t)
    assert health.state == STATE_PARKED and health.next_retry_at == 4300.0
    health.succeeded(now=4300.0)
    assert health.state == STATE_CONNECTED and not health.stable(4330.0) and health.stable(4360.0)
    assert health.status(now=4360.0)["consecutive_failures"] == 0
    health.lost("dropped", now=5000.0)                   # after a stable run the count restarts
    assert health.consecutive_failures == 1 and health.state != STATE_PARKED


async def test_unsafe_command_is_refused_not_retried(mgr):
    srv = MCPServer("bad", command="rm -rf / ; echo")
    mgr.register(srv)
    assert await srv.connect() is False
    assert srv.health.state == "refused" and not srv.health.retry_due()


async def test_health_is_in_the_admin_list(mgr, monkeypatch):
    from agents.core.routers import mcp as mcp_router

    await _server(mgr, "docs")
    hung = await _server(mgr, "hung", "hang")
    hung.connect_timeout = 1.0
    await mgr.connect_all()
    monkeypatch.setattr(mcp_router, "get_orch", lambda: SimpleNamespace(mcp=mgr))
    body = await mcp_router.admin_mcp_list()
    rows = {row["name"]: row for row in body["servers"]}
    assert rows["docs"]["health"]["state"] == "connected" and rows["docs"]["health"]["connected"]
    assert rows["hung"]["health"]["last_error"] == "connect_timeout"
    assert rows["hung"]["health"]["next_retry_in_s"] is not None
    assert rows["docs"]["resource_tools"] == ["list_resources", "read_resource", "list_prompts", "get_prompt"]
    assert rows["docs"]["sampling"]["mode"] == "off"
    assert body["sampling_budget"]["name"] == "mcp_sampling_tokens"


# ── H553: sampling ──────────────────────────────────────────────────────────


def _host(queue=None, *, answer="hello from nerva", budget=None, calls=None):
    calls = calls if calls is not None else []

    async def generator(**kw):
        calls.append(kw)
        return answer

    return MCPHost(approvals=lambda: queue, generator=generator,
                   budget=budget or SamplingBudget(daily_tokens=20_000)), calls


async def _sampling_server(mode: str, host: MCPHost, **sampling) -> tuple[MCPManager, MCPServer]:
    manager = MCPManager(host=host)
    srv = MCPServer("docs", command=_cmd("full"), trust="full", sampling={"mode": mode, **sampling})
    manager.register(srv)
    assert await srv.connect()
    return manager, srv


async def test_sampling_off_by_default_declares_nothing_and_refuses():
    host, calls = _host(ActionApprovalQueue())
    manager, srv = await _sampling_server("off", host)
    try:
        init = _reply(await srv.call_tool("client_caps"))
        assert "sampling" not in init["capabilities"]
        reply = _reply(await srv.call_tool("ask_sample"))
        assert reply["error"]["code"] == -1 and calls == []
    finally:
        await manager.close_all()


async def test_sampling_auto_answers_within_budget_and_charges_it():
    budget = SamplingBudget(daily_tokens=20_000)
    host, calls = _host(None, budget=budget)
    manager, srv = await _sampling_server("auto", host)
    try:
        init = _reply(await srv.call_tool("client_caps"))
        assert init["capabilities"]["sampling"] == {}
        assert "tools" not in init["capabilities"]["sampling"]
        reply = _reply(await srv.call_tool("ask_sample", {"prefs": {"intelligencePriority": 0.9}}))
        assert reply["result"]["content"]["text"] == "hello from nerva"
        assert reply["result"]["model"] == "nerva-capable"
        [call] = calls
        assert call["role"] == ROLE_CAPABLE and call["max_tokens"] == 50
        assert "third-party MCP server" in call["system"] and "User: Say hi" in call["prompt"]
        assert 0 < budget.status()["used"] < 20_000
        assert srv.health.counters["sampling_answered"] == 1
    finally:
        await manager.close_all()


async def test_sampling_over_budget_is_refused_before_any_call():
    host, calls = _host(None, budget=SamplingBudget(daily_tokens=20))
    manager, srv = await _sampling_server("auto", host)
    try:
        reply = _reply(await srv.call_tool("ask_sample"))
        assert reply["error"]["message"] == "refused: budget_exceeded" and calls == []
    finally:
        await manager.close_all()


async def test_sampling_refused_under_estop(monkeypatch):
    host, calls = _host(None)
    manager, srv = await _sampling_server("auto", host)
    try:
        _estop_on(monkeypatch)
        reply = _reply(await srv.call_tool("ask_sample"))
        assert reply["error"]["message"] == "refused: estop_engaged" and calls == []
    finally:
        monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
        await manager.close_all()


async def test_sampling_refused_by_kill_switch():
    class Kill:
        def is_halted(self, scope="global"):
            return scope == "mcp:docs"

    host, calls = _host(None)
    manager, srv = await _sampling_server("auto", host)
    host.kill_switch = lambda: Kill()
    try:
        reply = _reply(await srv.call_tool("ask_sample"))
        assert reply["error"]["message"] == "refused: kill_switch_engaged" and calls == []
    finally:
        await manager.close_all()


async def test_sampling_with_tools_is_refused():
    host, calls = _host(None)
    manager, srv = await _sampling_server("auto", host)
    try:
        reply = _reply(await srv.call_tool("ask_sample", {"tools": True}))
        assert "tools" in reply["error"]["message"] and calls == []
    finally:
        await manager.close_all()


async def test_sampling_rate_limit_per_server():
    host, calls = _host(None)
    manager, srv = await _sampling_server("auto", host, max_rpm=1)
    try:
        assert "result" in _reply(await srv.call_tool("ask_sample"))
        second = _reply(await srv.call_tool("ask_sample"))
        assert second["error"]["message"].startswith("rate limit") and len(calls) == 1
    finally:
        await manager.close_all()


async def test_sampling_ask_waits_for_the_owners_approval():
    queue = ActionApprovalQueue()
    host, calls = _host(queue)
    manager, srv = await _sampling_server("ask", host)
    try:
        call = asyncio.create_task(srv.call_tool("ask_sample"))
        card = await _wait_pending(queue, "mcp.sampling")
        assert calls == [] and card["args"]["untrusted"] is True and card["agent"] == "mcp:docs"
        queue.decide(card["id"], True, by="owner")
        reply = _reply(await call)
        assert reply["result"]["content"]["text"] == "hello from nerva" and len(calls) == 1
        call = asyncio.create_task(srv.call_tool("ask_sample"))
        card = await _wait_pending(queue, "mcp.sampling")
        queue.decide(card["id"], False, by="owner")
        assert _reply(await call)["error"]["message"] == "not approved: rejected" and len(calls) == 1
    finally:
        await manager.close_all()


def test_model_preferences_map_onto_nerva_roles_not_server_model_names():
    cfg = SamplingConfig()
    assert map_model_preferences(None, cfg) == ROLE_FAST
    assert map_model_preferences({"intelligencePriority": 0.9, "costPriority": 0.2}, cfg) == ROLE_CAPABLE
    assert map_model_preferences({"intelligencePriority": 0.6, "speedPriority": 0.8}, cfg) == ROLE_FAST
    assert map_model_preferences({"hints": [{"name": "gpt-x-huge"}]}, cfg) == ROLE_FAST
    assert map_model_preferences({"hints": [{"name": "capable"}]}, cfg) == ROLE_CAPABLE
    narrow = SamplingConfig.from_config({"mode": "auto", "allowed_roles": ["fast"]})
    assert map_model_preferences({"intelligencePriority": 1.0}, narrow) == ROLE_FAST
    pinned = SamplingConfig.from_config({"mode": "auto", "role": "capable"})
    assert map_model_preferences({"speedPriority": 1.0}, pinned) == ROLE_CAPABLE
    assert SamplingConfig.from_config({"mode": "auto", "max_tokens_cap": 99999}).max_tokens_cap == 1024


# ── H553: elicitation ───────────────────────────────────────────────────────


async def _elicit_server(host: MCPHost, **elicitation) -> tuple[MCPManager, MCPServer]:
    manager = MCPManager(host=host)
    srv = MCPServer("docs", command=_cmd("full"), trust="full",
                    elicitation={"enabled": True, "max_per_minute": 30, **elicitation})
    manager.register(srv)
    assert await srv.connect()
    return manager, srv


async def test_elicitation_is_never_auto_answered():
    queue = ActionApprovalQueue()
    host, _ = _host(queue)
    manager, srv = await _elicit_server(host, timeout=1.0)
    try:
        init = _reply(await srv.call_tool("client_caps"))
        assert "elicitation" in init["capabilities"]
        reply = _reply(await srv.call_tool("ask_input"))
        assert reply["result"] == {"action": "cancel"}
        [item] = [i for i in queue._items.values() if i["tool"] == "mcp.elicitation"]
        assert item["status"] == "expired" and item["args"]["message"] == "What is your name?"
    finally:
        await manager.close_all()


async def test_elicitation_owner_answer_reject_and_approve():
    queue = ActionApprovalQueue()
    host, _ = _host(queue)
    manager, srv = await _elicit_server(host)
    try:
        call = asyncio.create_task(srv.call_tool("ask_input", {"required": True}))
        card = await _wait_pending(queue, "mcp.elicitation")
        assert card["args"]["fields"] == [{"name": "name", "type": "string"}]
        assert host.answer_elicitation(card["id"], {"name": 5})["error"] == "bad_type:name"
        assert host.answer_elicitation(card["id"], {"name": "Ada"})["ok"] is True
        assert _reply(await call)["result"] == {"action": "accept", "content": {"name": "Ada"}}

        call = asyncio.create_task(srv.call_tool("ask_input", {"required": True}))
        card = await _wait_pending(queue, "mcp.elicitation")
        queue.decide(card["id"], False, by="owner")
        assert _reply(await call)["result"] == {"action": "decline"}

        call = asyncio.create_task(srv.call_tool("ask_input", {"required": True}))
        card = await _wait_pending(queue, "mcp.elicitation")
        queue.decide(card["id"], True, by="owner")              # approve, no content given
        assert _reply(await call)["result"] == {"action": "decline"}

        call = asyncio.create_task(srv.call_tool("ask_input"))   # nothing required
        card = await _wait_pending(queue, "mcp.elicitation")
        queue.decide(card["id"], True, by="owner")
        assert _reply(await call)["result"] == {"action": "accept", "content": {}}
    finally:
        await manager.close_all()


async def test_url_mode_and_estop_decline_without_a_card(monkeypatch):
    queue = ActionApprovalQueue()
    host, _ = _host(queue)
    manager, srv = await _elicit_server(host)
    try:
        assert _reply(await srv.call_tool("ask_input", {"url": True}))["result"] == {"action": "decline"}
        _estop_on(monkeypatch)
        assert _reply(await srv.call_tool("ask_input"))["result"] == {"action": "decline"}
        assert not queue._items
    finally:
        monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
        await manager.close_all()


def test_elicitation_content_validation():
    schema = {"type": "object", "required": ["n"], "properties": {
        "n": {"type": "integer"}, "ok": {"type": "boolean"}, "c": {"type": "string", "enum": ["a", "b"]}}}
    assert validate_content(schema, {"n": 1, "ok": True, "c": "a"}) == ({"n": 1, "ok": True, "c": "a"}, None)
    assert validate_content(schema, {"ok": True})[1] == "missing_field:n"
    assert validate_content(schema, {"n": True})[1] == "bad_type:n"
    assert validate_content(schema, {"n": 1, "c": "z"})[1] == "not_in_enum:c"
    assert validate_content(schema, {"n": 1, "x": 1})[1] == "unknown_field:x"


def test_sampling_and_elicitation_settings_persist():
    manager = MCPManager()
    manager.load_from_config([{"name": "a", "command": "x", "trust": "read-only",
                               "sampling": {"mode": "ask", "max_rpm": 3}, "elicitation": False}])
    [row] = manager.to_config()
    assert row["sampling"]["mode"] == "ask" and row["sampling"]["max_rpm"] == 3
    assert row["elicitation"]["enabled"] is False
    assert manager.servers["a"].host is manager.host
    assert MCPServer("b", command="x").elicitation.enabled is False    # off unless the owner says
    assert os.environ.get("JARVIS_MCP_AUTOCONNECT") in (None, "", "0")
