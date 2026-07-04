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


def _plugin_runtime_configuration(plugin) -> tuple[bool, str]:
    """Return whether a live plugin is actually owner-configured.

    The manifest says a plugin exists and is allowed; preview-mode HUD surfaces
    need the next bit of truth: whether the owner supplied keys / a LAN bridge /
    a local data file. Prefer each plugin's own ``available`` / ``_configured``
    contract when it has one; otherwise a constructed plugin is considered
    configured because there is no known extra setup signal.
    """
    if plugin is None:
        return False, "not-loaded"
    for attr_name in ("available", "_configured"):
        if not hasattr(plugin, attr_name):
            continue
        attr = getattr(plugin, attr_name)
        try:
            value = attr() if callable(attr) else attr
        except Exception:
            return False, f"{attr_name}-error"
        return bool(value), f"{attr_name}()"
    return True, "loaded"


def _live_plugin_for(orch, plugin_id: str):
    live_plugins = getattr(orch, "plugins", {}) or {}
    aliases = {
        "whatsapp-bridge": "whatsapp",
    }
    return live_plugins.get(plugin_id) or live_plugins.get(aliases.get(plugin_id, ""))


@router.get("/plugins")
async def list_plugins():
    """Return all registered plugins with status."""
    orch = get_orch()
    if orch is None or orch.permission_gate is None:
        return nocache_json({"plugins": [], "total": 0})
    gate = orch.permission_gate
    plugins = []
    for _pid, manifest in gate.plugins.items():
        live_plugin = _live_plugin_for(orch, manifest.id)
        configured, configuration_source = _plugin_runtime_configuration(live_plugin)
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
            "configured": configured,
            "configuration_source": configuration_source,
            # CDX-11 — least-privilege posture: whether this plugin's "all" wildcard
            # is currently withheld (external-write under hardening), plus any
            # owner-declared per-agent grants.
            "wildcard_restricted": gate.wildcard_restricted(manifest.id),
            "grants": gate.grants(manifest.id),
        })
    return nocache_json({
        "plugins": plugins,
        "total": len(plugins),
        "least_privilege": gate.least_privilege,
    })


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
