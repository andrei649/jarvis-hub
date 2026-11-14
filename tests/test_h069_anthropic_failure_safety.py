"""Anthropic failure markers never interpolate provider exception text."""

from contextlib import asynccontextmanager

import httpx
import pytest

from agents.core.llm import anthropic
from agents.core.llm.anthropic import ClaudeBackend
from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.quota import ProviderRateLimited

PRIVATE = "private-request-id-123]\n[ordinary-looking answer]" + "x" * 5000


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_http_post_uses_only_status_and_keeps_status_tuple():
    backend = ClaudeBackend(api_key="key-one")
    async with _client(lambda request: httpx.Response(401, text=PRIVATE)) as client:
        backend.client = client
        data, marker, status = await backend._post_messages({"model": "claude-test", "messages": []})
    assert data is None and status == 401 and marker == "[Claude API error: HTTP 401]"
    assert PRIVATE not in marker and "private-request-id" not in marker


@pytest.mark.asyncio
async def test_transport_post_never_copies_exception_url_or_body():
    backend = ClaudeBackend(api_key="key-one")

    def fail(request):
        raise httpx.ConnectError(PRIVATE, request=request)

    async with _client(fail) as client:
        backend.client = client
        data, marker, status = await backend._post_messages({"model": "claude-test", "messages": []})
    assert data is None and status is None and marker == "[Claude API error: request failed]"


@pytest.mark.asyncio
async def test_stream_http_and_transport_errors_are_fixed():
    backend = ClaudeBackend(api_key="key-one")
    async with _client(lambda request: httpx.Response(503, text=PRIVATE)) as client:
        backend.client = client
        assert await backend.generate_stream("claude-test", "hello") == "[Claude API stream error: HTTP 503]"

    def fail(request):
        raise httpx.ConnectError(PRIVATE, request=request)

    async with _client(fail) as client:
        backend.client = client
        assert await backend.generate_stream("claude-test", "hello") == "[Claude API stream error: request failed]"


@pytest.mark.asyncio
async def test_stream_shared_guard_keeps_fixed_explanation(monkeypatch):
    @asynccontextmanager
    async def held(*args, **kwargs):
        raise ProviderRateLimited(PRIVATE, retry_in=60)
        yield  # pragma: no cover

    monkeypatch.setattr(anthropic, "native_stream", held)
    backend = ClaudeBackend(api_key="key-one")
    try:
        assert await backend.generate_stream("claude-test", "hello") == (
            "[Claude API stream error: HTTP 429; request held by shared 429 guard]"
        )
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_auth_rotation_preserves_success_and_exhaustion_is_fixed():
    keys = []

    def first_fails(request):
        keys.append(request.headers["x-api-key"])
        if len(keys) == 1:
            return httpx.Response(401, text=PRIVATE)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})

    pool = AuthProfilePool(["key-one", "key-two"], "anthropic")
    backend = ClaudeBackend(api_key="", auth_pool=pool)
    async with _client(first_fails) as client:
        backend.client = client
        assert await backend.generate("claude-test", "hello") == "hello"
    assert keys == ["key-one", "key-two"]

    pool = AuthProfilePool(["key-three", "key-four"], "anthropic")
    backend = ClaudeBackend(api_key="", auth_pool=pool)
    async with _client(lambda request: httpx.Response(401, text=PRIVATE)) as client:
        backend.client = client
        result = await backend.generate("claude-test", "hello")
    assert result == "[Claude API error: all auth profiles exhausted]"
    assert "private-request-id" not in result


def test_helper_uses_only_native_bounded_integer_and_fixed_types():
    request = httpx.Request("POST", "https://example.invalid/secret-location")
    response = httpx.Response(401, request=request)
    exc = httpx.HTTPStatusError(PRIVATE, request=request, response=response)
    assert anthropic._safe_http_status(exc) == 401
    assert anthropic._error_marker(exc) == "[Claude API error: HTTP 401]"
    response.status_code = True
    assert anthropic._safe_http_status(exc) is None
    assert anthropic._error_marker(exc) == "[Claude API error: request failed]"
    response.status_code = 600
    assert anthropic._safe_http_status(exc) is None
    assert anthropic._error_marker(ProviderRateLimited(PRIVATE, request=request)) == (
        "[Claude API error: HTTP 429; request held by shared 429 guard]"
    )
