"""One Telegram poller per token, with claims retained through uncertain cleanup."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from agents.core.channels import delivery_ledger, polling_claims, telegram
from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel


@pytest.fixture
def claimed(tmp_path, monkeypatch):
    acquire = polling_claims.acquire_telegram_claim
    monkeypatch.setattr(polling_claims, "acquire_telegram_claim",
                        lambda token: acquire(token, root=tmp_path / "install"))
    channels = []

    def make(token="offline-token"):
        channel = TelegramChannel(token=token)
        channel._get_me = AsyncMock(return_value={"id": 42, "username": "offline_bot"})
        channel.publish_command_menu = AsyncMock(return_value=True)
        channel._resume_offset = Mock()

        async def poll():
            await asyncio.Event().wait()

        channel._poll_loop = poll
        channels.append(channel)
        return channel

    return make


async def close(*channels):
    for channel in channels:
        await channel.stop()


@pytest.mark.asyncio
async def test_same_token_second_instance_does_no_startup_work_until_owner_stops(claimed):
    first, second = claimed(), claimed()
    try:
        await first.start()
        await second.start()
        second._get_me.assert_not_awaited()
        second.publish_command_menu.assert_not_awaited()
        second._resume_offset.assert_not_called()
        assert second._poll_task is None and not second._running
        assert second.health_snapshot()["fatal"] == "polling_claim_busy"
        await first.stop()
        await second.start()
        second._get_me.assert_awaited_once()
        assert second._running and second._poll_task is not None
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_unavailable_claim_fails_closed_before_identity_or_cursor(claimed, tmp_path):
    # The helper refuses a non-directory claim root before opening a lock file.
    (tmp_path / ".install-channel-claims").write_text("unsafe")
    channel = claimed()
    try:
        await channel.start()
        channel._get_me.assert_not_awaited()
        channel._resume_offset.assert_not_called()
        channel.publish_command_menu.assert_not_awaited()
        assert not channel._running and channel._poll_task is None
        assert channel.health_snapshot()["fatal"] == "polling_claim_unavailable"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_independent_managers_conflict_without_second_startup_http(claimed, monkeypatch):
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    first, second = claimed(), claimed()
    owner, contender = ChannelManager(), ChannelManager()
    owner.register(first)
    contender.register(second)
    try:
        await owner.start_all()
        assert first._running
        await contender.start_all()
        second._get_me.assert_not_awaited()
        second._resume_offset.assert_not_called()
        assert (await contender.platform_snapshot())["telegram"]["fatal"] == "polling_claim_busy"
        await owner.stop_all()
        await contender.start_all()
        second._get_me.assert_awaited_once()
        assert second._running
    finally:
        await owner.stop_all()
        await contender.stop_all()


@pytest.mark.asyncio
async def test_distinct_tokens_start_independently_and_redundant_start_is_noop(claimed):
    first, second = claimed("token-one"), claimed("token-two")
    try:
        await first.start()
        original = first._poll_task
        await first.start()
        await second.start()
        first._get_me.assert_awaited_once()
        first.publish_command_menu.assert_awaited_once()
        assert first._poll_task is original and second._running
        second._get_me.assert_awaited_once()
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_failed_start_retains_claim_and_same_instance_cannot_restart_before_stop(claimed):
    first, second = claimed(), claimed()
    first._get_me.side_effect = RuntimeError("offline identity failure")
    try:
        with pytest.raises(RuntimeError, match="offline identity failure"):
            await first.start()
        assert not first._running and first._poll_claim is not None
        await first.start()
        first._get_me.assert_awaited_once()
        assert first.health_snapshot()["fatal"] == "polling_cleanup_required"
        await second.start()
        second._get_me.assert_not_awaited()
        await first.stop()
        await second.start()
        second._get_me.assert_awaited_once()
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_cancelled_start_keeps_claim_until_stop_and_waiting_start_cancels_cleanly(claimed):
    first, second = claimed(), claimed()
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait_for_identity():
        entered.set()
        await release.wait()

    first._get_me = AsyncMock(side_effect=wait_for_identity)
    starting = asyncio.create_task(first.start())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        redundant = asyncio.create_task(first.start())
        await asyncio.sleep(0)
        redundant.cancel()
        with pytest.raises(asyncio.CancelledError):
            await redundant
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not first._running and first._poll_claim is not None
        await second.start()
        second._get_me.assert_not_awaited()
        release.set()  # The retained identity request must actually settle first.
        await first.stop()
        await second.start()
        second._get_me.assert_awaited_once()
    finally:
        release.set()
        starting.cancel()
        await close(first, second)


@pytest.mark.asyncio
async def test_overlapping_and_cancelled_stop_retains_claim_until_completed(claimed, monkeypatch):
    first, contender = claimed(), claimed()
    await first.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original_close = first.client.aclose

    async def held_close():
        entered.set()
        await release.wait()
        await original_close()

    monkeypatch.setattr(first.client, "aclose", held_close)
    stopping = asyncio.create_task(first.stop())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second_stop = asyncio.create_task(first.stop())
        await asyncio.sleep(0)
        await contender.start()
        contender._get_me.assert_not_awaited()
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert first._poll_claim is not None
        await contender.start()
        contender._get_me.assert_not_awaited()
        release.set()
        await second_stop
        assert first._poll_claim is None
        await contender.start()
        contender._get_me.assert_awaited_once()
    finally:
        release.set()
        stopping.cancel()
        await close(first, contender)


@pytest.mark.asyncio
async def test_double_stop_releases_only_its_owned_claim(claimed):
    first, second = claimed(), claimed()
    try:
        await first.start()
        await asyncio.gather(first.stop(), first.stop())
        await second.start()
        assert second._running
        await first.stop()  # must not release the newer holder
        third = claimed()
        try:
            await third.start()
            third._get_me.assert_not_awaited()
            assert third.health_snapshot()["fatal"] == "polling_claim_busy"
        finally:
            await third.stop()
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_cancelled_stop_blocks_same_instance_restart_until_retry_completes(claimed, monkeypatch):
    channel = claimed()
    await channel.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original_close = channel.client.aclose

    async def held_close():
        entered.set()
        await release.wait()
        await original_close()

    monkeypatch.setattr(channel.client, "aclose", held_close)
    stopping = asyncio.create_task(channel.stop())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert channel._poll_claim is not None
        await channel.start()
        channel._get_me.assert_awaited_once()
        assert channel.health_snapshot()["fatal"] == "polling_cleanup_required"
        release.set()
        await channel.stop()
        assert channel._poll_claim is None
        await channel.start()
        assert channel._get_me.await_count == 2
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_stop_exception_keeps_claim_until_close_succeeds(claimed, monkeypatch):
    first, second = claimed(), claimed()
    await first.start()
    original_close = first.client.aclose
    attempts = 0

    async def fragile_close():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("offline close failure")
        await original_close()

    monkeypatch.setattr(first.client, "aclose", fragile_close)
    try:
        with pytest.raises(OSError, match="offline close failure"):
            await first.stop()
        assert first._poll_claim is not None
        await second.start()
        second._get_me.assert_not_awaited()
        await first.stop()
        await second.start()
        second._get_me.assert_awaited_once()
    finally:
        await close(first, second)
