import asyncio
from types import SimpleNamespace

import pytest

from agents.core.autonomy.jobs import JobRunner, JobStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from agents.core import estop

    monkeypatch.setattr(estop, "check_paused", lambda *a: False)
    store = JobStore(tmp_path / "jobs.db")
    runner = JobRunner(store, orch=SimpleNamespace(), scheduler=lambda: None)
    job = store.create(
        name="test",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "hi"},
        options={"deliver": []},
    )
    yield store, runner, job
    store.close()


@pytest.mark.asyncio
async def test_acceptance_is_durable_coalesced_and_does_not_execute(setup):
    store, runner, job = setup
    a = runner.request_run(job.id)
    assert runner.request_run(job.id)["id"] == a["id"]
    assert a["status"] == "queued" and store.runs(job.id) == []
    other = JobStore(store._path)
    try:
        assert other.dispatch.get(a["id"])["status"] == "queued"
        await runner.drain_manual()
        done = other.dispatch.get(a["id"])
        assert done["status"] == "completed" and done["run"]["status"] == "ok"
        assert done["run"]["id"] != a["id"]
    finally:
        other.close()


@pytest.mark.asyncio
async def test_paused_manual_preserves_force_semantics(setup):
    store, runner, job = setup
    store.pause(job.id, "owner")
    receipt = runner.request_run(job.id)
    await runner.drain_manual()
    assert store.dispatch.get(receipt["id"])["run"]["status"] == "ok"
    assert store.get(job.id).paused_reason == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "edit"])
async def test_unclaimed_deleted_or_changed_job_never_executes(setup, change):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    if change == "delete":
        store.delete(job.id)
    else:
        store.edit(job.id, action={"type": "remind", "message": "new"})
    await runner.drain_manual()
    assert store.dispatch.get(receipt["id"])["status"] == "cancelled"
    assert store.runs(job.id) == []


@pytest.mark.asyncio
async def test_cancelled_claim_becomes_unknown_without_replay(setup):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    ready = asyncio.Event()

    async def execute(job):
        ready.set()
        await asyncio.Event().wait()

    runner._execute = execute
    task = asyncio.create_task(runner.drain_manual())
    await asyncio.wait_for(ready.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await runner.drain_manual()
    assert store.dispatch.get(receipt["id"])["status"] == "unknown"
    assert store.get(job.id).attempts == 1


@pytest.mark.asyncio
async def test_shared_gate_prevents_cron_manual_overlap(setup):
    store, runner, job = setup
    ready, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(job):
        calls.append(job.id)
        ready.set()
        await release.wait()
        return "done", None

    runner._execute = execute
    receipt = runner.request_run(job.id)
    task = asyncio.create_task(runner.drain_manual())
    await asyncio.wait_for(ready.wait(), 1)
    cron = asyncio.create_task(runner.fire(job.id))
    await asyncio.sleep(0.01)
    assert not cron.done() and len(calls) == 1
    assert runner.request_run(job.id)["id"] == receipt["id"]
    release.set()
    await task
    assert (await cron).status == "ok" and len(calls) == 2
    assert store.dispatch.get(receipt["id"])["status"] == "completed"


def test_cross_store_coalescing_and_gate(setup):
    store, runner, job = setup
    other = JobStore(store._path)
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda s: s.dispatch.enqueue(job.id)["id"], [store, other]))
        assert len(set(ids)) == 1
        with store.dispatch.gate(job.id) as first, other.dispatch.gate(job.id) as second:
            assert first and not second
    finally:
        other.close()


@pytest.mark.asyncio
async def test_restart_unclaimed_survives_but_claimed_is_unknown(setup):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    assert store.dispatch.claim(receipt["id"])
    other = JobStore(store._path)
    try:
        recovered = JobRunner(other, orch=SimpleNamespace(), scheduler=lambda: None)
        await recovered.drain_manual()
        assert other.dispatch.get(receipt["id"])["status"] == "unknown"
        assert other.get(job.id).attempts == 0
        next_request = recovered.request_run(job.id)
        await recovered.drain_manual()
        assert other.dispatch.get(next_request["id"])["status"] == "completed"
    finally:
        other.close()


@pytest.mark.asyncio
async def test_pending_receipt_follows_exact_run_and_retains_evidence(setup):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    run = store.record_run(
        job.id, started_at="t", finished_at="t", status="pending", summary="approval"
    )
    store.dispatch.state(receipt["id"], "waiting", run=run.as_dict())
    for _ in range(205):
        store.record_run(job.id, started_at="t", finished_at="t", status="skipped")
    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE job_runs SET status='ok',summary='finished' WHERE id=?", (run.id,)
        )
    await runner.drain_manual()
    done = store.dispatch.get(receipt["id"])
    assert done["status"] == "completed" and done["run"]["summary"] == "finished"


@pytest.mark.asyncio
async def test_terminal_retention_bounded_and_active_preserved(setup):
    store, runner, job = setup
    other = store.create(
        name="queued", schedule_text="0 9 * * *", action={"type": "remind", "message": "x"}
    )
    pending = runner.request_run(other.id)
    for _ in range(205):
        receipt = runner.request_run(job.id)
        store.dispatch.state(receipt["id"], "unknown")
    with store._lock:
        assert store._conn.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0] == 201
    assert store.dispatch.get(pending["id"])["status"] == "queued"


@pytest.mark.asyncio
async def test_estop_and_repeat_still_apply_to_manual(setup, monkeypatch):
    from agents.core import estop

    store, runner, job = setup
    store.edit(job.id, options={"repeat": 1, "deliver": []})
    monkeypatch.setattr(estop, "check_paused", lambda *a: True)
    receipt = runner.request_run(job.id)
    await runner.drain_manual()
    assert store.dispatch.get(receipt["id"])["run"]["status"] == "skipped"
    assert store.get(job.id).attempts == 0
    monkeypatch.setattr(estop, "check_paused", lambda *a: False)
    for expected in ["ok", "skipped"]:
        receipt = runner.request_run(job.id)
        await runner.drain_manual()
        assert store.dispatch.get(receipt["id"])["run"]["status"] == expected


def test_gate_does_not_swallow_execution_vault_errors(setup):
    from agents.core.vault import VaultError

    store, _, job = setup
    with pytest.raises(VaultError, match="timed out"), store.dispatch.gate(job.id) as acquired:
        assert acquired
        raise VaultError("timed out waiting for vault lock")


@pytest.mark.asyncio
async def test_cancelled_receipt_retention_is_bounded(setup):
    store, runner, job = setup
    for i in range(205):
        runner.request_run(job.id)
        store.edit(job.id, action={"type": "remind", "message": str(i)})
        await runner.drain_manual()
    with store._lock:
        assert store._conn.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0] == 200


@pytest.mark.asyncio
async def test_finished_pending_run_allows_new_manual_request(setup):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    run = store.record_run(job.id, started_at="t", finished_at="t", status="pending")
    store.dispatch.state(receipt["id"], "waiting", run=run.as_dict())
    with store._lock, store._conn:
        store._conn.execute("UPDATE job_runs SET status='ok' WHERE id=?", (run.id,))
    new = runner.request_run(job.id)
    assert new["id"] != receipt["id"] and new["status"] == "queued"


def test_portable_gate_windows_branch_uses_existing_lock_contract(setup, monkeypatch):
    import os
    import sys

    from agents.core import vault

    store, _, job = setup
    calls = []
    fake_os = SimpleNamespace(
        **{key: getattr(os, key) for key in dir(os) if not key.startswith("__")}
    )
    fake_os.name = "nt"
    monkeypatch.setattr(vault, "os", fake_os)
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(
            LK_NBLCK=1, LK_UNLCK=2, locking=lambda fd, kind, count: calls.append((kind, count))
        ),
    )
    with store.dispatch.gate(job.id) as acquired:
        assert acquired
    assert calls == [(1, 1), (2, 1)]


@pytest.mark.asyncio
async def test_two_runners_serialize_same_job_without_losing_cron(setup):
    store, runner, job = setup
    other = JobStore(store._path)
    second = JobRunner(other, orch=SimpleNamespace(), scheduler=lambda: None)
    ready, release = asyncio.Event(), asyncio.Event()

    async def execute(job):
        ready.set()
        await release.wait()
        return "done", None

    runner._execute = execute
    runner.request_run(job.id)
    task = asyncio.create_task(runner.drain_manual())
    await asyncio.wait_for(ready.wait(), 1)
    cron = asyncio.create_task(second.fire(job.id))
    await asyncio.sleep(0.01)
    assert not cron.done()
    release.set()
    try:
        await task
        assert (await cron).status == "ok"
        assert store.get(job.id).attempts == 2
    finally:
        other.close()


@pytest.mark.asyncio
async def test_script_approval_reservation_outlives_manual_dispatch(tmp_path, monkeypatch):
    from agents.core import estop
    from tests.test_job_scripts import complete, make_runtime

    monkeypatch.setattr(estop, "check_paused", lambda *a: False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "watch.py").write_text("print('ready')")
    store, runner, job, tasks, outputs, _ = make_runtime(tmp_path, scripts)
    other = JobStore(store._path)
    # Both runners use the same explicit non-quiet test clock.
    second = JobRunner(other, orch=runner._orch, scheduler=lambda: None, quiet=lambda: False)
    second.bind_scripts(
        submit=runner._script_runtime.submit,
        get=tasks.get,
        find=lambda origin: [t for t in tasks.values() if t.origin == origin],
    )
    try:
        receipt = runner.request_run(job.id)
        await runner.drain_manual()
        assert store.dispatch.get(receipt["id"])["status"] == "waiting"
        run = await second.fire(job.id)
        assert run.status == "pending" and len(tasks) == 1
        assert other.get(job.id).attempts == 1
        assert second.request_run(job.id)["id"] == receipt["id"]
        complete(tasks[1])
        await second.reconcile_scripts()
        await runner.drain_manual()
        assert store.dispatch.get(receipt["id"])["run"]["status"] == "ok"
        assert outputs == ["ready\n"]
    finally:
        other.close()
        store.close()


def test_outstanding_capacity_is_explicit(setup):
    store, runner, job = setup
    with store._lock, store._conn:
        store._conn.executemany(
            "INSERT INTO job_requests(id,job_id,status,created_at,fingerprint) VALUES(?,?,'queued','t','x')",
            [(str(i), str(i)) for i in range(256)],
        )
    with pytest.raises(ValueError, match="capacity"):
        runner.request_run(job.id)
    assert store.runs(job.id) == []


@pytest.mark.asyncio
async def test_delete_after_claim_records_unknown_and_continues_other_requests(setup):
    store, runner, job = setup
    other = store.create(
        name="other",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"deliver": []},
    )
    receipt = runner.request_run(job.id)
    later = runner.request_run(other.id)
    original = runner._execute

    async def execute(active):
        if active.id == job.id:
            store.delete(job.id)
            return "effect may have happened", None
        return await original(active)

    runner._execute = execute
    await runner.drain_manual()
    assert store.dispatch.get(receipt["id"])["status"] == "unknown"
    assert store.dispatch.get(later["id"])["status"] == "completed"


@pytest.mark.asyncio
async def test_unrelated_stripe_contention_defers_instead_of_dropping_cron(setup, monkeypatch):
    store, runner, job = setup
    other = store.create(
        name="other",
        schedule_text="0 9 * * *",
        action={"type": "remind", "message": "x"},
        options={"deliver": []},
    )
    original_gate = store.dispatch.gate
    monkeypatch.setattr(store.dispatch, "gate", lambda _: original_gate("same-test-stripe"))
    with original_gate("same-test-stripe") as acquired:
        assert acquired
        cron = asyncio.create_task(runner.fire(other.id))
        await asyncio.sleep(0.01)
        assert not cron.done()
    assert (await asyncio.wait_for(cron, 1)).status == "ok"
    assert store.get(job.id).attempts == 0


@pytest.mark.asyncio
async def test_edit_between_claim_and_fire_cannot_replace_accepted_action(setup, monkeypatch):
    store, runner, job = setup
    receipt = runner.request_run(job.id)
    claim = store.dispatch.claim

    def changed(request_id):
        accepted = claim(request_id)
        store.edit(job.id, action={"type": "remind", "message": "replacement"})
        return accepted

    monkeypatch.setattr(store.dispatch, "claim", changed)
    await runner.drain_manual()
    result = store.dispatch.get(receipt["id"])
    assert result["run"]["status"] == "skipped"
    assert store.get(job.id).attempts == 0
    assert "replacement" not in result["run"]["summary"]


@pytest.mark.asyncio
async def test_pruned_waiting_snapshot_does_not_abort_later_queued_work(setup, monkeypatch):
    store, runner, job = setup
    old = runner.request_run(job.id)
    run = store.record_run(job.id, started_at="t", finished_at="t", status="pending")
    store.dispatch.state(old["id"], "waiting", run=run.as_dict())
    later = store.create(name="later", schedule_text="0 9 * * *",
                         action={"type": "remind", "message": "next"}, options={"deliver": []})
    runner.request_run(later.id)
    snapshot = store.dispatch.outstanding()
    other = JobStore(store._path)
    try:
        other.dispatch.state(old["id"], "completed", run=run.as_dict())
        for _ in range(200):
            item = other.dispatch.enqueue(job.id)
            other.dispatch.state(item["id"], "cancelled", reason="retention fixture")
        assert other.dispatch.get(old["id"]) is None
        monkeypatch.setattr(store.dispatch, "outstanding", lambda: snapshot)
        await runner.drain_manual()
        # Its older completed receipt may also age out; execution evidence remains.
        assert store.runs(later.id)[0].status == "ok"
        assert store.get(job.id).attempts == 0
        assert store.get(later.id).attempts == 1
    finally:
        other.close()
