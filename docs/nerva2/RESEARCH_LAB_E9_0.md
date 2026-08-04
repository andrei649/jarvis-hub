# Nerva 2.0 E9.0 — versioned benchmark contract and privacy-safe foundation

> **Status:** draft implementation for #784 · parent epic #767 · program #757 · blocker plan #778.  
> **Authority:** `evaluation_only`; no production routing, authorization, execution or completion authority.

## Outcome

This slice introduces the smallest reusable `nerva.benchmark.v1` substrate over the existing offline evaluation harness. It records what was tested, where it ran, which candidate and baseline were observed, what was measured, and what remains unknown—without turning benchmark output into production behavior.

The implementation reuses:

- `agents/core/observability/eval.py` for criterion scoring;
- DatasetStore path and versioning patterns;
- the current `IntentRouter` as the first production-adjacent surface;
- existing CI/local/cloud distinctions rather than inventing an authority lane.

## Canonical implementation

`agents/core/observability/benchmark.py` is the single canonical implementation and public contract. The historical private path `_benchmark_e9_0_base.py` is compatibility-only and re-exports the exact same classes and adapters. It contains no alternate implementation, subclass, monkey patch or weaker router path.

Consequently, direct private import and import order cannot bypass:

- deterministic-router provenance enforcement;
- baseline identity invariants;
- immutable authority flags;
- suite-case content fingerprint validation.

The canonical module exposes:

- typed `BenchmarkCase`, `BenchmarkRun` and `BenchmarkResult` records under `nerva.benchmark.v1`;
- explicit task, route, model, provider, host and hardware dimensions;
- separate quality, baseline quality, latency, cost, reliability, privacy and resource evidence;
- honest `measured`, `not_measured`, `not_applicable` and `failed` states;
- criterion-less cases as `unscored`, never fabricated passes;
- privacy classes and allowed execution lanes;
- versioned JSONL suites and append-only positive, negative and failed run evidence;
- a transparent exact keyword/phrase baseline;
- a fail-closed deterministic adapter for the existing router;
- stable structural fingerprints excluding run IDs, timestamps and measured values.

Retained run evidence contains response digests and lengths, not raw response text or exception messages. Exception evidence is restricted to bounded canonical class identifiers. Message-like, multiline and oversized values fail closed.

## Privacy and execution lanes

| Privacy class | CI | Local | Cloud | Rule |
|---|---:|---:|---:|---|
| `synthetic_public` | caller-declared | caller-declared | caller-declared | Contains no owner data. |
| `sanitized_public` | caller-declared | caller-declared | caller-declared | Sanitization remains an explicit producer responsibility. |
| `owner_private_local` | denied | required | denied | Allowed lanes must be exactly `local`. |

The store validates the lane before creating a suite and before recording run evidence. A run must cover the stored case IDs exactly.

## Immutable suite-case binding

Every `BenchmarkCase` carries a deterministic `content_fingerprint`. It binds all immutable evaluation semantics:

- schema and record kind;
- case ID and task type;
- SHA-256 prompt digest;
- privacy class and allowed lanes;
- criterion kind and expected value;
- tags and artifact references.

`BenchmarkHarness` copies that fingerprint into every result. `BenchmarkStore.record_run()` requires an exact match against the stored suite version in addition to matching `case_id`, `task_type` and `privacy_class`.

A result generated for one prompt or criterion therefore cannot be retained under a changed test with the same case ID and metadata. Hostile tests rewrite the stored prompt and criterion beneath an existing version and verify fail-closed rejection.

## Retained evidence invariants

Versioned construction and deserialization enforce:

- quality, baseline quality and reliability are numeric ratios in `[0, 1]` when measured;
- result status, pass flag and measured quality agree at the reused `EvalHarness` boundary: a score `>= 0.5` passes and a score `< 0.5` fails;
- latency is finite non-negative `ms`;
- cost is finite non-negative `usd`;
- privacy uses one declared classification value;
- resources are typed, numeric and uniquely named;
- failed evidence carries a canonical source but no value or unit;
- candidate and baseline errors retain only canonical exception class identifiers;
- baseline errors require absent baseline evidence and failed baseline-quality evidence;
- `baseline_id=None` forbids retained baseline evidence, baseline errors and measured/failed baseline quality;
- a declared `baseline_id` forbids `not_applicable` baseline quality;
- candidate-error runs skip the baseline explicitly as `not_measured`; they cannot retain baseline evidence or a fabricated baseline failure;
- stored results require an exact immutable suite-case content fingerprint.

These rules prevent anonymous baselines, contradictory pass/fail summaries and evidence attributed to altered tests.

## Router provenance boundary

`current_router_runner()` is intentionally a deterministic adapter. It requires the router to expose `llm_classifier` and requires that value to be `None` both when the adapter is created and immediately before every classification.

A configured or subsequently injected fallback therefore fails before `classify()` receives the fixture. An unexpected returned intent carrying `context.source == "llm_fallback"` is also rejected. Only after those checks may the adapter retain `model_id="none"`, `provider_id="local-deterministic"`, zero cost and `no_external_disclosure`.

The compatibility module exports this exact same function object. No old unguarded adapter remains importable.

This is deliberately narrower than measuring an LLM-backed router. A future runner that evaluates an LLM path must supply trustworthy actual model, provider, privacy and cost provenance rather than reuse this adapter.

## Security and authority

Every `BenchmarkRun` is fixed to:

```text
authority = evaluation_only
can_change_routing = false
can_authorize = false
can_execute = false
can_mark_complete = false
```

Deserialization rejects modified authority flags and summary drift. Benchmark code has no production-routing mutation path and does not import the Action Kernel, worker, promotion path or approval queue. Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Test evidence in this slice

`tests/test_nerva_benchmark_e9_0.py` preserves the twelve-test focused surface and covers:

- case/run round trips plus digest, fingerprint, authority and summary tamper rejection;
- exact `EvalHarness` pass-boundary behavior plus hostile rejection of passed/failed metadata that contradicts measured quality;
- owner-private local-only enforcement before storage;
- separate candidate/baseline route, model, provider, host and hardware evidence;
- criterion-less, negative and runner-error behavior;
- exception-message exclusion and hostile exception-type deserialization;
- metric-specific types, units, ranges and failed-state semantics;
- typed resource evidence and exact suite/result metadata binding;
- prompt and criterion drift beneath an existing suite version;
- path escape and non-finite measurement rejection;
- stable structural fingerprints;
- current-router comparison against a transparent simple baseline;
- configured and post-construction LLM fallbacks rejected without invocation;
- direct compatibility imports resolving to the canonical classes and adapter;
- anonymous baseline evidence, declared/not-applicable baselines and fabricated skipped-baseline failures rejected on round trip.

The nine unchanged tests remain in `tests/_nerva_benchmark_e9_0_base.py`; the adjusted structural-fingerprint regression and two bounded independent-review regressions are collected through the public test module. CI remains software evidence only, not owner-hardware, provider, energy or live-workflow proof.

## Documentation consistency

The focused collection remains **twelve tests**, so the five generated status surfaces already present in this PR remain numerically correct. `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md` and `STATUS.md` continue to report backend count `5,767`. No additional status-count churn is required for this correction.

`BACKLOG.md` remains unchanged because this draft does not change accepted delivery truth.

## Explicit exclusions

This package does **not** add:

- automatic model, provider, route or capability migration;
- production routing changes or scored-selector authority;
- cloud execution or owner-private fixture upload;
- nightly scheduling, dashboards or recommendations;
- E12 calibration or advanced-method adoption claims;
- Synapse acquisition, promotion or privileged action;
- owner-live reliability, energy or real-workflow value claims.

## Residual risks

- fixture sensitivity classification remains a producer responsibility;
- response digests remain linkable and unsuitable for predictable secrets;
- JSONL append is a local-process primitive, not a distributed transaction log;
- the first baseline validates the contract rather than proving router superiority;
- in-process latency includes harness overhead;
- provider, cost, energy and live reliability remain unknown for non-deterministic runners;
- the schema is unmerged and intentionally has no migration compatibility promise yet.

## Rollback

Revert together:

- the canonical `benchmark.py` implementation and compatibility-only `_benchmark_e9_0_base.py`;
- `test_nerva_benchmark_e9_0.py` and its reused private test support module;
- this document;
- the five mechanically generated status surfaces already included in the E9.0 candidate.

That atomic revert removes the benchmark contract and restores prior status metadata. Existing evaluation code, current routing and production data remain unchanged; no migration or compensating action is required.

## Next coherent package

First, complete fresh independent integration review of the unchanged exact head after the full CI matrix is green.

After independent acceptance only, E9.1 may persist one bounded current-router/Cortex shadow suite through the existing scheduled evaluation lane and report regressions without changing production routing. Synapse acquisition binding remains a separate E8 package and must preserve quarantine.
