"""
spotify_plugin.py — Spotify control plugin with OAuth refresh.

Playback control and playlist management for Jerome.
Uses the Spotify Web API with OAuth token.
"""

import logging
from typing import Optional

from ..http_client import PluginHTTPClient
from .oauth import refresh_spotify_token, load_token
from ..resilience import resilient_call

logger = logging.getLogger("jarvis.plugins.spotify")


class SpotifyPlugin:
    def __init__(self, access_token: str = "", refresh_token: str = "",
                 client_id: str = "", client_secret: str = ""):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_base = "https://api.spotify.com/v1"
        self.client = PluginHTTPClient.for_plugin("spotify")

    @property
    def configured(self) -> bool:
        """Whether playback calls have a usable token or refresh path."""
        return bool(
            self.access_token
            or (self.refresh_token and self.client_id and self.client_secret)
        )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _ensure_token(self):
        if self.access_token:
            return
        token_data = load_token("spotify")
        if token_data and token_data.get("access_token"):
            self.access_token = token_data["access_token"]
            self.refresh_token = token_data.get("refresh_token", self.refresh_token)
            logger.info("Spotify: token restored from persistent store")

    @resilient_call(
        max_retries=2,
        timeout=15.0,
        backoff_base=1.0,
        backoff_max=3.0,
        circuit_breaker_key="plugin:spotify",
        circuit_breaker_threshold=3,
        metrics_agent_id="spotify",
        metrics_backend="spotify-api",
    )
    async def _request(self, method: str, path: str, **kwargs):
        await self._ensure_token()
        url = f"{self.api_base}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        for attempt in range(2):
            resp = await self.client.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 401 and attempt == 0:
                new_token = await refresh_spotify_token()
                if new_token:
                    self.access_token = new_token
                    headers.update(self._headers())
                    continue
            resp.raise_for_status()
            return resp
        return resp

    async def get_playback(self) -> Optional[dict]:
        try:
            resp = await self._request("GET", "/me/player")
            if resp.status_code == 204:
                return {"is_playing": False, "device": None}
            data = resp.json()
            item = data.get("item", {})
            return {
                "is_playing": data.get("is_playing", False),
                "device": data.get("device", {}).get("name", "unknown"),
                "track": item.get("name", ""),
                "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                "progress_ms": data.get("progress_ms", 0),
                "duration_ms": item.get("duration_ms", 0),
            }
        except Exception as e:
            logger.warning(f"Spotify playback error: {e}")
            return None

    async def play(self, device_id: str = "", context_uri: str = "") -> bool:
        try:
            params = {}
            if device_id:
                params["device_id"] = device_id
            body = {}
            if context_uri:
                body["context_uri"] = context_uri
            await self._request("PUT", "/me/player/play", params=params, json=body)
            return True
        except Exception as e:
            logger.error(f"Spotify play error: {e}")
            return False

    async def pause(self) -> bool:
        try:
            await self._request("PUT", "/me/player/pause")
            return True
        except Exception as e:
            logger.error(f"Spotify pause error: {e}")
            return False

    async def next_track(self) -> bool:
        try:
            await self._request("POST", "/me/player/next")
            return True
        except Exception as e:
            logger.error(f"Spotify next error: {e}")
            return False

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        try:
            resp = await self._request(
                "GET", "/search",
                params={"q": query, "type": "track,playlist", "limit": limit},
            )
            data = resp.json()
            tracks = data.get("tracks", {}).get("items", [])
            return [
                {
                    "name": t["name"],
                    "artist": ", ".join(a["name"] for a in t["artists"]),
                    "uri": t["uri"],
                    "duration_ms": t.get("duration_ms", 0),
                }
                for t in tracks
            ]
        except Exception as e:
            logger.warning(f"Spotify search error: {e}")
            return []

    async def get_devices(self) -> list[dict]:
        try:
            resp = await self._request("GET", "/me/player/devices")
            return resp.json().get("devices", [])
        except Exception as e:
            logger.warning(f"Spotify devices error: {e}")
            return []

    async def close(self):
        await self.client.close()
