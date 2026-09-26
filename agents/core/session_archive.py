"""H218 — archived chats: put a conversation away, bring it back, or delete it for good.

Hermes keeps an Archived Chats view beside the chat list. Nerva's sessions could only be
listed and resumed; the only deletion was the install-wide ``/api/admin/forget``. Here:

- **Archive / unarchive.** A stamp (``archived_at``) in the session's metadata row. An
  archived session leaves ``GET /sessions`` and is listed by ``GET /sessions?archived=1``;
  nothing about it is deleted, and resuming it brings it back.
- **Auto-archive.** ``memory.auto_archive_days`` (0 = off) archives a session whose last
  activity is older than that many days, once a day; the session in use is never touched.
- **Delete permanently.** Backup first, like the install-wide forget: what the hub keeps
  under the session's id (its rows — the session, checkpoints, clock, continuation seed
  and history binding —, the transcript snapshot and log, the compaction archive, its
  checklist and its note) is written, encrypted, to ``<id>-<stamp>.json.enc`` beside the
  pre-forget archives, outside the data root (:func:`default_backup_dir`), fsynced and
  read back; only then is it deleted, with the chat's turn embeddings in long-term recall.
  A backup that did not land deletes nothing, and the newest few backups are kept. The
  route is admin-only, needs ``?confirm=DELETE`` and holds the session's turn lease; the
  session in use, and one another chat continues, cannot be deleted. Facts already
  extracted into the knowledge graph and the append-only audit log are not touched.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.session_archive")

SETTING_AUTO_DAYS = "memory.auto_archive_days"
MAX_AUTO_DAYS = 3650
CONFIRM = "DELETE"
BACKUP_SUFFIX = ".json.enc"
#: How many per-session backups are kept, newest first (``JARVIS_SESSION_BACKUP_KEEP``).
BACKUP_KEEP_DEFAULT = 10


class SessionDeleteError(RuntimeError):
    """A permanent delete refused, with a reason a route can name."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _now() -> datetime:
    return datetime.now(UTC)


def auto_archive_days(value: Any) -> int:
    """The setting as a whole number of days (0 = off); anything else is off."""
    if isinstance(value, bool):
        return 0
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 0
    return days if 0 < days <= MAX_AUTO_DAYS else 0


def run_auto_archive(checkpoints: Any, days: int, *, active: str | None = None,
                     now: datetime | None = None) -> list[str]:
    """Archive every unarchived session idle for more than ``days`` (never ``active``)."""
    if days <= 0 or checkpoints is None:
        return []
    moment = now or _now()
    before = (moment - timedelta(days=days)).isoformat()
    done: list[str] = []
    for sid in checkpoints.stale_sessions(before):
        if sid == active:
            continue
        if checkpoints.set_archived(sid, True, at=moment.isoformat()):
            done.append(sid)
    if done:
        logger.info("auto-archived %d idle session(s) older than %d day(s)", len(done), days)
    return done


def default_backup_dir() -> Path:
    """Where a permanent delete's backups go: beside the pre-forget archives, outside the
    data root, so a copy of a deleted chat never sits in the folder it was deleted from
    (AUDIT-2c). ``JARVIS_FORGET_ARCHIVE_DIR`` moves both."""
    from agents.core.backup import pre_forget_dir

    return pre_forget_dir() / "sessions"


def _parse_lines(text: str) -> list[Any]:
    out: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append(line)
    return out


def _files(session_id: str, archive_root: Path | None) -> dict[str, Path]:
    from agents.core.memory.persistence import memory_dir
    from agents.core.memory.precompress import TranscriptArchive

    base = memory_dir()
    return {
        "snapshot": base / f"{session_id}.json",
        "log": base / f"{session_id}.jsonl",
        "compaction_archive": TranscriptArchive(archive_root).path_for(session_id),
    }


def collect(session_id: str, *, checkpoints: Any, todos: Any, notes: Any = None,
            archive_root: Path | None = None) -> dict:
    """Everything the hub keeps under one session's id, as one JSON-able record. A file
    that is not UTF-8, or a snapshot that does not parse (a torn write), is kept byte for
    byte, base64, and named in ``unreadable``."""
    record: dict[str, Any] = {"session_id": session_id, "taken_at": _now().isoformat(), "unreadable": []}
    record.update(checkpoints.session_rows_for_backup(session_id) if checkpoints is not None else {})
    for name, path in _files(session_id, archive_root).items():
        if not path.is_file():
            record[name] = None if name == "snapshot" else []
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
            record[name] = json.loads(text) if name == "snapshot" else _parse_lines(text)
        except ValueError:
            record[name] = base64.b64encode(raw).decode("ascii")
            record["unreadable"].append(name)
    record["todo"] = todos.read(session_id) if todos is not None else None
    record["note"] = notes.get(session_id) if notes is not None else None
    return record


def _is_session(session_id: str, record: dict) -> bool:
    """Whether the id names a conversation, never another store in the data root
    (``notes.json``, ``kill_switch.json`` and ``autonomy_journal.jsonl`` live beside the
    transcripts): a session stem, and a snapshot that is this session's — or one that
    cannot be read, beside the session's row or log."""
    from agents.core.session_files import is_session_snapshot_payload, is_session_stem

    if not is_session_stem(session_id):
        return False
    snapshot = record.get("snapshot")
    if snapshot is not None and "snapshot" not in record["unreadable"]:
        return is_session_snapshot_payload(snapshot) and snapshot.get("session_id") == session_id
    return record.get("session") is not None or bool(record.get("log"))


def _write_backup(record: dict, target: Path) -> Path:
    """Encrypt, write, fsync (file and folder) and read back; raise when any step fails.

    Always encrypted, as the pre-forget archive is: the backup cipher's key lives under
    ``$JARVIS_KEY_DIR``, never beside the backup."""
    from agents.core.backup import _backup_cipher

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _backup_cipher(None).encrypt_bytes(
        json.dumps(record, ensure_ascii=False, default=str).encode("utf-8"))
    fd, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=str(target.parent))   # created 0600
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
    except OSError:
        dir_fd = None                      # a platform without directory fds (Windows)
    if dir_fd is not None:
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    if target.read_bytes() != payload:
        raise OSError("the backup did not read back")
    return target


def read_backup(path: str | Path) -> dict:
    """A permanent delete's backup, decrypted: the way back to what was deleted."""
    from agents.core.backup import _backup_cipher

    return json.loads(_backup_cipher(None).decrypt_bytes(Path(path).read_bytes()))


def prune_backups(root: Path, keep: int | None = None) -> list[str]:
    """Keep only the newest ``keep`` session backups (``JARVIS_SESSION_BACKUP_KEEP``, else
    :data:`BACKUP_KEEP_DEFAULT`, never fewer than the one just written); what was removed.
    A copy of a deleted chat is a safety net, not an archive kept forever."""
    from agents.core.env_config import env_int

    if keep is None:
        keep = env_int("JARVIS_SESSION_BACKUP_KEEP", BACKUP_KEEP_DEFAULT, minimum=1)
    backups = sorted(root.glob(f"*{BACKUP_SUFFIX}"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    removed: list[str] = []
    for stale in backups[max(1, keep):]:
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError:
            logger.warning("could not prune the stale session backup %s", stale.name)
    return removed


def _delete_traces(session_id: str, checkpoints: Any, files: dict[str, Path]) -> dict:
    removed: dict[str, Any] = {"rows": checkpoints.delete_session_rows(session_id) if checkpoints is not None else {}}
    for name, path in files.items():
        try:
            path.unlink()
            removed[name] = True
        except FileNotFoundError:
            removed[name] = False
    return removed


def _memory_locks(memory: Any) -> list[asyncio.Lock]:
    """The memory manager's lock, then its conversation's — the order a turn takes them.
    While both are held no turn writes the transcript, so the backup and the delete see
    the same one."""
    locks: list[asyncio.Lock] = []
    for owner in (memory, getattr(memory, "conversation", None)):
        lock = getattr(owner, "_lock", None)
        if isinstance(lock, asyncio.Lock) and all(lock is not held for held in locks):
            locks.append(lock)
    return locks


async def delete_session(session_id: str, *, checkpoints: Any, memory: Any = None, todos: Any = None,
                         notes: Any = None, active: str | None = None, backup_root: Path | None = None,
                         archive_root: Path | None = None) -> dict:
    """Back the session up, then delete it. Raises :class:`SessionDeleteError`
    (``active_session``, ``not_found``, ``has_continuations``, ``backup_failed``,
    ``recall_unavailable``) before anything is deleted.

    The caller holds the session's turn lease (the route does). The memory locks are held
    here from the first read to the last delete, so a turn written meanwhile is in the
    backup, or lands after the delete in a conversation of its own. The file, SQLite and
    fsync work runs on worker threads, never on the event loop."""
    from agents.core.secrets import SecretStoreError

    if session_id == active:
        raise SessionDeleteError("active_session")
    root = Path(backup_root) if backup_root is not None else default_backup_dir()
    async with contextlib.AsyncExitStack() as held:
        for lock in _memory_locks(memory):
            await held.enter_async_context(lock)
        try:
            record = await asyncio.to_thread(collect, session_id, checkpoints=checkpoints, todos=todos,
                                             notes=notes, archive_root=archive_root)
        except OSError as exc:
            logger.warning("session delete refused: the session could not be read (%s)", type(exc).__name__)
            raise SessionDeleteError("backup_failed") from exc
        if not _is_session(session_id, record):
            raise SessionDeleteError("not_found")
        if record.get("continued_by"):
            # A continued chat walks its ancestry back to this one; delete it first.
            raise SessionDeleteError("has_continuations")
        stamp = _now().strftime("%Y%m%dT%H%M%S%fZ")
        try:
            backup = await asyncio.to_thread(_write_backup, record, root / f"{session_id}-{stamp}{BACKUP_SUFFIX}")
        except (OSError, ValueError, TypeError, SecretStoreError) as exc:
            logger.warning("session delete refused: the backup did not land (%s)", type(exc).__name__)
            raise SessionDeleteError("backup_failed") from exc
        forget = getattr(memory, "forget_session_embeddings", None)
        try:
            embeddings = await forget(session_id) if callable(forget) else 0
        except Exception as exc:
            logger.warning("session delete refused: its turn embeddings could not be removed (%s)",
                           type(exc).__name__)
            raise SessionDeleteError("recall_unavailable") from exc
        removed = await asyncio.to_thread(_delete_traces, session_id, checkpoints, _files(session_id, archive_root))
        removed["embeddings"] = embeddings
        conversation = getattr(memory, "conversation", memory)
        for live in (getattr(conversation, "sessions", None), getattr(conversation, "instances", None)):
            if isinstance(live, dict):
                live.pop(session_id, None)
        removed["todo"] = bool(todos.forget(session_id)) if todos is not None else False
        removed["note"] = bool(notes.clear(session_id)) if notes is not None else False
    pruned = await asyncio.to_thread(prune_backups, root)
    logger.info("session %s deleted; backup at %s", session_id, backup)
    return {"ok": True, "session": session_id, "backup": str(backup), "removed": removed, "pruned": pruned}


__all__ = [
    "BACKUP_KEEP_DEFAULT", "BACKUP_SUFFIX", "CONFIRM", "MAX_AUTO_DAYS", "SETTING_AUTO_DAYS",
    "SessionDeleteError", "auto_archive_days", "collect", "default_backup_dir", "delete_session",
    "prune_backups", "read_backup", "run_auto_archive",
]
