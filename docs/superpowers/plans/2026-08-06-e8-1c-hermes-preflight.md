# E8.1c Hermes Evidence-Only Preflight — Implementation Plan

> Execute under issue #844 on `nerva2/e8-1c-hermes-preflight`. Preserve the
> no-install/no-import/no-execution boundary throughout.

**Goal:** Produce a deterministic, independently reviewable evidence record for
one pinned Hermes invocation/distribution candidate without adding or executing
a provider.

**Architecture:** Canonical closed-world JSON, a standard-library offline
validator/Markdown renderer, and hostile tests. No runtime module imports the
artifact or checker.

---

### Task 1: Freeze public-source evidence

**Files:** no repository edits

1. Query the authoritative GitHub repository/tag/commit/tree/blob APIs and raw
   exact-commit files.
2. Query authoritative PyPI project/release metadata without downloading or
   installing artifacts.
3. Query the Docker Registry manifest endpoint and exact upstream release run
   and provenance metadata without pulling or executing the OCI image/layers;
   keep signature, referrer, materials-completeness and SBOM states explicit.
4. Record timestamps, exact identifiers, content digests and query limitations.
5. Inventory direct requirements, exact lock versions, bundled license files
   and statically visible startup/import/container effects.
6. Record time-bounded OSV groups and exact restrictive bundled-license paths,
   while leaving transitive license/CVE/SBOM/runtime closure unresolved unless
   primary evidence actually closes it.

### Task 2: Write failing contract tests

**File:** `tests/test_nerva_e8_1c_preflight.py`

1. Add a missing-artifact/checker smoke test and run it to prove RED.
2. Add closed-world/schema, immutable-binding, evidence-state, authority and
   repository-effect tests.
3. Add hostile mutations for moving refs, substituted source identities,
   promoted unknowns, boolean aliases and readiness claims.
4. Add deterministic Markdown and safe CLI/output tests.
5. Add strict size/depth/duplicate-key tests and repository dependency/manifest
   injection guards.

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_nerva_e8_1c_preflight.py -q
```

Expected before implementation: collection/import or missing-artifact failure.

### Task 3: Implement the minimum offline checker

**File:** `scripts/check_nerva_e8_1c_preflight.py`

1. Implement strict JSON loading and bounded error rendering.
2. Validate the exact closed-world schema and cross-field invariants.
3. Validate immutable upstream and distribution bindings.
4. Enforce all no-authority/no-runtime/no-readiness and unmeasured gates.
5. Validate repository dependency/manifest absence without network access.
6. Render deterministic Markdown and expose `--check`/`--write` CLI modes with
   safe path handling and atomic replacement.

Run the focused tests until GREEN.

### Task 4: Add the canonical evidence snapshot

**Files:**

- `docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.json`
- `docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md`

1. Encode only the evidence obtained in Task 1.
2. Mark runtime behavior, transitive closure and E9 results blocked,
   `not_verified` or `not_measured`.
3. Generate Markdown using the checker; do not hand-maintain it.
4. Re-run focused tests and `--check`.

### Task 5: Review the whole branch adversarially

1. Compare the complete branch against current `origin/main`.
2. Independently review upstream identity, supply-chain truth, validator
   bypasses, privacy/error paths and completion wording.
3. Add red tests for every accepted finding before fixes.
4. Keep shared ledgers/workflow/manifest untouched while #842/#843 own them.

### Task 6: Verify and publish the bounded draft

Run:

```powershell
.venv\Scripts\python.exe scripts/check_nerva_e8_1c_preflight.py --check
.venv\Scripts\python.exe -m pytest tests/test_nerva_e8_1c_preflight.py tests/test_nerva_execution_provider_e8_1b.py tests/test_hermes_import.py tests/test_nerva_program_manifest.py -q
.venv\Scripts\python.exe -m ruff check scripts/check_nerva_e8_1c_preflight.py tests/test_nerva_e8_1c_preflight.py
.venv\Scripts\python.exe -m py_compile scripts/check_nerva_e8_1c_preflight.py tests/test_nerva_e8_1c_preflight.py
.venv\Scripts\python.exe scripts/status_sync.py --check --reuse-js-counts
.venv\Scripts\python.exe -m pytest tests/ -q
git diff --check
```

1. Commit the design before implementation, then commit the tested evidence
   package.
2. Push only this branch and open/update a draft PR linked to #844/#804.
3. Report exact command results and environment-version gaps.
4. Do not mark ready or merge until exact-head hosted checks and independent
   review are green and current-main ancestry is reverified.

### Task 7: Serialize shared truth later

After #842/#843 resolve, rebase once onto current `origin/main`, reconcile any
required workflow/program-manifest/BACKLOG/status changes, regenerate derived
artifacts and rerun the full exact-head envelope. If no shared enrolment is
required for acceptance, explicitly leave those files unchanged.

### Task 8: Reconcile accepted shared truth after #842/#843

1. Preserve the pre-rebase head with a backup ref, fetch without pruning, and
   rebase onto current `origin/main`.
2. Add a failing test that sets
   `repository_effects.shared_ledgers_changed=true`; confirm the old validator
   rejects it while the other repository-effect flags remain fail-closed.
3. Make that one evidence flag truthful, update the renderer wording and
   regenerate `EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md`.
4. Update `BACKLOG.md`, the E8 program-manifest blockers/references, the Nerva
   roadmap workflow and the non-blocking owner legal/supply-chain parking item.
   Do not add completion evidence or change E8/E8.1 from `BUILDING`.
5. Regenerate the program-manifest Markdown and the five status-sync surfaces.
6. Run focused Windows and WSL tests, adjacent and full suites, exact Ruff,
   Bandit, compile checks, all canonical `--check` modes and diff review.
7. Commit the reconciled exact candidate before running the manifest
   `--candidate-ref` gate, then obtain independent exact-head review and hosted
   Python 3.12 CI before ready/merge.
