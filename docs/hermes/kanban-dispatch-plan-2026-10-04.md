# Governed Kanban workers implementation plan

Goal: advance the complete 697-capability Hermes parity objective with real
Kanban worker execution. Generated 2026-10-04; base/head 78d0de874309e6f17939eeb0fd0fae7e1c3c77bd.
Previous goal turn: progress, committed state/tools and Inspector clients with
23,278 selected backend cases (23,243 passes,34 skips,1 existing xfail).
Local only: no push, merge, deploy, paid provider or real worker activation.

## Design and global constraints

Reuse pinned Hermes 59b2aeef6c7a DB claims, dependency recomputation,
priority ordering, review lanes, run IDs, heartbeat, failure accounting and
worker-context builder. Nerva's durable kernel-mediated queue replaces CLI
process creation/PID ownership. Metadata edits do not authorize execution.
A board task is proposed with its exact input/context digest; approval stays
on the existing queue. Execution verifies the durable queue row and current
board input, then claims the exact board run before calling the agent.
Unchanged pending proposals are idempotent. Changes require a new proposal;
a changed or replaced board task/run cannot borrow an old approval.

The classified kind is kanban.worker, mediated through AutonomyWorker's
existing signed intake and execution permits. Default-off llm.kanban_dispatch
is separate from llm.kanban; both and the existing tool-loop flag must be on.
Use existing admin-guarded autonomy routes for an explicit dispatch request,
and the existing coordinator tick for enabled background intake. The kernel
and queue enforce their current policy; no raw-enqueue fallback or fabricated
human principal, PID, Task ID, receipt or executor permit.

Workers have a unique context-local session and non-owner principal. Their
Kanban authority is only their exact live task/run. Ordinary delegates retain
the existing authority-clearing behavior. Provider errors, timeout and
cancellation are failure evidence; an unfinished worker is not completed just
because it returned prose. Goal tasks do not bypass the unbound judge.

Workspace/project, network attachment, channel and full board UI adapters
remain in the full objective, not excluded or treated as delivered here.

## Review focus

- Editing task input while approval waits refuses old execution before a model call.
- Concurrent ticks/proposals cannot create duplicate execution of one board task.
- A worker sees its isolated session and live board tools, without an inherited owner.
- Timeout/cancel/provider failure cannot mutate a successor run or count as success.
- A stopped, disabled or mismatched kernel/queue must refuse intake and execution.

### Task 1: Scoped Nerva worker turn

Files: agents/core/kanban/worker_runner.py;
tests/test_hermes_kanban_worker_runner.py. Single writer: one gpt-6-sol/high
implementer, no children, stage, commit or unrelated changes.

Interface: async run_worker_turn(orch, *, prompt: str, agent_id: str,
session_id: str) -> str; WorkerTurnRefused(RuntimeError). Requires the trusted
KanbanContext already bound by the approved controller, with exact profile,
task_id and run_id. Verify current board ownership before and after waiting
for the session lease. No fallback to jarvis for an unknown configured agent.
Bind the real Orchestrator context-local session and non-shared state, provider
session_scope, a non-owner Principal(channel='internal'), and generated action
origin. Clear parent selection/generation overrides and approval context.
Call process_detailed on the exact configured agent with channel='internal';
empty/error/refused/degraded results raise. Restore all tokens after success,
failure or cancellation. Do not use make_subagent_runner: it deliberately
clears Kanban authority and does not bind the board worker's session.

- [ ] Write failing regressions for actual Orchestrator session/principal identity,
      two overlapping sessions, unknown agent, closed/successor board scope,
      provider error, empty output, cancellation and parent token restoration.
- [ ] Run RED before implementation, then implement and run GREEN with existing
      session/steering/provider isolation regressions. Use synthetic data only.
- [ ] Report exact paths, commands, results, concerns and deferred requirements in
      /tmp/nerva-kanban-dispatch-20261004/task-1-report.md. Root integrates/reviews.

### Task 2: Durable kernel queue bridge and real consumer

Root owns agents/core/kanban/dispatcher.py and dispatch_store.py, kernel
registry/snapshots and tests/test_hermes_kanban_dispatcher.py. After Task 1's
handoff, the same gpt-6-sol/high implementer owns the localized coordinator
tick/executor registration, settings, admin autonomy entry point and
tests/test_hermes_kanban_dispatch_wiring.py. Root reviews and integrates.
Use the actual worker govern_enqueue and signed TaskQueue, not raw enqueue.
Durable submission records bind task/context digest to accepted queue row and
current run. Recover a crash between enqueue/binding by the unique submission
identity in the actual persisted queue, without inventing an approval. Pending
and live task capacity uses durable handles; never interpret a queue ID as PID.

- [ ] RED: signed intake DENY/QUEUE/GRANT and off/mismatched runtime; unchanged
      proposal deduplication/restart; current input and dependency edits; exact
      claim race; priority/review/cap behavior; real worker tick with fake model;
      output without terminal board action; timeout/cancel/successor protection.
- [ ] Implement the durable bridge, approved handler and real existing consumers;
      run the focused tests after each behavioral step and root review Task 1.
- [ ] Update route/action/parity snapshots only for intended new surfaces; preserve
      existing guards. Run affected integration once, then a frozen full milestone.
- [ ] Record truthful partial H075/H581/H358/H388 evidence and local rollback;
      commit only after verification. All 697 capabilities remain the goal.

Rollback: revert optional dispatcher/store/runner, flags and localized consumers
as one local unit. Preserve private board data and existing queues/sessions.

Full-suite integration findings (2026-10-04, before corrective edits): the
frozen 23,322-case run has nine failures, no source drift. Add the classified
worker to capability_manifests.py with an honest no-global-undo contract; clamp
its opt-in and capacity settings through safe_mode.py. Regenerate only the
intended OpenAPI/API-sweep additions and list the pending board caller in the
HUD parity punch list. Re-run these nine failures and their owning suites before
the final frozen verification. Actual parallel board execution remains open:
the current AutonomyWorker tick executes its queue rows serially.
