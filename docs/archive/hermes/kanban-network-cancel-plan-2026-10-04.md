# Kanban URL attachments and cancellation implementation plan

Goal: advance all 697 pinned Hermes capabilities with governed URL attachments
and immediate cancellation settlement. Generated 2026-10-04; base/head
44d3cd819f3864c1110ae116d55f777a059f9296. Previous goal turn: verified progress,
committed parallel workers with 23,312 backend passes,34 skips,1 existing xfail.
Local only: no push, merge, deployment, live worker activation or paid provider.

## URL attachment design

Reuse Hermes's filename derivation, 25 MiB attachment store and metadata/events.
Reuse Nerva PluginHTTPClient DNS-pinned egress and the strict URL-monitor pattern,
not the base client's allow-on-hook-error behavior. A default-off
llm.kanban_network_attachments flag makes the fourteenth tool offerable; enforced
kernel/queue mediation remains required. The existing validated owner/live-worker
tool submits an exact plugin.egress approval, with credential-free URL, board,
task, profile, session, optional owned run, filename and binary-identity framing.
The tool does not fetch until that approval executes. Each redirect proposes a
new separately approved hop (maximum five), never carries ambient credentials,
and never treats a queue ID as a worker PID or an approval as board ownership.

NetworkAttachmentAdapter(orch,*,home=None,resolver=None,transport_factory=None)
has synchronous submit(args), matches(task), guard(task), and async execute(task).
Its plugin identity is kanban-attachments. Guard consumes the real worker permit;
execute consumes a private one-use claim, verifies exact current queue/board/run
bindings and rechecks flag, e-stop, kernel, URL identity and owned run before dial,
after response, and before publication. Failed validation makes no request/blob.
Raw identity bytes stream under the donor cap and a 30-second deadline. Errors
never echo URL credentials, body, headers or arbitrary exception text.

Agent owns new kanban/network.py, kanban/runtime.py, kanban/tools.py and
tests/test_hermes_kanban_network.py. Root owns cached coordinator binding and
plugin.egress multiplexer composition, tool_profiles.py, settings_db.py,
plugin_gate.py, manifest/catalog guards and related snapshots/records.
Runtime adds network=lambda:None to register_kanban_tools; the existing sync
invoke validates scope and delegates attach_url to network().submit(args).
Other donor tools retain their current thread/context path.

## Cancellation design

Root owns kanban/dispatcher.py, autonomy/queue.py and
tests/test_hermes_kanban_parallel.py. Queue transitions gain an optional
expected_execution_sha256 predicate checked inside the existing write transaction,
alongside expected_status, so settlement cannot race a replacement execution.
When its actual model coroutine is cancelled, release only the owned board run
and settle only the same still-running authenticated queue execution as FAILED.
A missing, terminal, mutated or successor execution cannot be overwritten.
CancelledError still propagates, permits are revoked by the existing worker and
all TaskGroup cleanup is awaited. Ordinary kinds and crash/reaper behavior stay.

- [x] RED/GREEN: real signed queue URL proposal waits; approved pinned fetch
      stores exact bytes/metadata. Denied, direct, stale, revoked and oversized
      calls do not publish; DNS rebinding/private targets, credentials, redirects,
      cancellation and cap boundaries are covered without live sockets.
- [x] RED/GREEN: cancelled parallel workers have FAILED queue rows and released
      board claims immediately; a changed/terminal successor is not overwritten.
- [x] Root wires actual tool/profile/executor consumers, reusing their guards;
      verifies failure isolation and new egress domain routing.
- [ ] Run relevant authority/network/board/catalog integration after the batch,
      then one frozen full milestone, exact staged scan and local commit.

Rollback: revert these opt-in adapters/consumers as one unit; preserve queue,
board files, sessions and attachments. Full UI, workspace/project, watchers,
tenant controls, channel delivery, judges and live acceptance remain in scope.
Next action: delegate the bounded URL adapter after interfaces above are settled;
root first demonstrates the existing cancellation queue-state regression.

Progress update 2026-10-04: URL implementer gpt-6-sol/high handed off four owned
files; root completed queue CAS cancellation, consumers and critical review.
76 final board/network focused tests, 216 authority/queue regressions and
115 consumer tests passed. The 179-module integration selected 4,010 cases:
4,005 passed, one skipped, four failed due to the intentional new plugin's
static boot counts/snapshot. Reconciled 77 metadata/reality tests pass with
78 boot records, including the generated attachment plugin policy probe.
The snapshot generator added only plugin:kanban-attachments. No live claim.
Full backend milestone (23,379 collected cases) is the next action, followed
by exact-byte scan and local commit. Until it terminates, no frozen edits.
