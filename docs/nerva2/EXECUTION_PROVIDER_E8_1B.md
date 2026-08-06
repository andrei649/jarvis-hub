# Nerva E8.1b — provider-neutral execution contract

Status: contract-only candidate for issue #835. This slice defines
`nerva.execution-provider.v1`; it does not register, import, select or execute a
provider. Hermes remains only the first candidate named by the accepted E8.1a
discovery.

## Goal

Give Synapse and later adapters one strict, provider-neutral vocabulary for:

- provider identity, exact version/revision, declared capability IDs and
  environment/lifecycle requirements;
- bounded execution requests;
- provider-local, still-unverified results;
- evidence-qualified health and reliability snapshots.

The contract is an additive value layer over accepted Nerva boundaries. It is
not a second capability registry, execution router, Action Kernel, sandbox,
verification store or benchmark system.

## Explicit non-goals

This slice adds no:

- Hermes dependency, source copy, manifest enrolment or adapter;
- provider registry, discovery service, runtime factory or production route;
- network connection, subprocess, filesystem mutation, credential resolution or
  upstream execution;
- Action Kernel decision, approval, completion, capability promotion or
  canonical Atlas/Episodes write;
- endpoint, HUD/mobile surface, migration, setting or default-on behavior;
- reliability, compatibility, security or E9 benefit claim for Hermes.

## Contract records

All top-level records use `schema="nerva.execution-provider.v1"`, deterministic
Nerva-side JSON and a SHA-256 fingerprint over the complete serialized record.
The encoding uses UTF-8, sorted object keys, compact separators and finite JSON
numbers. Deserialization rejects unknown or missing fields, duplicate object
keys, non-string wire values and oversized/deep envelopes rather than guessing
defaults.

| Record | Purpose | Important boundary |
|---|---|---|
| `ProviderDescriptor` | Exact provider identity/revision, existing Synapse capability IDs, environment requirements and lifecycle support | Description only; capability IDs never grant permission |
| `ExecutionRequest` | Descriptor revision/fingerprint, JSON inputs plus exact environment, budget, lifecycle and external-verification policy | An inert bounded request; not an authorization token |
| `ExecutionResult` | Descriptor-bound provider-local status, output, usage, checkpoint, partial-effect, evidence and artifact references | Fixed `verification_status="unverified"`; `succeeded` is not Nerva completion |
| `ProviderHealthSnapshot` | Descriptor-bound, evidence-qualified readiness and reliability state | Health cannot promote or mark work complete |
| `ExecutionProvider` | Structural `Protocol` for a future adapter | No implementation or registration exists in this slice |

Nested policies remain frozen typed values:

- `SandboxPolicy` accepts only the existing isolated `docker` and `wasm`
  backend identities. `subprocess-host` is not representable in v1.
- `FilesystemPolicy` carries bounded opaque `artifact:*` / `workspace:*`
  references, never host paths. Writes are confined to `workspace:*` refs.
- `NetworkPolicy` is deny-by-default. An allowlist accepts canonical HTTPS
  origins, plus HTTP only for canonical loopback origins. Wildcards,
  credentials, paths, queries and fragments fail closed.
- `EnvironmentPolicy.secret_refs` accepts exact `{{secret:name}}` handles only.
  The record fixes `secret_values_serialized=false`; Nerva remains responsible
  for any later just-in-time resolution behind approval.
- `ExecutionBudget` uses bounded integers for wall time, cost in currency
  microunits, tokens and retries. Booleans are not accepted as integers.
- `ExecutionLifecycle` names opaque idempotency, cancellation and checkpoint
  references plus `none`, `report` or `compensate` partial-effect semantics.
- `VerificationPolicy` requires external verifier/evidence declarations and one
  native rollback reference.

References use field-specific namespaces (`request:`, `idempotency:`,
`cancellation:`, `checkpoint:`, `verifier:`, `rollback:`, `evidence:` and
`artifact:`) so one resolver handle cannot be substituted for another.
Provider and executable capability IDs are bounded exact IDs; wildcard patterns
are not executable identities.

JSON input/output values are copied and recursively frozen. The same limits are
applied to the complete top-level envelope on construction and load. Non-JSON
values, non-string object keys, duplicate fields, NaN/Infinity, payloads deeper
than 16 levels, more than 1,024 values or more than 65,536 canonical UTF-8 bytes
fail before a record is accepted.

## Authority boundary

Every descriptor, request, result and health snapshot fixes these fields through
non-init dataclass values and verifies their exact JSON boolean types on load:

```text
grants_authority=false
can_authorize=false
can_approve=false
can_mark_complete=false
can_write_canonical_state=false
requires_external_verification=true
```

Integer/string lookalikes such as `0`, `1`, `"false"` and `"true"` are rejected.
A provider result can report only what the provider observed. Even
`status="succeeded"` remains unverified candidate evidence. Verification Fabric
must produce separate evidence before any Nerva consumer may promote an outcome.

The serialized request deliberately carries no `nerva.action.v1` decision or
receipt as a bearer credential. A later executable adapter must receive a
trusted, Nerva-side execution context at its invocation seam and validate the
persisted Ultron decision there. The provider never becomes the authority or
the validator of its own authority.

## Binding and lifecycle rules

`validate_request_against_descriptor()` rejects provider identity/version
drift, source-revision or complete descriptor-fingerprint drift, undeclared
capability IDs, a widened environment or unsupported cancellation, checkpoint,
idempotency and partial-effect semantics.

Retries require an idempotency key. A future adapter may not infer idempotency
from an operation name. Cancellation and checkpoint handles are opaque contract
references; this slice does not create a cancellation service or checkpoint
store. In v1, a request checkpoint handle is the exact output handle authorized
for that invocation, not an implicit resume handle. A result may return it only
when it exactly matches the request. A future resume protocol requires a new,
explicit field/schema.
The structural `cancel()` seam receives the typed request, retaining its
cancellation handle and descriptor binding; it does not accept an unbound ID.

`validate_result_for_request()` binds untrusted output to the exact request ID
and fingerprint, provider identity/version, declared capability/environment,
budget and required evidence kinds. It also rejects:

- consumption above any request budget;
- a cancelled result when the request exposed no cancellation reference;
- a checkpoint when the provider declared no support, the request supplied no
  checkpoint handle, or the returned handle differs;
- partial effects outside the request's declared mode;
- a partial result without an explicit possible/reported effect state and
  rollback requirement.

Status values are provider-local only:

- `succeeded` — the bounded provider invocation reported success, with no
  provider error or partial effect;
- `failed`, `cancelled`, `timed_out` — require a canonical error code and retain
  negative evidence;
- `partial` — requires an error, a non-empty effect state and rollback.

Result and health timestamps use one fingerprint-stable spelling: UTC RFC 3339
at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`). Offset, basic, space-separated
and fractional variants are rejected rather than hashed as aliases.

## Health and measured reliability

`ProviderHealthSnapshot` represents `unknown`, `ready`, `degraded` or
`unavailable`. Every non-unknown readiness state requires evidence references;
`unavailable` also requires an error code.

Reliability remains explicitly one of:

- `measured` — finite ratio in `[0, 1]` plus source and evidence references;
- `not_measured` — no value or implied evidence;
- `failed` — no numeric value, but retained measurement source and failure
  evidence.

This structure can later receive E9 evidence; this contract itself measures
nothing and does not import the benchmark implementation.

## Existing boundaries reused

```text
provider capability IDs  -> nerva.capability.v1 / Synapse (description only)
future invocation        -> future adapter over ToolRPC + existing sandbox
privileged effect        -> Ultron / nerva.action.v1 (unchanged)
provider-local result    -> external Verification Fabric
provider comparison      -> E9 evidence lanes
```

The contract module imports none of ToolRPC, sandbox, Action Kernel, capability
actions, the Hermes importer or any provider code. Importing it performs no IO
and creates no runtime singleton.

## Security checks

The focused suite covers:

- schema/kind/unknown-field and authority/verification forgery;
- duplicate-key, full-envelope size/depth/item and non-string wire attacks;
- non-canonical provider, capability, source and opaque references;
- boolean lookalikes, duplicate or unsorted declarations;
- hostile JSON, NaN/Infinity, size/depth/item limits and post-construction
  mutation;
- plaintext/malformed secret references, unsafe network origins and host/path
  escape attempts;
- budget, retry/idempotency, checkpoint/cancellation and lifecycle
  contradictions;
- status/error/chronology, partial-effect and rollback contradictions;
- provider/request/result/health identity, fingerprint, capability, evidence and
  budget drift;
- readiness without evidence, fabricated reliability and completion claims;
- import-time absence of runtime/provider modules.

## Compatibility and rollback

This is additive code and documentation. No accepted runtime imports the new
module, no persistent schema changes, and native execution remains byte-for-byte
unchanged. Strict v1 serialization has no legacy consumers to migrate.

Rollback removes `agents/core/execution_provider_contract.py`, its focused test
and this document, then reverts the factual E8.1a status reconciliation. There
is no provider state, imported dependency, database record, route or canonical
outcome to recover.

## Residual risks and later gates

- The contract can prove that `secret_refs` are handles; it cannot prove that an
  arbitrary user input string contains no sensitive data. A later adapter must
  enforce privacy/data-minimization and output scrubbing at the trusted seam.
- Policies are declarations until an adapter binds them to the actual sandbox,
  network, filesystem and secret broker.
- An opaque evidence/artifact/checkpoint reference proves syntax, not existence,
  authenticity or ownership.
- Fingerprints are produced at the trusted Nerva-side adapter boundary and
  echoed as opaque bindings. V1 does not claim RFC 8785/JCS interoperability;
  external providers must not independently re-derive fingerprints from their
  own number serializer.
- Descriptor revision/fingerprint fields bind declarations but do not attest
  which binary actually executed. A later adapter needs signed provenance and
  sandbox observation.
- Health snapshots remain evidence records, not freshness decisions. A runtime
  consumer must enforce trusted-clock expiry/replay policy before use.
- Provider signatures remain intentionally absent; E8.1a found no stable Hermes
  public API, so E8.1c must bind one pinned upstream surface behind a thin
  adapter and compatibility tests.
- B7 task-persisted Ultron mediation and E9 measured comparison remain blockers
  for live effects or promotion, not for this inert contract.

## Next coherent package

After independent exact-head acceptance of issue #835, E8.1c may implement one
separately revertible Hermes adapter against a pinned interface in synthetic,
isolated shadow mode. Manifest enrolment, dual GitHub/PyPI drift, transitive
supply-chain review, provider-specific E9 comparison, production routing and
promotion remain separate gates. No later package may weaken the fixed authority
ceiling or external-verification requirement.
