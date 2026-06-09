"""
api.py — cognition APIRouter (H21.0).

A dedicated FastAPI router (mounted by web.py) so cognition endpoints don't grow
the web.py god-object (CLN-3 direction). For the skeleton this is just a status
probe that reflects the (all-OFF) flags.
"""

from __future__ import annotations

from fastapi import APIRouter

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
