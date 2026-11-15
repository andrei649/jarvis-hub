"""Telegram gates only getUpdates transport calls with an exclusive circuit lease."""

import asyncio

import httpx
import pytest

from agents.core.channels import telegram
from agents.core.channels.reconnect import PollingCircuit
from agents.core.channels.telegram import TelegramChannel


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def status_error(status, body=None):
    request = httpx.Request("GET", "https://telegram.invalid/getUpdates")
    response = httpx.Response(status, json=body or {}, request=request)
    return httpx.HTTPStatusError("private transport detail", request=request, response=response)


@pytest.fixture
def rig(monkeypatch):
    clock = Clock()
    channel = TelegramChannel("opaque-test-token")
    channel._poll_circuit = PollingCircuit(clock=clock)
    channel._running = True
    channel._ladder().jitter = 0
    waits = []

    async def advance(delay):
        waits.append(delay)
        clock.now += delay
        await asyncio.sleep(0)

    monkeypatch.setattr(telegram, "_backoff_sleep", advance)
    return channel, clock, waits


@pytest.mark.asyncio
async def test_five_transport_failures_open_and_one_recovery_probe_closes(rig):
    channel, clock, waits = rig
    called_at = []

    async def get_updates(*, timeout=25):
        called_at.append(clock.now)
        if len(called_at) <= 5:
            raise status_error(502)
        channel._running = False
        return []

    channel._get_updates = get_updates
    try:
        await asyncio.wait_for(channel._poll_loop(), 2)
        assert len(called_at) == 6
        assert called_at[-1] - called_at[-2] >= 120
        assert waits[:4] == [1, 2, 5, 10]
        assert waits[4] >= 120
        assert channel.health_snapshot()["circuit"] == {
            "state": "closed", "failures": 0, "retry_in_s": 0, "probe_active": False}
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_429_retry_after_is_one_wait_before_next_admission(rig):
    channel, clock, waits = rig
    called_at = []

    async def get_updates(*, timeout=25):
        called_at.append(clock.now)
        if len(called_at) == 1:
            raise status_error(429, {"parameters": {"retry_after": 9}})
        channel._running = False
        return []

    channel._get_updates = get_updates
    try:
        await asyncio.wait_for(channel._poll_loop(), 2)
        assert called_at == [0, 9]
        assert waits == [9]
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_fatal_401_keeps_fixed_reprobe_without_breaker_failure(rig):
    channel, clock, waits = rig
    called_at = []

    async def get_updates(*, timeout=25):
        called_at.append(clock.now)
        if len(called_at) == 1:
            raise status_error(401)
        channel._running = False
        return []

    channel._get_updates = get_updates
    try:
        await asyncio.wait_for(channel._poll_loop(), 2)
        assert called_at == [0, 600] and waits == [600]
        assert channel.health_snapshot()["circuit"]["failures"] == 0
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_handler_failure_after_success_cannot_open_transport_breaker(rig, monkeypatch):
    channel, _clock, waits = rig
    calls = 0

    async def get_updates(*, timeout=25):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"update_id": 1}]
        channel._running = False
        return []

    async def bad_handler(_update, _page):
        raise RuntimeError("PRIVATE body")

    monkeypatch.setattr(telegram, "HANDLING_ERROR_PAUSE", 0)
    channel._get_updates = get_updates
    channel._handle_update = bad_handler
    try:
        await asyncio.wait_for(channel._poll_loop(), 2)
        assert calls == 2 and waits == []
        assert channel.health_snapshot()["circuit"]["failures"] == 0
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_cancelled_get_updates_releases_probe_lease(rig):
    channel, _clock, _waits = rig
    entered = asyncio.Event()

    async def get_updates(*, timeout=25):
        entered.set()
        await asyncio.Event().wait()

    channel._get_updates = get_updates
    polling = asyncio.create_task(channel._poll_loop())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert channel.health_snapshot()["circuit"]["probe_active"]
        polling.cancel()
        with pytest.raises(asyncio.CancelledError):
            await polling
        assert not channel.health_snapshot()["circuit"]["probe_active"]
    finally:
        polling.cancel()
        await channel.client.aclose()
