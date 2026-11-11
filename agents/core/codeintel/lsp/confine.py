"""confine.py — how a language server (third-party code) is started.

A language server is a long-lived child, so the one-shot :mod:`agents.core.sandbox`
runner does not fit it. This module builds the same posture for it:

* **Scrubbed environment** — :func:`agents.core.environments.scrub_child_env` (no
  secret-looking names), ``HOME``/``XDG_*``/``TMPDIR`` pointed at a per-server state
  directory, and every toolchain told not to fetch (``GOPROXY=off``,
  ``GOTOOLCHAIN=local``, ``npm_config_offline``).
* **Filesystem and network isolation** where ``bwrap`` (bubblewrap) works: every
  namespace unshared (no network at all), the system read-only, a fresh ``/tmp``,
  the owner's home and Nerva's data root hidden behind empty tmpfs mounts, then only
  the workspace (read-only), the installed tools (read-only) and the server's own
  state directory (read-write) bound back. The server cannot write the workspace.
* **Resource limits** on POSIX: data segment (``RLIMIT_DATA``, which V8's large
  virtual reservations do not trip as ``RLIMIT_AS`` would), cumulative CPU seconds,
  file size, open files, no core dumps; its own session so the whole group dies on
  stop. Idle servers are killed by the manager.

When ``bwrap`` is missing or cannot create namespaces, the server runs with the
environment and the limits only, and :func:`isolation` says so (``rlimits``);
``JARVIS_LSP_REQUIRE_SANDBOX`` turns that into a refusal to start.
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
    path = [str(p) for p in extra_path] + [p for p in env.get("PATH", os.defpath).split(os.pathsep) if p]
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


def runtime_dirs(binary: str) -> tuple[Path, ...]:
    """What a binary found outside the system dirs needs to see to run: its directory,
    its real install prefix and, for a script, its interpreter's environment (a uv or
    pip tool's venv and the Python it was made from). Bound read-only."""
    found: list[Path] = []
    try:
        path = Path(binary)
        real = path.resolve()
        found += [path.parent, real.parent]
        if real.parent.name == "bin":
            found.append(real.parent.parent)
        with real.open("rb") as handle:
            head = handle.read(256)
        if head.startswith(b"#!"):
            parts = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").split()
            interp = parts[0] if parts else ""
            if interp.endswith("/env") and len(parts) > 1:
                interp = shutil.which(parts[1]) or ""
            if interp:
                ip = Path(interp)
                found += [ip.parent.parent, ip.resolve().parent.parent]
    except (OSError, ValueError, RuntimeError):
        pass
    return tuple(dict.fromkeys(found))


def wrap(argv: list[str], *, root: Path, state_dir: Path, read_only: tuple[Path, ...] = (),
         network: bool = False) -> tuple[list[str], str]:
    """The argv that starts *argv* confined, and the isolation it got."""
    bwrap = _bwrap()
    if not bwrap:
        if env_flag(REQUIRE_SANDBOX_ENV):
            raise ConfinementRefused("sandbox_unavailable")
        return list(argv), isolation()
    cmd = [bwrap, "--die-with-parent", "--new-session", "--unshare-all"]
    if network:
        cmd.append("--share-net")
    cmd += ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]  # nosec B108
    for hidden in _hidden_roots():
        cmd += ["--tmpfs", hidden]
    for directory in (*read_only, *runtime_dirs(argv[0])):
        text = str(Path(directory).resolve())
        if os.path.exists(text):
            cmd += ["--ro-bind", text, text]
    root_text = str(root.resolve())
    state_text = str(state_dir.resolve())
    if network:   # an install writes into its target and nowhere else
        cmd += ["--bind", root_text, root_text]
    else:
        cmd += ["--ro-bind", root_text, root_text]
    cmd += ["--bind", state_text, state_text, "--chdir", root_text, "--", *argv]
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


__all__ = ["ConfinementRefused", "child_env", "isolation", "memory_mb", "preexec", "runtime_dirs", "wrap"]
