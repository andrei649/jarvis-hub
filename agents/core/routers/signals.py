"""signals.py router — T-0.41 World Signal Packs: the live feed wired through routing.

`agents/core/signal_routing.py` (classify → per-domain → per-agent) shipped as a
pure, fully-tested module with **no caller** — nothing fetched live signals and
ran them through it, so the routing existed only in its own unit test. This is
the missing wiring: the Signal Layer sidecar's live `signals()` feed, routed into
per-domain and per-agent slices plus the per-domain brief.

Read-only, user-guarded, and honest by construction:

* no sidecar plugin configured → ``available: false`` with a reason, empty slices;
* sidecar configured but unreachable → the plugin's own ``unavailable`` status is
  surfaced verbatim, never replaced with fabricated signals;
* an unclassifiable signal stays visible in ``unrouted`` (``signal_routing``'s own
  contract) rather than being force-labeled into a domain.

The sidecar fetch is `await`ed directly — `SignalLayerPlugin` is already async
(httpx), so there is no blocking call to offload here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Query

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.signal_governance import GOVERNANCE_FLAG, TASK_KIND
from agents.core.signal_routing import AGENT_INTERESTS, build_domain_brief, route_signals
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.signals")

router = APIRouter(tags=["signals"])

_EMPTY = {
    "signals": [], "by_domain": {}, "by_agent": {}, "unrouted": [],
    "counts": {"signals": 0, "routed": 0, "unrouted": 0},
}


async def _live_signals(limit: int) -> tuple[list[dict], dict, str | None]:
    """Fetch the sidecar's current signals. Returns ``(signals, freshness, reason)``
    where a non-None *reason* means nothing was fetched (and signals is empty)."""
    orch = get_orch()
    plugin = (getattr(orch, "plugins", None) or {}).get("signal-layer") if orch else None
    if plugin is None:
        return [], {}, "signal_layer_plugin_unavailable"
    try:
        body = await plugin.signals(limit=limit)
    except Exception:
        logger.warning("signal-layer fetch failed", exc_info=True)
        return [], {}, "fetch_failed"
    if not isinstance(body, dict) or body.get("status") != "ok":
        return [], {}, str((body or {}).get("status") or "unavailable")
    return list(body.get("signals") or []), dict(body.get("freshness") or {}), None


@router.get("/api/signals/routed", dependencies=[Depends(user_guard)])
async def signals_routed(limit: int = Query(20, ge=1, le=200)):
    """Live signals classified per domain and sliced per interested agent."""
    signals, freshness, reason = await _live_signals(limit)
    if reason is not None:
        return nocache_json({"available": False, "reason": reason, "freshness": {}, **_EMPTY})
    routed = route_signals(signals)
    return nocache_json({
        "available": True, "reason": None, "freshness": freshness,
        "signals": routed["signals"],
        "by_domain": routed["by_domain"],
        "by_agent": routed["by_agent"],
        "unrouted": routed["unrouted"],
        "counts": routed["counts"],
    })


@router.get("/api/signals/agent/{agent_id}", dependencies=[Depends(user_guard)])
async def signals_for_agent(
    agent_id: str = Path(..., min_length=1, max_length=64),
    limit: int = Query(20, ge=1, le=200),
):
    """One agent's slice of the live feed — exactly the domains it subscribes to.

    An agent with no declared interests is reported ``known_agent: false`` with an
    empty slice, never silently given the whole feed.
    """
    known = agent_id in AGENT_INTERESTS
    signals, freshness, reason = await _live_signals(limit)
    if reason is not None or not known:
        return nocache_json({
            "agent": agent_id, "known_agent": known, "available": reason is None,
            "reason": reason, "domains": list(AGENT_INTERESTS.get(agent_id, ())),
            "signals": [], "count": 0, "freshness": {},
        })
    routed = route_signals(signals)
    idx = routed["by_agent"].get(agent_id, [])
    picked = [routed["signals"][i] for i in idx]
    return nocache_json({
        "agent": agent_id, "known_agent": True, "available": True, "reason": None,
        "domains": list(AGENT_INTERESTS[agent_id]),
        "signals": picked, "count": len(picked), "freshness": freshness,
    })


@router.get("/api/signals/brief/{domain}", dependencies=[Depends(user_guard)])
async def signals_domain_brief(
    domain: str = Path(..., min_length=1, max_length=64),
    top: int = Query(5, ge=1, le=50),
    limit: int = Query(20, ge=1, le=200),
):
    """A compact per-domain brief over the live feed (severity-ranked, honest empties)."""
    signals, freshness, reason = await _live_signals(limit)
    if reason is not None:
        return nocache_json({
            "domain": domain, "known_domain": None, "available": False, "reason": reason,
            "top": [], "count": 0, "headline": "signal layer unavailable", "freshness": {},
        })
    brief = build_domain_brief(signals, domain, top=top)
    return nocache_json({**brief, "available": True, "reason": None, "freshness": freshness})


def _bridge():
    """The orchestrator's SignalGovernanceBridge, or None if it isn't constructed."""
    orch = get_orch()
    return getattr(orch, "signal_governance", None) if orch else None


@router.get("/api/signals/governance", dependencies=[Depends(user_guard)])
async def signals_governance_status():
    """Whether the Signal Layer -> approval-inbox bridge is live, and what it has queued.

    Reads real state, never writes: the bridge's own ``enabled`` flag plus the
    number of ``signal_recommendation`` items already sitting in the decision
    inbox. Off is the default and is reported as a fact, not an error -- the flag
    is the owner's to flip. Submitting is the POST below, never this.
    """
    bridge = _bridge()
    if bridge is None:
        return nocache_json({
            "available": False, "reason": "signal_governance_unavailable",
            "enabled": False, "flag": GOVERNANCE_FLAG, "kind": TASK_KIND, "pending": 0,
        })
    try:
        pending = sum(1 for t in bridge.queue.pending_decisions() if t.kind == TASK_KIND)
    except Exception:
        logger.warning("signal governance pending read failed", exc_info=True)
        pending = 0
    return nocache_json({
        "available": True, "reason": None,
        "enabled": bool(bridge.enabled), "flag": GOVERNANCE_FLAG,
        "kind": TASK_KIND, "pending": pending,
        "note": "Preview only. Every queued item lands BLOCKED, awaiting a human decision.",
    })


@router.post("/api/signals/governance/submit", dependencies=[Depends(user_guard)])
async def signals_governance_submit():
    """Route the live world brief's actionable recommendations into the approval inbox.

    Honest at every step: no bridge -> ``available: false``; no sidecar -> the
    plugin's own reason verbatim; bridge off -> ``status: "disabled"`` with
    nothing queued. All of those are ``200`` -- from this surface a refusal is a
    real answer, not a transport error. Nothing is ever approved or executed here.
    """
    empty = {"status": "unavailable", "queued": 0, "task_ids": [], "skipped": 0}
    bridge = _bridge()
    if bridge is None:
        return nocache_json({
            "available": False, "reason": "signal_governance_unavailable", **empty,
        })

    orch = get_orch()
    plugin = (getattr(orch, "plugins", None) or {}).get("signal-layer") if orch else None
    if plugin is None:
        return nocache_json({
            "available": False, "reason": "signal_layer_plugin_unavailable", **empty,
        })
    try:
        body = await plugin.world_brief()
    except Exception:
        logger.warning("signal-layer world_brief fetch failed", exc_info=True)
        return nocache_json({"available": False, "reason": "fetch_failed", **empty})
    if not isinstance(body, dict) or body.get("status") != "ok":
        reason = str((body or {}).get("status") or "unavailable")
        return nocache_json({"available": False, "reason": reason, **empty})

    out = bridge.submit_from_brief(body.get("brief"))
    return nocache_json({"available": True, "reason": None, **out})
