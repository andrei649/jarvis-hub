"""H277 native Gemini normalization through the signed video consumer."""

from __future__ import annotations

import json

import httpx
import pytest

from agents.core.llm.egress import llm_async_client
from agents.core.llm.video_native import VideoNativeEmpty, VideoNativeRefused, gemini_video_answer
from tests.test_h277_video_analysis import rig
from tests.test_h277_video_gemini import _approved, _grant, _local_gemini


def _response(parts, **candidate_fields):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": parts},
                            **candidate_fields}]}


def test_native_visible_text_wins_over_thought_and_filters_inline_thinking():
    payload = _response([
        {"text": "private rationale", "thought": True, "thoughtSignature": "opaque-signature"},
        {"text": "<think>private inline</think>Visible answer."},
    ])
    assert gemini_video_answer(payload) == "Visible answer."


def test_native_thought_text_supplies_answer_only_when_visible_is_blank():
    payload = _response([
        {"text": " First obser", "thought": True, "thoughtSignature": "opaque-signature"},
        {"text": "vation.", "thought": True},
        {"text": "  "},
    ])
    assert gemini_video_answer(payload) == "First observation."


def test_native_thought_fragments_form_one_thinking_tag_before_filtering():
    payload = _response([
        {"text": "<thi", "thought": True},
        {"text": "nk>private</think>Recovered.", "thought": True},
        {"text": ""},
    ])
    assert gemini_video_answer(payload) == "Recovered."


def test_native_nonblank_inline_thinking_without_answer_is_terminal():
    with pytest.raises(VideoNativeRefused) as exc:
        gemini_video_answer(_response([{"text": "<think>private</think>"}]))
    assert type(exc.value) is VideoNativeRefused


@pytest.mark.parametrize("parts", [
    [{"text": "  "}],
    [{"text": " ", "thought": True}, {"text": "\n"}],
])
def test_native_truly_blank_typed_text_remains_recoverable_empty(parts):
    with pytest.raises(VideoNativeEmpty):
        gemini_video_answer(_response(parts))


@pytest.mark.parametrize("location", ["top", "feedback", "candidate", "content", "part"])
def test_native_explicit_error_envelope_is_terminal_even_with_visible_answer(location):
    payload = _response([{"text": "visible"}])
    if location == "top":
        payload["error"] = {"message": "private"}
    elif location == "feedback":
        payload["promptFeedback"] = {"error": {"message": "private"}}
    elif location == "candidate":
        payload["candidates"][0]["error"] = {"message": "private"}
    elif location == "content":
        payload["candidates"][0]["content"]["error"] = {"message": "private"}
    else:
        payload["candidates"][0]["content"]["parts"][0]["error"] = {"message": "private"}
    with pytest.raises(VideoNativeRefused) as exc:
        gemini_video_answer(payload)
    assert type(exc.value) is VideoNativeRefused
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("invalid_part", [
    {"thought": True, "functionCall": {"name": "internal"}},
    {"text": "hidden", "thought": True, "functionCall": {"name": "internal"}},
    {"text": "hidden", "thoughtSignature": {"opaque": "not-a-string"}},
    {"inlineData": {"mimeType": "audio/wav", "data": "AA=="}},
    {"text": "hidden", "functionCall": {"name": "internal"}},
])
def test_native_invalid_part_is_terminal_even_after_visible_answer(invalid_part):
    with pytest.raises(VideoNativeRefused) as exc:
        gemini_video_answer(_response([{"text": "visible"}, invalid_part]))
    assert type(exc.value) is VideoNativeRefused


@pytest.mark.asyncio
async def test_signed_native_thought_fallback_uses_one_request_and_keeps_output_cap(rig, monkeypatch):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []
    payload = _response([
        {"text": "R" * 17_000, "thought": True, "thoughtSignature": "private-signature"},
        {"text": "   "},
    ])

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json=payload)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "R" * 16_000
    assert result["result"]["chosen_call"] == 1
    assert len(sent) == 1
    assert "private-signature" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [
    [{"text": "visible"}, {"thought": True, "functionCall": {"name": "private"}}],
    [{"text": "<think>private</think>"}],
])
async def test_signed_native_invalid_output_never_uses_approved_fallback(rig, monkeypatch, parts):
    _local_gemini(monkeypatch)
    _grant(rig, monkeypatch)
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    monkeypatch.setenv("JARVIS_ROLE_VIDEO_FALLBACKS", json.dumps([{
        "provider": "lm-studio", "model": "backup", "base_url": "http://127.0.0.1:1235/v1"}]))
    sent = []
    payload = _response(parts)

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json=payload)

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    result = await _approved(rig)
    assert result["status"] != "ok"
    assert [request.url.port for request in sent] == [8420]
    assert "private" not in json.dumps(result)
