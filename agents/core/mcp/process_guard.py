"""process_guard.py — stdio MCP children that cannot outlive the hub or each other (H556).

Three pieces, POSIX only (each is a no-op elsewhere):

* **Own process group.** Every stdio server starts in a new session
  (``start_new_session=True``), so a launcher such as ``npx`` or ``uvx`` and the server it
  starts share one group, and :func:`terminate_group` stops the whole group (SIGTERM,
  then SIGKILL after the grace period). Terminating only the launcher used to leave the
  real server running, reparented to init.
* **Orphan reaper.** Each spawn is recorded in ``<data>/mcp_children.json`` with the
  hub's pid and the child's kernel start time (``/proc/<pid>/stat`` field 22); a clean
  teardown removes the record. :func:`reap_orphans` runs when the manager starts: a
  recorded group whose hub is gone and whose leader is still the *same* process (pid and
  start time both match, so a recycled pid is never touched) is stopped. That is the
  failure the watchdog exists for: a hard kill or crash of the hub, then a restart that
  spawns a second copy of every server against the same upstream session.
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
import signal
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.mcp.process")

POSIX = os.name == "posix"
REGISTRY_NAME = "mcp_children.json"
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


def _start_time(pid: int) -> int | None:
    """The kernel start time of *pid* in clock ticks (Linux), or None."""
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace")
    except (OSError, ValueError):
        return None
    # The command name (field 2) may hold spaces and parentheses: split after the last ')'.
    fields = raw[raw.rfind(")") + 2:].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


def _load(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _store(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, sort_keys=True)
    os.replace(tmp, path)


def record(pid: int, server: str, *, root: Path | None = None) -> None:
    """Note a spawned group leader (best effort: a failure here never stops a spawn)."""
    if not POSIX:
        return
    try:
        path = _registry_path(root)
        rows = _load(path)
        rows[str(int(pid))] = {"server": str(server)[:200], "hub_pid": os.getpid(),
                               "start": _start_time(pid), "at": time.time()}
        if len(rows) > MAX_RECORDS:
            for key in sorted(rows, key=lambda k: rows[k].get("at") or 0)[:len(rows) - MAX_RECORDS]:
                rows.pop(key, None)
        _store(path, rows)
    except Exception:
        logger.debug("MCP child %s not recorded", server, exc_info=True)


def forget(pid: int, *, root: Path | None = None) -> None:
    if not POSIX:
        return
    try:
        path = _registry_path(root)
        rows = _load(path)
        if rows.pop(str(int(pid)), None) is not None:
            _store(path, rows)
    except Exception:
        logger.debug("MCP child %s record not removed", pid, exc_info=True)


def _signal_group(pid: int, sig: int) -> bool:
    try:
        os.killpg(int(pid), sig)
        return True
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        return False


async def terminate_group(proc: Any, *, grace: float = GRACE_SECONDS) -> None:
    """Stop *proc* and every process in its group: SIGTERM, then SIGKILL after *grace*.

    The group is signalled only while its leader has not been reaped (``returncode`` is
    None): until then the leader's pid cannot be reused, so the group id cannot name
    anybody else's processes. A leader that already exited is only waited for."""
    pid = getattr(proc, "pid", None)
    grouped = POSIX and isinstance(pid, int) and pid > 0 and getattr(proc, "_mcp_group", False)

    def live() -> bool:
        return getattr(proc, "returncode", None) is None

    if live() and not (grouped and _signal_group(pid, signal.SIGTERM)):
        with contextlib.suppress(ProcessLookupError, AttributeError):
            proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        if not (grouped and live() and _signal_group(pid, signal.SIGKILL)):
            with contextlib.suppress(ProcessLookupError, AttributeError):
                proc.kill()
        with contextlib.suppress(TimeoutError, ProcessLookupError, AttributeError):
            await asyncio.wait_for(proc.wait(), timeout=grace)
    if grouped:
        forget(pid)


def reap_orphans(*, root: Path | None = None) -> list[int]:
    """Stop recorded groups whose hub is gone and whose leader is still the recorded
    process (same pid AND same kernel start time). Returns the pids stopped."""
    if not POSIX:
        return []
    path = _registry_path(root)
    rows = _load(path)
    if not rows:
        return []
    stopped: list[int] = []
    keep: dict[str, dict] = {}
    me = os.getpid()
    for key, row in rows.items():
        try:
            pid = int(key)
        except ValueError:
            continue
        hub = row.get("hub_pid")
        if hub == me or (isinstance(hub, int) and _alive(hub)):
            keep[key] = row      # a live hub (this one, or another sharing the data dir)
            continue
        recorded = row.get("start")
        if recorded is None or not _alive(pid) or _start_time(pid) != recorded:
            continue             # gone, or the pid now names some other process
        if _signal_group(pid, signal.SIGTERM):
            stopped.append(pid)
            logger.warning("MCP: stopped an orphaned server group %d (%s) left by a previous run",
                           pid, str(row.get("server"))[:60])
    if stopped:
        deadline = time.monotonic() + GRACE_SECONDS
        while time.monotonic() < deadline and any(_alive(p) for p in stopped):
            time.sleep(0.1)
        for pid in stopped:
            _signal_group(pid, signal.SIGKILL)
    try:
        _store(path, keep)
    except OSError:
        logger.debug("MCP child registry not rewritten", exc_info=True)
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
