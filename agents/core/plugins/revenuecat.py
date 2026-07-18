"""
revenuecat.py — RevenueCat subscription-revenue plugin (read-only).

Surfaces the RevenueCat REST API v2 project overview metrics (active
subscriptions, MRR, revenue, active trials, …) so business agents can answer
"how is revenue doing?" from real data. Requires REVENUECAT_API_KEY (a v2
secret key with *read-only* scope is enough and recommended) and
REVENUECAT_PROJECT_ID; degrades gracefully when unconfigured.

Deliberately read-only: this plugin never mutates products, offerings, or
customers — it is an eyes-only revenue feed.
"""

import logging
import os
from typing import Any

import httpx

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.revenuecat")

_API_URL = "https://api.revenuecat.com/v2"
_NOT_CONFIGURED = (
    "RevenueCat not configured — set REVENUECAT_API_KEY and REVENUECAT_PROJECT_ID."
)


class RevenueCatPlugin:
    """Read-only client for the RevenueCat REST API v2 overview metrics."""

    def __init__(self, api_key: str = "", project_id: str = "", client=None):
        self.api_key = api_key or os.getenv("REVENUECAT_API_KEY", "")
        self.project_id = project_id or os.getenv("REVENUECAT_PROJECT_ID", "")
        # Injectable network client (the host seam) — offline tests pass a fake.
        self._client = client or PluginHTTPClient.for_plugin("revenuecat")

    def available(self) -> bool:
        return bool(self.api_key and self.project_id)

    async def _get(self, path: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{_API_URL}{path}"
        try:
            resp = await self._client.get(
                url, headers={"Authorization": f"Bearer {self.api_key}"}
            )
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("RevenueCat connection error: %s", e)
            return {"ok": False, "error": f"RevenueCat unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("RevenueCat HTTP error: %s", e)
            return {"ok": False, "error": f"RevenueCat HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("RevenueCat error: %s", e)
            return {"ok": False, "error": str(e)}

    async def get_overview(self) -> dict[str, Any]:
        """GET /projects/{id}/metrics/overview — the headline revenue metrics."""
        return await self._get(f"/projects/{self.project_id}/metrics/overview")

    async def overview_text(self) -> str:
        """Compact metric lines for prompt injection; honest when unconfigured."""
        result = await self.get_overview()
        if not result.get("ok"):
            return f"[revenue unavailable: {result.get('error', 'unknown')}]"
        metrics = (result.get("data") or {}).get("metrics") or []
        if not metrics:
            return "[revenue: no metrics returned]"
        lines = []
        for m in metrics:
            name = m.get("name") or m.get("id") or "metric"
            value = m.get("value")
            unit = m.get("unit") or ""
            unit = f" {unit}" if unit and unit != "#" else ""
            lines.append(f"{name}: {value}{unit}")
        return "\n".join(lines)
