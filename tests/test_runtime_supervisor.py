"""scripts/runtime_supervisor.py — the crash/respawn loop, proven against a real
subprocess (not a mock) so the ``kill -9`` recovery guarantee is real.

Points ``_COORDINATOR`` at a tiny throwaway script instead of the real
scripts/coordinator.py so each cycle is near-instant and deterministic;
end-to-end recovery of the real coordinator is covered by manual verification
(HANDOFF.md) since a real cycle needs >=15s wall clock.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_fake_child(tmp_path: Path, *, sleep_seconds: float) -> Path:
    script = tmp_path / "fake_coordinator.py"
    script.write_text(
        f"import time\ntime.sleep({sleep_seconds})\n",
        encoding="utf-8",
    )
    return script


def _run_log(tmp_path: Path) -> Path:
    return tmp_path / "runtime.jsonl"


def _read_events(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def _wait_for(predicate, *, timeout: float = 10.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_supervisor_respawns_a_child_that_exits_and_logs_it(tmp_path, monkeypatch):
    fake_child = _write_fake_child(tmp_path, sleep_seconds=0.2)
    log_path = _run_log(tmp_path)
    env = dict(os.environ)
    env["JARVIS_RUNTIME_LOG"] = str(log_path)
    env["JARVIS_RUNTIME_RESPAWN_DELAY"] = "0.1"

    supervisor_src = (_REPO_ROOT / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = supervisor_src.replace(
        '_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
        f"_COORDINATOR = {str(fake_child)!r}",
    )
    supervisor_script = tmp_path / "runtime_supervisor.py"
    supervisor_script.write_text(patched, encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(supervisor_script)], env=env)
    try:
        assert _wait_for(lambda: len(_read_events(log_path)) >= 5, timeout=15.0)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)

    events = _read_events(log_path)
    kinds = [e["supervisor_event"] for e in events]
    assert kinds[0] == "spawned"
    assert "child_exited" in kinds
    assert "respawned" in kinds
    assert kinds[-1] == "stopped"


def test_supervisor_recovers_a_sigkilled_child_within_seconds(tmp_path):
    fake_child = _write_fake_child(tmp_path, sleep_seconds=30.0)
    log_path = _run_log(tmp_path)
    env = dict(os.environ)
    env["JARVIS_RUNTIME_LOG"] = str(log_path)
    env["JARVIS_RUNTIME_RESPAWN_DELAY"] = "0.1"

    supervisor_src = (_REPO_ROOT / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = supervisor_src.replace(
        '_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
        f"_COORDINATOR = {str(fake_child)!r}",
    )
    supervisor_script = tmp_path / "runtime_supervisor.py"
    supervisor_script.write_text(patched, encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(supervisor_script)], env=env)
    try:
        assert _wait_for(lambda: len(_read_events(log_path)) >= 1, timeout=10.0)
        first_pid = _read_events(log_path)[0]["pid"]

        os.kill(first_pid, signal.SIGKILL)

        def _respawned_with_new_pid() -> bool:
            events = _read_events(log_path)
            return any(
                e["supervisor_event"] == "respawned" and e["pid"] != first_pid for e in events
            )

        assert _wait_for(_respawned_with_new_pid, timeout=10.0)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)

    events = _read_events(log_path)
    exited = next(e for e in events if e["supervisor_event"] == "child_exited")
    assert exited["pid"] == first_pid
    # SIGKILL exit code is negative signal number on POSIX.
    assert exited["exit_code"] == -signal.SIGKILL
