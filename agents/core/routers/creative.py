"""Creative / Publishing pack (P4, Track P) — governed asset-pipeline planner.

`POST /api/creative/plan` takes a brief (goal / format / platforms / inputs) and returns an
ordered pipeline plan (script → image prompts → render → assemble → export) plus per-platform
export-pack *specs* (YouTube / Instagram / README) — each carrying provenance and
`generated: false`. `POST /api/creative/export-packs` returns just the export specs.

Honest + offline: this is a *planner* — it never generates media nor publishes. The actual
render (image/video models) and the terminal publish are owner-gated; publishing a finished
campaign is an irreversible side-effect the Action Kernel QUEUEs for approval, so nothing
goes out on your behalf. Live render/publish wiring is in `docs/OWNER_TASKS.md`.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["creative"])


class BriefBody(BaseModel):
    goal: str = Field("", max_length=500)
    format: str = Field("short-video", max_length=40)
    platforms: list[str] = Field(default_factory=list, max_length=20)   # youtube | instagram | readme
    inputs: list[str] = Field(default_factory=list, max_length=200)


class ExportBody(BaseModel):
    title: str = Field("asset", max_length=200)
    targets: list[str] = Field(default_factory=list, max_length=20)


class PublishBody(BaseModel):
    """T-0.50 — one finished asset's publish-readiness request.

    Deliberately carries no credentials and no destination account: this surface
    computes *readiness*, it never uploads. The terminal publish needs
    per-platform OAuth the owner provisions, and stays approval-held.
    """

    platform: str = Field(..., max_length=40)          # youtube | instagram | readme
    meta: dict | None = None
    asset: dict | None = None
    confirmations: dict | None = None


@router.post("/api/creative/plan", dependencies=[Depends(user_guard)])
async def creative_plan(body: BriefBody):
    """Plan the creative pipeline from a brief — stages + export-pack specs, with provenance."""
    from agents.core.creative import plan_pipeline
    return nocache_json(plan_pipeline(body.model_dump()))


@router.post("/api/creative/export-packs", dependencies=[Depends(user_guard)])
async def creative_export_packs(body: ExportBody):
    """Per-platform export-pack specs (dimensions/format/caption-kind) — never rendered media."""
    from agents.core.creative import build_export_packs
    return nocache_json({"packs": build_export_packs(body.title, body.targets)})


# ── T-0.50 publish readiness (never publishes) ───────────────────────────────
# `creative/publishing.py` had no route and no HUD: the whole publish-readiness
# story was invisible to the product. These two endpoints expose it, and stop
# exactly where the governance line is — `release_payload` is what the Action
# Kernel may be *asked* to approve, never an upload. The platform executor
# (per-platform OAuth) is owner-gated; see docs/OWNER_TASKS.md.

def _publish_platform_or_error(platform: str):
    from agents.core.creative.publishing import PLATFORM_RULES

    target = str(platform or "").strip().lower()
    if target not in PLATFORM_RULES:
        return None, nocache_json(
            {"error": f"unknown platform '{platform}'", "platform": platform,
             "supported": sorted(PLATFORM_RULES)},
            status_code=400,
        )
    return target, None


@router.post("/api/creative/publish/checklist", dependencies=[Depends(user_guard)])
async def creative_publish_checklist(body: PublishBody):
    """Pre-publish checks for one asset: automatic validation + the manual
    confirmations (disclosure / rights / preview) an owner must tick.

    Read-only and pure. Manual checks default to *unconfirmed* — nothing is
    assumed on the owner's behalf."""
    from agents.core.creative.publishing import (
        prepublish_checklist,
        validate_asset,
        validate_metadata,
    )

    target, err = _publish_platform_or_error(body.platform)
    if err is not None:
        return err
    return nocache_json({
        "platform": target,
        "checklist": prepublish_checklist(
            target, body.meta, asset=body.asset, confirmations=body.confirmations
        ),
        "violations": validate_metadata(target, body.meta) + validate_asset(target, body.asset),
    })


@router.post("/api/creative/publish/package", dependencies=[Depends(user_guard)])
async def creative_publish_package(body: PublishBody):
    """Package a finished asset for review. **Never uploads.**

    `ready_for_approval` means the package may be submitted to the Action
    Kernel; it never means published, and `release_payload` stays `None` until
    the asset, its metadata and every manual confirmation pass."""
    from agents.core.creative.publishing import build_publish_package

    target, err = _publish_platform_or_error(body.platform)
    if err is not None:
        return err
    return nocache_json(build_publish_package(
        target, body.meta, asset=body.asset, confirmations=body.confirmations
    ))
