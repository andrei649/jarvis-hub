"""channel_config.py — view and edit the messaging channels' settings from the HUD (G21 · H151/H160).

The channel the hub wires at start (Telegram) reads its settings from the environment.
Before this, changing one meant editing ``.env``. The HUD's Channels panel now edits the
same names, in two kinds:

* **Secrets** (the bot token) go only through :mod:`agents.core.integration_keys`: the
  hub's encrypted secret store under the broker-internal ``integration.`` prefix, placed in the process
  environment for the next read and again at the next start (``apply_stored``). A secret
  never comes back out: the view says only whether it is set and where (``env`` / ``hub`` /
  ``managed``) — not even the last characters.
* **Plain settings** (allowlists, switches) go to the settings
  database as one json setting, ``channels.config`` (``{NAME: value}``), and are placed
  in the environment by :func:`apply_stored` at start, right after the integration keys.
  Every value is validated by its field's kind before anything is written.

Both kinds follow the Integrations panel's rules: a name the environment already sets
(``.env`` or the process, either spelling) belongs to it and is refused here (``.env``
wins, :class:`EnvOwned`); a name the administrator pinned in the managed layer, or any
write while managed mode is on or the managed files cannot be read, is refused
(``managed_scope.ManagedRefused`` → 409, the settings write is checked by
``settings_db.put_category`` and every name by ``managed_scope.check_env_write``).

Channels are wired once, at start, so a change applies at the next restart (the view
says ``restart_required``). Only the names listed in :data:`CHANNELS` can be set.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("jarvis.channel_config")

SETTING_CATEGORY = "channels"
SETTING_KEY = "config"
MAX_TEXT = 512
MAX_LIST = 64

_LOCK = threading.Lock()
#: name -> sha256 of the plain value this module placed in os.environ (never the value).
_PLACED: dict[str, str] = {}
#: names whose value changed in this process after the channels were wired.
_CHANGED: set[str] = set()

class EnvOwned(Exception):
    """The environment (process or ``.env``) sets this name: it is edited there."""


class FrontDoorRefused(Exception):
    """H088: the write would leave an inbound channel answering any sender — the next start
    would refuse it (``boot_guards.front_door_problem``, the one predicate both ask)."""


def front_door_check(changes: dict[str, str | None], environ=None) -> None:
    """Refuse (:class:`FrontDoorRefused`) a write that opens an unguarded front door the
    boot guard would refuse: the boot's own predicate (``boot_guards.front_door_problems``)
    over the running process's environment, before and after *changes* (``None`` removes a
    name). A write is refused when it adds a door to that list — a first one, or a second
    one beside a door already refused; a write that adds none is not refused here. What
    this cannot see: a ``.env`` edited by hand since the hub started."""
    from agents.core.boot_guards import front_door_problems

    env = dict(os.environ if environ is None else environ)
    before = set(front_door_problems(env))
    after_env = dict(env)
    for name, value in changes.items():
        for spelling in _spellings(name):
            after_env.pop(spelling, None)
        if value is not None:
            after_env[name] = value
    added = [problem for problem in front_door_problems(after_env) if problem not in before]
    if added:
        raise FrontDoorRefused(added[0].replace("Refusing to start: ", "Not saved: the next start would refuse it — ", 1))


class InvalidValue(ValueError):
    """A value its field's kind does not accept; ``reason`` names the field, never the value."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"          # text | bool | int_list
    secret: bool = False
    now: bool = False           # read on every use (applies without a restart)

    def view(self) -> dict:
        return {"name": self.name, "label": self.label, "kind": "secret" if self.secret else self.kind,
                "secret": self.secret, "applies": "now" if self.now else "restart"}


@dataclass(frozen=True)
class Channel:
    id: str
    label: str
    fields: tuple[Field, ...]
    note: str = ""

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)


CHANNELS: tuple[Channel, ...] = (
    Channel("telegram", "Telegram", (
        Field("TELEGRAM_BOT_TOKEN", "Bot token (from @BotFather)", secret=True),
        Field("TELEGRAM_ALLOWED_USER_IDS", "Owner Telegram user ids", "int_list"),
    ), "the bot starts when a token is set; pairing admits other senders"),
)
_BY_ID = {c.id: c for c in CHANNELS}


def channel(channel_id: str) -> Channel | None:
    return _BY_ID.get(channel_id)


def secret_names() -> frozenset[str]:
    """Every secret name a channel field may store (the integration store's allowlist)."""
    return frozenset(f.name for c in CHANNELS for f in c.fields if f.secret)


def plain_names() -> frozenset[str]:
    return frozenset(f.name for c in CHANNELS for f in c.fields if not f.secret)


# ── validation ─────────────────────────────────────────────────────────────────

def _plain_text(value: str) -> str:
    if len(value) > MAX_TEXT or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidValue("text")
    return value


def normalise(field: Field, value: Any) -> str:
    """The environment string for *value*, or :class:`InvalidValue`."""
    if field.kind == "bool":
        if isinstance(value, bool):
            return "1" if value else "0"
        from agents.core.env_config import is_recognized_bool, truthy

        text = str(value).strip()
        if not text:
            return "0"
        if not is_recognized_bool(text):
            raise InvalidValue(field.name)
        return "1" if truthy(text) else "0"
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise InvalidValue(field.name)
    text = _plain_text(str(value).strip())
    if field.kind == "text":
        return text
    if field.kind == "int_list":
        items = [p.strip() for p in text.split(",") if p.strip()]
        if len(items) > MAX_LIST:
            raise InvalidValue(field.name)
        if not all(re.fullmatch(r"-?[0-9]{1,20}", p) for p in items):
            raise InvalidValue(field.name)
        return ",".join(items)
    raise InvalidValue(field.name)  # pragma: no cover — every kind is handled above


# ── where a value comes from ───────────────────────────────────────────────────

def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spellings(name: str) -> tuple[str, ...]:
    from agents.core.env_config import other_spelling

    other = other_spelling(name)
    return (name,) if other is None else (name, other)


def _raw(name: str) -> str | None:
    """One spelling's value exactly as the process holds it. This module places and
    withdraws channel values itself, so it must see each spelling on its own (not
    env_config's merged, pin-aware read) to know which ones it put there."""
    return os.environ.get(name)


def _placed_here(name: str) -> bool:
    digest = _PLACED.get(name)
    value = _raw(name)
    return digest is not None and value is not None and _digest(value) == digest


def plain_env_owned(name: str) -> bool:
    """True when the environment sets *name* (either spelling) and this module did not."""
    for spelling in _spellings(name):
        value = _raw(spelling)
        if value is not None and value.strip() and not _placed_here(spelling):
            return True
    return False


def _managed_pinned(name: str) -> bool:
    try:
        from agents.core.managed_scope import canonical_env, env_pins

        return canonical_env(name) in env_pins(strict=False)
    except Exception:  # noqa: BLE001 — a view never fails on the managed layer
        return False


def stored_plain() -> dict[str, str]:
    """The plain values the HUD stored (``channels.config``), only names this module knows."""
    from agents.core import settings_db

    try:
        raw = settings_db.get_value(SETTING_CATEGORY, SETTING_KEY, {})
    except Exception:  # noqa: BLE001 — an unreadable store shows nothing stored
        logger.warning("channels.config could not be read")
        return {}
    if not isinstance(raw, dict):
        return {}
    names = plain_names()
    return {k: str(v) for k, v in raw.items() if k in names and isinstance(v, (str, int, bool))}


def _plain_state(field: Field, stored: dict[str, str]) -> dict:
    out = field.view()
    for spelling in _spellings(field.name):
        value = _raw(spelling)
        if value is not None and value.strip():
            source = ("managed" if _managed_pinned(spelling)
                      else "hub" if _placed_here(spelling) else "env")
            return {**out, "set": True, "source": source, "value": value.strip(),
                    "editable": source == "hub"}
    if field.name in stored:      # stored, not yet in effect (the environment set it, then unset)
        return {**out, "set": True, "source": "hub", "value": stored[field.name], "editable": True}
    return {**out, "set": False, "source": None, "value": None, "editable": True}


def _secret_state(field: Field) -> dict:
    from agents.core import integration_keys

    status = integration_keys.status(field.name)
    source = status.get("source")
    return {**field.view(), "set": bool(status.get("set")), "source": source,
            "editable": source in (None, "hub")}


def listing(running: set[str] | frozenset[str] = frozenset()) -> dict:
    """Every channel with its fields' state — never a secret's value."""
    stored = stored_plain()
    out = []
    for ch in CHANNELS:
        fields = [(_secret_state(f) if f.secret else _plain_state(f, stored)) for f in ch.fields]
        changed = sorted(f.name for f in ch.fields if f.name in _CHANGED and not f.now)
        out.append({"id": ch.id, "label": ch.label, "note": ch.note, "running": ch.id in running,
                    "fields": fields, "restart_required": bool(changed), "changed": changed})
    return {"channels": out, "precedence": "env", "setting": f"{SETTING_CATEGORY}.{SETTING_KEY}"}


# ── writes ─────────────────────────────────────────────────────────────────────

def _check_managed(name: str) -> None:
    from agents.core.managed_scope import check_env_write

    check_env_write(name)


def set_plain(channel_id: str, values: dict[str, Any]) -> dict:
    """Store plain *values* (``None`` removes one) for *channel_id* and place them in the
    environment. Validates everything first; writes nothing on any refusal."""
    from agents.core import settings_db

    ch = channel(channel_id)
    if ch is None:
        raise KeyError(channel_id)
    if not values:
        raise InvalidValue("values")
    planned: dict[str, str | None] = {}
    for name, value in values.items():
        field = ch.field(name)
        if field is None or field.secret:
            raise KeyError(name)
        planned[name] = None if value is None else normalise(field, value)
    for name in planned:
        _check_managed(name)
        if plain_env_owned(name):
            raise EnvOwned(name)
    front_door_check(planned)
    with _LOCK:
        stored = stored_plain()
        merged = dict(stored)
        for name, value in planned.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        settings_db.put_category(SETTING_CATEGORY, {SETTING_KEY: merged})
        for name, value in planned.items():
            field = ch.field(name)
            if value is None:
                if _placed_here(name):
                    os.environ.pop(name, None)
                _PLACED.pop(name, None)
            else:
                os.environ[name] = value
                _PLACED[name] = _digest(value)
            if field is not None and not field.now:
                _CHANGED.add(name)
    return {"written": sorted(planned)}


def set_secret(channel_id: str, name: str, value: str) -> dict:
    """Store a channel secret through the integration-key store (encrypted, never echoed)."""
    from agents.core import integration_keys

    ch = channel(channel_id)
    field = ch.field(name) if ch is not None else None
    if field is None or not field.secret:
        raise KeyError(name)
    front_door_check({name: str(value)} if isinstance(value, str) and value.strip() else {name: None})
    try:
        integration_keys.set_key(name, value, allowed=secret_names(), owner=f"channel.{channel_id}")
    except integration_keys.EnvManaged:
        raise EnvOwned(name) from None
    if not field.now:
        _CHANGED.add(name)
    state = integration_keys.status(name)
    return {"name": name, "set": bool(state.get("set")), "source": state.get("source")}


def clear_secret(channel_id: str, name: str) -> dict:
    from agents.core import integration_keys

    ch = channel(channel_id)
    field = ch.field(name) if ch is not None else None
    if field is None or not field.secret:
        raise KeyError(name)
    front_door_check({name: None})
    try:
        integration_keys.clear_key(name, allowed=secret_names())
    except integration_keys.EnvManaged:
        raise EnvOwned(name) from None
    if not field.now:
        _CHANGED.add(name)
    state = integration_keys.status(name)
    return {"name": name, "set": bool(state.get("set")), "source": state.get("source")}


# ── start ──────────────────────────────────────────────────────────────────────

def apply_stored() -> list[str]:
    """Place every stored plain value whose name the environment left unset (``.env`` and
    the administrator's pins win). Called at start right after the integration keys, before
    the channels are wired. Returns the names applied."""
    stored = stored_plain()
    applied = []
    with _LOCK:
        for name, value in stored.items():
            field = next((f for c in CHANNELS for f in c.fields if f.name == name), None)
            if field is None or field.secret or plain_env_owned(name) or _managed_pinned(name):
                continue
            try:
                value = normalise(field, value)
            except InvalidValue:
                logger.warning("the stored channel setting %s is not valid; skipped", name)
                continue
            os.environ[name] = value
            _PLACED[name] = _digest(value)
            applied.append(name)
    return applied


def reset_for_tests() -> None:
    with _LOCK:
        for name in list(_PLACED):
            if _placed_here(name):
                os.environ.pop(name, None)
        _PLACED.clear()
        _CHANGED.clear()


__all__ = ["CHANNELS", "EnvOwned", "InvalidValue", "apply_stored", "channel", "clear_secret", "listing",
           "normalise", "plain_names", "secret_names", "set_plain", "set_secret", "stored_plain"]
