"""syscalls.py — ORIZONT-24 Track K4: kill-switch + credential quarantine as kernel calls.

Promotes the existing ``KillSwitch`` + ``SecretBroker`` to first-class kernel syscalls
(folds H23.3): **one halt** engages the kill-switch *and* quarantines credentials — secret
injection is forced blocked while halted — ``release`` resumes, and every step is audited.

**Compose, don't replace.** Like ``kernel.authorize``, the primitives are *passed in* (no
module globals), so this stays a thin, testable library:
  * halt / release  →  ``KillSwitch.engage`` / ``KillSwitch.disengage`` (already persisted).
  * quarantine      →  ``SecretBroker.inject(approved=…)`` (already gates on approval).
  * "halts new grants" is already enforced by ``kernel.authorize`` (it checks ``is_halted``).
"""

from __future__ import annotations

import contextlib

GLOBAL = "global"


def _emit(audit, action: str, why: str, metadata: dict | None = None) -> None:
    """Best-effort audit — an audit hiccup must never block a syscall."""
    if audit is None:
        return
    with contextlib.suppress(Exception):  # pragma: no cover - defensive
        audit.record(actor="kernel", action=action, why=why, metadata=metadata or {})


def halt(kill_switch, scope: str = GLOBAL, reason: str = "", *, audit=None) -> dict:
    """Engage the kill-switch for *scope* — new grants stop (via ``authorize``) and
    credentials are quarantined (via :func:`inject_guarded`). Audited."""
    entry = kill_switch.engage(scope, reason)
    _emit(audit, "kernel.halt", reason or "halt", {"scope": scope})
    return {"halted": True, "scope": scope, "entry": entry}


def release(kill_switch, scope: str = GLOBAL, *, audit=None) -> dict:
    """Disengage the kill-switch for *scope* — grants and credential injection resume. Audited."""
    released = bool(kill_switch.disengage(scope))
    _emit(audit, "kernel.release", "release", {"scope": scope, "released": released})
    return {"released": released, "scope": scope}


def is_quarantined(kill_switch, scope: str = GLOBAL) -> bool:
    """Credentials are quarantined whenever the kill-switch is halted for *scope*."""
    return bool(kill_switch.is_halted(scope))


def inject_guarded(
    secret_broker,
    kill_switch,
    text: str,
    approved: bool = False,
    scope: str = GLOBAL,
    *,
    audit=None,
) -> dict:
    """Quarantine-aware secret injection. While the kill-switch is halted, injection is
    forced **blocked** regardless of *approved* (credential quarantine). Returns the broker
    result with an added ``quarantined`` flag."""
    quarantined = is_quarantined(kill_switch, scope)
    result = secret_broker.inject(text, approved=approved and not quarantined)
    result["quarantined"] = quarantined
    if quarantined and approved:
        _emit(audit, "kernel.quarantine", "secret injection blocked (kill-switch halted)",
              {"scope": scope, "blocked": result.get("blocked", [])})
    return result
