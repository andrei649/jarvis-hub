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
- When this snapshot is present on `main` through merged PR #793, E1.1 is
  accepted as an evaluation-only regression baseline.
- Normalized request digests are pseudonymous/linkable and remain subject to
  access, retention and deletion controls for `redacted_local` evaluations.
- At E1.1 acceptance, #781 Atlas, #783 Synapse and #784 Research Lab remain separately eligible.

## E2.0 candidate transition

- E2.0 / #781 adds typed `nerva.observation.v1` projections and deterministic
  `nerva.atlas.snapshot.v1` read-only snapshots over the existing
  `BiTemporalKG`.
- On a feature branch, these artifacts remain candidate evidence only.
- Independent review and exact-head green CI are required before E2.0 can be
  accepted or #782 Episodes can be unblocked.
- Legacy facts default to `private_local` privacy and `unknown` confidence;
  explicit resolvers may narrow or qualify those values but cannot silently
  treat missing metadata as public or measured.
- Compatibility entity IDs are source-scoped so differently sourced subjects
  are not silently merged before an explicit identity-resolution contract.
- The candidate does not add a database, migration, mutation endpoint,
  cross-connector identity merge, deletion executor or live three-domain claim.

## Dependency posture

- #781 Atlas is the active candidate package.
- #783 Synapse and #784 Research Lab remain separately eligible.
- #782 Episodes remains blocked only by #781 until E2.0 is accepted.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Remaining E1 evidence

- bounded fallback behavior for a future selector;
- route-level measured cost, latency and outcome quality;
- at least 20 representative real Nerva tasks that beat or match the current
  router without safety regression;
- an independently reviewed selector decision before any production adoption.

## Remaining M1 evidence

- independent acceptance of the E2.0 Atlas snapshot contract;
- E8.0 Synapse manifest and conformance evidence;
- E9.0 versioned benchmark contract and first privacy-safe task suite;
- cross-cutting Goal/Evidence/Outcome/Cognitive-Ledger records;
- a real request replayed over truthful Atlas state and declared capabilities
  without performing an external action.
