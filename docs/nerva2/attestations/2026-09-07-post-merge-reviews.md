# Post-merge attestations — E6 #860, E9 #861, E9-totals #864, SEC-B8 #911

> **Role:** read-only post-merge reviewer, distinct from the original builders.
> **Commissioned by:** owner decision 2026-09-01 (`BACKLOG.md`, the two 🟡 paragraphs
> on the E1/E6/E9 authority-ceiling successors and the landed-not-yet-accepted
> governance wave).
> **Date:** 2026-09-07. **Reviewed against:** the merge commits named below, as the
> code stands on `main` today.

## Method, and its limits

Each claim was re-verified **behaviourally**, against the code as it is now — not by
reading the builder's tests and agreeing with them. Construction reuses the shipped
API (that is not what is under review); the **mutation and the assertion in every
check are the reviewer's own**, so a builder test that agreed with itself could not
produce a GO here.

Every probe carries a **control** that must come out the other way. A probe that
refuses everything proves nothing, and three of the four checks below initially
"passed" for the wrong reason until a control exposed it.

**What this attestation does not cover.** It is a review of the merged code against
its stated claim. It says nothing about the original review process, nothing about
behaviour on hardware this reviewer does not have, and it is **not dependency
acceptance** — exactly as the owner's decision specifies.

---

## E6 #860 — `f62d8b5` — **GO**

**Claim.** `OutcomeObservation.canonical_payload`, `LessonProposal.canonical_payload`
and `LessonEvaluationReport.to_dict` re-assert `proposal_only` / `evaluation_only`
and all `can_* = False` at emission time, so a post-construction mutation cannot
leak a widened authority into a serialized payload.

**Check.** Each object was built through its normal path, then every ceiling field
was flipped to `True` and `authority` set to `"full_authority"` via
`object.__setattr__` — and the serialized payload inspected.

| serialiser | mutated in memory | emitted |
|---|---|---|
| `OutcomeObservation.canonical_payload` | all `can_*` True, `authority="full_authority"` | ceiling re-asserted |
| `LessonProposal.canonical_payload` | same | ceiling re-asserted |
| `LessonEvaluationReport.to_dict` | same | ceiling re-asserted |

**Verdict: GO.** The claim holds on its stated scope.

---

## E9 #861 — `9b7ac88` — **GO**

**Claim.** `RegressionReport.to_dict` hard-codes the `evaluation_only` ceiling.

**Check.** A report built through `build_report` (its only construction path), then
mutated as above. The payload re-asserted `evaluation_only` and every `can_*` False.

A **stronger** property than the commit claimed also holds and is worth recording:
`RegressionReport` **cannot be constructed at all** outside `build_report` — a direct
construction refuses with *"a report must be derived from a retained run through
build_report"*. The serialisation guard is therefore a second line, not the only one.

**Verdict: GO.** The claim holds on its stated scope.

### Finding, outside the scope of #861 — `BenchmarkRun.to_dict` leaks

`BenchmarkRun` is re-exported from `scheduled_report` (it is *defined* in
`agents/core/observability/benchmark.py` — a detail that matters, because a reviewer
grepping only the module #861 touched would never see it) and carries **the same five
ceiling fields**
(`authority`, `can_change_routing`, `can_authorize`, `can_execute`,
`can_mark_complete`). It was not in #861's scope and it hard-codes none of them:

```
BenchmarkRun authority before: evaluation_only
BenchmarkRun.to_dict -> LEAKED {'can_change_routing': True, 'can_authorize': True,
                                'can_execute': True, 'can_mark_complete': True,
                                'authority': 'full_authority'}
```

This is **the exact defect #860 and #861 were opened to fix**, in a sibling type
neither touched, and inside the same threat model those PRs already accept (a
post-construction mutation via `object.__setattr__`). A `BenchmarkRun` is emitted
into reports and persisted, so a widened ceiling would travel.

It does **not** change the #861 verdict: #861 did what it said. It is recorded here
because a reviewer who found this and did not report it would be rubber-stamping.

> **The fix for this finding was written by the same agent, in the same PR, and is
> therefore NOT covered by this attestation.** It needs its own review by someone
> else. Recording the finding is the reviewer's act; fixing it is a builder's, and
> the two are kept visibly apart rather than quietly merged.
>
> The fix is in `agents/core/observability/benchmark.py`, covered by
> `tests/test_e9_benchmark_run_ceiling.py`. Those tests failed before it and pass
> after, which is the only evidence offered for the fix itself here.

---

## E9-totals #864 — `568de94` — **GO**

**Claim.** Totals with `scored > 0` and no `quality_mean` are rejected.

**Check.** `_validate_totals` has several guards, and a naive probe is refused by the
*wrong* one — the first attempt here was refused for a key-set mismatch and would
have produced a GO that proved nothing. Isolated, with controls on both sides:

| totals | outcome |
|---|---|
| valid scored run *(control)* | **accepted** |
| `scored=2, quality_mean=None` | refused — *"cannot claim scored cases without a quality_mean"* |
| `scored=0, quality_mean=0.5` | refused — *"cannot score an unscored run"* (the mirror rule) |
| `scored=0, quality_mean=None` *(control)* | **accepted** |

Both controls come out the other way, so the refusals are the invariant and not a
validator that refuses everything.

**Verdict: GO.** The claim holds, and the mirror rule holds too.

---

## SEC-B8 #911 — `790a725` — **PASS**

**Claim.** External-skill approval authority lives **outside** the candidate tree, so
a skill cannot approve itself by shipping its own approval file.

**Check.** `agents/core/skills/approval.py`:

* the approval root derives from the **data root** (`data_path`), not from the
  skill's own directory;
* the module contains **no reference to the candidate tree** at all — the separation
  is structural rather than a check that could be bypassed;
* `agents/core/skills/loader.py` imports and consumes that external store.

**Verdict: PASS.** Per the owner's decision this closes #905. #911 is
governance-complete as of this attestation.

---

## Summary

| review | commit | verdict |
|---|---|---|
| E6 #860 | `f62d8b5` | **GO** |
| E9-authority #861 | `9b7ac88` | **GO** (+ one out-of-scope finding) |
| E9-totals #864 | `568de94` | **GO** |
| SEC-B8 #911 | `790a725` | **PASS** — closes #905 |

Four GO/PASS verdicts, one finding, and no rubber stamps: the E9-totals probe had to
be rewritten once because its first version was refused by an unrelated guard, and
the `BenchmarkRun` gap was found by extending a check past the boundary of the claim
it was written for. Neither would have surfaced from reading the builders' tests.
