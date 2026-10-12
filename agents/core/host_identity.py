"""H283 — know what kind of machine this is, and tell the model.

One read-only detector for what kind of host this process runs on, so the prompt, the
skill gates and the doctor's container check describe the same machine:

- **container** — ``JARVIS_CONTAINER`` (the operator's word: a kind such as ``docker``, or
  ``1``/``true``/``yes``/``on`` for "some container"; ``none`` or any ``env_config`` falsy
  spelling, ``0``/``false``/``no``/``off``/``disable``/``disabled``, says "not a container"; a word
  that is neither is ignored and the markers decide), ``KUBERNETES_SERVICE_HOST`` (a pod), the marker files and PID 1 cgroup
  that ``host_posture.in_container`` reads, ``/run/systemd/container`` and the
  ``container`` variable podman and systemd-nspawn set. A cgroup v2 ``0::/`` with no
  marker says nothing: it is never read as "bare host".
- **WSL** (``WSL_DISTRO_NAME``/``WSL_INTEROP`` or a Microsoft kernel release) and
  **Termux** (``TERMUX_VERSION``, a ``com.termux`` ``PREFIX`` or its data directory).
- **supervisor** — ``s6`` (``S6_VERSION``/``S6_CMD_ARG0`` — the variables s6-overlay's
  init exports — or ``/run/s6``), ``systemd`` (a usable ``NOTIFY_SOCKET`` — the address ``sd_notify`` would send to — or ``INVOCATION_ID`` without a
  terminal; journal logging only when ``JOURNAL_STREAM`` names this stderr, as
  systemd documents; the watchdog from ``WATCHDOG_USEC`` for this PID), ``launchd``
  (macOS: ``LAUNCHD_SOCKET`` or a job's ``XPC_SERVICE_NAME``), else ``none``.
- **terminal and multiplexer** — ``WT_SESSION``, ``ITERM_SESSION_ID``,
  ``KITTY_WINDOW_ID``, ``WEZTERM_PANE``, ``GHOSTTY_*``, ``TERM_PROGRAM``, ``TMUX``,
  ``STY``, ``TERM``, ``COLORTERM``, ``COLORFGBG`` — each mapped onto a closed
  vocabulary; a raw value is never echoed.
- **machine id** — ``JARVIS_MACHINE_ID``, else ``/etc/machine-id`` (or dbus's, or the
  Windows ``MachineGuid``), given only as an app-specific keyed hash prefix (16 hex
  characters), never the raw value, and never to the model.

Every value that leaves this module is from a closed vocabulary, a boolean, a bounded
integer, the sanitised WSL distro name or the hash prefix. :func:`identity` is
computed once per process, so the prompt line built from it is byte-stable and the
prompt cache holds. Reported by ``GET /api/host/probe`` (``identity``, the HUD's host
readiness card), given to the model as one labelled line (:meth:`HostIdentity.prompt_line`,
through ``environment_hint.hint_block``), and printed for the calling shell by
``python -m agents.core.host_identity``. Stdlib only.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import logging
import math
import os
import re
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from . import host_posture

logger = logging.getLogger("jarvis.host_identity")

ENV_CONTAINER = "JARVIS_CONTAINER"
ENV_MACHINE_ID = "JARVIS_MACHINE_ID"

SYSTEMD_CONTAINER = "/run/systemd/container"
OSRELEASE = "/proc/sys/kernel/osrelease"
TERMUX_HOME = "/data/data/com.termux"
S6_PATHS = ("/run/s6", "/command/s6-svscan")
MACHINE_ID_FILES = (("/etc/machine-id", "etc"), ("/var/lib/dbus/machine-id", "dbus"))

CONTAINER_KINDS = ("docker", "podman", "kubernetes", "lxc", "containerd", "nspawn", "container")
WSL_KINDS = ("wsl1", "wsl2", "wsl")
SUPERVISORS = ("systemd", "s6", "launchd", "none")
TERMINALS = ("windows-terminal", "iterm2", "apple-terminal", "kitty", "wezterm", "ghostty", "alacritty",
             "konsole", "vte", "vscode", "warp", "hyper", "other", "none")
MULTIPLEXERS = ("tmux", "screen", "zellij", "none")
TERM_FAMILIES = ("xterm", "screen", "tmux", "linux", "vt", "dumb", "other", "none")
COLORS = ("truecolor", "256", "basic", "none")
BACKGROUNDS = ("dark", "light", "unknown")
MACHINE_ID_SOURCES = ("override", "etc", "dbus", "windows", "none")

#: A container word (operator's, systemd's or podman's) → the closed kind.
_KIND_WORDS = {
    "docker": "docker", "podman": "podman", "kubernetes": "kubernetes", "k8s": "kubernetes",
    "lxc": "lxc", "lxc-libvirt": "lxc", "containerd": "containerd", "systemd-nspawn": "nspawn",
    "nspawn": "nspawn", "oci": "container", "container": "container",
}
#: ``host_posture.in_container``'s marker → the kind it shows.
_MARKER_KINDS = {".dockerenv": "docker", ".containerenv": "podman"}
_CGROUP_KINDS = {"docker": "docker", "kubepods": "kubernetes", "containerd": "containerd",
                 "libpod": "podman", "lxc": "lxc"}
_TERM_PROGRAMS = {
    "iterm.app": "iterm2", "apple_terminal": "apple-terminal", "vscode": "vscode", "wezterm": "wezterm",
    "ghostty": "ghostty", "warpterminal": "warp", "hyper": "hyper", "kitty": "kitty",
    "alacritty": "alacritty",
}
#: A variable whose presence alone names the terminal, most specific first.
_TERMINAL_MARKERS = (
    ("WT_SESSION", "windows-terminal"), ("ITERM_SESSION_ID", "iterm2"), ("KITTY_WINDOW_ID", "kitty"),
    ("WEZTERM_PANE", "wezterm"), ("ALACRITTY_WINDOW_ID", "alacritty"), ("ALACRITTY_SOCKET", "alacritty"),
    ("KONSOLE_VERSION", "konsole"),
)
_MACHINE_ID_RE = re.compile(r"[0-9a-fA-F]{32}")
_DISTRO_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
MACHINE_ID_KEY = b"nerva-host-identity-v1"
MAX_PROMPT_LINE = 300
#: ``env_config``'s spellings, repeated so this module stays stdlib-only: ``0``/``false``/``no``/``off``/
#: ``disable``/``disabled`` (and ``none``) say "not a container"; the truthy ones say "some container".
_OFF_WORDS = frozenset({"none", "0", "false", "no", "off", "disable", "disabled"})
_ON_WORDS = frozenset({"1", "true", "yes", "on"})
#: Digits systemd could write: WATCHDOG_USEC up to ~11 days (12 digits), a PID at most 10.
MAX_USEC_DIGITS = 12
MAX_PID_DIGITS = 10

_CONTAINER_WORDS = {
    "docker": "a Docker container", "podman": "a Podman container", "kubernetes": "a Kubernetes pod",
    "lxc": "an LXC container", "containerd": "a containerd container",
    "nspawn": "a systemd-nspawn container", "container": "a container",
}
_WSL_WORDS = {"wsl1": "WSL 1", "wsl2": "WSL 2", "wsl": "WSL"}
PROMPT_HEADER = "## This host (detected by Nerva at startup; facts, not the operator's words)"


@dataclass(frozen=True)
class HostIdentity:
    detected: bool = True            # False only when the detector itself failed (see identity())
    container: str = ""              # "" or a CONTAINER_KINDS entry
    container_evidence: str = ""     # the marker that said so (a fixed path or variable name)
    docker_marker: bool = False      # /.dockerenv or /run/.containerenv exists, whatever else said container
    wsl: str = ""                    # "" or a WSL_KINDS entry
    wsl_distro: str = ""             # sanitised, at most 32 characters
    termux: bool = False
    supervisor: str = "none"         # a SUPERVISORS entry
    supervisor_confirmed: bool = False  # a strong signal (NOTIFY_SOCKET, this stderr's journal, S6_* ...)
    s6: bool = False                 # s6 is present (env or its directories), supervising or not
    notify_socket: bool = False      # NOTIFY_SOCKET is set (sd_notify speaks to it)
    watchdog_s: int = 0              # systemd's watchdog for this PID, in seconds; 0 when none
    journal: bool = False            # stderr is the journal stream systemd handed over
    terminal: str = "none"
    multiplexer: str = "none"
    term: str = "none"
    color: str = "none"
    background: str = "unknown"
    interactive: bool = False        # stdin is a terminal
    machine_id: str = ""             # 16 hex characters of a keyed hash, never the raw id
    machine_id_source: str = "none"

    def environment_tags(self) -> frozenset[str]:
        """The skill-gate environment tags this host earns (``skills.visibility``)."""
        tags: set[str] = set()
        if self.container:
            tags.add("container")
            tags.add("docker" if self.container in ("docker", "podman") else self.container)
            if self.docker_marker:  # as the skill gate always read it: a marker file means docker
                tags.add("docker")
        if self.s6:
            tags.add("s6")
        return frozenset(tags)

    def prompt_line(self) -> str:
        """One closed-vocabulary sentence for the model, or ``""`` when there is nothing
        to say. Terminal and machine id stay out: they describe a shell, not the hub."""
        parts = []
        if self.container:
            parts.append(f"in {_CONTAINER_WORDS[self.container]}")
        if self.wsl:
            parts.append(f"under Windows ({_WSL_WORDS[self.wsl]})")
        if self.termux:
            parts.append("in Termux on Android")
        if self.supervisor != "none" and self.supervisor_confirmed:
            extra = [word for flag, word in ((self.journal, "logs go to the journal"),
                                             (self.watchdog_s > 0, "the unit sets a systemd watchdog"))
                     if flag]
            parts.append(f"supervised by {self.supervisor}" + (f" ({'; '.join(extra)})" if extra else ""))
        elif self.supervisor == "s6":  # the directories exist; that does not make s6 this hub's parent
            parts.append("alongside an s6 supervision tree")
        if not parts:
            return ""
        return f"This hub runs {', '.join(parts)}."[:MAX_PROMPT_LINE]

    def prompt_block(self) -> str:
        line = self.prompt_line()
        return f"{PROMPT_HEADER}\n{line}" if line else ""

    def to_dict(self) -> dict:
        if not self.detected:  # the shape the probe route and the HUD already report
            return {"detected": False, "reason": "identity_failed"}
        row = asdict(self)
        for key in ("container", "container_evidence", "wsl", "wsl_distro", "machine_id"):
            row[key] = row[key] or None
        row["watchdog_s"] = self.watchdog_s or None
        row["prompt_line"] = self.prompt_line()
        return row


# ── the parts ────────────────────────────────────────────────────────────────


def _exists(exists: Callable[[str], bool], path: str) -> bool:
    try:
        return bool(exists(path))
    except (OSError, ValueError):
        return False


def _read(read_text: Callable[[str], str], path: str, limit: int = 4096) -> str:
    try:
        return (read_text(path) or "")[:limit]
    except (OSError, UnicodeError, ValueError):
        return ""


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(4096)


def _kind_word(word: str) -> str:
    return _KIND_WORDS.get(word.strip().lower(), "container")


def detect_container(env: Mapping[str, str], *, exists: Callable[[str], bool] = os.path.exists,
                     read_text: Callable[[str], str] = _read_file,
                     files: tuple[str, ...] = host_posture.CONTAINER_FILES,
                     cgroup: str = host_posture.PID1_CGROUP,
                     systemd_container: str = SYSTEMD_CONTAINER) -> tuple[str, str]:
    """``(kind, evidence)``, or ``("", "")`` when nothing says this is a container.
    The marker files and the PID 1 cgroup are ``host_posture.in_container``'s own read."""
    override = (env.get(ENV_CONTAINER) or "").strip().lower()
    if override in _OFF_WORDS:
        return "", ENV_CONTAINER
    if override in _ON_WORDS:
        return "container", ENV_CONTAINER
    if override in _KIND_WORDS:
        return _KIND_WORDS[override], ENV_CONTAINER
    # any other word (a typo, "yes please") is not an answer: the markers below decide
    if env.get("KUBERNETES_SERVICE_HOST"):
        return "kubernetes", "KUBERNETES_SERVICE_HOST"
    marker = host_posture.in_container(files=files, cgroup=cgroup, exists=exists)
    if marker:
        name = os.path.basename(marker)
        if name in _MARKER_KINDS:
            return _MARKER_KINDS[name], marker
        found = next((kind for word, kind in _CGROUP_KINDS.items() if f"({word})" in marker), "container")
        return found, marker
    word = _read(read_text, systemd_container, 64).strip()
    if word:
        return _kind_word(word), systemd_container
    if (env.get("container") or "").strip():
        return _kind_word(env["container"]), "container"
    return "", ""


def detect_wsl(env: Mapping[str, str], *, read_text: Callable[[str], str] = _read_file,
               platform: str = sys.platform, osrelease: str = OSRELEASE) -> tuple[str, str]:
    """``(kind, distro)``: ``wsl2``/``wsl1``/``wsl`` (version unknown), or ``("", "")``."""
    if not platform.startswith("linux"):
        return "", ""
    release = _read(read_text, osrelease, 256).lower()
    from_env = bool(env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"))
    if "microsoft-standard" in release or "wsl2" in release:
        kind = "wsl2"
    elif "microsoft" in release:
        kind = "wsl1"
    elif from_env:
        kind = "wsl"
    else:
        return "", ""
    distro = _DISTRO_UNSAFE.sub("", env.get("WSL_DISTRO_NAME") or "")[:32]
    return kind, distro


def detect_termux(env: Mapping[str, str], *, exists: Callable[[str], bool] = os.path.exists) -> bool:
    return bool(env.get("TERMUX_VERSION")) or "com.termux" in (env.get("PREFIX") or "") \
        or _exists(exists, TERMUX_HOME)


def _journal(env: Mapping[str, str], stderr_id: Callable[[], tuple[int, int] | None]) -> bool:
    """systemd's own test: ``JOURNAL_STREAM`` is ``device:inode`` of the stderr it handed over."""
    stream = env.get("JOURNAL_STREAM") or ""
    try:
        device, inode = (int(part) for part in stream.split(":"))
        return stderr_id() == (device, inode)
    except (ValueError, TypeError, OSError):
        return False


def _stderr_id() -> tuple[int, int] | None:
    try:
        st = os.fstat(2)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _decimal(raw: str, max_digits: int) -> int | None:
    """An ASCII decimal of at most ``max_digits``, as systemd writes them; ``int()`` alone takes
    ``٦٠``, ``6_0`` and ``+60``, and raises past 4,300 digits."""
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= max_digits else None


def notify_address(raw: str | None) -> str | bytes | None:
    """``NOTIFY_SOCKET`` as the socket address ``sd_notify`` sends to: a path, or ``@name`` for the
    abstract namespace (Linux). Unset, blank, relative or another scheme (``vsock:``) is no socket.
    The one parser: the prompt only says "supervised" where ``sd_notify`` would speak."""
    text = (raw or "").strip()
    if text.startswith("@"):
        return b"\0" + text[1:].encode("utf-8", "surrogateescape")
    if text.startswith("/"):
        return text
    return None


def watchdog_deadline(env: Mapping[str, str], pid: int) -> float | None:
    """``WATCHDOG_USEC`` in seconds when systemd armed the watchdog for ``pid``, else None.
    ``WATCHDOG_PID`` names the main PID: a child that inherited the variables is not armed.
    ``sd_notify`` pings from this same reading, so the prompt and the heartbeat agree."""
    usec = _decimal((env.get("WATCHDOG_USEC") or "").strip(), MAX_USEC_DIGITS)
    if not usec:
        return None
    owner = (env.get("WATCHDOG_PID") or "").strip()
    if owner and _decimal(owner, MAX_PID_DIGITS) != pid:
        return None
    return usec / 1_000_000


def _watchdog_seconds(env: Mapping[str, str], pid: int) -> int:
    deadline = watchdog_deadline(env, pid)
    return 0 if deadline is None else max(1, min(math.ceil(deadline), 86_400))


def detect_supervisor(env: Mapping[str, str], *, exists: Callable[[str], bool] = os.path.exists,
                      platform: str = sys.platform, interactive: bool = False,
                      stderr_id: Callable[[], tuple[int, int] | None] = _stderr_id,
                      pid: int | None = None) -> dict:
    """``supervisor``, ``s6``, ``notify_socket``, ``watchdog_s`` and ``journal``."""
    s6_env = any(env.get(name) for name in ("S6_VERSION", "S6_CMD_ARG0"))
    s6_files = any(_exists(exists, path) for path in S6_PATHS)
    notify = notify_address(env.get("NOTIFY_SOCKET")) is not None and hasattr(socket, "AF_UNIX")
    # INVOCATION_ID alone also reaches shells in a terminal that runs as a user service.
    systemd = notify or (bool(env.get("INVOCATION_ID")) and not interactive)
    xpc = (env.get("XPC_SERVICE_NAME") or "").strip()
    launchd = platform == "darwin" and (bool(env.get("LAUNCHD_SOCKET"))
                                        or (xpc not in ("", "0") and not xpc.startswith("application.")))
    if s6_env:
        supervisor = "s6"
    elif systemd:
        supervisor = "systemd"
    elif launchd:
        supervisor = "launchd"
    elif s6_files:
        supervisor = "s6"
    else:
        supervisor = "none"
    on_systemd = supervisor == "systemd"
    journal = on_systemd and _journal(env, stderr_id)
    # Strong: the manager itself handed us a socket or this very stderr, or the S6_* variables the
    # init sets. Weak: INVOCATION_ID (also set for a transient scope, e.g. `nohup` from a desktop
    # terminal), the s6 directories (also present in `docker exec` into an s6 image), a launchd name.
    confirmed = (on_systemd and (notify or journal)) or (supervisor == "s6" and s6_env) \
        or supervisor == "launchd"
    return {
        "supervisor": supervisor,
        "supervisor_confirmed": confirmed,
        "s6": s6_env or s6_files,
        "notify_socket": notify,
        "watchdog_s": _watchdog_seconds(env, os.getpid() if pid is None else pid) if on_systemd else 0,
        "journal": journal,
    }


def _term_family(term: str) -> str:
    term = term.strip().lower()
    if not term:
        return "none"
    for prefix in ("xterm", "screen", "tmux", "linux", "vt", "dumb"):
        if term.startswith(prefix):
            return prefix
    return "other"


def detect_terminal(env: Mapping[str, str], *, interactive: bool = False) -> dict:
    """Terminal, multiplexer, ``TERM`` family, colour depth and background: names only."""
    terminal = next((name for var, name in _TERMINAL_MARKERS if env.get(var)), "")
    if not terminal and any(key.startswith("GHOSTTY_") for key in env):
        terminal = "ghostty"
    program = (env.get("TERM_PROGRAM") or "").strip().lower()
    if not terminal and program and program != "tmux":
        terminal = _TERM_PROGRAMS.get(program, "other")
    if not terminal and env.get("VTE_VERSION"):
        terminal = "vte"
    raw_term = env.get("TERM") or ""
    family = _term_family(raw_term)
    if not terminal:
        terminal = "other" if family not in ("none", "dumb") else "none"
    if env.get("TMUX") or program == "tmux":
        multiplexer = "tmux"
    elif env.get("STY"):
        multiplexer = "screen"
    elif env.get("ZELLIJ"):
        multiplexer = "zellij"
    else:
        multiplexer = "none"
    colorterm = (env.get("COLORTERM") or "").strip().lower()
    if colorterm in ("truecolor", "24bit"):
        color = "truecolor"
    elif "256color" in raw_term.lower():
        color = "256"
    elif family not in ("none", "dumb"):
        color = "basic"
    else:
        color = "none"
    background = "unknown"
    fgbg = (env.get("COLORFGBG") or "").split(";")
    if len(fgbg) >= 2 and fgbg[-1].strip().isdigit():
        bg = int(fgbg[-1])
        if 0 <= bg <= 15:
            background = "dark" if bg <= 6 or bg == 8 else "light"
    return {"terminal": terminal, "multiplexer": multiplexer, "term": family, "color": color,
            "background": background, "interactive": interactive}


def _windows_machine_guid() -> str:
    import winreg  # type: ignore[import-not-found]

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
        return str(winreg.QueryValueEx(key, "MachineGuid")[0])


def hash_machine_id(raw: str) -> str:
    """An app-specific keyed hash of the raw id (systemd's app-specific id pattern):
    stable on this machine, useless for joining it with any other program's id."""
    return hmac.new(raw.encode("utf-8", "replace"), MACHINE_ID_KEY, hashlib.sha256).hexdigest()[:16]


def detect_machine_id(env: Mapping[str, str], *, read_text: Callable[[str], str] = _read_file,
                      platform: str = sys.platform,
                      windows_guid: Callable[[], str] = _windows_machine_guid) -> tuple[str, str]:
    """``(hash prefix, source)``; ``("", "none")`` when no id could be read."""
    override = (env.get(ENV_MACHINE_ID) or "").strip()[:256]
    if override:
        return hash_machine_id(override), "override"
    for path, source in MACHINE_ID_FILES:
        raw = _read(read_text, path, 256).strip()
        if _MACHINE_ID_RE.fullmatch(raw):
            return hash_machine_id(raw.lower()), source
    if platform.startswith("win"):
        try:
            raw = windows_guid().strip()
        except (OSError, ImportError, AttributeError):
            raw = ""
        if raw:
            return hash_machine_id(raw.lower()), "windows"
    return "", "none"


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def detect(env: Mapping[str, str] | None = None, *, exists: Callable[[str], bool] = os.path.exists,
           read_text: Callable[[str], str] = _read_file, platform: str = sys.platform,
           isatty: Callable[[], bool] = _stdin_is_tty,
           stderr_id: Callable[[], tuple[int, int] | None] = _stderr_id,
           windows_guid: Callable[[], str] = _windows_machine_guid,
           files: tuple[str, ...] = host_posture.CONTAINER_FILES,
           cgroup: str = host_posture.PID1_CGROUP, pid: int | None = None) -> HostIdentity:
    """Everything above, from ``env`` and the file system (each a parameter, for tests)."""
    env = os.environ if env is None else env
    interactive = bool(isatty())
    container, evidence = detect_container(env, exists=exists, read_text=read_text, files=files, cgroup=cgroup)
    marker = bool(container) and any(_exists(exists, path) for path in files)
    wsl, distro = detect_wsl(env, read_text=read_text, platform=platform)
    machine_id, source = detect_machine_id(env, read_text=read_text, platform=platform, windows_guid=windows_guid)
    return HostIdentity(
        container=container, container_evidence=evidence, docker_marker=marker, wsl=wsl, wsl_distro=distro,
        termux=detect_termux(env, exists=exists),
        **detect_supervisor(env, exists=exists, platform=platform, interactive=interactive,
                            stderr_id=stderr_id, pid=pid),
        **detect_terminal(env, interactive=interactive),
        machine_id=machine_id, machine_id_source=source,
    )


@functools.lru_cache(maxsize=1)
def identity() -> HostIdentity:
    """This process's host, detected once: the same bytes for every prompt it builds."""
    try:
        return detect()
    except Exception:  # a detector bug must never stop a prompt or a probe, nor pass as a bare host
        logger.warning("host identity could not be detected: the prompt says nothing about the host")
        return HostIdentity(detected=False)


def prompt_block() -> str:
    """The system prompt's block of detected facts, or ``""`` (never raises)."""
    try:
        return identity().prompt_block()
    except Exception:
        return ""


def container_marker() -> str | None:
    """What says this process is in a container (``host_posture``'s storage check), or None."""
    _kind, evidence = detect_container(os.environ)
    return evidence if _kind else None


def main(argv: list[str] | None = None) -> int:
    """``python -m agents.core.host_identity``: this shell's host, as JSON."""
    print(json.dumps(detect().to_dict(), indent=2, sort_keys=True))
    return 0


__all__ = [
    "BACKGROUNDS", "COLORS", "CONTAINER_KINDS", "ENV_CONTAINER", "ENV_MACHINE_ID", "HostIdentity",
    "MACHINE_ID_SOURCES", "MULTIPLEXERS", "PROMPT_HEADER", "SUPERVISORS", "TERMINALS", "TERM_FAMILIES",
    "WSL_KINDS", "container_marker", "detect", "detect_container", "detect_machine_id",
    "detect_supervisor", "detect_terminal", "detect_termux", "detect_wsl", "hash_machine_id", "identity",
    "main", "notify_address", "prompt_block", "watchdog_deadline",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
