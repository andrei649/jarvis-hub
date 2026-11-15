"""Observer scheduling stays bounded and pinned across thread and loop boundaries."""

from __future__ import annotations

import asyncio
import contextvars
import gc
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core.extensions.events import ExtensionEventBus


class _Runtime:
    def __init__(self, *, hold=False, context=None):
        self.hold = hold
        self.context = context
        self.seen = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def observers(self, _event):
        return ("observer",)

    async def observe(self, extension_id, event, payload):
        self.seen.append((extension_id, event, asyncio.get_running_loop(),
                          self.context.get() if self.context is not None else None))
        self.started.set()
        if self.hold:
            await self.release.wait()


def _emit(bus):
    return bus.emit("command.completed", command="status", status="answered")


def test_stopped_loop_queued_callbacks_are_counted_before_scheduling():
    loop = asyncio.new_event_loop()
    runtime = _Runtime()
    bus = ExtensionEventBus(runtime=runtime, loop=loop, max_pending=2)
    try:
        reports = [_emit(bus) for _ in range(100)]
        assert sum(len(report["delivered"]) for report in reports) == 2
        assert sum(report["dropped"] for report in reports) == 98
        assert bus.dropped == 98
        loop.run_until_complete(asyncio.sleep(0.01))
        loop.run_until_complete(bus.drain(timeout=1))
        assert len(runtime.seen) == 2
    finally:
        loop.close()


def test_task_creation_failure_releases_slot_and_closes_coroutine():
    class FailingLoop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

        def create_task(self, _coroutine, **_kwargs):
            raise RuntimeError("cannot create task")

    bus = ExtensionEventBus(runtime=_Runtime(), loop=FailingLoop(), max_pending=1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        first, second = _emit(bus), _emit(bus)
        gc.collect()
    assert first["delivered"] == second["delivered"] == ["observer"]
    assert bus.dropped == 2
    assert not any("was never awaited" in str(item.message) for item in caught)


@pytest.mark.asyncio
async def test_concurrent_thread_emitters_observe_one_shared_capacity():
    runtime = _Runtime(hold=True)
    bus = ExtensionEventBus(runtime=runtime, max_pending=2)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=16) as pool:
        reports = await asyncio.gather(*(loop.run_in_executor(pool, _emit, bus) for _ in range(100)))
    assert sum(len(report["delivered"]) for report in reports) == 2
    assert sum(report["dropped"] for report in reports) == 98
    await asyncio.wait_for(runtime.started.wait(), 1)
    assert len(runtime.seen) == 2
    runtime.release.set()
    await bus.drain(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("lazy_capture", [False, True])
async def test_foreign_running_loop_emits_onto_captured_loop_only(lazy_capture):
    captured = asyncio.get_running_loop()
    runtime = _Runtime()
    bus = (await asyncio.to_thread(ExtensionEventBus, runtime=runtime) if lazy_capture
           else ExtensionEventBus(runtime=runtime, loop=captured))
    if lazy_capture:
        assert _emit(bus)["delivered"] == ["observer"]
        await bus.drain(timeout=1)
        runtime.seen.clear()

    def foreign_thread():
        async def emit_from_foreign_loop():
            foreign = asyncio.get_running_loop()
            report = _emit(bus)
            await asyncio.sleep(0.05)
            return foreign, report

        return asyncio.run(emit_from_foreign_loop())

    foreign, report = await asyncio.to_thread(foreign_thread)
    await bus.drain(timeout=1)
    assert report["delivered"] == ["observer"]
    assert len(runtime.seen) == 1
    assert runtime.seen[0][2] is captured and runtime.seen[0][2] is not foreign


@pytest.mark.asyncio
async def test_cancelled_delivery_releases_capacity_for_next_event():
    runtime = _Runtime(hold=True)
    bus = ExtensionEventBus(runtime=runtime, max_pending=1)
    assert _emit(bus)["delivered"] == ["observer"]
    await asyncio.wait_for(runtime.started.wait(), 1)
    assert _emit(bus)["dropped"] == 1
    task = next(iter(bus._pending))  # cancel the materialized delivery; no counter internals inspected
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert _emit(bus)["delivered"] == ["observer"]
    runtime.release.set()
    await bus.drain(timeout=1)
    assert len(runtime.seen) == 2


@pytest.mark.asyncio
async def test_smart_observer_gets_empty_context_even_from_worker_thread():
    secret = contextvars.ContextVar("private-turn", default="empty")
    runtime = _Runtime(context=secret)
    bus = ExtensionEventBus(runtime=runtime)
    token = secret.set("private-turn-body")
    try:
        report = await asyncio.to_thread(
            bus.emit, "approval.smart.requested", request_id=uuid.uuid4().hex,
            surface="smart", command="echo safe", description="safe description",
        )
        assert report["delivered"] == ["observer"]
        await bus.drain(timeout=1)
        assert len(runtime.seen) == 1 and runtime.seen[0][3] == "empty"
    finally:
        secret.reset(token)
