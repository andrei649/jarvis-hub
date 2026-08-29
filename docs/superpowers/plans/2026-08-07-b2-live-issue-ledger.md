# B2.1 Point-in-Time Live Issue Movement Gate — Implementation Plan

> Execute under #846 on `nerva2/b2-live-issue-ledger-enforcement`, based on
> exact `main@e596920ec60f19d2e7f0937819c892746a1c42b2`. Preserve read-only
> GitHub access, point-in-time semantics and no-authority truth throughout.
> #847's conductor exclusion is a hard merged predecessor.

**Goal:** Make the live candidate-receipt check fail through the existing
required CI context for every deterministically classified Nerva PR, while
keeping comment mutation and owner-side ruleset limitations explicit.

**Architecture:** A current-PR live read plus all-PR classifier; semantic
manifest-diff scope derivation; strict PR attestation and append-only owner
receipts; a bounded standard-library REST/offline validator; and a `ci.yml`
dependency propagated into the already required Ubuntu/Windows test contexts.

---

### Task 0: Land the auto-merge exclusion predecessor

**Separate issue/branch:** #847 / `nerva2/b2-auto-merge-manual-exclusion`

1. Add a design-tested fail-closed skip in the hourly conductor for both
   `nerva2/` head branches and the exact Nerva movement marker.
2. Re-fetch draft/state/head/branch/body and repeat the exclusion immediately
   before any merge; preserve all non-Nerva `CLEAN`/squash/exact-head behavior.
3. Obtain exact-head CI and independent review, then integrate #847 before B2.1
   leaves draft.
4. Verify the default-branch workflow bytes and latest active workflow state;
   a change only on #846's candidate branch is not sufficient.
5. Record that #847 cannot be reverted while B2.1 remains `required`; B2.1 must
   transition to `safety_disabled` first.

### Task 1: Accept the corrected design and live constraints

**Files:**

- `docs/superpowers/specs/2026-08-07-b2-live-issue-ledger-design.md`
- `docs/superpowers/plans/2026-08-07-b2-live-issue-ledger.md`

1. Record the active ruleset's exact required contexts and absence of a
   pull-request rule.
2. Record that the path-filtered Nerva Roadmap job is not required.
3. Reconcile the two independent HOLD finding ledgers: self-referential comment
   ID, bypassable workflow, scope substitution, comment TOCTOU, false direct-
   push claim and unsafe full-revert rollback.
4. Obtain fresh independent design/security GO before implementation.
5. Reconcile live #846 so its workflow, permissions, guarantee and forward-
   rollback text match the accepted design; post no implementation claim.
6. Reassert `origin/main` still equals the accepted current base
   `e596920ec60f19d2e7f0937819c892746a1c42b2`. The legacy bootstrap SHA is
   retained only as the historical classifier source; if main advanced, stop
   and re-pin through design/security review; do not rebase silently.
7. Commit the design separately from checker code.

### Task 2: Write RED parser, classifier and semantic-scope tests

**File:** `tests/test_nerva_issue_movement.py`

1. Add a missing-module/checker smoke test and prove RED.
2. Define canonical PR-event, attestation, receipt, manifest and REST fixtures.
3. Cover the exact legacy bootstrap base and canonical hard-coded classifier
   seed, then require nested movement-gate v1 on every candidate/future base.
4. Cover Nerva classification by branch, attestation marker, registered path,
   `docs/nerva2/` and manifest static input; cover deterministic non-Nerva skip.
5. Parse `--name-status --no-renames -z` completely before classification;
   reject malformed statuses, paths, UTF-8 and case collisions for all PRs.
6. Classify against the baseline/candidate policy union and prove registry
   additions are sorted, unique, wildcard-free and monotone. Permit only the
   exact one-time pinned seed for existing paths; reject any extra seed entry.
7. Cover strict marker/JSON/type/size/depth/count/Unicode handling.
8. Derive one stream, canonical epic and exactly one union of newly introduced
   issue IDs; reject multi-stream, history deletion/rewrite and substitution.
9. Derive one append-only program-control implementation issue; reject every
   other root/stream mutation in program-control mode.
10. Prove non-draft Nerva candidates cannot omit manifest/view movement; prove
   receipt-free draft hold remains allowed.

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_nerva_issue_movement.py -q
```

Expected before implementation: missing-module/import failure.

### Task 3: Implement the pure bounded validator

**Files:**

- `scripts/check_nerva_issue_movement.py`
- `tests/test_nerva_issue_movement.py`

1. Implement strict UTF-8, marker and closed-world JSON loading with duplicate-
   key, non-finite, bool-as-int, control, depth, size and count rejection.
2. Parse the event payload only as data.
3. Compute a complete normalized `--name-status --no-renames -z` diff with fixed
   argv and `shell=False` before any classification result.
4. Implement baseline/candidate registry union, monotone evolution, deterministic
   classification and semantic manifest-diff scope.
5. Validate all event/manifest/attestation/receipt cross-bindings.
6. Keep errors bounded and free of tokens/comment bodies.
7. Expose an injected transport and offline snapshot mode.

Run the focused suite until the pure matrix is GREEN.

### Task 4: Add exact-head Git and manifest binding

**Files:**

- `scripts/check_nerva_issue_movement.py`
- `tests/test_nerva_issue_movement.py`

1. Resolve one trusted absolute Git executable; use fixed argv and a scrubbed
   environment without token/proxy variables.
2. Require validated exact base/head, base ancestry and event head == checkout.
3. Require canonical manifest JSON and generated Markdown in the exact diff.
4. Hash exact candidate manifest bytes and compare the attested SHA-256.
5. Reuse the existing manifest validation boundary.
6. Recheck HEAD immediately before success and prove moved-head RED -> GREEN.

### Task 5: Implement append-only REST receipt validation

**Files:**

- `scripts/check_nerva_issue_movement.py`
- `tests/test_nerva_issue_movement.py`

1. Make `--live` and `--snapshot-dir` exclusive; snapshot mode must read no token
   and open no network.
2. Fetch and validate the current PR first; compare current body/head/base/draft/
   state to event and checkout, and parse only the current body attestation.
3. Remove comment ID from the receipt schema; keep ID/body digest/updated time in
   the PR attestation only.
4. Validate the closed-world receipt independently from the extensible REST
   envelope.
5. Require exact response ID/issue URL/owner association, unedited timestamp and
   exact UTF-8 body digest.
6. Build only fixed pull-request/comment GET URLs after bounded validation.
7. Disable redirect and proxy handlers; request identity encoding and validate
   final URL.
8. Use verified TLS, require absent/identity response encoding, read `MAX + 1`,
   and cap event/body/marker/token/response count/aggregate bytes.
9. Reject every timeout, HTTP/rate-limit/truncation/malformed response; the
   workflow step timeout is the total deadline.
10. Read `GITHUB_TOKEN` only from environment and reject oversize/control/CRLF;
    never log it or pass it to Git subprocesses.
11. Prove redirects do not receive Authorization and env proxies are ignored.
12. Exercise offline PR/comment fixtures through identical validators.

### Task 6: Wire the gate into required CI

**Files:**

- `.github/workflows/ci.yml`
- `tests/test_nerva_issue_movement.py`

1. Preserve `opened`, `synchronize` and `reopened`; add `edited`,
   `ready_for_review` and `converted_to_draft` pull-request types.
2. Add PR-only `nerva-movement` with job-level `contents: read`, `issues: read`
   and `pull-requests: read`, exact-head checkout, full history,
   `persist-credentials: false` and step timeout.
3. State/test token semantics accurately: pinned checkout uses the transient
   read-only token and does not persist it; only checker gets an explicit token
   environment; Git subprocesses get a scrubbed environment.
4. Make matrix `test` depend on the movement job, run with `if: always()`, and
   fail before setup unless the dependency result is `success`.
5. Keep workflow-level path filters absent. On push, movement is skipped and the
   dependency guard is inactive, so both ordinary matrix test jobs still run.
6. Add workflow-text tests for event coverage, permissions, dependency
   propagation, no `pull_request_target`, no writes and no untrusted shell text.

### Task 7: Extend the manifest movement policy and reconcile facts

**Files:**

- `BACKLOG.md`
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json`
- `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md`
- `scripts/check_nerva_program_manifest.py`
- `tests/test_nerva_program_manifest.py`
- `docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md`

1. Mark E1.2a accepted/`contract_ready` through #842/`769b6334`, preserving all
   five E1.2b owner inputs and `real_task_outcome_quality=not_measured`.
2. Remove only the obsolete statement that E8.1c remains open; preserve its
   static-preflight/no-execution limits.
3. Add nested movement-gate schema v1, exact bootstrap base, closed-world
   classifier policy, registered paths and `program_control_issues=[846]`.
4. Treat missing gate as legacy-empty only for exact base `843918848...`; after
   bootstrap, missing/downgraded gate fails. Keep #839 only as the prior
   `evidence_snapshot.control_issue`, not a synthesized movement.
5. Require registry baseline/candidate union and append-only/no-wildcard/no-
   narrowing evolution; materialize only the pinned bootstrap seed plus entries
   covering files added by #846; derive #846 as the sole new control issue.
6. Preserve `live_issue_state_verified_by_checker=false`; add only explicit
   point-in-time receipt-control facts and false continuous-currentness.
7. Keep every authority/release field false and E1/E8 `BUILDING`.
8. Pin #847's workflow path, policy-test path, exact branch prefix and marker as
   manifest static invariants required while enforcement is `required`.
9. Generate Markdown from JSON; never hand-maintain it.
10. Document exact receipt creation, live-PR reread, rerun and forward-rollback
   procedures.
11. Define/test the explicit `required -> safety_disabled` program-control
    transition with rollback issue/reason/receipts; reject every ordinary
    downgrade or missing state.
12. Add RED -> GREEN manifest tests for every new invariant and bootstrap.

### Task 8: Run local verification and publish one draft

Run at minimum:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_nerva_issue_movement.py tests/test_nerva_program_manifest.py tests/test_reconcile_nerva_repository_ledgers.py -q
.venv\Scripts\python.exe scripts/check_nerva_program_manifest.py --check
.venv\Scripts\python.exe scripts/reconcile_nerva_repository_ledgers.py --check
.venv\Scripts\python.exe scripts/check_nerva_roadmap.py
.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
uvx ruff@0.16.1 check <changed-python-files>
uvx ruff@0.16.1 format --check <changed-python-files>
.venv\Scripts\python.exe -m py_compile <changed-python-files>
.venv\Scripts\python.exe -m pytest tests/ -q
git diff --check
```

Also parse workflow YAML and run Bandit on Linux/WSL or rely on exact hosted
Security if the local Windows baseline is path-unstable.

1. Commit only after focused GREEN and generated outputs are current.
2. Push only the reserved branch and open one draft PR linked to #846.
3. Record `draft_hold` honestly; it is not live-receipt proof.

### Task 9: Freeze and publish exact-head receipts

1. Freeze the candidate after local QA and first independent code/security
   review.
2. Post one append-only receipt each to #757, #778 and #846.
3. Hash each exact body returned by GitHub and copy its ID, digest and unchanged
   timestamp into the PR attestation.
4. Trigger `edited` and require the live movement job to GET/validate the current
   PR and receipts, plus propagated required test contexts, to pass.
5. If the head changes, create entirely new receipts and attestation; never edit
   or reuse the old set.

### Task 10: Independent review and integration gate

1. Security review: hostile parser/HTTP behavior, token scope, proxy/redirect
   denial, exact-head replay, semantic scope and no-write proof.
2. Integration review: required-context propagation, manifest/BACKLOG truth,
   classifier residual risk, generated outputs and forward rollback.
3. Require complete exact-head CI/Security/CodeQL and zero review threads.
4. Verify #847's exclusions from the live default branch. Mark ready only after
   both reviews are GO; do not enable auto-merge.
5. Explicitly rerun CI on the unchanged head immediately before merge; the run
   must GET the current PR body/head/base/draft and receipts. Wait for every
   required context, then revalidate ancestry and threads.
6. Squash-merge only if every result remains green and exact-head.
7. Verify the merged tree, post factual merge-SHA deltas to #846/#757/#778 and
   leave B2 `PARTIAL` unless the live program explicitly accepts the bounded
   point-in-time guarantee.
