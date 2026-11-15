"""A manager timeout cannot transfer an unclosed subscription to another profile."""

import asyncio

import pytest

from agents.core import lifecycle_budget
from agents.core.channels.manager import ChannelManager
from tests.test_h083_ntfy_claims import channels  # noqa: F401
from tests.test_h083_ntfy_deadline import HeldOpen
from tests.test_ntfy_inbound import until


@pytest.mark.asyncio
async def test_manager_retirement_keeps_claim_until_late_response_close(channels, monkeypatch):
    make, requests = channels
    owner, contender = make(), make(token="different-token")
    await owner.client.aclose()
    held = HeldOpen()
    owner.client = held
    owner._connect_timeout_seconds = 0.01
    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.02)
    manager = ChannelManager()
    try:
        await owner.start()
        await until(lambda: owner.health_snapshot()["error"] == "connect_timeout")
        held.release_open.set()
        await asyncio.wait_for(held.close_entered.wait(), 1)
        assert not await manager._bounded_platform_stop("ntfy", owner)
        await manager.wait_platform_cleanup("ntfy")
        assert owner._subscription_claim is not None
        await contender.start()
        assert contender.health_snapshot()["fatal"] == "stream_claim_busy"
        assert requests[contender] == []
        held.release_close.set()
        await owner.stop()
        await contender.start()
        await until(lambda: bool(requests[contender]))
        assert contender._running
    finally:
        held.release_open.set()
        held.release_close.set()
        await owner.stop()
        await contender.stop()
        await manager.wait_platform_cleanup("ntfy")
