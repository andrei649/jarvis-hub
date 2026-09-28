"""H318, the fourth review (review-H318d) — its findings, pinned.

- MAJOR-1: SKILL.md was written and read in text mode against a byte-exact check, so on
  Windows every approved change to a signed or approved skill was refused, and a
  rollback rewrote a CRLF file's line ends and broke the standing it restored. The apply
  reads and writes bytes.
- m-1: a signature renewed before the approval failed was left over the old text; the
  old SKILL.sig is put back too.
- m-2: publish packs the bytes of one snapshot: a linked skill folder, a link or FIFO
  member, and a file swapped for a link after the check are refused.
- m-3: skill_view serves every file it served before and its declared budget counts the
  description and the escapes.
- m-4: the proposals route re-binds and names every pending card, not only its page's.
- m-5: the survivors: a SKILL.md swapped after the write, an integrity-only signature
  with a key configured, a re-bind that must not touch other proposals' cards, the
  publish route's 422, a body whose escapes pass the ceiling.
- nits: a refused apply goes stale with its reason; a failed rollback says the new text
  stays; the tool supersedes by its own origin; an unreadable SKILL.sig stops only its
  own proposal.
"""

from __future__ import annotations

import json
import os
import pathlib
from pathlib import Path

import pytest

from agents.core.skills import proposals as proposals_mod
from agents.core.skills import signing
from agents.core.skills.tools import (
    MAX_DESCRIPTION_BYTES,
    MAX_ENCODED_BYTES,
    MAX_FILE_BYTES,
    TOOL_PROPOSE,
    TOOL_VIEW,
)
from tests.test_h318c_skill_review import (  # noqa: F401  (hub, client, _no_key are fixtures)
    ADMIN,
    _call,
    _new_text,
    _no_key,
    client,
    hub,
)
from tests.test_h318d_skill_review import _ledger


def _crlf_skill(hub, name):
    path = hub.write(name, code=True)
    text = (path / "SKILL.md").read_text()
    (path / "SKILL.md").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    return path


# ── MAJOR-1: bytes, whatever the line ends and the platform ──────────────────────

@pytest.fixture()
def windows_text(monkeypatch):
    """Text-mode writes as Windows makes them: "\\n" becomes "\\r\\n"."""
    real = pathlib.Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):
        return real(self, data.replace("\n", "\r\n"), encoding=encoding, errors=errors, newline="")

    monkeypatch.setattr(pathlib.Path, "write_text", write_text)


@pytest.mark.parametrize("line_ends", ["lf", "crlf"])
def test_an_approved_change_to_a_vouched_skill_applies_under_windows_writes(hub, windows_text, line_ends):
    path = hub.write("tool", code=True) if line_ends == "lf" else _crlf_skill(hub, "tool")
    hub.registry.approve(path)
    signing.sign_skill(path)
    hub.load()
    _ledger(hub, "tool")
    out = hub.curator.apply_decisions()
    assert out["applied"] == ["tool"] and out["outcomes"][0]["state"] == "shown"
    assert hub.registry.is_approved(path) and signing.verify_skill(path) == (True, "integrity-only")


def test_a_rollback_restores_a_crlf_skill_byte_for_byte(hub):
    path = _crlf_skill(hub, "tool")
    hub.registry.approve(path)
    before = (path / "SKILL.md").read_bytes()
    loader = hub.load()
    _ledger(hub, "tool")

    def broken(path, standing, snapshot=None):
        raise OSError("disk full")

    loader.restore_standing = broken
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "standing_not_renewed"
    assert (path / "SKILL.md").read_bytes() == before and hub.registry.is_approved(path)


# ── m-1: a partial renewal puts the old signature back ───────────────────────────

@pytest.mark.parametrize("had_sig", [True, False])
def test_a_failed_approval_after_a_new_signature_restores_the_old_signature(hub, monkeypatch, had_sig):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    if had_sig:
        signing.sign_skill(path)
    old_sig = (path / "SKILL.sig").read_bytes() if had_sig else None
    loader = hub.load()
    _ledger(hub, "tool")

    def renew_then_fail(path, standing, snapshot=None):
        signing.sign_skill(path, snapshot=snapshot)             # the signature step succeeds
        raise OSError(28, "No space left on device")             # the approval step does not

    loader.restore_standing = renew_then_fail
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "standing_not_renewed"
    if had_sig:
        assert (path / "SKILL.sig").read_bytes() == old_sig and signing.verify_skill(path)[0] is True
    else:
        assert not (path / "SKILL.sig").exists()
    assert hub.registry.is_approved(path)


# ── m-2 / M29: publish packs one snapshot's bytes ────────────────────────────────

def _market(tmp_path):
    from agents.core.skills.marketplace import SkillMarketplace

    return SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "mk.db"))


def test_a_skill_whose_folder_is_a_link_is_not_published(tmp_path):
    mk = _market(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "SKILL.md").write_text("# Proj\nversion: 1.0\n", encoding="utf-8")
    (project / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    mk.skills_dir.mkdir(parents=True, exist_ok=True)
    (mk.skills_dir / "proj").symlink_to(project)
    with pytest.raises(signing.SkillSourceSnapshotError):
        mk.publish_skill("proj")
    assert mk.list_skills() == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_a_skill_holding_a_fifo_is_not_published(tmp_path):
    mk = _market(tmp_path)
    source = mk.skills_dir / "piped"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Piped\nversion: 1.0\n", encoding="utf-8")
    os.mkfifo(source / "pipe")
    with pytest.raises(signing.SkillSourceSnapshotError):
        mk.publish_skill("piped")


def test_the_package_holds_the_bytes_the_snapshot_read(tmp_path, monkeypatch):
    """A member swapped for a link after the snapshot is not what ships."""
    mk = _market(tmp_path)
    source = mk.skills_dir / "notes"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"# Notes\n> Plain notes.\nversion: 1.0\n")
    (source / "notes.md").write_bytes(b"plain notes\n")                  # bytes: the Windows lane too
    (tmp_path / "id_rsa").write_text("-----BEGIN PRIVATE KEY----- SECRET\n", encoding="utf-8")
    real = signing.source_snapshot

    def snapshot_then_swap(path):
        snap = real(path)
        if Path(path) == source:
            (source / "notes.md").unlink()
            (source / "notes.md").symlink_to(tmp_path / "id_rsa")
        return snap

    monkeypatch.setattr(signing, "source_snapshot", snapshot_then_swap)
    mk.publish_skill("notes")
    import io
    import sqlite3
    import zipfile

    blob = sqlite3.connect(str(tmp_path / "mk.db")).execute("SELECT package_zip FROM marketplace_skills").fetchone()[0]
    with zipfile.ZipFile(io.BytesIO(blob)) as package:
        assert package.read("notes.md") == b"plain notes\n"


def test_a_refused_publish_answers_422(hub, client, tmp_path, monkeypatch):
    import agents.web as web

    mk = _market(tmp_path)
    source = mk.skills_dir / "linked"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Linked\nversion: 1.0\n", encoding="utf-8")
    (source / "helper.py").symlink_to(tmp_path / "mk.db")
    monkeypatch.setattr(web.orch, "marketplace", mk, raising=False)
    reply = client.post("/api/skills/marketplace/publish", json={"name": "linked"}, headers=ADMIN)
    assert reply.status_code == 422 and reply.json()["reason"] == "skill_source_refused"


# ── m-3 / M33: skill_view's bounds ───────────────────────────────────────────────

def test_a_file_that_was_readable_still_is(hub):
    text = "".join(f"line {i:05d} of the r\n" for i in range(3226))         # 20 bytes a line
    assert len(text.encode()) < MAX_FILE_BYTES < len(json.dumps(text).encode())
    hub.write("ref", files={"big.md": text})
    hub.load()
    got = _call(hub.server, TOOL_VIEW, {"name": "ref", "file": "big.md"})
    assert got["ok"] is True and got["content"] == text


def test_a_body_whose_escapes_pass_the_ceiling_is_refused(hub):
    hub.write("ctrl", body="\x01" * (MAX_ENCODED_BYTES // 6 + 10))
    hub.load()
    got = _call(hub.server, TOOL_VIEW, {"name": "ctrl"})
    assert got["ok"] is False and got["reason"] == "skill_file_too_large"


def test_the_answer_with_a_long_description_stays_within_the_declared_budget(hub):
    from tests.test_h318c_skill_review import _server

    path = hub.write("wide", body='"' * (MAX_FILE_BYTES - 4096),
                     files={f"ref/f{i:04d}.md": "x" for i in range(600)})
    text = (path / "SKILL.md").read_text()
    (path / "SKILL.md").write_text(text.replace("description: wide helper", "description: " + "\x01" * 1100))
    loader = hub.load()
    server = _server(loader, hub.proposals, hub.queue)
    got = _call(server, TOOL_VIEW, {"name": "wide"})
    assert got["ok"] is True
    assert len(json.dumps(got["description"], ensure_ascii=False).encode()) - 2 <= MAX_DESCRIPTION_BYTES
    assert len(json.dumps(got, ensure_ascii=False).encode()) <= server.declared_result_bytes(TOOL_VIEW)


# ── m-4 / M23: every pending card is re-bound and named ──────────────────────────

def test_the_route_rebinds_and_names_every_pending_card(hub, client, monkeypatch):
    from agents.core.routers import skills as route

    monkeypatch.setattr(route, "PROPOSALS_SHOWN", 2)
    current = (hub.root / "plan" / "SKILL.md").read_text()
    for i in range(4):
        rec = hub.proposals.propose("plan", current, _new_text("plan", f"Take {i}.\n"), origin=f"agent:a{i}")
        hub.proposals.queue_card(rec["id"], hub.queue, agent="a", summary="s")
    hub.queue.clear()
    reply = client.get("/api/skills/proposals", headers=ADMIN).json()
    cards = [p["card"] for p in hub.proposals.list("pending")]
    assert sorted(reply["cards"]) == sorted(cards) and len(set(cards)) == 4
    assert all(hub.queue.get(c)["status"] == "pending" for c in cards)


def test_rebinding_one_card_leaves_the_other_proposals_cards_alone(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    one = hub.proposals.propose("plan", current, _new_text("plan", "One.\n"), origin="agent:a")
    two = hub.proposals.propose("plan", current, _new_text("plan", "Two.\n"), origin="agent:b")
    first = hub.proposals.queue_card(one["id"], hub.queue, agent="a", summary="s")
    second = hub.proposals.queue_card(two["id"], hub.queue, agent="b", summary="s")
    hub.queue._items.pop(first)                                # only the first card is lost
    hub.proposals.queue_card(one["id"], hub.queue, agent="a", summary="s")
    assert hub.queue.get(second)["status"] == "pending"


# ── M2 / M10: the post-write check and the missing key ───────────────────────────

def test_a_skill_md_swapped_after_the_write_is_not_vouched(hub, monkeypatch):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    hub.load()
    _ledger(hub, "tool")
    real = proposals_mod._snapshot

    def swap_then_snapshot(p):
        (Path(p) / "SKILL.md").write_text(_new_text("tool", "Something else.\n"), encoding="utf-8")
        return real(p)

    monkeypatch.setattr(proposals_mod, "_snapshot", swap_then_snapshot)
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "changed_during_apply"


def test_an_integrity_only_signature_with_a_key_configured_does_not_wait_for_a_key(hub, monkeypatch):
    path = hub.write("tool", code=True)
    signing.sign_skill(path)                                      # sha256: no key then
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "k" * 40)
    loader = hub.load()
    assert loader.owner_standing(loader.skills["tool"])["key_missing"] is False
    _ledger(hub, "tool")
    assert hub.curator.apply_decisions()["outcomes"][0].get("reason") != "signing_key_missing"


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_a_rollback_that_fails_says_the_new_text_stays(hub, monkeypatch):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    loader = hub.load()
    rec, current = _ledger(hub, "tool")

    def broken(path, standing, snapshot=None):
        raise OSError("disk full")

    loader.restore_standing = broken
    real = os.replace
    writes = []

    def replace(src, dst):
        # SKILL.md is replaced whole from a temporary file (review-H318e n-3): the second
        # replacement of it is the rollback, which fails.
        writes.append(Path(dst).name)
        if Path(dst).name == "SKILL.md" and writes.count("SKILL.md") > 1:
            raise OSError("read-only now")
        return real(src, dst)

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "rollback_failed"
    assert hub.proposals.get(rec["id"])["status"] == "stale"


def test_the_tool_supersedes_by_its_own_origin(hub):
    hub.write("plan")
    hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    older = _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Mine.\n")})
    hub.proposals.propose("plan", current, _new_text("plan", "Shared.\n"), origin="background_review")
    _call(hub.server, TOOL_PROPOSE, {"name": "plan", "content": _new_text("plan", "Shared.\n")})
    assert hub.proposals.get(older["proposal_id"])["status"] == "superseded"


def test_an_unreadable_signature_reads_as_unsigned_and_breaks_no_pass(hub):
    bad = hub.write("bad", code=True)
    hub.write("good")
    loader = hub.load()
    (bad / "SKILL.sig").write_bytes(b"\xff\xfe not utf-8")
    standing = loader.owner_standing(loader.skills["bad"])
    assert (standing["signed"], standing["approved"]) == (False, False)
    _ledger(hub, "bad")
    _ledger(hub, "good")
    out = hub.curator.apply_decisions()
    assert sorted(out["applied"]) == ["bad", "good"]            # nothing vouched, nothing renewed


def test_one_proposal_that_raises_stops_only_itself(hub, monkeypatch):
    hub.write("bad")
    hub.write("good")
    hub.load()
    rec_bad, _ = _ledger(hub, "bad")
    _ledger(hub, "good")
    real = hub.proposals.apply

    def apply(pid, *args, **kwargs):
        if pid == rec_bad["id"]:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return real(pid, *args, **kwargs)

    monkeypatch.setattr(hub.proposals, "apply", apply)
    out = hub.curator.apply_decisions()
    reasons = {o["skill"]: o.get("reason") for o in out["outcomes"]}
    assert reasons["bad"] == "apply_error" and out["applied"] == ["good"]


def test_a_standing_that_cannot_be_read_refuses_only_that_proposal(hub):
    hub.write("tool")
    loader = hub.load()
    _ledger(hub, "tool")

    def unreadable(skill):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    loader.owner_standing = unreadable
    assert hub.curator.apply_decisions()["outcomes"][0]["reason"] == "unreadable_skill"
