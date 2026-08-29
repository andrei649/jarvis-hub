"""Boundary classifier tests.

Every scenario here is drawn from the session that motivated the classifier:
five attempts to weaken the movement gate, plus the two legitimate changes that
were sharing the same branch. The classifier must separate them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from classify_change_tier import classify  # noqa: E402

WORKFLOW = """\
name: ci
on: [pull_request]
permissions:
  contents: read
jobs:
  nerva-movement:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - run: python scripts/check_nerva_issue_movement.py --live
  test:
    needs: [nerva-movement]
    runs-on: ubuntu-latest
    steps:
      - name: Require successful Nerva movement on pull requests
        if: needs.nerva-movement.result != 'success'
        run: exit 1
      - run: pytest
"""

TESTS = """\
def test_ci_nerva_movement_is_pr_only():
    assert True


def test_ci_movement_permissions_are_read_only():
    assert True
"""

MANIFEST = """\
{"movement_gate": {"enforcement_state": "required",
 "receipt_control": {"fresh_owner_receipts_required": true}}}
"""


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    _write(root, files)
    _commit(root, "base")
    return root


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def _commit(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)


def _verdict(root: Path):
    return classify(str(root), "HEAD~1", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repo(
        tmp_path,
        {
            ".github/workflows/ci.yml": WORKFLOW,
            "tests/test_nerva_issue_movement.py": TESTS,
            "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json": MANIFEST,
            "nerva/core.py": "VALUE = 1\n",
        },
    )


# --- tier 0: ordinary work flows without a human -------------------------


def test_feature_change_is_tier_0(repo: Path) -> None:
    _write(repo, {"nerva/core.py": "VALUE = 2\n"})
    _commit(repo, "feat")
    v = _verdict(repo)
    assert v.tier == 0
    assert v.auto_merge_eligible


# --- tier 1, tightening or neutral: still no human -----------------------


def test_bugfix_in_gate_script_is_neutral(repo: Path) -> None:
    _write(repo, {"scripts/check_nerva_issue_movement.py": "# fix\n"})
    _commit(repo, "fix(nerva): narrow reader-thread handlers")
    v = _verdict(repo)
    assert v.tier == 1
    assert v.direction != "loosen"
    assert v.auto_merge_eligible


def test_dropping_a_write_permission_tightens(repo: Path) -> None:
    _write(repo, {".github/workflows/ci.yml": WORKFLOW.replace(
        "  contents: read\njobs:", "  contents: read\n  actions: read\njobs:")})
    _commit(repo, "ci: narrow")
    v = _verdict(repo)
    assert v.auto_merge_eligible


# --- tier 1, loosening: held for the owner -------------------------------


def test_continue_on_error_loosens(repo: Path) -> None:
    _write(repo, {".github/workflows/ci.yml": WORKFLOW.replace(
        "  nerva-movement:\n", "  nerva-movement:\n    continue-on-error: true\n")})
    _commit(repo, "ci: advisory gate")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert not v.auto_merge_eligible


def test_removing_needs_edge_loosens(repo: Path) -> None:
    _write(repo, {".github/workflows/ci.yml": WORKFLOW.replace(
        "    needs: [nerva-movement]\n", "")})
    _commit(repo, "ci: decouple")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert any("job dependency" in r for r in v.reasons)


def test_removing_hard_fail_guard_loosens(repo: Path) -> None:
    stripped = WORKFLOW.replace(
        "      - name: Require successful Nerva movement on pull requests\n"
        "        if: needs.nerva-movement.result != 'success'\n"
        "        run: exit 1\n", "")
    _write(repo, {".github/workflows/ci.yml": stripped})
    _commit(repo, "ci: drop guard")
    v = _verdict(repo)
    assert v.direction == "loosen"


def test_deleting_assertion_tests_loosens(repo: Path) -> None:
    _write(repo, {"tests/test_nerva_issue_movement.py":
                  "def test_ci_nerva_movement_is_pr_only():\n    assert True\n"})
    _commit(repo, "test: trim")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert any("test_ci_movement_permissions_are_read_only" in r for r in v.reasons)


def test_new_write_permission_loosens(repo: Path) -> None:
    _write(repo, {".github/workflows/ci.yml": WORKFLOW.replace(
        "  contents: read\njobs:", "  contents: write\njobs:")})
    _commit(repo, "ci: widen")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert any("write permission" in r for r in v.reasons)


def test_new_secret_reference_loosens(repo: Path) -> None:
    _write(repo, {".github/workflows/ci.yml": WORKFLOW.replace(
        "      - run: pytest", "      - run: pytest\n        env:\n"
        "          TOKEN: ${{ secrets.DEPLOY_TOKEN }}")})
    _commit(repo, "ci: add token")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert any("DEPLOY_TOKEN" in r for r in v.reasons)


def test_enforcement_downgrade_loosens(repo: Path) -> None:
    _write(repo, {"docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json":
                  MANIFEST.replace('"required"', '"safety_disabled"')})
    _commit(repo, "manifest: disable")
    v = _verdict(repo)
    assert v.direction == "loosen"
    assert any("enforcement_state" in r for r in v.reasons)


def test_deleting_a_boundary_file_loosens(repo: Path) -> None:
    (repo / ".github/workflows/ci.yml").unlink()
    _commit(repo, "ci: remove")
    v = _verdict(repo)
    assert v.direction == "loosen"


def test_weakening_codeowners_loosens(repo: Path) -> None:
    _write(repo, {".github/CODEOWNERS": "/.github/ @andrei649\n/scripts/ @andrei649\n"})
    _commit(repo, "codeowners")
    _write(repo, {".github/CODEOWNERS": "/.github/ @andrei649\n"})
    _commit(repo, "codeowners: trim")
    v = _verdict(repo)
    assert v.direction == "loosen"
