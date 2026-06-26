"""Design-partner feedback + NPS (H23.21) — first-party, local.

`POST /api/feedback` records an in-app NPS / comment / bug item (the HUD footer widget);
`GET /api/feedback/summary` is the owner's review (NPS + recent), admin-guarded.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["feedback"])


class FeedbackBody(BaseModel):
    kind: str = Field("comment", max_length=16)          # nps | comment | bug
    score: int | None = Field(None, ge=0, le=10)         # NPS 0–10
    message: str | None = Field(None, max_length=4000)
    session_id: str | None = Field(None, max_length=128)


@router.post("/api/feedback", dependencies=[Depends(user_guard)])
async def submit_feedback(body: FeedbackBody):
    """Record one in-app feedback item — first-party + local (never leaves the machine)."""
    from agents.core import feedback_store
    fid = feedback_store.record(
        body.kind, score=body.score, message=body.message, session_id=body.session_id
    )
    return nocache_json({"ok": True, "id": fid})


@router.get("/api/feedback/summary", dependencies=[Depends(admin_guard)])
async def feedback_summary():
    """Owner review: NPS + per-kind counts + the most recent items."""
    from agents.core import feedback_store
    return nocache_json(feedback_store.summary())
