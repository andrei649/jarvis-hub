"""
boot_guards.py — O26-P0.6 (finding F6): one set of fail-closed boot checks.

The repo documents two entry points: ``python serve.py`` and
``python -m uvicorn agents.web:app``. The guards below used to live only in
``serve.py``, so the raw-uvicorn path silently skipped both the
unauthenticated-external-bind refusal (AUD-4 analog) and the hardened-profile
precondition check (CDX-12) — a "hardened" box started with an unkeyed audit
chain and never knew. They now live here and run from the app lifespan too,
so every entry point enforces the same posture. ``serve.py`` re-exports them.

Residual (documented, not silently ignored): a bind host passed only as a raw
uvicorn CLI flag (``--host 0.0.0.0`` without ``JARVIS_HOST``) is invisible to
the app; the lifespan check covers the env-driven deployments (systemd/Docker
templates use ``JARVIS_HOST``), and ``serve.py`` remains the canonical entry.
"""

from __future__ import annotations

import os

_LOOPBACK_HOSTS = {"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


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
    ack = os.environ.get("JARVIS_ALLOW_INSECURE_BIND", "").strip().lower() in ("1", "true", "yes")
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


def enforce_boot_posture() -> None:
    """Run every boot guard from the app itself (called by the web lifespan).

    The bind host is read from ``JARVIS_HOST`` (the knob the deploy templates
    and ``serve.py`` use); see the module docstring for the raw-CLI residual.
    """
    assert_safe_bind(os.environ.get("JARVIS_HOST", "127.0.0.1"))
    assert_hardened_posture()
