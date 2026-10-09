"""H388: provider-specific instruction roles on the actual chat request wire."""

import json

import httpx
import pytest

from agents.core.llm.openrouter import OPENROUTER_BASE, OpenRouterBackend
from agents.core.llm.providers import DEFAULT_REGISTRY

_ANSWER = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


async def _capturing_backend(*, profile=None):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_ANSWER)

    client = httpx.AsyncClient(
        base_url=OPENROUTER_BASE,
        transport=httpx.MockTransport(handler),
    )
    return OpenRouterBackend(api_key="synthetic-key", client=client, profile=profile), requests


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["openai/gpt-5", "openai/gpt-5.1-codex", "openai/codex-mini"])
async def test_openrouter_openai_models_send_developer_role_in_plain_and_tool_turns(model):
    backend, requests = await _capturing_backend()
    history = [{"role": "system", "content": "instruction"},
               {"role": "user", "content": "question"}]
    try:
        assert await backend.generate(model, "question", system="instruction") == "ok"
        assert (await backend.generate_tool_turn(model, history, [])).content == "ok"
    finally:
        await backend.aclose()

    assert history[0]["role"] == "system"
    assert len(requests) == 2
    for request in requests:
        body = json.loads(request.content)
        assert body["messages"][:2] == [
            {"role": "developer", "content": "instruction"},
            {"role": "user", "content": "question"},
        ]
        assert request.headers["authorization"] == "Bearer synthetic-key"
        assert body["model"] == model


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["openai/gpt-4.1", "openai/gpt-50", "other/gpt-5"])
async def test_openrouter_other_models_keep_system_role(model):
    backend, requests = await _capturing_backend()
    try:
        await backend.generate(model, "question", system="instruction")
    finally:
        await backend.aclose()
    assert json.loads(requests[0].content)["messages"][0] == {
        "role": "system", "content": "instruction",
    }


@pytest.mark.asyncio
async def test_custom_openai_compatible_route_keeps_system_role_even_for_gpt5_name():
    backend, requests = await _capturing_backend(
        profile=DEFAULT_REGISTRY.get("openai-compatible"),
    )
    try:
        await backend.generate("openai/gpt-5", "question", system="instruction")
        await backend.generate_tool_turn(
            "openai/gpt-5", [{"role": "system", "content": "instruction"}], [],
        )
    finally:
        await backend.aclose()
    assert [json.loads(request.content)["messages"][0]["role"] for request in requests] == [
        "system", "system",
    ]
