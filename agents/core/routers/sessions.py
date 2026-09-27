"""Session endpoints — extracted from web.py (CLN-3).

Covers the `/sessions` surface: list recent sessions and resume a session by id.
Both are user-guarded. The orchestrator (which owns `checkpoints` + `memory`) is
resolved at request time via `get_orch()` (late binding to `web.orch`), matching
the other extracted routers. Behavior is unchanged from the inline versions.

H315 adds the agent's own plans: `GET /sessions/todo` (the ones the agent most
recently wrote or read) and `GET /sessions/{id}/todo` (one session's), both
user-guarded and never cached — a plan is work in flight and a stale copy misstates it.

H262 adds the pin (`POST /sessions/{id}/pin` and `/unpin`, user-guarded): a pinned chat is
never auto-archived and never deleted by retention; each list row carries `pinned_at`.
H262 review: unarchiving or resuming a chat stamps `kept_at`, from which the archiver
counts its idle time again, so the next sweep does not archive it straight back.
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
    """The newest sessions; H218: archived ones only with ``?archived=true``, never mixed in.
    H262: each row carries its ``pinned_at``."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20, archived=archived)
    from ..session_titles import title_fields  # H413: each session's title and its source

    return {"sessions": [{**row, **title_fields(row.get("metadata")), **_stamp_fields(row)} for row in sessions]}


def _stamp_fields(row: dict) -> dict:
    import json as _json

    try:
        meta = _json.loads(row.get("metadata") or "{}")
    except (TypeError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return {key: meta.get(key) if isinstance(meta.get(key), str) else None for key in ("archived_at", "pinned_at")}


#: The stamps a route may set or clear: the store's writer and the answer's field.
_STAMPS = {"archived": "set_archived", "pinned": "set_pinned"}


def _set_stamp(session_id: str, field: str, on: bool):
    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if (field, on) == ("archived", False):
        done = _keep(orch.checkpoints, session_id)
    else:
        done = getattr(orch.checkpoints, _STAMPS[field])(session_id, on)
    if done is None:
        return JSONResponse({"error": "the session store is unavailable", "reason": "store_unavailable"},
                            status_code=503)
    if not done:
        return JSONResponse({"error": f"session '{session_id}' not found"}, status_code=404)
    return JSONResponse({"ok": True, "session": session_id, field: on}, headers=_NO_STORE)


def _keep(checkpoints, session_id: str):
    """H262 review — the owner keeps a chat: unarchived, with ``kept_at`` stamped."""
    keep = getattr(checkpoints, "unarchive", None)
    return keep(session_id) if callable(keep) else checkpoints.set_archived(session_id, False)


@router.post("/sessions/{session_id}/archive", dependencies=[Depends(user_guard)])
async def archive_session(session_id: str):
    """H218 — put a conversation away: it leaves the list, nothing is deleted."""
    return _set_stamp(session_id, "archived", True)


@router.post("/sessions/{session_id}/unarchive", dependencies=[Depends(user_guard)])
async def unarchive_session(session_id: str):
    """H218 — bring an archived conversation back to the list (a pinned one too)."""
    return _set_stamp(session_id, "archived", False)


@router.post("/sessions/{session_id}/pin", dependencies=[Depends(user_guard)])
async def pin_session(session_id: str):
    """H262 — pin a conversation: never auto-archived, never deleted by retention."""
    return _set_stamp(session_id, "pinned", True)


@router.post("/sessions/{session_id}/unpin", dependencies=[Depends(user_guard)])
async def unpin_session(session_id: str):
    """H262 — take the pin off; the chat is archived and retained like any other again."""
    return _set_stamp(session_id, "pinned", False)


_DELETE_STATUS = {"active_session": 409, "session_busy": 409, "has_continuations": 409, "not_found": 404,
                  "recall_unavailable": 503}


@router.delete("/sessions/{session_id}", dependencies=[Depends(admin_guard)])
async def delete_session(session_id: str, confirm: str = ""):
    """H218 — delete one conversation for good, backup first. Needs ``?confirm=DELETE``.

    Holds the session's turn lease, as ``create_continuation`` does: a turn on it
    finishes first (it would write the transcript back, or add a turn the backup never
    saw), and one still running past the lease's wait answers 409 ``session_busy``."""
    from agents.core import session_archive

    if not is_valid_session_id(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    if confirm != session_archive.CONFIRM:
        return JSONResponse({"error": "a permanent delete requires ?confirm=DELETE",
                             "reason": "confirm_required"}, status_code=400)
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        # H262: the steps the lifecycle sweep's delete shares (session_archive.delete_leased).
        result = await session_archive.delete_leased(orch, session_id)
    except session_archive.SessionDeleteError as exc:
        return JSONResponse({"error": exc.reason.replace("_", " "), "reason": exc.reason},
                            status_code=_DELETE_STATUS.get(exc.reason, 500))
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
    from agents.core.session_continuation import ContinuationRefused

    try:
        ok = await orch.memory.resume_session(sid)
    except ContinuationRefused as exc:     # a continued chat whose history cannot be restored
        return JSONResponse({"error": exc.reason}, status_code=exc.status)
    if not ok:
        return JSONResponse({"error": f"session '{sid}' not found"}, status_code=404)
    orch.session_id = sid
    checkpoints = getattr(orch, "checkpoints", None)
    if checkpoints is not None:
        _keep(checkpoints, sid)   # H218: resuming an archived chat brings it back (H262: pin kept, kept_at stamped)
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
