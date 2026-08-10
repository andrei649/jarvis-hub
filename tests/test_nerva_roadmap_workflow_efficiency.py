"""Structural guards for stable, classifier-driven Nerva integrity checks."""

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = yaml.load(
    (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
    Loader=yaml.BaseLoader,
)
WORKFLOW = yaml.load(
    (REPO / ".github/workflows/nerva-roadmap.yml").read_text(encoding="utf-8"),
    Loader=yaml.BaseLoader,
)
POLICY = json.loads((REPO / ".github/change-risk.json").read_text(encoding="utf-8"))

NERVA_PATTERNS = [
    "BACKLOG.md",
    "STATUS.md",
    "docs/nerva2/**",
    "scripts/check_nerva_*.py",
    "scripts/reconcile_nerva_repository_ledgers.py",
    "tests/nerva_check_cases.py",
    "tests/_nerva_*_checks.py",
    "tests/test_nerva_*.py",
    "tests/test_reconcile_nerva_repository_ledgers.py",
    ".github/workflows/nerva-roadmap.yml",
]


def test_reusable_workflow_uses_one_trusted_owned_path_contract():
    triggers = WORKFLOW["on"]
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}
    call_inputs = triggers["workflow_call"]["inputs"]
    assert set(call_inputs) == {"enabled", "baseline_ref", "candidate_ref"}
    assert call_inputs["enabled"]["type"] == "boolean"
    assert call_inputs["enabled"]["required"] == "true"
    assert POLICY["nerva_patterns"] == NERVA_PATTERNS

    ci_job = CI["jobs"]["nerva-integrity"]
    assert set(ci_job["needs"]) == {"classify", "fast-gate"}
    assert ci_job["uses"] == "./.github/workflows/nerva-roadmap.yml"
    assert "nerva_relevant" in ci_job["with"]["enabled"]
    assert "nerva-integrity" in CI["jobs"]["required"]["needs"]


def test_workflow_is_bounded_and_cancels_superseded_heads():
    assert WORKFLOW["concurrency"]["cancel-in-progress"] == "true"
    assert "github.workflow" in WORKFLOW["concurrency"]["group"]
    assert int(WORKFLOW["jobs"]["validate"]["timeout-minutes"]) <= 15
    steps = WORKFLOW["jobs"]["validate"]["steps"]
    skip = next(step for step in steps if step.get("name", "").startswith("Skip Nerva"))
    assert "NERVA_ENABLED != 'true'" in skip["if"]
    enabled_steps = [step for step in steps if step is not skip]
    assert all("NERVA_ENABLED == 'true'" in step["if"] for step in enabled_steps)
