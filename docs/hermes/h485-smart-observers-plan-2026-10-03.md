# H485 smart guardian observer integration

Goal: deliver Hermes' observer-only pre-request and committed approve/deny events
through Nerva's consented sandbox extension runtime, without an authorization
return channel. Base/head before changes: `1459916af2e09b6f2ea0c9f46163390a5350882b`.
Generated 2026-10-03. Reference: pinned Hermes `59b2aeef6c7a`,
`tools/approval_smart.py:134-155`. This is the next H485 integration step; the
full 697-capability objective is unchanged. Local only: no publication, provider
spend, runtime activation or deployment.

The previous turn made verified progress: local checkpoint 1459916a and
21,564 backend passes. Current checkout is clean and the wiring graph is fresh.

## Design and trust boundaries

- Add `approval.smart.requested` and `approval.smart.decided` to the existing
  manifest event allowlist and event bus. Existing extension declarations remain
  valid; subscribing to either new event changes the consented manifest scope.
- Payload: random per-inference `request_id`, constant `surface=smart`, bounded
  redacted `command` and `description`. The post event additionally carries only
  `choice=smart_approve|smart_deny`, `decided_by=aux_llm`. No prompt, operator
  policy, model answer, provider/key, execution receipt or principal is included.
- Force the existing SecretScanner and credential/identifier CatalogueScanner
  on the complete bounded text before the
  existing 200-character field limit. Logging-redaction opt-out cannot disable
  this boundary. Pattern scanning is not a guarantee against arbitrary opaque
  secret literals or private prose/paths; the declared subscription explicitly
  includes these sanitized text fields. Do not claim zero-sensitive-data proof.
- A request event denotes a validated send attempt, not proven remote receipt.
  It is assembled/emitted only after native physical request
  identity/direct transport and live authority checks. Static policy DENY,
  advisory calls and failures before that boundary produce no model request event.
- A fresh per-judgement ContextVar scope with a mutable holder crosses the
  wait_for child task and parent durable store. Only the corresponding exact
  committed nonadvisory APPROVE/DENY produces a response event. Revoked/stale,
  duplicate, invalid and ESCALATE results do not. At most one request event per
  inference, even when a backend retries physical transport.
- Preparation/emission/delivery failure skips observation, preserving decision
  and all execution gates. Static logs contain no exception or source text.
  Delivery uses a fresh context; observer return/output cannot affect authority.
  Existing timeout, pending cap, consent, package pin and sandbox checks remain.

## Ownership and verification

One Sol/high implementer owns `autonomy/smart_observers.py`, `approval_judge.py`,
`advisory_judgements.py` and new native-dispatch tests. Root owns extension
`events.py`, `manifest.py`, event-payload tests, integration/records and review.
One Sol/high read-only reviewer checks privacy, correlation and revocation.
No agent delegates. No shared file writers.

1. Red-first bus tests: new declaration/delivery, useful sanitized text when log
   masking is disabled, secret crossing truncation, bad types/enums/keys, redactor
   failure and fresh delivery context. Preserve prior event shapes.
2. Red-first actual SQLite/TaskApprovalJudge/native HTTP tests: pre precedes
   dispatch; post follows accepted CAS; concurrent correlation; static DENY,
   ESCALATE, provider failures, revocation, stale snapshots and preparation
   failures; signed authority and manual owner behavior unchanged.
3. Focused authority/extension suites, independent review, global Ruff/Bandit,
   isolated source mutations for omission/wrong post and privacy boundaries.
4. Frozen complete backend milestone, source graph rebuild/check, truthful
   status/document-reference/count gates, exact staged secret scan/local commit.
   Frontend/mobile are unchanged; count reuse is explicit, not a fresh test run.

Rollback: revert this additive observer integration; no task/result/receipt
schema, signing bytes, grant or policy changes. H485 remains partial until the
broader synchronous shell/script, native/mobile and live acceptance requirements
are verified. Prior exclusions remain in the full goal; historical extension
docs calling them excluded must be corrected where this slice touches them.

Next action: implement the agreed contracts from independently failing tests,
then run bounded integration and authority regressions before the full milestone.

## Source-frozen focused verification

Initial bus proof: six absent-feature failures, ten invalid-field refusals already
passing. Initial native proof: eight absent-observer failures. Credential-catalogue
probes then reproduced four failures before adding forced catalogue scanning.
Root additionally reproduced transient parent entropy failure: wait_for's child
could reopen observation and emit an unmatched pre. A disabled scope marker now
propagates that failure without changing the committed verdict or slot release.

38 new cases pass (20 bus/field/privacy, 18 real queue/native transport). Combined
94-module H277/H513/H485/extension/catalogue regression: **2428 passed**, seven
warnings. Nine isolated observer mutants are assertion-killed, none survives or
is invalid; restored 38-case baseline passes and exact hashed sources remain
unchanged. Global Bandit 1.9.4 with the unchanged workflow baseline has zero
findings/errors; Ruff and whitespace checks pass. Independent Sol/high read-only
review found no actionable issue before the bounded parent-failure correction.

Twelve parent-current Hermes rows are reread; existing verdicts are preserved.
The H409 declaration citations are explicitly remapped to the reviewed AST ranges.
Historical active-exclusion wording and H571's stale claim that dispatch/events
are absent are corrected without claiming distribution/pack installation parity.
Graph rebuild/freshness and complete backend milestone are required next.
Frontend/mobile counts are reused explicitly; their tests were not rerun.


## Final complete-suite checkpoint

Complete frozen backend: **21,602 passed, 34 skipped, one xfailed**, 67 warnings,
1,119.27 seconds, exit zero. All eight source/test/harness hashes match after
completion. Graft build/check passes; current wiring graph, no semantic layer.
The 180 record/document/count cases pass at the frozen checkpoint.
See [complete verification report](evidence/h485-smart-observers-verification-2026-10-03.md).
H485 remains partial with no new equivalence credit. Next: bounded same-turn
terminal review/notification hold, then broader shell/script and live/native
acceptance; preserve every signed receipt, cancellation/revocation and floor.
