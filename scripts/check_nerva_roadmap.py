#!/usr/bin/env python3
"""Validate the Nerva ORIZONT-to-epic reconciliation after E0 closure.

This checker deliberately avoids runtime imports. It verifies planning integrity only: all legacy
horizons remain mapped, the first executable slices retain bounded authority, the E0 blocker is gone,
Episodes still waits for Atlas, reuse evidence exists, and the Markdown agrees with the JSON companion.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs" / "nerva2" / "ROADMAP_RECONCILIATION.json"
DOCUMENT = REPO / "docs" / "nerva2" / "ROADMAP_RECONCILIATION.md"

EXPECTED_HORIZONS = [f"O{number}" for number in range(27, 34)]
EXPECTED_SLICES = {
    "E1": {"issue": 780, "blocked_by": [], "authority": "shadow_no_action"},
    "E2": {"issue": 781, "blocked_by": [], "authority": "read_only_state"},
    "E3": {"issue": 782, "blocked_by": [781], "authority": "memory_record_only"},
    "E8": {"issue": 783, "blocked_by": [], "authority": "description_only"},
    "E9": {"issue": 784, "blocked_by": [], "authority": "evaluation_only"},
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
        errors.append("the historical ownership-map slice must remain E0.3b1")
    if data.get("status") != "done":
        errors.append("roadmap reconciliation must record E0 DONE")
    if data.get("snapshot_commit") != "0c7f880dea1fe254d590ce8967e45cfe453dc52f":
        errors.append("roadmap snapshot must use the accepted #789 merge")

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

    if by_epic.get("E3", {}).get("blocked_by") != [781]:
        errors.append("E3 must remain blocked only by the minimum Atlas slice")
    for epic in ("E1", "E2", "E8", "E9"):
        if by_epic.get(epic, {}).get("blocked_by") != []:
            errors.append(f"{epic} must be unblocked after E0 closure")
    if any(758 in item.get("blocked_by", []) for item in slices):
        errors.append("no first-wave slice may retain the closed E0 blocker")

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

    if data.get("remaining_e0_work") != []:
        errors.append("remaining_e0_work must be empty after E0 closure")
    if not data.get("post_e0_work"):
        errors.append("post_e0_work must keep broader program gaps explicit")

    required = (
        "E0 is `DONE`",
        "does not claim that legacy ORIZONT completion equals Nerva runtime or release completion",
        "#780, #781, #783 and #784 may proceed",
        "#782 still waits for #781",
        "Ultron as the sole privileged-action authority",
        "E1.0 / E2.0 / E8.0 / E9.0",
    )
    for phrase in required:
        if phrase not in text:
            errors.append(f"Markdown missing post-E0 invariant: {phrase}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Nerva roadmap reconciliation is internally consistent: "
        "7 horizons, 4 unblocked first slices, E3 still waits for Atlas, E0 DONE."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
