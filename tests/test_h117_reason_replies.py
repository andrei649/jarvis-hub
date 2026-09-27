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
spoken, and a tap read before the reply still supersedes the prompt it answers. Every other reply
is queued, merged and flushed as if the hook were not wired, and a failing hook never loses the
reply. While a reason prompt is still on its way to a chat (its message id not yet known), a
reply in that chat is classified behind it in the chat's lane too. These cases run on the real
poll loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels import voice_mode
from agents.core.channels.group_policy import GroupPolicy
from agents.core.channels.spoken_reply import Audio
from agents.core.channels.telegram import TelegramChannel

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
