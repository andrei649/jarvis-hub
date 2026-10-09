# H487 promoted notification freshness at dispatch

Goal: a grouped approval that was decided or edited while the durable delivery
broker held its notification must not be sent from the broker's later callback.
This is a local reliability/safety increment, not a shared approval grant.

Base: `a64d4a5d`; pinned Hermes:
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Hermes coalesces approval waits but requires a fresh prompt after a one-use
decision. Nerva promotes an individually signed follower; its outbox retry
currently looks up the leader before dispatch, then gives the broker a callback
that sends the captured task without checking whether it is still pending.

Contract:

- Recheck the task's current blocked/pushed state and group leadership inside
  the callback immediately before invoking the notifier. A promoted delivery
  also binds the original private group id, including singleton groups.
- If the card changed while the broker waited, return a non-acceptance to the
  broker; never mark the task pushed. The outbox drain rechecks current state on
  its next pass and acknowledges stale effects without resurrecting a decision.
- Preserve the broker's delivered-idempotent recovery after a crash between
  accepted delivery and `mark_pushed`. Do not add a provider call, change the
  daily interrupt allowance, reuse one task's approval for another, or hold a
  SQLite transaction across awaited network I/O.
- A decision that races *after* the final local callback check but while the
  external notifier is sending cannot be atomically undone. Record that limit
  rather than claiming cross-process linearizability of an external transport.

Implementation: first add an event-controlled regression using the real queue
and broker; confirm it fails before code. Add the callback recheck in the worker,
with an optional expected group for promotion drains. Run focused grouping,
expiry, broker and queue regressions, then the full backend milestone. Refresh
only reviewed Hermes evidence and generated test counts. Rollback is the worker
callback and tests together. No paid provider, live channel, push, merge or
deployment is required.

## Focused implementation result

The real-broker test first failed with a sent card for an already decided
follower. The worker now checks the current task and expected group inside the
broker callback and again before marking a delivery as pushed. An edited card
is bound to its exact task update revision; an idempotent broker receipt still
recovers a pending follower after an accepted send. The new delayed-edit,
expiry-promotion and idempotent cases pass. The six focused test modules collect
163 cases and pass, as do scoped Ruff, Graft and `git diff --check`. The full
backend run on this source snapshot passed: 21,209 passed, 34 skipped, one
expected failure from 21,244 collected. `hermes_status.py check` and
`status_sync.py --check --reuse-test-counts` pass; H487 remains partial.
