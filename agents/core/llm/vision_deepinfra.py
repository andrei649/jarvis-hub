"""Explicit DeepInfra vision role with scoped, bounded catalog discovery.

Only ``prepare_config`` performs metadata I/O. Normal role resolution reads an
explicit model or the validated in-process selection for these exact settings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..env_config import env_str
from .egress import llm_async_client
from .vision_openrouter import _validated_base

DEEPINFRA_VISION_BASE = "https://api.deepinfra.com/v1/openai"
_CATALOG_QUERY = "filter=true&sort_by=hermes"
_CATALOG_LIMIT = 2 * 1024 * 1024
_METADATA_DEADLINE = 5.0
_CACHE_LIMIT = 32
_NEGATIVE_TTL = 60.0
_SURFACE_TAGS = frozenset({"chat", "embed", "image-gen", "tts", "stt", "video-gen"})
_EXCLUDE = re.compile(r"(?i)(embed|rerank|whisper|stable-diffusion|flux|sdxl|"
                      r"tts|bark|speech|image-gen|clip|vit-|dpt-)")


@dataclass(frozen=True)
class _Settings:
    base: str
    local: bool
    key: str
    model: str
    scope: tuple[str, str]


@dataclass(frozen=True)
class _CacheEntry:
    model: str
    failed_at: float | None = None
    owner: object | None = None


_cache: OrderedDict[tuple[str, str], _CacheEntry] = OrderedDict()


def clear_cache() -> None:
    """Discard in-process catalog selections, for explicit reset and tests."""
    _cache.clear()


def _read(env: Mapping[str, str] | None, name: str) -> str:
    return str(env.get(name, "") or "") if env is not None else env_str(name, "")


def _valid_model(raw: str) -> str | None:
    model = raw.strip()
    if (not model or len(raw) > 512
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        return None
    return model


def _validated_settings(env: Mapping[str, str] | None) -> _Settings:
    from .vlm import VLMNotConfigured

    if _read(env, "JARVIS_ROLE_VISION_PROVIDER").strip().lower() != "deepinfra":
        raise VLMNotConfigured("vlm_disabled")
    raw_base = (_read(env, "JARVIS_ROLE_VISION_BASE_URL")
                or _read(env, "DEEPINFRA_BASE_URL") or DEEPINFRA_VISION_BASE)
    try:
        base, local, origin = _validated_base(raw_base)
    except ValueError:
        raise VLMNotConfigured("vlm_url_invalid") from None
    base = base.rstrip("/")
    dedicated = _read(env, "JARVIS_ROLE_VISION_KEY").strip()
    ambient = _read(env, "DEEPINFRA_API_KEY").strip()
    key = dedicated or (ambient if origin == ("https", "api.deepinfra.com", 443) else "")
    if not key:
        raise VLMNotConfigured("vlm_key_unset")
    if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise VLMNotConfigured("vlm_key_invalid")
    raw_model = _read(env, "JARVIS_ROLE_VISION_MODEL")
    model = _valid_model(raw_model) if raw_model.strip() else ""
    if raw_model.strip() and model is None:
        raise VLMNotConfigured("vlm_model_invalid")
    parts = urlsplit(base)
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    endpoint = f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}:{port}{parts.path.rstrip('/')}"
    scope = (endpoint, hashlib.sha256(key.encode("ascii")).hexdigest())
    return _Settings(base, local, key, model or "", scope)


def model_source(env: Mapping[str, str] | None = None) -> str:
    return "JARVIS_ROLE_VISION_MODEL" if _read(env, "JARVIS_ROLE_VISION_MODEL").strip() else "deepinfra_catalog"


def _cached_model(settings: _Settings) -> str:
    entry = _cache.get(settings.scope)
    if entry is None:
        return ""
    _cache.move_to_end(settings.scope)
    if entry.model:
        return entry.model
    if entry.owner is not None:
        # A pure role/status read may report unavailable while discovery runs,
        # but it must not revoke the fetch's bounded publication slot.
        return ""
    if entry.failed_at is not None and time.monotonic() - entry.failed_at < _NEGATIVE_TTL:
        return ""
    _cache.pop(settings.scope, None)
    return ""


def _put_cache(scope: tuple[str, str], entry: _CacheEntry) -> None:
    _cache[scope] = entry
    _cache.move_to_end(scope)
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)


def resolve_config(env: Mapping[str, str] | None = None):
    """Resolve only an explicit or already discovered model, without I/O."""
    from .vlm import VLMConfig, VLMNotConfigured

    settings = _validated_settings(env)
    model = settings.model or _cached_model(settings)
    if not model:
        raise VLMNotConfigured("vlm_model_unset")
    return VLMConfig(backend="deepinfra", base_url=settings.base, model=model,
                     api_key=settings.key, is_local=settings.local)


def _select_model(data: object) -> str:
    if not isinstance(data, list):
        return ""
    for item in data:
        if not isinstance(item, dict) or item.get("metadata") is None:
            continue
        model = item.get("id")
        if not isinstance(model, str) or _valid_model(model) is None:
            continue
        metadata = item["metadata"] if isinstance(item["metadata"], dict) else {}
        raw_tags = metadata.get("tags")
        tags = raw_tags if isinstance(raw_tags, list) else []
        if any(tag in _SURFACE_TAGS for tag in tags):
            chat = "chat" in tags
        else:
            chat = not _EXCLUDE.search(model)
        if chat and "vision" in tags:
            return model.strip()
    return ""


def _metadata_transport_factory() -> httpx.AsyncBaseTransport:
    # Explicit native transport prevents environment proxy, cookie, and redirect
    # settings from changing where the credential-bearing request goes.
    return httpx.AsyncHTTPTransport(trust_env=False, retries=0)


class _CatalogRefused(Exception):
    pass


class _GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, env: Mapping[str, str] | None,
                 expected: _Settings, url: str):
        self.inner = inner
        self.env = env
        self.expected = expected
        self.url = url

    def check_live(self) -> None:
        try:
            now = _validated_settings(self.env)
        except Exception:
            raise _CatalogRefused from None
        if now != self.expected:
            raise _CatalogRefused

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.check_live()
        if (request.method != "GET" or request.url != httpx.URL(self.url)
                or request.headers.get("authorization") != f"Bearer {self.expected.key}"):
            raise _CatalogRefused
        response = await self.inner.handle_async_request(request)
        try:
            self.check_live()
        except _CatalogRefused:
            await response.aclose()
            raise
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def _fetch_catalog(settings: _Settings, env: Mapping[str, str] | None) -> str:
    url = f"{settings.base}/models?{_CATALOG_QUERY}"
    guard = _GuardedTransport(_metadata_transport_factory(), env, settings, url)
    try:
        async with (
            asyncio.timeout(_METADATA_DEADLINE),
            llm_async_client(
                "deepinfra", transport=guard, trust_env=False, follow_redirects=False,
                cookies=None, timeout=httpx.Timeout(_METADATA_DEADLINE),
            ) as client,
            client.stream("GET", url, headers={"Authorization": f"Bearer {settings.key}"}) as response,
        ):
            guard.check_live()
            if response.status_code != 200:
                return ""
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > _CATALOG_LIMIT:
                    return ""
                content.extend(chunk)
            guard.check_live()
            payload = json.loads(content)
            return _select_model(payload.get("data")) if isinstance(payload, dict) else ""
    except Exception:
        return ""


async def prepare_config(env: Mapping[str, str] | None = None, *, force_refresh: bool = False):
    """Prepare a catalog selection for the selected role, then resolve it purely."""
    from .vlm import VLMNotConfigured

    settings = _validated_settings(env)
    if settings.model:
        return resolve_config(env)
    if force_refresh:
        _cache.pop(settings.scope, None)
    elif _cached_model(settings):
        return resolve_config(env)
    else:
        entry = _cache.get(settings.scope)
        if entry is not None and entry.failed_at is not None:
            raise VLMNotConfigured("vlm_model_unset")
    # The bounded cache slot itself owns this request. A later refresh, another
    # fetch, eviction, or clear_cache replaces/removes the slot, so an older
    # result cannot publish even when the endpoint and credential are unchanged.
    owner = object()
    _put_cache(settings.scope, _CacheEntry("", owner=owner))
    try:
        model = await _fetch_catalog(settings, env)
    except BaseException:
        entry = _cache.get(settings.scope)
        if entry is not None and entry.owner is owner:
            _cache.pop(settings.scope, None)
        raise
    entry = _cache.get(settings.scope)
    if entry is None or entry.owner is not owner:
        raise VLMNotConfigured("vlm_model_unset")
    try:
        if _validated_settings(env) != settings:
            _cache.pop(settings.scope, None)
            raise VLMNotConfigured("vlm_model_unset")
    except VLMNotConfigured:
        _cache.pop(settings.scope, None)
        raise VLMNotConfigured("vlm_model_unset") from None
    _put_cache(settings.scope, _CacheEntry(model, None if model else time.monotonic()))
    if not model:
        raise VLMNotConfigured("vlm_model_unset")
    return resolve_config(env)
