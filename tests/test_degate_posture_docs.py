"""Pins one consistent post-de-gate CI posture across the docs (DRA-30).

Truth as of 2026-08-29: the owner decided to *remove* the merge gates rather than promote
matrix/parity to required checks (#981). No workflow blocks a PR; the route-auth-matrix and
HUD-parity tests run in the advisory `test (ubuntu-latest)` lane plus post-merge lanes. Several
docs still described the old "promote to required" plan as pending, which is the contradiction
this file stops from coming back.

The GitHub *settings* half is owner-side and unobservable from the repo — these tests assert only
what the tree can prove, plus that the recovery path for a stale required check is documented.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_security_route_audit_does_not_claim_f10_is_still_open() -> None:
    text = _read("docs/SECURITY_ROUTE_AUDIT_2026-06-17.md")
    assert "Still open (owner-side, SEC-4)" not in text
    assert "promote the matrix/parity tests to a *required* branch-protection check" not in text
    assert "de-gate" in text.lower()
    assert "docs/restore/" in text or "restore/README.md" in text


def test_zero_ledger_sec4_is_not_an_open_owner_packet() -> None:
    rows = [ln for ln in _read("docs/BACKLOG_ZERO_LEDGER.md").splitlines() if "| SEC-4 |" in ln]
    assert rows, "SEC-4 row disappeared from the ledger"
    for row in rows:
        assert "promote matrix/parity to required branch-protection checks)" not in row
        assert "CLOSED by reversal" in row


def test_runbook_documents_the_expected_check_deadlock() -> None:
    text = _read("docs/MAINTENANCE_RUNBOOK.md")
    assert "## 10." in text
    assert "Expected" in text
    assert "required status checks" in text.lower()
    assert "OWNER_TASKS.md" in text
    assert "restore/README.md" in text


def test_owner_tasks_points_at_the_deadlock_runbook() -> None:
    text = _read("docs/OWNER_TASKS.md")
    assert "MAINTENANCE_RUNBOOK.md" in text
    assert "Expected — Waiting for status to be reported" in text


def test_no_workflow_comment_presumes_required_checks() -> None:
    """A workflow may not describe itself relative to gates that no longer exist."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "the required `CI` checks" not in text, path.name


def test_security_and_lockfile_lanes_are_restored_deliberately() -> None:
    """The four security scan jobs (gitleaks/semgrep/pip-audit/bandit) went with security.yml on
    2026-08-29 (#981) and came back on 2026-09-02 (CTO decision D1, docs/decisions/
    2026-09-02-cto-ci-posture-and-1.0-freeze.md) together with the lockfile-drift lane. A restore
    is only honest when docs/restore/README.md records it, so this pins both halves."""
    assert (WORKFLOWS / "security.yml").exists()
    assert (WORKFLOWS / "lockfile.yml").exists()
    readme = _read("docs/restore/README.md")
    assert "A-security-scans" in readme
    assert "2026-09-02" in readme


def test_security_chapter_states_the_de_gate_posture_instead_of_deferring_it() -> None:
    """DRA-30 remainder — chapter 08 was the fifth surface and still filed the required-check
    question under "could not verify on this checkout". It is verifiable: the gates were
    removed by #981, not promoted, so the chapter must say so rather than leave a tester
    hunting an owner-side setting that no longer has a workflow behind it."""
    text = _read("docs/test-manual/08-security-privacy.md")
    assert "whether the four CI security jobs are configured as" not in text
    assert "#981" in text
    assert "de-gate" in text.lower()
    assert "docs/restore/" in text
    assert "test (ubuntu-latest)" in text
