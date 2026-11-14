"""H214 + H238 + H590 — Petdex, Hatch-a-Pet, and reactive companion HTTP routes."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from agents.core.pets import PetError
from agents.core.routers._component import require_component
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["pets"])


def _pet_err(exc: PetError):
    return nocache_json(
        {"ok": False, "error": exc.reason, "detail": exc.detail},
        status_code=exc.status,
    )


class PetSelectBody(BaseModel):
    pet_id: str = Field(..., min_length=1, max_length=64)


class PetRenameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)


class PetPreferencesBody(BaseModel):
    enabled: bool | None = None
    roam: bool | None = None
    overlay_enabled: bool | None = None
    scale: float | None = None
    image_backend: str | None = None


class PetImportBody(BaseModel):
    zip_base64: str = Field(..., min_length=4, max_length=800_000)


class HatchGenerateBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=300)
    image_backend: str = Field("", max_length=40)
    reference_image_b64: str = Field("", max_length=1_500_000)
    defer_completion: bool = False


class HatchRemixBody(BaseModel):
    draft_id: str = Field(..., min_length=1, max_length=64)
    instruction: str = Field("", max_length=200)
    confirm: bool = False


class HatchAdoptBody(BaseModel):
    draft_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field("", max_length=48)
    adopt_active: bool = True


@router.get("/api/pets", dependencies=[Depends(user_guard)])
async def pets_info(state: str = Query("", max_length=24)):
    """H238 + H590 — active companion, live agent-state animation frame, and settings."""
    orch, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.info(orch=orch, state_override=state))
    except PetError as exc:
        return _pet_err(exc)


@router.get("/api/pets/gallery", dependencies=[Depends(user_guard)])
async def pets_gallery():
    """H214 + H238 — Petdex gallery of built-in and hatched/imported companions."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    return nocache_json(store.gallery())


@router.get("/api/pets/doctor", dependencies=[Depends(user_guard)])
async def pets_doctor():
    """H590 — companion store, sprite frames, settings, and terminal renderer diagnostics."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    return nocache_json(store.doctor())


@router.get("/api/pets/{pet_id}/meta", dependencies=[Depends(user_guard)])
async def pets_meta(pet_id: str):
    """H238 — metadata for one installed companion."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.meta(pet_id))
    except PetError as exc:
        return _pet_err(exc)


@router.get("/api/pets/{pet_id}/cells", dependencies=[Depends(user_guard)])
async def pets_cells(
    pet_id: str,
    state: str = Query("idle", max_length=24),
    frame: int = Query(0, ge=0, le=16),
):
    """H238 — 8x8 RGB cell matrix for a companion and agent state."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.cells(pet_id, state=state, frame=frame))
    except PetError as exc:
        return _pet_err(exc)


@router.get("/api/pets/{pet_id}/thumb", dependencies=[Depends(user_guard)])
async def pets_thumb(pet_id: str, state: str = Query("idle", max_length=24)):
    """H238 — SVG thumbnail and data URI for one companion."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.thumb(pet_id, state=state))
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/select", dependencies=[Depends(admin_guard)])
async def pets_select(body: PetSelectBody):
    """H238 — select the active Petdex companion."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.select(body.pet_id))
    except PetError as exc:
        return _pet_err(exc)


@router.put("/api/pets/preferences", dependencies=[Depends(admin_guard)])
async def pets_preferences(body: PetPreferencesBody):
    """H214 + H238 + H590 — update companion enabled, roam, overlay, scale, or backend."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(
            store.update_preferences(
                enabled=body.enabled,
                roam=body.roam,
                overlay_enabled=body.overlay_enabled,
                scale=body.scale,
                image_backend=body.image_backend,
            )
        )
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/{pet_id}/rename", dependencies=[Depends(admin_guard)])
async def pets_rename(pet_id: str, body: PetRenameBody):
    """H238 — rename an installed companion."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.rename(pet_id, body.name))
    except PetError as exc:
        return _pet_err(exc)


@router.delete("/api/pets/{pet_id}", dependencies=[Depends(admin_guard)])
async def pets_delete(pet_id: str, confirm: bool = Query(False)):
    """H214 + H238 — delete a custom hatched/imported companion (requires confirm=true)."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.remove(pet_id, confirm=confirm))
    except PetError as exc:
        return _pet_err(exc)


@router.get("/api/pets/{pet_id}/export", dependencies=[Depends(user_guard)])
async def pets_export(pet_id: str):
    """H238 — export a companion as a re-importable `.pet.zip` archive."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        filename, raw = store.export_zip(pet_id)
        return nocache_json(
            {
                "ok": True,
                "pet_id": pet_id,
                "filename": filename,
                "size_bytes": len(raw),
                "zip_base64": base64.b64encode(raw).decode("ascii"),
            }
        )
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/import", dependencies=[Depends(admin_guard)])
async def pets_import(body: PetImportBody):
    """H238 — import a `.pet.zip` companion archive."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        raw = base64.b64decode(body.zip_base64.strip(), validate=False)
    except Exception:
        return nocache_json({"ok": False, "error": "invalid_base64"}, status_code=400)
    try:
        return nocache_json(store.import_zip(raw))
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/hatch/generate", dependencies=[Depends(admin_guard)])
async def pets_hatch_generate(body: HatchGenerateBody):
    """H214 + H238 — generate 4 Hatch-a-Pet candidate looks."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(
            store.generate_drafts(
                body.prompt,
                image_backend=body.image_backend,
                reference_image_b64=body.reference_image_b64,
                defer_completion=body.defer_completion,
            )
        )
    except PetError as exc:
        return _pet_err(exc)


@router.get("/api/pets/hatch/jobs/{job_id}", dependencies=[Depends(user_guard)])
async def pets_hatch_status(job_id: str):
    """H238 — poll candidate generation status and draft grid."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.generation_status(job_id))
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/hatch/jobs/{job_id}/cancel", dependencies=[Depends(admin_guard)])
async def pets_hatch_cancel(job_id: str):
    """H238 — cancel an in-flight or unhatched candidate generation job."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(store.cancel_generation(job_id))
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/hatch/jobs/{job_id}/remix", dependencies=[Depends(admin_guard)])
async def pets_hatch_remix(job_id: str, body: HatchRemixBody):
    """H214 — remix a candidate draft with explicit owner confirmation."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(
            store.remix_draft(
                job_id,
                body.draft_id,
                instruction=body.instruction,
                confirm=body.confirm,
            )
        )
    except PetError as exc:
        return _pet_err(exc)


@router.post("/api/pets/hatch/jobs/{job_id}/adopt", dependencies=[Depends(admin_guard)])
async def pets_hatch_adopt(job_id: str, body: HatchAdoptBody):
    """H214 + H238 — hatch a chosen candidate draft into an installed Petdex companion."""
    _, store, err = require_component("pets", "pets store unavailable")
    if err is not None:
        return err
    try:
        return nocache_json(
            store.hatch_draft(
                job_id,
                body.draft_id,
                name=body.name,
                adopt_active=body.adopt_active,
            )
        )
    except PetError as exc:
        return _pet_err(exc)
