"""H083 failed-channel controls preserve the loaded adapter and owner intent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels.base import ChannelAdapter
from agents.core.channels.manager import ChannelManager
from agents.core.commands import CommandContext, Principal
from agents.core.platform_commands import platform_command


class FakeChannel(ChannelAdapter):
    def __init__(self, name="telegram", *, start_gate=None, stop_gate=None):
        super().__init__(name)
        self.starts = self.stops = 0
        self.start_gate = start_gate
        self.stop_gate = stop_gate

    async def start(self):
        self.starts += 1
        if self.start_gate:
            await self.start_gate.wait()
        self._running = True
        self.health.ok()

    async def stop(self):
        self.stops += 1
        if self.stop_gate:
            await self.stop_gate.wait()
        self._running = False
        self.health.stopped()

    async def send(self, message: str, **kwargs):
        return True


def _ctx(manager, args="", owner=True):
    return CommandContext(SimpleNamespace(channel_manager=manager),
                          Principal(channel="web", admin=owner), "platform", args)


@pytest.mark.asyncio
async def test_list_and_owner_grammar_do_not_mutate_channels():
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    assert "owner" in (await platform_command(_ctx(manager, owner=False))).lower()
    reply = await platform_command(_ctx(manager))
    assert "telegram" in reply and "idle" in reply
    assert "Usage" in await platform_command(_ctx(manager, "pause"))
    assert "Usage" in await platform_command(_ctx(manager, "unknown telegram"))
    assert channel.starts == channel.stops == 0


@pytest.mark.asyncio
async def test_only_confirmed_failed_channel_can_pause_and_resume_same_object():
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    await channel.start()
    assert (await manager.pause_failed("telegram"))["status"] == "not_failed"
    channel.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "paused"
    assert manager.get("telegram") is channel and not channel._running
    await manager.start_all()
    assert channel.starts == 1
    assert (await manager.resume_paused("telegram"))["status"] == "resumed"
    assert channel._running and channel.starts == 2


@pytest.mark.asyncio
async def test_sdk_zero_failure_retrying_and_unconfigured_are_refused():
    manager = ChannelManager()
    channel = FakeChannel("discord")
    manager.register(channel)
    channel.health.state = "retrying"  # SDK not-ready startup, no recorded failure.
    assert (await manager.pause_failed("discord"))["status"] == "not_failed"
    assert (await manager.pause_failed("missing"))["status"] == "unknown"
    assert channel.stops == 0


@pytest.mark.asyncio
async def test_fatal_channel_pause_preserves_fatal_notice_callback():
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    callback = channel.health.on_fatal
    channel.health.failed_fatally("unauthorized")
    assert (await manager.pause_failed("telegram"))["status"] == "paused"
    assert channel.health.on_fatal is callback
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "paused"


@pytest.mark.asyncio
async def test_concurrent_pause_and_resume_are_serialized():
    stop_gate = asyncio.Event()
    manager = ChannelManager()
    channel = FakeChannel(stop_gate=stop_gate)
    manager.register(channel)
    channel.health.retrying("network", 5)
    first = asyncio.create_task(manager.pause_failed("telegram"))
    await asyncio.sleep(0)
    second = asyncio.create_task(manager.pause_failed("telegram"))
    stop_gate.set()
    assert (await first)["status"] == "paused"
    assert (await second)["status"] == "already_paused"
    assert channel.stops == 1


@pytest.mark.asyncio
async def test_timed_out_resume_cleans_late_start_and_preserves_pause(monkeypatch):
    from agents.core import lifecycle_budget

    monkeypatch.setattr(lifecycle_budget, "CHANNEL_START_BUDGET", 0.01)
    release = asyncio.Event()
    manager = ChannelManager()
    class LateChannel(FakeChannel):
        async def start(self):
            self.starts += 1
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Model a shielded SDK worker that can finish after timeout.
                await release.wait()
            self._running = True

    channel = LateChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "paused"
    assert (await manager.resume_paused("telegram"))["status"] == "start_unconfirmed"
    assert (await manager.resume_paused("telegram"))["status"] == "start_unconfirmed"
    release.set()
    await manager.wait_platform_cleanup("telegram")
    assert not channel._running and (await manager.platform_snapshot())["telegram"]["pause_state"]


@pytest.mark.asyncio
async def test_safe_mode_refuses_resume_before_start_and_cleans_mid_start(monkeypatch):
    from agents.core import safe_mode

    active = {"value": False}
    monkeypatch.setattr(safe_mode, "enabled", lambda: active["value"])
    release = asyncio.Event()
    manager = ChannelManager()
    channel = FakeChannel(start_gate=release)
    manager.register(channel)
    channel.health.retrying("network", 5)
    await manager.pause_failed("telegram")
    active["value"] = True
    assert (await manager.resume_paused("telegram"))["status"] == "safe_mode"
    assert channel.starts == 0
    active["value"] = False
    task = asyncio.create_task(manager.resume_paused("telegram"))
    await asyncio.sleep(0)
    active["value"] = True
    release.set()
    assert (await task)["status"] == "safe_mode"
    assert not channel._running
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "paused"


@pytest.mark.asyncio
async def test_shutdown_invalidates_start_all_without_starting_next_channel():
    release = asyncio.Event()
    manager = ChannelManager()
    first = FakeChannel("telegram", start_gate=release)
    second = FakeChannel("ntfy")
    manager.register(first)
    manager.register(second)
    starting = asyncio.create_task(manager.start_all())
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(manager.stop_all())
    release.set()
    await asyncio.gather(starting, shutdown)
    assert not first._running and second.starts == 0


@pytest.mark.asyncio
async def test_cancelled_resume_tracks_and_closes_late_sdk_worker():
    release = asyncio.Event()

    class LateChannel(FakeChannel):
        async def start(self):
            self.starts += 1
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            self._running = True

    manager = ChannelManager()
    channel = LateChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    await manager.pause_failed("telegram")
    running = asyncio.create_task(manager.resume_paused("telegram"))
    await asyncio.sleep(0)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    release.set()
    await manager.wait_platform_cleanup("telegram")
    assert channel.starts == 1 and not channel._running
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "paused"


@pytest.mark.asyncio
async def test_stop_all_bypasses_held_start_lock_and_fences_late_worker(monkeypatch):
    from agents.core import lifecycle_budget

    monkeypatch.setattr(lifecycle_budget, "CHANNEL_START_BUDGET", 1)
    release = asyncio.Event()

    class LateChannel(FakeChannel):
        async def start(self):
            self.starts += 1
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            self._running = True

    manager = ChannelManager()
    channel = LateChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    await manager.pause_failed("telegram")
    running = asyncio.create_task(manager.resume_paused("telegram"))
    await asyncio.sleep(0)
    await asyncio.wait_for(manager.stop_all(), 0.2)
    assert (await manager.resume_paused("telegram"))["status"] == "shutdown"
    release.set()
    assert (await running)["status"] == "shutdown"
    await manager.wait_platform_cleanup("telegram")
    assert not channel._running


@pytest.mark.asyncio
async def test_start_all_handles_registration_replacement_while_awaiting():
    release = asyncio.Event()
    manager = ChannelManager()
    first = FakeChannel("telegram", start_gate=release)
    second = FakeChannel("ntfy")
    manager.register(first)
    manager.register(second)
    starting = asyncio.create_task(manager.start_all())
    await asyncio.sleep(0)
    replacement = FakeChannel("ntfy")
    manager.register(replacement)
    release.set()
    await starting
    assert second.starts == replacement.starts == 0
    assert manager.get("ntfy") is replacement


@pytest.mark.asyncio
async def test_shutdown_invalidates_in_flight_resume_and_replacement_identity():
    release = asyncio.Event()
    manager = ChannelManager()
    old = FakeChannel(start_gate=release)
    manager.register(old)
    old.health.retrying("network", 5)
    await manager.pause_failed("telegram")
    resume = asyncio.create_task(manager.resume_paused("telegram"))
    await asyncio.sleep(0)
    replacement = FakeChannel()
    manager.register(replacement)
    shutdown = asyncio.create_task(manager.stop_all())
    release.set()
    await shutdown
    result = await resume
    assert result["status"] in {"owner_changed", "shutdown", "start_unconfirmed"}
    await manager.wait_platform_cleanup("telegram")
    assert not old._running and replacement.starts == 0


@pytest.mark.asyncio
async def test_resume_failure_keeps_pause_for_retry():
    manager = ChannelManager()
    channel = FakeChannel()
    manager.register(channel)
    channel.health.retrying("network", 5)
    await manager.pause_failed("telegram")

    async def fail():
        raise RuntimeError("secret credential")

    channel.start = fail
    assert (await manager.resume_paused("telegram"))["status"] == "start_failed"
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "paused"


@pytest.mark.asyncio
async def test_false_running_flag_does_not_confirm_incomplete_stop(monkeypatch):
    from agents.core import lifecycle_budget

    monkeypatch.setattr(lifecycle_budget, "CHANNEL_STOP_BUDGET", 0.01)
    release = asyncio.Event()

    class HalfStopped(FakeChannel):
        async def stop(self):
            self.stops += 1
            self._running = False
            if self.stops == 1:
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()

    manager = ChannelManager()
    channel = HalfStopped()
    manager.register(channel)
    channel.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "stop_unconfirmed"
    assert (await manager.resume_paused("telegram"))["status"] == "start_unconfirmed"
    release.set()
    await manager.wait_platform_cleanup("telegram")
    assert (await manager.resume_paused("telegram"))["status"] == "resumed"
    assert channel.stops >= 2 and channel.starts == 1


@pytest.mark.asyncio
async def test_failed_late_cleanup_retains_unconfirmed_pause(monkeypatch):
    from agents.core import lifecycle_budget

    monkeypatch.setattr(lifecycle_budget, "CHANNEL_START_BUDGET", 0.01)
    release = asyncio.Event()

    class LateAndUnclosable(FakeChannel):
        async def start(self):
            self.starts += 1
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            self._running = True

        async def stop(self):
            self.stops += 1
            self._running = False
            raise RuntimeError("close failed")

    manager = ChannelManager()
    channel = LateAndUnclosable()
    manager.register(channel)
    channel.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "stop_unconfirmed"
    # First stop did not confirm closure. A second failed stop cannot authorize start.
    assert (await manager.resume_paused("telegram"))["status"] == "stop_unconfirmed"
    assert channel.starts == 0
    # A separate timeout cleanup from an authorized paused state also marks failure.
    channel.stop = FakeChannel.stop.__get__(channel)
    assert (await manager.resume_paused("telegram"))["status"] == "start_unconfirmed"
    channel.stop = LateAndUnclosable.stop.__get__(channel)
    release.set()
    await manager.wait_platform_cleanup("telegram")
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "stop_unconfirmed"


@pytest.mark.asyncio
async def test_pause_intent_survives_registered_adapter_replacement():
    manager = ChannelManager()
    old = FakeChannel()
    manager.register(old)
    old.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "paused"
    new = FakeChannel()
    manager.register(new)
    await manager.start_all()
    assert new.starts == 0 and manager.get("telegram") is new
    assert (await manager.resume_paused("telegram"))["status"] == "resumed"
    assert new.starts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["safe_mode", "replacement", "shutdown"])
async def test_retry_stop_rechecks_live_authority_before_start(monkeypatch, change):
    from agents.core import safe_mode

    active = {"value": False}
    monkeypatch.setattr(safe_mode, "enabled", lambda: active["value"])
    entered, release = asyncio.Event(), asyncio.Event()

    class RetryStop(FakeChannel):
        async def stop(self):
            self.stops += 1
            self._running = False
            if self.stops == 1:
                raise RuntimeError("initial close failed")
            entered.set()
            await release.wait()

    manager = ChannelManager()
    channel = RetryStop()
    manager.register(channel)
    channel.health.retrying("network", 5)
    assert (await manager.pause_failed("telegram"))["status"] == "stop_unconfirmed"
    running = asyncio.create_task(manager.resume_paused("telegram"))
    await asyncio.wait_for(entered.wait(), 1)
    if change == "safe_mode":
        active["value"] = True
    elif change == "replacement":
        manager.register(FakeChannel())
    else:
        shutdown = asyncio.create_task(manager.stop_all())
        await asyncio.sleep(0)
    release.set()
    result = await running
    assert result["status"] == {"safe_mode": "safe_mode", "replacement": "owner_changed",
                                "shutdown": "shutdown"}[change]
    if change == "shutdown":
        await shutdown
    assert channel.starts == 0


@pytest.mark.asyncio
async def test_late_cleanup_failure_is_retrieved():
    manager = ChannelManager()

    async def fail():
        raise RuntimeError("private error")

    task = asyncio.create_task(fail())
    manager._track_platform_cleanup("telegram", task)
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert not manager._platform_cleanup["telegram"]


@pytest.mark.asyncio
async def test_live_replaced_adapter_is_closed_before_new_one_starts():
    manager = ChannelManager()
    old, new = FakeChannel(), FakeChannel()
    manager.register(old)
    await old.start()
    manager.register(new)
    await manager.start_all()
    assert old.stops == 1 and not old._running
    assert new.starts == 1 and new._running
    await manager.stop_all()
    assert not new._running


@pytest.mark.asyncio
async def test_failed_retired_cleanup_blocks_replacement_start():
    manager = ChannelManager()
    old, new = FakeChannel(), FakeChannel()
    manager.register(old)
    await old.start()

    async def fail_stop():
        old.stops += 1
        raise RuntimeError("private close failure")

    old.stop = fail_stop
    manager.register(new)
    await manager.start_all()
    assert new.starts == 0
    assert (await manager.platform_snapshot())["telegram"]["pause_state"] == "cleanup_unconfirmed"


@pytest.mark.asyncio
async def test_two_concurrent_shutdowns_keep_reopen_fenced_until_both_finish():
    first_release, second_release = asyncio.Event(), asyncio.Event()

    class TwoStops(FakeChannel):
        async def stop(self):
            self.stops += 1
            await (first_release if self.stops == 1 else second_release).wait()
            self._running = False

    manager = ChannelManager()
    channel = TwoStops()
    manager.register(channel)
    first = asyncio.create_task(manager.stop_all())
    await asyncio.sleep(0)
    second = asyncio.create_task(manager.stop_all())
    await asyncio.sleep(0)
    first_release.set()
    await first
    await manager.start_all()
    assert channel.starts == 0 and not second.done()
    second_release.set()
    await second
