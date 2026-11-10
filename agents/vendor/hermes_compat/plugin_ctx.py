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

The vendored search is synchronous. It runs on a small executor of its own, never the
loop's default executor: the egress client resolves DNS there, so a search waiting on a
resolver queued behind it would starve both. The egress client and the provider scope are
bound in its context, and each request is scheduled back onto the event loop that owns the
client. At most :data:`MAX_CONCURRENT` searches hold a worker; the rest wait on the loop. A
call has :data:`SEARCH_DEADLINE_SECONDS`, under the tool loop's own 30 s cut, and when its
caller leaves (cancelled or timed out) the worker gives up at its next poll, so no thread
keeps waiting for a caller that is gone.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import logging
import sys
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any

from agents.vendor.hermes_compat import httpx
from agents.vendor.hermes_compat.web_search_provider import WebSearchProvider, provider_scope

logger = logging.getLogger("jarvis.vendor.hermes")

#: Vendored plugin packages under ``agents.vendor.hermes.plugins.web`` that are loaded.
ADOPTED_WEB_PLUGINS = ("exa", "brave_free", "parallel")

#: Server-owned: the Nerva tier of each adopted provider, by its upstream name. Brave counts
#: as paid: a BRAVE_SEARCH_API_KEY may be a paid-plan key and Nerva cannot tell which, so a
#: ``JARVIS_WEB_PROVIDER_TIER=free`` pin keeps it out rather than spend on the owner's plan.
PROVIDER_TIERS = {"exa": "paid", "brave-free": "paid", "parallel": "paid"}

#: Worker threads for vendored code, and how many searches may hold one at a time.
EXECUTOR_WORKERS = 4
MAX_CONCURRENT = 3
#: A search's whole budget (the tool loop cuts a tool at 30 s).
SEARCH_DEADLINE_SECONDS = 25.0
#: How long a search may wait for a free worker before it fails as busy.
QUEUE_WAIT_SECONDS = 10.0

_EXECUTOR = ThreadPoolExecutor(max_workers=EXECUTOR_WORKERS, thread_name_prefix="hermes-vendor")
_SLOTS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _slots(loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
    sem = _SLOTS.get(loop)
    if sem is None:
        sem = _SLOTS[loop] = asyncio.Semaphore(MAX_CONCURRENT)
    return sem


class _QuietVendorLogs(logging.Filter):
    """Drop vendored records below WARNING (upstream logs every query at INFO).

    A filter on each vendored logger, not a level: ``logging.config.dictConfig`` resets the
    level, handlers and propagation of existing child loggers but leaves their filters alone.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


_QUIET = _QuietVendorLogs()


def _quiet_vendor_loggers() -> None:
    for name, module in list(sys.modules.items()):
        if not name.startswith("agents.vendor.hermes.") or module is None:
            continue
        loggers = {logging.getLogger(name)}
        own = getattr(module, "logger", None)
        if isinstance(own, logging.Logger):
            loggers.add(own)
        for log in loggers:
            if _QUIET not in log.filters:
                log.addFilter(_QUIET)

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
            with provider_scope(self.name):
                return bool(self.hermes.supports_search() and self.hermes.is_available())

        async def search(self, client: Any, plugin: Any, query: str, max_results: int) -> list[dict]:
            loop = asyncio.get_running_loop()
            deadline = time.monotonic() + SEARCH_DEADLINE_SECONDS
            sem = _slots(loop)
            try:
                await asyncio.wait_for(sem.acquire(), timeout=QUEUE_WAIT_SECONDS)
            except TimeoutError:
                raise registry.ProviderFailure("busy") from None
            try:
                with httpx.bound_egress(client, loop, deadline=deadline) as call, \
                        provider_scope(self.name):
                    ctx = contextvars.copy_context()
                    work = loop.run_in_executor(_EXECUTOR, ctx.run, self.hermes.search,
                                                str(query), int(max_results))
                    try:
                        result = await asyncio.wait_for(
                            work, timeout=max(0.0, deadline - time.monotonic()))
                    except TimeoutError:
                        call.abandon()
                        raise registry.ProviderFailure("timeout") from None
                    except asyncio.CancelledError:
                        call.abandon()
                        raise
                    except Exception as exc:
                        if call.policy_block:
                            raise registry.PolicyBlock(call.policy_block) from None
                        raise registry.ProviderFailure(call.failure or type(exc).__name__) from None
            finally:
                sem.release()
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
    loggers drop records below WARNING (a filter on each one) so a query never reaches the log.
    """
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
    _quiet_vendor_loggers()
    return tuple(names)


__all__ = ["ADOPTED_WEB_PLUGINS", "EGRESS_IDENTITY", "PROVIDER_TIERS", "PluginContext",
           "adapter_class", "load_web_providers"]
