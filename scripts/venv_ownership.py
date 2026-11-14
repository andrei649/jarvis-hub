"""Bounded POSIX ownership preflight for an active Python virtual environment.

This module uses only the standard library and is also loaded by the bootstrap before
third-party packages exist. It never repairs the environment and does not provide an
atomic guarantee against concurrent writes by the same account.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

_INTERPRETER_NAME = re.compile(r"python(?:3|[0-9]+\.[0-9]+)?\Z")


def _result(ok: bool, state: str, reason: str | None = None) -> dict[str, object]:
    return {"ok": ok, "state": state, "reason": reason}


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except (ValueError, OSError):
        return False


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode, left.st_uid,
            getattr(left, "st_mtime_ns", None), getattr(left, "st_ctime_ns", None)) == (
        right.st_dev, right.st_ino, right.st_mode, right.st_uid,
        getattr(right, "st_mtime_ns", None), getattr(right, "st_ctime_ns", None))


def _refuse(reason: str) -> dict[str, object]:
    return _result(False, "refused", reason)


def preflight_venv(root: str | os.PathLike, *, uid: int | None = None,
                   max_entries: int = 100_000) -> dict[str, object]:
    """Inspect a venv without following links or changing files.

    A POSIX tree passes only when every in-tree inode belongs to the effective runtime
    UID. Internal symlinks are classified but never traversed. External symlinks are
    refused except the conventional ``bin/python``, ``bin/python3`` and versioned
    interpreter links to a regular file owned by the runtime UID or root.
    """
    if os.name == "nt":
        return _result(True, "ownership_unchecked_windows",
                       "Windows ACL ownership inspection is not implemented")
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
        return _refuse("invalid traversal budget")
    try:
        runtime_uid = os.geteuid() if uid is None else uid
    except (AttributeError, OSError):
        return _refuse("effective UID is unavailable")
    if not isinstance(runtime_uid, int) or isinstance(runtime_uid, bool) or runtime_uid < 0:
        return _refuse("invalid effective UID")

    base = Path(root)
    try:
        root_stat = os.lstat(base)
        if not stat.S_ISDIR(root_stat.st_mode):
            return _refuse("environment root is not a real directory")
        if root_stat.st_uid != runtime_uid:
            return _refuse("environment root is owned by another UID")
        real_root = str(base.resolve(strict=True))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _refuse(f"environment root cannot be inspected ({type(exc).__name__})")

    stack: list[Path] = [base]
    entries_seen = 1
    while stack:
        directory = stack.pop()
        try:
            before = os.lstat(directory)
            if not stat.S_ISDIR(before.st_mode) or before.st_uid != runtime_uid:
                return _refuse("directory changed or is foreign-owned during scan")
            with os.scandir(directory) as rows:
                for row in rows:
                    entries_seen += 1
                    if entries_seen > max_entries:
                        return _refuse("environment traversal budget exceeded")
                    path = Path(row.path)
                    try:
                        info = os.lstat(path)
                    except OSError as exc:
                        return _refuse(f"entry cannot be inspected ({type(exc).__name__})")
                    if info.st_uid != runtime_uid:
                        return _refuse("entry is owned by another UID")
                    mode = info.st_mode
                    if stat.S_ISDIR(mode):
                        stack.append(path)
                    elif stat.S_ISREG(mode):
                        continue
                    elif stat.S_ISLNK(mode):
                        try:
                            resolved = str(path.resolve(strict=True))
                            target_stat = os.stat(path)
                        except (OSError, RuntimeError, TypeError, ValueError) as exc:
                            return _refuse(f"symlink target cannot be inspected ({type(exc).__name__})")
                        if _inside(resolved, real_root):
                            continue  # Internal aliases are not traversed a second time.
                        relative = path.relative_to(base)
                        is_interpreter = (relative.parent == Path("bin")
                                          and _INTERPRETER_NAME.fullmatch(path.name) is not None)
                        try:
                            active_executable = (getattr(sys, "_base_executable", None)
                                                 or sys.executable)
                            active_target = str(Path(active_executable).resolve(strict=True))
                        except (OSError, RuntimeError, TypeError, ValueError):
                            active_target = None
                        is_active_executable = active_target is not None and resolved == active_target
                        allowed_owner = target_stat.st_uid in {runtime_uid, 0} or is_active_executable
                        if (not is_interpreter or not stat.S_ISREG(target_stat.st_mode) or not allowed_owner):
                            return _refuse("outward symlink is not an allowed interpreter link")
                    else:
                        return _refuse("special filesystem entry is not allowed")
            after = os.lstat(directory)
            if not _same_identity(before, after):
                return _refuse("directory changed during scan")
        except OSError as exc:
            return _refuse(f"directory cannot be scanned ({type(exc).__name__})")

    return _result(True, "checked")
