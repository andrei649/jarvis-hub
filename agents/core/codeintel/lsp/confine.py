"""confine.py — how a language server (third-party code) is started.

A language server is a long-lived child, so the one-shot :mod:`agents.core.sandbox`
runner does not fit it. This module builds the same posture for it:

* **Scrubbed environment** — :func:`agents.core.environments.scrub_child_env` (no
  secret-looking names), ``HOME``/``XDG_*``/``TMPDIR`` pointed at a per-server state
  directory, and every toolchain told not to fetch (``GOPROXY=off``,
  ``GOTOOLCHAIN=local``, ``npm_config_offline``).
* **Filesystem and network isolation** with ``bwrap`` (bubblewrap): every namespace
  unshared (no network at all) and an allowlisted filesystem — the system directories
  and a few ``/etc`` entries read-only, the server's own runtime read-only, the
  workspace read-only, the server's private state directory read-write, a fresh
  ``/proc`` and ``/tmp``. Nothing else of the host is mounted: the owner's home and
  Nerva's data root are absent, and a runtime directory that is or holds one of them
  is never bound (see :func:`runtime_dirs`). The server's working directory is its
  state directory, not the workspace.
* **Resource limits** on POSIX: data segment (``RLIMIT_DATA``, which V8's large
  virtual reservations do not trip as ``RLIMIT_AS`` would), cumulative CPU seconds,
  file size, open files, no core dumps; its own session so the whole group dies on
  stop. Idle servers are killed by the manager.

When ``bwrap`` is missing or cannot create namespaces, no server starts
(``sandbox_unavailable``): ``JARVIS_LSP_REQUIRE_SANDBOX`` defaults on. An owner who sets
it to ``0`` gets servers with the environment and the limits only, and
:func:`isolation` says so (``rlimits``).
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess  # nosec B404 — fixed argv probes, never a shell
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from agents.core.env_config import env_flag, env_int, env_str

logger = logging.getLogger("jarvis.codeintel.lsp")

REQUIRE_SANDBOX_ENV = "JARVIS_LSP_REQUIRE_SANDBOX"
MEMORY_ENV = "JARVIS_LSP_MEMORY_MB"
DEFAULT_MEMORY_MB = 2048
#: Cumulative CPU seconds one server process may burn before the kernel stops it.
CPU_SECONDS = 3600
FILE_SIZE_BYTES = 256 * 1024 * 1024
OPEN_FILES = 4096


class ConfinementRefused(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@functools.lru_cache(maxsize=1)
def _bwrap() -> str | None:
    """The bubblewrap binary when it can actually create the namespaces we use."""
    if not sys.platform.startswith("linux"):
        return None
    path = shutil.which("bwrap")
    if not path:
        return None
    try:
        probe = subprocess.run(  # nosec B603 — absolute binary, fixed argv
            [path, "--die-with-parent", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev",
             "--proc", "/proc", "--tmpfs", "/tmp", "true"],  # nosec B108 — a mount target in the sandbox
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return path if probe.returncode == 0 else None


def isolation() -> str:
    """``bwrap`` (namespaces + limits), ``rlimits`` (limits only) or ``none`` (Windows)."""
    if _bwrap():
        return "bwrap"
    return "rlimits" if os.name == "posix" else "none"


def memory_mb() -> int:
    return env_int(MEMORY_ENV, DEFAULT_MEMORY_MB, minimum=256)


def child_env(state_dir: Path, *, extra_path: tuple[Path, ...] = (),
              source: Mapping[str, str] | None = None, offline: bool = True) -> dict[str, str]:
    from agents.core.environments import scrub_child_env

    env = scrub_child_env(dict(os.environ if source is None else source))
    home = state_dir / "home"
    cache = state_dir / "cache"
    tmp = state_dir / "tmp"
    for directory in (home, cache, tmp):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update({
        "HOME": str(home), "XDG_CACHE_HOME": str(cache), "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"), "TMPDIR": str(tmp),
        "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=mod", "GOTELEMETRY": "off",
        "NO_UPDATE_NOTIFIER": "1", "npm_config_update_notifier": "false",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
    })
    if offline:
        env.update({"GOPROXY": "off", "npm_config_offline": "true", "PIP_NO_INDEX": "1"})
    # Absolute entries only: a relative one ("", ".", "bin") would resolve against the
    # server's working directory.
    path = [str(p) for p in extra_path] + [p for p in env.get("PATH", os.defpath).split(os.pathsep)
                                           if p and os.path.isabs(p)]
    env["PATH"] = os.pathsep.join(dict.fromkeys(path))
    return env


def _hidden_roots() -> list[str]:
    """Directories a server must not read: the owner's home and Nerva's data root."""
    hidden: list[str] = []
    for raw in (os.path.expanduser("~"), env_str("HOME", "")):
        if raw and raw != "/" and os.path.isdir(raw):
            hidden.append(os.path.realpath(raw))
    try:
        from agents.core.paths import data_root

        hidden.append(str(data_root().resolve()))
    except Exception:  # noqa: BLE001 — an unset data root hides nothing more
        logger.debug("no data root to hide from language servers", exc_info=True)
    keep = ("/", "/usr", "/etc", "/opt", "/tmp")  # nosec B108 — paths never hidden, not a file use
    return [h for h in dict.fromkeys(hidden) if h not in keep]


#: The system directories every sandbox sees, read-only (a symlinked one stays a symlink).
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32")
#: The few ``/etc`` entries a runtime needs (the loader cache, users, TLS roots, name
#: resolution for an install). Never ``/etc`` whole.
ETC_ENTRIES = ("ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "nsswitch.conf", "passwd",
               "group", "localtime", "ssl", "ca-certificates", "pki", "mime.types", "os-release",
               "resolv.conf", "hosts", "host.conf", "gai.conf")


def _contains_hidden(directory: Path, hidden: list[str]) -> bool:
    """True when binding *directory* would expose a hidden root (it is one, or above one)."""
    return str(directory) == "/" or any(Path(h) == directory or directory in Path(h).parents for h in hidden)


def _under_hidden(directory: Path, hidden: list[str]) -> bool:
    return any(Path(h) in directory.parents for h in hidden)


def _is_install_prefix(directory: Path) -> bool:
    """A specific install prefix (a venv, or a Python installation), not a catch-all like
    ``~/.local`` or ``~/.cargo``: only these may be bound from under the home."""
    if (directory / "pyvenv.cfg").is_file():
        return True
    return any(directory.glob("lib/python3*/os.py"))


def runtime_dirs(binary: str) -> tuple[Path, ...]:
    """What a server binary needs to see to run, as an allowlist: its own directory, its
    install prefix and, for a script, its interpreter's directory and prefix (a venv and
    the Python it was made from). Never ``/``, never a directory holding the home or the
    data root, and under those only the exact binary directory or a real install prefix
    (a venv or a Python), never ``~/.local`` or ``~/.cargo`` wholesale."""
    hidden = _hidden_roots()
    candidates: list[tuple[Path, bool]] = []   # (dir, exact: the binary's own directory)
    try:
        path = Path(binary)
        real = path.resolve()
        candidates += [(path.parent.resolve(), True), (real.parent, True)]
        if real.parent.name == "bin":
            candidates.append((real.parent.parent, False))
        with real.open("rb") as handle:
            head = handle.read(256)
        if head.startswith(b"#!"):
            parts = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").split()
            interp = parts[0] if parts else ""
            if interp.endswith("/env") and len(parts) > 1:
                interp = shutil.which(parts[1]) or ""
            if interp:
                ip = Path(interp)
                for one in dict.fromkeys((ip, ip.resolve())):
                    candidates += [(one.parent.resolve(), True), (one.parent.parent.resolve(), False)]
                cfg = ip.parent.parent / "pyvenv.cfg"
                if cfg.is_file():
                    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                        key, _, value = line.partition("=")
                        if key.strip() == "home" and value.strip():
                            base = Path(value.strip()).resolve()
                            candidates += [(base, True), (base.parent, False)]
    except (OSError, ValueError, RuntimeError):
        pass
    found: list[Path] = []
    for directory, exact in candidates:
        if _contains_hidden(directory, hidden):
            continue
        if _under_hidden(directory, hidden) and not exact and not _is_install_prefix(directory):
            continue
        found.append(directory)
    return tuple(dict.fromkeys(found))


def _system_mounts() -> list[str]:
    cmd: list[str] = []
    for name in SYSTEM_DIRS:
        if os.path.islink(name):
            cmd += ["--symlink", os.readlink(name), name]
        elif os.path.isdir(name):
            cmd += ["--ro-bind", name, name]
    for name in ETC_ENTRIES:
        full = os.path.join("/etc", name)
        if os.path.islink(full):
            cmd += ["--symlink", os.readlink(full), full]
        elif os.path.exists(full):
            cmd += ["--ro-bind", full, full]
    return cmd


def require_sandbox() -> bool:
    """Default ON: without a working bwrap no server (and no install) runs, unless the owner
    explicitly sets ``JARVIS_LSP_REQUIRE_SANDBOX=0``."""
    return env_flag(REQUIRE_SANDBOX_ENV, True)


def wrap(argv: list[str], *, root: Path, state_dir: Path, read_only: tuple[Path, ...] = (),
         network: bool = False) -> tuple[list[str], str]:
    """The argv that starts *argv* confined, and the isolation it got.

    The sandbox is an allowlist: a fresh ``/proc``, ``/dev`` and ``/tmp``; the system
    directories and a few ``/etc`` entries read-only; the server's runtime
    (:func:`runtime_dirs`) and *read_only* read-only; *root* read-only (read-write for an
    install, whose root is its own target); *state_dir* read-write. Nothing else of the
    host exists inside, so the home and the data root are absent rather than covered."""
    bwrap = _bwrap()
    if not bwrap:
        if require_sandbox():
            raise ConfinementRefused("sandbox_unavailable")
        return list(argv), isolation()
    hidden = _hidden_roots()
    root_path = root.resolve()
    if _contains_hidden(root_path, hidden):
        raise ConfinementRefused("workspace_contains_private_dir")
    cmd = [bwrap, "--die-with-parent", "--new-session", "--unshare-all"]
    if network:
        cmd.append("--share-net")
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]  # nosec B108 — sandbox mount targets
    cmd += _system_mounts()
    binds: list[str] = []
    for directory in (*runtime_dirs(argv[0]), *read_only):
        resolved = Path(directory).resolve()
        if _contains_hidden(resolved, hidden) or not resolved.exists():
            continue
        text = str(resolved)
        if text not in binds:
            binds.append(text)
            cmd += ["--ro-bind", text, text]
    root_text = str(root_path)
    state_text = str(state_dir.resolve())
    cmd += ["--bind" if network else "--ro-bind", root_text, root_text]
    cmd += ["--bind", state_text, state_text, "--chdir", state_text, "--", *argv]
    return cmd, "bwrap"


def preexec(memory: int | None = None) -> Callable[[], None] | None:
    """A ``preexec_fn`` applying the limits (POSIX), or None."""
    if os.name != "posix":
        return None
    data_bytes = (memory or memory_mb()) * 1024 * 1024

    def apply() -> None:
        import resource

        def cap(which: int, value: int) -> None:
            try:
                soft, hard = resource.getrlimit(which)
                ceiling = value if hard == resource.RLIM_INFINITY else min(hard, value)
                resource.setrlimit(which, (ceiling, ceiling))
            except (OSError, ValueError):
                pass   # a platform without the limit keeps the others

        cap(resource.RLIMIT_DATA, data_bytes)
        cap(resource.RLIMIT_CPU, CPU_SECONDS)
        cap(resource.RLIMIT_FSIZE, FILE_SIZE_BYTES)
        cap(resource.RLIMIT_NOFILE, OPEN_FILES)
        cap(resource.RLIMIT_CORE, 0)

    return apply


__all__ = ["ConfinementRefused", "child_env", "isolation", "memory_mb", "preexec", "require_sandbox", "runtime_dirs",
           "wrap"]
