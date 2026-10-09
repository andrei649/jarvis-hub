"""A reviewed visual follow-up carries active native image parts in order."""

import base64
import copy
import json

import httpx
import pytest

from agents.core.llm.vision_gemini_wire import generate_content_payload
from agents.core.llm.vision_nous_wire import messages_payload
from agents.core.llm.vision_ollama_wire import chat_payload
from agents.core.llm.vision_responses_wire import responses_payload
from agents.core.llm.vision_xai_wire import xai_payload
from agents.core.llm.vlm import VLMBackend

IMAGE = "data:image/png;base64," + base64.b64encode(b"sample-image").decode()
COMPATIBLE = {
    "model": "vision-model", "max_tokens": 160, "temperature": 0.2, "stream": False,
    "messages": [
        {"role": "system", "content": "Be precise."},
        {"role": "user", "content": [
            {"type": "text", "text": "What is here?"},
            {"type": "image_url", "image_url": {"url": IMAGE}},
        ]},
        {"role": "assistant", "content": "A red door."},
        {"role": "user", "content": [{"type": "text", "text": "What is its handle made of?"}]},
    ],
}


def test_ollama_preserves_prior_image_and_assistant_before_text_followup():
    body = chat_payload(COMPATIBLE)
    assert [item["role"] for item in body["messages"]] == ["system", "user", "assistant", "user"]
    assert body["messages"][1] == {
        "role": "user", "content": "What is here?",
        "images": [IMAGE.partition(",")[2]],
    }
    assert body["messages"][2] == {"role": "assistant", "content": "A red door."}
    assert body["messages"][3] == {"role": "user", "content": "What is its handle made of?"}


def test_gemini_preserves_prior_image_and_model_reply_before_followup():
    body = generate_content_payload(COMPATIBLE)
    assert [item["role"] for item in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][0]["parts"] == [
        {"text": "What is here?"},
        {"inline_data": {"mime_type": "image/png", "data": IMAGE.partition(",")[2]}},
    ]
    assert body["contents"][1]["parts"] == [{"text": "A red door."}]
    assert body["contents"][2]["parts"] == [{"text": "What is its handle made of?"}]


@pytest.mark.parametrize("codec", [
    lambda value: responses_payload(value, retention="in_memory"),
    lambda value: xai_payload(value, reasoning_effort="low"),
])
def test_responses_family_preserves_prior_image_and_assistant(codec):
    body = codec(COMPATIBLE)
    assert [item["role"] for item in body["input"]] == ["system", "user", "assistant", "user"]
    assert body["input"][1]["content"][1] == {
        "type": "input_image", "image_url": IMAGE, "detail": "auto"}
    assert body["input"][2]["content"] == [{"type": "output_text", "text": "A red door."}]
    assert body["input"][3]["content"] == [
        {"type": "input_text", "text": "What is its handle made of?"}]


def test_anthropic_messages_preserves_prior_image_and_assistant():
    body = messages_payload(COMPATIBLE)
    assert [item["role"] for item in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][0]["content"][1] == {
        "type": "image", "source": {"type": "base64", "media_type": "image/png",
                                    "data": IMAGE.partition(",")[2]}}
    assert body["messages"][1]["content"] == [{"type": "text", "text": "A red door."}]


@pytest.mark.parametrize("codec", [
    chat_payload, generate_content_payload, messages_payload,
    lambda value: responses_payload(value, retention="in_memory"),
    lambda value: xai_payload(value, reasoning_effort="low"),
])
def test_native_history_rejects_malformed_role_order_and_missing_image(codec):
    duplicate = copy.deepcopy(COMPATIBLE)
    duplicate["messages"].insert(2, {"role": "user", "content": [{"type": "text", "text": "wrong"}]})
    with pytest.raises(ValueError):
        codec(duplicate)

    text_only = copy.deepcopy(COMPATIBLE)
    text_only["messages"][1]["content"] = [{"type": "text", "text": "What is here?"}]
    with pytest.raises(ValueError):
        codec(text_only)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,wire,response,roles", [
    ("ollama", "ollama_chat", {"done": True, "done_reason": "stop",
        "message": {"role": "assistant", "content": "A brass handle."}}, ["user", "assistant", "user"]),
    ("gemini", "gemini_generate_content", {"candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": "A brass handle."}]}}]}, ["user", "model", "user"]),
    ("openai-responses", "responses", {"status": "completed", "output": [{"type": "message",
        "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": "A brass handle."}]}]}, ["user", "assistant", "user"]),
    ("xai", "xai_responses", {"status": "completed", "output": [{"type": "message",
        "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": "A brass handle."}]}]}, ["user", "assistant", "user"]),
    ("anthropic", "anthropic_messages", {"type": "message", "role": "assistant",
        "content": [{"type": "text", "text": "A brass handle."}], "stop_reason": "end_turn"},
        ["user", "assistant", "user"]),
])
async def test_selected_history_reaches_native_transport_in_order(provider, wire, response, roles):
    sent = []

    def respond(request: httpx.Request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234/v1",
                               transport=httpx.MockTransport(respond), trust_env=False)
    backend = VLMBackend(base_url="http://127.0.0.1:1234/v1", client=client,
                         provider_id=provider, wire_mode=wire)
    try:
        answer = await backend.generate_vision_checked(
            "vision-model", "What is its handle made of?", images=[],
            history=[("What is here?", "A red door.", (b"sample-image",))],
        )
    finally:
        await backend.aclose()
    assert answer == "A brass handle."
    assert len(sent) == 1
    turns = sent[0].get("contents", sent[0].get("input", sent[0].get("messages")))
    assert [item["role"] for item in turns] == roles


@pytest.mark.asyncio
async def test_compatible_backend_sends_history_parts_on_selected_model():
    seen = []

    def respond(request: httpx.Request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "A brass handle."}}]})

    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234/v1",
                               transport=httpx.MockTransport(respond), trust_env=False)
    backend = VLMBackend(base_url="http://127.0.0.1:1234/v1", client=client)
    try:
        answer = await backend.generate_vision_checked(
            "vision-model", "What is its handle made of?", images=[],
            history=[("What is here?", "A red door.", (b"sample-image",))],
        )
    finally:
        await backend.aclose()
    assert answer == "A brass handle."
    assert len(seen) == 1
    assert [item["role"] for item in seen[0]["messages"]] == ["user", "assistant", "user"]
    assert seen[0]["messages"][0]["content"][1]["type"] == "image_url"
    assert seen[0]["messages"][1]["content"] == "A red door."


@pytest.mark.asyncio
async def test_malformed_history_refuses_before_transport():
    sent = []
    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234/v1",
                               transport=httpx.MockTransport(lambda request: sent.append(request)
                                                             or httpx.Response(200, json={})), trust_env=False)
    backend = VLMBackend(base_url="http://127.0.0.1:1234/v1", client=client)
    try:
        with pytest.raises(ValueError):
            await backend.generate_vision_checked(
                "vision-model", "Follow up", images=[],
                history=[("question", "answer", ("https://remote.example/image.png",))],
            )
    finally:
        await backend.aclose()
    assert sent == []


@pytest.mark.asyncio
async def test_combined_history_request_over_wire_cap_refuses_before_transport():
    sent = []
    client = httpx.AsyncClient(base_url="http://127.0.0.1:1234/v1",
                               transport=httpx.MockTransport(lambda request: sent.append(request)
                                                             or httpx.Response(200, json={})), trust_env=False)
    backend = VLMBackend(base_url="http://127.0.0.1:1234/v1", client=client)
    try:
        with pytest.raises(ValueError, match="active image request too large"):
            await backend.generate_vision_checked(
                "vision-model", "Follow up", images=[],
                history=[("question", "answer", (b"x" * 3_800_000,) * 4)],
            )
    finally:
        await backend.aclose()
    assert sent == []
