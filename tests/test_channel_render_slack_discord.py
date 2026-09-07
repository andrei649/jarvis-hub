"""Hermes absorption 4d — Slack and Discord get text they can actually display.

Slack renders `mrkdwn` (`*bold*`, `_italic_`, `<url|text>`, `&amp; &lt; &gt;` escaped) and
caps a message at 40,000 characters; Discord renders Markdown itself and caps at 2,000. Both
adapters now declare that and send rendered, chunked text.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.channels.descriptor import (  # noqa: E402
    DIALECT_MARKDOWN,
    DIALECT_SLACK_MRKDWN,
    ChannelDescriptor,
)
from agents.core.channels.discord import DISCORD_MAX_MESSAGE_LENGTH, DiscordChannel  # noqa: E402
from agents.core.channels.render import render, render_outbound, to_slack_mrkdwn  # noqa: E402
from agents.core.channels.slack import SLACK_MAX_MESSAGE_LENGTH, SlackChannel  # noqa: E402


def test_descriptors_declare_the_dialect_and_the_cap():
    assert SlackChannel.descriptor.dialect == DIALECT_SLACK_MRKDWN
    assert SlackChannel.descriptor.max_message_length == SLACK_MAX_MESSAGE_LENGTH == 40_000
    assert DiscordChannel.descriptor.dialect == DIALECT_MARKDOWN
    assert DiscordChannel.descriptor.max_message_length == DISCORD_MAX_MESSAGE_LENGTH == 2_000
    assert SlackChannel.descriptor.supports_edit and DiscordChannel.descriptor.supports_edit


def test_mrkdwn_converts_balanced_markers_and_escapes():
    assert to_slack_mrkdwn("**b** and *i* and `x<y` & [t](https://u.example)") == (
        "*b* and _i_ and `x&lt;y` &amp; <https://u.example|t>"
    )
    assert to_slack_mrkdwn("# Title\n__strong__ and _soft_") == "*Title*\n*strong* and _soft_"
    assert to_slack_mrkdwn("3 * 4 and **unclosed") == "3 * 4 and **unclosed"
    assert to_slack_mrkdwn("```\na < b **raw**\n```") == "```\na &lt; b **raw**\n```"
    assert render("**b**", DIALECT_SLACK_MRKDWN) == "*b*"


def test_markdown_passes_through_and_is_only_chunked():
    assert render("**b** <tag>", DIALECT_MARKDOWN) == "**b** <tag>"
    descriptor = ChannelDescriptor(dialect=DIALECT_MARKDOWN, max_message_length=2000)
    pieces = render_outbound("\n\n".join("word " * 300 for _ in range(3)), descriptor)
    assert len(pieces) >= 2 and all(len(p) <= 2000 for p in pieces)
    assert pieces[0].startswith("word")


class _SlackClient:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, channel, text):
        self.posts.append((channel, text))
        return {"ok": True}


@pytest.mark.asyncio
async def test_slack_sends_rendered_chunks_in_order():
    channel = SlackChannel("tok")
    channel._client = _SlackClient()
    text = "**Report**\n\n" + "\n\n".join("line " * 6000 for _ in range(2))
    assert await channel.send(text, channel="C123") is True
    posts = channel._client.posts
    assert len(posts) == 2  # ~60,000 characters of source: two messages under the cap, in order
    assert posts[0][1].startswith("*Report*\n\nline line")
    assert posts[1][1].startswith("line line")
    assert all(len(t) <= SLACK_MAX_MESSAGE_LENGTH and c == "C123" for c, t in posts)
    assert await channel.send("hi") is False  # no channel named


class _DiscordChannelStub:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_discord_chunks_at_two_thousand():
    channel = DiscordChannel("tok")
    stub = _DiscordChannelStub()
    channel._client = SimpleNamespace(is_ready=lambda: True, get_channel=lambda cid: stub)
    assert await channel.send("\n\n".join("para " * 300 for _ in range(3)), channel_id="99") is True
    assert len(stub.sent) >= 2 and all(len(t) <= DISCORD_MAX_MESSAGE_LENGTH for t in stub.sent)
    assert stub.sent[0].startswith("para")
    channel._client = SimpleNamespace(is_ready=lambda: False, get_channel=lambda cid: stub)
    assert await channel.send("x", channel_id="99") is False
