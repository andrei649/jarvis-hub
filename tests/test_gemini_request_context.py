"""Request-scoped Gemini authentication and cache binding regressions."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any

import httpx
import pytest

from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.gemini import GeminiBackend

_GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


def _request_types():
    try:
        from agents.core.llm.auth_rotation import AuthLease
        from agents.core.llm.gemini_context import GeminiRequestBinding
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"request-scoped Gemini auth interfaces are missing: {exc}")
    return AuthLease, GeminiRequestBinding


def _binding(
    *,
    profile_id: str = "gemini-test",
    api_key: str = "test-key",
    session_id: str | None = "session",
    cache_name: str | None = None,
    invalidate_cache=None,
):
    AuthLease, GeminiRequestBinding = _request_types()
    return GeminiRequestBinding(
        lease=AuthLease(profile_id=profile_id, api_key=api_key),
        session_id=session_id,
        cache_name=cache_name,
        cached_prefix_count=1 if cache_name else 0,
        invalidate_cache=invalidate_cache,
    )


class _Response:
    def __init__(self, status_code: int = 200, data: dict[str, Any] | None = None) -> None:
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
        self.status_code = status_code
        self._response = httpx.Response(status_code, request=request)
        self._data = data or _GEMINI_OK

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self._response.request,
                response=self._response,
            )

    def json(self) -> dict[str, Any]:
        return self._data

    async def aiter_lines(self):
        yield 'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'


class _StreamContext:
    def __init__(self, response: _Response) -> None:
        self.response = response

    async def __aenter__(self) -> _Response:
        return self.response

    async def __aexit__(self, *_args) -> None:
        return None


class _RecordingClient:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.statuses = list(statuses or [200])
        self.calls: list[dict[str, Any]] = []

    def _next_response(self) -> _Response:
        status = self.statuses.pop(0) if self.statuses else 200
        return _Response(status)

    async def post(self, url: str, **kwargs) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self._next_response()

    def stream(self, method: str, url: str, **kwargs) -> _StreamContext:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _StreamContext(self._next_response())

    async def aclose(self) -> None:
        return None


def test_auth_values_are_frozen_and_repr_safe():
    lease = _binding(api_key="API_KEY_SENTINEL_7e31").lease
    binding = _binding(api_key="API_KEY_SENTINEL_7e31", cache_name="cachedContents/safe")

    with pytest.raises(FrozenInstanceError):
        lease.api_key = "replacement"
    with pytest.raises(FrozenInstanceError):
        binding.cache_name = "cachedContents/replacement"
    assert "API_KEY_SENTINEL_7e31" not in repr(lease)
    assert "API_KEY_SENTINEL_7e31" not in repr(binding)


def test_nested_scope_restores_parent():
    backend = GeminiBackend(api_key="fallback")
    parent = _binding(cache_name="cachedContents/parent")
    child = _binding(cache_name="cachedContents/child")

    assert backend.current_binding() is None
    with backend.request_scope(parent):
        assert backend.current_binding() is parent
        with backend.request_scope(child):
            assert backend.current_binding() is child
        assert backend.current_binding() is parent
    assert backend.current_binding() is None


def test_scope_resets_after_exception():
    backend = GeminiBackend(api_key="fallback")
    binding = _binding(cache_name="cachedContents/error")

    with pytest.raises(RuntimeError, match="boom"), backend.request_scope(binding):
        raise RuntimeError("boom")

    assert backend.current_binding() is None


@pytest.mark.asyncio
async def test_scope_resets_after_cancellation():
    backend = GeminiBackend(api_key="fallback")
    binding = _binding(cache_name="cachedContents/cancelled")
    entered = asyncio.Event()
    reset_values = []

    async def worker() -> None:
        try:
            with backend.request_scope(binding):
                entered.set()
                await asyncio.Event().wait()
        finally:
            reset_values.append(backend.current_binding())

    task = asyncio.create_task(worker())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert reset_values == [None]
    assert backend.current_binding() is None


@pytest.mark.asyncio
async def test_concurrent_scopes_do_not_leak_cache_names():
    backend = GeminiBackend(api_key="fallback")
    client = _RecordingClient([200, 200])
    backend.client = client

    first = _binding(profile_id="gemini-first", api_key="key-first", cache_name="cachedContents/first")
    second = _binding(profile_id="gemini-second", api_key="key-second", cache_name="cachedContents/second")

    async def invoke(binding):
        with backend.request_scope(binding):
            await asyncio.sleep(0)
            return await backend.generate("gemini-2.5-flash", "prompt")

    assert await asyncio.gather(invoke(first), invoke(second)) == ["ok", "ok"]
    observed = {
        call["headers"]["x-goog-api-key"]: call["json"].get("cachedContent")
        for call in client.calls
    }
    assert observed == {
        "key-first": "cachedContents/first",
        "key-second": "cachedContents/second",
    }
    assert backend.current_binding() is None


@pytest.mark.asyncio
async def test_uncached_request_inherits_no_previous_cache():
    backend = GeminiBackend(api_key="fallback-key")
    client = _RecordingClient([200, 200])
    backend.client = client

    cached = _binding(cache_name="cachedContents/previous")
    with backend.request_scope(cached):
        assert await backend.generate("gemini-2.5-flash", "cached prompt") == "ok"
    assert await backend.generate("gemini-2.5-flash", "fresh prompt") == "ok"

    assert client.calls[0]["json"]["cachedContent"] == "cachedContents/previous"
    assert "cachedContent" not in client.calls[1]["json"]
    assert client.calls[1]["headers"]["x-goog-api-key"] == "fallback-key"


@pytest.mark.asyncio
async def test_cached_rejection_invalidates_and_retries_generate_once():
    invalidations = 0

    async def invalidate() -> bool:
        nonlocal invalidations
        invalidations += 1
        return True

    backend = GeminiBackend(api_key="fallback")
    client = _RecordingClient([404, 200])
    backend.client = client
    binding = _binding(
        api_key="bound-key",
        cache_name="cachedContents/rejected",
        invalidate_cache=invalidate,
    )

    with backend.request_scope(binding):
        result = await backend.generate("gemini-2.5-flash", "prompt")

    assert result == "ok"
    assert invalidations == 1
    assert len(client.calls) == 2
    assert client.calls[0]["json"]["cachedContent"] == "cachedContents/rejected"
    assert "cachedContent" not in client.calls[1]["json"]
    assert [call["headers"]["x-goog-api-key"] for call in client.calls] == [
        "bound-key",
        "bound-key",
    ]


@pytest.mark.asyncio
async def test_cached_rejection_invalidates_and_retries_stream_once():
    invalidations = 0

    async def invalidate() -> bool:
        nonlocal invalidations
        invalidations += 1
        return True

    backend = GeminiBackend(api_key="fallback")
    client = _RecordingClient([400, 200])
    backend.client = client
    binding = _binding(
        api_key="stream-key",
        cache_name="cachedContents/stream-rejected",
        invalidate_cache=invalidate,
    )

    with backend.request_scope(binding):
        result = await backend.generate_stream("gemini-2.5-flash", "prompt")

    assert result == "ok"
    assert invalidations == 1
    assert len(client.calls) == 2
    assert client.calls[0]["json"]["cachedContent"] == "cachedContents/stream-rejected"
    assert "cachedContent" not in client.calls[1]["json"]
    assert [call["headers"]["x-goog-api-key"] for call in client.calls] == [
        "stream-key",
        "stream-key",
    ]


@pytest.mark.asyncio
async def test_auth_rotation_drops_old_cache_binding():
    pool = AuthProfilePool(["old-key", "new-key"], "gemini")
    backend = GeminiBackend(api_key="", auth_pool=pool)
    client = _RecordingClient([429, 200])
    backend.client = client
    old_binding = _binding(
        profile_id=pool.current().id,
        api_key="old-key",
        cache_name="cachedContents/old-credential",
    )

    with backend.request_scope(old_binding):
        result = await backend.generate("gemini-2.5-flash", "prompt")

    assert result == "ok"
    assert len(client.calls) == 2
    assert client.calls[0]["headers"]["x-goog-api-key"] == "old-key"
    assert client.calls[0]["json"]["cachedContent"] == "cachedContents/old-credential"
    assert client.calls[1]["headers"]["x-goog-api-key"] == "new-key"
    assert "cachedContent" not in client.calls[1]["json"]
    assert pool.current_key() == "new-key"


@pytest.mark.asyncio
async def test_stream_auth_rotation_drops_old_cache_binding():
    pool = AuthProfilePool(["old-key", "new-key"], "gemini")
    backend = GeminiBackend(api_key="", auth_pool=pool)
    client = _RecordingClient([429, 200])
    backend.client = client
    old_binding = _binding(
        profile_id=pool.current().id,
        api_key="old-key",
        cache_name="cachedContents/old-stream-credential",
    )

    with backend.request_scope(old_binding):
        result = await backend.generate_stream("gemini-2.5-flash", "prompt")

    assert result == "ok"
    assert len(client.calls) == 2
    assert client.calls[0]["headers"]["x-goog-api-key"] == "old-key"
    assert client.calls[0]["json"]["cachedContent"] == "cachedContents/old-stream-credential"
    assert client.calls[1]["headers"]["x-goog-api-key"] == "new-key"
    assert "cachedContent" not in client.calls[1]["json"]
    assert pool.current_key() == "new-key"
