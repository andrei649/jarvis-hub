"""Learning-loop endpoints — extracted from web.py (CLN-3).

Covers the learning surface: propose agent promotions into the decision inbox
(`/api/learning/propose`), the learning overview (`/learning`), manual bench-agent
promotion (`/learning/promote`), and live learning stats for SystemsPanel
(`/learning/stats`).

The orchestrator (which owns `learning`, `agents`, `_run_learning_loop`, and
`promote_bench_agent`) is resolved at request time via `get_orch()` (late binding
to `web.orch`), matching the other extracted routers — no static import edge into
web. Behavior is unchanged: handlers branch on a missing/partial orchestrator
exactly as the inline versions did.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["learning"])


@router.post("/api/learning/propose", dependencies=[Depends(admin_guard)])
async def learning_propose():
    """Run the learning loop now: propose agent promotions into the decision inbox."""
    orch = get_orch()
    if not orch or not hasattr(orch, "_run_learning_loop"):
        return JSONResponse({"error": "not available"}, status_code=503)
    proposals = await orch._run_learning_loop()
    return nocache_json({"ok": True, "proposed": proposals, "count": len(proposals)})


@router.get("/learning", dependencies=[Depends(user_guard)])
async def get_learning():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "stats": orch.learning.get_stats(active_ids=set(orch.agents.keys())),
        "optimizations": {
            aid: orch.learning.optimize_prompt(aid)
            for aid in orch.agents
        },
        "promotion_suggestions": orch.learning.suggest_promotions(active_ids=set(orch.agents.keys())),
    }


class PromoteRequest(BaseModel):
    bench_agent: str


@router.post("/learning/promote", dependencies=[Depends(admin_guard)])
async def learning_promote(body: PromoteRequest):
    """Manually promote a bench agent to active status."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    bench_id = body.bench_agent.strip().lower()
    if not bench_id:
        return JSONResponse({"error": "bench_agent is required"}, status_code=400)
    promoted = orch.promote_bench_agent(bench_id)
    if not promoted:
        # Honest result: a no-op (unknown bench id, or already active) is not a
        # success — say so with 404 so the HUD shows an error, not a fake "ok".
        return JSONResponse(
            {"ok": False, "bench_agent": bench_id, "promoted": False,
             "error": f"'{bench_id}' is not a promotable bench agent (unknown or already active)"},
            status_code=404,
        )
    return nocache_json({
        "ok": True,
        "bench_agent": bench_id,
        "promoted": promoted,
        "active_agents": list(orch.agents.keys()),
    })


@router.get("/learning/stats")
async def learning_stats():
    """Live learning stats for SystemsPanel."""
    orch = get_orch()
    if not orch or not hasattr(orch, 'learning') or not orch.learning:
        return nocache_json({"interactions_total": 0, "success_rate": 0, "prompt_optimizations": [], "promotion_candidates": [], "demotion_warnings": []})
    try:
        stats = orch.learning.get_stats()
        # `agents_tracked` is a COUNT; iterating it raised TypeError on every call.
        # `agent_ids` is the list this always meant.
        active_ids = list(stats.get("agent_ids") or [])
        optimizations = []
        for aid in active_ids:
            opt = orch.learning.optimize_prompt(aid) if hasattr(orch.learning, 'optimize_prompt') else None
            if opt:
                optimizations.append({"agent": aid, "before": "", "after": opt, "improvement": ""})
        promotions = orch.learning.suggest_promotions(active_ids) if hasattr(orch.learning, 'suggest_promotions') else []
        promos = [{"agent": p.get("bench_agent", p.get("agent", "")), "triggers": p.get("count", 0), "threshold": p.get("threshold", 0)} for p in promotions]
        total = stats.get("total_interactions", 0)
        successful = stats.get("successful", 0)
        rate = successful / total if total > 0 else 0
        return nocache_json({
            "interactions_total": total,
            "success_rate": round(rate, 3),
            "prompt_optimizations": optimizations,
            "promotion_candidates": promos,
            "demotion_warnings": [],
        })
    except Exception:
        # Zeros here are a claim: "the hub has had 0 interactions with a 0% success
        # rate", which the SystemsPanel renders as a real reading. A failed read is
        # a different fact, so say which one this is.
        logger.warning("learning stats read failed", exc_info=True)
        return nocache_json({
            "interactions_total": None, "success_rate": None,
            "prompt_optimizations": [], "promotion_candidates": [],
            "demotion_warnings": [],
            "available": False,
            "degraded": {"source": "learning", "reason": "read-failed"},
        })
