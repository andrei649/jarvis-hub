"""H526 — a spoken reply sounds like speech, not like read-out markdown.

One normaliser (``agents/core/voice/speech_text.for_speech``) sits in front of every
text-to-speech entry point — ``TTSEngine.speak`` (and so the wake-word pipeline, the
voice channel and chat voice notes), ``speak_stream`` and the ``/tts`` and
``/tts/stream`` routes — with a TypeScript twin in the HUD (``frontend/src/
speech-text.ts``). Both are pinned by the same cases, ``frontend/src/test/
speech-text-cases.json``, so the browser and the hub can never read the same reply
differently.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.core.voice import speech_text  # noqa: E402
from agents.core.voice.speech_text import for_speech, speech_lang  # noqa: E402

CASES = json.loads((ROOT / "frontend" / "src" / "test" / "speech-text-cases.json").read_text(encoding="utf-8"))


# ── the shared cases ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_shared_cases(case):
    assert for_speech(case["text"], lang=case["lang"]) == case["spoken"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_normalising_twice_changes_nothing(case):
    """Every entry point may normalise again (SpokenReply → TTSEngine.speak): it must be
    a fixed point, or a second pass would read "link" as something else."""
    once = for_speech(case["text"], lang=case["lang"])
    assert for_speech(once, lang=case["lang"]) == once


def test_the_cases_cover_what_the_row_names():
    names = {c["name"] for c in CASES}
    for required in ("emoji", "emoji_sequences", "lists", "table", "think_closed", "think_unclosed",
                     "symbols_en", "symbols_ro", "bare_url_in_parentheses", "emotion_tags_kept",
                     "unclosed_fence"):
        assert required in names, required


def test_nothing_in_is_nothing_out():
    for value in (None, "", "   ", 0, "```\n```"):
        assert for_speech(value) == ""


def test_the_language_picks_the_words():
    assert for_speech("a & b", lang="ro-RO") == "a și b"
    assert for_speech("a & b", lang="RO") == "a și b"
    assert for_speech("a & b", lang="en-GB") == "a and b"
    assert for_speech("a & b", lang=None) == "a and b"
    assert for_speech("a & b", lang="fr") == "a and b", "an unknown language reads the English words"


def test_speech_lang_follows_the_request_then_the_voice_then_the_default():
    assert speech_lang("ro", "en-GB-RyanNeural") == "ro"
    assert speech_lang(None, "ro-RO-EmilNeural") == "ro"
    assert speech_lang("", "en-US-GuyNeural") == "en"
    assert speech_lang(None, "xtts", default="ro") == "ro"
    assert speech_lang(None, None) == "en"


def test_emoji_ranges_keep_ordinary_text():
    text = "Preț: 5 € — „bine” … ™ © ° ș ț ă î â ñ ü 中文 😀"
    assert for_speech(text, lang="ro") == "Preț: 5 € — „bine”… ™ © grade ș ț ă î â ñ ü 中文"


# ── every hub entry point ────────────────────────────────────────────────────


class _Capture:
    def __init__(self):
        self.seen: list[str] = []

    async def __call__(self, text, voice=None):
        self.seen.append(text)
        return "/tmp/fake.mp3"


@pytest.mark.asyncio
async def test_tts_engine_speaks_the_normalised_text():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    edge = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_edge", edge):
        path = await engine.speak("**Gata** 🎉 -> [calm] vezi https://x.test/a.", lang="ro")
    assert path == "/tmp/fake.mp3"
    assert edge.seen == ["Gata spre vezi link."], "markup, emoji and the emotion tag never reach edge-tts"


@pytest.mark.asyncio
async def test_tts_engine_keeps_emotion_tags_for_fish():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine(consent_getter=lambda: True)
    fish = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_fish", fish):
        await engine.speak("[calm] **All** good 👍", voice="fish:abc", lang="en")
    assert fish.seen == ["[calm] All good"]


@pytest.mark.asyncio
async def test_tts_engine_takes_the_language_from_the_voice_when_none_is_given():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine(default_voice="ro-RO-EmilNeural")
    edge = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_edge", edge):
        await engine.speak("50%")
        await engine.speak("50%", voice="en-GB-RyanNeural")
    assert edge.seen == ["50 la sută", "50 percent"]


def test_the_engine_falls_back_to_its_own_language():
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine(default_voice="xtts", default_lang="ro")
    assert engine.speech_for("50%", voice="xtts") == "50 la sută"
    assert engine.speech_for("50%", voice="xtts", lang="en") == "50 percent"
    assert TTSEngine(default_voice="xtts").speech_for("50%") == "50 percent"


@pytest.mark.asyncio
async def test_a_reply_of_only_emotion_tags_is_nothing_to_say_for_edge():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    edge = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_edge", edge):
        assert await engine.speak("[calm] [excited]") is None
    assert edge.seen == []


@pytest.mark.asyncio
async def test_a_voice_note_uses_the_chats_language():
    from agents.core.channels.spoken_reply import SpokenReply

    seen = []

    async def synth(text, lang):
        seen.append((text, lang))
        return None

    await SpokenReply(synthesize=synth, available=True)("Gata 50%!", lang="ro")
    await SpokenReply(synthesize=synth, available=True)("Done 50%!", lang="en")
    assert seen == [("Gata 50 la sută!", "ro"), ("Done 50 percent!", "en")]


@pytest.mark.asyncio
async def test_nothing_to_say_is_no_synthesis():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    edge = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_edge", edge):
        assert await engine.speak("```\nprint(1)\n```\n👍") is None
    assert edge.seen == []


@pytest.mark.asyncio
async def test_nothing_to_say_never_reaches_fish_either():
    import agents.core.voice.tts as tts_module
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine(consent_getter=lambda: True)
    fish = _Capture()
    with patch.object(tts_module, "HAS_EDGE", True), patch.object(engine, "_speak_fish", fish):
        assert await engine.speak("```\nx\n```", voice="fish:abc") is None
    assert fish.seen == []


@pytest.mark.asyncio
async def test_speak_stream_normalises_before_it_splits():
    """A fenced block spanning sentences is dropped whole, never spoken a line at a time."""
    from agents.core.voice.tts import TTSEngine

    engine = TTSEngine()
    seen = []

    async def fake_speak(sentence, voice=None, lang=None):
        seen.append(sentence)
        return "/tmp/x.mp3"

    text = "Intro. ```py\nx = 1. y = 2.\nprint(x)\n``` Then <think>no. never.</think>the end!"
    with patch.object(engine, "speak", side_effect=fake_speak):
        chunks = [c async for c in engine.speak_stream(text, lang="en")]
    assert [c[1] for c in chunks] == ["Intro.", "Then the end!"]
    assert seen == ["Intro.", "Then the end!"]


@pytest.mark.asyncio
async def test_the_voice_note_path_shares_it():
    from agents.core.channels.spoken_reply import speakable

    assert speakable("R&D 👍 - done") == "R and D - done"
    assert speakable("- one\n- two") == "one. two."
    assert speakable("Docs (https://x.test/a).") == "Docs (link)."


@pytest.mark.asyncio
async def test_the_wake_word_pipeline_and_voice_channel_go_through_the_engine():
    """They call TTSEngine.speak, which normalises — pinned so a shortcut to a backend
    cannot creep back in."""
    import inspect

    from agents.core.channels import voice as voice_channel
    from agents.core.voice import pipeline

    assert "self.tts.speak(response)" in inspect.getsource(pipeline.VoicePipeline)
    assert "self.pipeline.tts.speak(" in inspect.getsource(voice_channel)
    src = inspect.getsource(__import__("agents.core.voice.tts", fromlist=["TTSEngine"]).TTSEngine.speak)
    assert src.index("for_speech(") < src.index("_speak_fish("), "normalised before any backend"


# ── the routes ───────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from agents import web

    with TestClient(web.app) as c:
        yield c


@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine.speak")
def test_tts_route_says_nothing_to_say_without_synthesising(mock_speak, client):
    resp = client.post("/tts", json={"text": "```\nls -la\n```", "lang": "en"})
    assert resp.status_code == 204
    assert resp.headers["x-nerva-speech"] == "nothing_to_say"
    assert resp.content == b""
    mock_speak.assert_not_called()


@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine.speak")
def test_tts_route_hands_the_engine_the_request(mock_speak, client):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"audio")
    mock_speak.return_value = tmp.name
    try:
        resp = client.post("/tts", json={"text": "**Salut** 👋", "lang": "ro"})
        assert resp.status_code == 200 and resp.content == b"audio"
        (args, kwargs) = mock_speak.call_args
        assert kwargs["lang"] == "ro"
    finally:
        os.remove(tmp.name)


@patch("agents.core.routers.voice._tts_stream_enabled", return_value=True)
@patch("core.voice.tts.HAS_EDGE", True)
@patch("core.voice.tts.TTSEngine._speak_edge")
def test_tts_stream_frames_carry_the_spoken_sentences(mock_edge, _enabled, client):
    paths = []

    async def fake_edge(text, voice=None):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"a:" + text.encode("utf-8"))
        paths.append(f.name)
        return f.name

    mock_edge.side_effect = fake_edge
    try:
        resp = client.post("/tts/stream", json={
            "text": "# Plan\n- **Step** one\n```sh\nrm -rf /\n```\nDone 🎉", "lang": "en"})
        assert resp.status_code == 200
        texts = []
        body, pos = resp.content, 0
        while pos < len(body):
            nl = body.index(b"\n", pos)
            header = json.loads(body[pos:nl])
            texts.append(header["text"])
            pos = nl + 1 + header["bytes"]
        assert texts == ["Plan.", "Step one.", "Done", ""]
    finally:
        for p in paths:
            os.remove(p)


def test_the_module_is_pure():
    src = (ROOT / "agents" / "core" / "voice" / "speech_text.py").read_text(encoding="utf-8")
    for forbidden in ("import httpx", "import requests", "open(", "subprocess"):
        assert forbidden not in src, forbidden
    assert speech_text.__all__
