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
  a :data:`cjk_fts.SEGMENTER_VERSION` change rebuilds the index, a snapshot whose
  ``(mtime_ns, size)`` differs from what was indexed (or that was never indexed) is
  (re)indexed, and the rows of a snapshot that is gone are dropped. So even a removal
  that bypassed every hook (a file deleted by hand, a purge resetting a snapshot to
  ``{}``) cannot be found through the index.

The index is a derived cache: when it is unreadable it is rebuilt from the snapshots;
when this SQLite has no FTS5 :func:`open_index` answers None and ``session_search``
falls back to its bounded scan. Deleted rows are not left in freed pages
(``secure_delete``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from agents.core.memory import cjk_fts
from agents.core.session_files import is_session_snapshot_payload, is_session_stem
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.session_index")

INDEX_NAME = "session_index.db"
#: The FTS module the index uses; a test points it at a missing module to exercise the
#: no-FTS5 fallback.
FTS5_MODULE = "fts5"
#: The turn prefix the index stores and matches — the scan reads the same prefix.
MAX_TURN_CHARS = 20_000
#: A snapshot larger than this is recorded as skipped, never parsed.
MAX_INDEX_SNAPSHOT_BYTES = 64_000_000
#: Called with each SQL statement the index runs, when set (tests prove MATCH ran).
TRACE: Callable[[str], None] | None = None

_SIDECARS = ("-wal", "-shm", "-journal")


class IndexUnavailable(Exception):
    """This SQLite has no FTS5 (or the index cannot be created): use the scan."""


def index_path(root: Path) -> Path:
    return Path(root) / INDEX_NAME


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS turn_fts USING {FTS5_MODULE}("
        f"seg, tokenize='{cjk_fts.TOKENIZE}')"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions (stem TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL,"
        " size INTEGER NOT NULL, indexed INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, stem TEXT NOT NULL,"
        " session_id TEXT NOT NULL, turn_idx INTEGER NOT NULL, role TEXT NOT NULL,"
        " content TEXT NOT NULL, ts TEXT, agent_id TEXT, media INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_stem ON turns(stem)")
    row = conn.execute("SELECT value FROM meta WHERE name='segmenter'").fetchone()
    if row is None or row[0] != cjk_fts.SEGMENTER_VERSION:
        # The reindex migration's first half: a different segmentation means every stored
        # row is wrong. Drop them all; the next sync re-reads every snapshot.
        conn.execute("DELETE FROM turn_fts")
        conn.execute("DELETE FROM turns")
        conn.execute("DELETE FROM sessions")
        conn.execute(
            "INSERT OR REPLACE INTO meta (name, value) VALUES ('segmenter', ?)",
            (cjk_fts.SEGMENTER_VERSION,),
        )
    conn.commit()


def _connect_once(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
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


def _remove_files(path: Path) -> None:
    for candidate in (path, *(Path(str(path) + s) for s in _SIDECARS)):
        with contextlib.suppress(FileNotFoundError):
            candidate.unlink()


def open_index(root: Path, *, create: bool = True) -> sqlite3.Connection | None:
    """A connection to *root*'s index with the schema in place, or None when there is
    nothing to open (``create=False`` and no index yet). Raises :class:`IndexUnavailable`
    when this SQLite cannot host it. A corrupt index (a wiped FTS5 shadow table, a torn
    file) is deleted and recreated empty — it is derived, :func:`sync` refills it."""
    root = Path(root)
    path = index_path(root)
    if not root.is_dir() or (not create and not path.exists()):
        return None
    existed = path.exists()
    try:
        return _connect_once(path)
    except sqlite3.OperationalError as exc:
        if "no such module" in str(exc):
            if not existed:
                _remove_files(path)   # leave no empty database behind
            raise IndexUnavailable(str(exc)) from exc
        failure: sqlite3.Error = exc
    except sqlite3.DatabaseError as exc:
        failure = exc
    logger.warning("session index unreadable (%s); rebuilding it", type(failure).__name__)
    _remove_files(path)
    try:
        return _connect_once(path)
    except sqlite3.Error as exc:
        raise IndexUnavailable(str(exc)) from exc


def _drop(conn: sqlite3.Connection, stem: str) -> None:
    conn.execute("DELETE FROM turn_fts WHERE rowid IN (SELECT id FROM turns WHERE stem=?)", (stem,))
    conn.execute("DELETE FROM turns WHERE stem=?", (stem,))
    conn.execute("DELETE FROM sessions WHERE stem=?", (stem,))


def _load(path: Path, size: int) -> dict | None:
    if size > MAX_INDEX_SNAPSHOT_BYTES:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if is_session_snapshot_payload(data) else None


def _index_file(conn: sqlite3.Connection, stem: str, path: Path) -> bool:
    """(Re)index one snapshot. Returns whether it held a session (False: recorded as
    skipped, with no turns, so it is not re-read until it changes)."""
    try:
        st = path.stat()
    except OSError:
        _drop(conn, stem)
        return False
    _drop(conn, stem)
    payload = _load(path, st.st_size)
    if payload is not None:
        sid = str(payload.get("session_id"))
        for index, turn in enumerate(payload["turns"]):
            if not isinstance(turn, dict):
                continue
            content = turn.get("content")
            if not isinstance(content, str) or not content:
                continue
            content = content[:MAX_TURN_CHARS]
            ts = turn.get("timestamp")
            agent = turn.get("agent_id")
            cur = conn.execute(
                "INSERT INTO turns (stem, session_id, turn_idx, role, content, ts, agent_id, media)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (stem, sid, index, str(turn.get("role") or ""), content,
                 ts if isinstance(ts, str) else None, agent if isinstance(agent, str) else None,
                 1 if turn.get("media") else 0),
            )
            conn.execute("INSERT INTO turn_fts (rowid, seg) VALUES (?, ?)",
                         (cur.lastrowid, cjk_fts.index_text(content)))
    conn.execute(
        "INSERT INTO sessions (stem, mtime_ns, size, indexed) VALUES (?, ?, ?, ?)",
        (stem, st.st_mtime_ns, st.st_size, 1 if payload is not None else 0),
    )
    return payload is not None


def sync(conn: sqlite3.Connection, root: Path) -> dict:
    """The reindex migration: (re)index every new or changed snapshot under *root* and
    drop the rows of every snapshot that is gone. Returns ``{indexed, dropped}``."""
    root = Path(root)
    on_disk: dict[str, tuple[int, int]] = {}
    with contextlib.suppress(OSError):
        for path in root.glob("*.json"):
            if not is_session_stem(path.stem):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            on_disk[path.stem] = (st.st_mtime_ns, st.st_size)
    known = {row["stem"]: (row["mtime_ns"], row["size"])
             for row in conn.execute("SELECT stem, mtime_ns, size FROM sessions")}
    dropped = [stem for stem in known if stem not in on_disk]
    for stem in dropped:
        _drop(conn, stem)
    indexed = 0
    for stem, stamp in on_disk.items():
        if known.get(stem) != stamp:
            _index_file(conn, stem, root / f"{stem}.json")
            indexed += 1
    conn.commit()
    if indexed or dropped:
        logger.info("session index: %d snapshot(s) indexed, %d dropped", indexed, len(dropped))
    return {"indexed": indexed, "dropped": len(dropped)}


def index_session(root: Path, session_id: str) -> bool:
    """Bring *session_id*'s rows in step with its snapshot (written or removed). Best
    effort: the snapshot is the record, the next :func:`sync` repairs a miss."""
    if not is_valid_session_id(session_id):
        return False
    path = Path(root) / f"{session_id}.json"
    if not (path.is_file() and is_session_stem(session_id)):
        forget_sessions(root, [session_id])
        return True
    try:
        conn = open_index(root)
    except IndexUnavailable:
        return False
    if conn is None:
        return False
    try:
        _index_file(conn, session_id, path)
        conn.commit()
        return True
    finally:
        conn.close()


def forget_sessions(root: Path, session_ids: Iterable[str]) -> int:
    """Drop every row of *session_ids* from *root*'s index (the session-removal hook).
    Returns how many sessions had rows. Never creates an index."""
    stems = [sid for sid in session_ids if isinstance(sid, str) and is_valid_session_id(sid)]
    if not stems:
        return 0
    try:
        conn = open_index(root, create=False)
    except IndexUnavailable:
        return 0
    if conn is None:
        return 0
    try:
        removed = 0
        for stem in stems:
            if conn.execute("SELECT 1 FROM sessions WHERE stem=?", (stem,)).fetchone():
                removed += 1
            _drop(conn, stem)
        conn.commit()
        return removed
    finally:
        conn.close()


def clear(root: Path) -> bool:
    """Empty *root*'s index (a forget of all memory). True when one existed."""
    try:
        conn = open_index(root, create=False)
    except IndexUnavailable:
        _remove_files(index_path(root))
        return True
    if conn is None:
        return False
    try:
        conn.execute("DELETE FROM turn_fts")
        conn.execute("DELETE FROM turns")
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.execute("VACUUM")
        return True
    finally:
        conn.close()


__all__ = [
    "FTS5_MODULE", "INDEX_NAME", "IndexUnavailable", "MAX_INDEX_SNAPSHOT_BYTES",
    "MAX_TURN_CHARS", "TRACE", "clear", "forget_sessions", "index_path", "index_session",
    "open_index", "sync",
]
