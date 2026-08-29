"""GAP-9 — the reality-evidence ledger (durable transcript, never authority).

Pins the two halves of the design: runs persist as bounded, append-only
`nerva.reality.run.v1` records (a red run included), AND the V3 constraint
survives — nothing reads the ledger back into the registry, so a persisted
green run cannot resurrect VERIFIED across a boot.
"""

import pytest

from agents.core.observability import capability_registry
from agents.core.observability.reality_evidence import (
    _RING_LIMIT,
    SCHEMA,
    RealityEvidenceLedger,
)
from agents.core.observability.reality_harness import run_reality
from agents.core.observability.reality_types import RealityCase


@pytest.fixture(autouse=True)
def _clean_registry():
    capability_registry.clear_verifications()
    yield
    capability_registry.clear_verifications()


def _case(name="rail", *, passed=True, capability_id="action:echo"):
    async def probe():
        return passed

    return RealityCase(
        capability_id=capability_id,
        name=name,
        contract="the echo rail echoes",
        probe=probe,
    )


async def _run(cases):
    return await run_reality(cases)


@pytest.mark.asyncio
async def test_run_is_recorded_with_schema_join_and_honesty_fields(tmp_path):
    cases = [_case()]
    run = await _run(cases)
    ledger = RealityEvidenceLedger(tmp_path)
    record = ledger.record_run(run, cases, revision="abc123", lane="scheduled")
    assert record["schema"] == SCHEMA
    assert record["totals"] == {"passed": 1, "total": 1, "skipped": 0, "cases": 1}
    # The artifact says what it is: a transcript, never authority.
    assert record["promotion_scope"] == "in_process_only"
    assert record["durable_promotion"] is False
    row = record["cases"][0]
    # ref joins the artifact to CapabilityRecord.verification.
    assert row["ref"] == cases[0].ref
    assert row["contract"] == "the echo rail echoes"
    stored = ledger.runs()
    assert len(stored) == 1
    assert stored[0]["schema"] == SCHEMA


@pytest.mark.asyncio
async def test_a_red_run_is_evidence_too(tmp_path):
    cases = [_case(passed=False)]
    run = await _run(cases)
    record = RealityEvidenceLedger(tmp_path).record_run(run, cases)
    assert record["totals"]["passed"] == 0
    assert record["promoted_in_process"] == []
    assert record["cases"][0]["passed"] is False


@pytest.mark.asyncio
async def test_ring_cap_keeps_only_the_latest_runs(tmp_path):
    cases = [_case()]
    run = await _run(cases)
    ledger = RealityEvidenceLedger(tmp_path)
    for i in range(_RING_LIMIT + 5):
        ledger.record_run(run, cases, runner_id=f"runner-{i}")
    stored = ledger.runs()
    assert len(stored) == _RING_LIMIT
    assert stored[-1]["runner_id"] == f"runner-{_RING_LIMIT + 4}"
    assert stored[0]["runner_id"] == "runner-5"


@pytest.mark.asyncio
async def test_unbounded_probe_metadata_is_bounded_and_events_dropped(tmp_path):
    async def probe():
        return {
            "passed": True,
            "metadata": {
                "events": ["raw"] * 10_000,  # the operator ledger shape: dropped
                "counters": {"actions": 3},
                "huge": "x" * 100_000,
            },
        }

    case = RealityCase(
        capability_id="action:echo", name="rail", contract="c", probe=probe
    )
    run = await _run([case])
    record = RealityEvidenceLedger(tmp_path).record_run(run, [case])
    metadata = record["cases"][0]["metadata"]
    assert "events" not in metadata
    assert metadata["counters"] == {"actions": 3}
    assert len(metadata["huge"]) <= 300


@pytest.mark.asyncio
async def test_torn_ledger_line_never_poisons_history(tmp_path):
    cases = [_case()]
    ledger = RealityEvidenceLedger(tmp_path)
    ledger.record_run(await _run(cases), cases)
    with ledger.path.open("a", encoding="utf-8") as handle:
        handle.write('{"torn": \n')
    ledger.record_run(await _run(cases), cases)
    assert len(ledger.runs()) == 2


@pytest.mark.asyncio
async def test_persisted_green_run_cannot_resurrect_verified(tmp_path):
    # The V3 no-durable-promotion pin: a green run on disk, then a fresh boot
    # (clear_verifications simulates it) — the registry must NOT see VERIFIED,
    # and the ledger must not be consulted by the registry at all.
    cases = [_case()]
    run = await _run(cases)  # promotes in-process
    RealityEvidenceLedger(tmp_path).record_run(run, cases)
    capability_registry.clear_verifications()  # the boot
    assert capability_registry._VERIFICATIONS == {}
    # No production module consumes the ledger: nothing imports
    # reality_evidence (its only entry points are the CLI and this suite),
    # so the registry cannot be fed from disk even by accident.
    import subprocess  # noqa: S404 - test-only source grep, fixed argv

    grep = subprocess.run(  # noqa: S603,S607
        ["grep", "-rl", "reality_evidence", "agents/"],
        capture_output=True,
        text=True,
        check=False,
    )
    readers = [
        line
        for line in grep.stdout.splitlines()
        if not line.endswith("reality_evidence.py") and not line.endswith(".pyc")
    ]
    assert readers == []


def test_workflow_uploads_evidence_on_always_with_bounded_retention():
    from pathlib import Path

    text = Path(".github/workflows/reality.yml").read_text(encoding="utf-8")
    assert "reality_evidence" in text
    assert text.count("if: ${{ always() }}") >= 2
    assert "retention-days: 14" in text
    # The evidence step must not weaken the lane: no continue-on-error.
    assert "continue-on-error" not in text


def test_ledger_lives_directly_under_its_root(tmp_path):
    ledger = RealityEvidenceLedger(tmp_path / "nested")
    assert ledger.path.parent == (tmp_path / "nested")
    assert ledger.path.name == "runs.jsonl"
