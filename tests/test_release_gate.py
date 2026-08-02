"""Tests for scripts/release_gate.py (H23.25 — the one-command RC readiness gate)."""

import importlib.util
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_gate", REPO / "scripts" / "release_gate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()

BACKLOG_OPEN = """
| A1 | ⭐B0 demo | ⬜ **the gate** |
| A2 | 72h soak | ⬜ |
| A7 | Recruit partners | ⬜ |
"""

BACKLOG_DONE = """
| A1 | ⭐B0 demo | ✅ 2026-08-01 |
| A2 | 72h soak | ✅ report attached |
| A7 | Recruit partners | ✅ two partners |
"""


def test_suite_check_pass_fail_and_skip_semantics():
    ok = gate.check_suite(skip=False, runner=lambda args: 0)
    assert (ok["status"], ok["name"]) == ("PASS", "offline-suite")
    assert gate.check_suite(skip=False, runner=lambda args: 3)["status"] == "FAIL"
    skipped = gate.check_suite(skip=True, runner=lambda args: 0)
    assert (skipped["status"], skipped["name"]) == ("WARN", "snapshot-guards")
    assert gate.check_suite(skip=True, runner=lambda args: 1)["status"] == "FAIL"


def test_code_complete_checks_release_tooling_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "REPO", tmp_path)
    missing = gate.check_code_complete()
    assert missing["tier"] == "code" and missing["status"] == "FAIL"
    for relative in gate.RELEASE_TOOLING:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("present", encoding="utf-8")
    complete = gate.check_code_complete()
    assert complete["status"] == "PASS"
    assert str(len(gate.RELEASE_TOOLING)) in complete["detail"]


def test_skip_tests_runs_the_snapshot_guard_subset():
    seen = []
    gate.check_suite(skip=True, runner=lambda args: seen.append(list(args)) or 0)
    assert seen == [gate.SNAPSHOT_GUARD_TESTS]


def test_fast_gate_includes_readiness_and_lifespan_guards():
    assert {
        "tests/test_capability_readiness_matrix.py",
        "tests/test_h2311_operability.py",
        "tests/test_lifespan_smoke.py",
    } <= set(gate.SNAPSHOT_GUARD_TESTS)


def test_status_sync_check_against_real_repo_is_clean():
    result = gate.check_status_sync()
    assert result["status"] == "PASS", result["detail"]

    baseline_path = REPO / "docs" / "nerva2" / "BASELINE.md"
    disposition_path = REPO / "docs" / "nerva2" / "REUSE_BUILD_RETIRE.md"
    dependencies_path = REPO / "docs" / "nerva2" / "DEPENDENCIES.md"
    hybrid_path = REPO / "docs" / "nerva2" / "HYBRID_COGNITION_BOUNDARY.md"
    registry_path = REPO / "docs" / "nerva2" / "CONTRACT_REGISTRY.json"
    baseline = baseline_path.read_text(encoding="utf-8")
    disposition = disposition_path.read_text(encoding="utf-8")
    dependencies = dependencies_path.read_text(encoding="utf-8")
    hybrid = hybrid_path.read_text(encoding="utf-8")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert "616f4d3e348675d56f0f600cca2d622b58ded804" in baseline
    assert "does **not** close E0" in baseline
    assert "Remaining E0 work" in baseline
    for state in ("`LIVE`", "`GATED`", "`SEAM`", "`STUB`", "`MIXED`"):
        assert state in baseline
    for decision in ("`REUSE`", "`INTEGRATE`", "`BUILD`", "`REFACTOR`", "`RETIRE`"):
        assert decision in disposition
    for relative in (
        "agents/core/orchestrator.py",
        "agents/core/agent_runtime.py",
        "agents/core/kernel/__init__.py",
        "agents/core/autonomy/observer.py",
        "agents/core/observability/capability_registry.py",
        "agents/core/memory/bitemporal.py",
        "agents/core/cognition/memory.py",
        "agents/core/learning/background_review.py",
        "agents/core/acquisition/runtime.py",
        "agents/core/observability/eval.py",
    ):
        assert (REPO / relative).is_file(), relative

    assert "a2766a98d16be40389ca587c6677c9e5e5d6e270" in dependencies
    assert "E12 Hybrid Cognition" in dependencies
    assert "No model, agent, preference predictor, simulator, metacognitive controller" in dependencies
    assert "Cortex chooses a route; it cannot authorize" in dependencies
    assert "Simulation never mutates live Atlas" in dependencies
    assert "## 2. Delivery prerequisite DAG — acyclic" in dependencies
    assert "### 2.1 Runtime cognitive feedback graph — cycles expected" in dependencies
    assert "E0 Baseline + E1 Cortex + E2 Atlas + E3 Episodes + E6 Reflection" in dependencies
    assert "E4 Howard, E8 Synapse Skills SDK, E9 Research Lab and E12 Hybrid Cognition" in dependencies
    assert "E12 ──belief / metacognition only────> Cortex / World Model / Research Lab" in dependencies
    assert "E12 advisory outputs ─" not in dependencies
    assert "E12 has no privileged-action authority" in hybrid
    assert "A probability is never promoted to fact" in hybrid
    assert "Any external effect ──> Ultron / Action Kernel" in hybrid

    assert registry["schema_version"] == 1
    assert registry["program_issue"] == 757
    assert registry["epic_issue"] == 758
    delivery = registry["delivery_dependencies"]
    assert delivery["E5"] == ["E0", "E1", "E2", "E3", "E6"]
    assert delivery["E12"] == ["E0", "E1", "E2", "E3", "E6", "E9"]
    assert {"E4", "E8", "E9", "E12"}.isdisjoint(delivery["E5"])
    known_epics = {"E0", *delivery}
    assert all(set(blockers) <= known_epics for blockers in delivery.values())

    visiting = set()
    visited = set()

    def visit(epic):
        assert epic not in visiting, f"cycle in delivery dependencies at {epic}"
        if epic in visited:
            return
        visiting.add(epic)
        for blocker in delivery.get(epic, []):
            visit(blocker)
        visiting.remove(epic)
        visited.add(epic)

    for epic in delivery:
        visit(epic)

    feedback = registry["runtime_feedback_edges"]
    assert ["E12", "E1"] in feedback
    assert ["E12", "E7"] in feedback
    assert ["E12", "E9"] in feedback
    assert all(edge[0] in known_epics and edge[1] in known_epics for edge in feedback)

    boundaries = registry["epic_boundaries"]
    assert boundaries == [
        {
            "id": "E12",
            "issue": 773,
            "owner": "Hybrid Cognition Lab",
            "status": "discovery",
            "depends_on": ["E0", "E1", "E2", "E3", "E6", "E9"],
            "authority": "advisory_only",
            "can_authorize_actions": False,
            "can_mutate_live_state": False,
            "boundary_path": "docs/nerva2/HYBRID_COGNITION_BOUNDARY.md",
        }
    ]
    contracts = registry["contracts"]
    ids = [contract["id"] for contract in contracts]
    assert len(ids) == len(set(ids))
    assert {
        "nerva.observation.v1",
        "nerva.atlas.snapshot.v1",
        "nerva.capability.v1",
        "nerva.decision.v1",
        "nerva.action.v1",
        "nerva.episode.v1",
        "nerva.lesson.v1",
        "nerva.preference.v1",
        "nerva.work-run.v1",
        "nerva.scenario.v1",
        "nerva.benchmark.v1",
        "nerva.evidence.v1",
    } == set(ids)
    assert [
        contract["id"]
        for contract in contracts
        if contract["authority"] == "privileged_action"
    ] == ["nerva.action.v1"]
    assert {
        "Atlas",
        "Synapse",
        "Cortex",
        "Ultron",
        "Episodes",
        "Reflection",
        "Howard",
        "Night Shift",
        "World Model",
        "Research Lab",
        "Verification Fabric",
    } <= {contract["owner"] for contract in contracts}
    by_id = {contract["id"]: contract for contract in contracts}
    for contract_id in (
        "nerva.atlas.snapshot.v1",
        "nerva.decision.v1",
        "nerva.episode.v1",
        "nerva.lesson.v1",
        "nerva.benchmark.v1",
        "nerva.evidence.v1",
    ):
        assert "E12" in by_id[contract_id]["unblocks"], contract_id
    for contract in contracts:
        assert contract["status"] in {"proposed", "evolves_existing"}
        assert contract["unblocks"]
        for relative in contract["evidence_paths"]:
            assert (REPO / relative).is_file(), f"{contract['id']}: {relative}"


def test_status_sync_check_runs_the_full_generated_artifact_gate():
    seen = []
    assert gate.check_status_sync(runner=lambda args: seen.append(args) or 0)["status"] == "PASS"
    assert seen == [[str(gate.REPO / "scripts" / "status_sync.py"), "--check", "--reuse-js-counts"]]
    assert gate.check_status_sync(runner=lambda args: 1)["status"] == "FAIL"


def test_doc_links_real_canon_is_clean_and_broken_is_reported(tmp_path, monkeypatch):
    clean = gate.check_doc_links()
    assert clean["status"] == "PASS", clean["detail"]
    doc = tmp_path / "X.md"
    doc.write_text("see [gone](missing/nowhere.md)", encoding="utf-8")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    broken = gate.check_doc_links(files=["X.md"])
    assert broken["status"] == "FAIL"
    assert "nowhere.md" in broken["detail"]


def test_version_tag_matrix():
    version = gate.read_version()
    assert version
    assert gate.check_version_tag(tag_reader=lambda: "")["status"] == "WARN"
    assert gate.check_version_tag(tag_reader=lambda: f"v{version}")["status"] == "PASS"
    assert gate.check_version_tag(tag_reader=lambda: "v0.0.1")["status"] == "WARN"


def test_owner_rows_never_pass_without_ledger_tick(tmp_path):
    results = gate.check_owner_and_market(
        backlog_text=BACKLOG_OPEN, feedback_db=tmp_path / "absent.db", soak_reports=[]
    )
    by_name = {result["name"]: result for result in results}
    assert by_name["b0-manual-signoff"]["status"] == "FAIL"
    assert by_name["72h-soak"]["status"] == "FAIL"
    assert by_name["design-partners"]["status"] == "FAIL"
    assert by_name["partner-feedback"]["status"] == "FAIL"
    assert all(result["tier"] in ("owner", "market") for result in results)


def test_owner_rows_pass_only_from_ledger_and_soak_needs_evidence(tmp_path):
    results = gate.check_owner_and_market(
        backlog_text=BACKLOG_DONE, feedback_db=tmp_path / "absent.db", soak_reports=[]
    )
    by_name = {result["name"]: result for result in results}
    assert by_name["b0-manual-signoff"]["status"] == "PASS"
    assert by_name["72h-soak"]["status"] == "WARN"
    with_evidence = gate.check_owner_and_market(
        backlog_text=BACKLOG_DONE,
        feedback_db=tmp_path / "absent.db",
        soak_reports=[tmp_path / "2026-08-04-soak-report.md"],
    )
    assert {result["name"]: result for result in with_evidence}["72h-soak"]["status"] == "PASS"


def test_partner_feedback_counts_real_rows(tmp_path):
    db = tmp_path / "feedback.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE feedback (id INTEGER PRIMARY KEY, ts TEXT, kind TEXT,"
            " score INTEGER, message TEXT, session_id TEXT)"
        )
        conn.execute("INSERT INTO feedback (ts, kind, score) VALUES ('t', 'nps', 9)")
    results = gate.check_owner_and_market(
        backlog_text=BACKLOG_OPEN, feedback_db=db, soak_reports=[]
    )
    row = {result["name"]: result for result in results}["partner-feedback"]
    assert row["status"] == "PASS"
    assert "1 feedback record" in row["detail"]


def test_render_orders_tiers_and_exit_verdict():
    results = [
        {"tier": "code", "name": "release-tooling", "status": "PASS", "detail": "present"},
        {"tier": "machine", "name": "offline-suite", "status": "PASS", "detail": "ok"},
        {"tier": "owner", "name": "b0-manual-signoff", "status": "FAIL", "detail": "missing"},
        {"tier": "market", "name": "design-partners", "status": "FAIL", "detail": "missing"},
    ]
    text = gate.render(results)
    assert text.index("code-complete") < text.index("machine-verified")
    assert text.index("machine-verified") < text.index("owner-verified")
    assert text.index("owner-verified") < text.index("market-verified")
    assert "NOT READY" in text and "2 FAIL" in text


def test_lane_a_parser_reads_the_real_backlog():
    rows = gate.lane_a_status((REPO / "BACKLOG.md").read_text(encoding="utf-8"))
    assert {"A1", "A2", "A7"} <= set(rows)
