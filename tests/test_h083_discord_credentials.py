"""Discord refuses obvious credential placeholders before SDK startup."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels import discord as transport
from agents.core.channels.discord import DiscordChannel


class OfflineClient:
    def __init__(self, *, intents, calls):
        calls.append("client")
        self.intents = intents
        self.calls = calls
        self.user = SimpleNamespace(id=900)
        self.ready = False
        self.events = {}
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def event(self, callback):
        self.events[callback.__name__] = callback
        return callback

    async def start(self, token):
        self.calls.append(("start", token))
        self.started.set()
        await self.release.wait()

    def is_ready(self):
        return self.ready

    def is_closed(self):
        return False

    async def close(self):
        self.calls.append("close")
        self.ready = False
        self.release.set()


@pytest.fixture
def offline_sdk(monkeypatch):
    calls = []

    def intents():
        calls.append("intents")
        return SimpleNamespace(message_content=False)

    monkeypatch.setattr(transport, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(transport, "discord", SimpleNamespace(
        Intents=SimpleNamespace(default=intents),
        Client=lambda **kwargs: OfflineClient(calls=calls, **kwargs),
    ))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [
    None, "", " \t ", "replace_me", "CHANGEme", "token_here",
    "YOUR_BOT_TOKEN", "${DISCORD_BOT_TOKEN}", "<Discord Bot Token>",
    42, True, object(),
])
async def test_invalid_credential_is_fatal_before_sdk_or_task(offline_sdk, caplog, credential):
    channel = DiscordChannel(token=credential)
    generation = channel._pending_callback_generation
    await channel.start()
    assert offline_sdk == []
    assert channel._client is None and not channel._running
    assert getattr(channel, "_start_task", None) is None
    assert channel._pending_callback_generation is generation
    health = channel.health_snapshot()
    assert (health["state"], health["fatal"], health["error"]) == (
        "fatal", "invalid_credential", "invalid_credential")
    assert health["native_commands_registered"] == 0
    if isinstance(credential, str) and credential.strip():
        assert credential not in caplog.text
        assert credential not in str(health)


@pytest.mark.asyncio
async def test_valid_opaque_token_retries_after_local_fatal_without_normalizing_bytes(offline_sdk):
    channel = DiscordChannel(token="token_here")
    await channel.start()
    assert channel.health_snapshot()["fatal"] == "invalid_credential"
    assert offline_sdk == []

    exact = "  opaque.token_here.suffix  "
    channel.token = exact
    starting = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(1):
            while channel._client is None:
                await asyncio.sleep(0)
        client = channel._client
        await asyncio.wait_for(client.started.wait(), 1)
        client.ready = True
        await client.events["on_ready"]()
        await asyncio.wait_for(starting, 1)
        assert offline_sdk == ["intents", "client", ("start", exact)]
        health = channel.health_snapshot()
        assert health["fatal"] is None and health["state"] == "healthy"
        assert channel._running and channel._client is client
        assert channel._start_task is not None and not channel._start_task.done()
    finally:
        await channel.stop()
