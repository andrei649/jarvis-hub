# Nerva E1.0 — shadow DecisionRecord

Program: #757 · Epic: #759 · Slice: #780

## Purpose

E1.0 observes the route selected by the existing `IntentRouter` and emits a typed,
replayable `nerva.decision.v1` record. It does **not** select a different route,
authorize an action, execute a tool, or mark work complete.

The implementation is a transparent `ShadowDecisionRouter` wrapper around the
current router. When disabled, no Cortex code is on the routing path. When enabled,
the wrapper calls the existing router first, builds a privacy-minimised record from
its output, hands that record to a supplied writer, and returns the exact same
`Intent` object.

## Data contract

A record contains:

- a digest and length of the normalized request, never unrestricted raw text;
- the sorted set of available agent identifiers;
- the current router source (`wake_word`, `keyword_match`, `llm`, or `general`);
- ordered candidates, selected route and fallbacks;
- measured router score/confidence only when those values actually exist;
- explicit `unknown` or `not_measured` states for quality, risk, privacy, latency
  and cost rather than fabricated estimates;
- typed hard-constraint rejections that are non-overridable by construction;
- fixed authority flags proving that the record cannot authorize, execute or mark
  a task complete.

Canonical JSON is key-sorted and compact. Its SHA-256 digest is the replay
fingerprint. Timestamps are intentionally excluded so the same normalized request,
available-agent state and router output produce the same fingerprint.

## Safety boundary

- Authority remains `route_selection_only`.
- Ultron / `nerva.action.v1` remains the sole privileged-action authority.
- Shadow-writer failures are caught and logged after the current router has made
  its decision; they cannot change or suppress that decision.
- Policy and privacy rejection records are hard constraints, not score penalties.
- No raw private payload is stored by this contract.

## Evidence covered

Existing tests now exercise shadow recording for four current route families:

1. explicit wake-word routing;
2. scored deterministic keyword routing, including ordered fallbacks;
3. optional LLM fallback routing;
4. general Jarvis fallback.

They also pin deterministic fingerprints, honest missing evidence, privacy-minimal
serialization, non-overridable rejection semantics and unchanged returned `Intent`
behavior without adding new collected test cases.

## Migration and rollback

Initial adoption should inject `ShadowDecisionRouter(existing_router, writer)` only
where a bounded trace writer is available. The writer should be local, retention-
limited and provenance-aware. Benchmark shadow records against the existing router
before proposing any scored Cortex selector.

Rollback is immediate: remove the wrapper or stop supplying the writer. The wrapped
router and its public contract are unchanged.
