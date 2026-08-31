"""System Profiles (0.62) — usage-mode posture presets, read-only.

`GET /api/system/profiles` reports the available usage modes (balanced / gaming /
ai / multimedia / admin), which one is active, and the active posture knobs.

`GET /api/system/hardware` (DRA-44) reports what the box actually has — the
spec-based hardware score and the profile it suggests. Deliberately a SEPARATE
route: `/api/system/profiles` is a pure env-only read that `support_bundle.py`
also consumes, and bolting an nvidia-smi subprocess onto it would make every
caller pay for the probe.

Selection is env-driven (`JARVIS_SYSTEM_PROFILE`), consistent with the other
posture presets (`JARVIS_HARDENED`, …) — so this surface is read-only; there's no
mutating route to change it at runtime, and the hardware recommendation is
advisory: it never writes the env.
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


@router.get("/api/system/hardware", dependencies=[Depends(user_guard)])
async def system_hardware():
    """DRA-44 — detected hardware + spec score + the profile it suggests.

    The score is spec-based (VRAM / threads / RAM as reported), NOT a throughput
    benchmark, and every component says whether it was measured — an unprobed
    component scores zero rather than being credited.
    """
    from agents.core import hardware
    from agents.core import system_profiles as sp

    detected = hardware.detect_hardware()
    return nocache_json({
        "detected": detected,
        "score": hardware.score_hardware(detected),
        "recommended_profile": hardware.recommended_profile(detected),
        "active_profile": sp.active_name(),
    })
