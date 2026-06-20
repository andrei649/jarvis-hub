# Decision: WorldMonitor as Jarvis Signal Provider

## Status

Accepted for the sprint implementation.

## Context

Jarvis needs external-world situational awareness: geopolitical events, country risk, travel disruption, aviation, cyber, markets, weather, disasters, energy, and infrastructure signals.

WorldMonitor is useful as the first public-world intelligence provider, but Jarvis should not become structurally dependent on WorldMonitor internals.

## Decision

Jarvis will run WorldMonitor as an external sidecar/service and consume it through a `SignalProvider` adapter.

Jarvis will not copy, fork, or deeply modify WorldMonitor code as part of this integration sprint.

## Rationale

- Keeps Jarvis schemas provider-independent.
- Preserves a cleaner licensing boundary.
- Lets Jarvis add future providers without rewriting the WorldView product.
- Keeps the durable layer inside Jarvis: evidence, relevance, assessments, memory, and action policy.
- Enables replay mode for deterministic demos and evals.

## Consequences

- Jarvis must maintain a provider adapter.
- WorldMonitor availability is an operational dependency in live mode.
- All provider outputs must be normalized into Jarvis-owned objects.
- Every user-visible claim must carry evidence, confidence, and freshness state.
