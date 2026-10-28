"""Nonblocking cross-process settings-selection lease; no selection authority here.

The lock identity is the active settings DB path, never an arbitrary caller value.
Signed readers require a real flock. Generic built-in writers may continue on
platforms without flock, where signed selection is unavailable.
"""
from __future__ import annotations

import asyncio
import errno
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows has no equivalent signed lease yet.
    fcntl = None


class SelectionUnavailable(RuntimeError):
    """A signed selection cannot prove its store-bound lease identity."""


class SelectionBusy(RuntimeError):
    """A current selected reader or writer holds the cross-process gate."""


class _Unsupported(SelectionUnavailable):
    pass


_LOCAL = threading.local()


def _path(path: str | Path | None) -> Path:
    from agents.core import settings_db

    actual = Path(os.path.abspath(settings_db.DB_PATH))
    proposed = actual if path is None else Path(os.path.abspath(path))
    if proposed != actual or proposed.is_symlink() or proposed.parent.is_symlink():
        raise SelectionUnavailable('selection gate must use the actual nonsymlink settings store')
    return actual


class SelectionLease:
    """An open file-description lease, held until close including response bodies."""

    def __init__(self, fd: int):
        self._fd = fd

    def close(self) -> None:
        fd, self._fd = self._fd, -1
        if fd >= 0:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _validate_store(path: Path, root_fd: int, *, allow_missing: bool) -> None:
    """A second name for this SQLite inode must never get a separate gate."""
    try:
        store_fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                           dir_fd=root_fd)
    except FileNotFoundError:
        if allow_missing:  # First built-in initialization owns the gate before DB creation.
            return
        raise SelectionUnavailable('selection store does not exist') from None
    try:
        opened = os.fstat(store_fd)
        named = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                or opened.st_mode & 0o022 or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise SelectionUnavailable('selection store has an unsafe or aliased identity')
    finally:
        os.close(store_fd)


def _acquire(path: Path, *, exclusive: bool, allow_missing: bool = False) -> SelectionLease:
    if (fcntl is None or not hasattr(fcntl, 'flock') or not hasattr(os, 'O_NOFOLLOW')
            or not hasattr(os, 'O_DIRECTORY') or not hasattr(os, 'O_NONBLOCK')):
        raise _Unsupported('signed selection requires safe file leases')
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or path.is_symlink():
        raise SelectionUnavailable('selection store path changed to a symlink')
    root_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root = os.fstat(root_fd)
        if (not stat.S_ISDIR(root.st_mode) or root.st_uid != os.getuid()
                or root.st_mode & 0o022):
            raise SelectionUnavailable('selection store directory is not privately owned')
        name = f'.{path.name}.selection.lock'
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                     dir_fd=root_fd)
        try:
            opened = os.fstat(fd)
            named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or opened.st_mode & 0o077 or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
                raise SelectionUnavailable('selection lock identity is unsafe')
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                            | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    raise SelectionBusy('selection lease busy; no settings written') from exc
                raise SelectionUnavailable('selection lease unavailable') from exc
            named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise SelectionUnavailable('selection lock changed during acquisition')
            current_root = os.stat(parent, follow_symlinks=False)
            if (root.st_dev, root.st_ino) != (current_root.st_dev, current_root.st_ino):
                raise SelectionUnavailable('selection store directory changed during acquisition')
            _validate_store(path, root_fd, allow_missing=allow_missing)
            return SelectionLease(fd)
        except BaseException:
            os.close(fd)
            raise
    except OSError as exc:
        raise SelectionUnavailable('selection lock path unavailable') from exc
    finally:
        os.close(root_fd)


def acquire_shared(path: str | Path | None = None) -> SelectionLease:
    return _acquire(_path(path), exclusive=False)


async def acquire_shared_async(path: str | Path | None = None) -> SelectionLease:
    """Drain a started offload on cancellation, closing any late acquired fd."""
    task = asyncio.create_task(asyncio.to_thread(acquire_shared, path))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    lease = task.result()
    if cancelled:
        lease.close()
        raise asyncio.CancelledError
    return lease


@contextmanager
def shared(path: str | Path | None = None):
    with acquire_shared(path) as lease:
        yield lease


@contextmanager
def shared_builtin(path: str | Path | None = None):
    """Read a built-in pair when flock is absent; signed leases still refuse."""
    actual = _path(path)
    try:
        lease = _acquire(actual, exclusive=False)
    except _Unsupported:
        lease = None
    try:
        yield lease
    finally:
        if lease is not None:
            lease.close()


@contextmanager
def exclusive(path: str | Path | None = None, *, signed: bool = False):
    """Nonblocking writer fence before planning or opening a SQLite transaction."""
    actual = _path(path)
    key = str(actual)
    held = getattr(_LOCAL, 'held', None)
    if held is None:
        held = _LOCAL.held = {}
    if key in held:
        depth, verified = held[key]
        if signed and not verified:
            raise SelectionUnavailable('signed selection requires a verified file lease')
        held[key] = (depth + 1, verified)
        try:
            yield
        finally:
            held[key] = (depth, verified)
        return
    try:
        lease = _acquire(actual, exclusive=True, allow_missing=not signed)
    except _Unsupported:
        if signed:
            raise
        lease = None
    held[key] = (1, lease is not None)
    try:
        yield
    finally:
        del held[key]
        if lease is not None:
            lease.close()
