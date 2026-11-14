"""Telegram identity deadlines retain the exact late request and poller claim."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from agents.core.channels import polling_claims
from agents.core.channels.telegram import TelegramChannel


@pytest.fixture
def channel_pair(tmp_path, monkeypatch):
    acquire = polling_claims.acquire_telegram_claim
    monkeypatch.setattr(polling_claims, "acquire_telegram_claim",
                        lambda token: acquire(token, root=tmp_path / "install"))
    channels = []

    def make(connect_timeout_seconds=15):
        channel = TelegramChannel("opaque-offline-token",
                                  connect_timeout_seconds=connect_timeout_seconds)
        channel._resume_offset = Mock()
        channel.publish_command_menu = AsyncMock(return_value=True)
        channel._poll_loop = AsyncMock()
        channels.append(channel)
        return channel

    yield make

    # Tests settle the identity task before reaching this cleanup.


@pytest.mark.asyncio
async def test_timed_identity_never_binds_late_result_and_keeps_claim(channel_pair):
    first, contender = channel_pair(), channel_pair()
    first._connect_timeout_seconds = 0.01
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_identity():
        entered.set()
        await release.wait()
        return {"id": 42, "username": "late_bot"}

    first._get_me = AsyncMock(side_effect=slow_identity)
    contender._get_me = AsyncMock(return_value={"id": 43, "username": "other_bot"})
    try:
        await asyncio.wait_for(first.start(), 1)
        assert entered.is_set()
        assert not first._running and first._poll_claim is not None
        assert first.health_snapshot()["fatal"] == "connect_timeout"
        assert first._bot_id is None and first._verified_bot_generation is None
        first.publish_command_menu.assert_not_awaited()
        assert first._poll_task is None
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "polling_claim_busy"
        contender._get_me.assert_not_awaited()
        release.set()
        await first._identity_task
        assert first._bot_id is None and first._poll_task is None
        first.publish_command_menu.assert_not_awaited()
        await first.start()
        assert first.health_snapshot()["fatal"] == "polling_cleanup_required"
        await first.stop()
        await contender.start()
        contender._get_me.assert_awaited_once()
    finally:
        release.set()
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_cancelled_start_and_stop_do_not_cancel_late_identity(channel_pair):
    channel, contender = channel_pair(), channel_pair()
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled_identity = []

    async def slow_identity():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled_identity.append(True)
            raise
        return {"id": 42, "username": "late_bot"}

    channel._get_me = slow_identity
    contender._get_me = AsyncMock(return_value={"id": 43})
    starting = asyncio.create_task(channel.start())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        stopping = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert cancelled_identity == [] and channel._poll_claim is not None
        await contender.start()
        contender._get_me.assert_not_awaited()
        release.set()
        await channel.stop()
        assert channel._poll_claim is None and channel._bot_id is None
        await contender.start()
        contender._get_me.assert_awaited_once()
    finally:
        release.set()
        await channel.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_connect_component_keeps_long_poll_read_and_recreation(channel_pair):
    channel = channel_pair(7)
    try:
        assert channel.client.timeout.connect == 7
        assert channel.client.timeout.read == channel.client.timeout.write == channel.client.timeout.pool == 15
        seen = []

        async def transport(request):
            seen.append(request.extensions["timeout"])
            return httpx.Response(200, json={"result": []})

        await channel.client.aclose()
        channel.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=7), transport=httpx.MockTransport(transport))
        assert await channel._get_updates() == []
        assert seen == [{"connect": 7, "read": 30, "write": 15, "pool": 15}]
        old = channel.client
        await old.aclose()
        channel._get_me = AsyncMock(return_value={"id": 1})
        await channel.start()
        assert channel.client is not old
        assert channel.client.timeout.connect == 7
        assert channel.client.timeout.read == channel.client.timeout.write == channel.client.timeout.pool == 15
    finally:
        await channel.stop()
