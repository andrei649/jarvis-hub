"""Wyoming protocol endpoints (H12.4) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter

router = APIRouter(tags=["wyoming"])


@router.get("/api/voice/wyoming")
async def wyoming_status():
    """Wyoming protocol support status (H12.4)."""
    from agents import web
    from agents.core.voice.wyoming import PROTOCOL_VERSION
    orch = web.orch
    enabled = bool(orch and orch.get_setting("voice.wyoming_enabled", False))
    port = int(orch.get_setting("voice.wyoming_port", 10700)) if orch else 10700
    return web._nocache_json({
        "protocol": "wyoming",
        "version": PROTOCOL_VERSION,
        "enabled": enabled,
        "port": port,
        "role": "handle",  # transcript → reply-to-speak
    })
