# Nerva 2.0 M1 delivery snapshot

Status date: 2026-08-03

This post-E0 snapshot is additive. The immutable E0 marker blocks in
`BACKLOG.md` and `STATUS.md` remain historical closure evidence.

## Accepted

- E0 is `DONE`.
- E1.0 / #780 / PR #791 is accepted on `main` as
  `9235ef69961862df49826a910be00955d7be420e`.
- `nerva.decision.v1` and the failure-isolated `ShadowDecisionRouter` are
  observation-only and do not alter production routing.
- E1.1 / #792 / PR #793 is accepted on `main` as
  `e244ea7c9e32673bdb56fe1459f355a7abb9d63f`.
- `nerva.cortex.comparison.v1` is an evaluation-only regression baseline; it
  does not add persistence, production selection or action authority.
- Normalized request digests are pseudonymous/linkable and remain subject to
  access, retention and deletion controls for `redacted_local` evaluations.
- E2.0 / #781 / PR #794 is accepted on `main` as
  `f2901528e452586f9702c7df1678e72ca36ca2ee` from exact reviewed head
  `f01b13e354eb64504d7996cc4d87d4828ae74330`.
- `nerva.observation.v1` projections and deterministic
  `nerva.atlas.snapshot.v1` snapshots are now accepted read-only substrate over
  the existing `BiTemporalKG`.

## E2.0 accepted contract

- Queries declare requested privacy classes, while a trusted
  `AtlasAccessAuthorizer` issues the effective grant before any source-store
  read. Requested scope alone never authorizes access.
- Legacy facts default to `private_local` privacy and `unknown` confidence;
  explicit resolvers may narrow or qualify those values but cannot silently
  treat missing metadata as public or measured.
- Compatibility entity IDs are source-scoped so differently sourced subjects
  are not silently merged before an explicit identity-resolution contract.
- Snapshot construction rejects non-observations, failed integrity, duplicate
  IDs and values outside the requested/granted query scope.
- E2.0 does not add a database, migration, mutation endpoint, production
  authentication, cross-connector identity merge, deletion executor or live
  three-domain claim.

## Historical transition rule — satisfied

Repository placement determines delivery state. Under the pre-integration rule, #781 remained transition evidence and #782 becomes eligible when the exact reviewed E2.0 head lands on `main`. That condition was satisfied by PR #794 and merge `f2901528e452586f9702c7df1678e72ca36ca2ee`; this wording is retained only as historical transition evidence, not as the current dependency state.

## E3.0 transition evidence

- The accepted E2.0 Atlas contract makes #782 eligible.
- E3.0 / #782 defines a typed `nerva.episode.v1` value contract and
  deterministic manual open, settle, consolidate, correct, merge, split and
  source-tombstone operations.
- Episode constructors store content-free source metadata and do not
  automatically copy source payloads or transcripts. Caller-supplied bounded
  derived assertions remain privacy-governed; the contract does not claim
  semantic transcript detection.
- Direct assertions retain evidence references. Low-confidence inference cannot
  enter settled or consolidated history without explicit measured confidence.
- Manual mutations emit deterministic integrity-checked audit events and exact
  immutable rollback values. Plain SHA-256 detects changed or corrupted content but
  does not authenticate a signer or provide non-repudiation. Merge and split remain
  atomic multi-record mutations.
- The included situation/outcome query is a focused fixture only. It selects one
  deterministic current revision per logical episode before scoring, rejects
  conflicting same-revision forks, and does not change production recall or
  establish a performance claim.
- Repository placement is transition evidence until independent integration of
  one exact head with required exact-head CI and resolved review concerns.

## Dependency posture

- #781 Atlas is accepted and closed through PR #794.
- #782 Episodes is the active bounded E3.0 transition after accepted Atlas E2.0.
- #783 Synapse and #784 Research Lab remain separately eligible.
- E3.0 is independent of those streams and does not change their dependency or
  authority boundaries.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.
- The E0 blocks in `BACKLOG.md` and `STATUS.md` remain immutable historical
  closure evidence; this delivery snapshot carries current post-E0 movement.

## Remaining E1 evidence

- bounded fallback behavior for a future selector;
- route-level measured cost, latency and outcome quality;
- at least 20 representative real Nerva tasks that beat or match the current
  router without safety regression;
- an independently reviewed selector decision before any production adoption.

## Remaining M1 evidence

- independent integration of the E3.0 typed episode/manual-boundary candidate;
- E8.0 Synapse manifest and conformance evidence;
- E9.0 versioned benchmark contract and first privacy-safe task suite;
- cross-cutting Goal/Evidence/Outcome/Cognitive-Ledger records;
- a real request replayed over truthful Atlas state and declared capabilities
  without performing an external action.

## Beyond this candidate

E3.0 does not complete Episodes. Measured retrieval against the current memory
baseline, learned boundary detection, durable persistence, Reflection/lesson
integration, production recall adoption, deletion execution and broad memory
migration remain separate work packages with separate rollback decisions.
