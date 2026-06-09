"""Passive multi-surface capture endpoints (H12.7) — extracted from web.py (CLN-3).

Opt-in, local, redacted, inspectable/forgettable.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

router = APIRouter(tags=["capture"])

_passive_capture = None


def _get_capture():
    from agents import web
    global _passive_capture
    if _passive_capture is None:
        from agents.core.passive_capture import PassiveCapture
        orch = web.orch
        kg = getattr(orch, "kg_updater", None) if orch else None
        _passive_capture = PassiveCapture(kg_updater=kg)
    return _passive_capture


class CaptureIngestBody(BaseModel):
    surface: str = Field(..., max_length=32)
    content: str = Field(..., max_length=100_000)
    source: str = Field("", max_length=200)


class CaptureSurfacesBody(BaseModel):
    surfaces: dict = Field(default_factory=dict)


@router.get("/api/capture/status", dependencies=[Depends(user_guard)])
async def capture_status():
    from agents import web
    return web._nocache_json(_get_capture().status())


@router.post("/api/capture/ingest", dependencies=[Depends(user_guard)])
async def capture_ingest(body: CaptureIngestBody):
    """Opt-in: capture a surface event (redacted, local, inspectable)."""
    from agents import web
    try:
        return web._nocache_json(_get_capture().ingest(body.surface, body.content, body.source))
    except ValueError as e:
        return web._nocache_json({"error": str(e)}, status_code=422)


@router.get("/api/capture", dependencies=[Depends(user_guard)])
async def capture_list(surface: Optional[str] = None):
    from agents import web
    return web._nocache_json({"records": _get_capture().list(surface)})


@router.post("/api/capture/surfaces", dependencies=[Depends(user_guard)])
async def capture_set_surfaces(body: CaptureSurfacesBody):
    from agents import web
    return web._nocache_json({"surfaces": _get_capture().set_surfaces(body.surfaces)})


@router.delete("/api/capture/{rec_id}", dependencies=[Depends(user_guard)])
async def capture_forget(rec_id: str):
    from agents import web
    ok = _get_capture().forget(rec_id)
    return web._nocache_json({"forgotten": ok}, status_code=200 if ok else 404)


@router.post("/api/capture/clear", dependencies=[Depends(user_guard)])
async def capture_clear(surface: Optional[str] = None):
    from agents import web
    return web._nocache_json({"removed": _get_capture().clear(surface)})
