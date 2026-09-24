"""H428 — pre-turn recall with a triviality gate, a hard timeout, and a late-result handoff.

Hermes gates its memory prefetch on one anchored ``is_trivial_prompt`` (empty input,
a slash command, a bare acknowledgement — ``k8s``/``yolo`` deliberately not), bounds
every external prefetch at 8 s on a daemon thread, skips a provider whose previous
prefetch is still running, and hands late results to the next turn instead of
throwing them away. Nerva's ``Orchestrator._recall_block`` paid an embedding plus a
fused vector ⊕ graph query for "ok", and awaited it with no bound: a slow backend
stalled the turn — and every recall queued behind the memory lock — without limit.
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from agents.core import settings_db
from agents.core.memory.recall_gate import is_trivial_prompt


@pytest.mark.parametrize("text", [
    "", "   ", "/help", "/skill weather now", "ok", "OK!", "okay.", "k", "thanks :)", "Thank you.",
    "thx", "hi!", "hello", "hey", "lgtm", "cool", "nice", "great!!", "done???", "go ahead", "got it",
    "yes", "no.", "sure", "da", "Nu.", "mersi", "Mulțumesc!", "multumesc", "mulţumesc", "merci",
    "bine", "super 👍", "perfect", "salut", "gata", "👍", "ok 🙏",
])
def test_trivial_prompts_skip_recall(text):
    assert is_trivial_prompt(text) is True


@pytest.mark.parametrize("text", [
    "k8s", "yolo", "note", "ok, and what about the dentist?", "thanks for the Q3 summary",
    "da, trimite raportul", "what did I say about the dentist", "hi, remind me what we decided",
    "okay so the invoice", "nope not that one either, the blue one", "o" * 50,
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

    async def recall(self, text, top_k=5):
        self.calls.append(text)
        await asyncio.sleep(self.delay)
        return list(self.hits)


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
    orch._recall_straggler.cancel()


async def test_a_turn_skips_recall_while_the_timed_out_one_is_still_running(caplog):
    memory = _Memory(delay=30)
    orch = _orch(memory, **{"memory.recall_timeout_s": 0.1})
    await orch._recall_block("first question about the dentist")
    with caplog.at_level(logging.INFO, logger="jarvis.orchestrator"):
        assert await orch._recall_block("second question about taxes") == ""
    assert memory.calls == ["first question about the dentist"]  # no second round-trip queued
    assert "still running" in caplog.text
    orch._recall_straggler.cancel()


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
])
def test_the_timeout_setting_is_validated(raw, expected):
    settings = {} if raw is None else {"memory.recall_timeout_s": raw}
    assert _orch(_Memory(), **settings)._recall_timeout_s() == expected


async def test_recall_off_is_still_off():
    memory = _Memory(hits=[_hit()])
    orch = _orch(memory, **{"memory.recall_enabled": False})
    assert await orch._recall_block("when is the dentist?") == ""
    assert memory.calls == []
