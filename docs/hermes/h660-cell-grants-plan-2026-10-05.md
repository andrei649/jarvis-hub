# H660/H595 cell grants — local correction

Goal: all697 Hermes capabilities. Previous goal turn made progress: H067 gateway
contract accepted,129/697 equivalent. Base/head
a7ffad6676cfb28e7ac374d495b4a5889e5f4646; generated2026-10-05; no publication.

Pinned H660 requires authorization for each cell, not only interpreter startup.
Current code_tools._authorize_cell rejects DENY but admits QUEUE/unknown/missing
decisions. SessionKernelManager.run authorizes before waiting on a record lock,
then dispatches without rereading policy. Both are concrete discrepancies in the
canonical requirement, not new acceptance gates.

Plan before source edits:
1. Reproduce non-GRANT cells and policy revocation during a held resident lock
   with the actual worker, CodeExecutionTool and existing kernel test fixtures.
2. Require an explicit GRANT for model-facing session/fallback dispatch. Missing,
   malformed and queued authorizers refuse before process creation or cell input.
3. Retain startup authorization and recheck after acquiring the resident lock,
   immediately before dispatch. Refusal preserves existing interpreter state.
   Also authorize an explicit reset before teardown: RED reproduced a denied
   reset discarding the previous variables even though its cell was refused.
4. Run affected code/kernel/runtime tests, existing production composition tests,
   scoped Ruff/Bandit/secret scan, frozen source checks and explicit Graft refresh.
   Record current evidence while H660/H595 remain partial for remote transports.

Scope: agents/core/code_tools.py, agents/core/session_kernels.py, corresponding
tests and docs/hermes evidence/status. Test-only worker hosts may supply an
explicit synthetic GRANT; production composition already supplies action_kernel.
No global ToolRPC policy rewrite, remote provisioning, provider spend, schema
changes, new dependencies or optional extensions in this correction.

Rollback: localized diff against external snapshot
/tmp/nerva-h660-cell-grants-baseline-20261005. Preserve inherited dirty work;
never reset, stage, commit, push, merge or deploy. Next action after correction:
reuse Hermes detached-kernel transport for the remaining pinned H660 backends,
with Nerva's existing isolation and per-cell authority contracts.

Canonical default continuation, planned before edits: H660 explicitly retires
the separate kernel-mode switch. Nerva still defaults its session setting off in
tool, coordinator and status route. Once execute_code is owner-enabled and an
isolated pinned backend is configured, default to the resident manager without
requiring a second opt-in; preserve explicit False as an existing owner override.
Code execution itself remains opt-in, no process starts at composition, and
missing pinned isolation still reports the existing one-shot/unavailable reason.
Add RED tests for actual two-cell persistence, production manager composition
and reported route mode. Additional localized paths: autonomy_coordinator.py,
routers/skills.py and matching route tests. No new endpoint or dependency.

Physical-dispatch check: reuse the existing bound kernel.revalidate API rather
than authorizing the same cell twice. Its contract is non-consuming (budget,
loop detector and audit); a second authorize can incorrectly exhaust a one-cell
budget. Test normal/reset cells with such a budget, retain one original grant
and use live revalidation for subsequent startup/lock/fallback checks. Pure test
authorizers without revalidate retain the conservative full-authorize fallback.
