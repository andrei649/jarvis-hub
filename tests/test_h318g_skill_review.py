"""H318, the sixth review (review-H318f) — its findings, pinned.

- m-1: the whole-file write staged its temporary file inside the skill's folder, where
  a file left by a crash counted as a member of the skill and voided its signature. It
  is staged beside the folder now, and flushed before the rename.
- nits: a SKILL.sig read that fails is retried, not given up (tests/test_h318f); the
  file's mode is kept; SKILL.sig is not put back over new text whose SKILL.md could not
  be (N13); /v1 offers only Reject for a change the hub will refuse (tools.test.js).
"""

from __future__ import annotations

import os
from pathlib import Path

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


# ── m-1: the temporary file never sits in the skill ──────────────────────────────

def test_a_crash_before_the_rename_leaves_the_skill_as_it_was(hub, monkeypatch):
    path = _vouched(hub)
    members = sorted(p.name for p in path.iterdir())
    hub.load()
    _ledger(hub, "tool")

    def crashed(src, dst):
        raise OSError(5, "the process died here")

    monkeypatch.setattr(proposals_mod.Path, "unlink", lambda self, missing_ok=False: None)  # no cleanup
    monkeypatch.setattr(proposals_mod.os, "replace", crashed)
    out = hub.curator.apply_decisions()
    monkeypatch.undo()
    assert out["outcomes"][0]["reason"] == "write_failed"
    assert sorted(p.name for p in path.iterdir()) == members          # nothing new in the skill
    assert signing.verify_skill(path)[0] is True and hub.registry.is_approved(path)
    assert list(path.parent.glob(f".{path.name}.SKILL.md.*.tmp"))       # left beside it instead


def test_the_staged_file_is_beside_the_folder_and_synced(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    target = skill / "SKILL.md"
    target.write_bytes(b"old")
    moved, synced = [], []
    real_replace, real_fsync = os.replace, os.fsync

    def replace(src, dst):
        moved.append(Path(src))
        return real_replace(src, dst)

    def fsync(fd):
        synced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    monkeypatch.setattr(proposals_mod.os, "fsync", fsync)
    proposals_mod._write_atomic(target, b"new")
    assert moved[0].parent == tmp_path and synced
    assert target.read_bytes() == b"new"


# ── n-2: the mode is kept ────────────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
@pytest.mark.parametrize("mode", [0o600, 0o640])
def test_the_file_keeps_its_mode(tmp_path, mode):
    target = tmp_path / "skill" / "SKILL.md"
    target.parent.mkdir()
    target.write_bytes(b"old")
    os.chmod(target, mode)
    proposals_mod._write_atomic(target, b"new")
    assert os.stat(target).st_mode & 0o777 == mode


# ── N13: no old signature over new text ──────────────────────────────────────────

def test_a_failed_text_rollback_leaves_the_signature_that_matches_the_text(hub, monkeypatch):
    path = _vouched(hub)
    old_sig = (path / "SKILL.sig").read_bytes()
    loader = hub.load()
    _ledger(hub, "tool")

    def renew_then_fail(path, standing, snapshot=None):
        signing.sign_skill(path, snapshot=snapshot)          # a new signature over the new text
        raise OSError(28, "No space left on device")

    loader.restore_standing = renew_then_fail
    real = os.replace
    seen = []

    def replace(src, dst):
        seen.append(Path(dst).name)
        if Path(dst).name == "SKILL.md" and seen.count("SKILL.md") > 1:
            raise OSError(30, "read-only file system")     # the text rollback fails
        return real(src, dst)

    monkeypatch.setattr(proposals_mod.os, "replace", replace)
    out = hub.curator.apply_decisions()
    monkeypatch.setattr(proposals_mod.os, "replace", real)
    assert out["outcomes"][0]["reason"] == "rollback_failed"
    assert (path / "SKILL.sig").read_bytes() != old_sig
    assert signing.verify_skill(path)[0] is True             # the signature matches the text that stays
