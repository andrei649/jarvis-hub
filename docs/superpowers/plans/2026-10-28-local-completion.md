# Local backlog and Hermes completion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task.

**Goal:** Finish the existing backlog and the complete accepted 697-contract Hermes integration; do not replace this scope with this first wave.

**Architecture:** Continue from synced main on `codex/local-development-20261028`. Reuse unfinished implementations only after source review, integrate non-overlapping product improvements, and reconcile the older Hermes branch by subsystem because a direct merge currently conflicts in 181 files. Preserve every local branch and the verified all-refs recovery bundle.

**Tech Stack:** Python 3.12/FastAPI/SQLite; React/TypeScript/Vite; hermetic backend tests and browser acceptance.

**Spec:** `BACKLOG.md` entries NWS-12, NWS-23 and HEQ-1; frozen `docs/hermes/assessment.json` and capability inventory; current `AGENTS.md` and owner directions in this chat.

## Global Constraints

- The objective remains all backlog implementation and all 697 accepted Hermes contracts. Current baseline: 42 open backlog entries; 130 equivalent, 446 partial, 121 missing Hermes contracts.
- Develop locally; do not push, open PRs, merge remotely, deploy, activate paid providers, ingest private data, or change global configuration. Publication waits until the project is finished.
- Preserve native authority, Action Kernel, default-off integrations, tenant isolation and existing user data. No automatic credential or device activation.
- Keep historical evidence distinct from current implementation and live acceptance. Do not close ledger rows on narrow mock-only proof.
- One writer per file. Coordinator owns shared ledgers, plans, generated artifacts, integration, and critical review. Workers do not delegate or change branches.
- Main baseline: `1f365ceaf8f90a886175e0e5a996fb42364cb32f`. Recovery: `/Users/andrei649/Projects/nerva-recovery/20261028T181927-local-sync/all-refs.bundle`.

## Review Focus

- Lazy route deep links, authenticated admin guards, loading/error announcements, keyboard focus and a failed chunk reload path.
- Interior report-table overflow at 768, 1024 and 1180 CSS pixels, and the shared visibility badge at 320 pixels.
- Run-now origin marker is one-use and bounded; unrelated direct opens must not announce stale outcomes.
- Restore into a dangling symlink must refuse without following it, changing the archive, or creating its target.
- Foreign siblings named `workspace.db-*` or `secrets.enc.*` must retain ownership and permissions; only exact SQLite sidecars and actual secret-store temporary files are private-store entries.

## Task 1: Complete Workspace frontend NWS-12 and NWS-23

**Files:** `frontend/src/workspace/routes.tsx`, `frontend/src/workspace/routes.test.tsx`, `frontend/src/workspace/routes.chunkfail.test.tsx`, `frontend/src/workspace/i18n/messages/common.ts`, `frontend/src/workspace/features.css`, `frontend/src/workspace/pages/reports/ReportsList.tsx`, `frontend/src/workspace/pages/reports/RunView.tsx`, `frontend/src/workspace/pages/reports/startRun.ts`, `frontend/src/workspace/pages/reports/reports.test.tsx`, and `frontend/e2e/workspace-journey.spec.ts` and `frontend/src/workspace/workspace.css` as needed. Coordinator regenerates `agents/web/workspace`, BACKLOG and queue after verification.

- [x] Reuse reviewed source from `origin/lean/nws-12-code-splitting` and `origin/lean/nws-23-residual-minors`; preserve current main behavior.
- [x] Add meaningful regression coverage for lazy loading/error recovery, deep-link/authorization behavior and one-use run announcements.
- [x] Verify TypeScript and focused frontend tests. Exercise report-table and badge layout in the browser at the exact specified viewports.
- [x] Measure initial JavaScript raw/gzip size and defer admin/reports chunks. Rebuild checked-in artifacts once after source settles.

## Task 2: Complete the NWS-23 backend restore and file-permission residuals

**Files:** `agents/core/backup.py`, `agents/core/workspace/db.py`, actual secret temporary-file producer if needed, and focused regression tests.

- [x] Inspect real restore-target and secret temporary-file construction before choosing the accepted names.
- [x] Demonstrate dangling-symlink wording and foreign-prefix permission defects with regression tests.
- [x] Implement exact refusals/names while retaining existing rollback and archive validation.
- [x] Run affected backup/workspace suites and independently review security/permission behavior.

## Task 2b: Fix the discovered native macOS restore-yield defect

**Files:** `agents/core/backup.py`, `tests/test_backup_h010_review3.py`, focused process-state probes.

- [x] Prove an exited but unreaped child is still reported as holding the data root on macOS.
- [x] Extend exact zombie/dead-state detection using the already-pinned psutil dependency when /proc is unavailable; unknown or inaccessible status remains conservative.
- [x] Run the real coordinator-yield and restore/archive suites without changing timeouts or skipping the failure.
- [x] Independently review this runtime change and keep all H010/H503 authority/restore claims accurate.

## Task 3: Integrate verified wave and maintain full-scope continuation

- [ ] Review the complete diff, update only genuinely completed NWS-12/NWS-23 backlog entries and queue rows, and document any acceptance gaps.
- [ ] Reassess affected Hermes source citations (especially H503), regenerate status and run parity/route/status guards applicable to the actual changes.
- [ ] Commit one coherent local checkpoint after checks; no GitHub publication.
- [ ] Continue remaining backlog and Hermes subsystem reconciliation. The 181-conflict merge preview is evidence of integration work required, not a reason to discard local code or reduce accepted scope.

## Task 4: Reconcile the signed-provider admission foundation

**Goal:** Restore the complete source-level foundation from local `7cf98801` against current main interfaces, as the first dependency of the owner-install and selected-credential/physical-send follow-ups. H361 remains incomplete until its whole accepted contract is delivered.

**Files:** `agents/core/llm/providers/{admission_contract,admitted_profiles,admitted_registry,hook_runtime,packages}.py`, `agents/core/capability_manifests.py`, `agents/core/kernel/registry.py`, `agents/core/llm/backend_factory.py`, `agents/core/llm/openrouter.py`, `agents/core/llm/providers/__init__.py`, `agents/core/llm/providers/candidates.py`, `agents/core/llm/providers/registry_layers.py`, `agents/core/llm/provider_request.py` and the minimal prerequisites needed by these preserved interfaces, `tests/test_h361_{admitted_profile,admitted_registry,provider_hook_runtime,provider_kernel,provider_packages,signed_native_integration}.py`, `tests/test_action_auth_matrix.py`, `tests/_snapshots/action_auth.json`.

**Interfaces:** Preserve current ProviderProfile/ProviderRegistry metadata/catalog/duplicate handling, backend factory and built-in backend behavior, Kernel action types/current owner actors, and the native HTTPX egress path. Signed package admission must be additive and bind the exact package hash to host authorization; unadmitted/untrusted packages never execute hooks.

- [ ] Use an isolated native managed worktree based on local `b2b5a4ee`; retain canonical checkout and other branches.
- [ ] Port/review existing focused regressions before source; observe missing admission behavior, then reconcile source rather than blindly cherry-picking old shared files.
- [ ] Implement the full admission foundation: signature/hash/manifest validation, capability/kernel authorization, constrained async native hooks, profile/registry projection, exact backend binding.
- [ ] Run new provider suites plus current built-in provider/factory/action-authority regressions and Ruff/diff checks. No paid/native provider calls, credentials, provider activation or process-wide client defaults.
- [ ] Independent review and source integration by coordinator; do not update shared ledgers or claim H361/H367 complete from this dependency alone.

## Continuation order after this wave

Reconcile the local Hermes provider/catalog/runtime changes and current-main consent/session changes with focused regressions; integrate reviewed Workspace SQLite/OCR work; implement the remaining backlog behavior; work every missing/partial Hermes contract to its complete accepted contract; finish broad integration, clients, platform proofs and A-Z acceptance. Owner-only external prerequisites remain explicit requirements and receive no fabricated completion credit.

## Rollback and verification

Revert the local wave commit to undo product changes; original local/remote branch refs and verified bundle retain all previous work. Tests use temporary data; no production service is started for unit tests. Build verification and browser acceptance are recorded separately. Full-objective completion requires requirement-by-requirement audit, not merely this wave passing.

## Verified local progress — 2026-10-28

- `cf608ed3`: NWS-23 shared-directory ownership/diagnostic residuals, eight expected original failures followed by 43 focused passes; independent review and one reviewed warning fix.
- `1c69775b`: native macOS zombie/coordinator restore-yield regression red-to-green; live/unknown holder still blocks. Final backend integration: 371 cases, 367 passed and 4 existing platform skips, no failures or errors.
- Eight affected Hermes reviews re-read, source citations moved by content and evidence hashes refreshed; statuses remain unchanged. The 130/697 headline remains incomplete.
- Frontend source and focused 38-case tests/typechecks pass. Required report-table/badge/lazy-chunk browser checks passed, but the serial journey found an existing admin-usage 320px overflow. Fix/browser continuation remains in progress, so NWS-12/NWS-23 are not yet closed.

Final Workspace acceptance supersedes preliminary results: 2,675 native JSON frontend tests pass,31 post-review browser journey cases and one targeted read-only table case pass; all three P2s addressed. NWS-12/NWS-23 now close locally, leaving40 backlog entries. Task4 foundation is isolated at d2ad83eb,357 focused/current compatibility cases pass, independent critical review pending. No provider or H361 completion claimed.
