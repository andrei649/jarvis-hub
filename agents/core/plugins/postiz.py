"""
postiz.py — Postiz social-scheduling plugin (self-hosted, draft-first).

Talks to a self-hosted Postiz instance's public API so agents can read the
social queue and connected channels, and queue *drafts* across the 30+
platforms Postiz supports. Requires POSTIZ_URL and POSTIZ_API_KEY; the host is
config-driven, so it is registered with the egress gate dynamically (SEC-5b),
exactly like n8n/SearXNG.

Draft-first by design: ``schedule_post`` submits ``type="draft"`` unless the
caller explicitly passes ``kind="schedule"``. Reads are free; anything that
would *publish* rides the same governed social-draft posture as Safe Comms —
callers that want a live schedule must come through an approval path, never
ambient chat. Plugin calls are additionally gated by PermissionGate +
PLUGIN_CALL_CONTRACT like every plugin.
"""

import logging
import os
from typing import Any

import httpx

from ..http_client import PluginHTTPClient

logger = logging.getLogger("jarvis.plugins.postiz")

_NOT_CONFIGURED = (
    "Postiz not configured — set POSTIZ_URL and POSTIZ_API_KEY environment variables."
)


class PostizPlugin:
    """Async client for the Postiz public API (v1)."""

    def __init__(self, base_url: str = "", api_key: str = "", client=None):
        self.base_url = (base_url or os.getenv("POSTIZ_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("POSTIZ_API_KEY", "")
        # Injectable network client (the host seam) — offline tests pass a fake.
        self._client = client or PluginHTTPClient.for_plugin("postiz")
        # SEC-5b: the Postiz host is config-driven; allow it through the egress gate.
        if self.base_url:
            from ..plugin_gate import register_dynamic_domain
            register_dynamic_domain("postiz", self.base_url)

    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       body: dict | None = None) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": _NOT_CONFIGURED}
        url = f"{self.base_url}/api/public/v1{path}"
        try:
            if method == "GET":
                resp = await self._client.get(url, headers=self._headers(), params=params or {})
            else:
                resp = await self._client.post(url, headers=self._headers(), json=body or {})
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except httpx.ConnectError as e:
            logger.warning("Postiz connection error: %s", e)
            return {"ok": False, "error": f"Postiz unreachable: {e}"}
        except httpx.HTTPStatusError as e:
            logger.warning("Postiz HTTP error: %s", e)
            return {"ok": False, "error": f"Postiz HTTP {e.response.status_code}: {e}"}
        except Exception as e:
            logger.warning("Postiz error: %s", e)
            return {"ok": False, "error": str(e)}

    async def list_integrations(self) -> dict[str, Any]:
        """GET /integrations — the connected social channels."""
        return await self._request("GET", "/integrations")

    async def list_posts(self, params: dict | None = None) -> dict[str, Any]:
        """GET /posts — the scheduled-post queue (optional Postiz query params)."""
        return await self._request("GET", "/posts", params=params)

    async def schedule_post(self, content: str, integration_ids: list[str],
                            publish_at: str, kind: str = "draft") -> dict[str, Any]:
        """POST /posts — queue content for the given channels.

        ``kind="draft"`` (default) creates an unpublished draft the owner
        promotes inside Postiz; only an explicit ``kind="schedule"`` arms a
        live publish, and that path is reserved for governed/approved callers.
        """
        if kind not in ("draft", "schedule"):
            return {"ok": False, "error": f"invalid kind: {kind!r}"}
        if not content or not integration_ids:
            return {"ok": False, "error": "content and integration_ids are required"}
        body = {
            "type": kind,
            "date": publish_at,
            "posts": [
                {"integration": {"id": iid}, "value": [{"content": content}]}
                for iid in integration_ids
            ],
        }
        return await self._request("POST", "/posts", body=body)

    async def queue_text(self) -> str:
        """Compact queue lines for prompt injection; honest when unconfigured."""
        result = await self.list_posts()
        if not result.get("ok"):
            return f"[social queue unavailable: {result.get('error', 'unknown')}]"
        data = result.get("data") or {}
        posts = data.get("posts") if isinstance(data, dict) else data
        if not posts:
            return "[social queue: empty]"
        lines = []
        for p in list(posts)[:10]:
            state = p.get("state") or p.get("type") or "?"
            when = p.get("publishDate") or p.get("date") or ""
            content = ((p.get("content") or "").strip().replace("\n", " "))[:80]
            lines.append(f"{state} @ {when}: {content}")
        return "\n".join(lines)
