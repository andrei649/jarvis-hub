"""Pins the CodeQL workflow's posture and the docs that describe it (DRA-16).

The workflow used to carry a false rationale — "unavailable on this private
personal repo, so the upload always errors" — plus a `continue-on-error: true`
that swallowed real analysis failures. The repo is public, code scanning is
enabled and SARIF upload succeeds, so the swallow is gone and the rationale is
now the true one: advisory by design (push-to-main + weekly, not a required
check), and red when the analysis or the upload actually breaks.

These tests also lock the deliberate 2026-08-29 de-gate: no `pull_request:`
trigger, so nothing silently re-creates the `Analyze (python)` PR check.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CODEQL = REPO / ".github/workflows/codeql.yml"


def _workflow_text() -> str:
    return CODEQL.read_text(encoding="utf-8")


def _analyze_step() -> dict:
    spec = yaml.safe_load(_workflow_text())
    steps = spec["jobs"]["analyze"]["steps"]
    (step,) = [s for s in steps if "codeql-action/analyze" in str(s.get("uses", ""))]
    return step


def test_analysis_failures_are_not_swallowed() -> None:
    """A broken analysis or failed SARIF upload must fail the job on main."""
    for step in yaml.safe_load(_workflow_text())["jobs"]["analyze"]["steps"]:
        assert "continue-on-error" not in step, step.get("name") or step.get("uses")
    assert "continue-on-error" not in yaml.safe_load(_workflow_text())["jobs"]["analyze"]
    assert "codeql-action/analyze" in str(_analyze_step()["uses"])


def test_rationale_does_not_claim_a_private_repo_or_a_broken_upload() -> None:
    """The stale rationale ('private repo', 'always errors') is factually wrong:
    the repo is public and the upload succeeds."""
    text = _workflow_text().lower()
    assert "private repo" not in text
    assert "private personal repo" not in text
    assert "always errors" not in text


def test_workflow_states_the_advisory_posture() -> None:
    text = _workflow_text().lower()
    assert "advisory" in text
    assert "required" in text  # says it is *not* a required status check


def test_de_gate_is_locked_no_pull_request_trigger() -> None:
    """The owner removed the `Analyze (python)` PR check on 2026-08-29. Re-adding
    a pull_request trigger is a deliberate owner decision (restore patch K), not
    something a later edit may do silently."""
    spec = yaml.safe_load(_workflow_text())
    triggers = spec[True] if True in spec else spec["on"]
    assert "pull_request" not in triggers
    assert "pull_request_target" not in triggers
    assert triggers["push"]["branches"] == ["main"]
    assert "schedule" in triggers


def test_docs_no_longer_claim_code_scanning_is_disabled() -> None:
    for rel in ("docs/design/HUD_V2_REMAINING.md", "docs/OWNER_TASKS.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "Code scanning is not enabled" not in text, rel


def test_roadmap_no_longer_calls_codeql_permanently_non_blocking() -> None:
    text = (REPO / "docs/DEVELOPMENT_ROADMAP.md").read_text(encoding="utf-8")
    assert "permanently non-blocking" not in text
