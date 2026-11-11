"""H342 — the values a skill's declared environment variables need, kept per skill.

A SKILL.md may declare ``required_environment_variables`` (also ``setup.collect_secrets``
and the legacy ``prerequisites.env_vars``; :mod:`.frontmatter` merges them). Hermes asks
for the values when the skill is installed and writes them to its global ``.env``. Nerva
keeps them narrower:

* **Where.** In the hub's encrypted secret store (the same ``secrets.enc`` the Integrations
  panel uses, :mod:`agents.core.integration_keys`), under ``integration.skill.<skill>.<NAME>``,
  with the install it was set for beside it (``integration.skillbind.<skill>.<NAME>``). The
  secret broker treats the ``integration.`` prefix as internal (never listed, never resolved
  from a ``{{secret:…}}`` handle) and redacts the values from text it scrubs.
* **Who sees it.** Nobody: :func:`requirements` answers whether a name is set and by whom
  (``skill``: stored here for this install of the skill; ``env``: the hub's own
  environment), never the value or any part of it. For a reserved name (a managed provider
  key, a control or hub name) it says only that the name is reserved, not whether the hub
  has it.
* **Where it goes.** Only to the skill's **own commands** (``Skill.execute``), as the
  read-only ``context["skill_env"]`` (:func:`skill_env`). Never into ``os.environ`` and
  **never into an ``execute_code`` interpreter**: an interpreter runs code the model wrote,
  and the ``skill_view`` that declares names can be the model's own call (G20 review). The
  code tool keeps reading only the hub's environment, as H595 had it. Error text a command
  returns or logs is scrubbed of its values (:func:`scrub`).
* **Which install.** A value is bound to the install it was set for (the install id the
  folder carries, else its path). Another skill that later takes the name does not get it;
  the owner sets it again. Removing a skill for good clears its values (:func:`forget_skill`).
* **Which names.** Only a name the skill itself declares, and only one ``code_env`` lets a
  skill pass.
* **While missing.** :func:`missing` lists the required (not ``optional``, not reserved)
  names that are set nowhere; a skill's runnable commands refuse with :func:`setup_message`.
"""

from __future__ import annotations

import base64
import logging
import re
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, quote_plus

logger = logging.getLogger("jarvis.skills.secrets")

PREFIX = "integration.skill."
BIND_PREFIX = "integration.skillbind."
MAX_VALUE = 4096
_SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
_LOCK = threading.Lock()


class SetupRefused(ValueError):
    """A name this skill does not declare, or one no skill may be handed."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _check(skill: str, name: str) -> None:
    if not isinstance(skill, str) or not _SKILL.fullmatch(skill):
        raise SetupRefused("invalid_skill")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SetupRefused("invalid_name")


def _key(skill: str, name: str) -> str:
    _check(skill, name)
    return f"{PREFIX}{skill}.{name}"


def _bind_key(skill: str, name: str) -> str:
    _check(skill, name)
    return f"{BIND_PREFIX}{skill}.{name}"


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


def identity(skill: Any) -> str:
    """The install a value is bound to: the folder's install id, else its resolved path."""
    path = getattr(skill, "path", None)
    if not path:
        return "none"
    try:
        from .loader import install_id_of

        install = install_id_of(Path(path))
    except Exception:  # noqa: BLE001
        install = ""
    if install:
        return f"install:{install}"
    try:
        return f"path:{Path(path).resolve()}"
    except OSError:
        return f"path:{path}"


def declared(skill: Any) -> list[dict]:
    """The skill's normalised declarations (``name``, ``prompt``, ``help``, ``optional`` …)."""
    manifest = getattr(skill, "manifest", None)
    rows = manifest.get("required_environment_variables", []) if isinstance(manifest, Mapping) else []
    return [dict(row) for row in rows if isinstance(row, Mapping) and isinstance(row.get("name"), str)]


def _lookup(skill: Any, name: str) -> tuple[str | None, bool]:
    """``(value bound to this install or None, a value for another install exists)``."""
    skill_name = str(getattr(skill, "name", "") or "")
    if not _store_exists():
        return None, False
    try:
        store = _store()
        value = store.get(_key(skill_name, name))
        bound = store.get(_bind_key(skill_name, name))
    except SetupRefused:
        return None, False
    except Exception:  # noqa: BLE001 — an unreadable store holds nothing usable
        logger.warning("a skill setup value could not be read (skill=%s, name=%s)", skill_name, name)
        return None, False
    if not isinstance(value, str) or not value:
        return None, False
    if bound != identity(skill):
        return None, True
    return value, False


def _in_env(name: str) -> bool:
    import os

    value = os.environ.get(name)
    return bool(value and value.strip())


def requirements(skill: Any) -> list[dict]:
    """Each declared name: what to ask, whether it is set and where. Never a value; for a
    reserved name, not even whether the hub has it."""
    out = []
    for row in declared(skill):
        name = row["name"]
        entry = {"name": name, "prompt": row.get("prompt") or f"Enter value for {name}",
                 "optional": bool(row.get("optional"))}
        for extra in ("help", "required_for"):
            if row.get(extra):
                entry[extra] = str(row[extra])
        if not passable(name):
            entry.update({"reserved": True, "settable": False, "refused": "reserved_name"})
            out.append(entry)
            continue
        value, stale = _lookup(skill, name)
        source = "skill" if value else "env" if _in_env(name) else None
        entry.update({"set": source is not None, "source": source, "settable": True})
        if stale and value is None:
            entry["stale"] = True      # set for an earlier install of this name: set it again
        out.append(entry)
    return out


def missing(skill: Any) -> list[str]:
    """The required (not optional, not reserved) names set nowhere."""
    try:
        return [row["name"] for row in requirements(skill)
                if not row.get("reserved") and not row["optional"] and not row["set"]]
    except Exception:  # noqa: BLE001 — a probe: an unreadable manifest declares nothing
        logger.warning("skill setup state could not be read", exc_info=True)
        return []


def setup_message(skill_name: str, names: Iterable[str]) -> str:
    listed = ", ".join(names)
    return (f"[skill:{skill_name}] needs setup before it can run: missing environment variable(s) "
            f"{listed}. Set them in Skills → Import → Skill setup (or PUT /api/skills/setup/"
            f"{skill_name}/<NAME>); the value is stored encrypted and handed only to this skill's "
            "own commands.")


def _require_declared(skill: Any, name: str) -> None:
    if name not in {row["name"] for row in declared(skill)}:
        raise SetupRefused("not_declared")
    if not passable(name):
        raise SetupRefused("reserved_name")


def set_value(skill: Any, name: str, value: str) -> dict:
    """Store *value* for the declared *name* of this install of *skill* (encrypted)."""
    skill_name = str(getattr(skill, "name", "") or "")
    key, bind = _key(skill_name, name), _bind_key(skill_name, name)
    _require_declared(skill, name)
    value = str(value or "").strip()
    if not value or len(value) > MAX_VALUE or any(ch in value for ch in "\r\n\x00"):
        raise SetupRefused("invalid_value")
    with _LOCK:
        store = _store()
        store.set(key, value)
        store.set(bind, identity(skill))
    return {"name": name, "set": True, "source": "skill"}


def clear_value(skill: Any, name: str) -> dict:
    """Forget the stored value of *name* for *skill* (a hub environment value stays)."""
    skill_name = str(getattr(skill, "name", "") or "")
    key, bind = _key(skill_name, name), _bind_key(skill_name, name)
    removed = False
    with _LOCK:
        if _store_exists():
            store = _store()
            removed = bool(store.delete(key))
            store.delete(bind)
    reserved = not passable(name)
    return {"name": name, "removed": removed,
            "set": False if reserved else _in_env(name),
            "source": None if reserved or not _in_env(name) else "env"}


def forget_skill(skill_name: str, install_id: str | None = None) -> int:
    """A skill was removed for good: drop its stored values. With *install_id*, only the
    values bound to that install (another install of the name keeps its own)."""
    if not isinstance(skill_name, str) or not _SKILL.fullmatch(skill_name) or not _store_exists():
        return 0
    head, bind_head = f"{PREFIX}{skill_name}.", f"{BIND_PREFIX}{skill_name}."
    dropped = 0
    with _LOCK:
        try:
            store = _store()
            for stored in list(store.names()):
                if not stored.startswith(head) or not _NAME.fullmatch(stored[len(head):]):
                    continue
                name = stored[len(head):]
                if install_id and store.get(bind_head + name) != f"install:{install_id}":
                    continue
                store.delete(stored)
                store.delete(bind_head + name)
                dropped += 1
        except Exception:  # noqa: BLE001 — the binding still keeps a stale value from use
            logger.warning("the setup values of the removed skill %s could not be cleared", skill_name)
    return dropped


def skill_env(skill: Any) -> Mapping[str, str]:
    """The stored values of *skill*'s own declared, passable names, bound to this install
    (read-only), for its in-process commands. Empty when none."""
    found = {}
    for row in declared(skill):
        name = row["name"]
        if passable(name):
            value, _stale = _lookup(skill, name)
            if value is not None:
                found[name] = value
    return MappingProxyType(found)


def _forms(value: str) -> set[str]:
    raw = value.encode("utf-8")
    forms = {value, quote(value, safe=""), quote_plus(value)}
    for enc in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
        text = enc.decode("ascii")
        forms.update({text, text.rstrip("=")})
    return {f for f in forms if len(f) >= 4}


def scrub(text: str, values: Iterable[str]) -> str:
    """*text* with each value (as is, URL-encoded, base64) replaced by ``[REDACTED]``."""
    out = str(text)
    for value in values:
        if isinstance(value, str) and value:
            for form in sorted(_forms(value), key=len, reverse=True):
                out = out.replace(form, "[REDACTED]")
    return out


__all__ = ["BIND_PREFIX", "PREFIX", "SetupRefused", "clear_value", "declared", "forget_skill", "identity",
           "missing", "passable", "requirements", "scrub", "set_value", "setup_message", "skill_env"]
