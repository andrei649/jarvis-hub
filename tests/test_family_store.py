"""Tests for the family_store skill (H2.8) — local SQLite, no network."""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load_skill_module(tmp_db):
    """Import skills/family_store/main.py fresh, pointed at a temp DB."""
    path = repo_root / "skills" / "family_store" / "main.py"
    spec = importlib.util.spec_from_file_location("family_store_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = tmp_db
    return mod


@pytest.fixture
def skill(tmp_path):
    return _load_skill_module(tmp_path / "family.db")


async def test_log_then_get_sleep(skill):
    out = await skill.log_sleep("max 9")
    assert "9" in out and "Max" in out
    res = await skill.get_sleep("max")
    assert "Max" in res and "9" in res


async def test_get_sleep_averages_recent(skill):
    for h in (8, 9, 7):
        await skill.log_sleep(f"max {h}")
    res = await skill.get_sleep("max")
    # average of 8,9,7 = 8.0
    assert "8.0" in res


async def test_get_sleep_unknown_person(skill):
    assert "Nu am date" in await skill.get_sleep("alexandra")


async def test_log_sleep_bad_input(skill):
    assert "Folosire" in await skill.log_sleep("max")
    assert "înțeles" in await skill.log_sleep("max abc")


async def test_handle_dispatch(skill):
    assert "necunoscută" in await skill.handle("bogus", "")
    await skill.handle("log_sleep", "max 6")
    assert "Max" in await skill.handle("get_sleep", "max")


def test_manifest_parses_via_loader():
    """The SKILL.md must be discoverable by the real SkillLoader parser."""
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    md = repo_root / "skills" / "family_store" / "SKILL.md"
    manifest = sl._parse_manifest(md)
    assert manifest["name"] == "Family Store"
    assert "frigga" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"log_sleep", "get_sleep"} <= cmds
