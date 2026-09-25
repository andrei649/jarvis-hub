"""H318, the fifth review (review-H318e) — its findings, pinned.

- m-1: the old SKILL.sig was read after SKILL.md was written, outside the guarded
  block: a failed read left the new text with no renewal and no rollback. It is read
  with SKILL.md, before anything is written.
- m-2: the round's own fixtures were written in text mode (the Windows lane); the H318
  helpers write bytes now.
- nits: a SKILL.sig that could not be put back is named for what it is; the background
  review supersedes by its own origin; SKILL.md is written whole or not at all, and a
  failed write leaves no backup behind; /v1 approves only beside a diff (tools.test.js);
  publish describes the SKILL.md it ships; the 422 names what it refuses; the escaped
  ceiling and the description cut are pinned.
"""

from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sqlite3
import zipfile
from pathlib import Path

from agents.core.skills import proposals as proposals_mod
from agents.core.skills import signing
from agents.core.skills.tools import (
    MAX_DESCRIPTION_BYTES,
    MAX_ENCODED_BYTES,
    TOOL_VIEW,
    _cut_encoded,
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
from tests.test_h318e_skill_review import _market


def _vouched(hub, name="tool"):
    path = hub.write(name, code=True)
    hub.registry.approve(path)
    signing.sign_skill(path)
    return path


# ── m-1: the old signature is read before anything is written ────────────────────

def test_a_signature_that_cannot_be_read_changes_nothing(hub, monkeypatch):
    path = _vouched(hub)
    before = (path / "SKILL.md").read_bytes()
    hub.load()
    rec, _current = _ledger(hub, "tool")
    real = pathlib.Path.read_bytes

    def read_bytes(self):
        if self.name == "SKILL.sig":
            raise PermissionError(13, "sharing violation")
        return real(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    out = hub.curator.apply_decisions()
    monkeypatch.setattr(pathlib.Path, "read_bytes", real)
    assert out["outcomes"][0]["reason"] == "unreadable_signature"
    assert (path / "SKILL.md").read_bytes() == before
    assert hub.registry.is_approved(path) and signing.verify_skill(path)[0] is True
    # Retried at the next pass, as a failed write is (review-H318f n-1).
    assert hub.proposals.get(rec["id"])["status"] == "approved"


# ── n-1: the old text is back, its signature is not ──────────────────────────────

def test_a_signature_that_cannot_be_put_back_is_named_for_what_it_is(hub, monkeypatch):
    path = _vouched(hub)
    before = (path / "SKILL.md").read_bytes()
    loader = hub.load()
    rec, _current = _ledger(hub, "tool")

    def renew_then_fail(path, standing, snapshot=None):
        signing.sign_skill(path, snapshot=snapshot)
        raise OSError(28, "No space left on device")

    loader.restore_standing = renew_then_fail
    real = os.replace

    def replace(src, dst):
        if Path(dst).name == "SKILL.sig":
            raise OSError(30, "read-only file system")
        return real(src, dst)

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    out = hub.curator.apply_decisions()
    monkeypatch.setattr(proposals_mod.os, "replace", real)
    assert out["outcomes"][0]["reason"] == "signature_not_restored"
    assert (path / "SKILL.md").read_bytes() == before
    assert hub.proposals.get(rec["id"])["status"] == "stale"


# ── n-3: SKILL.md is written whole or not at all ─────────────────────────────────

def test_a_write_cut_short_leaves_the_old_text_and_no_backup(hub, monkeypatch):
    path = hub.write("tool", code=True)
    hub.registry.approve(path)
    before = (path / "SKILL.md").read_bytes()
    hub.load()
    rec, _current = _ledger(hub, "tool")
    real = os.fsync

    def fsync(fd):
        raise OSError(28, "No space left on device")            # written, then the disk fills

    monkeypatch.setattr(proposals_mod.os, "fsync", fsync)
    out = hub.curator.apply_decisions()
    monkeypatch.setattr(proposals_mod.os, "fsync", real)
    assert out["outcomes"][0]["reason"] == "write_failed"
    assert (path / "SKILL.md").read_bytes() == before and hub.registry.is_approved(path)
    assert sorted(p.name for p in path.iterdir()) == ["SKILL.md", "main.py"]
    assert list(hub.archive.glob("**/*.SKILL.md")) == []
    assert hub.proposals.get(rec["id"])["status"] == "approved"          # retried at the next pass


def test_the_atomic_write_replaces_whole_and_leaves_nothing(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_bytes(b"old")
    proposals_mod._write_atomic(target, b"new text")
    assert target.read_bytes() == b"new text" and [p.name for p in tmp_path.iterdir()] == ["SKILL.md"]
    assert list(tmp_path.parent.glob(f".{tmp_path.name}.SKILL.md.*.tmp")) == []


# ── n-2: the background review supersedes by its own origin ──────────────────────

def test_the_review_supersedes_its_own_older_proposal_when_it_re_sends_anothers(hub):
    from agents.core.learning.background_review import BackgroundReviewer

    hub.write("plan")
    loader = hub.load()
    current = (hub.root / "plan" / "SKILL.md").read_text()
    replies = []

    async def llm(prompt):
        return replies.pop(0)

    reviewer = BackgroundReviewer(llm, living=None, skills=loader, proposals=hub.proposals,
                                  approvals=hub.queue, get_setting=lambda k, d=None: d)

    def patch(text):
        import json

        return json.dumps({"skill_updates": [{"kind": "patch", "name": "plan", "content": text}]})

    replies.append(patch(_new_text("plan", "Mine.\n")))
    asyncio.run(reviewer.run_on_demand("user: x"))
    [mine] = [p for p in hub.proposals.list("pending") if p["origin"] == "refine"]
    hub.proposals.propose("plan", current, _new_text("plan", "Shared.\n"), origin="agent:friday")
    replies.append(patch(_new_text("plan", "Shared.\n")))
    asyncio.run(reviewer.run_on_demand("user: y"))
    assert hub.proposals.get(mine["id"])["status"] == "superseded"


# ── n-5, n-6: publish describes what it ships, and says what it refused ──────────

def test_publish_describes_the_skill_md_it_packs(tmp_path, monkeypatch):
    mk = _market(tmp_path)
    source = mk.skills_dir / "two"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"---\nname: two\ndescription: honest\nversion: 1.0.0\n---\nSteps.\n")
    real = signing.source_snapshot

    def snapshot_then_edited(path):
        snap = real(path)
        (source / "SKILL.md").write_bytes(b"---\nname: two\ndescription: different\nversion: 9.9.9\n---\nOther.\n")
        return snap

    monkeypatch.setattr(signing, "source_snapshot", snapshot_then_edited)
    mk.publish_skill("two")
    row = sqlite3.connect(str(tmp_path / "mk.db")).execute(
        "SELECT version, description, package_zip FROM marketplace_skills").fetchone()
    with zipfile.ZipFile(io.BytesIO(row[2])) as package:
        packed = package.read("SKILL.md")
    assert b"version: 1.0.0" in packed and (row[0], row[1]) == ("1.0.0", "honest")


def test_a_refused_publish_names_what_it_refuses(hub, client, tmp_path, monkeypatch):
    import agents.web as web

    mk = _market(tmp_path)
    source = mk.skills_dir / "linked"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"# Linked\nversion: 1.0\n")
    (source / "helper.py").symlink_to(tmp_path / "mk.db")
    monkeypatch.setattr(web.orch, "marketplace", mk, raising=False)
    reply = client.post("/api/skills/marketplace/publish", json={"name": "linked"}, headers=ADMIN)
    assert reply.status_code == 422 and "a special file" in reply.json()["error"]


# ── n-7: the escaped ceiling and the description cut ─────────────────────────────

def test_a_file_exactly_at_the_escaped_ceiling_is_served_and_one_byte_more_is_not(hub):
    exact = "\x01" * 13215 + "a" * 51782                           # 6 x 13215 + 51782 = 131072
    over = "\x01" * 13216 + "a" * 51781
    hub.write("edge", files={"exact.md": exact, "over.md": over})
    hub.load()
    assert len(exact.encode()) < 65536 and MAX_ENCODED_BYTES == 6 * 13215 + 51782
    assert _call(hub.server, TOOL_VIEW, {"name": "edge", "file": "exact.md"})["ok"] is True
    got = _call(hub.server, TOOL_VIEW, {"name": "edge", "file": "over.md"})
    assert got["ok"] is False and got["reason"] == "skill_file_too_large"


def test_a_long_description_is_cut_to_what_fits_not_to_nothing():
    cut = _cut_encoded("\x01" * 1024, MAX_DESCRIPTION_BYTES)
    assert len(cut) == MAX_DESCRIPTION_BYTES // 6                 # 341 of them fit in 2 KiB escaped
    assert _cut_encoded("plain", MAX_DESCRIPTION_BYTES) == "plain"


def test_the_helpers_write_line_ends_as_given(hub):
    path = hub.write("lf", body="one\ntwo\n", files={"notes.md": "a\nb\n"})
    assert b"\r\n" not in (path / "SKILL.md").read_bytes() + (path / "notes.md").read_bytes()
    assert Path(path / "main.py").exists() is False
