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
