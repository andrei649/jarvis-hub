"""Tests for HeartbeatScheduler — parsing, loading, scheduling."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.heartbeat import HeartbeatScheduler


def test_init_default_dir():
    hb = HeartbeatScheduler()
    assert hb.agents_dir == Path("agents")
    assert hb._heartbeat_configs == {}
    assert hb.scheduler is None


def test_load_all_nonexistent_dir(caplog):
    hb = HeartbeatScheduler(agents_dir="/nonexistent/path")
    hb.load_all()
    assert hb._heartbeat_configs == {}


def test_parse_heartbeat_invalid_yaml(tmp_path):
    hb = HeartbeatScheduler()
    hb_file = tmp_path / "HEARTBEAT.md"
    hb_file.write_text("---\ninvalid: [yaml\n---\nbody")
    result = hb._parse_heartbeat(hb_file)
    assert result is None


def test_parse_heartbeat_no_frontmatter(tmp_path):
    hb = HeartbeatScheduler()
    hb_file = tmp_path / "HEARTBEAT.md"
    hb_file.write_text("Just a regular markdown file")
    result = hb._parse_heartbeat(hb_file)
    assert result is None


def test_parse_heartbeat_valid(tmp_path):
    hb = HeartbeatScheduler()
    hb_file = tmp_path / "HEARTBEAT.md"
    hb_file.write_text("---\nagent: friday\ncadence: cron:30 6 * * *\n---\nbody")
    result = hb._parse_heartbeat(hb_file)
    assert result is not None
    assert result["agent"] == "friday"
    assert result["cadence"] == "cron:30 6 * * *"


def test_load_all_reads_heartbeat_files(tmp_path):
    agent_dir = tmp_path / "friday"
    agent_dir.mkdir()
    hb_file = agent_dir / "HEARTBEAT.md"
    hb_file.write_text("---\nagent: friday\ncadence: cron:30 6 * * *\n---\nbody")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    hb.load_all()
    assert "friday" in hb._heartbeat_configs
    assert hb._heartbeat_configs["friday"]["cadence"] == "cron:30 6 * * *"


def test_start_no_apscheduler(monkeypatch):
    monkeypatch.setattr("core.heartbeat.AsyncIOScheduler", None)
    hb = HeartbeatScheduler()
    hb.start(None)
    assert hb.scheduler is None


def test_stop_without_start():
    hb = HeartbeatScheduler()
    hb.stop()  # should not raise


def test_cron_fires_per_day_every_minute():
    hb = HeartbeatScheduler()
    fires = hb._cron_fires_per_day(["*", "*", "*", "*", "*"])
    assert fires > 1400  # 1440x/day for * * * * *


def test_cron_fires_per_day_every_2_hours():
    hb = HeartbeatScheduler()
    fires = hb._cron_fires_per_day(["0", "*/2", "*", "*", "*"])
    assert fires == 12.0  # 12x/day for every 2h


def test_cron_fires_per_day_twice_daily():
    hb = HeartbeatScheduler()
    fires = hb._cron_fires_per_day(["0", "6,18", "*", "*", "*"])
    assert fires == 2.0  # 2x/day


def test_cron_fires_per_day_daily():
    hb = HeartbeatScheduler()
    fires = hb._cron_fires_per_day(["30", "6", "*", "*", "*"])
    assert fires == 1.0  # 1x/day


def test_frequent_heartbeat_warns_and_adds_jitter(caplog):
    hb = HeartbeatScheduler()
    config = {"agent": "steve", "cadence": "cron:* * * * *"}
    hb._heartbeat_configs["steve"] = config

    from unittest.mock import MagicMock
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    hb.scheduler = mock_scheduler

    import logging
    with caplog.at_level(logging.WARNING):
        hb.start(None)
    assert any("fires" in r.message for r in caplog.records)
    assert len(hb.scheduler.add_job.call_args_list) >= 1


def test_normal_heartbeat_no_warning(caplog):
    hb = HeartbeatScheduler()
    config = {"agent": "friday", "cadence": "cron:30 6 * * *"}
    hb._heartbeat_configs["friday"] = config

    from unittest.mock import MagicMock
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    hb.scheduler = mock_scheduler

    import logging
    with caplog.at_level(logging.WARNING):
        hb.start(None)
    warning_messages = [r.message for r in caplog.records if "fires" in r.message]
    assert len(warning_messages) == 0
    assert len(hb.scheduler.add_job.call_args_list) >= 1


# ─── Interval parsing tests ────────────────────────────────────────────────

def test_parse_interval_hours():
    hb = HeartbeatScheduler()
    assert hb._parse_interval("12h") == 43200
    assert hb._parse_interval("6h") == 21600
    assert hb._parse_interval("1h") == 3600
    assert hb._parse_interval("2h") == 7200


def test_parse_interval_minutes():
    hb = HeartbeatScheduler()
    assert hb._parse_interval("30m") == 1800
    assert hb._parse_interval("5m") == 300


def test_parse_interval_seconds():
    hb = HeartbeatScheduler()
    assert hb._parse_interval("90s") == 90


def test_parse_interval_plain_seconds():
    hb = HeartbeatScheduler()
    assert hb._parse_interval("3600") == 3600


def test_parse_interval_invalid_defaults_to_min(caplog):
    hb = HeartbeatScheduler()
    import logging
    with caplog.at_level(logging.WARNING):
        result = hb._parse_interval("foo")
    assert result == 3600  # MIN_HEARTBEAT_INTERVAL fallback
    assert any("Unrecognized" in r.message for r in caplog.records)


def test_coerce_interval_below_min(caplog):
    hb = HeartbeatScheduler()
    import logging
    with caplog.at_level(logging.WARNING):
        result = hb._coerce_interval(1800)
    assert result == 3600  # coerced upward
    assert any("coercing" in r.message.lower() for r in caplog.records)


def test_coerce_interval_above_min():
    hb = HeartbeatScheduler()
    assert hb._coerce_interval(7200) == 7200


def test_coerce_interval_at_min():
    hb = HeartbeatScheduler()
    assert hb._coerce_interval(3600) == 3600


# ─── Config-based loading tests ─────────────────────────────────────────────

def test_load_from_config_with_intervals():
    from unittest.mock import MagicMock

    hb = HeartbeatScheduler()
    mock_agent = MagicMock()
    mock_agent.status = "active"
    mock_agent.has_heartbeat = True
    mock_agent.heartbeat = "12h"
    mock_config = MagicMock()
    mock_config.agents = {"jarvis": mock_agent}

    hb.load_from_config(mock_config)
    assert "jarvis" in hb._heartbeat_configs
    assert hb._heartbeat_configs["jarvis"]["interval_seconds"] == 43200
    assert hb._heartbeat_configs["jarvis"]["cadence"] == "interval:43200"


def test_load_from_config_skips_no():
    from unittest.mock import MagicMock

    hb = HeartbeatScheduler()
    mock_agent = MagicMock()
    mock_agent.status = "active"
    mock_agent.has_heartbeat = False
    mock_agent.heartbeat = "no"
    mock_config = MagicMock()
    mock_config.agents = {"howard": mock_agent}

    hb.load_from_config(mock_config)
    assert "howard" not in hb._heartbeat_configs


def test_load_from_config_skips_inactive():
    from unittest.mock import MagicMock

    hb = HeartbeatScheduler()
    mock_agent = MagicMock()
    mock_agent.status = "bench"
    mock_agent.has_heartbeat = True
    mock_agent.heartbeat = "6h"
    mock_config = MagicMock()
    mock_config.agents = {"bruce": mock_agent}

    hb.load_from_config(mock_config)
    assert "bruce" not in hb._heartbeat_configs


def test_load_from_config_coerces_sub_minimum():
    from unittest.mock import MagicMock

    hb = HeartbeatScheduler()
    mock_agent = MagicMock()
    mock_agent.status = "active"
    mock_agent.has_heartbeat = True
    mock_agent.heartbeat = "30m"
    mock_config = MagicMock()
    mock_config.agents = {"steve": mock_agent}

    hb.load_from_config(mock_config)
    assert hb._heartbeat_configs["steve"]["interval_seconds"] == 3600  # coerced from 1800


# ─── Interval scheduling tests ──────────────────────────────────────────────

def test_start_schedules_interval_jobs():
    from unittest.mock import MagicMock, ANY

    hb = HeartbeatScheduler()
    hb._heartbeat_configs["jarvis"] = {
        "agent": "jarvis",
        "cadence": "interval:43200",
        "interval_seconds": 43200,
    }

    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    hb.scheduler = mock_scheduler

    hb.start(None)

    mock_scheduler.add_job.assert_called_once()
    call_args = mock_scheduler.add_job.call_args
    assert call_args[0][1] == "interval"  # trigger type
    assert call_args[1]["seconds"] == 43200
    assert call_args[1]["id"] == "heartbeat-jarvis"
    assert "jitter" in call_args[1]


def test_start_interval_job_has_jitter():
    from unittest.mock import MagicMock

    hb = HeartbeatScheduler()
    hb._heartbeat_configs["friday"] = {
        "agent": "friday",
        "cadence": "interval:21600",
        "interval_seconds": 21600,
    }

    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    hb.scheduler = mock_scheduler

    hb.start(None)

    call_kwargs = mock_scheduler.add_job.call_args[1]
    jitter = call_kwargs["jitter"]
    assert 15 <= jitter <= 30
