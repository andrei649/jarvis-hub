#!/usr/bin/env python3
"""Validate the canonical Nerva AI-development policy and its derived entrypoints."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

POLICY_RELATIVE = Path(".github/ai-development-policy.json")
PR_TEMPLATE_RELATIVE = Path(".github/pull_request_template.md")
DERIVED_DOCUMENTS = (
    Path("AGENTS.md"),
    Path("PARALLEL_WORKFLOW.md"),
    Path("docs/AGENT_WORKFLOW.md"),
)
HISTORICAL_DOCUMENTS = (
    Path(".opencode/plans/dev-methodology.md"),
    Path(".opencode/summary.md"),
    Path("docs/SPRINT.md"),
)
EXPECTED_RISK_TIERS = {"R0", "R1", "R2", "R3"}
EXPECTED_AUTOMATED_RISK_MAPPING = {"low": "R0", "medium": "R2", "high": "R3"}
EXPECTED_STATE_SETS = {
    "delivery": {
        "planned",
        "in_progress",
        "draft",
        "ready",
        "blocked",
        "merged",
        "superseded",
    },
    "ci": {"not_run", "running", "passed", "failed", "cancelled", "skipped", "stale"},
    "governance": {
        "unclassified",
        "review_required",
        "changes_requested",
        "approved",
        "owner_hold",
        "stale",
    },
    "lease": {"none", "requested", "active", "contested", "expired", "released"},
}
RECEIPT_FIELDS = {
    "policy_id",
    "policy_schema_version",
    "head_sha",
    "risk_tier",
    "changed_paths",
    "commands",
    "results",
    "producer",
    "generated_at",
}
PR_TEMPLATE_MARKERS = (
    "## Risk classification",
    "<!-- ai-policy-receipt:start -->",
    "policy_id: nerva-ai-development-v1",
    "policy_schema_version: 1",
    "head_sha: REPLACE_WITH_40_CHARACTER_HEAD_SHA",
    "risk_tier: REPLACE_WITH_R0_R1_R2_OR_R3",
    "changed_paths:",
    "commands:",
    "results:",
    "producer:",
    "generated_at:",
    "delivery_state:",
    "ci_state:",
    "governance_state:",
    "lease_state: none",
    "review_round:",
    "## Verification evidence",
    "Evidence head SHA",
    "two-round limit",
    "<!-- ai-policy-receipt:end -->",
)
RECEIPT_BLOCK = re.compile(
    r"<!-- ai-policy-receipt:start -->(.*?)<!-- ai-policy-receipt:end -->", re.DOTALL
)
FORBIDDEN_ACTIVE_GUIDANCE = {
    "git pull --rebase origin master": "obsolete default branch and unconditional sync",
    "claude pushes directly to main": "vendor-specific direct-push workflow",
    "a draft pr owns its touched files": "draft-as-lock coupling",
    "commit + push after every unit": "push-per-microtask CI churn",
    "do not edit files modified in the last 24h": "age-based ownership heuristic",
    "github-backed path-prefix leases are the coordination system of record": (
        "unenforced remote-lease claim"
    ),
    "the coordination system of record is a github-backed lease": "unenforced remote-lease claim",
}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains an ambiguous duplicate key."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_policy(path: Path) -> tuple[object | None, list[str]]:
    """Load the policy strictly and return data plus human-readable errors."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"{path}: cannot read policy: {exc}"]
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys), []
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        return None, [f"{path}: invalid policy JSON: {exc}"]


def _as_mapping(value: object, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return {}
    return value


def _string_set(value: object, location: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{location} must be a list of strings")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{location} must not contain duplicates")
    return set(value)


def _validate_policy_identity(policy: dict[str, Any], errors: list[str]) -> None:
    if policy.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if policy.get("policy_id") != "nerva-ai-development-v1":
        errors.append("policy_id must be nerva-ai-development-v1")


def _validate_authority(policy: dict[str, Any], errors: list[str]) -> None:
    authority = _as_mapping(policy.get("authority"), "authority", errors)
    if authority.get("canonical") is not True:
        errors.append("authority.canonical must be true")
    derived = _string_set(authority.get("derived_documents"), "authority.derived_documents", errors)
    if derived != {str(path) for path in DERIVED_DOCUMENTS}:
        errors.append("authority.derived_documents must name the three maintained guides exactly")
    historical = _string_set(
        authority.get("historical_documents"), "authority.historical_documents", errors
    )
    if historical != {str(path) for path in HISTORICAL_DOCUMENTS}:
        errors.append("authority.historical_documents must name all legacy context documents")


def _validate_preflight(policy: dict[str, Any], errors: list[str]) -> None:
    preflight = _as_mapping(policy.get("preflight"), "preflight", errors)
    if preflight.get("automatic_rebase") is not False:
        errors.append("preflight.automatic_rebase must be false")
    if preflight.get("preserve_unrelated_changes") is not True:
        errors.append("preflight.preserve_unrelated_changes must be true")
    rebase_requires = _string_set(
        preflight.get("rebase_requires"), "preflight.rebase_requires", errors
    )
    for required in {"owned_feature_branch", "clean_worktree", "no_uncommitted_user_changes"}:
        if required not in rebase_requires:
            errors.append(f"preflight.rebase_requires missing {required}")
    rebase_forbidden = _string_set(
        preflight.get("rebase_forbidden_when"), "preflight.rebase_forbidden_when", errors
    )
    for forbidden in {"read_only_task", "dirty_worktree", "unowned_changes_present"}:
        if forbidden not in rebase_forbidden:
            errors.append(f"preflight.rebase_forbidden_when missing {forbidden}")


def _validate_risk_tiers(policy: dict[str, Any], errors: list[str]) -> None:
    tiers = _as_mapping(policy.get("risk_tiers"), "risk_tiers", errors)
    if set(tiers) != EXPECTED_RISK_TIERS:
        errors.append("risk_tiers must be exactly R0, R1, R2, and R3")
    tier_mappings: dict[str, dict[str, Any]] = {}
    for tier_id in sorted(EXPECTED_RISK_TIERS):
        tier = _as_mapping(tiers.get(tier_id), f"risk_tiers.{tier_id}", errors)
        tier_mappings[tier_id] = tier
        _string_set(
            tier.get("required_controls"), f"risk_tiers.{tier_id}.required_controls", errors
        )
    r3_controls = set(tier_mappings["R3"].get("required_controls", []))
    if "separate_builder_reviewer_integrator" not in r3_controls:
        errors.append("R3 must require separate builder, reviewer, and integrator")


def _validate_automated_risk_mapping(policy: dict[str, Any], errors: list[str]) -> None:
    automated_risk = _as_mapping(
        policy.get("automated_risk_mapping"), "automated_risk_mapping", errors
    )
    mapping = _as_mapping(automated_risk.get("mapping"), "automated_risk_mapping.mapping", errors)
    if mapping != EXPECTED_AUTOMATED_RISK_MAPPING:
        errors.append(
            "automated_risk_mapping.mapping must conservatively map "
            "low->R0, medium->R2, and high->R3"
        )
    if automated_risk.get("posture") != "conservative":
        errors.append("automated_risk_mapping.posture must be conservative")
    if automated_risk.get("source") != ".github/change-risk.json:risk_level":
        errors.append("automated_risk_mapping.source must name change-risk.json:risk_level")


def _validate_lease_status(coordination: dict[str, Any], errors: list[str]) -> None:
    if coordination.get("lease_system_of_record") != "none":
        errors.append("coordination.lease_system_of_record must be none until enforcement exists")
    if coordination.get("planned_lease_system_of_record") != "github":
        errors.append("coordination.planned_lease_system_of_record must be github")
    if coordination.get("lease_enforcement_status") != "not_implemented":
        errors.append("coordination.lease_enforcement_status must be not_implemented")
    if coordination.get("active_lease_claims_allowed") is not False:
        errors.append("coordination.active_lease_claims_allowed must be false")


def _validate_planned_lease_contract(coordination: dict[str, Any], errors: list[str]) -> None:
    if coordination.get("planned_lease_granularity") != "path-prefix":
        errors.append("coordination.planned_lease_granularity must be path-prefix")
    planned_lease_fields = _string_set(
        coordination.get("planned_lease_fields"), "coordination.planned_lease_fields", errors
    )
    if planned_lease_fields != {
        "holder",
        "path_prefixes",
        "purpose",
        "base_sha",
        "expires_at",
        "heartbeat_at",
    }:
        errors.append("coordination.planned_lease_fields must match the planned lease contract")
    for active_key in ("lease_granularity", "lease_required_fields"):
        if active_key in coordination:
            errors.append(f"coordination.{active_key} must remain absent until enforcement exists")


def _validate_coordination(policy: dict[str, Any], errors: list[str]) -> None:
    coordination = _as_mapping(policy.get("coordination"), "coordination", errors)
    if coordination.get("draft_pr_is_lock") is not False:
        errors.append("coordination.draft_pr_is_lock must be false")
    _validate_lease_status(coordination, errors)
    _validate_planned_lease_contract(coordination, errors)
    if coordination.get("local_lock_files_are_advisory") is not True:
        errors.append("coordination.local_lock_files_are_advisory must be true")
    if coordination.get("capability_based_routing") is not True:
        errors.append("coordination.capability_based_routing must be true")
    role_separation = _string_set(
        coordination.get("r3_role_separation"), "coordination.r3_role_separation", errors
    )
    if role_separation != {"builder", "reviewer", "integrator"}:
        errors.append("coordination.r3_role_separation must be builder/reviewer/integrator")


def _validate_review(policy: dict[str, Any], errors: list[str]) -> None:
    review = _as_mapping(policy.get("review"), "review", errors)
    if review.get("max_normal_rounds") != 2:
        errors.append("review.max_normal_rounds must be 2")
    if review.get("after_limit") != "escalate_with_unresolved_findings":
        errors.append("review.after_limit must escalate unresolved findings")
    if review.get("new_head_invalidates_prior_approval") is not True:
        errors.append("review.new_head_invalidates_prior_approval must be true")


def _validate_state_machine(
    machine_name: str,
    expected_states: set[str],
    machines: dict[str, Any],
    errors: list[str],
) -> None:
    machine = _as_mapping(machines.get(machine_name), f"state_machines.{machine_name}", errors)
    transitions = _as_mapping(
        machine.get("transitions"), f"state_machines.{machine_name}.transitions", errors
    )
    if set(transitions) != expected_states:
        errors.append(f"state_machines.{machine_name} must define every expected state")
    if machine.get("initial") not in expected_states:
        errors.append(f"state_machines.{machine_name}.initial must be a known state")
    terminals = _string_set(
        machine.get("terminal"), f"state_machines.{machine_name}.terminal", errors
    )
    if not terminals <= expected_states:
        errors.append(f"state_machines.{machine_name}.terminal contains an unknown state")
    for source, targets in transitions.items():
        target_set = _string_set(
            targets, f"state_machines.{machine_name}.transitions.{source}", errors
        )
        unknown = target_set - expected_states
        if unknown:
            errors.append(
                f"state_machines.{machine_name}.{source} targets unknown states: "
                + ", ".join(sorted(unknown))
            )


def _validate_state_machines(policy: dict[str, Any], errors: list[str]) -> None:
    machines = _as_mapping(policy.get("state_machines"), "state_machines", errors)
    if set(machines) != set(EXPECTED_STATE_SETS):
        errors.append("state_machines must separate delivery, ci, governance, and lease")
    for machine_name, expected_states in EXPECTED_STATE_SETS.items():
        _validate_state_machine(machine_name, expected_states, machines, errors)
    lease_machine = _as_mapping(machines.get("lease"), "state_machines.lease", errors)
    if lease_machine.get("implementation_status") != "planned_not_implemented":
        errors.append("state_machines.lease.implementation_status must be planned_not_implemented")


def _validate_evidence_receipt_policy(policy: dict[str, Any], errors: list[str]) -> None:
    receipt = _as_mapping(policy.get("evidence_receipt"), "evidence_receipt", errors)
    if receipt.get("bind_to") != "exact_head_sha":
        errors.append("evidence_receipt.bind_to must be exact_head_sha")
    fields = _string_set(receipt.get("required_fields"), "evidence_receipt.required_fields", errors)
    if fields != RECEIPT_FIELDS:
        errors.append("evidence_receipt.required_fields must match the exact receipt contract")
    reuse = _as_mapping(receipt.get("reuse"), "evidence_receipt.reuse", errors)
    for condition in (
        "requires_same_head_sha",
        "requires_same_policy_id",
        "requires_same_policy_schema_version",
        "requires_unchanged_relevant_inputs",
    ):
        if reuse.get(condition) is not True:
            errors.append(f"evidence_receipt.reuse.{condition} must be true")
    if reuse.get("otherwise_state") != "stale":
        errors.append("evidence_receipt.reuse.otherwise_state must be stale")


def _validate_context(policy: dict[str, Any], errors: list[str]) -> None:
    context = _as_mapping(policy.get("context"), "context", errors)
    if context.get("stale_session_summaries_are_instructions") is not False:
        errors.append("context.stale_session_summaries_are_instructions must be false")
    if context.get("historical_documents_are_current_state") is not False:
        errors.append("context.historical_documents_are_current_state must be false")


def _validate_change_control(policy: dict[str, Any], errors: list[str]) -> None:
    change_control = _as_mapping(policy.get("change_control"), "change_control", errors)
    if change_control.get("default_branch") != "main":
        errors.append("change_control.default_branch must be main")
    if change_control.get("direct_push_to_default_branch") is not False:
        errors.append("change_control.direct_push_to_default_branch must be false")
    if change_control.get("remote_mutations_require_authorization") is not True:
        errors.append("change_control.remote_mutations_require_authorization must be true")
    if change_control.get("unrelated_cleanup_allowed") is not False:
        errors.append("change_control.unrelated_cleanup_allowed must be false")


def validate_policy(data: object) -> list[str]:
    """Validate safety and lifecycle invariants in parsed policy data."""

    errors: list[str] = []
    policy = _as_mapping(data, "policy", errors)
    if not policy:
        return errors

    _validate_policy_identity(policy, errors)
    _validate_authority(policy, errors)
    _validate_preflight(policy, errors)
    _validate_risk_tiers(policy, errors)
    _validate_automated_risk_mapping(policy, errors)
    _validate_coordination(policy, errors)
    _validate_review(policy, errors)
    _validate_state_machines(policy, errors)
    _validate_evidence_receipt_policy(policy, errors)
    _validate_context(policy, errors)
    _validate_change_control(policy, errors)
    return errors


def _validate_receipt_identity(
    receipt: dict[str, Any], policy: dict[str, Any], errors: list[str]
) -> None:
    missing = sorted(RECEIPT_FIELDS - set(receipt))
    if missing:
        errors.append("receipt missing canonical fields: " + ", ".join(missing))
    if receipt.get("policy_id") != policy.get("policy_id"):
        errors.append("receipt.policy_id does not match the canonical policy")
    if receipt.get("policy_schema_version") != policy.get("schema_version"):
        errors.append("receipt.policy_schema_version does not match the canonical policy")

    head_sha = receipt.get("head_sha")
    if not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        errors.append("receipt.head_sha must be an exact lowercase 40-hex commit")
    if receipt.get("risk_tier") not in EXPECTED_RISK_TIERS:
        errors.append("receipt.risk_tier must be R0, R1, R2, or R3")


def _validate_receipt_classification(
    receipt: dict[str, Any], policy: dict[str, Any], errors: list[str]
) -> None:
    classification = receipt.get("classification")
    if isinstance(classification, dict):
        risk_level = classification.get("risk_level")
        risk_policy = policy.get("automated_risk_mapping")
        mapping = risk_policy.get("mapping", {}) if isinstance(risk_policy, dict) else {}
        expected_tier = mapping.get(risk_level) if isinstance(mapping, dict) else None
        if expected_tier is not None and receipt.get("risk_tier") != expected_tier:
            errors.append("receipt.risk_tier does not match the automated change-risk mapping")
        metadata = classification.get("metadata")
        classified_head = metadata.get("head_sha") if isinstance(metadata, dict) else None
        if classified_head and classified_head != receipt.get("head_sha"):
            errors.append("receipt.head_sha does not match classification.metadata.head_sha")


def _validate_receipt_changed_paths(receipt: dict[str, Any], errors: list[str]) -> None:
    changed_paths = receipt.get("changed_paths")
    if not isinstance(changed_paths, list) or not all(
        isinstance(path, str) and path for path in changed_paths
    ):
        errors.append("receipt.changed_paths must be a list of non-empty paths")
    elif changed_paths != sorted(set(changed_paths)):
        errors.append("receipt.changed_paths must be sorted and unique")


def _validate_receipt_command(command: object, index: int, errors: list[str]) -> None:
    if not isinstance(command, dict):
        errors.append(f"receipt.commands[{index}] must be an object")
        return
    argv = command.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) and part for part in argv)
    ):
        errors.append(f"receipt.commands[{index}].argv must be a non-empty string list")
    if not isinstance(command.get("cwd"), str) or not command["cwd"]:
        errors.append(f"receipt.commands[{index}].cwd must be a non-empty string")


def _validate_receipt_commands(receipt: dict[str, Any], errors: list[str]) -> None:
    commands = receipt.get("commands")
    if not isinstance(commands, list):
        errors.append("receipt.commands must be a list")
        return
    for index, command in enumerate(commands):
        _validate_receipt_command(command, index, errors)


def _validate_receipt_result(result: object, index: int, errors: list[str]) -> None:
    if not isinstance(result, dict):
        errors.append(f"receipt.results[{index}] must be an object")
        return
    missing_result = {
        "command",
        "exit_code",
        "summary",
    } - set(result)
    if missing_result:
        errors.append(
            f"receipt.results[{index}] missing fields: " + ", ".join(sorted(missing_result))
        )
        return
    command = result["command"]
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        errors.append(f"receipt.results[{index}].command must be a string list")
    exit_code = result["exit_code"]
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        errors.append(f"receipt.results[{index}].exit_code must be an integer")
    if not isinstance(result["summary"], str) or not result["summary"]:
        errors.append(f"receipt.results[{index}].summary must be non-empty")


def _validate_receipt_results(receipt: dict[str, Any], errors: list[str]) -> None:
    results = receipt.get("results")
    if not isinstance(results, list):
        errors.append("receipt.results must be a list")
        return
    for index, result in enumerate(results):
        _validate_receipt_result(result, index, errors)


def _validate_receipt_provenance(receipt: dict[str, Any], errors: list[str]) -> None:
    producer = receipt.get("producer")
    if not isinstance(producer, str) or not producer.strip():
        errors.append("receipt.producer must be a non-empty actor or automation identity")
    generated_at = receipt.get("generated_at")
    if not isinstance(generated_at, str):
        errors.append("receipt.generated_at must be a timezone-aware ISO-8601 timestamp")
    else:
        try:
            timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            timestamp = None
        if timestamp is None or timestamp.tzinfo is None:
            errors.append("receipt.generated_at must be a timezone-aware ISO-8601 timestamp")


def validate_evidence_receipt(receipt_data: object, policy_data: object) -> list[str]:
    """Validate the canonical exact-head receipt emitted by verification tooling."""

    errors: list[str] = []
    receipt = _as_mapping(receipt_data, "receipt", errors)
    policy = _as_mapping(policy_data, "policy", errors)
    if not receipt or not policy:
        return errors

    _validate_receipt_identity(receipt, policy, errors)
    _validate_receipt_classification(receipt, policy, errors)
    _validate_receipt_changed_paths(receipt, errors)
    _validate_receipt_commands(receipt, errors)
    _validate_receipt_results(receipt, errors)
    _validate_receipt_provenance(receipt, errors)
    return errors


def _read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: cannot read document: {exc}")
        return ""


def _validate_active_documents(root: Path, errors: list[str]) -> None:
    active_documents = (*DERIVED_DOCUMENTS, PR_TEMPLATE_RELATIVE)
    for relative in active_documents:
        text = _read_text(root / relative, errors)
        if ".github/ai-development-policy.json" not in text:
            errors.append(f"{relative}: must link to the canonical AI development policy")
        folded = text.casefold()
        for phrase, reason in FORBIDDEN_ACTIVE_GUIDANCE.items():
            if phrase in folded:
                errors.append(f"{relative}: contains {reason}: {phrase!r}")


def _validate_historical_documents(root: Path, errors: list[str]) -> None:
    for relative in HISTORICAL_DOCUMENTS:
        text = _read_text(root / relative, errors)
        banner = "\n".join(text.splitlines()[:12]).casefold()
        if "historical" not in banner and "superseded" not in banner:
            errors.append(f"{relative}: missing historical/superseded status near the top")
        if "instructional: false" not in banner:
            errors.append(f"{relative}: missing instructional: false near the top")
        if ".github/ai-development-policy.json" not in text:
            errors.append(f"{relative}: must point readers to the canonical policy")


def _validate_template_receipt_block(template: str, errors: list[str]) -> None:
    receipt_match = RECEIPT_BLOCK.search(template)
    if not receipt_match:
        return
    top_level_keys = re.findall(r"^([a-z][a-z0-9_]*):", receipt_match.group(1), re.MULTILINE)
    missing_fields = sorted(RECEIPT_FIELDS - set(top_level_keys))
    if missing_fields:
        errors.append(
            f"{PR_TEMPLATE_RELATIVE}: receipt block missing canonical fields: "
            + ", ".join(missing_fields)
        )
    duplicates = sorted({key for key in top_level_keys if top_level_keys.count(key) > 1})
    if duplicates:
        errors.append(
            f"{PR_TEMPLATE_RELATIVE}: receipt block has duplicate fields: " + ", ".join(duplicates)
        )
    for legacy in ("receipt_producer", "receipt_generated_at"):
        if legacy in top_level_keys:
            errors.append(
                f"{PR_TEMPLATE_RELATIVE}: use canonical field name without legacy prefix: {legacy}"
            )


def _validate_pr_template(root: Path, errors: list[str]) -> None:
    template = _read_text(root / PR_TEMPLATE_RELATIVE, errors)
    for marker in PR_TEMPLATE_MARKERS:
        if marker not in template:
            errors.append(f"{PR_TEMPLATE_RELATIVE}: missing required marker {marker!r}")
    _validate_template_receipt_block(template, errors)


def validate_repository(root: Path) -> list[str]:
    """Validate policy plus the maintained and historical documentation contract."""

    root = root.resolve()
    data, errors = load_policy(root / POLICY_RELATIVE)
    if data is not None:
        errors.extend(validate_policy(data))

    _validate_active_documents(root, errors)
    _validate_historical_documents(root, errors)
    _validate_pr_template(root, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (defaults to this script's repository)",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON result")
    args = parser.parse_args(argv)

    errors = validate_repository(args.root)
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
    elif errors:
        print("AI development policy check failed:")
        for error in errors:
            print(f"- {error}")
    else:
        print("AI development policy check passed")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
