"""Security HUD reads (bare /security + /security/status) — extracted from web.py (CLN-3).

The two unguarded HUD reads that sit on the bare `/security` prefix (distinct from
the `/api/security/*` trust surface owned by `routers/security.py`). Behavior-frozen
move: paths/methods/bodies are byte-identical to the web.py originals.

`get_security` reads the live orchestrator, resolved at REQUEST time via
`get_orch()` (web owns the `orch` global; the suite rebinds it). `security_status`
is fully static.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["security"])


@router.get("/security")
async def get_security():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    guardrails = orch.security is not None
    return {
        "enabled": guardrails,
        "scanners": ["secrets", "pii"] if guardrails else [],
        "ssrf_protection": True,
        "audit_count": orch.checkpoints.count() if hasattr(orch.checkpoints, "count") else 0,
    }


@router.get("/security/status")
async def security_status():
    """Return security system status."""
    return nocache_json({
        "guardrails": {
            "mode": "WARN",
            "redact_count": 0,
            "block_count": 0,
        },
        "scanners": {
            "secret": {"patterns": 10, "findings": 0},
            "pii": {"patterns": 6, "findings": 0},
        },
        "ssrf": {
            "enabled": True,
            "blocked_requests": 0,
            "max_redirects": 5,
        },
    })
