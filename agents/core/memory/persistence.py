"""
persistence.py — Memory persistence: saves/loads conversation history across restarts.
"""

import hashlib
import json
import logging
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path

from agents.core.paths import data_root
from agents.core.persistence import atomic_write_json
from agents.core.session_files import is_session_stem, looks_like_session_snapshot
from agents.core.validation import is_valid_session_id

# Resolved LAZILY, not at import. `MEMORY_DIR = data_root()` bound the repo's
# memory_logs/ before a caller could redirect JARVIS_HOME, so scripts/install_smoke.py
# — which DOES set JARVIS_HOME to a temp dir — still wrote its fixture session into the
# live store, and every later boot restored "install_smoke" as the owner's session
# (2026-07-27 QA finding). Same class, and same fix, as the autonomy.db leak in #723.
# `MEMORY_DIR = None` means "ask data_root() each time". It stays a module attribute
# because tests pin it directly (monkeypatch.setattr(persistence, "MEMORY_DIR", tmp)),
# and that seam is worth keeping — it is how the traversal tests get a sandbox.
MEMORY_DIR: Path | None = None


def memory_dir() -> Path:
    """Where session state lives, resolved NOW — honors an explicit MEMORY_DIR override
    first, then the current JARVIS_HOME. Public because callers legitimately need the
    path (tests, the KG writing beside a snapshot); read it through this, never through
    a value captured at import."""
    return MEMORY_DIR if MEMORY_DIR is not None else data_root()


_memory_dir = memory_dir   # internal alias, kept so use sites read tersely

logger = logging.getLogger("jarvis.persistence")


class RewindPersistenceError(RuntimeError):
    """A rewound session's JSON and durable head could not advance together."""

    def __init__(self, message: str, *, inconsistent: bool = False):
        super().__init__(message)
        self.inconsistent = inconsistent


class SnapshotRevisionConflict(RewindPersistenceError):
    """A stale writer must not replace a committed rewind head."""


@contextmanager
def session_snapshot_lock(session_id: str):
    """Serialize snapshot writers across processes, including strict rewinds."""
    if not is_valid_session_id(session_id):
        raise ValueError("invalid session identifier")
    _memory_dir().mkdir(parents=True, exist_ok=True)
    path = _memory_dir() / f"{session_id}.json.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def snapshot_digest(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_snapshot_for_rewind(session_id: str) -> tuple[dict, str]:
    """Read an existing valid snapshot; caller supplies higher-level instance checks."""
    with session_snapshot_lock(session_id):
        path = _memory_dir() / f"{session_id}.json"
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if (type(document) is not dict or document.get("session_id") != session_id
                or type(document.get("turns")) is not list
                or type(document.get("revision", 0)) is not int
                or document.get("revision", 0) < 0):
            raise ValueError("conversation snapshot is unavailable")
        return document, snapshot_digest(document)


def replace_memory_if_current(session_id: str, *, instance_id: str, revision: int,
                              digest: str, turns: list[dict],
                              already_locked: bool = False,
                              expected_missing: bool = False,
                              foreign_origin=None) -> tuple[dict | None, str]:
    """Strict durable compare-and-replace; errors never become a successful undo."""
    with nullcontext() if already_locked else session_snapshot_lock(session_id):
        path = _memory_dir() / f"{session_id}.json"
        if expected_missing:
            if path.exists():
                raise ValueError("conversation snapshot changed")
            current = None
        else:
            with path.open("r", encoding="utf-8") as stream:
                current = json.load(stream)
            if (type(current) is not dict or current.get("session_id") != session_id
                    or current.get("instance_id") != instance_id
                    or current.get("revision", 0) != revision
                    or snapshot_digest(current) != digest):
                raise ValueError("conversation snapshot changed")
        updated = {"session_id": session_id, "turns": turns,
                   "instance_id": instance_id, "revision": revision + 1,
                   "rewound": True}
        if foreign_origin is not None:
            marker = {"kind": foreign_origin.kind, "source": foreign_origin.source,
                      "instance_id": foreign_origin.instance_id}
            if current is not None and current.get("foreign_history") != marker:
                raise ValueError("foreign lineage changed")
            updated["foreign_history"] = marker
        atomic_write_json(path, updated)
        return current, snapshot_digest(updated)


def restore_memory_if_current(session_id: str, *, digest: str, previous: dict | None,
                              already_locked: bool = False) -> bool:
    """Best-effort rollback if the SQLite half of a rewind failed after JSON replace."""
    try:
        with nullcontext() if already_locked else session_snapshot_lock(session_id):
            path = _memory_dir() / f"{session_id}.json"
            with path.open("r", encoding="utf-8") as stream:
                current = json.load(stream)
            if snapshot_digest(current) != digest:
                return False
            if previous is None:
                path.unlink()
            else:
                atomic_write_json(path, previous)
            return True
    except Exception:
        return False


def save_memory(session_id: str, turns: list[dict], *, instance_id: str | None = None,
                revision: int | None = None, checkpoint_mgr=None,
                require_rewind: bool = False, foreign_origin=None):
    # AUD-5: never let an id that isn't an inert identifier reach the path — a
    # second line of defense behind the router validation, so any internal caller
    # is protected too.
    if not is_valid_session_id(session_id):
        if foreign_origin is not None:
            raise ValueError("invalid foreign session identifier")
        logger.warning("refusing to save memory for invalid session_id")
        return
    try:
        _memory_dir().mkdir(parents=True, exist_ok=True)
        path = _memory_dir() / f"{session_id}.json"
        # tmp+replace, not open(path, "w"): the truncate-then-stream form left a
        # half-written snapshot on disk whenever the dump raised (or the process
        # died) mid-turn, and load_memory() reads that as an empty conversation.
        payload = {"session_id": session_id, "turns": turns,
                   **({"instance_id": instance_id} if instance_id else {}),
                   **({"revision": revision} if revision is not None else {})}
        if foreign_origin is not None:
            payload["foreign_history"] = {"kind": foreign_origin.kind, "source": foreign_origin.source,
                                          "instance_id": foreign_origin.instance_id}
        with (checkpoint_mgr._lock if checkpoint_mgr is not None else nullcontext()), session_snapshot_lock(session_id):
            conn = getattr(checkpoint_mgr, "_conn", None)
            if foreign_origin is not None:
                from ..foreign_history import status_locked
                if conn is None or status_locked(conn, session_id) != foreign_origin:
                    raise ValueError("foreign lineage changed")
                # Mark the immutable seed non-recoverable before attempting a
                # newer snapshot. A crash can conservatively refuse this session;
                # it must never resurrect a seed that omits an acknowledged reply.
                changed = conn.execute(
                    "UPDATE session_imports SET snapshot_required=1 "
                    "WHERE session_id=? AND instance_id=?", (session_id, foreign_origin.instance_id),
                )
                if changed.rowcount != 1:
                    raise ValueError("foreign receipt changed")
                conn.commit()
            try:
                head = (conn.execute(
                    "SELECT instance_id,revision,snapshot_sha256 FROM session_history_rewinds "
                    "WHERE session_id=?", (session_id,),
                ).fetchone() if conn is not None else None)
            except Exception as exc:
                if require_rewind:
                    raise RewindPersistenceError("conversation rewind head unavailable") from exc
                raise
            current = None
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        current = json.load(stream)
                except (OSError, ValueError, TypeError) as exc:
                    if head is not None or require_rewind:
                        raise RewindPersistenceError("conversation rewind snapshot unavailable") from exc
                    raise
            if require_rewind or head is not None or (isinstance(current, dict) and current.get("rewound") is True):
                if conn is None or head is None:
                    raise RewindPersistenceError("conversation rewind head unavailable")
                try:
                    current_digest = snapshot_digest(current) if type(current) is dict else None
                except (ValueError, TypeError) as exc:
                    raise RewindPersistenceError("conversation rewind snapshot unavailable") from exc
                if (type(current) is not dict or current.get("session_id") != session_id
                        or current.get("rewound") is not True
                        or type(revision) is not int or type(current.get("revision")) is not int
                        or instance_id != head[0] or current.get("instance_id") != instance_id
                        or current["revision"] != head[1]
                        or current_digest != head[2]):
                    raise SnapshotRevisionConflict("conversation changed after rewind")
                payload["rewound"] = True
                new_digest = snapshot_digest(payload)
                # Synchronous callers may re-save the exact durable head. This
                # is idempotent, never a way to replace history at the same revision.
                if revision == current["revision"] and new_digest == current_digest:
                    return
                if current["revision"] != revision - 1:
                    raise SnapshotRevisionConflict("conversation changed after rewind")
                wrote = False
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    atomic_write_json(path, payload)
                    wrote = True
                    changed = conn.execute(
                        "UPDATE session_history_rewinds SET revision=?,snapshot_sha256=? "
                        "WHERE session_id=? AND instance_id=? AND revision=? AND snapshot_sha256=?",
                        (revision, new_digest, session_id, instance_id, head[1], head[2]),
                    )
                    if changed.rowcount != 1:
                        raise SnapshotRevisionConflict("conversation rewind head changed")
                    conn.commit()
                except Exception as exc:
                    rollback_failed = False
                    try:
                        conn.rollback()
                    except Exception:
                        rollback_failed = True
                    restored = not wrote or restore_memory_if_current(
                        session_id, digest=new_digest, previous=current, already_locked=True
                    )
                    if rollback_failed or not restored:
                        raise RewindPersistenceError(
                            "conversation rewind needs recovery", inconsistent=True
                        ) from exc
                    if isinstance(exc, RewindPersistenceError):
                        raise
                    raise RewindPersistenceError("conversation rewind not persisted") from exc
            else:
                atomic_write_json(path, payload)
        logger.info(f"Memory saved: {path} ({len(turns)} turns)")
    except RewindPersistenceError:
        raise
    except Exception as e:
        if require_rewind or foreign_origin is not None:
            raise RewindPersistenceError("conversation rewind not persisted") from e
        logger.warning(f"Failed to save memory: {e}")


def load_memory_snapshot(session_id: str) -> dict:
    if not is_valid_session_id(session_id):
        logger.warning("refusing to load memory for invalid session_id")
        return {}
    path = _memory_dir() / f"{session_id}.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Memory loaded: {path} ({len(data.get('turns', []))} turns)")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to load memory: {e}")
        return {}


def load_memory(session_id: str) -> list[dict]:
    return load_memory_snapshot(session_id).get("turns", [])


def list_sessions() -> list[str]:
    """Most-recent conversation sessions in the data root, newest first (max 5).

    The data root is shared with runtime state (`entities.json`, `decay.json`,
    `bitemporal_kg.json`, …), so a bare `*.json` glob does not identify sessions:
    `entities.json` is rewritten on any turn mentioning a proper noun and is
    therefore usually the newest `*.json` in the directory. Ranking it first made
    `ConversationMemory._load_latest_session()` "restore" a session that does not
    exist, silently dropping history across restarts on a default install — no
    flag involved. Candidates are now filtered by name and confirmed by payload
    shape (`agents.core.session_files`).
    """
    _memory_dir().mkdir(parents=True, exist_ok=True)
    sessions = []
    # Sort by nanosecond mtime (finer than float-seconds st_mtime) with the stem as
    # a deterministic tiebreak: when two sessions are written within one filesystem
    # mtime tick — common on Windows — a plain st_mtime sort ties them and the stable
    # sort keeps alphabetical (glob) order, restoring the OLDER session on restart.
    # On a tie, alphabetically-last wins, which matches "most recent" for both the
    # timestamp session names and sequentially-named ones.
    for f in sorted(
        _memory_dir().glob("*.json"),
        key=lambda p: (p.stat().st_mtime_ns, p.stem),
        reverse=True,
    ):
        sid = f.stem
        if sid in sessions or not is_session_stem(sid):
            continue
        # Confirm the payload before treating it as a session. Only reached for
        # name-plausible candidates, and the loop stops at 5, so this reads a
        # handful of small files at boot at most.
        if not looks_like_session_snapshot(f):
            continue
        sessions.append(sid)
        if len(sessions) == 5:
            break
    return sessions


def delete_memory(session_id: str):
    if not is_valid_session_id(session_id):
        logger.warning("refusing to delete memory for invalid session_id")
        return
    path = _memory_dir() / f"{session_id}.json"
    if path.exists():
        path.unlink()
        logger.info(f"Memory deleted: {path}")
