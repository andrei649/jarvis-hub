"""H496 — keep one identity's credentials out of another identity's turn.

Every credential the hub holds belongs to one identity. Today there are two kinds of
holder: **the owner** (provider keys, the Integrations panel's keys, MCP servers' OAuth
tokens and secrets, a skill's setup values, the secret broker's handles, the configured
web-search backends) and **the Workspace organisation** (its SMTP password, in its own
store under ``<data>/business/secrets.enc``, never read by a hub turn). Guests — a
non-admin HUD token, a paired chat-channel sender who is not the owner, a non-owner
OpenAI-API key, the embedded widget — hold none.

A turn's credentials are resolved through the turn's principal, never through the
process: :func:`turn_identity` places the bound principal and action origin with the
same classifier the tool offer uses (``tool_profiles.classify_turn``), and every seam
that is about to put an owner credential on the wire asks :func:`check` first:

=========================  ===========================================================
``provider:<id>``          a cloud model route (``llm/data_handling.authorize``); a
                           loopback route uses no credential and is never refused
``mcp:<server>``           a bridged MCP tool call (``mcp/model_bridge``); a server an
                           editor handed over for one conversation is that
                           conversation's own and keeps its visibility rule (G11)
``web_search:<backend>``   a keyed web-search backend (``plugins/websearch``); the
                           keyless DuckDuckGo fallback holds no credential
``skill:<name>``           a skill command run with its stored setup values (H342)
``secret:<name>``          a ``{{secret:NAME}}`` handle the broker would inject
=========================  ===========================================================

The rule is the Hermes one made principal-shaped: the scope is **authoritative**. A
guest turn's miss never falls through to the owner's store — it is refused with
:class:`CredentialNotShared` — unless the owner has explicitly shared that one
integration with guests (:func:`share`), which is recorded with who and when in
``<data>/security/credential_shares.json`` and in the security audit log. The owner's
own turns (any surface) and turns with no human in them (heartbeats, jobs, workflows:
the ``system`` principal) use the owner's credentials as before. Anything the
classifier cannot place is a guest; an unreadable share ledger shares nothing.

What was already in place and is not repeated here: guest turns get no plugin data, no
core memory and no long-term recall (G12); gated tools are never offered to a guest
(``tool_profiles``); an ``execute_code`` interpreter receives declared environment
names only for an owner principal (H595 ``code_env``); a skill's stored values never
reach an interpreter (H342).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.security.credential_scope")

IDENTITY_OWNER = "owner"
IDENTITY_GUEST = "guest"
IDENTITY_SYSTEM = "system"

KIND_PROVIDER = "provider"
KIND_MCP = "mcp"
KIND_WEB_SEARCH = "web_search"
KIND_SKILL = "skill"
KIND_SECRET = "secret"  # nosec B105 - a credential kind label, not a credential
KINDS: tuple[str, ...] = (KIND_PROVIDER, KIND_MCP, KIND_WEB_SEARCH, KIND_SKILL, KIND_SECRET)
REASON = "credential_not_shared"
MAX_SHARES = 256
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_LOCK = threading.Lock()
_WRITE_LOCK = threading.Lock()
_override_path: Path | None = None
_cache: dict[str, Any] = {"key": None, "shares": {}}


class CredentialNotShared(PermissionError):
    """A guest turn asked for a credential the owner has not shared with guests."""

    def __init__(self, integration: str):
        self.integration = integration
        self.reason = REASON
        super().__init__(f"{REASON}: {integration}")


@dataclass(frozen=True)
class TurnIdentity:
    kind: str          # owner | guest | system
    channel: str
    sender: str | None

    @property
    def is_guest(self) -> bool:
        return self.kind == IDENTITY_GUEST


def integration_key(kind: str, name: str) -> str:
    """``kind:name`` after validation (``ValueError`` on an unknown kind or bad name)."""
    if kind not in KINDS:
        raise ValueError(f"unknown credential kind {kind!r}")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("credential name must be 1-128 characters [A-Za-z0-9._:/-]")
    return f"{kind}:{name}"


def parse_integration(text: str) -> tuple[str, str]:
    kind, sep, name = str(text or "").partition(":")
    if not sep:
        raise ValueError("integration must be '<kind>:<name>'")
    integration_key(kind, name)
    return kind, name


#: The hub machine's own voice pipeline (wake word -> STT on the host microphone,
#: ``channels/voice.VoiceChannel``) binds ``Principal(channel="voice")`` with no sender.
LOCAL_VOICE_CHANNEL = "voice"


def _local_voice(principal: Any, origin: str | None) -> bool:
    """Review M2: the local voice pipeline speaks for the owner, for credentials only.

    ``Orchestrator._channel_principal`` marks no voice turn admin (the tool posture keeps
    operator/guest for the room microphone: anyone near it is heard), but the owner's
    provider keys, search backends and MCP servers were always used for it before H496, and
    it is the owner's own machine. So credentials treat it as the owner. Only the local
    pipeline: channel ``voice``, no sender (the pipeline names none), and not an inbound
    turn. A voice note arriving through a chat channel keeps that channel's principal
    (``telegram`` etc.) and is judged as that sender."""
    from agents.core.action_origin import INBOUND_ACTION_ORIGIN

    channel = str(getattr(principal, "channel", "") or "").strip().lower()
    return (channel == LOCAL_VOICE_CHANNEL and getattr(principal, "sender", None) is None
            and str(origin or "").strip().lower() != INBOUND_ACTION_ORIGIN)


def turn_identity(principal: Any = None, origin: str | None = None) -> TurnIdentity:
    """Who this turn speaks for, from the bound principal and the action origin.

    Reads the current turn when *principal*/*origin* are not given. A classifier error
    reads as a guest (fail closed)."""
    try:
        from agents.core.action_origin import current_action_origin
        from agents.core.tool_profiles import (
            PRINCIPAL_GUEST,
            PRINCIPAL_OWNER,
            classify_turn,
        )

        if principal is None:
            from agents.core.orchestrator import _turn_principal
            principal = _turn_principal.get()
        origin_text = current_action_origin() if origin is None else origin
        if _local_voice(principal, origin_text):
            kind = IDENTITY_OWNER
        else:
            posture = classify_turn(principal, origin_text)
            kind = (IDENTITY_OWNER if posture.principal == PRINCIPAL_OWNER
                    else IDENTITY_GUEST if posture.principal == PRINCIPAL_GUEST
                    else IDENTITY_SYSTEM)
    except Exception:
        logger.warning("turn identity unavailable; treated as a guest", exc_info=True)
        kind = IDENTITY_GUEST
    channel = str(getattr(principal, "channel", "") or "unknown")
    sender = getattr(principal, "sender", None)
    return TurnIdentity(kind, channel, str(sender) if sender is not None else None)


# ── the share ledger ─────────────────────────────────────────────────────────

def ledger_path() -> Path:
    if _override_path is not None:
        return _override_path
    from agents.core.paths import data_path
    return data_path("security", "credential_shares.json")


def set_ledger_path_for_tests(path: Path | None) -> None:
    global _override_path
    with _LOCK:
        _override_path = Path(path) if path is not None else None
        _cache.update(key=None, shares={})


def _read() -> dict[str, dict]:
    """The recorded shares; an unreadable or malformed ledger shares nothing."""
    path = ledger_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    except OSError:
        logger.warning("credential share ledger unreadable; nothing is shared")
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        if _cache["key"] == key:
            return dict(_cache["shares"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("shares") if isinstance(raw, dict) else None
        if not isinstance(rows, dict):
            raise ValueError("shares must be an object")
        mac = raw.get("mac")
        if not isinstance(mac, str) or not hmac.compare_digest(mac, _mac(rows)):
            raise ValueError("share ledger integrity check failed")
        shares: dict[str, dict] = {}
        for integration, row in list(rows.items())[:MAX_SHARES]:
            parse_integration(integration)
            if isinstance(row, dict):
                shares[integration] = {k: row[k] for k in ("at", "by", "note") if k in row}
    except Exception:
        logger.warning("credential share ledger malformed or not written by this hub; nothing is shared")
        return {}
    with _LOCK:
        _cache.update(key=key, shares=shares)
    return dict(shares)


def list_shares() -> list[dict]:
    return [{"integration": k, **v} for k, v in sorted(_read().items())]


def is_shared(kind: str, name: str) -> bool:
    try:
        return integration_key(kind, name) in _read()
    except ValueError:
        return False


def _audit(audit: Any, action: str, integration: str, by: str) -> None:
    if audit is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    audit.log(SecurityEvent(event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                            action_taken=action,
                            content_preview=f"H496 {action}: {integration} (by {by})"))


def _default_mac_key() -> bytes:
    from agents.core.secrets import SecretStore

    return SecretStore()._key_b64


#: Where the ledger's MAC key comes from: the hub's protected secret-store key (tests
#: substitute one). A key that cannot be read makes the ledger unreadable: nothing shared.
_mac_key_source = _default_mac_key


def set_mac_key_for_tests(source) -> None:
    global _mac_key_source
    with _LOCK:
        _mac_key_source = source or _default_mac_key
        _cache.update(key=None, shares={})


def _mac(rows: dict) -> str:
    """Nit (review): a ledger edited outside the hub is not honoured. Domain-separated HMAC
    with the hub's secret-store key over the canonical shares."""
    key = hmac.digest(_mac_key_source(), b"nerva:H496:credential-shares:v1", "sha256")
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _write(shares: dict[str, dict]) -> None:
    from agents.core.persistence.json_store import atomic_write_json

    atomic_write_json(ledger_path(), {"version": 2, "shares": shares, "mac": _mac(shares)})
    with _LOCK:
        _cache.update(key=None, shares={})


def share(kind: str, name: str, *, by: str = "owner", note: str = "", audit: Any = None) -> dict:
    """Record that guests may use the owner's credential for this one integration."""
    integration = integration_key(kind, name)
    note = str(note or "")[:200]
    with _WRITE_LOCK:
        shares = _read()
        if integration not in shares and len(shares) >= MAX_SHARES:
            raise ValueError("too many shared integrations")
        # Audit first: a share the audit could not record is not granted.
        _audit(audit, "credential_shared_with_guests", integration, by)
        shares[integration] = {"at": time.time(), "by": str(by)[:64], "note": note}
        _write(shares)
    logger.info("credential %s shared with guests by %s", integration, by)
    return {"integration": integration, "shared": True, **shares[integration]}


def unshare(kind: str, name: str, *, by: str = "owner", audit: Any = None) -> dict:
    integration = integration_key(kind, name)
    with _WRITE_LOCK:
        shares = _read()
        existed = shares.pop(integration, None) is not None
        # Audit first, as for a share: an unshare the audit could not record changes nothing.
        _audit(audit, "credential_unshared", integration, by)
        _write(shares)
    return {"integration": integration, "shared": False, "changed": existed}


# ── the check every credential seam asks ─────────────────────────────────────

def allowed(kind: str, name: str, *, principal: Any = None, origin: str | None = None) -> bool:
    identity = turn_identity(principal, origin)
    if not identity.is_guest:
        return True
    return is_shared(kind, name)


def check(kind: str, name: str, *, principal: Any = None, origin: str | None = None) -> None:
    """Raise :class:`CredentialNotShared` when this turn may not use the credential."""
    if allowed(kind, name, principal=principal, origin=origin):
        return
    try:
        integration = integration_key(kind, name)
    except ValueError:
        integration = f"{kind}:?"
    identity = turn_identity(principal, origin)
    logger.warning("guest turn refused the owner's credential %s (channel=%s)",
                   integration, identity.channel)
    raise CredentialNotShared(integration)


def describe() -> dict:
    """The posture the security page and support bundles show."""
    return {"kinds": list(KINDS), "shares": list_shares(),
            "rule": "guest turns use no owner credential unless the owner shares that integration"}


__all__ = [
    "CredentialNotShared", "IDENTITY_GUEST", "IDENTITY_OWNER", "IDENTITY_SYSTEM", "KINDS",
    "KIND_MCP", "KIND_PROVIDER", "KIND_SECRET", "KIND_SKILL", "KIND_WEB_SEARCH", "REASON",
    "TurnIdentity", "allowed", "check", "describe", "integration_key", "is_shared",
    "list_shares", "parse_integration", "share", "turn_identity", "unshare",
]
