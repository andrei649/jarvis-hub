from __future__ import annotations

import stat
from pathlib import Path

import pytest

from scripts.reconcile_nerva_repository_ledgers import (
    BACKLOG_BLOCK,
    END,
    SPECS,
    START,
    STATUS_BLOCK,
    ReconciliationError,
    reconcile_bytes,
    reconcile_text,
    run,
)


def _with_line_ending(value: str, line_ending: str) -> str:
    return value if line_ending == "\n" else value.replace("\n", line_ending)


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.path)
def test_reconcile_preserves_every_original_byte(spec, line_ending: str) -> None:
    anchor = _with_line_ending(spec.anchor, line_ending)
    original = f"prefix{line_ending}{anchor}suffix{line_ending}".encode()

    reconciled, changed = reconcile_bytes(original, spec)

    block = _with_line_ending(spec.block, line_ending).encode()
    assert changed is True
    assert reconciled.replace(block, b"", 1) == original
    assert reconciled.count(START.encode()) == 1
    assert reconciled.count(END.encode()) == 1

    second_pass, changed_again = reconcile_bytes(reconciled, spec)
    assert changed_again is False
    assert second_pass == reconciled


def test_status_insertion_does_not_duplicate_history_separator() -> None:
    spec = next(item for item in SPECS if item.path == "STATUS.md")
    original = f"header\n{spec.anchor}history\n"

    reconciled, changed = reconcile_text(original, spec)

    assert changed is True
    expected_boundary = f"{END}\n\n---\n\n## ORIZONT 26 Update — 2026-07-04\n"
    assert expected_boundary in reconciled
    assert f"{END}\n\n---\n\n---\n" not in reconciled


@pytest.mark.parametrize(
    "text, message",
    [
        (f"{START}\nunfinished", "partial Nerva marker pair"),
        (f"{START}\nwrong\n{END}\n", "differs from canonical content"),
        (
            f"{BACKLOG_BLOCK}{BACKLOG_BLOCK}",
            "duplicate Nerva ledger blocks",
        ),
    ],
)
def test_refuses_partial_stale_or_duplicate_blocks(text: str, message: str) -> None:
    with pytest.raises(ReconciliationError, match=message):
        reconcile_text(text, SPECS[0])


def test_refuses_missing_or_ambiguous_anchor() -> None:
    spec = SPECS[0]
    with pytest.raises(ReconciliationError, match="found 0; refusing to guess"):
        reconcile_text("no stable anchor here\n", spec)
    with pytest.raises(ReconciliationError, match="found 2; refusing to guess"):
        reconcile_text(spec.anchor + spec.anchor, spec)


def test_write_validates_both_ledgers_before_touching_either(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    status = tmp_path / "STATUS.md"
    backlog.write_text(f"before\n{SPECS[0].anchor}after\n", encoding="utf-8")
    status.write_text("missing status anchor\n", encoding="utf-8")
    original = backlog.read_bytes()

    with pytest.raises(ReconciliationError, match="STATUS.md: expected one stable anchor"):
        run(tmp_path, write=True)

    assert backlog.read_bytes() == original


def test_run_writes_atomically_preserves_modes_and_then_checks(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    status = tmp_path / "STATUS.md"
    backlog.write_text(f"before\n{SPECS[0].anchor}after\n", encoding="utf-8")
    status.write_text(f"before\n{SPECS[1].anchor}after\n", encoding="utf-8")
    backlog.chmod(0o640)
    status.chmod(0o600)

    messages = run(tmp_path, write=True)

    assert messages[-1] == "updated 2 ledger(s) without rewriting existing history"
    assert stat.S_IMODE(backlog.stat().st_mode) == 0o640
    assert stat.S_IMODE(status.stat().st_mode) == 0o600
    assert BACKLOG_BLOCK in backlog.read_text(encoding="utf-8")
    assert STATUS_BLOCK in status.read_text(encoding="utf-8")

    checked = run(tmp_path, write=False)
    assert checked[-1] == "repository ledgers already reconciled; no files changed"


def test_check_mode_reports_unreconciled_ledgers_without_writes(tmp_path: Path) -> None:
    for spec in SPECS:
        (tmp_path / spec.path).write_text(
            f"before\n{spec.anchor}after\n",
            encoding="utf-8",
        )
    before = {spec.path: (tmp_path / spec.path).read_bytes() for spec in SPECS}

    with pytest.raises(ReconciliationError, match="run with --write in a dedicated branch"):
        run(tmp_path, write=False)

    after = {spec.path: (tmp_path / spec.path).read_bytes() for spec in SPECS}
    assert after == before
