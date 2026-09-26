"""H318, the seventh review (review-H318g) — its findings, pinned.

- m-1: a SKILL.sig that could not be read for a moment at the standing read as unsigned,
  so an approved change was applied with nothing to renew and the skill went hidden. A
  standing that cannot be read is retried, as the later read already was.
- nits: where the temporary file cannot sit beside the folder (another filesystem, a
  root the hub cannot write) it is made in the folder; it is created with the file's
  mode; a signature that stays unreadable is warned about once, not every pass; a failed
  replace leaves no temporary file anywhere; /v1's reject-only covers a rename
  (tools.test.js).
"""

from __future__ import annotations

import errno
import logging
import os
import pathlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.skills import proposals as proposals_mod
from agents.core.skills import signing
from tests.test_h318c_skill_review import hub  # noqa: F401  (a fixture)
from tests.test_h318d_skill_review import _ledger


def _vouched(hub, name="tool"):
    path = hub.write(name, code=True)
    hub.registry.approve(path)
    signing.sign_skill(path)
    return path


# ── m-1: an unreadable standing changes nothing ──────────────────────────────────

def test_a_standing_that_cannot_be_read_for_a_moment_is_retried(hub, monkeypatch):
    path = _vouched(hub)
    before = (path / "SKILL.md").read_bytes()
    hub.load()
    rec, _current = _ledger(hub, "tool")
    real, failed = signing.verify_skill, []

    def verify_skill(*args, **kwargs):
        if not failed:
            failed.append(True)
            raise PermissionError(13, "sharing violation")
        return real(*args, **kwargs)

    monkeypatch.setattr(signing, "verify_skill", verify_skill)
    out = hub.curator.apply_decisions()
    assert out["outcomes"][0]["reason"] == "unreadable_signature"
    assert (path / "SKILL.md").read_bytes() == before
    assert signing.verify_skill(path)[0] is True and hub.registry.is_approved(path)
    assert hub.proposals.get(rec["id"])["status"] == "approved"
    out = hub.curator.apply_decisions()                             # the next decision applies it
    assert out["applied"] == ["tool"] and out["outcomes"][0]["state"] == "shown"


def test_a_signature_that_is_not_utf8_still_reads_as_unsigned(hub):
    path = hub.write("plain", code=True)
    (path / "SKILL.sig").write_bytes(b"\xff\xfe not utf-8")
    loader = hub.load()                                          # such a skill does not load
    standing = loader.owner_standing(SimpleNamespace(path=str(path), external=True))
    assert standing["unreadable"] is False and standing["signed"] is False


# ── n-1: the folder is used when beside it cannot be ─────────────────────────────

@pytest.mark.parametrize("error", [errno.EXDEV, errno.EACCES])
def test_the_folder_is_used_when_beside_it_cannot_be(tmp_path, monkeypatch, error):
    skill = tmp_path / "skill"
    skill.mkdir()
    target = skill / "SKILL.md"
    target.write_bytes(b"old")
    real = os.replace

    def replace(src, dst):
        if Path(src).parent == tmp_path:
            raise OSError(error, os.strerror(error))
        return real(src, dst)

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    proposals_mod._write_atomic(target, b"new")
    assert target.read_bytes() == b"new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["skill"] and [p.name for p in skill.iterdir()] == ["SKILL.md"]


def test_another_error_beside_the_folder_is_not_retried_inside(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    target = skill / "SKILL.md"
    target.write_bytes(b"old")

    def replace(src, dst):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    with pytest.raises(OSError):
        proposals_mod._write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["skill"] and [p.name for p in skill.iterdir()] == ["SKILL.md"]


# ── n-2: never readable wider than the file ──────────────────────────────────────

@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_the_staged_file_is_created_with_the_files_mode(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    target = skill / "SKILL.md"
    target.write_bytes(b"old")
    os.chmod(target, 0o600)
    created = []
    real = os.open

    def open_(path, flags, mode=0o777, *args, **kwargs):
        if str(path).endswith(".tmp"):
            created.append(mode)
        return real(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(proposals_mod.os, "open", open_)
    proposals_mod._write_atomic(target, b"new")
    assert created == [0o600] and os.stat(target).st_mode & 0o777 == 0o600


# ── n-3: warned once ─────────────────────────────────────────────────────────────

def test_a_signature_that_stays_unreadable_is_warned_about_once(hub, monkeypatch, caplog):
    _vouched(hub)
    hub.load()
    _ledger(hub, "tool")
    real = pathlib.Path.read_bytes

    def read_bytes(self):
        if self.name == "SKILL.sig":
            raise PermissionError(13, "denied")
        return real(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        assert hub.curator.apply_decisions()["outcomes"][0]["reason"] == "unreadable_signature"
    assert sum("could not be read" in r.getMessage() for r in caplog.records) == 1
