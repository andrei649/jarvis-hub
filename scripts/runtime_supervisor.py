#!/usr/bin/env python3
"""runtime_supervisor.py — the single supervisor entrypoint.

Spawns ``scripts/coordinator.py`` (coordinator + heartbeat + night shift,
wired for real — see that module's docstring) as a child process and
respawns it immediately if it dies for any reason, including ``SIGKILL``: a
process cannot recover itself from ``kill -9``, so a killed coordinator's
recovery is this parent's job. Every respawn is appended to the same
``logs/runtime.jsonl`` the coordinator writes to, so a crash-and-recover is
visible in the run-log the morning brief reads, not just in stderr.

This is what ``deploy/systemd/jarvis-runtime.service`` and the
``runtime-coordinator`` docker-compose service both run. Layering systemd/
docker's own ``restart`` policy on top of this respawn loop is intentional
defense in depth: if the supervisor itself dies, the OS-level restart is the
backstop.

Usage:
    python scripts/runtime_supervisor.py
    (SIGTERM/SIGINT stop it — and the current child — cleanly)

Env (forwarded to the child; also read directly):
  JARVIS_RUNTIME_LOG            run-log path (default logs/runtime.jsonl)
  JARVIS_RUNTIME_RESPAWN_DELAY  minimum seconds between respawns (default 1.0,
                                 backs off a hot crash loop instead of
                                 spinning at 100% CPU)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # noqa: S404  # nosec B404  (fixed-argv commands, never a shell)
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")


def _log_path() -> Path:
    return Path(os.environ.get("JARVIS_RUNTIME_LOG", "logs/runtime.jsonl"))


def _append_supervisor_event(event: str, **fields) -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"supervisor_event": event, "at": time.time(), **fields}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError:
        pass  # the run-log is observability, never a reason to fail the supervisor


def main() -> int:
    respawn_delay = float(os.environ.get("JARVIS_RUNTIME_RESPAWN_DELAY", "1.0"))
    stopping = False

    def _request_stop(signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)

    # Fixed argv (this interpreter + a repo-relative script path) — no shell,
    # no untrusted input; matches the repo's other internal subprocess seams.
    child = subprocess.Popen([sys.executable, _COORDINATOR])  # noqa: S603  # nosec B603
    _append_supervisor_event("spawned", pid=child.pid)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    try:
        while True:
            exit_code = child.wait()
            if stopping:
                _append_supervisor_event("stopped", pid=child.pid, exit_code=exit_code)
                return 0
            _append_supervisor_event("child_exited", pid=child.pid, exit_code=exit_code)
            time.sleep(respawn_delay)
            child = subprocess.Popen([sys.executable, _COORDINATOR])  # noqa: S603  # nosec B603
            _append_supervisor_event("respawned", pid=child.pid)
    finally:
        if child.poll() is None:
            child.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
