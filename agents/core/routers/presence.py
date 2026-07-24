"""Owner desk-presence endpoints (H34.2).

A minimal control surface for the owner-side host daemon (Windows idle/lock
watcher or the 0.64 Tauri host overlay) to report whether the owner is at the
machine, plus a read for the HUD / Mission Control.

* ``POST /api/presence/owner`` — admin-guarded (the daemon holds the same
  ``hud.admin_token`` the Mission Control steering uses). Reports a presence
  signal; drives ``orch.owner_presence``. When the state is *away*, the autonomy
  layer additionally fans decision cards out to the escalation channels (see
  ``autonomy/escalation.py::AwayNotifier``) within the ≤4/day interrupt budget.
* ``GET /api/presence/owner`` — user-guarded snapshot of the current state.

Orchestrator-only shared state (``orch.owner_presence``), resolved lazily via
``get_orch()`` like the other extracted routers.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import error_json, nocache_json

router = APIRouter(tags=["presence"])


class PresenceBody(BaseModel):
    state: str = Field(..., min_length=1, max_length=32)
    source: str = Field("", max_length=64)
    idle_seconds: float | None = Field(None, ge=0)


@router.get("/api/presence/owner", dependencies=[Depends(user_guard)])
async def get_owner_presence():
    """Current owner desk-presence snapshot (present / idle / away / unknown)."""
    orch = get_orch()
    presence = getattr(orch, "owner_presence", None) if orch else None
    if presence is None:
        return JSONResponse({"error": "presence not available"}, status_code=503)
    return nocache_json(presence.snapshot().to_dict())


@router.post("/api/presence/owner", dependencies=[Depends(admin_guard)])
async def set_owner_presence(body: PresenceBody):
    """Report an owner desk-presence signal from the host daemon (admin)."""
    orch = get_orch()
    presence = getattr(orch, "owner_presence", None) if orch else None
    if presence is None:
        return JSONResponse({"error": "presence not available"}, status_code=503)
    try:
        snap = presence.update(
            body.state, source=body.source, idle_seconds=body.idle_seconds,
        )
    except ValueError as e:
        # CWE-209-safe: log the detail server-side, return a static message.
        return error_json(e, 422, "unsupported presence state")
    return nocache_json({"ok": True, **snap.to_dict()})
