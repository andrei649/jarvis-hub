"""Pure execution-environment contracts for governed sandbox/tool RPC work.

This package intentionally does not execute code. It describes supported
environment backends and provides shared helpers that later transports can use
without importing the runtime-heavy sandbox or Tool-RPC modules.
"""

from __future__ import annotations

import platform
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

SAFE_ENV_PREFIXES = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SHELL",
    "LOGNAME",
    "XDG_",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA",
)

SECRET_ENV_SUBSTRINGS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PASSWD",
    "AUTH",
    "DSN",
    "WEBHOOK",
)

JARVIS_CHILD_ALLOWED_ENV = frozenset({
    "JARVIS_HOME",
    "JARVIS_PROFILE",
    "JARVIS_ENV",
})

WINDOWS_ESSENTIAL_ENV_VARS = frozenset({
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "PUBLIC",
    "ALLUSERSPROFILE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "USERDOMAIN",
    "USERNAME",
    "HOMEDRIVE",
    "HOMEPATH",
    "COMPUTERNAME",
})

_SESSION_TOKEN_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class EnvironmentProfile:
    """Static capability description for an execution backend."""

    name: str
    isolated: bool
    remote: bool
    supports_file_rpc: bool
    supports_shell: bool = True
    supports_python: bool = True
    default_timeout_seconds: int = 300
    max_tool_calls: int = 50
    max_stdout_bytes: int = 50_000
    max_stderr_bytes: int = 10_000


@dataclass(frozen=True)
class CwdExtraction:
    """Result of removing CWD markers from backend command output."""

    output: str
    cwd: str | None


def backend_profiles() -> tuple[EnvironmentProfile, ...]:
    """Return the narrow backend set Jarvis should support for execute_code.

    Local is not isolated and should remain opt-in behind existing sandbox
    policy. Docker is the isolated local backend. SSH is remote and file-RPC
    capable, but its safety depends on the target host.
    """

    return (
        EnvironmentProfile(
            name="local",
            isolated=False,
            remote=False,
            supports_file_rpc=False,
        ),
        EnvironmentProfile(
            name="docker",
            isolated=True,
            remote=False,
            supports_file_rpc=True,
        ),
        EnvironmentProfile(
            name="ssh",
            isolated=False,
            remote=True,
            supports_file_rpc=True,
        ),
    )


def build_cwd_marker(session_id: str) -> str:
    """Build a deterministic marker used to persist backend working directory."""

    token = _SESSION_TOKEN_RE.sub("_", str(session_id or "").strip()).strip("_")
    return f"__JARVIS_CWD_{token or 'session'}__"


def extract_cwd_marker(output: str, session_id: str) -> CwdExtraction:
    """Strip complete CWD marker lines and return the last emitted CWD."""

    marker = build_cwd_marker(session_id)
    cwd: str | None = None
    clean_lines: list[str] = []

    for line in str(output or "").splitlines(keepends=True):
        first = line.find(marker)
        if first == -1:
            clean_lines.append(line)
            continue

        second = line.find(marker, first + len(marker))
        if second == -1:
            clean_lines.append(line)
            continue

        candidate = line[first + len(marker):second].strip()
        if candidate:
            cwd = candidate

        stripped = line.strip()
        if stripped.startswith(marker) and stripped.endswith(marker):
            continue
        clean_lines.append(line[:first] + line[second + len(marker):])

    return CwdExtraction(output="".join(clean_lines), cwd=cwd)


def scrub_child_env(
    source_env: Mapping[str, object],
    *,
    passthrough: Callable[[str], bool] | None = None,
    is_windows: bool | None = None,
) -> dict[str, str]:
    """Return a child-process environment with credentials removed.

    Passthrough is an explicit opt-in hook for skill/config-owned variables.
    It runs before secret-name filtering. Otherwise, secret-looking names are
    dropped, known safe OS/runtime names pass, and only a tiny Jarvis runtime
    allowlist is preserved.
    """

    allow_passthrough = passthrough or (lambda _key: False)
    windows = platform.system() == "Windows" if is_windows is None else is_windows
    scrubbed: dict[str, str] = {}
    safe_prefixes = tuple(prefix.upper() for prefix in SAFE_ENV_PREFIXES)

    for key, value in dict(source_env or {}).items():
        name = str(key)
        upper = name.upper()
        text = str(value)

        if allow_passthrough(name):
            scrubbed[name] = text
            continue
        if any(secret in upper for secret in SECRET_ENV_SUBSTRINGS):
            continue
        if upper.startswith(safe_prefixes):
            scrubbed[name] = text
            continue
        if upper in JARVIS_CHILD_ALLOWED_ENV:
            scrubbed[name] = text
            continue
        if windows and upper in WINDOWS_ESSENTIAL_ENV_VARS:
            scrubbed[name] = text

    return scrubbed


def prepare_python_child_env(
    source_env: Mapping[str, object],
    *,
    passthrough: Callable[[str], bool] | None = None,
    is_windows: bool | None = None,
) -> dict[str, str]:
    """Scrub a child env and force UTF-8 Python I/O for sandbox scripts."""

    child_env = scrub_child_env(
        source_env,
        passthrough=passthrough,
        is_windows=is_windows,
    )
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    return child_env
