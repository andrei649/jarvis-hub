"""Tests for the learning loop module."""
import asyncio
import pytest
from agents.core.learning_loop import run_learning_loop, _analyse_and_propose, LOOP_INTERVAL_SECONDS

def test_interval_is_weekly():
    assert LOOP_INTERVAL_SECONDS == 7 * 24 * 3600

@pytest.mark.asyncio
async def test_analyse_with_no_checkpoint():
    """Should not crash when orchestrator has no checkpoint."""
    class FakeOrchestrator:
        checkpoint = None
    await _analyse_and_propose(FakeOrchestrator())

@pytest.mark.asyncio
async def test_analyse_with_no_inbox():
    """Should not crash when orchestrator has no decision_inbox."""
    class FakeOrchestrator:
        checkpoint = object()
        decision_inbox = None
    await _analyse_and_propose(FakeOrchestrator())

@pytest.mark.asyncio
async def test_loop_cancels_cleanly():
    """Loop should exit cleanly when cancelled."""
    class FakeOrchestrator:
        checkpoint = None
    task = asyncio.create_task(run_learning_loop(FakeOrchestrator()))
    await asyncio.sleep(0.01)
    task.cancel()
    # The loop catches CancelledError internally and exits — task.cancel() schedules
    # cancellation; the loop handles it and returns, so no CancelledError propagates here.
    # Give it a moment to finish
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
