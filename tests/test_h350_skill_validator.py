"""H350 — a SKILL.md is validated before any write lands it, and linted on request.

Hermes blocks an agent's write of a malformed SKILL.md (``_validate_frontmatter``: the
fence, a YAML mapping, a name and a description, the description's length, a body, a
size cap) and lints the authoring standards the hard check does not cover. Nerva had
neither: a malformed file fell through to the heading parser and registered under its
folder's name with an empty description. Now every write path refuses one, with the
field and the reason, and ``nerva skills lint`` reports the rest.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from agents.core.skills import validate
from agents.core.skills.validate import (
    MAX_SKILL_MD_BYTES,
    SkillDocumentInvalid,
    lint_skill_md,
    require_valid,
    validate_skill_md,
)
from tests.test_h318c_skill_review import TOOL_PROPOSE, _call, _new_text, hub  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
GOOD_FM = "---\nname: invoice-digest\ndescription: Sum the week's invoices. Use when asked for totals.\n---\n## Steps\n1. Open the folder.\n"
GOOD_HEAD = "# Invoice Digest\n\n> Sum the week's invoices. Use when asked for totals.\n\n## Steps\n1. Open the folder.\n"


def _fields(document):
    return [(p.field, p.message) for p in validate_skill_md(document)]


# ── the hard check ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc", [GOOD_FM, GOOD_HEAD, GOOD_FM.encode(), "﻿" + GOOD_FM,
                                 GOOD_FM.replace("\n", "\r\n"), GOOD_HEAD.replace("\n", "\r\n"),
                                 "\ufeff" + GOOD_HEAD, ("\ufeff" + GOOD_HEAD).encode(),
                                 GOOD_HEAD.replace("\n", "\r"), GOOD_FM.replace("\n", "\r").encode(),
                                 "-----\n" + GOOD_HEAD])
def test_a_well_formed_skill_passes_in_either_dialect(doc):
    assert validate_skill_md(doc) == []
    require_valid(doc)


def test_every_skill_in_the_repository_passes():
    files = subprocess.run(["git", "ls-files", "*SKILL.md"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split()
    assert len(files) >= 12
    for rel in files:
        assert validate_skill_md((REPO / rel).read_bytes()) == [], rel


@pytest.mark.parametrize("doc,field,words", [
    ("", "document", "empty"),
    ("  \n\n", "document", "empty"),
    (b"\xff\xfe# x", "document", "not UTF-8"),
    ("# A\n> b c\nsteps\x00", "document", "NUL"),
    ("---\nname: a\ndescription: b\nsteps\n", "frontmatter", "closing '---'"),
    ("---\nname: [a\ndescription: b\n---\nsteps\n", "frontmatter", "not valid YAML"),
    ("---\n- a\n- b\n---\nsteps\n", "frontmatter", "mapping"),
    ("---\n---\nsteps\n", "frontmatter", "not nothing"),
    ("---\ndescription: does things\n---\nsteps\n", "name", "missing"),
    ("---\nname: 12\ndescription: does things\n---\nsteps\n", "name", "must be text"),
    ("---\nname: ../../etc\ndescription: does things\n---\nsteps\n", "name", "cannot name a skill folder"),
    ("---\nname: " + "a" * 65 + "\ndescription: does things\n---\nsteps\n", "name", "at most 64"),
    ("---\nname: a\n---\nsteps\n", "description", "missing"),
    ("---\nname: a\ndescription: [x]\n---\nsteps\n", "description", "must be text"),
    ("---\nname: a\ndescription: " + "d" * 1025 + "\n---\nsteps\n", "description", "at most 1,024"),
    ("---\nname: a\ndescription: does things\n---\n\n  \n", "body", "empty"),
    ("just some notes\n", "name", "missing"),
    ("# A\nsteps\n", "description", "missing"),
    ("# A\n> does things\nsteps\n```sh\n# install it\n```\n", "name", "second '# '"),
    ("# A\n> does things\nsteps\n> a quotation\n", "description", "second '> '"),
    ("# A\x07\n> does things\nsteps\n", "name", "control character"),
])
def test_each_problem_is_named_with_its_field(doc, field, words):
    found = _fields(doc)
    assert any(f == field and words in m for f, m in found), found


def test_the_size_cap_counts_bytes_as_written():
    big = GOOD_FM + "x" * MAX_SKILL_MD_BYTES
    assert _fields(big)[0][0] == "document" and "at most 65,536" in _fields(big)[0][1]
    assert _fields(big.encode())[0][0] == "document"
    fits = GOOD_FM + "é" * ((MAX_SKILL_MD_BYTES - len(GOOD_FM.encode())) // 2)
    assert validate_skill_md(fits) == []
    assert validate_skill_md(fits + "é")                        # one more two-byte character
    assert MAX_SKILL_MD_BYTES == __import__("agents.core.skills.tools", fromlist=["x"]).MAX_FILE_BYTES


def test_a_problem_carries_its_line_and_every_problem_is_reported():
    doc = "---\nname: ../x\ndescription: " + "d" * 2000 + "\n---\n\n"
    problems = validate_skill_md(doc)
    assert [p.field for p in problems] == ["name", "description", "body"]
    assert problems[0].line == 2 and problems[1].line == 3
    with pytest.raises(SkillDocumentInvalid) as exc:
        require_valid(doc)
    assert isinstance(exc.value, ValueError) and len(exc.value.as_list()) == 3
    assert exc.value.as_list()[0] == {"field": "name", "message": problems[0].message, "line": 2}
    assert "name:" in str(exc.value) and "(line 2)" in str(exc.value)


def test_a_yaml_error_names_its_line():
    problems = validate_skill_md("---\nname: a\ndescription: b\nbad: [x\n---\nsteps\n")
    assert problems[0].field == "frontmatter" and problems[0].line in (4, 5, 6)


def test_the_folder_rule_is_the_importers():
    from agents.core.skills.importer import _SLUG_RE, _safe_slug

    assert validate._FOLDER_NAME.pattern == _SLUG_RE.pattern
    for name in ("Google Workspace", "a.b_c-d", "x" * 64, "../x", "", " -a", "a/b", "é"):
        assert validate.folder_safe(name) == (_safe_slug(name) is not None), name


# ── the advisory lint ────────────────────────────────────────────────────────────

def test_the_lint_reports_what_the_hard_check_lets_through():
    doc = ("---\nname: other\ndescription: Does it.\nbogus_key: 1\n---\nRun /home/ann/bin/x \n"
           "```sh\nls\n")
    got = [(p.field, p.message) for p in lint_skill_md(doc, folder="mine")]
    assert validate_skill_md(doc) == []

    def has(field, words):
        return any(f == field and words in m for f, m in got)

    assert has("bogus_key", "not a key Nerva or Hermes reads")
    assert has("name", "'other' differs from its folder 'mine'")
    assert has("description", "too short") and has("description", "does not say when to use the skill")
    assert has("body", "no '## ' section") and has("body", "never closed") and has("body", "home folder")
    assert has("document", "trailing whitespace")
    assert lint_skill_md(GOOD_FM, folder="invoice-digest") == []
    assert lint_skill_md(GOOD_HEAD, folder="invoice_digest") == []


def test_a_heading_skill_needs_no_body_but_is_advised_one():
    doc = "# Photo Tool\n> Clean photos. Use when asked to enhance one.\n**Version:** 1.0\n"
    assert validate_skill_md(doc) == []
    assert any(p.field == "body" and "no '## ' section" in p.message for p in lint_skill_md(doc))


def test_a_long_body_is_advised_against_not_refused():
    doc = GOOD_FM + "line\n" * 600
    assert validate_skill_md(doc) == []
    assert any(p.field == "body" and p.message.startswith("603 lines") for p in lint_skill_md(doc))


# ── the write paths ──────────────────────────────────────────────────────────────

def test_an_import_refuses_an_invalid_skill_and_writes_nothing(tmp_path):
    from agents.core.skills.importer import SkillImporter

    importer = SkillImporter(str(tmp_path / "skills"))
    bad = "---\nname: x\n---\nsteps\n"
    assert asyncio.run(importer._save_skill("x", "github", skill_md_text=bad)) is False
    assert asyncio.run(importer._save_skill("x", "github", skill_md_bytes=bad.encode())) is False
    assert not (tmp_path / "skills" / "x").exists()
    assert [p.field for p in importer.last_refusal] == ["description"]
    assert asyncio.run(importer._save_skill("invoice-digest", "github", skill_md_text=GOOD_FM)) is True
    assert importer.last_refusal == []


def test_a_manifest_import_writes_a_skill_that_passes(tmp_path):
    from agents.core.skills.importer import SkillImporter

    importer = SkillImporter(str(tmp_path / "skills"))
    ok = asyncio.run(importer._save_skill("notes", "hermes",
                                          manifest={"name": "notes", "description": "Keep notes. Use when asked."}))
    assert ok is True
    assert validate_skill_md((tmp_path / "skills" / "notes" / "SKILL.md").read_bytes()) == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_local_import_refuses_an_invalid_skill_before_anything(tmp_path, dry_run):
    from agents.core.skills.importer import SkillImporter

    src = tmp_path / "home" / "skills" / "notes"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"---\nname: notes\n---\nKeep notes.\n")
    importer = SkillImporter(str(tmp_path / "skills"))
    got = asyncio.run(importer.import_local_skill(src, "hermes", dry_run=dry_run))
    assert got["status"] == "rejected" and got["reason"] == "invalid_skill_md"
    assert got["problems"] == [{"field": "description", "message": validate_skill_md(
        b"---\nname: notes\n---\nKeep notes.\n")[0].message}]
    assert not (tmp_path / "skills").exists() or not any((tmp_path / "skills").iterdir())


def test_a_reimport_of_a_source_that_went_bad_changes_nothing(tmp_path):
    from agents.core.skills.importer import SkillImporter

    src = tmp_path / "home" / "skills" / "notes"
    src.mkdir(parents=True)
    good = b"---\nname: notes\ndescription: Keep notes. Use when asked.\n---\nKeep notes.\n"
    (src / "SKILL.md").write_bytes(good)
    importer = SkillImporter(str(tmp_path / "skills"))
    assert asyncio.run(importer.import_local_skill(src, "hermes"))["status"] == "imported"
    target = tmp_path / "skills" / "notes"
    before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
    (src / "SKILL.md").write_bytes(b"---\nname: notes\ndescription: Keep notes.\n---\n")
    got = asyncio.run(importer.import_local_skill(src, "hermes", overwrite=True,
                                                  backup_dir=tmp_path / "backups",
                                                  revoke_approval=lambda _p: True))
    assert got["status"] == "rejected" and got["reason"] == "invalid_skill_md"
    assert {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()} == before
    assert not (tmp_path / "backups").exists()


@pytest.fixture()
def market(tmp_path, monkeypatch):
    from agents.core.skills.marketplace import SkillMarketplace

    monkeypatch.setattr("agents.core.skills.marketplace.DB_PATH", tmp_path / "m.db")
    (tmp_path / "skills").mkdir()
    return SkillMarketplace(skills_dir=str(tmp_path / "skills"))


def test_publishing_an_invalid_skill_is_refused_with_its_problems(market, tmp_path):
    folder = tmp_path / "skills" / "notes"
    folder.mkdir()
    (folder / "SKILL.md").write_bytes(b"# Notes\n\nKeep notes.\n")
    with pytest.raises(SkillDocumentInvalid) as exc:
        market.publish_skill("notes")
    assert [p.field for p in exc.value.problems] == ["description"]
    assert market.list_skills() == []


def _zip(skill_md: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", skill_md)
        archive.writestr("main.py", "# code\n")
    return buffer.getvalue()


def test_installing_an_invalid_package_is_refused_and_places_nothing(market, tmp_path):
    with pytest.raises(SkillDocumentInvalid):
        market.install_from_zip(_zip("# Notes\n> keep notes\n# Notes Again\nsteps\n"))
    assert [p.name for p in (tmp_path / "skills").iterdir() if not p.name.startswith(".")] == []
    assert market.install_from_zip(_zip(GOOD_HEAD)) is True


def test_the_routes_answer_422_with_every_problem(market, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h350")
    orch = type("O", (), {"marketplace": market, "skills": type("S", (), {"discover": lambda self: None})()})()
    monkeypatch.setattr(web, "orch", orch, raising=False)
    from agents.core.routers import skills as skills_router

    monkeypatch.setattr(skills_router, "get_orch", lambda: orch)
    client = TestClient(web.app)
    headers = {"X-Admin-Token": "adm-h350"}
    zipped = base64.b64encode(_zip("---\nname: n\n---\nsteps\n")).decode()
    got = client.post("/api/skills/marketplace/install-zip", json={"zip_base64": zipped}, headers=headers)
    assert got.status_code == 422, got.text
    body = got.json()
    assert body["reason"] == "invalid_skill_md" and body["problems"][0]["field"] == "description"
    (tmp_path / "skills" / "notes").mkdir()
    (tmp_path / "skills" / "notes" / "SKILL.md").write_bytes(b"# Notes\n\nsteps\n")
    got = client.post("/api/skills/marketplace/publish", json={"name": "notes"}, headers=headers)
    assert got.status_code == 422 and got.json()["problems"][0]["field"] == "description"


def test_generation_refuses_a_document_that_would_not_pass(hub, monkeypatch):
    from agents.core.skills import loader as loader_mod

    monkeypatch.setattr(loader_mod, "_writable_skills_dir", lambda: hub.root)
    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", lambda _c: True)
    loader = hub.load()
    assert loader.generate_skill("friday", "d" * 1100, ["step one"]) is None
    assert [p.field for p in loader.last_generation_problems] == ["description"]
    assert list(hub.root.iterdir()) == []
    assert len(loader._name_from_task("x" * 300)) <= 64          # one long word never makes a folder too long
    made = loader.generate_skill("friday", "summarize the weekly invoices", ["open the folder"])
    assert made and validate_skill_md((hub.root / made / "SKILL.md").read_bytes()) == []
    assert loader.last_generation_problems == []


def test_skill_propose_names_why_a_new_skill_was_not_written(hub, monkeypatch):
    from agents.core.skills import loader as loader_mod

    monkeypatch.setattr(loader_mod, "_writable_skills_dir", lambda: hub.root)
    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", lambda _c: True)
    hub.load()
    # A line break in the description puts a second '# ' line into the generated file.
    got = _call(hub.server, TOOL_PROPOSE, {"description": "sum the invoices\n# Other title",
                                            "steps": ["open it"]})
    assert got["ok"] is False and got["reason"] == "skill_propose_invalid", got
    assert got["problems"][0]["field"] == "name" and list(hub.root.iterdir()) == []


def test_skill_propose_refuses_an_invalid_patch_with_its_problems(hub):
    hub.write("plan")
    hub.load()
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "")})
    assert got["ok"] is False and got["reason"] == "skill_propose_invalid"
    assert got["problems"] == [{"field": "body", "message": "empty: the instructions go below the frontmatter",
                                "line": 4}]
    assert hub.proposals.list("pending") == []


def test_an_approved_proposal_that_fails_the_check_is_rejected_at_apply(hub):
    hub.write("plan")
    loader = hub.load()
    live = (hub.root / "plan" / "SKILL.md").read_bytes()
    rec = hub.proposals.propose("plan", live.decode(), "---\nname: plan\n---\nNo description.\n",
                                origin="background_review")        # a ledger entry from before H350
    card = hub.proposals.queue_card(rec["id"], hub.queue, agent="background_review", summary="x")
    hub.queue.decide(card, True, by="owner")
    out = hub.curator.apply_decisions()
    assert out["applied"] == [] and out["outcomes"][0]["reason"] == "invalid_skill_md"
    assert out["outcomes"][0]["problems"][0]["field"] == "description"
    assert hub.proposals.get(rec["id"])["status"] == "rejected"
    assert hub.proposals.get(rec["id"])["reason"] == "invalid_skill_md"
    assert (hub.root / "plan" / "SKILL.md").read_bytes() == live
    assert "plan" in loader.skills


def test_the_background_review_never_proposes_an_invalid_patch(hub):
    from agents.core.learning.background_review import BackgroundReviewer

    hub.write("plan")
    loader = hub.load()
    reviewer = BackgroundReviewer(lambda prompt: None, skills=loader, proposals=hub.proposals,
                                  approvals=hub.queue, get_setting=lambda k, d=None: d)
    assert reviewer._dispatch_patch({"name": "plan", "content": "---\nname: plan\n---\nSteps.\n"}, []) is False
    assert hub.proposals.list("pending") == [] and hub.queue.list("pending") == []
    assert reviewer._dispatch_patch({"name": "plan", "content": _new_text("plan", "Next.\n")}, []) is True


# ── the CLI ──────────────────────────────────────────────────────────────────────

def _nerva(*args):
    from agents.cli import nerva

    out, err = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ={}, out=out, err=err, inp=io.StringIO(""))
    code = nerva.main(list(args), context=ctx)
    return subprocess.CompletedProcess(args, code, out.getvalue(), err.getvalue())


def test_nerva_skills_lint_reports_problems_and_findings(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "SKILL.md").write_text(GOOD_FM.replace("invoice-digest", "good"), encoding="utf-8")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: bad\n---\nsteps\n", encoding="utf-8")
    run = _nerva("skills", "lint", str(good))
    assert run.returncode == 0 and "ok" in run.stdout, run.stdout + run.stderr
    run = _nerva("skills", "lint", str(tmp_path))
    assert run.returncode == 1
    assert "bad/SKILL.md" in run.stdout and "error  description: missing" in run.stdout
    run = _nerva("skills", "lint", "--json", str(bad / "SKILL.md"))
    report = json.loads(run.stdout)
    assert report[0]["errors"][0]["field"] == "description" and run.returncode == 1
    run = _nerva("skills", "lint", "--strict", str(good))
    assert run.returncode == 0
    (good / "SKILL.md").write_text(GOOD_FM.replace("invoice-digest", "good") + "tail \n", encoding="utf-8")
    assert _nerva("skills", "lint", str(good)).returncode == 0
    assert _nerva("skills", "lint", "--strict", str(good)).returncode == 1
    assert _nerva("skills", "lint", str(tmp_path / "missing")).returncode == 2
