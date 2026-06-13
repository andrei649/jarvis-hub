"""Wyoming protocol endpoints (H12.4) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["wyoming"])


@router.get("/api/voice/wyoming")
async def wyoming_status():
    """Wyoming protocol support status (H12.4)."""
    from agents.core.voice.wyoming import PROTOCOL_VERSION
    orch = get_orch()
    enabled = bool(orch and orch.get_setting("voice.wyoming_enabled", False))
    port = int(orch.get_setting("voice.wyoming_port", 10700)) if orch else 10700
    return nocache_json({
        "protocol": "wyoming",
        "version": PROTOCOL_VERSION,
        "enabled": enabled,
        "port": port,
        "role": "handle",  # transcript → reply-to-speak
    })
