# H28.2 Action-Hierarchy Router — Implementation Plan

1. Add red tests for route precedence, readiness filtering, visual opt-in, failure isolation,
   deterministic tie-breaking, and privacy-safe bounded audit.
2. Implement the pure selection model and router against an injected capability provider.
3. Run H27 registry/planning plus H28 browser/router tests, lint, compile, and Bandit.
4. Rebase after #669, update H28.1/H28.2 backlog and generated status, then ship both as
   one coherent operator-core batch PR.
