"""H350, the review round — its findings, pinned.

- F1: a lone carriage return passed the check, but the loader reads a snapshot split on
  '\\n' only, so an approved skill loaded under its folder's name with no description.
  Such a document is refused, and every document the check passes loads as it declares.
- F2: a registry install of a package with an invalid SKILL.md answered 404.
- F3: a GitHub/Hermes/OpenClaw import refused for its SKILL.md answered 404.
- F4: skill_propose quoted an earlier generation's problems.
- F5: a heading-dialect file framed by '---' fences loads, and is no longer refused.
- F6: install_from_zip picked its folder from any '# ' line and replaced another skill.
- F7: the import report's text output named no reason for a rejected skill.
- F9: one document could yield thousands of problems.
- F10: ``nerva skills lint`` reported every oversized file as 65,537 bytes.
- F11: a SKILL.md is written as the bytes checked, never text-mode translated.
- F12: a duplicated key's problem points at the line YAML used.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import sqlite3
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.skills import loader as loader_mod
from agents.core.skills.validate import SkillDocumentInvalid, validate_skill_md
from tests.test_h318c_skill_review import TOOL_PROPOSE, _call, hub  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
DESC = "Sum the week's invoices. Use when asked for totals."
GOOD_FM = f"---\nname: invoice-digest\ndescription: {DESC}\n---\n## Steps\n1. Open the folder.\n"
GOOD_HEAD = f"# Invoice Digest\n\n> {DESC}\n\n## Steps\n1. Open the folder.\n"
FENCED_HEAD = "---\n\n# Weather\n\n> Get the weather. Use when asked about the forecast.\n\n## Steps\n1. look\n\n---\n"


def _zip(skill_md: str | bytes, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{folder}SKILL.md", skill_md)
        archive.writestr(f"{folder}main.py", "# code\n")
    return buffer.getvalue()


# ── F1: a lone carriage return, and parity with the loader ───────────────────────

@pytest.mark.parametrize("doc", [GOOD_HEAD.replace("\n", "\r"), GOOD_FM.replace("\n", "\r").encode(),
                                 "# A\n> does things\rand more\n"])
def test_a_lone_carriage_return_is_refused(doc):
    problems = validate_skill_md(doc)
    assert [p.field for p in problems] == ["document"], problems
    assert "carriage return" in problems[0].message


def test_a_lone_carriage_return_names_its_line():
    [problem] = validate_skill_md("# A\r\n> does things\r\nsteps\rmore\n")
    assert problem.line == 3


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("doc,name,description", [
    (GOOD_FM, "invoice-digest", DESC),
    (GOOD_HEAD, "Invoice Digest", DESC),
    (GOOD_FM.replace("\n", "\r\n"), "invoice-digest", DESC),
    (GOOD_HEAD.replace("\n", "\r\n"), "Invoice Digest", DESC),
    ("\ufeff" + GOOD_FM, "invoice-digest", DESC),
    ("\ufeff" + GOOD_HEAD, "Invoice Digest", DESC),
    ("-----\n" + GOOD_HEAD, "Invoice Digest", DESC),
    (FENCED_HEAD, "Weather", "Get the weather. Use when asked about the forecast."),
    (GOOD_FM.replace("\n", "\r"), "invoice-digest", DESC),
    (GOOD_HEAD.replace("\n", "\r"), "Invoice Digest", DESC),
])
def test_a_document_the_check_passes_loads_as_it_declares(hub, doc, name, description, pending):
    folder = hub.root / "notes"
    folder.mkdir()
    (folder / "SKILL.md").write_bytes(doc.encode("utf-8"))
    if pending:
        (folder / "PENDING_REVIEW").write_bytes(b"agent=test\n")
    loader = hub.load()
    if validate_skill_md(doc):
        return                                # refused: no write path lands it
    assert name in loader.skills, sorted(loader.skills)
    assert loader.skills[name].description == description
    assert loader.manifest_name(folder, doc) == name


# ── F2 and F3: the routes name the problems ──────────────────────────────────────

@pytest.fixture()
def market(tmp_path, monkeypatch):
    from agents.core.skills.marketplace import SkillMarketplace

    monkeypatch.setattr("agents.core.skills.marketplace.DB_PATH", tmp_path / "m.db")
    (tmp_path / "skills").mkdir()
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"))


def _client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import skills as skills_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h350b")
    monkeypatch.setattr(web, "orch", orch, raising=False)
    monkeypatch.setattr(skills_router, "get_orch", lambda: orch)
    return TestClient(web.app)


def test_a_registry_install_of_an_invalid_package_answers_422(market, tmp_path, monkeypatch):
    folder = tmp_path / "skills" / "notes"
    folder.mkdir()
    (folder / "SKILL.md").write_bytes(b"---\nname: notes\ndescription: Keep notes. Use when asked.\n---\nSteps.\n")
    market.publish_skill("notes")
    market.set_review_status("notes", "approved")
    # A package published before H350 (or restored by a rollback) holds a document the
    # check now refuses.
    conn = sqlite3.connect(str(market.db_path))
    conn.execute("UPDATE marketplace_skills SET package_zip = ? WHERE name = ?",
                 (_zip("# Notes\n\nKeep notes.\n"), "notes"))
    conn.commit()
    conn.close()
    orch = SimpleNamespace(marketplace=market, skills=SimpleNamespace(discover=lambda: None))
    got = _client(monkeypatch, orch).post("/api/skills/marketplace/install", json={"name": "notes"},
                                          headers={"X-Admin-Token": "adm-h350b"})
    assert got.status_code == 422, got.text
    assert got.json()["reason"] == "invalid_skill_md"
    assert got.json()["problems"][0]["field"] == "description"


def test_an_import_refused_for_its_skill_md_answers_422(tmp_path, monkeypatch):
    from agents import web
    from agents.core.skills.importer import SkillImporter

    importer = SkillImporter(str(tmp_path / "skills"))

    async def flat(*_args):
        return "---\nname: notes\n---\nSteps here\n"

    monkeypatch.setattr(importer, "_fetch_skill_md_flat", flat)
    monkeypatch.setattr(web, "DEV_MODE", True)
    client = _client(monkeypatch, SimpleNamespace(skill_importer=importer,
                                                  skills=SimpleNamespace(discover=lambda: None)))
    got = client.post("/skills/import", json={"source": "someuser/repo", "skill": "notes"})
    assert got.status_code == 422, got.text
    assert got.json()["ok"] is False and got.json()["reason"] == "invalid_skill_md"
    assert got.json()["problems"][0]["field"] == "description"
    # A later refusal for another reason is not reported with the stale problems.
    got = client.post("/skills/import", json={"source": "someuser/repo", "skill": "../notes"})
    assert got.status_code == 404, got.text
    assert importer.last_refusal == []


def test_a_save_refused_before_the_check_clears_the_last_refusal(tmp_path):
    from agents.core.skills.importer import SkillImporter

    importer = SkillImporter(str(tmp_path / "skills"))
    assert asyncio.run(importer._save_skill("x", "github", skill_md_text="---\nname: x\n---\nsteps\n")) is False
    assert importer.last_refusal
    assert asyncio.run(importer._save_skill("../x", "github", skill_md_text=GOOD_FM)) is False
    assert importer.last_refusal == []


# ── F4: skill_propose reports this generation's problems only ────────────────────

def test_skill_propose_never_quotes_an_earlier_generations_problems(hub, monkeypatch):
    monkeypatch.setattr(loader_mod, "_writable_skills_dir", lambda: hub.root)
    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", lambda _c: True)
    loader = hub.load()
    bad = _call(hub.server, TOOL_PROPOSE, {"description": "sum the invoices\n# Private Heading",
                                           "steps": ["open it"]})
    assert bad["reason"] == "skill_propose_invalid"
    # The next generation stops before its check (the contract refuses it).
    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", lambda _c: False)
    again = _call(hub.server, TOOL_PROPOSE, {"description": "summarize the weekly invoices",
                                             "steps": ["open the folder"]})
    assert again["ok"] is False and again["reason"] == "skill_propose_refused", again
    assert "Private Heading" not in str(again)
    assert loader.last_generation_problems == [] and loader.last_generation_warnings == []


# ── F5: a heading file framed by fences ──────────────────────────────────────────

def test_a_heading_file_framed_by_fences_is_checked_as_headings():
    assert validate_skill_md(FENCED_HEAD) == []
    problems = validate_skill_md(FENCED_HEAD.replace("## Steps", "# Steps"))
    assert [p.field for p in problems] == ["name"] and "second '# '" in problems[0].message
    # Without a heading to read, the block is still reported as frontmatter.
    assert [p.field for p in validate_skill_md("---\n- a\n- b\n---\nsteps\n")] == ["frontmatter"]
    assert [p.field for p in validate_skill_md("---\nname: [a\ndescription: b\n---\n# A\n> b\n")] == ["frontmatter"]


# ── F6: the folder is the validated name, and another skill is never replaced ────

def test_the_folder_is_the_validated_name_not_a_body_heading(market, tmp_path):
    skills = tmp_path / "skills"
    (skills / "pm").mkdir()
    (skills / "pm" / "SKILL.md").write_bytes(b"# pm\n> Plan the week. Use when asked to plan.\n")
    (skills / "pm" / "main.py").write_bytes(b"def run():\n    return 1\n")
    package = f"---\nname: invoice-digest\ndescription: {DESC}\n---\n# Pm\n\nSteps here.\n"
    assert market.install_from_zip(_zip(package)) is True
    assert (skills / "invoice-digest" / "SKILL.md").read_bytes() == package.encode()
    assert (skills / "pm" / "main.py").read_bytes() == b"def run():\n    return 1\n"


def test_a_heading_after_a_byte_order_mark_names_the_folder(market, tmp_path):
    assert market.install_from_zip(_zip("\ufeff" + GOOD_HEAD, "zipdir/")) is True
    assert (tmp_path / "skills" / "invoice_digest").is_dir()
    assert not (tmp_path / "skills" / "zipdir").exists()


def test_an_install_never_replaces_another_skill(market, tmp_path):
    skills = tmp_path / "skills"
    (skills / "weather").mkdir()
    (skills / "weather" / "SKILL.md").write_bytes(b"# Weather Intel\n> Forecasts. Use when asked.\n")
    (skills / "weather" / "main.py").write_bytes(b"x = 1\n")
    with pytest.raises(SkillDocumentInvalid) as exc:
        market.install_from_zip(_zip(f"---\nname: weather\ndescription: {DESC}\n---\nSteps.\n"))
    assert exc.value.problems[0].field == "name" and "another skill" in exc.value.problems[0].message
    assert (skills / "weather" / "main.py").read_bytes() == b"x = 1\n"
    # The same skill again is a reinstall, and replaces its folder.
    assert market.install_from_zip(_zip(GOOD_HEAD)) is True
    assert market.install_from_zip(_zip(GOOD_HEAD.replace("Open the folder", "Open it"))) is True
    assert b"Open it" in (skills / "invoice_digest" / "SKILL.md").read_bytes()


# ── F7: the import report names why a skill was rejected ─────────────────────────

def _import_script():
    spec = importlib.util.spec_from_file_location("nerva_import_h350b", REPO / "scripts" / "nerva_import.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nerva_import_h350b"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_import_report_names_the_problems_of_a_rejected_skill(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    source = tmp_path / "home" / ".hermes" / "skills" / "notes"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"---\nname: notes\n---\n\nTake notes.\n")
    ni = _import_script()
    assert ni.main(["--from", "hermes", "--home", str(tmp_path / "home"), "--only", "skills",
                    "--skills-dir", str(tmp_path / "skills")]) == 0
    out = capsys.readouterr().out
    assert "1 rejected" in out
    assert "notes" in out and "invalid_skill_md" in out and "description: missing" in out


# ── F9: the problem list is bounded ──────────────────────────────────────────────

@pytest.mark.parametrize("extra", ["# a\n", "> b\n"])
def test_repeated_lines_are_one_problem_with_a_count(extra):
    problems = validate_skill_md("# a\n> b c\n" + extra * 16000)
    assert len(problems) == 1, len(problems)
    assert "15,999 more" in problems[0].message and problems[0].line == 3
    assert len(str(SkillDocumentInvalid(problems))) < 500


# ── F10: the lint names an oversized file's real size ────────────────────────────

def test_the_lint_reports_an_oversized_files_real_size(tmp_path):
    from tests.test_h350_skill_validator import _nerva

    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "SKILL.md").write_bytes(GOOD_FM.encode() + b"x" * 200_000)
    run = _nerva("skills", "lint", str(tmp_path / "big"))
    assert run.returncode == 1
    assert f"{len(GOOD_FM) + 200_000:,} bytes; at most 65,536" in run.stdout, run.stdout


# ── F11: the bytes checked are the bytes written ─────────────────────────────────

@pytest.fixture()
def windows_text(monkeypatch):
    """Path.write_text as Windows runs it: every '\\n' lands as '\\r\\n'."""
    real = Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:
            data = data.replace("\n", "\r\n")
        return real(self, data, encoding=encoding, errors=errors, newline="")

    monkeypatch.setattr(Path, "write_text", write_text)


def test_an_import_writes_the_checked_bytes(tmp_path, windows_text):
    from agents.core.skills.importer import SkillImporter

    importer = SkillImporter(str(tmp_path / "skills"))
    assert asyncio.run(importer._save_skill("invoice-digest", "github", skill_md_text=GOOD_FM)) is True
    assert (tmp_path / "skills" / "invoice-digest" / "SKILL.md").read_bytes() == GOOD_FM.encode()


def test_generation_writes_the_checked_bytes(hub, monkeypatch, windows_text):
    monkeypatch.setattr(loader_mod, "_writable_skills_dir", lambda: hub.root)
    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", lambda _c: True)
    made = hub.load().generate_skill("friday", "summarize the weekly invoices", ["open the folder"])
    assert made and b"\r" not in (hub.root / made / "SKILL.md").read_bytes()


# ── F12: a duplicated key points at the line YAML used ───────────────────────────

def test_a_duplicated_key_points_at_the_last_occurrence():
    [problem] = validate_skill_md("---\nname: good\nname: ../bad\ndescription: does things\n---\nbody\n")
    assert problem.field == "name" and "'../bad'" in problem.message and problem.line == 3

