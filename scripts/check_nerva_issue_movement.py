#!/usr/bin/env python3
"""Fail-closed, bounded validator for Nerva issue-movement evidence.

This module deliberately keeps untrusted event, diff and receipt input as data.
Network and exact-head orchestration are layered on top of these pure helpers.
"""

from __future__ import annotations

# The gate contract requires a fixed-argument Git diff subprocess.
import argparse
import hashlib
import http.client
import json
import math
import os
import re
import ssl
import stat
import subprocess  # nosec B404
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEGACY_BASE = "843918848c11bbd3f0099f9504d0e0eaaa56b9d6"
ACCEPTED_BOOTSTRAP_BASE = "e596920ec60f19d2e7f0937819c892746a1c42b2"
LEGACY_MANIFEST_SHA256 = "ab63a42837fb69af901326ffae5052d01c787a913960e2fb6f3bebeaac10ec7f"
LEGACY_MANIFEST_VIEW_SHA256 = "e4480f7c37de768ef59d64a542a2ec6c241b89d44ce89fa329a72ff987c1cfdc"
BOOTSTRAP_REGISTRY_SHA256 = "9ab8aadf4c986e6380e8421225e99de5afc585163366ebb53199eecdf58980fb"
MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
END_MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
RECEIPT_MARKER = "<!-- NERVA2:MOVEMENT-RECEIPT:START -->"
RECEIPT_END_MARKER = "<!-- NERVA2:MOVEMENT-RECEIPT:END -->"
MAX_JSON_BYTES = 65_536
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 1_024
MAX_EVENT_BYTES = 131_072
MAX_BODY_BYTES = 131_072
MAX_RESPONSE_BYTES = 262_144
MAX_RESPONSE_COUNT = 5
MAX_AGGREGATE_RESPONSE_BYTES = 1_048_576
MAX_TOKEN_BYTES = 8_192
MAX_DIFF_BYTES = 1_048_576
MAX_DIFF_RECORDS = 4_096
MAX_GITHUB_IDENTIFIER = 9_007_199_254_740_991
MAX_REPOSITORY_BYTES = 201
MAX_REF_BYTES = 256
REST_TIMEOUT_SECONDS = 20.0
BRANCH_PREFIX = "nerva2/"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MANIFEST_PATH = "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
MANIFEST_VIEW_PATH = "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
MAX_MANIFEST_VIEW_BYTES = MAX_DIFF_BYTES
REGISTERED = frozenset(
    {
        ".github/workflows/ci.yml",
        ".github/workflows/nerva-roadmap.yml",
        ".github/workflows/pr-auto-merge.yml",
        "BACKLOG.md",
        "GO_LIVE_PLAN.md",
        "NERVA.md",
        "README.md",
        "STATUS.md",
        "docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md",
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json",
        "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md",
        "docs/superpowers/plans/2026-08-07-b2-live-issue-ledger.md",
        "docs/superpowers/specs/2026-08-07-b2-live-issue-ledger-design.md",
        "project-status.json",
        "scripts/check_nerva_issue_movement.py",
        "scripts/check_nerva_program_manifest.py",
        "tests/test_nerva_issue_movement.py",
        "tests/test_nerva_program_manifest.py",
        "tests/test_pr_auto_merge_policy.py",
    }
)
BOOTSTRAP_REGISTRY = tuple(sorted(REGISTERED))
MANUAL_INTEGRATION_WORKFLOW = ".github/workflows/pr-auto-merge.yml"
MANUAL_INTEGRATION_POLICY_TEST = "tests/test_pr_auto_merge_policy.py"
MAX_ROLLBACK_REASON_BYTES = 512


class MovementError(ValueError):
    """A bounded, safe-to-report rejection reason."""


@dataclass(frozen=True)
class PureProof:
    status: str
    scope: dict[str, Any]


@dataclass
class _ResponseBudget:
    count: int = 0
    aggregate_bytes: int = 0

    def begin(self) -> None:
        self.count += 1
        if self.count > MAX_RESPONSE_COUNT:
            _reject("REST response count exceeds limit")

    def add_bytes(self, size: int) -> None:
        self.aggregate_bytes += size
        if self.aggregate_bytes > MAX_AGGREGATE_RESPONSE_BYTES:
            _reject("REST aggregate bytes exceed limit")


def _reject(message: str) -> None:
    raise MovementError(message)


def _is_safe_text(value: str) -> bool:
    return unicodedata.normalize("NFC", value) == value and all(
        character.isprintable() and ord(character) != 0x7F for character in value
    )


def _bounded_utf8(value: Any, *, max_bytes: int, error: str) -> bytes:
    if not isinstance(value, str):
        _reject(error)
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise MovementError(error) from exc
    if len(encoded) > max_bytes:
        _reject(error)
    return encoded


def _validate_github_identifier(value: Any, *, error: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_GITHUB_IDENTIFIER:
        _reject(error)
    return value


def _validate_repository_name(value: Any) -> str:
    if not isinstance(value, str):
        _reject("repository name is invalid")
    encoded = _bounded_utf8(
        value, max_bytes=MAX_REPOSITORY_BYTES, error="repository name is invalid"
    )
    if len(encoded) > MAX_REPOSITORY_BYTES or REPOSITORY_RE.fullmatch(value) is None:
        _reject("repository name is invalid")
    return value


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


def validate_manifest_gate(
    manifest: Mapping[str, Any],
    base: str,
    *,
    baseline_manifest_bytes: bytes | None = None,
    baseline_manifest_view_bytes: bytes | None = None,
) -> None:
    """Validate only the movement-gate shape required by this pure layer."""
    if not isinstance(manifest, Mapping) or not isinstance(base, str):
        _reject("manifest gate input is invalid")
    gate = manifest.get("movement_gate")
    if gate is None:
        if base != ACCEPTED_BOOTSTRAP_BASE:
            _reject("gate-less manifest requires the accepted bootstrap base")
        if (
            not isinstance(baseline_manifest_bytes, bytes)
            or _sha256(baseline_manifest_bytes) != LEGACY_MANIFEST_SHA256
        ):
            _reject("gate-less bootstrap legacy manifest bytes do not match")
        if (
            not isinstance(baseline_manifest_view_bytes, bytes)
            or _sha256(baseline_manifest_view_bytes) != LEGACY_MANIFEST_VIEW_SHA256
        ):
            _reject("gate-less bootstrap legacy manifest view bytes do not match")
        try:
            parsed_baseline = strict_json(baseline_manifest_bytes)
        except MovementError as exc:
            raise MovementError("gate-less bootstrap legacy manifest bytes do not match") from exc
        if not isinstance(parsed_baseline, dict) or not _same_json(parsed_baseline, manifest):
            _reject("gate-less bootstrap legacy manifest semantics do not match")
        return
    allowed = {
        "schema_version",
        "enforcement_state",
        "bootstrap",
        "branch_prefix",
        "attestation_start_marker",
        "registry",
        "program_control_issues",
        "receipt_control",
        "manual_integration",
        "rollback",
    }
    gate = _closed_object(gate, allowed_keys=allowed, required_keys=allowed)
    if type(gate.get("schema_version")) is not int or gate["schema_version"] != 1:
        _reject("movement gate schema is invalid")
    if gate.get("enforcement_state") not in {"required", "safety_disabled"}:
        _reject("movement gate enforcement state is invalid")
    bootstrap = _closed_object(
        gate.get("bootstrap"),
        allowed_keys={
            "source_sha",
            "accepted_base_sha",
            "legacy_manifest_sha256",
            "legacy_manifest_view_sha256",
            "registry_seed_sha256",
        },
        required_keys={
            "source_sha",
            "accepted_base_sha",
            "legacy_manifest_sha256",
            "legacy_manifest_view_sha256",
            "registry_seed_sha256",
        },
    )
    if bootstrap != {
        "source_sha": LEGACY_BASE,
        "accepted_base_sha": ACCEPTED_BOOTSTRAP_BASE,
        "legacy_manifest_sha256": LEGACY_MANIFEST_SHA256,
        "legacy_manifest_view_sha256": LEGACY_MANIFEST_VIEW_SHA256,
        "registry_seed_sha256": BOOTSTRAP_REGISTRY_SHA256,
    }:
        _reject("movement gate bootstrap provenance is invalid")
    if gate.get("branch_prefix") != BRANCH_PREFIX:
        _reject("movement gate branch prefix is invalid")
    if gate.get("attestation_start_marker") != MARKER:
        _reject("movement gate attestation marker is invalid")
    registry = gate.get("registry")
    if not isinstance(registry, list):
        _reject("movement gate registry is invalid")
    _validate_registry(registry)
    if base == ACCEPTED_BOOTSTRAP_BASE:
        registry_seed = json.dumps(registry, separators=(",", ":"), ensure_ascii=False).encode()
        if (
            tuple(registry) != BOOTSTRAP_REGISTRY
            or _sha256(registry_seed) != BOOTSTRAP_REGISTRY_SHA256
        ):
            _reject("accepted bootstrap registry does not match pinned seed")
    issues = gate.get("program_control_issues")
    if (
        not isinstance(issues, list)
        or any(type(issue) is not int or issue <= 0 for issue in issues)
        or len(issues) != len(set(issues))
    ):
        _reject("movement control issues are invalid")
    receipt_control = _closed_object(
        gate.get("receipt_control"),
        allowed_keys={
            "mode",
            "live_pr_reread_required",
            "fresh_exact_head_rerun_required",
            "fresh_owner_receipts_required",
            "continuous_currentness",
        },
        required_keys={
            "mode",
            "live_pr_reread_required",
            "fresh_exact_head_rerun_required",
            "fresh_owner_receipts_required",
            "continuous_currentness",
        },
    )
    if receipt_control != {
        "mode": "point_in_time",
        "live_pr_reread_required": True,
        "fresh_exact_head_rerun_required": True,
        "fresh_owner_receipts_required": True,
        "continuous_currentness": False,
    }:
        _reject("movement receipt control is invalid")
    manual = _closed_object(
        gate.get("manual_integration"),
        allowed_keys={"issue", "workflow_path", "policy_test_path"},
        required_keys={"issue", "workflow_path", "policy_test_path"},
    )
    if manual != {
        "issue": 847,
        "workflow_path": MANUAL_INTEGRATION_WORKFLOW,
        "policy_test_path": MANUAL_INTEGRATION_POLICY_TEST,
    }:
        _reject("movement manual-integration invariant is invalid")
    for required_path in (MANUAL_INTEGRATION_WORKFLOW, MANUAL_INTEGRATION_POLICY_TEST):
        if required_path not in registry:
            _reject("movement registry omits manual-integration invariant")
    rollback = gate.get("rollback")
    if gate["enforcement_state"] == "required":
        if rollback is not None:
            _reject("required movement gate cannot declare rollback evidence")
    else:
        rollback = _closed_object(
            rollback,
            allowed_keys={
                "issue",
                "rollback_of_issue",
                "reason",
                "fresh_owner_receipts_required",
                "exact_head_checks_required",
            },
            required_keys={
                "issue",
                "rollback_of_issue",
                "reason",
                "fresh_owner_receipts_required",
                "exact_head_checks_required",
            },
        )
        rollback_issue = _validate_github_identifier(
            rollback.get("issue"), error="movement rollback issue is invalid"
        )
        reason = rollback.get("reason")
        _bounded_utf8(
            reason,
            max_bytes=MAX_ROLLBACK_REASON_BYTES,
            error="movement rollback reason is invalid",
        )
        if not reason or not _is_safe_text(reason):
            _reject("movement rollback reason is invalid")
        if (
            rollback.get("rollback_of_issue") != 846
            or rollback_issue not in issues[1:]
            or rollback.get("fresh_owner_receipts_required") is not True
            or rollback.get("exact_head_checks_required") is not True
        ):
            _reject("movement rollback evidence is invalid")
    if base == ACCEPTED_BOOTSTRAP_BASE and (
        set(gate) != allowed
        or gate["enforcement_state"] != "required"
        or gate["program_control_issues"] != [846]
        or gate["rollback"] is not None
    ):
        _reject("accepted bootstrap gate is not canonical")


def _resolve_git_executable(root: Path, *, environment: Mapping[str, str] | None = None) -> str:
    """Resolve one absolute Git executable outside the repository and cwd."""
    source = os.environ if environment is None else environment
    path_value = next((value for key, value in source.items() if key.upper() == "PATH"), "")
    try:
        protected = {root.resolve(strict=True), Path.cwd().resolve(strict=True)}
    except (OSError, RuntimeError) as exc:
        raise MovementError("Git trust roots are unavailable") from exc
    executable_names = ("git.exe", "git") if os.name == "nt" else ("git",)
    for raw_entry in path_value.split(os.pathsep):
        entry = raw_entry.strip().strip('"')
        directory = Path(entry)
        if not entry or not directory.is_absolute():
            continue
        for executable_name in executable_names:
            try:
                candidate = (directory / executable_name).resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not candidate.is_absolute() or not candidate.is_file():
                continue
            if os.name != "nt" and not os.access(candidate, os.X_OK):
                continue
            if any(
                candidate == boundary or candidate.is_relative_to(boundary)
                for boundary in protected
            ):
                continue
            return str(candidate)
    _reject("trusted Git executable is unavailable")


def _git_environment(git: str, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a Git-only environment without token, proxy or ambient Git controls."""
    source = os.environ if environment is None else environment
    scrubbed: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper == "PATH" or upper.startswith("GIT_") or "TOKEN" in upper or "PROXY" in upper:
            continue
        scrubbed[key] = value
    scrubbed["PATH"] = str(Path(git).parent)
    scrubbed["GIT_CONFIG_NOSYSTEM"] = "1"
    scrubbed["GIT_CONFIG_GLOBAL"] = os.devnull
    scrubbed["GIT_NO_REPLACE_OBJECTS"] = "1"
    scrubbed["GIT_OPTIONAL_LOCKS"] = "0"
    scrubbed["GIT_TERMINAL_PROMPT"] = "0"
    return scrubbed


def _git_output(
    git: str,
    root: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str],
    max_bytes: int,
    timeout_seconds: float = 20,
) -> tuple[int, bytes]:
    """Run one fixed-argv Git query and read stdout with a hard byte bound."""
    chunks: list[bytes] = []
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
                if total > max_bytes:
                    oversized.set()
                    return
                chunks.append(chunk)
        except BaseException as exc:  # The caller receives only a fixed rejection.
            reader_error.append(exc)

    process: Any | None = None
    try:
        process = subprocess.Popen(  # nosec B603
            [git, "--no-replace-objects", "-C", str(root), *arguments],
            shell=False,
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:
            _reject("Git query failed")
        reader = threading.Thread(target=read_stdout, args=(process.stdout,), daemon=True)
        reader.start()
        reader.join(timeout=timeout_seconds)
        if reader.is_alive() or oversized.is_set():
            process.kill()
            reader.join(timeout=timeout_seconds)
            process.wait(timeout=timeout_seconds)
            _reject("Git query timed out" if reader.is_alive() else "Git output exceeds limit")
        if reader_error:
            _reject("Git query failed")
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=timeout_seconds)
            raise MovementError("Git query timed out") from exc
    except MovementError:
        raise
    except (AttributeError, OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=timeout_seconds)
            except (OSError, subprocess.SubprocessError):
                pass
        raise MovementError("Git query failed") from exc
    return exit_code, b"".join(chunks)


def _require_git_output(
    git: str,
    root: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str],
    max_bytes: int,
    error: str,
) -> bytes:
    exit_code, output = _git_output(
        git,
        root,
        arguments,
        environment=environment,
        max_bytes=max_bytes,
    )
    if exit_code != 0:
        _reject(error)
    return output


def _checkout_head(git: str, root: Path, environment: Mapping[str, str], *, error: str) -> str:
    output = _require_git_output(
        git,
        root,
        ("rev-parse", "--verify", "HEAD^{commit}"),
        environment=environment,
        max_bytes=128,
        error=error,
    )
    try:
        value = output.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise MovementError(error) from exc
    if SHA_RE.fullmatch(value) is None:
        _reject(error)
    return value


def _reject_legacy_grafts(git: str, root: Path, environment: Mapping[str, str]) -> None:
    """Reject active legacy grafts from the repository's resolved common Git dir."""
    common_output = _require_git_output(
        git,
        root,
        ("rev-parse", "--path-format=absolute", "--git-common-dir"),
        environment=environment,
        max_bytes=4_096,
        error="Git common directory is unavailable",
    )
    grafts_output = _require_git_output(
        git,
        root,
        ("rev-parse", "--path-format=absolute", "--git-path", "info/grafts"),
        environment=environment,
        max_bytes=4_096,
        error="legacy Git grafts path is unavailable",
    )
    try:
        common_text = common_output.decode("utf-8", "strict").strip()
        grafts_text = grafts_output.decode("utf-8", "strict").strip()
        common = Path(common_text)
        reported_grafts = Path(grafts_text)
        if not common_text or not grafts_text or not common.is_absolute():
            _reject("Git common directory is invalid")
        if not reported_grafts.is_absolute():
            _reject("legacy Git grafts path is invalid")
        common = common.resolve(strict=True)
        if not common.is_dir():
            _reject("Git common directory is invalid")
        expected_grafts = common / "info" / "grafts"
        if reported_grafts.resolve(strict=False) != expected_grafts.resolve(strict=False):
            _reject("legacy Git grafts path is invalid")
        info = common / "info"
        if info.exists() and (info.is_symlink() or not info.is_dir()):
            _reject("legacy Git grafts path is unsafe")
        metadata = reported_grafts.lstat()
    except FileNotFoundError:
        return
    except MovementError:
        raise
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise MovementError("cannot inspect legacy Git grafts") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size:
        _reject("legacy Git grafts are unsupported")


def _encode_diff(records: Iterable[tuple[str, str]]) -> bytes:
    return b"".join(
        status.encode("ascii") + b"\0" + path.encode("utf-8") + b"\0" for status, path in records
    )


def compute_name_status_diff(
    base: str,
    head: str,
    *,
    git: str = "git",
    cwd: Path | None = None,
    popen_factory: Any = subprocess.Popen,
    timeout_seconds: float = 20,
    environment: Mapping[str, str] | None = None,
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
            [
                git,
                "--no-replace-objects",
                "diff",
                "--no-ext-diff",
                "--name-status",
                "--no-renames",
                "-z",
                base,
                head,
                "--",
            ],
            shell=False,
            cwd=cwd,
            env=(
                dict(environment)
                if environment is not None
                else {"PATH": str(Path(git).parent) if Path(git).parent != Path(".") else ""}
            ),
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


def _event_context(event: Any) -> tuple[str, int, str, str, str, str, str, bool, str]:
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
    base_sha, base_branch = base.get("sha"), base.get("ref")
    head_sha, branch = head.get("sha"), head.get("ref")
    body = pull_request.get("body")
    draft = pull_request.get("draft")
    state = pull_request.get("state")
    if body is None:
        body = ""
    _validate_github_identifier(number, error="event pull request values are invalid")
    _validate_repository_name(repository_name)
    if (
        not all(
            isinstance(value, str)
            for value in (repository_name, base_sha, base_branch, head_sha, branch, body)
        )
        or type(draft) is not bool
        or state not in {"open", "closed"}
        or not SHA_RE.fullmatch(base_sha)
        or not SHA_RE.fullmatch(head_sha)
        or not _is_safe_text(base_branch)
        or not _is_safe_text(branch)
    ):
        _reject("event pull request values are invalid")
    _bounded_utf8(base_branch, max_bytes=MAX_REF_BYTES, error="event base ref exceeds limit")
    _bounded_utf8(branch, max_bytes=MAX_REF_BYTES, error="event head ref exceeds limit")
    _bounded_utf8(body, max_bytes=MAX_BODY_BYTES, error="event pull request body exceeds limit")
    return repository_name, number, base_sha, base_branch, head_sha, branch, body, draft, state


def _fetch_current_snapshot(
    transport: Any,
    *,
    repository: str,
    number: int,
    base: str,
    head: str,
    base_branch: str | None = None,
    branch: str | None = None,
    body: str | None = None,
    draft: bool | None = None,
    state: str | None = None,
) -> tuple[str, str, bool, dict[str, Any]]:
    """Fetch current PR before any classifier may observe stale event fields."""
    if transport is None:
        _reject("movement proof requires offline snapshot transport")
    try:
        current = transport("pull_request")
    except MovementError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise MovementError("pull request response is unavailable") from exc
    if not isinstance(current, dict):
        _reject("current pull request response is invalid")
    if current.get("state") != "open":
        _reject("current pull request is not open")
    current_base, current_head = current.get("base"), current.get("head")
    current_body, current_draft, current_state = (
        current.get("body"),
        current.get("draft"),
        current.get("state"),
    )
    if current_body is None:
        current_body = ""
        current = {**current, "body": current_body}
    current_repo = current_base.get("repo") if isinstance(current_base, dict) else None
    if (
        _validate_github_identifier(
            current.get("number"), error="current pull request does not bind event"
        )
        != number
        or not isinstance(current_repo, dict)
        or current_repo.get("full_name") != repository
        or not isinstance(current_base, dict)
        or current_base.get("sha") != base
        or not isinstance(current_base.get("ref"), str)
        or not _is_safe_text(current_base["ref"])
        or not isinstance(current_head, dict)
        or current_head.get("sha") != head
        or not isinstance(current_head.get("ref"), str)
        or not _is_safe_text(current_head["ref"])
        or not isinstance(current_body, str)
        or type(current_draft) is not bool
        or (base_branch is not None and current_base["ref"] != base_branch)
        or (branch is not None and current_head["ref"] != branch)
        or (body is not None and current_body != body)
        or (draft is not None and current_draft is not draft)
        or (state is not None and current_state != state)
    ):
        _reject("current pull request does not bind event")
    _bounded_utf8(
        current_base["ref"],
        max_bytes=MAX_REF_BYTES,
        error="current base ref exceeds limit",
    )
    _bounded_utf8(
        current_head["ref"],
        max_bytes=MAX_REF_BYTES,
        error="current head ref exceeds limit",
    )
    _bounded_utf8(
        current_body,
        max_bytes=MAX_BODY_BYTES,
        error="current pull request body exceeds limit",
    )
    return current_head["ref"], current_body, current_draft, current


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
        baseline_state = baseline_gate.get("enforcement_state")
        candidate_state = candidate_gate.get("enforcement_state")
        if baseline_state == "safety_disabled" and candidate_state != "safety_disabled":
            _reject("safety-disabled gate cannot return without a new schema")
        safety_transition = baseline_state == "required" and candidate_state == "safety_disabled"
        mutable_gate_fields = {"registry", "program_control_issues"}
        if safety_transition:
            mutable_gate_fields.update({"enforcement_state", "rollback"})
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
    if baseline_gate is not None:
        baseline_state = baseline_gate.get("enforcement_state")
        candidate_state = candidate_gate.get("enforcement_state")
        if baseline_state == "required" and candidate_state == "safety_disabled":
            rollback = candidate_gate.get("rollback")
            if (
                len(added_issues) != 1
                or not isinstance(rollback, dict)
                or rollback.get("issue") != added_issues[0]
                or rollback.get("rollback_of_issue") != 846
                or rollback.get("fresh_owner_receipts_required") is not True
                or rollback.get("exact_head_checks_required") is not True
            ):
                _reject("safety disable is not bound to one rollback movement")
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
        _validate_github_identifier(entry["comment_id"], error="attestation role map is invalid")
        if (
            not isinstance(entry["updated_at"], str)
            or TIMESTAMP_RE.fullmatch(entry["updated_at"]) is None
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


def _validate_comment_envelope(
    envelope: Any,
    *,
    issue: int,
    comment: Mapping[str, Any],
    repository: str,
) -> str:
    """Validate consumed GitHub fields while allowing unrelated envelope additions."""
    if not isinstance(envelope, dict):
        _reject("REST comment response is invalid")
    required_envelope = {
        "id",
        "issue_url",
        "body",
        "user",
        "author_association",
        "created_at",
        "updated_at",
    }
    comment_id = comment.get("comment_id")
    updated_at = comment.get("updated_at")
    body = envelope.get("body")
    user = envelope.get("user")
    if (
        not required_envelope <= set(envelope)
        or _validate_github_identifier(envelope.get("id"), error="comment identity is invalid")
        != _validate_github_identifier(comment_id, error="comment identity is invalid")
        or envelope.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue}"
        or not isinstance(user, dict)
        or user.get("login") != "andrei649"
        or envelope.get("author_association") != "OWNER"
        or not isinstance(updated_at, str)
        or TIMESTAMP_RE.fullmatch(updated_at) is None
        or envelope.get("created_at") != envelope.get("updated_at")
        or envelope.get("updated_at") != updated_at
    ):
        _reject("comment envelope does not bind receipt")
    body_bytes = _bounded_utf8(
        body, max_bytes=MAX_BODY_BYTES, error="comment envelope does not bind receipt"
    )
    if _sha256(body_bytes) != comment.get("comment_body_sha256"):
        _reject("comment envelope does not bind receipt")
    return body


def _validate_receipt_payload(
    body: str,
    *,
    role: str,
    issue: int,
    repository: str,
    number: int,
    base: str,
    head: str,
    digest: str,
    scope: Mapping[str, Any],
) -> None:
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
        body,
        RECEIPT_MARKER,
        RECEIPT_END_MARKER,
        allowed_keys=allowed,
        required_keys=allowed,
        max_body_bytes=MAX_BODY_BYTES,
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
    body = _validate_comment_envelope(
        envelope,
        issue=issue,
        comment=comment,
        repository=repository,
    )
    _validate_receipt_payload(
        body,
        role=role,
        issue=issue,
        repository=repository,
        number=number,
        base=base,
        head=head,
        digest=digest,
        scope=scope,
    )


def _validate_snapshot(
    transport: Any,
    *,
    current: Mapping[str, Any],
    event_repository: str,
    number: int,
    base: str,
    head: str,
    branch: str,
    digest: str,
    scope: Mapping[str, Any],
    allow_draft: bool,
) -> None:
    if (
        not isinstance(current, dict)
        or current.get("state") != "open"
        or (current.get("draft") is not False and not allow_draft)
    ):
        _reject("current pull request is not ready")
    current_base, current_head = current.get("base"), current.get("head")
    current_repo = current_base.get("repo") if isinstance(current_base, dict) else None
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
        except MovementError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise MovementError("comment response is unavailable") from exc
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
    baseline_manifest_bytes: bytes | None = None,
    baseline_manifest_view_bytes: bytes | None = None,
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
    (
        repository,
        number,
        event_base,
        event_base_branch,
        event_head,
        event_branch,
        event_body,
        event_draft,
        event_state,
    ) = _event_context(event)
    if event_base != base or event_head != head:
        _reject("event commits do not match requested commits")
    branch, body, draft, current = _fetch_current_snapshot(
        transport,
        repository=repository,
        number=number,
        base=base,
        head=head,
        base_branch=event_base_branch,
        branch=event_branch,
        body=event_body,
        draft=event_draft,
        state=event_state,
    )
    if not isinstance(baseline_manifest, dict) or not isinstance(candidate_manifest, dict):
        _reject("manifest must be an object")
    validate_manifest_gate(
        baseline_manifest,
        base,
        baseline_manifest_bytes=baseline_manifest_bytes,
        baseline_manifest_view_bytes=baseline_manifest_view_bytes,
    )
    validate_manifest_gate(candidate_manifest, base)
    records = parse_diff(diff)
    paths = [path for _, path in records]
    baseline_gate = baseline_manifest.get("movement_gate")
    candidate_gate = candidate_manifest.get("movement_gate")
    if not isinstance(candidate_gate, dict):
        _reject("candidate movement gate is missing")
    baseline_registry = [] if baseline_gate is None else baseline_gate["registry"]
    candidate_registry = candidate_gate["registry"]
    if baseline_gate is not None:
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
        current=current,
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


def _validate_candidate_manifest(root: Path, head: str, environment: Mapping[str, str]) -> None:
    """Run the existing whole-program checker against this exact candidate."""
    checker = Path(__file__).resolve().with_name("check_nerva_program_manifest.py")
    try:
        completed = subprocess.run(  # nosec B603
            [
                sys.executable,
                str(checker),
                "--check",
                "--root",
                str(root),
                "--candidate-ref",
                head,
            ],
            check=False,
            env=dict(environment),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MovementError("candidate manifest validation failed") from exc
    if completed.returncode != 0:
        _reject("candidate manifest validation failed")


def run_repository_proof(
    *,
    root: Path,
    event: Any,
    base: str,
    head: str,
    transport: Any | None,
    proof_runner: Any = run_pure_proof,
    manifest_validator: Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> PureProof:
    """Bind the pure movement proof to one exact repository base and checkout head."""
    if not isinstance(base, str) or not isinstance(head, str):
        _reject("requested commit is invalid")
    if SHA_RE.fullmatch(base) is None or SHA_RE.fullmatch(head) is None:
        _reject("requested commit is invalid")
    (
        _repository,
        _number,
        event_base,
        _base_branch,
        event_head,
        _branch,
        _body,
        _draft,
        _state,
    ) = _event_context(event)
    if event_base != base or event_head != head:
        _reject("event commits do not match requested commits")
    try:
        repository_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MovementError("repository root is unavailable") from exc
    if not repository_root.is_dir():
        _reject("repository root is unavailable")

    git = _resolve_git_executable(repository_root, environment=environment)
    git_environment = _git_environment(git, environment)
    top_level = _require_git_output(
        git,
        repository_root,
        ("rev-parse", "--show-toplevel"),
        environment=git_environment,
        max_bytes=4_096,
        error="repository root is invalid",
    )
    try:
        reported_root = Path(top_level.decode("utf-8", "strict").strip()).resolve(strict=True)
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise MovementError("repository root is invalid") from exc
    if reported_root != repository_root:
        _reject("repository root is invalid")

    _reject_legacy_grafts(git, repository_root, git_environment)
    for label, commit in (("base", base), ("head", head)):
        object_type = _require_git_output(
            git,
            repository_root,
            ("cat-file", "-t", commit),
            environment=git_environment,
            max_bytes=64,
            error=f"{label} commit is unavailable",
        )
        if object_type != b"commit\n":
            _reject(f"{label} must identify an exact commit object")
    ancestor_code, _ancestor_output = _git_output(
        git,
        repository_root,
        ("merge-base", "--is-ancestor", base, head),
        environment=git_environment,
        max_bytes=64,
    )
    if ancestor_code != 0:
        _reject("base is not an ancestor of head")
    if (
        _checkout_head(
            git, repository_root, git_environment, error="checked-out HEAD is unavailable"
        )
        != head
    ):
        _reject("event head does not equal checked-out HEAD")

    records = compute_name_status_diff(
        base,
        head,
        git=git,
        cwd=repository_root,
        environment=git_environment,
    )
    baseline_bytes = _require_git_output(
        git,
        repository_root,
        ("cat-file", "blob", f"{base}:{MANIFEST_PATH}"),
        environment=git_environment,
        max_bytes=MAX_JSON_BYTES,
        error="baseline manifest is unavailable",
    )
    baseline_view_bytes = _require_git_output(
        git,
        repository_root,
        ("cat-file", "blob", f"{base}:{MANIFEST_VIEW_PATH}"),
        environment=git_environment,
        max_bytes=MAX_MANIFEST_VIEW_BYTES,
        error="baseline manifest view is unavailable",
    )
    candidate_bytes = _require_git_output(
        git,
        repository_root,
        ("cat-file", "blob", f"{head}:{MANIFEST_PATH}"),
        environment=git_environment,
        max_bytes=MAX_JSON_BYTES,
        error="candidate manifest is unavailable",
    )
    baseline_manifest = strict_json(baseline_bytes)
    candidate_manifest = strict_json(candidate_bytes)
    if not isinstance(baseline_manifest, dict) or not isinstance(candidate_manifest, dict):
        _reject("manifest must be an object")

    result = proof_runner(
        event=event,
        baseline_manifest=baseline_manifest,
        baseline_manifest_bytes=baseline_bytes,
        baseline_manifest_view_bytes=baseline_view_bytes,
        candidate_manifest=candidate_manifest,
        candidate_manifest_bytes=candidate_bytes,
        base=base,
        head=head,
        diff=_encode_diff(records),
        transport=transport,
    )
    if result.status == "proved" or result.scope.get("kind") is not None:
        status_by_path = {path: status for status, path in records}
        required_paths = {MANIFEST_PATH, MANIFEST_VIEW_PATH}
        if any(status_by_path.get(path) not in {"A", "M"} for path in required_paths):
            _reject("Nerva movement omits canonical manifest or generated view")
        _require_git_output(
            git,
            repository_root,
            ("cat-file", "blob", f"{head}:{MANIFEST_VIEW_PATH}"),
            environment=git_environment,
            max_bytes=MAX_MANIFEST_VIEW_BYTES,
            error="generated manifest view is unavailable",
        )
        if manifest_validator is None:
            _validate_candidate_manifest(repository_root, head, git_environment)
        else:
            manifest_validator(repository_root, head)
    _reject_legacy_grafts(git, repository_root, git_environment)
    if (
        _checkout_head(
            git, repository_root, git_environment, error="checked-out HEAD moved during proof"
        )
        != head
    ):
        _reject("checked-out HEAD moved during proof")
    return result


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTP failure before credentials can be resent."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _build_live_opener(context: ssl.SSLContext) -> urllib.request.OpenerDirector:
    """Build a verified-TLS opener with neither proxies nor redirect following."""
    if not isinstance(context, ssl.SSLContext):
        _reject("verified TLS context is unavailable")
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        _reject("verified TLS context is required")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )


def _read_live_token(environment: Mapping[str, str]) -> str:
    """Read the sole live credential source without echoing rejected bytes."""
    try:
        token = environment.get("GITHUB_TOKEN")
    except (AttributeError, OSError) as exc:
        raise MovementError("GITHUB_TOKEN is unavailable") from exc
    if not isinstance(token, str):
        _reject("GITHUB_TOKEN is unavailable")
    try:
        encoded = token.encode("ascii", "strict")
    except UnicodeEncodeError as exc:
        raise MovementError("GITHUB_TOKEN is invalid") from exc
    if (
        not encoded
        or len(encoded) > MAX_TOKEN_BYTES
        or any(character < 0x21 or character > 0x7E for character in encoded)
    ):
        _reject("GITHUB_TOKEN is invalid")
    return token


def _comment_identifier(name: str) -> int | None:
    if name == "pull_request":
        return None
    if not isinstance(name, str) or not name.startswith("comment:"):
        _reject("REST response key is invalid")
    raw_identifier = name[8:]
    if (
        not raw_identifier
        or len(raw_identifier) > 16
        or not raw_identifier.isascii()
        or not raw_identifier.isdigit()
        or raw_identifier.startswith("0")
    ):
        _reject("comment identifier is invalid")
    comment_id = _validate_github_identifier(
        int(raw_identifier), error="comment identifier is invalid"
    )
    if str(comment_id) != raw_identifier:
        _reject("comment identifier is invalid")
    return comment_id


def _response_url(repository: str, number: int, name: str) -> str:
    """Construct one fixed GitHub REST URL only after bounded identifier validation."""
    repository = _validate_repository_name(repository)
    number = _validate_github_identifier(number, error="pull request identifier is invalid")
    comment_id = _comment_identifier(name)
    if comment_id is None:
        return f"https://api.github.com/repos/{repository}/pulls/{number}"
    return f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}"


def _header_value(headers: Any, name: str) -> str | None:
    try:
        get_all = getattr(headers, "get_all", None)
        if callable(get_all):
            values = get_all(name)
            if values is not None:
                if len(values) != 1 or not isinstance(values[0], str):
                    _reject("GitHub REST response headers are invalid")
                return values[0]
        value = headers.get(name)
    except (AttributeError, TypeError, ValueError) as exc:
        raise MovementError("GitHub REST response headers are invalid") from exc
    if value is not None and not isinstance(value, str):
        _reject("GitHub REST response headers are invalid")
    return value


def _read_rest_response(response: Any, *, expected_url: str, budget: _ResponseBudget) -> Any:
    try:
        status = response.status
        final_url = response.geturl()
        headers = response.headers
    except (AttributeError, TypeError, ValueError) as exc:
        raise MovementError("GitHub REST response is invalid") from exc
    if status != 200:
        _reject("GitHub REST response status is not successful")
    if final_url != expected_url:
        _reject("GitHub REST response URL changed")
    content_encoding = _header_value(headers, "Content-Encoding")
    if content_encoding not in {None, "identity"}:
        _reject("GitHub REST response encoding is invalid")
    content_length_value = _header_value(headers, "Content-Length")
    declared_length: int | None = None
    if content_length_value is not None:
        if (
            not content_length_value
            or len(content_length_value) > 9
            or not content_length_value.isascii()
            or not content_length_value.isdigit()
            or (content_length_value.startswith("0") and content_length_value != "0")
        ):
            _reject("GitHub REST response length is invalid")
        declared_length = int(content_length_value)
        if declared_length > MAX_RESPONSE_BYTES:
            _reject("GitHub REST response exceeds limit")
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (http.client.HTTPException, OSError, TimeoutError, ValueError) as exc:
        raise MovementError("GitHub REST response read failed") from exc
    if not isinstance(raw, bytes):
        _reject("GitHub REST response is invalid")
    if len(raw) > MAX_RESPONSE_BYTES:
        _reject("GitHub REST response exceeds limit")
    if declared_length is not None and declared_length != len(raw):
        _reject("GitHub REST response is truncated")
    budget.add_bytes(len(raw))
    try:
        return strict_json(raw, max_bytes=MAX_RESPONSE_BYTES)
    except MovementError as exc:
        raise MovementError("GitHub REST response JSON is invalid") from exc


def _live_transport(
    repository: str,
    number: int,
    *,
    environment: Mapping[str, str] | None = None,
    opener: Any | None = None,
    timeout_seconds: float = REST_TIMEOUT_SECONDS,
) -> Any:
    """Return one bounded callable for current PR and exact issue-comment GETs."""
    repository = _validate_repository_name(repository)
    number = _validate_github_identifier(number, error="pull request identifier is invalid")
    token = _read_live_token(os.environ if environment is None else environment)
    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 60
    ):
        _reject("REST timeout is invalid")
    if opener is None:
        try:
            context = ssl.create_default_context()
        except (OSError, ssl.SSLError) as exc:
            raise MovementError("verified TLS context is unavailable") from exc
        opener = _build_live_opener(context)
    budget = _ResponseBudget()

    def load(name: str) -> Any:
        url = _response_url(repository, number, name)
        budget.begin()
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {token}",
                "User-Agent": "nerva-movement-gate/1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=float(timeout_seconds)) as response:
                return _read_rest_response(response, expected_url=url, budget=budget)
        except MovementError:
            raise
        except (
            http.client.HTTPException,
            OSError,
            TimeoutError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            ValueError,
        ) as exc:
            raise MovementError("GitHub REST request failed") from exc

    return load


def _read_bounded_file(path: Path, *, max_bytes: int, error: str) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError as exc:
        raise MovementError(error) from exc
    if len(raw) > max_bytes:
        _reject(error)
    return raw


def _snapshot_transport(snapshot_dir: Path) -> Any:
    root = snapshot_dir.resolve()
    budget = _ResponseBudget()

    def load(name: str) -> Any:
        comment_id = _comment_identifier(name)
        budget.begin()
        if comment_id is None:
            path = root / "pull_request.json"
        else:
            path = root / "comments" / f"{comment_id}.json"
        try:
            raw = _read_bounded_file(
                path,
                max_bytes=MAX_RESPONSE_BYTES,
                error="offline snapshot is invalid",
            )
            budget.add_bytes(len(raw))
            return strict_json(raw, max_bytes=MAX_RESPONSE_BYTES)
        except MovementError as exc:
            raise MovementError("offline snapshot is invalid") from exc

    return load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    transport_mode = parser.add_mutually_exclusive_group(required=True)
    transport_mode.add_argument("--live", action="store_true")
    transport_mode.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--baseline-manifest", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--diff", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if any((args.baseline_manifest, args.manifest, args.diff)):
            _reject("external manifest and diff inputs are not accepted")
        event = strict_json(
            _read_bounded_file(
                args.event,
                max_bytes=MAX_EVENT_BYTES,
                error="event file is unavailable or exceeds limit",
            ),
            max_bytes=MAX_EVENT_BYTES,
        )
        (
            repository,
            number,
            _base,
            _base_branch,
            _head,
            _branch,
            _body,
            _draft,
            _state,
        ) = _event_context(event)
        if args.live:
            transport = _live_transport(
                repository,
                number,
                environment=os.environ,
            )
        else:
            transport = _snapshot_transport(args.snapshot_dir)
        result = run_repository_proof(
            root=args.root,
            event=event,
            base=args.base,
            head=args.head,
            transport=transport,
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
