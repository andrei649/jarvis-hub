"""Tests for the Content skill (H2.10) — Veronica drafts.

Converted from the HTTP-router TDD stub to the loader pattern (skills/content/),
which is the architecture the orchestrator actually runs.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def _load(tmp_dir):
    path = repo_root / "skills" / "content" / "main.py"
    spec = importlib.util.spec_from_file_location("content_skill_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DRAFTS_DIR = tmp_dir            # isolate writes to a temp dir
    return mod


@pytest.fixture
def skill(tmp_path):
    return _load(tmp_path / "content_drafts")


async def test_create_draft_success(skill):
    out = await skill.draft("linkedin|Hello|World body")
    assert "linkedin" in out and "Hello" in out


async def test_draft_then_list(skill):
    await skill.draft("blog|Post One|body")
    await skill.draft("blog|Post Two|body")
    listing = await skill.list_drafts("blog")
    assert "Post One" in listing and "Post Two" in listing


async def test_list_empty_platform(skill):
    assert "Niciun draft" in await skill.list_drafts("twitter")


async def test_draft_bad_input(skill):
    assert "Folosire" in await skill.draft("linkedin")


def test_programmatic_save_and_get(skill):
    res = skill.save_draft("linkedin", "AI Trends", "text Content")
    assert res["status"] == "success" and res["draft_id"]
    rows = skill.get_drafts("linkedin")
    assert rows and rows[0]["title"] == "AI Trends"


async def test_handle_dispatch(skill):
    assert "necunoscută" in await skill.handle("bogus", "")
    assert "salvat" in await skill.handle("draft", "x|t|b")


def test_manifest_parses_via_loader():
    from agents.core.skills.loader import SkillLoader
    sl = SkillLoader()
    manifest = sl._parse_manifest(repo_root / "skills" / "content" / "SKILL.md")
    assert manifest["name"] == "Content"
    assert "veronica" in manifest["agents"]
    cmds = {c["command"] for c in manifest["commands"]}
    assert {"draft", "list_drafts"} <= cmds
