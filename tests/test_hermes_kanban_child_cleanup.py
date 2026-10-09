"""Terminal board cleanup preserves a workspace while its child approval is live."""

import json

import pytest

from agents.core.kanban import child_store
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.workspace_context import workspace_scope
from agents.core.kanban.workspaces import cleanup_workspace, materialize_workspace, plan_workspace


def terminal_owned_scratch(tmp_path, monkeypatch):
    home = tmp_path / "board"
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(home))
    with kanban_scope(KanbanContext(home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        task_id = kb.create_task(conn, title="synthetic cleanup", assignee="jarvis",
                                 workspace_kind="scratch")
        claimed = kb.claim_task(conn, task_id, claimer="nerva:synthetic")
        assert claimed and claimed.current_run_id
    run_id = claimed.current_run_id
    worker = KanbanContext(home, "jarvis", task_id=task_id, run_id=run_id,
                           session_id="kanban::synthetic", can_mutate=True)
    with kanban_scope(worker), kb.connect_closing() as conn:
        spec = plan_workspace(claimed)
        path = materialize_workspace(spec, still_current=lambda: True, expected_run_id=run_id)
        (path / "child-output.txt").write_text("preserve while child approval waits")
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET workspace_path=? WHERE id=?", (str(path), task_id))
        with workspace_scope(path, still_current=lambda: True):
            assert kb.complete_task(conn, task_id, result="synthetic terminal parent",
                                    expected_run_id=run_id)
    assert path.is_dir()
    return home, task_id, run_id, path


def add_child_approval(conn, task_id, run_id, path, state):
    child_store.initialize(conn)
    info = path.stat()
    with kb.write_txn(conn):
        conn.execute("""INSERT INTO nerva_child_approvals (
            id, task_id, parent_submission_id, parent_queue_id, parent_enqueue_id,
            run_id, profile, session_id, workspace_json, cwd, cwd_dev, cwd_ino,
            intent_json, intent_sha, labels_json, state, child_queue_id,
            child_enqueue_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            "child", task_id, "synthetic", 41, "parent-enqueue", run_id, "jarvis",
            "kanban::synthetic", json.dumps({"spec": {"path": str(path)}}), str(path),
            info.st_dev, info.st_ino, "{}", "synthetic-sha", "{}", state,
            73, "child-enqueue", 1, 1,
        ))


@pytest.mark.parametrize("state", ["prepared", "queued", "executing"])
def test_terminal_cleanup_defers_for_durable_child_approval(tmp_path, monkeypatch, state):
    home, task_id, run_id, path = terminal_owned_scratch(tmp_path, monkeypatch)
    context = KanbanContext(home, "jarvis", task_id=task_id, run_id=run_id,
                            can_mutate=True)
    with kanban_scope(context), kb.connect_closing() as conn:
        add_child_approval(conn, task_id, run_id, path, state)
        result = cleanup_workspace(conn, task_id, expected_run_id=run_id,
                                   still_current=lambda: True)
    assert not result["removed"] and result["reason"] == "active_child"
    assert (path / "child-output.txt").read_text() == "preserve while child approval waits"


@pytest.mark.parametrize("state", [None, "succeeded", "failed"])
def test_terminal_owned_scratch_cleans_without_active_child(tmp_path, monkeypatch, state):
    home, task_id, run_id, path = terminal_owned_scratch(tmp_path, monkeypatch)
    context = KanbanContext(home, "jarvis", task_id=task_id, run_id=run_id,
                            can_mutate=True)
    with kanban_scope(context), kb.connect_closing() as conn:
        if state is not None:
            add_child_approval(conn, task_id, run_id, path, state)
        else:
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='nerva_child_approvals'").fetchone() is None
        result = cleanup_workspace(conn, task_id, expected_run_id=run_id,
                                   still_current=lambda: True)
    assert result["removed"] and result["reason"] == "removed"
    assert not path.exists()
