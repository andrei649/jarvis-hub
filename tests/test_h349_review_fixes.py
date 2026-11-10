"""H349 — the findings of the adversarial review of the provenance + pin commit.

M1  A sidecar row belongs to one skill: it is retired when the skill is removed (through
    any removal path, or found gone at a start), so a pin, an agent marker or an origin is
    never inherited by whatever later takes the name; ``pin`` refuses a skill that is not
    registered now.
M2  ``agent_created`` is a sticky marker an install record never clears; no importer or
    install path writes into a skill folder it did not create.
M3  A sidecar that does not parse is set aside (kept, logged), never silently replaced;
    malformed rows are repaired, each reader failing toward its stricter side.
M4  A batch delete re-checks the pin under the lock the pin write takes, immediately
    before the swap.
m1-m4 and the nits are pinned at the end.

Real loader, sidecar, batch, curator, importer, marketplace and routes over temp folders;
the reviewer's reproductions (a1.py … a6.py) are the scenarios.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core.skills import batch as batch_mod  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import usage as usage_mod  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.curator import SkillCurator  # noqa: E402
from agents.core.skills.importer import SkillImporter  # noqa: E402
from agents.core.skills.usage import SkillUsageStore, clean_source  # noqa: E402
from tests.test_h349_skill_provenance_pin import ADMIN, PIN, _md, _zip, hub  # noqa: E402,F401


def _create(hub, name, actor="agent:steve"):
    out = run_batch([{"name": name, "action": "create", "content": _md(name)}], hub.loader,
                    actor=actor, backup_dir=hub.tmp / "skill-archive")
    assert out["ok"] is True, out
    return out


def _delete(hub, name, actor="owner", **kw):
    return run_batch([{"name": name, "action": "delete"}], hub.loader, actor=actor,
                     backup_dir=hub.tmp / "skill-archive", **kw)


def _row(hub, name):
    return hub.usage.get(name)


def _generate(hub, task="tidy the meeting notes", **kw):
    hub.loader.generate_skill("jarvis", task, ["open the notes", "tidy them"], **kw)
    return next(n for n in hub.loader.skills if task.split()[0] in n.lower())


# ── M1: a row belongs to one skill ───────────────────────────────────────────────────

def test_a_pin_does_not_outlive_a_skill_removed_by_hand(hub):
    folder = hub.write("gamma")
    hub.boot()
    hub.usage.pin("gamma")
    shutil.rmtree(folder)
    hub.boot()                                                         # found gone at the start
    assert _row(hub, "gamma") is None and "gamma" not in hub.on_disk()
    with pytest.raises(usage_mod.PinRefused) as refused:               # a6: nothing installed to pin
        hub.usage.pin("gamma")
    assert refused.value.reason == "not_found"
    _create(hub, "gamma")                                              # the agent takes the name
    row = _row(hub, "gamma")
    assert row["pinned"] is False and row["agent_created"] is True
    gone = _delete(hub, "gamma")                                       # and the owner can delete it
    assert gone["ok"] is True, gone


def test_a_skill_removed_by_hand_while_the_hub_runs_is_retired_at_the_next_reload(hub):
    folder = hub.write("gamma")
    hub.boot()
    hub.usage.pin("gamma")
    shutil.rmtree(folder)
    hub.loader.discover()
    assert _row(hub, "gamma") is None
    with pytest.raises(usage_mod.PinRefused):
        hub.usage.pin("gamma")
    hub.write("gamma")                                                 # another skill, same name
    hub.loader.discover()
    assert (_row(hub, "gamma")["pinned"], _row(hub, "gamma")["origin"]) == (False, "local")


def test_a_skill_removed_by_hand_cannot_be_pinned_even_before_a_reload(hub):
    folder = hub.write("gamma")
    hub.boot()
    shutil.rmtree(folder)                                              # the registry entry is stale now
    reply = hub.client.post(PIN, json={"skill": "gamma", "pinned": True}, headers=ADMIN)
    assert reply.status_code == 404 and reply.json()["reason"] == "not_found", reply.text
    assert _row(hub, "gamma") is None


def test_the_known_sources_cover_every_migration_source():
    from agents.core.skills.importer import MIGRATION_SOURCES

    assert set(MIGRATION_SOURCES) <= set(usage_mod.KNOWN_SOURCES)


def test_an_owner_skill_does_not_inherit_agent_from_a_deleted_holder_of_the_name(hub):
    hub.boot()
    _create(hub, "delta")
    assert _row(hub, "delta")["agent_created"] is True
    assert _delete(hub, "delta")["ok"] is True
    hub.write("delta")                                                 # the owner's own, by hand
    hub.boot()
    row = _row(hub, "delta")
    assert (row["origin"], row["agent_created"], row["state"]) == ("local", False, "active")
    assert hub.usage.curatable("delta") is False
    assert hub.listing()["delta"]["usage"]["origin"] == "local"


def test_rejecting_a_pinned_skill_from_review_works_and_retires_its_row(hub, monkeypatch):
    from agents.core.routers import skills as skills_router

    monkeypatch.setattr(skills_router, "_discard_archive", lambda: hub.tmp / "discarded")
    hub.boot()
    name = _generate(hub)
    folder = Path(hub.loader.skills[name].path)
    assert hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN).status_code == 200
    gone = hub.client.post(f"/api/skills/{quote(folder.name, safe='')}/discard", headers=ADMIN)
    assert gone.status_code == 200, gone.text
    assert not folder.exists() and name not in hub.loader.skills
    assert _row(hub, name) is None and name not in hub.on_disk()       # a3: no stale pinned row


def test_uninstalling_a_pinned_package_works_and_a_reinstall_starts_clean(hub):
    hub.boot()
    body = {"zip_base64": _zip("market-tool")}
    assert hub.client.post("/api/skills/marketplace/install-zip", json=body, headers=ADMIN).status_code == 200
    name = hub.named("market-tool")
    hub.usage.bump(name, "use")
    assert hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN).status_code == 200
    gone = hub.client.post("/api/skills/marketplace/uninstall", json={"name": "market-tool"}, headers=ADMIN)
    assert gone.status_code == 200 and gone.json()["removed"] is True, gone.text
    assert _row(hub, name) is None
    assert hub.client.post("/api/skills/marketplace/install-zip", json=body, headers=ADMIN).status_code == 200
    row = _row(hub, name)
    assert (row["pinned"], row["use_count"], row["origin"], row["source"]) == (False, 0, "import", "marketplace")


async def test_the_curators_archive_keeps_what_a_restore_needs_and_nothing_a_new_skill_inherits(hub):
    hub.boot()
    name = _generate(hub, "file the receipts")
    assert hub.loader.approve_generated_skill(name)
    hub.usage.bump(name, "use")
    folder = Path(hub.loader.skills[name].path)
    later = datetime.now(UTC) + timedelta(days=200)
    curator = SkillCurator(hub.loader, hub.usage, archive_dir=hub.tmp / "curated", now=lambda: later,
                           get_setting=lambda k, d=None: d)
    assert curator._lifecycle_pass()["archived"] == [name]
    row = _row(hub, name)
    assert (row["state"], row["pinned"], row["agent_created"], row["use_count"]) == ("archived", False, True, 1)
    assert row["archived_at"] and name not in hub.loader.skills
    with pytest.raises(usage_mod.PinRefused):
        hub.usage.pin(name)                                            # archived: not installed
    assert hub.usage.stats()["total"] == len(hub.loader.skills)        # the tombstone is not an installed skill
    # The owner moves the archived folder back: the same bytes get their state back.
    archived = next((hub.tmp / "curated").iterdir())
    shutil.move(str(archived), str(folder))
    hub.boot()
    row = _row(hub, name)
    assert (row["state"], row["archived_at"], row["agent_created"], row["use_count"]) == ("active", None, True, 1)
    assert hub.usage.curatable(name) is True


async def test_a_different_skill_under_an_archived_name_starts_clean(hub):
    hub.boot()
    name = _generate(hub, "file the receipts")
    assert hub.loader.approve_generated_skill(name)
    folder = Path(hub.loader.skills[name].path)
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    later = datetime.now(UTC) + timedelta(days=200)
    curator = SkillCurator(hub.loader, hub.usage, archive_dir=hub.tmp / "curated", now=lambda: later,
                           get_setting=lambda k, d=None: d)
    assert curator._lifecycle_pass()["archived"] == [name]
    folder.mkdir()
    (folder / "SKILL.md").write_text(text + "\nThe owner's own notes.\n", encoding="utf-8")   # not the archived bytes
    hub.boot()
    row = _row(hub, name)
    assert (row["state"], row["agent_created"], row["origin"]) == ("active", False, "local")
    assert hub.usage.curatable(name) is False


def test_a_skill_left_unread_in_safe_mode_keeps_its_pin_and_marker(hub, monkeypatch):
    hub.boot()
    _create(hub, "alpha")
    hub.usage.pin("alpha")
    monkeypatch.setattr(loader_mod.safe_mode, "enabled", lambda: True)
    hub.boot()                                                         # the owner's folder is not read
    assert "alpha" not in hub.loader.skills
    row = _row(hub, "alpha")
    assert (row["pinned"], row["agent_created"]) == (True, True)
    monkeypatch.setattr(loader_mod.safe_mode, "enabled", lambda: False)
    hub.boot()
    assert hub.usage.is_pinned("alpha") and hub.listing()["alpha"]["usage"]["pinned"] is True


# ── M2: the agent marker is sticky; installs never write into another skill's folder ──

def test_planting_an_install_record_does_not_take_an_agent_skill_out_of_curation(hub):
    hub.boot()
    name = _generate(hub)
    folder = Path(hub.loader.skills[name].path)
    (folder / "manifest.json").write_text(json.dumps({"imported": True, "source": "hermes"}), encoding="utf-8")
    hub.boot()
    usage = hub.listing()[name]["usage"]
    # Both facts are shown: the agent made it, and its folder carries an import record.
    assert (usage["origin"], usage["source"], usage["agent_created"]) == ("import", "hermes", True)
    assert hub.usage.curatable(name) is True
    (folder / "manifest.json").unlink()
    hub.boot()
    assert hub.listing()[name]["usage"]["origin"] == "agent" and hub.usage.curatable(name) is True


async def test_an_import_never_writes_into_a_skill_folder_it_did_not_create(hub, monkeypatch):
    hub.boot()
    out = run_batch([{"name": "alpha", "action": "create", "content": _md("alpha", "Use when the agent wants")},
                     {"name": "alpha", "action": "write_file", "file_path": "scripts/run.py",
                      "file_content": "print('agent code')\n"}], hub.loader, actor="agent:steve",
                    backup_dir=hub.tmp / "skill-archive")
    assert out["ok"] is True, out
    hub.usage.pin("alpha")
    folder = hub.home / "alpha"
    before = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    importer = hub.orch.skill_importer
    assert await importer._save_skill("alpha", "hermes", skill_md_text=_md("alpha", "Use when upstream says")) is False
    assert importer.last_conflict == "exists"
    # Through the route: a clear refusal, nothing written, the row untouched.
    monkeypatch.setattr(web, "DEV_MODE", True)

    async def _fetch(self, client, repo, branch, subdir, slug):
        return _md(slug, "Use when upstream says")

    monkeypatch.setattr(SkillImporter, "_fetch_skill_md_flat", _fetch)
    reply = hub.client.post("/skills/import", json={"source": "openclaw", "skill": "alpha"}, headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "exists", reply.text
    assert {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before
    row = _row(hub, "alpha")
    assert (row["pinned"], row["agent_created"], row["origin"]) == (True, True, "agent")
    # Its own earlier import is updated in place; another source's import is not.
    assert await importer._save_skill("beta", "hermes", skill_md_text=_md("beta")) is True
    assert await importer._save_skill("beta", "hermes", skill_md_text=_md("beta", "Use when newer")) is True
    assert "Use when newer" in (hub.home / "beta" / "SKILL.md").read_text(encoding="utf-8")
    assert await importer._save_skill("beta", "openclaw", skill_md_text=_md("beta", "Use when other")) is False
    assert "Use when newer" in (hub.home / "beta" / "SKILL.md").read_text(encoding="utf-8")


def test_a_marketplace_package_never_replaces_a_skill_it_did_not_install(hub):
    hub.boot()
    _create(hub, "market-tool")
    folder = hub.home / "market-tool"
    before = (folder / "SKILL.md").read_bytes()
    reply = hub.client.post("/api/skills/marketplace/install-zip", json={"zip_base64": _zip("market-tool")},
                            headers=ADMIN)
    assert reply.status_code == 422, reply.text
    assert "did not install or publish" in json.dumps(reply.json())
    assert (folder / "SKILL.md").read_bytes() == before and not (folder / loader_mod.EXTERNAL_SOURCE_MARKER).exists()
    assert _row(hub, "market-tool")["agent_created"] is True
    # A package it installed itself is still updated by a reinstall.
    assert hub.client.post("/api/skills/marketplace/install-zip", json={"zip_base64": _zip("other-tool")},
                           headers=ADMIN).status_code == 200
    assert hub.client.post("/api/skills/marketplace/install-zip", json={"zip_base64": _zip("other-tool")},
                           headers=ADMIN).status_code == 200


async def test_a_local_migration_import_never_writes_into_another_skills_folder(hub):
    hub.boot()
    _create(hub, "pdf-tools")
    before = (hub.home / "pdf-tools" / "SKILL.md").read_bytes()
    source = hub.tmp / "claude" / "skills" / "pdf-tools"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(_md("pdf-tools", "Use when upstream says").encode())
    result = await hub.orch.skill_importer.import_local_skill(source, "claude-code", overwrite=True,
                                                              backup_dir=hub.tmp / "bk",
                                                              revoke_approval=lambda p: True)
    assert result["status"] == "skipped" and result["reason"] == "exists_not_imported_from_source", result
    assert (hub.home / "pdf-tools" / "SKILL.md").read_bytes() == before


# ── M3: an unreadable sidecar, and malformed rows ────────────────────────────────────

def _seed(hub):
    hub.write("own")
    hub.boot()
    _create(hub, "mine")
    hub.usage.pin("own")
    hub.usage.pin("mine")
    hub.usage.bump("own", "use")
    return hub.sidecar.read_text(encoding="utf-8")


@pytest.mark.parametrize("damage", ["truncated", "not_an_object", "skills_is_a_list"])
def test_a_sidecar_that_does_not_parse_is_set_aside_and_said(hub, caplog, damage):
    good = _seed(hub)
    bad = {"truncated": good[: len(good) // 2], "not_an_object": "[1, 2]", "skills_is_a_list": '{"skills": []}'}[damage]
    hub.sidecar.write_text(bad, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="jarvis.skills.usage"):
        hub.boot()
    kept = [p for p in hub.tmp.iterdir() if p.name.startswith("skill_usage.json.corrupt-")]
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == bad      # the bytes are kept
    said = [r.getMessage() for r in caplog.records if "skill_usage.json" in r.getMessage()]
    assert said and kept[0].name in said[0] and "mine" not in said[0]           # the file, not its contents
    assert hub.usage.is_pinned("own") is False                                 # started empty, and says so
    assert hub.on_disk()["own"]["origin"] == "local"


def test_rows_that_are_not_records_are_dropped_with_a_copy_and_the_rest_kept(hub, caplog):
    good = json.loads(_seed(hub))
    good["skills"]["mine"] = "x"
    text = json.dumps(good)
    hub.sidecar.write_text(text, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="jarvis.skills.usage"):
        hub.boot()
    kept = [p for p in hub.tmp.iterdir() if p.name.startswith("skill_usage.json.corrupt-")]
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == text
    assert hub.usage.is_pinned("own") is True and hub.usage.get("own")["use_count"] == 1
    assert hub.usage.is_pinned("mine") is False
    assert hub.usage.stats()["total"] == len(hub.loader.skills)                # stats() does not raise


def test_a_malformed_pin_fails_toward_the_stricter_side_for_each_reader(hub):
    data = json.loads(_seed(hub))
    data["skills"]["mine"]["pinned"] = "false"                         # a string, not a bool
    data["skills"]["own"]["pinned"] = "false"
    hub.sidecar.write_text(json.dumps(data), encoding="utf-8")
    hub.boot()
    # Shown: only an exact true is a pin.
    assert hub.usage.is_pinned("mine") is False and hub.listing()["mine"]["usage"]["pinned"] is False
    # The curator and an agent's delete leave alone what they cannot read as "not pinned".
    assert hub.usage.pin_blocks("mine") is True
    refused = _delete(hub, "mine", actor="agent:steve")
    assert refused["ok"] is False and refused["reason"] == "skill_batch_pinned"
    data["skills"]["mine"].update(agent_created=True, write_origin="learning", pinned="false")
    assert hub.usage.curatable("mine") is False
    # The owner's own delete is the owner's act; and a pin write stores a real bool again.
    assert hub.usage.pin("own", False)["pinned"] is False and hub.on_disk()["own"]["pinned"] is False
    assert _delete(hub, "own")["ok"] is True


def test_malformed_counters_and_fields_are_repaired_per_row(hub):
    data = json.loads(_seed(hub))
    data["skills"]["own"].update(use_count="many", view_count=-3, origin={"a": 1}, state=7, agent_created="yes")
    hub.sidecar.write_text(json.dumps(data), encoding="utf-8")
    hub.boot()
    hub.usage.bump("own", "use")
    row = hub.on_disk()["own"]
    assert row["use_count"] == 1 and row["last_used_at"] and row["view_count"] == 0
    assert (row["origin"], row["state"], row["agent_created"]) == ("local", "active", False)
    assert hub.usage.curatable("own") is False                         # a marker that is not exactly true


# ── M4: the pin and the swap are mutually exclusive ──────────────────────────────────

def test_a_pin_that_lands_after_the_first_check_still_stops_the_delete(hub, monkeypatch):
    hub.write("keep")
    hub.boot()
    real = batch_mod._cross_kernel

    def mid(*a, **k):                                                  # after the check, before the swap
        assert hub.usage.pin("keep")["changed"] is True
        return real(*a, **k)

    monkeypatch.setattr(batch_mod, "_cross_kernel", mid)
    out = _delete(hub, "keep", actor="agent:steve")
    assert out["ok"] is False and out["reason"] == "skill_batch_pinned", out
    assert (hub.home / "keep" / "SKILL.md").is_file() and "keep" in hub.loader.skills
    assert hub.usage.is_pinned("keep") and hub.on_disk()["keep"]["pinned"] is True


def test_a_pin_cannot_land_while_the_swap_runs(hub, monkeypatch):
    hub.write("keep")
    hub.boot()
    real = batch_mod._swap
    seen = {}

    def slow(target):
        def _pin():
            try:
                seen["answer"] = hub.usage.pin("keep")
            except usage_mod.PinRefused as exc:
                seen["refused"] = exc.reason

        worker = threading.Thread(target=_pin)
        worker.start()
        worker.join(0.3)
        seen["waited"] = worker.is_alive()                             # blocked behind the swap
        seen["worker"] = worker
        return real(target)

    monkeypatch.setattr(batch_mod, "_swap", slow)
    out = _delete(hub, "keep", actor="agent:steve")
    seen["worker"].join(5)
    assert out["ok"] is True and seen["waited"] is True
    # The pin was answered after the delete: there is no installed skill left to pin.
    assert seen.get("refused") == "not_found" and "answer" not in seen
    assert hub.usage.is_pinned("keep") is False and not (hub.home / "keep").exists()


# ── m1: an unwritable sidecar is said, not "no such skill" ───────────────────────────

def test_a_pin_on_a_skill_whose_row_could_not_be_written_answers_write_failed(hub):
    hub.boot()
    blocker = hub.tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    good = hub.usage.path
    hub.usage.path = blocker / "skill_usage.json"
    hub.write("fresh")
    hub.loader.discover()                                              # installed while it cannot be written
    assert "fresh" in hub.loader.skills
    reply = hub.client.post(PIN, json={"skill": "fresh", "pinned": True}, headers=ADMIN)
    assert reply.status_code == 503 and reply.json()["reason"] == "write_failed", reply.text
    hub.usage.path = good
    assert hub.client.post(PIN, json={"skill": "fresh", "pinned": True}, headers=ADMIN).status_code == 200


# ── m2: the source label is a known word or a bare repository name ───────────────────

@pytest.mark.parametrize("raw,label", [
    ("hermes", "hermes"), ("openclaw", "openclaw"), ("claude-code", "claude-code"), ("acme-skills", "acme-skills"),
    ("https://alice:ghp_AbCdEf0123456789@github.com/acme/secret-repo", ""),
    ("/home/alice/skills", ""), ("C:/Users/alice/skills", ""), ("home/alice/.claude/skills", ""),
    ("acme/private-repo", ""), ("user@host", ""), ("a:b", ""), ("<img src=x>", ""), ("a\x1b[31m", ""),
    ("ships with Nerva", ""), ("marketplace", ""), ("bundled", ""), ("agent", ""), ("local", ""), ("x" * 65, ""),
    (None, ""), (7, ""),
])
def test_clean_source_accepts_only_the_known_vocabulary(raw, label):
    assert clean_source(raw) == label


def test_a_hand_edited_record_cannot_spoof_the_marketplace_or_leak_a_url(hub):
    a = hub.write("spoof-a")
    (a / "manifest.json").write_text(json.dumps({"imported": True, "source": "marketplace"}), encoding="utf-8")
    b = hub.write("spoof-b")
    (b / "manifest.json").write_text(json.dumps(
        {"source_install": "https://alice:ghp_secret@github.com/acme/private"}), encoding="utf-8")
    c = hub.write("spoof-c")
    (c / loader_mod.EXTERNAL_SOURCE_MARKER).write_text("source=ships with Nerva\n", encoding="utf-8")
    hub.boot()
    rows = hub.listing()
    assert rows["spoof-a"]["usage"]["source"] == ""
    assert rows["spoof-b"]["usage"]["source"] == "" and "ghp_secret" not in hub.sidecar.read_text(encoding="utf-8")
    assert rows["spoof-c"]["usage"]["source"] == ""
    assert "ghp_secret" not in json.dumps(rows)


# ── m3: write origin — only autonomous creations are curated ─────────────────────────

def test_a_skill_the_model_created_in_a_turn_is_agent_made_but_not_curated(hub):
    from tests.test_h318_skill_tools import TOOL_PROPOSE, _call, _server

    hub.boot()
    _create(hub, "turn-made")                                          # the model's batch tool, in a turn
    row = _row(hub, "turn-made")
    assert (row["agent_created"], row["write_origin"]) == (True, "assistant_tool")
    assert hub.usage.curatable("turn-made") is False
    usage = hub.listing()["turn-made"]["usage"]
    assert (usage["origin"], usage["agent_created"], usage["write_origin"]) == ("agent", True, "assistant_tool")
    # The model's skill_propose tool creating a new skill in a turn: the same.
    got = _call(_server(hub.loader), TOOL_PROPOSE, {"description": "sort the inbox by sender",
                                                    "steps": ["open the inbox", "sort it"]})
    assert got["ok"] is True, got
    made = next(n for n in hub.loader.skills if "sort" in n.lower())
    assert (_row(hub, made)["agent_created"], _row(hub, made)["write_origin"]) == (True, "assistant_tool")
    assert hub.usage.curatable(made) is False
    # The learning loop and the background review are the agent's own initiative: curated.
    learned = _generate(hub, "tidy the meeting notes")
    assert _row(hub, learned)["write_origin"] == "learning" and hub.usage.curatable(learned) is True
    reviewed = _generate(hub, "file the receipts", write_origin="background_review")
    assert _row(hub, reviewed)["write_origin"] == "background_review" and hub.usage.curatable(reviewed) is True
    # A skill the owner's own batch created is nobody's but the owner's.
    _create(hub, "owner-made", actor="owner")
    assert (_row(hub, "owner-made")["agent_created"], _row(hub, "owner-made")["origin"]) == (False, "local")


def test_the_background_review_marks_its_new_skills(hub):
    from agents.core.learning.background_review import BackgroundReviewer

    hub.boot()
    reviewer = BackgroundReviewer.__new__(BackgroundReviewer)
    reviewer._skills = hub.loader
    actions = []
    assert reviewer._dispatch_new_skill({"task": "archive the old drafts", "steps": ["find", "archive"]}, actions)
    made = next(n for n in hub.loader.skills if "archive" in n.lower())
    assert _row(hub, made)["write_origin"] == "background_review" and hub.usage.curatable(made) is True


# ── m4: a pin stops automation and the journey's forget; the owner's removals work ────

def test_the_owners_own_batch_deletes_a_pinned_skill_and_an_agents_does_not(hub):
    folder = hub.write("my-notes")
    hub.boot()
    hub.usage.pin("my-notes")
    refused = _delete(hub, "my-notes", actor="agent:steve")
    assert refused["ok"] is False and refused["reason"] == "skill_batch_pinned"
    assert "ask the owner to unpin" in " ".join(refused["hints"])
    dry = _delete(hub, "my-notes", actor="agent:steve", dry_run=True)
    assert dry["ok"] is False and dry["reason"] == "skill_batch_pinned"
    gone = _delete(hub, "my-notes")                                    # the owner's own act
    assert gone["ok"] is True and not folder.exists()
    assert _row(hub, "my-notes") is None and "my-notes" not in hub.on_disk()   # the pin went with it


def test_the_journeys_forget_still_refuses_a_pinned_skill_in_the_owners_words(hub):
    hub.boot()
    name = _generate(hub)
    assert hub.loader.approve_generated_skill(name)
    hub.usage.pin(name)
    path = f"/api/dashboard/today/entries/{quote('skill:' + name, safe='')}"
    kept = hub.client.delete(path, headers=ADMIN)
    assert kept.status_code == 409 and kept.json()["reason"] == "skill_pinned"
    assert "unpin it first" in kept.json()["error"] and "ask the owner" not in kept.json()["error"]
    hub.usage.pin(name, False)
    gone = hub.client.delete(path, headers=ADMIN)
    assert gone.status_code == 200, gone.text
    row = _row(hub, name)
    assert (row["state"], row["pinned"], row["agent_created"]) == ("archived", False, True) and row["archived_at"]
    stats = hub.usage.stats()                                          # a tombstone is not an installed skill
    assert stats["total"] == len(hub.loader.skills) and stats["by_state"].get("archived") == 1


# ── nits ─────────────────────────────────────────────────────────────────────────────

def test_a_creation_marker_that_cannot_be_written_is_logged(hub, caplog):
    hub.boot()
    blocker = hub.tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    hub.usage.path = blocker / "skill_usage.json"
    with caplog.at_level(logging.WARNING, logger="jarvis.skills"):
        _generate(hub)
    assert any("agent-made" in r.getMessage() for r in caplog.records)


def test_stats_count_installed_skills_only(hub):
    hub.write("one")
    hub.write("two")
    hub.boot()
    assert hub.usage.stats()["total"] == 3                             # with the shipped one
    assert _delete(hub, "one")["ok"] is True
    assert hub.usage.stats()["total"] == 2


def test_a_reopened_sidecar_pins_nothing_until_the_loader_registers_the_skill(hub):
    hub.write("my-notes")
    hub.boot()
    fresh = SkillUsageStore(hub.sidecar)                               # rows on disk, no loader yet
    with pytest.raises(usage_mod.PinRefused) as refused:
        fresh.pin("my-notes")
    assert refused.value.reason == "not_found"
