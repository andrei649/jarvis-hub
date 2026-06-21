"""SOUL/HEARTBEAT templating — the gitignored *.local.md overlay wins at load time.

The repo ships generic templates (SOUL.md / HEARTBEAT.md); the owner's
personalized copies live in SOUL.local.md / HEARTBEAT.local.md and must
override the template without any code or config change.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.agent import Agent
from agents.core.heartbeat import HeartbeatScheduler


def _make_agent_dir(tmp_path, agent_id, soul=None, local=None):
    d = tmp_path / "agents" / agent_id
    d.mkdir(parents=True)
    if soul is not None:
        (d / "SOUL.md").write_text(soul, encoding="utf-8")
    if local is not None:
        (d / "SOUL.local.md").write_text(local, encoding="utf-8")
    return d


def _load(agent_id):
    a = Agent.__new__(Agent)
    a.id = agent_id
    a.soul = {}
    a._load_soul()
    return a


def test_soul_local_overrides_template(tmp_path, monkeypatch):
    _make_agent_dir(tmp_path, "foo", soul="# Generic template", local="# Personalized soul")
    monkeypatch.chdir(tmp_path)
    a = _load("foo")
    assert a.soul["content"] == "# Personalized soul"
    assert a.soul["path"].name == "SOUL.local.md"


def test_soul_falls_back_to_template(tmp_path, monkeypatch):
    _make_agent_dir(tmp_path, "bar", soul="# Generic template")
    monkeypatch.chdir(tmp_path)
    a = _load("bar")
    assert a.soul["content"] == "# Generic template"
    assert a.soul["path"].name == "SOUL.md"


HB = """---
agent: {agent}
cadence: cron:30 6 * * *
enabled: true
checklist:
  - {item}
---
# beat
"""


def test_heartbeat_local_overrides_template(tmp_path):
    d = tmp_path / "agents" / "baz"
    d.mkdir(parents=True)
    (d / "HEARTBEAT.md").write_text(HB.format(agent="baz", item="generic step"), encoding="utf-8")
    (d / "HEARTBEAT.local.md").write_text(HB.format(agent="baz", item="personal step"), encoding="utf-8")
    sched = HeartbeatScheduler(agents_dir=str(tmp_path / "agents"))
    sched.load_all()
    cfg = sched._heartbeat_configs["baz"]
    assert "personal step" in str(cfg)


def test_heartbeat_falls_back_to_template(tmp_path):
    d = tmp_path / "agents" / "qux"
    d.mkdir(parents=True)
    (d / "HEARTBEAT.md").write_text(HB.format(agent="qux", item="generic step"), encoding="utf-8")
    sched = HeartbeatScheduler(agents_dir=str(tmp_path / "agents"))
    sched.load_all()
    assert "generic step" in str(sched._heartbeat_configs["qux"])


async def test_soul_endpoint_rejects_path_traversal():
    """The soul endpoint turns agent_id into a path segment — ids outside the
    agent alphabet (dots, slashes, traversal) must 404 before touching disk."""
    import pytest
    from fastapi import HTTPException
    from agents.core.routers.agents_api import get_agent_soul  # extracted from web.py (CLN-3)

    for bad in ("..", "../jarvis", "a/../../etc", "jarvis%2f..", ".hidden", "x" * 65):
        with pytest.raises(HTTPException) as exc:
            await get_agent_soul(bad)
        assert exc.value.status_code == 404
