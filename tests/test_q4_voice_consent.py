"""M1.5 / Q4 voice-persona consent gate.

Plain asserts only: pytest can discover these, and the sandbox can run them
directly without a pytest install.
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.cognition.persona import PersonaModule
from agents.core.settings_db import DEFAULTS
from agents.core.voice import tts as tts_mod
from agents.core.voice.tts import (
    TTSEngine,
    is_persona_or_cloned_voice,
    voice_persona_consent_status,
)


def _run(coro):
    return asyncio.run(coro)


def _engine(consent: bool):
    tts_mod.HAS_EDGE = True
    tts_mod.HAS_KOKORO = False
    engine = TTSEngine(consent_getter=lambda: consent)
    calls = []

    async def xtts(text, voice):
        calls.append(("xtts", voice))
        return "xtts.wav"

    async def elevenlabs(text, voice):
        calls.append(("elevenlabs", voice))
        return "elevenlabs.mp3"

    async def edge(text, voice):
        calls.append(("edge", voice))
        return f"edge:{voice}"

    engine._speak_xtts = xtts
    engine._speak_elevenlabs = elevenlabs
    engine._speak_edge = edge
    return engine, calls


def test_persona_voice_detection_covers_cloned_providers():
    assert is_persona_or_cloned_voice("xtts:andrei") is True
    assert is_persona_or_cloned_voice("elevenlabs:voice-id") is True
    assert is_persona_or_cloned_voice("en-GB-RyanNeural") is False
    assert is_persona_or_cloned_voice(None) is False


def test_cloned_voice_falls_back_without_owner_consent():
    engine, calls = _engine(consent=False)

    out = _run(engine.speak("hello", voice="xtts:andrei", lang="ro"))

    assert out == "edge:ro-RO-EmilNeural"
    assert calls == [("edge", "ro-RO-EmilNeural")]
    assert engine.last_consent_status["required"] is True
    assert engine.last_consent_status["allowed"] is False
    assert engine.last_consent_status["requested_voice"] == "xtts:andrei"
    assert engine.last_consent_status["fallback_voice"] == "ro-RO-EmilNeural"
    assert "owner consent" in engine.last_consent_status["message"]


def test_cloned_voice_runs_after_owner_consent():
    engine, calls = _engine(consent=True)

    out = _run(engine.speak("hello", voice="elevenlabs:voice-id", lang="en"))

    assert out == "elevenlabs.mp3"
    assert calls == [("elevenlabs", "elevenlabs:voice-id")]
    assert engine.last_consent_status["required"] is True
    assert engine.last_consent_status["allowed"] is True


def test_default_voice_is_unaffected_without_owner_consent():
    engine, calls = _engine(consent=False)

    out = _run(engine.speak("hello", voice="en-US-GuyNeural", lang="en"))

    assert out == "edge:en-US-GuyNeural"
    assert calls == [("edge", "en-US-GuyNeural")]
    assert engine.last_consent_status["required"] is False
    assert engine.last_consent_status["allowed"] is True


def test_cloned_configured_default_voice_still_requires_consent():
    tts_mod.HAS_EDGE = True
    engine = TTSEngine(default_voice="xtts:configured", consent_getter=lambda: False)
    calls = []

    async def xtts(text, voice):
        calls.append(("xtts", voice))
        return "xtts.wav"

    async def edge(text, voice):
        calls.append(("edge", voice))
        return f"edge:{voice}"

    engine._speak_xtts = xtts
    engine._speak_edge = edge

    out = _run(engine.speak("hello"))

    assert out == "edge:en-GB-RyanNeural"
    assert calls == [("edge", "en-GB-RyanNeural")]
    assert engine.last_consent_status["requested_voice"] == "xtts:configured"
    assert engine.last_consent_status["allowed"] is False


def test_voice_persona_consent_default_is_seeded_off():
    row = next(
        item for item in DEFAULTS
        if item["category"] == "voice" and item["key"] == "persona_voice_consent"
    )
    assert row["value"] is False
    assert row["kind"] == "toggle"


def test_persona_module_surfaces_voice_consent_status():
    status = PersonaModule().voice_consent_status(consent_getter=lambda: False)

    assert status["required"] is True
    assert status["granted"] is False
    assert "owner consent" in status["message"]
    assert voice_persona_consent_status(consent_getter=lambda: True)["granted"] is True
