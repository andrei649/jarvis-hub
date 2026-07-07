"""argus.py — governed single interface over WorldView + Signal Layer.

Argus is the agent-facing facade for "world intelligence": it routes to the
Signal Layer (evidence-backed signals/briefs/assessments) and the WorldView 4D
OSINT surface behind one object, and every call passes through the egress
permission gate first. It does not bypass the plugins — it composes them — so the
LAN/LOCAL_ONLY manifests and fail-safe behavior still apply.

Read-only and fail-safe by construction:
- If the calling agent isn't allowed a backend, the method returns
  ``{"status": "forbidden", ...}`` instead of calling it.
- If a backend isn't wired or is unreachable, it returns
  ``{"status": "unavailable", ...}`` (the underlying plugins never fabricate data).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("jarvis.argus")

SIGNAL_LAYER = "signal-layer"
WORLDVIEW = "worldview"


class ArgusInterface:
    """Governed facade over the Signal Layer and WorldView plugins."""

    def __init__(
        self,
        permission_gate,
        signal_layer=None,
        worldview=None,
        worldview_write=None,
        agent_id: str = "argus",
    ):
        self.gate = permission_gate
        self.signal_layer = signal_layer
        self.worldview = worldview
        self.worldview_write = worldview_write
        self.agent_id = agent_id

    @classmethod
    def from_orchestrator(cls, orch, agent_id: str = "argus") -> "ArgusInterface":
        plugins = getattr(orch, "plugins", {}) or {}
        try:
            from agents.core.mcp.worldview_write import WorldViewMCPWriteClient
            worldview_write = WorldViewMCPWriteClient.from_orchestrator(orch, agent_id=agent_id)
        except Exception:
            logger.debug("Argus WorldView MCP write client unavailable", exc_info=True)
            worldview_write = None
        return cls(
            permission_gate=orch.permission_gate,
            signal_layer=plugins.get(SIGNAL_LAYER),
            worldview=plugins.get(WORLDVIEW),
            worldview_write=worldview_write,
            agent_id=agent_id,
        )

    # ── internal helpers ────────────────────────────────────────────────────
    def _allowed(self, plugin_id: str) -> bool:
        try:
            return bool(self.gate.check_call(plugin_id, self.agent_id))
        except Exception as e:  # a gate error must fail closed, never open
            logger.debug("Argus gate check failed for %s/%s: %s", plugin_id, self.agent_id, e)
            return False

    @staticmethod
    def _forbidden(plugin_id: str) -> dict[str, Any]:
        return {"status": "forbidden", "plugin": plugin_id, "reason": "agent not permitted for this backend"}

    @staticmethod
    def _unavailable(plugin_id: str) -> dict[str, Any]:
        return {"status": "unavailable", "plugin": plugin_id, "reason": "backend not wired"}

    async def _call(self, plugin_id: str, plugin, method: str, *args, **kwargs) -> dict[str, Any]:
        if not self._allowed(plugin_id):
            return self._forbidden(plugin_id)
        if plugin is None:
            return self._unavailable(plugin_id)
        fn = getattr(plugin, method, None)
        if fn is None:
            return self._unavailable(plugin_id)
        try:
            return await fn(*args, **kwargs)
        except Exception as e:  # mirror the plugins' fail-safe contract
            logger.debug("Argus %s.%s failed: %s", plugin_id, method, e)
            return {"status": "unavailable", "plugin": plugin_id, "error": str(e)}

    # ── Signal Layer ────────────────────────────────────────────────────────
    async def ask_world(self, question: str, mode: str = "general", country: str = "", limit: int = 12):
        return await self._call(SIGNAL_LAYER, self.signal_layer, "ask_world",
                                question, mode=mode, country=country, limit=limit)

    async def world_brief(self):
        return await self._call(SIGNAL_LAYER, self.signal_layer, "world_brief")

    async def country_risk(self, iso2: str):
        return await self._call(SIGNAL_LAYER, self.signal_layer, "country_assessment", iso2)

    async def signals(self, **kwargs):
        return await self._call(SIGNAL_LAYER, self.signal_layer, "signals", **kwargs)

    # ── WorldView ───────────────────────────────────────────────────────────
    async def worldview_state(self, layer: str, t: float, bbox: str = "", lod: str = ""):
        return await self._call(WORLDVIEW, self.worldview, "state_at", layer, t, bbox=bbox, lod=lod)

    async def recon_overview(self, lead: float | None = None):
        return await self._call(WORLDVIEW, self.worldview, "recon_overview", lead)

    async def _call_worldview_write(self, method: str, *args, **kwargs) -> dict[str, Any]:
        if self.worldview_write is None:
            return self._unavailable("worldview_write")
        fn = getattr(self.worldview_write, method, None)
        if fn is None:
            return self._unavailable("worldview_write")
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.debug("Argus worldview_write.%s failed: %s", method, e)
            return {"status": "unavailable", "plugin": "worldview_write", "error": str(e)}

    async def watch_aoi(
        self,
        aoi_id: str,
        rule: str,
        *,
        lead: float | None = None,
        origin: str = "generated",
    ):
        return await self._call_worldview_write(
            "watch_aoi",
            aoi_id,
            rule,
            lead=lead,
            origin=origin,
        )

    async def reconstruct_event(
        self,
        from_t: float,
        to_t: float,
        *,
        bbox: str = "",
        layers: list[str] | None = None,
        origin: str = "generated",
    ):
        return await self._call_worldview_write(
            "reconstruct_event",
            from_t,
            to_t,
            bbox=bbox,
            layers=layers,
            origin=origin,
        )

    # ── introspection ───────────────────────────────────────────────────────
    def capabilities(self) -> dict[str, Any]:
        """What this agent can reach right now (gate + wiring), for routing/UX."""
        return {
            "agent": self.agent_id,
            "signal_layer": {
                "permitted": self._allowed(SIGNAL_LAYER),
                "wired": self.signal_layer is not None,
                "methods": ["ask_world", "world_brief", "country_risk", "signals"],
            },
            "worldview": {
                "permitted": self._allowed(WORLDVIEW),
                "wired": self.worldview is not None,
                "methods": ["worldview_state", "recon_overview"],
            },
            "worldview_write": {
                "permitted": self._allowed(WORLDVIEW),
                "wired": self.worldview_write is not None,
                "methods": ["watch_aoi", "reconstruct_event"],
            },
        }
