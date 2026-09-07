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
    risks_path = REPO / "docs" / "nerva2" / "RISKS.md"
    registry_path = REPO / "docs" / "nerva2" / "CONTRACT_REGISTRY.json"
    baseline = baseline_path.read_text(encoding="utf-8")
    disposition = disposition_path.read_text(encoding="utf-8")
    dependencies = dependencies_path.read_text(encoding="utf-8")
    hybrid = hybrid_path.read_text(encoding="utf-8")
    risks = risks_path.read_text(encoding="utf-8")
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

    assert "8b8e64d599262f15334ce547b7adfa3c042a7a78" in risks
    assert "does **not** close E0" in risks
    assert "No risk below is marked `CLOSED`" in risks
    risk_ids = (
        "SEC-01",
        "SEC-02",
        "SEC-03",
        "SEC-04",
        "SEC-05",
        "SEC-06",
        "SEC-07",
        "PRIV-01",
        "PRIV-02",
        "PRIV-03",
        "PRIV-04",
        "DATA-01",
        "DATA-02",
        "DATA-03",
        "DATA-04",
        "MEM-01",
        "MEM-02",
        "MEM-03",
        "AUTO-01",
        "AUTO-02",
        "AUTO-03",
        "AUTO-04",
        "AUTO-05",
        "AUTO-06",
        "RES-01",
        "RES-02",
        "RES-03",
        "RES-04",
        "RES-05",
        "OPS-01",
        "OPS-02",
        "OPS-03",
        "OPS-04",
        "OPS-05",
        "PROD-01",
        "PROD-02",
        "PROD-03",
        "PROD-04",
        "PROD-05",
        "SUP-01",
    )
    for risk_id in risk_ids:
        assert risks.count(f"| `{risk_id}` |") == 1, risk_id
    for invariant in (
        "Ultron is the sole privileged-action authority",
        "Prediction is not consent",
        "Belief is not fact",
        "Simulation is not mutation",
        "Every material completion claim has environment-appropriate verification evidence",
        "Deletion/export covers derived state",
    ):
        assert invariant in risks
    assert "E0.3b must reconcile ORIZONT 27–33" in risks
    for relative in (
        "docs/THREAT_MODEL.md",
        "docs/PRIVACY.md",
        "docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md",
        "agents/core/kernel/__init__.py",
        "agents/core/autonomy/queue.py",
        "agents/core/autonomy/worker.py",
        "agents/core/security/audit.py",
        "agents/core/autonomy/audit_sink.py",
        "agents/core/data_purge.py",
        "agents/core/memory/bitemporal.py",
        "agents/core/cognition/memory.py",
        "agents/core/learning/background_review.py",
        "agents/core/autonomy/reflection.py",
        "agents/core/acquisition/runtime.py",
        "agents/core/observability/capability_registry.py",
        "agents/core/observability/reality_harness.py",
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
    assert "Cortex, Episodes, Howard, World Model, Experience, E12" in dependencies
    assert "Cortex, Howard, Night Shift, Reflection, World Model, E12" in dependencies
    assert "Episodes, Howard, Synapse, Experience, E12, human review" in dependencies
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
    contracts_by_owner = {}
    for contract in contracts:
        contracts_by_owner.setdefault(contract["owner"], []).append(contract)
    epic_owners = {
        "E1": "Cortex",
        "E2": "Atlas",
        "E3": "Episodes",
        "E4": "Howard",
        "E5": "Night Shift",
        "E6": "Reflection",
        "E7": "World Model",
        "E8": "Synapse",
        "E9": "Research Lab",
    }
    for dependent, blockers in delivery.items():
        if dependent == "E11":
            continue
        for blocker in blockers:
            if blocker == "E0":
                continue
            owner = epic_owners[blocker]
            assert any(
                dependent in contract["unblocks"]
                for contract in contracts_by_owner[owner]
            ), f"{blocker} ({owner}) does not expose a contract unblocking {dependent}"
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
        # The checker owns the vocabulary; the one state this gate refuses outright is
        # `accepted` — acceptance is the owner's, and the program may never self-assign it.
        assert contract["status"] in {"proposed", "candidate", "evolves_existing"}, contract["id"]
        assert contract["unblocks"]
        # A `candidate` claim must say what it is claiming and, like every other row,
        # point only at files that exist: a status is earned by shipped code.
        if contract["status"] == "candidate":
            assert contract.get("candidate_note", "").strip(), contract["id"]
        for relative in contract["evidence_paths"]:
            assert (REPO / relative).is_file(), f"{contract['id']}: {relative}"


def test_status_sync_check_runs_the_full_generated_artifact_gate():
    seen = []
    assert gate.check_status_sync(runner=lambda args: seen.append(args) or 0)["status"] == "PASS"
    assert seen == [
        [str(gate.REPO / "scripts" / "status_sync.py"), "--check", "--reuse-test-counts"]
    ]
    failed = gate.check_status_sync(runner=lambda args: 1)
    assert failed["status"] == "FAIL"
    assert "python scripts/status_sync.py --reuse-test-counts" in failed["detail"]


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


def test_companion_gate_row_runs_the_ci_gate_in_an_ephemeral_store():
    seen = []
    ok = gate.check_companion_gate(runner=lambda args: seen.append(list(args)) or 0)
    assert (ok["tier"], ok["name"], ok["status"]) == ("machine", "companion-eval", "PASS")
    (argv,) = seen
    assert argv[:3] == ["-m", "agents.core.observability.companion_eval", "--ci-gate"]
    assert "--store-root" in argv               # ephemeral — never the repo store
    assert gate.check_companion_gate(runner=lambda args: 1)["status"] == "FAIL"


def test_live_eval_evidence_owner_row_reads_recorded_lanes(tmp_path):
    import time as _time

    empty = gate.check_live_eval_evidence(store_root=tmp_path)
    assert (empty["tier"], empty["status"]) == ("owner", "FAIL")
    assert "--live-gate" in empty["detail"]     # actionable, never auto-passed

    lane = tmp_path / "datasets" / f"{gate.LIVE_EVAL_PREFIX}-owner-model"
    lane.mkdir(parents=True)
    now = _time.time()
    (lane / "runs.jsonl").write_text(
        json.dumps({"run_id": "abc", "ts": now - 3600, "version": 1,
                    "score": 0.8, "passed": 7, "total": 8, "cases": []}) + "\n",
        encoding="utf-8",
    )
    fresh = gate.check_live_eval_evidence(store_root=tmp_path, now=now)
    assert fresh["status"] == "PASS"
    assert f"{gate.LIVE_EVAL_PREFIX}-owner-model" in fresh["detail"]

    stale = gate.check_live_eval_evidence(
        store_root=tmp_path, now=now + (gate.LIVE_EVAL_STALE_DAYS + 2) * 86400
    )
    assert stale["status"] == "WARN"
    assert "stale" in stale["detail"]


def test_live_eval_evidence_ignores_the_deterministic_lane(tmp_path):
    lane = tmp_path / "datasets" / "companion_v1"
    lane.mkdir(parents=True)
    (lane / "runs.jsonl").write_text(
        json.dumps({"run_id": "abc", "ts": 1.0, "score": 1.0, "cases": []}) + "\n",
        encoding="utf-8",
    )
    result = gate.check_live_eval_evidence(store_root=tmp_path)
    assert result["status"] == "FAIL"           # golden-runner runs are not live evidence
