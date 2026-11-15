"""Cross-instance mutation lock for small extension metadata stores.

This helper owns only a persistent sibling lock file. It never reads or writes the
store payload. POSIX uses flock + O_NOFOLLOW; the Windows fallback validates the
opened file against the path before locking because O_NOFOLLOW is unavailable.
"""
from __future__ import annotations

import contextlib
import os
import stat
import threading
from pathlib import Path


class StoreLockError(ValueError):
    """Bounded failure acquiring or releasing an extension-store mutation lock."""

    reason = "extension_store_lock_unavailable"

    def __init__(self) -> None:
        super().__init__(self.reason)


_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _thread_locks_guard:
        return _thread_locks.setdefault(key, threading.RLock())


def _regular_stat_or_missing(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise StoreLockError() from None
    if not stat.S_ISREG(info.st_mode):
        raise StoreLockError()
    return info


def _same_identity(left, right) -> bool:
    return (left.st_ino != 0 and right.st_ino != 0
            and left.st_dev == right.st_dev and left.st_ino == right.st_ino)


def _verify_opened_path(fd: int, path: Path, before=None) -> None:
    try:
        opened = os.fstat(fd)
        current = path.lstat()
    except OSError:
        raise StoreLockError() from None
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode)
            or (before is not None and not _same_identity(before, current))
            or not _same_identity(opened, current)):
        raise StoreLockError()


@contextlib.contextmanager
def locked_store(path: str | Path):
    """Serialize a store mutation by path across threads and processes.

    The sibling `.lock` inode is persistent and must not be unlinked: removing it
    while another process holds it can split writers over different lock inodes.
    """
    store_path = Path(path)
    lock_path = store_path.with_name(store_path.name + ".lock")
    fd = None
    acquired = False
    with _thread_lock(store_path):
        try:
            store_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            before = _regular_stat_or_missing(lock_path)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(lock_path, flags, 0o600)
            _verify_opened_path(fd, lock_path, before)
            if os.name == "nt":  # pragma: no cover - Windows CI
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            acquired = True
            # The path could be swapped while this process waited on the inode lock.
            # Verify again while holding it so writers cannot split across inodes.
            _verify_opened_path(fd, lock_path, before)
        except (OSError, ImportError, StoreLockError):
            if fd is not None:
                if acquired:
                    with contextlib.suppress(OSError, ImportError):
                        if os.name == "nt":  # pragma: no cover - Windows CI
                            import msvcrt
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_UN)
                with contextlib.suppress(OSError):
                    os.close(fd)
            raise StoreLockError() from None
        try:
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":  # pragma: no cover - Windows CI
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
            except (OSError, ImportError):
                raise StoreLockError() from None
            finally:
                if fd is not None:
                    os.close(fd)


__all__ = ["StoreLockError", "locked_store"]
