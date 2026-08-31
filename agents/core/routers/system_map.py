"""H34.7 Live System Map — the architecture diagram as a realtime monitoring surface.

Serves the standalone map page (``GET /map``) and the read-only feed
(``GET /api/system-map``) that lights it: one bounded snapshot reducing every
subsystem in ``agents/core/system_map/topology.json`` to an honest status
(``ok | degraded | attention | off | unknown``) plus a few headline stats, and
every declared edge to a real traffic counter.

Rules this surface lives by (plan: docs/superpowers/plans/2026-08-31-live-system-map.md):

- **One bounded read.** Every reducer composes *existing* cached readers
  (tracer rollups, plugin honesty verdicts, kernel metrics, egress tallies,
  queue stats). Nothing here probes the network or blocks the event loop.
- **Unknown never renders green.** A reader that raises, or a subsystem with
  no evidence, reduces to ``unknown`` — a first-class, visibly gray state.
- **Payload-free.** Statuses, counts and model/backend names only — never task
  payloads, prompts, results, or memory content (H34.6 discipline).
- **Read-only.** Steering stays on Mission Control's governed endpoints.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from agents.core.app_state import get_orch
from agents.core.env_config import env_flag
from agents.core.routers._deps import user_guard
from agents.core.system_map import load_topology
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["system-map"])

_MAP_HTML = Path(__file__).resolve().parents[2] / "web" / "system_map.html"
_SPA_INDEX = Path(__file__).resolve().parents[2] / "web" / "v2" / "index.html"

_TRACE_LIMIT = 1000
_ACTIVE_WINDOW_S = 60
_CLOUD_MODEL_MARKERS = ("gemini", "claude", "gpt", "sonnet", "opus", "haiku", "flash")

_UNKNOWN = {"status": "unknown", "stats": {}, "evidence": None}


def _safe(fn, default=None):
    """A partially initialized orchestrator must never 500 the feed."""
    try:
        return fn()
    except Exception:
        return default


def _node(status: str, stats: dict, evidence: str) -> dict:
    return {"status": status, "stats": stats, "evidence": evidence}


# ── per-source reducers ───────────────────────────────────────────────────────
# One function per `health_source` declared in topology.json. The parity test
# (tests/test_system_map.py) fails if a declared source has no reducer here, so
# the map cannot claim a subsystem it does not actually read.


def _reduce_spa_bundle(orch, ctx) -> dict:
    present = _SPA_INDEX.is_file()
    return _node("ok" if present else "unknown", {"bundle_present": present}, "web/v2/index.html")


def _reduce_channel_manager(orch, ctx) -> dict:
    if orch is None:
        return dict(_UNKNOWN)
    channels = _safe(lambda: dict(orch.channels), None)
    if channels is None:
        return dict(_UNKNOWN)
    names = sorted(str(k) for k in channels)[:12]
    status = "ok" if names else "off"
    return _node(status, {"registered": len(names), "names": names}, "orch.channels")


def _reduce_app_shell(orch, ctx) -> dict:
    # If this reducer is running, the shell answered the request — that IS the
    # evidence. Route count comes from the live app when importable.
    routes = _safe(lambda: len(__import__("agents.web", fromlist=["app"]).app.routes), None)
    stats = {"serving": True}
    if isinstance(routes, int):
        # Route *objects* (routers mount many paths each) — deliberately not
        # named "routes" so it can't be misread as the canonical path count.
        stats["route_objects"] = routes
    return _node("ok", stats, "request served")


def _reduce_orchestrator(orch, ctx) -> dict:
    if orch is None:
        return _node("attention", {"initialized": False}, "app_state.get_orch")
    agents = _safe(lambda: len(orch.agents or {}), None)
    stats: dict = {"initialized": True, "turns_60s": ctx.get("turns_60s", 0)}
    if isinstance(agents, int):
        stats["agents"] = agents
    return _node("ok", stats, "orchestrator")


def _reduce_agent_roster(orch, ctx) -> dict:
    if orch is None:
        return dict(_UNKNOWN)
    roster = _safe(lambda: sorted(str(a) for a in (orch.agents or {})), None)
    if roster is None:
        return dict(_UNKNOWN)
    active = ctx.get("active_agents_60s", 0)
    status = "ok" if roster else "attention"
    return _node(status, {"agents": len(roster), "active_60s": active}, "orch.agents + tracer")


def _reduce_llm_router(orch, ctx) -> dict:
    lr = getattr(orch, "llm_router", None) if orch is not None else None
    if lr is None:
        return dict(_UNKNOWN)
    local = bool(_safe(lambda: lr._local_available, False))
    cloud = bool(_safe(lambda: lr._cloud_available, False)) or bool(
        _safe(lambda: lr._claude_available, False)
    )
    status = "ok" if (local or cloud) else "attention"
    stats = {
        "routes": _safe(lambda: str(lr.name), "—"),
        "backend_type": _safe(lambda: str(getattr(lr, "backend_type", "auto")), "auto"),
    }
    return _node(status, stats, "hybrid_router")


def _reduce_local_llm(orch, ctx) -> dict:
    lr = getattr(orch, "llm_router", None) if orch is not None else None
    if lr is None:
        return dict(_UNKNOWN)
    available = _safe(lambda: bool(lr._local_available), None)
    if available is None:
        return dict(_UNKNOWN)
    stats = {
        "available": available,
        "model": _safe(lambda: str(lr._local_model), "—") if available else "—",
        "backend": _safe(lambda: str(getattr(lr, "_backend_name", "—")), "—"),
    }
    # Local-first product: local backend down is a real signal, not a shrug.
    return _node("ok" if available else "attention", stats, "hybrid_router.local")


def _reduce_cloud_llm(orch, ctx) -> dict:
    lr = getattr(orch, "llm_router", None) if orch is not None else None
    if lr is None:
        return dict(_UNKNOWN)
    gemini = bool(_safe(lambda: lr._cloud_available, False))
    claude = bool(_safe(lambda: lr._claude_available, False))
    configured = gemini or claude
    stats = {"configured": configured, "gemini": gemini, "claude": claude,
             "cloud_turns_60s": ctx.get("cloud_turns_60s", 0)}
    # Opt-in surface: not configured is the honest default, not a failure.
    return _node("ok" if configured else "off", stats, "hybrid_router.cloud")


def _reduce_memory_manager(orch, ctx) -> dict:
    mem = getattr(orch, "memory", None) if orch is not None else None
    if mem is None:
        return dict(_UNKNOWN)
    vectors = _safe(lambda: len(mem.vectors), None)
    entities = _safe(lambda: len(mem.graph.entities), None)  # in-memory backend only
    recall = _safe(lambda: bool(orch.get_setting("memory.recall_enabled", False)), None)
    stats: dict = {}
    if isinstance(vectors, int):
        stats["vectors"] = vectors
    if isinstance(entities, int):
        stats["graph_entities"] = entities
    if recall is not None:
        stats["recall_enabled"] = recall
    return _node("ok" if stats else "unknown", stats, "memory_manager")


def _reduce_plugin_honesty(orch, ctx) -> dict:
    plugins = getattr(orch, "plugins", None) if orch is not None else None
    if not isinstance(plugins, dict):
        return dict(_UNKNOWN)
    from agents.core.plugins.honesty import (
        degradation_info,
        honesty_for,
        runtime_configuration,
    )

    counts = {"live": 0, "needs_config": 0, "unknown": 0}
    mock_active = 0
    for pid, plugin in plugins.items():
        configured, source = _safe(lambda p=plugin: runtime_configuration(p), (False, ""))
        degraded = bool(_safe(lambda p=plugin: degradation_info(p), None))
        verdict = _safe(
            lambda i=pid, c=configured, s=source, d=degraded: honesty_for(
                str(i), bool(c), str(s), d),
            {"status": "unknown"},
        )
        counts[str(verdict.get("status", "unknown"))] = (
            counts.get(str(verdict.get("status", "unknown")), 0) + 1
        )
        if degraded:
            mock_active += 1

    violations = ctx.get("egress_violations", [])
    if violations:
        status = "attention"  # a LOCAL_ONLY plugin made an external call
    elif mock_active:
        status = "degraded"  # something is actively serving mock data
    else:
        status = "ok"
    stats = dict(counts, mock_active=mock_active, egress_violations=len(violations))
    return _node(status, stats, "plugins.honesty + egress_monitor")


def _reduce_autonomy_queue(orch, ctx) -> dict:
    if orch is None:
        return dict(_UNKNOWN)
    stats_raw = _safe(lambda: dict(orch.autonomy_queue.stats() or {}), None)
    if stats_raw is None:
        return dict(_UNKNOWN)
    budget = _safe(
        lambda: {
            "remaining": orch.autonomy.budget.remaining(),
            "per_day": orch.autonomy.budget.per_day,
        },
        None,
    )
    failed = int(stats_raw.get("failed", 0) or 0)
    pending = int(stats_raw.get("pending", 0) or stats_raw.get("blocked", 0) or 0)
    status = "attention" if failed > 0 else "ok"
    stats: dict = {"pending": pending, "failed": failed,
                   "done": int(stats_raw.get("done", 0) or 0)}
    if budget:
        stats["interrupts_left"] = budget.get("remaining")
    return _node(status, stats, "autonomy_queue.stats")


def _reduce_action_kernel(orch, ctx) -> dict:
    enabled = env_flag("JARVIS_ACTION_KERNEL", False)
    snap = _safe(lambda: __import__(
        "agents.core.kernel.metrics", fromlist=["KERNEL_METRICS"]
    ).KERNEL_METRICS.snapshot(), {}) or {}
    halted = _safe(lambda: bool(orch.kill_switch.is_halted()), None) if orch else None
    tripped = None
    if orch is not None:
        tripped = _safe(lambda: bool(orch.loop_detector.status().get("tripped")), None)
    totals = snap.get("totals") or {k: snap.get(k) for k in ("grant", "deny", "queue") if k in snap}
    stats: dict = {"enabled": enabled, "decisions": totals or {},
                   "kill_switch": ("halted" if halted else "armed") if halted is not None else "—"}
    if tripped is not None:
        stats["loop_breaker"] = "tripped" if tripped else "closed"
    if halted or tripped:
        status = "attention"
    elif not enabled:
        status = "off"  # the risk-tier gate still runs; the kernel rail is opt-in
    else:
        status = "ok"
    return _node(status, stats, "kernel_metrics + kill_switch + loop_breaker")


# Registry keyed by topology `health_source` — the parity test walks this.
HEALTH_REDUCERS = {
    "spa_bundle": _reduce_spa_bundle,
    "channel_manager": _reduce_channel_manager,
    "app_shell": _reduce_app_shell,
    "orchestrator": _reduce_orchestrator,
    "agent_roster": _reduce_agent_roster,
    "llm_router": _reduce_llm_router,
    "local_llm": _reduce_local_llm,
    "cloud_llm": _reduce_cloud_llm,
    "memory_manager": _reduce_memory_manager,
    "plugin_honesty": _reduce_plugin_honesty,
    "autonomy_queue": _reduce_autonomy_queue,
    "action_kernel": _reduce_action_kernel,
}


# Every activity_source an edge may declare — the parity test's right-hand side.
ACTIVITY_SOURCES = (
    "turns_60s", "inbound_turns_60s", "local_turns_60s", "cloud_turns_60s",
    "kernel_decisions", "interrupts_today",
)


# ── shared context: one tracer pass + one egress read feed several reducers ──


def _build_context(orch, now: float) -> dict:
    ctx: dict = {"turns_60s": 0, "inbound_turns_60s": 0, "local_turns_60s": 0,
                 "cloud_turns_60s": 0, "active_agents_60s": 0, "egress_violations": []}
    traces = _safe(lambda: orch.tracer.list(limit=_TRACE_LIMIT), []) if orch else []
    active: set[str] = set()
    internal_channels = {"web", "voice", "internal", "eval", "workflow", ""}
    for t in traces:
        if not isinstance(t, dict):
            continue
        ts = _safe(lambda tr=t: float(tr.get("ts") or 0), 0.0)
        if now - ts > _ACTIVE_WINDOW_S:
            continue
        ctx["turns_60s"] += 1
        agent = str(t.get("route") or "")
        if agent:
            active.add(agent)
        if str(t.get("channel") or "") not in internal_channels:
            ctx["inbound_turns_60s"] += 1
        model = str(t.get("model") or "").lower()
        if model and model != "—":
            if any(m in model for m in _CLOUD_MODEL_MARKERS):
                ctx["cloud_turns_60s"] += 1
            else:
                ctx["local_turns_60s"] += 1
    ctx["active_agents_60s"] = len(active)
    egress = _safe(lambda: __import__(
        "agents.core.observability.egress_monitor", fromlist=["EGRESS_MONITOR"]
    ).EGRESS_MONITOR.snapshot(limit=0), {}) or {}
    ctx["egress_violations"] = list(egress.get("local_only_violations") or [])
    return ctx


def _edge_activity(orch, ctx) -> dict:
    """Per-edge counters. An edge whose source produced nothing is OMITTED —
    the client renders it static rather than pulsing a fabricated number."""
    kernel_totals = _safe(lambda: __import__(
        "agents.core.kernel.metrics", fromlist=["KERNEL_METRICS"]
    ).KERNEL_METRICS.snapshot(), {}) or {}
    totals = kernel_totals.get("totals") or {}
    kernel_decisions = None
    if isinstance(totals, dict) and totals:
        kernel_decisions = sum(v for v in totals.values() if isinstance(v, (int, float)))
    interrupts_today = None
    if orch is not None:
        used = _safe(
            lambda: orch.autonomy.budget.per_day - orch.autonomy.budget.remaining(), None
        )
        if isinstance(used, (int, float)):
            interrupts_today = int(used)
    values = {
        "turns_60s": ctx.get("turns_60s"),
        "inbound_turns_60s": ctx.get("inbound_turns_60s"),
        "local_turns_60s": ctx.get("local_turns_60s"),
        "cloud_turns_60s": ctx.get("cloud_turns_60s"),
        "kernel_decisions": kernel_decisions,
        "interrupts_today": interrupts_today,
    }
    # `values` and ACTIVITY_SOURCES are kept aligned by the parity test.
    out: dict = {}
    for edge in load_topology()["edges"]:
        source = edge.get("activity_source")
        if not source:
            continue
        val = values.get(source)
        if val is None:
            continue
        out[edge["id"]] = {"count": int(val), "source": source}
    return out


def build_system_map(orch) -> dict:
    """The whole feed: topology version + per-node status + per-edge activity."""
    now = time.time()
    topo = load_topology()
    ctx = _build_context(orch, now)
    nodes = {}
    for node in topo["nodes"]:
        reducer = HEALTH_REDUCERS.get(node["health_source"])
        if reducer is None:  # unreachable while the parity test holds
            nodes[node["id"]] = dict(_UNKNOWN)
            continue
        nodes[node["id"]] = _safe(lambda r=reducer: r(orch, ctx), dict(_UNKNOWN))
    return {
        "version": 1,
        "topology_version": topo["version"],
        "generated_at": now,
        "initialized": orch is not None,
        "nodes": nodes,
        "edges": _edge_activity(orch, ctx),
    }


@router.get("/map", dependencies=[Depends(user_guard)])
async def system_map_page():
    """The standalone Live System Map page (wall-screen / second monitor)."""
    if not _MAP_HTML.is_file():
        return JSONResponse({"error": "system_map.html not found"}, status_code=404)
    return FileResponse(str(_MAP_HTML), media_type="text/html")


@router.get("/api/system-map", dependencies=[Depends(user_guard)])
async def system_map_feed():
    """Live subsystem-health snapshot driving the map — read-only."""
    feed = build_system_map(get_orch())
    feed["topology"] = load_topology()
    return nocache_json(feed)
