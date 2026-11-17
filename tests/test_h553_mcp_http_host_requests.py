"""H553 — sampling and elicitation over Streamable HTTP, and a sampling budget that
survives a restart.

Owner's side: a remote (Streamable HTTP) MCP server that asks Nerva for a completion in the
middle of a tool call is answered exactly like a stdio one — only when the owner turned
sampling on for that server (so the capability is declared only then), inside the daily
budget, and the answer goes back to the server as a JSON-RPC response; a server that asks
more than twice in one call is refused for the rest. The day's sampling usage is kept on
disk, so restarting the hub does not hand servers a fresh allowance.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat

import httpx
import pytest

from agents.core.mcp.client import MCPManager, MCPServer
from agents.core.mcp.host_requests import MCPHost, SamplingBudget
from agents.core.mcp.http_transport import StreamableHttpTransport

URL = "http://127.0.0.1:9/mcp"


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    monkeypatch.setenv("JARVIS_MCP_HTTP_CLIENT", "1")
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)


class SamplingHub:
    """A Streamable HTTP server whose ``ask`` tool sends ``sampling/createMessage`` (*asks*
    times) inside the call's SSE stream and returns what the client answered."""

    def __init__(self, asks: int = 1):
        self.asks = asks
        self.init_params: dict = {}
        self.answers: list[dict] = []
        self._answered = asyncio.Event()

    def factory(self, target):
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content or b"{}")
        if "method" not in body and "id" in body:          # the client's answer to our request
            self.answers.append(body)
            if len(self.answers) >= self.asks:
                self._answered.set()
            return httpx.Response(202)
        if "id" not in body:
            return httpx.Response(202)
        method, msg_id = body["method"], body["id"]
        if method == "initialize":
            self.init_params = body["params"]
            return httpx.Response(200, headers={"mcp-session-id": "s1"}, json={
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}})
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [
                {"name": "ask", "inputSchema": {"type": "object"},
                 "annotations": {"readOnlyHint": True}}]}})
        if method == "tools/call":
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=self._stream(msg_id))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg_id, "result": {}})

    async def _stream(self, call_id):
        for n in range(self.asks):
            req = {"jsonrpc": "2.0", "id": f"srv-{n}", "method": "sampling/createMessage",
                   "params": {"messages": [{"role": "user",
                                            "content": {"type": "text", "text": "Say hi"}}],
                              "maxTokens": 40}}
            yield f"event: message\ndata: {json.dumps(req)}\n\n".encode()
        await asyncio.wait_for(self._answered.wait(), timeout=5)
        result = {"content": [{"type": "text", "text": json.dumps(self.answers)}]}
        yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': call_id, 'result': result})}\n\n".encode()


def _server(hub: SamplingHub, mode: str, host: MCPHost) -> tuple[MCPManager, MCPServer]:
    def factory(url, headers, *, name, **kw):
        return StreamableHttpTransport(url, headers, name=name, transport_factory=hub.factory, **kw)

    mgr = MCPManager(host=host)
    srv = MCPServer("remote", transport="streamable-http", url=URL, http_transport_factory=factory,
                    trust="full", sampling={"mode": mode})
    mgr.register(srv)
    return mgr, srv


def _host(budget=None, calls=None):
    calls = calls if calls is not None else []

    async def generator(**kw):
        calls.append(kw)
        return "hello from nerva"

    return MCPHost(approvals=lambda: None, generator=generator,
                   budget=budget or SamplingBudget(daily_tokens=20_000)), calls


async def test_http_sampling_is_declared_answered_and_charged():
    budget = SamplingBudget(daily_tokens=20_000)
    host, calls = _host(budget)
    hub = SamplingHub()
    mgr, srv = _server(hub, "auto", host)
    try:
        assert await srv.connect()
        assert hub.init_params["capabilities"] == {"sampling": {}}
        out = await srv.call_tool("ask", {})
        [answer] = json.loads(out["content"][0]["text"])
        assert answer["id"] == "srv-0"
        assert answer["result"]["content"]["text"] == "hello from nerva"
        assert len(calls) == 1 and calls[0]["max_tokens"] == 40
        assert 0 < budget.status()["used"] < 20_000
        assert srv.health.counters["sampling_answered"] == 1
    finally:
        await mgr.close_all()


async def test_http_sampling_off_declares_nothing_and_refuses():
    host, calls = _host()
    hub = SamplingHub()
    mgr, srv = _server(hub, "off", host)
    try:
        assert await srv.connect()
        assert hub.init_params["capabilities"] == {}
        out = await srv.call_tool("ask", {})
        [answer] = json.loads(out["content"][0]["text"])
        assert "error" in answer and calls == []
    finally:
        await mgr.close_all()


async def test_more_than_two_requests_in_one_call_are_refused():
    host, calls = _host()
    hub = SamplingHub(asks=3)
    mgr, srv = _server(hub, "auto", host)
    try:
        assert await srv.connect()
        out = await srv.call_tool("ask", {})
        answers = json.loads(out["content"][0]["text"])
        assert ["result" in a for a in answers] == [True, True, False]
        assert answers[2]["error"]["message"] == "too many requests in one call"
        assert len(calls) == 2
    finally:
        await mgr.close_all()


async def test_time_spent_answering_does_not_count_against_the_call():
    async def slow_generator(**kw):
        await asyncio.sleep(1.5)
        return "late but fine"

    host = MCPHost(approvals=lambda: None, generator=slow_generator,
                   budget=SamplingBudget(daily_tokens=20_000))
    hub = SamplingHub()
    mgr, srv = _server(hub, "auto", host)
    srv.options = {"timeout": 1.0}
    srv.request_timeout = 1.0
    try:
        assert await srv.connect()
        srv._http.timeout = 1.0
        out = await srv.call_tool("ask", {})
        [answer] = json.loads(out["content"][0]["text"])
        assert answer["result"]["content"]["text"] == "late but fine"
    finally:
        await mgr.close_all()


def test_sampling_budget_survives_a_restart(tmp_path):
    path = tmp_path / "mcp_sampling_budget.json"
    clock = lambda: 1_800_000_000.0  # noqa: E731 - a fixed day
    first = SamplingBudget(daily_tokens=1000, clock=clock, persist_path=path)
    assert first.reserve(300) is None
    first.settle(300, 250)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = SamplingBudget(daily_tokens=1000, clock=clock, persist_path=path)
    assert again.status()["used"] == 250
    assert again.reserve(800) == "budget_exceeded"
    tomorrow = SamplingBudget(daily_tokens=1000, clock=lambda: 1_800_000_000.0 + 86_400,
                              persist_path=path)
    assert tomorrow.status()["used"] == 0


def test_an_unreadable_budget_file_starts_the_day_spent(tmp_path):
    path = tmp_path / "mcp_sampling_budget.json"
    path.write_text("{not json")
    budget = SamplingBudget(daily_tokens=1000, persist_path=path)
    assert budget.reserve(1) == "budget_exceeded"
    assert SamplingBudget(daily_tokens=1000, persist_path=tmp_path / "absent.json").reserve(1) is None


async def test_http_elicitation_is_declared_only_with_an_approval_queue():
    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    for queue, declared in ((ActionApprovalQueue(), {"elicitation": {"form": {}}}), (None, {})):
        hub = SamplingHub()

        def factory(url, headers, *, name, hub=hub, **kw):
            return StreamableHttpTransport(url, headers, name=name, transport_factory=hub.factory, **kw)

        host = MCPHost(approvals=lambda q=queue: q, budget=SamplingBudget(daily_tokens=10))
        mgr = MCPManager(host=host)
        srv = MCPServer("remote", transport="streamable-http", url=URL,
                        http_transport_factory=factory, trust="full", elicitation=True)
        mgr.register(srv)
        try:
            assert await srv.connect()
            assert hub.init_params["capabilities"] == declared
        finally:
            await mgr.close_all()


def test_two_processes_sharing_the_budget_file_add_up(tmp_path):
    """Review m5: each save merges what another process booked since its last write."""
    path = tmp_path / "mcp_sampling_budget.json"
    clock = lambda: 1_800_000_000.0  # noqa: E731 - a fixed day
    a = SamplingBudget(daily_tokens=1000, clock=clock, persist_path=path)
    b = SamplingBudget(daily_tokens=1000, clock=clock, persist_path=path)
    assert a.reserve(300) is None
    assert b.reserve(200) is None
    assert json.loads(path.read_text())["used"] == 500
    assert a.reserve(100) is None
    assert json.loads(path.read_text())["used"] == 600
    assert SamplingBudget(daily_tokens=1000, clock=clock, persist_path=path).status()["used"] == 600


def test_the_budget_file_is_never_written_through_a_link(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    path = tmp_path / "mcp_sampling_budget.json"
    path.symlink_to(target)
    budget = SamplingBudget(daily_tokens=1000, persist_path=path)
    assert budget.reserve(1) == "budget_exceeded"          # an unreadable file starts spent
    assert target.read_text() == "keep"
