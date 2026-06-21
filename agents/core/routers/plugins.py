"""Plugin registry endpoints — extracted from web.py (CLN-3).

Covers the `/plugins` surface: list registered plugins with status, and the
admin-guarded per-plugin enable/disable toggle.

The orchestrator (which owns `permission_gate.plugins`) is resolved at request
time via `get_orch()` (late binding to `web.orch`), matching the other extracted
routers. Behavior is unchanged — no singleton lives here.
"""

import logging

from core.log_safe import log_safe
from fastapi import APIRouter, Depends, HTTPException

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["plugins"])

logger = logging.getLogger("jarvis.web")


@router.get("/plugins")
async def list_plugins():
    """Return all registered plugins with status."""
    orch = get_orch()
    if orch is None or orch.permission_gate is None:
        return nocache_json({"plugins": [], "total": 0})
    plugins = []
    for _pid, manifest in orch.permission_gate.plugins.items():
        plugins.append({
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "network_access": manifest.network_access.value,
            "data_scope": manifest.data_scope.value,
            "allowed_domains": manifest.allowed_domains,
            "agents_served": manifest.agents_served,
            "enabled": manifest.enabled,
        })
    return nocache_json({"plugins": plugins, "total": len(plugins)})


@router.put("/plugins/{plugin_id}/toggle", dependencies=[Depends(admin_guard)])
async def toggle_plugin(plugin_id: str):
    """Toggle a plugin's enabled state."""
    orch = get_orch()
    manifest = orch.permission_gate.plugins.get(plugin_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    if manifest.enabled:
        orch.permission_gate.disable(plugin_id)
        action = "disabled"
    else:
        orch.permission_gate.enable(plugin_id)
        action = "enabled"
    logger.info("Plugin %s %s", log_safe(plugin_id), action)
    return nocache_json({"id": plugin_id, "enabled": manifest.enabled, "action": action})
