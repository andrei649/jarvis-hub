"""A reply becomes a voice note, bounded and plain (H071, the spoken half).

What is pinned: the speakable text is prose only — no fenced code, no URLs,
no markers — cut at a sentence boundary with the cut marked; the gate answers
before any synthesis; every failure is a named reason and never an exception;
the synthesized file is read once and removed; the log never carries the
reply text.

Hermetic: an injected synthesizer writing to a temp dir, no speech stack.
"""

from __future__ import annotations

import logging

import pytest

from agents.core.channels.spoken_reply import (
    MAX_SPOKEN_CHARS,
    REASON_EMPTY,
    REASON_FAILED,
    REASON_NO_TTS,
    REASON_TOO_LARGE,
    Audio,
    SpokenReply,
    speakable,
)

# ── what is worth reading aloud ─────────────────────────────────────────────


def test_markers_links_and_code_do_not_get_read_aloud():
    text = (
        "**Done.** See `serve.py` and https://example.com/x for the rest.\n\n"
        "```python\nprint('never spoken')\n```\n"
        "_Next_: restart."
    )
    assert speakable(text) == "Done. See serve.py and link for the rest. Next: restart."


def test_whitespace_folds_and_nothing_becomes_nothing():
    assert speakable("  a \n\n\t b  ") == "a b"
    assert speakable("") == ""
    assert speakable(None) == ""
    assert speakable("```\nonly code\n```") == ""


def test_a_long_reply_is_cut_at_a_sentence_boundary_and_the_cut_is_marked():
    sentences = [f"Sentence number {i} is here." for i in range(200)]
    text = " ".join(sentences)
    spoken = speakable(text, max_chars=120)
    assert len(spoken) <= 120
    assert spoken.endswith("…")
    body = spoken[:-1]
    assert body.endswith("is here"), body
    assert body.count("Sentence number") >= 2, "a cut at the boundary keeps whole sentences"


def test_a_single_sentence_longer_than_the_cap_is_hard_cut_not_dropped():
    text = "x" * 500
    spoken = speakable(text, max_chars=64)
    assert spoken.endswith("…") and len(spoken) <= 64
    assert spoken[:10] == "x" * 10


def test_the_default_cap_is_a_paragraph_not_an_audiobook():
    assert MAX_SPOKEN_CHARS == 1500


@pytest.mark.parametrize("bad", [0, 15, -1, True, "16"])
def test_a_nonsense_cap_is_refused(bad):
    with pytest.raises(ValueError):
        speakable("hi", max_chars=bad)


# ── the synthesis ───────────────────────────────────────────────────────────


class _Synth:
    def __init__(self, tmp_path, *, suffix=".mp3", payload=b"ID3fake", fail=None):
        self.tmp_path = tmp_path
        self.suffix = suffix
        self.payload = payload
        self.fail = fail
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, text, lang):
        self.seen.append((text, lang))
        if self.fail == "raise":
            raise RuntimeError("engine said: " + text)
        if self.fail == "none":
            return None
        path = self.tmp_path / f"clip{len(self.seen)}{self.suffix}"
        path.write_bytes(self.payload)
        return str(path)


@pytest.mark.asyncio
async def test_the_gate_refuses_before_any_synthesis(tmp_path):
    synth = _Synth(tmp_path)
    speaker = SpokenReply(synthesize=synth, available=False)
    refused = speaker.refusal()
    assert refused is not None and refused.reason == REASON_NO_TTS
    audio = await speaker("hello")
    assert (audio.ok, audio.reason) == (False, REASON_NO_TTS)
    assert synth.seen == []


@pytest.mark.asyncio
async def test_a_reply_with_nothing_speakable_is_a_reason_not_a_call(tmp_path):
    synth = _Synth(tmp_path)
    audio = await SpokenReply(synthesize=synth, available=True)("```\ncode\n```")
    assert (audio.ok, audio.reason) == (False, REASON_EMPTY)
    assert synth.seen == []


@pytest.mark.asyncio
async def test_the_clip_comes_back_and_the_file_does_not_stay(tmp_path):
    synth = _Synth(tmp_path)
    audio = await SpokenReply(synthesize=synth, available=True, backend="fake")("**Salut**, ce faci?", lang="ro")
    assert audio.ok and audio.data == b"ID3fake" and audio.mime == "audio/mpeg"
    assert audio.chars == len("Salut, ce faci?") and audio.backend == "fake"
    assert synth.seen == [("Salut, ce faci?", "ro")], "the engine gets the plain text, not the markup"
    assert list(tmp_path.iterdir()) == [], "the clip lives in the message, not on the host"
    assert len(audio.sha256) == 64


@pytest.mark.asyncio
async def test_the_mime_follows_the_file_the_engine_wrote(tmp_path):
    ogg = await SpokenReply(synthesize=_Synth(tmp_path, suffix=".ogg", payload=b"OggS"), available=True)("hi")
    wav = await SpokenReply(synthesize=_Synth(tmp_path, suffix=".wav", payload=b"RIFF"), available=True)("hi")
    assert (ogg.mime, wav.mime) == ("audio/ogg", "audio/wav")


@pytest.mark.asyncio
async def test_an_engine_that_returns_nothing_or_raises_is_a_reason_and_the_text_is_not_logged(tmp_path, caplog):
    secret = "the owner's private sentence"
    with caplog.at_level(logging.INFO, logger="jarvis.channels.spoken_reply"):
        none = await SpokenReply(synthesize=_Synth(tmp_path, fail="none"), available=True)(secret)
        raised = await SpokenReply(synthesize=_Synth(tmp_path, fail="raise"), available=True)(secret)
    assert (none.ok, none.reason) == (False, REASON_FAILED)
    assert (raised.ok, raised.reason) == (False, REASON_FAILED)
    assert "private sentence" not in caplog.text


@pytest.mark.asyncio
async def test_an_empty_or_oversized_clip_is_refused_and_removed(tmp_path):
    empty = await SpokenReply(synthesize=_Synth(tmp_path, payload=b""), available=True)("hi")
    assert (empty.ok, empty.reason) == (False, REASON_FAILED)
    big = await SpokenReply(synthesize=_Synth(tmp_path, payload=b"x" * 64), available=True, max_bytes=32)("hi")
    assert (big.ok, big.reason) == (False, REASON_TOO_LARGE)
    assert list(tmp_path.iterdir()) == []


def test_the_loggable_view_carries_sizes_and_reasons_never_audio():
    view = Audio(True, data=b"abc", sha256="d" * 64, chars=3, backend="fake").to_dict()
    assert view == {"ok": True, "bytes": 3, "mime": "audio/mpeg", "sha256": "d" * 64,
                    "reason": "", "chars": 3, "backend": "fake"}


@pytest.mark.parametrize("kw", [{"max_chars": 8}, {"max_bytes": 0}, {"max_bytes": True}])
def test_nonsense_bounds_are_refused(kw):
    with pytest.raises(ValueError):
        SpokenReply(**kw)


def test_the_backend_is_named_honestly():
    assert SpokenReply(backend="x").backend_label() == "x"
    edge = SpokenReply()
    edge._engines = staticmethod(lambda: (True, True))
    assert SpokenReply._engines is not edge._engines
    assert SpokenReply(available=True).is_available is True
    assert SpokenReply(available=False).is_available is False
