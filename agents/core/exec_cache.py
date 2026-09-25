"""exec_cache.py — where code execution keeps its files, and who may delete them (H667).

The execution sandbox used to make its work directory with ``tempfile.mkdtemp()``: the
system temp root, which is RAM-backed (tmpfs) on several distributions and fills under
load on a box that runs for weeks. Nothing ever removed those directories either.

Where the work directories go, first match wins:

1. ``JARVIS_EXEC_TEMP_DIR`` in the process environment (an absolute path);
2. the owner's ``security.sandbox_temp_dir`` setting (an absolute path);
3. the managed cache, ``<data root>/cache/exec``.

Only the managed cache is ever pruned. A directory the owner pointed at is theirs: this
module creates run directories in it and never bulk-deletes anything there. When the
chosen root cannot be created, the system temp directory is used for that run, with a
warning, and it is not pruned either.

The prune ages each run directory as one group: the newest file anywhere inside it
dates the whole directory, so a live run's fresh output keeps its older script. A
directory whose lock is held (its sandbox is alive, in this process or another one) is
never removed, however old it looks, and only directories this module named
(``sandbox-*``) are considered.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

logger = logging.getLogger("jarvis.exec_cache")

ENV_KEY = "JARVIS_EXEC_TEMP_DIR"
SETTING = ("security", "sandbox_temp_dir")
AGE_SETTING = ("security", "sandbox_temp_max_age_hours")
DEFAULT_MAX_AGE_HOURS = 72
PREFIX = "sandbox-"
LOCK_NAME = ".sandbox.lock"

try:  # POSIX: a run directory's lock is an flock held for the sandbox's lifetime
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None


def managed_root() -> Path:
    from .paths import data_path

    return data_path("cache", "exec")


Getter = Callable[[str, str, object], object]


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


def resolve_root(environ: Mapping[str, str] | None = None,
                 get_value: Getter | None = None) -> tuple[Path, bool]:
    """``(root, managed)``: the directory run directories are made in, and whether it is
    the managed cache (the only one ever pruned). A relative path is not a choice: it
    would move with the working directory, so it is ignored with a warning."""
    env = os.environ if environ is None else environ
    for source, raw in (("the environment's " + ENV_KEY, (env.get(ENV_KEY) or "").strip()),
                        ("security.sandbox_temp_dir", _owner_setting(get_value))):
        if not raw:
            continue
        chosen = Path(raw).expanduser()
        if chosen.is_absolute():
            return chosen, False
        logger.warning("%s is not an absolute path (%r); using the managed cache", source, raw)
    return managed_root(), True


def new_work_dir(environ: Mapping[str, str] | None = None,
                 get_value: Getter | None = None) -> tuple[Path, bool]:
    """A fresh private run directory (mode 0700) under the resolved root: ``(dir, managed)``.
    Falls back to the system temp directory, unmanaged, when the root cannot be made."""
    root, managed = resolve_root(environ, get_value)
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=PREFIX, dir=root)), managed
    except OSError as exc:
        logger.warning("sandbox temp root %s is unusable (%s); using the system temp directory "
                       "for this run", root, exc.strerror or exc.__class__.__name__)
        return Path(tempfile.mkdtemp(prefix=PREFIX)), False


def hold(work_dir: Path) -> int | None:
    """Take the run directory's lock for the sandbox's lifetime: an open descriptor on
    its lock file, flocked on POSIX. On Windows the open handle alone makes the prune's
    rename of the directory fail. None when the file cannot be made (then only age and
    the live list protect the directory)."""
    try:
        fd = os.open(work_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
    return fd


def _newest(path: Path) -> float:
    """The newest mtime in the directory, itself included, never following a link."""
    newest = path.lstat().st_mtime
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


def _held(path: Path) -> bool:
    """Whether a live sandbox holds this directory's lock. Unknown reads as held."""
    if _fcntl is None:
        return False
    lock = path / LOCK_NAME
    try:
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)                          # closing drops the probe's own lock
    return False


def prune(root: Path | None = None, *, managed: bool = True,
          max_age_hours: float = DEFAULT_MAX_AGE_HOURS, live: Iterable[Path] = (),
          now: float | None = None) -> dict:
    """Remove the managed cache's run directories whose newest file is older than
    *max_age_hours*. Never an owner-pointed root (*managed* False), never a directory
    in *live* or one whose lock is held, never an entry this module did not name."""
    root = managed_root() if root is None else root
    report: dict = {"root": str(root), "managed": managed, "deleted": [], "kept": 0}
    if not managed:
        report["skipped"] = "owner_pointed"
        return report
    try:
        entries = list(root.iterdir())
    except FileNotFoundError:
        return report
    except OSError as exc:
        report["skipped"] = f"unreadable ({exc.strerror or exc.__class__.__name__})"
        return report
    cutoff = (time.time() if now is None else now) - max(1.0, float(max_age_hours)) * 3600
    keep = set()
    for path in live:
        with contextlib.suppress(OSError, RuntimeError):
            keep.add(Path(path).resolve())
    for entry in entries:
        try:
            if (not entry.name.startswith(PREFIX) or entry.is_symlink() or not entry.is_dir()
                    or entry.resolve() in keep or _newest(entry) >= cutoff or _held(entry)):
                report["kept"] += 1
                continue
            # Claim it under another name first: a sandbox that holds a file open
            # there (Windows) makes the rename fail, and nothing is half-deleted.
            claimed = entry.with_name(f".pruning-{entry.name}-{secrets.token_hex(4)}")
            entry.rename(claimed)
        except OSError:
            report["kept"] += 1
            continue
        shutil.rmtree(claimed, ignore_errors=True)
        report["deleted"].append(entry.name)
    for stale in root.glob(".pruning-*"):     # a claim an earlier sweep could not finish
        shutil.rmtree(stale, ignore_errors=True)
    return report


def max_age_hours(get_value: Getter | None = None) -> float:
    """The owner's age limit, 72 hours when unset or not a positive number."""
    try:
        hours = float(_getter(get_value)(*AGE_SETTING, DEFAULT_MAX_AGE_HOURS))
    except Exception:  # noqa: BLE001
        return float(DEFAULT_MAX_AGE_HOURS)
    return hours if 0 < hours < float("inf") else float(DEFAULT_MAX_AGE_HOURS)
