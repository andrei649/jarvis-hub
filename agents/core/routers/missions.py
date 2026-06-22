"""Mission Workspaces endpoints (roadmap 0.32) — `/api/missions`.

Thin governed surface over ``orch.missions`` (MissionStore): create a workspace
with a plan + budget, walk its pause/resume-able state machine, mark plan steps,
and read its budget + audit-trail. Reads are open (HUD polls them); every
*mutating* route is user-guarded (SEC-2), and the budget is a hard backend bound
— a step that exhausts it auto-fails the mission (a 409, not silent overrun).
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["missions"])


def _store():
    orch = get_orch()
    return getattr(orch, "missions", None) if orch else None


def _mission_payload(store, m) -> dict:
    d = m.to_dict()
    d["budget"] = store.budget_status(m.id)
    return d


@router.get("/api/missions")
async def missions_list(status: str = Query(None), limit: int = Query(50, ge=1, le=500)):
    """List mission workspaces (most-recent first), optionally by status."""
    store = _store()
    if store is None:
        return nocache_json({"missions": []})
    return nocache_json({"missions": [m.to_dict() for m in store.list(status=status, limit=limit)]})


@router.post("/api/missions", dependencies=[Depends(user_guard)])
async def missions_create(req: Request):
    """Create a workspace. Body: {title, goal?, plan?:[step titles], max_steps?, max_seconds?}."""
    store = _store()
    if store is None:
        return JSONResponse({"error": "missions not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    from agents.core.autonomy.missions import MissionError, DEFAULT_MAX_STEPS, DEFAULT_MAX_SECONDS
    try:
        m = store.create(
            title=(body or {}).get("title", ""),
            goal=(body or {}).get("goal", ""),
            plan=(body or {}).get("plan") or [],
            max_steps=int((body or {}).get("max_steps", DEFAULT_MAX_STEPS)),
            max_seconds=int((body or {}).get("max_seconds", DEFAULT_MAX_SECONDS)),
        )
    except (MissionError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return nocache_json({"ok": True, "mission": _mission_payload(store, m)})


@router.get("/api/missions/{mission_id}")
async def mission_get(mission_id: int):
    """Mission detail + budget + audit-trail events."""
    store = _store()
    if store is None:
        return JSONResponse({"error": "missions not available"}, status_code=503)
    m = store.get(mission_id)
    if m is None:
        return JSONResponse({"error": "mission not found"}, status_code=404)
    payload = _mission_payload(store, m)
    payload["events"] = [e.to_dict() for e in store.events(mission_id)]
    return nocache_json(payload)


def _transition(mission_id: int, op: str, **kwargs):
    """Shared body for the state-machine endpoints: 404 unknown, 409 illegal/budget."""
    store = _store()
    if store is None:
        return JSONResponse({"error": "missions not available"}, status_code=503)
    if store.get(mission_id) is None:
        return JSONResponse({"error": "mission not found"}, status_code=404)
    from agents.core.autonomy.missions import MissionError, BudgetExceeded
    try:
        m = getattr(store, op)(mission_id, **kwargs)
    except BudgetExceeded as e:
        return JSONResponse({"error": str(e), "budget_exceeded": True}, status_code=409)
    except MissionError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return nocache_json({"ok": True, "mission": _mission_payload(store, m)})


@router.post("/api/missions/{mission_id}/start", dependencies=[Depends(user_guard)])
async def mission_start(mission_id: int):
    return _transition(mission_id, "start")


@router.post("/api/missions/{mission_id}/pause", dependencies=[Depends(user_guard)])
async def mission_pause(mission_id: int):
    return _transition(mission_id, "pause")


@router.post("/api/missions/{mission_id}/resume", dependencies=[Depends(user_guard)])
async def mission_resume(mission_id: int):
    return _transition(mission_id, "resume")


@router.post("/api/missions/{mission_id}/complete", dependencies=[Depends(user_guard)])
async def mission_complete(mission_id: int):
    return _transition(mission_id, "complete")


@router.post("/api/missions/{mission_id}/cancel", dependencies=[Depends(user_guard)])
async def mission_cancel(mission_id: int):
    return _transition(mission_id, "cancel")


@router.post("/api/missions/{mission_id}/steps/{idx}/finish", dependencies=[Depends(user_guard)])
async def mission_finish_step(mission_id: int, idx: int, req: Request):
    """Mark plan step ``idx`` terminal. Body: {status?: done|failed|skipped, result?}.

    Charges the step budget; exhausting it auto-fails the mission (409)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    return _transition(
        mission_id, "finish_step", idx=idx,
        status=(body or {}).get("status", "done"),
        result=(body or {}).get("result"),
    )
