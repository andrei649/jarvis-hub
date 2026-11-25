# ADV-087 / ADV-098 reality-proof evidence

**Date:** 2026-08-12  
**Environment:** Windows, repository virtual environment  
**Scope:** Hermetic readiness and reality-harness verification; no hardware or live service

## Verdict

**FIXED-SINCE.** PR #897 already made action-capability probes resolve the actuator
declared by `manifest.implementation`, fail closed when it is absent, and identify the
certified implementation in result metadata. This run closes the remaining matrix defect:
`PENDING_VERIFY` now has to exactly match the coverage gaps computed from readiness records
and registered reality cases.

A record at `wired`, `verified`, or `ga` counts as covered only when its declared
verification reference resolves to exactly one case for the same capability and that case
is allowed to promote readiness. Missing, duplicate, capability-mismatched, and explicitly
non-promotable cases remain gaps with distinct reasons.

## Red reproduction

The new targeted tests failed before implementation because
`reality_coverage_gaps` did not exist. The readiness matrix's empty escape set therefore had
no executable derivation from the proof registry.

## Green evidence

```text
targeted coverage gate tests
2 passed

capability verification + readiness matrix + reality harness + registry + manifests
67 passed

adversarial audit probe-tool gate
15 passed; ADV-087 probe CLOSED with implementation resolution true

current readiness measurement
94 records; 93 proof-eligible; 133 cases; 0 gaps
eligible kinds: 38 plugin, 20 action, 24 component, 11 skill
```

One repository-declared skill remains `SEAM` and is intentionally outside proof eligibility.
The test run emitted one existing Starlette/httpx deprecation warning; no test was skipped.

## Boundary

This proves complete case registration for the deterministic readiness-matrix scope. It
does not turn hermetic proof into owner-host evidence, persist in-process verification
across restarts, or clear the A8 hardware gate.
