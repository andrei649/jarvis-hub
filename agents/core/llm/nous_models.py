"""Bounded Nous Portal vision recommendation discovery.

Only normalized public recommendation fields are persisted. Account entitlement is
kept in process memory, scoped to the exact profile, Portal and bearer identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agents.core.paths import data_path

from .nous_auth import NousAuthError, NousCredentials, _url
from .nous_credentials import _jwt_payload, _profile_name

_RECOMMENDATION_TTL = 600
_ENTITLEMENT_TTL = 180
_STALE_LIMIT = 30 * 24 * 3600
_DEADLINE = 8.0
_MAX_BODY = 65_536
_MAX_DISK = 65_536
_MAX_ENTRIES = 32
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,255}\Z", re.ASCII)
_FIELDS = ("paidRecommendedVisionModel", "freeRecommendedVisionModel")
_FALLBACK = "google/gemini-3.6-flash"


@dataclass(frozen=True)
class Recommendation:
    model: str
    source: str


_public_cache: dict[tuple[str, str], tuple[dict[str, str], float]] = {}
_entitlement_cache: dict[tuple[str, str, str], tuple[bool | None, float]] = {}
_generations: dict[tuple[str, str], int] = {}
_next_generation = 0


def _bound(cache: dict[Any, Any]) -> None:
    while len(cache) > _MAX_ENTRIES:
        cache.pop(next(iter(cache)))


def clear_cache() -> None:
    """Drop process cache; disk last-good data remains available for restart."""
    _public_cache.clear()
    _entitlement_cache.clear()
    _generations.clear()


def wire_mode(model: str, configured: str = "chat") -> str:
    """Pinned Nous default: only explicit native Anthropic uses Messages."""
    return (
        "anthropic_messages"
        if str(model or "").strip().lower().startswith("anthropic/") and configured == "native"
        else "chat_completions"
    )


def _transport_factory() -> httpx.AsyncBaseTransport:
    from agents.core.tls_trust import tls_verify

    return httpx.AsyncHTTPTransport(verify=tls_verify(), trust_env=False, retries=0)


class _GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, guard: Callable[[httpx.Request], None]):
        self.inner = inner
        self.guard = guard

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.guard(request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def _checked(credentials: NousCredentials, validate: Callable[[], None] | None) -> None:
    if validate is not None:
        validate()
    if credentials.expires_at is not None and credentials.expires_at <= time.time():
        raise NousAuthError("reauth_required")


def _normal_model(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    model = value.get("modelName")
    if not isinstance(model, str):
        return None
    model = model.strip()
    return model if _MODEL.fullmatch(model) else None


def _normal_recommendations(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    return {field: model for field in _FIELDS if (model := _normal_model(payload.get(field)))}


def _tier_from_account(payload: Any) -> bool | None:
    if not isinstance(payload, dict) or isinstance(payload.get("error"), str):
        return None
    access = payload.get("paid_service_access")
    if isinstance(access, dict):
        for field in ("allowed", "paid_access"):
            if isinstance(access.get(field), bool):
                return access[field]
    return None


async def _get_json(
    credentials: NousCredentials, path: str, *, bearer: bool,
    validate: Callable[[], None] | None, client_factory: Any,
) -> dict[str, Any]:
    url = f"{credentials.portal_base_url}{path}"
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {credentials.api_key}"

    def guard(request: httpx.Request) -> None:
        _checked(credentials, validate)
        if request.method != "GET" or str(request.url) != url or request.content:
            raise NousAuthError("invalid_configuration")
        if request.headers.get("accept") != "application/json":
            raise NousAuthError("invalid_configuration")
        if request.headers.get("authorization") != headers.get("Authorization"):
            raise NousAuthError("invalid_configuration")
        if any(name in request.headers for name in ("cookie", "proxy-authorization")):
            raise NousAuthError("invalid_configuration")

    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(_DEADLINE),
        "trust_env": False,
        "follow_redirects": False,
        "headers": headers,
    }
    if client_factory is None:
        from .egress import llm_async_client

        kwargs["transport"] = _GuardedTransport(_transport_factory(), guard)
        client = llm_async_client("nous-metadata", **kwargs)
    else:
        client = client_factory("nous-metadata", **kwargs)
        if not isinstance(client, httpx.AsyncClient):
            raise NousAuthError("invalid_configuration")
        if any(mount is not None for mount in client._mounts.values()):
            raise NousAuthError("invalid_configuration")
        client._transport = _GuardedTransport(client._transport, guard)
    async with asyncio.timeout(_DEADLINE), client, client.stream("GET", url, follow_redirects=False) as response:
        if response.status_code != 200:
            raise httpx.HTTPStatusError("Nous metadata unavailable", request=response.request, response=response)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_BODY:
                raise ValueError("Nous metadata too large")
    _checked(credentials, validate)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("invalid Nous metadata")
    return payload


def _cache_file(cache_dir: str | Path | None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else data_path("cache", "nous")
    return root / "recommended-models.json"


def _disk_key(profile: str, portal: str) -> str:
    return hashlib.sha256(f"{profile}\0{portal}".encode()).hexdigest()


def _read_disk(path: Path, key: str) -> tuple[dict[str, str], float] | None:
    try:
        if path.stat().st_size > _MAX_DISK:
            return None
        blob = json.loads(path.read_bytes())
        entry = blob.get(key) if isinstance(blob, dict) else None
        if not isinstance(entry, dict):
            return None
        ts = float(entry.get("ts"))
        age = time.time() - ts
        if not 0 <= age <= _STALE_LIMIT:
            return None
        data = _normal_recommendations(entry.get("data"))
        return (data, ts) if data else None
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
        return None


def _write_disk(path: Path, key: str, data: dict[str, str], stamp: float) -> None:
    if not data:
        return
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            blob = json.loads(path.read_bytes()) if path.stat().st_size <= _MAX_DISK else {}
        except (OSError, ValueError, UnicodeError):
            blob = {}
        if not isinstance(blob, dict):
            blob = {}
        entries = {
            name: entry for name, entry in blob.items()
            if isinstance(name, str) and len(name) == 64 and isinstance(entry, dict)
            and isinstance(entry.get("ts"), (int, float))
            and 0 <= stamp - entry["ts"] <= _STALE_LIMIT
        }
        entries[key] = {"ts": stamp, "data": {field: {"modelName": model} for field, model in data.items()}}
        entries = dict(sorted(entries.items(), key=lambda pair: pair[1]["ts"], reverse=True)[:_MAX_ENTRIES])
        raw = json.dumps(entries, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > _MAX_DISK:
            return
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, OverflowError):
        return


def _selection(data: dict[str, str], paid: bool | None) -> Recommendation:
    if paid is not False and (model := data.get("paidRecommendedVisionModel")):
        return Recommendation(model, "nous_recommended_paid")
    if model := data.get("freeRecommendedVisionModel"):
        return Recommendation(model, "nous_recommended_free")
    return Recommendation(_FALLBACK, "nous_fallback")


def _reserve(scope: tuple[str, str]) -> int:
    global _next_generation
    _next_generation += 1
    _generations[scope] = _next_generation
    _bound(_generations)
    return _next_generation


async def recommend_vision(
    credentials: NousCredentials, *, force_refresh: bool = False,
    validate: Callable[[], None] | None = None, client_factory: Any = None,
    cache_dir: str | Path | None = None,
) -> Recommendation:
    """Select an account-appropriate vision model from bounded public Portal data."""
    _checked(credentials, validate)
    try:
        _profile_name(credentials.profile)
    except ValueError as exc:
        raise NousAuthError("invalid_configuration") from exc
    portal = _url(credentials.portal_base_url, portal=True, operator=True)
    if portal is None or portal != credentials.portal_base_url:
        raise NousAuthError("invalid_configuration")
    scope = (credentials.profile, portal)
    if httpx.URL(credentials.base_url).host == "welcome-api.nousresearch.com":
        _checked(credentials, validate)
        return Recommendation("nous/welcome", "nous_welcome")

    # A forced call awaits account metadata before public recommendations. Reserve
    # its order now, so a slower older account response cannot publish last.
    generation = _reserve(scope) if force_refresh else None
    now = time.time()
    identity = (credentials.profile, portal, hashlib.sha256(credentials.api_key.encode()).hexdigest())
    cached_tier = _entitlement_cache.get(identity)
    paid = cached_tier[0] if cached_tier and now - cached_tier[1] < _ENTITLEMENT_TTL else None
    if paid is None:
        claims = _jwt_payload(credentials.api_key)
        claim = claims.get("paid_access") if claims else None
        paid = claim if isinstance(claim, bool) else None
    if force_refresh:
        try:
            account = await _get_json(
                credentials, "/api/oauth/account", bearer=True,
                validate=validate, client_factory=client_factory,
            )
        except (httpx.HTTPError, OSError, ValueError, TimeoutError):
            account = {}
        refreshed_tier = _tier_from_account(account)
        if refreshed_tier is not None and _generations.get(scope) == generation:
            paid = refreshed_tier
            _checked(credentials, validate)
            _entitlement_cache[identity] = (paid, time.time())
            _bound(_entitlement_cache)

    path = _cache_file(cache_dir)
    key = _disk_key(*scope)
    cached = _public_cache.get(scope)
    disk = _read_disk(path, key)
    if not force_refresh and cached and 0 <= now - cached[1] < _RECOMMENDATION_TTL:
        _checked(credentials, validate)
        return _selection(cached[0], paid)
    if not force_refresh and disk and 0 <= now - disk[1] < _RECOMMENDATION_TTL:
        _checked(credentials, validate)
        _public_cache[scope] = disk
        _bound(_public_cache)
        return _selection(disk[0], paid)

    if generation is None:
        generation = _reserve(scope)
    try:
        payload = await _get_json(
            credentials, "/api/nous/recommended-models", bearer=False,
            validate=validate, client_factory=client_factory,
        )
        data = _normal_recommendations(payload)
    except (httpx.HTTPError, OSError, ValueError, TimeoutError):
        data = {}
    _checked(credentials, validate)
    if _generations.get(scope) != generation:
        latest = _public_cache.get(scope)
        data = latest[0] if latest else (disk[0] if disk else {})
        latest_tier = _entitlement_cache.get(identity)
        if latest_tier and 0 <= time.time() - latest_tier[1] < _ENTITLEMENT_TTL:
            paid = latest_tier[0]
    elif data:
        stamp = time.time()
        _public_cache[scope] = (data, stamp)
        _bound(_public_cache)
        _write_disk(path, key, data, stamp)
    else:
        data = disk[0] if disk else (cached[0] if cached else {})
    _checked(credentials, validate)
    return _selection(data, paid)
