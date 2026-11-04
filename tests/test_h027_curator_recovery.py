"""Owner-approved curator recovery through the actual CLI and HTTP entrypoints."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_h027_entrypoints import owner  # noqa: F401


def _apply(owner, *argv):
    pending = owner.invoke(*argv)
    assert pending["ok"] is True and pending["status"] == "pending"
    applied = owner.decide(pending["card_id"])
    assert applied["ok"] is True and applied["status"] == "applied"
    return applied


def _preview(owner, operation, args):
    response = owner.client.post(
        "/api/curator/preview", json={"operation": operation, "args": args},
        headers={"X-Admin-Token": "owner-curator"},
    )
    assert response.status_code in {200, 409}, response.text
    return response.json()


def test_selected_backup_restores_archived_bytes_and_keeps_safety_snapshot(owner):
    backup = _apply(owner, "backup", "--reason", "before owner archive")
    backup_id = backup["backup_id"]
    assert (owner.operations.backup_dir / f"{backup_id}.tar.gz").is_file()
    archived = _apply(owner, "archive", "local-curation")
    assert archived["archive_ids"] and not owner.path.exists()

    restored = _apply(owner, "rollback", "--backup-id", backup_id)
    assert (owner.path / "SKILL.md").read_bytes() == owner.original
    assert owner.orch.skill_usage.get("local-curation")["state"] == "active"
    assert owner.invoke("list-archived")["items"] == []
    safety_id = restored["backup_id"]
    assert safety_id != backup_id
    assert (owner.operations.backup_dir / f"{safety_id}.tar.gz").is_file()
    assert {backup_id, safety_id} <= {row["id"] for row in owner.invoke("rollback", "--list")["items"]}


@pytest.mark.parametrize("operation", ["pin", "pause"])
def test_single_entry_pin_or_pause_rollback_reverses_only_approved_effect(owner, operation):
    before_bytes = (owner.path / "SKILL.md").read_bytes()
    applied = _apply(owner, operation, *("local-curation",) if operation == "pin" else ())
    assert (owner.orch.skill_usage.get("local-curation")["pinned"] if operation == "pin"
            else owner.invoke("status")["paused"]) is True

    rolled = _apply(owner, "rollback", "--ledger-id", applied["ledger_id"])
    assert rolled["ledger_id"]
    assert (owner.orch.skill_usage.get("local-curation")["pinned"] if operation == "pin"
            else owner.invoke("status")["paused"]) is False
    assert (owner.path / "SKILL.md").read_bytes() == before_bytes
    assert any(row["operation"] == "rollback" for row in owner.invoke("ledger")["items"])


def test_single_entry_adoption_rollback_preserves_unknown_origin(owner):
    owner.orch.skill_usage.restore_record("local-curation", None)
    assert owner.invoke("list-unmanaged")["items"][0]["name"] == "local-curation"
    adopted = _apply(owner, "adopt", "local-curation")
    assert owner.invoke("list-unmanaged")["items"] == []

    _apply(owner, "rollback", "--ledger-id", adopted["ledger_id"])
    assert owner.invoke("list-unmanaged")["items"][0]["name"] == "local-curation"
    assert owner.orch.skill_usage.get("local-curation") is None
    assert (owner.path / "SKILL.md").read_bytes() == owner.original


@pytest.mark.parametrize("operation, age_days", [("run", 60), ("prune", 120)])
def test_single_entry_age_transition_rollback_restores_usage_and_bytes(owner, monkeypatch, operation, age_days):
    monkeypatch.setattr(
        owner.operations, "get_setting",
        lambda key, default=None: True if key == "cognition.review_enabled" else default,
    )
    record = owner.orch.skill_usage.get("local-curation")
    record["last_used_at"] = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    owner.orch.skill_usage.restore_record("local-curation", record)
    before = owner.orch.skill_usage.get("local-curation")

    applied = _apply(owner, operation, *("--days", "90") if operation == "prune" else ())
    if operation == "run":
        assert owner.orch.skill_usage.get("local-curation")["state"] == "stale"
        assert owner.path.is_dir()
    else:
        assert owner.orch.skill_usage.get("local-curation")["state"] == "archived"
        assert not owner.path.exists()

    _apply(owner, "rollback", "--ledger-id", applied["ledger_id"])
    assert (owner.path / "SKILL.md").read_bytes() == owner.original
    assert owner.orch.skill_usage.get("local-curation") == before
    assert owner.invoke("list-archived")["items"] == []


def test_purge_requires_positive_ttl_and_predelete_recovery_snapshot(owner, monkeypatch):
    archived = _apply(owner, "archive", "local-curation")
    archive_id = archived["archive_ids"][0]
    assert _preview(owner, "purge", {})["status"] == "refused"
    assert owner.invoke("list-archived")["items"][0]["id"] == archive_id

    # The fixture models a legitimately old archive without waiting for wall time.
    old = datetime.now(UTC) - timedelta(days=3)
    state = owner.operations._state()
    state["archives"][archive_id]["at"] = old.isoformat()
    owner.operations._save(state)
    os.utime(owner.operations.archive_dir / archive_id, (old.timestamp(), old.timestamp()))
    monkeypatch.setattr(
        owner.operations, "get_setting",
        lambda key, default=None: 1 if key == "learning.curator_purge_days" else default,
    )

    purged = _apply(owner, "purge")
    assert not (owner.operations.archive_dir / archive_id).exists()
    assert owner.invoke("list-archived")["items"] == []
    safety = owner.operations.backup_dir / f"{purged['backup_id']}.tar.gz"
    assert safety.is_file()
    state = owner.operations._state()
    assert owner.operations._verify_backup(safety, state["backups"][purged["backup_id"]]["digest"])

    recovered = _apply(owner, "rollback", "--backup-id", purged["backup_id"])
    assert recovered["backup_id"] != purged["backup_id"]
    assert owner.invoke("list-archived")["items"][0]["id"] == archive_id
    restored = _apply(owner, "restore", archive_id)
    assert restored["status"] == "applied"
    assert (owner.path / "SKILL.md").read_bytes() == owner.original


def test_tampered_backup_or_archive_refuses_before_mutating_owner_bytes(owner):
    backup = _apply(owner, "backup")
    backup_path = owner.operations.backup_dir / f"{backup['backup_id']}.tar.gz"
    backup_path.write_bytes(backup_path.read_bytes() + b"tampered")
    assert _preview(owner, "rollback", {"backup_id": backup["backup_id"]})["status"] == "refused"
    assert (owner.path / "SKILL.md").read_bytes() == owner.original

    archived = _apply(owner, "archive", "local-curation")
    archive_id = archived["archive_ids"][0]
    (owner.operations.archive_dir / archive_id / "SKILL.md").write_bytes(owner.original + b"\nchanged")
    assert _preview(owner, "restore", {"archive_id": archive_id})["status"] == "refused"
    assert not owner.path.exists()
    assert (owner.operations.archive_dir / archive_id).exists()


def test_owner_edit_conflicts_with_selected_backup_rollback(owner):
    backup = _apply(owner, "backup")
    edited = owner.original + b"\nOwner edit after backup.\n"
    (owner.path / "SKILL.md").write_bytes(edited)
    result = _preview(owner, "rollback", {"backup_id": backup["backup_id"]})
    assert result["status"] == "refused" and result["reason"] == "rollback_conflict"
    assert (owner.path / "SKILL.md").read_bytes() == edited
    assert owner.invoke("ledger")["items"][0]["operation"] == "backup"
