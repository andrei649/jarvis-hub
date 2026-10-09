"""Bitwarden Secrets Manager bws adapter.

Adapted from Hermes agent/secret_sources/bitwarden.py at 59b2aeef6c7a (MIT).
No implicit installer or plaintext disk cache is used by Nerva.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - bws uses a fixed argv list through run_helper, never a shell

from .base import ErrorKind, FetchResult, Runner, executable, run_helper, valid_env_name


def fetch(cfg: dict, token: str, runner: Runner = subprocess.run) -> FetchResult:
    result = FetchResult()
    if not token or not cfg.get("project_id"):
        result.error, result.error_kind = "Bitwarden token or project is missing", ErrorKind.NOT_CONFIGURED
        return result
    binary = executable(str(cfg.get("binary_path") or ""), "bws")
    if binary is None:
        result.error, result.error_kind = "bws is not installed", ErrorKind.BINARY_MISSING
        return result
    argv = [binary, "secret", "list", str(cfg["project_id"]), "--output", "json"]
    extra = {"BWS_SERVER_URL": str(cfg["server_url"])} if cfg.get("server_url") else None
    try:
        proc = run_helper(runner, argv, credential=token, credential_name="BWS_ACCESS_TOKEN",
                          timeout=cfg.get("timeout_seconds", 10), extra_env=extra)
        if proc.returncode:
            detail = (proc.stderr or "").lower()
            if any(token in detail for token in ("unauthorized", "invalid token", "access token", "401",
                                                 "403", "invalid_client", "invalid_grant", "400 bad request")):
                result.error_kind = ErrorKind.AUTH_FAILED
            elif any(token in detail for token in ("network", "connection", "resolve", "download", "dns")):
                result.error_kind = ErrorKind.NETWORK
            else:
                result.error_kind = ErrorKind.INTERNAL
            result.error = "Bitwarden fetch failed"
            return result
        payload = json.loads(proc.stdout or "[]")
        if not isinstance(payload, list):
            raise ValueError("unexpected payload")
        for item in payload:
            if not isinstance(item, dict):
                continue
            name, value = item.get("key"), item.get("value")
            if valid_env_name(name) and isinstance(value, str) and value:
                result.secrets[name] = value
            elif name is not None:
                result.warnings.append("Bitwarden item skipped: invalid name or empty value")
    except subprocess.TimeoutExpired:
        result.error, result.error_kind = "Bitwarden fetch timed out", ErrorKind.TIMEOUT
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result.error, result.error_kind = "Bitwarden fetch failed", ErrorKind.INTERNAL
    return result
