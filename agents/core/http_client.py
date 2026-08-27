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

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

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


@dataclass(frozen=True, slots=True)
class PinnedTarget:
    """A logical URL and the one resolver-validated IP that may receive its bytes."""

    logical_url: str
    dial_url: str
    host_header: str
    sni_hostname: str
    pool_key: tuple[str, str, int, str]


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


_local_flag_cache: dict[str, tuple[float, bool]] = {}
_LOCAL_FLAG_TTL = 300.0


def _host_is_local_cached(host: str) -> bool:
    """TTL-cached wrapper for the network-monitor's ``local`` flag.

    ``_host_is_local`` does a blocking, uncached ``getaddrinfo`` for any
    non-literal hostname; that ran on the event loop for *every* outbound plugin
    request. This flag only annotates the egress ledger (not egress enforcement,
    which keeps calling ``_host_is_local`` directly), so a bounded-stale answer
    is fine.
    """
    if not host:
        return False
    now = time.monotonic()
    hit = _local_flag_cache.get(host)
    if hit is not None and now - hit[0] < _LOCAL_FLAG_TTL:
        return hit[1]
    val = _host_is_local(host)
    _local_flag_cache[host] = (now, val)
    return val


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


def _address_mode(host: str) -> str:
    """Pick the SSRF address class for a host the egress policy already cleared.

    Self-hosted integrations (n8n, SearXNG, Signal, Matrix) are configured with a
    loopback / RFC1918 *literal* — or the reserved name ``localhost`` — and must
    validate in ``lan`` mode, or local-first deployments cannot reach their own
    services (MOONSHOT §5.1). Every other name stays in ``public`` mode on
    purpose: letting an ordinary DNS name opt into ``lan`` merely because it
    currently resolves somewhere private is precisely the rebinding hole the
    SSRF guard exists to close.
    """
    from .security.ssrf import is_private_ip

    if host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
        return "lan"
    return "lan" if is_private_ip(host) else "public"


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
        *,
        resolver: Callable[..., tuple[list[str], Optional[str]]] | None = None,
        transport_factory: Callable[[PinnedTarget], httpx.AsyncBaseTransport] | None = None,
    ):
        self.plugin_name = plugin_name
        self.timeouts = timeouts or PluginTimeouts()
        self.circuit_breaker = circuit_breaker or get_circuit_breaker(
            f"http_client:{plugin_name}"
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._resolver = resolver
        self._transport_factory = transport_factory
        self._pinned_clients: dict[tuple[str, str, int, str], httpx.AsyncClient] = {}
        self._pinned_targets: list[PinnedTarget] = []

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
        """Return the legacy client for lifecycle compatibility, never for egress I/O."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeouts.to_httpx_timeout(),
                trust_env=False,
            )
        return self._client

    # ── Egress policy (F-07) ───────────────────────────────────────
    def _manifest_mode(self, url: str) -> str:
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
            return "public"
        manifest = BUILTIN_PLUGINS.get(self.plugin_name)
        if manifest is None:
            return "public"
        na = manifest.network_access
        if na == NetworkAccess.FULL:
            return "public"
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        if na == NetworkAccess.NONE:
            raise PluginEgressError(
                f"egress blocked: plugin '{self.plugin_name}' has no network access (tried {host or url})"
            )
        if na == NetworkAccess.LAN:
            return "lan"
        elif na == NetworkAccess.RESTRICTED:
            # SEC-5b: static allowlist ∪ hosts registered at init for config/env-
            # driven plugins (n8n, SearXNG, Signal, Matrix).
            allowed = manifest.allowed_domains + dynamic_domains(self.plugin_name)
            if host and host_in_allowlist(host, allowed):
                return _address_mode(host)
            violation = (f"plugin '{self.plugin_name}' may not reach '{host}' "
                         f"(allowed: {allowed})")
        else:
            return "public"
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
        return _address_mode(host)

    def _enforce_egress(self, url: str) -> None:
        """Legacy synchronous policy probe; request paths use ``_prepare_target``."""
        mode = self._manifest_mode(url)
        if mode == "lan":
            from .security.ssrf import resolve_and_validate

            host = _host_of(url)
            _ips, error = resolve_and_validate(host, mode="lan")
            if error:
                raise PluginEgressError(f"egress blocked: {error}")

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
        local = _host_is_local_cached(host)
        try:
            self._enforce_egress(url)
            self._enforce_kernel(method, url, host)   # wave-2: kernel mediation (default-off)
        except PluginEgressError as e:
            _record_egress(self.plugin_name, host, method, allowed=False, local=local, reason=str(e))
            raise
        _record_egress(self.plugin_name, host, method, allowed=True, local=local)

    async def _prepare_target(self, method: str, url: str) -> PinnedTarget:
        """Resolve and validate off-loop, then construct the only allowed dial target."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            raise PluginEgressError("egress blocked: unsupported URL")
        try:
            mode = self._manifest_mode(url)
            from .security.ssrf import resolve_and_validate

            resolver = self._resolver or resolve_and_validate
            ips, error = await asyncio.to_thread(resolver, host, mode=mode)
            if error or not ips:
                raise PluginEgressError(f"egress blocked: {error or 'empty DNS answer'}")
            normalized_ips = []
            for address in ips:
                validated, literal_error = resolve_and_validate(address, mode=mode)
                if literal_error or not validated:
                    raise PluginEgressError(
                        f"egress blocked: {literal_error or 'empty DNS answer'}"
                    )
                normalized_ips.append(validated[0])
            literal_ip = normalized_ips[0]
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            ip_host = f"[{literal_ip}]" if ":" in literal_ip else literal_ip
            netloc = f"{ip_host}:{port}" if parsed.port else ip_host
            dial_url = parsed._replace(netloc=netloc).geturl()
            host_header = host
            if parsed.port and parsed.port not in {80, 443}:
                host_header = f"{host}:{parsed.port}"
            target = PinnedTarget(
                logical_url=url,
                dial_url=dial_url,
                host_header=host_header,
                sni_hostname=host,
                pool_key=(parsed.scheme, literal_ip, port, host),
            )
            self._enforce_kernel(method, url, host)
        except PluginEgressError as exc:
            _record_egress(self.plugin_name, host, method, allowed=False, local=mode == "lan" if 'mode' in locals() else False, reason=str(exc))
            raise
        _record_egress(self.plugin_name, host, method, allowed=True, local=mode == "lan")
        return target

    def _pinned_client(self, target: PinnedTarget) -> httpx.AsyncClient:
        client = self._pinned_clients.get(target.pool_key)
        if client is None or client.is_closed:
            transport = self._transport_factory(target) if self._transport_factory else None
            client = httpx.AsyncClient(
                timeout=self.timeouts.to_httpx_timeout(),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            )
            self._pinned_clients[target.pool_key] = client
            self._pinned_targets.append(target)
        return client

    @staticmethod
    def _without_headers(headers: dict[str, str], names: set[str]) -> dict[str, str]:
        return {key: value for key, value in headers.items() if key.lower() not in names}

    @staticmethod
    def _cross_origin(left: str, right: str) -> bool:
        a, b = urlparse(left), urlparse(right)
        return (a.scheme, a.hostname, a.port) != (b.scheme, b.hostname, b.port)

    async def _request_pinned(self, method: str, url: str, **kwargs) -> httpx.Response:
        follow_redirects = bool(kwargs.pop("follow_redirects", False))
        headers = dict(kwargs.pop("headers", {}) or {})
        current_method, current_url = method.upper(), url
        for hop in range(21):
            target = await self._prepare_target(current_method, current_url)
            request_headers = {**headers, "Host": target.host_header}
            extensions = {**dict(kwargs.pop("extensions", {}) or {}), "sni_hostname": target.sni_hostname}
            response = await self._pinned_client(target).request(
                current_method,
                target.dial_url,
                headers=request_headers,
                extensions=extensions,
                follow_redirects=False,
                **kwargs,
            )
            if not follow_redirects or response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            await response.aclose()
            if not location or hop == 20:
                return response
            next_url = urljoin(current_url, location)
            cross_origin = self._cross_origin(current_url, next_url)
            if cross_origin:
                headers = self._without_headers(headers, {"authorization", "cookie", "proxy-authorization"})
            if current_method == "POST" and response.status_code in {301, 302, 303}:
                current_method = "GET"
                kwargs = {key: value for key, value in kwargs.items() if key not in {"content", "data", "json", "files"}}
                headers = self._without_headers(headers, {"content-length", "content-type", "transfer-encoding", "expect"})
            elif cross_origin and response.status_code in {307, 308}:
                # Preserve the redirect method but never replay an entity cross-origin.
                kwargs = {key: value for key, value in kwargs.items() if key not in {"content", "data", "json", "files"}}
                headers = self._without_headers(headers, {"content-length", "content-type", "transfer-encoding", "expect"})
            current_url = next_url
        raise PluginEgressError("egress blocked: redirect cap exceeded")

    # ── HTTP methods ───────────────────────────────────────────────

    async def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Shared verb path: breaker check → egress guard → timeout → record.

        Invokes the verb-specific httpx method (``client.get``/``post``/…) so the
        mocked surface in tests is unchanged. The URL is deliberately never logged.
        """
        if self.circuit_breaker.is_open():
            logger.debug(
                "Circuit breaker open for plugin '%s', refusing %s",
                self.plugin_name, method,
            )
            raise RuntimeError(f"Circuit breaker open: plugin={self.plugin_name}")
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._request_pinned(method, url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Perform a GET request with plugin timeouts applied."""
        return await self._send("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Perform a POST request with plugin timeouts applied."""
        return await self._send("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Perform a PUT request with plugin timeouts applied."""
        return await self._send("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """Perform a PATCH request with plugin timeouts applied."""
        return await self._send("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Perform a DELETE request with plugin timeouts applied."""
        return await self._send("DELETE", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Perform a generic HTTP request with plugin timeouts applied."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(
                f"Circuit breaker open: plugin={self.plugin_name}"
            )
        kwargs.setdefault("timeout", self.timeouts.to_httpx_timeout())
        try:
            resp = await self._request_pinned(method, url, **kwargs)
            self.circuit_breaker.record_success()
            return resp
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs):
        """Open a pinned stream; redirects are opt-in and revalidated per hop."""
        if self.circuit_breaker.is_open():
            raise RuntimeError(f"Circuit breaker open: plugin={self.plugin_name}")
        follow_redirects = bool(kwargs.pop("follow_redirects", False))
        headers = dict(kwargs.pop("headers", {}) or {})
        current_method, current_url = method.upper(), url
        for hop in range(21):
            target = await self._prepare_target(current_method, current_url)
            context = self._pinned_client(target).stream(
                current_method,
                target.dial_url,
                headers={**headers, "Host": target.host_header},
                extensions={**dict(kwargs.pop("extensions", {}) or {}), "sni_hostname": target.sni_hostname},
                follow_redirects=False,
                **kwargs,
            )
            response = await context.__aenter__()
            if not follow_redirects or response.status_code not in {301, 302, 303, 307, 308}:
                try:
                    self.circuit_breaker.record_success()
                    yield response
                except Exception:
                    self.circuit_breaker.record_failure()
                    raise
                finally:
                    await context.__aexit__(None, None, None)
                return
            location = response.headers.get("location")
            await context.__aexit__(None, None, None)
            if not location or hop == 20:
                self.circuit_breaker.record_success()
                return
            next_url = urljoin(current_url, location)
            cross_origin = self._cross_origin(current_url, next_url)
            if cross_origin:
                headers = self._without_headers(headers, {"authorization", "cookie", "proxy-authorization"})
            if current_method == "POST" and response.status_code in {301, 302, 303}:
                current_method = "GET"
                kwargs = {key: value for key, value in kwargs.items() if key not in {"content", "data", "json", "files"}}
                headers = self._without_headers(headers, {"content-length", "content-type", "transfer-encoding", "expect"})
            elif cross_origin and response.status_code in {307, 308}:
                kwargs = {key: value for key, value in kwargs.items() if key not in {"content", "data", "json", "files"}}
                headers = self._without_headers(headers, {"content-length", "content-type", "transfer-encoding", "expect"})
            current_url = next_url
        raise PluginEgressError("egress blocked: redirect cap exceeded")

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
        for client in list(self._pinned_clients.values()):
            if not client.is_closed:
                try:
                    await client.aclose()
                except RuntimeError:
                    pass
        self._pinned_clients.clear()
        self._pinned_targets.clear()
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
