"""
Tests for the SKILL.md-based skill importer (Hermes / agentskills.io) and the
loader's YAML-frontmatter parsing.

Regression coverage for the importer/loader fix: the real NousResearch/hermes-agent
repo lays skills out as skills/<category>/<skill>/SKILL.md with YAML frontmatter
(not a flat manifest.json), so the old importer 404'd on every skill and the
loader never read frontmatter. These tests run fully offline (httpx is mocked).
"""

import copy
import hashlib
import json

import pytest

import agents.core.skills.importer as importer_mod
from agents.core.skills.importer import SkillImporter, SkillImportError
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

PIN_REPOSITORY = "NousResearch/hermes-agent"
PIN_RELEASE_TAG = "v2026.8.27"
PIN_COMMIT = "5fc308a70719a83cccdbba4c0e39c23f5a8239d5"
PIN_TREE = "222ec43b5237deb643277bc2f64fa4b873dd7f28"
PIN_PATH = "skills/github/github-issues/SKILL.md"
PIN_FILE_SHA256 = "0acc2b07b31afc24ab04eac56596e6dde6427eaf5b1370009f5ec138f0c3f7fb"
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


@pytest.fixture
def httpx_harness(monkeypatch):
    import httpx

    _FakeClient.responses = {}
    _FakeClient.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
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
    }


def _pin_record(*entries):
    return {
        "schema_version": 1,
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
    assert len(pin.skills) == 82
    assert hashlib.sha256(importer_mod.HERMES_PIN_PATH.read_bytes()).hexdigest() == PIN_FILE_SHA256


@pytest.mark.asyncio
async def test_import_from_hermes_uses_exact_pin_and_records_provenance(tmp_path, pinned_hermes):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    ok = await importer.import_from_hermes("github-issues")
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
    assert await importer.import_from_hermes("github-issues") is True

    import agents.core.skills.loader as loader_mod

    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_dir)
    loader = SkillLoader()
    skills = loader.discover()
    assert "github-issues" in skills
    assert skills["github-issues"].version == "1.1.0"


@pytest.mark.asyncio
async def test_list_imported_reports_imported_only(tmp_path, pinned_hermes):
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))
    local = skills_dir / "brief"
    local.mkdir()
    (local / "SKILL.md").write_text("# Brief\n", encoding="utf-8")

    await importer.import_from_hermes("github-issues")
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

    assert await importer.import_from_hermes("does-not-exist") is False
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
    record["schema_version"] = 2
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
        await importer.import_from_hermes("github-issues")

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
        "response-path",
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
    elif failure == "response-path":
        response = _FakeResponse(
            200,
            content=content,
            url=expected_url.replace("github-issues", "other-skill"),
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

    assert await importer.import_from_hermes("github-issues") is False
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

    imported = await importer.sync_source("hermes")

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

    imported = await importer.sync_source("hermes", category="productivity")

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

    assert await importer.sync_source("hermes", category=category) == []
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

    assert await importer.sync_source("hermes") == []
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
        await importer.sync_source("hermes")

    assert httpx_harness.requests == []
    assert _tree_snapshot(skills_dir) == before


@pytest.mark.asyncio
async def test_openclaw_nested_import_keeps_existing_mutable_tree_behavior(tmp_path, httpx_harness):
    tree_url = "https://api.github.com/repos/openclaw/skills/git/trees/main?recursive=1"
    nested_path = "skills/github/github-issues/SKILL.md"
    raw_url = f"https://raw.githubusercontent.com/openclaw/skills/main/{nested_path}"
    httpx_harness.responses[tree_url] = _FakeResponse(
        200,
        json_data={
            "tree": [
                {"type": "tree", "path": "skills/github"},
                {"type": "blob", "path": nested_path},
            ]
        },
        url=tree_url,
    )
    httpx_harness.responses[raw_url] = _FakeResponse(200, content=HERMES_SKILL_BYTES, url=raw_url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))

    assert await importer.import_from_openclaw("github-issues") is True
    assert tree_url in httpx_harness.requests
    assert raw_url in httpx_harness.requests
    sidecar = json.loads(
        (skills_dir / "github-issues" / "manifest.json").read_text(encoding="utf-8")
    )
    assert sidecar["source"] == "openclaw"
    assert "source_commit" not in sidecar


@pytest.mark.asyncio
async def test_generic_github_flat_import_keeps_existing_behavior(tmp_path, httpx_harness):
    raw_url = "https://raw.githubusercontent.com/example/tools/main/skills/pdf/SKILL.md"
    httpx_harness.responses[raw_url] = _FakeResponse(200, content=PDF_SKILL_BYTES, url=raw_url)
    skills_dir = tmp_path / "installed"
    importer = SkillImporter(skills_dir=str(skills_dir))

    assert await importer.import_from_github("example/tools", "pdf") is True
    assert httpx_harness.requests == [raw_url]
    assert (skills_dir / "pdf" / "SKILL.md").read_text(encoding="utf-8") == PDF_SKILL_MD
