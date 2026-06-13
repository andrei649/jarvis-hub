"""Passive multi-surface capture endpoints (H12.7) — extracted from web.py (CLN-3).

Opt-in, local, redacted, inspectable/forgettable.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["capture"])

_passive_capture = None


def _get_capture():
    global _passive_capture
    if _passive_capture is None:
        from agents.core.passive_capture import PassiveCapture
        orch = get_orch()
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
    return nocache_json(_get_capture().status())


@router.post("/api/capture/ingest", dependencies=[Depends(user_guard)])
async def capture_ingest(body: CaptureIngestBody):
    """Opt-in: capture a surface event (redacted, local, inspectable)."""
    try:
        return nocache_json(_get_capture().ingest(body.surface, body.content, body.source))
    except ValueError as e:
        return nocache_json({"error": str(e)}, status_code=422)


@router.get("/api/capture", dependencies=[Depends(user_guard)])
async def capture_list(surface: Optional[str] = None):
    return nocache_json({"records": _get_capture().list(surface)})


@router.post("/api/capture/surfaces", dependencies=[Depends(user_guard)])
async def capture_set_surfaces(body: CaptureSurfacesBody):
    return nocache_json({"surfaces": _get_capture().set_surfaces(body.surfaces)})


@router.delete("/api/capture/{rec_id}", dependencies=[Depends(user_guard)])
async def capture_forget(rec_id: str):
    ok = _get_capture().forget(rec_id)
    return nocache_json({"forgotten": ok}, status_code=200 if ok else 404)


@router.post("/api/capture/clear", dependencies=[Depends(user_guard)])
async def capture_clear(surface: Optional[str] = None):
    return nocache_json({"removed": _get_capture().clear(surface)})
