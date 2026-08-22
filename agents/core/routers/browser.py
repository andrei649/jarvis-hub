"""Governed browser-use endpoints (H15.1) — extracted from web.py (CLN-3)."""

from __future__ import annotations

import asyncio

from collections.abc import Mapping
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from agents.core.routers._deps import user_guard

from agents.core.web_helpers import nocache_json


class _BrowserValidationRoute(APIRoute):
    """Keep rejected browser inputs out of FastAPI's verbose 422 body."""

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def bounded_route_handler(request: Request):
            try:
                return await route_handler(request)
            except RequestValidationError:
                return nocache_json(
                    {"detail": "invalid_browser_request"},
                    status_code=422,
                )

        return bounded_route_handler


router = APIRouter(tags=["browser"], route_class=_BrowserValidationRoute)


class _StrictBrowserBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


BrowserUrl = Annotated[str, Field(max_length=2000, strict=True)]
BrowserDomain = Annotated[str, Field(max_length=253, strict=True)]
BrowserSelector = Annotated[str, Field(max_length=512, strict=True)]
BrowserTypeText = Annotated[str, Field(max_length=4000, strict=True)]


class BrowserNavigateStep(_StrictBrowserBody):
    action: Literal["navigate"]
    url: BrowserUrl


class BrowserExtractStep(_StrictBrowserBody):
    action: Literal["extract"]
    selector: BrowserSelector


class BrowserClickStep(_StrictBrowserBody):
    action: Literal["click"]
    selector: BrowserSelector


class BrowserTypeStep(_StrictBrowserBody):
    action: Literal["type"]
    selector: BrowserSelector
    text: BrowserTypeText


class BrowserSubmitStep(_StrictBrowserBody):
    action: Literal["submit"]
    selector: BrowserSelector


BrowserPlanStep = Annotated[
    BrowserNavigateStep
    | BrowserExtractStep
    | BrowserClickStep
    | BrowserTypeStep
    | BrowserSubmitStep,
    Field(discriminator="action"),
]


class BrowserCheckBody(_StrictBrowserBody):
    url: BrowserUrl
    allowlist: list[BrowserDomain] = Field(default_factory=list, max_length=100)


class BrowserPreviewBody(_StrictBrowserBody):
    plan: list[BrowserPlanStep] = Field(default_factory=list, max_length=200)
    allowlist: list[BrowserDomain] = Field(default_factory=list, max_length=100)


def _bounded_reason(value) -> str:
    return str(value or "")[:240]


def _project_preview(raw) -> dict[str, list[dict]]:
    raw_steps = raw.get("steps", []) if isinstance(raw, Mapping) else []
    if not isinstance(raw_steps, list):
        raw_steps = []
    projected = []
    for fallback_index, raw_step in enumerate(raw_steps[:200]):
        if not isinstance(raw_step, Mapping):
            continue
        projected.append(
            {
                "index": fallback_index,
                "action": str(raw_step.get("action") or "")[:64],
                "kind": str(raw_step.get("kind") or "")[:32],
                "decision": str(raw_step.get("decision") or "")[:32],
                "reason": _bounded_reason(raw_step.get("reason")),
            }
        )
    return {"steps": projected}


@router.post("/api/browser/check", dependencies=[Depends(user_guard)])
async def browser_check(body: BrowserCheckBody):
    """H15.1 — would this URL pass the egress allowlist + SSRF filter?"""
    from agents.core.browser_agent import BrowserPolicy
    # domain_allowed() resolves DNS synchronously (socket.getaddrinfo via
    # check_ssrf); keep that off the event loop like the admin audit route.
    ok, reason = await asyncio.to_thread(
        BrowserPolicy(body.allowlist).domain_allowed, body.url,
    )
    return nocache_json({"allowed": ok, "reason": _bounded_reason(reason)})


@router.post("/api/browser/plan/preview", dependencies=[Depends(user_guard)])
async def browser_plan_preview(body: BrowserPreviewBody):
    """H15.1 — governance dry-run: per-step run/approve/block (no execution)."""
    from agents.core.browser_agent import GovernedBrowser, BrowserPolicy
    gb = GovernedBrowser(policy=BrowserPolicy(body.allowlist))
    plan = [step.model_dump(mode="python") for step in body.plan]
    # navigate steps resolve DNS inside preview(); same sync-seam rule as above.
    raw = await asyncio.to_thread(gb.preview, plan)
    return nocache_json(_project_preview(raw))
