# H487 approval-wait accounting review

Generated 2026-09-27; base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal and scope are in
[the implementation plan](h487-human-wait-budget-plan.md). Next action: standing
approval consent and the next media-provider integration contract. The final full
backend milestone passed 19,285 tests with 35 skips and no failure/error; scoped
Bandit/Gitleaks and Graft passed. Frontend is unchanged from its 1,822-test snapshot.

The native Company runtime binds its queue reader to the ledger. Only a real
BLOCKED ASK task with matching birth, intent and receipt identity establishes a
private wait interval. Ordinary queued work, library callers without the reader,
legacy blocks and missing data cannot invent human-wait credit. Each approval
epoch has a fixed 360-second ceiling; overlapping sources contribute their union.
The effective budget applies consistently at step admission, barriers and both
normal and expiry reconciliation. Absolute deadlines and non-approval holds retain
their authority; raw `WorkRun.seconds_used()` stays a wall-time measurement.

Three concrete review corrections were verified before the full suite:

- Queue decisions retain `first_at` independently of replacement reason/action
  metadata. Defer followed by accept cannot turn the intervening delay into human
  think time. Older or damaged history without a proven first timestamp remains
  conservative. No signed task intent or execution receipt is changed.
- Task observations record their read time. A slow reader returning an older
  pending snapshot cannot credit the time spent waiting for that reader. A
  persisted clock high-water prevents clock rollback from renewing the budget.
- Budget reads now write private accounting metadata, so `budget_state`,
  `record_step` and `set_barrier` acquire a SQLite write transaction before their
  snapshot and roll back failed refreshes. Intentional committed exhaustion and
  interruption holds retain their previous behavior.

The private metadata checksum detects accidental corruption; it is not a MAC or
an execution grant. Existing manual resume semantics are preserved. The new
conditional reconciliation resume checks the actual settled source rows, current
approval epoch, outstanding asks, budget and holds in one transaction.

Implementation focus passed 248 tests, independent actual-runtime integration
passed 13, and the coordinator's queue metadata regression set passed 140.
An additional bounded read-only review reported no further actionable findings;
it did not run tests. The suites remain offline. No live provider/device test,
new mutation campaign or frontend change is claimed.

This conservative initial cap does not implement longer deadline-derived credit,
standing session/always/deny permissions, or additional proven approval producers.
H487 remains partial. H277's queue evidence changes only in observational human
decision metadata; its judge and signed execution boundaries remain intact.
H513's shared `docs/FLAGS.md` evidence changes only in the Company Mode cost
paragraph; its provider-consent configuration and role documentation are unchanged.
