# Nerva E1.2a Measured Route-Adequacy Contract Design

## Goal

Add the owner-local, evaluation-only contract needed to measure the deterministic
current router against explicit acceptable-route labels while reusing accepted E9
benchmark evidence. The package must make latency, provider charge, privacy,
provenance, incompleteness, and authority boundaries explicit without reading owner
telemetry automatically or changing production routing.

This is the code-contract half of E1.2. A representative evidence run remains a
separate owner-gated movement because the repository does not contain the required
historical tasks, labels, sampling rule, retention policy, or permission to execute
against private data.

## Ground Truth

- Base: `main@4ba1ac26d05c8371ce89d6663a7d7f51457093b6`.
- Child issue: #841; parent Cortex epic: #759; program: #757; blocker plan: #778.
- No open pull request, E1.2 issue, or E1.2 remote branch existed when #841 was
  reserved.
- E1.1/#793 provides `nerva.cortex.comparison.v1` and the observation-only
  `ShadowDecisionRouter`/`nerva.decision.v1` seam.
- E9.0/#803 provides the canonical `BenchmarkCase`, `BenchmarkHarness`,
  `BenchmarkRun`, `BenchmarkStore`, measurement, privacy-lane, and
  `current_router_runner` contracts.
- E9.1/#809 provides detected environment evidence and a scheduled synthetic
  comparison. Its CI fixtures are infrastructure evidence, not representative
  owner-task evidence.
- E1 remains `building`; B2 remains partial; release readiness remains false; Ultron
  remains the sole privileged-action authority.

## Alternatives Considered

### 1. Owner-local adapter over retained E9 runs — selected

Add a separate Cortex label/runner/report layer while leaving E9 schemas and the
production router unchanged. The layer reads an explicitly supplied local label
file, uses E9 to execute and retain five comparable runs, and emits only bounded
aggregate evidence. This reuses the strongest existing integrity and privacy
boundaries and has a coherent one-revert rollback.

### 2. Mine cognition traces, run history, cost tracking, or learning rows — rejected

Those stores can contain private previews and ambiguous labels. Existing `success`
often means only that no structured error occurred, and cost data can be estimated or
aggregate rather than a per-route receipt. Mining them would silently change privacy,
retention, and outcome semantics.

### 3. Instrument and persist the live router — rejected

New hot-path timing, trace persistence, or selector logic would modify production
behavior and create a wider privacy and rollback boundary. E1.2a needs neither a new
store nor a production construction-path change.

## Semantic Boundary

The only quality label in this package is **primary-route adequacy**: whether the
actual primary route is a member of an owner-declared acceptable-route set. Multiple
routes may be acceptable. Route adequacy is not answer quality, executed-task
completion, safety proof, user value, or selector superiority.

The label file is owner-declared local evidence, not cryptographic attestation. The
report binds what was declared and measured; it does not prove that a human reviewed
the labels. A later E1.2b movement may attach owner review evidence without changing
this package's authority.

## Scope

### In scope

1. Strict owner-local route-label parsing and content fingerprinting.
2. Conversion to accepted E9 benchmark cases without committing owner prompts. E9
   necessarily persists those prompts in its owner-local suite file before retaining
   runs, so the explicit store root shares the same owner retention boundary.
3. A current-router runner that captures exactly one `DecisionRecord`, retains its
   fingerprint, and scores `accepted` or `rejected` separately from the actual route.
4. One unretained warm-up followed by exactly five retained, comparable runs.
5. A deterministic report over retained evidence with latency median/p95, provider
   charge, route-adequacy aggregates, incompleteness, privacy, and immutable authority.
6. JSON and Markdown output that contain no raw prompt, source-record identifier,
   free-form note, or exception message.
7. Owner-task, M1 delivery, program-manifest, backlog, and test documentation needed
   to keep repository and GitHub truth aligned.

### Non-goals

- No production selector, routing-table, orchestrator, model, provider, workflow,
  endpoint, HUD, mobile, Action Kernel, or Ultron change.
- No automatic telemetry discovery, second persistence implementation, scheduled
  owner-data job, or CI upload of local evidence. The accepted E9 store remains the
  only persistence path.
- No real-task fixture or generated owner report committed to Git.
- No cost claim for CPU/GPU/NPU, energy, hardware, downstream agents, tools, actions,
  or the full task.
- No claim that the current router beats another selector; no alternate selector
  exists in this slice.
- No E1, Night Shift, Nerva program, or release completion claim.

## Architecture

### Label contract

Create `agents/core/cortex_measured_compare.py` with two input records:

- `RouteLabelCase`: bounded canonical `case_id`, raw text held in local memory and in
  the explicitly approved owner-local E9 suite file, `owner_private_local` privacy,
  non-empty unique acceptable primary routes, canonical task category, and a lowercase
  64-hex source-record digest. Its normalized request digest is derived only through
  `DecisionRequest.from_input(text, {}).text_digest`, never caller-supplied or
  reimplemented.
- `RouteLabelSet`: schema `nerva.cortex.route-label-set.v1`, canonical ID, bounded
  sampling rule, canonical UTC source window, explicit `owner_attested=true`, bounded
  retention-policy ID, and at least 20 cases. Its content fingerprint covers every
  semantic field through request/source digests without exposing raw text.

`load_route_label_set(path, allowed_routes=...)` accepts exact JSON fields only. It
rejects symlinks/non-files, BOM/invalid UTF-8, duplicate JSON keys, floats/non-finite
numbers, unknown fields, invalid timestamps, duplicate case IDs or normalized request
digests, fewer than 20 cases, non-local privacy, missing attestation/policy/sampling
metadata, malformed source digests, and any acceptable route outside the supplied
current route registry. The label file remains caller-owned and is never written by
the module. Its `retention_policy_id` covers the label file and every derived local
suite, run, JSON report, and Markdown report artifact.

`build_owner_route_suite(label_set)` returns one E9 `BenchmarkCase` per label, all
fixed to `owner_private_local`, `allowed_lanes=("local",)`, and an exact `accepted`
criterion. Case artifact references contain only the label-set and case fingerprints,
not local paths or source identifiers. `ensure_owner_route_suite(store, label_set)`
reuses the latest stored version only when ordered case IDs and content fingerprints
match exactly; otherwise it writes a new E9 suite version. This accepted E9 write
persists raw prompt text in `<explicit-store-root>/suites/<suite>/vN.jsonl`.

### Measured current-router runner

`measured_current_router_runner(router, agents, label_set)` composes rather than
reimplements:

1. `ShadowDecisionRouter` captures `DecisionRecord` values into an invocation-local
   list.
2. E9 `current_router_runner` performs the deterministic classification and enforces
   `llm_classifier is None` both before and during every call.
3. The adapter requires exactly one shadow record, verifies that its selected route
   equals the E9 observation route, and verifies that the prompt digest selects exactly
   one label.
4. It returns a copied `BenchmarkObservation` whose scoring response is `accepted` or
   `rejected` and whose artifact references include only the decision fingerprint.

The retained E9 candidate evidence continues to carry the actual route ID. Scoring
output therefore cannot replace or conceal the actual route. Initial or late-injected
LLM fallback fails before prompt disclosure to a model.

### Run batch

`run_measured_comparison(..., store_root: Path, ...)` requires a non-default,
explicitly supplied owner-approved local root, constructs `BenchmarkStore(store_root)`,
detects one E9.1 `EnvironmentProfile`, ensures the immutable E9 suite, performs one
warm-up that is never stored, then performs exactly five retained E9 runs. It never
falls back to `BenchmarkStore()` or `data_path("benchmarks")`. It fixes the lane to
`local`, candidate identity to
`current-router-e1.2a`, baseline to none, and source revision to an exact lowercase
commit SHA. Run IDs include the label fingerprint and repetition index; each run still
retains its own timestamps and canonical fingerprint.

The function returns a guarded `MeasuredRunBatch`, not a plain caller-assembled tuple.
The batch binds the label fingerprint, suite name/version, environment, source
revision, repetition count, and retained run fingerprints. The guard is a module
capability rather than a cryptographic boundary; documentation states that code
executing inside the module is trusted.

### Report

`build_measured_report(batch, store, label_set)` first rebuilds the expected E9 cases
from the label set, loads the exact stored suite version, and proves ordered case IDs
and content fingerprints match exactly. It then proves that every run is present in
the supplied E9 store and that all runs have identical suite version, revision,
candidate/baseline identity, local lane, case fingerprints, and result coverage. Run
agreement alone is insufficient because a mutually consistent run set could otherwise
be unrelated to the supplied labels.

`MeasuredComparisonReport` uses schema
`nerva.cortex.measured-comparison.v1` and records:

- exact source revision, suite/version, label-set fingerprint, detected environment,
  five retained run fingerprints, unique task count, and sample count;
- aggregate and per-route adequacy, rejection count, error count, and incomplete
  count;
- latency median and nearest-rank p95 in milliseconds, sourced only from measured
  E9 `benchmark.harness` values;
- provider charge in USD, measured as zero only when every candidate proves
  `model_id=none`, `provider_id=local-deterministic`, no baseline/provider fallback,
  and an E9 `candidate.runner` cost measurement;
- explicit `not_measured` values for executed-task outcome quality, compute, energy,
  hardware, downstream-agent, tool, and action cost;
- immutable `evaluation_only`, `can_change_routing=false`, `can_authorize=false`,
  `can_execute=false`, `can_promote=false`, and `can_mark_complete=false` fields.

An adequacy rejection is valid negative evidence and does not make a run incomplete.
An error, unscored result, missing measurement, coverage mismatch, or mixed identity
does. An incomplete batch cannot serialize as complete measured evidence.
Warm-up `error`/`unscored` results abort before any run retention. During the five
measured repetitions, however, `error`/`unscored` results are retained and
fingerprint-proved as evidence; Task 4 reports the resulting batch with
`complete=false` rather than censoring those runs.

The report is constructed only through the builder guard. `from_json()` accepts exact
fields and recomputes authority, counts, numeric ranges, fingerprints, and internal
relationships; caller-supplied authority or completeness drift is rejected. Canonical
JSON uses sorted keys and fixed separators. Markdown renders only IDs, fingerprints,
aggregate measurements, limitations, and owner gates.

## Data Flow

```text
ignored owner-local label JSON
  -> strict RouteLabelSet in memory
  -> owner-private E9 BenchmarkCase suite
  -> raw prompts persisted in explicit owner-local suite vN.jsonl
  -> warm-up (discarded)
  -> 5 x ShadowDecisionRouter + current_router_runner
  -> retained BenchmarkRun records in owner-local runs.jsonl
  -> retained-run and label-set validation
  -> privacy-minimised owner-local JSON/Markdown MeasuredComparisonReport
```

Raw input is present in the caller-owned label file and the E9 suite copy required for
retention. It does not enter `runs.jsonl`, JSON reports, or Markdown reports. The module
does not select a default label/store path, scan a data directory, or upload an
artifact.

## Failure Behavior

- Missing/malformed/unsafe label file: fail before router construction.
- Missing, implicit, symlinked, or otherwise unsafe store root: fail before persisting
  the suite; never fall back to the repository's default benchmark path.
- Fewer than 20 unique tasks or incomplete labels: fail before warm-up.
- Configured or late-injected LLM: fail before model invocation and before retention.
- Zero/multiple shadow records or route mismatch: retain no successful sample for that
  invocation; the package is incomplete.
- Warm-up `error`/`unscored`: retain no measured run or batch.
- Retained measured `error`/`unscored`: preserve all five runs as incomplete evidence;
  do not reinterpret them as a write failure.
- Exception before a retained run exists, run-ID collision, retained-run write
  failure, or retrieval/fingerprint-proof failure: stop and return no batch; do not
  summarize an in-memory subset.
- Mixed identity/environment/revision/suite: refuse aggregation.
- Non-deterministic/provider-backed evidence: provider charge becomes unavailable and
  the batch cannot claim the deterministic zero-provider-charge contract.
- Negative adequacy: retain and report it; never drop it to improve the score.
- Report/output write failure: leave production routing untouched; no fallback writer
  or alternate path is introduced.

## Privacy and Authority

The owner supplies both the label-file path and E9 store root explicitly. Every case is
local-only and the E9 lane guard rejects CI/cloud execution. Raw prompts exist in the
caller-owned label file, process memory, and the required owner-local E9 suite
`vN.jsonl`; `runs.jsonl` and reports retain only privacy-minimised evidence. The named
retention/access/deletion policy covers all five artifact classes: label file, suite,
runs, JSON report, and Markdown report. Fingerprints remain pseudonymous/linkable and
are not anonymous.

The label file may say `owner_attested=true`, but this is a typed declaration, not
proof of consent or label correctness. The owner task remains open until the owner
actually supplies/approves the dataset and local run.

The module produces evaluation evidence only. It is not imported by the orchestrator,
router boot path, worker, Action Kernel, or capability-promotion path.

## Test Design

Add `tests/_nerva_e1_2_checks.py` and invoke it from the existing
`test_existing_weather_routes_to_friday` test so the collected test count remains
unchanged. Tests use temporary synthetic stand-ins that exercise the owner-local
schema but are never described as representative evidence.

The red/green matrix covers:

1. fewer than 20 tasks, duplicate IDs/digests, non-local privacy, missing attestation,
   retention/sampling/source metadata, and empty/duplicate/unregistered routes;
2. duplicate JSON keys, extra fields, BOM/invalid UTF-8, symlink/non-file input, floats,
   non-finite values, malformed timestamps/digests, and oversized strings;
3. initial and late-injected LLM fallback before classification;
4. exactly one decision record per sample, matching actual route and decision
   fingerprint;
5. raw prompt/source/note/exception-message absence from JSON and Markdown;
6. warm-up exclusion, five retained repetitions, deterministic median and nearest-rank
   p95;
7. mixed revision/suite/environment/repetition refusal, unretained-run refusal, exact
   stored-suite-to-label case/fingerprint binding, and refusal to use an implicit
   default store;
8. zero provider charge only under deterministic local evidence, with every other cost
   dimension explicitly unmeasured;
9. retained negative adequacy versus incomplete error/unscored evidence;
10. canonical replay, strict deserialization, authority/completeness tamper refusal,
    and no selector-superiority/end-to-end claims;
11. E1 remains `building`, the JSON manifest and generated Markdown agree, and workflow
    paths cover the new referenced artifact.

Focused verification includes router E1.1, E9.0/E9.1, the B2 manifest checker, Ruff,
targeted Bandit, compile, and `git diff --check`. Before integration, run the combined
adjacent suite and complete exact-head hosted CI/security matrix.

## Files and Ownership

- Create `agents/core/cortex_measured_compare.py`: strict input, adapter, batch, report,
  serialization, and rendering.
- Create `tests/_nerva_e1_2_checks.py`: bounded red/green and adversarial assertions.
- Modify `tests/test_router_v2.py`: one helper import and invocation.
- Create `docs/nerva2/CORTEX_E1_2.md`: contract, limitations, local operation,
  migration, and rollback.
- Modify `docs/OWNER_TASKS.md`: the five owner inputs for E1.2b.
- Modify `docs/nerva2/M1_DELIVERY.md`: contract-ready versus evidence-blocked truth.
- Modify `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json` and regenerate
  `NERVA_PROGRAM_MANIFEST_V1.md`: add the E1.2a reference while retaining E1
  `building` and release false.
- Modify `.github/workflows/nerva-roadmap.yml` if required by the manifest checker's
  complete referenced-path filter contract.
- Modify `BACKLOG.md`: record only factual contract state and the owner evidence gate;
  do not mark E1 complete.

No generated status file changes unless the canonical status tool reports a genuine
derived difference.

## Delivery and Rollback

Use branch `nerva2/e1-2a-measured-route-contract` and one draft PR. Keep design/plan,
implementation, and factual ledger integration as reviewable commits. The PR closes
#841 only after code acceptance and leaves #759/#757/#778 open.

Rollback is one coherent revert of the adapter/report, helper invocation,
documentation, owner-task entry, and factual manifest/backlog references. E1.0,
E1.1, E9.0, E9.1, and production routing remain untouched. A Git revert does not
delete owner-private label, suite, run, or report artifacts; those follow the named
retention/deletion policy at the explicitly supplied local root. No production schema
migration or compensating action is required.

## Acceptance Boundary

Autonomous acceptance can prove the contract, hostile tests, privacy-minimised output,
E9 reuse, manifest integrity, and absence of production/authority changes. It cannot
prove representative owner evidence.

E1.2b remains blocked until the owner provides or approves all five inputs:

1. at least 20 historical Nerva tasks in an ignored local path;
2. acceptable-route labels and task categories;
3. a predeclared sampling and exclusion rule;
4. retention, access, and deletion policy;
5. permission to execute the local run on the owner host.

Until then, documentation must say `contract_ready`, `owner_evidence_blocked`, and
`real_task_outcome_quality=not_measured`.
