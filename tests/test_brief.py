"""Tests for the Brief skill (H2.3) — Friday morning consolidated dashboard.

Converted from the HTTP-router stub to the loader pattern (skills/brief/).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "brief" / "main.py"
    spec = importlib.util.spec_from_file_location("brief_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def skill():
    return _load()


class _OkWeather:
    async def get_weather(self, location=""):
        return "București: +20°C, Clear"


class _OkNews:
    async def get_headlines(self, category="general", limit=5):
        return [{"title": "Headline one"}, {"title": "Headline two"}]


async def test_generate_brief_success(skill, monkeypatch):
    monkeypatch.setattr(skill, "_weather", _OkWeather())
    monkeypatch.setattr(skill, "_news", _OkNews())
    data = await skill.generate_brief()
    assert "weather" in data and "news" in data and "market" in data
    assert data["degraded_mode"] is False
    assert len(data["news"]) == 2


async def test_degraded_flag_is_bool(skill, monkeypatch):
    monkeypatch.setattr(skill, "_weather", _OkWeather())
    monkeypatch.setattr(skill, "_news", _OkNews())
    data = await skill.generate_brief()
    assert isinstance(data["degraded_mode"], bool)


async def test_degraded_when_source_fails(skill, monkeypatch):
    class _BadNews:
        async def get_headlines(self, category="general", limit=5):
            raise ConnectionError("rss down")
    monkeypatch.setattr(skill, "_weather", _OkWeather())
    monkeypatch.setattr(skill, "_news", _BadNews())
    data = await skill.generate_brief()
    assert data["degraded_mode"] is True


async def test_brief_command_text(skill, monkeypatch):
    monkeypatch.setattr(skill, "_weather", _OkWeather())
    monkeypatch.setattr(skill, "_news", _OkNews())
    out = await skill.brief("")
    assert "Headline one" in out and "Vreme" in out


async def test_handle_dispatch(skill, monkeypatch):
    monkeypatch.setattr(skill, "_weather", _OkWeather())
    monkeypatch.setattr(skill, "_news", _OkNews())
    assert "necunoscută" in await skill.handle("bogus", "")
    assert "Brief" in await skill.handle("brief", "")


def test_manifest_parses_via_loader(skill):
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "brief" / "SKILL.md")
    assert manifest["name"] == "Brief"
    assert "friday" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert "brief" in cmds
