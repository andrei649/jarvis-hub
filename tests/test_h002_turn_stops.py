"""A source-assigned generation stop survives synthesized prose and task copying."""

import asyncio

import pytest

from agents.core.tool_loop_result import ToolLoopExitReason
from agents.core.turn_stops import (
    STOP_REASONS,
    detached_turn_stops,
    record_runtime_stop,
    turn_stops_scope,
)


def test_known_stops_are_bounded_deduplicated_and_never_prose():
    with turn_stops_scope() as collector:
        record_runtime_stop(ToolLoopExitReason.MODEL_RESPONSE)
        record_runtime_stop("an arbitrary model answer containing deadline")
        record_runtime_stop(None)
        assert collector.snapshot() == []
        for reason in ToolLoopExitReason:
            record_runtime_stop(reason)
            record_runtime_stop(reason)
        record_runtime_stop("thinking_exhausted")
        for reason in ("generation_failed", "generation_refused", "continuation_refused"):
            record_runtime_stop(reason)
        snapshot = collector.snapshot()
        assert set(snapshot) == STOP_REASONS
        assert len(snapshot) == len(STOP_REASONS)
        snapshot.clear()
        assert collector.snapshot()


@pytest.mark.parametrize("reason", ["generation_failed", "generation_refused", "continuation_refused"])
def test_terminal_orchestrator_failures_have_stable_bounded_reasons(reason):
    with turn_stops_scope() as collector:
        record_runtime_stop(reason)
        assert collector.snapshot() == [reason]


@pytest.mark.asyncio
async def test_copied_child_shares_only_its_request_and_late_writes_are_inert():
    entered, release = asyncio.Event(), asyncio.Event()

    async def late():
        record_runtime_stop("deadline")
        entered.set()
        await release.wait()
        record_runtime_stop("iteration_limit")

    with turn_stops_scope() as outer:
        task = asyncio.create_task(late())
        await entered.wait()
        assert outer.snapshot() == ["deadline"]
        with turn_stops_scope() as other:
            record_runtime_stop("no_tools")
            assert other.snapshot() == ["no_tools"]
            assert outer.snapshot() == ["deadline"]
    release.set()
    await task
    assert outer.snapshot() == ["deadline"]
    outer.close()
    assert outer.snapshot() == ["deadline"]


@pytest.mark.asyncio
async def test_background_task_is_detached_before_it_can_finish():
    async def background():
        record_runtime_stop("deadline")

    with turn_stops_scope() as collector:
        with detached_turn_stops():
            task = asyncio.create_task(background())
        await task
        assert collector.snapshot() == []
        record_runtime_stop("thinking_exhausted")
        assert collector.snapshot() == ["thinking_exhausted"]
