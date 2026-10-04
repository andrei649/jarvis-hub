# Kanban CLI, chat and dashboard integration plan

Goal: continue all 697 Hermes capabilities, including H075 and H581, by reusing
the pinned CLI argument tree, command/state handlers and dashboard API. This
batch is not a redefinition of full parity. Workspace/Git effects, goal judging,
tenant isolation, notification delivery and complete dashboard/native consumers
remain required until their actual integrations are verified.

Generated: 2026-10-04. Base/head: 4d7f52382ab5c18e9be0a5c56306b7c15232f764.
Previous goal turn: progress; URL attachments and exact cancellation settlement
committed after 23,344 backend passes, 34 skips, one existing xfail, no drift.
Pinned source: 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e, MIT.
Local only: no push, merge, deployment, paid provider or real-worker activation.

## Architecture and shared contracts

Copy/adapt Hermes CLI parser and command/rendering helpers into the private
Kanban package; retain license and source mapping. Reuse the existing upstream
SQLite functions and current dispatcher, never a second board implementation.
Expose `agents.core.kanban.cli.execute_command(orch, argv, principal,
session_id=None, profile="owner")`, async, returning `{ok, exit_code, output,
reason?}`. It binds the real owner/session and board scope; argparse errors are
usage failures, unsupported effect bindings are failures, never successful prose.
`cli_parser.build_parser(parent_subparsers)` adds the full pinned kanban tree.
No process-global env, stdout redirection, monkeypatching or profile credentials.
Use context-local output sinks for copied print/rendering helpers.

Root exposes authenticated POST /api/kanban/command with `{argv: list[str]}`;
host `nerva kanban ...` uses HubClient, and owner `/kanban ...` uses the same
service. Limits: 128 argv entries, 8 KiB each, 64 KiB total; unknown fields fail.
No caller can provide trusted principal/profile/run/session provenance.

Copy/adapt Hermes dashboard API to `kanban/dashboard_api.py`, exporting router
without ambient activation. Its root-mounted HTTP wrapper at /api/kanban uses
admin_guard and a default-off board scope dependency. Every request copies the
real context into the synchronous handlers. Relative imports point only to this
repository; no optional-import auth fallback. Root owns authenticated WebSocket
events and mounts the module in web.py. Public channels/anonymous callers cannot
read owner state. Metadata CRUD and board events use donor algorithms. Dispatch
uses the current signed queue controller; process spawn/termination, arbitrary
filesystem/project/Git, auxiliary provider and channel effects require explicit
adapters and cannot fall back to the donor's raw execution paths.

Downloads validate stored file containment under the scoped board attachment
root before opening, uploads retain the donor cap, metadata authors are trusted
context identities, and workers cannot switch boards or edit successor runs.
Unknown/unbound adapters return explicit failure status; do not remove their
requirements or report full parity based on these failures.

## Ownership

- CLI implementer gpt-6-sol/high: new kanban/cli.py, cli_parser.py, copied CLI
  helpers under kanban/cli_upstream/, tests/test_hermes_kanban_cli.py only.
- API implementer gpt-6-sol/high: new kanban/dashboard_api.py, copied API helpers
  under kanban/dashboard_upstream/, tests/test_hermes_kanban_dashboard.py only.
- Root: routers/kanban.py, web.py mount, cli/nerva.py, commands.py registration,
  context/privileged seams if necessary, integration/auth/snapshot tests,
  generated schemas/reports and truthful HUD/mobile gaps. Single writer per file.
- Implementers must not delegate, stage, commit, run full suites or touch remotes.

## Verification and delivery

- [x] RED/GREEN parser argument fidelity and real durable command lifecycle:
  boards/cards/links/comments/attachments/reviews/runs; unknown arguments and
  delegated/stale/cross-board scopes fail without hidden effects.
- [x] RED/GREEN real dashboard requests: metadata lifecycle, attachments and
  containment, board separation, current run transitions and event streaming.
- [x] Root owner host/chat/HTTP consumers, disabled/guest/anonymous refusal,
  exact signed dispatch proposals; no donor process/provider fallback.
- [ ] Relevant integration after both handoffs, regenerate source-derived
  auth/readiness/schema artifacts, reconcile only reviewed evidence changes.
- [ ] One frozen full backend/frontend milestone as applicable, exact staged
  secret scan and local commit, retaining all remaining requirements.

Rollback: revert this coherent surface adapter batch, preserving queues,
board databases, sessions, files and the existing metadata/network/worker tools.
Progress (local, uncommitted): both implementers handed off their scoped ports.
Root connected CLI/chat/HTTP and guarded WebSocket, reused the shared owner board
selector, rejected truncation and identity injection, fixed title validation
before status writes and rechecked direct transitions under the donor writer lock.
Explicit owner chat dispatch has a separate command-context entry into the same
signed queue; ordinary inbound model-tool requests still refuse. Root-focused
run: 201 passed; route gates initially flagged only the 47 intentional additions
(46 donor HTTP pairs plus command), all verified admin-guarded before snapshot
generation. OpenAPI types were regenerated with the already cached 7.13.0 tool;
TypeScript compilation passed. Relevant Kanban integration: 175 passed. Two
semantically identical copied diagnostics engines were consolidated into one
shared donor module. The first security scan flagged diagnostic exception
isolation and SQL interpolation; table names are now explicitly allowlisted and
only generated placeholders interpolate, with bound values and localized scan
explanations. The security baseline is unchanged. New diagnostics use donor
defaults; unbound effects remain failures.
This is partial H075/H581 functionality, not full Kanban or all-697 completion.

Next action: finish generated OpenAPI/auth/readiness and focused integration,
review only affected Hermes evidence, then one frozen full milestone and local
exact-stage-scanned commit. No remote operations are authorized.
