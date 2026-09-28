# H487 implementation plan — 2026-09-27

Goal: carry a human decision reason across approval surfaces, expire unanswered
requests durably, and coalesce only genuinely interchangeable pending asks.
Base/head: `bd2bb70ead1b493043a335e77713fc42c47d4013` plus local H277 changes.
Generation: 2026-09-27. Implementation and verification increments are recorded below.

## Increment 1: reasons and terminal timeout

Backend owner: action approvals, autonomy queue/worker, actions/autonomy routers,
browser agent and pending requests, plus focused regression tests. Optional human
reason is limited to 280 characters and stripped of control characters. Persist
it only after a successful decision. It must survive executor result replacement;
executor output cannot forge or overwrite trusted human metadata. Keep machine
outcomes separate from human text and include reason in existing audit records.

On an action wait timeout, atomically expire only a still-pending item, persist,
clear advisory pending state and wake all waiters. A decision that wins the race
must remain the returned decision. Later approval cannot reopen an expired card.
Expose `expired_unanswered` to browser/tool/run consumers and count expired items.

Surface owner, after backend contracts settle: optional reason fields in browser
and legacy HUD, `nerva approvals reject --reason`, then Telegram's one-reply reason
window. Bind that window to the authorized owner, chat and exact rejected task;
writing a reason is metadata-only and never reopens an action.

## Increment 2: coalescing and task expiry

H659 idempotency replay/reservation remains before `request()`. A separate
coalescing fingerprint must include authority context, principal, taint and
approval binding, not merely agent/tool/args. Shared approval is not deduplicated
execution: never silently let multiple callers execute a destructive action once
per waiter under a card that promised one execution.

Task execution fingerprints include task identity and mediation receipts. They
cannot be reused as cross-task deduplication keys. Begin with visible grouping
that retains each task's signed authorization; design any shared execution as a
separate change. Durable task expiry requires an explicit deadline/state migration,
not just changing action-card timeout labels.

## Verification and delivery

Demonstrate RED then GREEN for reason propagation, executor forgery prevention,
timeout/decision races, late approval refusal, multi-waiter wake-up, Telegram
owner/chat/window binding, H659 replay ordering and coalescing authority isolation.
Run focused suites after each slice and broader integration at the batch boundary.
Update generated route/schema artifacts if request schemas change. Mark H487
partial until every required surface and expiry/coalescing contract is delivered.

No source edits start while the H277 full-suite milestone is running. Roll back
only the corresponding localized increment, preserving H277 and existing data.
No push, merge, deployment, new paid providers or personal-profile imports.

Next action: extend trusted grouping to production model/browser producers and bind
later decisions to their originating model continuation. Owner HTTP grouping and
first-slice integration are verified below. One-use approvals never fan out.

## Settled first-slice contract

Use a shared `normalize_reason(reason)` helper: None/string only, input limit280,
replace Unicode control/format characters with spaces, trim, empty becomes None.
No coercion of numbers/objects. API validation remains strict and backward compatible.

Task reasons use a nullable JSON `human_decision` metadata column, outside executor
`result` and signed action bytes: `{id, action, reason, by, at}`. The unique decision
id binds a later Telegram reply to exactly one decision. A successful new human
decision replaces prior metadata; omitting a reason clears its current attribution.
Execution/retries cannot write that column. Keep the legacy public shape when no
human reason exists. Reason recording and the corresponding transition/edit must
be atomic, with concurrent decision losers unable to alter the winner's metadata.
PendingRequests reads trusted task metadata and carries the human reason separately
from its machine outcome. A later Telegram reply must bind to that exact decision.

Writer A owns the helper, TaskQueue/worker, autonomy router, PendingRequests and new
task-reason tests. Writer B owns ActionApprovalQueue, actions router, browser agent,
CLI and new action-reason/expiry tests. B imports the helper after A creates it.
The shared H277 runner is unchanged. UI and Telegram integration follow after these
contracts pass. Coalescing and durable task deadlines remain a separate increment.

## First-slice verification

Local coordinator integration: 352 tests passed, zero failures, errors or skips
(`/tmp/nerva-h487-integration.xml`). This covers the new reason/expiry tests, H659
idempotency, Telegram batching and per-chat lanes, pending requests, action
approvals and API surface/type generation guards. Python runs keep the repository's
normal socket restrictions and timeout configuration. The expanded Telegram suite
also passed; existing inbound-media tests emit blocked-network warnings.

The browser Decision Inbox and legacy Actions panel accept per-card optional
reasons; their focused suites passed (24 and 36 tests). Blank reason requests retain
their previous shape. TypeScript checking and the production frontend build pass;
generated OpenAPI types include the optional bounded reason. The existing bundle
size warning remains.

Telegram uses an owner/chat/prompt-bound two-minute ForceReply window after reject.
The metadata-only compare-and-set cannot change execution state or overwrite a
later decision. A regression first reproduced a reply arriving before the prompt
HTTP response. Classification now runs after the callback in that chat's lane;
other chats progress, and an unrelated reply falls back exactly once in order.
These two lane regressions and the reason-window suite pass (13 tests).

This is a verified increment, not full H487 acceptance. Coalescing was added in the
owner-registration increment below; other producer contexts remain separate.
The frozen row requires unanswered outcomes distinct from rejection, but does not
by itself require adding deadline columns to every durable task. That migration
remains optional rather than an implicit expansion of this slice. Current action
wait timeout is terminal and durable; ordinary undecided tasks remain waiting.

## Owner-registration grouping verification

Action and task grouping are now integrated with legacy Actions, Decision Inbox and
Telegram cards. Complete per-member authority remains intact; approve once affects
one request, and explicit reject-group uses an exact current snapshot. Action save
failures roll back membership/state in memory. SQLite task settlement captures private
group identity inside the transaction, covering followers joining a singleton during
accept/reject/defer/edit; four deterministic cross-connection regressions passed.

Focused action integration: 344 passed. Final task integration after race repair:
407 passed (`/tmp/nerva-h487-task-promotion-race.xml`). Telegram group wiring: 27
passed. Complete frontend: 1802 passed; legacy coverage suite passes with 69.75%
line coverage (gate60%). API/doc gates: 21 passed. These are offline results.

The original frozen remaining note proposed fanning out every decision. Pinned
Hermes actually excludes `once` from follower adoption; Nerva retains one-use
authority. Shared session/always grants are not implemented by visual grouping.
Actual model/browser grouping contexts, originating chat decision continuations and
bounded human-wait accounting remain separate work, so H487 stays partial.

## Completed local integration milestone

The final complete backend suite passed 18,765 tests with 35 existing skips
(18,800 collected), with zero failures/errors. The full frontend passed 1,802
tests; legacy HUD passed 233 with 69.75% line coverage against the 60% gate.
TypeScript checking, production build, API/type/structural guards, Bandit and
the recorded source secret scan passed. Generated count verification matches the
actual backend/frontend reports. Initial failures and the interrupted first run
are retained, not hidden, in
[evidence/h487-h513-local-integration-2026-09-27.json](evidence/h487-h513-local-integration-2026-09-27.json).

This milestone is offline and local only. Both H487 and H513 remain partial for
the producer/consumer coverage gaps recorded in their assessments.
