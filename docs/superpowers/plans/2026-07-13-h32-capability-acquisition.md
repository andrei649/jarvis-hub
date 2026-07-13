# H32 Governed Capability Acquisition Implementation Plan

> Execute after H28/H29 registry and ToolRPC changes merge. Use strict TDD, one task at a time,
> sandbox receipts before promotion, and fresh review per task.

**Goal:** close the explicit capability-miss -> reuse -> governed research -> strict-local
generation -> isolated verification -> owner approval -> signing/marketplace -> sandbox-bound
registry -> reuse/rollback loop.

**Master setting:** `acquisition.enabled`, default false; Product Posture cannot enable it. Recheck
it before capture, research, generation, promotion, registration, and every acquired execution.

**Completion (2026-07-13):** Tasks 0–7 are implemented. The dedicated CI lane passed the full
digest-pinned Docker S2 lifecycle, including private runtime-UID mounts, host/network negatives,
tamper refusal, kernel halt, revoke/uninstall, and upgrade rollback. The checklist below is retained
as the original execution contract and review trail.

## Task 0 — Isolation and collision preflight

- [x] Rebase on current main and confirm Claude's stale Agent Runtime worktree is abandoned or
  integrated before touching `agent_runtime.py`, ToolRPC, orchestrator, or settings.
- [x] Require `Sandbox.active_backend()` to be `docker` or `wasm`. `disabled`, host subprocess,
  and mocks cannot satisfy H32.4/H32.7.
- [x] Build a dedicated hostile-code acquisition profile: non-root uid/gid, all capabilities
  dropped, `no-new-privileges`, pinned OCI digest/runtime hash, no host network/namespaces/devices/
  sockets, read-only root/source, isolated size-capped scratch/tmp, strict memory/pids/cpu/time/
  output enforcement, and no host fallback. WASM must prove equivalent memory/filesystem bounds.
- [x] Run a real hostile smoke receipt and bind the actual OCI digest/runtime attestation, never a
  mutable tag string.
- [x] If Docker/WASM is unavailable, continue request/reuse/research code only; mark acquisition
  promotion/reality honestly blocked rather than weakening isolation.

## Task 1 — H32.1 explicit durable capability-request plane

**Create:** `agents/core/acquisition/models.py`, `store.py`, focused tests; modify narrow Agent
Runtime and registry seams.

- [x] Red tests: only an explicit bounded tool/capability miss creates a request; normal unanswered
  chat does not. Validate redaction, goal/fingerprint bounds, dedupe, restart, lifecycle,
  concurrency, corruption, retention, and no repository writes.
- [x] Add registry state/source for `missing` without weakening SEAM/WIRED/VERIFIED/GA readiness.
- [x] Add an injected Agent Runtime gap callback after honest registry/tool refusal; capture a
  redacted goal and hash under runtime data.
- [x] Encrypt request goals/projections at rest; cap at 1,000 requests/16 MiB and 30 days unless an
  unresolved owner decision retains a redacted fingerprint. Purge removes goals and derived reuse
  state while preserving a non-sensitive tombstone/audit hash.
- [x] Provide read/status APIs only after auth/parity classifications are designed.
- [x] Run Agent Runtime/registry/store tests, Ruff/Bandit, review, and commit.

## Task 2 — H32.2 deterministic reuse-first resolver and metric

**Create:** `agents/core/acquisition/resolver.py`, focused tests; reuse registry, SkillLoader, and
reviewed marketplace APIs.

- [x] Red tests for exact/semantic goal ranking, deterministic ties, disabled/untrusted/quarantined
  candidates, version compatibility, local registry -> installed skill -> reviewed marketplace
  order, approval requirement for install, and zero network/generation before reuse exhaustion.
- [x] Persist decision provenance and terminal outcome. Define reuse rate as
  `reused / (reused + generated)`; blocked/abandoned requests remain visible but do not inflate it.
- [x] Verify reused capabilities execute through their existing ToolRPC/kernel/sandbox boundary.
- [x] Run skill/marketplace/registry tests, review, and commit.

## Task 3 — H32.3 governed, taint-preserving document research

**Create:** `agents/core/acquisition/research.py`, focused tests; reuse WebSearchPlugin,
PluginHTTPClient, injection/taint, and `ground_plan`.

- [x] Red tests: default-off/no backend, explicit owner consent for any network/cloud hop, local
  SearXNG provenance, allowlisted/SSRF-safe bounded fetch, redirect/DNS rebinding, byte/time/source
  caps, taint preservation, injection quarantine, source URL/hash anchoring, and no raw secrets.
- [x] Stream every fetch under a hard received-byte cap independent of `Content-Length`; abort
  chunked overflow, revalidate each redirect hop/address, and release response, connection, and
  partial buffers on overflow/truncation/cancellation.
- [x] Do not implicitly fall back to DuckDuckGo. Draft with a strict-local model seam.
- [x] Wrap `ground_plan` with a non-empty references/steps hard gate; every implementation step
  cites a fetched source id/hash and phantom citations fail.
- [x] Store only bounded source extracts and hashes; research content remains tainted and can never
  auto-authorize installation or execution.
- [x] Encrypt extracts at rest, cap each source/plan and the aggregate store, expire research after
  7 days, and purge it with the capability request unless retained as hash-only audit evidence.
- [x] Run websearch/egress/grounding/taint tests, review, and commit.

## Task 4 — H32.4 strict-local generation, quarantine, and isolated test receipt

**Create:** `agents/core/acquisition/generator.py`, quarantine/receipt modules and focused tests;
do not use `SkillLoader.generate_skill()`'s repository-writing path.

- [x] Red tests: strict-local generator route, runtime quarantine location, no repository `skills/`
  write, mandatory implementation plus verification test, path/symlink/archive escapes, code/size
  caps, dependency allowlist, no network/secrets, and isolation hard floor.
- [x] H32 v1 generated code is stdlib-only. Imports outside an explicit stdlib subset fail; no
  runtime package installation or network dependency resolution is permitted.
- [x] Run generated tests in Docker/WASM with read-only source, explicit scratch mount, no network,
  caps, timeout/cancellation, bounded output, and cleanup.
- [x] Do not trust model-generated tests alone. Add system-owned goal/entrypoint contract tests and
  anti-vacuity mutation checks: public entrypoint is exercised, goal-specific behavior is asserted,
  and the suite must fail against a negative/mutated implementation.
- [x] Produce an immutable receipt binding source, plan, model route, code, test, sandbox image/
  runtime, config, output, exit status, and timestamps by hashes.
- [x] A failing/missing/timed-out/tampered test never creates an approval proposal.
- [x] Encrypt quarantine metadata/artifacts at rest, cap each package and total store, expire
  rejected/abandoned artifacts in 7 days, and support immediate purge/cancel on disable/revoke.
- [x] Run sandbox/quarantine/trust tests and one real isolated smoke, review, and commit.

## Task 5 — H32.5 approval, receipt recheck, signing, registry, and rollback floor

**Create:** acquisition promotion broker, managed signing manifest, runtime acquired-package store,
sandbox ToolRPC runner; modify capability manifests/kernel registry, marketplace history,
TaskExecutor wiring, and focused tests.

- [x] Add a kernel-mediated `skill.install` action with permanent approval hard floor. Earned
  confidence cannot auto-install generated code.
- [x] Persist a bounded canonical proposal. At approved execution, revalidate task status and all
  receipt/artifact/source hashes to prevent TOCTOU, then sign and install through the reviewed
  marketplace path atomically.
- [x] Fail closed without a managed signing key. Sign a canonical manifest covering every package
  member, relative path, mode, size, content hash, entrypoint, tests, stdlib policy, receipt, and
  runtime digest. Record key id/version/rotation and verify after extraction and before every run.
- [x] Install into a runtime acquired-package store outside repository `skills/`, with persistent
  `execution_mode=acquired_sandbox`. `SkillLoader.discover()` must refuse to import these packages
  under every configuration/restart. Marketplace metadata may index them but cannot copy them into
  the normal in-process skill tree.
- [x] Register a concrete ToolRPC -> acquisition sandbox runner only after promotion. Every call
  rechecks enabled/revoked status, manifest/package hash, signing key, pinned backend attestation,
  resource profile, and capability binding; unregister denies new calls immediately and safely
  drains/cancels in-flight runs.
- [x] Signed means integrity/provenance, never permission for in-process import.
- [x] Register skill/tool identity at low confidence and generalize outcome projection beyond
  action records without manufacturing evidence.
- [x] Use a durable staged transaction journal across SQLite/package store/ToolRPC registration:
  prepare -> verify/sign -> install -> register -> committed, with restart reconciliation that
  rolls forward a fully verified stage or revokes/removes partial state. New-skill rollback is
  unregister/revoke/uninstall; upgrades restore the retained prior package. Test every crash point.
- [x] Run kernel/action-auth/signing/marketplace/rollback tests, review, and commit.

## Task 6 — H32.6 audit ledger, operator surfaces, and lifecycle controls

**Create:** tamper-evident acquisition ledger and domain router/HUD/mobile read surfaces.

- [x] Record request/reuse/research/generation/sandbox/approval/signature/install/registry/
  execution/revocation/rollback events with hashes and actor/task ids, not raw secrets or sources.
- [x] Encrypt any non-hash ledger projections, cap the ledger at 100,000 rows/64 MiB with 90-day
  detailed retention plus hash-chain summaries, and define owner purge/export semantics.
- [x] Admin mutations and user-readable status use separate guarded endpoints; expose honest
  disabled/blocked/quarantined/installed/revoked/degraded states plus reuse rate.
- [x] Add revoke/rollback controls that cannot bypass kernel/receipt checks.
- [x] Update route/OpenAPI/auth/HUD/mobile parity and generated types in the same slice.
- [x] Run backend/frontend/mobile tests, review, and commit.

## Task 7 — H32.7 S2 acquisition reality proof and truth sync

- [x] Under a real Docker/WASM backend, prove a net-new hermetic skill request: miss -> no reuse ->
  grounded local source fixture -> strict-local generation -> isolated passing test -> blocked
  approval -> receipt recheck -> signed install -> sandbox-bound execution -> registry outcome ->
  second request reuses it.
- [x] Negative cases prove no host execution, no install before approval, hash tamper refusal,
  kernel halt, revoke/uninstall, upgrade rollback, and no network from generated code.
- [x] Report reuse metric honestly and keep optional live web research separately gated.
- [x] Run all H32 plus registry/ToolRPC/sandbox/marketplace/kernel/reality/parity, full repository,
  frontend/mobile, Ruff/Bandit/diff-check/status-sync.
- [x] Fresh final review, truth sync, draft PR, CI monitoring, merge.

## Rollback

Disable the acquisition master flag to stop capture/research/generation. Revoke acquired registry
identities, uninstall new packages, restore retained prior versions, and preserve the bounded audit
ledger. Quarantine data is purgeable and never required for normal Jarvis startup.
