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

A session the editor never closed (a killed process) is reaped after
:data:`IDLE_SECONDS` without a turn, the next time any editor opens or closes one.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

#: An editor conversation with no turn for this long is closed at the next reap.
IDLE_SECONDS = 12 * 3600
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


def cwd_for(session_id: object) -> Path | None:
    """The folder a turn of *session_id* is bound to (and a touch of its idle clock)."""
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


def idle(now: float | None = None) -> list[str]:
    """Session ids idle past :data:`IDLE_SECONDS`."""
    moment = time.monotonic() if now is None else now
    with _LOCK:
        return [sid for sid, record in _SESSIONS.items() if moment - record.seen > IDLE_SECONDS]


def server_name(session_id: str, name: str) -> str:
    """The hub-wide name of a session's server: unique per session, legal for the MCP
    manager's name rule (letters, digits, - and _, at most 64)."""
    return f"acp_{session_id[len(PREFIX):len(PREFIX) + 8]}_{name}"[:64]


async def close(session_id: str, manager) -> list[str]:
    """Forget the session and remove every MCP server it owned. Returns their names."""
    record = pop(session_id)
    if record is None:
        return []
    removed = []
    for name in record.mcp:
        server = getattr(manager, "servers", {}).get(name) if manager is not None else None
        if server is not None and getattr(server, "session_scope", None) == session_id:
            try:
                await manager.remove_server(name)
            finally:
                removed.append(name)
    return removed


def _reset_for_tests() -> None:
    with _LOCK:
        _SESSIONS.clear()


__all__ = ["AcpSession", "IDLE_SECONDS", "PREFIX", "add_server", "close", "cwd_for", "get", "idle",
           "new_session_id", "pop", "register", "server_name"]
