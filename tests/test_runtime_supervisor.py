"""Tests for scripts/runtime_supervisor.py — the portable crash-recovery wrapper.

Spawns a real child process (not the real coordinator, which needs a full agent
boot) so the restart-on-exit and pidfile lifecycle are exercised end to end, not
just mocked. Kept fast: the fake child exits immediately and backoff constants
are patched down to milliseconds.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import signal
import threading
import time

import pytest
import runtime_supervisor as rs

from agents.core.autonomy.runtime_log import read_records


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(rs, "MIN_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(rs, "MAX_BACKOFF_SECONDS", 0.2)
    monkeypatch.setattr(rs, "BACKOFF_RESET_SECONDS", 999.0)  # never counts as "long-lived" in this test


@pytest.fixture
def env(tmp_path, monkeypatch):
    log_path = tmp_path / "runtime.jsonl"
    pidfile = tmp_path / "supervisor.pid"
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(log_path))
    monkeypatch.setenv("JARVIS_RUNTIME_SUPERVISOR_PIDFILE", str(pidfile))
    return {"log_path": log_path, "pidfile": pidfile}


def _stop_after(supervisor: "rs.Supervisor", delay: float):
    # Only flips the flag — never forces the child down. The loop checks
    # `_stopping` right after the current child's own `wait()` returns, so a
    # fast-exiting child (this test's `sys.exit(1)`) stops the loop cleanly on
    # its own. Forcing a `.terminate()` here would race a child that hasn't
    # reached `sys.exit(1)` yet under CI load, turning a clean returncode 1
    # into a SIGTERM (-15) and making the assertion below flaky.
    threading.Timer(delay, lambda: setattr(supervisor, "_stopping", True)).start()


def test_restarts_a_crashing_child_and_logs_lifecycle(env):
    # A child that exits immediately (nonzero) — the supervisor must restart it
    # more than once within the test window, proving crash recovery works.
    supervisor = rs.Supervisor(command=[sys.executable, "-c", "import sys; sys.exit(1)"])
    _stop_after(supervisor, 0.6)
    supervisor.run()

    records = read_records(env["log_path"])
    starts = [r for r in records if r.get("event") == "child_start"]
    exits = [r for r in records if r.get("event") == "child_exit"]
    assert len(starts) >= 2, "expected the supervisor to restart the crashing child at least once"
    assert len(exits) >= 1
    assert all(r["returncode"] == 1 for r in exits)
    assert any(r["event"] == "supervisor_start" for r in records)
    assert any(r["event"] == "supervisor_stop" for r in records)
    assert not env["pidfile"].exists()


def test_sigterm_stops_supervisor_and_child_without_restart(env):
    # `signal.signal()` only works on the interpreter's main thread, so `run()`
    # (which registers handlers) must execute there. The timer calls the
    # registered handler directly rather than raising a real OS signal: on
    # Windows, `os.kill(os.getpid(), SIGTERM)` does not invoke the Python
    # handler at all — it calls TerminateProcess on the *current* process,
    # killing the interpreter outright (verified against CPython's os.kill
    # docs). Under pytest-xdist that silently kills the worker mid-test with
    # no result ever reported, hanging the whole run rather than failing it.
    # Calling the handler directly exercises the same application logic
    # (stopping flag + child SIGTERM) without depending on OS signal delivery.
    supervisor = rs.Supervisor(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    threading.Timer(0.2, lambda: supervisor._handle_signal(signal.SIGTERM, None)).start()
    supervisor.run()

    records = read_records(env["log_path"])
    starts = [r for r in records if r.get("event") == "child_start"]
    assert len(starts) == 1, "SIGTERM must not trigger a restart"
    assert not env["pidfile"].exists()


def test_pidfile_written_while_running_and_removed_after(env):
    # See the note above `test_sigterm_stops_supervisor_and_child_without_restart`
    # on why the handler is called directly instead of raising a real OS signal.
    supervisor = rs.Supervisor(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    seen_pidfile = {}

    def _check_and_signal():
        seen_pidfile["exists"] = env["pidfile"].exists()
        seen_pidfile["pid"] = env["pidfile"].read_text().strip() if seen_pidfile["exists"] else None
        supervisor._handle_signal(signal.SIGTERM, None)

    threading.Timer(0.2, _check_and_signal).start()
    supervisor.run()

    assert seen_pidfile["exists"] is True
    assert seen_pidfile["pid"] == str(os.getpid())
    assert not env["pidfile"].exists()
