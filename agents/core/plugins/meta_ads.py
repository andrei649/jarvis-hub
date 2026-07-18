"""
meta_ads.py — Meta Ads campaign-insights plugin (read-only).

Reads ad-account insights and campaign status from the Meta Marketing API
(Graph API) so business agents can answer "how are the ads performing?".
Requires META_ADS_ACCESS_TOKEN (a token scoped to `ads_read` is enough and
recommended) and META_ADS_ACCOUNT_ID; degrades gracefully when unconfigured.

Deliberately read-only: budget/status *mutations* are not implemented. If they
ever land, they must go through an ask-tier automation contract + the approval
funnel like every other high-risk write — platform-side spending caps are not
a substitute for governance.
"""

import logging
import os
from typing import Any

import httpx

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.meta_ads")

_GRAPH_URL = "https://graph.facebook.com/v23.0"
_NOT_CONFIGURED = (
    "Meta Ads not configured — set META_ADS_ACCESS_TOKEN and META_ADS_ACCOUNT_ID."
)
_INSIGHT_FIELDS = "spend,impressions,clicks,ctr,cpc,reach"
_CAMPAIGN_FIELDS = "name,status,effective_status,daily_budget"


class MetaAdsPlugin:
    """Read-only client for Meta Marketing API ad-account insights."""

    def __init__(self, access_token: str = "", account_id: str = "", client=None):
        self.access_token = access_token or os.getenv("META_ADS_ACCESS_TOKEN", "")
        account_id = account_id or os.getenv("META_ADS_ACCOUNT_ID", "")
        # The Graph API addresses ad accounts as act_<numeric id>; accept both forms.
        if account_id and not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        self.account_id = account_id
        # Injectable network client (the host seam) — offline tests pass a fake.
        self._client = client or PluginHTTPClient.for_plugin("meta-ads")

    def available(self) -> bool:
        return bool(self.access_token and self.account_id)

    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{_GRAPH_URL}{path}"
        query = dict(params or {})
        query["access_token"] = self.access_token
        try:
            resp = await self._client.get(url, params=query)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("Meta Ads connection error: %s", e)
            return {"ok": False, "error": f"Meta Ads unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("Meta Ads HTTP error: %s", e)
            return {"ok": False, "error": f"Meta Ads HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("Meta Ads error: %s", e)
            return {"ok": False, "error": str(e)}

    async def get_insights(self, date_preset: str = "last_7d") -> dict[str, Any]:
        """GET /act_<id>/insights — account-level performance for a date preset."""
        return await self._get(
            f"/{self.account_id}/insights",
            params={"date_preset": date_preset, "fields": _INSIGHT_FIELDS},
        )

    async def get_campaigns(self, limit: int = 10) -> dict[str, Any]:
        """GET /act_<id>/campaigns — name/status/budget of recent campaigns."""
        return await self._get(
            f"/{self.account_id}/campaigns",
            params={"fields": _CAMPAIGN_FIELDS, "limit": limit},
        )

    async def insights_text(self, date_preset: str = "last_7d") -> str:
        """Compact performance lines for prompt injection; honest when unconfigured."""
        result = await self.get_insights(date_preset)
        if not result.get("ok"):
            return f"[ads unavailable: {result.get('error', 'unknown')}]"
        rows = (result.get("data") or {}).get("data") or []
        if not rows:
            return f"[ads: no insight rows for {date_preset}]"
        lines = []
        for row in rows:
            parts = [f"{k}: {row[k]}" for k in
                     ("spend", "impressions", "clicks", "ctr", "cpc", "reach") if k in row]
            lines.append(f"{date_preset} — " + ", ".join(parts))
        return "\n".join(lines)
