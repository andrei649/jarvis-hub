"""Read-only external secret source contract.

Adapted from Hermes agent/secret_sources/base.py at 59b2aeef6c7a (MIT).
Nerva resolves at an approved broker action, without modifying os.environ.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    BINARY_MISSING = "binary_missing"
    AUTH_FAILED = "auth_failed"
    REF_INVALID = "ref_invalid"
    NETWORK = "network"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


@dataclass
class FetchResult:
    secrets: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: ErrorKind | None = None


ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def valid_env_name(name: str) -> bool:
    return isinstance(name, str) and bool(ENV_NAME.fullmatch(name))


def run_helper(runner: Runner, argv: list[str], *, credential: str,
               credential_name: str, timeout: float = 10, extra_env: dict[str, str] | None = None):
    """Single noninteractive helper call with no unrelated process credentials."""
    import os

    allowed = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TEMP", "LANG",
               "LC_ALL", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "OP_CONFIG_DIR")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env[credential_name] = credential
    env["NO_COLOR"] = "1"
    if credential_name.startswith("OP_"):
        env["OP_BIOMETRIC_UNLOCK_ENABLED"] = "false"
        env["OP_CACHE"] = "false"
    if extra_env:
        env.update(extra_env)
    return runner(argv, env=env, capture_output=True, text=True, encoding="utf-8",
                  errors="replace", timeout=min(max(float(timeout), 0.1), 30.0),
                  stdin=subprocess.DEVNULL)


def executable(path: str, name: str) -> str | None:
    import os
    import shutil

    candidate = path or shutil.which(name)
    if not candidate and name == "bws":
        from .install import installed_bws_path
        candidate = str(installed_bws_path())
    return candidate if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK) else None
