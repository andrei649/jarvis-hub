#!/usr/bin/env python3
"""Compact checker for the offline Nerva E0-E12 program manifest.

Restores the control that #981 (``824ff187``) deleted with the PR-blocking gates, as an
advisory post-merge/scheduled job.  The manifest is repository evidence, not live GitHub
state, execution authority, completion authority or a release decision.  It proves:

* every ``movement_gate.registry`` path exists and every ``registry_retired`` path
  is really gone (a dead path in the registry is an error, not a warning);
* ``movement_gate.enforcement_state`` is honest: ``required`` forbids a rollback
  record, ``safety_disabled`` demands a bound one;
* stream statuses, gates, blockers and delivery eligibility follow the manifest's
  own derivation table and agree with ``docs/nerva2/CONTRACT_REGISTRY.json``;
* contract statuses mirrored in the manifest match the registry file byte-for-byte
  (SHA-256) and every contract evidence path exists;
* the rendered Markdown view is byte-identical to the JSON (``--write`` canonicalises the
  JSON, refreshes the contract-registry mirror and regenerates the view).

It never writes ``live_issue_state_verified_by_checker=true``: live verification runs only
through an injected or ``--live`` ``gh issue view`` runner and lives in that run's report
(``verified`` / ``mismatch``); without a real run the state is ``not_verified``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - fixed argv, shell=False, only for the optional gh runner
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_RELATIVE = "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
DOCUMENT_RELATIVE = "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
REGISTRY_RELATIVE = "docs/nerva2/CONTRACT_REGISTRY.json"

EXPECTED_EPICS = {
    "E0": 758, "E1": 759, "E2": 760, "E3": 761, "E4": 762, "E5": 763, "E6": 764,
    "E7": 765, "E8": 766, "E9": 767, "E10": 768, "E11": 769, "E12": 773,
}
PROGRAM_STATES = frozenset({"not_started", "discovery", "building", "verifying", "blocked", "done"})
ACTIVE_STATES = frozenset({"discovery", "building", "verifying"})
ELIGIBILITY = frozenset({"blocked", "eligible", "in_progress", "satisfied"})
GATE_STATES = frozenset({"satisfied", "unsatisfied"})
BLOCKER_KINDS = frozenset({"delivery_gate", "program_gate", "owner_live", "external_dependency"})
REFERENCE_KINDS = frozenset({"issue", "repo_path"})
ENFORCEMENT_STATES = frozenset({"required", "safety_disabled"})
CONTRACT_STATES = frozenset({"proposed", "candidate", "evolves_existing", "accepted"})
DRIFT_STATES = frozenset({"open", "resolved"})
BOOTSTRAP_CONTROL_ISSUE = 846
MAX_REASON_BYTES = 512

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")

LIVE_NOT_VERIFIED = "not_verified"
LIVE_VERIFIED = "verified"
LIVE_MISMATCH = "mismatch"

GhRunner = Callable[[Sequence[str]], tuple[int, str]]


@dataclass
class Report:
    """Outcome of one checker run.  ``live_issue_state`` is never ``verified`` unless
    a real ``gh`` runner answered every query consistently."""

    manifest_path: str
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest_sha256: str = ""
    document_matches: bool = False
    live_issue_state: str = LIVE_NOT_VERIFIED
    live_issue_details: list[str] = field(default_factory=list)
    registry_paths_checked: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


# ── helpers ──────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _safe_relative(path: Any) -> bool:
    if not isinstance(path, str) or not path or path != path.strip():
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute() or "\\" in path or "*" in path or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in pure.parts)


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        errors.append(f"{label}: unreadable JSON ({exc.__class__.__name__})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{label}: top level must be an object")
        return None
    return data


def _derive_eligibility(status: str, open_cause: bool, rules: dict[str, Any]) -> str | None:
    active = set(rules.get("active_program_statuses", ACTIVE_STATES))
    if status in active:
        return rules.get("active_result", "in_progress")
    if status == "not_started":
        return rules.get("not_started_open_cause_result", "blocked") if open_cause else rules.get(
            "not_started_clear_result", "eligible")
    if status == "blocked":
        return rules.get("blocked_result", "blocked") if open_cause else None
    if status == "done":
        return None if open_cause else rules.get("done_clear_result", "satisfied")
    return None


# ── section checks ───────────────────────────────────────────────────────────

def _check_snapshot(data: dict[str, Any], errors: list[str]) -> None:
    snap = data.get("evidence_snapshot")
    if not isinstance(snap, dict):
        errors.append("evidence_snapshot must be an object")
        return
    if not isinstance(snap.get("repository"), str) or "/" not in snap.get("repository", ""):
        errors.append("evidence_snapshot.repository must be owner/name")
    if not (isinstance(snap.get("baseline_commit"), str) and HEX40.match(snap["baseline_commit"])):
        errors.append("evidence_snapshot.baseline_commit must be a 40-hex commit")
    if not (isinstance(snap.get("observed_at_utc"), str) and UTC_TIMESTAMP.match(snap["observed_at_utc"])):
        errors.append("evidence_snapshot.observed_at_utc must be a Z-suffixed UTC timestamp")
    for key in ("program_issue", "blocker_plan_issue", "control_issue"):
        if not _is_int(snap.get(key)):
            errors.append(f"evidence_snapshot.{key} must be a positive issue number")
    if snap.get("live_issue_state_verified_by_checker") is not False:
        errors.append(
            "evidence_snapshot.live_issue_state_verified_by_checker must remain false in the file; "
            "only a real gh run reports 'verified' in its own report"
        )


def _check_authority(data: dict[str, Any], errors: list[str]) -> None:
    auth = data.get("authority")
    if not isinstance(auth, dict):
        errors.append("authority must be an object")
        return
    expected = {
        "status_is_evidence_label_only": True,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
        "ultron_remains_sole_action_authority": True,
    }
    for key, value in expected.items():
        if auth.get(key) is not value:
            errors.append(f"authority.{key} must be {str(value).lower()}")


def _check_movement_gate(data: dict[str, Any], root: Path, report: Report) -> None:
    errors = report.errors
    gate = data.get("movement_gate")
    if not isinstance(gate, dict):
        errors.append("movement_gate must be an object")
        return
    state = gate.get("enforcement_state")
    if state not in ENFORCEMENT_STATES:
        errors.append("movement_gate.enforcement_state must be required or safety_disabled")
    rollback = gate.get("rollback")
    if state == "required" and rollback is not None:
        errors.append("movement_gate.rollback must be null while enforcement is required")
    if state == "safety_disabled":
        _check_rollback(rollback, gate, errors)

    bootstrap = gate.get("bootstrap")
    if not isinstance(bootstrap, dict):
        errors.append("movement_gate.bootstrap must be an object")
    else:
        for key in ("source_sha", "accepted_base_sha"):
            if not (isinstance(bootstrap.get(key), str) and HEX40.match(bootstrap[key])):
                errors.append(f"movement_gate.bootstrap.{key} must be a 40-hex commit")
        for key in ("legacy_manifest_sha256", "legacy_manifest_view_sha256", "registry_seed_sha256"):
            if not (isinstance(bootstrap.get(key), str) and HEX64.match(bootstrap[key])):
                errors.append(f"movement_gate.bootstrap.{key} must be a 64-hex digest")

    registry = gate.get("registry")
    retired = gate.get("registry_retired", [])
    if not isinstance(registry, list) or not registry:
        errors.append("movement_gate.registry must be a non-empty list")
        registry = []
    if not isinstance(retired, list):
        errors.append("movement_gate.registry_retired must be a list")
        retired = []
    if registry != sorted(set(registry)):
        errors.append("movement_gate.registry must be sorted and unique")
    for entry in registry:
        if not _safe_relative(entry):
            errors.append(f"movement_gate.registry has an unsafe path: {entry!r}")
            continue
        report.registry_paths_checked += 1
        if not (root / entry).is_file():
            errors.append(f"dead_registry_path:{entry}")
    retired_paths: set[str] = set()
    for item in retired:
        if not isinstance(item, dict) or not _safe_relative(item.get("path")):
            errors.append("movement_gate.registry_retired entries need a safe 'path'")
            continue
        path = item["path"]
        retired_paths.add(path)
        if not (isinstance(item.get("retired_in_commit"), str) and HEX40.match(item["retired_in_commit"])):
            errors.append(f"registry_retired[{path}].retired_in_commit must be a 40-hex commit")
        if not _is_int(item.get("pull_request")):
            errors.append(f"registry_retired[{path}].pull_request must be a positive number")
        if path in registry:
            errors.append(f"registry_retired path is still in registry: {path}")
        if (root / path).exists():
            errors.append(f"retired_path_present:{path} (restore it into movement_gate.registry)")
    for entry in (MANIFEST_RELATIVE, DOCUMENT_RELATIVE, "scripts/check_nerva_program_manifest.py"):
        if entry not in registry:
            errors.append(f"movement_gate.registry must include {entry}")

    manual = gate.get("manual_integration")
    if not isinstance(manual, dict):
        errors.append("movement_gate.manual_integration must be an object")
    else:
        for key in ("workflow_path", "policy_test_path"):
            path = manual.get(key)
            if not _safe_relative(path) or not (root / path).is_file():
                errors.append(f"movement_gate.manual_integration.{key} must name an existing file")
        if not _is_int(manual.get("issue")):
            errors.append("movement_gate.manual_integration.issue must be a positive number")
    issues = gate.get("program_control_issues")
    if not isinstance(issues, list) or not issues or issues[0] != BOOTSTRAP_CONTROL_ISSUE:
        errors.append(f"movement_gate.program_control_issues must start with #{BOOTSTRAP_CONTROL_ISSUE}")
    elif any(not _is_int(i) for i in issues):
        errors.append("movement_gate.program_control_issues must be positive numbers")
    receipt = gate.get("receipt_control")
    if not isinstance(receipt, dict) or receipt.get("continuous_currentness") is not False:
        errors.append("movement_gate.receipt_control.continuous_currentness must be false")


def _check_rollback(rollback: Any, gate: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(rollback, dict):
        errors.append("movement_gate.rollback must be an object while enforcement is safety_disabled")
        return
    if rollback.get("rollback_of_issue") != BOOTSTRAP_CONTROL_ISSUE:
        errors.append(f"movement_gate.rollback.rollback_of_issue must be #{BOOTSTRAP_CONTROL_ISSUE}")
    if not (_is_int(rollback.get("pull_request")) or _is_int(rollback.get("issue"))):
        errors.append("movement_gate.rollback must bind a pull_request or issue number")
    if not (isinstance(rollback.get("commit"), str) and HEX40.match(rollback["commit"])):
        errors.append("movement_gate.rollback.commit must be a 40-hex commit")
    reason = rollback.get("reason")
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason.encode("utf-8")) > MAX_REASON_BYTES
        or not reason.isprintable()
    ):
        errors.append("movement_gate.rollback.reason must be bounded printable text")
    for key in ("fresh_owner_receipts_required", "exact_head_checks_required"):
        if rollback.get(key) is not True:
            errors.append(f"movement_gate.rollback.{key} must remain true")
    pulls = gate.get("program_control_pull_requests", [])
    if _is_int(rollback.get("pull_request")) and rollback["pull_request"] not in pulls:
        errors.append("movement_gate.rollback.pull_request must be listed in program_control_pull_requests")


def _check_evidence(item: Any, root: Path, label: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{label}: evidence must be an object")
        return
    if not (isinstance(item.get("commit"), str) and HEX40.match(item["commit"])):
        errors.append(f"{label}: evidence.commit must be a 40-hex commit")
    path = item.get("repo_path")
    if not _safe_relative(path) or not (root / path).is_file():
        errors.append(f"{label}: evidence.repo_path must name an existing file")
    for key in ("issue", "pull_request"):
        if not _is_int(item.get(key)):
            errors.append(f"{label}: evidence.{key} must be a positive number")
    if not (isinstance(item.get("claim_code"), str) and IDENTIFIER.match(item["claim_code"])):
        errors.append(f"{label}: evidence.claim_code must be an identifier")


def _check_streams(data: dict[str, Any], registry: dict[str, Any] | None, root: Path, errors: list[str]) -> None:
    streams = data.get("streams")
    if not isinstance(streams, list):
        errors.append("streams must be a list")
        return
    ids = [s.get("id") if isinstance(s, dict) else None for s in streams]
    if ids != list(EXPECTED_EPICS):
        errors.append(f"streams must be exactly {list(EXPECTED_EPICS)} in order")
        return
    rules = data.get("invariants", {}).get("delivery_eligibility_derivation", {}) if isinstance(
        data.get("invariants"), dict) else {}
    deps = registry.get("delivery_dependencies", {}) if registry else {}
    for stream in streams:
        sid = stream["id"]
        label = f"streams[{sid}]"
        if stream.get("epic_issue") != EXPECTED_EPICS[sid]:
            errors.append(f"{label}.epic_issue must be #{EXPECTED_EPICS[sid]}")
        status = stream.get("program_status")
        if status not in PROGRAM_STATES:
            errors.append(f"{label}.program_status must be one of {sorted(PROGRAM_STATES)}")
            continue
        prereqs = stream.get("delivery_prerequisites")
        blockers = stream.get("blockers")
        if not isinstance(prereqs, list) or not isinstance(blockers, list):
            errors.append(f"{label}: delivery_prerequisites and blockers must be lists")
            continue
        sources = [p.get("source") for p in prereqs if isinstance(p, dict)]
        if registry is not None and sid in deps and sorted(sources) != sorted(deps[sid]):
            errors.append(f"{label}.delivery_prerequisites {sorted(sources)} != registry {sorted(deps[sid])}")
        unsatisfied: set[str] = set()
        for prereq in prereqs:
            if not isinstance(prereq, dict) or prereq.get("gate_state") not in GATE_STATES:
                errors.append(f"{label}: prerequisite gate_state must be satisfied or unsatisfied")
                continue
            evidence = prereq.get("accepted_evidence", [])
            if prereq["gate_state"] == "satisfied":
                if not evidence:
                    errors.append(f"{label}: satisfied gate {prereq.get('source')} needs accepted_evidence")
                for item in evidence:
                    _check_evidence(item, root, f"{label}.gate[{prereq.get('source')}]", errors)
            else:
                unsatisfied.add(prereq.get("source"))
                if evidence:
                    errors.append(f"{label}: unsatisfied gate {prereq.get('source')} must carry no evidence")
        delivery_targets: set[str] = set()
        for blocker in blockers:
            if not isinstance(blocker, dict) or blocker.get("kind") not in BLOCKER_KINDS:
                errors.append(f"{label}: blocker kind must be one of {sorted(BLOCKER_KINDS)}")
                continue
            bid = blocker.get("id")
            if not (isinstance(bid, str) and bid.startswith(f"{sid}-")):
                errors.append(f"{label}: blocker id must start with '{sid}-'")
            if not _is_int(blocker.get("issue")):
                errors.append(f"{label}: blocker {bid} issue must be a positive number")
            artifact = blocker.get("artifact")
            if not _safe_relative(artifact) or not (root / artifact).is_file():
                errors.append(f"{label}: blocker {bid} artifact must name an existing file")
            if not (isinstance(blocker.get("reason_code"), str) and IDENTIFIER.match(blocker["reason_code"])):
                errors.append(f"{label}: blocker {bid} reason_code must be an identifier")
            if "note" in blocker and not (isinstance(blocker["note"], str) and blocker["note"].strip()):
                errors.append(f"{label}: blocker {bid} note must be non-empty text when present")
            if blocker["kind"] == "delivery_gate":
                target = blocker.get("target")
                delivery_targets.add(target)
                if target in EXPECTED_EPICS and blocker.get("issue") != EXPECTED_EPICS[target]:
                    errors.append(f"{label}: delivery blocker {bid} issue must be #{EXPECTED_EPICS.get(target)}")
        if delivery_targets != unsatisfied:
            errors.append(
                f"{label}: delivery_gate blockers {sorted(delivery_targets, key=str)} must equal "
                f"unsatisfied gates {sorted(unsatisfied, key=str)}"
            )
        open_cause = bool(unsatisfied) or bool(blockers)
        derived = _derive_eligibility(status, open_cause, rules)
        if derived is None:
            errors.append(f"{label}: program_status {status} with open_cause={open_cause} is invalid")
        elif stream.get("delivery_eligibility") != derived:
            errors.append(f"{label}.delivery_eligibility must derive to {derived}")
        if status == "done" and not stream.get("completion_evidence"):
            errors.append(f"{label}: done stream needs completion_evidence")
        for item in stream.get("completion_evidence", []):
            _check_evidence(item, root, f"{label}.completion", errors)
        for ref in stream.get("references", []):
            if not isinstance(ref, dict) or ref.get("kind") not in REFERENCE_KINDS:
                errors.append(f"{label}: reference kind must be issue or repo_path")
            elif ref["kind"] == "issue" and not _is_int(ref.get("value")):
                errors.append(f"{label}: issue reference must be a positive number")
            elif ref["kind"] == "repo_path" and (
                not _safe_relative(ref.get("value")) or not (root / ref["value"]).is_file()
            ):
                errors.append(f"{label}: dead_reference_path:{ref.get('value')}")


def _check_feedback_edges(data: dict[str, Any], registry: dict[str, Any] | None, errors: list[str]) -> None:
    edges = data.get("runtime_feedback_edges")
    if not isinstance(edges, list):
        errors.append("runtime_feedback_edges must be a list")
        return
    manifest_edges: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("grants_authority") is not False:
            errors.append("every runtime_feedback_edge must carry grants_authority=false")
            continue
        manifest_edges.add((edge.get("source"), edge.get("consumer")))
    drifts = data.get("known_source_drifts", [])
    drift_edges = {
        (d.get("edge", {}).get("source"), d.get("edge", {}).get("consumer"))
        for d in drifts if isinstance(d, dict) and d.get("state") == "open"
    }
    for drift in drifts:
        if not isinstance(drift, dict) or drift.get("state") not in DRIFT_STATES:
            errors.append("known_source_drifts entries need state open or resolved")
    if registry is None:
        return
    registry_edges = {tuple(e) for e in registry.get("runtime_feedback_edges", []) if len(e) == 2}
    for edge in registry_edges - manifest_edges:
        errors.append(f"registry runtime edge {edge} missing from manifest")
    for edge in manifest_edges - registry_edges:
        if edge not in drift_edges:
            errors.append(f"manifest runtime edge {edge} absent from registry without an open drift record")


def _check_contracts(data: dict[str, Any], registry: dict[str, Any] | None, registry_bytes: bytes | None,
                     root: Path, errors: list[str]) -> None:
    view = data.get("contract_registry")
    if not isinstance(view, dict):
        errors.append("contract_registry must be an object mirroring CONTRACT_REGISTRY.json")
        return
    if view.get("path") != REGISTRY_RELATIVE:
        errors.append(f"contract_registry.path must be {REGISTRY_RELATIVE}")
    if registry is None or registry_bytes is None:
        return
    if view.get("sha256") != _sha256(registry_bytes):
        errors.append("contract_registry.sha256 does not match CONTRACT_REGISTRY.json bytes")
    statuses = view.get("statuses")
    if not isinstance(statuses, dict):
        errors.append("contract_registry.statuses must be an object")
        return
    registry_statuses: dict[str, str] = {}
    for contract in registry.get("contracts", []):
        cid = contract.get("id")
        status = contract.get("status")
        registry_statuses[cid] = status
        if status not in CONTRACT_STATES:
            errors.append(f"contract {cid}: status must be one of {sorted(CONTRACT_STATES)}")
        paths = contract.get("evidence_paths", [])
        if not paths:
            errors.append(f"contract {cid}: needs at least one evidence path")
        for path in paths:
            if not _safe_relative(path) or not (root / path).is_file():
                errors.append(f"dead_contract_evidence_path:{cid}:{path}")
    if statuses != registry_statuses:
        errors.append(f"contract_registry.statuses {statuses} != registry {registry_statuses}")


def _check_reconciliation_log(data: dict[str, Any], root: Path, errors: list[str]) -> None:
    log = data.get("reconciliation_log", [])
    if not isinstance(log, list):
        errors.append("reconciliation_log must be a list")
        return
    seen: set[str] = set()
    for entry in log:
        if not isinstance(entry, dict):
            errors.append("reconciliation_log entries must be objects")
            continue
        eid = entry.get("id")
        if not (isinstance(eid, str) and IDENTIFIER.match(eid)) or eid in seen:
            errors.append(f"reconciliation_log id invalid or duplicated: {eid!r}")
        seen.add(str(eid))
        if not (isinstance(entry.get("date"), str) and ISO_DATE.match(entry["date"])):
            errors.append(f"reconciliation_log[{eid}].date must be YYYY-MM-DD")
        for key in ("decision", "effect"):
            if not (isinstance(entry.get(key), str) and entry[key].strip()):
                errors.append(f"reconciliation_log[{eid}].{key} must be non-empty text")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"reconciliation_log[{eid}].evidence must be a non-empty list")
            continue
        for item in evidence:
            if isinstance(item, str) and item.startswith(("docs/", "scripts/", "tests/", ".github/")):
                bare = item.split(":", 1)[0]
                if not (root / bare).is_file():
                    errors.append(f"reconciliation_log[{eid}]: dead evidence path {bare}")


# ── live issue verification ──────────────────────────────────────────────────

def _expected_issue_states(data: dict[str, Any]) -> dict[int, str | None]:
    """Issue → expected GitHub state (``OPEN``/``CLOSED``) or ``None`` for exist-only."""

    expected: dict[int, str | None] = {}
    snap = data.get("evidence_snapshot", {})
    for key in ("program_issue", "blocker_plan_issue", "control_issue"):
        if _is_int(snap.get(key)):
            expected.setdefault(snap[key], None)
    for stream in data.get("streams", []):
        if isinstance(stream, dict) and _is_int(stream.get("epic_issue")):
            expected[stream["epic_issue"]] = "CLOSED" if stream.get("program_status") == "done" else "OPEN"
        for ref in stream.get("references", []) if isinstance(stream, dict) else []:
            if isinstance(ref, dict) and ref.get("kind") == "issue" and _is_int(ref.get("value")):
                expected.setdefault(ref["value"], None)
    return expected


def verify_live_issues(data: dict[str, Any], gh: GhRunner, report: Report) -> None:
    """Query ``gh issue view`` for every referenced issue.  Sets ``report.live_issue_state``
    to ``verified`` only when every query succeeded and matched; any runner failure
    leaves it ``not_verified`` (never a silent pass)."""

    repository = data.get("evidence_snapshot", {}).get("repository")
    if not isinstance(repository, str):
        report.warnings.append("live: repository unknown; not verified")
        return
    mismatches: list[str] = []
    unavailable = False
    for number, want in sorted(_expected_issue_states(data).items()):
        argv = ["issue", "view", str(number), "--repo", repository, "--json", "number,state,title"]
        try:
            code, out = gh(argv)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            report.warnings.append(f"live: gh failed for #{number}: {exc.__class__.__name__}")
            unavailable = True
            break
        if code != 0:
            report.warnings.append(f"live: gh exit {code} for #{number}")
            unavailable = True
            break
        try:
            payload = json.loads(out)
        except ValueError:
            report.warnings.append(f"live: gh returned non-JSON for #{number}")
            unavailable = True
            break
        if not isinstance(payload, dict) or payload.get("number") != number:
            mismatches.append(f"#{number}: gh returned a different issue")
            continue
        state = str(payload.get("state", "")).upper()
        report.live_issue_details.append(f"#{number}: {state} (expected {want or 'any'})")
        if want is not None and state != want:
            mismatches.append(f"#{number}: live {state}, manifest expects {want}")
    if unavailable:
        report.live_issue_state = LIVE_NOT_VERIFIED
        return
    if mismatches:
        report.live_issue_state = LIVE_MISMATCH
        report.errors.extend(f"live_issue_mismatch:{m}" for m in mismatches)
        return
    report.live_issue_state = LIVE_VERIFIED


def gh_cli_runner(timeout: float = 20.0) -> GhRunner | None:
    """Real ``gh`` runner (argv list, ``shell=False``) or ``None`` when the CLI is absent."""

    executable = shutil.which("gh")
    if executable is None:
        return None

    def _run(argv: Sequence[str]) -> tuple[int, str]:
        completed = subprocess.run(  # nosec B603 - fixed executable, argv list, no shell
            [executable, *argv], check=False, capture_output=True, text=True, timeout=timeout,
        )
        return completed.returncode, completed.stdout

    return _run


# ── markdown view ────────────────────────────────────────────────────────────

def _issue_link(repo: str, number: int) -> str:
    return f"[#{number}](https://github.com/{repo}/issues/{number})"


def _pr_link(repo: str, number: int) -> str:
    return f"[#{number}](https://github.com/{repo}/pull/{number})"


def _evidence_cell(repo: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return "—"
    cells = []
    for item in items:
        commit = item["commit"]
        cells.append(
            f"[`{commit}`](https://github.com/{repo}/commit/{commit}) (immutable commit) · "
            f"{_issue_link(repo, item['issue'])} (mutable context) · "
            f"{_pr_link(repo, item['pull_request'])} (mutable context) · "
            f"[`{item['repo_path']}` at `{commit[:12]}`](https://github.com/{repo}/blob/{commit}/"
            f"{item['repo_path']}) (immutable blob locator) · `{item['claim_code']}`"
        )
    return " ; ".join(cells)


def render_markdown(data: dict[str, Any]) -> str:
    """Deterministic Markdown view of the JSON manifest (JSON stays the truth)."""

    snap = data["evidence_snapshot"]
    repo = snap["repository"]
    gate = data["movement_gate"]
    out: list[str] = [
        "# Nerva program manifest v1",
        "",
        "> Offline repository evidence snapshot rendered by `scripts/check_nerva_program_manifest.py`. "
        "This document does not query live GitHub, does not authorize execution, does not declare "
        "program completion, and does not establish release readiness.",
        "",
        "- The JSON manifest is the sole current dependency/status/gate/blocker/runtime truth; this view is regenerated with `--write` and byte-checked on every checker run.",
        f"- Evidence baseline: `{snap['baseline_commit']}`",
        f"- Observed at (mutable snapshot context): `{snap['observed_at_utc']}`",
        f"- Program issue: {_issue_link(repo, snap['program_issue'])}",
        f"- Blocker plan: {_issue_link(repo, snap['blocker_plan_issue'])}",
        f"- Manifest control: {_issue_link(repo, snap['control_issue'])}",
        f"- Live issue state verified by this file: `{str(snap['live_issue_state_verified_by_checker']).lower()}` "
        "(a `--live` checker run reports `verified` / `mismatch` / `not_verified` in its own report only)",
        "",
        "## Issue movement gate",
        "",
        f"- Schema version: `{gate['schema_version']}`",
        f"- Enforcement state: `{gate['enforcement_state']}`",
        f"- Historical bootstrap source: `{gate['bootstrap']['source_sha']}`",
        f"- Accepted implementation base: `{gate['bootstrap']['accepted_base_sha']}`",
        f"- Program-control issues: {', '.join(_issue_link(repo, i) for i in gate['program_control_issues'])}",
    ]
    pulls = gate.get("program_control_pull_requests", [])
    if pulls:
        out.append(f"- Program-control pull requests: {', '.join(_pr_link(repo, p) for p in pulls)}")
    rollback = gate.get("rollback")
    if rollback:
        binding = _pr_link(repo, rollback["pull_request"]) if rollback.get("pull_request") else _issue_link(
            repo, rollback["issue"])
        out.append(
            f"- Rollback record: forward safety movement of #{rollback['rollback_of_issue']} bound to {binding} "
            f"(`{rollback['commit']}`) — {rollback['reason']}"
        )
    out += [
        f"- Receipt proof mode: `{gate['receipt_control']['mode']}`; continuous currentness: "
        f"`{str(gate['receipt_control']['continuous_currentness']).lower()}`",
        f"- Manual-integration guard: {_issue_link(repo, gate['manual_integration']['issue'])} pins "
        f"`{gate['manual_integration']['workflow_path']}` and `{gate['manual_integration']['policy_test_path']}`.",
        "- This gate has no GitHub-write, runtime, completion, or release authority.",
        "",
        "### Registry (every path must exist)",
        "",
    ]
    out += [f"- `{p}`" for p in gate["registry"]]
    retired = gate.get("registry_retired", [])
    if retired:
        out += ["", "### Retired registry paths (must stay absent)", "", "| Path | Retired in | Pull request |", "|---|---|---:|"]
        out += [
            f"| `{r['path']}` | `{r['retired_in_commit'][:12]}` | {_pr_link(repo, r['pull_request'])} |"
            for r in retired
        ]
    out += [
        "",
        "## Program status and derived delivery eligibility",
        "",
        "| Stream | Epic | Program status | Delivery eligibility | Completion evidence |",
        "|---|---:|---|---|---|",
    ]
    for s in data["streams"]:
        out.append(
            f"| {s['id']} — {s['name']} | {_issue_link(repo, s['epic_issue'])} | `{s['program_status']}` | "
            f"`{s['delivery_eligibility']}` | {_evidence_cell(repo, s.get('completion_evidence', []))} |"
        )
    out += [
        "",
        "Program status describes the reviewed work snapshot. Delivery eligibility is derived independently: "
        "active discovery/build/verification remains `in_progress`; a consumer-specific gate may be satisfied "
        "while its source epic is still building.",
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
    for s in data["streams"]:
        for p in s["delivery_prerequisites"]:
            out.append(
                f"| {s['id']} | {p['source']} | `{p['gate_state']}` | "
                f"{_evidence_cell(repo, p.get('accepted_evidence', []))} |"
            )
    out += [
        "",
        "A satisfied delivery edge requires an accepted 40-hex commit, an artifact present at that commit, "
        "and mutable issue/PR context. An upstream epic's overall status is never substituted for "
        "consumer-specific gate acceptance.",
        "",
        "## Typed blockers",
        "",
        "| Stream | Kind | Target | Evidence context | Reason code | Note |",
        "|---|---|---|---|---|---|",
    ]
    for s in data["streams"]:
        for b in sorted(s["blockers"], key=lambda item: item["id"]):
            out.append(
                f"| {s['id']} | `{b['kind']}` | `{b['target']}` | {_issue_link(repo, b['issue'])} · "
                f"[`{b['artifact']}`](../../{b['artifact']}) | `{b['reason_code']}` | {b.get('note', '—')} |"
            )
    out += [
        "",
        "## Runtime feedback — advisory only",
        "",
        "| Source | Consumer | Mode | Grants authority |",
        "|---|---|---|---|",
    ]
    for e in sorted(data["runtime_feedback_edges"], key=lambda item: (item["source"], item["consumer"])):
        out.append(f"| {e['source']} | {e['consumer']} | `{e['mode']}` | `{str(e['grants_authority']).lower()}` |")
    out += ["", "## Contract registry mirror", "", f"- Source: `{data['contract_registry']['path']}` (SHA-256 `{data['contract_registry']['sha256']}`)", "", "| Contract | Status |", "|---|---|"]
    out += [f"| `{cid}` | `{status}` |" for cid, status in data["contract_registry"]["statuses"].items()]
    out += ["", "## Known source drift", ""]
    for d in data.get("known_source_drifts", []):
        out.append(
            f"- `{d['id']}` is `{d['state']}`: `{d['edge']['source']} -> {d['edge']['consumer']}` appears in "
            f"[`{d['present_in']}`](../../{d['present_in']}) but is absent from [`{d['missing_from']}`](../../{d['missing_from']}); "
            f"reason `{d['reason_code']}`."
        )
    log = data.get("reconciliation_log", [])
    if log:
        out += ["", "## Reconciliation log", "", "| Date | Id | Decision | Effect | Evidence |", "|---|---|---|---|---|"]
        for entry in log:
            out.append(
                f"| {entry['date']} | `{entry['id']}` | {entry['decision']} | {entry['effect']} | "
                f"{' · '.join(f'`{e}`' for e in entry['evidence'])} |"
            )
    out += [
        "",
        "## Authority and integrity boundary",
        "",
        "- This snapshot is evidence-only and cannot authorize or execute actions.",
        "- Ultron remains the sole privileged-action authority.",
        "- Runtime feedback is advisory and never becomes delivery or action authority.",
        "- `done` and `satisfied` are repository-evidence labels, not owner-live or release proof.",
        "- Release readiness remains `false`; typed owner-live, program, and external blockers remain visible above when present.",
        "",
    ]
    return "\n".join(out)


# ── entry points ─────────────────────────────────────────────────────────────

def check_manifest(path: str | Path | None = None, gh: GhRunner | None = None,
                   repo_root: str | Path | None = None) -> Report:
    """Validate the manifest at ``path`` against the repository at ``repo_root``.

    ``gh`` is an optional ``argv -> (exit_code, stdout)`` runner for live issue
    verification.  With ``gh=None`` the report's ``live_issue_state`` stays
    ``not_verified``; it becomes ``verified`` only from a real, fully consistent run.
    """

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    manifest_path = Path(path) if path is not None else root / MANIFEST_RELATIVE
    report = Report(manifest_path=str(manifest_path))
    errors = report.errors
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        errors.append(f"manifest unreadable: {exc.__class__.__name__}")
        return report
    report.manifest_sha256 = _sha256(raw)
    data = _load_json(manifest_path, errors, "manifest")
    if data is None:
        return report
    if data.get("schema_version") != 1 or data.get("manifest_id") != "nerva.program-manifest.v1":
        errors.append("manifest schema_version must be 1 with manifest_id nerva.program-manifest.v1")

    registry_path = root / REGISTRY_RELATIVE
    registry_bytes: bytes | None = None
    registry: dict[str, Any] | None = None
    if registry_path.is_file():
        registry_bytes = registry_path.read_bytes()
        registry = _load_json(registry_path, errors, "contract registry")
    else:
        errors.append(f"missing {REGISTRY_RELATIVE}")

    _check_snapshot(data, errors)
    _check_authority(data, errors)
    _check_movement_gate(data, root, report)
    _check_streams(data, registry, root, errors)
    _check_feedback_edges(data, registry, errors)
    _check_contracts(data, registry, registry_bytes, root, errors)
    _check_reconciliation_log(data, root, errors)

    document_path = root / DOCUMENT_RELATIVE
    if not errors:
        try:
            expected = render_markdown(data).encode("utf-8")
            current = document_path.read_bytes() if document_path.is_file() else b""
            report.document_matches = current == expected
            if not report.document_matches:
                errors.append(f"document_stale:{DOCUMENT_RELATIVE} (regenerate with --write)")
        except (KeyError, TypeError) as exc:
            errors.append(f"document render failed: {exc.__class__.__name__}: {exc}")

    if gh is not None:
        verify_live_issues(data, gh, report)
    report.ok = not errors
    return report


def _scalar_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(not isinstance(v, (dict, list)) for v in value.values())


def format_manifest_json(obj: Any, indent: int = 0) -> str:
    """Canonical, diff-friendly JSON: scalar lists and short scalar objects stay inline."""

    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        if _scalar_dict(obj) and indent >= 2:
            inline = "{" + ", ".join(
                f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}" for k, v in obj.items()
            ) + "}"
            if len(inline) <= 220:
                return inline
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: {format_manifest_json(v, indent + 1)}"
                 for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        if all(not isinstance(x, (dict, list)) for x in obj):
            return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in obj) + "]"
        return "[\n" + ",\n".join(f"{pad}  " + format_manifest_json(x, indent + 1) for x in obj) + f"\n{pad}]"
    return json.dumps(obj, ensure_ascii=False)


def write_document(path: str | Path | None = None, repo_root: str | Path | None = None) -> Path:
    """Refresh the contract-registry mirror, canonicalise the JSON and render the Markdown view.

    The manifest JSON is rewritten only when its bytes would change; ``live_issue_state_verified_by_checker``
    is never touched.
    """

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    manifest_path = Path(path) if path is not None else root / MANIFEST_RELATIVE
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry_path = root / REGISTRY_RELATIVE
    if registry_path.is_file():
        registry_bytes = registry_path.read_bytes()
        try:
            registry = json.loads(registry_bytes)
        except ValueError:
            registry = None
        if isinstance(registry, dict) and isinstance(registry.get("contracts"), list):
            data["contract_registry"] = {
                "path": REGISTRY_RELATIVE,
                "sha256": _sha256(registry_bytes),
                "statuses": {c.get("id"): c.get("status") for c in registry["contracts"] if isinstance(c, dict)},
            }
    canonical = (format_manifest_json(data) + "\n").encode("utf-8")
    if manifest_path.read_bytes() != canonical:
        manifest_path.write_bytes(canonical)
    document_path = root / DOCUMENT_RELATIVE
    document_path.write_bytes(render_markdown(data).encode("utf-8"))
    return document_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=None, help=f"manifest path (default {MANIFEST_RELATIVE})")
    parser.add_argument("--repo-root", default=None, help="repository root (default: this checkout)")
    parser.add_argument("--write", action="store_true",
                        help="canonicalise the JSON, refresh the contract-registry mirror and regenerate the Markdown view")
    parser.add_argument("--live", action="store_true",
                        help="verify referenced issues through `gh issue view` (advisory; requires gh)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    if args.write:
        written = write_document(args.manifest, args.repo_root)
        print(f"wrote {written}")

    gh: GhRunner | None = None
    if args.live:
        gh = gh_cli_runner()
    report = check_manifest(args.manifest, gh=gh, repo_root=args.repo_root)
    if args.live and gh is None:
        report.warnings.append("live: dependency_unavailable:gh — issue state not verified")

    if args.json:
        sys.stdout.write(report.to_json())
    else:
        status = "OK" if report.ok else "FAIL"
        print(f"nerva program manifest: {status} ({report.registry_paths_checked} registry paths, "
              f"live issue state: {report.live_issue_state})")
        for line in report.errors:
            print(f"  error: {line}")
        for line in report.warnings:
            print(f"  warning: {line}")
        for line in report.live_issue_details:
            print(f"  live: {line}")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
