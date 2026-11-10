"""H336 — the vendored Hermes skill catalog as an owner action: install outside DEV_MODE,
repair/restore, and ``nerva skills catalog`` (browse capped at 100 like Hermes).

Hermes ships its optional skills inert, ``hermes skills browse --source official`` lists at
most 100 a source, ``hermes skills install official/<category>/<skill>`` copies one into the
active skills folder and ``repair-official --restore`` puts a damaged one back. In Nerva the
owner route ``POST /api/skills/catalog/install`` (admin, no DEV_MODE: the catalog is pinned,
byte-verified and instruction-only) does both; every other import source and a user token
stay behind ``POST /skills/import``'s DEV_MODE gate. No test touches the network.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.cli.client import HubError  # noqa: E402
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, main  # noqa: E402
from agents.core.routers import skills as skills_router  # noqa: E402
from agents.core.skills import hermes_catalog  # noqa: E402
from agents.core.skills.importer import SkillImporter  # noqa: E402
from tests.test_h349_skill_provenance_pin import ADMIN, _md, hub  # noqa: E402,F401

VENDOR = hermes_catalog.VENDOR_ROOT
INSTALL = "/api/skills/catalog/install"
IMPORT = "/skills/import"
SKILL = "agentmail"                      # optional-skills/email/agentmail: SKILL.md + references
WITH_CODE = "comfyui"


def _entry(slug):
    return next(s for s in hermes_catalog.load().index["skills"] if s["slug"] == slug)


def _tree(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def owner(hub, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(web, "DEV_MODE", False)
    monkeypatch.setattr(skills_router, "_catalog_backups", lambda: tmp_path / "repair-backups")
    hub.boot()
    return hub


# ── install outside DEV_MODE, for the catalog only ───────────────────────────

@pytest.mark.parametrize("ident", [SKILL, "email/agentmail", "official/email/agentmail",
                                   "optional-skills/email/agentmail"])
def test_the_owner_installs_a_catalog_skill_without_dev_mode(owner, ident):
    entry = _entry(SKILL)
    reply = owner.client.post(INSTALL, json={"skill": ident}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["ok"] and body["action"] == "install" and body["status"] == "installed"
    assert body["skill"] == SKILL and body["path"] == entry["path"] and body["audited"] is True
    folder = owner.home / SKILL
    for item in entry["files"]:
        assert (folder / item["path"]).read_bytes() == (VENDOR / entry["path"] / item["path"]).read_bytes()
    sidecar = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert sidecar["source"] == "hermes" and sidecar["source_catalog"] == "vendored"
    assert SKILL in owner.loader.skills            # discovered at once
    assert owner.loader.skills[SKILL].external and not owner.loader.skills[SKILL].owner_vouched
    rows = [r for r in owner.log.rows if r["action"] == "skill.install"]
    assert len(rows) == 1 and rows[0]["actor"] == "owner" and rows[0]["cause"] == "skills.catalog"
    assert rows[0]["metadata"]["skill"] == SKILL and rows[0]["metadata"]["commit"] == body["commit"]


def test_a_user_token_cannot_install_and_other_sources_keep_dev_mode(owner, monkeypatch):
    monkeypatch.setattr(web, "USER_TOKEN", "u")
    for headers in ({}, {"X-User-Token": "u"}):
        assert owner.client.post(INSTALL, json={"skill": SKILL}, headers=headers).status_code in (401, 403)
    assert not (owner.home / SKILL).exists() and owner.log.rows == []
    # POST /skills/import is unchanged: every source, the catalog's included, needs DEV_MODE.
    for source in ("hermes-catalog", "hermes", "openclaw", "someone/repo"):
        reply = owner.client.post(IMPORT, json={"source": source, "skill": SKILL}, headers=ADMIN)
        assert reply.status_code == 403 and "DEV_MODE" in reply.json()["error"], source
    assert not (owner.home / SKILL).exists()
    # The owner route takes the catalog only: there is no source to name.
    bad = owner.client.post(INSTALL, json={"skill": SKILL, "source": "someone/repo"}, headers=ADMIN)
    assert bad.status_code == 422
    for body in ({}, {"skill": ""}, {"skill": SKILL, "repair": "yes"}, {"skill": "x" * 201}):
        assert owner.client.post(INSTALL, json=body, headers=ADMIN).status_code == 422, body


def test_code_excluded_and_unknown_skills_are_refused_and_nothing_is_written(owner):
    before = _tree(owner.home)
    code = owner.client.post(INSTALL, json={"skill": WITH_CODE}, headers=ADMIN)
    assert code.status_code == 422 and code.json()["reason"] == "upstream_only" and code.json()["code_files"]
    excluded = owner.client.post(INSTALL, json={"skill": "creative/pretext"}, headers=ADMIN)
    assert excluded.status_code == 422 and excluded.json()["reason"] == "excluded"
    for ident in ("no-such-skill", "../etc/passwd", "email/../../x", "nope/agentmail"):
        missing = owner.client.post(INSTALL, json={"skill": ident}, headers=ADMIN)
        assert missing.status_code == 404 and missing.json()["reason"] == "not_found", ident
    assert _tree(owner.home) == before and owner.log.rows == []


def test_an_owner_folder_of_that_name_is_left_alone(owner):
    mine = owner.home / SKILL
    mine.mkdir()
    (mine / "SKILL.md").write_bytes(_md(SKILL, "Use when the owner wrote it").encode())
    before = _tree(owner.home)
    reply = owner.client.post(INSTALL, json={"skill": SKILL}, headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "exists", reply.text
    repair = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True, "force": True}, headers=ADMIN)
    assert repair.status_code == 409 and repair.json()["reason"] == "not_from_catalog", repair.text
    assert _tree(owner.home) == before and owner.log.rows == []


# ── repair / restore ─────────────────────────────────────────────────────────

def _installed(owner):
    assert owner.client.post(INSTALL, json={"skill": SKILL}, headers=ADMIN).status_code == 200
    owner.log.rows.clear()
    return owner.home / SKILL, _entry(SKILL)


def test_repair_restores_deleted_files(owner):
    folder, entry = _installed(owner)
    extra = next(f["path"] for f in entry["files"] if f["path"] != "SKILL.md")
    (folder / extra).unlink()
    (folder / "SKILL.md").unlink()
    (folder / "my-notes.md").write_bytes(b"the owner's own\n")
    reply = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["action"] == "repair" and body["status"] == "repaired" and body["changed"]
    assert sorted(body["restored"]) == sorted(["SKILL.md", extra]) and body["replaced"] == []
    for item in entry["files"]:
        assert (folder / item["path"]).read_bytes() == (VENDOR / entry["path"] / item["path"]).read_bytes()
    assert (folder / "my-notes.md").read_bytes() == b"the owner's own\n"     # not the catalog's
    assert [r["action"] for r in owner.log.rows] == ["skill.repair"]
    assert owner.log.rows[0]["metadata"]["restored"] == body["restored"]
    # Nothing left to do: intact, nothing written, nothing audited.
    again = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True}, headers=ADMIN).json()
    assert again["status"] == "intact" and again["changed"] is False and len(owner.log.rows) == 1
    # A plain install of an installed skill is the same no-op, never a silent overwrite.
    plain = owner.client.post(INSTALL, json={"skill": SKILL}, headers=ADMIN).json()
    assert plain["action"] == "repair" and plain["status"] == "intact"


def test_repair_refuses_local_edits_unless_forced_and_keeps_a_copy(owner, tmp_path):
    folder, entry = _installed(owner)
    edited = b"---\nname: agentmail\ndescription: Use when the owner rewrote it\n---\nMine.\n"
    (folder / "SKILL.md").write_bytes(edited)
    before = _tree(owner.home)
    refused = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True}, headers=ADMIN)
    assert refused.status_code == 409 and refused.json()["reason"] == "local_edits"
    assert refused.json()["files"] == ["SKILL.md"]
    # Installing over it is refused the same way.
    assert owner.client.post(INSTALL, json={"skill": SKILL}, headers=ADMIN).status_code == 409
    assert _tree(owner.home) == before and owner.log.rows == []
    forced = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True, "force": True}, headers=ADMIN)
    assert forced.status_code == 200, forced.text
    body = forced.json()
    assert body["replaced"] == ["SKILL.md"] and body["backed_up"] == ["SKILL.md"]
    assert (folder / "SKILL.md").read_bytes() == (VENDOR / entry["path"] / "SKILL.md").read_bytes()
    copies = list((tmp_path / "repair-backups" / SKILL).rglob("SKILL.md"))
    assert len(copies) == 1 and copies[0].read_bytes() == edited
    assert [r["action"] for r in owner.log.rows] == ["skill.repair"]


def test_repair_never_touches_a_skill_the_catalog_did_not_install(owner, monkeypatch):
    missing = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True}, headers=ADMIN)
    assert missing.status_code == 404 and missing.json()["reason"] == "not_installed"
    # An import of the same slug from another source (DEV_MODE, GitHub): not the catalog's.
    monkeypatch.setattr(web, "DEV_MODE", True)

    async def _fetch(self, client, repo, branch, subdir, slug):
        return _md(SKILL, "Use when another source wrote it")

    monkeypatch.setattr(SkillImporter, "_fetch_skill_md_flat", _fetch)
    assert owner.client.post(IMPORT, json={"source": "someone/repo", "skill": SKILL},
                             headers=ADMIN).status_code == 200
    before = _tree(owner.home)
    for body in ({"skill": SKILL, "repair": True}, {"skill": SKILL, "repair": True, "force": True}):
        reply = owner.client.post(INSTALL, json=body, headers=ADMIN)
        assert reply.status_code == 409 and reply.json()["reason"] in ("not_from_catalog", "exists"), reply.text
    assert _tree(owner.home) == before


def test_repair_follows_a_new_catalog_commit_as_an_update(owner):
    folder, _entry_ = _installed(owner)
    sidecar = folder / "manifest.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["source_commit"] = "0" * 40
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    reply = owner.client.post(INSTALL, json={"skill": SKILL, "repair": True}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["status"] == "updated" and body["changed"] and body["restored"] == []
    assert json.loads(sidecar.read_text(encoding="utf-8"))["source_commit"] == body["commit"]


# ── nerva skills catalog ─────────────────────────────────────────────────────

class _FakeHub:
    def __init__(self, routes):
        self.routes, self.calls, self.base_url = routes, [], "http://127.0.0.1:8080"

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        answer = self.routes[f"{method} {path}"]
        if isinstance(answer, Exception):
            raise answer
        return answer(body) if callable(answer) else answer

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})


def _cli(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def _catalog_hub(**extra):
    listing = hermes_catalog.listing([])
    return _FakeHub({"GET /skills/imported": {"imported": [], "hermes_catalog": listing}, **extra})


def test_cli_browse_is_capped_at_100_and_says_so():
    hub = _catalog_hub()
    code, out, err = _cli(["skills", "catalog"], hub)
    assert code == EXIT_OK, err
    assert "125 installable, 55 carry code, 5 excluded" in out
    assert "showing 100 of 185" in out
    assert sum(1 for line in out.splitlines() if line.startswith("  ") and not line.startswith("   ")) == 100
    code, out, _ = _cli(["skills", "catalog", "--json"], hub)
    data = json.loads(out)
    assert data["matched"] == 185 and data["shown"] == 100 and data["truncated"] is True
    assert _cli(["skills", "catalog", "--limit", "101"], hub)[0] == EXIT_USAGE
    assert _cli(["skills", "catalog", "--limit", "0"], hub)[0] == EXIT_USAGE


def test_cli_browse_searches_and_filters_by_category_and_kind():
    hub = _catalog_hub()
    code, out, _ = _cli(["skills", "catalog", "--search", "AgentMail"], hub)
    assert code == EXIT_OK and "email/agentmail" in out and "needs AGENTMAIL_API_KEY" in out
    assert "showing" not in out
    code, out, _ = _cli(["skills", "catalog", "--category", "mlops", "--json"], hub)
    rows = json.loads(out)["skills"]
    assert rows and all(r["category"] == "mlops" for r in rows)
    code, out, _ = _cli(["skills", "catalog", "--kind", "upstream_only", "--search", WITH_CODE], hub)
    assert "carries code:" in out and "code " in out
    code, out, _ = _cli(["skills", "catalog", "--search", "zz-no-such-thing"], hub)
    assert code == EXIT_OK and "no catalog skill matches" in out
    # Control characters from the hub never reach the terminal.
    hostile = {"imported": [], "hermes_catalog": {"available": True, "commit": "a" * 40, "counts": {},
               "skills": [{"slug": "x", "category": "c", "kind": "instruction",
                           "description": "evil\x1b[31m red"}]}}
    _code, out, _ = _cli(["skills", "catalog"], _FakeHub({"GET /skills/imported": hostile}))
    assert "\x1b" not in out


def test_cli_install_and_repair_go_through_the_owner_route():
    answer = {"ok": True, "action": "install", "status": "installed", "skill": SKILL, "commit": "9c0560f8" * 5,
              "path": "optional-skills/email/agentmail", "audited": True}
    hub = _catalog_hub(**{f"POST {INSTALL}": answer})
    code, out, err = _cli(["skills", "catalog", "install", "email/agentmail"], hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1] == ("POST", INSTALL, {"skill": "email/agentmail", "repair": False, "force": False})
    assert "installed agentmail from the Hermes catalog @9c0560f8" in out
    repaired = {**answer, "action": "repair", "status": "repaired", "restored": ["SKILL.md"],
                "replaced": ["references/a.md"], "backed_up": ["references/a.md"], "backup_dir": "/data/b/agentmail"}
    hub = _catalog_hub(**{f"POST {INSTALL}": repaired})
    code, out, _ = _cli(["skills", "catalog", "repair", SKILL, "--force"], hub)
    assert code == EXIT_OK
    assert hub.calls[-1][2] == {"skill": SKILL, "repair": True, "force": True}
    assert "restored SKILL.md" in out and "replaced your edit of references/a.md" in out
    refused = HubError(409, "the installed files of 'agentmail' were edited; nothing was written")
    hub = _catalog_hub(**{f"POST {INSTALL}": refused})
    code, _out, err = _cli(["skills", "catalog", "repair", SKILL], hub)
    assert code == EXIT_FAILED and "--force" in err
