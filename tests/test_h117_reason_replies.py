"""H117 with the decision inbox wired: a Telegram reply is batched unless it answers a
decision-reason prompt.

H487 lets the owner answer a rejection's reason prompt by replying to it. The hook it added
(``TelegramChannel.on_decision_reason``, set by ``AutonomyCoordinator.wire`` whenever a bot and
an owner chat are configured) used to take EVERY text reply out of H117's batching: the sender's
held pieces were flushed and the reply ran on its own, even when the hook declined it. A split
reply, or a question sent as a reply to its photo, became two turns; an observed group reply no
longer let what was said before it go first; a group reply to the bot jumped ahead of another
member's earlier held question.

Now only a reply the decision inbox claims leaves the batching path. The poll loop asks
``TelegramChannel.decision_reason_pending`` (``AutonomyCoordinator.would_consume_reason_reply``),
which answers without side effects; a claimed reply is handled in its chat's lane, after
everything held for that chat, where the inbox saves the reason and acknowledges it. So the
acknowledgement keeps the chat's order, never holds the poll loop or another chat, is never
spoken, and a tap read before the reply still supersedes the prompt it answers. The reason window
is judged by the reply's stamp: the instant its getUpdates page came back (on the coordinator's
clock, handed to the channel as ``decision_reason_clock``), moved back by Telegram's own date for
the message but never before the previous page came back (a page cut short by an error is not
the previous page of the updates that come again). So neither a slow turn ahead of it in the
lane nor the poll loop reading an earlier update expires a reason the owner sent in time, as far
as the host's clock and Telegram's agree (see ``TelegramChannel._reason_arrival``), and a reply
stamped late stays late; no date Telegram sends makes the stamp raise. Every other reply is
queued, merged and flushed as if the hook were not wired, and a failing hook never loses the
reply. While a reason prompt is still on its way to a chat (its message id not yet known), a
reply in that chat is classified behind it in the chat's lane too. These cases run on the real
poll loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels import voice_mode
from agents.core.channels.group_policy import GroupPolicy
from agents.core.channels.spoken_reply import Audio
from agents.core.channels.telegram import TelegramChannel, _is_instant

BOT = 999
OWNER = 99
PROMPT = 77
_ids = itertools.count(1000)


def _msg(text, *, chat_id=42, uid=7, chat_type="private", **extra):
    return {"update_id": next(_ids), "message": {
        "message_id": next(_ids), "from": {"id": uid}, "chat": {"id": chat_id, "type": chat_type},
        "text": text, **extra}}


def _reply(message_id, author=BOT):
    return {"reply_to_message": {"message_id": message_id, "from": {"id": author}}}


def _tap(task_id, *, chat_id=42, uid=OWNER):
    return {"update_id": next(_ids), "callback_query": {
        "id": f"cb{next(_ids)}", "from": {"id": uid}, "data": f"aut:{task_id}:reject",
        "message": {"chat": {"id": chat_id}}}}


def _channel(monkeypatch, *, policy=None):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "60")
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MAX_MS", "200")
    received = []

    async def handler(text, channel="telegram", **kwargs):
        received.append((text, kwargs))
        return "ok"

    channel = TelegramChannel(token="t", handler=handler, group_policy=policy)
    channel._bot_id, channel._bot_username = BOT, "nerva_bot"
    return channel, received


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.005)


async def _run(channel, script):
    """Feed ``script`` — (before, updates) per getUpdates call, where *before* is a delay or
    a coroutine function awaited first — then stop once nothing is held."""
    async def fake_updates(timeout=25):
        if script:
            before, batch = script.pop(0)
            if callable(before):
                await asyncio.wait_for(before(), 5)
            elif before:
                await asyncio.sleep(before)
            return batch
        if not len(channel._batch):
            channel._running = False
        return []

    channel._get_updates = fake_updates
    channel._running = True
    await asyncio.wait_for(channel._poll_loop(), 10)


def _answering(channel, received, *, slow=None):
    """The orchestrator's stand-in: each turn is answered in its chat. The turn whose text is
    *slow* sets ``running`` and waits for ``release`` before it answers."""
    running, release = asyncio.Event(), asyncio.Event()

    async def handler(text, channel_name="telegram", **kwargs):
        kwargs.pop("channel", None)
        received.append((text, kwargs))
        if text == slow:
            running.set()
            await release.wait()
        await channel.send(f"answer to {text}", chat_id=kwargs["chat_id"])
        return "ok"

    channel.handler = handler
    return running, release


def _said(inbox):
    """What went out as chat messages: answers and the inbox's acknowledgements."""
    return [p for p in inbox.posted if p and (
        p.startswith("answer to ") or p == "Reason saved." or p.startswith("That reason"))]


class _Inbox:
    """The real decision inbox wired to the channel by ``AutonomyCoordinator.wire``, with
    Telegram's API answered in process. A reason prompt's response can be held back."""

    def __init__(self, channel, tmp_path, owner_chat, *, hold_prompt=False, hold_ack=False):
        self.channel = channel
        self.queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
        self.worker = AutonomyWorker(self.queue)
        self.posted = []
        self.prompts = 0
        self.prompt_visible = asyncio.Event()
        self.prompt_response = asyncio.Event()
        if not hold_prompt:
            self.prompt_response.set()
        # "Reason saved." can be held on its way too (a slow Telegram answer).
        self.ack_started, self.ack_release = asyncio.Event(), asyncio.Event()
        if not hold_ack:
            self.ack_release.set()
        orch = SimpleNamespace(
            autonomy=self.worker, autonomy_queue=self.queue, channels={"telegram": channel},
            get_setting=lambda key, default="": str(owner_chat) if key == "autonomy.owner_chat_id" else default,
        )
        self.coordinator = AutonomyCoordinator(orch)

    async def __aenter__(self):
        await self.channel.client.aclose()
        self.channel.client = httpx.AsyncClient(transport=httpx.MockTransport(self._api))
        self.coordinator.wire()
        assert self.channel.on_decision_reason == self.coordinator._on_reason_reply
        return self

    async def __aexit__(self, *exc):
        self.prompt_response.set()
        self.ack_release.set()
        await self.channel.client.aclose()
        self.queue.close()

    async def _api(self, request):
        body = json.loads(request.content)
        self.posted.append(body.get("text"))
        if body.get("reply_markup", {}).get("force_reply") is True:
            self.prompt_visible.set()
            await self.prompt_response.wait()
            prompt, self.prompts = PROMPT + self.prompts, self.prompts + 1   # 77, then 78, ...
            return httpx.Response(200, json={"ok": True, "result": {"message_id": prompt}})
        if body.get("text") == "Reason saved.":
            self.ack_started.set()
            await self.ack_release.wait()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    async def task(self):
        task = await self.worker.submit("jarvis", "delete_file", "Delete test file", attention_mode="none")
        return task.id

    def reason(self, task_id):
        return self.queue.get(task_id).human_decision["reason"]

    async def registered(self):
        await _until(lambda: self.coordinator._reason_windows)


# ── a reply the hook declines is an ordinary H117 piece ─────────────────────────

@pytest.fixture(params=["stub", "coordinator"])
def declining(request, tmp_path):
    """Wire the reason hook so it declines: a stub answering False (as the probe did), or
    the real inbox with no reason prompt open (the owner chat is the one under test)."""
    async def wire(channel, owner_chat):
        if request.param == "stub":
            asked = []

            async def not_a_reason(text, **kwargs):
                asked.append(text)
                return False

            channel.on_decision_reason = not_a_reason
            return None
        inbox = _Inbox(channel, tmp_path, owner_chat)
        return await inbox.__aenter__()

    return wire


async def test_a_split_reply_is_one_turn(monkeypatch, declining):
    channel, received = _channel(monkeypatch)
    inbox = await declining(channel, 42)
    try:
        await _run(channel, [(0, [_msg("first half of a long reply", **_reply(500)),
                                  _msg("second half of it")])])
    finally:
        if inbox:
            await inbox.__aexit__()
    assert received == [("first half of a long reply\nsecond half of it", {"chat_id": 42, "sender": "7"})]


async def test_a_photo_and_its_question_sent_as_a_reply_to_it_are_one_turn(monkeypatch, declining):
    channel, received = _channel(monkeypatch)
    inbox = await declining(channel, 42)

    async def read(attachment, spoken, chat_id, uid):
        return ("[photo: a cat]", "")

    monkeypatch.setattr(channel, "_read_attachment", read)
    photo = _msg("", photo=[{"file_id": "f1", "file_unique_id": "u1", "width": 10, "height": 10}])
    photo["message"].pop("text")
    question = _msg("what is this?", **_reply(photo["message"]["message_id"], author=7))
    try:
        await _run(channel, [(0, [photo, question])])
    finally:
        if inbox:
            await inbox.__aexit__()
    assert [t for t, _ in received] == ["[photo: a cat]\nwhat is this?"]


async def test_an_observed_group_reply_lets_everything_said_before_it_go_first(monkeypatch, declining):
    channel, received = _channel(monkeypatch, policy=GroupPolicy(observe_mode=True))
    inbox = await declining(channel, -5)
    try:
        await _run(channel, [(0, [_msg("@nerva_bot hi", chat_id=-5, chat_type="supergroup"),
                                  _msg("hello everyone", chat_id=-5, chat_type="supergroup", uid=8,
                                       **_reply(77, author=55))])])
    finally:
        if inbox:
            await inbox.__aexit__()
    assert [(t, "observe_only" in kw) for t, kw in received] == [("hi", False), ("hello everyone", True)]


async def test_a_group_reply_to_the_bot_waits_behind_another_members_earlier_question(monkeypatch, declining):
    channel, received = _channel(monkeypatch, policy=GroupPolicy())
    inbox = await declining(channel, -5)
    try:
        await _run(channel, [(0, [
            _msg("@nerva_bot first question", chat_id=-5, chat_type="supergroup", uid=1),
            _msg("and my follow-up to your answer", chat_id=-5, chat_type="supergroup", uid=2,
                 **_reply(90)),
        ])])
    finally:
        if inbox:
            await inbox.__aexit__()
    assert [(kw["sender"], t) for t, kw in received] == [
        ("1", "first question"), ("2", "and my follow-up to your answer")]


async def test_a_failing_reason_hook_never_loses_the_reply(monkeypatch):
    channel, received = _channel(monkeypatch)

    async def broken(text, **kwargs):
        raise RuntimeError("inbox offline")

    channel.on_decision_reason = broken
    await _run(channel, [(0, [_msg("first half of a long reply", **_reply(500)),
                              _msg("second half of it")])])
    assert [t for t, _ in received] == ["first half of a long reply\nsecond half of it"]


# ── a reply that answers a reason prompt is the reason, never a turn ────────────

async def test_a_reply_to_the_reason_prompt_is_the_reason_and_no_turn(monkeypatch, tmp_path):
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()
        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
        ])
        assert inbox.reason(task_id) == "Use staging"
        assert inbox.queue.get(task_id).status == "rejected"
    assert received == []
    assert "Reason saved." in inbox.posted


async def test_a_consumed_reason_goes_after_what_the_owner_said_before_it(monkeypatch, tmp_path):
    """The reason is handled in the chat's lane, so what the owner said before it is handed
    over first and answered first; what they say after it is a turn of its own. (Round 1
    consumed the reason in the poll loop and merged the two around it; round 2 keeps lane
    order instead, so the acknowledgement never overtakes the chat.)"""
    channel, received = _channel(monkeypatch)
    _answering(channel, received)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()
        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("thanks, and", uid=OWNER),
                                _msg("Use staging", uid=OWNER, **_reply(PROMPT)),
                                _msg("what is next?", uid=OWNER)]),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert received == [("thanks, and", {"chat_id": 42, "sender": str(OWNER)}),
                        ("what is next?", {"chat_id": 42, "sender": str(OWNER)})]
    assert _said(inbox) == ["answer to thanks, and", "Reason saved.", "answer to what is next?"]


async def test_only_the_owner_in_the_owner_chat_answers_the_prompt(monkeypatch, tmp_path):
    """Another member's reply to the prompt, and the owner's reply from another chat, are
    ordinary pieces (batched with what follows them); the owner's own reply is the reason."""
    group = -100
    channel, received = _channel(monkeypatch, policy=GroupPolicy())
    async with _Inbox(channel, tmp_path, group) as inbox:
        task_id = await inbox.task()
        await _run(channel, [
            (0, [_tap(task_id, chat_id=group)]),
            (inbox.registered, [
                _msg("not mine to answer", chat_id=group, chat_type="supergroup", uid=100, **_reply(PROMPT)),
                _msg("but here is more", chat_id=group, chat_type="supergroup", uid=100, **_reply(500)),
                _msg("wrong chat", chat_id=43, uid=OWNER, **_reply(PROMPT)),
                _msg("still the wrong chat", chat_id=43, uid=OWNER),
            ]),
            (0.3, []),
        ])
        assert inbox.reason(task_id) is None
        assert inbox.coordinator._reason_windows          # the prompt is still open
        await _run(channel, [(0, [
            _msg("Use staging", chat_id=group, chat_type="supergroup", uid=OWNER, **_reply(PROMPT))])])
        assert inbox.reason(task_id) == "Use staging"
    assert sorted((kw["chat_id"], kw["sender"], t) for t, kw in received) == [
        (group, "100", "not mine to answer\nbut here is more"),
        (43, str(OWNER), "wrong chat\nstill the wrong chat"),
    ]


# ── while a reason prompt is on its way ─────────────────────────────────────────

async def test_a_reply_while_the_prompt_is_on_its_way_waits_behind_the_chats_earlier_words(monkeypatch, tmp_path):
    """The prompt's id is unknown until Telegram answers, so a reply in its chat is classified
    behind it in the lane; what another member said before that reply still goes first, and
    another chat's burst is not cut by it."""
    group = -100
    channel, received = _channel(monkeypatch, policy=GroupPolicy())
    async with _Inbox(channel, tmp_path, group, hold_prompt=True) as inbox:
        task_id = await inbox.task()

        async def release():
            inbox.prompt_response.set()

        await _run(channel, [
            (0, [_tap(task_id, chat_id=group)]),
            (inbox.prompt_visible.wait, [
                _msg("elsewhere, part one", chat_id=43, uid=5),
                _msg("@nerva_bot first question", chat_id=group, chat_type="supergroup", uid=1),
                _msg("my own follow-up", chat_id=group, chat_type="supergroup", uid=OWNER, **_reply(500)),
                _msg("and part two", chat_id=43, uid=5),
            ]),
            (release, []),
        ])
        assert inbox.reason(task_id) is None
    assert [(kw["sender"], t) for t, kw in received if kw["chat_id"] == group] == [
        ("1", "first question"), (str(OWNER), "my own follow-up")]
    assert [t for t, kw in received if kw["chat_id"] == 43] == ["elsewhere, part one\nand part two"]


async def test_a_reply_in_another_chat_while_a_prompt_is_on_its_way_is_batched(monkeypatch, tmp_path):
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42, hold_prompt=True) as inbox:
        task_id = await inbox.task()

        async def release():
            inbox.prompt_response.set()

        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.prompt_visible.wait, [_msg("first half of a long reply", chat_id=43, **_reply(500)),
                                         _msg("second half of it", chat_id=43)]),
            (0.3, []),
            (release, []),
        ])
    assert [(kw["chat_id"], t) for t, kw in received] == [(43, "first half of a long reply\nsecond half of it")]


# ── round 2: decided at poll time without side effects, handled in the chat's lane ──

def _speaking(channel, mode):
    """Put the chat in voice *mode*; returns the list of texts that were spoken."""
    spoken = []
    channel._voice_modes = SimpleNamespace(get=lambda _channel, _chat: mode)

    async def speak(chat_id, text):
        spoken.append(text)
        return Audio(True, data=b"ogg", mime="audio/ogg")

    async def send_voice(chat_id, audio):
        return True

    channel._speak, channel._send_voice = speak, send_voice
    return spoken


def _voice_note(uid=OWNER, chat_id=42):
    note = _msg("", chat_id=chat_id, uid=uid, voice={"file_id": "v1", "file_unique_id": "u1", "duration": 2})
    note["message"].pop("text")
    return note


async def test_a_reason_given_during_a_voice_turn_leaves_that_turn_its_spoken_answer(monkeypatch, tmp_path):
    """/voice voice: the owner asks by voice note, then types the reason while that turn runs.
    The answer to the voice note is the one spoken; "Reason saved." is a text service line."""
    channel, received = _channel(monkeypatch)
    running, release = _answering(channel, received, slow="[voice] what is next?")
    spoken = _speaking(channel, voice_mode.VOICE)

    async def read(attachment, text, chat_id, uid):
        channel._voice_pending.add((chat_id, str(uid)))        # as the voice reader does
        return ("[voice] what is next?", "")

    monkeypatch.setattr(channel, "_read_attachment", read)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()

        async def release_soon():
            await asyncio.sleep(0.05)
            release.set()

        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_voice_note()]),
            (0.1, []),                                          # the note's turn starts
            (running.wait, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (release_soon, []),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert [t for t, _ in received] == ["[voice] what is next?"]
    assert spoken == ["answer to [voice] what is next?"]
    assert _said(inbox) == ["answer to [voice] what is next?", "Reason saved."]


async def test_a_reason_acknowledgement_is_never_spoken(monkeypatch, tmp_path):
    """/voice always speaks every reply, but the inbox's acknowledgements are service lines."""
    channel, received = _channel(monkeypatch)
    spoken = _speaking(channel, voice_mode.ALWAYS)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()
        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (0.1, [_msg("Replace it", uid=OWNER, **_reply(PROMPT))]),
            (0.1, []),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert received == []
    assert _said(inbox) == ["Reason saved.", "That reason prompt is no longer active; no decision changed."]
    assert spoken == []


async def test_a_slow_reason_acknowledgement_never_holds_another_chat(monkeypatch, tmp_path):
    """"Reason saved." is held on its way (a slow Telegram answer). Meanwhile another chat's
    held piece still goes out when its window closes, and a message read after the reason
    (another chat, same page) is read and answered: neither waits for the acknowledgement."""
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42, hold_ack=True) as inbox:
        task_id = await inbox.task()
        while_held = []

        async def watch():
            await asyncio.wait_for(inbox.ack_started.wait(), 2)
            with contextlib.suppress(TimeoutError):          # red: the loop is held
                await asyncio.wait_for(
                    _until(lambda: {43, 44} <= {kw["chat_id"] for _, kw in received}), 1)
            while_held.extend(sorted(kw["chat_id"] for _, kw in received))
            inbox.ack_release.set()

        watcher = asyncio.ensure_future(watch())
        try:
            await _run(channel, [
                (0, [_tap(task_id)]),
                (inbox.registered, [_msg("other chat, part one", chat_id=43, uid=5)]),
                (0.02, [_msg("Use staging", uid=OWNER, **_reply(PROMPT)),
                        _msg("other chat, other sender", chat_id=44, uid=6)]),
            ])
        finally:
            await asyncio.wait_for(watcher, 5)
        assert inbox.reason(task_id) == "Use staging"
    assert while_held == [43, 44]
    assert sorted((kw["chat_id"], t) for t, kw in received) == [
        (43, "other chat, part one"), (44, "other chat, other sender")]
    assert "Reason saved." in inbox.posted


async def test_the_reason_acknowledgement_follows_the_answer_the_chat_was_already_waiting_for(monkeypatch, tmp_path):
    channel, received = _channel(monkeypatch)
    running, release = _answering(channel, received, slow="is the backup done?")
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()

        async def release_soon():
            await asyncio.sleep(0.05)
            release.set()

        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("is the backup done?", uid=OWNER)]),
            (0.1, []),                                          # that turn starts
            (running.wait, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (release_soon, []),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert [t for t, _ in received] == ["is the backup done?"]
    assert _said(inbox) == ["answer to is the backup done?", "Reason saved."]


async def test_a_tap_read_before_a_reply_supersedes_the_prompt_that_reply_answers(monkeypatch, tmp_path):
    """One getUpdates page: the owner rejects a second task, then replies to the first task's
    prompt. The tap runs first (lane order), so that prompt is no longer active: the reply is
    refused, lands on neither task and is no chat turn, whatever the lane was doing."""
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        first, second = await inbox.task(), await inbox.task()
        await _run(channel, [
            (0, [_tap(first)]),
            (inbox.registered, [_tap(second), _msg("Old reason for the first", uid=OWNER, **_reply(PROMPT))]),
            (0.1, []),
        ])
        assert (inbox.reason(first), inbox.reason(second)) == (None, None)
        assert inbox.coordinator._reason_windows[("42", str(OWNER))]["prompt"] == PROMPT + 1
        prompt_for_second = next(i for i, p in enumerate(inbox.posted)
                                 if p and p.startswith(f"Task #{second} rejected."))
        refused = inbox.posted.index("That reason prompt is no longer active; no decision changed.")
    assert received == []
    assert refused > prompt_for_second
    assert "Reason saved." not in inbox.posted


@pytest.mark.parametrize("fault", ["acknowledgement", "audit"])
async def test_a_failure_after_the_reason_is_saved_never_runs_it_as_a_turn(monkeypatch, tmp_path, fault):
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()

        async def registered_then_break():
            await inbox.registered()
            if fault == "acknowledgement":
                real_send = channel.send

                async def send(text, **kwargs):
                    if text == "Reason saved.":
                        raise RuntimeError("transport broke after the save")
                    return await real_send(text, **kwargs)

                monkeypatch.setattr(channel, "send", send)
            else:
                def audit(*args, **kwargs):
                    raise RuntimeError("audit sink down after the save")

                monkeypatch.setattr(inbox.worker, "_audit", audit)

        await _run(channel, [
            (0, [_tap(task_id)]),
            (registered_then_break, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (0.1, []),
        ])
        assert inbox.reason(task_id) == "Use staging"
        assert not inbox.coordinator._reason_windows
    assert received == []
    if fault == "audit":
        assert "Reason saved." in inbox.posted


@pytest.mark.parametrize("inbox_says", ["declines", "raises"])
async def test_a_claimed_reply_the_inbox_then_turns_down_runs_as_a_turn_in_its_lane(monkeypatch, inbox_says):
    """Claimed at poll time, but in the lane the inbox no longer takes it (its window closed
    meanwhile) or fails before saving anything: the reply runs as its own turn, after what
    the chat said before it and before what it says next. Never lost, never merged."""
    channel, received = _channel(monkeypatch)
    asked = []
    channel.decision_reason_pending = lambda **kwargs: True

    async def inbox(text, **kwargs):
        asked.append(text)
        if inbox_says == "raises":
            raise RuntimeError("inbox offline")
        return False

    channel.on_decision_reason = inbox
    await _run(channel, [(0, [_msg("before it"), _msg("Use staging", **_reply(PROMPT)), _msg("after it")])])
    assert asked == ["Use staging"]
    assert [t for t, _ in received] == ["before it", "Use staging", "after it"]


async def test_a_failing_reason_predicate_leaves_the_reply_an_ordinary_piece(monkeypatch):
    """The poll loop decides with the side-effect-free predicate alone; the hook that saves
    and acknowledges is never run from the poll loop. A predicate that raises claims nothing."""
    channel, received = _channel(monkeypatch)
    asked = []

    def broken(**kwargs):
        raise RuntimeError("inbox offline")

    async def would_consume(text, **kwargs):
        asked.append(text)
        return True

    channel.decision_reason_pending = broken
    channel.on_decision_reason = would_consume
    await _run(channel, [(0, [_msg("first half of a long reply", **_reply(500)),
                              _msg("second half of it")])])
    assert asked == []
    assert [t for t, _ in received] == ["first half of a long reply\nsecond half of it"]


async def test_wire_hands_the_channel_the_side_effect_free_predicate(monkeypatch, tmp_path):
    channel, _ = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        assert channel.decision_reason_pending == inbox.coordinator.would_consume_reason_reply
        assert channel.decision_reason_clock == inbox.coordinator.reason_clock
        inbox.coordinator._reason_clock = lambda: 12.5          # read live, never copied at wire
        assert channel.decision_reason_clock() == 12.5


# ── round 3: the reason window is judged when the reply arrived ─────────────────

EXPIRED = "The reason window expired; the rejection is unchanged."


@pytest.mark.parametrize("replied_at, saved", [(1060.0, True), (1130.0, False)])
async def test_a_reason_is_judged_by_when_it_arrived_not_when_the_chats_lane_reaches_it(
        monkeypatch, tmp_path, replied_at, saved):
    """The prompt opens at t=1000, so its window ends at 1120. The owner asks a slow question,
    then replies to the prompt at *replied_at* while that turn runs; the turn ends at t=1150 and
    only then does the lane reach the reply. It is judged at the instant the poll loop claimed it,
    on the coordinator's clock: 60 s in, it is saved; 130 s in, it is refused as expired, though
    it waited in the same lane. Either way it follows the answer the chat was waiting for and is
    never a chat turn. (Round 2 judged it when the lane reached it: "expired" for both.)"""
    channel, received = _channel(monkeypatch)
    running, release = _answering(channel, received, slow="is the backup done?")
    clock = [1000.0]
    async with _Inbox(channel, tmp_path, 42) as inbox:
        inbox.coordinator._reason_clock = lambda: clock[0]
        task_id = await inbox.task()

        async def owner_replies():
            await running.wait()
            clock[0] = replied_at

        async def the_turn_ends_late():
            await asyncio.sleep(0.05)
            clock[0] = 1150.0
            release.set()

        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("is the backup done?", uid=OWNER)]),
            (0.1, []),                                          # that turn starts
            (owner_replies, [_msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (the_turn_ends_late, []),
            (0.1, []),
        ])
        assert inbox.reason(task_id) == ("Use staging" if saved else None)
        assert inbox.queue.get(task_id).status == "rejected"
        assert not inbox.coordinator._reason_windows
    assert [t for t, _ in received] == ["is the backup done?"]
    assert [p for p in inbox.posted if p in ("answer to is the backup done?", "Reason saved.", EXPIRED)] == [
        "answer to is the backup done?", "Reason saved." if saved else EXPIRED]


async def test_another_members_rejection_handled_after_the_deadline_never_drops_a_reason_sent_in_time(
        monkeypatch, tmp_path):
    """A group owner chat (no allowed-user list: every member counts as the owner). The owner's
    prompt opens at t=1000 (window to 1120) and they ask a slow question. At t=1050 another member
    rejects a second task; at t=1060 the owner replies to their prompt. Both wait in the chat's
    lane behind the slow turn, which ends at t=1150: the member's rejection opens its own window
    then, and must not prune the owner's window as expired, since their reply arrived in time."""
    group = -100
    channel, received = _channel(monkeypatch, policy=GroupPolicy())
    running, release = _answering(channel, received, slow="is the backup done?")
    clock = [1000.0]
    async with _Inbox(channel, tmp_path, group) as inbox:
        inbox.coordinator._reason_clock = lambda: clock[0]
        first, second = await inbox.task(), await inbox.task()

        async def member_rejects():
            await running.wait()
            clock[0] = 1050.0

        async def owner_replies():
            clock[0] = 1060.0

        async def the_turn_ends_late():
            await asyncio.sleep(0.05)
            clock[0] = 1150.0
            release.set()

        await _run(channel, [
            (0, [_tap(first, chat_id=group)]),
            (inbox.registered, [_msg("@nerva_bot is the backup done?", chat_id=group,
                                     chat_type="supergroup", uid=OWNER)]),
            (0.1, []),                                          # that turn starts
            (member_rejects, [_tap(second, chat_id=group, uid=100)]),
            (owner_replies, [_msg("Use staging", chat_id=group, chat_type="supergroup", uid=OWNER,
                                  **_reply(PROMPT))]),
            (the_turn_ends_late, []),
            (0.2, []),
        ])
        assert inbox.reason(first) == "Use staging"
        assert inbox.reason(second) is None
        assert list(inbox.coordinator._reason_windows) == [(str(group), "100")]
    assert [t for t, _ in received] == ["is the backup done?"]
    assert "Reason saved." in inbox.posted


@pytest.mark.parametrize("clock", [None, 5.0, "raises", "reads no instant"])
async def test_the_hook_is_told_when_the_reply_arrived_only_by_a_wired_clock(monkeypatch, clock):
    """With a clock wired, the hook gets ``received_at``: here the clock's reading when the reply's
    getUpdates page came back (it carries no Telegram date to credit). With none (or one that
    fails) it is called exactly as before, so an older hook that takes no ``received_at`` still
    consumes the replies it claims, and the inbox judges such a reply when it runs. A clock that
    reads no instant (NaN) counts as failed."""
    channel, received = _channel(monkeypatch)
    seen = []
    channel.decision_reason_pending = lambda **kwargs: True
    if clock == "raises":
        def broken():
            raise RuntimeError("clock offline")

        channel.decision_reason_clock = broken
    elif clock == "reads no instant":
        channel.decision_reason_clock = lambda: float("nan")
    elif clock is not None:
        channel.decision_reason_clock = lambda: clock

    async def older_hook(text, *, chat_id, user_id, reply_to_message_id):
        seen.append({"chat_id": chat_id, "user_id": user_id, "reply_to_message_id": reply_to_message_id})
        return True

    async def hook(text, **kwargs):
        seen.append(kwargs)
        return True

    channel.on_decision_reason = hook if clock == 5.0 else older_hook
    await _run(channel, [(0, [_msg("Use staging", **_reply(PROMPT))])])
    expected = {"chat_id": 42, "user_id": 7, "reply_to_message_id": PROMPT}
    assert seen == [{**expected, "received_at": 5.0} if clock == 5.0 else expected]
    assert received == []


async def test_a_reply_read_while_its_prompt_posts_is_judged_by_its_stamp_behind_a_slow_turn(
        monkeypatch, tmp_path):
    """The owner's question and their reply to the prompt come in one page while the prompt is
    still being posted (its id unknown), so the reply is classified in the chat's lane, behind
    the question's slow turn, which ends at t=1150. The reply is still stamped when its page
    came back (t=1000) and the reason is saved."""
    channel, received = _channel(monkeypatch)
    running, release = _answering(channel, received, slow="is the backup done?")
    clock = [1000.0]
    async with _Inbox(channel, tmp_path, 42, hold_prompt=True) as inbox:
        inbox.coordinator._reason_clock = lambda: clock[0]
        task_id = await inbox.task()

        async def prompt_answers():
            inbox.prompt_response.set()
            await inbox.registered()

        async def the_turn_ends_late():
            await running.wait()
            clock[0] = 1150.0
            release.set()

        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.prompt_visible.wait, [_msg("is the backup done?", uid=OWNER),
                                         _msg("Use staging", uid=OWNER, **_reply(PROMPT))]),
            (prompt_answers, []),
            (the_turn_ends_late, []),
            (0.2, []),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert [t for t, _ in received] == ["is the backup done?"]


# ── round 4: the stamp is the reply's page, credited by Telegram's date ─────────

#: The host's wall clock reads WALL plus the coordinator's (fake) clock, so a Telegram date
#: of WALL + t says the message was sent at t on the coordinator's clock.
WALL = 1_750_000_000


@pytest.mark.parametrize("delivered", ["on the next page", "in the photo's page"])
async def test_a_reason_sent_in_time_while_the_poll_loop_reads_another_chats_photo_is_saved(
        monkeypatch, tmp_path, delivered):
    """The prompt opens at t=1000 (window to 1120). Another user, in chat 55, sends a photo; the
    poll loop itself reads it (the download, then the local vision model), from t=1095 to
    t=1125. The owner's reply to the prompt is saved either way:

    - sent at t=1100 while the photo is read, it comes on the next page (back at t=1125; the
      photo's page came back at t=1000): Telegram's date credits it back to t=1100;
    - already in the photo's page, behind the photo: it is stamped when that page came back
      (t=1000), not when the poll loop got to it (t=1125).

    Round 3 stamped it when the poll loop got to it: "expired", and the reason was lost."""
    channel, received = _channel(monkeypatch)
    clock = [1000.0]
    channel._wall_clock = lambda: WALL + clock[0]
    async with _Inbox(channel, tmp_path, 42) as inbox:
        inbox.coordinator._reason_clock = lambda: clock[0]
        hook, stamps = channel.on_decision_reason, []

        async def stamped(text, **kwargs):
            stamps.append(kwargs.get("received_at"))
            return await hook(text, **kwargs)

        channel.on_decision_reason = stamped
        task_id = await inbox.task()

        async def slow_vlm_read(attachment, spoken, chat_id, uid):
            clock[0] = 1095.0            # the photo is read from here...
            await asyncio.sleep(0)
            clock[0] = 1125.0            # ...to here
            return "[photo: a cat]", ""

        monkeypatch.setattr(channel, "_read_attachment", slow_vlm_read)
        photo = _msg("", chat_id=55, uid=8,
                     photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}])
        photo["message"].pop("text")
        if delivered == "on the next page":
            reply = _msg("Use staging", uid=OWNER, date=WALL + 1100, **_reply(PROMPT))
            pages = [(inbox.registered, [photo]), (0, [reply])]
        else:
            pages = [(inbox.registered, [photo, _msg("Use staging", uid=OWNER, **_reply(PROMPT))])]
        await _run(channel, [(0, [_tap(task_id)]), *pages, (0.2, [])])
        assert inbox.reason(task_id) == "Use staging"
    assert stamps == [1100.0 if delivered == "on the next page" else 1000.0]
    assert EXPIRED not in inbox.posted and "Reason saved." in inbox.posted
    assert [t for t, _ in received] == ["[photo: a cat]"]


def _at(clock, t):
    async def tick():
        clock[0] = t
    return tick


@pytest.mark.parametrize("previous, sent, stamp", [
    ("read", None, 600.0),                  # no date: the page's own instant
    ("read", WALL + 550, 550.0),            # sent 50 s before its page came back: credited
    ("read", WALL + 600, 600.0),            # sent as its page came back
    ("read", WALL + 100, 500.0),            # far in the past (a skewed clock): never before the previous page
    ("read", WALL + 700, 600.0),            # in the future: the page's instant, never later
    ("read", float("-inf"), 600.0),         # not an instant: the page's instant
    ("read", float("nan"), 600.0),
    ("read", True, 600.0),
    ("read", str(WALL + 550), 600.0),
    ("none", WALL + 550, 600.0),            # the first page: no previous page to bound it, no credit
    ("failed", WALL + 550, 600.0),          # the previous page's reading failed: no credit
    ("stepped back", WALL + 550, 600.0),    # a clock swapped between pages: never after the page
])
async def test_telegrams_date_moves_a_stamp_back_only_as_far_as_the_previous_page(
        monkeypatch, previous, sent, stamp):
    """The poll loop reads the clock once per getUpdates page, as it comes back. A claimed reply
    is stamped with its page's instant, moved back by its age on Telegram's date (measured on
    the host's wall clock, read with the page), but never before the previous page came back
    and never after its own; the hook, run later in the chat's lane, gets that stamp."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []

    def reading():
        if clock[0] is None:
            raise RuntimeError("clock offline")
        return clock[0]

    async def hook(text, **kwargs):
        stamps.append(kwargs.get("received_at"))
        return True

    channel.decision_reason_pending = lambda **kwargs: True
    channel.decision_reason_clock = reading
    channel._wall_clock = lambda: WALL + (clock[0] or 0.0)
    channel.on_decision_reason = hook
    earlier = {"read": [(_at(clock, 400.0), []), (_at(clock, 500.0), [])],
               "none": [],
               "failed": [(_at(clock, 400.0), []), (_at(clock, None), [])],
               "stepped back": [(_at(clock, 650.0), [])]}[previous]
    date = {} if sent is None else {"date": sent}
    await _run(channel, [
        *earlier,
        (_at(clock, 600.0), [_msg("Use staging", **_reply(PROMPT), **date)]),
        (_at(clock, 900.0), []),                    # when the lane runs it does not matter
    ])
    assert stamps == [stamp]


async def test_the_replys_age_is_measured_when_its_page_came_back_not_when_it_is_reached(monkeypatch):
    """The previous page came back at t=900, the reply's page at t=1000. A photo ahead of the
    reply in that page holds the poll loop until t=1125. The reply was sent at t=950: its age is
    measured on the wall clock read with its page (50 s), so it is stamped 950 - not 900, as a
    wall clock read only when the poll loop reached it (175 s) would have it."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []

    async def hook(text, **kwargs):
        stamps.append(kwargs.get("received_at"))
        return True

    async def slow_read(attachment, spoken, chat_id, uid):
        clock[0] = 1125.0
        return "[photo: a cat]", ""

    channel.decision_reason_pending = lambda **kwargs: True
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: WALL + clock[0]
    channel.on_decision_reason = hook
    monkeypatch.setattr(channel, "_read_attachment", slow_read)
    photo = _msg("", chat_id=55, uid=8,
                 photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}])
    photo["message"].pop("text")
    await _run(channel, [
        (_at(clock, 900.0), []),
        (_at(clock, 1000.0), [photo, _msg("Use staging", date=WALL + 950, **_reply(PROMPT))]),
    ])
    assert stamps == [950.0]


async def test_an_update_handled_outside_the_poll_loop_is_stamped_when_it_is_claimed(monkeypatch):
    """No page, no previous page: the clock is read as the reply is claimed and its Telegram
    date is not credited."""
    channel, _received = _channel(monkeypatch)
    stamps = []

    async def hook(text, **kwargs):
        stamps.append(kwargs.get("received_at"))
        return True

    channel.decision_reason_pending = lambda **kwargs: True
    channel.decision_reason_clock = lambda: 42.0
    channel._wall_clock = lambda: WALL + 42.0
    channel.on_decision_reason = hook
    await channel._handle_update(_msg("Use staging", date=WALL + 10, **_reply(PROMPT)))
    assert stamps == [42.0]


async def test_a_failing_clock_is_logged_once_until_it_reads_again(monkeypatch, caplog):
    """The clock is read on every page; one that keeps failing is named once, not every poll,
    and named again if it fails after it recovered."""
    import logging

    channel, _received = _channel(monkeypatch)
    readings = [RuntimeError("clock offline")] * 3 + [5.0, RuntimeError("clock offline again")]

    def reading():
        value = readings.pop(0) if readings else 6.0
        if isinstance(value, Exception):
            raise value
        return value

    channel.decision_reason_clock = reading
    with caplog.at_level(logging.WARNING, logger="jarvis.channels.telegram"):
        await _run(channel, [(0, []), (0, []), (0, []), (0, []), (0, [])])
    failures = [r for r in caplog.records if "decision-reason clock failed" in r.getMessage()]
    assert len(failures) == 2


# ── round 5: a page cut short, hostile dates, and the stamp's other inputs ──────

def _photo(chat_id=55, uid=8):
    """A photo from another user in another chat: the poll loop itself reads it."""
    photo = _msg("", chat_id=chat_id, uid=uid,
                 photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}])
    photo["message"].pop("text")
    return photo


def _stamped(channel, stamps, *, keep_kwargs=False):
    """Claim every reply and record what the hook is handed: its ``received_at`` (or, with
    *keep_kwargs*, every keyword)."""
    async def hook(text, **kwargs):
        stamps.append(dict(kwargs) if keep_kwargs else kwargs.get("received_at"))
        return True

    channel.decision_reason_pending = lambda **kwargs: True
    channel.on_decision_reason = hook


@pytest.mark.parametrize("photo", ["read", "whose reading raises"])
async def test_a_reason_behind_an_update_whose_handling_failed_keeps_its_credit(
        monkeypatch, tmp_path, photo):
    """The prompt opens at t=1000 (window to 1120) and the previous page came back at t=1000.
    The owner replies at t=1100, in time, but the reply's page only comes back at t=1130, with
    a photo from chat 55 ahead of it. Read normally, the photo leaves the reply its credit: it
    is stamped max(1000, 1130 - 30) = 1100 and saved. If handling the photo raises, the poll
    loop backs off and the reply comes again on the next page (t=1133), since its offset was
    never passed. The page that failed before reaching it is not its previous page (that page
    already carried it), so its lower bound stays t=1000: stamped 1100 and saved, not 1130 and
    refused as expired."""
    channel, received = _channel(monkeypatch)
    clock = [1000.0]
    channel._wall_clock = lambda: WALL + clock[0]
    async with _Inbox(channel, tmp_path, 42) as inbox:
        inbox.coordinator._reason_clock = lambda: clock[0]
        hook, stamps = channel.on_decision_reason, []

        async def stamped(text, **kwargs):
            stamps.append(kwargs.get("received_at"))
            return await hook(text, **kwargs)

        channel.on_decision_reason = stamped
        task_id = await inbox.task()

        async def read(attachment, spoken, chat_id, uid):
            if photo == "whose reading raises":
                raise RuntimeError("vision backend misconfigured")
            return "[photo: a cat]", ""

        monkeypatch.setattr(channel, "_read_attachment", read)
        reply = _msg("Use staging", uid=OWNER, date=WALL + 1100, **_reply(PROMPT))
        pages = [(0, [_tap(task_id)]), (inbox.registered, []),
                 (_at(clock, 1130.0), [_photo(), reply])]
        if photo == "whose reading raises":
            pages.append((_at(clock, 1133.0), [reply]))     # fetched again after the back-off
        await _run(channel, [*pages, (0.2, [])])
        assert inbox.reason(task_id) == "Use staging"
    assert stamps == [1100.0]
    assert EXPIRED not in inbox.posted and "Reason saved." in inbox.posted


@pytest.mark.parametrize("failure", ["getUpdates", "after the page was handled"])
async def test_a_poll_error_that_cut_no_page_short_keeps_the_previous_page(monkeypatch, failure):
    """Only a page cut short gives its previous page back. A getUpdates that fails reads no
    page: the next page's reply is still credited back to the page before (t=500). A page
    handled to its end whose batch flush then fails is a previous page like any other: the
    next page's reply is credited back no further than it (t=550)."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: WALL + clock[0]
    if failure == "getUpdates":
        async def bad_gateway():
            raise RuntimeError("502 Bad Gateway")

        earlier, stamp = [(_at(clock, 500.0), []), (bad_gateway, [])], 520.0
    else:
        due, calls = channel._batch.due, [0]

        def flush_fails_on_the_second_page(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("flush failed")
            return due(*args, **kwargs)

        monkeypatch.setattr(channel._batch, "due", flush_fails_on_the_second_page)
        earlier, stamp = [(_at(clock, 500.0), []), (_at(clock, 550.0), [])], 550.0
    await _run(channel, [*earlier, (_at(clock, 600.0), [_msg("Use staging", date=WALL + 520,
                                                                **_reply(PROMPT))])])
    assert stamps == [stamp]


#: An int that still rounds to the largest finite float, though its sum with a wall clock read
#: as an int does not.
_ALMOST_TOO_LARGE = int(sys.float_info.max) + 2 ** 970 - 1


@pytest.mark.parametrize("value, instant", [
    (WALL, True), (float(WALL), True), (10 ** 308, True), (_ALMOST_TOO_LARGE, True),
    (10 ** 400, False), (-10 ** 400, False), (float("inf"), False), (float("nan"), False),
    (True, False), (str(WALL), False), (None, False),
], ids=["int", "float", "10**308", "almost too large", "10**400", "-10**400", "inf", "nan",
        "bool", "str", "None"])
def test_an_instant_is_a_finite_int_or_float_and_asking_never_raises(value, instant):
    """An int too large for a float is no instant: False, not an OverflowError."""
    assert _is_instant(value) is instant


@pytest.mark.parametrize("date, wall, stamp", [
    (10 ** 400, WALL + 600.0, 600.0),         # too large for a float: no instant, the page's
    (-10 ** 400, WALL + 600.0, 600.0),
    (10 ** 308, WALL + 600.0, 600.0),         # far in the future: the page's instant
    (-10 ** 308, WALL + 600.0, 500.0),        # far in the past: the previous page
    (-_ALMOST_TOO_LARGE, WALL + 600, 500.0),  # its age overflows a float against an int wall clock
], ids=["10**400", "-10**400", "10**308", "-10**308", "-almost too large, int wall clock"])
async def test_a_hostile_date_never_raises_and_the_reply_is_stamped_within_its_bounds(
        monkeypatch, date, wall, stamp):
    """Only a broken or hostile API server sends such a date. The reply is still claimed and
    handed to the hook with a stamp between the previous page (t=500) and its own (t=600); it
    is not dropped with the poll loop backing off."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: wall
    await _run(channel, [(_at(clock, 500.0), []),
                         (_at(clock, 600.0), [_msg("Use staging", date=date, **_reply(PROMPT))])])
    assert stamps == [stamp]


async def test_a_first_page_reply_behind_a_slow_photo_is_stamped_with_its_page_instant(monkeypatch):
    """No previous page (the first page): the reply is stamped with its page's instant (t=1000),
    not when the poll loop reached it behind a slow photo (t=1125)."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: WALL + clock[0]

    async def slow_read(attachment, spoken, chat_id, uid):
        clock[0] = 1125.0
        return "[photo: a cat]", ""

    monkeypatch.setattr(channel, "_read_attachment", slow_read)
    await _run(channel, [(_at(clock, 1000.0), [_photo(), _msg("Use staging", date=WALL + 990,
                                                                **_reply(PROMPT))])])
    assert stamps == [1000.0]


@pytest.mark.parametrize("wall", ["raises", "inf", "nan"])
async def test_an_unreadable_wall_clock_gives_the_page_instant_and_polling_goes_on(monkeypatch, wall):
    """The host's wall clock fails, or reads no instant: Telegram's date is not credited (the
    page's instant), and the poll loop is not disturbed."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]

    def broken():
        if wall == "raises":
            raise OSError("no wall clock")
        return float(wall)

    channel._wall_clock = broken
    await _run(channel, [(_at(clock, 500.0), []),
                         (_at(clock, 600.0), [_msg("Use staging", date=WALL + 550, **_reply(PROMPT))])])
    assert stamps == [600.0]


async def test_a_fractional_wall_clock_is_used_as_read(monkeypatch):
    """The reply's age is the wall clock as read, fractions of a second kept, less its date."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: WALL + clock[0]
    await _run(channel, [(_at(clock, 500.0), []),
                         (_at(clock, 600.75), [_msg("Use staging", date=WALL + 550, **_reply(PROMPT))])])
    assert stamps == [pytest.approx(550.0, abs=1e-3)]


async def test_a_page_whose_clock_reading_failed_hands_the_hook_no_stamp(monkeypatch):
    """The clock fails as the reply's page comes back and reads again when the reply is claimed:
    the hook gets no ``received_at`` (the inbox judges the reply when it runs), not a stamp read
    when the reply was claimed."""
    channel, _received = _channel(monkeypatch)
    calls, seen = [0], []
    _stamped(channel, seen, keep_kwargs=True)

    def flaky():
        calls[0] += 1
        if calls[0] == 2:                 # the reply's page
            raise RuntimeError("clock hiccup")
        return 500.0 + calls[0]

    channel.decision_reason_clock = flaky
    channel._wall_clock = lambda: WALL + 600.0
    await _run(channel, [(0, []), (0, [_msg("Use staging", date=WALL + 550, **_reply(PROMPT))])])
    assert len(seen) == 1 and "received_at" not in seen[0]


async def test_an_update_handled_outside_the_poll_loop_after_pages_gets_no_credit(monkeypatch):
    """Pages came back before, but an update handled directly has no page: it is stamped when it
    is claimed, and its Telegram date is not credited back to the last page."""
    channel, _received = _channel(monkeypatch)
    clock, stamps = [0.0], []
    _stamped(channel, stamps)
    channel.decision_reason_clock = lambda: clock[0]
    channel._wall_clock = lambda: WALL + clock[0]
    await _run(channel, [(_at(clock, 500.0), [])])
    clock[0] = 600.0
    await channel._handle_update(_msg("Use staging", date=WALL + 550, **_reply(PROMPT)))
    assert stamps == [600.0]
