"""Regression tests for chain-of-thought leakage + truncation handling.

Covers the bug where a reasoning model (deepseek-r1 / gemma) that ran out of
token budget mid-thought had its raw chain-of-thought surfaced as the answer
(and persisted to memory), instead of being suppressed.
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.base import (
    THINKING_EXHAUSTED_REPLY, LLMBackend, LMStudioBackend, OllamaBackend, ThinkingStreamFilter,
    strip_thinking,
)
from core.llm.anthropic import ClaudeBackend
from core.llm.gemini import GeminiBackend


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
    # A real httpx.Response always carries a status; generate_stream reads it to
    # decide whether the body has to be pulled in before the error is inspected.
    status_code = 200

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


def test_strip_preserves_numbered_steps_inside_answer():
    answer = "Here is the sequence:\n1. First step.\n2. Second step.\n\nFinal answer."
    assert strip_thinking(answer) == answer


def test_strip_preserves_leading_answer_steps_and_code():
    answer = "1. Open the project.\n2. Run it.\n\nYou are done."
    code = "Here is the example:\n```text\n1. First.\n2. Second.\n\nDone.\n```"
    assert strip_thinking(answer) == answer
    assert strip_thinking(code) == code


def test_strip_thinking_prose_requires_an_explicit_heading():
    answer = "Thinking about the API, I suggest this:\nKeep the current route.\n\nDone."
    assert strip_thinking(answer) == answer
    assert strip_thinking("**Thinking:**\nPrivate steps.\n\nFinal answer.") == "Final answer."


def test_strip_explicit_thinking_headings_and_unterminated_prose():
    for header in ("**Thinking**", "**Thinking...**", "Thinking…", "Thinking:"):
        for newline in ("\n", "\r\n"):
            assert strip_thinking(f"{header}{newline}Private steps.{newline}{newline}Answer.") == "Answer."
            assert strip_thinking(f"{header}{newline}Private steps.") == ""
    assert strip_thinking("\n\n**Thinking**\nPrivate steps.\n\nAnswer.") == "Answer."
    assert strip_thinking("\n\nThinking about the API.\n\nAnswer.") == "Thinking about the API.\n\nAnswer."


def test_stream_releases_ordinary_thinking_prose_before_newline():
    stream = ThinkingStreamFilter()
    first = stream.feed("Thinking about the API is ordinary answer prose with no newline yet.")
    assert first
    assert first + stream.flush() == "Thinking about the API is ordinary answer prose with no newline yet."
    stream = ThinkingStreamFilter()
    assert stream.feed("\n\nThinking about the API is also ordinary answer prose.")


def test_stream_does_not_retain_long_hidden_thinking_prose():
    stream = ThinkingStreamFilter()
    assert stream.feed("**Thinking**\n") == ""
    for _ in range(1000):
        assert stream.feed("private reasoning continues ") == ""
        assert len(stream._prose._pending) <= 4
    assert stream.feed("\n\nAnswer.") + stream.flush() == "Answer."


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
    # finish == length and no emitted answer → truncated mid-thought: the
    # reasoning is suppressed and (Hermes absorption 5c) the owner gets the
    # named degraded reply instead of a blank bubble.
    out = LLMBackend._finalize_stream("", "half a thought, cut", "length", "m")
    assert out == THINKING_EXHAUSTED_REPLY
    assert "half a thought" not in out


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
    out = await b.generate("m", "hi")
    assert out == THINKING_EXHAUSTED_REPLY   # Hermes absorption 5c: named, not blank
    assert "Drafting" not in out


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
    # Hermes absorption 5c: the return value names the exhausted budget; the
    # reasoning itself never leaks, and nothing was streamed to the user live.
    assert out == THINKING_EXHAUSTED_REPLY
    assert "thinking hard" not in out
    assert "".join(tokens) == ""


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
    assert out == THINKING_EXHAUSTED_REPLY   # Hermes absorption 5c: named, not blank


async def test_ollama_stream_reads_its_native_thinking_key():
    """Ollama spells chain-of-thought "thinking", not reasoning_content; a stream that
    only ever carried the native key used to look like "no reasoning at all" and the
    exhausted-budget guard never fired. Fails before the fix with an empty string."""
    lines = [
        '{"thinking":"let me reason about"}',
        '{"response":"","done":true,"done_reason":"length"}',
    ]
    b = OllamaBackend()
    b.client = _FakeStreamClient(lines)
    out = await b.generate_stream("m", "hi")
    assert out == THINKING_EXHAUSTED_REPLY
    assert "let me reason" not in out


async def test_ollama_stream_keeps_numbered_steps_in_answer():
    answer = "Here is the sequence:\n1. First step.\n2. Second step.\n\nFinal answer."
    raw = "<think>private reasoning</think>" + answer
    lines = [json.dumps({"response": raw[i:i + 7]}) for i in range(0, len(raw), 7)]
    lines.append(json.dumps({"response": "", "done": True, "done_reason": "stop"}))
    backend = OllamaBackend()
    backend.client = _FakeStreamClient(lines)
    tokens, on_token = _collect()

    result = await backend.generate_stream("m", "hi", on_token=on_token)

    assert result == answer
    assert "".join(tokens) == answer


async def test_ollama_stream_never_emits_explicit_thinking_prose():
    for raw, answer in (
        ("**Thinking**\nPrivate steps.\n\nAnswer.", "Answer."),
        ("**Thinking...**\nPrivate steps.\n\nAnswer.", "Answer."),
        ("\n\n**Thinking**\r\nPrivate steps.\r\n\r\nAnswer.", "Answer."),
        ("Here's a thinking process about the task:\nPrivate steps.\n\nAnswer.", "Answer."),
        ("Thinking…\r\nPrivate steps.", ""),
    ):
        lines = [json.dumps({"response": raw[i:i + 3]}) for i in range(0, len(raw), 3)]
        lines.append(json.dumps({"response": "", "done": True, "done_reason": "stop"}))
        backend = OllamaBackend()
        backend.client = _FakeStreamClient(lines)
        tokens, on_token = _collect()

        assert await backend.generate_stream("m", "hi", on_token=on_token) == answer
        assert "".join(tokens) == answer


# ── Cloud backends (Gemini / Claude) parity ──────────────────────────────
# Cloud APIs surface reasoning as structured fields we never read (Gemini
# `thought` parts, Claude `thinking` blocks), so a <think> block in the text
# field is unexpected — but if one lands there it must be stripped, same as
# the local backends (defense-in-depth via LLMBackend._finalize_cloud).

def test_finalize_cloud_passthrough_and_sentinels():
    assert LLMBackend._finalize_cloud("Just a reply.") == "Just a reply."
    assert LLMBackend._finalize_cloud("") == ""
    # error sentinels carry no think-markup and pass through unchanged
    sentinel = "[Gemini stream error: boom]"
    assert LLMBackend._finalize_cloud(sentinel) == sentinel


async def test_gemini_generate_strips_think():
    b = GeminiBackend(api_key="k")
    b.client = _FakePostClient({"candidates": [{"content": {"parts": [
        {"text": "<think>plan it</think>Hello, sir."},
    ]}}]})
    assert await b.generate("m", "hi") == "Hello, sir."


async def test_gemini_stream_strips_think():
    lines = [
        'data: {"candidates":[{"content":{"parts":[{"text":"<think>plan"}]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"</think>Hello, sir."}]}}]}',
        'data: [DONE]',
    ]
    b = GeminiBackend(api_key="k")
    b.client = _FakeStreamClient(lines)
    out = await b.generate_stream("m", "hi")
    assert out == "Hello, sir."


async def test_claude_generate_strips_think():
    b = ClaudeBackend(api_key="k")
    b.client = _FakePostClient({"content": [
        {"type": "text", "text": "<think>hmm</think>Done."},
    ]})
    assert await b.generate("m", "hi") == "Done."


async def test_claude_stream_strips_think():
    # `delta.type` is on every real content_block_delta; the fixture used to omit
    # it, and since H364 the block type is what decides whether a delta is part of
    # the answer (a reasoning delta is not).
    lines = [
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"<think>x</think>Done"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":", sir."}}',
        'data: {"type":"message_stop"}',
    ]
    b = ClaudeBackend(api_key="k")
    b.client = _FakeStreamClient(lines)
    out = await b.generate_stream("m", "hi")
    assert out == "Done, sir."
