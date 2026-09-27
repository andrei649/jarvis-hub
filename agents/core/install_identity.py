"""H689 — one durable identity per install, and one hub per data root.

Hermes names an install once and keeps the name; Nerva had only an analytics id that a
broken record re-minted. Here:

- **The install id.** One 32-hex opaque id in ``<data root>/install_id``, minted once under
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
- **Profiles.** ``JARVIS_PROFILE=<name>`` (see :func:`agents.core.paths.data_root`) gives
  each profile its own data root, beside the default one, and with it its own id, lock,
  settings and secret store (``agents/core/secrets.py`` resolves it under the data root the
  process starts with). The ``.env`` files are not per profile: every profile reads the
  repo's and the data home's.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
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


class HubAlreadyRunning(RuntimeError):
    """Another hub holds this data root."""

    def __init__(self, root: Path, pid: str) -> None:
        super().__init__(f"another hub (pid {pid or 'unknown'}) is running on {root}")
        self.root = root
        self.pid = pid


def _root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    from agents.core.paths import data_root

    return data_root()


def _file_lock(handle, *, blocking: bool) -> None:
    """An exclusive lock on an open file; raises OSError when it is held (non-blocking)."""
    if os.name == "nt":                                    # pragma: no cover - Windows
        import msvcrt

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
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise ValueError("not an id") from exc
    if not ID_RE.match(text):
        raise ValueError("not an id")
    return text


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
    base = _root(root)
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
                            _write(path, secrets.token_hex(16))
                            value = _read(path)            # read back what landed
                    finally:
                        _file_unlock(guard)
        except (OSError, ValueError) as exc:
            logger.warning("install id unavailable at %s (%s): not minting a new one", path, type(exc).__name__)
            return None
        if value is None:                                  # pragma: no cover - a write that vanished
            return None
        _cache[key] = value
        return value


def forget_cache() -> None:
    """Tests and a changed data root: read the id from disk again."""
    _cache.clear()


def acquire_hub_lock(root: str | Path | None = None):
    """Hold ``hub.lock`` under the data root for this process's life; raise
    :class:`HubAlreadyRunning` when another hub holds it. Idempotent in-process."""
    global _hub_handle
    if _hub_handle is not None:
        return _hub_handle
    base = _root(root)
    base.mkdir(parents=True, exist_ok=True)
    handle = open(base / HUB_LOCK_FILE, "a+", encoding="ascii")   # noqa: SIM115 - held until exit
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
    handle.truncate()
    handle.write(str(os.getpid()))
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
    of one write). The data root and the file are never created."""
    if _hub_handle is not None:
        return False
    try:
        with open(_root(root) / HUB_LOCK_FILE, encoding="ascii") as handle:
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
    "HUB_LOCK_FILE", "HubAlreadyRunning", "ID_FILE", "LOCK_FILE", "acquire_hub_lock", "forget_cache",
    "holds_hub_lock", "hub_lock_held_elsewhere", "install_id", "release_hub_lock",
]
