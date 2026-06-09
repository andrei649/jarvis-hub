"""Agent Canvas / A2UI endpoints (H12.18) — extracted from web.py (CLN-3)."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

router = APIRouter(tags=["canvas"])

_canvas_store = None


def _get_canvas():
    from agents import web
    orch = web.orch
    if orch is not None and getattr(orch, "canvas", None) is not None:
        return orch.canvas
    global _canvas_store
    if _canvas_store is None:
        from agents.core.canvas import CanvasStore
        _canvas_store = CanvasStore()
    return _canvas_store


class CanvasPostBody(BaseModel):
    agent: str = Field("agent", max_length=64)
    type: str = Field(..., max_length=32)
    payload: dict = Field(default_factory=dict)
    pinned: bool = False


@router.get("/api/canvas", dependencies=[Depends(user_guard)])
async def canvas_list(agent: Optional[str] = None):
    from agents import web
    return web._nocache_json({"elements": _get_canvas().list(agent)})


@router.post("/api/canvas/post", dependencies=[Depends(user_guard)])
async def canvas_post(body: CanvasPostBody):
    """Add a typed, sanitized element. Unsafe/unknown types are rejected (422)."""
    from agents import web
    try:
        return web._nocache_json(_get_canvas().post(body.agent, body.type, body.payload,
                                                    pinned=body.pinned))
    except ValueError as e:
        return web._nocache_json({"error": str(e)}, status_code=422)


@router.post("/api/canvas/{el_id}/pin", dependencies=[Depends(user_guard)])
async def canvas_pin(el_id: str, pinned: bool = True):
    from agents import web
    el = _get_canvas().pin(el_id, pinned)
    return web._nocache_json(el or {"error": "not found"}, status_code=200 if el else 404)


@router.delete("/api/canvas/{el_id}", dependencies=[Depends(user_guard)])
async def canvas_remove(el_id: str):
    from agents import web
    ok = _get_canvas().remove(el_id)
    return web._nocache_json({"removed": ok}, status_code=200 if ok else 404)


@router.post("/api/canvas/clear", dependencies=[Depends(user_guard)])
async def canvas_clear(agent: Optional[str] = None, keep_pinned: bool = True):
    from agents import web
    return web._nocache_json({"removed": _get_canvas().clear(agent, keep_pinned=keep_pinned)})
