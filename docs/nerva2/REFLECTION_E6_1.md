# Nerva E6.1 — held-out lesson-proposal evaluation

Issue [#817](https://github.com/andrei649/jarvis-hub/issues/817) adds one
bounded evaluator over the accepted E6.0 lesson contract and the accepted E9.0
benchmark store. Its result is `nerva.lesson.evaluation.v1` with fixed
`evaluation_only` authority. This slice remains synthetic/hermetic and does not promote
a lesson, change recall or routing, write memory, authorize, execute, or mark work
complete.

## Experiment contract

`LessonEvaluationPlan` is frozen before either evaluator runs. It binds:

- the exact source Git revision and a detected runner/environment identity;
- distinct candidate and simple-baseline identities;
- an immutable fixture digest over question, context, truth, subgroup, proposal,
  development observations, and held-out observation;
- one shared item/character budget used by both evaluators;
- the privacy lane, quality/reliability thresholds, and subgroup non-regression
  rules;
- a predeclared retention deadline and artifact-only expiry behavior.

Development and held-out observation IDs, episode IDs, fingerprints, reference
IDs, and source-record identities must be disjoint. Every proposal is
revalidated with E6.0 `validate_proposal_evidence`. A synthetic-public case also
requires public proposal and observation evidence. Owner-private cases are
supported only by an explicitly detected owner-local environment and a
separately retained local suite; they cannot enter the CI lane.

## Oracle isolation and equal budgets

The E9.0 suite retains a content-free runner envelope. The answer runner receives
only a frozen `LessonRunnerInput`: case ID, question, bounded context, treatment
label, shared source-set digest, and the shared budget. It never receives an
expected answer, abstention truth, held-out observation, or another oracle field.

The baseline fills the shared context slots with raw synthetic evidence. The
candidate replaces one of those bounded slots with the proposed lesson; it does
not gain another slot or a larger character budget. Both receive the same
question and source-set identity. The proposed lesson is therefore the declared
treatment rather than hidden extra capacity.

## Honest classifications and gates

Raw answers and exception messages are not retained. The adapter scores outside
the answer runner and records one canonical classification reference:

- `correct`
- `abstained`
- `false_recall`
- `hallucinated_recall`
- `runner_error`
- `unverified_outcome`

Missing, stale, contradictory, and insufficient outcomes are visible and
unscored; their answer runners are not invoked. Candidate and baseline errors
are caught independently so one failing side cannot suppress evidence from the
other side.

Overall quality/reliability and explicit false/hallucinated-recall deltas must
meet the predeclared thresholds. Each subgroup must independently avoid quality,
reliability, false-recall, and hallucination regression. Consequently, aggregate
wins cannot hide a failed subgroup.

## Retention and integrity

The evaluator saves the immutable E9.0 suite, runs both identities through the
E9.0 harness, and appends the E9.0 run before it builds a pass/fail report. A
regression is therefore retained even when the command exits non-zero. Reports
bind the exact retained suite/run fingerprints, source revision, fixture digest,
plan, environment, evaluator identities, budgets, and privacy lane. Loading or
validating a report recomputes it from the retained records and rejects direct
construction, identity changes, fixture tampering, privacy drift, unknown
classifications, or inconsistent metric totals.

Eval Nightly runs only the fixed synthetic-public fixture. Its store and report
upload under `always()` and expire after 14 days. The job has no cache-save or
baseline-promotion step. Expiry describes deletion of the CI artifact only; it
does not delete or rewrite accepted E6.0 observations/proposals or E9.0 records.

## Authority and rollback

The report fixes all of the following to false: lesson promotion, memory write,
routing change, authorization, execution, and completion. Success is evidence
about this fixture set, not authority and not an owner-live benefit claim.

Rollback is one independently revertible package: remove the evaluator, its
count-neutral checks, this nightly job, and this document. E6.0 and E9.0 types,
stores, lifecycle records, and production behavior remain untouched.

## Residual risks

- The fixed synthetic fixture is small and may overfit the deterministic
  adapters; it does not prove owner workload benefit.
- Exact-answer scoring is deliberately narrow and does not establish semantic
  answer quality for a live model.
- Module-private construction guards are process boundaries, not cryptographic
  capabilities; integrity comes from recomputing the report against retained
  immutable-suite and append-only-run evidence.
- Artifact expiry is enforced by the CI host. Local operators remain responsible
  for deleting a separately retained owner-private artifact when its deadline is
  due.

E6 remains `BUILDING`; E6.1 proves only this bounded evaluation path.
