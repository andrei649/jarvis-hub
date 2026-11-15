"""Read-only comparison of a retained terminal scope preimage and current files."""

from __future__ import annotations

import difflib
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .diff_paths import validate_paths
from .file_checkpoint_history import (
    HISTORY_SUPPORTED,
    MAX_SCOPE_BYTES,
    MAX_SCOPE_FILES,
    SCOPE_POLICY_VERSION,
    CheckpointRefusal,
    _canonical_selection,
)
from .file_tools import FileScopeError

_KINDS = ("terminal_invocation", "terminal_task", "terminal_turn")
_MAX_EXCLUSIONS = 5_000
_MAX_DIFF_BYTES = 65_536


def _refused(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def _covered(path: str, excluded: set[str]) -> bool:
    return not any(path == prefix or path.startswith(prefix + "/") for prefix in excluded)


def _read_baseline(history, root: Path, identity: tuple[int, int]):
    """Use an immutable read-only SQLite view, including when the index is absent."""
    directory = history.snapshots.directory
    db_path = directory / "history.sqlite3"
    try:
        directory_info = os.stat(directory, follow_symlinks=False)
        db_info = os.stat(db_path, follow_symlinks=False)
    except FileNotFoundError:
        return None, None, None, "no_baseline"
    except OSError:
        return None, None, None, "baseline_unavailable"
    if (not stat.S_ISDIR(directory_info.st_mode) or not stat.S_ISREG(db_info.st_mode)
            or db_info.st_nlink != 1 or db_info.st_size > 64 * 1024 * 1024
            or os.path.islink(db_path)):
        return None, None, None, "baseline_corrupt"
    # immutable=1 cannot create a journal or shared-memory file. A live WAL
    # would make this static view stale, so refuse rather than guess the oldest.
    if (db_path.parent / "history.sqlite3-wal").exists():
        return None, None, None, "baseline_unavailable"
    uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('groups','group_files','group_exclusions')")}
            if tables != {"groups", "group_files", "group_exclusions"}:
                return None, None, None, "baseline_corrupt"
            row = db.execute("""SELECT * FROM groups WHERE root=?
                AND source_kind IN (?,?,?) AND status IN ('finished','no_process')
                AND note IS NULL AND policy_version=?
                ORDER BY created_at ASC,id ASC LIMIT 1""",
                (str(root), *_KINDS, SCOPE_POLICY_VERSION)).fetchone()
            if row is None:
                return None, None, None, "no_baseline"
            if (row["root_dev"], row["root_ino"]) != identity:
                return None, None, None, "root_changed"
            group_id = row["id"]
            if (type(group_id) is not str or len(group_id) != 32
                    or any(ch not in "0123456789abcdef" for ch in group_id)):
                return None, None, None, "baseline_corrupt"
            files = db.execute("SELECT path,pre_ref,pre_existed FROM group_files "
                               "WHERE group_id=? ORDER BY path LIMIT ?",
                               (group_id, 2 * MAX_SCOPE_FILES + 1)).fetchall()
            exclusions = db.execute("SELECT path FROM group_exclusions "
                                    "WHERE group_id=? ORDER BY path LIMIT ?",
                                    (group_id, _MAX_EXCLUSIONS + 1)).fetchall()
            if (len(files) > 2 * MAX_SCOPE_FILES or len(exclusions) > _MAX_EXCLUSIONS
                    or row["excluded"] != len(exclusions)):
                return None, None, None, "baseline_corrupt"
            excluded = set()
            for item in exclusions:
                path = item["path"]
                if not _canonical_selection([path]) or path in excluded:
                    return None, None, None, "baseline_corrupt"
                excluded.add(path)
            before = {}
            captured_bytes = 0
            for item in files:
                path, ref, existed = item["path"], item["pre_ref"], item["pre_existed"]
                if not _canonical_selection([path]) or path in before:
                    return None, None, None, "baseline_corrupt"
                if existed == 0:
                    if ref is not None:
                        return None, None, None, "baseline_corrupt"
                    continue
                if existed != 1 or type(ref) is not str or not _covered(path, excluded):
                    return None, None, None, "baseline_corrupt"
                snap = history.load_snapshot(ref)
                if (snap is None or not snap.existed or snap.path != str(root / path)
                        or type(snap.size) is not int or not 0 <= snap.size <= MAX_SCOPE_BYTES
                        or snap.size > MAX_SCOPE_BYTES - captured_bytes):
                    return None, None, None, "baseline_corrupt"
                blob = history.snapshot_blob(snap)
                if blob is None or len(blob) != snap.size:
                    return None, None, None, "baseline_corrupt"
                before[path] = (snap.blob_sha, snap.size, snap.mode, blob)
                captured_bytes += snap.size
            after_info = os.stat(db_path, follow_symlinks=False)
            if (after_info.st_dev, after_info.st_ino, after_info.st_size,
                    after_info.st_mtime_ns) != (db_info.st_dev, db_info.st_ino,
                                             db_info.st_size, db_info.st_mtime_ns):
                return None, None, None, "baseline_unavailable"
            return group_id, before, excluded, None
    except (OSError, sqlite3.Error, TypeError, ValueError, CheckpointRefusal):
        return None, None, None, "baseline_corrupt"


def session_diff(history, root: Path, *, stat_only: bool = False,
                 max_bytes: int = _MAX_DIFF_BYTES,
                 paths: tuple[str, ...] | None = None) -> dict:
    selected = None if paths is None else validate_paths(paths)
    if paths is not None and selected is None:
        return _refused("invalid_paths")
    if (type(stat_only) is not bool or type(max_bytes) is not int
            or not 1 <= max_bytes <= _MAX_DIFF_BYTES):
        return _refused("invalid_options")
    if not HISTORY_SUPPORTED:
        return _refused("unsupported_platform")
    try:
        root = Path(root)
        current_root, identity = history._group_root(root)
        if history.scope.roots != (current_root,):
            return _refused("scope_changed")
        history._protected_scope_paths(root)
    except (OSError, ValueError, TypeError, CheckpointRefusal):
        return _refused("scope_changed")
    baseline, before, old_excluded, error = _read_baseline(history, root, identity)
    if error:
        return _refused(error)
    try:
        current, new_excluded = history._scan_group(root, identity)
    except (OSError, CheckpointRefusal):
        return _refused("current_scan_failed")
    excluded = old_excluded | new_excluded
    added = modified = deleted = binary = 0
    chunks: list[str] = []
    total = 0
    for path in sorted(set(before) | set(current)):
        if selected is not None and not any(
                path == item or path.startswith(item + "/") for item in selected):
            continue
        if not _covered(path, excluded):
            continue
        try:
            if history.scope.resolve(str(root / path)) != root / path:
                excluded.add(path)
                continue
        except FileScopeError:
            excluded.add(path)
            continue
        old = before.get(path)
        new = current.get(path)
        if old is None and new is not None:
            added += 1
        elif old is not None and new is None:
            # A now-unreadable path is not proof of deletion.
            if (root / path).exists() or (root / path).is_symlink():
                excluded.add(path)
                continue
            deleted += 1
        elif old is not None and new is not None and old[:3] != new[:3]:
            modified += 1
        else:
            continue
        old_bytes = old[3] if old is not None else b""
        new_bytes = new[3] if new is not None else b""
        try:
            old_text = old_bytes.decode("utf-8")
            new_text = new_bytes.decode("utf-8")
            if "\x00" in old_text or "\x00" in new_text:
                raise UnicodeError
        except UnicodeError:
            binary += 1
            continue
        if stat_only:
            continue
        if old is not None and new is not None and old[3] == new[3] and old[2] != new[2]:
            line = f"Mode changed: {path} ({old[2]:04o} -> {new[2]:04o})\n"
            total += len(line.encode("utf-8"))
            if total > max_bytes:
                return _refused("diff_too_large")
            chunks.append(line)
            continue
        for line in difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"before/{path}", tofile=f"after/{path}",
        ):
            total += len(line.encode("utf-8"))
            if total > max_bytes:
                return _refused("diff_too_large")
            chunks.append(line)
    try:
        if history._group_root(root)[1] != identity:
            return _refused("root_changed")
    except (OSError, CheckpointRefusal):
        return _refused("root_changed")
    summary = (f"Changed files: added {added}; modified {modified}; deleted {deleted}; "
               f"binary content omitted {binary}; excluded paths {len(excluded)}.")
    return {"ok": True, "diff": "".join(chunks), "stat": summary,
            "baseline": baseline, "excluded": len(excluded), "approximate": True}
