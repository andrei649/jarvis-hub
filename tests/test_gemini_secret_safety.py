"""Secret-safety regressions for Gemini backend and plugin failures."""

from __future__ import annotations

import inspect
import logging
from typing import Any

import httpx
import pytest

from agents.core.llm.auth_rotation import AuthProfilePool
from agents.core.llm.gemini import GeminiBackend
from agents.core.plugins.cloud_llm import CloudLLMPlugin
from agents.core.resilience import _circuit_breakers

API_KEY_SENTINEL = "API_KEY_SENTINEL_7e31"
URL_SENTINEL = "MODEL_URL_SENTINEL_91ac"
PROMPT_SENTINEL = "PROMPT_SENTINEL_02bf"
BODY_SENTINEL = "BODY_SENTINEL_f433"

EXPECTED_DEGRADED_REPLY = "[Gemini error: provider request failed]"
ALL_SENTINELS = (API_KEY_SENTINEL, URL_SENTINEL, PROMPT_SENTINEL, BODY_SENTINEL)
RAW_FAILURE = " ".join(ALL_SENTINELS)


@pytest.fixture(autouse=True)
def _reset_gemini_resilience_breaker():
    _circuit_breakers.pop("plugin:gemini", None)
    yield
    _circuit_breakers.pop("plugin:gemini", None)


def _assert_secret_safe(value: str) -> None:
    assert all(sentinel not in value for sentinel in ALL_SENTINELS)


def _assert_degraded_constant() -> None:
    try:
        from agents.core.llm.provider_errors import GEMINI_DEGRADED_REPLY
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"stable Gemini degraded reply is missing: {exc}")
    assert GEMINI_DEGRADED_REPLY == EXPECTED_DEGRADED_REPLY


def test_provider_failure_log_omits_exception_details(caplog):
    try:
        from agents.core.llm.provider_errors import log_provider_failure
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"provider-safe failure logger is missing: {exc}")

    response = _HTTPFailureResponse(
        500,
        f"https://example.test/{URL_SENTINEL}?key={API_KEY_SENTINEL}",
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()

    logger = logging.getLogger("test.gemini.provider_failure")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        log_provider_failure(
            logger,
            provider="Gemini",
            operation="generate",
            exc=caught.value,
            level=logging.DEBUG,
        )

    _assert_secret_safe(caplog.text)
    assert "HTTPStatusError" in caplog.text
    assert "status=500" in caplog.text


class _HTTPFailureResponse:
    def __init__(self, status_code: int, request_url: str) -> None:
        request = httpx.Request("POST", request_url)
        self.status_code = status_code
        self._response = httpx.Response(
            status_code,
            request=request,
            text=BODY_SENTINEL,
        )

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            RAW_FAILURE,
            request=self._response.request,
            response=self._response,
        )

    def json(self) -> dict[str, Any]:
        return {}


class _StreamContext:
    def __init__(self, response: _HTTPFailureResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _HTTPFailureResponse:
        return self.response

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.asyncio
async def test_generate_uses_header_auth_and_sanitizes_http_failure(monkeypatch, caplog):
    calls = []

    async def fail_post(_client, url, **kwargs):
        calls.append({"url": str(url), **kwargs})
        return _HTTPFailureResponse(500, str(url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_post)
    backend = GeminiBackend(
        api_key="",
        auth_pool=AuthProfilePool([API_KEY_SENTINEL], "gemini"),
    )
    with caplog.at_level(logging.DEBUG):
        try:
            result = await backend.generate(URL_SENTINEL, PROMPT_SENTINEL)
        finally:
            await backend.close()

    assert result == EXPECTED_DEGRADED_REPLY
    assert calls[0]["headers"]["x-goog-api-key"] == API_KEY_SENTINEL
    assert "?key=" not in calls[0]["url"]
    assert "key" not in calls[0].get("params", {})
    _assert_secret_safe(result)
    _assert_secret_safe(caplog.text)
    _assert_degraded_constant()


@pytest.mark.asyncio
async def test_stream_uses_header_auth_and_sanitizes_http_failure(monkeypatch, caplog):
    calls = []

    def fail_stream(_client, method, url, **kwargs):
        calls.append({"method": method, "url": str(url), **kwargs})
        return _StreamContext(_HTTPFailureResponse(500, str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fail_stream)
    backend = GeminiBackend(api_key=API_KEY_SENTINEL)
    with caplog.at_level(logging.DEBUG):
        try:
            result = await backend.generate_stream(URL_SENTINEL, PROMPT_SENTINEL)
        finally:
            await backend.close()

    assert result == EXPECTED_DEGRADED_REPLY
    assert calls[0]["headers"]["x-goog-api-key"] == API_KEY_SENTINEL
    assert "?key=" not in calls[0]["url"]
    assert "key" not in calls[0].get("params", {})
    _assert_secret_safe(result)
    _assert_secret_safe(caplog.text)


@pytest.mark.asyncio
async def test_non_http_transport_failure_is_sanitized(monkeypatch, caplog):
    calls = []

    async def fail_post(_client, url, **kwargs):
        calls.append({"url": str(url), **kwargs})
        raise RuntimeError(RAW_FAILURE)

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_post)
    backend = GeminiBackend(api_key=API_KEY_SENTINEL)
    with caplog.at_level(logging.DEBUG):
        try:
            result = await backend.generate(URL_SENTINEL, PROMPT_SENTINEL)
        finally:
            await backend.close()

    assert result == EXPECTED_DEGRADED_REPLY
    assert calls[0]["headers"]["x-goog-api-key"] == API_KEY_SENTINEL
    assert "?key=" not in calls[0]["url"]
    assert "key" not in calls[0].get("params", {})
    _assert_secret_safe(result)
    _assert_secret_safe(caplog.text)


class _FailingPluginClient:
    def __init__(self) -> None:
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": str(url), **kwargs})
        raise RuntimeError(RAW_FAILURE)


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_cloud_plugin_uses_header_and_sanitizes_retry_exhaustion(monkeypatch):
    monkeypatch.setattr("agents.core.resilience.asyncio.sleep", _no_sleep)
    plugin = CloudLLMPlugin(gemini_key=API_KEY_SENTINEL)
    client = _FailingPluginClient()
    plugin.client = client

    result = await plugin.generate(
        PROMPT_SENTINEL,
        BODY_SENTINEL,
        model=URL_SENTINEL,
        agent_id="jarvis",
    )

    assert result == EXPECTED_DEGRADED_REPLY
    assert len(client.calls) == 3
    assert all(call["headers"]["x-goog-api-key"] == API_KEY_SENTINEL for call in client.calls)
    assert all("?key=" not in call["url"] for call in client.calls)
    assert all("key" not in call.get("params", {}) for call in client.calls)
    _assert_secret_safe(result)


@pytest.mark.asyncio
async def test_gemini_sentinels_absent_from_debug_logs(monkeypatch, caplog):
    monkeypatch.setattr("agents.core.resilience.asyncio.sleep", _no_sleep)
    plugin = CloudLLMPlugin(gemini_key=API_KEY_SENTINEL)
    plugin.client = _FailingPluginClient()

    with caplog.at_level(logging.DEBUG):
        result = await plugin.generate(
            PROMPT_SENTINEL,
            BODY_SENTINEL,
            model=URL_SENTINEL,
            agent_id="jarvis",
        )

    assert result == EXPECTED_DEGRADED_REPLY
    _assert_secret_safe(caplog.text)


def test_gemini_sources_never_construct_key_query():
    source = "\n".join(
        (
            inspect.getsource(GeminiBackend),
            inspect.getsource(CloudLLMPlugin._call_gemini),
        )
    )

    assert "?key=" not in source


def test_gemini_backend_source_never_constructs_key_query():
    assert "?key=" not in inspect.getsource(GeminiBackend)
