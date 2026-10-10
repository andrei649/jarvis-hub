"""H002: a real owned HTTP dispatch reaches the ASGI chat receipt."""

import json

import httpx
import pytest

import agents.web as web
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.providers import get_profile
from agents.core.router import Intent
from tests.golden_harness import make_golden_orchestrator
from tests.h441_native_fixture import bind_native


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_local_mocktransport_generation_is_attributed_to_its_chat_turn(
    monkeypatch, tmp_path, path,
):
    orch, _ = await make_golden_orchestrator(monkeypatch, tmp_path)
    backend = LMStudioBackend("http://localhost:1234", trust_env=False)
    backend.profile = get_profile("lm-studio")
    backend.supports_tools = False
    requests = []

    def answer(request):
        requests.append(request)
        if json.loads(request.content)["stream"]:
            frames = [
                {"choices": [{"delta": {"content": "The local answer."}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 17, "completion_tokens": 5}},
                "[DONE]",
            ]
            content = "".join("data: " + (row if isinstance(row, str) else json.dumps(row)) + "\n\n"
                              for row in frames)
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "The local answer."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 5, "total_tokens": 22},
        })

    backend.client._mounts = {}
    backend.client._transport = httpx.MockTransport(answer)
    orch.llm_router._backend = backend
    orch.llm_router._backend_name = "lm-studio"
    get_setting = orch.get_setting
    orch.get_setting = lambda key, default=None: (
        False if key == "memory.session_titles" else get_setting(key, default))
    bind_native(orch, monkeypatch)
    sid = await orch.memory.new_session("h002_local_receipt")
    await orch.memory.add_turn(sid, "user", "Previous question")
    monkeypatch.setattr(web, "orch", orch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://testserver") as client:
            response = await client.post(path, json={"message": "What is two plus two?", "session_id": sid})
        assert response.status_code == 200, response.text
        if path.endswith("stream"):
            payload = [json.loads(line[6:]) for line in response.text.splitlines()
                       if line.startswith("data: ")][-1]
        else:
            payload = response.json()
        assert len(requests) == 1
        assert payload.get("reply", payload.get("text")) == "The local answer."
        assert payload["session_id"] == sid
        usage = payload["usage"]
        assert usage["api_calls"] == 1
        assert (usage["input_tokens"], usage["output_tokens"]) == (17, 5)
        assert usage["estimated_cost_usd"] == 0
        assert (usage["usage_basis"], usage["cost_basis"]) == ("provider_complete", "local_zero")
        assert usage["model"] == json.loads(requests[0].content)["model"]
        assert usage["provider"] == "lm-studio"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,stop", [
    (RuntimeError("provider failure"), "generation_failed"),
    (TimeoutError(), "deadline"),
])
async def test_parallel_agent_failure_survives_rephrased_synthesis(
    monkeypatch, tmp_path, failure, stop,
):
    orch, fake = await make_golden_orchestrator(monkeypatch, tmp_path, reply="That sounds fine now.")
    bind_native(orch, monkeypatch)
    sid = await orch.memory.new_session("h002_source_stop")
    await orch.memory.add_turn(sid, "user", "Previous question")

    async def selected(_text, _agents):
        return Intent(["athena"], False, {})

    async def failed(_text, _context, **_kwargs):
        raise failure

    monkeypatch.setattr(orch.router, "classify", selected)
    monkeypatch.setattr(orch.agents["athena"], "process", failed)
    monkeypatch.setattr(web, "orch", orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                 base_url="http://testserver") as client:
        response = await client.post("/chat", json={"message": "Please assess this", "session_id": sid})
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "That sounds fine now."
    assert response.json()["runtime_stops"] == [stop]
    assert fake.calls  # The successful-looking prose came from actual synthesis.
