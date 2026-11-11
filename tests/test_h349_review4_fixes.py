"""H349 — the fourth adversarial review: the name refusal holds across every skills root.

The product has two skills roots: the app-root ``skills/`` (where ``SkillImporter()``
writes) and the owner's skills folder (where the marketplace, generation and a batch write
when a user home is active). The refusal added in the third round looked only at the
caller's own root. Every test of the refusal here runs in BOTH layouts (``site``):

- ``two-root``: the importer writes into the app root, everything else into the owner's;
- ``single-root``: no user home, everything in the app root.

B1  one holder check over every root the loader discovers, by the loader's own parse, plus
    the live registry; and a row is never reset or lent because a folder with another
    install id registered under its name — each install has its own row.
M1  a marketplace package declaring the name of a skill in the other root is refused.
M2  the validator and the loader name a document alike.
M3  uninstalling a package installed beside its published source leaves the source's row.
m1-m4 and the nits at the end. Scenarios: the reviewer's p1, p2, p3 (P3/P4/P5), p7.
"""

from __future__ import annotations

import base64
import io
import json
import random
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402
from agents.core import load_set  # noqa: E402
from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import usage as usage_mod  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.importer import SkillImporter  # noqa: E402
from agents.core.skills.loader import SkillLoader  # noqa: E402
from agents.core.skills.marketplace import SkillMarketplace  # noqa: E402
from agents.core.skills.usage import SkillUsageStore  # noqa: E402
from agents.core.skills.validate import declared_name, validate_skill_md  # noqa: E402
from tests.test_h349_skill_provenance_pin import ADMIN, PIN, _md, hub, remote_body, serve_remote  # noqa: E402,F401

ZIP = "/api/skills/marketplace/install-zip"


def _zip(content: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", content)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture(params=["two-root", "single-root"])
def site(request, hub, monkeypatch):  # noqa: F811
    """The hub in one of the product's two layouts. ``site.app`` is the app-root skills
    folder (the importer's), ``site.own`` where the owner's skills, the marketplace,
    generation and a batch write."""
    two = request.param == "two-root"
    hub.app = hub.shipped
    hub.own = hub.home if two else hub.shipped
    if not two:
        monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    monkeypatch.setattr(web, "DEV_MODE", True)
    real_boot = hub.boot

    def boot():
        real_boot()
        hub.orch.skill_importer = SkillImporter(skills_dir=str(hub.app))
        hub.orch.marketplace = SkillMarketplace(skills_dir=str(hub.own), db_path=str(hub.tmp / "market.db"))
        return hub

    def put(folder, content, root=None):
        path = (root or hub.own) / folder
        path.mkdir(parents=True)
        (path / "SKILL.md").write_bytes(content.encode())
        return path

    def serve(text_for):
        serve_remote(monkeypatch, text_for)   # governance granted; the network, and only that, stubbed

    def served(name):
        skill = hub.loader.skills.get(name)
        return None if skill is None else Path(skill.path)

    hub.boot, hub.put, hub.serve, hub.served, hub.layout = boot, put, serve, served, request.param
    return hub


def _owner(site, folder="my-folder", name="mine", content=None):
    """The owner's own skill, pinned and used four times."""
    path = site.put(folder, content or _md(name, "Use when the OWNER wrote it"))
    site.boot()
    site.usage.pin(name)
    for _ in range(4):
        site.usage.bump(name, "use")
    return path


def _facts(site, name="mine"):
    row = site.on_disk().get(name)
    return None if row is None else (row["pinned"], row["use_count"])


def _tree(site):
    """Every file under both roots: what "nothing was written" means."""
    out = {}
    for root in {site.app, site.own}:
        for path in root.rglob("*"):
            if path.is_file():
                out[str(path.relative_to(site.tmp))] = path.read_bytes()
    return out


# ── B1: the import that declares a name held in another root ─────────────────────────

def test_an_import_declaring_a_name_held_anywhere_is_refused(site):
    folder = _owner(site)
    before, rows = _tree(site), site.on_disk()
    site.serve(lambda slug: _md("mine", "Use when a USER-tier import declares the owner's name"))
    reply = site.client.post("/skills/import", json=remote_body("someone/repo", "zzz"), headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "name_taken", reply.text
    assert _tree(site) == before and site.on_disk() == rows
    assert site.served("mine") == folder
    # p2: one start without the owner's folder, then a normal one — nothing to lose.
    stash = site.tmp / "stash"
    shutil.move(str(folder), str(stash))
    site.boot()
    shutil.move(str(stash), str(folder))
    site.boot()
    assert _facts(site) == (True, 4) and site.served("mine") == folder and site.usage.is_pinned("mine")


async def test_an_import_through_the_importer_itself_is_refused_too(site):
    _owner(site)
    before = _tree(site)
    importer = site.orch.skill_importer
    assert await importer._save_skill("zzz", "hermes", skill_md_text=_md("mine", "Use when imported")) is False
    assert importer.outcome().reason == "name_taken"
    source = site.tmp / "claude" / "skills" / "whatever"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(_md("mine", "Use when migrated").encode())
    result = await importer.import_local_skill(source, "claude-code")
    assert (result["status"], result["reason"]) == ("rejected", "name_taken"), result
    assert _tree(site) == before


def test_a_skill_the_load_set_or_safe_mode_keeps_unloaded_still_holds_its_name(site, monkeypatch):
    _owner(site)
    monkeypatch.setattr(load_set, "_setting", lambda key: "Weather Intel,weather" if key == "skills_only" else "")
    site.boot()
    assert "mine" not in site.loader.skills                            # installed, not loaded
    site.serve(lambda slug: _md("mine", "Use when imported"))
    reply = site.client.post("/skills/import", json=remote_body("someone/repo", "zzz"), headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "name_taken", reply.text
    reply = site.client.post(ZIP, json={"zip_base64": _zip(_md("mine", "Use when a package"))}, headers=ADMIN)
    assert reply.status_code == 422, reply.text


# ── M1: the marketplace package that declares a name held in the other root ──────────

def test_a_package_declaring_the_name_of_an_import_in_the_other_root_is_refused(site):
    site.boot()
    site.serve(lambda slug: _md("foo", "Use when the OWNER imported this"))
    assert site.client.post("/skills/import", json=remote_body("acme/skills", "foo"),
                            headers=ADMIN).status_code == 200
    assert site.served("foo") == site.app / "foo"
    for _ in range(3):
        site.usage.bump("foo", "use")
    assert site.client.post(PIN, json={"skill": "foo", "pinned": True}, headers=ADMIN).status_code == 200
    before, rows = _tree(site), site.on_disk()
    reply = site.client.post(ZIP, json={"zip_base64": _zip(_md("foo", "Use when SOMEONE ELSE's package"))},
                             headers=ADMIN)
    assert reply.status_code == 422, reply.text
    assert "already installed" in json.dumps(reply.json()) or "did not install" in json.dumps(reply.json())
    assert _tree(site) == before and site.on_disk() == rows
    site.boot()
    assert _facts(site, "foo") == (True, 3) and site.served("foo") == site.app / "foo"
    assert "OWNER imported" in (site.served("foo") / "SKILL.md").read_text(encoding="utf-8")


# ── B1, defence in depth: every install has its own row ──────────────────────────────

def test_a_folder_with_another_install_id_never_takes_or_borrows_the_owners_row(site):
    folder = _owner(site)
    # Past the refusal (written by hand, or installed while the owner's volume was away):
    other = site.app / "zzz"
    other.mkdir()
    (other / "manifest.json").write_text(json.dumps({"imported": True, "source": "hermes", "install_id": "a" * 32}),
                                         encoding="utf-8")
    (other / "SKILL.md").write_bytes(_md("mine", "Use when it shadows the owner").encode())
    stash = site.tmp / "stash"
    shutil.move(str(folder), str(stash))                               # one start without the owner's folder
    site.boot()
    assert site.served("mine") == other
    usage = site.listing()["mine"]["usage"]
    assert (usage["pinned"], usage["use_count"], usage["origin"]) == (False, 0, "import")    # its own row
    assert site.usage.pin_blocks("mine") is False
    site.usage.bump("mine", "use")
    other_was = site.usage.get("mine")["use_count"]
    shutil.rmtree(other)
    shutil.move(str(stash), str(folder))                               # the owner's folder is back
    site.boot()
    assert site.served("mine") == folder
    assert _facts(site) == (True, 4) and site.usage.is_pinned("mine")  # the owner's row, as it was
    assert other_was == 1


def test_two_installed_folders_of_one_name_each_keep_their_own_row(site):
    folder = _owner(site)
    other = site.app / "zzz" if site.layout == "single-root" else site.own / "zzz"
    other.mkdir()
    (other / "manifest.json").write_text(json.dumps({"imported": True, "source": "hermes", "install_id": "b" * 32}),
                                         encoding="utf-8")
    (other / "SKILL.md").write_bytes(_md("mine", "Use when it sorts later").encode())
    site.boot()                                                        # the later folder takes the name (as before)
    holder = site.served("mine")
    shown = site.listing()["mine"]["usage"]
    if holder == folder:
        assert (shown["pinned"], shown["use_count"]) == (True, 4)
    else:                                                              # never the owner's pin on other bytes
        assert (shown["pinned"], shown["use_count"]) == (False, 0)
    shutil.rmtree(other)
    site.boot()
    assert _facts(site) == (True, 4)


# ── M2: one parse of a skill's name ──────────────────────────────────────────────────

LEGACY = "# Notes\n\n> Use when the owner wrote it\n\n## Usage\n```\n# mine\n```\n"


def test_a_holder_is_named_as_the_loader_names_it(site):
    folder = _owner(site, folder="a-notes", content=LEGACY)             # the loader registers it as "mine"
    assert site.served("mine") == folder
    before = _tree(site)
    site.serve(lambda slug: _md("mine", "Use when a USER-tier import declares the owner's name"))
    reply = site.client.post("/skills/import", json=remote_body("someone/repo", "zzz"), headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "name_taken", reply.text
    reply = site.client.post(ZIP, json={"zip_base64": _zip(_md("mine", "Use when a package"))}, headers=ADMIN)
    assert reply.status_code == 422, reply.text
    assert _tree(site) == before and _facts(site) == (True, 4)


def test_the_validator_and_the_loader_name_every_document_alike(tmp_path):
    rng = random.Random(349)
    lines = ["# Alpha", "# beta", "> a description", "---", "name: gamma", "name: Delta Tool", "description: Use when x",
             "```", "## Usage", "", "text", "  # indented", "#nospace", "**Version:** 1.0.0", "name:", "name: [a, b]",
             "﻿# bom", "# trailing  ", "- `cmd <x>` — does it"]
    docs = [LEGACY, "# One\n\n> d\n", _md("frontmatter-name"), "---\nname: x\n---\n# Heading Too\n",
            "# A\n# B\n", "﻿---\nname: bom\ndescription: Use when bom\n---\nbody\n", ""]
    for _ in range(1500):
        docs.append("\n".join(rng.choice(lines) for _ in range(rng.randint(0, 9))) + rng.choice(["", "\n"]))
    folder = tmp_path / "folder-name"
    loader = SkillLoader.__new__(SkillLoader)
    compared = 0
    for doc in docs:
        loader_name = loader_mod.loader_name(folder, doc.encode("utf-8"))
        assert loader_name == str(loader._parse_manifest(folder / "SKILL.md", source_bytes=doc.encode("utf-8"))
                                  .get("name") or folder.name)
        declared = declared_name(doc)
        if declared is not None and not validate_skill_md(doc):
            compared += 1
            assert declared == loader_name, doc              # every document a write accepts
        if declared is not None and not doc.lstrip("﻿").startswith("---"):
            assert declared == loader_name, doc              # and every heading-dialect one, valid or not
    assert compared > 50


# ── M3: a package installed beside its published source ──────────────────────────────

def test_a_package_beside_its_published_source_has_its_own_row_and_uninstalls_alone(site):
    source = _owner(site, folder="a-notes")
    published = site.orch.marketplace.publish_skill("a-notes")
    assert published["name"] == "mine"
    reply = site.client.post(ZIP, json={"zip_base64": _zip(_md("mine", "Use when OTHER CONTENT was zipped"))},
                             headers=ADMIN)
    assert reply.status_code == 200, reply.text                        # the registry's own name: still allowed
    package = site.own / "mine"
    assert package.is_dir() and source.is_dir()
    shown = site.listing()["mine"]["usage"]
    if site.served("mine") == package:                                 # other bytes serve: not under the owner's pin
        assert (shown["pinned"], shown["use_count"], shown["origin"]) == (False, 0, "import")
    else:
        assert (shown["pinned"], shown["use_count"]) == (True, 4)
    gone = site.client.post("/api/skills/marketplace/uninstall", json={"name": "mine"}, headers=ADMIN)
    assert gone.status_code == 200 and gone.json()["removed"] is True, gone.text
    site.loader.discover()
    assert not package.exists() and site.served("mine") == source
    assert _facts(site) == (True, 4) and site.usage.is_pinned("mine")  # the source's row was never the package's
    site.boot()
    assert _facts(site) == (True, 4)


# ── m1: a batch create onto the name of an installed skill that is not loaded ────────

def test_an_agent_batch_cannot_create_over_an_installed_skill_that_is_not_loaded(site, monkeypatch):
    folder = _owner(site)                                              # folder my-folder, name mine
    monkeypatch.setattr(load_set, "_setting", lambda key: "Weather Intel,weather" if key == "skills_only" else "")
    site.loader.discover()
    assert "mine" not in site.loader.skills
    rows, before = site.on_disk(), _tree(site)
    ops = [{"name": "mine", "action": "create", "content": _md("mine", "Use when the AGENT wrote other bytes")}]
    for dry in (True, False):
        out = run_batch(ops, site.loader, actor="agent:steve", create_root=site.own, dry_run=dry)
        assert out["ok"] is False and out["reason"] == "skill_batch_exists", out
    assert site.on_disk() == rows and _tree(site) == before and folder.is_dir()


# ── m2: nothing on the event loop waits for the pin route's folder read ──────────────

def test_a_counter_bump_does_not_wait_for_the_pin_routes_folder_read(site, monkeypatch):
    _owner(site)
    site.usage.pin("mine", False)
    real = SkillLoader._fingerprint_of
    reading = threading.Event()

    def slow(skill, folder):
        reading.set()
        time.sleep(0.8)                                                # a slow volume
        return real(skill, folder)

    monkeypatch.setattr(SkillLoader, "_fingerprint_of", staticmethod(slow))
    answer = {}
    worker = threading.Thread(target=lambda: answer.setdefault(
        "pin", site.client.post(PIN, json={"skill": "mine", "pinned": True}, headers=ADMIN).status_code))
    worker.start()
    assert reading.wait(5)
    started = time.monotonic()
    site.usage.bump("mine", "use")
    waited = time.monotonic() - started
    worker.join(10)
    assert answer["pin"] == 200 and waited < 0.3, waited
    assert site.usage.get("mine")["use_count"] == 5 and site.usage.stats()["bumps_dropped"] == 0


# ── m3: the install id is not served ─────────────────────────────────────────────────

def test_the_imported_listing_does_not_serve_install_ids(site):
    site.boot()
    site.serve(lambda slug: _md(slug))
    assert site.client.post("/skills/import", json=remote_body("acme/skills", "foo"),
                            headers=ADMIN).status_code == 200
    stored = json.loads((site.app / "foo" / "manifest.json").read_text(encoding="utf-8"))
    assert usage_mod.clean_install_id(stored["install_id"])
    listed = site.client.get("/skills/imported", headers=ADMIN).json()["imported"]
    assert listed and all("install_id" not in row for row in listed)
    assert stored["install_id"] not in json.dumps(listed) + json.dumps(site.listing())


# ── m4: the owner's own act is not blocked by an unwritable sidecar ──────────────────

def test_an_unwritable_sidecar_blocks_the_agents_creation_and_not_the_owners(site):
    site.put("pat", _md("pat"))
    site.boot()
    site.usage.pin("pat")
    good = site.usage.path
    blocker = site.tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    site.usage.path = blocker / "skill_usage.json"
    agent = run_batch([{"name": "beta", "action": "create", "content": _md("beta")}], site.loader,
                      actor="agent:steve", create_root=site.own)
    assert agent["ok"] is False and agent["reason"] == "skill_batch_usage_unavailable"
    assert not (site.own / "beta").exists() and "try again" not in " ".join(agent["hints"])
    owner = run_batch([{"name": "beta", "action": "create", "content": _md("beta")}], site.loader, actor="owner",
                      create_root=site.own)
    assert owner["ok"] is True and (site.own / "beta" / "SKILL.md").is_file(), owner
    assert any("usage sidecar" in w for w in owner["warnings"])
    gone = run_batch([{"name": "pat", "action": "delete"}], site.loader, actor="owner")
    assert gone["ok"] is True and not (site.own / "pat").exists()
    assert any("pat" in w and "usage" in w for w in gone["warnings"])  # the leftover row is said
    assert site.usage.pending_removals() == ["pat"]
    with pytest.raises(usage_mod.PinRefused):
        site.usage.pin("pat")                                          # removed: nothing to pin meanwhile
    site.usage.path = good                                             # writable again: the next sync retires it
    site.loader.discover()
    assert site.on_disk().get("pat") is None and site.usage.pending_removals() == []


# ── nits ─────────────────────────────────────────────────────────────────────────────

def test_generation_onto_a_name_that_is_held_does_not_touch_its_row(site, monkeypatch):
    site.boot()
    monkeypatch.setattr(site.loader, "_name_from_task", lambda task: "alpha_tool")
    first = site.loader.generate_skill("steve", "alpha tool for owner", ["one", "two"])
    assert first == "alpha_tool"
    shutil.move(str(site.own / "alpha_tool"), str(site.own / "renamed-by-owner"))
    site.loader.discover()
    site.usage.bump("Alpha Tool", "use")
    assert site.client.post(PIN, json={"skill": "Alpha Tool", "pinned": True}, headers=ADMIN).status_code == 200
    rows = site.on_disk()
    assert site.loader.generate_skill("steve", "alpha tool for owner", ["three", "four"]) is None   # p7 P7d
    assert site.on_disk() == rows and not (site.own / "alpha_tool").exists()
    assert site.served("Alpha Tool") == site.own / "renamed-by-owner"


def test_a_generation_that_fails_after_its_row_was_written_leaves_no_stray_row(site, monkeypatch):
    site.boot()
    monkeypatch.setattr(site.loader, "_name_from_task", lambda task: "alpha_tool")

    def boom(*a, **k):
        raise RuntimeError("the folder could not be loaded")

    monkeypatch.setattr(site.loader, "_load_skill", boom)
    with pytest.raises(RuntimeError):
        site.loader.generate_skill("steve", "alpha tool for owner", ["one", "two"])
    assert "Alpha Tool" not in site.on_disk() and site.usage.get("Alpha Tool") is None


async def test_the_importers_outcome_belongs_to_the_call_not_to_the_shared_instance(site):
    import asyncio

    _owner(site)
    importer = site.orch.skill_importer
    seen = {}

    async def refused():
        ok = await importer._save_skill("zzz", "hermes", skill_md_text=_md("mine", "Use when imported"))
        await asyncio.sleep(0.05)                                      # another import finishes meanwhile
        seen["refused"] = (ok, importer.outcome().reason)

    async def fine():
        await asyncio.sleep(0.01)
        ok = await importer._save_skill("fine-one", "hermes", skill_md_text=_md("fine-one"))
        seen["fine"] = (ok, importer.outcome().reason)

    await asyncio.gather(refused(), fine())
    assert seen == {"refused": (False, "name_taken"), "fine": (True, "")}


def test_no_shape_of_the_shelf_stops_the_store(tmp_path):
    shapes = [None, 7, "x", [], [1, {"a": 1}], {}, {"mine": 7}, {"mine": [7, "x", {}, {"pinned": []}]},
              {"mine": {"install_id": "a" * 32}}, {"mine": [{"install_id": 5, "use_count": "many", "state": []}]}]
    for i, shape in enumerate(shapes):
        path = tmp_path / f"s{i}.json"
        path.write_text(json.dumps({"skills": {"mine": {"origin": "local", "pinned": True, "use_count": 2}},
                                    "shelved": shape}), encoding="utf-8")
        store = SkillUsageStore(path)
        assert store.is_pinned("mine") and store.get("mine")["use_count"] == 2
        store.reconcile_origins({"mine": ("import", "hermes", "fp", {"install_id": "c" * 32})}, full=True)
        assert store.is_pinned("mine") is False                        # the install's own row
        store.reconcile_origins({"mine": (None, "", "fp2", {"install_id": ""})}, full=True)
        assert store.is_pinned("mine") is True and store.get("mine")["use_count"] == 2   # the owner's, back
        SkillUsageStore(path)
        assert len(list(tmp_path.glob(f"s{i}.json.corrupt-*"))) <= 1
