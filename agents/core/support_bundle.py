"""support_bundle.py — 0.55 Design Partner Kit: a diagnostic "issue bundle".

Assembles a single, **non-sensitive** snapshot a design partner can attach to a
support request — version + posture + readiness + recent activity *counts*, so an
issue can be triaged without a screen-share or a risky data dump.

Safety is by **allow-list**, not redaction: this only ever includes the specific
aggregates below — never raw config, secrets, tokens, message content, audit
previews, or PII. Each section is assembled defensively; a source that fails is
reported as ``{"error": "unavailable"}`` rather than crashing the bundle or
leaking a traceback.

Included:
  * ``meta``         — app version, python, platform, generated_at
  * ``posture``      — hardened profile flags (CDX-12) + active system profile (0.62)
  * ``capabilities`` — readiness roll-ups (counts by state/kind; not the full list)
  * ``egress``       — per-plugin allowed/blocked/external tallies + local-only proof
  * ``audit``        — recent event *counts by type* + hash-chain integrity (no content)
  * ``routes``       — the HTTP route count
"""

from __future__ import annotations

import contextlib
import sys


def _meta(now_iso: str) -> dict:
    out = {"python": sys.version.split()[0], "platform": sys.platform, "generated_at": now_iso}
    with contextlib.suppress(Exception):
        from agents import __version__
        out["version"] = __version__
    return out


def _posture() -> dict:
    out: dict = {}
    try:
        from agents.core.security import hardened
        out["hardened"] = hardened.posture()
    except Exception:
        out["hardened"] = {"error": "unavailable"}
    try:
        from agents.core import system_profiles
        out["system_profile"] = system_profiles.list_profiles()
    except Exception:
        out["system_profile"] = {"error": "unavailable"}
    return out


def _capabilities(orch) -> dict:
    try:
        from agents.core.observability.capability_registry import snapshot
        snap = snapshot(orch)
        # roll-ups only — omit the full per-capability list to keep the bundle compact
        return {k: snap[k] for k in ("total", "by_state", "by_kind", "harness_pending") if k in snap}
    except Exception:
        return {"error": "unavailable"}


def _egress() -> dict:
    try:
        from agents.core.observability.egress_monitor import EGRESS_MONITOR
        snap = EGRESS_MONITOR.snapshot(limit=0)   # limit=0 → no event payloads, tallies only
        return {k: snap[k] for k in
                ("plugins", "external_egress_total", "local_only_violations", "clean") if k in snap}
    except Exception:
        return {"error": "unavailable"}


def _audit(orch) -> dict:
    try:
        audit = getattr(orch, "audit", None)
        if audit is None:
            return {"error": "unavailable"}
        events = audit.query(limit=500)
        counts: dict[str, int] = {}
        for e in events:
            t = str(getattr(e, "event_type", "") or "unknown")
            counts[t] = counts.get(t, 0) + 1
        out = {"recent_event_counts": counts, "window": len(events)}
        with contextlib.suppress(Exception):
            ok, broken_at = audit.verify_chain()
            out["chain_ok"] = bool(ok)
            if not ok:
                out["chain_broken_at"] = broken_at
        return out
    except Exception:
        return {"error": "unavailable"}


def _route_count() -> int | None:
    try:
        from agents.web import app
        return len(app.routes)
    except Exception:
        return None


def build_bundle(orch=None, *, now_iso: str = "") -> dict:
    """Assemble the diagnostic bundle. Pure aside from reading live diagnostics; every
    section is defensive so the bundle is always well-formed."""
    return {
        "meta": _meta(now_iso),
        "posture": _posture(),
        "capabilities": _capabilities(orch),
        "egress": _egress(),
        "audit": _audit(orch),
        "routes": _route_count(),
    }
