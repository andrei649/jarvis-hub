"""H318, the third review (review-H318c) — its findings, pinned.

- m-1: the standing was read, then the tree was written, then the renewal read the tree
  again: a write in between rode into the vouch. The renewal now covers the snapshot the
  standing was judged on, with only SKILL.md replaced by the approved text, or nothing.
- m-2 / n-7: the HUD sides (tests in frontend/src/test/skill-changes.test.tsx).
- m-3: a failed renewal left the new text unvouched and was reported as applied; the old
  text is put back and the reason named.
- m-4: a keyed signature whose key is missing is not overwritten; the change waits.
- m-5: skill_view's bounds count the bytes the answer carries.
- m-6: a proposal whose card is gone gets a new one.
- m-7: publishing a skill that holds a link is refused again.
- m-8: the reviewer's four real survivors (P15, P16, R4, B1).
- n-1..n-6: the nightly pass takes the apply lock; every origin supersedes; legacy and
  late cards are withdrawn; the rename check parses the stored text; a shipped skill is
  known by where it lives.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.skills import signing
from agents.core.skills.proposals import CARD_TOOL
from agents.core.skills.tools import MAX_FILE_BYTES, MAX_LISTED_BYTES, TOOL_PROPOSE, TOOL_VIEW
from tests.test_h318c_skill_review import (  # noqa: F401  (hub, client, _no_key are fixtures)
    ADMIN,
    REPO_SKILLS,
    _call,
    _new_text,
    _no_key,
    client,
    hub,
)


def _ledger(hub, name, text=None, origin="background_review"):
    """A ledger proposal whose own card the owner approved."""
    current = (hub.root / name / "SKILL.md").read_text()
    rec = hub.proposals.propose(name, current, text or _new_text(name, "Better steps.\n"), origin=origin)
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent=origin, summary="s"), True)
    return rec, current


# ── m-1: a write between the standing and the renewal rides into nothing ──────────

def test_code_changed_during_the_apply_is_not_approved_and_the_old_text_comes_back(hub):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    loader = hub.load()
    rec, current = _ledger(hub, "tool")
    judged = loader.owner_standing

    def standing_then_a_write(skill):
        standing = judged(skill)
        (path / "main.py").write_text("import os\nos.system('evil')\n", encoding="utf-8")
        return standing

    loader.owner_standing = standing_then_a_write
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "changed_during_apply" and out["applied"] == []
    assert (path / "SKILL.md").read_text() == current
    assert hub.registry.is_approved(path) is False                      # the new code got no vouch


def test_a_signed_skill_is_renewed_over_the_bytes_that_were_checked(hub):
    path = hub.write("tool", code=True)
    signing.sign_skill(path)
    hub.load()
    rec, _ = _ledger(hub, "tool")
    out = hub.curator.apply_decisions()
    assert out["applied"] == ["tool"]
    assert signing.verify_skill(path) == (True, "integrity-only")


# ── m-3: a renewal that fails puts the old text back and says so ─────────────────

def test_a_failed_renewal_keeps_the_old_text_and_its_standing(hub):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    loader = hub.load()
    rec, current = _ledger(hub, "tool")

    def broken(path, standing, snapshot=None):
        raise OSError("disk full")

    loader.restore_standing = broken
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "standing_not_renewed"
    assert (path / "SKILL.md").read_text() == current and hub.registry.is_approved(path) is True
    assert (hub.proposals.get(rec["id"])["status"], hub.proposals.get(rec["id"])["reason"]) == \
        ("stale", "standing_not_renewed")                        # not retried every pass (review-H318d n-1)


# ── m-4: a keyed signature whose key is missing waits for the key ─────────────────

def test_a_keyed_signature_with_its_key_missing_waits(hub, monkeypatch):
    path = hub.write("tool", code=True)
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "k" * 40)
    signing.sign_skill(path)
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY")
    hub.load()
    rec, current = _ledger(hub, "tool")
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "signing_key_missing"
    assert (path / "SKILL.md").read_text() == current and hub.proposals.get(rec["id"])["status"] == "approved"
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "k" * 40)
    hub.loader.skills["tool"].path = path
    out = hub.curator.apply_decisions()
    assert out["applied"] == ["tool"] and signing.verify_skill(path) == (True, "signed")


# ── m-5: the bounds count what the answer carries ────────────────────────────────

def test_the_file_list_is_bounded_in_the_bytes_the_answer_carries(hub):
    import json

    hub.write("odd", files={("\x01" * 40 + f"-{i:04d}.md"): "x" for i in range(400)})
    hub.load()
    got = _call(hub.server, TOOL_VIEW, {"name": "odd"})
    assert got["files_more"] > 0
    assert len(json.dumps(got["files"], ensure_ascii=False).encode()) <= MAX_LISTED_BYTES + 4 * len(got["files"])


def test_a_file_whose_escapes_pass_the_limit_is_refused(hub):
    hub.write("quotes", files={"ref.md": "\x01" * (MAX_FILE_BYTES // 2)})    # 6 bytes each once escaped
    hub.load()
    got = _call(hub.server, TOOL_VIEW, {"name": "quotes", "file": "ref.md"})
    assert got["ok"] is False and got["reason"] == "skill_file_too_large"


# ── m-6 / n-3 / n-4: cards ───────────────────────────────────────────────────────

def test_a_proposal_whose_card_is_gone_gets_a_new_one(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("plan", current, _new_text("plan"), origin="background_review")
    first = hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s")
    hub.queue.clear()
    second = hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s")
    assert second and second != first and hub.proposals.get(rec["id"])["card"] == second
    assert hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s") == second


def test_binding_a_card_withdraws_the_unbound_ones(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("plan", current, _new_text("plan"), origin="background_review")
    legacy = hub.queue.request({"tool": CARD_TOOL, "agent": "r", "summary": "old",
                                "args": {"skill": "plan", "proposal_id": rec["id"]}})["id"]
    card = hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s")
    assert hub.queue.get(legacy)["status"] == "rejected" and hub.queue.get(card)["status"] == "pending"


def test_a_proposal_superseded_while_its_card_was_queued_gets_no_card(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    rec = hub.proposals.propose("plan", current, _new_text("plan"), origin="background_review")
    real = hub.queue.request

    def request_then_supersede(action):
        item = real(action)
        hub.proposals.mark(rec["id"], "superseded")
        return item

    hub.queue.request = request_then_supersede
    assert hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s") is None
    [item] = hub.queue.list()
    assert item["status"] == "rejected" and "card" not in hub.proposals.get(rec["id"])


def test_the_route_rebinds_a_lost_card(hub, client):
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "New.\n")})
    first = hub.proposals.get(got["proposal_id"])["card"]
    hub.queue.clear()
    [row] = client.get("/api/skills/proposals", headers=ADMIN).json()["proposals"]
    assert row["card"] != first and hub.queue.get(row["card"])["status"] == "pending"


# ── m-7: a skill that holds a link is not published ──────────────────────────────

def test_publishing_a_skill_that_holds_a_link_is_refused(tmp_path):
    from agents.core.skills.marketplace import SkillMarketplace

    mk = SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "mk.db"))
    source = mk.skills_dir / "linked"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Linked\nversion: 1.0\n", encoding="utf-8")
    (source / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("x = 1\n", encoding="utf-8")
    (source / "helper.py").symlink_to(tmp_path / "helper.py")
    with pytest.raises(signing.SkillSourceSnapshotError):
        mk.publish_skill("linked")
    assert mk.list_skills() == []


# ── m-8: the survivors ───────────────────────────────────────────────────────────

@pytest.fixture()
def bundled(hub):
    import shutil

    shutil.copytree(REPO_SKILLS / "brief", hub.root / "brief", ignore=shutil.ignore_patterns("__pycache__"))
    return hub.load()


def test_describe_flags_a_bundled_skill_and_a_skill_that_is_gone(hub, bundled):
    live = (hub.root / "brief" / "SKILL.md").read_text()
    rec = hub.proposals.propose("Brief", live, live + "\nMore.\n", origin="background_review")
    assert "a bundled skill: it cannot be changed here" in hub.proposals.describe(rec, bundled)["flags"]
    hub.write("plan")
    loader = hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    gone = hub.proposals.propose("plan", current, _new_text("plan"), origin="background_review")
    del loader.skills["plan"]
    row = hub.proposals.describe(gone, loader)
    assert row["drifted"] is True and row["flags"] == ["the skill is gone"] and row["diff"] == ""


def test_the_route_lists_pending_proposals_only(hub, client):
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "One.\n")})
    hub.proposals.mark(got["proposal_id"], "rejected")
    assert client.get("/api/skills/proposals", headers=ADMIN).json()["proposals"] == []


def test_the_background_review_proposes_nothing_to_a_bundled_skill(hub, bundled):
    from agents.core.learning.background_review import BackgroundReviewer

    reviewer = BackgroundReviewer(lambda prompt: None, skills=bundled, proposals=hub.proposals,
                                  approvals=hub.queue, get_setting=lambda k, d=None: d)
    live = (hub.root / "brief" / "SKILL.md").read_text()
    assert reviewer._dispatch_patch({"name": "Brief", "content": live + "\nMore.\n"}, []) is False
    assert hub.proposals.list() == []


# ── n-1: the nightly pass waits for a decision's apply ───────────────────────────

def test_the_nightly_pass_takes_the_apply_lock(hub):
    hub.write("plan")
    hub.load()
    done = threading.Event()
    with hub.curator._apply_lock:
        runner = threading.Thread(target=lambda: (hub.curator._proposals_pass(), done.set()))
        runner.start()
        assert not done.wait(0.3)                            # it waits for the held lock
    runner.join(5)
    assert done.is_set()


# ── n-2: every origin supersedes, and the route sends a page ─────────────────────

def test_a_new_review_proposal_supersedes_the_last_one_for_that_skill(hub):
    from agents.core.learning.background_review import BackgroundReviewer

    hub.write("plan")
    loader = hub.load()
    reviewer = BackgroundReviewer(lambda prompt: None, skills=loader, proposals=hub.proposals,
                                  approvals=hub.queue, get_setting=lambda k, d=None: d)
    for body in ("First.\n", "Second.\n", "Third.\n"):
        assert reviewer._dispatch_patch({"name": "plan", "content": _new_text("plan", body)}, []) is True
    assert len(hub.proposals.list("pending")) == 1 and len(hub.queue.list("pending")) == 1


def test_the_route_sends_a_page_and_counts_the_rest(hub, client, monkeypatch):
    from agents.core.routers import skills as route

    monkeypatch.setattr(route, "PROPOSALS_SHOWN", 2)
    current = (hub.root / "plan" / "SKILL.md").read_text()
    for i in range(5):
        hub.proposals.propose("plan", current, _new_text("plan", f"Take {i}.\n"), origin=f"agent:a{i}")
    reply = client.get("/api/skills/proposals", headers=ADMIN).json()
    assert (reply["count"], reply["more"]) == (2, 3)


# ── n-5 / n-6: the rename check and a shipped skill's location ───────────────────

def test_a_rename_behind_a_blank_line_is_refused_when_proposed(hub):
    hub.write("plan")
    hub.write("other")
    hub.load()
    got = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": "\n\n" + _new_text("other")})
    assert got["ok"] is False and got["reason"] == "skill_propose_rename"


def test_a_drifted_shipped_skill_is_still_refused_by_where_it_lives(hub, bundled):
    path = hub.root / "brief"
    (path / "SKILL.md").write_text((path / "SKILL.md").read_text() + "drifted\n", encoding="utf-8")
    loader = hub.load()
    skill = loader.skills["Brief"]
    assert skill.external is True                             # its bytes drifted: loaded as external
    assert loader.owner_standing(skill)["bundled"] is True
    current = (path / "SKILL.md").read_text()
    rec = hub.proposals.propose("Brief", current, current + "More.\n", origin="background_review")
    hub.queue.decide(hub.proposals.queue_card(rec["id"], hub.queue, agent="r", summary="s"), True)
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "bundled_skill" and (path / "SKILL.md").read_text() == current
    assert Path(skill.path) == path


@pytest.mark.parametrize("vouch", ["approved", "signed"])
def test_the_renewal_covers_the_checked_bytes_not_a_later_read(hub, vouch):
    """A write that lands after the check but before the renewal is not vouched for."""
    path = hub.write("tool", code=True)
    if vouch == "approved":
        hub.registry.approve(path)
    else:
        signing.sign_skill(path)
    loader = hub.load()
    _ledger(hub, "tool")
    renew = loader.restore_standing

    def write_then_renew(path, standing, snapshot=None):
        (Path(path) / "main.py").write_text("import os\nos.system('evil')\n", encoding="utf-8")
        return renew(path, standing, snapshot=snapshot)

    loader.restore_standing = write_then_renew
    hub.curator.apply_decisions()
    if vouch == "approved":
        assert hub.registry.is_approved(path) is False
    else:
        assert signing.verify_skill(path)[1] == "signature-mismatch"


def test_a_drifted_shipped_skill_is_flagged_and_gets_no_review_proposal(hub, bundled):
    from agents.core.learning.background_review import BackgroundReviewer

    path = hub.root / "brief"
    (path / "SKILL.md").write_text((path / "SKILL.md").read_text() + "drifted\n", encoding="utf-8")
    loader = hub.load()
    assert loader.skills["Brief"].external is True
    current = (path / "SKILL.md").read_text()
    rec = hub.proposals.propose("Brief", current, current + "More.\n", origin="agent:friday")
    assert "a bundled skill: it cannot be changed here" in hub.proposals.describe(rec, loader)["flags"]
    reviewer = BackgroundReviewer(lambda prompt: None, skills=loader, proposals=hub.proposals,
                                  approvals=hub.queue, get_setting=lambda k, d=None: d)
    assert reviewer._dispatch_patch({"name": "Brief", "content": current + "Other.\n"}, []) is False
