"""Process-local, single-use owner confirmation for saved MCP configuration rereads.

The cache carries only hashes, identities and expiry. Effective saved rows are read
again for confirmation and before each awaited manager effect; no secret-bearing
configuration or candidate plan is retained here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Any

from . import load_set, settings_db

TTL_SECONDS = 120
MAX_PROPOSALS = 64
MAX_SAVED_SERVERS = 256
_lock = threading.Lock()
_proposals: dict[tuple[str, str | None, str | None, str], Proposal] = {}


class SavedConfigUnavailable(ValueError):
    """Effective saved MCP policy could not be read and validated."""


@dataclass(frozen=True)
class SavedRead:
    allowed_rows: list[dict]
    held_rows: list[dict]
    settings_digest: str
    boot_digest: str
    live_loadset_digest: str
    snapshot_id: int


@dataclass(frozen=True)
class Proposal:
    actor: tuple[str, str | None, str | None, str]
    manager_ref: weakref.ReferenceType
    nonce_digest: str
    fingerprint: str
    settings_digest: str
    boot_digest: str
    live_loadset_digest: str
    snapshot_id: int
    expires_at: float


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _snapshot(manager: Any) -> tuple[dict[str, tuple[str, ...]], int]:
    raw = getattr(manager, "saved_reload_load_set", None)
    if not isinstance(raw, dict) or set(raw) != {"disabled", "only"}:
        raise SavedConfigUnavailable("boot load set unavailable")
    result = {}
    for key in ("disabled", "only"):
        names = raw[key]
        if (not isinstance(names, (list, tuple)) or len(names) > load_set.MAX_NAMES
                or any(type(name) is not str for name in names)):
            raise SavedConfigUnavailable("boot load set malformed")
        parsed = tuple(load_set.parse_names(names))
        if parsed != tuple(names):
            raise SavedConfigUnavailable("boot load set malformed")
        result[key] = parsed
    return result, id(raw)


def _live_lists(rows: list[dict]) -> dict[str, tuple[str, ...]]:
    values: dict[str, Any] = {}
    for row in rows:
        key = row.get("key")
        if key in {"mcp_disabled", "mcp_only"}:
            if key in values:
                raise SavedConfigUnavailable("duplicate load set key")
            values[key] = row.get("value")
    if set(values) != {"mcp_disabled", "mcp_only"}:
        raise SavedConfigUnavailable("load set incomplete")
    if any(not isinstance(raw, (str, list, tuple)) for raw in values.values()):
        raise SavedConfigUnavailable("load set malformed")
    return {"disabled": tuple(load_set.parse_names(values["mcp_disabled"])),
            "only": tuple(load_set.parse_names(values["mcp_only"]))}


def _read_saved_config(manager: Any) -> SavedRead:
    """Strict synchronous read; async callers run it off the event loop."""
    settings_db.ensure_initialized()
    settings_db._require_readable_store()
    boot, snapshot_id = _snapshot(manager)
    mcp_rows = settings_db.get_category("mcp")
    matches = [row.get("value") for row in mcp_rows if row.get("key") == "servers"]
    if len(matches) != 1 or type(matches[0]) is not list or len(matches[0]) > MAX_SAVED_SERVERS:
        raise SavedConfigUnavailable("saved MCP server list unavailable")
    configs = matches[0]
    names: set[str] = set()
    for row in configs:
        if type(row) is not dict:
            raise SavedConfigUnavailable("saved MCP entry malformed")
        name = row.get("name")
        if (type(name) is not str or not name.strip() or len(name) > load_set.MAX_NAME_CHARS
                or name in names):
            raise SavedConfigUnavailable("saved MCP name malformed or duplicated")
        names.add(name)
    live = _live_lists(settings_db.get_category("loadset"))
    allowed = [row for row in configs if load_set.permits("mcp", row["name"], lists=boot)]
    held = [row for row in configs if not load_set.permits("mcp", row["name"], lists=boot)]
    again, again_id = _snapshot(manager)
    if again_id != snapshot_id or again != boot:
        raise SavedConfigUnavailable("boot load set changed during read")
    return SavedRead(allowed, held, _digest(configs), _digest(boot), _digest(live), snapshot_id)


def actor_for(principal: Any) -> tuple[str, str | None, str | None, str] | None:
    if not getattr(principal, "admin", False):
        return None
    channel, sender, chat, scope = (getattr(principal, key, None)
                                    for key in ("channel", "sender", "chat", "scope"))
    if channel not in {"web", "telegram", "discord", "slack", "matrix"} or scope not in {"dm", "group"}:
        return None
    if any(value is not None and (type(value) is not str or not value or len(value) > 256)
           for value in (sender, chat)):
        return None
    if channel != "web" and sender is None:
        return None
    if scope == "group" and chat is None:
        return None
    return channel, sender, chat, scope


def issue(actor: tuple[str, str | None, str | None, str], manager: Any,
          read: SavedRead, fingerprint: str) -> str | None:
    nonce = secrets.token_urlsafe(18)
    proposal = Proposal(actor, weakref.ref(manager), _digest(nonce), fingerprint,
                        read.settings_digest, read.boot_digest, read.live_loadset_digest,
                        read.snapshot_id, time.monotonic() + TTL_SECONDS)
    with _lock:
        now = time.monotonic()
        for key, existing in list(_proposals.items()):
            if existing.expires_at <= now or existing.manager_ref() is None:
                _proposals.pop(key, None)
        if actor not in _proposals and len(_proposals) >= MAX_PROPOSALS:
            return None
        _proposals[actor] = proposal
    return nonce


def consume(actor: tuple[str, str | None, str | None, str], nonce: str) -> Proposal | None:
    with _lock:
        proposal = _proposals.pop(actor, None)
    if (proposal is None or proposal.expires_at <= time.monotonic()
            or not hmac.compare_digest(proposal.nonce_digest, _digest(nonce))):
        return None
    return proposal


def cancel(actor: tuple[str, str | None, str | None, str]) -> bool:
    with _lock:
        return _proposals.pop(actor, None) is not None


def matches(proposal: Proposal, actor: tuple[str, str | None, str | None, str],
            manager: Any, read: SavedRead, fingerprint: str) -> bool:
    return (proposal.actor == actor and proposal.manager_ref() is manager
            and proposal.expires_at > time.monotonic()
            and proposal.fingerprint == fingerprint
            and proposal.settings_digest == read.settings_digest
            and proposal.boot_digest == read.boot_digest
            and proposal.live_loadset_digest == read.live_loadset_digest
            and proposal.snapshot_id == read.snapshot_id)
