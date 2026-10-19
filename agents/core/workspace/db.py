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

Private files whatever the umask (review OPS2-05). ``sqlite3`` would create the database
``0644 & ~umask`` — readable by every local user under the default ``0022`` — and its
``-wal``/``-shm`` files copy the database's mode. :func:`connect` therefore creates the
file itself, empty and ``0600`` (an empty file is an empty database to SQLite), and the
first connect of each process makes everything already under ``<data>/business`` private
(:func:`secure_storage`): a restore, a copy or an older build may have left it open.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
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

# v2 (review NWS-20, UX-23): what a report run's email delivery is doing, and the machine
# reason of its error_code. ``delivery_state`` is NULL for a run with no approved delivery,
# 'pending' from the moment the run is stored as succeeded until the mail server answered,
# then 'sent' or 'failed' — a live run page polls while it is 'pending'. ``error_reason``
# qualifies ``error_code`` the way an API error body's ``reason`` does (``model_unreachable``
# for ``model_unavailable``, ``timeout`` for ``smtp_failed`` …); NULL when nothing more is
# known. ADD COLUMN keeps every existing row (both read NULL) and is a constant-time change.
_SCHEMA_V2 = """
ALTER TABLE report_runs ADD COLUMN delivery_state TEXT
  CHECK (delivery_state IS NULL OR delivery_state IN ('pending','sent','failed'));
ALTER TABLE report_runs ADD COLUMN error_reason TEXT;
CREATE INDEX idx_report_runs_delivery_pending ON report_runs(delivery_state, finished_at);
"""

# v3 (review R4-07): how many approved recipients a run's delivery was addressed to, written
# with ``delivery_state='pending'`` in the statement that stores the run. A delivery its
# sender never settled (a hub killed mid-send) is audited by the restart sweep with the count
# it was really sent to, not with whatever the report's approved list holds by then. NULL for
# a run with no delivery and for every run stored before schema 3.
_SCHEMA_V3 = """
ALTER TABLE report_runs ADD COLUMN delivery_attempted INTEGER;
"""

#: Ordered (version, script) pairs; a database at user_version N runs every script > N.
MIGRATIONS: list[tuple[int, str]] = [(1, _SCHEMA_V1), (2, _SCHEMA_V2), (3, _SCHEMA_V3)]

_migrate_lock = threading.Lock()

#: Modes of the workspace's own files and directories (review OPS2-05).
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
#: The group and other permission bits :func:`secure_storage` removes.
_OPEN_BITS = 0o077
#: Workspace directories this process already made private (one pass per process each).
_secured: set[str] = set()
_secured_lock = threading.Lock()
#: How many names of other entries a "not the workspace's own folder" warning shows.
_FOREIGN_SHOWN = 3
#: What ``documents`` writes inside ``files/``: ``<id>.bin`` (``file_path``), ``.upload-….tmp``
#: (``_write_temp``) and ``.deleted-<id>.tmp`` (``_detach_file``).
_OWN_STORED_FILE = re.compile(r"\d+\.bin|\.upload-[^/]+\.tmp|\.deleted-\d+\.tmp")


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


def _create_private_db(path: Path) -> None:
    """Create *path* empty with mode 0600 unless it exists (SQLite reads it as empty).

    ``sqlite3.connect`` would create it ``0644 & ~umask``; SQLite then gives the ``-wal``
    and ``-shm`` files the database's own mode, so they are private too.
    """
    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(path, flags, PRIVATE_FILE_MODE)
    except FileExistsError:
        return
    os.close(fd)
    with suppress(OSError):   # the umask can only have narrowed 0600, never widened it
        os.chmod(path, PRIVATE_FILE_MODE)


def _private_mode(mode: int) -> int | None:
    """*mode* without its group/other bits, or ``None`` when it has none."""
    permissions = stat.S_IMODE(mode)
    return permissions & ~_OPEN_BITS if permissions & _OPEN_BITS else None


def _storage_root(directory: Path) -> Path | None:
    """The folder :func:`secure_storage` walks for *directory*, or ``None`` for none.

    ``<data>/business`` may be a symlink to a folder elsewhere (another disk): the
    workspace's files live there, so that folder is the one walked — resolved once, like the
    hub's root guard resolves it (review REV-POLISH-02); below it no symlink is followed. A
    link to a folder that holds *directory*'s own parent — ``/``, the data root or a folder
    above it — would reach far more than the workspace's files, so it is not walked and one
    WARNING says so; a link that leads to no folder is not walked either.
    """
    if not directory.is_symlink():
        return directory if directory.is_dir() else None
    try:
        real = directory.resolve(strict=True)
        parent = directory.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not real.is_dir():
        return None
    if parent.is_relative_to(real):
        logger.warning(
            "Nerva Workspace: %s is a link to %s, which holds the hub's data directory, so the "
            "modes under it are not checked — link business/ to a folder of its own "
            "(PILOT_GUIDE §13)", directory, real)
        return None
    return real


def own_entry(name: str) -> bool:
    """Whether *name*, directly under ``business/``, is one of the workspace's own entries.

    The database and its ``-wal``/``-shm``/``-journal`` files, ``files/`` (the stored
    originals), ``secrets.enc`` with its ``.salt``/``.key``/``.<random>.tmp`` siblings, and
    ``setup-code.txt`` with the ``.setup-code.txt.<random>`` file it is written through
    (``config.create_private_file``) — the names the modules that write them use.
    """
    return (name in (DB_FILE, config.FILES_DIRNAME, config.SECRETS_FILE, config.SETUP_CODE_FILE)
            or name.startswith((f"{DB_FILE}-", f"{config.SECRETS_FILE}.",
                                f".{config.SETUP_CODE_FILE}.")))


def _own_stored_file(name: str) -> bool:
    """Whether *name*, directly under ``files/``, is a file ``documents`` writes there."""
    return _OWN_STORED_FILE.fullmatch(name) is not None


def _foreign_names(folder: Path, own: Callable[[str], bool]) -> list[str]:
    """The entries of *folder* that are not the workspace's (*own* judges each name)."""
    return sorted(name for name in os.listdir(folder) if not own(name))


def secure_storage(directory: Path) -> list[Path]:
    """Remove group/other access from *directory* and everything under it; returns what changed.

    *directory* is the workspace's own (``<data>/business``: the database and its
    ``-wal``/``-shm``, ``files/`` and the stored documents, ``secrets.enc`` with its key and
    salt, ``setup-code.txt``), so nothing else is touched. When *directory* itself is a link
    to a folder, that folder is walked (:func:`_storage_root`) only while it is the
    workspace's own — every entry in it is one of :func:`own_entry`'s names. A link to a
    folder that holds other things as well (``business`` → ``/mnt/disc2``, a mount root
    with other data) gets one WARNING naming that folder, and only the workspace's own
    entries there are made private (in ``files/`` only the files the workspace writes, when
    it holds others too); the folder itself and every other entry keep their modes. Below
    the folder symlinks are never followed nor changed. A change is logged once, as a
    WARNING; a chmod the system refuses (files owned by another user — a command run as
    root) is logged once too, and never fails the caller.

    Why not "the folder holds ``workspace.db``": the first connect creates the database in
    the folder before this runs, so after one start every shared folder would hold it.
    """
    changed: list[Path] = []
    refused: list[tuple[Path, str]] = []

    def tighten(path: Path) -> None:
        try:
            info = path.lstat()
        except OSError:
            return
        if stat.S_ISLNK(info.st_mode):
            return
        mode = _private_mode(info.st_mode)
        if mode is None:
            return
        try:
            os.chmod(path, mode)
        except OSError as exc:
            refused.append((path, type(exc).__name__))
            return
        changed.append(path)

    def tighten_tree(top: Path) -> None:
        tighten(top)
        for parent, dirnames, filenames in os.walk(top, followlinks=False):
            base = Path(parent)
            for name in [*dirnames, *filenames]:
                tighten(base / name)

    root = _storage_root(directory)
    if root is None:
        return changed
    foreign = [] if root == directory else _foreign_names(root, own_entry)
    if not foreign:
        tighten_tree(root)
    else:
        logger.warning(
            "Nerva Workspace: %s is a link to %s, which also holds %d %s not the "
            "workspace's (%s), so only the workspace's own files there are made private and "
            "nothing else in that folder is changed — link business/ to a folder of its own "
            "(PILOT_GUIDE §13)", directory, root, len(foreign),
            "entry that is" if len(foreign) == 1 else "entries that are",
            ", ".join(foreign[:_FOREIGN_SHOWN]) + (", …" if len(foreign) > _FOREIGN_SHOWN else ""))
        _tighten_own_entries(root, tighten, tighten_tree)
    where = directory if root == directory else f"{directory} → {root}"
    if changed:
        logger.warning(
            "Nerva Workspace: %d file(s) or folder(s) under %s could be read by other users "
            "(a restore or a copy made with a permissive umask); they are private now — "
            "files 0600, folders 0700", len(changed), where)
    if refused:
        path, reason = refused[0]
        fix = ("make the service's user their owner and remove the access of others — "
               "chown -R jarvis:jarvis and chmod -R go-rwx" if not foreign else
               "make the service's user the owner of the workspace's own entries there "
               "(workspace.db*, files/, secrets.enc*, setup-code.txt) and remove the access of "
               "others with chown jarvis:jarvis and chmod go-rwx on those entries only, not on "
               "the whole folder")
        logger.warning(
            "Nerva Workspace: %d file(s) or folder(s) under %s can be read by other users and "
            "this process may not change that (%s on %s): %s (PILOT_GUIDE §14, §19)",
            len(refused), where, reason, path, fix)
    return changed


def _tighten_own_entries(root: Path, tighten: Callable[[Path], None],
                         tighten_tree: Callable[[Path], None]) -> None:
    """In a folder shared with other data: only the workspace's own entries, never the rest.

    ``files/`` is walked in full while it holds only what ``documents`` writes; otherwise
    just those files in it are tightened and the folder itself is left as it is.
    """
    for name in sorted(os.listdir(root)):
        if not own_entry(name):
            continue
        path = root / name
        if name == config.FILES_DIRNAME and path.is_dir() and not path.is_symlink():
            if not _foreign_names(path, _own_stored_file):
                tighten_tree(path)
                continue
            for stored in sorted(os.listdir(path)):
                if _own_stored_file(stored):
                    tighten(path / stored)
            continue
        tighten(path)


def _secure_once(directory: Path) -> None:
    """:func:`secure_storage` the first time this process opens *directory*'s database."""
    key = str(directory)
    if key in _secured:
        return
    with _secured_lock:
        if key in _secured:
            return
        try:
            secure_storage(directory)
        except OSError as exc:   # a walk that cannot read a folder must not stop the hub
            logger.warning("Nerva Workspace: the modes under %s could not be checked (%s)",
                           directory, type(exc).__name__)
        _secured.add(key)


def connect() -> sqlite3.Connection:
    """Open the workspace database (WAL, foreign keys, 5 s busy timeout, Row factory).

    The schema is ensured on every connect: one ``PRAGMA user_version`` read when the
    database is current, a migration otherwise. A new database is created ``0600`` and
    the first connect of a process makes the workspace's files private (:func:`secure_storage`).
    """
    path = db_path()
    _create_private_db(path)
    _secure_once(path.parent)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
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
