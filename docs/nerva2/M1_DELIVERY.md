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

## Current candidate

- E1.1 / #792 adds a privacy-safe current-router comparison baseline.
- It remains evaluation-only and does not add persistence, scoring authority,
  execution authority or an E1 completion claim.

## Dependency posture

- #781 Atlas, #783 Synapse and #784 Research Lab remain separately eligible.
- #782 Episodes remains blocked only by #781.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.

## Remaining E1 evidence

- bounded fallback behavior for a future selector;
- route-level measured cost, latency and outcome quality;
- at least 20 representative real Nerva tasks that beat or match the current
  router without safety regression;
- an independently reviewed selector decision before any production adoption.
