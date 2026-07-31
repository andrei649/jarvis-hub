"""Wyoming protocol endpoints (H12.4) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["wyoming"])


def _wyoming_listening(port: int) -> bool:
    """Is anything actually accepting Wyoming connections on this box right now?

    A real connect, not a flag. ``enabled`` reads the ``voice.wyoming_enabled`` SETTING,
    so an owner who turned it on saw ``enabled: true`` while nothing was listening —
    nothing in the product constructs or starts ``WyomingServer`` (the completeness
    critic's finding: a backlog item marked completed that ships a server nothing
    launches). Loopback only and 0.2s, so the status endpoint stays cheap.
    """
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


@router.get("/api/voice/wyoming")
async def wyoming_status():
    """Wyoming protocol support status (H12.4).

    Reports ``enabled`` (the setting) and ``listening`` (measured) separately, because
    they were conflated and only the first was ever true.
    """
    import asyncio

    from agents.core.voice.wyoming import PROTOCOL_VERSION
    orch = get_orch()
    enabled = bool(orch and orch.get_setting("voice.wyoming_enabled", False))
    port = int(orch.get_setting("voice.wyoming_port", 10700)) if orch else 10700
    listening = await asyncio.to_thread(_wyoming_listening, port)
    return nocache_json({
        "protocol": "wyoming",
        "version": PROTOCOL_VERSION,
        "enabled": enabled,
        "listening": listening,
        # The honest headline. Nothing in the product starts the server, so a satellite
        # cannot reach this box unless the owner runs one themselves.
        "reachable": bool(enabled and listening),
        "note": (
            "" if listening else
            "no Wyoming server is listening on this host — the protocol implementation "
            "ships but nothing in the product starts it"
        ),
        "port": port,
        "role": "handle",  # transcript → reply-to-speak
    })
