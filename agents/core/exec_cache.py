"""exec_cache.py — where code execution keeps its files, and who may delete them (H667).

The execution sandbox used to make its work directory with ``tempfile.mkdtemp()``: the
system temp root, which is RAM-backed (tmpfs) on several distributions and fills under
load on a box that runs for weeks. Nothing ever removed those directories either.

Where the work directories go, first match wins:

1. ``JARVIS_EXEC_TEMP_DIR`` in the process environment (an absolute path);
2. the owner's ``security.sandbox_temp_dir`` setting (an absolute path);
3. the managed cache, ``<data root>/cache/exec``.

A value that is not an absolute path, or cannot be read as one (``~nosuchuser``, a NUL
byte), is not a choice: it is skipped with a warning (review-H667 m1). Only the managed
cache is ever pruned, and it is pruned whatever the current choice is (review-H667 m5).
A directory the owner pointed at is theirs: run directories are made in it and nothing
there is ever bulk-deleted. When the chosen root cannot be used, the system temp
directory is used for that run, with a warning, and it is not pruned either.

The prune ages each run directory as one group: the newest file anywhere inside it
dates the whole directory, so a live run's fresh output keeps its older script. A file
is dated by the older of its mtime and its ctime, so an mtime set in the future never
keeps a directory forever (the kernel sets the ctime; review-H667 m6).

A live sandbox holds its directory's lock, which lives OUTSIDE the run directory, in
``<root>/.locks/<name>.lock``: code run in the directory cannot remove, replace or
forge it (review-H667 m6). The lock is an flock and records the owner's host and pid,
so where flock does not work (some network filesystems), a lock whose pid is alive on
this host still reads as held, and one from another host is kept (review-H667 m7).
Only directories this module named (``nerva-sandbox-*``) are considered, in a managed
root that is a real directory owned by this user and not writable by others.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import shutil
import socket
import stat
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

logger = logging.getLogger("jarvis.exec_cache")

ENV_KEY = "JARVIS_EXEC_TEMP_DIR"
SETTING = ("security", "sandbox_temp_dir")
AGE_SETTING = ("security", "sandbox_temp_max_age_hours")
DEFAULT_MAX_AGE_HOURS = 72
MIN_AGE_HOURS = 1.0
PREFIX = "nerva-sandbox-"
LOCKS = ".locks"
CLAIM = ".pruning-"

try:  # POSIX: a run directory's lock is an flock held for the sandbox's lifetime
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None

Getter = Callable[[str, str, object], object]


def managed_root() -> Path:
    from .paths import data_path

    return data_path("cache", "exec").absolute()


def _getter(get_value: Getter | None) -> Getter:
    if get_value is not None:
        return get_value
    from .settings_db import get_value as settings_value

    return settings_value


def _owner_setting(get_value: Getter | None) -> str:
    try:
        value = _getter(get_value)(*SETTING, "")
    except Exception:  # noqa: BLE001  (no settings store: nothing chosen)
        return ""
    return value.strip() if isinstance(value, str) else ""


def _as_root(raw: str) -> Path | None:
    """An absolute root from *raw*, or None when it is not one."""
    if "\x00" in raw:
        return None
    try:
        chosen = Path(raw).expanduser()
    except (RuntimeError, ValueError):       # ~nosuchuser
        return None
    return chosen if chosen.is_absolute() else None


def choice_problem(raw: object) -> str | None:
    """Why *raw* cannot be a sandbox root, or None ("" is no choice: the managed cache)."""
    if not isinstance(raw, str):
        return "expected a string"
    if raw.strip() and _as_root(raw.strip()) is None:
        return "expected an absolute path (or empty for the managed cache)"
    return None


def resolve_root(environ: Mapping[str, str] | None = None,
                 get_value: Getter | None = None) -> tuple[Path, bool]:
    """``(root, managed)``: the directory run directories are made in, and whether it is
    the managed cache (the only one ever pruned)."""
    env = os.environ if environ is None else environ
    managed = managed_root()
    for source, raw in (("the environment's " + ENV_KEY, (env.get(ENV_KEY) or "").strip()),
                        ("security.sandbox_temp_dir", _owner_setting(get_value))):
        if not raw:
            continue
        chosen = _as_root(raw)
        if chosen is None:
            logger.warning("%s is not an absolute path (%r); skipped", source, raw)
            continue
        if os.path.normcase(os.path.abspath(chosen)) == os.path.normcase(str(managed)):
            return managed, True
        return chosen, False
    return managed, True


def _secure_managed(root: Path) -> None:
    """The managed root is this user's own: private when this user owns it."""
    with contextlib.suppress(OSError, AttributeError):
        info = os.lstat(root)
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077:
            os.chmod(root, 0o700)


def new_work_dir(environ: Mapping[str, str] | None = None,
                 get_value: Getter | None = None) -> tuple[Path, bool]:
    """A fresh private run directory (mode 0700, absolute) under the resolved root:
    ``(dir, managed)``. Falls back to the system temp directory, unmanaged, when the
    root cannot be used."""
    try:
        root, managed = resolve_root(environ, get_value)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if managed:
            _secure_managed(root)
        return Path(tempfile.mkdtemp(prefix=PREFIX, dir=root)).absolute(), managed
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("sandbox temp root is unusable (%s); using the system temp directory "
                       "for this run", getattr(exc, "strerror", None) or exc.__class__.__name__)
        return Path(tempfile.mkdtemp(prefix=PREFIX)).absolute(), False


def _lock_path(work_dir: Path) -> Path:
    return work_dir.parent / LOCKS / f"{work_dir.name}.lock"


def hold(work_dir: Path) -> int | None:
    """Take the run directory's lock for the sandbox's lifetime: an open descriptor on
    ``<root>/.locks/<name>.lock``, flocked on POSIX, holding ``host pid`` (on Windows,
    with no flock, that record alone protects it). None when it cannot be made
    (logged: then only age and the live list protect the directory)."""
    lock = _lock_path(work_dir)
    try:
        lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        logger.warning("sandbox run directory %s has no lock (%s): only its age protects it "
                       "from another process's prune", work_dir.name, exc.strerror or exc)
        return None
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError as exc:
            logger.warning("sandbox run directory %s: flock unavailable (%s); its owner "
                           "record still protects it on this host", work_dir.name,
                           exc.strerror or exc)
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        os.write(fd, f"{socket.gethostname()} {os.getpid()}\n".encode())
    return fd


def release(fd: int | None, work_dir: Path) -> None:
    """A sandbox that is gone drops its lock: the descriptor and the lock file."""
    if fd is None:
        return
    with contextlib.suppress(OSError):
        _lock_path(work_dir).unlink()
    with contextlib.suppress(OSError):
        os.close(fd)


def _date(info: os.stat_result) -> float:
    return min(info.st_mtime, info.st_ctime)


def _newest(path: Path) -> float:
    """The newest date in the directory, itself included, never following a link."""
    newest = _date(path.lstat())
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            try:
                newest = max(newest, _date(os.lstat(os.path.join(dirpath, name))))
            except OSError:
                continue
    return newest


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _held(lock: Path) -> bool:
    """Whether a live sandbox holds this lock. Unknown reads as held."""
    try:
        info = os.lstat(lock)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if not stat.S_ISREG(info.st_mode):
        return False                          # not a lock this module made
    try:
        fd = os.open(lock, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return True
    try:
        if _fcntl is not None:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except OSError:
                return True
        try:
            host, _, pid = os.read(fd, 256).decode("utf-8", "replace").strip().partition(" ")
        except OSError:
            return True
        if not host:
            return False
        if host != socket.gethostname():
            return True                       # another host's: nothing here can tell
        return pid.isdigit() and _pid_alive(int(pid))
    finally:
        os.close(fd)                          # closing drops the probe's own lock


def _root_problem(root: Path) -> str | None:
    """Why the managed root must not be swept, or None."""
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return f"unreadable ({exc.strerror or exc.__class__.__name__})"
    if stat.S_ISLNK(info.st_mode):
        return "a link"
    if not stat.S_ISDIR(info.st_mode):
        return "not a directory"
    if hasattr(os, "getuid"):
        if info.st_uid != os.getuid():
            return "owned by another user"
        if info.st_mode & 0o022:
            return "writable by other users"
    return None


def prune(root: Path | None = None, *, managed: bool = True,
          max_age_hours: float = DEFAULT_MAX_AGE_HOURS, live: Iterable[Path] = (),
          now: float | None = None) -> dict:
    """Remove the managed cache's run directories whose newest file is older than
    *max_age_hours* (at least one hour). Never an owner-pointed root (*managed* False),
    never a directory in *live* or one whose lock is held, never an entry this module
    did not name. ``_scheduler_status`` says a sweep that could not run."""
    root = managed_root() if root is None else root
    report: dict = {"root": str(root), "managed": managed, "deleted": [], "kept": 0}
    if not managed:
        report.update(skipped="owner_pointed", _scheduler_status="skipped")
        return report
    problem = _root_problem(root)
    if problem == "missing":
        return report
    if problem is not None:
        logger.warning("sandbox cache %s not pruned: it is %s", root, problem)
        report.update(skipped=problem, _scheduler_status="failed")
        return report
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        report.update(skipped=f"unreadable ({exc.strerror or exc.__class__.__name__})",
                      _scheduler_status="failed")
        return report
    cutoff = (time.time() if now is None else now) - max(MIN_AGE_HOURS, float(max_age_hours)) * 3600
    keep = set()
    for path in live:
        with contextlib.suppress(OSError, RuntimeError):
            keep.add(Path(path).resolve())
    for entry in entries:
        try:
            if (not entry.name.startswith(PREFIX) or entry.is_symlink() or not entry.is_dir()
                    or entry.resolve() in keep or _newest(entry) >= cutoff
                    or _held(_lock_path(entry))):
                report["kept"] += 1
                continue
            # Claim it under another name first: a sandbox that holds a file open
            # there (Windows) makes the rename fail, and nothing is half-deleted.
            claimed = entry.with_name(f"{CLAIM}{entry.name}-{secrets.token_hex(4)}")
            entry.rename(claimed)
        except OSError:
            report["kept"] += 1
            continue
        if claimed.is_symlink():              # swapped for a link after the checks
            with contextlib.suppress(OSError):
                claimed.unlink()
            report["kept"] += 1
            continue
        shutil.rmtree(claimed, ignore_errors=True)
        with contextlib.suppress(OSError):
            _lock_path(entry).unlink()
        report["deleted"].append(entry.name)
    _finish_claims(root)
    _drop_orphan_locks(root)
    if report["deleted"]:
        logger.info("sandbox cache: %d run director(y/ies) pruned, %d kept",
                    len(report["deleted"]), report["kept"])
    return report


def _finish_claims(root: Path) -> None:
    """Remove a claim an earlier sweep could not finish; a link is only unlinked."""
    for stale in root.glob(f"{CLAIM}*"):
        with contextlib.suppress(OSError):
            if stale.is_symlink() or not stale.is_dir():
                stale.unlink()
                continue
        shutil.rmtree(stale, ignore_errors=True)


def _drop_orphan_locks(root: Path) -> None:
    """A lock whose run directory is gone, and that nobody holds, is removed."""
    locks = root / LOCKS
    with contextlib.suppress(OSError):
        if locks.is_symlink() or not locks.is_dir():
            return
        for lock in locks.iterdir():
            name = lock.name.removesuffix(".lock")
            if name.startswith(PREFIX) and not (root / name).exists() and not _held(lock):
                with contextlib.suppress(OSError):
                    lock.unlink()


def max_age_hours(get_value: Getter | None = None) -> float:
    """The owner's age limit, 72 hours when unset or not a positive number."""
    try:
        hours = float(_getter(get_value)(*AGE_SETTING, DEFAULT_MAX_AGE_HOURS))
    except Exception:  # noqa: BLE001
        return float(DEFAULT_MAX_AGE_HOURS)
    return hours if 0 < hours < float("inf") else float(DEFAULT_MAX_AGE_HOURS)
