"""The workspace schema, its migrations and the transaction rules (spec §4, §5 db.py)."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import db, make_department, seed_org, ws  # noqa: F401

TABLES = {
    "org", "departments", "users", "user_departments", "invites", "sessions", "login_attempts",
    "documents", "chunks", "chunks_fts", "conversations", "messages", "reports", "report_runs",
    "approvals", "notifications", "audit",
}
REQUIRED_INDEXES = {
    # every foreign key
    ("user_departments", "department_id"), ("invites", "user_id"), ("invites", "created_by"),
    ("sessions", "user_id"), ("documents", "department_id"), ("documents", "uploader_id"),
    ("chunks", "document_id"), ("conversations", "user_id"), ("conversations", "department_id"),
    ("messages", "conversation_id"), ("reports", "department_id"), ("reports", "owner_id"),
    ("report_runs", "report_id"), ("report_runs", "triggered_by"),
    ("approvals", "department_id"), ("approvals", "requester_id"), ("approvals", "decided_by"),
    ("notifications", "user_id"),
    # the named composite ones (leading column checked here, full list below)
    ("login_attempts", "email"), ("login_attempts", "ip"), ("approvals", "status"),
    ("audit", "ts"), ("reports", "active"),
}
COMPOSITES = {
    ("login_attempts", ("email", "ts")), ("login_attempts", ("ip", "ts")),
    ("notifications", ("user_id", "read_at")), ("approvals", ("status", "expires_at")),
    ("report_runs", ("report_id", "created_at")), ("messages", ("conversation_id", "id")),
    ("reports", ("active", "next_run_at")),
}


def _index_columns(conn: sqlite3.Connection) -> set[tuple[str, tuple[str, ...]]]:
    found = set()
    for table in TABLES - {"chunks_fts"}:
        for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
            cols = tuple(row["name"] for row in conn.execute(f"PRAGMA index_info({index['name']})"))
            found.add((table, cols))
    return found


def test_connect_configures_the_connection(ws):
    conn = db()
    assert conn.isolation_level is None, "autocommit: no implicit transactions"
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert workspace_db.db_path() == ws.data_dir / "workspace" / "workspace.db"
    conn.close()


def test_full_schema_exists_for_every_slice(ws):
    conn = db()
    names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= TABLES
    triggers = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"chunks_ai", "chunks_ad", "chunks_au"} <= triggers
    indexed = _index_columns(conn)
    leading = {(table, cols[0]) for table, cols in indexed}
    assert leading >= REQUIRED_INDEXES, REQUIRED_INDEXES - leading
    assert indexed >= COMPOSITES, COMPOSITES - indexed
    assert conn.execute("PRAGMA user_version").fetchone()[0] == workspace_db.schema_version()
    conn.close()


def test_schema_columns_match_the_contract(ws):
    conn = db()

    def columns(table):
        return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]

    assert columns("sessions") == ["id_hash", "user_id", "csrf_token", "created_at", "last_seen_at",
                                   "expires_at", "ip", "user_agent", "via", "sso_email", "revoked_at"]
    assert columns("audit") == ["id", "ts", "actor_user_id", "actor_email", "action", "target_type",
                                "target_id", "department_id", "ip", "details_json", "prev_hash",
                                "hash", "key_fp"]
    assert "delivery_approved_json" in columns("reports")
    assert "delivered_to_json" in columns("report_runs")
    assert "feedback_note" in columns("messages")
    conn.close()


def test_connect_twice_does_not_migrate_again(ws, monkeypatch):
    db().close()

    def boom(conn):
        raise AssertionError("migrate must not run on a current database")

    monkeypatch.setattr(workspace_db, "migrate", boom)
    conn = db()
    assert conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 0
    conn.close()


def test_migrate_is_idempotent_and_applies_new_versions_once(ws, monkeypatch):
    conn = db()
    version = workspace_db.schema_version()
    assert workspace_db.migrate(conn) == version
    assert workspace_db.migrate(conn) == version
    extra = (version + 1, "CREATE TABLE migration_probe (x INTEGER);\n"
                          "INSERT INTO migration_probe (x) VALUES (1);\n")
    monkeypatch.setattr(workspace_db, "MIGRATIONS", [*workspace_db.MIGRATIONS, extra])
    assert workspace_db.migrate(conn) == version + 1
    assert workspace_db.migrate(conn) == version + 1
    assert conn.execute("SELECT COUNT(*) FROM migration_probe").fetchone()[0] == 1
    second = db()
    assert second.execute("PRAGMA user_version").fetchone()[0] == version + 1
    second.close()
    conn.close()


def test_failed_migration_leaves_the_previous_version(ws, monkeypatch):
    conn = db()
    version = workspace_db.schema_version()
    broken = (version + 1, "CREATE TABLE half_done (x INTEGER);\nTHIS IS NOT SQL;\n")
    monkeypatch.setattr(workspace_db, "MIGRATIONS", [*workspace_db.MIGRATIONS, broken])
    with pytest.raises(sqlite3.OperationalError):
        workspace_db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='half_done'").fetchone() is None
    assert not conn.in_transaction
    conn.close()


def test_newer_database_is_left_alone_with_a_warning(ws, caplog):
    conn = db()
    conn.execute(f"PRAGMA user_version = {workspace_db.schema_version() + 5}")
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.db"):
        assert workspace_db.migrate(conn) == workspace_db.schema_version() + 5
    assert "newer" in caplog.text
    conn.close()


def test_fts_index_follows_chunks_including_cascade_and_diacritics(ws):
    conn = db()
    seed_org(conn)
    dept = make_department(conn, "Vânzări")
    with workspace_db.tx(conn):
        doc_id = conn.execute(
            "INSERT INTO documents (department_id, title, filename, mime, size_bytes, sha256, status, "
            "created_at, updated_at) VALUES (?, 't', 'f.txt', 'text/plain', 1, 'x', 'ready', 0, 0)",
            (dept,),
        ).lastrowid
        chunk_id = conn.execute(
            "INSERT INTO chunks (document_id, ord, text) VALUES (?, 0, 'Politica de vânzări și ședințe')",
            (doc_id,),
        ).lastrowid

    def hits(term):
        return [row[0] for row in conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?", (term,))]

    assert hits("vanzari") == [chunk_id], "remove_diacritics folds ă/â"
    assert hits("sedinte") == [chunk_id], "and ș/ț"
    with workspace_db.tx(conn):
        conn.execute("UPDATE chunks SET text = 'Bugetul anual' WHERE id = ?", (chunk_id,))
    assert hits("vanzari") == []
    assert hits("bugetul") == [chunk_id]
    with workspace_db.tx(conn):
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert hits("bugetul") == [], "ON DELETE CASCADE fires the ad trigger"
    conn.close()


def test_department_documents_need_a_department(ws):
    conn = db()
    insert = ("INSERT INTO documents (department_id, visibility, title, filename, mime, size_bytes, "
              "sha256, status, created_at, updated_at) VALUES (?, ?, 't', 'f', 'm', 1, 's', 'ready', 0, 0)")
    with pytest.raises(sqlite3.IntegrityError), workspace_db.tx(conn):
        conn.execute(insert, (None, "department"))
    with workspace_db.tx(conn):
        conn.execute(insert, (None, "company"))
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_foreign_keys_are_enforced(ws):
    conn = db()
    with pytest.raises(sqlite3.IntegrityError), workspace_db.tx(conn):
        conn.execute("INSERT INTO user_departments (user_id, department_id) VALUES (99, 98)")
    conn.close()


def test_tx_commits_and_rolls_back(ws):
    conn = db()
    with workspace_db.tx(conn):
        assert conn.in_transaction
        seed_org(conn)  # helper's own tx joins this one
    assert not conn.in_transaction
    with pytest.raises(RuntimeError), workspace_db.tx(conn):
        conn.execute("UPDATE org SET name = 'Changed'")
        raise RuntimeError("boom")
    assert not conn.in_transaction
    assert conn.execute("SELECT name FROM org").fetchone()[0] == "Acme"
    conn.close()


def test_nested_tx_joins_the_outer_one(ws):
    conn = db()
    seed_org(conn)
    with pytest.raises(ValueError), workspace_db.tx(conn):
        conn.execute("UPDATE org SET name = 'Outer'")
        with workspace_db.tx(conn):
            conn.execute("UPDATE org SET name = 'Inner'")
        raise ValueError("outer fails after the inner block finished")
    assert conn.execute("SELECT name FROM org").fetchone()[0] == "Acme", "inner did not commit alone"
    conn.close()


def test_tx_takes_the_write_lock_up_front(ws):
    first, second = db(), db()
    second.execute("PRAGMA busy_timeout = 0")
    with workspace_db.tx(first), pytest.raises(sqlite3.OperationalError, match="locked"):
        second.execute("BEGIN IMMEDIATE")
    second.execute("BEGIN IMMEDIATE")
    second.execute("ROLLBACK")
    first.close()
    second.close()


def test_get_db_refuses_when_disabled_without_creating_the_database(ws, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    generator = workspace_db.get_db()
    with pytest.raises(WorkspaceError) as caught:
        next(generator)
    assert (caught.value.status, caught.value.code) == (404, "workspace_disabled")
    assert not (ws.data_dir / "workspace" / "workspace.db").exists()


def test_get_db_rolls_back_a_leftover_transaction_and_closes(ws):
    seed = db()
    seed_org(seed)
    seed.close()
    generator = workspace_db.get_db()
    conn = next(generator)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE org SET name = 'Uncommitted'")
    with pytest.raises(StopIteration):
        next(generator)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    check = db()
    assert check.execute("SELECT name FROM org").fetchone()[0] == "Acme"
    check.close()
