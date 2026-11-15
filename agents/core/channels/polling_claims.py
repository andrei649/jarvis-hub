"""Process-lifetime kernel claims for chat polling and SDK connections.

The lock files contain one fixed byte and live beside the install data root, outside
profile backup and purge trees. They are never removed: replacing a locked inode
would allow a second process to acquire a different lock for the same credential.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import threading
from contextlib import suppress
from pathlib import Path

from agents.core.paths import install_root


class ClaimUnavailable(RuntimeError):
    """A fixed, redacted reason for refusing a channel credential claim."""

    def __init__(self, reason: str):
        if reason not in {"busy", "unavailable"}:
            raise ValueError("invalid claim reason")
        self.reason = reason
        super().__init__(reason)


_registry_lock = threading.Lock()
_held: dict[str, PollingClaim] = {}


class PollingClaim:
    """The exact open descriptor which owns one channel credential claim."""

    def __init__(self, fd: int, key: str):
        self._fd = fd
        self._key = key
        self._pid = os.getpid()

    def release(self) -> None:
        """Release this handle once; never release a later holder of the same key."""
        if os.getpid() != self._pid:
            return  # A forked child must never unlock its parent's file description.
        with _registry_lock:
            fd, self._fd = self._fd, -1
            if fd < 0:
                return
            if _held.get(self._key) is self:
                _held.pop(self._key, None)
            try:
                _unlock(fd)
            finally:
                os.close(fd)


def _after_fork_child() -> None:
    global _registry_lock, _held
    inherited = _held
    _held = {}
    _registry_lock = threading.Lock()
    for claim in inherited.values():
        fd, claim._fd = claim._fd, -1
        if fd >= 0:
            with suppress(OSError):
                os.close(fd)  # Closing a duplicated fd is safe; LOCK_UN is not.


def _before_fork() -> None:
    # An acquisition holds this mutex from open through registry insertion. Waiting
    # here prevents a child from inheriting an as-yet unregistered locked fd.
    _registry_lock.acquire()


def _after_fork_parent() -> None:
    _registry_lock.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(before=_before_fork, after_in_parent=_after_fork_parent,
                        after_in_child=_after_fork_child)


def _safe_directory(path: Path) -> None:
    with suppress(FileExistsError):
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("unsafe claim directory")
    if os.name == "nt":
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError("unsafe claim directory")
    elif info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OSError("unsafe claim directory")


def _open_windows(path: Path) -> int:
    """Create/open the final component without following a Windows reparse point."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    create = api.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = api.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    attributes = api.GetFileInformationByHandleEx
    attributes.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    attributes.restype = wintypes.BOOL

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = (("attributes", wintypes.DWORD), ("tag", wintypes.DWORD))

    handle = create(str(path), 0xC0000000, 0x3, None, 4, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("claim file unavailable")
    try:
        info = AttributeTagInfo()
        if not attributes(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("claim file unavailable")
        if info.attributes & 0x400:
            raise OSError("unsafe claim file")
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    try:
        os.set_inheritable(fd, False)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_file(path: Path) -> int:
    try:
        existing = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(existing.st_mode)
                or getattr(existing, "st_file_attributes", 0) & 0x400):
            raise OSError("unsafe claim file")
    if os.name == "nt":
        return _open_windows(path)
    flags = (os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    fd = os.open(path, flags, 0o600)
    try:
        os.set_inheritable(fd, False)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _check_file(fd: int, path: Path) -> None:
    opened = os.fstat(fd)
    linked = path.lstat()
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(linked.st_mode)
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
            or opened.st_nlink != 1):
        raise OSError("unsafe claim file")
    if os.name != "nt" and (opened.st_uid != os.geteuid() or opened.st_mode & 0o077):
        raise OSError("unsafe claim file")


def _lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _fixed_content(fd: int) -> None:
    size = os.fstat(fd).st_size
    if size == 0:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.write(fd, b"\0") != 1:
            raise OSError("claim file unavailable")
    elif size != 1:
        raise OSError("unsafe claim file")
    os.lseek(fd, 0, os.SEEK_SET)
    if os.read(fd, 1) != b"\0":
        raise OSError("unsafe claim file")


_CHANNELS = frozenset({"telegram", "discord", "slack-app", "slack-bot", "ntfy-inbound"})


def _acquire_claim(channel: str, token: str, *, root: Path | None = None) -> PollingClaim:
    if type(channel) is not str or channel not in _CHANNELS or type(token) is not str or not token:
        raise ClaimUnavailable("unavailable")
    try:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        base = (install_root() if root is None else Path(root)).expanduser().resolve()
        directory = base.parent / f".{base.name}-channel-claims"
        path = directory / f"{channel}-{digest}.lock"
        key = str(path)
        with _registry_lock:
            if key in _held:
                raise ClaimUnavailable("busy")
            _safe_directory(directory)
            fd = _open_file(path)
            locked = False
            try:
                _check_file(fd, path)
                try:
                    _lock(fd)
                except OSError as exc:
                    busy = exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
                    if os.name == "nt" and getattr(exc, "winerror", None) == 33:
                        busy = True
                    raise ClaimUnavailable("busy" if busy else "unavailable") from None
                locked = True
                # Windows _locking supports a range past EOF. Read/write only
                # after locking: another handle's locked byte is inaccessible.
                _fixed_content(fd)
                _check_file(fd, path)
                claim = PollingClaim(fd, key)
                _held[key] = claim
                return claim
            except BaseException:
                try:
                    if locked:
                        _unlock(fd)
                finally:
                    os.close(fd)
                raise
    except ClaimUnavailable:
        raise
    except (OSError, ValueError, UnicodeError, RuntimeError, TypeError):
        raise ClaimUnavailable("unavailable") from None


def acquire_telegram_claim(token: str, *, root: Path | None = None) -> PollingClaim:
    """Claim one exact Telegram token's startup/poller."""
    return _acquire_claim("telegram", token, root=root)


def acquire_discord_claim(token: str, *, root: Path | None = None) -> PollingClaim:
    """Claim one exact Discord token's connection startup/lifetime."""
    return _acquire_claim("discord", token, root=root)


def acquire_slack_app_claim(token: str, *, root: Path | None = None) -> PollingClaim:
    """Claim one exact Slack app token's Socket Mode connection lifetime."""
    return _acquire_claim("slack-app", token, root=root)


def acquire_slack_bot_claim(token: str, *, root: Path | None = None) -> PollingClaim:
    """Claim one exact Slack bot token's Socket Mode connection lifetime."""
    return _acquire_claim("slack-bot", token, root=root)


def acquire_ntfy_claim(resource: str, *, root: Path | None = None) -> PollingClaim:
    """Claim one normalized ntfy subscription identity across local profiles.

    The adapter supplies its normalized GET identity tuple without replay query or bearer
    token. Only the domain-separated digest reaches the private lock filename.
    """
    return _acquire_claim("ntfy-inbound", resource, root=root)


__all__ = [
    "ClaimUnavailable", "PollingClaim", "acquire_telegram_claim", "acquire_discord_claim",
    "acquire_slack_app_claim", "acquire_slack_bot_claim", "acquire_ntfy_claim",
]
