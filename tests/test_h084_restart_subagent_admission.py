"""A restart drain closes new subagent admission without stopping admitted work."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from contextlib import contextmanager

import pytest

from agents.core.autonomy.queue import TaskQueue
from agents.core.iteration_budget import IterationBudget
from agents.core.subagents import SubAgentManager


class _Lease:
    def __init__(self, gate):
        self.gate = gate
        self.live = True
        self.release_calls = 0

    @contextmanager
    def bind(self):
        assert self.live
        self.gate.bound_tasks.add(asyncio.current_task())
        try:
            yield
        finally:
            self.gate.bound_tasks.discard(asyncio.current_task())

    def release(self):
        self.release_calls += 1
        if self.live:
            self.live = False
            self.gate.active -= 1


class _Gate:
    def __init__(self):
        self.closed = False
        self.active = 0
        self.bound_tasks = set()
        self.kinds = []
        self.leases = []

    def acquire(self, kind, *, allow_reentrant=False):
        self.kinds.append((kind, allow_reentrant))
        if self.closed:
            return None
        self.active += 1
        lease = _Lease(self)
        self.leases.append(lease)
        return lease


def _manager(gate, tmp_path, **kwargs):
    return SubAgentManager(admission_runtime=gate, state_dir=tmp_path,
                           persist=False, cost_probe=lambda: {}, **kwargs)


@pytest.mark.asyncio
async def test_closed_gate_refuses_before_spawn_budget_or_record(tmp_path):
    gate = _Gate()
    gate.closed = True
    budget = IterationBudget(1)
    manager = _manager(gate, tmp_path, budget=budget)

    answer = await manager.spawn("new child")
    assert answer == {"ok": False, "reason": "restart_draining"}
    assert gate.kinds == [("subagent", False)]
    assert gate.active == 0
    assert budget.used == 0
    assert manager.stats()["active"] == 0
    assert manager.list() == []


@pytest.mark.asyncio
async def test_gate_rechecked_after_awaited_halt_read(tmp_path):
    gate = _Gate()
    budget = IterationBudget(1)
    manager = _manager(gate, tmp_path, budget=budget)
    reading = threading.Event()
    resume = threading.Event()

    def delayed_halt():
        reading.set()
        assert resume.wait(2)
        return {"halted": None, "paused": False, "pause": None}

    manager._halt_state = delayed_halt
    pending = asyncio.create_task(manager.spawn("new child"))
    try:
        assert await asyncio.to_thread(reading.wait, 2)
        gate.closed = True
    finally:
        resume.set()
    answer = await pending
    assert answer["reason"] == "restart_draining"
    assert budget.used == 0 and manager.stats()["active"] == 0
    assert manager.list() == []


@pytest.mark.asyncio
async def test_admitted_child_stays_live_and_cannot_spawn_new_child_during_drain(tmp_path):
    gate = _Gate()
    entered = asyncio.Event()
    proceed = asyncio.Event()
    manager = None

    async def runner(_task, _session_id, _agent):
        assert asyncio.current_task() in gate.bound_tasks
        entered.set()
        await proceed.wait()
        refused = await manager.spawn("nested child")
        assert refused["reason"] == "restart_draining"
        return {"output": "done"}

    manager = _manager(gate, tmp_path, runner=runner)
    pending = asyncio.create_task(manager.spawn("parent child"))
    await entered.wait()
    gate.closed = True
    assert gate.active == 1
    proceed.set()
    assert (await pending)["ok"] is True
    assert gate.active == 0
    assert gate.kinds == [("subagent", False), ("subagent", False)]


@pytest.mark.asyncio
async def test_lease_outlives_child_until_durable_settlement_finishes(tmp_path):
    gate = _Gate()
    finishing = threading.Event()
    release = threading.Event()

    class Store:
        def delegation_start(self, _row):
            pass

        def delegation_finish(self, *_args, **_kwargs):
            finishing.set()
            assert release.wait(2)

    async def runner(_task, _session_id, _agent):
        return {"output": "done"}

    manager = _manager(gate, tmp_path, runner=runner, store=Store())
    pending = asyncio.create_task(manager.spawn("one"))
    try:
        assert await asyncio.to_thread(finishing.wait, 2)
        assert manager.stats()["active"] == 0
        assert gate.active == 1
    finally:
        release.set()
    assert (await pending)["ok"] is True
    assert gate.active == 0


@pytest.mark.asyncio
async def test_lease_outlives_settlement_until_tool_thread_finishes(tmp_path):
    gate = _Gate()
    thread = concurrent.futures.Future()
    manager = None

    async def runner(_task, _session_id, _agent):
        spawn_id = next(iter(manager._spawns))
        manager._threads[spawn_id].add(thread)
        return {"output": "done"}

    manager = _manager(gate, tmp_path, runner=runner)
    assert (await manager.spawn("one"))["ok"] is True
    assert manager.stats()["active"] == 1
    assert gate.active == 1
    thread.set_result(None)
    for _ in range(20):
        if gate.active == 0:
            break
        await asyncio.sleep(0)
    assert gate.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_at", ("durable", "worktree", "worktree_error"))
async def test_stop_before_child_task_closes_only_selected_child(tmp_path, pause_at):
    gate = _Gate()
    entering = threading.Event()
    release = threading.Event()
    starts = []
    finishes = []
    work = []
    sibling_entered = asyncio.Event()
    sibling_release = asyncio.Event()

    class Store(TaskQueue):
        def delegation_start(self, row):
            if pause_at == "durable" and row["goal"] == "stopped child":
                entering.set()
                assert release.wait(2)
            starts.append(row["delegation_id"])
            return super().delegation_start(row)

        def delegation_finish(self, delegation_id, *args, **kwargs):
            finishes.append(delegation_id)
            return super().delegation_finish(delegation_id, *args, **kwargs)

    async def runner(task, _session_id, _agent):
        work.append(task)
        if task == "sibling child":
            sibling_entered.set()
            await sibling_release.wait()
        return {"output": task}

    def worktree_provider(spawn_id):
        if pause_at != "durable" and manager._spawns[spawn_id]["task"] == "stopped child":
            entering.set()
            assert release.wait(2)
            if pause_at == "worktree_error":
                raise RuntimeError("allocation failed after stop")
        return None

    store = Store(db_path=str(tmp_path / "autonomy.db")).initialize()
    manager = _manager(gate, tmp_path, runner=runner, store=store,
                       worktree_provider=worktree_provider if pause_at != "durable" else None)
    selected = asyncio.create_task(manager.spawn("stopped child"))
    sibling_task = None
    try:
        assert await asyncio.to_thread(entering.wait, 2)
        selected_id = next(r["id"] for r in manager._spawns.values()
                           if r["task"] == "stopped child")
        assert selected_id not in manager._tasks
        sibling_task = asyncio.create_task(manager.spawn("sibling child"))
        await asyncio.wait_for(sibling_entered.wait(), 2)
        assert not sibling_task.done()
        assert manager.stop(selected_id, reason="owner_stop")["status"] == "stopping"
        assert not sibling_task.done()
        release.set()
        sibling_release.set()
        stopped, sibling = await asyncio.gather(selected, sibling_task)
        assert sibling["status"] == "done" and sibling["result"]["output"] == "sibling child"
        assert stopped["status"] == "stopped"
        assert manager._spawns[selected_id]["stop_reason"] == "owner_stop"
        assert stopped["result"] == {"error": "stopped", "reason": "owner_stop"}
        assert work == ["sibling child"]
        assert store.delegation_get(stopped["delegation_id"])["status"] == "stopped"
        assert store.delegation_get(sibling["delegation_id"])["result"] == sibling["result"]
        assert starts.count(stopped["delegation_id"]) == finishes.count(stopped["delegation_id"]) == 1
        assert gate.active == 0 and manager.stats()["active"] == 0
        assert len(gate.leases) == 2 and all(lease.release_calls == 1 for lease in gate.leases)
    finally:
        release.set()
        sibling_release.set()
        await asyncio.gather(selected, *([sibling_task] if sibling_task else []),
                             return_exceptions=True)
        store.close()


@pytest.mark.asyncio
async def test_cancelled_parent_keeps_lease_until_blocked_settlement_finishes(tmp_path):
    gate = _Gate()
    finishing = threading.Event()
    release = threading.Event()

    class Store:
        def delegation_start(self, _row):
            pass

        def delegation_finish(self, *_args, **_kwargs):
            finishing.set()
            assert release.wait(2)

    async def runner(_task, _session_id, _agent):
        return {"output": "done"}

    manager = _manager(gate, tmp_path, runner=runner, store=Store())
    pending = asyncio.create_task(manager.spawn("one"))
    try:
        assert await asyncio.to_thread(finishing.wait, 2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert gate.active == 1
    finally:
        release.set()
    for _ in range(20):
        if gate.active == 0:
            break
        await asyncio.sleep(0.01)
    assert gate.active == 0
