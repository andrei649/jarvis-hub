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
