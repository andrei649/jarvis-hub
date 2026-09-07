"""MCP transports — DRA-25 Streamable HTTP client + H10.5 stdio server loop.

Everything is hermetic: the HTTP side runs against an ``httpx.MockTransport``
injected through the SSRF-pinned ``PluginHTTPClient`` seam (so the resolve-
then-pin guard, session header echo and SSE decoding are all exercised without
a socket); the stdio side uses in-memory ``asyncio.StreamReader`` frames plus
one real ``os.pipe`` round-trip; the bridge script is imported from its path
and driven with a fake hub.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.mcp import http_transport as ht  # noqa: E402
from agents.core.mcp.client import (  # noqa: E402
    STDIO_ENV_BASELINE_FLAG,
    MCPManager,
    MCPServer,
    stdio_env_baseline,
)
from agents.core.mcp.http_transport import (  # noqa: E402
    HTTP_CLIENT_FLAG,
    MCPTransportError,
    StreamableHttpTransport,
    normalize_transport,
    parse_sse_events,
    validate_mcp_url,
)
from agents.core.mcp.server import (  # noqa: E402
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PARSE_ERROR,
    JarvisMCPServer,
    open_stdio_streams,
    run_stdio_loop,
)

_LOOPBACK = "http://127.0.0.1:9/mcp"


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeMCPHub:
    """A spec-shaped Streamable HTTP MCP server behind ``httpx.MockTransport``."""

    def __init__(self, *, sse_for_calls: bool = True, session: str | None = "sess-1",
                 forget_session_after: int | None = None):
        self.requests: list[httpx.Request] = []
        self.sse_for_calls = sse_for_calls
        self.session = session
        self.forget_session_after = forget_session_after
        self.deleted: list[str] = []

    def factory(self, target):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "DELETE":
            self.deleted.append(request.headers.get("mcp-session-id", ""))
            return httpx.Response(200)
        body = json.loads(request.content or b"{}")
        method = body.get("method")
        msg_id = body.get("id")
        if (self.forget_session_after is not None
                and len(self.requests) > self.forget_session_after
                and request.headers.get("mcp-session-id")):
            return httpx.Response(404)
        if "id" not in body:
            return httpx.Response(202)
        if method == "initialize":
            headers = {"content-type": "application/json"}
            if self.session:
                headers["mcp-session-id"] = self.session
            return httpx.Response(200, headers=headers, json={
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                           "serverInfo": {"name": "fake-hub", "version": "0"}},
            })
        if method == "tools/list":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": [{"name": "echo", "description": "Echo",
                                      "inputSchema": {"type": "object"}}]},
            })
        if method == "tools/call":
            result = {"content": [{"type": "text", "text": body["params"]["arguments"]["text"]}],
                      "isError": False}
            reply = {"jsonrpc": "2.0", "id": msg_id, "result": result}
            if not self.sse_for_calls:
                return httpx.Response(200, json=reply)
            stream = (
                ": keep-alive\n\n"
                "event: message\n"
                'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"p":1}}\n\n'
                "event: message\n"
                f"data: {json.dumps(reply)}\n\n"
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=stream.encode())
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg_id,
                                         "error": {"code": -32601, "message": "nope"}})


def _http_server(name: str, hub: FakeMCPHub, url: str = _LOOPBACK, headers=None,
                 resolver=None) -> MCPServer:
    def factory(url, headers, *, name):
        return StreamableHttpTransport(url, headers, name=name, transport_factory=hub.factory,
                                       resolver=resolver)
    return MCPServer(name, transport="streamable-http", url=url, headers=headers,
                     http_transport_factory=factory)


class CollectingWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        return None

    def frames(self) -> list:
        return [json.loads(line) for line in self.buf.decode().splitlines() if line.strip()]


def _reader(*lines: str) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data(line.encode() + b"\n")
    reader.feed_eof()
    return reader


def _rpc_server(calls=None) -> JarvisMCPServer:
    async def runner(agent_id, text):
        if calls is not None:
            calls.append((agent_id, text))
        return f"[{agent_id}] {text}"
    return JarvisMCPServer(runner, {"jarvis": "Prime"})


# ── Streamable HTTP: flag gate + contract ────────────────────────────────────

async def test_http_transport_refused_without_flag(monkeypatch):
    monkeypatch.delenv(HTTP_CLIENT_FLAG, raising=False)
    hub = FakeMCPHub()
    srv = _http_server("gated", hub)
    assert await srv.connect() is False
    assert srv.last_error == f"transport_disabled:{HTTP_CLIENT_FLAG}"
    assert hub.requests == []  # not one byte left the process
    # Flag off → the historical stdio-only contract is the one evaluated.
    blocked = srv._tool_call_blocked("echo", {})
    assert blocked is not None and blocked["error"] == "value_not_allowed:transport"


async def test_contract_admits_http_only_while_flag_set(monkeypatch):
    from agents.core.mcp.client import (
        MCP_TOOL_CALL_CONTRACT,
        MCP_TOOL_CALL_CONTRACT_HTTP,
        active_tool_call_contract,
    )
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    assert active_tool_call_contract() is MCP_TOOL_CALL_CONTRACT_HTTP
    srv = _http_server("armed", FakeMCPHub())
    assert srv._tool_call_blocked("echo", {"text": "x"}) is None
    # The widened contract itself still re-checks the flag per call.
    monkeypatch.delenv(HTTP_CLIENT_FLAG)
    payload = {"kind": "mcp.tool_call", "server": "armed", "tool": "echo",
               "transport": "streamable-http", "args_keys": ["text"]}
    assert MCP_TOOL_CALL_CONTRACT_HTTP.evaluate(payload).reason == "transport_disabled"
    # Unsetting the flag revokes a persisted server at the next call — via the
    # historical contract, which is what every call sees again.
    assert active_tool_call_contract() is MCP_TOOL_CALL_CONTRACT
    assert srv._tool_call_blocked("echo", {"text": "x"})["error"] == "value_not_allowed:transport"
    # The deprecated pair stays refused by name regardless of the flag.
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    legacy = MCPServer("legacy", transport="sse", url=_LOOPBACK)
    assert legacy._tool_call_blocked("echo", {})["error"]
    assert await legacy.connect() is False
    assert legacy.last_error == "unsupported_transport:sse"


# ── Streamable HTTP: handshake, session, SSE, tool call ──────────────────────

async def test_http_initialize_tools_list_and_call_roundtrip(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    hub = FakeMCPHub()
    srv = _http_server("hub", hub, headers={"Authorization": "Bearer t0k",
                                             "Mcp-Session-Id": "forged"})
    assert await srv.connect() is True
    assert srv.is_connected() is True
    assert srv.last_error is None
    assert [t.name for t in srv.tools] == ["echo"]

    methods = [json.loads(r.content)["method"] for r in hub.requests]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    first, notified, listed = hub.requests
    assert first.headers["accept"] == "application/json, text/event-stream"
    assert first.headers["content-type"] == "application/json"
    assert first.headers["authorization"] == "Bearer t0k"
    assert "mcp-session-id" not in first.headers          # forged header dropped
    assert first.headers["host"] == "127.0.0.1:9"          # SSRF-pinned dial
    assert json.loads(first.content)["params"]["clientInfo"]["name"] == "nerva-hub"
    # Session + negotiated version echoed on every later call.
    assert notified.headers["mcp-session-id"] == "sess-1"
    assert listed.headers["mcp-session-id"] == "sess-1"
    assert listed.headers["mcp-protocol-version"] == "2025-03-26"
    assert "id" not in json.loads(notified.content)

    result = await srv.call_tool("echo", {"text": "hello"})
    assert result == {"content": [{"type": "text", "text": "hello"}], "isError": False}
    call = hub.requests[-1]
    assert json.loads(call.content)["params"] == {"name": "echo", "arguments": {"text": "hello"}}

    await srv.close()
    assert hub.deleted == ["sess-1"]
    assert srv.is_connected() is False
    assert await srv._send({"method": "ping"}) == {}


async def test_http_json_reply_and_stateless_server(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    hub = FakeMCPHub(sse_for_calls=False, session=None)
    srv = _http_server("stateless", hub)
    assert await srv.connect() is True
    assert srv._http.session_id is None
    assert (await srv.call_tool("echo", {"text": "json"}))["content"][0]["text"] == "json"
    await srv.close()
    assert hub.deleted == []  # no session → nothing to release


async def test_http_404_drops_session_and_reports_failure(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    hub = FakeMCPHub(forget_session_after=3)
    srv = _http_server("forgetful", hub)
    assert await srv.connect() is True
    assert srv._http.session_id == "sess-1"
    resp = await srv.call_tool("echo", {"text": "gone"})
    assert resp == {}
    assert srv._http.session_id is None
    assert srv.is_connected() is False


def test_sse_parser_joins_multiline_data_and_skips_comments():
    text = (
        ": hello\n"
        "event: message\n"
        'data: {"a":\n'
        'data:  1}\n'
        "\n"
        "data: not json\n\n"
        'data: {"b": 2}'
    )
    assert parse_sse_events(text) == [{"a": 1}, {"b": 2}]


# ── Streamable HTTP: SSRF guard is the same one plugins get ──────────────────

async def test_http_metadata_host_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    hub = FakeMCPHub()
    srv = _http_server("meta", hub, url="http://169.254.169.254/latest/mcp")
    assert await srv.connect() is False
    assert srv.last_error == "egress_blocked"
    assert hub.requests == []


async def test_http_public_name_resolving_private_is_pinned_and_refused(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    hub = FakeMCPHub()

    def rebinding(host, *, mode):
        assert mode == "public"
        return ["10.0.0.5"], None

    srv = _http_server("rebind", hub, url="http://mcp.example/mcp", resolver=rebinding)
    assert await srv.connect() is False
    assert srv.last_error == "egress_blocked"
    assert hub.requests == []

    def public(host, *, mode):
        return ["93.184.216.34"], None

    ok = _http_server("public", hub, url="http://mcp.example/mcp", resolver=public)
    assert await ok.connect() is True
    assert hub.requests[0].headers["host"] == "mcp.example"
    assert hub.requests[0].url.host == "93.184.216.34"


def test_url_and_header_validation():
    assert validate_mcp_url("") == "bad_url:empty"
    assert validate_mcp_url("ftp://x/mcp") == "bad_url:scheme"
    assert validate_mcp_url("http://user:pw@127.0.0.1/mcp") == "bad_url:credentials_in_url"
    assert validate_mcp_url("http://127.0.0.1/m cp") == "bad_url:control_chars"
    assert validate_mcp_url(_LOOPBACK) is None
    with pytest.raises(MCPTransportError) as exc:
        StreamableHttpTransport("ftp://127.0.0.1/mcp")
    assert exc.value.reason == "bad_url:scheme"
    with pytest.raises(MCPTransportError) as exc:
        StreamableHttpTransport(_LOOPBACK, {"X-Evil": "a\r\nInjected: b"})
    assert exc.value.reason == "bad_header"
    srv = MCPServer("bad", transport="http", url="not a url", http_transport_factory=None)
    assert srv.transport == "streamable-http"


async def test_bad_url_refused_with_reason(monkeypatch):
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    srv = MCPServer("bad", transport="streamable-http", url="mcp://x")
    assert await srv.connect() is False
    assert srv.last_error == "bad_url:scheme"


def test_transport_normalisation_and_config_roundtrip():
    assert normalize_transport(" HTTP ") == "streamable-http"
    assert normalize_transport("streamable_http") == "streamable-http"
    assert normalize_transport(None) == "stdio"
    assert normalize_transport("SSE") == "sse"
    mgr = MCPManager()
    mgr.load_from_config([
        {"name": "a", "transport": "http", "url": _LOOPBACK, "headers": {"X-T": "1"}},
        {"name": "b", "transport": "stdio", "command": "run-b"},
    ])
    assert mgr.servers["a"].transport == "streamable-http"
    assert mgr.servers["a"].headers == {"X-T": "1"}
    exported = {row["name"]: row for row in mgr.to_config()}
    assert exported["a"]["transport"] == "streamable-http"
    assert "headers" not in exported["a"]  # bearer tokens are never persisted


# ── stdio env baseline ───────────────────────────────────────────────────────

def test_stdio_env_baseline_strips_secrets_keeps_plumbing():
    environ = {
        "PATH": "/usr/bin", "HOME": "/home/u", "LANG": "C.UTF-8", "TMPDIR": "/tmp",
        "OPENAI_API_KEY": "sk-leak", "JARVIS_ADMIN_TOKEN": "adm", "ANTHROPIC_API_KEY": "k",
        "HTTPS_PROXY": "http://u:p@proxy", "JARVIS_HOME": "/data", "DB_PASSWORD": "pw",
        "Path": "C:\\Windows",  # case-insensitive match, original spelling kept
    }
    env = stdio_env_baseline(environ, {"WORLDVIEW_MCP_SECRET": "shared"})
    assert env == {
        "PATH": "/usr/bin", "HOME": "/home/u", "LANG": "C.UTF-8", "TMPDIR": "/tmp",
        "Path": "C:\\Windows", "WORLDVIEW_MCP_SECRET": "shared",
    }


class _FakeStdin:
    def is_closing(self):
        return False

    def write(self, data):
        pass

    async def drain(self):
        pass


class _FakeStdout:
    async def readline(self):
        return b'{"jsonrpc":"2.0","id":1,"result":{}}\n'


class _FakeProc:
    def __init__(self):
        self.stdin, self.stdout, self.stderr, self.returncode = _FakeStdin(), _FakeStdout(), None, None


async def test_stdio_subprocess_env_baseline_under_flag(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(kwargs)
        return _FakeProc()

    monkeypatch.setattr("agents.core.mcp.client.asyncio.create_subprocess_exec", fake_exec)
    # Flag off (default): historical behaviour — inherit everything.
    monkeypatch.delenv(STDIO_ENV_BASELINE_FLAG, raising=False)
    await MCPServer("plain", transport="stdio", command="run-x").connect()
    assert calls[-1]["env"] is None
    await MCPServer("ovr", transport="stdio", command="run-x", env={"K": "v"}).connect()
    assert calls[-1]["env"]["OPENAI_API_KEY"] == "sk-leak" and calls[-1]["env"]["K"] == "v"
    # Flag on: baseline + overrides only.
    monkeypatch.setenv(STDIO_ENV_BASELINE_FLAG, "1")
    await MCPServer("strict", transport="stdio", command="run-x", env={"K": "v"}).connect()
    env = calls[-1]["env"]
    assert "OPENAI_API_KEY" not in env
    assert env["PATH"] == "/usr/bin" and env["K"] == "v"


# ── stdio server loop ────────────────────────────────────────────────────────

async def test_stdio_loop_roundtrip_in_memory():
    calls = []
    server = _rpc_server(calls)
    reader = _reader(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "",
        json.dumps({"jsonrpc": "2.0", "id": "two", "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "ask_jarvis", "arguments": {"text": "hi"}}}),
    )
    writer = CollectingWriter()
    handled = await server.serve_stdio(reader, writer)
    assert handled == 4
    frames = writer.frames()
    assert [f["id"] for f in frames] == [1, "two", 3]  # notification produced no frame
    assert frames[0]["result"]["serverInfo"]["name"] == "jarvis-hub"
    assert [t["name"] for t in frames[1]["result"]["tools"]] == ["ask_jarvis"]
    assert frames[2]["result"]["content"][0]["text"] == "[jarvis] hi"
    assert calls == [("jarvis", "hi")]
    # One frame per line, never a multi-line JSON dump.
    assert writer.buf.count(b"\n") == 3


async def test_stdio_loop_parse_error_batch_and_invalid_request():
    server = _rpc_server()
    reader = _reader(
        "{not json",
        "42",
        "[]",
        json.dumps([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            "junk",
        ]),
        json.dumps([{"jsonrpc": "2.0", "method": "notifications/initialized"}]),
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "nope"}),
    )
    writer = CollectingWriter()
    assert await server.serve_stdio(reader, writer) == 4
    frames = writer.frames()
    assert frames[0]["error"]["code"] == PARSE_ERROR and frames[0]["id"] is None
    assert frames[1]["error"]["code"] == INVALID_REQUEST
    assert frames[2]["error"]["code"] == INVALID_REQUEST  # empty batch
    batch = frames[3]
    assert isinstance(batch, list) and len(batch) == 2
    assert batch[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert batch[1]["error"]["code"] == INVALID_REQUEST
    # A batch of only notifications writes nothing; the unknown method is last.
    assert frames[4]["id"] == 9 and frames[4]["error"]["code"] == -32601
    assert len(frames) == 5


async def test_stdio_loop_handler_exception_is_opaque():
    async def boom(message):
        raise RuntimeError("secret stack detail /home/owner/.ssh")

    writer = CollectingWriter()
    assert await run_stdio_loop(boom, _reader('{"jsonrpc":"2.0","id":7,"method":"x"}'), writer) == 1
    frame = writer.frames()[0]
    assert frame["id"] == 7 and frame["error"]["code"] == INTERNAL_ERROR
    assert "RuntimeError" in frame["error"]["message"]
    assert "secret" not in json.dumps(frame) and ".ssh" not in json.dumps(frame)


async def test_stdio_loop_refuses_oversized_frame():
    reader = asyncio.StreamReader(limit=64)
    reader.feed_data(b'{"jsonrpc":"2.0","id":1,"method":"' + b"a" * 200 + b'"}\n')
    reader.feed_eof()
    writer = CollectingWriter()
    assert await run_stdio_loop(_rpc_server().handle, reader, writer) == 0
    assert writer.frames()[0]["error"]["code"] == INVALID_REQUEST


async def test_stdio_loop_identity_reaches_tools(monkeypatch):
    seen = {}

    def guard(agent_id, text, identity):
        seen["identity"] = identity
        return None

    server = JarvisMCPServer(lambda a, t: asyncio.sleep(0, result="ok"), {"jarvis": "P"},
                             agent_request_guard=guard)
    reader = _reader(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "ask_jarvis", "arguments": {"text": "t"}}}))
    await server.serve_stdio(reader, CollectingWriter(), identity="user-token")
    assert seen["identity"] == "user-token"


@pytest.mark.skipif(sys.platform == "win32", reason="event-loop pipe transports are POSIX-only")
async def test_stdio_loop_over_real_pipes():
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    stdin = os.fdopen(in_r, "rb", buffering=0)
    stdout = os.fdopen(out_w, "wb", buffering=0)
    reader, writer = await open_stdio_streams(stdin=stdin, stdout=stdout)
    assert isinstance(reader, asyncio.StreamReader)
    server = _rpc_server()
    task = asyncio.create_task(server.serve_stdio(reader, writer))
    os.write(in_w, b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    os.write(in_w, b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')
    os.close(in_w)
    assert await asyncio.wait_for(task, 10) == 2
    writer.close()
    out = await asyncio.to_thread(os.read, out_r, 65536)
    os.close(out_r)
    lines = [json.loads(line) for line in out.decode().splitlines()]
    assert [line["id"] for line in lines] == [1, 2]
    assert lines[1]["result"]["tools"][0]["name"] == "ask_jarvis"


# ── stdio bridge script ──────────────────────────────────────────────────────

def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "nerva_mcp_stdio", repo_root / "scripts" / "nerva_mcp_stdio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeTransport:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.requests, self.notes = [], []
        self.closed = False

    async def request(self, method, params):
        self.requests.append((method, params))
        if self.error:
            raise self.error
        return self.reply

    async def notify(self, method, params):
        self.notes.append((method, params))

    async def close(self):
        self.closed = True


async def test_bridge_forwarder_restamps_client_id_and_maps_failures():
    bridge = _load_bridge()
    fake = _FakeTransport(reply={"jsonrpc": "2.0", "id": 17, "result": {"tools": []}})
    forward = bridge.make_forwarder(fake)
    assert await forward({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert fake.notes == [("notifications/initialized", {})]
    out = await forward({"jsonrpc": "2.0", "id": "client-abc", "method": "tools/list"})
    assert out == {"jsonrpc": "2.0", "id": "client-abc", "result": {"tools": []}}
    assert fake.requests == [("tools/list", {})]
    dead = bridge.make_forwarder(_FakeTransport(reply={}))
    out = await dead({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert out["id"] == 2 and out["error"]["code"] == -32000
    refused = bridge.make_forwarder(_FakeTransport(error=MCPTransportError("egress_blocked", "x")))
    out = await refused({"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert out["error"]["message"] == "transport: egress_blocked"


def test_bridge_argument_helpers_and_bad_url_exit(monkeypatch):
    bridge = _load_bridge()
    assert bridge.rpc_url("http://127.0.0.1:8080/", "/api/mcp/server/rpc") == \
        "http://127.0.0.1:8080/api/mcp/server/rpc"
    assert bridge.auth_headers("") == {}
    assert bridge.auth_headers(" tok ") == {"X-User-Token": "tok"}
    assert bridge.auth_headers("tok", admin=True) == {"X-Admin-Token": "tok"}
    args = bridge.build_parser().parse_args([])
    assert args.hub_url == "http://127.0.0.1:8080" and args.token_env == "JARVIS_USER_TOKEN"
    monkeypatch.setenv("NERVA_HUB_URL", "http://10.0.0.7:8080")
    assert bridge.build_parser().parse_args([]).hub_url == "http://10.0.0.7:8080"
    assert bridge.main(["--hub-url", "ftp://127.0.0.1"]) == 2


async def test_bridge_end_to_end_against_fake_hub(monkeypatch):
    """stdin frames → SSRF-pinned HTTP → fake hub route → stdout frames, ids preserved."""
    bridge = _load_bridge()
    seen: list[httpx.Request] = []

    def hub_route(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(200, json={"ok": True})
        if body["method"] == "tools/list":
            result = {"tools": [{"name": "ask_jarvis", "inputSchema": {}}]}
        else:
            result = {"protocolVersion": "2025-11-25", "serverInfo": {"name": "jarvis-hub"}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    transport = StreamableHttpTransport(
        bridge.rpc_url("http://127.0.0.1:8080", bridge.DEFAULT_RPC_PATH),
        bridge.auth_headers("tok"), name="bridge-test",
        transport_factory=lambda target: httpx.MockTransport(hub_route),
    )
    reader = _reader(
        '{"jsonrpc":"2.0","id":"init-1","method":"initialize","params":{}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":5,"method":"tools/list"}',
    )
    writer = CollectingWriter()
    assert await bridge.serve(transport, reader, writer) == 3
    frames = writer.frames()
    assert [f["id"] for f in frames] == ["init-1", 5]
    assert frames[1]["result"]["tools"][0]["name"] == "ask_jarvis"
    assert all(r.headers["x-user-token"] == "tok" for r in seen)
    assert all(r.url.path == "/api/mcp/server/rpc" for r in seen)
    assert transport.session_id is None  # hub issues none; nothing to DELETE
    assert not any(r.method == "DELETE" for r in seen)


def test_bridge_never_takes_the_token_from_argv():
    source = (repo_root / "scripts" / "nerva_mcp_stdio.py").read_text(encoding="utf-8")
    assert "--token-env" in source
    assert '"--token"' not in source and "'--token'" not in source


# ── honesty guards ───────────────────────────────────────────────────────────

def test_http_flag_is_default_off_and_named(monkeypatch):
    monkeypatch.delenv(HTTP_CLIENT_FLAG, raising=False)
    assert ht.http_client_enabled() is False
    assert HTTP_CLIENT_FLAG == "JARVIS_MCP_HTTP_CLIENT"
    assert ht.transport_allowed("stdio") is True
    assert ht.transport_allowed("streamable-http") is False
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "true")
    assert ht.transport_allowed("http") is True
    assert ht.transport_allowed("sse") is False
