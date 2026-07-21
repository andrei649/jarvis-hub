"""Live Quality Monitor endpoints (H10.23) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import admin_guard

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["quality"])


@router.get("/api/quality")
async def quality_status():
    """Rolling quality average + threshold alert for live requests."""
    orch = get_orch()
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return nocache_json({"stats": {}, "alert": {"alerting": False}})
    return nocache_json({"stats": q.stats(), "alert": q.check_alert()})


@router.get("/api/quality/scores")
async def quality_scores(limit: int = Query(50, ge=1, le=500)):
    """Recent per-request quality scores (most recent first)."""
    orch = get_orch()
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return nocache_json({"scores": []})
    return nocache_json({"scores": q.recent(limit)})


@router.post("/api/quality/threshold", dependencies=[Depends(admin_guard)])
async def quality_set_threshold(req: Request):
    """Set the alert threshold (admin)."""
    orch = get_orch()
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return JSONResponse({"error": "quality monitor not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    if "threshold" not in (body or {}):
        return JSONResponse({"error": "threshold required"}, status_code=400)
    try:
        value = float(body["threshold"])
    except (TypeError, ValueError):
        return JSONResponse({"error": "threshold must be a number"}, status_code=400)
    q.set_threshold(value)
    return nocache_json({"ok": True, "threshold": q.threshold})
