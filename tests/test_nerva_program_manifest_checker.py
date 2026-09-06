"""Hermetic tests for the compact Nerva program-manifest checker.

The fixture repository is built from the real manifest + contract registry, with every
referenced path materialised as an empty file, so each test can break exactly one thing
and watch the checker go red. Nothing here touches the network or a real ``gh``.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))
sys.path.insert(0, str(REPO / "scripts"))

import check_nerva_program_manifest as checker  # noqa: E402

MANIFEST = REPO / checker.MANIFEST_RELATIVE
REGISTRY = REPO / checker.REGISTRY_RELATIVE
WORKFLOW = REPO / ".github" / "workflows" / "nerva-manifest-check.yml"

# Files owned by sibling slices of the same PR (co-work-run-ledger, co-supervisor,
# co-verifier, work-judge, n2-e5-slice-doc). The real-repo strict test runs only once
# they are all present; until then it is a visible skip, never a silent pass.
SIBLING_PATHS = (
    "agents/core/autonomy/work_runs.py",
    "agents/core/autonomy/company_supervisor.py",
    "agents/core/autonomy/work_verifier.py",
    "agents/core/autonomy/work_judge.py",
    "docs/nerva2/NIGHT_SHIFT_E5_0.md",
)


def _touch(root: Path, relative: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text("fixture\n", encoding="utf-8")


def _referenced_paths(data: dict, registry: dict) -> set[str]:
    paths: set[str] = set(data["movement_gate"]["registry"])
    manual = data["movement_gate"]["manual_integration"]
    paths.update({manual["workflow_path"], manual["policy_test_path"]})
    for stream in data["streams"]:
        for item in stream.get("completion_evidence", []):
            paths.add(item["repo_path"])
        for prereq in stream["delivery_prerequisites"]:
            for item in prereq.get("accepted_evidence", []):
                paths.add(item["repo_path"])
        for blocker in stream["blockers"]:
            paths.add(blocker["artifact"])
        for ref in stream["references"]:
            if ref["kind"] == "repo_path":
                paths.add(ref["value"])
    for entry in data.get("reconciliation_log", []):
        for item in entry["evidence"]:
            if item.startswith(("docs/", "scripts/", "tests/", ".github/")):
                paths.add(item.split(":", 1)[0])
    for contract in registry["contracts"]:
        paths.update(contract["evidence_paths"])
    return paths


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A throwaway repository root whose manifest is the real one, fully materialised."""

    root = tmp_path / "repo"
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    registry_bytes = REGISTRY.read_bytes()
    registry = json.loads(registry_bytes)
    (root / "docs/nerva2").mkdir(parents=True)
    (root / checker.REGISTRY_RELATIVE).write_bytes(registry_bytes)
    for relative in _referenced_paths(data, registry):
        _touch(root, relative)
    _write_manifest(root, data)
    return root


def _write_manifest(root: Path, data: dict) -> None:
    (root / checker.MANIFEST_RELATIVE).write_text(json.dumps(data, indent=1), encoding="utf-8")
    checker.write_document(repo_root=root)


def _load(root: Path) -> dict:
    return json.loads((root / checker.MANIFEST_RELATIVE).read_text(encoding="utf-8"))


def _fake_gh(states: dict[int, str], *, exit_code: int = 0, broken_json: bool = False):
    """Deterministic ``gh issue view`` stand-in: ``argv -> (rc, stdout)``."""

    calls: list[list[str]] = []

    def run(argv):
        calls.append(list(argv))
        number = int(argv[2])
        if exit_code:
            return exit_code, ""
        if broken_json:
            return 0, "not json"
        return 0, json.dumps({"number": number, "state": states.get(number, "OPEN"), "title": "t"})

    run.calls = calls  # type: ignore[attr-defined]
    return run


# ── green path ────────────────────────────────────────────────────────────────

def test_reconciled_fixture_manifest_passes(fixture_repo: Path) -> None:
    report = checker.check_manifest(repo_root=fixture_repo)
    assert report.errors == []
    assert report.ok is True
    assert report.document_matches is True
    assert report.registry_paths_checked >= 15
    assert report.live_issue_state == "not_verified"


def test_manifest_truth_after_reconciliation(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    gate = data["movement_gate"]
    assert gate["enforcement_state"] == "safety_disabled"
    assert gate["rollback"]["pull_request"] == 981
    assert gate["rollback"]["rollback_of_issue"] == 846
    retired = {r["path"] for r in gate["registry_retired"]}
    assert "tests/test_nerva_program_manifest.py" in retired
    assert ".github/workflows/nerva-roadmap.yml" in retired
    assert "scripts/check_nerva_program_manifest.py" in gate["registry"]
    streams = {s["id"]: s for s in data["streams"]}
    assert {"kind": "issue", "value": 1008} in streams["E4"]["references"]
    e11 = {b["id"]: b for b in streams["E11"]["blockers"]}["E11-owner-OWNER_LIVE"]
    assert e11["reason_code"] == "a1_section0_run_record_owed"
    b7 = {b["id"]: b for b in streams["E5"]["blockers"]}["E5-program-B7"]
    assert "#918" in b7["note"] and "not program-accepted" in b7["note"]
    # The mirror is a projection of the registry, so compare it to the registry rather
    # than to a word: a hard-coded status turns into a false claim the moment the real
    # row moves, which is exactly what it is here to catch.
    registry_now = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert data["contract_registry"]["statuses"] == {
        c["id"]: c["status"] for c in registry_now["contracts"]
    }
    assert data["evidence_snapshot"]["live_issue_state_verified_by_checker"] is False


# ── red paths: registry and gate ──────────────────────────────────────────────

def test_dead_registry_path_fails(fixture_repo: Path) -> None:
    (fixture_repo / "GO_LIVE_PLAN.md").unlink()
    report = checker.check_manifest(repo_root=fixture_repo)
    assert report.ok is False
    assert "dead_registry_path:GO_LIVE_PLAN.md" in report.errors


def test_retired_path_reappearing_fails(fixture_repo: Path) -> None:
    _touch(fixture_repo, "tests/test_nerva_program_manifest.py")
    report = checker.check_manifest(repo_root=fixture_repo)
    assert any(e.startswith("retired_path_present:tests/test_nerva_program_manifest.py") for e in report.errors)


def test_unsorted_registry_fails(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    data["movement_gate"]["registry"].reverse()
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "movement_gate.registry must be sorted and unique" in report.errors


def test_required_state_forbids_rollback_and_safety_disabled_requires_it(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    data["movement_gate"]["enforcement_state"] = "required"
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "movement_gate.rollback must be null while enforcement is required" in report.errors

    data["movement_gate"]["enforcement_state"] = "safety_disabled"
    data["movement_gate"]["rollback"] = None
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "movement_gate.rollback must be an object while enforcement is safety_disabled" in report.errors


def test_rollback_must_bind_commit_and_listed_pull_request(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    data["movement_gate"]["rollback"]["commit"] = "deadbeef"
    data["movement_gate"]["program_control_pull_requests"] = []
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "movement_gate.rollback.commit must be a 40-hex commit" in report.errors
    assert "movement_gate.rollback.pull_request must be listed in program_control_pull_requests" in report.errors


# ── red paths: streams, contracts, document ──────────────────────────────────

def test_live_flag_in_file_can_never_be_true(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    data["evidence_snapshot"]["live_issue_state_verified_by_checker"] = True
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert report.ok is False
    assert any("live_issue_state_verified_by_checker must remain false" in e for e in report.errors)


def test_eligibility_must_derive_from_status_and_open_causes(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    e4 = next(s for s in data["streams"] if s["id"] == "E4")
    e4["delivery_eligibility"] = "eligible"
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "streams[E4].delivery_eligibility must derive to blocked" in report.errors


def test_delivery_blockers_must_mirror_unsatisfied_gates(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    e7 = next(s for s in data["streams"] if s["id"] == "E7")
    e7["blockers"] = [b for b in e7["blockers"] if b["target"] != "E4"]
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert any(e.startswith("streams[E7]: delivery_gate blockers") for e in report.errors)


def test_prerequisites_must_match_contract_registry(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    e8 = next(s for s in data["streams"] if s["id"] == "E8")
    e8["delivery_prerequisites"].append({"source": "E9", "gate_state": "unsatisfied", "accepted_evidence": []})
    e8["blockers"].append({
        "id": "E8-delivery-E9", "kind": "delivery_gate", "target": "E9", "issue": 767,
        "artifact": "docs/nerva2/DEPENDENCIES.md", "reason_code": "upstream_gate_not_accepted",
    })
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert any("streams[E8].delivery_prerequisites" in e and "!= registry" in e for e in report.errors)


def test_contract_status_drift_fails(fixture_repo: Path) -> None:
    registry_path = fixture_repo / checker.REGISTRY_RELATIVE
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    next(c for c in registry["contracts"] if c["id"] == "nerva.work-run.v1")["status"] = "accepted"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    report = checker.check_manifest(repo_root=fixture_repo)
    assert "contract_registry.sha256 does not match CONTRACT_REGISTRY.json bytes" in report.errors
    assert any(e.startswith("contract_registry.statuses") for e in report.errors)


def test_dead_contract_evidence_path_fails(fixture_repo: Path) -> None:
    """Deleting a file the registry cites must be caught by name.

    The path is READ from the registry rather than written here: an earlier version
    named a file the registry had stopped citing, so the red path stopped exercising
    the check it exists to prove.
    """
    registry = json.loads((fixture_repo / checker.REGISTRY_RELATIVE).read_text(encoding="utf-8"))
    contract = next(c for c in registry["contracts"] if c["id"] == "nerva.work-run.v1")
    relative = contract["evidence_paths"][0]
    (fixture_repo / relative).unlink()
    report = checker.check_manifest(repo_root=fixture_repo)
    assert f"dead_contract_evidence_path:nerva.work-run.v1:{relative}" in report.errors


def test_stale_markdown_view_fails_and_write_repairs_it(fixture_repo: Path) -> None:
    document = fixture_repo / checker.DOCUMENT_RELATIVE
    document.write_text(document.read_text(encoding="utf-8") + "\nedited by hand\n", encoding="utf-8")
    report = checker.check_manifest(repo_root=fixture_repo)
    assert report.document_matches is False
    assert any(e.startswith("document_stale:") for e in report.errors)
    checker.write_document(repo_root=fixture_repo)
    assert checker.check_manifest(repo_root=fixture_repo).ok is True


def test_runtime_edge_absent_from_registry_needs_open_drift(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    data["known_source_drifts"] = []
    _write_manifest(fixture_repo, data)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert any("absent from registry without an open drift record" in e for e in report.errors)


# ── live verification ────────────────────────────────────────────────────────

def _consistent_states(data: dict) -> dict[int, str]:
    return {s["epic_issue"]: "CLOSED" if s["program_status"] == "done" else "OPEN" for s in data["streams"]}


def test_live_absent_stays_not_verified(fixture_repo: Path) -> None:
    report = checker.check_manifest(repo_root=fixture_repo, gh=None)
    assert report.live_issue_state == "not_verified"
    assert report.ok is True


def test_live_consistent_gh_run_verifies(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    gh = _fake_gh(_consistent_states(data))
    report = checker.check_manifest(repo_root=fixture_repo, gh=gh)
    assert report.live_issue_state == "verified"
    assert report.ok is True
    assert all(call[:2] == ["issue", "view"] and "--repo" in call for call in gh.calls)
    assert {int(call[2]) for call in gh.calls} >= set(_consistent_states(data))
    # The file itself never flips: verification lives in the report only.
    assert _load(fixture_repo)["evidence_snapshot"]["live_issue_state_verified_by_checker"] is False


def test_live_mismatch_is_reported_as_error(fixture_repo: Path) -> None:
    data = _load(fixture_repo)
    states = _consistent_states(data)
    states[758] = "OPEN"  # E0 is done in the manifest, so live OPEN contradicts it
    report = checker.check_manifest(repo_root=fixture_repo, gh=_fake_gh(states))
    assert report.live_issue_state == "mismatch"
    assert report.ok is False
    assert any(e.startswith("live_issue_mismatch:#758") for e in report.errors)


@pytest.mark.parametrize("kwargs", [{"exit_code": 4}, {"broken_json": True}])
def test_live_gh_failure_never_reports_verified(fixture_repo: Path, kwargs: dict) -> None:
    data = _load(fixture_repo)
    report = checker.check_manifest(repo_root=fixture_repo, gh=_fake_gh(_consistent_states(data), **kwargs))
    assert report.live_issue_state == "not_verified"
    assert report.warnings, "a failed gh query must leave a visible warning"


def test_gh_cli_runner_refuses_without_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checker.shutil, "which", lambda _name: None)
    assert checker.gh_cli_runner() is None


# ── CLI and workflow ─────────────────────────────────────────────────────────

def test_cli_json_exit_codes(fixture_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert checker.main(["--repo-root", str(fixture_repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["live_issue_state"] == "not_verified"
    (fixture_repo / "README.md").unlink()
    assert checker.main(["--repo-root", str(fixture_repo)]) == 1
    assert "dead_registry_path:README.md" in capsys.readouterr().out


def test_cli_live_without_gh_warns_and_stays_not_verified(
    fixture_repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "gh_cli_runner", lambda: None)
    assert checker.main(["--repo-root", str(fixture_repo), "--live", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["live_issue_state"] == "not_verified"
    assert any("dependency_unavailable:gh" in w for w in payload["warnings"])


def test_workflow_is_advisory_and_read_only() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on") or workflow.get(True)
    assert "pull_request" not in triggers, "post-de-gate posture: never a PR gate"
    assert set(triggers) >= {"push", "schedule", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read", "issues": "read"}
    steps = workflow["jobs"]["manifest"]["steps"]
    offline = next(s for s in steps if s.get("name") == "Offline manifest check")
    assert offline["run"].strip() == "python scripts/check_nerva_program_manifest.py"
    live = next(s for s in steps if s.get("name", "").startswith("Live issue verification"))
    assert live["continue-on-error"] is True and "--live" in live["run"]


# ── the real repository ──────────────────────────────────────────────────────

def test_real_manifest_has_no_dead_registry_paths_and_consistent_structure() -> None:
    report = checker.check_manifest()
    pending = [e for e in report.errors if any(p in e for p in SIBLING_PATHS)]
    unexpected = [e for e in report.errors if e not in pending]
    assert not [e for e in report.errors if e.startswith("dead_registry_path:")]
    assert unexpected == [], unexpected
    assert report.live_issue_state == "not_verified"


@pytest.mark.skipif(
    not all((REPO / p).exists() for p in SIBLING_PATHS),
    reason="E5.0 sibling slices not landed in this checkout yet",
)
def test_real_manifest_is_fully_green_once_siblings_land() -> None:
    report = checker.check_manifest()
    assert report.errors == []
    assert report.ok is True


def test_real_contract_registry_work_run_row_claims_only_what_exists() -> None:
    """The Night Shift row's authority is fixed; its status is whatever the shipped code
    earns, and every evidence path it names must be a real file.

    This deliberately does NOT pin the status word. The row was briefly written as
    `candidate` ahead of the E5.0 modules, naming four files that did not exist; a test
    that hard-codes the word makes that kind of claim look verified. What must always
    hold is the pair below: the authority never widens, and the evidence is real.
    """
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    contract = next(c for c in registry["contracts"] if c["id"] == "nerva.work-run.v1")
    assert contract["authority"] == "delegated_execution_only"
    assert contract["status"] in checker.CONTRACT_STATES
    # `accepted` is the owner's word, never the program's.
    assert contract["status"] != "accepted"
    assert contract["evidence_paths"]
    for relative in contract["evidence_paths"]:
        assert (REPO / relative).is_file(), relative
    assert all(c["status"] in checker.CONTRACT_STATES for c in registry["contracts"])
    assert copy.deepcopy(registry) == registry


def test_write_refreshes_registry_mirror_and_canonical_json(fixture_repo: Path) -> None:
    registry_path = fixture_repo / checker.REGISTRY_RELATIVE
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    next(c for c in registry["contracts"] if c["id"] == "nerva.scenario.v1")["status"] = "candidate"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    assert checker.check_manifest(repo_root=fixture_repo).ok is False
    checker.write_document(repo_root=fixture_repo)
    report = checker.check_manifest(repo_root=fixture_repo)
    assert report.ok is True, report.errors
    data = _load(fixture_repo)
    assert data["contract_registry"]["statuses"]["nerva.scenario.v1"] == "candidate"
    assert data["evidence_snapshot"]["live_issue_state_verified_by_checker"] is False
    manifest_path = fixture_repo / checker.MANIFEST_RELATIVE
    first = manifest_path.read_bytes()
    checker.write_document(repo_root=fixture_repo)
    assert manifest_path.read_bytes() == first, "--write must be idempotent"
