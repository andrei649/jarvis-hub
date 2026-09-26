"""A Telegram reply becomes a voice note when the chat asked (H071, the spoken half).

The hook sits where the words are actually delivered — `send()` and the
streaming draft's `finish()` — so the mode can only add audio to a reply that
was already going out as text. What is pinned: off by default; `voice` speaks
only the reply to a voice note and forgets the mark after a silent turn;
`always` speaks every delivered reply; a failed synthesis or a refused upload
costs the clip and never the text; Telegram's 400 on the clip falls back to an
audio file once; the transcript echo is a service line that is never spoken
and never spends the mark.

Hermetic: a recording HTTP client, an in-memory mode store, an injected
synthesizer and transcriber, no Telegram and no speech stack.
"""

from __future__ import annotations

import itertools

import pytest

from agents.core.channels import telegram as telegram_module
from agents.core.channels.inbound_voice import InboundVoiceReader
from agents.core.channels.render import to_telegram_html
from agents.core.channels.spoken_reply import SpokenReply
from agents.core.channels.telegram import TelegramChannel, TelegramDraft
from agents.core.channels.voice_mode import ALWAYS, OFF, VOICE, VoiceModeStore

_update_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _one_turn_per_message(monkeypatch):
    """These tests are about each message on its own; H117's batching has its own tests."""
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")


OGG = b"OggS" + b"pretend"
SAID = "cât e ceasul"
REPLY = "**Este** ora 10.\n\n```\nnot spoken\n```"
SPOKEN = "Este ora 10."


class _Response:
    def __init__(self, status=200):
        self.status_code = status
        self.is_success = status < 400

    def json(self):
        return {"ok": self.is_success, "result": {"message_id": 7}} if self.is_success else {"ok": False}

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Records every POST by Telegram method; answers with scripted statuses."""

    def __init__(self, statuses=None):
        self.calls: list[tuple[str, dict]] = []
        self.statuses = dict(statuses or {})

    async def post(self, url, json=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, {"json": json, "data": data, "files": files}))
        queue = self.statuses.get(method)
        status = queue.pop(0) if queue else 200
        return _Response(status)

    def methods(self):
        return [m for m, _ in self.calls]


class _Synth:
    def __init__(self, tmp_path, fail=False):
        self.tmp_path, self.fail, self.seen = tmp_path, fail, []

    async def __call__(self, text, lang):
        self.seen.append((text, lang))
        if self.fail:
            return None
        path = self.tmp_path / f"clip{len(self.seen)}.mp3"
        path.write_bytes(b"ID3clip")
        return str(path)


async def _transcribe(audio, language):
    return SAID


def _channel(tmp_path, mode=OFF, *, reply=REPLY, statuses=None, synth_fail=False, silent=False):
    client = _Client(statuses)
    synth = _Synth(tmp_path, fail=synth_fail)

    async def handler(text, channel="telegram", **kwargs):
        # The orchestrator delivers through the adapter's own send(); a silent
        # turn delivers nothing at all.
        if not silent:
            await ch.send(reply, chat_id=kwargs["chat_id"])
        return None if silent else reply

    ch = TelegramChannel(token="t", handler=handler)
    ch._bot_id, ch._bot_username = 1, "nerva_bot"
    ch.client = client
    ch._voice_modes = VoiceModeStore(None)
    ch._voice_modes.set("telegram", 42, mode)
    ch._speaker = SpokenReply(synthesize=synth, available=True, backend="fake")
    ch._voice_reader = InboundVoiceReader(available=True, transcribe=_transcribe)

    async def fake_download(file_id, max_bytes):
        return OGG

    ch._download_file = fake_download
    return ch, client, synth


def _update(chat_id=42, uid=42, **extra):
    return {
        "update_id": next(_update_ids),
        "message": {"message_id": 1, "from": {"id": uid}, "chat": {"id": chat_id, "type": "private"}, **extra},
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


VOICE_NOTE = {"voice": {"file_id": "v", "file_size": 4096}}


# ── the modes ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_off_by_default_a_voice_note_gets_a_text_reply_only(tmp_path):
    ch, client, synth = _channel(tmp_path, OFF)
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods() == ["sendChatAction", "sendMessage"]
    assert synth.seen == []


@pytest.mark.asyncio
async def test_voice_mode_answers_a_voice_note_with_a_voice_note_after_the_text(tmp_path):
    ch, client, synth = _channel(tmp_path, VOICE)
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods() == ["sendChatAction", "sendMessage", "sendChatAction", "sendVoice"]
    assert client.calls[2][1]["json"] == {"chat_id": 42, "action": "record_voice"}
    method, call = client.calls[3]
    assert call["data"] == {"chat_id": "42"}
    filename, data, mime = call["files"]["voice"]
    assert (filename, data, mime) == ("reply.mp3", b"ID3clip", "audio/mpeg")
    assert synth.seen == [(SPOKEN, "ro")], "the engine gets the plain reply, not the markup or the code"


@pytest.mark.asyncio
async def test_voice_mode_leaves_a_typed_question_as_text(tmp_path):
    ch, client, synth = _channel(tmp_path, VOICE)
    await _drain(ch, [_update(text="cât e ceasul")])
    assert client.methods() == ["sendMessage"]
    assert synth.seen == []


@pytest.mark.asyncio
async def test_always_mode_speaks_a_reply_to_a_typed_question(tmp_path):
    ch, client, _synth = _channel(tmp_path, ALWAYS)
    await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage", "sendChatAction", "sendVoice"]


@pytest.mark.asyncio
async def test_a_silent_turn_does_not_leave_its_voice_mark_for_the_next_typed_one(tmp_path):
    ch, client, synth = _channel(tmp_path, VOICE, silent=True)
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods() == ["sendChatAction"], "nothing was delivered, so nothing was spoken"
    assert ch._voice_turns == set()

    async def handler(text, channel="telegram", **kwargs):
        await ch.send("typed answer", chat_id=kwargs["chat_id"])
        return "typed answer"

    ch.handler = handler
    await _drain(ch, [_update(text="și acum?")])
    assert client.methods()[1:] == ["sendMessage"]
    assert synth.seen == []


@pytest.mark.asyncio
async def test_the_reply_that_answers_the_note_spends_the_mark_so_a_second_message_is_text(tmp_path):
    ch, client, synth = _channel(tmp_path, VOICE)

    async def handler(text, channel="telegram", **kwargs):
        # A job delivery landing in the same chat mid-turn is not the answer to
        # the voice note; only the first reply is.
        await ch.send("the answer", chat_id=kwargs["chat_id"])
        await ch.send("an unrelated delivery", chat_id=kwargs["chat_id"])
        return "the answer"

    ch.handler = handler
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods().count("sendVoice") == 1
    assert synth.seen == [("the answer", "ro")]


@pytest.mark.asyncio
async def test_a_note_nobody_could_read_is_refused_in_text_even_in_voice_mode(tmp_path):
    ch, client, synth = _channel(tmp_path, VOICE)

    async def silence(audio, language):
        return "[silence]"

    ch._voice_reader = InboundVoiceReader(available=True, transcribe=silence)
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods() == ["sendChatAction", "sendMessage"], "the refusal is a line, not a clip"
    assert synth.seen == [] and ch._voice_turns == set()


# ── failure costs the clip, never the text ──────────────────────────────────


@pytest.mark.asyncio
async def test_an_upload_telegram_did_not_acknowledge_is_recorded_as_not_delivered(tmp_path, caplog):
    import logging

    ch, client, _synth = _channel(tmp_path, ALWAYS, statuses={"sendVoice": [500]})
    with caplog.at_level(logging.INFO, logger="jarvis.channels.telegram"):
        await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage", "sendChatAction", "sendVoice"], "only a 400 earns the audio retry"
    assert "spoken reply not delivered" in caplog.text and "'reason': 'send_failed'" in caplog.text
    assert REPLY not in caplog.text and SPOKEN not in caplog.text, "the log carries reasons, never the reply"


@pytest.mark.asyncio
async def test_a_failed_synthesis_still_delivers_the_text_and_sends_no_clip(tmp_path):
    ch, client, _synth = _channel(tmp_path, ALWAYS, synth_fail=True)
    await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage", "sendChatAction"]


@pytest.mark.asyncio
async def test_a_refused_voice_message_is_sent_once_more_as_an_audio_file(tmp_path):
    ch, client, _synth = _channel(tmp_path, ALWAYS, statuses={"sendVoice": [400]})
    await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage", "sendChatAction", "sendVoice", "sendAudio"]
    assert client.calls[3][1]["files"]["audio"][0] == "reply.mp3"


@pytest.mark.asyncio
async def test_a_transport_error_on_the_clip_is_swallowed_and_the_reply_stands(tmp_path):
    ch, client, _synth = _channel(tmp_path, ALWAYS)
    real_post = client.post

    async def post(url, **kw):
        if url.endswith("/sendVoice"):
            raise RuntimeError("network")
        return await real_post(url, **kw)

    client.post = post
    await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage", "sendChatAction"]


@pytest.mark.asyncio
async def test_a_host_without_a_speech_engine_delivers_text_and_never_synthesizes(tmp_path):
    ch, client, synth = _channel(tmp_path, ALWAYS)
    ch._speaker = SpokenReply(synthesize=synth, available=False)
    await _drain(ch, [_update(text="salut")])
    assert client.methods() == ["sendMessage"], "no recording indicator either: the gate answers first"
    assert synth.seen == []


# ── the echo ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_transcript_echo_is_off_by_default(tmp_path):
    ch, client, _synth = _channel(tmp_path, OFF)
    await _drain(ch, [_update(**VOICE_NOTE)])
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts == [to_telegram_html(REPLY)], "exactly the reply, no echo line before it"


@pytest.mark.asyncio
async def test_the_echo_says_what_was_heard_before_the_answer_and_is_never_spoken(tmp_path, monkeypatch):
    monkeypatch.setattr(
        telegram_module, "get_value",
        lambda cat, key, default=None: True if key == "stt_echo_transcripts" else default,
    )
    ch, client, synth = _channel(tmp_path, VOICE)
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert client.methods() == ["sendChatAction", "sendMessage", "sendMessage", "sendChatAction", "sendVoice"]
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts[0] == f"🎙️ I heard: “{SAID}”"
    assert synth.seen == [(SPOKEN, "ro")], "the echo spent neither the mark nor the engine"


# ── the streaming draft ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_streamed_reply_is_spoken_once_its_final_edit_landed(tmp_path):
    ch, client, synth = _channel(tmp_path, ALWAYS)
    draft = TelegramDraft(ch, 42, interval=0)
    await draft.push("Este ")
    await draft.push("ora 10.")
    assert await draft.finish("Este ora 10.") is True
    assert client.methods()[-3:] == ["editMessageText", "sendChatAction", "sendVoice"]
    assert synth.seen == [("Este ora 10.", "ro")]


@pytest.mark.asyncio
async def test_a_draft_that_never_started_speaks_through_send_exactly_once(tmp_path):
    ch, client, synth = _channel(tmp_path, ALWAYS)
    draft = TelegramDraft(ch, 42, interval=0)
    assert await draft.finish("Este ora 10.") is True
    assert client.methods() == ["sendMessage", "sendChatAction", "sendVoice"]
    assert len(synth.seen) == 1
