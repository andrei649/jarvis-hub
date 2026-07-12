# H28.2 Action-Hierarchy Router — Design

## Goal

Given a bounded goal and a trusted catalog of implementations, deterministically select
the lowest-risk available route in this fixed order:

`API → CLI → structured UI → visual computer use`.

## Non-goals

- No direct execution. The selected implementation remains responsible for using the
  Unified Action API, governed terminal, `GovernedBrowser`, or `GovernedDesktop`.
- No LLM classification, endpoint, HUD surface, or new capability manifest.
- No risk-tier lowering and no promotion of SEAM/unknown capabilities.

## Model

`OperatorImplementation` is trusted registration metadata: stable id, route class,
capability id, deterministic matcher, availability probe, and within-route priority.
`ActionHierarchyRouter` validates unique ids and reads readiness from an injected registry
provider. Candidates are eligible only when the capability exists at WIRED/VERIFIED/GA,
the availability probe is true, and the matcher accepts the goal/params. Probe exceptions
fail that candidate closed.

Selection sorts by fixed route rank, then explicit non-negative priority, then id. Visual
implementations are excluded unless `allow_visual_fallback=True`, even when they are the
only match. This makes visual an explicit fallback rather than a planner default.

## Audit and privacy

Every decision appends a bounded in-process audit record before returning. The record
contains goal SHA-256 + length, selected implementation/route/capability, opt-in state,
and rejection reasons. It never stores raw goal text or params. An optional external sink
receives a copy; sink failure is recorded but cannot erase the internal trace. The audit
ring has a configurable maximum and drops oldest entries.

## Tests

- API wins over all higher routes regardless of registration order.
- CLI and structured UI are selected only when lower routes fail closed.
- Visual is refused by default and selected only with explicit opt-in.
- Missing/SEAM registry rows, provider/probe/matcher exceptions, and duplicate ids fail
  closed without disturbing eligible alternatives.
- Audit records are bounded, deterministic, and contain no raw goal/params.
- The decision is selection metadata only; no handler/execution surface exists.

## Rollback

Remove the router and tests. No existing execution path or registry behavior changes.
