"""Tests for the Health skill (H2.4) — Hercules telemetry analysis.

Converted from the HTTP-router stub to the loader pattern (skills/health/).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "health" / "main.py"
    spec = importlib.util.spec_from_file_location("health_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def skill():
    return _load()


def test_process_metrics_contract(skill):
    payload = {"metric_type": "heart_rate", "values": [72, 75, 80, 110, 68], "unit": "count/min"}
    res = skill.process_metrics(payload)
    assert res["status"] == "processed"
    a = res["analysis"]
    assert a["max"] == 110 and a["min"] == 68
    assert abs(a["mean"] - 81.0) < 0.01


def test_analyze_values_trend(skill):
    assert skill.analyze_values([1, 2, 3, 8, 9])["trend"] == "up"
    assert skill.analyze_values([9, 8, 3, 2, 1])["trend"] == "down"
    assert skill.analyze_values([])["n"] == 0


async def test_analyze_command(skill):
    out = await skill.analyze("72, 75, 80, 110, 68")
    assert "medie 81.0" in out and "max 110" in out


async def test_analyze_bad_input(skill):
    assert "Folosire" in await skill.analyze("")


async def test_summary_bridge_down_graceful(skill, monkeypatch):
    class _Down:
        async def get_summary(self, days=1):
            raise ConnectionError("no bridge")
    monkeypatch.setattr(skill, "_plugin", _Down())
    msg = await skill.summary("7")
    assert "nu răspunde" in msg.lower()


async def test_summary_ok(skill, monkeypatch):
    class _Ok:
        async def get_summary(self, days=1):
            return {"sleep_hours": 7.5, "resting_hr": 54}
    monkeypatch.setattr(skill, "_plugin", _Ok())
    out = await skill.summary("1")
    assert "sleep_hours" in out and "7.5" in out


async def test_handle_dispatch(skill):
    assert "necunoscută" in await skill.handle("bogus", "")
    assert "valori" in await skill.handle("analyze", "1,2,3")


def test_manifest_parses_via_loader(skill):
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "health" / "SKILL.md")
    assert manifest["name"] == "Health"
    assert "hercules" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"analyze", "summary"} <= cmds
