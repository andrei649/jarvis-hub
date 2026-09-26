"""H182 — the machine's power state: ``GET /api/power`` and ``GET /api/power/stream``.

Both are user-guarded and read-only. ``/api/power`` answers once: on battery, percent,
plugged in, the last resume from sleep, whether heavy background jobs are being deferred
(``system.battery_defer_percent``) and the keep-awake state (``JARVIS_KEEP_AWAKE``: on,
held, refused and why). ``/api/power/stream`` pushes the same payload to a connected
client every time it changes, with a keepalive comment while it does not.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agents.core import power
from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["power"])

STREAM_INTERVAL = 5.0
HEARTBEAT_EVERY = 6            # idle ticks between keepalive comments (30 s)


def _get_setting():
    orch = get_orch()
    return getattr(orch, "get_setting", None) if orch is not None else None


@router.get("/api/power", dependencies=[Depends(user_guard)])
async def power_state():
    """Battery, resume, background deferral and keep-awake, as of now."""
    return nocache_json(await asyncio.to_thread(power.public_state, _get_setting()))


async def power_events(read: Callable[[], Any], *, sleep=asyncio.sleep, interval: float = STREAM_INTERVAL,
                       heartbeat_every: int = HEARTBEAT_EVERY, max_iterations: int | None = None):
    """SSE frames: one ``data:`` frame per change of ``read()``, a keepalive while idle."""
    last = None
    idle = 0
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        try:
            state = await asyncio.to_thread(read)
        except Exception:
            state = None
        sig = json.dumps(state, sort_keys=True, default=str) if state else ""
        if state and sig != last:
            last = sig
            idle = 0
            yield f"data: {json.dumps({'type': 'power', **state}, default=str)}\n\n"
        else:
            idle += 1
            if heartbeat_every and idle % heartbeat_every == 0:
                yield ": keepalive\n\n"
        await sleep(interval)


@router.get("/api/power/stream", dependencies=[Depends(user_guard)])
async def power_stream():
    """Every change of the power state, as server-sent events."""
    get_setting = _get_setting()
    return StreamingResponse(
        power_events(lambda: power.public_state(get_setting)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
