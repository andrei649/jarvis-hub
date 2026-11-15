"""Discord connection claims cover SDK startup through settled shutdown."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels import discord as transport
from agents.core.channels import polling_claims
from agents.core.channels.discord import DiscordChannel
from agents.core.channels.manager import ChannelManager


class OfflineClient:
    def __init__(self, *, intents, calls):
        calls.append("client")
        self.calls = calls
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()
        self.close_entered = asyncio.Event()
        self.close_release = None
        self.resist_cancel = False
        self.close_failure = False
        self.user = SimpleNamespace(id=900)
        self.events = {}
        self.ready = False

    def event(self, callback):
        self.events[callback.__name__] = callback
        return callback

    async def start(self, token):
        self.calls.append(("start", token))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if self.resist_cancel:
                await self.release.wait()
            else:
                raise

    async def close(self):
        self.calls.append("close")
        self.close_entered.set()
        if self.close_failure:
            raise RuntimeError("offline close failure")
        if self.close_release is not None:
            await self.close_release.wait()

    def is_ready(self):
        return self.ready

    def is_closed(self):
        return self.close_entered.is_set()


@pytest.fixture
def offline(tmp_path, monkeypatch):
    original = polling_claims.acquire_discord_claim
    monkeypatch.setattr(polling_claims, "acquire_discord_claim",
                        lambda token: original(token, root=tmp_path / "install"))
    clients, calls = [], []

    def create_client(**kwargs):
        client = OfflineClient(calls=calls, **kwargs)
        clients.append(client)
        return client

    def intents():
        calls.append("intents")
        return SimpleNamespace(message_content=False)

    monkeypatch.setattr(transport, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(transport, "discord", SimpleNamespace(
        Intents=SimpleNamespace(default=intents), Client=create_client))
    return clients, calls


async def close(*channels):
    for channel in channels:
        await channel.stop()


async def emit_ready(client):
    client.ready = True
    await client.events["on_ready"]()


async def start_ready(channel, clients, *, concurrent=1):
    """Keep the SDK lifetime task alive while satisfying actual startup readiness."""
    previous = len(clients)
    starters = [asyncio.create_task(channel.start()) for _ in range(concurrent)]
    async with asyncio.timeout(1):
        while len(clients) <= previous:
            await asyncio.sleep(0)
    client = clients[-1]
    await asyncio.wait_for(client.started.wait(), 1)
    await emit_ready(client)
    await asyncio.wait_for(asyncio.gather(*starters), 1)
    return client


@pytest.mark.asyncio
async def test_same_token_contender_does_no_sdk_work_until_owner_stops(offline):
    clients, calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    try:
        await start_ready(first, clients)
        await asyncio.wait_for(clients[0].started.wait(), 1)
        await second.start()
        assert calls == ["intents", "client", ("start", "opaque-token")]
        assert second._client is None and not second._running
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        await first.stop()
        await start_ready(second, clients)
        assert second._running and len(clients) == 2
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_unavailable_claim_refuses_before_sdk_setup(offline, tmp_path):
    (tmp_path / ".install-channel-claims").write_text("unsafe")
    clients, calls = offline
    channel = DiscordChannel("opaque-token")
    try:
        await channel.start()
        assert clients == [] and calls == []
        assert not channel._running
        assert channel.health_snapshot()["fatal"] == "connection_claim_unavailable"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_distinct_tokens_and_telegram_namespace_start_independently(offline, tmp_path):
    clients, _calls = offline
    first, second = DiscordChannel("one-token"), DiscordChannel("two-token")
    # The other channel's claim namespace cannot lock out a Discord connection.
    telegram = polling_claims.acquire_telegram_claim("one-token", root=tmp_path / "install")
    try:
        await start_ready(first, clients)
        await start_ready(second, clients)
        assert len(clients) == 2 and first._running and second._running
    finally:
        await close(first, second)
        telegram.release()


@pytest.mark.asyncio
async def test_overlapping_and_redundant_starts_create_one_sdk_task(offline):
    clients, calls = offline
    channel = DiscordChannel("opaque-token")
    try:
        await start_ready(channel, clients, concurrent=2)
        task = channel._start_task
        await channel.start()
        assert channel._start_task is task
        assert len(clients) == 1
        assert calls.count("intents") == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_failed_start_keeps_claim_until_successful_stop(offline, monkeypatch):
    clients, calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    original = first._install_slash_tree

    def fail_once():
        first._install_slash_tree = original
        raise RuntimeError("offline setup failure")

    first._install_slash_tree = fail_once
    try:
        with pytest.raises(RuntimeError, match="offline setup failure"):
            await first.start()
        assert not first._running and first._connection_claim is not None
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        assert len(clients) == 1 and ("start", "opaque-token") not in calls
        await first.stop()
        await start_ready(second, clients)
        assert second._running
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_cancelled_start_keeps_claim_until_explicit_stop(offline):
    clients, _calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    prior_entered, prior_cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def prior_callback():
        prior_entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            prior_cancelled.set()
            await release.wait()

    prior = asyncio.create_task(prior_callback())
    await asyncio.wait_for(prior_entered.wait(), 1)
    first._pending_callback_fast[1] = prior
    starting = asyncio.create_task(first.start())
    try:
        await asyncio.wait_for(prior_cancelled.wait(), 1)
        assert first._connection_claim is not None and clients == []
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not first._running and first._connection_claim is not None
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        release.set()
        await first.stop()
        await start_ready(second, clients)
        assert second._running
    finally:
        release.set()
        starting.cancel()
        await asyncio.gather(prior, starting, return_exceptions=True)
        await close(first, second)


@pytest.mark.asyncio
async def test_closed_client_with_unsettled_sdk_task_keeps_contender_busy(offline):
    clients, _calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    try:
        await start_ready(first, clients)
        client = clients[0]
        client.resist_cancel = True
        await asyncio.wait_for(client.started.wait(), 1)
        stopping = asyncio.create_task(first.stop())
        await asyncio.wait_for(client.cancelled.wait(), 1)
        assert client.close_entered.is_set() and not stopping.done()
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        client.release.set()
        await asyncio.wait_for(stopping, 1)
        await start_ready(second, clients)
        assert second._running
    finally:
        if clients:
            clients[0].release.set()
        await close(first, second)


@pytest.mark.asyncio
async def test_cancelled_stop_retains_claim_until_task_settles_and_explicit_stop(offline):
    clients, _calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    try:
        await start_ready(first, clients)
        client = clients[0]
        client.resist_cancel = True
        await asyncio.wait_for(client.started.wait(), 1)
        stopping = asyncio.create_task(first.stop())
        await asyncio.wait_for(client.cancelled.wait(), 1)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert first._connection_claim is not None and not first._start_task.done()
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        client.release.set()
        await asyncio.wait_for(first._start_task, 1)
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        await first.stop()
        await start_ready(second, clients)
        assert second._running
    finally:
        if clients:
            clients[0].release.set()
        await close(first, second)


@pytest.mark.asyncio
async def test_failed_client_close_retains_claim_until_retry(offline):
    clients, _calls = offline
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    try:
        await start_ready(first, clients)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        client.close_failure = True
        with pytest.raises(RuntimeError, match="offline close failure"):
            await first.stop()
        assert first._connection_claim is not None
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        client.close_failure = False
        await first.stop()
        await start_ready(second, clients)
        assert second._running
    finally:
        if clients:
            clients[0].close_failure = False
        await close(first, second)


@pytest.mark.asyncio
async def test_overlapping_stops_are_serialized_and_release_exactly_once(offline):
    clients, _calls = offline
    channel = DiscordChannel("opaque-token")
    try:
        await start_ready(channel, clients)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        client.close_release = asyncio.Event()
        first = asyncio.create_task(channel.stop())
        await asyncio.wait_for(client.close_entered.wait(), 1)
        second = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        client.close_release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert channel._connection_claim is None
        replacement = DiscordChannel("opaque-token")
        try:
            await start_ready(replacement, clients)
            await channel.stop()
            third = DiscordChannel("opaque-token")
            try:
                await third.start()
                assert third.health_snapshot()["fatal"] == "connection_claim_busy"
            finally:
                await third.stop()
        finally:
            await replacement.stop()
    finally:
        if clients and clients[0].close_release is not None:
            clients[0].close_release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_existing_fake_client_without_start_task_still_stops(offline):
    channel = DiscordChannel("opaque-token")
    client = OfflineClient(intents=object(), calls=[])
    channel._client = client
    channel._running = True
    await channel.stop()
    assert client.close_entered.is_set()
    assert channel._connection_claim is None


@pytest.mark.asyncio
async def test_manager_replacement_waits_for_retired_sdk_task(offline, monkeypatch):
    from agents.core import lifecycle_budget
    from agents.core.channels import delivery_ledger

    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.05)
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    clients, _calls = offline
    manager = ChannelManager()
    first, second = DiscordChannel("opaque-token"), DiscordChannel("opaque-token")
    manager.register(first)
    try:
        starting = asyncio.create_task(manager.start_all())
        while not clients:
            await asyncio.sleep(0)
        await asyncio.wait_for(clients[0].started.wait(), 1)
        await emit_ready(clients[0])
        await asyncio.wait_for(starting, 1)
        client = clients[0]
        client.resist_cancel = True
        await asyncio.wait_for(client.started.wait(), 1)
        manager.register(second)
        await asyncio.wait_for(client.cancelled.wait(), 1)
        restart = asyncio.create_task(manager.start_all())
        await asyncio.wait_for(restart, 1)
        assert second._client is None and not second._running
        assert first._connection_claim is not None
        client.release.set()
        await manager.wait_platform_cleanup("discord")
        restart = asyncio.create_task(manager.start_all())
        while len(clients) < 2:
            await asyncio.sleep(0)
        await asyncio.wait_for(clients[1].started.wait(), 1)
        await emit_ready(clients[1])
        await asyncio.wait_for(restart, 1)
        assert second._running and len(clients) == 2
    finally:
        if clients:
            clients[0].release.set()
        await manager.stop_all()
