# H487 bounded Company Mode approval-wait accounting

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal: remove a bounded, proven human approval wait
from Company Mode's elapsed-seconds budget. Next action: implement and verify
the contract below after the model-grouping milestone. No publication or live
providers. Rollback only this slice's source/test hunks and additive metadata.

## Production boundary

ToolRPC returns `approval_required` immediately; there is no suspended concurrent
batch to pause. Company Mode persists the wait instead. Its `queued` steps can
refer to auto-approved tasks, so queued status alone proves no human wait.
Wire the actual runtime's queue reader into the ledger through an optional internal
binding. Callers without that reader retain existing wall-time accounting.

Only a freshly read real BLOCKED, effective ASK task qualifies. Bind its durable
birth, intent and receipt identity to the run's existing approval-block epoch.
Store private timing metadata outside the immutable run identity and task signed
bytes. Do not infer a grant, decision, or permission from this accounting.

## Accounting contract

Use one union window per approval-block epoch, capped at 360 seconds from its
first qualified source. This explicit conservative fallback comes from the pinned
Hermes default approval timeout of 300 seconds plus its 60-second margin. A real
task deadline may shorten eligibility, never lengthen this initial cap. It does
not add a default expiry to Nerva's otherwise indefinite pending approvals.
Overlapping asks cannot double count or reset the ceiling.

Close credit at the durable human decision timestamp or expiry timestamp, rather
than delayed reconciliation time or mutable task `updated_at`. Edits, defer,
missing/reused tasks, unreadable data and mismatched intent invalidate eligibility
conservatively; none can reopen a closed epoch. Reject nonfinite/negative/corrupt
timing material. Restart preserves valid recorded credit; clock rollback cannot
extend or restart a window. Finalization must be idempotent and transactionally
aligned with step settlement, including expiry settlement before its budget check.

Keep `WorkRun.seconds_used()` as raw wall time for compatibility. All ledger budget
decisions must consistently use effective time, including step admission, barrier
checks and resume. Add explicit wall-time and human-wait diagnostics to budget
state. Absolute deadlines, step and interruption limits, e-stop/stop, barriers and
non-approval holds keep their authority. Normal-answer resume must not bypass a
fresh budget/hold check. Never turn an unproven legacy block into approval.

## Ownership and tests

Writer A owns `agents/core/autonomy/work_runs.py`,
`agents/core/autonomy/company_supervisor.py`,
`agents/core/autonomy/company_runtime.py`,
`agents/core/autonomy/pending_requests.py` and new
`tests/test_h487_human_wait_budget.py`. Avoid changing supervisor if runtime and
ledger wiring suffice. No queue schema/source edits or existing-test edits without
declaring the specific need. Writer B owns only new
`tests/test_h487_human_wait_integration.py`, using real queue/runtime public APIs.
Coordinator owns shared contracts, review, records and milestone verification.
At most two Sol High implementers; no subdelegation.

RED/GREEN: real pending ask excludes elapsed human time, auto-approved IDs and
unbound library callers do not; overlap union/cap; actual decision cutoff despite
delayed reconciliation/execution; restart; edit/reuse/defer; failed reader and
corrupt/backward clocks; deadline/stop/barrier/interruption preservation; expiry
settlement atomically checks adjusted budget and never resumes an unrelated hold.
Focused suites after each implementation change, independent integration at freeze,
then one serial full backend milestone plus scoped scans/Graft and status checks.
No frontend change anticipated; retain its preceding tested snapshot.

This slice does not implement standing session/always/deny grants or an uncalled
suspended-batch helper. Longer explicit-deadline wait-credit adaptation remains a
follow-up; H487 cannot be marked complete solely from these changes.

Coordinator GO: this bounded contract is released for execution.

Review amendment: deferred/edited decisions can be replaced before reconciliation.
Coordinator additionally owns `agents/core/autonomy/queue.py` and new
`tests/test_h487_decision_clock.py` to retain the earliest queue-authored decision
timestamp in human-decision metadata. All three writers (individual transition,
group rejection, edit) preserve it in the same transaction. No signed intent or
execution receipt changes. Ledger settlement must require that bounded timestamp;
an older record containing only the last `at` cannot prove the first decision.
Task observations also carry their read time so slow reads cannot retrospectively
credit later time. Source ownership remains separate.
