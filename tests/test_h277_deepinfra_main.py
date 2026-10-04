"""Explicit DeepInfra main chat and reviewed selected-main images use one authority."""

import asyncio
import hashlib
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from agents import web
from agents.core import settings_db
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.llm import vlm
from agents.core.llm.data_handling import DataHandlingRefused, physical_request_scope, resolve
from agents.core.llm.egress import llm_async_client
from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.router import LLMRouter
from agents.core.llm.vision_main import selected_main_config
from agents.core.llm.vlm import VLMNotConfigured
from agents.core.orchestrator import Orchestrator
from tests.test_composer_vision import PNG
from tests.test_h277_vision_auto_consumer import approved, route  # noqa: F401

MODEL = "vendor/deepinfra-vision"
BASE = "https://api.deepinfra.com/v1/openai"
DIGEST = hashlib.sha256(PNG.encode()).hexdigest()


def _backend(*, key="deepinfra-key", base=BASE, client=None):
    module = importlib.import_module("agents.core.llm.deepinfra")
    return module.DeepInfraBackend(key, base_url=base, client=client)


def test_profile_and_settings_offer_explicit_deepinfra_chat_without_policy_alias():
    profile = DEFAULT_REGISTRY.get("deepinfra")
    assert profile.backend_kind == "openai-compatible"
    assert profile.capabilities >= {"chat", "vision", "model-catalog", "cloud"}
    assert profile.data_policy == "unknown"
    row = next(r for r in settings_db.DEFAULTS if r["category"] == "llm" and r["key"] == "compatible_provider")
    assert "deepinfra" in row["opts"]


@pytest.mark.asyncio
async def test_explicit_router_uses_deepinfra_identity_and_only_own_key(monkeypatch):
    settings = {"compatible_provider": "deepinfra", "compatible_model": MODEL,
                "cloud_fallback": "on-demand"}
    monkeypatch.setenv("DEEPINFRA_API_KEY", "deepinfra-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "foreign-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting", staticmethod(lambda key, default: settings.get(key, default)))
    router = HybridRouter()
    await router.detect()
    try:
        backend, model, route = router.select_backend("jarvis", "Hello")
        assert (backend.profile.id, backend.api_key, backend.base_url, model, route) == (
            "deepinfra", "deepinfra-key", BASE, MODEL, "cloud-compatible")
        assert resolve(router, backend, model, route).policy == "unknown"
        with pytest.raises(LocalBackendUnavailableError):
            router.select_backend("frigga", "Hello")
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_main_chat_and_tool_wire_are_deepinfra_labeled_and_sanitized(monkeypatch):
    seen = []
    def answer(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A square."}}]})
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(answer))
    backend = _backend(client=client)
    try:
        assert await backend.generate(MODEL, "Describe", system="Follow instructions") == "A square."
        turn = await backend.generate_tool_turn(MODEL, [{"role": "user", "content": "Inspect"}], [])
        assert turn.content == "A square."
        assert len(seen) == 2
        for request in seen:
            assert str(request.url) == BASE + "/chat/completions"
            assert request.headers["Authorization"] == "Bearer deepinfra-key"
            body = json.loads(request.content)
            assert body["model"] == MODEL and "provider" not in body
            assert "foreign-key" not in str(request)
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_every_physical_main_send_rechecks_scope(monkeypatch):
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))[1]))
    backend = _backend(client=client)
    calls = 0
    def guard():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DataHandlingRefused("revoked")
    try:
        with pytest.raises(DataHandlingRefused, match="revoked"), physical_request_scope(guard):
            assert await backend.generate(MODEL, "first") == "ok"
            assert await backend.generate(MODEL, "second") != "ok"
        assert len(seen) == 1 and calls == 2
    finally:
        await backend.aclose()


@pytest.mark.parametrize("base,key,reason", [
    (BASE, "", "vlm_key_unset"),
    ("https://other.example/v1", "foreign-key", "vlm_url_invalid"),
    ("http://remote.example/v1", "deepinfra-key", "vlm_url_invalid"),
])
def test_deepinfra_selected_image_refuses_invalid_authority(base, key, reason):
    backend = object.__new__(importlib.import_module("agents.core.llm.deepinfra").DeepInfraBackend)
    backend.profile = DEFAULT_REGISTRY.get("deepinfra")
    backend.base_url = base
    backend.api_key = key
    with pytest.raises(VLMNotConfigured) as refused:
        selected_main_config(backend, MODEL, "cloud-compatible")
    assert refused.value.reason == reason


def test_selected_image_config_keeps_deepinfra_key_model_and_url():
    backend = _backend(client=object())
    config = selected_main_config(backend, MODEL, "cloud-compatible")
    assert (config.backend, config.base_url, config.api_key, config.model, config.route_source) == (
        "deepinfra", BASE, "deepinfra-key", MODEL, "auto:main")


def test_reviewed_deepinfra_selected_image_sends_and_commits_history(route, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = _backend(client=object())
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("deepinfra_selected_image"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Blue square."}}]})
    monkeypatch.setattr(vlm, "llm_async_client", lambda provider, **kwargs:
                        llm_async_client(provider, transport=httpx.MockTransport(respond), **kwargs))
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
        "selected_turn": True, "image_digests": [DIGEST]})
    assert preview.status_code == 200, preview.text
    status = preview.json()
    assert (status["backend"], status["model"], status["destination"], status["selection_source"]) == (
        "deepinfra", MODEL, BASE, "auto:main")
    assert "deepinfra-key" not in str(status)
    assert seen == []
    body = {**approved(status), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": status["review_token"]}
    for item in status.get("selection_requirements", []):
        body[item["needs"]] = True
    sent = route.client.post("/api/vlm/composer/chat-prepared", json=body)
    assert sent.status_code == 200, sent.text
    assert sent.json()["committed"] is True
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == BASE + "/chat/completions"
    assert request.headers["Authorization"] == "Bearer deepinfra-key"
    payload = json.loads(request.content)
    assert payload["model"] == MODEL and "provider" not in payload
    assert PNG in str(payload["messages"])
    history = asyncio.run(orch.memory.get_history(sid))
    assert [(r["role"], r["content"]) for r in history] == [
        ("user", "Describe this\n[1 image attached]"), ("assistant", "Blue square.")]
    assert all(row["media"]["backend"] == "deepinfra" for row in history)


def test_reviewed_deepinfra_rejects_key_change_before_image_egress(route, monkeypatch):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = _backend(client=object())
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("deepinfra_changed_key"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
        "selected_turn": True, "image_digests": [DIGEST]})
    assert preview.status_code == 200, preview.text
    backend.api_key = "rotated-key"
    body = {**approved(preview.json()), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": preview.json()["review_token"]}
    refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
    assert refused.status_code == 409
    assert route.requests == []

@pytest.mark.asyncio
async def test_late_hook_cannot_change_deepinfra_physical_authority():
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200, json={"choices": [{"message": {"content": "unsafe"}}]}))[1]))
    backend = _backend(client=client)
    async def mutate(request):
        request.headers["Authorization"] = "Bearer foreign-key"
        request.url = httpx.URL("https://other.example/v1/chat/completions")
    client.event_hooks["request"].append(mutate)
    try:
        assert await backend.generate(MODEL, "private prompt") != "unsafe"
        assert seen == []
    finally:
        await backend.aclose()


def test_deepinfra_unknown_policy_requires_durable_internal_ack(tmp_path, monkeypatch):
    from agents.core.commands import Principal
    from agents.core.llm import data_handling
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    router = SimpleNamespace(_compatible_backend=_backend(client=object()),
                             _compatible_model=MODEL, _backend=None,
                             _ollama_backend=None, _gemini_backend=None,
                             _claude_backend=None)
    resolved = data_handling.resolve(router, router._compatible_backend, MODEL, "cloud-compatible")
    assert resolved.provider == "deepinfra" and resolved.policy == "unknown" and resolved.warning
    with pytest.raises(DataHandlingRefused, match="acknowledgment"):
        data_handling.authorize(router, router._compatible_backend, MODEL,
                                "cloud-compatible", principal=Principal())

@pytest.mark.asyncio
@pytest.mark.parametrize("key,base", [
    ("", BASE), ("", "https://other.example/v1"),
    ("own-key", "https://other.example/v1"),
    ("own-key", "http://api.deepinfra.com/v1/openai"),
])
async def test_unavailable_or_foreign_main_authority_never_builds_route(monkeypatch, key, base):
    settings = {"compatible_provider": "deepinfra", "compatible_model": MODEL}
    monkeypatch.setenv("DEEPINFRA_API_KEY", key)
    monkeypatch.setenv("DEEPINFRA_BASE_URL", base)
    monkeypatch.setenv("OPENROUTER_API_KEY", "foreign-openrouter-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting", staticmethod(lambda name, default: settings.get(name, default)))
    router = HybridRouter()
    await router.detect()
    try:
        assert router._compatible_backend is None
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_deepinfra_http_error_never_surfaces_provider_body(caplog):
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda _request:
                                  httpx.Response(400, text="private secret response")))
    backend = _backend(client=client)
    try:
        answer = await backend.generate(MODEL, "private prompt")
        assert answer == "[VLM error]"
        assert "private secret response" not in answer
        assert "private secret response" not in caplog.text
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_preceding_request_hook_cannot_change_deepinfra_key():
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200, json={"choices": [{"message": {"content": "unsafe"}}]}))[1]))
    backend = _backend(client=client)
    async def mutate(request):
        request.headers["Authorization"] = "Bearer foreign-key"
    client.event_hooks["request"].insert(-2, mutate)
    try:
        assert await backend.generate(MODEL, "private prompt") == "[VLM error]"
        assert seen == []
    finally:
        await backend.aclose()

@pytest.mark.asyncio
async def test_duplicate_physical_model_field_refuses_before_deepinfra_send():
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200, json={"choices": [{"message": {"content": "unsafe"}}]}))[1]))
    backend = _backend(client=client)
    async def duplicate(request):
        request._content = b'{"model":"' + MODEL.encode() + b'",' + request.content[1:]
    client.event_hooks["request"].insert(-2, duplicate)
    try:
        assert await backend.generate(MODEL, "private prompt") == "[VLM error]"
        assert seen == []
    finally:
        await backend.aclose()

class _GatedSSE(httpx.AsyncByteStream):
    def __init__(self):
        self.first = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hello world"},"finish_reason":null}]}\n\n'
        self.first.set()
        await self.release.wait()
        yield b'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}\n\n'
        yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closed.set()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_emits_before_completion_and_tracks_usage(monkeypatch):
    from agents.core.llm import deepinfra
    seen = []
    frames = _GatedSSE()
    usage = []
    monkeypatch.setattr(deepinfra, "report_text_usage", usage.append)
    def respond(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=frames)
    backend = _backend(client=llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                                               transport=httpx.MockTransport(respond)))
    tokens = []
    try:
        task = asyncio.create_task(backend.generate_stream(MODEL, "private prompt", on_token=tokens.append))
        await asyncio.wait_for(frames.first.wait(), 2)
        await asyncio.sleep(0)
        assert tokens and "".join(tokens) == "Hello"
        assert not task.done()
        frames.release.set()
        assert await asyncio.wait_for(task, 2) == "Hello world!"
        assert frames.closed.is_set()
        assert len(seen) == 1
        body = json.loads(seen[0].content)
        assert body["stream"] is True and body["model"] == MODEL
        assert seen[0].headers["Authorization"] == "Bearer deepinfra-key"
        assert len(usage) == 1 and (usage[0].input_tokens, usage[0].output_tokens) == (2, 2)
    finally:
        frames.release.set()
        await backend.aclose()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_filters_reasoning_and_requires_clean_finish():
    payload = (b'data: {"choices":[{"delta":{"content":"<think>private"}}]}\n\n'
               b'data: {"choices":[{"delta":{"reasoning_content":"secret", "content":"</think>Public"},"finish_reason":"stop"}]}\n\n'
               b'data: [DONE]\n\n')
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda _request: httpx.Response(
                                  200, headers={"content-type": "text/event-stream"}, content=payload)))
    backend = _backend(client=client)
    tokens = []
    try:
        assert await backend.generate_stream(MODEL, "prompt", on_token=tokens.append) == "Public"
        assert "".join(tokens) == "Public"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_rejection_sanitized_and_no_retry(caplog):
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request),
                                  httpx.Response(401, text="private vendor token"))[1]))
    backend = _backend(client=client)
    tokens = []
    try:
        assert await backend.generate_stream(MODEL, "prompt", on_token=tokens.append) == "[VLM error]"
        assert tokens == [] and len(seen) == 1
        assert "private vendor token" not in caplog.text
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_cancel_closes_without_retry():
    frames = _GatedSSE()
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request),
                                  httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=frames))[1]))
    backend = _backend(client=client)
    tokens = []
    try:
        task = asyncio.create_task(backend.generate_stream(MODEL, "prompt", on_token=tokens.append))
        await asyncio.wait_for(frames.first.wait(), 2)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert frames.closed.is_set() and len(seen) == 1
        assert "".join(tokens) == "Hello"
    finally:
        frames.release.set()
        await backend.aclose()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_late_hook_and_scope_refuse_before_transport():
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200))[1]))
    backend = _backend(client=client)
    async def mutate(request):
        request.headers["Authorization"] = "Bearer foreign-key"
    client.event_hooks["request"].insert(-2, mutate)
    try:
        assert await backend.generate_stream(MODEL, "prompt") == "[VLM error]"
        assert seen == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("key,model", [("", MODEL), ("deepinfra-key", "")])
async def test_explicit_deepinfra_missing_key_or_model_never_falls_to_gemini(monkeypatch, key, model):
    settings = {"compatible_provider": "deepinfra", "compatible_model": model,
                "cloud_fallback": "on-demand"}
    monkeypatch.setenv("DEEPINFRA_API_KEY", key)
    monkeypatch.setenv("GEMINI_API_KEY", "foreign-gemini-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting", staticmethod(lambda name, default: settings.get(name, default)))
    router = HybridRouter()
    await router.detect()
    try:
        assert router._compatible_backend is None
        with pytest.raises((RuntimeError, LocalBackendUnavailableError)):
            router.select_backend("jarvis", "private prompt")
    finally:
        await router.aclose()

@pytest.mark.asyncio
async def test_native_deepinfra_sse_late_hook_replacement_refuses_before_transport():
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200))[1]))
    backend = _backend(client=client)
    async def mutate(request):
        request.url = httpx.URL("https://other.example/v1/chat/completions")
    client.event_hooks["request"].append(mutate)
    try:
        assert await backend.generate_stream(MODEL, "prompt") == "[VLM error]"
        assert seen == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_native_deepinfra_sse_rechecks_scope_and_never_retries():
    seen = []
    sse = b'data: {"choices":[{"delta":{"content":"Hello world"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request),
                                  httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse))[1]))
    backend = _backend(client=client)
    calls = 0
    def guard():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DataHandlingRefused("revoked")
    try:
        with pytest.raises(DataHandlingRefused, match="revoked"), physical_request_scope(guard):
            assert await backend.generate_stream(MODEL, "first") == "Hello world"
            assert await backend.generate_stream(MODEL, "second") == "[VLM error]"
        assert len(seen) == 1 and calls == 2
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", [
    b'data: {"error":{"message":"private vendor body"}}\n\n',
    b'data: {"choices":[{"delta":{"content":"unsafe"}}]}\n\n',
])
async def test_native_deepinfra_sse_error_or_incomplete_frame_fails_closed(frame, caplog):
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda _request: httpx.Response(
                                  200, headers={"content-type": "text/event-stream"}, content=frame)))
    backend = _backend(client=client)
    try:
        assert await backend.generate_stream(MODEL, "prompt") == "[VLM error]"
        assert "private vendor body" not in caplog.text
    finally:
        await backend.aclose()

@pytest.mark.parametrize("base", [
    "https://api.deepinfra.com/attacker/path",
    "https://api.deepinfra.com/v1/openai/other",
    "https://api.deepinfra.com/v1/openai/../other",
    "https://api.deepinfra.com/v1/openai/%2e%2e/other",
    "https://api.deepinfra.com/v1/%6fpenai",
    "https://api.deepinfra.com/v1/openai?mode=other",
    "https://api.deepinfra.com/v1/openai#other",
    "https://api.deepinfra.com:0443/v1/openai",
])
def test_deepinfra_main_constructor_refuses_same_origin_ambiguous_path_without_egress(base):
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request), httpx.Response(200))[1]))
    try:
        with pytest.raises(ValueError, match="DeepInfra main destination"):
            _backend(base=base, client=client)
        assert seen == []
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("base", [BASE, BASE + "/",
                                  "https://api.deepinfra.com:443/v1/openai",
                                  "https://api.deepinfra.com:443/v1/openai/"])
def test_deepinfra_main_normalizes_supported_default_port_forms(base):
    backend = _backend(base=base, client=object())
    assert backend.base_url == BASE
    assert selected_main_config(backend, MODEL, "cloud-compatible").base_url == BASE


@pytest.mark.parametrize("base", ["https://api.deepinfra.com/attacker/path",
                                  "https://api.deepinfra.com/v1/openai/other"])
def test_deepinfra_selected_image_refuses_same_host_wrong_path(base):
    backend = _backend(client=object())
    backend.base_url = base
    with pytest.raises(VLMNotConfigured) as refused:
        selected_main_config(backend, MODEL, "cloud-compatible")
    assert refused.value.reason == "vlm_url_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["https://api.deepinfra.com/attacker/path",
                                  "https://api.deepinfra.com/v1/openai/other"])
async def test_deepinfra_main_refuses_postconstruction_path_mutation_before_send(base):
    seen = []
    client = llm_async_client("deepinfra", base_url=BASE, trust_env=False,
                              transport=httpx.MockTransport(lambda request: (seen.append(request),
                                  httpx.Response(200, json={"choices": [{"message": {"content": "unsafe"}}]}))[1]))
    backend = _backend(client=client)
    backend.base_url = base
    try:
        assert await backend.generate(MODEL, "private prompt") == "[VLM error]"
        assert seen == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["https://api.deepinfra.com/attacker/path",
                                  "https://api.deepinfra.com/v1/openai/other"])
async def test_deepinfra_router_refuses_wrong_same_host_path_with_gemini_present(monkeypatch, base):
    settings = {"compatible_provider": "deepinfra", "compatible_model": MODEL,
                "cloud_fallback": "on-demand"}
    monkeypatch.setenv("DEEPINFRA_API_KEY", "deepinfra-key")
    monkeypatch.setenv("DEEPINFRA_BASE_URL", base)
    monkeypatch.setenv("GEMINI_API_KEY", "foreign-gemini-key")
    monkeypatch.setattr(LLMRouter, "detect", lambda *_: asyncio.sleep(0))
    monkeypatch.setattr(HybridRouter, "_check", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting", staticmethod(lambda name, default: settings.get(name, default)))
    router = HybridRouter()
    await router.detect()
    try:
        assert router._compatible_backend is None
        with pytest.raises((RuntimeError, LocalBackendUnavailableError)):
            router.select_backend("jarvis", "private prompt")
    finally:
        await router.aclose()

@pytest.mark.parametrize("base", ["https://api.deepinfra.com/attacker/path",
                                  "https://api.deepinfra.com/v1/openai/other"])
def test_reviewed_deepinfra_image_path_change_refuses_before_egress(route, monkeypatch, base):
    orch = Orchestrator(JarvisConfig())
    orch.agents["jarvis"] = Agent("jarvis", {}, orch.llm_router)
    backend = _backend(client=object())
    orch.llm_router.select_backend = lambda _agent, _prompt: (backend, MODEL, "cloud-compatible")
    sid = asyncio.run(orch.memory.new_session("deepinfra_changed_path"))
    orch._session_id_default = sid
    monkeypatch.setattr(web, "orch", orch)
    preview = route.client.post("/api/vlm/composer/prepare", json={
        "prompt": "Describe this", "agent": "jarvis", "session_id": sid,
        "selected_turn": True, "image_digests": [DIGEST]})
    assert preview.status_code == 200, preview.text
    backend.base_url = base
    body = {**approved(preview.json()), "agent": "jarvis", "session_id": sid,
            "selected_turn": True, "review_token": preview.json()["review_token"]}
    refused = route.client.post("/api/vlm/composer/chat-prepared", json=body)
    assert refused.status_code == 409
    assert route.requests == []
