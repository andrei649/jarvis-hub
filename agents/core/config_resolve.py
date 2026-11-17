"""H248 — one effective-value view over Nerva's configuration planes, with provenance.

Nerva's configuration lives in several planes that each already know their own
precedence: the declared defaults and the settings store (``settings_db``), ``${env:…}``
references inside a stored value (H255), the selected product posture's forced values,
the administrator's managed pins (G1), the environment (process, repo ``.env``, data-home
``.env``, managed ``.env``; ``env_provenance``) and the agent registry (``agents.yaml``
under the owner's roster, H202). :func:`explain` answers, for one name, *what value is in
effect and which plane supplied it*, listing every plane that has a say in order, the
one in effect marked. It reads; it never writes, and it never returns a secret's value
(a credential setting is masked, an environment variable is reported set/unset only).

Names: ``category.key`` (a setting), ``NERVA_X`` / ``JARVIS_X`` or any name the
environment registry declares (an environment variable), ``agents.<id>.<field>`` (the
agent registry).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MASK = "••••••"
AGENT_FIELDS = ("model", "status", "tier", "llm_policy", "channel", "approved_models", "plugins", "name")


def _masked(value: Any, secret: bool) -> Any:
    return MASK if secret and value not in (None, "", [], {}) else value


def _stored_raw(category: str, key: str) -> tuple[bool, Any]:
    """``(found, stored value)`` read straight from the store, before any overlay; a
    secret comes back decrypted (the caller masks it)."""
    from agents.core import settings_db

    path = Path(settings_db.DB_PATH)
    if not path.exists():
        return False, None
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        row = conn.execute("SELECT value FROM settings WHERE category=? AND key=?", (category, key)).fetchone()
    finally:
        conn.close()
    if row is None:
        return False, None
    return True, settings_db._decrypt_if_secret(json.loads(row[0]))


def explain_setting(category: str, key: str) -> dict[str, Any] | None:
    """The planes behind one setting, in the order they apply; None when nothing declares
    or stores it."""
    from agents.core import settings_db

    spec = settings_db._SPEC.get((category, key))
    row = next((r for r in settings_db.get_category(category) if r["key"] == key), None)
    if spec is None and row is None:
        return None
    secret = key in settings_db.SECRET_KEYS or settings_db.is_secret_setting(category, key)
    found, stored = _stored_raw(category, key)
    layers: list[dict[str, Any]] = []
    if spec is not None:
        layers.append({"plane": "default", "source": "declared in agents/core/settings_db.py",
                       "value": _masked(spec.get("value"), secret)})
    if found:
        differs = spec is None or not settings_db._same_value(stored, spec.get("value"))
        layers.append({"plane": "store", "source": str(settings_db.DB_PATH),
                       "value": _masked(stored, secret), "overrides": differs})
    refs = (row or {}).get("env_refs") or []
    if refs:
        layers.append({"plane": "environment reference", "source": "${env:…} in the stored value",
                       "names": [{"name": r.get("name"), "set": bool(r.get("set")),
                                  **({"refused": r["refused"]} if r.get("refused") else {})} for r in refs]})
    used = settings_db.get_value(category, key, spec.get("value") if spec else None)
    managed = (row or {}).get("managed")
    if isinstance(managed, Mapping):
        layers.append({"plane": "managed", "source": managed.get("source"),
                       "leaves": managed.get("leaves") or [], "applies": not managed.get("invalid"),
                       **({"invalid": managed["invalid"]} if managed.get("invalid") else {})})
    overlay = (row or {}).get("overlay")
    if overlay:
        layers.append({"plane": "posture", "source": overlay, "value": _masked(row.get("in_effect"), secret),
                       "scope": "the hub's runtime settings (the orchestrator applies it over what readers "
                                "of the store see)"})
    # which plane supplied what a reader gets
    if isinstance(managed, Mapping) and not managed.get("invalid"):
        supplied = "managed"
    elif refs and any(r.get("set") and not r.get("refused") for r in refs) and used != stored:
        supplied = "environment reference"
    elif found and (spec is None or not settings_db._same_value(stored, spec.get("value"))):
        supplied = "store"
    else:
        supplied = "default"
    result = {"name": f"{category}.{key}", "kind": "setting", "value": _masked(used, secret),
              "supplied_by": supplied, "layers": layers, "secret": secret}
    if overlay:
        result["runtime"] = {"value": _masked(row.get("in_effect"), secret), "supplied_by": "posture"}
    return result


def explain_env(name: str, environ: Mapping[str, str]) -> dict[str, Any] | None:
    """The layers behind one environment variable — set or unset in each, never a value."""
    from agents.core import env_alias, env_registry
    from agents.core import env_provenance as ep

    canonical = env_registry.canonical(name)
    entry = env_registry.entries().get(canonical or "", {})
    if canonical is None and not name.startswith(env_registry.HUB_PREFIXES):
        return None
    spellings = [canonical or name, *entry.get("aliases", [])]
    keys = {env_alias.canonical(s) for s in spellings}
    table, _names = env_surface(environ)
    hit = next((table[k] for k in keys if k in table), None)
    layers: list[dict[str, Any]] = []
    if entry.get("default") is not None and entry.get("type") != "credential":
        layers.append({"plane": "default", "source": "the reader's shipped default", "value": entry["default"]})
    for layer in (ep.USER_ENV, ep.REPO_ENV, ep.PROCESS):
        shadowed = bool(hit and layer in (hit.get("shadowed") or []))
        if hit and (hit.get("layer") == layer or shadowed):
            layers.append({"plane": ep.LABELS.get(layer, layer), "set": True, "applies": hit.get("layer") == layer})
    managed = _managed_env_keys(environ)
    pinned = bool(keys & managed)
    if pinned:
        layers.append({"plane": ep.LABELS.get(ep.MANAGED, ep.MANAGED), "set": True, "applies": True})
    supplied = (ep.LABELS.get(ep.MANAGED) if pinned else
                ep.LABELS.get(hit["layer"], hit["layer"]) if hit else ("default" if layers else "unset"))
    return {"name": canonical or name, "kind": "environment", "set": bool(hit) or pinned,
            "supplied_by": supplied, "layers": layers, "type": entry.get("type"),
            "purpose": entry.get("purpose") or "", "known": canonical is not None}


def env_surface(environ: Mapping[str, str]) -> tuple[dict, list[str]]:
    """``(the provenance table, every name the .env files and the environment set)`` for
    *environ*, as the hub's load would see them (a profile reads its own .env only; H689b).
    Names and layers only: no value is read into the result."""
    from agents.core import env_provenance as ep
    from agents.core.paths import user_home

    profile_env = ep.profile_env_file(environ)
    if profile_env is not None:
        files = [profile_env]
        table = ep.derive(None, profile_env, environ)
    else:
        def home_env(merged):
            home = user_home(merged)
            return home / ".env" if home is not None else None

        files = [ep.REPO_ENV_FILE, home_env(ep.after_repo_layer(ep.REPO_ENV_FILE, environ))]
        table = ep.derive(ep.REPO_ENV_FILE, home_env, environ)
    names = list(environ)
    for path in files:
        if path is not None and ep.is_file_or_fifo(path) and not ep.is_fifo(path):
            names += ep.env_file_keys(path)
    return table, names


def _managed_env_keys(environ: Mapping[str, str]) -> set[str]:
    from agents.core import env_alias, managed_scope
    from agents.core import env_provenance as ep

    try:
        root = managed_scope.managed_dir(environ)[0]
    except Exception:  # noqa: BLE001 — an unreadable managed scope pins nothing here
        return set()
    if root is None:
        return set()
    path = root / managed_scope.ENV_FILE
    if not ep.is_file_or_fifo(path) or ep.is_fifo(path):
        return set()
    return {env_alias.canonical(k) for k in ep.env_file_keys(path)}


def explain_agent(agent_id: str, field: str) -> dict[str, Any] | None:
    """An agent's field as the registry (agents.yaml under the owner's roster) declares it."""
    from agents.core.config import JarvisConfig

    if field not in AGENT_FIELDS:
        return None
    config = JarvisConfig()
    agent = config.agents.get(agent_id)
    if agent is None:
        return None
    value = getattr(agent, field, None)
    return {"name": f"agents.{agent_id}.{field}", "kind": "agent", "value": value,
            "supplied_by": "agents.yaml", "layers": [{"plane": "agents.yaml", "source": str(config.path),
                                                       "value": value}],
            "note": "a per-agent override set through PUT /api/admin/agents/{id} lives in the running "
                    "hub's memory only and is not part of this view"}


def explain(name: str, environ: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """The effective value of *name* and the plane that supplied it; None when no plane
    knows the name."""
    from agents.core import env_registry

    environ = {} if environ is None else environ
    if not isinstance(name, str) or not name or len(name) > 512:
        return None
    if name.startswith("agents."):
        parts = name.split(".")
        return explain_agent(parts[1], parts[2]) if len(parts) == 3 else None
    if "." not in name and (env_registry.canonical(name) is not None
                            or name.startswith(env_registry.HUB_PREFIXES)):
        return explain_env(name, environ)
    category, _, key = name.partition(".")
    return explain_setting(category, key) if key else None


__all__ = ["AGENT_FIELDS", "MASK", "env_surface", "explain", "explain_agent", "explain_env",
           "explain_setting"]
