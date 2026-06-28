"""System Profiles (0.62) — usage-mode posture presets, read-only.

`GET /api/system/profiles` reports the available usage modes (balanced / gaming /
ai / multimedia / admin), which one is active, and the active posture knobs.

Selection is env-driven (`JARVIS_SYSTEM_PROFILE`), consistent with the other
posture presets (`JARVIS_HARDENED`, …) — so this surface is read-only; there's no
mutating route to change it at runtime.
"""

from fastapi import APIRouter, Depends

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["system"])


@router.get("/api/system/profiles", dependencies=[Depends(user_guard)])
async def system_profiles():
    """List usage-mode profiles + the active one + its posture knobs."""
    from agents.core import system_profiles as sp
    return nocache_json(sp.list_profiles())
