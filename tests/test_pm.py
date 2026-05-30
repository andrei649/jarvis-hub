"""Tests for the PM skill (H2.7) — Hephaestus project tracker (SQLite).

Converted from the HTTP-router stub to the loader pattern (skills/pm/), which
is the architecture the orchestrator actually runs.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load(tmp_db):
    path = repo_root / "skills" / "pm" / "main.py"
    spec = importlib.util.spec_from_file_location("pm_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = tmp_db                # isolate to a temp DB
    return mod


@pytest.fixture
def skill(tmp_path):
    return _load(tmp_path / "pm.db")


def test_create_and_get_tasks(skill):
    res = skill.create_task("cosmina", "Pour foundation")
    assert res["status"] == "success" and res["id"] == 1
    rows = skill.get_tasks("cosmina")
    assert len(rows) == 1 and rows[0]["title"] == "Pour foundation"
    assert rows[0]["status"] == "todo"          # default


def test_create_task_returns_incrementing_ids(skill):
    a = skill.create_task("bmw", "Order N54 parts")
    b = skill.create_task("bmw", "Book service")
    assert b["id"] == a["id"] + 1


def test_update_status(skill):
    tid = skill.create_task("cosmina", "Roof")["id"]
    assert skill.update_status(tid, "doing") is True
    assert skill.get_tasks("cosmina")[0]["status"] == "doing"
    assert skill.update_status(999, "done") is False


async def test_add_task_command(skill):
    out = await skill.add_task("cosmina|Wiring")
    assert "#1" in out and "cosmina" in out


async def test_list_and_set_status_commands(skill):
    await skill.add_task("bmw|Brakes")
    assert "Brakes" in await skill.list_tasks("bmw")
    assert "doing" in await skill.set_status("1|doing")
    assert "invalid" in (await skill.set_status("1|bogus")).lower()


async def test_add_task_bad_input(skill):
    assert "Folosire" in await skill.add_task("only-project")


async def test_handle_dispatch(skill):
    assert "necunoscută" in await skill.handle("bogus", "")
    assert "adăugat" in await skill.handle("add_task", "x|y")


def test_manifest_parses_via_loader():
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "pm" / "SKILL.md")
    assert manifest["name"] == "PM"
    assert "hephaestus" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"add_task", "list_tasks", "set_status"} <= cmds
