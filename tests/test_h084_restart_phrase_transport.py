"""A private restart phrase remains one original Telegram command candidate."""

from __future__ import annotations

import pytest

from agents.core.channels.batching import Coalescer
from agents.core.channels.telegram import TelegramChannel


@pytest.mark.asyncio
async def test_private_restart_phrase_is_a_standalone_batch_barrier():
    channel = TelegramChannel("test-token")
    channel._batch = Coalescer(window=0.5, hard_cap=1.0, clock=lambda: 0.0)
    delivered = []

    async def record(chat_id, uid, turn, **metadata):
        delivered.append((chat_id, uid, turn, metadata))

    channel._deliver_turn = record
    try:
        channel._batch.add((10, "10"), "earlier question")
        await channel._queue_turn(10, 10, "restart gateway")
        assert [item[2] for item in delivered] == ["earlier question", "restart gateway"]
        assert channel._batch.held_keys() == []
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_group_phrase_and_longer_prose_remain_ordinary_batches():
    channel = TelegramChannel("test-token")
    channel._batch = Coalescer(window=0.5, hard_cap=1.0, clock=lambda: 0.0)
    delivered = []

    async def record(_chat_id, _uid, turn, **_metadata):
        delivered.append(turn)

    channel._deliver_turn = record
    try:
        await channel._queue_turn(10, 10, "restart gateway", chat_type="group")
        await channel._queue_turn(11, 11, "restart gateway now")
        assert delivered == []
        assert channel._batch.pop((10, "10")).text == "restart gateway"
        assert channel._batch.pop((11, "11")).text == "restart gateway now"
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_private_phrase_bypasses_pending_reply_and_decision_reason_without_seed():
    delivered = []
    pending = []
    reasons = []

    async def receive(text, **_kwargs):
        delivered.append(text)
        return "handled"

    async def pending_reply(text, **_kwargs):
        pending.append(text)
        return True

    async def decision_reason(text, **_kwargs):
        reasons.append(text)
        return True

    channel = TelegramChannel("test-token", handler=receive,
                              pending_reply_handler=pending_reply)
    channel._running = True
    channel._owner_once_generation = "current"
    channel._verified_bot_generation = "current"
    channel._bot_id = 42
    channel.on_decision_reason = decision_reason
    channel._claims_reason = lambda *_args: True
    channel._heal_dead_target = lambda _up: None
    message = {"from": {"id": 10, "is_bot": True},
               "chat": {"id": 10, "type": "private"},
               "message_id": 12, "text": "restart gateway",
               "reply_to_message": {"message_id": 11}}
    try:
        await channel._handle_update({"update_id": 7, "message": message})
        assert pending == [] and reasons == []
        assert delivered == ["restart gateway"]
    finally:
        await channel.client.aclose()
