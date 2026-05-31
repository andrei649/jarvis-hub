"""
analytics.py — Stark GA4 + Firebase Analytics Plugin.
Uses Google Analytics Data API v1 and Firebase Analytics API.
Returns realistic mock KPIs when no Service Account is configured.
"""
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.stark.analytics")

MOCK_KPIS = {
    "daily_users": 1420,
    "page_views": 8900,
    "sessions": 5600,
    "conversion_rate": 0.032,
    "revenue": 45200.00,
    "top_pages": [
        {"page": "/pricing", "views": 2100},
        {"page": "/blog", "views": 1800},
        {"page": "/features", "views": 1500},
    ],
    "mock": True,
}

MOCK_CAMPAIGNS = {
    "campaigns": [
        {"name": "Q2 Launch", "impressions": 45000, "clicks": 2300, "spend": 3200.00, "revenue": 12400.00},
        {"name": "Email June", "impressions": 12000, "clicks": 890, "spend": 500.00, "revenue": 3400.00},
    ],
    "total_roas": 3.8,
    "mock": True,
}


class AnalyticsPlugin:
    def __init__(self, ga4_service_account: str = "", ga4_property_id: str = ""):
        self.client = httpx.AsyncClient(timeout=30.0)
        self._sa = self._parse_service_account(ga4_service_account) if ga4_service_account else None
        self.property_id = ga4_property_id

    def _parse_service_account(self, raw: str) -> Optional[dict]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def available(self) -> bool:
        return self._sa is not None and bool(self.property_id)

    async def get_kpis(self, days: int = 30) -> dict:
        if not self.available():
            return dict(MOCK_KPIS)
        try:
            return await self._fetch_ga4_kpis(days)
        except Exception as e:
            logger.warning(f"GA4 API failed: {e}")
            return dict(MOCK_KPIS)

    async def get_summary(self) -> str:
        data = await self.get_kpis()
        lines = [
            f"**Daily Active Users:** {data.get('daily_users', 0):,}",
            f"**Page Views:** {data.get('page_views', 0):,}",
            f"**Sessions:** {data.get('sessions', 0):,}",
            f"**Conversion Rate:** {data.get('conversion_rate', 0)*100:.1f}%",
            f"**Revenue:** ${data.get('revenue', 0):,.2f}",
        ]
        if data.get("mock"):
            lines.append("_(mock data — configurează GA4 Service Account în Admin → Plugins)_")
        return "\n".join(lines)

    async def get_campaign_performance(self) -> dict:
        if not self.available():
            return dict(MOCK_CAMPAIGNS)
        try:
            return await self._fetch_ga4_campaigns()
        except Exception as e:
            logger.warning(f"GA4 campaigns failed: {e}")
            return dict(MOCK_CAMPAIGNS)

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
        }

    async def _fetch_ga4_campaigns(self) -> dict:
        return dict(MOCK_CAMPAIGNS)

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
        await self.client.aclose()
