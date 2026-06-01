"""Tests for the /tts endpoint."""
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agents import web
from agents.web import TTSRequest

client = TestClient(web.app)


def test_tts_request_model():
    req = TTSRequest(text="Salut, ce mai faci?", lang="ro")
    assert req.text == "Salut, ce mai faci?"
    assert req.lang == "ro"


@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine.speak")
def test_tts_endpoint_success(mock_speak):
    # We use a real temporary file so FileResponse works perfectly without mocking stats or file system
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"dummy audio data")
        tmp_path = tmp.name

    try:
        mock_speak.return_value = tmp_path

        resp = client.post("/tts", json={"text": "Salut", "lang": "ro"})
        assert resp.status_code == 200
        assert resp.content == b"dummy audio data"
        assert resp.headers["content-type"] == "audio/mpeg"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@patch("core.voice.tts.HAS_EDGE", False)
def test_tts_endpoint_no_edge():
    resp = client.post("/tts", json={"text": "Salut", "lang": "ro"})
    assert resp.status_code == 503
    data = resp.json()
    assert "error" in data
    assert "edge-tts not installed" in data["error"]


@pytest.mark.asyncio
async def test_tts_engine_cloning_fallbacks():
    from agents.core.voice.tts import TTSEngine

    # Initialize TTS Engine offline (HAS_EDGE is patched or we can test fallback directly)
    engine = TTSEngine()

    # Verify XTTS fallback: should return None or fall back to standard if server is down
    # But since it falls back to edge_tts, and we mock _speak_edge to succeed:
    with patch.object(engine, "_speak_edge", return_value="mock_edge_path") as mock_edge, \
         patch.object(engine, "_speak_xtts", return_value=None) as mock_xtts:
        
        res = await engine.speak("salut", voice="xtts", lang="ro")
        assert res == "mock_edge_path"
        mock_xtts.assert_called_once()
        mock_edge.assert_called_once()


@pytest.mark.asyncio
async def test_tts_engine_elevenlabs_no_key_fallback():
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()

    with patch.dict(os.environ, {}, clear=True), \
         patch.object(engine, "_speak_edge", return_value="mock_edge_path") as mock_edge:
        
        res = await engine.speak("hello", voice="elevenlabs", lang="en")
        assert res == "mock_edge_path"
        mock_edge.assert_called_once()
