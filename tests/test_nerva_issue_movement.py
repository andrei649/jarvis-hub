import hashlib
import json
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
    derive_scope,
    main,
    parse_diff,
    parse_marker_json,
    run_pure_proof,
    strict_json,
    validate_manifest_gate,
    validate_registry_evolution,
    validate_stream_evidence_bindings,
)

BASE = LEGACY_BASE
HEAD = "b" * 40
REPOSITORY = "andrei649/jarvis-hub"
PR_NUMBER = 849


def valid_gate():
    return {
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


def candidate_manifest():
    return {"movement_gate": valid_gate()}


def snapshot_proof(*, mutate_receipt=False):
    candidate = candidate_manifest()
    candidate_bytes = json.dumps(candidate, separators=(",", ":")).encode()
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    receipt_fields = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "pull_request": PR_NUMBER,
        "movement_kind": "program_control",
        "implementation_issue": 846,
        "base_sha": BASE,
        "head_sha": HEAD,
        "manifest_sha256": digest,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
    }
    comments = {}
    roles = {}
    for role, issue, comment_id in (
        ("program", 757, 1),
        ("blocker", 778, 2),
        ("implementation", 846, 3),
    ):
        receipt = {**receipt_fields, "role": role, "issue": issue}
        body = (
            "<!-- NERVA2:MOVEMENT-RECEIPT:START -->"
            + json.dumps(receipt, separators=(",", ":"))
            + "<!-- NERVA2:MOVEMENT-RECEIPT:END -->"
        )
        roles[role] = {
            "comment_id": comment_id,
            "comment_body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "updated_at": "2026-08-07T00:00:00Z",
        }
        comments[f"comment:{comment_id}"] = {
            "id": comment_id,
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{issue}",
            "body": body + ("x" if mutate_receipt and role == "program" else ""),
            "user": {"login": "andrei649"},
            "author_association": "OWNER",
            "created_at": "2026-08-07T00:00:00Z",
            "updated_at": "2026-08-07T00:00:00Z",
        }
    attestation = {
        "schema_version": 1,
        "movement_kind": "program_control",
        "repository": REPOSITORY,
        "pull_request": PR_NUMBER,
        "base_sha": BASE,
        "head_sha": HEAD,
        "manifest_sha256": digest,
        "program_issue": 757,
        "blocker_issue": 778,
        "implementation_issue": 846,
        "roles": roles,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
    }
    body = (
        "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
        + json.dumps(attestation, separators=(",", ":"))
        + "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
    )
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": BASE},
            "head": {"sha": HEAD, "ref": "nerva2/b2"},
            "body": body,
            "draft": False,
        },
    }
    current = {**event["pull_request"], "repository": {"full_name": REPOSITORY}, "state": "open"}
    return event, candidate, candidate_bytes, {"pull_request": current, **comments}


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


def test_strict_json_normalizes_huge_integer_parser_failure():
    with pytest.raises(MovementError):
        strict_json("9" * 5_000)


def test_empty_diff_is_a_valid_zero_record_diff():
    assert parse_diff(b"") == []


def test_legacy_baseline_projects_missing_gate_but_candidate_must_materialize_it():
    event, _candidate, _candidate_bytes, _snapshot = snapshot_proof()
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest={},
            candidate_manifest_bytes=b"{}",
            base=BASE,
            head=HEAD,
            diff=b"",
        )


def test_non_draft_nerva_requires_manifest_view_and_injected_snapshot_proof():
    event, candidate, candidate_bytes, _snapshot = snapshot_proof()
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        )


def test_offline_snapshot_proves_attestation_receipt_and_semantic_scope():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    result = run_pure_proof(
        event=event,
        baseline_manifest={},
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        transport=snapshot.__getitem__,
    )
    assert result.status == "proved"
    assert result.scope["implementation_issue"] == 846
    assert derive_scope({}, candidate)["kind"] == "program_control"


def test_offline_snapshot_rejects_edited_receipt_and_cross_binding():
    event, candidate, candidate_bytes, snapshot = snapshot_proof(mutate_receipt=True)
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_semantic_stream_scope_derives_exactly_one_new_referenced_issue():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "references": [{"kind": "issue", "value": 759}],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    assert derive_scope(baseline, candidate) == {
        "kind": "stream",
        "implementation_issue": 900,
        "stream_id": "E1",
        "epic_issue": 759,
    }


def test_legacy_bootstrap_preserves_real_baseline_root_data_except_gate_addition():
    baseline = {"authority": {"can_execute": False}, "streams": []}
    candidate = {**baseline, "movement_gate": valid_gate()}
    assert derive_scope(baseline, candidate)["implementation_issue"] == 846


def test_program_control_rejects_immutable_gate_transition():
    baseline = {"movement_gate": valid_gate()}
    candidate = json.loads(json.dumps(baseline))
    candidate["movement_gate"]["enforcement_state"] = "safety_disabled"
    candidate["movement_gate"]["program_control_issues"].append(900)
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_stream_scope_rejects_history_rewrite_and_building_to_done():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "program_status": "building",
                "references": [{"kind": "issue", "value": 759}],
                "completion_evidence": [{"issue": 700}],
                "delivery_prerequisites": [],
                "blockers": [],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    candidate["streams"][0]["completion_evidence"] = []
    candidate["streams"][0]["program_status"] = "done"
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_current_snapshot_is_fetched_before_non_nerva_classification():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"]["head"]["ref"] = "feature/event-stale"
    calls = []

    def transport(key):
        calls.append(key)
        return snapshot[key]

    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"",
            transport=transport,
        )
    assert calls == ["pull_request"]


def test_legacy_bootstrap_gate_rejects_any_noncanonical_control_state():
    for key, value in (
        ("enforcement_state", "safety_disabled"),
        ("program_control_issues", [999]),
        ("continuous_currentness", True),
        ("live_receipt_control", False),
    ):
        gate = valid_gate()
        gate[key] = value
        with pytest.raises(MovementError):
            validate_manifest_gate({"movement_gate": gate}, LEGACY_BASE)


def test_program_control_rejects_duplicate_or_replayed_issue_append():
    baseline = {"movement_gate": valid_gate()}
    candidate = json.loads(json.dumps(baseline))
    candidate["movement_gate"]["program_control_issues"].append(846)
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_stream_new_evidence_must_bind_current_pull_request():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [{"issue": 900, "pull_request": 123}],
        "delivery_prerequisites": [],
    }
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_snapshot_rejects_boolean_comment_identifier():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    snapshot["comment:1"]["id"] = True
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_draft_without_marker_is_receipt_free_hold_and_marker_proof_is_validated_hold():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"]["draft"] = True
    snapshot["pull_request"]["draft"] = True
    proof = run_pure_proof(
        event=event,
        baseline_manifest={},
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        transport=snapshot.__getitem__,
    )
    assert proof.status == "draft_hold"
    snapshot["pull_request"]["body"] = ""
    proof = run_pure_proof(
        event=event,
        baseline_manifest={},
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"",
        transport=snapshot.__getitem__,
    )
    assert proof.status == "draft_hold"


def test_new_prerequisite_accepted_evidence_must_bind_current_pr():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [],
        "delivery_prerequisites": [
            {"source": "E0", "accepted_evidence": [{"issue": 900, "pull_request": 12}]}
        ],
    }
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_stream_scope_allows_append_only_evidence_on_existing_prerequisite():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "references": [{"kind": "issue", "value": 759}],
                "completion_evidence": [],
                "delivery_prerequisites": [{"source": "E0", "accepted_evidence": []}],
                "blockers": [],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    candidate["streams"][0]["delivery_prerequisites"][0]["accepted_evidence"].append(
        {"issue": 900, "pull_request": 849}
    )
    assert derive_scope(baseline, candidate)["implementation_issue"] == 900


def test_diff_wait_timeout_kills_and_reaps_before_distinct_timeout():
    class Process:
        def __init__(self):
            self.stdout = __import__("io").BytesIO(b"")
            self.killed = False

        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired("git", timeout)
            return 0

        def kill(self):
            self.killed = True

    process = Process()
    with pytest.raises(MovementError, match="diff read timed out"):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: process,
        )
    assert process.killed
