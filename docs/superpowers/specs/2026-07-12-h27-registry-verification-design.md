# H27.5 Registry Verification — Design

## Goal

Complete the live verification field for the 70 non-executable boot-snapshot
capabilities: 33 plugins, 24 components, and 13 skills. Every registry verification
reference must resolve to exactly one executable `RealityCase`, and only the existing
`run_reality()` path may record a promotion.

## Non-goals

- No network calls, external credentials, or fabricated service success.
- No durable cross-process VERIFIED state; V3 remains the owner of committed readiness.
- No attempt to make the intentionally manifest-only `skill:Weather Intel` wired.
- No new endpoint or HUD/mobile surface.

## Design

Add stable plugin/component/skill case-name and verification-ref helpers beside the
existing action/tool helpers. Add `registry_reality_cases(orch)` to generate cases from
the same live sources used by `capability_registry.build_records(orch)`.

- **Plugins:** construct the real `PluginHTTPClient` for each built-in manifest and call
  its real `_enforce_egress` boundary without opening a socket. `NONE` must block an
  external IP; `LAN` must allow loopback and block an external IP; `RESTRICTED` must
  allow a declared domain and block an external IP; `FULL` must allow the external IP.
- **Components:** capture the real boot registry status and owner attribute. A case is
  green only when status is `ok` and the constructed attribute is non-null.
- **Skills:** capture the real discovered skill object. A case is green only when the
  skill still exists in the loader and has a loaded module.

The dynamic cases carry one capability id and one stable ref each. Existing specialized
rail cases remain in `CASES`; the new canonical registry cases are returned separately
because they require a booted orchestrator. `all_reality_cases(orch)` provides the full
run set while preserving the fast static `CASES` API.

## Safety and failure semantics

- Case generation is deterministic and rejects duplicate refs or capability ids.
- Plugin probes force strict egress locally and restore the caller environment.
- Probe exceptions are failures through the existing runner, never promotions.
- `SEAM` component/skill cases remain executable but red; even a stray green verdict
  cannot promote a SEAM because the registry already enforces that invariant.

## Tests

1. Exact 33/24/13 case counts from a real cached booted orchestrator.
2. Every registry ref resolves one-to-one to the matching capability id.
3. All WIRED plugin/component/skill cases pass hermetically.
4. The intentional Weather Intel seam fails and remains SEAM after a promoted run.
5. A broken component/object mismatch and missing skill module fail honestly.
6. Existing action/tool, reality-harness, readiness-matrix, plugin egress, loader, and
   capability-registry suites remain green.

## Rollback

Revert the generated-case helpers and tests. Registry readiness derivation and the
existing action/tool cases remain behaviorally unchanged.
