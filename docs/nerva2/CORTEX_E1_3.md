# Cortex E1.3 — `nerva.ledger.v1` cognitive-ledger contracts (B4)

Program: #757 · Epic: #759 · Blocker plan: #778 item B4 / M1 item 5 ·
Prerequisites: E1.0 (`nerva.decision.v1`), B7 mediation receipts, E6.0
(`OutcomeObservation`), GAP-9 (`nerva.reality.run.v1`), E9.0 (`nerva.benchmark.v1`)

## State and boundary

**DELIVERED CONTRACT — NOT PROGRAM-ACCEPTED.** E1.3 ships the typed records that
M1 item 5 ("cross-cutting Goal/Evidence/Outcome/Cognitive-Ledger records") was
missing: nothing in the codebase previously linked a Cortex `DecisionRecord` to
a kernel `Decision`, a task execution, a reality/benchmark verification and an
`OutcomeObservation`. E1 stays `building`; this slice adds plain typed data and
no runtime path, flag, route, store or kernel action kind. Program completion,
release readiness and any E5/E10/E11 claim do not follow from this document.

The ledger is **record-only**. Every record carries `authority="record_only"`
and `can_authorize=can_execute=can_mark_complete=False` as non-init fields; a
loaded payload that flips any of them, changes the authority string, or carries
a foreign schema is rejected. Ultron remains the sole authority — the ledger
points at Ultron's sealed `MediationReceipt`, it never issues one.

## Module

`agents/core/cognitive_ledger.py` (tests: `tests/test_nerva_cognitive_ledger.py`).

| Record | Names its sources through | Rule it carries |
| --- | --- | --- |
| `LedgerRef` | — | content-free pointer: `record_schema`, `record_id`, `integrity_sha256`, `privacy_class` (the `EpisodeReference` pattern). `from_decision_record`, `from_receipt`, `from_reality_run`, `from_benchmark_run`, `from_outcome_observation`, `to_record`. |
| `GoalSpec` | `approved_by` | scope (`GoalScope` domains / capability ids), `GoalBudget` (steps, wall_seconds, usd), `deadline_at`, non-empty `stop_conditions`; **frozen once approved** (cannot be superseded). |
| `EvidenceRecord` | `sources` (≥1) | `claim`, `environment ∈ {ci, local, owner_live}`; a claim with no source is invalid. |
| `ActionIntent` | `goal_ref`, `decision_ref` | kernel `Action` digested through `mediation.payload_digest`; the payload itself never enters the ledger. |
| `AuthorizationRecord` | `intent_ref`, `receipt_ref` | kernel `Decision` verdict / tier / `reason_sha256`; **`grant` without a receipt ref is a forgery**; `from_decision` refuses a receipt whose payload digest, kind or verdict does not bind the intent. |
| `ExecutionRecord` | `authorization_ref` | `task_id`, `execution_id`, `status ∈ {queued, running, partial, done, failed}`; terminal states need `started_at`/`finished_at`. |
| `VerificationRecord` | `execution_ref`, `run_ref` | `method ∈ {reality_run, benchmark_run}` must match the run ref schema; `verdict ∈ {verified, not_verified, not_exercised}` (`not_exercised` must state a limitation). |
| `OutcomeRecord` | `verification_ref`, `observation_ref` | pointer to a `nerva.outcome-observation.v1`; `comparison_status` mirrors Reflection's four statuses. |

Every record is **content-addressed**: `record_id = "ledger:<kind>:" +
sha256(canonical payload with empty record_id)[:24]`, `fingerprint =
sha256(canonical JSON)`. Canonical JSON is `mediation.canonical_json` (sorted
keys, compact separators, bounded depth/size, NaN refused). Editing a field
breaks the address, so nothing is ever overwritten in place.

### `LedgerChain.build()` / `validate()`

- every ledger-schema ref resolves to a retained record whose fingerprint equals
  the ref's `integrity_sha256`; a missing or mismatched ref is rejected;
- **monotone chronology**: a record cannot precede any record it derives from;
  authorization ≥ intent, execution start ≥ decision, verification ≥ execution
  finish, outcome ≥ verification;
- **supersession never overwrites**: `supersedes_record_id` must name a
  retained record of the same kind, older or equal, never superseded twice
  (no forks), never an approved goal; `chain.heads` is the current view,
  `chain.records` keeps everything;
- **privacy only escalates**: a record's `privacy_class` cannot fall below the
  highest class among its sources;
- intents fall inside an **approved** goal's scope and deadline;
- executions beyond `queued` rest on a `grant`; nothing follows a `deny`;
- **"ran" ≠ "verified"**: `ExecutionRecord.status="done"` and
  `VerificationRecord.verdict="verified"` are distinct records, `summarize()`
  reports them separately, and a `confirmed` outcome cannot rest on an
  unverified verification;
- external refs (`nerva.decision.v1`, `nerva.mediation.receipt.v1`,
  `nerva.reality.run.v1`, `nerva.benchmark.v1`, `nerva.outcome-observation.v1`,
  audit rows) are listed in `chain.unresolved` and bound only when the caller
  passes their fingerprints to `validate(external=...)`.

`load_record` / `load_chain` rebuild records from canonical payloads and reject
unknown or missing keys, boolean timestamps, forged authority flags and any
`record_id` that no longer matches the content.

## Evidence (hermetic)

`tests/test_nerva_cognitive_ledger.py` (8 tests) builds the chain over a real
`ShadowDecisionRouter` record, a real `issue_receipt()` receipt sealed with a
detached HMAC, and a real `compare_outcome()` observation; it covers broken and
tampered refs, supersession retention / fork / frozen-goal, privacy escalation,
forged `grant`, receipt/intent binding, immutable authority flags, stable
fingerprints, loader rejections, and the ran-vs-verified distinction.

Red-proof: with the forged-grant guard disabled,
`test_forged_authorization_is_rejected` fails with `DID NOT RAISE`.

## What this is not

No persistence (no SQLite store, no data path), no route, no HUD panel, no
kernel action kind, no flag, no production caller. Wiring a writer (E5 work
runs, E10 experience cards, E11 evidence receipts) is separate work with its
own rollback decision. `DecisionRecord`, `MediationReceipt` and
`OutcomeObservation` are referenced by digest, never duplicated.

## Rollback

Delete `agents/core/cognitive_ledger.py`, `tests/test_nerva_cognitive_ledger.py`
and this document; revert the `docs/ARCHITECTURE.md` §3 row and the BACKLOG
program-control row. Nothing else imports the module.
