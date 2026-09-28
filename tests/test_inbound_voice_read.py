"""A voice note becomes what the sender said — and the bytes stay on the box.

The Telegram half of H071. `media_reader` reads a photo; this reads speech, and
the two are deliberately *not* the same shape, because the trust story differs:

- A photo description is a model's observation of bytes a stranger chose, so it
  travels inside the untrusted fence.
- A transcript is the sender's own words at exactly the trust level those words
  would have had typed, so it travels as an ordinary turn. Fencing it would tell
  the model to read the owner's own request as quarantined data, and would
  advertise a protection that is not the one doing the work.

The protection that *is* doing the work is the hallucination filter
(`test_voice_hallucination.py`), and it runs inside the engine so the browser
dictation route gets it too. What is pinned here: the local gate runs before the
download, the sentinels never reach the model as speech, nothing is written to
disk, and the turn is not fenced.

Hermetic: no network, no Whisper, no Telegram.
"""

from __future__ import annotations

import itertools

import pytest

from agents.core.action_origin import INBOUND_ACTION_ORIGIN, origin_for_channel
from agents.core.channels.inbound_media import classify
from agents.core.channels.inbound_voice import (
    MAX_TRANSCRIPT_CHARS,
    NOTES,
    REASON_DOWNLOAD,
    REASON_EMPTY,
    REASON_FAILED,
    REASON_NO_STT,
    REASON_SILENCE,
    REASON_TOO_LARGE,
    InboundVoiceReader,
    Transcript,
    note,
    turn_text,
)
from agents.core.channels.telegram import TelegramChannel
from agents.core.security.taint import is_untrusted_source


@pytest.fixture(autouse=True)
def _one_turn_per_message(monkeypatch):
    """These tests are about each message on its own; H117's batching has its own tests."""
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")


OGG = b"OggS" + b"not really opus, and it never needs to be"
SAID = "pornește calculatorul din birou"


class _Spy:
    """Records every call. `seen` staying empty is what the gate tests assert."""

    def __init__(self, reply=SAID):
        self.reply = reply
        self.seen: list[tuple[bytes, str]] = []

    async def __call__(self, audio, language):
        self.seen.append((audio, language))
        return self.reply


def _reader(*, available=True, spy=None, **kw):
    return InboundVoiceReader(available=available, transcribe=spy or _Spy(), **kw)


# ── the gate ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_host_with_no_speech_engine_transcribes_nothing():
    spy = _Spy()
    out = await _reader(available=False, spy=spy)(OGG)
    assert (out.ok, out.reason) == (False, REASON_NO_STT)
    assert spy.seen == []


def test_refusal_answers_before_any_bytes_exist():
    """So a caller can skip the download instead of paying for it."""
    assert _reader(available=True).refusal() is None
    assert _reader(available=False).refusal().reason == REASON_NO_STT


@pytest.mark.asyncio
async def test_the_gate_and_the_refusal_cannot_disagree():
    reader = _reader(available=False)
    assert reader.refusal().reason == (await reader(OGG)).reason


def test_availability_derives_from_the_installed_engine():
    """With no override it reads HAS_WHISPER, never a setting or a guess."""
    reader = InboundVoiceReader()
    from agents.core.voice.stt import HAS_WHISPER

    assert reader.is_available is bool(HAS_WHISPER)


# ── bounds ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_audio_is_a_named_refusal_not_a_call():
    spy = _Spy()
    out = await _reader(spy=spy)(b"")
    assert (out.ok, out.reason) == (False, REASON_EMPTY)
    assert spy.seen == []


@pytest.mark.asyncio
async def test_an_oversized_recording_is_refused_before_the_engine():
    spy = _Spy()
    out = await _reader(spy=spy, max_bytes=64)(b"x" * 65)
    assert (out.ok, out.reason) == (False, REASON_TOO_LARGE)
    assert spy.seen == []


@pytest.mark.asyncio
async def test_a_long_transcript_is_bounded_before_it_travels():
    out = await _reader(spy=_Spy("word " * 5000), max_chars=64)(OGG)
    assert out.ok is True
    assert len(out.text) <= 64


def test_the_reader_refuses_a_nonsense_bound():
    for kwargs in ({"max_bytes": 0}, {"max_bytes": True}, {"max_chars": 8}):
        with pytest.raises(ValueError):
            InboundVoiceReader(**kwargs)


def test_the_transcript_cap_leaves_room_for_a_real_voice_note():
    assert 1000 <= MAX_TRANSCRIPT_CHARS <= 20000


# ── the engine's sentinels are failures, never speech ───────────────────────


@pytest.mark.asyncio
async def test_silence_is_reported_as_silence_not_spoken():
    out = await _reader(spy=_Spy("[silence]"))(OGG)
    assert (out.ok, out.reason) == (False, REASON_SILENCE)
    assert out.text == ""


@pytest.mark.asyncio
async def test_an_unavailable_engine_sentinel_maps_to_its_own_reason():
    out = await _reader(spy=_Spy("[STT unavailable]"))(OGG)
    assert (out.ok, out.reason) == (False, REASON_NO_STT)


@pytest.mark.asyncio
async def test_an_engine_error_sentinel_never_reaches_the_model_as_speech():
    out = await _reader(spy=_Spy("[STT error: CUDA out of memory at 0x7f]"))(OGG)
    assert (out.ok, out.reason) == (False, REASON_FAILED)
    assert "CUDA" not in str(out.to_dict())
    assert turn_text(out) == ""


@pytest.mark.asyncio
async def test_a_raising_engine_leaks_no_exception_text():
    class _Boom:
        async def __call__(self, audio, language):
            raise RuntimeError("model path /home/andrei/.cache/whisper missing")

    out = await InboundVoiceReader(available=True, transcribe=_Boom())(OGG)
    assert (out.ok, out.reason) == (False, REASON_FAILED)
    assert "andrei" not in str(out.to_dict())


@pytest.mark.asyncio
async def test_an_empty_answer_is_a_failure_not_an_empty_message():
    assert (await _reader(spy=_Spy("   "))(OGG)).reason == REASON_FAILED


# ── the turn: the sender's own words, unfenced ──────────────────────────────


@pytest.mark.asyncio
async def test_the_transcript_is_not_fenced():
    """The architectural decision, pinned.

    A transcript is what the sender said. Wrapping it in the untrusted fence
    would tell the model to treat the owner's own request as quarantined data —
    the opposite of what a spoken instruction is — and would claim a protection
    that the hallucination filter, not the fence, actually provides here.
    """
    out = await _reader(spy=_Spy(SAID))(OGG)
    assert out.ok is True
    assert out.text == SAID
    assert "<<UNTRUSTED" not in out.text
    assert "▁" not in out.text
    assert turn_text(out) == SAID


def test_a_caption_on_a_voice_note_leads_and_the_speech_follows():
    out = Transcript(True, text=SAID)
    assert turn_text(out, "uite:") == f"uite:\n\n{SAID}"


def test_a_failed_transcription_carries_only_what_was_written():
    assert turn_text(Transcript(False, reason=REASON_SILENCE), "uite:") == "uite:"
    assert turn_text(Transcript(False, reason=REASON_SILENCE), "") == ""


def test_turn_text_refuses_a_shape_it_does_not_understand():
    with pytest.raises(TypeError):
        turn_text({"ok": True, "text": "hi"})


@pytest.mark.asyncio
async def test_the_loggable_view_never_carries_what_was_said():
    out = await _reader(spy=_Spy("codul de la seif este 1234"))(OGG)
    assert "seif" not in str(out.to_dict())
    assert "1234" not in str(out.to_dict())
    assert out.to_dict()["chars"] > 0


@pytest.mark.asyncio
async def test_the_digest_ties_a_transcript_to_the_bytes_without_keeping_them():
    import hashlib

    out = await _reader()(OGG)
    assert out.sha256 == hashlib.sha256(OGG).hexdigest()


def test_every_reason_has_a_sentence_for_the_sender():
    reasons = {REASON_NO_STT, REASON_EMPTY, REASON_TOO_LARGE,
               REASON_FAILED, REASON_SILENCE, REASON_DOWNLOAD}
    assert set(NOTES) == reasons
    for reason in reasons:
        clause = note(Transcript(False, reason=reason))
        assert clause and not clause.endswith(".")


def test_a_refusal_never_names_a_host_a_path_or_a_handle():
    joined = " ".join(NOTES.values())
    for leak in ("http", "/home", "file_id", "token", "Traceback", "whisper"):
        assert leak not in joined


def test_a_successful_transcription_has_no_note():
    assert note(Transcript(True, text=SAID)) == ""


# ── the engine applies the filter ───────────────────────────────────────────


class _FakeInfo:
    def __init__(self, duration):
        self.duration = duration


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    """Stands in for a loaded Whisper model; records what it was handed."""

    def __init__(self, text, duration=3.0):
        self.text = text
        self.duration = duration
        self.sources = []

    def transcribe(self, source, **kw):
        self.sources.append(source)
        return [_FakeSegment(self.text)], _FakeInfo(self.duration)


def _engine(text, duration=3.0):
    from agents.core.voice.stt import STTEngine

    engine = STTEngine.__new__(STTEngine)
    engine.beam_size = 1
    engine._model = _FakeModel(text, duration)
    return engine


def test_the_engine_discards_a_hallucination_as_silence():
    """One filter, applied where every caller already handles the answer.

    `[silence]` is the sentinel this method already returned for empty audio, so
    the browser route (`routers/voice.py` skips dictation cleanup on a leading
    `[`) and the HUD (`frontend/src/voice.ts` drops it) both honour it unchanged.
    """
    assert _engine("Subtitles by the Amara.org community").transcribe(b"x") == "[silence]"
    assert _engine("Thanks for watching!").transcribe(b"x") == "[silence]"


def test_the_engine_keeps_real_speech():
    assert _engine(SAID).transcribe(b"x") == SAID


def test_the_engine_uses_the_decoded_duration_not_a_sender_supplied_one():
    """A short-recording rule driven by a number in an envelope could be steered."""
    assert _engine("Mulțumesc.", duration=0.2).transcribe(b"x") == "[silence]"
    assert _engine("Mulțumesc.", duration=4.0).transcribe(b"x") == "Mulțumesc."


def test_the_engine_takes_bytes_without_writing_them_to_disk():
    import io

    engine = _engine(SAID)
    engine.transcribe(b"raw-audio-bytes")
    handed = engine._model.sources[0]
    assert isinstance(handed, io.BytesIO)
    assert handed.getvalue() == b"raw-audio-bytes"


def test_the_engine_still_takes_a_path():
    engine = _engine(SAID)
    engine.transcribe("/tmp/recording.webm")
    assert engine._model.sources[0] == "/tmp/recording.webm"


def test_an_engine_with_no_model_is_honest_rather_than_inventive():
    from agents.core.voice.stt import STTEngine

    engine = STTEngine.__new__(STTEngine)
    engine._model = None
    assert engine.transcribe(b"x") == "[STT unavailable]"


# ── the Telegram seam ───────────────────────────────────────────────────────


_update_ids = itertools.count(21000)


def _update(chat_id=42, uid=42, **extra):
    return {
        "update_id": next(_update_ids),
        "message": {"message_id": 1, "from": {"id": uid},
                    "chat": {"id": chat_id, "type": "private"}, **extra},
    }


async def _drain(channel, updates):
    batches = [updates]

    async def fake_updates():
        if batches:
            return batches.pop(0)
        channel._running = False
        return []

    channel._get_updates = fake_updates
    channel._running = True
    await channel._poll_loop()


def _channel(voice_reader=None):
    turns, sent, actions = [], [], []

    async def handler(text, channel="telegram", **kwargs):
        turns.append(text)
        return "ok"

    ch = TelegramChannel(token="t", handler=handler)
    ch._bot_id, ch._bot_username = 1, "nerva_bot"

    async def fake_send(message, chat_id=None, **kwargs):
        sent.append(message)
        return True

    async def fake_action(chat_id, action="typing"):
        actions.append(action)
        return True

    ch.send = fake_send
    ch.send_action = fake_action
    if voice_reader is not None:
        ch._voice_reader = voice_reader
    return ch, turns, sent, actions


@pytest.mark.asyncio
async def test_a_voice_note_becomes_the_turn_it_says():
    ch, turns, sent, actions = _channel(_reader(spy=_Spy(SAID)))

    async def fake_download(file_id, max_bytes):
        return OGG

    ch._download_file = fake_download
    await _drain(ch, [_update(voice={"file_id": "v", "file_size": 4096})])
    assert turns == [SAID]
    assert sent == [], "a transcribed note is answered, not acknowledged twice"
    assert actions == ["typing"]


@pytest.mark.asyncio
async def test_a_voice_note_is_not_downloaded_when_nothing_could_read_it():
    calls = []
    ch, turns, sent, _ = _channel(_reader(available=False))

    async def fake_download(file_id, max_bytes):
        calls.append(file_id)
        return OGG

    ch._download_file = fake_download
    await _drain(ch, [_update(voice={"file_id": "v"})])
    assert calls == [], "someone's recording was downloaded for nothing"
    assert sent == ["I can see you sent a voice note, but there is no speech "
                    "engine installed here yet."]
    assert turns == []


@pytest.mark.asyncio
async def test_a_silent_recording_is_answered_rather_than_turned_into_a_message():
    """The safety control, end to end: nobody said it, so nobody asked for anything."""
    ch, turns, sent, _ = _channel(_reader(spy=_Spy("[silence]")))

    async def fake_download(file_id, max_bytes):
        return OGG

    ch._download_file = fake_download
    await _drain(ch, [_update(voice={"file_id": "v"})])
    assert turns == []
    assert sent == ["I can see you sent a voice note, but I could not hear "
                    "anything said in it."]


@pytest.mark.asyncio
async def test_a_failed_download_says_so_instead_of_answering():
    ch, turns, sent, _ = _channel(_reader(spy=_Spy()))

    async def boom(file_id, max_bytes):
        raise RuntimeError("502 from api.telegram.org")

    ch._download_file = boom
    await _drain(ch, [_update(voice={"file_id": "v"})])
    assert sent == ["I can see you sent a voice note, but I could not download "
                    "it from Telegram."]
    assert "502" not in " ".join(sent)
    assert turns == []


@pytest.mark.asyncio
async def test_a_text_message_never_builds_a_voice_reader():
    ch, turns, sent, actions = _channel()
    await _drain(ch, [_update(text="salut")])
    assert turns == ["salut"]
    assert ch._voice_reader is None
    assert sent == [] and actions == []


def test_a_spoken_instruction_cannot_auto_execute():
    """Speech is an inbound turn like any other, and the kernel queues those.

    The same conclusion the photo path pins, and for a stronger reason here: a
    voice note is the most natural way to ask for something destructive, so the
    origin the kernel sees must stay untrusted whatever else changes.
    """
    origin = origin_for_channel("telegram")
    assert is_untrusted_source(origin)
    assert origin == INBOUND_ACTION_ORIGIN


def test_a_voice_note_is_classified_as_readable_now():
    att = classify({"voice": {"file_id": "v", "file_size": 4096}})
    assert att.kind == "voice"
    assert att.readable is True
    assert att.reason == ""
