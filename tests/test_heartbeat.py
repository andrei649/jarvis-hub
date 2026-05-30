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
