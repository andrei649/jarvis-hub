"""hardened.py — CDX-12 "Design-Partner / Hardened" profile.

A single opt-in switch — ``JARVIS_HARDENED=1`` — that tightens four posture
toggles at once for a design-partner / multi-tenant deployment. Default **OFF**:
nothing changes until the owner sets it, so every existing behavior is preserved.

The preset never *invents* policy; it only forces the safe direction of toggles
the system already has, and makes them non-overridable while it is on:

  1. **Guardrails** default ``WARN`` → ``REDACT`` (``security.guardrails_mode``).
     An explicit owner setting still wins; only the *default* tightens.
  2. **Audit HMAC required** — ``JARVIS_AUDIT_KEY`` must be present, else startup
     fails closed (``enforce()`` returns a violation that ``serve.py`` raises on).
  3. **Strict egress forced** — the ``JARVIS_STRICT_EGRESS=0`` downgrade escape
     hatch is ignored, so egress stays strict.
  4. **Mutating MCP forced off** — ``JARVIS_MCP_MUTATING_TOOLS`` cannot re-open the
     write surface.

It also turns on CDX-11 plugin least-privilege, which already reads
``JARVIS_HARDENED`` directly (see ``plugin_gate.least_privilege_from_env``).
"""

from __future__ import annotations

import os

_TRUTHY = ("1", "true", "yes", "on")


def enabled() -> bool:
    """True when the hardened profile is on (``JARVIS_HARDENED``)."""
    return os.environ.get("JARVIS_HARDENED", "").strip().lower() in _TRUTHY


def guardrails_default(base: str = "WARN") -> str:
    """Default guardrails mode — ``REDACT`` under hardening, else *base* (``WARN``).

    This is only the *default*: an explicit ``security.guardrails_mode`` setting
    still takes precedence at the call site.
    """
    return "REDACT" if enabled() else base


def strict_egress_forced() -> bool:
    """When True, ignore a ``JARVIS_STRICT_EGRESS=0`` downgrade and stay strict."""
    return enabled()


def mutating_mcp_blocked() -> bool:
    """When True, mutating MCP route tools stay off regardless of their env switch."""
    return enabled()


def audit_key_required() -> bool:
    """When True, the audit log must be HMAC-keyed (``JARVIS_AUDIT_KEY`` set)."""
    return enabled()


def missing_audit_key() -> bool:
    """True iff hardening is on but no ``JARVIS_AUDIT_KEY`` is configured."""
    return enabled() and not os.environ.get("JARVIS_AUDIT_KEY", "").strip()


def posture() -> dict:
    """Machine-readable snapshot of the hardened toggles (for ``/api/security``)."""
    return {
        "enabled": enabled(),
        "guardrails_mode_default": guardrails_default(),
        "audit_key_required": audit_key_required(),
        "audit_key_present": bool(os.environ.get("JARVIS_AUDIT_KEY", "").strip()),
        "strict_egress_forced": strict_egress_forced(),
        "mutating_mcp_blocked": mutating_mcp_blocked(),
        "plugin_least_privilege": enabled(),  # CDX-11 reads JARVIS_HARDENED too
    }


def enforce() -> list[str]:
    """Return fatal posture violations (empty when ok). Callers fail closed on a
    non-empty list. Today the only hard requirement is the audit key: a hardened
    deployment that can't HMAC-key its audit log is mis-configured, not merely
    suboptimal, so it must not start silently."""
    problems: list[str] = []
    if missing_audit_key():
        problems.append(
            "JARVIS_HARDENED=1 requires JARVIS_AUDIT_KEY so the audit log is "
            "HMAC-keyed (an attacker with DB write access cannot forge the chain "
            "without it). Set JARVIS_AUDIT_KEY or unset JARVIS_HARDENED."
        )
    return problems
