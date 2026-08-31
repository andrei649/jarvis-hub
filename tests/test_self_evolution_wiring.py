"""DRA-41 — self_evolution.py gets a production caller.

`agents/core/self_evolution.py` (H20.4) shipped a TrajectoryStore + a gated
`propose_optimization`, but nothing in the running hub ever built a store, ever
called it, and no scheduler job ever fired it — so "self-evolution" existed only
in the unit tests. These tests pin the missing seam: trajectories captured from
the data the hub ALREADY records (the learning loop), a proposal that lands in
the real decision inbox, idempotency, and the unattended scheduler job that runs
it with no owner action.

Honesty boundary asserted below: approving the task does NOT hot-swap a live
prompt (agents load SOUL from disk), so the payload must carry the real apply
step. Nothing here registers an executor that pretends otherwise.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.queue import TaskQueue
from agents.core.learning.evolution import (
    PROMPT_OPTIMIZATION_KIND,
    capture_trajectories,
    propose_prompt_optimizations,
)
from agents.core.learning.loop import LearningLoop


class _Agent:
    def __init__(self, content: str):
        self.soul = {"content": content}


def _loop(tmp_path, ok=3, fail=0):
    loop = LearningLoop(db_path=str(tmp_path / "learn/"))
    for i in range(ok):
        loop.record("ana", f"task {i}", f"answer {i}", success=True, latency=1.0)
    for i in range(fail):
        loop.record("ana", f"bad {i}", "boom", success=False, latency=9.0)
    return loop


def _queue(tmp_path):
    q = TaskQueue(db_path=str(tmp_path / "q.db"))
    q.initialize()
    return q


def test_capture_trajectories_scores_only_successes(tmp_path):
    loop = _loop(tmp_path, ok=3, fail=1)
    store = capture_trajectories(loop, "ana")
    assert store.count("ana") == 3          # the failed turn is not a demo
    assert all(t["score"] > 0 for t in store.best("ana", k=10))


@pytest.mark.asyncio
async def test_prompt_optimization_reaches_decision_inbox(tmp_path):
    loop = _loop(tmp_path, ok=3)
    q = _queue(tmp_path)
    out = await propose_prompt_optimizations(loop, {"ana": _Agent("base prompt")}, q)
    assert len(out) == 1
    tasks = [t for t in q.list(status="proposed") if t.kind == PROMPT_OPTIMIZATION_KIND]
    assert len(tasks) == 1
    task = tasks[0]
    assert task.autonomy_level == "ask" and task.origin == "generated"
    assert task.payload["agent"] == "ana"
    assert "answer 0" in task.payload["proposed_prompt"]
    assert task.payload["requires_approval"] is True
    # the apply step is named honestly — approval alone changes no live prompt
    assert "/api/admin/prompts/ana/commit" in task.payload["expected"]
    # verbatim conversation text must not raise an interrupt
    assert task.attention_mode == "digest"
    # and it is really in the inbox the rest of the product reads
    assert any(t.id == task.id for t in q.pending_decisions())


@pytest.mark.asyncio
async def test_prompt_optimization_is_idempotent(tmp_path):
    loop = _loop(tmp_path, ok=3)
    q = _queue(tmp_path)
    agents = {"ana": _Agent("base prompt")}
    assert len(await propose_prompt_optimizations(loop, agents, q)) == 1
    assert await propose_prompt_optimizations(loop, agents, q) == []
    assert len([t for t in q.list(status="proposed") if t.kind == PROMPT_OPTIMIZATION_KIND]) == 1


@pytest.mark.asyncio
async def test_skips_agents_without_a_soul_or_enough_trajectories(tmp_path):
    q = _queue(tmp_path)
    thin = _loop(tmp_path, ok=1)
    assert await propose_prompt_optimizations(thin, {"ana": _Agent("base prompt")}, q) == []
    assert await propose_prompt_optimizations(_loop(tmp_path, ok=3), {"ana": _Agent("")}, q) == []
    assert await propose_prompt_optimizations(None, {}, None) == []


def test_orchestrator_and_scheduler_have_a_production_caller():
    """The assertion that actually red-proofs 'no production caller'."""
    from agents.core.orchestrator import Orchestrator
    from agents.core.scheduler_service import SchedulerService

    assert hasattr(Orchestrator, "_run_prompt_evolution")

    class _Sched:
        def __init__(self):
            self.ids = []

        def add_job(self, *a, **kw):
            self.ids.append(kw.get("id"))

    class _Orch:
        heartbeat_scheduler = type("H", (), {"scheduler": _Sched()})()
        config = {"autonomy": {"learning_loop_interval_hours": 168}}

        async def _run_learning_loop(self):
            return []

        async def _run_prompt_evolution(self):
            return []

    orch = _Orch()
    SchedulerService(orch).schedule_learning_loop()
    ids = orch.heartbeat_scheduler.scheduler.ids
    assert "learning-loop-promotions" in ids
    assert "learning-loop-prompt-evolution" in ids


def test_learning_evolve_endpoint():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as c:
            assert c.post("/api/learning/evolve").status_code == 401   # admin-guarded
            r = c.post("/api/learning/evolve", headers={"X-Admin-Token": "test-secret"})
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True and "count" in body and isinstance(body["proposed"], list)
    finally:
        web.ADMIN_TOKEN = old
