# H27.1-H27.3 Capability Registry and Unified Action API Design

## Goal

Finish the P0 foundation of ORIZONT 27 without creating a second capability system:
extend the existing O24 readiness registry with an executable schema, describe every
kernel-mediated action and governed plugin, and expose one default-off `perform()` path.

## Non-goals

- No model-directed capability selection (H27.4).
- No durable verification promotion, rollback execution, or earned-autonomy policy
  (H27.5-H27.7).
- No new HTTP route or HUD surface (H27.8).
- No unparked browser, desktop, media, training, or Rust work.
- No refactor of every existing broker into a new execution framework.

## Ground truth and scope reconciliation

The runtime action-auth registry is authoritative. It currently contains 12
kernel-mediated patterns, although the backlog text says 11. H27.2 covers all 12 and
adds a drift test so a future action cannot exist without a manifest. Wildcard kinds
(`social.*`, `writeback.*`) remain patterns in the manifest layer and match concrete
actions through the existing `kernel.registry.classify()` semantics.

## Architecture

### 1. Manifest layer

Add `agents/core/capability_manifests.py` with a frozen `CapabilityManifest` and a
curated `ACTION_CAPABILITY_MANIFESTS` mapping. Each manifest carries:

- `description`
- JSON-schema-like `inputs`
- `risk`
- `requires`
- `supports`
- `verification`
- `rollback`
- `confidence` in `[0, 1]`
- `implementation`
- optional `contract_ref`
- the concrete or wildcard `action_kind`

Action manifests are explicit because their risk and rollback stories are product
decisions. Plugin capability metadata is derived from the existing
`plugin_gate.PluginManifest`; network and data-scope policy remains single-sourced.
The derivation is deterministic and conservative: transmitted/full-network plugins
receive a higher risk label than local/LAN plugins, disabled plugins have zero
confidence, and every plugin rollback is disablement.

### 2. Registry v1

Extend `observability.capability_registry.CapabilityRecord` with the v1 fields while
retaining the existing readiness and verification fields for compatibility. The
registry continues to derive plugins, components, and skills from their current
sources, and additionally derives `action:<pattern>` records from the action manifests.

Components and skills without richer native manifests receive explicit conservative
defaults rather than invented guarantees. Existing verification promotion and manual
demotion rules remain unchanged. The existing `/api/metrics/capabilities` response is
enriched automatically; no route is added.

### 3. Unified action facade

Add `agents/core/capability_actions.py`:

- `CapabilityActionAPI.register()` binds a capability id to an async or sync handler.
- `perform(capability_id, params, ctx)` validates the flag, manifest, input shape,
  handler, and mediation mode, then returns a stable `PerformResult`.
- `facade` mediation calls the injected kernel exactly once. `DENY` becomes
  `refused`, `QUEUE` becomes `queued`, and only `GRANT` invokes the implementation.
- `delegated` mediation is for existing brokers and ToolRPC paths that already call
  the kernel. It is accepted only when the action kind is classified `KERNEL`, avoiding
  both bypasses and double authorization.
- `register_broker()` and `register_tool_rpc()` are narrow convenience adapters over
  the same registration primitive.
- `JARVIS_UNIFIED_ACTION_API=1` is required. With the flag absent, `perform()` returns
  `disabled` and invokes neither kernel nor handler.

The facade accepts dependencies by injection. It does not import the orchestrator or
construct global brokers, which keeps tests hermetic and prevents a second lifecycle.

## Data flow

1. Caller supplies a capability id, parameters, and bounded execution context.
2. The facade checks the opt-in flag and resolves the current manifest.
3. Parameters must be a mapping and must satisfy the manifest's required input keys.
4. For facade-mediated bindings, the facade creates the existing kernel `Action` and
   calls the injected authorizer. Only `GRANT` reaches the handler.
5. For delegated bindings, the facade verifies the action kind is classified as
   kernel-mediated, then calls the broker/ToolRPC adapter, which owns authorization.
6. Exceptions become a redacted `failed` result; raw parameters, secrets, and host
   details are never copied into the result.

## Error and safety contract

- Unknown capability, missing handler, malformed params, missing required inputs, and
  invalid delegation fail closed without invocation.
- Disabled mode is distinguishable from denial.
- Kernel decision reason and tier may be returned; handler exception text is not.
- Confidence is descriptive in this wave and cannot lower an approval tier.
- An `IRREVERSIBLE_OR_MONEY` capability cannot bypass kernel mediation.

## Tests

- Registry schema serialization, validation, conservative defaults, and compatibility.
- Exact equality between action-auth kinds and action manifests.
- Every governed plugin produces complete v1 metadata.
- Default-off no-op; unknown/malformed/missing-input failures.
- Facade mediation: single authorize call, deny/queue do not execute, grant executes.
- Delegated mediation: only `KERNEL` kinds accepted and no double authorize.
- Broker and ToolRPC adapter behavior with real facade boundaries and hermetic fakes.
- Existing capability-registry, action-auth, kernel, ToolRPC, route/OpenAPI/auth, and
  lifespan regression suites.

## Rollback

Revert the batch commit. The new flag defaults off, the endpoint shape is additive,
and no persistent schema or migration is introduced.
