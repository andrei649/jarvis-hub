"""An inbound ntfy subscription owns its exact wire resource until teardown."""

import asyncio

import httpx
import pytest

from agents.core.channels import ntfy, polling_claims
from tests.test_h083_ntfy_deadline import HeldOpen
from tests.test_ntfy_inbound import Frames, setup_channel, until


@pytest.fixture
def channels(tmp_path, monkeypatch):
    monkeypatch.setattr(polling_claims, "install_root", lambda: tmp_path / "install")
    anchor, _, _, _, _, _ = setup_channel(tmp_path)
    made = [anchor]
    requests = {}

    def make(url="https://ntfy.example", topic="home", token="", *, inbound=True):
        seen = []
        stream = Frames([], hold=True)

        async def transport(request):
            seen.append(request)
            return httpx.Response(200, stream=stream)

        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        channel = ntfy.NtfyChannel(url, topic, token=token, inbound=inbound,
                                   client=client, handler=anchor.handler,
                                   pairing=anchor.pairing,
                                   pending_reply_handler=lambda *_args, **_kwargs: False)
        made.append(channel)
        requests[channel] = seen
        return channel

    yield make, requests
    # Each test explicitly stops active owners before the fixture exits.


@pytest.mark.asyncio
@pytest.mark.parametrize("first_url,second_url", [
    ("https://NTFY.example:443/base", "https://ntfy.example/base"),
    ("https://ntfy.example/a/../base", "https://ntfy.example/base"),
    ("https://ntfy.example/café", "https://ntfy.example/caf%C3%A9"),
])
async def test_wire_equivalent_subscriptions_collide_before_second_get(
        channels, first_url, second_url):
    make, requests = channels
    first = make(first_url, token="first-secret")
    second = make(second_url, token="rotated-secret")
    try:
        await first.start()
        await until(lambda: bool(requests[first]))
        await second.start()
        assert second.health_snapshot()["fatal"] == "stream_claim_busy"
        assert not second._running and requests[second] == []
        assert second._cursor_store is None and second._dispatch_task is None
        await first.stop()
        await second.start()
        await until(lambda: bool(requests[second]))
    finally:
        await first.stop()
        await second.stop()


@pytest.mark.asyncio
async def test_distinct_wire_resources_and_send_only_channel_do_not_collide(channels):
    make, requests = channels
    first = make("https://ntfy.example/base", "home")
    other_path = make("https://ntfy.example/BASE", "home")
    other_topic = make("https://ntfy.example/base", "other")
    other_port = make("https://ntfy.example:0/base", "home")
    send_only = make("https://ntfy.example/base", "home", inbound=False)
    try:
        await asyncio.gather(first.start(), other_path.start(), other_topic.start(), other_port.start(),
                             send_only.start())
        await until(lambda: all(requests[ch] for ch in (first, other_path, other_topic,
                                                        other_port)))
        assert all(ch._running for ch in (first, other_path, other_topic, other_port, send_only))
        assert send_only._subscription_claim is None and requests[send_only] == []
    finally:
        await asyncio.gather(first.stop(), other_path.stop(), other_topic.stop(), other_port.stop(),
                             send_only.stop())


@pytest.mark.asyncio
async def test_late_open_and_close_hold_claim_until_exact_cleanup(channels):
    make, requests = channels
    first, contender = make(), make(token="new-token")
    await first.client.aclose()
    held = HeldOpen()
    first.client = held
    first._connect_timeout_seconds = 0.01
    try:
        await first.start()
        await until(lambda: first.health_snapshot()["error"] == "connect_timeout")
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "stream_claim_busy"
        assert requests[contender] == []
        held.release_open.set()
        await asyncio.wait_for(held.close_entered.wait(), 1)
        stopping = asyncio.create_task(first.stop())
        await asyncio.sleep(0)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "stream_claim_busy"
        held.release_close.set()
        await first.stop()
        await contender.start()
        await until(lambda: bool(requests[contender]))
    finally:
        held.release_open.set()
        held.release_close.set()
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_failed_client_close_retains_claim_until_explicit_stop_retry(channels):
    make, requests = channels
    first, contender = make(), make(token="new-token")
    original_close = first.client.aclose
    calls = 0

    async def close_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("PRIVATE close failure")
        await original_close()

    first.client.aclose = close_once
    try:
        await first.start()
        await until(lambda: bool(requests[first]))
        with pytest.raises(RuntimeError, match="PRIVATE close failure"):
            await first.stop()
        await first.start()
        assert first.health_snapshot()["fatal"] == "stream_cleanup_required"
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "stream_claim_busy"
        assert requests[contender] == []
        await first.stop()
        await contender.start()
        await until(lambda: bool(requests[contender]))
    finally:
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_local_startup_failure_retains_claim_until_stop(channels):
    make, requests = channels
    first, contender = make(), make(token="new-token")

    def failed_cursor():
        raise RuntimeError("offline cursor failure")

    first._resume_cursor = failed_cursor
    try:
        with pytest.raises(RuntimeError, match="offline cursor failure"):
            await first.start()
        assert not first._running and requests[first] == []
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "stream_claim_busy"
        assert requests[contender] == []
        await first.stop()
        await contender.start()
        await until(lambda: bool(requests[contender]))
    finally:
        await first.stop()
        await contender.stop()


@pytest.mark.asyncio
async def test_unavailable_claim_refuses_before_cursor_dispatch_or_get(channels, monkeypatch):
    make, requests = channels
    channel = make()
    cursor_reads = []
    channel._resume_cursor = lambda: cursor_reads.append(True)

    def unavailable(_resource):
        raise polling_claims.ClaimUnavailable("unavailable")

    monkeypatch.setattr(polling_claims, "acquire_ntfy_claim", unavailable)
    try:
        await channel.start()
        assert channel.health_snapshot()["fatal"] == "stream_claim_unavailable"
        assert not channel._running and channel._subscription_claim is None
        assert channel._dispatch_task is None and channel._stream_task is None
        assert cursor_reads == [] and requests[channel] == []
    finally:
        await channel.stop()
