"""H235 — what the terminal chat shows about where it runs: working directory and git
branch, battery, and the clipboard through OSC 52.

Everything here reads this machine only (no hub, no network), never runs a shell, and
returns text already made safe to draw (control, bidi and zero-width characters removed,
bounded). The battery is read from the platform's own source: ``/sys/class/power_supply``
on Linux, ``/usr/bin/pmset -g batt`` (fixed absolute argv, 2 s budget) on macOS,
``GetSystemPowerStatus`` on Windows; anything else, or a machine without a battery, is
``None`` and nothing is shown.
"""

from __future__ import annotations

import base64
import os
import re
import stat
import subprocess  # nosec B404 — one fixed absolute argv (pmset), no shell
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Bytes read from a git HEAD or ``.git`` file, and levels walked up to find one.
_GIT_READ = 4096
_GIT_DEPTH = 64
#: OSC 52 payloads past this many base64 bytes are refused (terminals cut them silently).
OSC52_LIMIT = 74_994


def _safe(text: Any, width: int, *, keep_tail: bool = False) -> str:
    from .chat_prompts import card_safe

    line = card_safe(text)
    if len(line) <= width:
        return line
    return "…" + line[-(width - 1):] if keep_tail else line[: width - 1] + "…"


_OPEN_FLAGS = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
               | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_BINARY", 0))


def _trusted_owner(info: os.stat_result) -> bool:
    """Owned by this user or by root (git's safe.directory idea); always true where
    the platform has no uids."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid is None or info.st_uid in (0, geteuid())


def _read_small(path: Path) -> str | None:
    """Up to _GIT_READ bytes of *path* — only a regular file owned by this user or root,
    opened non-blocking and without following a symlink (a FIFO, a device or a link to
    /dev/tty is refused, never waited on; review M2)."""
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not _trusted_owner(info):
            return None
        return os.read(fd, _GIT_READ).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def _kind(path: Path) -> str | None:
    """``dir`` / ``file`` for a real (not symlinked) directory or regular file owned by
    this user or root; None otherwise."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not _trusted_owner(info):
        return None
    if stat.S_ISDIR(info.st_mode):
        return "dir"
    return "file" if stat.S_ISREG(info.st_mode) else None


def git_branch(start: Path, home: Path | None = None) -> str | None:
    """The branch checked out at *start* (or above it): its name, ``@<sha12>`` when
    detached, None outside a repository. Reads ``.git/HEAD`` (following a worktree's
    ``gitdir:`` file); runs no git. The walk up stops at *home* and at a filesystem
    boundary, and a ``.git`` owned by someone else is not read."""
    here = start
    try:
        device = os.stat(here).st_dev
    except OSError:
        return None
    for _ in range(_GIT_DEPTH):
        dot = here / ".git"
        kind = _kind(dot)
        if kind == "dir":
            head = _read_small(dot / "HEAD")
            break
        if kind == "file":
            pointer = (_read_small(dot) or "").strip()
            if not pointer.startswith("gitdir:"):
                return None
            gitdir = Path(pointer[len("gitdir:"):].strip())
            head = _read_small((gitdir if gitdir.is_absolute() else here / gitdir) / "HEAD")
            break
        if here.parent == here or (home is not None and here == home):
            return None
        here = here.parent
        try:
            if os.stat(here).st_dev != device:
                return None
        except OSError:
            return None
    else:
        return None
    head = (head or "").strip()
    if head.startswith("ref:"):
        ref = head[len("ref:"):].strip()
        name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        return _safe(name, 60) or None
    if re.fullmatch(r"[0-9a-f]{40,64}", head):
        return f"@{head[:12]}"
    return None


def cwd_label(cwd: Path, home: Path | None) -> str:
    """*cwd* with the home folder as ``~``, safe to draw, the tail kept when long."""
    text = str(cwd)
    if home is not None:
        try:
            rest = cwd.relative_to(home)
            text = "~" if str(rest) == "." else f"~/{rest}"
        except ValueError:
            pass
    return _safe(text, 60, keep_tail=True)


@dataclass(frozen=True)
class Battery:
    percent: int
    charging: bool

    def label(self) -> str:
        return f"battery {self.percent}%" + (" (charging)" if self.charging else "")


def _linux_battery(root: Path) -> Battery | None:
    try:
        supplies = sorted(root.iterdir())
    except OSError:
        return None
    for supply in supplies:
        if (_read_small(supply / "type") or "").strip() != "Battery":
            continue
        capacity = (_read_small(supply / "capacity") or "").strip()
        if not capacity.isdigit():
            continue
        status = (_read_small(supply / "status") or "").strip().lower()
        return Battery(max(0, min(100, int(capacity))), status in ("charging", "full", "not charging"))
    return None


_PMSET = re.compile(r"(\d{1,3})%;\s*([a-z ]+)")


def parse_pmset(text: str) -> Battery | None:
    """``pmset -g batt`` output (``… 54%; discharging; 3:12 remaining``) as a Battery."""
    match = _PMSET.search(text or "")
    if match is None:
        return None
    state = match.group(2).strip()
    return Battery(max(0, min(100, int(match.group(1)))), state in ("charging", "charged", "finishing charge",
                                                                    "ac attached"))


def _mac_battery(run: Callable[[list[str]], str] | None) -> Battery | None:
    def default(argv: list[str]) -> str:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=2, check=False)  # nosec B603
        return done.stdout[:4096]

    try:
        return parse_pmset((run or default)(["/usr/bin/pmset", "-g", "batt"]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _windows_battery() -> Battery | None:
    import ctypes

    class _Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    status = _Status()
    try:
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None
    except (AttributeError, OSError):
        return None
    percent = status.BatteryLifePercent & 0xFF
    if status.BatteryFlag & 0x80 or percent == 255:      # no system battery / unknown
        return None
    return Battery(min(100, percent), status.ACLineStatus == 1)


def battery(*, platform: str | None = None, sysfs: Path = Path("/sys/class/power_supply"),
            run: Callable[[list[str]], str] | None = None) -> Battery | None:
    """This machine's battery, or None (no battery, or a platform this cannot read)."""
    platform = platform or sys.platform
    if platform.startswith("linux"):
        return _linux_battery(sysfs)
    if platform == "darwin":
        return _mac_battery(run)
    if platform == "win32":
        return _windows_battery()
    return None


def osc52(text: str, environ: Mapping[str, str]) -> str | None:
    """The OSC 52 sequence that puts *text* on the terminal's clipboard (wrapped for
    tmux), or None when it is too long to send. The payload is base64, so nothing in
    *text* can reach the terminal as a control sequence."""
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(payload) > OSC52_LIMIT:
        return None
    sequence = f"\x1b]52;c;{payload}\x07"
    if environ.get("TMUX"):
        sequence = "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return sequence
