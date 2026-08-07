import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from check_nerva_issue_movement import (
    LEGACY_BASE,
    MARKER,
    MAX_DIFF_BYTES,
    MovementError,
    classify,
    compute_name_status_diff,
    main,
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


def test_strict_json_rejects_float_overflow_and_recursion_error():
    with pytest.raises(MovementError):
        strict_json("1e400")
    with pytest.raises(MovementError):
        strict_json("[" * 2_000 + "0" + "]" * 2_000, max_depth=32)


def test_diff_requires_complete_nul_records():
    assert parse_diff(b"M\0BACKLOG.md\0") == [("M", "BACKLOG.md")]
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


def test_registry_rejects_wildcards_and_unrelated_broad_prefixes():
    with pytest.raises(MovementError):
        validate_registry_evolution([], ["docs/*.md"], {"docs/example.md"})
    with pytest.raises(MovementError):
        validate_registry_evolution([], ["docs/"], {"docs/example.md"})


def test_legacy_bootstrap_requires_exact_pinned_seed_and_real_integer_schema_version():
    gate = {
        "schema_version": 1,
        "enforcement_state": "required",
        "bootstrap_base": LEGACY_BASE,
        "registry": [
            ".github/workflows/ci.yml",
            ".github/workflows/nerva-roadmap.yml",
            "BACKLOG.md",
            "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json",
            "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md",
            "scripts/check_nerva_issue_movement.py",
            "scripts/check_nerva_program_manifest.py",
            "tests/test_nerva_issue_movement.py",
            "tests/test_nerva_program_manifest.py",
        ],
        "program_control_issues": [846],
        "continuous_currentness": False,
        "live_receipt_control": True,
    }
    validate_manifest_gate({"movement_gate": gate}, LEGACY_BASE)
    gate["schema_version"] = True
    with pytest.raises(MovementError):
        validate_manifest_gate({"movement_gate": gate}, LEGACY_BASE)
    gate["schema_version"] = 1
    gate["registry"] = gate["registry"][:-1]
    with pytest.raises(MovementError):
        validate_manifest_gate({"movement_gate": gate}, LEGACY_BASE)


def test_compute_diff_parses_the_real_status_nul_path_nul_git_format(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    path = tmp_path / "tracked.txt"
    path.write_text("one\n", encoding="utf-8")
    subprocess.run([git, "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "first"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    path.write_text("two\n", encoding="utf-8")
    subprocess.run([git, "commit", "-am", "second"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert compute_name_status_diff(base, head, git=git, cwd=tmp_path) == [("M", "tracked.txt")]


def test_compute_diff_rejects_oversized_stream_without_returning_classification():
    class Process:
        returncode = 0

        def __init__(self):
            self.stdout = __import__("io").BytesIO(b"A\0" + b"x" * MAX_DIFF_BYTES)

        def wait(self, timeout):
            return 0

        def kill(self):
            return None

    with pytest.raises(MovementError):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: Process(),
        )


def test_compute_diff_does_not_expose_os_error_text():
    secret = "token-not-for-logs"

    def failing_popen(*_args, **_kwargs):
        raise OSError(secret)

    with pytest.raises(MovementError) as failure:
        compute_name_status_diff("a" * 40, "b" * 40, popen_factory=failing_popen)
    assert secret not in str(failure.value)


def test_cli_rejects_event_that_is_not_bound_to_requested_base_head_and_diff(tmp_path):
    event = tmp_path / "event.json"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    diff = tmp_path / "diff.bin"
    event.write_text(
        '{"pull_request":{"base":{"sha":"'
        + "a" * 40
        + '"},"head":{"ref":"nerva2/x","sha":"'
        + "b" * 40
        + '"}}}',
        encoding="utf-8",
    )
    baseline.write_text("{}", encoding="utf-8")
    candidate.write_text("{}", encoding="utf-8")
    diff.write_bytes(b"M\0BACKLOG.md\0")
    assert (
        main(
            [
                "--event",
                str(event),
                "--baseline-manifest",
                str(baseline),
                "--manifest",
                str(candidate),
                "--base",
                "c" * 40,
                "--head",
                "b" * 40,
                "--diff",
                str(diff),
            ]
        )
        == 1
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
