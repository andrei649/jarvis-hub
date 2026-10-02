"""H277 selected local auxiliary routing through the real SOUL draft consumer."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db, soul_edit
from agents.core.llm import data_handling
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.router import LLMRouter


@pytest.fixture
def draft_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, "_scope_key", lambda: b"synthetic-soul-draft")
    sent = []

    def answer(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"content": "A local household assistant."},
            "finish_reason": "stop",
        }]})

    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    asyncio.run(backend.client.aclose())
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(answer),
    )
    router = LLMRouter()
    router._backend = backend
    router._backend_name = "lm-studio"
    router._detected_model = "active-local"
    orch = SimpleNamespace(
        agents={"jarvis": SimpleNamespace(soul={"content": "Private house persona"})},
        llm_router=router,
    )
    return orch, backend, sent


@pytest.mark.asyncio
async def test_soul_draft_uses_independent_selected_local_model(draft_route, monkeypatch):
    orch, backend, sent = draft_route
    monkeypatch.setenv("JARVIS_AUX_SOUL_DESCRIPTION_MODEL", "draft-local")
    try:
        assert await soul_edit.draft_description(orch, "jarvis") == "A local household assistant."
        assert len(sent) == 1
        assert sent[0]["model"] == "draft-local"
        assert sent[0]["max_tokens"] == soul_edit.DRAFT_MAX_TOKENS
        assert sent[0]["temperature"] == 0.3
        assert sent[0]["messages"][-1]["content"] == "Persona:\nPrivate house persona"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_rechecks_h513_before_model_request(draft_route, monkeypatch):
    orch, backend, sent = draft_route

    def revoke(*_args, **_kwargs):
        raise data_handling.DataHandlingRefused("synthetic revocation")

    monkeypatch.setattr(data_handling, "authorize", revoke)
    try:
        with pytest.raises(soul_edit.SoulEditError) as error:
            await soul_edit.draft_description(orch, "jarvis")
        assert error.value.code == "no_local_model"
        assert sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_rechecks_h513_at_physical_request(draft_route, monkeypatch):
    orch, backend, sent = draft_route
    original = data_handling.authorize
    checks = 0

    def revoke_on_send(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise data_handling.DataHandlingRefused("synthetic physical revocation")
        return original(*args, **kwargs)

    monkeypatch.setattr(data_handling, "authorize", revoke_on_send)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert checks == 2 and sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_refuses_proxy_before_persona_egress(draft_route):
    orch, backend, sent = draft_route
    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        proxy="http://proxy.invalid:8080",
    )
    proxied = []
    proxy = backend.client._transport_for_url(httpx.URL(backend.base_url))

    async def offline(request):
        proxied.append(request)
        return httpx.Response(200, json={"choices": [{
            "message": {"content": "unexpected"}, "finish_reason": "stop",
        }]})

    proxy.handle_async_request = offline
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert proxied == sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_refuses_late_proxy_mount(draft_route):
    from httpx._utils import URLPattern

    orch, backend, sent = draft_route
    proxy = httpx.AsyncHTTPTransport(proxy="http://proxy.invalid:8080", trust_env=False)
    proxied = []

    async def offline(request):
        proxied.append(request)
        return httpx.Response(200, json={"choices": [{
            "message": {"content": "unexpected"}, "finish_reason": "stop",
        }]})

    proxy.handle_async_request = offline

    async def reroute(_request):
        backend.client._mounts[URLPattern("http://127.0.0.1:1234")] = proxy

    backend.client.event_hooks["request"].insert(0, reroute)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert proxied == sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_uses_ollama_native_generate_route(draft_route):
    orch, old_backend, _old_sent = draft_route
    await old_backend.aclose()
    sent = []

    def answer(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"response": "A local Ollama assistant.", "done": True})

    backend = OllamaBackend("http://127.0.0.1:11434", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client(
        "ollama", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(answer),
    )
    orch.llm_router._backend = backend
    orch.llm_router._backend_name = "ollama"
    try:
        assert await soul_edit.draft_description(orch, "jarvis") == "A local Ollama assistant."
        assert len(sent) == 1
        assert sent[0][0] == "http://127.0.0.1:11434/api/generate"
        assert sent[0][1]["model"] == "active-local"
        assert sent[0][1]["options"]["num_predict"] == soul_edit.DRAFT_MAX_TOKENS
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "prompt", "cap"])
async def test_soul_draft_binds_selected_payload_at_physical_request(draft_route, change):
    orch, backend, sent = draft_route

    async def switch_payload(request):
        body = json.loads(request.content)
        if change == "model":
            body["model"] = "different-local"
        elif change == "prompt":
            body["messages"][-1]["content"] = "different persona"
        else:
            body["max_tokens"] = 100_000
        request._content = json.dumps(body).encode()

    backend.client.event_hooks["request"].insert(0, switch_payload)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_refuses_hook_after_final_request_guard(draft_route):
    orch, backend, sent = draft_route

    async def late_redirect(request):
        request.url = httpx.URL("https://remote.invalid/v1/chat/completions")

    backend.client.event_hooks["request"].append(late_redirect)
    try:
        with pytest.raises(soul_edit.SoulEditError):
            await soul_edit.draft_description(orch, "jarvis")
        assert sent == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_soul_draft_preserves_legitimate_bracketed_description(draft_route):
    orch, backend, _sent = draft_route
    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
            "choices": [{"message": {"content": "[1] Handles the house."},
                         "finish_reason": "stop"}],
        })),
    )
    try:
        assert await soul_edit.draft_description(orch, "jarvis") == "[1] Handles the house."
    finally:
        await backend.aclose()
