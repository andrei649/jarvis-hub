#!/usr/bin/env python3
"""runtime_supervisor.py — portable crash-recovery wrapper for the Always-On coordinator.

Spawns ``python -m agents.core.autonomy.runtime_coordinator`` as a child process and
restarts it whenever it exits, with a short backoff so a boot-time crash loop doesn't
spin hot. This is the dependency-free equivalent of ``Restart=on-failure`` in
``deploy/systemd/jarvis-runtime-coordinator.service`` — use that unit in production on a
systemd host; use this script (via ``make runtime-up``) anywhere else, including inside a
container that has no init system, for local dev, and for the DoD verification loop
(``kill -9`` on the coordinator PID must recover within the backoff window).

The child's own module path contains "coordinator" (``pgrep -f coordinator`` matches it
directly), so an operator or a health check can find and signal it without consulting
this script.

Writes its own PID to ``$JARVIS_RUNTIME_SUPERVISOR_PIDFILE`` (default
``logs/runtime_supervisor.pid``) so ``make runtime-down`` can stop it cleanly. Lifecycle
events (child start / child exit / supervisor stop) are appended to the same run-log the
coordinator writes cycles to, so ``tail logs/runtime.jsonl`` tells the whole story.
"""

from __future__ import annotations

import contextlib
import os
import signal

# Fixed argv only (no shell, no string interpolation) — see the Popen call below.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents"))

MIN_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
# A child that survives at least this long resets the backoff — distinguishes a genuine
# crash loop (backs off) from an operator's intentional `kill -9` during a long healthy run.
BACKOFF_RESET_SECONDS = 30.0


def _pidfile_path() -> Path:
    env = os.environ.get("JARVIS_RUNTIME_SUPERVISOR_PIDFILE", "").strip()
    if env:
        return Path(env).expanduser()
    return REPO_ROOT / "logs" / "runtime_supervisor.pid"


def _write_pidfile(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _remove_pidfile(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


class Supervisor:
    def __init__(self, command: list[str] | None = None):
        from agents.core.autonomy.runtime_log import append_record, default_log_path

        self._append_record = append_record
        self.log_path = default_log_path()
        self._stopping = False
        self._child: subprocess.Popen | None = None
        # Overridable for tests (a real coordinator boot needs the full agent
        # roster + an LLM backend probe); production always uses the default.
        self.command = command or [sys.executable, "-m", "agents.core.autonomy.runtime_coordinator"]

    def _log(self, event: str, **extra) -> None:
        self._append_record(self.log_path, {"phase": "supervisor", "event": event, **extra})

    def _handle_signal(self, signum, _frame) -> None:
        self._stopping = True
        if self._child is not None and self._child.poll() is None:
            with contextlib.suppress(OSError):
                self._child.send_signal(signal.SIGTERM)

    def run(self) -> int:
        pidfile = _pidfile_path()
        _write_pidfile(pidfile)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)

        self._log("supervisor_start", pid=os.getpid())
        backoff = MIN_BACKOFF_SECONDS
        try:
            while not self._stopping:
                started_at = time.monotonic()
                # `self.command` defaults to a fixed argv list (module path, not a shell
                # string) and is only ever overridden by a test fixture, never by
                # untrusted/user input — no shell=True, no interpolation.
                self._child = subprocess.Popen(self.command, cwd=str(REPO_ROOT))  # noqa: S603  # nosec B603
                self._log("child_start", child_pid=self._child.pid)
                returncode = self._child.wait()
                ran_for = time.monotonic() - started_at
                self._log("child_exit", child_pid=self._child.pid, returncode=returncode, ran_seconds=round(ran_for, 1))
                self._child = None
                if self._stopping:
                    break
                if ran_for >= BACKOFF_RESET_SECONDS:
                    backoff = MIN_BACKOFF_SECONDS
                time.sleep(backoff)
                backoff = min(MAX_BACKOFF_SECONDS, backoff * 2)
            return 0
        finally:
            self._log("supervisor_stop", pid=os.getpid())
            _remove_pidfile(pidfile)


def main() -> int:
    return Supervisor().run()


if __name__ == "__main__":
    raise SystemExit(main())
