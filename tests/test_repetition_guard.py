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
        return out, "".join(shown)

    out, shown = asyncio.run(go())
    assert out == looping.strip()              # complete (not truncated): delivered
    assert len(shown) < len(looping) // 4      # but never painted live in full


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
