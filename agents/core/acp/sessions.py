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
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("jarvis.acp")

#: A session whose lease was not renewed for this long is reaped (its MCP children killed).
LEASE_SECONDS = 5 * 60
#: How often the hub's timer looks for expired leases.
REAP_INTERVAL_SECONDS = 60
MAX_SESSIONS = 64
MAX_SERVERS_PER_SESSION = 8
PREFIX = "acp_"


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


def register(session_id: str, cwd: Path) -> AcpSession:
    now = time.monotonic()
    with _LOCK:
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
    """The folder a turn of *session_id* is bound to (and a renewal of its lease)."""
    if not isinstance(session_id, str) or not session_id.startswith(PREFIX):
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


def _reset_for_tests() -> None:
    with _LOCK:
        _SESSIONS.clear()


__all__ = ["AcpSession", "LEASE_SECONDS", "PREFIX", "REAP_INTERVAL_SECONDS", "add_server", "close", "count",
           "cwd_for", "expired", "get", "new_session_id", "pop", "register", "renew", "server_name"]
