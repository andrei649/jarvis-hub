"""A delivered native prompt can pause only its owning run's execution clocks."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from agents.core import native_human_wait
from agents.core.agent_runtime import AgentToolRuntime, _OwnedTimeout
from agents.core.native_human_wait import (
    current_human_wait_scope,
    native_human_wait_window,
    runtime_human_wait_scope,
)
from agents.core.tool_rpc import ToolRPCServer


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def advance(self, seconds):
        self.now += seconds


def _use_clock(monkeypatch, clock):
    # Replace only this module's reference; asyncio keeps real monotonic time.
    monkeypatch.setattr(native_human_wait, "time", SimpleNamespace(monotonic=lambda: clock.now))


@pytest.mark.asyncio
async def test_overlapping_native_windows_credit_union_once(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    loop_start = asyncio.get_running_loop().time()
    with runtime_human_wait_scope() as scope:
        with native_human_wait_window(deadline=130.0, current=lambda: True):
            clock.advance(3)
            with native_human_wait_window(deadline=130.0, current=lambda: True):
                clock.advance(4)
                assert scope.seconds() == 7.0
            clock.advance(2)
        assert scope.seconds() == 9.0
    assert current_human_wait_scope() is None
    clock.advance(20)
    assert scope.seconds() == 9.0
    assert 0 <= asyncio.get_running_loop().time() - loop_start < 1.0


@pytest.mark.asyncio
async def test_deadline_bounds_live_and_closed_window(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    with runtime_human_wait_scope() as scope:
        with native_human_wait_window(deadline=103.0, current=lambda: True):
            clock.advance(20)
            assert scope.seconds() == 3.0
        assert scope.seconds() == 3.0


@pytest.mark.asyncio
async def test_lost_current_binding_stops_new_credit(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    live = True
    with (
        runtime_human_wait_scope() as scope,
        native_human_wait_window(deadline=120.0, current=lambda: live),
    ):
        clock.advance(2)
        assert scope.seconds() == 2.0
        live = False
        clock.advance(5)
        assert scope.seconds() == 2.0
        live = True
        clock.advance(2)
        assert scope.seconds() == 2.0


@pytest.mark.asyncio
async def test_bad_window_inputs_and_predicate_errors_fail_closed(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)

    def broken():
        raise RuntimeError("not current")

    with runtime_human_wait_scope() as scope:
        for deadline, current in [
            (float("nan"), lambda: True),
            (float("inf"), lambda: True),
            (99.0, lambda: True),
            ("later", lambda: True),
            (10 ** 1000, lambda: True),
            (120.0, None),
            (120.0, broken),
        ]:
            with native_human_wait_window(deadline=deadline, current=current):
                clock.advance(1)
        assert scope.seconds() == 0.0


@pytest.mark.asyncio
async def test_nonfinite_clock_at_window_entry_never_earns_later_credit(monkeypatch):
    clock = Clock(float("nan"))
    _use_clock(monkeypatch, clock)
    with (
        runtime_human_wait_scope() as scope,
        native_human_wait_window(deadline=120.0, current=lambda: True),
    ):
        clock.now = 105.0
        assert scope.seconds() == 0.0


@pytest.mark.asyncio
async def test_parallel_and_nested_runs_have_independent_credit(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    with (
        runtime_human_wait_scope() as outer,
        native_human_wait_window(deadline=120.0, current=lambda: True),
    ):
        clock.advance(1)
        with runtime_human_wait_scope() as inner:
            assert current_human_wait_scope() is inner
            assert inner.seconds() == 0.0
            with native_human_wait_window(deadline=120.0, current=lambda: True):
                clock.advance(2)
            assert inner.seconds() == 2.0
        assert current_human_wait_scope() is outer
        assert outer.seconds() == 3.0

        async def separate_run():
            with runtime_human_wait_scope() as parallel:
                assert parallel is not outer
                assert parallel.seconds() == 0.0
                with native_human_wait_window(deadline=120.0, current=lambda: True):
                    clock.advance(1)
                return parallel.seconds()

        assert await asyncio.create_task(separate_run()) == 1.0
        assert outer.seconds() == 4.0


@pytest.mark.asyncio
async def test_closed_parent_scope_cannot_be_extended_by_detached_child(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    start = asyncio.Event()
    resume = asyncio.Event()

    async def child():
        start.set()
        await resume.wait()
        assert current_human_wait_scope() is None
        with native_human_wait_window(deadline=120.0, current=lambda: True):
            clock.advance(5)

    with runtime_human_wait_scope() as scope:
        task = asyncio.create_task(child())
        await start.wait()
    resume.set()
    await task
    assert scope.seconds() == 0.0


@pytest.mark.asyncio
async def test_cancellation_resistant_prompt_task_cannot_keep_accruing(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def resistant():
        with native_human_wait_window(deadline=120.0, current=lambda: True):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

    with runtime_human_wait_scope() as scope:
        task = asyncio.create_task(resistant())
        await entered.wait()
        clock.advance(2)
        assert scope.seconds() == 2.0
        task.cancel()
        await cancelled.wait()
        clock.advance(5)
        assert scope.seconds() == 2.0
        release.set()
        await task


@pytest.mark.asyncio
async def test_window_outside_runtime_or_task_is_inert(monkeypatch):
    clock = Clock()
    _use_clock(monkeypatch, clock)
    with native_human_wait_window(deadline=120.0, current=lambda: True):
        clock.advance(2)
    with runtime_human_wait_scope() as scope:
        # asyncio.current_task() is absent in this synchronous callback's thread.
        await asyncio.to_thread(_open_window_without_task, clock)
        assert math.isclose(scope.seconds(), 0.0)


def _open_window_without_task(clock):
    with native_human_wait_window(deadline=120.0, current=lambda: True):
        clock.advance(2)


@pytest.mark.asyncio
async def test_owned_execution_deadline_excludes_only_new_live_wait_credit():
    runtime = AgentToolRuntime(ToolRPCServer())

    async def delivered_wait():
        with native_human_wait_window(
            deadline=asyncio.get_running_loop().time() + 0.2, current=lambda: True,
        ):
            await asyncio.sleep(0.06)
        return "owner answered"

    with runtime_human_wait_scope():
        answer = await runtime._await_owned(
            delivered_wait(), timeout=0.025, exclude_human_wait=True,
        )
    assert answer == "owner answered"


@pytest.mark.asyncio
async def test_preexisting_credit_cannot_extend_next_owned_deadline():
    runtime = AgentToolRuntime(ToolRPCServer())

    with runtime_human_wait_scope() as scope:
        with native_human_wait_window(
            deadline=asyncio.get_running_loop().time() + 0.2, current=lambda: True,
        ):
            await asyncio.sleep(0.05)
        assert scope.seconds() >= 0.04
        with pytest.raises(_OwnedTimeout):
            await runtime._await_owned(
                asyncio.sleep(0.08), timeout=0.02, exclude_human_wait=True,
            )


@pytest.mark.asyncio
async def test_uncredited_owned_wait_keeps_original_deadline():
    runtime = AgentToolRuntime(ToolRPCServer())

    async def delivered_wait():
        with native_human_wait_window(
            deadline=asyncio.get_running_loop().time() + 0.2, current=lambda: True,
        ):
            await asyncio.sleep(0.06)

    with runtime_human_wait_scope(), pytest.raises(_OwnedTimeout):
        await runtime._await_owned(delivered_wait(), timeout=0.02)
