"""Scoped, durable behavior checks for the pinned Hermes Kanban state port."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path

import pytest

from agents.core.kanban.context import KanbanContext, current_context, kanban_scope, scope_is_bound
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import kanban_db_dispatch as dispatch
from agents.core.kanban.upstream.compat import get_env


def _scope(tmp_path: Path, **overrides):
    return kanban_scope(KanbanContext(home=tmp_path, profile="owner", can_mutate=True, **overrides))


def test_scope_closes_for_inherited_context(tmp_path):
    with _scope(tmp_path):
        inherited = __import__("contextvars").copy_context()
        assert current_context().home == tmp_path
        assert scope_is_bound()
    with pytest.raises(PermissionError):
        inherited.run(kb.set_current_board, "default")
    assert inherited.run(current_context) is None
    assert inherited.run(scope_is_bound)
    assert not scope_is_bound()


def test_delegate_clear_scope_drops_inherited_task_identity(tmp_path):
    with kanban_scope(KanbanContext(home=tmp_path, profile="owner", task_id="t_1", run_id=7, can_mutate=True)):
        assert get_env("HERMES_KANBAN_TASK") == "t_1"
        assert get_env("HERMES_KANBAN_RUN_ID") == "7"
        with kanban_scope(None):
            assert current_context() is None
            with pytest.raises(PermissionError):
                get_env("HERMES_KANBAN_TASK")
        assert get_env("HERMES_KANBAN_TASK") == "t_1"


def test_missing_readonly_and_delegated_scopes_refuse_writes(tmp_path):
    with _scope(tmp_path), kb.connect_closing() as conn:
        kb.create_task(conn, title="existing", assignee="owner")
    with pytest.raises(PermissionError):
        kb.connect()
    for flags in ({}, {"can_mutate": True, "delegated": True}):
        with kanban_scope(KanbanContext(home=tmp_path, profile="owner", **flags)):
            with pytest.raises(PermissionError):
                kb.set_current_board("default")
            with kb.connect_closing() as conn, pytest.raises(PermissionError):
                kb.create_task(conn, title="forbidden", assignee="owner")
    with _scope(tmp_path), kb.connect_closing() as conn:
        assert [task.title for task in kb.list_tasks(conn)] == ["existing"]


def test_scoped_boards_are_durable_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "wrong"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "wrong.db"))
    with _scope(tmp_path):
        with kb.connect_closing() as conn:
            task_id = kb.create_task(conn, title="persist", assignee="owner")
        assert kb.kanban_db_path() == tmp_path / "kanban.db"
        with kb.connect_closing(board="second") as conn:
            assert kb.get_task(conn, task_id) is None
            second = kb.create_task(conn, title="another", assignee="owner")
        with kb.connect_closing() as conn:
            assert kb.get_task(conn, task_id).title == "persist"
            assert kb.get_task(conn, second) is None
        assert not (tmp_path / "wrong.db").exists()


def test_concurrent_claim_has_one_winner(tmp_path):
    with _scope(tmp_path):
        with kb.connect_closing() as conn:
            task_id = kb.create_task(conn, title="race", assignee="owner")
        def claim():
            with kb.connect_closing() as conn:
                return kb.claim_task(conn, task_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, claim) for _ in range(2)]
            results = [future.result() for future in futures]
        assert sum(result is not None for result in results) == 1


def test_dependency_cycle_rejected_and_parent_completion_promotes_child(tmp_path):
    with _scope(tmp_path), kb.connect_closing() as conn:
        parent = kb.create_task(conn, title="parent", assignee="owner")
        child = kb.create_task(conn, title="child", assignee="owner")
        assert kb.link_tasks(conn, parent, child)
        assert kb.get_task(conn, child).status == "todo"
        with pytest.raises(ValueError, match="cycle"):
            kb.link_tasks(conn, child, parent)
        assert kb.parent_ids(conn, child) == [parent]
        assert kb.complete_task(conn, parent, result="parent result")
        assert kb.get_task(conn, child).status == "ready"


def test_stale_run_cannot_complete_or_steal_current_claim(tmp_path):
    with _scope(tmp_path), kb.connect_closing() as conn:
        task_id = kb.create_task(conn, title="owned", assignee="owner")
        claimed = kb.claim_task(conn, task_id)
        assert claimed is not None
        assert kb.complete_task(conn, task_id, result="wrong run", expected_run_id=claimed.current_run_id + 1) is False
        assert kb.get_task(conn, task_id).status == "running"
        assert kb.complete_task(conn, task_id, result="owned result", expected_run_id=claimed.current_run_id)
        assert kb.get_task(conn, task_id).status == "done"


def test_attachment_bytes_and_metadata_survive_reopen(tmp_path):
    with _scope(tmp_path):
        with kb.connect_closing() as conn:
            task_id = kb.create_task(conn, title="artifact", assignee="owner")
            attachment_id = kb.store_attachment_bytes(conn, task_id, "../note.txt", b"evidence")
        with kb.connect_closing() as conn:
            attachment = kb.get_attachment(conn, attachment_id)
            assert attachment.filename == "note.txt"
            assert Path(attachment.stored_path).read_bytes() == b"evidence"
            assert [row.id for row in kb.list_attachments(conn, task_id)] == [attachment_id]


def test_internal_sql_identifiers_cannot_inject_into_board(tmp_path):
    from agents.core.kanban.upstream import kanban_db_workspace as workspace
    with _scope(tmp_path), kb.connect_closing() as conn:
        tid = kb.create_task(conn, title="preserved", assignee="owner")
        for operation in (
            lambda: kb._linked_ids(conn, "parent_id; DROP TABLE tasks", "child_id", tid),
            lambda: kb._task_rows(conn, "tasks", tid, "created_at ASC"),
            lambda: workspace._set_task_column(conn, tid, "title = 'forged' --", "ignored"),
        ):
            with pytest.raises(ValueError, match="identifier"):
                operation()
        assert kb.get_task(conn, tid).title == "preserved"


def test_review_handoff_and_changes_request_preserve_run_provenance(tmp_path):
    with _scope(tmp_path), kb.connect_closing() as conn:
        task_id = kb.create_task(conn, title="review me", assignee="builder")
        implementer = kb.claim_task(conn, task_id)
        assert kb.request_review(
            conn, task_id, summary="ready for review", reviewer="reviewer",
            expected_run_id=implementer.current_run_id,
        )
        assert kb.get_task(conn, task_id).status == "review"
        reviewer = kb.claim_review_task(conn, task_id)
        assert reviewer.current_run_id != implementer.current_run_id
        assert kb.request_changes(conn, task_id, reason="revise", expected_run_id=implementer.current_run_id)[0] is False
        assert kb.request_changes(conn, task_id, reason="revise", expected_run_id=reviewer.current_run_id) == (True, "builder")
        task = kb.get_task(conn, task_id)
        assert task.status == "ready" and task.assignee == "builder"


def test_dispatcher_entrypoints_refuse_external_worker_activation(tmp_path):
    with _scope(tmp_path), kb.connect_closing() as conn:
        task_id = kb.create_task(conn, title="not launched", assignee="owner")
        with pytest.raises(NotImplementedError, match="approved Nerva dispatcher"):
            dispatch.dispatch_once(conn)
        with pytest.raises(NotImplementedError, match="approved Nerva dispatcher"):
            dispatch.run_daemon()
        task = kb.get_task(conn, task_id)
        with pytest.raises(NotImplementedError, match="approved Nerva dispatcher"):
            dispatch._default_spawn(task, str(tmp_path))
        assert kb.get_task(conn, task_id).status == "ready"


def test_unbound_workspace_cleanup_refuses_before_terminal_transition(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    with _scope(tmp_path), kb.connect_closing() as conn:
        task_id = kb.create_task(
            conn, title="workspace artifact", assignee="owner",
            workspace_path=str(workspace),
        )
        with pytest.raises(NotImplementedError, match="FileScope workspace cleanup"):
            kb.complete_task(conn, task_id, result="done")
        assert kb.get_task(conn, task_id).status == "ready"
        with pytest.raises(NotImplementedError, match="FileScope workspace cleanup"):
            kb.archive_task(conn, task_id)
        assert kb.get_task(conn, task_id).status == "ready"
        assert workspace.is_dir()


def test_explicit_db_paths_cannot_escape_scoped_home(tmp_path):
    outside = tmp_path.parent / "outside-kanban.db"
    with _scope(tmp_path):
        for operation in (kb.connect, kb.init_db, kb.repair_db):
            with pytest.raises(PermissionError):
                operation(outside)
        with pytest.raises(ValueError, match="invalid board slug"):
            kb.kanban_db_path("../escape")
    assert not outside.exists()
