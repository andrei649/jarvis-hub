# B7 task-persisted Ultron mediation evidence

**Status:** owner decisions recorded on #818; implementation authorized, default-off.

## Goal

Prove that each `TaskQueue`-persisted action classified `Mediation.KERNEL` was
authorized by the existing Action Kernel, bound to the exact queued task bytes,
validated again by the worker, and represented by tamper-evident persisted events.
B7 measures mediation; it does not widen authority or implement Night Shift.

## Non-goals

- No synchronous, workflow, facade, provider, scheduler, dashboard, or Night Shift
  expansion.
- No second policy or permission engine. `kernel.authorize()` remains the decision
  source; B7 only seals and validates its decision.
- No silent trust for legacy rows, raw enqueues, missing keys, or default-off state.
- No release, live-hardware, or universal-mediation claim.

## Owner decisions applied

1. Coverage is limited to persisted kinds that `kernel.registry.classify()` returns
   as `Mediation.KERNEL`.
2. The broker obtains a kernel decision first. A signed decision receipt is then
   verified and inserted with the task and initial event in one SQLite transaction.
3. `enforce` mode fails closed when the kernel, signer, receipt, or evidence write
   is unavailable. `off` is the compatibility default, not a proof state.
4. Pre-B7 classified rows without valid receipts become `quarantined`; they are
   never inferred governed or re-authorized in place.
5. `hold` is the rollback mode: it refuses new classified work and never claims or
   executes stamped work, while preserving every receipt/event/counter.
6. Queue, worker, kernel, metrics, and mediation evidence use `agents.core.*` as
   their canonical production identity; hostile import-order tests reject a split.

## Contract and persistence

`agents/core/autonomy/mediation.py` owns canonical serialization, digests, and
detached HMAC validation. It receives an existing owner-held signing primitive; it
does not decide policy. A version-1 receipt binds:

- receipt and enqueue UUIDs;
- agent, kind, title, origin, scope and canonical payload digest;
- kernel verdict, tier, reason digest and policy revision;
- issued/expiry time and single-use enqueue revision;
- signature over every field above.

`TaskQueue.initialize()` adds nullable task columns for the immutable digest,
enqueue identity/revision and receipt, plus `task_mediation_events`. Events bind
task/enqueue/receipt/execution identity, outcome, timestamp, previous event hash,
event hash and HMAC. Required outcomes are `governed`, `refused_unmediated`, and
`ungoverned_detected`; counters group only events whose chain and signature verify.

`enqueue_mediated()` verifies the receipt and exact proposed fields, then inserts
the task, receipt binding and enqueue event atomically. Raw `enqueue()` refuses a
classified kind in `enforce`/`hold` and persists `refused_unmediated`. An evidence
write failure rolls back the task insert.

`claim_mediated()` is one compare-and-set transaction. It reloads the persisted
row, validates signature, path-independent canonical bytes, policy revision,
expiry, task/payload/kind/scope identity, enqueue revision and absence of a prior
claim, then changes `approved -> running` and records `governed` with a fresh worker
execution UUID. Missing, forged, copied, stale, replayed or modified receipts are
quarantined and recorded as refusal/detection; the executor is never called.

## Runtime flow

`AutonomyWorker` receives an optional bound kernel and mediation authority. In
`off`, existing behavior stays unchanged. In `enforce`, `govern_enqueue()` and
`submit()` classify the server-owned kind, call the existing kernel, and:

- `DENY`: persist refusal, create no task;
- `QUEUE` or `GRANT`: seal the exact decision and call `enqueue_mediated()`;
- missing/disabled/failing kernel: persist refusal, create no executable task.

The existing autonomy policy may still tighten a kernel result, but never loosen
it. Human approval changes task state only; it does not rewrite the sealed receipt.
Payload edits require a new enqueue revision and kernel decision, never mutation of
the old governed row. `tick()` uses `claim_mediated()` before executing classified
tasks. `hold` reports them held without state mutation.

At startup under `enforce` or `hold`, the queue quarantines classified legacy rows
that lack a valid receipt, including approved/running recovery rows. A detector
persists `ungoverned_detected` for planted or externally modified classified rows;
no counter is calculated by subtraction or literal zero.

## Failure and concurrency model

- SQLite `BEGIN IMMEDIATE` plus the queue lock serializes insert, claim and event
  chain updates.
- Receipt and event comparison uses constant-time HMAC verification.
- One enqueue UUID and revision can produce one task; one task/revision can produce
  one worker claim. Retries require a new execution event but cannot authorize a
  different task or payload.
- Restart reconstruction reads and verifies persisted rows only; process memory is
  not evidence.
- Corrupt schemas, malformed JSON, signing-key failure, evidence-write failure and
  classifier failure all deny or hold classified execution.

## Tests

Red-first tests cover missing/forged/copied receipts; task, payload, kind and scope
substitution; post-approval edit; stale revision/expiry; replay; concurrent double
claim; restart/retry; legacy approved/running quarantine; event-write rollback;
kernel off/unbound; raw enqueue and direct-executor bypass; event tampering; planted
ungoverned rows; real-event counters; hold rollback; and `core.*`/`agents.core.*`
import order. Adjacent queue/worker/broker/action-auth/lifespan suites, Ruff, security
gates, status synchronization and exact-head hosted Windows/Linux CI remain required.

## Rollback

Set the mode to `hold`, not `off`. This stops new classified enqueue and execution
without deleting receipts or events. Reverting code leaves additive SQLite columns
and tables inert. Resumption requires a compatible B7 validator in `enforce` mode;
every held task is revalidated at claim time. Legacy rows never become governed.
