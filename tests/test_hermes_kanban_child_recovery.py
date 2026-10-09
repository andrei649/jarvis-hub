"""Crash recovery for durable child intents, using the real board and mediated queue."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from agents.core.autonomy.queue import TaskStatus
from agents.core.kanban import child_store, dispatch_store, workspaces
from agents.core.kanban.context import KanbanContext, current_context, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.workspace_context import current_workspace
from tests.test_hermes_kanban_child_effects import propose_child
from tests.test_hermes_kanban_child_store import prepare, running_parent
from tests.test_hermes_kanban_dispatcher import OWNER, create, fixture_runtime


def enqueue_child(worker, queue, record):
    intent = json.loads(record["intent_json"])
    labels = json.loads(record["labels_json"])
    payload = {
        "submission_id": record["id"],
        "tool": intent["tool"],
        "args": {"path": "note.txt", "content": "new"},
        "labels": labels,
        "class": "ordinary",
        "kanban_child": intent,
    }
    queue_id = worker.govern_enqueue(
        agent=record["profile"], kind="toolrpc.file_write", title="synthetic child",
        payload=payload, risk_tier=2, autonomy_level="ask", origin="generated",
    )
    return queue.get(queue_id)


def test_rejected_bound_child_reconciles_once_and_keeps_parent_blocked(tmp_path, monkeypatch):
    _, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    queue = orch.autonomy_queue
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        record = prepare(conn, parent, parent_queue, cwd)
        child = enqueue_child(orch.autonomy, queue, record)
        bound = child_store.bind_and_park(conn, record, child)
        assert workspaces._active_child(conn, parent["task_id"])
        queue.transition(child.id, TaskStatus.REJECTED, decided_by="owner", decision="reject")

        changed = child_store.reconcile(conn, queue)
        assert [row["id"] for row in changed] == [record["id"]]
        assert changed[0]["state"] == "failed"
        assert child_store.reconcile(conn, queue) == []
        assert not child_store.active(conn, parent["task_id"])
        assert not workspaces._active_child(conn, parent["task_id"])
        task = kb.get_task(conn, parent["task_id"])
        assert task.status == "blocked" and task.block_kind == "needs_input"
        assert cwd.is_dir()
        with kb.connect_closing() as reopened:
            assert child_store.get(reopened, bound["id"])["state"] == "failed"
            assert not child_store.active(reopened, parent["task_id"])


def test_prepared_orphan_waits_for_terminal_parent(tmp_path, monkeypatch):
    _, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    queue = orch.autonomy_queue
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        prepare(conn, parent, parent_queue, cwd)
        assert child_store.reconcile(conn, queue) == []
        assert child_store.active(conn, parent["task_id"])
        assert kb.block_task(conn, parent["task_id"], kind="needs_input",
                             reason="synthetic parent interruption", expected_run_id=parent["run_id"])
        # The fake parent queue is not an authenticated queue birth.
        assert child_store.reconcile(conn, queue) == []
        assert child_store.active(conn, parent["task_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("born", [False, True])
async def test_prepared_parent_terminal_recovers_exact_child_queue_birth(tmp_path, monkeypatch, born):
    controller, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    records = []
    child_queues = []

    async def runner(_orch, **_kwargs):
        context = current_context()
        with kb.connect_closing() as conn:
            parent = dispatch_store.get(conn, context.session_id.removeprefix("kanban::"))
            parent_queue = orch.autonomy_queue.get(parent["queue_id"])
            child_store.initialize(conn)
            record = child_store.prepare(
                conn, parent, parent_queue, current_workspace().cwd,
                "file_write", {"path": "note.txt", "content": "new"}, {"class": "ordinary"},
            )
            records.append(record)
            if born:
                child_queues.append(enqueue_child(orch.autonomy, orch.autonomy_queue, record))
            assert kb.block_task(conn, context.task_id, kind="needs_input",
                                 reason="synthetic prepared interruption", expected_run_id=context.run_id)
        return "waiting"

    controller.runner = runner
    task_id = create(controller, workspace_kind="scratch")
    parent_queue_id = (await controller.request(OWNER))["queued"][0]["queue_id"]
    orch.autonomy_queue.transition(parent_queue_id, TaskStatus.APPROVED,
                                   decided_by="owner", decision="approve")
    assert (await orch.autonomy.tick())["done"] == 1
    assert orch.autonomy_queue.get(parent_queue_id).status == "done"
    record = records[0]
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        assert kb.get_task(conn, task_id).status == "blocked"
        if born:
            assert child_store.reconcile(conn, orch.autonomy_queue) == []
            assert child_store.active(conn, task_id)
            orch.autonomy_queue.transition(child_queues[0].id, TaskStatus.REJECTED,
                                           decided_by="owner", decision="reject")
        else:
            lookup = orch.autonomy_queue.find_submission_task

            def corrupt_lookup(*_args, **_kwargs):
                raise sqlite3.DatabaseError("corrupt queue lookup")

            orch.autonomy_queue.find_submission_task = corrupt_lookup
            try:
                assert child_store.reconcile(conn, orch.autonomy_queue) == []
                assert child_store.active(conn, task_id)
            finally:
                orch.autonomy_queue.find_submission_task = lookup
        settled = child_store.reconcile(conn, orch.autonomy_queue)
        assert [row["id"] for row in settled] == [record["id"]]
        assert settled[0]["state"] == "failed"
        assert not child_store.active(conn, task_id)
        assert kb.get_task(conn, task_id).status == "blocked"
        assert child_store.reconcile(conn, orch.autonomy_queue) == []
    with kanban_scope(KanbanContext(controller.home, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
        assert child_store.get(conn, record["id"])["state"] == "failed"


def test_degraded_queue_snapshot_cannot_settle_rejected_child(tmp_path, monkeypatch):
    _, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    queue = orch.autonomy_queue
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        record = prepare(conn, parent, parent_queue, cwd)
        child = enqueue_child(orch.autonomy, queue, record)
        child_store.bind_and_park(conn, record, child)
        queue.transition(child.id, TaskStatus.REJECTED, decided_by="owner", decision="reject")
        snapshot = queue.execution_snapshot
        queue.execution_snapshot = lambda *_args, **_kwargs: (None, True)
        try:
            assert child_store.reconcile(conn, queue) == []
            assert child_store.active(conn, parent["task_id"])
        finally:
            queue.execution_snapshot = snapshot
        assert child_store.reconcile(conn, queue)[0]["state"] == "failed"


def test_expired_child_is_terminal_nonexecution_and_releases_guard(tmp_path, monkeypatch):
    _, orch, _, _, _ = fixture_runtime(tmp_path, monkeypatch)
    queue = orch.autonomy_queue
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        record = prepare(conn, parent, parent_queue, cwd)
        child = enqueue_child(orch.autonomy, queue, record)
        child_store.bind_and_park(conn, record, child)
        deadline = datetime.now(UTC) - timedelta(minutes=1)
        queue._conn.execute("UPDATE tasks SET approval_deadline_at=? WHERE id=?",
                            (deadline.isoformat(), child.id))
        queue._conn.commit()
        batch = queue.expire_pending_approvals(now=datetime.now(UTC))
        assert [task.id for task in batch.tasks] == [child.id]
        assert queue.get(child.id).status == "expired"
        assert child_store.reconcile(conn, queue)[0]["state"] == "failed"
        assert kb.get_task(conn, parent["task_id"]).status == "blocked"
        assert cwd.is_dir()


@pytest.mark.asyncio
async def test_success_before_queue_done_is_never_reclassified(tmp_path, monkeypatch):
    coordinator, orch, _, _, task_id, child = await propose_child(tmp_path, monkeypatch)
    await orch.autonomy.apply_decision(child.id, "accept", "owner")
    assert (await orch.autonomy.tick())["done"] == 1
    with (kanban_scope(KanbanContext(coordinator.kanban_dispatcher().home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        child_id = child.payload["kanban_child"]["child_id"]
        assert child_store.get(conn, child_id)["state"] == "succeeded"
        assert child_store.reconcile(conn, orch.autonomy_queue) == []
        assert child_store.get(conn, child_id)["state"] == "succeeded"
        assert kb.get_task(conn, task_id).status == "blocked"


@pytest.mark.asyncio
async def test_executing_crash_after_physical_effect_records_ambiguity_without_replay(tmp_path, monkeypatch):
    coordinator, orch, _, cwd, task_id, child = await propose_child(tmp_path, monkeypatch)
    original = child_store.complete

    def crash_before_board_result(*_args, **_kwargs):
        raise RuntimeError("synthetic crash after effect")

    monkeypatch.setattr(child_store, "complete", crash_before_board_result)
    try:
        await orch.autonomy.apply_decision(child.id, "accept", "owner")
        await orch.autonomy.tick()
    finally:
        monkeypatch.setattr(child_store, "complete", original)
    assert (cwd / "note.txt").read_text() == "worker after"
    assert orch.autonomy_queue.get(child.id).status == "failed"

    with (kanban_scope(KanbanContext(coordinator.kanban_dispatcher().home, "dispatcher", can_mutate=True)),
          kb.connect_closing() as conn):
        assert child_store.get(conn, child.payload["kanban_child"]["child_id"])["state"] == "executing"
        settled = child_store.reconcile(conn, orch.autonomy_queue)
        assert len(settled) == 1 and settled[0]["error"] == "child_execution_interrupted_ambiguous"
        assert kb.get_task(conn, task_id).status == "blocked"
        assert child_store.reconcile(conn, orch.autonomy_queue) == []
    assert (await orch.autonomy.tick())["ran"] == 0
    assert (cwd / "note.txt").read_text() == "worker after"
