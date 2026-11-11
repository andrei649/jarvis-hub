"""G11 — the hub routes behind ``nerva acp`` (an editor's coding agent over ACP).

Three routes, all admin-guarded (the owner's credential, the same one that adds an MCP
server or decides an approval card):

* ``POST /api/acp/sessions`` — open a conversation of its own for an editor folder. The
  folder must be an existing directory inside the owner's file roots; the conversation's
  turns then bind their file tools and project files to it. The HUD's shared conversation
  is never switched.
* ``POST /api/acp/sessions/{id}/mcp`` — register an MCP server the editor handed over,
  for this conversation only (H545). The ACP process calls it only after the owner
  accepted the server in the editor; it goes through the same refusals as any added
  server (safe mode, a managed pin on ``mcp.servers``), its trust tier is ``read-only``
  unless ``JARVIS_ACP_MCP_TRUST=full``, it is never saved, and its tools are offered to
  this conversation's turns only.
* ``DELETE /api/acp/sessions/{id}`` — the editor closed the session: its MCP servers are
  removed and the binding forgotten.

Turns themselves go through ``POST /chat/stream`` and approvals through the autonomy
decision routes, unchanged: this router adds no second agent path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.core.acp import sessions as acp_sessions
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.acp")

router = APIRouter(tags=["acp"])

_SESSION_ID = r"^acp_[0-9a-f]{24}$"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
#: How long the route waits for a session server's first connect before answering; a
#: slower one keeps connecting and its tools join the offer at a later turn.
CONNECT_WAIT_SECONDS = 15.0


class AcpSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cwd: str = Field(min_length=1, max_length=4096)


class AcpMcpBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    command: str = Field(min_length=1, max_length=4096)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict, max_length=32)


def _editor_folder(raw: str) -> tuple[Path | None, str | None]:
    """The folder resolved, or a refusal word. Inside the owner's file roots only."""
    if "\x00" in raw:
        return None, "invalid_cwd"
    path = Path(raw)
    if not path.is_absolute():
        return None, "cwd_not_absolute"
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "cwd_missing"
    if not resolved.is_dir():
        return None, "cwd_not_a_directory"
    from agents.core.file_tools import FileScope

    try:
        inside = FileScope.from_env().root_for(resolved) is not None
    except Exception:
        inside = False
    if not inside:
        return None, "cwd_outside_file_roots"
    return resolved, None


async def _open_conversation(orch, session_id: str) -> None:
    """A durable conversation for the editor, created without moving the hub's current
    one (the HUD's): the memory manager makes the session and its history identity, and
    the previous current session is put back under the conversation's own lock."""
    memory = orch.memory
    conversation = memory.conversation
    previous = conversation.current_session_id
    sid = await memory.new_session(session_id)
    async with conversation._lock:
        if conversation.current_session_id == sid:
            conversation.current_session_id = previous
    if getattr(conversation, "persist", False):
        await asyncio.to_thread(conversation._save_snapshot, sid)


async def _reap(orch) -> None:
    for session_id in acp_sessions.idle():
        removed = await acp_sessions.close(session_id, getattr(orch, "mcp", None))
        logger.info("idle editor session closed; %d MCP server(s) removed", len(removed))


@router.post("/api/acp/sessions", dependencies=[Depends(admin_guard)])
async def acp_open_session(body: AcpSessionBody):
    """Open a conversation for an editor folder (``session/new``)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    await _reap(orch)
    folder, refusal = await asyncio.to_thread(_editor_folder, body.cwd)
    if refusal is not None:
        return JSONResponse({"error": refusal}, status_code=409 if refusal == "cwd_outside_file_roots" else 400)
    session_id = acp_sessions.new_session_id()
    try:
        await _open_conversation(orch, session_id)
        acp_sessions.register(session_id, folder)
    except OverflowError:
        return JSONResponse({"error": "too_many_sessions"}, status_code=429)
    except Exception:
        logger.warning("editor conversation could not be opened", exc_info=True)
        return JSONResponse({"error": "session_unavailable"}, status_code=503)
    return nocache_json({"ok": True, "session_id": session_id, "cwd": str(folder)})


@router.post("/api/acp/sessions/{session_id}/mcp", dependencies=[Depends(admin_guard)])
async def acp_add_session_mcp(session_id: str, body: AcpMcpBody):
    """Register an editor-supplied MCP server for this conversation only (H545)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if re.fullmatch(_SESSION_ID, session_id) is None:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    record = acp_sessions.get(session_id)
    if record is None:
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    from agents.core.routers.mcp import _managed_refusal, _safe_mode_refusal

    refusal = _safe_mode_refusal() or await _managed_refusal()
    if refusal is not None:
        return refusal
    if any(not _ENV_NAME.fullmatch(k) or "\x00" in v or len(v) > 4096 for k, v in body.env.items()) \
            or any("\x00" in a or len(a) > 4096 for a in body.args) or "\x00" in body.command:
        return JSONResponse({"error": "invalid_server"}, status_code=400)
    from agents.core.env_config import env_str
    from agents.core.mcp.client import TRUST_READ_ONLY, MCPServer, normalize_trust

    trust = normalize_trust(env_str("JARVIS_ACP_MCP_TRUST", TRUST_READ_ONLY).strip() or TRUST_READ_ONLY)
    trust = trust or TRUST_READ_ONLY            # an unknown spelling is read-only, never wider
    name = acp_sessions.server_name(session_id, body.name)
    if name in orch.mcp.servers:
        return JSONResponse({"error": "server_exists"}, status_code=409)
    server = MCPServer(name=name, transport="stdio",
                       command=shlex.join([body.command, *body.args]),
                       cwd=str(record.cwd), env=dict(body.env), trust=trust)
    server.session_scope = session_id
    if server._command_argv() is None:
        return JSONResponse({"error": "command_refused",
                             "message": "the command holds shell metacharacters or does not parse"},
                            status_code=400)
    try:
        acp_sessions.add_server(session_id, name)
    except (KeyError, OverflowError):
        return JSONResponse({"error": "too_many_servers"}, status_code=429)
    manager = orch.mcp
    if callable(getattr(type(manager), "register", None)):
        manager.register(server)
    else:
        manager.servers[name] = server
    server.wanted = True          # the supervisor retries it while the session lives
    try:
        connected = await asyncio.wait_for(manager.connect_server(name), CONNECT_WAIT_SECONDS)
    except TimeoutError:
        connected = False
    except Exception:
        logger.warning("editor MCP server did not connect", exc_info=True)
        connected = False
    tools = [tool.name for tool in server.all_tools()] if connected else []
    return nocache_json({"ok": True, "server": name, "connected": bool(connected), "trust": trust,
                         "tools": tools[:200], "error": None if connected else server.last_error})


@router.delete("/api/acp/sessions/{session_id}", dependencies=[Depends(admin_guard)])
async def acp_close_session(session_id: str):
    """The editor closed the session: remove its MCP servers, forget its folder."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if re.fullmatch(_SESSION_ID, session_id) is None:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    removed = await acp_sessions.close(session_id, getattr(orch, "mcp", None))
    await _reap(orch)
    return nocache_json({"ok": True, "removed": removed})
