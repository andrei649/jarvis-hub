"""H024 — ``nerva skills search | check | update | list-modified | reset``.

Search reads the hub's one cross-source search route; check compares each installed pinned
skill with its source's current commit; update repairs catalog skills to the catalog commit
through the owner route (an edited skill refuses, nothing is forced); list-modified diffs
every stock install offline; reset is the catalog repair with --force. Hub text is
sanitised before it reaches the terminal."""

from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from agents.cli import skill_sources as ss
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, command_tree, main
from tests.test_h025_skill_sources_cli import _catalog_install

OLD = "1" * 40
NEW = "2" * 40
SHA = "c" * 64


class FakeHub:
    def __init__(self, gets=None, posts=None):
        self.calls, self.gets, self.posts = [], gets or {}, posts or {}

    def get(self, path):
        self.calls.append(("GET", path, None))
        key = path.split("?", 1)[0]
        return self.gets[key]

    def post(self, path, body=None, **_kw):
        self.calls.append(("POST", path, body))
        reply = self.posts.get((path, body.get("skill"))) if isinstance(body, dict) else None
        reply = reply if reply is not None else self.posts.get(path, {"ok": True})
        if isinstance(reply, Exception):
            raise reply
        return reply


def run_cli(args, hub):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda _env: hub)
    return main(["skills", *args], context=ctx), out.getvalue(), err.getvalue()


def test_command_tree_lists_the_lifecycle_verbs():
    assert {"search", "check", "update", "list-modified", "reset"} <= set(command_tree()["skills"])


def test_search_queries_the_cross_source_route_and_sanitises():
    hub = FakeHub(gets={ss.TAP_SEARCH: {"matched": 2, "results": [
        {"tap": "hermes-catalog", "trust": "official", "slug": "agentmail", "installable": True,
         "description": "mail \x1b]8;;http://evil\x07link"},
        {"tap": "acme--skills", "trust": "community", "slug": "tool", "installable": False,
         "reason": "carries code‮"}]}})
    code, out, err = run_cli(["search", "mail", "--tap", "Acme/Skills", "-n", "5"], hub)
    assert code == EXIT_OK and err == ""
    query = parse_qs(urlsplit(hub.calls[0][1]).query)
    assert query == {"q": ["mail"], "limit": ["5"], "tap": ["acme--skills"]}
    assert "\x1b" not in out and "\x07" not in out and "‮" not in out
    assert "agentmail" in out and "why: carries code" in out


@pytest.mark.parametrize("args", [["search", "-n", "0"], ["search", "x" * 101], ["search", "--tap", "../x"]])
def test_search_refuses_bad_input_before_calling_the_hub(args):
    hub = FakeHub()
    code, _, _ = run_cli(args, hub)
    assert code == EXIT_USAGE and hub.calls == []


def _state(catalog_commit=NEW, tap_commit=NEW):
    taps = {"taps": [
        {"id": "hermes-catalog", "builtin": True, "status": "active", "commit": catalog_commit},
        {"id": "hermes", "builtin": True, "status": "active", "commit": OLD},
        {"id": "acme--skills", "status": "active", "commit": tap_commit, "repo": "acme/skills",
         "path": "skills", "trust": "community"}]}
    imported = {"imported": [
        {"name": "agentmail", "source": "hermes", "source_catalog": "vendored", "source_commit": OLD,
         "content_sha256": SHA, "source_path": "optional-skills/email/agentmail/SKILL.md"},
        {"name": "lint", "source": "acme/skills", "source_repository": "acme/skills", "source_commit": OLD,
         "content_sha256": SHA, "source_path": "skills/lint/SKILL.md"},
        {"name": "pinned", "source": "hermes", "source_repository": "NousResearch/hermes-agent",
         "source_commit": OLD, "content_sha256": SHA, "source_path": "skills/x/pinned/SKILL.md"}]}
    return {ss.TAPS: taps, ss.IMPORTED: imported}


def test_check_lists_skills_behind_their_source():
    code, out, _ = run_cli(["check"], FakeHub(gets=_state()))
    assert code == EXIT_OK
    assert "agentmail" in out and "lint" in out and "pinned" not in out
    assert "nerva skills update" in out and "installing it again" in out
    code, out, _ = run_cli(["check"], FakeHub(gets=_state(catalog_commit=OLD, tap_commit=OLD)))
    assert "every installed pinned skill is at its source's current commit" in out


@pytest.fixture
def local_agentmail(tmp_path, monkeypatch):
    from agents.core.skills import loader

    monkeypatch.setattr(loader, "_writable_skills_dir", lambda: tmp_path)
    return _catalog_install(tmp_path, "agentmail")


def test_update_repairs_only_unedited_catalog_skills_without_force(local_agentmail):
    hub = FakeHub(gets=_state())
    code, out, _ = run_cli(["update"], hub)
    assert code == EXIT_OK
    posts = [c for c in hub.calls if c[0] == "POST"]
    assert posts == [("POST", ss.CATALOG_INSTALL, {"skill": "optional-skills/email/agentmail",
                                                   "repair": True, "force": False})]
    assert "agentmail: updated" in out


def test_update_reports_a_hub_refusal_sanitised(local_agentmail):
    hub = FakeHub(gets=_state(), posts={ss.CATALOG_INSTALL: HubError(409, "local_edits: SKILL.md\x1b[2J")})
    code, out, _ = run_cli(["update", "agentmail"], hub)
    assert code == EXIT_FAILED and "\x1b" not in out and "nerva skills reset" in out
    assert all(c[2]["force"] is False for c in hub.calls if c[0] == "POST")


def test_update_never_restores_a_file_the_owner_deleted(local_agentmail):
    target, _files = local_agentmail
    (target / "references" / "core.md").unlink()
    hub = FakeHub(gets=_state())
    code, out, _ = run_cli(["update"], hub)
    assert code == EXIT_FAILED and "removed" in out and "--force" in out
    assert not [c for c in hub.calls if c[0] == "POST"]
    code, out, _ = run_cli(["update", "--force"], hub)
    assert code == EXIT_OK
    assert [c for c in hub.calls if c[0] == "POST"][-1][2]["force"] is True


def test_update_refuses_a_skill_it_cannot_check_from_here(tmp_path, monkeypatch):
    from agents.core.skills import loader

    monkeypatch.setattr(loader, "_writable_skills_dir", lambda: tmp_path)
    hub = FakeHub(gets=_state())
    code, out, _ = run_cli(["update"], hub)
    assert code == EXIT_FAILED and "cannot be checked" in out
    assert not [c for c in hub.calls if c[0] == "POST"]


def test_update_refuses_a_name_that_is_not_behind():
    hub = FakeHub(gets=_state())
    code, _, err = run_cli(["update", "lint"], hub)
    assert code == EXIT_USAGE and "not a catalog skill behind" in err
    assert not [c for c in hub.calls if c[0] == "POST"]


def test_reset_is_the_forced_catalog_repair():
    hub = FakeHub(posts={ss.CATALOG_INSTALL: {"ok": True, "skill": "agentmail", "commit": NEW,
                                              "action": "repair", "status": "repaired",
                                              "replaced": ["SKILL.md"], "audited": True}})
    code, _, err = run_cli(["reset", "agentmail"], hub)
    assert code == EXIT_FAILED and "--yes" in err and hub.calls == []
    code, out, _ = run_cli(["reset", "agentmail", "--yes"], hub)
    assert code == EXIT_OK
    assert hub.calls == [("POST", ss.CATALOG_INSTALL, {"skill": "agentmail", "repair": True, "force": True})]
    assert "replaced your edit of SKILL.md" in out


def test_list_modified_finds_edited_stock_skills(tmp_path, monkeypatch):
    from agents.core.skills import loader

    target, files = _catalog_install(tmp_path)
    (target / "SKILL.md").write_bytes(files["SKILL.md"] + b"\nedit\n")
    (target / "extra.md").write_text("mine")
    mine = tmp_path / "own-skill"
    mine.mkdir()
    (mine / "SKILL.md").write_text("mine")
    (tmp_path / "linked").symlink_to(target)
    assert ss.installed_stock_folders(tmp_path) == ["antigravity-cli"]
    monkeypatch.setattr(loader, "_writable_skills_dir", lambda: tmp_path)
    code, out, err = run_cli(["list-modified", "--json"], FakeHub())
    assert code == EXIT_OK and err == ""
    data = json.loads(out)
    assert data["modified"] == [{"skill": "antigravity-cli", "source": "hermes-catalog",
                                 "files": {"added": 1, "modified": 1}, "behind": False}]
    (target / "SKILL.md").write_bytes(files["SKILL.md"])
    (target / "extra.md").unlink()
    code, out, _ = run_cli(["list-modified"], FakeHub())
    assert code == EXIT_OK and "no stock skill was edited" in out


def _search_hub(rows, posts=None):
    return FakeHub(gets={ss.TAP_SEARCH: {"matched": len(rows), "results": rows}}, posts=posts)


ROWS = [
    {"tap": "hermes-catalog", "trust": "official", "slug": "agentmail", "installable": True, "commit": NEW,
     "description": "mail", "required_env": ["AGENTMAIL_API_KEY"]},
    {"tap": "acme--skills", "trust": "community", "slug": "agentmail", "installable": True, "commit": OLD},
    {"tap": "acme--skills", "trust": "community", "slug": "lint", "installable": True, "commit": OLD,
     "injection_flags": ["ignore previous\x1b[2J"], "carries_code": True},
    {"tap": "acme--skills", "trust": "community", "slug": "runner", "installable": False,
     "reason": "invalid_index_entry"},
]


def test_install_from_a_tap_goes_through_the_tap_install_route():
    hub = _search_hub(ROWS, posts={ss.TAP_INSTALL: {"ok": True, "setup": {"missing": ["LINT_TOKEN"]}}})
    code, out, err = run_cli(["install", "lint"], hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1] == ("POST", ss.TAP_INSTALL, {"tap": "acme--skills", "skill": "lint"})
    assert "quarantined" in out and "still needs: LINT_TOKEN" in out


def test_install_from_the_catalog_uses_the_catalog_route():
    hub = _search_hub(ROWS, posts={ss.CATALOG_INSTALL: {"ok": True, "skill": "agentmail", "commit": NEW,
                                                        "action": "install", "path": "x", "audited": True}})
    code, out, _ = run_cli(["install", "agentmail", "--from", "hermes-catalog"], hub)
    assert code == EXIT_OK
    assert parse_qs(urlsplit(hub.calls[0][1]).query)["tap"] == ["hermes-catalog"]
    assert hub.calls[-1] == ("POST", ss.CATALOG_INSTALL, {"skill": "agentmail", "repair": False, "force": False})


def test_install_asks_which_source_and_refuses_what_is_not_installable():
    hub = _search_hub(ROWS)
    code, _, err = run_cli(["install", "agentmail"], hub)
    assert code == EXIT_FAILED and "choose one with --from" in err
    code, _, err = run_cli(["install", "runner"], hub)
    assert code == EXIT_FAILED and "invalid_index_entry" in err
    code, _, err = run_cli(["install", "../x"], hub)
    assert code == EXIT_USAGE
    assert not [c for c in hub.calls if c[0] == "POST"]


def test_inspect_shows_the_preview_sanitised_and_writes_nothing():
    hub = _search_hub(ROWS)
    code, out, _ = run_cli(["inspect", "lint"], hub)
    assert code == EXIT_OK and "flagged: ignore previous" in out and "\x1b" not in out
    assert "carries code" in out and not [c for c in hub.calls if c[0] == "POST"]
