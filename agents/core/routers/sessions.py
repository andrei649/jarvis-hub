"""Session endpoints — extracted from web.py (CLN-3).

Covers the `/sessions` surface: list recent sessions and resume a session by id.
Both are user-guarded. The orchestrator (which owns `checkpoints` + `memory`) is
resolved at request time via `get_orch()` (late binding to `web.orch`), matching
the other extracted routers. Behavior is unchanged from the inline versions.

H315 adds the agent's own plans: `GET /sessions/todo` (the ones the agent most
recently wrote or read) and `GET /sessions/{id}/todo` (one session's), both
user-guarded and never cached — a plan is work in flight and a stale copy misstates it.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.validation import is_valid_session_id

router = APIRouter(tags=["sessions"])


@router.get("/sessions", dependencies=[Depends(user_guard)])
async def get_sessions(archived: bool = False):
    """The newest sessions; H218: archived ones only with ``?archived=true``, never mixed in."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20, archived=archived)
    from ..session_titles import title_fields  # H413: each session's title and its source

    return {"sessions": [{**row, **title_fields(row.get("metadata")), **_archived_field(row)} for row in sessions]}


def _archived_field(row: dict) -> dict:
    import json as _json

    try:
        meta = _json.loads(row.get("metadata") or "{}")
    except (TypeError, ValueError):
        meta = {}
    stamp = meta.get("archived_at") if isinstance(meta, dict) else None
    return {"archived_at": stamp if isinstance(stamp, str) else None}


def _set_archived(session_id: str, archived: bool):
    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not orch.checkpoints.set_archived(session_id, archived):
        return JSONResponse({"error": f"session '{session_id}' not found"}, status_code=404)
    return JSONResponse({"ok": True, "session": session_id, "archived": archived}, headers=_NO_STORE)


@router.post("/sessions/{session_id}/archive", dependencies=[Depends(user_guard)])
async def archive_session(session_id: str):
    """H218 — put a conversation away: it leaves the list, nothing is deleted."""
    return _set_archived(session_id, True)


@router.post("/sessions/{session_id}/unarchive", dependencies=[Depends(user_guard)])
async def unarchive_session(session_id: str):
    """H218 — bring an archived conversation back to the list."""
    return _set_archived(session_id, False)


@router.delete("/sessions/{session_id}", dependencies=[Depends(admin_guard)])
async def delete_session(session_id: str, confirm: str = ""):
    """H218 — delete one conversation for good, backup first. Needs ``?confirm=DELETE``."""
    from agents.core import session_archive, todo_tool

    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    if confirm != session_archive.CONFIRM:
        return JSONResponse({"error": "a permanent delete requires ?confirm=DELETE",
                             "reason": "confirm_required"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        result = await session_archive.delete_session(
            session_id, checkpoints=orch.checkpoints, memory=getattr(orch.memory, "conversation", None),
            todos=todo_tool.TODOS, active=getattr(orch, "session_id", None))
    except session_archive.SessionDeleteError as exc:
        status = {"active_session": 409, "not_found": 404}.get(exc.reason, 500)
        return JSONResponse({"error": exc.reason.replace("_", " "), "reason": exc.reason}, status_code=status)
    return JSONResponse(result, headers=_NO_STORE)


_NO_STORE = {"Cache-Control": "no-store"}
#: How many plans the recent list returns — the Decision Inbox shows a few, `nerva todo`
#: prints them all.
RECENT_PLANS = 20


@router.get("/sessions/todo", dependencies=[Depends(user_guard)])
async def get_recent_plans():
    """H315 — the checklists the agent keeps, the one it most recently wrote or read
    first (each carries ``updated_at``, when its list last changed)."""
    from agents.core import todo_tool

    return JSONResponse({"plans": todo_tool.TODOS.recent(RECENT_PLANS)}, headers=_NO_STORE)


@router.get("/sessions/{session_id}/todo", dependencies=[Depends(user_guard)])
async def get_session_plan(session_id: str):
    """H315 — one session's checklist; a session with none answers an empty list."""
    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    from agents.core import todo_tool

    return JSONResponse(todo_tool.TODOS.read(session_id), headers=_NO_STORE)


@router.post("/sessions/resume", dependencies=[Depends(user_guard)])
async def resume_session(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = body.get("session_id") if isinstance(body, dict) else None
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    # AUD-5: reject anything that isn't an inert identifier before it can reach a
    # filesystem path (memory/persistence.py builds MEMORY_DIR / f"{sid}.json").
    if not is_valid_session_id(sid):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    ok = await orch.memory.resume_session(sid)
    if not ok:
        return JSONResponse({"error": f"session '{sid}' not found"}, status_code=404)
    orch.session_id = sid
    checkpoints = getattr(orch, "checkpoints", None)
    if checkpoints is not None:
        checkpoints.set_archived(sid, False)   # H218: resuming an archived chat brings it back
    history = await orch.memory.get_history(sid)
    from agents.core.memory.recap import render_recap

    # H441 — the recap is rendered from the stored turns, never by a model; "turns"
    # stays the last 20 raw turns for the clients that replay them.
    return JSONResponse({"ok": True, "session": sid, "turns": history[-20:],
                         "recap": render_recap(history)})


class ContinueSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_session_id: str
    request_id: UUID

    @field_validator("source_session_id")
    @classmethod
    def valid_source(cls, value):
        if not is_valid_session_id(value):
            raise ValueError("invalid session_id")
        return value


@router.post("/sessions/continue", dependencies=[Depends(admin_guard)])
async def continue_session(body: ContinueSessionRequest):
    from agents.core.session_continuation import ContinuationRefused, create_continuation
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        result = await create_continuation(orch, body.source_session_id, str(body.request_id))
    except ContinuationRefused as exc:
        return JSONResponse({"error": exc.reason}, status_code=exc.status)
    return JSONResponse(result, status_code=201)
