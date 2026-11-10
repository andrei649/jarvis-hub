"""The plugin ``ctx`` vendored Hermes plugins register through, and the search adapter.

A vendored plugin's ``register(ctx)`` calls ``ctx.register_web_search_provider(provider)``.
Here that wraps the Hermes provider in :class:`HermesSearchProvider` — a Nerva
``SearchProvider`` — and hands it to ``web_providers.register_search_provider``, so the
registry's own checks (name, tier, a manifested RESTRICTED egress identity) apply and the
provider is selected by the same ``JARVIS_WEB_BACKEND`` / tier / rescue rules as a native one.

What the adapter decides, not the vendored code:

* **Egress identity**: ``websearch``, the manifest the native backends dial under; the
  adopted hosts are on its allowlist.
* **Tier**: from :data:`PROVIDER_TIERS`, a server-owned table. A provider whose name is not
  in it is refused, so a vendored file cannot add a backend nobody reviewed.
* **Keyless**: never. A provider is configured only when its key is set (off by default).
* **Classification**: a refusal recorded by the compat ``httpx`` raises ``PolicyBlock``
  (never rescued) whatever the vendored code returned; any other failure raises
  ``ProviderFailure`` with a reason code only.

The vendored search is synchronous: it runs in a worker thread with the egress client
bound in its context, and each request is scheduled back onto the event loop that owns
the client.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from types import ModuleType
from typing import Any

from agents.vendor.hermes_compat import httpx
from agents.vendor.hermes_compat.web_search_provider import WebSearchProvider

logger = logging.getLogger("jarvis.vendor.hermes")

#: Vendored plugin packages under ``agents.vendor.hermes.plugins.web`` that are loaded.
ADOPTED_WEB_PLUGINS = ("exa", "brave_free", "parallel")

#: Server-owned: the Nerva tier of each adopted provider, by its upstream name.
PROVIDER_TIERS = {"exa": "paid", "brave-free": "free", "parallel": "paid"}

#: The egress identity every adopted search dials under (its manifest lists their hosts).
EGRESS_IDENTITY = "websearch"

_ADAPTERS: dict[int, type] = {}


def _rows(result: Any, max_results: int, call: httpx.EgressCall, registry: ModuleType) -> list[dict]:
    """Hermes ``{"success", "data": {"web": [...]}}`` to Nerva ``title``/``url``/``snippet`` rows."""
    if not isinstance(result, dict) or result.get("success") is not True:
        raise registry.ProviderFailure(call.failure or "hermes_error")
    data = result.get("data")
    web = data.get("web") if isinstance(data, dict) else None
    if not isinstance(web, list):
        raise registry.ProviderFailure("bad_rows")
    rows = []
    for hit in web:
        if not isinstance(hit, dict):
            continue
        rows.append({"title": str(hit.get("title") or ""), "url": str(hit.get("url") or ""),
                     "snippet": str(hit.get("description") or "")})
    return rows[:max(0, int(max_results))]


def adapter_class(registry: ModuleType) -> type:
    """The adapter class for one ``web_providers`` module object.

    Built per module object because the repo can import ``web_providers`` under two names
    (``agents.core...`` and ``core...``), each with its own registry and ``SearchProvider``.
    """
    cached = _ADAPTERS.get(id(registry))
    if cached is not None and issubclass(cached, registry.SearchProvider):
        return cached

    class HermesSearchProvider(registry.SearchProvider):
        """A vendored Hermes ``WebSearchProvider`` seen as a Nerva ``SearchProvider``."""

        plugin_id = EGRESS_IDENTITY
        keyless = False
        requires = None

        def __init__(self, hermes: WebSearchProvider) -> None:
            if not isinstance(hermes, WebSearchProvider):
                raise TypeError("an adopted provider must subclass the compat WebSearchProvider")
            name = str(hermes.name or "")
            tier = PROVIDER_TIERS.get(name)
            if tier is None:
                raise ValueError(f"adopted provider {name!r} has no reviewed tier")
            self.name = name
            self.tier = tier
            self.hermes = hermes

        def __repr__(self) -> str:
            return f"<HermesSearchProvider {self.name}>"

        def configured(self, plugin: Any) -> bool:
            return bool(self.hermes.supports_search() and self.hermes.is_available())

        async def search(self, client: Any, plugin: Any, query: str, max_results: int) -> list[dict]:
            loop = asyncio.get_running_loop()
            with httpx.bound_egress(client, loop) as call:
                try:
                    result = await asyncio.to_thread(self.hermes.search, str(query), int(max_results))
                except Exception as exc:
                    if call.policy_block:
                        raise registry.PolicyBlock(call.policy_block) from None
                    raise registry.ProviderFailure(call.failure or type(exc).__name__) from None
            if call.policy_block:
                raise registry.PolicyBlock(call.policy_block)
            return _rows(result, max_results, call, registry)

    _ADAPTERS[id(registry)] = HermesSearchProvider
    return HermesSearchProvider


class PluginContext:
    """The ``ctx`` a vendored plugin's ``register(ctx)`` receives.

    Only ``register_web_search_provider`` is offered: it is the one registration the
    adopted plugins make. Any other ``ctx.register_*`` is absent, so a plugin needing one
    fails to load (loudly) instead of registering something unreviewed.
    """

    def __init__(self, registry: ModuleType, plugin: str) -> None:
        self._registry = registry
        self.plugin = plugin
        self.registered: list[str] = []

    def register_web_search_provider(self, provider: WebSearchProvider) -> None:
        adapter = adapter_class(self._registry)(provider)
        self._registry.register_search_provider(adapter, replace=True)
        self.registered.append(adapter.name)


def load_web_providers(registry: ModuleType) -> tuple[str, ...]:
    """Import the adopted plugins and register their providers into *registry*.

    A plugin that fails to import or register is skipped with a warning (type only); it
    never breaks the native backends. Upstream logs each query at INFO; the vendored
    loggers are held at WARNING so a query never reaches the log.
    """
    logging.getLogger("agents.vendor.hermes").setLevel(logging.WARNING)
    names: list[str] = []
    for package in ADOPTED_WEB_PLUGINS:
        try:
            module = importlib.import_module(f"agents.vendor.hermes.plugins.web.{package}")
            ctx = PluginContext(registry, package)
            module.register(ctx)
            names.extend(ctx.registered)
        except Exception as exc:
            logger.warning("adopted Hermes web provider %s not loaded (type=%s)",
                           package, type(exc).__name__)
    return tuple(names)


__all__ = ["ADOPTED_WEB_PLUGINS", "EGRESS_IDENTITY", "PROVIDER_TIERS", "PluginContext",
           "adapter_class", "load_web_providers"]
