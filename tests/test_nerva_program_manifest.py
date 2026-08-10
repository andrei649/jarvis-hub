from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_nerva_program_manifest as manifest_checker  # noqa: E402
from check_nerva_program_manifest import (  # noqa: E402
    DOCUMENT_RELATIVE,
    MANIFEST_RELATIVE,
    MAX_JSON_DEPTH,
    ManifestError,
    _derive_eligibility,
    _git_executable,
    _git_root_error,
    _tracked_repository_paths,
    _validate_snapshot,
    _verify_candidate_head,
    _verify_candidate_paths,
    _verify_git_evidence,
    load_json_strict,
    main,
    manifest_static_paths,
    render_markdown,
    run,
    validate_manifest,
    validate_repo_path,
)

MANIFEST = REPO / MANIFEST_RELATIVE
REGISTRY = REPO / "docs" / "nerva2" / "CONTRACT_REGISTRY.json"
EXPECTED_STREAMS = [f"E{number}" for number in range(13)]
EXPECTED_EPICS = {
    "E0": 758,
    "E1": 759,
    "E2": 760,
    "E3": 761,
    "E4": 762,
    "E5": 763,
    "E6": 764,
    "E7": 765,
    "E8": 766,
    "E9": 767,
    "E10": 768,
    "E11": 769,
    "E12": 773,
}


def _manifest() -> dict:
    return load_json_strict(MANIFEST)


def _registry() -> dict:
    return load_json_strict(REGISTRY)


def _errors(
    data: object,
    *,
    registry: object | None = None,
    root: Path = REPO,
    verify_git: bool = False,
) -> list[str]:
    return validate_manifest(
        data,
        root=root,
        registry=registry if registry is not None else _registry(),
        verify_git=verify_git,
    )


def _stream(data: dict, stream_id: str) -> dict:
    return next(item for item in data["streams"] if item["id"] == stream_id)


def _edge(data: dict, consumer: str, source: str) -> dict:
    return next(
        edge
        for edge in _stream(data, consumer)["delivery_prerequisites"]
        if edge["source"] == source
    )


def _blocker(data: dict, consumer: str, blocker_id: str) -> dict:
    return next(item for item in _stream(data, consumer)["blockers"] if item["id"] == blocker_id)


def _copy_fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    shutil.copytree(REPO / "docs" / "nerva2", root / "docs" / "nerva2")
    shutil.copy2(REPO / "BACKLOG.md", root / "BACKLOG.md")
    return root


def test_canonical_manifest_is_gate_complete_and_generated_view_is_exact() -> None:
    data = _manifest()

    assert [item["id"] for item in data["streams"]] == EXPECTED_STREAMS
    assert {item["id"]: item["epic_issue"] for item in data["streams"]} == EXPECTED_EPICS
    for stream in data["streams"]:
        assert bool(stream["completion_evidence"]) is (stream["program_status"] == "done")
        for edge in stream["delivery_prerequisites"]:
            assert bool(edge["accepted_evidence"]) is (edge["gate_state"] == "satisfied")
    # Full-history evidence resolution runs in the dedicated Nerva workflow. The general
    # pytest workflow intentionally uses a shallow checkout, so this assertion is structural.
    assert _errors(data, verify_git=False) == []

    expected = render_markdown(data).encode("utf-8")
    actual = (REPO / DOCUMENT_RELATIVE).read_bytes()
    assert actual == expected
    first_evidence = _stream(data, "E0")["completion_evidence"][0]
    commit = first_evidence["commit"]
    path = first_evidence["repo_path"]
    rendered = actual.decode("utf-8")
    assert "sole current dependency/status/gate/blocker/runtime truth" in rendered
    assert f"/commit/{commit}" in rendered
    assert f"/blob/{commit}/{path}" in rendered
    assert "(mutable context)" in rendered
    assert not actual.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in actual
    assert actual.endswith(b"\n") and not actual.endswith(b"\n\n")


def test_partial_epic_gates_allow_e3_and_e6_to_be_in_progress() -> None:
    data = _manifest()

    assert _stream(data, "E2")["program_status"] == "building"
    assert _edge(data, "E3", "E2")["gate_state"] == "satisfied"
    assert _edge(data, "E3", "E2")["accepted_evidence"]
    assert _stream(data, "E3")["delivery_eligibility"] == "in_progress"

    assert _stream(data, "E3")["program_status"] == "building"
    assert _edge(data, "E6", "E3")["gate_state"] == "satisfied"
    assert len(_edge(data, "E6", "E3")["accepted_evidence"]) == 1
    assert _stream(data, "E6")["delivery_eligibility"] == "in_progress"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["streams"].pop(), "stream order must be exactly"),
        (
            lambda data: data["streams"].append(copy.deepcopy(data["streams"][0])),
            "stream order must be exactly",
        ),
        (
            lambda data: _stream(data, "E2").update(epic_issue=759),
            "E2: epic_issue must be #760",
        ),
        (
            lambda data: _stream(data, "E1").update(program_status="shipped"),
            "E1: invalid program_status",
        ),
        (
            lambda data: _stream(data, "E3").update(delivery_eligibility="blocked"),
            "E3: delivery_eligibility must be 'in_progress'",
        ),
        (
            lambda data: _stream(data, "E1").update(delivery_eligibility="eligible"),
            "E1: delivery_eligibility must be 'in_progress'",
        ),
        (
            lambda data: _stream(data, "E0").update(delivery_eligibility="eligible"),
            "E0: delivery_eligibility must be 'satisfied'",
        ),
    ],
)
def test_status_and_eligibility_contradictions_fail_closed(mutate, message: str) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)
    assert any(message in error for error in _errors(data))


def test_done_or_blocked_status_requires_consistent_gate_state() -> None:
    done = copy.deepcopy(_manifest())
    e12 = _stream(done, "E12")
    e12["program_status"] = "done"
    e12["delivery_eligibility"] = "satisfied"
    assert any(
        "E12: done status cannot retain unsatisfied gates or blockers" in error
        for error in _errors(done)
    )

    blocked = copy.deepcopy(_manifest())
    e3 = _stream(blocked, "E3")
    e3["program_status"] = "blocked"
    e3["delivery_eligibility"] = "blocked"
    assert any(
        "E3: blocked status requires an unsatisfied gate or typed blocker" in error
        for error in _errors(blocked)
    )


@pytest.mark.parametrize(
    ("status", "has_open_cause", "expected"),
    [
        ("not_started", False, "eligible"),
        ("not_started", True, "blocked"),
        ("discovery", False, "in_progress"),
        ("discovery", True, "in_progress"),
        ("building", False, "in_progress"),
        ("building", True, "in_progress"),
        ("verifying", False, "in_progress"),
        ("verifying", True, "in_progress"),
        ("blocked", False, "blocked"),
        ("blocked", True, "blocked"),
        ("done", False, "satisfied"),
        ("done", True, "blocked"),
    ],
)
def test_delivery_eligibility_state_machine_is_complete(
    status: str, has_open_cause: bool, expected: str
) -> None:
    assert _derive_eligibility(status, has_open_cause) == expected


def test_done_status_is_bound_to_immutable_completion_evidence() -> None:
    missing = copy.deepcopy(_manifest())
    _stream(missing, "E0")["completion_evidence"] = []
    assert any(
        "E0: done status requires immutable completion evidence" in error
        for error in _errors(missing)
    )

    non_done = copy.deepcopy(_manifest())
    _stream(non_done, "E1")["completion_evidence"] = copy.deepcopy(
        _stream(non_done, "E0")["completion_evidence"]
    )
    assert any(
        "E1: non-done status cannot carry completion evidence" in error
        for error in _errors(non_done)
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: _edge(data, "E3", "E2").update(accepted_evidence=[]),
            "E3<-E2: satisfied gate requires immutable accepted evidence",
        ),
        (
            lambda data: _edge(data, "E4", "E3")["accepted_evidence"].append(
                copy.deepcopy(_edge(data, "E3", "E2")["accepted_evidence"][0])
            ),
            "E4<-E3: unsatisfied gate cannot carry accepted evidence",
        ),
        (
            lambda data: _edge(data, "E3", "E2")["accepted_evidence"][0].pop("commit"),
            "E3<-E2.accepted_evidence[0]: missing fields ['commit']",
        ),
        (
            lambda data: _edge(data, "E3", "E2")["accepted_evidence"][0].update(commit="abc"),
            "E3<-E2.accepted_evidence[0]: commit must be lowercase 40-hex",
        ),
        (
            lambda data: _edge(data, "E3", "E2")["accepted_evidence"][0].update(issue=True),
            "E3<-E2.accepted_evidence[0]: issue must be a positive integer",
        ),
        (
            lambda data: _edge(data, "E3", "E2")["accepted_evidence"][0].update(
                repo_path="../escape"
            ),
            "E3<-E2.accepted_evidence[0]: repository artifact path",
        ),
    ],
)
def test_gate_evidence_shape_and_mutable_only_claims_fail_closed(mutate, message: str) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)
    assert any(message in error for error in _errors(data))


def test_evidence_claim_codes_are_bound_to_their_semantic_context() -> None:
    completion = copy.deepcopy(_manifest())
    _stream(completion, "E0")["completion_evidence"][0]["claim_code"] = (
        "consumer_delivery_gate_accepted"
    )
    assert any(
        "claim_code is not valid for this evidence context" in error
        for error in _errors(completion)
    )

    gate_as_completion = copy.deepcopy(_manifest())
    _edge(gate_as_completion, "E3", "E2")["accepted_evidence"][0]["claim_code"] = (
        "stream_completion_accepted"
    )
    assert any(
        "claim_code is not valid for this evidence context" in error
        for error in _errors(gate_as_completion)
    )

    wrong_specialized_gate = copy.deepcopy(_manifest())
    _edge(wrong_specialized_gate, "E3", "E2")["accepted_evidence"][0]["claim_code"] = (
        "e0_control_gate_accepted"
    )
    assert any(
        "claim_code is not valid for this evidence context" in error
        for error in _errors(wrong_specialized_gate)
    )


def test_gate_evidence_is_resolved_against_immutable_baseline_history(tmp_path: Path) -> None:
    root = tmp_path / "history"
    root.mkdir()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init")
    git("config", "user.email", "nerva-tests@example.invalid")
    git("config", "user.name", "Nerva Tests")
    (root / "artifact.txt").write_text("accepted\n", encoding="utf-8", newline="\n")
    (root / "folder").mkdir()
    (root / "folder" / "nested.txt").write_text("nested\n", encoding="utf-8", newline="\n")
    git("add", "artifact.txt", "folder/nested.txt")
    git("commit", "-m", "accepted evidence (#42)")
    accepted = git("rev-parse", "HEAD")

    (root / "baseline.txt").write_text("baseline\n", encoding="utf-8", newline="\n")
    git("add", "baseline.txt")
    git("commit", "-m", "evidence baseline")
    baseline = git("rev-parse", "HEAD")

    assert _verify_git_evidence(root, baseline, accepted, "artifact.txt", "fixture", 42) == []
    git("tag", "-a", "annotated-evidence", "-m", "annotated evidence", accepted)
    annotated_evidence_object = git("rev-parse", "annotated-evidence")
    assert any(
        "accepted commit must identify an exact commit object" in error
        for error in _verify_git_evidence(
            root,
            baseline,
            annotated_evidence_object,
            "artifact.txt",
            "fixture",
            42,
        )
    )
    assert any(
        "accepted commit does not resolve" in error
        for error in _verify_git_evidence(root, baseline, "0" * 40, "artifact.txt", "fixture", 42)
    )

    invalid_snapshot = copy.deepcopy(_manifest()["evidence_snapshot"])
    invalid_snapshot["baseline_commit"] = "0" * 40
    invalid_baseline_errors: list[str] = []
    _validate_snapshot(
        invalid_snapshot,
        root=root,
        verify_git=True,
        errors=invalid_baseline_errors,
    )
    assert any(
        "evidence baseline does not resolve as an exact commit object" in error
        for error in invalid_baseline_errors
    )

    tagged_snapshot = copy.deepcopy(_manifest()["evidence_snapshot"])
    tagged_snapshot["baseline_commit"] = annotated_evidence_object
    tagged_baseline_errors: list[str] = []
    _validate_snapshot(
        tagged_snapshot,
        root=root,
        verify_git=True,
        errors=tagged_baseline_errors,
    )
    assert any(
        "evidence baseline must identify an exact commit object" in error
        for error in tagged_baseline_errors
    )

    (root / "late.txt").write_text("later\n", encoding="utf-8", newline="\n")
    git("add", "late.txt")
    git("commit", "-m", "post-baseline commit")
    later = git("rev-parse", "HEAD")
    _verify_candidate_head(root, later)
    with pytest.raises(ManifestError, match="does not equal checked-out HEAD"):
        _verify_candidate_head(root, baseline)
    git("tag", "-a", "annotated-candidate", "-m", "annotated candidate", later)
    annotated_tag_object = git("rev-parse", "annotated-candidate")
    with pytest.raises(ManifestError, match="exact commit object, not a tag"):
        _verify_candidate_head(root, annotated_tag_object)

    assert _verify_candidate_paths(root, later, {"artifact.txt"}) == []
    (root / "artifact.txt").write_text("modified\n", encoding="utf-8", newline="\n")
    assert any(
        "working tree differs from candidate commit" in error
        for error in _verify_candidate_paths(root, later, {"artifact.txt"})
    )
    (root / "artifact.txt").write_text("accepted\n", encoding="utf-8", newline="\n")
    git("update-index", "--skip-worktree", "artifact.txt")
    (root / "artifact.txt").write_text("hidden hostile\n", encoding="utf-8", newline="\n")
    assert any(
        "working tree differs from candidate commit" in error
        for error in _verify_candidate_paths(root, later, {"artifact.txt"})
    )
    git("update-index", "--no-skip-worktree", "artifact.txt")
    (root / "artifact.txt").write_text("accepted\n", encoding="utf-8", newline="\n")
    (root / "artifact.txt").write_text("staged hostile\n", encoding="utf-8", newline="\n")
    git("add", "artifact.txt")
    (root / "artifact.txt").write_text("accepted\n", encoding="utf-8", newline="\n")
    assert any(
        "index differs from candidate commit" in error
        for error in _verify_candidate_paths(root, later, {"artifact.txt"})
    )
    git("add", "artifact.txt")
    assert any(
        "consumed bytes differ from candidate commit" in error
        for error in _verify_candidate_paths(
            root,
            later,
            {"artifact.txt"},
            consumed_bytes={"artifact.txt": b"previously consumed hostile\n"},
        )
    )
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8", newline="\n")
    assert any(
        "tracked repository file" in error
        for error in _verify_candidate_paths(root, later, {"untracked.txt"})
    )
    assert "must equal Git top level" in (_git_root_error(root / "folder") or "")
    assert any(
        "is not an ancestor of evidence baseline" in error
        for error in _verify_git_evidence(root, baseline, later, "artifact.txt", "fixture", 42)
    )
    assert any(
        "artifact is absent at accepted commit" in error
        for error in _verify_git_evidence(root, baseline, accepted, "late.txt", "fixture", 42)
    )
    assert any(
        "artifact at accepted commit is not a blob" in error
        for error in _verify_git_evidence(root, baseline, accepted, "folder", "fixture", 42)
    )
    assert any(
        "evidence baseline does not resolve" in error
        for error in _verify_git_evidence(root, "f" * 40, accepted, "artifact.txt", "fixture", 42)
    )
    grafts = root / ".git" / "info" / "grafts"
    grafts.write_text(f"{later} {accepted}\n", encoding="ascii", newline="\n")
    assert "grafts" in (_git_root_error(root) or "")
    assert any(
        "grafts" in error
        for error in _verify_git_evidence(root, baseline, accepted, "artifact.txt", "fixture", 42)
    )


def test_git_executable_resolution_is_absolute_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "candidate-repository"
    safe_bin = tmp_path / "safe-bin"
    root.mkdir()
    safe_bin.mkdir()
    executable_name = "git.exe" if os.name == "nt" else "git"
    hostile = root / executable_name
    executable = safe_bin / executable_name
    hostile.write_bytes(b"hostile")
    executable.write_bytes(b"fixture")
    if os.name != "nt":
        hostile.chmod(0o700)
        executable.chmod(0o700)
    monkeypatch.chdir(root)
    environment = {"PATH": os.pathsep.join([str(root), "", "relative-bin", str(safe_bin)])}

    selected = Path(_git_executable(root, environment=environment))
    assert selected.is_absolute()
    assert selected.samefile(executable)
    assert not selected.samefile(hostile)

    with pytest.raises(FileNotFoundError, match="Git executable is unavailable"):
        _git_executable(root, environment={"PATH": str(root)})


def test_duplicate_gate_evidence_is_rejected() -> None:
    data = copy.deepcopy(_manifest())
    evidence = _edge(data, "E3", "E2")["accepted_evidence"]
    evidence.append(copy.deepcopy(evidence[0]))
    assert any("duplicate accepted evidence" in error for error in _errors(data))


def test_git_replace_refs_cannot_forge_immutable_evidence(tmp_path: Path) -> None:
    root = tmp_path / "replace-history"
    root.mkdir()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init")
    git("config", "user.email", "nerva-tests@example.invalid")
    git("config", "user.name", "Nerva Tests")
    (root / "base.txt").write_text("original\n", encoding="utf-8", newline="\n")
    git("add", "base.txt")
    git("commit", "-m", "wrong evidence subject")
    original = git("rev-parse", "HEAD")
    (root / "baseline.txt").write_text("baseline\n", encoding="utf-8", newline="\n")
    git("add", "baseline.txt")
    git("commit", "-m", "baseline")
    baseline = git("rev-parse", "HEAD")

    (root / "artifact.txt").write_text("forged\n", encoding="utf-8", newline="\n")
    git("add", "artifact.txt")
    forged_tree = git("write-tree")
    forged = subprocess.run(
        ["git", "-C", str(root), "commit-tree", forged_tree],
        input="accepted evidence (#42)\n",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git("replace", original, forged)

    errors = _verify_git_evidence(root, baseline, original, "artifact.txt", "fixture", 42)
    assert any("artifact is absent at accepted commit" in error for error in errors)
    assert any("accepted commit subject does not bind PR #42" in error for error in errors)


def test_git_repository_override_environment_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def create_repo(path: Path, payload: str) -> str:
        path.mkdir()
        subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(path), "config", "user.email", "nerva-tests@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "config", "user.name", "Nerva Tests"],
            check=True,
        )
        (path / "input.txt").write_text(payload, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(path), "add", "input.txt"], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", payload], check=True)
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    root = tmp_path / "real"
    foreign = tmp_path / "foreign"
    real_head = create_repo(root, "real\n")
    foreign_head = create_repo(foreign, "foreign\n")
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(root))

    assert _git_root_error(root) is None
    _verify_candidate_head(root, real_head)
    with pytest.raises(ManifestError):
        _verify_candidate_head(root, foreign_head)


def test_typed_blockers_cover_unsatisfied_edges_without_snapshot_pinning() -> None:
    missing_delivery = copy.deepcopy(_manifest())
    _stream(missing_delivery, "E4")["blockers"].clear()
    assert any(
        "E4<-E3: unsatisfied gate requires exactly one delivery_gate blocker" in error
        for error in _errors(missing_delivery)
    )

    ambiguous = copy.deepcopy(_manifest())
    blocker = copy.deepcopy(_blocker(ambiguous, "E4", "E4-delivery-E3"))
    blocker["id"] = "E3-forged-satisfied-blocker"
    blocker["target"] = "E2"
    _stream(ambiguous, "E3")["blockers"].append(blocker)
    assert any(
        "E3<-E2: satisfied gate cannot also have a delivery_gate blocker" in error
        for error in _errors(ambiguous)
    )

    no_longer_blocked = copy.deepcopy(_manifest())
    _stream(no_longer_blocked, "E5")["blockers"] = [
        blocker
        for blocker in _stream(no_longer_blocked, "E5")["blockers"]
        if blocker["kind"] == "delivery_gate"
    ]
    assert not any("missing required blocker" in error for error in _errors(no_longer_blocked))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: _blocker(data, "E5", "E5-program-B7").update(target="bad target"),
            "E5-program-B7: invalid blocker target",
        ),
        (
            lambda data: _blocker(data, "E5", "E5-program-B7").update(reason_code="all_done"),
            "E5-program-B7: invalid blocker reason_code",
        ),
        (
            lambda data: _blocker(data, "E5", "E5-program-B7").update(issue=True),
            "E5-program-B7: issue must be a positive integer",
        ),
        (
            lambda data: _blocker(data, "E5", "E5-program-B7").update(artifact="../escape"),
            "E5-program-B7: repository artifact path",
        ),
        (
            lambda data: _stream(data, "E5")["blockers"].append(
                copy.deepcopy(_blocker(data, "E5", "E5-program-B7"))
            ),
            "E5: duplicate blocker id 'E5-program-B7'",
        ),
    ],
)
def test_malformed_or_orphan_typed_blockers_fail_closed(mutate, message: str) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)
    assert any(message in error for error in _errors(data))


def test_non_delivery_blocker_reason_binds_kind_target_and_identifier() -> None:
    wrong_kind = copy.deepcopy(_manifest())
    _blocker(wrong_kind, "E11", "E11-owner-OWNER_LIVE")["kind"] = "program_gate"
    assert any("reason_code requires kind 'owner_live'" in error for error in _errors(wrong_kind))

    wrong_target = copy.deepcopy(_manifest())
    _blocker(wrong_target, "E11", "E11-owner-OWNER_LIVE")["target"] = "FAKE"
    assert any(
        "reason_code requires target 'OWNER_LIVE'" in error for error in _errors(wrong_target)
    )

    wrong_id = copy.deepcopy(_manifest())
    _blocker(wrong_id, "E11", "E11-owner-OWNER_LIVE")["id"] = "E11-program-OWNER_LIVE"
    assert any("blocker id is not canonical" in error for error in _errors(wrong_id))


def test_e5_prerequisites_are_exact_and_delivery_cycles_fail_closed() -> None:
    e5 = copy.deepcopy(_manifest())
    _stream(e5, "E5")["delivery_prerequisites"].pop(1)
    assert any("E5 direct prerequisites must be exactly" in error for error in _errors(e5))

    cyclic = copy.deepcopy(_manifest())
    _stream(cyclic, "E0")["delivery_prerequisites"] = [
        {"source": "E1", "gate_state": "unsatisfied", "accepted_evidence": []}
    ]
    _stream(cyclic, "E0")["blockers"] = [
        {
            "id": "E0-delivery-E1",
            "kind": "delivery_gate",
            "target": "E1",
            "issue": 759,
            "artifact": "docs/nerva2/DEPENDENCIES.md",
            "reason_code": "upstream_gate_not_accepted",
        }
    ]
    assert any("delivery cycle:" in error for error in _errors(cyclic))


def test_delivery_self_edge_and_unknown_dependency_source_fail_closed() -> None:
    self_edge = copy.deepcopy(_manifest())
    _stream(self_edge, "E4")["delivery_prerequisites"].append(
        {"source": "E4", "gate_state": "unsatisfied", "accepted_evidence": []}
    )
    assert any("E4<-E4: delivery self-edge is forbidden" in error for error in _errors(self_edge))

    unknown = copy.deepcopy(_manifest())
    _stream(unknown, "E4")["delivery_prerequisites"].append(
        {"source": "E99", "gate_state": "unsatisfied", "accepted_evidence": []}
    )
    assert any("invalid delivery source" in error for error in _errors(unknown))


def test_manifest_is_the_only_delivery_topology_source() -> None:
    data = copy.deepcopy(_manifest())
    _stream(data, "E4")["delivery_prerequisites"] = [
        edge for edge in _stream(data, "E4")["delivery_prerequisites"] if edge["source"] != "E3"
    ]
    _stream(data, "E4")["blockers"] = []
    _stream(data, "E4")["delivery_eligibility"] = "eligible"

    assert _errors(data) == []

    unrelated_registry_change = copy.deepcopy(_registry())
    unrelated_registry_change["delivery_dependencies"]["E4"] = ["E0", "E1"]
    assert _errors(data, registry=unrelated_registry_change) == []


def test_stream_reference_paths_are_owned_by_the_manifest() -> None:
    data = copy.deepcopy(_manifest())
    _stream(data, "E1")["references"][1]["value"] = "BACKLOG.md"
    assert _errors(data) == []


def test_runtime_feedback_is_separate_exact_and_never_authoritative() -> None:
    data = copy.deepcopy(_manifest())
    data["runtime_feedback_edges"][0]["grants_authority"] = True
    assert any("runtime feedback cannot grant authority" in error for error in _errors(data))

    orphan = copy.deepcopy(_manifest())
    orphan["runtime_feedback_edges"][0]["consumer"] = "E99"
    assert any("unknown runtime feedback consumer 'E99'" in error for error in _errors(orphan))

    registry = copy.deepcopy(_registry())
    registry["runtime_feedback_edges"].append(["E4", "E1"])
    assert any(
        "stale declared runtime drift" in error for error in _errors(_manifest(), registry=registry)
    )

    manifest_owned_removal = copy.deepcopy(_manifest())
    manifest_owned_removal["runtime_feedback_edges"].pop()
    assert _errors(manifest_owned_removal) == []

    unrelated_registry_change = copy.deepcopy(_registry())
    unrelated_registry_change["runtime_feedback_edges"].append(["E0", "E1"])
    assert _errors(_manifest(), registry=unrelated_registry_change) == []

    wrong_mode = copy.deepcopy(_manifest())
    wrong_mode["runtime_feedback_edges"][0]["mode"] = "authoritative_prediction"
    assert any(
        "mode must be a portable advisory identifier" in error for error in _errors(wrong_mode)
    )

    wrong_drift_reason = copy.deepcopy(_manifest())
    wrong_drift_reason["known_source_drifts"][0]["reason_code"] = "bad reason"
    assert any(
        "reason_code must be a portable identifier" in error
        for error in _errors(wrong_drift_reason)
    )


def test_runtime_only_cycle_never_enters_delivery_cycle_analysis() -> None:
    data = copy.deepcopy(_manifest())
    data["runtime_feedback_edges"].append(
        {"source": "E1", "consumer": "E6", "mode": "test_cycle_advisory", "grants_authority": False}
    )
    errors = _errors(data)
    assert not any("delivery cycle:" in error for error in errors)
    assert errors == []


@pytest.mark.parametrize(
    "path_value",
    [
        "../secret.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "\\\\server\\share\\file",
        "docs\\nerva2\\DEPENDENCIES.md",
        "https://example.com/file",
        "docs/nerva2/../nerva2/DEPENDENCIES.md",
        ".",
        "docs/nerva2",
        "docs/nerva2/DEPENDENCIES.md\x00suffix",
        "docs/nerva2/DEPENDENCIES.md\nsecond",
        ".git",
        ".git/config",
        "docs/nerva2/CON.txt",
        "docs/nerva2/trailing.",
        "docs/nerva2/double//segment.txt",
        "docs/nerva2/\ud800.txt",
    ],
)
def test_repository_artifact_paths_reject_unsafe_or_non_file_values(path_value: str) -> None:
    assert validate_repo_path(REPO, path_value) is not None


def test_repository_artifact_path_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    assert validate_repo_path(root, "escape.txt") is not None


def test_repository_artifact_path_rejects_internal_symlink_and_untracked_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    tracked = root / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True, capture_output=True)
    untracked = root / "untracked.txt"
    untracked.write_text("untracked\n", encoding="utf-8", newline="\n")
    assert "tracked repository file" in (validate_repo_path(root, "untracked.txt") or "")

    link = root / "alias.txt"
    try:
        os.symlink(tracked, link)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    assert "symlink" in (validate_repo_path(root, "alias.txt") or "")


@pytest.mark.parametrize("control", ["\u0085", "\u009b", "\u200b", "\u202e", "\u2066"])
def test_repository_artifact_path_rejects_unicode_controls(tmp_path: Path, control: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    relative = f"x{control}y.md"
    (root / relative).write_text("payload\n", encoding="utf-8", newline="\n")
    assert "control characters" in (validate_repo_path(root, relative) or "")


def test_repository_artifact_path_rejects_markdown_label_injection(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    relative = "x`](evil)[y.md"
    (root / relative).write_text("payload\n", encoding="utf-8", newline="\n")
    assert "portable ASCII" in (validate_repo_path(root, relative) or "")


def test_manifest_validation_enumerates_tracked_paths_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = subprocess.run
    ls_files_calls = 0

    def counting_run(*args, **kwargs):
        nonlocal ls_files_calls
        command = args[0]
        if command[-2:] == ["ls-files", "-z"]:
            ls_files_calls += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting_run)
    assert _errors(_manifest()) == []
    assert ls_files_calls == 1


def test_tracked_path_snapshot_is_fresh_per_validation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
    (root / "later.txt").write_text("later\n", encoding="utf-8", newline="\n")

    first, first_error = _tracked_repository_paths(root)
    assert first_error is None and first is not None
    assert b"later.txt" not in first
    assert "tracked repository file" in (
        validate_repo_path(root, "later.txt", tracked_paths=first) or ""
    )

    subprocess.run(["git", "-C", str(root), "add", "later.txt"], check=True)
    second, second_error = _tracked_repository_paths(root)
    assert second_error is None and second is not None
    assert b"later.txt" in second
    assert validate_repo_path(root, "later.txt", tracked_paths=second) is None


def test_tracked_path_enumeration_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_run = subprocess.run

    def failing_run(*args, **kwargs):
        command = args[0]
        if command[-2:] == ["ls-files", "-z"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=b"",
                stderr=b"forced enumeration failure",
            )
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failing_run)
    errors = _errors(_manifest())
    assert any("cannot enumerate tracked repository paths" in error for error in errors)
    assert any("must resolve to a tracked repository file" in error for error in errors)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(extra_root_field=True), "root: unknown fields"),
        (
            lambda data: _stream(data, "E1").update(extra_stream_field=True),
            "E1: unknown fields",
        ),
        (lambda data: data.update(schema_version=True), "schema_version must be integer 1"),
        (lambda data: data.update(schema_version=1.0), "schema_version must be integer 1"),
        (
            lambda data: data["evidence_snapshot"].update(program_issue=757.0),
            "evidence_snapshot.program_issue must be #757",
        ),
        (
            lambda data: _stream(data, "E1").update(epic_issue=759.0),
            "E1: epic_issue must be #759",
        ),
        (
            lambda data: data["authority"].update(can_authorize=True),
            "authority.can_authorize must remain false",
        ),
        (
            lambda data: data["authority"].update(release_ready=True),
            "authority.release_ready must remain false",
        ),
    ],
)
def test_closed_world_and_authority_contracts_fail_closed(mutate, message: str) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)
    assert any(message in error for error in _errors(data))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["streams"][0].update(id=[]),
        lambda data: _stream(data, "E1").update(program_status=[], delivery_eligibility=[]),
        lambda data: data["runtime_feedback_edges"][0].update(source={}),
        lambda data: data["known_source_drifts"][0]["edge"].update(source=[]),
        lambda data: data["streams"][0]["references"][0].update(kind=[]),
        lambda data: _edge(data, "E3", "E2").update(accepted_evidence=[[]]),
        lambda data: _stream(data, "E5")["blockers"].__setitem__(0, []),
        lambda data: _stream(data, "E1")["references"].__setitem__(0, []),
        lambda data: data["runtime_feedback_edges"].__setitem__(0, []),
        lambda data: data["known_source_drifts"].__setitem__(0, []),
        lambda data: data.update(authority=[]),
        lambda data: data.update(invariants=[]),
    ],
)
def test_hostile_json_types_return_errors_instead_of_tracebacks(mutate) -> None:
    data = copy.deepcopy(_manifest())
    mutate(data)
    errors = _errors(data)
    assert errors
    assert all(isinstance(error, str) for error in errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blocked_requires_open_cause", 1),
        ("done_open_cause_allowed", 0),
    ],
)
def test_eligibility_boolean_invariants_reject_integer_aliases(field: str, value: int) -> None:
    data = copy.deepcopy(_manifest())
    data["invariants"]["delivery_eligibility_derivation"][field] = value
    assert any(
        "delivery_eligibility_derivation must match the canonical derivation rule" in error
        for error in _errors(data)
    )


def test_cli_escapes_surrogate_errors_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_fixture_root(tmp_path)
    manifest_path = root / MANIFEST_RELATIVE
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    _stream(data, "E5")["blockers"][0]["id"] = "\ud800"
    data["\ud800"] = True
    manifest_path.write_text(json.dumps(data), encoding="utf-8", newline="\n")

    assert main(["--root", str(root), "--check"]) == 1
    assert "\\ud800" in capsys.readouterr().err


def test_cli_rejects_nul_repository_root_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--root", "\x00", "--check"]) == 1
    assert capsys.readouterr().err


def test_nested_enum_and_duplicate_ambiguity_fail_closed() -> None:
    bad_gate = copy.deepcopy(_manifest())
    _edge(bad_gate, "E3", "E2")["gate_state"] = "accepted"
    assert any("invalid gate_state" in error for error in _errors(bad_gate))

    bad_claim = copy.deepcopy(_manifest())
    _edge(bad_claim, "E3", "E2")["accepted_evidence"][0]["claim_code"] = "trusted"
    assert any("invalid claim_code" in error for error in _errors(bad_claim))

    bad_kind = copy.deepcopy(_manifest())
    _blocker(bad_kind, "E5", "E5-program-B7")["kind"] = "free_text"
    assert any("invalid blocker kind" in error for error in _errors(bad_kind))

    duplicate_edge = copy.deepcopy(_manifest())
    _stream(duplicate_edge, "E3")["delivery_prerequisites"].append(
        copy.deepcopy(_edge(duplicate_edge, "E3", "E2"))
    )
    assert any("duplicate delivery prerequisite 'E2'" in error for error in _errors(duplicate_edge))

    duplicate_reference = copy.deepcopy(_manifest())
    _stream(duplicate_reference, "E1")["references"].append(
        copy.deepcopy(_stream(duplicate_reference, "E1")["references"][0])
    )
    assert any("duplicate reference" in error for error in _errors(duplicate_reference))


def test_strict_json_loader_rejects_duplicate_keys_and_non_finite_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate JSON key 'schema_version'"):
        load_json_strict(duplicate)

    non_finite = tmp_path / "non-finite.json"
    non_finite.write_text('{"schema_version": NaN}', encoding="utf-8")
    with pytest.raises(ManifestError, match="non-finite JSON value 'NaN'"):
        load_json_strict(non_finite)

    for token in ("1e999", "-1e999"):
        exponent = tmp_path / f"exponent-{token[0]}.json"
        exponent.write_text(f'{{"value": {token}}}', encoding="utf-8")
        with pytest.raises(ManifestError, match="floating-point JSON value"):
            load_json_strict(exponent)

    boundary = tmp_path / "depth-boundary.json"
    boundary.write_text(
        "[" * MAX_JSON_DEPTH + "0" + "]" * MAX_JSON_DEPTH,
        encoding="utf-8",
    )
    assert load_json_strict(boundary)

    deep = tmp_path / "deep.json"
    depth = MAX_JSON_DEPTH + 2
    deep.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")
    with pytest.raises(ManifestError, match="JSON nesting exceeds"):
        load_json_strict(deep)

    huge_integer = tmp_path / "huge-integer.json"
    huge_integer.write_text('{"value": ' + "9" * 5000 + "}", encoding="utf-8")
    with pytest.raises(ManifestError, match="integer JSON value exceeds 20 digits"):
        load_json_strict(huge_integer)

    control_key = tmp_path / "control-key.json"
    control_key.write_text(
        '{"\\u001b[31m": 1, "\\u001b[31m": 2}',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError) as exc_info:
        load_json_strict(control_key)
    assert "\x1b" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("observed_at", "message"),
    [
        ("2026-08-04T23:59:59Z", "predates manifest v1"),
        ("2099-01-01T00:00:00Z", "cannot be in the future"),
    ],
)
def test_evidence_observation_time_is_bounded(observed_at: str, message: str) -> None:
    data = copy.deepcopy(_manifest())
    data["evidence_snapshot"]["observed_at_utc"] = observed_at
    assert any(message in error for error in _errors(data))


def test_drift_source_digest_binds_the_asserted_repository_bytes(tmp_path: Path) -> None:
    root = _copy_fixture_root(tmp_path)
    (root / "docs" / "nerva2" / "DEPENDENCIES.md").write_text(
        "changed source\n", encoding="utf-8", newline="\n"
    )
    data = load_json_strict(root / MANIFEST_RELATIVE)
    registry = load_json_strict(root / "docs" / "nerva2" / "CONTRACT_REGISTRY.json")
    assert any(
        "present_in_sha256 does not match source content" in error
        for error in _errors(data, registry=registry, root=root)
    )


def test_drift_source_anchor_binds_the_asserted_edge_semantics() -> None:
    data = copy.deepcopy(_manifest())
    drift = data["known_source_drifts"][0]
    unrelated = REPO / "pyproject.toml"
    drift["present_in"] = "pyproject.toml"
    drift["present_in_sha256"] = hashlib.sha256(
        unrelated.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    assert any(
        "present_in_anchor does not occur in source content" in error for error in _errors(data)
    )


def test_generated_markdown_is_deterministic_under_blocker_reordering() -> None:
    data = copy.deepcopy(_manifest())
    baseline = render_markdown(data)
    _stream(data, "E5")["blockers"].reverse()
    assert render_markdown(data) == baseline


def test_write_repairs_drift_with_lf_is_idempotent_and_check_detects_crlf(tmp_path: Path) -> None:
    root = _copy_fixture_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    document.write_bytes(b"stale\r\n")

    messages = run(root, write=True, verify_git=False)
    first = document.read_bytes()
    assert messages[-1] == "generated Markdown updated"
    assert first == render_markdown(load_json_strict(root / MANIFEST_RELATIVE)).encode("utf-8")
    assert b"\r\n" not in first

    second_messages = run(root, write=True, verify_git=False)
    assert second_messages[-1] == "generated Markdown already current"
    assert document.read_bytes() == first

    document.write_bytes(first.replace(b"\n", b"\r\n"))
    with pytest.raises(ManifestError, match="generated Markdown drift"):
        run(root, write=False, verify_git=False)


def test_atomic_write_never_widens_temporary_file_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _copy_fixture_root(tmp_path)
    (root / DOCUMENT_RELATIVE).write_bytes(b"stale\n")

    def reject_permission_widening(*args, **kwargs) -> None:
        raise AssertionError("generated output permissions must not be widened")

    monkeypatch.setattr(manifest_checker.os, "chmod", reject_permission_widening)
    messages = run(root, write=True, verify_git=False)

    assert messages[-1] == "generated Markdown updated"


def test_exact_head_run_binds_bytes_consumed_before_candidate_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "candidate"
    for relative in manifest_static_paths(_manifest()):
        source = REPO / Path(*relative.split("/"))
        destination = root / Path(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "nerva-tests@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Nerva Tests"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "candidate"], check=True)
    candidate = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    document = root / DOCUMENT_RELATIVE
    document_before = document.read_bytes()
    with pytest.raises(ManifestError, match="candidate_ref is check-only"):
        run(root, write=True, verify_git=False, candidate_ref=candidate)
    assert document.read_bytes() == document_before

    original_loader = manifest_checker._load_json_strict_with_bytes

    def substituted_loader(path: Path):
        data, raw = original_loader(path)
        if path == root / MANIFEST_RELATIVE:
            return data, raw + b" "
        return data, raw

    monkeypatch.setattr(manifest_checker, "_load_json_strict_with_bytes", substituted_loader)
    with pytest.raises(ManifestError, match="consumed bytes differ from candidate commit"):
        run(root, write=False, verify_git=False, candidate_ref=candidate)


def test_exact_head_run_rechecks_head_immediately_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "candidate-head-move"
    for relative in manifest_static_paths(_manifest()):
        source = REPO / Path(*relative.split("/"))
        destination = root / Path(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "nerva-tests@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Nerva Tests"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "candidate"], check=True)
    candidate = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    original_verify_paths = manifest_checker._verify_candidate_paths

    def move_head_after_path_verification(*args, **kwargs):
        errors = original_verify_paths(*args, **kwargs)
        subprocess.run(
            ["git", "-C", str(root), "commit", "--allow-empty", "-m", "same-tree successor"],
            check=True,
        )
        return errors

    monkeypatch.setattr(
        manifest_checker, "_verify_candidate_paths", move_head_after_path_verification
    )
    with pytest.raises(ManifestError, match="does not equal checked-out HEAD"):
        run(root, write=False, verify_git=False, candidate_ref=candidate)


def test_invalid_manifest_never_rewrites_existing_document(tmp_path: Path) -> None:
    root = _copy_fixture_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    original = b"preserve me exactly\r\n"
    document.write_bytes(original)

    path = root / MANIFEST_RELATIVE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["streams"].pop()
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")

    with pytest.raises(ManifestError, match="stream order must be exactly"):
        run(root, write=True, verify_git=False)
    assert document.read_bytes() == original


def test_generated_document_symlink_is_rejected(tmp_path: Path) -> None:
    root = _copy_fixture_root(tmp_path)
    document = root / DOCUMENT_RELATIVE
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8", newline="\n")
    document.unlink()
    try:
        os.symlink(outside, document)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    with pytest.raises(ManifestError, match="target must not be a symlink"):
        run(root, write=True, verify_git=False)
    assert outside.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.parametrize(
    "relative",
    [
        MANIFEST_RELATIVE,
        Path("docs/nerva2/CONTRACT_REGISTRY.json"),
    ],
)
def test_canonical_json_input_symlink_is_rejected(tmp_path: Path, relative: Path) -> None:
    root = _copy_fixture_root(tmp_path)
    canonical = root / relative
    outside = tmp_path / f"outside-{canonical.name}"
    outside.write_bytes(canonical.read_bytes())
    canonical.unlink()
    try:
        os.symlink(outside, canonical)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    with pytest.raises(ManifestError, match="JSON input must be a non-symlink regular file"):
        run(root, write=False, verify_git=False)


def test_roadmap_workflow_wires_every_static_input_and_check_only_command() -> None:
    workflow = (REPO / ".github" / "workflows" / "nerva-roadmap.yml").read_text(encoding="utf-8")
    policy = json.loads((REPO / ".github" / "change-risk.json").read_text(encoding="utf-8"))
    for relative in manifest_static_paths(_manifest()):
        assert any(fnmatchcase(relative, pattern) for pattern in policy["nerva_patterns"])
    assert "  workflow_call:" in workflow
    assert "  workflow_dispatch:" in workflow
    assert "  pull_request:" not in workflow
    assert "  push:" not in workflow
    assert workflow.count("scripts/check_nerva_program_manifest.py") == 2
    assert workflow.count("          --check\n") == 1
    assert workflow.count('--candidate-ref "${NERVA_CANDIDATE_REF}"') == 2
    assert "fetch-depth: 0" in workflow
    assert "scripts/check_nerva_program_manifest.py\n" in workflow
    assert "tests/test_nerva_program_manifest.py\n" in workflow
