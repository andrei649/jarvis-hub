"""H330 — a skill delete migrates the references to it (Hermes ``skill_manage`` delete
with ``absorbed_into``) and shares one atomic batch with the edits that update them.

Hermes moves a deleted skill's cron ``skills`` links to the skill that absorbed it. Nerva
names a skill from more places, so a delete in a batch (``skills.batch.run_batch``, through
the owner's ``POST /api/skills/batch`` and the model's ``skill_propose {operations}``
decided on its card) asks every holder and each reference is migrated or reported:

* another skill's ``related_skills`` is rewritten on its staging copy (diffed, swapped and
  rolled back with the rest); its prose is reported with lines;
* a bundle member is rewritten when the batch lands, inside the same rollback;
* scheduled jobs, the load set, the switches, pending proposals and batches are reported.

Governance: before anything moves the delete crosses the ``skill.install`` kernel gate and
every other write the ``skill.generation`` one (registered in ``ACTION_REGISTRY``; it also
guards ``generate_skill``, ``approve_generated_skill`` and an approved SKILL.md proposal); a
create in the batch passes the ``skill.generation`` contract; a skill in CDX-8 quarantine is
never edited, migrated or made the absorbing skill. On the governed path a bundle member the
agent may not see is counted, never named, and whatever the review showed rewritten must be
unchanged when the owner's card applies it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.autonomy.jobs import JobStore
from agents.core.skills import batch as batch_mod
from agents.core.skills import bundles, references
from agents.core.skills import loader as loader_mod
from agents.core.skills.batch import CARD_TOOL, SkillBatchStore, run_batch
from agents.core.skills.references import Holders
from tests.test_skill_batch import _md, _no_key, _propose, _Queue, _server, hub  # noqa: F401


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(bundles, "bundles_dir", lambda: tmp_path / "skill-bundles")
    monkeypatch.setattr(bundles, "_CACHE", {"dir": None, "key": None, "bundles": {}, "problems": []})


def _related_md(name: str, related: str, body: str = "## Steps\n\nDo the thing.\n") -> str:
    return f"---\nname: {name}\ndescription: Use when testing {name}\n{related}---\n{body}"


def _holders(**kw) -> Holders:
    return Holders(**{"jobs": lambda: [], "proposals": lambda: [], "batches": lambda: [], **kw})


def _run(hub, ops, **kw):
    kw.setdefault("holders", _holders())
    return run_batch(ops, hub.loader, backup_dir=hub.archive, **kw)


def _bundle(name, skills):
    bundles.save(name, skills, description=f"the {name} bundle")
    return bundles.get(name)


def _ref(out, skill):
    [entry] = [r for r in out["references"] if r["skill"] == skill]
    return entry


# ── one batch: the delete and the edits that update its references ───────────────────

def test_a_delete_shares_one_atomic_batch_with_edits_to_other_skills(hub):
    # Fails on the old code: a delete in a batch of more than one operation was refused
    # with skill_batch_delete_not_alone (batch.py:214-215 before H330).
    hub.write("alpha")
    hub.write("beta", body="## Steps\n\nUse the alpha skill first.\n")
    hub.write("omega")
    hub.load()
    out = _run(hub, [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"},
        {"name": "beta", "action": "patch", "old_string": "the alpha skill", "new_string": "the omega skill"},
        {"name": "omega", "action": "write_file", "file_path": "references/from-alpha.md", "file_content": "x\n"},
    ])
    assert out["ok"] is True and out["applied"] is True, out
    assert not (hub.root / "alpha").exists() and "alpha" not in hub.loader.skills
    assert "the omega skill" in (hub.root / "beta" / "SKILL.md").read_text()
    assert (hub.root / "omega" / "references" / "from-alpha.md").exists()
    assert {s["name"]: s["change"] for s in out["skills"]} == {"alpha": "deleted", "beta": "changed",
                                                               "omega": "changed"}
    ref = _ref(out, "alpha")
    assert ref["absorbed_into"] == "omega" and ref["left"] == []          # the batch's own edit fixed beta


def test_a_failing_edit_in_a_delete_batch_changes_nothing(hub):
    hub.write("alpha")
    hub.write("beta")
    hub.write("omega")
    hub.load()
    _bundle("research", ["alpha", "beta"])
    before, bundle_before = hub.tree(), bundles.get("research").path.read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"},
                     {"name": "beta", "action": "patch", "old_string": "not there", "new_string": "x"}])
    assert out["ok"] is False and out["reason"] == "skill_batch_patch_no_match"
    assert hub.tree() == before and bundles.get("research").path.read_bytes() == bundle_before


def test_ordering_rules_for_a_delete_and_its_absorbing_skill(hub):
    hub.write("alpha")
    hub.write("beta")
    hub.load()
    before = hub.tree()
    cases = [
        ([{"name": "alpha", "action": "delete", "absorbed_into": "alpha"}], "skill_batch_bad_field"),
        ([{"name": "alpha", "action": "delete", "absorbed_into": 3}], "skill_batch_bad_field"),
        ([{"name": "alpha", "action": "delete", "absorbed_into": "beta"},
          {"name": "beta", "action": "delete"}], "skill_batch_absorbed_deleted"),
        ([{"name": "alpha", "action": "delete", "absorbed_into": "nobody"}], "skill_batch_absorbed_unknown"),
        ([{"name": "alpha", "action": "patch", "absorbed_into": "beta", "old_string": "Do", "new_string": "x"}],
         "skill_batch_bad_field"),
    ]
    for ops, reason in cases:
        out = _run(hub, ops)
        assert out["reason"] == reason, (ops, out)
        assert hub.tree() == before
    # The absorbing skill may be one the same batch creates, wherever its create stands.
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "gamma"},
                     {"name": "gamma", "action": "create", "content": _md("gamma")}])
    assert out["ok"] is True and (hub.root / "gamma").is_dir() and not (hub.root / "alpha").exists()


# ── other skills: related_skills migrated, prose reported ────────────────────────────

def test_related_skills_naming_the_deleted_skill_move_to_the_absorbing_one(hub):
    hub.write("alpha")
    hub.write("omega")
    flow = hub.root / "flow"
    flow.mkdir()
    (flow / "SKILL.md").write_text(_related_md("flow", "related_skills: [alpha, other]\n"))
    block = hub.root / "block"
    block.mkdir()
    (block / "SKILL.md").write_text(_related_md(
        "block", "metadata:\n  hermes:\n    related_skills:\n      - alpha\n      - omega\n    tags: [x]\n"))
    hub.load()
    dry = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}], dry_run=True)
    assert dry["ok"] is True and dry["applied"] is False
    changed = {s["name"]: s for s in dry["skills"]}
    assert changed["flow"]["migrated_for"] == ["alpha"] and changed["block"]["migrated_for"] == ["alpha"]
    assert "+related_skills: [omega, other]" in changed["flow"]["files"][0]["diff"]
    assert (flow / "SKILL.md").read_text() == _related_md("flow", "related_skills: [alpha, other]\n")
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True, out
    assert references.related_names((flow / "SKILL.md").read_text()) == ["omega", "other"]
    # Already related to omega: the entry is dropped, not repeated; the other keys stay.
    text = (block / "SKILL.md").read_text()
    assert references.related_names(text) == ["omega"] and "tags: [x]" in text
    assert hub.loader.skills["flow"].manifest["related_skills"] == ["omega", "other"]
    assert {m["name"] for m in _ref(out, "alpha")["migrated"] if m["holder"] == "skill"} == {"flow", "block"}
    assert (Path(out["backup"]) / "flow" / "SKILL.md").read_text().count("alpha") == 1     # reversible


def test_without_an_absorbing_skill_references_are_reported_not_rewritten(hub):
    hub.write("alpha")
    hub.write("mentions", body="## Steps\n\nFirst.\nThen run alpha on it.\n", files={
        "references/notes.md": "see alpha\n"})
    rel = hub.root / "rel"
    rel.mkdir()
    (rel / "SKILL.md").write_text(_related_md("rel", "related_skills: [alpha]\n"))
    hub.load()
    before_rel = (rel / "SKILL.md").read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete"}])
    assert out["ok"] is True and (rel / "SKILL.md").read_bytes() == before_rel
    left = _ref(out, "alpha")["left"]
    assert {"holder": "skill", "name": "rel", "field": "related_skills", "why": "no absorbing skill named"} in left
    assert {"holder": "skill", "name": "mentions", "field": "text", "file": "SKILL.md", "lines": [8]} in left
    assert {"holder": "skill", "name": "mentions", "field": "text", "file": "references/notes.md",
            "lines": [1]} in left


def test_a_quarantined_skill_is_reported_never_rewritten_nor_made_the_absorber(hub):
    hub.write("alpha")
    hub.write("omega")
    pending = hub.root / "pending"
    pending.mkdir()
    (pending / "SKILL.md").write_text(_related_md("pending", "related_skills: [alpha]\n"))
    (pending / "PENDING_REVIEW").write_text("")
    hub.load()
    before = (pending / "SKILL.md").read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True and (pending / "SKILL.md").read_bytes() == before            # CDX-8 holds
    assert {"holder": "skill", "name": "pending", "field": "related_skills",
            "why": "awaits the owner's review (quarantine)"} in _ref(out, "alpha")["left"]
    hub.write("beta")
    hub.load()
    out = _run(hub, [{"name": "beta", "action": "delete", "absorbed_into": "pending"}])
    assert out["reason"] == "skill_batch_absorbed_pending_review" and (hub.root / "beta").exists()


# ── bundles: rewritten inside the same all-or-nothing apply ──────────────────────────

def test_a_bundle_listing_the_deleted_skill_is_rewritten_to_the_absorbing_one(hub):
    hub.write("alpha")
    hub.write("beta")
    hub.write("omega")
    hub.load()
    _bundle("research", ["alpha", "beta"])
    _bundle("both", ["alpha", "omega"])
    _bundle("other", ["beta"])
    other_before = bundles.get("other").path.read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True, out
    assert list(bundles.get("research").skills) == ["omega", "beta"]
    assert list(bundles.get("both").skills) == ["omega"]                            # not repeated
    assert bundles.get("research").description == "the research bundle"
    assert bundles.get("other").path.read_bytes() == other_before
    moved = {m["slug"]: m for m in _ref(out, "alpha")["migrated"] if m["holder"] == "bundle"}
    assert moved["research"]["before"] == ["alpha", "beta"] and moved["research"]["after"] == ["omega", "beta"]
    # The bundles' old bytes are archived with the old folders (review-H330 r1 minor e).
    archived = Path(out["backup"]) / "bundles"
    assert sorted(p.name for p in archived.iterdir()) == sorted(
        bundles.get(slug).path.name for slug in ("research", "both"))


def test_a_bundle_without_an_absorbing_skill_is_reported_and_left(hub):
    hub.write("alpha")
    hub.write("beta")
    hub.load()
    _bundle("research", ["alpha", "beta"])
    before = bundles.get("research").path.read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete"}])
    assert out["ok"] is True and bundles.get("research").path.read_bytes() == before
    assert {"holder": "bundle", "name": "research", "slug": "research", "skill": "alpha", "member": "alpha",
            "why": "no absorbing skill named"} in _ref(out, "alpha")["left"]


def test_a_failed_bundle_write_puts_every_bundle_and_skill_back(hub, monkeypatch):
    hub.write("alpha")
    hub.write("omega")
    rel = hub.root / "rel"
    rel.mkdir()
    (rel / "SKILL.md").write_text(_related_md("rel", "related_skills: [alpha]\n"))
    hub.load()
    _bundle("first", ["alpha"])
    _bundle("second", ["alpha"])
    before = hub.tree()
    files = {b.slug: b.path.read_bytes() for b in bundles.list_bundles()}
    real_save, calls = bundles.save, []

    def failing_save(name, members, **kw):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_save(name, members, **kw)

    monkeypatch.setattr(bundles, "save", failing_save)
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is False and out["reason"] == "skill_batch_apply_failed", out
    # The first bundle was rewritten and the second failed mid-write: both get their bytes back.
    assert sorted(out["rolled_back"]) == ["alpha", "rel"] and len(out["bundles_rolled_back"]) == 2
    assert hub.tree() == before                                   # alpha back, rel's related_skills back
    assert {b.slug: b.path.read_bytes() for b in bundles.list_bundles()} == files
    assert not list(hub.root.glob(".skill-batch-*"))


# ── holders outside the skills tree: reported ────────────────────────────────────────

def test_jobs_the_load_set_switches_proposals_and_batches_are_reported(hub, tmp_path, monkeypatch):
    from agents.core import load_set
    from agents.core.skills import switches

    hub.write("alpha")
    hub.write("omega")
    hub.load()
    jobs = JobStore(tmp_path / "jobs.db")
    asked = jobs.create(name="Morning digest", schedule_text="every day at 9",
                        action={"type": "ask", "prompt": "Run the alpha skill and report.", "agent": "jarvis"})
    jobs.create(name="Unrelated", schedule_text="every day at 9",
                action={"type": "remind", "message": "drink water"})
    rows = {"skills_only": "alpha,beta", "skills_disabled": ""}
    monkeypatch.setattr(load_set, "_setting", lambda key: rows.get(key, ""))
    monkeypatch.setattr(switches, "state", lambda: {"disabled": ["Alpha"], "channel_disabled": {"voice": ["alpha"]}})
    holders = references.hub_holders(SimpleNamespace(
        jobs=SimpleNamespace(store=jobs),
        skill_proposals=SimpleNamespace(list=lambda status=None: [{"id": "sp-1", "skill": "alpha"}]),
        skill_batches=SimpleNamespace(list=lambda status=None: [{"id": "sb-9", "skills": ["alpha", "beta"]}])))
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}], holders=holders)
    assert out["ok"] is True, out
    left = _ref(out, "alpha")["left"]
    assert {"holder": "job", "id": asked.id, "name": "Morning digest", "field": "prompt", "lines": [1]} in left
    assert not any(e.get("name") == "Unrelated" for e in left)
    assert {"holder": "load_set", "setting": "loadset.skills_only", "skill": "alpha"} in left
    assert any(e.get("warning") and "'omega' is not in skills_only" in e["warning"] for e in left)
    assert {"holder": "switch", "setting": "skills.disabled", "skill": "alpha"} in left
    assert {"holder": "switch", "setting": "skills.channel_disabled", "channel": "voice", "skill": "alpha"} in left
    assert {"holder": "proposal", "id": "sp-1", "skill": "alpha"} in left
    assert {"holder": "batch", "id": "sb-9", "skill": "alpha"} in left
    # Reported, not rewritten: the job's prompt and the owner's lists are as they were.
    assert jobs.get(asked.id).action["prompt"] == "Run the alpha skill and report."
    assert rows["skills_only"] == "alpha,beta"


# ── governance ───────────────────────────────────────────────────────────────────────

def _deny_kernel(monkeypatch, verdict="deny"):
    from agents.core import kernel
    from agents.core.kernel import binding

    seen = []

    def action_kernel(action, *a, **kw):
        seen.append(action)
        return kernel.Decision(kernel.Verdict(verdict), reason="halted")

    monkeypatch.setattr(kernel, "kernel_enabled", lambda: True)
    monkeypatch.setattr(binding, "make_action_kernel", lambda orch, **kw: action_kernel)
    return seen


def test_a_delete_crosses_the_skill_install_kernel_gate_before_anything_moves(hub, monkeypatch):
    hub.write("alpha")
    hub.write("beta")
    hub.write("omega")
    hub.load()
    _bundle("research", ["alpha"])
    seen = _deny_kernel(monkeypatch)
    before, bundle_before = hub.tree(), bundles.get("research").path.read_bytes()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"},
                     {"name": "beta", "action": "patch", "old_string": "Do", "new_string": "Make"}])
    assert out["ok"] is False and out["reason"] == "skill_batch_kernel_denied", out
    assert hub.tree() == before and bundles.get("research").path.read_bytes() == bundle_before
    [action] = seen                                  # the delete is asked first; its DENY ends it
    assert action.kind == "skill.install" and action.payload["operation"] == "delete"
    assert action.payload["names"] == ["alpha"] and action.payload["absorbed_into"] == {"alpha": "omega"}
    assert out["kernel_kind"] == "skill.install"
    # A QUEUE is the owner decision the batch carries: both kinds are asked, and it lands.
    seen = _deny_kernel(monkeypatch, verdict="queue")
    assert _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"},
                      {"name": "beta", "action": "patch", "old_string": "Do", "new_string": "Make"}])["ok"] is True
    assert [a.kind for a in seen] == ["skill.install", "skill.generation"]
    assert seen[1].payload["changed"] == ["beta"] and seen[1].payload["bundles"] == ["research"]


def test_every_other_batch_write_crosses_skill_generation_before_anything_moves(hub, monkeypatch):
    # Fails on the old code: only a delete reached the kernel, so a patch, a file write and
    # a create landed under a DENY (review-H330 r1).
    hub.write("beta")
    hub.load()
    seen = _deny_kernel(monkeypatch)
    before = hub.tree()
    for ops in ([{"name": "beta", "action": "patch", "old_string": "Do", "new_string": "Make"}],
                [{"name": "beta", "action": "write_file", "file_path": "references/x.md", "file_content": "x"}],
                [{"name": "gamma", "action": "create", "content": _md("gamma")}]):
        out = _run(hub, ops)
        assert out["reason"] == "skill_batch_kernel_denied" and out["kernel_kind"] == "skill.generation", out
        assert hub.tree() == before
    assert [a.kind for a in seen] == ["skill.generation"] * 3
    assert seen[0].payload["changed"] == ["beta"] and seen[2].payload["created"] == ["gamma"]
    # A dry run moves nothing, so it asks nothing.
    assert _run(hub, [{"name": "beta", "action": "patch", "old_string": "Do", "new_string": "Make"}],
                dry_run=True)["ok"] is True
    assert len(seen) == 3


def _real_kernel_hub(monkeypatch, tmp_path, loader=None):
    """The production default gates against a real kernel: a real policy and kill switch."""
    import agents.web as web
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    switch = KillSwitch(tmp_path / "kill.json")
    monkeypatch.setattr(web, "orch", SimpleNamespace(kill_switch=switch, capabilities=CapabilityBroker(),
                                                     autonomy_policy=AutonomyPolicy(), intent_log=None,
                                                     skills=loader))
    return switch


def test_a_halt_stops_every_skill_write_through_the_real_kernel(hub, monkeypatch, tmp_path):
    # Fails on the old code: with the kill switch engaged a delete was refused, but a
    # patch-only batch on the same hub applied (review-H330 r1, reproduced with the real kernel).
    hub.write("alpha")
    hub.write("beta")
    hub.load()
    switch = _real_kernel_hub(monkeypatch, tmp_path)
    patch = [{"name": "beta", "action": "patch", "old_string": "Do", "new_string": "Make"}]
    assert run_batch(patch, hub.loader, backup_dir=hub.archive, holders=_holders())["ok"] is True
    switch.engage(reason="test")
    before = hub.tree()
    out = run_batch([{"name": "beta", "action": "patch", "old_string": "Make", "new_string": "Do"}], hub.loader,
                    backup_dir=hub.archive, holders=_holders())
    assert out["reason"] == "skill_batch_kernel_denied" and out["kernel_kind"] == "skill.generation", out
    out = _run(hub, [{"name": "alpha", "action": "delete"}])
    assert out["reason"] == "skill_batch_kernel_denied" and out["kernel_kind"] == "skill.install"
    assert hub.tree() == before


def test_promoting_a_generated_skill_crosses_the_kernel(hub, monkeypatch, tmp_path):
    # Fails on the old code: approve_generated_skill signed and activated LLM-authored code
    # behind admin_guard alone; the kernel (and so the kill switch) was never asked.
    from fastapi.testclient import TestClient

    import agents.web as web

    hub.load()
    switch = _real_kernel_hub(monkeypatch, tmp_path, loader=hub.loader)
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h330-admin")
    name = hub.loader.generate_skill("pepper", "organize the morning inbox", ["read", "label"], "tidy_inbox")
    assert name and (hub.root / name / "PENDING_REVIEW").exists()
    switch.engage(reason="test")
    client = TestClient(web.app)
    reviewed = hub.loader.pending_skill_fingerprint(name)
    refused = client.post(f"/api/skills/{name}/approve", headers=ADMIN,
                          json={"expected_fingerprint": reviewed})
    assert refused.status_code == 403 and refused.json()["reason"] == "kernel_denied", refused.json()
    assert (hub.root / name / "PENDING_REVIEW").exists() and not (hub.root / name / "SKILL.sig").exists()
    # A halted kernel also stops a new generated skill before its folder exists.
    assert hub.loader.generate_skill("pepper", "summarize the evening news", ["read"], "news") is None
    assert not any(p.name.startswith("summarize") for p in hub.root.iterdir())
    switch.disengage()
    approved = client.post(f"/api/skills/{name}/approve", headers=ADMIN,
                           json={"expected_fingerprint": reviewed})
    assert approved.status_code == 200 and approved.json()["approved"] is True, approved.json()
    assert not (hub.root / name / "PENDING_REVIEW").exists()


def test_an_approved_skill_change_crosses_the_kernel_before_it_is_written(hub, monkeypatch, tmp_path):
    # Fails on the old code: an approved SKILL.md proposal was written under a halt, with
    # no kernel crossing at all.
    from agents.core.skills.proposals import STATUS_APPROVED, SkillProposalStore

    hub.write("alpha")
    hub.load()
    store = SkillProposalStore(tmp_path / "proposals.json")
    current = (hub.root / "alpha" / "SKILL.md").read_text()
    rec = store.propose("alpha", current, current.replace("Do the thing.", "Make the thing."))
    store.mark(rec["id"], STATUS_APPROVED)
    switch = _real_kernel_hub(monkeypatch, tmp_path)
    switch.engage(reason="test")
    out = store.apply(rec["id"], hub.loader, tmp_path / "backups")
    assert out == {"ok": False, "reason": "kernel_denied"}, out
    assert (hub.root / "alpha" / "SKILL.md").read_text() == current and store.get(rec["id"])["status"] == "approved"
    switch.disengage()
    assert store.apply(rec["id"], hub.loader, tmp_path / "backups")["ok"] is True
    assert "Make the thing." in (hub.root / "alpha" / "SKILL.md").read_text()
    # What the gate is asked: a skill.generation patch of this skill.
    seen = []
    rec = store.propose("alpha", (hub.root / "alpha" / "SKILL.md").read_text(), _md("alpha", "## Steps\n\nx\n"))
    store.mark(rec["id"], STATUS_APPROVED)
    store.apply(rec["id"], hub.loader, tmp_path / "backups", kernel_gate=lambda p: seen.append(p) or "deny")
    assert seen[0]["kind"] == "skill.generation" and seen[0]["action"] == "patch" and seen[0]["skill"] == "alpha"


def test_a_kernel_gate_that_fails_refuses_the_delete(hub):
    hub.write("alpha")
    hub.load()
    before = hub.tree()

    def broken(_payload):
        raise RuntimeError("kernel down")

    out = _run(hub, [{"name": "alpha", "action": "delete"}], delete_gate=broken)
    assert out["reason"] == "skill_batch_kernel_error" and hub.tree() == before


def test_a_create_in_a_delete_batch_crosses_the_skill_generation_contract(hub, monkeypatch):
    hub.write("alpha")
    hub.load()
    seen = []

    def contract(payload):
        seen.append(payload)
        return payload["name"] != "forbidden"

    monkeypatch.setattr(loader_mod, "_skill_generation_allowed", contract)
    before = hub.tree()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "forbidden"},
                     {"name": "forbidden", "action": "create", "content": _md("forbidden")}])
    assert out["reason"] == "skill_batch_generation_refused" and hub.tree() == before
    assert seen[-1] == {"action": "generate", "agent": "owner", "name": "forbidden"}
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "fine"},
                     {"name": "fine", "action": "create", "content": _md("fine")}])
    assert out["ok"] is True and seen[-1]["name"] == "fine"


# ── the real entry points: the owner's route, the model's tool, the card ─────────────

@pytest.fixture()
def client(hub, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import agents.web as web
    from agents.core import paths

    hub.write("alpha")
    hub.write("omega")
    rel = hub.root / "rel"
    rel.mkdir()
    (rel / "SKILL.md").write_text(_related_md("rel", "related_skills: [alpha]\n"))
    hub.write("prose", body="## Steps\n\nCall alpha.\n")
    hub.load()
    hub.store = SkillBatchStore(hub.tmp / "batches.json")
    hub.queue = ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    hub.jobs = JobStore(tmp_path / "jobs.db")
    monkeypatch.setattr(paths, "data_path", lambda *parts: hub.tmp.joinpath("data", *[str(p) for p in parts]))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h330-admin")
    monkeypatch.setattr(web, "orch", SimpleNamespace(skills=hub.loader, skill_batches=hub.store,
                                                     action_approvals=hub.queue,
                                                     jobs=SimpleNamespace(store=hub.jobs)))
    _bundle("research", ["alpha"])
    return TestClient(web.app)


ADMIN = {"X-Admin-Token": "h330-admin"}
OPS = [{"name": "alpha", "action": "delete", "absorbed_into": "omega"},
       {"name": "prose", "action": "patch", "old_string": "Call alpha.", "new_string": "Call omega."}]


def test_the_owner_route_deletes_migrates_and_reports_in_one_batch(hub, client):
    job = hub.jobs.create(name="Daily", schedule_text="every day at 9",
                          action={"type": "ask", "prompt": "use alpha", "agent": "jarvis"})
    dry = client.post("/api/skills/batch", json={"operations": OPS, "dry_run": True}, headers=ADMIN)
    assert dry.status_code == 200 and (hub.root / "alpha").exists(), dry.json()
    assert {s["name"] for s in dry.json()["skills"]} == {"alpha", "prose", "rel"}
    done = client.post("/api/skills/batch", json={"operations": OPS}, headers=ADMIN)
    body = done.json()
    assert done.status_code == 200 and body["applied"] is True, body
    assert not (hub.root / "alpha").exists() and "Call omega." in (hub.root / "prose" / "SKILL.md").read_text()
    assert references.related_names((hub.root / "rel" / "SKILL.md").read_text()) == ["omega"]
    assert list(bundles.get("research").skills) == ["omega"]
    ref = _ref(body, "alpha")
    assert {(m["holder"], m["name"]) for m in ref["migrated"]} == {("skill", "rel"), ("bundle", "research")}
    assert ref["left"] == [{"holder": "job", "id": job.id, "name": "Daily", "field": "prompt", "lines": [1]}]


def test_the_owner_route_crosses_the_kernel_for_a_delete(hub, client, monkeypatch):
    seen = _deny_kernel(monkeypatch)
    before = hub.tree()
    refused = client.post("/api/skills/batch", json={"operations": OPS}, headers=ADMIN)
    assert refused.status_code == 422 and refused.json()["reason"] == "skill_batch_kernel_denied"
    assert hub.tree() == before and list(bundles.get("research").skills) == ["alpha"]
    assert seen and seen[0].kind == "skill.install"


def test_the_model_proposes_delete_and_edits_and_the_card_applies_them_whole(hub, client):
    server = _server(hub, hub.store, hub.queue)
    got = _propose(server, {"operations": OPS})
    assert got["ok"] is True and got["kind"] == "batch", got
    assert hub.tree()["alpha/SKILL.md"]                                         # nothing yet
    ref = _ref(got, "alpha")
    assert {(m["holder"], m["name"]) for m in ref["migrated"]} == {("skill", "rel"), ("bundle", "research")}
    rec = hub.store.get(got["batch_id"])
    assert rec["expect"]["rel"] and set(rec["skills"]) == {"alpha", "prose", "rel"}    # rel pinned too
    listed = client.get("/api/skills/batches", headers=ADMIN).json()["batches"][0]
    assert listed["references"][0]["absorbed_into"] == "omega"
    reply = client.post(f"/api/actions/{rec['card']}/decide", json={"approved": True}, headers=ADMIN).json()
    applied = reply["action"]["applied"]
    assert applied["ok"] is True, applied
    assert not (hub.root / "alpha").exists() and list(bundles.get("research").skills) == ["omega"]
    assert references.related_names((hub.root / "rel" / "SKILL.md").read_text()) == ["omega"]
    assert hub.store.get(got["batch_id"])["status"] == "applied"


def test_the_decide_route_crosses_the_kernel_and_a_deny_applies_nothing(hub, client, monkeypatch):
    got = _propose(_server(hub, hub.store, hub.queue), {"operations": OPS})
    card = hub.store.get(got["batch_id"])["card"]
    seen = _deny_kernel(monkeypatch)
    before = hub.tree()
    reply = client.post(f"/api/actions/{card}/decide", json={"approved": True}, headers=ADMIN).json()
    assert reply["action"]["applied"]["reason"] == "skill_batch_kernel_denied"
    assert hub.tree() == before and list(bundles.get("research").skills) == ["alpha"]
    assert hub.store.get(got["batch_id"])["status"] == "failed" and seen[0].kind == "skill.install"


def test_a_migrated_skill_that_changes_after_the_proposal_is_not_applied(hub, client):
    got = _propose(_server(hub, hub.store, hub.queue), {"operations": OPS})
    rel = hub.root / "rel" / "SKILL.md"
    rel.write_text(rel.read_text() + "\nedited by hand\n")
    before = hub.tree()
    card = hub.store.get(got["batch_id"])["card"]
    reply = client.post(f"/api/actions/{card}/decide", json={"approved": True}, headers=ADMIN).json()
    assert reply["action"]["applied"]["reason"] == "skill_batch_drifted" and hub.tree() == before


def test_a_governed_apply_rewrites_only_the_bundles_the_owner_saw(hub, client):
    got = _propose(_server(hub, hub.store, hub.queue), {"operations": OPS})
    _bundle("late", ["alpha"])                                     # made after the review
    card = hub.store.get(got["batch_id"])["card"]
    reply = client.post(f"/api/actions/{card}/decide", json={"approved": True}, headers=ADMIN).json()
    applied = reply["action"]["applied"]
    assert applied["ok"] is True and list(bundles.get("research").skills) == ["omega"]
    assert list(bundles.get("late").skills) == ["alpha"]
    assert {"holder": "bundle", "name": "late", "slug": "late", "skill": "alpha", "member": "alpha",
            "why": "not in the batch the owner approved"} in _ref(applied, "alpha")["left"]


def test_the_tool_reports_what_is_left_with_a_hint_and_hides_what_the_agent_cannot_see(hub, monkeypatch):
    hub.write("alpha")
    hub.write("omega")
    hub.write("secret", body="## Steps\n\nalpha inside.\n")
    hub.write("open", body="## Steps\n\nalpha here too.\n")
    hub.load()
    from agents.core.skills import tools as tools_mod

    real_gate = tools_mod._gate
    monkeypatch.setattr(tools_mod, "_gate",
                        lambda target, name, agent="": None if name == "secret" else real_gate(target, name, agent))
    store, queue = SkillBatchStore(hub.tmp / "b.json"), _Queue()
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    ref = _ref(got, "alpha")
    assert ref["hidden"] == 1 and not any(e.get("name") == "secret" for e in ref["left"])
    assert {"holder": "skill", "name": "open", "field": "text", "file": "SKILL.md", "lines": [7]} in ref["left"]
    assert got["hints"] and "patch" in got["hints"][0]
    # An absorbing skill the agent may not see answers as one that does not exist.
    refused = _propose(_server(hub, store, queue), {"operations": [
        {"name": "omega", "action": "delete", "absorbed_into": "secret"}]})
    assert refused["ok"] is False and refused["failed_op"]["index"] == 0
    assert json.dumps(refused).count("secret") == 1                       # only the name it asked for


def test_the_card_tool_and_store_keep_old_records_working(hub):
    # A batch recorded before H330 carries no references: it still applies, rewriting no bundle.
    hub.write("alpha")
    hub.load()
    store, queue = SkillBatchStore(hub.tmp / "b.json"), _Queue()
    rec = store.propose([{"name": "alpha", "action": "patch", "old_string": "Do", "new_string": "Make"}],
                        expect=batch_mod.fingerprints([{"name": "alpha", "action": "patch"}], hub.loader),
                        preview=[], origin="agent:friday")
    assert "references" not in rec
    card = store.queue_card(rec["id"], queue, agent="friday", summary="s")
    assert queue.get(card)["tool"] == CARD_TOOL
    queue.decide(card, True)
    out = store.decide(rec["id"], card, queue, hub.loader, backup_dir=hub.archive, holders=_holders())
    assert out["ok"] is True and "Make the thing." in (hub.root / "alpha" / "SKILL.md").read_text()


def test_rewrite_related_is_exact_or_nothing():
    flow = _related_md("x", "related_skills: [alpha, beta]  # comment\n")
    assert references.related_names(references.rewrite_related(flow, {"alpha"}, "omega")) == ["omega", "beta"]
    same_indent = _related_md("x", "related_skills:\n- alpha\n- beta\ntags: [t]\n")
    out = references.rewrite_related(same_indent, {"alpha"}, "beta")
    assert references.related_names(out) == ["beta"] and "tags: [t]" in out
    quoted = _related_md("x", "related_skills: ['alpha', \"2fa\"]\n")
    assert references.related_names(references.rewrite_related(quoted, {"alpha"}, "omega")) == ["omega", "2fa"]
    # A scalar list or a file that names nothing to move is not rewritten by hand.
    assert references.rewrite_related(_related_md("x", "related_skills: alpha, beta\n"), {"alpha"}, "o") is None
    assert references.rewrite_related(_related_md("x", "related_skills: [beta]\n"), {"alpha"}, "o") is None
    body = _related_md("x", "related_skills: [alpha]\n", body="alpha stays in the body\n")
    assert references.rewrite_related(body, {"alpha"}, "omega").endswith("alpha stays in the body\n")
    assert references.mention_lines("alphabet\nthe alpha.\nalpha-two\nx/alpha\n", {"alpha"}) == [2, 4]


def test_the_tool_schema_takes_absorbed_into():
    from agents.core.skills.tools import PROPOSE_DESCRIPTION, PROPOSE_SCHEMA

    item = PROPOSE_SCHEMA["properties"]["operations"]["items"]
    assert item["properties"]["absorbed_into"]["type"] == "string"
    assert "absorbed_into" in PROPOSE_DESCRIPTION and "only as the sole op" not in PROPOSE_DESCRIPTION


# ── review-H330 r1: what the model sees, and the governed apply is the batch approved ──

def _hide(monkeypatch, *hidden):
    from agents.core.skills import tools as tools_mod

    real_gate = tools_mod._gate
    monkeypatch.setattr(tools_mod, "_gate",
                        lambda target, name, agent="": None if name in hidden else real_gate(target, name, agent))


def test_a_bundle_member_the_agent_cannot_see_is_counted_never_named(hub, monkeypatch):
    # Fails on the old code: the bundle's before/after member lists reached the model whole,
    # naming a skill the agent may not see (review-H330 r1).
    hub.write("alpha")
    hub.write("omega")
    hub.write("secretskill")
    hub.load()
    _bundle("research", ["alpha", "secretskill"])
    _hide(monkeypatch, "secretskill")
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    assert got["ok"] is True, got
    assert "secretskill" not in json.dumps(got)
    [moved] = [m for m in _ref(got, "alpha")["migrated"] if m["holder"] == "bundle"]
    assert moved == {"holder": "bundle", "name": "research", "slug": "research", "before": ["alpha"],
                     "after": ["omega"], "hidden_members": 1}
    rec = store.get(got["batch_id"])
    assert "secretskill" not in json.dumps(rec.get("references")) and "bundle_pins" not in got
    # The owner's approval still rewrites the bundle whole, the hidden member kept.
    queue.decide(rec["card"], True)
    out = store.decide(rec["id"], rec["card"], queue, hub.loader, backup_dir=hub.archive, holders=_holders())
    assert out["ok"] is True, out
    assert list(bundles.get("research").skills) == ["omega", "secretskill"]


def test_an_approved_bundle_migration_that_cannot_be_read_refuses_the_apply(hub):
    # Fails on the old code: the delete landed (ok: true) and the bundle the owner saw
    # rewritten still named the deleted skill (review-H330 r1).
    hub.write("alpha")
    hub.write("omega")
    hub.load()
    _bundle("research", ["alpha"])
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    rec = store.get(got["batch_id"])
    queue.decide(rec["card"], True)

    def broken():
        raise OSError("bundles folder unreadable")

    before = hub.tree()
    out = store.decide(rec["id"], rec["card"], queue, hub.loader, backup_dir=hub.archive,
                       holders=_holders(bundles=broken))
    assert out["ok"] is False and out["reason"] == "skill_batch_bundles_unreadable", out
    assert hub.tree() == before and list(bundles.get("research").skills) == ["alpha"]
    assert store.get(rec["id"])["status"] == "failed"


def test_a_bundle_changed_after_the_review_is_drift(hub):
    hub.write("alpha")
    hub.write("beta")
    hub.write("omega")
    hub.load()
    _bundle("research", ["alpha"])
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    rec = store.get(got["batch_id"])
    bundles.save("research", ["alpha", "beta"], description="the research bundle", overwrite=True)
    queue.decide(rec["card"], True)
    before = hub.tree()
    out = store.decide(rec["id"], rec["card"], queue, hub.loader, backup_dir=hub.archive, holders=_holders())
    assert out["reason"] == "skill_batch_drifted" and "research" in out["detail"], out
    assert hub.tree() == before and list(bundles.get("research").skills) == ["alpha", "beta"]


def test_a_migrated_skill_the_apply_could_no_longer_rewrite_is_drift(hub, client):
    # Fails on the old code: rel, shown rewritten in the review and then put in quarantine,
    # was dropped from the migration silently and the delete landed (review-H330 r1 minor b).
    got = _propose(_server(hub, hub.store, hub.queue), {"operations": OPS})
    (hub.root / "rel" / "PENDING_REVIEW").write_text("")
    before = hub.tree()
    card = hub.store.get(got["batch_id"])["card"]
    reply = client.post(f"/api/actions/{card}/decide", json={"approved": True}, headers=ADMIN).json()
    applied = reply["action"]["applied"]
    assert applied["reason"] == "skill_batch_drifted" and "'rel'" in applied["detail"], applied
    assert hub.tree() == before and list(bundles.get("research").skills) == ["alpha"]


def test_a_load_set_that_cannot_be_read_is_reported_unreadable(hub):
    # Fails on the old code: a failing load-set read answered as "nothing names it".
    hub.write("alpha")
    hub.load()

    def broken():
        raise RuntimeError("settings db locked")

    out = _run(hub, [{"name": "alpha", "action": "delete"}], holders=_holders(load_set=broken))
    assert {"holder": "load_set", "unreadable": True} in _ref(out, "alpha")["left"]


def test_the_absorbing_skill_never_lists_itself_as_related(hub):
    # Fails on the old code: omega's related_skills [alpha, beta] became [omega, beta].
    hub.write("alpha")
    hub.write("beta")
    omega = hub.root / "omega"
    omega.mkdir()
    (omega / "SKILL.md").write_text(_related_md("omega", "related_skills: [alpha, beta]\n"))
    only = hub.root / "only"
    only.mkdir()
    (only / "SKILL.md").write_text(_related_md("only", "related_skills:\n  - alpha\ntags: [t]\n"))
    hub.load()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True, out
    assert references.related_names((omega / "SKILL.md").read_text()) == ["beta"]
    assert references.related_names((only / "SKILL.md").read_text()) == ["omega"]
    moved = {m["name"]: m for m in _ref(out, "alpha")["migrated"] if m["holder"] == "skill"}
    assert moved["omega"].get("dropped") is True and "dropped" not in moved["only"]
    # Its only entry gone, the absorbing skill keeps an empty list and every other key.
    lone = _related_md("omega", "related_skills:\n  - alpha\ntags: [t]\n")
    text = references.rewrite_related(lone, {"alpha"}, None)
    assert references.related_names(text) == [] and "related_skills: []" in text and "tags: [t]" in text


# ── review-H330 r2: the card names what the apply moves; a migration keeps every entry ──

def _frontmatter(path: Path) -> dict:
    from agents.core.skills.frontmatter import split_frontmatter

    fm, _body = split_frontmatter(path.read_text(), lenient=False)
    return fm


@pytest.mark.parametrize("spelling", ["path", "case", "other_case"])
def test_a_bundle_member_is_shown_as_the_skill_it_resolves_to(hub, monkeypatch, spelling):
    # Fails on the old code: a member naming alpha by its path or as "Alpha" (or beta as
    # "Beta") was judged by its raw text, so the card the owner approved said
    # "beta -> omega, beta (and 1 member the agent cannot see, kept)" while the apply moved
    # that member (review-H330 r2).
    hub.write("alpha")
    hub.write("omega")
    hub.write("beta")
    hub.write("secretskill")
    hub.load()
    _hide(monkeypatch, "secretskill")
    first = {"path": str(hub.root / "alpha"), "case": "Alpha", "other_case": "alpha"}[spelling]
    second = "Beta" if spelling == "other_case" else "beta"
    _bundle("research", [first, second, "SecretSkill"])
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    assert got["ok"] is True, got
    rec = store.get(got["batch_id"])
    for view in (_ref(got, "alpha"), rec["references"][0]):
        [moved] = [m for m in view["migrated"] if m["holder"] == "bundle"]
        # The hidden skill, in whatever case the bundle spells it, is still counted, never named.
        assert moved == {"holder": "bundle", "name": "research", "slug": "research", "before": [first, second],
                         "after": ["omega", second], "hidden_members": 1}, moved
    assert "secretskill" not in json.dumps(got).casefold()
    queue.decide(rec["card"], True)
    out = store.decide(rec["id"], rec["card"], queue, hub.loader, backup_dir=hub.archive, holders=_holders())
    assert out["ok"] is True, out
    # What the card said is what landed.
    assert list(bundles.get("research").skills) == ["omega", second, "SecretSkill"]


def test_a_long_related_list_is_migrated_whole(hub):
    # Fails on the old code: the check compared the loader's capped views (64 entries), so
    # rel's SKILL.md was written back as [omega, s0..s62] and 17 entries were gone.
    hub.write("alpha")
    hub.write("omega")
    rel = hub.root / "rel"
    rel.mkdir()
    names = ["alpha"] + [f"s{i}" for i in range(80)] + ["s3"]
    (rel / "SKILL.md").write_text(_related_md("rel", "related_skills: [" + ", ".join(names) + "]\n"))
    hub.load()
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True, out
    # Every other entry kept as written, where it was, the repeated one too.
    assert _frontmatter(rel / "SKILL.md")["related_skills"] == ["omega"] + names[1:]
    assert {"holder": "skill", "name": "rel", "field": "related_skills"} in _ref(out, "alpha")["migrated"]


@pytest.mark.parametrize("related", [
    "related_skills:\n  - alpha\n  - {x: y}\n  - true\n",
    "related_skills: [alpha, 7]\n",
    "related_skills:\n  alpha, beta\n",
])
def test_a_related_value_that_is_not_a_list_of_names_is_reported_not_rewritten(hub, related):
    # Fails on the old code: [alpha, {x: y}, true] became [omega, "True"] (the mapping item
    # dropped, the boolean turned to a string), [alpha, 7] became [omega, "7"], and the
    # scalar "alpha, beta" under the key became a block list (review-H330 r2).
    hub.write("alpha")
    hub.write("omega")
    rel = hub.root / "rel"
    rel.mkdir()
    text = _related_md("rel", related)
    (rel / "SKILL.md").write_text(text)
    hub.load()
    assert references.rewrite_related(text, {"alpha"}, "omega") is None
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}])
    assert out["ok"] is True, out
    assert (rel / "SKILL.md").read_text() == text
    assert "rel" not in {s["name"] for s in out["skills"]}
    assert {"holder": "skill", "name": "rel", "field": "related_skills",
            "why": "its related_skills could not be rewritten exactly"} in _ref(out, "alpha")["left"]


def test_rewrite_related_moves_only_the_entries_naming_the_deleted_skill():
    # Fails on the old code: every repeated entry was folded into one ([alpha, b, b] became
    # [omega, b]). An entry the loader reads as alpha (quoted with spaces) is moved too.
    out = references.rewrite_related(_related_md("x", "related_skills: [alpha, b, b]\n"), {"alpha"}, "omega")
    assert "related_skills: [omega, b, b]" in out
    spaced = references.rewrite_related(_related_md("x", "related_skills: [' alpha ', b]\n"), {"alpha"}, "omega")
    assert "related_skills: [omega, b]" in spaced
    # A list that names alpha only in another key's mapping item is not this rewrite's.
    nested = _related_md("x", "related_skills: [beta]\nextra:\n  related_skills: [alpha]\n")
    assert references.rewrite_related(nested, {"alpha"}, "omega") is None


def _break(bundle) -> None:
    bundle.path.write_text("name: research\nskills: [alpha\n")      # no longer parses


def test_a_bundle_file_that_does_not_parse_is_reported_as_not_checked(hub, monkeypatch):
    # Fails on the old code: the folder read's skipped files were dropped, so a bundle that
    # may list the deleted skill was neither migrated nor reported (review-H330 r2 minor 5).
    hub.write("alpha")
    hub.write("omega")
    hub.load()
    _break(_bundle("research", ["alpha"]))
    out = _run(hub, [{"name": "alpha", "action": "delete", "absorbed_into": "omega"}], dry_run=True)
    assert {"holder": "bundle", "skill": "alpha", "file": "research.yaml", "unreadable": True,
            "why": "invalid_yaml"} in _ref(out, "alpha")["left"]
    # The agent is told a bundle file was not checked, without the file's name.
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    assert got["ok"] is True, got
    assert {"holder": "bundle", "skill": "alpha", "unreadable": True, "why": "invalid_yaml"} in _ref(got, "alpha")["left"]
    assert "research.yaml" not in json.dumps(got)


@pytest.mark.parametrize("change", ["no_longer_parses", "no_longer_lists_it"])
def test_an_approved_bundle_rewrite_the_apply_would_not_make_refuses_it(hub, change):
    # Fails on the old code: the owner approved "research: alpha -> omega", the bundle's file
    # then stopped parsing (or stopped listing alpha), and the delete landed with that rewrite
    # silently gone from the batch and from its report (review-H330 r2).
    hub.write("alpha")
    hub.write("omega")
    hub.load()
    bundle = _bundle("research", ["alpha", "omega"])
    store, queue = SkillBatchStore(hub.tmp / "b.json"), ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    got = _propose(_server(hub, store, queue), {"operations": [
        {"name": "alpha", "action": "delete", "absorbed_into": "omega"}]})
    rec = store.get(got["batch_id"])
    assert [m["slug"] for m in rec["references"][0]["migrated"] if m["holder"] == "bundle"] == ["research"]
    if change == "no_longer_parses":
        _break(bundle)
    else:
        bundles.save("research", ["omega"], description="the research bundle", overwrite=True)
    before = hub.tree()
    queue.decide(rec["card"], True)
    out = store.decide(rec["id"], rec["card"], queue, hub.loader, backup_dir=hub.archive, holders=_holders())
    assert out["ok"] is False and out["reason"] == "skill_batch_drifted", out
    assert "'research'" in out["detail"] and hub.tree() == before and (hub.root / "alpha").is_dir()
