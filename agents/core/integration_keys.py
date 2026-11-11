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
* **Choices.** Two non-secret choices are kept the same way: the search backend
  (``JARVIS_WEB_BACKEND``) and the video provider (``JARVIS_VIDEO_PROVIDER``, G19), each
  applied at start only with a value the panel offers.
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
OWNER_PREFIX = PREFIX + "owner."
#: The longest key the panel takes (a real key is far shorter).
MAX_VALUE = 4096
#: A value shorter than this shows no characters at all, only "set".
HINT_MIN_LENGTH = 20

_LOCK = threading.Lock()
#: name -> sha256 of the value this module placed in os.environ (never the value).
_PLACED: dict[str, str] = {}


class EnvManaged(Exception):
    """The environment (process or ``.env``) sets this name: it is edited there."""


class UnknownName(KeyError):
    """A name the Integrations panel does not manage."""


def _refuse_managed(name: str) -> None:
    """G1 — raise ``managed_scope.ManagedRefused`` when the administrator pinned *name*
    (or no configuration write may happen now: managed mode, an unreadable managed file)."""
    from agents.core.managed_scope import check_env_write

    check_env_write(name)


def admin_managed(name: str) -> bool:
    """G1 — True when the administrator's managed ``.env`` pins *name* (either spelling)."""
    try:
        from agents.core.managed_scope import canonical_env, env_pins

        return canonical_env(name) in env_pins(strict=False)
    except Exception:  # noqa: BLE001 — a view: never fail on the managed layer
        return False


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

#
# Each stored key records which panel entries it was typed for (``integration.owner.<NAME>``,
# a comma list of entry ids, not secret). A key name several providers read
# (``DASHSCOPE_API_KEY`` …) is one value; the owners list says who vouched for it, so a
# sibling never shows it as its own and removing it for one entry leaves the others' key.

def _owners_name(name: str) -> str:
    return OWNER_PREFIX + name


def owners(name: str) -> list[str]:
    """The panel entries the stored key *name* was set for (``[]`` when none / no store)."""
    if not _store_path().exists():
        return []
    try:
        raw = _store().get(_owners_name(name)) or ""
    except Exception:  # noqa: BLE001
        return []
    return [part for part in raw.split(",") if part]


def stored_copy(name: str) -> bool:
    """True when the store holds a key for *name* (whoever is in effect)."""
    if not _store_path().exists():
        return False
    try:
        return (KEY_PREFIX + name) in _store()
    except Exception:  # noqa: BLE001
        return False


def set_key(name: str, value: str, *, allowed: frozenset[str] | None = None, owner: str = "",
            keep_owners: bool = False) -> dict:
    """Store *value* for key *name* (encrypted) and put it in effect now. *owner* is the
    panel entry it was typed for; *keep_owners* keeps the entries that already vouched for
    the same key (the owner confirmed it is the same key), else they are replaced."""
    _check(name, allowed)
    _refuse_managed(name)
    value = str(value or "").strip()
    if not value or len(value) > MAX_VALUE or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("a key is one line of at most 4096 characters")
    with _LOCK:
        if env_owned(name):
            raise EnvManaged(name)
        before = owners(name) if keep_owners else []
        store = _store()
        store.set(KEY_PREFIX + name, value)
        if owner:
            store.set(_owners_name(name), ",".join(dict.fromkeys([*before, owner])))
        _place(name, value)
    return status(name)


def release_key(name: str, owner: str, *, allowed: frozenset[str] | None = None) -> dict:
    """Take entry *owner*'s claim off key *name*. The stored key goes only when no other
    entry vouched for it; it leaves the environment only if this module put it there (a
    ``.env`` value stays). ``{"removed", "kept_for", "env"}``."""
    _check(name, allowed)
    _refuse_managed(name)
    with _LOCK:
        others = [o for o in owners(name) if o != owner]
        if others:
            _store().set(_owners_name(name), ",".join(others))
            return {"removed": False, "kept_for": others, "env": env_owned(name)}
        if _store_path().exists():
            store = _store()
            store.delete(KEY_PREFIX + name)
            store.delete(_owners_name(name))
        env = env_owned(name)
        if not env:
            _unplace(name)
        return {"removed": True, "kept_for": [], "env": env}


def clear_key(name: str, *, allowed: frozenset[str] | None = None) -> dict:
    """Remove the stored key *name* entirely and take it out of effect now."""
    _check(name, allowed)
    _refuse_managed(name)
    with _LOCK:
        if env_owned(name):
            raise EnvManaged(name)
        if _store_path().exists():
            store = _store()
            store.delete(KEY_PREFIX + name)
            store.delete(_owners_name(name))
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
        source = ("managed" if admin_managed(spelling)          # G1: pinned by the administrator
                  else "hub" if placed_here(spelling) else "env")
        value = value.strip()
        hint = f"…{value[-4:]}" if len(value) >= HINT_MIN_LENGTH else None
        return {"set": True, "source": source, "hint": hint}
    return {"set": False, "source": None, "hint": None}


# ── non-secret choices (a search backend) ────────────────────────────────────────

def set_choice(name: str, value: str) -> None:
    """Store a non-secret choice (``JARVIS_WEB_BACKEND``) and put it in effect; an empty
    value removes it (back to the default)."""
    value = str(value or "").strip()
    _refuse_managed(name)
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

def _allowed_names() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """What a stored entry may put in the environment: only the key names the panel
    manages, and only the search choice with one of the panel's backend names. Anything
    else in the store (written by hand or by another tool) is never applied."""
    from agents.core import integrations_catalog

    try:
        keys = integrations_catalog.managed_keys()
    except Exception:  # noqa: BLE001 — the static search rows still apply
        keys = frozenset(n for row in integrations_catalog.SEARCH_ROWS for n in row.keys)
    try:            # G21: the channels' secrets, set in the HUD's Channels panel
        from agents.core.channel_config import secret_names

        keys = keys | secret_names()
    except Exception:  # noqa: BLE001 — no channel secret is applied then
        logger.warning("channel secret names unavailable; none applied")
    backends = frozenset(row.name for row in integrations_catalog.SEARCH_ROWS)
    try:
        from agents.core.creative.video_providers import PROVIDERS

        videos = frozenset(PROVIDERS)
    except Exception:  # noqa: BLE001 — no video choice is applied then
        videos = frozenset()
    return keys, {integrations_catalog.WEB_BACKEND: backends, integrations_catalog.VIDEO_CHOICE: videos}


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
    keys, choices = _allowed_names()
    try:            # G1 — a name the administrator pinned is never overwritten by a stored copy
        from agents.core.managed_scope import env_pins

        pinned = frozenset(env_pins(strict=False))
    except Exception:  # noqa: BLE001 — the hub's load already refused an unreadable managed file
        pinned = frozenset()
    applied = []
    with _LOCK:
        for stored in names:
            if stored.startswith(KEY_PREFIX):
                name = stored[len(KEY_PREFIX):]
                allowed_here = name in keys
            elif stored.startswith(CHOICE_PREFIX):
                name = stored[len(CHOICE_PREFIX):]
                allowed_here = name in choices
            else:
                continue
            if not name or not allowed_here or env_owned(name) or placed_here(name):
                continue
            from agents.core.managed_scope import canonical_env

            if canonical_env(name) in pinned:
                continue
            try:
                value = store.get(stored)
            except Exception:  # noqa: BLE001
                logger.warning("integration value %s could not be read; skipped", name)
                continue
            if stored.startswith(CHOICE_PREFIX) and value not in choices[name]:
                logger.warning("the stored choice for %s is not a known value; skipped", name)
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
