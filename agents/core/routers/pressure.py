"""H161 — memory and disk pressure: ``GET /api/system/pressure`` and its dismissal.

Both are user-guarded. The GET answers the ranked conditions (disk critical, memory
critical, a suspected OOM restart, disk elevated, memory elevated) and the worst one
not dismissed, sampling first when the last sample is over a minute old; the POST
dismisses one condition for this boot. Neither depends on autonomy being on.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.core import resource_pressure
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["system"])

MAX_AGE = 60.0


class DismissBody(BaseModel):
    condition: str
    boot_id: str


@router.get("/api/system/pressure", dependencies=[Depends(user_guard)])
async def pressure_state():
    """The ranked memory/disk conditions and the worst one not dismissed."""
    return nocache_json(await asyncio.to_thread(resource_pressure.monitor().fresh, MAX_AGE))


@router.post("/api/system/pressure/dismiss", dependencies=[Depends(user_guard)])
async def pressure_dismiss(body: DismissBody):
    """Dismiss one raised condition for this boot (a new boot, or its recovery, re-arms it)."""
    monitor = resource_pressure.monitor()
    if not await asyncio.to_thread(monitor.dismiss, body.condition, body.boot_id):
        return JSONResponse({"ok": False, "error": "not_dismissable",
                             "detail": "no such raised condition on this boot"}, status_code=409)
    return nocache_json({"ok": True, **monitor.snapshot()})
