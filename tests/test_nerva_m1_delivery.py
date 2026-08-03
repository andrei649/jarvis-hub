"""Fail-closed checks for the additive post-E0 Nerva M1 delivery snapshot."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_m1_snapshot_records_current_e1_and_dependency_posture():
    snapshot = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )

    assert "9235ef69961862df49826a910be00955d7be420e" in snapshot
    assert "E1.1 / #792 / PR #793" in snapshot
    assert "On a feature branch, these artifacts remain candidate evidence only" in snapshot
    assert (
        "When this snapshot is present on `main` through merged PR #793, E1.1 is"
        in snapshot
    )
    assert "pseudonymous/linkable" in snapshot
    assert (
        "#781 Atlas, #783 Synapse and #784 Research Lab remain separately eligible"
        in snapshot
    )
    assert "#782 Episodes remains blocked only by #781" in snapshot
    assert (
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority"
        in snapshot
    )


def test_e0_marker_remains_historical_and_m1_snapshot_is_additive():
    backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    snapshot = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )

    marker = "<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->"
    assert marker in backlog
    assert marker in status
    assert "This post-E0 snapshot is additive" in snapshot
    assert "immutable E0 marker blocks" in snapshot
