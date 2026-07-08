"""System/ops read endpoints — extracted from web.py (CLN-3).

Covers public/HUD-facing system reads plus the machine-facing operability probes:
- `GET /healthz` — liveness: the process is up and serving (H23.11). Never touches
  the orchestrator, so it answers even mid-startup or with the LLM down — exactly
  what a load balancer / systemd `WatchdogSec` / Docker `HEALTHCHECK` wants.
- `GET /readyz` — readiness: the app finished booting (orchestrator + agents
  loaded). Returns **503** until ready so an orchestrator can hold traffic back
  during startup; LLM availability is reported but does NOT gate readiness (the
  hub degrades gracefully when the local model is down). (H23.11)
- `GET /api/resilience` — circuit-breaker states + resilience metrics (unguarded).
- `GET /api/cognition` — the last dynamic routing/cognition context (user-guarded).

The orchestrator is resolved at request time via `get_orch()` (late binding to
`web.orch`), matching the other extracted routers — no static import edge into
web. Behavior is unchanged from the inline versions.
"""

import time

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from agents.core.app_state import get_orch
from agents.core.observability.http_metrics import HTTP_METRICS, PROM_CONTENT_TYPE
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["ops"])

# Captured at import (≈ process start). Used only for the liveness uptime read;
# monotonic so a wall-clock adjustment can't make it go backwards.
_PROCESS_START = time.monotonic()


# ── Operability probes (machine-facing: LB / systemd / Docker HEALTHCHECK) ──

@router.get("/healthz")
async def healthz():
    """Liveness probe — 200 as long as the ASGI app is serving requests.

    Deliberately dependency-free (no orchestrator/LLM/DB touch) so it can never
    flap on a slow backend: it answers the single question a supervisor asks —
    "is this process alive enough to keep, or should it be restarted?".
    """
    return nocache_json({
        "status": "ok",
        "uptime_seconds": round(time.monotonic() - _PROCESS_START, 1),
    })


def readiness_snapshot() -> dict:
    """The /readyz verdict as pure data — shared with the first-run command center.

    Ready = the orchestrator exists and has loaded its agents. The LLM backend is
    reported for observability but intentionally does NOT gate readiness: the hub
    answers with a graceful fallback when the local model is down, so flipping to
    not-ready there would needlessly drain a healthy instance.
    """
    orch = get_orch()
    agents = getattr(orch, "agents", None) if orch else None
    n_agents = len(agents) if agents else 0
    checks = {
        "orchestrator": orch is not None,
        "agents_loaded": n_agents,
        "channels": len(getattr(orch, "channels", {}) or {}) if orch else 0,
    }
    llm = getattr(orch, "llm_router", None) if orch else None
    if llm is not None:
        checks["llm_backend"] = getattr(llm, "name", "none")
    ready = orch is not None and n_agents > 0
    body = {"ready": ready, "checks": checks}
    if not ready:
        body["reason"] = "starting" if orch is None else "agents-not-loaded"
    return body


@router.get("/readyz")
async def readyz():
    """Readiness probe — 200 once boot finished, **503** while still starting."""
    body = readiness_snapshot()
    if not body["ready"]:
        # 503 so a load balancer holds traffic back; never cache a readiness verdict.
        return nocache_json(body, status_code=503)
    return nocache_json(body)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """AUD-17: Prometheus scrape — HTTP golden signals (rate/errors/duration) +
    in-flight gauge. Unauthenticated like the probes (a monitor polls it from a
    trusted network); expose it off-loopback only behind access control. The RED
    signals are recorded by the `_golden_signals` middleware in web.py."""
    return PlainTextResponse(HTTP_METRICS.render(), media_type=PROM_CONTENT_TYPE)


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
