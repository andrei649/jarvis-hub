"""E5.0 — the work verifier: does the evidence a run produced actually hold?

The verifier's whole value is that it refuses the leap from "I ran the build" to
"the build passes". These tests pin that refusal from every direction: no probe,
a broken probe, a probe that answers something other than yes/no, work taken
without an approved task, and a tampered run row.

Hermetic: the ledger is real (in-memory SQLite) so the verdict really lands, and
probes are plain callables.
"""

import types

import pytest

from agents.core.autonomy.work_runs import WorkRunLedger
from agents.core.autonomy.work_verifier import Check, WorkVerifier

pytestmark = pytest.mark.asyncio


def _goal(goal_id: str = "g-1"):
    return types.SimpleNamespace(
        goal_id=goal_id,
        title="Prepare the quarterly brief",
        approved_by="receipt:owner-accepted-1",
        deadline_at=100_000.0,
    )


@pytest.fixture
def ledger():
    led = WorkRunLedger(":memory:", clock=lambda: 1_000.0)
    yield led
    led.close()


@pytest.fixture
def run(ledger):
    opened = ledger.open_run(_goal())
    ledger.record_step(opened.id, kind="build", summary="ran the build",
                       outcome="ok", task_id=11)
    return opened


# ── the core refusal ─────────────────────────────────────────────────────────

async def test_a_check_with_no_probe_is_unverifiable_and_never_a_pass(ledger, run):
    """The absence of a way to look is a fact about the check, not a pass."""
    report = await WorkVerifier(ledger).verify(
        run.id, [Check(id="build-green", describe="the build passes")]
    )
    assert report.passed is False
    assert report.counts == {"passed": 0, "failed": 0, "unverifiable": 1}
    assert "no probe" in report.reason
    assert ledger.get(run.id).status == "working"  # a verifier verdict never settles


async def test_a_probe_that_looks_and_finds_the_property_passes(ledger, run):
    report = await WorkVerifier(ledger).verify(
        run.id, [Check(id="build-green", describe="the build passes", probe=lambda: True)]
    )
    assert report.passed is True
    assert report.reason == "every required check was probed and holds"
    assert [v.passed for v in ledger.verdicts(run.id)] == [True]


async def test_a_probe_that_raises_is_a_failure_not_a_skip(ledger, run):
    """Swallowing probe errors would turn every broken probe into silent success."""
    def _boom():
        raise RuntimeError("no such file")

    report = await WorkVerifier(ledger).verify(
        run.id, [Check(id="artifact", describe="the artifact exists", probe=_boom)]
    )
    assert report.passed is False
    assert report.counts["failed"] == 1
    assert "probe raised RuntimeError" in report.outcomes[0].detail


async def test_a_probe_that_answers_something_other_than_yes_or_no_fails(ledger, run):
    """A truthy string is not an observation. Accepting it is exactly the leap
    this component exists to refuse."""
    report = await WorkVerifier(ledger).verify(
        run.id,
        [Check(id="looks-fine", describe="it looks fine", probe=lambda: "probably")],
    )
    assert report.passed is False
    assert "not a yes/no" in report.outcomes[0].detail


async def test_an_async_probe_is_awaited(ledger, run):
    async def _probe():
        return True

    report = await WorkVerifier(ledger).verify(
        run.id, [Check(id="async", describe="an async probe", probe=_probe)]
    )
    assert report.passed is True


# ── what outranks the probes ─────────────────────────────────────────────────

async def test_a_step_taken_without_an_approved_task_fails_however_good_the_probes(
    ledger,
):
    """Work Nerva was not authorised to do cannot be laundered into a pass."""
    opened = ledger.open_run(_goal())
    ledger.record_step(opened.id, kind="edit", summary="wrote a file", outcome="ok")
    report = await WorkVerifier(ledger).verify(
        opened.id, [Check(id="c", describe="everything is fine", probe=lambda: True)]
    )
    assert report.passed is False
    assert report.unauthorised_steps == (1,)
    assert "no approved task" in report.reason
    # the probe still ran and still reported honestly — it was simply outranked
    assert report.counts["passed"] == 1


async def test_a_tampered_run_row_outranks_everything(ledger, run, monkeypatch):
    real = ledger.snapshot

    def _tampered(run_id, **kwargs):
        return {**real(run_id, **kwargs), "tampered": True}

    monkeypatch.setattr(ledger, "snapshot", _tampered)
    report = await WorkVerifier(ledger).verify(
        run.id, [Check(id="c", describe="fine", probe=lambda: True)]
    )
    assert report.passed is False
    assert report.reason == "run row does not match its fingerprint"


async def test_a_run_with_no_checks_cannot_pass(ledger, run):
    """A goal that declared nothing to verify has not been verified. Passing it
    would make the verifier a rubber stamp for any goal that skipped the work."""
    report = await WorkVerifier(ledger).verify(run.id, [])
    assert report.passed is False
    assert "declared no checks" in report.reason


# ── required vs optional ─────────────────────────────────────────────────────

async def test_an_unprobed_optional_check_does_not_sink_the_run_but_is_reported(
    ledger, run
):
    report = await WorkVerifier(ledger).verify(
        run.id,
        [
            Check(id="core", describe="the required one", probe=lambda: True),
            Check(id="nice", describe="the optional one", required=False),
        ],
    )
    assert report.passed is True
    assert "1 optional check(s) unprobed" in report.reason
    assert report.counts == {"passed": 1, "failed": 0, "unverifiable": 1}


async def test_a_failed_optional_check_still_fails_the_run(ledger, run):
    """Optional means "we may not be able to look", never "we may ignore a no"."""
    report = await WorkVerifier(ledger).verify(
        run.id,
        [
            Check(id="core", describe="required", probe=lambda: True),
            Check(id="nice", describe="optional", probe=lambda: False, required=False),
        ],
    )
    assert report.passed is False
    assert report.counts["failed"] == 1


# ── the verdict it writes ────────────────────────────────────────────────────

async def test_the_verdict_carries_a_line_of_evidence_per_check(ledger, run):
    await WorkVerifier(ledger).verify(
        run.id,
        [
            Check(id="a", describe="first", probe=lambda: True),
            Check(id="b", describe="second", probe=lambda: True),
        ],
    )
    verdict = ledger.verdicts(run.id)[0]
    assert verdict.role == "verifier"
    assert len(verdict.evidence) == 2
    assert verdict.evidence[0].startswith("a: passed")


async def test_record_false_looks_without_spending_the_run_s_one_verdict(ledger, run):
    """The supervisor peeks mid-run; a peek must not consume the single verdict
    the ledger allows, or the real verification at the end would be refused."""
    verifier = WorkVerifier(ledger)
    peek = await verifier.verify(
        run.id, [Check(id="a", describe="first", probe=lambda: False)], record=False
    )
    assert peek.passed is False
    assert ledger.verdicts(run.id) == []
    final = await verifier.verify(
        run.id, [Check(id="a", describe="first", probe=lambda: True)]
    )
    assert final.passed is True
    assert len(ledger.verdicts(run.id)) == 1


async def test_a_verified_run_is_still_the_judge_s_to_settle(ledger, run):
    """The verifier says the evidence holds; only the judge says the goal was met."""
    await WorkVerifier(ledger).verify(
        run.id, [Check(id="a", describe="first", probe=lambda: True)]
    )
    assert ledger.get(run.id).status == "working"
    ledger.record_verdict(run.id, role="judge", passed=True, reason="goal met")
    assert ledger.get(run.id).status == "succeeded"


# ── construction ─────────────────────────────────────────────────────────────

async def test_a_check_needs_an_id_and_a_description():
    for kwargs in ({"id": "", "describe": "x"}, {"id": "x", "describe": "  "}):
        with pytest.raises(ValueError):
            Check(**kwargs)
