#!/usr/bin/env python3
"""Fail-closed, bounded validator for Nerva issue-movement evidence.

This module deliberately keeps untrusted event, diff and receipt input as data.
Network and exact-head orchestration are layered on top of these pure helpers.
"""

from __future__ import annotations

# The gate contract requires a fixed-argument Git diff subprocess.
import argparse
import hashlib
import json
import math
import re
import subprocess  # nosec B404
import sys
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEGACY_BASE = "843918848c11bbd3f0099f9504d0e0eaaa56b9d6"
MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
END_MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
RECEIPT_MARKER = "<!-- NERVA2:MOVEMENT-RECEIPT:START -->"
RECEIPT_END_MARKER = "<!-- NERVA2:MOVEMENT-RECEIPT:END -->"
MAX_JSON_BYTES = 65_536
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 1_024
MAX_DIFF_BYTES = 1_048_576
MAX_DIFF_RECORDS = 4_096
BRANCH_PREFIX = "nerva2/"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REGISTERED = frozenset(
    {
        ".github/workflows/ci.yml",
        ".github/workflows/nerva-roadmap.yml",
        "BACKLOG.md",
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json",
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md",
        "scripts/check_nerva_issue_movement.py",
        "scripts/check_nerva_program_manifest.py",
        "tests/test_nerva_issue_movement.py",
        "tests/test_nerva_program_manifest.py",
    }
)
BOOTSTRAP_REGISTRY = tuple(sorted(REGISTERED))


class MovementError(ValueError):
    """A bounded, safe-to-report rejection reason."""


@dataclass(frozen=True)
class PureProof:
    status: str
    scope: dict[str, Any]


def _reject(message: str) -> None:
    raise MovementError(message)


def _is_safe_text(value: str) -> bool:
    return unicodedata.normalize("NFC", value) == value and all(
        character.isprintable() and ord(character) != 0x7F for character in value
    )


def _validate_json_tree(
    value: Any, *, depth: int, item_count: list[int], max_depth: int, max_items: int
) -> None:
    if depth > max_depth:
        _reject("JSON nesting exceeds limit")
    item_count[0] += 1
    if item_count[0] > max_items:
        _reject("JSON item count exceeds limit")
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            _reject("JSON has non-finite number")
        return
    if isinstance(value, str):
        if not _is_safe_text(value):
            _reject("JSON contains ambiguous text")
        return
    if isinstance(value, list):
        for child in value:
            _validate_json_tree(
                child,
                depth=depth + 1,
                item_count=item_count,
                max_depth=max_depth,
                max_items=max_items,
            )
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not _is_safe_text(key):
                _reject("JSON contains invalid key")
            _validate_json_tree(
                child,
                depth=depth + 1,
                item_count=item_count,
                max_depth=max_depth,
                max_items=max_items,
            )
        return
    _reject("JSON contains unsupported value")


def strict_json(
    raw: str | bytes,
    *,
    max_bytes: int = MAX_JSON_BYTES,
    max_depth: int = MAX_JSON_DEPTH,
    max_items: int = MAX_JSON_ITEMS,
) -> Any:
    """Load bounded UTF-8 JSON while rejecting duplicate and non-finite values."""
    if isinstance(raw, bytes):
        if len(raw) > max_bytes:
            _reject("JSON exceeds byte limit")
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise MovementError("JSON is not valid UTF-8") from exc
    elif isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise MovementError("JSON is not valid UTF-8") from exc
        if len(encoded) > max_bytes:
            _reject("JSON exceeds byte limit")
        text = raw
    else:
        _reject("JSON input must be text")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                _reject("JSON has duplicate key")
            output[key] = value
        return output

    def reject_constant(_: str) -> None:
        _reject("JSON has non-finite number")

    try:
        value = json.loads(text, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError, UnicodeError, ValueError) as exc:
        raise MovementError("JSON is malformed") from exc
    try:
        _validate_json_tree(
            value,
            depth=0,
            item_count=[0],
            max_depth=max_depth,
            max_items=max_items,
        )
    except RecursionError as exc:
        raise MovementError("JSON nesting exceeds limit") from exc
    return value


def _closed_object(
    value: Any, *, allowed_keys: set[str], required_keys: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject("JSON object required")
    if set(value) - allowed_keys:
        _reject("JSON object has unknown field")
    if required_keys and not required_keys <= set(value):
        _reject("JSON object misses required field")
    return value


def parse_marker_json(
    body: str | bytes,
    start_marker: str,
    end_marker: str,
    *,
    allowed_keys: set[str],
    required_keys: set[str] | None = None,
    max_body_bytes: int = MAX_JSON_BYTES * 2,
) -> dict[str, Any]:
    """Extract exactly one complete marker block and load its closed-world object."""
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise MovementError("marked body is not valid UTF-8") from exc
    elif isinstance(body, str):
        text = body
    else:
        _reject("marked body must be text")
    try:
        if len(text.encode("utf-8", "strict")) > max_body_bytes:
            _reject("marked body exceeds byte limit")
    except UnicodeEncodeError as exc:
        raise MovementError("marked body is not valid UTF-8") from exc
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        _reject("marker must appear exactly once")
    start = text.find(start_marker) + len(start_marker)
    end = text.find(end_marker)
    if end < start:
        _reject("marker order is invalid")
    return _closed_object(
        strict_json(text[start:end]), allowed_keys=allowed_keys, required_keys=required_keys
    )


def _validate_repo_path(path: str, *, prefix_allowed: bool = False) -> None:
    if not isinstance(path, str) or not path or not _is_safe_text(path):
        _reject("repository path is invalid")
    is_prefix = path.endswith("/")
    if is_prefix and not prefix_allowed:
        _reject("repository path must name a file")
    if path.startswith(("/", "\\")) or "\\" in path or ":" in path or "//" in path:
        _reject("repository path is not portable")
    components = path.rstrip("/").split("/")
    if not components or any(component in {"", ".", ".."} for component in components):
        _reject("repository path traverses outside repository")


def parse_diff(
    raw: bytes, *, max_bytes: int = MAX_DIFF_BYTES, max_records: int = MAX_DIFF_RECORDS
) -> list[tuple[str, str]]:
    """Decode only the fixed `git diff --name-status --no-renames -z` format."""
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        _reject("diff exceeds byte limit")
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        _reject("diff is not NUL terminated")
    records = raw[:-1].split(b"\0")
    if len(records) % 2 or len(records) // 2 > max_records:
        _reject("diff has too many records")
    seen_casefolded: set[str] = set()
    parsed: list[tuple[str, str]] = []
    for index in range(0, len(records), 2):
        status, encoded_path = records[index : index + 2]
        if status not in {b"A", b"M", b"D"} or not encoded_path:
            _reject("diff status is invalid")
        try:
            path = encoded_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise MovementError("diff path is not valid UTF-8") from exc
        _validate_repo_path(path)
        folded = path.casefold()
        if folded in seen_casefolded:
            _reject("diff has case-colliding path")
        seen_casefolded.add(folded)
        parsed.append((status.decode("ascii"), path))
    return parsed


def _registry_covers(entry: str, path: str) -> bool:
    return path.startswith(entry) if entry.endswith("/") else path == entry


def _validate_registry(registry: Iterable[str]) -> list[str]:
    if isinstance(registry, (str, bytes)):
        _reject("registry must be a list")
    entries = list(registry)
    if not all(isinstance(entry, str) for entry in entries):
        _reject("registry entry must be text")
    for entry in entries:
        _validate_repo_path(entry, prefix_allowed=True)
        if any(character in entry for character in "*?[]{}"):
            _reject("registry entry contains wildcard")
        if entry.endswith("/") and len(entry.rstrip("/").split("/")) < 2:
            _reject("registry prefix is too broad")
    if entries != sorted(entries) or len(entries) != len(set(entries)):
        _reject("registry must be sorted and unique")
    folded = [entry.casefold() for entry in entries]
    if len(folded) != len(set(folded)):
        _reject("registry has case-colliding entry")
    return entries


def validate_registry_evolution(
    baseline_registry: Iterable[str], candidate_registry: Iterable[str], added_paths: set[str]
) -> None:
    """Require append-only classifier coverage and proof for each new entry."""
    baseline = _validate_registry(baseline_registry)
    candidate = _validate_registry(candidate_registry)
    if not set(baseline) <= set(candidate):
        _reject("candidate registry removes baseline coverage")
    for path in added_paths:
        _validate_repo_path(path)
    for entry in set(candidate) - set(baseline):
        if not any(_registry_covers(entry, path) for path in added_paths):
            _reject("new registry entry does not cover same-PR addition")


def classify(
    branch: str,
    body: str,
    paths: list[str],
    *,
    manifest_changed: bool = False,
    baseline_registry: Iterable[str] | None = None,
    candidate_registry: Iterable[str] | None = None,
) -> bool:
    """Return deterministic Nerva classification after caller has validated the diff."""
    if not isinstance(branch, str) or not isinstance(body, str):
        _reject("classification input must be text")
    if not all(isinstance(path, str) for path in paths):
        _reject("classification paths must be text")
    for path in paths:
        _validate_repo_path(path)
    registry = set(REGISTERED)
    if baseline_registry is not None:
        registry.update(_validate_registry(baseline_registry))
    if candidate_registry is not None:
        registry.update(_validate_registry(candidate_registry))
    return (
        branch.startswith(BRANCH_PREFIX)
        or MARKER in body
        or manifest_changed
        or any(
            path.startswith("docs/nerva2/")
            or any(_registry_covers(entry, path) for entry in registry)
            for path in paths
        )
    )


def validate_manifest_gate(manifest: Mapping[str, Any], base: str) -> None:
    """Validate only the movement-gate shape required by this pure layer."""
    if not isinstance(manifest, Mapping) or not isinstance(base, str):
        _reject("manifest gate input is invalid")
    gate = manifest.get("movement_gate")
    if gate is None:
        if base == LEGACY_BASE:
            return
        _reject("movement gate is required")
    allowed = {
        "schema_version",
        "enforcement_state",
        "bootstrap_base",
        "registry",
        "program_control_issues",
        "continuous_currentness",
        "live_receipt_control",
    }
    gate = _closed_object(gate, allowed_keys=allowed)
    if type(gate.get("schema_version")) is not int or gate["schema_version"] != 1:
        _reject("movement gate schema is invalid")
    if gate.get("enforcement_state") not in {"required", "safety_disabled"}:
        _reject("movement gate enforcement state is invalid")
    if gate.get("bootstrap_base") != LEGACY_BASE:
        _reject("movement gate bootstrap base is invalid")
    registry = gate.get("registry")
    if not isinstance(registry, list):
        _reject("movement gate registry is invalid")
    _validate_registry(registry)
    if base == LEGACY_BASE and tuple(registry) != BOOTSTRAP_REGISTRY:
        _reject("legacy bootstrap registry does not match pinned seed")
    issues = gate.get("program_control_issues")
    if (
        not isinstance(issues, list)
        or any(type(issue) is not int or issue <= 0 for issue in issues)
        or len(issues) != len(set(issues))
    ):
        _reject("movement control issues are invalid")
    if base == LEGACY_BASE and (
        set(gate) != allowed
        or gate["enforcement_state"] != "required"
        or gate["program_control_issues"] != [846]
        or gate["continuous_currentness"] is not False
        or gate["live_receipt_control"] is not True
    ):
        _reject("legacy bootstrap gate is not canonical")


def compute_name_status_diff(
    base: str,
    head: str,
    *,
    git: str = "git",
    cwd: Path | None = None,
    popen_factory: Any = subprocess.Popen,
    timeout_seconds: float = 20,
) -> list[tuple[str, str]]:
    """Run the only accepted diff command; arguments are never built from shell text."""
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        _reject("diff commit is invalid")
    raw_parts: list[bytes] = []
    reader_error: list[BaseException] = []
    oversized = threading.Event()

    def read_stdout(stream: Any) -> None:
        try:
            total = 0
            while True:
                chunk = stream.read(8_192)
                if not chunk:
                    return
                total += len(chunk)
                if total > MAX_DIFF_BYTES:
                    oversized.set()
                    return
                raw_parts.append(chunk)
        except BaseException as exc:  # The caller reports a fixed safe failure.
            reader_error.append(exc)

    try:
        process = popen_factory(
            [git, "diff", "--name-status", "--no-renames", "-z", base, head, "--"],
            shell=False,
            cwd=cwd,
            env={"PATH": str(Path(git).parent) if Path(git).parent != Path(".") else ""},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:
            _reject("cannot compute repository diff")
        reader = threading.Thread(target=read_stdout, args=(process.stdout,), daemon=True)
        reader.start()
        reader.join(timeout=timeout_seconds)
        timed_out = reader.is_alive()
        if timed_out or oversized.is_set():
            process.kill()
            reader.join(timeout=timeout_seconds)
            process.wait(timeout=timeout_seconds)
            _reject("diff read timed out" if timed_out else "diff exceeds byte limit")
        if reader_error:
            _reject("cannot compute repository diff")
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=timeout_seconds)
            raise MovementError("diff read timed out") from exc
        if exit_code != 0:
            _reject("cannot compute repository diff")
    except subprocess.TimeoutExpired as exc:
        raise MovementError("diff read timed out") from exc
    except (AttributeError, OSError, subprocess.SubprocessError) as exc:
        raise MovementError("cannot compute repository diff") from exc
    return parse_diff(b"".join(raw_parts))


def _event_context(event: Any) -> tuple[str, int, str, str, str, str, bool]:
    if not isinstance(event, dict):
        _reject("event must be an object")
    repository = event.get("repository")
    pull_request = event.get("pull_request")
    if not isinstance(repository, dict) or not isinstance(pull_request, dict):
        _reject("event pull request is invalid")
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        _reject("event pull request refs are invalid")
    repository_name = repository.get("full_name")
    number = pull_request.get("number")
    base_sha, head_sha, branch = base.get("sha"), head.get("sha"), head.get("ref")
    body = pull_request.get("body")
    draft = pull_request.get("draft")
    if body is None:
        body = ""
    if (
        not all(
            isinstance(value, str) for value in (repository_name, base_sha, head_sha, branch, body)
        )
        or type(number) is not int
        or number <= 0
        or type(draft) is not bool
        or not SHA_RE.fullmatch(base_sha)
        or not SHA_RE.fullmatch(head_sha)
        or not _is_safe_text(branch)
    ):
        _reject("event pull request values are invalid")
    return repository_name, number, base_sha, head_sha, branch, body, draft


def _fetch_current_snapshot(
    transport: Any,
    *,
    repository: str,
    number: int,
    base: str,
    head: str,
) -> tuple[str, str, bool, dict[str, Any]]:
    """Fetch current PR before any classifier may observe stale event fields."""
    if transport is None:
        _reject("movement proof requires offline snapshot transport")
    try:
        current = transport("pull_request")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise MovementError("offline pull request snapshot is unavailable") from exc
    if not isinstance(current, dict) or current.get("state") != "open":
        _reject("current pull request is not open")
    current_repo, current_base, current_head = (
        current.get("repository"),
        current.get("base"),
        current.get("head"),
    )
    body, draft = current.get("body"), current.get("draft")
    if (
        type(current.get("number")) is not int
        or current.get("number") != number
        or not isinstance(current_repo, dict)
        or current_repo.get("full_name") != repository
        or not isinstance(current_base, dict)
        or current_base.get("sha") != base
        or not isinstance(current_head, dict)
        or current_head.get("sha") != head
        or not isinstance(current_head.get("ref"), str)
        or not _is_safe_text(current_head["ref"])
        or not isinstance(body, str)
        or type(draft) is not bool
    ):
        _reject("current pull request does not bind event")
    return current_head["ref"], body, draft, current


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def derive_scope(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Derive one closed-world program-control or stream movement from manifest data."""
    candidate_gate = candidate.get("movement_gate")
    if not isinstance(candidate_gate, dict):
        _reject("candidate movement gate is missing")
    baseline_gate = baseline.get("movement_gate")
    if baseline_gate is None:
        if any(
            key != "movement_gate" and not _same_json(baseline.get(key), candidate.get(key))
            for key in set(baseline) | set(candidate)
        ):
            _reject("legacy bootstrap changes non-gate manifest data")
        previous_issues: list[int] = []
    else:
        if not isinstance(baseline_gate, dict):
            _reject("baseline movement gate is invalid")
        previous_issues = baseline_gate.get("program_control_issues", [])
        if not isinstance(previous_issues, list):
            _reject("baseline control issues are invalid")
        mutable_gate_fields = {"registry", "program_control_issues"}
        if any(
            key not in mutable_gate_fields
            and not _same_json(baseline_gate.get(key), candidate_gate.get(key))
            for key in set(baseline_gate) | set(candidate_gate)
        ):
            _reject("movement gate changes immutable control")
    candidate_issues = candidate_gate.get("program_control_issues")
    if (
        not isinstance(candidate_issues, list)
        or candidate_issues[: len(previous_issues)] != previous_issues
    ):
        _reject("program control history is not append-only")
    added_issues = candidate_issues[len(previous_issues) :]
    if any(
        type(issue) is not int or issue <= 0 or issue in previous_issues for issue in added_issues
    ):
        _reject("program control issue is invalid")
    root_delivery_same = all(
        key == "movement_gate" or _same_json(baseline.get(key), candidate.get(key))
        for key in set(baseline) | set(candidate)
    )
    if len(added_issues) == 1 and root_delivery_same:
        return {
            "kind": "program_control",
            "implementation_issue": added_issues[0],
            "stream_id": None,
            "epic_issue": None,
        }
    streams_before, streams_after = baseline.get("streams"), candidate.get("streams")
    if not isinstance(streams_before, list) or not isinstance(streams_after, list):
        _reject("movement scope is ambiguous")
    if added_issues:
        _reject("stream movement changes program-control issue history")
    for key in set(baseline) | set(candidate):
        if key not in {"movement_gate", "streams"} and not _same_json(
            baseline.get(key), candidate.get(key)
        ):
            _reject("stream movement changes unrelated manifest data")
    if len(streams_before) != len(streams_after):
        _reject("movement scope is ambiguous")
    changed = [
        index
        for index, (before, after) in enumerate(zip(streams_before, streams_after, strict=True))
        if not _same_json(before, after)
    ]
    if len(changed) != 1:
        _reject("movement scope is ambiguous")
    before, after = streams_before[changed[0]], streams_after[changed[0]]
    if not isinstance(before, dict) or not isinstance(after, dict):
        _reject("stream movement is invalid")
    if any(before.get(field) != after.get(field) for field in ("id", "name", "epic_issue")):
        _reject("stream identity is not immutable")
    for field in ("references", "completion_evidence", "blockers"):
        before_history, after_history = before.get(field, []), after.get(field, [])
        if not isinstance(before_history, list) or not isinstance(after_history, list):
            _reject("stream history is invalid")
        if len(after_history) < len(before_history) or any(
            not _same_json(previous, observed)
            for previous, observed in zip(before_history, after_history, strict=False)
        ):
            _reject("stream history is not append-only")
    before_prerequisites = before.get("delivery_prerequisites", [])
    after_prerequisites = after.get("delivery_prerequisites", [])
    if (
        not isinstance(before_prerequisites, list)
        or not isinstance(after_prerequisites, list)
        or len(after_prerequisites) < len(before_prerequisites)
    ):
        _reject("stream prerequisite history is invalid")
    for previous, observed in zip(before_prerequisites, after_prerequisites, strict=False):
        if not isinstance(previous, dict) or not isinstance(observed, dict):
            _reject("stream prerequisite history is invalid")
        previous_without_evidence = {
            key: value for key, value in previous.items() if key != "accepted_evidence"
        }
        observed_without_evidence = {
            key: value for key, value in observed.items() if key != "accepted_evidence"
        }
        if not _same_json(previous_without_evidence, observed_without_evidence):
            _reject("stream prerequisite is rewritten")
        old_evidence = previous.get("accepted_evidence", [])
        new_evidence = observed.get("accepted_evidence", [])
        if (
            not isinstance(old_evidence, list)
            or not isinstance(new_evidence, list)
            or len(new_evidence) < len(old_evidence)
            or any(
                not _same_json(old, new)
                for old, new in zip(old_evidence, new_evidence, strict=False)
            )
        ):
            _reject("prerequisite accepted evidence is not append-only")
    if before.get("program_status") == "building" and after.get("program_status") == "done":
        _reject("stream status cannot move from building to done")
    stream_id, epic = after.get("id"), after.get("epic_issue")
    if not isinstance(stream_id, str) or type(epic) is not int:
        _reject("stream scope is invalid")

    def issue_values(value: Any) -> set[int]:
        if isinstance(value, list):
            return set().union(*(issue_values(item) for item in value)) if value else set()
        if not isinstance(value, dict):
            return set()
        values = {
            child
            for key, child in value.items()
            if key == "issue" and type(child) is int and child > 0
        }
        references = value.get("references")
        if isinstance(references, list):
            values.update(
                item["value"]
                for item in references
                if isinstance(item, dict)
                and item.get("kind") == "issue"
                and type(item.get("value")) is int
                and item["value"] > 0
            )
        for key, child in value.items():
            if key != "references":
                values.update(issue_values(child))
        return values

    new_issue_values = issue_values(after) - issue_values(before)
    if len(new_issue_values) != 1:
        _reject("stream movement must introduce exactly one issue")
    implementation_issue = next(iter(new_issue_values))
    return {
        "kind": "stream",
        "implementation_issue": implementation_issue,
        "stream_id": stream_id,
        "epic_issue": epic,
    }


def validate_stream_evidence_bindings(
    baseline_stream: Mapping[str, Any], candidate_stream: Mapping[str, Any], *, pull_request: int
) -> None:
    """Require all newly appended stream evidence to bind the current pull request."""
    if type(pull_request) is not int or pull_request <= 0:
        _reject("current pull request is invalid")

    def appended(before: Any, after: Any) -> list[Any]:
        if not isinstance(before, list) or not isinstance(after, list) or len(after) < len(before):
            _reject("stream evidence history is invalid")
        return after[len(before) :]

    evidence = appended(
        baseline_stream.get("completion_evidence", []),
        candidate_stream.get("completion_evidence", []),
    )
    before_edges = baseline_stream.get("delivery_prerequisites", [])
    after_edges = candidate_stream.get("delivery_prerequisites", [])
    new_edges = appended(before_edges, after_edges)
    for before_edge, after_edge in zip(before_edges, after_edges, strict=False):
        if not isinstance(before_edge, Mapping) or not isinstance(after_edge, Mapping):
            _reject("stream prerequisite is invalid")
        evidence.extend(
            appended(
                before_edge.get("accepted_evidence", []), after_edge.get("accepted_evidence", [])
            )
        )
    for edge in new_edges:
        if not isinstance(edge, Mapping):
            _reject("stream prerequisite is invalid")
        accepted = edge.get("accepted_evidence", [])
        if not isinstance(accepted, list):
            _reject("stream prerequisite evidence is invalid")
        evidence.extend(accepted)
    for record in evidence:
        if (
            not isinstance(record, Mapping)
            or type(record.get("issue")) is not int
            or record["issue"] <= 0
            or type(record.get("pull_request")) is not int
            or record["pull_request"] <= 0
            or record["pull_request"] != pull_request
        ):
            _reject("new stream evidence does not bind current pull request")


def _require_false(data: Mapping[str, Any]) -> None:
    for key in ("can_authorize", "can_execute", "completion_authority", "release_ready"):
        if data.get(key) is not False:
            _reject("authority claim must be false")


def _validate_role_map(roles: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    required = {"program", "blocker", "implementation"}
    if scope["kind"] == "stream":
        required.add("epic")
    roles = _closed_object(roles, allowed_keys=required, required_keys=required)
    ids: set[int] = set()
    for value in roles.values():
        entry = _closed_object(
            value,
            allowed_keys={"comment_id", "comment_body_sha256", "updated_at"},
            required_keys={"comment_id", "comment_body_sha256", "updated_at"},
        )
        if (
            type(entry["comment_id"]) is not int
            or entry["comment_id"] <= 0
            or not isinstance(entry["updated_at"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["comment_body_sha256"])
            or entry["comment_id"] in ids
        ):
            _reject("attestation role map is invalid")
        ids.add(entry["comment_id"])
    return roles


def _validate_attestation(
    body: str,
    *,
    repository: str,
    number: int,
    base: str,
    head: str,
    digest: str,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "movement_kind",
        "repository",
        "pull_request",
        "base_sha",
        "head_sha",
        "manifest_sha256",
        "program_issue",
        "blocker_issue",
        "implementation_issue",
        "roles",
        "can_authorize",
        "can_execute",
        "completion_authority",
        "release_ready",
    }
    if scope["kind"] == "stream":
        allowed.update({"stream_id", "epic_issue"})
    data = parse_marker_json(body, MARKER, END_MARKER, allowed_keys=allowed, required_keys=allowed)
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["movement_kind"] != scope["kind"]
        or data["repository"] != repository
        or type(data["pull_request"]) is not int
        or data["pull_request"] != number
        or data["base_sha"] != base
        or data["head_sha"] != head
        or data["manifest_sha256"] != digest
        or type(data["program_issue"]) is not int
        or data["program_issue"] != 757
        or type(data["blocker_issue"]) is not int
        or data["blocker_issue"] != 778
        or type(data["implementation_issue"]) is not int
        or data["implementation_issue"] != scope["implementation_issue"]
    ):
        _reject("attestation does not bind movement proof")
    if scope["kind"] == "stream" and (
        data["stream_id"] != scope["stream_id"]
        or type(data["epic_issue"]) is not int
        or data["epic_issue"] != scope["epic_issue"]
    ):
        _reject("attestation stream scope is invalid")
    _require_false(data)
    _validate_role_map(data["roles"], scope)
    return data


def _validate_receipt(
    envelope: Any,
    *,
    role: str,
    issue: int,
    comment: Mapping[str, Any],
    repository: str,
    number: int,
    base: str,
    head: str,
    digest: str,
    scope: Mapping[str, Any],
) -> None:
    if not isinstance(envelope, dict):
        _reject("snapshot comment is invalid")
    required_envelope = {
        "id",
        "issue_url",
        "body",
        "user",
        "author_association",
        "created_at",
        "updated_at",
    }
    if (
        not required_envelope <= set(envelope)
        or type(envelope["id"]) is not int
        or envelope["id"] != comment["comment_id"]
    ):
        _reject("comment identity is invalid")
    if (
        envelope["issue_url"] != f"https://api.github.com/repos/{repository}/issues/{issue}"
        or not isinstance(envelope["body"], str)
        or not isinstance(envelope["user"], dict)
        or envelope["user"].get("login") != "andrei649"
        or envelope["author_association"] != "OWNER"
        or envelope["created_at"] != envelope["updated_at"]
        or envelope["updated_at"] != comment["updated_at"]
        or _sha256(envelope["body"].encode("utf-8")) != comment["comment_body_sha256"]
    ):
        _reject("comment envelope does not bind receipt")
    allowed = {
        "schema_version",
        "repository",
        "issue",
        "pull_request",
        "role",
        "movement_kind",
        "implementation_issue",
        "base_sha",
        "head_sha",
        "manifest_sha256",
        "can_authorize",
        "can_execute",
        "completion_authority",
        "release_ready",
    }
    if scope["kind"] == "stream":
        allowed.update({"stream_id", "epic_issue"})
    receipt = parse_marker_json(
        envelope["body"],
        RECEIPT_MARKER,
        RECEIPT_END_MARKER,
        allowed_keys=allowed,
        required_keys=allowed,
    )
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["repository"] != repository
        or type(receipt["issue"]) is not int
        or receipt["issue"] != issue
        or type(receipt["pull_request"]) is not int
        or receipt["pull_request"] != number
        or receipt["role"] != role
        or receipt["movement_kind"] != scope["kind"]
        or type(receipt["implementation_issue"]) is not int
        or receipt["implementation_issue"] != scope["implementation_issue"]
        or receipt["base_sha"] != base
        or receipt["head_sha"] != head
        or receipt["manifest_sha256"] != digest
    ):
        _reject("receipt does not bind movement proof")
    if scope["kind"] == "stream" and (
        receipt["stream_id"] != scope["stream_id"]
        or type(receipt["epic_issue"]) is not int
        or receipt["epic_issue"] != scope["epic_issue"]
    ):
        _reject("receipt stream scope is invalid")
    _require_false(receipt)


def _validate_snapshot(
    transport: Any,
    *,
    event_repository: str,
    number: int,
    base: str,
    head: str,
    branch: str,
    digest: str,
    scope: Mapping[str, Any],
    allow_draft: bool,
) -> None:
    try:
        current = transport("pull_request")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise MovementError("offline pull request snapshot is unavailable") from exc
    if (
        not isinstance(current, dict)
        or current.get("state") != "open"
        or (current.get("draft") is not False and not allow_draft)
    ):
        _reject("current pull request is not ready")
    current_repo = current.get("repository")
    current_base, current_head = current.get("base"), current.get("head")
    if (
        type(current.get("number")) is not int
        or current.get("number") != number
        or not isinstance(current_repo, dict)
        or current_repo.get("full_name") != event_repository
        or not isinstance(current_base, dict)
        or not isinstance(current_head, dict)
        or current_base.get("sha") != base
        or current_head.get("sha") != head
        or current_head.get("ref") != branch
        or not isinstance(current.get("body"), str)
    ):
        _reject("current pull request does not bind event")
    attestation = _validate_attestation(
        current["body"],
        repository=event_repository,
        number=number,
        base=base,
        head=head,
        digest=digest,
        scope=scope,
    )
    roles = attestation["roles"]
    issue_by_role = {
        "program": 757,
        "blocker": 778,
        "implementation": scope["implementation_issue"],
    }
    if scope["kind"] == "stream":
        issue_by_role["epic"] = scope["epic_issue"]
    for role, issue in issue_by_role.items():
        try:
            envelope = transport(f"comment:{roles[role]['comment_id']}")
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise MovementError("offline comment snapshot is unavailable") from exc
        _validate_receipt(
            envelope,
            role=role,
            issue=issue,
            comment=roles[role],
            repository=event_repository,
            number=number,
            base=base,
            head=head,
            digest=digest,
            scope=scope,
        )


def run_pure_proof(
    *,
    event: Any,
    baseline_manifest: Any,
    candidate_manifest: Any,
    candidate_manifest_bytes: bytes,
    base: str,
    head: str,
    diff: bytes,
    transport: Any | None = None,
) -> PureProof:
    """Prove pure/offline Nerva movement; classification alone is never success."""
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        _reject("requested commit is invalid")
    repository, number, event_base, event_head, _event_branch, _event_body, _event_draft = (
        _event_context(event)
    )
    if event_base != base or event_head != head:
        _reject("event commits do not match requested commits")
    branch, body, draft, _current = _fetch_current_snapshot(
        transport, repository=repository, number=number, base=base, head=head
    )
    if not isinstance(baseline_manifest, dict) or not isinstance(candidate_manifest, dict):
        _reject("manifest must be an object")
    validate_manifest_gate(baseline_manifest, base)
    validate_manifest_gate(candidate_manifest, base)
    records = parse_diff(diff)
    paths = [path for _, path in records]
    baseline_gate = baseline_manifest.get("movement_gate")
    candidate_gate = candidate_manifest.get("movement_gate")
    if not isinstance(candidate_gate, dict):
        _reject("candidate movement gate is missing")
    baseline_registry = [] if baseline_gate is None else baseline_gate["registry"]
    candidate_registry = candidate_gate["registry"]
    if base != LEGACY_BASE:
        validate_registry_evolution(
            baseline_registry,
            candidate_registry,
            {path for status, path in records if status == "A"},
        )
    nerva = classify(
        branch,
        body,
        paths,
        baseline_registry=baseline_registry,
        candidate_registry=candidate_registry,
    )
    if not nerva:
        return PureProof("non_nerva", {"kind": None, "implementation_issue": None})
    if draft and MARKER not in body:
        return PureProof("draft_hold", {"kind": None, "implementation_issue": None})
    required_paths = {
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json",
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md",
    }
    status_by_path = {path: status for status, path in records}
    if not required_paths <= set(paths) or any(
        status_by_path.get(path) not in {"A", "M"} for path in required_paths
    ):
        _reject("Nerva movement omits canonical manifest or generated view")
    scope = derive_scope(baseline_manifest, candidate_manifest)
    if scope["implementation_issue"] in {757, 778, scope["epic_issue"]}:
        _reject("implementation issue is reserved")
    if scope["kind"] == "stream":
        baseline_streams = baseline_manifest.get("streams")
        candidate_streams = candidate_manifest.get("streams")
        if not isinstance(baseline_streams, list) or not isinstance(candidate_streams, list):
            _reject("stream evidence scope is invalid")
        pairs = zip(baseline_streams, candidate_streams, strict=True)
        for baseline_stream, candidate_stream in pairs:
            if (
                isinstance(candidate_stream, dict)
                and candidate_stream.get("id") == scope["stream_id"]
            ):
                if not isinstance(baseline_stream, dict):
                    _reject("stream evidence scope is invalid")
                validate_stream_evidence_bindings(
                    baseline_stream, candidate_stream, pull_request=number
                )
                break
        else:
            _reject("stream evidence scope is invalid")
    if (
        not isinstance(candidate_manifest_bytes, bytes)
        or len(candidate_manifest_bytes) > MAX_JSON_BYTES
    ):
        _reject("candidate manifest bytes are invalid")
    try:
        parsed_candidate = strict_json(candidate_manifest_bytes)
    except MovementError as exc:
        raise MovementError("candidate manifest bytes are invalid") from exc
    if not isinstance(parsed_candidate, dict) or not _same_json(
        parsed_candidate, candidate_manifest
    ):
        _reject("candidate manifest bytes do not bind parsed manifest")
    digest = _sha256(candidate_manifest_bytes)
    _validate_snapshot(
        transport,
        event_repository=repository,
        number=number,
        base=base,
        head=head,
        branch=branch,
        digest=digest,
        scope=scope,
        allow_draft=draft,
    )
    return PureProof("draft_hold" if draft else "proved", scope)


def _snapshot_transport(snapshot_dir: Path) -> Any:
    root = snapshot_dir.resolve()

    def load(name: str) -> Any:
        if name == "pull_request":
            path = root / "pull_request.json"
        elif name.startswith("comment:") and name[8:].isdigit():
            path = root / "comments" / f"{name[8:]}.json"
        else:
            _reject("offline snapshot key is invalid")
        try:
            return strict_json(path.read_bytes())
        except (OSError, MovementError) as exc:
            raise MovementError("offline snapshot is invalid") from exc

    return load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        candidate_bytes = args.manifest.read_bytes()
        result = run_pure_proof(
            event=strict_json(args.event.read_bytes()),
            baseline_manifest=strict_json(args.baseline_manifest.read_bytes()),
            candidate_manifest=strict_json(candidate_bytes),
            candidate_manifest_bytes=candidate_bytes,
            base=args.base,
            head=args.head,
            diff=args.diff.read_bytes(),
            transport=_snapshot_transport(args.snapshot_dir) if args.snapshot_dir else None,
        )
    except MovementError as exc:
        print(f"movement gate rejected: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("movement gate rejected: input file is unavailable", file=sys.stderr)
        return 1
    print(result.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
