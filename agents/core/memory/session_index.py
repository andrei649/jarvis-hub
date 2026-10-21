"""session_index.py — the CJK-aware FTS5 index over session transcripts (H574).

``session_search`` used to answer every query with a linear scan of the ``<sid>.json``
snapshots, capped at the 200 newest sessions and a 5-second deadline: anything older was
unreachable, and a search slowed down as history grew. Hermes answers the same query from
an FTS5 index over all of its history (``state.db`` messages FTS, with a ``unicode61`` +
CJK-bigram tokenizer). This module is Nerva's equivalent:

* ``<data root>/session_index.db`` holds one row per turn — the session file's stem, the
  session id from the payload, the turn index, role, timestamp, agent, an image-derived
  flag and the turn's content (the first :data:`MAX_TURN_CHARS`, as the scan reads) —
  with an FTS5 table over the turn's :func:`cjk_fts.index_text` segmentation (CJK runs as
  unigrams + bigrams, everything else as ``unicode61`` words). Python's ``sqlite3``
  cannot register a C tokenizer, so the segmentation happens on both sides in Python.
* :func:`index_session` keeps a session's rows in step when ``save_memory`` (or a rewind)
  writes its snapshot; :func:`forget_sessions` drops them in the same operation that
  removes a session (session delete, retention, forget/purge).
* :func:`sync` is the reindex migration, run whenever the index is opened for a search:
  a :data:`cjk_fts.SEGMENTER_VERSION` (or :data:`SCHEMA_VERSION`) change rebuilds the
  index, a snapshot whose ``(mtime_ns, size)`` differs from what was indexed (or that was
  never indexed) is (re)indexed, and the rows of a snapshot that is gone are dropped. So
  even a removal that bypassed every hook (a file deleted by hand, a purge resetting a
  snapshot to ``{}``) cannot be found through the index.

The index is a derived cache: when it is *corrupt* it is rebuilt from the snapshots;
when it is merely busy (another connection holds its lock) or this SQLite has no FTS5,
:func:`open_index` raises :class:`IndexUnavailable` and ``session_search`` falls back to
its bounded scan. A lock is never mistaken for corruption, so a live index is never
deleted under a running sync.

Erasure: a plain FTS5 DELETE leaves the deleted terms in the segment b-tree
(``turn_fts_data``) until segments merge, and neither ``PRAGMA secure_delete`` nor VACUUM
merges them. The index turns on FTS5 ``secure-delete`` (SQLite 3.44+), so a DELETE
removes the entries themselves; where that option is missing, every transaction that
dropped rows ends with ``optimize``. With ``PRAGMA secure_delete`` the freed pages are
zeroed too, so a forgotten session's words are gone from the file, not only unreachable.
:func:`clear` (forget all memory) removes the file outright.

Cost on the save path: :func:`index_session` is incremental. Each session's record keeps
the number of turns indexed and a digest of their indexed fields; when a save only
appended turns (the digest of that prefix is unchanged) only the new turns are segmented
and inserted, and the whole session is re-read only after a rewind or a replace. The save
hook opens the index with a short busy timeout (:data:`HOOK_TIMEOUT`) and skips on a busy
index (:func:`sync` repairs the miss by ``(mtime_ns, size)``), and ``persistence`` calls
it after the snapshot and checkpoint locks are released. :func:`sync` commits in small
batches and takes a deadline; what it did not reach is returned as ``pending`` for the
caller's bounded scan.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from agents.core.memory import cjk_fts
from agents.core.memory.private_db import PRIVATE_MODE, ensure_private
from agents.core.session_files import is_session_snapshot_payload, is_session_stem
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.session_index")

INDEX_NAME = "session_index.db"
#: Stems a removal could not drop (busy index), dropped by the next :func:`open_index`.
PENDING_NAME = "session_index.forget"
#: The FTS module the index uses; a test points it at a missing module to exercise the
#: no-FTS5 fallback.
FTS5_MODULE = "fts5"
#: Bumped when the tables change shape; a stored index with another value is rebuilt.
SCHEMA_VERSION = "2"
#: The turn prefix the index stores and matches — the scan reads the same prefix.
MAX_TURN_CHARS = 20_000
#: A snapshot larger than this is recorded as skipped, never parsed.
MAX_INDEX_SNAPSHOT_BYTES = 64_000_000
#: Busy timeout (seconds) for a search or a removal opening the index.
OPEN_TIMEOUT = 5.0
#: Busy timeout (seconds) for the save hook: a busy index is skipped, never waited on.
HOOK_TIMEOUT = 0.2
#: :func:`sync` commits at least this often (seconds), so no writer holds the lock long.
BATCH_SECONDS = 0.2
#: Called with each SQL statement the index runs, when set (tests prove MATCH ran).
TRACE: Callable[[str], None] | None = None

_SIDECARS = ("-wal", "-shm", "-journal")
_BUSY_CODES = frozenset({5, 6})         # SQLITE_BUSY, SQLITE_LOCKED (primary codes)
_CORRUPT_CODES = frozenset({11, 26})    # SQLITE_CORRUPT, SQLITE_NOTADB
_CORRUPT_TEXT = ("malformed", "file format", "not a database", "corrupt")


class IndexUnavailable(Exception):
    """The index cannot answer now: no FTS5, a busy lock, or a file that could not be
    replaced. ``busy`` says it was the lock; the caller falls back or skips, and nothing
    is deleted."""

    def __init__(self, message: str, *, busy: bool = False) -> None:
        super().__init__(message)
        self.busy = busy


class _IndexConnection(sqlite3.Connection):
    """A connection that knows whether its FTS table removes deleted entries itself."""

    secure_fts: bool = False
    purge_pending: bool = False


def index_path(root: Path) -> Path:
    return Path(root) / INDEX_NAME


def pending_path(root: Path) -> Path:
    return Path(root) / PENDING_NAME


def is_busy_error(exc: BaseException) -> bool:
    """SQLITE_BUSY / SQLITE_LOCKED: another connection holds the lock."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in _BUSY_CODES:
        return True
    text = str(exc).lower()
    return "database is locked" in text or "table is locked" in text or "database is busy" in text


def is_corrupt_error(exc: BaseException) -> bool:
    """SQLITE_CORRUPT / SQLITE_NOTADB, or FTS5's "invalid fts5 file format"."""
    if is_busy_error(exc):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in _CORRUPT_CODES:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _CORRUPT_TEXT)


_TABLES = (
    "CREATE VIRTUAL TABLE turn_fts USING {module}(seg, tokenize='{tokenize}')",
    "CREATE TABLE sessions (stem TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL,"
    " size INTEGER NOT NULL, indexed INTEGER NOT NULL, session_id TEXT NOT NULL DEFAULT '',"
    " nturns INTEGER NOT NULL DEFAULT 0, digest TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE turns (id INTEGER PRIMARY KEY, stem TEXT NOT NULL,"
    " session_id TEXT NOT NULL, turn_idx INTEGER NOT NULL, role TEXT NOT NULL,"
    " content TEXT NOT NULL, ts TEXT, agent_id TEXT, media INTEGER NOT NULL)",
    "CREATE INDEX idx_turns_stem ON turns(stem)",
)
_DROPS = ("DROP TABLE IF EXISTS turn_fts", "DROP TABLE IF EXISTS turns",
          "DROP TABLE IF EXISTS sessions")


def _versions(conn: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in conn.execute("SELECT name, value FROM meta")}


def _current(rows: dict[str, str]) -> bool:
    return (rows.get("segmenter") == cjk_fts.SEGMENTER_VERSION
            and rows.get("schema") == SCHEMA_VERSION
            and rows.get("module") == FTS5_MODULE)


def _schema(conn: _IndexConnection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if not _current(_versions(conn)):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not _current(_versions(conn)):
                # The reindex migration's first half: another segmentation or table shape
                # means every stored row is wrong. The tables are dropped, not emptied, so
                # no old segment survives; the next sync re-reads every snapshot.
                for statement in _DROPS:
                    conn.execute(statement)
                for statement in _TABLES:
                    conn.execute(statement.format(module=FTS5_MODULE, tokenize=cjk_fts.TOKENIZE))
                for name, value in (("segmenter", cjk_fts.SEGMENTER_VERSION),
                                    ("schema", SCHEMA_VERSION), ("module", FTS5_MODULE)):
                    conn.execute("INSERT OR REPLACE INTO meta (name, value) VALUES (?, ?)",
                                 (name, value))
                cjk_fts.enable_secure_delete(conn, "turn_fts")
            conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
    conn.secure_fts = cjk_fts.secure_delete_enabled(conn, "turn_fts")


def _connect_once(path: Path, timeout: float) -> _IndexConnection:
    # The index holds a verbatim copy of every turn: owner-only like the snapshots (and
    # its -journal, which SQLite creates with the main file's mode), never 0o666 & ~umask.
    ensure_private(path)
    conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None,
                           factory=_IndexConnection)
    conn.row_factory = sqlite3.Row
    if TRACE is not None:
        conn.set_trace_callback(TRACE)
    try:
        conn.execute("PRAGMA secure_delete = ON")
        _schema(conn)
        # A read of the FTS structure: a wiped shadow table fails here, not mid-search.
        conn.execute("SELECT count(*) FROM turn_fts WHERE turn_fts MATCH 'x'").fetchone()
    except BaseException:
        conn.close()
        raise
    return conn


def _remove_files(path: Path, *, strict: bool = False) -> None:
    """Unlink the index and its sidecars. A failure (Windows refuses to unlink an open
    file) raises :class:`IndexUnavailable`, or the ``OSError`` itself when *strict*."""
    for candidate in (path, *(Path(str(path) + s) for s in _SIDECARS)):
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            if strict:
                raise
            raise IndexUnavailable(f"could not remove {candidate.name}: {exc}") from exc


def open_index(root: Path, *, create: bool = True,
               timeout: float | None = None) -> _IndexConnection | None:
    """A connection to *root*'s index with the schema in place, or None when there is
    nothing to open (``create=False`` and no index yet).

    Raises :class:`IndexUnavailable` when this SQLite cannot host it, when another
    connection holds the lock past *timeout* (``busy``; default :data:`OPEN_TIMEOUT`), or
    on any other error. Only a *corrupt* index (SQLITE_CORRUPT / NOTADB, a wiped FTS5
    shadow table) is deleted and recreated empty: it is derived, :func:`sync` refills it.
    """
    root = Path(root)
    path = index_path(root)
    if not root.is_dir() or (not create and not path.exists()):
        return None
    wait = OPEN_TIMEOUT if timeout is None else timeout
    existed = path.exists()
    try:
        return _drain_pending(_connect_once(path, wait), root)
    except sqlite3.Error as exc:
        if "no such module" in str(exc):
            if not existed:
                _remove_files(path)   # leave no empty database behind
            raise IndexUnavailable(str(exc)) from exc
        if is_busy_error(exc):
            raise IndexUnavailable(str(exc), busy=True) from exc
        if not is_corrupt_error(exc):
            raise IndexUnavailable(str(exc)) from exc
        failure: sqlite3.Error = exc
    logger.warning("session index corrupt (%s); rebuilding it", type(failure).__name__)
    _remove_files(path)
    try:
        return _drain_pending(_connect_once(path, wait), root)
    except sqlite3.Error as exc:
        raise IndexUnavailable(str(exc), busy=is_busy_error(exc)) from exc


def _record_pending(root: Path, stems: list[str]) -> None:
    """Remember *stems* a removal could not drop (the index was busy), owner-only."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(pending_path(root), flags, PRIVATE_MODE)
        try:
            os.write(fd, "".join(f"{stem}\n" for stem in stems).encode("ascii"))
        finally:
            os.close(fd)
    except OSError as exc:
        logger.warning("session index: could not record a pending removal: %s", exc)


def _drain_pending(conn: _IndexConnection, root: Path) -> _IndexConnection:
    """Drop the rows of the removals :func:`forget_sessions` left pending on a busy
    index, so the next open of any kind (a save, a search, a removal) erases them, not
    only a search's :func:`sync`. A stem whose snapshot exists again is left to sync.
    Best effort: on a busy lock the list stays for the next open."""
    pending = pending_path(root)
    if not pending.is_file():
        return conn
    # Claim the list first, so a removal appending meanwhile writes a new one.
    claim = pending.with_name(f"{PENDING_NAME}.{os.getpid()}.{threading.get_ident()}")
    try:
        os.replace(pending, claim)
        text = claim.read_text(encoding="ascii", errors="ignore")
    except OSError:
        return conn
    stems = [stem for stem in dict.fromkeys(text.split())
             if is_valid_session_id(stem) and not (Path(root) / f"{stem}.json").exists()]
    try:
        if stems:
            conn.execute("BEGIN IMMEDIATE")
            for stem in stems:
                _drop(conn, stem)
            _commit(conn)
    except sqlite3.Error as exc:
        _rollback(conn)
        logger.debug("session index: pending removals kept for the next open: %s", exc)
        _record_pending(root, stems)
    with contextlib.suppress(OSError):
        claim.unlink()
    return conn


def _drop(conn: _IndexConnection, stem: str) -> int:
    """Delete every row of *stem*; returns how many turns it had."""
    conn.execute(
        "DELETE FROM turn_fts WHERE rowid IN (SELECT id FROM turns WHERE stem=?)", (stem,)
    )
    gone = conn.execute("DELETE FROM turns WHERE stem=?", (stem,)).rowcount
    conn.execute("DELETE FROM sessions WHERE stem=?", (stem,))
    if gone > 0:
        conn.purge_pending = True
    return max(gone, 0)


def _commit(conn: _IndexConnection) -> None:
    """End a write transaction. Where FTS5 ``secure-delete`` is unavailable, a
    transaction that dropped rows first rewrites the index (``optimize``) so the dropped
    terms leave the file."""
    if conn.purge_pending and not conn.secure_fts:
        cjk_fts.purge_deleted(conn, "turn_fts")
    conn.purge_pending = False
    conn.execute("COMMIT")


def _rollback(conn: _IndexConnection) -> None:
    conn.purge_pending = False
    with contextlib.suppress(sqlite3.Error):
        conn.execute("ROLLBACK")


def _load(path: Path, size: int) -> dict | None:
    if size > MAX_INDEX_SNAPSHOT_BYTES:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if is_session_snapshot_payload(data) else None


def _fields(turn: object) -> tuple[str, str, str | None, str | None, int] | None:
    """What the index stores of one turn, or None for a turn it skips."""
    if not isinstance(turn, dict):
        return None
    content = turn.get("content")
    if not isinstance(content, str) or not content:
        return None
    ts = turn.get("timestamp")
    agent = turn.get("agent_id")
    return (str(turn.get("role") or ""), content[:MAX_TURN_CHARS],
            ts if isinstance(ts, str) else None, agent if isinstance(agent, str) else None,
            1 if turn.get("media") else 0)


def _digest_update(digest: Any, turn: object) -> None:
    digest.update(json.dumps(_fields(turn), ensure_ascii=False).encode("utf-8"))
    digest.update(b"\n")


def _index_file(conn: _IndexConnection, stem: str, path: Path) -> str:
    """(Re)index one snapshot inside the caller's transaction. Returns ``"append"`` when
    only turns after the indexed prefix were read, ``"full"`` when the session was
    re-read, ``"skipped"`` when the file holds no session (recorded with no turns, so it
    is not re-read until it changes) and ``"gone"`` when it vanished."""
    try:
        st = path.stat()
    except OSError:
        _drop(conn, stem)
        return "gone"
    payload = _load(path, st.st_size)
    known = conn.execute(
        "SELECT indexed, session_id, nturns, digest FROM sessions WHERE stem=?", (stem,)
    ).fetchone()
    if payload is None:
        _drop(conn, stem)
        conn.execute(
            "INSERT INTO sessions (stem, mtime_ns, size, indexed) VALUES (?, ?, ?, 0)",
            (stem, st.st_mtime_ns, st.st_size),
        )
        return "skipped"
    sid = str(payload.get("session_id"))
    turns = payload["turns"]
    digest = hashlib.sha256()
    start = 0
    if (known is not None and known["indexed"] and known["session_id"] == sid
            and 0 < known["nturns"] <= len(turns)):
        for turn in turns[:known["nturns"]]:
            _digest_update(digest, turn)
        if digest.hexdigest() == known["digest"]:
            start = known["nturns"]        # an append: the indexed prefix is unchanged
    if start == 0:
        digest = hashlib.sha256()
        _drop(conn, stem)                  # a rewind or a replace: re-read it all
    for index in range(start, len(turns)):
        turn = turns[index]
        _digest_update(digest, turn)
        fields = _fields(turn)
        if fields is None:
            continue
        role, content, ts, agent, media = fields
        cur = conn.execute(
            "INSERT INTO turns (stem, session_id, turn_idx, role, content, ts, agent_id, media)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (stem, sid, index, role, content, ts, agent, media),
        )
        conn.execute("INSERT INTO turn_fts (rowid, seg) VALUES (?, ?)",
                     (cur.lastrowid, cjk_fts.index_text(content)))
    conn.execute(
        "INSERT INTO sessions (stem, mtime_ns, size, indexed, session_id, nturns, digest)"
        " VALUES (?, ?, ?, 1, ?, ?, ?) ON CONFLICT(stem) DO UPDATE SET"
        " mtime_ns=excluded.mtime_ns, size=excluded.size, indexed=1,"
        " session_id=excluded.session_id, nturns=excluded.nturns, digest=excluded.digest",
        (stem, st.st_mtime_ns, st.st_size, sid, len(turns), digest.hexdigest()),
    )
    return "append" if start else "full"


def _on_disk(root: Path) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    with contextlib.suppress(OSError):
        for path in root.glob("*.json"):
            if not is_session_stem(path.stem):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            found[path.stem] = (st.st_mtime_ns, st.st_size)
    return found


def sync(conn: _IndexConnection, root: Path, *, deadline: float | None = None) -> dict:
    """The reindex migration: (re)index every new or changed snapshot under *root*,
    newest first, and drop the rows of every snapshot that is gone.

    It commits at least every :data:`BATCH_SECONDS`, so neither a search's backfill nor a
    large history holds the write lock for long. Past *deadline* (a ``time.monotonic()``
    value), or when another writer holds the lock, it stops: the snapshots it did not
    bring in step are returned in ``pending`` (newest first); their rows, if any, are
    stale and the caller must not answer from them. Returns ``{indexed, dropped,
    pending}``."""
    root = Path(root)
    on_disk = _on_disk(root)
    known = {row["stem"]: (row["mtime_ns"], row["size"])
             for row in conn.execute("SELECT stem, mtime_ns, size FROM sessions")}
    gone = [stem for stem in known if stem not in on_disk]
    todo = sorted((stem for stem, stamp in on_disk.items() if known.get(stem) != stamp),
                  key=lambda stem: (on_disk[stem][0], stem), reverse=True)
    dropped = position = 0
    try:
        if gone:
            conn.execute("BEGIN IMMEDIATE")
            for stem in gone:
                _drop(conn, stem)
            _commit(conn)
            dropped = len(gone)
        while position < len(todo):
            if deadline is not None and time.monotonic() > deadline:
                break
            conn.execute("BEGIN IMMEDIATE")
            batch_end = time.monotonic() + BATCH_SECONDS
            done = position
            while done < len(todo):
                _index_file(conn, todo[done], root / f"{todo[done]}.json")
                done += 1
                now = time.monotonic()
                if now > batch_end or (deadline is not None and now > deadline):
                    break
            _commit(conn)
            position = done
    except sqlite3.OperationalError as exc:
        _rollback(conn)
        if not is_busy_error(exc):
            raise
        logger.info("session index busy; %d snapshot(s) left for the next sync",
                    len(todo) - position)
    pending = todo[position:]
    if position or dropped:
        logger.info("session index: %d snapshot(s) indexed, %d dropped", position, dropped)
    return {"indexed": position, "dropped": dropped, "pending": pending}


def index_session(root: Path, session_id: str, *, timeout: float | None = None) -> bool:
    """Bring *session_id*'s rows in step with its snapshot (written or removed): the save
    hook. Incremental: an append segments only the new turns. Best effort and never
    waits long: with a busy index (past *timeout*, default :data:`HOOK_TIMEOUT`) it
    returns False and the next :func:`sync` repairs the miss by ``(mtime_ns, size)``."""
    if not is_valid_session_id(session_id):
        return False
    path = Path(root) / f"{session_id}.json"
    if not (path.is_file() and is_session_stem(session_id)):
        forget_sessions(root, [session_id])
        return True
    try:
        conn = open_index(root, timeout=HOOK_TIMEOUT if timeout is None else timeout)
    except IndexUnavailable as exc:
        if exc.busy:
            logger.debug("session index busy; this save is left to the next sync")
        return False
    if conn is None:
        return False
    try:
        conn.execute("BEGIN IMMEDIATE")
        _index_file(conn, session_id, path)
        _commit(conn)
        return True
    except sqlite3.OperationalError as exc:
        _rollback(conn)
        if is_busy_error(exc):
            logger.debug("session index busy; this save is left to the next sync")
            return False
        raise
    finally:
        conn.close()


def forget_sessions(root: Path, session_ids: Iterable[str]) -> int:
    """Drop every row of *session_ids* from *root*'s index (the session-removal hook),
    erasing their terms from the FTS segments too. Returns how many sessions had rows.
    Never creates an index. A busy index answers 0 and the stems are recorded as
    pending: the next :func:`open_index` of any kind (a save, a search) drops them."""
    stems = [sid for sid in session_ids if isinstance(sid, str) and is_valid_session_id(sid)]
    if not stems:
        return 0
    try:
        conn = open_index(root, create=False)
    except IndexUnavailable as exc:
        if exc.busy:
            _record_pending(root, stems)
        return 0
    if conn is None:
        return 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        removed = 0
        for stem in stems:
            if conn.execute("SELECT 1 FROM sessions WHERE stem=?", (stem,)).fetchone():
                removed += 1
            _drop(conn, stem)
        _commit(conn)
        return removed
    except sqlite3.OperationalError as exc:
        _rollback(conn)
        if is_busy_error(exc):
            _record_pending(root, stems)
            return 0
        raise
    finally:
        conn.close()


def clear(root: Path) -> bool:
    """Erase *root*'s index (a forget of all memory) by removing the file and its
    sidecars: it is derived, and the next search rebuilds it. True when one existed and is
    now gone; the ``OSError`` propagates when it could not be removed."""
    path = index_path(root)
    with contextlib.suppress(OSError):
        pending_path(root).unlink()        # nothing is left to drop
    if not any(Path(str(path) + suffix).exists() for suffix in ("", *_SIDECARS)):
        return False
    _remove_files(path, strict=True)
    return not path.exists()


__all__ = [
    "BATCH_SECONDS", "FTS5_MODULE", "HOOK_TIMEOUT", "INDEX_NAME", "IndexUnavailable",
    "MAX_INDEX_SNAPSHOT_BYTES", "MAX_TURN_CHARS", "OPEN_TIMEOUT", "PENDING_NAME",
    "SCHEMA_VERSION", "TRACE", "clear", "forget_sessions", "index_path", "index_session",
    "is_busy_error", "is_corrupt_error", "open_index", "pending_path", "sync",
]
