"""H277: role inspection and guarded image dispatch use real route entrypoints."""

import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agents.core.llm import model_roles, vlm
from agents.core.llm import selection_guards as sg
from agents.core.routers import models_llm, multimodal
from agents.core.routers._deps import user_guard


def test_role_route_is_authenticated_and_projects_no_credentials(monkeypatch):
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "judge")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "https://private.example/v1")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_KEY", "sentinel-secret")
    monkeypatch.setenv("JARVIS_ROLE_VISION_PROVIDER", "lm-studio")
    monkeypatch.setenv("JARVIS_ROLE_VISION_MODEL", "vision")
    monkeypatch.setenv("JARVIS_ROLE_VISION_BASE_URL", "http://user:url-secret@127.0.0.1:1234/v1?token=query-secret")
    app = FastAPI()
    app.include_router(models_llm.router)

    def denied():
        raise HTTPException(status_code=401)

    app.dependency_overrides[user_guard] = denied
    with TestClient(app) as client:
        assert client.get("/api/llm/roles").status_code == 401
        app.dependency_overrides[user_guard] = lambda: None
        response = client.get("/api/llm/roles")
    assert response.status_code == 200
    assert {r["role"] for r in response.json()["roles"]} == set(model_roles.ROLES)
    assert "sentinel-secret" not in response.text
    assert "private.example" not in response.text
    assert "url-secret" not in response.text
    assert "query-secret" not in response.text
    assert response.json()["reachable"] is None


def configure(monkeypatch, *, local=True):
    config = vlm.VLMConfig(backend="lmstudio", model="local-vision",
                           base_url="http://127.0.0.1:1234/v1" if local else "https://remote.test/v1",
                           api_key="", is_local=local)
    monkeypatch.setattr(vlm, "resolve_vlm_config", lambda: config)
    return config


@pytest.mark.asyncio
async def test_remote_image_describe_never_constructs_a_client(monkeypatch):
    configure(monkeypatch, local=False)
    clients = []

    class Backend:
        def __init__(self, **kw):
            clients.append(kw)

        async def generate_vision(self, *args, **kwargs):
            return "unexpected remote send"

        async def aclose(self):
            pass

    monkeypatch.setattr(vlm, "VLMBackend", Backend)
    result = await multimodal.vlm_describe(multimodal.VLMDescribeBody(prompt="read", images=["data:image/png;base64,eA=="]))
    assert result.status_code == 503
    assert not clients


@pytest.mark.asyncio
async def test_vision_override_is_guarded_before_dispatch(monkeypatch):
    configure(monkeypatch)
    seen, sent = [], []

    def evaluate(choices):
        seen.extend(choices)
        return [sg.Finding("cost", "confirm_expensive", choices[0], "too expensive")]

    class Backend:
        def __init__(self, **kw):
            sent.append(kw)

        async def generate_vision(self, *args, **kwargs):
            return "unexpected"

        async def aclose(self):
            pass

    monkeypatch.setattr(sg, "evaluate", evaluate)
    monkeypatch.setattr(vlm, "VLMBackend", Backend)
    result = await multimodal.vlm_describe(multimodal.VLMDescribeBody(prompt="read", model="costly-override"))
    assert result.status_code == 409
    assert seen[0].model == "costly-override"
    assert json.loads(result.body)["error"] == "selection_guard"
    assert not sent


@pytest.mark.asyncio
async def test_local_vision_still_dispatches_actual_model_and_closes(monkeypatch):
    configure(monkeypatch)
    calls = []
    monkeypatch.setattr(sg, "evaluate", lambda choices: [])

    native = vlm.VLMBackend
    from agents.core.llm.egress import llm_async_client

    def factory(**kw):
        def handle(request):
            payload = json.loads(request.content)
            content = payload['messages'][-1]['content']
            prompt = next(part['text'] for part in content if part['type'] == 'text')
            images = [part['image_url']['url'] for part in content if part['type'] == 'image_url']
            calls.append((payload['model'], prompt, {'images': images}))
            return httpx.Response(200, json={'choices': [{'message': {'content': 'image description'}}]})
        actual = llm_async_client('vlm', base_url=kw['base_url'], auth=httpx.Auth(), trust_env=False,
                                  transport=httpx.MockTransport(handle))
        backend = native(client=actual, **kw)
        close = backend.aclose
        async def closed():
            await close()
            calls.append('closed')
        backend.aclose = closed
        return backend

    monkeypatch.setattr(vlm, 'VLMBackend', factory)
    result = await multimodal.vlm_describe(multimodal.VLMDescribeBody(prompt="read", model="chosen"))
    assert json.loads(result.body)["response"] == "image description"
    assert calls == [("chosen", "read", {"images": []}), "closed"]
