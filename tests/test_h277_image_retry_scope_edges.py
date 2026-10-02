"""Behavioral exclusions and hook ordering for governed image recovery."""

import json

import httpx
import pytest

from agents.core.commands import Principal
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from agents.core.llm.egress import llm_async_client


@pytest.mark.asyncio
async def test_hook_appended_after_scope_guard_cannot_reach_transport(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    config = vlm.VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", "vision", "", True)
    sent = []
    client = llm_async_client(
        "vlm", base_url=config.base_url, auth=httpx.Auth(), trust_env=False,
        transport=httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "answer"}}]})),
    )
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)

    async def tamper(request):
        payload = json.loads(request.content)
        payload["messages"][-1]["content"][0]["text"] = "changed after final validation"
        request._content = json.dumps(payload).encode()

    try:
        with pytest.raises(vp.VisionDestinationChanged), vp.composer_request_scope(
            config, backend, resolve_config=lambda: config,
            remote_ack=False, principal=Principal(channel="web"),
        ):
            client.event_hooks["request"].append(tamper)
            await backend.generate_vision_checked(config.model, "what?", images=[b"synthetic"])
        assert sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_text_only_call_in_governed_scope_never_retries(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_VISION_EMPTY_RETRIES", "1")
    config = vlm.VLMConfig("lmstudio", "http://127.0.0.1:1234/v1", "vision", "", True)
    sent = []
    client = llm_async_client(
        "vlm", base_url=config.base_url, auth=httpx.Auth(), trust_env=False,
        transport=httpx.MockTransport(lambda request: sent.append(request) or httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": ""}}]})),
    )
    backend = vlm.VLMBackend(config.base_url, client=client, composer_auth=True)
    try:
        with vp.composer_request_scope(
            config, backend, resolve_config=lambda: config,
            remote_ack=False, principal=Principal(channel="web"),
        ):
            assert await backend.generate_vision_checked(config.model, "text only", images=[]) == ""
        assert len(sent) == 1
        payload = json.loads(sent[0].content)
        assert all(part["type"] != "image_url" for part in payload["messages"][-1]["content"])
    finally:
        await backend.aclose()
