"""Tests for the loader-pattern Spotify skill (H2.5, Claude).

Distinct from opencode's tests/test_spotify.py (HTTP-router pattern) — this
covers skills/spotify/main.py which the real SkillLoader discovers.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "spotify" / "main.py"
    spec = importlib.util.spec_from_file_location("spotify_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakePlugin:
    """Stand-in for SpotifyPlugin with a token and canned responses."""
    access_token = "fake-token"

    def __init__(self):
        self.paused = False
        self.skipped = False

    async def search(self, query, limit=5):
        return [{"uri": "spotify:track:1", "name": "Weightless", "artist": "Marconi Union"}]

    async def play(self, context_uri="", device_id=""):
        return True

    async def pause(self):
        self.paused = True
        return True

    async def next_track(self):
        self.skipped = True
        return True

    async def get_playback(self):
        return {"item": {"name": "Weightless", "artists": [{"name": "Marconi Union"}]}}


@pytest.fixture
def skill(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_plugin", _FakePlugin())
    return mod


async def test_play_focus_plays_match(skill):
    out = await skill.play_focus("ambient")
    assert "Weightless" in out and "Marconi Union" in out


async def test_pause(skill):
    assert "pauz" in (await skill.pause()).lower()


async def test_skip(skill):
    assert "piesă" in await skill.skip()


async def test_now_playing(skill):
    out = await skill.now_playing("")
    assert "Weightless" in out


async def test_handle_dispatch(skill):
    assert "Weightless" in await skill.handle("play_focus", "x")
    assert "necunoscută" in await skill.handle("bogus", "")


async def test_no_token_graceful(monkeypatch):
    """Without a token the skill returns a clear message, never crashes."""
    mod = _load()

    class _NoToken:
        access_token = ""
    monkeypatch.setattr(mod, "_plugin", _NoToken())
    msg = await mod.play_focus("x")
    assert "nu e conectat" in msg.lower()


def test_manifest_parses_via_loader():
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "spotify" / "SKILL.md")
    assert manifest["name"] == "Spotify"
    assert "jerome" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"play_focus", "pause", "skip", "now_playing"} <= cmds
