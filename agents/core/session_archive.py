"""H218 — archived chats: put a conversation away, bring it back, or delete it for good.

Hermes keeps an Archived Chats view beside the chat list. Nerva's sessions could only be
listed and resumed; the only deletion was the install-wide ``/api/admin/forget``. Here:

- **Archive / unarchive.** A stamp (``archived_at``) in the session's metadata row. An
  archived session leaves ``GET /sessions`` and is listed by ``GET /sessions?archived=1``;
  nothing about it is deleted, and resuming it brings it back.
- **Auto-archive.** ``memory.auto_archive_days`` (0 = off) archives a session whose last
  activity is older than that many days, once a day; the session in use is never touched.
- **Delete permanently.** Backup first, like the install-wide forget: every trace of the
  session this hub keeps (its row, checkpoints and clock, the transcript snapshot and log,
  its checklist, the compaction archive) is written to
  ``<data root>/backups/sessions/<id>-<stamp>.json``, fsynced and read back, and only then
  deleted. A backup that did not land deletes nothing. The route is admin-only and needs
  ``?confirm=DELETE``; the session in use cannot be deleted.
"""
from __future__ import annotations

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
BACKUP_DIR = ("backups", "sessions")


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


def _read_lines(path: Path) -> list[Any]:
    out: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
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


def collect(session_id: str, *, checkpoints: Any, todos: Any, archive_root: Path | None = None) -> dict:
    """Everything the hub keeps about one session, as one JSON-able record."""
    record: dict[str, Any] = {"session_id": session_id, "taken_at": _now().isoformat()}
    record.update(checkpoints.session_rows_for_backup(session_id) if checkpoints is not None else {})
    files = _files(session_id, archive_root)
    snapshot = files["snapshot"]
    record["snapshot"] = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.is_file() else None
    record["log"] = _read_lines(files["log"]) if files["log"].is_file() else []
    record["compaction_archive"] = (_read_lines(files["compaction_archive"])
                                    if files["compaction_archive"].is_file() else [])
    record["todo"] = todos.read(session_id) if todos is not None else None
    return record


def _write_backup(record: dict, target: Path) -> Path:
    """Write, fsync (file and folder) and read back; raise when any step fails."""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    fd, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=str(target.parent))   # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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
    if json.loads(target.read_text(encoding="utf-8")).get("session_id") != record["session_id"]:
        raise OSError("the backup did not read back")
    return target


async def delete_session(session_id: str, *, checkpoints: Any, memory: Any = None, todos: Any = None,
                         active: str | None = None, backup_root: Path | None = None,
                         archive_root: Path | None = None) -> dict:
    """Back the session up, then delete every trace of it. Raises
    :class:`SessionDeleteError` (``active_session``, ``not_found``, ``backup_failed``)
    before anything is deleted."""
    from agents.core.paths import data_path

    if session_id == active:
        raise SessionDeleteError("active_session")
    record = collect(session_id, checkpoints=checkpoints, todos=todos, archive_root=archive_root)
    files = _files(session_id, archive_root)
    if record.get("session") is None and record.get("snapshot") is None and not record.get("log"):
        raise SessionDeleteError("not_found")
    stamp = _now().strftime("%Y%m%dT%H%M%S%fZ")
    root = backup_root if backup_root is not None else data_path(*BACKUP_DIR)
    try:
        backup = _write_backup(record, Path(root) / f"{session_id}-{stamp}.json")
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("session delete refused: the backup did not land (%s)", type(exc).__name__)
        raise SessionDeleteError("backup_failed") from exc
    removed: dict[str, Any] = {"rows": checkpoints.delete_session_rows(session_id) if checkpoints is not None else {}}
    for name, path in files.items():
        try:
            path.unlink()
            removed[name] = True
        except FileNotFoundError:
            removed[name] = False
    clear = getattr(memory, "clear", None)
    if callable(clear):
        await clear(session_id)
    removed["todo"] = bool(todos.forget(session_id)) if todos is not None else False
    logger.info("session %s deleted; backup at %s", session_id, backup)
    return {"ok": True, "session": session_id, "backup": str(backup), "removed": removed}


__all__ = [
    "BACKUP_DIR", "CONFIRM", "MAX_AUTO_DAYS", "SETTING_AUTO_DAYS", "SessionDeleteError",
    "auto_archive_days", "collect", "delete_session", "run_auto_archive",
]
