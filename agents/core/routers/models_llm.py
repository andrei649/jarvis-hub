"""Models / LLM-control endpoints — extracted from web.py (CLN-3).

Covers two address spaces that together form the LLM-control surface:

* `/api/llm/*` — GBNF grammar generation (H13.2), the OpenRouter `/model`
  hot-swap parser (H20.2), the MoE thinking-routing preview (H13.4), masked
  cloud auth-profile pools (H12.20), and the LM Studio lifecycle controls
  (start server / load / unload).
* `/api/models/*` — local-model browse + switch (H12.9): list models from the
  live local backends (LM Studio + Ollama) and activate one on the router.

Orchestrator-only state is read at request time via `get_orch()`. One web.py
helper is kept in `web.py` because the local-models test suite monkeypatches it
on the module (`monkeypatch.setattr(web, "_list_local_models", ...)`). The helper
delegates to the shared local-model inventory and is reached at request time through
`sys.modules.get("agents.web")._list_local_models` so the monkeypatch is observed
and there is no static import edge back into web. `put_category` is imported here
directly from its leaf module (`core.settings_db`); the local-models suite patches
it in this module's namespace. The LM Studio lifecycle helpers `_lmstudio_or_503`
/ `_llm_status_code` were used only by this domain and are moved here verbatim.
"""

import asyncio
import os
import sys
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.settings_db import get_value, put_category

from agents.core.app_state import get_orch
from agents.core.llm.local_model_inventory import invalidate_local_model_inventory_cache
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import logger, nocache_json

router = APIRouter(tags=["models"])
_model_switch_lock = asyncio.Lock()


def _web():
    # Always present at request time (the app is running). Not an import edge.
    # `_list_local_models` is monkeypatched on `agents.web` by the local-models
    # test suite, so it must be resolved here on each call.
    return sys.modules.get("agents.web")


@router.post("/api/llm/grammar", dependencies=[Depends(user_guard)])
async def llm_grammar(req: Request):
    """Generate a GBNF grammar from a JSON schema or tool spec (constrained decoding)."""
    from agents.core.llm.grammar import json_schema_to_gbnf, tool_to_gbnf
    try:
        body = await req.json()
    except Exception:
        body = {}
    if (body or {}).get("tool"):
        return nocache_json({"gbnf": tool_to_gbnf(body["tool"])})
    if (body or {}).get("schema"):
        return nocache_json({"gbnf": json_schema_to_gbnf(body["schema"])})
    return JSONResponse({"error": "schema or tool required"}, status_code=400)


class ModelSwapBody(BaseModel):
    command: str = Field(..., max_length=200)


@router.post("/api/llm/openrouter", dependencies=[Depends(admin_guard)])
async def llm_openrouter_swap(body: ModelSwapBody):
    """H20.2 — parse a `/model` hot-swap command; report OpenRouter availability."""
    from agents.core.llm.openrouter import parse_model_command, OPENROUTER_BASE
    parsed = parse_model_command(body.command)
    if parsed is None:
        return nocache_json({"ok": False, "reason": "not_a_model_command"}, status_code=422)
    return nocache_json({"ok": True, "parsed": parsed, "base": OPENROUTER_BASE,
                         "configured": bool(os.environ.get("OPENROUTER_API_KEY", ""))})


class MoERouteBody(BaseModel):
    prompt: str = Field(..., max_length=8000)
    model: str = Field("gpt-oss-20b", max_length=80)


@router.post("/api/llm/moe/route", dependencies=[Depends(admin_guard)])
async def llm_moe_route(body: MoERouteBody):
    """H13.4 — preview the MoE thinking/non-thinking routing decision."""
    from agents.core.llm.moe_routing import route_moe
    return nocache_json(route_moe(body.prompt, model=body.model))


# ── Local model management (browse / switch) — H12.9 ─────────────
#
# Surfaces models available in the live local backends (LM Studio + Ollama,
# the same providers the HybridRouter talks to) so the HUD can browse them,
# see which is active, and switch with a single click — Jan.ai style.
#
# `_list_local_models` stays in web.py as a compatibility seam because the test
# suite monkeypatches it on that module. It delegates to the shared inventory and
# is read here via `_web()._list_local_models()` so those patches are observed.


@router.get("/api/models/local", dependencies=[Depends(admin_guard)])
async def models_local_list():
    """List local models from LM Studio / Ollama and mark the active one."""
    catalog = await _web()._list_local_models()
    # H23.2 (opt-in): teach the model-info registry the fingerprints of whatever the
    # local backends currently report, so traces can be stamped with {id, version,
    # quant, sha256}. Best-effort; a no-op when JARVIS_MODEL_INFO is unset (registry
    # is None) and never fatal to the listing.
    orch = get_orch()
    reg = getattr(orch, "model_info", None) if orch else None
    if reg is not None:
        try:
            reg.ingest_listing(catalog)
        except Exception:
            logger.debug("model_info ingest_listing failed", exc_info=True)
    return nocache_json(catalog)


@router.get("/api/models/info", dependencies=[Depends(admin_guard)])
async def models_info():
    """H23.2 read surface: recorded model fingerprints ``{id, version, quant, sha256}``
    for reproducibility — which exact model build produced each run.

    A pure read of the in-memory registry (populated as a side effect of listing local
    models / running traced requests). Reports ``enabled: false`` with empty data when
    JARVIS_MODEL_INFO is unset."""
    orch = get_orch()
    reg = getattr(orch, "model_info", None) if orch else None
    if reg is None:
        return nocache_json({"enabled": False, "models": [],
                             "stats": {"total": 0, "with_sha256": 0, "with_quant": 0}})
    return nocache_json({"enabled": True, "models": reg.all(), "stats": reg.stats()})


class LocalModelSwitch(BaseModel):
    model: str = Field(..., min_length=1)
    provider: Literal["lm-studio", "ollama"] | None = None


def _local_provider_name(router_) -> str:
    value = getattr(router_, "_backend_name", None)
    return value.strip() if isinstance(value, str) and value.strip() else "none"


async def _restore_local_provider(
    router_,
    *,
    provider: str,
    backend_type,
    default_model,
    runtime_model: str | None,
) -> dict[str, bool]:
    """Attempt and verify persisted plus live cross-provider rollback."""
    settings_write_ok = False
    try:
        updated, skipped = put_category(
            "llm",
            {"backend_type": backend_type, "default_model": default_model},
        )
        settings_write_ok = updated == 2 and not skipped
    except Exception:
        pass

    settings_readback_ok = False
    try:
        restored_backend_type = get_value("llm", "backend_type", None)
        restored_default_model = get_value("llm", "default_model", None)
        settings_readback_ok = (
            restored_backend_type == backend_type
            and restored_default_model == default_model
        )
    except Exception:
        pass

    provider_restored = False
    try:
        router_.backend_type = backend_type
        await router_.detect()
        provider_restored = _local_provider_name(router_) == provider
    except Exception:
        pass

    runtime_model_restored = False
    if provider_restored:
        try:
            if getattr(router_, "active_model", None) != runtime_model:
                router_.set_active_model(runtime_model)
            runtime_model_restored = getattr(router_, "active_model", None) == runtime_model
        except Exception:
            pass

    result = {
        "settings_write": settings_write_ok,
        "settings_readback": settings_readback_ok,
        "provider": provider_restored,
        "runtime_model": runtime_model_restored,
    }
    result["ok"] = all(result.values())
    return result


async def _finish_local_provider_restore(
    router_, **restore_kwargs
) -> tuple[dict[str, bool], bool]:
    """Finish rollback before propagating cancellation to the switch caller."""
    restore = asyncio.create_task(_restore_local_provider(router_, **restore_kwargs))
    cancelled_during_restore = False
    while not restore.done():
        try:
            await asyncio.shield(restore)
        except asyncio.CancelledError:
            # Keep the shared switch lock held until the live and persisted
            # pair is restored, even if the client cancels more than once.
            cancelled_during_restore = True
    return restore.result(), cancelled_during_restore


async def _adopt_local_provider(router_, *, provider: str, model: str) -> dict[str, bool]:
    """Persist and adopt one exact local provider, rolling back on failure."""
    old_provider = _local_provider_name(router_)
    old_runtime_model = getattr(router_, "active_model", None)
    old_backend_type = get_value("llm", "backend_type", "auto")
    old_default_model = get_value("llm", "default_model", "")

    try:
        updated, skipped = put_category(
            "llm", {"backend_type": provider, "default_model": model}
        )
        if updated != 2 or skipped:
            raise RuntimeError("provider selection was not fully persisted")
        # Base LLMRouter instances honor this directly; HybridRouter.detect()
        # deliberately reloads the same value from the setting persisted above.
        router_.backend_type = provider
        await router_.detect()
        if _local_provider_name(router_) != provider:
            raise RuntimeError("provider adoption did not take effect")
        router_.set_active_model(model)
    except asyncio.CancelledError:
        rollback, _ = await _finish_local_provider_restore(
            router_,
            provider=old_provider,
            backend_type=old_backend_type,
            default_model=old_default_model,
            runtime_model=old_runtime_model,
        )
        if not rollback["ok"]:
            logger.critical(
                "local provider rollback incomplete after cancelled adoption to %s",
                provider,
            )
        raise
    except Exception:
        rollback, cancelled_during_restore = await _finish_local_provider_restore(
            router_,
            provider=old_provider,
            backend_type=old_backend_type,
            default_model=old_default_model,
            runtime_model=old_runtime_model,
        )
        if cancelled_during_restore:
            if not rollback["ok"]:
                logger.critical(
                    "local provider rollback incomplete after cancelled adoption to %s",
                    provider,
                )
            raise asyncio.CancelledError from None
        return {"adopted": False, "rollback_complete": rollback["ok"]}

    invalidate_local_model_inventory_cache()
    return {"adopted": True, "rollback_complete": True}


async def _switch_local_model_locked(
    router_, model_id: str, provider: Literal["lm-studio", "ollama"] | None = None
):
    """Resolve and apply a switch while the caller holds `_model_switch_lock`."""
    catalog = await _web()._list_local_models()
    matches = [
        model
        for model in catalog["models"]
        if model.get("id") == model_id
        and model.get("available") is True
        and (provider is None or model.get("provider") == provider)
    ]
    available = sorted(
        {
            model["id"]
            for model in catalog["models"]
            if model.get("available") is True
            and (provider is None or model.get("provider") == provider)
        }
    )
    if not matches:
        if provider is not None:
            return nocache_json(
                {
                    "error": "requested model/provider pair is not available locally",
                    "provider": provider,
                },
                status_code=404,
            )
        return nocache_json(
            {"error": f"model '{model_id}' not available locally", "available": available},
            status_code=404,
        )
    providers = sorted({model.get("provider") for model in matches if model.get("provider")})
    if len(providers) != 1:
        return nocache_json(
            {"error": "model id is ambiguous across local providers", "providers": providers},
            status_code=409,
        )

    target_provider = provider or providers[0]
    current_provider = _local_provider_name(router_)
    if target_provider != current_provider:
        if target_provider not in {"lm-studio", "ollama"}:
            return nocache_json(
                {
                    "error": "local provider could not be adopted",
                    "provider": target_provider,
                },
                status_code=409,
            )
        adoption = await _adopt_local_provider(
            router_, provider=target_provider, model=model_id
        )
        if not adoption["adopted"]:
            if not adoption["rollback_complete"]:
                logger.error(
                    "local provider adoption rollback incomplete for %s",
                    target_provider,
                )
                return nocache_json(
                    {
                        "error": "local provider adoption rollback incomplete",
                        "provider": target_provider,
                    },
                    status_code=500,
                )
            return nocache_json(
                {
                    "error": "local provider could not be adopted",
                    "provider": target_provider,
                },
                status_code=409,
            )
        return nocache_json(
            {"ok": True, "active": model_id, "provider": target_provider}
        )

    router_.set_active_model(model_id)
    try:
        put_category("llm", {"default_model": model_id})
    except Exception:
        # Persistence is best-effort; the live switch already took effect.
        pass

    return nocache_json({"ok": True, "active": model_id, "provider": target_provider})


@router.post("/api/models/local/switch", dependencies=[Depends(admin_guard)])
async def models_local_switch(body: LocalModelSwitch):
    """Set the active local model on the live router and persist the choice.

    The model must be present in one of the local backends. The selection is
    written to `llm.default_model` (settings_db) so it survives a restart, and
    applied immediately to the running HybridRouter. Switches are serialized
    across their authoritative catalog decision and complete live/persisted
    mutation so one request cannot roll back another.
    """
    orch = get_orch()
    if not orch or getattr(orch, "llm_router", None) is None:
        return nocache_json({"error": "not initialized"}, status_code=503)

    async with _model_switch_lock:
        return await _switch_local_model_locked(
            orch.llm_router, body.model, provider=body.provider
        )


# ── LM Studio lifecycle control (start server / load / unload) ───
# Jarvis connects to a running LM Studio and auto-detects the model; these let
# the operator (or Jarvis) actually start the server and load/unload a model via
# the `lms` CLI. Admin-guarded, like the model-switch endpoint above.

class LMLoad(BaseModel):
    model: str = Field(..., min_length=1, max_length=200)


class LMUnload(BaseModel):
    model: str | None = Field(default=None, max_length=200)


def _lmstudio_or_503():
    orch = get_orch()
    if not orch or getattr(orch, "lmstudio", None) is None:
        return None, nocache_json({"error": "not initialized"}, status_code=503)
    return orch.lmstudio, None


def _llm_status_code(result: dict) -> int:
    """Map a controller result status to an HTTP code (disabled/blocked → 403)."""
    return {"ok": 200, "disabled": 403, "blocked": 403, "rejected": 400,
            "ambiguous": 409}.get(result.get("status"), 502)


def _restore_lifecycle_router_pair(
    router_, *, provider: str, runtime_model: str | None
) -> bool:
    """Keep LM Studio lifecycle independent from the configured routing pair."""
    if _local_provider_name(router_) != provider:
        return False
    if getattr(router_, "active_model", None) == runtime_model:
        return True
    try:
        router_.set_active_model(runtime_model)
    except Exception:
        return False
    return (
        _local_provider_name(router_) == provider
        and getattr(router_, "active_model", None) == runtime_model
    )


@router.get("/api/llm/auth-profiles", dependencies=[Depends(admin_guard)])
async def llm_auth_profiles():
    """H12.20 — masked status of the cloud auth-profile pools (rotation/failover)."""
    orch = get_orch()
    router_ = getattr(orch, "llm_router", None) if orch else None
    pools = {}
    for name in ("_anthropic_pool", "_gemini_pool"):
        pool = getattr(router_, name, None) if router_ else None
        if pool is not None:
            pools[pool.provider or name] = pool.status()
    return nocache_json({"pools": pools})


@router.get("/api/llm/status", dependencies=[Depends(admin_guard)])
async def llm_status():
    """Live LM Studio controller state for the admin UI.

    Returns ``{online, enabled, server_url, active_model}`` from
    ``LMStudioController.status()``. Degrades gracefully when the controller is
    not wired yet (orchestrator still booting) so the status card can render an
    honest "unavailable" instead of erroring."""
    ctrl, err = _lmstudio_or_503()
    if err:
        return err
    try:
        return nocache_json(await ctrl.status())
    except Exception:
        # status() never raises by design, but never let host control crash the
        # endpoint — degrade to an offline/unavailable shape the UI can render.
        return nocache_json(
            {"online": False, "enabled": getattr(ctrl, "enabled", False),
             "server_url": getattr(ctrl, "server_url", ""), "active_model": None},
            status_code=200,
        )


@router.post("/api/llm/server/start", dependencies=[Depends(admin_guard)])
async def llm_server_start():
    ctrl, err = _lmstudio_or_503()
    if err:
        return err
    result = await ctrl.start_server(agent="jarvis")
    return nocache_json(result, status_code=_llm_status_code(result))


@router.post("/api/llm/load", dependencies=[Depends(admin_guard)])
async def llm_load(body: LMLoad):
    ctrl, err = _lmstudio_or_503()
    if err:
        return err
    async with _model_switch_lock:
        orch = get_orch()
        live_router = getattr(orch, "llm_router", None) if orch else None
        previous_provider = _local_provider_name(live_router)
        previous_model = getattr(live_router, "active_model", None)
        result = await ctrl.load_model(body.model, agent="jarvis")
        if result.get("status") == "ok":
            coherent = _restore_lifecycle_router_pair(
                live_router,
                provider=previous_provider,
                runtime_model=previous_model,
            )
            invalidate_local_model_inventory_cache()
            if not coherent:
                logger.error("local model load left router state incoherent")
                return nocache_json(
                    {"error": "local model lifecycle router state incoherent"},
                    status_code=500,
                )
            return nocache_json(result)
        return nocache_json(result, status_code=_llm_status_code(result))


@router.post("/api/llm/unload", dependencies=[Depends(admin_guard)])
async def llm_unload(body: LMUnload):
    ctrl, err = _lmstudio_or_503()
    if err:
        return err
    async with _model_switch_lock:
        orch = get_orch()
        live_router = getattr(orch, "llm_router", None) if orch else None
        previous_provider = _local_provider_name(live_router)
        previous_model = getattr(live_router, "active_model", None)
        result = await ctrl.unload_model(body.model, agent="jarvis")
        if result.get("status") == "ok":
            coherent = _restore_lifecycle_router_pair(
                live_router,
                provider=previous_provider,
                runtime_model=previous_model,
            )
            invalidate_local_model_inventory_cache()
            if not coherent:
                logger.error("local model unload left router state incoherent")
                return nocache_json(
                    {"error": "local model lifecycle router state incoherent"},
                    status_code=500,
                )
        return nocache_json(result, status_code=_llm_status_code(result))
