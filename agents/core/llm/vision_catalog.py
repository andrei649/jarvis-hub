"""Public model-catalog vision evidence for a selected cloud image turn.

Only the async preparation path may fetch metadata. The synchronous review and
physical-request guard consult the last bounded in-process snapshot without I/O.
No prompt, image, model ID or model credential is sent to the catalog.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx

from .data_handling import DataHandlingRefused, physical_request_scope
from .direct_transport import require_direct_async_transport
from .egress import llm_async_client

CATALOG_URL = "https://models.dev/api.json"
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 5.0
TTL_SECONDS = 4 * 3600.0
RETRY_SECONDS = 300.0
_PROVIDERS = frozenset({"anthropic", "google", "openai", "xai", "openrouter"})

_lock = threading.Lock()
_catalog: dict[str, dict[str, bool]] | None = None
_fetched_at = 0.0
_retry_after = 0.0
_inflight: asyncio.Task | None = None
_generation = 0


def entry_vision_verdict(entry: object) -> bool | None:
    """Follow Hermes: input modalities outrank the older attachment field."""
    if type(entry) is not dict:
        return None
    modalities = entry.get("modalities")
    inputs = modalities.get("input") if type(modalities) is dict else None
    if type(inputs) is list:
        return "image" in inputs if all(type(item) is str for item in inputs) else None
    attachment = entry.get("attachment")
    return attachment if type(attachment) is bool else None


def parse_catalog(payload: object) -> dict[str, dict[str, bool]] | None:
    """Keep only explicit verdicts for native selected providers."""
    if type(payload) is not dict:
        return None
    catalog: dict[str, dict[str, bool]] = {}
    for provider in _PROVIDERS:
        row = payload.get(provider)
        models = row.get("models") if type(row) is dict else None
        if type(models) is not dict:
            continue
        verdicts = {}
        for model, entry in models.items():
            if (type(model) is not str or not model or model.strip() != model
                    or len(model) > 512):
                continue
            verdict = entry_vision_verdict(entry)
            if verdict is not None:
                verdicts[model] = verdict
        catalog[provider] = verdicts
    return catalog or None


def catalog_provider(config: object) -> str | None:
    """Map only a native adapter at its canonical destination to a catalog id."""
    from .anthropic import ANTHROPIC_API_BASE
    from .gemini import GEMINI_API_BASE
    from .responses import ENDPOINT as RESPONSES_ENDPOINT
    from .vision_openrouter import OPENROUTER_VISION_BASE
    from .vision_xai_wire import XAI_ENDPOINT

    if getattr(config, "is_local", None) is not False:
        return None
    expected = {
        "anthropic": (ANTHROPIC_API_BASE, "anthropic"),
        "gemini": (GEMINI_API_BASE, "google"),
        "openai-responses": (RESPONSES_ENDPOINT.removesuffix("/responses"), "openai"),
        "xai": (XAI_ENDPOINT.removesuffix("/responses"), "xai"),
        "openrouter": (OPENROUTER_VISION_BASE, "openrouter"),
    }
    row = expected.get(getattr(config, "backend", None))
    return row[1] if row and getattr(config, "base_url", None) == row[0] else None


def cached_vision_eligibility(config: object) -> bool | None:
    """Read the catalog verdict for this exact provider/model without I/O."""
    provider = catalog_provider(config)
    model = getattr(config, "model", None)
    if provider is None or type(model) is not str:
        return None
    with _lock:
        catalog = _catalog
    verdict = catalog.get(provider, {}).get(model) if catalog is not None else None
    return verdict if type(verdict) is bool else None


def _metadata_transport_factory() -> httpx.AsyncBaseTransport:
    from agents.core.tls_trust import verify_for

    return httpx.AsyncHTTPTransport(
        trust_env=False, retries=0, verify=verify_for("models-dev", CATALOG_URL),
    )


async def _fetch_catalog() -> dict[str, dict[str, bool]] | None:
    """Fetch one fixed public URL over direct transport with a strict body cap."""
    expected = httpx.URL(CATALOG_URL)
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with llm_async_client(
                "models-dev", transport=_metadata_transport_factory(), trust_env=False,
                follow_redirects=False, cookies=None, timeout=httpx.Timeout(TIMEOUT_SECONDS),
            ) as client:
                require_direct_async_transport(client, expected)

                def request_check(request: httpx.Request) -> None:
                    if (request.method != "GET" or request.url != expected
                            or request.content != b"" or "authorization" in request.headers
                            or "cookie" in request.headers):
                        raise DataHandlingRefused("model catalog request changed")
                    require_direct_async_transport(client, request.url)

                with physical_request_scope(None, request_check=request_check):
                    async with client.stream("GET", CATALOG_URL, follow_redirects=False) as response:
                        if response.status_code != 200:
                            return None
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_BYTES:
                                return None
                            body.extend(chunk)
        return parse_catalog(json.loads(body))
    except Exception:
        # HTTPX/AnyIO can group transport failures (including blocked sockets)
        # under ExceptionGroup. A catalog miss is unknown, never proof of false.
        return None


async def _refresh(now: float, generation: int) -> None:
    global _catalog, _fetched_at, _retry_after, _inflight
    try:
        try:
            fresh = await _fetch_catalog()
        except Exception:
            # Metadata is advisory; even an unexpected HTTPX failure cannot
            # turn an otherwise reviewed image route into a server error.
            fresh = None
        with _lock:
            if generation != _generation:
                return
            if fresh is not None:
                _catalog = fresh
                _fetched_at = now
                _retry_after = 0.0
            else:
                _retry_after = now + RETRY_SECONDS
    finally:
        with _lock:
            if _inflight is asyncio.current_task():
                _inflight = None


async def ensure_catalog(*, clock=time.monotonic) -> None:
    """Refresh once per TTL; concurrent image previews share one bounded fetch."""
    global _generation, _inflight
    now = clock()
    loop = asyncio.get_running_loop()
    with _lock:
        if _catalog is not None and now - _fetched_at < TTL_SECONDS:
            return
        if now < _retry_after:
            return
        running = _inflight
        if running is None or running.get_loop() is not loop:
            _generation += 1
            running = loop.create_task(_refresh(now, _generation))
            _inflight = running
    await asyncio.shield(running)


async def prepare_catalog_vision(backend: object, model: str, route: str) -> None:
    """Resolve selected authority before a public fetch; owner overrides skip it."""
    from .vision_capability import owner_vision_eligibility
    from .vision_main import selected_main_config
    from .vlm import VLMNotConfigured

    try:
        config = selected_main_config(backend, model, route)
    except VLMNotConfigured:
        return
    if (config is not None and catalog_provider(config) is not None
            and owner_vision_eligibility(config) is None):
        await ensure_catalog()


def reset_cache() -> None:
    """Discard public metadata between isolated tests or after an explicit reset."""
    global _catalog, _fetched_at, _retry_after, _generation, _inflight
    with _lock:
        _generation += 1
        _catalog = None
        _fetched_at = 0.0
        _retry_after = 0.0
        _inflight = None
