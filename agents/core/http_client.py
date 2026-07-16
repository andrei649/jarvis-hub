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

from .observability.egress_monitor import EGRESS_MONITOR
from .resilience import CircuitBreaker, get_circuit_breaker

logger = logging.getLogger("jarvis.http_client")

# B3 — durable audit of a strict-egress *downgrade* (JARVIS_STRICT_EGRESS=0 allowing a
# policy violation). The orchestrator installs an AuditLogger adapter at boot; None = no-op
# (the egress monitor still records the call live either way). Decoupled by design — this
# low-level module never imports the security event types.
_EGRESS_AUDIT_SINK = None


def set_egress_audit_sink(sink) -> None:
    """Install the durable audit sink for strict-egress downgrades. ``sink(plugin, violation)``."""
    global _EGRESS_AUDIT_SINK
    _EGRESS_AUDIT_SINK = sink


# ORIZONT-24 K1 wave-2 — route policy-passing egress through the Action Kernel. The
# orchestrator installs a hook ``(plugin, method, url, host) -> reason|None`` bound to
# kernel.authorize; a non-empty reason BLOCKS the call (kill-switch engaged / over-budget /
# runaway loop). None = no kernel (default). Decoupled by design — this low-level module
# never imports the kernel; the hook itself no-ops unless JARVIS_ACTION_KERNEL is set.
_EGRESS_KERNEL_HOOK = None


def set_egress_kernel_hook(hook) -> None:
    """Install the wave-2 egress→kernel authorization hook, or ``None`` to remove it.

    ``hook(plugin, method, url, host)`` returns a deny-reason ``str`` (block) or a falsy
    value (allow)."""
    global _EGRESS_KERNEL_HOOK
    _EGRESS_KERNEL_HOOK = hook
# Default timeouts applied to all plugin HTTP calls
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_TOTAL_TIMEOUT = 60.0

# Registry of per-plugin clients (cached for reuse)
_clients: dict[str, "PluginHTTPClient"] = {}


class PluginEgressError(PermissionError):
    """A plugin HTTP request violated its manifest's network policy (F-07)."""


def _host_is_local(host: str) -> bool:
    """True if *host* is loopback / private / link-local / mDNS (.local) — i.e. LAN."""
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        return True
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass
    # Hostname (not a literal IP): resolve best-effort; all addresses must be local.
    import socket
    try:
        ips = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except Exception:
        return False
    if not ips:
        return False
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if not (a.is_private or a.is_loopback or a.is_link_local):
            return False
    return True


def _host_of(url: str) -> str:
    """Best-effort hostname from a URL, lower-cased and trailing-dot-stripped."""
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return ""


def _record_egress(plugin: str, host: str, method: str, *, allowed: bool, local: bool, reason: str = "") -> None:
    """Feed the H23.16 network monitor. Never raises — observability must not break egress."""
    try:
        EGRESS_MONITOR.record(plugin, host, method, allowed=allowed, local=local, reason=reason)
    except Exception as exc:  # pragma: no cover - defensive: monitoring is never load-bearing
        logger.debug(
            "egress monitor record failed (type=%s)",
            type(exc).__name__,
        )


def strict_egress_enabled() -> bool:
    """SEC-5: egress is strict by default; opt out only with an explicit falsy
    ``JARVIS_STRICT_EGRESS``. CDX-12: the hardened profile forces strict and
    ignores the downgrade — that layering stays here, not in env_config."""
    from agents.core.env_config import env_flag
    from .security import hardened
    return hardened.strict_egress_forced() or env_flag("JARVIS_STRICT_EGRESS", True)


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

    # ── Egress policy (F-07) ───────────────────────────────────────
    def _enforce_egress(self, url: str) -> None:
        """Enforce the plugin manifest's network policy on an outbound URL.

        Looks up the plugin's manifest (by exact id). Plugins with no manifest
        (internal/ad-hoc clients) are unaffected. ``NONE`` always blocks — a
        no-network plugin making an HTTP call is unambiguously wrong. For ``LAN``
        and ``RESTRICTED`` a host outside the policy is **blocked by default**
        (SEC-5); set ``JARVIS_STRICT_EGRESS=0`` to downgrade to a warning (escape
        hatch if a new host needs allowlisting). ``FULL`` is unrestricted by
        declaration.
        """
        try:
            from agents.core.plugin_gate import (
                BUILTIN_PLUGINS, NetworkAccess, host_in_allowlist, dynamic_domains,
            )
        except Exception:
            return
        manifest = BUILTIN_PLUGINS.get(self.plugin_name)
        if manifest is None:
            return  # no declared policy → unchanged behavior
        na = manifest.network_access
        if na == NetworkAccess.FULL:
            return
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        if na == NetworkAccess.NONE:
            raise PluginEgressError(
                f"egress blocked: plugin '{self.plugin_name}' has no network access (tried {host or url})"
            )
        if na == NetworkAccess.LAN:
            if _host_is_local(host):
                return
            violation = f"plugin '{self.plugin_name}' is LAN-only but '{host}' is not a local address"
        elif na == NetworkAccess.RESTRICTED:
            # SEC-5b: static allowlist ∪ hosts registered at init for config/env-
            # driven plugins (n8n, SearXNG, Signal, Matrix).
            allowed = manifest.allowed_domains + dynamic_domains(self.plugin_name)
            if host and host_in_allowlist(host, allowed):
                return
            violation = (f"plugin '{self.plugin_name}' may not reach '{host}' "
                         f"(allowed: {allowed})")
        else:
            return
        strict = strict_egress_enabled()
        if strict:
            raise PluginEgressError(f"egress blocked: {violation}")
        logger.warning("egress policy violation (JARVIS_STRICT_EGRESS=0, allowing): %s", violation)
        # B3: the downgrade is no longer silent — record a durable, alertable audit event.
        if _EGRESS_AUDIT_SINK is not None:
            try:
                _EGRESS_AUDIT_SINK(self.plugin_name, violation)
            except Exception as exc:  # pragma: no cover - audit must never break egress
                logger.debug(
                    "egress downgrade audit failed (type=%s)",
                    type(exc).__name__,
                )

    def _enforce_kernel(self, method: str, url: str, host: str) -> None:
        """ORIZONT-24 K1 wave-2: mediate policy-passing egress through the Action Kernel.

        The manifest policy (``_enforce_egress``) decides *where* a plugin may reach;
        the kernel adds an orthogonal gate that can DENY otherwise-allowed egress
        (kill-switch engaged → no outbound calls, over-budget, runaway loop). Default-off:
        no hook installed → no-op; the hook itself no-ops unless ``JARVIS_ACTION_KERNEL``.

        The experimental kernel gate must never *brick* egress on a bug — the manifest
        policy already ran — so a hook that raises degrades to allow + a visible warning;
        only an explicit deny-reason blocks.
        """
        hook = _EGRESS_KERNEL_HOOK
        if hook is None:
            return
        try:
            reason = hook(self.plugin_name, method, url, host)
        except Exception as exc:  # pragma: no cover - defensive; a kernel bug can't break egress
            logger.warning(
                "egress kernel hook failed (type=%s); allowing (manifest policy already enforced)",
                type(exc).__name__,
            )
            return
        if reason:
            raise PluginEgressError(f"egress blocked by kernel: {reason}")

    def _guard(self, method: str, url: str) -> None:
        """Enforce egress policy AND record the attempt for the network monitor (H23.16).

        Every verb funnels through here so blocked *and* allowed calls land in the
        ledger — that's what lets the HUD prove a local-only plugin made zero outbound
        calls. A blocked call is recorded before re-raising so the attempt is visible.
        """
        host = _host_of(url)
        local = _host_is_local(host)
        try:
            self._enforce_egress(url)
            self._enforce_kernel(method, url, host)   # wave-2: kernel mediation (default-off)
        except PluginEgressError as e:
            _record_egress(self.plugin_name, host, method, allowed=False, local=local, reason=str(e))
            raise
        _record_egress(self.plugin_name, host, method, allowed=True, local=local)

    # ── HTTP methods ───────────────────────────────────────────────

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Perform a GET request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            logger.debug(
                "Circuit breaker open for plugin '%s', refusing GET",
                self.plugin_name,
            )
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        self._guard("GET", url)
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
                "Circuit breaker open for plugin '%s', refusing POST",
                self.plugin_name,
            )
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        self._guard("POST", url)
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
        self._guard("PUT", url)
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
        self._guard("PATCH", url)
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
        self._guard("DELETE", url)
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
        self._guard(method, url)
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


async def close_all() -> None:
    """Close every registered per-plugin HTTP client (AUD-18 leak closure).

    Each pooled :class:`PluginHTTPClient` holds a long-lived ``httpx.AsyncClient``;
    on graceful shutdown the orchestrator calls this to drain them all. Best-effort
    and order-independent: iterate a snapshot (each ``close()`` mutates ``_clients``)
    and swallow per-client errors so shutdown never raises.
    """
    for client in list(_clients.values()):
        try:
            await client.close()
        except Exception as exc:
            logger.debug(
                "plugin http client close failed (type=%s)",
                type(exc).__name__,
            )
