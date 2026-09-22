"""HEARTBEAT.md wins over the agents.yaml interval; a refused file is scheduled from neither.

`HeartbeatScheduler.load_from_config` used to overwrite, for every active agent whose
agents.yaml `heartbeat:` is an interval, the entry `load_all()` had built from the agent's
HEARTBEAT.md / HEARTBEAT.local.md — cron cadence and `checklist` both gone. All twelve
shipped agents with a HEARTBEAT.md also carry an interval in agents.yaml, so in production
every one of them ran as an empty interval job (`Agent.run_heartbeat` returns None without
a checklist). The same overwrite re-added, as an interval job, an agent whose file the
H506 injection scan had refused, so `start()` scheduled it anyway and `get_status()`
listed one agent under both `heartbeats` and `blocked`.

The refusal itself lives on `hermes/h506-read-side-scan` (`_parse_heartbeat` records the
verdict in `_blocked` and returns None); until it lands, `_refuse` below stands in for it
with the same contract, so these tests pin the composition either way.
"""
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agents.core.config import JarvisConfig  # noqa: E402
from agents.core.heartbeat import HeartbeatScheduler  # noqa: E402

CHECKLIST = ["Fetch weather for the home city", "Synthesize morning brief"]
HB = """---
agent: {agent}
cadence: {cadence}
enabled: true
checklist:
  - Fetch weather for the home city
  - Synthesize morning brief
---
# body
"""


@pytest.fixture(autouse=True)
def _no_user_home(monkeypatch):
    """A developer's Documents/Nerva overlay must not leak into the tmp agent tree."""
    monkeypatch.delenv("JARVIS_USER_HOME", raising=False)


class _Scheduler:
    """Records what `start()` / `start_heartbeat()` hand to APScheduler."""

    def __init__(self):
        self.jobs = []
        self.started = False
        self.running = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((trigger, kwargs))

    def start(self):
        self.started = True

    def ids(self):
        return [kw["id"] for _trigger, kw in self.jobs]


def _registry(**intervals):
    """The slice of JarvisConfig `load_from_config` reads, one active agent per keyword."""
    return SimpleNamespace(agents={
        agent_id: SimpleNamespace(status="active", has_heartbeat=interval != "no", heartbeat=interval)
        for agent_id, interval in intervals.items()
    })


def _write(tmp_path, agent, cadence="cron:30 6 * * *"):
    (tmp_path / agent).mkdir()
    (tmp_path / agent / "HEARTBEAT.md").write_text(HB.format(agent=agent, cadence=cadence), encoding="utf-8")


def _refuse(hb, agent_id):
    """The H506 verdict for one agent: the parser records the refusal and returns None."""
    real = hb._parse_heartbeat

    def parse(path):
        if path.parent.name == agent_id:
            hb._blocked[agent_id] = {
                "agent_id": agent_id, "path": str(path),
                "flags": ["you are now\\b"], "digest": "0" * 64,
            }
            return None
        return real(path)

    hb._parse_heartbeat = parse


# ─── Precedence ──────────────────────────────────────────────────────────────

def test_heartbeat_file_keeps_its_cadence_and_checklist_over_the_agents_yaml_interval(tmp_path):
    _write(tmp_path, "friday", "cron:30 6 * * *")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    hb.load_all()
    hb.load_from_config(_registry(friday="6h"))

    cfg = hb._heartbeat_configs["friday"]
    assert cfg["cadence"] == "cron:30 6 * * *"
    assert cfg["checklist"] == CHECKLIST
    assert "interval_seconds" not in cfg

    hb.scheduler = _Scheduler()
    hb.start(orchestrator=None)
    assert [(trigger, kw["id"]) for trigger, kw in hb.scheduler.jobs] == [("cron", "heartbeat-friday")]
    assert hb.scheduler.started


def test_agents_yaml_interval_fills_only_agents_without_a_heartbeat_file(tmp_path):
    _write(tmp_path, "friday")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    hb.load_all()
    hb.load_from_config(_registry(friday="6h", argus="6h", jerome="no"))

    assert hb._heartbeat_configs["friday"]["cadence"] == "cron:30 6 * * *"
    assert hb._heartbeat_configs["argus"] == {
        "agent": "argus", "cadence": "interval:21600", "interval_seconds": 21600,
    }
    assert "jerome" not in hb._heartbeat_configs

    hb.scheduler = _Scheduler()
    hb.start(orchestrator=None)
    assert sorted(hb.scheduler.ids()) == ["heartbeat-argus", "heartbeat-friday"]


def test_every_shipped_heartbeat_file_survives_the_shipped_registry(tmp_path):
    """The production pair: the repo's HEARTBEAT.md templates against the repo's agents.yaml.

    The templates are copied without any gitignored overlay so the assertion is about
    what ships, on any developer machine.
    """
    shipped = {}
    for template in sorted((REPO / "agents").glob("*/HEARTBEAT.md")):
        agent_id = template.parent.name
        (tmp_path / agent_id).mkdir()
        shutil.copyfile(template, tmp_path / agent_id / "HEARTBEAT.md")
        shipped[agent_id] = template
    assert "friday" in shipped and "jarvis" in shipped

    registry = JarvisConfig(str(REPO / "agents" / "_system" / "agents.yaml"))
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    hb.load_all()
    hb.load_from_config(registry)

    with_checklist = set()
    for agent_id, template in shipped.items():
        cfg = hb._heartbeat_configs[agent_id]
        # The entry is the template's front-matter, verbatim — the registry touched nothing.
        assert cfg == hb._parse_heartbeat(template), agent_id
        assert cfg["cadence"].startswith("cron:"), (agent_id, cfg["cadence"])
        assert "interval_seconds" not in cfg, agent_id
        if cfg.get("checklist"):
            with_checklist.add(agent_id)
    # Only some templates declare a machine-readable checklist (the rest keep theirs in
    # the prose body the parser discards); the ones that do must keep it.
    assert {"jarvis", "friday", "pepper"} <= with_checklist

    fallback_only = {
        agent_id for agent_id, agent in registry.agents.items()
        if agent.status == "active" and isinstance(agent.heartbeat, str)
        and agent.heartbeat != "no" and agent_id not in shipped
    }
    assert fallback_only, "the registry should still supply an interval to someone"
    for agent_id in fallback_only:
        assert hb._heartbeat_configs[agent_id]["cadence"].startswith("interval:"), agent_id


# ─── A refused file is scheduled from neither source ─────────────────────────

def test_a_refused_heartbeat_gets_no_interval_fallback_and_is_never_scheduled(tmp_path):
    _write(tmp_path, "friday")
    _write(tmp_path, "jarvis", "cron:0 7 * * *")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    _refuse(hb, "friday")
    hb.load_all()
    hb.load_from_config(_registry(friday="6h", jarvis="12h"))

    assert "friday" not in hb._heartbeat_configs
    assert "friday" in hb._blocked
    assert hb._heartbeat_configs["jarvis"]["cadence"] == "cron:0 7 * * *"

    hb.scheduler = _Scheduler()
    hb.start(orchestrator=None)
    assert hb.scheduler.ids() == ["heartbeat-jarvis"]

    hb.scheduler.running = True
    assert hb.start_heartbeat("friday", orchestrator=None) is False
    assert hb.scheduler.ids() == ["heartbeat-jarvis"]


def test_a_refused_heartbeat_stays_unscheduled_when_the_registry_loads_first(tmp_path):
    """The orchestrator loads the files first; the verdict must not depend on that."""
    _write(tmp_path, "friday")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    _refuse(hb, "friday")
    hb.load_from_config(_registry(friday="6h"))
    assert hb._heartbeat_configs["friday"]["cadence"] == "interval:21600"

    hb.load_all()
    assert "friday" not in hb._heartbeat_configs

    hb.scheduler = _Scheduler()
    hb.start(orchestrator=None)
    assert hb.scheduler.ids() == []


def test_the_scheduling_gate_holds_even_for_an_entry_injected_behind_the_loaders():
    hb = HeartbeatScheduler(agents_dir=os.devnull)
    hb._blocked["friday"] = {"agent_id": "friday", "path": "x", "flags": ["f"], "digest": "0" * 64}
    hb._heartbeat_configs["friday"] = {"agent": "friday", "cadence": "interval:21600", "interval_seconds": 21600}
    hb.scheduler = _Scheduler()
    hb.start(orchestrator=None)
    hb.scheduler.running = True
    assert hb.scheduler.ids() == []
    assert hb.start_heartbeat("friday", orchestrator=None) is False
    assert hb.scheduler.ids() == []


def test_status_without_a_scheduler_still_carries_the_verdict():
    hb = HeartbeatScheduler(agents_dir=os.devnull)
    assert hb.get_status() == {"scheduler_running": False, "heartbeats": [], "blocked": []}
    verdict = {"agent_id": "friday", "path": "x", "flags": ["f"], "digest": "0" * 64}
    hb._blocked["friday"] = verdict
    status = hb.get_status()
    assert status["blocked"] == [verdict]
    assert status["blocked"][0] is not verdict  # a copy, the verdict is not the caller's to edit


async def test_get_status_never_lists_an_agent_under_both_heartbeats_and_blocked(tmp_path):
    """Real APScheduler, the orchestrator's own load order, one refused and one clean agent."""
    _write(tmp_path, "friday")
    _write(tmp_path, "jarvis", "cron:0 7 * * *")
    hb = HeartbeatScheduler(agents_dir=str(tmp_path))
    _refuse(hb, "friday")
    hb.load_all()
    hb.load_from_config(_registry(friday="6h", jarvis="12h", argus="6h"))
    hb.scheduler = AsyncIOScheduler()
    try:
        hb.start(orchestrator=None)
        status = hb.get_status()
    finally:
        hb.stop()

    assert status["scheduler_running"] is True
    scheduled = {entry["agent_id"] for entry in status["heartbeats"]}
    blocked = {entry["agent_id"] for entry in status["blocked"]}
    assert scheduled == {"jarvis", "argus"}
    assert blocked == {"friday"}
    assert not scheduled & blocked
    assert status["blocked"][0]["flags"] == ["you are now\\b"]
