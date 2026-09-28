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
forge it (review-H667 m6). The lock is an flock (POSIX) and records its owner: host,
pid, whether the flock was taken, the kernel's boot id and the pid's start time. The
record is written before the lock has its name, so a lock is never seen empty.

Whether a lock is held (review-H667b m1, M1; review-H667c):

- a probe that finds the flock busy is the answer: held. Any other flock error (a
  filesystem that refuses flock) reads the record instead of guessing;
- on the kernel that wrote it (same boot id, or same host where there is no boot id),
  a record whose writer took the flock is held exactly while the flock is: a crashed
  sandbox whose pid came back (the hub is pid 1 in a container) is free. So is one
  from before a reboot of this host, and one from before the flag existed (its writer
  always took the flock), when the probe gets the flock;
- a record written without a flock (Windows, a filesystem without flock) is held while
  its pid is alive with the same start time, and only when it was numbered in this pid
  namespace; on Windows the process table is asked, never ``os.kill(pid, 0)`` (signal 0
  is CTRL_C_EVENT there);
- another host's record, a record from another pid namespace, a record whose writer
  held a flock the probe could not test, and a record with a pid no hold writes are
  kept until the directory (or the orphan lock) is ten times the age limit old: nothing
  here can tell whether they are alive, and nothing may keep a directory forever. A
  lock that cannot be judged at all is kept and logged; the sweep goes on.

Only directories this module named (``nerva-sandbox-*``) are considered, in a managed
root that is a real directory owned by this user and not writable by others. To move
the managed cache, set ``JARVIS_EXEC_TEMP_DIR`` (an owner-pointed root, never pruned);
a managed cache that is itself a link is never pruned.
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
FOREIGN_FACTOR = 10          # another host's record is kept until 10x the age limit
_WINDOWS = os.name == "nt"
_PID_LIMIT = 2 ** 32 if _WINDOWS else 2 ** 22   # Linux's pid_max ceiling
#: Reparse tags that make a directory a link: a junction (mount point) and a symlink. A
#: cloud placeholder (OneDrive) carries another tag and is a real directory.
_LINK_REPARSE_TAGS = frozenset({0xA0000003, 0xA000000C})

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
    """An absolute root from *raw*, or None when it is not one (a control character,
    a NUL or a newline, is never part of one: review-H667b nit 1)."""
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in raw):
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


def _same_dir(a: Path, b: Path) -> bool:
    """Whether two spellings name one directory: by identity when both exist, else by
    their resolved paths (review-H667b m3: a link or a ``..`` is the same cache)."""
    with contextlib.suppress(OSError):
        return os.path.samefile(a, b)
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except (OSError, RuntimeError):
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


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
        if _same_dir(chosen, managed):
            return managed, True
        return chosen, False
    return managed, True


def _secure_managed(root: Path) -> None:
    """The managed root is this user's own: private when this user owns it."""
    with contextlib.suppress(OSError, AttributeError):
        info = os.lstat(root)
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077:
            os.chmod(root, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions


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


def _boot_id() -> str:
    """This kernel's boot id (Linux), or ""."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return ""


def _start_token(pid: int) -> str:
    """What tells this pid from a later process given the same number: the start tick
    since boot on Linux, the creation time on Windows, or "" when unknown."""
    if _WINDOWS:
        process = _windows_process(pid)
        return process[1] if process else ""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except (OSError, ValueError):
        return ""
    fields = text.rpartition(")")[2].split()
    return fields[19] if len(fields) > 19 else ""       # field 22, starttime


def _pid_ns() -> str:
    """This process's pid namespace (Linux: the inode of ``/proc/self/ns/pid``), or "":
    a pid means something only in the namespace that numbered it (review-H667c nit 2)."""
    try:
        return str(os.stat("/proc/self/ns/pid").st_ino)
    except OSError:
        return ""


def _record(flocked: bool) -> bytes:
    pid = os.getpid()
    return (f"{socket.gethostname()} {pid} flock={int(flocked)} boot={_boot_id()} "
            f"start={_start_token(pid)} ns={_pid_ns()}\n").encode()


def _parse(text: str) -> dict:
    words = text.split()
    record = {"host": words[0] if words else "", "pid": words[1] if len(words) > 1 else ""}
    for word in words[2:]:
        key, sep, value = word.partition("=")
        if sep:
            record[key] = value
    return record


def _locks_dir(work_dir: Path) -> Path | None:
    """``<root>/.locks``, made private; None when it is a link or not a directory."""
    locks = work_dir.parent / LOCKS
    locks.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(locks)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return None
    if hasattr(os, "getuid") and info.st_uid == os.getuid() and info.st_mode & 0o077:
        os.chmod(locks, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    return locks


def hold(work_dir: Path) -> int | None:
    """Take the run directory's lock for the sandbox's lifetime: an open descriptor on
    ``<root>/.locks/<name>.lock``, flocked on POSIX, holding the owner record. The record
    is written to a private temporary name and then renamed into place, so the lock is
    never seen empty (review-H667b nit 7) and a link planted at its name is replaced,
    never written through. None when it cannot be made (logged: then only age and the
    live list protect the directory)."""
    lock = _lock_path(work_dir)
    staged = None
    try:
        locks = _locks_dir(work_dir)
        if locks is None:
            raise OSError(0, "the locks directory is a link or not a directory")
        staged = locks / f".{work_dir.name}.{secrets.token_hex(4)}.tmp"
        fd = os.open(staged, os.O_RDWR | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        logger.warning("sandbox run directory %s has no lock (%s): only its age protects it "
                       "from another process's prune", work_dir.name, exc.strerror or exc)
        return None
    flocked = False
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            flocked = True
        except OSError as exc:
            logger.warning("sandbox run directory %s: flock unavailable (%s); its owner "
                           "record still protects it on this host", work_dir.name,
                           exc.strerror or exc)
    def abandon() -> None:
        with contextlib.suppress(OSError):
            if fd >= 0:
                os.close(fd)
        with contextlib.suppress(OSError):
            staged.unlink()

    try:
        os.write(fd, _record(flocked))
        if _WINDOWS:                    # an open file cannot be renamed there
            os.close(fd)
            fd = -1
        os.replace(staged, lock)
        if fd < 0:
            fd = os.open(lock, os.O_RDWR)
    except OSError as exc:
        logger.warning("sandbox run directory %s has no lock (%s): only its age protects it "
                       "from another process's prune", work_dir.name, exc.strerror or exc)
        abandon()
        return None
    except BaseException:               # an interrupt: no descriptor or staged file left behind
        abandon()
        raise
    return fd


def release(fd: int | None, work_dir: Path) -> None:
    """A sandbox that is gone drops its lock: the descriptor, then the lock file (an
    open file cannot be removed on Windows: review-H667b M1)."""
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.close(fd)
    with contextlib.suppress(OSError):
        _lock_path(work_dir).unlink()


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


_KERNEL32 = None


def _kernel32():  # pragma: no cover - Windows
    """kernel32 with the argument and return types of the calls made here declared, so
    a HANDLE is never truncated to a C int (review-H667c nit 6). Built once."""
    global _KERNEL32
    if _KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        dll.OpenProcess.restype = wintypes.HANDLE
        dll.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        dll.GetExitCodeProcess.restype = wintypes.BOOL
        filetime = ctypes.POINTER(ctypes.c_ulonglong)
        dll.GetProcessTimes.argtypes = [wintypes.HANDLE, filetime, filetime, filetime, filetime]
        dll.GetProcessTimes.restype = wintypes.BOOL
        dll.CloseHandle.argtypes = [wintypes.HANDLE]
        dll.CloseHandle.restype = wintypes.BOOL
        _KERNEL32 = dll
    return _KERNEL32


def _last_error() -> int:  # pragma: no cover - Windows
    import ctypes

    return ctypes.get_last_error()


def _windows_process(pid: int) -> tuple[bool, str] | None:
    """``(alive, creation time)`` from the process table, or None for no such process.
    Access denied (another user's process) reads as alive."""
    import ctypes

    kernel = _kernel32()
    handle = kernel.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None if _last_error() == 87 else (True, "")  # ERROR_INVALID_PARAMETER
    try:
        code = ctypes.c_ulong()
        alive = not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        created, exited, kernel_time, user_time = (ctypes.c_ulonglong() for _ in range(4))
        ok = kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel_time), ctypes.byref(user_time))
        return alive, (str(created.value) if ok else "")
    finally:
        kernel.CloseHandle(handle)


def _pid_alive(pid: int, start: str = "") -> bool:
    """Whether *pid* is a live process, and the same one as at *start* when given."""
    if _WINDOWS:
        process = _windows_process(pid)
        if process is None or not process[0]:
            return False
        return not (start and process[1] and process[1] != start)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    now = _start_token(pid)
    return not (start and now and now != start)


def _held(lock: Path, *, foreign_expired: bool = False) -> bool:
    """Whether a live sandbox holds this lock. Unknown reads as held; another host's
    record is held until *foreign_expired*."""
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
        probed = False
        if _fcntl is not None:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                probed = True
            except BlockingIOError:
                return True                   # busy: its writer holds it
            except OSError:
                probed = False                # a filesystem that refuses flock: read the record
        try:
            record = _parse(os.read(fd, 512).decode("utf-8", "replace"))
        except OSError:
            return True
        if not record["host"]:
            return False
        boot, rec_boot = _boot_id(), record.get("boot", "")
        same_host = record["host"] == socket.gethostname()
        if boot and rec_boot:
            this_kernel = rec_boot == boot
            rebooted = same_host and not this_kernel
        else:
            this_kernel, rebooted = same_host, False
        flocked = record.get("flock")
        if probed and ((this_kernel and flocked == "1") or rebooted
                       or (same_host and flocked is None)):
            # Its writer's flock is gone, or its writer's kernel is (a reboot), or it is a
            # record from before the flag, whose writer always took the flock.
            return False
        if not this_kernel and not same_host:
            return not foreign_expired        # another host's: nothing here can tell
        if flocked == "1":
            return not foreign_expired        # its writer held a flock this probe could not test
        ns, mine = record.get("ns", ""), _pid_ns()
        if ns and mine and ns != mine:
            return not foreign_expired        # another pid namespace: its pid means nothing here
        pid = record["pid"]
        if not (pid.isascii() and pid.isdigit()) or int(pid) >= _PID_LIMIT:
            return not foreign_expired        # a record no hold wrote: unknown, aged out
        return _pid_alive(int(pid), record.get("start", ""))
    finally:
        os.close(fd)                          # closing drops the probe's own lock


def _held_safely(lock: Path, **kwargs) -> bool:
    """``_held``, where anything unexpected reads as held and is logged: one odd lock
    never stops the whole sweep (review-H667c nit 4)."""
    try:
        return _held(lock, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sandbox lock %s could not be judged (%s); kept", lock.name,
                       exc.__class__.__name__)
        return True


def _root_problem(root: Path) -> str | None:
    """Why the managed root must not be swept, or None."""
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return f"unreadable ({exc.strerror or exc.__class__.__name__})"
    reparse = getattr(info, "st_file_attributes", 0) & 0x400      # a Windows reparse point
    if stat.S_ISLNK(info.st_mode) or (
            reparse and getattr(info, "st_reparse_tag", 0xA0000003) in _LINK_REPARSE_TAGS):
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
    now = time.time() if now is None else now
    hours = max(MIN_AGE_HOURS, float(max_age_hours))
    cutoff = now - hours * 3600
    foreign_cutoff = now - FOREIGN_FACTOR * hours * 3600
    keep = set()
    for path in live:
        with contextlib.suppress(OSError, RuntimeError):
            keep.add(Path(path).resolve())
    for entry in entries:
        try:
            if (not entry.name.startswith(PREFIX) or entry.is_symlink() or not entry.is_dir()
                    or entry.resolve() in keep or (newest := _newest(entry)) >= cutoff
                    or _held_safely(_lock_path(entry), foreign_expired=newest < foreign_cutoff)):
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
    _drop_orphan_locks(root, foreign_cutoff)
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


def _drop_orphan_locks(root: Path, foreign_cutoff: float) -> None:
    """A lock whose run directory is gone, and that nobody holds, is removed; another
    host's once the lock itself is older than *foreign_cutoff*."""
    locks = root / LOCKS
    with contextlib.suppress(OSError):
        if locks.is_symlink() or not locks.is_dir():
            return
        stale_staged = time.time() - 3600
        for lock in locks.iterdir():
            if lock.name.startswith("." + PREFIX) and lock.name.endswith(".tmp"):
                # a record staged by a hold that never finished (review-H667c nit 3)
                with contextlib.suppress(OSError):
                    if _date(lock.lstat()) < stale_staged:
                        lock.unlink()
                continue
            name = lock.name.removesuffix(".lock")
            if not name.startswith(PREFIX) or (root / name).exists():
                continue
            with contextlib.suppress(OSError):
                if not _held_safely(lock, foreign_expired=_date(lock.lstat()) < foreign_cutoff):
                    lock.unlink()


def max_age_hours(get_value: Getter | None = None) -> float:
    """The owner's age limit, 72 hours when unset or not a positive number."""
    try:
        hours = float(_getter(get_value)(*AGE_SETTING, DEFAULT_MAX_AGE_HOURS))
    except Exception:  # noqa: BLE001
        return float(DEFAULT_MAX_AGE_HOURS)
    return hours if 0 < hours < float("inf") else float(DEFAULT_MAX_AGE_HOURS)
