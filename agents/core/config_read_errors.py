"""Recovery evidence for unreadable persisted configuration.

Adapted from pinned Hermes hermes_cli/config_read_errors.py and config_backups.py
(MIT license, Nous Research, hermes-agent commit 59b2aeef6c7a). Nerva refuses a
fresh start without valid policy instead of serving permissive defaults.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import threading
import time
from contextlib import ExitStack, suppress
from pathlib import Path

logger = logging.getLogger("jarvis.config")
_warned: set[tuple[str, int, int]] = set()
_lock = threading.Lock()


def _signature(path: Path) -> tuple[str, int, int]:
    try:
        info = path.stat()
        return str(path.resolve()), info.st_mtime_ns, info.st_size
    except OSError:
        return str(path.absolute()), -1, -1


def _snapshot_corrupt(path: Path) -> Path | None:
    """Keep exact file bytes in a private, exclusive copy; never follow a planted link."""
    try:
        root = path.parent / "backups" / "config"
        dest = root / f"{path.name}.corrupt.{time.time_ns()}"
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        with ExitStack() as stack:
            parent_fd = os.open(path.parent, directory)
            stack.callback(os.close, parent_fd)
            backup_fd = _private_subdir(parent_fd, "backups", directory)
            stack.callback(os.close, backup_fd)
            config_fd = _private_subdir(backup_fd, "config", directory)
            stack.callback(os.close, config_fd)

            source_fd = os.open(path, os.O_RDONLY | nofollow)
            source = stack.enter_context(os.fdopen(source_fd, "rb"))
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return None
            target_fd = os.open(dest.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                                stat.S_IRUSR | stat.S_IWUSR, dir_fd=config_fd)
            try:
                with os.fdopen(target_fd, "wb") as target:
                    shutil.copyfileobj(source, target)
            except BaseException:
                os.unlink(dest.name, dir_fd=config_fd)
                raise
        return dest
    except OSError as exc:
        logger.warning("Could not snapshot unreadable settings at %s: %s", path, type(exc).__name__)
        return None


def _private_subdir(parent_fd: int, name: str, flags: int) -> int:
    with suppress(FileExistsError):
        os.mkdir(name, mode=stat.S_IRWXU, dir_fd=parent_fd)
    child_fd = os.open(name, flags, dir_fd=parent_fd)
    os.fchmod(child_fd, stat.S_IRWXU)
    return child_fd


def report_unreadable(path: Path, exc: Exception) -> None:
    """Warn once per path/mtime/size and snapshot persisted corrupt bytes."""
    signature = _signature(path)
    with _lock:
        if signature in _warned:
            return
        _warned.add(signature)
    snapshot = _snapshot_corrupt(path) if not isinstance(exc, OSError) else None
    suffix = f"; corrupt bytes saved to {snapshot}" if snapshot else ""
    logger.warning("Unreadable persisted settings %s (%s)%s", path, type(exc).__name__, suffix)
