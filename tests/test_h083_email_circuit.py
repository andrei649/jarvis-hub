"""The IMAP circuit gates real fetches while preserving email routing."""

from __future__ import annotations

import asyncio
import imaplib
import threading

import pytest

from agents.core.channels import email
from agents.core.channels.reconnect import PollingCircuit


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.mark.asyncio
async def test_open_gate_suppresses_imap_fetch_until_one_recovery_probe(monkeypatch):
    clock = Clock()
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    channel._circuit = PollingCircuit(clock=clock, failure_threshold=1)
    calls = []
    waits = asyncio.Queue()
    resume = asyncio.Event()

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("offline")
        return []

    async def hold_sleep(delay):
        waits.put_nowait(delay)
        await resume.wait()
        resume.clear()

    monkeypatch.setattr(channel, "_imap_fetch", fetch)
    monkeypatch.setattr(email.asyncio, "sleep", hold_sleep)
    await channel.start()
    try:
        assert await asyncio.wait_for(waits.get(), 1) == 120
        assert calls == [1]
        assert channel.health_snapshot()["circuit"]["state"] == "open"
        clock.advance(119)
        resume.set()
        assert await asyncio.wait_for(waits.get(), 1) == 1
        assert calls == [1], "an early wake must recheck the open gate"
        clock.advance(1)
        resume.set()
        assert await asyncio.wait_for(waits.get(), 1) == 60
        assert calls == [1, 1]
        assert channel.health_snapshot()["circuit"]["state"] == "closed"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_fatal_imap_login_keeps_slow_reprobe_without_tripping_circuit(monkeypatch):
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    channel._circuit = PollingCircuit(failure_threshold=1)
    calls = []
    waits = asyncio.Queue()
    blocked = asyncio.Event()

    def fetch():
        calls.append(1)
        raise imaplib.IMAP4.error("authentication failed")

    async def hold_sleep(delay):
        waits.put_nowait(delay)
        await blocked.wait()

    monkeypatch.setattr(channel, "_imap_fetch", fetch)
    monkeypatch.setattr(email.asyncio, "sleep", hold_sleep)
    await channel.start()
    try:
        assert await asyncio.wait_for(waits.get(), 1) == 600
        assert calls == [1]
        assert channel.health_snapshot()["circuit"]["state"] == "closed"
        assert channel.health_snapshot()["state"] == "fatal"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_routing_error_after_successful_fetch_does_not_trip_transport_gate(monkeypatch):
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    channel._circuit = PollingCircuit(failure_threshold=1)
    calls = []
    routed = []
    waits = asyncio.Queue()
    blocked = asyncio.Event()
    channel._route_failures[("v", 1)] = email.ROUTE_ATTEMPTS - 1

    def fetch():
        calls.append(1)
        return [{"_validity": "v", "uid": 1, "attachments": []}]

    async def route(_item, _budget):
        routed.append(1)
        raise ValueError("bad message")

    async def hold_sleep(delay):
        waits.put_nowait(delay)
        await blocked.wait()

    monkeypatch.setattr(channel, "_imap_fetch", fetch)
    monkeypatch.setattr(channel, "_route", route)
    monkeypatch.setattr(email.asyncio, "sleep", hold_sleep)
    await channel.start()
    try:
        assert await asyncio.wait_for(waits.get(), 1) == 60
        assert calls == [1] and routed == [1]
        assert channel.health_snapshot()["circuit"]["state"] == "closed"
        assert channel.health_snapshot()["state"] == "healthy"
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_retains_probe_lease_until_blocking_worker_settles(monkeypatch):
    channel = email.EmailChannel(imap_config={"host": "offline.invalid", "user": "owner"})
    entered, release = threading.Event(), threading.Event()

    def fetch():
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(channel, "_imap_fetch", fetch)
    stopping = None
    try:
        await channel.start()
        assert await asyncio.to_thread(entered.wait, 1)
        assert channel.health_snapshot()["circuit"]["probe_active"] is True
        stopping = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        await asyncio.gather(stopping, return_exceptions=True)
        assert channel.health_snapshot()["circuit"]["probe_active"] is True
        assert channel._circuit.reset() is False
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            await channel.start()
    finally:
        release.set()
        await asyncio.wait_for(channel.stop(), 2)
        assert channel.health_snapshot()["circuit"]["probe_active"] is False
