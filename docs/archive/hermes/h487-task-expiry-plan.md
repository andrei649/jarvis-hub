# H487 optional persisted task approval expiry

Status: design only, 2026-09-27; implementation awaits coordinator GO after the
current full checkpoint. Base/head `bd2bb70ead1b493043a335e77713fc42c47d4013` plus
preserved verified sprint changes. Goal: an owner may put an absolute deadline on
one persisted TaskQueue approval. No default expiry, synthetic approval, task
execution TTL, new notifications under emergency stop, or whole-run expiry policy.

Checkpoint release: 2026-09-27. Composer/embedding full milestone passed 18,978
backend tests with 35 skips and 1,806 frontend tests; typecheck/build and scoped
security checks passed. Coordinator authorizes the two owned implementation lanes
below, including the reviewed atomic work-run settlement addition. Next action:
focused RED/GREEN implementation, then coordinator integration and full checkpoint.

## Existing seams verified

TaskQueue stores proposed/blocked/approved/running and terminal states in SQLite.
`transition_with_group`, `update_payload_policy_with_group` and
`reject_pending_group` already acquire `BEGIN IMMEDIATE`; their current blanket
exception handlers roll back. `_withdraw_task_group_locked` changes membership
and rotates the group's snapshot, and group projection chooses the smallest
remaining member as leader. Worker decisions already clear judge pending state,
reconcile work-run asks and notify an unpushed promoted leader after commit.

`AutonomyWorker.submit` applies risk policy then uses plain or mediated enqueue.
`tick` reaps crash-stranded running tasks before its kill-switch check. The
coordinator's loop instead skips the whole worker tick under global e-stop.
`PendingRequests` reads durable task states, resolves queued steps idempotently
and resumes blocked runs only when all outstanding asks are answered. It currently
recognizes approved/rejected/waiting/lost, with a missing task recorded as failed.
Chat outcomes derive a fenced, revision-bound observation from the task row;
terminal acknowledged observations are retained for 30 days.

## Public input and durable representation

Owner-authenticated `POST /autonomy/tasks` gains optional top-level
`approval_deadline_at: str | None = None`. Keep its existing admin guard, task
policy/mediation path and response envelope. Do not accept deadlines from payload
metadata or automatically propagate them from tool/model arguments. Existing
callers which omit the field retain indefinite approval waiting.

Accept only bounded ISO-8601 datetime strings with a timezone: `Z` or an explicit
UTC offset. Reject numbers, booleans, naive datetimes, date-only values, malformed
text and invalid/nonfinite dates. Normalize aware inputs to UTC with fixed
microsecond precision and `+00:00`; compare instants, not mixed-offset text.
Proposed HTTP validation: reject deadlines at or before the validation clock with
422 before any enqueue. The queue's reusable normalization accepts historical
aware instants for trusted callers/recovery tests, but never grants late approval.
If a valid future HTTP deadline passes during intake, the durable due check wins;
return a bounded 409 identifying the persisted expired task, with no push/action.
This creation-boundary choice is explicit and can be adjusted before GO.

Add nullable metadata columns `approval_deadline_at TEXT` and `expired_at TEXT`
using the existing additive migration pattern. Add matching keyword-only default
Task fields so old direct constructors remain valid. Omit absent optional fields
from `to_dict()` to preserve old task JSON shapes; opted-in tasks expose their
canonical deadline, and expired tasks additionally expose discovery time.
`expired_at` is when the queue commits expiry, not a manufactured human decision.

These columns are outside payload, signed receipt/evidence, mediation events,
execution fingerprints and original-intent fingerprints. Do not rewrite
`decided_by`, `decision`, `human_decision`, executor result, task title/payload,
receipt or receipt digests on expiry. Existing human edit metadata may remain
historical; it must not be described as the author of expiry. Preserve the existing
`enqueue_mediated` duplicate-receipt rejection; add no replay support, deadline
refresh or reopening behavior. Existing H659 authority ordering remains intact.

At initial owner intake, compute effective policy BEFORE enqueue. Persist the
requested deadline only when that result requires human ASK; immediate ACT/NOTIFY
auto-approval has no human wait and uses no approval deadline. The API response
then omits the deadline for that auto-approved task. This avoids the transient
PROPOSED row being swept before its policy approval transaction. Do not special-case
due CAS by trusting a payload or a caller-provided "policy" decider. Direct/manual
proposed tasks with an explicitly persisted deadline remain eligible regardless
of their origin label. Existing approved/running rows never expire.

## State and atomic deadline rule

Add `TaskStatus.EXPIRED = "expired"` to TERMINAL with no outgoing transitions.
Only proposed/blocked awaiting-approval rows with a non-null due deadline expire.
Equality is due: `deadline <= transaction_now`. Approved/running tasks, execution
retries, done/failed/rejected/quarantined and deferred tasks never expire under
this feature. An owner defer is a response: keep the deadline metadata but do not
expire DEFERRED. An ASK edit still requires approval and keeps the original
absolute deadline; it must not reset the window. Merely having edit metadata does
not exempt a still-blocked task. An explicit later transition of a deferred task
back into awaiting approval reuses its retained deadline and may immediately be
due; this slice adds no reopen/reset endpoint.

One fresh UTC time is captured after acquiring each write transaction. The same
locked helper checks due rows before accept/edit/reject/defer and approval-policy
transitions from awaiting states. This makes decision ordering independent of a
scheduler: a waiter that acquires the lock after the deadline loses even if its
HTTP request started earlier. A decision committed before the deadline wins;
approved tasks are never subsequently expired by a stale sweep snapshot.

Due discovery atomically writes status/expired_at/updated_at, withdraws group
membership and inserts a durable expiry-effect
row in the same transaction. Commit that expiry BEFORE reporting
409. Do not let existing exception rollback undo the expiry. No human decision,
payload edit, preference learning or first-action metric may land on that loser.
Expired rows cannot be reopened by either mediated replay or direct transitions.
Unreadable/corrupt deadline metadata fails closed for decisions/judgments; log and
retain it for repair rather than silently approving or inventing an expiry time.

For group rejection, read the group's authoritative pending rows under the write
lock and expire due members before validating its immutable client snapshot.
A due member invalidates the whole submitted group decision: persist only expiry,
return the existing group-changed 409, and do not reject any remaining member.
Membership withdrawal rotates the snapshot and promotes a surviving leader,
including the existing singleton projection. Do not accept a silently reduced
subset using the old request. Group IDs/member IDs from the client cannot expand
which unrelated tasks this transaction expires.

## Proposed queue and worker interfaces

Writer A owns shared queue contracts and freezes them before dependent integration:

- `normalize_approval_deadline(value: str | None) -> str | None`: strict format
  validation and canonical UTC; no clock-dependent default.
- Optional keyword-only `approval_deadline_at=None` on `enqueue` and
  `enqueue_mediated`; threaded from the owner submit path only.
- Frozen `ApprovalExpiryEffect(task_id: int, expired_at: str,
  group_id: str | None)` preserves the exact acknowledgment identity even if a
  task was subsequently purged. Frozen
  `ApprovalExpiryBatch(tasks: tuple[Task, ...], group_ids: tuple[str, ...], *,
  effects: tuple[ApprovalExpiryEffect, ...] = ())` keeps existing detached-task
  convenience fields; tasks includes only matching current EXPIRED records,
  while effects includes every selected outbox receipt, including missing rows.
- `expire_pending_approvals(*, now: datetime | None = None, limit: int = 100)
  -> ApprovalExpiryBatch`: one bounded due scan/CAS transaction, idempotent across
  processes/restart; `now` must be aware and is normalized. No I/O/notifications.
- `TaskApprovalExpired(TaskQueueError)` carries the committed batch for deadline
  discoveries inside decision/edit/group mutations. Raised only AFTER commit.
  Other illegal/stale transitions retain existing errors/return conventions.
- `pending_approval_expiry_effects(*, limit: int = 100) -> ApprovalExpiryBatch`
  and `ack_approval_expiry_effects(batch: ApprovalExpiryBatch) -> int`: restart-safe
  recovery and exact `(task_id, expired_at)` compare-and-delete acknowledgment.
- `approval_is_pending(task: Task, *, now: datetime | None = None) -> bool`: pure
  status/deadline predicate for fresh judge validity; corrupt metadata returns
  false. BLOCKED-only opinion checks continue to enforce their existing rule.

Writer B threads the field through `AutonomyWorker.submit` and its plain/mediated
helpers only for effective ASK; lower-level intake defaults remain unchanged.
It consumes expiry batches
through one post-commit handler: clear pending judge keys, record a bounded machine
expiry audit, reconcile waiting runs through the existing reconciler, and optionally
push promoted leaders through existing budget/attention rules. Audit or notification
failure never reverses an expired row, grants authority or repeats preferences.

Choose the minimal durable outbox rather than relying on newly expired return
values: `task_approval_expiry_effects(task_id PRIMARY KEY, expired_at TEXT NOT NULL,
group_id TEXT NULL)`. It contains no copied payload, principal or human reason.
Every expiry path inserts it atomically, including decision/edit/group discovery
outside tick. Normal housekeeping drains existing pending effects even when its
new due scan changes zero rows. Read the authoritative expired task again before
side effects; a purged/mismatched row is acknowledged without recreating it or
sending a notification. No hard capacity cutoff silently drops effects: scans are
bounded and fair; completed rows are removed, pending rows survive downtime.

Use a queue-persisted round-robin scan cursor, following the existing queue
retention pattern, not a new scheduler: select oldest task IDs greater than the
cursor in a bounded batch, and wrap when that portion is exhausted. Returning the
detached batch advances the cursor transactionally, without removing any effect.
A failed or budget-held row remains pending but does not block later expiry
reconciliation. This is selection fairness, never acknowledgment or a work lease.
Concurrent drains can repeat an effect, so existing delivery/resolution CAS and
exact effect acknowledgment remain necessary.

After judge clearing, reconciliation, audit and promotion processing complete,
acknowledge each exact successfully processed effect. A failed effect remains
pending; successful later records in the same batch are acknowledged independently.
The existing `_audit`, `_reconcile_waiting_run` and `_push_promoted_group` swallow
errors, so merely awaiting/calling them is not proof that processing succeeded.
Use narrow expiry-specific equivalents returning reliable bool results (or raising
typed exceptions); preserve all old callers and helper contracts. A missing optional
audit/ledger or no matching outstanding run/group is a completed no-op, while a
configured audit failure, unreadable ledger, failed reconciliation or failed/budget-
held notification leaves that effect pending. Reconcile stopping/terminal runs
through the existing non-resume rules; idempotent already-resolved steps count as
completed. A surviving non-interrupt/already-pushed leader needs no new notification.
Notification delivery continues to use existing task pushed/delivery/budget guards,
and step reconciliation already has durable CAS, so retries cannot execute or
resume a second action. External best-effort machine audit may be duplicated by
a crash between logging and acknowledgment; do not claim cross-store exactly-once
audit delivery. No preference or activation event is emitted. Group promotion is
derived from current group membership, never stale leader data in the outbox.

Proposed minimal async hook:
`approval_housekeeping(*, limit=100, now=None, reconcile=True,
notify_promotions=True) -> dict` returns an expired count and bounded bookkeeping
summary, never executes tasks or creates proposals. `tick` invokes it before new
execution, using false reconciliation/notification flags when halted. A normal
housekeeping pass drains the persisted expiry effects for promotion/reconciliation
even after halt/restart or a queue-level decision conflict.

Coordinator invokes that hook with BOTH flags false before its global-estop
`continue`. It must not run the ordinary tick, reaper, observer, workflow drain,
company planner, notifier or run resume from this branch. This mode performs only
the queue metadata sweep/outbox insertion and clears newly expired in-memory
judge keys without draining durable effects. Fresh deadline/status predicates
also invalidate model sends and annotations.
Retain unacknowledged durable effects until normal post-commit processing is
permitted; defer external audit delivery too, avoiding repeated halt-tick logs.
Expiry is durable state
bookkeeping, not permission to work. After release, normal existing company-run
reconciliation sees expired tasks; normal promotion processing may push survivors.
Worker decision/group wrappers consume a `TaskApprovalExpired` batch before
preserving their existing HTTP conflict behavior. For group rejection the worker
returns None after handling expiry, preserving the current route's group-changed
409 without an uncaught exception. No periodic sweeper is relied on for correctness.

The work-run ledger is attached even when Company Mode is off, for historical
reads. Expiry reconciliation must therefore recheck `JARVIS_COMPANY_MODE` before
mutating that ledger. Relevant queued sources retain their expiry effects while
the flag is off, and recover after it is enabled. Task expiry itself remains
available independently. Freshly read each receipt's current task/status/stamp
before effects; a purged or mismatched receipt produces no audit, resume or
notification. Halted housekeeping still clears pending judge keys, but retains
durable effects and performs no external audit or run reconciliation.

## Reconciliation, judges and chat observations

PendingRequests adds exact resolution `expired_unanswered`: classify durable
EXPIRED separately, resolve its queued step as `failed`, and record a fixed reason
that the approval deadline passed. Mark the resolution machine-originated without
borrowing any historical human decider/reason. Expiry uses the localized atomic
ledger settlement below, preserving still-waiting/stopping/terminal protections.
Do not invent a whole-run failure, approve the queued action, or synthesize a
human rejection. Existing supervisor budgets/repeat-failure handling remain owner
of any eventual run termination.

### Atomic expiry ask settlement and approval-block identity

The current ordinary reconciler calls `resolve_step` (which commits) and then
`resume` separately. A crash between them strands a blocked run with no queued
asks, and `run_waiting_on` cannot rediscover the closed source. Do not reproduce
that gap for expiry or fix it by blindly resuming any later blocked run.

Add private nullable `approval_block_seq INTEGER` ledger bookkeeping through its
existing migration mechanism, outside public run authority/fingerprint fields.
When `record_step(outcome="queued")` enters blocked from a nonblocked run, set it
to that first queued sequence. Retain it across further queued steps in the same
known approval block. Clear on working/stop/terminal transitions and on another
cause of blocking, including interrupt-budget refusal. An already blocked legacy
row with no marker remains unproven: recording another queued step must NOT
manufacture a marker for it. Old unmarked blocked runs conservatively stay held.
This changes private bookkeeping, not ordinary `resolve_step`/`resume` behavior.

Exact new ledger method:
`settle_expired_ask(run_id: str, seq: int, *, task_id: int, expired_at: str)
-> ExpiryAskSettlement(settled: bool, first_settlement: bool, resumed: bool,
note: str)`. All identifiers are trusted ledger/task metadata, never body identities.
Use `BEGIN IMMEDIATE`, read the exact `(run_id, seq, task_id)` source and current
run, then compare-and-set ONLY its first queued settlement to failed with fixed
`resolution="expired_unanswered"` and the exact expiry receipt. Conditionally
resume in that SAME transaction only when the run is still in its proven approval
block, source `seq >= approval_block_seq`, no queued asks remain, and there is no
barrier, stop/terminal state, other/budget block or spent budget. Use the existing
legal transition helper with `commit=False`, then commit once. A failure rolls
back BOTH source resolution and run movement. Add no step, spend no second budget
and do not invent a whole-run terminal outcome.

A repeated already-failed source carrying the same exact expiry receipt reports
settled but never resumes, even if the run has since entered another block. A
different task/receipt/resolution is a fail-closed mismatch, not permission to
rewrite a closed step. A first settlement can legitimately report held/no resume
(remaining asks, legacy missing marker, stopped/terminal/budget/barrier block);
that is a completed durable failed-step observation, not an effect error.

`steps.task_id` is not unique. Add bounded
`pending_asks_for_task(task_id, *, limit=100) -> list[Step]`, querying queued source
steps in sequence order (and a matching task/sequence index). Expiry-specific
reconciliation settles EVERY selected exact source, not only `run_waiting_on`'s
first match. Before effect ACK, test whether any matching queued sources remain.
If a page limit is reached, leave the effect pending; the next pass progresses
because atomically settled rows are no longer queued. No persistent second list
of pending asks, wildcard run resume or unbounded cross-run operation is needed.
Already-closed sources do not need rediscovery to complete a resume: first closure
and its conditional resume either both committed or neither did.

Keep ordinary non-expiry reconciliation unchanged. An expiry branch in
PendingRequests must use this atomic seam, including when the company scheduler
finds expiry before the outbox drain; it must never perform a second generic
`resume` for that expiry settlement. For a mixed reconciliation pass, process
ordinary answered asks first and expired asks last, so the atomic final expiry
settlement can safely resume the same block once all asks are closed. Respect
still-waiting sources and inspect all queued asks transactionally, not just the
bounded page. Report the atomic result rather than infer resume from current run
status. An expiry-containing pass has no unconditional resume fallback; replay
of a previously settled expiry cannot unblock a subsequent unrelated block.

TaskApprovalJudge's fresh snapshot uses `approval_is_pending` in addition to its
BLOCKED/digest checks, including after slot acquisition and before physical sends.
Queue opinion reads/stores also reject due snapshots before a timer sweep, and
persisted expiry rejects late generation/annotation. Clear pending state on every
consumed expiry batch, without changing shared capacity mechanics or judge APIs.
Do not increment the advisory edit revision just for expiry: that counter also
participates in the chat original-intent hash. Deadline/status predicates revoke
opinions without falsely presenting unchanged action bytes as an edit.

Chat outcome projection adds `state="expired"`, `outcome="expired_unanswered"`
and bounded `expired_at`/deadline metadata; it remains separate from human decision.
Include expiry metadata in observation revision CAS, not signed intent bytes.
The existing renderer fences it as data and forbids replay; acknowledgment remains
only after successfully persisted reply and only for actually included rows.
Add expired to terminal same-revision 30-day retention. No new observation is
attached to arbitrary owner API tasks lacking an existing exact chat association.

## Ownership, tests, compatibility and rollback

Writer A: `agents/core/autonomy/queue.py`, new queue expiry tests in
`tests/test_h487_task_expiry.py`, narrowly relevant queue/group/chat store tests.
Writer B: `agents/core/autonomy/worker.py`,
`agents/core/autonomy/pending_requests.py`,
`agents/core/autonomy/work_runs.py` and new `tests/test_h487_work_run_expiry.py`
(localized atomic expiry settlement and private marker bookkeeping),
`agents/core/autonomy/task_approval_judge.py`,
`agents/core/autonomy_coordinator.py`, `agents/core/routers/autonomy.py`, new
`tests/test_h487_task_expiry_integration.py`, and narrowly relevant worker/pending/
coordinator/judge tests. Coordinate exact batch/exception/predicate interfaces
before B writes; no two writers edit queue.py. Coordinator owns shared integration,
HUD/API artifacts and reviewed evidence/coverage records.

RED/GREEN, offline, normal project pytest timeout/socket flags:

- Old migrated DB and direct Task construction; unset/null means no expiry; aware
  offsets/Z normalize; wrong types/naive/date-only/malformed/past HTTP input refuse.
- Boundary before/equal/after deadline, restart downtime, bounded repeated sweeps,
  and two independent SQLite connections racing sweep vs accept/edit/defer.
- Due decision without a sweep commits expiry despite 409; early accept wins;
  approved/running/retry/terminal/deferred never expire; ASK edit retains deadline.
  Explicit deadline on immediate AUTO/NOTIFY does not create a human expiry window;
  a direct manual proposed task with its persisted deadline still expires.
- Receipt bytes/digests/execution fingerprint remain unchanged by metadata/expiry;
  existing mediated duplicate receipt rejection remains unchanged and cannot
  refresh a deadline or reopen terminal state.
- Group due-member conflict commits only expiry, leaves all survivors undecided,
  rotates snapshot, promotes leader and rejects old callbacks; singleton behavior.
- Blocked run records failed/expired_unanswered once and resumes through existing
  reconciliation only; remaining asks hold it, stopped/terminal runs never reopen.
  Inject failure between step UPDATE and run UPDATE/commit: both roll back;
  reopen/retry settles and resumes once. Replay a settled receipt after a later
  approval/budget block: no second resume. Marker is retained across same-block
  queued steps, cleared on other/working/stop transitions, and never inferred for
  an existing unmarked blocked row. Multiple asks/run reuse of one task ID and
  more-than-one-page sources all settle before truthful effect ACK. Mixed normal
  and expiry resolutions never trigger a second generic resume.
- Judge queued behind a slot crosses deadline: no model request/opinion; deadline
  crossing during model await rejects late annotation and clears pending keys.
- Global e-stop housekeeping persists expiry with zero execution/proposal/notification/
  resume; release/restart reconciles and promotes through ordinary bounded paths.
  Queue-level expiry followed by a crash before worker handoff is recovered from
  pending effects even when the next sweep expires no new rows; acknowledgment CAS
  and partial side-effect failures preserve retry safety.
- Exact-session chat snapshot renders distinct expiry, retains failed/cancelled-turn
  delivery, uses observation revision CAS and prunes only terminal acknowledged rows.

Do not run duplicate full suites per writer. Coordinator runs one serial full
checkpoint after focused results/source freeze. Existing omitted-field POST,
decision/group envelopes, preferences, action-approval expiry and work-run budgets
retain their contracts. Coordinator owns optional deadline/expiry display in the
existing Decision Inbox (`frontend/src/gap.tsx` and its tests) and generated schema.
There is no new general task-creation UI: owner POST is the authoring seam. This
plan requires no deadline input UI, expiry default or browser-run timeout change.

Rollback removes the opt-in creation field and runtime expiry/housekeeping paths,
leaving nullable columns for compatible metadata recovery. Never automatically
reopen expired tasks or reinterpret them as approved. Any operational rollback
must retain recognition of already-persisted EXPIRED rows and reconciliation/chat
projection, or export/migrate them explicitly before using an older binary that
cannot parse the enum. Signed authority records remain untouched throughout.
