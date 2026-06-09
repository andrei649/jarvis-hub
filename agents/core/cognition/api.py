"""
api.py — cognition APIRouter (H21.0).

A dedicated FastAPI router (mounted by web.py) so cognition endpoints don't grow
the web.py god-object (CLN-3 direction). For the skeleton this is just a status
probe that reflects the (all-OFF) flags.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/cognition", tags=["cognition"])


def _facade():
    # Lazy access to the orchestrator's facade (avoids an import cycle at load).
    from agents import web
    orch = getattr(web, "orch", None)
    return getattr(orch, "cognition", None) if orch else None


@router.get("/status")
async def cognition_status():
    """H21.0 — cognition flags (master + sub-capabilities); all OFF by default."""
    f = _facade()
    if f is None:
        return {"enabled": False, "available": False}
    return f.status()


@router.get("/honesty")
async def cognition_honesty():
    """H21.1 — Sycophancy Index + alert (anti-sycophancy axis)."""
    f = _facade()
    m = f.module("honesty") if f is not None else None
    if m is None:
        return {"available": False}
    return m.status()


@router.get("/personality")
async def cognition_personality():
    """H21.2 — persona module status (configured agents)."""
    f = _facade()
    m = f.module("persona") if f is not None else None
    if m is None:
        return {"available": False}
    return m.status()


@router.get("/memory")
async def cognition_memory():
    """H21.3 — living-memory status (tier counts, core size, embed version)."""
    f = _facade()
    m = f.module("memory") if f is not None else None
    if m is None:
        return {"available": False}
    return m.status()


@router.get("/learning")
async def cognition_learning():
    """H21.4 — governed-learning status (KC count, corrections)."""
    f = _facade()
    m = f.module("learning") if f is not None else None
    if m is None:
        return {"available": False}
    return m.status()


@router.get("/ensemble")
async def cognition_ensemble():
    """H21.5 — ensemble diversity + maturation status."""
    f = _facade()
    m = f.module("ensemble") if f is not None else None
    if m is None:
        return {"available": False}
    return m.status()


async def _cognition_events(get_cog, *, sleep=asyncio.sleep, interval=1.0,
                            heartbeat_every=15, max_iterations=None):
    """NTH-1 — yield SSE frames for live cognition scoring.

    Emits a ``data:`` frame whenever the ``last_cognition`` snapshot changes and a
    ``: keepalive`` comment every ``heartbeat_every`` idle ticks. ``get_cog`` and
    ``sleep`` are injected so the generator is deterministically testable offline.
    """
    last_sig = None
    idle = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        cog = get_cog()
        sig = json.dumps(cog, sort_keys=True, default=str) if cog else ""
        if cog and sig != last_sig:
            last_sig = sig
            idle = 0
            yield f"data: {json.dumps({'type': 'cognition', 'cognition': cog})}\n\n"
        else:
            idle += 1
            if heartbeat_every and idle % heartbeat_every == 0:
                yield ": keepalive\n\n"
        await sleep(interval)


def _live_cognition():
    """Current ``last_cognition`` snapshot from the live orchestrator (or None)."""
    from agents import web
    orch = getattr(web, "orch", None)
    return getattr(orch, "last_cognition", None) if orch else None


@router.get("/stream")
async def cognition_stream():
    """NTH-1 — server-sent stream of live cognition scoring (vs the static
    ``/api/cognition`` snapshot), so the HUD can show routing decisions as they
    happen."""
    return StreamingResponse(
        _cognition_events(_live_cognition),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
