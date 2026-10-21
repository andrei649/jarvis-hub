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
import pytest

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


# ── H393 review round 1: every cloud backend, tool turns, late loops ──

_TOOL_CALL = {"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}


class _CapturedPost:
    """Minimal async client: answers every POST with one fixed JSON body."""

    def __init__(self, data):
        self.data = data

    async def post(self, url, json=None, headers=None):
        data = self.data

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return data

        return _Resp()

    async def aclose(self):
        pass


def _openrouter(data):
    from agents.core.llm.openrouter import OpenRouterBackend

    return OpenRouterBackend(api_key="k", client=_CapturedPost(data))


def test_openrouter_generate_drops_truncated_repetition_loop():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "length"}]}
    assert asyncio.run(_openrouter(data).generate("acme/m", "p")) == ""


def test_openrouter_generate_keeps_complete_repetitive_answer():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "stop"}]}
    assert asyncio.run(_openrouter(data).generate("acme/m", "p")) == REPEATED_TEXT


def test_openrouter_stream_fallback_never_paints_a_truncated_loop():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "length"}]}
    shown = []
    out = asyncio.run(_openrouter(data).generate_stream("acme/m", "p", on_token=shown.append))
    assert out == "" and shown == []


def test_openrouter_tool_turn_drops_truncated_loop_but_keeps_calls():
    data = {"choices": [{"message": {"content": REPEATED_TEXT, "tool_calls": [_TOOL_CALL]},
                         "finish_reason": "length"}]}
    turn = asyncio.run(_openrouter(data).generate_tool_turn(
        "acme/m", [{"role": "user", "content": "hi"}], []))
    assert turn.content == "" and len(turn.tool_calls) == 1 and turn.finish_reason == "length"


_DI_BASE = "https://api.deepinfra.com/v1/openai"


def _deepinfra_run(handler, call):
    from agents.core.llm.deepinfra import DeepInfraBackend
    from agents.core.llm.egress import llm_async_client

    async def go():
        client = llm_async_client("deepinfra", base_url=_DI_BASE, trust_env=False,
                                  transport=httpx.MockTransport(handler))
        backend = DeepInfraBackend("deepinfra-key", base_url=_DI_BASE, client=client)
        try:
            return await call(backend)
        finally:
            await backend.aclose()

    return asyncio.run(go())


def test_deepinfra_generate_drops_truncated_repetition_loop():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "length"}]}
    out = _deepinfra_run(lambda req: httpx.Response(200, json=data),
                         lambda b: b.generate("vendor/m", "p"))
    assert out == ""


def test_deepinfra_generate_keeps_complete_repetitive_answer():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "stop"}]}
    out = _deepinfra_run(lambda req: httpx.Response(200, json=data),
                         lambda b: b.generate("vendor/m", "p"))
    assert out == REPEATED_TEXT


def _deepinfra_sse(text: str, finish: str) -> bytes:
    frames = [{"choices": [{"delta": {"content": text[i:i + 30]}}]} for i in range(0, len(text), 30)]
    frames.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    return ("".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n").encode()


def test_deepinfra_stream_drops_truncated_loop_and_hides_it_live():
    looping = UNALIGNED_TEXT * 4
    body = _deepinfra_sse(looping, "length")
    shown = []
    out = _deepinfra_run(
        lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body),
        lambda b: b.generate_stream("vendor/m", "p", on_token=shown.append))
    assert out == ""
    assert len("".join(shown)) < len(looping) // 4


def test_deepinfra_stream_shows_ordinary_answer_live():
    text = "\n".join(f"Step {i}: a distinct instruction, part {i}." for i in range(60))
    body = _deepinfra_sse(text, "length")
    shown = []
    out = _deepinfra_run(
        lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body),
        lambda b: b.generate_stream("vendor/m", "p", on_token=shown.append))
    assert out == text and "".join(shown) == text


def test_deepinfra_tool_turn_drops_truncated_loop():
    data = {"choices": [{"message": {"content": REPEATED_TEXT}, "finish_reason": "length"}]}
    turn = _deepinfra_run(lambda req: httpx.Response(200, json=data),
                          lambda b: b.generate_tool_turn("vendor/m", [{"role": "user", "content": "x"}], []))
    assert turn.content == "" and turn.finish_reason == "length"


def _claude_tool_turn(stop_reason):
    def handler(request):
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": REPEATED_TEXT}],
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    backend = _claude_backend(handler)
    try:
        return asyncio.run(backend.generate_tool_turn(
            "claude-x", [{"role": "user", "content": "hi"}], []))
    finally:
        asyncio.run(backend.client.aclose())


def test_claude_tool_turn_drops_truncated_repetition_loop():
    assert _claude_tool_turn("max_tokens").content == ""


def test_claude_tool_turn_keeps_complete_answer():
    assert _claude_tool_turn("end_turn").content == REPEATED_TEXT


def test_gemini_tool_turn_drops_truncated_repetition_loop():
    body = _gemini_frame(REPEATED_TEXT, "MAX_TOKENS")
    turn = _gemini_run(lambda req: httpx.Response(200, json=body),
                       lambda b: b.generate_tool_turn("gemini-x", [{"role": "user", "content": "hi"}], []))
    assert turn.content == ""


def test_gemini_tool_turn_keeps_complete_answer():
    body = _gemini_frame(REPEATED_TEXT, "STOP")
    turn = _gemini_run(lambda req: httpx.Response(200, json=body),
                       lambda b: b.generate_tool_turn("gemini-x", [{"role": "user", "content": "hi"}], []))
    assert turn.content == REPEATED_TEXT


def _local_run(backend_cls, base, data, call):
    backend = backend_cls(base)
    backend.client = httpx.AsyncClient(base_url=base,
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data)))
    try:
        return asyncio.run(call(backend))
    finally:
        asyncio.run(backend.client.aclose())


def test_lmstudio_tool_turn_with_calls_drops_truncated_loop():
    from agents.core.llm.base import LMStudioBackend

    data = {"choices": [{"message": {"content": REPEATED_TEXT, "tool_calls": [_TOOL_CALL]},
                         "finish_reason": "length"}]}
    turn = _local_run(LMStudioBackend, "http://lmstudio.invalid", data,
                      lambda b: b.generate_tool_turn("m", [{"role": "user", "content": "x"}], []))
    assert turn.content == "" and len(turn.tool_calls) == 1


def test_ollama_tool_turn_drops_truncated_loop():
    from agents.core.llm.base import OllamaBackend

    data = {"message": {"content": REPEATED_TEXT, "thinking": "some reasoning"},
            "done": True, "done_reason": "length"}
    turn = _local_run(OllamaBackend, "http://ollama.invalid", data,
                      lambda b: b.generate_tool_turn("m", [{"role": "user", "content": "x"}], []))
    assert turn.content == ""


def test_ollama_generate_drops_truncated_loop_without_exhaustion_reply():
    from agents.core.llm.base import OllamaBackend

    data = {"response": REPEATED_TEXT, "thinking": "some reasoning", "done": True, "done_reason": "length"}
    out = _local_run(OllamaBackend, "http://ollama.invalid", data, lambda b: b.generate("m", "p"))
    assert out == ""


def test_ollama_generate_keeps_complete_repetitive_answer():
    from agents.core.llm.base import OllamaBackend

    data = {"response": REPEATED_TEXT, "done": True, "done_reason": "stop"}
    out = _local_run(OllamaBackend, "http://ollama.invalid", data, lambda b: b.generate("m", "p"))
    assert out == REPEATED_TEXT


def test_responses_stream_hides_loop_live_but_delivers_complete_answer():
    from agents.core.llm.responses import ResponsesBackend

    looping = UNALIGNED_TEXT * 4
    events = [{"type": "response.output_text.delta", "delta": looping[i:i + 30]}
              for i in range(0, len(looping), 30)]
    events.append({"type": "response.completed", "response": {
        "status": "completed",
        "output": [{"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": looping}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }})
    body = b"".join(("data: " + json.dumps(e) + "\n\n").encode() for e in events)

    async def go():
        backend = ResponsesBackend("fixture-only",
                                   transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body)))
        shown = []
        try:
            out = await backend.generate_stream("gpt-4.1", "p", on_token=shown.append)
        finally:
            await backend.aclose()
        return out, shown

    out, shown = asyncio.run(go())
    assert out == looping.strip()                       # complete (not truncated): delivered
    assert len("".join(shown[:-1])) < len(looping) // 4  # never painted live while generating
    # Once the finalizer keeps the answer, the withheld rest is released so the
    # bubble ends with the same text the answer carries.
    assert "".join(shown) == looping


# A long, varied, legitimate answer that a loop can follow.
_LEGIT = "\n".join(
    f"Paragraph {i}: unique content about topic number {i} with details {i * 7}." for i in range(400)
)


def _late_loop_shown(prefix_len: int, unit: str, step: int = 8) -> int:
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    prefix = _LEGIT[:prefix_len]
    text = prefix + unit * 80
    guard = RepetitionStreamGuard()
    out = "".join(guard.feed(text[i:i + step]) for i in range(0, len(text), step))
    assert guard.tripped is True
    assert out.startswith(prefix)
    return len(out) - len(prefix)


def test_stream_guard_cuts_a_late_loop_after_a_few_repeats():
    unit = "the same sixty-plus character fragment keeps flowing without a break "
    for prefix_len in (0, 1500, 3600, 6000):
        # Was ~34 repeats (2.4 KB) once a long prefix filled the 4000-char tail.
        assert _late_loop_shown(prefix_len, unit) <= 6 * len(unit)


def test_stream_guard_catches_a_long_period_loop():
    unit = "".join(f"Block {i}: a long-period loop body sentence number {i} of the cycle. " for i in range(8))
    assert len(unit) > 500
    # Was never caught live: a 520-char period never reached the tail's dominance ratio.
    assert _late_loop_shown(3600, unit) <= 6 * len(unit)


def test_stream_guard_lets_structured_but_varied_text_through():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    table = "| Name | Value |\n|------|-------|\n" + "".join(f"| row {i} | {i * 3} |\n" for i in range(200))
    code = "".join(f"    result.append(compute(item_{i}, factor={i}))\n" for i in range(80))
    rule = "-" * 80 + "\n"
    text = "Intro.\n" + table + rule + code + rule + "Done."
    guard = RepetitionStreamGuard()
    out = "".join(guard.feed(text[i:i + 5]) for i in range(0, len(text), 5))
    assert out == text and guard.tripped is False


def test_horizontal_rules_do_not_count_as_repetition():
    # Two 80-dash markdown rules: the 60-char window recurs at 21 offsets inside
    # each rule. Overlapping occurrences must not be scored as coverage.
    body = "\n".join(f"Line {i}: varied prose about subject {i} and its outcome {i * 11}." for i in range(50))
    text = body + "\n" + "-" * 80 + "\n" + body.upper() + "\n" + "-" * 80 + "\nEnd."
    assert len(text) > 4000
    assert is_repetition_dominated(text[-4000:]) is False
    assert LLMBackend._finalize_cloud(text, "length", "m") == text.strip()


# ── H393 review round 2: loops with a period shorter than the 60-char window ──

# Varied prose with no 60-char repeat and no line breaks.
_PROSE = " ".join(
    f"Sentence {i} talks about item {i * 13} and its result {i * 7 + 3} in plain words." for i in range(400)
)


def _sentence_unit(period: int) -> str:
    base = "Let me check the configuration file again to verify it all works out fine. "
    return base[: period - 1] + " "


def _prose_then_loop(n: int, period: int, share: float) -> str:
    unit = _sentence_unit(period)
    assert len(unit) == period and "\n" not in unit
    loop_len = int(n * share)
    loop = (unit * (loop_len // period + 1))[:loop_len]
    return _PROSE[: n - loop_len] + loop


def test_short_period_no_newline_loops_are_repetition_dominated():
    # Round-1 regression: counting only NON-overlapping 60-char windows credited
    # a loop of period 31..59 with ~60 chars per ~2 periods, so these returned
    # False (base and Hermes both catch them).
    for n in (4000, 6000):
        for period in (25, 41, 45, 47, 53, 55, 59):
            for share in (0.6, 0.75, 0.9):
                text = _prose_then_loop(n, period, share)
                assert is_repetition_dominated(text) is True, (n, period, share)


def test_finalize_cloud_drops_truncated_short_period_loop():
    for period in (41, 47, 53, 59):
        text = _prose_then_loop(4000, period, 0.65)
        assert LLMBackend._finalize_cloud(text, "length", "m") == "", period
        # A complete answer is never touched.
        assert LLMBackend._finalize_cloud(text, "stop", "m") == text.strip()


def test_finalize_stream_drops_truncated_short_period_loop():
    text = _prose_then_loop(6000, 55, 0.9)
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""


def test_deepinfra_generate_drops_truncated_short_period_loop():
    text = _prose_then_loop(6000, 55, 0.75)
    data = {"choices": [{"message": {"content": text}, "finish_reason": "length"}]}
    out = _deepinfra_run(lambda req: httpx.Response(200, json=data),
                         lambda b: b.generate("vendor/m", "p"))
    assert out == ""


def test_prose_minority_loop_follows_the_hermes_trigger():
    # Round-3 regression: round 2 scored union coverage only, so a period-25
    # loop covering 35% was kept although base/Hermes (overlapping occurrence
    # count >= ceil(n*0.5/60)) drops it.
    for period in (25, 45, 59):
        text = _prose_then_loop(4000, period, 0.35)
        assert is_repetition_dominated(text) is _hermes_dominated(text), period
    assert is_repetition_dominated(_prose_then_loop(4000, 25, 0.35)) is True


# ── H393 review round 2: formatting runs must stream through in full ──

_TAIL_PROSE = "\n\nThat is the whole layout. " + " ".join(
    f"Note {i}: the field at offset {i * 4} holds value {i * 9 + 1}." for i in range(30)
)
_ZERO_MATRIX = "```python\nm = [\n" + "".join(
    "    [" + ", ".join(["0"] * 16) + "],\n" for _ in range(16)) + "]\n```"
_BYTE_ARRAY = "static const uint8_t buf[256] = {\n" + "".join(
    "    " + ", ".join(["0x00"] * 12) + ",\n" for _ in range(12)) + "};"
_UNDERLINE = "Results\n" + "=" * 320


def _stream_through(text: str, step: int = 8):
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    guard = RepetitionStreamGuard()
    live = "".join(guard.feed(text[i:i + step]) for i in range(0, len(text), step))
    return guard, live


def test_formatting_runs_followed_by_prose_stream_in_full():
    for block in (_ZERO_MATRIX, _BYTE_ARRAY, _UNDERLINE):
        text = "Here it is:\n" + block + _TAIL_PROSE
        guard, live = _stream_through(text)
        # Round 1 tripped on all three (the onset detector took a period-1..4
        # run as a loop) and dropped every later chunk, prose included.
        assert live + guard.release(text) == text, block[:20]
        assert guard.tripped is False, block[:20]


def test_lmstudio_stream_shows_zero_matrix_and_trailing_prose_in_full():
    text = "Here it is:\n" + _ZERO_MATRIX + _TAIL_PROSE
    out, shown = _lmstudio_stream(text, "stop")
    assert out == text and shown == text


def test_deepinfra_stream_shows_byte_array_and_trailing_prose_in_full():
    text = "Here it is:\n" + _BYTE_ARRAY + _TAIL_PROSE
    body = _deepinfra_sse(text, "stop")
    shown = []
    out = _deepinfra_run(
        lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body),
        lambda b: b.generate_stream("vendor/m", "p", on_token=shown.append))
    assert out == text and "".join(shown) == text


def test_claude_stream_shows_underline_and_trailing_prose_in_full():
    text = "Here it is:\n" + _UNDERLINE + _TAIL_PROSE
    body = _claude_stream_body(text, "end_turn")
    backend = _claude_backend(lambda req: httpx.Response(200, text=body))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("claude-x", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == text and "".join(shown) == text


def test_stream_guard_release_returns_withheld_text_only_when_kept():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    text = _LEGIT[:1500] + UNALIGNED_TEXT * 3
    guard, live = _stream_through(text)
    assert guard.tripped is True and len(live) < len(text)
    assert live + guard.release(text) == text      # kept: rest is released
    assert guard.release(text) == ""               # released once

    guard, live = _stream_through(text)
    assert guard.release("") == ""                 # dropped: nothing more shown
    assert guard.release(text) == ""


def test_complete_loop_is_released_after_finalize_on_lmstudio():
    # Hidden while generating, but a complete answer is delivered in full, so
    # the live bubble must end with the same text (round-1 inconsistency).
    looping = UNALIGNED_TEXT * 4
    out, shown = _lmstudio_stream(looping, "stop")
    assert out == looping.strip() and shown == looping


def test_truncated_loop_withheld_text_is_never_released_on_ollama():
    test_ollama_stream_hides_repetition_loop_live()


def test_onset_detector_ignores_loops_inside_an_open_code_fence():
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    row = "    assert compute(value) == expected_value_for_this_row  # check\n"
    intro = _LEGIT[:1200] + "\nTests:\n"
    text = intro + "```python\n" + row * 6 + "```\nAll rows above are the same check."
    guard = RepetitionStreamGuard()
    live = "".join(guard.feed(text[i:i + 8]) for i in range(0, len(text), 8))
    assert live == text and guard.tripped is False
    # The same rows outside a fence are a loop onset.
    guard = RepetitionStreamGuard()
    plain = intro + row * 6
    live = "".join(guard.feed(plain[i:i + 8]) for i in range(0, len(plain), 8))
    assert guard.tripped is True


def test_onset_detector_still_cuts_a_sentence_loop_with_period_under_60():
    unit = _sentence_unit(41)
    assert _late_loop_shown(3600, unit) <= 6 * len(unit) + 60


def test_low_variety_flood_is_still_cut_live_once_it_fills_the_tail():
    from agents.core.llm.repetition_guard import _STREAM_TAIL

    text = _LEGIT[:800] + "0, " * 20000
    guard, live = _stream_through(text, step=16)
    assert guard.tripped is True
    assert len(live) < 800 + _STREAM_TAIL + 400
    assert guard.release("") == ""


def test_min_distinct_only_relaxes_the_live_check():
    flood = "Results:\n" + "=" * 3000
    assert is_repetition_dominated(flood) is True                 # finalizers: unchanged
    assert is_repetition_dominated(flood, min_distinct=8) is False
    assert is_repetition_dominated(UNALIGNED_TEXT, min_distinct=8) is True
    assert is_repetition_dominated(REPEATED_TEXT, min_distinct=8) is True


# ── H393 review round 3: Hermes parity for short-period loops below 50% ──

def _hermes_dominated(text: str) -> bool:
    """The verbatim Hermes ``is_repetition_dominated`` (the merge-base port)."""
    import math

    from agents.core.llm.repetition_guard import _line_repetition_dominated

    n = len(text)
    if n < 400:
        return False
    if _line_repetition_dominated(text, n):
        return True
    needed = max(5, math.ceil(n * 0.5 / 60))
    counts: dict[str, int] = {}
    for i in range(n - 60 + 1):
        key = text[i:i + 60]
        c = counts.get(key, 0) + 1
        if c >= needed:
            return True
        counts[key] = c
    return False


def _prose_then_unit_loop(n: int, unit: str, share: float) -> str:
    loop_len = int(n * share)
    loop = (unit * (loop_len // len(unit) + 1))[:loop_len]
    return _PROSE[: n - loop_len] + loop


_R3_UNITS = (
    "I'm sorry ",                         # p=10
    "the ",                               # p=4
    "Let me check that file again. ",     # p=30
    "Wait, let me rethink it. ",          # p=25
)


@pytest.mark.parametrize("unit", _R3_UNITS)
@pytest.mark.parametrize("share", (0.3, 0.45))
@pytest.mark.parametrize("n", (4000, 8000))
def test_truncated_short_period_minority_loop_is_dropped(unit, share, n):
    text = _prose_then_unit_loop(n, unit, share)
    assert _hermes_dominated(text) is True          # what the port drops
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""
    assert LLMBackend._finalize_cloud(text, "length", "m") == ""
    # A complete answer is never touched.
    assert LLMBackend._finalize_cloud(text, "stop", "m") == text.strip()


def _random_unit(period: int, seed: int) -> str:
    import random

    rng = random.Random(seed * 1000 + period)  # nosec B311
    alphabet = "abcdefghijklmnopqrstuvwxyz ,.'"
    return "".join(rng.choice(alphabet) for _ in range(period))


def test_detector_is_a_superset_of_the_hermes_port():
    misses = []
    for n in (1000, 4000):
        for period in range(5, 60, 3):
            for share in (0.15, 0.25, 0.35, 0.45, 0.6, 0.75, 0.9):
                for unit in (_random_unit(period, 1), _random_unit(period, 2), _sentence_unit(period)):
                    if len(set(unit)) <= 2:
                        continue   # low-variety rule inputs are the one sanctioned exemption
                    text = _prose_then_unit_loop(n, unit, share)
                    if _hermes_dominated(text) and not is_repetition_dominated(text):
                        misses.append((n, period, share, unit))
    assert misses == []


def test_detector_matches_hermes_on_the_reviewer_grid():
    for n in (2000, 4000, 6000):
        for period in (10, 20, 25, 30, 40):
            for share in (0.25, 0.35, 0.45):
                text = _prose_then_loop(n, period, share)
                if _hermes_dominated(text):
                    assert is_repetition_dominated(text) is True, (n, period, share)
                    assert LLMBackend._finalize_cloud(text, "length", "m") == ""


def test_horizontal_rules_stay_exempt_while_hermes_trips_on_them():
    body = "\n".join(f"Line {i}: varied prose about subject {i} and its outcome {i * 11}." for i in range(50))
    text = (body + "\n" + "-" * 80 + "\n" + body.upper() + "\n" + "-" * 80 + "\nEnd.")[-4000:]
    assert _hermes_dominated(text) is True          # the port's false positive
    assert is_repetition_dominated(text) is False


def _claude_stream_body_no_stop(text: str) -> str:
    events = [{"type": "message_start", "message": {"usage": {"input_tokens": 1}}}]
    events += [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": text[i:i + 40]}}
               for i in range(0, len(text), 40)]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


def test_claude_stream_clean_eof_without_message_stop_releases_held_text():
    # The stream ends cleanly with no message_stop: the answer is the full text
    # (no sentinel), so the live bubble must end with that same text.
    looping = UNALIGNED_TEXT * 4
    body = _claude_stream_body_no_stop(looping)
    backend = _claude_backend(lambda req: httpx.Response(200, text=body))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("claude-x", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out == looping.strip()
    assert "".join(shown) == looping


def test_claude_stream_error_after_trip_never_releases_held_text():
    looping = UNALIGNED_TEXT * 4
    body = _claude_stream_body_no_stop(looping)

    class Cut(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield body.encode()
            raise httpx.ReadError("cut")

    backend = _claude_backend(lambda req: httpx.Response(200, stream=Cut()))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("claude-x", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    assert out.startswith("[Claude API stream error")
    assert len("".join(shown)) < len(looping) // 2


# ── H393 review round 4: the live guard agrees with the finalizer on short loops ──

# Short-period / low-distinct loops the finalizers drop (Hermes count) but the
# round-3 live guard never tripped on in a stream under the 4000-char tail.
_R4_LIVE_UNITS = _R3_UNITS + ("ha ha ", "0, ")


@pytest.mark.parametrize("unit", _R4_LIVE_UNITS)
@pytest.mark.parametrize("share", (0.3, 0.45))
@pytest.mark.parametrize("n", (2000, 3105))
def test_short_period_truncated_loop_is_not_painted_live(unit, share, n):
    from agents.core.llm.repetition_guard import _STREAM_MIN_LOOP_SPAN

    text = _prose_then_unit_loop(n, unit, share)
    prefix_len = n - int(n * share)
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""
    guard, live = _stream_through(text, step=5)
    assert guard.withholding is True
    assert text.startswith(live)
    # Only the loop's first few hundred characters ever reach the bubble.
    assert len(live) <= prefix_len + _STREAM_MIN_LOOP_SPAN + 5, (len(live), prefix_len)
    assert guard.release("") == ""


@pytest.mark.parametrize("unit", _R4_LIVE_UNITS)
def test_short_period_loop_held_text_is_released_when_kept(unit):
    text = _prose_then_unit_loop(3000, unit, 0.4)
    guard, live = _stream_through(text, step=5)
    assert len(live) < len(text)
    assert live + guard.release(text) == text


def _ollama_stream(text: str, done_reason: str):
    from agents.core.llm.base import OllamaBackend

    lines = [{"response": text[i:i + 6]} for i in range(0, len(text), 6)]
    lines.append({"done": True, "done_reason": done_reason})
    body = "\n".join(json.dumps(line) for line in lines) + "\n"
    backend = OllamaBackend("http://ollama.invalid")
    backend.client = httpx.AsyncClient(base_url="http://ollama.invalid",
                                       transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    shown = []
    try:
        out = asyncio.run(backend.generate_stream("m", "p", on_token=shown.append))
    finally:
        asyncio.run(backend.client.aclose())
    return out, "".join(shown)


@pytest.mark.parametrize("unit", ("the ", "I'm sorry ", "ha ha "))
def test_ollama_stream_short_period_truncated_loop_never_painted(unit):
    text = _prose_then_unit_loop(3105, unit, 0.5)
    out, shown = _ollama_stream(text, "length")
    assert out == ""
    loop = text[3105 - int(3105 * 0.5):]
    assert loop not in shown and len(shown) < len(text) - 1000


@pytest.mark.parametrize("unit", ("the ", "0, "))
def test_lmstudio_stream_short_period_truncated_loop_never_painted(unit):
    text = _prose_then_unit_loop(3000, unit, 0.35)
    out, shown = _lmstudio_stream(text, "length")
    assert out == ""
    assert len(shown) < len(text) - 600


def test_short_run_hold_resumes_and_flushes_when_prose_follows():
    # A 600-char periodic run inside a normal answer is held only while it
    # runs; once prose follows, it is flushed and streaming continues live.
    text = _PROSE[:1500] + "\n" + "0, " * 200 + "\n" + _PROSE[1500:3500]
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


def _matrix_answer(run: str) -> str:
    words = " ".join(f"word{i} item{i * 3} value{i * 7}" for i in range(600))
    return words[:3000] + "\n" + run + "\n" + words[3000:6000]


def test_small_zero_matrix_late_in_a_long_answer_streams_live_in_full():
    # Round-3 regression: the full-tail check used the Hermes overlapping count,
    # so a 240-char zero matrix past the first 4000 chars tripped the guard.
    text = _matrix_answer("[" + ", ".join(["0"] * 80) + "]")
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False
    assert live == text


def test_table_separator_run_late_in_a_long_answer_streams_live_in_full():
    text = _matrix_answer("| --- " * 50 + "|")
    assert len("| --- " * 50) == 300
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False
    assert live == text


def test_live_full_tail_check_is_coverage_only():
    tail = _matrix_answer("[" + ", ".join(["0"] * 80) + "]")[-4000:]
    assert is_repetition_dominated(tail) is True                    # finalizers: Hermes count
    assert is_repetition_dominated(tail, count_trigger=False) is False


# Low-variety (<= 2 distinct chars) loops: the exemption covers rule-length
# runs only (< 2 windows), so a real "hahaha" / newline / "0 0 0" flood
# follows Hermes.
_R4_LOW_VARIETY_UNITS = ("ha", "0 ", "!", "\n", "- ", "=")


@pytest.mark.parametrize("unit", _R4_LOW_VARIETY_UNITS)
@pytest.mark.parametrize("share", (0.1, 0.25, 0.45))
@pytest.mark.parametrize("n", (1000, 4000))
def test_low_variety_loops_follow_the_hermes_trigger(unit, share, n):
    text = _prose_then_unit_loop(n, unit, share)
    loop_len = int(n * share)
    assert _hermes_dominated(text) is True
    if loop_len >= 120:     # a run of two windows or more is a loop, not a rule
        assert is_repetition_dominated(text) is True, (unit, share, n)
        if unit.strip():   # a trailing newline flood is already stripped as whitespace
            assert LLMBackend._finalize_cloud(text, "length", "m") == ""
    else:                  # rule-length run (here: 100 chars) stays exempt
        assert is_repetition_dominated(text) is False


def test_rule_length_low_variety_runs_stay_exempt():
    # Several 80-char rules: each run is shorter than two windows.
    body = "\n".join(f"Line {i}: varied prose about subject {i} and its outcome {i * 11}." for i in range(12))
    text = ("\n" + "=" * 80 + "\n").join([body, body.upper(), body.lower(), body.title()])
    assert _hermes_dominated(text) is True
    assert is_repetition_dominated(text) is False


# ── H393 review round 5: loops the 4000-char tail cannot see ──
#
# The onset detector caps the period at len(tail) // 5 = 800 and the short-loop
# hold at 60, so (a) a paragraph line repeated with a period over 800 and (b) a
# low-variety row (fewer than 8 distinct characters) with a period of 61..800
# were painted live in full while the finalizer dropped the truncated answer.

_R5_PROSE_PREFIX = (
    "Sure, here is a summary of the incident report together with the main follow-up actions "
    "we agreed on during the review meeting.\n"
)


def _paragraph_line(period: int, seed: int = 7) -> str:
    import random

    rng = random.Random(seed * 10007 + period)  # nosec B311
    words = ("system", "review", "network", "storage", "latency", "budget", "report", "update",
             "service", "cluster", "deploy", "config", "monitor", "rollback", "release", "metric")
    out = ""
    while len(out) < period:
        out += rng.choice(words) + (", " if rng.random() < 0.15 else " ")
    return out[: period - 1] + "."


def _paragraph_loop(period: int, total: int = 30000) -> str:
    line = _paragraph_line(period)
    assert len(line) == period and "\n" not in line
    body = ""
    while len(_R5_PROSE_PREFIX) + len(body) < total:
        body += line + "\n"
    return _R5_PROSE_PREFIX + body


@pytest.mark.parametrize("period", (500, 900, 1200, 2000, 3000))
def test_long_period_paragraph_loop_is_not_painted_live(period):
    text = _paragraph_loop(period)
    assert is_repetition_dominated(text) is True          # what the finalizer drops
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""
    guard, live = _stream_through(text, step=7)
    assert guard.withholding is True
    assert text.startswith(live)
    assert len(live) <= len(_R5_PROSE_PREFIX) + 6 * period, (len(live), period)
    assert guard.release("") == ""


@pytest.mark.parametrize("period", (900, 2000))
def test_long_period_paragraph_loop_with_blank_lines_is_not_painted_live(period):
    line = _paragraph_line(period, seed=3)
    text = _R5_PROSE_PREFIX + (line + "\n\n") * (30000 // period)
    assert is_repetition_dominated(text) is True
    guard, live = _stream_through(text, step=7)
    assert guard.withholding is True
    assert len(live) <= len(_R5_PROSE_PREFIX) + 6 * (period + 2)
    assert guard.release("") == ""


def test_long_period_loop_is_released_when_the_answer_is_kept():
    text = _paragraph_loop(1200)
    guard, live = _stream_through(text, step=7)
    assert len(live) < len(text)
    assert live + guard.release(text) == text


@pytest.mark.parametrize("period", (900, 2000))
def test_ollama_stream_long_period_truncated_loop_never_painted(period):
    text = _paragraph_loop(period)
    out, shown = _ollama_stream(text, "length")
    assert out == ""
    assert len(shown) <= len(_R5_PROSE_PREFIX) + 6 * period


@pytest.mark.parametrize("period", (900, 2000))
def test_lmstudio_stream_long_period_truncated_loop_never_painted(period):
    text = _paragraph_loop(period)
    out, shown = _lmstudio_stream(text, "length")
    assert out == ""
    assert len(shown) <= len(_R5_PROSE_PREFIX) + 6 * period


@pytest.mark.parametrize("copies", (2, 3, 4))
def test_long_line_repeated_a_few_times_streams_in_full(copies):
    line = _paragraph_line(900, seed=11)
    # Back to back, and spread through a varied answer.
    for text in (
        _R5_PROSE_PREFIX + (line + "\n") * copies + "That is all.",
        _LEGIT[:2000] + "\n" + ("\n" + _LEGIT[2000:2600] + "\n").join([line] * copies) + "\nEnd.",
    ):
        guard, live = _stream_through(text, step=7)
        assert guard.tripped is False and guard.withholding is False
        assert live == text


def test_long_line_repeated_inside_a_code_fence_streams_in_full():
    line = "    " + _paragraph_line(900, seed=5).replace(".", ";")
    text = _LEGIT[:6000] + "\n```text\n" + (line + "\n") * 6 + "```\n" + _LEGIT[6000:9000]
    assert is_repetition_dominated(text) is False
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


# Low-variety rows (< 8 distinct chars) with a period over 60.
_R5_LOW_VARIETY_ROWS = (
    "[" + ", ".join(["0"] * 22) + "],\n",
    "| 0 |" * 16 + "\n",
    "ha " * 23 + "\n",
    "-" * 79 + "\n",
)
_R5_SHORT_PROSE = "Here is the result you asked for, computed from the inputs shown above:\n"


def _low_variety_row_loop(row: str, total: int = 8000) -> str:
    return _R5_SHORT_PROSE + row * ((total - len(_R5_SHORT_PROSE)) // len(row) + 1)


@pytest.mark.parametrize("row", _R5_LOW_VARIETY_ROWS)
def test_low_variety_row_loop_is_not_painted_live(row):
    period = len(row)
    assert period > 60 and len(set(row)) < 8
    text = _low_variety_row_loop(row)
    assert is_repetition_dominated(text) is True
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""
    guard, live = _stream_through(text, step=4)
    assert guard.withholding is True
    assert text.startswith(live)
    assert len(live) <= len(_R5_SHORT_PROSE) + 5 * period + 8, (len(live), period)
    assert guard.release("") == ""


@pytest.mark.parametrize("row", _R5_LOW_VARIETY_ROWS)
def test_low_variety_row_hold_is_released_when_kept(row):
    text = _low_variety_row_loop(row)
    guard, live = _stream_through(text, step=4)
    assert live + guard.release(text) == text


def test_thirty_row_zero_matrix_followed_by_prose_streams_in_full():
    row = _R5_LOW_VARIETY_ROWS[0]
    text = _R5_SHORT_PROSE + row * 30 + "\nEach row is one sensor; all of them read zero today. " + _PROSE[:1500]
    guard, live = _stream_through(text, step=4)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


@pytest.mark.parametrize("row", (_R5_LOW_VARIETY_ROWS[0], _R5_LOW_VARIETY_ROWS[1]))
def test_ollama_stream_low_variety_row_loop_never_painted(row):
    text = _low_variety_row_loop(row)
    out, shown = _ollama_stream(text, "length")
    assert out == ""
    assert len(shown) <= len(_R5_SHORT_PROSE) + 5 * len(row) + 8


@pytest.mark.parametrize("row", (_R5_LOW_VARIETY_ROWS[2], _R5_LOW_VARIETY_ROWS[3]))
def test_lmstudio_stream_low_variety_row_loop_never_painted(row):
    text = _low_variety_row_loop(row)
    out, shown = _lmstudio_stream(text, "length")
    assert out == ""
    assert len(shown) <= len(_R5_SHORT_PROSE) + 5 * len(row) + 32


def test_lmstudio_stream_zero_matrix_then_prose_is_shown_in_full():
    row = _R5_LOW_VARIETY_ROWS[0]
    text = _R5_SHORT_PROSE + row * 30 + "\nAll sensors read zero. " + _PROSE[:800]
    out, shown = _lmstudio_stream(text, "stop")
    assert out == text and shown == text


def _bit_line(length: int, seed: int) -> str:
    import random

    rng = random.Random(seed)  # nosec B311
    return "".join(rng.choice("01 ") for _ in range(length))


def test_long_low_variety_line_loop_is_held_not_painted():
    # A low-variety line longer than the tail can see (period > 800), with no
    # short internal period: the long-line HOLD keeps it off the bubble.
    line = _bit_line(1100, 4)
    assert len(set(line)) < 8
    text = _R5_SHORT_PROSE + (line + "\n") * 25
    assert is_repetition_dominated(text) is True
    guard, live = _stream_through(text, step=5)
    assert guard.tripped is False and guard.withholding is True
    assert len(live) <= len(_R5_SHORT_PROSE) + 5 * (len(line) + 1) + 5
    assert guard.release("") == ""
    guard, live = _stream_through(text, step=5)
    assert live + guard.release(text) == text


@pytest.mark.parametrize("after", ("\nA short note.\n", "\nThat is the dump of every register in the device, as requested.\n"))
def test_long_low_variety_line_hold_lifts_when_a_different_line_completes(after):
    line = _bit_line(1100, 9)
    text = _R5_SHORT_PROSE + (line + "\n") * 6 + after
    guard, live = _stream_through(text, step=5)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


def test_line_detector_judges_each_line_with_its_own_fence_state():
    # The chunk that completes the 6th fenced copy also closes the fence: that
    # line is still inside the fence, so it is not a loop onset.
    line = _paragraph_line(900, seed=5)
    text = _LEGIT[:6000] + "\n```\n" + (line + "\n") * 6 + "```\n" + _LEGIT[6000:9000]
    from agents.core.llm.repetition_guard import RepetitionStreamGuard

    head = text.index("```\n" + _LEGIT[6000:6010], 6010)
    guard = RepetitionStreamGuard()
    live = guard.feed(text[:head - 2]) + guard.feed(text[head - 2:head + 6]) + guard.feed(text[head + 6:])
    assert guard.tripped is False and live == text


def test_line_detector_handles_crlf_and_memory_stays_bounded(monkeypatch):
    from agents.core.llm import repetition_guard as rg

    line = _paragraph_line(900, seed=2)
    text = _R5_SHORT_PROSE + (line + "\r\n") * 10
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is True and len(live) <= len(_R5_SHORT_PROSE) + 6 * 902

    assert rg._STREAM_LINE_SLOTS == 4096
    monkeypatch.setattr(rg, "_STREAM_LINE_SLOTS", 64)
    guard = rg.RepetitionStreamGuard()
    for i in range(300):
        guard.feed(f"{i}: " + _paragraph_line(70, seed=i) + "\n")
    assert len(guard._lines.counts) == 64 and guard.tripped is False


def test_long_varied_answer_with_repeated_boilerplate_streams_in_full():
    # The same 70-char disclaimer under every section (never back to back, never
    # half the output) is ordinary formatting.
    note = "Note: figures in this section are estimates and may change later on."
    sections = [f"## Section {i}\n" + _LEGIT[i * 900:(i + 1) * 900] + "\n" + note + "\n" for i in range(12)]
    text = "".join(sections)
    guard, live = _stream_through(text, step=6)
    assert guard.tripped is False and live == text


# ── H393 review round 6: multi-line loop units with a period over 800 ──
#
# The round-5 line detector only knew single-line runs: any other non-blank
# line between two copies (a "**Note:**" heading, a "---" rule, a second line
# of the unit) reset the run, so after a long legitimate prefix only the
# whole-stream dominance trip fired — once the loop had painted roughly as much
# text as the prefix (10k-40k chars) live, although the finalizer drops it.


def _r6_prefix(n: int) -> str:
    return _LEGIT[:n].rsplit("\n", 1)[0] + "\n"


def _r6_units():
    a, b = _paragraph_line(700, seed=21), _paragraph_line(150, seed=22)
    units = [(f"note+{p}", "**Note:**\n" + _paragraph_line(p, seed=p) + "\n") for p in (900, 1500, 3000)]
    units.append(("A700+B150", a + "\n" + b + "\n"))
    line = _paragraph_line(1000, seed=31)
    for name, sep in (("rule", "\n\n---\n\n"), ("heading", "\n\n## Summary\n\n"), ("stars", "\n* * *\n")):
        units.append((name, line + sep))
    return units


def _r6_loop(prefix_len: int, unit: str) -> tuple[str, str]:
    prefix = _r6_prefix(prefix_len)
    return prefix, prefix + unit * (3 * len(prefix) // len(unit) + 6)


@pytest.mark.parametrize("name,unit", _r6_units(), ids=[u[0] for u in _r6_units()])
@pytest.mark.parametrize("prefix_len", (8000, 10000, 20000))
def test_multi_line_long_period_loop_after_long_prefix_is_not_painted_live(name, unit, prefix_len):
    prefix, text = _r6_loop(prefix_len, unit)
    assert is_repetition_dominated(text) is True                      # the finalizer drops it
    assert LLMBackend._finalize_stream(text, "", "length", "m") == ""
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is True and guard.withholding is True
    assert text.startswith(live) and live.startswith(prefix)
    assert len(live) - len(prefix) <= 6 * len(unit), (name, len(live) - len(prefix), len(unit))
    assert guard.release("") == ""


def test_multi_line_loop_is_released_when_the_answer_is_kept():
    prefix, text = _r6_loop(10000, _r6_units()[0][1])
    guard, live = _stream_through(text, step=7)
    assert len(live) < len(text)
    assert live + guard.release(text) == text


@pytest.mark.parametrize("name,unit", (_r6_units()[0], _r6_units()[3], _r6_units()[4]))
def test_ollama_stream_multi_line_truncated_loop_never_painted(name, unit):
    prefix, text = _r6_loop(10000, unit)
    out, shown = _ollama_stream(text, "length")
    assert out == ""
    assert shown.startswith(prefix) and len(shown) - len(prefix) <= 6 * len(unit)


@pytest.mark.parametrize("name,unit", (_r6_units()[1], _r6_units()[3], _r6_units()[5]))
def test_lmstudio_stream_multi_line_truncated_loop_never_painted(name, unit):
    prefix, text = _r6_loop(10000, unit)
    out, shown = _lmstudio_stream(text, "length")
    assert out == ""
    assert shown.startswith(prefix) and len(shown) - len(prefix) <= 6 * len(unit)


def test_per_section_boilerplate_repeated_with_varied_content_streams_in_full():
    # A long disclaimer + heading repeated under 4 sections, with different
    # content between the copies: never a back-to-back multi-line unit.
    note = "**Note:**\n" + _paragraph_line(900, seed=41) + "\n"
    text = "".join(f"## Section {i}\n" + _LEGIT[i * 700:(i + 1) * 700] + "\n" + note for i in range(4))
    text += "That is the full report."
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


@pytest.mark.parametrize("copies", (2, 3, 4))
def test_multi_line_unit_repeated_a_few_times_streams_in_full(copies):
    unit = "**Note:**\n" + _paragraph_line(900, seed=43) + "\n"
    text = _r6_prefix(10000) + unit * copies + "That is all."
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


def test_multi_line_unit_inside_a_code_fence_streams_in_full():
    a = "    " + _paragraph_line(700, seed=51).replace(".", ";")
    b = "    " + _paragraph_line(150, seed=52).replace(".", ";")
    text = _LEGIT[:12000] + "\n```text\n" + (a + "\n" + b + "\n") * 6 + "```\n" + _LEGIT[12000:15000]
    assert is_repetition_dominated(text) is False
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


def test_long_line_interleaved_with_distinct_short_lines_inside_fence_streams_in_full():
    line = "    " + _paragraph_line(900, seed=53).replace(".", ";")
    body = "".join(f"# step {i}\n{line}\n" for i in range(5))
    text = _LEGIT[:12000] + "\n```text\n" + body + "```\n" + _LEGIT[12000:15000]
    guard, live = _stream_through(text, step=7)
    assert guard.tripped is False and guard.withholding is False
    assert live == text


def test_multi_line_low_variety_loop_is_held_not_tripped():
    # A low-variety two-line unit (no line with 8+ distinct chars) over 800
    # chars: may be formatting, so it is HELD (recoverable), never tripped.
    a, b = _bit_line(700, 61), _bit_line(200, 62)
    unit = a + "\n" + b + "\n"
    text = _R5_SHORT_PROSE + unit * 20
    assert is_repetition_dominated(text) is True
    guard, live = _stream_through(text, step=5)
    assert guard.tripped is False and guard.withholding is True
    assert len(live) <= len(_R5_SHORT_PROSE) + 6 * len(unit)
    assert live + guard.release(text) == text
    text2 = _R5_SHORT_PROSE + unit * 6 + "And that is the register dump you asked for, in full.\n"
    guard, live = _stream_through(text2, step=5)
    assert guard.withholding is False and live == text2
