"""Observer admission bounds queued callbacks as well as running tasks."""

from __future__ import annotations

import asyncio
import contextvars
import gc
import warnings

import pytest

from agents.core.extensions.events import ExtensionEventBus


class Runtime:
    def __init__(self, *, hold=False):
        self.seen: list[str] = []
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    def observers(self, _event):
        return ("observer",)

    async def observe(self, _extension, _event, payload):
        self.seen.append(payload["command"])
        await self.release.wait()


def test_stopped_loop_burst_has_bounded_callbacks_and_exact_immediate_reports():
    loop = asyncio.new_event_loop()
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime, loop=loop, max_pending=2)
    try:
        reports = [bus.emit("command.started", command="status") for _ in range(100)]
        assert sum(len(row["delivered"]) for row in reports) == 2
        assert sum(row["dropped"] for row in reports) == 98
        assert bus.dropped == 98

        async def settle():
            await asyncio.sleep(0)
            await bus.drain(timeout=1)

        loop.run_until_complete(settle())
        assert runtime.seen == ["status", "status"]
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_inline_capacity_reports_only_admitted_then_releases_completed_slots():
    runtime = Runtime(hold=True)
    bus = ExtensionEventBus(runtime=runtime, max_pending=2)
    reports = [bus.emit("command.started", command="status") for _ in range(3)]
    assert [row["delivered"] for row in reports] == [["observer"], ["observer"], []]
    assert [row["dropped"] for row in reports] == [0, 0, 1]
    assert bus.dropped == 1
    runtime.release.set()
    await bus.drain(timeout=1)
    await asyncio.sleep(0)
    assert len(runtime.seen) == 2
    assert bus.emit("command.started", command="again")["delivered"] == ["observer"]
    await bus.drain(timeout=1)
    assert runtime.seen[-1] == "again"


def test_scheduling_failure_releases_slot_and_reports_drop():
    class BrokenLoop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, *_args):
            raise RuntimeError("loop refused callback")

    bus = ExtensionEventBus(runtime=Runtime(), loop=BrokenLoop(), max_pending=1)
    for _ in range(2):
        report = bus.emit("command.started", command="status")
        assert report["delivered"] == [] and report["dropped"] == 1
    assert bus.dropped == 2


def test_task_creation_failure_closes_coroutine_and_releases_slot():
    class BrokenLoop:
        def __init__(self):
            self.callbacks = []

        def is_closed(self):
            return False

        def call_soon_threadsafe(self, callback, *args):
            self.callbacks.append((callback, args))

        def create_task(self, _coroutine, **_kwargs):
            raise RuntimeError("task creation refused")

    loop = BrokenLoop()
    bus = ExtensionEventBus(runtime=Runtime(), loop=loop, max_pending=1)
    assert bus.emit("command.started", command="first")["delivered"] == ["observer"]
    assert bus.emit("command.started", command="blocked")["dropped"] == 1
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always", RuntimeWarning)
        callback, args = loop.callbacks.pop()
        callback(*args)
        gc.collect()
    assert not any("never awaited" in str(item.message) for item in observed)
    assert bus.emit("command.started", command="next")["delivered"] == ["observer"]


@pytest.mark.asyncio
async def test_cancelled_task_releases_slot():
    class CancellingRuntime(Runtime):
        async def observe(self, _extension, _event, payload):
            self.seen.append(payload["command"])
            asyncio.current_task().cancel()
            await asyncio.sleep(0)

    runtime = CancellingRuntime()
    bus = ExtensionEventBus(runtime=runtime, max_pending=1)
    assert bus.emit("command.started", command="first")["delivered"] == ["observer"]
    await bus.drain(timeout=1)
    await asyncio.sleep(0)
    assert bus.emit("command.started", command="second")["delivered"] == ["observer"]
    await bus.drain(timeout=1)
    assert runtime.seen == ["first", "second"]


@pytest.mark.asyncio
async def test_a_foreign_running_loop_schedules_on_the_original_loop():
    original = asyncio.new_event_loop()
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime, loop=original, max_pending=1)
    try:
        accepted = bus.emit("command.started", command="status")
        assert accepted["delivered"] == ["observer"]
        assert runtime.seen == [], "the foreign running loop cannot create this bus's task"

        async def settle():
            await asyncio.sleep(0)
            await bus.drain(timeout=1)

        await asyncio.to_thread(original.run_until_complete, settle())
        assert runtime.seen == ["status"]
    finally:
        original.close()


@pytest.mark.asyncio
async def test_lazy_first_running_loop_pins_and_closed_loop_does_not_switch():
    runtime = Runtime()
    bus = ExtensionEventBus(runtime=runtime, max_pending=1, loop=None)
    assert bus.emit("command.started", command="first")["delivered"] == ["observer"]
    await bus.drain(timeout=1)
    assert runtime.seen == ["first"]
    target = bus._loop
    assert target is asyncio.get_running_loop()
    # A separately constructed bus pins a loop that has since closed.
    closed = asyncio.new_event_loop()
    stale = ExtensionEventBus(runtime=runtime, max_pending=1, loop=closed)
    closed.close()
    refused = stale.emit("command.started", command="second")
    assert refused["delivered"] == [] and refused["dropped"] == 1
    assert runtime.seen == ["first"]


@pytest.mark.asyncio
async def test_smart_event_observer_keeps_empty_context_after_admission():
    import uuid

    private = contextvars.ContextVar("private", default="clean")

    class SmartRuntime:
        def __init__(self):
            self.seen = []

        def observers(self, _event):
            return ("observer",)

        async def observe(self, _extension, _event, _payload):
            self.seen.append(private.get())

    runtime = SmartRuntime()
    bus = ExtensionEventBus(runtime=runtime, max_pending=1)
    token = private.set("private-turn")
    try:
        report = bus.emit("approval.smart.requested", request_id=uuid.uuid4().hex,
                          surface="smart", command="status", description="safe operation")
        assert report["delivered"] == ["observer"]
        await bus.drain(timeout=1)
    finally:
        private.reset(token)
    assert runtime.seen == ["clean"]
