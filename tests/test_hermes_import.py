"""
Tests for the SKILL.md-based skill importer (Hermes / agentskills.io) and the
loader's YAML-frontmatter parsing.

Regression coverage for the importer/loader fix: the real NousResearch/hermes-agent
repo lays skills out as skills/<category>/<skill>/SKILL.md with YAML frontmatter
(not a flat manifest.json), so the old importer 404'd on every skill and the
loader never read frontmatter. These tests run fully offline (httpx is mocked).
"""

import ast
import copy
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.core.skills.importer as importer_mod
from agents.core.skills.importer import SkillImporter, SkillImportError
from agents.core.skills.loader import SkillLoader, _split_frontmatter
from agents.core.skills.remote_pin import (
    RemoteImportAuthorization,
    RemoteImportRefused,
    RemoteSkillPin,
)

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

PIN_REPOSITORY = "NousResearch/hermes-agent"
PIN_RELEASE_TAG = "v2026.8.31"
PIN_COMMIT = "29112bef099274229cadff79cdff7bf7b99c4b77"
PIN_TREE = "daaffc303ae437041b7f76be17c5f61b14f2ce99"
PIN_PATH = "skills/github/github-issues/SKILL.md"
PIN_FILE_SHA256 = "4dc8036b0e3ca395b1ae009e67d601c933921671059dae7a325cd7716518929a"
# Owner decision 2026-09-01: the four productivity subtrees carrying separate Anthropic terms are
# NOT accepted, so the shipped allowlist must not let the importer fetch them (82 -> 78 skills).
EXCLUDED_HERMES_SUBTREES = (
    "skills/productivity/docx/",
    "skills/productivity/pdf/",
    "skills/productivity/powerpoint/",
    "skills/productivity/xlsx/",
)
HERMES_SKILL_BYTES = HERMES_SKILL_MD.encode("utf-8")

PDF_SKILL_MD = """---
name: pdf
description: Read PDF files.
version: 1.0.0
---
# PDF
"""
PDF_SKILL_BYTES = PDF_SKILL_MD.encode("utf-8")


class _FakeResponse:
    def __init__(self, status_code, *, content=b"", json_data=None, url=None):
        self.status_code = status_code
        self.content = content
        self._json = json_data
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return self._json

    async def aiter_bytes(self):
        yield self.content


class _FakeClient:
    """Mimics the slice of httpx.AsyncClient the importer uses."""

    responses = {}
    requests = []

    def __init__(self, *args, **kwargs):
        self.options = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        type(self).requests.append(url)
        response = type(self).responses.get(url)
        if isinstance(response, Exception):
            raise response
        if response is None:
            return _FakeResponse(404, url=url)
        if response.url is None:
            response.url = url
        return response

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        assert method == "GET"
        assert kwargs.get("follow_redirects") is False
        yield await self.get(url)


def _authorization(install_gate=None, egress_gate=None):
    return RemoteImportAuthorization(
        install_gate=install_gate or (lambda _payload: "grant"),
        egress_gate=egress_gate or (lambda *_: None),
    )


@pytest.fixture
def httpx_harness(monkeypatch):
    _FakeClient.responses = {}
    _FakeClient.requests = []
    monkeypatch.setattr(SkillImporter, "_remote_client", lambda self, _authorization: _FakeClient())
    return _FakeClient


def _pin_entry(
    *,
    slug="github-issues",
    path=PIN_PATH,
    content=HERMES_SKILL_BYTES,
):
    return {
        "slug": slug,
        "path": path,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "tier": "optional" if path.startswith("optional-skills/") else "bundled",
    }


def _pin_record(*entries):
    return {
        "schema_version": 2,
        "repository": PIN_REPOSITORY,
        "release_tag": PIN_RELEASE_TAG,
        "commit": PIN_COMMIT,
        "tree": PIN_TREE,
        "skills": list(entries or (_pin_entry(),)),
    }


def _configure_pin(monkeypatch, tmp_path, record):
    pin_path = tmp_path / "hermes-pin.json"
    pin_path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(importer_mod, "HERMES_PIN_PATH", pin_path, raising=False)
    return pin_path


def _raw_url(entry, *, commit=PIN_COMMIT):
    return f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{commit}/{entry['path']}"


def _tree_snapshot(root):
    if not root.exists():
        return []
    snapshot = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snapshot.append((rel, None if path.is_dir() else path.read_bytes()))
    return snapshot


@pytest.fixture
def pinned_hermes(monkeypatch, tmp_path, httpx_harness):
    entry = _pin_entry()
    _configure_pin(monkeypatch, tmp_path, _pin_record(entry))
    url = _raw_url(entry)
    httpx_harness.responses[url] = _FakeResponse(200, content=HERMES_SKILL_BYTES, url=url)
    return httpx_harness


def test_repository_hermes_pin_is_exact_release_inventory():
    pin = importer_mod._load_hermes_pin()

    assert pin.repository == PIN_REPOSITORY
    assert pin.release_tag == PIN_RELEASE_TAG
    assert pin.commit == PIN_COMMIT
    assert pin.tree == PIN_TREE
    assert len(pin.skills) == 190
    slugs = {entry.slug for entry in pin.skills}
    assert {"github", "grill-me"} <= slugs
    assert slugs.isdisjoint({"github-auth", "github-code-review", "github-issue-to-pr",
                             "github-issues", "github-pr-workflow", "github-repo-management",
                             "plan", "session-librarian", "blogwatcher"})
    assert next(e for e in pin.skills if e.slug == "grill-me").tier == "optional"
    assert len(next(e for e in pin.skills if e.slug == "github").files) == 10
    assert len([RemoteSkillPin(pin.repository, pin.commit, entry.path,
                               entry.content_sha256, entry.files)
                for entry in pin.skills]) == 190
    assert hashlib.sha256(importer_mod.HERMES_PIN_PATH.read_bytes()).hexdigest() == PIN_FILE_SHA256


def test_repository_hermes_pin_excludes_the_anthropic_terms_subtrees():
    pin = importer_mod._load_hermes_pin()

    for entry in pin.skills:
        assert not entry.path.startswith(EXCLUDED_HERMES_SUBTREES), entry.path
    assert {entry.slug for entry in pin.skills}.isdisjoint({"docx", "pdf", "powerpoint", "xlsx"})
    # the rest of the productivity category is untouched
    assert any(entry.path.startswith("skills/productivity/") for entry in pin.skills)


def test_nerva_ships_small_default_and_installable_optional_skill_roots():
    root = Path(__file__).resolve().parents[1]
    bundled = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}
    optional = {path.parent.name for path in (root / "optional-skills").glob("*/SKILL.md")}
    assert bundled == {"brief", "pm", "security_monitor", "system_monitor", "weather"}
    assert optional == {"calendar", "content", "email_triage", "family_store", "health",
                        "spotify", "web_research"}


def test_frozen_package_carries_optional_catalog_and_v2_pin():
    root = Path(__file__).resolve().parents[1]
    spec = ast.parse((root / "packaging/nerva.spec").read_text(encoding="utf-8"))
    datas = next(node.value for node in spec.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "datas"
                         for target in node.targets))
    optional_loop = next(node for node in spec.body if isinstance(node, ast.For)
                         and isinstance(node.target, ast.Name) and node.target.id == "skill_name")
    packaged_names = {elt.value for elt in optional_loop.iter.elts}
    actual_names = {path.name for path in (root / "optional-skills").iterdir() if path.is_dir()}
    assert packaged_names == actual_names
    assert "'optional-skills'" in ast.unparse(optional_loop)
    for name in packaged_names:
        assert (root / "optional-skills" / name / "SKILL.md").is_file()
        assert (root / "optional-skills" / name / "main.py").is_file()
    assert (root / "agents/core/skills/hermes_pin_v2.json").is_file()
    assert any("hermes_pin_v2.json" in ast.unparse(elt) for elt in datas.elts)


@pytest.mark.asyncio
async def test_import_from_hermes_uses_exact_pin_and_records_provenance(tmp_path, pinned_hermes):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    ok = await importer.import_from_hermes("github-issues", authorization=_authorization())
    assert ok is True

    expected_url = _raw_url(_pin_entry())
    assert pinned_hermes.requests == [expected_url]
    assert "/main/" not in expected_url
    assert f"/{PIN_RELEASE_TAG}/" not in expected_url

    saved = skills_dir / "github-issues"
    assert (saved / "SKILL.md").exists()
    assert (saved / "SKILL.md").read_bytes() == HERMES_SKILL_BYTES

    sidecar = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
    assert sidecar["source"] == "hermes"
    assert sidecar["imported"] is True
    assert sidecar["version"] == "1.1.0"
    assert sidecar["source_repository"] == PIN_REPOSITORY
    assert sidecar["source_release_tag"] == PIN_RELEASE_TAG
    assert sidecar["source_commit"] == PIN_COMMIT
    assert sidecar["source_tree"] == PIN_TREE
    assert sidecar["source_path"] == PIN_PATH
    assert sidecar["content_sha256"] == hashlib.sha256(HERMES_SKILL_BYTES).hexdigest()


@pytest.mark.asyncio
async def test_imported_skill_is_loader_discoverable(tmp_path, pinned_hermes, monkeypatch):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    assert await importer.import_from_hermes("github-issues", authorization=_authorization()) is True

    import agents.core.skills.loader as loader_mod

    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_dir)
    loader = SkillLoader()
    skills = loader.discover()
    assert "github-issues" in skills
    assert skills["github-issues"].version == "1.1.0"
    assert (skills_dir / "github-issues/PENDING_REVIEW").exists()
    assert skills["github-issues"].sandboxed is True
    assert loader.pending_skill_detail("github-issues") is not None


@pytest.mark.asyncio
async def test_list_imported_reports_imported_only(tmp_path, pinned_hermes):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    local = skills_dir / "brief"
    local.mkdir()
    (local / "SKILL.md").write_text("# Brief\n", encoding="utf-8")

    await importer.import_from_hermes("github-issues", authorization=_authorization())
    names = [d["name"] for d in importer.list_imported()]
    assert "github-issues" in names
    assert "Brief" not in names and "brief" not in names


@pytest.mark.asyncio
async def test_unpinned_hermes_skill_returns_false_without_network_or_mutation(
    tmp_path, pinned_hermes
):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    before = _tree_snapshot(skills_dir)

    assert await importer.import_from_hermes("does-not-exist", authorization=_authorization()) is False
    assert pinned_hermes.requests == []
    assert _tree_snapshot(skills_dir) == before


def _invalid_pin_cases():
    cases = []

    record = _pin_record()
    record["unexpected"] = True
    cases.append(("unknown top-level field", record))

    record = _pin_record()
    del record["tree"]
    cases.append(("missing top-level field", record))

    record = _pin_record()
    record["schema_version"] = True
    cases.append(("boolean schema version", record))

    record = _pin_record()
    record["schema_version"] = 1
    cases.append(("unsupported schema version", record))

    record = _pin_record()
    record["repository"] = "attacker/hermes-agent"
    cases.append(("repository substitution", record))

    record = _pin_record()
    record["release_tag"] = "main"
    cases.append(("mutable release ref", record))

    record = _pin_record()
    record["release_tag"] = "v2026.8.4"
    cases.append(("release tag substitution", record))

    record = _pin_record()
    record["commit"] = "1" * 40
    cases.append(("commit substitution", record))

    record = _pin_record()
    record["tree"] = "2" * 40
    cases.append(("tree substitution", record))

    record = _pin_record()
    record["commit"] = "A" * 40
    cases.append(("non-canonical commit", record))

    record = _pin_record()
    record["tree"] = "1" * 39
    cases.append(("malformed tree", record))

    record = _pin_record()
    record["skills"] = []
    cases.append(("empty allowlist", record))

    record = _pin_record()
    record["skills"][0]["unexpected"] = True
    cases.append(("unknown entry field", record))

    record = _pin_record()
    record["skills"].append(_pin_entry(path="skills/other/github-issues/SKILL.md"))
    cases.append(("duplicate slug", record))

    record = _pin_record()
    record["skills"].append(copy.deepcopy(record["skills"][0]))
    cases.append(("duplicate path", record))

    record = _pin_record(
        _pin_entry(
            slug="pdf",
            path="skills/productivity/pdf/SKILL.md",
            content=PDF_SKILL_BYTES,
        ),
        _pin_entry(),
    )
    cases.append(("non-deterministic entry order", record))

    record = _pin_record()
    record["skills"][0]["slug"] = "../github-issues"
    cases.append(("unsafe slug", record))

    record = _pin_record()
    record["skills"][0]["path"] = "skills/github/../github-issues/SKILL.md"
    cases.append(("path traversal", record))

    record = _pin_record()
    record["skills"][0]["path"] = "skills/github/other/SKILL.md"
    cases.append(("slug path drift", record))

    record = _pin_record()
    record["skills"][0]["content_sha256"] = "not-a-digest"
    cases.append(("malformed digest", record))

    record = _pin_record()
    record["skills"][0]["tier"] = "optional"
    cases.append(("tier root mismatch", record))

    record = _pin_record()
    record["skills"][0]["files"] = [{"path": "skills/github/github-issues/references/../auth.md",
                                      "content_sha256": "0" * 64}]
    cases.append(("unsafe reference traversal", record))

    record = _pin_record()
    ref = {"path": "skills/github/github-issues/references/auth.md", "content_sha256": "0" * 64}
    record["skills"][0]["files"] = [ref, ref]
    cases.append(("duplicate reference path", record))

    return cases


_INVALID_PIN_CASES = _invalid_pin_cases()


@pytest.mark.parametrize(
    "case,record",
    _INVALID_PIN_CASES,
    ids=[case for case, _ in _INVALID_PIN_CASES],
)
@pytest.mark.asyncio
async def test_malformed_hermes_pin_fails_before_network_or_mutation(
    case, record, tmp_path, monkeypatch, httpx_harness
):
    del case
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    sentinel = skills_dir / "keep.txt"
    sentinel.write_bytes(b"unchanged")
    before = _tree_snapshot(skills_dir)
    _configure_pin(monkeypatch, tmp_path, record)

    with pytest.raises(SkillImportError):
        await importer.import_from_hermes("github-issues", authorization=_authorization())

    assert httpx_harness.requests == []
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.parametrize(
    "failure",
    [
        "tampered-bytes",
        "invalid-utf8",
        "content-slug",
        "unavailable",
        "network-error",
        "redirect",
    ],
)
@pytest.mark.asyncio
async def test_hermes_integrity_failure_preserves_existing_target(
    failure, tmp_path, monkeypatch, httpx_harness
):
    if failure == "invalid-utf8":
        content = b"\xff\xfe"
    elif failure == "content-slug":
        content = HERMES_SKILL_BYTES.replace(b"name: github-issues", b"name: other-skill")
    else:
        content = HERMES_SKILL_BYTES
    entry = _pin_entry(content=content)
    _configure_pin(monkeypatch, tmp_path, _pin_record(entry))
    expected_url = _raw_url(entry)

    if failure == "tampered-bytes":
        response = _FakeResponse(
            200,
            content=HERMES_SKILL_BYTES + b"tampered",
            url=expected_url,
        )
    elif failure == "unavailable":
        response = _FakeResponse(404, url=expected_url)
    elif failure == "network-error":
        response = OSError("offline")
    elif failure == "redirect":
        response = _FakeResponse(
            302, url=expected_url,
        )
    else:
        response = _FakeResponse(200, content=content, url=expected_url)
    httpx_harness.responses[expected_url] = response

    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    target = skills_dir / "github-issues"
    target.mkdir()
    (target / "SKILL.md").write_bytes(b"old-content")
    (target / "manifest.json").write_bytes(b'{"old": true}')
    before = _tree_snapshot(skills_dir)

    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_hermes("github-issues", authorization=_authorization())
    assert caught.value.code == {
        "tampered-bytes": "digest_mismatch",
        "invalid-utf8": "invalid_skill",
        "content-slug": "source_identity_mismatch",
        "unavailable": "fetch_failed",
        "network-error": "fetch_failed",
        "redirect": "source_identity_mismatch",
    }[failure]
    assert httpx_harness.requests == [expected_url]
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.asyncio
async def test_save_rejects_verified_byte_text_mismatch_before_target_mutation(tmp_path):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    before = _tree_snapshot(skills_dir)

    assert (
        await importer._save_skill(
            "github-issues",
            "hermes",
            skill_md_text=HERMES_SKILL_MD.replace("github-issues", "other-skill"),
            skill_md_bytes=HERMES_SKILL_BYTES,
            provenance={"content_sha256": hashlib.sha256(HERMES_SKILL_BYTES).hexdigest()},
        )
        is False
    )
    assert _tree_snapshot(skills_dir) == before


def _two_skill_pin():
    return _pin_record(
        _pin_entry(),
        _pin_entry(
            slug="pdf",
            path="skills/productivity/pdf/SKILL.md",
            content=PDF_SKILL_BYTES,
        ),
    )


def _configure_two_skill_responses(httpx_harness):
    entries = _two_skill_pin()["skills"]
    contents = [HERMES_SKILL_BYTES, PDF_SKILL_BYTES]
    for entry, content in zip(entries, contents, strict=True):
        url = _raw_url(entry)
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    return entries


@pytest.mark.asyncio
async def test_hermes_bulk_sync_iterates_allowlist_without_github_tree(
    tmp_path, monkeypatch, httpx_harness
):
    record = _two_skill_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entries = _configure_two_skill_responses(httpx_harness)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))

    imported = await importer.sync_source("hermes", authorization=_authorization())

    assert imported == ["github-issues", "pdf"]
    assert httpx_harness.requests == [_raw_url(entry) for entry in entries]
    assert all("/git/trees/" not in url for url in httpx_harness.requests)
    assert (skills_dir / "github-issues" / "SKILL.md").read_bytes() == HERMES_SKILL_BYTES
    assert (skills_dir / "pdf" / "SKILL.md").read_bytes() == PDF_SKILL_BYTES


@pytest.mark.asyncio
async def test_hermes_category_sync_filters_pinned_paths_without_tree_listing(
    tmp_path, monkeypatch, httpx_harness
):
    record = _two_skill_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entries = _configure_two_skill_responses(httpx_harness)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))

    imported = await importer.sync_source("hermes", category="productivity",
                                          authorization=_authorization())

    assert imported == ["pdf"]
    assert httpx_harness.requests == [_raw_url(entries[1])]
    assert not (skills_dir / "github-issues").exists()
    assert (skills_dir / "pdf").is_dir()


@pytest.mark.parametrize("category", ["../github", "/github", "github\\other", ""])
@pytest.mark.asyncio
async def test_hermes_sync_rejects_unsafe_category_without_network_or_mutation(
    category, tmp_path, monkeypatch, httpx_harness
):
    _configure_pin(monkeypatch, tmp_path, _two_skill_pin())
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    before = _tree_snapshot(skills_dir)

    assert await importer.sync_source("hermes", category=category,
                                      authorization=_authorization()) == []
    assert httpx_harness.requests == []
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.asyncio
async def test_hermes_bulk_verifies_every_selected_skill_before_any_write(
    tmp_path, monkeypatch, httpx_harness
):
    record = _two_skill_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entries = record["skills"]
    first_url = _raw_url(entries[0])
    second_url = _raw_url(entries[1])
    httpx_harness.responses[first_url] = _FakeResponse(
        200, content=HERMES_SKILL_BYTES, url=first_url
    )
    httpx_harness.responses[second_url] = _FakeResponse(
        200, content=PDF_SKILL_BYTES + b"tampered", url=second_url
    )
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    before = _tree_snapshot(skills_dir)

    with pytest.raises(RemoteImportRefused) as caught:
        await importer.sync_source("hermes", authorization=_authorization())
    assert caught.value.code == "digest_mismatch"
    assert httpx_harness.requests == [first_url, second_url]
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.asyncio
async def test_hermes_bulk_validates_complete_pin_before_any_fetch_or_write(
    tmp_path, monkeypatch, httpx_harness
):
    record = _two_skill_pin()
    record["skills"][1]["content_sha256"] = "broken"
    _configure_pin(monkeypatch, tmp_path, record)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    before = _tree_snapshot(skills_dir)

    with pytest.raises(SkillImportError):
        await importer.sync_source("hermes", authorization=_authorization())

    assert httpx_harness.requests == []
    assert _tree_snapshot(skills_dir) == before


# H696: a complete skill is a digest-verified directory, including its references.
GITHUB_REFERENCE = b"# GitHub authentication\nUse a token scoped to this task.\n"


def _v2_github_pin(*, reference_digest=None, reference_path=None, tier="bundled"):
    record = _pin_record(_pin_entry(slug="github", path="skills/software-development/github/SKILL.md",
                                     content=HERMES_SKILL_BYTES.replace(b"github-issues", b"github")))
    record["schema_version"] = 2
    record["skills"][0]["tier"] = tier
    record["skills"][0]["files"] = [{
        "path": reference_path or "skills/software-development/github/references/auth.md",
        "content_sha256": reference_digest or hashlib.sha256(GITHUB_REFERENCE).hexdigest(),
    }]
    return record


@pytest.mark.asyncio
async def test_hermes_v2_import_writes_verified_reference_and_tier(
    tmp_path, monkeypatch, httpx_harness
):
    record = _v2_github_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entry = record["skills"][0]
    skill_bytes = HERMES_SKILL_BYTES.replace(b"github-issues", b"github")
    for path, content in [(entry["path"], skill_bytes),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    skills_dir = tmp_path / "installed"
    assert await SkillImporter(str(skills_dir)).import_from_hermes(
        "github", authorization=_authorization()) is True
    assert (skills_dir / "github/references/auth.md").read_bytes() == GITHUB_REFERENCE
    manifest = json.loads((skills_dir / "github/manifest.json").read_text())
    assert manifest["source_tier"] == "bundled"
    assert manifest["source_files"] == entry["files"]


@pytest.mark.asyncio
async def test_hermes_reference_digest_failure_has_no_partial_write(
    tmp_path, monkeypatch, httpx_harness
):
    record = _v2_github_pin(reference_digest="0" * 64)
    _configure_pin(monkeypatch, tmp_path, record)
    entry = record["skills"][0]
    for path, content in [(entry["path"], HERMES_SKILL_BYTES.replace(b"github-issues", b"github")),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(str(skills_dir))
    before = _tree_snapshot(skills_dir)
    with pytest.raises(RemoteImportRefused) as caught:
        await importer.import_from_hermes("github", authorization=_authorization())
    assert caught.value.code == "digest_mismatch"
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.parametrize("path", [
    "skills/software-development/github/../escape.md",
    "skills/software-development/github/references/../../escape.md",
    "skills/software-development/other/references/auth.md",
    "skills/software-development/github/references/auth.md?raw=1",
    "skills/software-development/github/SKILL.md",
])
@pytest.mark.asyncio
async def test_hermes_v2_unsafe_reference_fails_before_network(
    path, tmp_path, monkeypatch, httpx_harness
):
    _configure_pin(monkeypatch, tmp_path, _v2_github_pin(reference_path=path))
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(str(skills_dir))
    before = _tree_snapshot(skills_dir)
    with pytest.raises(SkillImportError):
        await importer.import_from_hermes("github", authorization=_authorization())
    assert httpx_harness.requests == []
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.asyncio
async def test_hermes_v2_optional_root_is_accepted(tmp_path, monkeypatch, httpx_harness):
    record = _v2_github_pin(tier="optional")
    record["skills"][0]["path"] = "optional-skills/software-development/github/SKILL.md"
    record["skills"][0]["files"][0]["path"] = (
        "optional-skills/software-development/github/references/auth.md"
    )
    _configure_pin(monkeypatch, tmp_path, record)
    entry = record["skills"][0]
    for path, content in [(entry["path"], HERMES_SKILL_BYTES.replace(b"github-issues", b"github")),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    assert await SkillImporter(str(tmp_path / "installed")).import_from_hermes(
        "github", authorization=_authorization())


@pytest.mark.asyncio
async def test_hermes_category_sync_includes_optional_root(tmp_path, monkeypatch, httpx_harness):
    record = _v2_github_pin(tier="optional")
    entry = record["skills"][0]
    entry["path"] = "optional-skills/software-development/github/SKILL.md"
    entry["files"][0]["path"] = "optional-skills/software-development/github/references/auth.md"
    _configure_pin(monkeypatch, tmp_path, record)
    for path, content in [(entry["path"], HERMES_SKILL_BYTES.replace(b"github-issues", b"github")),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    importer = SkillImporter(str(tmp_path / "installed"))
    assert await importer.sync_source("hermes", category="software-development",
                                      authorization=_authorization()) == ["github"]


@pytest.mark.asyncio
async def test_hermes_import_refuses_existing_owner_copy_and_link(tmp_path, monkeypatch, httpx_harness):
    record = _v2_github_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entry = record["skills"][0]
    for path, content in [(entry["path"], HERMES_SKILL_BYTES.replace(b"github-issues", b"github")),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(str(skills_dir))
    owner = skills_dir / "github"
    owner.mkdir()
    (owner / "SKILL.md").write_bytes(b"owner copy")
    before = _tree_snapshot(skills_dir)
    assert await importer.import_from_hermes("github", authorization=_authorization()) is False
    assert _tree_snapshot(skills_dir) == before
    __import__("shutil").rmtree(owner)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"safe")
    owner.symlink_to(outside, target_is_directory=True)
    assert await importer.import_from_hermes("github", authorization=_authorization()) is False
    assert (outside / "sentinel").read_bytes() == b"safe"


@pytest.mark.asyncio
async def test_repo_optional_install_is_snapshot_bound_and_quarantined(tmp_path, monkeypatch):
    source = tmp_path / "optional" / "calendar"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Calendar\n\n> Schedule tasks.\n", encoding="utf-8")
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    from agents.core.skills.signing import source_snapshot

    fingerprint = source_snapshot(source).fingerprint
    target = tmp_path / "installed"
    importer = SkillImporter(str(target))
    assert await importer.import_repo_optional(source, "calendar", fingerprint)
    assert (target / "calendar/PENDING_REVIEW").exists()
    assert (target / "calendar/main.py").read_bytes() == b"VALUE = 1\n"
    from agents.core.skills import loader as loader_mod
    from agents.core.skills.approval import SkillApprovalStore

    monkeypatch.setattr(loader_mod, "SKILLS_DIR", target)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    loader = SkillLoader(approval_store=SkillApprovalStore(tmp_path / "approvals.json"))
    loader.discover()
    assert loader.skills["Calendar"].sandboxed is True
    assert loader.skills["Calendar"].trusted is False
    assert not await importer.import_repo_optional(source, "calendar", fingerprint)
    assert (target / "calendar/main.py").read_bytes() == b"VALUE = 1\n"


@pytest.mark.asyncio
async def test_repo_optional_install_refuses_drift_and_symlink(tmp_path):
    source = tmp_path / "optional" / "calendar"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Calendar\n\n> Schedule tasks.\n", encoding="utf-8")
    from agents.core.skills.signing import source_snapshot

    fingerprint = source_snapshot(source).fingerprint
    (source / "SKILL.md").write_text("# Calendar\n\n> Changed.\n", encoding="utf-8")
    target = tmp_path / "installed"
    importer = SkillImporter(str(target))
    before = _tree_snapshot(target)
    assert not await importer.import_repo_optional(source, "calendar", fingerprint)
    assert _tree_snapshot(target) == before
    fresh = source_snapshot(source).fingerprint
    (source / "link.py").symlink_to(source / "SKILL.md")
    assert not await importer.import_repo_optional(source, "calendar", fresh)
    assert _tree_snapshot(target) == before


@pytest.mark.asyncio
async def test_verified_hermes_publish_cannot_replace_racing_empty_owner_dir(
    tmp_path, monkeypatch, httpx_harness
):
    from agents.core.skills import importer as importer_module

    record = _v2_github_pin()
    _configure_pin(monkeypatch, tmp_path, record)
    entry = record["skills"][0]
    for path, content in [(entry["path"], HERMES_SKILL_BYTES.replace(b"github-issues", b"github")),
                          (entry["files"][0]["path"], GITHUB_REFERENCE)]:
        url = f"https://raw.githubusercontent.com/{PIN_REPOSITORY}/{PIN_COMMIT}/{path}"
        httpx_harness.responses[url] = _FakeResponse(200, content=content, url=url)
    installed = tmp_path / "installed"
    importer = SkillImporter(str(installed))
    native_publish = importer_module._publish_stage_no_replace
    winner = {}

    def racing_publish(stage, target):
        target.mkdir()
        target.chmod(0o700)
        winner["inode"] = target.stat().st_ino
        return native_publish(stage, target)

    monkeypatch.setattr(importer_module, "_publish_stage_no_replace", racing_publish)
    assert await importer.import_from_hermes("github", authorization=_authorization()) is False
    target = installed / "github"
    assert target.stat().st_ino == winner["inode"]
    assert target.stat().st_mode & 0o777 == 0o700
    assert list(target.iterdir()) == []
    assert not list(installed.glob(".hermes-stage-*"))


@pytest.mark.asyncio
async def test_repo_optional_publish_cannot_replace_racing_empty_owner_dir(tmp_path, monkeypatch):
    from agents.core.skills import importer as importer_module
    from agents.core.skills.signing import source_snapshot

    source = tmp_path / "optional" / "calendar"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Calendar\n\n> Schedule tasks.\n", encoding="utf-8")
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    installed = tmp_path / "installed"
    importer = SkillImporter(str(installed))
    native_publish = importer_module._publish_stage_no_replace
    winner = {}

    def racing_publish(stage, target):
        target.mkdir()
        target.chmod(0o700)
        winner["inode"] = target.stat().st_ino
        return native_publish(stage, target)

    monkeypatch.setattr(importer_module, "_publish_stage_no_replace", racing_publish)
    assert await importer.import_repo_optional(source, "calendar", source_snapshot(source).fingerprint) is False
    target = installed / "calendar"
    assert target.stat().st_ino == winner["inode"]
    assert target.stat().st_mode & 0o777 == 0o700
    assert list(target.iterdir()) == []
    assert not list(installed.glob(".optional-stage-*"))


def test_exclusive_publish_fails_closed_on_unsupported_platform(tmp_path, monkeypatch):
    from agents.core.skills import importer as importer_module

    stage = tmp_path / ".stage"
    stage.mkdir()
    (stage / "SKILL.md").write_text("owner candidate", encoding="utf-8")
    target = tmp_path / "skill"
    # Keep the interpreter's real os.name/sys.platform intact: changing them
    # globally breaks pathlib on Windows and would select the Windows branch.
    monkeypatch.setattr(importer_module, "os", SimpleNamespace(
        name="posix", fsencode=os.fsencode, fspath=os.fspath, strerror=os.strerror,
    ))
    monkeypatch.setattr(importer_module, "sys", SimpleNamespace(platform="unsupported-os"))
    with pytest.raises(OSError, match="exclusive directory rename unavailable"):
        importer_module._publish_stage_no_replace(stage, target)
    assert (stage / "SKILL.md").read_text(encoding="utf-8") == "owner candidate"
    assert not target.exists()


@pytest.mark.asyncio
async def test_optional_pending_review_survives_restart_and_approves_exact_bytes(tmp_path, monkeypatch):
    source = tmp_path / "optional" / "calendar"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Calendar\n\n> Schedule tasks.\n", encoding="utf-8")
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    from agents.core.skills import loader as loader_mod
    from agents.core.skills.approval import SkillApprovalStore
    from agents.core.skills.signing import source_snapshot

    target = tmp_path / "installed"
    assert await SkillImporter(str(target)).import_repo_optional(
        source, "calendar", source_snapshot(source).fingerprint
    )
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", target)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    store_path = tmp_path / "approvals.json"
    first = SkillLoader(approval_store=SkillApprovalStore(store_path))
    first.discover()
    assert first.skills["Calendar"].sandboxed
    detail = first.pending_skill_detail("calendar")
    assert detail is not None
    assert {row["path"] for row in detail["files"]} >= {"SKILL.md", "main.py"}
    assert next(row for row in detail["files"] if row["path"] == "main.py")["sha256"] == (
        hashlib.sha256(b"VALUE = 1\n").hexdigest()
    )
    restarted = SkillLoader(approval_store=SkillApprovalStore(store_path))
    restarted.discover()
    assert restarted.pending_skill_detail("calendar") is not None
    assert restarted.skills["Calendar"].sandboxed
    restarted.kernel_gate = lambda payload: "grant"
    assert restarted.approve_generated_skill("calendar", restarted.pending_skill_fingerprint("calendar")) is True
    assert not (target / "calendar/PENDING_REVIEW").exists()
    assert restarted._approval_store.approved_snapshot(target / "calendar") is not None


@pytest.mark.asyncio
async def test_openclaw_nested_import_uses_exact_commit_without_tree_listing(tmp_path, httpx_harness):
    nested_path = "skills/github/github-issues/SKILL.md"
    raw_url = f"https://raw.githubusercontent.com/openclaw/skills/{PIN_COMMIT}/{nested_path}"
    httpx_harness.responses[raw_url] = _FakeResponse(200, content=HERMES_SKILL_BYTES, url=raw_url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    pin = RemoteSkillPin("openclaw/skills", PIN_COMMIT, nested_path,
                         hashlib.sha256(HERMES_SKILL_BYTES).hexdigest())

    assert await importer.import_from_openclaw(
        "github-issues", pin=pin, authorization=_authorization()) is True
    assert httpx_harness.requests == [raw_url]
    sidecar = json.loads(
        (skills_dir / "github-issues" / "manifest.json").read_text(encoding="utf-8")
    )
    assert sidecar["source"] == "openclaw"
    assert sidecar["source_commit"] == PIN_COMMIT
    assert (skills_dir / "github-issues/PENDING_REVIEW").is_file()


@pytest.mark.asyncio
async def test_generic_github_flat_import_keeps_exact_pinned_artifact(tmp_path, httpx_harness):
    raw_url = f"https://raw.githubusercontent.com/example/tools/{PIN_COMMIT}/skills/pdf/SKILL.md"
    httpx_harness.responses[raw_url] = _FakeResponse(200, content=PDF_SKILL_BYTES, url=raw_url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))

    pin = RemoteSkillPin("example/tools", PIN_COMMIT, "skills/pdf/SKILL.md",
                         hashlib.sha256(PDF_SKILL_BYTES).hexdigest())
    assert await importer.import_from_github(
        "example/tools", "pdf", pin=pin, authorization=_authorization()) is True
    assert httpx_harness.requests == [raw_url]
    assert (skills_dir / "pdf" / "SKILL.md").read_text(encoding="utf-8") == PDF_SKILL_MD
    assert (skills_dir / "pdf/PENDING_REVIEW").is_file()
