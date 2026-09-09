"""Slack ingress: fake SDK regressions plus an optional real-SDK offline smoke."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channels import slack
from agents.core.channels.gateway import Gateway
from agents.core.channels.pairing import SenderPairing


@pytest.mark.asyncio
async def test_native_sdk_parser_callback_and_threads_close_without_network(monkeypatch):
    """Exercise SDK lifecycle internals when installed; only network seams are mocked."""
    native = pytest.importorskip("slack_sdk.socket_mode")
    responses = pytest.importorskip("slack_sdk.socket_mode.response")
    reached, seen, acks = asyncio.Event(), [], []

    class OfflineWebClient:
        def __init__(self, **kwargs):
            pass

        def auth_test(self):
            return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    async def handler(text, **metadata):
        seen.append((text, metadata["sender"]))
        reached.set()

    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", OfflineWebClient, raising=False)
    monkeypatch.setattr(slack, "SocketModeClient", native.SocketModeClient, raising=False)
    monkeypatch.setattr(slack, "SocketModeResponse", responses.SocketModeResponse, raising=False)
    monkeypatch.setattr(native.SocketModeClient, "connect", lambda self: None)
    monkeypatch.setattr(native.SocketModeClient, "is_connected", lambda self: not self.closed)
    monkeypatch.setattr(native.SocketModeClient, "send_socket_mode_response",
                        lambda self, response: acks.append(response.to_dict()))
    channel = slack.SlackChannel("offline-bot", handler=handler, app_token="offline-app")
    await channel.start()
    client = channel._socket_client
    try:
        assert client is not None
        request = envelope()
        client.enqueue_message(json.dumps({
            "type": request.type, "envelope_id": request.envelope_id, "payload": request.payload,
        }))
        await asyncio.wait_for(reached.wait(), timeout=5)
        assert seen == [("hello", "T1:U1")]
        assert acks == [{"envelope_id": request.envelope_id}]
    finally:
        await channel.stop()
    assert not client.current_session_runner.is_alive()
    assert not client.message_processor.is_alive()
    assert not client.current_app_monitor.is_alive()


class SDKResponse:
    """SlackResponse supports get/indexing without being a dict."""

    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]


@pytest.fixture
def sdk(monkeypatch):
    sockets = []

    class WebClient:
        def __init__(self, token, **kwargs):
            self.token = token
            self.options = kwargs
            self.posts = []
            self.auth_thread = None

        def auth_test(self):
            self.auth_thread = threading.get_ident()
            return SDKResponse({"ok": True, "team_id": "T1", "user_id": "UBOT"})

        def chat_postMessage(self, **kwargs):
            self.posts.append(kwargs)
            return {"ok": True}

    class SocketModeClient:
        def __init__(self, app_token, web_client, **kwargs):
            self.app_token = app_token
            self.web_client = web_client
            self.socket_mode_request_listeners = []
            self.acks = []
            self.connected = False
            self.closed = False
            self.connect_thread = None
            self.close_thread = None
            self.current_session_state = SimpleNamespace(terminated=False)
            self.current_session_runner = SimpleNamespace(is_alive=lambda: False)
            sockets.append(self)

        def connect(self):
            self.connect_thread = threading.get_ident()
            self.connected = True

        def is_connected(self):
            return self.connected

        def close(self):
            self.close_thread = threading.get_ident()
            self.closed = True
            self.connected = False

        def disconnect(self):
            self.connected = False

        def send_socket_mode_response(self, response):
            self.acks.append(response.envelope_id)

        def emit(self, request):
            for listener in self.socket_mode_request_listeners:
                listener(self, request)

    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", WebClient, raising=False)
    monkeypatch.setattr(slack, "SocketModeClient", SocketModeClient, raising=False)
    monkeypatch.setattr(slack, "SocketModeResponse", SimpleNamespace, raising=False)
    return SimpleNamespace(sockets=sockets, socket_class=SocketModeClient, web_class=WebClient)


def envelope(event_id="Ev1", *, event=None, **payload):
    return SimpleNamespace(
        type="events_api", envelope_id=f"envelope-{event_id}",
        payload={
            "type": "event_callback", "team_id": "T1", "event_id": event_id,
            "event": {
                "type": "message", "channel_type": "im", "channel": "D1",
                "user": "U1", "text": "hello", "ts": "100.001", **(event or {}),
            },
            **payload,
        },
    )


async def settle():
    # Advance the event loop without a wall-clock delay; handlers in these tests
    # either finish immediately or signal a deterministic Event.
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_sdk_thread_ack_is_prompt_and_dispatch_runs_on_hub_loop(sdk):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    main_thread = threading.get_ident()

    async def handler(text, **kwargs):
        seen.append((text, kwargs, threading.get_ident()))
        entered.set()
        await release.wait()
        return "must not be sent directly"

    channel = slack.SlackChannel("bot-secret", handler=handler, app_token="app-secret")
    await channel.start()
    client = sdk.sockets[0]
    try:
        await asyncio.wait_for(asyncio.to_thread(client.emit, envelope()), timeout=2)
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert client.acks == ["envelope-Ev1"]
        assert seen == [("hello", {"channel": "slack", "slack_channel": "D1", "sender": "T1:U1"}, main_thread)]
        # A blocked handler must not hold either ACK or another SDK callback.
        await asyncio.wait_for(asyncio.to_thread(client.emit, envelope("Ev2")), timeout=2)
        assert len(client.acks) == 2 and len(seen) == 1
        assert client.web_client.posts == []
        assert client.connect_thread != main_thread
        assert isinstance(client.web_client.auth_thread, int)
        assert client.web_client.auth_thread != main_thread
    finally:
        await channel.stop()
    assert client.closed and client.close_thread != main_thread
    assert not channel._running
    assert channel._dispatch_task is None
    await asyncio.to_thread(client.emit, envelope("Ev3"))
    await settle()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_allowed_events_keep_only_safe_room_thread_identity(sdk):
    seen = []

    async def handler(text, **kwargs):
        seen.append((text, kwargs))

    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    try:
        client.emit(envelope(event={"thread_ts": "99.000001", "sender": "forged", "origin": "owner", "pairing_code": "forged", "_inbox_message_id": "forged"}))
        client.emit(envelope("Ev2", event={"type": "app_mention", "channel": "C1", "channel_type": "channel"}))
        await settle()
        assert seen == [
            ("hello", {"channel": "slack", "slack_channel": "D1", "sender": "T1:U1", "thread_ts": "99.000001"}),
            ("hello", {"channel": "slack", "slack_channel": "C1", "sender": "T1:U1", "thread_ts": "100.001"}),
        ]
    finally:
        await channel.stop()


@pytest.mark.parametrize("changes", [
    {"bot_id": "B1"}, {"bot_profile": {"id": "B1"}}, {"subtype": "bot_message"},
    {"subtype": "message_changed"}, {"subtype": "message_deleted"}, {"hidden": True},
    {"user": ""}, {"user": None}, {"user": "U1\nforged"}, {"user": "B1"},
    {"channel": ""}, {"channel": 1}, {"channel": "D1\n"},
    {"text": None}, {"text": " "}, {"text": "x" * 40_001},
    {"type": "reaction_added"}, {"channel_type": "channel", "channel": "C1"},
    {"channel_type": "mpim", "channel": "G1"}, {"channel_type": "im", "channel": "C1"},
    {"thread_ts": "bad"}, {"thread_ts": {"ts": "100.001"}},
    {"ts": ""}, {"ts": 100.001}, {"ts": "100.001\n"},
])
@pytest.mark.asyncio
async def test_ignored_events_are_acked_without_dispatch(sdk, changes):
    seen = []

    async def handler(*args, **kwargs):
        seen.append(args)

    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    try:
        sdk.sockets[0].emit(envelope(event=changes))
        await settle()
        assert sdk.sockets[0].acks == ["envelope-Ev1"]
        assert seen == []
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_malformed_and_unsupported_envelopes_are_not_dispatched(sdk):
    seen = []

    async def handler(*args, **kwargs):
        seen.append(args)

    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    try:
        for payload in ({"event": None}, {"event_id": ""}, {"event_id": []}, {"team_id": None}, {"type": "url_verification"}):
            request = envelope()
            request.payload.update(payload)
            client.emit(request)
        request = envelope()
        request.type = "interactive"
        client.emit(request)
        request = envelope()
        request.payload = []
        client.emit(request)
        client.emit(SimpleNamespace(type="events_api"))
        await settle()
        assert len(client.acks) == 7
        assert seen == []
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_queue_and_dedup_are_bounded_replays_are_team_scoped(sdk, monkeypatch):
    monkeypatch.setattr(slack, "SLACK_INBOUND_QUEUE_SIZE", 2, raising=False)
    monkeypatch.setattr(slack, "SLACK_EVENT_CACHE_SIZE", 2, raising=False)
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)

    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    try:
        client.emit(envelope())
        client.emit(envelope())
        client.emit(envelope(team_id="T2"))
        client.emit(envelope("Ev2"))
        client.emit(envelope("Ev3"))  # queue full: ACK and drop
        assert channel._inbound_queue.qsize() == 2
        assert len(channel._seen_events) == 2
        await settle()
        assert len(seen) == 2
        client.emit(envelope())  # recent duplicate
        client.emit(envelope("Ev3"))  # overflow was never admitted: can retry
        await settle()
        assert len(seen) == 3
        client.emit(envelope())  # bounded cache has evicted oldest
        await settle()
        assert len(seen) == 4 and len(channel._seen_events) == 2
        assert len(client.acks) == 8
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_connection_failure_closes_partial_client_and_can_retry(sdk, monkeypatch, caplog):
    original = sdk.socket_class.connect

    def fail(self):
        raise RuntimeError("app-secret bot-secret")

    monkeypatch.setattr(sdk.socket_class, "connect", fail)
    channel = slack.SlackChannel("bot-secret", app_token="app-secret")
    await channel.start()
    assert sdk.sockets[0].closed
    assert not channel._running and channel._dispatch_task is None
    assert "app-secret" not in caplog.text and "bot-secret" not in caplog.text
    assert "failed" in caplog.text.lower()
    monkeypatch.setattr(sdk.socket_class, "connect", original)
    await channel.start()
    await channel.start()
    assert len(sdk.sockets) == 2 and channel._running
    await channel.stop()
    await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_start_waits_for_blocking_connect_then_closes(sdk, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow_connect(self):
        entered.set()
        assert release.wait(timeout=5)
        self.connected = True

    monkeypatch.setattr(sdk.socket_class, "connect", slow_connect)
    channel = slack.SlackChannel("bot", app_token="app")
    startup = asyncio.create_task(channel.start())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        startup.cancel()
        await settle()
        startup.cancel()
        await settle()
        assert not startup.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
    assert sdk.sockets[0].closed and not sdk.sockets[0].connected
    assert channel._dispatch_task is None and not channel._running


@pytest.mark.asyncio
async def test_other_workspace_and_own_bot_never_reach_pairing(sdk):
    seen = []

    async def handler(*args, **kwargs):
        seen.append(kwargs)

    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    try:
        sdk.sockets[0].emit(envelope(team_id="T2"))
        sdk.sockets[0].emit(envelope("Ev2", event={"user": "UBOT"}))
        await settle()
        assert seen == []
        assert len(sdk.sockets[0].acks) == 2
    finally:
        await channel.stop()


@pytest.mark.parametrize("identity", [
    None, {}, {"ok": False, "team_id": "T1", "user_id": "UBOT"},
    {"ok": True, "team_id": "", "user_id": "UBOT"},
    {"ok": True, "team_id": "T1", "user_id": ""},
])
@pytest.mark.asyncio
async def test_invalid_bot_identity_never_opens_socket(sdk, monkeypatch, identity):
    monkeypatch.setattr(sdk.web_class, "auth_test", lambda self: identity)
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    assert not channel._running and sdk.sockets == []


@pytest.mark.asyncio
async def test_failed_handshake_without_exception_is_not_ready(sdk, monkeypatch, caplog):
    monkeypatch.setattr(sdk.socket_class, "connect", lambda self: None)
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    assert not channel._running and sdk.sockets[0].closed
    assert "failed" in caplog.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_shutdown", [False, True])
async def test_blocking_close_yields_to_hub_and_discards_pending_messages(sdk, monkeypatch, cancel_shutdown):
    entered, release = threading.Event(), threading.Event()
    seen = []

    def slow_close(self):
        entered.set()
        assert release.wait(timeout=5)
        self.closed = True

    async def handler(*args, **kwargs):
        seen.append(args)
        await asyncio.Event().wait()

    monkeypatch.setattr(sdk.socket_class, "close", slow_close)
    channel = slack.SlackChannel("bot", handler=handler, app_token="app")
    await channel.start()
    sdk.sockets[0].emit(envelope())
    sdk.sockets[0].emit(envelope("Ev2"))
    await settle()
    shutdown = asyncio.create_task(channel.stop())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), timeout=3)
        assert not shutdown.done()
        assert channel._inbound_queue.empty()
        assert channel._dispatch_task is None
        assert len(seen) == 1
        if cancel_shutdown:
            shutdown.cancel()
            await settle()
            shutdown.cancel()
            await settle()
            assert not shutdown.done()
    finally:
        release.set()
        if cancel_shutdown:
            with pytest.raises(asyncio.CancelledError):
                await shutdown
        else:
            await shutdown


@pytest.mark.asyncio
async def test_socket_discovery_has_no_unbounded_retry_and_sdk_logs_are_scrubbed(sdk, monkeypatch, caplog):
    calls = []

    def rate_limited(self, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("secret-response")

    monkeypatch.setattr(sdk.web_class, "apps_connections_open", rate_limited, raising=False)
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    try:
        assert client.web_client.options["retry_handlers"] == []
        assert client.web_client.options["timeout"] == 10
        with pytest.raises(RuntimeError):
            client.issue_new_wss_url()
        assert calls == [{"app_token": "app"}]
        monkeypatch.setattr(sdk.web_class, "apps_connections_open", lambda self, **kwargs: SDKResponse({"url": "wss://slack.invalid"}))
        assert client.issue_new_wss_url() == "wss://slack.invalid"
        client.web_client.options["logger"].error("app-secret secret-response", exc_info=True)
        assert "Slack SDK transport operation failed" in caplog.text
        assert "secret-response" not in caplog.text and "app-secret" not in caplog.text
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_sdk_close_settles_late_reconnect_and_terminates_reader(sdk, monkeypatch):
    def late_reconnect(self):
        self.connected = True  # Reconnect finishes while SDK close joins its monitor.

    monkeypatch.setattr(sdk.socket_class, "close", late_reconnect)
    channel = slack.SlackChannel("bot", app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    joined = []

    def join_reader():
        assert client.current_session_state.terminated
        assert not client.connected
        joined.append(True)

    client.current_session_runner = SimpleNamespace(is_alive=lambda: True, shutdown=join_reader)
    await channel.stop()
    assert joined == [True]
    assert client.auto_reconnect_enabled is False and not client.connected


@pytest.mark.asyncio
async def test_failed_ack_does_not_admit_or_deduplicate_event(sdk, monkeypatch, caplog):
    seen = []

    async def handler(*args, **kwargs):
        seen.append(args)

    def fail(response):
        raise RuntimeError("app-secret message-secret")

    channel = slack.SlackChannel("bot", handler=handler, app_token="app-secret")
    await channel.start()
    client = sdk.sockets[0]
    original = client.send_socket_mode_response
    try:
        monkeypatch.setattr(client, "send_socket_mode_response", fail)
        client.emit(envelope())
        await settle()
        assert not seen and not channel._seen_events
        assert "app-secret" not in caplog.text and "message-secret" not in caplog.text
        monkeypatch.setattr(client, "send_socket_mode_response", original)
        client.emit(envelope())
        await settle()
        assert len(seen) == 1
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_handler_failure_does_not_kill_dispatch_or_leak_payload(sdk, caplog):
    seen = []

    async def handler(text, **kwargs):
        seen.append(text)
        if len(seen) == 1:
            raise RuntimeError("app-secret message-secret")

    channel = slack.SlackChannel("bot", handler=handler, app_token="app-secret")
    await channel.start()
    try:
        sdk.sockets[0].emit(envelope())
        sdk.sockets[0].emit(envelope("Ev2"))
        await settle()
        assert len(seen) == 2
        assert "app-secret" not in caplog.text and "message-secret" not in caplog.text
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_token_only_seam_and_optional_sdk_remain_supported(sdk, monkeypatch):
    seen = []

    async def handler(text, **kwargs):
        seen.append((text, kwargs))

    channel = slack.SlackChannel("bot", handler)
    await channel.start()
    assert channel._running and sdk.sockets == []
    await channel.receive_event("manual", "C1", user="legacy-user", thread_ts="100.001")
    assert seen[0][1]["sender"] == "legacy-user"
    assert await channel.send("reply", slack_channel="C1", thread_ts="100.001")
    await channel.stop()
    monkeypatch.setattr(slack, "SLACK_AVAILABLE", False)
    unavailable = slack.SlackChannel("bot", app_token="app")
    await unavailable.start()
    assert not unavailable._running and sdk.sockets == []


@pytest.mark.asyncio
async def test_socket_ingress_reaches_persistent_inbox_only_after_real_pairing(sdk, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    monkeypatch.delenv("SLACK_ALLOWED_USER_IDS", raising=False)
    inbox_path = tmp_path / "inbox.json"
    inbox = ChannelInboxStore(inbox_path)
    pairing = SenderPairing(tmp_path / "pairing.json")
    pairing.approve("slack", "U1")  # A legacy or other-workspace identity is not consent.
    pairing.approve("slack", "T2:U1")
    seen = []

    async def handler(text, **kwargs):
        seen.append(kwargs)
        return "no direct echo"

    gateway = Gateway(handler=handler, pairing=pairing, inbox_store=inbox)
    channel = slack.SlackChannel("bot", handler=gateway.route, app_token="app")
    await channel.start()
    client = sdk.sockets[0]
    try:
        await asyncio.to_thread(client.emit, envelope())
        await settle()
        assert inbox.threads() == [] and seen == []
        assert gateway.get_summary()["total_held"] == 1
        pairing.approve("slack", "T1:U1")
        await asyncio.to_thread(client.emit, envelope("Ev2", event={"thread_ts": "99.001"}))
        await settle()
        persisted = ChannelInboxStore(inbox_path)
        assert persisted.threads()[0]["reply"] == {"slack_channel": "D1", "thread_ts": "99.001"}
        assert seen[0]["origin"] == "inbound"
        assert persisted.get_message(seen[0]["_inbox_message_id"])["text"] == "hello"
        assert client.web_client.posts == []
    finally:
        await channel.stop()
