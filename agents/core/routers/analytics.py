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

import json as _json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import error_json, nocache_json, safe_reflect

router = APIRouter(tags=["observe"])


# ── H22 first-party local analytics: beacon ingest ───────────────────

class AnalyticsEvent(BaseModel):
    """Validated body for the public analytics beacon (H22).

    Deliberately tiny: a page-view / custom event. Nothing sensitive — `props`
    is a small free-form bag, `session_id` is an opaque per-visit token (not a
    user id). Lengths are bounded so the public ingest can't bloat the table;
    the store clips again as a backstop. extra='forbid' rejects junk keys."""

    model_config = {"extra": "forbid"}

    name: str = Field(..., min_length=1, max_length=128)
    path: str | None = Field(default=None, max_length=512)
    referrer: str | None = Field(default=None, max_length=512)
    session_id: str | None = Field(default=None, max_length=128)
    props: dict | None = Field(default=None)

    @field_validator("props")
    @classmethod
    def _bound_props(cls, v):
        """Bound the one free-form field at the parse layer (review #2): the other
        fields are length-capped, but ``props`` was unbounded → reject (422) an
        oversized bag rather than buffer/parse it."""
        if v is None:
            return v
        if len(v) > 30:
            raise ValueError("props has too many keys (max 30)")
        if len(_json.dumps(v, ensure_ascii=False)) > 2048:
            raise ValueError("props too large (max 2048 bytes serialized)")
        return v


@router.post("/api/analytics/event")
async def ingest_analytics_event(event: AnalyticsEvent):
    """Ingest a single first-party analytics event (privacy-first, local-only).

    Public beacon by design (page-view tracking must work without auth), but it
    is rate-limited by the global unauthenticated throttle and writes nothing
    sensitive — a single bounded INSERT into the local events table. Aggregation
    happens on read (`/api/analytics/*` KPIs), Plausible-style. CLN-3: route lives
    here; auth-matrix classifies it INTENTIONALLY_OPEN (public ingress, mints
    nothing)."""
    from agents.core import analytics_store
    try:
        event_id = analytics_store.record_event(
            event.name,
            path=event.path,
            referrer=event.referrer,
            props=event.props,
            session_id=event.session_id,
        )
        return nocache_json({"ok": True, "id": event_id})
    except Exception as e:
        return error_json(e, 200, "analytics ingest failed", extra={"ok": False})


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


@router.get("/api/metrics/north-star")
async def metrics_north_star(days: int = Query(7, ge=1, le=90)):
    """The MOONSHOT §6 metric set in one call — north-star + counter-metrics.

    Weekly autonomous actions *accepted* per active user, plus interrupt rate,
    reject rate, %-local, and p95 per-turn non-LLM latency. Open like the sibling
    analytics/locality + traces meters (non-sensitive aggregate counts; the whole
    app is localhost-only until a token is set). Single-user today, so the meter
    reports `active_users` honestly rather than fabricating a fleet."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    queue = getattr(orch, "autonomy_queue", None)
    if queue is None:
        return nocache_json({"error": "autonomy queue not available"}, status_code=503)
    from agents.core.observability.north_star import compute_north_star
    # Mirror the worker's local-time night window (autonomy.night_start/end) so the
    # night-shift split matches what actually gated the overnight tier caps.
    get_setting = getattr(orch, "get_setting", None)
    try:
        night_window = (
            int(get_setting("autonomy.night_start", 23) or 23),
            int(get_setting("autonomy.night_end", 6) or 6),
        ) if callable(get_setting) else (23, 6)
    except (TypeError, ValueError):
        night_window = (23, 6)
    return nocache_json(compute_north_star(
        queue,
        getattr(orch, "run_history", None),
        getattr(orch, "tracer", None),
        budget=getattr(getattr(orch, "autonomy", None), "budget", None),
        attention_ledger=getattr(orch, "attention_ledger", None),
        days=days,
        night_window=night_window,
    ))


@router.get("/api/metrics/capabilities")
async def metrics_capabilities():
    """V2 — capability readiness registry: a SEAM/WIRED/VERIFIED/GA state per capability.

    Derived from the plugin/component/skill registries (ORIZONT 24 Track V); makes
    "looks done, isn't wired" a visible state instead of a per-caller guess. Open like
    the sibling north-star meter (non-sensitive aggregate; the app is localhost-only
    until a token is set). 503 until the orchestrator is up. Nothing is VERIFIED until
    the reality harness (V1) lands — `harness_pending` reflects that honestly."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    from agents.core.observability.capability_registry import snapshot
    return nocache_json(snapshot(orch))


@router.get("/api/capabilities", dependencies=[Depends(user_guard)])
async def capabilities():
    """Canonical user-facing capability inventory (H27.8).

    Extends the legacy metrics surface without removing it: the same live registry snapshot is
    available here under the normal user guard for planners and product clients.
    """
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    from agents.core.observability.capability_registry import snapshot
    return nocache_json(snapshot(orch))


@router.get("/api/metrics/kernel")
async def metrics_kernel():
    """Live tally of Action-Kernel decisions — grant/deny/queue per action kind, deny-rate,
    and the recent denials (with reasons, so a halt / runaway / over-budget is visible).

    In-memory observability (resets on restart; the IntentLog audit chain is the durable
    record). Open like the sibling meters. Empty until `JARVIS_ACTION_KERNEL` is on and
    actions are actually mediated — no orchestrator dependency (a module-level meter)."""
    from agents.core.kernel.metrics import KERNEL_METRICS
    return nocache_json(KERNEL_METRICS.snapshot())


@router.get("/api/reflection/status")
async def reflection_status():
    """Daily reflection status (H5.15)."""
    orch = get_orch()
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return nocache_json({"enabled": False, "last_run": None, "last_result": None})
    return nocache_json(orch.reflector.status())


@router.post("/api/reflection/run", dependencies=[Depends(user_guard)])
async def reflection_run():
    """Trigger nightly reflection manually (H5.15)."""
    orch = get_orch()
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return nocache_json({"ok": False, "error": "reflector not initialized"})
    try:
        result = await orch.reflector.run(
            enabled=orch.get_setting("system.reflection_enabled", True),
            force=True,
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
        return nocache_json({"error": f"trace '{safe_reflect(trace_id)}' not found"}, status_code=404)
    return nocache_json(item)


@router.post("/api/traces/clear", dependencies=[Depends(admin_guard)])
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
