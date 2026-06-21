"""Tests for the browser-voice endpoints: /api/voice/stt and /api/voice/capabilities.

Headless-safe: the real Whisper engine is never constructed (it would download a
~2GB model and needs hardware). We assert honest degradation + the wiring, mirroring
the mocked style of test_tts.py."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agents import web
from agents.core.routers import voice as voice_router  # voice routes extracted from web.py (CLN-3)


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
    resp = client.post("/api/voice/stt", content=b"fake-audio-bytes")
    assert resp.status_code == 503
    data = resp.json()
    assert data.get("stt") is False
    assert "faster-whisper" in data["error"]


@patch("core.voice.stt.HAS_WHISPER", True)
def test_stt_transcribes_via_engine(client):
    fake = AsyncMock()
    fake.transcribe_async = AsyncMock(return_value="salut lume")
    # Patch the cached-engine factory so no real model loads.
    with patch.object(voice_router, "_stt_engine", return_value=fake):
        resp = client.post("/api/voice/stt?lang=ro", content=b"fake-audio-bytes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "salut lume"
    assert data["lang"] == "ro"
    fake.transcribe_async.assert_awaited_once()


def test_stt_engine_uses_configured_model_size(monkeypatch):
    # _stt_engine() must build Whisper with the /admin voice.stt_model_size, not a
    # hardcoded "medium".
    captured = {}

    class FakeSTT:
        def __init__(self, model_size="medium", device="auto"):
            captured["model_size"] = model_size

    monkeypatch.setattr("core.voice.stt.STTEngine", FakeSTT)
    monkeypatch.setattr("core.settings_db.get_value",
                        lambda cat, key, default=None: "small" if key == "stt_model_size" else default)
    monkeypatch.setattr(voice_router, "_STT_ENGINE", None)  # bust the cache
    voice_router._stt_engine()
    assert captured["model_size"] == "small"


@patch("core.voice.stt.HAS_WHISPER", True)
def test_stt_lang_falls_back_to_setting(client, monkeypatch):
    # No ?lang= → use voice.stt_language from /admin instead of the old "ro" literal.
    fake = AsyncMock()
    fake.transcribe_async = AsyncMock(return_value="hello world")
    monkeypatch.setattr("core.settings_db.get_value",
                        lambda cat, key, default=None: "en" if key == "stt_language" else default)
    with patch.object(voice_router, "_stt_engine", return_value=fake):
        resp = client.post("/api/voice/stt", content=b"fake-audio-bytes")
    assert resp.status_code == 200
    assert resp.json()["lang"] == "en"
    fake.transcribe_async.assert_awaited_once()


@patch("core.voice.stt.HAS_WHISPER", True)
def test_stt_rejects_empty_audio(client):
    with patch.object(voice_router, "_stt_engine", return_value=AsyncMock()):
        resp = client.post("/api/voice/stt", content=b"")
    assert resp.status_code == 400
