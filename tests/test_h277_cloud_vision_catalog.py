"""Selected-main cloud capability evidence stays scoped and offline-testable."""

import asyncio

import httpx
import pytest

from agents.core.llm import vision_catalog
from agents.core.llm.vlm import VLMConfig


def _config(backend="anthropic", model="owner/text",
            base_url="https://api.anthropic.com/v1"):
    wire = {"anthropic": "anthropic_messages", "gemini": "gemini_generate_content",
            "openai-responses": "responses", "xai": "xai_responses"}.get(backend,
                                                                      "chat_completions")
    return VLMConfig(backend=backend, base_url=base_url, model=model,
                     api_key="private-selected-key", is_local=False, wire_mode=wire)


@pytest.mark.parametrize(("entry", "expected"), [
    ({"modalities": {"input": ["text", "image"]}, "attachment": False}, True),
    ({"modalities": {"input": ["text"]}, "attachment": True}, False),
    ({"attachment": False}, False),
    ({"attachment": True}, True),
    ({"modalities": {"input": ["text", 4]}, "attachment": False}, None),
    ({"attachment": "false"}, None),
    ({}, None),
])
def test_catalog_entry_uses_explicit_image_input_evidence(entry, expected):
    assert vision_catalog.entry_vision_verdict(entry) is expected


def test_provider_scope_requires_the_exact_native_endpoint():
    assert vision_catalog.catalog_provider(_config()) == "anthropic"
    assert vision_catalog.catalog_provider(_config(
        "gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta")) == "google"
    assert vision_catalog.catalog_provider(_config(
        "openai-responses", "gpt-4.1", "https://api.openai.com/v1")) == "openai"
    assert vision_catalog.catalog_provider(_config(
        "xai", "grok-4", "https://api.x.ai/v1")) == "xai"
    assert vision_catalog.catalog_provider(_config(
        "openrouter", "vendor/model", "https://openrouter.ai/api/v1")) == "openrouter"
    assert vision_catalog.catalog_provider(_config(
        "openrouter", "vendor/model", "https://proxy.example/api/v1")) is None
    assert vision_catalog.catalog_provider(_config(
        "custom", "vendor/model", "https://openrouter.ai/api/v1")) is None
    assert vision_catalog.catalog_provider(_config(
        "anthropic", "owner/text", "https://proxy.example/v1")) is None


def test_catalog_parsing_is_exact_and_unknown_when_metadata_is_missing():
    payload = {
        "anthropic": {"models": {
            "owner/text": {"modalities": {"input": ["text"]}},
            "owner/vision": {"modalities": {"input": ["text", "image"]}},
            "owner/unknown": {},
        }},
        "openrouter": {"models": {"owner/text": {"attachment": True}}},
    }
    catalog = vision_catalog.parse_catalog(payload)
    assert catalog["anthropic"] == {"owner/text": False, "owner/vision": True}
    assert catalog["openrouter"] == {"owner/text": True}
    assert vision_catalog.parse_catalog({}) is None
    assert vision_catalog.parse_catalog({"anthropic": {"models": []}}) is None


@pytest.mark.asyncio
async def test_catalog_fetch_is_bounded_direct_and_sends_no_credentials(monkeypatch):
    observed = []
    payload = b'{"anthropic":{"models":{"owner/text":{"attachment":false}}}}'

    def respond(request):
        observed.append(request)
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(vision_catalog, "_metadata_transport_factory",
                        lambda: httpx.MockTransport(respond))
    assert await vision_catalog._fetch_catalog() == {"anthropic": {"owner/text": False}}
    assert len(observed) == 1
    request = observed[0]
    assert request.method == "GET" and str(request.url) == vision_catalog.CATALOG_URL
    assert request.content == b""
    assert "authorization" not in request.headers and "cookie" not in request.headers


@pytest.mark.asyncio
async def test_catalog_rejects_redirect_oversize_and_bad_json(monkeypatch):
    for response in (
        httpx.Response(302, headers={"location": "https://other.example/api.json"}),
        httpx.Response(200, content=b"x" * (vision_catalog.MAX_BYTES + 1)),
        httpx.Response(200, content=b"not-json"),
    ):
        monkeypatch.setattr(vision_catalog, "_metadata_transport_factory",
                            lambda response=response: httpx.MockTransport(lambda _: response))
        assert await vision_catalog._fetch_catalog() is None


@pytest.mark.asyncio
async def test_catalog_refuses_an_opaque_transport_before_dispatch(monkeypatch):
    sent = []

    class OpaqueTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            sent.append(request)
            return httpx.Response(200, json={})

    monkeypatch.setattr(vision_catalog, "_metadata_transport_factory", OpaqueTransport)
    assert await vision_catalog._fetch_catalog() is None
    assert sent == []


@pytest.mark.asyncio
async def test_catalog_cache_deduplicates_refresh_and_backs_off_failure(monkeypatch):
    vision_catalog.reset_cache()
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        calls.append("fetch")
        started.set()
        await release.wait()
        return {"anthropic": {"owner/text": False}}

    monkeypatch.setattr(vision_catalog, "_fetch_catalog", fetch)
    first = asyncio.create_task(vision_catalog.ensure_catalog(clock=lambda: 1000.0))
    await started.wait()
    second = asyncio.create_task(vision_catalog.ensure_catalog(clock=lambda: 1000.0))
    release.set()
    await asyncio.gather(first, second)
    assert calls == ["fetch"]
    assert vision_catalog.cached_vision_eligibility(_config()) is False
    await vision_catalog.ensure_catalog(clock=lambda: 1001.0)
    assert calls == ["fetch"]

    async def fail():
        calls.append("fail")
        return None

    monkeypatch.setattr(vision_catalog, "_fetch_catalog", fail)
    await vision_catalog.ensure_catalog(clock=lambda: 1000.0 + vision_catalog.TTL_SECONDS + 1)
    await vision_catalog.ensure_catalog(clock=lambda: 1000.0 + vision_catalog.TTL_SECONDS + 2)
    assert calls == ["fetch", "fail"]
    assert vision_catalog.cached_vision_eligibility(_config()) is False
    vision_catalog.reset_cache()


@pytest.mark.asyncio
async def test_reset_during_fetch_cannot_restore_a_stale_catalog(monkeypatch):
    vision_catalog.reset_cache()
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch():
        started.set()
        await release.wait()
        return {"anthropic": {"owner/text": False}}

    monkeypatch.setattr(vision_catalog, "_fetch_catalog", fetch)
    task = asyncio.create_task(vision_catalog.ensure_catalog(clock=lambda: 10.0))
    await started.wait()
    vision_catalog.reset_cache()
    release.set()
    await task
    assert vision_catalog.cached_vision_eligibility(_config()) is None


@pytest.mark.asyncio
async def test_unexpected_fetch_error_is_backed_off_as_unknown(monkeypatch):
    vision_catalog.reset_cache()
    calls = []

    async def fail():
        calls.append("failed")
        raise RuntimeError("synthetic transport failure")

    monkeypatch.setattr(vision_catalog, "_fetch_catalog", fail)
    await vision_catalog.ensure_catalog(clock=lambda: 10.0)
    await vision_catalog.ensure_catalog(clock=lambda: 11.0)
    assert calls == ["failed"]
    assert vision_catalog.cached_vision_eligibility(_config()) is None
    vision_catalog.reset_cache()
