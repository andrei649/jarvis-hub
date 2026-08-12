"""Model Arena / Blind Comparison endpoints (H10.19) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Request, Depends
from agents.core.routers._deps import user_guard
from fastapi.responses import JSONResponse

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["arena"])


@router.post("/api/arena/run", dependencies=[Depends(user_guard)])
async def arena_run(req: Request):
    """Create a blind match. Body: {query, candidates:{model:response}} or
    {query, agents:[id,...]} to run the query against those agents live."""
    orch = get_orch()
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    query = (body or {}).get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    candidates = (body or {}).get("candidates") or {}
    if not candidates:
        agents = (body or {}).get("agents") or []
        if len(agents) < 2 or not orch:
            return JSONResponse({"error": "provide candidates or >=2 agents"}, status_code=400)
        for aid in agents:
            try:
                candidates[aid] = await orch.handle_input(query, channel="arena", agent_override=aid)
            except Exception as e:
                candidates[aid] = f"[error:{e}]"
    try:
        match = arena.create_match(query, candidates)
    except ValueError as e:
        return error_json(e, 400, "invalid match request")
    return nocache_json({"ok": True, "match": match})


@router.post("/api/arena/vote", dependencies=[Depends(user_guard)])
async def arena_vote(req: Request):
    """Vote for a label; reveals the mapping and updates ELO/win-rate."""
    orch = get_orch()
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    match_id = (body or {}).get("match_id", "")
    winner = (body or {}).get("winner", "")
    if not match_id or not winner:
        return JSONResponse({"error": "match_id and winner required"}, status_code=400)
    try:
        return nocache_json({"ok": True, "match": arena.vote(match_id, winner)})
    except KeyError:
        return JSONResponse({"error": "unknown match"}, status_code=404)
    except ValueError as e:
        return error_json(e, 400, "invalid vote")


@router.get("/api/arena/match/{match_id}", dependencies=[Depends(user_guard)])
async def arena_match(match_id: str):
    orch = get_orch()
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    m = arena.get_match(match_id)
    if m is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(m)


@router.get("/api/arena/leaderboard")
async def arena_leaderboard():
    orch = get_orch()
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return nocache_json({"leaderboard": []})
    return nocache_json({"leaderboard": arena.leaderboard()})
