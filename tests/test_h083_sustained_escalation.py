"""Manager samples only confirmed sustained channel failures and sends once per episode."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger, outbound
from agents.core.channels.base import ChannelAdapter
from agents.core.channels.escalation import FailureEscalation
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

    async def send(self, message, **_kwargs):
        self.sent.append(message)
        return True


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


async def host(monkeypatch, *, sink=True):
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    monkeypatch.setattr(outbound, "resolve_destination", lambda *_args: ({}, ""))
    clock = Clock()
    manager = ChannelManager()
    manager._failure_escalation = FailureEscalation(clock=clock)
    source, destination = Adapter("slack"), Adapter("ntfy")
    manager.register(source)
    if sink:
        manager.register(destination)
    await manager.start_all()
    return manager, source, destination, clock


async def sample(manager):
    manager._sample_escalation(manager._platform_epoch)
    tasks = tuple(manager._notices)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


@pytest.mark.asyncio
async def test_sustained_failure_threshold_and_stable_recovery_rearm(monkeypatch):
    manager, source, destination, clock = await host(monkeypatch)
    try:
        source.health.retrying("network", 1)
        await sample(manager)
        clock.now = 299
        await sample(manager)
        assert destination.sent == []
        clock.now = 300
        await sample(manager)
        assert len(destination.sent) == 1
        clock.now = 900
        await sample(manager)
        assert len(destination.sent) == 1

        source.health.ok()
        clock.now = 901
        await sample(manager)
        clock.now = 960
        await sample(manager)
        source.health.retrying("network", 1)
        await sample(manager)
        clock.now = 1260
        await sample(manager)
        assert len(destination.sent) == 1  # 59 healthy seconds did not rearm.

        source.health.ok()
        clock.now = 1261
        await sample(manager)
        clock.now = 1321
        await sample(manager)
        source.health.retrying("network", 1)
        await sample(manager)
        clock.now = 1621
        await sample(manager)
        assert len(destination.sent) == 2
        assert all("network" not in message for message in destination.sent)
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_initial_zero_unknown_and_pause_break_pending_failure_duration(monkeypatch):
    manager, source, destination, clock = await host(monkeypatch)
    try:
        source.health.state = "retrying"
        source.health.failures = 0
        await sample(manager)
        clock.now = 500
        source.health.failures = 1
        await sample(manager)
        clock.now = 799
        await sample(manager)
        assert destination.sent == []
        source.health.state = "unknown"
        clock.now = 800
        await sample(manager)
        source.health.state = "retrying"
        clock.now = 900
        await sample(manager)
        manager._platform_paused["slack"] = (source, "paused")
        clock.now = 1200
        await sample(manager)
        manager._platform_paused.pop("slack")
        await sample(manager)
        clock.now = 1499
        await sample(manager)
        assert destination.sent == []
        clock.now = 1500
        await sample(manager)
        assert len(destination.sent) == 1
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_fatal_callback_and_projected_fatal_share_episode_latch(monkeypatch):
    manager, source, destination, clock = await host(monkeypatch)
    try:
        source.health.retrying("network", 1)
        await sample(manager)
        clock.now = 300
        await sample(manager)
        source.health.failed_fatally("PRIVATE credential detail")
        await sample(manager)
        assert len(destination.sent) == 1
        assert "PRIVATE" not in destination.sent[0]
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_missing_destination_spends_episode_without_later_retry(monkeypatch):
    manager, source, destination, clock = await host(monkeypatch, sink=False)
    try:
        source.health.retrying("network", 1)
        await sample(manager)
        clock.now = 300
        await sample(manager)
        manager.register(destination)
        await destination.start()
        clock.now = 600
        await sample(manager)
        assert destination.sent == []
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_repeated_start_replaces_one_monitor_and_stop_joins_it(monkeypatch):
    manager, _source, _destination, _clock = await host(monkeypatch)
    first = manager._escalation_monitor
    try:
        assert first is not None and not first.done()
        await manager.start_all()
        second = manager._escalation_monitor
        assert second is not first and first.done() and not second.done()
        await manager.stop_all()
        assert second.done() and manager._escalation_monitor is None
    finally:
        if not manager._platform_stopping:
            await manager.stop_all()


@pytest.mark.asyncio
async def test_stale_sample_cannot_replace_new_registration_episode(monkeypatch):
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    manager = ChannelManager()
    trigger, old, replacement = Adapter("discord"), Adapter("slack"), Adapter("slack")
    manager.register(trigger)
    manager.register(old)
    await manager.start_all()
    try:
        def replace_during_snapshot():
            manager.register(replacement)
            revision = manager._platform_revisions["slack"]
            manager._failure_escalation.fatal("slack", replacement, revision)
            return {"state": "healthy"}

        trigger.health_snapshot = replace_during_snapshot
        manager._sample_escalation(manager._platform_epoch)
        episode = manager._failure_escalation._episodes["slack"]
        assert episode.adapter is replacement and episode.spent
    finally:
        await manager.stop_all()
