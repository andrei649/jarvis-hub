"""E11.0 — typed ``nerva.evidence.v1`` receipts, the receipts store and the gate consumer."""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for entry in (str(REPO), str(REPO / "agents")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agents.core.observability import evidence_receipt as er  # noqa: E402
from agents.core.observability.evidence_receipt import (  # noqa: E402
    EvidenceReceipt,
    EvidenceRef,
    EvidenceValue,
    ReceiptEnvironmentRefused,
    ReceiptStore,
    evaluate_release_rows,
    from_benchmark_run,
    from_reality_run,
    validate_receipt_environment,
)

CI = {"GITHUB_ACTIONS": "true"}
OWNER_BOX: dict[str, str] = {}
NOW = 1_800_000_000.0


def _receipt(**overrides) -> EvidenceReceipt:
    fields = {
        "claim": "restore drill restored a full install",
        "target": EvidenceRef("drill", "restore"),
        "expected_state": "restored_and_ready",
        "observed_state": "restored_and_ready",
        "method": "drill",
        "environment": "owner_live",
        "timestamp": NOW,
        "confidence": EvidenceValue("measured", 1.0, "restore_drill.hashes"),
        "run_status": "completed",
        "limitations": ("single host",),
        "environ": OWNER_BOX,
    }
    fields.update(overrides)
    return EvidenceReceipt.mint(**fields)


# ----------------------------------------------------------------- environment (OPS-03)


def test_ci_cannot_mint_owner_live_receipts():
    with pytest.raises(ReceiptEnvironmentRefused) as refused:
        _receipt(environ=CI)
    assert refused.value.reason == "ci_cannot_mint_owner_live"
    with pytest.raises(ReceiptEnvironmentRefused):
        validate_receipt_environment("owner_live", environ={"CI": "1"})
    # CI may still record what it actually is.
    assert _receipt(environment="ci", environ=CI).environment == "ci"
    assert validate_receipt_environment("local", environ=CI) == "local"
    with pytest.raises(ValueError, match="not recognized"):
        validate_receipt_environment("prod", environ=OWNER_BOX)


def test_process_environment_is_the_default_guard(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert er.detect_environment() == "ci"
    with pytest.raises(ReceiptEnvironmentRefused):
        _receipt(environ=None)
    monkeypatch.delenv("GITHUB_ACTIONS")
    monkeypatch.delenv("CI", raising=False)
    assert er.detect_environment() == "local"
    assert _receipt(environ=None).environment == "owner_live"


def test_store_refuses_owner_live_append_under_ci(tmp_path):
    store = ReceiptStore(tmp_path)
    receipt = _receipt()
    with pytest.raises(ReceiptEnvironmentRefused):
        store.append(receipt, environ=CI)
    assert not store.path.exists()
    assert store.append(receipt, environ=OWNER_BOX) == receipt.fingerprint


def test_hermetic_tests_never_claim_owner_hardware():
    with pytest.raises(ValueError, match="never owner-hardware proof"):
        _receipt(method="hermetic_test")
    assert _receipt(method="hermetic_test", environment="local").environment == "local"
    with pytest.raises(ValueError, match="environment=owner_live"):
        _receipt(method="owner_live_run", environment="local")


# ----------------------------------------------------------------- contract shape


def test_authority_is_pinned_and_forged_flags_are_rejected():
    receipt = _receipt()
    assert receipt.schema == "nerva.evidence.v1"
    assert receipt.authority == "claim_evidence_only"
    assert (receipt.can_authorize, receipt.can_execute, receipt.can_mark_complete) == (
        False,
        False,
        False,
    )
    with pytest.raises(TypeError):
        EvidenceReceipt.mint(can_authorize=True, **{})  # authority flags are not init fields
    payload = json.loads(receipt.to_json())
    assert EvidenceReceipt.from_payload(payload) == receipt
    for name, forged in (
        ("can_authorize", True),
        ("can_execute", 1),
        ("can_mark_complete", "false"),
        ("authority", "privileged_action"),
        ("schema", "nerva.action.v1"),
    ):
        with pytest.raises(ValueError, match=f"forged {name}"):
            EvidenceReceipt.from_payload({**payload, name: forged})
    with pytest.raises(ValueError, match="unknown keys"):
        EvidenceReceipt.from_payload({**payload, "approved": True})
    with pytest.raises(ValueError, match="epoch"):
        EvidenceReceipt.from_payload({**payload, "timestamp": True})


def test_limitations_and_source_artifacts_are_preserved_round_trip():
    artifact = EvidenceRef("file", "docs/research/soak.md", integrity_sha256="a" * 64)
    receipt = _receipt(
        limitations=("owner_live_not_exercised:camera.snapshot", "no restart during soak"),
        source_artifacts=(artifact,),
    )
    restored = EvidenceReceipt.from_payload(json.loads(receipt.to_json()))
    assert restored.limitations == (
        "owner_live_not_exercised:camera.snapshot",
        "no restart during soak",
    )
    assert restored.source_artifacts == (artifact,)
    assert restored.source_artifacts[0].integrity_sha256 == "a" * 64
    with pytest.raises(ValueError, match="sha256"):
        EvidenceRef("file", "x", integrity_sha256="not-a-digest")
    with pytest.raises(ValueError, match="single line"):
        _receipt(limitations=("two\nlines",))


def test_fingerprint_is_stable_and_content_addressed():
    first, second = _receipt(), _receipt()
    assert first.fingerprint == second.fingerprint == first.receipt_id
    assert len(first.fingerprint) == 64
    assert _receipt(limitations=("different",)).fingerprint != first.fingerprint
    assert _receipt(timestamp=NOW + 1).fingerprint != first.fingerprint
    # Pinned: the canonical payload of a fixed receipt must not drift silently.
    assert first.fingerprint == EvidenceReceipt.from_payload(
        json.loads(first.to_json())
    ).fingerprint
    assert json.loads(first.to_json())["authority"] == "claim_evidence_only"


def test_green_is_not_success():
    # A completed run whose observation disagrees with the expectation is not verified.
    run_green = _receipt(observed_state="run_completed_no_backup_verified")
    assert run_green.run_status == "completed" and run_green.verified is False
    assert run_green.is_owner_live_proof is False
    with pytest.raises(ValueError, match="observed_state differs"):
        replace(run_green, verified=True)
    with pytest.raises(ValueError, match="skipped run cannot verify"):
        replace(_receipt(), run_status="skipped")
    assert _receipt(run_status="failed").verified is False
    with pytest.raises(ValueError, match="verified must be a bool"):
        replace(_receipt(), verified=1)
    with pytest.raises(ValueError, match="\\[0, 1\\]"):
        _receipt(confidence=EvidenceValue("measured", 7, "x"))
    with pytest.raises(ValueError, match="not recognized"):
        _receipt(method="vibes")


# ----------------------------------------------------------------- adapters


def _reality_record(*, lane="scheduled", off_box=("camera.snapshot",), passed=3, total=4):
    return {
        "schema": "nerva.reality.run.v1",
        "harness_id": "reality-v1",
        "started_at": "2026-09-01T02:00:00+00:00",
        "finished_at": "2026-09-01T02:05:00+00:00",
        "revision": "abc",
        "runner_id": "gh",
        "lane": lane,
        "live_enabled": False,
        "totals": {
            "passed": passed,
            "total": total,
            "skipped": 0,
            "cases": total,
            "expected_seam_failures": 0,
            "owner_live_not_exercised": len(off_box),
        },
        "expected_seam_failures": [],
        "owner_live_not_exercised": list(off_box),
        "promotion_scope": "in_process_only",
        "durable_promotion": False,
        "promoted_in_process": [],
        "cases": [
            {"capability_id": "voice.tts", "name": "tts", "skipped": False, "passed": True,
             "detail": "", "metadata": {}, "live": False},
            {"capability_id": "camera.snapshot", "name": "cam", "skipped": False,
             "passed": False, "detail": "", "metadata": {"reason": "owner_live_disabled"},
             "live": True},
        ],
    }


def test_from_reality_run_keeps_off_box_cases_as_limitations_and_never_owner_live():
    receipt = from_reality_run(_reality_record(), environ=CI)
    assert receipt.environment == "ci"
    assert receipt.method == "reality_harness"
    assert receipt.verified is True  # excused verdict — a green transcript...
    assert receipt.is_owner_live_proof is False  # ...that is not owner-hardware proof
    assert "owner_live_not_exercised:camera.snapshot" in receipt.limitations
    assert "promotion_scope:in_process_only" in receipt.limitations
    assert receipt.confidence == EvidenceValue("measured", 0.75, "reality_evidence.totals")
    assert receipt.source_artifacts[0].kind == "reality_run"
    assert receipt.source_artifacts[0].integrity_sha256 == er._digest(_reality_record())
    assert receipt.timestamp == datetime(2026, 9, 1, 2, 5, tzinfo=UTC).timestamp()
    red = from_reality_run(_reality_record(off_box=(), passed=2), environ=CI)
    assert red.verified is False and red.observed_state == "unexcused_failures:2"
    assert from_reality_run(_reality_record(lane="local"), environ=OWNER_BOX).environment == "local"


def test_from_reality_run_per_capability_receipts():
    record = _reality_record()
    ok = from_reality_run(record, capability_id="voice.tts", environ=CI)
    assert (ok.target.ref_id, ok.observed_state, ok.verified) == ("voice.tts", "passed", True)
    cam = from_reality_run(record, capability_id="camera.snapshot", environ=CI)
    assert cam.observed_state == "owner_live_not_exercised"
    assert cam.run_status == "not_run" and cam.verified is False
    assert any(item.startswith("owner_live_not_exercised") for item in cam.limitations)
    with pytest.raises(ValueError, match="no case"):
        from_reality_run(record, capability_id="ghost", environ=CI)


def test_from_benchmark_run_is_evaluation_only_evidence():
    from agents.core.observability.benchmark import BenchmarkRun
    from tests import _nerva_benchmark_e9_0_base as base

    run = BenchmarkRun(
        suite_name="stable-shape",
        suite_version=1,
        lane="ci",
        run_id="run-one",
        started_at=base._FIXED_TS,
        finished_at=base._FIXED_TS,
        source_revision=base._REVISION,
        candidate_id="current-router",
        baseline_id=None,
        results=(base._result_fixture(),),
    )
    receipt = from_benchmark_run(run, environ=CI)
    assert receipt.environment == "ci" and receipt.verified is True
    assert receipt.target == EvidenceRef("benchmark_suite", "stable-shape", source_schema="nerva.benchmark.v1")
    assert receipt.confidence == EvidenceValue("measured", 1.0, "benchmark.summary.quality_mean")
    assert "authority:evaluation_only" in receipt.limitations
    assert "not_owner_live_proof" in receipt.limitations
    assert receipt.source_artifacts[0] == EvidenceRef(
        "benchmark_run",
        "run-one",
        integrity_sha256=er.hashlib.sha256(run.to_json().encode("utf-8")).hexdigest(),
        source_schema="nerva.benchmark.v1",
    )
    assert receipt.is_owner_live_proof is False


# ----------------------------------------------------------------- store


def test_store_appends_dedupes_and_tolerates_torn_lines(tmp_path):
    store = ReceiptStore(tmp_path)
    receipt = _receipt()
    assert store.append(receipt, environ=OWNER_BOX) == receipt.fingerprint
    assert store.append(receipt, environ=OWNER_BOX) == receipt.fingerprint
    assert store.path == tmp_path / "receipts.jsonl"
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == 1
    other = _receipt(target=EvidenceRef("soak", "72h"), method="soak", claim="72h soak held")
    store.append(other, environ=OWNER_BOX)
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write('{"claim": "torn')
        handle.write("\n")
        forged = json.loads(receipt.to_json())
        forged["can_mark_complete"] = True
        handle.write(json.dumps(forged) + "\n")
    loaded = store.load()
    assert [item.fingerprint for item in loaded.receipts] == [receipt.fingerprint, other.fingerprint]
    assert loaded.rejected == 2
    assert any("forged can_mark_complete" in reason for reason in loaded.reasons)
    assert store.latest(method="soak") == other
    assert store.latest(target_kind="drill", target_id="restore", verified=True) == receipt
    assert store.latest(environment="ci") is None
    with pytest.raises(ValueError, match="only EvidenceReceipt"):
        store.append({"claim": "dict"}, environ=OWNER_BOX)


def test_store_defaults_under_data_root_and_is_thread_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    store = ReceiptStore()
    assert store.path == tmp_path / "home" / "evidence" / "receipts.jsonl"
    receipts = [_receipt(timestamp=NOW + i) for i in range(12)]
    threads = [
        threading.Thread(target=store.append, args=(item,), kwargs={"environ": OWNER_BOX})
        for item in receipts
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.receipts()) == 12
    assert store.load().rejected == 0


# ----------------------------------------------------------------- release-gate consumer


def _workflow(name: str, *, timestamp: float = NOW, environment: str = "owner_live", ok=True):
    return _receipt(
        claim=f"recurring workflow {name} produced its result",
        target=EvidenceRef("workflow", name),
        expected_state="result_delivered",
        observed_state="result_delivered" if ok else "result_missing",
        method="postcondition",
        environment=environment,
        timestamp=timestamp,
    )


def test_gate_rows_pass_only_from_verified_owner_live_receipts():
    empty = {row["name"]: row for row in evaluate_release_rows([], now=NOW)}
    assert set(empty) == {"restore-drill", "multi-day-soak", "recurring-workflows"}
    assert all(row["status"] == "FAIL" and row["tier"] == "owner" for row in empty.values())
    assert "no receipt recorded" in empty["restore-drill"]["detail"]

    ci_only = evaluate_release_rows([_receipt(environment="ci", environ=CI)], now=NOW)
    drill = {row["name"]: row for row in ci_only}["restore-drill"]
    assert drill["status"] == "FAIL" and "OPS-03" in drill["detail"]

    failed_live = evaluate_release_rows(
        [_receipt(observed_state="restore_incomplete")], now=NOW
    )
    drill = {row["name"]: row for row in failed_live}["restore-drill"]
    assert drill["status"] == "FAIL" and "restore_incomplete" in drill["detail"]

    passing = evaluate_release_rows([_receipt(), _receipt(observed_state="x")], now=NOW + 3600)
    drill = {row["name"]: row for row in passing}["restore-drill"]
    assert drill["status"] == "PASS" and "restore 0.0d ago" in drill["detail"]


def test_gate_rows_need_three_distinct_workflows_and_flag_stale_proof():
    two = [_workflow("morning-brief"), _workflow("morning-brief"), _workflow("backup")]
    rows = {row["name"]: row for row in evaluate_release_rows(two, now=NOW)}
    assert rows["recurring-workflows"]["status"] == "FAIL"
    assert "2/3 owner_live target(s)" in rows["recurring-workflows"]["detail"]
    three = [*two, _workflow("digest")]
    rows = {row["name"]: row for row in evaluate_release_rows(three, now=NOW)}
    assert rows["recurring-workflows"]["status"] == "PASS"
    stale_now = NOW + (er.RECEIPT_STALE_DAYS + 1) * 86400
    rows = {row["name"]: row for row in evaluate_release_rows(three, now=stale_now)}
    assert rows["recurring-workflows"]["status"] == "WARN"
    assert "stale" in rows["recurring-workflows"]["detail"]
    # ci receipts for the same workflows never count toward the three.
    mixed = [_workflow("a"), _workflow("b"), _workflow("c", environment="ci")]
    rows = {row["name"]: row for row in evaluate_release_rows(mixed, now=NOW)}
    assert rows["recurring-workflows"]["status"] == "FAIL"


def test_check_evidence_receipts_reads_the_store_and_reports_rejected_lines(tmp_path):
    store = ReceiptStore(tmp_path)
    store.append(_receipt(), environ=OWNER_BOX)
    store.path.write_text(store.path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    rows = {row["name"]: row for row in er.check_evidence_receipts(store_root=tmp_path, now=NOW)}
    assert rows["restore-drill"]["status"] == "PASS"
    assert "1 unreadable/forged receipt line(s) ignored" in rows["restore-drill"]["detail"]
    assert rows["multi-day-soak"]["status"] == "FAIL"
    assert er.check_evidence_receipts(store_root=tmp_path / "absent", now=NOW)[0]["status"] == "FAIL"
