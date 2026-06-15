"""Analytics / cost / traces / reflection endpoints — extracted from web.py (CLN-3).

Covers the observability read surface across four address spaces:

* `/api/analytics/*` — per-agent LLM usage + cost summary (H7.10), model-tier
  classification, and the on-device-vs-cloud locality counter-metric (MOONSHOT §6).
* `/api/cost` — estimated $ cost per agent + per day off the tracer (H10.24).
* `/api/traces/*` — the H9.2 Trace Explorer (list / get / clear) over the
  in-memory trace ring buffer.
* `/api/reflection/*` — nightly reflection status + manual trigger (H5.15).

Orchestrator-only: every handler reads its subsystem off the live orchestrator
(`orch.run_history` / `orch.reflector` / `orch.tracer`) via `get_orch()`, with no
web-module globals. The cost/model-tier handlers are pure leaf calls into
`core.cost_tracker`.
"""

from fastapi import APIRouter, Query

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["observe"])


@router.get("/api/analytics/cost")
async def get_analytics_cost():
    """Return per-agent LLM usage and cost summary (H7.10)."""
    from agents.core.cost_tracker import get_summary
    return get_summary()


@router.get("/api/analytics/model-tiers")
async def get_model_tiers():
    """Return per-agent model tier classification and usage summary."""
    from agents.core.cost_tracker import get_summary
    summary = get_summary()

    def classify_tier(model: str) -> str:
        m = model.lower()
        if "local" in m or m == "default":
            return "local"
        if "haiku" in m or "mini" in m or "flash" in m:
            return "fast"
        if "opus" in m:
            return "heavy"
        return "standard"

    tiers: dict[str, list] = {"local": [], "fast": [], "standard": [], "heavy": []}
    for agent_name, data in summary.get("agents", {}).items():
        tier = classify_tier(data.get("model", "default"))
        tiers[tier].append({
            "agent": agent_name,
            "model": data.get("model", "unknown"),
            "calls": data.get("calls", 0),
            "cost_usd": data.get("cost_usd", 0),
        })

    return {
        "tiers": tiers,
        "total_cost_usd": summary.get("total_cost_usd", 0),
        "tier_counts": {k: len(v) for k, v in tiers.items()},
    }


@router.get("/api/analytics/locality")
async def analytics_locality():
    """% of agent runs served on-device vs cloud (MOONSHOT §6 counter-metric).

    Drives the HUD Trust mode's "%-local" meter with a REAL number from the run
    history's route field — `local_pct` is null until there's at least one routed
    run, so the meter shows "—" rather than a fabricated 100%."""
    orch = get_orch()
    rh = getattr(orch, "run_history", None) if orch else None
    if rh is None:
        return nocache_json({"local_pct": None, "local": 0, "cloud": 0,
                              "unknown": 0, "total": 0})
    return nocache_json(rh.locality())


@router.get("/api/reflection/status")
async def reflection_status():
    """Daily reflection status (H5.15)."""
    orch = get_orch()
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return nocache_json({"enabled": False, "last_run": None, "last_result": None})
    return nocache_json(orch.reflector.status())


@router.post("/api/reflection/run")
async def reflection_run():
    """Trigger nightly reflection manually (H5.15)."""
    orch = get_orch()
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return nocache_json({"ok": False, "error": "reflector not initialized"})
    try:
        # Force re-run by temporarily clearing last_run
        orch.reflector._last_run = None
        result = await orch.reflector.run(
            enabled=orch.get_setting("system.reflection_enabled", True)
        )
        return nocache_json({"ok": True, "result": result})
    except Exception as e:
        return error_json(e, 200, "reflection run failed", extra={"ok": False})


# ── H9.2 Trace Explorer endpoints ────────────────────────────────

@router.get("/api/traces")
async def list_traces(limit: int = Query(50, ge=1, le=200)):
    """Return recent per-request traces (most-recent first, summarized)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"traces": [], "error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return nocache_json({"traces": [], "error": "tracer not available"})
    limit = max(1, min(limit, 500))
    return nocache_json({"traces": tracer.list(limit)})


@router.get("/api/cost")
async def cost_breakdown():
    """H10.24 — estimated $ cost per agent and per day (local models = $0)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return nocache_json(
            {"by_agent": [], "by_day": [], "summary": {}, "error": "tracer not available"}
        )
    return nocache_json({
        "by_agent": tracer.cost_by_agent(),
        "by_day": tracer.cost_by_day(),
        "summary": tracer.cost_summary(),
    })


@router.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Return the full trace dict for a specific trace id."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return nocache_json({"error": "tracer not available"}, status_code=503)
    item = tracer.get(trace_id)
    if item is None:
        return nocache_json({"error": f"trace '{trace_id}' not found"}, status_code=404)
    return nocache_json(item)


@router.post("/api/traces/clear")
async def clear_traces():
    """Flush all traces from the in-memory ring buffer."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return nocache_json({"error": "tracer not available"}, status_code=503)
    tracer.clear()
    return nocache_json({"ok": True})
