"""Support / diagnostics (0.55 Design Partner Kit) — the issue bundle.

`GET /api/support/bundle` (admin) assembles a single non-sensitive diagnostic
snapshot (version + posture + readiness roll-ups + recent activity counts) a
design partner can attach to a support request, so an issue can be triaged
without a screen-share or a risky data dump. Safety is allow-list, not redaction
(see `support_bundle`): only the specific aggregates are ever included.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["support"])


@router.get("/api/support/bundle", dependencies=[Depends(admin_guard)])
async def support_bundle(request: Request):
    """A non-sensitive diagnostic bundle for support triage (admin-only)."""
    from agents.core import support_bundle as sb
    orch = get_orch()
    # Read the route count off the live app (request.app) rather than importing
    # agents.web here — that keeps support_bundle out of an import cycle (CodeQL).
    route_count = len(getattr(request.app, "routes", []))
    return nocache_json(sb.build_bundle(orch, now_iso=datetime.now(UTC).isoformat(),
                                        route_count=route_count))
