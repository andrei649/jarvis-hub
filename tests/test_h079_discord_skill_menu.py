"""A generic native Discord picker keeps skill names out of the global tree."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    import discord
except ImportError:
    discord = None

pytestmark = pytest.mark.skipif(discord is None, reason="optional discord.py SDK not installed")

from agents.core.channels.discord import DiscordChannel
from agents.core.channels.gateway import Gateway
from agents.core.channels.pairing import SenderPairing
from tests.test_h026_skill_bundles import _hub, _md_skill, isolated  # noqa: F401
from tests.test_h057_discord_commands import interaction


def _ready_channel(orch, handler, *, owner=lambda sender, _channel, _kind: sender == "43"):
    channel = DiscordChannel(
        token="offline", handler=handler, command_registry=orch.commands,
        skill_loader=orch.skills, skill_owner=owner, skill_taken=orch._command_name_taken,
    )
    client = discord.Client(intents=discord.Intents.default())
    client._connection.user = SimpleNamespace(id=99)
    client.is_ready = lambda: True
    channel._client, channel._running, channel._slash_generation = client, True, object()
    channel._install_slash_tree()
    return channel, client


@pytest.mark.asyncio
async def test_generic_picker_is_private_and_routes_selected_skill_through_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"))
    seen = []

    async def handler(text, **kwargs):
        seen.append((text, kwargs))

    pairing = SenderPairing(tmp_path / "pairing.json")
    gateway = Gateway(handler=handler, pairing=pairing)
    channel, client = _ready_channel(orch, gateway.route)
    try:
        assert "skill" in {cmd.name for cmd in channel._slash_tree.get_commands()}
        assert "weather" not in {cmd.name for cmd in channel._slash_tree.get_commands()}
        native = channel._slash_tree.get_command("skill")
        autocomplete = native._params["name"].autocomplete
        channel._skill_projection = lambda: (_ for _ in ()).throw(AssertionError("guest catalog read"))
        assert await autocomplete(interaction(client=client, sender=42), "we") == []
        del channel._skill_projection
        matches = await autocomplete(interaction(client=client, sender=43), "we")
        assert [(choice.name, choice.value) for choice in matches] == [("weather", "weather")]

        await native.callback(interaction(client=client, sender=43), "weather", "tomorrow")
        assert seen == [] and gateway.get_summary()["total_held"] == 1
        pairing.approve("discord", "43")
        await native.callback(interaction(client=client, sender=43, event_id=9002),
                              "weather", "tomorrow")
        assert seen[-1][0] == "/weather tomorrow"
        assert seen[-1][1]["pending_input_eligible"] is False
        assert seen[-1][1]["provider_id"] == "9002"
        pairing.approve("discord", "42")
        await native.callback(interaction(client=client, sender=42, event_id=9003),
                              "weather", "secret")
        assert seen[-1][0] == "/skill"
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_picker_rechecks_live_collisions_and_ack_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)

    channel, client = _ready_channel(orch, handler)
    try:
        native = channel._slash_tree.get_command("skill")
        autocomplete = native._params["name"].autocomplete
        assert len(await autocomplete(interaction(client=client, sender=43), "we")) == 1
        failed = interaction(client=client, sender=43, fail_ack=True)
        await native.callback(failed, "weather")
        assert seen == []
        monkeypatch.setattr(orch, "_command_name_taken", lambda word: word == "skill" or word == "weather")
        channel.skill_taken = orch._command_name_taken
        assert await autocomplete(interaction(client=client, sender=43), "we") == []
        await native.callback(interaction(client=client, sender=43, event_id=9002), "weather")
        assert seen == []
    finally:
        orch.checkpoints.close()


def test_generic_picker_does_not_claim_a_skill_named_skill_or_a_full_tree(tmp_path, monkeypatch):
    from agents.core.commands import CommandRegistry, SlashCommand

    named = _md_skill("weather")
    named.name = "skill"
    orch, _ = _hub(tmp_path, monkeypatch, named)
    try:
        channel, _ = _ready_channel(orch, lambda *args, **kwargs: None)
        assert channel._slash_tree.get_command("skill") is None
        many = CommandRegistry()
        for index in range(100):
            many.register(SlashCommand(f"item{index:03d}", "item", lambda ctx: "ok"))
        channel.command_registry = many
        orch.skills.skills = {"weather": _md_skill("weather")}
        channel.skill_taken = lambda _word: False
        channel._client = discord.Client(intents=discord.Intents.default())
        channel._install_slash_tree()
        assert len(channel._slash_tree.get_commands()) == 100
        assert channel._slash_tree.get_command("skill") is None
        assert channel.health_snapshot()["native_commands_hidden"] == 1
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_canonical_plugin_skill_command_keeps_its_registry_text_path(tmp_path, monkeypatch):
    from agents.core.commands import SlashCommand

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    orch.commands.register(SlashCommand("skill", "Plugin command", lambda ctx: "ok"))
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)

    channel, client = _ready_channel(orch, handler)
    try:
        native = channel._slash_tree.get_command("skill")
        assert [param.name for param in native._params.values()] == ["text"]
        await native.callback(interaction(client=client, sender=43), "plugin text")
        assert seen == ["/skill plugin text"]
    finally:
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_picker_caps_autocomplete_and_rejects_stale_or_bad_identity(tmp_path, monkeypatch):
    skills = []
    for index in range(30):
        skill = _md_skill("weather")
        skill.name = f"weather-{index:02d}"
        skills.append(skill)
    orch, _ = _hub(tmp_path, monkeypatch, *skills)
    channel, client = _ready_channel(orch, lambda *args, **kwargs: None)
    try:
        native = channel._slash_tree.get_command("skill")
        autocomplete = native._params["name"].autocomplete
        assert len(await autocomplete(interaction(client=client, sender=43), "weather")) == 25
        assert await autocomplete(interaction(client=client, sender=43, bot=True), "weather") == []
        assert await autocomplete(interaction(client=client, sender=43, guild="1"), "weather") == []
        old = channel._slash_generation
        channel._slash_generation = object()
        assert await autocomplete(interaction(client=client, sender=43), "weather") == []
        channel._slash_generation = old
        channel._running = False
        assert await autocomplete(interaction(client=client, sender=43), "weather") == []
    finally:
        orch.checkpoints.close()
