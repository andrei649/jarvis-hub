"""Security HUD reads (bare /security + /security/status) — extracted from web.py (CLN-3).

The two unguarded HUD reads that sit on the bare `/security` prefix (distinct from
the `/api/security/*` trust surface owned by `routers/security.py`). Behavior-frozen
move: paths/methods/bodies are byte-identical to the web.py originals.

Both read the live orchestrator, resolved at REQUEST time via `get_orch()` (web
owns the `orch` global; the suite rebinds it). `security_status` used to be fully
static — every counter a literal zero and the mode always "WARN" — which the
Console rendered as measured security activity; it now reports the guardrail
engine's real counters, or `available: false` for what is genuinely not measured.
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
    """Live security system status.

    Every number here used to be a literal. `mode` was always "WARN", the redact
    and block counts were always 0, the pattern counts were hand-written (10 and
    6 — both wrong), and the SSRF counters were 0. The Console renders these as
    measured security activity, so a hub running in BLOCK mode that had redacted
    forty PII spans reported a clean, untriggered system with the wrong mode.

    The engine now counts what it does; anything still unmeasured is reported as
    null with `available: false`, never as a zero that reads like a measurement.
    """
    orch = get_orch()
    engine = getattr(orch, "security", None) if orch else None
    stats = engine.stats() if hasattr(engine, "stats") else None

    if stats is None:
        # Guardrails are not running. That is a real fact and worth stating — but
        # it is "no guardrails", not "guardrails found nothing".
        guardrails = {"enabled": False, "mode": None, "available": False,
                      "note": "guardrails engine is not attached"}
        scanners: dict = {}
    else:
        counters = stats["counters"]
        guardrails = {
            "enabled": True,
            "available": True,
            "mode": stats["mode"],
            "scan_input": stats["scan_input"],
            "scan_output": stats["scan_output"],
            "scans": counters.get("scanned", 0),
            "findings": counters.get("findings", 0),
            "warn_count": counters.get("warned", 0),
            "redact_count": counters.get("redacted", 0),
            "block_count": counters.get("blocked", 0),
        }
        # Pattern counts from the compiled ruleset. Per-scanner finding counts are
        # not tracked separately (the engine merges results before it sees which
        # scanner produced what), so that is reported as unknown rather than 0.
        scanners = {
            sid: {"patterns": s["patterns"], "findings": None, "available": False}
            for sid, s in stats["scanners"].items()
        }

    # SSRF: the guard is real, its counters are not wired up. Say so.
    ssrf = {
        "enabled": True,
        "max_redirects": 5,
        "blocked_requests": None,
        "available": False,
        "note": "the SSRF guard is active but does not yet count blocked requests",
    }
    return nocache_json({"guardrails": guardrails, "scanners": scanners, "ssrf": ssrf})
