"""H099: real synthetic streams, topic authority, lifecycle and governed replies."""

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channel_reply import ChannelReplyBroker
from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.channels.ntfy import NtfyChannel
from agents.core.channels.pairing import SenderPairing
from tests.test_channel_handler_session_wiring import _bare_orchestrator


class Frames(httpx.AsyncByteStream):
    def __init__(self, frames, *, hold=False):
        self.frames = frames
        self.hold = hold
        self.closed = False

    async def __aiter__(self):
        for frame in self.frames:
            yield frame
        if self.hold:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def event(key="m1", text="hello", **extra):
    return {"event": "message", "id": key, "topic": "home", "message": text, **extra}


def line(value):
    return (json.dumps(value) + "\n").encode()


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


def setup_channel(tmp_path, frames=(), *, hold=True, status=200, paired=True):
    stream = Frames(frames, hold=hold)
    requests = []

    async def transport(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(status, stream=stream)
        return httpx.Response(200, json={"id": "published"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    pairing = SenderPairing(tmp_path / "pairing.json")
    if paired:
        pairing.approve("ntfy", "home")
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    seen = []

    async def handler(text, **kwargs):
        seen.append((text, kwargs))
        return "do not echo this return value"

    gateway = Gateway(handler=handler, pairing=pairing, inbox_store=inbox)
    channel = NtfyChannel("https://ntfy.example", "home", client=client,
                          handler=gateway.route, pairing=pairing, inbound=True)
    return channel, gateway, inbox, seen, requests, stream


def test_receiving_requires_explicit_opt_in_and_no_default_public_server():
    assert NtfyChannel.from_env({"NTFY_TOPIC": "home", "NTFY_INBOUND": "1"}) is None
    default = NtfyChannel.from_env({"NTFY_URL": "http://127.0.0.1:8080", "NTFY_TOPIC": "home"})
    receiving = NtfyChannel.from_env({"NTFY_URL": "http://127.0.0.1:8080", "NTFY_TOPIC": "home",
                                      "NTFY_INBOUND": "1"})
    assert getattr(default, "inbound", False) is False
    assert getattr(receiving, "inbound", False) is True


@pytest.mark.asyncio
async def test_stream_routes_once_with_configured_identity_taint_and_exact_inbox(tmp_path):
    channel, gateway, inbox, seen, requests, stream = setup_channel(tmp_path, [
        line({"event": "keepalive"}), b"bad json\n", line(["not an event"]),
        line(event(topic="foreign", title="home")),
        line(event(title="administrator", sender="owner", pairing_code="spoof")),
        line(event()), line(event("m2", tags=["nerva-agent"])),
    ])
    try:
        await channel.start()
        await until(lambda: len(seen) == 1)
        assert seen[0][0] == "hello"
        meta = seen[0][1]
        assert meta["sender"] == meta["chat_id"] == "home"
        assert meta["origin"] == "inbound" and meta["_inbound_meta"]["tainted"]
        assert "pairing_code" not in meta
        assert inbox.get_message(meta["_inbox_message_id"])["sender"] == "home"
        assert [r.method for r in requests] == ["GET"]
        assert requests[0].url.path == "/home/json"
        assert requests[0].url.params["poll"] == "false"
        assert gateway.get_channel_info("ntfy")["message_count"] == 1
    finally:
        await channel.stop()
    assert stream.closed and channel._stream_task is None


@pytest.mark.asyncio
async def test_unpaired_topic_is_held_even_if_title_claims_a_paired_name(tmp_path):
    channel, gateway, inbox, seen, requests, _ = setup_channel(tmp_path,
        [line(event(title="trusted-owner", sender="trusted-owner"))], paired=False)
    channel.pairing.approve("ntfy", "trusted-owner")
    try:
        await channel.start()
        await until(lambda: gateway.get_summary()["total_held"] == 1)
        assert seen == [] and inbox.threads() == []
        assert [r.method for r in requests] == ["GET"]
        channel.pairing.approve("ntfy", "home")
        await channel._on_message(event("resend"))
        assert len(seen) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_receiving_without_shared_pairing_fails_before_get(tmp_path):
    channel, _, _, _, requests, _ = setup_channel(tmp_path)
    channel.pairing = None
    try:
        with pytest.raises(ValueError, match="pairing"):
            await channel.start()
        assert requests == []
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_dedup_expires_and_remains_bounded(tmp_path, monkeypatch):
    import agents.core.channels.ntfy as ntfy
    clock = [10.0]
    monkeypatch.setattr(ntfy, "monotonic", lambda: clock[0])
    channel, gateway, inbox, seen, _, _ = setup_channel(tmp_path)
    gateway.set_rate_limit(10000)
    try:
        await channel.start()
        await channel._on_message(event())
        await channel._on_message(event())
        assert len(seen) == 1
        clock[0] = 311.0
        await channel._on_message(event())
        assert len(seen) == 2
        for i in range(1001):
            await channel._on_message(event(f"later-{i}"))
        before = len(seen)
        await channel._on_message(event("later-1000"))
        assert len(seen) == before
        await channel._on_message(event("later-0"))
        assert len(seen) == before + 1
        assert inbox.stats()["messages"] == 500
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_oversized_or_invalid_frames_do_not_hide_the_next_valid_event(tmp_path):
    channel, _, _, seen, _, _ = setup_channel(tmp_path, [
        b"x" * 100000 + b"\n", b'\xff\n', b"[" * 2000 + b"0" + b"]" * 2000 + b"\n",
        line(event("large", "x" * 5000)),
        line(event("wrong", 7)), line(event("empty", " ")), line(event("valid", "last")),
    ])
    try:
        await channel.start()
        await until(lambda: bool(seen))
        assert [s[0] for s in seen] == ["last"]
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_fatal_response_stops_without_retry_or_topic_in_logs(tmp_path, status, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    channel, _, _, seen, requests, _ = setup_channel(tmp_path, status=status)
    try:
        await channel.start()
        await until(lambda: channel._stream_task.done())
        assert seen == [] and len(requests) == 1
        assert channel.fatal_error == f"http_{status}"
        assert all("/home" not in r.getMessage() for r in caplog.records)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_reconnect_backoff_reset_and_dedup_across_connections(tmp_path, monkeypatch):
    import agents.core.channels.ntfy as ntfy
    clock = [0.0]
    monkeypatch.setattr(ntfy, "monotonic", lambda: clock[0])
    delays, requests = [], []
    channel, _, _, seen, _, _ = setup_channel(tmp_path)
    await channel.client.aclose()

    async def transport(request):
        requests.append(request)
        if len(requests) == 7:
            clock[0] += 61
        return httpx.Response(200, stream=Frames([line(event())]))

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 7:
            await asyncio.Event().wait()

    monkeypatch.setattr(ntfy, "sleep", sleep)
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        await channel.start()
        await channel.start()  # idempotent: no second listener
        await until(lambda: len(delays) == 7)
        assert delays == [2, 5, 10, 30, 60, 60, 2]
        assert len(requests) == 7 and len(seen) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_automatic_reply_uses_exact_inbox_and_never_direct_send(tmp_path):
    channel, gateway, inbox, _, requests, _ = setup_channel(tmp_path, [line(event())])
    orch, captured = _bare_orchestrator(response="answer")
    proposals = []

    def enqueue(*args, **kwargs):
        proposals.append((args, kwargs))
        return 1

    orch.channel_replies = ChannelReplyBroker(inbox=inbox, enqueue=enqueue)
    gateway.handler = orch.channel_handler
    try:
        await channel.start()
        await until(lambda: bool(proposals) or bool(captured["sent"]))
        assert captured["sent"] == []
        assert len(proposals) == 1
        payload = proposals[0][1]["payload"]
        assert payload["channel"] == "ntfy"
        assert inbox.get_message(payload["message_id"])["text"] == "hello"
        assert payload["reply"]["ntfy_topic"] == "home"
        assert [r.method for r in requests] == ["GET"]
    finally:
        await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["url", "topic", "_token", "revoked", "stopped"])
async def test_queued_reply_refuses_changed_destination_or_revoked_pairing(tmp_path, drift):
    channel, _, inbox, seen, requests, _ = setup_channel(tmp_path, [line(event())])
    manager = ChannelManager()
    manager.register(channel)
    broker = ChannelReplyBroker(inbox=inbox, channel_manager=manager)
    try:
        await channel.start()
        await until(lambda: bool(seen))
        proposal = broker.request(inbox.threads()[0]["thread_id"], "answer")
        assert proposal["ok"], proposal
        if drift == "revoked":
            channel.pairing.block("ntfy", "home")
        elif drift == "stopped":
            await channel.stop()
        else:
            setattr(channel, drift, "changed")
        result = await broker.execute(SimpleNamespace(payload=proposal["payload"]))
        assert result["status"] != "ok"
        assert [r.method for r in requests] == ["GET"]
        assert len(inbox.messages(proposal["payload"]["thread_id"])) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_basic_auth_publish_topic_and_markdown_configuration(tmp_path):
    channel, _, _, _, requests, _ = setup_channel(tmp_path)
    await channel.stop()
    configured = NtfyChannel.from_env({
        "NTFY_SERVER_URL": "https://ntfy.example", "NTFY_TOPIC": "home",
        "NTFY_PUBLISH_TOPIC": "updates", "NTFY_MARKDOWN": "1", "NTFY_TOKEN": "user:pass",
    })
    assert configured is not None
    configured.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200)))
    try:
        assert await configured.send("**bold**")
        request = requests[-1]
        assert request.url.path == "/updates"
        assert request.headers["Authorization"] == "Basic dXNlcjpwYXNz"
        assert request.headers["X-Markdown"] == "true" and request.content == b"**bold**"
    finally:
        await configured.stop()


@pytest.mark.asyncio
async def test_pairing_cannot_be_silently_disabled_on_a_running_listener(tmp_path, monkeypatch):
    channel, _, _, seen, requests, _ = setup_channel(tmp_path)
    try:
        await channel.start()
        monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
        monkeypatch.delenv("JARVIS_CHANNEL_OPEN", raising=False)
        await channel._on_message(event())
        assert seen == []
        assert not await channel.send_reply("answer", ntfy_topic="home", ntfy_context=channel._context())
        assert all(r.method != "POST" for r in requests)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_reply_revoked_during_dns_wait_never_reaches_transport(tmp_path, monkeypatch):
    from agents.core.http_client import PluginHTTPClient

    pairing = SenderPairing(tmp_path / "pairing.json")
    pairing.approve("ntfy", "home")
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    gateway = Gateway(handler=lambda *_a, **_k: None, pairing=pairing, inbox_store=inbox)
    channel = NtfyChannel("https://ntfy.example", "home", inbound=True,
                          handler=gateway.route, pairing=pairing)
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    original = PluginHTTPClient._prepare_target

    async def prepare(client, method, url):
        target = await original(client, method, url)
        if method == "POST":
            entered.set()
            await release.wait()
        return target

    monkeypatch.setattr(PluginHTTPClient, "_prepare_target", prepare)
    channel.client._resolver = lambda *_a, **_k: (["9.9.9.9"], None)

    def transport(request):
        requests.append(request)
        return httpx.Response(200, stream=Frames([], hold=True)) if request.method == "GET" else httpx.Response(200)

    channel.client._transport_factory = lambda _target: httpx.MockTransport(transport)
    pending = None
    try:
        await channel.start()
        await until(lambda: bool(requests))
        pending = asyncio.create_task(channel.send_reply("answer", ntfy_topic="home",
                                                        ntfy_context=channel._context()))
        await entered.wait()
        pairing.block("ntfy", "home")
        release.set()
        assert await pending is False
        assert [r.method for r in requests] == ["GET"]
    finally:
        release.set()
        if pending is not None:
            await pending
        await channel.stop()


@pytest.mark.asyncio
async def test_changed_configuration_cannot_relabel_an_open_subscription(tmp_path):
    channel, _, inbox, seen, _, _ = setup_channel(tmp_path)
    try:
        await channel.start()
        channel.topic = "new-topic"
        channel.pairing.approve("ntfy", "new-topic")
        message = event()
        message.pop("topic")  # An event without its own topic must not gain a new identity.
        await channel._on_message(message)
        assert seen == [] and inbox.threads() == []
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_failed_inbox_write_cannot_reuse_a_forged_message_id(tmp_path):
    channel, gateway, inbox, _, _, _ = setup_channel(tmp_path)
    orch, captured = _bare_orchestrator(response="answer")
    proposals = []
    orch.channel_replies = ChannelReplyBroker(inbox=inbox, enqueue=lambda *a, **k: proposals.append(k))
    old = inbox.record_inbound("ntfy", "old", sender="home",
                               metadata={"ntfy_topic": "home", "ntfy_context": "a" * 64})

    def broken(*_a, **_k):
        raise OSError("synthetic full disk")

    gateway.inbox_store = SimpleNamespace(record_inbound=broken)
    gateway.handler = orch.channel_handler
    await gateway.route("new", channel="ntfy", sender="home", origin="generated",
                        _inbox_message_id=old["id"], ntfy_topic="home", ntfy_context="a" * 64)
    assert proposals == [] and captured["sent"] == []
    await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["kernel_denied", "redirect"])
async def test_real_egress_client_refuses_denial_and_does_not_forward_credentials(tmp_path, monkeypatch, mode):
    import agents.core.http_client as http_client
    channel = NtfyChannel("https://ntfy.example", "home", token="synthetic-value")
    channel.client._resolver = lambda *_a, **_k: (["9.9.9.9"], None)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://unconfigured.example/home"})

    channel.client._transport_factory = lambda _target: httpx.MockTransport(transport)
    if mode == "kernel_denied":
        monkeypatch.setattr(http_client, "_EGRESS_KERNEL_HOOK", lambda *_a: "synthetic-denial")
    try:
        assert await channel.send("alert") is False
        if mode == "kernel_denied":
            assert requests == []
        else:
            assert len(requests) == 1
            assert requests[0].headers["Host"] == "ntfy.example"
            assert requests[0].headers["Authorization"] == "Bearer synthetic-value"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_same_adapter_restart_invalidates_previously_queued_reply(tmp_path):
    channel, _, inbox, seen, requests, _ = setup_channel(tmp_path, [line(event())])
    manager = ChannelManager()
    manager.register(channel)
    broker = ChannelReplyBroker(inbox=inbox, channel_manager=manager)
    try:
        await channel.start()
        await until(lambda: bool(seen))
        proposal = broker.request(inbox.threads()[0]["thread_id"], "old reply")
        assert proposal["ok"]
        await channel.stop()
        channel.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(
                200, stream=Frames([], hold=request.method == "GET"))))
        await channel.start()
        result = await broker.execute(SimpleNamespace(payload=proposal["payload"]))
        assert result["status"] != "ok"
        assert all(r.method != "POST" for r in requests)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_utf8_chunks_obey_ntfy_byte_limit_without_corrupting_text():
    requests = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200)))
    channel = NtfyChannel("https://ntfy.example", "home", client=client)
    text = "😊" * 2000
    try:
        assert await channel.send(text, plain=True)
        assert all(len(r.content) <= 4096 for r in requests)
        assert "".join(r.content.decode() for r in requests) == text
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_ntfy_log_redaction_does_not_hide_other_http_requests(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    channel = NtfyChannel("https://ntfy.example", "private-topic", client=client)
    try:
        assert await channel.send("hello")
        await client.get("https://ordinary.example/public")
        messages = [r.getMessage() for r in caplog.records]
        assert not any("private-topic" in text for text in messages)
        assert any("ordinary.example/public" in text for text in messages)
    finally:
        await channel.stop()
