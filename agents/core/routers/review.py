"""Human Review Queue endpoints (H10.25) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Request, Query, Depends
from agents.core.routers._deps import user_guard
from fastapi.responses import JSONResponse

from agents.core.web_helpers import nocache_json, error_json, logger
from agents.core.app_state import get_orch


router = APIRouter(tags=["review"])


@router.get("/api/review/queue")
async def review_queue_list(status: str = Query("", max_length=20)):
    orch = get_orch()
    q = getattr(orch, "review_queue", None) if orch else None
    if q is None:
        return nocache_json({"items": [], "rubric_criteria": []})
    from agents.core.observability.review_queue import RUBRIC_CRITERIA
    return nocache_json({"items": q.list(status or None), "rubric_criteria": RUBRIC_CRITERIA})


@router.get("/api/review/stats")
async def review_queue_stats():
    orch = get_orch()
    q = getattr(orch, "review_queue", None) if orch else None
    if q is None:
        return nocache_json({"stats": {}})
    return nocache_json({"stats": q.stats()})


@router.post("/api/review/flag", dependencies=[Depends(user_guard)])
async def review_queue_flag(req: Request):
    """Manually flag a trace for review. Body: {trace, reason?}."""
    orch = get_orch()
    q = getattr(orch, "review_queue", None) if orch else None
    if q is None:
        return JSONResponse({"error": "review queue not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    trace = (body or {}).get("trace")
    if not trace:
        return JSONResponse({"error": "trace required"}, status_code=400)
    return nocache_json({"ok": True, "item": q.flag(trace, (body or {}).get("reason", "manual"))})


@router.post("/api/review/{item_id}/vote", dependencies=[Depends(user_guard)])
async def review_queue_vote(item_id: str, req: Request):
    """Record a thumbs up/down + rubric for a queued item."""
    orch = get_orch()
    q = getattr(orch, "review_queue", None) if orch else None
    if q is None:
        return JSONResponse({"error": "review queue not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        item = q.review(item_id, (body or {}).get("verdict", ""),
                        (body or {}).get("rubric"), (body or {}).get("notes", ""))
    except ValueError as e:
        return error_json(e, 400, "invalid review verdict")
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "item": item})


@router.post("/api/review/{item_id}/dataset", dependencies=[Depends(user_guard)])
async def review_queue_to_dataset(item_id: str, req: Request):
    """Promote a reviewed item into an eval dataset (H9.3b)."""
    orch = get_orch()
    q = getattr(orch, "review_queue", None) if orch else None
    if q is None:
        return JSONResponse({"error": "review queue not available"}, status_code=503)
    item = q.get(item_id)
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body or {}).get("dataset", "review_flagged")
    case = q.to_eval_case(item)
    try:
        from agents.core.observability.datasets import DatasetStore
        store = DatasetStore()
        cases = store.load(name) or []
        cases.append(case)
        version = store.save_version(name, cases)
    except Exception:
        logger.exception("review dataset write failed")
        return JSONResponse({"error": "dataset write failed", "code": 500}, status_code=500)
    q.mark_in_dataset(item_id)
    return nocache_json({"ok": True, "dataset": name, "version": version, "case": case})
