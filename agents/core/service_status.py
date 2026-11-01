"""H019 — is this hub running under a service manager, and since when.

The service block of ``GET /status`` and ``nerva status`` (Hermes ``hermes status`` →
"Gateway Service"): which service manager runs this hub, the unit it runs as, whether
the unit Nerva ships is installed on this host and active, and the hub's pid and uptime.

- **manager** — :func:`host_identity.identity`'s supervisor (``systemd``, ``launchd``,
  ``s6``), or ``nssm`` on Windows when the installer's marker is set
  (``NERVA_SERVICE_WRAPPER=nssm``, ``deploy/windows/install-service.ps1``; serve.py's
  self-restart reads the same marker); ``none`` when nothing says a manager runs it;
  ``unknown`` when the detector failed. ``confirmed`` is the detector's strong signal
  (``NOTIFY_SOCKET``, the journal on this stderr, the ``S6_*`` variables, a launchd job,
  the NSSM marker).
- **unit** — what this hub runs as when a manager runs it (systemd: the ``.service`` this
  process's cgroup sits in; launchd: the job label), else the unit Nerva ships for this
  platform (``jarvis-hub.service`` from ``deploy/systemd``, the ``JarvisHub`` Windows
  service); ``None`` when no name can be read.
- **installed / active / managing** — that unit is present on this host, is active, and
  runs this hub process. A hub a confirmed manager runs is all three. Otherwise the
  shipped unit is looked for (systemd's unit directories when systemd is the init, the
  Windows service registry) and, when it is installed, its state is asked once
  (``systemctl is-active`` / ``sc query``, read-only, bounded by ``QUERY_TIMEOUT_S``).
- **state** — one of :data:`STATES`: ``managed``, ``unconfirmed`` (a weak signal names a
  manager), ``installed_not_managing``, ``installed_stopped`` (Hermes keeps these two
  apart: they need different fixes), ``not_installed``, ``unsupported`` (no unit is
  shipped for this platform or systemd is not the init), ``unknown``.

Every value is from a closed vocabulary, a bounded name, a boolean, an integer or
``None``. ``None`` is "could not tell" and renders unknown; it is never read as no or
ok. The manager half is cached for ``PROBE_TTL_S``; pid and uptime are read on each
call. Nothing here starts, stops or changes a unit, and nothing raises.
"""
from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess  # nosec B404 - fixed argv (a resolved systemctl/sc and a constant unit), read-only
import sys
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from . import host_identity

logger = logging.getLogger("jarvis.service_status")

#: The unit ``deploy/systemd/jarvis-hub.service`` installs.
SYSTEMD_UNIT = "jarvis-hub.service"
#: ``deploy/windows/install-service.ps1``'s default ``-ServiceName``.
WINDOWS_SERVICE = "JarvisHub"
#: Set by the NSSM installer; serve.py's ``SERVICE_WRAPPER_ENV``.
SERVICE_WRAPPER_ENV = "NERVA_SERVICE_WRAPPER"
#: sd_booted(3): systemd is the init when this directory exists.
SD_BOOTED = "/run/systemd/system"
SYSTEM_UNIT_DIRS = ("/etc/systemd/system", "/run/systemd/system", "/usr/local/lib/systemd/system",
                    "/usr/lib/systemd/system", "/lib/systemd/system")
USER_UNIT_DIRS = ("~/.config/systemd/user", "/etc/systemd/user", "/usr/lib/systemd/user")
PROC_CGROUP = "/proc/self/cgroup"
WINDOWS_SERVICES_KEY = "SYSTEM\\CurrentControlSet\\Services"

MANAGERS = ("systemd", "launchd", "s6", "nssm", "none", "unknown")
STATES = ("managed", "unconfirmed", "installed_not_managing", "installed_stopped", "not_installed",
          "unsupported", "unknown")
PROBE_TTL_S = 30.0
QUERY_TIMEOUT_S = 2.0
MAX_QUERY_OUTPUT = 4096

_UNIT_NAME = re.compile(r"[A-Za-z0-9:_.@\-]{1,92}\.service")
_LAUNCHD_LABEL = re.compile(r"[A-Za-z0-9._\-]{1,128}")
#: ``systemctl is-active``'s words: running or on its way up / on its way down or not running.
_SYSTEMD_ACTIVE = {"active": True, "reloading": True, "refreshing": True, "activating": True,
                   "inactive": False, "failed": False, "deactivating": False}
#: ``sc query``'s STATE codes: 4 RUNNING, 2 START_PENDING, 5-7 continue/pause pending, paused
#: (the process runs); 1 STOPPED, 3 STOP_PENDING.
_SC_STATES = {1: False, 2: True, 3: False, 4: True, 5: True, 6: True, 7: True}
_SC_STATE_LINE = re.compile(r"^\s*STATE\s*:\s*(\d+)\b", re.MULTILINE)


# ── the parts ────────────────────────────────────────────────────────────────


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(8192)


def _present(stat: Callable[[str], Any], path: str) -> bool | None:
    """True when *path* exists, False when it does not, None when it could not be read."""
    try:
        stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError):
        return None
    return True


def _run(argv: list[str]) -> str | None:
    """*argv*'s stdout, or None when it could not run or did not finish in time."""
    try:
        done = subprocess.run(  # nosec B603 - argv is a resolved binary, a fixed verb and a constant unit
            argv, capture_output=True, text=True, timeout=QUERY_TIMEOUT_S, check=False,
            stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return (done.stdout or "")[:MAX_QUERY_OUTPUT]


def _windows_service_present(name: str) -> bool | None:
    """Whether the Windows service *name* is registered (its Services key exists)."""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{WINDOWS_SERVICES_KEY}\\{name}"):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return None


def cgroup_unit(text: str) -> str | None:
    """The ``.service`` this process sits in, from ``/proc/self/cgroup`` text: the leaf of
    the unified (``0::``) or the ``name=systemd`` hierarchy. A scope (a terminal's
    session) or a name outside systemd's characters is None."""
    for line in (text or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if (hierarchy == "0" and controllers == "") or controllers == "name=systemd":
            leaf = path.strip().rstrip("/").rsplit("/", 1)[-1]
            return leaf if _UNIT_NAME.fullmatch(leaf) else None
    return None


def systemd_state(output: str | None) -> bool | None:
    """``systemctl is-active``'s answer as active (True), not (False) or unknown (None)."""
    word = (output or "").strip().split("\n", 1)[0].strip()
    return _SYSTEMD_ACTIVE.get(word)


def windows_state(output: str | None) -> bool | None:
    """``sc query``'s STATE as running (True), stopped (False) or unknown (None)."""
    match = _SC_STATE_LINE.search(output or "")
    return _SC_STATES.get(int(match.group(1))) if match else None


def _own_unit(manager: str, env: Mapping[str, str], read_text: Callable[[str], str]) -> str | None:
    if manager == "systemd":
        try:
            return cgroup_unit(read_text(PROC_CGROUP))
        except (OSError, UnicodeError, ValueError):
            return None
    if manager == "launchd":
        label = (env.get("XPC_SERVICE_NAME") or "").strip()
        return label if _LAUNCHD_LABEL.fullmatch(label) else None
    return None


def _manager(ident: Any, env: Mapping[str, str], platform: str) -> tuple[str, bool]:
    if platform == "win32" and (env.get(SERVICE_WRAPPER_ENV) or "").strip().lower() == "nssm":
        return "nssm", True
    if not getattr(ident, "detected", False):
        return "unknown", False
    supervisor = getattr(ident, "supervisor", "none")
    if supervisor not in MANAGERS:
        return "unknown", False
    return supervisor, bool(getattr(ident, "supervisor_confirmed", False))


def shipped_unit(*, platform: str = sys.platform, stat: Callable[[str], Any] = os.stat,
                 which: Callable[[str], str | None] = shutil.which,
                 run: Callable[[list[str]], str | None] = _run,
                 registry: Callable[[str], bool | None] = _windows_service_present,
                 expanduser: Callable[[str], str] = os.path.expanduser) -> dict:
    """The unit Nerva ships for this platform, on this host: ``applicable`` (a unit is
    shipped and its manager is here), ``unit``, ``installed`` and ``active`` (tri-state).
    ``nerva status`` also reads it on the box when no hub answers."""
    if platform.startswith("linux"):
        booted = _present(stat, SD_BOOTED)
        if booted is False:
            return {"applicable": False, "unit": SYSTEMD_UNIT, "installed": None, "active": None}
        if booted is None:
            return {"applicable": True, "unit": SYSTEMD_UNIT, "installed": None, "active": None}
        scope, unreadable = None, False
        for name, dirs in (("system", SYSTEM_UNIT_DIRS), ("user", USER_UNIT_DIRS)):
            for folder in dirs:
                found = _present(stat, os.path.join(expanduser(folder), SYSTEMD_UNIT))
                if found:
                    scope = name
                    break
                unreadable = unreadable or found is None
            if scope:
                break
        if scope is None:
            return {"applicable": True, "unit": SYSTEMD_UNIT, "installed": None if unreadable else False,
                    "active": None if unreadable else False}
        binary = which("systemctl")
        argv = [binary, *(["--user"] if scope == "user" else []), "is-active", SYSTEMD_UNIT] if binary else None
        return {"applicable": True, "unit": SYSTEMD_UNIT, "installed": True,
                "active": systemd_state(run(argv)) if argv else None}
    if platform == "win32":
        installed = registry(WINDOWS_SERVICE)
        active: bool | None = False if installed is False else None
        if installed:
            binary = which("sc.exe") or which("sc")
            active = windows_state(run([binary, "query", WINDOWS_SERVICE])) if binary else None
        return {"applicable": True, "unit": WINDOWS_SERVICE, "installed": installed, "active": active}
    # macOS (launchd) and the rest: Nerva ships no unit there, so there is nothing to look for.
    return {"applicable": False, "unit": None, "installed": None, "active": None}


def _row(manager: str, confirmed: bool, unit: str | None, installed: bool | None,
         active: bool | None, managing: bool | None, state: str) -> dict:
    return {"manager": manager, "confirmed": confirmed, "unit": unit, "installed": installed,
            "active": active, "managing": managing, "state": state}


def probe(env: Mapping[str, str] | None = None, *, identity: Any = None, platform: str = sys.platform,
          read_text: Callable[[str], str] = _read_text, **unit_probes: Any) -> dict:
    """The manager half of the block (no pid or uptime); ``unit_probes`` go to
    :func:`shipped_unit` (``stat``, ``which``, ``run``, ``registry``, ``expanduser``)."""
    env = os.environ if env is None else env
    ident = host_identity.identity() if identity is None else identity
    manager, confirmed = _manager(ident, env, platform)
    if manager == "unknown":
        return _row("unknown", False, None, None, None, None, "unknown")
    if manager != "none":
        unit = _own_unit(manager, env, read_text)
        if confirmed:
            return _row(manager, True, unit, True, True, True, "managed")
        return _row(manager, False, unit, None, None, None, "unconfirmed")
    shipped = shipped_unit(platform=platform, **unit_probes)
    installed, active = shipped["installed"], shipped["active"]
    if not shipped["applicable"]:
        state = "unsupported"
    elif installed is None:
        state = "unknown"
    elif installed is False:
        state = "not_installed"
    elif active is False:
        state = "installed_stopped"
    else:
        state = "installed_not_managing"
    unit = shipped["unit"] if shipped["applicable"] else None
    return _row("none", False, unit, installed, active, False, state)


# ── the block ────────────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def reset_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def cached_probe(*, clock: Callable[[], float] = time.monotonic) -> dict:
    """:func:`probe`, at most once per ``PROBE_TTL_S`` (the HUD polls ``/status``)."""
    global _cache
    # One lock around the read and the probe: a burst of requests when the entry expires
    # asks the service manager once, and the rest read what it answered.
    with _cache_lock:
        now = clock()
        if _cache is not None and now - _cache[0] < PROBE_TTL_S:
            return dict(_cache[1])
        try:
            row = probe()
        except Exception as exc:  # a detector bug must never take /status down, nor read as "none"
            logger.warning("service status could not be read (%s)", type(exc).__name__)
            row = _row("unknown", False, None, None, None, None, "unknown")
        _cache = (now, row)
    return dict(row)


def snapshot(*, started_at: float | None, now: Callable[[], float] = time.time,
             pid: Callable[[], int] = os.getpid, rows: Callable[[], dict] = cached_probe) -> dict:
    """The whole block: :func:`cached_probe` plus this process's ``pid``, ``started_at``
    (ISO 8601, UTC) and ``uptime_s`` — None for a start time that is not a past instant."""
    block = rows()
    block["pid"] = pid()
    current = now()
    known = (isinstance(started_at, (int, float)) and not isinstance(started_at, bool)
             and math.isfinite(started_at) and 0 < started_at <= current)
    block["started_at"] = (datetime.fromtimestamp(started_at, UTC).isoformat(timespec="seconds")
                           .replace("+00:00", "Z")
                           if known else None)
    block["uptime_s"] = int(current - started_at) if known else None
    return block


__all__ = ["MANAGERS", "STATES", "SYSTEMD_UNIT", "WINDOWS_SERVICE", "cached_probe", "cgroup_unit",
           "probe", "reset_cache", "shipped_unit", "snapshot", "systemd_state", "windows_state"]
