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
