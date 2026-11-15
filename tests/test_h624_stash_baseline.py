"""V56 regression: never replay an owner stash on a different checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agents.core import hub_update_apply


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "base.txt")
    git(root, "commit", "-qm", "base")
    baseline = git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(hub_update_apply.hub_update, "repo_root", lambda: root)
    return root, baseline


def make_stash(root: Path, baseline: str) -> str:
    (root / "owner.txt").write_text("owner data\n", encoding="utf-8")
    git(root, "add", "owner.txt")
    git(root, "stash", "push", "--message", "nerva-update-test")
    stash = git(root, "rev-parse", "refs/stash")
    assert git(root, "rev-parse", f"{stash}^1") == baseline
    return stash


def test_stash_restores_on_exact_original_clean_commit_and_is_retained(repo):
    root, baseline = repo
    stash = make_stash(root, baseline)
    receipt = {"stash": stash, "stash_parent": baseline, "from": baseline}
    lines = []

    assert hub_update_apply._restore_stash(receipt, lines.append) is True
    assert receipt["stash_restored"] is True
    assert (root / "owner.txt").read_text(encoding="utf-8") == "owner data\n"
    assert git(root, "rev-parse", "refs/stash") == stash


def test_cleanly_applicable_stash_is_refused_after_head_moves(repo):
    root, baseline = repo
    stash = make_stash(root, baseline)
    (root / "external.txt").write_text("compatible unrelated change\n", encoding="utf-8")
    git(root, "add", "external.txt")
    git(root, "commit", "-qm", "new unrelated head")
    moved_head = git(root, "rev-parse", "HEAD")
    receipt = {"stash": stash, "stash_parent": baseline, "from": baseline}
    lines = []

    assert hub_update_apply._restore_stash(receipt, lines.append) is False
    assert receipt["stash_restored"] is False
    assert "original commit" in receipt["action_needed"]
    assert git(root, "rev-parse", "HEAD") == moved_head
    assert not (root / "owner.txt").exists()
    assert git(root, "rev-parse", "refs/stash") == stash
    assert "NOT re-applied" in "\n".join(lines)


def test_dirty_tree_refuses_before_apply_and_keeps_stash(repo):
    root, baseline = repo
    stash = make_stash(root, baseline)
    (root / "late.txt").write_text("late data\n", encoding="utf-8")
    receipt = {"stash": stash, "stash_parent": baseline, "from": baseline}

    assert hub_update_apply._restore_stash(receipt, lambda _line: None) is False
    assert (root / "late.txt").exists() and not (root / "owner.txt").exists()
    assert git(root, "rev-parse", "refs/stash") == stash


def test_malformed_stash_is_rejected_before_any_git_call(monkeypatch):
    calls = []
    monkeypatch.setattr(hub_update_apply, "_git", lambda *a, **k: calls.append(a))
    receipt = {"stash": "--exec=bad", "stash_parent": "b" * 40, "from": "b" * 40}

    assert hub_update_apply._restore_stash(receipt, lambda _line: None) is False
    assert calls == []


@pytest.mark.parametrize("stash", [0, False, [], ""])
def test_falsy_but_present_stash_is_not_treated_as_no_stash(monkeypatch, stash):
    calls = []
    monkeypatch.setattr(hub_update_apply, "_git", lambda *a, **k: calls.append(a))
    receipt = {"stash": stash, "stash_parent": "b" * 40, "from": "b" * 40}

    assert hub_update_apply._restore_stash(receipt, lambda _line: None) is False
    assert calls == []


def test_rollback_cannot_claim_complete_when_owner_stash_was_not_restored():
    receipt = {"kind": "update", "from": "a" * 40, "to": "b" * 40,
               "migrations": False, "dependencies_restored": True,
               "stash": "d" * 40, "stash_restored": False}

    assert hub_update_apply._rollback_result(receipt, "a" * 40) == (
        "rollback_incomplete", "owner_stash_not_restored")


def test_stash_from_another_parent_is_refused_and_retained(repo):
    root, baseline = repo
    git(root, "checkout", "-qb", "other-base")
    (root / "other.txt").write_text("other\n", encoding="utf-8")
    git(root, "add", "other.txt")
    git(root, "commit", "-qm", "other base")
    other = git(root, "rev-parse", "HEAD")
    stash = make_stash(root, other)
    git(root, "checkout", "-q", baseline)
    receipt = {"stash": stash, "stash_parent": baseline, "from": baseline}

    assert hub_update_apply._restore_stash(receipt, lambda _line: None) is False
    assert not (root / "owner.txt").exists()
    assert git(root, "rev-parse", "refs/stash") == stash
