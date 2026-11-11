"""H349 — the third adversarial review: the row of a new skill is decided at creation.

B1  An install whose SKILL.md declares the name of a skill installed from another folder
    is refused before anything is written; and no row is ever reset for a name whose
    holder is still installed elsewhere.
M1  The row of a created skill is written at creation, in the sidecar (generation and a
    batch create write it before the folder appears) or with the folder itself (an
    install carries an install id), never as a mark kept in memory until the skill
    registers. So a skill that does not load at once (a load-set only-list, a crash, the
    offline import) still gets the right row: an agent-made skill always has the agent
    marker, no created skill is born pinned, an install never inherits an agent marker.
m1-m6 and the nits at the end. Scenarios: the reviewer's m1_matrix, m3b_races, m6_route,
m7_zip, m8_patch, m9_loadset. Real loader, sidecar, batch, importer, marketplace, routes.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import threading
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core import load_set  # noqa: E402
from agents.core.skills import batch as batch_mod  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import usage as usage_mod  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.curator import SkillCurator  # noqa: E402
from agents.core.skills.importer import SkillImporter  # noqa: E402
from agents.core.skills.usage import SkillUsageStore  # noqa: E402
from tests.test_h349_skill_provenance_pin import ADMIN, PIN, _md, hub, remote_body, serve_remote  # noqa: E402,F401

ZIP = "/api/skills/marketplace/install-zip"


def _zip(content: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", content)
    return base64.b64encode(buf.getvalue()).decode()


def _owner_skill(hub, folder, name="mine"):
    """The owner's pinned, used skill ``name`` living in ``folder``."""
    path = hub.home / folder
    path.mkdir(parents=True)
    (path / "SKILL.md").write_bytes(_md(name).encode())
    hub.boot()
    hub.usage.pin(name)
    for _ in range(4):
        hub.usage.bump(name, "use")
    return path


def _facts(hub, name="mine"):
    row = hub.on_disk().get(name)
    return None if row is None else (row["pinned"], row["use_count"], row["agent_created"], row["origin"])


def _only(monkeypatch, names):
    """A load-set only-list (the owner's ``skills_only``), changeable in place."""
    listed = ["Weather Intel", "weather", *names]
    monkeypatch.setattr(load_set, "_setting", lambda key: ",".join(listed) if key == "skills_only" else "")
    return listed


def _stale(hub, name, *, agent=False, pinned=True, content=None):
    """A row left by a skill of ``name`` that was removed by hand."""
    folder = hub.home / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_bytes((content or _md(name, "Use when the earlier holder wrote it")).encode())
    hub.boot()
    hub.usage.bump(name, "use")
    hub.usage.bump(name, "use")
    if agent:
        hub.usage.mark_agent_created(name, usage_mod.WRITE_LEARNING)
    if pinned:
        hub.usage.pin(name)
    shutil.rmtree(folder)
    hub.boot()
    assert hub.on_disk()[name]["use_count"] == 2


# ── B1: a declared name that is taken ────────────────────────────────────────────────

@pytest.mark.parametrize("folder", ["a-notes", "my-folder"])
def test_a_package_declaring_an_installed_skills_name_is_refused(hub, folder):
    _owner_skill(hub, folder)
    before = hub.on_disk()
    reply = hub.client.post(ZIP, json={"zip_base64": _zip(_md("mine", "Use when a package"))}, headers=ADMIN)
    assert reply.status_code == 422, reply.text
    assert "already installed" in json.dumps(reply.json())
    assert hub.on_disk() == before and _facts(hub) == (True, 4, False, "local")
    assert Path(hub.loader.skills["mine"].path).name == folder        # still the owner's
    assert sorted(p.name for p in hub.home.iterdir() if p.is_dir()) == [folder]    # nothing was written


def test_an_import_whose_skill_md_declares_an_installed_name_is_refused(hub, monkeypatch):
    _owner_skill(hub, "mine")
    before = hub.on_disk()

    serve_remote(monkeypatch, lambda slug: _md("mine", "Use when shadowing the owner's skill"))
    reply = hub.client.post("/skills/import", json=remote_body("someone/their-repo", "zzz"), headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "name_taken", reply.text
    assert not (hub.home / "zzz").exists()
    assert hub.on_disk() == before and Path(hub.loader.skills["mine"].path).name == "mine"


async def test_a_local_migration_declaring_an_installed_name_is_refused(hub):
    _owner_skill(hub, "a-notes")
    before = hub.on_disk()
    source = hub.tmp / "claude" / "skills" / "whatever"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(_md("mine", "Use when migrated").encode())
    result = await hub.orch.skill_importer.import_local_skill(source, "claude-code")
    assert (result["status"], result["reason"]) == ("rejected", "name_taken"), result
    assert not (hub.home / "mine").exists() and hub.on_disk() == before


def test_a_hand_dropped_duplicate_takes_the_name_as_before_but_never_resets_the_row(hub):
    _owner_skill(hub, "a-notes")
    dup = hub.home / "zzz"
    dup.mkdir()
    (dup / "SKILL.md").write_bytes(_md("mine", "Use when dropped by hand").encode())
    (dup / "manifest.json").write_text(json.dumps({"imported": True, "source": "hermes", "install_id": "a" * 32}),
                                       encoding="utf-8")              # even with an install record
    hub.loader.discover()
    # Fourth review: the duplicate (another install id) holds the name with a row of its
    # own, never the owner's pin and counters; the owner's row is kept aside, untouched.
    row = hub.on_disk()["mine"]
    assert (row["pinned"], row["use_count"], row["install_id"]) == (False, 0, "a" * 32)
    hub.boot()
    assert hub.on_disk()["mine"]["pinned"] is False
    shutil.rmtree(dup)
    hub.boot()                                                         # the owner's folder holds it again
    row = hub.on_disk()["mine"]
    assert (row["pinned"], row["use_count"], row["install_id"]) == (True, 4, "")


def test_installing_a_package_the_owner_published_beside_its_source_never_resets_the_row(hub):
    _owner_skill(hub, "src-folder", name="pubskill")
    published = hub.orch.marketplace.publish_skill("src-folder")
    reply = hub.client.post("/api/skills/marketplace/install", json={"name": published["name"]}, headers=ADMIN)
    assert reply.status_code == 200, reply.text                        # the registry's own skill: allowed
    assert (hub.home / "pubskill").is_dir() and (hub.home / "src-folder").is_dir()
    assert _facts(hub, "pubskill")[:2] == (True, 4)                    # the holder is still installed: no reset
    hub.boot()
    assert _facts(hub, "pubskill")[:2] == (True, 4)


def test_an_update_of_its_own_install_keeps_the_row(hub):
    hub.boot()
    assert hub.client.post(ZIP, json={"zip_base64": _zip(_md("pkg"))}, headers=ADMIN).status_code == 200
    hub.usage.pin("pkg")
    hub.usage.bump("pkg", "use")
    update = hub.client.post(ZIP, json={"zip_base64": _zip(_md("pkg", "Use when updated to v2"))}, headers=ADMIN)
    assert update.status_code == 200, update.text
    assert _facts(hub, "pkg") == (True, 1, False, "import")
    hub.boot()
    assert _facts(hub, "pkg") == (True, 1, False, "import")


# ── M1: the row is decided at creation ───────────────────────────────────────────────

def test_a_skill_generated_while_an_only_list_keeps_it_unloaded_has_its_row_and_marker(hub, monkeypatch):
    only = _only(monkeypatch, [])
    hub.boot()
    slug = hub.loader.generate_skill("steve", "convert the thing to pdf", ["one", "two"])
    title = slug.replace("_", " ").title()
    assert title not in hub.loader.skills                              # the list keeps it out
    row = hub.on_disk()[title]                                         # keyed by the title, at creation
    assert (row["agent_created"], row["write_origin"], row["pinned"]) == (True, "learning", False)
    assert slug not in hub.on_disk()                                   # no stray row under the folder slug
    only.append(slug)
    hub.loader.discover()
    assert title in hub.loader.skills and hub.usage.curatable(title) is True
    hub.boot()
    assert hub.on_disk()[title]["agent_created"] is True and slug not in hub.on_disk()


def test_an_agent_batch_create_under_an_only_list_keeps_its_marker_when_listed_later(hub, monkeypatch):
    only = _only(monkeypatch, [])
    hub.boot()
    out = run_batch([{"name": "alpha", "action": "create", "content": _md("alpha")}], hub.loader,
                    actor="agent:steve", create_root=hub.home)
    assert out["ok"] is True and "alpha" not in hub.loader.skills
    assert hub.on_disk()["alpha"]["agent_created"] is True
    only.append("alpha")
    hub.loader.discover()
    row = hub.on_disk()["alpha"]
    assert (row["agent_created"], row["write_origin"], row["origin"]) == (True, "assistant_tool", "agent")


def test_an_agent_skill_created_over_a_stale_pinned_row_is_never_born_pinned(hub, monkeypatch):
    _stale(hub, "alpha")
    only = _only(monkeypatch, [])
    hub.boot()
    out = run_batch([{"name": "alpha", "action": "create", "content": _md("alpha", "Use when the AGENT wrote it")}],
                    hub.loader, actor="agent:steve", create_root=hub.home)
    assert out["ok"] is True
    hub.boot()                                                         # a restart before the list changes
    only.append("alpha")
    hub.loader.discover()
    row = hub.on_disk()["alpha"]
    assert (row["pinned"], row["agent_created"], row["use_count"]) == (False, True, 0)
    assert hub.usage.pin_blocks("alpha") is False


def test_a_crash_between_the_batch_swap_and_the_reload_leaves_the_right_row(hub, monkeypatch):
    _stale(hub, "alpha")

    def crash(*a, **k):
        raise SystemExit("the process died after the swap")

    monkeypatch.setattr(batch_mod, "_reload", crash)
    with pytest.raises(SystemExit):
        run_batch([{"name": "alpha", "action": "create", "content": _md("alpha", "Use when the AGENT wrote it")}],
                  hub.loader, actor="agent:steve", create_root=hub.home)
    assert (hub.home / "alpha" / "SKILL.md").is_file()                 # the folder landed
    monkeypatch.undo()
    hub.boot()
    row = hub.on_disk()["alpha"]
    assert (row["pinned"], row["agent_created"], row["write_origin"]) == (False, True, "assistant_tool")


def test_a_crash_before_a_generated_skill_registers_leaves_the_right_row(hub, monkeypatch):
    hub.boot()
    monkeypatch.setattr(hub.loader, "_name_from_task", lambda task: "alpha_tool")
    hub.usage.start("Alpha Tool", origin="local")                      # a stale pinned row under its title
    hub.usage.pin("Alpha Tool")
    hub.usage.unregister("Alpha Tool")

    def crash(*a, **k):
        raise SystemExit("the process died before the skill loaded")

    monkeypatch.setattr(hub.loader, "_load_skill", crash)
    with pytest.raises(SystemExit):
        hub.loader.generate_skill("steve", "alpha tool for owner", ["one", "two"], write_origin="background_review")
    monkeypatch.undo()
    hub.boot()
    row = hub.on_disk()["Alpha Tool"]
    assert (row["pinned"], row["agent_created"], row["write_origin"]) == (False, True, "background_review")
    assert hub.usage.curatable("Alpha Tool") is True


@pytest.mark.parametrize("path", ["import", "marketplace", "migration"])
async def test_an_install_the_hub_never_saw_register_does_not_inherit_a_stale_row(hub, path):
    """The offline import, and a crash between an install and the next discovery: the
    folder itself says it is a new install."""
    _stale(hub, "alpha", agent=True)
    text = _md("alpha", "Use when installed")
    if path == "import":
        assert await SkillImporter(skills_dir=str(hub.home))._save_skill("alpha", "hermes", skill_md_text=text)
    elif path == "marketplace":
        from agents.core.skills.marketplace import SkillMarketplace

        zipped = base64.b64decode(_zip(text))
        assert SkillMarketplace(skills_dir=str(hub.home), db_path=str(hub.tmp / "m2.db")).install_from_zip(zipped)
    else:
        source = hub.tmp / "hermes" / "skills" / "alpha"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_bytes(text.encode())
        result = await SkillImporter(skills_dir=str(hub.home)).import_local_skill(source, "hermes")
        assert result["status"] == "imported", result
    hub.boot()                                                         # the first time the hub sees it
    row = hub.on_disk()["alpha"]
    assert (row["pinned"], row["agent_created"], row["use_count"], row["origin"]) == (False, False, 0, "import")
    assert hub.usage.curatable("alpha") is False
    hub.usage.pin("alpha")
    hub.usage.bump("alpha", "use")
    hub.boot()                                                         # the same install seen again: its own row
    assert _facts(hub, "alpha") == (True, 1, False, "import")


async def test_an_import_that_dies_midway_never_leaves_a_skill_without_its_install_id(hub, monkeypatch):
    _stale(hub, "alpha", agent=True)
    real = Path.write_bytes

    def dies(self, data):                                              # the process dies writing SKILL.md
        if self.name == "SKILL.md" and self.parent.name == "alpha":
            raise SystemExit("crash")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", dies)
    with pytest.raises(SystemExit):
        await SkillImporter(skills_dir=str(hub.home))._save_skill("alpha", "hermes", skill_md_text=_md("alpha", "x y"))
    monkeypatch.undo()
    assert (hub.home / "alpha" / "manifest.json").is_file() and not (hub.home / "alpha" / "SKILL.md").exists()
    hub.boot()
    assert "alpha" not in hub.loader.skills                            # not a skill: nothing inherits the row
    assert hub.on_disk()["alpha"]["pinned"] is True                    # and the stale row is untouched


def test_a_byte_identical_agent_create_keeps_the_counters_but_not_the_pin(hub):
    content = _md("alpha", "Use when the earlier holder wrote it")
    _stale(hub, "alpha", content=content)
    out = run_batch([{"name": "alpha", "action": "create", "content": content}], hub.loader, actor="agent:steve",
                    create_root=hub.home)
    assert out["ok"] is True, out
    row = hub.on_disk()["alpha"]
    assert (row["use_count"], row["pinned"], row["agent_created"]) == (2, False, True)


def test_an_install_id_written_into_an_installed_skill_does_not_launder_its_pin(hub):
    hub.write("mine")
    hub.boot()
    hub.usage.pin("mine")
    out = run_batch([{"name": "mine", "action": "write_file", "file_path": "manifest.json",
                      "file_content": json.dumps({"imported": True, "source": "hermes", "install_id": "b" * 32})}],
                    hub.loader, actor="agent:steve", backup_dir=hub.tmp / "skill-archive")
    # The agent's batch reaches SKILL.md and four sub-folders, never the install record:
    assert out["ok"] is False and not (hub.home / "mine" / "manifest.json").exists()
    out = run_batch([{"name": "mine", "action": "write_file", "file_path": "EXTERNAL_SOURCE",
                      "file_content": "source=marketplace\ninstall=" + "c" * 32 + "\n"}],
                    hub.loader, actor="agent:steve", backup_dir=hub.tmp / "skill-archive")
    assert out["ok"] is False and hub.on_disk()["mine"]["pinned"] is True
    hub.boot()
    assert hub.on_disk()["mine"]["pinned"] is True
    refused = run_batch([{"name": "mine", "action": "delete"}], hub.loader, actor="agent:steve")
    assert refused["reason"] == "skill_batch_pinned"


def test_an_agent_creation_that_cannot_record_its_row_does_not_happen(hub):
    _stale(hub, "alpha")
    blocker = hub.tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    hub.usage.path = blocker / "skill_usage.json"                      # the sidecar cannot be written
    out = run_batch([{"name": "alpha", "action": "create", "content": _md("alpha", "Use when the AGENT wrote it")}],
                    hub.loader, actor="agent:steve", create_root=hub.home)
    assert out["ok"] is False and out["reason"] == "skill_batch_usage_unavailable", out
    assert not (hub.home / "alpha").exists()                           # nothing was created
    assert hub.usage.get("alpha")["pinned"] is True                    # and the row is as it was
    assert hub.loader.generate_skill("steve", "convert the thing to pdf", ["one", "two"]) is None
    assert [p.name for p in hub.home.iterdir()] == []


def test_a_legacy_import_without_an_install_id_keeps_its_row(hub):
    folder = hub.write("old-import")
    (folder / "manifest.json").write_text(json.dumps({"imported": True, "source": "hermes"}), encoding="utf-8")
    hub.boot()
    hub.usage.pin("old-import")
    hub.usage.bump("old-import", "use")
    hub.boot()
    assert _facts(hub, "old-import") == (True, 1, False, "import")


# ── m1: the pin and a removal that lands between the look and the write ──────────────

def test_a_removal_between_the_folder_check_and_the_write_is_not_undone(hub):
    hub.write("victim")
    hub.boot()
    real = hub.usage.reconcile_origins

    def slow(observed, **kw):                                          # m3b R1b: the delete lands here
        hub.usage.reconcile_origins = real
        out = run_batch([{"name": "victim", "action": "delete"}], hub.loader, actor="owner")
        assert out["ok"] is True and hub.on_disk().get("victim") is None
        return real(observed, **kw)

    hub.usage.reconcile_origins = slow
    hub.loader.sync_origins(["victim"], strict=True)                   # no KeyError
    assert hub.on_disk().get("victim") is None                         # the forgotten row is not re-created
    with pytest.raises(usage_mod.PinRefused):
        hub.usage.pin("victim")


def test_the_pin_route_holds_the_store_lock_across_its_check_and_its_write(hub):
    hub.write("victim")
    hub.boot()
    real = hub.loader.record
    seen = {}

    def spying(names=None, **kw):
        def _try():
            seen["got"] = hub.usage._lock.acquire(timeout=0.3)
            if seen["got"]:
                hub.usage._lock.release()

        probe = threading.Thread(target=_try)
        probe.start()
        probe.join(2)
        return real(names, **kw)

    hub.loader.record = spying
    assert hub.client.post(PIN, json={"skill": "victim", "pinned": True}, headers=ADMIN).status_code == 200
    assert seen["got"] is False                                        # nothing else could write meanwhile


# ── m3 / m4 / nits ───────────────────────────────────────────────────────────────────

def test_an_unknown_write_origin_is_never_curated(hub):
    hub.write("mine")
    hub.boot()
    data = json.loads(hub.sidecar.read_text(encoding="utf-8"))
    data["skills"]["mine"].update(agent_created=True, write_origin="owner")
    hub.sidecar.write_text(json.dumps(data), encoding="utf-8")
    hub.boot()
    assert hub.on_disk()["mine"]["agent_created"] is True and hub.usage.curatable("mine") is False
    later = datetime.now(UTC) + timedelta(days=400)
    curator = SkillCurator(hub.loader, hub.usage, archive_dir=hub.tmp / "curated", now=lambda: later,
                           get_setting=lambda k, d=None: d)
    assert curator._lifecycle_pass()["archived"] == [] and (hub.home / "mine").is_dir()


def test_a_legacy_tombstone_restored_by_the_owner_keeps_the_agent_marker(hub):
    hub.write("old-skill")
    hub.sidecar.write_text(json.dumps({"skills": {"old-skill": {
        "origin": "agent", "created_at": "2026-01-01T00:00:00+00:00", "use_count": 2, "view_count": 0,
        "patch_count": 0, "last_used_at": "2026-01-02T00:00:00+00:00", "last_viewed_at": None,
        "last_patched_at": None, "pinned": False, "state": "archived"}}}), encoding="utf-8")
    hub.boot()                                                         # the folder is back out of the archive
    row = hub.on_disk()["old-skill"]
    assert (row["state"], row["agent_created"], row["use_count"]) == ("active", True, 2)
    assert row["restore_pending"] is True


def test_a_non_bool_restore_pending_keeps_the_shield(hub):
    hub.boot()
    hub.loader.generate_skill("steve", "convert the thing to pdf", ["one", "two"])
    name = next(n for n in hub.loader.skills if "convert" in n.lower())
    data = json.loads(hub.sidecar.read_text(encoding="utf-8"))
    data["skills"][name]["restore_pending"] = "yes"
    hub.sidecar.write_text(json.dumps(data), encoding="utf-8")
    hub.boot()
    later = datetime.now(UTC) + timedelta(days=400)
    curator = SkillCurator(hub.loader, hub.usage, archive_dir=hub.tmp / "curated", now=lambda: later,
                           get_setting=lambda k, d=None: d)
    assert curator._lifecycle_pass()["archived"] == []                 # shielded this pass, settled on its clock
    assert hub.on_disk()[name]["restored_at"] == later.isoformat()


def test_a_dropped_bump_is_counted(hub):
    hub.write("mine")
    hub.boot()
    release, holding = threading.Event(), threading.Event()

    def slow():
        with hub.usage.removal(["mine"], respect_pins=False):
            holding.set()
            release.wait(10)

    worker = threading.Thread(target=slow)
    worker.start()
    assert holding.wait(5)
    try:
        hub.usage.bump("mine", "use")
    finally:
        release.set()
        worker.join(10)
    assert hub.usage.stats()["bumps_dropped"] == 1 and hub.usage.get("mine")["use_count"] == 0


def test_a_sidecar_with_a_byte_order_mark_is_read_not_set_aside(hub):
    hub.write("mine")
    hub.boot()
    hub.usage.pin("mine")
    hub.sidecar.write_bytes(b"\xef\xbb\xbf" + hub.sidecar.read_bytes())
    hub.boot()
    assert hub.usage.is_pinned("mine") and not list(hub.tmp.glob("skill_usage.json.corrupt-*"))


def test_duplicate_keys_make_the_row_malformed_on_the_stricter_side(hub, tmp_path):
    hub.write("mine")
    hub.boot()
    hub.usage.mark_agent_created("mine", usage_mod.WRITE_LEARNING)
    text = hub.sidecar.read_text(encoding="utf-8")
    at = text.index('"mine": {')
    text = text[:at] + text[at:].replace('"pinned": false', '"pinned": true, "pinned": false', 1)
    assert '"pinned": true, "pinned": false' in text
    hub.sidecar.write_text(text, encoding="utf-8")
    store = SkillUsageStore(hub.sidecar)
    assert store.is_pinned("mine") is False                            # shown: not a pin
    assert store.pin_blocks("mine") is True and store.curatable("mine") is False    # automation: hands off
    assert len(list(hub.tmp.glob("skill_usage.json.corrupt-*"))) == 1  # the file as it was is kept


# ── m6: the approval card says a touched skill is pinned ─────────────────────────────

def test_the_preview_and_the_card_say_a_patched_skill_is_pinned(hub):
    from agents.core.skills.batch import SkillBatchStore
    from tests.test_h318_skill_tools import TOOL_PROPOSE, _call
    from tests.test_skill_batch import _Queue, _server

    hub.write("mine")
    hub.write("other")
    hub.boot()
    hub.usage.pin("mine")
    ops = [{"name": "mine", "action": "patch", "old_string": "Do it.", "new_string": "The agent's text."},
           {"name": "other", "action": "patch", "old_string": "Do it.", "new_string": "The agent's text."}]
    dry = run_batch(ops, hub.loader, actor="agent:steve", dry_run=True)
    assert dry["ok"] is True
    by_name = {s["name"]: s for s in dry["skills"]}
    assert by_name["mine"]["pinned"] is True and "pinned" not in by_name["other"]
    store, queue = SkillBatchStore(hub.tmp / "batches.json"), _Queue()
    got = _call(_server(hub, store, queue), TOOL_PROPOSE, {"operations": ops})
    assert got["ok"] is True, got
    card = queue.items[store.get(got["batch_id"])["card"]]
    assert "pinned by the owner: mine" in json.dumps(card)
    assert {s["name"]: s.get("pinned") for s in store.get(got["batch_id"])["preview"]} == {"mine": True, "other": None}
