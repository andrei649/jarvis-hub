"""H083: SDK reconnect snapshots distinguish startup from a lost live socket."""

from __future__ import annotations

import asyncio
import threading

import pytest

from agents.core.channels import discord as discord_channel
from agents.core.channels import polling_claims, slack
from agents.core.channels.manager import ChannelManager


@pytest.fixture
def slack_sdk(monkeypatch):
    sockets = []

    class WebClient:
        def __init__(self, **kwargs):
            pass

        def auth_test(self):
            return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    class Socket:
        def __init__(self, connected=True):
            self.connected = connected
            self.socket_mode_request_listeners = []
            self.current_session_runner = type("Runner", (), {"is_alive": lambda runner: self.connected})()
            self.current_app_monitor = type("Runner", (), {"is_alive": lambda runner: self.connected})()
            self.message_processor = type("Runner", (), {"is_alive": lambda runner: self.connected})()

        def connect(self):
            return None  # SDK connect completion alone does not prove readiness.

        def is_connected(self):
            return self.connected

        def close(self):
            self.connected = False

    def factory(*_a, **_kw):
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", WebClient, raising=False)
    monkeypatch.setattr(slack, "_socket_client", factory)
    return sockets


@pytest.mark.asyncio
async def test_slack_initial_not_ready_then_actual_socket_disconnect_and_reconnect(slack_sdk):
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    socket = slack_sdk[0]
    try:
        socket.connected = False
        first = channel.health_snapshot()
        assert first["state"] == "retrying" and first["failures"] == 1
        assert channel.health_snapshot()["failures"] == 1
        socket.connected = True
        assert channel.health_snapshot()["state"] == "healthy"
        assert channel.health_snapshot()["failures"] == 0
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_slack_initial_connect_in_flight_has_zero_failures(slack_sdk, monkeypatch):
    channel = slack.SlackChannel("bot", app_token="app")
    original = slack._socket_client
    entered, release = threading.Event(), threading.Event()

    def unopened(*args, **kwargs):
        socket = original(*args, **kwargs)
        socket.connected = False

        def connect():
            entered.set()
            release.wait(2)

        socket.connect = connect
        return socket

    monkeypatch.setattr(slack, "_socket_client", unopened)
    starting = asyncio.create_task(channel.start())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert channel.health_snapshot()["state"] == "retrying"
        assert channel.health_snapshot()["failures"] == 0
    finally:
        release.set()
        await starting
        await channel.stop()
    assert not channel._running and slack_sdk[0].connected is False


@pytest.mark.asyncio
async def test_slack_stop_restart_resets_client_generation_and_manager_pause(slack_sdk):
    channel = slack.SlackChannel("bot", app_token="app")
    manager = ChannelManager()
    manager.register(channel)
    await channel.start()
    first = slack_sdk[0]
    old_generation = channel._socket_generation
    first.connected = False
    assert (await manager.pause_failed("slack"))["status"] == "paused"
    assert not channel._running
    assert (await manager.resume_paused("slack"))["status"] == "resumed"
    second = slack_sdk[1]
    try:
        assert channel.health_snapshot()["failures"] == 0
        first.connected = True
        assert channel._observe_socket(first, old_generation) is None
        assert channel.health_snapshot()["failures"] == 0
        second.connected = False
        assert channel.health_snapshot()["failures"] == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_slack_socket_replacement_during_probe_cannot_mark_old_ready(slack_sdk):
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    old, old_generation = slack_sdk[0], channel._socket_generation

    def replaced_mid_probe():
        channel._socket_client = object()
        channel._socket_generation = object()
        return True

    old.is_connected = replaced_mid_probe
    try:
        assert channel._observe_socket(old, old_generation) is None
        assert channel._socket_ready_generation is not channel._socket_generation
    finally:
        channel._socket_client = old
        channel._socket_generation = old_generation
        await channel.stop()


@pytest.mark.asyncio
async def test_slack_unreadable_probe_after_ready_cannot_authorize_pause(slack_sdk):
    channel = slack.SlackChannel("bot", app_token="app")
    manager = ChannelManager()
    manager.register(channel)
    await channel.start()
    socket = slack_sdk[0]

    def unreadable():
        raise RuntimeError("SDK probe failed")

    socket.is_connected = unreadable
    try:
        health = channel.health_snapshot()
        assert health["state"] == "unknown" and health["failures"] == 0
        assert (await manager.pause_failed("slack"))["status"] == "not_failed"
        assert channel._running and socket.connected
    finally:
        await channel.stop()


@pytest.fixture
def discord_sdk(monkeypatch, tmp_path):
    if discord_channel.discord is None:
        pytest.skip("optional discord.py SDK not installed")
    clients = []

    class Client:
        def __init__(self, *, intents):
            self.ready = self.closed = False
            self.user = "offline-bot"
            self.events = {}
            self.wait = asyncio.Event()
            self.started = asyncio.Event()
            clients.append(self)

        def event(self, fn):
            self.events[fn.__name__] = fn
            return fn

        async def start(self, token):
            self.started.set()
            await self.wait.wait()

        async def close(self):
            self.closed = True
            self.ready = False
            self.wait.set()

        def is_ready(self):
            return self.ready

        def is_closed(self):
            return self.closed

    monkeypatch.setattr(discord_channel.discord, "Client", Client)
    acquire = polling_claims.acquire_discord_claim
    monkeypatch.setattr(
        polling_claims, "acquire_discord_claim",
        lambda token: acquire(token, root=tmp_path / "install"),
    )
    return clients


async def start_discord_pending(channel, clients):
    previous = len(clients)
    starting = asyncio.create_task(channel.start())
    async with asyncio.timeout(1):
        while len(clients) <= previous:
            await asyncio.sleep(0)
    client = clients[-1]
    await asyncio.wait_for(client.started.wait(), 1)
    return starting, client


async def emit_discord_ready(starting, client):
    client.ready = True
    await client.events["on_ready"]()
    await asyncio.wait_for(starting, 1)


@pytest.mark.asyncio
async def test_discord_initial_not_ready_then_ready_disconnect_reconnect(discord_sdk):
    channel = discord_channel.DiscordChannel(token="offline")
    starting, client = await start_discord_pending(channel, discord_sdk)
    try:
        assert not starting.done()
        assert channel.health_snapshot()["state"] == "retrying"
        assert channel.health_snapshot()["failures"] == 0
        await emit_discord_ready(starting, client)
        assert channel.health_snapshot()["state"] == "healthy"
        client.ready = False
        assert channel.health_snapshot()["failures"] == 1
        assert channel.health_snapshot()["failures"] == 1
        client.ready = True
        assert channel.health_snapshot()["failures"] == 0
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_discord_stale_ready_callback_cannot_mark_replacement(discord_sdk):
    channel = discord_channel.DiscordChannel(token="offline")
    starting, old = await start_discord_pending(channel, discord_sdk)
    await emit_discord_ready(starting, old)
    await channel.stop()
    starting, new = await start_discord_pending(channel, discord_sdk)
    try:
        old.ready = True
        await old.events["on_ready"]()
        assert channel.health_snapshot()["failures"] == 0
        assert channel.health_snapshot()["state"] == "retrying"
        await emit_discord_ready(starting, new)
        assert channel.health_snapshot()["state"] == "healthy"
        new.ready = False
        assert channel.health_snapshot()["failures"] == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_discord_manager_pauses_only_confirmed_disconnect(discord_sdk):
    channel = discord_channel.DiscordChannel(token="offline")
    manager = ChannelManager()
    manager.register(channel)
    starting, client = await start_discord_pending(channel, discord_sdk)
    assert (await manager.pause_failed("discord"))["status"] == "not_failed"
    await emit_discord_ready(starting, client)
    client.ready = False
    assert (await manager.pause_failed("discord"))["status"] == "paused"
    assert not channel._running


@pytest.mark.asyncio
async def test_discord_unreadable_probe_after_ready_cannot_authorize_pause(discord_sdk):
    channel = discord_channel.DiscordChannel(token="offline")
    manager = ChannelManager()
    manager.register(channel)
    starting, client = await start_discord_pending(channel, discord_sdk)
    await emit_discord_ready(starting, client)

    def unreadable():
        raise RuntimeError("SDK probe failed")

    client.is_ready = unreadable
    try:
        health = channel.health_snapshot()
        assert health["state"] == "unknown" and health["failures"] == 0
        assert (await manager.pause_failed("discord"))["status"] == "not_failed"
        assert channel._running and not client.closed
    finally:
        await channel.stop()
