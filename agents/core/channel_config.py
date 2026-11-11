"""channel_config.py — view and edit the messaging channels' settings from the HUD (G21 · H151/H160).

Every channel the hub wires at start (Telegram, Discord, Slack, email, ntfy, SMS) reads its
settings from the environment. Before this, changing one meant editing ``.env``. The HUD's
Channels panel now edits the same names, in two kinds:

* **Secrets** (bot tokens, app tokens, mail passwords, the ntfy token and topics, the Twilio
  auth token) go only through :mod:`agents.core.integration_keys`: the hub's encrypted
  secret store under the broker-internal ``integration.`` prefix, placed in the process
  environment for the next read and again at the next start (``apply_stored``). A secret
  never comes back out: the view says only whether it is set and where (``env`` / ``hub`` /
  ``managed``) — not even the last characters.
* **Plain settings** (hosts, ports, user names, allowlists, switches) go to the settings
  database as one json setting, ``channels.config`` (``{NAME: value}``), and are placed
  in the environment by :func:`apply_stored` at start, right after the integration keys.
  Every value is validated by its field's kind before anything is written.

Both kinds follow the Integrations panel's rules: a name the environment already sets
(``.env`` or the process, either spelling) belongs to it and is refused here (``.env``
wins, :class:`EnvOwned`); a name the administrator pinned in the managed layer, or any
write while managed mode is on or the managed files cannot be read, is refused
(``managed_scope.ManagedRefused`` → 409, the settings write is checked by
``settings_db.put_category`` and every name by ``managed_scope.check_env_write``).

**A secret is bound to its server** (review M1): the ntfy token and topics to the ntfy
URL, ``SMTP_PASS`` to the SMTP host and port, ``IMAP_PASS`` to the IMAP host and port
(:data:`ENDPOINTS`). Changing one of those endpoint values here — setting it for the first
time included — clears the stored secret, so it must be typed again for the new server; it
is refused (``BoundSecretInEnv``) while the secret comes from ``.env`` or the
administrator. Each stored secret records a digest of the endpoint values it was entered
for, and :func:`verify_bindings` (at start) withholds one whose endpoint changed any other
way (the generic settings route, an edit of ``.env``). The ntfy URL must be ``https://``
(``http://`` only to a loopback host), and the email channel verifies the mail servers'
certificates (``channels/email.py``).

Channels are wired once, at start, so a change applies at the next restart (the view
says ``restart_required``); the SMS channel reads its account, numbers and token on every
request, so those apply now. Only the names listed in :data:`CHANNELS` can be set.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

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
#: secrets stored here but withheld at start: their endpoint changed since they were entered.
_WITHHELD: set[str] = set()
BIND_PREFIX = "integration.bind."

#: G21 review M1 — a secret is bound to the endpoint it was entered for. Changing one of
#: these endpoint values clears the stored secret (it must be typed again for the new
#: host), refuses while the secret comes from ``.env``, and a stored secret whose endpoint
#: changed some other way (the generic settings route, ``.env``) is withheld at start.
ENDPOINTS: dict[str, tuple[str, ...]] = {
    "NTFY_TOKEN": ("NTFY_URL", "NTFY_SERVER_URL"),
    "NTFY_TOPIC": ("NTFY_URL", "NTFY_SERVER_URL"),
    "NTFY_PUBLISH_TOPIC": ("NTFY_URL", "NTFY_SERVER_URL"),
    "SMTP_PASS": ("SMTP_HOST", "SMTP_PORT"),
    "IMAP_PASS": ("IMAP_HOST", "IMAP_PORT"),
}


class BoundSecretInEnv(Exception):
    """An endpoint change while its bound secret comes from ``.env`` (or the administrator):
    the secret cannot be cleared here, so the endpoint may not move away from it."""

    def __init__(self, endpoint: str, secret: str) -> None:
        super().__init__(f"{endpoint} cannot change here while {secret} is set in .env (or by the "
                         f"administrator): it would be sent to the new host. Change both in .env.")
        self.endpoint = endpoint
        self.secret = secret


class EnvOwned(Exception):
    """The environment (process or ``.env``) sets this name: it is edited there."""


class InvalidValue(ValueError):
    """A value its field's kind does not accept; ``reason`` names the field, never the value."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"          # text | host | port | url | bool | int_list | phone | phone_list
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
    Channel("discord", "Discord", (
        Field("DISCORD_BOT_TOKEN", "Bot token", secret=True),
    )),
    Channel("slack", "Slack", (
        Field("SLACK_BOT_TOKEN", "Bot token (xoxb-…)", secret=True),
        Field("SLACK_APP_TOKEN", "App-level token (xapp-…, Socket Mode)", secret=True),
    )),
    Channel("email", "Email", (
        Field("SMTP_HOST", "SMTP host", "host"),
        Field("SMTP_PORT", "SMTP port", "port"),
        Field("SMTP_USER", "SMTP user"),
        Field("SMTP_PASS", "SMTP password", secret=True),
        Field("IMAP_HOST", "IMAP host", "host"),
        Field("IMAP_PORT", "IMAP port", "port"),
        Field("IMAP_USER", "IMAP user"),
        Field("IMAP_PASS", "IMAP password", secret=True),
    ), "starts when both an SMTP and an IMAP host are set"),
    Channel("ntfy", "ntfy", (
        Field("NTFY_URL", "Server URL (https)", "secure_url"),
        Field("NTFY_TOPIC", "Topic (anyone who knows it can read it)", secret=True),
        Field("NTFY_TOKEN", "Access token", secret=True),
        Field("NTFY_TITLE", "Notification title"),
        Field("NTFY_INBOUND", "Receive messages from the topic", "bool"),
        Field("NTFY_PUBLISH_TOPIC", "Separate publish topic", secret=True),
        Field("NTFY_MARKDOWN", "Send Markdown", "bool"),
    ), "starts when a server URL and a topic are set"),
    Channel("sms", "SMS (Twilio)", (
        Field("JARVIS_SMS_ENABLED", "SMS channel on", "bool"),
        Field("JARVIS_SMS_ACCOUNT_SID", "Twilio account SID", now=True),
        Field("JARVIS_SMS_AUTH_TOKEN", "Twilio auth token", secret=True, now=True),
        Field("JARVIS_SMS_FROM_NUMBER", "Twilio number (E.164)", "phone", now=True),
        Field("JARVIS_SMS_ALLOWED_NUMBERS", "Your numbers (E.164)", "phone_list", now=True),
        Field("JARVIS_SMS_WEBHOOK_URL", "Public webhook URL", "url", now=True),
    ), "every reply waits for your approval; see docs/SMS_SETUP.md"),
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

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_PHONE = re.compile(r"^\+[1-9][0-9]{6,14}$")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _plain_text(value: str) -> str:
    if len(value) > MAX_TEXT or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidValue("text")
    return value


def normalise(field: Field, value: Any) -> str:
    """The environment string for *value*, or :class:`InvalidValue`."""
    if field.kind == "bool":
        if isinstance(value, bool):
            return "1" if value else "0"
        text = str(value).strip().lower()
        if text in _TRUE:
            return "1"
        if text in _FALSE:
            return "0"
        raise InvalidValue(field.name)
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise InvalidValue(field.name)
    text = _plain_text(str(value).strip())
    if field.kind == "text":
        return text
    if field.kind == "host":
        try:
            ipaddress.ip_address(text)
            return text
        except ValueError:
            pass
        if not _HOST.match(text):
            raise InvalidValue(field.name)
        return text
    if field.kind == "port":
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            raise InvalidValue(field.name)
        return str(int(text))
    if field.kind == "secure_url":
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        loopback = host == "localhost"
        with contextlib.suppress(ValueError):
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        if (not host or parts.username or parts.password
                or not (parts.scheme == "https" or (parts.scheme == "http" and loopback))):
            raise InvalidValue(field.name)
        return text
    if field.kind == "url":
        parts = urlsplit(text)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise InvalidValue(field.name)
        return text
    if field.kind in {"int_list", "phone_list"}:
        items = [p.strip() for p in text.split(",") if p.strip()]
        if len(items) > MAX_LIST:
            raise InvalidValue(field.name)
        check = (lambda p: re.fullmatch(r"-?[0-9]{1,20}", p)) if field.kind == "int_list" else _PHONE.match
        if not all(check(p) for p in items):
            raise InvalidValue(field.name)
        return ",".join(items)
    if field.kind == "phone":
        if not _PHONE.match(text):
            raise InvalidValue(field.name)
        return text
    raise InvalidValue(field.name)  # pragma: no cover — every kind is handled above


# ── where a value comes from ───────────────────────────────────────────────────

def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spellings(name: str) -> tuple[str, ...]:
    from agents.core.env_config import other_spelling

    other = other_spelling(name)
    return (name,) if other is None else (name, other)


def _placed_here(name: str) -> bool:
    digest = _PLACED.get(name)
    value = os.environ.get(name)
    return digest is not None and value is not None and _digest(value) == digest


def plain_env_owned(name: str) -> bool:
    """True when the environment sets *name* (either spelling) and this module did not."""
    for spelling in _spellings(name):
        value = os.environ.get(spelling)
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
        value = os.environ.get(spelling)
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
            "editable": source in (None, "hub"), "needs_reentry": field.name in _WITHHELD}


def _effective(name: str) -> str:
    for spelling in _spellings(name):
        value = os.environ.get(spelling)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _endpoint_digest(secret: str) -> str:
    joined = "\x00".join(f"{n}={_effective(n)}" for n in ENDPOINTS.get(secret, ()))
    return _digest(joined)


def _record_binding(secret: str) -> None:
    from agents.core import integration_keys

    if secret in ENDPOINTS:
        integration_keys._store().set(BIND_PREFIX + secret, _endpoint_digest(secret))


def _drop_binding(secret: str) -> None:
    from agents.core import integration_keys

    if secret in ENDPOINTS and integration_keys._store_path().exists():
        integration_keys._store().delete(BIND_PREFIX + secret)


def verify_bindings() -> list[str]:
    """Withhold (take out of the environment) every stored secret whose endpoint is not the
    one it was entered for. Returns the names withheld. Called at start."""
    from agents.core import integration_keys

    if not integration_keys._store_path().exists():
        return []
    withheld = []
    store = integration_keys._store()
    for secret in ENDPOINTS:
        if not integration_keys.placed_here(secret):
            continue
        try:
            recorded = store.get(BIND_PREFIX + secret)
        except Exception:  # noqa: BLE001 — an unreadable record withholds, the safe side
            recorded = None
        if recorded != _endpoint_digest(secret):
            os.environ.pop(secret, None)
            integration_keys._PLACED.pop(secret, None)
            _WITHHELD.add(secret)
            withheld.append(secret)
            logger.warning("channel secret %s withheld: its server changed since it was entered; "
                           "enter it again in the Channels panel", secret)
    return withheld


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
    from agents.core import integration_keys

    to_clear: list[str] = []
    for secret, endpoints in ENDPOINTS.items():
        moved = [n for n in endpoints if n in planned and (planned[n] or "") != _effective(n)]
        if not moved:
            continue
        state = integration_keys.status(secret)
        if state.get("set") and state.get("source") in ("env", "managed"):
            raise BoundSecretInEnv(moved[0], secret)
        if integration_keys.stored_copy(secret) or state.get("set"):
            to_clear.append(secret)
    for secret in to_clear:          # first: a failed settings write must not keep the pairing
        integration_keys.clear_key(secret, allowed=secret_names())
        _drop_binding(secret)
        _WITHHELD.discard(secret)
        _CHANGED.add(secret)
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
    return {"written": sorted(planned), "cleared_secrets": sorted(to_clear)}


def set_secret(channel_id: str, name: str, value: str) -> dict:
    """Store a channel secret through the integration-key store (encrypted, never echoed)."""
    from agents.core import integration_keys

    ch = channel(channel_id)
    field = ch.field(name) if ch is not None else None
    if field is None or not field.secret:
        raise KeyError(name)
    try:
        integration_keys.set_key(name, value, allowed=secret_names(), owner=f"channel.{channel_id}")
    except integration_keys.EnvManaged:
        raise EnvOwned(name) from None
    _record_binding(name)
    _WITHHELD.discard(name)
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
    try:
        integration_keys.clear_key(name, allowed=secret_names())
    except integration_keys.EnvManaged:
        raise EnvOwned(name) from None
    _drop_binding(name)
    _WITHHELD.discard(name)
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
    verify_bindings()
    return applied


def reset_for_tests() -> None:
    with _LOCK:
        for name in list(_PLACED):
            if _placed_here(name):
                os.environ.pop(name, None)
        _PLACED.clear()
        _CHANGED.clear()
        _WITHHELD.clear()


__all__ = ["CHANNELS", "ENDPOINTS", "BoundSecretInEnv", "EnvOwned", "InvalidValue", "apply_stored", "channel", "clear_secret", "listing",
           "normalise", "plain_names", "secret_names", "set_plain", "set_secret", "stored_plain", "verify_bindings"]
