"""Action-Level Approval endpoints (H10.18) — extracted from web.py (CLN-3)."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import user_guard, admin_guard, _web
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["actions"])


def _judge_status(q) -> dict:
    """H277: the advisory approval judge's state (``configured``, ``reason``, provider/model,
    ``judging`` ids) — never a key, a base URL only for a local judge."""
    status = getattr(q, "judge_status_public", None)
    return status() if callable(status) else {"configured": False, "reason": "judge_unset", "judging": []}


def _groups_projection(q) -> dict:
    groups = q.pending_groups()
    return {'groups': groups} if groups else {}


@router.get("/api/actions", dependencies=[Depends(user_guard)])
async def actions_list(status: str = Query("", max_length=20)):
    orch = get_orch()
    q = getattr(orch, "action_approvals", None) if orch else None
    if q is None:
        return nocache_json({"actions": [], "stats": {}})
    return nocache_json({"actions": q.list(status or None), "stats": q.stats(), "judge": _judge_status(q),
                         **(_groups_projection(q) if not status or status == 'pending' else {})})


@router.get("/api/actions/pending", dependencies=[Depends(user_guard)])
async def actions_pending():
    orch = get_orch()
    q = getattr(orch, "action_approvals", None) if orch else None
    if q is None:
        return nocache_json({"actions": []})
    return nocache_json({"actions": q.list("pending"), "judge": _judge_status(q), **_groups_projection(q)})


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
    started = await asyncio.to_thread(idempotency.begin, req, "actions", raw)
    if started.refusal is not None:
        return started.refusal
    if started.replay is not None:
        action_id = str((started.replay.ref or {}).get("action_id") or "")
        return idempotency.replayed({"ok": True, "action": q.get(action_id) or {"id": action_id}})
    try:
        # This is a registration context, never an execution/session grant.
        # Reuse the existing verified owner check; client context claims opt out
        # inside the queue and ordinary user/direct/browser requests stay separate.
        from agents.core.autonomy.approval_grouping import OwnerRegistrationContext

        web = _web()
        principal = web._web_principal(req) if web is not None else None
        if getattr(principal, 'admin', False) is True:
            action = q.request(body, grouping_context=OwnerRegistrationContext())
        else:
            action = q.request(body)
    except BaseException:
        if started.claim is not None:
            started.claim.release()
        raise
    if started.claim is not None:
        await asyncio.to_thread(started.claim.done, {"action_id": action.get("id")})
    return nocache_json({"ok": True, "action": action})


@router.post('/api/actions/groups/{group_id}/reject', dependencies=[Depends(admin_guard)])
async def actions_reject_group(group_id: str, req: Request):
    """Reject only an exact still-current registration group, never approve it."""
    _, q, err = require_component('action_approvals', 'action approvals not available')
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = None
    if (not isinstance(body, dict) or not isinstance(body.get('snapshot'), str)
            or not isinstance(body.get('member_ids'), list)
            or not all(isinstance(member, str) for member in body['member_ids'])
            or 'approved' in body):
        return JSONResponse({'error': 'snapshot and exact member_ids required'}, status_code=400)
    try:
        decided = q.reject_group(group_id, snapshot=body['snapshot'], member_ids=body['member_ids'],
                                 by='admin', reason=body.get('reason'))
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    if decided is None:
        return JSONResponse({'error': 'approval group changed'}, status_code=409)
    return nocache_json({'ok': True, 'actions': decided})


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
    if not isinstance(body, dict) or not isinstance(body.get("approved"), bool):
        return JSONResponse({"error": "approved (bool) required"}, status_code=400)
    try:
        item = q.decide(action_id, body["approved"], by=body.get("by", "user"),
                        reason=body.get("reason"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
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
