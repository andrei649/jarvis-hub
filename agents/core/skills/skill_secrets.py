"""H342 — the values a skill's declared environment variables need, kept per skill.

A SKILL.md may declare ``required_environment_variables`` (also ``setup.collect_secrets``
and the legacy ``prerequisites.env_vars``; :mod:`.frontmatter` merges them). Hermes asks
for the values when the skill is installed and writes them to its global ``.env``. Nerva
keeps them narrower:

* **Where.** In the hub's encrypted secret store (the same ``secrets.enc`` the Integrations
  panel uses, :mod:`agents.core.integration_keys`), under ``integration.skill.<skill>.<NAME>``.
  The secret broker treats the ``integration.`` prefix as internal (never listed, never
  resolved from a ``{{secret:…}}`` handle) and redacts these values from text it scrubs.
* **Who sees it.** Nobody: :func:`requirements` answers whether a name is set and by whom
  (``skill``: stored here for this skill; ``env``: the hub's own environment), never the
  value or any part of it.
* **Where it goes.** Never into ``os.environ``. A stored value reaches only an
  ``execute_code`` interpreter started in a scope where the owner viewed (vouched) that very
  skill (:func:`scoped_source`, wired in ``code_tools``), and the in-process commands of
  that skill (:func:`skill_env`). Another skill declaring the same name does not get it.
* **Which names.** Only a name the skill itself declares, and only one ``code_env`` lets a
  skill pass (a managed provider key, a control name such as ``PATH`` or a hub name is
  refused, as it is for the code tool).
* **While missing.** :func:`missing` lists the required (not ``optional``) names that are
  set nowhere; a skill's runnable commands refuse with :func:`setup_message` until they are.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any

logger = logging.getLogger("jarvis.skills.secrets")

PREFIX = "integration.skill."
MAX_VALUE = 4096
_SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_LOCK = threading.Lock()


class SetupRefused(ValueError):
    """A name this skill does not declare, or one no skill may be handed."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _key(skill: str, name: str) -> str:
    if not isinstance(skill, str) or not _SKILL.fullmatch(skill):
        raise SetupRefused("invalid_skill")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SetupRefused("invalid_name")
    return f"{PREFIX}{skill}.{name}"


def _store():
    from agents.core import integration_keys

    return integration_keys._store()


def _store_exists() -> bool:
    from agents.core import integration_keys

    try:
        return integration_keys._store_path().exists()
    except Exception:  # noqa: BLE001 — no data root: nothing stored
        return False


def passable(name: str) -> bool:
    """True when a skill may be handed *name* at all (``code_env``'s rule)."""
    from agents.core.code_env import _passable_name

    return _passable_name(name)


def declared(skill: Any) -> list[dict]:
    """The skill's normalised declarations (``name``, ``prompt``, ``help``, ``optional`` …)."""
    manifest = getattr(skill, "manifest", None)
    rows = manifest.get("required_environment_variables", []) if isinstance(manifest, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping) and isinstance(row.get("name"), str)]


def _stored(skill_name: str, name: str) -> str | None:
    if not _store_exists():
        return None
    try:
        value = _store().get(_key(skill_name, name))
    except SetupRefused:
        return None
    except Exception:  # noqa: BLE001 — an unreadable store holds nothing usable
        logger.warning("a skill setup value could not be read (skill=%s, name=%s)", skill_name, name)
        return None
    return value if isinstance(value, str) and value else None


def _in_env(name: str) -> bool:
    import os

    value = os.environ.get(name)
    return bool(value and value.strip())


def requirements(skill: Any) -> list[dict]:
    """Each declared name: what to ask, whether it is set and where. Never a value."""
    out = []
    name_of_skill = str(getattr(skill, "name", "") or "")
    for row in declared(skill):
        name = row["name"]
        allowed = passable(name)
        source = None
        if allowed and _stored(name_of_skill, name):
            source = "skill"
        elif _in_env(name):
            source = "env"
        entry = {"name": name, "prompt": row.get("prompt") or f"Enter value for {name}",
                 "optional": bool(row.get("optional")), "set": source is not None, "source": source,
                 "settable": allowed}
        for extra in ("help", "required_for"):
            if row.get(extra):
                entry[extra] = str(row[extra])
        if not allowed:
            entry["refused"] = "reserved_name"
        out.append(entry)
    return out


def missing(skill: Any) -> list[str]:
    """The required (not optional) names that are set nowhere. A reserved name the skill
    declares counts too unless the hub's environment has it: it can never be set here."""
    try:
        return [row["name"] for row in requirements(skill) if not row["optional"] and not row["set"]]
    except Exception:  # noqa: BLE001 — a probe: an unreadable manifest declares nothing
        logger.warning("skill setup state could not be read", exc_info=True)
        return []


def setup_message(skill_name: str, names: Iterable[str]) -> str:
    listed = ", ".join(names)
    return (f"[skill:{skill_name}] needs setup before it can run: missing environment variable(s) "
            f"{listed}. Set them in Skills → Import → Skill setup (or PUT /api/skills/setup/"
            f"{skill_name}/<NAME>); the value is stored encrypted and handed only to this skill.")


def _require_declared(skill: Any, name: str) -> None:
    if name not in {row["name"] for row in declared(skill)}:
        raise SetupRefused("not_declared")
    if not passable(name):
        raise SetupRefused("reserved_name")


def set_value(skill: Any, name: str, value: str) -> dict:
    """Store *value* for the declared *name* of *skill* (encrypted). Never echoed."""
    skill_name = str(getattr(skill, "name", "") or "")
    key = _key(skill_name, name)
    _require_declared(skill, name)
    value = str(value or "").strip()
    if not value or len(value) > MAX_VALUE or any(ch in value for ch in "\r\n\x00"):
        raise SetupRefused("invalid_value")
    with _LOCK:
        _store().set(key, value)
    return {"name": name, "set": True, "source": "skill"}


def clear_value(skill: Any, name: str) -> dict:
    """Forget the stored value of *name* for *skill* (a hub environment value stays)."""
    skill_name = str(getattr(skill, "name", "") or "")
    key = _key(skill_name, name)
    removed = False
    with _LOCK:
        if _store_exists():
            removed = bool(_store().delete(key))
    return {"name": name, "removed": removed, "set": _in_env(name),
            "source": "env" if _in_env(name) else None}


def skill_env(skill: Any) -> Mapping[str, str]:
    """The stored values of *skill*'s own declared, passable names (read-only), for its
    in-process commands. Empty when it declares none or nothing is stored."""
    skill_name = str(getattr(skill, "name", "") or "")
    found = {}
    for row in declared(skill):
        name = row["name"]
        if passable(name):
            value = _stored(skill_name, name)
            if value is not None:
                found[name] = value
    return MappingProxyType(found)


def scoped_source(base: Mapping[str, str] | Callable[[str], str | None],
                  declarations: Mapping[str, Iterable[str]]) -> Callable[[str], str | None]:
    """A value reader for one interpreter start: a name declared by a skill the owner
    viewed in this scope (*declarations*: skill → names) reads that skill's stored value
    first; anything else, or a name nothing stored, reads *base* as before."""
    owners: dict[str, list[str]] = {}
    for skill_name, names in sorted((declarations or {}).items()):
        for name in names:
            owners.setdefault(name, []).append(skill_name)

    def read(name: str) -> str | None:
        for skill_name in owners.get(name, ()):
            value = _stored(skill_name, name)
            if value is not None:
                return value
        return base(name) if callable(base) else base.get(name)

    return read


__all__ = ["PREFIX", "SetupRefused", "clear_value", "declared", "missing", "passable", "requirements",
           "scoped_source", "set_value", "setup_message", "skill_env"]
