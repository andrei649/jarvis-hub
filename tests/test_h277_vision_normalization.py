"""Real compatible image/video consumers normalize native model replies."""

import httpx
import pytest

from agents.core.commands import Principal
from agents.core.llm import vision_policy as vp
from agents.core.llm.egress import llm_async_client
from agents.core.llm.vlm import VLMBackend, VLMConfig
from tests.test_h277_video_analysis import rig
from tests.test_h277_video_provider_chain import approved_run


def _reply(message, *, finish="stop", **choice_fields):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish,
        "message": message, **choice_fields}]})


async def _image(payload, *, retry_setting=False, monkeypatch=None):
    if retry_setting:
        monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    config = VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", "vision", "", True)
    sent = []

    def respond(request):
        sent.append(request)
        return payload

    client = llm_async_client("vlm", base_url=config.base_url,
                              auth=httpx.Auth(), trust_env=False,
                              transport=httpx.MockTransport(respond))
    backend = VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        if retry_setting:
            with vp.composer_request_scope(
                    config, backend, resolve_config=lambda: config,
                    remote_ack=False, principal=Principal(channel="web")):
                return await backend.generate_vision_checked(
                    config.model, "What is here?", images=[b"image"]), sent
        return await backend.generate_vision_checked(
            config.model, "What is here?", images=[b"image"]), sent
    finally:
        await backend.aclose()


async def _video(rig, payload, monkeypatch, *, retry=False):
    if retry:
        monkeypatch.setenv("JARVIS_ROLE_VIDEO_EMPTY_RETRIES", "1")
    sent = []

    def respond(request):
        sent.append(request)
        return payload

    rig.video.model_client_factory = lambda backend, **kw: llm_async_client(
        backend, transport=httpx.MockTransport(respond), **kw)
    return await approved_run(rig), sent


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_setting", [False, True])
async def test_image_visible_text_wins_and_thinking_is_hidden(retry_setting, monkeypatch):
    message = {"content": "<think>private</think>  Visible answer.  ",
               "reasoning": "Reasoning should not displace visible text."}
    answer, sent = await _image(_reply(message), retry_setting=retry_setting, monkeypatch=monkeypatch)
    assert answer == "Visible answer."
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "expected"), [
    ({"content": "", "reasoning": "First insight."}, "First insight."),
    ({"content": None, "reasoning_content": "Second insight."}, "Second insight."),
    ({"reasoning_details": [{"type": "reasoning.text", "text": "Detail insight."}]}, "Detail insight."),
    ({"content": "<think>unfinished private thought", "reasoning_content": "Structured answer."}, "Structured answer."),
    ({"content": "", "reasoning": "A", "reasoning_content": " A ",
      "reasoning_details": [{"summary": "B"}, {"content": "B"}, {"text": "C"},
                            {"data": "opaque", "text": 42}]}, "A\n\nB\n\nC"),
    ({"content": "", "reasoning_details": [{"summary": "Top summary", "content": "Unused", "text": "Unused"},
                                           {"summary": [], "content": "Content fallback", "text": "Unused"}]},
     "Top summary\n\nContent fallback"),
])
async def test_image_uses_structured_reasoning_without_extra_send(message, expected, monkeypatch):
    answer, sent = await _image(_reply(message), retry_setting=True, monkeypatch=monkeypatch)
    assert answer == expected
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"error": {"message": "private"}, "choices": [{"message": {"content": "Visible"}}]},
    {"choices": [{"error": {"message": "private"}, "message": {"content": "Visible"}}]},
    {"choices": [{"message": {"content": "Visible", "error": {"message": "private"}}}]},
    {"choices": [{"message": {"content": "Visible", "refusal": "denied"}}]},
    {"choices": [{"message": {"content": "Visible", "tool_calls": [{"id": "tool"}]}}]},
    {"choices": [{"message": {"content": "Visible", "function_call": {"name": "tool"}}}]},
    {"choices": [{"message": {"content": "Visible", "audio": {"id": "audio"}}}]},
    {"choices": [{"finish_reason": "content_filter", "message": {"content": "Visible"}}]},
    {"choices": [{"message": {"content": ["Visible"], "reasoning": "Fallback"}}]},
])
async def test_image_rejects_mixed_invalid_reply_without_serialization(payload, monkeypatch):
    response = httpx.Response(200, json=payload)
    with pytest.raises(ValueError):
        await _image(response, retry_setting=True, monkeypatch=monkeypatch)


@pytest.mark.asyncio
async def test_image_length_finish_with_visible_text_is_accepted(monkeypatch):
    answer, sent = await _image(_reply({"content": "Finished."}, finish="length"),
                                retry_setting=True, monkeypatch=monkeypatch)
    assert answer == "Finished." and len(sent) == 1


@pytest.mark.asyncio
async def test_image_length_finish_with_structured_reasoning_is_accepted(monkeypatch):
    answer, sent = await _image(_reply({"content": "", "reasoning": "Partial insight."}, finish="length"),
                                retry_setting=True, monkeypatch=monkeypatch)
    assert answer == "Partial insight." and len(sent) == 1


@pytest.mark.asyncio
async def test_image_empty_refusal_metadata_does_not_hide_visible_text(monkeypatch):
    answer, sent = await _image(_reply({"content": "Visible.", "refusal": ""}),
                                retry_setting=True, monkeypatch=monkeypatch)
    assert answer == "Visible." and len(sent) == 1


@pytest.mark.asyncio
async def test_image_alias_thinking_tags_are_hidden_before_visible_answer(monkeypatch):
    answer, sent = await _image(_reply({"content": "<thinking>private</thinking> <思考>hidden</思考> Seen.",
                                        "reasoning": "Other."}),
                                retry_setting=True, monkeypatch=monkeypatch)
    assert answer == "Seen." and len(sent) == 1


@pytest.mark.asyncio
async def test_video_visible_text_wins_and_thinking_is_hidden(rig, monkeypatch):
    result, sent = await _video(rig, _reply({"content": "<think>private</think> Visible.",
                                          "reasoning": "Alternative."}), monkeypatch)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Visible."
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "expected"), [
    ({"content": "", "reasoning": "Reasoned answer."}, "Reasoned answer."),
    ({"content": None, "reasoning_content": "Content answer."}, "Content answer."),
    ({"reasoning_details": [{"summary": "Detail answer."}]}, "Detail answer."),
    ({"content": "", "reasoning": "One", "reasoning_content": "One",
      "reasoning_details": [{"text": "Two"}, {"content": " Two "}]}, "One\n\nTwo"),
])
async def test_video_uses_reasoning_without_extra_send(rig, monkeypatch, message, expected):
    result, sent = await _video(rig, _reply(message), monkeypatch, retry=True)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == expected
    assert result["result"]["chosen_call"] == 1
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_video_alias_thinking_and_length_reasoning_use_same_reply(rig, monkeypatch):
    result, sent = await _video(rig, _reply({"content": "<reasoning>hidden</reasoning>",
                                            "reasoning_content": "<反思>private</反思> Motion insight."},
                                           finish="length"), monkeypatch, retry=True)
    assert result["status"] == "ok", result
    assert result["result"]["analysis"] == "Motion insight."
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"error": {"message": "private"}, "choices": [{"message": {"content": "Visible"}}]},
    {"choices": [{"error": {"message": "private"}, "message": {"content": "Visible"}}]},
    {"choices": [{"message": {"content": "Visible", "error": {"message": "private"}}}]},
    {"choices": [{"message": {"content": "Visible", "refusal": "denied"}}]},
    {"choices": [{"message": {"content": "Visible", "tool_calls": [{"id": "tool"}]}}]},
    {"choices": [{"message": {"content": "Visible", "function_call": {"name": "tool"}}}]},
    {"choices": [{"message": {"content": "Visible", "audio": {"id": "audio"}}}]},
    {"choices": [{"finish_reason": "content_filter", "message": {"content": "Visible"}}]},
    {"choices": [{"message": {"content": ["Visible"], "reasoning": "Fallback"}}]},
])
async def test_video_rejects_mixed_invalid_reply_without_extra_send(rig, monkeypatch, payload):
    result, sent = await _video(rig, httpx.Response(200, json=payload), monkeypatch, retry=True)
    assert result["status"] != "ok"
    assert "Visible" not in str(result) and "private" not in str(result)
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("detail_type", ["reasoning.encrypted", "reasoning.opaque", "unknown", {}, []])
async def test_image_skips_opaque_reasoning_details(detail_type, monkeypatch):
    message = {"content": "", "reasoning_details": [
        {"type": detail_type, "summary": "opaque-token", "content": "opaque-token", "text": "opaque-token"},
        {"type": "reasoning.summary", "summary": "Useful answer."},
    ]}
    answer, sent = await _image(_reply(message), retry_setting=True, monkeypatch=monkeypatch)
    assert answer == "Useful answer."
    assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_answer", [False, True])
async def test_video_never_returns_or_retries_encrypted_details(rig, monkeypatch, with_answer):
    details = [{"type": "reasoning.encrypted", "content": "opaque-token"}]
    if with_answer:
        details.append({"type": "reasoning.text", "text": "Useful answer."})
    result, sent = await _video(rig, _reply({"content": "", "reasoning_details": details}),
                                monkeypatch, retry=True)
    assert "opaque-token" not in str(result)
    if with_answer:
        assert result["status"] == "ok", result
        assert result["result"]["analysis"] == "Useful answer."
    else:
        assert result["status"] != "ok", result
    assert len(sent) == 1
