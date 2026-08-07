import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from check_nerva_issue_movement import (
    LEGACY_BASE,
    MARKER,
    MovementError,
    classify,
    parse_diff,
    parse_marker_json,
    strict_json,
    validate_manifest_gate,
    validate_registry_evolution,
)


def test_missing_gate_allowed_only_legacy():
    validate_manifest_gate({}, LEGACY_BASE)
    with pytest.raises(MovementError):
        validate_manifest_gate({}, "e596920ec60f19d2e7f0937819c892746a1c42b2")


def test_duplicate_json_rejected():
    with pytest.raises(MovementError):
        strict_json('{"a":1,"a":2}')


@pytest.mark.parametrize(
    "raw",
    [
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":"line\\u0001break"}',
        "[" * 33 + "0" + "]" * 33,
    ],
)
def test_strict_json_rejects_hostile_scalars_and_depth(raw):
    with pytest.raises(MovementError):
        strict_json(raw, max_depth=32)


def test_diff_requires_complete_nul_records():
    assert parse_diff(b"M\tBACKLOG.md\0") == [("M", "BACKLOG.md")]
    with pytest.raises(MovementError):
        parse_diff(b"M\tBACKLOG.md")


@pytest.mark.parametrize(
    "raw",
    [
        b"R100\told\tnew\0",
        b"M\t../BACKLOG.md\0",
        b"M\tC:\\repo\\BACKLOG.md\0",
        b"M\t/absolute/path\0",
        b"M\tbad\x01path\0",
        b"M\tbad\xffpath\0",
    ],
)
def test_diff_rejects_ambiguous_or_unsafe_records_before_classification(raw):
    with pytest.raises(MovementError):
        parse_diff(raw)


def test_marker_requires_one_complete_bounded_closed_world_json_object():
    end = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
    body = f'prefix\n{MARKER}\n{{"schema_version":1}}\n{end}\nsuffix'
    assert parse_marker_json(body, MARKER, end, allowed_keys={"schema_version"}) == {
        "schema_version": 1
    }
    with pytest.raises(MovementError):
        parse_marker_json(body + MARKER, MARKER, end, allowed_keys={"schema_version"})
    with pytest.raises(MovementError):
        parse_marker_json(
            f'{MARKER}{{"schema_version":1,"extra":false}}{end}',
            MARKER,
            end,
            allowed_keys={"schema_version"},
        )


def test_registry_cannot_remove_or_narrow_coverage_and_new_entries_need_added_path():
    baseline = ["docs/nerva2/", "scripts/check_nerva_issue_movement.py"]
    with pytest.raises(MovementError):
        validate_registry_evolution(baseline, ["docs/nerva2/"], set())
    with pytest.raises(MovementError):
        validate_registry_evolution(baseline, ["docs/nerva2/", "docs/nerva2/private/"], set())
    validate_registry_evolution(
        baseline,
        baseline + ["tests/test_nerva_issue_movement.py"],
        {"tests/test_nerva_issue_movement.py"},
    )


def test_classifier_uses_baseline_candidate_registry_union():
    assert classify(
        "feature/x",
        "",
        ["scripts/check_nerva_issue_movement.py"],
        baseline_registry=["scripts/check_nerva_issue_movement.py"],
        candidate_registry=[],
    )


def test_classifier_is_deterministic():
    assert classify("nerva2/x", "", [])
    assert classify("feature/x", MARKER, [])
    assert not classify("feature/x", "", ["src/app.py"])
