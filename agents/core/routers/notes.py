"""Conversation Notes endpoints (H10.21) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json, logger
from agents.core.app_state import get_orch


router = APIRouter(tags=["notes"])


class _NoteBody(BaseModel):
    content: str = Field("", max_length=20000)


@router.get("/api/notes", dependencies=[Depends(user_guard)])
async def notes_get():
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    sid = getattr(orch, "session_id", "web") if orch else "web"
    return nocache_json({"session": sid, "content": notes.get(sid) if notes else ""})


@router.put("/api/notes", dependencies=[Depends(user_guard)])
async def notes_set(body: _NoteBody):
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    if notes is None:
        return JSONResponse({"error": "notes not available"}, status_code=503)
    sid = getattr(orch, "session_id", "web")
    return nocache_json({"ok": True, "session": sid, **notes.set(sid, body.content)})


@router.delete("/api/notes", dependencies=[Depends(user_guard)])
async def notes_clear():
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    sid = getattr(orch, "session_id", "web") if orch else "web"
    cleared = notes.clear(sid) if notes else False
    return nocache_json({"ok": True, "cleared": cleared})


@router.post("/api/notes/rewrite", dependencies=[Depends(user_guard)])
async def notes_rewrite(req: Request):
    """H10.21 — 'Rewrite with AI': run the note through an agent; optionally save."""
    orch = get_orch()
    notes = getattr(orch, "notes", None) if orch else None
    if notes is None or not orch:
        return JSONResponse({"error": "notes not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = getattr(orch, "session_id", "web")
    content = notes.get(sid)
    if not content.strip():
        return JSONResponse({"error": "note is empty"}, status_code=400)
    instruction = (body or {}).get("instruction") or "Rewrite these notes to be clearer and well-organized."
    prompt = f"{instruction}\n\n---\n{content}"
    try:
        rewritten = await orch.handle_input(prompt, channel="notes")
    except Exception:
        logger.exception("notes rewrite failed")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)
    saved = False
    if (body or {}).get("save"):
        notes.set(sid, rewritten)
        saved = True
    return nocache_json({"ok": True, "rewritten": rewritten, "saved": saved})
