"""web_providers.py — the search backends behind ``web_search`` (H310 / H537 / H607).

One ABC (:class:`SearchProvider`), one registry, one resolution rule. The three
built-ins (Tavily, SearXNG, keyless DuckDuckGo) register through the same
:func:`register_search_provider` a first-party plugin uses to add a backend, so the
registry is the only path a search takes — there is no hard-coded branch beside it.

**Egress stays where it was.** A provider never builds an HTTP client: it is handed
the ``PluginHTTPClient`` of its declared ``plugin_id``. Registration is refused unless
that id has a ``plugin_gate`` manifest whose network access is ``RESTRICTED`` or
``LAN`` — so every backend's hosts are the manifest allowlist (plus hosts registered
through ``register_dynamic_domain``), every request crosses the SSRF pinning and the
kernel's ``plugin.egress`` hook, and no provider can become a second route around
them. A FULL-network identity (``webread``) is refused for search on purpose.
Third-party extensions cannot register: their sandbox has no network by design.

**Selection is read per call**, from the environment (``env_config``), never at boot:

* ``JARVIS_WEB_BACKEND`` — ``auto`` (default) or a registered provider name. ``auto``
  keeps the historical priority: owner-configured backends in registration order
  (Tavily, SearXNG, then plugin-registered ones), the keyless DuckDuckGo last. A named
  backend that is unknown, not configured or outside the tier pin answers *unavailable
  with its reason* — it never silently falls back.
* ``JARVIS_WEB_PROVIDER_TIER`` — ``any`` (default), ``free`` or ``paid``: pins which
  providers may answer at all.
* ``JARVIS_WEB_RESCUE`` — one-shot rescue. Unset: ``auto`` rescues, a named backend
  does not (naming a backend is a choice about who sees the query). ``0`` turns it
  off, ``1`` turns it on for a named backend too. The rescue stays inside the tier pin.
  **A keyless provider (DuckDuckGo) is never a rescue target** unless the owner set
  ``JARVIS_WEB_RESCUE=1`` *and* the caller is the interactive ``web_search`` tool
  (``allow_keyless_rescue=True``): unattended callers of ``search()`` — the research
  handler, the tech scout, the plugin gatherer — keep configured-only egress, so a
  failing configured backend never leaks their query to a third party the owner did
  not choose.
* ``JARVIS_WEB_BLOCKED_DOMAINS`` — operator-disallowed sites (comma list, subdomains
  included): ``web_extract`` refuses them on every redirect hop, ``web_search`` drops
  rows that point at them.

**Failure is classified** (:class:`ProviderFailure` vs :class:`PolicyBlock`). A
network error, an HTTP error status or an unreadable body may be rescued once by the
next eligible provider. A refusal by a gate — the manifest allowlist, the SSRF guard,
the kernel's e-stop — is a :class:`PolicyBlock` and is never retried anywhere:
retrying a deliberate refusal as if it were transient is how a boundary turns
advisory.

``python -m agents.core.plugins.web_providers [--json]`` is the offline verification
command: it prints what ``auto`` resolves to and why, per provider, without printing a
key.
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import logging
import re
import socket
import sys
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from ..env_config import env_str, truthy

logger = logging.getLogger("jarvis.plugins.web_providers")

BACKEND_ENV = "JARVIS_WEB_BACKEND"
TIER_ENV = "JARVIS_WEB_PROVIDER_TIER"
RESCUE_ENV = "JARVIS_WEB_RESCUE"
BLOCKED_DOMAINS_ENV = "JARVIS_WEB_BLOCKED_DOMAINS"

AUTO = "auto"
TIER_ANY = "any"
TIER_FREE = "free"
TIER_PAID = "paid"
TIERS = frozenset({TIER_ANY, TIER_FREE, TIER_PAID})
PROVIDER_TIERS = frozenset({TIER_FREE, TIER_PAID})

#: Why a selection has no provider; ``web_search`` reports it as ``detail``.
REASON_UNKNOWN = "unknown_backend"
REASON_NOT_CONFIGURED = "backend_not_configured"
REASON_TIER_PINNED = "tier_pinned"
REASON_INVALID_TIER = "invalid_tier"
REASON_PARSER_MISSING = "parser_missing"
REASON_NO_BACKEND = "no_backend"

_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
TAVILY_URL = "https://api.tavily.com/search"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"


class PolicyBlock(Exception):
    """A gate refused the request (manifest allowlist, SSRF guard, kernel). Never rescued."""

    kind = "policy"


class ProviderFailure(Exception):
    """The backend did not answer usefully (network, HTTP status, body). May be rescued."""

    kind = "failed"


_DNS_FAILURE_PREFIXES = ("egress blocked: DNS resolution failed", "egress blocked: empty DNS answer")


def is_dns_failure(exc: BaseException) -> bool:
    """True when an egress refusal is only "the name did not resolve".

    The egress client folds a resolver outage (a stopped container name, a flaky
    resolver) into the same ``PluginEgressError`` as a gate refusal. Nothing was
    forbidden by that, so callers treat it as a failure that may be retried or rescued;
    every other message (allowlist, SSRF, kernel) stays a refusal.
    """
    return str(exc).startswith(_DNS_FAILURE_PREFIXES)


async def classified(awaitable: Awaitable[Any]) -> Any:
    """Await one HTTP call and translate what went wrong into the two classes.

    ``PluginEgressError`` is the egress layer's refusal (allowlist, SSRF, kernel deny),
    so it becomes :class:`PolicyBlock` (except "the name did not resolve", which is a
    failure: see :func:`is_dns_failure`); anything else — a connect error, an open
    breaker, an HTTP error status — is a :class:`ProviderFailure`. The message carries
    the exception type only, never the URL or the query.
    """
    from ..http_client import PluginEgressError

    try:
        resp = await awaitable
    except PluginEgressError as exc:
        if is_dns_failure(exc):
            raise ProviderFailure("dns_failed") from None
        raise PolicyBlock("egress_blocked") from None
    except (PolicyBlock, ProviderFailure):
        raise
    except Exception as exc:
        raise ProviderFailure(type(exc).__name__) from None
    status = getattr(resp, "status_code", None)
    if isinstance(status, int):
        if status >= 400:
            raise ProviderFailure(f"http_{status}")
        return resp
    check = getattr(resp, "raise_for_status", None)
    if callable(check):
        try:
            check()
        except Exception as exc:
            raise ProviderFailure(type(exc).__name__) from None
    return resp


def _json_body(resp: Any) -> dict:
    try:
        data = resp.json()
    except Exception as exc:
        raise ProviderFailure(f"bad_body:{type(exc).__name__}") from None
    if not isinstance(data, dict):
        raise ProviderFailure("bad_body")
    return data


class SearchProvider(ABC):
    """One search backend. Subclasses set ``name``/``plugin_id``/``tier`` and implement
    :meth:`configured` and :meth:`search`; :meth:`search` raises :class:`PolicyBlock`
    or :class:`ProviderFailure` (wrap each call in :func:`classified`) and returns rows
    of ``title`` / ``url`` / ``snippet``. Taint is applied by the plugin, not here."""

    name: str = ""
    #: The egress identity whose ``PluginHTTPClient`` this provider is handed.
    plugin_id: str = "websearch"
    #: ``free`` or ``paid`` — what ``JARVIS_WEB_PROVIDER_TIER`` pins against.
    tier: str = TIER_FREE
    #: True when no owner setup is needed; such a backend is never "configured" for
    #: the HUD or unattended research, only usable by the interactive tool.
    keyless: bool = False
    #: ``(module, package)`` of an optional import the provider needs, or None.
    requires: tuple[str, str] | None = None

    def missing(self) -> str:
        """The package to install when the provider's optional import is absent."""
        if not self.requires:
            return ""
        module, package = self.requires
        try:
            found = importlib.util.find_spec(module) is not None
        except Exception:  # a broken import path reads as absent, never raises
            found = False
        return "" if found else package

    @abstractmethod
    def configured(self, plugin: Any) -> bool:
        """True when the owner supplied what this backend needs (read from *plugin*)."""

    @abstractmethod
    async def search(self, client: Any, plugin: Any, query: str, max_results: int) -> list[dict]:
        """Rows for *query*, dialled through *client* only."""


class TavilyProvider(SearchProvider):
    name = "tavily"
    tier = TIER_PAID

    def configured(self, plugin: Any) -> bool:
        return bool(str(getattr(plugin, "tavily_api_key", "") or "").strip())

    async def search(self, client, plugin, query, max_results):
        resp = await classified(client.post(
            TAVILY_URL,
            json={"api_key": plugin.tavily_api_key, "query": query, "max_results": max_results},
        ))
        data = _json_body(resp)
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", []) or [] if isinstance(r, dict)
        ]


class SearxngProvider(SearchProvider):
    name = "searxng"
    tier = TIER_FREE

    def configured(self, plugin: Any) -> bool:
        return bool(str(getattr(plugin, "searxng_url", "") or "").strip())

    async def search(self, client, plugin, query, max_results):
        resp = await classified(client.get(
            f"{plugin.searxng_url}/search",
            params={"q": query, "format": "json", "number_of_results": max_results},
        ))
        data = _json_body(resp)
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in (data.get("results", []) or [])[:max_results] if isinstance(r, dict)
        ]


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"
    tier = TIER_FREE
    keyless = True
    requires = ("bs4", "beautifulsoup4")

    def configured(self, plugin: Any) -> bool:
        return True

    async def search(self, client, plugin, query, max_results):
        resp = await classified(client.get(
            DUCKDUCKGO_URL, params={"q": query}, headers={"User-Agent": "Mozilla/5.0"},
        ))
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ProviderFailure("missing:beautifulsoup4") from None
        from .websearch import _unwrap_result_url

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = []
            for r in soup.select(".result")[:max_results]:
                title_el = r.select_one(".result__title a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    rows.append({
                        "title": title_el.get_text(strip=True),
                        "url": _unwrap_result_url(title_el.get("href", "")),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
        except Exception as exc:
            raise ProviderFailure(f"parse:{type(exc).__name__}") from None
        status = getattr(resp, "status_code", 200)
        if not rows and isinstance(status, int) and status != 200:
            # A 202 "anomaly" page parses to nothing: that is a failed answer, not "no hits".
            raise ProviderFailure(f"empty_http_{status}")
        return rows


# ── the registry ─────────────────────────────────────────────────────────────

_REGISTRY: dict[str, SearchProvider] = {}


#: The three first-party backends; they cannot be replaced or removed at runtime.
BUILTIN_NAMES = frozenset({"tavily", "searxng", "duckduckgo"})


def register_search_provider(provider: SearchProvider, *, replace: bool = False) -> None:
    """Add a backend ``JARVIS_WEB_BACKEND`` can select. Refused (``ValueError``) for a bad
    name or tier, an egress identity with no manifest, a manifest that may reach the
    whole web (or nothing), a built-in name, and a name already taken unless ``replace``.

    Registration is a *trusted in-process act*: the provider sees every query routed to
    it and the configured keys it is handed, so only first-party code may call this."""
    if not isinstance(provider, SearchProvider):
        raise TypeError("a search provider must subclass SearchProvider")
    name = str(getattr(provider, "name", "") or "")
    if not _NAME.fullmatch(name) or name == AUTO:
        raise ValueError("provider name must be 2-32 chars of a-z, 0-9, '-' or '_'")
    if getattr(provider, "tier", None) not in PROVIDER_TIERS:
        raise ValueError("provider tier must be 'free' or 'paid'")
    from ..plugin_gate import BUILTIN_PLUGINS, NetworkAccess

    plugin_id = str(getattr(provider, "plugin_id", "") or "")
    manifest = BUILTIN_PLUGINS.get(plugin_id)
    if manifest is None:
        raise ValueError(f"egress identity {plugin_id!r} has no plugin manifest")
    if manifest.network_access not in (NetworkAccess.RESTRICTED, NetworkAccess.LAN):
        raise ValueError(
            f"egress identity {plugin_id!r} declares network access "
            f"{manifest.network_access.value!r}; a search backend needs RESTRICTED or LAN"
        )
    if name in _REGISTRY and (not replace or name in _builtin_names()):
        raise ValueError(f"search provider {name!r} is already registered")
    _REGISTRY[name] = provider


def unregister_search_provider(name: str) -> bool:
    """Remove a registered backend (a plugin unloading). True when one was removed;
    the built-ins stay."""
    if str(name or "") in _builtin_names():
        return False
    return _REGISTRY.pop(str(name or ""), None) is not None


def search_providers() -> tuple[str, ...]:
    """Registered backend names, in registration order (the ``auto`` order)."""
    return tuple(_REGISTRY)


def get_search_provider(name: str) -> SearchProvider | None:
    return _REGISTRY.get(str(name or ""))


_BUILTINS_LOCKED = False


def _builtin_names() -> frozenset[str]:
    return BUILTIN_NAMES if _BUILTINS_LOCKED else frozenset()


for _builtin in (TavilyProvider(), SearxngProvider(), DuckDuckGoProvider()):
    register_search_provider(_builtin)
del _builtin
_BUILTINS_LOCKED = True


# ── configuration, read per call ─────────────────────────────────────────────

def configured_backend(explicit: str | None = None) -> str:
    raw = explicit if explicit is not None else env_str(BACKEND_ENV, "")
    return str(raw or "").strip().lower() or AUTO


def configured_tier(explicit: str | None = None) -> str:
    raw = explicit if explicit is not None else env_str(TIER_ENV, "")
    return str(raw or "").strip().lower() or TIER_ANY


def rescue_setting(explicit: bool | None = None) -> bool | None:
    """True/False when set (explicitly or in the env), None for "the default"."""
    if explicit is not None:
        return bool(explicit)
    raw = env_str(RESCUE_ENV, "").strip()
    if not raw:
        return None
    return truthy(raw, False)


_DOT_VARIANTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
_HOST_OK = re.compile(r"^[a-z0-9._\-\[\]:]+$")
_BRACKET_HOST = re.compile(r"\[([0-9a-f:.]+)\](?::\d{1,5})?")


def _normalize_host(text: str) -> str:
    """A hostname in one comparable shape: lower-case, ASCII dots, punycode, no port.

    ``http://Evil.COM:8080/x``, ``evil.com.``, ``bad\u3002org`` (an ideographic dot the
    resolver treats as ``.``) and ``m\u00fcnchen.de`` / ``xn--mnchen-3ya.de`` each reduce to
    one form, so the operator's list and a URL's host compare equal whichever way
    either was written. ``""`` when the text is not a usable host.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        if "://" in raw:
            raw = urlsplit(raw).hostname or ""
        elif "/" in raw or "?" in raw or "#" in raw or "@" in raw:
            raw = urlsplit("//" + raw).hostname or ""
        elif raw.count(":") == 1:  # host:port
            raw = raw.split(":", 1)[0]
    except ValueError:
        return ""
    raw = unicodedata.normalize("NFKC", raw).translate(_DOT_VARIANTS).lower().strip(".")
    bracketed = _BRACKET_HOST.fullmatch(raw)
    if bracketed:  # "[::1]:8080" -> "::1": an IPv6 literal with its port
        raw = bracketed.group(1)
    if not raw:
        return ""
    try:
        ascii_host = raw.encode("idna").decode("ascii")
    except UnicodeError:
        ascii_host = raw
    ascii_host = ascii_host.lower().strip(".")
    if not _HOST_OK.fullmatch(ascii_host):
        return ""
    canonical = _canonical_ip(ascii_host)
    if canonical:
        return canonical
    # A colon or a bracket belongs to an IP literal only; anything else is a typo that
    # would match nothing and fail open silently.
    if ":" in ascii_host or "[" in ascii_host or "]" in ascii_host:
        return ""
    return ascii_host


_NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+)){0,3}")


def _canonical_ip(host: str) -> str:
    """The one dotted/colon form of an IP literal, or ``""`` for a name.

    A browser or resolver reads ``167838211``, ``0xa010203``, ``012.1.2.3`` and
    ``::ffff:10.1.2.3`` as 10.1.2.3, so a block-list entry written one way must still
    match a URL written another.
    """
    bare = host.strip("[]")
    try:
        addr = ipaddress.ip_address(bare)
    except ValueError:
        addr = None
    if addr is None and _NUMERIC_HOST.fullmatch(host):
        try:
            addr = ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))
        except (OSError, ValueError):
            return ""
    if addr is None:
        return ""
    mapped = getattr(addr, "ipv4_mapped", None)
    return str(mapped or addr)


def _blocked_entries() -> tuple[list[str], list[str]]:
    """``(hosts, unusable)`` from ``JARVIS_WEB_BLOCKED_DOMAINS`` (comma list)."""
    hosts: list[str] = []
    bad: list[str] = []
    for part in env_str(BLOCKED_DOMAINS_ENV, "").split(","):
        entry = part.strip()
        if not entry:
            continue
        host = _normalize_host(entry.lstrip("*").lstrip("."))
        if host:
            hosts.append(host)
        else:
            bad.append(entry[:64])
    if bad:
        key = tuple(bad)
        if key not in _WARNED_UNUSABLE:
            _WARNED_UNUSABLE.add(key)
            logger.warning(
                "%s has %d entr%s that name no host and block nothing: %s",
                BLOCKED_DOMAINS_ENV, len(bad), "y" if len(bad) == 1 else "ies",
                ", ".join(bad)[:200],
            )
    return list(dict.fromkeys(hosts)), bad


#: unusable block-list entries already logged (so a hot path warns once per distinct list)
_WARNED_UNUSABLE: set[tuple[str, ...]] = set()


def blocked_domains() -> tuple[str, ...]:
    return tuple(_blocked_entries()[0])


def unusable_blocked_entries() -> tuple[str, ...]:
    """Entries of the block list that name no host (a typo would otherwise fail open)."""
    return tuple(_blocked_entries()[1])


def blocked_host(url_or_host: object) -> bool:
    """True when *url_or_host* is an operator-disallowed site or a subdomain of one."""
    domains = blocked_domains()
    if not domains:
        return False
    host = _normalize_host(str(url_or_host or ""))
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


@dataclass(frozen=True)
class Selection:
    """Who answers a search now, who may rescue it, and why nobody can."""

    backend: str
    tier: str
    primary: SearchProvider | None
    rescue: tuple[SearchProvider, ...] = ()
    reason: str = ""
    missing: str = ""

    @property
    def key(self) -> str:
        """The cache-key part that changes when the answering backend changes."""
        return f"{self.backend}|{self.tier}|{self.primary.name if self.primary else ''}"


def _configured(provider: SearchProvider, plugin: Any) -> bool:
    try:
        return bool(provider.configured(plugin))
    except Exception as exc:
        logger.warning("search provider configured() failed (type=%s)", type(exc).__name__)
        return False


def _tier_ok(provider: SearchProvider, tier: str) -> bool:
    return tier == TIER_ANY or provider.tier == tier


def auto_order() -> list[SearchProvider]:
    """Owner-configured backends in registration order, keyless ones last."""
    providers = list(_REGISTRY.values())
    return [p for p in providers if not p.keyless] + [p for p in providers if p.keyless]


def _rescuers(candidates: list[SearchProvider], exclude: SearchProvider, *,
              rescue_on: bool | None, allow_keyless: bool) -> tuple[SearchProvider, ...]:
    """The one provider that may take over from *exclude*, or ``()``.

    A keyless provider qualifies only when the owner switched rescue on *explicitly*
    and the caller is the interactive tool; see the module docstring.
    """
    keyless_ok = allow_keyless and rescue_on is True
    for p in candidates:
        if p is exclude:
            continue
        if p.keyless and not keyless_ok:
            continue
        return (p,)
    return ()


def resolve(plugin: Any, *, backend: str | None = None, tier: str | None = None,
            rescue: bool | None = None, allow_keyless_rescue: bool = False) -> Selection:
    """The selection for one call. Pure: reads the registry and the environment only."""
    backend = configured_backend(backend)
    tier = configured_tier(tier)
    if tier not in TIERS:
        return Selection(backend, tier, None, reason=REASON_INVALID_TIER)
    ordered = auto_order()
    candidates = [p for p in ordered
                  if _tier_ok(p, tier) and _configured(p, plugin) and not p.missing()]
    rescue_on = rescue_setting(rescue)
    if backend == AUTO:
        if not candidates:
            missing = next((p.missing() for p in ordered
                            if _tier_ok(p, tier) and _configured(p, plugin) and p.missing()), "")
            return Selection(backend, tier, None, reason=REASON_NO_BACKEND, missing=missing)
        allow = True if rescue_on is None else rescue_on
        primary = candidates[0]
        rescuers = (_rescuers(candidates, primary, rescue_on=rescue_on,
                              allow_keyless=allow_keyless_rescue) if allow else ())
        return Selection(backend, tier, primary, rescuers)
    provider = _REGISTRY.get(backend)
    if provider is None:
        return Selection(backend, tier, None, reason=REASON_UNKNOWN)
    if not _tier_ok(provider, tier):
        return Selection(backend, tier, None, reason=REASON_TIER_PINNED)
    if not _configured(provider, plugin):
        return Selection(backend, tier, None, reason=REASON_NOT_CONFIGURED)
    missing = provider.missing()
    if missing:
        return Selection(backend, tier, None, reason=REASON_PARSER_MISSING, missing=missing)
    rescuers = (_rescuers(candidates, provider, rescue_on=rescue_on,
                          allow_keyless=allow_keyless_rescue) if rescue_on is True else ())
    return Selection(backend, tier, provider, rescuers)


# ── the verification command (H607) ──────────────────────────────────────────

def _parser_present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def describe(plugin: Any = None) -> dict:
    """What a search would use right now, and why — never a key value."""
    if plugin is None:
        # The same two env reads plugin_manager makes; no client is built.
        plugin = SimpleNamespace(tavily_api_key=env_str("TAVILY_API_KEY"),
                                 searxng_url=env_str("SEARXNG_URL"),
                                 backend=None, provider_tier=None, rescue=None)
    args = {"backend": getattr(plugin, "backend", None),
            "tier": getattr(plugin, "provider_tier", None),
            "rescue": getattr(plugin, "rescue", None)}
    selection = resolve(plugin, **args)
    interactive = resolve(plugin, allow_keyless_rescue=True, **args)
    rescue = rescue_setting(getattr(plugin, "rescue", None))
    providers = []
    for p in auto_order():
        providers.append({
            "name": p.name, "plugin_id": p.plugin_id, "tier": p.tier, "keyless": p.keyless,
            "configured": _configured(p, plugin), "eligible": _tier_ok(p, selection.tier),
            "missing": p.missing(),
        })
    return {
        "backend": selection.backend,
        "tier": selection.tier,
        "rescue": ("default (auto only)" if rescue is None else ("on" if rescue else "off")),
        "primary": selection.primary.name if selection.primary else None,
        "rescue_to": [p.name for p in selection.rescue],
        "rescue_to_interactive": [p.name for p in interactive.rescue],
        "reason": selection.reason,
        "missing": selection.missing,
        "providers": providers,
        "parsers": {"beautifulsoup4": _parser_present("bs4"), "pypdf": _parser_present("pypdf")},
        "blocked_domains": list(blocked_domains()),
        "blocked_domains_unusable": list(unusable_blocked_entries()),
    }


def _text_report(report: dict) -> str:
    lines = [
        f"backend   {report['backend']}  ({BACKEND_ENV})",
        f"tier      {report['tier']}  ({TIER_ENV})",
        f"rescue    {report['rescue']}  ({RESCUE_ENV})",
    ]
    if report["primary"]:
        rescue_to = ", ".join(report["rescue_to"]) or "none"
        lines.append(f"answers   {report['primary']}  (rescue: {rescue_to})")
        if report["rescue_to_interactive"] != report["rescue_to"]:
            lines.append("          interactive web_search tool only, rescue: "
                         + ", ".join(report["rescue_to_interactive"]))
    else:
        missing = f", install {report['missing']}" if report["missing"] else ""
        lines.append(f"answers   nobody — {report['reason']}{missing}")
    lines.append("providers (auto order):")
    for p in report["providers"]:
        state = "configured" if p["configured"] else "not configured"
        if p["keyless"]:
            state = "keyless"
        flags = [state, p["tier"], f"egress={p['plugin_id']}"]
        if not p["eligible"]:
            flags.append("outside tier pin")
        if p["missing"]:
            flags.append(f"missing {p['missing']}")
        lines.append(f"  {p['name']:<12} " + ", ".join(flags))
    parsers = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in report["parsers"].items())
    lines.append(f"parsers   {parsers}")
    if report["blocked_domains"]:
        lines.append(f"blocked   {', '.join(report['blocked_domains'])}")
    if report["blocked_domains_unusable"]:
        lines.append("WARNING   unusable entries in " + BLOCKED_DOMAINS_ENV + " (ignored): "
                     + ", ".join(report["blocked_domains_unusable"]))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agents.core.plugins.web_providers",
        description="Offline check of which web search backend would answer, and why.",
    )
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    report = describe()
    if ns.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_text_report(report))
    return 0 if report["primary"] else 1


__all__ = [
    "AUTO", "BACKEND_ENV", "BLOCKED_DOMAINS_ENV", "DuckDuckGoProvider", "PolicyBlock",
    "ProviderFailure", "RESCUE_ENV", "SearchProvider", "SearxngProvider", "Selection",
    "TIER_ENV", "TavilyProvider", "auto_order", "blocked_host", "classified", "describe",
    "get_search_provider", "main", "register_search_provider", "resolve",
    "search_providers", "unregister_search_provider", "unusable_blocked_entries",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
