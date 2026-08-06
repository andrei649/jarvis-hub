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
IDs, and source-record identities must be disjoint across the complete plan,
not only within one case. Development and held-out observation/evidence
timestamps cannot postdate the declared evaluation time. Every proposal is
created no later than evaluation and strictly before every held-out evidence
timestamp, preventing retrospective post-outcome proposal leakage. Every proposal
is revalidated with E6.0 `validate_proposal_evidence`. A synthetic-public case also
requires public proposal and observation evidence. Owner-private cases are
supported only by an explicitly detected owner-local environment and a
separately retained local suite; they cannot enter the CI lane.

Immediately before any store or runner mutation, the evaluator re-detects the
host Python, platform system, and machine for the declared runner/evidence lane.
A copied environment with caller-forged host fields is rejected.

## Oracle isolation and equal budgets

The E9.0 suite retains a content-free runner envelope. The answer runner receives
only a frozen `LessonRunnerInput`: case ID, question, bounded context, treatment
label, shared source-set digest, and the shared budget. It never receives an
expected answer, abstention truth, held-out observation, or another oracle field.

The baseline fills the shared context slots with raw synthetic evidence. The
candidate deterministically replaces one selected source slot with the proposed
lesson; it receives exactly the same number of items and never gains another
slot or a larger character budget. Both receive the same
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
validating a report uses strict JSON decoding, recomputes it from the retained
records, and rejects duplicate members, non-finite values, direct construction,
identity changes, fixture tampering, privacy drift, unknown classifications, or
inconsistent metric totals.
The E6 boundary reads the exact retained suite bytes and every retained run JSONL
record with the same strict duplicate/non-finite policy before constructing E9
types. Only strictly parsed records are canonically reserialized into the
accepted E9 run constructor; its permissive decoder never receives raw retained
bytes.

Every existing suite version and every retained run are strict-scanned before a
new suite version, runner call, or run record can change the store. The effective
run ID is generated when needed, validated, and collision-checked against that
same strict preflight snapshot before case materialization, suite save, or runner
callbacks. The report path is resolved and must be disjoint from the retained
evidence store before evaluation starts.
Report outputs are create-once: an existing path, including a hardlink alias, is
rejected. Before any store mutation, the exact output namespace is reserved as
an exclusively created empty directory, which cannot be hardlinked into retained
files. After the evaluator returns, its directory identity and unchanged emptiness
are verified before a non-recursive removal and immediate exclusive file create.
No evaluator callback remains when report bytes are written. On evaluator failure,
only a still-owned, unchanged, empty reservation is removed; callers then choose
a fresh path.

Eval Nightly runs only the fixed synthetic-public fixture. Its store and report
upload under `always()` and expire after 14 days. The job has no cache-save or
baseline-promotion step. Expiry describes deletion of the CI artifact only; it
does not delete or rewrite accepted E6.0 observations/proposals or E9.0 records.
The fixture uses a deterministic logical fixture time, so identical source
revision and runner identity produce stable fixture, suite, and plan digests.
The actual predeclaration and expiry timestamps remain separate wall-clock retention
metadata; their exact values still bind the retained run and reconstructed report.

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
