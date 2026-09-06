"""IP-pinned browser transport for :mod:`agents.core.browser_playwright` (SEC-B4).

The plugin HTTP client already dials only the resolver-validated IP
(:class:`agents.core.http_client.PinnedTarget`). A browser cannot be given a pinned
socket, but Chromium can be given a *fixed resolver table*: ``--host-resolver-rules``
maps every pinned host to the IP that :func:`agents.core.security.ssrf.resolve_and_validate`
validated and maps every other host to ``~NOTFOUND``. That closes the TOCTOU gap
between "the URL guard resolved host X to a public IP" and "the browser dialed host
X" — a low-TTL rebind cannot swap in a private address, and a redirect, iframe, or
fetch to an unpinned host fails at the resolver, one layer below Playwright's
request interception.

This module owns no policy beyond SSRF. Allowlists, approvals, and the kernel stay
in :mod:`agents.core.browser_agent`. Firefox and WebKit expose no resolver table, so
the pinned transport refuses them with a named reason instead of pretending.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger("jarvis.browser.transport")

ALLOWED_SCHEMES = frozenset({"http", "https"})
PINNED_BROWSERS = frozenset({"chromium"})
PINNED_TRANSPORT_REQUIRES_CHROMIUM = "pinned_transport_requires_chromium"
MODES = ("public", "lan")
DEFAULT_MAX_PINS = 64

_Resolver = Callable[..., tuple[list[str], str | None]]


class BrowserTransportRefused(RuntimeError):
    """The transport refused to bind a host; ``reason`` is a stable, named code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = str(reason)
        self.detail = str(detail or "")
        message = self.reason if not self.detail else f"{self.reason}: {self.detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PinnedTarget:
    """One logical URL and the single validated IP its host may resolve to."""

    host: str
    ip: str
    scheme: str
    port: int
    logical_url: str
    mode: str

    def __post_init__(self) -> None:
        if not self.host or self.host != self.host.lower().rstrip("."):
            raise ValueError("host must be a normalized lowercase hostname")
        try:
            ipaddress.ip_address(self.ip)
        except ValueError:
            raise ValueError(f"ip is not an IP literal: {self.ip!r}") from None
        if self.scheme not in ALLOWED_SCHEMES:
            raise ValueError(f"scheme must be one of {sorted(ALLOWED_SCHEMES)}")
        if not 1 <= int(self.port) <= 65_535:
            raise ValueError("port out of range")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")

    @property
    def resolver_rule(self) -> str:
        """The Chromium ``--host-resolver-rules`` clause for this pin."""
        return f"MAP {self.host} {format_ip_for_rule(self.ip)}"


def format_ip_for_rule(ip: str) -> str:
    """Chromium resolver rules want IPv6 replacements bracketed."""
    return f"[{ip}]" if ":" in ip else ip


def is_private_host_literal(host: str) -> bool:
    """True for loopback names and RFC1918 / loopback / link-local IP literals.

    Hostnames that merely *resolve* to private space are the resolver's job
    (:func:`resolve_and_validate`); this is the cheap literal check the request
    layer can run without touching DNS.
    """
    host = (host or "").lower().rstrip(".").strip("[]")
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        from agents.core.security.ssrf import is_private_ip
    except Exception:  # pragma: no cover - the ssrf module is part of the tree
        return False
    return is_private_ip(host)


class PinnedResolver:
    """Resolve, validate, and remember one IP per host for a Chromium launch.

    ``mode="public"`` accepts only globally routable addresses. ``mode="lan"`` is the
    owner's house-LAN opt-in (``JARVIS_BROWSER_ALLOW_PRIVATE_URLS``): a host is first
    validated as public and, failing that, as RFC1918/loopback — cloud-metadata names
    and link-local ranges stay refused in both modes because
    :func:`resolve_and_validate` never admits them.

    ``resolver`` mirrors ``resolve_and_validate(host, *, mode)`` and exists for
    hermetic tests; production resolves through the real SSRF guard.
    """

    def __init__(
        self,
        *,
        mode: Literal["public", "lan"] = "public",
        resolver: _Resolver | None = None,
        max_pins: int = DEFAULT_MAX_PINS,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if int(max_pins) <= 0:
            raise ValueError("max_pins must be positive")
        self.mode = mode
        self.max_pins = int(max_pins)
        self._resolver = resolver
        self._pins: dict[str, PinnedTarget] = {}

    @classmethod
    def from_env(cls, **kwargs) -> PinnedResolver:
        """Build the production resolver; private URLs are an explicit opt-in."""
        from agents.core.env_config import env_flag

        kwargs.setdefault(
            "mode", "lan" if env_flag("JARVIS_BROWSER_ALLOW_PRIVATE_URLS") else "public"
        )
        return cls(**kwargs)

    # -- resolution -----------------------------------------------------------

    def _resolve(self, host: str, mode: str) -> tuple[list[str], str | None]:
        if self._resolver is not None:
            return self._resolver(host, mode=mode)
        from agents.core.security.ssrf import resolve_and_validate

        return resolve_and_validate(host, mode=mode)

    def _validated_ip(self, host: str) -> str:
        ips, error = self._resolve(host, "public")
        if (error or not ips) and self.mode == "lan":
            ips, error = self._resolve(host, "lan")
        if error or not ips:
            raise BrowserTransportRefused("resolver_refused", error or "empty DNS answer")
        literal = str(ips[0]).split("%")[0]
        try:
            ipaddress.ip_address(literal)
        except ValueError:
            raise BrowserTransportRefused("resolver_refused", "resolver returned a non-IP") from None
        return literal

    def pin(self, url: str) -> PinnedTarget:
        """Validate ``url``'s host and remember the IP it must resolve to.

        A host already pinned keeps its first validated IP for the life of this
        resolver: the launch table is what the browser dialed, so a later, different
        answer must never silently replace it.
        """
        parsed = urlparse(str(url or ""))
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_SCHEMES:
            raise BrowserTransportRefused("unsupported_scheme", scheme or "none")
        try:
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError:
            raise BrowserTransportRefused("invalid_url", "unparseable netloc") from None
        if not host:
            raise BrowserTransportRefused("no_hostname")
        port = int(port or (443 if scheme == "https" else 80))
        if self.mode == "public" and is_private_host_literal(host):
            raise BrowserTransportRefused("private_address_denied", host)

        existing = self._pins.get(host)
        if existing is not None:
            return PinnedTarget(
                host=host, ip=existing.ip, scheme=scheme, port=port,
                logical_url=str(url), mode=self.mode,
            )
        if len(self._pins) >= self.max_pins:
            raise BrowserTransportRefused("pin_table_full", str(self.max_pins))
        ip = self._validated_ip(host)
        target = PinnedTarget(
            host=host, ip=ip, scheme=scheme, port=port, logical_url=str(url), mode=self.mode
        )
        self._pins[host] = target
        logger.info("browser transport pinned host=%s mode=%s", host, self.mode)
        return target

    async def pin_async(self, url: str) -> PinnedTarget:
        """:meth:`pin` off the event loop — the resolver blocks on ``getaddrinfo``."""
        return await asyncio.to_thread(self.pin, url)

    # -- inspection -----------------------------------------------------------

    def pinned_hosts(self) -> frozenset[str]:
        return frozenset(self._pins)

    def pinned_ip(self, host: str) -> str | None:
        target = self._pins.get((host or "").lower().rstrip("."))
        return target.ip if target else None

    def is_pinned(self, url: str) -> bool:
        try:
            host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        return bool(host) and host in self._pins

    def snapshot(self) -> dict:
        """Inspectable view of the pin table (no secrets: hosts and IPs only)."""
        return {
            "mode": self.mode,
            "pins": {host: target.ip for host, target in sorted(self._pins.items())},
            "max_pins": self.max_pins,
        }

    # -- launch ---------------------------------------------------------------

    def launch_args(self, browser: str = "chromium") -> list[str]:
        """Chromium argv that binds every pinned host to its validated IP.

        Every unpinned host maps to ``~NOTFOUND`` so a redirect or subresource to a
        host the guard never validated fails at name resolution. Rules are matched
        in order, so the explicit pins precede the catch-all.
        """
        if browser not in PINNED_BROWSERS:
            raise BrowserTransportRefused(PINNED_TRANSPORT_REQUIRES_CHROMIUM, str(browser))
        rules = [target.resolver_rule for _host, target in sorted(self._pins.items())]
        rules.append("MAP * ~NOTFOUND")
        return [f"--host-resolver-rules={', '.join(rules)}"]


def transport_from_env() -> PinnedResolver | None:
    """The production transport, or ``None`` when the owner never enabled the host.

    Kept next to :class:`PinnedResolver` so a caller can ask for "the configured
    transport" without importing the driver module.
    """
    from agents.core.env_config import env_flag

    if not env_flag("JARVIS_PLAYWRIGHT_HOST"):
        return None
    if os.getenv("JARVIS_PLAYWRIGHT_BROWSER", "chromium").strip() not in PINNED_BROWSERS:
        return None
    return PinnedResolver.from_env()


__all__ = [
    "ALLOWED_SCHEMES",
    "PINNED_BROWSERS",
    "PINNED_TRANSPORT_REQUIRES_CHROMIUM",
    "BrowserTransportRefused",
    "PinnedResolver",
    "PinnedTarget",
    "format_ip_for_rule",
    "is_private_host_literal",
    "transport_from_env",
]
