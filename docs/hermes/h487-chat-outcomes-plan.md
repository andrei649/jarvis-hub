# H487 originating chat approval outcomes

Status: implemented and focused verification passed, 2026-09-27. H487 remains
partial. This slice reports authoritative task outcomes on a later human turn;
it does not resume a suspended tool loop or grant authority. The combined
22-file regression run passed all 776 tests, including 46 new cases. Exact
snapshot and limitations: [verification evidence](evidence/h487-chat-outcomes-2026-09-27.json).

Base/head: `bd2bb70ead1b493043a335e77713fc42c47d4013` plus the current local
H277/H487/H513 diffs. Generated 2026-09-27. Changed paths: approval_outcomes.py,
autonomy/queue.py, autonomy/worker.py, orchestrator.py, tool_rpc.py,
session_archive.py and two focused test modules, all under agents/core or tests.
Next action: H513 auxiliary dispatch policy, followed by the next integration
milestone. The design below records the approved contract; implementation notes
at the end record narrowed producer coverage and inspected receipt semantics.

## Observed integration paths

- `agents/core/tool_rpc.py:ToolRPCServer.handle` has two successful gated
  enqueue paths: a registered server-owned `gated_intake`, and the generic
  `_enqueue` callback. Both call `record_pending_approval(task_id)` only after
  the callback returns. The no-enqueue path returns `approval_required` without
  an ID and must produce no durable association.
- `agents/core/autonomy_coordinator.py:_wire_agent_tool_runtime` wires the real
  ToolRPC server to `_governed_enqueue`, which delegates to
  `AutonomyWorker.govern_enqueue`; the fallback calls TaskQueue directly.
  Specialized image/speech intakes can use the same queue through their own
  server-owned paths. Associate the actual task they create, not a guessed
  `toolrpc.<name>` kind or model-supplied task ID.
- `agents/core/turn_approvals.py` is a reporting-only ContextVar containing a
  mutable list of IDs. `/chat` and the `/chat/stream` runner open it and return
  `pending_approvals`; it has no session, principal, turn ID or durable store.
  Preserve this API and its exception/cancellation reporting behavior.
- `agents/core/agent_runtime.py:AgentRuntime` appends tool observations to its
  temporary model messages, then returns `_approval_reply` immediately when
  an observation is `approval_required`. Those temporary messages do not
  become a durable conversation. Later prompt history contains ordinary
  user/assistant prose, not a live approval outcome.
- Both orchestrator turn paths resolve the context-local session, prepare a
  continuation, and persist the user message before routing. Streaming and
  non-streaming prompt construction converge on `_build_agent_turn_text`;
  managed compaction also calls it from `_shared_route_plan`. This is the
  common observation insertion point. `_history_for_prompt_parts` is rendered
  conversation history and should remain unchanged.
- `project_context.note_task` records a task-to-session association only in a
  bounded process-local dictionary, only on the generic ToolRPC path. It tracks
  a later terminal working directory, not approval identity or durable outcomes.
  It is insufficient as this slice's authority or persistence source.

## Identity that exists, and prerequisites that do not

Checkpoint `sessions.instance_id` is durable and randomly assigned, including
legacy migration. `CheckpointManager.clock_snapshot(session_id)` returns an
existing live session's instance; it does not manufacture a session. Continuation
creation assigns a new session ID and new instance, even though its clock carries
the root birth time and its seed copies conversation history. Bind to the exact
current `(session_id, instance_id)`, never a root ID or birth date. Branches do
not inherit outstanding approval associations.

`Principal(channel, sender, admin, chat)` is established at the HTTP/channel
boundary. HTTP `_web_principal` verifies owner/admin credentials or the existing
fresh-box direct-localhost posture, but all ordinary users have `sender=None`.
It is not a per-user identity API. `_channel_principal` has Telegram sender/chat
identity and the existing allowlist/owner-chat authorization test. Voice and
unknown principals have no stable authenticated subject. Do not derive identity
from request bodies, user text, tool arguments, session names, raw credentials,
model actor names or `decided_by` strings.

Recommended first producer coverage: verified owner-web gets fixed private
subject `web-owner`, within this queue namespace; authorized Telegram requires
both an actual sender and chat, and uses that exact tuple. Require the same
verified principal on the consuming turn. This intentionally does not bridge
web and Telegram even when cross-channel sessions are enabled. Owner-web is one
existing local owner role, not a claim of account-level isolation. Ordinary
HTTP users, identity-less voice, other channels and background work opt out.
Supporting them needs a real channel-authenticated stable subject API first.

Conversation `Turn` currently has timestamp, content, role, agent and tool names,
but no durable turn identifier. Add a server-generated random originating-turn
ID in the association store after the real user message is accepted, before any
model/tool call. Never use turn count, timestamp or message digest as identity.
The new origin record is the durable tool-producing turn identity; this slice
need not change transcript formats. A failed/cancelled turn can still own a
persisted queued ask. A turn without an accepted live session has no producer
context and retains legacy behavior.

## Proposed storage and producer contract

Use a new small `agents/core/approval_outcomes.py` for typed, server-only turn and
ToolRPC producer contexts plus bounded rendering. Persist origin associations
in TaskQueue's SQLite database, outside `tasks.payload`, `result`, signed action
bytes and mediation receipts. Keep all new state out of Task/to_dict and the
existing execution fingerprint. No new HTTP request fields are needed.

Proposed tables:

1. `chat_approval_origins`: queue-local origin ID primary key; exact session ID,
   session instance, private canonical principal key, originating turn ID,
   creation time. Index the exact consumer tuple.
2. `chat_approval_tasks`: actual task ID primary key; origin ID; bounded original
   ToolRPC name; original intent digest/edit revision; finalized binding digest;
   ready flag; latest delivered observation revision. No copied decision/result.

Generate one turn context after session preparation/user persistence in
`_handle_input` and `_handle_input_stream_prepared`, and reset/close it in the
public wrappers' `finally`. Its shared lifetime guard closes inherited child
contexts too, so a detached background job cannot keep attaching to a finished
turn. A nested ToolRPC-only producer scope wraps the two actual synchronous
enqueue callbacks. The queue consumes that typed scope during `enqueue` or
`enqueue_mediated` and inserts the task association in the **same transaction**
as the task. This covers the raw-queue fallback without marking every autonomous
enqueue occurring during a chat. Require exactly one associated task for the
returned ID; mismatches or multi-task specialized intakes are explicitly
unsupported until their contract is tested. Model-provided context is ignored.

The current collector remains reporting-only; recording the association only
in `record_pending_approval` would leave a crash/fast-decision race after enqueue.
Adding SQLite writes there is therefore insufficient.

Bind the final ASK intent/authority coherently when governed intake changes the
actual task to BLOCKED, after any server-owned intake evidence is finalized.
Use the existing queue transaction for that transition. Initial insert records
origin but not an approved observation-ready snapshot. A failed or unfinished
intake remains not ready and cannot report an approval. Specialized intakes must
explicitly finish this same queue-owned association step, with exact task ID and
validated binding. If a path cannot prove its finalization point, opt it out and
report that coverage gap; never finalize an arbitrary returned ID after the fact.

Do **not** use `execution_fingerprint` or `approval_snapshot_digest` directly:
they include decision/decider and signed receipt execution fields which change
during ordinary authorization/execution. Add a dedicated intent projection over
original task agent/kind/title/payload/origin/risk/autonomy/attention and immutable
enqueue authority identifiers, policy/scope and finalized intake binding, plus
the existing advisory edit revision. Compare immutable binding independently
from legitimate receipt advancement. Payload edits, even equal-byte edits,
invalidate original intent; notification timestamps, pushed flags, attempts,
decision/reason and ordinary execution receipt advancement do not. Never rewrite
the original intent digest to make an edited action appear unchanged.

## Authoritative consumer and observation contract

At a later matching human turn, before any model call, read a bounded joined
TaskQueue snapshot for the exact session instance and principal. Exclude asks
originating in the current turn. Resolve from current queue state and trusted
`human_decision` metadata, never executor result keys or the collector's list.
Freeze that read for the current prompt preparation, so parallel agents and
managed/unmanaged prompt paths see the same bounded observation. A decision
arriving after that snapshot belongs to the next matching turn.

Proposed private queue API:
`chat_outcome_snapshot(context, *, limit=8, max_bytes=4096)` returns detached
structured observations and their revision tokens; `ack_chat_outcomes(context,
observations)` compare-and-sets exactly those revisions after a model reply is
successfully persisted. Interrupted/failed turns do not consume the revision.
No exactly-once model delivery is claimed across a reply-persistence crash;
repeat bounded reporting is safe because it performs no operation. Keep
unacknowledged oldest revisions eligible so more than eight asks do not starve.

Each observation contains only task ID, originating turn ID, bounded tool name,
`intent: original|changed`, current task state, machine outcome, and optional
trusted decision `{id, action, by, human_reason}`. No arguments, raw result,
credential or receipt bytes. A revision digest covers current state, changed
intent marker and complete trusted decision metadata; it excludes pushed and
updated_at. A later Telegram reason attachment changes the revision even though
its decision ID and execution state are unchanged. Acknowledgement of the old
revision cannot consume that new reason.

Render a labeled structured data block in `_build_agent_turn_text`, outside
conversation-history cache parts. Use the existing untrusted-data fencing for
human reason text: normalized controls and 280 characters do not make human
text a system instruction. Fixed instructions state that these are observations,
approval does not prove execution, and no tool is to be replayed. Never append
fabricated `role=tool` messages or tool-call IDs to a later turn.

Distinguish `waiting` (proposed/blocked/deferred), `approved_not_executed`,
`running`, `completed`, `execution_failed`, `rejected`, `quarantined` and `lost`.
A failed execution is not a human rejection. An edited task reports changed
intent and the actual edit outcome; approval of the edited action must never be
described as approval of the original arguments. Use a dedicated classifier:
`PendingRequests.classify` is designed to unblock work-run asks and intentionally
collapses several of these statuses. Do not change work-run reconciliation for
chat reporting. Missing task ID reports lost, with no inference of approval.

## Deletion, bounds and explicit exclusions

Revalidate checkpoint session instance before association and before prompt
injection; fail closed for absent/mismatched identity. Existing session leases
protect accepted HTTP/channel turns, but checkpoint and autonomy databases are
separate: there is no existing atomic cross-database deletion transaction.
Add association cleanup to successful `session_archive.delete_session` /
`delete_leased` / retention deletion, with backup/purge coverage and retries for
cross-store cleanup failure. Identity gating prevents leakage before cleanup;
it is not a substitute for deleting retained principal/session metadata.
Continuation seed creation copies no associations. Purging TaskQueue rows must
either retain a bounded lost marker or prune according to documented retention.

Proposed bounds: eight observations/4096 UTF-8 bytes per turn; at most 64
outstanding associations per origin turn, 256 per exact consumer identity;
bounded housekeeping batches of 128. Keep full associations for pending asks;
reject new observational association at the cap, retain the actual task and
legacy pending_approvals response, and log a bounded coverage-gap event. Do not
delete an undecided task to meet the cap. Terminal acknowledged metadata can be
pruned after a documented retention interval; agree that interval before code.
No timers, model wakeups, automatic execution, ToolRPC replay, duplicate cards,
shared grants, browser producer grouping or cross-channel identity mapping.

TaskQueue has no EXPIRED status or durable task deadline. ActionApprovalQueue's
expired-unanswered behavior applies to its own records only. Ordinary chat
ToolRPC asks remain waiting indefinitely until decided/lost. Durable TaskQueue
deadline/state migration and human-wait budget accounting are distinct optional
prerequisites, not delivered or implied by this observation slice.

## Implementation ownership and acceptance checks

Recommended backend writer: new approval_outcomes module; turn_approvals lifetime
seam; orchestrator binding/prompt/ack hooks; ToolRPC producer scope; TaskQueue
association/finalization/read/CAS; worker governed ASK finalization. Specialist
intake hooks are separately assigned only after proving their final enqueue
boundary. Session lifecycle writer: checkpoint identity accessor if needed,
archive/retention/purge cleanup and backup contract. Keep existing HTTP response
shape and auth behavior. AgentRuntime needs no resumed-loop implementation.

New `tests/test_h487_chat_outcomes.py` should demonstrate RED/GREEN for actual
chat -> ToolRPC -> governed queue -> later chat, on streaming/non-streaming and
managed/unmanaged prompt paths. Assert one enqueue and no tool invocation on
observation delivery; accept before worker tick reports not executed; later
running/done/failed revisions reflect actual execution independently of approval.
Reject reason survives restart, executor result cannot forge it, later Telegram
reason is a new revision, and an acknowledgement race preserves the newer one.
Cover same-byte and changed edits, edited-BLOCKED/rejected edits, refused edit,
notification-only bookkeeping, original receipt/fingerprint integrity,
missing/purged task, unauthorized principal, same session with different sender,
same sender in another chat, delete/recreate, continuation parent/child isolation,
background/expired contexts, failed enqueue and SQL rollback. A fast decision
from a second SQLite connection cannot consume an unfinalized binding. Cap and
byte-limit tests prove bounded prompts and pending association preservation.

Focused regressions: `test_turn_pending_approvals`, `test_tool_rpc_runtime`,
`test_tool_rpc_intake`, `test_tool_rpc_h20_1`, `test_agent_runtime_v2`,
`test_session_continuation`, `test_h218_archived_chats`, H487 task reasons/groups,
task mediation evidence/head-store and pending requests. Run ordinary repository
pytest options; no full suite until coordinator requests the milestone.

Rollback: disable only the new observation producer/consumer; pending tasks and
their normal decision/execution continue unchanged. Nullable/new side tables are
additive and remain readable for cleanup; never downgrade/delete existing queue
rows, decisions, signed receipts or H277 advisory state. Remove new metadata only
through the explicit session/privacy cleanup path, after backup requirements.

Coordinator decisions under the owner's standing local-development authorization:
start with verified owner-web and exact authorized Telegram sender/chat, explicitly
opting out other principals; retain acknowledged terminal association metadata for
30 days, while session deletion purges it immediately. Pending associations are
never removed to satisfy the cap. Identity checks fail closed even when cross-store
cleanup fails. Prove each specialized intake finalization before enabling it; an
unproven producer remains outside the association contract. Assign queue/helper/
worker changes separately from orchestrator/ToolRPC/session lifecycle integration,
with one writer per file. No additional owner approval is needed for this local work.

## Backend store implementation notes

Implemented shared contract in `approval_outcomes.py`: `open_approval_turn`,
`bind_approval_turn` (including None for entry isolation), `close_approval_turn`,
`current_approval_turn`, and `tool_approval_scope` (None masks inherited scopes).
Both turn and producer lifetimes close across copied child contexts. Renderer
returns `(complete_block, detached_included_observations)` so acknowledgements
cannot consume omitted records. JSON angle brackets are Unicode-escaped before
the existing quarantine fence; decoded human text remains exact, literal fence
markers cannot terminate it. Header/fence/data share one 4096-byte UTF-8 budget.

Queue `chat_outcome_snapshot`, `ack_chat_outcomes`, `chat_outcomes_for_backup`,
`purge_chat_outcomes`, and `prune_chat_outcomes` provide consumer/lifecycle hooks.
Task insertion and origin insertion share one SQLite transaction in both enqueue
paths. The worker's existing policy/needs-approval BLOCKED transition finalizes
the binding inside that same transition transaction, only while the actual
originating producer context is live. Worker initial governed ASK settlement uses
an optional `expected_status=PROPOSED` transaction CAS; other transition callers
retain their previous default semantics. A second connection's accept/reject/
defer/edit can no longer be overwritten by the initial needs-approval transition,
and its losing intake cannot finalize the association.
Raw queue fallback and unfinished/failed intakes remain unfinalized. Generic
ToolRPC is the only initial producer; specialized intake scopes opt out.

Source inspection corrected the earlier receipt assumption: version1 enqueue
MediationReceipt is immutable; claim adds `mediation_execution_id` without changing
the receipt. Intent therefore includes the full original enqueue receipt and
finalized intake evidence, while excluding execution ID, decision/decider/status/
result/attempts and notification bookkeeping. Existing advisory edit revision
detects equal-byte edits. Normal queue IDs are AUTOINCREMENT and no queue reset/
reuse path exists; whole-database purge removes associations too. Stored task
birth additionally recognizes externally substituted incarnations.

Corrupt/unavailable observations fail closed with a bounded fixed log message;
an invalid member cannot suppress unrelated valid members. Live instance checks
occur before/after snapshot and before acknowledgement commit. Revision-CAS reads
current authoritative state and trusted decision metadata, including late reason
attachment. Missing task rows report lost; approval reports not-yet-executed until
actual running/completed/failed state arrives. Acknowledged terminal retention
uses the shared 30-day constant and a durable bounded scan cursor so old pending
or changed revisions cannot permanently starve later eligible records. The sweep
runs when a live consumer requests its next snapshot. Pending tasks are retained.
The sweep self-seeds its cursor inside the transaction after a live global data
purge removes all metadata rows, so cleanup continues without a queue restart.
