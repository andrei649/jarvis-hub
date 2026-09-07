# E2.1 — `epistemic_status` on `nerva.observation.v1`

> **Status:** delivered, not program-accepted.
> **Owner decision:** 2026-09-01, `CONTINUITY_CORE_RECONCILIATION.md` §2.
> **Closes:** B3 / #731 criterion 5.

## The distinction

Every Atlas observation now says **how it came to be known**. Three states, because
they fail in three different ways:

| status | wrong when | compounding |
|---|---|---|
| `observed` | the source was wrong | no |
| `inferred` | any input was wrong **or** the reasoning was | yes — inferences over inferences compound both |
| `simulated` | never evidence of anything about the world, whatever it looks like | n/a |

A system that cannot tell these apart will eventually cite a simulation as a fact,
and it will do so with exactly the same confidence it cites a measurement.

## Why there is no default

`AtlasObservation.epistemic_status` is a **required** constructor argument. That is
the whole design, and the reason is one sentence:

> A field that silently defaults to `observed` relabels every inference and every
> simulation as evidence.

A default would be convenient at exactly the moments it is most dangerous — bulk
imports, backfills, a new projection someone wrote in a hurry. So the projection
policy has to **declare** it:

```python
LegacyProjectionPolicy(default_epistemic_status="observed")   # a claim, visibly made
```

`observed` is defensible *there* because a legacy bitemporal fact really was recorded
by something. A caller projecting inferred facts sets the policy to `inferred` rather
than inheriting a claim that is not true of their data, and an individual fact can
carry its own `epistemic_status` which wins over the policy.

## It is inside the integrity hash

`epistemic_status` is part of the material `integrity_sha256` covers. A status that
could be changed without breaking the hash would let a simulation be relabelled as an
observation **and still verify** — which is worse than having no field, because the
verification would now be actively misleading.

## Checks

`tests/_nerva_e2_1_checks.py`, invoked from `tests/test_h14_1_bitemporal_kg.py`
(count-neutral). Nine checks; the two that carry the design are
`_the_field_is_required_rather_than_defaulted` and
`_the_status_is_inside_the_integrity_hash`, both red-proven.
