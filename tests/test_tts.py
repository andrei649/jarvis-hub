"""Tests for the /tts endpoint."""
import json
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from agents import web
from agents.web import TTSRequest


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_tts_request_model():
    req = TTSRequest(text="Salut, ce mai faci?", lang="ro")
    assert req.text == "Salut, ce mai faci?"
    assert req.lang == "ro"


@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine.speak")
def test_tts_endpoint_success(mock_speak, client):
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
def test_tts_endpoint_no_edge(client):
    resp = client.post("/tts", json={"text": "Salut", "lang": "ro"})
    assert resp.status_code == 503
    data = resp.json()
    assert "error" in data
    assert "edge-tts not installed" in data["error"]


@pytest.mark.asyncio
async def test_tts_engine_cloning_fallbacks():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()

    # HAS_EDGE must be True so speak() reaches _speak_edge after xtts returns None
    with patch.object(tts_module, "HAS_EDGE", True), \
         patch.object(engine, "_speak_edge", return_value="mock_edge_path") as mock_edge, \
         patch.object(engine, "_speak_xtts", return_value=None) as mock_xtts:

        res = await engine.speak("salut", voice="xtts", lang="ro")
        assert res == "mock_edge_path"
        mock_xtts.assert_called_once()
        mock_edge.assert_called_once()


@pytest.mark.asyncio
async def test_tts_engine_elevenlabs_no_key_fallback():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()

    # HAS_EDGE must be True so speak() reaches _speak_edge after elevenlabs returns None
    with patch.dict(os.environ, {}, clear=True), \
         patch.object(tts_module, "HAS_EDGE", True), \
         patch.object(engine, "_speak_edge", return_value="mock_edge_path") as mock_edge:

        res = await engine.speak("hello", voice="elevenlabs", lang="en")
        assert res == "mock_edge_path"
        mock_edge.assert_called_once()


# ── Sentence-level streaming (H5.16) ─────────────────────────────

@pytest.mark.asyncio
async def test_speak_stream_yields_per_sentence():
    """speak_stream splits into sentences and synthesizes each, preserving order."""
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    seen = []

    async def fake_speak(sentence, voice=None, lang=None):
        seen.append(sentence)
        return f"/tmp/{len(seen)}.mp3"

    with patch.object(engine, "speak", side_effect=fake_speak):
        chunks = [c async for c in engine.speak_stream("One. Two? Three!", lang="en")]

    assert [c[1] for c in chunks] == ["One.", "Two?", "Three!"]
    assert [c[0] for c in chunks] == [0, 1, 2]
    assert all(c[2] is not None for c in chunks)
    assert seen == ["One.", "Two?", "Three!"]


@pytest.mark.asyncio
async def test_speak_stream_isolates_chunk_failure():
    """A sentence that fails to synthesize yields path=None; the stream continues."""
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    calls = {"n": 0}

    async def flaky_speak(sentence, voice=None, lang=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return "/tmp/ok.mp3"

    with patch.object(engine, "speak", side_effect=flaky_speak):
        chunks = [c async for c in engine.speak_stream("A. B. C.", lang="en")]

    assert [c[2] for c in chunks] == ["/tmp/ok.mp3", None, "/tmp/ok.mp3"]


def _parse_tts_stream(body: bytes):
    """Parse the /tts/stream wire framing into a list of (header_dict, audio_bytes)."""
    frames = []
    pos = 0
    while pos < len(body):
        nl = body.index(b"\n", pos)
        header = json.loads(body[pos:nl].decode("utf-8"))
        start = nl + 1
        audio = body[start:start + header["bytes"]]
        frames.append((header, audio))
        pos = start + header["bytes"]
    return frames


@patch("core.voice.tts.HAS_EDGE", True)
def test_tts_stream_disabled_by_default(client):
    resp = client.post("/tts/stream", json={"text": "Hi. There.", "lang": "en"})
    assert resp.status_code == 409
    assert resp.json()["enabled"] is False


@patch("agents.web._tts_stream_enabled", return_value=True)
@patch("core.voice.tts.HAS_EDGE", False)
def test_tts_stream_no_edge(_enabled, client):
    resp = client.post("/tts/stream", json={"text": "Hi.", "lang": "en"})
    assert resp.status_code == 503
    assert "edge-tts not installed" in resp.json()["error"]


@patch("agents.web._tts_stream_enabled", return_value=True)
@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine.speak")
def test_tts_stream_frames_per_sentence(mock_speak, _enabled, client):
    # Each synthesized chunk is a tiny real file so the endpoint can read its bytes.
    paths = []

    async def fake_speak(sentence, voice=None, lang=None):
        f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        f.write(b"audio-" + sentence.encode("utf-8"))
        f.close()
        paths.append(f.name)
        return f.name

    mock_speak.side_effect = fake_speak
    try:
        resp = client.post("/tts/stream", json={"text": "One. Two?", "lang": "en"})
        assert resp.status_code == 200
        frames = _parse_tts_stream(resp.content)
        # Two sentence frames + one terminal frame.
        assert len(frames) == 3
        assert frames[0][0]["text"] == "One." and frames[0][1] == b"audio-One."
        assert frames[1][0]["text"] == "Two?" and frames[1][1] == b"audio-Two?"
        assert frames[-1][0]["done"] is True and frames[-1][1] == b""
    finally:
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
