"""H331 — the human review gate before an agent-written skill takes effect, completed.

- The owner reads a quarantined skill's whole content (SKILL.md, its code, every other
  file, the quarantine note and the code-guidance findings) before approving it:
  ``SkillLoader.pending_skill_detail`` + ``GET /api/skills/pending/{name}`` (admin).
- The owner can reject one: ``SkillLoader.discard_generated_skill`` +
  ``POST /api/skills/{name}/discard`` (admin) move its folder out of the skills tree into
  an archive, drop its registry entry and any approval bound to its path. Only a skill
  that awaits review can be discarded.
- Several pending skills, skill-change proposals and skill batches are approved or
  rejected in one move: ``POST /api/skills/review/bulk`` (admin), per-item outcomes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.skills import loader as loader_mod
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.batch import SkillBatchStore
from agents.core.skills.curator import SkillCurator
from agents.core.skills.loader import SkillLoader
from agents.core.skills.proposals import SkillProposalStore
from agents.core.skills.tools import TOOL_PROPOSE, register_skill_tools
from agents.core.tool_rpc import ToolRPCServer

PENDING_REASON = "pending review (CDX-8 quarantine)"


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    for name in ("JARVIS_SKILL_SIGNING_KEY", "JARVIS_REQUIRE_SIGNED_SKILLS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    registry = SkillApprovalStore(tmp_path / "skill_approvals.json")
    loader = SkillLoader(approval_store=registry)
    loader.discover()
    proposals = SkillProposalStore(path=str(tmp_path / "proposals.json"))
    batches = SkillBatchStore(tmp_path / "batches.json")
    queue = ActionApprovalQueue(path=str(tmp_path / "actions.json"))
    curator = SkillCurator(loader, None, proposals=proposals, approvals=queue,
                           archive_dir=str(tmp_path / "archive"))
    server = ToolRPCServer()
    register_skill_tools(server, loader=lambda: loader, proposals=lambda: proposals, approvals=lambda: queue,
                         batches=lambda: batches, session_id=lambda: "web-1",
                         posture=lambda: "operator/owner", origin=lambda: "hud",
                         settings=lambda key, default: default)
    return SimpleNamespace(root=root, tmp=tmp_path, registry=registry, loader=loader, proposals=proposals,
                           batches=batches, queue=queue, curator=curator, server=server,
                           discarded=tmp_path / "discarded")


def _gen(hub, cmd="tidy_inbox", task="organize the morning inbox"):
    folder = hub.loader.generate_skill(agent_id="pepper", task_description=task,
                                       solution_steps=["read inbox", "label", "archive"], command_name=cmd)
    assert folder is not None
    name = next(n for n, s in hub.loader.skills.items() if Path(s.path) == hub.root / folder)
    return folder, name


def _write(hub, name, body="Steps.\n"):
    path = hub.root / name
    path.mkdir()
    (path / "SKILL.md").write_bytes(f"---\nname: {name}\ndescription: {name} helper\n---\n{body}".encode())
    return path


def _call(hub, args):
    reply = asyncio.run(hub.server.handle({"tool": TOOL_PROPOSE, "args": args}, actor="friday"))
    assert reply["ok"] is True, reply
    return reply["result"]


# ── the whole content before approval ─────────────────────────────────────────────

def test_the_detail_carries_skill_md_and_the_code_the_owner_would_approve(hub):
    folder, name = _gen(hub)
    skill_dir = hub.root / folder
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "notes.md").write_text("extra notes\n", encoding="utf-8")
    detail = hub.loader.pending_skill_detail(name)
    assert detail is not None and detail["name"] == name and detail["folder"] == folder
    paths = [f["path"] for f in detail["files"]]
    assert paths[0] == "SKILL.md" and "main.py" in paths and "references/notes.md" in paths
    assert "PENDING_REVIEW" not in paths
    files = {f["path"]: f for f in detail["files"]}
    assert files["main.py"]["text"] == (skill_dir / "main.py").read_text(encoding="utf-8")
    assert files["SKILL.md"]["text"] == (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert files["main.py"]["truncated"] is False and len(files["main.py"]["sha256"]) == 64
    assert "agent=pepper" in detail["review_note"] and "organize the morning inbox" in detail["review_note"]
    assert isinstance(detail["warnings"], list)
    # by the on-disk slug too
    assert hub.loader.pending_skill_detail(folder)["folder"] == folder


def test_the_detail_is_bounded_and_says_what_it_left_out(hub, monkeypatch):
    folder, name = _gen(hub)
    skill_dir = hub.root / folder
    (skill_dir / "big.txt").write_text("x" * 300, encoding="utf-8")
    (skill_dir / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
    monkeypatch.setattr(SkillLoader, "REVIEW_FILE_CHARS", 100)
    files = {f["path"]: f for f in hub.loader.pending_skill_detail(name)["files"]}
    assert files["big.txt"]["truncated"] is True and len(files["big.txt"]["text"]) == 100
    assert files["blob.bin"]["binary"] is True and files["blob.bin"]["text"] is None
    monkeypatch.setattr(SkillLoader, "REVIEW_MAX_FILES", 2)
    detail = hub.loader.pending_skill_detail(name)
    assert len(detail["files"]) == 2 and detail["more_files"] >= 1


def test_no_detail_for_a_skill_that_awaits_no_review_or_a_crafted_name(hub):
    _write(hub, "plan")
    hub.loader.discover()
    assert hub.loader.pending_skill_detail("plan") is None
    assert hub.loader.pending_skill_detail("missing") is None
    for bad in ("..", "../skills", "a/b", ""):
        assert hub.loader.pending_skill_detail(bad) is None


def test_a_symlinked_folder_outside_the_tree_is_never_read(hub, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("secret\n", encoding="utf-8")
    (outside / "PENDING_REVIEW").write_text("x\n", encoding="utf-8")
    (hub.root / "linked").symlink_to(outside, target_is_directory=True)
    assert hub.loader.pending_skill_detail("linked") is None
    assert hub.loader.discard_generated_skill("linked", hub.discarded) is None
    assert (outside / "SKILL.md").exists()


# ── reject / discard ───────────────────────────────────────────────────────────────

def test_discard_moves_the_skill_out_of_the_tree_and_unregisters_it(hub):
    folder, name = _gen(hub)
    dest = hub.loader.discard_generated_skill(name, hub.discarded)
    assert dest is not None and dest.parent == hub.discarded and (dest / "main.py").exists()
    assert not (hub.root / folder).exists()
    assert name not in hub.loader.skills
    hub.loader.discover()
    assert name not in hub.loader.skills
    # the second discard finds nothing
    assert hub.loader.discard_generated_skill(name, hub.discarded) is None


def test_discard_never_touches_a_skill_that_awaits_no_review(hub):
    path = _write(hub, "plan")
    hub.loader.discover()
    assert hub.loader.discard_generated_skill("plan", hub.discarded) is None
    assert (path / "SKILL.md").exists() and "plan" in hub.loader.skills


def test_an_approved_skill_can_no_longer_be_discarded(hub):
    folder, name = _gen(hub)
    assert hub.loader.approve_generated_skill(name) is True
    assert hub.loader.discard_generated_skill(name, hub.discarded) is None
    assert (hub.root / folder / "main.py").exists()


def test_discard_drops_an_approval_bound_to_the_path(hub):
    folder, name = _gen(hub)
    hub.registry.approve(hub.root / folder)      # e.g. a re-import left a stale approval behind
    hub.loader.discard_generated_skill(name, hub.discarded)
    assert not hub.registry.is_approved(hub.root / folder)


def test_two_discards_of_one_name_keep_both_archives(hub):
    _, name = _gen(hub)
    first = hub.loader.discard_generated_skill(name, hub.discarded)
    _, again = _gen(hub)
    second = hub.loader.discard_generated_skill(again, hub.discarded)
    assert first != second and first.exists() and second.exists()


# ── the routes ─────────────────────────────────────────────────────────────────────

ADMIN = {"X-Admin-Token": "h331-admin"}


@pytest.fixture()
def client(hub, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web
    from agents.core.routers import skills as skills_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "h331-admin")
    monkeypatch.setattr(web, "orch", SimpleNamespace(
        skill_proposals=hub.proposals, skill_batches=hub.batches, skills=hub.loader,
        action_approvals=hub.queue, curator=hub.curator))
    monkeypatch.setattr(skills_router, "_discard_archive", lambda: hub.discarded)
    monkeypatch.setattr(skills_router, "_batch_archive", lambda: hub.tmp / "batch-archive")
    return TestClient(web.app)


def test_the_detail_route_serves_the_whole_content(hub, client):
    folder, name = _gen(hub)
    reply = client.get(f"/api/skills/pending/{name}", headers=ADMIN)
    assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
    body = reply.json()
    files = {f["path"]: f for f in body["files"]}
    assert files["main.py"]["text"] == (hub.root / folder / "main.py").read_text(encoding="utf-8")
    assert body["quarantined"] is True
    assert client.get(f"/api/skills/pending/{name}").status_code == 401
    assert client.get("/api/skills/pending/nothing-here", headers=ADMIN).status_code == 404


def test_the_discard_route_rejects_a_pending_skill(hub, client):
    folder, name = _gen(hub)
    assert client.post(f"/api/skills/{name}/discard").status_code == 401
    reply = client.post(f"/api/skills/{name}/discard", headers=ADMIN)
    assert reply.status_code == 200 and reply.json()["discarded"] is True
    assert not (hub.root / folder).exists()
    assert client.get("/api/skills/pending", headers=ADMIN).json()["pending"] == []
    assert client.post(f"/api/skills/{name}/discard", headers=ADMIN).status_code == 404


def _proposal(hub, name):
    got = _call(hub, {"name": name, "content": f"---\nname: {name}\ndescription: {name} helper\n---\nBetter.\n"})
    assert got["ok"] is True and got.get("proposal_id"), got
    return got["proposal_id"]


def _batch(hub, name):
    got = _call(hub, {"operations": [{"name": name, "action": "patch", "old_string": "Steps.",
                                      "new_string": "Better steps."}]})
    assert got["ok"] is True and got.get("batch_id"), got
    return got["batch_id"]


def test_bulk_approve_across_skills_proposals_and_batches(hub, client):
    folder_a, a = _gen(hub, cmd="tidy_inbox")
    folder_b, b = _gen(hub, cmd="file_receipts", task="file the receipts")
    _write(hub, "plan")
    _write(hub, "notes")
    hub.loader.discover()
    proposal = _proposal(hub, "plan")
    batch = _batch(hub, "notes")
    reply = client.post("/api/skills/review/bulk", headers=ADMIN, json={
        "approved": True, "skills": [a, b], "proposals": [proposal], "batches": [batch]})
    assert reply.status_code == 200, reply.text
    out = reply.json()
    assert out["ok"] is True and out["failed"] == 0 and out["decided"] == 4
    assert {(r["kind"], r["id"], r["ok"]) for r in out["results"]} == {
        ("skill", a, True), ("skill", b, True), ("proposal", proposal, True), ("batch", batch, True)}
    for folder in (folder_a, folder_b):
        assert not (hub.root / folder / "PENDING_REVIEW").exists()
    assert hub.loader.skills[a].signature_reason != PENDING_REASON
    assert "Better." in (hub.root / "plan" / "SKILL.md").read_text()
    assert "Better steps." in (hub.root / "notes" / "SKILL.md").read_text()
    assert hub.proposals.get(proposal)["status"] != "pending"
    assert hub.batches.get(batch)["status"] == "applied"


def test_bulk_reject_discards_skills_and_closes_proposals_and_batches(hub, client):
    folder_a, a = _gen(hub, cmd="tidy_inbox")
    _write(hub, "plan")
    _write(hub, "notes")
    hub.loader.discover()
    proposal = _proposal(hub, "plan")
    batch = _batch(hub, "notes")
    reply = client.post("/api/skills/review/bulk", headers=ADMIN, json={
        "approved": False, "skills": [a], "proposals": [proposal], "batches": [batch]})
    out = reply.json()
    assert reply.status_code == 200 and out["ok"] is True and out["decided"] == 3, out
    assert not (hub.root / folder_a).exists() and a not in hub.loader.skills
    assert (hub.root / "plan" / "SKILL.md").read_text().endswith("Steps.\n")
    assert (hub.root / "notes" / "SKILL.md").read_text().endswith("Steps.\n")
    card = hub.proposals.get(proposal)["card"]
    assert hub.queue.get(card)["status"] == "rejected"
    assert hub.batches.get(batch)["status"] == "rejected"


def test_bulk_reports_each_item_and_one_failure_does_not_undo_the_rest(hub, client):
    _, a = _gen(hub)
    reply = client.post("/api/skills/review/bulk", headers=ADMIN, json={
        "approved": True, "skills": [a, "no-such-skill"], "proposals": ["p-missing"], "batches": ["b-missing"]})
    out = reply.json()
    assert reply.status_code == 200 and out["ok"] is False and out["decided"] == 1 and out["failed"] == 3
    by = {(r["kind"], r["id"]): r for r in out["results"]}
    assert by[("skill", a)]["ok"] is True
    assert by[("skill", "no-such-skill")]["error"] == "not_pending"
    assert by[("proposal", "p-missing")]["error"] == "not_found"
    assert by[("batch", "b-missing")]["error"] == "not_found"


def test_bulk_is_admin_only_and_validates_its_body(client):
    assert client.post("/api/skills/review/bulk", json={"approved": True, "skills": ["x"]}).status_code == 401
    assert client.post("/api/skills/review/bulk", headers=ADMIN, json={"skills": ["x"]}).status_code == 422
    assert client.post("/api/skills/review/bulk", headers=ADMIN,
                       json={"approved": True}).status_code == 400
    assert client.post("/api/skills/review/bulk", headers=ADMIN,
                       json={"approved": True, "skills": ["x"] * 51}).status_code == 422
    assert client.post("/api/skills/review/bulk", headers=ADMIN,
                       json={"approved": True, "skills": ["x"], "extra": 1}).status_code == 422


def test_bulk_reports_a_proposal_the_curator_could_not_apply(hub, client):
    # Codex P2 (PR #1279): the skill changed after the proposal was made, so the curator
    # marks it stale and applies nothing; the bulk answer must say so, not report it approved.
    path = _write(hub, "plan")
    hub.loader.discover()
    proposal = _proposal(hub, "plan")
    (path / "SKILL.md").write_bytes(b"---\nname: plan\ndescription: plan helper\n---\nEdited since.\n")
    out = client.post("/api/skills/review/bulk", headers=ADMIN,
                      json={"approved": True, "proposals": [proposal]}).json()
    assert out["ok"] is False and out["failed"] == 1 and out["decided"] == 0, out
    row = out["results"][0]
    assert row["ok"] is False and row["error"] == "drifted_since_proposal" and row["status"] == "stale"
    assert "Edited since." in (path / "SKILL.md").read_text()


def test_bulk_reports_a_curator_that_raised(hub, client, monkeypatch):
    _write(hub, "plan")
    hub.loader.discover()
    proposal = _proposal(hub, "plan")

    def boom():
        raise RuntimeError("apply pass broke")

    monkeypatch.setattr(hub.curator, "apply_decisions", boom)
    out = client.post("/api/skills/review/bulk", headers=ADMIN,
                      json={"approved": True, "proposals": [proposal]}).json()
    assert out["ok"] is False and out["failed"] == 1, out
    assert out["results"][0]["error"] == "apply_error"
