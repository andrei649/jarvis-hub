"""G11 — the hub routes behind ``nerva acp`` (an editor's coding agent over ACP).

Five routes, all admin-guarded (the owner's credential, the same one that adds an MCP
server or decides an approval card):

* ``POST /api/acp/sessions`` — open a conversation of its own for an editor folder. The
  folder must be an existing directory inside the owner's file roots; the conversation's
  turns then bind their file tools and project files to it. The HUD's shared conversation
  is never switched. With ``load`` it binds an earlier editor conversation again
  (``session/load`` and ``session/resume``); with ``fork`` it makes a continuation of one
  (``session/fork``, the hub's own ``create_continuation``, so the copy stands as its
  source does). Either may only name a conversation an editor opened for **the same
  folder**, and ``load`` one no other editor holds open (H542).
* ``GET /api/acp/sessions`` — the editor conversations, newest first, 50 a page, for one
  folder or all (``session/list``).
* ``POST /api/acp/sessions/{id}/mcp`` — register an MCP server the editor handed over,
  for this conversation only (H545). The ACP process calls it only after the owner
  accepted the server in the editor; it goes through the same refusals as any added
  server (safe mode, a managed pin on ``mcp.servers``), its trust tier is ``read-only``
  unless ``JARVIS_ACP_MCP_TRUST=full``, it is never saved, and its tools are offered to
  this conversation's turns only.
* Every route below takes the binding's holder token (``X-ACP-Holder``, from the open,
  load or fork answer): an editor that lost the conversation to another cannot renew,
  close or extend it.
* ``POST /api/acp/sessions/{id}/lease`` — ``nerva acp`` renews the session's lease every
  minute while the editor is connected. A lease older than five minutes is reaped by a timer
  here (its MCP servers removed); 410 tells the editor the hub no longer holds the session.
* ``DELETE /api/acp/sessions/{id}`` — the editor closed the session: its MCP servers are
  removed and the binding forgotten.

A conversation the hub no longer holds (reaped, or forgotten by a restart) is refused by
``prepare_session`` with 410 ``editor_session_closed``, never run without its folder.

Turns themselves go through ``POST /chat/stream`` and approvals through the autonomy
decision routes, unchanged: this router adds no second agent path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from pathlib import Path

from fastapi import APIRouter, Depends, Header
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


_ANY_SESSION = r"^[A-Za-z0-9_-]{1,128}$"


class AcpSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cwd: str = Field(min_length=1, max_length=4096)
    #: Bind this earlier editor conversation again (session/load, session/resume).
    load: str | None = Field(default=None, pattern=_ANY_SESSION)
    #: Continue this editor conversation in a new one (session/fork).
    fork: str | None = Field(default=None, pattern=_ANY_SESSION)


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


_REAPER: asyncio.Task | None = None


def _ensure_reaper(orch) -> None:
    """G11 review: expired leases are reaped on a timer, not only when another editor
    opens or closes a session. The task runs while any editor session is open."""
    global _REAPER
    if _REAPER is not None and not _REAPER.done():
        return

    async def loop() -> None:
        while acp_sessions.count():
            await asyncio.sleep(acp_sessions.REAP_INTERVAL_SECONDS)
            try:
                await _reap(orch)
            except Exception:
                logger.warning("editor session reap failed", exc_info=True)

    _REAPER = asyncio.ensure_future(loop())


async def _reap(orch) -> None:
    for session_id in acp_sessions.expired():
        removed = await acp_sessions.close(session_id, getattr(orch, "mcp", None))
        logger.info("editor session lease expired; %d MCP server(s) removed", len(removed))


@router.post("/api/acp/sessions", dependencies=[Depends(admin_guard)])
async def acp_open_session(body: AcpSessionBody):
    """Open a conversation for an editor folder (``session/new``), bind an earlier one again
    (``load``: ``session/load`` / ``session/resume``) or continue one in a new conversation
    (``fork``: ``session/fork``)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if body.load is not None and body.fork is not None:
        return JSONResponse({"error": "load_or_fork"}, status_code=400)
    await _reap(orch)
    folder, refusal = await asyncio.to_thread(_editor_folder, body.cwd)
    if refusal is not None:
        return JSONResponse({"error": refusal}, status_code=409 if refusal == "cwd_outside_file_roots" else 400)
    earlier = body.load or body.fork
    if earlier is not None:
        entry = await asyncio.to_thread(acp_sessions.known, earlier)
        if entry is None:
            return JSONResponse({"error": "session_not_found"}, status_code=404)
        if entry["cwd"] != str(folder):
            # An editor conversation stays with the folder it was made for.
            return JSONResponse({"error": "cwd_mismatch"}, status_code=409)
    if body.load is not None:
        return await _load(orch, body.load, folder)
    if body.fork is not None:
        return await _fork(orch, body.fork, folder)
    session_id = acp_sessions.new_session_id()
    try:
        # Registered first: a full registry refuses before any conversation is made.
        record = acp_sessions.register(session_id, folder)
    except OverflowError:
        return JSONResponse({"error": "too_many_sessions"}, status_code=429)
    try:
        await _open_conversation(orch, session_id)
        await asyncio.to_thread(acp_sessions.remember, session_id, folder)
    except Exception:
        acp_sessions.pop(session_id)
        logger.warning("editor conversation could not be opened", exc_info=True)
        return JSONResponse({"error": "session_unavailable"}, status_code=503)
    _ensure_reaper(orch)
    return _opened(record, folder)


def _opened(record, folder: Path, **extra):
    """The binding's answer. ``holder`` is the token the editor presents on the lease,
    close and MCP routes (H542 review m1); only this response carries it."""
    return nocache_json({"ok": True, "session_id": record.session_id, "cwd": str(folder),
                         "holder": record.holder, "lease_seconds": acp_sessions.LEASE_SECONDS, **extra})


def _holder_refusal(session_id: str, holder: str | None):
    """None when *holder* holds the live binding of *session_id*; else the refusal."""
    if acp_sessions.get(session_id) is None:
        return None
    if not acp_sessions.holds(session_id, holder):
        return JSONResponse({"error": "not_holder"}, status_code=409)
    return None


async def _load(orch, session_id: str, folder: Path):
    """Bind an earlier editor conversation to its folder again. Its history is loaded by
    the next turn (``prepare_session``, with every identity check); one that never had a
    turn is made again empty, as at ``session/new``."""
    try:
        record = acp_sessions.register(session_id, folder, exclusive=True)
    except KeyError:
        return JSONResponse({"error": "session_in_use"}, status_code=409)
    except OverflowError:
        return JSONResponse({"error": "too_many_sessions"}, status_code=429)
    except ValueError:
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    try:
        conversation = orch.memory.conversation
        if session_id not in conversation.sessions and await asyncio.to_thread(_never_used, orch, session_id):
            await _open_conversation(orch, session_id)
    except Exception:
        acp_sessions.pop(session_id)
        logger.warning("editor conversation could not be loaded", exc_info=True)
        return JSONResponse({"error": "session_unavailable"}, status_code=503)
    _ensure_reaper(orch)
    return _opened(record, folder, loaded=True)


def _never_used(orch, session_id: str) -> bool:
    """No turn was ever kept for *session_id*: not a continuation (a fork's history is its
    continuation seed, with no snapshot until its first turn — H542 review M2), and no
    snapshot or the empty one ``session/new`` saved (a rewound snapshot is never treated as
    empty: the next turn verifies it)."""
    from agents.core.memory import persistence

    checkpoints = getattr(orch, "checkpoints", None)
    conn = getattr(checkpoints, "_conn", None)
    if conn is not None:
        with checkpoints._lock:
            if conn.execute("SELECT 1 FROM session_continuations WHERE session_id=?",
                            (session_id,)).fetchone() is not None:
                return False
    if not (persistence.memory_dir() / f"{session_id}.json").exists():
        return True
    snapshot = persistence.load_memory_snapshot(session_id)
    return snapshot.get("turns") == [] and snapshot.get("rewound") is not True


async def _fork(orch, source: str, folder: Path):
    """A continuation of an editor conversation, bound to the same folder. The copy is the
    hub's own continuation (lineage, identity and standing as for ``/sessions/continue``)."""
    import uuid

    from agents.core.session_continuation import ContinuationRefused, create_continuation

    # The copy gets an acp_ id (H542 review M1/M3): it is an editor conversation by its id,
    # whatever happens to the index, and the lease, close and MCP routes take it.
    child = acp_sessions.new_session_id()
    try:
        record = acp_sessions.register(child, folder)       # a full registry refuses first
    except OverflowError:
        return JSONResponse({"error": "too_many_sessions"}, status_code=429)
    try:
        created = await create_continuation(orch, source, str(uuid.uuid4()), child_id=child)
    except ContinuationRefused as exc:
        acp_sessions.pop(child)
        return JSONResponse({"error": exc.reason}, status_code=409 if exc.status in (404, 422) else exc.status)
    except Exception:
        acp_sessions.pop(child)
        logger.warning("editor conversation could not be forked", exc_info=True)
        return JSONResponse({"error": "session_unavailable"}, status_code=503)
    if not isinstance(created, dict) or created.get("session_id") != child:
        acp_sessions.pop(child)
        return JSONResponse({"error": "session_unavailable"}, status_code=503)
    try:
        await asyncio.to_thread(acp_sessions.remember, child, folder, parent=source)
    except Exception:
        logger.warning("forked editor conversation could not be listed", exc_info=True)
    _ensure_reaper(orch)
    return _opened(record, folder, forked_from=source)


@router.get("/api/acp/sessions", dependencies=[Depends(admin_guard)])
async def acp_list_sessions(cwd: str | None = None, cursor: str | None = None):
    """The editor conversations, newest first, a page of 50 (``session/list``)."""
    folder = None
    if cwd is not None:
        folder, refusal = await asyncio.to_thread(_editor_folder, cwd[:4096])
        if refusal is not None:
            return JSONResponse({"error": refusal}, status_code=409 if refusal == "cwd_outside_file_roots" else 400)
    offset = 0
    if cursor is not None:
        if not cursor.isdigit() or len(cursor) > 6:
            return JSONResponse({"error": "invalid_cursor"}, status_code=400)
        offset = int(cursor)
    rows, following = await asyncio.to_thread(acp_sessions.listing, folder, offset=offset)
    return nocache_json({"sessions": rows, "next_cursor": None if following is None else str(following)})


@router.post("/api/acp/sessions/{session_id}/lease", dependencies=[Depends(admin_guard)])
async def acp_renew_session(session_id: str, holder: str | None = Header(None, alias="X-ACP-Holder")):
    """`nerva acp` renews its sessions' lease while the editor is connected; a session
    whose lease runs out is reaped (its MCP servers removed) and refused from then on.
    Only the editor holding the binding renews it (``X-ACP-Holder``)."""
    if re.fullmatch(_SESSION_ID, session_id) is None:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    refused = _holder_refusal(session_id, holder)
    if refused is not None:
        return refused
    if not acp_sessions.renew(session_id):
        return JSONResponse({"error": "editor_session_closed"}, status_code=410)
    return nocache_json({"ok": True, "lease_seconds": acp_sessions.LEASE_SECONDS})


@router.post("/api/acp/sessions/{session_id}/mcp", dependencies=[Depends(admin_guard)])
async def acp_add_session_mcp(session_id: str, body: AcpMcpBody,
                              holder: str | None = Header(None, alias="X-ACP-Holder")):
    """Register an editor-supplied MCP server for this conversation only (H545), for the
    editor holding the binding (``X-ACP-Holder``)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if re.fullmatch(_SESSION_ID, session_id) is None:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    record = acp_sessions.get(session_id)
    if record is None:
        return JSONResponse({"error": "session_not_found"}, status_code=404)
    refused = _holder_refusal(session_id, holder)
    if refused is not None:
        return refused
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
    refused = server.config_findings()
    if refused:
        # H555: the editor's server meets the same launch validator as a saved one, here
        # and again before it spawns.
        return JSONResponse({"error": "config_refused", "findings": refused,
                             "message": "this server configuration matches a refused shape"},
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
async def acp_close_session(session_id: str, holder: str | None = Header(None, alias="X-ACP-Holder")):
    """The editor closed the session: remove its MCP servers, forget its folder. Only the
    editor holding the binding closes it (``X-ACP-Holder``); a session no longer held is a
    no-op."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if re.fullmatch(_SESSION_ID, session_id) is None:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    refused = _holder_refusal(session_id, holder)
    if refused is not None:
        return refused
    removed = await acp_sessions.close(session_id, getattr(orch, "mcp", None))
    await _reap(orch)
    return nocache_json({"ok": True, "removed": removed})
