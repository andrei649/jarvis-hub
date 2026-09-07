"""The gap the #861 post-merge review found: `BenchmarkRun.to_dict` leaked.

`RegressionReport.to_dict` re-asserts its authority ceiling at emission (#861),
and the E6 payloads do the same (#860). `BenchmarkRun` sits in the same module,
carries **the same five ceiling fields**, and was in neither PR's scope — so it
returned `asdict(self)` verbatim and a post-construction mutation travelled
straight into a persisted run.

That is inside the threat model both PRs already accept: they exist *because* a
frozen dataclass can still be mutated through `object.__setattr__`, and they both
answer it at the serialisation boundary rather than trusting the object. This
closes the same hole in the third type.

Why it matters more here than it looks: a `BenchmarkRun` is **persisted**. A
widened ceiling on a report dies with the process; one on a stored run outlives
whatever widened it, and is read back later as though it were what the run always
claimed.

Found by `docs/nerva2/attestations/2026-09-07-post-merge-reviews.md`. That
attestation deliberately does **not** cover this fix — the same agent wrote both,
and a reviewer signing off their own patch is the thing the role split prevents.
"""

from __future__ import annotations

import asyncio
import dataclasses
import tempfile
from pathlib import Path

import pytest

from agents.core.observability.benchmark import BenchmarkStore
from agents.core.observability.scheduled_report import BenchmarkRun, run_scheduled_suite

CEILING = ("can_change_routing", "can_authorize", "can_execute", "can_mark_complete")


def _run() -> BenchmarkRun:
    with tempfile.TemporaryDirectory() as tmp:
        store = BenchmarkStore(Path(tmp))
        return asyncio.run(
            run_scheduled_suite(store, revision="a" * 40, run_id="ceiling-probe")
        )


def _widen(run: BenchmarkRun) -> BenchmarkRun:
    """Exactly the mutation #860 and #861 defend against."""
    for field in dataclasses.fields(run):
        if field.name in CEILING:
            object.__setattr__(run, field.name, True)
        elif field.name == "authority":
            object.__setattr__(run, field.name, "full_authority")
    return run


def test_a_widened_authority_never_reaches_the_emitted_run():
    """A BenchmarkRun is persisted, so a widened ceiling here outlives the process
    that widened it and is read back as what the run always claimed."""
    payload = _widen(_run()).to_dict()
    assert payload["authority"] == "evaluation_only"


@pytest.mark.parametrize("field", CEILING)
def test_every_ceiling_field_is_re_asserted(field):
    assert _widen(_run()).to_dict()[field] is False


def test_the_unmutated_run_is_unchanged():
    """The guard must re-assert, not rewrite: an honest run's payload is the same
    with or without it."""
    payload = _run().to_dict()
    assert payload["authority"] == "evaluation_only"
    assert all(payload[f] is False for f in CEILING)


def test_the_rest_of_the_payload_still_travels():
    """A ceiling guard that flattened the payload would trade one bug for a worse
    one — a run that carries no result."""
    payload = _run().to_dict()
    assert payload.get("summary")
    assert payload.get("run_id") == "ceiling-probe"


def test_benchmark_run_carries_the_same_ceiling_as_its_sibling():
    """If the two ever diverge, one of them is defending a field the other does
    not have — and the gap this test closed would reopen somewhere new."""
    from agents.core.observability.scheduled_report import RegressionReport

    def ceiling_fields(cls):
        return {f.name for f in dataclasses.fields(cls)
                if f.name in CEILING or f.name == "authority"}

    assert ceiling_fields(BenchmarkRun) == ceiling_fields(RegressionReport)
