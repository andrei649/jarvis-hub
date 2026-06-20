"""
n8n.py — n8n Workflow Designer plugin for Oracle agent.

Integrates with the n8n REST API (v1) to create, list, activate, and monitor
workflows. Requires N8N_BASE_URL and N8N_API_KEY env vars; degrades gracefully
when n8n is not configured or not reachable.

Auth: X-N8N-API-KEY header (n8n >= 1.0 public API).
"""

import logging
import os
from typing import Any

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.n8n")

_NOT_CONFIGURED = (
    "n8n not configured — set N8N_BASE_URL and N8N_API_KEY environment variables."
)


import httpx


class N8NPlugin:
    """Async client for the n8n public REST API v1."""

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = (base_url or os.getenv("N8N_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("N8N_API_KEY", "")
        self._client = PluginHTTPClient.for_plugin("n8n")
        # SEC-5b: n8n's host is config-driven; allow it through the egress gate.
        if self.base_url:
            from ..plugin_gate import register_dynamic_domain
            register_dynamic_domain("n8n", self.base_url)

    # ── helpers ────────────────────────────────────────────────────

    def _configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"X-N8N-API-KEY": self.api_key, "Content-Type": "application/json"}

    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        if not self._configured():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{self.base_url}/api/v1{path}"
        try:
            resp = await self._client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("n8n connection error: %s", e)
            return {"ok": False, "error": f"n8n unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("n8n HTTP error: %s", e)
            return {"ok": False, "error": f"n8n HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("n8n error: %s", e)
            return {"ok": False, "error": str(e)}

    async def _post(self, path: str, body: dict) -> dict[str, Any]:
        if not self._configured():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{self.base_url}/api/v1{path}"
        try:
            resp = await self._client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("n8n connection error: %s", e)
            return {"ok": False, "error": f"n8n unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("n8n HTTP error: %s", e)
            return {"ok": False, "error": f"n8n HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("n8n error: %s", e)
            return {"ok": False, "error": str(e)}

    async def _patch(self, path: str, body: dict) -> dict[str, Any]:
        if not self._configured():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{self.base_url}/api/v1{path}"
        try:
            resp = await self._client.patch(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("n8n connection error: %s", e)
            return {"ok": False, "error": f"n8n unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("n8n HTTP error: %s", e)
            return {"ok": False, "error": f"n8n HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("n8n error: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Public API ─────────────────────────────────────────────────

    async def list_workflows(self) -> dict[str, Any]:
        """GET /api/v1/workflows — return all workflows."""
        return await self._get("/workflows")

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        """GET /api/v1/workflows/{id} — return a single workflow."""
        return await self._get(f"/workflows/{workflow_id}")

    async def get_executions(self, workflow_id: str, limit: int = 20) -> dict[str, Any]:
        """GET /api/v1/executions — return executions filtered by workflow."""
        return await self._get("/executions", params={"workflowId": workflow_id, "limit": limit})

    async def create_workflow(
        self,
        name: str,
        nodes: list[dict],
        connections: dict,
        settings: dict | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/workflows — create a new workflow."""
        body: dict[str, Any] = {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": settings or {},
        }
        return await self._post("/workflows", body)

    async def activate_workflow(self, workflow_id: str) -> dict[str, Any]:
        """PATCH /api/v1/workflows/{id} — set active=true."""
        return await self._patch(f"/workflows/{workflow_id}", {"active": True})

    async def deactivate_workflow(self, workflow_id: str) -> dict[str, Any]:
        """PATCH /api/v1/workflows/{id} — set active=false."""
        return await self._patch(f"/workflows/{workflow_id}", {"active": False})

    # ── Convenience builders ───────────────────────────────────────

    def build_daily_weather_workflow(self, city: str = "Bucharest") -> dict[str, Any]:
        """
        Build a minimal n8n workflow JSON:
          Schedule (daily 07:00 via cron) → HTTP Request (wttr.in weather for city).

        Returns the raw workflow dict (nodes + connections), ready to pass
        to create_workflow().
        """
        schedule_node: dict[str, Any] = {
            "id": "node-schedule",
            "name": "Daily Schedule",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1,
            "position": [250, 300],
            "parameters": {
                "rule": {
                    "interval": [{"field": "hours", "hoursInterval": 24}]
                },
                "cronExpression": "0 7 * * *",
            },
        }

        http_node: dict[str, Any] = {
            "id": "node-http",
            "name": "Fetch Weather",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 3,
            "position": [450, 300],
            "parameters": {
                "url": f"https://wttr.in/{city}?format=3",
                "method": "GET",
                "options": {},
            },
        }

        connections: dict[str, Any] = {
            "Daily Schedule": {
                "main": [[{"node": "Fetch Weather", "type": "main", "index": 0}]]
            }
        }

        return {
            "name": f"Daily Weather — {city}",
            "nodes": [schedule_node, http_node],
            "connections": connections,
            "settings": {"executionOrder": "v1"},
        }

    async def create_daily_weather_workflow(self, city: str = "Bucharest") -> dict[str, Any]:
        """
        Convenience method: build + POST a daily weather workflow for city.

        Satisfies AC: "Oracle, creează workflow vreme zilnic".
        Returns the n8n API response dict with {ok, data} or {ok, error}.
        """
        wf = self.build_daily_weather_workflow(city)
        result = await self.create_workflow(
            name=wf["name"],
            nodes=wf["nodes"],
            connections=wf["connections"],
            settings=wf.get("settings"),
        )
        if result.get("ok"):
            wf_id = result["data"].get("id", "")
            logger.info("Created daily weather workflow id=%s city=%s", wf_id, city)
        else:
            logger.warning("Failed to create weather workflow: %s", result.get("error"))
        return result
