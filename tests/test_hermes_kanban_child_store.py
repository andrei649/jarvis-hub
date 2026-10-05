"""A child approval belongs to one real board run and one signed queue item."""

import json
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.kanban import child_store, dispatch_store
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.workspace_context import workspace_scope


@contextmanager
def running_parent(tmp_path, monkeypatch):
    home = tmp_path / "board"
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    with kanban_scope(KanbanContext(home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        task_id = kb.create_task(conn, title="synthetic parent", assignee="jarvis",
                                 workspace_kind="scratch")
        claimed = kb.claim_task(conn, task_id, claimer="nerva:parent")
        assert claimed and claimed.current_run_id
    cwd = home / "kanban" / "workspaces" / task_id
    cwd.mkdir(parents=True)
    worker = KanbanContext(home, "jarvis", task_id=task_id,
                           run_id=claimed.current_run_id, session_id="kanban::parent",
                           can_mutate=True)
    parent_queue = SimpleNamespace(id=41, mediation_enqueue_id="parent-enqueue",
                                   kind="kanban.worker", agent="jarvis", status="running")
    with kanban_scope(worker), workspace_scope(cwd, still_current=lambda: True), kb.connect_closing() as conn:
        dispatch_store.initialize(conn)
        child_store.initialize(conn)
        binding = dispatch_store.workspace_snapshot(conn, task_id)
        with kb.write_txn(conn):
            conn.execute(
                "INSERT INTO nerva_dispatches "
                "(id, task_id, input_sha, lane, profile, prompt, prompt_sha, state, "
                "queue_id, enqueue_id, run_id, created_at, workspace_json) "
                "VALUES ('parent', ?, 'input', 'ready', 'jarvis', 'prompt', 'hash', "
                "'running', 41, 'parent-enqueue', ?, 1, ?)",
                (task_id, claimed.current_run_id, json.dumps(binding)),
            )
        parent = dispatch_store.get(conn, "parent")
        yield conn, parent, parent_queue, cwd


def child_queue(row, *, args=None, intent=None, enqueue="child-enqueue"):
    return SimpleNamespace(
        id=73, mediation_enqueue_id=enqueue, kind="toolrpc.file_write", agent="jarvis",
        status="running", payload={
            "tool": "file_write", "args": args or {"path": "note.txt", "content": "new"},
            "labels": {"class": "ordinary"},
            "class": "ordinary",
            "kanban_child": json.loads(row["intent_json"]) if intent is None else intent,
        },
    )


def prepare(conn, parent, queue, cwd):
    return child_store.prepare(conn, parent, queue, cwd, "file_write",
                               {"path": "note.txt", "content": "new"},
                               {"class": "ordinary"})


def test_approved_child_claims_once_after_atomic_parent_park(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        assert row["state"] == "prepared"
        assert child_store.active(conn, parent["task_id"])
        with pytest.raises(ValueError):
            prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)
        parked = child_store.bind_and_park(conn, row, queued)
        assert parked["state"] == "queued"
        board_task = kb.get_task(conn, parent["task_id"])
        assert board_task.status == "blocked" and board_task.block_kind == "needs_input"
        ended = kb.latest_run(conn, parent["task_id"])
        assert ended.id == parent["run_id"] and ended.outcome == "blocked"
        assert ended.ended_at is not None
        claimed = child_store.claim(conn, parked, queued)
        assert claimed["state"] == "executing"
        assert child_store.validate(conn, claimed, queued)
        with pytest.raises(ValueError):
            child_store.claim(conn, parked, queued)
        done = child_store.complete(conn, row["id"], success=True)
        assert done["state"] == "succeeded"
        assert not child_store.active(conn, parent["task_id"])
        assert not child_store.validate(conn, done, queued)
        with pytest.raises(ValueError):
            child_store.complete(conn, row["id"], success=True)
        with kb.connect_closing() as reopened:
            assert child_store.get(reopened, row["id"])["state"] == "succeeded"


def test_forged_queue_payload_cannot_park_parent(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        forged = child_queue(row, args={"path": "note.txt", "content": "forged"})
        with pytest.raises(ValueError):
            child_store.bind_and_park(conn, row, forged)
        assert child_store.get(conn, row["id"])["state"] == "prepared"
        assert kb.get_task(conn, parent["task_id"]).status == "running"
        assert kb.get_run(conn, parent["run_id"]).ended_at is None


def test_board_and_workspace_drift_refuse_approved_child(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)
        child_store.bind_and_park(conn, row, queued)
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(cwd))
        with pytest.raises(ValueError):
            child_store.claim(conn, row, queued)
        assert not child_store.validate(conn, row, queued)
        assert child_store.get(conn, row["id"])["state"] == "queued"


def test_parent_dispatch_may_finish_but_newer_run_refuses_claim(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)
        child_store.bind_and_park(conn, row, queued)
        dispatch_store.finish(conn, parent["id"], state="finished")
        assert child_store.validate(conn, row, queued)
        with kb.write_txn(conn):
            conn.execute("INSERT INTO task_runs (task_id, profile, status, started_at, ended_at, outcome) "
                         "VALUES (?, 'jarvis', 'blocked', ?, ?, 'blocked')",
                         (parent["task_id"], int(time.time()) + 100, int(time.time()) + 100))
        assert not child_store.validate(conn, row, queued)
        with pytest.raises(ValueError):
            child_store.claim(conn, row, queued)
        assert child_store.get(conn, row["id"])["state"] == "queued"


def test_queue_changes_inside_park_transaction_roll_back_board(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)

        class ChangingQueue:
            id = queued.id
            mediation_enqueue_id = queued.mediation_enqueue_id
            kind = queued.kind
            agent = queued.agent
            status = queued.status
            reads = 0

            @property
            def payload(self):
                self.reads += 1
                if self.reads == 1:
                    return queued.payload
                return {**queued.payload, "args": {"path": "note.txt", "content": "forged"}}

        with pytest.raises(ValueError):
            child_store.bind_and_park(conn, row, ChangingQueue())
        assert kb.get_task(conn, parent["task_id"]).status == "running"
        assert kb.get_run(conn, parent["run_id"]).ended_at is None
        assert child_store.get(conn, row["id"])["state"] == "prepared"


def test_failed_child_is_terminal_and_cannot_replay(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)
        child_store.bind_and_park(conn, row, queued)
        child_store.claim(conn, row, queued)
        failed = child_store.complete(conn, row["id"], success=False, error="synthetic tool error")
        assert failed["state"] == "failed" and failed["error"] == "synthetic tool error"
        assert not child_store.active(conn, parent["task_id"])
        with pytest.raises(ValueError):
            child_store.claim(conn, row, queued)


def test_approved_child_refuses_changed_args_and_replaced_cwd(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        row = prepare(conn, parent, parent_queue, cwd)
        queued = child_queue(row)
        child_store.bind_and_park(conn, row, queued)
        queued.payload["args"]["content"] = "forged after approval"
        assert not child_store.validate(conn, row, queued)
        with pytest.raises(ValueError):
            child_store.claim(conn, row, queued)
        queued.payload["args"]["content"] = "new"
        cwd.rename(cwd.with_name("old-workspace"))
        cwd.mkdir()
        assert not child_store.validate(conn, row, queued)
        with pytest.raises(ValueError):
            child_store.claim(conn, row, queued)


def test_stale_parent_scope_cannot_prepare_child(tmp_path, monkeypatch):
    with running_parent(tmp_path, monkeypatch) as (conn, parent, parent_queue, cwd):
        with (kanban_scope(replace(KanbanContext(tmp_path / "board", "jarvis", task_id=parent["task_id"],
                                                 run_id=parent["run_id"], session_id="kanban::parent",
                                                 can_mutate=True), run_id=parent["run_id"] + 1)),
              pytest.raises((PermissionError, ValueError))):
            prepare(conn, parent, parent_queue, cwd)
        assert not child_store.active(conn, parent["task_id"])
