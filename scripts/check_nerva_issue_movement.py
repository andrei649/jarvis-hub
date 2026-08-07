#!/usr/bin/env python3
"""Fail-closed, bounded validator for Nerva issue-movement evidence.

This module deliberately keeps untrusted event, diff and receipt input as data.
Network and exact-head orchestration are layered on top of these pure helpers.
"""

from __future__ import annotations

# The gate contract requires a fixed-argument Git diff subprocess.
import argparse
import json
import math
import re
import subprocess  # nosec B404
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

LEGACY_BASE = "843918848c11bbd3f0099f9504d0e0eaaa56b9d6"
MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
END_MARKER = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
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
    except (json.JSONDecodeError, RecursionError, UnicodeError) as exc:
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
    if not isinstance(issues, list) or any(
        type(issue) is not int or issue <= 0 for issue in issues
    ):
        _reject("movement control issues are invalid")


def compute_name_status_diff(
    base: str,
    head: str,
    *,
    git: str = "git",
    cwd: Path | None = None,
    popen_factory: Any = subprocess.Popen,
) -> list[tuple[str, str]]:
    """Run the only accepted diff command; arguments are never built from shell text."""
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        _reject("diff commit is invalid")
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
        raw = process.stdout.read(MAX_DIFF_BYTES + 1)
        if len(raw) > MAX_DIFF_BYTES:
            process.kill()
            _reject("diff exceeds byte limit")
        if process.wait(timeout=20) != 0:
            _reject("cannot compute repository diff")
    except (AttributeError, OSError, subprocess.SubprocessError) as exc:
        raise MovementError("cannot compute repository diff") from exc
    return parse_diff(raw)


def _event_context(event: Any) -> tuple[str, str, str, str]:
    if not isinstance(event, dict):
        _reject("event must be an object")
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        _reject("event pull request is invalid")
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        _reject("event pull request refs are invalid")
    base_sha, head_sha, branch = base.get("sha"), head.get("sha"), head.get("ref")
    body = pull_request.get("body")
    if body is None:
        body = ""
    if (
        not all(isinstance(value, str) for value in (base_sha, head_sha, branch, body))
        or not SHA_RE.fullmatch(base_sha)
        or not SHA_RE.fullmatch(head_sha)
        or not _is_safe_text(branch)
    ):
        _reject("event pull request values are invalid")
    return base_sha, head_sha, branch, body


def run_pure_proof(
    *,
    event: Any,
    baseline_manifest: Any,
    candidate_manifest: Any,
    base: str,
    head: str,
    diff: bytes,
) -> bool:
    """Bind event, manifests and complete diff before returning a classification."""
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        _reject("requested commit is invalid")
    event_base, event_head, branch, body = _event_context(event)
    if event_base != base or event_head != head:
        _reject("event commits do not match requested commits")
    if not isinstance(baseline_manifest, dict) or not isinstance(candidate_manifest, dict):
        _reject("manifest must be an object")
    validate_manifest_gate(baseline_manifest, base)
    validate_manifest_gate(candidate_manifest, base)
    records = parse_diff(diff)
    paths = [path for _, path in records]
    baseline_gate = baseline_manifest.get("movement_gate")
    candidate_gate = candidate_manifest["movement_gate"]
    baseline_registry = [] if baseline_gate is None else baseline_gate["registry"]
    candidate_registry = candidate_gate["registry"]
    if base != LEGACY_BASE:
        validate_registry_evolution(
            baseline_registry,
            candidate_registry,
            {path for status, path in records if status == "A"},
        )
    return classify(
        branch,
        body,
        paths,
        baseline_registry=baseline_registry,
        candidate_registry=candidate_registry,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--diff", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run_pure_proof(
            event=strict_json(args.event.read_bytes()),
            baseline_manifest=strict_json(args.baseline_manifest.read_bytes()),
            candidate_manifest=strict_json(args.manifest.read_bytes()),
            base=args.base,
            head=args.head,
            diff=args.diff.read_bytes(),
        )
    except (MovementError, OSError) as exc:
        print(f"movement gate rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
