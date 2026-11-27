"""Actual manager notice dispatch must respect current owner and failure state."""

import asyncio
import threading

import pytest

from agents.core.channels import delivery_ledger, outbound
from agents.core.channels.base import ChannelAdapter
from agents.core.channels.manager import ChannelManager


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


async def host(monkeypatch, cid="voice"):
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    monkeypatch.setattr(outbound, "resolve_destination", lambda *_args: ({}, None))
    manager = ChannelManager()
    source, sink = Adapter(cid), Adapter("telegram")
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
        manager.register(Adapter("voice"))
        await drain(manager)
        assert sink.sent == []
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_retired_adapter_fatal_callback_cannot_report_for_replacement(monkeypatch):
    manager, source, sink = await host(monkeypatch)
    try:
        manager.register(Adapter("voice"))
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
            manager.register(Adapter("voice"))
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
        assert await manager.pause_failed("telegram") == {"status": "stop_unconfirmed"}
        assert sink._running is True
        await drain(manager)
        assert sink.sent == []
    finally:
        sink.stop = original_stop
        await manager.stop_all()


@pytest.mark.asyncio
async def test_destination_resolution_failure_logs_fixed_diagnostic_and_sends_nothing(monkeypatch, caplog):
    manager, source, sink = await host(monkeypatch)

    def resolve(_manager, channel):
        raise RuntimeError("PRIVATE destination detail")

    monkeypatch.setattr(outbound, "resolve_destination", resolve)
    try:
        source.health.failed_fatally("offline_failure")
        await drain(manager)
        assert sink.sent == []
        assert "Owner notice destination could not be resolved" in caplog.text
        assert "PRIVATE" not in caplog.text
    finally:
        await manager.stop_all()
