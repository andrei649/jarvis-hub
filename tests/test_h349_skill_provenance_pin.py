"""H349 — where each skill came from, and the owner's pin.

Hermes keeps a per-skill usage sidecar with counters, lifecycle state and provenance
(agent-created, hub-installed, bundled), and ``hermes curator pin|unpin``. Nerva's sidecar
(``agents/core/skills/usage.py``) already counted use/view/patch and recorded ``agent``;
these tests pin the rest of the row:

- the origin of an imported, a marketplace-installed, a locally migrated and a shipped
  skill is recorded when the loader registers it (the one step every install path crosses,
  including an install made while the hub was down), read from the install record in the
  skill's own folder;
- ``POST /api/skills/pin`` (admin), ``nerva skills pin|unpin`` and the listing carry the
  pin; the sidecar itself refuses a pin the route would refuse, and a write that fails
  changes nothing;
- a pinned skill is not deleted by a skill batch.

Everything here runs the real loader, importer, marketplace, sidecar and routes over temp
folders; only the network fetch of an import and the hub transport of the CLI are doubles.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main  # noqa: E402
from agents.core import settings_db  # noqa: E402
from agents.core.routers import skills as skills_router  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import usage as usage_mod  # noqa: E402
from agents.core.skills.approval import SkillApprovalStore  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.importer import SkillImporter  # noqa: E402
from agents.core.skills.loader import SkillLoader  # noqa: E402
from agents.core.skills.marketplace import SkillMarketplace  # noqa: E402
from agents.core.skills.usage import SkillUsageStore  # noqa: E402
from tests.test_h046_journey import _AppHub  # noqa: E402

ADMIN = {"X-Admin-Token": "t"}
PIN = "/api/skills/pin"


def _md(name: str, description: str | None = None) -> str:
    return f"---\nname: {name}\ndescription: {description or 'Use when testing ' + name}\n---\n## Steps\n\nDo it.\n"


class _Log:
    def __init__(self):
        self.rows = []

    def record(self, **row):
        self.rows.append(row)


@pytest.fixture
def hub(tmp_path, monkeypatch):
    for name in ("JARVIS_SKILL_SIGNING_KEY", "JARVIS_REQUIRE_SIGNED_SKILLS", "JARVIS_REQUIRE_REVIEWED_SKILLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    shipped = tmp_path / "skills"
    shipped.mkdir()
    # One skill exactly as Nerva ships it: it loads as bundled by its bytes.
    shutil.copytree(repo_root / "skills" / "weather", shipped / "weather")
    home = tmp_path / "home" / "skills"
    home.mkdir(parents=True)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", shipped)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: home)
    monkeypatch.setattr(skills_router, "_batch_archive", lambda: tmp_path / "skill-archive")
    approvals = SkillApprovalStore(tmp_path / "skill_approvals.json")
    sidecar = tmp_path / "skill_usage.json"
    log = _Log()
    ns = SimpleNamespace(tmp=tmp_path, shipped=shipped, home=home, sidecar=sidecar, log=log, approvals=approvals)

    def boot():
        """A hub start: discover the skills, then attach the sidecar (the orchestrator's order)."""
        ns.loader = SkillLoader(approval_store=approvals)
        ns.loader.discover()
        ns.usage = SkillUsageStore(sidecar)
        ns.loader.attach_usage(ns.usage)
        ns.orch = SimpleNamespace(
            skills=ns.loader, skill_usage=ns.usage, intent_log=log,
            skill_importer=SkillImporter(skills_dir=str(home)),
            marketplace=SkillMarketplace(skills_dir=str(home), db_path=str(tmp_path / "market.db")))
        monkeypatch.setattr(web, "orch", ns.orch)
        return ns

    def write(folder, name=None):
        path = home / folder
        path.mkdir(parents=True)
        (path / "SKILL.md").write_bytes(_md(name or folder).encode())
        return path

    def named(folder):
        """The registered name of the skill loaded from ``folder``."""
        return next(n for n, s in ns.loader.skills.items() if Path(s.path).name == folder)

    def on_disk():
        return json.loads(sidecar.read_text(encoding="utf-8"))["skills"]

    def listing():
        reply = ns.client.get("/skills", headers=ADMIN)
        assert reply.status_code == 200, reply.text
        return reply.json()["skills"]

    ns.boot, ns.write, ns.named, ns.on_disk, ns.listing = boot, write, named, on_disk, listing
    monkeypatch.setattr(web, "ADMIN_TOKEN", "t")
    ns.client = TestClient(web.app)
    return ns


def _cli(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    app_hub = _AppHub(hub.client)
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: app_hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), app_hub


def _zip(name: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", _md(name))
    return base64.b64encode(buf.getvalue()).decode()


# ── origin: every way a skill gets installed ─────────────────────────────────────────

def test_a_shipped_and_a_hand_written_skill_are_recorded_at_start(hub):
    hub.write("my-notes")
    hub.boot()
    rows = hub.listing()
    assert rows["Weather Intel"]["usage"]["origin"] == "bundled"
    assert rows["Weather Intel"]["usage"]["source"] == "" and rows["Weather Intel"]["usage"]["pinnable"] is False
    mine = rows[hub.named("my-notes")]["usage"]
    # No install record and no agent marker: not claimed as shipped, imported or agent-made.
    assert (mine["origin"], mine["source"], mine["pinnable"], mine["pinned"]) == ("local", "", True, False)
    # Recorded in the sidecar file, not only answered from memory.
    disk = hub.on_disk()
    assert disk["Weather Intel"]["origin"] == "bundled" and disk[hub.named("my-notes")]["origin"] == "local"


async def test_an_imported_skill_records_import_and_its_source(hub):
    hub.boot()
    assert await hub.orch.skill_importer._save_skill("meeting-notes", "hermes", skill_md_text=_md("meeting-notes"))
    hub.loader.discover()                                  # what POST /skills/import does next
    usage = hub.listing()[hub.named("meeting-notes")]["usage"]
    assert (usage["origin"], usage["source"]) == ("import", "hermes")
    assert hub.on_disk()[hub.named("meeting-notes")]["origin"] == "import"
    assert hub.usage.curatable(hub.named("meeting-notes")) is False


def test_the_import_route_records_the_origin(hub, monkeypatch):
    hub.boot()
    monkeypatch.setattr(web, "DEV_MODE", True)

    async def _fetch(self, client, repo, branch, subdir, slug):    # the network, and only that
        return _md(slug)

    monkeypatch.setattr(SkillImporter, "_fetch_skill_md_flat", _fetch)
    reply = hub.client.post("/skills/import", json={"source": "openclaw", "skill": "trip-planner"}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    usage = hub.listing()[hub.named("trip-planner")]["usage"]
    assert (usage["origin"], usage["source"]) == ("import", "openclaw")


def test_a_marketplace_install_records_import_from_the_marketplace(hub):
    hub.boot()
    reply = hub.client.post("/api/skills/marketplace/install-zip", json={"zip_base64": _zip("market-tool")},
                            headers=ADMIN)
    assert reply.status_code == 200, reply.text
    usage = hub.listing()[hub.named("market-tool")]["usage"]
    assert (usage["origin"], usage["source"]) == ("import", "marketplace")
    assert hub.on_disk()[hub.named("market-tool")]["source"] == "marketplace"


async def test_a_local_migration_import_records_the_install_it_came_from(hub):
    hub.boot()
    source = hub.tmp / "claude" / "skills" / "pdf-tools"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(_md("pdf-tools").encode())
    result = await hub.orch.skill_importer.import_local_skill(source, "claude-code")
    assert result["status"] == "imported", result
    hub.loader.discover()
    usage = hub.listing()[hub.named(result["slug"])]["usage"]
    assert (usage["origin"], usage["source"]) == ("import", "claude-code")


async def test_a_skill_installed_while_the_hub_was_down_is_recorded_at_the_next_start(hub):
    hub.boot()
    # `nerva import` writes the skills tree with no hub running: nothing calls the sidecar.
    assert await SkillImporter(skills_dir=str(hub.home))._save_skill(
        "offline-skill", "acme-skills", skill_md_text=_md("offline-skill"))
    assert "offline-skill" not in json.dumps(hub.on_disk())
    hub.boot()
    row = hub.on_disk()[hub.named("offline-skill")]
    assert (row["origin"], row["source"]) == ("import", "acme-skills")      # a bare repository name


def test_an_agent_made_skill_keeps_its_marker_beside_an_install_record(hub):
    hub.boot()
    hub.loader.generate_skill("jarvis", "tidy the meeting notes", ["open the notes", "tidy them"])
    name = next(n for n in hub.loader.skills if "tidy" in n.lower())
    assert hub.listing()[name]["usage"]["origin"] == "agent"
    hub.boot()                                             # a restart re-reads the folders
    assert hub.listing()[name]["usage"]["origin"] == "agent" and hub.usage.curatable(name)
    # An install record that appears in its folder is shown, and the agent marker stays:
    # nothing written into the folder takes the skill out of curation or the journey
    # (review M2). No install path writes there: see tests/test_h349_review_fixes.py.
    folder = Path(hub.loader.skills[name].path)
    (folder / loader_mod.EXTERNAL_SOURCE_MARKER).write_text("source=marketplace\n", encoding="utf-8")
    hub.loader.discover()
    usage = hub.listing()[name]["usage"]
    assert (usage["origin"], usage["source"], usage["agent_created"]) == ("import", "marketplace", True)
    assert hub.usage.curatable(name) is True


def test_a_row_left_from_before_is_corrected_and_an_unregistered_name_is_not_claimed(hub):
    hub.write("my-notes")
    # The sidecar as the old default wrote it: every row "bundled", whatever the skill was.
    hub.sidecar.write_text(json.dumps({"skills": {
        "my-notes": {"origin": "bundled", "use_count": 4, "pinned": False, "state": "active"},
        "gone-skill": {"origin": "import", "use_count": 1, "pinned": False, "state": "active"}}}), encoding="utf-8")
    hub.boot()
    assert hub.named("my-notes") == "my-notes"
    usage = hub.listing()["my-notes"]["usage"]
    assert (usage["origin"], usage["use_count"]) == ("local", 4)        # corrected, counters kept
    assert hub.on_disk()["gone-skill"]["origin"] == "import"            # not installed: left alone
    # A counter bumped under a name no skill is registered for claims nothing about it.
    hub.usage.bump("never-installed", "view")
    assert hub.usage.get("never-installed")["origin"] == "unknown"
    assert usage_mod.usage_summary(hub.usage, "nobody")["origin"] == "unknown"
    assert usage_mod.usage_summary(None, "nobody")["pinnable"] is False


def test_the_source_label_is_display_text_and_never_a_path_or_markup(hub):
    folder = hub.write("odd-source")
    (folder / "manifest.json").write_text(json.dumps(
        {"imported": True, "source": "<img src=x onerror=alert(1)>\n/etc/passwd " + "x" * 200}), encoding="utf-8")
    hub.boot()
    usage = hub.listing()[hub.named("odd-source")]["usage"]
    assert (usage["origin"], usage["source"]) == ("import", "")
    assert hub.on_disk()[hub.named("odd-source")]["source"] == ""


def test_starting_twice_writes_the_sidecar_once(hub):
    hub.write("my-notes")
    hub.boot()
    first = hub.sidecar.read_bytes()
    stamp = hub.sidecar.stat().st_mtime_ns
    hub.boot()
    hub.loader.discover()
    assert hub.sidecar.read_bytes() == first and hub.sidecar.stat().st_mtime_ns == stamp


# ── the pin ──────────────────────────────────────────────────────────────────────────

def test_the_owner_pins_and_unpins_through_the_route(hub):
    hub.write("my-notes")
    hub.boot()
    name = hub.named("my-notes")
    reply = hub.client.post(PIN, json={"skill": "my-notes", "pinned": True}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert (body["ok"], body["skill"], body["pinned"], body["changed"], body["audited"]) == (True, name, True, True, True)
    assert body["usage"]["pinned"] is True
    assert hub.on_disk()[name]["pinned"] is True                       # on disk
    assert hub.listing()[name]["usage"]["pinned"] is True              # and in the listing
    assert SkillUsageStore(hub.sidecar).curatable(name) is False       # a restart keeps it
    assert [(r["action"], r["actor"], r["metadata"]["skill"]) for r in hub.log.rows] == [("skill.pin", "owner", name)]
    # Again: nothing changes and nothing new is logged.
    again = hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN).json()
    assert (again["changed"], again["pinned"]) == (False, True) and len(hub.log.rows) == 1
    off = hub.client.post(PIN, json={"skill": name, "pinned": False}, headers=ADMIN).json()
    assert (off["changed"], off["pinned"]) == (True, False)
    assert hub.on_disk()[name]["pinned"] is False
    assert [r["action"] for r in hub.log.rows] == ["skill.pin", "skill.unpin"]


def test_the_pin_route_is_for_an_admin_and_checks_what_it_is_given(hub, monkeypatch):
    hub.write("my-notes")
    hub.boot()
    name = hub.named("my-notes")
    monkeypatch.setattr(web, "USER_TOKEN", "u")
    assert hub.client.post(PIN, json={"skill": name, "pinned": True}).status_code in (401, 403)
    guest = hub.client.post(PIN, json={"skill": name, "pinned": True}, headers={"X-User-Token": "u"})
    assert guest.status_code in (401, 403)
    assert hub.on_disk()[name]["pinned"] is False and hub.log.rows == []
    for bad in ({"skill": name}, {"pinned": True}, {"skill": "", "pinned": True},
                {"skill": "x" * 129, "pinned": True}, {"skill": name, "pinned": "maybe"},
                {"skill": name, "pinned": True, "origin": "agent"}):
        assert hub.client.post(PIN, json=bad, headers=ADMIN).status_code == 422, bad
    missing = hub.client.post(PIN, json={"skill": "../../etc/passwd", "pinned": True}, headers=ADMIN)
    assert missing.status_code == 404 and missing.json()["reason"] == "not_found"
    shipped = hub.client.post(PIN, json={"skill": "Weather Intel", "pinned": True}, headers=ADMIN)
    assert shipped.status_code == 409 and shipped.json()["reason"] == "not_pinnable"
    assert "ships with Nerva" in shipped.json()["error"]
    assert hub.on_disk()["Weather Intel"]["pinned"] is False
    assert "../../etc/passwd" not in hub.on_disk() and hub.log.rows == []


def test_the_sidecar_itself_refuses_what_the_route_refuses(hub):
    hub.write("my-notes")
    hub.boot()
    with pytest.raises(usage_mod.PinRefused) as ghost:
        hub.usage.pin("ghost")
    assert ghost.value.reason == "not_found" and hub.usage.get("ghost") is None
    with pytest.raises(usage_mod.PinRefused) as shipped:
        hub.usage.pin("Weather Intel")
    assert shipped.value.reason == "not_pinnable" and hub.usage.get("Weather Intel")["pinned"] is False
    # A row a counter made for a name that is no registered skill is not an installed skill.
    hub.usage.bump("never-installed", "view")
    with pytest.raises(usage_mod.PinRefused) as stray:
        hub.usage.pin("never-installed")
    assert stray.value.reason == "not_found" and hub.usage.get("never-installed")["pinned"] is False
    assert usage_mod.usage_summary(hub.usage, "never-installed")["pinnable"] is False
    assert hub.usage.pin(hub.named("my-notes"))["changed"] is True
    assert hub.usage.pin("Weather Intel", False)["changed"] is False      # unpinning is always allowed


def test_a_pin_that_cannot_be_written_changes_nothing_and_says_so(hub):
    hub.write("my-notes")
    hub.boot()
    name = hub.named("my-notes")
    blocker = hub.tmp / "blocker"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    hub.usage.path = blocker / "skill_usage.json"                      # the disk refuses the write
    reply = hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN)
    assert reply.status_code == 503 and reply.json()["reason"] == "write_failed"
    # What the hub answers is what the file holds: not pinned, in memory or on disk.
    assert hub.usage.get(name)["pinned"] is False and hub.usage.is_pinned(name) is False
    assert hub.listing()[name]["usage"]["pinned"] is False
    assert hub.on_disk()[name]["pinned"] is False and hub.log.rows == []


def test_no_sidecar_is_a_refusal_not_a_silent_ok(hub):
    hub.write("my-notes")
    hub.boot()
    hub.orch.skill_usage = None
    reply = hub.client.post(PIN, json={"skill": hub.named("my-notes"), "pinned": True}, headers=ADMIN)
    assert reply.status_code == 503 and "sidecar is not available, so nothing was pinned" in reply.json()["error"]
    hub.orch.skill_usage = SimpleNamespace()                           # a stand-in that cannot pin
    reply = hub.client.post(PIN, json={"skill": hub.named("my-notes"), "pinned": True}, headers=ADMIN)
    assert reply.status_code == 503 and hub.on_disk()[hub.named("my-notes")]["pinned"] is False


def test_a_pinned_skill_is_not_deleted_by_an_agents_batch_until_it_is_unpinned(hub):
    folder = hub.write("my-notes")
    hub.boot()
    name = hub.named("my-notes")
    hub.usage.pin(name)
    refused = run_batch([{"name": name, "action": "delete"}], hub.loader,
                        backup_dir=hub.tmp / "skill-archive", actor="agent:jarvis")
    assert refused["ok"] is False and refused["reason"] == "skill_batch_pinned", refused
    assert "pinned by the owner" in refused["detail"] and "unpin" in " ".join(refused["hints"])
    assert (folder / "SKILL.md").is_file() and name in hub.loader.skills
    hub.usage.pin(name, False)
    gone = run_batch([{"name": name, "action": "delete"}], hub.loader, backup_dir=hub.tmp / "skill-archive",
                     actor="agent:jarvis")
    assert gone["ok"] is True, gone
    assert not folder.exists() and name not in hub.loader.skills


def test_the_journeys_forget_refuses_a_pinned_skill_even_while_it_awaits_review(hub, monkeypatch):
    monkeypatch.setattr(skills_router, "_discard_archive", lambda: hub.tmp / "discarded")
    hub.boot()
    hub.loader.generate_skill("jarvis", "tidy the meeting notes", ["open the notes", "tidy them"])
    name = next(n for n in hub.loader.skills if "tidy" in n.lower())
    folder = Path(hub.loader.skills[name].path)
    assert (folder / "PENDING_REVIEW").exists()                        # quarantined, not approved
    assert hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN).status_code == 200
    from urllib.parse import quote

    path = f"/api/dashboard/today/entries/{quote('skill:' + name, safe='')}"
    kept = hub.client.delete(path, headers=ADMIN)
    assert kept.status_code == 409 and kept.json()["reason"] == "skill_pinned", kept.text
    assert (folder / "SKILL.md").is_file() and name in hub.loader.skills
    assert hub.client.post(PIN, json={"skill": name, "pinned": False}, headers=ADMIN).status_code == 200
    gone = hub.client.delete(path, headers=ADMIN)
    assert gone.status_code == 200 and gone.json()["discarded"] is True, gone.text
    assert not folder.exists()


# ── the CLI ──────────────────────────────────────────────────────────────────────────

def test_nerva_skills_pin_unpin_and_the_listing(hub):
    hub.write("my-notes")
    hub.boot()
    name = hub.named("my-notes")
    code, out, err, app_hub = _cli(["skills", "pin", "my-notes"], hub)
    assert code == EXIT_OK, err
    assert f"pinned {name}" in out and hub.on_disk()[name]["pinned"] is True
    assert app_hub.calls == [("POST", PIN)]
    code, out, _err, _ = _cli(["skills", "pin", name], hub)
    assert code == EXIT_OK and "already pinned" in out
    code, out, _err, _ = _cli(["skills", "list"], hub)
    assert code == EXIT_OK
    mine = next(line for line in out.splitlines() if line.startswith(f"{name}:"))
    assert "local" in mine and "pinned" in mine
    shipped = next(line for line in out.splitlines() if line.startswith("Weather Intel:"))
    assert "bundled" in shipped and "pinned" not in shipped
    code, out, _err, _ = _cli(["skills", "unpin", name, "--json"], hub)
    assert code == EXIT_OK and json.loads(out)["pinned"] is False and hub.on_disk()[name]["pinned"] is False


def test_nerva_skills_pin_reports_a_refusal_and_fails(hub):
    hub.boot()
    code, out, err, _ = _cli(["skills", "pin", "Weather Intel"], hub)
    assert code == EXIT_FAILED and "ships with Nerva" in err and "pinned" not in out
    code, _out, err, _ = _cli(["skills", "pin", "no-such-skill"], hub)
    assert code == EXIT_FAILED and "no installed skill" in err
