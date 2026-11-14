"""Tests for `scripts/bench_nerva_differentiators.py` and committed benchmark artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agents.core import settings_db
from scripts import bench_nerva_differentiators as bench
from tests.test_doc_reference_integrity import REPO, _candidate_paths


@pytest.fixture(scope="module")
def measured_report() -> dict[str, Any]:
    """Execute the full 5-subsystem benchmark suite once for module assertions."""
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
    assert "_lww_order_manifests" in measured_report["honest_scope_note"]
    assert "DirectorySyncTransport.fetch_manifests()" in measured_report["honest_scope_note"]
    assert measured_report["summary"] == {
        "total_benchmarks": 5,
        "passed_benchmarks": 5,
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
    assert (
        dm["lww_ordering_source"]
        == "benchmark_harness__lww_order_manifests_over_e2e_envelope_ts_device"
    )
    assert dm["lww_arrival_permutations_tested"] == 6
    assert dm["nerva_lww_convergence_rate"] == 1.0
    assert dm["baseline_arrival_order_convergence_rate"] < 1.0


def test_committed_benchmark_artifacts_and_doc_reference_integrity() -> None:
    assert bench.DEFAULT_JSON_OUT.is_file()
    assert bench.DEFAULT_MD_OUT.is_file()
    assert bench.main(["--check"]) == 0

    md_text = bench.DEFAULT_MD_OUT.read_text(encoding="utf-8")
    assert "_lww_order_manifests" in md_text
    assert "DirectorySyncTransport" in md_text
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
    # Avoid repeating the 2s timeout sleep inside this CLI guard unit test by reusing measured_report.
    monkeypatch.setattr(bench, "run_all_benchmarks", lambda: json.loads(json.dumps(measured_report)))

    json_out = tmp_path / "out" / "report.json"
    md_out = tmp_path / "out" / "report.md"

    # Missing files fail --check.
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1

    # Generating files and immediately running --check succeeds.
    assert bench.main(["--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 0

    # Tampering with a deterministic metric fails --check.
    tampered = json.loads(json_out.read_text(encoding="utf-8"))
    tampered["benchmarks"][1]["deterministic_metrics"]["nerva_unconsented_cloud_calls_leaked"] = 1
    json_out.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1

    # Restore valid JSON, then inject a broken relative Markdown link -> fails --check.
    json_out.write_text(json.dumps(measured_report, indent=2), encoding="utf-8")
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    md_out.write_text(
        md_out.read_text(encoding="utf-8") + "\nSee [dangling](../does-not-exist-xyz.md).\n",
        encoding="utf-8",
    )
    assert bench.main(["--check", "--json-out", str(json_out), "--md-out", str(md_out)]) == 1
