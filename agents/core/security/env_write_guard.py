"""Shared dangerous & security-policy environment variable denylist and `.env` write guard (H499).

Unifies the environment variable denylist across:
1. Child/interpreter execution (`agents/core/code_env.py` — H595)
2. Persistent `.env` write boundaries (`agents/cli/env_cmd.py` — `nerva env set|unset`,
   and any future HUD or installer `.env` writer).

Blocked categories at the persistence boundary:
- ``control_or_loader``: dynamic linker, interpreter startup, shell RC/IFS, PATH/HOME,
  TLS CA bundle overrides, and internal ToolRPC/gateway control channels
  (:data:`SHARED_CONTROL_ENV_NAMES` and :data:`SHARED_CONTROL_ENV_PREFIXES`).
- ``security_policy``: Action Kernel, safe mode, strict-local routing, bind/CSP/log-redaction
  floors, host/SSH terminal gates, smart-approval policy, plugin grants, managed-mode pins,
  and hub authentication/signing tokens (:data:`SECURITY_POLICY_ENV_NAMES`).
- ``process_only_location``: data/install root selectors (:data:`FROM_PROCESS_ONLY`) that
  ``env_provenance`` refuses to load from `.env` files to prevent split-root state.
- ``administrator_managed``: keys pinned by an administrator's ``managed_scope`` layer.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}\Z")

#: Code-loading, shell/interpreter hijack, TLS trust override, and host identity names.
#: Shared between ``code_env.py`` and the `.env` persistence write guard.
SHARED_CONTROL_ENV_NAMES: frozenset[str] = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMP", "TEMP", "TMPDIR",
    "TZ", "LANG", "IFS", "ZDOTDIR", "ENV", "BASH_ENV", "PROMPT_COMMAND",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "NODE_OPTIONS", "RUBYOPT", "PERL5OPT", "JAVA_TOOL_OPTIONS", "ELECTRON_RUN_AS_NODE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "VIRTUAL_ENV", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH",
    "_NERVA_ENV_PREFERRED", "_NERVA_ENV_PREFERRED_PID",
})

#: Prefixes that load code, alter runtime locale/paths, or carry private RPC authority.
SHARED_CONTROL_ENV_PREFIXES: tuple[str, ...] = (
    "PYTHON",
    "LD_",
    "DYLD_",
    "GIT_CONFIG",
    "JARVIS_RPC_",
    "HERMES_RPC_",
    "JARVIS_TOOL_RPC_",
    "HERMES_TOOL_RPC_",
    "NERVA_RPC_",
    "NERVA_TOOL_RPC_",
    "GATEWAY_RELAY_",
    "CODEX_",
    "LC_",
    "XDG_",
    "CONDA_",
)

#: Canonical security-policy, privilege, and root-location stems (refused under both
#: ``JARVIS_<STEM>`` and ``NERVA_<STEM>`` spellings, plus standalone ``DEV_MODE``).
_SECURITY_POLICY_STEMS: tuple[str, ...] = (
    "ACTION_KERNEL",
    "SAFE_MODE",
    "STRICT_LOCAL",
    "ALLOW_INSECURE_BIND",
    "DISABLE_CSP",
    "CSP",
    "CORS_ORIGINS",
    "TRUSTED_PROXIES",
    "TRUSTED_PROXY",
    "LOG_REDACTION",
    "TERMINAL_TARGETS",
    "TERMINAL_LOCAL_HOST",
    "TERMINAL_SSH_HOST",
    "TERMINAL_SSH_HOSTS",
    "TERMINAL_SSH_KNOWN_HOSTS",
    "SMART_APPROVALS",
    "SMART_APPROVAL_POLICY",
    "SMART_APPROVAL_DENY",
    "PLUGIN_GRANTS",
    "MANAGED",
    "MANAGED_DIR",
    "APP_ROOT",
    "HOME",
    "MEMORY_DIR",
    "USER_HOME",
    "PROFILE",
    "KEY_DIR",
    "ADMIN_TOKEN",
    "USER_TOKEN",
    "SECRET_KEY",
    "AUDIT_KEY",
    "BACKUP_KEY",
    "DEV_MODE",
)

SECURITY_POLICY_ENV_NAMES: frozenset[str] = frozenset({
    "DEV_MODE",
    "HERMES_DASHBOARD_SESSION_TOKEN",
    "NERVA_WORKSPACE_SETUP_CODE",
    "NERVA_WORKSPACE_JOB_NONCE",
    "NERVA_WS_SESSION",
    "NERVA_WS_ADMIN_SESSION",
    *(f"JARVIS_{stem}" for stem in _SECURITY_POLICY_STEMS),
    *(f"NERVA_{stem}" for stem in _SECURITY_POLICY_STEMS),
})

#: Complete exact-name persistence denylist.
PERSISTENCE_ENV_DENYLIST: frozenset[str] = SHARED_CONTROL_ENV_NAMES | SECURITY_POLICY_ENV_NAMES


class EnvWriteRefusedError(ValueError):
    """Raised when a persistent `.env` write targets a denylisted or invalid variable."""

    def __init__(self, variable: str, reason: str, *, category: str = "blocked") -> None:
        self.variable = str(variable)
        self.reason = str(reason)
        self.category = str(category)
        super().__init__(f"Refusing persistent .env write for {self.variable}: {self.reason} [{self.category}]")


def check_env_persistence_allowed(name: object) -> tuple[bool, str | None, str | None]:
    """Return ``(allowed, category, reason)`` for writing *name* into a `.env` file."""
    if not isinstance(name, str) or not name.strip():
        return False, "invalid_name", "variable name must be a non-empty string"
    cleaned = name.strip()
    if not _ENV_NAME_RE.match(cleaned):
        return (
            False,
            "invalid_name",
            "variable name must match [A-Z_][A-Z0-9_]{0,127} (uppercase ASCII letters, digits, '_')",
        )
    upper = cleaned.upper()
    if upper in SHARED_CONTROL_ENV_NAMES:
        return (
            False,
            "control_or_loader",
            f"{upper} controls process execution, shell startup, paths, or TLS trust",
        )
    for prefix in SHARED_CONTROL_ENV_PREFIXES:
        if upper.startswith(prefix):
            return (
                False,
                "control_or_loader",
                f"{upper} matches protected execution/RPC prefix {prefix}*",
            )
    if upper in SECURITY_POLICY_ENV_NAMES:
        return (
            False,
            "security_policy",
            f"{upper} is a security-policy, authentication, or root-boundary variable",
        )
    try:
        from ..env_provenance import FROM_PROCESS_ONLY
        from ..env_config import other_spelling

        alt = other_spelling(upper)
        if upper in FROM_PROCESS_ONLY or (alt and alt in FROM_PROCESS_ONLY):
            return (
                False,
                "process_only_location",
                f"{upper} must be set in the process environment before startup",
            )
    except Exception:
        pass
    try:
        from .. import managed_scope

        pinned_fn = getattr(managed_scope, "env_names", None)
        if callable(pinned_fn):
            pinned = pinned_fn()
            if upper in pinned:
                return (
                    False,
                    "administrator_managed",
                    f"{upper} is pinned by administrator managed configuration",
                )
    except Exception:
        pass
    return True, None, None


def denylist_manifest() -> dict[str, Any]:
    """Structured snapshot of the shared persistence-boundary environment denylist."""
    return {
        "control_or_loader_names": sorted(SHARED_CONTROL_ENV_NAMES),
        "control_or_loader_prefixes": list(SHARED_CONTROL_ENV_PREFIXES),
        "security_policy_names": sorted(SECURITY_POLICY_ENV_NAMES),
        "total_exact_names": len(PERSISTENCE_ENV_DENYLIST),
    }


def _format_dotenv_value(value: str) -> str:
    """Format *value* as a safe single-line `.env` literal without `$VAR` expansion."""
    if not isinstance(value, str):
        raise ValueError("environment value must be a string")
    if "\x00" in value:
        raise ValueError("environment value cannot contain NUL bytes")
    if "\r" in value or "\n" in value:
        raise ValueError("environment value cannot contain raw newline characters")
    if value == "":
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_./:@+-]+", value):
        return value
    if "'" not in value:
        return f"'{value}'"
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


_LINE_KEY_RE = re.compile(r"^\s*(?:export\s+)?(?:'([A-Za-z_][A-Za-z0-9_]*)'|([A-Za-z_][A-Za-z0-9_]*))\s*=")


def _extract_line_key(line: str) -> str | None:
    match = _LINE_KEY_RE.match(line)
    if not match:
        return None
    return match.group(1) or match.group(2)


def read_dotenv_summary(env_path: Path) -> list[dict[str, Any]]:
    """List keys defined in *env_path* with secret-mask metadata, never returning secret values."""
    from ..env_provenance import masked

    target = Path(env_path).expanduser()
    if not target.is_file() or target.is_symlink():
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        key = _extract_line_key(line)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    rows: list[dict[str, Any]] = []
    for key in keys:
        allowed, category, _ = check_env_persistence_allowed(key)
        rows.append({
            "name": key,
            "masked": masked(key),
            "protected_by_denylist": not allowed,
            "denylist_category": category,
        })
    return rows


def _atomic_write_dotenv(target: Path, lines: list[str]) -> None:
    if target.exists() and target.is_symlink():
        raise ValueError(f"refusing to write .env through symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = ("\n".join(lines).rstrip("\n") + "\n") if lines else ""
    fd, tmp_name = tempfile.mkstemp(prefix=".nerva-env-", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_dotenv_var(env_path: Path, name: str, value: str) -> dict[str, Any]:
    """Persist ``NAME=VALUE`` to *env_path* (`0o600`), refusing any denylisted variable first."""
    cleaned_name = str(name or "").strip()
    allowed, category, reason = check_env_persistence_allowed(cleaned_name)
    if not allowed:
        raise EnvWriteRefusedError(cleaned_name or "<empty>", reason or "blocked variable", category=category or "blocked")
    rendered_val = _format_dotenv_value(value)
    target = Path(env_path).expanduser()
    if target.exists() and target.is_symlink():
        raise ValueError(f"refusing to write .env through symlink: {target}")

    existing_lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    new_binding = f"{cleaned_name}={rendered_val}"
    updated = False
    out_lines: list[str] = []
    for line in existing_lines:
        if _extract_line_key(line) == cleaned_name:
            if not updated:
                out_lines.append(new_binding)
                updated = True
        else:
            out_lines.append(line)
    if not updated:
        out_lines.append(new_binding)

    _atomic_write_dotenv(target, out_lines)
    return {
        "ok": True,
        "name": cleaned_name,
        "path": str(target),
        "action": "updated" if updated else "added",
    }


def unset_dotenv_var(env_path: Path, name: str) -> dict[str, Any]:
    """Remove ``NAME`` from *env_path*, refusing denylisted security-policy variables."""
    cleaned_name = str(name or "").strip()
    allowed, category, reason = check_env_persistence_allowed(cleaned_name)
    if not allowed:
        raise EnvWriteRefusedError(cleaned_name or "<empty>", reason or "blocked variable", category=category or "blocked")
    target = Path(env_path).expanduser()
    if not target.is_file():
        return {"ok": True, "name": cleaned_name, "path": str(target), "removed": False}
    if target.is_symlink():
        raise ValueError(f"refusing to modify symlink .env: {target}")

    existing_lines = target.read_text(encoding="utf-8").splitlines()
    kept_lines = [line for line in existing_lines if _extract_line_key(line) != cleaned_name]
    removed = len(kept_lines) != len(existing_lines)
    if removed:
        _atomic_write_dotenv(target, kept_lines)
    return {
        "ok": True,
        "name": cleaned_name,
        "path": str(target),
        "removed": removed,
    }


def resolve_default_dotenv_target(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the active profile `.env`, user-home `.env`, or repo `.env` for CLI writes."""
    from ..paths import app_root, data_root, profile_name, user_home

    if profile_name(environ):
        return data_root(environ) / ".env"
    u_home = user_home(environ)
    if u_home is not None:
        return u_home / ".env"
    return app_root() / ".env"


__all__ = [
    "EnvWriteRefusedError",
    "PERSISTENCE_ENV_DENYLIST",
    "SECURITY_POLICY_ENV_NAMES",
    "SHARED_CONTROL_ENV_NAMES",
    "SHARED_CONTROL_ENV_PREFIXES",
    "check_env_persistence_allowed",
    "denylist_manifest",
    "read_dotenv_summary",
    "resolve_default_dotenv_target",
    "unset_dotenv_var",
    "write_dotenv_var",
]
