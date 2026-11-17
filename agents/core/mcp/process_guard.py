"""process_guard.py — stdio MCP children that cannot outlive the hub or each other (H556).

Three pieces, POSIX only (each is a no-op elsewhere):

* **Own process group.** Every stdio server starts in a new session
  (``start_new_session=True``), so a launcher such as ``npx`` or ``uvx`` and the server it
  starts share one group, and :func:`terminate_group` stops the whole group: SIGTERM, a
  grace period for the leader *and* every member, then SIGKILL to whatever is left (a
  member that ignores SIGTERM is killed even after its launcher exited). Terminating only
  the launcher used to leave the real server running, reparented to init.
* **Orphan reaper.** Each spawn is recorded in ``<data>/mcp_children.json`` with the
  hub's pid and the leader's kernel start time (``/proc/<pid>/stat`` field 22); the record
  is removed only once the group is empty. :func:`reap_orphans` runs when the manager
  starts and stops a recorded group whose hub is gone. A group is signalled only when it
  is provably still ours (:func:`_group_is_ours`): the leader is alive with the recorded
  start time, or the leader is gone and members of that group remain (Linux does not hand
  out a pid while it still names a process group). A recycled pid is never touched.
  Every read-modify-write of the registry holds an ``flock`` on ``mcp_children.lock``.
* **Discovery lock.** :func:`discovery_lock` holds an advisory ``flock`` on
  ``<data>/mcp_discovery.lock`` while one process connects its saved servers, so two
  processes sharing a data directory do not spawn the same servers at once. Waiting is
  bounded; on timeout the connect goes ahead and says so.

What this does not do: a resident per-child watchdog that kills the group the moment the
hub dies (Hermes's supervisor). Here the group is stopped at the hub's next start.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import signal
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.mcp.process")

POSIX = os.name == "posix"
LINUX_PROC = Path("/proc/self/stat").exists()
REGISTRY_NAME = "mcp_children.json"
REGISTRY_LOCK_NAME = "mcp_children.lock"
LOCK_NAME = "mcp_discovery.lock"
#: Seconds a stopped group gets between SIGTERM and SIGKILL.
GRACE_SECONDS = 5.0
#: Seconds :func:`discovery_lock` waits for another process before connecting anyway.
LOCK_WAIT_SECONDS = 30.0
MAX_RECORDS = 512


def spawn_kwargs() -> dict[str, Any]:
    """Extra ``create_subprocess_exec`` arguments for a stdio server."""
    return {"start_new_session": True} if POSIX else {}


def _registry_path(root: Path | None = None) -> Path:
    if root is not None:
        return root / REGISTRY_NAME
    from agents.core.paths import data_path

    return data_path(REGISTRY_NAME)


def _stat_fields(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace")
    except (OSError, ValueError):
        return None
    # The command name (field 2) may hold spaces and parentheses: split after the last ')'.
    return raw[raw.rfind(")") + 2:].split()


def _start_time(pid: int) -> int | None:
    """The kernel start time of *pid* in clock ticks (Linux), or None."""
    fields = _stat_fields(pid)
    try:
        return int(fields[19]) if fields else None
    except (IndexError, ValueError):
        return None


def _alive(pid: int) -> bool:
    """A live (not zombie) process."""
    fields = _stat_fields(pid) if LINUX_PROC else None
    if fields:
        return fields[0] != "Z"
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return not LINUX_PROC


def group_members(pgid: int) -> list[int]:
    """Live processes whose process group is *pgid* (Linux ``/proc``; [] elsewhere)."""
    if not LINUX_PROC:
        return []
    members = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        fields = _stat_fields(int(entry))
        try:
            if fields and fields[0] != "Z" and int(fields[2]) == int(pgid):
                members.append(int(entry))
        except (IndexError, ValueError):
            continue
    return members


def _valid_pid(pid: object) -> bool:
    return (isinstance(pid, int) and not isinstance(pid, bool) and pid > 1
            and pid != os.getpid() and pid != os.getpgrp())


def _group_is_ours(pgid: int, start: int | None) -> bool:
    """May group *pgid* be signalled as the one spawned with leader start time *start*?

    Yes when the leader is alive with exactly that start time, or when no process holds
    the pid any more and the group still has members: a pid is not reused while it still
    names a process group, so those members are the ones we started. No when another
    process now holds the pid (a recycled pid), or when the group is empty."""
    if not _valid_pid(pgid):
        return False
    if _alive(pgid):
        return start is not None and _start_time(pgid) == start
    return bool(group_members(pgid))


def _signal_group(pid: int, sig: int) -> bool:
    try:
        os.killpg(int(pid), sig)
        return True
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        return False


@contextlib.contextmanager
def _registry_lock(root: Path | None = None):
    """An exclusive ``flock`` over the registry's read-modify-write (bounded wait)."""
    try:
        import fcntl
    except ImportError:          # pragma: no cover - not POSIX
        yield
        return
    path = _registry_path(root).with_name(REGISTRY_LOCK_NAME)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("MCP child registry is locked") from None
                time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def _load(path: Path) -> dict[str, dict]:
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read(1 << 20))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _store(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def record(pid: int, server: str, *, root: Path | None = None) -> int | None:
    """Note a spawned group leader; returns its kernel start time (best effort: a failure
    here never stops a spawn)."""
    if not POSIX:
        return None
    start = _start_time(pid)
    try:
        path = _registry_path(root)
        with _registry_lock(root):
            rows = _load(path)
            rows[str(int(pid))] = {"server": str(server)[:200], "hub_pid": os.getpid(),
                                   "start": start, "at": time.time()}
            if len(rows) > MAX_RECORDS:
                for key in sorted(rows, key=lambda k: rows[k].get("at") or 0)[:len(rows) - MAX_RECORDS]:
                    rows.pop(key, None)
            _store(path, rows)
    except Exception:
        logger.debug("MCP child %s not recorded", server, exc_info=True)
    return start


def forget(pid: int, *, root: Path | None = None) -> None:
    if not POSIX:
        return
    try:
        path = _registry_path(root)
        with _registry_lock(root):
            rows = _load(path)
            if rows.pop(str(int(pid)), None) is not None:
                _store(path, rows)
    except Exception:
        logger.debug("MCP child %s record not removed", pid, exc_info=True)


async def _wait_group_empty(pgid: int, until: float) -> bool:
    while time.monotonic() < until:
        if not group_members(pgid):
            return True
        await asyncio.sleep(0.05)
    return not group_members(pgid)


async def terminate_group(proc: Any, *, grace: float = GRACE_SECONDS,
                          root: Path | None = None) -> None:
    """Stop *proc* and every process in its group: SIGTERM, *grace* seconds for the leader
    and every member, then SIGKILL to the group while it still has members.

    The group is signalled only while it is provably ours (:func:`_group_is_ours`). Its
    registry record is removed only once the group is empty, so a member that survived
    is still stopped by the reaper at the next start."""
    pid = getattr(proc, "pid", None)
    grouped = POSIX and isinstance(pid, int) and pid > 0 and getattr(proc, "_mcp_group", False)
    start = getattr(proc, "_mcp_start", None)

    def live() -> bool:
        return getattr(proc, "returncode", None) is None

    if grouped and start is None and live():
        start = _start_time(pid)
    if live() and not (grouped and _group_is_ours(pid, start)
                       and _signal_group(pid, signal.SIGTERM)):
        with contextlib.suppress(ProcessLookupError, AttributeError):
            proc.terminate()
    until = time.monotonic() + grace
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=grace)
    if not grouped:
        if live():
            with contextlib.suppress(ProcessLookupError, AttributeError):
                proc.kill()
            with contextlib.suppress(TimeoutError, ProcessLookupError, AttributeError):
                await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    empty = not LINUX_PROC or await _wait_group_empty(pid, until)
    if not empty or live():
        if _group_is_ours(pid, start):
            _signal_group(pid, signal.SIGKILL)
        elif live():
            with contextlib.suppress(ProcessLookupError, AttributeError):
                proc.kill()
        with contextlib.suppress(TimeoutError, ProcessLookupError, AttributeError):
            await asyncio.wait_for(proc.wait(), timeout=grace)
        empty = not LINUX_PROC or await _wait_group_empty(pid, time.monotonic() + grace)
    if empty:
        forget(pid, root=root)
    else:
        logger.warning("MCP server group %d still has members; left for the orphan reaper", pid)


def _valid_row(key: str, row: dict) -> tuple[int, int | None, int] | None:
    """``(pid, start, hub_pid)`` from a registry row, or None when any field is off."""
    try:
        pid = int(key)
    except ValueError:
        return None
    start, hub = row.get("start"), row.get("hub_pid")
    if not _valid_pid(pid) or str(pid) != key:
        return None
    if start is not None and (not isinstance(start, int) or isinstance(start, bool) or start < 0):
        return None
    if not isinstance(hub, int) or isinstance(hub, bool) or hub <= 1:
        return None
    return pid, start, hub


def reap_orphans(*, root: Path | None = None) -> list[int]:
    """Stop recorded groups whose hub is gone and that are provably still ours
    (:func:`_group_is_ours`). Returns the group ids signalled."""
    if not POSIX:
        return []
    path = _registry_path(root)
    try:
        with _registry_lock(root):
            rows = _load(path)
            stopped: list[int] = []
            keep: dict[str, dict] = {}
            me = os.getpid()
            for key, row in rows.items():
                parsed = _valid_row(key, row)
                if parsed is None:
                    continue             # malformed: dropped, never signalled
                pid, start, hub = parsed
                if hub == me or _alive(hub):
                    keep[key] = row      # a live hub (this one, or another sharing the data dir)
                    continue
                if not _group_is_ours(pid, start):
                    continue             # gone, or the pid now names some other process
                if _signal_group(pid, signal.SIGTERM):
                    stopped.append(pid)
                    logger.warning("MCP: stopped an orphaned server group %d (%s) left by a "
                                   "previous run", pid, str(row.get("server"))[:60])
            if stopped:
                deadline = time.monotonic() + GRACE_SECONDS
                while time.monotonic() < deadline and any(
                        _alive(p) or group_members(p) for p in stopped):
                    time.sleep(0.1)
                for pid in stopped:
                    if group_members(pid) or _alive(pid):
                        start = rows[str(pid)].get("start")
                        if _group_is_ours(pid, start):
                            _signal_group(pid, signal.SIGKILL)
            _store(path, keep)
    except OSError:
        logger.debug("MCP child registry not swept", exc_info=True)
        return []
    return stopped


@contextlib.asynccontextmanager
async def discovery_lock(*, root: Path | None = None, wait: float = LOCK_WAIT_SECONDS):
    """Hold the cross-process discovery lock while connecting; yields True when held."""
    try:
        import fcntl
    except ImportError:          # pragma: no cover - not POSIX
        yield False
        return
    if root is not None:
        path = root / LOCK_NAME
    else:
        from agents.core.paths import data_path

        path = data_path(LOCK_NAME)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        logger.debug("MCP discovery lock unavailable", exc_info=True)
        yield False
        return
    held = False
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    logger.warning("MCP discovery lock still held by another process after %.0fs; "
                                   "connecting anyway", wait)
                    break
                await asyncio.sleep(0.2)
            except OSError:
                break
        yield held
    finally:
        if held:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
