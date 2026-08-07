#!/usr/bin/env python3
"""Validate and render the offline Nerva E0-E12 program evidence manifest.

The manifest is repository evidence, not live GitHub state, execution authority, completion
authority, or a release decision. Delivery gates and runtime feedback are deliberately separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat

# The checker invokes only an absolute Git executable with fixed argv and shell=False.
import subprocess  # nosec B404
import sys
import tempfile
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

MANIFEST_RELATIVE = Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json")
DOCUMENT_RELATIVE = Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md")
REGISTRY_RELATIVE = Path("docs/nerva2/CONTRACT_REGISTRY.json")
CONTROL_RELATIVE_PATHS = {
    MANIFEST_RELATIVE.as_posix(),
    DOCUMENT_RELATIVE.as_posix(),
    REGISTRY_RELATIVE.as_posix(),
    "scripts/check_nerva_program_manifest.py",
    "tests/test_nerva_program_manifest.py",
    ".github/workflows/nerva-roadmap.yml",
}

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
EXPECTED_NAMES = {
    "E0": "Baseline and migration map",
    "E1": "Cortex meta-decision and capability routing",
    "E2": "Atlas unified reality graph",
    "E3": "Episodes experience-centric memory",
    "E4": "Howard digital twin and preference model",
    "E5": "Night Shift autonomous work loop",
    "E6": "Reflection and memory consolidation",
    "E7": "Governed world model and what-if simulation",
    "E8": "Synapse Skills SDK and acquisition loop",
    "E9": "Research Lab and continuous benchmark harness",
    "E10": "Executive dashboard and coherent experience",
    "E11": "Proof, safety and release gate",
    "E12": "Hybrid Cognition Lab",
}
STREAM_SOURCE_TOKENS = {
    "E0": "E0",
    "E1": "Cortex",
    "E2": "Atlas",
    "E3": "Episodes",
    "E4": "Howard",
    "E5": "Night Shift",
    "E6": "Reflection",
    "E7": "World Model",
    "E8": "Synapse",
    "E9": "Research Lab",
    "E10": "Experience",
    "E11": "Verification",
    "E12": "E12",
}
PROGRAM_STATES = {"not_started", "discovery", "building", "verifying", "blocked", "done"}
DELIVERY_ELIGIBILITY = {"blocked", "eligible", "in_progress", "satisfied"}
GATE_STATES = {"satisfied", "unsatisfied"}
REFERENCE_KINDS = {"issue", "repo_path"}
BLOCKER_KINDS = {"delivery_gate", "program_gate", "owner_live", "external_dependency"}
BLOCKER_REASON_TEXT = {
    "upstream_gate_not_accepted": "Consumer-specific upstream gate evidence is not accepted.",
    "task_mediation_acceptance_pending": "Task-mediation evidence awaits exact-head acceptance.",
    "provider_preflight_not_accepted": "Execution-provider preflight is not accepted.",
    "provider_specific_evidence_missing": "Provider-specific evidence is missing.",
    "owner_live_proof_missing": "Owner-host live proof is missing.",
    "restore_soak_proof_missing": "Restore and soak proof is missing.",
    "recurring_workflow_proof_missing": "Recurring-workflow proof is missing.",
}
BLOCKER_REASON_CONTRACT = {
    "upstream_gate_not_accepted": ("delivery_gate", None),
    "task_mediation_acceptance_pending": ("program_gate", "B7"),
    "provider_preflight_not_accepted": ("external_dependency", "E8_1C"),
    "provider_specific_evidence_missing": ("external_dependency", "PROVIDER_E9"),
    "owner_live_proof_missing": ("owner_live", "OWNER_LIVE"),
    "restore_soak_proof_missing": ("program_gate", "RESTORE_SOAK"),
    "recurring_workflow_proof_missing": ("program_gate", "RECURRING_WORKFLOWS"),
}
BLOCKER_KIND_ID_TOKEN = {
    "delivery_gate": "delivery",
    "program_gate": "program",
    "owner_live": "owner",
    "external_dependency": "external",
}
CLAIM_TEXT = {
    "e0_control_gate_accepted": "E0 control gate accepted",
    "atlas_minimum_for_episodes_accepted": "Atlas minimum for Episodes accepted",
    "episodes_minimum_for_reflection_accepted": "Episodes minimum for Reflection accepted",
    "consumer_delivery_gate_accepted": "Consumer delivery gate accepted",
    "stream_completion_accepted": "Stream completion accepted",
}
E5_PREREQUISITES = ["E0", "E1", "E2", "E3", "E6"]

ROOT_FIELDS = {
    "schema_version",
    "manifest_id",
    "evidence_snapshot",
    "authority",
    "streams",
    "runtime_feedback_edges",
    "known_source_drifts",
    "invariants",
    "movement_gate",
}
SNAPSHOT_FIELDS = {
    "repository",
    "baseline_commit",
    "observed_at_utc",
    "program_issue",
    "blocker_plan_issue",
    "control_issue",
    "live_issue_state_verified_by_checker",
}
AUTHORITY_FIELDS = {
    "status_is_evidence_label_only",
    "can_authorize",
    "can_execute",
    "completion_authority",
    "release_ready",
    "ultron_remains_sole_action_authority",
}
STREAM_FIELDS = {
    "id",
    "name",
    "epic_issue",
    "program_status",
    "delivery_eligibility",
    "completion_evidence",
    "delivery_prerequisites",
    "blockers",
    "references",
}
EDGE_FIELDS = {"source", "gate_state", "accepted_evidence"}
EVIDENCE_FIELDS = {"commit", "repo_path", "issue", "pull_request", "claim_code"}
BLOCKER_FIELDS = {"id", "kind", "target", "issue", "artifact", "reason_code"}
REFERENCE_FIELDS = {"kind", "value"}
RUNTIME_FIELDS = {"source", "consumer", "mode", "grants_authority"}
DRIFT_FIELDS = {
    "id",
    "state",
    "present_in",
    "present_in_sha256",
    "present_in_anchor",
    "missing_from",
    "edge",
    "reason_code",
}
DRIFT_EDGE_FIELDS = {"source", "consumer"}
INVARIANT_FIELDS = {
    "e5_direct_prerequisites",
    "runtime_feedback_is_not_delivery_authority",
    "satisfied_gate_requires_immutable_evidence",
    "delivery_eligibility_derivation",
}
ELIGIBILITY_DERIVATION_FIELDS = {
    "active_program_statuses",
    "active_result",
    "open_cause_types",
    "not_started_open_cause_result",
    "not_started_clear_result",
    "blocked_result",
    "blocked_requires_open_cause",
    "done_clear_result",
    "done_open_cause_allowed",
}
EXPECTED_ELIGIBILITY_DERIVATION = {
    "active_program_statuses": ["discovery", "building", "verifying"],
    "active_result": "in_progress",
    "open_cause_types": ["unsatisfied_delivery_gate", "typed_blocker"],
    "not_started_open_cause_result": "blocked",
    "not_started_clear_result": "eligible",
    "blocked_result": "blocked",
    "blocked_requires_open_cause": True,
    "done_clear_result": "satisfied",
    "done_open_cause_allowed": False,
}

LEGACY_MOVEMENT_BASE = "843918848c11bbd3f0099f9504d0e0eaaa56b9d6"
MOVEMENT_BRANCH_PREFIX = "nerva2/"
MOVEMENT_ATTESTATION_START = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
MANUAL_INTEGRATION_WORKFLOW = ".github/workflows/pr-auto-merge.yml"
MANUAL_INTEGRATION_POLICY_TEST = "tests/test_pr_auto_merge_policy.py"
MOVEMENT_GATE_FIELDS = {
    "schema_version",
    "enforcement_state",
    "bootstrap_base",
    "branch_prefix",
    "attestation_start_marker",
    "registry",
    "program_control_issues",
    "receipt_control",
    "manual_integration",
    "rollback",
}
RECEIPT_CONTROL_FIELDS = {
    "mode",
    "live_pr_reread_required",
    "fresh_exact_head_rerun_required",
    "fresh_owner_receipts_required",
    "continuous_currentness",
}
MANUAL_INTEGRATION_FIELDS = {"issue", "workflow_path", "policy_test_path"}
ROLLBACK_FIELDS = {
    "issue",
    "rollback_of_issue",
    "reason",
    "fresh_owner_receipts_required",
    "exact_head_checks_required",
}
REQUIRED_MOVEMENT_STATIC_PATHS = {
    MANUAL_INTEGRATION_WORKFLOW,
    MANUAL_INTEGRATION_POLICY_TEST,
}
MAX_ROLLBACK_REASON_BYTES = 512

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")
PORTABLE_REPO_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
MANIFEST_V1_NOT_BEFORE = datetime(2026, 8, 5, tzinfo=UTC)
MAX_JSON_DEPTH = 64


class ManifestError(RuntimeError):
    """Raised for deterministic manifest, generation, or repository-evidence failures."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ManifestError(f"non-finite JSON value '{value}'")


def _reject_float(value: str) -> None:
    raise ManifestError(f"floating-point JSON value {value!r} is not allowed")


def _parse_int(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > 20:
        raise ManifestError("integer JSON value exceeds 20 digits")
    return int(value)


def _reject_excessive_json_depth(data: Any, path: Path) -> None:
    stack: list[tuple[Any, int]] = [(data, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ManifestError(
                f"invalid JSON in {path}: JSON nesting exceeds {MAX_JSON_DEPTH} levels"
            )
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def _load_json_strict_with_bytes(path: Path) -> tuple[Any, bytes]:
    """Load strict JSON and retain the exact bytes that produced the parsed value."""

    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ManifestError(f"JSON input must be a non-symlink regular file: {path}")
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ManifestError(f"UTF-8 BOM is not allowed in {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"invalid UTF-8 in {path}: {exc}") from exc
    try:
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
            parse_float=_reject_float,
            parse_int=_parse_int,
        )
        _reject_excessive_json_depth(data, path)
    except ManifestError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ManifestError(f"invalid JSON in {path}: {exc}") from exc
    return data, raw


def load_json_strict(path: Path) -> Any:
    """Load UTF-8 JSON while rejecting BOMs, duplicate keys, and non-finite numbers."""

    data, _ = _load_json_strict_with_bytes(path)
    return data


def _field_errors(value: Any, expected: set[str], label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}: must be an object"]
    actual = set(value)
    errors: list[str] = []
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        errors.append(f"{label}: missing fields {missing}")
    if unknown:
        errors.append(f"{label}: unknown fields {unknown}")
    return errors


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _safe_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def validate_repo_path(
    root: Path,
    value: Any,
    *,
    tracked_paths: frozenset[bytes] | None = None,
) -> str | None:
    """Return an error for unsafe/non-file repository paths, otherwise ``None``."""

    if not isinstance(value, str):
        return "must be a string"
    if not value or value != value.strip():
        return "must be a non-empty trimmed path"
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        return "must not contain control characters"
    if PORTABLE_REPO_PATH.fullmatch(value) is None:
        return "must use portable ASCII path characters"
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return "must be valid UTF-8 without surrogate code points"
    if unicodedata.normalize("NFC", value) != value:
        return "must use NFC Unicode normalization"
    if "\\" in value or ":" in value or "://" in value:
        return "must use normalized POSIX repository-relative syntax"
    if "//" in value:
        return "must not contain empty path segments"
    pure = PurePosixPath(value)
    if pure.is_absolute() or value.startswith("//"):
        return "must be repository-relative"
    if value == "." or any(part in {"", ".", ".."} for part in pure.parts):
        return "must not contain empty, dot, or parent segments"
    if pure.as_posix() != value:
        return "must be normalized"
    invalid_windows_characters = set('<>:"|?*')
    windows_reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    for part in pure.parts:
        if part.casefold() == ".git":
            return "must not address Git internal metadata"
        if part.endswith((".", " ")):
            return "must not use Windows trailing dot or space segments"
        if any(character in invalid_windows_characters for character in part):
            return "must not contain Windows-reserved characters"
        if part.split(".", 1)[0].upper() in windows_reserved:
            return "must not use Windows-reserved names"

    try:
        root_resolved = root.resolve(strict=True)
        cursor = root_resolved
        for part in pure.parts:
            cursor /= part
            if cursor.is_symlink():
                return "must not traverse symlink components"
        candidate = cursor.resolve(strict=True)
        candidate.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return "must resolve to an existing file inside the repository"
    if not candidate.is_file():
        return "must resolve to a regular file"
    if tracked_paths is not None:
        if value.encode("utf-8") not in tracked_paths:
            return "must resolve to a tracked repository file"
    elif (root_resolved / ".git").exists():
        tracked_result, _ = _git_call(
            str(root_resolved), ("ls-files", "--error-unmatch", "--", value)
        )
        if tracked_result != 0:
            return "must resolve to a tracked repository file"
    return None


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _git_executable(root: str | Path, *, environment: Mapping[str, str] | None = None) -> str:
    """Resolve Git from absolute PATH entries outside the repository and cwd."""

    source = os.environ if environment is None else environment
    path_value = next((value for key, value in source.items() if key.upper() == "PATH"), "")
    try:
        protected_roots = {Path(root).resolve(strict=True), Path.cwd().resolve(strict=True)}
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError(f"Git executable trust roots cannot be resolved: {exc}") from exc
    executable_name = "git.exe" if os.name == "nt" else "git"
    for raw_entry in path_value.split(os.pathsep):
        entry = raw_entry.strip().strip('"')
        directory = Path(entry)
        if not entry or not directory.is_absolute():
            continue
        try:
            candidate = (directory / executable_name).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not candidate.is_file() or not candidate.is_absolute():
            continue
        if os.name != "nt" and not os.access(candidate, os.X_OK):
            continue
        if any(
            candidate == protected or candidate.is_relative_to(protected)
            for protected in protected_roots
        ):
            continue
        return str(candidate)
    raise FileNotFoundError("Git executable is unavailable outside the repository and cwd")


def _git_call(root_text: str, arguments: tuple[str, ...]) -> tuple[int, str]:
    try:
        environment = _git_environment()
        # Arguments remain a fixed list; repository values never enter a shell command.
        completed = subprocess.run(  # nosec B603
            [
                _git_executable(root_text, environment=environment),
                "--no-replace-objects",
                "-C",
                root_text,
                *arguments,
            ],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return 127, str(exc)
    message = (
        completed.stdout.strip()
        if completed.returncode == 0
        else (completed.stderr or completed.stdout).strip()
    )
    return completed.returncode, message


def _tracked_repository_paths(
    root: Path,
) -> tuple[frozenset[bytes] | None, str | None]:
    try:
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return frozenset(), f"cannot enumerate tracked repository paths: {exc}"
    if not (root_resolved / ".git").exists():
        return None, None
    try:
        environment = _git_environment()
        # Arguments remain a fixed list; repository values never enter a shell command.
        completed = subprocess.run(  # nosec B603
            [
                _git_executable(root_resolved, environment=environment),
                "--no-replace-objects",
                "-C",
                str(root_resolved),
                "ls-files",
                "-z",
            ],
            check=False,
            capture_output=True,
            env=environment,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return frozenset(), f"cannot enumerate tracked repository paths: {exc}"
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).decode("utf-8", errors="backslashreplace")
        return frozenset(), f"cannot enumerate tracked repository paths: {message.strip()}"
    return frozenset(path for path in completed.stdout.split(b"\0") if path), None


def _git_hash_bytes(root_text: str, payload: bytes) -> tuple[int, str]:
    try:
        environment = _git_environment()
        # Arguments remain a fixed list; repository values never enter a shell command.
        completed = subprocess.run(  # nosec B603
            [
                _git_executable(root_text, environment=environment),
                "--no-replace-objects",
                "-C",
                root_text,
                "hash-object",
                "--stdin",
                "--no-filters",
            ],
            input=payload,
            check=False,
            capture_output=True,
            env=environment,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    output = completed.stdout if completed.returncode == 0 else completed.stderr
    return completed.returncode, output.decode("ascii", errors="backslashreplace").strip()


def _git_grafts_error(root_text: str) -> str | None:
    result, path_text = _git_call(
        root_text,
        ("rev-parse", "--path-format=absolute", "--git-path", "info/grafts"),
    )
    if result != 0:
        return f"cannot inspect legacy Git grafts path: {path_text}"
    try:
        metadata = Path(path_text).lstat()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return f"cannot inspect legacy Git grafts file: {exc}"
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size:
        return "legacy Git grafts are unsupported for immutable evidence verification"
    return None


def _git_root_error(root: Path) -> str | None:
    try:
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"repository root is invalid: {exc}"
    result, message = _git_call(str(root_resolved), ("rev-parse", "--show-toplevel"))
    if result != 0:
        return f"repository root is not a Git worktree: {message}"
    try:
        discovered = Path(message).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"Git top-level path is invalid: {exc}"
    if discovered != root_resolved:
        return f"repository root must equal Git top level {discovered}"
    return _git_grafts_error(str(root_resolved))


def _verify_git_evidence(
    root: Path,
    baseline: str,
    commit: str,
    repo_path: str,
    label: str,
    pull_request: int | None = None,
) -> list[str]:
    errors: list[str] = []
    root_text = str(root.resolve())
    grafts_error = _git_grafts_error(root_text)
    if grafts_error:
        return [grafts_error]
    baseline_result, baseline_message = _git_call(root_text, ("cat-file", "-t", baseline))
    if baseline_result != 0:
        return [f"evidence baseline does not resolve as an exact commit object: {baseline_message}"]
    if baseline_message != "commit":
        return ["evidence baseline must identify an exact commit object"]

    head_result, head_message = _git_call(root_text, ("cat-file", "-e", "HEAD^{commit}"))
    if head_result != 0:
        return [f"candidate HEAD does not resolve as a commit: {head_message}"]
    baseline_ancestor_result, baseline_ancestor_message = _git_call(
        root_text, ("merge-base", "--is-ancestor", baseline, "HEAD")
    )
    if baseline_ancestor_result == 1:
        errors.append("evidence baseline is not an ancestor of candidate HEAD")
    elif baseline_ancestor_result != 0:
        errors.append(
            "cannot compare evidence baseline to candidate HEAD: " + baseline_ancestor_message
        )

    commit_type_result, commit_type = _git_call(root_text, ("cat-file", "-t", commit))
    if commit_type_result != 0:
        return [f"{label}: accepted commit does not resolve: {commit_type}"]
    if commit_type != "commit":
        return [f"{label}: accepted commit must identify an exact commit object"]
    commit_result, commit_message = _git_call(root_text, ("cat-file", "-e", f"{commit}^{{commit}}"))
    if commit_result != 0:
        return [f"{label}: accepted commit does not resolve: {commit_message}"]

    ancestor_result, ancestor_message = _git_call(
        root_text, ("merge-base", "--is-ancestor", commit, baseline)
    )
    if ancestor_result == 1:
        errors.append(f"{label}: accepted commit is not an ancestor of evidence baseline")
    elif ancestor_result != 0:
        errors.append(f"{label}: cannot compare accepted commit to baseline: {ancestor_message}")

    artifact_result, artifact_message = _git_call(
        root_text, ("cat-file", "-t", f"{commit}:{repo_path}")
    )
    if artifact_result != 0:
        errors.append(f"{label}: artifact is absent at accepted commit: {artifact_message}")
    elif artifact_message != "blob":
        errors.append(f"{label}: artifact at accepted commit is not a blob")

    tree_result, tree_message = _git_call(root_text, ("ls-tree", commit, "--", repo_path))
    if tree_result != 0:
        errors.append(f"{label}: cannot inspect accepted artifact mode: {tree_message}")
    elif tree_message and not tree_message.startswith(("100644 blob ", "100755 blob ")):
        errors.append(f"{label}: artifact at accepted commit is not a regular file")

    changed_result, changed_message = _git_call(
        root_text,
        ("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit, "--", repo_path),
    )
    if changed_result != 0:
        errors.append(f"{label}: cannot inspect accepted commit paths: {changed_message}")
    elif repo_path not in changed_message.splitlines():
        errors.append(f"{label}: artifact was not changed by accepted commit")

    if pull_request is not None:
        subject_result, subject_message = _git_call(
            root_text, ("show", "-s", "--format=%s", commit)
        )
        if subject_result != 0:
            errors.append(f"{label}: cannot inspect accepted commit subject: {subject_message}")
        elif f"(#{pull_request})" not in subject_message:
            errors.append(f"{label}: accepted commit subject does not bind PR #{pull_request}")
    return errors


def _verify_candidate_head(root: Path, candidate_ref: str) -> None:
    if not isinstance(candidate_ref, str) or HEX40.fullmatch(candidate_ref) is None:
        raise ManifestError("candidate_ref must be lowercase 40-hex")
    root_error = _git_root_error(root)
    if root_error:
        raise ManifestError(root_error)
    root_text = str(root.resolve())
    candidate_type_result, candidate_type = _git_call(root_text, ("cat-file", "-t", candidate_ref))
    if candidate_type_result != 0 or candidate_type != "commit":
        raise ManifestError("candidate_ref must identify an exact commit object, not a tag")
    candidate_result, candidate_message = _git_call(
        root_text, ("rev-parse", "--verify", candidate_ref)
    )
    if candidate_result != 0:
        raise ManifestError(f"candidate_ref does not resolve: {candidate_message}")
    head_result, head_message = _git_call(root_text, ("rev-parse", "--verify", "HEAD"))
    if head_result != 0:
        raise ManifestError(f"candidate HEAD does not resolve as a commit: {head_message}")
    if candidate_message != head_message:
        raise ManifestError(
            f"candidate_ref {candidate_message} does not equal checked-out HEAD {head_message}"
        )


def _verify_candidate_paths(
    root: Path,
    candidate_ref: str,
    paths: set[str],
    *,
    tracked_snapshot: tuple[frozenset[bytes] | None, str | None] | None = None,
    consumed_bytes: dict[str, bytes] | None = None,
) -> list[str]:
    errors: list[str] = []
    root_text = str(root.resolve())
    tracked_paths, tracked_error = (
        tracked_snapshot if tracked_snapshot is not None else _tracked_repository_paths(root)
    )
    if tracked_error:
        return [tracked_error]
    for repo_path in sorted(paths):
        current_path_error = validate_repo_path(root, repo_path, tracked_paths=tracked_paths)
        if current_path_error:
            errors.append(f"candidate input {repo_path}: {current_path_error}")
            continue
        tree_result, tree_message = _git_call(
            root_text, ("ls-tree", candidate_ref, "--", repo_path)
        )
        if tree_result != 0 or not tree_message:
            errors.append(f"candidate input {repo_path}: absent from candidate commit")
            continue
        if not tree_message.startswith(("100644 blob ", "100755 blob ")):
            errors.append(f"candidate input {repo_path}: candidate object is not a regular file")
            continue
        tree_fields = tree_message.split(maxsplit=3)
        candidate_mode = tree_fields[0]
        candidate_blob = tree_fields[2]
        index_result, index_message = _git_call(root_text, ("ls-files", "--stage", "--", repo_path))
        index_lines = index_message.splitlines() if index_result == 0 else []
        if len(index_lines) != 1:
            errors.append(f"candidate input {repo_path}: index entry is missing or unmerged")
        else:
            index_metadata, separator, index_path = index_lines[0].partition("\t")
            index_fields = index_metadata.split()
            if (
                not separator
                or index_path != repo_path
                or len(index_fields) != 3
                or index_fields[2] != "0"
                or index_fields[0] != candidate_mode
                or index_fields[1] != candidate_blob
            ):
                errors.append(f"candidate input {repo_path}: index differs from candidate commit")
        try:
            current_payload = (root / Path(*PurePosixPath(repo_path).parts)).read_bytes()
        except OSError as exc:
            errors.append(f"candidate input {repo_path}: cannot read working bytes: {exc}")
            continue
        if consumed_bytes is not None and repo_path not in consumed_bytes:
            errors.append(f"candidate input {repo_path}: consumed byte snapshot is missing")
            continue
        payload = consumed_bytes[repo_path] if consumed_bytes is not None else current_payload
        hash_result, working_blob = _git_hash_bytes(root_text, payload)
        if hash_result != 0:
            errors.append(f"candidate input {repo_path}: cannot hash working bytes: {working_blob}")
        elif working_blob != candidate_blob:
            difference = (
                "consumed bytes differ" if consumed_bytes is not None else "working tree differs"
            )
            errors.append(f"candidate input {repo_path}: {difference} from candidate commit")
        if consumed_bytes is not None:
            current_hash_result, current_blob = _git_hash_bytes(root_text, current_payload)
            if current_hash_result != 0:
                errors.append(
                    f"candidate input {repo_path}: cannot hash current working bytes: "
                    f"{current_blob}"
                )
            elif current_blob != candidate_blob:
                errors.append(
                    f"candidate input {repo_path}: working tree differs from candidate commit"
                )
    return errors


def _validate_snapshot(
    data: Any,
    *,
    root: Path,
    verify_git: bool,
    errors: list[str],
) -> str | None:
    errors.extend(_field_errors(data, SNAPSHOT_FIELDS, "evidence_snapshot"))
    if not isinstance(data, dict):
        return None
    if data.get("repository") != "andrei649/jarvis-hub":
        errors.append("evidence_snapshot.repository must be 'andrei649/jarvis-hub'")
    baseline = data.get("baseline_commit")
    if not isinstance(baseline, str) or HEX40.fullmatch(baseline) is None:
        errors.append("evidence_snapshot.baseline_commit must be lowercase 40-hex")
        baseline = None
    observed = data.get("observed_at_utc")
    observed_time: datetime | None = None
    if not isinstance(observed, str) or UTC_TIMESTAMP.fullmatch(observed) is None:
        errors.append("evidence_snapshot.observed_at_utc must be second-precision UTC")
    else:
        try:
            observed_time = datetime.strptime(observed, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            errors.append("evidence_snapshot.observed_at_utc must be a valid UTC timestamp")
    if observed_time is not None:
        if observed_time < MANIFEST_V1_NOT_BEFORE:
            errors.append("evidence_snapshot.observed_at_utc predates manifest v1")
        if observed_time > datetime.now(UTC) + timedelta(minutes=5):
            errors.append("evidence_snapshot.observed_at_utc cannot be in the future")
    if verify_git and baseline:
        root_text = str(root.resolve())
        baseline_result, baseline_type = _git_call(root_text, ("cat-file", "-t", baseline))
        if baseline_result != 0:
            errors.append(
                "evidence baseline does not resolve as an exact commit object: " + baseline_type
            )
            baseline = None
        elif baseline_type != "commit":
            errors.append("evidence baseline must identify an exact commit object")
            baseline = None
        else:
            ancestor_result, ancestor_message = _git_call(
                root_text, ("merge-base", "--is-ancestor", baseline, "HEAD")
            )
            if ancestor_result == 1:
                errors.append("evidence baseline is not an ancestor of candidate HEAD")
            elif ancestor_result != 0:
                errors.append(
                    "cannot compare evidence baseline to candidate HEAD: " + ancestor_message
                )
    if verify_git and baseline and observed_time is not None:
        result, commit_time = _git_call(root_text, ("show", "-s", "--format=%cI", baseline))
        if result != 0:
            errors.append("cannot inspect evidence baseline commit time: " + commit_time)
        else:
            try:
                baseline_time = datetime.fromisoformat(commit_time).astimezone(UTC)
            except ValueError:
                errors.append("cannot parse evidence baseline commit time")
            else:
                if observed_time < baseline_time:
                    errors.append("evidence observation predates the baseline commit")
    for field, expected in (
        ("program_issue", 757),
        ("blocker_plan_issue", 778),
        ("control_issue", 839),
    ):
        if type(data.get(field)) is not int or data.get(field) != expected:
            errors.append(f"evidence_snapshot.{field} must be #{expected}")
    if data.get("live_issue_state_verified_by_checker") is not False:
        errors.append("evidence_snapshot.live_issue_state_verified_by_checker must remain false")
    return baseline


def _validate_authority(data: Any, errors: list[str]) -> None:
    errors.extend(_field_errors(data, AUTHORITY_FIELDS, "authority"))
    if not isinstance(data, dict):
        return
    expected = {
        "status_is_evidence_label_only": True,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
        "ultron_remains_sole_action_authority": True,
    }
    for field, required in expected.items():
        if data.get(field) is not required:
            errors.append(f"authority.{field} must remain {str(required).lower()}")


def _validate_movement_registry(data: Any, errors: list[str]) -> list[str]:
    if not isinstance(data, list):
        errors.append("movement_gate.registry must be a list")
        return []
    if not all(isinstance(entry, str) for entry in data):
        errors.append("movement_gate.registry entries must be text")
        return []
    for entry in data:
        if any(character in entry for character in "*?[]{}"):
            errors.append("movement_gate.registry entry contains wildcard")
            continue
        candidate = entry[:-1] if entry.endswith("/") else entry
        if not candidate or PORTABLE_REPO_PATH.fullmatch(candidate) is None:
            errors.append("movement_gate.registry entry must be a portable repository path")
            continue
        pure = PurePosixPath(candidate)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            errors.append("movement_gate.registry entry must be a portable repository path")
        if entry.endswith("/") and len(pure.parts) < 2:
            errors.append("movement_gate.registry prefix is too broad")
    if data != sorted(data) or len(data) != len(set(data)):
        errors.append("movement_gate.registry must be sorted and unique")
    if len({entry.casefold() for entry in data}) != len(data):
        errors.append("movement_gate.registry has case-colliding entries")
    return data


def _validate_movement_gate(
    data: Any,
    *,
    root: Path,
    tracked_paths: frozenset[bytes] | None,
    errors: list[str],
) -> None:
    errors.extend(_field_errors(data, MOVEMENT_GATE_FIELDS, "movement_gate"))
    if not isinstance(data, dict):
        return
    if type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        errors.append("movement_gate.schema_version must be integer 1")
    state = data.get("enforcement_state")
    if state not in {"required", "safety_disabled"}:
        errors.append("movement_gate.enforcement_state must be required or safety_disabled")
    if data.get("bootstrap_base") != LEGACY_MOVEMENT_BASE:
        errors.append("movement_gate.bootstrap_base must match the exact legacy bootstrap")
    if data.get("branch_prefix") != MOVEMENT_BRANCH_PREFIX:
        errors.append("movement_gate.branch_prefix must be 'nerva2/'")
    if data.get("attestation_start_marker") != MOVEMENT_ATTESTATION_START:
        errors.append("movement_gate.attestation_start_marker must match the canonical marker")

    registry = _validate_movement_registry(data.get("registry"), errors)
    if state == "required":
        for required_path in sorted(REQUIRED_MOVEMENT_STATIC_PATHS):
            if required_path not in registry:
                errors.append(
                    f"movement_gate.registry must include required static path {required_path}"
                )
            else:
                path_error = validate_repo_path(root, required_path, tracked_paths=tracked_paths)
                if path_error:
                    errors.append(f"movement_gate static input {required_path}: {path_error}")

    issues = data.get("program_control_issues")
    if (
        not isinstance(issues, list)
        or not issues
        or issues[0] != 846
        or any(type(issue) is not int or issue <= 0 for issue in issues)
        or len(issues) != len(set(issues))
    ):
        errors.append("movement_gate.program_control_issues must start with sole bootstrap #846")

    receipt_control = data.get("receipt_control")
    errors.extend(
        _field_errors(
            receipt_control,
            RECEIPT_CONTROL_FIELDS,
            "movement_gate.receipt_control",
        )
    )
    if isinstance(receipt_control, dict):
        expected_receipt = {
            "mode": "point_in_time",
            "live_pr_reread_required": True,
            "fresh_exact_head_rerun_required": True,
            "fresh_owner_receipts_required": True,
            "continuous_currentness": False,
        }
        for field, expected in expected_receipt.items():
            actual = receipt_control.get(field)
            matches = actual is expected if isinstance(expected, bool) else actual == expected
            if not matches:
                errors.append(
                    f"movement_gate.receipt_control.{field} must remain {str(expected).lower()}"
                )

    manual = data.get("manual_integration")
    errors.extend(
        _field_errors(
            manual,
            MANUAL_INTEGRATION_FIELDS,
            "movement_gate.manual_integration",
        )
    )
    if isinstance(manual, dict):
        if type(manual.get("issue")) is not int or manual.get("issue") != 847:
            errors.append("movement_gate.manual_integration.issue must be #847")
        if manual.get("workflow_path") != MANUAL_INTEGRATION_WORKFLOW:
            errors.append(
                "movement_gate.manual_integration.workflow_path must pin the conductor workflow"
            )
        if manual.get("policy_test_path") != MANUAL_INTEGRATION_POLICY_TEST:
            errors.append(
                "movement_gate.manual_integration.policy_test_path must pin the conductor test"
            )

    rollback = data.get("rollback")
    if state == "required":
        if rollback is not None:
            errors.append("movement_gate.rollback must be null while enforcement is required")
    elif state == "safety_disabled":
        errors.extend(_field_errors(rollback, ROLLBACK_FIELDS, "movement_gate.rollback"))
        if isinstance(rollback, dict):
            rollback_issue = rollback.get("issue")
            if type(rollback_issue) is not int or rollback_issue <= 0:
                errors.append("movement_gate.rollback.issue must be a positive issue number")
            elif not isinstance(issues, list) or rollback_issue not in issues[1:]:
                errors.append(
                    "movement_gate.rollback.issue must be appended after bootstrap control #846"
                )
            if rollback.get("rollback_of_issue") != 846:
                errors.append("movement_gate.rollback.rollback_of_issue must be #846")
            reason = rollback.get("reason")
            if (
                not isinstance(reason, str)
                or not reason
                or len(reason.encode("utf-8", errors="ignore")) > MAX_ROLLBACK_REASON_BYTES
                or unicodedata.normalize("NFC", reason) != reason
                or any(not character.isprintable() for character in reason)
            ):
                errors.append("movement_gate.rollback.reason must be bounded printable NFC text")
            for field in ("fresh_owner_receipts_required", "exact_head_checks_required"):
                if rollback.get(field) is not True:
                    errors.append(f"movement_gate.rollback.{field} must remain true")


def _validate_reference(
    root: Path,
    reference: Any,
    label: str,
    errors: list[str],
    tracked_paths: frozenset[bytes] | None,
) -> None:
    errors.extend(_field_errors(reference, REFERENCE_FIELDS, label))
    if not isinstance(reference, dict):
        return
    kind = reference.get("kind")
    if not isinstance(kind, str) or kind not in REFERENCE_KINDS:
        errors.append(f"{label}: invalid reference kind")
        return
    value = reference.get("value")
    if kind == "issue":
        if not _positive_int(value):
            errors.append(f"{label}: issue value must be a positive integer")
    elif kind == "repo_path":
        path_error = validate_repo_path(root, value, tracked_paths=tracked_paths)
        if path_error:
            errors.append(f"{label}: repository artifact path {path_error}")


def _validate_evidence(
    root: Path,
    evidence: Any,
    label: str,
    baseline: str | None,
    verify_git: bool,
    errors: list[str],
    tracked_paths: frozenset[bytes] | None,
    allowed_claims: set[str],
) -> tuple[Any, ...] | None:
    errors.extend(_field_errors(evidence, EVIDENCE_FIELDS, label))
    if not isinstance(evidence, dict):
        return None

    commit = evidence.get("commit")
    if not isinstance(commit, str) or HEX40.fullmatch(commit) is None:
        errors.append(f"{label}: commit must be lowercase 40-hex")
    repo_path = evidence.get("repo_path")
    path_error = validate_repo_path(root, repo_path, tracked_paths=tracked_paths)
    if path_error:
        errors.append(f"{label}: repository artifact path {path_error}")
    issue = evidence.get("issue")
    if not _positive_int(issue):
        errors.append(f"{label}: issue must be a positive integer")
    pull_request = evidence.get("pull_request")
    if not _positive_int(pull_request):
        errors.append(f"{label}: pull_request must be a positive integer")
    claim = evidence.get("claim_code")
    if not isinstance(claim, str) or claim not in CLAIM_TEXT:
        errors.append(f"{label}: invalid claim_code")
    elif claim not in allowed_claims:
        errors.append(f"{label}: claim_code is not valid for this evidence context")

    valid_commit = isinstance(commit, str) and HEX40.fullmatch(commit) is not None
    valid_path = isinstance(repo_path, str) and path_error is None
    if verify_git and baseline and valid_commit and valid_path:
        errors.extend(
            _verify_git_evidence(
                root,
                baseline,
                commit,
                repo_path,
                label,
                pull_request if _positive_int(pull_request) else None,
            )
        )

    values = (commit, repo_path, issue, pull_request, claim)
    try:
        hash(values)
    except TypeError:
        return None
    return values


def _validate_blocker(
    root: Path,
    blocker: Any,
    consumer: str,
    index: int,
    errors: list[str],
    tracked_paths: frozenset[bytes] | None,
) -> tuple[str | None, str | None]:
    fallback = f"{consumer}.blockers[{index}]"
    errors.extend(_field_errors(blocker, BLOCKER_FIELDS, fallback))
    if not isinstance(blocker, dict):
        return None, None
    blocker_id = _safe_str(blocker.get("id"))
    valid_id = (
        blocker_id is not None
        and bool(blocker_id)
        and blocker_id == blocker_id.strip()
        and IDENTIFIER.fullmatch(blocker_id) is not None
    )
    label = blocker_id if valid_id else fallback
    if not valid_id:
        errors.append(f"{fallback}: id must be a portable identifier")
        blocker_id = None
    elif not blocker_id.startswith(f"{consumer}-"):
        errors.append(f"{label}: blocker id must be scoped to {consumer}")
    kind = blocker.get("kind")
    if not isinstance(kind, str) or kind not in BLOCKER_KINDS:
        errors.append(f"{label}: invalid blocker kind")
        kind = None
    target = blocker.get("target")
    valid_target = isinstance(target, str) and IDENTIFIER.fullmatch(target) is not None
    if kind == "delivery_gate":
        valid_target = valid_target and target in EXPECTED_STREAMS
    if kind is None or not valid_target:
        errors.append(f"{label}: invalid blocker target")
    reason = blocker.get("reason_code")
    if not isinstance(reason, str) or reason not in BLOCKER_REASON_TEXT:
        errors.append(f"{label}: invalid blocker reason_code")
    else:
        expected_kind, expected_target = BLOCKER_REASON_CONTRACT[reason]
        if kind != expected_kind:
            errors.append(f"{label}: reason_code requires kind '{expected_kind}'")
        if expected_target is not None and target != expected_target:
            errors.append(f"{label}: reason_code requires target '{expected_target}'")
    if blocker_id is not None and kind in BLOCKER_KIND_ID_TOKEN and valid_target:
        expected_blocker_id = f"{consumer}-{BLOCKER_KIND_ID_TOKEN[kind]}-{target}"
        if blocker_id != expected_blocker_id:
            errors.append(f"{label}: blocker id is not canonical")
    if not _positive_int(blocker.get("issue")):
        errors.append(f"{label}: issue must be a positive integer")
    path_error = validate_repo_path(root, blocker.get("artifact"), tracked_paths=tracked_paths)
    if path_error:
        errors.append(f"{label}: repository artifact path {path_error}")
    return blocker_id, kind


def _derive_eligibility(status: str, has_open_gate_or_blocker: bool) -> str:
    if status == "done":
        return "blocked" if has_open_gate_or_blocker else "satisfied"
    if status == "blocked":
        return "blocked"
    if status in {"discovery", "building", "verifying"}:
        return "in_progress"
    return "blocked" if has_open_gate_or_blocker else "eligible"


def _delivery_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = dict.fromkeys(EXPECTED_STREAMS, 0)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for source in graph.get(node, []):
            if source not in state:
                continue
            if state[source] == 0:
                found = visit(source)
                if found:
                    return found
            elif state[source] == 1:
                start = stack.index(source)
                return [*stack[start:], source]
        stack.pop()
        state[node] = 2
        return None

    for node in EXPECTED_STREAMS:
        if state[node] == 0:
            found = visit(node)
            if found:
                return found
    return None


def _registry_runtime_reference(registry: Any, errors: list[str]) -> set[tuple[str, str]]:
    """Read only the historical registry field cited by manifest drift claims."""

    if not isinstance(registry, dict):
        errors.append("registry reference root must be an object")
        return set()
    raw = registry.get("runtime_feedback_edges")
    if not isinstance(raw, list):
        errors.append("registry reference runtime_feedback_edges must be a list")
        return set()
    result: set[tuple[str, str]] = set()
    for index, item in enumerate(raw):
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
        ):
            errors.append(
                f"registry reference runtime_feedback_edges[{index}] must be a string pair"
            )
            continue
        pair = (item[0], item[1])
        if pair in result:
            errors.append(f"registry reference has duplicate runtime feedback edge {pair}")
        result.add(pair)
    return result


def _validate_stream(
    root: Path,
    stream: Any,
    expected_id: str,
    baseline: str | None,
    verify_git: bool,
    errors: list[str],
    tracked_paths: frozenset[bytes] | None,
) -> list[str]:
    errors.extend(_field_errors(stream, STREAM_FIELDS, expected_id))
    if not isinstance(stream, dict):
        return []

    stream_id = stream.get("id")
    if stream_id != expected_id:
        errors.append(f"{expected_id}: id must be '{expected_id}'")
    if stream.get("name") != EXPECTED_NAMES[expected_id]:
        errors.append(f"{expected_id}: name must match the canonical stream name")
    epic = stream.get("epic_issue")
    if type(epic) is not int or epic != EXPECTED_EPICS[expected_id]:
        errors.append(f"{expected_id}: epic_issue must be #{EXPECTED_EPICS[expected_id]}")

    status = stream.get("program_status")
    valid_status = isinstance(status, str) and status in PROGRAM_STATES
    if not valid_status:
        errors.append(f"{expected_id}: invalid program_status")

    completion_evidence = stream.get("completion_evidence")
    if not isinstance(completion_evidence, list):
        errors.append(f"{expected_id}: completion_evidence must be a list")
        completion_evidence = []
    completion_keys: set[tuple[Any, ...]] = set()
    for evidence_index, evidence in enumerate(completion_evidence):
        evidence_label = f"{expected_id}.completion_evidence[{evidence_index}]"
        key = _validate_evidence(
            root,
            evidence,
            evidence_label,
            baseline,
            verify_git,
            errors,
            tracked_paths,
            {"stream_completion_accepted", "e0_control_gate_accepted"}
            if expected_id == "E0"
            else {"stream_completion_accepted"},
        )
        if key is not None:
            if key in completion_keys:
                errors.append(f"{expected_id}: duplicate completion evidence")
            completion_keys.add(key)
    if status == "done" and not completion_evidence:
        errors.append(f"{expected_id}: done status requires immutable completion evidence")
    if status != "done" and completion_evidence:
        errors.append(f"{expected_id}: non-done status cannot carry completion evidence")

    prerequisites = stream.get("delivery_prerequisites")
    sources: list[str] = []
    edges_by_source: dict[str, dict[str, Any]] = {}
    if not isinstance(prerequisites, list):
        errors.append(f"{expected_id}: delivery_prerequisites must be a list")
        prerequisites = []
    for index, edge in enumerate(prerequisites):
        fallback = f"{expected_id}.delivery_prerequisites[{index}]"
        errors.extend(_field_errors(edge, EDGE_FIELDS, fallback))
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        if not isinstance(source, str) or source not in EXPECTED_STREAMS:
            errors.append(f"{fallback}: invalid delivery source")
            continue
        label = f"{expected_id}<-{source}"
        if source == expected_id:
            errors.append(f"{label}: delivery self-edge is forbidden")
        if source in edges_by_source:
            errors.append(f"{expected_id}: duplicate delivery prerequisite '{source}'")
        else:
            edges_by_source[source] = edge
            sources.append(source)

        gate_state = edge.get("gate_state")
        if not isinstance(gate_state, str) or gate_state not in GATE_STATES:
            errors.append(f"{label}: invalid gate_state")
        raw_evidence = edge.get("accepted_evidence")
        if not isinstance(raw_evidence, list):
            errors.append(f"{label}: accepted_evidence must be a list")
            raw_evidence = []
        evidence_keys: set[tuple[Any, ...]] = set()
        for evidence_index, evidence in enumerate(raw_evidence):
            evidence_label = f"{label}.accepted_evidence[{evidence_index}]"
            key = _validate_evidence(
                root,
                evidence,
                evidence_label,
                baseline,
                verify_git,
                errors,
                tracked_paths,
                {
                    "consumer_delivery_gate_accepted",
                    *({"e0_control_gate_accepted"} if source == "E0" else set()),
                    *(
                        {"atlas_minimum_for_episodes_accepted"}
                        if (expected_id, source) == ("E3", "E2")
                        else set()
                    ),
                    *(
                        {"episodes_minimum_for_reflection_accepted"}
                        if (expected_id, source) == ("E6", "E3")
                        else set()
                    ),
                },
            )
            if key is not None:
                if key in evidence_keys:
                    errors.append(f"{label}: duplicate accepted evidence")
                evidence_keys.add(key)
        if gate_state == "satisfied" and not raw_evidence:
            errors.append(f"{label}: satisfied gate requires immutable accepted evidence")
        if gate_state == "unsatisfied" and raw_evidence:
            errors.append(f"{label}: unsatisfied gate cannot carry accepted evidence")

    if expected_id == "E5" and sources != E5_PREREQUISITES:
        errors.append(f"E5 direct prerequisites must be exactly {E5_PREREQUISITES}")

    blockers = stream.get("blockers")
    if not isinstance(blockers, list):
        errors.append(f"{expected_id}: blockers must be a list")
        blockers = []
    blockers_by_id: dict[str, dict[str, Any]] = {}
    delivery_blockers: dict[str, list[dict[str, Any]]] = {}
    for index, blocker in enumerate(blockers):
        blocker_id, kind = _validate_blocker(
            root, blocker, expected_id, index, errors, tracked_paths
        )
        if isinstance(blocker_id, str):
            if blocker_id in blockers_by_id:
                errors.append(f"{expected_id}: duplicate blocker id '{blocker_id}'")
            elif isinstance(blocker, dict):
                blockers_by_id[blocker_id] = blocker
        if kind == "delivery_gate" and isinstance(blocker, dict):
            target = blocker.get("target")
            if isinstance(target, str):
                delivery_blockers.setdefault(target, []).append(blocker)

    for source, edge in edges_by_source.items():
        matching = delivery_blockers.get(source, [])
        if edge.get("gate_state") == "unsatisfied" and len(matching) != 1:
            errors.append(
                f"{expected_id}<-{source}: unsatisfied gate requires exactly one "
                "delivery_gate blocker"
            )
        if edge.get("gate_state") == "satisfied" and matching:
            errors.append(
                f"{expected_id}<-{source}: satisfied gate cannot also have a delivery_gate blocker"
            )
        for blocker in matching:
            blocker_id = blocker.get("id")
            if blocker_id != f"{expected_id}-delivery-{source}":
                errors.append(f"{expected_id}<-{source}: delivery blocker id is not canonical")
            if blocker.get("issue") != EXPECTED_EPICS[source]:
                errors.append(f"{expected_id}<-{source}: delivery blocker issue must match source")
            if blocker.get("artifact") != "docs/nerva2/DEPENDENCIES.md":
                errors.append(
                    f"{expected_id}<-{source}: delivery blocker artifact is not canonical"
                )
            if blocker.get("reason_code") != "upstream_gate_not_accepted":
                errors.append(f"{expected_id}<-{source}: delivery blocker reason is not canonical")
    for source in delivery_blockers:
        if source not in edges_by_source:
            errors.append(
                f"{expected_id}<-{source}: delivery_gate blocker has no matching delivery edge"
            )

    expected_blocker_ids = {
        f"{expected_id}-delivery-{source}"
        for source, edge in edges_by_source.items()
        if edge.get("gate_state") == "unsatisfied"
    }
    actual_blocker_ids = set(blockers_by_id)
    for blocker_id in sorted(expected_blocker_ids - actual_blocker_ids):
        errors.append(f"{expected_id}: missing required blocker '{blocker_id}'")

    has_open_gate = any(
        edge.get("gate_state") == "unsatisfied" for edge in edges_by_source.values()
    )
    has_cause = has_open_gate or bool(blockers)
    if status == "done" and has_cause:
        errors.append(f"{expected_id}: done status cannot retain unsatisfied gates or blockers")
    if status == "blocked" and not has_cause:
        errors.append(
            f"{expected_id}: blocked status requires an unsatisfied gate or typed blocker"
        )
    declared = stream.get("delivery_eligibility")
    valid_declared = isinstance(declared, str) and declared in DELIVERY_ELIGIBILITY
    if not valid_declared:
        errors.append(f"{expected_id}: invalid delivery_eligibility")
    if valid_status:
        derived = _derive_eligibility(status, has_cause)
        if declared != derived:
            errors.append(f"{expected_id}: delivery_eligibility must be '{derived}'")

    references = stream.get("references")
    if not isinstance(references, list):
        errors.append(f"{expected_id}: references must be a list")
        references = []
    reference_keys: set[tuple[str, Any]] = set()
    has_epic_reference = False
    has_path_reference = False
    for index, reference in enumerate(references):
        _validate_reference(
            root,
            reference,
            f"{expected_id}.references[{index}]",
            errors,
            tracked_paths,
        )
        if not isinstance(reference, dict):
            continue
        kind = reference.get("kind")
        value = reference.get("value")
        if kind == "issue" and value == EXPECTED_EPICS[expected_id]:
            has_epic_reference = True
        if kind == "repo_path" and isinstance(value, str):
            has_path_reference = True
        if isinstance(kind, str) and isinstance(value, (str, int)) and not isinstance(value, bool):
            key = (kind, value)
            if key in reference_keys:
                errors.append(f"{expected_id}: duplicate reference {key}")
            reference_keys.add(key)
    if not has_epic_reference:
        errors.append(
            f"{expected_id}: references must include epic issue #{EXPECTED_EPICS[expected_id]}"
        )
    if not has_path_reference:
        errors.append(f"{expected_id}: references must include a repository artifact")
    return sources


def _validate_runtime(
    data: Any,
    errors: list[str],
) -> set[tuple[str, str]]:
    if not isinstance(data, list):
        errors.append("runtime_feedback_edges must be a list")
        return set()
    pairs: set[tuple[str, str]] = set()
    for index, edge in enumerate(data):
        label = f"runtime_feedback_edges[{index}]"
        errors.extend(_field_errors(edge, RUNTIME_FIELDS, label))
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        consumer = edge.get("consumer")
        mode = edge.get("mode")
        if not isinstance(source, str) or source not in EXPECTED_STREAMS:
            errors.append(f"unknown runtime feedback source {source!r}")
        if not isinstance(consumer, str) or consumer not in EXPECTED_STREAMS:
            errors.append(f"unknown runtime feedback consumer {consumer!r}")
        if (
            not isinstance(mode, str)
            or IDENTIFIER.fullmatch(mode) is None
            or not mode.endswith("_advisory")
        ):
            errors.append(f"{label}: mode must be a portable advisory identifier")
        if edge.get("grants_authority") is not False:
            errors.append("runtime feedback cannot grant authority")
        if source in EXPECTED_STREAMS and consumer in EXPECTED_STREAMS:
            pair = (source, consumer)
            if pair in pairs:
                errors.append(f"duplicate runtime feedback edge {pair}")
            pairs.add(pair)
    return pairs


def _validate_drift(
    root: Path,
    data: Any,
    registry_runtime_reference: set[tuple[str, str]],
    runtime_pairs: set[tuple[str, str]],
    errors: list[str],
    tracked_paths: frozenset[bytes] | None,
    static_bytes: dict[str, bytes] | None,
) -> None:
    if not isinstance(data, list):
        errors.append("known_source_drifts must be a list")
        return
    drift_ids: set[str] = set()
    drift_pairs: set[tuple[str, str]] = set()
    for index, drift in enumerate(data):
        label = f"known_source_drifts[{index}]"
        errors.extend(_field_errors(drift, DRIFT_FIELDS, label))
        if not isinstance(drift, dict):
            continue
        edge = drift.get("edge")
        errors.extend(_field_errors(edge, DRIFT_EDGE_FIELDS, f"{label}.edge"))
        source = edge.get("source") if isinstance(edge, dict) else None
        consumer = edge.get("consumer") if isinstance(edge, dict) else None
        pair = (
            (source, consumer)
            if source in EXPECTED_STREAMS and consumer in EXPECTED_STREAMS
            else None
        )
        drift_id = drift.get("id")
        if not isinstance(drift_id, str) or IDENTIFIER.fullmatch(drift_id) is None:
            errors.append(f"{label}: id must be a portable identifier")
        elif drift_id in drift_ids:
            errors.append(f"{label}: duplicate drift id")
        else:
            drift_ids.add(drift_id)
        if drift.get("state") != "open":
            errors.append(f"{label}: state must be 'open'")
        reason_code = drift.get("reason_code")
        if not isinstance(reason_code, str) or IDENTIFIER.fullmatch(reason_code) is None:
            errors.append(f"{label}: reason_code must be a portable identifier")
        if source not in EXPECTED_STREAMS:
            errors.append(f"{label}.edge: unknown source")
        if consumer not in EXPECTED_STREAMS:
            errors.append(f"{label}.edge: unknown consumer")
        for field in ("present_in", "missing_from"):
            path_error = validate_repo_path(root, drift.get(field), tracked_paths=tracked_paths)
            if path_error:
                errors.append(f"{label}.{field}: repository artifact path {path_error}")
        if drift.get("missing_from") != REGISTRY_RELATIVE.as_posix():
            errors.append(f"{label}.missing_from must identify the contract registry")
        digest = drift.get("present_in_sha256")
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            errors.append(f"{label}.present_in_sha256 must be lowercase 64-hex")
        anchor = drift.get("present_in_anchor")
        valid_anchor = (
            isinstance(anchor, str)
            and anchor == anchor.strip()
            and 0 < len(anchor) <= 500
            and unicodedata.normalize("NFC", anchor) == anchor
            and not any(unicodedata.category(character) in {"Cc", "Cf"} for character in anchor)
        )
        if not valid_anchor:
            errors.append(f"{label}.present_in_anchor must be a safe single-line source excerpt")
        present_in = drift.get("present_in")
        if (
            isinstance(present_in, str)
            and validate_repo_path(root, present_in, tracked_paths=tracked_paths) is None
        ):
            if static_bytes is not None and present_in not in static_bytes:
                errors.append(f"{label}.present_in is missing from the consumed byte snapshot")
            else:
                try:
                    raw = (
                        static_bytes[present_in]
                        if static_bytes is not None
                        else (root / Path(*PurePosixPath(present_in).parts)).read_bytes()
                    )
                except OSError as exc:
                    errors.append(f"{label}.present_in cannot be hashed: {exc}")
                    continue
                normalized = raw.replace(b"\r\n", b"\n")
                observed_digest = hashlib.sha256(normalized).hexdigest()
                if digest != observed_digest:
                    errors.append(f"{label}.present_in_sha256 does not match source content")
                try:
                    source_text = normalized.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"{label}.present_in must be UTF-8 text")
                else:
                    if valid_anchor and source_text.count(anchor) != 1:
                        errors.append(
                            f"{label}.present_in_anchor does not occur in source content exactly once"
                        )
                    elif valid_anchor and pair is not None:
                        source_token = STREAM_SOURCE_TOKENS[source]
                        consumer_token = STREAM_SOURCE_TOKENS[consumer]
                        source_position = anchor.find(source_token)
                        consumer_position = anchor.find(consumer_token, source_position + 1)
                        if (
                            source_position < 0
                            or consumer_position < 0
                            or ">" not in anchor[source_position:consumer_position]
                        ):
                            errors.append(
                                f"{label}.present_in_anchor does not encode the declared edge"
                            )
        if pair is not None and pair in registry_runtime_reference:
            errors.append(f"stale declared runtime drift {pair}")
        if pair is not None and pair not in runtime_pairs:
            errors.append(f"declared runtime drift {pair} is absent from manifest runtime graph")
        if pair is not None:
            if pair in drift_pairs:
                errors.append(f"duplicate declared runtime drift {pair}")
            drift_pairs.add(pair)


def _validate_invariants(data: Any, errors: list[str]) -> None:
    errors.extend(_field_errors(data, INVARIANT_FIELDS, "invariants"))
    if not isinstance(data, dict):
        return
    if data.get("e5_direct_prerequisites") != E5_PREREQUISITES:
        errors.append(f"invariants.e5_direct_prerequisites must be exactly {E5_PREREQUISITES}")
    if data.get("runtime_feedback_is_not_delivery_authority") is not True:
        errors.append("invariants.runtime_feedback_is_not_delivery_authority must remain true")
    if data.get("satisfied_gate_requires_immutable_evidence") is not True:
        errors.append("invariants.satisfied_gate_requires_immutable_evidence must remain true")
    derivation = data.get("delivery_eligibility_derivation")
    errors.extend(
        _field_errors(
            derivation,
            ELIGIBILITY_DERIVATION_FIELDS,
            "invariants.delivery_eligibility_derivation",
        )
    )
    derivation_matches = isinstance(derivation, dict)
    if isinstance(derivation, dict):
        for field, expected in EXPECTED_ELIGIBILITY_DERIVATION.items():
            actual = derivation.get(field)
            if isinstance(expected, bool):
                field_matches = actual is expected
            elif isinstance(expected, list):
                field_matches = type(actual) is list and actual == expected
            else:
                field_matches = type(actual) is type(expected) and actual == expected
            derivation_matches = derivation_matches and field_matches
    if not derivation_matches:
        errors.append(
            "invariants.delivery_eligibility_derivation must match the canonical derivation rule"
        )


def validate_manifest(
    data: Any,
    *,
    root: Path,
    registry: Any,
    verify_git: bool = True,
    tracked_snapshot: tuple[frozenset[bytes] | None, str | None] | None = None,
    static_bytes: dict[str, bytes] | None = None,
) -> list[str]:
    """Return every deterministic validation error without throwing on hostile JSON types."""

    errors = _field_errors(data, ROOT_FIELDS, "root")
    if not isinstance(data, dict):
        return errors
    tracked_paths, tracked_error = (
        tracked_snapshot if tracked_snapshot is not None else _tracked_repository_paths(root)
    )
    if tracked_error:
        errors.append(tracked_error)
    if verify_git:
        root_error = _git_root_error(root)
        if root_error:
            errors.append(root_error)
            verify_git = False
    version = data.get("schema_version")
    if type(version) is not int or version != 1:
        errors.append("schema_version must be integer 1")
    if data.get("manifest_id") != "nerva.program-manifest.v1":
        errors.append("manifest_id must be 'nerva.program-manifest.v1'")

    baseline = _validate_snapshot(
        data.get("evidence_snapshot"),
        root=root,
        verify_git=verify_git,
        errors=errors,
    )
    _validate_authority(data.get("authority"), errors)
    _validate_movement_gate(
        data.get("movement_gate"),
        root=root,
        tracked_paths=tracked_paths,
        errors=errors,
    )
    registry_runtime_reference = _registry_runtime_reference(registry, errors)

    raw_streams = data.get("streams")
    graph: dict[str, list[str]] = {stream: [] for stream in EXPECTED_STREAMS}
    if not isinstance(raw_streams, list):
        errors.append("streams must be a list")
        raw_streams = []
    ids = [item.get("id") if isinstance(item, dict) else None for item in raw_streams]
    if ids != EXPECTED_STREAMS:
        errors.append(f"stream order must be exactly {EXPECTED_STREAMS}")
    for index, expected_id in enumerate(EXPECTED_STREAMS):
        if index >= len(raw_streams):
            continue
        sources = _validate_stream(
            root,
            raw_streams[index],
            expected_id,
            baseline,
            verify_git,
            errors,
            tracked_paths,
        )
        graph[expected_id] = sources
    cycle = _delivery_cycle(graph)
    if cycle:
        errors.append(f"delivery cycle: {' -> '.join(cycle)}")

    runtime_pairs = _validate_runtime(data.get("runtime_feedback_edges"), errors)
    _validate_drift(
        root,
        data.get("known_source_drifts"),
        registry_runtime_reference,
        runtime_pairs,
        errors,
        tracked_paths,
        static_bytes,
    )
    _validate_invariants(data.get("invariants"), errors)
    return errors


def _issue_link(number: int) -> str:
    return f"[#{number}](https://github.com/andrei649/jarvis-hub/issues/{number})"


def _repo_link(path: str) -> str:
    return f"[`{path}`](../../{quote(path, safe='/')})"


def _commit_link(commit: str) -> str:
    return f"[`{commit}`](https://github.com/andrei649/jarvis-hub/commit/{commit})"


def _pull_request_link(number: int) -> str:
    return f"[#{number}](https://github.com/andrei649/jarvis-hub/pull/{number})"


def _blob_link(commit: str, path: str) -> str:
    encoded = quote(path, safe="/")
    return (
        f"[`{path}` at `{commit[:12]}`]"
        f"(https://github.com/andrei649/jarvis-hub/blob/{commit}/{encoded})"
    )


def _render_evidence(evidence: dict[str, Any]) -> str:
    return (
        f"{_commit_link(evidence['commit'])} (immutable commit) · "
        f"{_issue_link(evidence['issue'])} (mutable context) · "
        f"{_pull_request_link(evidence['pull_request'])} (mutable context) · "
        f"{_blob_link(evidence['commit'], evidence['repo_path'])} (immutable blob locator) · "
        f"{CLAIM_TEXT[evidence['claim_code']]}"
    )


def _join_text(*parts: str) -> str:
    """Join wrapped prose without implicit literal concatenation."""

    return "".join(parts)


def render_markdown(data: dict[str, Any]) -> str:
    """Render only fixed prose from validated structured fields."""

    snapshot = data["evidence_snapshot"]
    gate = data["movement_gate"]
    receipt = gate["receipt_control"]
    manual = gate["manual_integration"]
    control_issues = ", ".join(_issue_link(issue) for issue in gate["program_control_issues"])
    lines = [
        "# Nerva program manifest v1",
        "",
        _join_text(
            "> Offline repository evidence snapshot. This document does not query live GitHub, ",
            "does not authorize execution, does not declare program completion, and does not ",
            "establish release readiness.",
        ),
        "",
        "- The JSON manifest is the sole current dependency/status/gate/blocker/runtime truth.",
        f"- Evidence baseline: `{snapshot['baseline_commit']}`",
        f"- Observed at (mutable snapshot context): `{snapshot['observed_at_utc']}`",
        f"- Program issue: {_issue_link(snapshot['program_issue'])}",
        f"- Blocker plan: {_issue_link(snapshot['blocker_plan_issue'])}",
        f"- Manifest control: {_issue_link(snapshot['control_issue'])}",
        "- Live issue state verified by this checker: `false`",
        "",
        "## Point-in-time issue movement gate",
        "",
        f"- Schema version: `{gate['schema_version']}`",
        f"- Enforcement state: `{gate['enforcement_state']}`",
        f"- Historical bootstrap base: `{gate['bootstrap_base']}`",
        f"- Program-control issues: {control_issues}",
        f"- Receipt proof mode: `{receipt['mode']}`; continuous currentness: `false`",
        "- The live pull request must be reread and the unchanged exact head rerun before integration.",
        (
            f"- Manual-integration guard: {_issue_link(manual['issue'])} pins "
            f"`{manual['workflow_path']}` and `{manual['policy_test_path']}`."
        ),
        "- This gate has no GitHub-write, runtime, completion, or release authority.",
        "",
        "## Program status and derived delivery eligibility",
        "",
        "| Stream | Epic | Program status | Delivery eligibility | Completion evidence |",
        "|---|---:|---|---|---|",
    ]
    for stream in data["streams"]:
        completion = (
            "<br>".join(
                _render_evidence(item)
                for item in sorted(
                    stream["completion_evidence"],
                    key=lambda item: (item["commit"], item["repo_path"], item["pull_request"]),
                )
            )
            or "—"
        )
        lines.append(
            f"| {stream['id']} — {stream['name']} | {_issue_link(stream['epic_issue'])} | "
            f"`{stream['program_status']}` | `{stream['delivery_eligibility']}` | "
            f"{completion} |"
        )

    lines.extend(
        [
            "",
            _join_text(
                "Program status describes the reviewed work snapshot. Delivery eligibility is ",
                "derived independently: active discovery/build/verification remains `in_progress`; ",
                "a consumer-specific gate may be satisfied while its source epic is still building.",
            ),
            "",
            "| Program status | Open delivery gate or typed blocker | Derived result |",
            "|---|---|---|",
            "| `not_started` | no | `eligible` |",
            "| `not_started` | yes | `blocked` |",
            "| `discovery`, `building`, or `verifying` | either | `in_progress` |",
            "| `blocked` | yes | `blocked` (no open cause is invalid) |",
            "| `done` | no | `satisfied` (an open cause is invalid) |",
            "",
            "## Delivery gates",
            "",
            "| Consumer | Source | Gate state | Commit and evidence context |",
            "|---|---|---|---|",
        ]
    )
    for stream in data["streams"]:
        for edge in stream["delivery_prerequisites"]:
            evidence_parts = []
            for evidence in sorted(
                edge["accepted_evidence"],
                key=lambda item: (item["commit"], item["repo_path"], item["pull_request"]),
            ):
                evidence_parts.append(_render_evidence(evidence))
            evidence_text = "<br>".join(evidence_parts) if evidence_parts else "—"
            lines.append(
                f"| {stream['id']} | {edge['source']} | `{edge['gate_state']}` | {evidence_text} |"
            )

    lines.extend(
        [
            "",
            _join_text(
                "A satisfied delivery edge requires an accepted 40-hex commit, an artifact present ",
                "at that commit, and mutable issue/PR context. An upstream epic's overall status is ",
                "never substituted for consumer-specific gate acceptance.",
            ),
            "",
            "## Typed blockers",
            "",
            "| Stream | Kind | Target | Evidence context | Reason |",
            "|---|---|---|---|---|",
        ]
    )
    for stream in data["streams"]:
        for blocker in sorted(stream["blockers"], key=lambda item: item["id"]):
            context = f"{_issue_link(blocker['issue'])} · {_repo_link(blocker['artifact'])}"
            lines.append(
                f"| {stream['id']} | `{blocker['kind']}` | `{blocker['target']}` | "
                f"{context} | {BLOCKER_REASON_TEXT[blocker['reason_code']]} |"
            )
    if not any(stream["blockers"] for stream in data["streams"]):
        lines.append("| — | — | — | — | — |")

    lines.extend(
        [
            "",
            "## Runtime feedback — advisory only",
            "",
            "| Source | Consumer | Mode | Grants authority |",
            "|---|---|---|---|",
        ]
    )
    for edge in sorted(
        data["runtime_feedback_edges"],
        key=lambda item: (item["source"], item["consumer"], item["mode"]),
    ):
        lines.append(
            f"| {edge['source']} | {edge['consumer']} | `{edge['mode']}` | "
            f"`{str(edge['grants_authority']).lower()}` |"
        )

    lines.extend(["", "## Known source drift", ""])
    for drift in sorted(data["known_source_drifts"], key=lambda item: item["id"]):
        edge = drift["edge"]
        lines.append(
            f"- `{drift['id']}` is `{drift['state']}`: `{edge['source']} -> "
            f"{edge['consumer']}` appears in {_repo_link(drift['present_in'])} but is absent "
            f"from {_repo_link(drift['missing_from'])}; normalized source SHA-256 "
            f"`{drift['present_in_sha256']}`."
        )

    lines.extend(
        [
            "",
            "## Authority and integrity boundary",
            "",
            "- This snapshot is evidence-only and cannot authorize or execute actions.",
            "- Ultron remains the sole privileged-action authority.",
            "- Runtime feedback is advisory and never becomes delivery or action authority.",
            "- `done` and `satisfied` are repository-evidence labels, not owner-live or release proof.",
            _join_text(
                "- Release readiness remains `false`; typed owner-live, program, and external blockers ",
                "remain visible above when present.",
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _validate_output_target(root: Path, path: Path) -> str | None:
    try:
        root_resolved = root.resolve(strict=True)
        expected = root_resolved / DOCUMENT_RELATIVE
        if path.absolute() != expected.absolute():
            return "generated Markdown target is not the canonical repository path"
        cursor = root_resolved
        for part in DOCUMENT_RELATIVE.parent.parts:
            cursor /= part
            if cursor.is_symlink():
                return "generated Markdown parent must not traverse symlink components"
        parent = expected.parent.resolve(strict=True)
        parent.relative_to(root_resolved)
        if not parent.is_dir():
            return "generated Markdown parent must be a directory"
        if expected.is_symlink():
            return "generated Markdown target must not be a symlink"
        if expected.exists() and not expected.is_file():
            return "generated Markdown target must be a regular file"
    except (OSError, RuntimeError, ValueError) as exc:
        return f"generated Markdown target is unsafe: {exc}"
    return None


def _atomic_write(root: Path, path: Path, payload: bytes) -> None:
    target_error = _validate_output_target(root, path)
    if target_error:
        raise ManifestError(target_error)
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as exc:
        raise ManifestError(f"cannot create generated Markdown temporary file: {exc}") from exc
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        target_error = _validate_output_target(root, path)
        if target_error:
            raise ManifestError(target_error)
        os.replace(temporary, path)
    except (ManifestError, OSError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            if isinstance(exc, ManifestError):
                raise
            raise ManifestError(f"cannot update generated Markdown: {exc}") from exc


def manifest_static_paths(data: dict[str, Any]) -> set[str]:
    """Return every repository file whose bytes can affect validation or rendering."""

    paths = set(CONTROL_RELATIVE_PATHS)
    movement_gate = data.get("movement_gate")
    if isinstance(movement_gate, dict) and movement_gate.get("enforcement_state") == "required":
        paths.update(REQUIRED_MOVEMENT_STATIC_PATHS)
    for stream in data["streams"]:
        for evidence in stream["completion_evidence"]:
            paths.add(evidence["repo_path"])
        for edge in stream["delivery_prerequisites"]:
            for evidence in edge["accepted_evidence"]:
                paths.add(evidence["repo_path"])
        for blocker in stream["blockers"]:
            paths.add(blocker["artifact"])
        for reference in stream["references"]:
            if reference["kind"] == "repo_path":
                paths.add(reference["value"])
    for drift in data["known_source_drifts"]:
        paths.add(drift["present_in"])
        paths.add(drift["missing_from"])
    return paths


def _snapshot_static_inputs(
    root: Path,
    paths: set[str],
    *,
    manifest_raw: bytes,
    registry_raw: bytes,
    tracked_paths: frozenset[bytes] | None,
) -> dict[str, bytes]:
    snapshots = {
        MANIFEST_RELATIVE.as_posix(): manifest_raw,
        REGISTRY_RELATIVE.as_posix(): registry_raw,
    }
    for repo_path in sorted(paths - set(snapshots)):
        path_error = validate_repo_path(root, repo_path, tracked_paths=tracked_paths)
        if path_error:
            raise ManifestError(f"candidate input {repo_path}: {path_error}")
        path = root / Path(*PurePosixPath(repo_path).parts)
        try:
            snapshots[repo_path] = path.read_bytes()
        except OSError as exc:
            raise ManifestError(f"cannot snapshot candidate input {repo_path}: {exc}") from exc
    return snapshots


def run(
    root: Path,
    *,
    write: bool,
    verify_git: bool = True,
    candidate_ref: str | None = None,
) -> list[str]:
    if write and candidate_ref is not None:
        raise ManifestError("candidate_ref is check-only and cannot be combined with --write")
    manifest_path = root / MANIFEST_RELATIVE
    registry_path = root / REGISTRY_RELATIVE
    document_path = root / DOCUMENT_RELATIVE
    if candidate_ref is not None:
        _verify_candidate_head(root, candidate_ref)
    tracked_snapshot = _tracked_repository_paths(root)
    tracked_paths, tracked_error = tracked_snapshot
    data, manifest_raw = _load_json_strict_with_bytes(manifest_path)
    registry, registry_raw = _load_json_strict_with_bytes(registry_path)
    static_bytes: dict[str, bytes] | None = None
    if candidate_ref is not None:
        structural_errors = validate_manifest(
            data,
            root=root,
            registry=registry,
            verify_git=False,
            tracked_snapshot=tracked_snapshot,
        )
        if structural_errors:
            raise ManifestError("manifest validation failed:\n- " + "\n- ".join(structural_errors))
        if tracked_error:
            raise ManifestError(tracked_error)
        static_bytes = _snapshot_static_inputs(
            root,
            manifest_static_paths(data),
            manifest_raw=manifest_raw,
            registry_raw=registry_raw,
            tracked_paths=tracked_paths,
        )
    errors = validate_manifest(
        data,
        root=root,
        registry=registry,
        verify_git=verify_git,
        tracked_snapshot=tracked_snapshot,
        static_bytes=static_bytes,
    )
    if errors:
        raise ManifestError("manifest validation failed:\n- " + "\n- ".join(errors))
    if candidate_ref is not None:
        candidate_errors = _verify_candidate_paths(
            root,
            candidate_ref,
            manifest_static_paths(data),
            tracked_snapshot=tracked_snapshot,
            consumed_bytes=static_bytes,
        )
        if candidate_errors:
            raise ManifestError(
                "candidate input validation failed:\n- " + "\n- ".join(candidate_errors)
            )
    try:
        rendered = render_markdown(data).encode("utf-8")
    except (KeyError, TypeError, UnicodeError) as exc:
        raise ManifestError(f"cannot render validated manifest: {exc}") from exc
    target_error = _validate_output_target(root, document_path)
    if target_error:
        raise ManifestError(target_error)
    try:
        existing = (
            static_bytes.get(DOCUMENT_RELATIVE.as_posix())
            if static_bytes is not None
            else (document_path.read_bytes() if document_path.exists() else None)
        )
    except OSError as exc:
        raise ManifestError(f"cannot read generated Markdown: {exc}") from exc
    messages = ["program manifest valid"]
    if write:
        if existing == rendered:
            messages.append("generated Markdown already current")
        else:
            _atomic_write(root, document_path, rendered)
            messages.append("generated Markdown updated")
    elif existing != rendered:
        raise ManifestError(
            "generated Markdown drift; run scripts/check_nerva_program_manifest.py --write"
        )
    else:
        messages.append("generated Markdown current")
    if candidate_ref is not None:
        _verify_candidate_head(root, candidate_ref)
    return messages


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate without modifying files")
    mode.add_argument("--write", action="store_true", help="atomically refresh generated Markdown")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root",
    )
    parser.add_argument(
        "--candidate-ref",
        help="exact lowercase 40-hex commit that must equal checked-out HEAD",
    )
    return parser.parse_args(argv)


def _safe_error_text(value: object) -> str:
    text = str(value)
    controls_escaped = "".join(
        character
        if character == "\n" or not (ord(character) < 32 or 127 <= ord(character) <= 159)
        else f"\\x{ord(character):02x}"
        for character in text
    )
    encoding = sys.stderr.encoding or "utf-8"
    return controls_escaped.encode(encoding, errors="backslashreplace").decode(encoding)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        root = args.root.resolve()
        messages = run(
            root,
            write=args.write,
            verify_git=True,
            candidate_ref=args.candidate_ref,
        )
    except (ManifestError, OSError, RuntimeError, ValueError) as exc:
        print(_safe_error_text(exc), file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
