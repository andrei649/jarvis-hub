"""A timed-out ntfy open owns its late response until exact teardown settles."""

import asyncio

import httpx
import pytest

from agents.core.channels import ntfy
from tests.test_ntfy_inbound import event, line, setup_channel, until


def test_configured_connect_component_reaches_environment_channel():
    channel = ntfy.NtfyChannel.from_env({
        "NTFY_URL": "https://ntfy.example", "NTFY_TOPIC": "home",
    }, connect_timeout_seconds=4)
    assert channel is not None and channel._connect_timeout_seconds == 4


@pytest.mark.asyncio
async def test_httpx_stream_get_uses_configured_connect_and_existing_read_timeout(tmp_path):
    channel, _, _, _, requests, _ = setup_channel(tmp_path)
    channel._connect_timeout_seconds = 0.02
    try:
        await channel.start()
        await until(lambda: bool(requests))
        limits = requests[0].extensions["timeout"]
        assert limits["connect"] == 0.02
        assert limits["read"] == 90.0
    finally:
        await channel.stop()


class HeldOpen:
    def __init__(self, *, close_error=False):
        self.entered = asyncio.Event()
        self.release_open = asyncio.Event()
        self.close_entered = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_error = close_error
        self.opens = 0
        self.closed = False
        self.client_closed = False
        self.timeout = None

    def stream(self, method, url, **kwargs):
        assert method == "GET"
        self.opens += 1
        self.timeout = kwargs["timeout"]
        return self

    async def __aenter__(self):
        self.entered.set()
        await self.release_open.wait()
        return self

    async def __aexit__(self, *_args):
        self.close_entered.set()
        await self.release_close.wait()
        if self.close_error:
            raise RuntimeError("PRIVATE close detail")
        self.closed = True

    @property
    def status_code(self):
        return 200

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield line(event("late"))

    async def aclose(self):
        self.client_closed = True


@pytest.mark.asyncio
async def test_late_open_never_dispatches_and_single_failure_waits_for_close(tmp_path):
    channel, _, _, seen, _, _ = setup_channel(tmp_path)
    await channel.client.aclose()
    client = HeldOpen()
    channel.client = client
    channel._connect_timeout_seconds = 0.01
    channel._backoff.jitter = 0
    try:
        await channel.start()
        await asyncio.wait_for(client.entered.wait(), 1)
        await until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
        assert channel.health_snapshot()["failures"] == 1
        assert client.opens == 1 and channel._healthy_timer is None
        assert channel.health_snapshot()["circuit"]["probe_active"]
        assert isinstance(client.timeout, httpx.Timeout)
        assert client.timeout.connect == 0.01 and client.timeout.read == 90.0
        client.release_open.set()
        await asyncio.wait_for(client.close_entered.wait(), 1)
        assert seen == [] and client.opens == 1
        assert channel.health_snapshot()["failures"] == 1
        client.release_close.set()
        await until(lambda: client.closed)
        assert seen == []
    finally:
        client.release_open.set()
        client.release_close.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_retains_late_open_and_close_ownership(tmp_path):
    channel, _, _, seen, _, _ = setup_channel(tmp_path)
    await channel.client.aclose()
    client = HeldOpen()
    channel.client = client
    channel._connect_timeout_seconds = 0.01
    await channel.start()
    await until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
    stopper = asyncio.create_task(channel.stop())
    try:
        await asyncio.sleep(0)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopper
        await channel.start()
        assert client.opens == 1 and not channel._running
        assert channel.health_snapshot()["circuit"]["probe_active"]
        client.release_open.set()
        await asyncio.wait_for(client.close_entered.wait(), 1)
        assert seen == []
        client.release_close.set()
        await channel.stop()
        assert client.closed and client.client_closed
        assert not channel.health_snapshot()["circuit"]["probe_active"]
    finally:
        client.release_open.set()
        client.release_close.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_failed_late_response_close_retains_lease_and_refuses_restart(tmp_path, monkeypatch):
    from agents.core.channels import polling_claims

    # Unconfirmed response teardown deliberately keeps ownership until process exit.
    monkeypatch.setattr(polling_claims, "install_root", lambda: tmp_path / "install")
    channel, _, _, seen, _, _ = setup_channel(tmp_path)
    await channel.client.aclose()
    client = HeldOpen(close_error=True)
    channel.client = client
    channel._connect_timeout_seconds = 0.01
    await channel.start()
    await until(lambda: channel.health_snapshot()["error"] == "connect_timeout")
    client.release_open.set()
    client.release_close.set()
    await asyncio.wait_for(client.close_entered.wait(), 1)
    await until(lambda: channel._stream_task.done())
    with pytest.raises(RuntimeError, match="ntfy stream cleanup unconfirmed"):
        await channel.stop()
    assert channel.health_snapshot()["circuit"]["probe_active"]
    await channel.start()
    assert client.opens == 1 and seen == []
    assert channel.health_snapshot()["fatal"] == "stream_cleanup_required"
