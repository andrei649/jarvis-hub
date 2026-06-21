"""System/ops read endpoints — extracted from web.py (CLN-3).

Covers two public/HUD-facing system reads:
- `GET /api/resilience` — circuit-breaker states + resilience metrics (unguarded).
- `GET /api/cognition` — the last dynamic routing/cognition context (user-guarded).

The orchestrator is resolved at request time via `get_orch()` (late binding to
`web.orch`), matching the other extracted routers — no static import edge into
web. Behavior is unchanged from the inline versions.
"""

from fastapi import APIRouter, Depends

from agents.core.app_state import get_orch
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["ops"])


@router.get("/api/resilience")
async def resilience_public():
    """Public resilience metrics and circuit breaker states (no admin auth)."""
    from core.resilience import _circuit_breakers, get_metrics
    metrics = get_metrics().get_stats()
    breakers = {
        key: {
            "state": cb.state,
            "failure_count": cb.failure_count,
            "last_failure_time": cb.last_failure_time,
        }
        for key, cb in _circuit_breakers.items()
    }
    return nocache_json({"metrics": metrics, "circuit_breakers": breakers})


@router.get("/api/cognition", dependencies=[Depends(user_guard)])
async def get_cognition():
    """Return the last dynamic routing/cognition context."""
    orch = get_orch()
    cog = getattr(orch, "last_cognition", None) if orch else None
    if not cog:
        from core.router import INTENT_RULES
        scoring = []
        for kw, rule in list(INTENT_RULES.items())[:5]:
            scoring.append({
                "keyword": kw,
                "weight": rule[2],
                "agents": rule[0],
                "category": kw
            })
        cog = {
            "scoring": scoring,
            "decision": {
                "source": "standby",
                "confidence": 1.0,
                "agents_selected": ["jarvis"],
                "alternatives": [],
                "timing": {"classify": 0, "route": 0, "total": 0}
            },
            "trace": []
        }
    return nocache_json(cog)
