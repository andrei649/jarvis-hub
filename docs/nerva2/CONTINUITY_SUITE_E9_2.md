# Nerva E9.2 — Continuity Core (#731) evaluation suite on `nerva.benchmark.v1`

> **Status:** delivered, not program-accepted · B3 / #731 evaluation-suite destination
> recorded in [`CONTINUITY_CORE_RECONCILIATION.md`](CONTINUITY_CORE_RECONCILIATION.md) §"Evaluation suite"
> (owner decision 2026-09-01) · parent E9 Research Lab #767 · program #757.
> **Authority:** `evaluation_only`; no routing, authorization, execution, promotion, completion or
> epic-acceptance authority.

## Outcome

The reconciliation said "no suite package exists yet". This slice is that package:
`agents/core/observability/continuity_suite.py`, a separately scoped `evaluation_only` suite
named **`continuity-core-v1`** that runs on the accepted E9.0 `BenchmarkStore` / `BenchmarkHarness`
without touching them, outside E9's serialized #854 repair queue.

It reuses, unchanged:

- `nerva.benchmark.v1` `BenchmarkCase`, `BenchmarkRun`, `BenchmarkStore`, `BenchmarkHarness` and their
  privacy lanes, immutable case-content fingerprints, retained-evidence rules and authority ceiling;
- the E9.1 lane conventions (`$GITHUB_STEP_SUMMARY` append, atomic single-document JSON write,
  exact-revision binding that never shells out).

## What a case is

Each case is a synthetic-public **scenario** (`nerva.continuity.scenario.v1`): a bounded sequence of
memory events followed by one question, serialized as canonical JSON into `BenchmarkCase.input_text`,
with an `exact` criterion on the answer. Events: `observe` / `correct` (with a `source` of `owner`,
`untrusted` or `inferred`), `forget`, `restart`, and identity governance (`identity_set`,
`identity_propose`, `identity_approve`). Questions: `recall`, `audit`, `explain`, `identity`.
Every token is a trimmed single line of at most 256 characters; the fixtures name only
`howard`/`guest`/`coffee`/`black`-style synthetic values, never owner data.

The subject under evaluation is any object with `apply(event)` and `answer(query)`
(`ContinuitySubject`). `subject_runner()` adapts a subject **factory** to the E9.0 runner envelope
(one fresh instance per scenario). Its defaults describe an in-process deterministic subject; a caller
wrapping a model-backed memory must pass truthful `model_id` / `provider_id` / `privacy_effect` — the
suite never infers provenance.

## The 20 scenarios and their acceptance owners

| criterion (`task_type`) | scenarios | acceptance owner (not this suite) |
|---|---:|---|
| `multi-session-recall` | 2 | E3 Episodes (#761) |
| `recall-precision-under-taint` | 4 | E3 admission reason (#761) + `RISKS.md` MEM-03/SEC-05 |
| `contradiction-retraction` | 3 | E3.0 supersession + E6 Reflection |
| `cross-person-leakage` | 2 | `RISKS.md` PRIV-02 (E2 #760 primary) |
| `abstention-calibration` | 2 | E12 Hybrid Cognition (advisory only) |
| `identity-stability` | 3 | E4 Identity Manifest (#1008) |
| `forget-purge-honesty` | 4 | E3 tombstones + E11 migration parity |

The scenario set is versioned by content: `suite_fingerprint()` is the SHA-256 over the ordered E9.0
case fingerprints and is **pinned in the test** (`5a0096d9…d487de`). Same inputs ⇒ same fingerprint;
any scenario change flips it, and `ensure_suite()` then mints a new suite version instead of
comparing runs across content that differed.

## Reference subject and the baseline that fails

`ReferenceContinuityMemory` is a transparent in-process model of the #731 semantics: facts keyed per
person; only `owner`/`inferred` sources admitted as current truth, with an inspectable admission
reason (`admitted:owner`, `admitted:inferred`, `rejected:untrusted`, `abstain:unknown`,
`abstain:purged`); untrusted evidence retained but never recalled and unable to supersede; corrections
supersede and the old value never resurfaces; `forget` purges the value and leaves an honest tombstone
(`audit` → `purged`, not `unknown`); `restart` preserves everything; identity changes apply only after
an explicit approval of a proposal.

`NaiveRecallBaseline` is the deliberately weak comparison — last write wins, no people, every source
admitted, proposals applied immediately, state lost on restart, purges reported as never known. In the
retained run it scores **0.35** against the reference's **1.0**, failing exactly the taint, leakage,
restart-continuity, purge-honesty and identity-governance cases. That is the proof the suite can fail.

Measuring the reference subject validates the **suite contract**; it proves nothing about production
memory. Pointing the suite at the real E3 episode store / Atlas is a future adapter that E3 owns,
exactly as E9.0's first baseline "validates the contract rather than proving router superiority".

## Report

`build_report()` produces a `nerva.continuity.report.v1` document from a **retained** run only
(an unrecorded run is rejected), with per-criterion candidate and baseline pass ratios, the acceptance
owner per criterion, `acceptance: "not_claimed"`, and an explicit `can_accept_epic = false` alongside
the E9.1 ceiling flags — all `init=False`, so neither direct construction nor `dataclasses.replace`
can flip them. A regression is declared only against a comparable previous run (same suite version,
candidate and baseline) whose criterion pass ratio was higher; a first run says
"no comparable previous run".

## Lane entry (integrator)

```text
python -m agents.core.observability.continuity_suite \
  --store-root "$NERVA_CONTINUITY_STORE" --summary "$GITHUB_STEP_SUMMARY" \
  --json-out "$NERVA_CONTINUITY_REPORT" --revision "$GITHUB_SHA" --fail-on-regression
```

Exit codes: `0` ran, `1` regressed under `--fail-on-regression`, `2` prerequisite missing (no exact
revision, or a lane the suite is not allowed in). Owner-var gating and cache/artifact retention follow
the existing `nerva-router-shadow` job in `eval-nightly.yml`; CI is software evidence only.

## Tests

`tests/test_continuity_suite.py` (6 collected tests, hermetic): suite registers on `BenchmarkStore`
with a stable version; pinned fingerprint and hostile-scenario rejection; reference passes 20/20 while
the baseline fails the named cases; subject errors retained without messages and provenance explicit;
nothing can be marked accepted (imports scanned by `ast`, run/report flags, forged report rejected);
deterministic report, regression only across comparable runs, CLI exit codes 2/0/1.

Red-proof: admitting `untrusted` sources in the reference memory fails
`test_reference_subject_passes_and_naive_baseline_fails_where_it_should` (`16 == 20`) and the
report test's per-criterion ratios.

## Explicit exclusions

- no production memory adapter, no owner-private or sanitized fixtures, no cloud lane;
- no E3/E6/E12/E11 acceptance claims — #731 stays open on its own bar;
- no dashboard, HUD panel or route (the retained JSONL is inspectable through the E9.0 store);
- no Action Kernel involvement: the suite performs no privileged effect and registers no action kind.
