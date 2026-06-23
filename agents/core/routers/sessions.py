"""Session endpoints — extracted from web.py (CLN-3).

Covers the `/sessions` surface: list recent sessions and resume a session by id.
Both are user-guarded. The orchestrator (which owns `checkpoints` + `memory`) is
resolved at request time via `get_orch()` (late binding to `web.orch`), matching
the other extracted routers. Behavior is unchanged from the inline versions.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.validation import is_valid_session_id

router = APIRouter(tags=["sessions"])


@router.get("/sessions", dependencies=[Depends(user_guard)])
async def get_sessions():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20)
    return {"sessions": sessions}


@router.post("/sessions/resume", dependencies=[Depends(user_guard)])
async def resume_session(req: Request):
    body = await req.json()
    sid = body.get("session_id")
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
