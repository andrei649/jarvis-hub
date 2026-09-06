"""H20.6 — Dynamic sub-agent delegation (isolated, capped). All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import asyncio
import pytest

from agents.core.subagents import SubAgentManager, NullRunner


@pytest.mark.asyncio
async def test_spawn_runs_in_isolated_session():
    m = SubAgentManager()
    out = await m.spawn("do research", agent="vision")
    assert out["ok"] is True and out["status"] == "done"
    assert out["session_id"].startswith("session::sub-")
    assert "vision" in out["result"]["output"]


@pytest.mark.asyncio
async def test_spawns_get_distinct_sessions():
    m = SubAgentManager()
    a = await m.spawn("t1")
    b = await m.spawn("t2")
    assert a["session_id"] != b["session_id"]
    assert m.stats()["total"] == 2


@pytest.mark.asyncio
async def test_concurrency_cap_rejects_excess():
    # A runner that blocks until released, so spawns stay "active".
    release = asyncio.Event()

    class _Blocking:
        async def __call__(self, task, session_id, agent):
            await release.wait()
            return {"output": "ok", "session_id": session_id}

    m = SubAgentManager(runner=_Blocking(), max_concurrent=2)
    t1 = asyncio.create_task(m.spawn("a"))
    t2 = asyncio.create_task(m.spawn("b"))
    await asyncio.sleep(0.01)                 # let both occupy the cap
    rejected = await m.spawn("c")             # 3rd → over cap
    assert rejected["ok"] is False and rejected["reason"] == "concurrency_cap"
    release.set()
    await asyncio.gather(t1, t2)
    assert m.stats()["active"] == 0           # all drained


@pytest.mark.asyncio
async def test_runner_failure_is_captured():
    class _Boom:
        async def __call__(self, task, session_id, agent):
            raise RuntimeError("nope")

    m = SubAgentManager(runner=_Boom())
    out = await m.spawn("x")
    assert out["ok"] is False and out["status"] == "failed"
    assert m.stats()["active"] == 0           # released even on failure


@pytest.mark.asyncio
async def test_null_runner_echoes():
    out = await NullRunner()("hello", "s1", "sub")
    assert "hello" in out["output"] and out["session_id"] == "s1"


@pytest.mark.asyncio
async def test_spawn_budget_exhausted():
    """co-subagent-steer: the total-spawn budget (autonomy.max_subagent_spawns_per_boot
    in prod) refuses the N+1th spawn with a named reason — and never runs it."""
    from agents.core.iteration_budget import IterationBudget

    ran = []

    async def runner(task, session_id, agent):
        ran.append(task)
        return {"output": task}

    m = SubAgentManager(runner=runner, budget=IterationBudget(1), cost_probe=lambda: {},
                        persist=False)
    assert (await m.spawn("first"))["ok"] is True
    out = await m.spawn("second")
    assert out["ok"] is False and out["reason"] == "spawn_budget_exhausted"
    assert out["used"] == 1 and out["max_total"] == 1
    assert ran == ["first"]                       # the refused spawn never ran
    assert m.stats()["budget"]["remaining"] == 0
