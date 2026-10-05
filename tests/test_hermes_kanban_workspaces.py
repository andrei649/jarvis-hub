"""Behavior tests for the scoped Hermes workspace adapter."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from contextvars import Context
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.file_tools import FileScope
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.workspace_context import workspace_scope
from agents.core.kanban.workspaces import cleanup_workspace, materialize_workspace, plan_workspace


def _task(task_id="t_abc", kind="scratch", path=None, branch=None, run_id=7):
    return SimpleNamespace(
        id=task_id, workspace_kind=kind, workspace_path=path,
        branch_name=branch, current_run_id=run_id,
    )


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True,
        timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def owner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "owned"
    home.mkdir()
    root.mkdir()
    monkeypatch.setattr(FileScope, "from_env", classmethod(lambda cls: cls([home, root])))
    context = KanbanContext(home=home, profile="owner", board="default", task_id="t_abc", run_id=7, can_mutate=True)
    return home, root, context


def test_scratch_plan_is_pure_and_materialization_needs_live_callback(owner):
    home, _, context = owner
    with kanban_scope(context):
        spec = plan_workspace(_task())
        path = Path(spec["path"])
        assert spec["kind"] == "scratch"
        assert path == home / "kanban" / "workspaces" / "t_abc"
        assert not path.exists()
        with pytest.raises(PermissionError):
            materialize_workspace(spec, still_current=lambda: False)
        assert not path.exists()
        assert materialize_workspace(spec, still_current=lambda: True) == path
        assert path.is_dir()


def test_stale_and_foreign_spec_cannot_create_workspace(owner):
    _, root, context = owner
    with kanban_scope(context):
        spec = plan_workspace(_task(kind="dir", path=str(root / "new")))
        for changed in ({**spec, "task_id": "foreign"}, {**spec, "path": str(root / "other")},
                        {**spec, "run_id": 8}):
            with pytest.raises((PermissionError, ValueError)):
                materialize_workspace(changed, still_current=lambda: True)
        with pytest.raises(PermissionError):
            materialize_workspace(spec, still_current=lambda: (_ for _ in ()).throw(RuntimeError("revoked")))
    assert not (root / "new").exists()
    assert not (root / "other").exists()


def test_worktree_branch_reuse_and_dirty_unpushed_cleanup(owner):
    _, root, context = owner
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--allow-empty", "-m", "base")
    with kanban_scope(context):
        spec = plan_workspace(_task(kind="worktree", path=str(repo)))
        target = Path(spec["path"])
        assert target == repo / ".worktrees" / "t_abc"
        assert not target.exists()
        assert materialize_workspace(spec, still_current=lambda: True) == target
        assert _git(target, "branch", "--show-current") == "wt/t_abc"
        assert materialize_workspace(spec, still_current=lambda: True) == target
        conn = _db(target, "worktree")
        assert cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        assert not target.exists()
        assert not _git(repo, "branch", "--list", "wt/t_abc")
        materialize_workspace(spec, still_current=lambda: True)
        (target / "dirty.txt").write_text("work")
        assert not cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        assert target.exists()
        (target / "dirty.txt").unlink()
        _git(target, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--allow-empty", "-m", "unique")
        assert not cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        assert target.exists()


def _db(path: Path, kind: str):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, workspace_kind TEXT, workspace_path TEXT,
                            branch_name TEXT, current_run_id INTEGER);
        CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
        CREATE TABLE task_attachments (task_id TEXT, stored_path TEXT);
        CREATE TABLE task_runs (id INTEGER, task_id TEXT, status TEXT);
    """)
    conn.execute("INSERT INTO tasks VALUES (?, 'done', ?, ?, ?, NULL)", ("t_abc", kind, str(path), "wt/t_abc"))
    conn.execute("INSERT INTO task_runs VALUES (7, 't_abc', 'done')")
    return conn


def test_cleanup_preserves_foreign_paths_children_and_attachments(owner):
    home, root, context = owner
    foreign = root / "user"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("keep")
    with kanban_scope(context):
        conn = _db(foreign, "scratch")
        assert not cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        assert (foreign / "keep.txt").exists()
        scratch = home / "kanban" / "workspaces" / "t_abc"
        assert materialize_workspace(plan_workspace(_task()), still_current=lambda: True) == scratch
        conn.execute("UPDATE tasks SET workspace_path=? WHERE id='t_abc'", (str(scratch),))
        conn.execute("INSERT INTO tasks VALUES ('child', 'ready', 'dir', NULL, NULL, NULL)")
        conn.execute("INSERT INTO task_links VALUES ('t_abc', 'child')")
        assert not cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        conn.execute("UPDATE tasks SET status='done' WHERE id='child'")
        conn.execute("INSERT INTO task_attachments VALUES ('t_abc', ?)", (str(scratch / "artifact.txt"),))
        assert not cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        conn.execute("DELETE FROM task_attachments")
        with pytest.raises(PermissionError):
            cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: False)
        assert scratch.exists()
        conn.execute("INSERT INTO task_runs VALUES (8, 't_abc', 'done')")
        assert cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["reason"] == "wrong_run"
        conn.execute("DELETE FROM task_runs WHERE id=8")
        assert cleanup_workspace(conn, "t_abc", expected_run_id=7, still_current=lambda: True)["removed"]
        assert not scratch.exists()


def test_delegated_and_closed_scope_have_no_effects(owner):
    home, _, context = owner
    with kanban_scope(context):
        spec = plan_workspace(_task())
    with pytest.raises(PermissionError):
        materialize_workspace(spec, still_current=lambda: True)
    delegated = KanbanContext(**{**context.__dict__, "delegated": True})
    with kanban_scope(delegated), pytest.raises(PermissionError):
        materialize_workspace(spec, still_current=lambda: True)
    assert not Path(spec["path"]).exists()


def test_serialized_spec_and_live_scope_drift(owner, monkeypatch):
    home, root, context = owner
    with kanban_scope(context):
        spec = plan_workspace(_task(kind="dir", path=str(root / "work")))
        restored = json.loads(json.dumps(spec))
        assert materialize_workspace(restored, still_current=lambda: True, expected_run_id=7) == root / "work"
        with pytest.raises(PermissionError):
            materialize_workspace(restored, still_current=lambda: True, expected_run_id=8)
        monkeypatch.setattr(FileScope, "from_env", classmethod(lambda cls: cls([home])))
        with pytest.raises((PermissionError, ValueError)):
            materialize_workspace(restored, still_current=lambda: True)


def test_inherited_worktree_on_other_branch_gets_per_task_fallback(owner):
    _, root, context = owner
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--allow-empty", "-m", "base")
    inherited = repo / ".worktrees" / "parent"
    inherited.parent.mkdir()
    _git(repo, "worktree", "add", "-b", "wt/parent", str(inherited))
    with kanban_scope(context):
        spec = plan_workspace(_task(kind="worktree", path=str(inherited)))
        assert spec["path"] == str(repo / ".worktrees" / "t_abc")
        created = materialize_workspace(spec, still_current=lambda: True)
        assert _git(created, "branch", "--show-current") == "wt/t_abc"
        assert _git(inherited, "branch", "--show-current") == "wt/parent"


def test_symlink_escape_and_callback_revocation_preserve_paths(owner):
    home, root, context = owner
    outside = root.parent / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with kanban_scope(context):
        with pytest.raises((PermissionError, ValueError)):
            plan_workspace(_task(kind="dir", path=str(root / "link" / "new")))
        spec = plan_workspace(_task())
        calls = iter((True, False))
        with pytest.raises(PermissionError):
            materialize_workspace(spec, still_current=lambda: next(calls))
        assert not Path(spec["path"]).exists()
        scratch_parent = home / "kanban" / "workspaces"
        scratch_parent.mkdir(parents=True)
        scratch_parent.rmdir()
        scratch_parent.symlink_to(outside, target_is_directory=True)
        with pytest.raises(PermissionError):
            materialize_workspace(spec, still_current=lambda: True)
        assert not (outside / "t_abc").exists()


def test_worktree_checkout_refuses_repository_filter_commands(owner):
    _, root, context = owner
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--allow-empty", "-m", "base")
    marker = root / "executed"
    _git(repo, "config", "filter.inject.smudge", f"touch {marker}")
    with kanban_scope(context), pytest.raises(PermissionError):
        plan_workspace(_task(kind="worktree", path=str(repo)))
    assert not marker.exists()
    assert not (repo / ".worktrees" / "t_abc").exists()


def test_existing_scratch_is_reused_without_acquiring_cleanup_ownership(owner):
    with kanban_scope(owner[2]):
        spec = plan_workspace(_task())
        path = Path(spec["path"])
        path.mkdir(parents=True)
        sentinel = path / "user-sentinel.txt"
        sentinel.write_text("pre-existing user work")
        assert materialize_workspace(spec, still_current=lambda: True) == path
        result = cleanup_workspace(_db(path, "scratch"), "t_abc", expected_run_id=7,
                                   still_current=lambda: True)
        assert not result["removed"]
        assert result["reason"] == "unowned_scratch"
        assert sentinel.read_text() == "pre-existing user work"


def test_terminal_scratch_cannot_be_removed_until_its_workspace_scope_exits(owner):
    with kanban_scope(owner[2]):
        spec = plan_workspace(_task())
        path = materialize_workspace(spec, still_current=lambda: True)
        conn = _db(path, "scratch")
        with workspace_scope(path, still_current=lambda: True):
            result = cleanup_workspace(conn, "t_abc", expected_run_id=7,
                                       still_current=lambda: True)
            assert result["reason"] == "bound_workspace"
            assert not result["removed"] and path.is_dir()
        assert cleanup_workspace(conn, "t_abc", expected_run_id=7,
                                 still_current=lambda: True)["removed"]


def test_scratch_cleanup_defers_when_runner_is_bound_in_another_context(owner):
    context = owner[2]
    with kanban_scope(context):
        spec = plan_workspace(_task())
        path = materialize_workspace(spec, still_current=lambda: True)
        conn = _db(path, "scratch")
        with workspace_scope(path, still_current=lambda: True):
            def cleanup_elsewhere():
                with kanban_scope(context):
                    return cleanup_workspace(conn, "t_abc", expected_run_id=7,
                                             still_current=lambda: True)
            result = Context().run(cleanup_elsewhere)
            assert not result["removed"] and result["reason"] == "bound_workspace"
            assert path.is_dir()


def test_scratch_cleanup_preserves_replacement_at_previously_owned_path(owner):
    with kanban_scope(owner[2]):
        spec = plan_workspace(_task())
        path = materialize_workspace(spec, still_current=lambda: True)
        original = path.with_name("original-workspace")
        path.rename(original)
        path.mkdir()
        sentinel = path / "replacement.txt"
        sentinel.write_text("new owner")
        # Reusing a path must never overwrite an old ownership record.
        assert materialize_workspace(spec, still_current=lambda: True) == path
        result = cleanup_workspace(_db(path, "scratch"), "t_abc", expected_run_id=7,
                                   still_current=lambda: True)
        assert not result["removed"] and result["reason"] == "unowned_scratch"
        assert sentinel.read_text() == "new owner" and original.is_dir()


@pytest.mark.parametrize("record_state", ["missing", "malformed", "symlink", "wrong_identity", "oversized"])
def test_scratch_cleanup_requires_intact_record_outside_worker_root(owner, record_state):
    with kanban_scope(owner[2]):
        path = materialize_workspace(plan_workspace(_task()), still_current=lambda: True)
        record = path.parent / ".ownership" / "t_abc.json"
        assert record.is_file() and path not in record.parents
        if record_state == "missing":
            record.unlink()
        elif record_state == "malformed":
            record.write_text("{")
        elif record_state == "symlink":
            target = record.with_name("foreign.json")
            record.rename(target)
            record.symlink_to(target)
        elif record_state == "oversized":
            record.write_text(" " * 4097)
        else:
            values = json.loads(record.read_text())
            values["task_id"] = "another-task"
            record.write_text(json.dumps(values))
        (path / "keep.txt").write_text("keep")
        result = cleanup_workspace(_db(path, "scratch"), "t_abc", expected_run_id=7,
                                   still_current=lambda: True)
        assert result["reason"] == "unowned_scratch" and not result["removed"]
        assert (path / "keep.txt").read_text() == "keep"


def test_scratch_creation_revocation_does_not_adopt_directory_on_retry(owner):
    with kanban_scope(owner[2]):
        spec = plan_workspace(_task())
        path = Path(spec["path"])
        with pytest.raises(PermissionError):
            materialize_workspace(spec, still_current=lambda: not path.exists())
        assert path.is_dir()
        # A failed creation's leftover directory is preserved conservatively.
        assert materialize_workspace(spec, still_current=lambda: True) == path
        result = cleanup_workspace(_db(path, "scratch"), "t_abc", expected_run_id=7,
                                   still_current=lambda: True)
        assert result["reason"] == "unowned_scratch" and path.is_dir()


def test_cleanup_preserves_scratch_when_ownership_record_cannot_be_retired(owner, monkeypatch):
    with kanban_scope(owner[2]):
        path = materialize_workspace(plan_workspace(_task()), still_current=lambda: True)
        record = path.parent / ".ownership" / "t_abc.json"
        unlink = Path.unlink

        def refused_unlink(candidate, *args, **kwargs):
            if candidate == record:
                raise PermissionError("record became read-only")
            return unlink(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", refused_unlink)
        result = cleanup_workspace(_db(path, "scratch"), "t_abc", expected_run_id=7,
                                   still_current=lambda: True)
        assert not result["removed"] and result["reason"] == "ownership_record_retained"
        assert path.exists() and record.exists()


def test_worktree_cleanup_reports_removal_when_branch_permission_is_revoked(owner):
    _, root, context = owner
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "--allow-empty", "-m", "base")
    with kanban_scope(context):
        path = materialize_workspace(plan_workspace(_task(kind="worktree", path=str(repo))),
                                     still_current=lambda: True)
        result = cleanup_workspace(_db(path, "worktree"), "t_abc", expected_run_id=7,
                                   still_current=path.exists)
        assert result["removed"] and result["reason"] == "removed_branch_retained"
        assert not path.exists() and _git(repo, "branch", "--list", "wt/t_abc")
