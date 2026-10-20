"""
Tests for the truncated-output repetition guard (agents/core/llm/
repetition_guard.py) and its wiring into the LLM finalizers — ported from
hermes-agent agent/repetition_guard.py (Nous Research, MIT, v2026.8.27).
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm.base import LLMBackend, _finalize_lmstudio_message
from agents.core.llm.repetition_guard import (
    MIN_FRAGMENT_LENGTH,
    is_repetition_dominated,
)

# A single long sentence echoed until it dominates the fragment (line-aligned).
_ECHO_LINE = "I will now repeat this exact sentence because I am stuck in a loop."
REPEATED_TEXT = "\n".join([_ECHO_LINE] * 40)

# Repetition that does NOT align to line boundaries (one unbroken stream).
UNALIGNED_TEXT = ("the same sixty-plus character fragment keeps flowing without a break " * 30)


def test_short_fragments_never_trip():
    assert is_repetition_dominated(_ECHO_LINE) is False
    assert is_repetition_dominated("a" * (MIN_FRAGMENT_LENGTH - 1)) is False


def test_non_string_and_empty_fail_open():
    assert is_repetition_dominated(None) is False
    assert is_repetition_dominated("") is False
    assert is_repetition_dominated(12345) is False


def test_line_aligned_repetition_detected():
    assert is_repetition_dominated(REPEATED_TEXT) is True


def test_unaligned_repetition_detected():
    assert is_repetition_dominated(UNALIGNED_TEXT) is True


def test_ordinary_long_prose_not_blocked():
    # Long, varied text (unique lines) must never be classified as repetition.
    text = "\n".join(f"Paragraph {i}: unique content about topic number {i}." for i in range(60))
    assert len(text) > MIN_FRAGMENT_LENGTH
    assert is_repetition_dominated(text) is False


def test_repeated_headings_in_varied_text_not_blocked():
    # A heading repeated a few times inside otherwise-unique text is ordinary.
    blocks = []
    for i in range(4):
        blocks.append("## Results")
        blocks.append(f"Section {i} discusses a different aspect of the data, {i * 17}.")
    text = "\n".join(blocks) * 3
    assert is_repetition_dominated(text) is False


# ── wiring: truncated + repetition-dominated ⇒ no answer (degrade cleanly) ──


def test_finalize_stream_drops_repetition_dominated_truncation():
    out = LLMBackend._finalize_stream(REPEATED_TEXT, "", "length", "test-model")
    assert out == ""


def test_finalize_stream_keeps_clean_truncated_answer():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(40))
    out = LLMBackend._finalize_stream(text, "", "length", "test-model")
    assert out == text


def test_finalize_stream_keeps_repetitive_but_complete_answer():
    # finish != length: the model chose to stop — deliver what it wrote.
    out = LLMBackend._finalize_stream(REPEATED_TEXT, "", "stop", "test-model")
    assert out == REPEATED_TEXT


def test_finalize_lmstudio_drops_repetition_dominated_truncation():
    out = _finalize_lmstudio_message({"content": REPEATED_TEXT}, "length", "test-model")
    assert out == ""


def test_finalize_lmstudio_keeps_clean_answer():
    out = _finalize_lmstudio_message({"content": "A short clean answer."}, "stop", "test-model")
    assert out == "A short clean answer."


# ── H393: the guard on cloud finalization (_finalize_cloud) ──


def test_finalize_cloud_drops_repetition_dominated_truncation():
    for finish in ("length", "max_tokens", "MAX_TOKENS"):
        assert LLMBackend._finalize_cloud(REPEATED_TEXT, finish, "cloud-model") == ""


def test_finalize_cloud_keeps_repetitive_but_complete_answer():
    assert LLMBackend._finalize_cloud(REPEATED_TEXT, "end_turn", "m") == REPEATED_TEXT
    # Legacy single-argument call: no finish reason known => never blocked.
    assert LLMBackend._finalize_cloud(REPEATED_TEXT) == REPEATED_TEXT


def test_finalize_cloud_keeps_clean_truncated_answer():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(40))
    assert LLMBackend._finalize_cloud(text, "max_tokens", "m") == text


def _claude_backend(handler):
    from agents.core.llm.anthropic import ClaudeBackend

    backend = ClaudeBackend(api_key="k")
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return backend


def test_claude_generate_drops_truncated_repetition_loop():
    def handler(request):
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": REPEATED_TEXT}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    backend = _claude_backend(handler)
    try:
        out = asyncio.run(backend.generate("claude-x", "p"))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == ""


def _claude_stream_body(text: str, stop_reason: str) -> str:
    events = [{"type": "message_start", "message": {"usage": {"input_tokens": 1}}}]
    events += [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": text[i:i + 40]}}
               for i in range(0, len(text), 40)]
    events += [{"type": "message_delta", "delta": {"stop_reason": stop_reason},
                "usage": {"output_tokens": 5}},
               {"type": "message_stop"}]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


def test_claude_stream_drops_truncated_loop_and_hides_it_live():
    body = _claude_stream_body(UNALIGNED_TEXT * 4, "max_tokens")
    backend = _claude_backend(lambda req: httpx.Response(200, text=body))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("claude-x", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == ""
    assert len("".join(shown)) < len(UNALIGNED_TEXT * 4) // 4


def test_claude_stream_keeps_complete_answer():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(60))
    body = _claude_stream_body(text, "end_turn")
    backend = _claude_backend(lambda req: httpx.Response(200, text=body))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("claude-x", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == text and "".join(shown) == text


def _gemini_run(handler, call):
    from agents.core.llm.gemini import GeminiBackend

    backend = GeminiBackend(api_key="gm-test")
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        return asyncio.run(call(backend))
    finally:
        asyncio.run(backend.client.aclose())


def _gemini_frame(text: str, finish: str | None = None) -> dict:
    candidate = {"content": {"parts": [{"text": text}]}, "index": 0}
    if finish:
        candidate["finishReason"] = finish
    return {"candidates": [candidate]}


def test_gemini_generate_drops_truncated_repetition_loop():
    body = _gemini_frame(REPEATED_TEXT, "MAX_TOKENS")
    out = _gemini_run(lambda req: httpx.Response(200, json=body),
                      lambda b: b.generate("gemini-x", "p"))
    assert out == ""


def test_gemini_generate_keeps_complete_repetitive_answer():
    body = _gemini_frame(REPEATED_TEXT, "STOP")
    out = _gemini_run(lambda req: httpx.Response(200, json=body),
                      lambda b: b.generate("gemini-x", "p"))
    assert out == REPEATED_TEXT


def test_gemini_stream_drops_truncated_loop_and_hides_it_live():
    looping = UNALIGNED_TEXT * 4
    frames = [_gemini_frame(looping[i:i + 40]) for i in range(0, len(looping), 40)]
    frames.append(_gemini_frame("", "MAX_TOKENS"))
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames)
    shown = []
    out = _gemini_run(lambda req: httpx.Response(200, text=body),
                      lambda b: b.generate_stream("gemini-x", "p", on_token=shown.append))
    assert out == ""
    assert len("".join(shown)) < len(looping) // 4


# ── H393: incremental detection while streaming ──


def test_stream_guard_passes_ordinary_text_through():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    text = "\n".join(f"Paragraph {i}: unique content about topic number {i}." for i in range(80))
    guard = RepetitionStreamGuard()
    out = "".join(guard.feed(text[i:i + 7]) for i in range(0, len(text), 7))
    assert out == text and guard.tripped is False


def test_stream_guard_stops_emitting_once_tail_is_repetition_dominated():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    prefix = "Here is a genuine introduction to the answer before things go wrong.\n"
    text = prefix + UNALIGNED_TEXT * 4
    guard = RepetitionStreamGuard()
    out = "".join(guard.feed(text[i:i + 13]) for i in range(0, len(text), 13))
    assert guard.tripped is True
    assert out.startswith(prefix)
    # Only a small lead-in of the loop is ever shown live.
    assert len(out) < len(text) // 4
    assert guard.feed("anything more") == ""


def test_stream_guard_ignores_non_strings():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    guard = RepetitionStreamGuard()
    assert guard.feed(None) == "" and guard.feed("") == ""


def _lmstudio_stream(text: str, finish: str):
    from agents.core.llm.base import LMStudioBackend

    chunks = [{"choices": [{"delta": {"content": text[i:i + 30]}}]} for i in range(0, len(text), 30)]
    chunks.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    backend = LMStudioBackend("http://lmstudio.invalid")
    backend.client = httpx.AsyncClient(base_url="http://lmstudio.invalid",
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("m", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    return out, "".join(shown)


def test_lmstudio_stream_hides_repetition_loop_live():
    looping = UNALIGNED_TEXT * 4
    out, shown = _lmstudio_stream(looping, "length")
    assert out == ""
    assert len(shown) < len(looping) // 4


def test_lmstudio_stream_shows_ordinary_answer_live():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(60))
    out, shown = _lmstudio_stream(text, "stop")
    assert out == text and shown == text


def test_ollama_stream_hides_repetition_loop_live():
    from agents.core.llm.base import OllamaBackend

    looping = UNALIGNED_TEXT * 4
    lines = [{"response": looping[i:i + 30]} for i in range(0, len(looping), 30)]
    lines.append({"done": True, "done_reason": "length"})
    body = "\n".join(json.dumps(line) for line in lines) + "\n"
    backend = OllamaBackend("http://ollama.invalid")
    backend.client = httpx.AsyncClient(base_url="http://ollama.invalid",
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("m", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == ""
    assert len("".join(shown)) < len(looping) // 4
