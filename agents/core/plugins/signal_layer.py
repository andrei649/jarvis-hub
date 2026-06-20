"""
signal_layer.py — Jarvis Signal Layer plugin.

This is the agent-facing bridge to the provider-neutral situational-awareness
service. It complements the existing WorldView 4D OSINT plugin:

- WorldViewPlugin: geospatial/4D layer queries from the local WorldView stack.
- SignalLayerPlugin: evidence-backed signals, briefs, assessments, and relevance
  from the Jarvis Signal Layer, with WorldMonitor as provider #1.

Read-only and fail-safe: if the Signal Layer is unreachable the methods return a
structured ``{"status": "unavailable", ...}`` instead of raising or inventing
world intel.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..http_client import PluginHTTPClient
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.signal_layer")

DEFAULT_SIGNAL_LAYER_URL = "http://localhost:8787"


class SignalLayerPlugin:
    """Read-only client for the local Jarvis Signal Layer HTTP API."""

    def __init__(self, api_url: str = "", api_token: str = ""):
        self.api_url = (api_url or os.environ.get("SIGNAL_LAYER_API_URL", DEFAULT_SIGNAL_LAYER_URL)).rstrip("/")
        self.api_token = (api_token or os.environ.get("SIGNAL_LAYER_API_TOKEN", "")).strip()
        self.client = PluginHTTPClient.for_plugin("signal-layer")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}

    def _url(self, path: str) -> str:
        return f"{self.api_url}/{path.lstrip('/')}"

    @staticmethod
    def _unavailable(detail: str) -> dict[str, Any]:
        return {"status": "unavailable", "error": detail, "provider": "signal-layer"}

    @resilient_call(
        max_retries=2,
        timeout=5.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:signal-layer",
        circuit_breaker_threshold=3,
        metrics_agent_id="argus",
        metrics_backend="signal-layer",
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        resp = await self.client.get(self._url(path), params=clean, headers=self._auth_headers())
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}

    @resilient_call(
        max_retries=2,
        timeout=5.0,
        backoff_base=0.5,
        backoff_max=2.0,
        circuit_breaker_key="plugin:signal-layer",
        circuit_breaker_threshold=3,
        metrics_agent_id="argus",
        metrics_backend="signal-layer",
    )
    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self.client.post(self._url(path), json=payload or {}, headers=self._auth_headers())
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}

    async def _safe_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return await self._get(path, params)
        except Exception as e:
            logger.debug("Signal Layer unavailable (%s): %s", path, e)
            return self._unavailable(path)

    async def _safe_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return await self._post(path, payload)
        except Exception as e:
            logger.debug("Signal Layer unavailable (%s): %s", path, e)
            return self._unavailable(path)

    async def health(self) -> dict[str, Any]:
        """Signal Layer service health: ``GET /healthz``."""
        body = await self._safe_get("/healthz")
        if body.get("status") == "unavailable":
            return body
        return {"status": "ok", "api_url": self.api_url, **body}

    async def provider_health(self) -> dict[str, Any]:
        """World provider health/freshness: ``GET /provider-health/worldmonitor``."""
        body = await self._safe_get("/provider-health/worldmonitor")
        if body.get("status") == "unavailable":
            return body
        return {"status": "ok", "provider_health": body}

    async def signals(
        self,
        limit: int | None = 20,
        relevant_only: bool = True,
        signal_type: str = "",
        country: str = "",
        min_severity: str = "",
    ) -> dict[str, Any]:
        """Normalized signals: ``GET /signals``."""
        body = await self._safe_get(
            "/signals",
            {
                "limit": limit,
                "relevantOnly": "true" if relevant_only else "false",
                "type": signal_type,
                "country": country,
                "minSeverity": min_severity,
            },
        )
        if body.get("status") == "unavailable":
            return body
        return {
            "status": "ok",
            "count": body.get("count", len(body.get("signals", []) or [])),
            "signals": body.get("signals", []) or [],
            "evidence": body.get("evidence", []) or [],
            "freshness": body.get("freshness", {}),
            "provider": body.get("provider", "signal-layer"),
        }

    async def world_brief(self) -> dict[str, Any]:
        """Global Jarvis brief: ``GET /briefs/world``."""
        body = await self._safe_get("/briefs/world")
        if body.get("status") == "unavailable":
            return body
        return {"status": "ok", "brief": body}

    async def country_assessment(self, iso2: str) -> dict[str, Any]:
        """Country assessment: ``GET /assessments/country/:iso2``."""
        code = str(iso2 or "").strip().upper()
        if len(code) != 2:
            return {"status": "error", "error": "country code must be ISO-2"}
        body = await self._safe_get(f"/assessments/country/{code}")
        if body.get("status") == "unavailable":
            return body
        return {"status": "ok", "assessment": body}

    async def ask_world(
        self,
        question: str,
        mode: str = "general",
        country: str = "",
        limit: int | None = 12,
    ) -> dict[str, Any]:
        """World Analyst answer: ``POST /ask/world``."""
        body = await self._safe_post(
            "/ask/world",
            {
                "question": question,
                "mode": mode,
                "country": country or None,
                "limit": limit,
            },
        )
        if body.get("status") == "unavailable":
            return body
        return {"status": "ok", **body}

    async def close(self):
        await self.client.close()
