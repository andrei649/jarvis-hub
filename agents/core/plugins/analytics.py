"""
analytics.py — first-party local analytics plugin (H22).

Privacy-first, offline analytics in the lineage of Plausible: KPIs are aggregated
**on read** with SQL `GROUP BY` over a local first-party event table
(`core.analytics_store`), not fetched from GA4. We own the data; nothing leaves
the box.

The public interface (`get_kpis()` / `get_summary()` / `get_campaign_performance()`)
is unchanged so the HUD/dashboard wiring is untouched — only the data path moved
from "GA4 mock / GA4 API" to "local SQLite aggregate-on-read".

The old GA4 Data API path is kept behind a disabled-by-default setting
(``ga4_service_account`` + ``ga4_property_id`` AND ``ga4_enabled=True``); when off
(the default) it is never called. ``available()`` reflects whether that legacy
remote path is wired, NOT whether local analytics works — local always works.
"""
import json
import logging
from typing import Optional

from ..http_client import PluginHTTPClient
from .. import analytics_store

logger = logging.getLogger("jarvis.stark.analytics")


class AnalyticsPlugin:
    def __init__(
        self,
        ga4_service_account: str = "",
        ga4_property_id: str = "",
        ga4_enabled: bool = False,
    ):
        self.client = PluginHTTPClient.for_plugin("analytics")
        self._sa = self._parse_service_account(ga4_service_account) if ga4_service_account else None
        self.property_id = ga4_property_id
        # GA4 is an opt-in legacy remote path, OFF by default. Local-first wins.
        self.ga4_enabled = bool(ga4_enabled)
        analytics_store.initialize()

    def _parse_service_account(self, raw: str) -> Optional[dict]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def available(self) -> bool:
        """True only when the (disabled-by-default) GA4 remote path is wired.

        Local analytics is always available — this flag is solely about whether
        the optional GA4 mirror could be queried."""
        return self.ga4_enabled and self._sa is not None and bool(self.property_id)

    async def get_kpis(self, days: int = 30) -> dict:
        """Headline KPIs, aggregated on read from the local event table.

        When the GA4 remote path is explicitly enabled AND configured, it is used
        as the source instead; any failure falls back to local aggregates rather
        than fabricated mock data."""
        if self.available():
            try:
                return await self._fetch_ga4_kpis(days)
            except Exception as e:
                logger.warning(f"GA4 API failed, falling back to local: {e}")
        return analytics_store.kpis(days)

    async def get_summary(self) -> str:
        data = await self.get_kpis()
        lines = [
            f"**Daily Active Users:** {data.get('daily_users', 0):,}",
            f"**Page Views:** {data.get('page_views', 0):,}",
            f"**Sessions:** {data.get('sessions', 0):,}",
            f"**Conversion Rate:** {data.get('conversion_rate', 0)*100:.1f}%",
            f"**Revenue:** ${data.get('revenue', 0):,.2f}",
        ]
        if data.get("total_events", 0) == 0 and not data.get("mock"):
            lines.append("_(no local events yet — POST to /api/analytics/event to populate)_")
        return "\n".join(lines)

    async def get_campaign_performance(self) -> dict:
        """Campaign/ROAS performance.

        Campaigns require ad-network spend data we don't collect locally, so this
        returns an empty, explicitly-not-mock structure unless the GA4 remote path
        is enabled. Shape is unchanged for the dashboard."""
        if self.available():
            try:
                return await self._fetch_ga4_campaigns()
            except Exception as e:
                logger.warning(f"GA4 campaigns failed: {e}")
        return {"campaigns": [], "total_roas": 0.0, "mock": False}

    # ── legacy GA4 remote path (opt-in, disabled by default) ───────────

    async def _fetch_ga4_kpis(self, days: int) -> dict:
        access_token = await self._get_access_token()
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{self.property_id}:runReport"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        payload = {
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
            "metrics": [
                {"name": "activeUsers"},
                {"name": "screenPageViews"},
                {"name": "sessions"},
                {"name": "conversionRate"},
                {"name": "totalRevenue"},
            ],
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("rows", [{}])[0]
        metric_values = {m["name"]: m.get("value", "0") for m in rows.get("metricValues", [])}
        return {
            "daily_users": int(metric_values.get("activeUsers", 0)),
            "page_views": int(metric_values.get("screenPageViews", 0)),
            "sessions": int(metric_values.get("sessions", 0)),
            "conversion_rate": float(metric_values.get("conversionRate", 0)),
            "revenue": float(metric_values.get("totalRevenue", 0)),
            "top_pages": [],
            "mock": False,
        }

    async def _fetch_ga4_campaigns(self) -> dict:
        return {"campaigns": [], "total_roas": 0.0, "mock": False}

    async def _get_access_token(self) -> str:
        if not self._sa:
            return ""
        url = "https://oauth2.googleapis.com/token"
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": self._sa.get("private_key", ""),
        }
        resp = await self.client.post(url, data=payload)
        resp.raise_for_status()
        return resp.json().get("access_token", "")

    async def close(self):
        await self.client.close()
