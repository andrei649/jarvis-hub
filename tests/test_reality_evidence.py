"""GAP-9 — the reality-evidence ledger (durable transcript, never authority).

Pins the two halves of the design: runs persist as bounded, append-only
`nerva.reality.run.v1` records (a red run included), AND the V3 constraint
survives — nothing reads the ledger back into the registry, so a persisted
green run cannot resurrect VERIFIED across a boot.
"""

import json

import pytest

from agents.core.observability import capability_registry
from agents.core.observability.reality_evidence import (
    _RING_LIMIT,
    SCHEMA,
    RealityEvidenceLedger,
    explain_verdict,
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


def _verdict_message(record):
    """Newline-joined, NOT the raw list.

    A bare `assert rc == 0` reports only "assert 1 == 0" and discards which case
    broke the verdict. But passing the list itself is barely better: pytest
    renders it through `saferepr`, which truncates in the middle — measured, the
    `[UNEXCUSED]` row is elided when it is not last, i.e. exactly the line the
    message exists to carry. Joining on newlines renders every row.
    """
    return "\n" + "\n".join(explain_verdict(record)["lines"])


def _row(cid, *, passed, live=False, name=None, skipped=False):
    return {"capability_id": cid, "name": name or f"{cid} probe",
            "passed": passed, "skipped": skipped, "live": live}


def test_explain_verdict_names_the_unexcused_case_and_nothing_else():
    """A red run used to print only the arithmetic — "131/136 passed, 1 expected
    seam failures, 3 owner-live cases not exercised" — and exit 1. The one fact
    a reader needs, *which* case broke the verdict, was in the JSON artifact and
    nowhere in the log, so a flake here cost #1017 a full investigation.

    The two excusals are per-CASE, but the record stores them as capability-id
    lists, and an id is shared by a capability's offline and owner-live rows.
    So the owner-live excusal only applies to a row that is itself `live`:
    an offline sibling failing under the same id is a regression, not an
    excusal — the same distinction the run-verdict test below pins.
    """
    record = {
        "cases": [
            _row("action:echo", passed=True),
            _row("skill:Weather Intel", passed=False),                 # expected seam
            _row("action:house.control", passed=False, live=True),     # owner-live, off-box
            _row("action:house.control", passed=False, live=False),    # its OFFLINE sibling: real
            _row("component:camera_source", passed=False, skipped=True),
            _row("component:orchestrator", passed=False, name="the regression"),
        ],
        "expected_seam_failures": ["skill:Weather Intel"],
        "owner_live_not_exercised": ["action:house.control"],
    }
    unexcused = explain_verdict(record)["unexcused"]
    ids = [c["capability_id"] for c in unexcused]

    assert "component:orchestrator" in ids
    # the offline sibling must NOT be excused by its owner-live twin's id
    assert ids.count("action:house.control") == 1
    # …and the genuinely excused / passing / skipped rows must not appear
    assert "skill:Weather Intel" not in ids
    assert "action:echo" not in ids
    assert "component:camera_source" not in ids
    assert len(ids) == 2

    lines = explain_verdict(record)["lines"]
    blob = "\n".join(lines)
    assert "component:orchestrator" in blob and "the regression" in blob
    assert "skill:Weather Intel" in blob, "every failing row is listed, tagged"
    assert "expected-seam" in blob and "owner-live" in blob and "UNEXCUSED" in blob


def test_explain_verdict_is_quiet_when_every_failure_is_excused():
    record = {
        "cases": [_row("action:echo", passed=True),
                  _row("skill:Weather Intel", passed=False)],
        "expected_seam_failures": ["skill:Weather Intel"],
        "owner_live_not_exercised": [],
    }
    assert explain_verdict(record)["unexcused"] == []


@pytest.mark.asyncio
async def test_run_is_recorded_with_schema_join_and_honesty_fields(tmp_path):
    cases = [_case()]
    run = await _run(cases)
    ledger = RealityEvidenceLedger(tmp_path)
    record = ledger.record_run(run, cases, revision="abc123", lane="scheduled")
    assert record["schema"] == SCHEMA
    assert record["totals"] == {
            "passed": 1, "total": 1, "skipped": 0, "cases": 1, "expected_seam_failures": 0,
            "owner_live_not_exercised": 0,
        }
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
    # No production module CONSUMES the ledger: nothing imports
    # reality_evidence and nothing constructs its ledger class, so the
    # registry cannot be fed from disk even by accident.
    #
    # The grep matches import statements and the ledger class name rather than
    # the bare substring: a module may legitimately *name* this lane as the
    # provenance of a measurement it was handed (evidence_receipt.py labels an
    # EvidenceValue "reality_evidence.totals"), and a label in a string cannot
    # promote anything. An import or a ledger construction can, so those stay
    # forbidden — which is the invariant this test exists to pin.
    import re
    import subprocess  # noqa: S404 - test-only source grep, fixed argv

    grep = subprocess.run(  # noqa: S603,S607
        ["grep", "-rn", "-E", r"(^|\s)(import|from)\s+\S*reality_evidence|RealityEvidenceLedger", "agents/"],
        capture_output=True,
        text=True,
        check=False,
    )
    readers = [
        line
        for line in grep.stdout.splitlines()
        if not re.match(r"^agents/core/observability/reality_evidence\.py:", line)
        and ".pyc" not in line.split(":", 1)[0]
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


# ── the scheduled lane's actual entry point (red 4 nights: #980 called a
#    non-existent ``agents.core.skills.discover``) ──────────────────────────
@pytest.mark.asyncio
async def test_run_and_record_boots_the_orchestrator_and_discovers_skills(tmp_path):
    """Exercise ``_run_and_record`` in-process, offline, exactly as
    ``python -m agents.core.observability.reality_evidence --lane scheduled``
    does: it must return a record (not raise) and the skills-discovery path
    must have produced the derived ``skill:*`` cases."""
    import argparse

    from agents.core.observability.reality_evidence import _run_and_record

    args = argparse.Namespace(
        store_root=str(tmp_path),
        revision="deadbeef",
        runner_id="pytest",
        lane="scheduled",
    )
    record = await _run_and_record(args)

    assert record["schema"] == SCHEMA
    assert record["lane"] == "scheduled"
    assert record["revision"] == "deadbeef"
    assert record["totals"]["cases"] == len(record["cases"]) > 0
    skill_cases = [c for c in record["cases"] if str(c["capability_id"]).startswith("skill:")]
    assert skill_cases, "skills discovery ran, so skill:* cases must exist"
    # The ledger landed under the requested root, not the data root.
    ledger = RealityEvidenceLedger(tmp_path)
    assert ledger.path.exists()
    assert len(ledger.runs()) == 1


def test_run_and_record_uses_the_loader_discover_not_a_package_attribute():
    """Pin the fix shape: discovery is ``SkillLoader.discover`` on the
    orchestrator — the ``agents.core.skills`` package exposes no ``discover``."""
    import inspect

    from agents.core import skills as skills_pkg
    from agents.core.observability import reality_evidence

    assert not hasattr(skills_pkg, "discover")
    source = inspect.getsource(reality_evidence._run_and_record)
    assert "orch.skills.discover()" in source
    assert "skill_registry.discover()" not in source


def test_main_exits_zero_offline_when_only_seam_capabilities_fail(tmp_path):
    """The scheduled lane's exit verdict mirrors the pytest contract: a SEAM capability
    (registered, no runtime behind it) is expected to fail its probe and must not turn the
    nightly red — anything else failing still exits 1 (CTO decision D3, 2026-09-02)."""
    from agents.core.observability.reality_evidence import main

    out = tmp_path / "latest-run.json"
    rc = main(["--store-root", str(tmp_path), "--json-out", str(out), "--lane", "local"])
    record = json.loads(out.read_text(encoding="utf-8"))
    totals = record["totals"]
    failing = {case["capability_id"] for case in record["cases"] if not case["passed"] and not case["skipped"]}
    assert rc == 0, _verdict_message(record)
    assert totals["passed"] + totals["expected_seam_failures"] >= totals["total"]
    assert set(record["expected_seam_failures"]) | set(record["owner_live_not_exercised"]) == failing


def test_main_exits_zero_in_live_mode_when_owner_hardware_is_absent(tmp_path, monkeypatch):
    """The scheduled lane runs with JARVIS_REALITY_HARNESS=1 on a GitHub runner: the
    owner-live house/camera cases report their opt-in as missing and must count as
    'not exercised on this host', never as a red nightly (2026-09-03 run 70)."""
    from agents.core.observability.reality_evidence import main

    monkeypatch.setenv("JARVIS_REALITY_HARNESS", "1")
    monkeypatch.delenv("JARVIS_H30_HA_LIVE", raising=False)
    out = tmp_path / "latest-run.json"
    rc = main(["--store-root", str(tmp_path), "--json-out", str(out), "--lane", "scheduled"])
    record = json.loads(out.read_text(encoding="utf-8"))
    totals = record["totals"]
    failing = {c["capability_id"] for c in record["cases"] if not c["passed"] and not c["skipped"]}
    assert rc == 0, _verdict_message(record)
    assert totals["owner_live_not_exercised"] >= 1
    assert set(record["expected_seam_failures"]) | set(record["owner_live_not_exercised"]) == failing
    for case in record["cases"]:
        # a capability id is shared by its offline and owner-live cases; only the
        # failing owner-live rows are the ones the verdict excused
        if case["capability_id"] in record["owner_live_not_exercised"] and not case["passed"]:
            assert case["live"] is True and case["promotable"] is False
