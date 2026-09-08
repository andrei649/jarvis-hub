"""Hermes absorption 5c — a model that spends its whole budget thinking says so.

A reasoning model that hits max_tokens while still in reasoning_content used to
come back as "" — and a blank bubble is indistinguishable from "the model said
nothing", so the owner could not tell a budget problem from a silent model. Now
that exact case returns ``THINKING_EXHAUSTED_REPLY``. The reply starts with "⚠️"
on purpose: that is the H23.12 degraded-reply contract, so the orchestrator
scores it as a failed generation (no learning review, zero living-memory reward)
instead of reading it back as an answer the model gave. Every other branch of
the two finalizers is pinned unchanged here, and the reasoning text itself must
never reach the return value in any of them.

Hermetic: pure functions, no model, no network.
"""

from __future__ import annotations

import pytest

from agents.core.llm.base import (
    THINKING_EXHAUSTED_REPLY,
    LLMBackend,
    _finalize_lmstudio_message,
    is_degraded_reply,
)

REASONING = "The owner asked for X; first consider Y, then compare against Z..."


def test_stream_length_with_reasoning_only_returns_the_named_reply():
    out = LLMBackend._finalize_stream("", REASONING, "length", "test-model")
    assert out == THINKING_EXHAUSTED_REPLY


def test_lmstudio_message_length_with_reasoning_only_returns_the_named_reply():
    out = _finalize_lmstudio_message(
        {"content": "", "reasoning_content": REASONING}, "length", "test-model"
    )
    assert out == THINKING_EXHAUSTED_REPLY


def test_reply_is_classified_degraded():
    """The whole point of the "⚠️" prefix: orchestrator persistence and warm-up
    both route through ``is_degraded_reply`` and must treat the reply as a
    failure, not an answer."""
    assert THINKING_EXHAUSTED_REPLY.startswith("⚠️")
    assert is_degraded_reply(THINKING_EXHAUSTED_REPLY) is True


def test_clean_finish_with_reasoning_only_still_surfaces_the_reasoning():
    """finish != length: the model chose to stop and put its answer in
    reasoning_content — that is the answer, not an exhausted budget."""
    assert LLMBackend._finalize_stream("", "The answer is 42.", "stop", "m") == "The answer is 42."
    assert _finalize_lmstudio_message(
        {"content": "", "reasoning_content": "The answer is 42."}, "stop", "m"
    ) == "The answer is 42."


def test_length_with_visible_answer_is_unchanged():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(40))
    assert LLMBackend._finalize_stream(text, REASONING, "length", "m") == text
    assert _finalize_lmstudio_message(
        {"content": text, "reasoning_content": REASONING}, "length", "m"
    ) == text


def test_length_with_no_reasoning_still_returns_empty():
    """Nothing was thought and nothing was said: there is nothing to name."""
    assert LLMBackend._finalize_stream("", "", "length", "m") == ""
    assert LLMBackend._finalize_stream("", "   \n", "length", "m") == ""
    assert _finalize_lmstudio_message({"content": ""}, "length", "m") == ""
    assert _finalize_lmstudio_message(
        {"content": "", "reasoning_content": "<think>only a tag</think>"}, "length", "m"
    ) == ""


def test_repetition_flood_branch_is_unchanged():
    flood = "\n".join(["this exact sixty-plus character line repeats itself over and over again"] * 40)
    assert LLMBackend._finalize_stream(flood, REASONING, "length", "m") == ""
    assert _finalize_lmstudio_message(
        {"content": flood, "reasoning_content": REASONING}, "length", "m"
    ) == ""


def test_reasoning_text_never_leaks_into_the_reply():
    """The named reply is a fixed string; no fragment of the chain-of-thought
    may ride along with it on a length finish."""
    secret = "SECRET-CHAIN-OF-THOUGHT-FRAGMENT"
    out_stream = LLMBackend._finalize_stream("", f"{REASONING} {secret}", "length", "m")
    out_msg = _finalize_lmstudio_message(
        {"content": "", "reasoning_content": f"{REASONING} {secret}"}, "length", "m"
    )
    assert secret not in out_stream and secret not in out_msg
    assert out_stream == out_msg == THINKING_EXHAUSTED_REPLY


@pytest.mark.asyncio
async def test_warm_up_treats_the_named_reply_as_a_loaded_model():
    """A thinking model spends warm-up's single token on reasoning and answers the
    exhausted-budget reply; the weights are resident, which is what warm-up asked.
    A real degraded reply still counts as a failed warm-up."""
    from agents.core.llm.base import LLMBackend

    class _Backend(LLMBackend):
        def __init__(self, reply):
            self.reply = reply

        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            return self.reply

    assert await _Backend(THINKING_EXHAUSTED_REPLY).warm_up("qwen3:32b") is True
    assert await _Backend("Okay.").warm_up("qwen3:32b") is True
    assert await _Backend("⚠️ I can't reach the local LM Studio model right now.").warm_up("m") is False
    assert await _Backend("[LM Studio error: boom]").warm_up("m") is False
