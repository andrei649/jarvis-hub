from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scripts.reconcile_nerva_repository_ledgers import (
    BACKLOG_BLOCK,
    END,
    PREVIOUS_BACKLOG_BLOCK,
    PREVIOUS_STATUS_BLOCK,
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
def test_reconcile_preserves_every_original_byte_on_insert(spec, line_ending: str) -> None:
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


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.path)
def test_exact_verifying_block_transitions_to_done_without_touching_surroundings(
    spec, line_ending: str
) -> None:
    previous = _with_line_ending(spec.previous_block, line_ending).rstrip("\r\n")
    original = f"prefix{line_ending}{previous}{line_ending}suffix{line_ending}"

    reconciled, changed = reconcile_text(original, spec)

    expected = _with_line_ending(spec.block, line_ending).rstrip("\r\n")
    assert changed is True
    assert reconciled == f"prefix{line_ending}{expected}{line_ending}suffix{line_ending}"


def test_status_transition_does_not_duplicate_history_separator() -> None:
    spec = next(item for item in SPECS if item.path == "STATUS.md")
    original = f"header\n{PREVIOUS_STATUS_BLOCK}{spec.anchor}history\n"

    reconciled, changed = reconcile_text(original, spec)

    assert changed is True
    expected_boundary = f"{END}\n\n---\n\n## ORIZONT 26 Update — 2026-07-04\n"
    assert expected_boundary in reconciled
    assert f"{END}\n\n---\n\n---\n" not in reconciled


@pytest.mark.parametrize(
    "text, message",
    [
        (f"{START}\nunfinished", "partial Nerva marker pair"),
        (
            f"{START}\nunknown intermediate state\n{END}\n",
            "neither the accepted VERIFYING state nor the canonical DONE state",
        ),
        (
            f"{BACKLOG_BLOCK}{BACKLOG_BLOCK}",
            "duplicate Nerva ledger blocks",
        ),
    ],
)
def test_refuses_partial_unknown_or_duplicate_blocks(text: str, message: str) -> None:
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
    backlog.write_text(f"before\n{PREVIOUS_BACKLOG_BLOCK}after\n", encoding="utf-8")
    status.write_text(f"{START}\nunknown\n{END}\n", encoding="utf-8")
    original = backlog.read_bytes()

    with pytest.raises(ReconciliationError, match="STATUS.md: marker-bounded block"):
        run(tmp_path, write=True)

    assert backlog.read_bytes() == original


def test_run_transitions_atomically_preserves_modes_and_then_checks(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    status = tmp_path / "STATUS.md"
    backlog.write_text(f"before\n{PREVIOUS_BACKLOG_BLOCK}after\n", encoding="utf-8")
    status.write_text(f"before\n{PREVIOUS_STATUS_BLOCK}after\n", encoding="utf-8")
    backlog.chmod(0o640)
    status.chmod(0o600)

    messages = run(tmp_path, write=True)

    assert messages[-1] == "updated 2 ledger(s) without rewriting existing history"
    if os.name != "nt":
        assert stat.S_IMODE(backlog.stat().st_mode) == 0o640
        assert stat.S_IMODE(status.stat().st_mode) == 0o600
    assert BACKLOG_BLOCK in backlog.read_text(encoding="utf-8")
    assert STATUS_BLOCK in status.read_text(encoding="utf-8")
    assert PREVIOUS_BACKLOG_BLOCK not in backlog.read_text(encoding="utf-8")
    assert PREVIOUS_STATUS_BLOCK not in status.read_text(encoding="utf-8")

    checked = run(tmp_path, write=False)
    assert checked[-1] == "repository ledgers already record E0 DONE; no files changed"


def test_check_mode_rejects_partial_closure_without_writes(tmp_path: Path) -> None:
    backlog = tmp_path / "BACKLOG.md"
    status = tmp_path / "STATUS.md"
    backlog.write_text(f"before\n{BACKLOG_BLOCK}after\n", encoding="utf-8")
    status.write_text(f"before\n{PREVIOUS_STATUS_BLOCK}after\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in (backlog, status)}

    with pytest.raises(ReconciliationError, match="not in the canonical E0 DONE state"):
        run(tmp_path, write=False)

    after = {path.name: path.read_bytes() for path in (backlog, status)}
    assert after == before
