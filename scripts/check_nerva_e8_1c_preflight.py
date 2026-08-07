"""Validate and render the evidence-only Nerva E8.1c Hermes preflight.

The checker is intentionally offline and standard-library-only.  It validates a
time-bounded public-source evidence snapshot; it never imports, installs,
downloads, or executes Hermes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVIDENCE_RELATIVE = Path("docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.json")
DOCUMENT_RELATIVE = Path("docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md")

UPSTREAM_REPOSITORY = "NousResearch/hermes-agent"
UPSTREAM_TAG = "v2026.8.3"
UPSTREAM_COMMIT = "3c27eb6234bf91b8ceee9e9071591b31e9b148cb"
UPSTREAM_TREE = "b217767ccb994605dad522e693fa1b4cdbc2f352"
UPSTREAM_TAG_OBJECT = "7de39e700d2c329e15d32eb0b96e2f7cdd9fbdb2"

EXPECTED_SOURCE_FILES = {
    ".github/workflows/docker.yml": (
        "7e47b1db693b68d8b4c68f1d5611c3055c365543",
        "c32901e3327877c14eb57cd9a5d7c4c56a95a5587c09de6aa42d6008d93d2ecc",
        11839,
    ),
    "Dockerfile": (
        "2de6192715ed9a839c257b1f34f98d0832797159",
        "a11fc9fc39eadcaffd99377d831b5ec2458f1e09a5f5d5312fd8adcec362b7fc",
        25687,
    ),
    "docker/entrypoint-dispatch.sh": (
        "927ed032f6d821e5bc9d047aed10e37f125d5a6a",
        "d6f8e569fd2bfbf8d1f45619243681b9a1390c5bd3c9c584532692893b1d4fcd",
        1123,
    ),
    "docker/hermes-exec-shim.sh": (
        "7f4c5c3c0a0e9216b262e6ecf7b96cf868f0a4ce",
        "57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985",
        3711,
    ),
    "docker/stage2-hook.sh": (
        "899c8e86ac989735a27d67cb3b11df88762bbb9b",
        "942cc3c8c9df4168c58c30dc961b43e322c6d3cfb007e1a56f2c9ede48c710a7",
        28558,
    ),
    "LICENSE": (
        "75410e73319c72cd3e991a501c5455eb78f38375",
        "821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6",
        1070,
    ),
    "skills/productivity/docx/LICENSE.txt": (
        "c55ab42224874608473643de0a85736b7fec0730",
        "79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa",
        1467,
    ),
    "skills/productivity/pdf/LICENSE.txt": (
        "c55ab42224874608473643de0a85736b7fec0730",
        "79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa",
        1467,
    ),
    "skills/productivity/powerpoint/LICENSE.txt": (
        "c55ab42224874608473643de0a85736b7fec0730",
        "79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa",
        1467,
    ),
    "skills/productivity/xlsx/LICENSE.txt": (
        "c55ab42224874608473643de0a85736b7fec0730",
        "79f6d8f5b427252fa3b1c11ecdbdb6bf610b944f7530b4de78f770f38741cfaa",
        1467,
    ),
    "pyproject.toml": (
        "b9578f3fc53e701c2c9966d7aa5b7eeae574a2db",
        "64d1085ee1c23caf0ae0d9e65c73e280f466362ed43fdda1531f18f3af1d9869",
        23044,
    ),
    "uv.lock": (
        "592d5db2612fc0e306a42e8eccabf9b7856cd3c4",
        "aab3c83f71b683507a590b6315b23bdc0abd6b63b76b2349eae15bf00dfbaf2b",
        715301,
    ),
    "run_agent.py": (
        "e2bc5f8660bd6bfd101175cf55131a7c9e253a31",
        "7d22f38b5eac3b2951fa28aec5b2b06ec007bc96d88e5d35278481bf2ab52122",
        364804,
    ),
    "hermes_bootstrap.py": (
        "c0622bb0d96162b825be102896e4c01af6eb5062",
        "225112594c045e57b9413c3054948da865febeba589c0c4d1b5c9c1bda0b5d28",
        10514,
    ),
    "hermes_cli/_early_recovery.py": (
        "7a19167eca04bcd3755fac521fead07529f5e4ef",
        "3215692e4d5e1ab9bf255fd25c5c35f82afe6525bb430c50f9de10e4ad1a7ff4",
        10716,
    ),
    "hermes_cli/_parser.py": (
        "b5098f6c98d6891d090db73a66d03d3ac6c51ff7",
        "30621be86ee4d30322e106b318b211c7a7ffe1f271688436849a4b80bb3f4d2c",
        17625,
    ),
    "hermes_cli/main.py": (
        "cd9966cf8cff6b3a93d5a24d61b2a84a9b7d49d8",
        "f27fcee078bc3696d4c37fa98d04972e214d53b01bd6075f12e988ef69d6c241",
        504355,
    ),
    "hermes_cli/oneshot.py": (
        "f13fe64029d5cde2acab4584968275a62fa1319a",
        "dab3aea137b5c8f19c0835c7393a729ff982f16c18ded3e155aa549fc087e8c2",
        21819,
    ),
    "setup.py": (
        "fac7fe88161e7aae1033f163fb9bf0705b825b73",
        "b81382e9c4d1bc10694c42177edec65fdab9afe6511dd4c43b2279440b6ad13e",
        2920,
    ),
    "toolsets.py": (
        "f4bb3c3343a99e3100abfa5e9d8ed10c33fe2efc",
        "35658a881a40913ea3bd54b9bb0b5a355ae0cf18abb2e249b48833218be572b3",
        36388,
    ),
}

EXPECTED_CONSOLE_SCRIPTS = {
    "hermes": "hermes_cli.main:main",
    "hermes-agent": "run_agent:main",
}

EXPECTED_SURFACE_DECISIONS = {
    "hermes-agent": "rejected",
    "hermes-oneshot": "candidate_not_executed",
}

REQUIRED_HERMES_AGENT_REASONS = {
    "deep_internal_import_graph",
    "default_task_when_prompt_missing",
    "human_oriented_output",
    "no_typed_result_envelope",
    "weak_failure_exit_contract",
}

REQUIRED_ONESHOT_REASONS = {
    "approval_bypass",
    "configured_toolset_inheritance",
    "cwd_context_loading",
    "import_time_env_loading",
    "mcp_discovery",
    "no_zero_tool_mode",
    "optional_usage_file_write",
    "process_hard_exit",
    "recovery_may_mutate_environment",
    "safe_mode_does_not_skip_context_or_memory",
    "safe_mode_cli_not_supported_with_oneshot",
    "safe_toolset_network_capable",
    "session_database_write",
    "untyped_final_text",
}

REQUIRED_SIDE_EFFECTS = {
    "container_default_root_entrypoint",
    "container_dispatches_via_s6_stage2",
    "container_narrow_shim_candidate",
    "container_stage2_mutation",
    "import_bootstrap_mutation",
    "import_dotenv_loading",
    "import_early_recovery",
    "oneshot_auto_approvals",
    "oneshot_cwd_context",
    "oneshot_model_network",
    "oneshot_toolset_inheritance",
    "oneshot_plugin_mcp_hook_discovery",
    "safe_toolset_not_offline",
    "oneshot_session_database",
    "oneshot_usage_file",
    "oneshot_hard_exit",
    "run_agent_import_graph",
}

EXPECTED_SIDE_EFFECT_DIGESTS = {
    "container_default_root_entrypoint": "e2ebd4d1006d843bd0da2690de5c7d151a6d4d3559944396ccde3aa4c79a7db6",
    "container_dispatches_via_s6_stage2": "4cccd1b268c548a8ce095b6e0734082ed046254598e421990474eeea0011c608",
    "container_narrow_shim_candidate": "272a8aea19db4ebac65c67f0f100aa6280a5510bb726837b3d7a8531b260b9da",
    "container_stage2_mutation": "6da430d2ecdb5c3ce35ff8d8630fb0db8fdce11f5bc65e850928461b03561c58",
    "import_bootstrap_mutation": "a47cf3966adab3e08575a2beb1087767b9dd79f9a568bcac0c097fc0aa0c2686",
    "import_dotenv_loading": "c661564ad2951f77427692f1b12e65b9e08934c7346975df06a039b05bbe6d9e",
    "import_early_recovery": "b9116bd8130e6f04bb20c236b690cfbc64413865a41dc7d4bc67657f91d44af4",
    "oneshot_auto_approvals": "7cfe616180f66cf493d318b015a1e2d847d77e65f16c571c082adf94d3acce0e",
    "oneshot_cwd_context": "cbb0b04cb09233eb339418dd6772cd22cd5cca60b239d9c6c4789034a6641a36",
    "oneshot_hard_exit": "4b1a58ce9b548dda083bec0a08d455c91474153dd954c239aa3eaf1355556e3b",
    "oneshot_model_network": "ea32dcf7185d41b2305c7aff509864adf199530e2df4764cc2bab5b36abc86ad",
    "oneshot_plugin_mcp_hook_discovery": "b2ed5ce0fe89de6a438da962623bcf3f652fa4c4b5cec299b2b47f3572378891",
    "oneshot_session_database": "2de2304fc11c694503fc7ff8188f448acc568c5496d0405b169ae580330ef0a0",
    "oneshot_toolset_inheritance": "bc5eddb1e81d6379756b2b6c92376d6d4e3ce1bd3248d8e7030e4e1ce7792140",
    "oneshot_usage_file": "a5c689b16bc2f0a69bb827a7efb08231a8fcee157871fd3a2f134a20ebcdae57",
    "run_agent_import_graph": "4d722a7e9d63cefbe49a9e33a79f148643a04b2bc8e26bc6db731a86bb0fcf96",
    "safe_toolset_not_offline": "025b98f7ddf4e7e6c7b951e2bdd73ac157036b5ce082c252381d90a7c8c77778",
}

EXPECTED_BUNDLED_LICENSE_PATHS = {
    "skills/productivity/docx/LICENSE.txt",
    "skills/productivity/pdf/LICENSE.txt",
    "skills/productivity/powerpoint/LICENSE.txt",
    "skills/productivity/xlsx/LICENSE.txt",
}

EXPECTED_OSV_PACKAGES = {
    "aiohttp": (
        "3.14.1",
        {"CVE-2026-59881", "CVE-2026-69243", "CVE-2026-69244"},
    ),
    "cryptography": (
        "48.0.1",
        {"CVE-2026-69247", "CVE-2026-69248", "CVE-2026-69249"},
    ),
}

EXPECTED_OSV_SOURCES = [
    "https://api.osv.dev/v1/querybatch",
    "https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/uv.lock",
    "https://github.com/NousResearch/hermes-agent/blob/3c27eb6234bf91b8ceee9e9071591b31e9b148cb/Dockerfile",
]

REQUIRED_FIXTURE_BOUNDARIES = {
    "/opt/hermes/bin/hermes",
    "/init",
    "10000:10000",
    "/opt/data",
    "HERMES_SAFE_MODE=1",
    "--safe-mode",
}

EXPECTED_REPOSITORY_DEPENDENCY_FILES = [
    "pyproject.toml",
    "requirements-beta.lock",
    "requirements-beta.txt",
    "requirements-dev.lock",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements.txt",
    "worldview/ingestion-workers/pyproject.toml",
    "worldview/ingestion-workers/requirements.txt",
]

EXPECTED_METHOD_SOURCES = [
    "github_api",
    "github_exact_commit_raw",
    "pypi_json_api",
    "docker_registry_v2_api",
    "osv_querybatch_api",
]

E9_DIMENSIONS = ["quality", "latency", "cost", "reliability", "privacy"]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ANCHOR = re.compile(r"^L[1-9]\d*(?:-L[1-9]\d*)?$")
DEPENDENCY_DECLARATION = re.compile(
    r"""(?ix)
    ^\s*["']?\s*
    (?P<name>[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)
    (?=\s*(?:\[|@|={1,3}|~=|!=|<=|>=|<|>|["']|,|$))
    """
)
LEGACY_EGG_FRAGMENT = re.compile(r"(?i)(?:#|&)egg=(?P<name>[a-z0-9][a-z0-9._-]*)")
MAX_JSON_DEPTH = 48
MAX_JSON_BYTES = 1_048_576
MAX_DOCUMENT_BYTES = 1_048_576


class PreflightError(RuntimeError):
    """Raised for deterministic evidence, rendering, or filesystem failures."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise PreflightError(f"non-finite JSON value {value!r}")


def _reject_float(value: str) -> None:
    raise PreflightError(f"floating-point JSON value {value!r} is not allowed")


def _parse_int(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > 20:
        raise PreflightError("integer JSON value exceeds 20 digits")
    return int(value)


def _check_depth(data: Any, path: Path) -> None:
    stack: list[tuple[Any, int]] = [(data, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise PreflightError(
                f"invalid JSON in {path}: JSON nesting exceeds {MAX_JSON_DEPTH} levels"
            )
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def load_json_strict(path: Path) -> Any:
    """Load a regular UTF-8 JSON file with deterministic hostile-input rejection."""

    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise PreflightError(f"JSON input must be a non-symlink regular file: {path}")
        if metadata.st_size > MAX_JSON_BYTES:
            raise PreflightError(f"JSON input {path} exceeds {MAX_JSON_BYTES} bytes")
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise PreflightError(f"cannot read {path}: {exc}") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise PreflightError(f"JSON input {path} exceeds {MAX_JSON_BYTES} bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PreflightError(f"UTF-8 BOM is not allowed in {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightError(f"invalid UTF-8 in {path}: {exc}") from exc
    try:
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
            parse_float=_reject_float,
            parse_int=_parse_int,
        )
        _check_depth(data, path)
    except PreflightError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise PreflightError(f"invalid JSON in {path}: {exc}") from exc
    return data


def _object(value: Any, expected: set[str], label: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label}: must be an object")
        return None
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        errors.append(f"{label}: missing fields {missing}")
    if unknown:
        errors.append(f"{label}: unknown fields {unknown}")
    return value


def _list(value: Any, label: str, errors: list[str]) -> list[Any] | None:
    if not isinstance(value, list):
        errors.append(f"{label}: must be an array")
        return None
    return value


def _text(value: Any, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        errors.append(f"{label}: must be a non-empty trimmed string")
        return None
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        errors.append(f"{label}: must not contain control characters")
        return None
    return value


def _boolean(value: Any, label: str, errors: list[str]) -> bool | None:
    if type(value) is not bool:
        errors.append(f"{label}: must be a boolean")
        return None
    return value


def _positive_int(value: Any, label: str, errors: list[str]) -> int | None:
    if type(value) is not int or value <= 0:
        errors.append(f"{label}: must be a positive integer")
        return None
    return value


def _strings(value: Any, label: str, errors: list[str]) -> list[str] | None:
    items = _list(value, label, errors)
    if items is None:
        return None
    result: list[str] = []
    for index, item in enumerate(items):
        parsed = _text(item, f"{label}[{index}]", errors)
        if parsed is not None:
            result.append(parsed)
    if len(result) != len(set(result)):
        errors.append(f"{label}: values must be unique")
    return result


def _expect(value: Any, expected: Any, label: str, errors: list[str]) -> None:
    if value != expected or type(value) is not type(expected):
        errors.append(f"{label}: must equal {expected!r}")


def _canonical_record_digest(value: Any) -> str | None:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest()


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value.casefold())


def _declared_distribution_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = DEPENDENCY_DECLARATION.match(line)
        if match is not None:
            names.add(_normalize_distribution_name(match.group("name")))
        for egg in LEGACY_EGG_FRAGMENT.finditer(line):
            names.add(_normalize_distribution_name(egg.group("name")))
    return names


def _timestamp(value: Any, label: str, errors: list[str]) -> datetime | None:
    parsed = _text(value, label, errors)
    if parsed is None:
        return None
    if not UTC_TIMESTAMP.fullmatch(parsed):
        errors.append(f"{label}: must be an RFC3339 UTC timestamp without fractions")
        return None
    try:
        result = datetime.strptime(parsed, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        errors.append(f"{label}: must be a valid timestamp")
        return None
    if result > datetime.now(UTC):
        errors.append(f"{label}: cannot be in the future")
    return result


def _validate_status(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {
            "observed_at_utc",
            "evidence_status",
            "adapter_status",
            "program_status",
            "release_ready",
            "issue",
            "parent_issue",
            "epic_issue",
        },
        "status",
        errors,
    )
    if item is None:
        return
    observed = _timestamp(item.get("observed_at_utc"), "status.observed_at_utc", errors)
    if observed is not None and observed < datetime(2026, 8, 6, tzinfo=UTC):
        errors.append("status.observed_at_utc: predates the #844 preflight")
    _expect(
        item.get("evidence_status"), "preflight_evidence_only", "status.evidence_status", errors
    )
    _expect(item.get("adapter_status"), "blocked", "status.adapter_status", errors)
    _expect(item.get("program_status"), "building", "status.program_status", errors)
    _expect(item.get("release_ready"), False, "status.release_ready", errors)
    _expect(item.get("issue"), 844, "status.issue", errors)
    _expect(item.get("parent_issue"), 804, "status.parent_issue", errors)
    _expect(item.get("epic_issue"), 766, "status.epic_issue", errors)


def _validate_method(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {
            "network_scope",
            "primary_sources_only",
            "upstream_imported",
            "upstream_executed",
            "package_or_image_artifact_downloaded",
            "package_installed",
            "sources",
            "limitations",
        },
        "method",
        errors,
    )
    if item is None:
        return
    _expect(
        item.get("network_scope"), "read_only_metadata_and_source", "method.network_scope", errors
    )
    _expect(item.get("primary_sources_only"), True, "method.primary_sources_only", errors)
    for field in (
        "upstream_imported",
        "upstream_executed",
        "package_or_image_artifact_downloaded",
        "package_installed",
    ):
        _expect(item.get(field), False, f"method.{field}", errors)
    sources = _strings(item.get("sources"), "method.sources", errors)
    if sources is not None and sources != EXPECTED_METHOD_SOURCES:
        errors.append("method.sources: must match the authoritative read-only source set")
    limitations = _strings(item.get("limitations"), "method.limitations", errors)
    if limitations is not None and len(limitations) < 4:
        errors.append("method.limitations: must retain at least four explicit limitations")


def _validate_upstream(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {
            "repository",
            "release_tag",
            "tag_object_sha",
            "tag_target_sha",
            "tag_verification",
            "commit_sha",
            "commit_verification",
            "tree_sha",
            "release_url",
            "default_branch_comparison",
            "source_files",
        },
        "upstream",
        errors,
    )
    if item is None:
        return
    _expect(item.get("repository"), UPSTREAM_REPOSITORY, "upstream.repository", errors)
    _expect(item.get("release_tag"), UPSTREAM_TAG, "upstream.release_tag", errors)
    _expect(item.get("tag_object_sha"), UPSTREAM_TAG_OBJECT, "upstream.tag_object_sha", errors)
    _expect(item.get("tag_target_sha"), UPSTREAM_COMMIT, "upstream.tag_target_sha", errors)
    _expect(item.get("tag_verification"), "valid_ssh_metadata", "upstream.tag_verification", errors)
    _expect(item.get("commit_sha"), UPSTREAM_COMMIT, "upstream.commit_sha", errors)
    _expect(item.get("commit_verification"), "unsigned", "upstream.commit_verification", errors)
    _expect(item.get("tree_sha"), UPSTREAM_TREE, "upstream.tree_sha", errors)
    _expect(
        item.get("release_url"),
        "https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.3",
        "upstream.release_url",
        errors,
    )
    comparison = _object(
        item.get("default_branch_comparison"),
        {"observed_at_utc", "ref", "ahead_by", "behind_by", "status", "evidence_state"},
        "upstream.default_branch_comparison",
        errors,
    )
    if comparison is not None:
        _expect(
            comparison.get("observed_at_utc"),
            "2026-08-06T23:40:22Z",
            "upstream.default_branch_comparison.observed_at_utc",
            errors,
        )
        _timestamp(
            comparison.get("observed_at_utc"),
            "upstream.default_branch_comparison.observed_at_utc",
            errors,
        )
        _expect(comparison.get("ref"), "main", "upstream.default_branch_comparison.ref", errors)
        _expect(
            comparison.get("ahead_by"),
            300,
            "upstream.default_branch_comparison.ahead_by",
            errors,
        )
        _expect(
            comparison.get("behind_by"),
            0,
            "upstream.default_branch_comparison.behind_by",
            errors,
        )
        _expect(
            comparison.get("status"),
            "ahead",
            "upstream.default_branch_comparison.status",
            errors,
        )
        _expect(
            comparison.get("evidence_state"),
            "recorded_metadata",
            "upstream.default_branch_comparison.evidence_state",
            errors,
        )

    files = _list(item.get("source_files"), "upstream.source_files", errors)
    if files is None:
        return
    observed: dict[str, dict[str, Any]] = {}
    fields = {"path", "blob_sha", "sha256", "size", "raw_url", "evidence_state"}
    for index, value_item in enumerate(files):
        source = _object(value_item, fields, f"upstream.source_files[{index}]", errors)
        if source is None:
            continue
        path = _text(source.get("path"), f"upstream.source_files[{index}].path", errors)
        if path is None:
            continue
        if path in observed:
            errors.append(f"upstream.source_files: duplicate path {path!r}")
        observed[path] = source
        expected = EXPECTED_SOURCE_FILES.get(path)
        if expected is None:
            errors.append(f"upstream.source_files: unexpected path {path!r}")
            continue
        blob_sha, sha256, size = expected
        _expect(source.get("blob_sha"), blob_sha, f"source {path}.blob_sha", errors)
        _expect(source.get("sha256"), sha256, f"source {path}.sha256", errors)
        _expect(source.get("size"), size, f"source {path}.size", errors)
        _expect(
            source.get("evidence_state"), "verified_static", f"source {path}.evidence_state", errors
        )
        expected_url = (
            f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{UPSTREAM_COMMIT}/{path}"
        )
        _expect(source.get("raw_url"), expected_url, f"source {path}.raw_url", errors)
    if set(observed) != set(EXPECTED_SOURCE_FILES):
        errors.append("upstream.source_files: path set must match the canonical pinned snapshot")


def _validate_distribution(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {
            "source_distribution",
            "source_version",
            "requires_python",
            "console_scripts",
            "pypi",
            "container",
            "selected_distribution_route",
        },
        "distribution",
        errors,
    )
    if item is None:
        return
    _expect(
        item.get("source_distribution"), "hermes-agent", "distribution.source_distribution", errors
    )
    _expect(item.get("source_version"), "0.20.0", "distribution.source_version", errors)
    _expect(item.get("requires_python"), ">=3.11,<3.14", "distribution.requires_python", errors)
    _expect(
        item.get("selected_distribution_route"),
        "dockerhub_oci_index_candidate_not_pulled",
        "distribution.selected_distribution_route",
        errors,
    )

    scripts = _list(item.get("console_scripts"), "distribution.console_scripts", errors)
    seen: dict[str, Any] = {}
    if scripts is not None:
        for index, raw in enumerate(scripts):
            script = _object(
                raw,
                {"name", "mapping", "source_path", "anchor", "evidence_state"},
                f"distribution.console_scripts[{index}]",
                errors,
            )
            if script is None:
                continue
            name = _text(script.get("name"), f"distribution.console_scripts[{index}].name", errors)
            if name is None:
                continue
            if name in seen:
                errors.append(f"distribution.console_scripts: duplicate {name!r}")
            seen[name] = script
            if name not in EXPECTED_CONSOLE_SCRIPTS:
                errors.append(f"distribution.console_scripts: unexpected {name!r}")
                continue
            _expect(
                script.get("mapping"),
                EXPECTED_CONSOLE_SCRIPTS[name],
                f"console script {name}.mapping",
                errors,
            )
            _expect(
                script.get("source_path"),
                "pyproject.toml",
                f"console script {name}.source_path",
                errors,
            )
            _expect(script.get("anchor"), "L348-L350", f"console script {name}.anchor", errors)
            _expect(
                script.get("evidence_state"),
                "verified_static",
                f"console script {name}.evidence_state",
                errors,
            )
    if set(seen) != set(EXPECTED_CONSOLE_SCRIPTS):
        errors.append("distribution.console_scripts: script set must match pinned pyproject")

    pypi = _object(
        item.get("pypi"),
        {
            "project",
            "observed_version",
            "observed_at_utc",
            "requires_python",
            "license_expression",
            "source_commit_distribution_available",
            "wheel_sha256",
            "sdist_sha256",
            "response_bytes",
            "response_sha256",
            "response_etag",
            "release_count",
            "evidence_state",
            "url",
        },
        "distribution.pypi",
        errors,
    )
    if pypi is not None:
        _expect(pypi.get("project"), "hermes-agent", "distribution.pypi.project", errors)
        _expect(
            pypi.get("observed_version"), "0.19.0", "distribution.pypi.observed_version", errors
        )
        _timestamp(pypi.get("observed_at_utc"), "distribution.pypi.observed_at_utc", errors)
        _expect(
            pypi.get("requires_python"), "<3.14,>=3.11", "distribution.pypi.requires_python", errors
        )
        _expect(
            pypi.get("license_expression"), "MIT", "distribution.pypi.license_expression", errors
        )
        _expect(
            pypi.get("source_commit_distribution_available"),
            False,
            "distribution.pypi.source_commit_distribution_available",
            errors,
        )
        _expect(
            pypi.get("wheel_sha256"),
            "bd0bac012aee38a60894781f4597dc29ee7bedb3448540249921f10d3bef327f",
            "distribution.pypi.wheel_sha256",
            errors,
        )
        _expect(
            pypi.get("sdist_sha256"),
            "ac986bede64a2785436676c0ea084ec586574f8cb00a9d047e095b435d3e21c0",
            "distribution.pypi.sdist_sha256",
            errors,
        )
        _expect(pypi.get("response_bytes"), 45448, "distribution.pypi.response_bytes", errors)
        _expect(
            pypi.get("response_sha256"),
            "af89ca1ed4d433b307b1f3c0b65459424815d83077fa66c2934b61a5d07c15e2",
            "distribution.pypi.response_sha256",
            errors,
        )
        _expect(
            pypi.get("response_etag"),
            '"p7GD9lV+0ULm+HAZzyDjPQ"',
            "distribution.pypi.response_etag",
            errors,
        )
        _expect(pypi.get("release_count"), 11, "distribution.pypi.release_count", errors)
        _expect(
            pypi.get("evidence_state"),
            "recorded_metadata",
            "distribution.pypi.evidence_state",
            errors,
        )
        _expect(
            pypi.get("url"),
            "https://pypi.org/pypi/hermes-agent/json",
            "distribution.pypi.url",
            errors,
        )

    container = _object(
        item.get("container"),
        {
            "registry",
            "image",
            "tag",
            "index_digest",
            "media_type",
            "platform_manifests",
            "attestation_manifests",
            "provenance",
            "release_workflow_run",
            "release_workflow_head",
            "release_workflow_conclusion",
            "evidence_state",
            "pulled",
            "executed",
            "attestations_verified",
        },
        "distribution.container",
        errors,
    )
    if container is None:
        return
    _expect(
        container.get("registry"),
        "registry-1.docker.io",
        "distribution.container.registry",
        errors,
    )
    _expect(
        container.get("image"),
        "nousresearch/hermes-agent",
        "distribution.container.image",
        errors,
    )
    _expect(container.get("tag"), UPSTREAM_TAG, "distribution.container.tag", errors)
    _expect(
        container.get("index_digest"),
        "sha256:16788311e2fa3035456bdc1bafb8ec2b1777db64ebf020af9bb7eb73c3712c9e",
        "distribution.container.index_digest",
        errors,
    )
    _expect(
        container.get("media_type"),
        "application/vnd.oci.image.index.v1+json",
        "distribution.container.media_type",
        errors,
    )
    expected_platforms = {
        "linux/amd64": "sha256:c0cab4e3711bcb27a312be1b3776254fc06fd50d5f7a6b8017915fc7171cb39e",
        "linux/arm64": "sha256:153a021a0c59f28c1c230b201c8b819403da2a01969b9ffd939f1a429b7af2cd",
    }
    platform_items = _list(
        container.get("platform_manifests"),
        "distribution.container.platform_manifests",
        errors,
    )
    observed_platforms: dict[str, str] = {}
    if platform_items is not None:
        for index, raw in enumerate(platform_items):
            platform = _object(
                raw,
                {"platform", "digest", "size"},
                f"distribution.container.platform_manifests[{index}]",
                errors,
            )
            if platform is None:
                continue
            name = _text(
                platform.get("platform"),
                f"distribution.container.platform_manifests[{index}].platform",
                errors,
            )
            digest = _text(
                platform.get("digest"),
                f"distribution.container.platform_manifests[{index}].digest",
                errors,
            )
            _expect(
                platform.get("size"),
                7523,
                f"distribution.container.platform_manifests[{index}].size",
                errors,
            )
            if name is not None and digest is not None:
                if name in observed_platforms:
                    errors.append(f"distribution.container.platform_manifests: duplicate {name!r}")
                observed_platforms[name] = digest
    if observed_platforms != expected_platforms:
        errors.append("distribution.container.platform_manifests: exact linux manifests required")

    expected_attestations = {
        "sha256:c0cab4e3711bcb27a312be1b3776254fc06fd50d5f7a6b8017915fc7171cb39e": "sha256:c2677c3c5a5a4029d40f43b1aa2dd6bfa554753596f2d289e98ce74eca6e5787",
        "sha256:153a021a0c59f28c1c230b201c8b819403da2a01969b9ffd939f1a429b7af2cd": "sha256:7e1c68556289212c82671940d827c60a3b859d16e4147cc0f77d51e0d68a3606",
    }
    attestation_items = _list(
        container.get("attestation_manifests"),
        "distribution.container.attestation_manifests",
        errors,
    )
    observed_attestations: dict[str, str] = {}
    if attestation_items is not None:
        for index, raw in enumerate(attestation_items):
            attestation = _object(
                raw,
                {"subject_digest", "manifest_digest", "size"},
                f"distribution.container.attestation_manifests[{index}]",
                errors,
            )
            if attestation is None:
                continue
            subject = _text(
                attestation.get("subject_digest"),
                f"distribution.container.attestation_manifests[{index}].subject_digest",
                errors,
            )
            manifest_digest = _text(
                attestation.get("manifest_digest"),
                f"distribution.container.attestation_manifests[{index}].manifest_digest",
                errors,
            )
            _expect(
                attestation.get("size"),
                566,
                f"distribution.container.attestation_manifests[{index}].size",
                errors,
            )
            if subject is not None and manifest_digest is not None:
                if subject in observed_attestations:
                    errors.append(
                        f"distribution.container.attestation_manifests: duplicate {subject!r}"
                    )
                observed_attestations[subject] = manifest_digest
    if observed_attestations != expected_attestations:
        errors.append("distribution.container.attestation_manifests: exact index metadata required")
    provenance = _object(
        container.get("provenance"),
        {
            "state",
            "authenticity_verified",
            "signature_present",
            "buildkit_materials_complete",
            "registry_referrer_count",
            "workflow_run",
            "workflow_attempt",
            "statements",
        },
        "distribution.container.provenance",
        errors,
    )
    if provenance is not None:
        _expect(
            provenance.get("state"),
            "recorded_metadata",
            "distribution.container.provenance.state",
            errors,
        )
        for field in (
            "authenticity_verified",
            "signature_present",
            "buildkit_materials_complete",
        ):
            _expect(
                provenance.get(field),
                False,
                f"distribution.container.provenance.{field}",
                errors,
            )
        _expect(
            provenance.get("registry_referrer_count"),
            0,
            "distribution.container.provenance.registry_referrer_count",
            errors,
        )
        _expect(
            provenance.get("workflow_run"),
            30834568564,
            "distribution.container.provenance.workflow_run",
            errors,
        )
        _expect(
            provenance.get("workflow_attempt"),
            1,
            "distribution.container.provenance.workflow_attempt",
            errors,
        )
        statements = _list(
            provenance.get("statements"),
            "distribution.container.provenance.statements",
            errors,
        )
        expected_statements = {
            "linux/amd64": (
                "sha256:c0cab4e3711bcb27a312be1b3776254fc06fd50d5f7a6b8017915fc7171cb39e",
                "sha256:1011de3fa75e1d7fcc3542343a13cf0bf7ef565115a1e091354c0dd0f121f47a",
                263204,
            ),
            "linux/arm64": (
                "sha256:153a021a0c59f28c1c230b201c8b819403da2a01969b9ffd939f1a429b7af2cd",
                "sha256:87bd0d7e671e0c152d2b813f31c4fd6223a3b99e7e14ad52527ceaf26ac5728c",
                340516,
            ),
        }
        observed_statements: dict[str, tuple[str, str, int]] = {}
        if statements is not None:
            for index, raw in enumerate(statements):
                statement = _object(
                    raw,
                    {"platform", "subject_digest", "layer_digest", "size"},
                    f"distribution.container.provenance.statements[{index}]",
                    errors,
                )
                if statement is None:
                    continue
                platform = _text(
                    statement.get("platform"),
                    f"distribution.container.provenance.statements[{index}].platform",
                    errors,
                )
                subject = _text(
                    statement.get("subject_digest"),
                    f"distribution.container.provenance.statements[{index}].subject_digest",
                    errors,
                )
                layer = _text(
                    statement.get("layer_digest"),
                    f"distribution.container.provenance.statements[{index}].layer_digest",
                    errors,
                )
                size = statement.get("size")
                _positive_int(
                    size,
                    f"distribution.container.provenance.statements[{index}].size",
                    errors,
                )
                if platform is not None and subject is not None and layer is not None:
                    if platform in observed_statements:
                        errors.append(
                            "distribution.container.provenance.statements: "
                            f"duplicate platform {platform!r}"
                        )
                    if type(size) is int:
                        observed_statements[platform] = (subject, layer, size)
        if observed_statements != expected_statements:
            errors.append(
                "distribution.container.provenance.statements: "
                "exact pinned SLSA layer metadata required"
            )
    _expect(
        container.get("release_workflow_run"),
        30834568564,
        "distribution.container.release_workflow_run",
        errors,
    )
    _expect(
        container.get("release_workflow_head"),
        UPSTREAM_COMMIT,
        "distribution.container.release_workflow_head",
        errors,
    )
    _expect(
        container.get("release_workflow_conclusion"),
        "success",
        "distribution.container.release_workflow_conclusion",
        errors,
    )
    _expect(
        container.get("evidence_state"),
        "recorded_metadata",
        "distribution.container.evidence_state",
        errors,
    )
    _expect(container.get("pulled"), False, "distribution.container.pulled", errors)
    _expect(container.get("executed"), False, "distribution.container.executed", errors)
    _expect(
        container.get("attestations_verified"),
        False,
        "distribution.container.attestations_verified",
        errors,
    )


def _validate_invocation_surfaces(value: Any, errors: list[str]) -> None:
    items = _list(value, "invocation_surfaces", errors)
    if items is None:
        return
    seen: dict[str, dict[str, Any]] = {}
    fields = {
        "id",
        "console_script",
        "selector",
        "entrypoint_chain",
        "decision",
        "evidence_state",
        "reason_codes",
        "result_contract",
    }
    for index, raw in enumerate(items):
        surface = _object(raw, fields, f"invocation_surfaces[{index}]", errors)
        if surface is None:
            continue
        identifier = _text(surface.get("id"), f"invocation_surfaces[{index}].id", errors)
        if identifier is None:
            continue
        if identifier in seen:
            errors.append(f"invocation_surfaces: duplicate id {identifier!r}")
        seen[identifier] = surface
        expected_decision = EXPECTED_SURFACE_DECISIONS.get(identifier)
        if expected_decision is None:
            errors.append(f"invocation_surfaces: unexpected id {identifier!r}")
            continue
        _expect(
            surface.get("decision"), expected_decision, f"surface {identifier}.decision", errors
        )
        _expect(
            surface.get("evidence_state"),
            "verified_static",
            f"surface {identifier}.evidence_state",
            errors,
        )
        reasons = _strings(
            surface.get("reason_codes"), f"surface {identifier}.reason_codes", errors
        )
        if reasons is not None:
            required = (
                REQUIRED_HERMES_AGENT_REASONS
                if identifier == "hermes-agent"
                else REQUIRED_ONESHOT_REASONS
            )
            if not required.issubset(reasons):
                errors.append(f"surface {identifier}.reason_codes: required hazards are missing")
        if identifier == "hermes-agent":
            _expect(
                surface.get("console_script"),
                "hermes-agent",
                "surface hermes-agent.console_script",
                errors,
            )
            _expect(surface.get("selector"), "none", "surface hermes-agent.selector", errors)
            _expect(
                surface.get("entrypoint_chain"),
                "run_agent:main",
                "surface hermes-agent.entrypoint_chain",
                errors,
            )
            _expect(
                surface.get("result_contract"),
                "human_text_no_typed_envelope",
                "surface hermes-agent.result_contract",
                errors,
            )
        else:
            _expect(
                surface.get("console_script"),
                "hermes",
                "surface hermes-oneshot.console_script",
                errors,
            )
            _expect(
                surface.get("selector"),
                "-z/--oneshot",
                "surface hermes-oneshot.selector",
                errors,
            )
            _expect(
                surface.get("entrypoint_chain"),
                "hermes_cli.main:main -> hermes_cli.oneshot:run_oneshot",
                "surface hermes-oneshot.entrypoint_chain",
                errors,
            )
            _expect(
                surface.get("result_contract"),
                "final_text_plus_optional_usage_json",
                "surface hermes-oneshot.result_contract",
                errors,
            )
    if set(seen) != set(EXPECTED_SURFACE_DECISIONS):
        errors.append("invocation_surfaces: exactly the two pinned surfaces are required")


def _validate_side_effects(value: Any, errors: list[str]) -> None:
    items = _list(value, "side_effects", errors)
    if items is None:
        return
    seen: set[str] = set()
    fields = {
        "id",
        "surface",
        "phase",
        "evidence_state",
        "source_path",
        "anchors",
        "behavior",
        "risk",
    }
    for index, raw in enumerate(items):
        effect = _object(raw, fields, f"side_effects[{index}]", errors)
        if effect is None:
            continue
        identifier = _text(effect.get("id"), f"side_effects[{index}].id", errors)
        if identifier is not None:
            if identifier in seen:
                errors.append(f"side_effects: duplicate id {identifier!r}")
            seen.add(identifier)
            expected_digest = EXPECTED_SIDE_EFFECT_DIGESTS.get(identifier)
            if expected_digest is not None and _canonical_record_digest(effect) != expected_digest:
                errors.append(f"side_effects: record binding mismatch for {identifier!r}")
        _text(effect.get("surface"), f"side_effects[{index}].surface", errors)
        phase = _text(effect.get("phase"), f"side_effects[{index}].phase", errors)
        if phase is not None and phase not in {
            "import_static",
            "startup_static",
            "runtime_static",
            "shutdown_static",
        }:
            errors.append(f"side_effects[{index}].phase: invalid static phase")
        _expect(
            effect.get("evidence_state"),
            "verified_static",
            f"side_effects[{index}].evidence_state",
            errors,
        )
        source_path = _text(effect.get("source_path"), f"side_effects[{index}].source_path", errors)
        if source_path is not None and source_path not in EXPECTED_SOURCE_FILES:
            errors.append(f"side_effects[{index}].source_path: must be an exact pinned source file")
        anchors = _strings(effect.get("anchors"), f"side_effects[{index}].anchors", errors)
        if anchors is not None and (
            not anchors or any(not ANCHOR.fullmatch(anchor) for anchor in anchors)
        ):
            errors.append(f"side_effects[{index}].anchors: invalid or empty line anchor set")
        _text(effect.get("behavior"), f"side_effects[{index}].behavior", errors)
        _text(effect.get("risk"), f"side_effects[{index}].risk", errors)
    if seen != REQUIRED_SIDE_EFFECTS:
        errors.append("side_effects: required static hazard inventory is incomplete")


def _validate_supply_chain(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {
            "direct_dependencies",
            "optional_dependencies",
            "lock_snapshot",
            "upstream_license",
            "bundled_license_findings",
            "transitive_license_closure",
            "vulnerability_review",
            "sbom",
        },
        "supply_chain",
        errors,
    )
    if item is None:
        return

    direct = _object(
        item.get("direct_dependencies"),
        {"count", "requirements_sha256", "source_path", "evidence_state", "fully_exact_pinned"},
        "supply_chain.direct_dependencies",
        errors,
    )
    if direct is not None:
        _expect(direct.get("count"), 32, "supply_chain.direct_dependencies.count", errors)
        _expect(
            direct.get("requirements_sha256"),
            "c42068239c7f78a58e2269f3311623d49b821e29575b2e24b0aa5c8a3602be35",
            "supply_chain.direct_dependencies.requirements_sha256",
            errors,
        )
        _expect(
            direct.get("source_path"),
            "pyproject.toml",
            "supply_chain.direct_dependencies.source_path",
            errors,
        )
        _expect(
            direct.get("evidence_state"),
            "verified_static",
            "supply_chain.direct_dependencies.evidence_state",
            errors,
        )
        _expect(
            direct.get("fully_exact_pinned"),
            False,
            "supply_chain.direct_dependencies.fully_exact_pinned",
            errors,
        )

    optional = _object(
        item.get("optional_dependencies"),
        {"group_count", "default_selected", "evidence_state", "source_path"},
        "supply_chain.optional_dependencies",
        errors,
    )
    if optional is not None:
        _expect(
            optional.get("group_count"),
            45,
            "supply_chain.optional_dependencies.group_count",
            errors,
        )
        _expect(
            optional.get("default_selected"),
            False,
            "supply_chain.optional_dependencies.default_selected",
            errors,
        )
        _expect(
            optional.get("evidence_state"),
            "verified_static",
            "supply_chain.optional_dependencies.evidence_state",
            errors,
        )
        _expect(
            optional.get("source_path"),
            "pyproject.toml",
            "supply_chain.optional_dependencies.source_path",
            errors,
        )

    lock = _object(
        item.get("lock_snapshot"),
        {"source_path", "package_records", "unique_names", "license_fields", "evidence_state"},
        "supply_chain.lock_snapshot",
        errors,
    )
    if lock is not None:
        _expect(
            lock.get("source_path"), "uv.lock", "supply_chain.lock_snapshot.source_path", errors
        )
        _expect(
            lock.get("package_records"), 250, "supply_chain.lock_snapshot.package_records", errors
        )
        _expect(lock.get("unique_names"), 249, "supply_chain.lock_snapshot.unique_names", errors)
        _expect(lock.get("license_fields"), 0, "supply_chain.lock_snapshot.license_fields", errors)
        _expect(
            lock.get("evidence_state"),
            "verified_static",
            "supply_chain.lock_snapshot.evidence_state",
            errors,
        )

    license_item = _object(
        item.get("upstream_license"),
        {"expression", "source_path", "evidence_state"},
        "supply_chain.upstream_license",
        errors,
    )
    if license_item is not None:
        _expect(
            license_item.get("expression"),
            "MIT",
            "supply_chain.upstream_license.expression",
            errors,
        )
        _expect(
            license_item.get("source_path"),
            "LICENSE",
            "supply_chain.upstream_license.source_path",
            errors,
        )
        _expect(
            license_item.get("evidence_state"),
            "verified_static",
            "supply_chain.upstream_license.evidence_state",
            errors,
        )

    bundled = _object(
        item.get("bundled_license_findings"),
        {"state", "complete", "owner_or_legal_acceptance", "findings", "blocker"},
        "supply_chain.bundled_license_findings",
        errors,
    )
    if bundled is not None:
        _expect(
            bundled.get("state"),
            "verified_static",
            "supply_chain.bundled_license_findings.state",
            errors,
        )
        _expect(
            bundled.get("complete"),
            False,
            "supply_chain.bundled_license_findings.complete",
            errors,
        )
        _expect(
            bundled.get("owner_or_legal_acceptance"),
            False,
            "supply_chain.bundled_license_findings.owner_or_legal_acceptance",
            errors,
        )
        findings = _list(
            bundled.get("findings"),
            "supply_chain.bundled_license_findings.findings",
            errors,
        )
        observed_licenses: set[str] = set()
        if findings is not None:
            for index, raw in enumerate(findings):
                finding = _object(
                    raw,
                    {"path", "classification", "evidence_state"},
                    f"supply_chain.bundled_license_findings.findings[{index}]",
                    errors,
                )
                if finding is None:
                    continue
                path = _text(
                    finding.get("path"),
                    f"supply_chain.bundled_license_findings.findings[{index}].path",
                    errors,
                )
                if path is not None:
                    if path in observed_licenses:
                        errors.append(
                            "supply_chain.bundled_license_findings.findings: "
                            f"duplicate path {path!r}"
                        )
                    observed_licenses.add(path)
                _expect(
                    finding.get("classification"),
                    "separate_restrictive_anthropic_terms",
                    f"supply_chain.bundled_license_findings.findings[{index}].classification",
                    errors,
                )
                _expect(
                    finding.get("evidence_state"),
                    "verified_static",
                    f"supply_chain.bundled_license_findings.findings[{index}].evidence_state",
                    errors,
                )
        if observed_licenses != EXPECTED_BUNDLED_LICENSE_PATHS:
            errors.append(
                "supply_chain.bundled_license_findings.findings: "
                "exact restrictive bundled-license paths required"
            )
        _text(
            bundled.get("blocker"),
            "supply_chain.bundled_license_findings.blocker",
            errors,
        )

    closure = _object(
        item.get("transitive_license_closure"),
        {"state", "complete", "blocker"},
        "supply_chain.transitive_license_closure",
        errors,
    )
    if closure is not None:
        _expect(
            closure.get("state"),
            "not_verified",
            "supply_chain.transitive_license_closure.state",
            errors,
        )
        _expect(
            closure.get("complete"),
            False,
            "supply_chain.transitive_license_closure.complete",
            errors,
        )
        _text(closure.get("blocker"), "supply_chain.transitive_license_closure.blocker", errors)

    vulnerabilities = _object(
        item.get("vulnerability_review"),
        {
            "state",
            "complete",
            "queried_at_utc",
            "alias_deduplication",
            "finding_count",
            "affected_lock_packages",
            "sources",
            "finding_ids",
            "limitations",
        },
        "supply_chain.vulnerability_review",
        errors,
    )
    if vulnerabilities is not None:
        state = _text(
            vulnerabilities.get("state"), "supply_chain.vulnerability_review.state", errors
        )
        if state is not None and state not in {"recorded_metadata", "not_verified"}:
            errors.append("supply_chain.vulnerability_review.state: cannot claim verified closure")
        _expect(
            vulnerabilities.get("complete"),
            False,
            "supply_chain.vulnerability_review.complete",
            errors,
        )
        _timestamp(
            vulnerabilities.get("queried_at_utc"),
            "supply_chain.vulnerability_review.queried_at_utc",
            errors,
        )
        _expect(
            vulnerabilities.get("alias_deduplication"),
            "cve_group",
            "supply_chain.vulnerability_review.alias_deduplication",
            errors,
        )
        _expect(
            vulnerabilities.get("finding_count"),
            6,
            "supply_chain.vulnerability_review.finding_count",
            errors,
        )
        packages = _list(
            vulnerabilities.get("affected_lock_packages"),
            "supply_chain.vulnerability_review.affected_lock_packages",
            errors,
        )
        observed_packages: dict[str, tuple[str, set[str]]] = {}
        if packages is not None:
            for index, raw in enumerate(packages):
                package = _object(
                    raw,
                    {"package", "version", "finding_ids"},
                    f"supply_chain.vulnerability_review.affected_lock_packages[{index}]",
                    errors,
                )
                if package is None:
                    continue
                name = _text(
                    package.get("package"),
                    f"supply_chain.vulnerability_review.affected_lock_packages[{index}].package",
                    errors,
                )
                version = _text(
                    package.get("version"),
                    f"supply_chain.vulnerability_review.affected_lock_packages[{index}].version",
                    errors,
                )
                ids = _strings(
                    package.get("finding_ids"),
                    "supply_chain.vulnerability_review.affected_lock_packages"
                    f"[{index}].finding_ids",
                    errors,
                )
                if name is not None and version is not None and ids is not None:
                    if name in observed_packages:
                        errors.append(
                            "supply_chain.vulnerability_review.affected_lock_packages: "
                            f"duplicate package {name!r}"
                        )
                    observed_packages[name] = (version, set(ids))
        if observed_packages != EXPECTED_OSV_PACKAGES:
            errors.append(
                "supply_chain.vulnerability_review.affected_lock_packages: "
                "exact affected lock versions and CVE groups required"
            )
        sources = _strings(
            vulnerabilities.get("sources"), "supply_chain.vulnerability_review.sources", errors
        )
        if sources is not None and sources != EXPECTED_OSV_SOURCES:
            errors.append(
                "supply_chain.vulnerability_review.sources: "
                "must match the canonical primary-source set"
            )
        finding_ids = _strings(
            vulnerabilities.get("finding_ids"),
            "supply_chain.vulnerability_review.finding_ids",
            errors,
        )
        expected_ids = set().union(*(findings for _, findings in EXPECTED_OSV_PACKAGES.values()))
        if finding_ids is not None and set(finding_ids) != expected_ids:
            errors.append(
                "supply_chain.vulnerability_review.finding_ids: "
                "exact six deduplicated CVE groups required"
            )
        limitations = _strings(
            vulnerabilities.get("limitations"),
            "supply_chain.vulnerability_review.limitations",
            errors,
        )
        if limitations is not None and len(limitations) < 2:
            errors.append(
                "supply_chain.vulnerability_review.limitations: incomplete-query limits must remain explicit"
            )

    sbom = _object(
        item.get("sbom"),
        {
            "state",
            "complete",
            "upstream_document_detected",
            "provenance_field_detected",
            "blocker",
        },
        "supply_chain.sbom",
        errors,
    )
    if sbom is not None:
        _expect(sbom.get("state"), "not_verified", "supply_chain.sbom.state", errors)
        _expect(sbom.get("complete"), False, "supply_chain.sbom.complete", errors)
        _expect(
            sbom.get("upstream_document_detected"),
            False,
            "supply_chain.sbom.upstream_document_detected",
            errors,
        )
        _expect(
            sbom.get("provenance_field_detected"),
            False,
            "supply_chain.sbom.provenance_field_detected",
            errors,
        )
        _text(sbom.get("blocker"), "supply_chain.sbom.blocker", errors)


def _validate_compatibility(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {"repository_python", "upstream_python", "target_platforms", "fixture", "isolation"},
        "compatibility",
        errors,
    )
    if item is None:
        return
    _expect(item.get("repository_python"), "3.12", "compatibility.repository_python", errors)
    _expect(item.get("upstream_python"), ">=3.11,<3.14", "compatibility.upstream_python", errors)
    platforms = _strings(item.get("target_platforms"), "compatibility.target_platforms", errors)
    if platforms is not None and platforms != ["linux", "windows"]:
        errors.append("compatibility.target_platforms: must be ['linux', 'windows']")

    fixture = _object(
        item.get("fixture"),
        {"state", "executed", "synthetic_task", "required_assertions"},
        "compatibility.fixture",
        errors,
    )
    if fixture is not None:
        _expect(fixture.get("state"), "not_executed", "compatibility.fixture.state", errors)
        _expect(fixture.get("executed"), False, "compatibility.fixture.executed", errors)
        _text(fixture.get("synthetic_task"), "compatibility.fixture.synthetic_task", errors)
        assertions = _strings(
            fixture.get("required_assertions"), "compatibility.fixture.required_assertions", errors
        )
        if assertions is not None and len(assertions) < 6:
            errors.append(
                "compatibility.fixture.required_assertions: at least six gates are required"
            )
        if assertions is not None:
            for boundary in sorted(REQUIRED_FIXTURE_BOUNDARIES):
                if not any(boundary in assertion for assertion in assertions):
                    errors.append(
                        f"compatibility.fixture.required_assertions: missing boundary {boundary!r}"
                    )

    isolation = _object(
        item.get("isolation"),
        {"state", "b7_issue", "requirements"},
        "compatibility.isolation",
        errors,
    )
    if isolation is not None:
        _expect(isolation.get("state"), "blocked", "compatibility.isolation.state", errors)
        _expect(isolation.get("b7_issue"), 818, "compatibility.isolation.b7_issue", errors)
        requirements = _strings(
            isolation.get("requirements"), "compatibility.isolation.requirements", errors
        )
        if requirements is not None and len(requirements) < 8:
            errors.append("compatibility.isolation.requirements: isolation envelope is incomplete")


def _validate_e9(value: Any, errors: list[str]) -> None:
    item = _object(
        value,
        {"state", "benchmark_issue", "dimensions", "negative_cases", "can_promote"},
        "e9",
        errors,
    )
    if item is None:
        return
    _expect(item.get("state"), "not_measured", "e9.state", errors)
    _expect(item.get("benchmark_issue"), 767, "e9.benchmark_issue", errors)
    _expect(item.get("can_promote"), False, "e9.can_promote", errors)
    dimensions = _list(item.get("dimensions"), "e9.dimensions", errors)
    seen: list[str] = []
    if dimensions is not None:
        for index, raw in enumerate(dimensions):
            dimension = _object(raw, {"name", "state"}, f"e9.dimensions[{index}]", errors)
            if dimension is None:
                continue
            name = _text(dimension.get("name"), f"e9.dimensions[{index}].name", errors)
            if name is not None:
                seen.append(name)
            _expect(dimension.get("state"), "not_measured", f"e9.dimensions[{index}].state", errors)
    if seen != E9_DIMENSIONS:
        errors.append(f"e9.dimensions: ordered names must be {E9_DIMENSIONS}")
    negative = _strings(item.get("negative_cases"), "e9.negative_cases", errors)
    if negative is not None and len(negative) < 5:
        errors.append("e9.negative_cases: cancellation/failure/rollback coverage is incomplete")


def _validate_authority(value: Any, errors: list[str]) -> None:
    fields = {
        "grants_authority",
        "can_install",
        "can_import",
        "can_execute",
        "can_register_provider",
        "can_add_route",
        "can_access_credentials",
        "can_write_canonical_state",
        "can_authorize",
        "can_approve",
        "can_mark_complete",
        "can_promote",
        "release_ready",
    }
    item = _object(value, fields, "authority", errors)
    if item is None:
        return
    for field in sorted(fields):
        _expect(item.get(field), False, f"authority.{field}", errors)


def _validate_repository_effects(value: Any, root: Path | None, errors: list[str]) -> None:
    fields = {
        "dependency_enrolled",
        "manifest_enrolled",
        "adapter_implemented",
        "provider_registered",
        "route_added",
        "runtime_changed",
        "shared_ledgers_changed",
        "checked_dependency_files",
        "checked_manifest_path",
    }
    item = _object(value, fields, "repository_effects", errors)
    if item is None:
        return
    for field in (
        "dependency_enrolled",
        "manifest_enrolled",
        "adapter_implemented",
        "provider_registered",
        "route_added",
        "runtime_changed",
    ):
        _expect(item.get(field), False, f"repository_effects.{field}", errors)
    _expect(
        item.get("shared_ledgers_changed"),
        True,
        "repository_effects.shared_ledgers_changed",
        errors,
    )
    dependency_files = _strings(
        item.get("checked_dependency_files"),
        "repository_effects.checked_dependency_files",
        errors,
    )
    if dependency_files is not None and dependency_files != EXPECTED_REPOSITORY_DEPENDENCY_FILES:
        errors.append(
            "repository_effects.checked_dependency_files: "
            "must match the canonical dependency surfaces"
        )
    _expect(
        item.get("checked_manifest_path"),
        ".github/third-party-manifest.json",
        "repository_effects.checked_manifest_path",
        errors,
    )
    if root is None or dependency_files is None:
        return
    for relative in dependency_files:
        if relative.startswith("/") or "\\" in relative or ".." in Path(relative).parts:
            errors.append(f"repository_effects.checked_dependency_files: unsafe path {relative!r}")
            continue
        path = root / relative
        try:
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                errors.append(
                    f"repository dependency evidence {relative}: must be a non-symlink regular file"
                )
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"repository dependency evidence {relative}: cannot read: {exc}")
            continue
        if "hermes-agent" in _declared_distribution_names(text):
            errors.append(f"repository_effects: hermes-agent is enrolled in {relative}")
    manifest_path = root / ".github" / "third-party-manifest.json"
    try:
        manifest = load_json_strict(manifest_path)
    except PreflightError as exc:
        errors.append(f"repository_effects: cannot inspect third-party manifest: {exc}")
        return
    if not isinstance(manifest, dict):
        errors.append("repository_effects: third-party manifest must be an object")
        return
    manifest_entries: list[Any] = []
    for section in ("sources", "untracked"):
        entries = manifest.get(section)
        if not isinstance(entries, list):
            errors.append(f"repository_effects: third-party manifest {section} must be an array")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(
                    f"repository_effects: third-party manifest {section} entries must be objects"
                )
                continue
            manifest_entries.append(entry)
    for source in manifest_entries:
        name = source.get("name")
        repo = source.get("repo")
        normalized_name = _normalize_distribution_name(name) if isinstance(name, str) else ""
        normalized_repo = repo.casefold().strip() if isinstance(repo, str) else ""
        if normalized_name == "hermes-agent" or normalized_repo == ("nousresearch/hermes-agent"):
            errors.append("repository_effects: Hermes is enrolled in third-party manifest")


def validate_evidence(data: Any, *, root: Path | None = None) -> list[str]:
    """Return deterministic validation errors for a parsed preflight artifact."""

    errors: list[str] = []
    item = _object(
        data,
        {
            "schema_version",
            "record_id",
            "status",
            "method",
            "upstream",
            "distribution",
            "invocation_surfaces",
            "side_effects",
            "supply_chain",
            "compatibility",
            "e9",
            "authority",
            "repository_effects",
        },
        "root",
        errors,
    )
    if item is None:
        return errors
    _expect(item.get("schema_version"), 1, "schema_version", errors)
    _expect(item.get("record_id"), "nerva.e8.1c.hermes-preflight.v1", "record_id", errors)
    _validate_status(item.get("status"), errors)
    _validate_method(item.get("method"), errors)
    _validate_upstream(item.get("upstream"), errors)
    _validate_distribution(item.get("distribution"), errors)
    _validate_invocation_surfaces(item.get("invocation_surfaces"), errors)
    _validate_side_effects(item.get("side_effects"), errors)
    _validate_supply_chain(item.get("supply_chain"), errors)
    _validate_compatibility(item.get("compatibility"), errors)
    _validate_e9(item.get("e9"), errors)
    _validate_authority(item.get("authority"), errors)
    _validate_repository_effects(item.get("repository_effects"), root, errors)
    return errors


def _md(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(text.splitlines())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def render_markdown(data: dict[str, Any]) -> str:
    """Render the already-validated canonical artifact deterministically."""

    status = data["status"]
    upstream = data["upstream"]
    distribution = data["distribution"]
    supply = data["supply_chain"]
    lines = [
        "# Nerva E8.1c — Hermes invocation and supply-chain preflight",
        "",
        "> Generated from `EXECUTION_PROVIDER_E8_1C_PREFLIGHT.json`; do not edit by hand.",
        "",
        f"Status: `{_md(status['evidence_status'])}` · adapter `{_md(status['adapter_status'])}` · "
        f"E8.1 `{_md(status['program_status'])}` · release ready `{_yes_no(status['release_ready'])}`.",
        "",
        "This is static, public-source preflight evidence only. No Hermes package or OCI image/layer was downloaded, installed, imported or executed; only public source and metadata payloads were inspected. It proves no compatibility, safety, benchmark benefit or authority.",
        "",
        "## Immutable upstream snapshot",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Observed | {_md(status['observed_at_utc'])} |",
        f"| Repository | {_md(upstream['repository'])} |",
        f"| Release | {_md(upstream['release_tag'])} |",
        f"| Tag object | {_md(upstream['tag_object_sha'])} ({_md(upstream['tag_verification'])}) |",
        f"| Commit | {_md(upstream['commit_sha'])} ({_md(upstream['commit_verification'])}) |",
        f"| Tree | {_md(upstream['tree_sha'])} |",
        f"| Default-branch drift at {_md(upstream['default_branch_comparison']['observed_at_utc'])} | main is {upstream['default_branch_comparison']['ahead_by']} ahead / {upstream['default_branch_comparison']['behind_by']} behind the pin |",
        "",
        "### Bound source files",
        "",
        "| Path | Git blob | SHA-256 | Bytes |",
        "|---|---|---|---:|",
    ]
    for source in sorted(upstream["source_files"], key=lambda item: item["path"]):
        lines.append(
            f"| {_md(source['path'])} | {_md(source['blob_sha'])} | {_md(source['sha256'])} | {source['size']} |"
        )
    lines.extend(
        [
            "",
            "## Distribution and invocation decision",
            "",
            f"Pinned source reports `{_md(distribution['source_distribution'])}` `{_md(distribution['source_version'])}` with Python `{_md(distribution['requires_python'])}`. The selected future distribution route is `{_md(distribution['selected_distribution_route'])}` at OCI index `{_md(distribution['container']['index_digest'])}`.",
            "",
            f"PyPI still reports `{_md(distribution['pypi']['observed_version'])}` and therefore does not distribute the selected `0.20.0` source commit. Its {_md(distribution['pypi']['response_bytes'])}-byte response is content-bound in the canonical artifact; no package artifact was downloaded.",
            "",
            f"OCI provenance metadata was observed for {len(distribution['container']['provenance']['statements'])} platform manifests, but authenticity is not independently verified, no signature is present, BuildKit material completeness is false and the registry returned {distribution['container']['provenance']['registry_referrer_count']} referrers.",
            "",
            "| Surface | Mapping / selector | Decision | Result contract |",
            "|---|---|---|---|",
        ]
    )
    for surface in sorted(data["invocation_surfaces"], key=lambda item: item["id"]):
        lines.append(
            f"| {_md(surface['id'])} | {_md(surface['entrypoint_chain'])}; {_md(surface['selector'])} | {_md(surface['decision'])} | {_md(surface['result_contract'])} |"
        )
    lines.extend(
        [
            "",
            "`hermes-agent = run_agent:main` is rejected as a programmatic seam. `hermes -z/--oneshot` is only a candidate for a later isolated fixture. The chat-only `--safe-mode` flag cannot be passed to one-shot; a later fixture must set `HERMES_SAFE_MODE=1` before process start, and that environment setting is still insufficient isolation. Nothing was accepted or executed.",
            "",
            "## Statically observed side effects",
            "",
            "| ID | Phase | Evidence | Risk |",
            "|---|---|---|---|",
        ]
    )
    for effect in sorted(data["side_effects"], key=lambda item: item["id"]):
        anchors = ", ".join(effect["anchors"])
        lines.append(
            f"| {_md(effect['id'])} | {_md(effect['phase'])} | {_md(effect['source_path'])} {_md(anchors)}: {_md(effect['behavior'])} | {_md(effect['risk'])} |"
        )
    lines.extend(
        [
            "",
            "## Supply-chain state",
            "",
            "| Evidence | State | Result |",
            "|---|---|---|",
            f"| Direct requirements | {_md(supply['direct_dependencies']['evidence_state'])} | {supply['direct_dependencies']['count']} requirements; not all exact-pinned |",
            f"| Optional groups | {_md(supply['optional_dependencies']['evidence_state'])} | {supply['optional_dependencies']['group_count']} groups; none selected here |",
            f"| Upstream lock | {_md(supply['lock_snapshot']['evidence_state'])} | {supply['lock_snapshot']['package_records']} records / {supply['lock_snapshot']['unique_names']} names; zero license fields |",
            f"| Upstream license | {_md(supply['upstream_license']['evidence_state'])} | {_md(supply['upstream_license']['expression'])} |",
            f"| Bundled license findings | {_md(supply['bundled_license_findings']['state'])}; complete={_yes_no(supply['bundled_license_findings']['complete'])}; accepted={_yes_no(supply['bundled_license_findings']['owner_or_legal_acceptance'])} | {_md(supply['bundled_license_findings']['blocker'])} |",
            f"| Transitive license closure | {_md(supply['transitive_license_closure']['state'])} | {_md(supply['transitive_license_closure']['blocker'])} |",
            f"| Vulnerability review | {_md(supply['vulnerability_review']['state'])}; complete={_yes_no(supply['vulnerability_review']['complete'])}; {supply['vulnerability_review']['finding_count']} CVE groups | {_md('; '.join(item.rstrip('.') for item in sorted(supply['vulnerability_review']['limitations'])))} |",
            f"| SBOM | {_md(supply['sbom']['state'])}; complete={_yes_no(supply['sbom']['complete'])} | {_md(supply['sbom']['blocker'])} |",
            "",
            "Restrictive bundled-license paths: "
            + ", ".join(
                f"`{_md(item['path'])}`"
                for item in sorted(
                    supply["bundled_license_findings"]["findings"],
                    key=lambda item: item["path"],
                )
            )
            + ".",
            "",
            "OSV-identified lock versions (six CVE groups after alias de-duplication): "
            + "; ".join(
                f"`{_md(item['package'])} {_md(item['version'])}`: "
                + ", ".join(f"`{_md(identifier)}`" for identifier in sorted(item["finding_ids"]))
                for item in sorted(
                    supply["vulnerability_review"]["affected_lock_packages"],
                    key=lambda item: item["package"],
                )
            )
            + ". Advisory-range conflicts remain fail-closed; this is not an exploitability determination.",
            "",
            "## Later compatibility and isolation fixture",
            "",
            f"Fixture state: `{_md(data['compatibility']['fixture']['state'])}`. Isolation state: `{_md(data['compatibility']['isolation']['state'])}` on B7/#818.",
            "",
        ]
    )
    for requirement in sorted(data["compatibility"]["isolation"]["requirements"]):
        lines.append(f"- {_md(requirement)}")
    lines.extend(["", "### Required assertions for the unexecuted fixture", ""])
    for assertion in sorted(data["compatibility"]["fixture"]["required_assertions"]):
        lines.append(f"- {_md(assertion)}")
    lines.extend(
        [
            "",
            "## E9 and authority",
            "",
            "All provider-specific E9 dimensions remain `not_measured`: "
            + ", ".join(dimension["name"] for dimension in data["e9"]["dimensions"])
            + ".",
            "",
            "Every authority flag and every dependency, third-party-manifest, adapter, provider, route and runtime repository-effect flag is `false`. The same PR reconciles shared documentation, workflow and generated ledgers (`shared_ledgers_changed=true`) without granting runtime authority. The preflight cannot install, import, execute, register, route, authorize, approve, mark complete, promote or claim release readiness. Ultron / `nerva.action.v1` remains the sole privileged-action authority.",
            "",
            "## Remaining blockers",
            "",
        ]
    )
    for limitation in sorted(data["method"]["limitations"]):
        lines.append(f"- {_md(limitation)}")
    lines.extend(
        [
            "",
            "Completion of this preflight would not complete E8.1c or E8.1. A Hermes-executing adapter, manifest enrolment, supply-chain closure, trusted Nerva kernel context, compatibility runs and E9 comparison remain separate reviewed packages.",
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
        if expected.is_symlink():
            return "generated Markdown target must not be a symlink"
        if expected.exists():
            metadata = expected.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                return "generated Markdown target must be a regular file"
            if metadata.st_size > MAX_DOCUMENT_BYTES:
                return f"generated Markdown target exceeds {MAX_DOCUMENT_BYTES} bytes"
    except (OSError, RuntimeError, ValueError) as exc:
        return f"generated Markdown target is unsafe: {exc}"
    return None


def _atomic_write(root: Path, path: Path, payload: bytes) -> None:
    target_error = _validate_output_target(root, path)
    if target_error:
        raise PreflightError(target_error)
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as exc:
        raise PreflightError(f"cannot create generated Markdown temporary file: {exc}") from exc
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        target_error = _validate_output_target(root, path)
        if target_error:
            raise PreflightError(target_error)
        os.replace(temporary, path)
    except (PreflightError, OSError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            if isinstance(exc, PreflightError):
                raise
            raise PreflightError(f"cannot update generated Markdown: {exc}") from exc


def _read_document_bounded(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_DOCUMENT_BYTES + 1)
    except OSError as exc:
        raise PreflightError(f"cannot read generated Markdown: {exc}") from exc
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise PreflightError(f"generated Markdown target exceeds {MAX_DOCUMENT_BYTES} bytes")
    return payload


def run(root: Path, *, write: bool) -> list[str]:
    evidence_path = root / EVIDENCE_RELATIVE
    document_path = root / DOCUMENT_RELATIVE
    data = load_json_strict(evidence_path)
    errors = validate_evidence(data, root=root)
    if errors:
        raise PreflightError("invalid E8.1c preflight:\n- " + "\n- ".join(errors))
    rendered = render_markdown(data).encode("utf-8")
    target_error = _validate_output_target(root, document_path)
    if target_error:
        raise PreflightError(target_error)
    if write:
        before = _read_document_bounded(document_path) if document_path.exists() else None
        _atomic_write(root, document_path, rendered)
        return [
            "generated Markdown already current"
            if before == rendered
            else "generated Markdown updated"
        ]
    current = _read_document_bounded(document_path)
    if current != rendered:
        raise PreflightError("generated Markdown drift; run with --write")
    return ["E8.1c preflight valid; generated Markdown current"]


def _safe_error_text(exc: BaseException) -> str:
    text = str(exc)
    escaped = "".join(
        character
        if unicodedata.category(character) not in {"Cc", "Cf"} or character in "\n\t"
        else f"\\x{ord(character):02x}"
        for character in text
    )
    encoding = sys.stderr.encoding or "utf-8"
    return escaped.encode(encoding, errors="backslashreplace").decode(encoding)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate without writing (default)")
    mode.add_argument("--write", action="store_true", help="regenerate canonical Markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        root = args.root.resolve(strict=True)
        messages = run(root, write=args.write)
    except (PreflightError, OSError, RuntimeError, ValueError) as exc:
        print(_safe_error_text(exc), file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
