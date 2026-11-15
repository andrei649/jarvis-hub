"""Telegram ordinary replies require a confirmed message receipt and never replay uncertainty."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agents.core.channels import outbound_safety
from agents.core.channels.telegram import TelegramChannel, TelegramDraft


@pytest.fixture(autouse=True)
def _isolated_ack_transport(monkeypatch):
    """Exercise draft HTTP receipts without an opaque process-wide secret broker.

    An installed known-secret redactor intentionally buffers all draft previews
    until finish; these cases need to reach the mocked POST or edit seam.
    """
    monkeypatch.setattr(outbound_safety, "_known_redactor", None)


class _Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.is_success = 200 <= status < 300
        self.request = httpx.Request("POST", "https://api.telegram.org/botfixture/sendMessage")

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("telegram refused", request=self.request,
                                        response=httpx.Response(self.status_code, request=self.request,
                                                                json=self.body))

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class _Client:
    is_closed = False

    def __init__(self, *answers):
        self.answers = list(answers)
        self.posts = []

    async def post(self, url, **kwargs):
        self.posts.append((url.rsplit("/", 1)[-1], kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class _SuspendedClient(_Client):
    def __init__(self, *, first_ack=False):
        super().__init__()
        self.first_ack = first_ack
        self.entered = asyncio.Event()

    async def post(self, url, **kwargs):
        self.posts.append((url.rsplit("/", 1)[-1], kwargs))
        if self.first_ack and len(self.posts) == 1:
            return _Response(ACK)
        if len(self.posts) == (2 if self.first_ack else 1):
            self.entered.set()
            await asyncio.Event().wait()
        return _Response(ACK)


def _channel(*answers):
    channel = TelegramChannel("fixture")
    channel.client = _Client(*answers)
    return channel


ACK = {"ok": True, "result": {"message_id": 17}}
BAD_ACKS = (
    {"ok": True}, {"ok": False, "description": "refused"},
    {"ok": True, "result": {"message_id": 0}},
    {"ok": True, "result": {"message_id": True}},
    {"ok": True, "result": {"message_id": "17"}},
    ValueError("invalid json"),
)


@pytest.mark.parametrize("body", BAD_ACKS)
@pytest.mark.parametrize("plain", [False, True])
async def test_ordinary_send_requires_exact_positive_message_id(body, plain):
    channel = _channel(_Response(body))
    assert await channel.send("hello", chat_id=7, plain=plain, voice=False) is False
    assert len(channel.client.posts) == 1


@pytest.mark.parametrize("plain", [False, True])
async def test_ordinary_send_accepts_confirmed_ack(plain):
    channel = _channel(_Response(ACK))
    assert await channel.send("hello", chat_id=7, plain=plain, voice=False) is True


@pytest.mark.parametrize("body", BAD_ACKS)
async def test_ephemeral_invalid_ack_schedules_no_deletion(body):
    from agents.core.channels.ephemeral import EphemeralReply

    channel = _channel(_Response(body))
    assert await channel.send(EphemeralReply("notice", ttl_seconds=30), chat_id=7) is False
    assert len(channel.client.posts) == 1
    assert not channel._ephemeral_deletes._tasks


@pytest.mark.parametrize("body", BAD_ACKS)
async def test_card_send_requires_a_confirmed_message(body):
    channel = _channel(_Response(body))
    assert await channel.send_card(7, {"text": "approve?"}) is False
    assert len(channel.client.posts) == 1


@pytest.mark.parametrize("first", [
    _Response({"ok": True, "result": {}}),
    _Response({"ok": False}),
    _Response(ACK, status=500),
    httpx.ReadTimeout("lost response"),
    httpx.DecodingError("response could not be decoded"),
])
async def test_first_draft_send_uncertain_never_sends_again(first, monkeypatch):
    channel = _channel(first)
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: effects.append("media") or ("x", []))
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    await draft.push("hello ")
    assert draft.started is True
    await draft.push("again ")
    assert await draft.finish("hello again") is False
    assert len(channel.client.posts) == 1 and effects == []


async def test_definite_preconnect_failure_can_use_next_draft_frame():
    channel = _channel(httpx.ConnectError("not connected"), _Response(ACK))
    draft = TelegramDraft(channel, 7, interval=0)
    await draft.push("hello ")
    assert draft.started is False
    await draft.push("again ")
    assert draft.started is True
    assert len(channel.client.posts) == 2


async def test_cancelled_first_post_latches_uncertainty_and_propagates(monkeypatch):
    channel = _channel()
    channel.client = _SuspendedClient()
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: effects.append("media") or ("x", []))
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    pushing = asyncio.create_task(draft.push("hello "))
    await asyncio.wait_for(channel.client.entered.wait(), 1)
    pushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pushing
    assert draft.started is True
    await asyncio.wait_for(draft.push("again "), 1)
    assert await asyncio.wait_for(draft.finish("hello again"), 1) is False
    assert len(channel.client.posts) == 1 and effects == []


async def test_cancelled_edit_latches_and_blocks_final_send():
    channel = _channel()
    channel.client = _SuspendedClient(first_ack=True)
    draft = TelegramDraft(channel, 7, interval=0)
    await draft.push("hello ")
    pushing = asyncio.create_task(draft.push("again "))
    await asyncio.wait_for(channel.client.entered.wait(), 1)
    pushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pushing
    assert draft.started is True
    await draft.push("later ")
    assert await asyncio.wait_for(draft.finish("final"), 1) is False
    assert len(channel.client.posts) == 2


async def test_cancelled_no_id_final_send_marks_draft_started():
    channel = _channel()
    channel.client = _SuspendedClient()
    draft = TelegramDraft(channel, 7, interval=0)
    finishing = asyncio.create_task(draft.finish("final answer"))
    await asyncio.wait_for(channel.client.entered.wait(), 1)
    finishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finishing
    assert draft.started is True and draft.finished is True
    assert await draft.finish("retry") is False
    assert len(channel.client.posts) == 1


async def test_cancelled_final_edit_propagates_and_never_replays(monkeypatch):
    channel = _channel()
    channel.client = _SuspendedClient(first_ack=True)
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: ("final text", [object()]))

    async def deliver(*_a, **_k):
        effects.append("media")

    monkeypatch.setattr(channel, "_deliver_media", deliver)
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    await draft.push("hello ")
    finishing = asyncio.create_task(draft.finish("final text"))
    await asyncio.wait_for(channel.client.entered.wait(), 1)
    finishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finishing
    assert draft.started is True and draft.finished is True
    assert await draft.finish("retry") is False
    assert len(channel.client.posts) == 2 and effects == []


@pytest.mark.parametrize("edit", [
    _Response({"ok": True, "result": {}}),
    _Response({"ok": True, "result": True}),
    _Response({"ok": True, "result": {"message_id": 18}}),
    _Response(ACK, status=500),
    httpx.ReadTimeout("lost edit response"),
    httpx.DecodingError("edit response could not be decoded"),
])
async def test_uncertain_edit_never_falls_back_to_fresh_send(edit, monkeypatch):
    channel = _channel(_Response(ACK), edit)
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: effects.append("media") or ("x", []))
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    await draft.push("hello ")
    await draft.push("there ")
    assert draft.started is True
    assert await draft.finish("hello there and more") is False
    assert [method for method, _ in channel.client.posts] == ["sendMessage", "editMessageText"]
    assert effects == []


@pytest.mark.parametrize("edit", [
    _Response({"ok": True, "result": {}}),
    httpx.DecodingError("final response could not be decoded"),
])
async def test_final_uncertain_edit_never_falls_back_or_sends_overflow(monkeypatch, edit):
    channel = _channel(_Response(ACK), edit)
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: ("final " * 2000, [object()]))

    async def deliver(*_a, **_k):
        effects.append("media")

    monkeypatch.setattr(channel, "_deliver_media", deliver)
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    await draft.push("hello ")
    assert await draft.finish("final " * 2000) is False
    assert [method for method, _ in channel.client.posts] == ["sendMessage", "editMessageText"]
    assert effects == []


async def test_failed_final_fallback_stops_before_overflow_media_or_voice(monkeypatch):
    channel = _channel(_Response(ACK), _Response({"ok": False}, status=400),
                       _Response({"ok": False}, status=400), _Response({"ok": True}))
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: ("final " * 2000, [object()]))

    async def deliver(*_a, **_k):
        effects.append("media")

    monkeypatch.setattr(channel, "_deliver_media", deliver)
    monkeypatch.setattr(channel, "_after_reply", lambda *_a, **_k: effects.append("voice"))
    await draft.push("hello ")
    assert await draft.finish("final " * 2000) is False
    assert [method for method, _ in channel.client.posts] == [
        "sendMessage", "editMessageText", "editMessageText", "sendMessage"]
    assert effects == []


async def test_no_id_final_text_failure_does_not_send_media(monkeypatch):
    channel = _channel(_Response({"ok": True}))
    draft = TelegramDraft(channel, 7, interval=0)
    effects = []
    monkeypatch.setattr(channel, "_take_media", lambda *_a, **_k: ("final text", [object()]))

    async def deliver(*_a, **_k):
        effects.append("media")

    monkeypatch.setattr(channel, "_deliver_media", deliver)
    assert await draft.finish("final text") is False
    assert effects == [] and len(channel.client.posts) == 1


@pytest.mark.parametrize("plain", [False, True])
async def test_multiple_chunks_stop_after_unconfirmed_ack(plain):
    channel = _channel(_Response(ACK), _Response({"ok": True, "result": {}}))
    assert await channel.send("word " * 2000, chat_id=7, plain=plain, voice=False) is False
    assert len(channel.client.posts) == 2
