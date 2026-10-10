"""H441 — getting back into a conversation: a recap rendered locally, never by a model.

Resuming a session returned its last 20 raw turns and nothing else; there was no
/recap and the HUD showed nothing after a resume. Hermes replays the last exchanges on
resume and answers /recap from the transcript with no LLM call, tool calls collapsed to
a count. Now: a bounded renderer, the tools each reply called recorded on its turn,
the recap on the resume route, /recap in every channel, and the HUD showing it.
"""

from __future__ import annotations

import asyncio
import functools
import json
from types import SimpleNamespace

import pytest

from agents.core.memory import turn_tools
from agents.core.memory.conversation import ConversationMemory, Turn
from agents.core.memory.recap import DEFAULT_EXCHANGES, MAX_EXCHANGES, render_recap, tool_line


@pytest.fixture(autouse=True)
def _no_turn_open():
    """A test that opens a turn in the main context must not leak it into the next."""
    token = turn_tools._CURRENT.set(None)
    yield
    turn_tools._CURRENT.reset(token)


def _t(role, content, agent=None, tools=None):
    row = {"role": role, "content": content, "agent_id": agent}
    if tools is not None:
        row["tools"] = tools
    return row


def _conversation(n):
    turns = []
    for i in range(n):
        turns.append(_t("user", f"question {i}"))
        turns.append(_t("assistant", f"answer {i}", "jarvis"))
    return turns


# ── the renderer ─────────────────────────────────────────────────────────────────

def test_the_recap_shows_the_last_exchanges_and_says_how_many_there_are():
    recap = render_recap(_conversation(14))
    assert recap["shown"] == DEFAULT_EXCHANGES == 10 and recap["total"] == 14
    assert recap["exchanges"][0][0]["text"] == "question 4"
    assert recap["exchanges"][-1][1] == {"role": "assistant", "agent": "jarvis", "text": "answer 13",
                                         "tool_calls": 0, "tools": []}
    assert recap["text"].splitlines()[0] == "Previous conversation (the last 10 of 14 exchanges):"
    assert "● you: question 13" in recap["text"] and "◆ jarvis: answer 13" in recap["text"]
    short = render_recap(_conversation(2))
    assert short["text"].splitlines()[0] == "Previous conversation:" and short["shown"] == 2


def test_tool_calls_collapse_to_a_count_and_their_names():
    turns = [_t("user", "check the weather"),
             _t("assistant", "It is sunny.", "jarvis", tools=["web_search", "web_fetch", "web_search"])]
    recap = render_recap(turns)
    entry = recap["exchanges"][0][1]
    assert entry["tool_calls"] == 3 and entry["tools"] == ["web_search", "web_fetch"]
    assert "◆ jarvis: It is sunny.  [3 tool calls: web_search, web_fetch]" in recap["text"]
    assert tool_line(["terminal_run"]) == "[1 tool call: terminal_run]"
    assert tool_line([]) == ""
    many = tool_line([f"t{i}" for i in range(9)])
    assert many.startswith("[9 tool calls: t0, t1, t2, t3, t4, t5, …")


def test_each_turn_is_one_bounded_line_of_plain_text():
    long = "word " * 200
    recap = render_recap([_t("user", "a\n\nb\tc\x1b[31m‮evil"), _t("assistant", long, "jarvis")],
                         max_chars=50)
    user, reply = recap["exchanges"][0]
    assert user["text"] == "a b c[31mevil"
    assert len(reply["text"]) == 50 and reply["text"].endswith("…")
    assert "\n" not in reply["text"]


def test_bounds_and_odd_input():
    assert render_recap(_conversation(60), exchanges=500)["shown"] == MAX_EXCHANGES
    assert render_recap(_conversation(3), exchanges=0)["shown"] == 3        # 0 means the default
    empty = render_recap([])
    assert empty["shown"] == 0 and empty["text"] == "Nothing to recap yet: this conversation has no turns."
    assert render_recap(None)["total"] == 0
    odd = render_recap(["junk", _t("assistant", "a greeting first"), _t("user", "hi"),
                        _t("assistant", None), _t("assistant", "x", tools="not a list")])
    assert odd["total"] == 2 and odd["exchanges"][0][0]["agent"] == "" and "nerva" in odd["text"]
    assert odd["exchanges"][1][2]["tool_calls"] == 0
    # An owner turn never shows a tool line, even from a hand-edited snapshot.
    edited = render_recap([_t("user", "q", tools=["web_search"])])
    assert edited["exchanges"][0][0]["tool_calls"] == 0 and "tool call" not in edited["text"]


def test_the_renderer_is_pure_it_calls_no_model():
    from pathlib import Path

    import agents.core.memory.recap as recap_module

    source = Path(recap_module.__file__).read_text(encoding="utf-8")
    for banned in ("import httpx", "llm", "generate", "backend", "requests", "openai"):
        assert banned not in source.split('"""', 2)[2], banned


# ── the tools a turn called ──────────────────────────────────────────────────────

def test_turn_tools_collects_finished_calls_by_name_only():
    turn_tools.begin()
    turn_tools.note({"event": "tool_started", "tool": "ignored"})
    turn_tools.note({"event": "tool_result", "tool": "web_search", "args": "secret"})
    turn_tools.note({"event": "tool_failed", "tool": "terminal_run"})
    turn_tools.note({"event": "tool_result", "tool": ""})
    turn_tools.note("not an event")
    assert turn_tools.collected() == ["web_search", "terminal_run"]
    taken = turn_tools.collected()
    taken.append("mutated by a caller")
    turn_tools.note({"event": "tool_result", "tool": "later"})
    assert taken == ["web_search", "terminal_run", "mutated by a caller"]
    assert turn_tools.collected() == ["web_search", "terminal_run", "later"]
    turn_tools.begin()
    assert turn_tools.collected() == []


def test_concurrent_turns_never_mix_and_a_worker_thread_lands_in_its_turn():
    async def turn(name, n):
        turn_tools.begin()
        for _ in range(n):
            await asyncio.sleep(0)
            await asyncio.to_thread(turn_tools.note, {"event": "tool_result", "tool": name})
        return turn_tools.collected()

    async def both():
        return await asyncio.gather(turn("a", 3), turn("b", 2))

    assert asyncio.run(both()) == [["a", "a", "a"], ["b", "b"]]


def test_no_turn_open_notes_nothing():
    async def outside():
        turn_tools.note({"event": "tool_result", "tool": "x"})
        return turn_tools.collected()

    assert asyncio.run(outside()) == []


def test_the_agents_sink_notes_the_turn_and_still_records_the_trail():
    from agents.core.agent import Agent

    agent = Agent("jarvis", {"name": "Jarvis"})
    seen = []
    agent.tool_event_sink = seen.append
    turn_tools.begin()
    agent._tool_event_sink()({"event": "tool_result", "tool": "web_search"})
    assert seen == [{"event": "tool_result", "tool": "web_search"}]
    assert turn_tools.collected() == ["web_search"]


def test_a_turns_tools_are_stored_and_survive_a_reload(tmp_path, monkeypatch):
    from agents.core.memory import conversation, persistence

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path, raising=False)
    memory = ConversationMemory(persist=True)

    async def run():
        await memory.add_turn("s1", "user", "weather?")
        await memory.add_turn("s1", "assistant", "sunny", "jarvis", tools=["web_search", "web_fetch"])
        await memory.add_turn("s1", "assistant", "plain", "jarvis")
        return await memory.get_history("s1")

    history = asyncio.run(run())
    assert history[1]["tools"] == ["web_search", "web_fetch"] and "tools" not in history[2]
    again = ConversationMemory(persist=True)            # loads the newest session at start
    assert asyncio.run(again.get_history("s1"))[1]["tools"] == ["web_search", "web_fetch"]

    async def newer():
        await memory.add_turn("s2", "user", "later")
    asyncio.run(newer())
    third = ConversationMemory(persist=True)            # s2 is newest: s1 comes back by resume
    assert "s1" not in third.sessions
    assert asyncio.run(third.resume_session("s1")) is True
    assert asyncio.run(third.get_history("s1"))[1]["tools"] == ["web_search", "web_fetch"]


def test_a_snapshot_with_a_bad_tools_value_reads_as_none():
    assert Turn("assistant", "x", tools="web_search").tools == []
    assert Turn("assistant", "x", tools=[1, None, " web ", "", "a" * 100]).tools == ["web", "a" * 64]
    assert "tools" not in Turn("assistant", "x").to_dict()


def test_the_manager_passes_the_tools_down(tmp_path, monkeypatch):
    from agents.core.memory.manager import MemoryManager

    manager = MemoryManager.__new__(MemoryManager)
    calls = []

    class Conv:
        sessions = {}
        instances = {}

        async def add_turn(self, *args, **kwargs):
            calls.append((args, kwargs))

    manager.conversation = Conv()
    manager._lock = asyncio.Lock()
    manager.embed_turns = False
    manager._bind_history_instance = lambda sid: None
    asyncio.run(manager.add_turn("s", "assistant", "hi", "jarvis", tools=["x"]))
    asyncio.run(manager.add_turn("s", "assistant", "hi", "jarvis"))
    assert calls[0][1] == {"tools": ["x"]} and calls[1][1] == {}


# ── the resume route ─────────────────────────────────────────────────────────────

class _Memory:
    def __init__(self, turns):
        self.turns = turns

    async def resume_session(self, sid):
        return sid == "s-old"

    async def get_history(self, sid, last_n=None):
        rows = list(self.turns)
        return rows[-last_n:] if last_n else rows


class _NoModel:
    def __getattr__(self, name):
        raise AssertionError(f"a model was called: {name}")


def test_resume_answers_with_a_recap_and_calls_no_model(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    turns = _conversation(15)
    turns[-1]["tools"] = ["web_search"]
    from agents.core.checkpoint import CheckpointManager
    checkpoints = CheckpointManager(":memory:")
    checkpoints.initialize()
    orch = SimpleNamespace(memory=_Memory(turns), session_id="s-now", llm_router=_NoModel(),
                           backend=_NoModel(), checkpoints=checkpoints)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    got = TestClient(web.app).post("/sessions/resume", json={"session_id": "s-old"})
    assert got.status_code == 200
    body = got.json()
    assert body["session"] == "s-old" and orch.session_id == "s-old"
    assert len(body["turns"]) == 20 and body["turns"][-1]["content"] == "answer 14"
    assert body["recap"]["total"] == 15 and body["recap"]["shown"] == 10
    assert body["recap"]["exchanges"][-1][1]["tool_calls"] == 1
    assert "[1 tool call: web_search]" in body["recap"]["text"]
    missing = TestClient(web.app).post("/sessions/resume", json={"session_id": "s-gone"})
    assert missing.status_code == 404


# ── /recap ───────────────────────────────────────────────────────────────────────

def _cmd_orch(turns, session="s-1", shared=False):
    from agents.core.commands import build_default_registry

    return SimpleNamespace(memory=_Memory(turns), session_id=session, llm_router=_NoModel(),
                           commands=build_default_registry(), on_shared_session=lambda: shared)


@pytest.mark.asyncio
async def test_slash_recap_answers_in_any_channel_without_a_model():
    from agents.core.commands import Principal, build_default_registry

    guest = Principal(channel="telegram", sender="7", admin=False)
    turns = _conversation(3) + [_t("user", "/recap")]
    outcome = await build_default_registry().dispatch("/recap", orch=_cmd_orch(turns), principal=guest)
    assert outcome is not None
    reply = outcome.reply
    assert reply.splitlines()[0] == "Previous conversation:"
    assert "● you: question 2" in reply and "/recap" not in reply


@pytest.mark.asyncio
async def test_slash_recap_takes_a_count_and_says_when_there_is_nothing():
    from agents.core.commands import Principal, build_default_registry

    owner = Principal(channel="telegram", sender="1", admin=True)
    registry = build_default_registry()
    more = await registry.dispatch("/recap 12", orch=_cmd_orch(_conversation(20)), principal=owner)
    assert more.reply.splitlines()[0] == "Previous conversation (the last 12 of 20 exchanges):"
    bogus = await registry.dispatch("/recap lots", orch=_cmd_orch(_conversation(20)), principal=owner)
    assert "the last 10 of 20" in bogus.reply
    none = await registry.dispatch("/recap", orch=_cmd_orch([_t("user", "/recap")]), principal=owner)
    assert none.reply == "Nothing to recap yet: this conversation has no turns."
    no_memory = await registry.dispatch("/recap", orch=SimpleNamespace(session_id=None), principal=owner)
    assert no_memory.reply == "There is no conversation here to recap yet."
    listed = await registry.dispatch("/help", orch=_cmd_orch([]), principal=owner)
    assert "/recap" in listed.reply


# ── the orchestrator records the tools on the reply ──────────────────────────────

def test_the_post_llm_seam_stores_the_turns_tools():
    from agents.core.orchestrator import Orchestrator

    calls = []

    class Mem:
        async def add_turn(self, *args, **kwargs):
            calls.append((args, kwargs))

    orch = Orchestrator.__new__(Orchestrator)
    orch.memory = Mem()
    orch.session_id = "s-1"

    async def stop(*a, **k):
        raise RuntimeError("stop after the turn is stored")

    orch._maybe_checkpoint = stop

    async def run(tools):
        turn_tools.begin()
        for name in tools:
            turn_tools.note({"event": "tool_result", "tool": name})
        with pytest.raises(RuntimeError):
            await orch._complete_llm_turn(text="q", intent=None, plugin_data={}, responses={},
                                          synthesized="reply", responder_id="jarvis", route_name="r",
                                          channel="web", action_taken="", t_classify=0, t_route=0,
                                          t_plugin=0, t_synthesize=0)

    asyncio.run(run(["web_search", "web_fetch"]))
    asyncio.run(run([]))
    assert calls[0][1] == {"agent_id": "jarvis", "tools": ["web_search", "web_fetch"]}
    assert calls[1][1] == {"agent_id": "jarvis"}


# ── review round ─────────────────────────────────────────────────────────────────
#
# /recap read whatever session the turn landed on, and a turn with no session of its
# own (a widget visitor, a webhook, an MCP caller) lands on the owner's; a session
# loaded through the continuation path dropped its tools and the next turn erased them
# from disk; the /recap line stayed in when typed in capitals; a huge turn was cleaned
# whole before it was cut; a non-ASCII digit crashed the command.

@pytest.fixture
def hub(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "h441-admin")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "h441-admin")
    with TestClient(web.app) as client:
        yield client


_ADMIN = {"X-Admin-Token": "h441-admin"}
_SECRET = "OWNER-SECRET: the alarm code is 7731"


def test_a_widget_visitor_a_webhook_and_mcp_cannot_recap_the_owners_conversation(hub):
    from agents.core.app_state import get_orch

    orch = get_orch()
    hud = orch.session_id
    hub.portal.call(orch.memory.add_turn, hud, "user", _SECRET)
    hub.portal.call(functools.partial(orch.memory.add_turn, hud, "assistant", "Noted.", "jarvis",
                                      tools=["notes_write"]))

    widget = hub.post("/api/admin/widgets", json={}, headers=_ADMIN).json()
    token = widget.get("token") or widget.get("widget", {}).get("token")
    visitor = hub.post(f"/api/widget/{token}/message", json={"message": "/recap 50"}).json()["reply"]
    assert "7731" not in visitor and "notes_write" not in visitor and "owner" in visitor

    hook = hub.post("/api/webhooks", json={"target": "jarvis"}, headers=_ADMIN).json()
    delivery = hub.post(f"/api/webhooks/{hook['id']}", headers={"X-Webhook-Token": hook["token"]},
                        content=json.dumps({"text": "/recap 50"})).json()
    assert "owner" in delivery["response"] and "7731" not in json.dumps(delivery)

    mcp = hub.portal.call(orch.handle_input, "/recap 50", "mcp")
    assert "7731" not in mcp and "owner" in mcp

    owner = hub.post("/chat", json={"message": "/recap 50"}, headers=_ADMIN).json()["reply"]
    assert f"● you: {_SECRET}" in owner and "◆ jarvis: Noted.  [1 tool call: notes_write]" in owner


@pytest.mark.asyncio
async def test_a_guest_on_the_shared_session_is_refused_before_anything_is_read():
    from agents.core.commands import Principal, build_default_registry

    class _Unread:
        async def get_history(self, *_a, **_k):
            raise AssertionError("the shared session was read for a guest")

    registry = build_default_registry()
    guest = Principal(channel="widget", admin=False)
    shared = SimpleNamespace(memory=_Unread(), session_id="hud", on_shared_session=lambda: True)
    refused = await registry.dispatch("/recap", orch=shared, principal=guest)
    assert "owner" in refused.reply
    no_probe = SimpleNamespace(memory=_Unread(), session_id="hud")          # counts as shared
    assert "owner" in (await registry.dispatch("/recap", orch=no_probe, principal=guest)).reply
    # A guest in a chat of its own reads that chat, and the owner reads the shared one.
    own = await registry.dispatch("/recap", orch=_cmd_orch(_conversation(2)), principal=guest)
    assert "● you: question 1" in own.reply
    owner = Principal(channel="web", admin=True)
    hud = await registry.dispatch("/recap", orch=_cmd_orch(_conversation(2), shared=True), principal=owner)
    assert "● you: question 1" in hud.reply


@pytest.mark.asyncio
async def test_the_recap_line_is_left_out_whatever_its_case_and_an_odd_digit_is_the_default():
    from agents.core.commands import Principal, build_default_registry

    owner = Principal(channel="telegram", sender="1", admin=True)
    registry = build_default_registry()
    for line, shown in (("/Recap 2", 2), ("/RECAP 3", 3), ("/recap@nerva_bot 2", 2)):
        outcome = await registry.dispatch(line, orch=_cmd_orch(_conversation(5) + [_t("user", line)]),
                                          principal=owner)
        assert outcome.reply.splitlines()[0] == f"Previous conversation (the last {shown} of 5 exchanges):"
        assert line not in outcome.reply
    # Another command's line is a turn like any other.
    kept = await registry.dispatch("/recap", orch=_cmd_orch(_conversation(1) + [_t("user", "/recapitulate")]),
                                   principal=owner)
    assert "● you: /recapitulate" in kept.reply
    odd = await registry.dispatch("/recap ²", orch=_cmd_orch(_conversation(20)), principal=owner)
    assert odd.status == "answered" and "the last 10 of 20" in odd.reply


def test_a_huge_turn_is_cut_before_it_is_cleaned(monkeypatch):
    import unicodedata

    import agents.core.memory.recap as recap_module
    from agents.core.memory.recap import DEFAULT_TURN_CHARS

    calls = [0]

    def category(ch):
        calls[0] += 1
        return unicodedata.category(ch)

    monkeypatch.setattr(recap_module, "unicodedata", SimpleNamespace(category=category))
    recap = render_recap([_t("user", "x" * 5_000_000), _t("assistant", "short", "jarvis")])
    assert calls[0] <= 4 * DEFAULT_TURN_CHARS + len("short") + len("jarvis")
    assert recap["exchanges"][0][0]["text"] == "x" * (DEFAULT_TURN_CHARS - 1) + "…"
    # Cut on the way in, so a head that folds short still says it was cut.
    spaced = render_recap([_t("user", "a" + " " * 5_000 + "tail")])
    assert spaced["exchanges"][0][0]["text"] == "a…"
    assert render_recap([_t("user", "y" * 1000)])["exchanges"][0][0]["text"] == "y" * 279 + "…"


def _checkpoints(tmp_path):
    from agents.core.checkpoint import CheckpointManager

    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    return cp


@pytest.mark.asyncio
async def test_a_turns_tools_survive_an_explicit_session_load_and_the_next_turn(tmp_path, monkeypatch):
    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import prepare_session

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = _checkpoints(tmp_path)
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    sid = await memory.new_session("session_tools")
    await memory.add_turn(sid, "user", "weather?")
    await memory.add_turn(sid, "assistant", "sunny", "jarvis", tools=["web_search"])

    fresh = MemoryManager()                              # after a restart, another session newest
    fresh.set_checkpoint_manager(cp)
    fresh.conversation.sessions.pop(sid, None)
    await prepare_session(SimpleNamespace(memory=fresh, checkpoints=cp), sid)   # /chat with session_id
    assert (await fresh.get_history(sid))[1]["tools"] == ["web_search"]
    await fresh.add_turn(sid, "user", "and tomorrow?")
    assert json.loads((tmp_path / f"{sid}.json").read_text())["turns"][1]["tools"] == ["web_search"]
    cp.close()


@pytest.mark.asyncio
async def test_a_continued_session_carries_the_tools_in_its_seed(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import ContinuationStore, create_continuation, seed_json

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = _checkpoints(tmp_path)
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    sid = await memory.new_session("session_source")
    await memory.add_turn(sid, "user", "weather?")
    await memory.add_turn(sid, "assistant", "sunny", "jarvis", tools=["web_search", "web_fetch"])

    @asynccontextmanager
    async def lease(_sid):
        yield True

    orch = SimpleNamespace(memory=memory, checkpoints=cp, session_id="default", turn_lease=lease)
    child = (await create_continuation(orch, sid, "00000000-0000-4000-8000-000000000441"))["session_id"]
    assert ContinuationStore(cp).seed(child)[1]["tools"] == ["web_search", "web_fetch"]

    again = MemoryManager()                              # after a restart: the child is seed-only
    again.set_checkpoint_manager(cp)
    again.conversation.sessions.pop(child, None)
    assert await again.resume_session(child)             # POST /sessions/resume
    assert (await again.get_history(child))[1]["tools"] == ["web_search", "web_fetch"]
    await again.add_turn(child, "user", "and tomorrow?")
    stored = json.loads((tmp_path / f"{child}.json").read_text())["turns"]
    assert stored[1]["tools"] == ["web_search", "web_fetch"]
    cp.close()

    # The seed keeps names only, as a stored turn does; none is no key at all.
    turn = {"role": "assistant", "content": "x", "agent_id": None,
            "timestamp": "2026-09-01T10:00:00+00:00", "token_count": 0}
    assert "tools" not in seed_json([turn]) and "tools" not in seed_json([{**turn, "tools": []}])
    assert json.loads(seed_json([{**turn, "tools": [" web ", 3, ""]}]))[0]["tools"] == ["web"]
