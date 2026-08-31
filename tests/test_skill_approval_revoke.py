"""DRA-54 — an owner approval must die with the skill it approved.

`SkillApprovalStore` could only ever grow: `approve()` had no inverse, so a row
survived uninstalling the skill. Because `signing.source_snapshot` excludes the
signature/marker sidecars, a re-created directory with byte-identical content
hashes the same — meaning a stale row silently re-authorized a *new* tree at the
old path. These tests pin the revoke path, the discovery-time self-heal for
out-of-band deletes, and the fail-closed behaviour on a corrupt registry.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agents.core.skills.approval import SkillApprovalStore, SkillApprovalStoreError


def _make_skill(path: Path, *, body: str = "VALUE = 1\n") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (path / "main.py").write_text(body, encoding="utf-8")
    return path


def test_revoke_drops_the_row_and_is_idempotent(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)
    assert store.is_approved(skill)
    assert store.tracks_path(skill)

    assert store.revoke(skill) is True
    assert not store.is_approved(skill)
    assert not store.tracks_path(skill)
    # Nothing left to remove — a second revoke reports False and writes nothing.
    assert store.revoke(skill) is False


def test_removed_skill_row_cannot_reauthorize_a_recreated_path(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    _make_skill(skill_dir)
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill_dir)

    shutil.rmtree(skill_dir)
    assert store.prune_missing() == [str(skill_dir.resolve())]

    # Byte-identical re-creation: the fingerprint still matches, so without the
    # prune the stale row would silently approve code the owner never saw.
    _make_skill(skill_dir)
    assert store.is_approved(skill_dir) is False
    assert store.tracks_path(skill_dir) is False


def test_prune_leaves_live_rows_alone(tmp_path: Path) -> None:
    kept = _make_skill(tmp_path / "skills" / "kept")
    gone = _make_skill(tmp_path / "skills" / "gone")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(kept)
    store.approve(gone)

    shutil.rmtree(gone)
    assert store.prune_missing() == [str(gone.resolve())]
    assert store.is_approved(kept)
    assert store.tracks_path(kept)


def test_prune_does_not_drop_a_present_but_drifted_row(tmp_path: Path) -> None:
    """Fail-safe invariant from tracks_path: drifted bytes stay classified external."""
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)
    (skill / "main.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert store.prune_missing() == []
    assert store.tracks_path(skill)
    assert not store.is_approved(skill)


def test_revoke_fails_closed_on_a_corrupt_registry(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / "skills" / "demo")
    registry = tmp_path / "private" / "approvals.json"
    store = SkillApprovalStore(registry)
    store.approve(skill)

    registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(SkillApprovalStoreError):
        store.revoke(skill)
    # The corrupt registry must NOT have been rewritten as an empty valid one.
    assert registry.read_text(encoding="utf-8") == "{not json"

    with pytest.raises(SkillApprovalStoreError):
        store.prune_missing()
    assert registry.read_text(encoding="utf-8") == "{not json"


def test_discover_self_heals_rows_for_deleted_skill_dirs(tmp_path: Path, monkeypatch) -> None:
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    skill_dir = _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill_dir)
    shutil.rmtree(skill_dir)

    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    loader = loader_mod.SkillLoader(approval_store=store)
    loader.discover()

    assert not store.tracks_path(skill_dir)

    # Re-created with identical bytes: still external, never trusted again.
    _make_skill(skills_root / "demo", body="def register(skill):\n    pass\n")
    assert store.is_approved(skill_dir) is False
    loader.discover()
    skill = next(iter(loader.skills.values()))
    assert skill.sandboxed is True


def test_uninstall_call_site_revokes_immediately(tmp_path: Path, monkeypatch) -> None:
    """The router's uninstall path drops the row without waiting for a discover()."""
    from agents.core.skills import loader as loader_mod

    skills_root = tmp_path / "skills"
    skill_dir = _make_skill(skills_root / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill_dir)

    monkeypatch.setattr(loader_mod, "SKILLS_DIR", skills_root)
    loader = loader_mod.SkillLoader(approval_store=store)

    shutil.rmtree(skill_dir)
    assert loader.revoke_approval(skill_dir) is True
    assert not store.tracks_path(skill_dir)
