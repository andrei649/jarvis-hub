import hashlib
import json
import os
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
    PureProof,
    _fetch_current_snapshot,
    _git_environment,
    _resolve_git_executable,
    _validate_attestation,
    _validate_receipt,
    classify,
    compute_name_status_diff,
    derive_scope,
    main,
    parse_diff,
    parse_marker_json,
    run_pure_proof,
    run_repository_proof,
    strict_json,
    validate_manifest_gate,
    validate_registry_evolution,
    validate_stream_evidence_bindings,
)

BASE = LEGACY_BASE
HEAD = "b" * 40
REPOSITORY = "andrei649/jarvis-hub"
PR_NUMBER = 849


def binding_repository(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    manifest = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"version":1}\n')
    document.write_bytes(b"# version 1\n")
    subprocess.run([git, "add", "docs"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest.write_bytes(b'{"version":2}\n')
    document.write_bytes(b"# version 2\n")
    subprocess.run(
        [git, "commit", "-am", "candidate"], cwd=tmp_path, check=True, capture_output=True
    )
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base},
            "head": {"sha": head, "ref": "nerva2/binding"},
            "body": "",
            "draft": False,
        },
    }
    return git, base, head, event


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


def test_attestation_digest_binds_exact_candidate_manifest_bytes():
    event, candidate, _candidate_bytes, snapshot = snapshot_proof()
    semantically_equal_bytes = json.dumps(candidate, indent=2).encode()
    with pytest.raises(MovementError, match="attestation does not bind movement proof"):
        run_pure_proof(
            event=event,
            baseline_manifest={},
            candidate_manifest=candidate,
            candidate_manifest_bytes=semantically_equal_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


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


def test_numeric_cross_bindings_reject_boolean_aliases():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    scope = derive_scope({}, candidate)
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    current = json.loads(json.dumps(snapshot["pull_request"]))
    current["number"] = True
    with pytest.raises(MovementError):
        _fetch_current_snapshot(
            lambda _key: current,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
        )
    attestation_body = snapshot["pull_request"]["body"].replace(
        '"pull_request":849', '"pull_request":true'
    )
    with pytest.raises(MovementError):
        _validate_attestation(
            attestation_body,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
            digest=digest,
            scope=scope,
        )
    receipt_envelope = json.loads(json.dumps(snapshot["comment:1"]))
    receipt_envelope["body"] = receipt_envelope["body"].replace(
        '"pull_request":849', '"pull_request":true'
    )
    comment = dict(
        json.loads(json.dumps(snapshot["pull_request"]))["body"]
        and {"comment_id": 1, "updated_at": "2026-08-07T00:00:00Z"}
    )
    comment["comment_body_sha256"] = hashlib.sha256(receipt_envelope["body"].encode()).hexdigest()
    with pytest.raises(MovementError):
        _validate_receipt(
            receipt_envelope,
            role="program",
            issue=757,
            comment=comment,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
            digest=digest,
            scope=scope,
        )


def test_blocked_reader_reports_timeout_even_if_kill_unblocks_eof():
    released = __import__("threading").Event()

    class BlockingStream:
        def read(self, _size):
            released.wait()
            return b""

    class Process:
        def __init__(self):
            self.stdout = BlockingStream()
            self.killed = False
            self.waits = 0

        def kill(self):
            self.killed = True
            released.set()

        def wait(self, timeout):
            del timeout
            self.waits += 1
            return 0

    process = Process()
    with pytest.raises(MovementError, match="diff read timed out"):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: process,
            timeout_seconds=0.01,
        )
    assert process.killed and process.waits == 1


@pytest.mark.parametrize(
    "field,value", [("issue", True), ("issue", 0), ("pull_request", True), ("pull_request", 0)]
)
@pytest.mark.parametrize("kind", ["completion", "accepted"])
def test_new_evidence_requires_positive_real_issue_and_pull_request(field, value, kind):
    record = {"issue": 900, "pull_request": 849}
    record[field] = value
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = (
        {"completion_evidence": [record], "delivery_prerequisites": []}
        if kind == "completion"
        else {
            "completion_evidence": [],
            "delivery_prerequisites": [{"source": "E0", "accepted_evidence": [record]}],
        }
    )
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_new_evidence_accepts_legitimate_positive_issue_reference():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [{"issue": 900, "pull_request": 849}],
        "delivery_prerequisites": [
            {"source": "E0", "accepted_evidence": [{"issue": 900, "pull_request": 849}]}
        ],
    }
    validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_git_resolution_is_absolute_and_subprocess_environment_drops_secrets(tmp_path):
    git = _resolve_git_executable(tmp_path)
    assert Path(git).is_absolute()
    environment = _git_environment(
        git,
        {
            "PATH": os.environ.get("PATH", ""),
            "Path": "C:\\untrusted-path",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GITHUB_TOKEN": "github-secret",
            "GH_TOKEN": "gh-secret",
            "HTTP_PROXY": "http://proxy.invalid",
            "https_proxy": "http://proxy.invalid",
            "NO_PROXY": "github.com",
            "GIT_CONFIG_GLOBAL": "hostile-config",
        },
    )
    upper_keys = {key.upper() for key in environment}
    assert "GITHUB_TOKEN" not in upper_keys
    assert "GH_TOKEN" not in upper_keys
    assert "HTTP_PROXY" not in upper_keys
    assert "HTTPS_PROXY" not in upper_keys
    assert "NO_PROXY" not in upper_keys
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert sum(key.upper() == "PATH" for key in environment) == 1
    assert Path(environment["PATH"]).resolve() == Path(git).parent.resolve()


def test_repository_proof_binds_exact_commits_manifest_bytes_and_diff(tmp_path):
    _git, base, head, event = binding_repository(tmp_path)
    observed = {}

    def proof_runner(**kwargs):
        observed.update(kwargs)
        return PureProof("proved", {"kind": "program_control", "implementation_issue": 846})

    validated = []
    result = run_repository_proof(
        root=tmp_path,
        event=event,
        base=base,
        head=head,
        transport=None,
        proof_runner=proof_runner,
        manifest_validator=lambda root, candidate: validated.append((root, candidate)),
    )
    assert result.status == "proved"
    assert observed["candidate_manifest_bytes"] == b'{"version":2}\n'
    assert observed["candidate_manifest"] == {"version": 2}
    assert observed["baseline_manifest"] == {"version": 1}
    assert observed["diff"] == (
        b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0"
        b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0"
    )
    assert validated == [(tmp_path.resolve(), head)]


def test_repository_proof_rejects_non_ancestor_base(tmp_path):
    git, _base, head, event = binding_repository(tmp_path)
    subprocess.run(
        [git, "checkout", "--orphan", "unrelated"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run([git, "rm", "-rf", "."], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    subprocess.run([git, "add", "unrelated.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [git, "commit", "-m", "unrelated"], cwd=tmp_path, check=True, capture_output=True
    )
    unrelated = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run([git, "checkout", head], cwd=tmp_path, check=True, capture_output=True)
    event["pull_request"]["base"]["sha"] = unrelated
    with pytest.raises(MovementError, match="base is not an ancestor"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=unrelated,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: pytest.fail("proof must not run"),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_rejects_event_head_that_is_not_checkout(tmp_path):
    git, base, head, event = binding_repository(tmp_path)
    subprocess.run(
        [git, "commit", "--allow-empty", "-m", "different checkout"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    with pytest.raises(MovementError, match="event head does not equal checked-out HEAD"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: pytest.fail("proof must not run"),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_requires_both_canonical_manifest_files_in_exact_diff(tmp_path):
    git, base, _head, event = binding_repository(tmp_path)
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    document.write_bytes(b"# version 1\n")
    subprocess.run(
        [git, "commit", "-am", "omit generated view"], cwd=tmp_path, check=True, capture_output=True
    )
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event["pull_request"]["head"]["sha"] = head
    with pytest.raises(MovementError, match="omits canonical manifest or generated view"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: PureProof(
                "proved", {"kind": "program_control", "implementation_issue": 846}
            ),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_binding_preserves_non_nerva_skip_without_manifest_churn(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    manifest = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(candidate_manifest()), encoding="utf-8")
    document.write_text("unchanged\n", encoding="utf-8")
    subprocess.run([git, "add", "docs"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    source = tmp_path / "src/app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run([git, "add", "src/app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "ordinary"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base},
            "head": {"sha": head, "ref": "feature/ordinary"},
            "body": "",
            "draft": False,
        },
    }
    current = {**event["pull_request"], "repository": event["repository"], "state": "open"}
    result = run_repository_proof(
        root=tmp_path,
        event=event,
        base=base,
        head=head,
        transport={"pull_request": current}.__getitem__,
        manifest_validator=lambda *_args: pytest.fail("non-Nerva must not invoke validator"),
    )
    assert result.status == "non_nerva"


def test_repository_proof_rechecks_head_immediately_before_success(tmp_path):
    git, base, head, event = binding_repository(tmp_path)

    def move_head(**_kwargs):
        subprocess.run(
            [git, "commit", "--allow-empty", "-m", "move head"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        return PureProof("proved", {"kind": "program_control", "implementation_issue": 846})

    with pytest.raises(MovementError, match="checked-out HEAD moved"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=move_head,
            manifest_validator=lambda *_args: None,
        )
