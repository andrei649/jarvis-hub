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
import json
import logging
import re
import sys
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


async def classified(awaitable: Awaitable[Any]) -> Any:
    """Await one HTTP call and translate what went wrong into the two classes.

    ``PluginEgressError`` is the egress layer's refusal (allowlist, SSRF, kernel deny),
    so it becomes :class:`PolicyBlock`; anything else — a connect error, an open
    breaker, an HTTP error status — is a :class:`ProviderFailure`. The message carries
    the exception type only, never the URL or the query.
    """
    from ..http_client import PluginEgressError

    try:
        resp = await awaitable
    except PluginEgressError:
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
            return rows
        except Exception as exc:
            raise ProviderFailure(f"parse:{type(exc).__name__}") from None


# ── the registry ─────────────────────────────────────────────────────────────

_REGISTRY: dict[str, SearchProvider] = {}


def register_search_provider(provider: SearchProvider, *, replace: bool = False) -> None:
    """Add a backend ``JARVIS_WEB_BACKEND`` can select. Refused (``ValueError``) for a bad
    name or tier, an egress identity with no manifest, a manifest that may reach the
    whole web (or nothing), and a name already taken unless ``replace``."""
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
    if name in _REGISTRY and not replace:
        raise ValueError(f"search provider {name!r} is already registered")
    _REGISTRY[name] = provider


def unregister_search_provider(name: str) -> bool:
    """Remove a registered backend (a plugin unloading). True when one was removed."""
    return _REGISTRY.pop(str(name or ""), None) is not None


def search_providers() -> tuple[str, ...]:
    """Registered backend names, in registration order (the ``auto`` order)."""
    return tuple(_REGISTRY)


def get_search_provider(name: str) -> SearchProvider | None:
    return _REGISTRY.get(str(name or ""))


for _builtin in (TavilyProvider(), SearxngProvider(), DuckDuckGoProvider()):
    register_search_provider(_builtin)
del _builtin


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


def blocked_domains() -> tuple[str, ...]:
    raw = env_str(BLOCKED_DOMAINS_ENV, "")
    out = []
    for part in raw.split(","):
        domain = part.strip().lower().lstrip("*").strip(".")
        if domain:
            out.append(domain)
    return tuple(dict.fromkeys(out))


def blocked_host(url_or_host: object) -> bool:
    """True when *url_or_host* is an operator-disallowed site or a subdomain of one."""
    domains = blocked_domains()
    if not domains:
        return False
    text = str(url_or_host or "").strip()
    host = ""
    if "://" in text:
        try:
            host = urlsplit(text).hostname or ""
        except ValueError:
            return False
    else:
        host = text
    host = host.lower().rstrip(".")
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


def resolve(plugin: Any, *, backend: str | None = None, tier: str | None = None,
            rescue: bool | None = None) -> Selection:
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
        return Selection(backend, tier, candidates[0], tuple(candidates[1:2]) if allow else ())
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
    rescuers = tuple(p for p in candidates if p is not provider)[:1] if rescue_on is True else ()
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
    selection = resolve(plugin, backend=getattr(plugin, "backend", None),
                        tier=getattr(plugin, "provider_tier", None),
                        rescue=getattr(plugin, "rescue", None))
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
        "reason": selection.reason,
        "missing": selection.missing,
        "providers": providers,
        "parsers": {"beautifulsoup4": _parser_present("bs4"), "pypdf": _parser_present("pypdf")},
        "blocked_domains": list(blocked_domains()),
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
    "search_providers", "unregister_search_provider",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
