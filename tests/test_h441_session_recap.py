"""H441 — getting back into a conversation: a recap rendered locally, never by a model.

Resuming a session returned its last 20 raw turns and nothing else; there was no
/recap and the HUD showed nothing after a resume. Hermes replays the last exchanges on
resume and answers /recap from the transcript with no LLM call, tool calls collapsed to
a count. Now: a bounded renderer, the tools each reply called recorded on its turn,
the recap on the resume route, /recap in every channel, and the HUD showing it.
"""

from __future__ import annotations

import asyncio
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
    orch = SimpleNamespace(memory=_Memory(turns), session_id="s-now", llm_router=_NoModel(), backend=_NoModel())
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

def _cmd_orch(turns, session="s-1"):
    from agents.core.commands import build_default_registry

    return SimpleNamespace(memory=_Memory(turns), session_id=session, llm_router=_NoModel(),
                           commands=build_default_registry())


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
