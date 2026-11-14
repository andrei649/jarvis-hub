"""One Slack opening deadline retains both token claims until SDK work settles."""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from agents.core import lifecycle_budget
from agents.core.channels import polling_claims, slack
from agents.core.channels.manager import ChannelManager
from tests.test_h083_slack_claims import channel, sdk  # noqa: F401 - pytest fixture


async def _thread_event(event):
    assert await asyncio.to_thread(event.wait, 2)


@pytest.mark.asyncio
async def test_late_auth_returns_at_deadline_without_binding_identity(sdk, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def held_auth(_client):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    monkeypatch.setattr(slack.WebClient, "auth_test", held_auth)
    first, contender = channel(), channel()
    first._connect_timeout_seconds = 0.5
    starting = asyncio.create_task(first.start())
    try:
        await _thread_event(entered)
        await asyncio.sleep(0.55)
        assert starting.done()
        await starting
        assert first.health_snapshot()["fatal"] == "connect_timeout"
        assert not first._running and first._team_id == "" and sdk.sockets == []
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "connection_claim_busy"
        assert len(sdk.web) == 1
        release.set()
        await first._startup_cleanup_task
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
        await first.stop()
        await contender.start()
        assert contender._running
    finally:
        release.set()
        await starting
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_late_socket_open_never_acks_event_after_deadline(sdk, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = slack.SocketModeClient.connect

    def held_connect(client):
        entered.set()
        assert release.wait(5)
        original(client)

    monkeypatch.setattr(slack.SocketModeClient, "connect", held_connect)
    first = channel()
    first._connect_timeout_seconds = 0.5
    starting = asyncio.create_task(first.start())
    try:
        await _thread_event(entered)
        socket = sdk.sockets[0]
        acks = []
        socket.send_socket_mode_response = lambda receipt: acks.append(receipt)
        request = SimpleNamespace(envelope_id="envelope", type="events_api", payload={
            "type": "event_callback", "team_id": "T1", "event_id": "E1",
            "event": {"user": "U1", "channel": "D1", "text": "hello", "ts": "1.000001"},
        })
        first._on_socket_request(socket, request)
        assert len(acks) == 1  # Timely callbacks remain enabled during opening.
        await asyncio.sleep(0.55)
        assert starting.done()
        await starting
        assert first.health_snapshot()["fatal"] == "connect_timeout"
        first._on_socket_request(socket, request)
        assert len(acks) == 1 and not first._running
        release.set()
        await first._startup_cleanup_task
        assert socket.closed
    finally:
        release.set()
        await starting
        await first.stop()


@pytest.mark.asyncio
async def test_auth_elapsed_time_reduces_connect_wait(sdk, monkeypatch):
    auth_entered, auth_release = threading.Event(), threading.Event()
    connect_entered, connect_release = threading.Event(), threading.Event()
    original_connect = slack.SocketModeClient.connect

    def held_auth(_client):
        auth_entered.set()
        assert auth_release.wait(5)
        return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    def held_connect(client):
        connect_entered.set()
        assert connect_release.wait(5)
        original_connect(client)

    monkeypatch.setattr(slack.WebClient, "auth_test", held_auth)
    monkeypatch.setattr(slack.SocketModeClient, "connect", held_connect)
    first = channel()
    first._connect_timeout_seconds = 0.5
    starting = asyncio.create_task(first.start())
    try:
        await _thread_event(auth_entered)
        await asyncio.sleep(0.3)
        auth_release.set()
        await _thread_event(connect_entered)
        await asyncio.sleep(0.3)
        assert starting.done()  # A fresh 0.5s socket budget would still be pending.
        await starting
        assert first.health_snapshot()["fatal"] == "connect_timeout"
    finally:
        auth_release.set()
        connect_release.set()
        await starting
        await first.stop()


@pytest.mark.asyncio
async def test_socket_constructor_time_counts_before_ingress_or_connect(sdk, monkeypatch):
    original_init = slack.SocketModeClient.__init__

    def slow_init(client, *args, **kwargs):
        time.sleep(0.6)
        original_init(client, *args, **kwargs)

    monkeypatch.setattr(slack.SocketModeClient, "__init__", slow_init)
    first = channel()
    first._connect_timeout_seconds = 0.5
    try:
        await first.start()
        assert first.health_snapshot()["fatal"] == "connect_timeout"
        assert len(sdk.sockets) == 1
        assert not sdk.sockets[0].connect_entered.is_set()
        assert not first._running and first._pending_callback_generation is None
        await first._startup_cleanup_task
        assert sdk.sockets[0].closed
    finally:
        await first.stop()


@pytest.mark.asyncio
async def test_completed_worker_is_not_accepted_after_delayed_loop_wake(sdk, monkeypatch):
    first = channel()
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    original_wait = slack.asyncio.wait

    async def delayed_wait(*args, **kwargs):
        result = await original_wait(*args, **kwargs)
        await asyncio.sleep(0.03)
        return result

    monkeypatch.setattr(slack.asyncio, "wait", delayed_wait)
    assert not await first._within_opening_budget(
        task, asyncio.get_running_loop().time() + 0.01)


@pytest.mark.asyncio
async def test_bounded_stop_retains_late_connect_and_both_claims(sdk, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = slack.SocketModeClient.connect

    def held_connect(client):
        entered.set()
        assert release.wait(5)
        original(client)

    monkeypatch.setattr(slack.SocketModeClient, "connect", held_connect)
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.01)
    first = channel()
    same_app, same_bot = channel("other-bot", "app-token"), channel("bot-token", "other-app")
    first._connect_timeout_seconds = 0.5
    manager = ChannelManager()
    try:
        await first.start()
        assert entered.is_set() and first._startup_cleanup_task is not None
        assert not await manager._bounded_platform_stop("slack", first)
        await manager.wait_platform_cleanup("slack")
        await same_app.start()
        await same_bot.start()
        assert len(sdk.web) == 1
        assert same_app.health_snapshot()["fatal"] == "connection_claim_busy"
        assert same_bot.health_snapshot()["fatal"] == "connection_claim_busy"
        release.set()
        await first._startup_cleanup_task
        assert all(getattr(sdk.sockets[0], name).is_alive() is False for name in (
            "current_session_runner", "current_app_monitor", "message_processor"))
        await first.stop()
        await same_app.start()
        assert same_app._running
    finally:
        release.set()
        await first.stop()
        await same_app.stop()
        await same_bot.stop()
        await manager.wait_platform_cleanup("slack")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "unknown_runner"])
async def test_failed_late_close_retains_claim_until_explicit_retry(sdk, monkeypatch, failure):
    entered, release = threading.Event(), threading.Event()
    original_connect = slack.SocketModeClient.connect

    def held_connect(client):
        entered.set()
        assert release.wait(5)
        original_connect(client)

    monkeypatch.setattr(slack.SocketModeClient, "connect", held_connect)
    first, contender = channel(), channel()
    first._connect_timeout_seconds = 0.5
    restore = None
    try:
        await first.start()
        socket = sdk.sockets[0]
        if failure == "exception":
            original_close = socket.close
            socket.close = lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE close detail"))

            def restore():
                socket.close = original_close
        else:
            runner = socket.current_app_monitor
            original_probe = runner.is_alive
            runner.is_alive = lambda: None

            def restore():
                runner.is_alive = original_probe
        release.set()
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await first._startup_cleanup_task
        await contender.start()
        assert len(sdk.web) == 1 and contender.health_snapshot()["fatal"] == "connection_claim_busy"
        restore()
        restore = None
        await first.stop()
        await contender.start()
        assert contender._running
    finally:
        release.set()
        if restore is not None:
            restore()
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_native_sdk_late_connect_closes_all_runners_before_claim_release(
        tmp_path, monkeypatch):
    native = pytest.importorskip("slack_sdk.socket_mode")
    entered, release = threading.Event(), threading.Event()
    constructed = []

    class OfflineWebClient:
        def __init__(self, **kwargs):
            constructed.append(self)

        def auth_test(self):
            return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    def held_connect(_client):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(polling_claims, "install_root", lambda: tmp_path / "install")
    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", OfflineWebClient)
    monkeypatch.setattr(slack, "SocketModeClient", native.SocketModeClient)
    monkeypatch.setattr(native.SocketModeClient, "connect", held_connect)
    first = slack.SlackChannel("offline-bot", app_token="offline-app")
    contender = slack.SlackChannel("other-bot", app_token="offline-app")
    first._connect_timeout_seconds = 0.5
    try:
        await first.start()
        assert entered.is_set() and first.health_snapshot()["fatal"] == "connect_timeout"
        client = first._socket_client
        assert client is not None and client.message_processor.is_alive()
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "connection_claim_busy"
        assert len(constructed) == 1
        release.set()
        await first._startup_cleanup_task
        assert all(getattr(client, name).is_alive() is False for name in (
            "current_session_runner", "current_app_monitor", "message_processor"))
        assert first._slack_app_claim is None and first._slack_bot_claim is None
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
    finally:
        release.set()
        await first.stop()
        await contender.stop()
