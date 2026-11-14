"""Tests for `scripts/bench_nerva_differentiators.py`, `cost_cascade.py`, and benchmark artifacts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.core import settings_db
from agents.core.llm.cost_cascade import (
    AdaptiveCostCascade,
    CascadeConfigError,
    CascadePolicy,
    CascadeSessionBudget,
    clear_cascade_runs,
    recent_cascade_runs,
)
from agents.core.llm.data_handling import DataHandlingRefused, check_physical_request
from scripts import bench_nerva_differentiators as bench
from tests.test_doc_reference_integrity import REPO, _candidate_paths


@pytest.fixture(scope="module")
def measured_report() -> dict[str, Any]:
    """Execute the full 6-subsystem benchmark suite once for module assertions."""
    before_db = settings_db.DB_PATH
    before_home = os.environ.get("JARVIS_HOME")
    report = bench.run_all_benchmarks()
    assert before_db == settings_db.DB_PATH
    assert os.environ.get("JARVIS_HOME") == before_home
    return report


def test_suite_metadata_and_honest_scope_invariants(measured_report: dict[str, Any]) -> None:
    assert measured_report["schema_version"] == bench.SCHEMA_VERSION
    assert measured_report["suite_spec_sha256"] == bench.suite_spec_digest()
    assert measured_report["execution_mode"] == "hermetic_in_process"
    assert measured_report["live_network_llm_calls"] == 0
    assert "0 live network LLM calls" in measured_report["honest_scope_note"]
    assert "E2ESync.pull_state()" in measured_report["honest_scope_note"]
    assert measured_report["summary"] == {
        "total_benchmarks": 6,
        "passed_benchmarks": 6,
        "all_passed": True,
    }


def test_benchmark_1_resilient_hybrid_committee_metrics(measured_report: dict[str, Any]) -> None:
    b1 = next(b for b in measured_report["benchmarks"] if b["id"] == "B1_moa_resilient_hybrid_committee")
    assert b1["passed"] is True
    dm = b1["deterministic_metrics"]
    tt = b1["timing_telemetry"]

    assert dm["proposer_count"] == 4
    assert dm["min_quorum"] == 3
    assert dm["nerva_faulted_quorum_completion_rate"] == 1.0
    assert dm["baseline_sequential_completion_rate"] == 0.0
    assert dm["timeout_cap_enforced"] is True
    assert dm["max_tokens_budget_enforced"] is True
    assert dm["below_quorum_fail_closed"] is True
    assert tt["steady_state_parallel_speedup"] >= 2.5
    assert tt["overall_wall_speedup_vs_sequential_baseline"] >= 1.8


def test_benchmark_2_h513_controllable_cloud_privacy_metrics(measured_report: dict[str, Any]) -> None:
    b2 = next(b for b in measured_report["benchmarks"] if b["id"] == "B2_h513_controllable_cloud_privacy")
    assert b2["passed"] is True
    dm = b2["deterministic_metrics"]

    assert dm["sensitive_prompts_tested"] == 4
    assert dm["nerva_unconsented_cloud_calls_leaked"] == 0
    assert dm["nerva_unconsented_cloud_tokens_leaked"] == 0
    assert dm["nerva_policy_block_accuracy"] == 1.0
    assert dm["nerva_local_grounded_synthesis_rate"] == 1.0
    assert dm["strict_local_specialist_blocked_hybrid"] is True
    assert dm["baseline_unconsented_cloud_calls_leaked"] == 4
    assert dm["baseline_unconsented_cloud_tokens_leaked"] > 0


def test_benchmark_3_h657_room_failover_and_fencing_metrics(measured_report: dict[str, Any]) -> None:
    b3 = next(b for b in measured_report["benchmarks"] if b["id"] == "B3_h657_surviving_host_room_failover")
    assert b3["passed"] is True
    dm = b3["deterministic_metrics"]
    tt = b3["timing_telemetry"]

    assert dm["replicated_entries_expected"] == 12
    assert dm["lost_replicated_entries"] == 0
    assert dm["post_failover_entries_committed"] == 3
    assert dm["idempotent_duplicate_entries_skipped"] == 12
    assert dm["nerva_stale_epoch_write_rejection_rate"] == 1.0
    assert dm["stale_epoch_replication_rejected"] is True
    assert dm["sequence_gap_rejected"] is True
    assert dm["hash_chain_tamper_rejected"] is True
    assert dm["forged_hmac_fencing_proof_rejected"] is True
    assert 0.0 < tt["failover_promote_latency_ms"] < 50.0


def test_benchmark_4_h086_identity_scoped_browser_broker_metrics(measured_report: dict[str, Any]) -> None:
    b4 = next(b for b in measured_report["benchmarks"] if b["id"] == "B4_h086_identity_scoped_browser_broker")
    assert b4["passed"] is True
    dm = b4["deterministic_metrics"]

    assert dm["ssrf_attack_vectors_tested"] == 8
    assert dm["nerva_ssrf_block_rate"] == 1.0
    assert dm["cross_principal_attacks_tested"] == 6
    assert dm["nerva_cross_principal_isolation_rate"] == 1.0
    assert dm["ticket_replay_attempts_tested"] == 6
    assert dm["nerva_ticket_replay_rejection_rate"] == 1.0
    assert dm["https_transport_and_sha256_verified"] is True


def test_benchmark_5_h040_secret_stripped_e2e_sync_metrics(measured_report: dict[str, Any]) -> None:
    b5 = next(b for b in measured_report["benchmarks"] if b["id"] == "B5_h040_secret_stripped_e2e_sync")
    assert b5["passed"] is True
    dm = b5["deterministic_metrics"]

    assert dm["cipher"] == "fernet-aes128-cbc-hmac-sha256"
    assert dm["kdf"] == "pbkdf2-hmac-sha256-390000"
    assert dm["nerva_leaked_secret_keys_in_envelope"] == 0
    assert dm["nerva_plaintext_tokens_in_wire_manifest"] == 0
    assert dm["plaintext_envelope_field_rejected"] is True
    assert dm["hostile_skill_injection_quarantined"] is True
    assert dm["ciphertext_bitflip_trials"] == 8
    assert dm["nerva_authenticated_tamper_rejection_rate"] == 1.0
    assert dm["lww_ordering_source"] == "production_e2e_sync_pull_state_sealed_fernet_ts_inner_device"
    assert dm["plaintext_envelope_ts_forgery_resisted"] is True
    assert dm["lww_arrival_permutations_tested"] == 6
    assert dm["nerva_lww_convergence_rate"] == 1.0
    assert dm["baseline_arrival_order_convergence_rate"] < 1.0


def test_benchmark_6_governed_adaptive_cost_sla_cascade_metrics(measured_report: dict[str, Any]) -> None:
    b6 = next(
        b for b in measured_report["benchmarks"] if b["id"] == "B6_governed_adaptive_cost_sla_cascade"
    )
    assert b6["passed"] is True
    dm = b6["deterministic_metrics"]

    assert dm["total_turns"] == 20
    assert dm["nerva_completed_turns"] == 20
    assert dm["nerva_completion_rate"] == 1.0
    assert dm["nerva_consented_cloud_escalations"] == 3
    assert dm["nerva_local_zero_cost_turns"] == 17
    assert dm["nerva_usd_cost_reduction_ratio"] >= 0.60
    assert dm["nerva_budget_overruns"] == 0
    assert dm["nerva_usd_cap_enforcement_rate"] == 1.0
    assert dm["session_final_spent_usd"] <= dm["max_session_usd_cap"]
    assert dm["nerva_unconsented_cloud_escalations"] == 0
    assert dm["nerva_governance_block_accuracy"] == 1.0
    assert dm["sla_timeout_graceful_local_fallback"] is True
    assert dm["usd_accounting"] == "estimated_via_cost_estimator_and_tokenizer_not_provider_reported"
    assert dm["live_routing_wired"] is False


class _RevokedMidFlightCloud:
    """Cloud backend whose H513 consent passes pre-flight but is revoked at the physical request."""

    def __init__(self) -> None:
        self.consent_checks = 0
        self.sent = 0

    def authorize_data_handling(self, *, actual_use: bool = True) -> dict[str, Any]:
        self.consent_checks += 1
        if self.consent_checks > 1:
            raise DataHandlingRefused("consent revoked between pre-flight and physical request")
        return {"acknowledged": True}

    async def generate(self, model: str, prompt: str, **_kwargs: Any) -> str:
        # Real HTTP adapters call this from their request hook before any byte leaves the host.
        await check_physical_request(SimpleNamespace(method="POST"))
        self.sent += 1
        return "cloud reply that must never be produced"


def test_adaptive_cost_cascade_rechecks_h513_per_physical_request() -> None:
    router, _loc, _consented, _unconsented = bench._build_cascade_fixture()
    cloud = _RevokedMidFlightCloud()
    budget = CascadeSessionBudget(0.05, session_id="recheck-sess")
    cascade = AdaptiveCostCascade(
        router=router,
        agent_id="jarvis",
        policy=CascadePolicy(max_turn_usd=0.05, max_session_usd=0.05),
        session_budget=budget,
        cloud_binding=(cloud, "claude-opus-4-7", "claude"),
    )
    res = asyncio.run(cascade.execute_turn("[NEEDS_ESCALATION] Check revoked consent.", max_tokens=128))
    assert cloud.consent_checks == 2
    assert cloud.sent == 0
    assert res.escalated_to_cloud is False
    assert res.block_reason == "cloud_h513_recheck_refused"
    assert res.usd_cost == 0.0
    assert res.degraded_gracefully is True
    snap = budget.snapshot()
    assert snap["reserved_usd"] == 0.0 and snap["spent_usd"] == 0.0
    assert snap["policy_blocks"] == 1


def test_adaptive_cost_cascade_unit_guards_and_prompt_free_telemetry() -> None:
    with pytest.raises(CascadeConfigError):
        CascadePolicy(max_turn_usd=-0.01)
    with pytest.raises(CascadeConfigError):
        CascadePolicy(min_local_confidence=1.5)
    with pytest.raises(CascadeConfigError):
        CascadePolicy(local_sla_timeout_s=0.0)

    budget = CascadeSessionBudget(0.010, session_id="unit-sess")
    ok1, reason1 = budget.try_reserve(0.006, max_turn_usd=0.008)
    assert ok1 is True and reason1 is None
    # Concurrent second reservation before settlement cannot breach max_session_usd.
    ok2, reason2 = budget.try_reserve(0.006, max_turn_usd=0.008)
    assert ok2 is False and reason2 == "session_usd_cap_exceeded"
    budget.settle_cloud(0.006, 0.002)
    snap = budget.snapshot()
    assert snap["spent_usd"] == 0.002
    assert snap["reserved_usd"] == 0.0
    assert snap["budget_blocks"] == 1

    # Unpriced cloud models (ADV-078) are blocked fail-closed and degrade to approved local slot.
    clear_cascade_runs()
    router, _loc, consented_cloud, _unconsented = bench._build_cascade_fixture()
    cascade = AdaptiveCostCascade(
        router=router,
        agent_id="jarvis",
        policy=CascadePolicy(max_turn_usd=0.05, max_session_usd=0.20),
        cloud_binding=(consented_cloud, "unpriced-custom-model-v9", "claude"),
        approved_models_override=("google/gemma-4-12b", "unpriced-custom-model-v9"),
    )
    secret_marker = "CONFIDENTIAL_MARKER_DO_NOT_RECORD_7788"
    out = asyncio.run(
        cascade.generate(
            "cascade:auto",
            f"[NEEDS_ESCALATION] Verify {secret_marker}",
            max_tokens=128,
        )
    )
    assert "google/gemma-4-12b" in out
    assert cascade.last_turn_result is not None
    assert cascade.last_turn_result.block_reason == "unpriced_cloud_model"
    assert cascade.last_turn_result.degraded_gracefully is True
    assert cascade.last_turn_result.usd_cost == 0.0

    runs_json = json.dumps(recent_cascade_runs())
    assert secret_marker not in runs_json
    clear_cascade_runs()


def test_committed_benchmark_artifacts_and_doc_reference_integrity() -> None:
    assert bench.DEFAULT_JSON_OUT.is_file()
    assert bench.DEFAULT_MD_OUT.is_file()
    assert bench.main(["--check"]) == 0

    md_text = bench.DEFAULT_MD_OUT.read_text(encoding="utf-8")
    assert "E2ESync.pull_state()" in md_text
    assert "cost_cascade.py" in md_text
    base = bench.DEFAULT_MD_OUT.parent
    missing: list[str] = []
    for line_no, target in _candidate_paths(md_text):
        if "*" in target or not target:
            continue
        resolved = (base / target) if not (REPO / target).exists() else (REPO / target)
        if not resolved.exists():
            missing.append(f"{bench.DEFAULT_MD_OUT.name}:{line_no} -> {target}")
    assert not missing, f"benchmark markdown references missing paths: {missing}"


def test_cli_write_and_check_reproducibility_guards(
    tmp_path: Path,
    measured_report: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bench, "run_all_benchmarks", lambda: json.loads(json.dumps(measured_report)))

    json_out = tmp_path / "out" / "report.json"
    md_out = tmp_path / "out" / "report.md"

    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1
    assert bench.main(["--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 0

    tampered = json.loads(json_out.read_text(encoding="utf-8"))
    tampered["benchmarks"][1]["deterministic_metrics"]["nerva_unconsented_cloud_calls_leaked"] = 1
    json_out.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1

    json_out.write_text(json.dumps(measured_report, indent=2), encoding="utf-8")
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    md_out.write_text(
        md_out.read_text(encoding="utf-8") + "\nSee [dangling](../does-not-exist-xyz.md).\n",
        encoding="utf-8",
    )
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1
