"""Ntfy holds one stream probe through quiet health and proven response close."""

import asyncio
import logging

import httpx
import pytest

from agents.core.channels import ntfy
from agents.core.channels.reconnect import PollingCircuit
from tests.test_ntfy_inbound import Frames, event, line, setup_channel, until


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.mark.asyncio
async def test_quiet_stream_becomes_healthy_after_owned_timer_without_second_get(
        tmp_path, monkeypatch):
    channel, _, _, _, requests, stream = setup_channel(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def quiet(_seconds):
        entered.set()
        await release.wait()

    monkeypatch.setattr(ntfy, "_quiet_sleep", quiet)
    try:
        await channel.start()
        await asyncio.wait_for(entered.wait(), 1)
        assert len(requests) == 1
        assert channel.health_snapshot()["state"] != "healthy"
        assert channel.health_snapshot()["circuit"]["probe_active"]
        release.set()
        await until(lambda: channel.health_snapshot()["state"] == "healthy")
        assert len(requests) == 1
        assert channel.health_snapshot()["circuit"] == {
            "state": "closed", "failures": 0, "retry_in_s": 0, "probe_active": True}
    finally:
        release.set()
        await channel.stop()
    assert stream.closed and not channel.health_snapshot()["circuit"]["probe_active"]


@pytest.mark.asyncio
async def test_early_stream_closes_open_circuit_then_one_half_open_get(tmp_path, monkeypatch):
    channel, _, _, _, _requests, _stream = setup_channel(tmp_path)
    await channel.client.aclose()
    clock = Clock()
    channel._stream_circuit = PollingCircuit(clock=clock)
    channel._backoff.jitter = 0
    delays, requested_at = [], []
    holding = Frames([], hold=True)

    async def transport(_request):
        requested_at.append(clock.now)
        return httpx.Response(200, stream=(Frames([]) if len(requested_at) <= 5 else holding))

    async def advance(delay):
        delays.append(delay)
        clock.now += delay
        await asyncio.sleep(0)

    monkeypatch.setattr(ntfy, "sleep", advance)
    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        await channel.start()
        await until(lambda: len(requested_at) == 6)
        assert requested_at[-1] - requested_at[-2] >= 120
        assert delays[:4] == [2, 5, 10, 30]
        assert len(requested_at) == 6
        assert channel.health_snapshot()["circuit"]["probe_active"]
    finally:
        await channel.stop()
    assert holding.closed


@pytest.mark.asyncio
async def test_application_handler_exception_is_fixed_log_and_stream_continues(
        tmp_path, caplog):
    channel, _, _, _, requests, _ = setup_channel(
        tmp_path, [line(event("first")), line(event("second"))])
    seen = []

    async def handle(value):
        if value.get("id") == "first":
            raise RuntimeError("PRIVATE message body")
        seen.append(value["id"])

    channel._on_message = handle
    try:
        with caplog.at_level(logging.WARNING, logger="jarvis.channels.ntfy"):
            await channel.start()
            await until(lambda: bool(seen))
        assert seen == ["second"] and len(requests) == 1
        assert channel.health_snapshot()["circuit"]["failures"] == 0
        assert "ntfy inbound message handling failed" in caplog.text
        assert "PRIVATE" not in caplog.text
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_response_close_exception_keeps_lease_and_refuses_restart(tmp_path, monkeypatch):
    from agents.core.channels import polling_claims

    # This test intentionally retains unconfirmed cleanup and its kernel claim.
    monkeypatch.setattr(polling_claims, "install_root", lambda: tmp_path / "install")
    channel, _, _, _, requests, stream = setup_channel(tmp_path)

    async def bad_close():
        raise RuntimeError("PRIVATE close detail")

    monkeypatch.setattr(stream, "aclose", bad_close)
    await channel.start()
    await until(lambda: bool(requests))
    with pytest.raises(RuntimeError, match="ntfy stream cleanup unconfirmed"):
        await channel.stop()
    assert channel.health_snapshot()["circuit"]["probe_active"]
    assert channel._stream_close_task is not None
    await channel.start()
    assert not channel._running
    assert channel.health_snapshot()["fatal"] == "stream_cleanup_required"
    assert len(requests) == 1
    await channel.client.aclose()


@pytest.mark.asyncio
async def test_outbound_only_channel_exposes_no_inbound_circuit(tmp_path):
    channel, _, _, _, _, _ = setup_channel(tmp_path)
    channel.inbound = False
    try:
        assert "circuit" not in channel.health_snapshot()
        await channel.start()
        assert "circuit" not in channel.health_snapshot()
    finally:
        await channel.stop()
