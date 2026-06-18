"""Regression tests for chain-of-thought leakage + truncation handling.

Covers the bug where a reasoning model (deepseek-r1 / gemma) that ran out of
token budget mid-thought had its raw chain-of-thought surfaced as the answer
(and persisted to memory), instead of being suppressed.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.base import (
    LLMBackend, LMStudioBackend, OllamaBackend, strip_thinking,
)


# ── Fake httpx clients (offline) ─────────────────────────────────────────

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakePostClient:
    def __init__(self, data):
        self._data = data

    async def post(self, *a, **kw):
        return _FakeResp(self._data)


class _FakeStreamResp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


class _FakeStreamCtx:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return _FakeStreamResp(self._lines)

    async def __aexit__(self, *a):
        return False


class _FakeStreamClient:
    def __init__(self, lines):
        self._lines = lines

    def stream(self, *a, **kw):
        return _FakeStreamCtx(self._lines)


def _collect():
    out = []
    return out, (lambda t: out.append(t))


# ── strip_thinking ───────────────────────────────────────────────────────

def test_strip_closed_think():
    assert strip_thinking("<think>plan it</think>Hello, sir.") == "Hello, sir."


def test_strip_unclosed_think_after_answer():
    # answer first, then a truncated think block with no closing tag
    assert strip_thinking("Done, sir.<think>now I should also") == "Done, sir."


def test_strip_unclosed_think_only():
    # pure truncated reasoning, no answer at all → nothing to show
    assert strip_thinking("<think>user wants X, *Drafting:* ... Wait") == ""


def test_strip_plain_passthrough():
    assert strip_thinking("Just a normal reply.") == "Just a normal reply."


def test_strip_leading_numbered_steps():
    # a leading numbered-step block terminated by a blank line is dropped
    assert strip_thinking("1. Plan it\n2. Execute\n\nFinal answer.") == "Final answer."


def test_strip_numbered_steps_redos_safe():
    # Pathological input for the old super-linear regex (many "N. …" lines, no
    # terminating blank line). The linear pattern must return promptly and leave
    # the text unchanged (no match → no strip), not hang.
    pathological = "1. " + "a" * 50000
    assert strip_thinking(pathological) == pathological


# ── _finalize_stream decision logic ──────────────────────────────────────

def test_finalize_prefers_emitted():
    assert LLMBackend._finalize_stream("Hi.", "thoughts", "stop", "m") == "Hi."


def test_finalize_drops_truncated_reasoning():
    # finish == length and no emitted answer → truncated mid-thought, suppress
    assert LLMBackend._finalize_stream("", "half a thought, cut", "length", "m") == ""


def test_finalize_surfaces_reasoning_when_finished():
    # model finished cleanly but put the reply in reasoning_content → surface it
    assert LLMBackend._finalize_stream("", "The answer is 42.", "stop", "m") == "The answer is 42."


# ── LMStudioBackend.generate (non-stream) ────────────────────────────────

async def test_generate_truncated_reasoning_not_leaked():
    b = LMStudioBackend()
    b.client = _FakePostClient({"choices": [{
        "message": {"content": "", "reasoning_content": "user wants... *Drafting:* ... Wait"},
        "finish_reason": "length",
    }]})
    assert await b.generate("m", "hi") == ""


async def test_generate_reasoning_as_answer_when_finished():
    b = LMStudioBackend()
    b.client = _FakePostClient({"choices": [{
        "message": {"content": "", "reasoning_content": "The answer is 42."},
        "finish_reason": "stop",
    }]})
    assert await b.generate("m", "hi") == "The answer is 42."


async def test_generate_strips_inline_think():
    b = LMStudioBackend()
    b.client = _FakePostClient({"choices": [{
        "message": {"content": "<think>hmm</think>Hello, sir."},
        "finish_reason": "stop",
    }]})
    assert await b.generate("m", "hi") == "Hello, sir."


# ── LMStudioBackend.generate_stream ──────────────────────────────────────

async def test_stream_reasoning_only_truncated_not_leaked():
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"thinking hard..."}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
        'data: [DONE]',
    ]
    b = LMStudioBackend()
    b.client = _FakeStreamClient(lines)
    tokens, on_token = _collect()
    out = await b.generate_stream("m", "hi", on_token=on_token)
    assert out == ""                 # nothing leaks as the return value
    assert "".join(tokens) == ""     # nothing was streamed to the user either


async def test_stream_emits_answer_after_think():
    lines = [
        'data: {"choices":[{"delta":{"content":"<think>plan</think>Hello"}}]}',
        'data: {"choices":[{"delta":{"content":", sir."},"finish_reason":"stop"}]}',
        'data: [DONE]',
    ]
    b = LMStudioBackend()
    b.client = _FakeStreamClient(lines)
    tokens, on_token = _collect()
    out = await b.generate_stream("m", "hi", on_token=on_token)
    assert out == "Hello, sir."
    assert "".join(tokens) == "Hello, sir."


async def test_stream_inline_think_truncated_not_leaked():
    # opens <think>, never closes, runs out of budget → no answer, no leak
    lines = [
        'data: {"choices":[{"delta":{"content":"<think>let me draft a reply, *Refining*"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
        'data: [DONE]',
    ]
    b = LMStudioBackend()
    b.client = _FakeStreamClient(lines)
    tokens, on_token = _collect()
    out = await b.generate_stream("m", "hi", on_token=on_token)
    assert out == ""
    assert "".join(tokens) == ""


# ── OllamaBackend parity ─────────────────────────────────────────────────

async def test_ollama_stream_drops_truncated_reasoning():
    lines = [
        '{"reasoning_content":"thinking"}',
        '{"response":"","done":true,"done_reason":"length"}',
    ]
    b = OllamaBackend()
    b.client = _FakeStreamClient(lines)
    out = await b.generate_stream("m", "hi")
    assert out == ""
