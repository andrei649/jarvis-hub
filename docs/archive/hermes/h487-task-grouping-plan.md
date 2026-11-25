# H487 task registration grouping — bounded implementation plan

Approved scope: queue.py, worker.py, routers/autonomy.py, autonomy/inbox.py and
new test_h487_task_groups.py. Coordinator, HUDs and generated artifacts belong
to the parent. Action grouping files remain untouched.

Only the existing admin-guarded POST /autonomy/tasks produces an internal owner
registration marker. The raw canonical request participates in equality;
unknown authority/session/task/context claims opt out. Direct producers stay
independent. The marker conveys registration provenance, never an execution grant.

After an ASK submission becomes BLOCKED, register grouping metadata in separate
SQLite tables. Equality includes complete request, finalized payload/origin/tier,
attention/autonomy level, canonical actual AutonomyPolicy configuration and
outcome, independently computed taint, queue mediation mode/policy revision,
and receipt scope/verdict/tier binding. Unknown custom policies or unverifiable
receipts opt out. Independently signed receipt/ID bytes bind each member's own
CAS snapshot; never reuse execution_fingerprint as cross-task equality.

GET /autonomy/tasks keeps the complete tasks array, adding optional groups with
{id,leader_id,count,member_ids,snapshot}. Queue pending_groups()/pending_group(id)
provide the same projection. Group id/snapshot are random opaque tokens; private
request/member hashes are never public. Existing decisions remain individual.

POST /autonomy/tasks/groups/{group_id}/reject requires exact snapshot + member_ids
and optional strict reason. BEGIN IMMEDIATE checks live BLOCKED membership and
immutable snapshots then updates all statuses/human decision records or none.
Audit/prefs/run reconciliation occur after commit. Edits withdraw membership;
settlements rotate group token and promote next pending member. Notification
pushed/updated_at changes do not invalidate execution snapshots.

inbox.is_decision_notification_leader(queue, task) suppresses only a currently
pending follower. Worker _maybe_push invokes it before notifier/broker/budget,
without marking followers pushed. Parent Telegram renderer reads queue.pending_group(task.id) for group count.
Inspection found no pending-decision drain. After a successful individual
settlement or edit withdrawal, the worker performs one group-specific promotion
push for the next unpushed interrupt-mode member. It uses that member's own
budget/delivery ID; promotion failure cannot undo an already committed decision. No task deadlines or shared approval fanout.

RED/GREEN: actual admin route two tasks/one group, direct/claim/origin/policy/
taint/binding isolation, once executes one task, notification suppression and
promotion, edits and membership races across queue connections, SQLabort rollback,
reopen, independently signed receipts unchanged by grouping. Focused regressions
only, no full suite/commit/push. Group checks/fanout are capped at 64 members.

## Review correction: singleton join during settlement

Public groups omit singletons and cannot provide promotion provenance. A follower
can join through another SQLite connection after a worker's public pre-read but
before the leader's decision transaction, suppressing its own notification.
Capture the private group id inside transition_with_group() or
update_payload_policy_with_group() while withdrawing membership under
BEGIN IMMEDIATE. Return (Task, group_id) only after commit; legacy transition and
update_payload_policy wrappers still return Task. The worker promotes using that
stable private identity, including a group that was a singleton before settlement.
A deterministic pre-BEGIN barrier covers real follower notification suppression
and promotion for accept/reject/defer/edit across two SQLite connections.
