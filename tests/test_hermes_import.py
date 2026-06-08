"""
Tests for the SKILL.md-based skill importer (Hermes / agentskills.io) and the
loader's YAML-frontmatter parsing.

Regression coverage for the importer/loader fix: the real NousResearch/hermes-agent
repo lays skills out as skills/<category>/<skill>/SKILL.md with YAML frontmatter
(not a flat manifest.json), so the old importer 404'd on every skill and the
loader never read frontmatter. These tests run fully offline (httpx is mocked).
"""

import json

import pytest

from agents.core.skills.importer import SkillImporter
from agents.core.skills.loader import SkillLoader, _split_frontmatter

HERMES_SKILL_MD = """---
name: github-issues
description: "Create, triage, label, assign GitHub issues via gh or REST."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [GitHub, Issues, Triage]
    related_skills: [github-auth]
    requires_toolsets: [gh, git]
---
# GitHub Issues

Manage GitHub issues via the `gh` CLI or the REST API.

## Commands
- `issues <query>` — list and triage issues
"""


# ── loader frontmatter parsing ────────────────────────────────────

def test_split_frontmatter_parses_yaml():
    fm, body = _split_frontmatter(HERMES_SKILL_MD)
    assert fm is not None
    assert fm["name"] == "github-issues"
    assert body.lstrip().startswith("# GitHub Issues")


def test_split_frontmatter_none_for_heading_style():
    content = "# Brief\n\n> a heading-style skill\n\n**Version:** 0.1.0\n"
    fm, body = _split_frontmatter(content)
    assert fm is None
    assert body == content


def test_loader_parses_frontmatter_manifest(tmp_path):
    skill_dir = tmp_path / "github-issues"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(HERMES_SKILL_MD, encoding="utf-8")

    manifest = SkillLoader()._parse_manifest(skill_dir / "SKILL.md")
    assert manifest["name"] == "github-issues"
    assert manifest["version"] == "1.1.0"
    assert manifest["author"] == "Hermes Agent"
    assert manifest["license"] == "MIT"
    # requires_toolsets is surfaced as `requires`
    assert "gh" in manifest["requires"]
    # commands are parsed from the markdown body
    assert any(c["command"] == "issues" for c in manifest["commands"])


def test_loader_still_parses_heading_style(tmp_path):
    skill_dir = tmp_path / "brief"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# Brief\n\n> morning brief\n\n**Version:** 0.2.0\n**Author:** claude\n"
        "**Agents:** friday\n\n## Commands\n- `brief <input>` — generate the brief\n",
        encoding="utf-8",
    )
    manifest = SkillLoader()._parse_manifest(skill_dir / "SKILL.md")
    assert manifest["name"] == "Brief"
    assert manifest["version"] == "0.2.0"
    assert manifest["agents"] == ["friday"]
    assert manifest["commands"][0]["command"] == "brief"


# ── importer: mocked httpx GitHub ─────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code, *, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        return self._json


class _FakeClient:
    """Mimics the slice of httpx.AsyncClient the importer uses.

    Models the real nested layout: a flat SKILL.md 404s, the recursive git
    tree lists skills/github/github-issues/SKILL.md, and the raw fetch of that
    path returns the SKILL.md body.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if url.endswith("/git/trees/main?recursive=1"):
            return _FakeResponse(200, json_data={"tree": [
                {"type": "tree", "path": "skills/github"},
                {"type": "blob", "path": "skills/github/DESCRIPTION.md"},
                {"type": "blob", "path": "skills/github/github-issues/SKILL.md"},
            ]})
        if url.endswith("skills/github/github-issues/SKILL.md"):
            return _FakeResponse(200, text=HERMES_SKILL_MD)
        # flat SKILL.md and legacy manifest.* probes all miss
        return _FakeResponse(404)


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return httpx


@pytest.mark.asyncio
async def test_import_from_hermes_nested_skill(tmp_path, fake_httpx):
    importer = SkillImporter(skills_dir=str(tmp_path))
    ok = await importer.import_from_hermes("github-issues")
    assert ok is True

    saved = tmp_path / "github-issues"
    assert (saved / "SKILL.md").exists()
    # SKILL.md is saved verbatim so the loader can read it
    assert "name: github-issues" in (saved / "SKILL.md").read_text()

    # provenance sidecar drives list_imported()
    sidecar = json.loads((saved / "manifest.json").read_text())
    assert sidecar["source"] == "hermes"
    assert sidecar["imported"] is True
    assert sidecar["version"] == "1.1.0"


@pytest.mark.asyncio
async def test_imported_skill_is_loader_discoverable(tmp_path, fake_httpx, monkeypatch):
    importer = SkillImporter(skills_dir=str(tmp_path))
    assert await importer.import_from_hermes("github-issues") is True

    # Point the loader at the same dir and confirm it loads the imported skill.
    import agents.core.skills.loader as loader_mod
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path)
    loader = SkillLoader()
    skills = loader.discover()
    assert "github-issues" in skills
    assert skills["github-issues"].version == "1.1.0"


@pytest.mark.asyncio
async def test_list_imported_reports_imported_only(tmp_path, fake_httpx):
    importer = SkillImporter(skills_dir=str(tmp_path))
    # a non-imported local skill (SKILL.md only, no sidecar) must be excluded
    local = tmp_path / "brief"
    local.mkdir()
    (local / "SKILL.md").write_text("# Brief\n", encoding="utf-8")

    await importer.import_from_hermes("github-issues")
    names = [d["name"] for d in importer.list_imported()]
    assert "github-issues" in names
    assert "Brief" not in names and "brief" not in names


@pytest.mark.asyncio
async def test_import_missing_skill_returns_false(tmp_path, fake_httpx):
    importer = SkillImporter(skills_dir=str(tmp_path))
    assert await importer.import_from_hermes("does-not-exist") is False
