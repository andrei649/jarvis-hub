"""H31.5 camera intelligence API — bounded metadata only, never frames or clips."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.cameras.onvif import OnvifDiscoveryError
from agents.core.cameras.retrieval import CameraFilter, CameraSearchError
from agents.core.cameras.runtime import CameraRuntime, build_camera_runtime
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["cameras"])
_runtime: CameraRuntime | None = None


class CameraSearchBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=1, max_length=256)
    limit: int = Field(100, ge=1, le=100)


def _get_runtime() -> CameraRuntime:
    global _runtime
    orch = get_orch()
    orch_id = id(orch) if orch is not None else 0
    if _runtime is None or _runtime.orch_id != orch_id:
        _runtime = build_camera_runtime(orch)
    return _runtime


def _disabled_payload(runtime: CameraRuntime) -> dict:
    return {
        "enabled": False,
        "status": runtime.status,
        "reason": runtime.reason,
        "interpretation": {},
        "events": [],
    }


@router.get("/api/cameras/status", dependencies=[Depends(user_guard)])
async def camera_status():
    runtime = _get_runtime()
    if not runtime.enabled or runtime.health is None:
        return nocache_json(
            {
                "enabled": False,
                "status": runtime.status,
                "reason": runtime.reason,
                "source": None,
                "storage": None,
            }
        )
    health = runtime.health.snapshot()
    return nocache_json(
        {
            "enabled": True,
            "status": health["status"],
            "reason": runtime.reason,
            "source": health["source"],
            "storage": health["storage"],
        }
    )


@router.get("/api/cameras/events", dependencies=[Depends(user_guard)])
async def camera_events(
    after: Annotated[float | None, Query(ge=0)] = None,
    before: Annotated[float | None, Query(ge=0)] = None,
    label: Annotated[str | None, Query(max_length=32)] = None,
    camera_id: Annotated[str | None, Query(max_length=64)] = None,
    zone: Annotated[str | None, Query(max_length=64)] = None,
    room_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    runtime = _get_runtime()
    if not runtime.enabled or runtime.retrieval is None:
        return nocache_json(_disabled_payload(runtime))
    try:
        result = runtime.retrieval.query(
            CameraFilter(
                after=after,
                before=before,
                label=label,
                camera_id=camera_id,
                zone=zone,
                room_id=room_id,
                limit=limit,
            )
        )
    except ValueError:
        return nocache_json(
            {
                "enabled": True,
                "status": "invalid",
                "reason": "camera_filter_invalid",
                "interpretation": {},
                "events": [],
            },
            status_code=422,
        )
    return nocache_json({"enabled": True, **result.to_public()})


@router.post("/api/cameras/search", dependencies=[Depends(user_guard)])
async def camera_search(body: CameraSearchBody):
    runtime = _get_runtime()
    if not runtime.enabled or runtime.retrieval is None:
        return nocache_json(_disabled_payload(runtime))
    try:
        result = runtime.retrieval.search(body.query, limit=body.limit)
    except CameraSearchError:
        return nocache_json(
            {
                "enabled": True,
                "status": "invalid",
                "reason": "camera_query_invalid",
                "interpretation": {},
                "events": [],
            },
            status_code=422,
        )
    return nocache_json({"enabled": True, **result.to_public()})


@router.post("/api/cameras/onvif/discover", dependencies=[Depends(admin_guard)])
async def camera_onvif_discover():
    runtime = _get_runtime()
    if not runtime.enabled:
        return nocache_json(
            {
                "enabled": False,
                "status": runtime.status,
                "reason": runtime.reason,
                "devices": [],
            }
        )
    if runtime.discovery is None:
        return nocache_json(
            {
                "enabled": True,
                "status": "unavailable",
                "reason": "discovery_unavailable",
                "devices": [],
            }
        )
    try:
        result = await runtime.discovery.discover()
    except OnvifDiscoveryError as exc:
        reason = str(exc) if str(exc) in {"discovery_disabled", "admin_required"} else "discovery_failed"
        return nocache_json(
            {
                "enabled": True,
                "status": "disabled" if reason == "discovery_disabled" else "denied",
                "reason": reason,
                "devices": [],
            }
        )
    return nocache_json({"enabled": True, **result.to_public()})


__all__ = ["CameraRuntime", "CameraSearchBody", "router"]
