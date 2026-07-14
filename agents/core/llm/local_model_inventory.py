"""Shared configured, catalog, and resident truth for local LLM providers.

Catalog availability and runtime residency are separate facts.  This module
probes both dimensions for LM Studio and Ollama, caches only those raw probe
results, and rebuilds routing/configuration and lifecycle controls on every
call so operator settings cannot be hidden by the short probe cache.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx

from agents.core.app_state import get_orch

_CACHE_TTL_SECONDS = 8.0
_DEFAULT_LM_STUDIO_URL = "http://localhost:1234"
_DEFAULT_OLLAMA_URL = "http://localhost:11434"

_raw_cache: dict[str, Any] = {"key": None, "at": 0.0, "providers": None}


def _trim_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _url(router: Any, attribute: str, default: str) -> str:
    value = getattr(router, attribute, None) if router is not None else None
    if not isinstance(value, str) or not value.strip():
        value = default
    return value.strip().rstrip("/")


def _ids(items: Any, key: str) -> set[str]:
    if not isinstance(items, list):
        raise ValueError("provider payload items must be a list")
    result: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            model_id = _trim_id(item.get(key))
            if model_id is not None:
                result.add(model_id)
    return result


def _parse_lm_catalog(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("LM Studio catalog must be an object")
    return _ids(payload.get("data") or [], "id")


def _parse_lm_residents(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("LM Studio residency must be an object")
    items = payload.get("data") or []
    if not isinstance(items, list):
        raise ValueError("LM Studio residency data must be a list")
    result: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = _trim_id(item.get("id"))
        state = item.get("state")
        if model_id is not None and isinstance(state, str) and state.lower() == "loaded":
            result.add(model_id)
    return result


def _parse_ollama_catalog(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("Ollama catalog must be an object")
    return _ids(payload.get("models") or [], "name")


def _parse_ollama_residents(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("Ollama residency must be an object")
    items = payload.get("models") or []
    if not isinstance(items, list):
        raise ValueError("Ollama residency models must be a list")
    result: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = _trim_id(item.get("name") or item.get("model"))
        if model_id is not None:
            result.add(model_id)
    return result


async def _probe(
    client: httpx.AsyncClient,
    url: str,
    parser: Callable[[Any], set[str]],
) -> tuple[bool, set[str]]:
    try:
        response = await client.get(url)
        if not response.is_success:
            return False, set()
        return True, parser(response.json())
    except Exception:
        # Public status is intentionally bounded: probe exception text can
        # contain host paths, credentials, or details from a local runtime.
        return False, set()


async def _probe_providers(lm_url: str, ollama_url: str) -> dict[str, dict[str, Any]]:
    offline = {
        "catalog_ok": False,
        "catalog_ids": set(),
        "residency_ok": False,
        "resident_ids": set(),
    }
    raw: dict[str, dict[str, Any]] = {
        "lm-studio": dict(offline),
        "ollama": dict(offline),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            lm_catalog, lm_resident, ollama_catalog, ollama_resident = await asyncio.gather(
                _probe(client, f"{lm_url}/v1/models", _parse_lm_catalog),
                _probe(client, f"{lm_url}/api/v0/models", _parse_lm_residents),
                _probe(client, f"{ollama_url}/api/tags", _parse_ollama_catalog),
                _probe(client, f"{ollama_url}/api/ps", _parse_ollama_residents),
            )
    except Exception:
        return raw

    raw["lm-studio"] = {
        "catalog_ok": lm_catalog[0],
        "catalog_ids": lm_catalog[1],
        "residency_ok": lm_resident[0],
        "resident_ids": lm_resident[1],
    }
    raw["ollama"] = {
        "catalog_ok": ollama_catalog[0],
        "catalog_ids": ollama_catalog[1],
        "residency_ok": ollama_resident[0],
        "resident_ids": ollama_resident[1],
    }
    return raw


def _provider_projection(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    catalog_ok = bool(raw["catalog_ok"])
    residency_ok = bool(raw["residency_ok"])
    online = catalog_ok or residency_ok
    return {
        "name": name,
        "online": online,
        "catalog_state": "known" if catalog_ok else ("unknown" if residency_ok else "offline"),
        "residency_state": (
            "known" if residency_ok else ("unknown" if catalog_ok else "offline")
        ),
    }


def _configured_pair(
    configured_id: str | None,
    backend: str,
    raw_by_provider: dict[str, dict[str, Any]],
) -> tuple[str, str] | None:
    if configured_id is None:
        return None
    if backend in raw_by_provider:
        return backend, configured_id
    matches = [
        name
        for name, raw in raw_by_provider.items()
        if configured_id in raw["catalog_ids"] or configured_id in raw["resident_ids"]
    ]
    if len(matches) == 1:
        return matches[0], configured_id
    return "unknown", configured_id


def _controls(
    *,
    provider: str,
    available: bool | None,
    resident: bool | None,
    controller_enabled: bool,
) -> dict[str, bool]:
    return {
        "can_configure": available is True,
        "can_load": bool(
            provider == "lm-studio"
            and controller_enabled
            and available is True
            and resident is False
        ),
        "can_unload": bool(
            provider == "lm-studio" and controller_enabled and resident is True
        ),
    }


async def get_local_model_inventory(
    *,
    router: Any = None,
    controller: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return shared local-model truth with stable provider/model identity."""
    orch = get_orch()
    if router is None:
        router = getattr(orch, "llm_router", None) if orch is not None else None
    if controller is None:
        controller = getattr(orch, "lmstudio", None) if orch is not None else None

    lm_url = _url(router, "lm_studio_url", _DEFAULT_LM_STUDIO_URL)
    ollama_url = _url(router, "ollama_url", _DEFAULT_OLLAMA_URL)
    cache_key = (lm_url, ollama_url)
    now = time.monotonic()
    if (
        force_refresh
        or _raw_cache["providers"] is None
        or _raw_cache["key"] != cache_key
        or now - float(_raw_cache["at"]) >= _CACHE_TTL_SECONDS
    ):
        _raw_cache.update(
            key=cache_key,
            at=now,
            providers=await _probe_providers(lm_url, ollama_url),
        )

    raw_by_provider = _raw_cache["providers"]
    providers = [
        _provider_projection(name, raw_by_provider[name])
        for name in sorted(raw_by_provider)
    ]
    aggregate_residency = (
        "offline"
        if not any(provider["online"] for provider in providers)
        else "unknown"
        if any(
            provider["online"] and provider["residency_state"] == "unknown"
            for provider in providers
        )
        else "known"
    )

    configured_id = _trim_id(getattr(router, "active_model", None)) if router else None
    backend_value = getattr(router, "_backend_name", None) if router else None
    backend = backend_value.strip() if isinstance(backend_value, str) and backend_value.strip() else "none"
    configured_pair = _configured_pair(configured_id, backend, raw_by_provider)
    controller_enabled = bool(getattr(controller, "enabled", False))

    rows: list[dict[str, Any]] = []
    resident_models: list[dict[str, str]] = []
    for provider in sorted(raw_by_provider):
        raw = raw_by_provider[provider]
        catalog_known = bool(raw["catalog_ok"])
        residency_known = bool(raw["residency_ok"])
        model_ids = set(raw["catalog_ids"]) | set(raw["resident_ids"])
        if configured_pair and configured_pair[0] == provider:
            model_ids.add(configured_pair[1])
        for model_id in sorted(model_ids):
            available = model_id in raw["catalog_ids"] if catalog_known else None
            resident = model_id in raw["resident_ids"] if residency_known else None
            configured = configured_pair == (provider, model_id)
            rows.append(
                {
                    "id": model_id,
                    "provider": provider,
                    "available": available,
                    "configured": configured,
                    "active": configured,
                    "resident": resident,
                    "controls": _controls(
                        provider=provider,
                        available=available,
                        resident=resident,
                        controller_enabled=controller_enabled,
                    ),
                }
            )
            if resident is True:
                resident_models.append({"provider": provider, "id": model_id})

    if configured_pair and configured_pair[0] == "unknown":
        rows.append(
            {
                "id": configured_pair[1],
                "provider": "unknown",
                "available": None,
                "configured": True,
                "active": True,
                "resident": None,
                "controls": _controls(
                    provider="unknown",
                    available=None,
                    resident=None,
                    controller_enabled=controller_enabled,
                ),
            }
        )

    rows.sort(key=lambda row: (row["provider"], row["id"]))
    resident_models.sort(key=lambda row: (row["provider"], row["id"]))
    return {
        "active": configured_id,
        "configured_model": configured_id,
        "resident_models": resident_models,
        "residency_state": aggregate_residency,
        "backend": backend,
        "providers": providers,
        "models": rows,
    }


def project_llm_status(inventory: dict[str, Any]) -> dict[str, Any]:
    """Project the shared inventory into the legacy HUD status vocabulary."""
    resident_models = list(inventory.get("resident_models") or [])
    residency_state = inventory.get("residency_state") or "offline"
    providers = inventory.get("providers") or []
    if resident_models:
        model_state = "ready"
    elif residency_state == "unknown":
        model_state = "unknown"
    elif any(provider.get("online") for provider in providers):
        model_state = "no_model"
    else:
        model_state = "offline"

    resident_pairs = {
        (row.get("provider"), row.get("id"))
        for row in resident_models
        if isinstance(row, dict)
    }
    configured_resident = next(
        (
            row.get("id")
            for row in (inventory.get("models") or [])
            if isinstance(row, dict)
            and row.get("configured") is True
            and (row.get("provider"), row.get("id")) in resident_pairs
        ),
        None,
    )
    loaded_model = configured_resident
    if loaded_model is None and resident_models:
        loaded_model = resident_models[0].get("id")

    return {
        "model_state": model_state,
        "model_loaded": bool(resident_models),
        "loaded_model": loaded_model,
        "resident_models": resident_models,
        "residency_state": residency_state,
        # Compatibility aliases consumed by web._llm_ready().
        "state": model_state,
        "model": loaded_model,
    }


def invalidate_local_model_inventory_cache() -> None:
    """Discard cached raw provider probes after a lifecycle mutation."""
    _raw_cache.update(key=None, at=0.0, providers=None)
