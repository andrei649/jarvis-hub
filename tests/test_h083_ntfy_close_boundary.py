"""A bounded manager stop must not cancel ntfy's actual stream teardown twice."""

import asyncio

import pytest

from agents.core import lifecycle_budget
from agents.core.channels.manager import ChannelManager
from tests.test_ntfy_inbound import setup_channel, until


@pytest.mark.asyncio
async def test_timed_out_stop_retains_the_stream_until_close_settles(tmp_path, monkeypatch):
    channel, _, _, _, requests, stream = setup_channel(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    cancellations = []

    async def close():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancellations.append(True)
            raise
        stream.closed = True

    monkeypatch.setattr(stream, "aclose", close)
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.02)
    manager = ChannelManager()
    try:
        await channel.start()
        await until(lambda: bool(requests))
        assert not await manager._bounded_platform_stop("ntfy", channel)
        await manager.wait_platform_cleanup("ntfy")
        assert entered.is_set()
        assert cancellations == []
        assert not stream.closed
        await channel.start()
        assert len(requests) == 1 and not channel._running
        release.set()
        await asyncio.wait_for(channel.stop(), 2)
        assert stream.closed
        assert not channel.health_snapshot()["circuit"]["probe_active"]
    finally:
        release.set()
        await channel.stop()
        await manager.wait_platform_cleanup("ntfy")


@pytest.mark.asyncio
async def test_quiet_timer_cannot_heal_a_changed_subscription(tmp_path, monkeypatch):
    from agents.core.channels import ntfy

    channel, _, _, _, requests, _ = setup_channel(tmp_path)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def quiet(_seconds):
        entered.set()
        await release.wait()
        finished.set()

    monkeypatch.setattr(ntfy, "_quiet_sleep", quiet)
    try:
        await channel.start()
        await asyncio.wait_for(entered.wait(), 1)
        timer = channel._healthy_timer
        channel._token = "changed-subscription"
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        await timer
        assert channel.health_snapshot()["state"] != "healthy"
        assert channel.health_snapshot()["circuit"]["probe_active"]
        assert len(requests) == 1
    finally:
        release.set()
        await channel.stop()
