"""integration_keys.py — keys and choices the owner sets in the HUD's Integrations panel.

Before this, turning on a search backend or a model provider meant editing ``.env`` and
restarting. The Integrations panel (``routers/integrations_setup.py``) stores the same
values here instead:

* **Where.** In the hub's encrypted secret store (``agents.core.secrets.SecretStore``,
  ``<data>/security/secrets.enc``, Fernet with the store's own key or
  ``JARVIS_SECRET_KEY``), under the reserved prefix ``integration.``. The secret broker
  treats that prefix as internal: it never lists the names, never resolves a
  ``{{secret:…}}`` handle to one and never deletes one; it still redacts their values.
  Nothing is written to ``.env``, to the settings database or to the browser.
* **How it takes effect.** A stored value is placed in the hub's process environment
  under its own name (``EXA_API_KEY``, ``DEEPSEEK_API_KEY`` …), exactly where a ``.env``
  key lands when the hub loads it. Every reader already goes through
  ``env_config.env_str`` at call time (the search providers' ``configured()`` checks, the
  adopted profiles' ``auth_key``, the router's ``detect()``), so the value is in effect
  for the next read, without a restart. The names are all on ``code_env``'s managed list
  (or are native keys a skill cannot be granted either), so the sandbox child
  environment never receives them.
* **``.env`` wins.** A name the environment already sets (the process environment or a
  ``.env`` file, under either spelling for a ``JARVIS_``/``NERVA_`` name) belongs to it:
  the panel shows it as "set in .env" and refuses to overwrite or remove it there. At
  start, :func:`apply_stored` fills only names the environment left unset, after the
  ``.env`` files are loaded, so a key in ``.env`` keeps winning across restarts.

Values never leave this module except into the process environment: :func:`status`
answers whether a name is set, by whom, and at most the value's last four characters.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("jarvis.integration_keys")

#: The secret-store namespace (the secret broker keeps it internal).
PREFIX = "integration."
KEY_PREFIX = PREFIX + "key."
CHOICE_PREFIX = PREFIX + "choice."
#: The longest key the panel takes (a real key is far shorter).
MAX_VALUE = 4096
#: A value shorter than this shows no characters at all, only "set".
HINT_MIN_LENGTH = 12

_LOCK = threading.Lock()
#: name -> sha256 of the value this module placed in os.environ (never the value).
_PLACED: dict[str, str] = {}


class EnvManaged(Exception):
    """The environment (process or ``.env``) sets this name: it is edited there."""


class UnknownName(KeyError):
    """A name the Integrations panel does not manage."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _store_path() -> Path:
    from agents.core.paths import data_path

    return Path(data_path("security", "secrets.enc"))


def _store():
    from agents.core.secrets import SecretStore

    return SecretStore(path=_store_path())


def _spellings(name: str) -> tuple[str, ...]:
    from agents.core.env_config import other_spelling

    other = other_spelling(name)
    return (name,) if other is None else (name, other)


def placed_here(name: str) -> bool:
    """True when the value now in the environment under *name* is the one this module put there."""
    digest = _PLACED.get(name)
    value = os.environ.get(name)
    return digest is not None and value is not None and _digest(value) == digest


def env_owned(name: str) -> bool:
    """True when the environment sets *name* (either spelling) and this module did not."""
    for spelling in _spellings(name):
        value = os.environ.get(spelling)
        if value is not None and value.strip() and not placed_here(spelling):
            return True
    return False


def _place(name: str, value: str) -> None:
    os.environ[name] = value
    _PLACED[name] = _digest(value)


def _unplace(name: str) -> None:
    if placed_here(name):
        os.environ.pop(name, None)
    _PLACED.pop(name, None)


def _check(name: str, allowed: frozenset[str] | None) -> None:
    if allowed is not None and name not in allowed:
        raise UnknownName(name)


# ── keys ─────────────────────────────────────────────────────────────────────────

def set_key(name: str, value: str, *, allowed: frozenset[str] | None = None) -> dict:
    """Store *value* for key *name* (encrypted) and put it in effect now."""
    _check(name, allowed)
    value = str(value or "").strip()
    if not value or len(value) > MAX_VALUE or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("a key is one line of at most 4096 characters")
    with _LOCK:
        if env_owned(name):
            raise EnvManaged(name)
        _store().set(KEY_PREFIX + name, value)
        _place(name, value)
    return status(name)


def clear_key(name: str, *, allowed: frozenset[str] | None = None) -> dict:
    """Remove the stored key *name* and take it out of effect now."""
    _check(name, allowed)
    with _LOCK:
        if env_owned(name):
            raise EnvManaged(name)
        if _store_path().exists():
            _store().delete(KEY_PREFIX + name)
        _unplace(name)
    return status(name)


def status(name: str) -> dict:
    """``{"set", "source", "hint"}`` for *name*: source ``env`` (.env or the process),
    ``hub`` (stored here), or None; ``hint`` is ``…`` and the last four characters of a
    value at least :data:`HINT_MIN_LENGTH` long, else None. Never the value."""
    for spelling in _spellings(name):
        value = os.environ.get(spelling)
        if value is None or not value.strip():
            continue
        source = "hub" if placed_here(spelling) else "env"
        value = value.strip()
        hint = f"…{value[-4:]}" if len(value) >= HINT_MIN_LENGTH else None
        return {"set": True, "source": source, "hint": hint}
    return {"set": False, "source": None, "hint": None}


# ── non-secret choices (a search backend) ────────────────────────────────────────

def set_choice(name: str, value: str) -> None:
    """Store a non-secret choice (``JARVIS_WEB_BACKEND``) and put it in effect; an empty
    value removes it (back to the default)."""
    value = str(value or "").strip()
    with _LOCK:
        if env_owned(name):
            raise EnvManaged(name)
        if value:
            _store().set(CHOICE_PREFIX + name, value)
            _place(name, value)
        else:
            if _store_path().exists():
                _store().delete(CHOICE_PREFIX + name)
            _unplace(name)


# ── start ────────────────────────────────────────────────────────────────────────

def apply_stored() -> list[str]:
    """Put every stored key and choice in effect whose name the environment left unset.

    Called once the ``.env`` files are loaded (the lifespan, ``PluginManager.build``), so
    ``.env`` keeps winning. Returns the names applied. A missing store is not created; an
    unreadable entry is skipped with a warning naming it (never its value)."""
    if not _store_path().exists():
        return []
    try:
        store = _store()
        names = store.names()
    except Exception as exc:  # noqa: BLE001 — a broken store must not stop the hub
        logger.warning("integration keys not applied (type=%s)", type(exc).__name__)
        return []
    applied = []
    with _LOCK:
        for stored in names:
            if not stored.startswith((KEY_PREFIX, CHOICE_PREFIX)):
                continue
            name = stored.split(".", 2)[2]
            if not name or env_owned(name) or placed_here(name):
                continue
            try:
                value = store.get(stored)
            except Exception:  # noqa: BLE001
                logger.warning("integration value %s could not be read; skipped", name)
                continue
            if value:
                _place(name, value)
                applied.append(name)
    return applied


def reset_for_tests() -> None:
    with _LOCK:
        for name in list(_PLACED):
            _unplace(name)


__all__ = ["CHOICE_PREFIX", "EnvManaged", "KEY_PREFIX", "PREFIX", "UnknownName", "apply_stored",
           "clear_key", "env_owned", "placed_here", "set_choice", "set_key", "status"]
