"""H264 — the declared environment surface: every variable the hub reads, inspectable.

``env_registry.json`` (written by ``scripts/gen_env_registry.py``, kept fresh by
``tests/test_h264_env_registry.py``) lists each hub variable under its preferred
``NERVA_`` name with the deprecated ``JARVIS_`` spelling, its type and shipped default
(measured from the typed getter calls), what it is for (from ``.env.example`` and
``docs/FLAGS.md``) and whether the docs call it required for some setup; plus the other
names ``.env.example`` tells the owner to set (provider keys, channel tokens).

This module answers three questions without ever reading or returning a value:

* :func:`status` — which variables are set, and in which layer (the process
  environment, the repo ``.env``, the data-home ``.env``), with what each one is for;
* :func:`unread` — the ``.env`` / environment names that look like Nerva configuration
  but that nothing reads (a typo, a line left from an older build), with a suggestion;
* :func:`introduced_since` — the variables this build knows that an earlier one did not
  (the settings store records the names the previous build knew, ``settings_ladder``).
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_FILE = Path(__file__).with_name("env_registry.json")
#: Prefixes of Nerva's own configuration names: an unknown name with one is suspicious.
HUB_PREFIXES = ("NERVA_", "JARVIS_")
_NAME_MAX = 128


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """The registry document (cached: it changes only with the build)."""
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def entries() -> dict[str, dict[str, Any]]:
    """``{preferred name: entry}``, in the registry's order."""
    return load()["entries"]


@lru_cache(maxsize=1)
def _spellings() -> dict[str, str]:
    table: dict[str, str] = {}
    for name, entry in entries().items():
        table[name] = name
        for alias in entry.get("aliases", []):
            table[alias] = name
    return table


def _families() -> tuple[str, ...]:
    from agents.core import env_config

    out: list[str] = []
    for family in env_config.HUB_ENV_FAMILIES:
        out += [env_config.PREFERRED_PREFIX + family, env_config.DEPRECATED_PREFIX + family]
    return tuple(out)


def canonical(name: str) -> str | None:
    """The registry name *name* is a spelling of, or None when the registry lists no such
    variable. A name built at run time (``NERVA_ROLE_<NAME>_MODEL``) is its own entry."""
    if not isinstance(name, str):
        return None
    found = _spellings().get(name)
    if found is not None:
        return found
    return name if name.startswith(_families()) else None


def is_known(name: str) -> bool:
    """Whether the hub reads *name*: a registry entry or spelling, a run-time family, or
    the private control channel it hands a sandboxed child (never operator config, but
    not a stale line either)."""
    from agents.core import env_config

    if canonical(name) is not None:
        return True
    return any(name.startswith(prefix + family) for prefix in HUB_PREFIXES
               for family in env_config.UNALIASED_FAMILIES)


def suggestion(name: str) -> str | None:
    """The closest registry name to *name* (difflib), or None when nothing is close."""
    head = name[:_NAME_MAX]
    candidates = list(_spellings())
    close = difflib.get_close_matches(head, candidates, n=1, cutoff=0.75)
    return _spellings()[close[0]] if close else None


def unread(names: Iterable[str]) -> list[dict[str, Any]]:
    """The names among *names* that carry Nerva's prefix and that nothing reads, each with
    the closest variable it may have meant (``{"name", "did_you_mean"}``). Bounded: a name
    is judged by its first 128 characters."""
    out: list[dict[str, Any]] = []
    for name in sorted(set(names)):
        if not isinstance(name, str) or not name.startswith(HUB_PREFIXES) or is_known(name):
            continue
        out.append({"name": name[:_NAME_MAX], "did_you_mean": suggestion(name)})
    return out


def status(table: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per registry variable: ``name``, ``set`` and the ``layer`` that supplies it
    (from an ``env_provenance.derive`` table, keyed by the hub's own spelling), plus its
    type, shipped default (never for a credential), purpose and when it is required.
    Never a value."""
    from agents.core import env_alias

    rows: list[dict[str, Any]] = []
    for name, entry in entries().items():
        spellings = [name, *entry.get("aliases", [])]
        hit = next((table[s] for s in (env_alias.canonical(s) for s in spellings) if s in table), None)
        row = {"name": name, "set": hit is not None, "layer": (hit or {}).get("layer"),
               "namespace": entry.get("namespace"), "type": entry.get("type"),
               "purpose": entry.get("purpose") or "", "required_when": entry.get("required_when") or "",
               "section": entry.get("section") or ""}
        if entry.get("type") != "credential" and entry.get("default") is not None:
            row["default"] = entry["default"]
        rows.append(row)
    return rows


def introduced_since(previous: Iterable[str]) -> list[str]:
    """The registry names this build lists that *previous* (the names an earlier build
    listed) does not; ``[]`` when *previous* is empty (nothing to compare against)."""
    before = set(previous)
    if not before:
        return []
    return [name for name in entries() if name not in before]


def documented_share() -> tuple[int, int]:
    """``(hub variables with a purpose, hub variables)`` — the registry's own gap."""
    hub = [e for e in entries().values() if e.get("namespace") == "hub"]
    return sum(1 for e in hub if e.get("purpose")), len(hub)


__all__ = ["HUB_PREFIXES", "REGISTRY_FILE", "canonical", "documented_share", "entries", "introduced_since",
           "is_known", "load", "status", "suggestion", "unread"]
