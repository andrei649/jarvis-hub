"""G6/G7 second adversarial review: per-result bounds without loop stalls, an idle
server cannot park memory in the hub, concurrent large reads are bounded, flapping
parks, MCP cards cannot hold a turn open for hours, and an answer that crosses a
cancellation reaches the server. Real stdio child (``tests/fixtures/mcp_fake_server.py``).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.mcp import client as client_mod
from agents.core.mcp import host_requests as host_mod
from agents.core.mcp import resources as res_mod
from agents.core.mcp.client import MCPManager, MCPServer
from agents.core.mcp.host_requests import ElicitationConfig, MCPHost
from agents.core.native_human_wait import runtime_human_wait_scope

FAKE = Path(__file__).resolve().parent / "fixtures" / "mcp_fake_server.py"


def _cmd(mode: str) -> str:
    return f"{sys.executable} {FAKE} {mode}"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr("agents.core.estop.is_engaged", lambda: False)
    monkeypatch.setattr(res_mod, "cache_dir", lambda server: tmp_path / "mcp_cache" / server)


@pytest.fixture
async def mgr():
    manager = MCPManager()
    yield manager
    await manager.close_all()


async def _server(manager, name="docs", mode="full", **kw):
    srv = MCPServer(name, command=_cmd(mode), trust="full", **kw)
    manager.register(srv)
    assert await manager.connect_server(name)
    return srv


class _Ticker:
    """The longest gap between 10 ms ticks of the event loop while it runs."""

    def __init__(self):
        self.worst = 0.0
        self._task = None

    async def _run(self):
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            self.worst = max(self.worst, now - last - 0.01)
            last = now

    def __enter__(self):
        self._task = asyncio.get_running_loop().create_task(self._run())
        return self

    def __exit__(self, *exc):
        self._task.cancel()


def _text_chars(blocks) -> int:
    return sum(len(b.get("text", "")) for b in blocks if isinstance(b, dict))


# ── MAJOR-1: one result is bounded, and bounding it does not stall the loop ──


async def test_many_large_blocks_are_capped_without_stalling_the_loop(mgr):
    await _server(mgr)
    await res_mod.warm_cleaner()
    with _Ticker() as ticker:
        out = await mgr.call_tool("read_resource", {"uri": "blocks:120"}, server="docs")
    assert len(out["contents"]) == res_mod.MAX_RESULT_BLOCKS and out["blocks_omitted"] == 20
    assert _text_chars(out["contents"]) <= res_mod.MAX_RESULT_TEXT_CHARS + 200
    assert out["text_truncated"] is True
    # 0.4 s: the regression this guards is an 8 s stall; parallel CI load adds ~0.1-0.2 s.
    assert ticker.worst < 0.4, f"event loop stalled {ticker.worst:.3f}s"


async def test_a_sixty_megabyte_reply_is_bounded(mgr):
    await _server(mgr)
    out = await mgr.call_tool("read_resource", {"uri": "blocks:600"}, server="docs")
    assert len(out["contents"]) == 100 and out["blocks_omitted"] == 500
    assert _text_chars(out["contents"]) <= res_mod.MAX_RESULT_TEXT_CHARS + 200


async def test_tool_call_results_are_bounded_too(mgr):
    await _server(mgr)
    with _Ticker() as ticker:
        out = await mgr.call_tool("blocks", {"n": 120, "rows": 2500}, server="docs")
    assert len(out["content"]) == 100 and out["blocks_omitted"] == 20
    assert _text_chars(out["content"]) <= res_mod.MAX_RESULT_TEXT_CHARS + 200
    assert str(out["structuredContent"]).startswith("[structuredContent omitted")
    # 0.4 s: the regression this guards is an 8 s stall; parallel CI load adds ~0.1-0.2 s.
    assert ticker.worst < 0.4, f"event loop stalled {ticker.worst:.3f}s"


def test_cleaning_is_one_fast_pass_over_multiline_text():
    res_mod._drop_pattern()
    text = ("a line ​ with \x1b[2J noise\n" * 70_000)
    started = time.monotonic()
    cleaned = res_mod.clean_text(text)
    assert time.monotonic() - started < 0.5
    assert "​" not in cleaned and "\x1b" not in cleaned and cleaned.count("\n") == 70_000


# ── MINOR-1: an idle server cannot park memory; big reads are bounded hub-wide ──


async def test_an_idle_flood_is_bounded_and_drops_the_server(mgr):
    srv = await _server(mgr, mode="idleflood")
    await asyncio.sleep(2.0)
    buffered = len(srv._proc.stdout._buffer)
    assert buffered <= 2 * client_mod.STDIO_IDLE_LINE_LIMIT + 256 * 1024
    out = await mgr.call_tool("echo", {}, server="docs")
    assert out["error"]["message"] == "unsolicited_output" and not srv.is_connected()


async def test_large_content_reads_are_bounded_across_servers(mgr, monkeypatch):
    active = {"now": 0, "most": 0}
    real = client_mod._content_gate

    class Counting:
        def __init__(self, gate):
            self.gate = gate

        async def __aenter__(self):
            await self.gate.acquire()
            active["now"] += 1
            active["most"] = max(active["most"], active["now"])

        async def __aexit__(self, *exc):
            active["now"] -= 1
            self.gate.release()

    monkeypatch.setattr(client_mod, "_content_gate", lambda: Counting(real()))
    servers = [await _server(mgr, name=f"s{i}") for i in range(4)]
    outs = await asyncio.gather(*(mgr.call_tool("read_resource", {"uri": "big:2000000"}, server=s.name)
                                  for s in servers))
    assert all(o["contents"][0]["bytes"] == 2_000_000 for o in outs)
    assert active["most"] == client_mod.CONTENT_READS_AT_ONCE


# ── MINOR-3: MCP cards cannot hold a turn open for hours ────────────────────


async def test_the_turn_card_allowance_is_capped():
    queue = ActionApprovalQueue()
    manager = MCPManager(host=MCPHost(approvals=lambda: queue))
    srv = MCPServer("docs", command=_cmd("full"), trust="full",
                    elicitation={"enabled": True, "max_per_minute": 30})
    manager.register(srv)
    try:
        await manager.connect_server("docs")
        with runtime_human_wait_scope() as scope:
            scope._mcp_card_seconds = host_mod.TURN_CARD_WAIT_SECONDS
            out = json.loads((await srv.call_tool("ask_input"))["content"][0]["text"])
        assert out["result"] == {"action": "decline"} and queue.list() == []
        with runtime_human_wait_scope() as scope:
            scope._mcp_card_seconds = host_mod.TURN_CARD_WAIT_SECONDS - 5
            call = asyncio.create_task(srv.call_tool("ask_input"))
            started = time.monotonic()
            out = json.loads((await call)["content"][0]["text"])
        assert out["result"] == {"action": "cancel"} and 4 <= time.monotonic() - started < 9
    finally:
        await manager.close_all()


async def test_open_cards_count_against_the_rate():
    queue = ActionApprovalQueue()
    host = MCPHost(approvals=lambda: queue)
    host.elicit_limiter.window = 0.01
    fake = SimpleNamespace(name="docs", health=None,
                           elicitation=ElicitationConfig(enabled=True, max_per_minute=1))
    params = {"message": "hi", "requestedSchema": {"type": "object", "properties": {}}}
    first = asyncio.create_task(host.handle(fake, "elicitation/create", params))
    while not queue.list("pending"):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)                            # the per-minute window has passed
    second = await host.handle(fake, "elicitation/create", params)
    assert second["result"] == {"action": "decline"} and len(queue.list()) == 1
    queue.decide(queue.list("pending")[0]["id"], False, by="owner")
    assert (await first)["result"] == {"action": "decline"}


# ── NIT: an answer that crosses a cancellation is what the server gets ──────


async def test_an_answer_crossing_a_cancellation_reaches_the_server():
    queue = ActionApprovalQueue()
    host = MCPHost(approvals=lambda: queue)
    manager = MCPManager(host=host)
    srv = MCPServer("docs", command=_cmd("full"), trust="full",
                    elicitation={"enabled": True, "max_per_minute": 30})
    manager.register(srv)
    try:
        await manager.connect_server("docs")
        call = asyncio.create_task(srv.call_tool("ask_input"))
        while not queue.list("pending"):
            await asyncio.sleep(0.01)
        card = queue.list("pending")[0]
        assert host.answer_elicitation(card["id"], {"name": "owner"})["ok"]
        call.cancel()                                     # before the waiter resumes
        with pytest.raises(asyncio.CancelledError):
            await call
        got = json.loads((await srv.call_tool("last_elicit"))["content"][0]["text"])
        assert got["result"] == {"action": "accept", "content": {"name": "owner"}}
        assert host.answer_elicitation(card["id"], {"name": "x"})["error"] == "already_answered"
    finally:
        await manager.close_all()


def test_servers_whose_names_sanitise_alike_get_distinct_cache_folders(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr("agents.core.paths.data_path", lambda *parts: tmp_path.joinpath(*parts))
    assert res_mod.cache_dir("a/b") != res_mod.cache_dir("a_b")
    assert res_mod.cache_dir("a/b").parent.name == "mcp_cache"


def test_closed_cards_are_trimmed():
    host = MCPHost()
    for i in range(700):
        host._remember_closed(f"c{i}", "approved")
    assert len(host._closed) == 500 and "c699" in host._closed
