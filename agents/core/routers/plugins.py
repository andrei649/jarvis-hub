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
from agents.core.plugins.honesty import degradation_info as _plugin_degradation
from agents.core.plugins.honesty import honesty_for
from agents.core.plugins.honesty import live_plugin_for as _live_plugin_for
from agents.core.plugins.honesty import runtime_configuration as _plugin_runtime_configuration
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["plugins"])

logger = logging.getLogger("jarvis.web")

# _plugin_runtime_configuration / _plugin_degradation / _live_plugin_for moved to
# agents.core.plugins.honesty (as runtime_configuration / degradation_info /
# live_plugin_for) so the capability registry can share the exact same resolution
# logic instead of re-deriving it — re-imported here under their prior names so
# nothing else in this module (or its tests) has to change.


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
        degradation = _plugin_degradation(live_plugin)
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
            # Runtime honesty verdict the HUD badges render: live vs mock/degraded,
            # plus exactly what the owner must configure to make it live.
            "honesty": honesty_for(manifest.id, configured, configuration_source,
                                   degraded=degradation is not None),
            # Honesty layer (Live-vs-Plumbing): True when this plugin's calls
            # would currently return mock data instead of touching the real
            # service — so the HUD can badge it rather than read as live.
            "degraded": degradation is not None,
            "degraded_reason": (degradation or {}).get("reason", ""),
            "degraded_needs": list((degradation or {}).get("needs", [])),
            # CDX-11 — least-privilege posture: whether this plugin's "all" wildcard
            # is currently withheld (external-write under hardening), plus any
            # owner-declared per-agent grants.
            "wildcard_restricted": gate.wildcard_restricted(manifest.id),
            "grants": gate.grants(manifest.id),
        })
    live = sum(1 for p in plugins if p["honesty"]["status"] == "live")
    return nocache_json({
        "plugins": plugins,
        "total": len(plugins),
        "least_privilege": gate.least_privilege,
        # At-a-glance honesty rollup for the HUD: how many plugins are actually
        # live vs still running in a mock/degraded fallback awaiting config.
        "honesty_summary": {"live": live, "needs_config": len(plugins) - live},
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
