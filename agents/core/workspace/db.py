"""The workspace database: one SQLite file holding the whole §4 schema.

Why one file and one owner. Every slice (identity, documents, chat, reports,
approvals) reads across the others' tables — department isolation, stats, the delete
guard of a department — so the schema is defined here, complete, and migrated through
``PRAGMA user_version``. Later slices never change it; they only query it.

Connections run in autocommit mode (``isolation_level=None``) so Python's sqlite3
module never opens an implicit transaction behind the code's back. Writes are grouped
explicitly with :func:`tx` (``BEGIN IMMEDIATE`` takes the write lock up front, which
serializes the audit hash chain and the compare-and-set claims). Rules every caller
follows: never hold a transaction across an ``await`` of the model, SMTP, extraction
or any I/O; writes that must survive an error response (failed logins, throttling
rows, failed approvals) commit in their own ``tx`` before the error is raised.

Time is read through :func:`now` everywhere in the workspace so tests can move the
clock with ``monkeypatch.setattr(db, "now", ...)`` instead of patching ``time.time``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from agents.core.paths import data_path
from agents.core.workspace import config
from agents.core.workspace.errors import WorkspaceError

logger = logging.getLogger("nerva.workspace.db")

DB_FILE = "workspace.db"

# AUTOINCREMENT on every table whose ids leave the row — in audit target_ids, approval
# payloads, notification links, files/<id>.bin, ids a request holds across an await: SQLite
# otherwise hands the id of the newest deleted row to the next insert, so one id could name
# two objects over time (another department's, even). The slices' own (id, created_at)
# guards stay as defence in depth; tables whose ids never leave the row keep plain rowids.
_SCHEMA_V1 = """
CREATE TABLE org (id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT NOT NULL,
  default_locale TEXT NOT NULL DEFAULT 'ro' CHECK (default_locale IN ('ro','en')),
  model_policy TEXT NOT NULL DEFAULT 'local_only' CHECK (model_policy IN ('local_only','allow_cloud')),
  settings_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);

CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '', assistant_instructions TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);

CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','approver','member')),
  status TEXT NOT NULL CHECK (status IN ('invited','active','disabled')),
  password_hash TEXT, locale TEXT NOT NULL DEFAULT 'ro' CHECK (locale IN ('ro','en')),
  theme TEXT NOT NULL DEFAULT 'light' CHECK (theme IN ('light','dark','system')),
  last_login_at REAL, created_at REAL NOT NULL);

CREATE TABLE user_departments (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, department_id));

CREATE TABLE invites (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, purpose TEXT NOT NULL CHECK (purpose IN ('invite','reset')),
  created_by INTEGER REFERENCES users(id), created_at REAL NOT NULL, expires_at REAL NOT NULL,
  used_at REAL);

CREATE TABLE sessions (id_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, csrf_token TEXT NOT NULL, created_at REAL NOT NULL, last_seen_at REAL NOT NULL,
  expires_at REAL NOT NULL, ip TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '',
  via TEXT NOT NULL DEFAULT 'password' CHECK (via IN ('password','invite','setup','sso')),
  sso_email TEXT, revoked_at REAL);

CREATE TABLE login_attempts (id INTEGER PRIMARY KEY, ip TEXT NOT NULL, email TEXT NOT NULL,
  ok INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('login','setup','invite_lookup','sso')),
  ts REAL NOT NULL);

CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER REFERENCES departments(id),
  visibility TEXT NOT NULL DEFAULT 'department' CHECK (visibility IN ('department','company')),
  title TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL, uploader_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('processing','ready','failed')), error TEXT,
  page_count INTEGER, chunk_count INTEGER NOT NULL DEFAULT 0, char_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  CHECK (visibility = 'company' OR department_id IS NOT NULL));

CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id)
  ON DELETE CASCADE, ord INTEGER NOT NULL, page INTEGER, text TEXT NOT NULL, embedding BLOB);

CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');

CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, department_id INTEGER NOT NULL REFERENCES departments(id), title TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);

CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL
  REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('pending','complete','error')),
  error_code TEXT, model TEXT, route TEXT, locality TEXT, latency_ms INTEGER, feedback INTEGER,
  feedback_note TEXT, created_at REAL NOT NULL);

CREATE TABLE reports (id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER NOT NULL REFERENCES departments(id),
  name TEXT NOT NULL, instructions TEXT NOT NULL, document_ids_json TEXT NOT NULL DEFAULT '[]',
  schedule_kind TEXT NOT NULL DEFAULT 'manual' CHECK (schedule_kind IN ('manual','daily','weekly')),
  schedule_time TEXT, schedule_weekday INTEGER, timezone TEXT NOT NULL DEFAULT 'Europe/Bucharest',
  delivery_emails_json TEXT NOT NULL DEFAULT '[]', delivery_status TEXT NOT NULL DEFAULT 'none'
  CHECK (delivery_status IN ('none','pending','approved','rejected')),
  delivery_approved_json TEXT NOT NULL DEFAULT '[]', delivery_approval_id INTEGER,
  owner_id INTEGER REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1,
  next_run_at REAL, last_run_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL);

CREATE TABLE report_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL REFERENCES reports(id)
  ON DELETE CASCADE, status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
  trigger TEXT NOT NULL CHECK (trigger IN ('manual','schedule')),
  triggered_by INTEGER REFERENCES users(id),
  content_md TEXT, citations_json TEXT NOT NULL DEFAULT '[]', model TEXT, route TEXT, locality TEXT,
  error_code TEXT, error TEXT, shared_company INTEGER NOT NULL DEFAULT 0,
  delivered_to_json TEXT NOT NULL DEFAULT '[]', started_at REAL, finished_at REAL,
  created_at REAL NOT NULL);

CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
  department_id INTEGER REFERENCES departments(id),
  requester_id INTEGER NOT NULL REFERENCES users(id), summary TEXT NOT NULL, payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','executing','approved','rejected','cancelled',
    'expired','failed')),
  decided_by INTEGER REFERENCES users(id), decided_at REAL, decision_note TEXT, result_json TEXT,
  error_code TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL);

CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id)
  ON DELETE CASCADE, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, read_at REAL);

CREATE TABLE audit (id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor_user_id INTEGER,
  actor_email TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '', department_id INTEGER, ip TEXT NOT NULL DEFAULT '',
  details_json TEXT NOT NULL DEFAULT '{}', prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  key_fp TEXT NOT NULL);

CREATE INDEX idx_user_departments_department ON user_departments(department_id);
CREATE INDEX idx_invites_user ON invites(user_id);
CREATE INDEX idx_invites_created_by ON invites(created_by);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_login_attempts_email_ts ON login_attempts(email, ts);
CREATE INDEX idx_login_attempts_ip_ts ON login_attempts(ip, ts);
CREATE INDEX idx_login_attempts_ts ON login_attempts(ts);
CREATE INDEX idx_documents_department ON documents(department_id);
CREATE INDEX idx_documents_uploader ON documents(uploader_id);
CREATE INDEX idx_chunks_document ON chunks(document_id, ord);
CREATE INDEX idx_conversations_user ON conversations(user_id, updated_at);
CREATE INDEX idx_conversations_department ON conversations(department_id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);
CREATE INDEX idx_reports_department ON reports(department_id);
CREATE INDEX idx_reports_owner ON reports(owner_id);
CREATE INDEX idx_reports_active_next ON reports(active, next_run_at);
CREATE INDEX idx_report_runs_report ON report_runs(report_id, created_at);
CREATE INDEX idx_report_runs_triggered_by ON report_runs(triggered_by);
CREATE INDEX idx_approvals_department ON approvals(department_id);
CREATE INDEX idx_approvals_requester ON approvals(requester_id);
CREATE INDEX idx_approvals_decided_by ON approvals(decided_by);
CREATE INDEX idx_approvals_status_expires ON approvals(status, expires_at);
CREATE INDEX idx_notifications_user_read ON notifications(user_id, read_at);
CREATE INDEX idx_audit_ts ON audit(ts);
CREATE INDEX idx_audit_actor ON audit(actor_user_id);
CREATE INDEX idx_audit_action ON audit(action);
"""

#: Ordered (version, script) pairs; a database at user_version N runs every script > N.
MIGRATIONS: list[tuple[int, str]] = [(1, _SCHEMA_V1)]

_migrate_lock = threading.Lock()


def now() -> float:
    """UTC epoch seconds — the workspace's single clock (patched in tests)."""
    return time.time()


def schema_version() -> int:
    """The version a fully migrated database reports in ``PRAGMA user_version``."""
    return MIGRATIONS[-1][0]


def db_path() -> Path:
    """``<data>/business/workspace.db`` (resolved at call time; see ``config.DATA_DIRNAME``)."""
    return config.workspace_dir() / DB_FILE


def existing_db_path() -> Path:
    """Where :func:`db_path` points, without creating the directory (it may not exist)."""
    return data_path(config.DATA_DIRNAME, DB_FILE)


def connect_read_only(path: Path) -> sqlite3.Connection:
    """Open an existing database read-only: no migration, no write, no new file.

    Without a ``-wal`` file (no live writer: the service is stopped and checkpointed) it is
    opened ``immutable``, so not even ``-wal``/``-shm`` files are created — which a command
    run as another user (root) would leave behind, unwritable for the service. With one
    (the hub is running), it reads through the live WAL as any reader does.
    """
    wal = path.with_name(f"{path.name}-wal")
    mode = "mode=ro" if wal.exists() else "mode=ro&immutable=1"
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?{mode}", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _split_statements(script: str) -> list[str]:
    """Split a migration script into complete statements (triggers stay whole)."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def migrate(conn: sqlite3.Connection) -> int:
    """Bring *conn*'s database to :func:`schema_version`; returns the version reached.

    Each pending script runs in one ``BEGIN IMMEDIATE`` transaction together with its
    ``user_version`` bump, so a crash leaves the database at a clean version and two
    processes racing to migrate cannot both apply a script (the loser re-reads the
    version under the write lock and finds nothing to do). ``executescript`` is avoided
    because it commits on its own.
    """
    current = _user_version(conn)
    target = schema_version()
    if current > target:
        logger.warning("workspace database is at schema %s, newer than this code (%s)",
                       current, target)
        return current
    for version, script in MIGRATIONS:
        if version <= current:
            continue
        with _migrate_lock, tx(conn):
            if _user_version(conn) >= version:
                continue
            for statement in _split_statements(script):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {int(version)}")
        logger.info("workspace database migrated to schema %s", version)
        current = version
    return current


def connect() -> sqlite3.Connection:
    """Open the workspace database (WAL, foreign keys, 5 s busy timeout, Row factory).

    The schema is ensured on every connect: one ``PRAGMA user_version`` read when the
    database is current, a migration otherwise.
    """
    conn = sqlite3.connect(str(db_path()), check_same_thread=False, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        if _user_version(conn) < schema_version():
            migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; ``ROLLBACK`` on any exception.

    Nested use joins the outer transaction (a no-op when ``conn.in_transaction``), so
    helpers that write can be called both standalone and from inside a caller's tx.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, closed afterwards.

    It refuses with ``404 workspace_disabled`` before touching the disk, so a request
    to a disabled workspace never creates the database whatever order a route declares
    its dependencies in. A transaction still open at teardown (a handler bug) is
    rolled back rather than committed.
    """
    if not config.enabled():
        raise WorkspaceError("workspace_disabled", "Nerva Workspace is not enabled", 404)
    conn = connect()
    try:
        yield conn
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
