"""H428 — pre-turn recall with a triviality gate, a hard timeout and skip-while-stuck.

Hermes gates its memory prefetch on one anchored ``is_trivial_prompt`` (empty input,
a slash command, a bare acknowledgement — ``k8s``/``yolo`` deliberately not), bounds
every external prefetch at 8 s on a daemon thread, and skips a provider whose previous
prefetch is still running (the timed-out result itself is thrown away). Nerva's
``Orchestrator._recall_block`` paid an embedding plus a fused vector ⊕ graph query for
"ok" and awaited it with no bound. A slow backend stalled the turn and every recall
queued behind the memory lock without limit, and the search held the same lock that
saving a reply and every other session's turn need.

Nerva adds one thing Hermes does not do: a straggler that finishes cleanly leaves its
hits for a retry of the same question (never for another question, never across a
purge).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import unicodedata

import pytest

from agents.core import settings_db
from agents.core.memory.recall_gate import is_trivial_prompt


@pytest.mark.parametrize("text", [
    "", "   ", "/help", "/skill weather now", "/remind@nerva_bot every day at 9 | water",
    "ok", "OK!", "okay.", "k", "thanks :)", "Thank you.",
    "thx", "hi!", "hello", "hey", "lgtm", "cool", "nice", "great!!", "done???", "go ahead", "got it",
    "yes", "no.", "sure", "da", "Nu.", "mersi", "Mulțumesc!", "multumesc", "mulţumesc", "merci",
    "bine", "super 👍", "perfect", "salut", "gata", "👍", "ok 🙏", "...",
    # review round: NFD, a zero-width space, internal commas, a leading ¿, more Romanian acks
    unicodedata.normalize("NFD", "mulțumesc"), "ok\u200b", "ok, mersi", "mersi frumos", "¿ok?",
])
def test_trivial_prompts_skip_recall(text):
    assert is_trivial_prompt(text) is True


@pytest.mark.parametrize("text", [
    "k8s", "yolo", "note", "ok, and what about the dentist?", "thanks for the Q3 summary",
    "da, trimite raportul", "what did I say about the dentist", "hi, remind me what we decided",
    "okay so the invoice", "nope not that one either, the blue one", "o" * 50,
    # review round: a path is no command, and an emoji that asks something is a question
    "/etc/hosts has a new line, when did I add it and why?", "/tmp/x?", "🦷?", "📅❓",
])
def test_prompts_with_content_still_recall(text):
    assert is_trivial_prompt(text) is False


def test_the_timeout_setting_is_seeded_so_the_ui_can_change_it():
    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    row = rows[("memory", "recall_timeout_s")]
    assert row["kind"] == "number" and row["value"] == 8


class _Memory:
    """A recall backend whose latency and results the test controls."""

    def __init__(self, delay: float = 0.0, hits=()):
        self.delay = delay
        self.hits = list(hits)
        self.calls: list[str] = []

    async def recall(self, text, top_k=5, keyword=None):
        self.calls.append(text)
        await asyncio.sleep(self.delay)
        return list(self.hits)


def _stuck(orch):
    return list(getattr(orch, "_recall_state", None).stuck) if getattr(orch, "_recall_state", None) else []


def _release(orch):
    for task in _stuck(orch):
        task.cancel()


def _hit(text="the dentist is on Tuesday"):
    from agents.core.memory.fusion import FusedHit

    return FusedHit(id="mem-1", score=1.0, sources=["vector"], payload={"metadata": {"text": text}})


def _orch(memory, **settings):
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)  # bypass heavy __init__, as the other recall tests do
    orch._runtime_settings = {"memory.recall_enabled": True, "memory.recall_top_k": 5, **settings}
    orch.memory = memory
    return orch


async def test_a_trivial_prompt_never_reaches_the_backend():
    memory = _Memory(hits=[_hit()])
    orch = _orch(memory)
    assert await orch._recall_block("ok") == ""
    assert await orch._recall_block("/help") == ""
    assert memory.calls == []


async def test_a_real_question_still_recalls():
    memory = _Memory(hits=[_hit()])
    block = await _orch(memory)._recall_block("when is the dentist?")
    assert "Tuesday" in block
    assert memory.calls == ["when is the dentist?"]


async def test_a_hung_backend_cannot_stall_the_turn(caplog):
    memory = _Memory(delay=30)
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.2})
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="jarvis.orchestrator"):
        block = await orch._recall_block("what did I say about the dentist?")
    assert block == ""
    assert time.monotonic() - started < 1.0
    assert "recall timed out" in caplog.text
    _release(orch)


async def test_a_turn_skips_recall_while_the_timed_out_one_is_still_running(caplog):
    memory = _Memory(delay=30)
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await orch._recall_block("first question about the dentist")
    with caplog.at_level(logging.INFO, logger="jarvis.orchestrator"):
        assert await orch._recall_block("second question about taxes") == ""
    assert memory.calls == ["first question about the dentist"]  # no second round-trip queued
    assert "still running" in caplog.text
    _release(orch)


async def test_a_late_result_is_handed_to_a_retry_of_the_same_question():
    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    assert await orch._recall_block("when is the dentist?") == ""
    await asyncio.sleep(0.4)  # the straggler finishes in the background
    block = await orch._recall_block("when is the dentist?")
    assert "Tuesday" in block
    assert memory.calls == ["when is the dentist?"]  # served from the late result, no new query


async def test_a_late_result_is_not_injected_into_an_unrelated_turn():
    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await orch._recall_block("when is the dentist?")
    await asyncio.sleep(0.4)
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("what is the weather tomorrow?") == ""
    assert memory.calls == ["when is the dentist?", "what is the weather tomorrow?"]
    # The handoff is consumed once: the stale result is gone after an unrelated turn.
    memory.hits = []
    assert await orch._recall_block("when is the dentist?") == ""


async def test_a_backend_error_still_degrades_to_an_empty_block(caplog):
    class _Broken(_Memory):
        async def recall(self, text, top_k=5):
            raise RuntimeError("qdrant unreachable")

    with caplog.at_level(logging.WARNING, logger="jarvis.orchestrator"):
        assert await _orch(_Broken())._recall_block("where is my passport?") == ""
    assert "recall failed" in caplog.text


@pytest.mark.parametrize("raw,expected", [
    (None, 8.0), ("abc", 8.0), (0, 8.0), (-3, 8.0), (True, 8.0), (2.5, 2.5), (10_000, 60.0), (0.01, 0.1),
    (float("nan"), 8.0), (float("inf"), 8.0), (float("-inf"), 8.0),
])
def test_the_timeout_setting_is_validated(raw, expected):
    settings = {} if raw is None else {"memory.recall_timeout_s": raw}
    assert _orch(_Memory(), **settings)._recall_timeout_s() == expected


async def test_recall_off_is_still_off():
    from agents.core.orchestrator import Orchestrator

    memory = _Memory(hits=[_hit()])
    orch = Orchestrator.__new__(Orchestrator)
    orch._runtime_settings = {}  # the seeded default, not an explicit False
    orch.memory = memory
    assert await orch._recall_block("when is the dentist?") == ""
    assert memory.calls == []


# ── review round ─────────────────────────────────────────────────────────────


def test_a_non_finite_number_setting_is_refused():
    assert settings_db.validate_category("memory", {"recall_timeout_s": float("nan")})
    assert settings_db.validate_category("memory", {"recall_timeout_s": float("inf")})
    assert settings_db.validate_category("memory", {"recall_timeout_s": 3}) == []


class _HashEmbedder:
    def embed(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [b / 255 for b in digest]
        return (values * ((768 // len(values)) + 1))[:768]


class _SlowEmbedder(_HashEmbedder):
    def __init__(self, delay):
        self.delay = delay

    def embed(self, text):
        time.sleep(self.delay)
        return super().embed(text)


async def test_a_hung_search_blocks_neither_the_reply_nor_other_sessions(monkeypatch):
    """A real MemoryManager: the stuck search holds only the store lock."""
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    mm._embedder = _HashEmbedder()
    release = threading.Event()

    def stuck_search(query, k=5):
        release.wait(10)
        return []

    monkeypatch.setattr(mm.vectors, "search", stuck_search)
    orch = _orch(mm, **{"memory.recall_timeout_s": 0.2})
    sid = await mm.new_session()
    started = time.monotonic()
    try:
        assert await orch._recall_block("what did I say about the dentist?") == ""
        await asyncio.wait_for(mm.add_turn(sid, "assistant", "noted"), 0.5)
        other = await asyncio.wait_for(mm.new_session(), 0.5)
        await asyncio.wait_for(mm.add_turn(other, "user", "hello there"), 0.5)
        await asyncio.wait_for(mm.get_context(other), 0.5)
        assert time.monotonic() - started < 1.5
        # while the search is stuck, the next recall is skipped, not queued behind it
        assert await asyncio.wait_for(orch._recall_block("and my passport?"), 0.5) == ""
    finally:
        release.set()
        for task in _stuck(orch):
            await asyncio.wait({task})


async def test_a_slow_turn_embedding_never_blocks_the_turn():
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    mm._embedder = _SlowEmbedder(0.5)
    mm.embed_turns = True
    sid = await mm.new_session()
    started = time.monotonic()
    await mm.add_turn(sid, "user", "remember that I like espresso")
    await mm.add_turn(sid, "assistant", "noted, espresso")
    assert time.monotonic() - started < 0.3
    await mm.flush_embeddings()
    assert len(mm.vectors) == 2
    texts = [r.metadata["text"] for r in mm.vectors.records]
    assert texts == ["remember that I like espresso", "noted, espresso"]  # oldest first


async def test_a_purge_drops_queued_turn_embeddings():
    from agents.core import data_purge
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    mm._embedder = _SlowEmbedder(0.3)
    mm.embed_turns = True
    sid = await mm.new_session()
    await mm.add_turn(sid, "user", "my PIN is 1234")

    class _Orch:
        memory = mm

    await data_purge.clear_live_memory(_Orch())
    await mm.flush_embeddings()
    assert len(mm.vectors) == 0


async def test_a_purge_drops_the_late_result_and_anything_still_running():
    from agents.core import data_purge

    memory = _Memory(delay=0.3, hits=[_hit("my PIN is 1234")])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    assert await orch._recall_block("what is my PIN?") == ""   # times out; the straggler runs on
    await data_purge.clear_live_memory(orch)                    # "forget me" while it runs
    await asyncio.sleep(0.4)
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("what is my PIN?") == ""   # the pre-purge result is never served
    assert memory.calls == ["what is my PIN?", "what is my PIN?"]


async def test_a_pinned_job_turn_neither_receives_nor_consumes_a_late_result():
    from agents.core.llm.job_selection import selection_scope

    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await orch._recall_block("when is the dentist?")
    await asyncio.sleep(0.4)
    with selection_scope({"model": "pinned-model"}):
        assert await orch._recall_block("when is the dentist?") == ""
    assert "Tuesday" in await orch._recall_block("when is the dentist?")  # still there for the owner
    assert memory.calls == ["when is the dentist?"]


async def test_concurrent_timeouts_are_all_tracked_and_block_new_queries():
    memory = _Memory(delay=30)
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await asyncio.gather(orch._recall_block("session A asks about the dentist"),
                         orch._recall_block("session B asks about taxes"))
    assert len(_stuck(orch)) == 2
    assert await orch._recall_block("session C asks about the car") == ""
    assert len(memory.calls) == 2  # no third round-trip while either is stuck
    _release(orch)


async def test_a_cancelled_turn_leaves_its_recall_running_as_a_straggler():
    memory = _Memory(delay=0.5)
    orch = _orch(memory, **{"memory.recall_timeout_s": 5})
    turn = asyncio.ensure_future(orch._recall_block("where is my passport?"))
    await asyncio.sleep(0.05)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    stuck = _stuck(orch)
    assert len(stuck) == 1 and not stuck[0].cancelled()  # not cancelled out from under its threads
    assert await orch._recall_block("and my keys?") == ""
    assert memory.calls == ["where is my passport?"]
    await asyncio.wait(set(stuck))


async def test_the_handoff_ttl_counts_from_completion(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(Orchestrator, "_RECALL_HANDOFF_TTL_S", 0.2)
    memory = _Memory(delay=0.5, hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await orch._recall_block("when is the dentist?")
    await asyncio.sleep(0.5)  # finished just now: older than the TTL since the timeout, fresh since completion
    assert "Tuesday" in await orch._recall_block("when is the dentist?")


async def test_a_straggler_that_fails_leaves_nothing_behind(caplog):
    class _Failing(_Memory):
        async def recall(self, text, top_k=5, keyword=None):
            self.calls.append(text)
            await asyncio.sleep(0.2)
            raise RuntimeError("neo4j went away")

    memory = _Failing()
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.05})
    await orch._recall_block("when is the dentist?")
    await asyncio.sleep(0.3)
    memory.calls.clear()
    with caplog.at_level(logging.ERROR):
        assert await orch._recall_block("when is the dentist?") == ""
    assert memory.calls == ["when is the dentist?"]  # a fresh query, not a served failure
    assert "never retrieved" not in caplog.text


async def test_the_rerank_runs_after_the_bound_and_off_the_event_loop(monkeypatch):
    memory = _Memory(hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.2})
    ticks = 0

    def slow_rerank(hits):
        time.sleep(0.5)  # a slow LivingMemory store
        return hits

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    orch._living_memory_rerank_hits = slow_rerank
    beat = asyncio.ensure_future(ticker())
    try:
        block = await orch._recall_block("when is the dentist?")
    finally:
        beat.cancel()
    assert "Tuesday" in block  # the bound covers retrieval, not the local rerank
    assert ticks >= 10         # the loop kept running during the rerank
