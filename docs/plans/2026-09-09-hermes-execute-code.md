# Hermes K1: model-facing one-shot code execution

> Historical investigation, preserved in the Hermes 697 sprint PR. The untracked
> state below describes the original capture. No production K0/K1 implementation
> is claimed. Current scope: [Hermes sprint](../HERMES_SPRINT.md).

Generated: 2026-09-09 12:48 UTC. Base SHA and inspected HEAD:
`a5b8b496f319447f0233b1baf4a0f54cb8551c06`.
Branch: `codex/hermes-execute-code`. Local plan; no commit or remote mutation.
Changed paths at generation: this plan, `2026-09-09-hermes-execute-code-probe.py`
and `2026-09-09-hermes-execute-code-evidence.json` in this directory; all untracked.
No production sources changed. Next action: design the prerequisite K0 authority
contract as a separate delivery unit; keep model-facing `execute_code` unregistered.

## Goal and boundaries

Offer a bounded `execute_code` tool through the existing agent ToolRPC loop,
using a fresh isolated Docker/WASM sandbox per invocation. Inner ToolRPC calls
must retain the exact trusted principal, session, agent and data scope, and may
only use the intersection of the outer turn's offered tools and current policy.
Missing scope or unusable isolation must refuse before execution. Model-supplied
identity fields, recursive code execution and host-subprocess fallback are excluded.

Non-goals: persistent kernels, a new approval authority, new routes, cloud use,
package/model installation, service startup, SDK/lifecycle hooks and desktop UI.
The earlier host probe found the Docker executable but could not connect to its
daemon. This is historical probe state, not a claim about its state after restart.
No live isolated execution proof is available. This does not establish a code defect.

## Intended implementation and tests, subject to authority audit

Likely production paths: a new `agents/core/code_tools.py`,
`agents/core/tool_rpc_runtime.py`, `agents/core/agent_runtime.py`, and the registration
point in `agents/core/autonomy_coordinator.py`. Preserve the independent local-image
wiring when that change lands. No protected kernel/security/workflow/policy files.
Tests would cover model-loop discoverability, unusable isolation refusal, fresh
private workspaces, stdout/time/call bounds, cancellation/container cleanup, absence
of host fallback, exact actor/principal/session/data-space propagation, profile
intersection including capability-registry narrowing, no recursion, inner taint
before subsequent calls and gated calls queued under existing authority only.

Dependencies: an existing authoritative per-turn data scope and a scoped inner RPC
contract are necessary; merely passing a string actor is insufficient. An available
isolated backend is necessary for owner-host proof but not hermetic regressions.
Rollback: remove the single tool registration and revert this standalone slice;
no data migration. If the authority dependency is missing, do not register the tool.
BACKLOG and mobile/HUD parity should change only when implementation changes delivery.

## Authority audit decision: K1 depends on K0

The existing bridge invokes `ToolRPCServer.handle` without an actor or a resolved
profile. The server defaults missing actors to its configured agent. The exact
offered set currently lives in the agent runtime, outside the sandbox bridge.

`DataSpaces` describes per-agent read restrictions, but its production enforcement
calls are only in `agents/core/routers/data_spaces.py`. The registry itself has no
authoritative session-to-source mapping. `session_search` reads the configured
memory directory and accepts a caller-selected optional session filter; neither
its handler nor ToolRPC receives a trusted data-space grant. Inheriting Python
context variables cannot create this missing authority contract.

The preserved evidence file was captured at 12:38:11 UTC. Repeating the same probe
at 12:46:49 UTC after the interruption produced the same observations, source
hashes and probe hash; tracked sources remained clean. The probe uses temporary
synthetic snapshots and an in-memory queue only, with no sandbox, generated code,
personal data access or external action:

- Intended outer actor `frigga` and offered tools `[echo]` are not inputs supported
  by the bridge. Calling its existing inner request method with the synthetic
  gated tool enqueues `toolrpc.synthetic_mutation` as default actor `jarvis`.
  The gated handler executes zero times; the approval gate remains in effect.
- A synthetic DataSpaces assignment contains only `session_allowed`, while
  `session_search` returns both temporary matching snapshots. Those arbitrary
  source labels have no authoritative mapping to session records today.

This proves missing authority bindings for the proposed model-facing feature. It
does **not** demonstrate bypass of an implemented session ACL, direct execution of
the gated operation, or a current model-visible `execute_code` attack path.
Passing an actor string or copying ContextVars alone cannot complete the missing
session/data-source contract. K1 registration is therefore deferred.

## K0 prerequisite: trusted invocation scope

Goal: establish a testable, fail-closed contract for a nested tool invocation before
exposing code execution to a model. Keep it a separate reversible unit from K1.

1. Resolve principal, agent, session, origin and data-space grants at the trusted
   turn boundary. Bind an immutable invocation identifier and lifetime there;
   reject missing or model-authored scope. Define a canonical session-to-source
   mapping and explicit policy for legacy/unassigned records before enforcing it.
   Existing DataSpaces defaults must not silently become a fabricated session ACL.
2. Make every inner call use the intersection of the outer turn's actual offered
   tools, current tool profile, live capability registry and data grants. Refuse
   recursion, unregistered tools, expired/revoked scope and ambiguous identity
   before either reading data or creating a queued operation.
3. Enforce shared server-side call/time/output budgets across nested calls and
   propagate origin and increasing recall taint through asynchronous boundaries.
   Recheck current authorization before each data read or side effect; queued
   mutations must retain their trusted scope and existing approval authority.
4. Prove isolation and cleanup independently of authorization: unavailable Docker
   or WASM refuses, with no host-subprocess fallback. Cancellation, timeout and
   revocation terminate servicing and clean only the invocation's private files.

Likely investigation paths: `agents/core/orchestrator.py`,
`agents/core/agent_runtime.py`, `agents/core/tool_profiles.py`,
`agents/core/tool_rpc.py`, `agents/core/tool_rpc_runtime.py`,
`agents/core/data_spaces.py` and `agents/core/memory/session_search.py`.
Classify the concrete K0 file set with the trusted `main` self-development policy
before implementation. If its correct enforcement requires protected authority
roots, it is a separate control-plane dependency and cannot self-authorize a change.

Required regressions: two concurrent principals/sessions do not share scope;
forged/missing/expired scope fails before reads and queue writes; inner calls never
exceed the outer offered set; current registry/profile/data grant revocation takes
effect between calls and before approved execution; cross-source session search
fails under the newly specified mapping; recall taint is monotonic; recursion and
nested budget resets fail; cancellation leaves no continuing handler or sandbox.
Host isolation proof follows hermetic tests and remains a distinct readiness item.

K0 rollback must withdraw the new scope consumer without broadening existing read
access. K1 remains unavailable until K0 and its required isolation proof pass.
This audit creates no BACKLOG completion or parity claim.

## Verification on the inspected base

The synthetic probe replayed successfully without changing its saved evidence.
The bounded existing regression packet passed all 90 tests on local Python 3.11.15:
`test_tool_rpc_h20_1.py`, `test_tool_rpc_kernel_wave.py`, `test_tool_profiles.py`,
`test_session_search.py` and `test_data_spaces_h10_26.py`. The packet reported one
existing Starlette/httpx deprecation warning. These tests validate current behavior;
they do not prove the future K0 contract. Host-subprocess sandbox tests and live
Docker/WASM execution were deliberately outside this audit packet.
