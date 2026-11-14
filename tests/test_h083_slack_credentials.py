"""Slack credential preflight is local, fatal, and preserves manual ingress."""

import pytest

from agents.core.channels import slack
from tests.test_slack_socket_mode import sdk  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("bot,app", [
    ("", ""), (" ", ""), (None, ""), (True, ""),
    ("YOUR_SLACK_BOT_TOKEN", ""), ("${SLACK_BOT_TOKEN}", ""),
    ("bot", " "), ("bot", None), ("bot", "replace_me"),
    ("bot", "<slack-app-token>"),
])
async def test_invalid_bot_or_supplied_app_refuses_before_sdk_and_marks_fixed_fatal(
    sdk, monkeypatch, caplog, bot, app,
):
    constructed = []
    original = slack.WebClient

    def web_client(*args, **kwargs):
        constructed.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(slack, "WebClient", web_client)
    channel = slack.SlackChannel(bot, app_token=app)
    try:
        await channel.start()
        assert constructed == [] and sdk.sockets == []
        assert channel._client is None and channel._socket_client is None
        assert not channel._running and channel._dispatch_task is None
        assert channel.health_snapshot()["state"] == "fatal"
        assert channel.health_snapshot()["fatal"] == "invalid_credential"
        if isinstance(bot, str) and len(bot.strip()) >= 8:
            assert bot not in caplog.text
        if isinstance(app, str) and len(app.strip()) >= 8:
            assert app not in caplog.text
    finally:
        await channel.stop()
    assert channel.health_snapshot()["fatal"] == "invalid_credential"


@pytest.mark.asyncio
async def test_empty_optional_app_token_keeps_manual_ingress_and_opaque_bot_bytes(sdk):
    raw = " bot opaque token "
    channel = slack.SlackChannel(raw, app_token="")
    try:
        await channel.start()
        assert channel._running is True and channel._client is not None
        assert channel._client.token == raw
        assert channel._socket_client is None and sdk.sockets == []
        assert channel.health_snapshot()["fatal"] is None
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_valid_opaque_app_token_is_forwarded_unchanged_to_offline_sdk(sdk):
    raw_app = " app opaque token "
    channel = slack.SlackChannel("bot", app_token=raw_app)
    try:
        await channel.start()
        assert channel._running is True
        assert sdk.sockets[0].app_token == raw_app
        assert sdk.sockets[0].web_client.token == "bot"
    finally:
        await channel.stop()
