"""
tests/test_http_client.py — Unit tests for PluginHTTPClient (H7.3).

All HTTP calls are mocked — no real network access.
"""

import asyncio
import inspect
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.core import http_client as http_client_module
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


def _make_client_with_mock(status_code: int = 200, side_effect=None) -> tuple[PluginHTTPClient, SimpleNamespace]:
    """Return a client backed by a recording pinned transport, never the generic pool."""
    recorder = SimpleNamespace(requests=[])
    response = _make_response(status_code)

    def handler(request):
        recorder.requests.append(request)
        if side_effect is not None:
            raise side_effect
        return httpx.Response(response.status_code, content=response.content, request=request)

    plugin_name = f"_test_{id(recorder)}"
    client = PluginHTTPClient(
        plugin_name=plugin_name,
        resolver=lambda _host, *, mode: (["93.184.216.34"], None),
        transport_factory=lambda _target: httpx.MockTransport(handler),
    )
    return client, recorder


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

    [request] = mock_httpx.requests
    assert request.url.host == "93.184.216.34"
    assert request.extensions["timeout"]["connect"] == DEFAULT_CONNECT_TIMEOUT
    assert request.extensions["timeout"]["read"] == DEFAULT_READ_TIMEOUT


@pytest.mark.asyncio
async def test_caller_supplied_timeout_is_not_overridden():
    """If the caller explicitly sets timeout=, the client must not overwrite it."""
    client, mock_httpx = _make_client_with_mock()
    custom = httpx.Timeout(timeout=3.0)

    await client.get("https://example.com/test", timeout=custom)

    [request] = mock_httpx.requests
    assert request.extensions["timeout"]["connect"] == 3.0


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

    calls = []
    client._resolver = lambda _host, *, mode: (["93.184.216.34"], None)
    client._transport_factory = lambda _target: httpx.MockTransport(
        lambda request: calls.append(request) or (_ for _ in ()).throw(httpx.ConnectError("refused"))
    )

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
    calls = []
    client._resolver = lambda _host, *, mode: (["93.184.216.34"], None)
    client._transport_factory = lambda _target: httpx.MockTransport(lambda request: calls.append(request))

    with pytest.raises(RuntimeError, match="Circuit breaker open"):
        await client.get("https://example.com/")

    assert calls == []


@pytest.mark.asyncio
async def test_open_post_breaker_log_omits_request_url(caplog):
    request_url = "https://example.com/REQUEST_URL_SENTINEL_017a?key=secret"
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=9999.0)
    cb.record_failure()
    client = PluginHTTPClient(plugin_name="_test_post_log_safe", circuit_breaker=cb)

    with caplog.at_level(logging.DEBUG, logger="jarvis.http_client"), \
            pytest.raises(RuntimeError, match="Circuit breaker open"):
        await client.post(request_url)

    assert "REQUEST_URL_SENTINEL_017a" not in caplog.text
    assert "?key=secret" not in caplog.text
    assert "_test_post_log_safe" in caplog.text


def test_http_client_source_never_requests_traceback_logging():
    source = inspect.getsource(http_client_module)

    assert "exc_info=True" not in source


def test_kernel_hook_failure_log_omits_url_and_traceback(monkeypatch, caplog):
    request_url = "https://example.com/REQUEST_URL_SENTINEL_b814?key=QUERY_SECRET_SENTINEL_d722"

    def fail_with_request(_plugin, _method, url, _host):
        raise RuntimeError(f"KERNEL_EXCEPTION_SENTINEL_5b31 {url}")

    monkeypatch.setattr(http_client_module, "_EGRESS_KERNEL_HOOK", fail_with_request)
    client = PluginHTTPClient(plugin_name="_test_kernel_log_safe")

    with caplog.at_level(logging.DEBUG, logger="jarvis.http_client"):
        client._guard("POST", request_url)

    assert "REQUEST_URL_SENTINEL_b814" not in caplog.text
    assert "QUERY_SECRET_SENTINEL_d722" not in caplog.text
    assert "KERNEL_EXCEPTION_SENTINEL_5b31" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "egress kernel hook" in caplog.text
    assert "RuntimeError" in caplog.text


def test_monitor_failure_log_omits_exception_and_traceback(monkeypatch, caplog):
    def fail_record(*_args, **_kwargs):
        raise RuntimeError("MONITOR_EXCEPTION_SENTINEL_95ea")

    monkeypatch.setattr(http_client_module.EGRESS_MONITOR, "record", fail_record)

    with caplog.at_level(logging.DEBUG, logger="jarvis.http_client"):
        http_client_module._record_egress(
            "_test_monitor_log_safe",
            "example.com",
            "GET",
            allowed=True,
            local=False,
        )

    assert "MONITOR_EXCEPTION_SENTINEL_95ea" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "egress monitor record" in caplog.text
    assert "RuntimeError" in caplog.text


def test_audit_failure_log_omits_exception_and_traceback(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")

    def fail_audit(_plugin, _violation):
        raise RuntimeError("AUDIT_EXCEPTION_SENTINEL_220c")

    monkeypatch.setattr(http_client_module, "_EGRESS_AUDIT_SINK", fail_audit)
    client = PluginHTTPClient(plugin_name="weather")

    with caplog.at_level(logging.DEBUG, logger="jarvis.http_client"):
        client._enforce_egress("https://evil.example/path?key=QUERY_SECRET_SENTINEL_96bd")

    assert "AUDIT_EXCEPTION_SENTINEL_220c" not in caplog.text
    assert "QUERY_SECRET_SENTINEL_96bd" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "egress downgrade audit" in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_close_failure_log_omits_exception_and_traceback(caplog):
    class FailingClient:
        async def close(self):
            raise RuntimeError("CLOSE_EXCEPTION_SENTINEL_b725")

    _clients["_test_close_log_safe"] = FailingClient()

    with caplog.at_level(logging.DEBUG, logger="jarvis.http_client"):
        await http_client_module.close_all()

    assert "CLOSE_EXCEPTION_SENTINEL_b725" not in caplog.text
    assert "Traceback" not in caplog.text
    assert "plugin http client close" in caplog.text
    assert "RuntimeError" in caplog.text


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

    [request] = mock_httpx.requests
    assert request.extensions["timeout"]["connect"] == DEFAULT_CONNECT_TIMEOUT
    assert request.extensions["timeout"]["read"] == DEFAULT_READ_TIMEOUT
