"""Trusted Telegram turn provenance expires even in copied async contexts."""

import asyncio
from types import SimpleNamespace

from agents.core.owner_once_context import (
    OwnerReplySource,
    bind_owner_reply_source,
    close_owner_reply_source,
    current_owner_reply_source,
)


async def _waiting(event):
    await event.wait()


async def test_source_lives_only_for_running_turn_and_poller():
    poll_release = asyncio.Event()
    turn_release = asyncio.Event()
    poller = asyncio.create_task(_waiting(poll_release))
    turn = asyncio.create_task(_waiting(turn_release))
    channel = SimpleNamespace(_running=True, _owner_once_generation="generation", _poll_task=poller)
    source = OwnerReplySource(channel, "generation", -500, 42, turn)
    token = bind_owner_reply_source(source)
    try:
        assert current_owner_reply_source() is source
        channel._owner_once_generation = "new generation"
        assert current_owner_reply_source() is None
        channel._owner_once_generation = "generation"
        channel._poll_task = None
        assert current_owner_reply_source() is None
        channel._poll_task = poller
        turn.cancel()
        assert current_owner_reply_source() is None
    finally:
        close_owner_reply_source(source, token)
        poller.cancel()
        await asyncio.gather(poller, turn, return_exceptions=True)


async def test_closing_parent_scope_invalidates_child_context_copy():
    poll_release = asyncio.Event()
    turn_release = asyncio.Event()
    child_release = asyncio.Event()
    poller = asyncio.create_task(_waiting(poll_release))
    turn = asyncio.create_task(_waiting(turn_release))
    channel = SimpleNamespace(_running=True, _owner_once_generation="g", _poll_task=poller)
    source = OwnerReplySource(channel, "g", -500, 42, turn)
    token = bind_owner_reply_source(source)

    async def child():
        await child_release.wait()
        return current_owner_reply_source()

    copied = asyncio.create_task(child())
    close_owner_reply_source(source, token)
    child_release.set()
    assert await copied is None
    assert current_owner_reply_source() is None
    turn.cancel()
    poller.cancel()
    await asyncio.gather(turn, poller, return_exceptions=True)
