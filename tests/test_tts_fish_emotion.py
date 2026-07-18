"""Fish Audio TTS backend + inline [emotion] tag handling (guide-gap wave).

All HTTP is mocked — no real Fish Audio account or network required.

Covers:
- strip_emotion_tags: known tags removed, unknown bracketed text untouched;
- speak() strips emotion tags for non-Fish backends (they would read them aloud);
- speak() passes raw tagged text through to the Fish path;
- _speak_fish: not-configured honesty, reference-id resolution (env + voice
  override), success path writes the audio file;
- Fish counts as a persona/cloned voice → owner consent gate applies.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.voice import tts as tts_mod
from core.voice.tts import TTSEngine, is_persona_or_cloned_voice, strip_emotion_tags

# ---------------------------------------------------------------------------
# strip_emotion_tags
# ---------------------------------------------------------------------------

def test_strip_known_emotion_tags():
    assert strip_emotion_tags("[calm] Good morning, sir.") == "Good morning, sir."
    assert strip_emotion_tags("[Amused] Indeed. [CALM] As you wish.") == "Indeed. As you wish."


def test_strip_leaves_unknown_bracketed_text():
    assert strip_emotion_tags("[2026] revenue is up [citation]") == "[2026] revenue is up [citation]"


def test_strip_no_brackets_fast_path_and_non_str():
    assert strip_emotion_tags("plain text") == "plain text"
    assert strip_emotion_tags(None) is None


# ---------------------------------------------------------------------------
# Persona/consent classification
# ---------------------------------------------------------------------------

def test_fish_is_persona_voice():
    assert is_persona_or_cloned_voice("fish")
    assert is_persona_or_cloned_voice("fish:my-reference-id")


async def test_fish_without_consent_falls_back_to_safe_voice(monkeypatch):
    engine = TTSEngine(consent_getter=lambda: False)
    fish = AsyncMock(return_value=None)
    edge_capture = AsyncMock(return_value="/tmp/out.mp3")
    monkeypatch.setattr(engine, "_speak_fish", fish)
    monkeypatch.setattr(engine, "_speak_edge", edge_capture)
    monkeypatch.setattr(tts_mod, "HAS_EDGE", True)

    result = await engine.speak("hello", voice="fish")

    fish.assert_not_awaited()          # consent denied → never reaches Fish
    assert result == "/tmp/out.mp3"
    assert engine.last_consent_status["allowed"] is False


# ---------------------------------------------------------------------------
# speak() routing + tag stripping
# ---------------------------------------------------------------------------

async def test_speak_passes_raw_tags_to_fish(monkeypatch):
    engine = TTSEngine(consent_getter=lambda: True)
    seen = {}

    async def fake_fish(text, voice):
        seen["text"] = text
        return "/tmp/fish.mp3"

    monkeypatch.setattr(engine, "_speak_fish", fake_fish)
    result = await engine.speak("[calm] All systems nominal.", voice="fish")
    assert result == "/tmp/fish.mp3"
    assert seen["text"] == "[calm] All systems nominal."   # tags survive for Fish


async def test_speak_strips_tags_for_edge(monkeypatch):
    engine = TTSEngine()
    seen = {}

    async def fake_edge(text, voice):
        seen["text"] = text
        return "/tmp/edge.mp3"

    monkeypatch.setattr(engine, "_speak_edge", fake_edge)
    monkeypatch.setattr(tts_mod, "HAS_EDGE", True)
    result = await engine.speak("[cheerful] Done, sir. [calm] Anything else?")
    assert result == "/tmp/edge.mp3"
    assert seen["text"] == "Done, sir. Anything else?"


async def test_fish_failure_falls_back_to_edge_with_stripped_text(monkeypatch):
    engine = TTSEngine(consent_getter=lambda: True)
    seen = {}

    async def fake_fish(text, voice):
        return None                     # Fish down / unconfigured

    async def fake_edge(text, voice):
        seen["text"] = text
        seen["voice"] = voice
        return "/tmp/edge.mp3"

    monkeypatch.setattr(engine, "_speak_fish", fake_fish)
    monkeypatch.setattr(engine, "_speak_edge", fake_edge)
    monkeypatch.setattr(tts_mod, "HAS_EDGE", True)
    result = await engine.speak("[calm] fallback please", voice="fish")
    assert result == "/tmp/edge.mp3"
    assert seen["text"] == "fallback please"
    assert "fish" not in str(seen["voice"]).lower()   # fell back to a safe voice


# ---------------------------------------------------------------------------
# _speak_fish
# ---------------------------------------------------------------------------

class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in capturing the POST call."""

    calls: list = []
    response = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = None
    yield


async def test_speak_fish_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    engine = TTSEngine()
    assert await engine._speak_fish("hello", "fish") is None


async def test_speak_fish_success_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fa-test-key")
    monkeypatch.setenv("FISH_AUDIO_VOICE_ID", "env-ref-id")
    monkeypatch.setenv("FISH_AUDIO_MODEL", "s1")
    monkeypatch.setattr(tts_mod, "TEMP_DIR", tmp_path)

    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"MP3DATA"
    _FakeAsyncClient.response = resp
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    engine = TTSEngine()
    out = await engine._speak_fish("[calm] Good evening.", "fish")
    assert out is not None and Path(out).read_bytes() == b"MP3DATA"

    call = _FakeAsyncClient.calls[0]
    assert call["json"]["text"] == "[calm] Good evening."     # raw tags on the wire
    assert call["json"]["reference_id"] == "env-ref-id"
    assert call["headers"]["Authorization"] == "Bearer fa-test-key"
    assert call["headers"]["model"] == "s1"


async def test_speak_fish_voice_reference_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fa-test-key")
    monkeypatch.setenv("FISH_AUDIO_VOICE_ID", "env-ref-id")
    monkeypatch.setattr(tts_mod, "TEMP_DIR", tmp_path)

    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"X"
    _FakeAsyncClient.response = resp
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    engine = TTSEngine()
    await engine._speak_fish("hi", "fish:override-id")
    assert _FakeAsyncClient.calls[0]["json"]["reference_id"] == "override-id"


async def test_speak_fish_http_error_returns_none(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fa-test-key")
    resp = MagicMock()
    resp.status_code = 402
    _FakeAsyncClient.response = resp
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    engine = TTSEngine()
    assert await engine._speak_fish("hi", "fish") is None
