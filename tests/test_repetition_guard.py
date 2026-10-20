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
