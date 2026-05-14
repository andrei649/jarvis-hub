"""
Spotify Control Plugin — Spotify playback control via Web API.
Requires: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET in .env
Permission scope: read-write (playback control)
"""

import logging
import os
from typing import Optional

from core.permission_gate import PermissionGate

logger = logging.getLogger("plugins.spotify")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
]


class SpotifyControl:
    def __init__(self, permission_gate: PermissionGate):
        self._sp = None
        self.permission_gate = permission_gate

    async def start(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> bool:
        if not SPOTIPY_AVAILABLE:
            logger.error("spotipy not installed")
            return False
        cid = client_id or os.getenv("SPOTIFY_CLIENT_ID", "")
        cs = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET", "")
        if not cid or not cs:
            logger.error("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set")
            return False
        try:
            from requests import Session
            session = Session()
            self._sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=cid,
                    client_secret=cs,
                    redirect_uri="http://localhost:8888/callback",
                    scope=" ".join(SCOPES),
                    cache_path="data/spotify_cache",
                )
            )
            user = self._sp.current_user()
            logger.info(f"Spotify control started (user: {user.get('display_name', '?')})")
            return True
        except Exception as e:
            logger.error(f"Spotify auth failed: {e}")
            return False

    async def current_playback(self) -> Optional[dict]:
        if not self._sp:
            return None
        try:
            return self._sp.current_playback()
        except Exception as e:
            logger.error(f"Spotify playback error: {e}")
            return None

    async def play(self, uri: Optional[str] = None) -> bool:
        if not self._sp:
            return False
        try:
            if uri:
                self._sp.start_playback(context_uri=uri)
            else:
                self._sp.start_playback()
            return True
        except Exception as e:
            logger.error(f"Spotify play error: {e}")
            return False

    async def pause(self) -> bool:
        if not self._sp:
            return False
        try:
            self._sp.pause_playback()
            return True
        except Exception as e:
            logger.error(f"Spotify pause error: {e}")
            return False

    async def next_track(self) -> bool:
        if not self._sp:
            return False
        try:
            self._sp.next_track()
            return True
        except Exception as e:
            logger.error(f"Spotify next error: {e}")
            return False

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        if not self._sp:
            return []
        try:
            results = self._sp.search(q=query, limit=limit, type="track")
            tracks = results.get("tracks", {}).get("items", [])
            return [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "artist": ", ".join(a["name"] for a in t["artists"]),
                    "album": t["album"]["name"],
                    "uri": t["uri"],
                }
                for t in tracks
            ]
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return []

    async def stop(self):
        self._sp = None


def create(permission_gate: PermissionGate) -> SpotifyControl:
    return SpotifyControl(permission_gate)
