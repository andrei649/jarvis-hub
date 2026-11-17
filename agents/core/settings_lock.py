"""The settings-write lock, across processes (review of H257 M1).

``autonomy.mode._write_lock`` serialises settings writers — the approval-dial writers, a
category PUT, an import, a reset, an undo and the coordinator's policy sync — so the
store, the live policy and the audit log never disagree. It used to be a
``threading.RLock``: process-local, so ``nerva config set`` (another process) and the hub
were not serialised at all.

:class:`SettingsWriteLock` keeps the in-process re-entrant lock and adds an advisory
``flock`` on ``<settings dir>/.<store name>.write.lock`` held while the outermost
acquisition lasts, so another process — the hub, a second CLI — waits for it. The wait is
bounded (``WAIT_SECONDS``): a writer that cannot take the lock in time raises
:class:`SettingsLockBusy` and writes nothing, rather than hanging the hub behind a stuck
process. The lock file is opened without following a link and must be a private regular
file. Where ``fcntl`` does not exist (Windows) the lock is in-process only, and says so
in the log once.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

WAIT_SECONDS = 30.0
_POLL = 0.02

try:  # pragma: no cover - platform
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


class SettingsLockBusy(RuntimeError):
    """Another process held the settings-write lock past the bounded wait; nothing written."""


def lock_path(db_path: Path | None = None) -> Path:
    if db_path is None:
        from agents.core import settings_db

        db_path = Path(settings_db.DB_PATH)
    db_path = Path(db_path)
    return db_path.parent / f".{db_path.name}.write.lock"


def _open_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (
                hasattr(os, "getuid") and info.st_uid != os.getuid()):
            raise SettingsLockBusy(f"the settings lock file {path} is not a private regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _flock(path: Path, blocking: bool, timeout: float) -> int | None:
    """An fd holding the exclusive flock, None when not blocking and busy."""
    fd = _open_lock(path)
    deadline = time.monotonic() + (WAIT_SECONDS if timeout is None or timeout < 0 else timeout)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if not blocking:
                os.close(fd)
                return None
            if time.monotonic() >= deadline:
                os.close(fd)
                raise SettingsLockBusy("another process holds the settings-write lock; nothing was "
                                       "written — retry") from None
            time.sleep(_POLL)


class SettingsWriteLock:
    """A re-entrant lock: in-process (``threading.RLock``) plus cross-process (``flock``)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._rlock = threading.RLock()
        self._local = threading.local()
        self._db_path = db_path
        self._warned = False

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if not self._rlock.acquire(blocking, timeout if blocking else -1):
            return False
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            fd = None
            if fcntl is None:
                if not self._warned:
                    logger.warning("settings-write lock: no fcntl here, so it serialises this process only")
                    self._warned = True
            else:
                try:
                    fd = _flock(lock_path(self._db_path), blocking, timeout)
                except BaseException:
                    self._rlock.release()
                    raise
                if fd is None:
                    self._rlock.release()
                    return False
            self._local.fd = fd
        self._local.depth = depth + 1
        return True

    def release(self) -> None:
        depth = getattr(self._local, "depth", 0)
        if depth <= 0:
            raise RuntimeError("release of an unheld settings-write lock")
        self._local.depth = depth - 1
        if depth == 1:
            fd = getattr(self._local, "fd", None)
            self._local.fd = None
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        self._rlock.release()

    def __enter__(self) -> SettingsWriteLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


__all__ = ["SettingsLockBusy", "SettingsWriteLock", "WAIT_SECONDS", "lock_path"]
