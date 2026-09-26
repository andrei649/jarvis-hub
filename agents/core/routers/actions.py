"""Action-Level Approval endpoints (H10.18) — extracted from web.py (CLN-3)."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import user_guard, admin_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


logger = logging.getLogger("jarvis.web")

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
    """Register a pending tool-call approval (sub-task granularity).

    H659: with an ``Idempotency-Key``, a retry returns the action the first request queued
    instead of queuing a second approval card."""
    from agents.core import idempotency

    refusal = idempotency.check_header(req)
    if refusal is not None:
        return refusal
    _, q, err = require_component("action_approvals", "action approvals not available")
    if err is not None:
        return err
    raw = await req.body()
    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):  # valid JSON that isn't an object → treat as empty
        body = {}
    if not (body or {}).get("tool"):
        return JSONResponse({"error": "tool required"}, status_code=400)
    started = idempotency.begin(req, "actions", raw)
    if started.refusal is not None:
        return started.refusal
    if started.replay is not None:
        action_id = str((started.replay.ref or {}).get("action_id") or "")
        return idempotency.replayed({"ok": True, "action": q.get(action_id) or {"id": action_id}})
    try:
        action = q.request(body)
    except BaseException:
        if started.claim is not None:
            started.claim.release()
        raise
    if started.claim is not None:
        started.claim.done({"action_id": action.get("id")})
    return nocache_json({"ok": True, "action": action})


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
    if item.get("tool") == "skill.patch_proposal":
        # H318 review — a decided skill change lands now, not at the curator's next night
        # (which never comes while the learning loop is off, the default).
        store = getattr(get_orch(), "skill_proposals", None)
        rec = store.get(str((item.get("args") or {}).get("proposal_id") or "")) if store is not None else None
        if rec is None or rec.get("card") != action_id:
            # Only the card a proposal queued decides it (review-H318b m-6): say so, rather
            # than answer as if this decision changed a skill.
            return nocache_json({"ok": True, "action": {
                **item, "note": "this card is not a proposal's own approval card: no skill was changed"}})
        curator = getattr(get_orch(), "curator", None)
        if curator is not None and hasattr(curator, "apply_decisions"):
            try:
                item = {**item, "applied": await asyncio.to_thread(curator.apply_decisions)}
            except Exception:
                logger.warning("skill proposal apply after decision failed", exc_info=True)
    return nocache_json({"ok": True, "action": item})
