"""Hostile, count-neutral checks for the fail-closed Innovation Lab control.

The repository runs this file directly so strengthening the control plane does
not manufacture a collected-pytest count change.  The matrix exercises the
real standard-library validator, including its closed schema profile and Git
reference boundary.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
SCHEMA_PATH = REPO / "docs/nerva2/INNOVATION_LAB_V1.schema.json"
GARDEN_PATH = REPO / "docs/nerva2/KNOWLEDGE_GARDEN_V1.json"


def _load_checker():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from check_nerva_innovation_lab import (  # noqa: PLC0415
        SCHEMA_SHA256,
        compare_append_only,
        decode_json_bytes,
        evaluate_schema,
        validate_bundle,
        validate_git_refs,
        validate_repository,
        validate_schema_bytes,
        validate_schema_document,
    )

    return {
        "schema_sha256": SCHEMA_SHA256,
        "compare": compare_append_only,
        "decode": decode_json_bytes,
        "evaluate_schema": evaluate_schema,
        "validate_bundle": validate_bundle,
        "validate_git_refs": validate_git_refs,
        "validate_repository": validate_repository,
        "validate_schema_bytes": validate_schema_bytes,
        "validate_schema_document": validate_schema_document,
    }


def _authority() -> dict:
    return {
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


def _valid_bundle() -> dict:
    return {
        "schema_version": "nerva.innovation-lab.v1",
        "program_issue": 805,
        "authority_ceiling": _authority(),
        "catalogues": [],
        "records": [
            {
                "id": "OBS-0001",
                "kind": "OBSERVATION",
                "summary": "The bounded manual process has measurable delay.",
                "source_ref": "repo://docs/nerva2/BASELINE.md",
                "privacy_class": "synthetic_public",
                "retention_class": "repository_history",
                "integrity_sha256": "0" * 64,
                "observed_at": "2026-08-06T00:00:00Z",
            },
            {
                "id": "IDEA-0001",
                "kind": "IDEA",
                "title": "Reduce the manual delay",
                "problem": "The bounded task takes longer than its baseline.",
                "owner_outcome": "Return time without changing authority.",
            },
            {
                "id": "EVID-PRIMARY-0001",
                "kind": "EVIDENCE",
                "evidence_class": "in_repository",
                "claim": "The existing path and limitation were inspected.",
                "source_ref": "repo://docs/nerva2/BASELINE.md",
                "limitations": "Repository evidence is not owner-live evidence.",
                "integrity_sha256": "a" * 64,
                "observed_at": "2026-08-06T00:01:00Z",
            },
            {
                "id": "EVID-BASE-0001",
                "kind": "EVIDENCE",
                "evidence_class": "benchmark",
                "claim": "A retained baseline makes the claim falsifiable.",
                "source_ref": "repo://docs/nerva2/RESEARCH_LAB_E9_0.md",
                "limitations": "Synthetic evidence cannot prove owner value.",
                "integrity_sha256": "b" * 64,
                "observed_at": "2026-08-06T00:01:30Z",
            },
            {
                "id": "RFC-0001-R1",
                "kind": "RFC",
                "stable_id": "RFC-0001",
                "revision": 1,
                "lane": "ALPHA",
                "author_id": "research-builder",
                "authoring_role": "Research Builder",
                "stage": "DECIDED",
                "stage_history": [
                    {"from_stage": None, "to_stage": "DRAFT", "at": "2026-08-06T00:02:00Z"},
                    {
                        "from_stage": "DRAFT",
                        "to_stage": "EVIDENCE_GATHERING",
                        "at": "2026-08-06T00:03:00Z",
                    },
                    {
                        "from_stage": "EVIDENCE_GATHERING",
                        "to_stage": "READY_FOR_REVIEW",
                        "at": "2026-08-06T00:04:00Z",
                    },
                    {
                        "from_stage": "READY_FOR_REVIEW",
                        "to_stage": "DECIDED",
                        "at": "2026-08-06T00:05:00Z",
                    },
                ],
                "title": "Bounded manual-delay experiment",
                "problem": "The bounded task takes longer than its baseline.",
                "owner_outcome": "Return time without changing authority.",
                "hypothesis": "A smaller reusable step reduces elapsed time.",
                "alternatives": ["Keep the baseline", "Simplify the existing step"],
                "reuse_build_reject": {
                    "reuse": "Reuse the current evaluation boundary.",
                    "build": "Build only through a separately reviewed epic.",
                    "reject": "Reject direct production integration from this RFC.",
                },
                "dependencies": ["E9 accepted benchmark evidence"],
                "affected_contracts": ["nerva.benchmark.v1"],
                "assessments": {
                    "authority": {"status": "assessed", "details": "No authority is granted."},
                    "security": {
                        "status": "assessed",
                        "details": "The slice is documentation-only.",
                    },
                    "privacy": {
                        "status": "assessed",
                        "details": "Only synthetic-public fixtures are allowed.",
                        "private_data_policy": "excluded",
                        "policy_ref": None,
                    },
                    "data_retention": {
                        "status": "assessed",
                        "details": "Only repository history remains.",
                    },
                    "license": {
                        "status": "not_applicable",
                        "details": "No external code is copied.",
                    },
                    "supply_chain": {
                        "status": "not_applicable",
                        "details": "No dependency is introduced.",
                    },
                    "compatibility": {
                        "status": "assessed",
                        "details": "The proposal is removable.",
                    },
                },
                "external_code_involved": False,
                "advisory_dimensions": {
                    "impact": 3,
                    "novelty": 2,
                    "difficulty": 2,
                    "risk": 1,
                    "compatibility": 5,
                    "expected_time_saved_hours": 1.0,
                    "probability_of_benefit": 0.7,
                    "innovation_score": 60.0,
                    "advisory_only": True,
                },
                "benchmark": {
                    "baseline_ref": "EVID-BASE-0001",
                    "falsification_plan": "Reject if the retained baseline is not beaten.",
                },
                "prototype_disposition": {
                    "status": "not_required",
                    "reason": "Retained evidence is sufficient for the bounded decision.",
                },
                "outcome_history": [
                    {
                        "from_status": None,
                        "to_status": "pending",
                        "at": "2026-08-06T00:05:00Z",
                        "reason": "The separate epic has not produced an outcome.",
                    }
                ],
                "migration": {"required": False, "plan": "No runtime or stored data changes."},
                "rollback": {"plan": "Revert only the separately scoped epic."},
                "authority": _authority(),
                "reopens_decision_id": None,
            },
            {
                "id": "DEC-0001",
                "kind": "DECISION",
                "status": "ACCEPTED_FOR_EPIC",
                "reviewer_id": "independent-integrator",
                "reviewer_role": "Independent Integrator",
                "basis": "evidence_and_review",
                "rationale": "Evidence supports a separately scoped epic.",
                "reconsideration_trigger": "New negative evidence or a failed outcome.",
                "evidence_refs": ["EVID-PRIMARY-0001", "EVID-BASE-0001"],
                "unresolved_requirements": [],
                "decided_at": "2026-08-06T00:05:00Z",
            },
            {
                "id": "EPIC-0001",
                "kind": "EPIC",
                "repository": "andrei649/jarvis-hub",
                "issue": 900,
                "title": "Separate bounded implementation epic",
                "dependencies": ["E9"],
                "acceptance_criteria": ["Beat the retained baseline without authority drift."],
            },
        ],
        "links": [
            {"from": "OBS-0001", "relation": "MOTIVATES", "to": "IDEA-0001"},
            {"from": "IDEA-0001", "relation": "DEVELOPED_AS", "to": "RFC-0001-R1"},
            {"from": "RFC-0001-R1", "relation": "SUPPORTED_BY", "to": "EVID-PRIMARY-0001"},
            {"from": "RFC-0001-R1", "relation": "SUPPORTED_BY", "to": "EVID-BASE-0001"},
            {"from": "RFC-0001-R1", "relation": "DECIDED_BY", "to": "DEC-0001"},
            {"from": "DEC-0001", "relation": "ACCEPTED_AS", "to": "EPIC-0001"},
        ],
    }


def _parked_bundle() -> dict:
    bundle = _valid_bundle()
    rfc = bundle["records"][4]
    decision = bundle["records"][5]
    decision["status"] = "PARKED"
    decision["unresolved_requirements"] = ["Collect owner-live evidence before reconsideration."]
    rfc["outcome_history"] = [
        {
            "from_status": None,
            "to_status": "not_applicable",
            "at": decision["decided_at"],
            "reason": "A parked RFC cannot create an outcome.",
        }
    ]
    bundle["records"].pop()
    bundle["links"] = [link for link in bundle["links"] if link["relation"] != "ACCEPTED_AS"]
    return bundle


def _rejected_bundle() -> dict:
    bundle = _parked_bundle()
    decision = bundle["records"][5]
    decision["status"] = "REJECTED"
    decision["unresolved_requirements"] = []
    challenge_link = next(
        link
        for link in bundle["links"]
        if link["relation"] == "SUPPORTED_BY" and link["to"] == "EVID-PRIMARY-0001"
    )
    challenge_link["relation"] = "CHALLENGED_BY"
    return bundle


def _ready_bundle() -> dict:
    bundle = _valid_bundle()
    rfc = bundle["records"][4]
    rfc["stage"] = "READY_FOR_REVIEW"
    rfc["stage_history"] = rfc["stage_history"][:3]
    rfc["outcome_history"] = []
    bundle["records"] = bundle["records"][:5]
    bundle["links"] = [
        link for link in bundle["links"] if link["relation"] not in {"DECIDED_BY", "ACCEPTED_AS"}
    ]
    return bundle


def _draft_to_evidence_progression() -> tuple[dict, dict]:
    template = _valid_bundle()
    full_stage_history = copy.deepcopy(template["records"][4]["stage_history"])
    rfc = template["records"][4]
    rfc["stage"] = "DRAFT"
    rfc["stage_history"] = full_stage_history[:1]
    rfc["benchmark"]["baseline_ref"] = None
    rfc["outcome_history"] = []
    baseline = {
        **{key: copy.deepcopy(template[key]) for key in ("schema_version", "program_issue")},
        "authority_ceiling": copy.deepcopy(template["authority_ceiling"]),
        "catalogues": [],
        "records": copy.deepcopy([template["records"][0], template["records"][1], rfc]),
        "links": copy.deepcopy(template["links"][:2]),
    }

    candidate = copy.deepcopy(baseline)
    candidate_rfc = candidate["records"][2]
    candidate_rfc["stage"] = "EVIDENCE_GATHERING"
    candidate_rfc["stage_history"] = full_stage_history[:2]
    candidate_rfc["benchmark"]["baseline_ref"] = "EVID-BASE-0001"
    candidate["records"].extend(copy.deepcopy(template["records"][2:4]))
    candidate["links"].extend(copy.deepcopy(template["links"][2:4]))
    return baseline, candidate


def _evidence_to_ready_assessment_progression() -> tuple[dict, dict]:
    _, baseline = _draft_to_evidence_progression()
    required = ("authority", "security", "privacy", "data_retention", "compatibility")
    baseline_rfc = baseline["records"][2]
    for name in required:
        baseline_rfc["assessments"][name]["status"] = "unknown"
        baseline_rfc["assessments"][name]["details"] = "Assessment is pending."

    candidate = copy.deepcopy(baseline)
    candidate_rfc = candidate["records"][2]
    candidate_rfc["stage"] = "READY_FOR_REVIEW"
    candidate_rfc["stage_history"] = copy.deepcopy(
        _valid_bundle()["records"][4]["stage_history"][:3]
    )
    completed = _valid_bundle()["records"][4]["assessments"]
    for name in required:
        candidate_rfc["assessments"][name] = copy.deepcopy(completed[name])
    return baseline, candidate


def _required_prototype_progression() -> tuple[dict, dict]:
    baseline = _valid_bundle()
    rfc = baseline["records"][4]
    observation, idea = baseline["records"][:2]
    rfc["stage"] = "DRAFT"
    rfc["stage_history"] = rfc["stage_history"][:1]
    rfc["prototype_disposition"]["status"] = "required"
    rfc["outcome_history"] = []
    baseline["records"] = [observation, idea, rfc]
    baseline["links"] = baseline["links"][:2]

    candidate = copy.deepcopy(baseline)
    candidate_rfc = candidate["records"][2]
    candidate_rfc["stage"] = "READY_FOR_REVIEW"
    candidate_rfc["stage_history"] = copy.deepcopy(
        _valid_bundle()["records"][4]["stage_history"][:3]
    )
    candidate["records"].extend(copy.deepcopy(_valid_bundle()["records"][2:4]))
    candidate["records"].append(
        {
            "id": "PROTO-0001",
            "kind": "PROTOTYPE",
            "branch": "nerva-lab/rfc-0001-r1-bounded-test",
            "disposable": True,
            "production_data": False,
            "private_data_policy": "excluded",
            "policy_ref": None,
            "teardown_plan": "Delete the disposable branch and fixtures.",
            "tested_at": "2026-08-06T00:03:30Z",
        }
    )
    candidate["links"].extend(
        [
            {"from": "RFC-0001-R1", "relation": "SUPPORTED_BY", "to": "EVID-PRIMARY-0001"},
            {"from": "RFC-0001-R1", "relation": "SUPPORTED_BY", "to": "EVID-BASE-0001"},
            {"from": "RFC-0001-R1", "relation": "TESTED_BY", "to": "PROTO-0001"},
        ]
    )
    return baseline, candidate


def _reopened_bundle() -> dict:
    bundle = _parked_bundle()
    bundle["records"].append(
        {
            "id": "EVID-NEW-0001",
            "kind": "EVIDENCE",
            "evidence_class": "primary_read",
            "claim": "A later artifact addresses the recorded reconsideration trigger.",
            "source_ref": "repo://docs/nerva2/DEPENDENCIES.md",
            "limitations": "Architecture evidence is not production proof.",
            "integrity_sha256": "c" * 64,
            "observed_at": "2026-08-06T01:00:00Z",
        }
    )
    revision = copy.deepcopy(bundle["records"][4])
    revision.update(
        {
            "id": "RFC-0001-R2",
            "revision": 2,
            "stage": "EVIDENCE_GATHERING",
            "stage_history": [
                {"from_stage": None, "to_stage": "DRAFT", "at": "2026-08-06T01:01:00Z"},
                {
                    "from_stage": "DRAFT",
                    "to_stage": "EVIDENCE_GATHERING",
                    "at": "2026-08-06T01:02:00Z",
                },
            ],
            "benchmark": {
                "baseline_ref": "EVID-NEW-0001",
                "falsification_plan": "Reject if the new artifact does not change the result.",
            },
            "outcome_history": [],
            "reopens_decision_id": "DEC-0001",
        }
    )
    bundle["records"].append(revision)
    bundle["links"].extend(
        [
            {"from": "IDEA-0001", "relation": "DEVELOPED_AS", "to": "RFC-0001-R2"},
            {"from": "RFC-0001-R2", "relation": "SUPPORTED_BY", "to": "EVID-NEW-0001"},
            {"from": "RFC-0001-R2", "relation": "SUPERSEDES", "to": "RFC-0001-R1"},
            {"from": "RFC-0001-R2", "relation": "REOPENS", "to": "DEC-0001"},
        ]
    )
    return bundle


def _decided_reopened_bundle(*, novel_observed_at: str, include_novel_in_decision: bool) -> dict:
    bundle = _reopened_bundle()
    novel_evidence = bundle["records"][6]
    successor = bundle["records"][7]
    novel_evidence["observed_at"] = novel_observed_at
    successor["stage"] = "DECIDED"
    successor["stage_history"].append(
        {
            "from_stage": "EVIDENCE_GATHERING",
            "to_stage": "DECIDED",
            "at": "2026-08-06T01:03:00Z",
        }
    )
    successor["outcome_history"] = [
        {
            "from_status": None,
            "to_status": "not_applicable",
            "at": "2026-08-06T01:03:00Z",
            "reason": "The successor remains parked without an outcome.",
        }
    ]
    bundle["records"].append(
        {
            "id": "DEC-0002",
            "kind": "DECISION",
            "status": "PARKED",
            "reviewer_id": "independent-integrator",
            "reviewer_role": "Independent Integrator",
            "basis": "evidence_and_review",
            "rationale": "Retained evidence does not yet justify a separate epic.",
            "reconsideration_trigger": "Observe the novel artifact before another decision.",
            "evidence_refs": (
                ["EVID-NEW-0001", "EVID-BASE-0001"]
                if include_novel_in_decision
                else ["EVID-BASE-0001"]
            ),
            "unresolved_requirements": ["Retain novel evidence before reconsideration."],
            "decided_at": "2026-08-06T01:03:00Z",
        }
    )
    bundle["links"].extend(
        [
            {"from": "RFC-0001-R2", "relation": "SUPPORTED_BY", "to": "EVID-BASE-0001"},
            {"from": "RFC-0001-R2", "relation": "DECIDED_BY", "to": "DEC-0002"},
        ]
    )
    return bundle


def _outcome_bundle() -> dict:
    bundle = _valid_bundle()
    rfc = bundle["records"][4]
    rfc["stage"] = "OUTCOME_REVIEWED"
    rfc["stage_history"].append(
        {"from_stage": "DECIDED", "to_stage": "OUTCOME_REVIEWED", "at": "2026-08-06T00:07:00Z"}
    )
    rfc["outcome_history"].append(
        {
            "from_status": "pending",
            "to_status": "linked",
            "at": "2026-08-06T00:07:00Z",
            "reason": "The separate epic produced an evidence-bound outcome.",
        }
    )
    bundle["records"].extend(
        [
            {
                "id": "EVID-OUTCOME-0001",
                "kind": "EVIDENCE",
                "evidence_class": "negative_result",
                "claim": "The separately scoped comparison produced a retained result.",
                "source_ref": "repo://docs/nerva2/OUTCOME.md",
                "limitations": "The result is hermetic and not owner-live.",
                "integrity_sha256": "d" * 64,
                "observed_at": "2026-08-06T00:06:00Z",
            },
            {
                "id": "OUT-0001",
                "kind": "OUTCOME",
                "summary": "The hermetic comparison completed.",
                "claim_scope": "hermetic",
                "evidence_refs": ["EVID-OUTCOME-0001"],
                "measured_at": "2026-08-06T00:07:00Z",
            },
        ]
    )
    bundle["links"].extend(
        [
            {"from": "RFC-0001-R1", "relation": "CHALLENGED_BY", "to": "EVID-OUTCOME-0001"},
            {"from": "EPIC-0001", "relation": "PRODUCED", "to": "OUT-0001"},
        ]
    )
    return bundle


def _accepted_successor_bundle() -> dict:
    bundle = _valid_bundle()
    successor = copy.deepcopy(bundle["records"][4])
    successor.update(
        {
            "id": "RFC-0001-R2",
            "revision": 2,
            "stage": "DRAFT",
            "stage_history": [
                {"from_stage": None, "to_stage": "DRAFT", "at": "2026-08-06T01:00:00Z"}
            ],
            "benchmark": {
                "baseline_ref": None,
                "falsification_plan": "Evaluate the separately motivated follow-on.",
            },
            "outcome_history": [],
            "reopens_decision_id": None,
        }
    )
    bundle["records"].append(successor)
    bundle["links"].extend(
        [
            {"from": "IDEA-0001", "relation": "DEVELOPED_AS", "to": "RFC-0001-R2"},
            {"from": "RFC-0001-R2", "relation": "SUPERSEDES", "to": "RFC-0001-R1"},
        ]
    )
    return bundle


def _with_second_accepted_line(*, duplicate_epic_issue: bool) -> dict:
    bundle = _valid_bundle()
    mapping = {
        "OBS-0001": "OBS-0002",
        "IDEA-0001": "IDEA-0002",
        "EVID-PRIMARY-0001": "EVID-PRIMARY-0002",
        "EVID-BASE-0001": "EVID-BASE-0002",
        "RFC-0001": "RFC-0002",
        "RFC-0001-R1": "RFC-0002-R1",
        "DEC-0001": "DEC-0002",
        "EPIC-0001": "EPIC-0002",
    }

    def remap(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    records = remap(copy.deepcopy(bundle["records"]))
    records[0]["integrity_sha256"] = "4" * 64
    records[2]["integrity_sha256"] = "2" * 64
    records[3]["integrity_sha256"] = "3" * 64
    records[6]["issue"] = 900 if duplicate_epic_issue else 901
    bundle["records"].extend(records)
    bundle["links"].extend(remap(copy.deepcopy(bundle["links"])))
    return bundle


def _two_line_bundle_with_nonterminal_second_rfc() -> dict:
    bundle = _with_second_accepted_line(duplicate_epic_issue=False)
    second_rfc = next(record for record in bundle["records"] if record["id"] == "RFC-0002-R1")
    second_rfc["stage"] = "EVIDENCE_GATHERING"
    second_rfc["stage_history"] = second_rfc["stage_history"][:2]
    second_rfc["outcome_history"] = []
    removed = {"DEC-0002", "EPIC-0002"}
    bundle["records"] = [record for record in bundle["records"] if record["id"] not in removed]
    bundle["links"] = [
        link
        for link in bundle["links"]
        if link["from"] not in removed and link["to"] not in removed
    ]
    return bundle


def _assert_error(errors: list[str], fragment: str) -> None:
    assert any(fragment in error for error in errors), (
        f"expected error containing {fragment!r}, got {errors}"
    )


def _run_git(repo: Path, *args: str, input_text: str | None = None) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Nerva Test",
            "GIT_AUTHOR_EMAIL": "nerva@example.invalid",
            "GIT_COMMITTER_NAME": "Nerva Test",
            "GIT_COMMITTER_EMAIL": "nerva@example.invalid",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
    ).stdout.strip()


def _git_ref_matrix(validate_git_refs, validate_repository) -> None:
    with tempfile.TemporaryDirectory(prefix="nerva-innovation-git-") as temp:
        repo = Path(temp) / "source"
        repo.mkdir()
        _run_git(repo, "init", "-q")
        _run_git(repo, "config", "user.name", "Nerva Test")
        _run_git(repo, "config", "user.email", "nerva@example.invalid")
        (repo / "marker.txt").write_text("baseline\n", encoding="utf-8")
        _run_git(repo, "add", "marker.txt")
        _run_git(repo, "commit", "-q", "-m", "baseline")
        baseline = _run_git(repo, "rev-parse", "HEAD")
        (repo / "marker.txt").write_text("candidate\n", encoding="utf-8")
        _run_git(repo, "commit", "-q", "-am", "candidate")
        candidate = _run_git(repo, "rev-parse", "HEAD")

        assert validate_git_refs(repo, baseline, candidate) == []
        _assert_error(validate_git_refs(repo, baseline.upper(), candidate), "lowercase 40-hex")
        _assert_error(validate_git_refs(repo, baseline[:12], candidate), "lowercase 40-hex")

        tree = _run_git(repo, "rev-parse", "HEAD^{tree}")
        orphan = _run_git(repo, "commit-tree", tree, input_text="orphan\n")
        _assert_error(validate_git_refs(repo, orphan, candidate), "ancestor")

        (repo / "marker.txt").write_text("new head\n", encoding="utf-8")
        _run_git(repo, "commit", "-q", "-am", "new-head")
        _assert_error(validate_git_refs(repo, baseline, candidate), "candidate-ref must equal HEAD")

        shallow = Path(temp) / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
            text=True,
        )
        shallow_head = _run_git(shallow, "rev-parse", "HEAD")
        _assert_error(
            validate_git_refs(shallow, shallow_head, shallow_head),
            "shallow repository",
        )

        partial = Path(temp) / "partial-baseline"
        partial.mkdir()
        _run_git(partial, "init", "-q")
        _run_git(partial, "config", "user.name", "Nerva Test")
        _run_git(partial, "config", "user.email", "nerva@example.invalid")
        partial_schema = partial / "docs/nerva2/INNOVATION_LAB_V1.schema.json"
        partial_schema.parent.mkdir(parents=True)
        partial_schema.write_bytes(SCHEMA_PATH.read_bytes())
        _run_git(partial, "add", "docs/nerva2/INNOVATION_LAB_V1.schema.json")
        _run_git(partial, "commit", "-q", "-m", "partial baseline")
        partial_base = _run_git(partial, "rev-parse", "HEAD")
        partial_garden = partial / "docs/nerva2/KNOWLEDGE_GARDEN_V1.json"
        partial_garden.write_text("{}\n", encoding="utf-8")
        _run_git(partial, "add", "docs/nerva2/KNOWLEDGE_GARDEN_V1.json")
        _run_git(partial, "commit", "-q", "-m", "candidate")
        partial_candidate = _run_git(partial, "rev-parse", "HEAD")
        _assert_error(
            validate_repository(partial, partial_base, partial_candidate),
            "bootstrap requires both schema and garden to be absent",
        )


def run_checks() -> None:
    checker = _load_checker()
    raw_schema = SCHEMA_PATH.read_bytes()
    schema, schema_errors = checker["validate_schema_bytes"](raw_schema)
    assert schema is not None and schema_errors == [], schema_errors
    assert checker["schema_sha256"] == __import__("hashlib").sha256(raw_schema).hexdigest()

    # Strict JSON decode rejects ambiguity and all non-finite numeric spellings.
    _, errors = checker["decode"](b'{"a": 1, "a": 2}', "duplicate fixture")
    _assert_error(errors, "duplicate key")
    for numeric in (b'{"n": NaN}', b'{"n": Infinity}', b'{"n": -Infinity}', b'{"n": 1e999}'):
        _, errors = checker["decode"](numeric, "non-finite fixture")
        _assert_error(errors, "non-finite")

    # The schema itself is a pinned program in a deliberately closed profile.
    assert checker["validate_schema_document"](schema) == []
    unknown_keyword = copy.deepcopy(schema)
    unknown_keyword["$defs"]["authority"]["properties"]["can_merge"]["default"] = False
    _assert_error(checker["validate_schema_document"](unknown_keyword), "unknown schema keyword")
    bad_keyword_type = copy.deepcopy(schema)
    bad_keyword_type["$defs"]["non_empty_string"]["minLength"] = True
    _assert_error(checker["validate_schema_document"](bad_keyword_type), "minLength")
    remote_ref = copy.deepcopy(schema)
    remote_ref["properties"]["authority_ceiling"] = {"$ref": "https://example.invalid/schema"}
    _assert_error(checker["validate_schema_document"](remote_ref), "local $defs reference")
    ref_sibling = copy.deepcopy(schema)
    ref_sibling["properties"]["authority_ceiling"]["type"] = "object"
    _assert_error(checker["validate_schema_document"](ref_sibling), "$ref siblings")
    cyclic = copy.deepcopy(schema)
    cyclic["$defs"]["cycle_a"] = {"$ref": "#/$defs/cycle_b"}
    cyclic["$defs"]["cycle_b"] = {"$ref": "#/$defs/cycle_a"}
    _assert_error(checker["validate_schema_document"](cyclic), "cyclic $ref")
    _, errors = checker["validate_schema_bytes"](raw_schema + b" ")
    _assert_error(errors, "pinned schema SHA-256")

    def validate(bundle: dict) -> list[str]:
        return checker["validate_bundle"](bundle, schema=schema)

    assert validate(_valid_bundle()) == []
    assert validate(_parked_bundle()) == []
    assert validate(_rejected_bundle()) == []
    assert validate(_reopened_bundle()) == []
    assert validate(_outcome_bundle()) == []

    parked_predates_decision = _parked_bundle()
    parked_predates_decision["records"][4]["outcome_history"][0]["at"] = "2026-08-06T00:04:59Z"
    _assert_error(
        validate(parked_predates_decision),
        "not_applicable outcome must start at the decision timestamp",
    )
    rejected_predates_decision = _rejected_bundle()
    rejected_predates_decision["records"][4]["outcome_history"][0]["at"] = "2026-08-06T00:04:59Z"
    _assert_error(
        validate(rejected_predates_decision),
        "not_applicable outcome must start at the decision timestamp",
    )
    parked_postdates_decision = _parked_bundle()
    parked_postdates_decision["records"][4]["outcome_history"][0]["at"] = "2026-08-06T00:05:01Z"
    _assert_error(
        validate(parked_postdates_decision),
        "not_applicable outcome must start at the decision timestamp",
    )

    challenge_only_acceptance = _valid_bundle()
    for link in challenge_only_acceptance["links"]:
        if link["relation"] == "SUPPORTED_BY":
            link["relation"] = "CHALLENGED_BY"
    _assert_error(
        validate(challenge_only_acceptance),
        "ACCEPTED_FOR_EPIC requires strong pre-decision SUPPORTED_BY evidence",
    )

    non_benchmark_acceptance = _valid_bundle()
    non_benchmark_acceptance["records"][4]["benchmark"]["baseline_ref"] = "EVID-PRIMARY-0001"
    _assert_error(
        validate(non_benchmark_acceptance),
        "benchmark baseline_ref must resolve to pre-decision SUPPORTED_BY benchmark evidence",
    )

    support_only_rejection = _parked_bundle()
    support_only_rejection["records"][5]["status"] = "REJECTED"
    support_only_rejection["records"][5]["unresolved_requirements"] = []
    _assert_error(
        validate(support_only_rejection),
        "REJECTED requires strong pre-decision CHALLENGED_BY evidence",
    )

    ready = _ready_bundle()
    assert validate(ready) == []
    assert checker["compare"](ready, _valid_bundle()) == [], (
        "READY_FOR_REVIEW -> accepted decision/epic is a legal append-only progression"
    )
    draft_baseline, evidence_candidate = _draft_to_evidence_progression()
    assert validate(draft_baseline) == []
    assert validate(evidence_candidate) == []
    assert checker["compare"](draft_baseline, evidence_candidate) == [], (
        "DRAFT -> EVIDENCE_GATHERING may fill an empty exact-evidence baseline_ref"
    )
    evidence_baseline, ready_candidate = _evidence_to_ready_assessment_progression()
    assert validate(evidence_baseline) == []
    assert validate(ready_candidate) == []
    assert checker["compare"](evidence_baseline, ready_candidate) == [], (
        "EVIDENCE_GATHERING -> READY_FOR_REVIEW may complete required assessments"
    )

    assert checker["compare"](draft_baseline, ready_candidate) == [], (
        "one candidate may append DRAFT -> EVIDENCE_GATHERING -> READY_FOR_REVIEW"
    )
    parked_template = _parked_bundle()
    draft_to_decided = copy.deepcopy(draft_baseline)
    draft_to_decided_rfc = draft_to_decided["records"][2]
    draft_to_decided_rfc["stage"] = "DECIDED"
    draft_to_decided_rfc["stage_history"].append(
        {
            "from_stage": "DRAFT",
            "to_stage": "DECIDED",
            "at": "2026-08-06T00:05:00Z",
        }
    )
    draft_to_decided_rfc["benchmark"] = copy.deepcopy(parked_template["records"][4]["benchmark"])
    draft_to_decided_rfc["outcome_history"] = copy.deepcopy(
        parked_template["records"][4]["outcome_history"]
    )
    draft_to_decided["records"].extend(copy.deepcopy(parked_template["records"][2:4]))
    draft_to_decided["records"].append(copy.deepcopy(parked_template["records"][5]))
    draft_to_decided["links"].extend(copy.deepcopy(parked_template["links"][2:]))
    assert validate(draft_to_decided) == []
    assert checker["compare"](draft_baseline, draft_to_decided) == [], (
        "DRAFT -> DECIDED may fill the baseline for a PARKED decision"
    )

    evidence_to_decided = copy.deepcopy(evidence_baseline)
    evidence_to_decided_rfc = evidence_to_decided["records"][2]
    evidence_to_decided_rfc["stage"] = "DECIDED"
    evidence_to_decided_rfc["stage_history"].append(
        {
            "from_stage": "EVIDENCE_GATHERING",
            "to_stage": "DECIDED",
            "at": "2026-08-06T00:05:00Z",
        }
    )
    evidence_to_decided_rfc["assessments"] = copy.deepcopy(
        parked_template["records"][4]["assessments"]
    )
    evidence_to_decided_rfc["outcome_history"] = copy.deepcopy(
        parked_template["records"][4]["outcome_history"]
    )
    evidence_to_decided["records"].append(copy.deepcopy(parked_template["records"][5]))
    evidence_to_decided["links"].append(copy.deepcopy(parked_template["links"][-1]))
    assert validate(evidence_to_decided) == []
    assert checker["compare"](evidence_baseline, evidence_to_decided) == [], (
        "EVIDENCE_GATHERING -> DECIDED may complete required assessments for PARKED"
    )

    rewritten_baseline = copy.deepcopy(evidence_candidate)
    rewritten_baseline["records"][2]["benchmark"]["baseline_ref"] = "EVID-PRIMARY-0001"
    _assert_error(
        checker["compare"](evidence_candidate, rewritten_baseline),
        "benchmark baseline_ref",
    )
    fill_without_progression = copy.deepcopy(evidence_candidate)
    fill_without_progression["records"][2]["stage"] = "DRAFT"
    fill_without_progression["records"][2]["stage_history"] = copy.deepcopy(
        draft_baseline["records"][2]["stage_history"]
    )
    assert validate(fill_without_progression) == []
    _assert_error(
        checker["compare"](draft_baseline, fill_without_progression),
        "DRAFT -> EVIDENCE_GATHERING",
    )
    regressed_assessment = copy.deepcopy(ready_candidate)
    regressed_assessment["records"][2]["assessments"]["authority"] = {
        "status": "unknown",
        "details": "Assessment was erased.",
    }
    _assert_error(
        checker["compare"](ready_candidate, regressed_assessment),
        "assessment 'authority'",
    )
    rewritten_assessment = copy.deepcopy(ready_candidate)
    rewritten_assessment["records"][2]["assessments"]["security"]["details"] = (
        "A previously assessed result was rewritten."
    )
    _assert_error(
        checker["compare"](ready_candidate, rewritten_assessment),
        "assessment 'security'",
    )
    terminal_rfc_mutation = _valid_bundle()
    terminal_rfc_mutation["records"][4]["benchmark"]["falsification_plan"] = (
        "Rewrite the terminal experiment."
    )
    _assert_error(
        checker["compare"](_valid_bundle(), terminal_rfc_mutation),
        "terminal RFC core field 'benchmark'",
    )
    prototype_baseline, prototype_candidate = _required_prototype_progression()
    assert validate(prototype_baseline) == []
    assert validate(prototype_candidate) == []
    assert checker["compare"](prototype_baseline, prototype_candidate) == []

    # Early roots are honest backlog state; the validator never forces fake progression.
    early_observation = _valid_bundle()
    early_observation["records"] = early_observation["records"][:1]
    early_observation["links"] = []
    assert validate(early_observation) == []
    early_idea = copy.deepcopy(early_observation)
    early_idea["records"].append(copy.deepcopy(_valid_bundle()["records"][1]))
    early_idea["links"].append({"from": "OBS-0001", "relation": "MOTIVATES", "to": "IDEA-0001"})
    assert validate(early_idea) == []

    # Schema evaluation is type-sensitive at nested authority and record fields.
    false_lookalike = _valid_bundle()
    false_lookalike["authority_ceiling"]["can_merge"] = 0
    _assert_error(validate(false_lookalike), "can_merge")
    nested_type = _valid_bundle()
    nested_type["records"][4]["assessments"]["security"]["status"] = 0
    _assert_error(validate(nested_type), "security.status")
    missing_rfc_authority = _valid_bundle()
    del missing_rfc_authority["records"][4]["authority"]
    _assert_error(validate(missing_rfc_authority), "authority")
    authority_grant = _valid_bundle()
    authority_grant["records"][4]["authority"]["grants_authority"] = True
    _assert_error(validate(authority_grant), "grants_authority")
    actor_whitespace = _valid_bundle()
    actor_whitespace["records"][5]["reviewer_id"] = " independent-integrator "
    _assert_error(validate(actor_whitespace), "reviewer_id")
    digit_actor = _valid_bundle()
    digit_actor["records"][4]["author_id"] = "9research-builder"
    _assert_error(validate(digit_actor), "author_id")
    score_basis = _valid_bundle()
    score_basis["records"][5]["basis"] = "innovation_score"
    _assert_error(validate(score_basis), "basis")
    whitespace_rationale = _valid_bundle()
    whitespace_rationale["records"][5]["rationale"] = "   "
    _assert_error(validate(whitespace_rationale), "rationale")
    rfc_local_fixture = _valid_bundle()
    rfc_privacy = rfc_local_fixture["records"][4]["assessments"]["privacy"]
    rfc_privacy["private_data_policy"] = "local_only_fixture"
    rfc_privacy["policy_ref"] = "repo://fixtures/privacy-policy"
    assert validate(rfc_local_fixture) == []
    rfc_whitespace_policy = copy.deepcopy(rfc_local_fixture)
    rfc_whitespace_policy["records"][4]["assessments"]["privacy"]["policy_ref"] = "   "
    _assert_error(
        checker["evaluate_schema"](rfc_whitespace_policy, schema),
        "policy_ref",
    )
    relaxed_rfc_policy_schema = copy.deepcopy(schema)
    relaxed_rfc_policy_schema["$defs"]["privacy_assessment"]["properties"]["policy_ref"] = {
        "type": ["string", "null"]
    }
    _assert_error(
        checker["validate_bundle"](
            rfc_whitespace_policy,
            schema=relaxed_rfc_policy_schema,
        ),
        "local_only_fixture requires a non-whitespace policy_ref",
    )
    foreign_epic = _valid_bundle()
    foreign_epic["records"][6]["repository"] = "someone-else/jarvis-hub"
    _assert_error(validate(foreign_epic), "repository")
    duplicate_epic = _with_second_accepted_line(duplicate_epic_issue=True)
    _assert_error(validate(duplicate_epic), "repository/issue pair must be globally unique")

    # Closed-world graph validation rejects every orphan and ownership collision.
    orphan = _valid_bundle()
    orphan["records"].append(
        {
            **copy.deepcopy(orphan["records"][2]),
            "id": "EVID-ORPHAN-0001",
            "integrity_sha256": "e" * 64,
        }
    )
    _assert_error(validate(orphan), "reachable from an OBSERVATION")
    multi_owner_idea = _valid_bundle()
    second_observation = copy.deepcopy(multi_owner_idea["records"][0])
    second_observation.update({"id": "OBS-0002", "integrity_sha256": "f" * 64})
    multi_owner_idea["records"].append(second_observation)
    multi_owner_idea["links"].append(
        {"from": "OBS-0002", "relation": "MOTIVATES", "to": "IDEA-0001"}
    )
    assert validate(multi_owner_idea) == [], "two observations may motivate one idea"

    one_idea_two_lines = _valid_bundle()
    second_line = copy.deepcopy(one_idea_two_lines["records"][4])
    second_line.update(
        {
            "id": "RFC-0002-R1",
            "stable_id": "RFC-0002",
            "stage": "DRAFT",
            "stage_history": [
                {"from_stage": None, "to_stage": "DRAFT", "at": "2026-08-06T01:00:00Z"}
            ],
            "benchmark": {
                "baseline_ref": None,
                "falsification_plan": "Keep the second line independently falsifiable.",
            },
            "outcome_history": [],
            "reopens_decision_id": None,
        }
    )
    one_idea_two_lines["records"].append(second_line)
    one_idea_two_lines["links"].append(
        {"from": "IDEA-0001", "relation": "DEVELOPED_AS", "to": "RFC-0002-R1"}
    )
    _assert_error(validate(one_idea_two_lines), "IDEA may own only one stable_id lineage")

    shared_same_lineage = _reopened_bundle()
    shared_same_lineage["links"].append(
        {"from": "RFC-0001-R2", "relation": "SUPPORTED_BY", "to": "EVID-BASE-0001"}
    )
    assert validate(shared_same_lineage) == [], (
        "R1/R2 in one stable lineage may share retained evidence"
    )
    cross_lineage_evidence = _with_second_accepted_line(duplicate_epic_issue=False)
    cross_lineage_evidence["links"].append(
        {"from": "RFC-0002-R1", "relation": "CHALLENGED_BY", "to": "EVID-BASE-0001"}
    )
    _assert_error(
        validate(cross_lineage_evidence),
        "EVIDENCE owners must share exactly one stable_id lineage",
    )
    dual_disposition = _valid_bundle()
    dual_disposition["links"].append(
        {"from": "RFC-0001-R1", "relation": "CHALLENGED_BY", "to": "EVID-BASE-0001"}
    )
    _assert_error(
        validate(dual_disposition),
        "same RFC/evidence pair cannot be both SUPPORTED_BY and CHALLENGED_BY",
    )

    shared_decision = _valid_bundle()
    second_evidence = copy.deepcopy(shared_decision["records"][2])
    second_evidence.update(
        {
            "id": "EVID-SECOND-0001",
            "integrity_sha256": "1" * 64,
            "source_ref": "repo://second",
            "claim": "A second RFC has separate evidence.",
        }
    )
    second_rfc = copy.deepcopy(shared_decision["records"][4])
    second_rfc.update(
        {
            "id": "RFC-0002-R1",
            "stable_id": "RFC-0002",
            "benchmark": {
                "baseline_ref": "EVID-SECOND-0001",
                "falsification_plan": "Reject if the second evidence does not hold.",
            },
        }
    )
    shared_decision["records"].extend([second_evidence, second_rfc])
    shared_decision["links"].extend(
        [
            {"from": "IDEA-0001", "relation": "DEVELOPED_AS", "to": "RFC-0002-R1"},
            {"from": "RFC-0002-R1", "relation": "SUPPORTED_BY", "to": "EVID-SECOND-0001"},
            {"from": "RFC-0002-R1", "relation": "DECIDED_BY", "to": "DEC-0001"},
        ]
    )
    _assert_error(validate(shared_decision), "DECISION must be owned by exactly one RFC")

    # Artifact and semantic fingerprints prevent ID cloning or evidence-class upgrades.
    relabel = _valid_bundle()
    relabelled = copy.deepcopy(relabel["records"][2])
    relabelled.update(
        {
            "id": "EVID-RELABELLED-0001",
            "evidence_class": "owner_live",
            "source_ref": "owner://upgraded",
            "claim": "Relabelled bytes must not become stronger evidence.",
        }
    )
    relabel["records"].append(relabelled)
    _assert_error(validate(relabel), "artifact fingerprint")

    semantic_clone = _valid_bundle()
    clone = copy.deepcopy(semantic_clone["records"][2])
    clone["id"] = "EVID-CLONE-0001"
    clone["claim"] = "  The existing path and limitation were inspected.  "
    semantic_clone["records"].append(clone)
    _assert_error(validate(semantic_clone), "semantic fingerprint")

    forged_reopen = _reopened_bundle()
    forged_reopen["records"][6]["integrity_sha256"] = "a" * 64
    forged_reopen["records"][6]["evidence_class"] = "in_repository"
    forged_reopen["records"][6]["source_ref"] = "repo://docs/nerva2/BASELINE.md"
    _assert_error(validate(forged_reopen), "new artifact fingerprint")
    backdated_reopen = _reopened_bundle()
    backdated_reopen["records"][6]["observed_at"] = "2026-08-06T00:04:59Z"
    _assert_error(validate(backdated_reopen), "observed after the prior decision")
    decided_reopen = _decided_reopened_bundle(
        novel_observed_at="2026-08-06T01:02:30Z",
        include_novel_in_decision=True,
    )
    assert validate(decided_reopen) == []
    boundary_reopen = _decided_reopened_bundle(
        novel_observed_at="2026-08-06T01:03:00Z",
        include_novel_in_decision=True,
    )
    assert validate(boundary_reopen) == []
    postdecision_novelty = _decided_reopened_bundle(
        novel_observed_at="2026-08-06T01:03:01Z",
        include_novel_in_decision=False,
    )
    _assert_error(
        validate(postdecision_novelty),
        "reopening evidence must be observed on or before the successor decision",
    )
    missing_reopens = _reopened_bundle()
    missing_reopens["links"] = [
        link for link in missing_reopens["links"] if link["relation"] != "REOPENS"
    ]
    _assert_error(validate(missing_reopens), "matching REOPENS")
    accepted_reopen = _reopened_bundle()
    accepted_reopen["records"][5]["status"] = "ACCEPTED_FOR_EPIC"
    _assert_error(validate(accepted_reopen), "PARKED or REJECTED")
    accepted_successor = _accepted_successor_bundle()
    _assert_error(
        validate(accepted_successor),
        "accepted predecessor terminates its stable_id lineage",
    )
    backdated_successor = _reopened_bundle()
    backdated_successor["records"][7]["stage_history"][0]["at"] = "2026-08-06T00:05:00Z"
    _assert_error(
        validate(backdated_successor),
        "initial stage must be strictly after predecessor decision",
    )

    # Prototype and outcome claims stay bound to the exact RFC and decision chain.
    prototype = _valid_bundle()
    prototype["records"][4]["prototype_disposition"]["status"] = "required"
    prototype["records"].append(
        {
            "id": "PROTO-0001",
            "kind": "PROTOTYPE",
            "branch": "nerva-lab/rfc-0001-r1-bounded-test",
            "disposable": True,
            "production_data": False,
            "private_data_policy": "excluded",
            "policy_ref": None,
            "teardown_plan": "Delete the disposable branch and fixtures.",
            "tested_at": "2026-08-06T00:03:30Z",
        }
    )
    prototype["links"].append({"from": "RFC-0001-R1", "relation": "TESTED_BY", "to": "PROTO-0001"})
    assert validate(prototype) == []
    draft_boundary_prototype = copy.deepcopy(prototype)
    draft_boundary_prototype["records"][7]["tested_at"] = "2026-08-06T00:02:00Z"
    assert validate(draft_boundary_prototype) == []
    pre_draft_prototype = copy.deepcopy(prototype)
    pre_draft_prototype["records"][7]["tested_at"] = "2026-08-06T00:01:59Z"
    _assert_error(validate(pre_draft_prototype), "no earlier than RFC initial DRAFT")
    wrong_prototype = copy.deepcopy(prototype)
    wrong_prototype["records"][7]["branch"] = "nerva-lab/rfc-9999-r1-bounded-test"
    _assert_error(validate(wrong_prototype), "exact RFC record")
    post_review_prototype = copy.deepcopy(prototype)
    post_review_prototype["records"][7]["tested_at"] = "2026-08-06T00:04:30Z"
    _assert_error(validate(post_review_prototype), "no later than first READY_FOR_REVIEW")
    post_decision_prototype = copy.deepcopy(prototype)
    post_decision_prototype["records"][7]["tested_at"] = "2026-08-06T00:06:00Z"
    _assert_error(validate(post_decision_prototype), "before the decision")
    prototype_local_fixture = copy.deepcopy(prototype)
    prototype_local_fixture["records"][7]["private_data_policy"] = "local_only_fixture"
    prototype_local_fixture["records"][7]["policy_ref"] = "repo://fixtures/prototype-policy"
    assert validate(prototype_local_fixture) == []
    prototype_whitespace_policy = copy.deepcopy(prototype_local_fixture)
    prototype_whitespace_policy["records"][7]["policy_ref"] = "\t "
    _assert_error(
        checker["evaluate_schema"](prototype_whitespace_policy, schema),
        "policy_ref",
    )
    relaxed_prototype_policy_schema = copy.deepcopy(schema)
    relaxed_prototype_policy_schema["$defs"]["prototype"]["properties"]["policy_ref"] = {
        "type": ["string", "null"]
    }
    _assert_error(
        checker["validate_bundle"](
            prototype_whitespace_policy,
            schema=relaxed_prototype_policy_schema,
        ),
        "local_only_fixture requires a non-whitespace policy_ref",
    )

    premature_outcome = _outcome_bundle()
    premature_outcome["records"][7]["observed_at"] = "2026-08-06T00:04:00Z"
    _assert_error(validate(premature_outcome), "post-decision evidence")
    decision_evidence_outcome = _outcome_bundle()
    decision_evidence_outcome["records"][8]["evidence_refs"] = ["EVID-BASE-0001"]
    _assert_error(validate(decision_evidence_outcome), "exact-RFC post-decision evidence")
    false_live = _outcome_bundle()
    false_live["records"][8]["claim_scope"] = "owner_live"
    _assert_error(validate(false_live), "owner_live evidence")
    future_outcome_evidence = _outcome_bundle()
    future_outcome_evidence["records"][7]["observed_at"] = "2026-08-06T00:08:00Z"
    _assert_error(
        validate(future_outcome_evidence),
        "observed no later than the outcome",
    )

    # Baseline comparison is append-only, order-sensitive and history-prefix aware.
    compare = checker["compare"]
    assert compare(_valid_bundle(), _valid_bundle()) == []
    assert compare(_parked_bundle(), _reopened_bundle()) == []
    assert compare(_valid_bundle(), _outcome_bundle()) == []
    assert compare(_ready_bundle(), _valid_bundle()) == []

    retained_evidence_baseline = _reopened_bundle()
    retained_evidence_candidate = copy.deepcopy(retained_evidence_baseline)
    retained_evidence_candidate["links"].extend(
        [
            {
                "from": "RFC-0001-R2",
                "relation": "SUPPORTED_BY",
                "to": "EVID-PRIMARY-0001",
            },
            {
                "from": "RFC-0001-R2",
                "relation": "CHALLENGED_BY",
                "to": "EVID-BASE-0001",
            },
        ]
    )
    assert validate(retained_evidence_candidate) == []
    assert compare(retained_evidence_baseline, retained_evidence_candidate) == [], (
        "a retained nonterminal RFC may link retained evidence from its stable lineage"
    )

    retained_dual_label = copy.deepcopy(retained_evidence_baseline)
    retained_dual_label["links"].append(
        {"from": "RFC-0001-R2", "relation": "CHALLENGED_BY", "to": "EVID-NEW-0001"}
    )
    _assert_error(
        compare(retained_evidence_baseline, retained_dual_label),
        "both SUPPORTED_BY and CHALLENGED_BY",
    )

    cross_lineage_baseline = _two_line_bundle_with_nonterminal_second_rfc()
    assert validate(cross_lineage_baseline) == []
    retained_cross_lineage = copy.deepcopy(cross_lineage_baseline)
    retained_cross_lineage["links"].append(
        {"from": "RFC-0002-R1", "relation": "CHALLENGED_BY", "to": "EVID-BASE-0001"}
    )
    _assert_error(
        compare(cross_lineage_baseline, retained_cross_lineage),
        "same stable_id lineage",
    )

    retained_terminal_edge = copy.deepcopy(retained_evidence_baseline)
    retained_terminal_edge["links"].append(
        {"from": "RFC-0001-R1", "relation": "CHALLENGED_BY", "to": "EVID-NEW-0001"}
    )
    _assert_error(
        compare(retained_evidence_baseline, retained_terminal_edge),
        "frozen baseline edge",
    )

    new_observation_candidate = _valid_bundle()
    new_observation = copy.deepcopy(new_observation_candidate["records"][0])
    new_observation.update(
        {
            "id": "OBS-0002",
            "summary": "A second retained observation independently motivates the idea.",
            "source_ref": "repo://docs/nerva2/SECOND-OBSERVATION.md",
            "integrity_sha256": "f" * 64,
            "observed_at": "2026-08-06T00:00:30Z",
        }
    )
    new_observation_candidate["records"].append(new_observation)
    new_observation_candidate["links"].append(
        {"from": "OBS-0002", "relation": "MOTIVATES", "to": "IDEA-0001"}
    )
    assert validate(new_observation_candidate) == []
    assert compare(_valid_bundle(), new_observation_candidate) == [], (
        "a new observation may append motivation to a retained idea"
    )

    relabelled_retained_idea = copy.deepcopy(new_observation_candidate)
    relabelled_retained_idea["records"][1]["title"] = "Relabelled retained idea"
    _assert_error(
        compare(_valid_bundle(), relabelled_retained_idea),
        "immutable prior record",
    )
    deleted_retained_record = _valid_bundle()
    deleted_retained_record["records"].pop()
    _assert_error(
        compare(_valid_bundle(), deleted_retained_record),
        "records cannot be deleted",
    )
    reordered = _valid_bundle()
    reordered["records"][0], reordered["records"][1] = (
        reordered["records"][1],
        reordered["records"][0],
    )
    _assert_error(compare(_valid_bundle(), reordered), "record order/identity")
    rewritten = _valid_bundle()
    rewritten["records"][5]["rationale"] = "Rewritten historical rationale."
    _assert_error(compare(_valid_bundle(), rewritten), "immutable prior record")
    object_order_only = _valid_bundle()
    object_order_only["records"][5] = dict(reversed(object_order_only["records"][5].items()))
    assert compare(_valid_bundle(), object_order_only) == [], (
        "JSON object member order is not semantic state"
    )
    rewritten_history = _outcome_bundle()
    rewritten_history["records"][4]["stage_history"][0]["at"] = "2026-08-05T00:00:00Z"
    _assert_error(
        compare(_valid_bundle(), rewritten_history), "stage_history must retain the baseline prefix"
    )
    reordered_links = _valid_bundle()
    reordered_links["links"][0], reordered_links["links"][1] = (
        reordered_links["links"][1],
        reordered_links["links"][0],
    )
    _assert_error(
        compare(_valid_bundle(), reordered_links), "links must retain the baseline prefix"
    )
    catalogue_baseline = json.loads(GARDEN_PATH.read_text(encoding="utf-8"))
    catalogue_rewrite = copy.deepcopy(catalogue_baseline)
    catalogue_rewrite["catalogues"][0]["content_bytes"] += 1
    _assert_error(
        compare(catalogue_baseline, catalogue_rewrite), "catalogues must retain the baseline prefix"
    )

    backdated_history = _outcome_bundle()
    backdated_history["records"][4]["stage_history"][-1]["at"] = "2026-08-06T00:04:59Z"
    _assert_error(validate(backdated_history), "strictly increasing")

    # Historical catalogue anchors are immutable, versioned references only.
    canonical_garden = json.loads(GARDEN_PATH.read_text(encoding="utf-8"))
    canonical_errors = checker["validate_bundle"](
        canonical_garden,
        schema=schema,
        repo=REPO,
        verify_catalogues=True,
        require_canonical_catalogues=True,
    )
    assert canonical_errors == [], canonical_errors
    catalogue_mutation = copy.deepcopy(canonical_garden)
    catalogue_mutation["catalogues"][1]["source_issue"] = 805
    _assert_error(
        checker["validate_bundle"](
            catalogue_mutation,
            schema=schema,
            repo=REPO,
            verify_catalogues=True,
            require_canonical_catalogues=True,
        ),
        "immutable historical catalogue anchor",
    )

    # Immutable Git refs are strict SHA inputs; shallow and non-ancestor cases fail.
    _git_ref_matrix(checker["validate_git_refs"], checker["validate_repository"])

    # Direct evaluator sanity: bool is not the integer zero in const/enum checks.
    _assert_error(checker["evaluate_schema"](0, {"const": False}), "const")
    _assert_error(checker["evaluate_schema"](False, {"type": "integer"}), "type")


if __name__ == "__main__":
    run_checks()
    print("Innovation Lab fail-closed hostile matrix passed")
