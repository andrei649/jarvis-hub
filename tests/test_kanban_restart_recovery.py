"""A native worker lost with its hub leaves an owner-reviewable board card."""

import sqlite3
from types import SimpleNamespace

import pytest

from agents.core.autonomy.queue import TaskStatus
from agents.core.kanban import dispatch_store as store
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.dispatcher import _file_identity
from agents.core.kanban.upstream import kanban_db as kb
from tests.test_hermes_kanban_dispatcher import OWNER, create, fixture_runtime, read


def test_file_identity_round_trips_wide_windows_file_ids():
    expected = _file_identity(SimpleNamespace(st_dev=7, st_ino=2**100 + 1))
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE receipt(dev INTEGER, ino INTEGER)")
        conn.execute("INSERT INTO receipt VALUES (?, ?)", expected)
        assert conn.execute("SELECT dev, ino FROM receipt").fetchone() == expected
    finally:
        conn.close()


async def claimed_attempt(tmp_path, monkeypatch, *, marked=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    task_id = create(controller)
    queued = (await controller.request(OWNER))["queued"][0]
    queue = orch.autonomy_queue
    queue.transition(queued["queue_id"], TaskStatus.APPROVED,
                     decided_by="owner", decision="approve")
    q = queue.claim_mediated(queued["queue_id"],
                             execution_id="00000000-0000-4000-8000-000000000001")
    with (kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        record = conn.execute("SELECT * FROM nerva_dispatches WHERE task_id=?",
                              (task_id,)).fetchone()
        with controller._attempt_lock(record["id"]) as identity:
            claimed = store.claim(conn, record, q, ttl_seconds=3600,
                                  recovery_identity=identity if marked else None)
    return controller, orch, task_id, q, claimed.current_run_id


@pytest.mark.asyncio
async def test_released_attempt_is_parked_once_without_replay(tmp_path, monkeypatch):
    controller, orch, task_id, q, run_id = await claimed_attempt(tmp_path, monkeypatch)
    with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
        first = await controller.recover_interrupted(task_id, expected_run_id=run_id)
    assert first["status"] == "recovered"
    assert read(controller, task_id).status == "blocked"
    assert orch.autonomy_queue.get(q.id).status == "failed"
    with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
        assert (await controller.recover_interrupted(task_id,
                                                     expected_run_id=run_id))["status"] == "already_recovered"
    assert (await controller.request(OWNER))["queued"] == []


@pytest.mark.asyncio
async def test_active_attempt_and_legacy_claim_are_not_recovered(tmp_path, monkeypatch):
    controller, orch, task_id, q, run_id = await claimed_attempt(tmp_path, monkeypatch)
    with (kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        sid = store.submissions(conn)[0]["id"]
    # A second live lock holder proves the process still owns the attempt.
    from pathlib import Path
    path = Path(controller.home) / "nerva-attempts" / (sid + ".lock")
    with path.open("r+b") as handle:
        from agents.core.kanban.upstream import kanban_db_connect as kbc
        assert kbc._try_lock_nb(handle)
        try:
            with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
                result = await controller.recover_interrupted(task_id, expected_run_id=run_id)
            assert result["reason"] == "active_attempt"
        finally:
            kbc._unlock(handle)
    assert read(controller, task_id).status == "running"
    assert orch.autonomy_queue.get(q.id).status == "running"

    older, old_orch, old_id, old_q, old_run = await claimed_attempt(
        tmp_path / "legacy", monkeypatch, marked=False)
    with kanban_scope(KanbanContext(older.home, "owner", can_mutate=True)):
        assert (await older.recover_interrupted(old_id,
                                                expected_run_id=old_run))["reason"] == "unverifiable_attempt"
    assert read(older, old_id).status == "running"
    assert old_orch.autonomy_queue.get(old_q.id).status == "running"


@pytest.mark.asyncio
async def test_dispatch_reconciles_released_attempt_without_replaying(tmp_path, monkeypatch):
    controller, orch, task_id, q, _run_id = await claimed_attempt(tmp_path, monkeypatch)
    assert (await controller.request(OWNER))["queued"] == []
    assert read(controller, task_id).status == "blocked"
    assert orch.autonomy_queue.get(q.id).status == "failed"


@pytest.mark.asyncio
async def test_completed_board_effect_survives_interrupted_queue(tmp_path, monkeypatch):
    controller, orch, task_id, q, run_id = await claimed_attempt(tmp_path, monkeypatch)
    with kanban_scope(KanbanContext(controller.home, "jarvis", task_id=task_id,
                                    run_id=run_id, can_mutate=True)), kb.connect_closing() as conn:
        assert kb.complete_task(conn, task_id, result="finished", expected_run_id=run_id)
    monkeypatch.setattr("agents.core.kanban.dispatcher._pid_alive", lambda pid: False)
    with kanban_scope(KanbanContext(controller.home, "owner", can_mutate=True)):
        result = await controller.recover_interrupted(task_id, expected_run_id=run_id)
    assert result["status"] == "board_effect_preserved"
    assert read(controller, task_id).status == "done"
    assert orch.autonomy_queue.get(q.id).status == "failed"


@pytest.mark.asyncio
async def test_finished_board_waits_for_process_exit_before_queue_settlement(tmp_path, monkeypatch):
    controller, orch, task_id, q, run_id = await claimed_attempt(tmp_path, monkeypatch)
    with kanban_scope(KanbanContext(controller.home, "jarvis", task_id=task_id,
                                    run_id=run_id, can_mutate=True)), kb.connect_closing() as conn:
        assert kb.complete_task(conn, task_id, result="finished", expected_run_id=run_id)
    with (kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        store.finish(conn, store.submissions(conn)[0]["id"], state="finished")
    await controller.request(OWNER)
    assert orch.autonomy_queue.get(q.id).status == "running"
    monkeypatch.setattr("agents.core.kanban.dispatcher._pid_alive", lambda pid: False)
    await controller.request(OWNER)
    assert orch.autonomy_queue.get(q.id).status == "failed"
    assert read(controller, task_id).status == "done"


@pytest.mark.asyncio
async def test_finished_receipt_is_removed_once_after_queue_completion(tmp_path, monkeypatch):
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    create(controller)
    qid = (await controller.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(qid, TaskStatus.APPROVED,
                                   decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["done"] == 1
    with (kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        record = store.submissions(conn)[0]
    from pathlib import Path
    path = Path(controller.home) / "nerva-attempts" / (record["id"] + ".lock")
    assert path.exists()
    await controller.request(OWNER)
    assert not path.exists()
    with (kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        assert store.submissions(conn)[0]["recovery_dev"] is None
