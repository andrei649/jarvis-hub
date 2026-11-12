"""H089 — ``nerva service install | uninstall | show``: run the hub as a per-user service.

Hermes' gateway installs itself as a systemd user unit or a launchd agent from its CLI.
This is Nerva's equivalent, for the default profile of the checkout ``nerva`` runs from:

* **Linux** — ``~/.config/systemd/user/jarvis-hub.service`` (the unit name ``nerva status``
  already looks for). ``Type=notify`` with the watchdog, as the system unit in
  ``deploy/systemd`` (``serve.py`` speaks sd_notify), ``Restart=on-failure`` and
  ``RestartPreventExitStatus=78``: a permanent configuration refusal is not respawned.
  A user unit stops at logout unless lingering is on (``loginctl enable-linger``); the
  install says so.
* **macOS** — ``~/Library/LaunchAgents/ai.nerva.hub.plist``: ``RunAtLoad``, ``KeepAlive``
  = ``{SuccessfulExit: false}`` (launchd has no "do not restart on 78", so the hub run by
  this agent leaves a permanent refusal with 0 — ``agents.core.boot_refusal``), logs in the
  data root's ``logs/`` folder.
* **Windows** — the NSSM service script in ``deploy/windows`` (it needs an elevated shell);
  ``install`` says so and changes nothing.

The command line in the file is this interpreter (``sys.executable``) and this checkout's
``serve.py`` — nothing is taken from a request or the environment. ``install`` refuses to
replace a file it did not write (``--force`` does), never writes through a link, writes
atomically, and with ``--now`` asks the manager to load it (``systemctl --user`` from a
fixed system folder, ``/bin/launchctl``; fixed argv, no shell). ``uninstall`` removes only
a file this command wrote. ``--dry-run`` prints the file and the commands and writes
nothing. A profile other than the default is refused: one unit per checkout.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import plistlib
import subprocess  # nosec B404 - fixed argv: systemctl/launchctl from fixed system folders, no shell
import sys
import tempfile
from pathlib import Path

UNIT_NAME = "jarvis-hub.service"
USER_UNIT_DIR = "~/.config/systemd/user"
LAUNCHD_LABEL = "ai.nerva.hub"
LAUNCH_AGENTS_DIR = "~/Library/LaunchAgents"
LAUNCHCTL = "/bin/launchctl"
MARKER = "written by `nerva service install`"
COMMAND_TIMEOUT_S = 20
MAX_EXISTING_BYTES = 64 * 1024

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


class ServiceError(Exception):
    """A refusal with the owner's next step in its text."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _systemd_quote(value: str) -> str:
    """One ExecStart / WorkingDirectory word: quoted, with systemd's specifier (``%``) and
    variable (``$``) characters escaped. A control character is refused."""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ServiceError("the interpreter or checkout path holds a control character; "
                           "move the checkout to a plain path")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


def _systemd_path(value: str) -> str:
    """A path setting (``WorkingDirectory=``): taken whole, unquoted; only specifiers are
    expanded there, so ``%`` is escaped. It must be absolute."""
    _systemd_quote(value)   # the same control-character refusal
    if not value.startswith("/"):
        raise ServiceError(f"{value!r} is not an absolute path")
    return value.replace("%", "%%")


#: Review M6: the process-only variables that locate the hub. A service started without
#: them would open the default data root — another hub, with empty pairing, memory and
#: keys — so each one set when `install` runs is written into the unit / agent.
LOCATION_VARS = ("JARVIS_HOME", "JARVIS_USER_HOME", "JARVIS_MEMORY_DIR", "JARVIS_MANAGED_DIR")


def location_env(environ) -> dict[str, str]:
    """``{name as spelled: value}`` of :data:`LOCATION_VARS` set in *environ* (either
    spelling — the one the owner used is kept, so the unit never sets one twice)."""
    from agents.core.env_config import resolve_spellings

    found: dict[str, str] = {}
    for name in LOCATION_VARS:
        value, spelled = resolve_spellings(environ or {}, name)
        if isinstance(value, str) and value.strip():
            found[spelled or name] = value
    return found


def marker_line(root: Path) -> str:
    """The exact line that says this command wrote the file, for *this* checkout."""
    return f"Nerva hub — {MARKER} for {root}"


def _systemd_env(name: str, value: str) -> str:
    """One ``Environment=`` line: the whole assignment quoted, ``\\`` ``"`` escaped, and
    systemd's specifier and variable characters doubled."""
    return f"Environment={_systemd_quote(f'{name}={value}')}"


def systemd_user_unit(python: str, root: Path, env: dict[str, str] | None = None) -> str:
    serve = root / "serve.py"
    _systemd_quote(str(root))   # a control character in the checkout path is refused first
    return "\n".join([
        f"# {marker_line(root)}",
        "# Remove with `nerva service uninstall`. Logs: journalctl --user -u jarvis-hub -f",
        "[Unit]",
        "Description=Nerva hub (per-user service)",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "# serve.py tells systemd when it is ready and feeds the watchdog (H283).",
        "Type=notify",
        "NotifyAccess=main",
        "WatchdogSec=60",
        "TimeoutStartSec=300",
        f"WorkingDirectory={_systemd_path(str(root))}",
        f"ExecStart={_systemd_quote(python)} {_systemd_quote(str(serve))}",
        *[_systemd_env(name, value) for name, value in sorted((env or {}).items())],
        "Restart=on-failure",
        "RestartSec=5",
        "# 78: the configuration is refused and no restart can cure it (H089).",
        "RestartPreventExitStatus=78",
        "KillSignal=SIGTERM",
        "TimeoutStopSec=20",
        "NoNewPrivileges=yes",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def launchd_plist(python: str, root: Path, log_dir: Path, env: dict[str, str] | None = None) -> bytes:
    payload = {
        "Label": LAUNCHD_LABEL,
        "Comment": marker_line(root),
        "ProgramArguments": [python, str(root / "serve.py")],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "EnvironmentVariables": {**dict(env or {}), "NERVA_SERVICE_WRAPPER": "launchd"},
        "StandardOutPath": str(log_dir / "service.out.log"),
        "StandardErrorPath": str(log_dir / "service.err.log"),
    }
    return plistlib.dumps(payload, sort_keys=False)


def _platform_kind(platform: str) -> str:
    if platform.startswith("linux"):
        return "systemd"
    if platform == "darwin":
        return "launchd"
    if platform == "win32":
        return "windows"
    return "unsupported"


def _target(kind: str) -> Path:
    if kind == "systemd":
        return Path(os.path.expanduser(USER_UNIT_DIR)) / UNIT_NAME
    return Path(os.path.expanduser(LAUNCH_AGENTS_DIR)) / f"{LAUNCHD_LABEL}.plist"


def _read_existing(path: Path) -> bytes | None:
    """The file at *path*, or None when there is none. A link, a non-regular file or an
    oversized one is refused: this command neither follows nor replaces it."""
    if path.is_symlink():
        raise ServiceError(f"{path} is a link; remove it yourself first")
    if not path.exists():
        return None
    if not path.is_file():
        raise ServiceError(f"{path} is not a regular file; remove it yourself first")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_EXISTING_BYTES + 1)
    if len(data) > MAX_EXISTING_BYTES:
        raise ServiceError(f"{path} is larger than a service file; remove it yourself first")
    return data


def _ours(data: bytes, root: Path, kind: str) -> bool:
    """Whether this command wrote *data* for the checkout *root*: the exact marker line
    (systemd) or ``Comment`` (launchd), not a substring anywhere."""
    if kind == "launchd":
        try:
            return plistlib.loads(data).get("Comment") == marker_line(root)
        except Exception:
            return False
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    return f"# {marker_line(root)}" in lines


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ServiceError(f"{path.parent} is a link; this command does not write through it")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _commands(kind: str, action: str, target: Path) -> list[list[str]]:
    if kind == "systemd":
        from agents.core.service_status import systemctl_path

        binary = systemctl_path()
        if binary is None:
            raise ServiceError("systemctl was not found in a system folder")
        if action == "load":
            return [[binary, "--user", "daemon-reload"],
                    [binary, "--user", "enable", "--now", UNIT_NAME]]
        return [[binary, "--user", "disable", "--now", UNIT_NAME]]
    domain = f"gui/{os.getuid()}" if hasattr(os, "getuid") else "gui/0"
    if action == "load":
        return [[LAUNCHCTL, "bootstrap", domain, str(target)]]
    return [[LAUNCHCTL, "bootout", f"{domain}/{LAUNCHD_LABEL}"]]


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S,  # nosec B603
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, type(exc).__name__
    detail = " ".join((done.stderr or done.stdout or "").split())[:300]
    return done.returncode, detail


def _check_profile(environ) -> None:
    from agents.core.paths import profile_name

    if profile_name(environ):
        raise ServiceError("`nerva service` installs the default profile only; unset "
                           "JARVIS_PROFILE / --profile (a service per profile is not built)")


def install(*, kind: str, python: str, root: Path, environ, dry_run: bool, force: bool,
            now: bool, say, run=_run) -> int:
    _check_profile(environ)
    if not (root / "serve.py").is_file():
        raise ServiceError(f"{root} has no serve.py; run nerva from the checkout you want to serve")
    target = _target(kind)
    env = location_env(environ)
    if kind == "systemd":
        data = systemd_user_unit(python, root, env).encode("utf-8")
    else:
        from agents.core.paths import data_root

        # The service's own data root: the location variables above are in its environment.
        log_dir = data_root(environ) / "logs"
        data = launchd_plist(python, root, log_dir, env)
    existing = _read_existing(target)
    if existing is not None and not _ours(existing, root, kind) and not force:
        raise ServiceError(f"{target} exists and was not written by this command; "
                           "pass --force to replace it")
    commands = _commands(kind, "load", target) if now else []
    if dry_run:
        say(f"would write {target}:")
        say(data.decode("utf-8").rstrip("\n"))
        for argv in commands:
            say("would run: " + " ".join(argv))
        return EXIT_OK
    if kind == "launchd":
        (data_root(environ) / "logs").mkdir(parents=True, exist_ok=True)
    _write_atomic(target, data)
    say(f"wrote {target}" + (" (replaced)" if existing is not None else ""))
    for argv in commands:
        code, detail = run(argv)
        if code != 0:
            say(f"failed: {' '.join(argv)} — {detail or f'exit {code}'}")
            return EXIT_FAILED
        say("ran: " + " ".join(argv))
    if not commands:
        say("start it with: " + "; ".join(" ".join(argv) for argv in _commands(kind, "load", target)))
    if kind == "systemd":
        say("a user service stops when you log out unless lingering is on: loginctl enable-linger")
    return EXIT_OK


def uninstall(*, kind: str, dry_run: bool, say, run=_run, root: Path | None = None) -> int:
    target = _target(kind)
    existing = _read_existing(target)
    if existing is None:
        say(f"nothing to remove: {target} does not exist")
        return EXIT_OK
    if not _ours(existing, root or repo_root(), kind):
        raise ServiceError(f"{target} was not written by `nerva service install`; remove it yourself")
    commands = _commands(kind, "unload", target)
    if dry_run:
        for argv in commands:
            say("would run: " + " ".join(argv))
        say(f"would remove {target}")
        return EXIT_OK
    for argv in commands:
        code, detail = run(argv)
        # Not loaded is fine: the file is still removed.
        say(("ran: " if code == 0 else f"note: {detail or f'exit {code}'} — ") + " ".join(argv))
    target.unlink()
    say(f"removed {target}")
    if kind == "systemd":
        from agents.core.service_status import systemctl_path

        binary = systemctl_path()
        if binary is not None:
            run([binary, "--user", "daemon-reload"])
    return EXIT_OK


def show(*, kind: str, say, root: Path | None = None) -> int:
    target = _target(kind)
    existing = _read_existing(target)
    if existing is None:
        say(f"not installed ({target})")
    else:
        say(f"installed: {target}" + ("" if _ours(existing, root or repo_root(), kind)
                                       else " (not written by nerva service install for this checkout)"))
    return EXIT_OK


def register(verbs) -> None:
    service = verbs.add_parser(
        "service", help="run the hub as a per-user service: systemd user unit or launchd agent (offline)")
    service_verbs = service.add_subparsers(dest="action", required=True)
    inst = service_verbs.add_parser("install", help="write the unit / agent for this checkout")
    inst.add_argument("--dry-run", action="store_true", help="print the file and commands; write nothing")
    inst.add_argument("--force", action="store_true", help="replace a file this command did not write")
    inst.add_argument("--now", action="store_true", help="also enable and start it")
    uninst = service_verbs.add_parser("uninstall", help="stop it and remove the file this command wrote")
    uninst.add_argument("--dry-run", action="store_true")
    service_verbs.add_parser("show", help="whether it is installed, and where")


def run(ns: argparse.Namespace, ctx, *, platform: str | None = None, python: str | None = None,
        root: Path | None = None, runner=_run) -> int:
    kind = _platform_kind(platform or sys.platform)
    if kind == "windows":
        ctx.err.write("On Windows the hub runs as a service through NSSM: run "
                      "deploy\\windows\\install-service.ps1 from an elevated PowerShell.\n")
        return EXIT_USAGE
    if kind == "unsupported":
        ctx.err.write("no per-user service manager is supported on this platform\n")
        return EXIT_USAGE
    try:
        if ns.action == "install":
            return install(kind=kind, python=python or sys.executable, root=root or repo_root(),
                           environ=ctx.environ, dry_run=ns.dry_run, force=ns.force, now=ns.now,
                           say=ctx.say, run=runner)
        if ns.action == "uninstall":
            return uninstall(kind=kind, dry_run=ns.dry_run, say=ctx.say, run=runner, root=root)
        return show(kind=kind, say=ctx.say, root=root)
    except (ServiceError, OSError) as exc:
        ctx.err.write(f"nerva service: {exc}\n")
        return EXIT_FAILED


__all__ = ["install", "launchd_plist", "register", "run", "show", "systemd_user_unit", "uninstall"]
