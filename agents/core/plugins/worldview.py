"""
worldview.py — WorldView 4D OSINT plugin (ticket H19.3.3).

Lets a JARVIS agent (Athena / Stark / Vision) query the WorldView 4D OSINT platform
in a normal session: the as-of-T state of any layer, predicted satellite recon
windows + the due-alert subset, and provenance / chain-of-custody for an entity.

WorldView is local-first and runs alongside JARVIS, so this is a LAN, local-only
integration that calls the WorldView Fastify REST API (``@worldview/backend-api``,
default ``http://localhost:4000``). It mirrors the WorldView MCP server's *read*
tools, so an agent gets the same contract whether it reaches WorldView over MCP or
through this plugin.

Read-only and fail-safe: if the backend is unreachable the methods return a
structured ``{"status": "unavailable", ...}`` instead of raising or fabricating
intel (this is an OSINT surface — no invented data). Mutating operations
(``watch_aoi`` / ``reconstruct_event``) deliberately live only behind the
capability-token-gated MCP server, not here.
"""

import asyncio
import logging
from urllib.parse import quote

from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.worldview")

# The five 4D layers the backend serves (mirrors backend-api/src/types.ts + the MCP server).
LAYERS = ("adsb", "ais", "tle", "ew", "context")
DEFAULT_API_URL = "http://localhost:4000"


class WorldViewPlugin:
    """Read-only client for the WorldView 4D OSINT REST API."""

    def __init__(self, api_url: str = ""):
        # Local-first default; override with WORLDVIEW_API_URL for a remote deployment.
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")
        self.client = PluginHTTPClient.for_plugin("worldview")

    # ── internals ──────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"{self.api_url}/{path.lstrip('/')}"

    @resilient_call(
        max_retries=2,
        # Interactive budget: this plugin sits on the synchronous chat turn, so keep
        # the per-attempt timeout small (5s) — worst case ~15s/call across retries
        # rather than 45s. recon_overview's two sub-calls are issued concurrently
        # (see below), so an unreachable backend degrades fast instead of stalling
        # the turn. NB: this is the *inner* circuit breaker (plugin:worldview); the
        # shared PluginHTTPClient adds an outer one (http_client:worldview). The
        # double breaker is benign (the inner trips first on this plugin's own error
        # streak) and intentionally left in place — removing it would drop the
        # plugin-scoped fail-fast that other plugins also rely on.
        timeout=5.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:worldview",
        circuit_breaker_threshold=3,
        metrics_agent_id="athena",
        metrics_backend="worldview",
    )
    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET a JSON object from the backend (retried + circuit-broken). Raises on failure."""
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        resp = await self.client.get(self._url(path), params=clean)
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _unavailable(detail: str) -> dict:
        return {"status": "unavailable", "error": detail}

    async def _safe_get(self, path: str, params: dict | None = None) -> dict | None:
        """``_get`` wrapped so callers never see an exception; ``None`` signals unavailable."""
        try:
            return await self._get(path, params)
        except Exception as e:  # httpx / OS / circuit-open — degrade, never crash the agent
            # Expected when WorldView isn't running (optional, separate stack on :4000); the
            # caller degrades to {"status": "unavailable"} and never fabricates intel. DEBUG so a
            # down backend doesn't flood the log every autonomy tick.
            logger.debug("WorldView API unavailable (%s): %s", path, e)
            return None

    # ── read tools (mirror the WorldView MCP server) ───────────────
    async def state_at(self, layer: str, t: float, bbox: str = "", lod: str = "") -> dict:
        """As-of-T reconstruction of one layer: ``GET /history/:layer?t=&bbox=&lod=``."""
        if layer not in LAYERS:
            return {"status": "error", "error": f"unknown layer '{layer}'", "layers": list(LAYERS)}
        fc = await self._safe_get(f"/history/{layer}", {"t": t, "bbox": bbox, "lod": lod})
        if fc is None:
            return self._unavailable(f"history/{layer}")
        feats = fc.get("features", []) or []
        return {"status": "ok", "layer": layer, "t": t, "count": len(feats), "features": feats}

    async def recon_windows(
        self, aoi: str = "", from_t: float | None = None, to_t: float | None = None
    ) -> dict:
        """Upcoming satellite recon windows: ``GET /recon/windows?aoi=&from=&to=``."""
        body = await self._safe_get("/recon/windows", {"aoi": aoi, "from": from_t, "to": to_t})
        if body is None:
            return self._unavailable("recon/windows")
        windows = body.get("windows", []) or []
        return {"status": "ok", "count": len(windows), "windows": windows}

    async def recon_alerts(self, lead: float | None = None) -> dict:
        """Recon passes due within a lead time: ``GET /recon/alerts?lead=``."""
        body = await self._safe_get("/recon/alerts", {"lead": lead})
        if body is None:
            return self._unavailable("recon/alerts")
        alerts = body.get("alerts", []) or []
        return {"status": "ok", "count": len(alerts), "alerts": alerts}

    async def provenance(self, layer: str, entity_id: str, t: float | None = None) -> dict:
        """Chain-of-custody of an entity's last-known datum: ``GET /provenance/:layer/:entityId?t=``."""
        if layer not in LAYERS:
            return {"status": "error", "error": f"unknown layer '{layer}'", "layers": list(LAYERS)}
        path = f"/provenance/{layer}/{quote(str(entity_id), safe='')}"
        body = await self._safe_get(path, {"t": t})
        if body is None:
            return self._unavailable(f"provenance/{layer}")
        return {"status": "ok", "provenance": body.get("provenance")}

    async def recon_overview(self, lead: float | None = None) -> dict:
        """Answer-oriented convenience: upcoming recon windows + the alertable subset.

        This is what the orchestrator surfaces for a general geospatial question — the
        flagship "satellite pass over an AOI in N minutes" insight — without the caller
        having to choose a layer or timestamp. Returns ``unavailable`` only if BOTH
        underlying calls fail (a partial answer still surfaces what it could fetch).
        """
        # Fetch the two sub-calls concurrently so the worst-case latency on the chat
        # turn is one call's budget, not two back-to-back (each already retried +
        # circuit-broken inside _safe_get, which never raises).
        windows, alerts = await asyncio.gather(
            self.recon_windows(), self.recon_alerts(lead=lead)
        )
        if windows.get("status") != "ok" and alerts.get("status") != "ok":
            return self._unavailable("recon")
        return {
            "status": "ok",
            "upcoming_windows": windows.get("windows", []),
            "due_alerts": alerts.get("alerts", []),
            "api_url": self.api_url,
        }

    # ── ontology (graph projection — feeds the JARVIS knowledge-graph sync) ──
    async def ontology_objects(self, obj_type: str, limit: int | None = None) -> dict:
        """Ontology objects of one type: ``GET /ontology/objects/:type?limit=``."""
        body = await self._safe_get(
            f"/ontology/objects/{quote(str(obj_type), safe='')}", {"limit": limit}
        )
        if body is None:
            return self._unavailable(f"ontology/objects/{obj_type}")
        return {"status": "ok", "type": obj_type, "objects": body.get("objects", []) or []}

    async def ontology_links(self, obj_type: str, obj_id: str) -> dict:
        """Links incident to one object: ``GET /ontology/objects/:type/:id/links``."""
        path = f"/ontology/objects/{quote(str(obj_type), safe='')}/{quote(str(obj_id), safe='')}/links"
        body = await self._safe_get(path)
        if body is None:
            return self._unavailable(f"ontology/links/{obj_type}")
        return {"status": "ok", "type": obj_type, "id": obj_id, "links": body.get("links", []) or []}

    async def close(self):
        await self.client.close()
