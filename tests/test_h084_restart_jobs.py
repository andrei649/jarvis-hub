"""Restart admission never consumes an owner job's pending work."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from agents.core.autonomy.jobs import JobRunner, JobStore
from agents.core.restart_runtime import runtime_for


@pytest.fixture()
def rig(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    orch = SimpleNamespace()
    runner = JobRunner(store, orch=orch, scheduler=lambda: None, quiet=lambda: False)
    job = runner.create(name="notice", schedule_text="0 9 * * *",
                        action={"type": "remind", "message": "notice"},
                        options={"repeat": 1, "deliver": []})
    yield SimpleNamespace(store=store, orch=orch, runner=runner, job=job,
                          runtime=runtime_for(orch))
    store.close()


@pytest.mark.asyncio
async def test_running_job_counts_until_its_execution_settles(rig, monkeypatch):
    entered, finish = asyncio.Event(), asyncio.Event()

    async def slow(_job, _publish):
        entered.set()
        await finish.wait()
        return "complete", None

    monkeypatch.setattr(rig.runner, "_bounded_execute", slow)
    running = asyncio.create_task(rig.runner.fire(rig.job.id))
    await asyncio.wait_for(entered.wait(), 2)
    token = rig.runtime.close_admission()
    assert rig.runtime.snapshot()["by_kind"]["job"] == 1
    second = await rig.runner.fire(rig.job.id)
    assert second.status == "skipped"
    assert rig.store.get(rig.job.id).attempts == 1
    waiter = asyncio.create_task(rig.runtime.wait_idle(token, 1))
    assert not waiter.done()
    finish.set()
    assert (await running).status == "ok"
    assert await waiter is True
    assert rig.store.get(rig.job.id).paused_reason is None
    assert rig.runtime.reopen(token)


@pytest.mark.asyncio
async def test_manual_queued_request_is_not_claimed_while_closed(rig, monkeypatch):
    async def complete(_job, _publish):
        return "complete", None

    monkeypatch.setattr(rig.runner, "_bounded_execute", complete)
    request = rig.runner.request_run(rig.job.id)
    token = rig.runtime.close_admission()
    await rig.runner.drain_manual()
    assert rig.store.dispatch.get(request["id"])["status"] == "queued"
    assert rig.store.get(rig.job.id).attempts == 0
    assert rig.runtime.reopen(token)
    await rig.runner.drain_manual()
    assert rig.store.dispatch.get(request["id"])["status"] == "completed"
    assert rig.store.get(rig.job.id).attempts == 1


@pytest.mark.asyncio
async def test_manual_claim_rechecks_after_cross_process_gate_wait(rig, monkeypatch):
    request = rig.runner.request_run(rig.job.id)

    @contextmanager
    def gate(_job_id):
        token = rig.runtime.close_admission()
        assert token is not None
        yield True

    monkeypatch.setattr(rig.store.dispatch, "gate", gate)
    await rig.runner.drain_manual()
    assert rig.store.dispatch.get(request["id"])["status"] == "queued"
    assert rig.store.get(rig.job.id).attempts == 0


@pytest.mark.asyncio
async def test_fallback_tick_does_not_consume_due_slot_when_closed(rig):
    when = datetime(2026, 11, 13, 9, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
    token = rig.runtime.close_admission()
    assert await rig.runner.tick(now=when) == []
    with rig.store._lock:
        assert rig.store._conn.execute("SELECT COUNT(*) FROM job_ticks").fetchone()[0] == 0
    assert rig.store.get(rig.job.id).attempts == 0
    assert rig.runtime.reopen(token)


@pytest.mark.asyncio
async def test_new_script_reconcile_and_held_flush_wait_for_open_gate(rig, monkeypatch):
    calls = []

    async def reconcile():
        calls.append("script")
        return 1

    async def flush():
        calls.append("held")
        return 0

    monkeypatch.setattr(rig.runner._script_runtime, "reconcile", reconcile)
    monkeypatch.setattr(rig.runner.media, "flush_held", flush)
    token = rig.runtime.close_admission()
    assert await rig.runner.reconcile_scripts() == 0
    assert await rig.runner.flush_held() == 0
    assert calls == []
    assert rig.runtime.reopen(token)
    assert await rig.runner.reconcile_scripts() == 1
    await rig.runner.flush_held()
    assert calls == ["script", "held"]


@pytest.mark.asyncio
async def test_cancelled_or_failed_job_releases_its_admission(rig, monkeypatch):
    entered = asyncio.Event()

    async def suspended(_job, _publish):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.runner, "_bounded_execute", suspended)
    running = asyncio.create_task(rig.runner.fire(rig.job.id))
    await asyncio.wait_for(entered.wait(), 2)
    assert rig.runtime.snapshot()["by_kind"]["job"] == 1
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert rig.runtime.snapshot()["active"] == 0

    async def failed(_job, _publish):
        raise ValueError("fixture failure")

    monkeypatch.setattr(rig.runner, "_bounded_execute", failed)
    another = rig.runner.create(name="other", schedule_text="0 10 * * *",
                                action={"type": "remind", "message": "other"},
                                options={"deliver": []})
    assert (await rig.runner.fire(another.id)).status == "failed"
    assert rig.runtime.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_cancelled_manual_dispatch_releases_admission(rig, monkeypatch):
    entered = asyncio.Event()

    async def suspended(_job, _publish):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.runner, "_bounded_execute", suspended)
    request = rig.runner.request_run(rig.job.id)
    running = asyncio.create_task(rig.runner.drain_manual())
    await asyncio.wait_for(entered.wait(), 2)
    assert rig.runtime.snapshot()["by_kind"]["manual"] == 1
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert rig.store.dispatch.get(request["id"])["status"] == "unknown"
    assert rig.runtime.snapshot()["active"] == 0
