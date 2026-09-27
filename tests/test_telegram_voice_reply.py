"""A Telegram reply becomes a voice note when the chat asked (H071, the spoken half).

The hook sits where the words are actually delivered — `send()` and the
streaming draft's `finish()` — so the mode can only add audio to a reply that
was already going out as text. What is pinned: off by default; `voice` speaks
only the reply to a voice note and forgets the mark after a silent turn;
`always` speaks every delivered reply; a failed synthesis or a refused upload
costs the clip and never the text; Telegram's 400 on the clip falls back to an
audio file once; the transcript echo, the notice that an attachment could not be
read and the deeplink pairing replies are service lines that are never spoken and
never spend the mark; and only the running turn of the chat takes its mark — a send
from outside that turn (the daily digest, an outbound notice, another chat's turn,
a task or a scheduler job an earlier turn left behind) is never the answer to the
voice note.

Hermetic: a recording HTTP client, an in-memory mode store, an injected
synthesizer and transcriber, no Telegram and no speech stack.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
from types import SimpleNamespace

import pytest

from agents.core import scheduler_service
from agents.core.channels import telegram as telegram_module
from agents.core.channels.inbound_voice import InboundVoiceReader
from agents.core.channels.media_reader import InboundImageReader
from agents.core.channels.outbound import send_to_target
from agents.core.channels.pairing import SenderPairing
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


# ── service lines are never spoken ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unreadable_photo_during_a_voice_turn_is_a_text_notice_and_the_note_keeps_its_voice(tmp_path):
    """/voice voice: while the answer to a voice note is still being worked out, the sender
    sends a photo that cannot be read (no local vision model). The notice saying so is a
    service line: it is not spoken and does not take the note's voice mark, so the note's own
    answer is the one spoken. (It used to be the notice that was spoken, and the answer not.)"""
    ch, client, synth = _channel(tmp_path, VOICE)
    ch._image_reader = InboundImageReader()             # no vision model: every photo is refused
    running, release = asyncio.Event(), asyncio.Event()

    async def handler(text, channel="telegram", **kwargs):
        running.set()
        await release.wait()
        await ch.send(REPLY, chat_id=kwargs["chat_id"])
        return REPLY

    ch.handler = handler
    photo = _update(photo=[{"file_id": "p", "file_unique_id": "u", "width": 1, "height": 1}])
    pages = [(None, [_update(**VOICE_NOTE)]), (running.wait, [photo])]

    async def fake_updates(timeout=25):
        if pages:
            before, page = pages.pop(0)
            if before is not None:
                await asyncio.wait_for(before(), 5)
            return page
        release.set()                                   # the note's turn ends after the photo
        ch._running = False
        return []

    ch._get_updates = fake_updates
    ch._running = True
    await asyncio.wait_for(ch._poll_loop(), 10)
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts[0].startswith("I can see you sent a photo, but ")
    assert texts[1:] == [to_telegram_html(REPLY)]
    assert synth.seen == [(SPOKEN, "ro")], "the note's answer is spoken, the notice is not"
    assert client.methods().count("sendVoice") == 1
    assert ch._voice_turns == set() and ch._voice_pending == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["paired", "invalid", "unwired"])
async def test_a_deeplink_pairing_reply_is_a_service_line_that_is_never_spoken(tmp_path, case):
    """/voice always speaks every reply, but "Paired." and "That pairing link is not valid."
    are service lines sent from the poll loop: text only."""
    ch, client, synth = _channel(tmp_path, ALWAYS)
    ch._pairing = None if case == "unwired" else SenderPairing(tmp_path / "pairing.json")
    token = ch._pairing.mint_deeplink()["token"] if case == "paired" else "not-a-real-token"
    await _drain(ch, [_update(text=f"/start {token}")])
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts == ["Paired. This device can now talk to Nerva." if case == "paired"
                     else "That pairing link is not valid."]
    assert client.methods() == ["sendMessage"]
    assert synth.seen == []


# ── only the running turn of the chat takes its mark ────────────────────────

NEWS = "Good evening. 3 tasks await you."


def _owner_hub(ch, monkeypatch):
    """The orchestrator as the scheduler and outbound.py see it: the owner chat is 42."""
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    return SimpleNamespace(
        autonomy_queue=object(), channels={"telegram": ch},
        get_setting=lambda key, default="": "42" if key == "autonomy.owner_chat_id" else default,
    )


async def _poll(ch, script):
    """Feed *script* — (before, page) per getUpdates call, *before* awaited first when set —
    then stop."""
    async def fake_updates(timeout=25):
        if script:
            before, page = script.pop(0)
            if before is not None:
                await asyncio.wait_for(before(), 5)
            return page
        ch._running = False
        return []

    ch._get_updates = fake_updates
    ch._running = True
    await asyncio.wait_for(ch._poll_loop(), 10)


@pytest.mark.asyncio
@pytest.mark.parametrize("sender", ["the daily digest", "an outbound notice"])
async def test_a_proactive_send_during_a_voice_turn_is_text_and_the_note_keeps_its_voice(
        tmp_path, monkeypatch, sender):
    """/voice voice: while the answer to a voice note is being worked out, the scheduler's
    evening digest (scheduler_service.run_daily_digest) or a non-plain outbound.py notice goes
    to the owner chat, from outside any turn. Neither is the answer to the note: it is text
    only, and the note's own answer is the one spoken. (Either used to take the note's mark:
    the digest was spoken and the answer was not.)"""
    ch, client, synth = _channel(tmp_path, VOICE)
    hub = _owner_hub(ch, monkeypatch)
    monkeypatch.setattr(scheduler_service, "build_evening_retro", lambda queue: NEWS)
    running, release = asyncio.Event(), asyncio.Event()

    async def handler(text, channel="telegram", **kwargs):
        running.set()
        await release.wait()
        await ch.send(REPLY, chat_id=kwargs["chat_id"])
        return REPLY

    async def proactive():
        await running.wait()
        if sender == "the daily digest":
            assert await scheduler_service.SchedulerService(hub).run_daily_digest("evening") is None
        else:
            assert (await send_to_target(hub, "telegram", NEWS))["ok"] is True
        release.set()

    ch.handler = handler
    await _poll(ch, [(None, [_update(**VOICE_NOTE)]), (proactive, [])])
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts == [NEWS, to_telegram_html(REPLY)]
    assert synth.seen == [(SPOKEN, "ro")], f"spoken: {synth.seen}"
    assert ch._voice_turns == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("sender", ["another chat's turn", "a task an earlier turn left running"])
async def test_only_the_running_turn_of_the_chat_takes_its_voice_mark(tmp_path, sender):
    """/voice voice, a voice note's turn running in chat 42. A turn in chat 43 that tells the
    owner chat something, or a task an earlier (typed) turn of chat 42 created and that sends
    only now, is not the answer to the note: text only, and the note's answer is spoken. A
    task inherits the context of the turn that made it, so the mark is taken only while that
    turn is still running."""
    ch, client, synth = _channel(tmp_path, VOICE)
    running, release, later = asyncio.Event(), asyncio.Event(), asyncio.Event()
    leftovers = []

    async def handler(text, channel="telegram", **kwargs):
        if kwargs["chat_id"] == 43:
            await ch.send(NEWS, chat_id=42)
            return None
        if text == "remind me":
            async def remind():
                await later.wait()
                await ch.send(NEWS, chat_id=42)

            leftovers.append(asyncio.create_task(remind()))
            await ch.send("ok", chat_id=42)
            return "ok"
        running.set()
        await release.wait()
        await ch.send(REPLY, chat_id=42)
        return REPLY

    async def news_sent():
        while NEWS not in [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]:
            await asyncio.sleep(0.005)
        release.set()

    async def the_leftover_sends():
        await running.wait()
        later.set()
        await leftovers[0]
        release.set()

    ch.handler = handler
    if sender == "another chat's turn":
        script = [(None, [_update(**VOICE_NOTE)]),
                  (running.wait, [_update(chat_id=43, uid=43, text="status?")]),
                  (news_sent, [])]
    else:
        script = [(None, [_update(text="remind me")]), (None, [_update(**VOICE_NOTE)]),
                  (the_leftover_sends, [])]
    await _poll(ch, script)
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert NEWS in texts and texts[-1] == to_telegram_html(REPLY)
    assert synth.seen == [(SPOKEN, "ro")], f"spoken: {synth.seen}"
    assert ch._voice_turns == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["awaited", "a task", "a worker thread", "a streamed draft",
                                  "a draft that never started"])
async def test_the_notes_answer_is_spoken_on_every_path_its_turn_sends_it(tmp_path, path):
    """The mark goes with the turn's context: a reply sent from a task the turn created, from a
    worker thread the turn started with that context (asyncio.to_thread copies it), or as a
    streaming draft's final text is still the answer to the note."""
    ch, client, synth = _channel(tmp_path, VOICE)
    loop = asyncio.get_running_loop()

    async def handler(text, channel="telegram", **kwargs):
        cid = kwargs["chat_id"]
        if path == "awaited":
            await ch.send(REPLY, chat_id=cid)
        elif path == "a task":
            await asyncio.create_task(ch.send(REPLY, chat_id=cid))
        elif path == "a worker thread":
            await asyncio.to_thread(
                lambda: asyncio.run_coroutine_threadsafe(ch.send(REPLY, chat_id=cid), loop).result(5))
        else:
            draft = ch.begin_stream(chat_id=cid)
            if path == "a streamed draft":
                await draft.push("**Este** ora 10.")
            assert await draft.finish(REPLY) is True
        return REPLY

    ch.handler = handler
    await _drain(ch, [_update(**VOICE_NOTE)])
    assert synth.seen == [(SPOKEN, "ro")], f"spoken: {synth.seen}"
    assert client.methods().count("sendVoice") == 1
    assert ch._voice_turns == set()


@pytest.mark.asyncio
async def test_a_plain_notice_the_turn_itself_sends_leaves_the_mark_to_its_answer(tmp_path, monkeypatch):
    """/voice voice: inside the voice note's own turn, a plain outbound notice to the owner chat
    (outbound.py sends it with ``voice=False``) goes first. A ``voice=False`` send never takes the
    mark, even from inside the turn: the answer that follows is the one spoken."""
    ch, client, synth = _channel(tmp_path, VOICE)
    hub = _owner_hub(ch, monkeypatch)

    async def handler(text, channel="telegram", **kwargs):
        assert (await send_to_target(hub, "telegram", NEWS, plain=True))["ok"] is True
        await ch.send(REPLY, chat_id=kwargs["chat_id"])
        return REPLY

    ch.handler = handler
    await _drain(ch, [_update(**VOICE_NOTE)])
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts == [NEWS, to_telegram_html(REPLY)]
    assert synth.seen == [(SPOKEN, "ro")], f"spoken: {synth.seen}"


@pytest.mark.asyncio
async def test_a_turn_on_one_bot_never_takes_the_voice_mark_of_the_same_chat_on_another(tmp_path):
    """Two Telegram channels (two bots) can see the same chat id. A turn running on the first
    that sends to that chat through the second is not the second's turn: its voice mark stays
    for its own turn's answer."""
    first, _client, _synth = _channel(tmp_path, VOICE)
    second, second_client, second_synth = _channel(tmp_path, VOICE)
    second._voice_turns.add(42)                        # a voice note's turn of the second bot

    async def handler(text, channel="telegram", **kwargs):
        await second.send(NEWS, chat_id=42)
        return None

    first.handler = handler
    await first._run_turn(42, 42, "status?")
    assert second_synth.seen == [] and 42 in second._voice_turns
    assert [m for m, _ in second_client.calls] == ["sendMessage"]


@pytest.mark.asyncio
async def test_a_job_an_ended_voice_turn_armed_never_takes_a_later_voice_turns_mark(tmp_path, monkeypatch):
    """/voice voice. A voice note's turn arms a job on a real AsyncIOScheduler (as /remind does:
    ``add_job``, then ``wakeup``). APScheduler runs its wakeup through
    ``loop.call_soon_threadsafe`` and re-arms its timer with ``loop.call_later``; both copy the
    turn's context, so the task the job later runs in carries that turn's scope. The turn
    answers and ends. The job fires while a second voice note's turn is still working: the
    first turn's scope is closed and answers nothing, so the job's digest is text only and the
    second note's own answer is the one spoken."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    ch, client, synth = _channel(tmp_path, VOICE)
    hub = _owner_hub(ch, monkeypatch)
    monkeypatch.setattr(scheduler_service, "build_evening_retro", lambda queue: NEWS)
    service = scheduler_service.SchedulerService(hub)
    sched = AsyncIOScheduler()
    sched.start()
    second_running, digest_sent = asyncio.Event(), asyncio.Event()
    turns = []

    async def armed_by_the_first_turn():
        await second_running.wait()
        await service.run_daily_digest("evening")
        digest_sent.set()

    async def handler(text, channel="telegram", **kwargs):
        turns.append(text)
        if len(turns) == 1:
            sched.add_job(armed_by_the_first_turn, "date", id="reminder",
                          run_date=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=0.1))
        else:
            second_running.set()
            await asyncio.wait_for(digest_sent.wait(), 5)     # still working when the job sends
        await ch.send(REPLY, chat_id=kwargs["chat_id"])
        return REPLY

    ch.handler = handler
    try:
        await _poll(ch, [(None, [_update(**VOICE_NOTE)]), (None, [_update(**VOICE_NOTE)]),
                         (digest_sent.wait, [])])
    finally:
        sched.shutdown(wait=False)
    texts = [c["json"]["text"] for m, c in client.calls if m == "sendMessage"]
    assert texts == [to_telegram_html(REPLY), NEWS, to_telegram_html(REPLY)]
    assert synth.seen == [(SPOKEN, "ro"), (SPOKEN, "ro")], f"spoken: {synth.seen}"
    assert client.methods().count("sendVoice") == 2
    assert ch._voice_turns == set()


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
