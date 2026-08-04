# Nerva E9.1 — scheduled current-router shadow comparison and regression report

Status: draft implementation evidence for #807 / #767. This document does not
claim owner-hardware performance, provider comparison, migration recommendation
or Research Lab epic completion.

## Purpose

E9.1 runs one bounded current-router/Cortex shadow benchmark through the
repository's existing scheduled evaluation lane, retains reproducible evidence
through the accepted E9.0 store, and emits an honest regression report. It
proves scheduled operation and reporting only.

## Dependency and authority boundary

- prerequisites: accepted E9.0 / #784 / #803 and Cortex E1.1 / #792, both in `main`;
- base revision: `main@5bd996f83f9a5cca10fa49d0c680b851c18139e8`;
- report authority is fixed to `evaluation_only`;
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

```text
can_change_routing     = false
can_authorize          = false
can_execute            = false
can_promote_capability = false
can_mark_complete      = false
```

These are immutable `init=False` fields, so the ceiling is serialized into every
report payload.

## Reused implementation

- accepted `nerva.benchmark.v1` `BenchmarkCase`, `BenchmarkRun`, `BenchmarkStore`
  and `BenchmarkHarness` from `agents/core/observability/benchmark.py`;
- the accepted `current_router_runner()` deterministic adapter and the
  transparent `KeywordRouteBaseline`;
- the existing **Eval Nightly** workflow, its cache-restore/save pattern and its
  `$GITHUB_STEP_SUMMARY` reporting convention;
- the existing `tests/test_nerva_benchmark_e9_0.py` regression surface.

No second store, scorer, scheduler or permission system is introduced.

## The scheduled suite

`nerva-router-shadow` contains four `synthetic_public` route-selection cases
restricted to the `ci` lane. Owner-private, sanitized and provider-secret suites
remain separate local/live packages and cannot run here — `BenchmarkCase.enforce_lane()`
refuses them.

`ensure_suite()` saves a new version **only when the case content changes**. An
unchanged re-run reuses the existing version, so regression history never
compares across versions that never differed.

## Report

`nerva.benchmark.report.v1` binds each report to the suite name and version, the
exact `source_revision`, the run identifier, the candidate and baseline
identities, and an `EnvironmentProfile` (runner identity, platform, Python
version). `hardware_profile` is fixed at `not_measured`: a shared CI runner
cannot support a hardware claim.

Compared metrics are `quality_mean`, `baseline_quality_mean` and `pass_ratio`,
all higher-is-better. Each comparison carries one status:

```text
improved | regressed | unchanged | not_measured | no_baseline
```

**Only metrics genuinely measured on both sides decide a regression.** If either
side is unmeasured the comparison is `not_measured` and carries no delta;
`pass_ratio` is only computed when every case in the run was scored. The first
scheduled run, or a run whose predecessor used a different suite version, yields
`no_baseline` throughout and cannot claim a regression.

Report construction is deterministic: the same run and environment reproduce
byte-identical JSON.

## Failure behavior

`missing_prerequisites()` checks the declared software prerequisites — the
router import, construction, and the deterministic (`llm_classifier is None`)
lane. When any is missing, or the source revision cannot be resolved, the CLI:

- writes a visible `### Nerva E9.1 — FAILED` block to the job summary;
- exits with code `2`;
- retains **no** run for a suite that never executed.

A fabricated pass is impossible by construction. Negative, failed and unscored
case results are retained in the run evidence and remain visible in the summary
totals rather than being dropped.

`--fail-on-regression` makes a measured regression exit `1`. Without it the
regression is reported but not enforced.

## Workflow, permissions and retention

The `nerva-router-shadow` job runs in the existing Eval Nightly workflow on its
daily schedule, on `workflow_dispatch`, and on pull requests touching the
observability package or this lane. It declares least-privilege
`permissions: contents: read`.

Retention is the GitHub Actions cache at `.nerva-bench-cache/e9-1`, keyed on the
hashes of `scheduled_report.py` and `benchmark.py`. It holds only
synthetic-public suite content and run evidence — no owner data, no provider
secrets, no credentials. The baseline is saved only on a successful non-pull-request
run, so a pull request can never poison the scheduled baseline. A cache miss
degrades to `no_baseline`, never to a fabricated comparison.

The job writes to `$GITHUB_STEP_SUMMARY`; `--json-out` is available for local
runs and is not enabled in CI.

## Test surface and test-count neutrality

The repository pins its generated test count. Following the E3.0/E3.1/E6.0
convention, the bounded assertions live in `tests/_nerva_e9_1_checks.py` and are
invoked from the existing `tests/test_nerva_benchmark_e9_0.py` regression, so the
collected test count is unchanged (5767 before and after). Ten assertion groups
cover synthetic-public/CI-only enforcement, suite-version stability, persistence
through the accepted store, the first-run `no_baseline` state, regression and
improvement decisions, refusal to coerce unmeasured metrics, deterministic
evaluation-only reports, report invariants, visible prerequisite failure, and the
CLI path.

## What this slice is not

- not a production selector, route, model or provider change;
- not a Hermes/provider adapter or Synapse acquisition binding;
- not an automatic migration recommendation or promotion;
- not an owner-hardware, energy, GPU/NPU, cloud or live reliability claim;
- not a dashboard or HUD implementation;
- not E12 calibration;
- not Research Lab epic completion.

## Risks

Scheduled CI evidence can be mistaken for owner-live performance — the report
states its runner identity and a `not_measured` hardware profile to make that
misreading harder, but the misreading remains possible. Shared runners add
latency variance, which is why latency is not a compared metric here. The
four-case fixture is small and agreement can overfit. JSONL persistence through
the accepted store is not a distributed transaction log. Workflow artifacts can
retain linkable metadata.

## Rollback

Revert the suite/reporting module, the workflow job, the test helper, its
four-line invocation and this document as one unit. Accepted E9.0 contracts and
existing retained records are untouched; production routing and capability state
are unaffected. No data migration is required — deleting the cache key is
sufficient to discard retained scheduled evidence.

## Next coherent package

After E9.1 acceptance, choose separately between a local owner-hardware profile,
a provider comparison, or a real-task routing validation. Do not combine those
evidence lanes or any production adoption decision.
