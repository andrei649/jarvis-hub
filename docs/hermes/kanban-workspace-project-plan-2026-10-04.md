# Kanban workspace and project integration implementation plan

> For agentic workers: execute the two independent module tasks with
> subagent-driven-development; root owns all shared integration and reviews.

**Goal:** Implement and connect pinned Hermes scratch/dir/worktree and project
lifecycle in Nerva, continuing all 697 capabilities without narrowing the goal.
**Architecture:** Reuse the pinned donor algorithms and SQLite store behind
Nerva's live scope and existing signed queue. A canonical workspace specification
is signed before approval and checked at actual execution; file and terminal
roots/cwd are per worker, with closed inherited lifetimes.
**Tech stack:** Existing Python 3.12, SQLite WAL helpers, local Git CLI, FastAPI,
ContextVars, FileScope and action-kernel/queue permits; no dependency changes.
**Base:** a7ffad6676cfb28e7ac374d495b4a5889e5f4646.
**Head inspected:** a7ffad6676cfb28e7ac374d495b4a5889e5f4646 (dirty local batch).
**Generated:** 2026-10-04T20:15:09Z.
**Changed paths:** scoped Kanban project/workspace modules and their tests; shared
FileTools, orchestrator, terminal intake, CLI/chat/router bindings; generated API
types/snapshots/manual and truthful local status/assessment projections.
**Next action:** freeze this partial integration milestone, verify the full backend
serially, inspect exact drift and create a scanned local checkpoint; then implement
the signed child file/terminal approval and resume flow below.
**Spec:** Full pinned Hermes 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e
workspace and projects_db behavior; original H075/H581 scope stays required.

## Constraints

Local only. No push/merge/deployment, paid providers, real worker activation,
shared cwd/env/settings mutation, shell commands, network Git or force removal.
At most two gpt-6-sol/high implementers, no child delegation or overlapping writes.
Root performs shared/security/integration reviews; helper presence is not parity.

## Settled interfaces and ownership


Workspace implementer owns new `agents/core/kanban/workspaces.py` and
`tests/test_hermes_kanban_workspaces.py` only. Reuse the pinned workspace resolution,
branch/linked-worktree and safe cleanup algorithms; no writes to upstream or shared
host files. Public interface: `plan_workspace(task, *, board=None, project_root=None)`
returns a JSON-safe immutable specification without creating directories/worktrees;
`materialize_workspace(spec, *, still_current)` creates/resolves the exact proposed
workspace only after the root-supplied live execution callback passes;
`cleanup_workspace(conn, task_id, *, expected_run_id, still_current)` preserves user
paths, active children, attached workspace artifacts and dirty/unpushed worktrees.
Managed scratch authority is exactly this board/task path; dir/worktree anchors and
Git metadata must remain inside the owner's current configured FileScope roots.
Every filesystem/Git mutation rechecks the root callback and live containment.
No os.chdir, environment mutation, shell, network Git operations or force removal.
Subprocesses use explicit cwd/argv, bounded timeout/output, no Git hooks/fsmonitor.

Project implementer owns new `upstream/projects_db.py`, `projects.py` and
`tests/test_hermes_kanban_projects.py` only. Copy the pinned 490-line project store,
retaining provenance/license and adapting SQLite imports to the existing private
WAL/transaction helpers. Require the live Nerva context, an exact managed projects.db
path, owner-only writes (no delegated/task/run authority), and configured FileScope
for project/folder/discovery paths. Preserve all CRUD, folder/primary/active/archive,
path lookup, branch naming and discovery-policy semantics. No filesystem repo scans,
credential reads or process launch. `projects.resolve_project(ref)` returns
(id, name, primary_path) from the actual durable store, refusing unknown/archived or
revoked paths; `projects.list_projects()` returns the donor dashboard projection.

Root owns all existing shared files: signed workspace snapshot persistence and CAS,
canonical board/project metadata and proposals, execution-time revalidation, actual
per-worker file/terminal cwd scopes with closed inherited lifetimes, lifecycle
settlement, owner API/CLI/typed consumers and security/integration tests. Workspace
bookkeeping may not manufacture an approval or borrow the parent's tool grant.
The root must connect project CRUD to reachable authenticated consumers; helper
presence alone does not finish this unit or establish parity.


## Root integration and verification

### Execution binding implementation sequence

1. Extend dispatch snapshots with canonical board/project metadata and the pure
   workspace specification. Persist the exact JSON specification and bind it in
   the mediated queue payload; older submissions without it must not execute.
2. Verify proposal drift before claiming. During execution require the consumed
   exact queue permit, current dispatch record and exact live board run. Recheck
   owner roots and board/project anchors at every workspace/file effect.
3. Materialize only inside the claimed task/run scope. Bind the actual registered
   file tools to that workspace for the runner's lifetime without shared cwd/env.
   Runtime bookkeeping does not change the signed requested path. Expire inherited
   bindings before settlement; cleanup remains separately verified and conservative.
4. Independently reuse the donor's complete `project` CLI parser/handlers in new
   `cli_upstream/projects_commands.py` and `projects_cli.py`; its implementer owns
   only those new files and `tests/test_hermes_projects_cli.py`. Root mounts the
   actual CLI/typed consumers and reviews board-link behavior. No broad suites,
   external writes, live providers or child delegation during implementation.

- [ ] RED/GREEN actual temporary scratch/dir/worktree materialization and cleanup;
  preserve dirty/unpushed/user paths, active children and attached artifacts.
- [ ] RED/GREEN project/folder/primary/active/archive/discovery-policy durable CRUD,
  scoped home separation, revoked roots, symlink escapes and expired owner scopes.
- [ ] Bind board default_workdir/project anchors and the complete canonical
  workspace specification in signed proposals and current-execution checks.
- [ ] Connect actual worker cwd and file scope without global mutation; reject
  stale/cancelled/successor or inherited closed authority at effects.
- [ ] Connect project CRUD and linkage through authenticated real consumers;
  preserve donor argument/data fidelity and explicit remaining missing effects.
- [ ] Root review both ports and run focused integration after handoffs. Then
  regenerate only affected artifacts/reports, run serial frozen full suites as
  applicable, exact staged scan and local commit. No broad suites mid-implementation.

## Review focus

### Review corrections, before the next frozen milestone

1. Reproduce pre-existing scratch deletion and terminal-but-still-bound cleanup.
   Record ownership only when this adapter creates a scratch directory, outside
   the worker-visible directory, with its canonical home/board/task/path and
   directory identity. Reuse does not acquire ownership. Cleanup must preserve
   missing/invalid ownership, replaced directories and any live workspace binding.
   Existing owned scratch can resume and be reclaimed after its runner closes.
   Retire the ownership record before directory removal to prevent stale records
   from authorizing a replacement after a crash/inode reuse. Defer removal if that
   record cannot be retired. Report completed worktree removal accurately even
   when subsequent branch deletion is refused.
2. Reproduce reads through captured SQLite cursors after project scope expiry,
   including raw connection/cursor entry points. Bind each cursor's execution,
   fetch and iteration to the connection lifetime; preserve closing/rollback and
   donor row/transaction behavior. This is a lifetime boundary, not isolation from
   arbitrary malicious Python that can import SQLite independently.
3. Reproduce archive of a bound project preventing ordinary board task creation.
   Preserve donor archive/restore and archived metadata editing semantics. Make
   board/project linkage transactional or recoverable on failure, without silently
   falling back to a different approved project/workspace. Verify failures and
   restoration through the real CLI/API adapters, then retest shared consumers.

Root owns workspace correction and shared hosts; one Sol/high implementer may own
only projects_db cursor correction/tests and another only project command lifecycle
correction/tests. No overlapping edits, full-suite runs or child delegation.

Approval-to-execution board/project/root drift; two simultaneous workers with
independent cwd; missing/expired callbacks; foreign task/run/path/board identity;
cleanup races, active children/artifacts and dirty/unpushed worktree preservation;
no false success for unbound process/provider/notification/native effects.

Remaining original scope includes goal mode, gateway multi-board subscriptions,
tenants, process controls, auxiliary providers, pinned skills/swarm, channels and
artifact delivery, transfers/deletion, full HUD/Triage/native consumers, all other
capabilities and full H277/live acceptance audit. Nothing is replaced by this unit.

## Next integration unit: approved worker file mutations (not implemented)

Source trace confirms that enforced queue mediation currently refuses the exact
`toolrpc.file_write`/`toolrpc.file_delete` kinds: only `toolrpc.terminal_run` has
an exact physical-kind mapping. The parent Kanban dispatcher requires enforce
mode, so current worker file mutation intake fails; it does not have a signed
child approval. Off-mode/global tool replay lacks workspace provenance and must
not become the worker's fallback.
Until this integration exists, reject terminal intake from a task-bound or expired
Kanban scope before queue creation. Owner terminal usage outside a worker remains
available. Test both mediation modes and preserve the separate signed child goal;
the refusal is an explicit missing effect, not terminal parity.

1. Classify the exact server-owned file child kinds through the existing physical
   `file.write` contract, with signed intake, consumed child permit and no wildcard.
2. Bind a server-derived immutable workspace intent and durable board pending-child
   record before approval. Reconcile enqueue/park races and restart recovery. Park
   the parent in typed approval-wait state, retaining its workspace; blocked tasks
   already refuse this adapter's terminal cleanup.
3. Establish the child-specific file scope before ToolRPC rechecks preflight and
   classification. Require its own permit, exact signed payload, durable pending
   link, original run/workspace identity and live project/board/root checks. Never
   reuse the parent queue grant or fall back to the owner's ambient roots.
4. Reconcile actual effect success, rejection and expiry; queue DONE alone is not
   effect success. Resume through a fresh governed worker proposal, preserving the
   result/audit, rather than manufacturing a worker approval.

RED/GREEN acceptance must enqueue from a real scoped worker, approve through the
real queue and prove a relative write reaches only that workspace. Cover replay,
stale/replaced roots, project/board/run drift, rejection, expiry and restart/resume.
Terminal cwd, parent cleanup, complete donor HUD and all other original capabilities
remain required after this unit; none are counted complete by the current adapters.

## Frozen full-backend round1 correction plan

Authoritative terminal result (2026-10-04T20:46:48Z):23521 cases,23480 pass,6 failures,35 skips/xfail, zero frozen drift. Full goal remains active. The six failures reduce to three reproducible compatibility defects plus one presently non-reproduced timing failure:
- New complete project parser eagerly imports FileScope and thereby optional httpx, breaking existing python -S help/completion. Make only runtime dependency imports lazy in projects_commands.py; preserve actual project commands and existing stdlib regressions. Sol/high specialist owns this file and scoped project CLI tests.
- H218 setting fixture has a pre-workspace build_turn signature. Accept and assert the new optional scope argument (None for this owner test); actual workspace scope behavior remains covered by workspace integration tests. Do not remove production workspace binding or swallow errors. Root owns this test.
- Fourteen existing external binding callsites moved by exactly eight lines after the explicit terminal intake guard. Refresh only their exact reviewed location inventory in orchestrator_bindings.py; preserve attribute, file, column and exact inventory checking. Root owns this module.
- H487 off/tool execution budget0.25s failed once in full run, then all eight actual human-wait cases passed in the isolated reproduction. Keep the production deadline and test budget unchanged; investigate/re-run scoped behavior serially and require the next frozen full result before checkpoint. A scoped pass is not proof of full-suite stability.

RED evidence: /tmp/nerva-workspace-project-full-failures-repro-20261004.xml (5 reproducible failures,8 human-wait passes). Green/dependent evidence, current-input H277 campaign and next serial frozen milestone will be recorded after actual execution. No push/merge/deploy.

## Reachable HUD and board metadata integration plan

Generated: 2026-10-04T21:07:42Z; base/head a7ffad66, local dirty batch. Original697/H277 scope remains active. Root owns dashboard_api.py, a new board metadata API regression file, ProjectsMode mount in frontend/src/gap.tsx and a focused host test; Sol/high owns only new Kanban frontend module/tests.

RED/GREEN steps: (1) real owner API creates/updates project-linked boards and derives scratch/dir/worktree from validated effective workdir; project/default-workdir inheritance reaches actual task creation. Unknown/archived projects, revoked/outside/symlink paths must refuse before metadata writes; explicit clear and unchanged fields remain distinct, owner scope/default-off auth retained. Reuse existing project resolver and bounded no-hook Git inspection, no workspace materialization. (2) mount full Kanban view in ProjectsMode while preserving Rooms/Missions/Sessions/Activity; scoped UI host regression proves actual mount. (3) root review stale async mutation replies across board changes, then frontend integration/typecheck/build. Unsupported profile/transfer/native/goal controls remain required and cannot imply success.

Rollback unit: only these localized diffs/new module/test files, preserving prior work. Dependencies: existing durable project store, FileScope, canonical signed workspace proposals and host settings gates. Next full suite runs only when this coherent batch settles; prior full-run timing failure still requires final green evidence. No push/merge/deploy.
