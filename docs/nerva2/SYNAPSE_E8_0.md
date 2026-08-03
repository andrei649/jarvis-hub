# Nerva E8.0 — Synapse manifest conformance

Program: #757 · Epic: #766 · Slice: #783

## Scope

E8.0 adds a versioned, typed `nerva.capability.v1` descriptor over the capability
metadata that already exists in `agents/core/capability_manifests.py` and
`agents/core/observability/capability_registry.py`. It is a compatibility and
conformance layer, not a second registry, installer, orchestrator, or action-authority
path.

The contract covers:

- typed object input and output schemas;
- preconditions, expected effects, and honest failure semantics;
- required permissions, privacy class, risk, reversibility, and approval floor;
- executor implementation, environments, credentials, and hardware prerequisites;
- verifier declarations and evidence-bounded readiness;
- rollback/compensation metadata;
- reliability, latency, and cost fields that remain `unknown` until measured;
- provenance, maintainer, package trust state, and quarantine status.

## Compatibility adapters

`adapt_capability_manifest()` projects the current immutable `CapabilityManifest`
without changing its behavior or claiming runtime verification. Existing `requires`
and `supports` become the initial preconditions/effects, while missing failure and
telemetry evidence remains explicitly `unknown`. Explicit empty or malformed overrides
are rejected rather than silently replaced with defaults.

Input and output schemas are copied and recursively frozen when the Synapse descriptor
is created. `to_payload()` emits ordinary canonical JSON objects and arrays, so callers
cannot mutate a validated in-memory schema and silently change the later payload.

`adapt_capability_record()` projects a structurally complete current Capability
Registry record. The adapter is deliberately conservative:

| Current registry state | Synapse readiness |
|---|---|
| `missing` | `unknown` |
| `seam` / `wired` | `declared` |
| `verified` / `ga` with dated reality-harness evidence | `hermetic_verified` |

Incomplete or malformed records still fail closed on the required manifest fields. A
CI/reality-harness result is not owner-live evidence. The adapter therefore cannot
produce `live_verified` or `reliable`; those levels require separate owner-live and
measured reliability evidence. When a record is demoted to `seam` or `wired`, stale
harness timestamps are not projected as current Synapse verifier evidence.

The readiness vocabulary is evidence-gated:

- `sandboxed` requires dated `sandbox:`, `reality-harness:` or stronger evidence;
- `hermetic_verified` requires dated `reality-harness:` evidence;
- `live_verified` additionally requires `owner-live:` evidence;
- `reliable` additionally requires measured reliability and a named telemetry source.

Schemas and emitted payloads must be JSON-compatible. Numeric confidence and telemetry
must be finite; booleans are not accepted as numeric evidence. Verification timestamps
use a canonical RFC 3339 profile with a full date, `T`, hours/minutes/seconds, optional
dot-separated fractional seconds, and either `Z` or a colon-delimited numeric offset.
ISO week dates, missing seconds, comma fractions, compact offsets, offset seconds, and
naive timestamps fail closed. Executor implementations use exactly one `module:member`
separator with non-empty, already-trimmed sides; dotted module and member paths remain
valid. These checks prevent invalid values such as `NaN`, implicit coercions, or
non-canonical portable metadata from entering a manifest payload.

## Permission and rollback floors

The contract reuses the existing capability risk vocabulary and will not accept an
approval floor below the minimum for that risk:

| Risk | Minimum approval |
|---|---|
| `read_only` | `none` |
| `reversible` | `session` |
| `sensitive` | `explicit` |
| `irreversible_or_money` | `permanent_owner` |

Rollback metadata continues to reuse `RollbackContract`, while Synapse additionally
requires strict boolean automatic-rollback flags and typed handler/limitation fields.
This describes the recovery promise; it does not execute recovery or grant authority.

## Conformance fixtures

The existing H27 capability-manifest suite now exercises the same contract against
shipped capabilities with different risk and execution characteristics, including:

1. `action:media.present` — reversible actuation with a session approval floor;
2. `action:payment` — restricted, permanent-owner approval;
3. `plugin:weather` — provider-backed read metadata whose missing legacy failure detail
   remains explicitly `unknown` rather than fabricated.

The suite also projects every currently registered action and governed built-in plugin,
so the three acceptance fixtures are not isolated bespoke cases. It does not invoke the
capabilities or claim live reliability. It proves that current metadata can be adapted
and validated without bespoke Cortex wiring or a new execution path.

## Authority and supply-chain boundary

A Synapse manifest **describes** permission; it never grants permission. The contract
fixes `grants_authority=false`, requires `action-kernel` on action descriptors, and
rejects any candidate that claims manifest-level authority, including non-boolean
lookalikes. Ultron / `nerva.action.v1` remains the sole privileged-action authority.

Generated capabilities must remain `quarantined`. Signing metadata may establish
package provenance, but it does not install, promote, authorize, execute, or mark a
capability verified. Current skill signing, quarantine, approval, Action Kernel, ToolRPC,
and verification paths remain authoritative.

## Extension points

A future native manifest may replace adapter defaults by supplying:

- narrower output schemas;
- capability-specific failure codes and partial-effect behavior;
- exact executor environments, credentials, and hardware;
- benchmark/reality-harness evidence references;
- measured telemetry with a named source;
- signed package digest and maintainer provenance.

These additions must remain backward-compatible or ship with an explicit migration and
rollback contract.

## Forbidden shortcuts

- Do not treat descriptions, model output, or manifest fields as permission.
- Do not promote `wired` to verified, CI evidence to owner-live, or signed to installed.
- Do not fabricate reliability, latency, cost, or failure precision.
- Do not coerce malformed registry values or replace explicitly invalid fields with
  adapter defaults.
- Do not lower the approval floor below the declared capability risk.
- Do not let generated or untrusted packages leave quarantine without existing evidence
  and owner/policy gates.
- Do not bypass the current Capability Registry, Action Kernel, approval queue, ToolRPC,
  verifier, or rollback path.
- Do not add auto-install, auto-promotion, production routing changes, or a central
  orchestrator rewrite in E8.0.

## Rollback

E8.0 is additive. Remove `agents/core/synapse_manifest.py`, revert the Synapse assertions
added to `tests/test_h27_capability_manifests.py`, and remove this document. Existing
capability manifests, registry records, execution behavior, signing, quarantine,
authorization, and verification remain unchanged.

## Next package

Bind governed acquisition output to this conformance contract and the separate E9
benchmark contract before any staged promotion flow. Keep acquisition, benchmark
evidence, promotion policy, and action authority independently reviewable.
