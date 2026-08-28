"""
Tests for the global emergency stop (agents/core/estop.py) — the resumable
pause for NEW autonomous work (heartbeats + autonomy ticks), ported from
hermes-agent agent/estop.py (Nous Research, MIT, v2026.8.27).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import json
import logging

import pytest

from agents.core import estop


@pytest.fixture
def estop_home(tmp_path, monkeypatch):
    """Point the sentinel at a temp dir and reset the log-once bookkeeping."""
    monkeypatch.setattr(estop, "data_path", lambda *parts: tmp_path.joinpath(*parts))
    estop._reset_log_state_for_tests()
    return tmp_path


def test_disengaged_by_default(estop_home):
    assert estop.is_engaged() is False
    assert estop.get_state() is None


def test_engage_writes_reason_and_timestamp(estop_home):
    path = estop.engage("smoke in the server room")
    assert path == estop_home / "ESTOP"
    assert estop.is_engaged() is True
    state = estop.get_state()
    assert state["reason"] == "smoke in the server room"
    assert state["engaged_at"]
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["reason"] == "smoke in the server room"


def test_engage_is_idempotent_and_updates_reason(estop_home):
    estop.engage("first")
    estop.engage("second")
    assert estop.get_state()["reason"] == "second"


def test_disengage_lifts_pause_and_reports(estop_home):
    estop.engage()
    assert estop.disengage() is True
    assert estop.is_engaged() is False
    assert estop.disengage() is False  # already lifted


def test_corrupt_sentinel_still_counts_engaged(estop_home):
    # `touch data/ESTOP` (empty / non-JSON body) must still pause — fail safe.
    (estop_home / "ESTOP").write_text("not json", encoding="utf-8")
    assert estop.is_engaged() is True
    state = estop.get_state()
    assert state == {"reason": None, "engaged_at": None}


def test_check_paused_logs_once_per_engagement(estop_home, caplog):
    logger = logging.getLogger("test.estop")
    with caplog.at_level(logging.INFO, logger="test.estop"):
        assert estop.check_paused("autonomy", logger) is False
        estop.engage("drill")
        assert estop.check_paused("autonomy", logger) is True
        assert estop.check_paused("autonomy", logger) is True
        # one log line for the engaged transition, not one per tick
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 1
        # a resume re-arms the log for the next engagement
        estop.disengage()
        assert estop.check_paused("autonomy", logger) is False
        estop.engage("second drill")
        assert estop.check_paused("autonomy", logger) is True
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 2


def test_components_log_independently(estop_home, caplog):
    logger = logging.getLogger("test.estop")
    estop.engage()
    with caplog.at_level(logging.INFO, logger="test.estop"):
        assert estop.check_paused("autonomy", logger) is True
        assert estop.check_paused("heartbeat:friday", logger) is True
        paused_lines = [r for r in caplog.records if "paused" in r.getMessage()]
        assert len(paused_lines) == 2


async def test_heartbeat_dispatch_skipped_while_engaged(estop_home):
    from agents.core.heartbeat import HeartbeatScheduler

    calls = []

    class FakeOrchestrator:
        async def run_heartbeat(self, agent_id):
            calls.append(agent_id)
            return "ran"

    scheduler = HeartbeatScheduler.__new__(HeartbeatScheduler)
    estop.engage("test pause")
    await scheduler._run_heartbeat("friday", FakeOrchestrator())
    assert calls == []

    estop.disengage()
    await scheduler._run_heartbeat("friday", FakeOrchestrator())
    assert calls == ["friday"]
