"""H117 with the decision inbox wired: a Telegram reply is batched unless it answers a
decision-reason prompt.

H487 lets the owner answer a rejection's reason prompt by replying to it. The hook it added
(``TelegramChannel.on_decision_reason``, set by ``AutonomyCoordinator.wire`` whenever a bot and
an owner chat are configured) used to take EVERY text reply out of H117's batching: the sender's
held pieces were flushed and the reply ran on its own, even when the hook declined it. A split
reply, or a question sent as a reply to its photo, became two turns; an observed group reply no
longer let what was said before it go first; a group reply to the bot jumped ahead of another
member's earlier held question.

Now only a reply the hook consumes leaves the batching path. Every other reply is queued,
merged and flushed as if the hook were not wired, and a failing hook never loses the reply.
While a reason prompt is still on its way to a chat (its message id not yet known), a reply in
that chat is classified behind it in the chat's lane, after everything held for that chat.
These cases run on the real poll loop.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.group_policy import GroupPolicy
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


class _Inbox:
    """The real decision inbox wired to the channel by ``AutonomyCoordinator.wire``, with
    Telegram's API answered in process. A reason prompt's response can be held back."""

    def __init__(self, channel, tmp_path, owner_chat, *, hold_prompt=False):
        self.channel = channel
        self.queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
        self.worker = AutonomyWorker(self.queue)
        self.posted = []
        self.prompt_visible = asyncio.Event()
        self.prompt_response = asyncio.Event()
        if not hold_prompt:
            self.prompt_response.set()
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
        await self.channel.client.aclose()
        self.queue.close()

    async def _api(self, request):
        body = json.loads(request.content)
        self.posted.append(body.get("text"))
        if body.get("reply_markup", {}).get("force_reply") is True:
            self.prompt_visible.set()
            await self.prompt_response.wait()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": PROMPT}})
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


async def test_a_consumed_reason_does_not_cut_the_owners_burst_around_it(monkeypatch, tmp_path):
    channel, received = _channel(monkeypatch)
    async with _Inbox(channel, tmp_path, 42) as inbox:
        task_id = await inbox.task()
        await _run(channel, [
            (0, [_tap(task_id)]),
            (inbox.registered, [_msg("thanks, and", uid=OWNER),
                                _msg("Use staging", uid=OWNER, **_reply(PROMPT)),
                                _msg("what is next?", uid=OWNER)]),
        ])
        assert inbox.reason(task_id) == "Use staging"
    assert received == [("thanks, and\nwhat is next?", {"chat_id": 42, "sender": str(OWNER)})]


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
