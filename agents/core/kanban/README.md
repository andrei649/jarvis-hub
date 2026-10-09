# Pinned Hermes Kanban integration

Source: NousResearch/hermes-agent at
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. The copied SQLite, graph, run,
review, attachment and notification-storage algorithms retain the MIT notice
in `upstream/LICENSE`; the copied tools and schemas carry that notice too.

`llm.kanban` is a boolean setting, default false. With the agent tool loop
enabled, the owner on the operator surface can edit board metadata through the
existing chat/ToolRPC surface. The fourteen pinned schemas are registered;
URL attachments require the separate default-off
`llm.kanban_network_attachments` flag. The tool proposes a signed network
approval; it does not fetch in the caller's turn. Each redirect requires a new
approval. Approved requests use DNS-pinned public HTTP(S), credential-free URLs,
identity bytes, the donor's 25 MiB cap and a 30-second deadline. Revoked settings,
kernel denial or changed worker ownership prevent publication.
The database lives under Nerva's private `data_path('kanban')`, never `~/.hermes`.
The copied CLI argument tree is available through `nerva kanban ...` and the
typed owner `/kanban ...` command. Both share the scoped state service with the
admin-only `/api/kanban` board/file APIs. The event WebSocket authenticates host,
origin and current admin authority; credentials are never accepted in its URL.
Owner board selection persists across CLI/API requests. Explicit owner chat
dispatch proposes work through the same signed queue; inbound model tools keep
their existing operator restriction. Unsupported effects return failures.
Handlers use the real caller identity and session, not model-provided identity
or ambient `HERMES_*` values. A worker needs a live scoped task/run; it cannot
switch boards, change another task's dependencies or borrow a successor's run.
Ordinary delegates and late inherited scopes cannot recreate owner authority.

The preserved state API includes boards, durable task/review lifecycle,
dependencies, atomic claims, stale-run refusal, comments/events, inline
attachments and notification records. Metadata tools execute off the event
loop, and results are fenced as untrusted board content by the existing loop.

`llm.kanban_dispatch` separately enables durable worker intake, default false.
The existing coordinator and admin-only `POST /api/autonomy/kanban/dispatch`
share one dispatcher. Each proposal carries the exact worker prompt in the
existing signed approval queue. Approval never claims the board until actual
execution; changed task input/dependencies refuse the old approval. Workers
use isolated sessions, task-owned model pins, exact run ownership, heartbeat,
timeout/cancellation accounting and review reservation. Total and per-agent
capacity includes pending proposals on every board. The default watcher intakes
the default board; explicit requests can target another board.
The enabled coordinator runs approved board turns concurrently through the same
signed queue claims and execution permits. Total and per-agent budgets include
durable running queue rows; excess approvals wait. A strict host worker lock
prevents overlapping dispatcher batches. Ordinary kinds retain serial execution.
A zero total or per-agent budget withholds board execution and new proposals
rather than substituting a larger default. Safe mode disables both
board, dispatch and network opt-ins and clamps these budgets to the stricter
shipped value. Cancelling a live board worker releases its owned board claim
and atomically settles the same running queue execution as failed, so new work
does not wait for crash recovery. A successor or externally settled queue row
is preserved; unavailable storage retains the existing crash-reaper fallback.

This is an integration in progress. Full multi-board/event watchers,
FileScope workspaces/projects, goal judging,
channel delivery and the board/dashboard/native
consumers still need their Nerva bindings. Unsupported effects return errors;
the private upstream launcher/Git implementations are not activated. Dead
launcher bodies after explicit unresolved seams were removed; the pinned
reference remains the source for the remaining adapters.

Restart recovery reconnects an interrupted proposal-to-queue handoff by its
durable submission identity. A terminal queue attempt releases only its own
still-current run on the next intake. Existing queue reaping handles stranded
executions; no queue ID is represented as a worker PID. Synthetic tests verify
this adaptation; no real provider, live worker or service was activated.

Static review: dynamic SQL uses parameter-bound values, fixed placeholder
lists and allowlisted identifiers. Internal graph/table/workspace identifier
guards reject injected names. Narrow Bandit annotations document these
expressions, read-only bounded process probes and best-effort bookkeeping;
no global scan exclusion or baseline relaxation was introduced.

Rollback: revert the optional package, setting, ToolRPC registration and new
profile/guidance branches together. Existing Nerva queues, sessions and user
data are not migrated or deleted by this port.
