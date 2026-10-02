# H487 ordinary promotion recovery

Goal: after a grouped task leader is decided or edited, the next pending
interrupt card must remain deliverable across a notification failure or worker
restart. This is one reliability increment toward H487, not shared approval.

Base: `e3117df0` on `codex/h277-provider-discovery-20261002`, 2026-10-02.
Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`tools/approval_gateway_wait.py::_await_coalesced_leader`. Hermes lets a
follower adopt session/always/deny but requires a fresh prompt after `once`.
Nerva keeps individually signed tasks and does not fan out one-use authority;
its next member becomes leader and must be visible to the owner.

Current source: `TaskQueue.transition_with_group` and
`update_payload_policy_with_group` atomically withdraw the decided/edited
member and return the private group id. `AutonomyWorker._push_promoted_group`
then attempts one notification. It catches failures and has no ordinary retry
record. Approval expiry already has a separate durable effect outbox and drain.

## Contract

- In the same SQLite transaction as an ordinary grouped withdrawal, write a
  private promotion effect keyed by group id with source task id and a random
  revision. A failed effect write rolls back the decision or edit.
- The effect is a request to check the *current* group leader, never a grant or
  a frozen authorization. It contains no task payload, credential or signed
  receipt. Newer withdrawals replace the revision; an old drain cannot ack it.
- After commit, try the current leader through the existing notification
  broker. If it is already pushed, absent, or non-interrupt, ack the effect.
  On transport failure, downgrade, missing broker, or halt, retain the effect.
- Normal approval housekeeping scans effects fairly, so a failed first group
  cannot starve later groups. Restart reads the same SQLite rows. Repeated
  drains do not resend a marked-pushed card.
- Expiry effects keep their existing separate outbox. Group rejection of all
  members has no leader to promote. No decision is repeated, no execution is
  deduplicated, and `once` never authorizes a follower.

## Implementation plan

1. Add red tests in `tests/test_h487_promotion_retry.py` for atomic write,
   notifier failure/restart recovery, CAS ack, stale/empty group, halt, fair
   scan and exactly-one eventual notification.
2. Add the private table and bounded scan/ack methods in
   `agents/core/autonomy/queue.py`; register effects only in ordinary
   transition/edit transactions.
3. Make `agents/core/autonomy/worker.py` drain the exact effect immediately
   and pending effects during housekeeping through `_maybe_push`.
4. Run focused H487/expiry/grouping/policy tests, then the full backend suite
   at a source milestone. Rebuild/check Graft, update only affected Hermes
   evidence, and run strict staged secret and generated-status gates.

Review focus: concurrent replacement before ack; a follower decided before
drain; a broker that reports downgraded without delivery; a stopped worker;
many failing early groups; SQLite insert failure after task update; a restart
with the original worker gone. `H487` stays partial for reusable session/always
consent, specialized producers, other channel identities and live acceptance.

Rollback: revert the queue table/methods, worker drain and tests together.
Existing outbox rows then remain inert private metadata; no payload or grant
is lost. No push, merge, deployment or paid provider call is authorized here.

## Local verification

The restart regression failed before implementation because housekeeping did
not resend the promoted follower. The implemented outbox now passes 138 focused
H487/grouping/expiry cases, including restart recovery, atomic insert failure,
revision-based acknowledgement, a failed group alongside a deliverable group,
an empty group and a halted worker. Scoped Ruff and the rebuilt Graft wiring
graph pass. The first full backend run stopped at the generated Hermes report
check because the queue/worker evidence had drifted. Six affected rows were
re-read and restamped, including a correction to an old H288 claimant claim.
The second full backend run passed: 21,205 passed, 34 skipped, 1 expected
failure from 21,240 collected. `hermes_status.py check` and
`status_sync.py --check --reuse-test-counts` pass. H487 remains partial.
