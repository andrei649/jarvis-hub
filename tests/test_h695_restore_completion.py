"""H695: a staged rollback backup is complete only after exact applied-result proof."""

from __future__ import annotations

from agents.core import backup, hub_update_apply

IDENTITY = {"name": "jarvis-backup-pre-update.tar.gz", "staged_at": "2026-11-13T10:00:00+00:00",
            "sha256": "a" * 64}
GOOD = {**IDENTITY, "status": "restored", "ok": True}


def receipt(**extra):
    return {"kind": "update", "from": "b" * 40, "to": "c" * 40,
            "migrations": ["agents/core/persistence/migrations.py"],
            "data_restore_staged": True, "data_restore_stage": dict(IDENTITY),
            "data_restored": False, "backup": IDENTITY["name"], **extra}


def test_staging_is_separate_from_completion_and_keeps_exact_identity(monkeypatch):
    monkeypatch.setattr(backup, "stage_restore", lambda *a, **k: {"ok": True, **IDENTITY})
    current = receipt()
    hub_update_apply._record_data_restore_stage(current, lambda _line: None, "self")
    assert current["data_restore_staged"] is True
    assert current["data_restore_stage"] == IDENTITY
    assert current["data_restored"] is False


def test_only_matching_success_marks_data_restored(monkeypatch):
    monkeypatch.setattr(backup, "last_restore", lambda: GOOD)
    current = receipt()
    assert hub_update_apply._rollback_result(current, "b" * 40) == ("rolled_back", None)
    assert current["data_restored"] is True


def test_nonmatching_or_noncomplete_restore_proof_stays_incomplete(monkeypatch):
    cases = [
        None,
        {**GOOD, "name": "jarvis-backup-stale.tar.gz"},
        {**GOOD, "staged_at": "2026-11-12T10:00:00+00:00"},
        {**GOOD, "sha256": "b" * 64},
        {**IDENTITY, "status": "failed", "ok": False},
        {**IDENTITY, "status": "deferred", "ok": False},
        {**IDENTITY, "status": "cancelled", "ok": False},
        {**IDENTITY, "status": "interrupted", "ok": False},
        {**IDENTITY, "status": "restored", "ok": False},
        {**IDENTITY, "status": "restored", "ok": 1},
    ]
    for proof in cases:
        monkeypatch.setattr(backup, "last_restore", lambda proof=proof: proof)
        current = receipt()
        result, reason = hub_update_apply._rollback_result(current, "b" * 40)
        assert result == "rollback_incomplete", proof
        assert reason in {"data_restore_unconfirmed", "data_restore_failed"}, proof
        assert current["data_restored"] is False
        assert "last-restore.json" in current["action_needed"]


def test_unreadable_restore_proof_is_incomplete(monkeypatch):
    def unreadable():
        raise OSError("fixture unreadable")
    monkeypatch.setattr(backup, "last_restore", unreadable)
    current = receipt()
    assert hub_update_apply._rollback_result(current, "b" * 40) == (
        "rollback_incomplete", "data_restore_unconfirmed")
    assert current["data_restored"] is False


def test_legacy_boolean_stage_claim_cannot_prove_completion(monkeypatch):
    monkeypatch.setattr(backup, "last_restore", lambda: GOOD)
    current = receipt(data_restore_staged=None, data_restore_stage=None, data_restored=True)
    current.pop("data_restore_staged")
    current.pop("data_restore_stage")
    assert hub_update_apply._rollback_result(current, "b" * 40) == (
        "rollback_incomplete", "data_restore_identity_missing")
    assert current["data_restored"] is False


def test_failed_stage_and_corrupt_stage_identity_cannot_complete(monkeypatch):
    monkeypatch.setattr(backup, "stage_restore", lambda *a, **k: {"ok": False, "problem": "drill failed"})
    current = receipt()
    staged, identity = hub_update_apply._stage_data_restore(current, lambda _line: None, "self")
    assert staged is False and identity is None
    current["data_restore_staged"] = staged
    current["data_restore_stage"] = identity
    assert hub_update_apply._rollback_result(current, "b" * 40) == (
        "rollback_incomplete", "data_restore_not_staged")

    monkeypatch.setattr(backup, "last_restore", lambda: GOOD)
    current = receipt(data_restore_stage={**IDENTITY, "sha256": "not-a-digest"})
    assert hub_update_apply._rollback_result(current, "b" * 40) == (
        "rollback_incomplete", "data_restore_identity_missing")


def test_dependency_failure_precedes_restore_failure(monkeypatch):
    monkeypatch.setattr(backup, "last_restore", lambda: {**IDENTITY, "status": "failed", "ok": False})
    current = receipt(dependencies_restored=False)
    assert hub_update_apply._rollback_result(current, "b" * 40) == (
        "rollback_incomplete", "dependency_reinstall_failed")


def test_no_data_rollback_does_not_require_restore_proof(monkeypatch):
    monkeypatch.setattr(backup, "last_restore", lambda: None)
    current = {"kind": "rollback", "from": "b" * 40, "to": "c" * 40,
               "restore_data": False, "dependencies_restored": True}
    assert hub_update_apply._rollback_result(current, "c" * 40) == ("rolled_back", None)
    assert "data_restored" not in current
