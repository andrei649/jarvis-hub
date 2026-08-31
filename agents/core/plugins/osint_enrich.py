"""osint_enrich.py — the one live OSINT pivot-lookup client (DRA-05/DRA-10).

Implements the :class:`agents.core.osint.enrich.PivotLookupClient` seam with *keyless*
resolvers only, and is **off unless the owner turns egress on** (``JARVIS_OSINT_ENRICH``).
With the flag unset ``supports()`` is False and ``lookup()`` returns ``[]`` after zero HTTP
calls, so nothing about installing this plugin puts an indicator on the wire.

Two rules shape the resolver table:

* **The indicator is never the host.** Every request goes to a *fixed* host named in the
  manifest (``dns.google`` / ``rdap.org``) with the indicator carried as a query parameter
  or as an already-parsed IP in the path. An indicator is attacker-influenceable data; if
  it could become the request host, this plugin would be an SSRF pivot with a manifest
  stamped on it. (``PluginHTTPClient`` also pins DNS and validates every hop — this rule is
  the layer above that, not a substitute for it.)
* **No key, no claim.** Only ``domain→ip``, ``ip→domain`` and ``ip→asn`` have a keyless
  resolver. Every other pair reports ``supports() is False``, which the scaffold records as
  ``provider_not_configured`` — the honest boundary where the owner's paid providers
  (Shodan, HIBP, SpiderFoot modules, the WorldView REST) would later plug in as extra
  branches rather than a redesign.
"""

from __future__ import annotations

import ipaddress
import logging
import re

from ..env_config import env_flag
from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.osint_enrich")

#: Owner-flipped egress flag. Default-off, exactly like ``JARVIS_TERMINAL_TARGETS``.
ENABLE_FLAG = "JARVIS_OSINT_ENRICH"

DNS_RESOLVE_URL = "https://dns.google/resolve"
RDAP_IP_URL = "https://rdap.org/ip/"

#: Pivot pairs a keyless resolver can actually answer.
RESOLVERS = frozenset({("domain", "ip"), ("ip", "domain"), ("ip", "asn")})

_DNS_TYPE_A = 1
_DNS_TYPE_PTR = 12

# A conservative hostname shape. Anything else never reaches the wire, so a hostile
# "indicator" cannot smuggle a path, a query, or a second host into the request.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _clean_hostname(value: str) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    return host if _HOSTNAME_RE.match(host) else ""


def _clean_ip(value: str):
    try:
        return ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None


class OsintEnrichPlugin:
    """Keyless OSINT pivot resolver, default-off behind ``JARVIS_OSINT_ENRICH``."""

    def __init__(self, http_client=None):
        # The injected client is a test seam; production always gets the manifest-gated,
        # DNS-pinned PluginHTTPClient under the ``osint_enrich`` manifest id.
        self.client = http_client if http_client is not None else PluginHTTPClient.for_plugin(
            "osint_enrich"
        )

    # ── contract ────────────────────────────────────────────────────────────
    def enabled(self) -> bool:
        """True only when the owner has explicitly permitted enrichment egress."""
        return env_flag(ENABLE_FLAG)

    def available(self) -> bool:
        """Runtime honesty signal: this plugin is dark until its egress flag is on."""
        return self.enabled()

    def supports(self, from_kind: str, to_kind: str) -> bool:
        if not self.enabled():
            return False
        pair = (str(from_kind or "").strip().lower(), str(to_kind or "").strip().lower())
        return pair in RESOLVERS

    async def lookup(self, *, from_kind: str, from_value: str, to_kind: str) -> list[dict]:
        """Resolve one pivot. Returns ``[]`` when disabled, unsupported, or simply unknown."""
        if not self.supports(from_kind, to_kind):
            return []
        pair = (from_kind.strip().lower(), to_kind.strip().lower())
        if pair == ("domain", "ip"):
            return await self._resolve_a(from_value)
        if pair == ("ip", "domain"):
            return await self._resolve_ptr(from_value)
        if pair == ("ip", "asn"):
            return await self._resolve_origin_asn(from_value)
        return []

    # ── resolvers ───────────────────────────────────────────────────────────
    async def _resolve_a(self, value: str) -> list[dict]:
        host = _clean_hostname(value)
        if not host:
            return []
        data = await self._get_json(DNS_RESOLVE_URL, {"name": host, "type": "A"})
        out = []
        for answer in (data or {}).get("Answer") or []:
            if not isinstance(answer, dict) or answer.get("type") != _DNS_TYPE_A:
                continue
            address = _clean_ip(answer.get("data"))
            if address is None:
                continue
            out.append({"kind": "ip", "value": str(address),
                        "detail": f"DNS A record for {host}", "url": ""})
        return out

    async def _resolve_ptr(self, value: str) -> list[dict]:
        address = _clean_ip(value)
        if address is None:
            return []
        data = await self._get_json(DNS_RESOLVE_URL,
                                    {"name": address.reverse_pointer, "type": "PTR"})
        out = []
        for answer in (data or {}).get("Answer") or []:
            if not isinstance(answer, dict) or answer.get("type") != _DNS_TYPE_PTR:
                continue
            host = _clean_hostname(str(answer.get("data") or ""))
            if not host:
                continue
            out.append({"kind": "domain", "value": host,
                        "detail": f"reverse DNS for {address}", "url": ""})
        return out

    async def _resolve_origin_asn(self, value: str) -> list[dict]:
        """Origin AS numbers RDAP actually publishes for this address — never a guess.

        Only some registries populate the origin-AS extension; when it is absent we return
        nothing rather than inferring an ASN from the network handle, which is a different
        fact wearing the same shape.
        """
        address = _clean_ip(value)
        if address is None:
            return []
        # ``address`` is a parsed IP re-stringified, so nothing from the indicator can
        # escape into the URL path.
        url = f"{RDAP_IP_URL}{address}"
        data = await self._get_json(url, None)
        out = []
        for number in (data or {}).get("arin_originas0_originautnums") or []:
            text = str(number).strip()
            if not text.isdigit():
                continue
            out.append({"kind": "asn", "value": f"AS{int(text)}",
                        "detail": f"RDAP origin AS for {address}", "url": url})
        return out

    # ── transport ───────────────────────────────────────────────────────────
    @resilient_call(
        max_retries=2,
        timeout=10.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:osint_enrich",
        circuit_breaker_threshold=3,
        metrics_agent_id="osint_enrich",
        metrics_backend="osint-keyless-resolvers",
    )
    async def _get_json(self, url: str, params: dict | None) -> dict:
        kwargs = {"params": params} if params else {}
        resp = await self.client.get(url, **kwargs)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception:
            logger.warning("osint_enrich: non-JSON response from %s", url)
            return {}
        return payload if isinstance(payload, dict) else {}

    async def close(self):
        close = getattr(self.client, "close", None)
        if callable(close):
            await close()
