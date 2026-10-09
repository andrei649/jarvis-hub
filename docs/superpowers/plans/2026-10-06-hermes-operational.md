# Hermes operational continuation

Goal: make the imported runtime usable from the Hub and by a later coding session, with real action-bound approvals instead of permanently refusing privileged methods.

Base/head at start: c6a855183b26a8b45200d47834565d69aa6dcb0f. Generated: 2026-10-06. Publication remains in PR #1233; no merge or deployment.

Architecture: preserve the pinned private Hermes process and mandatory Action Kernel. Persist approval requests in the canonical TaskQueue, use its authentic approval/mediation evidence, and revalidate authority immediately before the exact frozen operation. Tool calls remain paused until a matching approval; restart, cancellation, expiry, replay, payload change and kill switch must refuse execution. Do not grant a generic session-wide approval or lower classification floors. The Hub owns all paths, credentials and action identities.

Global constraints: preserve prior work; source pin stays unchanged; default-off and safe-mode behavior remain; local fake providers only in tests; no credential values in output; no security workflow/baseline weakening; do not claim native parity for importing upstream. Actual installation/profile state stays outside Git.

Review focus: one-use approval, stale generation, substituted args, lost outcome without retry, and approval denial/expiry after the original request disconnects.

## Task 1: canonical governed approval and continuation

Owned: agents/core/hermes_runtime/{policy,bridge,worker,service,client}.py, new approval module there, agents/core/routers/hermes_runtime.py, tests/test_hermes_runtime_*.py except CLI tests. If a coordinator/runner hook is necessary, coordinate its exact path before editing.

Interfaces: add GET /api/hermes/approvals and POST /api/hermes/approvals/{task_id}/decision with strict body {approved: boolean}, admin-authenticated. Service async approval_list() and approval_decide(task_id: int, approved: bool) return bounded public task data without private tokens. Retain existing RPC contracts; queued replies include task_id and disposition. Approval must only authorize the exact canonical TaskQueue action, with live Kernel/capability/kill-switch revalidation and one-use dispatch. No ad-hoc approval database or fake approval callback.

- [x] Inspect canonical intake, approval, receipt, runner APIs and select the minimal supported wiring.
- [x] Write and observe failing tests for queue -> approved exact RPC/tool -> single execution, denied operation, payload substitution, stop/restart, double approval, timeout and authority loss.
- [x] Implement durable request state and canonical dispatch/continuation, with bounded polling rather than unlimited HTTP handler waits.
- [x] Exercise actual pinned Hermes write/command with a harmless temporary sentinel, approval and denial, plus restart revocation. Run existing Hermes backend suite. Record results and remaining constraints in /workspace/scratch/hermes-operational-core-report.md.

## Task 2: usable Hub controls and subsequent-session CLI

Owned: frontend/src/hermes-runtime-panel.tsx, frontend/src/test/hermes-runtime-panel.test.tsx, scripts/hermes_control.py (new), tests/test_hermes_control.py (new), docs/hermes/OPERATOR.md (new).

Consume Task 1 endpoints. Show pending tasks, exact target/arguments, approve/deny controls, meaningful outcomes and refresh behavior. Keep mutation requests single-attempt and approved calls separate from user/provider confirmations. Add a small stdlib operator CLI that can call the local authenticated Hub: status, start, stop, catalog, rpc, approvals, approve, deny. Read admin token from the documented environment, never print it or accept it on a command line; JSON params from file/stdin. Require loopback HTTP or explicitly configured HTTPS and refuse redirects so credentials cannot leak. Make subsequent sessions able to inspect, execute and approve through this API; no bypass of the Hub.

- [x] Write and observe failing tests for queued-action controls and CLI auth/redirection/error behavior.
- [x] Implement the controls and CLI, document exact setup/use/approval flow.
- [x] Run focused UI/CLI tests, typecheck. Report in /workspace/scratch/hermes-operational-ui-report.md. Root owns generated build assets and route/schema snapshots.

## Task 3: CI, integration, installation and publication

Root owns existing failure fixes after reproduction, generated snapshots/assets/status, integration docs/evidence, commits and PR publication. Reproduce real CI failures or local aggregate failures; fix root causes without disabling tests or permission gates. Run full backend only after implementation freezes, full frontend once at final milestone, real installed runtime and scanner contracts. Provision and leave a private verified local installation for later use if the existing instance can be reused safely; no provider credentials or production activation. Publish truthful usable scope and exact remaining external configuration needs.

- [x] Reproduce and fix actionable backend failures.
- [x] Review Task 1 authority boundary and Task 2 UX/CLI.
- [x] Run stable final integration and required checks; update snapshots and evidence.
- [ ] Publish the verified continuation to the same PR and verify remote head/check results.

Rollback: stop the runtime, disable JARVIS_HERMES_ENABLED, revert this continuation's commit(s); preserve the private profile and prior accumulated work.

Final local verification: 2026-10-06, base c6a855183b26a8b45200d47834565d69aa6dcb0f. Full backend: 24,611 passed, 55 skips and one expected failure (24,667 collected), zero failures/errors, 762.222 seconds; 5,455 frozen paths did not drift. Full frontend: 1,985 passed, typecheck and production build passed. Pinned-runtime approval/denial/restart probes and the authenticated full-Hub CLI probe passed without real provider calls. Ruff, unchanged-baseline Bandit, unchanged-config Semgrep and Gitleaks passed.

Changed path groups: agents/core/hermes_runtime, canonical TaskQueue/Kernel dispatch, Hermes admin router, HUD panel and compiled assets, stdlib operator CLI, integration/acceptance tests, narrowly reproduced aggregate-suite repairs, generated contracts/status and integration evidence. Source pin unchanged. Native equivalence remains 124/697; runtime import receives no native-equivalence credit.

Next action: publish the frozen continuation in PR #1233 and inspect its reported GitHub checks. No merge or deployment is part of this request.
