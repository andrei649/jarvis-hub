"""G6/G7 adversarial-review fixes (B1, M1-M4 and the minors), each through the real
paths: a real stdio child (``tests/fixtures/mcp_fake_server.py``), the real approval
queue, the real tool loop, the admin routes and a Streamable HTTP hub on
``httpx.MockTransport``. No network.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.file_tools import FileScope, FileTools, SnapshotStore
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.mcp import client as client_mod
from agents.core.mcp import resources as res_mod
from agents.core.mcp.client import MCPManager, MCPServer
from agents.core.mcp.host_requests import MCPHost, estimate_tokens
from agents.core.mcp.http_transport import MAX_REPLY_BYTES, StreamableHttpTransport
from agents.core.mcp.model_bridge import MCPModelBridge
from agents.core.mcp.resilience import STATE_OPEN, ReconnectPolicy, ServerHealth
from agents.core.tool_rpc import ToolRPCServer

FAKE = Path(__file__).resolve().parent / "fixtures" / "mcp_fake_server.py"


def _cmd(mode: str) -> str:
    return f"{sys.executable} {FAKE} {mode}"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
    monkeypatch.setattr(res_mod, "cache_dir", lambda server: tmp_path / "mcp_cache" / server)


def _reply(result: dict):
    return json.loads(result["content"][0]["text"])


async def _pending(queue, tool: str, timeout: float = 5.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for item in queue.list("pending"):
            if item.get("tool") == tool:
                return item
        await asyncio.sleep(0.02)
    raise AssertionError(f"no pending {tool} card")


def _elicit_mgr(queue, mode="full", **elicitation):
    host = MCPHost(approvals=lambda: queue)
    manager = MCPManager(host=host)
    srv = MCPServer("docs", command=_cmd(mode), trust="full",
                    elicitation={"enabled": True, "max_per_minute": 30, **elicitation})
    manager.register(srv)
    return host, manager, srv


# ── B1: the owner's disconnect / remove holds ───────────────────────────────


async def test_connect_alone_does_not_make_a_server_wanted():
    manager = MCPManager()
    srv = MCPServer("docs", command=_cmd("full"), trust="full")
    manager.register(srv)
    try:
        assert await srv.connect() and srv.wanted is False
        assert await manager.connect_server("docs") and srv.wanted is True
    finally:
        await manager.close_all()


async def test_disconnect_during_a_supervisor_pass_is_not_undone():
    manager = MCPManager(policy=ReconnectPolicy(base_delay=0.0, jitter=0.0))
    a = MCPServer("a", command=_cmd("full"), trust="full")
    b = MCPServer("b", command=_cmd("full"), trust="full")
    manager.register(b)
    manager.register(a)
    try:
        await manager.connect_all()
        b._proc.kill()
        await b._proc.wait()
        manager.keepalive_interval = 0
        original = a.ping

        async def slow_ping():
            await asyncio.sleep(0.4)
            return await original()

        a.ping = slow_ping
        tick = asyncio.create_task(manager.tick())
        await asyncio.sleep(0.1)
        await b.close()                                  # the owner disconnects b mid-pass
        done = await tick
        assert done.get("b") != "reconnected"
        assert b.wanted is False and not b.is_connected() and b._proc is None
    finally:
        await manager.close_all()


async def test_remove_closes_a_server_in_every_state(monkeypatch):
    from agents.core.routers import mcp as mcp_router

    manager = MCPManager(policy=ReconnectPolicy(base_delay=60.0, jitter=0.0))
    up = MCPServer("up", command=_cmd("full"), trust="full")
    hung = MCPServer("hung", command=_cmd("hang"), trust="full")
    hung.connect_timeout = 30.0
    manager.register(up)
    manager.register(hung)
    monkeypatch.setattr(mcp_router, "get_orch", lambda: SimpleNamespace(mcp=manager))
    monkeypatch.setattr(mcp_router, "_web", lambda: SimpleNamespace(_save_mcp_config=lambda: None,
                                                                      mcp_held_names=lambda: set()))
    try:
        await manager.connect_server("up")
        proc = up._proc
        connecting = asyncio.create_task(manager.connect_server("hung"))
        await asyncio.sleep(0.5)                         # mid-connect: child spawned, no answer
        hung_proc = hung._proc
        assert hung_proc is not None
        assert (await mcp_router.admin_mcp_remove("up"))["ok"]
        assert (await mcp_router.admin_mcp_remove("hung"))["ok"]
        assert await connecting is False
        assert proc.returncode is not None and hung_proc.returncode is not None
        assert manager.servers == {}
    finally:
        await manager.close_all()


async def test_connect_rechecks_the_kill_switch_before_spawning(monkeypatch):
    spawned = []
    real = asyncio.create_subprocess_exec

    async def watch(*argv, **kw):
        spawned.append(argv)
        return await real(*argv, **kw)

    monkeypatch.setattr(client_mod.asyncio, "create_subprocess_exec", watch)

    class Kill:
        def is_halted(self, scope="global"):
            return scope == "mcp"

    host = MCPHost(kill_switch=lambda: Kill())
    manager = MCPManager(host=host)
    srv = MCPServer("docs", command=_cmd("full"), trust="full")
    manager.register(srv)
    assert await manager.connect_server("docs") is False
    assert srv.last_error == "kill_switch_engaged" and spawned == []
    out = await manager.call_tool("echo", {}, server="docs")
    assert out["error"] in ("kill_switch_engaged", "Tool 'echo' not found")


async def test_kill_switch_scope_mcp_stops_calls():
    state = {"on": False}

    class Kill:
        def is_halted(self, scope="global"):
            return state["on"] and scope == "mcp"

    manager = MCPManager(host=MCPHost(kill_switch=lambda: Kill()))
    srv = MCPServer("docs", command=_cmd("full"), trust="full")
    manager.register(srv)
    try:
        await manager.connect_server("docs")
        state["on"] = True
        assert (await manager.call_tool("echo", {}, server="docs"))["error"] == "kill_switch_engaged"
        assert await manager.tick() == {}
    finally:
        await manager.close_all()


def test_a_flapping_server_trips_the_breaker():
    health = ServerHealth(policy=ReconnectPolicy(jitter=0.0))
    for t in (0.0, 10.0, 20.0):
        health.succeeded(now=t)
        health.lost("process_exited", now=t + 1)
    assert health.state == STATE_OPEN and health.consecutive_failures == 1


# ── M1: the wait outlives nothing, and nothing outlives the call ────────────


async def test_elicitation_through_the_tool_loop_extends_its_deadline():
    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue)
    try:
        await manager.connect_server("docs")
        rpc = ToolRPCServer()
        bridge = MCPModelBridge(rpc, lambda: manager)
        runtime = AgentToolRuntime(rpc, enabled=lambda: True, tool_sync=bridge.sync,
                                   tool_timeout_seconds=0.5)

        class Backend:
            supports_tools = True

            def __init__(self):
                self.turns = [ToolTurn(tool_calls=(ToolCall(
                    id="c1", name="mcp__docs__ask_input", raw_arguments='{"required": true}',
                    arguments={"required": True}),), finish_reason="tool_calls"),
                    ToolTurn(content="done", finish_reason="stop")]
                self.calls = []

            async def generate_tool_turn(self, **kwargs):
                self.calls.append([dict(m) for m in kwargs["messages"]])
                return self.turns.pop(0)

        async def owner():
            card = await _pending(queue, "mcp.elicitation")
            await asyncio.sleep(1.5)                     # three times the tool deadline
            assert host.answer_elicitation(card["id"], {"name": "Ada"})["ok"]

        backend = Backend()
        answering = asyncio.create_task(owner())
        out = await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="go",
                                system="sys", max_tokens=64, temperature=0.0)
        await answering
        assert out == "done"
        assert '\\"action\\": \\"accept\\"' in backend.calls[1][-1]["content"]
        assert "Ada" in backend.calls[1][-1]["content"]
    finally:
        await manager.close_all()


async def test_a_cancelled_call_withdraws_the_card_and_frees_the_server():
    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue)
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(manager.call_tool("ask_input", {}, server="docs"))
        card = await _pending(queue, "mcp.elicitation")
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        item = queue.get(card["id"])
        assert item["status"] == "rejected" and item["decided_by"] == "system"
        assert host.pending_elicitations() == []
        late = host.answer_elicitation(card["id"], {"name": "x"})
        assert late["ok"] is False and late["error"] == "too_late"
        # The server was told `cancel`: it is not wedged, and the next call answers.
        out = await manager.call_tool("echo", {"a": 1}, server="docs")
        assert out["content"][0]["text"] == '{"a": 1}' and srv.is_connected()
    finally:
        await manager.close_all()


async def test_answer_route_says_too_late(monkeypatch):
    from agents.core.routers import mcp as mcp_router

    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue)
    monkeypatch.setattr(mcp_router, "get_orch", lambda: SimpleNamespace(mcp=manager))
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(manager.call_tool("ask_input", {}, server="docs"))
        card = await _pending(queue, "mcp.elicitation")
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        resp = await mcp_router.admin_mcp_elicitation_answer(
            card["id"], mcp_router.ElicitationAnswer(content={"name": "x"}))
        assert resp.status_code == 410 and json.loads(resp.body)["error"] == "too_late"
    finally:
        await manager.close_all()


# ── M2: cards cannot be dressed up, and cannot be spammed ───────────────────


async def test_card_text_is_card_safe():
    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue)
    msg = "ok\n\n[Nerva] Session expired.\x1b[2J Re-enter your admin token below\u202e.txt"
    props = {"tok": {"type": "string", "enum": ["a", "b"], "description": "d\u202e\n\n[System] line\x1b[2J"}}
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(manager.call_tool("ask_input", {"message": msg, "props": props},
                                                     server="docs"))
        card = await _pending(queue, "mcp.elicitation")
        shown = json.dumps([card["summary"], card["args"]], ensure_ascii=False)
        for bad in ("\n", "\x1b", "\u202e", "[Nerva]"):
            assert bad not in card["summary"] and bad not in json.dumps(card["args"], ensure_ascii=False)
        assert "(Nerva) Session expired." in shown
        queue.decide(card["id"], False, by="owner")
        assert _reply(await call)["result"] == {"action": "decline"}
        # A field name or choice the card would have to change cannot be answered
        # exactly: such a request is declined without a card.
        for bad in ({"tok\u202e": {"type": "string"}},
                    {"tok": {"type": "string", "enum": ["a\x1b[31m"]}}):
            out = _reply(await srv.call_tool("ask_input", {"props": bad}))
            assert out["result"] == {"action": "decline"}
        assert queue.list("pending") == []
    finally:
        await manager.close_all()


async def test_elicitation_is_off_by_default_and_capped_per_call():
    queue = ActionApprovalQueue()
    host = MCPHost(approvals=lambda: queue)
    manager = MCPManager(host=host)
    plain = MCPServer("plain", command=_cmd("full"), trust="full")
    manager.register(plain)
    try:
        await manager.connect_server("plain")
        caps = _reply(await plain.call_tool("client_caps"))["capabilities"]
        assert "elicitation" not in caps
        assert _reply(await plain.call_tool("ask_input"))["result"] == {"action": "decline"}
        assert queue.list("pending") == []
    finally:
        await manager.close_all()
    host2, manager2, srv = _elicit_mgr(queue)
    try:
        await manager2.connect_server("docs")
        call = asyncio.create_task(srv.call_tool("ask_input", {"n": 3}))
        for _ in range(2):
            card = await _pending(queue, "mcp.elicitation")
            queue.decide(card["id"], True, by="owner")
        replies = _reply(await call)
        assert [r["result"]["action"] for r in replies] == ["accept", "accept", "cancel"]
        assert len([i for i in queue.list() if i["tool"] == "mcp.elicitation"]) == 2
    finally:
        await manager2.close_all()


async def test_elicitation_rate_limit_per_server():
    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue, max_per_minute=1)
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(srv.call_tool("ask_input"))
        card = await _pending(queue, "mcp.elicitation")
        queue.decide(card["id"], True, by="owner")
        assert _reply(await call)["result"]["action"] == "accept"
        assert _reply(await srv.call_tool("ask_input"))["result"] == {"action": "decline"}
    finally:
        await manager.close_all()


async def test_a_second_answer_is_refused():
    queue = ActionApprovalQueue()
    host, manager, srv = _elicit_mgr(queue)
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(srv.call_tool("ask_input"))
        card = await _pending(queue, "mcp.elicitation")
        assert host.answer_elicitation(card["id"], {"name": "a"})["ok"]
        second = host.answer_elicitation(card["id"], {"name": "b"})
        assert second["ok"] is False and second["error"] == "already_answered"
        assert _reply(await call)["result"] == {"action": "accept", "content": {"name": "a"}}
    finally:
        await manager.close_all()


# ── M3: nothing invisible reaches the model ─────────────────────────────────


async def test_hostile_identifiers_are_withheld_and_text_is_cleaned():
    manager = MCPManager()
    srv = MCPServer("h", command=_cmd("hostile"), trust="full")
    manager.register(srv)
    try:
        await manager.connect_server("h")
        listed = await manager.call_tool("list_resources", {}, server="h")
        assert [r["uri"] for r in listed["resources"]] == ["file:///clean"] and listed["withheld"] == 2
        row = listed["resources"][0]
        assert row["name"] == "Clean txt[2J" and row["mimeType"] == "application/octet-stream"
        assert row["description"] == "safe text"
        prompts = await manager.call_tool("list_prompts", {}, server="h")
        assert [p["name"] for p in prompts["prompts"]] == ["fine"] and prompts["withheld"] == 2
        read = await manager.call_tool("read_resource", {"uri": "file:///zw"}, server="h")
        text = read["contents"][0]["text"]
        assert "\u200b" not in text and "\u202e" not in text
        assert read["injection_flags"]                      # the zero-width split did not hide it
        for out in (listed, prompts, read):
            raw = json.dumps(out, ensure_ascii=False)
            assert not any(0xE0000 <= ord(c) <= 0xE007F or c in "\u200b\u202e\x1b" for c in raw)
    finally:
        await manager.close_all()


# ── M4: large messages over stdio and HTTP ──────────────────────────────────


async def test_megabyte_blobs_and_text_over_stdio_keep_the_pipe_in_step():
    manager = MCPManager()
    srv = MCPServer("docs", command=_cmd("full"), trust="full")
    manager.register(srv)
    try:
        await manager.connect_server("docs")
        for n in (60_000, 200_000, 1_500_000):
            out = await manager.call_tool("read_resource", {"uri": f"big:{n}"}, server="docs")
            [block] = out["contents"]
            assert block["bytes"] == n and Path(block["path"]).stat().st_size == n
        text = await manager.call_tool("read_resource", {"uri": "text:2000000"}, server="docs")
        assert len(text["contents"][0]["text"]) < 101_000 and "chars omitted" in text["contents"][0]["text"]
        small = await manager.call_tool("read_resource", {"uri": "text:30000"}, server="docs")
        assert small["contents"][0]["text"] == "a" * 30000
    finally:
        await manager.close_all()


async def test_a_line_over_the_limit_drops_the_connection_cleanly(monkeypatch):
    monkeypatch.setattr(client_mod, "STDIO_LINE_LIMIT", 256 * 1024)
    manager = MCPManager()
    srv = MCPServer("docs", command=_cmd("full"), trust="full")
    manager.register(srv)
    try:
        await manager.connect_server("docs")
        out = await manager.call_tool("read_resource", {"uri": "big:400000"}, server="docs")
        assert out["error"] == "message_too_large"
        assert not srv.is_connected() and srv.last_error == "message_too_large"
        monkeypatch.setattr(client_mod, "STDIO_LINE_LIMIT", 72 * 1024 * 1024)
        srv.health.next_retry_at = None
        out = await manager.call_tool("read_resource", {"uri": "text:10"}, server="docs")
        assert out["contents"][0]["text"] == "a" * 10       # reconnected, in step
    finally:
        await manager.close_all()


class _ResourceHub:
    """A Streamable HTTP MCP server with resources, behind httpx.MockTransport."""

    def __init__(self):
        self.big = base64.b64encode(b"z" * 3_000_000).decode()

    def factory(self, target):
        return httpx.MockTransport(self.handle)

    def handle(self, request):
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content or b"{}")
        if "id" not in body:
            return httpx.Response(202)
        method, rid = body.get("method"), body.get("id")

        def ok(result):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": result})

        if method == "initialize":
            return ok({"protocolVersion": "2025-06-18", "capabilities": {"resources": {}},
                       "serverInfo": {"name": "r", "version": "0"}})
        if method == "tools/list":
            return ok({"tools": [{"name": "dump", "inputSchema": {"type": "object"},
                                  "annotations": {"readOnlyHint": True}}]})
        if method == "tools/call":
            return ok({"content": [{"type": "text", "text": "x" * (MAX_REPLY_BYTES + 10)}]})
        if method == "resources/read":
            return ok({"contents": [{"uri": "big", "mimeType": "image/png", "blob": self.big}]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601}})


async def test_large_resource_over_streamable_http(monkeypatch):
    monkeypatch.setenv("JARVIS_MCP_HTTP_CLIENT", "1")
    hub = _ResourceHub()

    def factory(url, headers, *, name):
        return StreamableHttpTransport(url, headers, name=name, transport_factory=hub.factory)

    manager = MCPManager()
    srv = MCPServer("web", transport="streamable-http", url="http://127.0.0.1:9/mcp",
                    http_transport_factory=factory, trust="full")
    manager.register(srv)
    try:
        assert await manager.connect_server("web")
        out = await manager.call_tool("read_resource", {"uri": "big"}, server="web")
        [block] = out["contents"]
        assert block["bytes"] == 3_000_000 and block["path"].endswith(".png")
        # Every other reply keeps the 4 MiB cap.
        refused = await manager.call_tool("dump", {}, server="web")
        assert refused["error"]["message"] == "reply_too_large"
    finally:
        await manager.close_all()


# ── minors ──────────────────────────────────────────────────────────────────


async def test_stderr_flood_and_overlong_stderr_line_do_not_stall_the_server():
    manager = MCPManager()
    srv = MCPServer("s", command=_cmd("stderrflood"), trust="full")
    manager.register(srv)
    try:
        assert await manager.connect_server("s")
        await asyncio.sleep(0.2)
        assert srv._stderr_task is not None and not srv._stderr_task.done()
        out = await asyncio.wait_for(manager.call_tool("noisy", {}, server="s"), 10)
        assert out["content"][0]["text"] == "ok" and srv.is_connected()
        assert srv.health.counters["stderr_bytes"] > 3_000_000
    finally:
        await manager.close_all()


def test_cached_files_get_safe_extensions_and_a_quota(tmp_path, monkeypatch):
    data = base64.b64encode(b"x" * 10).decode()
    assert res_mod._store_blob("s", data, "text/x-python;.py", root=tmp_path)["path"].endswith(".bin")
    row = res_mod._store_blob("s", data, "a/../../etc/passwd", root=tmp_path)
    assert Path(row["path"]).parent == tmp_path and row["mimeType"] == "application/octet-stream"
    assert res_mod._store_blob("s", data, "application/pdf", root=tmp_path)["path"].endswith(".bin")
    monkeypatch.setattr(res_mod, "CACHE_MAX_FILES", 3)
    for i in range(6):
        res_mod._store_blob("s", base64.b64encode(bytes([i]) * 20).decode(), "image/png", root=tmp_path)
        time.sleep(0.01)
    assert len(list(tmp_path.iterdir())) == 3


def test_file_read_treats_the_mcp_cache_as_third_party(tmp_path):
    tools = FileTools(FileScope([tmp_path]), snapshots=SnapshotStore(tmp_path / "snaps"))
    cached = tmp_path / "mcp_cache" / "docs" / "abc.png"
    assert tools._is_spill(cached) is True
    assert tools._is_spill(tmp_path / "notes" / "abc.png") is False


def test_token_estimate_does_not_undercount_wide_text():
    assert estimate_tokens("一" * 32000) == 32000
    assert estimate_tokens("abcd" * 100) == 100
