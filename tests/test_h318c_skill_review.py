"""H318, the second review (review-H318b) — its findings, pinned.

- M-1: an approved change to a skill kept none of the skill's standing: a bundled skill
  was unbundled (and, with its code, sandboxed and hidden), a signed skill failed its
  signature and a skill the owner had approved lost the approval. Now a bundled skill is
  refused, and an applied change re-signs what verified and re-approves what the owner
  had approved; a skill nothing vouched for gains no vouch.
- M-2: the owner approved blind. GET /api/skills/proposals (admin) serves each pending
  proposal with its whole diff, built from the ledger; the Decision Inbox shows it.
- m-1: a superseded proposal's card is withdrawn; one card per proposal, whoever proposed.
- m-2: the reviewer's six unpinned mutants.
- m-4: skill_view's file list is bounded. m-5: the backup is named by the directory.
- m-6: only the card a proposal queued decides it. m-7: publishing signs a staged copy.
- n-1: applies run one at a time. n-2: a rename is refused. n-3: every outcome is reported.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.skills import loader as loader_mod
from agents.core.skills import signing
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.curator import SkillCurator
from agents.core.skills.loader import SkillLoader
from agents.core.skills.proposals import SkillProposalStore
from agents.core.skills.tools import (
    MAX_FILE_BYTES,
    MAX_LISTED_BYTES,
    MAX_PROPOSALS_PER_DAY,
    TOOL_PROPOSE,
    TOOL_VIEW,
    register_skill_tools,
)
from agents.core.tool_rpc import ToolRPCServer

REPO_SKILLS = Path(loader_mod.SKILLS_DIR)
CODE = "def run(*args, **kwargs):\n    return 'ok'\n"


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    for name in ("JARVIS_SKILL_SIGNING_KEY", "JARVIS_REQUIRE_SIGNED_SKILLS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    """A skill tree, an approval registry, a proposal ledger, an approval queue and a
    curator: the whole path from skill_propose to an applied change."""
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    registry = SkillApprovalStore(tmp_path / "skill_approvals.json")
    ns = SimpleNamespace(root=root, registry=registry, archive=tmp_path / "archive")

    def write(name, body="Steps.\n", *, code=False, files=None, title=None):
        path = root / name
        path.mkdir(parents=True)
        # Bytes, never text mode: Windows would write "\r\n" (review-H318e m-2).
        (path / "SKILL.md").write_bytes(
            f"---\nname: {title or name}\ndescription: {name} helper\n---\n{body}".encode())
        if code:
            (path / "main.py").write_bytes(CODE.encode("utf-8"))
        for rel, data in (files or {}).items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def load():
        ns.loader = SkillLoader(approval_store=registry)
        ns.loader.discover()
        ns.proposals = SkillProposalStore(path=str(tmp_path / "proposals.json"))
        ns.queue = ActionApprovalQueue(path=str(tmp_path / "actions.json"))
        ns.curator = SkillCurator(ns.loader, None, proposals=ns.proposals, approvals=ns.queue,
                                  archive_dir=str(ns.archive))
        ns.server = _server(ns.loader, ns.proposals, ns.queue)
        return ns.loader

    ns.write, ns.load = write, load
    return ns


def _server(loader, proposals, queue, settings=None):
    server = ToolRPCServer()
    register_skill_tools(server, loader=lambda: loader, proposals=lambda: proposals, approvals=lambda: queue,
                         session_id=lambda: "web-1", posture=lambda: "operator/owner", origin=lambda: "hud",
                         settings=lambda key, default: (settings or {}).get(key, default))
    return server


def _call(server, tool, args, actor="friday"):
    reply = asyncio.run(server.handle({"tool": tool, "args": args}, actor=actor))
    assert reply["ok"] is True, reply
    return reply["result"]


def _new_text(name, body="Better steps.\n"):
    return f"---\nname: {name}\ndescription: {name} helper\n---\n{body}"


def _approve(ns, name, text):
    """skill_propose, then the owner approves the proposal's card: the real path."""
    got = _call(ns.server, TOOL_PROPOSE, {"name": name, "content": text})
    assert got["ok"] is True, got
    card = ns.proposals.get(got["proposal_id"])["card"]
    ns.queue.decide(card, True, by="owner")
    return got["proposal_id"], ns.curator.apply_decisions()


def _state(loader, name):
    skill = loader.skills.get(name)
    if skill is None:
        return "hidden"
    return loader.catalog_gate(skill) or "shown"


# ── M-1: an approved change keeps the skill's standing ───────────────────────────

def test_a_generated_skill_the_owner_approved_stays_approved_and_loaded(hub):
    path = hub.write("digest", code=True)
    signing.sign_skill(path)                      # what approve_generated_skill does
    hub.registry.approve(path)
    loader = hub.load()
    assert loader.skills["digest"].owner_vouched and not loader.skills["digest"].sandboxed
    pid, out = _approve(hub, "digest", _new_text("digest"))
    assert out["applied"] == ["digest"] and out["outcomes"][0]["state"] == "shown"
    skill = loader.skills["digest"]
    assert (path / "SKILL.md").read_text() == _new_text("digest").strip()
    assert skill.signature_reason == "integrity-only" and skill.owner_vouched and not skill.sandboxed
    assert hub.registry.is_approved(path)


def test_a_keyed_signature_is_renewed_for_the_approved_bytes(hub, monkeypatch):
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "k" * 40)
    path = hub.write("mailer", code=True)
    signing.sign_skill(path)
    loader = hub.load()
    assert loader.skills["mailer"].signature_reason == "signed" and not loader.skills["mailer"].sandboxed
    _, out = _approve(hub, "mailer", _new_text("mailer"))
    assert out["outcomes"][0] == {"skill": "mailer", "proposal_id": out["outcomes"][0]["proposal_id"],
                                  "ok": True, "state": "shown"}
    assert loader.skills["mailer"].signature_reason == "signed" and not loader.skills["mailer"].sandboxed
    assert not hub.registry.tracks_path(path)      # no approval minted beside the signature


def test_an_integrity_only_signature_still_verifies_and_the_skill_stays_visible(hub):
    path = hub.write("notes")
    signing.sign_skill(path)
    loader = hub.load()
    before = _state(loader, "notes")
    _approve(hub, "notes", _new_text("notes"))
    assert loader.skills["notes"].signature_reason == "integrity-only"
    assert _state(loader, "notes") == before


def test_a_skill_nothing_vouched_for_gains_no_vouch(hub):
    path = hub.write("outsider", code=True)
    loader = hub.load()
    assert loader.skills["outsider"].sandboxed and not loader.skills["outsider"].owner_vouched
    # skill_propose does not see a sandboxed skill; the background review's ledger does
    current = (path / "SKILL.md").read_text()
    rec = hub.proposals.propose("outsider", current, _new_text("outsider"), origin="background_review")
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
    out = hub.curator.apply_decisions()
    assert out["applied"] == ["outsider"]
    assert out["outcomes"][0]["state"] == "sandboxed"          # said, not hidden behind "applied"
    assert not (path / "SKILL.sig").exists() and not hub.registry.is_approved(path)
    assert loader.skills["outsider"].sandboxed and not loader.skills["outsider"].owner_vouched


def test_code_changed_on_disk_since_the_approval_does_not_ride_the_patch(hub):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    loader = hub.load()
    assert not loader.skills["tool"].sandboxed
    (path / "main.py").write_text(CODE + "import os\n", encoding="utf-8")   # after the owner looked
    _approve(hub, "tool", _new_text("tool"))
    assert not hub.registry.is_approved(path)
    assert loader.skills["tool"].sandboxed


def test_a_signature_that_no_longer_verifies_is_not_renewed(hub):
    """A tampered skill (its SKILL.sig mismatches) must not be laundered into a clean one."""
    path = hub.write("tampered")
    signing.sign_skill(path)
    (path / "SKILL.md").write_text((path / "SKILL.md").read_text() + "edited by someone\n", encoding="utf-8")
    loader = hub.load()
    assert loader.skills["tampered"].signature_reason == "signature-mismatch"
    current = (path / "SKILL.md").read_text()
    rec = hub.proposals.propose("tampered", current, _new_text("tampered"), origin="background_review")
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
    out = hub.curator.apply_decisions()
    assert out["applied"] == ["tampered"] and out["outcomes"][0]["state"] == "untrusted"
    assert signing.verify_skill(path)[1] == "signature-mismatch"


@pytest.fixture()
def bundled_brief(hub):
    shutil.copytree(REPO_SKILLS / "brief", hub.root / "brief", ignore=shutil.ignore_patterns("__pycache__"))
    loader = hub.load()
    assert loader.skills["Brief"].external is False
    return loader


def test_a_bundled_skill_cannot_be_proposed_to(hub, bundled_brief):
    live = (hub.root / "brief" / "SKILL.md").read_bytes()
    got = _call(hub.server, TOOL_PROPOSE, {"name": "Brief", "content": _new_text("Brief")})
    assert got["ok"] is False and got["reason"] == "skill_propose_bundled"
    assert hub.proposals.list() == [] and (hub.root / "brief" / "SKILL.md").read_bytes() == live


def test_a_ledger_proposal_to_a_bundled_skill_is_refused_at_apply(hub, bundled_brief):
    live = (hub.root / "brief" / "SKILL.md").read_text()
    rec = hub.proposals.propose("Brief", live, live + "\nMore.\n", origin="background_review")
    card = hub.proposals.queue_card(rec["id"], hub.queue, agent="background_review", summary="x")
    hub.queue.decide(card, True)
    out = hub.curator.apply_decisions()
    assert out["applied"] == [] and out["failed"] == ["Brief"]
    assert out["outcomes"][0]["reason"] == "bundled_skill"
    assert hub.proposals.get(rec["id"])["status"] == "rejected"
    assert hub.proposals.get(rec["id"])["reason"] == "bundled"
    assert (hub.root / "brief" / "SKILL.md").read_text() == live
    assert _state(bundled_brief, "Brief") == "shown" and not bundled_brief.skills["Brief"].sandboxed


# ── n-2: a rename is refused ─────────────────────────────────────────────────────

def test_a_rename_is_refused_when_proposed_and_when_applied(hub):
    hub.write("plan")
    hub.write("other")
    hub.load()
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("other")})
    assert got["ok"] is False and got["reason"] == "skill_propose_rename"
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("plan", current, _new_text("other"), origin="background_review")
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "renames_skill"
    assert (hub.root / "plan" / "SKILL.md").read_text() == current


# ── M-2 / m-6: the owner sees the ledger's change, decided by the proposal's card ──

@pytest.fixture()
def client(hub, monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web

    hub.write("plan", "Old steps.\n")
    hub.load()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h318c-admin")
    monkeypatch.setattr(web, "orch", SimpleNamespace(skill_proposals=hub.proposals, skills=hub.loader,
                                                     action_approvals=hub.queue, curator=hub.curator))
    return TestClient(web.app)


ADMIN = {"X-Admin-Token": "h318c-admin"}


def test_the_route_shows_the_whole_change_from_the_ledger(hub, client):
    long_body = "".join(f"step {i}: do the next thing carefully\n" for i in range(400))   # ~15 KB
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", long_body)})
    reply = client.get("/api/skills/proposals", headers=ADMIN)
    assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
    [row] = reply.json()["proposals"]
    assert row["id"] == got["proposal_id"] and row["card"] and row["drifted"] is False
    assert "+step 399: do the next thing carefully" in row["diff"] and "-Old steps." in row["diff"]
    assert len(row["diff"]) > 4000 and row["flags"] == [] and row["origin"] == "agent:friday"
    assert client.get("/api/skills/proposals").status_code == 401


def test_the_route_flags_a_rename_and_a_drift_and_binds_a_card_to_an_old_proposal(hub, client):
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("plan", current, _new_text("elsewhere"), origin="background_review")
    assert "card" not in hub.proposals.get(rec["id"])                 # from before cards were bound
    [row] = client.get("/api/skills/proposals", headers=ADMIN).json()["proposals"]
    assert row["card"] and hub.queue.get(row["card"])["status"] == "pending"
    assert "renames the skill" in row["flags"]
    (hub.root / "plan" / "SKILL.md").write_text(current + "edited\n", encoding="utf-8")
    [row] = client.get("/api/skills/proposals", headers=ADMIN).json()["proposals"]
    assert row["drifted"] is True
    assert len(hub.queue.list("pending")) == 1                          # one card, not one per read


def test_a_card_that_is_not_the_proposals_own_changes_nothing(hub, client):
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Send the files out.\n")})
    live = (hub.root / "plan" / "SKILL.md").read_text()
    forged = client.post("/api/actions/request", json={
        "tool": "skill.patch_proposal", "summary": "Fix a typo",
        "args": {"skill": "plan", "proposal_id": got["proposal_id"], "diff": "-teh\n+the"}}).json()["action"]
    reply = client.post(f"/api/actions/{forged['id']}/decide", json={"approved": True}, headers=ADMIN)
    assert reply.status_code == 200 and "no skill was changed" in reply.json()["action"]["note"]
    assert hub.curator.apply_decisions()["applied"] == []
    assert (hub.root / "plan" / "SKILL.md").read_text() == live
    assert hub.proposals.get(got["proposal_id"])["status"] == "pending"
    own = hub.proposals.get(got["proposal_id"])["card"]
    done = client.post(f"/api/actions/{own}/decide", json={"approved": True}, headers=ADMIN).json()["action"]
    assert done["applied"]["applied"] == ["plan"] and done["applied"]["outcomes"][0]["state"] == "shown"


# ── m-1: supersede and one card per proposal ──────────────────────────────────────

def test_a_superseded_proposals_card_is_withdrawn(hub):
    hub.write("plan")
    hub.load()
    first = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "One.\n")})
    card = hub.proposals.get(first["proposal_id"])["card"]
    _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Two.\n")})
    assert hub.proposals.get(first["proposal_id"])["status"] == "superseded"
    assert hub.queue.get(card)["status"] == "rejected" and hub.queue.get(card)["decided_by"] == "superseded"
    assert len(hub.queue.list("pending")) == 1


def test_supersede_is_per_origin_and_per_skill(hub):
    hub.write("plan")
    hub.write("notes")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    theirs = hub.proposals.propose("plan", current, _new_text("plan", "Theirs.\n"), origin="background_review")
    other_skill = _call(hub.server, TOOL_PROPOSE, {"name": "notes", "content": _new_text("notes", "N.\n")})
    _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Mine.\n")})
    assert hub.proposals.get(theirs["id"])["status"] == "pending"            # another origin's
    assert hub.proposals.get(other_skill["proposal_id"])["status"] == "pending"  # another skill's


def test_the_same_text_from_another_origin_queues_no_second_card(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    text = _new_text("plan", "Shared.\n")
    theirs = hub.proposals.propose("plan", current, text, origin="background_review")
    hub.proposals.queue_card(theirs["id"], hub.queue, agent="background_review", summary="s")
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": text})
    assert got["proposal_id"] == theirs["id"] and len(hub.queue.list("pending")) == 1


# ── m-2: the reviewer's unpinned mutants ──────────────────────────────────────────

def test_a_new_skill_counts_toward_the_daily_limit(hub, monkeypatch):
    hub.load()
    made = iter(range(100))
    monkeypatch.setattr(hub.loader, "generate_skill", lambda actor, description, steps: f"new_{next(made)}")
    for _ in range(MAX_PROPOSALS_PER_DAY):
        assert _call(hub.server, TOOL_PROPOSE, {"description": "a thing", "steps": ["do it"]})["ok"] is True
    got = _call(hub.server, TOOL_PROPOSE, {"description": "a thing", "steps": ["do it"]})
    assert got["reason"] == "skill_propose_limit"


def test_the_rendered_bound_counts_bytes_not_characters(hub):
    # 32,000 characters of body (64,000 bytes) and four variables of 250 two-byte
    # characters: 33,000 characters, 66,000 bytes once rendered.
    hub.write("wide", "é" * 32_000 + "${a}${b}${c}${d}\n")
    loader = hub.load()
    wide = dict.fromkeys("abcd", "é" * 250)
    server = _server(loader, hub.proposals, hub.queue, settings={"skills.template_vars": wide})
    got = _call(server, TOOL_VIEW, {"name": "wide"})
    assert got["ok"] is False and got["reason"] == "skill_file_too_large" and "rendered" in got["detail"]


def test_a_file_of_exactly_the_limit_is_readable(hub):
    hub.write("edge", files={"ref.md": "x" * loader_mod.VIEW_FILE_BYTES})
    loader = hub.load()
    got = _call(_server(loader, hub.proposals, hub.queue), TOOL_VIEW, {"name": "edge", "file": "ref.md"})
    assert got["ok"] is True and len(got["content"]) == loader_mod.VIEW_FILE_BYTES


# ── m-4: the file list is bounded ──────────────────────────────────────────────────

def test_a_skill_with_thousands_of_files_answers_within_its_budget(hub):
    hub.write("many", files={f"ref/file_{i:04d}.md": "x" for i in range(2_000)})
    loader = hub.load()
    server = _server(loader, hub.proposals, hub.queue)
    got = _call(server, TOOL_VIEW, {"name": "many"})
    assert got["ok"] is True and got["files_more"] == 2_000 - len(got["files"]) > 0
    assert sum(len(f.encode()) + 4 for f in got["files"]) <= MAX_LISTED_BYTES
    assert len(json.dumps(got).encode()) <= server.declared_result_bytes(TOOL_VIEW)
    from agents.core.skills.tools import MAX_DESCRIPTION_BYTES, MAX_ENCODED_BYTES

    assert server.declared_result_bytes(TOOL_VIEW) == (MAX_ENCODED_BYTES + MAX_LISTED_BYTES
                                                       + MAX_DESCRIPTION_BYTES + 4096)   # review-H318d m-3
    last = f"ref/file_{1_999:04d}.md"                   # a file not listed is still readable
    assert _call(server, TOOL_VIEW, {"name": "many", "file": last})["content"] == "x"


# ── m-5: the backup is named by the directory, uniquely ───────────────────────────

def test_the_backup_is_named_by_the_directory_and_never_overwritten(hub):
    hub.write("plan", title="Plan Helper")
    loader = hub.load()
    assert "Plan Helper" in loader.skills
    for body in ("One.\n", "Two.\n"):
        current = (hub.root / "plan" / "SKILL.md").read_text()
        rec = hub.proposals.propose("Plan Helper", current, _new_text("Plan Helper", body), origin="r")
        hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
        assert hub.curator.apply_decisions()["applied"] == ["Plan Helper"]
    backups = sorted(p.name for p in hub.archive.iterdir())
    assert len(backups) == 2 and all(name.startswith("plan-") for name in backups)


def test_a_name_that_is_a_path_is_never_applied_or_backed_up(hub):
    # A skill already on disk under a name like ../../escaped can no longer be changed:
    # the new text keeps its name, and a name that is a path fails the H350 check.
    hub.write("plan", title="../../escaped")
    loader = hub.load()
    assert "../../escaped" in loader.skills
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("../../escaped", current, _new_text("../../escaped", "One.\n"), origin="r")
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
    out = hub.curator.apply_decisions()
    assert out["applied"] == [] and out["outcomes"][0]["reason"] == "invalid_skill_md"
    assert (hub.root / "plan" / "SKILL.md").read_text() == current
    assert not hub.archive.exists() or not any(hub.archive.iterdir())
    assert not any(hub.archive.parent.parent.glob("escaped-*"))


# ── m-7: publishing signs a staged copy ───────────────────────────────────────────

def test_publishing_with_a_key_does_not_vouch_for_the_source(tmp_path, monkeypatch):
    from agents.core.skills.marketplace import SkillMarketplace

    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "k" * 40)
    mk = SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "mk.db"))
    source = mk.skills_dir / "imported"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Imported\n> An imported skill.\nversion: 1.0\n", encoding="utf-8")
    (source / "main.py").write_text(CODE, encoding="utf-8")
    mk.publish_skill("imported")
    assert not (source / "SKILL.sig").exists()
    assert signing.verify_skill(source) == (False, "unsigned")
    assert mk.list_skills()[0]["signed"] is True                     # the package is signed


# ── n-1: two decisions at once apply one after the other ──────────────────────────

def test_overlapping_decisions_report_one_apply_and_no_stale(hub, monkeypatch):
    hub.write("plan")
    hub.load()
    pid, _ = _approve(hub, "plan", _new_text("plan", "Next.\n"))     # applied once already
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Again.\n")})
    hub.queue.decide(hub.proposals.get(got["proposal_id"])["card"], True)
    real_apply = hub.proposals.apply
    inside = threading.Event()
    release = threading.Event()

    def slow_apply(*args, **kwargs):
        inside.set()
        release.wait(5)
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(hub.proposals, "apply", slow_apply)
    results = []
    first = threading.Thread(target=lambda: results.append(hub.curator.apply_decisions()))
    first.start()
    assert inside.wait(5)
    second = threading.Thread(target=lambda: results.append(hub.curator.apply_decisions()))
    second.start()
    second.join(0.3)
    assert second.is_alive()                                          # waits its turn
    release.set()
    first.join(5)
    second.join(5)
    assert [r["applied"] for r in results] == [["plan"], []]
    assert all(r["stale"] == [] for r in results)
