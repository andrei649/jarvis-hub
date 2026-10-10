"""H689 — one durable identity per install, and one hub per data root.

Hermes names an install once and keeps the name; Nerva had only an analytics id that a
broken record re-minted. Here:

- **The install id.** One 32-hex opaque id in ``<install root>/install_id``, minted once under
  an in-process lock and a cross-process file lock (``fcntl.flock``, or ``msvcrt.locking``
  on Windows), written atomically (mkstemp, fsync, ``os.replace``, directory fsync) and
  read back before it is returned. :func:`install_id` returns ``None`` — never a fresh or
  a throw-away value — when the file cannot be read, holds anything but an id, or cannot
  be written: a changed identity would silently orphan everything scoped to the old one.
- **One hub per root.** :func:`acquire_hub_lock` holds ``<data root>/hub.lock`` for the
  life of the hub (``serve.py``, and the app's lifespan for a bare ``uvicorn
  agents.web:app``); a second hub on the same root is refused and told the holder's pid.
  The lock is the kernel's, so a crashed hub leaves nothing to clean. H262 review:
  :func:`holds_hub_lock` and :func:`hub_lock_held_elsewhere` (a read-only probe of the pid
  in ``hub.lock`` — it never takes the lock and never creates the data root) let a
  coordinator leave the lifecycle sweep to a running hub.
- **Profiles.** ``JARVIS_PROFILE=<name>`` gives each profile its own data root, hub lock,
  settings and credentials while all profiles share the unprofiled install id.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import stat
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger("jarvis.install_identity")

ID_FILE = "install_id"
LOCK_FILE = "install_id.lock"
HUB_LOCK_FILE = "hub.lock"
ID_RE = re.compile(r"^[0-9a-f]{32}$")

#: Windows locks are mandatory: the byte locked sits past the pid a hub writes at the start
#: of hub.lock, so a refused hub can still read who holds it.
_NT_LOCK_BYTE = 64

_lock = threading.Lock()
_cache: dict[str, str] = {}
_hub_handle = None

UNAVAILABLE_REASON = "install_identity_unavailable"
UNAVAILABLE_MESSAGE = (
    "install identity unavailable; inspect install_id in the install root and direct "
    "profile roots, reconcile conflicting or damaged legacy IDs, then re-pair "
    "identity-bound devices"
)


class InstallIdentityUnavailable(RuntimeError):
    """An identity-bound grant or pairing cannot safely be created."""

    def __init__(self) -> None:
        super().__init__(UNAVAILABLE_MESSAGE)
        self.reason = UNAVAILABLE_REASON


class HubAlreadyRunning(RuntimeError):
    """Another hub holds this data root."""

    def __init__(self, root: Path, pid: str) -> None:
        super().__init__(f"another hub (pid {pid or 'unknown'}) is running on {root}")
        self.root = root
        self.pid = pid


def _identity_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    from agents.core.paths import install_root

    return install_root()


def _hub_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    from agents.core.paths import data_root
    return data_root()


def require_install_id() -> str:
    """An identity-bound operation must fail before issuing an unscoped credential."""
    value = install_id()
    if value is None:
        raise InstallIdentityUnavailable()
    return value


def _file_lock(handle, *, blocking: bool) -> None:
    """An exclusive lock on an open file; raises OSError when it is held (non-blocking)."""
    if os.name == "nt":                                    # pragma: no cover - Windows
        import msvcrt

        # Windows cannot lock a byte past EOF. Pad with spaces rather than NULs so
        # hub.lock's readable PID remains a plain number after strip().
        handle.seek(0, os.SEEK_END)
        missing = _NT_LOCK_BYTE + 1 - handle.tell()
        if missing > 0:
            handle.write(" " * missing)
            handle.flush()
        handle.seek(_NT_LOCK_BYTE)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def _file_unlock(handle) -> None:
    if os.name == "nt":                                    # pragma: no cover - Windows
        import msvcrt

        handle.seek(_NT_LOCK_BYTE)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read(path: Path) -> str | None:
    """The stored id, or None when there is none. Raises ValueError for a file that
    exists but holds anything else, and OSError when it cannot be read."""
    if path.is_symlink():
        raise ValueError("symlinked id")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("not a regular id file")
    except FileNotFoundError:
        return None
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise ValueError("not an id") from exc
    if not ID_RE.match(text):
        raise ValueError("not an id")
    return text


def _legacy_id(base: Path) -> str | None:
    """One unambiguous direct-profile ID, while the shared lock is held.

    Never follow a profile directory or ID symlink, and never treat a malformed
    legacy file as absence. Those conditions need owner reconciliation.
    """
    from agents.core.paths import PROFILE_ENV, profile_error

    siblings = base.parent / f"{base.name}-profiles"
    if not siblings.exists() and not siblings.is_symlink():
        return None
    if siblings.is_symlink() or not siblings.is_dir():
        raise ValueError("unsafe profile root")
    found: set[str] = set()
    for profile in siblings.iterdir():
        if profile_error({PROFILE_ENV: profile.name}) is not None or profile.name == "default":
            continue
        if profile.is_symlink():
            raise ValueError("symlinked profile")
        if not profile.is_dir():
            continue
        legacy = profile / ID_FILE
        if legacy.is_symlink():
            raise ValueError("symlinked legacy id")
        value = _read(legacy)
        if value is not None:
            found.add(value)
        if len(found) > 1:
            raise ValueError("conflicting legacy ids")
    return next(iter(found), None)


def _fsync_dir(folder: Path) -> None:
    try:
        fd = os.open(str(folder), os.O_RDONLY)
    except OSError:
        return                                             # no directory fds (Windows)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path: Path, value: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".install_id-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def install_id(root: str | Path | None = None) -> str | None:
    """This install's id, minted on first use; None when it cannot be read or kept."""
    base = _identity_root(root)
    key = str(base)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    path = base / ID_FILE
    with _lock:
        try:
            value = _read(path)        # written atomically: a kept id needs no lock to read
            if value is None:
                base.mkdir(parents=True, exist_ok=True)
                with open(base / LOCK_FILE, "a+", encoding="ascii") as guard:
                    _file_lock(guard, blocking=True)
                    try:
                        value = _read(path)
                        if value is None:
                            prior = _legacy_id(base) if root is None else None
                            _write(path, prior or secrets.token_hex(16))
                            value = _read(path)            # read back what landed
                    finally:
                        _file_unlock(guard)
        except (OSError, ValueError) as exc:
            logger.warning("%s at %s (%s)", UNAVAILABLE_MESSAGE, path, type(exc).__name__)
            return None
        if value is None:                                  # pragma: no cover - a write that vanished
            return None
        _cache[key] = value
        return value


def forget_cache() -> None:
    """Tests and a changed data root: read the id from disk again."""
    _cache.clear()


def _open_hub_lock(path: Path):
    """Open the existing lock inode for in-place PID updates, without append mode."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        return os.fdopen(descriptor, "r+", encoding="ascii")
    except BaseException:
        os.close(descriptor)
        raise


def acquire_hub_lock(root: str | Path | None = None):
    """Hold ``hub.lock`` under the data root for this process's life; raise
    :class:`HubAlreadyRunning` when another hub holds it. Idempotent in-process."""
    global _hub_handle
    if _hub_handle is not None:
        return _hub_handle
    base = _hub_root(root)
    base.mkdir(parents=True, exist_ok=True)
    handle = _open_hub_lock(base / HUB_LOCK_FILE)   # held until exit, same inode
    try:
        _file_lock(handle, blocking=False)
    except OSError:
        try:
            handle.seek(0)
            pid = handle.read().strip()[:16]
        except (OSError, ValueError):                      # unreadable: still refused
            pid = ""
        finally:
            handle.close()
        raise HubAlreadyRunning(base, pid) from None
    handle.seek(0)
    # POSIX can shorten the pid file. On Windows byte 64 is locked; truncating
    # the file below it would remove the very byte whose lock protects this hub.
    if os.name != "nt":
        handle.truncate()
    pid = str(os.getpid())
    handle.write(pid.ljust(_NT_LOCK_BYTE + 1) if os.name == "nt" else pid)
    handle.flush()
    _hub_handle = handle
    return handle


def holds_hub_lock() -> bool:
    """H262 review — whether this process holds ``hub.lock`` (it is the hub)."""
    return _hub_handle is not None


def _pid_alive(pid: int) -> bool:
    """Whether *pid* is a live process. POSIX: ``os.kill(pid, 0)`` — a permission error is
    a live process of another user, no such process is a dead one. Windows (where
    ``os.kill`` would end the process): the exec cache's handle-based check."""
    if os.name == "nt":
        from agents.core.exec_cache import _pid_alive as alive_on_windows

        return alive_on_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def hub_lock_held_elsewhere(root: str | Path | None = None) -> bool:
    """H262 review — whether another process (a running hub) holds ``hub.lock`` under the
    data root. Read-only (review round 2): the pid the hub wrote in the file is read, the
    lock itself is never taken, so a hub starting at that moment is never refused because
    of the probe. An empty, missing or unreadable file, or anything but a pid, is no hub;
    this process's pid, or its own hold, is not "elsewhere"; a dead process's stale pid is
    no hub. A hub between truncating the file and writing its pid reads as none (a window
    of one write). The data root and the file are never created.

    What a pid cannot tell: a crashed hub's pid reused by another process reads as a hub
    (the coordinator then skips its sweeps until that process exits: nothing is deleted),
    and a hub in another pid namespace sharing the data root (a separate container) reads
    as none. The shipped compose file does not share a data root between containers."""
    if _hub_handle is not None:
        return False
    try:
        with open(_hub_root(root) / HUB_LOCK_FILE, encoding="ascii") as handle:
            text = handle.read(32).strip()
    except (OSError, ValueError):
        return False
    if not text.isdigit():
        return False
    pid = int(text)
    if pid <= 0 or pid == os.getpid():
        return False
    return _pid_alive(pid)


def release_hub_lock() -> None:
    global _hub_handle
    handle, _hub_handle = _hub_handle, None
    if handle is not None:
        try:
            _file_unlock(handle)
        finally:
            handle.close()


__all__ = [
    "HUB_LOCK_FILE", "HubAlreadyRunning", "ID_FILE", "LOCK_FILE", "InstallIdentityUnavailable",
    "UNAVAILABLE_MESSAGE", "UNAVAILABLE_REASON", "acquire_hub_lock", "forget_cache",
    "holds_hub_lock", "hub_lock_held_elsewhere", "install_id", "release_hub_lock",
    "require_install_id",
]
