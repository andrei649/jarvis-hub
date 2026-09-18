"""
serve.py — Launch Cabinet Beta web UI with full feature stack.
Detects dependencies and starts the FastAPI server.
"""

import errno
import os
import socket
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

# O26-P0.6 (F6): the boot guards moved to agents/core/boot_guards.py so the
# raw-uvicorn entry (`python -m uvicorn agents.web:app`) enforces the same
# posture via the app lifespan. Re-exported here — serve.py stays the
# canonical entry and existing imports keep working.
from agents.core.boot_guards import (  # noqa: E402,F401
    assert_hardened_posture,
    assert_parseable_posture_flags,
    assert_safe_bind,
)
from agents.core.env_config import env_int  # noqa: E402  (O26-P2.1: was a local _env_int)
from agents.web import app


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
        port=env_int("JARVIS_PORT", 8080),
        log_level=os.environ.get("JARVIS_LOG_LEVEL", "info"),
        timeout_graceful_shutdown=env_int("JARVIS_SHUTDOWN_TIMEOUT", 10),
    )


#: Exit codes for the pre-bind port probe (H042). Deliberately distinct from
#: uvicorn's own ``STARTUP_FAILURE`` (3), which it uses for *every* startup
#: failure — so today "the port is taken" and "the lifespan blew up" are the
#: same exit code to a supervisor or a script.
EXIT_PORT_IN_USE = 12
EXIT_PORT_DENIED = 13


def probe_bind(host: str, port: int) -> None:
    """Name the cause when the configured port cannot be bound (H042).

    A **diagnostic, not a lock**. It binds and immediately closes a socket on the
    address uvicorn is about to bind, purely so the owner gets a sentence instead
    of uvicorn's bare ``[Errno 98] address already in use`` followed by exit 3.
    Nothing is reserved between this probe and the real bind, so the race is real
    and deliberate: if something grabs the port in that window, uvicorn fails
    exactly as it does today. The probe only ever *adds* an explanation — it must
    never turn a boot that would have worked into a refusal.

    That guarantee is why the socket mirrors asyncio's own flags instead of
    stricter ones. ``uvicorn.Server.startup`` binds through
    ``loop.create_server(host=..., port=...)``, and asyncio sets ``SO_REUSEADDR``
    there on POSIX only (``reuse_address = os.name == "posix"``). A probe *without*
    it would be stricter than the real bind: a port still holding a TIME_WAIT
    connection from the instance the owner just Ctrl-C'd refuses a plain bind but
    accepts uvicorn's, so the probe would block a restart that actually works. On
    Windows asyncio sets no reuse flag and neither do we — there ``SO_REUSEADDR``
    means "bind over whoever holds it", which would make the probe report a busy
    port as free. (Read against uvicorn 0.52.4 + CPython 3.12. The POSIX half is
    *executed* here — `test_probe_bind_does_not_block_a_restart_over_time_wait`
    reproduces the TIME_WAIT state and watches the probe stay silent. The Windows
    half is read off asyncio's ``reuse_address = os.name == "posix"`` line and has
    never been run: this is Linux, and that test skips off POSIX.)

    Any ``OSError`` we do not recognise is swallowed for the same reason: an
    unexpected probe failure must not become a boot failure — uvicorn's own bind
    stays the authority on those. **The constructor is inside the guarded region
    too**, not just the bind: ``JARVIS_HOST=::1`` on a box with no IPv6 stack
    raises ``EAFNOSUPPORT`` from ``socket.socket()`` itself, and letting that
    escape would replace uvicorn's clean one-line error + exit 3 with a traceback
    pointing at this helper + exit 1 — the exact ergonomics failure H042 exists to
    remove, inflicted by the fix for it.
    """
    if port == 0:
        return  # "pick any free port" — there is nothing to conflict with
    # An IPv6 literal carries a colon; everything else is probed as AF_INET. That
    # is *one* family, while uvicorn binds every address getaddrinfo returns for
    # the host — so a dual-stack name like "localhost" is probed on v4 only and can
    # miss a conflict held on the v6 address. That miss is in the silent direction
    # (uvicorn then reports it exactly as it does today), which is the only
    # direction this probe is allowed to be wrong in.
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = None
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        if os.name == "posix":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Port unavailable: something is already listening on {host}:{port} — "
                f"if that is Nerva, `nerva status` will say so; otherwise set JARVIS_PORT "
                f"to another port and start again.",
                file=sys.stderr,
            )
            raise SystemExit(EXIT_PORT_IN_USE) from None
        if exc.errno == errno.EACCES:
            print(
                f"Port refused: not allowed to bind {host}:{port} — ports below 1024 need "
                f"root or CAP_NET_BIND_SERVICE; set JARVIS_PORT to a port above 1024.",
                file=sys.stderr,
            )
            raise SystemExit(EXIT_PORT_DENIED) from None
        # Anything else (a host that is not local to this box, an exotic family)
        # is not a diagnosis we can stand behind — let uvicorn's bind report it.
    finally:
        if sock is not None:      # the constructor itself may have raised
            sock.close()


def main():
    import uvicorn
    config = server_config()
    assert_parseable_posture_flags()  # fail-closed on a mistyped posture flag (H23.30)
    assert_safe_bind(config.host)   # fail-closed on an unauthenticated external bind
    assert_hardened_posture()       # fail-closed on a mis-configured hardened profile (CDX-12)
    # Posture guards run first (they must fail-closed even on a taken port); only
    # then do we tell the owner *why* the bind is about to fail (H042).
    probe_bind(config.host, config.port)
    # Packaged installs: create + announce the owner's data folder up front so
    # first-run users know exactly where their memory/config/skills live.
    from agents.core.paths import ensure_user_home
    home = ensure_user_home()
    if home is not None:
        print(f"Your data lives in: {home}  (config: {home / '.env'})")
    print(f"Nerva starting at http://{config.host}:{config.port}")
    print("Features: multi-agent cabinet, skills system, memory store, cost analytics, CI/CD")
    # uvicorn.Server installs SIGINT/SIGTERM handlers and triggers the lifespan
    # shutdown (graceful channel stop + pooled-client close), bounded by
    # timeout_graceful_shutdown above.
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
