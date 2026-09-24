"""Session endpoints — extracted from web.py (CLN-3).

Covers the `/sessions` surface: list recent sessions and resume a session by id.
Both are user-guarded. The orchestrator (which owns `checkpoints` + `memory`) is
resolved at request time via `get_orch()` (late binding to `web.orch`), matching
the other extracted routers. Behavior is unchanged from the inline versions.

H315 adds the agent's own plans: `GET /sessions/todo` (the most recently updated
ones) and `GET /sessions/{id}/todo` (one session's), both user-guarded and never
cached — a plan is work in flight and a stale copy misstates it.
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
async def get_sessions():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20)
    return {"sessions": sessions}


_NO_STORE = {"Cache-Control": "no-store"}
#: How many plans the recent list returns — the Decision Inbox shows a few, `nerva todo`
#: prints them all.
RECENT_PLANS = 20


@router.get("/sessions/todo", dependencies=[Depends(user_guard)])
async def get_recent_plans():
    """H315 — the checklists the agent keeps, most recently updated first."""
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
    history = await orch.memory.get_history(sid, last_n=20)
    return JSONResponse({"ok": True, "session": sid, "turns": history})


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
