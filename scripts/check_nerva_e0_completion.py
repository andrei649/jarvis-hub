#!/usr/bin/env python3
"""Validate the Nerva E0 verification ledger without claiming E0 is complete.

The checker is repository-only and side-effect free. GitHub issue bodies and CI results remain
external evidence reviewed by the integrator; this gate verifies accepted control slices,
first-wave dependencies, exact repository-ledger blocks, recorded issue-ledger posture and authority
boundaries while E0 is VERIFYING.
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
}
EXPECTED_SLICES = {
    "E1": {"issue": 780, "blocked_by": [758], "authority": "shadow_no_action"},
    "E2": {"issue": 781, "blocked_by": [758], "authority": "read_only_state"},
    "E3": {"issue": 782, "blocked_by": [758, 781], "authority": "memory_record_only"},
    "E8": {"issue": 783, "blocked_by": [758], "authority": "description_only"},
    "E9": {"issue": 784, "blocked_by": [758], "authority": "evaluation_only"},
}
EXPECTED_ISSUE_STATUS = {
    "757": "body_reconciled",
    "758": "body_reconciled",
    "778": "body_reconciled",
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
        errors.append(f"{name}: canonical Nerva repository-ledger block is absent or stale")
    for token in historical_tokens:
        if token not in text:
            errors.append(f"{name}: lost existing Nerva/ORIZONT anchor: {token}")


def validate() -> list[str]:
    errors: list[str] = []
    data = _load_json(MANIFEST, errors)
    roadmap = _load_json(ROADMAP, errors)
    text = _read_text(DOCUMENT, errors)
    final_text = _read_text(FINAL_RECONCILIATION, errors)
    issue_text = _read_text(ISSUE_RECONCILIATION, errors)
    migration_text = _read_text(MIGRATION_DOCUMENT, errors)
    blocker_plan_text = _read_text(BLOCKER_PLAN_RECONCILIATION, errors)

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("program_issue") != 757 or data.get("epic_issue") != 758:
        errors.append("program/epic linkage drifted")
    if data.get("slice") != "E0.3b2b-repository-ledgers":
        errors.append("completion ledger slice must be E0.3b2b-repository-ledgers")
    if data.get("status") != "verifying" or data.get("close_e0") is not False:
        errors.append("completion ledger must keep E0 VERIFYING and close_e0=false")
    if data.get("snapshot_commit") != EXPECTED_CONTROLS["E0.3b2b-issues"]["merge_commit"]:
        errors.append("completion ledger snapshot must be the accepted #788 merge")

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
        issue = expected["issue"]
        if f"**#{issue}**" not in text:
            errors.append(f"{epic}: issue #{issue} missing from completion document")

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

    ledgers = data.get("repository_ledgers", {})
    if set(ledgers) != {"BACKLOG.md", "STATUS.md"}:
        errors.append("repository_ledgers must contain exactly BACKLOG.md and STATUS.md")
    for name in ("BACKLOG.md", "STATUS.md"):
        entry = ledgers.get(name, {})
        if entry.get("state") != "reconciled_in_pr":
            errors.append(f"{name}: must be reconciled_in_pr while #789 awaits integration")
        for field in ("evidence", "historical_truth_preserved", "remaining_gate"):
            if not entry.get(field):
                errors.append(f"{name}: missing {field}")

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
            errors.append(f"issue #{issue}: missing reconciliation evidence")

    if len(data.get("closure_requirements", [])) < 6:
        errors.append("E0 closure requirements are incomplete")
    next_slice = str(data.get("next_slice", ""))
    if not next_slice.startswith("E0.3b2b-independent-closure"):
        errors.append("next slice must be independent E0 closure review")

    required_phrases = (
        "E0 is `VERIFYING`",
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority",
        "No item above is evidence of implementation",
        "`BACKLOG.md` and `STATUS.md` are reconciled in draft #789",
        "The #778 body is reconciled",
        "E0.3b2b-independent-closure",
    )
    for phrase in required_phrases:
        if phrase not in text:
            errors.append(f"completion document missing invariant: {phrase}")

    final_required = (
        "Status: **VERIFYING**",
        "E0.3b2b-issues",
        "#788",
        "`BACKLOG.md` and `STATUS.md` contain",
        "#778 body is reconciled",
        "#780",
        "#781",
        "#782",
        "#783",
        "#784",
        "Ultron / `nerva.action.v1` remains the sole privileged-action authority",
        "scripts/status_sync.py --check",
        "E0.3b2b-independent-closure",
    )
    for phrase in final_required:
        if phrase not in final_text:
            errors.append(f"final reconciliation brief missing invariant: {phrase}")

    issue_required = (
        "Status:** E0 remains `VERIFYING`",
        "#757",
        "#758",
        "#778",
        "| #778 | body reconciled |",
        "reconciled in draft #789",
        "E0.3b2b-independent-closure",
    )
    for phrase in issue_required:
        if phrase not in issue_text:
            errors.append(f"issue reconciliation document missing invariant: {phrase}")

    migration_required = (
        "Applied state",
        "draft #789",
        "scripts/status_sync.py --check",
        "E0_778_BODY_RECONCILIATION.md",
        "E0.3b2b-independent-closure",
    )
    for phrase in migration_required:
        if phrase not in migration_text:
            errors.append(f"repository-ledger migration document missing invariant: {phrase}")

    blocker_plan_required = (
        "Status:** E0 remains `VERIFYING`",
        "B0 is resolved",
        "B1 / M0 remain `VERIFYING`",
        "B2 is partial",
        "B3–B10 remain open",
        "Ultron / `nerva.action.v1` is the sole privileged-action authority",
        "E0.3b2b-independent-closure",
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
        "Nerva E0 verification ledger is consistent: 7 accepted control slices, "
        "2 exact repository blocks, 3 reconciled issue bodies, 5 blocked first slices, "
        "E0 still VERIFYING pending independent closure."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
