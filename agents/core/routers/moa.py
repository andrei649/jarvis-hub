"""Mixture-of-Agents (MoA) committee presets & resilient execution routes (H032)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agents.core.app_state import get_orch
from agents.core.llm.data_handling import DataHandlingRefused
from agents.core.llm.hybrid_router import LocalBackendUnavailableError, ModelNotApprovedError
from agents.core.llm.moa import (
    PRESET_NAME_RE,
    MoAConfigError,
    delete_preset,
    get_active_preset_name,
    list_presets,
    recent_runs,
    save_preset,
    set_active_preset,
    validate_preset,
)
from agents.core.managed_scope import check_llm_write
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["models"])


class MoAPresetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposers: list[str] = Field(..., min_length=2, max_length=6)
    aggregator: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=240)
    min_quorum: int | None = Field(default=None, ge=1, le=6)
    timeout_s: float = Field(default=45.0, ge=2.0, le=180.0)
    temperature: float = Field(default=0.6, ge=0.0, le=1.5)


class MoAActiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=64)


class MoARunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = Field(..., min_length=1, max_length=64)
    prompt: str = Field(..., min_length=1, max_length=32000)
    agent: str = Field(default="jarvis", min_length=1, max_length=64)
    system: str = Field(default="", max_length=8000)
    max_tokens: int = Field(default=1024, ge=1, le=16384)


def _invalidate_router_cache() -> None:
    orch = get_orch()
    llm_router = getattr(orch, "llm_router", None) if orch is not None else None
    cache = getattr(llm_router, "_moa_backend_cache", None)
    if isinstance(cache, dict):
        cache.clear()


@router.get("/api/llm/moa/presets", dependencies=[Depends(admin_guard)])
async def moa_list_presets():
    """List saved MoA committee presets, active preset name, and metadata-only run telemetry."""
    presets, active = await asyncio.to_thread(
        lambda: ([p.to_dict() for p in list_presets()], get_active_preset_name())
    )
    return nocache_json(
        {
            "presets": presets,
            "active": active,
            "recent_runs": recent_runs()[:20],
        }
    )


@router.put("/api/llm/moa/presets/{name}", dependencies=[Depends(admin_guard)])
async def moa_put_preset(name: str, body: MoAPresetBody):
    """Create or update a named MoA committee preset."""
    check_llm_write(selection=False)
    try:
        preset = validate_preset(
            name,
            proposers=body.proposers,
            aggregator=body.aggregator,
            description=body.description,
            min_quorum=body.min_quorum,
            timeout_s=body.timeout_s,
            temperature=body.temperature,
        )
        saved = await asyncio.to_thread(save_preset, preset)
    except MoAConfigError as exc:
        return nocache_json({"error": "invalid_moa_preset", "detail": str(exc)}, status_code=422)
    _invalidate_router_cache()
    return nocache_json({"ok": True, "preset": saved.to_dict()})


@router.delete("/api/llm/moa/presets/{name}", dependencies=[Depends(admin_guard)])
async def moa_delete_preset(name: str):
    """Delete a named MoA committee preset (clears active if it was active)."""
    clean = (name or "").strip()
    if not PRESET_NAME_RE.fullmatch(clean):
        return nocache_json({"error": "invalid_moa_preset", "detail": "invalid preset name"}, status_code=422)
    was_active = await asyncio.to_thread(get_active_preset_name) == clean
    check_llm_write(selection=was_active)
    deleted = await asyncio.to_thread(delete_preset, clean)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"unknown MoA preset '{clean}'")
    _invalidate_router_cache()
    active = await asyncio.to_thread(get_active_preset_name)
    return nocache_json({"ok": True, "deleted": clean, "active": active})


@router.post("/api/llm/moa/active", dependencies=[Depends(admin_guard)])
async def moa_set_active(body: MoAActiveBody):
    """Activate a saved MoA committee preset globally, or clear active preset when name is null/blank."""
    check_llm_write(selection=True)
    try:
        selected = await asyncio.to_thread(set_active_preset, body.name)
    except MoAConfigError as exc:
        return nocache_json({"error": "unknown_moa_preset", "detail": str(exc)}, status_code=404)
    _invalidate_router_cache()
    return nocache_json(
        {
            "ok": True,
            "active": selected.name if selected is not None else None,
            "preset": selected.to_dict() if selected is not None else None,
        }
    )


@router.post("/api/llm/moa/run", dependencies=[Depends(admin_guard)])
async def moa_run_preset(body: MoARunBody):
    """Execute one governed MoA committee synthesis turn and return answer + quorum telemetry."""
    orch = get_orch()
    llm_router = getattr(orch, "llm_router", None) if orch is not None else None
    if llm_router is None or not hasattr(llm_router, "resolve_moa_preset"):
        return nocache_json({"error": "router_unavailable", "detail": "LLM router is not initialized"}, status_code=503)
    try:
        backend, model_id, route = llm_router.resolve_moa_preset(body.agent, body.preset)
        answer = await backend.generate(
            model_id,
            body.prompt,
            system=body.system,
            max_tokens=body.max_tokens,
        )
    except MoAConfigError as exc:
        return nocache_json({"error": "invalid_moa_preset", "detail": str(exc)}, status_code=422)
    except (ModelNotApprovedError, DataHandlingRefused) as exc:
        return nocache_json({"error": "moa_policy_refused", "detail": str(exc)}, status_code=409)
    except LocalBackendUnavailableError as exc:
        return nocache_json({"error": "moa_backend_unavailable", "detail": str(exc)}, status_code=503)
    except RuntimeError as exc:
        return nocache_json({"error": "moa_quorum_failed", "detail": str(exc)}, status_code=502)
    return nocache_json(
        {
            "ok": True,
            "model": model_id,
            "route": route,
            "answer": answer,
            "telemetry": backend.last_run_telemetry,
        }
    )
