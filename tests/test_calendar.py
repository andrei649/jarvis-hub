"""Tests for the Calendar skill (H2.1) — Pepper Google Calendar management.

Converted from the HTTP-router stub to the loader pattern (skills/calendar/).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load():
    path = repo_root / "skills" / "calendar" / "main.py"
    spec = importlib.util.spec_from_file_location("calendar_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def skill():
    return _load()


class _FakeCal:
    access_token = "tok"

    async def get_today_events(self):
        return [{"start": "10:00", "summary": "Standup"},
                {"start": "14:00", "summary": "Review"}]

    async def create_event(self, summary, start, end):
        return {"id": "ev123", "summary": summary}


async def test_today_lists_events(skill, monkeypatch):
    monkeypatch.setattr(skill, "_plugin", _FakeCal())
    out = await skill.today()
    assert "Standup" in out and "Review" in out


async def test_add_event_creates(skill, monkeypatch):
    monkeypatch.setattr(skill, "_plugin", _FakeCal())
    out = await skill.add_event("Meeting|2026-06-01T10:00|2026-06-01T11:00")
    assert "Meeting" in out and "ev123" in out


async def test_missing_token_graceful(skill, monkeypatch):
    class _NoTok:
        access_token = ""
    monkeypatch.setattr(skill, "_plugin", _NoTok())
    msg = await skill.today()
    assert "credentials" in msg.lower()


async def test_add_event_bad_input(skill, monkeypatch):
    monkeypatch.setattr(skill, "_plugin", _FakeCal())
    assert "Folosire" in await skill.add_event("only title")


async def test_today_empty(skill, monkeypatch):
    class _Empty:
        access_token = "tok"
        async def get_today_events(self):
            return []
    monkeypatch.setattr(skill, "_plugin", _Empty())
    assert "Nimic" in await skill.today()


async def test_handle_dispatch(skill, monkeypatch):
    monkeypatch.setattr(skill, "_plugin", _FakeCal())
    assert "necunoscută" in await skill.handle("bogus", "")
    assert "Standup" in await skill.handle("today", "")


def test_manifest_parses_via_loader(skill):
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "calendar" / "SKILL.md")
    assert manifest["name"] == "Calendar"
    assert "pepper" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"today", "add_event"} <= cmds
