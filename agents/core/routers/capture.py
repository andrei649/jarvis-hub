"""Passive multi-surface capture endpoints (H12.7) — extracted from web.py (CLN-3).

Opt-in, local, redacted, inspectable/forgettable.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json, error_json
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
        return error_json(e, 422, "invalid capture input")


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


@router.get("/api/capture/export", dependencies=[Depends(user_guard)])
async def capture_export(surface: Optional[str] = None):
    """T-0.26 — the portable snapshot the phone (or anything else) takes off the box.

    Read-only, and deliberately the *same* data `/api/capture` already returns: records
    carry only already-redacted previews and metadata, because raw content is never
    stored in the first place (redaction happens at ingest). So this route widens no
    exposure — it packages what the inbox already shows into a self-describing envelope
    (`version`, `exported_at`, the surface filter, the count, the opt-in state) that
    still means something after it has been copied off the machine.

    An unknown surface is a 422, not an empty export. The two are indistinguishable in
    a saved file, and "you captured nothing from your clipboard" is a very different
    claim from "you spelled clipboard wrong" — a typo must never be able to read as an
    all-clear.
    """
    from agents.core.passive_capture import SURFACES

    if surface is not None and surface not in SURFACES:
        # The message and `known_surfaces` are built from the module constant, never
        # from the caller's string — `error_json` returns only the static public
        # message by design (CWE-209), so the useful half has to be data we own.
        return error_json(
            ValueError(f"unknown capture surface: {surface!r}"),
            422,
            "unknown capture surface — known surfaces are " + ", ".join(SURFACES),
            extra={"known_surfaces": list(SURFACES)},
        )
    return nocache_json(_get_capture().export(surface=surface))
