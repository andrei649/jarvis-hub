"""Workflow batch concurrency is bounded (BACKLOG H22.6).

A parallel batch must interleave at most _MAX_PARALLEL_STEPS at a time, so a wide
pipeline can't launch dozens of simultaneous LLM calls and starve the
interactive path. Offline: the orchestrator is bypassed with a counting fake.
"""

import asyncio
import sys
from collections import deque
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.workflows.engine import WorkflowEngine, _MAX_PARALLEL_STEPS
from agents.core.workflows.pipeline import Pipeline, WorkflowStep


def _engine_with_counting_exec(state):
    """A WorkflowEngine whose step execution tracks peak concurrency."""
    eng = WorkflowEngine.__new__(WorkflowEngine)  # skip orchestrator init
    eng._orch = None
    eng.recent_runs = deque(maxlen=50)

    async def fake_exec(step, ctx, step_map):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0.01)
        state["cur"] -= 1
        return "ok"

    eng._traced_execute = fake_exec
    return eng


def _wide_pipeline(n):
    steps = [
        WorkflowStep(id=f"s{i}", agent_id="jarvis", prompt_template="{_input}")
        for i in range(n)
    ]  # no depends_on → all in one parallel batch
    return Pipeline(id="p", name="p", description="", steps=steps)


async def test_batch_concurrency_is_capped():
    state = {"cur": 0, "max": 0}
    eng = _engine_with_counting_exec(state)
    n = _MAX_PARALLEL_STEPS * 3
    result = await eng.run(_wide_pipeline(n), "hi")

    assert state["max"] <= _MAX_PARALLEL_STEPS      # never exceeds the cap
    assert state["max"] > 1                          # but genuinely parallel
    assert result["_ok"] is True
    assert all(result[f"s{i}"] == "ok" for i in range(n))


async def test_small_batch_runs_fully_parallel():
    state = {"cur": 0, "max": 0}
    eng = _engine_with_counting_exec(state)
    n = _MAX_PARALLEL_STEPS - 1                       # under the cap
    await eng.run(_wide_pipeline(n), "hi")

    assert state["max"] == n                          # all ran at once
