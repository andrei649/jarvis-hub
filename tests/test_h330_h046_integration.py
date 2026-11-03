"""Hermes batch 3 integration — where H330 (a skill delete reports what still names it),
H046 (the learning journey forgets and lists learned skills) and H389 (pruned skill
copies and their reload notice) meet once merged.

- A learned skill the journey archives (route, `nerva journey delete`, the TODAY card) goes
  through the skill batch's delete, and the owner is told what still names it: a bundle,
  another skill's ``related_skills`` or prose. Nothing is left pointing at a gone skill
  without anyone being told (references.py).
- A pending batch that names the deleted skill as its ``absorbed_into`` is reported: it
  can no longer apply.
- Prose and job prompts name a skill the way a sentence does, in any case; a reference is
  found whatever its case, as bundle members and switches are.
- A skill the agent's own batch created (Hermes ``skill_manage create``, applied on the
  owner's card) is a skill the agent learned: the journey lists it from the start.
- The bulk review returns what an apply migrated and left, as one card's decide does.
- A pruned skill that a later ``skill_view`` finds gone stops asking for a reload.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.skills import bundles
from agents.core.skills import tools as skill_tools
from agents.core.skills.batch import SkillBatchStore, run_batch
from agents.core.skills.references import Holders, mention_lines, outside
from tests.test_h046_journey import ADMIN, _cli, _entries, _learn_skill, _skill_path, hub  # noqa: F401


@pytest.fixture(autouse=True)
def _isolated_bundles(tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "bundles_dir", lambda: tmp_path / "skill-bundles")
    monkeypatch.setattr(bundles, "_CACHE", {"dir": None, "key": None, "bundles": {}, "problems": []})


def _named_elsewhere(hub):
    """A learned, approved skill that another skill's related_skills and prose name, and
    that a bundle lists."""
    name = _learn_skill(hub)
    folder = Path(hub.loader.skills[name].path).name
    other = hub.skills_root / "follow-up"
    other.mkdir()
    (other / "SKILL.md").write_text(
        f"---\nname: follow-up\ndescription: Use when following up\nrelated_skills: [{folder}]\n---\n"
        f"## Steps\n\nFirst run {folder}.\n")
    hub.loader.discover()
    bundles.save("notes", [folder, "follow-up"], description="the notes bundle")
    return name, folder


def _left(references):
    return [e for ref in references for e in ref.get("left") or []]


# ── the journey archive reports what still names the skill ─────────────────────


def test_a_journey_archive_reports_what_still_names_the_skill(hub):
    name, folder = _named_elsewhere(hub)
    gone = hub.client.delete(_skill_path(f"skill:{name}"), headers=ADMIN)
    assert gone.status_code == 200, gone.text
    body = gone.json()
    assert body["ok"] is True and body["archived_to"]
    left = _left(body["references"])
    holders = {(e["holder"], e.get("name"), e.get("field")) for e in left}
    assert ("bundle", "notes", None) in holders                        # the bundle still lists it
    assert ("skill", "follow-up", "related_skills") in holders          # related_skills still names it
    assert any(e["holder"] == "skill" and e.get("name") == "follow-up" and e.get("lines") for e in left)  # prose
    # Reported, not silently rewritten: the journey names no absorbing skill.
    assert folder in bundles.get("notes").skills
    assert folder in (hub.skills_root / "follow-up" / "SKILL.md").read_text()


def test_a_journey_archive_with_nothing_naming_it_reports_an_empty_list(hub):
    name = _learn_skill(hub)
    gone = hub.client.delete(_skill_path(f"skill:{name}"), headers=ADMIN)
    assert gone.status_code == 200, gone.text
    assert _left(gone.json()["references"]) == []


def test_cli_journey_delete_prints_what_still_names_the_skill(hub):
    name, _folder = _named_elsewhere(hub)
    code, out, err, _app = _cli(["journey", "delete", f"skill:{name}", "--yes"], hub,
                                environ={"JARVIS_ADMIN_TOKEN": "t"})
    assert code == 0, err
    assert f"archived skill:{name}" in out
    assert "still names it: bundle notes" in out
    assert "still names it: skill follow-up · related_skills" in out


# ── a pending batch whose absorbing skill is deleted ──────────────────────────


def test_a_pending_batch_absorbing_into_the_deleted_skill_is_reported():
    pending = [{"id": "b1", "skills": ["alpha"],
                "operations": [{"name": "alpha", "action": "delete", "absorbed_into": "Omega"}]}]
    holders = Holders(batches=lambda: pending, switches=lambda: {}, load_set=lambda: {})
    omega = SimpleNamespace(name="omega", path="/skills/omega")
    left = outside("omega", omega, None, holders)
    assert {"holder": "batch", "id": "b1", "skill": "omega"} in left
    # A batch that names neither the skill nor it as an absorber is not reported.
    other = SimpleNamespace(name="beta", path="/skills/beta")
    assert not [e for e in outside("beta", other, None, holders) if e["holder"] == "batch"]


# ── mentions in any case ─────────────────────────────────────────────────────


def test_a_mention_is_found_in_any_case():
    assert mention_lines("Run the Alpha skill daily\nthen rest", {"alpha"}) == [1]
    assert mention_lines("ALPHA first", {"alpha"}) == [1]
    # Still a whole word: a longer name that only contains it is not a mention.
    assert mention_lines("alphabet soup, alpha-two", {"alpha"}) == []


def test_a_job_prompt_naming_the_skill_in_another_case_is_reported():
    job = SimpleNamespace(id="j1", name="morning", action={"prompt": "Run the Alpha skill"})
    holders = Holders(jobs=lambda: [job], switches=lambda: {}, load_set=lambda: {})
    left = outside("alpha", SimpleNamespace(name="alpha", path="/skills/alpha"), None, holders)
    assert {"holder": "job", "id": "j1", "name": "morning", "field": "prompt", "lines": [1]} in left


# ── a skill the agent's batch created is a learned skill ──────────────────────


_MD = "---\nname: file-receipts\ndescription: Use when filing receipts\n---\n## Steps\n\nFile them.\n"


def test_a_skill_the_agents_batch_created_is_on_the_journey(hub):
    out = run_batch([{"name": "file-receipts", "action": "create", "content": _MD}], hub.loader,
                    create_root=hub.skills_root, backup_dir=hub.tmp / "arch", actor="agent:jarvis",
                    holders=Holders())
    assert out["ok"] is True, out
    assert hub.usage.get("file-receipts")["origin"] == "agent"
    ids = [e["entry_id"] for e in _entries(hub, store="skill")["entries"]]
    assert "skill:file-receipts" in ids


def test_a_skill_the_owners_batch_created_is_not_a_learned_one(hub):
    out = run_batch([{"name": "file-receipts", "action": "create", "content": _MD}], hub.loader,
                    create_root=hub.skills_root, backup_dir=hub.tmp / "arch", holders=Holders())
    assert out["ok"] is True, out
    assert (hub.usage.get("file-receipts") or {}).get("origin") != "agent"
    assert "skill:file-receipts" not in [e["entry_id"] for e in _entries(hub, store="skill")["entries"]]


# ── the bulk review keeps the apply's references ──────────────────────────────


def test_the_bulk_review_returns_what_the_apply_left(hub, monkeypatch):
    from agents.core.autonomy.action_approvals import ActionApprovalQueue
    from agents.core.routers import skills as skills_router
    from agents.core.tool_rpc import ToolRPCServer

    name, folder = _named_elsewhere(hub)
    batches = SkillBatchStore(hub.tmp / "batches.json")
    queue = ActionApprovalQueue(path=str(hub.tmp / "actions.json"))
    server = ToolRPCServer()
    skill_tools.register_skill_tools(server, loader=lambda: hub.loader, approvals=lambda: queue,
                                     batches=lambda: batches, session_id=lambda: "web-1",
                                     posture=lambda: "operator/owner", origin=lambda: "hud",
                                     settings=lambda key, default: default)
    import asyncio

    reply = asyncio.run(server.handle({"tool": skill_tools.TOOL_PROPOSE, "args": {
        "operations": [{"name": "follow-up", "action": "delete"}]}}, actor="jarvis"))
    assert reply["ok"] is True and reply["result"].get("batch_id"), reply
    batch_id = reply["result"]["batch_id"]
    # A bundle saved after the review lists the skill: the apply reports it, never rewrites it.
    bundles.save("late", ["follow-up"], description="saved after the review")
    hub.orch.skill_batches, hub.orch.action_approvals = batches, queue
    monkeypatch.setattr(skills_router, "_batch_archive", lambda: hub.tmp / "batch-archive")
    out = hub.client.post("/api/skills/review/bulk", headers=ADMIN,
                          json={"approved": True, "batches": [batch_id]})
    assert out.status_code == 200, out.text
    [row] = out.json()["results"]
    assert row["ok"] is True and row["status"] == "applied", row
    assert any(e["holder"] == "bundle" and e.get("name") == "late" for e in _left(row["references"]))


# ── H389: a pruned skill that is gone stops asking for a reload ───────────────


def _view_call(cid, name):
    return {"role": "assistant", "tool_calls": [{"id": cid, "function": {
        "name": "skill_view", "arguments": json.dumps({"name": name})}}]}


def _rows(name, reload_answer):
    served = json.dumps({"ok": True, "tool": "skill_view",
                         "result": {"ok": True, "name": name, "body": "## Steps\nDo it."}})
    return [_view_call("c1", name), {"role": "tool", "tool_call_id": "c1",
                                     "content": skill_tools.pruned_skill_content(served)},
            _view_call("c2", name), {"role": "tool", "tool_call_id": "c2",
                                     "content": json.dumps({"ok": True, "tool": "skill_view",
                                                            "result": reload_answer})}]


def test_a_pruned_skill_found_gone_on_reload_is_no_longer_pending():
    gone = {"ok": False, "reason": "skill_unknown",
            "detail": "no skill named 'alpha' is available to you: call skills_list"}
    messages = _rows("alpha", gone)
    assert skill_tools.pruned_skills(messages) == []
    assert "skill_view(name='alpha')" not in skill_tools.with_pruned_skill_notice("SYSTEM", messages)


def test_another_refusal_keeps_the_prune_pending():
    busy = {"ok": False, "reason": "skill_unknown_field", "detail": "skill_view takes name, file and reload"}
    messages = _rows("alpha", busy)
    assert skill_tools.pruned_skills(messages) == [("alpha", "")]
