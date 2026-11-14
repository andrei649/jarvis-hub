"""Small read-only projection of the updater's on-disk progress.

The updater's UI helpers intentionally tolerate damaged files. This reader does
not: an absent file is empty progress; an unreadable or ambiguous one is unknown.
It reads only a bounded current record and the final complete receipt line.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from . import hub_update_apply

MAX_CURRENT_BYTES = 128 * 1024
MAX_RECEIPT_TAIL_BYTES = 64 * 1024
_KINDS = frozenset({"update", "rollback"})
_RESULTS = frozenset({"verified", "failed", "refused", "rollback_incomplete",
                      "rollback_failed", "rolled_back"})
_PHASES = frozenset({"started", "backed_up", "fast_forwarded", "dependencies_installed",
                     "restarting", "verifying", "rolling_back", "rolled_back_restarting",
                     *_RESULTS})
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


class UpdateProgressUnavailable(RuntimeError):
    """The durable update state could not be projected safely."""


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    kind: str
    task_id: int | None
    phase: str | None
    result: str | None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    current: ProgressRecord | None
    last: ProgressRecord | None


def _same(before, after) -> bool:
    return before is not None and after is not None and all(
        getattr(before, name) == getattr(after, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _safe_type(value, *, directory: bool) -> bool:
    mode = stat.S_ISDIR if directory else stat.S_ISREG
    return mode(value.st_mode) and not (getattr(value, "st_file_attributes", 0) & _REPARSE)


def _lstat(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _directory(path: Path):
    found = _lstat(path)
    if found is not None and not _safe_type(found, directory=True):
        raise UpdateProgressUnavailable("update progress directory unavailable")
    return found


def _read_exact(fd: int, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            raise UpdateProgressUnavailable("update progress changed during read")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(fd, 1):
        raise UpdateProgressUnavailable("update progress changed during read")
    return b"".join(chunks)


def _read_regular(path: Path, *, tail: bool, cap: int) -> tuple[bytes, bool] | None:
    """Read one stable regular file, at most cap bytes; bool says prefix omitted."""
    before = _lstat(path)
    if before is None:
        return None
    if not _safe_type(before, directory=False) or (not tail and before.st_size > cap):
        raise UpdateProgressUnavailable("update progress file unavailable")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not _safe_type(opened, directory=False) or not _same(before, opened):
            raise UpdateProgressUnavailable("update progress file changed")
        length = min(opened.st_size, cap) if tail else opened.st_size
        if tail and opened.st_size > length:
            os.lseek(fd, opened.st_size - length, os.SEEK_SET)
        data = _read_exact(fd, length)
        if not _same(opened, os.fstat(fd)):
            raise UpdateProgressUnavailable("update progress file changed")
    finally:
        os.close(fd)
    after = _lstat(path)
    if after is None or not _same(before, after):
        raise UpdateProgressUnavailable("update progress file changed")
    return data, before.st_size > length


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate update progress field")
        out[key] = value
    return out


def _json_record(data: bytes) -> ProgressRecord:
    def nonfinite(_value):
        raise ValueError("non-finite update progress")

    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=nonfinite)
    if type(value) is not dict or value.get("kind") not in _KINDS:
        raise UpdateProgressUnavailable("update progress record unavailable")
    task_id = value.get("task_id")
    phase = value.get("phase")
    result = value.get("result")
    if ((task_id is not None and (type(task_id) is not int or not 0 < task_id <= (1 << 63) - 1))
            or (phase is not None and (type(phase) is not str or phase not in _PHASES))
            or (result is not None and (type(result) is not str or result not in _RESULTS))
            or (result is not None and phase != result)
            or (phase in _RESULTS and result != phase)
            or (value["kind"] == "rollback" and (phase in {
                "backed_up", "fast_forwarded", "dependencies_installed", "restarting",
                "verifying", "rolling_back", "verified"} or result == "verified"))):
        raise UpdateProgressUnavailable("update progress record unavailable")
    return ProgressRecord(value["kind"], task_id, phase, result)


def _last_line(data: bytes, *, prefix_omitted: bool) -> bytes:
    if not data or data[-1:] != b"\n":
        raise UpdateProgressUnavailable("update progress receipt incomplete")
    previous = data.rfind(b"\n", 0, len(data) - 1)
    if previous < 0 and prefix_omitted:
        raise UpdateProgressUnavailable("update progress receipt exceeds bound")
    line = data[previous + 1:-1]
    if not line:
        raise UpdateProgressUnavailable("update progress receipt unavailable")
    return line


def read_progress_snapshot() -> ProgressSnapshot:
    """Project current state and newest receipt, or raise on unknown state.

    A missing update directory or file is empty progress. Any existing unsafe,
    malformed, oversized or changing file refuses the entire snapshot.
    """
    try:
        directory = Path(hub_update_apply.state_dir())
        parent = _directory(directory.parent)
        if parent is None:
            if _lstat(directory) is not None:
                raise UpdateProgressUnavailable("update progress parent unavailable")
            return ProgressSnapshot(None, None)
        state = _directory(directory)
        if state is None:
            if not _same(parent, _directory(directory.parent)) or _lstat(directory) is not None:
                raise UpdateProgressUnavailable("update progress directory changed")
            return ProgressSnapshot(None, None)
        current_bytes = _read_regular(directory / "current.json", tail=False,
                                      cap=MAX_CURRENT_BYTES)
        receipt_bytes = _read_regular(directory / "receipts.jsonl", tail=True,
                                      cap=MAX_RECEIPT_TAIL_BYTES)
        if (not _same(parent, _directory(directory.parent))
                or not _same(state, _directory(directory))):
            raise UpdateProgressUnavailable("update progress directory changed")
        current = _json_record(current_bytes[0]) if current_bytes is not None else None
        last = (_json_record(_last_line(receipt_bytes[0], prefix_omitted=receipt_bytes[1]))
                if receipt_bytes is not None else None)
        return ProgressSnapshot(current, last)
    except UpdateProgressUnavailable:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise UpdateProgressUnavailable("update progress unavailable") from exc


__all__ = ["ProgressRecord", "ProgressSnapshot", "UpdateProgressUnavailable",
           "read_progress_snapshot"]
