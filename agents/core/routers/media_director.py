"""Media Director endpoints (ORIZONT 29 wave 1) — the `present()` surface.

Default-off behind ``JARVIS_MEDIA_DIRECTOR``: every endpoint answers
``enabled: false`` honestly until the owner opts in. Presents and restores are
mediated by the O27 unified action facade; when the facade is off, the routes
refuse rather than bypassing mediation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import error_json, nocache_json

router = APIRouter(tags=["media"])

_director = None


def _get_director():
    global _director
    if _director is None:
        from agents.core.media_director import MediaDirector

        _director = MediaDirector()
    return _director


def _disabled_body() -> dict:
    return {
        "enabled": False,
        "hint": "set JARVIS_MEDIA_DIRECTOR=1 to enable the Media Director (O29)",
    }


def _enabled() -> bool:
    from agents.core.media_director import media_director_enabled

    return media_director_enabled()


class DeviceBody(BaseModel):
    id: str = Field(..., max_length=64)
    name: str = Field(..., max_length=120)
    kind: str = Field(..., max_length=32)
    room: str = Field("", max_length=64)
    supports: list[str] = Field(default_factory=lambda: ["play"], max_length=16)


class PresentBody(BaseModel):
    content: dict = Field(...)
    target: str = Field(..., max_length=120)
    mode: str = Field("play", max_length=16)
    privacy: str = Field("household", max_length=16)
    urgency: str = Field("normal", max_length=16)
    duration_seconds: float | None = Field(None, gt=0)


async def _perform_media(capability_id: str, params: dict, *, title: str):
    """Build the request-scoped facade and bind both governed media actions."""
    from agents.core.app_state import get_orch
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.media_director import register_media_capability

    orch = get_orch()
    api = CapabilityActionAPI(authorizer=make_action_kernel(orch) if orch else None)
    register_media_capability(api, _get_director())
    return await api.perform(
        capability_id,
        params,
        PerformContext(agent="jarvis", title=title, origin="user"),
    )


def _perform_payload(result) -> dict:
    payload = {
        "enabled": True,
        "status": result.status,
        "reason": result.reason,
        "output": result.output,
    }
    if result.card is not None:
        payload["card"] = result.card
    return payload


@router.get("/api/media/devices", dependencies=[Depends(user_guard)])
async def media_devices():
    if not _enabled():
        return nocache_json(_disabled_body())
    return nocache_json({"enabled": True, "devices": _get_director().registry.list()})


@router.post("/api/media/devices", dependencies=[Depends(admin_guard)])
async def media_register_device(body: DeviceBody):
    """Owner-curated device registration (discovery stays a host seam)."""
    if not _enabled():
        return nocache_json(_disabled_body())
    from agents.core.media_director import MediaDevice, MediaError

    try:
        device = _get_director().registry.register(
            MediaDevice(
                id=body.id,
                name=body.name,
                kind=body.kind,
                room=body.room,
                supports=tuple(body.supports),
            )
        )
    except MediaError as exc:
        return error_json(exc, 422, "invalid media device")
    from dataclasses import asdict

    return nocache_json({"enabled": True, "device": asdict(device)})


@router.delete("/api/media/devices/{device_id}", dependencies=[Depends(admin_guard)])
async def media_remove_device(device_id: str):
    if not _enabled():
        return nocache_json(_disabled_body())
    removed = _get_director().registry.remove(device_id)
    if not removed:
        return nocache_json({"enabled": True, "error": "unknown device"}, status_code=404)
    return nocache_json({"enabled": True, "removed": device_id})


@router.get("/api/media/session", dependencies=[Depends(user_guard)])
async def media_sessions():
    if not _enabled():
        return nocache_json(_disabled_body())
    return nocache_json({"enabled": True, "sessions": _get_director().sessions.list()})


@router.post("/api/media/present", dependencies=[Depends(user_guard)])
async def media_present(body: PresentBody):
    """Present content on a device — kernel-mediated through the O27 facade.

    The facade path is the only execution path: with the unified action API off
    this refuses honestly instead of driving devices unmediated.
    """
    if not _enabled():
        return nocache_json(_disabled_body())
    # perform() gates on the unified-API + kernel flags before touching the
    # authorizer, so a missing orchestrator still yields an honest refusal
    # ("kernel_unavailable") instead of a 503 on the disabled path.
    result = await _perform_media(
        "action:media.present",
        body.model_dump(),
        title=f"present on {body.target}",
    )
    return nocache_json(_perform_payload(result))


@router.post("/api/media/restore/{device_id}", dependencies=[Depends(user_guard)])
async def media_restore(device_id: str):
    """Replay the pre-present snapshot through its own governed action."""
    if not _enabled():
        return nocache_json(_disabled_body())
    result = await _perform_media(
        "action:media.restore",
        {"device_id": device_id},
        title=f"restore {device_id}",
    )
    return nocache_json(_perform_payload(result))
