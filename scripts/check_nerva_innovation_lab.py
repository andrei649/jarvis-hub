"""Fail-closed Innovation Lab schema, graph, and Git-baseline validator.

The module is intentionally standard-library only.  The checked-in JSON schema
is a small, pinned program evaluated by the closed profile implemented here;
neither a mutable worktree file nor an untrusted schema keyword can weaken the
decision, authority, evidence, or append-only boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess  # nosec B404
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCHEMA_REL = "docs/nerva2/INNOVATION_LAB_V1.schema.json"
GARDEN_REL = "docs/nerva2/KNOWLEDGE_GARDEN_V1.json"
DOCUMENT_REL = "docs/nerva2/INNOVATION_LAB_RFC_V1.md"
WORKFLOW_REL = ".github/workflows/nerva-roadmap.yml"

SCHEMA_VERSION = "nerva.innovation-lab.v1"
SCHEMA_PROFILE = "nerva.stdlib-schema-profile.v1"
SCHEMA_SHA256 = "310d2cbb91c550d9409e6a5b9849918256a0484066429c260334caf4af660898"
PROGRAM_ISSUE = 805
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
ACTOR_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

AUTHORITY = {
    "can_commit_main": False,
    "can_merge": False,
    "can_deploy": False,
    "can_change_roadmap": False,
    "can_promote_capability": False,
    "can_authorize_actions": False,
    "can_claim_completion": False,
    "grants_authority": False,
    "privileged_action_authority": "nerva.action.v1",
}

CATALOGUE_V1 = {
    "id": "CATALOGUE-EXTERNAL-INTEGRATIONS-V1",
    "path": "docs/nerva2/INTEGRATION_CATALOGUE_RFC.md",
    "source_pr": 821,
    "accepted_merge_commit": "ccc36e851094976fe8f6c209a8c2f5bf07aaad05",
    "git_blob_oid": "9e446b8d7c5fbad954760f665a24de11b9755c59",
    "content_bytes": 16965,
    "content_sha256": "5697cc44824b01efb20cd345e79846b1ecd086a4999e2e75d0984c4b3d1944d3",
    "reference_state": "historical_accepted_blob",
    "import_mode": "reference_only",
    "claim_scope": "precursor_hypotheses_only",
    "satisfies_issue_805": [],
    "limitations": [
        "The catalogue is not an RFC record and satisfies no #805 checkbox.",
        "Rows remain hypotheses until separately evidenced through this schema.",
    ],
}

CATALOGUE_V2 = {
    "id": "CATALOGUE-EXTERNAL-INTEGRATIONS-V2",
    "path": "docs/nerva2/INTEGRATION_CATALOGUE_RFC.md",
    "source_pr": 826,
    "source_issue": 825,
    "accepted_merge_commit": "72dca7eea42229cca9a55a5bda7276810c376d8e",
    "git_blob_oid": "9aee52226fa6e0075023f419a8273332f799ca46",
    "content_bytes": 19409,
    "content_sha256": "8d39336e657424a39fb1e77b4b12460085bd6aa86449267ce0553a5757161dae",
    "reference_state": "historical_accepted_blob",
    "import_mode": "reference_only",
    "claim_scope": "precursor_hypotheses_only",
    "satisfies_issue_805": [],
    "supersedes": "CATALOGUE-EXTERNAL-INTEGRATIONS-V1",
    "limitations": [
        "The evidence correction is not an RFC record and satisfies no #805 checkbox.",
        "Corrected self-hosting facts remain discovery inputs without delivery authority.",
    ],
}

CATALOGUE_V3 = {
    "id": "CATALOGUE-EXTERNAL-INTEGRATIONS-V3",
    "path": "docs/nerva2/INTEGRATION_CATALOGUE_RFC.md",
    "source_pr": 827,
    "source_issue": 824,
    "accepted_merge_commit": "002b30fcdf7077880ad4f42f3c2297e97d26afa9",
    "git_blob_oid": "245b0f7e90f414659499bd56bc157ff72c87e340",
    "content_bytes": 19681,
    "content_sha256": "ad211700fd4fc81be3006f31b2d5011e1070b56e2281ee94e5f298fe783972c9",
    "reference_state": "historical_accepted_blob",
    "import_mode": "reference_only",
    "claim_scope": "precursor_hypotheses_only",
    "satisfies_issue_805": [],
    "supersedes": "CATALOGUE-EXTERNAL-INTEGRATIONS-V2",
    "limitations": [
        "The drift-policy revision is not an RFC record and satisfies no #805 checkbox.",
        "Provider and authority decisions remain gated outside this catalogue reference.",
    ],
}

KNOWN_CATALOGUES = (CATALOGUE_V1, CATALOGUE_V2, CATALOGUE_V3)
KNOWN_CATALOGUE_BY_ID = {entry["id"]: entry for entry in KNOWN_CATALOGUES}

PROFILE_KEYWORDS = {
    "$ref",
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "pattern",
    "minimum",
    "maximum",
    "oneOf",
    "not",
}
ROOT_SCHEMA_KEYS = PROFILE_KEYWORDS | {
    "$schema",
    "$id",
    "$defs",
    "x-nerva-schema-profile",
}
JSON_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}

ALLOWED_LINKS = {
    "MOTIVATES": ("OBSERVATION", "IDEA"),
    "DEVELOPED_AS": ("IDEA", "RFC"),
    "SUPPORTED_BY": ("RFC", "EVIDENCE"),
    "CHALLENGED_BY": ("RFC", "EVIDENCE"),
    "TESTED_BY": ("RFC", "PROTOTYPE"),
    "DECIDED_BY": ("RFC", "DECISION"),
    "ACCEPTED_AS": ("DECISION", "EPIC"),
    "PRODUCED": ("EPIC", "OUTCOME"),
    "SUPERSEDES": ("RFC", "RFC"),
    "REOPENS": ("RFC", "DECISION"),
}
STRONG_EVIDENCE = {
    "primary_read",
    "in_repository",
    "benchmark",
    "owner_live",
    "negative_result",
}
STAGE_TRANSITIONS = {
    (None, "DRAFT"),
    ("DRAFT", "EVIDENCE_GATHERING"),
    ("DRAFT", "DECIDED"),
    ("EVIDENCE_GATHERING", "READY_FOR_REVIEW"),
    ("EVIDENCE_GATHERING", "DECIDED"),
    ("READY_FOR_REVIEW", "EVIDENCE_GATHERING"),
    ("READY_FOR_REVIEW", "DECIDED"),
    ("DECIDED", "OUTCOME_REVIEWED"),
}
OUTCOME_TRANSITIONS = {
    (None, "pending"),
    (None, "not_applicable"),
    ("pending", "linked"),
}


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate key {key!r}")
        result[key] = value
    return result


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite number {value!r}")
    return parsed


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value!r}")


def _find_non_finite(value: Any, path: str = "$") -> str | None:
    if isinstance(value, float) and not math.isfinite(value):
        return path
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_non_finite(item, f"{path}[{index}]")
            if found:
                return found
    if isinstance(value, dict):
        for key, item in value.items():
            found = _find_non_finite(item, f"{path}.{key}")
            if found:
                return found
    return None


def decode_json_bytes(raw: bytes, label: str = "JSON") -> tuple[Any | None, list[str]]:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    errors: list[str] = []
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return None, [f"{label}: invalid UTF-8: {exc}"]
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_parse_finite_float,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, _DuplicateKey, ValueError) as exc:
        message = str(exc)
        if "duplicate key" in message or "non-finite" in message:
            errors.append(f"{label}: {message}")
        else:
            errors.append(f"{label}: invalid JSON: {message}")
        return None, errors
    non_finite_path = _find_non_finite(value)
    if non_finite_path:
        errors.append(f"{label}: non-finite number at {non_finite_path}")
        return None, errors
    return value, []


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) and math.isfinite(
        float(value)
    )


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _validate_schema_node(
    node: Any,
    path: str,
    root: dict[str, Any],
    errors: list[str],
    *,
    is_root: bool = False,
) -> None:
    if not isinstance(node, dict):
        errors.append(f"{path}: schema node must be an object")
        return
    allowed = ROOT_SCHEMA_KEYS if is_root else PROFILE_KEYWORDS
    unknown = set(node) - allowed
    if unknown:
        errors.append(f"{path}: unknown schema keyword(s): {sorted(unknown)}")

    if "$ref" in node:
        if set(node) != {"$ref"}:
            errors.append(f"{path}: $ref siblings are forbidden by the closed profile")
        reference = node.get("$ref")
        if not isinstance(reference, str) or not re.fullmatch(
            r"#/\$defs/[A-Za-z0-9_-]+", reference
        ):
            errors.append(f"{path}: $ref must be a local $defs reference")
        elif reference.removeprefix("#/$defs/") not in root.get("$defs", {}):
            errors.append(f"{path}: unresolved local $ref {reference!r}")
        return

    schema_type = node.get("type")
    if schema_type is not None:
        type_values = schema_type if isinstance(schema_type, list) else [schema_type]
        if not type_values or not all(
            isinstance(item, str) and item in JSON_TYPES for item in type_values
        ):
            errors.append(f"{path}.type: expected a supported JSON type or non-empty type list")
        elif len(set(type_values)) != len(type_values):
            errors.append(f"{path}.type: duplicate type entries are forbidden")

    required = node.get("required")
    if required is not None and (
        not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or len(set(required)) != len(required)
    ):
        errors.append(f"{path}.required: expected a unique string list")

    properties = node.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            errors.append(f"{path}.properties: expected an object")
        else:
            for name, child in properties.items():
                _validate_schema_node(child, f"{path}.properties.{name}", root, errors)

    additional = node.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        errors.append(f"{path}.additionalProperties: only literal booleans are supported")

    if "items" in node:
        _validate_schema_node(node["items"], f"{path}.items", root, errors)

    for keyword in ("minItems", "maxItems", "minLength"):
        if keyword in node and (not _is_int(node[keyword]) or node[keyword] < 0):
            errors.append(f"{path}.{keyword}: expected a non-negative integer")
    if "minItems" in node and "maxItems" in node and node["minItems"] > node["maxItems"]:
        errors.append(f"{path}: minItems cannot exceed maxItems")
    if "uniqueItems" in node and not isinstance(node["uniqueItems"], bool):
        errors.append(f"{path}.uniqueItems: expected a literal boolean")
    if "pattern" in node:
        if not isinstance(node["pattern"], str):
            errors.append(f"{path}.pattern: expected a string")
        else:
            try:
                re.compile(node["pattern"])
            except re.error as exc:
                errors.append(f"{path}.pattern: invalid regular expression: {exc}")
    for keyword in ("minimum", "maximum"):
        if keyword in node and not _is_number(node[keyword]):
            errors.append(f"{path}.{keyword}: expected a finite number")
    if "minimum" in node and "maximum" in node and node["minimum"] > node["maximum"]:
        errors.append(f"{path}: minimum cannot exceed maximum")

    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            errors.append(f"{path}.enum: expected a non-empty array")
        elif any(
            _json_equal(value, prior) for index, value in enumerate(enum) for prior in enum[:index]
        ):
            errors.append(f"{path}.enum: duplicate values are forbidden")

    one_of = node.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list) or not one_of:
            errors.append(f"{path}.oneOf: expected a non-empty schema list")
        else:
            for index, child in enumerate(one_of):
                _validate_schema_node(child, f"{path}.oneOf[{index}]", root, errors)
    if "not" in node:
        _validate_schema_node(node["not"], f"{path}.not", root, errors)

    if is_root:
        definitions = node.get("$defs")
        if not isinstance(definitions, dict) or not definitions:
            errors.append("$.$defs: expected a non-empty object")
        else:
            for name, child in definitions.items():
                if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                    errors.append(f"$.$defs: invalid definition name {name!r}")
                _validate_schema_node(child, f"$.$defs.{name}", root, errors)


def _collect_refs(node: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            refs.add(reference.removeprefix("#/$defs/"))
        for value in node.values():
            refs.update(_collect_refs(value))
    elif isinstance(node, list):
        for value in node:
            refs.update(_collect_refs(value))
    return refs


def _validate_ref_cycles(schema: dict[str, Any], errors: list[str]) -> None:
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        return
    graph = {name: _collect_refs(value) for name, value in definitions.items()}
    active: list[str] = []
    complete: set[str] = set()

    def visit(name: str) -> None:
        if name in complete:
            return
        if name in active:
            cycle = " -> ".join([*active[active.index(name) :], name])
            errors.append(f"cyclic $ref is forbidden: {cycle}")
            return
        active.append(name)
        for target in sorted(graph.get(name, set())):
            if target in graph:
                visit(target)
        active.pop()
        complete.add(name)

    for name in sorted(graph):
        visit(name)


def validate_schema_document(schema: Any) -> list[str]:
    """Validate the schema source against the closed stdlib profile."""

    if not isinstance(schema, dict):
        return ["Innovation Lab schema root must be an object"]
    errors: list[str] = []
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("schema $schema must pin JSON Schema Draft 2020-12")
    if schema.get("$id") != SCHEMA_VERSION:
        errors.append(f"schema $id must be {SCHEMA_VERSION!r}")
    if schema.get("x-nerva-schema-profile") != SCHEMA_PROFILE:
        errors.append(f"schema must pin x-nerva-schema-profile={SCHEMA_PROFILE!r}")
    _validate_schema_node(schema, "$", schema, errors, is_root=True)
    _validate_ref_cycles(schema, errors)
    return errors


def validate_schema_bytes(raw: bytes) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SCHEMA_SHA256:
        errors.append(f"pinned schema SHA-256 mismatch: expected {SCHEMA_SHA256}, got {digest}")
    decoded, decode_errors = decode_json_bytes(raw, "Innovation Lab schema")
    errors.extend(decode_errors)
    if not isinstance(decoded, dict):
        if decoded is not None:
            errors.append("Innovation Lab schema root must be an object")
        return None, errors
    errors.extend(validate_schema_document(decoded))
    return decoded, errors


def _instance_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": _is_number(value),
        "integer": _is_int(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[expected]


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    return root["$defs"][reference.removeprefix("#/$defs/")]


def _evaluate_schema(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
) -> list[str]:
    if "$ref" in schema:
        return _evaluate_schema(value, _resolve_ref(root, schema["$ref"]), root, path)
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_instance_type_matches(value, item) for item in expected_types):
            errors.append(f"{path}: type must be {expected!r}")
            return errors
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: value must equal const {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        errors.append(f"{path}: value is outside enum {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                errors.append(f"{path}.{name}: required property is missing")
        properties = schema.get("properties", {})
        for name, item in value.items():
            if name in properties:
                errors.extend(_evaluate_schema(item, properties[name], root, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{name}: additional property is forbidden")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: array has fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array has more than maxItems={schema['maxItems']}")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_json_equal(item, prior) for prior in value[:index]):
                    errors.append(f"{path}[{index}]: duplicate item violates uniqueItems")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_evaluate_schema(item, schema["items"], root, f"{path}[{index}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string is shorter than minLength={schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: string does not match pattern {schema['pattern']!r}")
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: number is below minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: number is above maximum={schema['maximum']}")

    if "oneOf" in schema:
        branch_errors = [_evaluate_schema(value, branch, root, path) for branch in schema["oneOf"]]
        matches = sum(not branch for branch in branch_errors)
        if matches != 1:
            details = "; ".join(
                f"branch {index}: {', '.join(branch[:2]) or 'matched'}"
                for index, branch in enumerate(branch_errors)
            )
            errors.append(f"{path}: oneOf matched {matches} branches ({details})")
    if "not" in schema and not _evaluate_schema(value, schema["not"], root, path):
        errors.append(f"{path}: value matched forbidden not schema")
    return errors


def evaluate_schema(value: Any, schema: dict[str, Any]) -> list[str]:
    """Evaluate a candidate with the supported, type-sensitive schema subset."""

    return _evaluate_schema(value, schema, schema, "$")


def _parse_time(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        errors.append(f"{label}: expected canonical UTC timestamp")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        errors.append(f"{label}: invalid calendar timestamp")
        return None


def _normalise_evidence_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _semantic_fingerprint(record: dict[str, Any]) -> str:
    payload = "\0".join(
        (
            record["integrity_sha256"],
            _normalise_evidence_text(record["claim"]),
            _normalise_evidence_text(record["limitations"]),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git(
    repo: Path,
    *args: str,
    binary: bool = False,
) -> bytes | str | None:
    try:
        # No shell is used; untrusted refs have already passed strict SHA validation.
        completed = subprocess.run(  # nosec B603, B607
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout


def _validate_catalogues(
    catalogues: list[dict[str, Any]],
    errors: list[str],
    *,
    repo: Path | None,
    verify_catalogues: bool,
    require_canonical_catalogues: bool,
) -> None:
    ids = [entry["id"] for entry in catalogues]
    if require_canonical_catalogues and ids != [entry["id"] for entry in KNOWN_CATALOGUES]:
        errors.append("canonical garden must retain the exact V1/V2/V3 catalogue anchor order")
    for index, entry in enumerate(catalogues):
        entry_id = entry["id"]
        expected = KNOWN_CATALOGUE_BY_ID.get(entry_id)
        if expected is not None and not _json_equal(entry, expected):
            errors.append(f"{entry_id}: immutable historical catalogue anchor drifted")
        supersedes = entry.get("supersedes")
        if supersedes is not None and supersedes not in ids[:index]:
            errors.append(f"{entry_id}: supersedes must name an earlier catalogue anchor")
        path = PurePosixPath(entry["path"])
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{entry_id}: catalogue path must remain repository-relative")
        if not verify_catalogues or repo is None or expected is None:
            continue
        commit = entry["accepted_merge_commit"]
        resolved = _git(repo, "rev-parse", f"{commit}^{{commit}}")
        if not isinstance(resolved, str) or resolved.strip() != commit:
            errors.append(f"{entry_id}: accepted merge commit is unavailable")
            continue
        blob = _git(repo, "rev-parse", f"{commit}:{entry['path']}")
        if not isinstance(blob, str) or blob.strip() != entry["git_blob_oid"]:
            errors.append(f"{entry_id}: historical Git blob OID does not match the anchor")
            continue
        raw = _git(repo, "cat-file", "blob", entry["git_blob_oid"], binary=True)
        if not isinstance(raw, bytes):
            errors.append(f"{entry_id}: historical catalogue blob is unavailable")
            continue
        if len(raw) != entry["content_bytes"]:
            errors.append(f"{entry_id}: historical catalogue byte count drifted")
        if hashlib.sha256(raw).hexdigest() != entry["content_sha256"]:
            errors.append(f"{entry_id}: historical catalogue SHA-256 drifted")


def _validate_stage_history(rfc: dict[str, Any], errors: list[str]) -> None:
    history = rfc["stage_history"]
    prior_stage: str | None = None
    prior_time: datetime | None = None
    for index, transition in enumerate(history):
        source = transition["from_stage"]
        target = transition["to_stage"]
        if source != prior_stage:
            errors.append(f"{rfc['id']}: stage_history is not contiguous at entry {index}")
        if (source, target) not in STAGE_TRANSITIONS:
            errors.append(f"{rfc['id']}: illegal stage transition {source!r} -> {target!r}")
        current_time = _parse_time(
            transition["at"], f"{rfc['id']}.stage_history[{index}].at", errors
        )
        if current_time is not None and prior_time is not None and current_time <= prior_time:
            errors.append(f"{rfc['id']}: stage_history timestamps must be strictly increasing")
        prior_stage = target
        prior_time = current_time
    if prior_stage != rfc["stage"]:
        errors.append(f"{rfc['id']}: stage must match the stage_history tail")


def _validate_outcome_history(rfc: dict[str, Any], errors: list[str]) -> None:
    history = rfc["outcome_history"]
    prior_status: str | None = None
    prior_time: datetime | None = None
    for index, transition in enumerate(history):
        source = transition["from_status"]
        target = transition["to_status"]
        if source != prior_status:
            errors.append(f"{rfc['id']}: outcome_history is not contiguous at entry {index}")
        if (source, target) not in OUTCOME_TRANSITIONS:
            errors.append(f"{rfc['id']}: illegal outcome transition {source!r} -> {target!r}")
        current_time = _parse_time(
            transition["at"], f"{rfc['id']}.outcome_history[{index}].at", errors
        )
        if current_time is not None and prior_time is not None and current_time <= prior_time:
            errors.append(f"{rfc['id']}: outcome_history timestamps must be strictly increasing")
        prior_status = target
        prior_time = current_time


def _validate_evidence_fingerprints(records: list[dict[str, Any]], errors: list[str]) -> None:
    artifacts: dict[str, dict[str, Any]] = {}
    semantics: dict[str, str] = {}
    for record in records:
        if record["kind"] != "EVIDENCE":
            continue
        digest = record["integrity_sha256"]
        prior = artifacts.get(digest)
        if prior is not None and (
            record["evidence_class"] != prior["evidence_class"]
            or record["source_ref"] != prior["source_ref"]
        ):
            errors.append(
                f"{record['id']}: artifact fingerprint {digest} cannot change evidence_class or source_ref"
            )
        else:
            artifacts.setdefault(digest, record)
        semantic = _semantic_fingerprint(record)
        if semantic in semantics:
            errors.append(f"{record['id']}: semantic fingerprint duplicates {semantics[semantic]}")
        else:
            semantics[semantic] = record["id"]


def _validate_rfc(
    rfc: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    outgoing: dict[tuple[str, str], list[str]],
    incoming: dict[tuple[str, str], list[str]],
    errors: list[str],
) -> None:
    rfc_id = rfc["id"]
    _validate_stage_history(rfc, errors)
    _validate_outcome_history(rfc, errors)
    expected_id = f"{rfc['stable_id']}-R{rfc['revision']}"
    if rfc_id != expected_id:
        errors.append(f"{rfc_id}: RFC record id must equal stable_id plus revision")
    if rfc["authority"] != AUTHORITY:
        errors.append(f"{rfc_id}: per-RFC authority must retain the exact no-action contract")
    if not ACTOR_RE.fullmatch(rfc["author_id"]):
        errors.append(f"{rfc_id}: author_id must be a canonical ASCII lowercase slug")

    supported_ids = outgoing.get((rfc_id, "SUPPORTED_BY"), [])
    challenged_ids = outgoing.get((rfc_id, "CHALLENGED_BY"), [])
    evidence_ids = [*supported_ids, *challenged_ids]
    stage = rfc["stage"]
    if stage in {"EVIDENCE_GATHERING", "READY_FOR_REVIEW", "DECIDED", "OUTCOME_REVIEWED"}:
        baseline_ref = rfc["benchmark"]["baseline_ref"]
        if baseline_ref not in evidence_ids:
            errors.append(f"{rfc_id}: benchmark baseline_ref must resolve to exact-RFC evidence")
    if stage in {"READY_FOR_REVIEW", "DECIDED", "OUTCOME_REVIEWED"}:
        for name in ("authority", "security", "privacy", "data_retention", "compatibility"):
            if rfc["assessments"][name]["status"] != "assessed":
                errors.append(f"{rfc_id}: {name} must be assessed before review or decision")
    if rfc["external_code_involved"]:
        for name in ("license", "supply_chain"):
            if rfc["assessments"][name]["status"] != "assessed":
                errors.append(f"{rfc_id}: external code requires assessed {name}")
    privacy = rfc["assessments"]["privacy"]
    if privacy["private_data_policy"] == "local_only_fixture" and (
        not isinstance(privacy["policy_ref"], str) or not privacy["policy_ref"].strip()
    ):
        errors.append(f"{rfc_id}: local_only_fixture requires a non-whitespace policy_ref")

    prototype_ids = outgoing.get((rfc_id, "TESTED_BY"), [])
    first_ready = next(
        (
            transition
            for transition in rfc["stage_history"]
            if transition["to_stage"] == "READY_FOR_REVIEW"
        ),
        None,
    )
    if rfc["prototype_disposition"]["status"] == "required":
        prototype_required_now = first_ready is not None or stage in {"DECIDED", "OUTCOME_REVIEWED"}
        if len(prototype_ids) > 1 or (prototype_required_now and len(prototype_ids) != 1):
            errors.append(f"{rfc_id}: required prototype needs exactly one TESTED_BY link")
        elif len(prototype_ids) == 1:
            prototype = by_id[prototype_ids[0]]
            required_prefix = f"nerva-lab/{rfc_id.lower()}-"
            if not prototype["branch"].startswith(required_prefix):
                errors.append(
                    f"{prototype['id']}: branch must bind the exact RFC record via {required_prefix}"
                )
            if prototype["private_data_policy"] == "local_only_fixture" and (
                not isinstance(prototype["policy_ref"], str) or not prototype["policy_ref"].strip()
            ):
                errors.append(
                    f"{prototype['id']}: local_only_fixture requires a non-whitespace policy_ref"
                )
            tested_at = _parse_time(prototype["tested_at"], f"{prototype['id']}.tested_at", errors)
            initial_draft_at = _parse_time(
                rfc["stage_history"][0]["at"],
                f"{rfc_id}.initial_DRAFT",
                errors,
            )
            if (
                tested_at is not None
                and initial_draft_at is not None
                and tested_at < initial_draft_at
            ):
                errors.append(
                    f"{prototype['id']}: tested_at must be no earlier than RFC initial DRAFT"
                )
            if first_ready is not None:
                ready_at = _parse_time(
                    first_ready["at"], f"{rfc_id}.first_READY_FOR_REVIEW", errors
                )
                if tested_at is not None and ready_at is not None and tested_at > ready_at:
                    errors.append(
                        f"{prototype['id']}: tested_at must be no later than first READY_FOR_REVIEW"
                    )
            prototype_decisions = outgoing.get((rfc_id, "DECIDED_BY"), [])
            if len(prototype_decisions) == 1:
                decided_at = _parse_time(
                    by_id[prototype_decisions[0]]["decided_at"],
                    f"{prototype_decisions[0]}.decided_at",
                    errors,
                )
                if tested_at is not None and decided_at is not None and tested_at >= decided_at:
                    errors.append(f"{prototype['id']}: tested_at must be before the decision")
    elif prototype_ids:
        errors.append(f"{rfc_id}: not_required prototype disposition forbids TESTED_BY links")

    decision_ids = outgoing.get((rfc_id, "DECIDED_BY"), [])
    if stage in {"DECIDED", "OUTCOME_REVIEWED"}:
        if len(decision_ids) != 1:
            errors.append(f"{rfc_id}: decided RFC requires exactly one DECIDED_BY link")
            return
    elif decision_ids:
        errors.append(f"{rfc_id}: undecided RFC must not have a DECIDED_BY link")
        return
    else:
        if rfc["outcome_history"]:
            errors.append(f"{rfc_id}: undecided RFC must keep outcome_history empty")
        return

    decision = by_id[decision_ids[0]]
    decision_id = decision["id"]
    if not ACTOR_RE.fullmatch(decision["reviewer_id"]):
        errors.append(f"{decision_id}: reviewer_id must be a canonical ASCII lowercase slug")
    if decision["reviewer_id"] == rfc["author_id"]:
        errors.append(f"{decision_id}: reviewer must be independent from the RFC author")
    decided_transition = next(
        (item for item in rfc["stage_history"] if item["to_stage"] == "DECIDED"),
        None,
    )
    if decided_transition is None or decided_transition["at"] != decision["decided_at"]:
        errors.append(f"{rfc_id}: DECIDED transition must bind the decision timestamp")
    decision_time = _parse_time(decision["decided_at"], f"{decision_id}.decided_at", errors)

    predecision_supported_ids: set[str] = set()
    predecision_challenged_ids: set[str] = set()
    for record_ids, predecision_ids_for_relation in (
        (supported_ids, predecision_supported_ids),
        (challenged_ids, predecision_challenged_ids),
    ):
        for record_id in record_ids:
            record = by_id[record_id]
            observed = _parse_time(record["observed_at"], f"{record['id']}.observed_at", errors)
            if observed is not None and decision_time is not None and observed <= decision_time:
                predecision_ids_for_relation.add(record_id)
    predecision_ids = predecision_supported_ids | predecision_challenged_ids
    if set(decision["evidence_refs"]) != predecision_ids:
        errors.append(
            f"{decision_id}: evidence_refs must equal the exact-RFC evidence observed by the decision"
        )
    status = decision["status"]
    if status == "ACCEPTED_FOR_EPIC" and not any(
        by_id[item]["evidence_class"] in STRONG_EVIDENCE for item in predecision_supported_ids
    ):
        errors.append(
            f"{decision_id}: ACCEPTED_FOR_EPIC requires strong pre-decision SUPPORTED_BY evidence"
        )
    if status == "ACCEPTED_FOR_EPIC":
        baseline_ref = rfc["benchmark"]["baseline_ref"]
        if (
            baseline_ref not in predecision_supported_ids
            or by_id[baseline_ref]["evidence_class"] != "benchmark"
        ):
            errors.append(
                f"{rfc_id}: benchmark baseline_ref must resolve to pre-decision "
                "SUPPORTED_BY benchmark evidence"
            )
    if status == "REJECTED" and not any(
        by_id[item]["evidence_class"] in STRONG_EVIDENCE for item in predecision_challenged_ids
    ):
        errors.append(
            f"{decision_id}: REJECTED requires strong pre-decision CHALLENGED_BY evidence"
        )

    epic_ids = outgoing.get((decision_id, "ACCEPTED_AS"), [])
    outcome_tail = rfc["outcome_history"][-1]["to_status"] if rfc["outcome_history"] else None
    if status == "ACCEPTED_FOR_EPIC":
        if decided_transition is None or decided_transition["from_stage"] != "READY_FOR_REVIEW":
            errors.append(f"{rfc_id}: ACCEPTED_FOR_EPIC requires READY_FOR_REVIEW")
        if decision["unresolved_requirements"]:
            errors.append(f"{decision_id}: accepted decision cannot retain unresolved requirements")
        if len(epic_ids) != 1:
            errors.append(f"{decision_id}: accepted decision requires exactly one separate epic")
            return
        epic = by_id[epic_ids[0]]
        if epic["issue"] == PROGRAM_ISSUE:
            errors.append(f"{epic['id']}: #805 cannot be its own delivery epic")
        if not rfc["outcome_history"] or rfc["outcome_history"][0]["to_status"] != "pending":
            errors.append(f"{rfc_id}: accepted RFC outcome_history must begin pending")
        elif rfc["outcome_history"][0]["at"] != decision["decided_at"]:
            errors.append(f"{rfc_id}: pending outcome must start at the decision timestamp")
        outcome_ids = outgoing.get((epic["id"], "PRODUCED"), [])
        if stage == "DECIDED":
            if outcome_tail != "pending" or outcome_ids:
                errors.append(f"{rfc_id}: pending accepted RFC must not claim an outcome")
        else:
            if outcome_tail != "linked" or len(outcome_ids) != 1:
                errors.append(f"{rfc_id}: OUTCOME_REVIEWED requires one linked outcome")
                return
            outcome = by_id[outcome_ids[0]]
            final_stage = rfc["stage_history"][-1]
            final_outcome = rfc["outcome_history"][-1]
            if not (final_stage["at"] == final_outcome["at"] == outcome["measured_at"]):
                errors.append(
                    f"{rfc_id}: outcome, lifecycle, and outcome_history timestamps must bind"
                )
            outcome_time = _parse_time(
                outcome["measured_at"], f"{outcome['id']}.measured_at", errors
            )
            postdecision_ids: set[str] = set()
            for reference in outcome["evidence_refs"]:
                if reference not in evidence_ids:
                    errors.append(
                        f"{outcome['id']}: evidence_refs must use exact-RFC post-decision evidence"
                    )
                    continue
                record = by_id[reference]
                observed = _parse_time(record["observed_at"], f"{record['id']}.observed_at", errors)
                if (
                    observed is not None
                    and decision_time is not None
                    and observed > decision_time
                    and reference not in decision["evidence_refs"]
                ):
                    if outcome_time is not None and observed <= outcome_time:
                        postdecision_ids.add(reference)
                    else:
                        errors.append(
                            f"{record['id']}: outcome evidence must be observed no later than the outcome"
                        )
            if set(outcome["evidence_refs"]) != postdecision_ids:
                errors.append(
                    f"{outcome['id']}: outcome requires new exact-RFC post-decision evidence"
                )
            if outcome["claim_scope"] == "owner_live" and not any(
                by_id[reference]["evidence_class"] == "owner_live" for reference in postdecision_ids
            ):
                errors.append(f"{outcome['id']}: owner_live claim requires owner_live evidence")
    else:
        if epic_ids:
            errors.append(f"{decision_id}: {status} must not create an epic")
        if outcome_tail != "not_applicable" or len(rfc["outcome_history"]) != 1:
            errors.append(f"{rfc_id}: {status} outcome must remain not_applicable")
        if stage != "DECIDED":
            errors.append(f"{rfc_id}: {status} cannot enter OUTCOME_REVIEWED")
        if status == "PARKED" and not decision["unresolved_requirements"]:
            errors.append(f"{decision_id}: PARKED must name unresolved requirements")


def _validate_lineage(
    rfcs: list[dict[str, Any]],
    records: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    outgoing: dict[tuple[str, str], list[str]],
    incoming: dict[tuple[str, str], list[str]],
    errors: list[str],
) -> None:
    record_position = {record["id"]: index for index, record in enumerate(records)}
    groups: dict[str, list[dict[str, Any]]] = {}
    for rfc in rfcs:
        groups.setdefault(rfc["stable_id"], []).append(rfc)
    for stable_id, revisions in groups.items():
        revisions.sort(key=lambda item: item["revision"])
        expected_revisions = list(range(1, len(revisions) + 1))
        if [item["revision"] for item in revisions] != expected_revisions:
            errors.append(f"{stable_id}: revisions must be contiguous from 1")
            continue
        parent_ideas = {tuple(incoming.get((item["id"], "DEVELOPED_AS"), [])) for item in revisions}
        if len(parent_ideas) != 1:
            errors.append(f"{stable_id}: every revision must retain one stable parent IDEA")
        for index, current in enumerate(revisions):
            current_id = current["id"]
            supersedes = outgoing.get((current_id, "SUPERSEDES"), [])
            reopens = outgoing.get((current_id, "REOPENS"), [])
            if index == 0:
                if supersedes or reopens or current["reopens_decision_id"] is not None:
                    errors.append(f"{current_id}: first revision cannot supersede or reopen")
                continue
            prior = revisions[index - 1]
            if supersedes != [prior["id"]]:
                errors.append(
                    f"{current_id}: must supersede the exact direct predecessor {prior['id']}"
                )
            if record_position[prior["id"]] >= record_position[current_id]:
                errors.append(f"{current_id}: new revisions must point backward in record order")
            prior_decisions = outgoing.get((prior["id"], "DECIDED_BY"), [])
            if len(prior_decisions) != 1:
                errors.append(f"{current_id}: direct predecessor must retain exactly one decision")
                continue
            decision = by_id[prior_decisions[0]]
            decision_time = _parse_time(
                decision["decided_at"], f"{decision['id']}.decided_at", errors
            )
            initial_time = _parse_time(
                current["stage_history"][0]["at"],
                f"{current_id}.stage_history[0].at",
                errors,
            )
            if (
                decision_time is not None
                and initial_time is not None
                and initial_time <= decision_time
            ):
                errors.append(
                    f"{current_id}: successor initial stage must be strictly after predecessor decision"
                )
            if decision["status"] == "ACCEPTED_FOR_EPIC":
                errors.append(
                    f"{current_id}: accepted predecessor terminates its stable_id lineage; "
                    "follow-on work requires a new IDEA and stable_id"
                )
                if reopens or current["reopens_decision_id"] is not None:
                    errors.append(
                        f"{current_id}: REOPENS may target only a PARKED or REJECTED decision; "
                        "accepted history never reopens"
                    )
                continue
            if decision["status"] in {"PARKED", "REJECTED"}:
                if current["reopens_decision_id"] != decision["id"] or reopens != [decision["id"]]:
                    errors.append(
                        f"{current_id}: reopening requires a matching REOPENS edge and decision id"
                    )
                decision_artifacts = {
                    by_id[reference]["integrity_sha256"]
                    for reference in decision["evidence_refs"]
                    if reference in by_id
                }
                new_evidence = [
                    by_id[reference]
                    for relation in ("SUPPORTED_BY", "CHALLENGED_BY")
                    for reference in outgoing.get((current_id, relation), [])
                    if by_id[reference]["integrity_sha256"] not in decision_artifacts
                ]
                if not new_evidence:
                    errors.append(f"{current_id}: reopening requires a new artifact fingerprint")
                elif decision_time is not None and not any(
                    (
                        _parse_time(item["observed_at"], f"{item['id']}.observed_at", errors)
                        or decision_time
                    )
                    > decision_time
                    for item in new_evidence
                ):
                    errors.append(
                        f"{current_id}: reopening evidence must be observed after the prior decision"
                    )


def _validate_graph(data: dict[str, Any], errors: list[str]) -> None:
    records = data["records"]
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record["id"]
        if record_id in by_id:
            errors.append(f"duplicate record id: {record_id}")
        else:
            by_id[record_id] = record
    if len(by_id) != len(records):
        return

    epic_keys: dict[tuple[str, int], str] = {}
    for record in records:
        if record["kind"] != "EPIC":
            continue
        key = (record["repository"], record["issue"])
        if record["repository"] != "andrei649/jarvis-hub":
            errors.append(f"{record['id']}: EPIC repository must be andrei649/jarvis-hub")
        if record["issue"] == PROGRAM_ISSUE:
            errors.append(f"{record['id']}: #805 cannot be its own delivery epic")
        if key in epic_keys:
            errors.append(
                f"{record['id']}: EPIC repository/issue pair must be globally unique; "
                f"already used by {epic_keys[key]}"
            )
        else:
            epic_keys[key] = record["id"]

    outgoing: dict[tuple[str, str], list[str]] = {}
    incoming: dict[tuple[str, str], list[str]] = {}
    seen_links: set[tuple[str, str, str]] = set()
    evidence_dispositions: dict[tuple[str, str], set[str]] = {}
    adjacency: dict[str, list[str]] = {record_id: [] for record_id in by_id}
    for link in data["links"]:
        source = link["from"]
        relation = link["relation"]
        target = link["to"]
        identity = (source, relation, target)
        if identity in seen_links:
            errors.append(f"duplicate link: {source} {relation} {target}")
            continue
        seen_links.add(identity)
        if source not in by_id:
            errors.append(f"dangling link source: {source}")
            continue
        if target not in by_id:
            errors.append(f"dangling link target: {target}")
            continue
        expected_kinds = ALLOWED_LINKS[relation]
        actual_kinds = (by_id[source]["kind"], by_id[target]["kind"])
        if actual_kinds != expected_kinds:
            errors.append(f"illegal link {relation}: expected {expected_kinds}, got {actual_kinds}")
            continue
        outgoing.setdefault((source, relation), []).append(target)
        incoming.setdefault((target, relation), []).append(source)
        adjacency[source].append(target)
        if relation in {"SUPPORTED_BY", "CHALLENGED_BY"}:
            pair = (source, target)
            evidence_dispositions.setdefault(pair, set()).add(relation)

    for (rfc_id, evidence_id), relations in evidence_dispositions.items():
        if relations == {"SUPPORTED_BY", "CHALLENGED_BY"}:
            errors.append(
                f"{rfc_id}/{evidence_id}: same RFC/evidence pair cannot be both "
                "SUPPORTED_BY and CHALLENGED_BY"
            )

    ownership = {
        "RFC": ("DEVELOPED_AS", "exactly one DEVELOPED_AS owner"),
        "PROTOTYPE": ("TESTED_BY", "exactly one RFC prototype owner"),
        "DECISION": ("DECIDED_BY", "DECISION must be owned by exactly one RFC"),
        "EPIC": ("ACCEPTED_AS", "EPIC must be owned by exactly one accepted decision"),
        "OUTCOME": ("PRODUCED", "OUTCOME must be owned by exactly one EPIC"),
    }
    for record in records:
        kind = record["kind"]
        if kind == "OBSERVATION":
            owner_count = sum(
                len(values)
                for (target, _relation), values in incoming.items()
                if target == record["id"]
            )
            if owner_count:
                errors.append(f"{record['id']}: OBSERVATION must remain a graph root")
            continue
        if kind == "IDEA":
            if not incoming.get((record["id"], "MOTIVATES"), []):
                errors.append(f"{record['id']}: IDEA requires at least one MOTIVATES owner")
            rfc_ids = outgoing.get((record["id"], "DEVELOPED_AS"), [])
            stable_ids = {by_id[rfc_id]["stable_id"] for rfc_id in rfc_ids}
            if len(stable_ids) > 1:
                errors.append(f"{record['id']}: IDEA may own only one stable_id lineage")
            continue
        if kind == "EVIDENCE":
            owner_ids = [
                *incoming.get((record["id"], "SUPPORTED_BY"), []),
                *incoming.get((record["id"], "CHALLENGED_BY"), []),
            ]
            if not owner_ids:
                errors.append(f"{record['id']}: EVIDENCE requires at least one RFC owner")
            elif len({by_id[owner_id]["stable_id"] for owner_id in owner_ids}) != 1:
                errors.append(
                    f"{record['id']}: EVIDENCE owners must share exactly one stable_id lineage"
                )
            continue
        relation_spec, message = ownership[kind]
        relations = relation_spec if isinstance(relation_spec, tuple) else (relation_spec,)
        count = sum(len(incoming.get((record["id"], relation), [])) for relation in relations)
        if count != 1:
            errors.append(f"{record['id']}: {message}")

    roots = [record["id"] for record in records if record["kind"] == "OBSERVATION"]
    reachable = set(roots)
    pending = list(roots)
    while pending:
        source = pending.pop()
        for target in adjacency.get(source, []):
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    for record_id in by_id:
        if record_id not in reachable:
            errors.append(f"{record_id}: every record must be reachable from an OBSERVATION")

    _validate_evidence_fingerprints(records, errors)
    rfcs = [record for record in records if record["kind"] == "RFC"]
    for rfc in rfcs:
        _validate_rfc(rfc, by_id, outgoing, incoming, errors)
    _validate_lineage(rfcs, records, by_id, outgoing, incoming, errors)


def validate_bundle(
    data: Any,
    *,
    schema: dict[str, Any] | None = None,
    repo: Path | None = None,
    verify_catalogues: bool = False,
    require_canonical_catalogues: bool = False,
) -> list[str]:
    """Run schema then semantic validation over one candidate garden."""

    errors: list[str] = []
    if schema is None:
        raw = (REPO / SCHEMA_REL).read_bytes()
        schema, schema_errors = validate_schema_bytes(raw)
        errors.extend(schema_errors)
        if schema is None:
            return errors
    else:
        errors.extend(validate_schema_document(schema))
    if errors:
        return errors
    schema_errors = evaluate_schema(data, schema)
    if schema_errors:
        return schema_errors
    if not isinstance(data, dict):
        return ["candidate Knowledge Garden root must be an object"]
    if data["authority_ceiling"] != AUTHORITY:
        errors.append("top-level authority ceiling must retain the exact no-action contract")
    _validate_catalogues(
        data["catalogues"],
        errors,
        repo=repo,
        verify_catalogues=verify_catalogues,
        require_canonical_catalogues=require_canonical_catalogues,
    )
    _validate_graph(data, errors)
    return errors


def _prefix_equal(baseline: list[Any], candidate: list[Any]) -> bool:
    return len(candidate) >= len(baseline) and all(
        _json_equal(item, candidate[index]) for index, item in enumerate(baseline)
    )


def _accepted_rfc_ids(bundle: dict[str, Any]) -> set[str]:
    by_id = {record["id"]: record for record in bundle.get("records", [])}
    accepted: set[str] = set()
    for link in bundle.get("links", []):
        if link.get("relation") != "DECIDED_BY":
            continue
        decision = by_id.get(link.get("to"))
        if decision and decision.get("status") == "ACCEPTED_FOR_EPIC":
            accepted.add(link["from"])
    return accepted


def compare_append_only(baseline: Any, candidate: Any) -> list[str]:
    """Compare an accepted baseline with a candidate without trusting record IDs."""

    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return ["baseline and candidate gardens must be objects"]
    errors: list[str] = []
    for field in ("schema_version", "program_issue", "authority_ceiling"):
        if not _json_equal(baseline.get(field), candidate.get(field)):
            errors.append(f"top-level {field} is immutable after bootstrap")
    for field in ("catalogues", "links"):
        base_items = baseline.get(field)
        candidate_items = candidate.get(field)
        if not isinstance(base_items, list) or not isinstance(candidate_items, list):
            errors.append(f"{field} must remain arrays")
        elif not _prefix_equal(base_items, candidate_items):
            errors.append(
                f"{field} must retain the baseline prefix with exact canonical-JSON semantics"
            )

    base_records = baseline.get("records")
    candidate_records = candidate.get("records")
    if not isinstance(base_records, list) or not isinstance(candidate_records, list):
        errors.append("records must remain arrays")
        return errors
    if len(candidate_records) < len(base_records):
        errors.append("records cannot be deleted from the accepted baseline")
        return errors
    for index, prior in enumerate(base_records):
        current = candidate_records[index]
        if not isinstance(prior, dict) or not isinstance(current, dict):
            errors.append(f"records[{index}]: prior record shape is immutable")
            continue
        if prior.get("id") != current.get("id") or prior.get("kind") != current.get("kind"):
            errors.append(f"records[{index}]: record order/identity is immutable")
            continue
        if prior.get("kind") != "RFC":
            if not _json_equal(prior, current):
                errors.append(f"{prior.get('id')}: immutable prior record was rewritten")
            continue
        for field, value in prior.items():
            if field in {"stage", "stage_history", "outcome_history"}:
                continue
            if field not in current or not _json_equal(value, current[field]):
                errors.append(f"{prior['id']}: immutable RFC core field {field!r} was rewritten")
        if set(current) != set(prior):
            errors.append(f"{prior['id']}: RFC core property set is immutable")
        if not _prefix_equal(prior["stage_history"], current["stage_history"]):
            errors.append(f"{prior['id']}: stage_history must retain the baseline prefix")
        if not _prefix_equal(prior["outcome_history"], current["outcome_history"]):
            errors.append(f"{prior['id']}: outcome_history must retain the baseline prefix")

    base_ids = {record["id"] for record in base_records if isinstance(record, dict)}
    candidate_by_id = {
        record["id"]: record for record in candidate_records if isinstance(record, dict)
    }
    baseline_by_id = {record["id"]: record for record in base_records if isinstance(record, dict)}
    accepted_rfcs = _accepted_rfc_ids(baseline)
    nonterminal_rfcs = {
        record_id
        for record_id, record in baseline_by_id.items()
        if record.get("kind") == "RFC"
        and record.get("stage") in {"DRAFT", "EVIDENCE_GATHERING", "READY_FOR_REVIEW"}
    }
    base_links = baseline.get("links", []) if isinstance(baseline.get("links"), list) else []
    candidate_links = candidate.get("links", []) if isinstance(candidate.get("links"), list) else []
    baseline_evidence_owner_stable_ids: dict[str, set[str]] = {}
    for link in base_links:
        if not isinstance(link, dict) or link.get("relation") not in {
            "SUPPORTED_BY",
            "CHALLENGED_BY",
        }:
            continue
        owner = baseline_by_id.get(link.get("from"), {})
        stable_id = owner.get("stable_id") if owner.get("kind") == "RFC" else None
        target = link.get("to")
        if isinstance(stable_id, str) and isinstance(target, str):
            baseline_evidence_owner_stable_ids.setdefault(target, set()).add(stable_id)
    candidate_evidence_pair_relations: dict[tuple[str, str], set[str]] = {}
    for link in candidate_links:
        if not isinstance(link, dict) or link.get("relation") not in {
            "SUPPORTED_BY",
            "CHALLENGED_BY",
        }:
            continue
        source = link.get("from")
        target = link.get("to")
        if isinstance(source, str) and isinstance(target, str):
            candidate_evidence_pair_relations.setdefault((source, target), set()).add(
                link["relation"]
            )
    for link in candidate_links[len(base_links) :]:
        source = link.get("from")
        target = link.get("to")
        relation = link.get("relation")
        if source not in base_ids and target not in base_ids:
            continue
        source_kind = candidate_by_id.get(source, {}).get("kind")
        target_kind = candidate_by_id.get(target, {}).get("kind")
        retained_evidence_extension = (
            relation in {"SUPPORTED_BY", "CHALLENGED_BY"}
            and source in base_ids
            and target in base_ids
            and source_kind == "RFC"
            and target_kind == "EVIDENCE"
        )
        retained_evidence_allowed = False
        retained_evidence_error: str | None = None
        if retained_evidence_extension and source in nonterminal_rfcs:
            pair_relations = candidate_evidence_pair_relations.get((source, target), set())
            if pair_relations == {"SUPPORTED_BY", "CHALLENGED_BY"}:
                retained_evidence_error = (
                    f"new link {source} {relation} {target} cannot make one RFC/evidence pair "
                    "both SUPPORTED_BY and CHALLENGED_BY"
                )
            else:
                source_stable_id = baseline_by_id[source].get("stable_id")
                evidence_stable_ids = baseline_evidence_owner_stable_ids.get(target, set())
                if evidence_stable_ids != {source_stable_id}:
                    retained_evidence_error = (
                        f"new link {source} {relation} {target} must retain the evidence's "
                        "same stable_id lineage"
                    )
                else:
                    retained_evidence_allowed = True
        allowed_extension = (
            (
                relation == "MOTIVATES"
                and source_kind == "OBSERVATION"
                and source in base_ids
                and target_kind == "IDEA"
                and target not in base_ids
            )
            or (
                relation == "MOTIVATES"
                and source_kind == "OBSERVATION"
                and source not in base_ids
                and target_kind == "IDEA"
                and target in base_ids
            )
            or (
                relation == "DEVELOPED_AS"
                and source_kind == "IDEA"
                and source in base_ids
                and target_kind == "RFC"
                and target not in base_ids
            )
            or (
                relation in {"SUPERSEDES", "REOPENS"}
                and source_kind == "RFC"
                and source not in base_ids
                and target in base_ids
            )
            or (
                relation in {"SUPPORTED_BY", "CHALLENGED_BY"}
                and source in nonterminal_rfcs | accepted_rfcs
                and target_kind == "EVIDENCE"
                and target not in base_ids
            )
            or (
                relation in {"SUPPORTED_BY", "CHALLENGED_BY"}
                and source_kind == "RFC"
                and source not in base_ids
                and target_kind == "EVIDENCE"
                and target in base_ids
            )
            or retained_evidence_allowed
            or (
                relation == "TESTED_BY"
                and source in nonterminal_rfcs
                and target_kind == "PROTOTYPE"
                and target not in base_ids
            )
            or (
                relation == "DECIDED_BY"
                and source in nonterminal_rfcs
                and target_kind == "DECISION"
                and target not in base_ids
            )
            or (
                relation == "PRODUCED"
                and source_kind == "EPIC"
                and source in base_ids
                and target_kind == "OUTCOME"
                and target not in base_ids
            )
        )
        if not allowed_extension:
            errors.append(
                retained_evidence_error
                or f"new link {source} {relation} {target} illegally extends a frozen baseline edge"
            )
    return errors


def validate_git_refs(repo: Path, baseline_ref: str, candidate_ref: str) -> list[str]:
    """Validate immutable commit inputs before reading any governed documents."""

    errors: list[str] = []
    if not HEX40_RE.fullmatch(baseline_ref) or not HEX40_RE.fullmatch(candidate_ref):
        return ["--baseline-ref and --candidate-ref must be exact lowercase 40-hex SHAs"]
    shallow = _git(repo, "rev-parse", "--is-shallow-repository")
    if not isinstance(shallow, str):
        return ["unable to determine Git shallow state"]
    if shallow.strip() == "true":
        errors.append("shallow repository cannot prove baseline ancestry")
    for label, commit in (("baseline", baseline_ref), ("candidate", candidate_ref)):
        resolved = _git(repo, "rev-parse", f"{commit}^{{commit}}")
        if not isinstance(resolved, str) or resolved.strip() != commit:
            errors.append(f"{label} commit {commit} is missing or unresolved")
    head = _git(repo, "rev-parse", "HEAD")
    if not isinstance(head, str) or head.strip() != candidate_ref:
        errors.append("candidate-ref must equal HEAD exactly")
    ancestry = _git(repo, "merge-base", "--is-ancestor", baseline_ref, candidate_ref)
    if ancestry is None:
        errors.append("baseline-ref must be an ancestor of candidate-ref")
    return errors


def _read_git_path(repo: Path, commit: str, path: str) -> bytes | None:
    result = _git(repo, "show", f"{commit}:{path}", binary=True)
    return result if isinstance(result, bytes) else None


def validate_repository(repo: Path, baseline_ref: str, candidate_ref: str) -> list[str]:
    """Validate only immutable Git objects, then compare the accepted baseline."""

    repo = repo.resolve()
    errors = validate_git_refs(repo, baseline_ref, candidate_ref)
    if errors:
        return errors
    candidate_schema_raw = _read_git_path(repo, candidate_ref, SCHEMA_REL)
    candidate_garden_raw = _read_git_path(repo, candidate_ref, GARDEN_REL)
    if candidate_schema_raw is None:
        errors.append(f"candidate is missing {SCHEMA_REL}")
    if candidate_garden_raw is None:
        errors.append(f"candidate is missing {GARDEN_REL}")
    if errors:
        return errors

    baseline_schema_raw = _read_git_path(repo, baseline_ref, SCHEMA_REL)
    baseline_garden_raw = _read_git_path(repo, baseline_ref, GARDEN_REL)
    baseline_missing = (baseline_schema_raw is None, baseline_garden_raw is None)
    if baseline_missing.count(True) == 1:
        errors.append(
            "baseline contains only one governed path; bootstrap requires both schema and garden to be absent"
        )
        return errors
    bootstrap = all(baseline_missing)

    if candidate_schema_raw is None or candidate_garden_raw is None:
        return [*errors, "candidate governed Git objects became unavailable"]
    schema, schema_errors = validate_schema_bytes(candidate_schema_raw)
    errors.extend(schema_errors)
    candidate, decode_errors = decode_json_bytes(candidate_garden_raw, "candidate Knowledge Garden")
    errors.extend(decode_errors)
    if schema is None or not isinstance(candidate, dict):
        if candidate is not None and not isinstance(candidate, dict):
            errors.append("candidate Knowledge Garden root must be an object")
        return errors
    errors.extend(
        validate_bundle(
            candidate,
            schema=schema,
            repo=repo,
            verify_catalogues=True,
            require_canonical_catalogues=True,
        )
    )
    if not bootstrap:
        if baseline_schema_raw is None or baseline_garden_raw is None:
            return [*errors, "baseline governed Git objects became unavailable"]
        if baseline_schema_raw != candidate_schema_raw:
            errors.append("accepted baseline schema bytes and semantics are immutable")
        baseline, decode_errors = decode_json_bytes(
            baseline_garden_raw, "baseline Knowledge Garden"
        )
        errors.extend(decode_errors)
        if isinstance(baseline, dict):
            errors.extend(validate_bundle(baseline, schema=schema))
            errors.extend(compare_append_only(baseline, candidate))
        elif baseline is not None:
            errors.append("baseline Knowledge Garden root must be an object")

    document_raw = _read_git_path(repo, candidate_ref, DOCUMENT_REL)
    workflow_raw = _read_git_path(repo, candidate_ref, WORKFLOW_REL)
    if document_raw is None:
        errors.append(f"candidate is missing {DOCUMENT_REL}")
    else:
        document = document_raw.decode("utf-8", errors="replace")
        for phrase in (
            "nerva.stdlib-schema-profile.v1",
            "append-only",
            "CATALOGUE-EXTERNAL-INTEGRATIONS-V1",
            "CATALOGUE-EXTERNAL-INTEGRATIONS-V2",
            "CATALOGUE-EXTERNAL-INTEGRATIONS-V3",
            "#805 remains open and `DISCOVERY`",
        ):
            if phrase not in document:
                errors.append(f"Innovation Lab contract is missing required invariant: {phrase}")
    if workflow_raw is None:
        errors.append(f"candidate is missing {WORKFLOW_REL}")
    else:
        workflow = workflow_raw.decode("utf-8", errors="replace")
        for phrase in (
            "fetch-depth: 0",
            "persist-credentials: false",
            "--baseline-ref",
            "--candidate-ref",
            "github.event.pull_request.base.sha",
            "github.event.pull_request.head.sha",
            "github.event.before",
            "github.event.after",
        ):
            if phrase not in workflow:
                errors.append(f"Nerva roadmap workflow is missing fail-closed input: {phrase}")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the fail-closed Nerva Innovation Lab control from immutable Git refs."
    )
    parser.add_argument(
        "--baseline-ref", required=True, help="Exact lowercase 40-hex baseline commit"
    )
    parser.add_argument(
        "--candidate-ref", required=True, help="Exact lowercase 40-hex candidate commit"
    )
    parser.add_argument("--repo", type=Path, default=REPO, help="Repository root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    errors = validate_repository(args.repo, args.baseline_ref, args.candidate_ref)
    if errors:
        print("Innovation Lab validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Innovation Lab validation passed: pinned schema, closed graph, append-only Git baseline, no delivery authority."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
