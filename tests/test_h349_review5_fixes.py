"""H349 — the fifth adversarial review: two defects of the holder check and the pending
removal, kept small.

B1  The holder check compares names exactly, as the registry does, and a skill that ships
    with Nerva is not a holder for a folder that goes into another root: a user-root skill
    named like a bundled one is base behaviour (``discover()`` loads the owner's folder
    after the app root so that it wins). An update of an installed skill that keeps its
    name is never refused over another holder.
M1  A removal that could not be written is not applied to a skill created under the name
    afterwards.
m1/m3 and the shelf cap at the end. Scenarios: the reviewer's s1, s2, s3, s3b.

Every refusal test runs in both layouts (``site``); the fourth review's cross-root
refusals are re-asserted here beside the new allowances.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.usage import SHELF_PER_NAME, SkillUsageStore  # noqa: E402
from tests.test_h349_review4_fixes import site  # noqa: E402,F401
from tests.test_h349_skill_provenance_pin import ADMIN, PIN, _md, hub  # noqa: E402,F401

ZIP = "/api/skills/marketplace/install-zip"


def _zip(content: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SKILL.md", content)
    return base64.b64encode(buf.getvalue()).decode()


def _bundled(site, *folders):  # noqa: F811
    for folder in folders:
        shutil.copytree(repo_root / "skills" / folder, site.app / folder)


def _install(site, name, text="A marketplace package"):  # noqa: F811
    return site.client.post(ZIP, json={"zip_base64": _zip(_md(name, text))}, headers=ADMIN)


# ── B1 (1): names are compared exactly ───────────────────────────────────────────────

def test_a_name_that_differs_only_in_case_from_a_bundled_skill_is_not_held(site):  # noqa: F811
    site.boot()
    assert "Weather Intel" in site.loader.skills                       # ships with Nerva
    reply = _install(site, "weather intel")                            # another name to the registry
    assert reply.status_code == 200, reply.text
    assert {"Weather Intel", "weather intel"} <= set(site.loader.skills)
    assert site.on_disk()["Weather Intel"]["origin"] == "bundled"       # each its own row
    assert site.on_disk()["weather intel"]["origin"] == "import"


def test_an_exact_name_held_by_an_installed_skill_is_still_refused(site):  # noqa: F811
    folder = site.put("my-folder", _md("mine", "Use when the OWNER wrote it"))
    site.boot()
    site.usage.pin("mine")
    rows = site.on_disk()
    assert _install(site, "mine").status_code == 422                   # the fourth review's refusal holds
    out = run_batch([{"name": "mine", "action": "create", "content": _md("mine", "agent")}], site.loader,
                    actor="agent:steve", create_root=site.own)
    assert out["ok"] is False and out["reason"] == "skill_batch_exists"
    site.serve(lambda slug: _md("mine", "Use when imported"))
    reply = site.client.post("/skills/import", json={"source": "someone/repo", "skill": "zzz"}, headers=ADMIN)
    assert reply.status_code == 409 and reply.json()["reason"] == "name_taken"
    assert site.on_disk() == rows and site.served("mine") == folder


# ── B1 (2): a bundled skill is not a holder for a folder in another root ─────────────

def test_a_user_root_skill_named_like_a_bundled_one_is_allowed_as_on_base(site):  # noqa: F811
    _bundled(site, "spotify", "calendar", "health")
    site.boot()
    assert {"Spotify", "Calendar", "Health"} <= set(site.loader.skills)
    if site.layout == "two-root":
        for name in ("spotify", "Spotify", "calendar"):               # the reviewer's s3
            reply = _install(site, name)
            assert reply.status_code == 200, (name, reply.text)
        out = run_batch([{"name": "health", "action": "create", "content": _md("health", "agent's own")}],
                        site.loader, actor="agent:steve", create_root=site.own)
        assert out["ok"] is True, out
        # The owner's folder wins the name, by design; the shipped folder is untouched.
        assert Path(site.loader.skills["Spotify"].path).parent == site.own
        assert (site.app / "spotify" / "SKILL.md").read_bytes() == (repo_root / "skills/spotify/SKILL.md").read_bytes()
        row = site.on_disk()["Spotify"]
        assert (row["origin"], row["pinned"]) == ("import", False) and row["install_id"]    # its own row
    else:
        # One root: the package would land in, or beside, the shipped folder of that root.
        assert _install(site, "Spotify").status_code == 422
        assert (site.app / "spotify" / "SKILL.md").read_bytes() == (repo_root / "skills/spotify/SKILL.md").read_bytes()
        out = run_batch([{"name": "calendar-sync", "action": "create", "content": _md("calendar-sync")}],
                        site.loader, actor="agent:steve", create_root=site.own)
        assert out["ok"] is True, out


# ── B1 (3): an update that keeps its name is never refused over another holder ───────

def test_the_update_of_a_base_era_install_named_like_a_bundled_skill_goes_through(site):  # noqa: F811
    if site.layout != "two-root":
        return                                                         # one root has one 'spotify' folder
    _bundled(site, "spotify")
    old = site.put("spotify", _md("spotify", "community spotify package v1"))
    (old / loader_mod.EXTERNAL_SOURCE_MARKER).write_text("source=marketplace\n", encoding="utf-8")   # base-era
    site.boot()
    assert {"Spotify", "spotify"} <= set(site.loader.skills)
    for _ in range(3):
        site.usage.bump("spotify", "use")
    pinned = site.client.post(PIN, json={"skill": "spotify", "pinned": True}, headers=ADMIN)   # m3: the exact name
    assert pinned.status_code == 200 and pinned.json()["skill"] == "spotify", pinned.text
    reply = _install(site, "spotify", "community spotify package v2")
    assert reply.status_code == 200, reply.text                        # the reviewer's s3b
    assert "package v2" in (old / "SKILL.md").read_text(encoding="utf-8")
    row = site.on_disk()["spotify"]
    assert (row["pinned"], row["use_count"], row["install_id"]) == (True, 3, "")
    assert site.on_disk()["Spotify"]["origin"] == "bundled"


def test_an_update_of_an_installed_package_is_not_refused_over_a_duplicate_holder(site):  # noqa: F811
    site.boot()
    assert _install(site, "tool", "v1").status_code == 200
    site.usage.pin("tool")
    dup = site.put("zz-dup", _md("tool", "a hand-dropped duplicate"))  # another folder declares the name
    site.loader.discover()
    reply = _install(site, "tool", "v2")
    assert reply.status_code == 200, reply.text
    assert "v2" in (site.own / "tool" / "SKILL.md").read_text(encoding="utf-8") and dup.is_dir()


async def test_an_import_update_that_would_take_another_skills_name_is_still_refused(site):  # noqa: F811
    site.put("my-folder", _md("mine", "Use when the OWNER wrote it"))
    site.boot()
    importer = site.orch.skill_importer
    assert await importer._save_skill("zzz", "hermes", skill_md_text=_md("zzz")) is True
    assert await importer._save_skill("zzz", "hermes", skill_md_text=_md("zzz", "v2")) is True    # keeps its name
    before = (site.app / "zzz" / "SKILL.md").read_bytes()
    assert await importer._save_skill("zzz", "hermes", skill_md_text=_md("mine", "renamed upstream")) is False
    assert importer.outcome().reason == "name_taken" and (site.app / "zzz" / "SKILL.md").read_bytes() == before


# ── M1: a pending removal is not applied to a skill created afterwards ───────────────

def _unwritable(site):  # noqa: F811
    good = site.usage.path
    blocker = site.tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    site.usage.path = blocker / "skill_usage.json"
    return good


def test_a_pending_removal_does_not_hit_a_batch_created_skill_of_the_same_name(site):  # noqa: F811
    site.put("xskill", _md("xskill", "OWNER v1"))
    site.boot()
    good = _unwritable(site)
    gone = run_batch([{"name": "xskill", "action": "delete"}], site.loader, actor="owner")
    assert gone["ok"] is True and site.usage.pending_removals() == ["xskill"]
    site.usage.path = good                                             # writable again
    made = run_batch([{"name": "xskill", "action": "create", "content": _md("xskill", "AGENT bytes")}],
                     site.loader, actor="agent:steve", create_root=site.own)
    assert made["ok"] is True, made
    assert site.usage.pending_removals() == []
    row = site.on_disk()["xskill"]
    assert (row["agent_created"], row["write_origin"], row["state"]) == (True, "assistant_tool", "active")
    site.loader.discover()                                             # the sync that applies pending removals
    row = site.on_disk()["xskill"]
    assert (row["agent_created"], row["state"]) == (True, "active")


def test_a_pending_removal_does_not_hit_a_regenerated_skill(site, monkeypatch):  # noqa: F811
    site.boot()
    monkeypatch.setattr(site.loader, "_name_from_task", lambda task: "alpha_tool")
    site.loader.generate_skill("steve", "alpha tool for owner", ["one", "two"])
    assert site.loader.approve_generated_skill("Alpha Tool")
    good = _unwritable(site)
    gone = run_batch([{"name": "Alpha Tool", "action": "delete"}], site.loader, actor="owner")
    assert gone["ok"] is True and site.usage.pending_removals() == ["Alpha Tool"]
    site.usage.path = good
    assert site.loader.generate_skill("steve", "alpha tool for owner", ["three", "four"]) == "alpha_tool"
    site.loader.discover()
    row = site.on_disk()["Alpha Tool"]
    assert (row["agent_created"], row["write_origin"], row["state"]) == (True, "learning", "active")
    assert site.usage.curatable("Alpha Tool") is True and site.usage.pending_removals() == []


# ── m1: the id-less row of a removed folder goes when only an install still holds the name ──

def test_an_uninstalled_id_less_folder_leaves_no_shelved_row_for_a_later_folder(site):  # noqa: F811
    source = site.put("a-notes", _md("mine", "OWNER bytes"))
    site.boot()
    site.usage.pin("mine")
    site.orch.marketplace.publish_skill("a-notes")
    assert _install(site, "mine", "PACKAGE other bytes").status_code == 200     # its own row; the owner's shelved
    gone = site.client.post("/api/skills/marketplace/uninstall", json={"name": "a-notes"}, headers=ADMIN)
    assert gone.status_code == 200 and not source.exists()
    data = json.loads(site.sidecar.read_text(encoding="utf-8"))
    assert not data.get("shelved", {}).get("mine")                     # the id-less pinned row went with its folder
    site.client.post("/api/skills/marketplace/uninstall", json={"name": "mine"}, headers=ADMIN)
    site.put("hand", _md("mine", "HAND-DROPPED"))                      # the reviewer's s1: a later folder
    site.loader.discover()
    row = site.on_disk()["mine"]
    assert (row["pinned"], row["use_count"]) == (False, 0)


# ── m3 and the shelf cap ─────────────────────────────────────────────────────────────

def test_the_pin_route_takes_the_exact_registry_name_first(site):  # noqa: F811
    site.put("wi", _md("weather intel", "the owner's own"))
    site.boot()
    assert {"Weather Intel", "weather intel"} <= set(site.loader.skills)
    reply = site.client.post(PIN, json={"skill": "weather intel", "pinned": True}, headers=ADMIN)
    assert reply.status_code == 200 and reply.json()["skill"] == "weather intel", reply.text
    assert site.on_disk()["weather intel"]["pinned"] is True and site.on_disk()["Weather Intel"]["pinned"] is False


def test_the_shelf_read_from_the_file_has_the_same_cap_as_the_shelf_written(tmp_path):
    rows = [{"install_id": f"{i:032x}", "origin": "import", "use_count": i} for i in range(1, 30)]
    path = tmp_path / "skill_usage.json"
    path.write_text(json.dumps({"skills": {}, "shelved": {"mine": rows}}), encoding="utf-8")
    SkillUsageStore(path)
    kept = json.loads(path.read_text(encoding="utf-8")).get("shelved", {}).get("mine", [])
    assert len(kept) == SHELF_PER_NAME


# ── sixth review ─────────────────────────────────────────────────────────────────────

def test_removing_a_duplicate_does_not_cost_the_owner_the_pin_of_the_skill_still_installed(site):  # noqa: F811
    """Three folders under one name: the owner's pinned skill, a hand copy of it, and a
    package installed beside the published source. Uninstalling the COPY leaves an id-less
    folder of that name installed, so the id-less row — the owner's pin and uses — stays."""
    source = site.put("a-notes", _md("mine", "OWNER bytes"))
    site.put("a-notes-old", _md("mine", "OWNER bytes, an old copy"))
    site.boot()
    site.usage.pin("mine")
    site.orch.marketplace.publish_skill("a-notes")
    assert _install(site, "mine", "PACKAGE other bytes").status_code == 200
    gone = site.client.post("/api/skills/marketplace/uninstall", json={"name": "a-notes-old"}, headers=ADMIN)
    assert gone.status_code == 200 and source.exists()
    shelved = json.loads(site.sidecar.read_text(encoding="utf-8")).get("shelved", {}).get("mine") or []
    assert [row.get("pinned") for row in shelved] == [True]            # still there, behind the package
    site.client.post("/api/skills/marketplace/uninstall", json={"name": "mine"}, headers=ADMIN)
    site.loader.discover()
    assert site.on_disk()["mine"]["pinned"] is True                    # and back with its folder


def test_an_import_that_sits_at_a_shipped_location_still_holds_its_name(site):  # noqa: F811
    """The exemption is for skills that ship with Nerva. An import the owner made under a
    shipped folder name (the shipped folder itself gone) carries an install record: it is
    the owner's install, pinnable, and holds its name against the other root."""
    if site.layout != "two-root":
        pytest.skip("the exemption only applies across roots")
    from agents.core.skills.loader import _BUNDLED_SKILL_MANIFEST, name_holder

    slug = sorted(_BUNDLED_SKILL_MANIFEST)[0]
    shutil.rmtree(site.app / slug, ignore_errors=True)
    imported = site.put(slug, _md("daily-notes", "OWNER imported this"), root=site.app)
    (imported / "manifest.json").write_text(json.dumps({"imported": True, "source": "someone/repo",
                                                        "install_id": "a" * 32}), encoding="utf-8")
    assert loader_mod._shipped_location(imported)
    target = site.own / "daily-notes"
    assert name_holder("daily-notes", except_dir=target) == imported   # not exempt: it holds its name
    site.boot()
    assert _install(site, "daily-notes", "PACKAGE someone else's bytes").status_code == 422
    out = run_batch([{"name": "daily-notes", "action": "create", "content": _md("daily-notes", "agent")}],
                    site.loader, actor="agent:steve", create_root=site.own)
    assert out["ok"] is False and out["reason"] == "skill_batch_exists"
