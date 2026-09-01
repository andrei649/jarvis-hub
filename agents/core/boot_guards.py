"""
boot_guards.py — O26-P0.6 (finding F6): one set of fail-closed boot checks.

The repo documents two entry points: ``python serve.py`` and
``python -m uvicorn agents.web:app``. The guards below used to live only in
``serve.py``, so the raw-uvicorn path silently skipped both the
unauthenticated-external-bind refusal (AUD-4 analog) and the hardened-profile
precondition check (CDX-12) — a "hardened" box started with an unkeyed audit
chain and never knew. They now live here and run from the app lifespan too,
so every entry point enforces the same posture. ``serve.py`` re-exports them.

A third guard (H23.30 / DRA-07 / DRA-14) refuses to start when a *parse-critical*
posture flag is set to a value no spelling recognizes — the boolean flags below and
the ``JARVIS_TASK_MEDIATION`` mode enum. It runs first, before anything constructs a
memory graph or a task queue.

Residual (documented, not silently ignored): a bind host passed only as a raw
uvicorn CLI flag (``--host 0.0.0.0`` without ``JARVIS_HOST``) is invisible to
the app; the lifespan check covers the env-driven deployments (systemd/Docker
templates use ``JARVIS_HOST``), and ``serve.py`` remains the canonical entry.
"""

from __future__ import annotations

import os

_LOOPBACK_HOSTS = {"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}

# Flags whose *unrecognized* spelling resolves to the UNSAFE direction. The AUD-14 rule
# (``env_config.truthy``) sends junk to the flag's declared default, which is right
# everywhere the default is the safe position. NERVA_PUBLIC_PROFILE is the inverse: it is a
# default-off opt-in whose "on" position is the safe one, so ``NERVA_PUBLIC_PROFILE=pubic``
# reads as *private* and a public demo box seeds the owner's family into a stranger's graph
# (H23.30; tests/test_public_profile_seed_gate.py). A typo there must stop the boot rather
# than resolve to the default.
_PARSE_CRITICAL_BOOL_FLAGS = ("NERVA_PUBLIC_PROFILE",)


def assert_safe_bind(host: str) -> None:
    """Fail-closed on an unauthenticated external bind (mirrors WorldView AUD-4).

    Binding to a non-loopback address exposes the unauthenticated public routes
    (``/status``, ``/dashboard``, …) on the network, so we refuse to start unless
    the deployment is either authenticated (a ``JARVIS_USER_TOKEN`` /
    ``JARVIS_ADMIN_TOKEN`` is configured) or the insecure posture is explicitly
    acknowledged with ``JARVIS_ALLOW_INSECURE_BIND=1``. Loopback always allowed.
    """
    if host.strip().lower() in _LOOPBACK_HOSTS:
        return
    has_token = bool(os.environ.get("JARVIS_USER_TOKEN", "").strip()
                     or os.environ.get("JARVIS_ADMIN_TOKEN", "").strip())
    from agents.core.env_config import env_flag
    ack = env_flag("JARVIS_ALLOW_INSECURE_BIND")
    if has_token or ack:
        print(f"[SECURITY] binding to non-loopback host {host!r} — public routes are "
              f"reachable from the network ({'authenticated' if has_token else 'INSECURE, acknowledged'}).")
        return
    raise SystemExit(
        f"Refusing to bind to non-loopback host {host!r} without authentication.\n"
        "Set JARVIS_USER_TOKEN (and/or JARVIS_ADMIN_TOKEN) to require a credential for "
        "remote access, or set JARVIS_ALLOW_INSECURE_BIND=1 to accept an open bind. "
        "The default 127.0.0.1 keeps the hub loopback-only."
    )


def assert_hardened_posture() -> None:
    """Fail-closed on a mis-configured hardened profile (CDX-12).

    ``JARVIS_HARDENED=1`` requires its hard preconditions (today: a
    ``JARVIS_AUDIT_KEY`` so the audit log is HMAC-keyed). A hardened deployment
    that can't meet them is mis-configured, not merely suboptimal, so we refuse
    to start rather than run a weaker posture than the operator asked for.
    No-op when hardening is off.
    """
    from agents.core.security import hardened
    problems = hardened.enforce()
    if problems:
        raise SystemExit(
            "Refusing to start with JARVIS_HARDENED=1:\n  - " + "\n  - ".join(problems)
        )


def assert_parseable_posture_flags() -> None:
    """Fail-closed on a set-but-unparseable posture flag (H23.30 residual).

    This does **not** change the AUD-14 parse: ``env_config`` stays the one parse home and
    still never raises, so ``env_flag("NERVA_PUBLIC_PROFILE")`` keeps returning the declared
    default for a typo. What changes is that the box no longer *starts* with that typo, so
    the operator fixes the spelling instead of shipping the wrong posture silently. Unset,
    empty and whitespace-only mean "unset", exactly as ``env_flag`` treats them.

    The message names the variable and the accepted spellings, never the offending value —
    ``env_config``'s module contract is that nothing here logs values, and a future entry in
    ``_PARSE_CRITICAL_BOOL_FLAGS`` may well be sensitive.
    """
    from agents.core.env_config import env_flag_is_malformed

    bad = [name for name in _PARSE_CRITICAL_BOOL_FLAGS if env_flag_is_malformed(name)]
    if bad:
        raise SystemExit(
            "Refusing to start: unparseable value for " + ", ".join(bad) + ".\n"
            "Use one of 1/true/yes/on or 0/false/no/off. An unrecognized spelling silently "
            "falls back to the flag's default — for NERVA_PUBLIC_PROFILE that is the private "
            "install, which seeds the owner's personal knowledge graph — so this fails closed "
            "instead."
        )
    # Same rule, non-boolean flag: JARVIS_TASK_MEDIATION selects the B7 tamper-evidence
    # posture (off|hold|enforce) and its default, `off`, is the UNPROTECTED position — so
    # `JARVIS_TASK_MEDIATION=enfroce` must stop the boot, not quietly disable mediation.
    from agents.core.autonomy.mediation_head_store import (
        MALFORMED_MODE_MESSAGE,
        task_mediation_mode_is_malformed,
    )

    if task_mediation_mode_is_malformed():
        raise SystemExit(MALFORMED_MODE_MESSAGE)


def enforce_boot_posture() -> None:
    """Run every boot guard from the app itself (called by the web lifespan).

    The bind host is read from ``JARVIS_HOST`` (the knob the deploy templates
    and ``serve.py`` use); see the module docstring for the raw-CLI residual.
    """
    # First: a mistyped posture flag must be refused before anything constructs a
    # MemoryManager or touches the graph.
    assert_parseable_posture_flags()
    assert_safe_bind(os.environ.get("JARVIS_HOST", "127.0.0.1"))
    assert_hardened_posture()
