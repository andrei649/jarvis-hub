"""JARVIS Neural Mesh — live brain visualization (page + telemetry feed).

Serves the neural-mesh page (`GET /brain`) and the JSON feed (`GET
/api/brain/summary`) that drives it. The summary aggregates the request tracer
(per-agent / per-model token + cost rollups) into the shape the canvas renderer
expects, seeded with the live agent roster so the mesh shows every node — core,
models, agents — even when the system is idle, then lights up the nodes with
real traffic.

The visualization is adapted from Axon's "NEURAL MESH" by Daniel Tamas, used
under the MIT License — see ``LICENSES/axon-MIT.txt``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["brain"])

# agents/core/routers/brain.py → parents[2] == agents/  → web/brain.html
_BRAIN_HTML = Path(__file__).resolve().parents[2] / "web" / "brain.html"

_RANGE_WINDOWS = {"7d": 7 * 86400, "30d": 30 * 86400}


def _backend_for(model: str) -> str:
    """Map a model id to the JARVIS backend ('harness') that served it."""
    m = (model or "").lower()
    if "claude" in m:
        return "claude"
    if "gemini" in m:
        return "gemini"
    return "local"


def _today_start(now: float) -> float:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _cutoff(rng: str, now: float) -> float | None:
    if rng == "today":
        return _today_start(now)
    secs = _RANGE_WINDOWS.get(rng)
    return (now - secs) if secs else None


def build_summary(orch, rng: str = "all") -> dict:
    """Aggregate the tracer (+ live roster) into the neural-mesh feed shape."""
    now = time.time()
    tracer = getattr(orch, "tracer", None) if orch else None
    traces = tracer.list(limit=10000) if tracer is not None else []

    cutoff = _cutoff(rng, now)
    if cutoff is not None:
        traces = [t for t in traces if float(t.get("ts") or 0) >= cutoff]

    # ── seed the mesh with the full live roster (zero-cost nodes) ─────────────
    ag_agg: dict[str, dict] = {}
    md_agg: dict[str, dict] = {}

    def _node(store: dict, key: str) -> dict:
        return store.setdefault(key, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0})

    if orch is not None:
        for aid, ag in (getattr(orch, "agents", None) or {}).items():
            if aid == "jarvis":  # the orchestrator itself is the mesh core, not a ring node
                continue
            _node(ag_agg, aid)
            mdl = (getattr(ag, "config", None) or {}).get("model")
            if mdl:
                _node(md_agg, mdl)

    # ── overlay real activity ────────────────────────────────────────────────
    hn_agg: dict[str, dict] = {}
    tot_in = tot_out = 0
    tot_cost = today_c = week_c = month_c = 0.0
    t_start, w_start, m_start = _today_start(now), now - 7 * 86400, now - 30 * 86400
    channels: set[str] = set()
    recent: list[dict] = []

    for t in traces:
        agent = t.get("route") or (t.get("agents") or [""])[0] or "unknown"
        if agent == "jarvis":
            agent = "unknown"
        model = t.get("model") or "—"
        ti = int(t.get("tokens_in") or 0)
        to = int(t.get("tokens_out") or 0)
        cost = float(t.get("cost") or 0.0)
        harness = _backend_for(model)

        a = _node(ag_agg, agent)
        a["tokens_in"] += ti
        a["tokens_out"] += to
        a["cost"] += cost
        md = _node(md_agg, model)
        md["tokens_in"] += ti
        md["tokens_out"] += to
        md["cost"] += cost
        h = hn_agg.setdefault(harness, {"cost": 0.0, "events": 0})
        h["cost"] += cost
        h["events"] += 1

        tot_in += ti
        tot_out += to
        tot_cost += cost
        ts = float(t.get("ts") or 0)
        if ts >= t_start:
            today_c += cost
        if ts >= w_start:
            week_c += cost
        if ts >= m_start:
            month_c += cost
        if t.get("channel"):
            channels.add(t["channel"])
        if len(recent) < 60:  # tracer.list() is already newest-first
            recent.append({
                "ts": int(ts * 1000),  # the renderer expects epoch ms
                "agent": agent,
                "model": model,
                "harness": harness,
                "tokens_out": to,
                "cost_eur": round(cost, 6),
                "duration_ms": int(t.get("total_ms") or 0),
            })

    def _rows(store: dict, key: str) -> list[dict]:
        rows = [
            {key: k, "tokens_in": v["tokens_in"], "tokens_out": v["tokens_out"],
             "cost_eur": round(v["cost"], 6)}
            for k, v in store.items()
        ]
        rows.sort(key=lambda r: (r["cost_eur"], r["tokens_out"]), reverse=True)
        return rows

    by_harness = sorted(
        ({"harness": k, "cost_eur": round(v["cost"], 6), "events": v["events"]}
         for k, v in hn_agg.items()),
        key=lambda r: r["cost_eur"], reverse=True,
    )
    active_agents = sum(1 for v in ag_agg.values() if v["tokens_out"] or v["cost"])

    return {
        "range": rng,
        "events": len(traces),
        "sessions": len(channels),       # rendered as "CHANNELS"
        "tokens_in": tot_in,
        "tokens_out": tot_out,
        "loc_added": active_agents,      # rendered as "AGENTS" (fired this window)
        "cost_eur": round(tot_cost, 6),
        "today_cost_eur": round(today_c, 6),
        "week_cost_eur": round(week_c, 6),
        "month_cost_eur": round(month_c, 6),
        "budget_day_eur": None,
        "budget_week_eur": None,
        "budget_month_eur": None,
        "unpriced_models": [],
        "unattributed_token_pct": 0,
        "by_agent": _rows(ag_agg, "agent"),
        "by_model": _rows(md_agg, "model"),
        "by_harness": by_harness,
        "recent": recent,
        "rtk": None,
    }


@router.get("/brain", dependencies=[Depends(user_guard)])
async def brain_page():
    """The JARVIS Neural Mesh page (live brain of agents + models firing)."""
    if not _BRAIN_HTML.is_file():
        return JSONResponse({"error": "brain.html not found"}, status_code=404)
    return FileResponse(str(_BRAIN_HTML), media_type="text/html")


@router.get("/api/brain/summary", dependencies=[Depends(user_guard)])
async def brain_summary(range: str = "all"):
    """Telemetry feed driving the neural mesh — tracer rollups + live roster."""
    rng = range if range in ("today", "7d", "30d", "all") else "all"
    orch = get_orch()
    return nocache_json(build_summary(orch, rng))
