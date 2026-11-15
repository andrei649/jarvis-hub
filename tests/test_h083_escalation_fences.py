"""Actual manager notice dispatch must respect current owner and failure state."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.core.channels import delivery_ledger, outbound
from agents.core.channels.base import ChannelAdapter
from agents.core.channels.manager import ChannelManager
from tests.test_h083_sdk_failures import discord_sdk, slack_sdk  # noqa: F401


class Adapter(ChannelAdapter):
    def __init__(self, cid):
        super().__init__(cid)
        self.sent = []

    async def start(self):
        self._running = True
        self.health.ok()

    async def stop(self):
        self._running = False
        self.health.stopped()

    async def send(self, message, **kwargs):
        self.sent.append(message)
        return True


async def host(monkeypatch, cid="discord"):
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    monkeypatch.setattr(outbound, "resolve_destination", lambda *_args: ({}, None))
    manager = ChannelManager()
    source, sink = Adapter(cid), Adapter("ntfy")
    manager.register(source)
    manager.register(sink)
    await manager.start_all()
    return manager, source, sink


async def drain(manager):
    await asyncio.sleep(0)  # Admit callbacks handed back from another thread.
    tasks = tuple(manager._notices)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


@pytest.mark.asyncio
async def test_queued_fatal_notice_is_fenced_by_source_replacement(monkeypatch):
    manager, source, sink = await host(monkeypatch)
    try:
        source.health.failed_fatally("offline_failure")
        manager.register(Adapter("discord"))
        await drain(manager)
        assert sink.sent == []
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_retired_adapter_fatal_callback_cannot_report_for_replacement(monkeypatch):
    manager, source, sink = await host(monkeypatch)
    try:
        manager.register(Adapter("discord"))
        source.health.failed_fatally("offline_failure")
        await drain(manager)
        assert sink.sent == []
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_recovery_before_queued_notice_suppresses_stale_message(monkeypatch):
    manager, source, sink = await host(monkeypatch)
    try:
        source.health.failed_fatally("offline_failure")
        source.health.ok()
        await drain(manager)
        assert sink.sent == []
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_notice_does_not_include_custom_channel_name_or_raw_reason(monkeypatch):
    manager, source, sink = await host(monkeypatch, "PRIVATE_CHANNEL_NAME")
    try:
        source.health.failed_fatally("PRIVATE_FAILURE_DETAIL")
        await drain(manager)
        assert len(sink.sent) == 1
        assert "PRIVATE" not in sink.sent[0]
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("replace", [False, True])
async def test_thread_fatal_handoff_rechecks_current_registration(monkeypatch, replace):
    manager, source, sink = await host(monkeypatch)
    try:
        worker = threading.Thread(target=source.health.failed_fatally, args=("offline_failure",))
        worker.start()
        worker.join(timeout=1)  # Keep the loop parked until replacement, not SDK/network work.
        assert not worker.is_alive()
        if replace:
            manager.register(Adapter("discord"))
        await drain(manager)
        assert len(sink.sent) == (0 if replace else 1)
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_queued_notice_honors_destination_pause_even_when_stop_is_unconfirmed(monkeypatch):
    manager, source, sink = await host(monkeypatch)
    original_stop = sink.stop

    async def failed_stop():
        raise RuntimeError("offline stop failure")

    try:
        source.health.failed_fatally("offline_failure")
        sink.health.retrying("network", 1)
        sink.stop = failed_stop
        assert await manager.pause_failed("ntfy") == {"status": "stop_unconfirmed"}
        assert sink._running is True
        await drain(manager)
        assert sink.sent == []
    finally:
        sink.stop = original_stop
        await manager.stop_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["slack", "discord"])
async def test_actual_sdk_snapshots_drive_only_confirmed_failure_episodes(monkeypatch, request, platform):
    from agents.core.channels.discord import DiscordChannel
    from agents.core.channels.escalation import FailureEscalation
    from agents.core.channels.slack import SlackChannel

    clients = request.getfixturevalue(f"{platform}_sdk")
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    monkeypatch.setattr(outbound, "resolve_destination", lambda *_args: ({}, None))
    clock = SimpleNamespace(now=0.0)
    manager = ChannelManager()
    manager._failure_escalation = FailureEscalation(clock=lambda: clock.now)
    source = (SlackChannel("offline-bot", app_token="offline-app") if platform == "slack"
              else DiscordChannel("offline-bot"))
    sink = Adapter("ntfy")
    manager.register(source)
    manager.register(sink)
    startup = None
    if platform == "discord":
        startup = asyncio.create_task(manager.start_all())
        async with asyncio.timeout(1):
            while not clients:
                await asyncio.sleep(0)
        client = clients[0]
        await asyncio.wait_for(client.started.wait(), 1)
    else:
        await manager.start_all()
        client = clients[0]
    ready_attr = "connected" if platform == "slack" else "ready"
    probe_attr = "is_connected" if platform == "slack" else "is_ready"
    original_probe = getattr(client, probe_attr)

    async def sample(at):
        clock.now = at
        manager._sample_escalation(manager._platform_epoch)
        await drain(manager)

    try:
        if platform == "discord":
            assert source.health_snapshot()["failures"] == 0
            await sample(0)
            await sample(500)
            assert sink.sent == []
            client.ready = True
            await client.events["on_ready"]()
            await asyncio.wait_for(startup, 1)
        setattr(client, ready_attr, True)
        await sample(501)
        setattr(client, ready_attr, False)
        assert source.health_snapshot()["failures"] == 1
        await sample(502)
        await sample(801)
        assert sink.sent == []

        def unknown_probe():
            raise RuntimeError("PRIVATE probe error")

        setattr(client, probe_attr, unknown_probe)
        await sample(802)
        assert source.health_snapshot()["state"] == "unknown"
        setattr(client, probe_attr, original_probe)
        await sample(900)
        await sample(1199)
        assert sink.sent == []
        await sample(1200)
        assert len(sink.sent) == 1 and "PRIVATE" not in sink.sent[0]
        setattr(client, ready_attr, True)
        await sample(1201)
        await sample(1261)
        setattr(client, ready_attr, False)
        await sample(1262)
        await sample(1562)
        assert len(sink.sent) == 2
    finally:
        setattr(client, probe_attr, original_probe)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_destination_resolution_failure_logs_fixed_diagnostic_and_uses_fallback(monkeypatch, caplog):
    manager, source, sink = await host(monkeypatch)
    fallback = Adapter("telegram")
    manager.register(fallback)
    await fallback.start()

    def resolve(_manager, channel):
        if channel == "ntfy":
            raise RuntimeError("PRIVATE destination detail")
        return {"chat_id": "offline-owner"}, None

    monkeypatch.setattr(outbound, "resolve_destination", resolve)
    try:
        source.health.failed_fatally("offline_failure")
        await drain(manager)
        assert sink.sent == [] and len(fallback.sent) == 1
        assert "Owner notice destination could not be resolved" in caplog.text
        assert "PRIVATE" not in caplog.text + fallback.sent[0]
    finally:
        await manager.stop_all()
