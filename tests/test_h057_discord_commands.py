"""H057 native Discord slash commands, kept on the ordinary gateway path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

try:
    import discord
except ImportError:
    discord = None

pytestmark = pytest.mark.skipif(discord is None, reason="optional discord.py SDK not installed")

from agents.core.channels.discord import DiscordChannel
from agents.core.channels.discord_commands import project_commands
from agents.core.channels.gateway import Gateway
from agents.core.channels.pairing import SenderPairing
from agents.core.commands import (
    ADMIN,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)


def test_projection_is_bounded_and_reports_hidden_commands():
    registry = CommandRegistry()
    for index in range(110):
        registry.register(SlashCommand(f"item{index:03d}", "d" * 150, lambda ctx: "ok"))
    projection = project_commands(registry)
    assert len(projection.entries) == 100
    assert projection.hidden_count == 10
    assert projection.entries[0].name == "item000"
    assert all(1 <= len(entry.description) <= 100 for entry in projection.entries)
    channel = DiscordChannel(token="offline", command_registry=registry)
    channel._client = discord.Client(intents=discord.Intents.default())
    channel._install_slash_tree()
    health = channel.health_snapshot()
    assert health["native_commands_registered"] == 100
    assert health["native_commands_hidden"] == 10


def test_real_sdk_command_tree_registers_registry_names_offline():
    registry = build_default_registry()
    channel = DiscordChannel(token="offline", command_registry=registry)
    client = discord.Client(intents=discord.Intents.default())
    channel._client = client
    try:
        channel._install_slash_tree()
        names = {command.name for command in channel._slash_tree.get_commands()}
        assert names == {command.name for command in registry.commands()}
        assert channel._slash_hidden_count == 0
    finally:
        # The client never connected and no Discord API request was made.
        channel._client = None


class Response:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    async def send_message(self, text, **kwargs):
        self.calls.append((text, kwargs))
        if self.fail:
            raise RuntimeError("offline ACK failure")


def interaction(*, sender=42, channel=123, event_id=9001, bot=False, guild=None,
                parent=None, client=None, fail_ack=False):
    return SimpleNamespace(
        id=event_id, user=SimpleNamespace(id=sender, bot=bot), channel_id=channel,
        channel=SimpleNamespace(id=channel, parent_id=parent), guild_id=guild,
        client=client, response=Response(fail=fail_ack),
    )


@pytest.mark.asyncio
async def test_native_interaction_acks_then_reaches_gateway_pairing_and_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "help", lambda ctx: "helped"))
    registry.register(SlashCommand("secret", "secret", lambda ctx: "sensitive", tier=ADMIN))
    pairing = SenderPairing(tmp_path / "pairing.json")
    seen, pending, outcomes = [], [], []

    async def handler(text, *, channel, sender, **kwargs):
        seen.append((text, sender, kwargs))
        outcome = await registry.dispatch(text, orch=None,
                                          principal=Principal(channel=channel, sender=sender,
                                                              admin=sender == "43"))
        outcomes.append(outcome)
        return outcome.reply

    async def consume_pending(*args, **kwargs):
        pending.append((args, kwargs))
        return True

    gateway = Gateway(handler=handler, pairing=pairing, pending_handler=consume_pending)
    channel = DiscordChannel(token="offline", handler=gateway.route,
                             pairing=pairing, command_registry=registry)
    client = discord.Client(intents=discord.Intents.default())
    client._connection.user = SimpleNamespace(id=99)
    client.is_ready = lambda: True
    channel._client = client
    channel._running = True
    channel._slash_generation = object()
    channel._install_slash_tree()
    native_secret = channel._slash_tree.get_command("secret")
    first = interaction(client=client)
    await native_secret.callback(first)
    assert first.response.calls == [("Command received. If admitted, any reply will arrive in this channel.",
                                     {"ephemeral": True})]
    assert seen == [] and pending == [] and gateway.get_summary()["total_held"] == 1

    pairing.approve("discord", "42")
    second = interaction(client=client, event_id=9002)
    await native_secret.callback(second)
    assert seen[-1][0:2] == ("/secret", "42")
    assert seen[-1][2]["pending_input_eligible"] is False
    assert outcomes[-1].name == "secret" and outcomes[-1].status == "refused"
    assert pending == []
    assert gateway.get_summary()["total_messages"] == 1
    await native_secret.callback(second)
    assert len(seen) == 1

    pairing.approve("discord", "43")
    owner = interaction(client=client, sender=43, event_id=9003)
    await native_secret.callback(owner, "extra")
    assert seen[-1][0:2] == ("/secret extra", "43")
    assert outcomes[-1].status == "answered"
    assert gateway.get_summary()["total_messages"] == 2


@pytest.mark.asyncio
async def test_native_sync_is_once_per_live_generation_and_never_calls_network_here():
    channel = DiscordChannel(token="offline", command_registry=build_default_registry())
    client = discord.Client(intents=discord.Intents.default())
    channel._client = client
    channel._running = True
    channel._slash_generation = object()
    channel._install_slash_tree()
    sync = AsyncMock(return_value=[])
    channel._slash_tree.sync = sync
    generation = channel._slash_generation
    await channel._sync_slash_tree(generation, client)
    await channel._sync_slash_tree(generation, client)  # reconnect callback
    sync.assert_awaited_once()
    channel._slash_generation = None  # stop invalidates the old callback
    await channel._sync_slash_tree(generation, client)
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_sync_finishing_after_restart_cannot_clear_new_sync():
    channel = DiscordChannel(token="offline", command_registry=build_default_registry())
    old_client, new_client = object(), object()
    old_started, old_release = asyncio.Event(), asyncio.Event()
    new_started, new_release = asyncio.Event(), asyncio.Event()

    async def old_sync():
        old_started.set()
        await old_release.wait()

    async def new_sync():
        new_started.set()
        await new_release.wait()

    old_gen = object()
    channel._client, channel._running, channel._slash_generation = old_client, True, old_gen
    channel._slash_tree = SimpleNamespace(sync=old_sync)
    old_task = asyncio.create_task(channel._sync_slash_tree(old_gen, old_client))
    await old_started.wait()

    new_gen = object()
    channel._client, channel._slash_generation = new_client, new_gen
    channel._slash_syncing = None
    channel._slash_tree = SimpleNamespace(sync=new_sync)
    new_task = asyncio.create_task(channel._sync_slash_tree(new_gen, new_client))
    await new_started.wait()
    old_release.set()
    await old_task
    assert channel._slash_syncing is new_gen
    await channel._sync_slash_tree(new_gen, new_client)
    assert channel._slash_syncing is new_gen
    new_release.set()
    await new_task
    assert channel._slash_syncing is None and channel._slash_synced is True


@pytest.mark.asyncio
async def test_stale_native_delivery_after_restart_is_dropped():
    seen = []

    async def handler(*args, **kwargs):
        seen.append((args, kwargs))

    channel = DiscordChannel(token="offline", handler=handler)
    old_client, new_client = object(), object()
    old_gen, new_gen = object(), object()
    channel._client, channel._running, channel._slash_generation = old_client, True, old_gen
    queued = {"sender": "42", "channel_id": "123", "provider_id": "9001",
              "pending_input_eligible": False,
              "_slash_generation": old_gen, "_slash_client": old_client}
    channel._client, channel._slash_generation = new_client, new_gen
    await channel._deliver_turn(("123", "42"), "/help", queued)
    assert seen == []
    queued.update(_slash_generation=new_gen, _slash_client=new_client)
    await channel._deliver_turn(("123", "42"), "/help", queued)
    assert seen[0][1]["pending_input_eligible"] is False
    assert "_slash_generation" not in seen[0][1]


@pytest.mark.asyncio
async def test_acked_command_waiting_behind_turn_is_discarded_on_stop(monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "350")
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)
        entered.set()
        await release.wait()

    channel = DiscordChannel(token="offline", handler=handler,
                             command_registry=build_default_registry())

    class Client:
        user = SimpleNamespace(id=99)

        def is_ready(self):
            return True

        async def close(self):
            return None

    client = Client()
    channel._client, channel._running, channel._slash_generation = client, True, object()
    channel._slash_names = frozenset({"help"})
    first = asyncio.create_task(channel._batch.submit(("123", "42"), "/help",
                                                     sender="42", channel_id="123"))
    await entered.wait()
    native = interaction(client=client)
    second = asyncio.create_task(channel._handle_slash_interaction(native, "help", ""))
    for _ in range(10):
        if native.response.calls:
            break
        await asyncio.sleep(0)
    assert native.response.calls and not second.done()
    await channel.stop()
    channel._client, channel._running, channel._slash_generation = Client(), True, object()
    release.set()
    await asyncio.gather(first, second)
    assert seen == ["/help"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"sender": True}, {"sender": 0}, {"channel": "123"}, {"channel": 0},
    {"event_id": True}, {"event_id": 0}, {"bot": True}, {"guild": "1"},
])
async def test_bad_identity_never_reaches_handler(bad):
    seen = []

    async def handler(*args, **kwargs):
        seen.append((args, kwargs))

    channel = DiscordChannel(token="offline", handler=handler)
    client = SimpleNamespace(user=SimpleNamespace(id=99), is_ready=lambda: True)
    channel._client = client
    channel._running = True
    channel._slash_generation = object()
    channel._slash_names = frozenset({"help"})
    event = interaction(client=client, **bad)
    await channel._handle_slash_interaction(event, "help", "")
    assert seen == []


@pytest.mark.asyncio
async def test_ack_failure_and_stale_generation_do_not_dispatch():
    seen = []

    async def handler(*args, **kwargs):
        seen.append((args, kwargs))

    channel = DiscordChannel(token="offline", handler=handler)
    client = SimpleNamespace(user=SimpleNamespace(id=99), is_ready=lambda: True)
    channel._client = client
    channel._running = True
    channel._slash_generation = object()
    channel._slash_names = frozenset({"help"})
    failed = interaction(client=client, fail_ack=True)
    await channel._handle_slash_interaction(failed, "help", "")
    assert seen == []
    stale = interaction(client=client, event_id=9002)
    generation = channel._slash_generation
    channel._slash_generation = object()
    await channel._handle_slash_interaction(stale, "help", "", generation=generation)
    assert stale.response.calls == [] and seen == []
