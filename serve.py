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
    print(f"Jarvis Hub starting at http://{config.host}:{config.port}")
    print("Features: multi-agent cabinet, skills system, memory store, cost analytics, CI/CD")
    # uvicorn.Server installs SIGINT/SIGTERM handlers and triggers the lifespan
    # shutdown (graceful channel stop + pooled-client close), bounded by
    # timeout_graceful_shutdown above.
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
