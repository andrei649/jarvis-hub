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

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from agents.core.app_state import get_orch
from agents.core.observability.http_metrics import HTTP_METRICS, PROM_CONTENT_TYPE
from agents.core.routers._deps import admin_guard, user_guard

# `agents.core.*` flavour on purpose — `core.security.ssrf` is a distinct module
# object and every production refusal lands in this one.
from agents.core.security.ssrf import blocked_requests
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
    from agents.core import safe_mode

    return nocache_json({
        "status": "ok",
        "uptime_seconds": round(time.monotonic() - _PROCESS_START, 1),
        # H275: a flag read from the environment, still dependency-free.
        "safe_mode": safe_mode.enabled(),
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
    from agents.core import safe_mode

    # H275: said, never a reason to be not-ready — a safe-mode hub serves.
    from agents.core.lifecycle_budget import WARMUP

    # H677: the boot warm-up is reported, never a reason to be not-ready (the gate
    # already held the channels; a turn served while it still runs is marked warming).
    body = {"ready": ready, "checks": checks, "llm": _llm_snapshot(orch), "safe_mode": safe_mode.status(),
            "warmup": WARMUP.snapshot()}
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
    """Public resilience metrics and circuit breaker states (no admin auth).

    DRA-47 — also carries the three top-level numbers the Observe HUD reads
    (`uptime`, `ssrf_blocked`, `redactions`) and used to substitute a seed for.
    `uptime` is a DURATION since process start (HH:MM:SS), deliberately not an
    availability percentage; the two counters are process-lifetime and reset with
    the process. `redactions` is null — never 0 — when no guardrails engine is
    attached, so the HUD renders "—" instead of "nothing was redacted". There is
    deliberately no `errors_24h`: ResilienceMetrics has no time window, so a key
    named that would be a mislabelled number.
    """
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
    uptime_seconds = max(0.0, time.monotonic() - _PROCESS_START)
    whole = int(uptime_seconds)
    orch = get_orch()
    engine = getattr(orch, "security", None) if orch else None
    redactions = None
    if engine is not None and hasattr(engine, "stats"):
        try:
            redactions = engine.stats()["counters"].get("redacted")
        except Exception:
            redactions = None
    return nocache_json({
        "metrics": metrics,
        "circuit_breakers": breakers,
        "uptime_seconds": round(uptime_seconds, 1),
        "uptime": f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d}",
        "ssrf_blocked": blocked_requests(),
        "redactions": redactions,
    })


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


# ── G21 (H160/H173): restart the hub and check for an update, owner-only ──

async def _same_origin(request: Request) -> None:
    from agents.core.routers.integrations_setup import same_origin_write

    await same_origin_write(request)


_OPS_WRITE = [Depends(admin_guard), Depends(_same_origin)]


async def _ops_audit(preview: str, action: str) -> None:
    import asyncio

    from agents.core.security.types import SecurityEvent, SecurityEventType

    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch is not None else None
    if audit is None:
        return
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
            content_preview=preview[:500], action_taken=action))
    except Exception:  # noqa: BLE001 — the action happened; a lost audit row is only logged
        import logging

        logging.getLogger("jarvis.routers.ops").warning("ops audit row lost (%s)", action)


@router.get("/api/admin/ops/update", dependencies=[Depends(admin_guard)])
async def ops_update_check():
    """What the hub runs, how it stands against its upstream as of the last fetch, and why
    applying an update from the HUD is not offered (``apply_refused``)."""
    import asyncio

    from agents.core import hub_update

    return nocache_json(await asyncio.to_thread(hub_update.check))


@router.post("/api/admin/ops/update/fetch", dependencies=_OPS_WRITE)
async def ops_update_fetch():
    """Fetch the tracked upstream in the background; poll the action by its id."""
    import asyncio

    from agents.core import hub_update

    record, refused = await asyncio.to_thread(hub_update.start_fetch)
    if record is None:
        return nocache_json({"error": refused}, status_code=409)
    await _ops_audit("update check: fetch of the tracked upstream started", "ops_update_fetch")
    return nocache_json(record, status_code=202)


@router.get("/api/admin/ops/actions/{action_id}", dependencies=[Depends(admin_guard)])
async def ops_action(action_id: str = Path(..., pattern=r"^[0-9a-f]{16}$")):
    """One ops action's status and its log lines (a fetch, a restart)."""
    from agents.core import hub_update

    record = hub_update.action(action_id)
    if record is None:
        return nocache_json({"error": "unknown_action"}, status_code=404)
    return nocache_json(record)


class RestartBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: StrictStr = Field(min_length=1, max_length=16)


@router.post("/api/admin/ops/restart", dependencies=_OPS_WRITE)
async def ops_restart(body: RestartBody):
    """Restart the hub (``{"confirm": "restart"}``). 202 when this process will restart
    itself in a moment; 409 ``manual`` when it was started some other way."""
    from agents.core import hub_update

    if body.confirm != hub_update.RESTART_CONFIRM:
        return nocache_json({"error": "confirm_required", "detail": 'send {"confirm": "restart"}'},
                            status_code=400)
    record, refused = hub_update.restart()
    if record is None:
        detail = ("this hub was not started by serve.py, so it cannot restart itself; restart it the "
                  "way it was started (systemd, START.bat, the service manager)"
                  if refused == "manual" else "another ops action is running")
        return nocache_json({"error": refused, "restart": hub_update.restart_mode(), "detail": detail},
                            status_code=409)
    await _ops_audit("hub restart requested from the HUD", "ops_restart")
    return nocache_json({**record, "restart": "requested"}, status_code=202)
