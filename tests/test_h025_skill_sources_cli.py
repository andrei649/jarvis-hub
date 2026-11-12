"""H025 — ``nerva skills tap | snapshot | diff``.

Taps go through the hub's admin taps routes (adding one only queues the irreversible-tier
card); a snapshot import replays each install through that skill's own install route, never
bulk-approving; ``diff`` compares an edited stock skill with its stock copy offline. Every
local read is bounded and refuses links and special files; hub text is sanitised."""

from __future__ import annotations

import io
import json
import os
import stat
import threading

import pytest

from agents.cli import skill_sources as ss
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, command_tree, main
from agents.core.skills import hermes_catalog

COMMIT = "a" * 40
OTHER = "b" * 40
SHA = "c" * 64
SHA2 = "d" * 64


class FakeHub:
    def __init__(self, taps=None, imported=None, replies=None, after_install=None):
        self.calls = []
        self.taps = taps if taps is not None else []
        self.imported = imported if imported is not None else []
        self.replies = replies or {}
        self.after_install = after_install

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path == ss.TAPS:
            return {"taps": self.taps}
        if path == ss.IMPORTED:
            return {"imported": self.imported}
        raise AssertionError(path)

    def post(self, path, body=None, **_kw):
        self.calls.append(("POST", path, body))
        reply = self.replies.get(path)
        if isinstance(reply, Exception):
            raise reply
        if path in (ss.CATALOG_INSTALL, ss.TAP_INSTALL, ss.OPTIONAL_INSTALL) and self.after_install:
            self.after_install(path, body)
        if reply is not None:
            return reply
        if path == ss.TAPS:
            return {"ok": True, "status": "pending_approval", "task_id": 41, "tap": {}}
        if path == ss.OPTIONAL_INSTALL:
            return {"status": "installed_review_required", "name": body["name"]}
        return {"ok": True}

    def request(self, method, path, body=None, **_kw):
        self.calls.append((method, path, body))
        return self.replies.get(path, {"ok": True, "removed": True})

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


def run_cli(args, hub=None, stdin=None):
    hub = hub or FakeHub()
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=stdin or io.StringIO(""), client_factory=lambda _env: hub)
    code = main(["skills", *args], context=ctx)
    return code, out.getvalue(), err.getvalue(), hub


BUILTINS = [
    {"id": "hermes-catalog", "builtin": True, "trust": "official", "status": "active",
     "repo": "NousResearch/hermes-agent", "commit": COMMIT, "skills": 3},
    {"id": "hermes", "builtin": True, "trust": "official", "status": "active",
     "repo": "NousResearch/hermes-agent", "commit": OTHER, "skills": 2},
]


def test_command_tree_lists_the_three_verbs():
    assert {"tap", "snapshot", "diff"} <= set(command_tree()["skills"])


# ── taps ────────────────────────────────────────────────────────────────────────

def test_tap_list_sanitises_hub_text():
    hub = FakeHub(taps=[*BUILTINS, {"id": "acme--skills\x1b[2J", "builtin": False, "trust": "community",
                                    "status": "active‮", "repo": "acme/skills", "commit": COMMIT,
                                    "path": "skills", "skills": 4}])
    code, out, err, _ = run_cli(["tap", "list"], hub)
    assert code == EXIT_OK and err == ""
    assert "\x1b" not in out and "‮" not in out
    assert "acme--skills" in out and "4 skills" in out


def test_tap_list_json_escapes_non_ascii():
    hub = FakeHub(taps=[{"id": "x--y", "repo": "x/y​"}])
    code, out, _, _ = run_cli(["tap", "list", "--json"], hub)
    assert code == EXIT_OK and "​" not in out and json.loads(out)["taps"][0]["repo"] == "x/y​"


@pytest.mark.parametrize("args", [
    ["tap", "add", "acme/skills", "--commit", "main"],
    ["tap", "add", "acme/skills", "--commit", COMMIT.upper()],
    ["tap", "add", "acme", "--commit", COMMIT],
    ["tap", "add", "acme/skills", "--commit", COMMIT, "--path", "../etc"],
])
def test_tap_add_refuses_moving_or_malformed_sources_before_calling_the_hub(args):
    code, _, err, hub = run_cli(args)
    assert code == EXIT_USAGE and err and hub.calls == []


def test_tap_add_only_queues_the_approval_card():
    code, out, err, hub = run_cli(["tap", "add", "Acme/Skills", "--commit", COMMIT, "--trust", "trusted"])
    assert code == EXIT_OK and err == ""
    assert hub.calls == [("POST", ss.TAPS, {"repo": "Acme/Skills", "commit": COMMIT, "path": "skills",
                                            "trust": "trusted"})]
    assert "approval pending #41" in out and "nerva skills tap refresh acme--skills" in out


def test_tap_add_without_a_card_is_a_failure():
    hub = FakeHub(replies={ss.TAPS: {"ok": True, "status": "active"}})
    code, _, err, _ = run_cli(["tap", "add", "acme/skills", "--commit", COMMIT], hub)
    assert code == EXIT_FAILED and "not confirmed" in err


def test_tap_remove_and_refresh_use_the_tap_routes():
    code, out, _, hub = run_cli(["tap", "remove", "Acme/Skills"])
    assert code == EXIT_OK and hub.calls == [("DELETE", "/api/skills/taps/acme--skills", None)]
    assert "stay installed" in out
    hub = FakeHub(replies={"/api/skills/taps/acme--skills/refresh": {"ok": True, "tap": {"skills": 3, "refused": 1}}})
    code, out, _, hub = run_cli(["tap", "refresh", "acme--skills"], hub)
    assert code == EXIT_OK and hub.calls == [("POST", "/api/skills/taps/acme--skills/refresh", {})]
    assert "3 installable skills, 1 refused" in out


def test_tap_remove_refuses_a_bad_identifier():
    code, _, err, hub = run_cli(["tap", "remove", "../../api/admin"])
    assert code == EXIT_USAGE and hub.calls == []


# ── snapshot export ─────────────────────────────────────────────────────────────

IMPORTED = [
    {"name": "agentmail", "source": "hermes", "source_catalog": "vendored", "source_commit": COMMIT,
     "content_sha256": SHA, "source_path": "optional-skills/email/agentmail/SKILL.md"},
    {"name": "lint", "source": "acme/skills", "source_repository": "acme/skills", "source_commit": COMMIT,
     "content_sha256": SHA2, "source_path": "skills/lint/SKILL.md"},
    {"name": "email_triage", "source": "nerva-optional", "content_sha256": SHA,
     "source_path": "optional-skills/email_triage/SKILL.md"},
    {"name": "mine", "source": "local", "imported": True},
]
TAP_ROW = {"id": "acme--skills", "builtin": False, "trust": "community", "status": "active",
           "repo": "acme/skills", "commit": COMMIT, "path": "skills"}


def test_build_snapshot_records_pins_and_names_what_it_cannot_export():
    snap = ss.build_snapshot({"imported": IMPORTED}, {"taps": [*BUILTINS, TAP_ROW]}, now=0)
    kinds = {(s["kind"], s["slug"]) for s in snap["skills"]}
    assert kinds == {("catalog", "agentmail"), ("tap", "lint"), ("optional", "email_triage")}
    assert snap["taps"] == [{"id": "acme--skills", "repo": "acme/skills", "commit": COMMIT, "path": "skills",
                             "trust": "community"}]
    assert [row["name"] for row in snap["not_exported"]] == ["mine"]
    # Round trip: what export writes, import reads.
    parsed = ss.parse_snapshot(json.dumps(snap).encode())
    assert {s["kind"] for s in parsed["skills"]} == {"catalog", "tap", "optional"}


def test_export_writes_a_private_file(tmp_path):
    target = tmp_path / "skills.json"
    code, out, err, _ = run_cli(["snapshot", "export", str(target)],
                                FakeHub(taps=[*BUILTINS, TAP_ROW], imported=IMPORTED))
    assert code == EXIT_OK and err == "", err
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert json.loads(target.read_text())["format"] == ss.SNAPSHOT_FORMAT
    assert "3 skill(s), 1 tap(s)" in out and "not exported: mine" in out


def test_export_never_writes_through_a_link(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "out.json"
    link.symlink_to(victim)
    code, _, err, _ = run_cli(["snapshot", "export", str(link)], FakeHub(taps=BUILTINS))
    assert code == EXIT_FAILED and "not a regular file" in err
    assert victim.read_text() == "keep" and link.is_symlink()


# ── snapshot import: reading the file ───────────────────────────────────────────

def _snapshot(skills=None, taps=None):
    return {"format": ss.SNAPSHOT_FORMAT, "version": 1,
            "skills": skills if skills is not None else [], "taps": taps if taps is not None else []}


@pytest.mark.parametrize("data,needle", [
    ({"format": "other"}, "not a nerva skills snapshot"),
    ({**_snapshot(), "version": 2}, "not supported"),
    (_snapshot(skills=[{"kind": "tap", "slug": "x", "tap": "acme--skills", "commit": COMMIT,
                        "content_sha256": SHA}]), "does not list"),
    (_snapshot(skills=[{"kind": "tap", "slug": "x", "tap": "acme--skills", "commit": OTHER,
                        "content_sha256": SHA}],
               taps=[{"repo": "acme/skills", "commit": COMMIT, "path": "skills", "trust": "community"}]),
     "different commits"),
    (_snapshot(taps=[{"repo": "acme/skills", "commit": COMMIT, "path": "skills", "trust": "official"}]),
     "a tap entry"),
    (_snapshot(taps=[{"repo": "NousResearch/hermes", "commit": COMMIT, "path": "skills",
                      "trust": "community"}] * 2), "listed twice"),
    (_snapshot(skills=[{"kind": "catalog", "slug": "x", "identifier": "../x", "commit": COMMIT,
                        "content_sha256": SHA}]), "catalog path"),
    (_snapshot(skills=[{"kind": "optional", "slug": "../x", "content_sha256": SHA}]), "optional"),
    (_snapshot(skills=[{"kind": "script", "slug": "x"}]), "no kind"),
])
def test_parse_snapshot_refuses_what_it_cannot_trust(data, needle):
    with pytest.raises(ss.SnapshotError, match=needle):
        ss.parse_snapshot(json.dumps(data).encode())


def test_read_regular_file_bounds_and_refuses_special_files(tmp_path):
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * 11)
    with pytest.raises(OSError, match="larger"):
        ss.read_regular_file(str(big), 10)
    assert ss.read_regular_file(str(big), 11) == b"x" * 11
    link = tmp_path / "link.json"
    link.symlink_to(big)
    with pytest.raises(OSError):
        ss.read_regular_file(str(link), 100)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    done = []

    def read_fifo():
        try:
            ss.read_regular_file(str(fifo), 100)
        except OSError:
            done.append("refused")

    worker = threading.Thread(target=read_fifo, daemon=True)
    worker.start()
    worker.join(5)
    assert done == ["refused"], "reading a FIFO blocked or was not refused"


def test_import_refuses_a_fifo_without_blocking(tmp_path):
    fifo = tmp_path / "snap.json"
    os.mkfifo(fifo)
    code, _, err, hub = run_cli(["snapshot", "import", str(fifo), "--yes"])
    assert code == EXIT_USAGE and "not a regular file" in err and hub.calls == []


# ── snapshot import: replaying it ───────────────────────────────────────────────

FULL = _snapshot(
    skills=[{"kind": "catalog", "slug": "agentmail", "identifier": "optional-skills/email/agentmail",
             "commit": COMMIT, "content_sha256": SHA},
            {"kind": "tap", "slug": "lint", "tap": "acme--skills", "commit": COMMIT, "content_sha256": SHA2},
            {"kind": "optional", "slug": "email_triage", "content_sha256": SHA},
            {"kind": "catalog", "slug": "old", "identifier": "skills/x/old", "commit": OTHER,
             "content_sha256": SHA}],
    taps=[{"repo": "acme/skills", "commit": COMMIT, "path": "skills", "trust": "community"}])


def _write(tmp_path, data):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_import_plan_requests_missing_taps_and_waits_for_them(tmp_path):
    def installed(path, body):
        if path == ss.CATALOG_INSTALL:
            hub.imported.append({"source": "hermes", "content_sha256": SHA, "source_commit": COMMIT})
        if path == ss.OPTIONAL_INSTALL:
            hub.imported.append({"source": "nerva-optional", "content_sha256": SHA,
                                 "source_path": "optional-skills/email_triage/SKILL.md"})

    hub = FakeHub(taps=BUILTINS, after_install=installed)
    code, out, err, hub = run_cli(["snapshot", "import", _write(tmp_path, FULL), "--yes"], hub)
    assert code == EXIT_OK, (out, err)
    writes = hub.writes()
    # The tap is only *requested* (a card); the file never trusts it.
    assert ("POST", ss.TAPS, {"repo": "acme/skills", "commit": COMMIT, "path": "skills",
                              "trust": "community"}) in writes
    assert ("POST", ss.CATALOG_INSTALL, {"skill": "optional-skills/email/agentmail"}) in writes
    assert ("POST", ss.OPTIONAL_INSTALL, {"name": "email_triage"}) in writes
    # Nothing is installed from a tap that is not trusted yet, nor from another catalog commit.
    assert not any(path == ss.TAP_INSTALL for _, path, _ in writes)
    assert "lint" in out and "needs your approval card" in out
    assert "this hub's catalog is @" in out
    assert "2 installed, 1 waiting for a tap, 1 skipped, 0 failed" in out


def test_import_installs_from_an_approved_tap_and_skips_what_is_installed(tmp_path):
    hub = FakeHub(taps=[*BUILTINS, TAP_ROW],
                  imported=[{"source": "hermes", "content_sha256": SHA, "source_commit": COMMIT},
                            {"source": "nerva-optional", "content_sha256": SHA2,
                             "source_path": "optional-skills/email_triage/SKILL.md"}])
    hub.after_install = lambda path, body: hub.imported.append(
        {"source": "acme/skills", "content_sha256": SHA2, "source_commit": COMMIT})
    code, out, _, hub = run_cli(["snapshot", "import", _write(tmp_path, FULL), "--yes"], hub)
    assert code == EXIT_OK, out
    assert hub.writes() == [("POST", ss.TAP_INSTALL, {"tap": "acme--skills", "skill": "lint"})]
    assert "installed here already" in out


def test_import_reports_a_hub_that_installed_other_bytes(tmp_path):
    hub = FakeHub(taps=[*BUILTINS, TAP_ROW])
    data = _snapshot(skills=[FULL["skills"][1]], taps=FULL["taps"])
    code, out, _, _ = run_cli(["snapshot", "import", _write(tmp_path, data), "--yes"], hub)
    assert code == EXIT_FAILED and "mismatch" in out


def test_import_counts_a_refused_install_as_failed(tmp_path):
    hub = FakeHub(taps=BUILTINS, replies={ss.CATALOG_INSTALL: HubError(409, "local_edits\x1b[31m")})
    data = _snapshot(skills=[FULL["skills"][0]])
    code, out, _, _ = run_cli(["snapshot", "import", _write(tmp_path, data), "--yes"], hub)
    assert code == EXIT_FAILED and "failed" in out and "\x1b" not in out


def test_import_dry_run_and_no_terminal_change_nothing(tmp_path):
    path = _write(tmp_path, FULL)
    code, out, _, hub = run_cli(["snapshot", "import", path, "--dry-run"], FakeHub(taps=BUILTINS))
    assert code == EXIT_OK and hub.writes() == [] and "request a card for acme/skills" in out
    code, _, err, hub = run_cli(["snapshot", "import", path], FakeHub(taps=BUILTINS))
    assert code == EXIT_FAILED and "--yes" in err and hub.writes() == []


def test_import_asks_on_a_terminal(tmp_path):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    code, out, _, hub = run_cli(["snapshot", "import", _write(tmp_path, FULL)], FakeHub(taps=BUILTINS),
                                stdin=Tty("n\n"))
    assert code == EXIT_FAILED and "Go ahead?" in out and hub.writes() == []


# ── diff ────────────────────────────────────────────────────────────────────────

def _catalog_install(skills_dir, slug="antigravity-cli"):
    catalog = hermes_catalog.load()
    entry = hermes_catalog.resolve(catalog, slug)
    files = hermes_catalog.verified_files(catalog, entry)
    target = skills_dir / entry["slug"]
    for rel, data in files.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_bytes(data)
    record = {"imported": True, "source": hermes_catalog.INSTALL_SOURCE,
              **hermes_catalog.provenance(catalog, entry, files)}
    (target / "manifest.json").write_text(json.dumps(record))
    (target / "PENDING_REVIEW").write_text("quarantined\n")
    return target, files


def test_diff_unmodified_catalog_skill(tmp_path):
    _catalog_install(tmp_path)
    result = ss.diff_installed_skill(tmp_path, "autonomous-ai-agents/antigravity-cli")
    assert result["ok"] and result["modified"] is False and result["source"] == "hermes-catalog"


def test_diff_shows_edits_additions_removals_and_links(tmp_path):
    target, files = _catalog_install(tmp_path)
    (target / "SKILL.md").write_bytes(files["SKILL.md"] + b"\nmy own line \x1b]0;pwned\x07\n")
    (target / "references" / "cli-docs.md").unlink()
    (target / "references" / "cli-docs.md").symlink_to("/etc/hostname")
    (target / "notes.md").write_text("mine\n")
    result = ss.diff_installed_skill(tmp_path, "antigravity-cli")
    status = {f["path"]: f["status"] for f in result["files"]}
    assert status == {"SKILL.md": "modified", "references/cli-docs.md": "not_plain", "notes.md": "added"}
    code, out, err, _ = _run_diff(tmp_path, "antigravity-cli")
    assert code == EXIT_OK and err == ""
    assert "+my own line" in out and "\x1b" not in out and "\x07" not in out
    assert "nerva skills catalog repair antigravity-cli --force" in out


def _run_diff(skills_dir, name):
    from agents.core.skills import loader

    original = loader._writable_skills_dir
    loader._writable_skills_dir = lambda: skills_dir
    try:
        return run_cli(["diff", name])
    finally:
        loader._writable_skills_dir = original


def test_diff_refuses_a_skill_the_catalog_did_not_write(tmp_path):
    (tmp_path / "antigravity-cli").mkdir()
    (tmp_path / "antigravity-cli" / "SKILL.md").write_text("mine")
    result = ss.diff_installed_skill(tmp_path, "antigravity-cli")
    assert result == {"ok": False, "reason": "this folder was not written by a catalog install of that skill"}
    assert ss.diff_installed_skill(tmp_path, "no-such-skill")["ok"] is False
    code, _, err, _ = _run_diff(tmp_path, "antigravity-cli")
    assert code == EXIT_FAILED and "not written by a catalog install" in err


def test_diff_compares_a_nerva_optional_skill_with_its_shipped_copy(tmp_path):
    stock = tmp_path / "optional" / "email_triage"
    stock.mkdir(parents=True)
    (stock / "SKILL.md").write_text("---\nname: email_triage\n---\nstock\n")
    skills = tmp_path / "skills"
    mine = skills / "email_triage"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("---\nname: email_triage\n---\nedited\n")
    (mine / "PENDING_REVIEW").write_text("x")
    (mine / "manifest.json").write_text(json.dumps({
        "name": "email_triage", "source": "nerva-optional", "imported": True,
        "source_path": "optional-skills/email_triage/SKILL.md"}))
    result = ss.diff_installed_skill(skills, "email_triage", optional_root=tmp_path / "optional")
    assert result["ok"] and result["source"] == "nerva-optional"
    assert [(f["path"], f["status"]) for f in result["files"]] == [("SKILL.md", "modified")]
    assert "-stock" in result["files"][0]["diff"] and "+edited" in result["files"][0]["diff"]


def test_diff_does_not_read_a_manifest_that_is_a_fifo(tmp_path):
    mine = tmp_path / "skills" / "email_triage"
    mine.mkdir(parents=True)
    os.mkfifo(mine / "manifest.json")
    result = ss.diff_installed_skill(tmp_path / "skills", "email_triage", optional_root=tmp_path)
    assert result["ok"] is False and "not a stock skill" in result["reason"]
