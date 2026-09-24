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
    "?", "??", "…?",  # punctuation alone: nothing to search for
    "❓", "❔❔", "$?", "+?",  # second review: a question mark emoji or a sign is punctuation too
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


def _turn(orch, session="owner"):
    """Bind the turn's session the way _resolve_session does. Async tests only: each runs
    in its own task context, so the binding cannot leak into another test."""
    from agents.core.orchestrator import _active_session

    _active_session.set(session)
    return orch


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
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
    assert await orch._recall_block("when is the dentist?") == ""
    await asyncio.sleep(0.4)  # the straggler finishes in the background
    block = await orch._recall_block("when is the dentist?")
    assert "Tuesday" in block
    assert memory.calls == ["when is the dentist?"]  # served from the late result, no new query


async def test_a_late_result_is_not_injected_into_an_unrelated_turn():
    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
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


class _ByTextEmbedder(_HashEmbedder):
    """The first turn embeds slowly, the second fast: only the queue keeps them in order."""

    def embed(self, text):
        time.sleep(0.4 if "espresso" in text and "noted" not in text else 0.05)
        return super().embed(text)


async def test_a_slow_turn_embedding_never_blocks_the_turn():
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    mm._embedder = _ByTextEmbedder()
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
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
    assert await orch._recall_block("what is my PIN?") == ""   # times out; the straggler runs on
    await data_purge.clear_live_memory(orch)                    # "forget me" while it runs
    await asyncio.sleep(0.4)
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("what is my PIN?") == ""   # the pre-purge result is never served
    assert memory.calls == ["what is my PIN?", "what is my PIN?"]


async def test_a_pinned_job_turn_neither_receives_nor_consumes_a_late_result():
    from agents.core.llm.job_selection import selection_scope

    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
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
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
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
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.05}))
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


# ── next-turn warm-up (the half the review found missing) ────────────────────


def _in_session(orch, session):
    return _turn(orch, session)


async def test_a_timed_out_turn_falls_back_to_this_sessions_previous_recall(caplog):
    memory = _Memory(hits=[_hit()])
    orch = _in_session(_orch(memory, **{"memory.recall_timeout_s": 0.2}), "owner")
    assert "Tuesday" in await orch._recall_block("when is the dentist?")
    memory.delay = 30  # the backend hangs from here on
    with caplog.at_level(logging.INFO, logger="jarvis.orchestrator"):
        block = await orch._recall_block("and what time was it?")
    assert "Tuesday" in block and "previous recall (1 hits)" in caplog.text
    # skipped behind the stuck one: the warm context still stands in
    assert "Tuesday" in await orch._recall_block("and which clinic?")
    assert memory.calls == ["when is the dentist?", "and what time was it?"]
    _release(orch)


async def test_warm_context_never_crosses_sessions():
    memory = _Memory(hits=[_hit()])
    orch = _in_session(_orch(memory, **{"memory.recall_timeout_s": 0.2}), "owner")
    await orch._recall_block("when is the dentist?")
    memory.delay = 30
    _in_session(orch, "guest-telegram-42")
    assert await orch._recall_block("and what time was it?") == ""
    _release(orch)


async def test_an_empty_recall_is_an_answer_not_a_miss():
    memory = _Memory(hits=[_hit()])
    orch = _in_session(_orch(memory), "owner")
    await orch._recall_block("when is the dentist?")
    memory.hits = []
    assert await orch._recall_block("what is the weather tomorrow?") == ""


async def test_warm_context_is_dropped_by_a_purge_and_expires(monkeypatch):
    from agents.core import data_purge
    from agents.core.orchestrator import Orchestrator

    memory = _Memory(hits=[_hit("my PIN is 1234")])
    orch = _in_session(_orch(memory, **{"memory.recall_timeout_s": 0.2}), "owner")
    await orch._recall_block("what is my PIN?")
    await data_purge.clear_live_memory(orch)
    memory.delay = 30
    assert await orch._recall_block("and the other card?") == ""
    _release(orch)

    memory.delay = 0
    fresh = _in_session(_orch(memory, **{"memory.recall_timeout_s": 0.2}), "owner")
    await fresh._recall_block("what is my PIN?")
    monkeypatch.setattr(Orchestrator, "_RECALL_HANDOFF_TTL_S", 0.0)
    memory.delay = 30
    assert await fresh._recall_block("and the other card?") == ""
    _release(fresh)


async def test_trivial_and_pinned_turns_get_no_warm_context():
    from agents.core.llm.job_selection import selection_scope

    memory = _Memory(hits=[_hit()])
    orch = _in_session(_orch(memory, **{"memory.recall_timeout_s": 0.2}), "owner")
    await orch._recall_block("when is the dentist?")
    memory.delay = 30
    assert await orch._recall_block("ok") == ""
    with selection_scope({"model": "pinned-model"}):
        assert await orch._recall_block("and what time was it?") == ""
    assert memory.calls == ["when is the dentist?"]



# ── re-review round: the generation a recall starts under ─────────────────────


async def test_a_purge_inside_the_bound_discards_what_the_recall_read():
    from agents.core import data_purge

    memory = _Memory(delay=0.3, hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 2.0}))
    turn = asyncio.ensure_future(orch._recall_block("what is my PIN?"))
    await asyncio.sleep(0.1)
    await data_purge.clear_live_memory(orch)       # "forget me" while the search runs
    assert await turn == ""                        # it finished inside the bound, but read pre-purge data
    memory.delay, memory.hits = 30, []
    assert await orch._recall_block("and the other card?") == ""   # and nothing was kept warm
    _release(orch)


async def test_a_purge_between_start_and_timeout_leaves_no_handoff():
    from agents.core import data_purge

    memory = _Memory(delay=0.5, hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.3}))
    turn = asyncio.ensure_future(orch._recall_block("what is my PIN?"))
    await asyncio.sleep(0.1)
    await data_purge.clear_live_memory(orch)       # before the timeout adopts the straggler
    assert await turn == ""
    await asyncio.sleep(0.5)                       # the straggler finishes after the purge
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("what is my PIN?") == ""
    assert memory.calls == ["what is my PIN?", "what is my PIN?"]  # a fresh query, no handoff


async def test_an_empty_recall_replaces_the_warm_context():
    memory = _Memory(hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.2}))
    await orch._recall_block("when is the dentist?")
    memory.hits = []
    assert await orch._recall_block("what is the weather tomorrow?") == ""
    memory.delay = 30
    assert await orch._recall_block("and the day after?") == ""   # not the dentist from two turns ago
    _release(orch)


async def test_a_single_memory_delete_drops_cached_recall_results():
    from agents.core.routers.memory_kg import _recall_forget

    memory = _Memory(hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.2}))
    await orch._recall_block("when is the dentist?")
    _recall_forget(orch)                           # what DELETE /api/kg/entities/{name} now does
    memory.delay = 30
    assert await orch._recall_block("and what time was it?") == ""
    _release(orch)


async def test_internal_callers_neither_keep_nor_take_turn_state():
    from agents.core.orchestrator import _SESSION_UNSET, _active_session

    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
    await orch._recall_block("when is the dentist?")      # an owner's turn times out
    await asyncio.sleep(0.4)                               # its late result is waiting
    _active_session.set(_SESSION_UNSET)                    # an autonomy task: no bound session
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("when is the dentist?") == ""
    assert "owner" in orch._recall_state.late              # not consumed by the background caller
    assert orch._recall_state.warm == {}                   # and nothing kept warm for it
    _turn(orch)
    assert "Tuesday" in await orch._recall_block("when is the dentist?")  # the owner's retry gets it


async def test_the_purge_waits_for_a_write_already_in_the_store():
    from agents.core import data_purge
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    real_add = mm.vectors.add

    def slow_add(record_id, vector, metadata=None):
        time.sleep(0.3)
        real_add(record_id, vector, metadata)

    mm.vectors.add = slow_add
    write = asyncio.ensure_future(mm.store_embedding("mem-1", [0.1] * 768, {"text": "my PIN is 1234"}))
    await asyncio.sleep(0.05)                      # the write holds the store lock, inside vectors.add

    class _Orch:
        memory = mm

    await data_purge.clear_live_memory(_Orch())
    await write
    assert len(mm.vectors) == 0                    # the wipe came after the write, not before


async def test_a_single_vector_remove_does_not_hold_the_conversation_lock():
    from agents.core.memory.manager import MemoryManager
    from agents.core.routers.memory_kg import _vector_remove

    mm = MemoryManager()
    mm._embedder = _HashEmbedder()
    await mm.remember("forget this", record_id="mem-x")
    async with mm._lock:                           # a turn is saving its reply
        assert await asyncio.wait_for(_vector_remove(mm, "mem-x"), 0.5) is True
    assert len(mm.vectors) == 0


async def test_the_cli_flush_waits_for_the_queued_embeddings():
    import agents.run as run

    class _Memory:
        flushed = 0

        async def flush_embeddings(self):
            _Memory.flushed += 1

    await run._flush_embeddings(type("Orch", (), {"memory": _Memory()})())
    assert _Memory.flushed == 1


async def test_the_cli_says_on_exit_that_unwritten_turns_may_be_lost(capsys):
    import agents.run as run

    class _Memory:
        async def flush_embeddings(self):
            await asyncio.sleep(1)

    await run._flush_embeddings(type("Orch", (), {"memory": _Memory()})(), timeout=0.01)
    assert "may not be remembered" in capsys.readouterr().out


async def test_shutdown_drops_what_did_not_land_in_time(monkeypatch):
    from types import SimpleNamespace

    from agents.core.orchestrator import Orchestrator

    real_wait_for = asyncio.wait_for
    monkeypatch.setattr(asyncio, "wait_for", lambda aw, timeout: real_wait_for(aw, 0.01))

    class _Memory:
        discarded = 0

        async def flush_embeddings(self):
            await asyncio.sleep(1)

        def discard_pending_embeddings(self):
            _Memory.discarded += 1

    async def _noop(*a, **k):
        return None

    orch = Orchestrator.__new__(Orchestrator)
    orch.channel_manager = SimpleNamespace(stop_all=_noop)
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None)
    orch.plugin_manager = SimpleNamespace(close_all=_noop)
    orch._settings_watcher_task = orch._autonomy_task = orch._learning_task = None
    orch.oracle_bridge = None
    orch.memory = _Memory()
    await orch.stop_channels()
    assert _Memory.discarded == 1


def _cli(monkeypatch, lines, *, typing_s=0.0, flush=None):
    """agents.run.main() over a scripted stdin; returns the event log."""
    import builtins
    from types import SimpleNamespace

    import agents.run as run

    events = []

    class _Memory:
        async def flush_embeddings(self):
            events.append("flush")
            if flush is not None:
                await flush()

    class _Orch:
        def __init__(self, _config):
            self.memory = _Memory()
            self.llm_router = SimpleNamespace(name="stub")
            self.agents, self.skills = {}, SimpleNamespace(skills={})
            self.checkpoints = SimpleNamespace(info=lambda: {})

        async def load_agents(self):
            return None

        async def handle_input(self, text):
            events.append(f"turn:{text}")
            return "ok"

    script = iter(lines)

    def _input(_prompt=""):
        time.sleep(typing_s)  # the owner typing
        events.append("input")
        try:
            return next(script)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(run, "JarvisConfig", lambda: None)
    monkeypatch.setattr(run, "Orchestrator", _Orch)
    monkeypatch.setattr(builtins, "input", _input)
    return run, events


async def test_the_cli_flushes_on_exit_and_never_between_turns(monkeypatch):
    run, events = _cli(monkeypatch, ["hello", "exit"])
    await run.main()
    assert events == ["input", "turn:hello", "input", "flush"]


async def test_the_cli_flushes_at_the_end_of_input_too(monkeypatch):
    run, events = _cli(monkeypatch, ["hello"])
    await run.main()
    assert events == ["input", "turn:hello", "input", "flush"]


async def test_the_event_loop_keeps_running_while_the_owner_types(monkeypatch):
    # input() used to block the loop, so queued turn embeddings waited for the next
    # message; now the prompt reads on a daemon thread and background work runs on.
    run, events = _cli(monkeypatch, ["exit"], typing_s=0.3)
    ticks = 0

    async def background():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.ensure_future(background())
    try:
        await run.main()
    finally:
        beat.cancel()
    assert ticks >= 5 and events == ["input", "flush"]


# ── re-review round: every guard pinned on its own ────────────────────────────


class _SlowClearMemory(_Memory):
    """A recall backend whose conversation clear takes a while (a real purge awaits it)."""

    clear_s = 0.4

    async def clear(self):
        await asyncio.sleep(self.clear_s)


async def test_a_recall_that_finishes_during_the_purge_is_not_served():
    from agents.core import data_purge

    memory = _SlowClearMemory(delay=0.2, hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 2.0}))
    turn = asyncio.ensure_future(orch._recall_block("what is my PIN?"))
    await asyncio.sleep(0.05)
    purge = asyncio.ensure_future(data_purge.clear_live_memory(orch))
    assert await turn == ""                        # it finished mid-purge, before the wipe
    await purge


async def test_a_recall_started_during_the_purge_is_not_kept_after_it():
    from agents.core import data_purge

    memory = _SlowClearMemory(hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.2}))
    purge = asyncio.ensure_future(data_purge.clear_live_memory(orch))
    await asyncio.sleep(0.1)                       # the purge is clearing, the stores are not wiped yet
    await orch._recall_block("what is my PIN?")    # reads what is about to be wiped
    await purge
    memory.delay = 30
    assert await orch._recall_block("and the other card?") == ""   # its warm context is gone
    _release(orch)


async def test_a_delete_during_the_search_skips_the_rerank():
    memory = _Memory(delay=0.2, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 2.0}))
    reranked = []
    orch._living_memory_rerank_hits = lambda hits: reranked.append(hits) or hits
    turn = asyncio.ensure_future(orch._recall_block("when is the dentist?"))
    await asyncio.sleep(0.05)
    orch._recall_purged()                          # a delete lands while the search runs
    assert await turn == ""
    assert reranked == []                          # deleted memories are not reinforced


async def test_a_delete_during_the_rerank_serves_and_keeps_nothing():
    memory = _Memory(hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.2}))

    def rerank_then_delete(hits):
        orch._recall_purged()                      # the delete lands while the rerank runs
        return hits

    orch._living_memory_rerank_hits = rerank_then_delete
    assert await orch._recall_block("when is the dentist?") == ""
    assert orch._recall_state.warm == {}           # nothing stored under the stale generation
    memory.delay = 30
    assert await orch._recall_block("and what time was it?") == ""  # not kept warm either
    _release(orch)


async def test_the_kg_delete_routes_drop_cached_recall_results(monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory.graph import InMemoryGraph
    from agents.core.routers import memory_kg

    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    graph = InMemoryGraph()
    graph.add_entity("Dentist", "place")
    graph.add_entity("Owner", "person")
    graph.add_relation("Owner", "VISITS", "Dentist")
    purged = []
    orch = SimpleNamespace(memory=SimpleNamespace(graph=graph), _recall_purged=lambda: purged.append(1))
    monkeypatch.setattr(memory_kg, "get_orch", lambda: orch)

    assert (await memory_kg.kg_delete_relation("Owner", "VISITS", "Dentist")).status_code == 200
    assert purged == [1]
    assert (await memory_kg.kg_delete_entity("Dentist")).status_code == 200
    assert purged == [1, 1]
    assert (await memory_kg.kg_delete_entity("Dentist")).status_code == 404
    assert purged == [1, 1]                        # nothing was deleted: nothing to drop


async def test_a_consolidation_that_removes_a_memory_drops_cached_recall_results(monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory.consolidation import ADD, UPDATE, ConsolidationEngine
    from agents.core.routers import _component, memory_kg

    class _Vectors:
        def remove(self, record_id):
            return None

    class _Mem:
        vectors = _Vectors()

        async def remember(self, text, record_id=None, metadata=None):
            if record_id:
                raise RuntimeError("the embedder died after the old vector was removed")
            return "mem-new"

    purged = []
    orch = SimpleNamespace(memory=_Mem(), consolidation=ConsolidationEngine(),
                           _recall_purged=lambda: purged.append(1))
    monkeypatch.setattr(memory_kg, "get_orch", lambda: orch)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    existing = [{"id": "mem-1", "key": "city", "text": "User lives in Bucharest", "persistable": True}]

    class _Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    add = [{"op": ADD, "text": "User works as an architect"}]
    update = [{"op": UPDATE, "target_id": "mem-1", "text": "User lives in Cluj"}]
    await memory_kg.memory_consolidate_apply(_Req({"plan": add, "existing": existing}))
    await memory_kg.memory_consolidate_apply(_Req({"plan": update, "existing": existing, "dry_run": True}))
    assert purged == []                            # an ADD or a dry run removes nothing
    await memory_kg.memory_consolidate_apply(_Req({"plan": update, "existing": existing}))
    assert purged == [1]                           # the old text was removed, even though the re-add failed


# ── second review: the write side, sessions, and the erasing window ─────────────


async def test_a_write_slower_than_the_purges_wait_removes_itself_and_the_purge_says_so(monkeypatch):
    from agents.core import data_purge
    from agents.core.memory.manager import MemoryManager

    monkeypatch.setattr(data_purge, "STORE_LOCK_WAIT_S", 0.2)   # stands in for 10 s
    mm = MemoryManager()
    real_add = mm.vectors.add

    def slow_add(record_id, vector, metadata=None):
        time.sleep(0.6)                            # a Qdrant PUT slower than the wait
        real_add(record_id, vector, metadata)

    mm.vectors.add = slow_add
    write = asyncio.ensure_future(mm.store_embedding(
        "mem-1", [0.1] * 768, {"text": "my PIN is 1234"}, generation=mm._embed_generation))
    await asyncio.sleep(0.05)                      # past its generation check, inside vectors.add

    class _Orch:
        memory = mm

    cleared, failed = await data_purge.clear_live_memory(_Orch())
    assert "vectors" in cleared
    assert any(f.startswith("store lock:") for f in failed)   # not a clean-wipe claim (AUDIT-2)
    assert await write is False
    assert len(mm.vectors) == 0                    # it took its own record back out


async def test_a_queued_turn_embedding_in_the_store_at_the_wipe_does_not_survive(monkeypatch):
    import threading

    from agents.core import data_purge
    from agents.core.memory.manager import MemoryManager

    monkeypatch.setattr(data_purge, "STORE_LOCK_WAIT_S", 0.2)
    mm = MemoryManager()
    mm._embedder = _HashEmbedder()
    mm.embed_turns = True
    real_add = mm.vectors.add
    in_add = threading.Event()

    def slow_add(record_id, vector, metadata=None):
        in_add.set()
        time.sleep(0.6)
        real_add(record_id, vector, metadata)

    mm.vectors.add = slow_add
    sid = await mm.new_session()
    await mm.add_turn(sid, "user", "my PIN is 1234")
    for _ in range(100):
        if in_add.is_set():
            break
        await asyncio.sleep(0.01)

    class _Orch:
        memory = mm

    await data_purge.clear_live_memory(_Orch())
    await mm.flush_embeddings()
    assert len(mm.vectors) == 0


async def test_remember_carries_the_generation_it_started_under():
    from agents.core.memory.manager import MemoryManager

    mm = MemoryManager()
    gate = asyncio.Event()

    async def slow_embed(text):
        await gate.wait()
        return [0.1] * 768

    mm.embed = slow_embed
    pending = asyncio.ensure_future(mm.remember("my PIN is 1234"))
    await asyncio.sleep(0)
    mm.discard_pending_embeddings()                # "forget me" while it embeds
    gate.set()
    assert await pending is None and len(mm.vectors) == 0


async def test_recall_serves_nothing_while_the_purge_is_erasing():
    from agents.core import data_purge

    memory = _SlowClearMemory(hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 2.0}))
    purge = asyncio.ensure_future(data_purge.clear_live_memory(orch))
    await asyncio.sleep(0.1)                       # between the purge's two bumps
    assert await orch._recall_block("what is my PIN?") == ""
    assert memory.calls == []                      # not even searched
    await purge
    assert orch._recall_state.erasing == 0
    memory.hits = [_hit("the dentist is on Tuesday")]
    assert "Tuesday" in await orch._recall_block("when is the dentist?")   # recall is back


async def test_a_failed_purge_still_ends_the_erasing_window(monkeypatch):
    from agents.core import data_purge

    async def boom(*_a, **_k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(data_purge, "_clear_live_stores", boom)
    orch = _turn(_orch(_Memory(hits=[_hit()])))
    with pytest.raises(RuntimeError):
        await data_purge.clear_live_memory(orch)
    assert orch._recall_state.erasing == 0 and orch._recall_state.generation == 2


async def test_an_internal_callers_straggler_leaves_the_owners_handoff_alone():
    from agents.core.orchestrator import _SESSION_UNSET, _active_session

    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
    assert await orch._recall_block("when is the dentist?") == ""
    await asyncio.sleep(0.4)                       # the owner's late result is waiting
    token = _active_session.set(_SESSION_UNSET)    # an autonomy task times out as well
    assert await orch._recall_block("summarise today's calendar") == ""
    await asyncio.sleep(0.4)
    _active_session.reset(token)
    assert list(orch._recall_state.late) == ["owner"]    # the background straggler left none
    memory.delay = 30
    assert "Tuesday" in await orch._recall_block("when is the dentist?")   # still the owner's
    _release(orch)


async def test_a_late_result_is_handed_only_to_its_own_session():
    memory = _Memory(delay=0.3, hits=[_hit()])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 0.1}))
    await orch._recall_block("when is the dentist?")        # the owner's recall times out
    await asyncio.sleep(0.4)
    _turn(orch, "guest-telegram-42")
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("when is the dentist?") == ""   # searched afresh, not handed
    assert memory.calls == ["when is the dentist?", "when is the dentist?"]
    _turn(orch)
    assert "Tuesday" in await orch._recall_block("when is the dentist?")   # the owner's is intact


async def test_a_cancelled_turn_across_a_purge_leaves_no_handoff():
    from agents.core import data_purge

    memory = _Memory(delay=0.5, hits=[_hit("my PIN is 1234")])
    orch = _turn(_orch(memory, **{"memory.recall_timeout_s": 2.0}))
    turn = asyncio.ensure_future(orch._recall_block("what is my PIN?"))
    await asyncio.sleep(0.1)
    await data_purge.clear_live_memory(orch)       # forget while the search runs
    turn.cancel()                                  # then the client goes away
    with pytest.raises(asyncio.CancelledError):
        await turn
    await asyncio.sleep(0.6)                       # the straggler finishes after the purge
    assert orch._recall_state.late == {}
    memory.delay, memory.hits = 0.0, []
    assert await orch._recall_block("what is my PIN?") == ""
    assert memory.calls == ["what is my PIN?", "what is my PIN?"]


async def test_the_purge_never_releases_a_store_lock_it_did_not_take(monkeypatch):
    import threading

    from agents.core import data_purge
    from agents.core.memory.manager import MemoryManager

    monkeypatch.setattr(data_purge, "STORE_LOCK_WAIT_S", 0.1)
    mm = MemoryManager()
    mm._embedder = _HashEmbedder()
    await mm.remember("my PIN is 1234")
    release = threading.Event()
    real_search = mm.vectors.search

    def stuck_search(query, k=5):
        release.wait(5)
        return real_search(query, k)

    monkeypatch.setattr(mm.vectors, "search", stuck_search)
    search = asyncio.ensure_future(mm.hybrid_search(embedding=[0.1] * 768, keyword="PIN", top_k=5))
    await asyncio.sleep(0.05)

    class _Orch:
        memory = mm

    _cleared, failed = await data_purge.clear_live_memory(_Orch())
    assert any(f.startswith("store lock:") for f in failed)
    assert mm._store_lock.locked()                 # still the search's
    release.set()
    await search                                   # its own release works
    assert not mm._store_lock.locked()


async def test_a_kg_edit_that_replaces_an_entity_drops_cached_recall_results(monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory.graph import InMemoryGraph
    from agents.core.routers import memory_kg

    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    graph = InMemoryGraph()
    graph.add_entity("Card", "thing", {"pin": "1234"})
    purged = []
    orch = SimpleNamespace(memory=SimpleNamespace(graph=graph), _recall_purged=lambda: purged.append(1))
    monkeypatch.setattr(memory_kg, "get_orch", lambda: orch)

    class _Req:
        headers = {}

        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    await memory_kg.kg_upsert_entity(_Req({"name": "Bank", "type": "thing"}))
    assert purged == []                            # a new entity removes nothing
    await memory_kg.kg_upsert_entity(_Req({"name": "Card", "type": "thing", "properties": {}}))
    assert purged == [1]                           # the PIN was edited out


async def test_a_kg_delete_cancelled_mid_call_still_drops_cached_results(monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory.graph import InMemoryGraph
    from agents.core.routers import memory_kg

    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    graph = InMemoryGraph()
    graph.add_entity("Card", "thing", {"pin": "1234"})
    real_delete = graph.delete_entity

    def slow_delete(name):
        time.sleep(0.3)                            # a Neo4j round-trip
        return real_delete(name)

    graph.delete_entity = slow_delete
    purged = []
    orch = SimpleNamespace(memory=SimpleNamespace(graph=graph), _recall_purged=lambda: purged.append(1))
    monkeypatch.setattr(memory_kg, "get_orch", lambda: orch)
    call = asyncio.ensure_future(memory_kg.kg_delete_entity("Card"))
    await asyncio.sleep(0.1)
    call.cancel()                                  # the thread goes on and deletes
    with pytest.raises(asyncio.CancelledError):
        await call
    assert purged == [1]


async def test_a_consolidation_that_removes_nothing_keeps_the_cached_results(monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory.consolidation import UPDATE, ConsolidationEngine
    from agents.core.routers import _component, memory_kg

    removed = []

    class _Mem:
        vectors = SimpleNamespace(remove=removed.append)

        async def remember(self, text, record_id=None, metadata=None):
            return record_id or "mem-new"

    purged = []
    orch = SimpleNamespace(memory=_Mem(), consolidation=ConsolidationEngine(),
                           _recall_purged=lambda: purged.append(1))
    monkeypatch.setattr(memory_kg, "get_orch", lambda: orch)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)

    class _Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    graph_only = [{"id": "Rex", "key": None, "text": "User has a dog named Rex", "persistable": False}]
    out = await memory_kg.memory_consolidate_apply(_Req({
        "plan": [{"op": UPDATE, "target_id": "Rex", "text": "User has a cat"}], "existing": graph_only}))
    assert out.status_code == 200 and removed == [] and purged == []   # skipped: nothing removed


async def test_a_failed_recall_overtaken_by_a_delete_leaves_no_unretrieved_exception(caplog):
    import gc

    class _Failing(_Memory):
        async def recall(self, text, top_k=5, keyword=None):
            await asyncio.sleep(0.2)
            raise RuntimeError("qdrant went away")

    orch = _turn(_orch(_Failing(), **{"memory.recall_timeout_s": 2.0}))
    turn = asyncio.ensure_future(orch._recall_block("what is my PIN?"))
    await asyncio.sleep(0.05)
    orch._recall_purged()
    with caplog.at_level(logging.ERROR, logger="asyncio"):
        assert await turn == ""
        gc.collect()
        await asyncio.sleep(0)
    assert "never retrieved" not in caplog.text
