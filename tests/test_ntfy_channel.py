"""Hermes absorption 4g — a push to the owner's phone with no bot and no account.

One HTTP POST to an ntfy server the owner names. Outbound only: the topic is the identity on
ntfy, so nothing that arrives there can become a turn. Chunked at the cap, title and priority
as headers, a bearer token when the server wants one; every send crosses the manager's
contract gate and the escalation router reaches it like any other adapter.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.autonomy.escalation import EscalationRouter  # noqa: E402
from agents.core.channels.descriptor import DIALECT_PLAIN  # noqa: E402
from agents.core.channels.manager import ChannelManager  # noqa: E402
from agents.core.channels.ntfy import NTFY_MAX_MESSAGE_LENGTH, NtfyChannel  # noqa: E402


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, statuses=()):
        self.posts = []
        self.statuses = list(statuses)
        self.closed = False

    async def post(self, url, content=None, headers=None, **kwargs):
        self.posts.append((url, content, dict(headers or {})))
        return _Resp(self.statuses.pop(0) if self.statuses else 200)

    async def aclose(self):
        self.closed = True


def _channel(statuses=(), **kwargs):
    client = _Client(statuses)
    return NtfyChannel("https://ntfy.example/", "nerva-owner", client=client, **kwargs), client


def test_descriptor_and_validation():
    channel, _ = _channel()
    assert channel.channel_id == "ntfy" and channel.url == "https://ntfy.example"
    assert NtfyChannel.descriptor.dialect == DIALECT_PLAIN
    assert NtfyChannel.descriptor.max_message_length == NTFY_MAX_MESSAGE_LENGTH == 4096
    assert not NtfyChannel.descriptor.supports_edit
    for url, topic in (("ftp://x", "t"), ("", "t"), ("https://x", ""), ("https://x", "bad topic"), ("https://x", "x" * 65)):
        with pytest.raises(ValueError):
            NtfyChannel(url, topic, client=_Client())


@pytest.mark.asyncio
async def test_send_posts_plain_chunks_with_title_priority_and_token():
    channel, client = _channel(token="tok-1", title="Casa ✓")
    ok = await channel.send("**alert** the `pump` is on\n\n" + "word " * 1200, priority=5)
    assert ok is True
    assert len(client.posts) >= 2
    url, body, headers = client.posts[0]
    assert url == "https://ntfy.example/nerva-owner"
    assert body.decode("utf-8").startswith("alert the pump is on")       # plain, no markers
    assert headers == {"Title": "Casa", "Priority": "5", "Authorization": "Bearer tok-1"}
    assert all(len(b) <= NTFY_MAX_MESSAGE_LENGTH for _, b, _ in client.posts)


@pytest.mark.asyncio
async def test_priority_is_clamped_and_title_falls_back():
    channel, client = _channel(title="")
    assert await channel.send("hi", priority=99, title="Ünïcode only: ✓") is True
    assert client.posts[0][2] == {"Title": "ncode only:", "Priority": "5"}
    assert await channel.send("hi", priority="low") is True
    assert client.posts[1][2]["Priority"] == "3"
    assert await channel.send("hi", title="✓✓") is True
    assert client.posts[2][2]["Title"] == "Nerva"


@pytest.mark.asyncio
async def test_a_refused_chunk_is_false_and_nothing_raises():
    channel, client = _channel([200, 500])
    text = "\n\n".join("p " * 1500 for _ in range(3))
    assert await channel.send(text) is False
    assert len(client.posts) == 2                       # stops at the refusal, in order
    channel, _ = _channel([403])
    assert await channel.send("hi") is False


@pytest.mark.asyncio
async def test_start_and_stop_are_quiet_and_close_the_client():
    channel, client = _channel()
    await channel.start()
    await channel.stop()
    assert client.closed is True


def test_from_env_requires_both_and_refuses_nonsense(caplog):
    assert NtfyChannel.from_env({}) is None
    with caplog.at_level(logging.WARNING, logger="jarvis.channels.ntfy"):
        assert NtfyChannel.from_env({"NTFY_URL": "https://ntfy.example"}) is None
        assert NtfyChannel.from_env({"NTFY_URL": "https://ntfy.example", "NTFY_TOPIC": "bad topic"}) is None
    messages = [r.getMessage() for r in caplog.records]
    assert any("needs both" in m for m in messages) and any("disabled" in m for m in messages)
    channel = NtfyChannel.from_env({
        "NTFY_URL": "http://ntfy.lan:8080/", "NTFY_TOPIC": "home_alerts", "NTFY_TOKEN": "t", "NTFY_TITLE": "Home",
    })
    assert channel is not None and channel.url == "http://ntfy.lan:8080" and channel.topic == "home_alerts"
    assert channel.title == "Home" and channel._token == "t"


@pytest.mark.asyncio
async def test_the_manager_sends_through_the_contract_gate():
    channel, client = _channel()
    manager = ChannelManager()
    manager.register(channel)
    assert await manager.send("ntfy", "queue needs you", priority=4) is True
    assert client.posts[0][1] == b"queue needs you" and client.posts[0][2]["Priority"] == "4"


@pytest.mark.asyncio
async def test_escalations_reach_ntfy_like_any_registered_adapter():
    channel, client = _channel()
    router = EscalationRouter({"ntfy": channel})
    out = await router.escalate("approval waiting: pay the invoice")
    assert out["delivered"] == ["ntfy"] and out["failed"] == []
    assert client.posts[0][1] == b"approval waiting: pay the invoice"
