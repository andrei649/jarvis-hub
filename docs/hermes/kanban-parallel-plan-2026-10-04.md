# Parallel approved Kanban workers implementation plan

Goal: advance full pinned-Hermes parity with simultaneous approved board workers.
Generated 2026-10-04; base/head e8d4992b90228c9ac1b55b5f790345eb6240a870.
Previous goal turn: no implementation progress; confirmed committed state and next gap.
Local only: no push, merge, deployment or real provider activation.

Reuse the existing AutonomyWorker execution path, including signed queue claims,
execution permits, tier/kill-switch checks, outcome accounting and board cleanup.
Extract its existing serial row loop without changing those decisions. `tick`
accepts optional `parallel_kind`, `parallel_limit`, `parallel_agent_limit`; ordinary
callers retain serial behavior. A selected parallel batch counts existing running
rows, leaves excess approvals waiting and executes each selected row in a child
async task. Ordinary kinds remain serial. Housekeeping runs once per tick.

The dispatcher exposes `approved_tick(max_tier=None)` under a distinct strict
host worker flock and a process-local non-waiting lock. It delegates to the actual
worker tick with Kanban-only concurrency and current bounded settings, including
zero. The coordinator uses this only under the existing three opt-ins, and still
uses normal tick when disabled or settings are unavailable. No new route or flag.

Root owns worker.py and tests/test_hermes_kanban_parallel.py. One Sol High agent
owns dispatcher.py, autonomy_coordinator.py and dispatch_wiring tests. Interfaces
above are settled; neither writer edits the other's files. No child agents.

- [x] RED: two different agents reach a barrier together through the real signed
      queue; serial execution fails. Pins, sessions and run IDs remain distinct.
- [x] GREEN: reuse exact approved row loop; verify limits, zero, existing-running
      capacity, duplicate ticks, night tier, halt, isolated failures and cancellation.
- [x] Agent: wire the real coordinator caller, strict nonblocking host lock,
      fail-safe settings/runtime behavior, default-off compatibility and tests.
- [x] Integrate, run affected queue/authority/session suites, lint and status gates.
      Record the actual evidence; full suites run at a subsequent frozen milestone.

Non-goals for this unit: new board UI, workspace/network/goal-judge adapters or
claiming full Hermes equivalence. These remain in the full 697-capability goal.
Rollback: revert this optional scheduling unit; retain all board/queue/session data.
Next action: one frozen complete backend milestone, then exact staged scan and local commit.

Focused final union:67 passed. Final affected integration: 3798 selected, 3797 passed, 1 skip, zero failures/errors.
Serial-scheduling mutant is detected. Whole Ruff and unchanged-baseline Bandit pass.
Ordinary queue work is completed serially before the parallel board batch.
Owned board cancellation cleanup retains existing queue crash/reaper bookkeeping.
All 697 capabilities remain in scope; this unit grants no new equivalent row.

Complete milestone follow-up:23,347 selected;23,311 passed,34 ordinary skips,
one existing xfail and one broken-store fault-injection failure, zero source drift.
The injector matched the former tick frame instead of the extracted shared loop.
Its caller is corrected without changing production authority behavior; all77
cloud/parallel cases pass. A fresh frozen full run will verify this final candidate.
