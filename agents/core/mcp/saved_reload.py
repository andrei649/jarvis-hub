"""Inert, bounded parsing of saved MCP rows for owner-confirmed reconciliation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class SavedReloadRefused(ValueError):
    """A saved list cannot be reconciled without guessing its meaning."""


@dataclass(frozen=True)
class SavedReloadPlan:
    fingerprint: str
    summary: dict[str, int]
    _manager: object = field(repr=False, compare=False)
    _candidates: dict[str, object] = field(repr=False, compare=False)
    _state: tuple = field(repr=False, compare=False)


_FIELDS = frozenset({
    "name", "transport", "command", "url", "cwd", "trust", "tools_allow",
    "tools_deny", "sampling", "elicitation", "auth", "env", "secret_env",
    "secret_headers", "oauth", "origin", "headers",
})


def candidates(configs: object) -> tuple[dict[str, object], bytes]:
    """Validate the entire effective list before creating any live server."""
    from .client import MCPManager, normalize_trust, tool_patterns_over_bounds
    from .http_transport import normalize_transport, validate_mcp_url

    if type(configs) is not list or len(configs) > 128:
        raise SavedReloadRefused("saved_config_invalid")
    try:
        encoded = json.dumps(configs, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode()
        if len(encoded) > 256_000:
            raise SavedReloadRefused("saved_config_invalid")
        rows = json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SavedReloadRefused("saved_config_invalid") from exc
    from .catalog import NAME_RE

    result = {}
    for row in rows:
        if type(row) is not dict or set(row) - _FIELDS:
            raise SavedReloadRefused("saved_config_invalid")
        name = row.get("name")
        if type(name) is not str or not NAME_RE.fullmatch(name) or name in result:
            raise SavedReloadRefused("saved_config_invalid")
        transport = normalize_transport(row.get("transport", "stdio"))
        if transport not in {"stdio", "streamable-http"}:
            raise SavedReloadRefused("saved_config_invalid")
        for key in ("command", "url", "cwd"):
            if row.get(key) is not None and (type(row[key]) is not str
                                             or len(row[key]) > 4096):
                raise SavedReloadRefused("saved_config_invalid")
        if transport == "streamable-http" and validate_mcp_url(row.get("url")):
            raise SavedReloadRefused("saved_config_invalid")
        if transport == "stdio" and not row.get("command"):
            raise SavedReloadRefused("saved_config_invalid")
        for key in ("tools_allow", "tools_deny"):
            value = row.get(key)
            if value is not None and (type(value) is not list
                                      or any(type(p) is not str or not p.strip() for p in value)
                                      or tool_patterns_over_bounds(value)):
                raise SavedReloadRefused("saved_config_invalid")
        trust = normalize_trust(row.get("trust"))
        if trust is None:
            if row.get("trust") is not None:
                raise SavedReloadRefused("saved_config_invalid")
            trust = "full"  # historical saved entries without a tier retain boot semantics
        if row.get("auth", "none") not in ("none", "oauth", "api_key"):
            raise SavedReloadRefused("saved_config_invalid")
        if row.get("sampling") is not None and type(row["sampling"]) not in (str, dict):
            raise SavedReloadRefused("saved_config_invalid")
        if row.get("elicitation") is not None and type(row["elicitation"]) not in (bool, dict):
            raise SavedReloadRefused("saved_config_invalid")
        for key in ("env", "secret_headers", "oauth", "origin", "headers"):
            value = row.get(key)
            if value is None:
                continue
            if type(value) is not dict or len(value) > 128 or any(
                type(k) is not str or len(k) > 256 or
                not (type(v) is str or (key == "origin" and type(v) in (int, type(None)))) or
                (type(v) is str and len(v) > 4096)
                for k, v in value.items()
            ):
                raise SavedReloadRefused("saved_config_invalid")
        if row.get("env") and not row.get("origin"):
            raise SavedReloadRefused("saved_config_invalid")
        if row.get("secret_env") is not None and (type(row["secret_env"]) is not list
                                                   or any(type(n) is not str for n in row["secret_env"])):
            raise SavedReloadRefused("saved_config_invalid")
        if row.get("secret_env") and len(row["secret_env"]) > 128:
            raise SavedReloadRefused("saved_config_invalid")
        parser = MCPManager()
        parser.load_from_config([{**row, "trust": trust}])
        server = parser.servers.get(name)
        if server is None:
            raise SavedReloadRefused("saved_config_invalid")
        if transport == "stdio" and server._command_argv() is None:
            raise SavedReloadRefused("saved_config_invalid")
        result[name] = server
    return result, encoded


def config_digest(row: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()
