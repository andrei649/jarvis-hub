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
