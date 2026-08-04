# Nerva 2.0 E9.0 — versioned benchmark contract and privacy-safe foundation

> **Status:** draft implementation for #784 · parent epic #767 · program #757 · blocker plan #778.  
> **Authority:** `evaluation_only`; no production routing, authorization, execution or completion authority.

## Outcome

This slice introduces the smallest reusable `nerva.benchmark.v1` substrate over the existing offline evaluation harness. It records what was tested, where it ran, which candidate and baseline were observed, what was measured, and what remains unknown—without turning benchmark output into production behavior.

The implementation reuses:

- `agents/core/observability/eval.py` for criterion scoring;
- `agents/core/observability/datasets.py` path and versioning patterns;
- the current `IntentRouter` as the first observed production-adjacent decision surface;
- the existing CI/local/live distinction rather than inventing a new authority lane.

## Included contract

`agents/core/observability/benchmark.py` defines:

- typed `BenchmarkCase`, `BenchmarkRun` and `BenchmarkResult` records under `nerva.benchmark.v1`;
- explicit task, route, model, provider, host and hardware dimensions;
- separate quality, baseline quality, latency, cost, reliability, privacy and resource evidence;
- honest `measured`, `not_measured`, `not_applicable` and `failed` states;
- criterion-less cases as `unscored`, never fabricated passes;
- privacy classes and allowed execution lanes;
- a versioned JSONL suite store and append-only run evidence retaining negative and failed runs;
- a transparent exact keyword/phrase baseline and an adapter that observes the existing router without changing its returned decision;
- stable structural fingerprints that exclude run IDs, timestamps and measured values.

Retained run evidence contains response digests and lengths, not raw response text or exception messages. Exception evidence is restricted to bounded canonical class identifiers such as `RuntimeError`; message-like, multiline and oversized values fail closed. Suite definitions retain fixture text because cases must be replayable; owner-private fixtures can be serialized and executed only in an explicit local lane.

## Privacy and execution lanes

| Privacy class | CI | Local | Cloud | Rule |
|---|---:|---:|---:|---|
| `synthetic_public` | caller-declared | caller-declared | caller-declared | Contains no owner data. |
| `sanitized_public` | caller-declared | caller-declared | caller-declared | Sanitization remains an explicit producer responsibility. |
| `owner_private_local` | denied | required | denied | Allowed lanes must be exactly `local`; serialization without an explicit local lane fails closed. |

The store validates the lane before creating a suite and again before recording run evidence. A run must cover the suite's case IDs exactly, and each retained result must preserve the stored case's immutable `task_type` and `privacy_class`. Reusing a valid case ID while changing either field is rejected before append.

## Retained measurement invariants

Versioned result deserialization validates each metric at its own semantic boundary:

- quality, baseline quality and reliability are numeric `ratio` values in `[0, 1]` when measured;
- latency is a finite non-negative numeric `ms` value;
- cost is a finite non-negative numeric `usd` value;
- privacy is one of the declared classification values and uses the `classification` unit;
- resources use typed, uniquely named numeric measurements;
- `failed` evidence carries a canonical source but no value or unit;
- `passed`, `failed`, `unscored` and `error` states must agree with pass flags, candidate evidence and quality evidence;
- candidate errors may retain only a canonical `error_type` and cannot claim candidate evidence;
- baseline errors require absent baseline evidence, failed baseline-quality evidence and a canonical `baseline_error_type`.

These checks apply on object construction and on JSON round trip, so arbitrary free text, mismatched units, out-of-range ratios and inconsistent status combinations cannot enter retained canonical evidence.

## Security and authority boundary

Every `BenchmarkRun` is fixed to:

```text
authority = evaluation_only
can_change_routing = false
can_authorize = false
can_execute = false
can_mark_complete = false
```

Deserialization rejects modified authority flags and summary drift. Benchmark code has no production-routing mutation path and does not import the Action Kernel, task worker, promotion path or approval queue. Ultron / `nerva.action.v1` remains the sole privileged-action authority.

The router adapter calls the existing `classify()` method and records the returned primary route. It does not wrap, replace or update the production router. The simple baseline is deliberately transparent and deterministic; benchmark results may inform a later reviewed proposal but cannot apply one.

## Test evidence in this slice

`tests/test_nerva_benchmark_e9_0.py` covers:

- case/run schema round trips and digest, authority and summary tamper rejection;
- owner-private local-only enforcement before storage;
- separate candidate/baseline route, model, provider, host and hardware evidence;
- criterion-less unscored behavior;
- negative and runner-error retention without exception-message leakage;
- hostile exception-type deserialization and error/baseline semantic drift;
- metric-specific type, unit, range, privacy-classification and failed-state rejection;
- typed and unique resource evidence;
- exact suite/run case coverage plus task/privacy metadata binding;
- path escape and non-finite measurement rejection;
- stable result-structure fingerprints;
- the real current `IntentRouter` measured against a transparent keyword baseline on privacy-safe route fixtures.

CI evidence is software evidence only. It is not owner-hardware, cloud-provider, energy, live reliability or migration proof.

## Documentation consistency

The twelve focused tests change the repository's canonical backend-test count. `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md` and `STATUS.md` are refreshed in this PR by the existing `scripts/status_sync.py` generator. These five files are mechanical status outputs coupled to the same test surface and rollback; they do not add another feature, epic or authority change.

## Explicit exclusions

This package does **not** add:

- automatic model, provider, route or capability migration;
- production routing changes or scored-selector authority;
- cloud execution or owner-private fixture upload;
- nightly scheduling, dashboards or migration recommendations;
- E12 calibration, ablation or advanced-method adoption claims;
- Synapse acquisition binding or capability promotion;
- owner-live reliability, energy or real-workflow value claims.

## Residual risks

- fixture sensitivity classification cannot be inferred perfectly from free text;
- response digests remain linkable evidence and should not encode secrets through predictable fixtures;
- JSONL append operations are local-process primitives, not a distributed transaction system;
- the first baseline is intentionally simple and validates the contract, not router superiority;
- latency from the in-process adapter includes harness overhead and is not a hardware benchmark;
- provider, cost, energy and live reliability remain unknown until a separately governed runner supplies measured evidence;
- a benchmark recommendation still requires normal review, policy and rollback evidence before any production change.

## Rollback

Revert the three E9.0 source/test/document files together with the five mechanically generated status surfaces. This removes the benchmark contract and restores the prior canonical test-count metadata. Existing `EvalHarness`, `DatasetStore`, reality harness, current router and stored runtime data remain unchanged. No migration or compensating action is required.

## Next coherent package

After independent acceptance, use `nerva.benchmark.v1` in one separate E9.1 package to persist a bounded current-router/Cortex shadow suite through the existing scheduled evaluation lane and report regressions without changing production routing. Synapse acquisition binding may consume the accepted benchmark contract in its own independently reversible E8 package; it must remain quarantined and cannot bundle promotion or action authority.
