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

- [x] Review the complete diff, update only genuinely completed NWS-12/NWS-23 backlog entries and queue rows, and document any acceptance gaps.
- [x] Reassess affected Hermes source citations (especially H503), regenerate status and run parity/route/status guards applicable to the actual changes.
- [x] Commit one coherent local checkpoint after checks; no GitHub publication.
- [ ] Continue remaining backlog and Hermes subsystem reconciliation. The 181-conflict merge preview is evidence of integration work required, not a reason to discard local code or reduce accepted scope.

## Task 4: Reconcile the signed-provider admission foundation

**Goal:** Restore the complete source-level foundation from local `7cf98801` against current main interfaces, as the first dependency of the owner-install and selected-credential/physical-send follow-ups. H361 remains incomplete until its whole accepted contract is delivered.

**Files:** `agents/core/llm/providers/{admission_contract,admitted_profiles,admitted_registry,hook_runtime,packages}.py`, `agents/core/capability_manifests.py`, `agents/core/kernel/registry.py`, `agents/core/llm/backend_factory.py`, `agents/core/llm/openrouter.py`, `agents/core/llm/providers/__init__.py`, `agents/core/llm/providers/candidates.py`, `agents/core/llm/providers/registry_layers.py`, `agents/core/llm/provider_request.py` and the minimal prerequisites needed by these preserved interfaces, `tests/test_h361_{admitted_profile,admitted_registry,provider_hook_runtime,provider_kernel,provider_packages,signed_native_integration}.py`, `tests/test_action_auth_matrix.py`, `tests/_snapshots/action_auth.json`.

**Interfaces:** Preserve current ProviderProfile/ProviderRegistry metadata/catalog/duplicate handling, backend factory and built-in backend behavior, Kernel action types/current owner actors, and the native HTTPX egress path. Signed package admission must be additive and bind the exact package hash to host authorization; unadmitted/untrusted packages never execute hooks.

- [x] Use an isolated linked worktree based on local `b2b5a4ee`; native tooling rejected the nested sourceRoot, so the documented manual fallback preserves canonical and other branches.
- [x] Port/review existing focused regressions before source; observe missing admission behavior, then reconcile source rather than blindly cherry-picking old shared files.
- [x] Implement the full admission foundation: signature/hash/manifest validation, capability/kernel authorization, constrained async native hooks, profile/registry projection, exact backend binding.
- [x] Run new provider suites plus current built-in provider/factory/action-authority regressions and Ruff/diff checks. No paid/native provider calls, credentials, provider activation or process-wide client defaults.
- [x] Independent review and source integration by coordinator; do not update shared ledgers or claim H361/H367 complete from this dependency alone.

## Task 5: Complete Workspace SQLite work off the event loop (NWS-13)

**Files:** `agents/core/routers/workspace_{admin,approvals,auth,chat,reports}.py`, `agents/core/workspace/{approvals,documents,http,reports}.py`, `tests/test_workspace_sqlite_off_loop.py`, relevant existing Workspace regression files, and the specific concurrency/cancellation section of `docs/business/WORKSPACE_PILOT_SPEC.md`.

**Interfaces:** All synchronous SQLite transactions and FTS work reachable from async Workspace handlers/background coroutines must execute off the event loop as complete synchronous units. Preserve the five-second SQLite busy timeout, BEGIN IMMEDIATE/audit chain, per-user/department checks, error semantics, request-owned connection lifetime, cancellation and no transaction held across a model/SMTP await.

- [x] Reuse/review the source dependency slice on `origin/lean/nws-13-sqlite-off-loop` against current main plus the completed NWS-23 storage fixes; do not transplant stale ledgers/artifacts.
- [x] Audit all async Workspace SQLite call paths; choose one coherent offload helper and preserve synchronous caller compatibility.
- [x] Prove a real held SQLite write lock does not stall an unrelated async request/event-loop heartbeat, then implement; cover cancellation without closing a connection still used by a worker, transaction completion/rollback, exceptions and FTS.
- [x] Run relevant Workspace auth/upload/chat/report/approval/scheduler/storage suites and independent review; update the concurrency spec alongside source.
- [x] Coordinator integrates, updates BACKLOG/queue and generated evidence only after current-state proof. No live accounts, providers, mail delivery or production service changes.

## Task 6: Owner installation lifecycle

Use the reviewed provider worktree at c540114f and reconcile the installation dependency from 0c67599d: signed inspection/inventory, exact one-use owner decisions, current Kernel authority, redacted default-off service/routes, durable async revocation. Preserve native dispatch allowlist and all reviewed transport guards. Verify owner/action/route/provider compatibility and independent review before integration. Scope and tests: ignored SDD task-6-brief.md/task-6-inventory.md. The native dialect bridges remain required in Task8; selected credentials/physical runtime follow them.

## Task 7: Optional bounded local OCR (NWS-10)

Use the isolated workspace-ocr worktree at c6a30304. Reconcile origin/lean/nws-10-ocr-scanned-pdf source with actual child-only execution, page/document/resource bounds, descendant cleanup, missing-engine/default-off behavior, truthful OCR/partial limits and extraction regressions. Preserve originals and current SQLite/storage behavior; no mandatory engine install or private input. Scope and tests: ignored SDD task-7-brief.md. Coordinator closes NWS-10 only after source/integration/review acceptance; no cloud or native engine success inferred from fakes.

## Task 8: Complete guarded native dialect bridges

After Task6, reconcile every admitted native cloud dialect (Anthropic/Gemini/DeepInfra/Responses/xAI) from 0c67599d with a per-dispatch physical lease, exact host/credential/protocol/data binding and honest ambiguous-egress accounting. Cover text/tool/stream/retry paths before widening the factory allowlist. Then reconcile selected host-managed credentials/runtime from42eeda3e. These are full-scope remaining requirements, not completed by the admission foundation.

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

Reviewed integration checkpoint c6a30304: Task4 source foundation passes its three fix rounds and465 covering tests; Task5 passes scoped/extended suites and independent10cancellation+4SMTP checks. NWS-13 closes locally, leaving39 backlog entries. Global Ruff passes (one pre-existing invalid-noqa warning). Canonical broad backend integration and affected-provider review pins are the next milestone; H361/H367 remain incomplete. Task6 owner lifecycle and Task7 OCR are isolated implementations; Task8 remains required.

Full canonical backend milestone at c6a30304 plus recorded metadata diff: 29,781 collected, 29,687 passed,21failed,73skipped in1068.349s; this is not a green full suite. Failures group into5provider integration cases,7existingMac extraction cases and9TLS/uninstall/log cases. Scope/status metadata checks pass after three precise citation corrections. Follow-up integration repairs remain required; no remote publication.

Owner installation checkpoint5e1b6308: reviewed Task6 lifecycle and cancellation/redaction fixes plus Task8 async-admission prerequisite integrated locally. Current 15-file owner/route/evidence integration:393cases,392passed/1skip. All37affected claim reviews re-read, exact citations/pins refreshed; no verdict change, Hermes remains130equivalent/447partial/120missing, all697accepted. Fresh backend collection29818, routes714, frontend2675unchanged, mobile359reused. Full29781-case milestone remains failed21until the isolated repair batch is reviewed and integrated.

Task9 is the broad integration/capability/TLS/Mac fixture repair, with separate rollback units. Task10 now names selected encrypted credentials/router/pinned physical runtime from42eeda3e (earlier Task8 worker notes called this Task9). Task7 round2 repairs process enumeration failure during page/document cleanup; NWS10 is not closed. Task8 native bridge requires a distinct contract-bound signed egress receipt through the real current Kernel before acceptance, without lowering its tier3 policy or granting arbitrary plugin.egress.

Task9 A/B/manual repair integrated locally through81431045 after scoped independent reviews. Integrated capability/owner/TLS/uninstall/log suites:287passed,0skips/failures. Trusted OpenSSL PEM retains AUX serverAuth/reject purposes; the deliberate runtime rejected CA remains untouched. All21affected claims source-reassessed;130equivalent/447partial/120missing, no new parity credit. Fresh backend collection29823/routes714; frontend2675unchanged/mobile359reused. This focused result does not replace the failed29781-case broad milestone; OCR/native source remains isolated pending fix review.

Task9 evidence checkpoint:287integrated source cases passed; metadata/status/context guards259total=258pass/1skip; all21affected claims re-read with no verdict upgrade. Fresh collection29823/2675/359(reused mobile),714routes; all697accepted,130equivalent447partial120missing. OCRround3 and native-round1 peer review remain active; their isolated source is not credited as delivered.

## Task 11: Windows OCR resource ownership

Implement the Job Object backend from the bounded Windows design in an isolated593b53ae worktree. Own handles and descendant membership at creation with JOB_LIST and a strict inherited stdio whitelist; configure process/aggregate commit limits and kill-on-close before execution. Preserve parent page/document deadlines and cancellation cleanup before resource release. Use lazy Windows APIs, Proactor-compatible bounded pipes and no new mandatory/global dependency. Mac fake-kernel and existing POSIX regressions validate logic only; actual Windows process/commit/pipe/crash/frozen and real-engine tests remain required before enabling native Windows OCR. Existing Windows extraction remains time-only and OCR fail-closed until that proof. Root owns metadata; source rollback is a separate local commit.

OCR/native integration through593b53ae:410extraction and154native/usage cases pass on canonical; native round2 independent review clears all3stream findings. Global Ruff passes. Full backend milestone remains pending and no real engine/provider/Docker/platform acceptance is inferred.

## Task 10A: Inert owner credential dependency

Implement a private Fernet-only credential envelope, exact current signed-record/home binding, durable generation and metadata-only owner API in an isolated2bd56156 worktree. Reuse the existing cipher without fallback or decrypted cache; derive authority from the server and a live owner actor. The new tier3 provider.credential action requires an exact real-Kernel receipt, current mode/kill/taint checks and cancellation-drained durable mutations. No credential reaches a worker, Action, log, response or backend. Cover signed-owner integration, tamper/binding/path/concurrency, malformed-input non-echo and existing provider/security guards. API/action snapshots and explicit HUD/mobile gaps accompany source. This is an inert dependency: Task10B must still implement durable selection, generic-writer fencing, router/privacy policies, shared6dialect guard, lifecycle rotation/revocation drains and publicDNS/IP/SNI before any activation.

Native/OCR evidence checkpoint2ba96cdc: Task8 fixture round3 adds only the real built-in Anthropic profile to three synthetic __new__ fixtures;70tool-turn,230related and154native/usage cases pass, scoped independent review approved. All109affected OCR/native/flag claims plus11fixture claims were re-read, exact citations resolved and no verdict promoted. Current status:130equivalent/447partial/120missing/0stale, all697accepted,642reviewed;39backlog open. Fresh backend collection29947, frontend2675unchanged, mobile359reused, routes714. Metadata/context guards259cases=258passed/1skip. The full backend run on this frozen batch is still pending; older21fail milestone remains historical.

## Task10B1: Signed selection storage and writer fencing

Implement an inert CAS selection record and cross-process shared/exclusive selection gate, then fence every settings pair writer before SQLite: direct PUT/CLI, import, reset/undo, migration and initialization. Revalidate H378 effective choices after awaits and drain started offloaded writes on cancellation. Add invalidation triggers for strict readback, without treating them as a physical-send lease. Preserve ordinary settings on unsupported hosts while signed selection fails closed. No owner route/backend activation yet;10B2 still owns actual router/credentials/publicDNS-IP-SNI/common six-dialect guard and lifecycle drains. Work is isolated and does not overlap Task13 repair files.

Reviewed local checkpoint2a0fd7a8: owner vault/HWM b459b86, typed context refusal0a719714, gated Windows OCR+finite parent clocks dd388fa, exact credential metadata manual ae788164/81731e75, and Task13 integration repairs through2a0fd7a8. Broad b11 milestone recorded29947total/29866pass/8fail/73skip; Task13 now passes229currentcanonical cases includingAPI10, while prior post-wave688cases had684pass/4nativeWindows-skips. GlobalRuffpasses. All178affected claim records were semantically re-read/citations resolved, no verdict upgrade; current130equivalent447partial120missing0stale642reviewed, all697accepted. Fresh collection30020backend,2675frontend unchanged/359mobile reused,717routes. Metadataguards259cases258pass1skip. These scoped checks do not constitute a new full-suite pass; selected runtime, realengine/provider/container andnativeplatform gates remain open. B1 selectionfence201cases and two fixrounds are independently approved in isolation, nextintegration;10B2 physical routing remains required.

## Task10B2: Owner-selected physical provider runtime

From reviewed3b27d20, implement the complete owner select/status/clear service, distinct exact tier3 selection receipt, current signedmodel declarations and honest unknownprice/data acknowledgements. Wire exact selected H513 scope andlocal-only/model/job rules throughrouter andsharedsix-dialect preparedtransport. Inject VaultHWM-bound keys onlyinto ephemeral verified publicIP/Host/SNI wirecopies, oneattempt pool andoneegress record. Preserve selection/lifecycle/package/credential lockorder anddrainbeforeEX mutations, bodyownership/cancellation andbusyrefusal. Syntheticowner/Kernel/TLS/DNS/race tests establish source behavior; liveprovider/engine/Windows/Docker/UI/mobile/SDK breadth remain separate acceptedrequirements. Rootownsmetadata andfullmilestones.

## Task15: Complete H391 turn-compaction lifecycle

From reviewed3b27d20, implement distinct turn-start/idle/pre-API/post-turn gates, material-progress and real-usage anti-thrash controls, genuine-user reanchoring, reference-handoff guard and visible deduplicated pressure warnings. Preserve opt-in defaults and selected-route budget checks. Durable micro-summary views must retain original transcripts and publish only through matching source/clock CAS; restart, revision, cancellation and late-worker tests are required. Isolated source ownership excludes all B2 provider/router/Kernel paths. Root owns shared evidence and serial full milestones; live provider acceptance remains separate.

B1 integrated checkpoint3b27d20: reviewed storage/writer fencing and both fix rounds pass201canonical cases. All184affected Hermes records re-read and refreshed without verdict upgrades;0stale,130equivalent/447partial/120missing,642reviewed/all697accepted. Fresh backend collection30038,717routes, frontend2675unchanged/mobile359reused. Metadata guards258pass1skip; Ruffpasses. A new serial full backend run is required to verify the Task13 repairs and B1 together; previous full b11 result remains8fail. No selected provider or production service has been activated.

Full backend milestone34424df2 completed:30038collected,29933passed,6failed,22errors,77skipped in1076.891s, clean source unchanged. Priorb11 eight failing exact tests nowallpass. Task18 triage reproduced24namespace cases (22Gemini setup+2voice500), a fresh-process Anthropic/tool_rpc circular import behind the mount-test failure, and three registry/static-guard/doc-count mismatches. These remain required fixes, not flaky skips.

## Task18: Backend integration follow-up

Align cache fixtures and voice settings consumers with the canonical namespace while retaining exact B1 store/lease validation. Rename the Windows OCR owned process handle so the Workspace personal-pipeline guard remains strict; retain all lifetime/native acceptance gates. B2 owns the adjacent refusal-kind and eager image-validator import repairs. Root updates present-tense roadmap counts from the actual HUD punch list. Use isolated focused red/green proofs, independent review and a new serial full milestone after the source batch is stable.

## Task19: Governed browser runtime foundation

From reviewed e074fbc6, connect the real fresh-profile Chromium driver to one bounded owner-approved ToolRPC plan and exact per-step Kernel receipt, pinned public network policy and verified cleanup. Add the owner Operator HUD action and prove the actual local synthetic page flow, denial, timeout and cancellation. New browser dependencies belong in an isolated project environment while the canonical full-suite environment stays fixed. This is the runtime foundation; every accepted advanced browser, engine, profile-consent, recording and reaping milestone remains required afterward. No production flag, private profile, external site, paid provider or service is activated.

## Task21: Shared guard registry on signed selection

A synthetic extra-guard probe showed that the new signed owner selection could persist without executing the common H378 registry. Run that registry on the exact trusted candidate before CAS, preserving signed policy/unknown-price acknowledgements, live owner/Kernel authority, nonreentrant lock order and audit failure refusal. Registered denial or exception must leave the selection unchanged. This is an integration repair; the reviewed provider streaming and H391 fixes remain intact.

## Task22: Durable consent proof for selected providers

An internal selection CAS with true acknowledgement flags currently grants selected runtime and unattended H513 acknowledgement without the owner selection Kernel/audit path. Add durable authenticated consent proof bound to the exact revision, signed configuration, model, credential generation and policy. Mint only after the live owner, shared registry, Kernel and required audit decisions; verify on runtime readback and actual use. Missing, altered, replayed or unavailable proof fails closed. Preserve atomic CAS, restart behavior, lifecycle drains, secure private key ownership and built-in/role policies. This is a trusted internal storage seam; no external exploit or whole-host anti-rollback claim is implied. Independent review and covering tests precede integration.

Local checkpoint at11965931: H391 and B2 plus their reviewed fixes pass1060 combined cases; Task21 exact-candidate common registry is independently approved and passes322 canonical cases. All246 affected claim records were semantically reviewed, citations resolved and current source pinned. H513 is explicitly downgraded for the newly discovered selected-consent gap:129equivalent/448partial/120missing/0stale,642current reviews, all697accepted. H391 remains partial pending the next serial full backend milestone. Fresh collection30130,720routes; frontend2675 unchanged, mobile359 reused. Task19 real Chromium foundation and Task22 consent proof remain isolated and receive no integrated credit. The latest completed full backend remains34424df2 with6failures/22errors, despite focused fixes for those reports. No remote publication or production activation.

Checkpoint metadata verification:259cases,258passed/1optional skip; whole agents/scripts/tests Ruff and diff checks pass. Hermes reports and generated project status are in sync. Manual source-only CBM and curated Graft caches were refreshed; three pre-existing unrelated frontend parse gaps remain explicit. This prepares a frozen serial30130-case backend milestone; its result must be recorded before integrating the isolated browser/consent batch.
