"""H380 — prove that a configured cloud provider actually works.

A provider counted as "configured" when its key variable was non-empty, and a cloud
route counted as ready when the router had a key to use: a wrong or revoked key was
found out by the first real turn that failed. This module asks the provider itself,
once, with the key the hub would use: one authenticated ``GET`` of its model list
(Anthropic ``/v1/models``, Gemini ``/v1beta/models``, the OpenAI-shaped
``<base>/models``), through ``llm_async_client``, so the request is in the egress
ledger and the host-protocol mandate applies to it. No prompt is sent and nothing is
generated.

The verdict is one of:

- ``ok``: the key was accepted and the list was read (``models`` is its length);
- ``no_listing``: the key was not refused, but the provider has no model list here
  (404/405); ``models`` counts the profile's ``fallback_models`` instead;
- ``auth_failed`` (401), ``forbidden`` (403), ``rate_limited`` (429), ``error`` (any
  other status, which is named): the provider answered and did not accept it;
- ``unreachable``: no answer (DNS, connection, timeout, TLS);
- ``refused``: the hub refused to send it (the host mandates another protocol);
- ``not_configured``: no key is set, so nothing was sent;
- ``not_cloud``: a local provider, which this does not probe.

Neither the key nor the response body is ever in a result or a log line. A result
is cached for :data:`TTL_SECONDS` per provider and key (a changed key is probed
afresh), and a forced re-probe of the same key is refused for
:data:`MIN_INTERVAL_SECONDS`, so a page that asks cannot turn into a stream of
requests. The admin route ``POST /api/admin/llm/providers/probe``, the HUD's model
panel and the command-center model block (read by ``nerva doctor``) use it.
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
MIN_INTERVAL_SECONDS = 30.0
TIMEOUT_SECONDS = 10.0
VERDICTS = ("ok", "no_listing", "auth_failed", "forbidden", "rate_limited", "error",
            "unreachable", "refused", "not_configured", "not_cloud")
#: The verdicts that mean the provider can answer a turn with this key.
WORKING = frozenset({"ok", "no_listing"})
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

_lock = threading.Lock()
_cache: dict[tuple[str, str], dict] = {}


def is_cloud(profile: ProviderProfile) -> bool:
    return profile.auth_type != "none"


def cloud_profiles() -> list[ProviderProfile]:
    return [p for p in list_profiles() if is_cloud(p)]


def configured_key(profile: ProviderProfile, environ: Mapping[str, str] | None = None) -> str:
    """The key the hub would use for ``profile``: the first of ``<VAR>S`` (a rotation
    pool), else ``<VAR>``; ``""`` when none is set."""
    from agents.core.env_config import env_str

    if not profile.auth_env:
        return ""
    if environ is None:
        pool, single = env_str(f"{profile.auth_env}S"), env_str(profile.auth_env)
    else:
        pool, single = str(environ.get(f"{profile.auth_env}S", "")), str(environ.get(profile.auth_env, ""))
    for part in pool.replace("\n", ",").split(","):
        if part.strip():
            return part.strip()
    return single.strip()


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def request_for(profile: ProviderProfile, key: str, environ: Mapping[str, str] | None = None) -> tuple[str, dict]:
    """The URL and headers of the probe for ``profile`` (the key only in a header)."""
    if profile.backend_kind == "anthropic":
        return ANTHROPIC_MODELS_URL, {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if profile.backend_kind == "gemini":
        return GEMINI_MODELS_URL, {"x-goog-api-key": key}
    base = str(profile.status(environ=environ).get("base_url") or profile.default_base_url or "").rstrip("/")
    return f"{base}/models", {"Authorization": f"Bearer {key}"}


def _count(response: httpx.Response) -> int | None:
    try:
        body = response.json()
    except Exception:
        return None
    for field in ("data", "models"):
        if isinstance(body, dict) and isinstance(body.get(field), list):
            return len(body[field])
    return len(body) if isinstance(body, list) else None


def _verdict(status: int) -> str:
    if 200 <= status < 300:
        return "ok"
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


async def _send(profile: ProviderProfile, key: str, environ, client_factory) -> dict:
    from .host_protocol import HostProtocolRefused

    url, headers = request_for(profile, key, environ)
    try:
        async with client_factory(profile.id, timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
    except HostProtocolRefused:
        return _result(profile, "refused")
    except httpx.TransportError:
        return _result(profile, "unreachable")
    except Exception:
        logger.warning("provider probe for %s failed", profile.id, exc_info=False)
        return _result(profile, "error")
    verdict = _verdict(response.status_code)
    return _result(profile, verdict, status=response.status_code,
                   models=_count(response) if verdict == "ok" else None)


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
    slot = (profile.id, _fingerprint(key))
    now = clock()
    with _lock:
        cached = _cache.get(slot)
    if cached is not None:
        age = now - cached["_at"]
        if age < TTL_SECONDS and not force:
            return {**_public(cached), "cached": True}
        if force and age < MIN_INTERVAL_SECONDS:
            return {**_public(cached), "cached": True, "throttled": True}
    result = await _send(profile, key, environ, client_factory or llm_async_client)
    with _lock:
        _cache[slot] = {**result, "_at": now}
    logger.info("Provider probe %s: %s", profile.id, result["verdict"])
    return result


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
        cached = _cache.get((profile.id, _fingerprint(key)))
    if cached is None or clock() - cached["_at"] >= TTL_SECONDS:
        return None
    return {**_public(cached), "cached": True}


async def probe_all(*, force: bool = False, environ: Mapping[str, str] | None = None,
                    client_factory: Callable[..., Any] | None = None) -> list[dict]:
    """Every cloud provider, concurrently (a provider with no key sends nothing)."""
    return list(await asyncio.gather(*(
        probe(p.id, force=force, environ=environ, client_factory=client_factory) for p in cloud_profiles())))


def reset() -> None:
    """Forget every cached verdict (tests; a key rotation the owner wants re-checked)."""
    with _lock:
        _cache.clear()


__all__ = [
    "MIN_INTERVAL_SECONDS", "TTL_SECONDS", "VERDICTS", "WORKING", "cloud_profiles", "configured_key",
    "is_cloud", "last", "probe", "probe_all", "request_for", "reset",
]
