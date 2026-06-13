"""Governed browser-use endpoints (H15.1) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json


router = APIRouter(tags=["browser"])


class BrowserCheckBody(BaseModel):
    url: str = Field(..., max_length=2000)
    allowlist: list[str] = Field(default_factory=list, max_length=100)


class BrowserPreviewBody(BaseModel):
    plan: list[dict] = Field(default_factory=list, max_length=200)
    allowlist: list[str] = Field(default_factory=list, max_length=100)


@router.post("/api/browser/check", dependencies=[Depends(user_guard)])
async def browser_check(body: BrowserCheckBody):
    """H15.1 — would this URL pass the egress allowlist + SSRF filter?"""
    from agents.core.browser_agent import BrowserPolicy
    ok, reason = BrowserPolicy(body.allowlist).domain_allowed(body.url)
    return nocache_json({"allowed": ok, "reason": reason})


@router.post("/api/browser/plan/preview", dependencies=[Depends(user_guard)])
async def browser_plan_preview(body: BrowserPreviewBody):
    """H15.1 — governance dry-run: per-step run/approve/block (no execution)."""
    from agents.core.browser_agent import GovernedBrowser, BrowserPolicy
    gb = GovernedBrowser(policy=BrowserPolicy(body.allowlist))
    return nocache_json(gb.preview(body.plan))
