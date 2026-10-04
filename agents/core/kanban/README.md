# Pinned Hermes Kanban integration

Source: NousResearch/hermes-agent at
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. The copied SQLite, graph, run,
review, attachment and notification-storage algorithms retain the MIT notice
in `upstream/LICENSE`; the copied tools and schemas carry that notice too.

`llm.kanban` is a boolean setting, default false. With the agent tool loop
enabled, the owner on the operator surface can edit board metadata through the
existing chat/ToolRPC surface. The fourteen pinned schemas are registered;
network attachments are withheld until an approved network adapter is bound.
The database lives under Nerva's private `data_path('kanban')`, never `~/.hermes`.
Handlers use the real caller identity and session, not model-provided identity
or ambient `HERMES_*` values. A worker needs a live scoped task/run; it cannot
switch boards, change another task's dependencies or borrow a successor's run.
Ordinary delegates and late inherited scopes cannot recreate owner authority.

The preserved state API includes boards, durable task/review lifecycle,
dependencies, atomic claims, stale-run refusal, comments/events, inline
attachments and notification records. Metadata tools execute off the event
loop, and results are fenced as untrusted board content by the existing loop.

This is an integration in progress. Approved TaskQueue/kernel dispatch,
watchers, workers/reaping, FileScope workspaces/projects, goal judging,
network attachment transport, channel delivery and the board/dashboard/native
consumers still need their Nerva bindings. Unsupported effects return errors;
the private upstream launcher/Git implementations are not activated. Dead
launcher bodies after explicit unresolved seams were removed; the pinned
reference remains the source for the remaining adapters.

Static review: dynamic SQL uses parameter-bound values, fixed placeholder
lists and allowlisted identifiers. Internal graph/table/workspace identifier
guards reject injected names. Narrow Bandit annotations document these
expressions, read-only bounded process probes and best-effort bookkeeping;
no global scan exclusion or baseline relaxation was introduced.

Rollback: revert the optional package, setting, ToolRPC registration and new
profile/guidance branches together. Existing Nerva queues, sessions and user
data are not migrated or deleted by this port.
