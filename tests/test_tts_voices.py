"""Per-agent signature voice resolution (local Kokoro, no cloud).
Tests config resolution only — does not require the kokoro package."""
from voice.tts import TextToSpeech, AGENT_VOICE_MAP, DEFAULT_LANG


def test_jarvis_uses_signature_british_voice():
    tts = TextToSpeech.for_agent("jarvis")
    assert tts.lang == "en-gb"
    assert tts.voice == "bm_george"


def test_unmapped_agent_falls_back_to_default():
    tts = TextToSpeech.for_agent("pepper")
    assert tts.lang == DEFAULT_LANG
    assert tts.voice is None  # resolved to language default at load() time


def test_jarvis_is_registered():
    assert "jarvis" in AGENT_VOICE_MAP
