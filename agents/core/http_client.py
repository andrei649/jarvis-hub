"""
http_client.py — Centralized HTTP client for all plugins.

Provides a single PluginHTTPClient class that wraps httpx.AsyncClient with:
- Consistent default timeouts (connect=5s, read=30s, total=60s)
- Per-plugin CircuitBreaker from the resilience module
- Integration with @resilient_call for retry + exponential backoff
- Async context manager support

Usage:
    async with PluginHTTPClient.for_plugin("weather") as client:
        resp = await client.get("https://wttr.in/London")

    # Or reuse a cached instance:
    client = PluginHTTPClient.for_plugin("weather")
    resp = await client.get("https://wttr.in/London")
"""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from .resilience import CircuitBreaker, get_circuit_breaker

logger = logging.getLogger("jarvis.http_client")

# Default timeouts applied to all plugin HTTP calls
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_TOTAL_TIMEOUT = 60.0

# Registry of per-plugin clients (cached for reuse)
_clients: dict[str, "PluginHTTPClient"] = {}


@dataclass
class PluginTimeouts:
    """Timeout configuration for a PluginHTTPClient."""
    connect: float = DEFAULT_CONNECT_TIMEOUT
    read: float = DEFAULT_READ_TIMEOUT
    total: float = DEFAULT_TOTAL_TIMEOUT

    def to_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect,
            read=self.read,
            write=self.total,
            pool=self.total,
        )


class PluginHTTPClient:
    """
    Centralized async HTTP client for plugins.

    Wraps httpx.AsyncClient with consistent default timeouts and a per-plugin
    CircuitBreaker.  The @resilient_call decorator (used by plugin methods)
    handles retry + backoff — this class provides the underlying HTTP transport.

    Thread/task safety: each plugin keeps its own httpx.AsyncClient (not shared
    across plugins) so connection pools stay bounded.
    """

    def __init__(
        self,
        plugin_name: str,
        timeouts: Optional[PluginTimeouts] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.plugin_name = plugin_name
        self.timeouts = timeouts or PluginTimeouts()
        self.circuit_breaker = circuit_breaker or get_circuit_breaker(
            f"http_client:{plugin_name}"
        )
        self._client: Optional[httpx.AsyncClient] = None

    # ── Factory ────────────────────────────────────────────────────

    @classmethod
    def for_plugin(
        cls,
        plugin_name: str,
        timeouts: Optional[PluginTimeouts] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> "PluginHTTPClient":
        """
        Return (or create and cache) a PluginHTTPClient for *plugin_name*.

        The same CircuitBreaker instance is reused across calls so the breaker
        state persists between requests.
        """
        if plugin_name not in _clients:
            _clients[plugin_name] = cls(
                plugin_name=plugin_name,
                timeouts=timeouts,
                circuit_breaker=circuit_breaker,
            )
        return _clients[plugin_name]

    # ── Underlying httpx client ────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        """Return the underlying httpx.AsyncClient, creating it if needed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeouts.to_httpx_timeout(),
            )
        return self._client

    # ── HTTP methods ───────────────────────────────────────────────

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Perform a GET request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            logger.debug(
                "Circuit breaker open for plugin '%s', refusing GET %s",
                self.plugin_name, url,
            )
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().get(url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Perform a POST request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            logger.debug(
                "Circuit breaker open for plugin '%s', refusing POST %s",
                self.plugin_name, url,
            )
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().post(url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Perform a PUT request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().put(url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """Perform a PATCH request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().patch(url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Perform a DELETE request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().delete(url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Perform a generic HTTP request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._get_client().request(method, url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    # ── Lifecycle ──────────────────────────────────────────────────

    async def close(self):
        """Close the underlying httpx client and remove from registry.

        Gracefully ignores RuntimeError raised when the event loop is already
        shutting down (e.g. during test teardown).
        """
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except RuntimeError:
                # Event loop may already be closed during teardown — ignore.
                pass
        _clients.pop(self.plugin_name, None)

    async def __aenter__(self) -> "PluginHTTPClient":
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __repr__(self) -> str:
        cb_state = self.circuit_breaker.state
        return (
            f"PluginHTTPClient(plugin={self.plugin_name!r}, "
            f"timeouts={self.timeouts}, cb_state={cb_state!r})"
        )
