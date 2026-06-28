"""
serve.py — Launch Cabinet Beta web UI with full feature stack.
Detects dependencies and starts the FastAPI server.
"""

import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "agents"))

import importlib.util

# Dependency availability probes (find_spec checks without importing the module).
missing = [pkg for mod, pkg in (
    ("yaml", "pyyaml"), ("httpx", "httpx"), ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    # cryptography.fernet is hard-imported at boot via agents/core/plugins/oauth.py;
    # probe it here so a missing dep gives the friendly hint, not an opaque crash.
    ("cryptography", "cryptography"),
) if importlib.util.find_spec(mod) is None]

if missing:
    print(f"Missing dependencies: {', '.join(missing)}")
    print("Run: pip install -r requirements-beta.txt")
    sys.exit(1)

if importlib.util.find_spec("numpy") is None:
    warnings.warn("numpy not installed — vector store will be slower")

from agents.web import app


def _env_int(name: str, default: int) -> int:
    """Best-effort int env read (falls back to default on missing/garbage)."""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


_LOOPBACK_HOSTS = {"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def assert_safe_bind(host: str) -> None:
    """Fail-closed on an unauthenticated external bind (mirrors WorldView AUD-4).

    The historical default was a hardcoded 127.0.0.1; ``JARVIS_HOST`` now lets an
    operator bind elsewhere. Binding to a non-loopback address exposes the
    unauthenticated public routes (``/status``, ``/dashboard``, …) on the network,
    so we refuse to start unless the deployment is either authenticated (a
    ``JARVIS_USER_TOKEN`` / ``JARVIS_ADMIN_TOKEN`` is configured — which a real
    network deployment needs anyway for the user/admin guards to allow remote
    access) or the insecure posture is explicitly acknowledged with
    ``JARVIS_ALLOW_INSECURE_BIND=1``. Loopback binds are always allowed.
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
    that can't meet them is mis-configured, not merely suboptimal, so we refuse to
    start rather than run a weaker posture than the operator asked for. No-op when
    hardening is off.
    """
    from agents.core.security import hardened
    problems = hardened.enforce()
    if problems:
        raise SystemExit(
            "Refusing to start with JARVIS_HARDENED=1:\n  - " + "\n  - ".join(problems)
        )


def server_config():
    """Build the uvicorn config from the environment (H23.11).

    Factored out of ``main()`` so it is unit-testable without binding a socket.
    Defaults match the historical ``uvicorn.run(host=127.0.0.1, port=8080)`` call,
    so behaviour is unchanged unless an env var is set:

      JARVIS_HOST              bind host          (default 127.0.0.1 — loopback)
      JARVIS_PORT              bind port          (default 8080)
      JARVIS_LOG_LEVEL         uvicorn log level  (default info)
      JARVIS_SHUTDOWN_TIMEOUT  graceful-drain seconds for in-flight requests on
                               SIGTERM/SIGINT before they're cancelled (default 10)

    A bounded ``timeout_graceful_shutdown`` is the productionization win: uvicorn
    already installs SIGINT/SIGTERM handlers and runs the FastAPI lifespan teardown
    (channels stopped, pooled clients closed) — here we cap how long a slow in-flight
    request may delay that shutdown so a `systemctl stop` / container SIGTERM can't
    hang indefinitely.
    """
    import uvicorn
    return uvicorn.Config(
        app,
        host=os.environ.get("JARVIS_HOST", "127.0.0.1"),
        port=_env_int("JARVIS_PORT", 8080),
        log_level=os.environ.get("JARVIS_LOG_LEVEL", "info"),
        timeout_graceful_shutdown=_env_int("JARVIS_SHUTDOWN_TIMEOUT", 10),
    )


def main():
    import uvicorn
    config = server_config()
    assert_safe_bind(config.host)   # fail-closed on an unauthenticated external bind
    assert_hardened_posture()       # fail-closed on a mis-configured hardened profile (CDX-12)
    print(f"Jarvis Hub starting at http://{config.host}:{config.port}")
    print("Features: multi-agent cabinet, skills system, memory store, cost analytics, CI/CD")
    # uvicorn.Server installs SIGINT/SIGTERM handlers and triggers the lifespan
    # shutdown (graceful channel stop + pooled-client close), bounded by
    # timeout_graceful_shutdown above.
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
