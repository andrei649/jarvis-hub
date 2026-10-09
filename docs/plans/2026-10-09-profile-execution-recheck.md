# Tool profile recheck at dispatch

- Generated: 2026-10-09 UTC. Base/head before edit: `c72f176` on `codex/profile-execution-recheck-20261009`.
- Goal: a model tool call that was offered earlier in a turn cannot start preflight/intake/handler after its current profile has revoked that registered tool, even when no context fold refreshed the offer.
- Root cause: `AgentToolRuntime` snapshots provider specs and gate/taint views at turn start or a fold; `_execute_rpc` awaits its event sink before a child task calls `ToolRPCServer.handle`, whose preflight currently has no profile check. The existing H672 no-fold test proves the revoked handler runs.
- Paths: `agents/core/agent_runtime.py`, `agents/core/tool_rpc.py`, `agents/core/autonomy_coordinator.py`, `tests/test_h672_compaction_refresh.py`, new `tests/test_tool_profile_execution.py`, and this plan.
- Design: a private kw-only synchronous execution check travels out of band with only agent-loop `handle` calls. The server invokes it after request args, job toolset, and registered-tool validity, directly before preflight. It returns literal `True` only if a fresh underlying profile resolver still offers that same registered name for the current agent; errors/missing row deny with existing `tool_not_allowed`. The coordinator passes its `ToolProfileResolver` directly for this check, keeping `_profile_and_note_offer` and H661 turn-offer notes untouched. ContextVars for principal, origin, and job scope are inherited by the child task and remain independent restrictions.
- Non-goals: no provider schema/offer refresh between folds, taint or gated-status rewriting, in-flight cancellation, queued-approval replay/rewrite, job-toolset weakening, or SEC-B5 taint finalizer change. Direct/script `handle` and approved-task `execute` calls without the private hook retain existing behavior.
- Tests: red/green H672 no-fold revocation, resolver failure and missing row, await-window revocation after `tool_started`, preflight/intake never reached, principal/origin and job-scope inheritance, H661 offer note unchanged; focused ToolRPC/profile/fold regressions, Ruff, diff check.
- Proof: the old H672 baseline passed while showing a revoked shell handler running. The first red pass failed six of seven targeted cases before source changes. After the recheck, targeted tests passed, including a real coordinator wiring test that narrows `jarvis` to `echo`, blocks `time`, and observes the unchanged H661 offer marker inside the allowed child handler. A gated-tool regression checks that revocation before dispatch leaves preflight, approval intake, pending approval reporting, and handler untouched. The focused ten-file regression union passed 196 tests (`/workspace/scratch/profile-execution-recheck-focused.xml`).
- Limit: the model-visible tool offer still updates only at the existing run/fold boundary. The new recheck applies only to agent-loop calls wired through the coordinator or to runtimes explicitly given `execution_profile`; a standalone `AgentToolRuntime(tool_profile=...)` without that separate execution hook retains legacy behavior. Direct/script calls and in-flight actions are outside this dispatch boundary.
- Rollback: revert the three source changes, two test changes, and this plan as one local unit. Existing profile offer/fold behavior returns; no persisted data or task migration.

Coordinator checkpoint (2026-10-09): independent gpt-6-sol/high review found no
Critical/Important issue and independently passed the eight new regression cases.
The builder used the same model/effort; a read-only gpt-6-luna/medium inventory
reviewed 26 previously current target-file pins across 20 assessment rows and
mapped their moved citations. Only those pins were refreshed. All 41 preexisting
stale target pins, including H672's runtime and H661's coordinator pins, remain
unchanged; all assessment verdicts are preserved. H672's remaining now distinguishes
new-call admission from in-flight/direct/queued execution and persona/fold limits.

Full collection confirms 21,114 backend cases (+8); frontend 1,962/mobile 284/routes
554 remain unchanged. Ruff, diff and generated project/Hermes freshness gates pass.
A full-backend integration run followed this source checkpoint. No provider,
device, publication or deployment was performed.

Integration checkpoint (2026-10-09, source `a5642a1`): 21,114 backend cases yielded
21,076 passed, 37 skipped, one failure and zero errors in 266.299 seconds. The only
failure was the strict external-binding callsite inventory: the new coordinator
constructor argument moved 12 existing binding calls by one line. A separate run
reproduced that failure before repair. Only those 12 inventory line coordinates
were updated; names, paths, columns, binding behavior and the assertion are intact.
The H515 inventory-file evidence pin was already stale before this unit and remains
untouched. After repair, the complete binding module plus status/Hermes regressions
passed 136/136; the original failing node is included and passes. Ruff, exact backend
count and generated freshness gates pass. The full suite was not repeated after
this metadata-only correction; the recorded full result remains a failed checkpoint.
See [integration evidence](../project-profile-execution-integration-20261009.md).
