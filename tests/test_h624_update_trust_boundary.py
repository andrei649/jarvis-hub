"""H624: a slow backup or signature check cannot outlive update authority."""

from __future__ import annotations

import pytest

from agents.core import hub_restart, hub_update_apply

FROM = "a" * 40
TO = "b" * 40
OTHER = "c" * 40


@pytest.fixture
def isolated_update(tmp_path, monkeypatch):
    state = tmp_path / "update"
    monkeypatch.setattr(hub_update_apply, "state_dir", lambda: state)
    monkeypatch.setattr(hub_update_apply, "head", lambda: FROM)
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value: TO if value == TO else None)
    monkeypatch.setattr(hub_restart, "request",
                        lambda *_a: pytest.fail("runtime restart was reached"))
    monkeypatch.setattr(hub_update_apply, "install_dependencies",
                        lambda *_a: pytest.fail("dependency install was reached"))
    return state


def _payload(*, stash=False):
    return {"from": FROM, "to": TO, "target_ref": TO, "tag": None,
            "from_version": "1", "to_version": "2", "signer": None,
            "dependencies_changed": False, "migrations": False,
            "dirty_policy": "stash" if stash else "refuse"}


@pytest.mark.parametrize("stash", [False, True])
def test_trust_revoked_during_backup_refuses_merge_and_restores_stash(
        isolated_update, monkeypatch, stash):
    hub_update_apply._write_trust({"mode": "pinned", "commit": TO}, "owner", None)
    dirty_reads = iter([stash, False])
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: next(dirty_reads))
    monkeypatch.setattr(hub_update_apply, "_tree_clean_for_stash_restore", lambda: True)
    git_calls = []

    def git(*args, **_kwargs):
        git_calls.append(args)
        if args[:2] == ("stash", "push"):
            return 0, "", ""
        if args[:2] == ("stash", "apply"):
            return 0, "", ""
        pytest.fail(f"unexpected Git effect: {args[0]}")

    monkeypatch.setattr(hub_update_apply, "_git", git)
    if stash:
        stash_reads = iter(["e" * 40, "d" * 40])
        monkeypatch.setattr(hub_update_apply, "_rev", lambda value:
                            next(stash_reads) if value == "stash@{0}" else
                            FROM if value == f"{'d' * 40}^1" else TO if value == TO else None)

    def backup(_log, _label):
        # This is the real local trust store, but never a real backup or Git repo.
        hub_update_apply._write_trust({"mode": "pinned", "commit": OTHER}, "owner", None)
        return {"name": "mocked-backup", "ok": True}

    monkeypatch.setattr(hub_update_apply, "_backup", backup)
    result = hub_update_apply._run_pipeline(_payload(stash=stash), "owner", 1, None)
    assert result["result"] == "refused" and result["reason"] == "untrusted_target"
    assert not any(args[0] == "merge" for args in git_calls)
    assert ("stash", "apply", "--index", "d" * 40) in git_calls if stash else not git_calls
    assert hub_update_apply.current() is None


@pytest.mark.parametrize("changed", ["head", "tree"])
def test_final_head_and_tree_fence_runs_after_slow_reverification(
        isolated_update, monkeypatch, changed):
    state = {"head": FROM, "dirty": False, "verifies": 0}
    monkeypatch.setattr(hub_update_apply, "head", lambda: state["head"])
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: state["dirty"])

    def verify(_commit, _tag):
        state["verifies"] += 1
        if state["verifies"] == 2:
            state[changed if changed == "head" else "dirty"] = OTHER if changed == "head" else True
        return {"trusted": True, "how": "pinned", "signer": None}

    monkeypatch.setattr(hub_update_apply, "verify_target", verify)
    monkeypatch.setattr(hub_update_apply, "_backup",
                        lambda *_a: {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "_git",
                        lambda *_a, **_k: pytest.fail("Git merge ran after a changed final fence"))
    result = hub_update_apply._run_pipeline(_payload(), "owner", 1, None)
    assert state["verifies"] == 2
    assert result["result"] == "refused"
    assert result["reason"] in {"head_moved", "tree_changed"}


def test_second_trust_check_error_restores_prepared_stash_and_refuses_merge(
        isolated_update, monkeypatch):
    checks = 0
    git_calls = []

    def verify(_commit, _tag):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise OSError("private trust store path")
        return {"trusted": True, "how": "pinned", "signer": None}

    def git(*args, **_kwargs):
        git_calls.append(args)
        if args[:2] in {("stash", "push"), ("stash", "apply")}:
            return 0, "", ""
        pytest.fail("Git merge ran after trust verification failed")

    monkeypatch.setattr(hub_update_apply, "verify_target", verify)
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: True)
    monkeypatch.setattr(hub_update_apply, "_tree_clean_for_stash_restore", lambda: True)
    stash_reads = iter(["e" * 40, "d" * 40])
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value:
                        next(stash_reads) if value == "stash@{0}" else
                        FROM if value == f"{'d' * 40}^1" else TO if value == TO else None)
    monkeypatch.setattr(hub_update_apply, "_backup",
                        lambda *_a: {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "_git", git)
    result = hub_update_apply._run_pipeline(_payload(stash=True), "owner", 1, None)
    assert checks == 2 and result["result"] == "refused"
    assert result["reason"] == "trust_check_failed"
    assert git_calls[0][:2] == ("stash", "push")
    assert ("stash", "apply", "--index", "d" * 40) in git_calls
    assert "private trust store path" not in "\n".join(result["log"])


def test_stash_push_that_created_no_new_object_does_not_adopt_previous_stash(
        isolated_update, monkeypatch):
    hub_update_apply._write_trust({"mode": "pinned", "commit": TO}, "owner", None)
    monkeypatch.setattr(hub_update_apply, "_dirty", lambda: True)
    monkeypatch.setattr(hub_update_apply, "_backup",
                        lambda *_a: {"name": "mocked-backup", "ok": True})
    monkeypatch.setattr(hub_update_apply, "_rev", lambda value:
                        "d" * 40 if value == "stash@{0}" else TO if value == TO else None)
    calls = []

    def git(*args, **_kwargs):
        calls.append(args)
        if args[:2] == ("stash", "push"):
            return 0, "No local changes to save", ""
        pytest.fail(f"unexpected Git effect after no-op stash push: {args}")

    monkeypatch.setattr(hub_update_apply, "_git", git)
    result = hub_update_apply._run_pipeline(_payload(stash=True), "owner", 1, None)

    assert result["result"] == "failed" and result["reason"] == "stash_failed"
    assert calls == [("stash", "push", "--message", f"nerva-update-{result['id']}")]
    assert not any(args[:2] in {("stash", "apply"), ("merge", "--ff-only")} for args in calls)
    assert "inspect it" in result["action_needed"]
