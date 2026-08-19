"""AutonomyCoordinator._record_cycle — the per-tick bridge into RuntimeRunLog.

``loop()`` calls this once on the success path and once from the outer
``except`` (see agents/core/autonomy_coordinator.py). It must be a true no-op
when no ``runtime_log`` is wired (the default, byte-identical today) and must
never let a logging failure surface as a tick failure.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy_coordinator import AutonomyCoordinator  # noqa: E402


class _FakeScheduler:
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return self._status


class _FakeRunLog:
    def __init__(self, *, raises=False):
        self.calls = []
        self._raises = raises

    def record_cycle(self, **kwargs):
        if self._raises:
            raise RuntimeError("disk full")
        self.calls.append(kwargs)


class _Orch:
    def __init__(self, *, runtime_log=None, heartbeat_scheduler=None):
        self.runtime_log = runtime_log
        self.heartbeat_scheduler = heartbeat_scheduler
        self._settings = {"autonomy.night_shift": False}

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)


def test_no_runtime_log_is_a_true_noop():
    orch = _Orch(runtime_log=None, heartbeat_scheduler=_FakeScheduler({"scheduler_running": True}))
    coordinator = AutonomyCoordinator(orch)

    coordinator._record_cycle(amode="auto", max_tier=None, ok=True)  # must not raise


def test_success_cycle_forwards_heartbeat_coordinator_and_night_shift():
    run_log = _FakeRunLog()
    orch = _Orch(
        runtime_log=run_log,
        heartbeat_scheduler=_FakeScheduler({"scheduler_running": True, "heartbeats": []}),
    )
    orch._settings["autonomy.night_shift"] = True
    coordinator = AutonomyCoordinator(orch)

    coordinator._record_cycle(amode="auto", max_tier=1, ok=True)

    assert len(run_log.calls) == 1
    call = run_log.calls[0]
    assert call["ok"] is True
    assert call["error"] == ""
    assert call["heartbeat"] == {"scheduler_running": True, "heartbeats": []}
    assert call["coordinator"] == {"mode": "auto", "max_tier": 1}
    assert call["night_shift"] == {"enabled": True, "active_window": True}


def test_missing_heartbeat_scheduler_reports_not_running():
    run_log = _FakeRunLog()
    orch = _Orch(runtime_log=run_log, heartbeat_scheduler=None)
    coordinator = AutonomyCoordinator(orch)

    coordinator._record_cycle(amode="ask", max_tier=None, ok=False, error="boom")

    call = run_log.calls[0]
    assert call["heartbeat"] == {"scheduler_running": False}
    assert call["ok"] is False
    assert call["error"] == "boom"
    assert call["night_shift"] == {"enabled": False, "active_window": False}


def test_run_log_failure_never_raises_out_of_record_cycle():
    orch = _Orch(runtime_log=_FakeRunLog(raises=True), heartbeat_scheduler=_FakeScheduler({}))
    coordinator = AutonomyCoordinator(orch)

    coordinator._record_cycle(amode="auto", max_tier=None, ok=True)  # must not raise
