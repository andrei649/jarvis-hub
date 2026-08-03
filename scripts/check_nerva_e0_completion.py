#!/usr/bin/env python3
"""Validate the closed Nerva E0 planning/control ledger.

The checker is repository-only and side-effect free. It validates accepted evidence, post-E0
first-wave dependencies, exact repository-ledger blocks, issue-ledger target posture and authority
boundaries. GitHub issue state and CI results remain external evidence for the independent integrator.
"""

from __future__ import annotations

import json
from pathlib import Path

from reconcile_nerva_repository_ledgers import BACKLOG_BLOCK, END, START, STATUS_BLOCK

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs" / "nerva2" / "E0_COMPLETION.json"
DOCUMENT = REPO / "docs" / "nerva2" / "E0_COMPLETION.md"
FINAL_RECONCILIATION = REPO / "docs" / "nerva2" / "E0_FINAL_RECONCILIATION.md"
ISSUE_RECONCILIATION = REPO / "docs" / "nerva2" / "ISSUE_LEDGER_RECONCILIATION.md"
MIGRATION_DOCUMENT = REPO / "docs" / "nerva2" / "E0_REPOSITORY_LEDGER_MIGRATION.md"
BLOCKER_PLAN_RECONCILIATION = REPO / "docs" / "nerva2" / "E0_778_BODY_RECONCILIATION.md"
ROADMAP = REPO / "docs" / "nerva2" / "ROADMAP_RECONCILIATION.json"
BACKLOG = REPO / "BACKLOG.md"
STATUS = REPO / "STATUS.md"

EXPECTED_CONTROLS = {
    "E0.1": {
        "pull_request": 771,
        "merge_commit": "288412086439e5a02c08fcf8e575944c9b81f96c",
    },
    "E0.2": {
        "pull_request": 772,
        "merge_commit": "8b8e64d599262f15334ce547b7adfa3c042a7a78",
    },
    "E0.3a": {
        "pull_request": 779,
        "merge_commit": "ab177c5501eeea379b66d9d33a1ed895a322e934",
    },
    "E0.3b1": {
        "pull_request": 785,
        "merge_commit": "a943514050a361cbd909761f05c7d9731e0f323e",
    },
    "E0.3b2a": {
        "pull_request": 786,
        "merge_commit": "265a1c984822b059bfbf9449dacc2bde7554d225",
    },
    "E0.3b2b-control": {
        "pull_request": 787,
        "merge_commit": "25eac3688830750be231c43ebacce889427c50cc",
    },
    "E0.3b2b-issues": {
        "pull_request": 788,
        "merge_commit": "13290b6a10f2bfce5b10a3bf57305777341c0909",
    },
    "E0.3b2b-repository-ledgers": {
        "pull_request": 789,
        "merge_commit": "0c7f880dea1fe254d590ce8967e45cfe453dc52f",
    },
}
EXPECTED_SLICES = {
    "E1": {"issue": 780, "blocked_by": [], "authority": "shadow_no_action"},
    "E2": {"issue": 781, "blocked_by": [], "authority": "read_only_state"},
    "E3": {"issue": 782, "blocked_by": [781], "authority": "memory_record_only"},
    "E8": {"issue": 783, "blocked_by": [], "authority": "description_only"},
    "E9": {"issue": 784, "blocked_by": [], "authority": "evaluation_only"},
}
EXPECTED_ISSUE_STATUS = {
    "757": "e0_done",
    "758": "e0_done",
    "778": "e0_done",
}


def _load_json(path: Path, errors: list[str]) -> dict:
    if not path.is_file():
        errors.append(f"missing file: {path.relative_to(REPO)}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path.relative_to(REPO)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected object: {path.relative_to(REPO)}")
        return {}
    return value


def _read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"missing file: {path.relative_to(REPO)}")
        return ""
    return path.read_text(encoding="utf-8")


def _validate_exact_block(
    *, name: str, text: str, expected_block: str, historical_tokens: tuple[str, ...], errors: list[str]
) -> None:
    if text.count(START) != 1 or text.count(END) != 1:
        errors.append(f"{name}: expected exactly one complete Nerva repository-ledger block")
    if expected_block not in text:
        errors.append(f"{name}: canonical Nerva E0 DONE block is absent or stale")
    for token in historical_tokens:
        if token not in text:
            errors.append(f"{name}: lost existing Nerva/ORIZONT anchor: {token}")


def validate_state(data: dict, errors: list[str]) -> None:
    """Validate the machine-readable closure state, including partial-closure rejection."""

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("program_issue") != 757 or data.get("epic_issue") != 758:
        errors.append("program/epic linkage drifted")
    if data.get("slice") != "E0.3b2c-closure-state-transition":
        errors.append("completion ledger slice must be E0.3b2c-closure-state-transition")
    if data.get("status") != "done" or data.get("close_e0") is not True:
        errors.append("completion ledger must set status=done and close_e0=true together")
    if data.get("snapshot_commit") != EXPECTED_CONTROLS["E0.3b2b-repository-ledgers"][
        "merge_commit"
    ]:
        errors.append("completion ledger snapshot must be the accepted #789 merge")

    controls = data.get("accepted_control_slices", [])
    by_slice = {item.get("slice"): item for item in controls if isinstance(item, dict)}
    if set(by_slice) != set(EXPECTED_CONTROLS) or len(by_slice) != len(controls):
        errors.append("accepted control slice set is missing, duplicated or expanded")
    for slice_id, expected in EXPECTED_CONTROLS.items():
        actual = by_slice.get(slice_id, {})
        for key, value in expected.items():
            if actual.get(key) != value:
                errors.append(f"{slice_id}: expected {key}={value!r}, got {actual.get(key)!r}")
        artifacts = actual.get("artifacts", [])
        if not artifacts:
            errors.append(f"{slice_id}: no accepted artifacts")
        for relative in artifacts:
            if not isinstance(relative, str) or not (REPO / relative).is_file():
                errors.append(f"{slice_id}: missing accepted artifact {relative!r}")

    slices = data.get("first_executable_slices", [])
    by_epic = {item.get("epic"): item for item in slices if isinstance(item, dict)}
    if set(by_epic) != set(EXPECTED_SLICES) or len(by_epic) != len(slices):
        errors.append("first executable slice set drifted")
    for epic, expected in EXPECTED_SLICES.items():
        actual = by_epic.get(epic, {})
        for key, value in expected.items():
            if actual.get(key) != value:
                errors.append(f"{epic}: expected {key}={value!r}, got {actual.get(key)!r}")
    if any(758 in item.get("blocked_by", []) for item in slices if isinstance(item, dict)):
        errors.append("partial closure: a first-wave slice still retains #758 as a blocker")
    if by_epic.get("E3", {}).get("blocked_by") != [781]:
        errors.append("E3 must remain blocked only by #781 after E0 closure")

    ledgers = data.get("repository_ledgers", {})
    if set(ledgers) != {"BACKLOG.md", "STATUS.md"}:
        errors.append("repository_ledgers must contain exactly BACKLOG.md and STATUS.md")
    for name in ("BACKLOG.md", "STATUS.md"):
        entry = ledgers.get(name, {})
        if entry.get("state") != "e0_done":
            errors.append(f"{name}: state must be e0_done")
        for field in ("evidence", "historical_truth_preserved", "remaining_gate"):
            if not entry.get(field):
                errors.append(f"{name}: missing {field}")

    if data.get("issue_ledgers") != [757, 758, 778]:
        errors.append("issue ledger set must remain #757, #758 and #778")
    issue_status = data.get("issue_ledger_status", {})
    if set(issue_status) != set(EXPECTED_ISSUE_STATUS):
        errors.append("issue_ledger_status must contain exactly #757, #758 and #778")
    for issue, expected_state in EXPECTED_ISSUE_STATUS.items():
        entry = issue_status.get(issue, {})
        if entry.get("state") != expected_state:
            errors.append(
                f"issue #{issue}: expected state {expected_state!r}, got {entry.get('state')!r}"
            )
        if not entry.get("evidence"):
            errors.append(f"issue #{issue}: missing closure evidence")

    if len(data.get("closure_invariants", [])) < 8:
        errors.append("E0 closure invariants are incomplete")
    if not data.get("post_e0_open_work"):
        errors.append("post-E0 open work must remain explicit")
    next_slice = str(data.get("next_slice", ""))
    if not next_slice.startswith("E1.0 / E2.0 / E8.0 / E9.0"):
        errors.append("next slice must name the bounded post-E0 parallel wave")


def validate() -> list[str]:
    errors: list[str] = []
    data = _load_json(MANIFEST, errors)
    roadmap = _load_json(ROADMAP, errors)
    text = _read_text(DOCUMENT, errors)
    final_text = _read_text(FINAL_RECONCILIATION, errors)
    issue_text = _read_text(ISSUE_RECONCILIATION, errors)
    migration_text = _read_text(MIGRATION_DOCUMENT, errors)
    blocker_plan_text = _read_text(BLOCKER_PLAN_RECONCILIATION, errors)

    validate_state(data, errors)

    slices = data.get("first_executable_slices", [])
    for item in slices:
        if isinstance(item, dict) and f"**#{item.get('issue')}**" not in text:
            errors.append(f"{item.get('epic')}: issue #{item.get('issue')} missing from completion document")

    roadmap_slices = {
        item.get("epic"): {
            "issue": item.get("issue"),
            "blocked_by": item.get("blocked_by"),
            "authority": item.get("authority"),
        }
        for item in roadmap.get("first_executable_slices", [])
        if isinstance(item, dict)
    }
    if roadmap_slices != EXPECTED_SLICES:
        errors.append("completion ledger and accepted roadmap first slices disagree")
    if roadmap.get("status") != "done":
        errors.append("roadmap reconciliation must record E0 DONE")

    backlog = _read_text(BACKLOG, errors)
    status = _read_text(STATUS, errors)
    if backlog:
        _validate_exact_block(
            name="BACKLOG.md",
            text=backlog,
            expected_block=BACKLOG_BLOCK,
            historical_tokens=("NERVA_VISION.md", "ORIZONT 27", "ORIZONT 33"),
            errors=errors,
        )
    if status:
        _validate_exact_block(
            name="STATUS.md",
            text=status,
            expected_block=STATUS_BLOCK,
            historical_tokens=("NERVA_VISION.md", "ORIZONT 27–33"),
            errors=errors,
        )

    required_phrases = (
        "E0 is `DONE`",
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority",
        "No item above is evidence of implementation",
        "#780, #781, #783 and #784 may proceed",
        "#782 still waits for #781",
        "E1.0 / E2.0 / E8.0 / E9.0",
    )
    for phrase in required_phrases:
        if phrase not in text:
            errors.append(f"completion document missing invariant: {phrase}")

    final_required = (
        "Status: **DONE**",
        "E0.3b2b-repository-ledgers",
        "#789",
        "#780, #781, #783 and #784 may proceed",
        "#782 still waits for #781",
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority",
        "scripts/status_sync.py --check",
        "E1.0 / E2.0 / E8.0 / E9.0",
    )
    for phrase in final_required:
        if phrase not in final_text:
            errors.append(f"final reconciliation brief missing invariant: {phrase}")

    issue_required = (
        "Status:** E0 is `DONE`",
        "#757",
        "#758",
        "#778",
        "| #778 | E0 done |",
        "| `BACKLOG.md` | E0 done |",
        "| `STATUS.md` | E0 done |",
        "#782 still waits for #781",
    )
    for phrase in issue_required:
        if phrase not in issue_text:
            errors.append(f"issue reconciliation document missing invariant: {phrase}")

    migration_required = (
        "Closure transition",
        "accepted VERIFYING block",
        "canonical E0 DONE block",
        "scripts/status_sync.py --check",
        "partial closure",
    )
    for phrase in migration_required:
        if phrase not in migration_text:
            errors.append(f"repository-ledger migration document missing invariant: {phrase}")

    blocker_plan_required = (
        "Status:** E0 is `DONE`",
        "B0 and B1 are resolved",
        "M0 is complete",
        "B2 is partial",
        "B3–B10 remain open",
        "Ultron / `nerva.action.v1` is the sole privileged-action authority",
        "#782 still waits for #781",
    )
    for phrase in blocker_plan_required:
        if phrase not in blocker_plan_text:
            errors.append(f"#778 reconciliation evidence missing invariant: {phrase}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Nerva E0 closure ledger is consistent: 8 accepted control slices, "
        "2 exact E0 DONE repository blocks, 3 E0-done issue targets, "
        "4 E0-unblocked first slices, E3 still waiting for Atlas."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
