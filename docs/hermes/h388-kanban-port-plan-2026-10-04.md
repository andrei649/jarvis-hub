# Pinned Hermes Kanban port and inspector clients

Generated: 2026-10-04. Goal: all697 functional Hermes parity, including the
previously excluded board/dispatcher/plugin rows. Base/head: 38ca4ad4.
Previous goal turn: progress; producer integration committed with a frozen
23,247-case backend result (23,212 passes,34 ordinary skips,1 existing xfail).
Local only; no publication, deployment, paid provider or real worker activation.

Port the pinned 59b2aeef6c7a implementation rather than building an unrelated
board. Upstream has14 registered kanban tools and ~12,000 lines across its
database, schemas, workspace, notification and dispatch modules. Keep its
transaction/CAS, run identity, dependency, review, attachment and retry semantics
and MIT notice. Imported functions alone do not establish runtime parity.

## Selected design and authority

Private package agents/core/kanban/upstream retains original module basenames;
rewrite imports only into this namespace or explicit Nerva compatibility seams.
No global sys.modules aliases, no import of a live Hermes checkout and no new
dependencies. Root/home/profile/worker identity come from a scoped runtime
context, never HERMES_* environment variables, tool args or ~/.hermes defaults.

agents/core/kanban/context.py supplies frozen KanbanContext(home:Path,
profile:str, board:str='default', task_id:str|None=None, run_id:int|None=None,
session_id:str|None=None, can_mutate:bool=False, delegated:bool=False),
kanban_scope(context), current_context() and require_mutation(). A bound scope
has a closed lifetime; missing/closed/delegated/non-mutating scopes refuse writes.
Board selection still validates upstream slugs. No tool-supplied root/identity.

The Nerva tool/runtime adapter must retain the actual ToolProfileResolver and
TaskQueue/kernel gates. Card dispatch must be an approved durable task before
starting an existing Nerva agent runner; metadata transitions require owner or
the exact owned run. Workspaces resolve through FileScope. External upstream
CLI workers, Git/workspace cleanup, network attachments and goal judges must not
be silently activated by the port. Preserve these APIs with explicit unresolved
Nerva seams where required; do not call the whole dispatcher equivalent yet.

H227 clients render the backend's existing resolved/model/route/route_error
fields. A fixed empty-turn preview must be labeled as such; unresolved, legacy
and withheld states stay distinct. No history/schema/cache byte-equality claim.

## Ownership and execution

1. One gpt-6-sol/high implementer owns only kanban/upstream, kanban/context.py,
   kanban/__init__.py and new state-port tests. Copy upstream modules and direct
   dependencies; use exact fixed compatibility APIs, meaningful scoped RED/GREEN
   and representative adapted upstream behavior tests. No children/commit/stage.
2. A second gpt-6-sol/high implementer owns CLI render_inspector, inspector.tsx,
   inspector.test.tsx and one new H227 CLI test module. No backend edits or new
   routes. RED/GREEN for resolved/unresolved/legacy/withheld client disclosure.
3. Root owns tool adapter/runtime, shared coordinator/profile/kernel integration,
   critical review and truthful records. Settle identity/mutation/dispatch seams
   before wiring them; no fake environment bridge or ungated dispatcher fallback.
4. Focused regressions per meaningful step. Review copied imports and entry points,
   then run affected integration suites. Freeze one serial whole-suite milestone
   for an integrated batch; no automatic whole-suite repeat per small edit.

## Acceptance and remaining objective

Verify durable task/review lifecycle, graph cycle rejection and dependencies,
concurrent claims/CAS, stale-run refusal, attachments, board separation and
closed/delegated context refusal with synthetic temporary data. Runtime acceptance
additionally requires actual ToolRPC offers/requests, task dispatch/worker
terminators, model/skills/workspace binding and channel/dashboard consumers.
Notifications, websocket events, tenant isolation, worker restart/reaping and
all previously excluded board/plugin scope remain required, not substituted by
the library port. No row is marked equivalent based on copied lines alone.

Likely paths: new kanban package/state tests, autonomy_coordinator.py,
agent_runtime.py, operating_guidance.py, tool_profiles.py, task executor/wiring;
the named CLI/frontend inspector paths; Hermes records and parity notes.
Rollback: revert the coherent optional package/adapter/client batch; retain
existing queues, settings, sessions and unrelated source. No migrations of user
data or deletion of existing state during development.

Next action: implement the scoped upstream state port and inspector disclosure
in parallel; root integrates actual tool/dispatch authority as evidence permits.

## Current integration milestone

Generated: 2026-10-04. Source base/head remains 38ca4ad4; local changes only.
The previous goal turn yielded concrete guard findings; this turn implements
the private state/tool port and real coordinator registration. Sol High state
and client implementers have stopped editing; root owns integration/review.

Delivered locally: durable scoped state and thirteen local tool operations;
the fourteenth pinned schema (network attachments) is registered but withheld
and refused until its approved transport exists. The matching assigned worker
reaches actual model guidance. Delegate/closed owner fallback and sibling
dependency mutation regressions are fixed. The actual settings registry now
contains a default-off boolean llm.kanban. No workers are launched by this port.

The full frontend milestone passes 1,892/1,892; TypeScript passes. Focused state,
ToolRPC, settings, Inspector, profile, steering and binding tests pass after
fixing the port's async mismatch, an empty-project refusal, identifier guards
and stale registry/binding assertions. Whole Ruff and baseline-aware Bandit
pass; SQL values remain bound and identifier guards have behavioral tests.
Dead upstream launcher/Git bodies were removed after explicit unresolved
seams. Narrow static annotations do not modify the global scan baseline.

The initial general run was deliberately cancelled after the focused ledger
guard reported stale image/code evidence pins. It terminated with exit 2,
2,363 passing cases and no source drift; it is not a full-suite success.
The complete coordinator/binding diff was re-read for H515/H595/H660: only
Kanban registration, delegated-board authority clearing and exact callsite
coordinates change. Image/code bodies remain intact. Their 668-case regression
union passes with seven existing environment skips; the ledger guard passes.

The reconciled run selected all 23,278 cases and found three integration
failures: the exact coordinator registry expectation omitted the fourteen
board tools, a now-unused copied configuration helper duplicated the central
environment convention, and four raw environment reads exceeded the existing
ratchet. Corrected the local adapter: pinned TTL/grace/cooldown defaults remain,
task timeout context ignores ambient TERMINAL_TIMEOUT, executable lookup uses
env_config, and the registry test retains its full non-board assertion while
checking the fourteen registered board names. Existing guards were not relaxed.
The focused runtime/environment/state/tools union, Ruff and Bandit pass.

Final frozen backend run completed: 23,278 selected, 23,243 passed, 34 ordinary
skips and one existing expected failure; zero failures/errors or source drift.
The frontend milestone passes all 1,892 cases and TypeScript checking. Local
results, failed/cancelled predecessor runs and source hashes are preserved in
docs/hermes/evidence/kanban-port-local-2026-10-04.json.
Next action: adapt the pinned dispatcher and its behavioral tests to approved
durable Nerva queue tasks and the existing runner, preserving exact task/run
ownership. Workspace/judge/network/channel and UI adapters remain separate
unresolved integration requirements.

Five primary Hermes reviews are partial: H075, H581, H358, H388 and H227. Shared
CLI/runtime file hashes also make older unrelated reviews stale; those stay
needs_review pending claim-by-claim collateral review rather than hash-only
restamping. All 697 capabilities and the remaining dispatcher/consumer/plugin
work remain the objective. Mobile/HUD gaps are recorded in their parity files.
