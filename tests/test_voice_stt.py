"""Tests for the browser-voice endpoints: /api/voice/stt and /api/voice/capabilities.

Headless-safe: the real Whisper engine is never constructed (it would download a
~2GB model and needs hardware). We assert honest degradation + the wiring, mirroring
the mocked style of test_tts.py."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agents import web


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_capabilities_shape(client):
    resp = client.get("/api/voice/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    # Honest booleans the HUD relies on — present regardless of what's installed.
    for key in ("stt", "tts", "tts_local", "providers"):
        assert key in data
    assert isinstance(data["stt"], bool)
    assert "stt" in data["providers"]


@patch("core.voice.stt.HAS_WHISPER", False)
def test_stt_unavailable_is_honest(client):
    # No fabricated transcript when Whisper isn't installed — a 503 with an install hint.
    resp = client.post(
        "/api/voice/stt",
        files={"audio": ("rec.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert resp.status_code == 503
    data = resp.json()
    assert data.get("stt") is False
    assert "faster-whisper" in data["error"]


@patch("core.voice.stt.HAS_WHISPER", True)
def test_stt_transcribes_via_engine(client):
    fake = AsyncMock()
    fake.transcribe_async = AsyncMock(return_value="salut lume")
    # Patch the cached-engine factory so no real model loads.
    with patch.object(web, "_stt_engine", return_value=fake):
        resp = client.post(
            "/api/voice/stt?lang=ro",
            files={"audio": ("rec.webm", b"fake-audio-bytes", "audio/webm")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "salut lume"
    assert data["lang"] == "ro"
    fake.transcribe_async.assert_awaited_once()


@patch("core.voice.stt.HAS_WHISPER", True)
def test_stt_rejects_empty_audio(client):
    with patch.object(web, "_stt_engine", return_value=AsyncMock()):
        resp = client.post(
            "/api/voice/stt",
            files={"audio": ("rec.webm", b"", "audio/webm")},
        )
    assert resp.status_code == 400
