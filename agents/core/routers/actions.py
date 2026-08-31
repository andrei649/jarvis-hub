"""Action-Level Approval endpoints (H10.18) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import user_guard, admin_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["actions"])


@router.get("/api/actions", dependencies=[Depends(user_guard)])
async def actions_list(status: str = Query("", max_length=20)):
    orch = get_orch()
    q = getattr(orch, "action_approvals", None) if orch else None
    if q is None:
        return nocache_json({"actions": [], "stats": {}})
    return nocache_json({"actions": q.list(status or None), "stats": q.stats()})


@router.get("/api/actions/pending", dependencies=[Depends(user_guard)])
async def actions_pending():
    orch = get_orch()
    q = getattr(orch, "action_approvals", None) if orch else None
    if q is None:
        return nocache_json({"actions": []})
    return nocache_json({"actions": q.list("pending")})


@router.post("/api/actions/request", dependencies=[Depends(user_guard)])
async def actions_request(req: Request):
    """Register a pending tool-call approval (sub-task granularity)."""
    _, q, err = require_component("action_approvals", "action approvals not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):  # valid JSON that isn't an object → treat as empty
        body = {}
    if not (body or {}).get("tool"):
        return JSONResponse({"error": "tool required"}, status_code=400)
    return nocache_json({"ok": True, "action": q.request(body)})


@router.post("/api/actions/{action_id}/decide", dependencies=[Depends(admin_guard)])
async def actions_decide(action_id: str, req: Request):
    """Approve or reject a single pending action (admin)."""
    _, q, err = require_component("action_approvals", "action approvals not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    if "approved" not in (body or {}):
        return JSONResponse({"error": "approved (bool) required"}, status_code=400)
    item = q.decide(action_id, bool(body["approved"]), by=(body or {}).get("by", "user"))
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "action": item})
