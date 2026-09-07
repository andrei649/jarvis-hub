"""E2.1 — `epistemic_status` on `nerva.observation.v1`.

Owner-decided 2026-09-01 (CONTINUITY_CORE_RECONCILIATION.md §2). Called from
`tests/test_h14_1_bitemporal_kg.py` so it is count-neutral for the wave's own
test accounting.

The field exists because three ways of knowing something fail differently:

  · **observed** is wrong only if the source was wrong;
  · **inferred** is wrong if any input was wrong OR the reasoning was, and a
    chain of inferences over inferences compounds both;
  · **simulated** is never evidence of anything about the world, whatever it
    looks like.

So the one thing that must never happen is a silent default of "observed" —
which would relabel every inference and every simulation as evidence. That is
what these checks are for.
"""

from __future__ import annotations

import pytest

from agents.core.memory.atlas_snapshot import (
    EPISTEMIC_STATUSES,
    AtlasObservation,
    LegacyBiTemporalAdapter,
    LegacyProjectionPolicy,
)


def _fact(**over):
    base = {
        "id": "f-1",
        "subject": "andrei",
        "predicate": "prefers",
        "object": "espresso",
        "valid_from": 1.0,
        "ingested_at": 2.0,
    }
    base.update(over)
    return base


def run_e2_1_checks() -> int:
    """Every E2.1 check. Returns how many ran, so a caller can assert it grew."""
    checks = (
        _the_vocabulary_is_the_three_ways_of_knowing,
        _a_status_outside_the_vocabulary_is_refused,
        _the_field_is_required_rather_than_defaulted,
        _a_projection_declares_its_status_explicitly,
        _a_fact_can_carry_its_own_status,
        _an_inferred_fact_is_not_relabelled_as_observed,
        _a_simulated_fact_survives_projection_as_simulated,
        _the_status_is_inside_the_integrity_hash,
        _the_status_appears_in_the_canonical_payload,
    )
    for check in checks:
        check()
    return len(checks)


def _the_vocabulary_is_the_three_ways_of_knowing() -> None:
    assert EPISTEMIC_STATUSES == ("observed", "inferred", "simulated")


def _a_status_outside_the_vocabulary_is_refused() -> None:
    adapter = LegacyBiTemporalAdapter()
    with pytest.raises(ValueError, match="epistemic_status"):
        adapter.project(_fact(epistemic_status="probably"))


def _the_field_is_required_rather_than_defaulted() -> None:
    """A default of "observed" would silently relabel every inference as
    evidence, which is the whole reason the field exists."""
    import inspect

    signature = inspect.signature(AtlasObservation.__init__)
    assert signature.parameters["epistemic_status"].default is inspect.Parameter.empty


def _a_projection_declares_its_status_explicitly() -> None:
    """A legacy bitemporal fact WAS recorded by something, which is what makes
    "observed" a defensible *declaration* rather than a default."""
    assert LegacyProjectionPolicy().default_epistemic_status == "observed"
    observation = LegacyBiTemporalAdapter().project(_fact())
    assert observation.epistemic_status == "observed"


def _a_fact_can_carry_its_own_status() -> None:
    observation = LegacyBiTemporalAdapter().project(_fact(epistemic_status="inferred"))
    assert observation.epistemic_status == "inferred"


def _an_inferred_fact_is_not_relabelled_as_observed() -> None:
    policy = LegacyProjectionPolicy(default_epistemic_status="inferred")
    observation = LegacyBiTemporalAdapter(policy).project(_fact())
    assert observation.epistemic_status == "inferred"


def _a_simulated_fact_survives_projection_as_simulated() -> None:
    """A simulation that reached storage labelled as an observation is a fact
    about the world that nobody observed."""
    observation = LegacyBiTemporalAdapter().project(_fact(epistemic_status="simulated"))
    assert observation.epistemic_status == "simulated"
    assert observation.verify_integrity() is True


def _the_status_is_inside_the_integrity_hash() -> None:
    """A status changeable without breaking the hash would let a simulation be
    relabelled as an observation and still verify."""
    observed = LegacyBiTemporalAdapter().project(_fact())
    simulated = LegacyBiTemporalAdapter().project(_fact(epistemic_status="simulated"))
    assert observed.integrity_sha256 != simulated.integrity_sha256


def _the_status_appears_in_the_canonical_payload() -> None:
    payload = LegacyBiTemporalAdapter().project(_fact()).canonical_payload()
    assert payload["epistemic_status"] == "observed"
