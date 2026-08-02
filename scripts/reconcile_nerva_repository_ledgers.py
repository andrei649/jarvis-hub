#!/usr/bin/env python3
"""Apply or verify the bounded Nerva E0 blocks in BACKLOG.md and STATUS.md.

This migrator exists because both ledgers contain long-lived delivery history that must not be
reconstructed or reformatted to add the current Nerva program state. It inserts one exact,
marker-bounded block at a unique stable anchor and otherwise preserves the input bytes.

The script does not close E0. The inserted truth keeps E0 VERIFYING, close_e0=false and the first
implementation wave blocked pending independent integration review.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

START = "<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->"
END = "<!-- NERVA2:E0-REPOSITORY-LEDGER:END -->"

BACKLOG_BLOCK = """<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->
## Nerva 2.0 program control — E0 VERIFYING

> Canonical program: [#757](https://github.com/andrei649/jarvis-hub/issues/757) · E0 epic:
> [#758](https://github.com/andrei649/jarvis-hub/issues/758) · blocker plan:
> [#778](https://github.com/andrei649/jarvis-hub/issues/778) · machine-readable completion ledger:
> [`docs/nerva2/E0_COMPLETION.json`](docs/nerva2/E0_COMPLETION.json).

- Accepted E0 control evidence: #771, #772, #779, #785, #786, #787 and #788.
- E0 remains **VERIFYING** with `close_e0=false`; this block is program truth, not an implementation
  claim and not an E0 closure decision.
- First executable slices #780 (Cortex), #781 (Atlas), #783 (Synapse) and #784 (Research Lab) remain
  blocked by #758. #782 (Episodes) remains blocked by #758 and the minimum Atlas slice #781.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority. Cortex is shadow/no-action,
  Atlas is read-only to consumers, Episodes is memory-record-only, Synapse is description-only and
  Research Lab is evaluation-only in the first wave.
- The historical ORIZONT delivery record below remains intact. Nerva completion is earned only by
  reviewed repository/issue agreement, green generated-status and integrity checks, exact-head CI,
  and a separate independent integrator decision.
<!-- NERVA2:E0-REPOSITORY-LEDGER:END -->

"""

STATUS_BLOCK = """<!-- NERVA2:E0-REPOSITORY-LEDGER:START -->
## Nerva 2.0 verification snapshot — 2026-08-02

- **Program state:** E0 is `VERIFYING`; `close_e0=false`.
- **Accepted controls:** #771, #772, #779, #785, #786, #787 and #788.
- **Blocked first wave:** #780, #781, #783 and #784 wait for #758; #782 waits for #758 and #781.
- **Authority ceiling:** Ultron / `nerva.action.v1` is the sole privileged-action authority. The first
  Cortex, Atlas, Episodes, Synapse and Research Lab slices do not gain action authority.
- **Truth boundary:** the issues and control artifacts are plans and verification evidence, not proof
  that first-wave runtime capabilities are implemented. The ORIZONT history below is preserved.
- **Closure gate:** `scripts/status_sync.py --check`, both Nerva integrity checkers, all required CI and
  a separate independent review must pass before E0 can be marked complete or downstream work starts.

Canonical evidence: [#757](https://github.com/andrei649/jarvis-hub/issues/757),
[#758](https://github.com/andrei649/jarvis-hub/issues/758),
[#778](https://github.com/andrei649/jarvis-hub/issues/778),
[`docs/nerva2/E0_COMPLETION.md`](docs/nerva2/E0_COMPLETION.md).
<!-- NERVA2:E0-REPOSITORY-LEDGER:END -->

"""


@dataclass(frozen=True)
class LedgerSpec:
    path: str
    anchor: str
    block: str


SPECS = (
    LedgerSpec(
        path="BACKLOG.md",
        anchor="**S = story points (1 = ~jumătate de zi) · P = prioritate (P0–P3)**\n",
        block=BACKLOG_BLOCK,
    ),
    LedgerSpec(
        path="STATUS.md",
        anchor="---\n\n## ORIZONT 26 Update — 2026-07-04\n",
        block=STATUS_BLOCK,
    ),
)


class ReconciliationError(RuntimeError):
    """Raised when a ledger cannot be changed without ambiguity or history risk."""


def _decode(raw: bytes, relative_path: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReconciliationError(f"{relative_path}: expected UTF-8 input: {exc}") from exc


def _with_line_ending(value: str, line_ending: str) -> str:
    return value if line_ending == "\n" else value.replace("\n", line_ending)


def _existing_block_line_ending(text: str, start: int, path: str) -> str:
    after_start = start + len(START)
    if text.startswith("\r\n", after_start):
        return "\r\n"
    if text.startswith("\n", after_start):
        return "\n"
    raise ReconciliationError(f"{path}: marker is not followed by a supported line ending")


def _find_anchor(text: str, spec: LedgerSpec) -> tuple[str, str]:
    candidates = (
        (spec.anchor, "\n"),
        (_with_line_ending(spec.anchor, "\r\n"), "\r\n"),
    )
    matches = [(anchor, ending) for anchor, ending in candidates if text.count(anchor)]
    count = sum(text.count(anchor) for anchor, _ in candidates)
    if count != 1 or len(matches) != 1:
        raise ReconciliationError(
            f"{spec.path}: expected one stable anchor, found {count}; refusing to guess"
        )
    return matches[0]


def reconcile_text(text: str, spec: LedgerSpec) -> tuple[str, bool]:
    """Return the exact reconciled text and whether a write is required."""

    starts = text.count(START)
    ends = text.count(END)
    if starts != ends:
        raise ReconciliationError(
            f"{spec.path}: partial Nerva marker pair (start={starts}, end={ends})"
        )
    if starts > 1:
        raise ReconciliationError(f"{spec.path}: duplicate Nerva ledger blocks")

    if starts == 1:
        start = text.index(START)
        end = text.index(END, start) + len(END)
        line_ending = _existing_block_line_ending(text, start, spec.path)
        existing = text[start:end]
        expected = _with_line_ending(spec.block, line_ending).rstrip("\r\n")
        if existing != expected:
            raise ReconciliationError(
                f"{spec.path}: marker-bounded block exists but differs from canonical content"
            )
        return text, False

    anchor, line_ending = _find_anchor(text, spec)
    block = _with_line_ending(spec.block, line_ending)
    reconciled = text.replace(anchor, block + anchor, 1)
    if reconciled.replace(block, "", 1) != text:
        raise ReconciliationError(f"{spec.path}: preservation invariant failed")
    return reconciled, True


def reconcile_bytes(raw: bytes, spec: LedgerSpec) -> tuple[bytes, bool]:
    text = _decode(raw, spec.path)
    reconciled, changed = reconcile_text(text, spec)
    return reconciled.encode("utf-8"), changed


def _atomic_write(path: Path, content: bytes) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def run(root: Path, *, write: bool) -> list[str]:
    messages: list[str] = []
    pending: list[tuple[Path, bytes]] = []

    for spec in SPECS:
        path = root / spec.path
        if not path.is_file():
            raise ReconciliationError(f"{spec.path}: file is missing")
        raw = path.read_bytes()
        reconciled, changed = reconcile_bytes(raw, spec)
        if changed:
            pending.append((path, reconciled))
            messages.append(f"{spec.path}: reconciliation required")
        else:
            messages.append(f"{spec.path}: canonical block present")

    if pending and not write:
        raise ReconciliationError(
            "repository ledgers are not reconciled; run with --write in a dedicated branch"
        )

    for path, content in pending:
        _atomic_write(path, content)

    if pending:
        messages.append(f"updated {len(pending)} ledger(s) without rewriting existing history")
    else:
        messages.append("repository ledgers already reconciled; no files changed")
    return messages


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if either canonical block is absent",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="insert missing canonical blocks atomically",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: parent of scripts/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        messages = run(args.root.resolve(), write=args.write)
    except ReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
