# Nerva E1.2a Measured Route-Adequacy Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the strict, owner-local, evaluation-only E1.2a contract that can measure current-router primary-route adequacy over an owner-approved set of at least 20 historical tasks while keeping the actual evidence run blocked on the five missing owner inputs.

**Architecture:** Add one Cortex adapter/report module over the accepted E1.1 decision seam and E9.0/E9.1 benchmark contracts. The module strictly loads an explicit owner-local label file, persists its raw prompts only through an explicitly rooted E9 store, performs one discarded warm-up plus exactly five retained deterministic runs, and builds a privacy-minimised report that is bound back to the stored suite and runs. It is never imported by a production routing, orchestration, action, promotion, endpoint, or scheduled-job path.

**Tech Stack:** Python 3.12 dataclasses and standard library; `DecisionRequest`, `ShadowDecisionRouter`, E9 `BenchmarkCase`/`BenchmarkHarness`/`BenchmarkStore`, E9.1 `EnvironmentProfile`; pytest helper assertions; Ruff, Bandit, compileall, manifest checker, and GitHub Actions.

## Global Constraints

- Work only in `nerva2/e1-2a-measured-route-contract` and draft PR #842, based on `main@4ba1ac26d05c8371ce89d6663a7d7f51457093b6`.
- Keep the primary checkout and its `docs/qa-runs/2026-07-27-run3.md` state untouched.
- Refresh the component locks before edits or commits; release them only after the PR is integrated or explicitly parked.
- Do not modify E1.1, E9.0/E9.1 serialized schemas, the orchestrator, Action
  Kernel, Ultron, endpoints, HUD/mobile, or scheduled owner-data execution. The
  exact-head security HOLD in Task 6 Step 3a explicitly authorizes narrow edits to
  `agents/core/router.py`, `agents/core/cortex_decision.py`, and
  `agents/core/observability/benchmark.py` only for the no-LLM capability and strict
  parser invariants; production `classify()` semantics and serialized fields must not
  change.
- Do not add a real-task fixture, prompt, source identifier, local evidence path, or generated owner report to Git.
- The label file, E9 suite `vN.jsonl`, `runs.jsonl`, JSON report, and Markdown report all belong to the same named owner retention/access/deletion policy. A Git revert does not delete them.
- Primary-route adequacy is the only quality claim. It is not answer quality, task completion, safety, user value, or selector superiority.
- Keep E1 `building`, B2 partial/live enforcement open, E1.2b owner-blocked, and release readiness false.
- Preserve the repository's collected count of 6052 tests by invoking one synchronous helper from the existing `test_existing_weather_routes_to_friday` test.
- Use the repository Python from the worktree root as `& ..\..\.venv\Scripts\python.exe`; ambient Python is not accepted evidence.

---

## Task 1: Strict route-label contract and E9 suite binding

**Files:**

- Create: `agents/core/cortex_measured_compare.py`
- Create: `tests/_nerva_e1_2_checks.py`
- Modify: `tests/test_router_v2.py`

- [ ] **Step 1: Add the helper hook without adding a collected test**

Add `from _nerva_e1_2_checks import run_e1_2_checks` beside the E1.1 helper import, then call `run_e1_2_checks()` immediately after `run_e1_1_checks()` in `test_existing_weather_routes_to_friday`.

Create `tests/_nerva_e1_2_checks.py` with one public synchronous entry point:

```python
def run_e1_2_checks() -> None:
    _check_strict_route_labels()
    _check_suite_binding()
```

Keep all helpers prefixed with `_`; do not add `test_*` functions or pytest parameterization in this file.

- [ ] **Step 2: Write red tests for the exact label schema**

Use a temporary directory and a synthetic 20-case JSON document with this exact external shape:

```json
{
  "schema": "nerva.cortex.route-label-set.v1",
  "label_set_id": "owner-history-2026-08",
  "sampling_rule": "consecutive-distinct-eligible-tasks",
  "source_window": {
    "start": "2026-07-01T00:00:00.000Z",
    "end": "2026-07-31T23:59:59.000Z"
  },
  "owner_attested": true,
  "retention_policy_id": "owner-local-e1-2-v1",
  "cases": [
    {
      "case_id": "task-001",
      "text": "synthetic weather request 001",
      "privacy_class": "owner_private_local",
      "acceptable_primary_routes": ["friday"],
      "task_category": "weather",
      "source_record_digest": "<64 lowercase hex>"
    }
  ]
}
```

Assert the loader rejects, one mutation at a time:

- 19 cases; duplicate `case_id`; duplicate `DecisionRequest.from_input(text, {}).text_digest` after whitespace/case normalization; duplicate source-record digests;
- missing/false owner attestation, empty sampling rule, empty retention-policy ID, reversed or non-canonical UTC source window;
- any privacy value except `owner_private_local`;
- empty, duplicate, non-canonical, or unregistered acceptable route IDs;
- malformed source digest, missing exact fields, extra fields at the root/window/case levels;
- duplicate JSON keys, a UTF-8 BOM, invalid UTF-8, a float or `NaN`/`Infinity`, oversized strings, a directory, and a symlink when the platform permits it.

Assert a valid file loads with 20 ordered cases, raw `text` excluded from `repr`, request digests equal `DecisionRequest.from_input(text, {}).text_digest`, acceptable routes canonicalized to a sorted tuple, and stable case/label fingerprints that do not contain raw text.

- [ ] **Step 3: Run the focused test and confirm RED**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday -q
```

Expected: fail during import because `agents.core.cortex_measured_compare` or its contract symbols do not exist. Record that failure in the implementation notes; do not weaken an assertion to obtain green.

- [ ] **Step 4: Implement bounded input records and a strict loader**

In `agents/core/cortex_measured_compare.py`, define:

```python
MIN_OWNER_TASKS = 20
RETAINED_REPETITIONS = 5
LABEL_SCHEMA = "nerva.cortex.route-label-set.v1"
REPORT_SCHEMA = "nerva.cortex.measured-comparison.v1"
CANDIDATE_ID = "current-router-e1.2a"

@dataclass(frozen=True, repr=False)
class RouteLabelCase:
    case_id: str
    text: str = field(repr=False)
    acceptable_primary_routes: tuple[str, ...]
    task_category: str
    source_record_digest: str = field(repr=False)
    privacy_class: str = field(default="owner_private_local", init=False)
    request_digest: str = field(init=False)
    content_fingerprint: str = field(init=False)

@dataclass(frozen=True)
class RouteLabelSet:
    label_set_id: str
    sampling_rule: str
    source_window_start: str
    source_window_end: str
    owner_attested: bool
    retention_policy_id: str
    cases: tuple[RouteLabelCase, ...]
    schema: str = field(default=LABEL_SCHEMA, init=False)
    content_fingerprint: str = field(init=False)
```

Expose the exact loader signature `load_route_label_set(path: str | Path, *,
allowed_routes: Collection[str]) -> RouteLabelSet`.

Implementation requirements:

- Parse bytes only from an existing, non-symlink regular file with strict UTF-8 and no BOM.
- Use `json.loads(..., object_pairs_hook=...)` to reject duplicate keys and `parse_float`/`parse_constant` callbacks that reject every float and non-finite literal before dataclass construction.
- Require exact key sets at all three object levels. Reject booleans where an integer/string is expected and reject control characters, newlines, path separators, non-canonical identifiers, and strings over their documented bounds.
- Accept timestamps only in canonical UTC RFC 3339 millisecond form and require `start <= end`.
- Derive the normalized request digest only with `DecisionRequest.from_input(text, {}).text_digest`.
- Canonicalize acceptable routes to a sorted tuple only after rejecting duplicates; validate them against a non-empty canonical `allowed_routes` collection supplied by the caller.
- Fingerprint canonical, compact, sorted-key JSON. A case fingerprint covers case ID, request digest, acceptable routes, category, privacy, and source-record digest. The label-set fingerprint covers schema, label metadata, and the ordered case fingerprints, never raw text.

- [ ] **Step 5: Add red/green tests for suite conversion and version reuse**

Add assertions for:

Implement `build_owner_route_suite(label_set: RouteLabelSet) -> tuple[BenchmarkCase, ...]`
and `ensure_owner_route_suite(store: BenchmarkStore, label_set: RouteLabelSet) ->
tuple[str, int, tuple[BenchmarkCase, ...]]`.

The suite name must be a deterministic bounded derivative of the label-set ID/fingerprint. Each case must use:

- `privacy_class="owner_private_local"`;
- `allowed_lanes=("local",)`;
- `criterion=BenchmarkCriterion("exact", "accepted")`;
- task type from the bounded category;
- artifact references containing only the label-set and case fingerprints.

Assert `ensure_owner_route_suite` reuses the latest version only when the ordered `(case_id, content_fingerprint)` sequence is exact; any semantic label change writes the next version. Assert the stored suite file contains the raw synthetic prompt, documenting that this is intentional E9 persistence under the explicit owner retention boundary, while its artifact references contain no path/source identifier.

- [ ] **Step 6: Run focused checks and commit Task 1**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday tests/test_nerva_benchmark_e9_0.py -q
& ..\..\.venv\Scripts\python.exe -m ruff check agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py tests/test_router_v2.py
git diff --check
```

Expected: both pytest targets pass, Ruff passes, and the diff check is empty.

Commit:

```powershell
git add agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py tests/test_router_v2.py
git commit -m "feat(cortex): add strict measured-route labels"
```

---

## Task 2: Deterministic measured runner with separate route and score evidence

**Files:**

- Modify: `agents/core/cortex_measured_compare.py`
- Modify: `tests/_nerva_e1_2_checks.py`

- [ ] **Step 1: Write red runner-adapter assertions**

Extend `run_e1_2_checks()` with `_check_measured_runner()` and assert:

- a configured `llm_classifier` is rejected when the adapter is built;
- a router whose `llm_classifier` changes after adapter creation is rejected before its `classify` body runs;
- an unknown normalized prompt fails before classification;
- each invocation captures exactly one `DecisionRecord` and the record's selected route equals the retained observation's actual `route_id`;
- zero or two captured records, or a deliberately mismatched selected route, raise without returning scored evidence;
- an acceptable actual route yields `response="accepted"`; a non-acceptable actual route yields `response="rejected"` while retaining the non-acceptable actual `route_id`;
- the decision replay fingerprint is added to artifact references, while prompt text and source-record digest are absent;
- concurrent invocations cannot share record buffers.

- [ ] **Step 2: Run focused test and confirm RED**

Run the existing router target. Expected: missing `measured_current_router_runner` or failed runner assertions.

- [ ] **Step 3: Implement by composition, not routing reimplementation**

Add `measured_current_router_runner(router: Any, agents: Mapping[str, Any],
label_set: RouteLabelSet, *, host_id: str = "in-process") -> BenchmarkRunner`.

At factory time, call the accepted `current_router_runner` once for its deterministic-router guard. Build a request-digest-to-label map and reject ambiguity. Inside every returned async invocation:

1. Derive the prompt digest through `DecisionRequest.from_input(prompt, {}).text_digest` and select exactly one label before classification.
2. Allocate an invocation-local `records: list[DecisionRecord]`.
3. Wrap the router in `ShadowDecisionRouter(router, records.append)` and build the accepted E9 `current_router_runner` around that wrapper so the late-injected LLM guard runs before classification.
4. Await the E9 runner; require exactly one record and exact `selected_route == observation.route_id`.
5. Return `dataclasses.replace(observation, response=score, artifact_refs=(f"decision:{record.replay_fingerprint}",))`, where `score` is exactly `accepted` or `rejected`. The retained adapter reference is exactly this one fingerprint, even if a future underlying adapter grows unrelated references.

Do not catch router/adapter exceptions, persist prompt text, or set latency yourself; `BenchmarkHarness` remains the sole latency source.

- [ ] **Step 4: Verify and commit Task 2**

Run the focused router and E9.0 tests, Ruff, and `git diff --check` as in Task 1.

Commit:

```powershell
git add agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
git commit -m "feat(cortex): score deterministic route adequacy"
```

---

## Task 3: Explicit-root warm-up and five-run retained batch

**Files:**

- Modify: `agents/core/cortex_measured_compare.py`
- Modify: `tests/_nerva_e1_2_checks.py`

- [ ] **Step 1: Write red batch assertions**

Add `_check_measured_run_batch()` covering:

- missing, non-`Path`, relative, non-existent, file, symlink, and Windows reparse/junction store roots fail before `BenchmarkStore` writes anything;
- no code path constructs `BenchmarkStore()` without the supplied root;
- the lane is always `local`, candidate ID is exactly `current-router-e1.2a`, baseline is absent, and revision must be an exact lowercase 40- or 64-hex commit SHA;
- `EnvironmentProfile.detect(runner_id="owner-local-e1-2a")` is called once for the batch;
- one warm-up runs all 20 cases but is never passed to `record_run`;
- exactly five later runs are retained, with unique bounded IDs carrying label-fingerprint prefix, nonce, and repetition index; collision with an already retained run ID fails before append even though E9 itself does not reject duplicate run IDs;
- a warm-up `error`/`unscored` result retains no run; retained measured
  `error`/`unscored` results remain evidence and all five repetitions are stored, while
  an exception before a run exists, run-ID collision, write failure, or retrieval/
  fingerprint-proof failure stops immediately and never returns a partial batch;
- the returned batch cannot be directly constructed or modified by a caller and binds the resolved store root, label fingerprint, suite/version, environment fingerprint, revision, repetition count, and ordered run fingerprints.

- [ ] **Step 2: Run focused test and confirm RED**

Expected: `run_measured_comparison`/`MeasuredRunBatch` are missing or the new guard assertions fail.

- [ ] **Step 3: Implement the guarded batch**

Add a module-private sentinel and:

```python
@dataclass(frozen=True)
class MeasuredRunBatch:
    label_set_fingerprint: str
    suite_name: str
    suite_version: int
    environment: EnvironmentProfile
    environment_fingerprint: str
    source_revision: str
    run_fingerprints: tuple[str, ...]
    store_root: Path = field(repr=False)
    repetitions: int = field(default=RETAINED_REPETITIONS, init=False)
    _guard: Any = field(default=None, repr=False, compare=False)
```

Expose the exact async signature `run_measured_comparison(*, router: Any, agents:
Mapping[str, Any], label_set: RouteLabelSet, store_root: Path, source_revision: str,
run_nonce: Callable[[], str] | None = None) -> MeasuredRunBatch`.

Implementation order is security-relevant:

1. Require a `Path` instance and validate an explicitly supplied absolute, existing directory; reject the final path and every traversed Windows reparse/symlink boundary before resolving it. Never create/fallback to a default root.
2. Validate the exact revision, label set, route registry, and initial deterministic-router state before the first suite write.
3. Construct `BenchmarkStore(resolved_root)`, ensure the suite, detect one environment, and hash its canonical payload.
4. Build the measured runner and `BenchmarkHarness(candidate_id=CANDIDATE_ID)` with no baseline. Document that the accepted E9 store is a single-writer owner-local store; do not claim concurrent-writer safety that it does not provide.
5. Run one full warm-up with lane `local` and never record it. Treat any warm-up result with status `error` or `unscored` as a warm-up failure.
6. Run exactly five full retained repetitions. Before `store.record_run`, reject an existing run-ID collision and replace each run's artifact references with bounded label/environment fingerprints. Retain `BenchmarkRun` values containing `error` or `unscored` results so Task 4 can report `complete=false`. Record each run immediately, then prove its canonical fingerprint is uniquely retrievable from the complete store with an exact match before continuing. An exception before a run exists, collision, write failure, or retrieval/fingerprint-proof failure raises and returns no batch.
7. Construct the batch only through the module sentinel after all five stores succeed. Hash runs with accepted E9.1 `run_fingerprint`.

The batch's store path is internal evidence only and must never enter report serialization or Markdown.

- [ ] **Step 4: Verify and commit Task 3**

Run the focused router test and the combined E9.0/E9.1 host file plus Ruff and diff check:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday tests/test_nerva_benchmark_e9_0.py -q
& ..\..\.venv\Scripts\python.exe -m ruff check agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
git diff --check
```

Commit:

```powershell
git add agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
git commit -m "feat(cortex): retain guarded measured route batches"
```

---

## Task 4: Evidence-bound aggregate report and privacy-minimised rendering

**Files:**

- Modify: `agents/core/cortex_measured_compare.py`
- Modify: `tests/_nerva_e1_2_checks.py`

- [ ] **Step 1: Write red report and adversarial assertions**

Add `_check_measured_report()` and `_check_measured_report_adversarial()` with controlled five-run fixtures. Cover:

- 100 samples for 20 tasks x 5 repetitions; accepted/rejected counts and overall/per-actual-route ratios are exact;
- route rejection is valid negative evidence and does not increase incomplete/error counts;
- an `error` or `unscored` result makes `complete=false`, preserves the negative/error count, and prevents a full-quality claim;
- median is the ordinary middle/mean-of-two statistic and p95 is nearest-rank `sorted_values[ceil(0.95*n)-1]` over only E9 `benchmark.harness`/`ms` measurements;
- provider charge is measured `$0` only if every candidate proves `model_id="none"`, `provider_id="local-deterministic"`, no baseline, and measured E9 `candidate.runner`/`usd` cost of `0.0`; otherwise it is `not_measured` and the deterministic-charge contract is incomplete;
- compute, energy, hardware, downstream-agent, tool, action, and executed-task outcome measurements remain `not_measured`;
- mixed revision, suite/version, candidate/baseline, lane, environment, result coverage, case fingerprint, or repetition sets refuse aggregation;
- a batch run fingerprint missing from the supplied store refuses aggregation;
- mutually consistent runs against a different stored suite/label set refuse aggregation;
- JSON is canonical and round-trips structurally; unknown/missing fields, floats outside finite/range constraints, altered totals/fingerprints/completeness, and authority changes are rejected;
- raw prompts, source-record digests, source identifiers, arbitrary notes, exception messages, store paths, and local usernames are absent from JSON and Markdown;
- JSON/Markdown contain no `beats_current`, selector-superiority, answer-quality, end-to-end-completion, or safety claim;
- direct construction/replacement cannot set `can_change_routing`, `can_authorize`, `can_execute`, `can_promote`, or `can_mark_complete` true.

- [ ] **Step 2: Run focused test and confirm RED**

Expected: report types/builders/renderers are missing or the new aggregate assertions fail.

- [ ] **Step 3: Implement strict report records and builder**

Define bounded frozen records for per-route aggregates and the full `MeasuredComparisonReport`. The report must carry:

- schema, label-set ID/fingerprint, suite/version, exact revision, fixed candidate/no baseline;
- a dedicated immutable `EnvironmentEvidence` snapshot with fixed runner/schema/hardware fields, SHA-256 digests of the exact detected platform and Python-version strings, and a fingerprint over that sanitised payload; keep the separate raw-profile `environment_fingerprint`, exactly five ordered retained-run fingerprints, and repetition/task/sample counts; do not attempt to construct or deserialize the guarded E9.1 `EnvironmentProfile` directly;
- accepted, rejected, error, and incomplete counts; overall and sorted per-actual-route adequacy;
- typed E9 `Measurement` values for latency median/p95, provider charge, and every explicitly unmeasured dimension;
- fixed limitation codes and the five owner-gate codes, not free-form prose;
- `complete` derived from evidence only;
- fixed `authority="evaluation_only"` and every routing/action/promotion/completion flag false.

Implement these exact public signatures:

- `build_measured_report(batch: MeasuredRunBatch, store: BenchmarkStore, label_set: RouteLabelSet) -> MeasuredComparisonReport`
- `validate_measured_report_against_evidence(report: MeasuredComparisonReport, batch: MeasuredRunBatch, store: BenchmarkStore, label_set: RouteLabelSet) -> None`
- `render_measured_report(report: MeasuredComparisonReport) -> str`

Builder validation must:

1. Require `store.root.resolve() == batch.store_root` without serializing the path.
2. Rebuild expected E9 cases from the label set; load the exact suite version; compare ordered `(case_id, content_fingerprint)` sequences.
3. Load retained runs from the store and locate each exact batch fingerprint; reject absent or duplicate matches.
4. Verify every identity, artifact fingerprint, result coverage, task/privacy/case fingerprint, lane, candidate/baseline, environment snapshot, and revision field before aggregation. Recompute the raw E9 profile fingerprint against the batch, then derive the sanitised environment snapshot; its content fingerprint is intentionally distinct. Candidate hardware provenance (`not-measured`) and E9.1 environment hardware (`not_measured`) are distinct fields and must not be compared or normalized into one claim.
5. Count failed route criteria as rejection evidence; count errors/unscored/missing measurements as incomplete evidence without hiding them.

`MeasuredComparisonReport.to_json()` must use `ensure_ascii=False`, `sort_keys=True`, and `separators=(",", ":")`. `from_json()` must reject duplicate keys, floats/non-finite values that violate the report schema, unknown fields (including raw `platform` or `python_version`), derived-count/fingerprint drift, completeness drift, and immutable-authority drift. A deserialized report is structurally valid but becomes accepted retained evidence only after `validate_measured_report_against_evidence` proves both the raw batch environment fingerprint and sanitised snapshot. This is a pre-acceptance v1 correction; no persisted owner report exists and no migration is required.

Markdown must render only bounded IDs, fingerprints, aggregate numbers, measurement status/source/unit, fixed limitation labels, and owner gates. It must say that owner evidence is blocked and real task-outcome quality is not measured.

- [ ] **Step 4: Verify and commit Task 4**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday tests/test_nerva_benchmark_e9_0.py -q
& ..\..\.venv\Scripts\python.exe -m ruff check agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
& ..\..\.venv\Scripts\python.exe -m bandit -q agents/core/cortex_measured_compare.py
& ..\..\.venv\Scripts\python.exe -m compileall -q agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
git diff --check
```

Commit:

```powershell
git add agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
git commit -m "feat(cortex): report measured route adequacy"
```

---

## Task 5: Truthful operator docs, owner gate, and program-manifest integration

**Files:**

- Create: `docs/nerva2/CORTEX_E1_2.md`
- Modify: `docs/OWNER_TASKS.md`
- Modify: `docs/nerva2/M1_DELIVERY.md`
- Modify: `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json`
- Regenerate: `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md`
- Modify: `.github/workflows/nerva-roadmap.yml`
- Modify: `BACKLOG.md`
- Modify: `tests/_nerva_e1_2_checks.py`

- [ ] **Step 1: Add red repository-truth assertions**

Assert from the E1.2 helper that:

- `CORTEX_E1_2.md` names the exact schema, explicit store requirement, warm-up + five retained runs, suite prompt persistence, five artifact classes under retention, limitations, migration-free rollback, and owner-blocked E1.2b state;
- `OWNER_TASKS.md` lists all five missing owner inputs and does not imply that `owner_attested=true` proves consent;
- M1 delivery and BACKLOG distinguish `contract_ready` from `owner_evidence_blocked` and say `real_task_outcome_quality=not_measured`;
- manifest E1 remains `building`/`in_progress`, adds #841 and `docs/nerva2/CORTEX_E1_2.md`, and does not mark the program or release complete;
- both push and pull-request path blocks in `nerva-roadmap.yml` include the new referenced document.

Run the router helper plus manifest checker and confirm RED before editing docs.

- [ ] **Step 2: Write the operator contract and factual ledgers**

`docs/nerva2/CORTEX_E1_2.md` must include:

- exact external label schema with synthetic example values only;
- local invocation example that requires explicit label and store paths but does not invent a committed CLI if no CLI is implemented;
- stored-data table for label file, suite vN.jsonl, runs.jsonl, JSON report, Markdown report;
- measured/unmeasured matrix and primary-route-adequacy semantics;
- failure, privacy/linkability, authority, owner-gate, migration, and rollback sections.

Update `docs/OWNER_TASKS.md` with one unchecked E1.2b owner task containing: at least 20 historical tasks in an ignored path; acceptable routes/categories; predeclared sampling/exclusion rule; retention/access/deletion policy for all five artifacts; and permission for the local run.

Update M1/BACKLOG/manifest truth without checking E1 complete or widening scope. Add #841 and the E1.2 document to E1 references; retain the existing E1 blocker/eligibility state. Add the new document to both workflow path blocks.

- [ ] **Step 3: Regenerate the manifest view and run consistency gates**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe scripts/check_nerva_program_manifest.py --write
& ..\..\.venv\Scripts\python.exe scripts/check_nerva_program_manifest.py --check
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py::test_existing_weather_routes_to_friday tests/test_nerva_program_manifest.py -q
git diff --check
```

Inspect the generated Markdown diff. It must be a deterministic projection of JSON, not a manual edit.

- [ ] **Step 4: Run canonical status sync without inventing count changes**

Run:

```powershell
& ..\..\.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
```

Expected: no derived status drift and test counts remain 6052 backend / 408 frontend / 96 mobile. If the tool reports a real difference, stop and diagnose it; do not manually alter generated status or claim parity.

- [ ] **Step 5: Commit Task 5**

```powershell
git add docs/nerva2/CORTEX_E1_2.md docs/OWNER_TASKS.md docs/nerva2/M1_DELIVERY.md docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md .github/workflows/nerva-roadmap.yml BACKLOG.md tests/_nerva_e1_2_checks.py
git commit -m "docs(nerva): register E1.2a owner-local contract"
```

---

## Task 6: Full verification, independent reviews, exact-head CI, and integration

**Files:**

- Review all files in PR #842; change only scoped files when a verified finding requires it.

- [ ] **Step 1: Self-review the complete branch diff**

Run and inspect:

```powershell
git status --short --branch
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
git diff origin/main...HEAD -- agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py tests/test_router_v2.py docs/nerva2/CORTEX_E1_2.md docs/OWNER_TASKS.md docs/nerva2/M1_DELIVERY.md docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md .github/workflows/nerva-roadmap.yml BACKLOG.md
rg -n "TODO|FIXME|placeholder|beats_current|release.ready|owner_attested.*proof" agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py docs/nerva2/CORTEX_E1_2.md docs/OWNER_TASKS.md docs/nerva2/M1_DELIVERY.md BACKLOG.md
```

Confirm no unrelated primary-checkout or worktree metadata appears in the diff.

- [ ] **Step 2: Run the local acceptance matrix**

Run, in order:

```powershell
& ..\..\.venv\Scripts\python.exe -m pytest tests/test_router_v2.py tests/test_nerva_benchmark_e9_0.py tests/test_nerva_program_manifest.py -q
& ..\..\.venv\Scripts\python.exe -m pytest tests/ -q
& ..\..\.venv\Scripts\python.exe -m ruff check agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py tests/test_router_v2.py
& ..\..\.venv\Scripts\python.exe -m bandit -q agents/core/cortex_measured_compare.py
& ..\..\.venv\Scripts\python.exe -m compileall -q agents/core/cortex_measured_compare.py tests/_nerva_e1_2_checks.py
& ..\..\.venv\Scripts\python.exe scripts/check_nerva_program_manifest.py --check
& ..\..\.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
git diff --check origin/main...HEAD
```

Record every command, exit code, pass count, warning, skipped/unavailable check, and exact branch SHA. Green focused tests alone are not completion.

- [ ] **Step 3: Obtain independent functional, privacy/security, and truth-ledger review**

Use fresh reviewers that did not implement the code. Require each to inspect the exact SHA and report GO/HOLD with file/line evidence. Resolve only verified findings, rerun the affected local matrix, and request re-review of the new exact SHA.

At minimum review:

- hostile JSON/path parsing, symlink/store-root behavior, prompt/source leakage, late LLM injection, and authority tamper resistance;
- exact E9 suite/run binding, warm-up exclusion, five-run comparability, adequacy/latency/cost arithmetic, error honesty, and deserialization boundaries;
- BACKLOG/M1/owner task/manifest/workflow truth and preservation of `building`, owner-blocked, and release-false claims.

- [ ] **Step 3a: Resolve the exact-head security HOLD with new TDD evidence**

The security reviewer reproduced one Critical and two Important findings at
`4b81110156d3a313ad07fc8951878c4c7d4366b2`, plus one bounded-input Minor. Before
publishing, add failing tests for all four classes, then apply the minimum design-
addendum implementation:

1. Add `IntentRouter.classify_deterministic()` and matching shadow capture; make
   `current_router_runner()` require/capture/invoke only this no-LLM capability and
   reject both LLM provenance spellings. Prove a late-injecting normal `classify()`
   receives zero calls and never sees the prompt.
2. Harden the E1.2a label path and store descendants through one private measured-
   store boundary used by suite ensure/reuse, retained-run collision/readback/write,
   and report suite/run reads. Reject ancestor/final symlink or Windows reparse
   boundaries, including pre-existing `suites`, selected suite directories, exact
   `vN.jsonl`, and `runs.jsonl` paths, before every relevant read/write. Prove label-
   ancestor, `suites`, selected-suite, version-file, and runs-file redirections fail;
   no outside sentinel may be created or consumed.
3. Make `BenchmarkRun.from_json()` reject duplicate members and exact-type violations
   for immutable Boolean authority fields. Prove `false -> 0` and duplicate authority
   keys fail before canonical fingerprint lookup.
4. Enforce the design bounds (2,000,000-byte labels, 1,000 cases, 32 routes/case,
   2,000,000-character report JSON), reject surrogate text, and normalize recursion /
   Unicode parser failures to `ValueError`.

Expected files are `agents/core/router.py`, `agents/core/cortex_decision.py`,
`agents/core/observability/benchmark.py`, `agents/core/cortex_measured_compare.py`,
`tests/test_nerva_benchmark_e9_0.py`, and `tests/_nerva_e1_2_checks.py`, plus this
design/plan. Do not change production routing semantics, report schema, owner ledgers,
manifest status, or release authority.

Run the new red tests first. After GREEN, rerun the focused E1.2a + E9.0 + manifest
suite, Ruff on every touched Python file, Bandit on both production modules,
compileall, manifest/status checks, and cumulative diff checks. Run Bandit on every
touched production module. Commit the remediation,
then require the same security reviewer (or a fresh equivalent) to reproduce every
old probe against the new exact SHA. Any residual disclosure or outside-root write is
HOLD.

- [ ] **Step 4: Refresh live GitHub state before publishing**

Fetch `origin`, re-check open/draft/closed PRs, current `origin/main`, issue #841/#759/#757/#778 bodies, and any new overlapping branch or draft lock. If `origin/main` moved, rebase the isolated branch, rerun the full local matrix, and obtain reviews on the rebased exact head.

- [ ] **Step 5: Push, update PR #842, and run exact-head hosted checks**

Push the branch. Update the PR body with exact local evidence and the explicit distinction:

`CODE CONTRACT READY · OWNER EVIDENCE BLOCKED · EVALUATION ONLY · RELEASE FALSE`.

Keep the PR draft until independent reviews are GO. Then mark ready and wait for every required hosted check, including Windows, aggregate CodeQL/security, and any review-thread resolution, on the exact head SHA. Do not merge a superseded SHA or infer success from an older run.

- [ ] **Step 6: Merge only when all gates are factual**

If all exact-head reviews/checks are green and no draft lock/overlap appeared, squash-merge #842. Verify:

- the merge commit parent is the reviewed current `origin/main`;
- every scoped path is byte-equivalent to the reviewed candidate;
- #841 closes, while #759/#757/#778 remain open and truthful;
- the primary checkout is still on `qa/run3-preflight-2026-07-27` at its original HEAD with its original `AD docs/qa-runs/2026-07-27-run3.md` state.

Update issue/epic/program comments with the merge SHA, exact tests/checks, code-contract acceptance, and the five owner blockers. Do not claim representative measured evidence or E1 completion.

- [ ] **Step 7: Release locks and report the actual terminal state**

Release only the E1.2a component locks. Report one of: `merged`, `waiting exact-head checks`, `draft-hold`, `blocked`, or `superseded`. State actual elapsed time and distinguish code complete from release ready.
