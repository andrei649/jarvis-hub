"""Discord opening deadlines retain SDK and claim ownership through cleanup."""
import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels import discord as transport
from agents.core.channels import polling_claims
from agents.core.channels.discord import DiscordChannel


class FakeClient:
    def __init__(self, **_kwargs):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.ready = False
        self.closed = False
        self.events = {}
        self.user = SimpleNamespace(id=900)
        self.close_failure = False

    def event(self, callback):
        self.events[callback.__name__] = callback
        return callback

    async def start(self, _token):
        self.started.set()
        await self.release.wait()

    async def close(self):
        if self.close_failure:
            raise RuntimeError("offline close failure")
        self.closed = True
        self.ready = False
        self.release.set()

    def is_ready(self):
        return self.ready

    def is_closed(self):
        return self.closed

    async def emit_ready(self):
        self.ready = True
        await self.events["on_ready"]()

    async def emit_message(self, message):
        await self.events["on_message"](message)


@pytest.fixture
def setup_discord(tmp_path, monkeypatch):
    original = polling_claims.acquire_discord_claim
    monkeypatch.setattr(polling_claims, "acquire_discord_claim",
                        lambda token: original(token, root=tmp_path / "install"))
    clients = []

    def create_client(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(transport, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(transport, "discord", SimpleNamespace(
        Intents=SimpleNamespace(default=lambda: SimpleNamespace(message_content=False)),
        Client=create_client,
    ))
    return clients


@pytest.mark.asyncio
async def test_unready_start_times_out_but_keeps_sdk_task_and_claim(setup_discord):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 0.03
    try:
        await channel.start()
        client = clients[0]
        assert not channel._running
        assert channel.health_snapshot()["fatal"] == "connect_timeout"
        assert channel._start_task is not None and not channel._start_task.done()
        assert channel._client is client and not client.closed
        assert channel._connection_claim is not None
    finally:
        await channel.stop()
    assert channel._connection_claim is None


@pytest.mark.asyncio
async def test_timely_on_ready_admits_and_reconnect_remains_healthy(setup_discord):
    clients = setup_discord
    delivered = []
    channel = DiscordChannel("opaque-token", handler=lambda *a, **k: delivered.append((a, k)))
    channel._connect_timeout_seconds = 0.2
    starting = asyncio.create_task(channel.start())
    try:
        while not clients:
            await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        assert not starting.done()
        await client.emit_message(SimpleNamespace(
            author=SimpleNamespace(id=1, bot=False), channel=SimpleNamespace(id=2, parent_id=None),
            guild=None, content="too early", id=3))
        assert delivered == []
        await client.emit_ready()
        await asyncio.wait_for(starting, 1)
        assert channel.health_snapshot()["state"] == "healthy"
        client.ready = False
        assert channel.health_snapshot()["state"] == "retrying"
        client.ready = True
        assert channel.health_snapshot()["state"] == "healthy"
    finally:
        if not starting.done():
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_early_sdk_error_fails_start_without_releasing_claim(setup_discord, monkeypatch):

    class LoginFailure(Exception):
        pass

    async def failed_start(self, _token):
        self.started.set()
        raise LoginFailure("opaque SDK error")

    monkeypatch.setattr(FakeClient, "start", failed_start)
    channel = DiscordChannel("opaque-token")
    try:
        await channel.start()
        assert channel.health_snapshot()["fatal"] == "unauthorized"
        assert not channel._running
        assert channel._connection_claim is not None
        assert channel._start_task.done()
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_late_ready_and_message_callbacks_are_fenced_after_timeout(setup_discord, monkeypatch):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 0.02
    handled = []
    channel.handler = lambda *args, **kwargs: handled.append((args, kwargs))
    await channel.start()
    client = clients[0]
    syncs = []

    async def sync(*_args):
        syncs.append(True)

    monkeypatch.setattr(channel, "_sync_slash_tree", sync)
    message = SimpleNamespace(author=SimpleNamespace(id=1, bot=False),
                              channel=SimpleNamespace(id=2, parent_id=None),
                              guild=None, content="late", id=3)
    try:
        await client.emit_ready()
        await client.emit_message(message)
        assert syncs == []
        assert handled == []
        assert channel.health_snapshot()["fatal"] == "connect_timeout"
        assert channel._connection_claim is not None
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_readiness_wait_retains_task_and_claim_until_stop(setup_discord):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    starting = asyncio.create_task(channel.start())
    try:
        while not clients:
            await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        assert channel._connection_claim is not None
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not channel._running
        assert channel._start_task is not None and not channel._start_task.done()
        assert channel._connection_claim is not None
    finally:
        if not starting.done():
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_ready_callback_observed_after_monotonic_deadline_is_not_admitted(
        setup_discord, monkeypatch):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 0.03
    syncs = []

    async def sync(*_args):
        syncs.append(True)

    monkeypatch.setattr(channel, "_sync_slash_tree", sync)
    original_wait = asyncio.wait

    async def delayed_wait(tasks, **kwargs):
        result = await original_wait(tasks, **kwargs)
        if channel._start_task in tasks:
            # Simulate a busy event loop resuming the admission waiter late.
            await asyncio.sleep(0.05)
        return result

    monkeypatch.setattr(asyncio, "wait", delayed_wait)
    starting = asyncio.create_task(channel.start())
    try:
        while not clients:
            await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        await asyncio.sleep(0.005)
        callback = asyncio.create_task(client.emit_ready())
        await asyncio.wait_for(starting, 1)
        await asyncio.wait_for(callback, 1)
        assert not channel._running
        assert channel.health_snapshot()["fatal"] == "connect_timeout"
        assert syncs == []
        assert channel._connection_claim is not None
    finally:
        if not starting.done():
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_close_failure_keeps_claim_and_blocks_same_token_restart(setup_discord):
    clients = setup_discord
    first = DiscordChannel("opaque-token")
    second = DiscordChannel("opaque-token")
    first._connect_timeout_seconds = 0.02
    second._connect_timeout_seconds = 0.02
    try:
        await first.start()
        clients[0].close_failure = True
        with pytest.raises(RuntimeError, match="offline close failure"):
            await first.stop()
        assert first._connection_claim is not None
        await second.start()
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        clients[0].close_failure = False
        await first.stop()
        assert first._connection_claim is None
    finally:
        clients[0].close_failure = False
        await first.stop()
        await second.stop()

@pytest.mark.asyncio
async def test_cancelled_start_revokes_ingress_before_releasing_held_ready_callback(
        setup_discord, monkeypatch):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 5
    syncs, delivered = [], []
    channel.handler = lambda *a, **k: delivered.append((a, k))

    async def sync(*_args):
        syncs.append(True)

    monkeypatch.setattr(channel, "_sync_slash_tree", sync)
    original_wait = asyncio.wait
    held = asyncio.Event()

    async def hold_after_ready(tasks, **kwargs):
        done, pending = await original_wait(tasks, **kwargs)
        if channel._start_task in tasks and any(task is not channel._start_task for task in done):
            held.set()
            await asyncio.Event().wait()
        return done, pending

    monkeypatch.setattr(asyncio, "wait", hold_after_ready)
    starting = asyncio.create_task(channel.start())
    client = None
    ready_callback = None
    try:
        while not clients:
            await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        ready_callback = asyncio.create_task(client.emit_ready())
        await asyncio.wait_for(held.wait(), 1)
        assert not ready_callback.done()
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        await asyncio.wait_for(ready_callback, 1)
        await client.emit_message(SimpleNamespace(
            author=SimpleNamespace(id=1, bot=False), channel=SimpleNamespace(id=2, parent_id=None),
            guild=None, content="after cancel", id=4))
        assert not channel._running
        assert syncs == [] and delivered == []
        assert channel._connection_claim is not None
        assert channel._start_task is not None and not channel._start_task.done()
    finally:
        if not starting.done():
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
        if ready_callback is not None and not ready_callback.done():
            await asyncio.gather(ready_callback, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_sdk_exit_wins_when_ready_waiter_and_lifetime_task_finish_together(
        setup_discord, monkeypatch):
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 1

    class LoginFailure(Exception):
        pass

    async def ready_then_fail(self, _token):
        self.started.set()
        self.ready = True
        asyncio.create_task(self.events["on_ready"]())
        raise LoginFailure("offline failure")

    monkeypatch.setattr(FakeClient, "start", ready_then_fail)
    original_wait = asyncio.wait

    async def settle_both(tasks, **kwargs):
        done, pending = await original_wait(tasks, **kwargs)
        if channel._start_task in tasks and channel._start_task in done:
            # Let the queued on_ready and ready-event waiter settle in the same
            # cycle before reporting both tasks complete to the adapter.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            done = {task for task in tasks if task.done()}
        return done, pending

    monkeypatch.setattr(asyncio, "wait", settle_both)
    try:
        await channel.start()
        assert channel.health_snapshot()["fatal"] == "unauthorized"
        assert not channel._running
        assert channel._connection_claim is not None
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_sdk_ready_is_not_healthy_until_startup_admission(setup_discord, monkeypatch):
    clients = setup_discord
    channel = DiscordChannel("opaque-token")
    channel._connect_timeout_seconds = 1
    original_wait = asyncio.wait
    admitted_waiter = asyncio.Event()
    release_waiter = asyncio.Event()

    async def hold_admission(tasks, **kwargs):
        result = await original_wait(tasks, **kwargs)
        if channel._start_task in tasks and any(
                task is not channel._start_task for task in result[0]):
            admitted_waiter.set()
            await release_waiter.wait()
        return result

    monkeypatch.setattr(asyncio, "wait", hold_admission)
    starting = asyncio.create_task(channel.start())
    ready_callback = None
    try:
        while not clients:
            await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
        ready_callback = asyncio.create_task(client.emit_ready())
        await asyncio.wait_for(admitted_waiter.wait(), 1)
        assert channel.health_snapshot()["state"] == "retrying"
        assert channel.health_snapshot()["error"] == "not_ready"
        release_waiter.set()
        await asyncio.wait_for(starting, 1)
        await asyncio.wait_for(ready_callback, 1)
        assert channel.health_snapshot()["state"] == "healthy"
    finally:
        release_waiter.set()
        if not starting.done():
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
        if ready_callback is not None and not ready_callback.done():
            await asyncio.gather(ready_callback, return_exceptions=True)
        await channel.stop()
