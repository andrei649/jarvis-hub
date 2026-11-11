"""H349 — the second adversarial review: the row lifecycle must never act on absence.

The principle these tests pin: the sidecar never destroys or resets a row because of what
it fails to see. A moved skills folder, an empty or missing folder at one start, an
unreachable volume, a SKILL.md that fails to load once — none of them is a removal. A row
ends only through an explicit removal act (batch delete, reject from review, uninstall,
journey forget, curator archive), and a row is replaced only when a creation path makes a
new skill under the name with other bytes, or other bytes register over a tombstone.

B1  moving the skills folder keeps every row.
B2  absence never deletes or resets a row; a stale pin is kept off a NEW skill at creation.
M1  an upgrade from the base commit keeps every agent marker, pin and counter.
M2  a restored skill is not archived again by the next curator pass.
M3  no JSON shape in the sidecar can stop the store from loading.
m1-m3 and the nits at the end. Scenarios: the reviewer's b1 … b6 and c_base/c_branch.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.skills import loader as loader_mod  # noqa: E402
from agents.core.skills import usage as usage_mod  # noqa: E402
from agents.core.skills.batch import run_batch  # noqa: E402
from agents.core.skills.curator import SkillCurator  # noqa: E402
from agents.core.skills.usage import SkillUsageStore, clean_source  # noqa: E402
from tests.test_h349_skill_provenance_pin import (  # noqa: E402,F401
    ADMIN,
    PIN,
    _md,
    _zip,
    hub,
    remote_body,
    serve_remote,
)

BASE_COMMIT = "14ca282"


def _generate(hub, task="convert the thing to pdf", approve=False):
    hub.loader.generate_skill("steve", task, ["step one", "step two"])
    name = next(n for n in hub.loader.skills if task.split()[0] in n.lower())
    if approve:
        assert hub.loader.approve_generated_skill(name, hub.loader.pending_skill_fingerprint(name))
    return name


def _facts(hub, name):
    row = hub.on_disk().get(name)
    return None if row is None else (row["agent_created"], row["pinned"], row["use_count"], row["state"])


def _seed(hub):
    """An agent-made skill and the owner's own, both pinned and used (b1/b2)."""
    hub.boot()
    agent = _generate(hub)
    hub.write("mine")
    hub.loader.discover()
    hub.usage.pin("mine")
    hub.usage.pin(agent)
    hub.usage.bump("mine", "use")
    hub.usage.bump(agent, "use")
    assert _facts(hub, agent) == (True, True, 1, "active") and _facts(hub, "mine") == (False, True, 1, "active")
    return agent


def _curator(hub, clock):
    return SkillCurator(hub.loader, hub.usage, archive_dir=hub.tmp / "curated", now=lambda: clock[0],
                        get_setting=lambda k, d=None: d)


# ── B1: the row is not tied to a path ────────────────────────────────────────────────

def test_moving_the_skills_folder_keeps_every_row(hub, monkeypatch):
    agent = _seed(hub)
    moved = hub.tmp / "home2" / "skills"
    moved.parent.mkdir()
    shutil.move(str(hub.home), str(moved))                             # same skills, same bytes, new path
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: moved)
    hub.boot()
    assert _facts(hub, agent) == (True, True, 1, "active") and _facts(hub, "mine") == (False, True, 1, "active")
    assert hub.usage.is_pinned("mine") and hub.usage.curatable(agent) is False      # pinned, so not curated
    hub.usage.pin(agent, False)
    assert hub.usage.curatable(agent) is True
    assert str(moved) not in hub.sidecar.read_text(encoding="utf-8")   # no absolute path is recorded
    assert str(hub.tmp) not in hub.sidecar.read_text(encoding="utf-8")


# ── B2: absence is not a removal ─────────────────────────────────────────────────────

def test_an_empty_skills_folder_at_one_start_changes_no_row(hub):
    agent = _seed(hub)
    before = hub.on_disk()
    stash = hub.tmp / "stash"
    shutil.move(str(hub.home), str(stash))
    hub.home.mkdir()                                                   # the mount point without the drive
    hub.boot()
    assert hub.on_disk() == before                                     # not one row touched
    assert agent not in hub.loader.skills
    with pytest.raises(usage_mod.PinRefused):                          # not installed now: no new pin,
        hub.usage.pin("mine")
    assert hub.on_disk() == before                                     # and still nothing touched
    shutil.rmtree(hub.home)
    shutil.move(str(stash), str(hub.home))
    hub.boot()
    assert _facts(hub, agent) == (True, True, 1, "active") and _facts(hub, "mine") == (False, True, 1, "active")
    assert hub.usage.is_pinned("mine") and hub.listing()["mine"]["usage"]["pinned"] is True


def test_a_missing_skills_folder_at_one_start_changes_no_row(hub):
    agent = _seed(hub)
    before = hub.on_disk()
    stash = hub.tmp / "stash"
    shutil.move(str(hub.home), str(stash))
    hub.boot()
    assert hub.on_disk() == before
    shutil.move(str(stash), str(hub.home))
    hub.boot()
    assert _facts(hub, agent) == (True, True, 1, "active")


def test_a_pin_request_while_the_volume_is_unreachable_touches_nothing(hub):
    hub.boot()
    name = _generate(hub, approve=True)
    hub.usage.bump(name, "use")
    hub.usage.pin(name)
    before = hub.on_disk()
    stash = hub.tmp / "stash"
    shutil.move(str(hub.home), str(stash))                             # drops out while the hub runs
    hub.loader.sync_origins([name], strict=True)                       # what the pin route runs first
    assert hub.on_disk() == before
    reply = hub.client.post(PIN, json={"skill": name, "pinned": True}, headers=ADMIN)
    assert reply.status_code == 404 and reply.json()["reason"] == "not_found", reply.text
    assert hub.on_disk() == before                                     # refused without touching the row
    # An unpin is still honoured: it only ever narrows.
    shutil.move(str(stash), str(hub.home))
    hub.loader.discover()
    assert _facts(hub, name) == (True, True, 1, "active") and hub.usage.is_pinned(name)


def test_a_skill_that_fails_to_load_once_keeps_its_row(hub):
    agent = _seed(hub)
    before = hub.on_disk()
    md = Path(hub.loader.skills[agent].path) / "SKILL.md"
    good = md.read_bytes()
    md.write_bytes(b"\xff\xfe not a skill")
    hub.boot()
    assert hub.on_disk()[agent] == before[agent]
    md.write_bytes(good)
    hub.boot()
    assert _facts(hub, agent) == (True, True, 1, "active")


def test_a_stale_pin_is_kept_off_a_new_skill_at_creation_not_by_sweeping(hub):
    folder = hub.write("gamma")
    hub.boot()
    hub.usage.pin("gamma")
    hub.usage.bump("gamma", "use")
    shutil.rmtree(folder)                                              # removed by hand: no removal act
    hub.boot()
    row = hub.on_disk()["gamma"]
    assert (row["pinned"], row["use_count"]) == (True, 1)              # the row is left exactly as it was
    with pytest.raises(usage_mod.PinRefused):
        hub.usage.pin("gamma")                                         # nothing installed to pin
    assert hub.usage.stats()["total"] == len(hub.loader.skills)        # and it is not counted as installed
    # A creation path makes another skill under the name: it starts fresh.
    out = run_batch([{"name": "gamma", "action": "create", "content": _md("gamma", "Use when the agent says so")}],
                    hub.loader, actor="agent:steve", backup_dir=hub.tmp / "skill-archive")
    assert out["ok"] is True, out
    row = hub.on_disk()["gamma"]
    assert (row["pinned"], row["use_count"], row["agent_created"]) == (False, 0, True)


def test_the_same_bytes_created_again_are_the_same_skill(hub):
    folder = hub.write("gamma")
    hub.boot()
    hub.usage.pin("gamma")
    hub.usage.bump("gamma", "use")
    shutil.rmtree(folder)
    hub.boot()
    out = run_batch([{"name": "gamma", "action": "create", "content": _md("gamma")}], hub.loader, actor="owner",
                    backup_dir=hub.tmp / "skill-archive")
    assert out["ok"] is True, out
    row = hub.on_disk()["gamma"]
    # Byte for byte the skill the row knew: its use is kept. Its pin is not (third review):
    # a pin is the owner's act on the skill as it was, and a creation is never born pinned.
    assert (row["pinned"], row["use_count"]) == (False, 1)


async def test_an_install_into_a_new_folder_does_not_inherit_a_row_left_under_the_name(hub, monkeypatch):
    from agents import web
    from agents.core.skills.importer import SkillImporter

    for folder in ("trip-planner", "market-tool"):
        (hub.write(folder) / "SKILL.md").write_bytes(_md(folder, "Use when the owner wrote it").encode())
    hub.boot()
    for name in ("trip-planner", "market-tool"):
        hub.usage.pin(name)
        hub.usage.bump(name, "use")
        shutil.rmtree(hub.home / name)                                 # by hand; the rows stay
    hub.loader.discover()

    serve_remote(monkeypatch, lambda slug: _md(slug, "Use when upstream says"))
    reply = hub.client.post("/skills/import", json=remote_body("openclaw", "trip-planner"), headers=ADMIN)
    assert reply.status_code == 200, reply.text
    row = hub.on_disk()["trip-planner"]
    assert (row["pinned"], row["use_count"], row["origin"]) == (False, 0, "import")
    reply = hub.client.post("/api/skills/marketplace/install-zip", json={"zip_base64": _zip("market-tool")},
                            headers=ADMIN)
    assert reply.status_code == 200, reply.text
    row = hub.on_disk()["market-tool"]
    assert (row["pinned"], row["use_count"], row["source"]) == (False, 0, "marketplace")


def test_a_hand_renamed_skill_leaves_a_row_nobody_inherits_by_creation(hub):
    folder = hub.write("old-name")
    hub.boot()
    hub.usage.pin("old-name")
    (folder / "SKILL.md").write_bytes(_md("new-name").encode())
    folder.rename(hub.home / "new-name")
    hub.boot()
    assert hub.on_disk()["old-name"]["pinned"] is True                  # left as it was
    assert hub.on_disk()["new-name"]["pinned"] is False
    assert "old-name" not in hub.listing()                             # not shown as installed
    with pytest.raises(usage_mod.PinRefused):
        hub.usage.pin("old-name")
    assert hub.usage.pin("old-name", False)["changed"] is True          # the owner can still clear it


# ── M1: the upgrade from the base commit ─────────────────────────────────────────────

def _base_row(origin="agent", pinned=False, uses=1):
    """A row exactly as the base commit's usage.py writes one (captured from its code)."""
    stamp = "2026-11-10T04:11:43.848502+00:00"
    return {"origin": origin, "created_at": stamp, "use_count": uses, "view_count": 0, "patch_count": 0,
            "last_used_at": stamp if uses else None, "last_viewed_at": None, "last_patched_at": None,
            "pinned": pinned, "state": "active"}


def _base_install(hub):
    for folder in ("alpha-report", "beta-digest", "mine"):
        hub.write(folder)
    hub.sidecar.write_text(json.dumps({"skills": {
        "alpha-report": _base_row(), "beta-digest": _base_row(pinned=True),
        "mine": _base_row(origin="bundled", uses=2)}}, indent=2), encoding="utf-8")


def _kept(hub):
    rows = hub.on_disk()
    return {n: (rows[n]["agent_created"], rows[n]["pinned"], rows[n]["use_count"]) for n in sorted(rows)
            if n != "Weather Intel"}


_UPGRADED = {"alpha-report": (True, False, 1), "beta-digest": (True, True, 1), "mine": (False, False, 2)}


def test_the_fixture_row_is_what_the_base_commit_writes():
    """The literal above is not a guess: when the base commit is in this clone, its own
    usage.py is run and must write the same keys."""
    got = subprocess.run(["git", "show", f"{BASE_COMMIT}:agents/core/skills/usage.py"], cwd=repo_root,
                         capture_output=True, text=True)
    if got.returncode != 0:
        pytest.skip("the base commit is not in this clone")
    scope: dict = {"__name__": "base_usage"}
    exec(compile(got.stdout, "base_usage.py", "exec"), scope)  # noqa: S102 - this repo's own earlier source
    store = scope["SkillUsageStore"](None)
    store.note_created("a", "agent")
    store.bump("a", "use")
    assert set(store.get("a")) == set(_base_row()) and store.get("a")["origin"] == "agent"


def test_upgrade_plain_first_start(hub):
    _base_install(hub)
    hub.boot()
    assert _kept(hub) == _UPGRADED
    assert hub.usage.curatable("alpha-report") is True                 # a legacy agent row is curated as before
    assert hub.usage.curatable("beta-digest") is False                 # pinned
    assert hub.on_disk()["mine"]["origin"] == "local"                  # the false "bundled" is corrected


@pytest.mark.parametrize("fault", ["missing", "empty"])
def test_upgrade_with_the_user_folder_missing_or_empty_at_the_first_start(hub, fault):
    _base_install(hub)
    stash = hub.tmp / "stash"
    shutil.move(str(hub.home), str(stash))
    if fault == "empty":
        hub.home.mkdir()
    hub.boot()
    rows = hub.on_disk()
    assert (rows["alpha-report"]["origin"], rows["beta-digest"]["pinned"]) == ("agent", True)   # untouched
    if fault == "empty":
        shutil.rmtree(hub.home)
    shutil.move(str(stash), str(hub.home))
    hub.boot()
    assert _kept(hub) == _UPGRADED and hub.usage.curatable("alpha-report") is True


def test_upgrade_with_one_unreadable_skill_at_the_first_start(hub):
    _base_install(hub)
    md = hub.home / "alpha-report" / "SKILL.md"
    good = md.read_bytes()
    md.write_bytes(b"\xff\xfe not a skill")
    hub.boot()
    assert "alpha-report" not in hub.loader.skills
    assert hub.on_disk()["alpha-report"]["origin"] == "agent"
    md.write_bytes(good)
    hub.boot()
    assert _kept(hub) == _UPGRADED and hub.usage.curatable("alpha-report") is True


# ── M2 / m1: a restore is not archived again ─────────────────────────────────────────

@pytest.mark.parametrize("approve", [True, False])
def test_a_restored_skill_gets_its_state_back_and_a_fresh_idle_clock(hub, approve):
    hub.boot()
    name = _generate(hub, approve=approve)                             # not approved: its fingerprint is not loaded
    hub.usage.bump(name, "use")
    folder = Path(hub.loader.skills[name].path)
    clock = [datetime.now(UTC) + timedelta(days=100)]
    assert _curator(hub, clock)._lifecycle_pass()["archived"] == [name]
    row = hub.on_disk()[name]
    assert row["state"] == "archived" and row["fingerprint"]           # bound to the archived bytes
    shutil.move(str(next((hub.tmp / "curated").iterdir())), str(folder))   # the owner moves it back
    hub.boot()
    assert _facts(hub, name) == (True, False, 1, "active")
    clock[0] += timedelta(days=1)                                      # the reviewer's b3b: the next nightly pass
    assert _curator(hub, clock)._lifecycle_pass()["archived"] == []
    assert folder.is_dir() and name in hub.loader.skills               # still installed
    row = hub.on_disk()[name]
    assert row["restored_at"] == clock[0].isoformat() and "restore_pending" not in row
    clock[0] += timedelta(days=20)
    assert _curator(hub, clock)._lifecycle_pass()["archived"] == []    # the idle clock runs from the restore
    clock[0] += timedelta(days=200)
    assert _curator(hub, clock)._lifecycle_pass()["archived"] == [name]    # and an idle skill still ages out


# ── M3: no JSON shape stops the store ────────────────────────────────────────────────

_SHAPES = [None, True, False, 0, -7, 3.5, 1e308, "", "x", "active", "agent", "true", "x" * 5000, [], [1, [2, [3]]],
           {}, {"a": {"b": {"c": []}}}, [{}], "\x00", "import", "archived", "assistant_tool"]
_FIELDS = ["restore_pending", "origin", "source", "agent_created", "write_origin", "created_at", "fingerprint", "use_count",
           "view_count", "patch_count", "switch_on_count", "last_used_at", "last_viewed_at", "last_patched_at",
           "last_switched_on_at", "restored_at", "pinned", "state", "archived_at", "folder", "unknown_future_field"]


def _exercise(store):
    """Every reader and writer a hub start and a request reach."""
    for name in list(store.list()) + ["mine", "nobody"]:
        store.get(name)
        store.is_pinned(name)
        store.pin_blocks(name)
        store.curatable(name)
        usage_mod.usage_summary(store, name)
        usage_mod.latest_activity_at(store.get(name) or {})
        store.bump(name, "use")
    store.stats()
    store.reconcile_origins({"mine": (None, "", "fp-1")}, full=True)
    store.pin("mine", True)
    store.pin("mine", False)


def test_every_field_as_every_shape_loads_and_is_set_aside_once(tmp_path):
    case = 0
    for field in _FIELDS:
        for shape in _SHAPES:
            case += 1
            folder = tmp_path / f"c{case}"
            folder.mkdir()
            path = folder / "skill_usage.json"
            text = json.dumps({"skills": {"mine": {"origin": "agent", "pinned": True, "use_count": 2, field: shape},
                                          "other": {"origin": "agent", "use_count": 3}}})
            path.write_text(text, encoding="utf-8")
            store = SkillUsageStore(path)                              # never raises
            _exercise(store)
            copies = sorted(folder.glob("skill_usage.json.corrupt-*"))
            assert len(copies) <= 1, (field, shape)
            if copies:
                assert copies[0].read_text(encoding="utf-8") == text   # the original, whole
            assert store.get("other")["use_count"] == 4                # the good row survived, and counts
            SkillUsageStore(path)                                      # a second start makes no second copy
            assert len(list(folder.glob("skill_usage.json.corrupt-*"))) == len(copies), (field, shape)


def test_random_json_never_stops_the_store(tmp_path):
    rng = random.Random(349)

    def any_json(depth=0):
        roll = rng.random()
        if depth > 4 or roll < 0.45:
            return rng.choice(_SHAPES[:13])
        if roll < 0.7:
            return [any_json(depth + 1) for _ in range(rng.randint(0, 4))]
        keys = rng.sample(_FIELDS + ["skills", "mine", "a"], rng.randint(0, 6))
        return {k: any_json(depth + 1) for k in keys}

    for case in range(400):
        folder = tmp_path / f"r{case}"
        folder.mkdir()
        path = folder / "skill_usage.json"
        top = any_json() if case % 3 else {"skills": {f"s{i}": any_json() for i in range(rng.randint(0, 5))}}
        path.write_text(json.dumps(top), encoding="utf-8")
        store = SkillUsageStore(path)
        _exercise(store)
        assert len(list(folder.glob("skill_usage.json.corrupt-*"))) <= 1
    for text in ('{"skills":' + "[" * 50000 + "]" * 50000 + "}", "[1]", '"x"', "nul", "", '{"skills": 7}'):
        path = tmp_path / "deep.json"
        path.write_text(text, encoding="utf-8")
        _exercise(SkillUsageStore(path))


def test_a_clean_sidecar_and_an_upgraded_one_are_never_set_aside(hub):
    _base_install(hub)
    hub.boot()
    hub.boot()
    assert not list(hub.tmp.glob("skill_usage.json.corrupt-*"))        # a row from before is not damage


def test_b5b_a_list_or_dict_in_a_word_field_does_not_take_the_store_down(tmp_path):
    for field, value in (("state", {}), ("state", []), ("origin", []), ("write_origin", {}),
                         ("source", {"a": 1}), ("pinned", [])):
        path = tmp_path / f"{field}-{type(value).__name__}.json"
        path.write_text(json.dumps({"skills": {"mine": {"origin": "agent", "pinned": True, field: value},
                                               "other": {"origin": "agent", "use_count": 3}}}), encoding="utf-8")
        store = SkillUsageStore(path)
        assert store.get("other")["use_count"] == 3 and store.get("mine") is not None


# ── m2: no reader waits behind a removal ─────────────────────────────────────────────

def test_reading_the_listing_does_not_wait_for_a_removal_in_progress(hub):
    hub.write("mine")
    hub.boot()
    release = threading.Event()
    holding = threading.Event()

    def slow():
        with hub.usage.removal(["mine"], respect_pins=False):
            holding.set()
            release.wait(10)                                           # a batch swap or an archive move

    worker = threading.Thread(target=slow)
    worker.start()
    assert holding.wait(5)
    try:
        started = time.monotonic()
        usage_mod.usage_summary(hub.usage, "mine")
        hub.usage.get("mine")
        hub.usage.list()
        hub.usage.is_pinned("mine")
        assert hub.listing()["mine"]["usage"]["origin"] == "local"     # GET /skills, while it is held
        hub.usage.bump("mine", "use")                                  # a skill running on the loop gives up
        assert time.monotonic() - started < 2.0
        assert hub.usage.get("mine")["use_count"] == 0
    finally:
        release.set()
        worker.join(10)
    hub.usage.bump("mine", "use")
    assert hub.usage.get("mine")["use_count"] == 1                     # and counts again once it is free


# ── m3: the copies are bounded ───────────────────────────────────────────────────────

def test_a_dropped_row_is_copied_once_and_copies_are_capped(hub):
    hub.write("mine")
    hub.boot()
    hub.usage.pin("mine")
    data = json.loads(hub.sidecar.read_text(encoding="utf-8"))
    data["skills"]["junk"] = 7
    hub.sidecar.write_text(json.dumps(data), encoding="utf-8")
    for _ in range(4):
        hub.boot()
    assert len(list(hub.tmp.glob("skill_usage.json.corrupt-*"))) == 1  # one copy, not one a start
    assert "junk" not in hub.on_disk() and hub.usage.is_pinned("mine")
    for _ in range(usage_mod.CORRUPT_COPIES_KEPT + 4):
        hub.sidecar.write_text("{not json", encoding="utf-8")
        hub.boot()
    assert len(list(hub.tmp.glob("skill_usage.json.corrupt-*"))) == usage_mod.CORRUPT_COPIES_KEPT


# ── nits ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,label", [
    ("acme-skills", "acme-skills"), ("claude-code", "claude-code"), ("a" * 39, "a" * 39), ("a" * 40, ""),
    ("ghp_AbCdEf0123456789AbCdEf0123456789", ""), ("github_pat_11ABCDEFG0", ""), ("sk-live-1234", ""),
    ("0123456789abcdef0123456789abcdef", ""), ("QWxhZGRpbjpvcGVuIHNlc2FtZQ", ""), ("skills.v2_final", "skills.v2_final"),
])
def test_the_source_label_is_a_repository_name_and_never_token_shaped(raw, label):
    assert clean_source(raw) == label
