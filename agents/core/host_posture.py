"""H501 — warn about a dangerous host posture before it becomes an incident.

The bind guard (``boot_guards.assert_safe_bind``) already *refuses* an unauthenticated
network bind. This module adds Hermes' host half: three cheap, read-only checks that
never block and never change anything, logged once when the hub starts and reported by
``nerva doctor`` (``scripts/doctor.py``) and ``GET /api/security/posture``:

- **root** — the hub runs as root (or elevated on Windows), on any host: one prompt
  injection would then be a whole-host compromise.
- **sshd_passwords** — ``sshd`` accepts passwords: ``/etc/ssh/sshd_config`` read with
  sshd's own rules — its ``Include`` files read in place, in lexical order; the first
  value of a keyword wins; a ``Match`` block overrides only the connections it matches
  (and lasts to the end of its file); an absent ``PasswordAuthentication`` means the
  sshd default, ``yes``.
- **container_storage** — the hub runs in a container (``/.dockerenv``,
  ``/run/.containerenv``, or a container cgroup of PID 1) while its data root is not on
  a volume or bind mount (``/proc/self/mountinfo``), so memory, the vault and keys go
  with the container.

Every check answers ``ok``, ``warn`` or ``unknown`` (it could not tell — never a false
green), with a reason, what it saw, and the fix. Stdlib only, so the doctor can use it on
a broken install; every OS path is a parameter, for tests.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shlex
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.host_posture")

OK, WARN, UNKNOWN = "ok", "warn", "unknown"
SSHD_CONFIG = "/etc/ssh/sshd_config"
SSHD_DIR = "/etc/ssh"
MOUNTINFO = "/proc/self/mountinfo"
PID1_CGROUP = "/proc/1/cgroup"
CONTAINER_FILES = ("/.dockerenv", "/run/.containerenv")
CONTAINER_CGROUP_MARKERS = ("docker", "kubepods", "containerd", "libpod", "lxc")
EPHEMERAL_FS = frozenset({"tmpfs", "ramfs"})
MAX_INCLUDE_DEPTH = 16          # sshd's own limit
MAX_CONFIG_BYTES = 256 * 1024

FIX = {
    "root": "run the hub as an unprivileged user (deploy/systemd/jarvis-hub.service uses User=jarvis; "
            "in a container, add a USER or run with --user)",
    "sshd_passwords": "set 'PasswordAuthentication no' where sshd reads it first (a file in "
                      "/etc/ssh/sshd_config.d/ when the main file Includes it at the top), use keys, "
                      "and reload sshd",
    "container_storage": "mount a volume or a bind mount at the data root (JARVIS_HOME), e.g. "
                         "-v nerva-data:/data -e JARVIS_HOME=/data",
}


def _finding(check: str, status: str, reason: str, detail: str = "") -> dict:
    row = {"check": check, "status": status, "reason": reason, "detail": detail}
    if status == WARN:
        row["fix"] = FIX[check]
    return row


# ── root ─────────────────────────────────────────────────────────────────────


def check_root(*, platform: str | None = None, geteuid: Callable[[], int] | None = None,
               is_admin: Callable[[], Any] | None = None) -> dict:
    """Is this process root (POSIX euid 0) or elevated (Windows)?"""
    plat = platform or sys.platform
    try:
        if plat.startswith("win"):
            if is_admin is None:
                import ctypes

                is_admin = ctypes.windll.shell32.IsUserAnAdmin  # type: ignore[attr-defined]
            elevated = bool(is_admin())
            label = "elevated (administrator)"
        else:
            geteuid = geteuid or getattr(os, "geteuid", None)
            if geteuid is None:
                return _finding("root", UNKNOWN, "no_euid")
            euid = geteuid()
            elevated = euid == 0
            label = f"euid {euid}"
    except Exception as exc:
        return _finding("root", UNKNOWN, "unreadable", type(exc).__name__)
    if elevated:
        return _finding("root", WARN, "running_as_root", label)
    return _finding("root", OK, "unprivileged", label)


# ── sshd ─────────────────────────────────────────────────────────────────────


def _read_config(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(MAX_CONFIG_BYTES).splitlines()


_KEYWORD = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*=?\s*(.*)$")


def _split(line: str) -> tuple[str, list[str]] | None:
    """``Keyword value``, ``Keyword=value`` or ``Keyword = value``; None for a blank or comment."""
    m = _KEYWORD.match(line.strip())             # a blank or a comment has no keyword
    if m is None:
        return None
    try:
        values = shlex.split(m.group(2), comments=True)
    except ValueError:
        values = m.group(2).split()
    return m.group(1).lower(), values


class _SshdScan:
    def __init__(self, base: str, glob_fn: Callable[[str], list[str]], read: Callable[[str], list[str]]):
        self.base = base
        self.glob = glob_fn
        self.read = read
        self.global_value: tuple[str, str] | None = None     # (value, where)
        self.match_yes: str | None = None                     # where a Match block turns it on
        self.errors: list[str] = []

    def scan(self, path: str, depth: int = 0, in_match: bool = False) -> None:
        if depth > MAX_INCLUDE_DEPTH:
            self.errors.append(f"{path}: Include nested too deep")
            return
        try:
            lines = self.read(path)
        except FileNotFoundError:
            if depth == 0:
                raise
            return                                              # a glob hit that vanished
        except OSError as exc:
            self.errors.append(f"{path}: {type(exc).__name__}")
            return
        matched = in_match
        for number, line in enumerate(lines, 1):
            parsed = _split(line)
            if parsed is None:
                continue
            keyword, values = parsed
            if keyword == "match":
                matched = True                                  # to the end of this file
                continue
            if keyword == "include":
                for pattern in values:
                    full = pattern if os.path.isabs(pattern) else os.path.join(self.base, pattern)
                    for hit in sorted(self.glob(full)):
                        self.scan(hit, depth + 1, matched)
                continue
            if keyword != "passwordauthentication" or not values:
                continue
            value = values[0].lower()
            where = f"{path}:{number}"
            if matched:
                if value == "yes" and self.match_yes is None:
                    self.match_yes = where
            elif self.global_value is None:                     # the first value wins
                self.global_value = (value, where)


def check_sshd(*, config: str = SSHD_CONFIG, base: str = SSHD_DIR,
               glob_fn: Callable[[str], list[str]] = glob.glob,
               read: Callable[[str], list[str]] = _read_config) -> dict:
    """Does sshd accept password logins, by its own reading of its configuration?"""
    scan = _SshdScan(base, glob_fn, read)
    try:
        scan.scan(config)                                   # other read errors land in scan.errors
    except FileNotFoundError:
        return _finding("sshd_passwords", OK, "no_sshd_config", config)
    if scan.errors and scan.global_value is None:
        return _finding("sshd_passwords", UNKNOWN, "unreadable", "; ".join(scan.errors))
    value, where = scan.global_value or ("yes", "not set: the sshd default")
    if value == "yes":
        return _finding("sshd_passwords", WARN, "password_auth_enabled", where)
    if value != "no":
        return _finding("sshd_passwords", UNKNOWN, "unrecognised_value", f"{where}: {value}")
    if scan.match_yes:
        return _finding("sshd_passwords", WARN, "password_auth_in_match", scan.match_yes)
    return _finding("sshd_passwords", OK, "password_auth_disabled", where)


# ── container storage ────────────────────────────────────────────────────────


def in_container(*, files: tuple[str, ...] = CONTAINER_FILES, cgroup: str = PID1_CGROUP,
                 exists: Callable[[str], bool] = os.path.exists) -> str | None:
    """The marker that says this is a container, or None."""
    for marker in files:
        try:
            if exists(marker):
                return marker
        except OSError:
            continue
    try:
        text = Path(cgroup).read_text(encoding="utf-8", errors="replace")[:65536]
    except OSError:
        return None
    for marker in CONTAINER_CGROUP_MARKERS:
        if marker in text:
            return f"{cgroup} ({marker})"
    return None


def _unescape(field: str) -> str:
    """mountinfo octal escapes (``\\040`` is a space)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def parse_mountinfo(text: str) -> list[tuple[str, str]]:
    """(mount point, filesystem type) for each line of ``/proc/self/mountinfo``."""
    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if "-" not in fields:
            continue
        dash = fields.index("-")
        if dash < 5 or dash + 1 >= len(fields):
            continue
        mounts.append((_unescape(fields[4]), fields[dash + 1]))
    return mounts


def mount_of(path: str, mounts: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The mount *path* lives on: the longest mount point that contains it (the last
    such line wins, as the kernel stacks a later mount over an earlier one)."""
    best: tuple[str, str] | None = None
    for point, fstype in mounts:
        inside = path == point or point == "/" or path.startswith(point.rstrip("/") + "/")
        if inside and (best is None or len(point) >= len(best[0])):
            best = (point, fstype)
    return best


def check_container_storage(data_root: str | os.PathLike, *, marker: str | None | bool = True,
                            mountinfo: str = MOUNTINFO) -> dict:
    """In a container, is the data root on a volume or bind mount (not the container's
    own filesystem or a tmpfs)?  ``marker=True`` detects the container."""
    found = in_container() if marker is True else marker
    if not found:
        return _finding("container_storage", OK, "not_in_container")
    try:
        text = Path(mountinfo).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _finding("container_storage", UNKNOWN, "no_mountinfo", f"{found}; {type(exc).__name__}")
    root = os.path.realpath(os.fspath(data_root))
    mount = mount_of(root, parse_mountinfo(text))
    if mount is None:
        return _finding("container_storage", UNKNOWN, "no_mount_found", f"{found}; {root}")
    point, fstype = mount
    if point == "/":
        return _finding("container_storage", WARN, "data_root_on_container_root", f"{found}; {root}")
    if fstype in EPHEMERAL_FS:
        return _finding("container_storage", WARN, "data_root_on_tmpfs", f"{found}; {root} on {point}")
    return _finding("container_storage", OK, "data_root_on_mount", f"{root} on {point} ({fstype})")


# ── together ─────────────────────────────────────────────────────────────────


def _data_root() -> Path:
    from agents.core.paths import data_root

    return data_root()


def run_checks(data_root: str | os.PathLike | None = None) -> list[dict]:
    """The three checks, in order; each is independent and none raises."""
    out = []
    for check in (lambda: check_root(), lambda: check_sshd(),
                  lambda: check_container_storage(data_root if data_root is not None else _data_root())):
        try:
            out.append(check())
        except Exception as exc:                                # a check must never break a caller
            logger.debug("host posture check failed", exc_info=True)
            out.append({"check": "unknown", "status": UNKNOWN, "reason": "check_failed",
                        "detail": type(exc).__name__})
    return out


def report(data_root: str | os.PathLike | None = None) -> dict:
    checks = run_checks(data_root)
    return {"checks": checks, "warnings": sum(1 for c in checks if c["status"] == WARN)}


_logged = threading.Event()


def log_startup(data_root: str | os.PathLike | None = None, *, force: bool = False) -> list[dict]:
    """Log each warning once per process (the hub's start); never raises, never blocks."""
    if _logged.is_set() and not force:
        return []
    _logged.set()
    checks = run_checks(data_root)
    for c in checks:
        if c["status"] == WARN:
            logger.warning("host posture: %s (%s): %s. Fix: %s", c["check"], c["reason"], c["detail"], c["fix"])
    return checks


__all__ = [
    "FIX", "OK", "UNKNOWN", "WARN", "check_container_storage", "check_root", "check_sshd", "in_container",
    "log_startup", "mount_of", "parse_mountinfo", "report", "run_checks",
]
