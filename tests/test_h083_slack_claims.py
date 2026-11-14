"""Slack Socket Mode claims span startup and proven SDK worker shutdown."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core import lifecycle_budget
from agents.core.channels import delivery_ledger, polling_claims, slack
from agents.core.channels.manager import ChannelManager


class Runner:
    def __init__(self):
        self.alive = False

    def is_alive(self):
        return self.alive

    def shutdown(self):
        self.alive = False


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    original_app = polling_claims.acquire_slack_app_claim
    original_bot = polling_claims.acquire_slack_bot_claim
    monkeypatch.setattr(polling_claims, "acquire_slack_app_claim",
                        lambda token: original_app(token, root=tmp_path / "install"))
    monkeypatch.setattr(polling_claims, "acquire_slack_bot_claim",
                        lambda token: original_bot(token, root=tmp_path / "install"))
    web_clients, sockets = [], []

    class WebClient:
        def __init__(self, token, **_kwargs):
            self.token = token
            web_clients.append(self)

        def auth_test(self):
            return {"ok": True, "team_id": "T1", "user_id": "UBOT"}

    class SocketModeClient:
        def __init__(self, app_token, web_client, **_kwargs):
            self.app_token = app_token
            self.web_client = web_client
            self.socket_mode_request_listeners = []
            self.current_session_state = SimpleNamespace(terminated=False)
            self.current_session_runner = Runner()
            self.current_app_monitor = Runner()
            self.message_processor = Runner()
            self.connect_entered = threading.Event()
            self.connect_release = threading.Event()
            self.close_entered = threading.Event()
            self.close_release = threading.Event()
            self.connected = False
            self.closed = False
            self.block_connect = False
            self.block_close = False
            self.fail_close = False
            sockets.append(self)

        def connect(self):
            self.connect_entered.set()
            if self.block_connect:
                assert self.connect_release.wait(5)
            self.connected = True
            for name in ("current_session_runner", "current_app_monitor", "message_processor"):
                getattr(self, name).alive = True

        def is_connected(self):
            return self.connected

        def close(self):
            self.close_entered.set()
            if self.block_close:
                assert self.close_release.wait(5)
            if self.fail_close:
                raise RuntimeError("PRIVATE close error")
            self.closed = True
            self.connected = False
            for name in ("current_session_runner", "current_app_monitor", "message_processor"):
                getattr(self, name).alive = False

        def disconnect(self):
            self.connected = False

    monkeypatch.setattr(slack, "SLACK_AVAILABLE", True)
    monkeypatch.setattr(slack, "WebClient", WebClient)
    monkeypatch.setattr(slack, "SocketModeClient", SocketModeClient)
    return SimpleNamespace(web=web_clients, sockets=sockets, socket_class=SocketModeClient)


def channel(bot="bot-token", app="app-token"):
    return slack.SlackChannel(bot, app_token=app)


async def close(*channels):
    for item in channels:
        await item.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("second_bot,second_app", [
    ("other-bot", "app-token"), ("bot-token", "other-app"),
])
async def test_either_shared_token_blocks_second_sdk_start(sdk, second_bot, second_app):
    first, second = channel(), channel(second_bot, second_app)
    try:
        await first.start()
        await second.start()
        assert len(sdk.web) == len(sdk.sockets) == 1
        assert second.health_snapshot()["fatal"] == "connection_claim_busy"
        await first.stop()
        await second.start()
        assert second._running and len(sdk.sockets) == 2
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_bot_collision_rolls_back_new_app_prefix(sdk):
    first, refused, independent = channel(), channel("bot-token", "new-app"), channel("new-bot", "new-app")
    try:
        await first.start()
        await refused.start()
        assert refused.health_snapshot()["fatal"] == "connection_claim_busy"
        assert refused._slack_app_claim is None and refused._slack_bot_claim is None
        await independent.start()
        assert independent._running and len(sdk.web) == 2
    finally:
        await close(first, refused, independent)


@pytest.mark.asyncio
async def test_prefix_rollback_failure_retains_app_handle_for_explicit_stop(sdk, monkeypatch):
    original_acquire = polling_claims.acquire_slack_app_claim
    wrapped = False

    def acquire(token):
        nonlocal wrapped
        claim = original_acquire(token)
        if token == "new-app" and not wrapped:
            wrapped = True
            release = claim.release
            attempts = 0

            def fail_once():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("offline prefix release failure")
                release()

            claim.release = fail_once
        return claim

    monkeypatch.setattr(polling_claims, "acquire_slack_app_claim", acquire)
    first, refused, independent = channel(), channel("bot-token", "new-app"), channel("new-bot", "new-app")
    try:
        await first.start()
        with pytest.raises(RuntimeError, match="offline prefix release failure"):
            await refused.start()
        assert refused._slack_app_claim is not None and refused._slack_bot_claim is None
        assert len(sdk.web) == 1
        await independent.start()
        assert independent.health_snapshot()["fatal"] == "connection_claim_busy"
        await refused.stop()
        await independent.start()
        assert independent._running
    finally:
        await close(first, refused, independent)


@pytest.mark.asyncio
async def test_independent_pair_and_redundant_start(sdk):
    first, second = channel(), channel("other-bot", "other-app")
    try:
        await asyncio.gather(first.start(), first.start())
        await first.start()
        await second.start()
        assert len(sdk.web) == len(sdk.sockets) == 2
        assert first._running and second._running
    finally:
        await close(first, second)


@pytest.mark.asyncio
async def test_cancelled_connect_waits_for_worker_and_close_before_release(sdk, monkeypatch):
    first, second = channel(), channel()
    original = sdk.socket_class.connect

    def blocked_connect(self):
        self.block_connect = self is sdk.sockets[0]
        return original(self)

    monkeypatch.setattr(sdk.socket_class, "connect", blocked_connect)
    starting = asyncio.create_task(first.start())
    try:
        while not sdk.sockets:
            await asyncio.sleep(0)
        socket = sdk.sockets[0]
        assert await asyncio.to_thread(socket.connect_entered.wait, 2)
        starting.cancel()
        await second.start()
        assert len(sdk.web) == 1 and second.health_snapshot()["fatal"] == "connection_claim_busy"
        socket.connect_release.set()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert socket.closed and first._slack_app_claim is None
        await second.start()
        assert second._running
    finally:
        if sdk.sockets:
            sdk.sockets[0].connect_release.set()
        await close(first, second)


@pytest.mark.asyncio
async def test_failed_close_keeps_exact_client_and_claims_until_retry(sdk, caplog):
    first, second = channel(), channel()
    try:
        await first.start()
        socket = sdk.sockets[0]
        socket.fail_close = True
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await first.stop()
        assert first._socket_client is socket
        assert first._slack_app_claim is not None and first._slack_bot_claim is not None
        assert "PRIVATE close error" not in caplog.text
        await first.start()
        assert first.health_snapshot()["fatal"] == "connection_cleanup_required"
        await second.start()
        assert len(sdk.web) == 1
        socket.fail_close = False
        await first.stop()
        await second.start()
        assert second._running
    finally:
        if sdk.sockets:
            sdk.sockets[0].fail_close = False
        await close(first, second)


@pytest.mark.asyncio
async def test_unknown_runner_keeps_claim_after_close_return(sdk):
    first, second = channel(), channel()
    try:
        await first.start()
        socket = sdk.sockets[0]
        original = socket.current_app_monitor.is_alive
        socket.current_app_monitor.is_alive = lambda: None
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await first.stop()
        assert socket.closed and first._socket_client is socket
        await second.start()
        assert len(sdk.web) == 1
        socket.current_app_monitor.is_alive = original
        await first.stop()
        await second.start()
        assert second._running
    finally:
        if sdk.sockets:
            sdk.sockets[0].current_app_monitor.is_alive = lambda: False
        await close(first, second)


@pytest.mark.asyncio
async def test_release_failure_keeps_remaining_claim_handle_for_retry(sdk):
    first, contender = channel(), channel("other-bot", "app-token")
    try:
        await first.start()
        claim = first._slack_bot_claim
        original = claim.release
        failures = 0

        def fail_once():
            nonlocal failures
            original()
            failures += 1
            if failures == 1:
                raise RuntimeError("offline release failure")

        claim.release = fail_once
        with pytest.raises(RuntimeError, match="offline release failure"):
            await first.stop()
        assert first._slack_bot_claim is claim and first._slack_app_claim is not None
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "connection_claim_busy"
        assert len(sdk.web) == 1
        await first.stop()
        await contender.start()
        assert contender._running
    finally:
        await close(first, contender)


@pytest.mark.asyncio
async def test_cancelled_blocking_close_does_not_release_early(sdk, monkeypatch):
    first, second = channel(), channel()
    original = sdk.socket_class.close

    def blocked_close(self):
        self.block_close = True
        return original(self)

    monkeypatch.setattr(sdk.socket_class, "close", blocked_close)
    try:
        await first.start()
        socket = sdk.sockets[0]
        stopping = asyncio.create_task(first.stop())
        assert await asyncio.to_thread(socket.close_entered.wait, 2)
        stopping.cancel()
        await second.start()
        assert len(sdk.web) == 1 and second.health_snapshot()["fatal"] == "connection_claim_busy"
        socket.close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        await second.start()
        assert second._running
    finally:
        for socket in sdk.sockets:
            socket.close_release.set()
        await close(first, second)


@pytest.mark.asyncio
async def test_manager_replacement_waits_for_retired_close(sdk, monkeypatch):
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.05)
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    manager = ChannelManager()
    first, second = channel(), channel()
    manager.register(first)
    try:
        await manager.start_all()
        socket = sdk.sockets[0]
        socket.block_close = True
        manager.register(second)
        assert await asyncio.to_thread(socket.close_entered.wait, 2)
        await manager.start_all()
        assert len(sdk.web) == 1 and not second._running
        socket.close_release.set()
        await manager.wait_platform_cleanup("slack")
        await manager.start_all()
        assert second._running and len(sdk.web) == 2
    finally:
        for socket in sdk.sockets:
            socket.close_release.set()
        await manager.stop_all()


@pytest.mark.asyncio
async def test_manual_ingress_claims_neither_token(sdk):
    manual, socket = channel(app=""), channel()
    try:
        await manual.start()
        await socket.start()
        assert manual._running and socket._running
        assert manual._slack_app_claim is None and manual._slack_bot_claim is None
        assert len(sdk.web) == 2 and len(sdk.sockets) == 1
    finally:
        await close(manual, socket)
