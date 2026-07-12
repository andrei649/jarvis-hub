# H27.4-H27.5 Registry Planning and Verification Design

## Goal

Make the default-off Agent Runtime select only live, registry-described tools and
attach every executable action/tool verification reference to a real V1 reality case.

## Non-goals

- No rollback UI, confidence policy, new API route, or HUD work (H27.6-H27.8).
- No automatic capability acquisition or generated tools.
- No promotion persisted across process restarts; the committed readiness snapshot
  remains the durable truth and stays WIRED/PENDING_VERIFY in this wave.
- No behavior change while `llm.registry_planning_enabled` is false.

## Tool identity and registry derivation

`ToolRPCServer.register_tool()` gains an optional `capability_id`. The public `tools()`
projection includes it only when declared, preserving exact legacy output for callers
that do not opt in. The production `echo` and `time` tools declare `tool:echo` and
`tool:time`. Declared ids are bounded and unique per server; registry derivation keeps
the earlier canonical source when a tool implements an existing `action:*` record.

The existing capability registry derives `tool` records from `orch.tool_rpc.tools()`.
Their readiness is WIRED because the handler is registered on the live server; risk is
`sensitive` for gated tools and `read_only` for inline tools; confidence begins at 0.0.
Their description/input schema remains single-sourced from ToolRPC registration.

## Registry-aware planning

`AgentToolRuntime` receives two injected callables:

- `registry_enabled()` — backed by the default-false setting
  `llm.registry_planning_enabled`;
- `capability_snapshot()` — returns the existing registry snapshot.

When disabled, metadata and execution remain byte-compatible. When enabled, the runtime:

1. reads the current ToolRPC allowlist;
2. requires each tool to declare a capability id;
3. resolves that id in the current registry;
4. drops SEAM, missing, malformed, or duplicate records fail-closed;
5. builds `ToolSpec` from registry description/input schema and appends bounded
   risk/readiness/confidence context to the description;
6. keeps ToolRPC's gated bit as the execution truth.

The model remains the semantic selector among the filtered ToolSpecs. If no eligible
tool remains, the runtime returns a stable honest-refusal reply before a provider call.
The same filtered name set is enforced again at execution, so a provider cannot call a
SEAM/missing tool by hallucinating a name that was not offered.
The tool-loop master flag and provider `supports_tools` checks stay unchanged.

## V1 verification linkage

`RealityCase` exposes a stable `ref` (`reality-v1:<case-name>`). Add:

- one hermetic case per `action:*` manifest, using the real `CapabilityActionAPI`, real
  `kernel.authorize`, real `AutonomyPolicy`, and a throwaway engaged `KillSwitch`; the
  contract passes only when the action is refused and its handler is never invoked;
- hermetic `tool:echo` and `tool:time` cases using a real `ToolRPCServer` request/response
  path.

Action manifest and derived tool-record `verification` values equal those case refs.
A gate asserts every action/tool record points to exactly one case with the same
capability id. The existing no-fabricated-VERIFIED invariant remains authoritative:
only a green `run_reality()` result may promote a record in-process.

## Failure and safety behavior

- Registry provider errors or malformed snapshots produce the honest refusal and no
  provider/tool call.
- Missing capability ids never fall back to the legacy allowlist while registry mode is
  enabled.
- SEAM capabilities are not offered to the model.
- Reality probes isolate environment and kill-switch files, restore flags, open no
  sockets, and never execute an action handler while the halt is engaged.
- Tool results continue through the existing JSON bounds, secret scrubber, approval
  gate, deadlines, and event sink.

## Tests

- ToolRPC capability-id projection and legacy output compatibility.
- Registry derivation of live tool records.
- Runtime default-off parity, enriched selection, SEAM/missing filtering, malformed
  provider failure, and no-match refusal without backend/RPC invocation.
- All action/tool verification refs match real cases.
- All new action/tool reality cases pass hermetically and promote only through
  `run_reality()`.
- Existing Agent Runtime, ToolRPC, registry, readiness, action-auth, route/OpenAPI/auth,
  and lifespan suites remain green.

## Rollback

Revert the PR. Both runtime behaviors are additive/default-off, with no persistent
schema or route change.
