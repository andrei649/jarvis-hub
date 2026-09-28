"""H380 — prove that a configured cloud provider actually works.

A provider counted as "configured" when its key variable was non-empty, and a cloud
route counted as ready when the router had a key to use: a wrong or revoked key was
found out by the first real turn that failed. This module asks the provider itself,
once, with the key the hub would use: one authenticated ``GET`` (Anthropic
``/v1/models``, Gemini ``/v1beta/models``, OpenRouter ``<base>/key`` — its model list
answers without any key — and the OpenAI-shaped ``<base>/models``), through
``llm_async_client`` with the backend's own proxy setting, so the request is in the
egress ledger and the host-protocol mandate and the shared 429 guard apply to it. No
prompt is sent and nothing is generated.

The verdict is one of:

- ``ok``: the key was accepted (``models`` is the list's length when there is one);
- ``no_listing``: nothing at that URL (404/405: a wrong base URL, or a gateway without
  a model list), so the key was never evaluated and is not proven to work; ``models``
  counts the profile's ``fallback_models`` instead;
- ``auth_failed`` (401, or a 400 that names a bad key), ``forbidden`` (403),
  ``rate_limited`` (429), ``error`` (any other status, which is named): the provider
  answered and did not accept it;
- ``rate_limited`` too when the shared 429 guard (H373) holds the key: nothing was sent;
- ``unreachable``: no answer (DNS, connection, timeout, TLS);
- ``refused``: the hub refused to send it (the host mandates another protocol);
- ``not_configured``: no key is set, so nothing was sent;
- ``not_cloud``: a local provider, which this does not probe.

Neither the key nor the response body is ever in a result or a log line. A result
is cached for :data:`TTL_SECONDS` per provider, key and URL (a changed key or base URL
is probed afresh), a transient one (:data:`TRANSIENT`) for
:data:`TRANSIENT_TTL_SECONDS` only; concurrent callers share one request, and a forced
re-probe of the same key is refused for :data:`MIN_INTERVAL_SECONDS`, so a page that
asks cannot turn into a stream of requests. The admin route
``POST /api/admin/llm/providers/probe``, the HUD's model panel and the command-center
model block (read by ``nerva doctor``) use it.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from .providers import ProviderProfile, get_profile, list_profiles

logger = logging.getLogger("jarvis.llm.provider_probe")

TTL_SECONDS = 300.0
#: A verdict that says nothing lasting about the key is asked again this soon.
TRANSIENT_TTL_SECONDS = 30.0
MIN_INTERVAL_SECONDS = 30.0
TIMEOUT_SECONDS = 10.0
VERDICTS = ("ok", "no_listing", "auth_failed", "forbidden", "rate_limited", "error",
            "unreachable", "refused", "not_configured", "not_cloud")
#: The verdict that means the provider accepted this key.
WORKING = frozenset({"ok"})
TRANSIENT = frozenset({"rate_limited", "error", "unreachable"})
#: The profiles whose router reads a rotation pool, ``<VAR>S`` before ``<VAR>``
#: (``HybridRouter.detect``); every other backend reads ``<VAR>`` only.
POOLED = frozenset({"anthropic", "gemini"})
#: The profiles whose backend never takes the environment's proxy or CA (``trust_env``).
NO_ENV_TRUST = frozenset({"xai", "openai-responses"})
#: A 400 that names a bad key: Gemini's ErrorInfo reasons (xAI says "Incorrect API key").
BAD_KEY_REASONS = frozenset({"API_KEY_INVALID", "API_KEY_EXPIRED"})
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

_lock = threading.Lock()
_cache: dict[tuple[str, str, str], dict] = {}
_inflight: dict[tuple[str, str, str], asyncio.Task] = {}


def is_cloud(profile: ProviderProfile) -> bool:
    return profile.auth_type != "none"


def cloud_profiles() -> list[ProviderProfile]:
    return [p for p in list_profiles() if is_cloud(p)]


def configured_key(profile: ProviderProfile, environ: Mapping[str, str] | None = None) -> str:
    """The key the hub would use for ``profile``: for a pooled provider the first of
    ``<VAR>S``, split as the pool splits it; else ``<VAR>``; ``""`` when none is set."""
    from agents.core.env_config import env_str

    from .auth_rotation import _split_keys

    if not profile.auth_env:
        return ""
    read = env_str if environ is None else (lambda name: str(environ.get(name, "")))
    pool = _split_keys(read(f"{profile.auth_env}S")) if profile.id in POOLED else []
    return pool[0] if pool else read(profile.auth_env).strip()


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def request_for(profile: ProviderProfile, key: str, environ: Mapping[str, str] | None = None) -> tuple[str, dict]:
    """The URL and headers of the probe for ``profile`` (the key only in a header)."""
    if profile.backend_kind == "anthropic":
        return ANTHROPIC_MODELS_URL, {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if profile.backend_kind == "gemini":
        return GEMINI_MODELS_URL, {"x-goog-api-key": key}
    base = str(profile.status(environ=environ).get("base_url") or profile.default_base_url or "").rstrip("/")
    # OpenRouter's model list answers anyone; ``/key`` answers only for a key it knows.
    path = "key" if profile.id == "openrouter" else "models"
    return f"{base}/{path}", {"Authorization": f"Bearer {key}"}


def _slot(profile: ProviderProfile, key: str, environ: Mapping[str, str] | None) -> tuple[str, str, str]:
    return profile.id, _fingerprint(key), request_for(profile, key, environ)[0]


def _count(response: httpx.Response) -> int | None:
    try:
        body = response.json()
    except Exception:
        return None
    for field in ("data", "models"):
        if isinstance(body, dict) and isinstance(body.get(field), list):
            return len(body[field])
    return len(body) if isinstance(body, list) else None


def _names_a_bad_key(response: httpx.Response) -> bool:
    """A 400 whose body says the key is bad (read here, never returned)."""
    try:
        body = response.json()
    except Exception:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str):
        return error.startswith("Incorrect API key")
    details = error.get("details") if isinstance(error, dict) else None
    return isinstance(details, list) and any(
        isinstance(d, dict) and d.get("reason") in BAD_KEY_REASONS for d in details)


def _verdict(response: httpx.Response) -> str:
    status = response.status_code
    if 200 <= status < 300:
        return "ok"
    if status == 400 and _names_a_bad_key(response):
        return "auth_failed"
    return {401: "auth_failed", 403: "forbidden", 404: "no_listing", 405: "no_listing",
            429: "rate_limited"}.get(status, "error")


def _result(profile: ProviderProfile, verdict: str, *, status: int | None = None,
            models: int | None = None, now: float | None = None) -> dict:
    if verdict == "no_listing":
        models = len(profile.fallback_models)
    return {
        "provider": profile.id, "display_name": profile.display_name, "verdict": verdict,
        "working": verdict in WORKING, "status_code": status, "models": models,
        "checked_at": time.time() if now is None else now, "cached": False, "throttled": False,
    }


def _held_for(profile: ProviderProfile, refusal: Exception) -> float:
    """How much longer the shared 429 guard holds this key, at most the transient TTL."""
    from .quota import get_store, key_fingerprint

    try:
        until = get_store().blocked_until(profile.id, key_fingerprint(refusal.request))
    except Exception:
        until = None
    return min(TRANSIENT_TTL_SECONDS, max(0.0, (until or 0.0) - time.time()))


async def _send(profile: ProviderProfile, key: str, environ, client_factory) -> dict:
    from .host_protocol import HostProtocolRefused
    from .quota import ProviderRateLimited

    url, headers = request_for(profile, key, environ)
    # The backend's own network path: xAI and OpenAI Responses never take the env's proxy.
    options = {"trust_env": False} if profile.id in NO_ENV_TRUST else {}
    try:
        async with client_factory(profile.id, timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                  **options) as client:
            response = await client.get(url, headers=headers)
    except HostProtocolRefused:
        return _result(profile, "refused")
    except ProviderRateLimited as exc:
        # Held by the shared 429 guard: nothing was sent, and the verdict lasts no longer
        # than the hold.
        return {**_result(profile, "rate_limited"), "_ttl": _held_for(profile, exc)}
    except httpx.TransportError:
        return _result(profile, "unreachable")
    except Exception:
        logger.warning("provider probe for %s failed", profile.id, exc_info=False)
        return _result(profile, "error")
    verdict = _verdict(response)
    return _result(profile, verdict, status=response.status_code,
                   models=_count(response) if verdict == "ok" else None)


async def _fresh(slot: tuple[str, str, str], profile: ProviderProfile, key: str, environ,
                 client_factory, now: float) -> dict:
    """One request, cached; every caller that asks meanwhile awaits this one."""
    try:
        result = await _send(profile, key, environ, client_factory)
        hold = result.pop("_ttl", None)
        ttl = TTL_SECONDS if result["verdict"] not in TRANSIENT else (
            TRANSIENT_TTL_SECONDS if hold is None else hold)
        with _lock:
            _cache[slot] = {**result, "_at": now, "_ttl": ttl}
        logger.info("Provider probe %s: %s", profile.id, result["verdict"])
        return result
    finally:
        with _lock:
            if _inflight.get(slot) is asyncio.current_task():
                del _inflight[slot]


async def probe(provider_id: str, *, key: str | None = None, force: bool = False,
                environ: Mapping[str, str] | None = None,
                client_factory: Callable[..., Any] | None = None,
                clock: Callable[[], float] = time.monotonic) -> dict:
    """The verdict for one provider, from the cache when it is fresh (see the module)."""
    from .egress import llm_async_client

    profile = get_profile(provider_id)
    if not is_cloud(profile):
        return _result(profile, "not_cloud")
    key = (configured_key(profile, environ) if key is None else str(key)).strip()
    if not key:
        return _result(profile, "not_configured")
    slot = _slot(profile, key, environ)
    now = clock()
    loop = asyncio.get_running_loop()
    with _lock:
        cached, running = _cache.get(slot), _inflight.get(slot)
        if running is not None and running.get_loop() is not loop:
            running = None                      # another loop's request cannot be awaited here
        if running is None and cached is not None:
            age = now - cached["_at"]
            if age < cached["_ttl"] and not force:
                return {**_public(cached), "cached": True}
            if force and age < MIN_INTERVAL_SECONDS:
                return {**_public(cached), "cached": True, "throttled": True}
        joined = running is not None
        if not joined:
            running = loop.create_task(
                _fresh(slot, profile, key, environ, client_factory or llm_async_client, now))
            _inflight[slot] = running
    # Shielded: a caller that stops waiting leaves the request to finish and be cached.
    result = await asyncio.shield(running)
    return {**result, "cached": True, "throttled": force} if joined else result


def _public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def last(provider_id: str, *, key: str | None = None, environ: Mapping[str, str] | None = None,
         clock: Callable[[], float] = time.monotonic) -> dict | None:
    """The cached verdict for this provider and key while it is fresh, or None. No request."""
    profile = get_profile(provider_id)
    key = (configured_key(profile, environ) if key is None else str(key)).strip()
    if not key:
        return None
    with _lock:
        cached = _cache.get(_slot(profile, key, environ))
    if cached is None or clock() - cached["_at"] >= cached["_ttl"]:
        return None
    return {**_public(cached), "cached": True}


def _selected_compatible() -> str:
    """The owner's ``llm.compatible_provider`` (``""`` when unset or unreadable)."""
    try:
        from agents.core.settings_db import get_value

        return str(get_value("llm", "compatible_provider", "") or "").strip().lower()
    except Exception:
        return ""


def _key_for_elsewhere(profile: ProviderProfile, environ: Mapping[str, str] | None, selected: str) -> bool:
    """True when ``profile`` shares its key variable with a profile whose base URL is on
    another host: an ``OPENAI_API_KEY`` beside an ``OPENAI_BASE_URL`` on a gateway is that
    gateway's key, sent to api.openai.com only when the owner selected OpenAI Responses."""
    from .host_protocol import hostname_of

    if profile.base_url_env or profile.id == selected:
        return False
    home = hostname_of(profile.default_base_url)
    return any(other.auth_env == profile.auth_env and other.base_url_env
               and hostname_of(other.status(environ=environ)["base_url"]) != home
               for other in cloud_profiles())


async def probe_all(*, force: bool = False, environ: Mapping[str, str] | None = None,
                    client_factory: Callable[..., Any] | None = None) -> list[dict]:
    """Every cloud provider, concurrently (a provider with no key sends nothing, and a key
    that belongs to another host is not sent to this one: :func:`_key_for_elsewhere`)."""
    selected = _selected_compatible()
    return list(await asyncio.gather(*(
        probe(p.id, force=force, environ=environ, client_factory=client_factory)
        for p in cloud_profiles() if not _key_for_elsewhere(p, environ, selected))))


def reset() -> None:
    """Forget every cached verdict (tests; a key rotation the owner wants re-checked)."""
    with _lock:
        _cache.clear()
        _inflight.clear()


__all__ = [
    "MIN_INTERVAL_SECONDS", "TRANSIENT", "TRANSIENT_TTL_SECONDS", "TTL_SECONDS", "VERDICTS", "WORKING",
    "cloud_profiles", "configured_key", "is_cloud", "last", "probe", "probe_all", "request_for", "reset",
]
