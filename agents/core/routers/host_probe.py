"""Host capability probe route (op-host-probe) — ``GET /api/host/probe``.

One user-guarded, read-only route that runs :func:`agents.core.host_probe.probe_host`
off the event loop and returns its facts verbatim: platform, optional-dependency
presence, tri-state permissions, the closed refusal vocabulary this host trips,
and the owner flags it only *reports*.  It never actuates, never prompts for an
OS permission, and never mounts a driver — the honesty surface for the desktop
operator, nothing more.

A probe failure is itself reported honestly (``probed: false``,
``reason: probe_failed``) with no exception text, so the HUD can say "not
probed" instead of painting an empty, green-chipped host.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends

from agents.core.host_probe import REFUSAL_HINTS, REFUSAL_REASONS, probe_host
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["host"])

# Monkeypatch seam for tests (the route never imports OS libraries itself).
_probe = probe_host


@router.get("/api/host/probe", dependencies=[Depends(user_guard)])
async def host_probe():
    """What this host can honestly offer the computer operator, and why not."""
    vocabulary = sorted(REFUSAL_REASONS)
    try:
        probe = await asyncio.to_thread(_probe)
    except Exception:
        # Never carry host exception text upward; say only that the probe did not run.
        return nocache_json({
            "ok": False,
            "probed": False,
            "reason": "probe_failed",
            "vocabulary": vocabulary,
            "probed_at": time.time(),
        })
    payload = probe.to_dict()
    payload.update({
        "probed": True,
        "vocabulary": vocabulary,
        "vocabulary_hints": dict(REFUSAL_HINTS),
        "probed_at": time.time(),
    })
    return nocache_json(payload)
