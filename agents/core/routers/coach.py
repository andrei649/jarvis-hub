"""Learning Coach pack (0.43) — spaced repetition + curriculum endpoints.

Stateless study-coach surface (the caller holds card state; the server computes the
schedule):

  * `POST /api/coach/review`     — apply one SM-2 review to a card → next schedule
  * `POST /api/coach/session`    — select today's session (due cards + new, capped)
  * `POST /api/coach/curriculum` — order topics by prerequisites, split into sessions

Offline, deterministic, no persistence. User-guarded like the other capability packs.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["coach"])


class ReviewBody(BaseModel):
    card: dict = Field(default_factory=dict)
    quality: int = Field(..., ge=0, le=5)
    now_day: int = Field(0, ge=0)


class SessionBody(BaseModel):
    cards: list[dict] = Field(default_factory=list, max_length=5000)
    now_day: int = Field(0, ge=0)
    new_limit: int = Field(20, ge=0, le=1000)
    max_reviews: int = Field(200, ge=1, le=5000)


class CurriculumBody(BaseModel):
    topics: list[dict] = Field(default_factory=list, max_length=2000)
    per_session: int = Field(3, ge=1, le=100)


@router.post("/api/coach/review", dependencies=[Depends(user_guard)])
async def coach_review(body: ReviewBody):
    """Apply one SM-2 review to a card and return its next interval/ease/due day."""
    from agents.core import coach
    return nocache_json(coach.review(body.card, body.quality, now_day=body.now_day))


@router.post("/api/coach/session", dependencies=[Depends(user_guard)])
async def coach_session(body: SessionBody):
    """Select today's study session: due cards + up to new_limit new cards (capped)."""
    from agents.core import coach
    return nocache_json(coach.build_session(
        body.cards, now_day=body.now_day, new_limit=body.new_limit, max_reviews=body.max_reviews))


@router.post("/api/coach/curriculum", dependencies=[Depends(user_guard)])
async def coach_curriculum(body: CurriculumBody):
    """Order topics by prerequisites (deterministic) and split into sessions."""
    from agents.core import coach
    return nocache_json(coach.plan_curriculum(body.topics, per_session=body.per_session))
