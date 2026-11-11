"""Later owner data and decisions survive recovery of an older curator receipt."""

from tests.test_h027_entrypoints import owner  # noqa: F401


def _apply(owner, *args):
    return owner.decide(owner.invoke(*args)["card_id"])


def _preview(owner, args):
    return owner.client.post("/api/curator/preview", headers={"X-Admin-Token": "owner-curator"},
                             json={"operation": "rollback", "args": args})


def test_snapshot_cannot_remove_a_managed_skill_created_after_backup(owner):
    from agents.core.skills.usage import ORIGIN_AGENT

    backup_id = _apply(owner, "backup")["backup_id"]
    later = owner.path.parent / "later-local"
    later.mkdir()
    body = b"---\nname: later-local\ndescription: Later local fixture\n---\n\n# Later\n"
    (later / "SKILL.md").write_bytes(body)
    owner.orch.skills._load_skill(later, discovery_root=later.parent)
    owner.orch.skill_usage.note_created("later-local", ORIGIN_AGENT)
    before = owner.orch.skill_usage.path.read_bytes()
    response = _preview(owner, {"backup_id": backup_id})
    assert response.status_code == 409
    assert response.json()["reason"] == "snapshot_scope_changed"
    assert (later / "SKILL.md").read_bytes() == body
    assert owner.orch.skill_usage.path.read_bytes() == before


def test_snapshot_rollback_preserves_activity_recorded_after_backup(owner):
    backup_id = _apply(owner, "backup")["backup_id"]
    owner.orch.skill_usage.bump("local-curation", "use")
    owner.orch.skill_usage.bump("local-curation", "view")
    before = owner.orch.skill_usage.get("local-curation")
    outcome = _apply(owner, "rollback", "--backup-id", backup_id)
    assert outcome["status"] == "applied"
    after = owner.orch.skill_usage.get("local-curation")
    assert after["use_count"] == before["use_count"] == 1
    assert after["view_count"] == before["view_count"] == 1
    assert after["last_used_at"] == before["last_used_at"]
    assert after["last_viewed_at"] == before["last_viewed_at"]


def test_undo_of_pin_that_created_usage_never_erases_later_activity(owner):
    owner.orch.skill_usage.restore_record("local-curation", None)
    # Under the H349 sidecar an installed skill always has a row: the next discover (the hub
    # runs one at every start and after every curator change) makes a fresh one before a pin.
    owner.orch.skills.discover()
    first = _apply(owner, "pin", "local-curation")
    owner.orch.skill_usage.bump("local-curation", "use")
    before = owner.orch.skill_usage.get("local-curation")
    assert _apply(owner, "rollback", "--ledger-id", first["ledger_id"])["status"] == "applied"
    after = owner.orch.skill_usage.get("local-curation")
    assert after is not None and after["pinned"] is False
    assert after["use_count"] == before["use_count"] == 1
    assert after["last_used_at"] == before["last_used_at"]
    assert after["origin"] == before["origin"]


def test_old_pin_undo_cannot_reverse_a_later_owner_pin(owner):
    first = _apply(owner, "pin", "local-curation")
    _apply(owner, "unpin", "local-curation")
    _apply(owner, "pin", "local-curation")
    before = owner.orch.skill_usage.path.read_bytes()
    response = _preview(owner, {"ledger_id": first["ledger_id"]})
    assert response.status_code == 409
    assert response.json()["reason"] == "rollback_superseded"
    assert owner.orch.skill_usage.path.read_bytes() == before


def test_old_pause_undo_cannot_reverse_a_later_owner_pause(owner):
    first = _apply(owner, "pause")
    _apply(owner, "resume")
    _apply(owner, "pause")
    response = _preview(owner, {"ledger_id": first["ledger_id"]})
    assert response.status_code == 409
    assert response.json()["reason"] == "rollback_superseded"
    assert owner.invoke("status")["paused"] is True


def test_recovery_file_has_private_exclusive_creation_before_member_bytes(owner, monkeypatch):
    import os
    import tarfile
    from pathlib import Path

    real_open, real_add = os.open, tarfile.TarFile.addfile
    created = []

    def observe_open(path, flags, mode=0o777, **kwargs):
        descriptor = real_open(path, flags, mode, **kwargs)
        if not isinstance(path, int) and Path(path).is_relative_to(owner.operations.backup_dir):
            created.append((flags, mode, os.fstat(descriptor).st_size))
        return descriptor

    def observe_member(archive, info, fileobj=None):
        assert created, "recovery bytes must follow explicitly private file creation"
        assert all(mode == 0o600 and flags & os.O_EXCL and size == 0
                   for flags, mode, size in created)
        return real_add(archive, info, fileobj)

    monkeypatch.setattr(os, "open", observe_open)
    monkeypatch.setattr(tarfile.TarFile, "addfile", observe_member)
    assert _apply(owner, "backup")["status"] == "applied"


def test_approved_snapshot_recovery_preserves_supporting_script_permissions(owner):
    import stat

    script = owner.path / "scripts" / "run.sh"
    script.parent.mkdir()
    body = b"#!/bin/sh\nprintf 'local fixture'\n"
    script.write_bytes(body)
    script.chmod(0o755)
    original_mode = stat.S_IMODE(script.stat().st_mode)
    backup_id = _apply(owner, "backup")["backup_id"]
    _apply(owner, "archive", "local-curation")
    assert _apply(owner, "rollback", "--backup-id", backup_id)["status"] == "applied"
    assert script.read_bytes() == body
    assert stat.S_IMODE(script.stat().st_mode) == original_mode


def _create_identical_later_skill(owner):
    from agents.core.skills.usage import ORIGIN_AGENT, STATE_ACTIVE

    owner.path.mkdir()
    (owner.path / "SKILL.md").write_bytes(owner.original)
    owner.orch.skills._load_skill(owner.path, discovery_root=owner.path.parent)
    owner.orch.skill_usage.note_created("local-curation", ORIGIN_AGENT)
    owner.orch.skill_usage.set_state("local-curation", STATE_ACTIVE)


def _archive_bytes(owner):
    root = owner.operations.archive_dir
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_archived_snapshot_does_not_claim_a_new_identical_active_copy(owner):
    _apply(owner, "archive", "local-curation")
    backup_id = _apply(owner, "backup")["backup_id"]
    _create_identical_later_skill(owner)
    archived, usage = _archive_bytes(owner), owner.orch.skill_usage.path.read_bytes()
    response = _preview(owner, {"backup_id": backup_id})
    assert response.status_code == 409
    assert response.json()["reason"] == "snapshot_scope_changed"
    assert (owner.path / "SKILL.md").read_bytes() == owner.original
    assert _archive_bytes(owner) == archived
    assert owner.orch.skill_usage.path.read_bytes() == usage


def test_active_snapshot_does_not_claim_both_later_active_and_archived_copies(owner):
    backup_id = _apply(owner, "backup")["backup_id"]
    _apply(owner, "archive", "local-curation")
    _create_identical_later_skill(owner)
    archived, usage = _archive_bytes(owner), owner.orch.skill_usage.path.read_bytes()
    response = _preview(owner, {"backup_id": backup_id})
    assert response.status_code == 409
    assert response.json()["reason"] == "snapshot_scope_changed"
    assert (owner.path / "SKILL.md").read_bytes() == owner.original
    assert _archive_bytes(owner) == archived
    assert owner.orch.skill_usage.path.read_bytes() == usage
