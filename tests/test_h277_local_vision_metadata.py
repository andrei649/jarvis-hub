"""Exact local model metadata drives the selected-main image decision."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agents.core.llm import vision_capability
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.egress import llm_async_client


async def _backend(kind: str, handler):
    backend = (LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
               if kind == "lmstudio" else OllamaBackend("http://127.0.0.1:11434", trust_env=False))
    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio" if kind == "lmstudio" else "ollama",
        base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(handler),
    )
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize(("vision", "expected"), [(True, True), (False, False)])
async def test_lm_studio_v1_exact_model_boolean(vision, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"models": [
            {"key": "another-model", "type": "llm", "capabilities": {"vision": not vision}},
            {"key": "local/model", "type": "llm", "capabilities": {"vision": vision}},
        ]})

    backend = await _backend("lmstudio", respond)
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is expected
        assert vision_capability.main_vision_eligibility(backend, "local/model") is expected
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert str(requests[0].url) == "http://127.0.0.1:1234/api/v1/models"
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("model_row", [
    {"key": "local/other", "type": "llm", "capabilities": {"vision": False}},
    {"key": "local/model", "type": "embedding", "capabilities": {"vision": False}},
    {"key": "local/model", "type": "llm", "capabilities": {"vision": "false"}},
    {"key": "local/model", "type": "llm"},
])
async def test_lm_studio_missing_or_malformed_verdict_is_unknown(model_row):
    backend = await _backend("lmstudio", lambda _request: httpx.Response(
        200, json={"models": [model_row]},
    ))
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert vision_capability.main_vision_eligibility(backend, "local/model") is None
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("capabilities", "expected"), [
    (["completion", "vision"], True),
    (["completion"], False),
    ([], None),
    (["completion", 42], None),
])
async def test_ollama_show_exact_model_capabilities(capabilities, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"capabilities": capabilities})

    backend = await _backend("ollama", respond)
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is expected
        assert vision_capability.main_vision_eligibility(backend, "local/model") is expected
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert str(requests[0].url) == "http://127.0.0.1:11434/api/show"
        assert json.loads(requests[0].content) == {"model": "local/model"}
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_failed_refresh_removes_stale_negative_verdict():
    responses = [httpx.Response(200, json={"models": [{
        "key": "local/model", "type": "llm", "capabilities": {"vision": False},
    }]}), httpx.Response(503)]
    backend = await _backend("lmstudio", lambda _request: responses.pop(0))
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is False
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert vision_capability.main_vision_eligibility(backend, "local/model") is None
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_proxy_transport_does_not_receive_model_identity():
    backend = LMStudioBackend("http://127.0.0.1:1234", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        proxy="http://proxy.invalid:8080",
    )
    proxied = []
    proxy = backend.client._transport_for_url(httpx.URL(backend.base_url))

    async def offline(request):
        proxied.append(request)
        return httpx.Response(200, json={"models": []})

    proxy.handle_async_request = offline
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert proxied == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_late_proxy_mount_is_refused_before_metadata_io():
    from httpx._utils import URLPattern

    direct, proxied = [], []
    backend = await _backend("lmstudio", lambda request: (
        direct.append(request), httpx.Response(200, json={"models": []})
    )[1])
    proxy = httpx.AsyncHTTPTransport(proxy="http://proxy.invalid:8080", trust_env=False)

    async def offline(request):
        proxied.append(request)
        return httpx.Response(200, json={"models": []})

    proxy.handle_async_request = offline

    async def reroute(_request):
        backend.client._mounts[URLPattern("http://127.0.0.1:1234")] = proxy

    backend.client.event_hooks["request"].insert(0, reroute)
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert direct == proxied == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_ollama_metadata_body_is_bound_to_selected_model():
    sent = []
    backend = await _backend("ollama", lambda request: (
        sent.append(request), httpx.Response(200, json={"capabilities": ["vision"]})
    )[1])

    async def switch_model(request):
        request._content = json.dumps({"model": "different/model"}).encode()

    backend.client.event_hooks["request"].insert(0, switch_model)
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert sent == []
        assert vision_capability.main_vision_eligibility(backend, "local/model") is None
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_metadata_redirect_is_not_followed():
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://remote.invalid/models"})

    backend = await _backend("lmstudio", redirect)
    backend.client.follow_redirects = True
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert len(requests) == 1
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_off_loopback_backend_never_probes_metadata():
    requests = []
    backend = LMStudioBackend("https://remote.invalid", trust_env=False)
    await backend.client.aclose()
    backend.client = llm_async_client(
        "lm-studio", base_url=backend.base_url, trust_env=False,
        transport=httpx.MockTransport(
            lambda request: (requests.append(request), httpx.Response(200))[1]
        ),
    )
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
        assert requests == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_oversize_metadata_is_unknown():
    backend = await _backend("lmstudio", lambda _request: httpx.Response(
        200, content=b"x" * (1024 * 1024 + 1),
    ))
    try:
        assert await vision_capability.prepare_local_model_vision(backend, "local/model") is None
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_cancelled_metadata_probe_propagates():
    async def cancel(_request):
        raise asyncio.CancelledError

    backend = await _backend("lmstudio", cancel)
    backend.model_vision_capabilities = {"local/model": False}
    try:
        with pytest.raises(asyncio.CancelledError):
            await vision_capability.prepare_local_model_vision(backend, "local/model")
        assert vision_capability.main_vision_eligibility(backend, "local/model") is None
    finally:
        await backend.aclose()
