"""H414 — a /btw side question through the real channel adapters.

The orchestrator and lifecycle tests call ``channel_handler`` directly; an adapter has its
own front door. Telegram signals running code for every admitted message BEFORE batching
and queues the turn on a per-chat lane, and Discord/Slack deliver a command under the
sender's key lock. A /btw is asked beside the running work, so on each of those paths it
must neither interrupt that work nor wait behind it. Hermetic: fake lanes and handlers.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from agents.core import code_interruptions
from agents.core.channels.batching import AsyncBatcher, Coalescer
from agents.core.channels.chat_lanes import ChatLanes
from agents.core.channels.gateway import Gateway
from agents.core.channels.session import SessionSource, build_session_key
from agents.core.channels.telegram import TelegramChannel
from agents.core.orchestrator import Orchestrator


def _orchestrator():
    orch = object.__new__(Orchestrator)
    orch._session_id_default = "shared"
    orch._runtime_settings = {}
    source = SessionSource(channel="telegram", sender="99", thread_id="42")
    orch._channel_sessions = {build_session_key(source): "actual-session-42"}
    return orch


def _telegram(batch_window=0.0):
    orch = _orchestrator()
    pairing = SimpleNamespace(is_allowed=lambda channel, sender: sender == "99")
    gateway = Gateway(interrupt_handler=orch.interrupt_channel_message, pairing=pairing)
    channel = TelegramChannel(
        token="fake", allowed_user_ids=[99], pairing=pairing,
        pre_turn_interrupt=gateway.pre_lane_interrupt,
    )
    channel._batch = Coalescer(window=batch_window) if batch_window == 0 else Coalescer(batch_window, 10.0)
    channel._lanes = ChatLanes(name="btw-telegram")
    return channel, gateway, orch


async def _message(channel, text, chat=42, user=99):
    await channel._handle_update({"message": {
        "from": {"id": user}, "chat": {"id": chat, "type": "private"}, "text": text,
    }})


async def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_telegram_pre_lane_probe_ignores_a_side_question_but_not_a_message():
    channel, gateway, orch = _telegram()
    task = asyncio.create_task(asyncio.sleep(30))
    record = code_interruptions.register("actual-session-42", task, code_interruptions.PartialOutput())
    ran = []

    async def run_turn(chat_id, uid, turn, **kwargs):
        ran.append(turn)

    channel._run_turn = run_turn
    try:
        await _message(channel, "/btw what did I ask first?")
        await _wait_for(lambda: ran == ["/btw what did I ask first?"])
        assert record.interrupted is False and not task.done()
        # The gateway and the orchestrator hooks agree on their own.
        kwargs = {"channel": "telegram", "sender": "99", "chat_id": 42}
        assert gateway.pre_lane_interrupt(text="/btw anything", **kwargs) is False
        assert orch.interrupt_channel_message(text="/btw anything", sender="99", channel="telegram",
                                              chat_id=42) is False
        assert record.interrupted is False
        # An ordinary message still interrupts, exactly as before.
        await _message(channel, "interrupt me")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert record.interrupted is True
    finally:
        await channel._lanes.settle()
        code_interruptions.unregister(record)
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [0.0, 5.0])
async def test_telegram_answers_a_side_question_while_the_chat_lane_is_occupied(window):
    channel, _gateway, _orch = _telegram(batch_window=window)
    blocked = asyncio.Event()
    ran = []

    async def run_turn(chat_id, uid, turn, **kwargs):
        ran.append(turn)

    channel._run_turn = run_turn
    channel._lanes.submit(42, lambda: blocked.wait())          # the main turn, still running
    try:
        if window:
            await _message(channel, "a held piece")            # held in the batch window
        await _message(channel, "/btw what did I ask first?")
        await _wait_for(lambda: "/btw what did I ask first?" in ran)
        assert not blocked.is_set()
        assert ran == ["/btw what did I ask first?"]           # the held piece is queued, not run
        blocked.set()
        if window:
            await _wait_for(lambda: ran == ["/btw what did I ask first?", "a held piece"])
    finally:
        blocked.set()
        await channel._lanes.settle()
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_telegram_side_question_takes_no_voice_mark_and_has_its_own_lane():
    channel, _gateway, _orch = _telegram()
    channel._voice_pending.add((42, "99"))
    seen = []

    async def run_turn(chat_id, uid, turn, spoken=False, **kwargs):
        seen.append((turn, spoken))

    channel._run_turn = run_turn
    try:
        await _message(channel, "/btw what did I ask first?")
        await channel._lanes.settle()
        assert seen == [("/btw what did I ask first?", False)]
        assert (42, "99") in channel._voice_pending       # the voice mark waits for a real turn
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_async_batcher_delivers_a_side_question_without_waiting_for_the_running_turn():
    """Discord and Slack: a command is delivered under the sender's key lock, behind the
    running turn; a /btw is not."""
    release = asyncio.Event()
    delivered = []

    async def deliver(key, text, meta):
        delivered.append(text)
        if text == "main turn":
            await release.wait()
        return f"reply:{text}"

    batcher = AsyncBatcher(deliver, 0.01, 0.05)
    key = ("channel-1", "sender-1")
    main = asyncio.create_task(batcher.submit(key, "/status"))     # a command: delivered at once
    await asyncio.sleep(0)
    running = asyncio.create_task(batcher._in_order(key, "main turn", {}, batcher._generation))
    await _wait_for(lambda: "main turn" in delivered)
    ordinary = asyncio.create_task(batcher.submit(key, "/help"))   # waits behind the running turn
    await asyncio.sleep(0.05)
    assert "/help" not in delivered
    answer = await asyncio.wait_for(batcher.submit(key, "/btw what did I ask first?"), 3)
    assert answer == "reply:/btw what did I ask first?" and not release.is_set()
    release.set()
    await asyncio.gather(main, running, ordinary)
    assert delivered.index("/btw what did I ask first?") < delivered.index("/help")
