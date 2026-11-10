"""
spotify/main.py — Jerome's Spotify control skill (H2.5).

Loader-pattern skill (skills/<name>/SKILL.md + main.py). Wraps the existing
SpotifyPlugin (agents/core/plugins/spotify_plugin.py) so Jerome can control
playback by voice/chat. Degrades gracefully when no token / no device.

Commands (see get_commands):
  play_focus <query>   — search library and start playback of best match
  pause                — pause playback
  skip                 — next track
  now_playing          — what's playing right now
"""

import logging
import os

logger = logging.getLogger("jarvis.skills.spotify")

_plugin = None


def _get_plugin():
    """Lazily build a SpotifyPlugin from env tokens (cached per process)."""
    global _plugin
    if _plugin is not None:
        return _plugin
    try:
        from agents.core.plugins.spotify_plugin import SpotifyPlugin
    except ImportError:
        from core.plugins.spotify_plugin import SpotifyPlugin
    _plugin = SpotifyPlugin(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        access_token=os.environ.get("SPOTIFY_ACCESS_TOKEN", ""),
        refresh_token=os.environ.get("SPOTIFY_REFRESH_TOKEN", ""),
    )
    return _plugin


def get_commands() -> list[str]:
    return ["play_focus", "pause", "skip", "now_playing"]


def _no_token_msg() -> str:
    return "Spotify nu e conectat — adaugă SPOTIFY_ACCESS_TOKEN în .env."


async def play_focus(args: str, context: dict = None) -> str:
    """`play_focus <query>` — search and play the best matching track."""
    query = (args or "").strip() or "focus"
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token_msg()
    try:
        results = await plugin.search(query, limit=1)
    except Exception as e:
        logger.warning(f"Spotify search failed: {e}")
        return "Spotify nu răspunde acum. Încearcă din nou."
    if not results:
        return f"Nu am găsit nimic pentru „{query}”."
    track = results[0]
    uri = track.get("uri", "")
    name = track.get("name", query)
    artist = track.get("artist", "")
    ok = await plugin.play(context_uri=uri) if uri else await plugin.play()
    if not ok:
        return "Nu am putut porni redarea — niciun dispozitiv activ?"
    suffix = f" — {artist}" if artist else ""
    return f"Pun „{name}”{suffix}. 🎧"


async def pause(args: str = "", context: dict = None) -> str:
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token_msg()
    ok = await plugin.pause()
    return "Am pus pauză." if ok else "N-am putut pune pauză."


async def skip(args: str = "", context: dict = None) -> str:
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token_msg()
    ok = await plugin.next_track()
    return "Următoarea piesă. ⏭" if ok else "N-am putut sări piesa."


async def now_playing(args: str = "", context: dict = None) -> str:
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token_msg()
    try:
        state = await plugin.get_playback()
    except Exception as e:
        logger.warning(f"Spotify get_playback failed: {e}")
        return "Spotify nu răspunde acum."
    if not state or not state.get("item"):
        return "Nu se redă nimic acum."
    item = state["item"]
    name = item.get("name", "?")
    artists = item.get("artists", [])
    artist = artists[0]["name"] if artists and isinstance(artists[0], dict) else ""
    suffix = f" — {artist}" if artist else ""
    return f"Acum: „{name}”{suffix}."


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {
        "play_focus": play_focus, "pause": pause,
        "skip": skip, "now_playing": now_playing,
    }
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[spotify] comandă necunoscută: {cmd}"
