"""Tests for the Spotify skill (H2.5) — Jerome music playback control."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture
def skill():
    path = repo_root / "agents" / "core" / "skills" / "spotify.py"
    if not path.exists():
        pytest.skip("agents/core/skills/spotify.py not yet implemented")
    spec = importlib.util.spec_from_file_location("spotify_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mock_spotify():
    """Patch httpx.AsyncClient globally so the skill module talks to our mock."""
    with patch("httpx.AsyncClient") as mc:
        client = AsyncMock()
        mc.return_value.__aenter__.return_value = client
        yield client


async def test_play(skill, mock_spotify):
    mock_spotify.put.return_value = AsyncMock(status_code=204)
    result = await skill.play(["spotify:track:4pt5GZ6gNUXH7"])
    assert "Playback started" in result


async def test_play_no_device(skill, mock_spotify):
    mock_spotify.put.return_value = AsyncMock(status_code=404)
    result = await skill.play([])
    assert "No active device" in result


async def test_pause(skill, mock_spotify):
    mock_spotify.put.return_value = AsyncMock(status_code=204)
    result = await skill.pause()
    assert "Paused" in result


async def test_skip(skill, mock_spotify):
    mock_spotify.post.return_value = AsyncMock(status_code=204)
    result = await skill.skip()
    assert "Skipped" in result


async def test_queue(skill, mock_spotify):
    mock_spotify.post.return_value = AsyncMock(status_code=204)
    result = await skill.queue("spotify:track:4pt5GZ6gNUXH7")
    assert "queued" in result.lower()


async def test_now_playing(skill, mock_spotify):
    mock_spotify.get.return_value = AsyncMock(
        status_code=200,
        json=lambda: {
            "is_playing": True,
            "item": {"name": "Test Track", "artists": [{"name": "Test Artist"}], "duration_ms": 180000},
            "progress_ms": 30000,
        },
    )
    result = await skill.now_playing()
    assert result.get("is_playing") is True
    assert result.get("track_name") == "Test Track"


async def test_now_playing_empty(skill, mock_spotify):
    mock_spotify.get.return_value = AsyncMock(status_code=204)
    result = await skill.now_playing()
    assert result is None


async def test_upstream_failure(skill, mock_spotify):
    mock_spotify.get.side_effect = Exception("Spotify unreachable")
    result = await skill.now_playing()
    assert "error" in result or "unavailable" in str(result).lower()
