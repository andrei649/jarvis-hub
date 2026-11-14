"""Credential refusals happen before Telegram startup work, entirely offline."""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from agents.core.channels.telegram import TelegramChannel


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, 123, "", "   ", "YOUR_TELEGRAM_BOT_TOKEN",
                                  "replace_me", "${TELEGRAM_BOT_TOKEN}", "<telegram-token>"])
async def test_invalid_credential_never_starts_identity_menu_or_poll(token, monkeypatch, caplog):
    channel = TelegramChannel(token=token)
    initial_generation = channel._pending_callback_generation
    identity = AsyncMock(return_value={"id": 42, "username": "offline_bot"})
    menu, poll, cursor = AsyncMock(), AsyncMock(), Mock()
    monkeypatch.setattr(channel, "_get_me", identity)
    monkeypatch.setattr(channel, "publish_command_menu", menu)
    monkeypatch.setattr(channel, "_poll_loop", poll)
    monkeypatch.setattr(channel, "_resume_offset", cursor)
    try:
        await channel.start()
        identity.assert_not_called()
        menu.assert_not_called()
        poll.assert_not_called()
        cursor.assert_not_called()
        assert channel._running is False
        assert channel._pending_callback_generation is initial_generation
        snapshot = channel.health_snapshot()
        assert snapshot["state"] == "fatal"
        assert snapshot["fatal"] == "invalid_credential"
        if isinstance(token, str) and token.strip():
            assert token not in caplog.text + json.dumps(snapshot)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_refusal_does_not_recreate_closed_http_client(monkeypatch):
    channel = TelegramChannel(token="YOUR_TOKEN")
    await channel.client.aclose()
    factory = Mock(side_effect=AssertionError("invalid startup constructed an HTTP client"))
    monkeypatch.setattr("agents.core.channels.telegram.httpx.AsyncClient", factory)
    await channel.start()
    factory.assert_not_called()
    assert channel.health_snapshot()["fatal"] == "invalid_credential"


@pytest.mark.asyncio
async def test_valid_explicit_retry_keeps_opaque_token_and_clears_local_fatal(monkeypatch):
    token = "  opaque-private-credential  "
    channel = TelegramChannel(token=token)
    identity = AsyncMock(return_value={"id": 42, "username": "offline_bot"})
    monkeypatch.setattr(channel, "_get_me", identity)
    monkeypatch.setattr(channel, "publish_command_menu", AsyncMock())
    monkeypatch.setattr(channel, "_poll_loop", AsyncMock())
    monkeypatch.setattr(channel, "_resume_offset", Mock())
    channel.health.failed_fatally("invalid_credential")
    try:
        await channel.start()
        identity.assert_awaited_once()
        assert channel.token == token
        assert channel._running is True
        assert channel.health_snapshot()["fatal"] is None
    finally:
        await channel.stop()
