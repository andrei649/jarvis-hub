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

## Dependency posture

- #781 Atlas is accepted and closed through PR #794.
- #782 Episodes is `NOT STARTED · ELIGIBLE` for one bounded typed
  episode/manual-boundary package.
- #783 Synapse and #784 Research Lab remain separately eligible.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Remaining E1 evidence

- bounded fallback behavior for a future selector;
- route-level measured cost, latency and outcome quality;
- at least 20 representative real Nerva tasks that beat or match the current
  router without safety regression;
- an independently reviewed selector decision before any production adoption.

## Remaining M1 evidence

- E8.0 Synapse manifest and conformance evidence;
- E9.0 versioned benchmark contract and first privacy-safe task suite;
- cross-cutting Goal/Evidence/Outcome/Cognitive-Ledger records;
- a real request replayed over truthful Atlas state and declared capabilities
  without performing an external action.

## Next coherent package

Build #782 as a separate E3.0 PR containing the typed episode value contract,
deterministic manual open/settle/merge/split operations, source-reference and
deletion-lineage tests, and coherent rollback documentation. Keep learned
boundary detection, Reflection, production recall changes and action authority
out of that package.
