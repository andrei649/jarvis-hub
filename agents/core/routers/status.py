"""Status / health endpoints — extracted from web.py (CLN-3).

Covers the small status surface: component-health (`/api/health/components`), the
HUD-compatible `/status` snapshot, and the lightweight `/api/status` smoke probe.
All three are unguarded, exactly as inline.

`/status` leans on web.py's `_sys_info()`, `_enrich_agents()`, and late-bound
`_list_local_models()` compatibility seam.  The latter delegates to the shared
local-model inventory, keeping `/status` and `/api/models/local` on one truth source.
"""

import sys

from fastapi import APIRouter

from agents.core.app_state import get_orch
from agents.core.llm.local_model_inventory import project_llm_status
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["status"])


def _web():
    # Always present at request time (the app is running). Not an import edge.
    # The helpers stay owned by web.py; resolve them here on each call so tests'
    # monkeypatches and the runtime orchestrator remain observable.
    return sys.modules.get("agents.web")


def _channel_rows(orch):
    manager = getattr(orch, "channel_manager", None)
    channels = getattr(manager, "channels", None) or getattr(orch, "channels", None) or {}
    running = set(getattr(orch, "running_channels", []) or [])
    rows = []
    for channel_id, channel in channels.items():
        is_running = bool(
            channel_id in running
            or getattr(channel, "_running", False)
            or getattr(channel, "running", False)
        )
        rows.append({
            "id": str(channel_id),
            "running": is_running,
            "ready": is_running or channel_id in {"web", "voice"},
        })
    return rows


# ── Status (HUD-compatible) ──────────────────────────────────────

@router.get("/api/health/components")
async def component_health():
    """A8: which optional components initialized (vs failed silently)."""
    orch = get_orch()
    reg = getattr(orch, "components", None) if orch else None
    if reg is None:
        return nocache_json({"components": {}, "summary": "registry unavailable"})
    return nocache_json({"components": reg.health(), "failed": reg.failed(),
                         "summary": reg.summary()})


@router.get("/status")
async def status():
    orch = get_orch()
    if not orch:
        return nocache_json({"status": "starting"})
    web = _web()
    enriched = web._enrich_agents()
    voice_state = "idle"
    inventory = await web._list_local_models()
    ready = project_llm_status(inventory)
    lm_online = any(provider.get("online") for provider in inventory.get("providers", []))
    from agents import __version__
    return nocache_json({
        "version": __version__,
        "sys": web._sys_info(),
        "voice_state": voice_state,
        "lm_online": lm_online,                       # backend configured/reachable
        "model_state": ready["model_state"],
        "model_loaded": ready["model_loaded"],
        "loaded_model": ready["loaded_model"],
        "resident_models": ready["resident_models"],
        "residency_state": ready["residency_state"],
        "configured_model": inventory.get("configured_model"),
        "llm_backend": inventory.get("backend", "none"),
        "active_model": inventory.get("configured_model"),
        "agents": [{"id": a["id"], "status": a["status"]} for a in enriched],
        "agents_online": sum(1 for a in enriched if a["status"] != "idle"),
        "agents_total": len(enriched),
        "channels": _channel_rows(orch),
    })


@router.get("/api/status")
async def api_status():
    """Return service version, agent count, and health status."""
    from agents import AGENT_COUNT, __version__
    return {"version": __version__, "agents": AGENT_COUNT, "status": "ok"}
