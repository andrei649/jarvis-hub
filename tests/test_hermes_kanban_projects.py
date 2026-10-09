"""Durable and scoped behavior of the pinned Hermes project store."""

import sqlite3
from contextlib import closing

import pytest

from agents.core.kanban import projects
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import projects_db as pdb


def _scope(home, **flags):
    return kanban_scope(KanbanContext(home=home, profile=flags.pop("profile", "owner"), **flags))


def test_projects_persist_per_home_and_resolve_from_durable_store(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    a = root / "a"
    b = root / "b"
    a.mkdir()
    b.mkdir()
    home_a, home_b = tmp_path / "home-a", tmp_path / "home-b"
    with _scope(home_a, can_mutate=True), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Alpha", folders=[str(a), str(b)], primary_path=str(b))
        assert pdb.get_project(conn, pid).primary_path == str(b)
    with _scope(home_a):
        assert projects.resolve_project("alpha") == (pid, "Alpha", str(b))
        listed = projects.list_projects()
        assert listed[0]["folders"][0]["path"] == str(b)
        assert listed[0]["folders"][0]["is_primary"] is True
    with _scope(home_b):
        with pytest.raises(ValueError):
            projects.resolve_project("alpha")
        assert projects.list_projects() == []
    assert (home_a / "projects.db").exists()
    assert not (home_b / "projects.db").exists()


def test_owner_only_mutation_and_foreign_connection_refused(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    with _scope(tmp_path / "home", can_mutate=True), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Original")
        db_path = pdb.projects_db_path()
        with closing(sqlite3.connect(db_path)) as foreign, pytest.raises(PermissionError):
            pdb.update_project(foreign, pid, name="Foreign")
    for flags in ({}, {"can_mutate": True, "delegated": True},
                  {"can_mutate": True, "profile": "worker"},
                  {"can_mutate": True, "task_id": "t_1"},
                  {"can_mutate": True, "run_id": 1}):
        with _scope(tmp_path / "home", **flags), pdb.connect_closing() as conn, pytest.raises(PermissionError):
            pdb.update_project(conn, pid, name="Forbidden")
    with _scope(tmp_path / "home"), pdb.connect_closing() as conn:
        assert pdb.get_project(conn, pid).name == "Original"
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE projects SET name = 'Bypass' WHERE id = ?", (pid,))
        with pytest.raises(sqlite3.DatabaseError):
            conn._raw.execute("DELETE FROM projects WHERE id = ?", (pid,))
    with _scope(tmp_path / "home"), pdb.connect_closing() as conn:
        assert pdb.get_project(conn, pid).name == "Original"


def test_connection_cannot_cross_scope_lifetime(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    owner = KanbanContext(home=tmp_path / "home", profile="owner", can_mutate=True)
    with kanban_scope(owner):
        old = pdb.connect()
        pid = pdb.create_project(old, name="Original")
    try:
        with kanban_scope(owner), pytest.raises(PermissionError):
            pdb.update_project(old, pid, name="Revived")
        with kanban_scope(owner), pytest.raises(PermissionError):
            old.execute("DELETE FROM projects WHERE id = ?", (pid,))
    finally:
        old.close()


@pytest.mark.parametrize("entry", ("execute", "raw_execute", "cursor", "raw_cursor"))
@pytest.mark.parametrize("read", ("fetchone", "fetchmany", "fetchall", "next", "list"))
def test_captured_cursor_cannot_read_after_scope_expires(tmp_path, entry, read):
    owner = KanbanContext(home=tmp_path / "home", profile="owner", can_mutate=True)
    with kanban_scope(owner):
        conn = pdb.connect()
        pdb.create_project(conn, name="Original")
        source = conn._raw if entry.startswith("raw_") else conn
        cursor = (source.execute("SELECT name FROM projects") if entry.endswith("execute")
                  else source.cursor().execute("SELECT name FROM projects"))
    try:
        with kanban_scope(owner), pytest.raises(PermissionError):
            if read == "next":
                next(cursor)
            elif read == "list":
                list(cursor)
            else:
                getattr(cursor, read)()
    finally:
        conn.close()


@pytest.mark.parametrize("entry", ("cursor", "raw_cursor"))
@pytest.mark.parametrize("operation", ("execute", "executemany", "executescript"))
def test_captured_cursor_cannot_execute_after_scope_expires(tmp_path, entry, operation):
    owner = KanbanContext(home=tmp_path / "home", profile="owner", can_mutate=True)
    with kanban_scope(owner):
        conn = pdb.connect()
        cursor = (conn._raw if entry == "raw_cursor" else conn).cursor()
    try:
        with kanban_scope(owner), pytest.raises(PermissionError):
            if operation == "executemany":
                cursor.executemany("SELECT 1", [])
            else:
                getattr(cursor, operation)("SELECT 1")
    finally:
        conn.close()


def test_project_cursor_preserves_rows_transaction_and_cleanup(tmp_path):
    owner = KanbanContext(home=tmp_path / "home", profile="owner", can_mutate=True)
    with kanban_scope(owner):
        conn = pdb.connect()
        pid = pdb.create_project(conn, name="Original")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM projects WHERE id = ?", (pid,))
        assert isinstance(cursor.fetchone(), sqlite3.Row)
        assert conn._raw.execute("SELECT name FROM projects WHERE id = ?", (pid,)).fetchone()["name"] == "Original"
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE projects SET name = 'Transient' WHERE id = ?", (pid,))
    conn.rollback()
    conn.close()
    with kanban_scope(owner), pdb.connect_closing() as reopened:
        assert pdb.get_project(reopened, pid).name == "Original"


def test_captured_cursor_rechecks_sidecar_and_home_before_fetch(tmp_path):
    home = tmp_path / "home"
    owner = KanbanContext(home=home, profile="owner", can_mutate=True)
    with kanban_scope(owner):
        conn = pdb.connect()
        pdb.create_project(conn, name="Original")
        cursor = conn.execute("SELECT name FROM projects")
        sidecar = home / "projects.db-journal"
        sidecar.symlink_to(tmp_path / "outside.db")
        with pytest.raises(PermissionError):
            cursor.fetchone()
        sidecar.unlink()
        assert cursor.fetchone()["name"] == "Original"
        with _scope(tmp_path / "other-home", can_mutate=True), pytest.raises(PermissionError):
            conn._raw.cursor()
        with _scope(tmp_path / "other-home", can_mutate=True), pytest.raises(PermissionError):
            cursor.connection.execute("SELECT name FROM projects")
        conn.close()


def test_readonly_open_does_not_migrate_schema(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    home.mkdir()
    with closing(sqlite3.connect(home / "projects.db")) as conn:
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, slug TEXT NOT NULL, name TEXT NOT NULL, created_at INTEGER NOT NULL)")
        conn.commit()
    with _scope(home), pytest.raises(PermissionError):
        pdb.connect()
    with closing(sqlite3.connect(home / "projects.db")) as conn:
        assert {row[1] for row in conn.execute("PRAGMA table_info(projects)")} == {"id", "slug", "name", "created_at"}


def test_paths_revoked_symlink_and_relative_are_refused(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    secret = root / ".ssh"
    secret.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    with _scope(tmp_path / "home", can_mutate=True), pdb.connect_closing() as conn:
        for bad in ("relative", str(outside), str(root / "escape"), str(secret)):
            with pytest.raises(ValueError):
                pdb.create_project(conn, name="Bad", primary_path=bad)
        path = root / "good"
        path.mkdir()
        pid = pdb.create_project(conn, name="Good", primary_path=str(path))
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(outside))
    with _scope(tmp_path / "home"), pytest.raises(PermissionError):
        projects.resolve_project(pid)


def test_folder_and_discovery_mutators_validate_paths(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    outside = tmp_path / "outside"
    outside.mkdir()
    with _scope(tmp_path / "home", can_mutate=True), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Good")
        with pytest.raises(ValueError):
            pdb.add_folder(conn, pid, str(outside))
        with pytest.raises(ValueError):
            pdb.record_discovered_repos(conn, [(str(outside), "Outside")])
        assert pdb.get_project(conn, pid).folders == []
        assert pdb.list_discovered_repos(conn) == []


def test_stored_path_symlink_drift_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    path = root / "project"
    path.mkdir()
    with _scope(tmp_path / "home", can_mutate=True), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Good", primary_path=str(path))
    path.rmdir()
    other = root / "other"
    other.mkdir()
    path.symlink_to(other, target_is_directory=True)
    with _scope(tmp_path / "home"), pytest.raises(PermissionError):
        projects.resolve_project(pid)


def test_db_and_sidecar_symlinks_are_refused(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "outside.db"
    (home / "projects.db").symlink_to(target)
    with _scope(home), pytest.raises(PermissionError):
        pdb.connect()
    (home / "projects.db").unlink()
    (home / "projects.db-wal").symlink_to(target)
    with _scope(home), pytest.raises(PermissionError):
        pdb.connect()
    (home / "projects.db-wal").unlink()
    (home / "projects.db-journal").symlink_to(target)
    with _scope(home), pytest.raises(PermissionError):
        pdb.connect()


def test_sidecar_symlink_added_after_open_blocks_mutation(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    with _scope(home, can_mutate=True), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Original")
        target = tmp_path / "outside.db"
        sidecar = home / "projects.db-shm"
        sidecar.unlink(missing_ok=True)
        sidecar.symlink_to(target)
        with pytest.raises(PermissionError):
            pdb.update_project(conn, pid, name="Escaped")
        sidecar.unlink()


def test_primary_active_archive_discovery_and_path_matching(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    outer, inner = root / "outer", root / "outer" / "inner"
    inner.mkdir(parents=True)
    with _scope(tmp_path / "home", can_mutate=True), pdb.connect_closing() as conn:
        first = pdb.create_project(conn, name="Outer", primary_path=str(outer))
        second = pdb.create_project(conn, name="Inner", primary_path=str(inner))
        assert pdb.project_for_path(conn, str(inner / "file.py")).id == second
        assert pdb.find_by_primary_path(conn, str(outer)).id == first
        pdb.set_active(conn, second)
        assert pdb.get_active_id(conn) == second
        assert pdb.branch_name_for(pdb.get_project(conn, second), "t_7", title="Fix UI!") == "inner/t_7-fix-ui"
        assert pdb.record_discovered_repos(conn, [(str(inner), "Repo")], policy_key="p1") == 1
        assert pdb.list_discovered_repos(conn)[0]["root"] == str(inner)
        assert pdb.reconcile_discovered_repos_policy(conn, "p2") is True
        assert pdb.list_discovered_repos(conn) == []
        assert pdb.archive_project(conn, second)
        with pytest.raises(ValueError):
            projects.resolve_project(second)
        assert [row["id"] for row in projects.list_projects()] == [first]
        assert {row["id"] for row in projects.list_projects(include_archived=True)} == {first, second}
        assert pdb.restore_project(conn, second)
        assert projects.resolve_project(second)[0] == second
        assert pdb.remove_folder(conn, second, str(inner))
        assert pdb.get_project(conn, second).primary_path is None
        assert pdb.delete_project(conn, second)
        assert pdb.get_project(conn, second) is None


def test_recreated_database_reinitializes_and_legacy_schema_migrates(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    with _scope(home, can_mutate=True), pdb.connect_closing() as conn:
        pdb.create_project(conn, name="First")
    (home / "projects.db").unlink()
    with _scope(home, can_mutate=True), pdb.connect_closing() as conn:
        assert pdb.create_project(conn, name="Second")
    for suffix in ("", "-wal", "-shm"):
        (home / f"projects.db{suffix}").unlink(missing_ok=True)
    with closing(sqlite3.connect(home / "projects.db")) as conn:
        conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, slug TEXT NOT NULL, name TEXT NOT NULL, created_at INTEGER NOT NULL, archived INTEGER DEFAULT 0)")
        conn.execute("INSERT INTO projects VALUES ('p_old', 'old', 'Old', 1, 0)")
        conn.commit()
    with _scope(home, can_mutate=True), pdb.connect_closing() as conn:
        assert pdb.get_project(conn, "p_old").name == "Old"
        assert pdb.create_project(conn, name="New", primary_path=str(root))
