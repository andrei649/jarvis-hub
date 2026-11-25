# H515 job continuation and remaining providers

**Goal:** Finish Krea's interruption recovery, then integrate donor xAI and DeepInfra image contracts into the same local workflow.

**Head:** `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`; existing dirty consent worktree. Generated 2026-10-06. Root owns shared runtime/API/worker interfaces; two retained implementation agents own isolated provider modules/tests and the bounded frontend scope, then review each other's integrations read-only.

**Architecture:** Krea continuation is a new signed `plugin.egress` GET task bound to the original immutable proposal, nonce, recorded job ID and credential generation. Its fresh execution receipt authorizes polling and result admission; it can never submit a generation POST. Both executions use a nonblocking portable per-source-job lock, released on process exit. Publication is canonical to the original source task, so concurrent continuations reuse one artifact and completion.

**Constraints:** All697 remains the target. No publication, activation, live/billable calls, dependency installation or credential imports. Preserve current modifications. Reuse donor modules/tests and the existing PermissionGate, public-DNS transport, mediated worker and HUD. Result downloads carry no API credentials. Do not rewrite queue authority or retry an interrupted mediated task.

## Implementation

- [x] Add `CloudImageRuntime.resume(task_id, origin, actor)` and a strict continuation descriptor. Validate recorded job/binding/generation, original human decision and exact fixed job endpoint; reject missing/altered records, completed sources, source cycles and provider changes.
- [x] Add nonblocking per-source execution locking. Refactor only the Krea submit branch: normal tasks retain one POST, continuations skip it and enter the existing bounded polling/download/finalization path. Persist one source completion and reuse it without further network calls.
- [x] Extend the existing generation request/tool with `resume_task_id` (Krea only, empty prompt and no new generation options). Add owner-visible `resume_available` to task metadata and a HUD continuation action which queues once and follows the new task through Decision Inbox approval.
- [x] Verify restart recovery using a freshly constructed runtime, durable job state and real signed tasks. Test immutable source tampering, credential/config withdrawal, active execution, concurrent continuations, receipt requirements, no POST and canonical catalog/artifact reuse.
- [x] Adapt xAI fixed native generation/edit payloads and DeepInfra dynamic catalog/image payloads. Do not replace DeepInfra discovery with a guessed small model list. Root owns approved catalog acquisition/persistence and integration.
- [x] Integrate verified provider seams, model metadata and HUD controls without silent fallback. Run focused step tests and the affected milestone union; save current-source receipts, review, hashes and exact security scan. Update only inspected H515 evidence, preserve unrelated stale pins and report remaining gaps.

**Verification scope:** Injected provider HTTP through the composed mediated worker, authenticated API and registered tool; frontend control/approval tests, typecheck/build, route/parity guards and narrow security checks. These are local proofs; no live/provider or native-device acceptance is implied.

**Rollback:** Restore only this batch's exact preimages in `/tmp/nerva-h515-continuation-provider-baseline-20261006`; never reset the checkout or touch unrelated dirty paths.

**Review corrections:** Original Krea approval identity and actual continuation execution are privately bound; unexecuted siblings cannot inherit ready results. xAI admits the official documented result host in its disabled restricted manifest. DeepInfra caches bind result digest, execution identity and current configuration. Legacy Krea jobs missing private authority proof remain non-resumable.

**Results:** 786 affected backend tests, 1965 full frontend tests and 120 record/route/schema gates passed. Typecheck/build and scoped Ruff/Bandit passed. Independent review corrections and current graph freshness are recorded with exact source hashes in `docs/hermes/evidence/2026-10-06-image-continuation-xai-deepinfra/`.

**Next action:** Separately approved Krea Enhance and remaining H515 donor contracts. No full697 or live acceptance is claimed by this batch.
