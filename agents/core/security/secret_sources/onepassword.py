"""1Password op:// mapped reference adapter.

Adapted from Hermes agent/secret_sources/onepassword.py at 59b2aeef6c7a (MIT).
"""

from __future__ import annotations

import subprocess
import time

from .base import ErrorKind, FetchResult, Runner, executable, run_helper, valid_env_name


def valid_reference(value: str) -> bool:
    return isinstance(value, str) and value.strip().startswith("op://") and len(value.strip().split("/")) >= 5


def fetch(cfg: dict, token: str, runner: Runner = subprocess.run, *, session: bool = False) -> FetchResult:
    result = FetchResult()
    refs = cfg.get("env")
    if not isinstance(refs, dict) or not refs:
        result.error, result.error_kind = "1Password references are missing", ErrorKind.NOT_CONFIGURED
        return result
    if not token:
        result.error, result.error_kind = "1Password owner session or token is missing", ErrorKind.NOT_CONFIGURED
        return result
    binary = executable(str(cfg.get("binary_path") or ""), "op")
    if binary is None:
        result.error, result.error_kind = "op is not installed", ErrorKind.BINARY_MISSING
        return result
    try:
        budget = min(max(float(cfg.get("timeout_seconds", 10)), 0.1), 30.0)
    except (TypeError, ValueError):
        budget = 10.0
    deadline = time.monotonic() + budget
    for name in sorted(refs):
        ref = refs[name]
        if not valid_env_name(name) or not valid_reference(ref):
            result.warnings.append("1Password reference skipped: invalid name or URI")
            continue
        argv = [binary, "read"]
        if cfg.get("account"):
            argv.extend(("--account", str(cfg["account"])))
        argv.extend(("--", ref.strip()))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result.error, result.error_kind = "1Password fetch timed out", ErrorKind.TIMEOUT
            result.secrets.clear()
            return result
        try:
            key = "OP_SESSION" if session else "OP_SERVICE_ACCOUNT_TOKEN"
            proc = run_helper(runner, argv, credential=token, credential_name=key,
                              timeout=remaining)
            if proc.returncode:
                message = (proc.stderr or "").lower()
                if any(marker in message for marker in ("unauthorized", "not signed in", "session expired",
                                                          "authentication", "invalid token", "401", "403")):
                    result.error = "1Password authentication failed"
                    result.error_kind = ErrorKind.AUTH_FAILED
                    result.secrets.clear()
                    return result
                result.warnings.append(f"1Password read failed for {name}")
                continue
            value = (proc.stdout or "").rstrip("\r\n")
            if value.strip():
                result.secrets[name] = value
            else:
                result.warnings.append(f"1Password returned empty value for {name}")
        except subprocess.TimeoutExpired:
            result.warnings.append(f"1Password read timed out for {name}")
        except (OSError, TypeError, ValueError):
            result.warnings.append(f"1Password read failed for {name}")
    return result
