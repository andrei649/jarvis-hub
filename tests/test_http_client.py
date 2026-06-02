"""
tests/test_http_client.py — Unit tests for PluginHTTPClient (H7.3).

All HTTP calls are mocked — no real network access.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.core.http_client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_TOTAL_TIMEOUT,
    PluginHTTPClient,
    PluginTimeouts,
    _clients,
)
from agents.core.resilience import CircuitBreaker


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Build a fake httpx.Response without a real HTTP connection."""
    content = b"{}" if json_data is None else __import__("json").dumps(json_data).encode()
    return httpx.Response(status_code=status_code, content=content)


def _make_client_with_mock(status_code: int = 200, side_effect=None) -> tuple[PluginHTTPClient, MagicMock]:
    """Return a PluginHTTPClient whose underlying httpx.AsyncClient is mocked."""
    mock_httpx = MagicMock(spec=httpx.AsyncClient)
    mock_httpx.is_closed = False

    response = _make_response(status_code)
    if side_effect is not None:
        mock_httpx.get = AsyncMock(side_effect=side_effect)
        mock_httpx.post = AsyncMock(side_effect=side_effect)
    else:
        mock_httpx.get = AsyncMock(return_value=response)
        mock_httpx.post = AsyncMock(return_value=response)

    plugin_name = f"_test_{id(mock_httpx)}"
    client = PluginHTTPClient(plugin_name=plugin_name)
    client._client = mock_httpx
    return client, mock_httpx


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_client_registry():
    """Ensure each test starts with a clean plugin registry."""
    _clients.clear()
    yield
    _clients.clear()


# ── test_default_timeouts_applied ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_default_timeouts_applied():
    """PluginTimeouts should encode connect=5 and read=30 into httpx.Timeout."""
    timeouts = PluginTimeouts()
    assert timeouts.connect == DEFAULT_CONNECT_TIMEOUT  # 5.0
    assert timeouts.read == DEFAULT_READ_TIMEOUT         # 30.0
    assert timeouts.total == DEFAULT_TOTAL_TIMEOUT       # 60.0

    httpx_timeout = timeouts.to_httpx_timeout()
    assert httpx_timeout.connect == 5.0
    assert httpx_timeout.read == 30.0


@pytest.mark.asyncio
async def test_default_timeout_passed_to_get():
    """get() should pass the default httpx.Timeout when caller does not supply one."""
    client, mock_httpx = _make_client_with_mock()

    await client.get("https://example.com/test")

    call_kwargs = mock_httpx.get.call_args.kwargs
    timeout = call_kwargs.get("timeout")
    assert isinstance(timeout, httpx.Timeout), "timeout kwarg must be an httpx.Timeout"
    assert timeout.connect == DEFAULT_CONNECT_TIMEOUT
    assert timeout.read == DEFAULT_READ_TIMEOUT


@pytest.mark.asyncio
async def test_caller_supplied_timeout_is_not_overridden():
    """If the caller explicitly sets timeout=, the client must not overwrite it."""
    client, mock_httpx = _make_client_with_mock()
    custom = httpx.Timeout(timeout=3.0)

    await client.get("https://example.com/test", timeout=custom)

    call_kwargs = mock_httpx.get.call_args.kwargs
    assert call_kwargs["timeout"] is custom


# ── test_retry_on_transient_failure ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_records_success():
    """A successful call should record success on the circuit breaker."""
    client, _ = _make_client_with_mock(status_code=200)

    await client.get("https://example.com/ok")

    assert client.circuit_breaker.failure_count == 0
    assert client.circuit_breaker.state == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_records_failure_on_exception():
    """A connection error should record a failure on the circuit breaker."""
    client, _ = _make_client_with_mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(httpx.ConnectError):
        await client.get("https://example.com/fail")

    assert client.circuit_breaker.failure_count == 1


# ── test_circuit_breaker_opens ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    """After failure_threshold consecutive failures the breaker should open."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    client = PluginHTTPClient(plugin_name="_test_cb_opens", circuit_breaker=cb)

    mock_httpx = MagicMock(spec=httpx.AsyncClient)
    mock_httpx.is_closed = False
    mock_httpx.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client._client = mock_httpx

    for _ in range(3):
        with pytest.raises(httpx.ConnectError):
            await client.get("https://example.com/fail")

    assert cb.state == "open"


@pytest.mark.asyncio
async def test_open_circuit_breaker_raises_runtime_error_without_calling_http():
    """Once open, the circuit breaker must fail-fast without making any HTTP call."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=9999.0)
    cb.record_failure()  # force open
    assert cb.state == "open"

    client = PluginHTTPClient(plugin_name="_test_cb_failfast", circuit_breaker=cb)
    mock_httpx = MagicMock(spec=httpx.AsyncClient)
    mock_httpx.is_closed = False
    mock_httpx.get = AsyncMock(return_value=_make_response(200))
    client._client = mock_httpx

    with pytest.raises(RuntimeError, match="Circuit breaker open"):
        await client.get("https://example.com/")

    mock_httpx.get.assert_not_called()


# ── test_for_plugin_returns_same_instance ─────────────────────────────────────

def test_for_plugin_returns_same_instance():
    """Two calls to for_plugin with the same name must return the identical object."""
    a = PluginHTTPClient.for_plugin("same_plugin")
    b = PluginHTTPClient.for_plugin("same_plugin")
    assert a is b


def test_for_plugin_same_circuit_breaker():
    """Both handles must share exactly the same CircuitBreaker instance."""
    a = PluginHTTPClient.for_plugin("cb_shared_plugin")
    b = PluginHTTPClient.for_plugin("cb_shared_plugin")
    assert a.circuit_breaker is b.circuit_breaker


def test_for_plugin_different_names_different_instances():
    """Different plugin names must yield different client objects."""
    a = PluginHTTPClient.for_plugin("plugin_alpha")
    b = PluginHTTPClient.for_plugin("plugin_beta")
    assert a is not b
    assert a.circuit_breaker is not b.circuit_breaker


# ── test_async_context_manager ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_context_manager_closes_client():
    """Using PluginHTTPClient as context manager should close the underlying client."""
    async with PluginHTTPClient.for_plugin("_ctx_test") as client:
        assert client.plugin_name == "_ctx_test"

    # After __aexit__, the underlying httpx client (if created) must be closed.
    # The client was never actually used so _client is None — that is fine.
    assert client._client is None or client._client.is_closed


# ── test_custom_timeouts ──────────────────────────────────────────────────────

def test_custom_timeouts_preserved():
    """PluginHTTPClient must honour custom timeouts passed at construction."""
    custom_timeouts = PluginTimeouts(connect=1.0, read=5.0, total=10.0)
    client = PluginHTTPClient(plugin_name="_custom_timeout_test", timeouts=custom_timeouts)

    assert client.timeouts.connect == 1.0
    assert client.timeouts.read == 5.0
    assert client.timeouts.total == 10.0

    httpx_t = client.timeouts.to_httpx_timeout()
    assert httpx_t.connect == 1.0
    assert httpx_t.read == 5.0


# ── test_post_method ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_passes_default_timeout():
    """post() should also pass the default httpx.Timeout."""
    client, mock_httpx = _make_client_with_mock()

    await client.post("https://example.com/api", json={"key": "value"})

    call_kwargs = mock_httpx.post.call_args.kwargs
    timeout = call_kwargs.get("timeout")
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == DEFAULT_CONNECT_TIMEOUT
    assert timeout.read == DEFAULT_READ_TIMEOUT
