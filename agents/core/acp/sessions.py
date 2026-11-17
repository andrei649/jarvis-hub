"""Hub side of G11: the conversations an editor opened, and what each one owns.

In memory on purpose — an editor session lives exactly as long as the ``nerva acp``
process that opened it, and nothing here may outlive a hub restart:

* ``cwd`` — the editor's folder. It must lie inside the owner's file roots
  (``FileScope``); a turn of this conversation then binds its file tools and its project
  files to that folder (``orchestrator._begin_project_context``, the same seam a
  ``/worktree new`` session uses), so the editor narrows what the tools reach and can
  never widen it.
* ``mcp`` — the names of the MCP servers registered for this conversation only (H545).
  Their tools are offered to this conversation's turns and no other
  (``MCPServer.session_scope``), they are never written to the saved server list, and
  :func:`close` removes them.

**A lease, not trust (G11 review).** ``nerva acp`` renews each session's lease while the
editor is connected (``POST /api/acp/sessions/{id}/lease``, every minute); a turn renews
it too. A session whose lease is older than :data:`LEASE_SECONDS` is reaped by the hub's
timer (``routers/acp.py``), which removes its MCP children. A conversation the hub no
longer holds — reaped, or forgotten by a restart — is **refused** from then on
(``session_continuation.editor_session_closed``, HTTP 410), never run without its folder
binding; ``nerva acp`` then opens a new one and tells the editor.

**The editor's conversation list (H542).** The live registry above is in memory; what
survives a restart is a small owner-only index of the conversations editors opened
(:func:`remember`, ``<memory dir>/acp/editor_sessions.json``): the id, the folder it is
bound to, when it was made and the conversation it was forked from. ``session/list``
reads it, and ``session/load`` / ``session/resume`` / ``session/fork`` may only name a
conversation in it, for the same folder. A conversation in the index is an editor
conversation for good (:func:`is_editor_conversation`): without a live binding it is
refused, never run without its folder — including a fork, whose id is an ordinary
continuation id rather than ``acp_…``.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jarvis.acp")

#: A session whose lease was not renewed for this long is reaped (its MCP children killed).
LEASE_SECONDS = 5 * 60
#: How often the hub's timer looks for expired leases.
REAP_INTERVAL_SECONDS = 60
MAX_SESSIONS = 64
MAX_SERVERS_PER_SESSION = 8
PREFIX = "acp_"
#: Editor conversations the durable index keeps (the oldest are dropped past this).
MAX_INDEX = 500
#: The largest index file read back (a larger one is treated as unreadable, not trusted).
MAX_INDEX_BYTES = 1024 * 1024
#: ``session/list`` page size (the ACP default Hermes uses).
PAGE_SIZE = 50


@dataclass
class AcpSession:
    session_id: str
    cwd: Path
    created: float
    seen: float
    mcp: list[str] = field(default_factory=list)


_LOCK = threading.Lock()
_SESSIONS: dict[str, AcpSession] = {}


def new_session_id() -> str:
    return PREFIX + secrets.token_hex(12)


def register(session_id: str, cwd: Path, *, exclusive: bool = False) -> AcpSession:
    """Bind *session_id* to *cwd*. With *exclusive*, a session already held is refused
    (KeyError) instead of re-bound, so two editors never hold one conversation."""
    now = time.monotonic()
    with _LOCK:
        if exclusive and session_id in _SESSIONS:
            raise KeyError(session_id)
        if len(_SESSIONS) >= MAX_SESSIONS:
            raise OverflowError("too many editor sessions")
        record = AcpSession(session_id, Path(cwd), now, now)
        _SESSIONS[session_id] = record
        return record


def get(session_id: object) -> AcpSession | None:
    if not isinstance(session_id, str):
        return None
    with _LOCK:
        return _SESSIONS.get(session_id)


def count() -> int:
    with _LOCK:
        return len(_SESSIONS)


def renew(session_id: object) -> bool:
    """Renew the lease; False when the hub no longer holds the session."""
    if not isinstance(session_id, str):
        return False
    with _LOCK:
        record = _SESSIONS.get(session_id)
        if record is None:
            return False
        record.seen = time.monotonic()
        return True


def cwd_for(session_id: object) -> Path | None:
    """The folder a turn of *session_id* is bound to (and a renewal of its lease). Only
    editor conversations are in the registry, whatever their id looks like (a fork's id
    is a continuation id)."""
    if not isinstance(session_id, str):
        return None
    with _LOCK:
        record = _SESSIONS.get(session_id)
        if record is None:
            return None
        record.seen = time.monotonic()
        return record.cwd


def add_server(session_id: str, name: str) -> None:
    with _LOCK:
        record = _SESSIONS.get(session_id)
        if record is None:
            raise KeyError(session_id)
        if len(record.mcp) >= MAX_SERVERS_PER_SESSION:
            raise OverflowError("too many MCP servers for this session")
        record.mcp.append(name)


def pop(session_id: str) -> AcpSession | None:
    with _LOCK:
        return _SESSIONS.pop(session_id, None)


def expired(now: float | None = None) -> list[str]:
    """Session ids whose lease is older than :data:`LEASE_SECONDS`."""
    moment = time.monotonic() if now is None else now
    with _LOCK:
        return [sid for sid, record in _SESSIONS.items() if moment - record.seen > LEASE_SECONDS]


#: The earlier name.
idle = expired


def server_name(session_id: str, name: str) -> str:
    """The hub-wide name of a session's server: unique per session, legal for the MCP
    manager's name rule (letters, digits, - and _, at most 64)."""
    return f"acp_{session_id[len(PREFIX):len(PREFIX) + 8]}_{name}"[:64]


async def close(session_id: str, manager) -> list[str]:
    """Forget the session and remove every MCP server it owned. Returns their names. One
    server that fails to close does not keep the others running (each is tried, the
    failures are logged)."""
    record = pop(session_id)
    if record is None:
        return []
    removed = []
    for name in record.mcp:
        server = getattr(manager, "servers", {}).get(name) if manager is not None else None
        if server is None or getattr(server, "session_scope", None) != session_id:
            continue
        try:
            await manager.remove_server(name)
        except Exception:  # noqa: BLE001 - keep closing the rest
            logger.warning("editor MCP server %s did not close cleanly", name, exc_info=True)
            servers = getattr(manager, "servers", None)
            if isinstance(servers, dict):
                servers.pop(name, None)       # never left offered to anyone
        removed.append(name)
    return removed


# ── the durable index (H542: list, load, resume, fork) ──────────────────────

_INDEX_LOCK = threading.Lock()
#: (path, entries) of the index as last read or written by this process.
_INDEX_CACHE: tuple[Path, dict[str, dict]] | None = None


def index_path() -> Path:
    from agents.core.memory import persistence

    return persistence.memory_dir() / "acp" / "editor_sessions.json"


def _valid_entry(sid: object, row: object) -> bool:
    return (isinstance(sid, str) and 0 < len(sid) <= 128 and isinstance(row, dict)
            and isinstance(row.get("cwd"), str) and isinstance(row.get("created"), str)
            and (row.get("parent") is None or isinstance(row.get("parent"), str)))


def _read_index_locked() -> dict[str, dict]:
    global _INDEX_CACHE
    path = index_path()
    if _INDEX_CACHE is not None and _INDEX_CACHE[0] == path:
        return _INDEX_CACHE[1]
    entries: dict[str, dict] = {}
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_INDEX_BYTES + 1)
        document = json.loads(raw) if len(raw) <= MAX_INDEX_BYTES else None
        rows = document.get("sessions") if isinstance(document, dict) else None
        for sid, row in (rows.items() if isinstance(rows, dict) else ()):
            if _valid_entry(sid, row):
                entries[sid] = {"cwd": row["cwd"], "created": row["created"], "parent": row.get("parent")}
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        logger.warning("editor session index unreadable; editor conversations start a new list")
    _INDEX_CACHE = (path, entries)
    return entries


def remember(session_id: str, cwd: Path, *, parent: str | None = None) -> None:
    """Record an editor conversation and its folder in the durable index (owner-only file)."""
    from agents.core.persistence.json_store import atomic_write_json

    global _INDEX_CACHE
    with _INDEX_LOCK:
        entries = dict(_read_index_locked())
        entries[session_id] = {"cwd": str(cwd), "created": datetime.now(UTC).isoformat(timespec="seconds"),
                               "parent": parent}
        if len(entries) > MAX_INDEX:
            for sid in sorted(entries, key=lambda k: entries[k]["created"])[:len(entries) - MAX_INDEX]:
                entries.pop(sid, None)
        path = index_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_json(path, {"schema": 1, "sessions": entries})
        _INDEX_CACHE = (path, entries)


def known(session_id: object) -> dict | None:
    """The index entry of an editor conversation, or None."""
    if not isinstance(session_id, str):
        return None
    with _INDEX_LOCK:
        row = _read_index_locked().get(session_id)
        return dict(row) if row else None


def is_editor_conversation(session_id: object) -> bool:
    """*session_id* names a conversation an editor opened (it is bound to a folder)."""
    return isinstance(session_id, str) and (session_id.startswith(PREFIX) or known(session_id) is not None)


def listing(cwd: Path | None = None, *, offset: int = 0, limit: int = PAGE_SIZE) -> tuple[list[dict], int | None]:
    """A page of the index, newest first, for one folder or all: ``(rows, next_offset)``."""
    with _INDEX_LOCK:
        entries = dict(_read_index_locked())
    rows = [{"session_id": sid, **row} for sid, row in entries.items()
            if cwd is None or row["cwd"] == str(cwd)]
    rows.sort(key=lambda r: (r["created"], r["session_id"]), reverse=True)
    offset = max(0, int(offset))
    limit = max(1, min(PAGE_SIZE, int(limit)))
    page = rows[offset:offset + limit]
    with _LOCK:
        for row in page:
            row["live"] = row["session_id"] in _SESSIONS
    following = offset + limit
    return page, (following if following < len(rows) else None)


def _reset_for_tests() -> None:
    global _INDEX_CACHE
    with _LOCK:
        _SESSIONS.clear()
    with _INDEX_LOCK:
        _INDEX_CACHE = None


__all__ = ["AcpSession", "LEASE_SECONDS", "PAGE_SIZE", "PREFIX", "REAP_INTERVAL_SECONDS", "add_server", "close",
           "count", "cwd_for", "expired", "get", "index_path", "is_editor_conversation", "known", "listing",
           "new_session_id", "pop", "register", "remember", "renew", "server_name"]
