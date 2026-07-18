"""
degradation.py — shared "honest fallback" helper for plugins.

Many plugins ship a real integration path that degrades to mock / placeholder
data when its credential, hardware, or engine isn't configured. Historically each
did this ad-hoc — a bare ``{"_mock": True}``, a ``mock_sent`` status, or nothing
at all — so the HUD and callers could not reliably tell a *real* result from a
*degraded* one. That is the sharp edge behind "the product looks live but isn't":
a mocked toggle was indistinguishable from a real one.

This module gives one shape for "this is not real data, and here is why / what it
needs", so degraded features can be badged consistently everywhere.
"""
from __future__ import annotations

from typing import Any


def degraded(payload: dict | None = None, *, reason: str,
             needs: list[str] | None = None) -> dict:
    """Stamp a payload as a degraded (non-live) result.

    Preserves any real keys already in ``payload`` (so existing consumers still
    find e.g. ``monthly_spend``) and adds machine-readable degradation metadata:

    * ``_mock`` / ``mock`` — legacy boolean flags callers already check.
    * ``_degraded`` — ``{"reason": <why>, "needs": [<config the owner must supply>]}``.
    """
    out: dict[str, Any] = dict(payload or {})
    out["_mock"] = True
    out["mock"] = True
    out["_degraded"] = {"reason": reason, "needs": list(needs or [])}
    return out


def is_degraded(payload: Any) -> bool:
    """True if a payload carries any known degradation marker."""
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("_mock") or payload.get("mock") or payload.get("_degraded"))
