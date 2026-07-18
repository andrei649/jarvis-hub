"""Self-Improvement dashboard: read-only aggregation of subsystems that already
exist (error/bug diagnostics, the resource/service Observer, H32 Capability
Acquisition, H33 Ambient Intelligence, the Proactive Technology Scout) plus one
convenience settings-bundle "enable" endpoint.

This router adds no new capability of its own — every flag it can flip already
exists, is already individually toggleable via ``PUT /api/admin/settings/{cat}``,
and ships default-off for the same governance reasons documented at each
subsystem (Product Posture O26-P2.4, H32/H33 explicit owner opt-in). The bundle
endpoint is a one-action convenience for this instance's owner, not a change to
any shipped default.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.settings_db import put_category, validate_category
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["self-improvement"])

# Every category/key here already exists in settings_db.DEFAULTS and is already
# independently writable via the generic admin settings API — this is a bundle
# of existing opt-ins, not a new one. See docs/OWNER_TASKS.md for what each
# flag actually turns on and what (if anything) still needs owner credentials.
_ENABLE_BUNDLE: dict[str, dict[str, object]] = {
    "cognition": {"enabled": True, "review_enabled": True},
    "acquisition": {"enabled": True},
    "ambient": {"enabled": True},
    "autonomy": {"tech_scout_enabled": True},
}


def _errors_summary() -> dict:
    from agents.core.autonomy.error_logger import summarize_problems
    groups = summarize_problems(hours=48)
    return {"window_hours": 48, "active_groups": len(groups), "top": groups[:5]}


def _observer_summary(orch) -> dict:
    observer = getattr(orch, "observer", None)
    if observer is None:
        return {"enabled": False}
    try:
        return {"enabled": True, **observer.status()}
    except Exception:
        logger.warning("self-improvement: observer status failed", exc_info=True)
        return {"enabled": True, "status": "unavailable"}


def _acquisition_summary(orch) -> dict:
    runtime = getattr(orch, "acquisition", None)
    if runtime is None:
        return {"enabled": False, "status": "unavailable"}
    try:
        snap = runtime.status_snapshot()
    except Exception:
        logger.warning("self-improvement: acquisition status failed", exc_info=True)
        return {"enabled": False, "status": "unavailable"}
    return {
        "enabled": bool(snap.get("enabled")),
        "status": snap.get("status"),
        "states": snap.get("states", {}),
        "reuse": snap.get("reuse", {}),
    }


def _ambient_summary(orch) -> dict:
    try:
        from agents.core.ambient.runtime import get_ambient_runtime
        runtime = get_ambient_runtime(orch)
    except Exception:
        logger.warning("self-improvement: ambient runtime unavailable", exc_info=True)
        return {"enabled": False, "status": "unavailable"}
    monitors = 0
    if runtime.enabled and runtime.registry is not None:
        try:
            monitors = len(list(runtime.registry.list()))
        except Exception:
            monitors = 0
    return {"enabled": bool(runtime.enabled), "status": runtime.status, "monitors": monitors}


def _tech_scout_summary(orch) -> dict:
    enabled = bool(orch.get_setting("autonomy.tech_scout_enabled", False))
    scout = getattr(orch, "tech_scout", None)
    if scout is None:
        return {"enabled": enabled, "available": False}
    try:
        return {"enabled": enabled, "available": True, **scout.status()}
    except Exception:
        logger.warning("self-improvement: tech scout status failed", exc_info=True)
        return {"enabled": enabled, "available": True, "status": "unavailable"}


@router.get("/api/self-improvement/status", dependencies=[Depends(admin_guard)])
async def self_improvement_status():
    orch = get_orch()
    if orch is None:
        return nocache_json({"available": False})
    return nocache_json({
        "available": True,
        "generated_at": time.time(),
        "errors": _errors_summary(),
        "observer": _observer_summary(orch),
        "acquisition": _acquisition_summary(orch),
        "ambient": _ambient_summary(orch),
        "tech_scout": _tech_scout_summary(orch),
    })


async def _audit_settings_change(category: str, keys: list) -> None:
    """Same audit convention as ``admin_put_category`` (AUD-8): record the
    changed KEY NAMES only, never their values."""
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None or not keys:
        return
    try:
        from agents.core.security.types import SecurityEvent, SecurityEventType
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=f"settings.{category} updated: {sorted(keys)} (self-improvement bundle)",
            action_taken="settings_update",
        ))
    except Exception:
        logger.warning("self-improvement: failed to audit settings change for %s", category)


@router.post("/api/self-improvement/enable", dependencies=[Depends(admin_guard)])
async def self_improvement_enable():
    """Flip the documented bundle of already-existing settings (see
    ``_ENABLE_BUNDLE`` above / docs/OWNER_TASKS.md). One explicit owner action,
    same effect as making each PUT call individually via the admin settings API."""
    applied: dict[str, dict[str, bool]] = {}
    for category, values in _ENABLE_BUNDLE.items():
        errors = validate_category(category, values)
        if errors:
            applied[category] = dict.fromkeys(values, False)
            continue
        _updated, skipped = put_category(category, values)
        changed = [k for k in values if k not in skipped]
        await _audit_settings_change(category, changed)
        applied[category] = {k: (k not in skipped) for k in values}
    return nocache_json({"applied": applied})


__all__ = ["router"]
