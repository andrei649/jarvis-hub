"""design_manifest.py router — 0.53 Design System Manifest read surface (T-0.53).

Exposes `core.design_manifest.build_manifest()` (a pure parse of
`frontend/src/styles.css` — tokens per look/accent variant + the component-class
inventory) at `GET /api/design-manifest`. Open like the sibling meters
(`/api/metrics/kernel`, `/api/metrics/capabilities`): design tokens are not
personal data and the route never mutates anything, only reads a stylesheet
already shipped in the repo.

Figma token sync (the other half of T-0.53) needs an owner-provisioned Figma
API token and stays a separate, owner-gated follow-up — this route is the
AI-buildable half: making the manifest inspectable at all.
"""

from __future__ import annotations

from fastapi import APIRouter

from agents.core.design_manifest import build_manifest
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["observe"])


@router.get("/api/design-manifest")
async def design_manifest():
    """The HUD design-system manifest: tokens (base + per-variant) + the
    component-class inventory, parsed live from `frontend/src/styles.css`."""
    return nocache_json(build_manifest())
