#!/usr/bin/env python3
"""Validate the Nerva E0.3b ORIZONT-to-epic reconciliation.

This checker deliberately avoids runtime imports. It verifies planning integrity only:
all legacy horizons remain mapped, first executable slices are bounded and dependency-safe,
reuse evidence exists, and the human-readable document agrees with the JSON companion.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs" / "nerva2" / "ROADMAP_RECONCILIATION.json"
DOCUMENT = REPO / "docs" / "nerva2" / "ROADMAP_RECONCILIATION.md"

EXPECTED_HORIZONS = [f"O{number}" for number in range(27, 34)]
EXPECTED_SLICES = {
    "E1": {"issue": 780, "blocked_by": [758], "authority": "shadow_no_action"},
    "E2": {"issue": 781, "blocked_by": [758], "authority": "read_only_state"},
    "E3": {"issue": 782, "blocked_by": [758, 781], "authority": "memory_record_only"},
    "E8": {"issue": 783, "blocked_by": [758], "authority": "description_only"},
    "E9": {"issue": 784, "blocked_by": [758], "authority": "evaluation_only"},
}
ALLOWED_DISPOSITIONS = {"integrate", "build_on_existing_boundaries"}
FORBIDDEN_COMPLETION_STATES = {"done", "live", "ga", "closed"}


def validate() -> list[str]:
    errors: list[str] = []
    if not MANIFEST.is_file():
        return [f"missing manifest: {MANIFEST.relative_to(REPO)}"]
    if not DOCUMENT.is_file():
        return [f"missing document: {DOCUMENT.relative_to(REPO)}"]

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    text = DOCUMENT.read_text(encoding="utf-8")

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("program_issue") != 757 or data.get("epic_issue") != 758:
        errors.append("program/epic issue linkage drifted")
    if data.get("slice") != "E0.3b1":
        errors.append("slice must remain E0.3b1 until direct ledger reconciliation lands")
    if data.get("status") != "building":
        errors.append("E0.3b1 must not claim E0 completion")

    horizons = data.get("horizons", [])
    horizon_ids = [item.get("id") for item in horizons]
    if horizon_ids != EXPECTED_HORIZONS:
        errors.append(f"expected horizons {EXPECTED_HORIZONS}, got {horizon_ids}")

    for horizon in horizons:
        horizon_id = horizon.get("id", "<unknown>")
        disposition = horizon.get("disposition")
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(f"{horizon_id}: unsupported disposition {disposition!r}")
        state = str(horizon.get("honest_state", "")).lower()
        if not state or state in FORBIDDEN_COMPLETION_STATES:
            errors.append(f"{horizon_id}: dishonest or missing state {state!r}")
        if not horizon.get("nerva_epics"):
            errors.append(f"{horizon_id}: no Nerva owner epic")
        if not horizon.get("remaining_nerva_value"):
            errors.append(f"{horizon_id}: no remaining Nerva value stated")
        for relative in horizon.get("reuse_paths", []):
            if not (REPO / relative).exists():
                errors.append(f"{horizon_id}: missing reuse evidence {relative}")
        if f"**{horizon_id}" not in text:
            errors.append(f"{horizon_id}: missing from Markdown reconciliation")

    slices = data.get("first_executable_slices", [])
    by_epic = {item.get("epic"): item for item in slices}
    if set(by_epic) != set(EXPECTED_SLICES):
        errors.append(
            f"first slice epics must be {sorted(EXPECTED_SLICES)}, got {sorted(by_epic)}"
        )
    if len(by_epic) != len(slices):
        errors.append("duplicate first executable epic")

    for epic, expected in EXPECTED_SLICES.items():
        actual = by_epic.get(epic, {})
        for field, value in expected.items():
            if actual.get(field) != value:
                errors.append(f"{epic}: expected {field}={value!r}, got {actual.get(field)!r}")
        issue = expected["issue"]
        if f"**#{issue}**" not in text:
            errors.append(f"{epic}: issue #{issue} missing from Markdown table")

    # The first wave must not skip the Atlas prerequisite for Episodes.
    if by_epic.get("E3", {}).get("blocked_by") != [758, 781]:
        errors.append("E3 must remain blocked by E0 and the minimum Atlas slice")
    for epic in ("E1", "E2", "E8", "E9"):
        if by_epic.get(epic, {}).get("blocked_by") != [758]:
            errors.append(f"{epic} must remain blocked only by the E0 gate in this plan")

    source_artifacts = data.get("source_artifacts", {})
    for key in (
        "product_destination",
        "delivery_roadmap",
        "implementation_snapshot",
        "dependency_contract",
        "risk_contract",
    ):
        relative = source_artifacts.get(key)
        if not relative or not (REPO / relative).is_file():
            errors.append(f"missing canonical source artifact for {key}: {relative!r}")

    remaining = data.get("remaining_e0_work", [])
    if not remaining:
        errors.append("remaining_e0_work must stay explicit")
    if "does not close E0" not in text:
        errors.append("Markdown must state that this slice does not close E0")
    if "E0.3b2 — direct ledger reconciliation" not in text:
        errors.append("next bounded slice is missing or drifted")
    if "Ultron as the sole privileged-action authority" not in text:
        errors.append("Ultron authority invariant missing from reconciliation")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Nerva roadmap reconciliation is internally consistent: "
        "7 horizons, 5 bounded first slices, E0 still building."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
