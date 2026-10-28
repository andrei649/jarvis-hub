"""Nonblocking provider mutation barrier and same-process selected body drain."""
from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import re
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

from .packages import ProviderPackageError, _secure_root, fcntl


class LifecycleBusy(ProviderPackageError):
    pass


_GUARD = threading.Lock()
_BODIES: dict[tuple[str, str], set] = {}
_UNCERTAIN: dict[tuple[str, str], list[tuple[object, object]]] = {}


def _key(root, provider):
    if (type(provider) is not str
            or re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,127}', provider) is None):
        raise ProviderPackageError('invalid lifecycle provider')
    return str(Path(root).absolute()), provider


class Lease:
    def __init__(self, fd):
        self.fd = fd

    def close(self):
        fd, self.fd = self.fd, -1
        if fd >= 0:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def acquire(root, provider, *, exclusive):
    if fcntl is None or not hasattr(fcntl, 'flock') or not hasattr(os, 'O_NOFOLLOW'):
        raise ProviderPackageError('provider lifecycle lease unavailable')
    _key(root, provider)
    directory, identity = _secure_root(Path(root) / 'lifecycle')
    name = hashlib.sha256(provider.encode('ascii')).hexdigest() + '.lock'
    fd = os.open(directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        opened = os.fstat(fd)
        named = (directory / name).lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) & 0o077 or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or _secure_root(directory)[1] != identity):
            raise ProviderPackageError('provider lifecycle lock identity changed')
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                raise LifecycleBusy('provider lifecycle lease busy') from exc
            raise ProviderPackageError('provider lifecycle lease unavailable') from exc
        named = (directory / name).lstat()
        if ((opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or _secure_root(directory)[1] != identity):
            raise ProviderPackageError('provider lifecycle lock identity changed')
        return Lease(fd)
    except BaseException:
        os.close(fd)
        raise


async def acquire_shared_async(root, provider):
    task = asyncio.create_task(asyncio.to_thread(acquire, root, provider, exclusive=False))
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
def exclusive(root, provider):
    """Refuse a mutation while any attempt or body still owns this provider."""
    with acquire(root, provider, exclusive=True):
        yield


def register_body(root, provider, body):
    key = _key(root, provider)
    with _GUARD:
        _BODIES.setdefault(key, set()).add(body)


def unregister_body(root, provider, body):
    key = _key(root, provider)
    with _GUARD:
        bodies = _BODIES.get(key)
        if bodies is not None:
            bodies.discard(body)
            if not bodies:
                _BODIES.pop(key, None)


def retain_uncertain(root, provider, selection_lease, lifecycle_lease):
    """Keep both FDs live when attempt-pool close cannot prove completion."""
    if selection_lease is None or lifecycle_lease is None:
        raise ProviderPackageError('selected attempt cleanup is unverified')
    with _GUARD:
        _UNCERTAIN.setdefault(_key(root, provider), []).append(
            (selection_lease, lifecycle_lease))


async def drain(root, provider):
    """Finish known same-process readers before an owner mutation tries EX.

    The EX acquisition is still the cross-process and late-registration barrier.
    A canceled caller must wait for already-started body finalizers.
    """
    key = _key(root, provider)
    with _GUARD:
        bodies = tuple(_BODIES.get(key, ()))
    if bodies:
        worker = asyncio.ensure_future(asyncio.gather(
            *(body.aclose() for body in bodies), return_exceptions=True))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        results = worker.result()
        for result in results:
            if isinstance(result, BaseException):
                raise result
        if cancelled:
            raise asyncio.CancelledError


async def quiesce(root, provider, store):
    """Cancel known header-time sends, then finish their selected bodies.

    The later nonblocking EX acquisition is the authoritative barrier for
    unscheduled and cross-process attempts, including cancellation suppression.
    """
    from .packages import _DISPATCH_GUARD, _DISPATCH_TASKS

    current = asyncio.current_task()
    with _DISPATCH_GUARD:
        tasks = tuple(_DISPATCH_TASKS.get(store._root_identity, {}).get(provider, ()))
    for loop, task in tasks:
        if task is not current and not task.done():
            loop.call_soon_threadsafe(task.cancel)
    if tasks:
        loop = asyncio.get_running_loop()
        pending = [task for task_loop, task in tasks
                   if task_loop is loop and task is not current and not task.done()]
        if pending:
            # Responsive cancellation finishes its file-lease cleanup. A
            # cancellation-suppressing attempt leaves EX busy and no mutation.
            await asyncio.wait(pending, timeout=1.0)
    await drain(root, provider)
