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
from agents.core.routers._deps import admin_guard, user_guard
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


# A backend availability flag older than this is reported as stale. `detect()` runs
# at boot and on an admin reconnect — never on a timer — so on a long-lived process
# the flag describes the box as it was at startup, not as it is now.
_LLM_PROBE_STALE_AFTER = 300.0  # seconds


def _llm_snapshot(orch) -> dict:
    """What we actually know about the LLM backend, and when we last knew it.

    Deliberately NOT part of `checks`: nothing here is measured at request time.
    `/readyz` is scraped by load balancers and systemd, so probing a model server
    on every scrape would put an unbounded network call on the readiness path —
    the exact defect this endpoint is supposed to detect elsewhere. Instead we
    report the last real measurement together with its age, so a stale reading is
    labelled stale rather than read as a live pass.
    """
    llm = getattr(orch, "llm_router", None) if orch else None
    if llm is None:
        return {"configured_backend": None, "measured": None,
                "note": "no LLM router on the orchestrator"}
    age = None
    probe_age = getattr(llm, "probe_age_seconds", None)
    if callable(probe_age):
        try:
            age = probe_age()
        except Exception:  # a router stub without the timing fields
            age = None
    snapshot = {
        # What the owner CONFIGURED / what detect() selected. A name, not a verdict.
        "configured_backend": getattr(llm, "name", "none"),
        # What was actually MEASURED, and when. None = never probed.
        "measured": None,
    }
    if age is None:
        snapshot["note"] = "backend availability has never been probed"
        return snapshot
    reachable = bool(getattr(llm, "_local_available", False))
    stale = age > _LLM_PROBE_STALE_AFTER
    snapshot["measured"] = {
        "local_backend_reachable": reachable,
        "age_seconds": round(age, 1),
        "stale": stale,
    }
    if stale:
        snapshot["note"] = (
            f"last probed {round(age)}s ago — availability is not re-measured on a "
            "timer, so treat this as a startup reading, not current health"
        )
    return snapshot


def readiness_snapshot() -> dict:
    """The /readyz verdict as pure data — shared with the first-run command center.

    Ready = the orchestrator exists and has loaded its agents. LLM availability is
    reported but intentionally does NOT gate readiness: the hub answers with a
    graceful fallback when the local model is down, so flipping to not-ready there
    would needlessly drain a healthy instance.

    Every entry under `checks` is measured at request time. Anything we merely
    *configured* — or measured once at boot — lives under `llm`, with its age, so a
    monitor cannot mistake a setting for a passing check. It previously could:
    `checks["llm_backend"]` held the configured backend NAME, which is truthy
    whether or not that backend is up, so `/readyz` published a clean bill of
    health for an unreachable model.
    """
    orch = get_orch()
    agents = getattr(orch, "agents", None) if orch else None
    n_agents = len(agents) if agents else 0
    checks = {
        "orchestrator": orch is not None,
        "agents_loaded": n_agents,
        "channels": len(getattr(orch, "channels", {}) or {}) if orch else 0,
    }
    ready = orch is not None and n_agents > 0
    body = {"ready": ready, "checks": checks, "llm": _llm_snapshot(orch)}
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
    """Return the last dynamic routing/cognition context, or an honest empty.

    Before any request has been routed there is nothing to show. This used to
    manufacture one: the first five entries of ``INTENT_RULES`` were returned as
    ``scoring`` — so the panel drew weight bars for keywords the owner had never
    typed — alongside a ``decision`` with ``confidence: 1.0`` and
    ``agents_selected: ["jarvis"]`` for a routing decision that never happened.
    Nothing marked any of it synthetic, so the HUD rendered "ROUTING DECISION /
    STANDBY / Confidence 100%" as though the router had actually decided that.

    Now the empty case is returned as empty, with ``live: false`` and a ``state``
    the UI can render as "nothing routed yet".
    """
    orch = get_orch()
    cog = getattr(orch, "last_cognition", None) if orch else None
    if not cog:
        return nocache_json({
            "scoring": [],
            "decision": None,
            "trace": [],
            "live": False,
            "state": "no-request-routed-yet" if orch is not None else "starting",
        })
    return nocache_json({**cog, "live": True, "state": "last-request"})


# ── Global emergency stop (ESTOP) — pause NEW autonomous work, resumable ──

@router.get("/api/ops/estop", dependencies=[Depends(user_guard)])
async def estop_state():
    """Current emergency-stop state (engaged flag + reason/engaged_at)."""
    from agents.core import estop
    state = estop.get_state()
    return nocache_json({"engaged": state is not None, "state": state})


@router.post("/api/ops/estop/engage", dependencies=[Depends(admin_guard)])
async def estop_engage(body: dict | None = None):
    """Engage the emergency stop: heartbeats and autonomy ticks pause on the
    very next check. Owner chat keeps working; in-flight work is not killed."""
    from agents.core import estop
    reason = None
    if isinstance(body, dict):
        raw = body.get("reason")
        if isinstance(raw, str) and raw.strip():
            reason = raw.strip()[:500]
    estop.engage(reason)
    return nocache_json({"engaged": True, "state": estop.get_state()})


@router.post("/api/ops/estop/resume", dependencies=[Depends(admin_guard)])
async def estop_resume():
    """Lift the emergency stop; autonomous dispatch resumes on the next tick."""
    from agents.core import estop
    lifted = estop.disengage()
    return nocache_json({"engaged": estop.is_engaged(), "lifted": lifted})
