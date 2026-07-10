# Agent Runtime v2 Wave 1 — Design

**Status:** Approved by owner on 2026-07-10 as the first implementation slice from the
Jarvis-versus-Hermes capability audit.

## Goal

Give the normal Jarvis agent path a bounded, model-directed tool loop that can call the
existing governed ToolRPC allowlist, observe results, and continue to a final answer.
The first live provider is LM Studio's OpenAI-compatible chat-completions endpoint.

This wave establishes the execution spine needed by later file, process, browser, build,
multimedia, MCP, and subagent tools. It does not add those higher-risk tools yet.

## Non-goals

- No file writes, shell commands, browser control, build launching, or desktop control.
- No weakening of ToolRPC approval, contract, Action Kernel, secret-scrub, or audit paths.
- No cloud-provider tool calling in this PR.
- No new inline routes in agents/web.py.
- No chat attachment or artifact-store implementation; Claude owns that independent PR.
- No automatic enablement. Existing behavior remains byte-identical unless
  llm.tool_loop_enabled is explicitly turned on.

## Parallel ownership

### Codex lane — this PR

Owned files:

- agents/core/agent_runtime.py
- agents/core/llm/tool_protocol.py
- agents/core/llm/base.py
- agents/core/security/guardrails.py
- agents/core/tool_rpc.py
- agents/core/agent.py
- agents/core/orchestrator.py
- agents/core/autonomy_coordinator.py
- agents/core/settings_db.py
- tests/test_agent_runtime_v2.py
- tests/test_llm_tool_protocol.py
- this spec and its implementation plan
- BACKLOG.md and coordination docs when tracker updates are due

### Claude Fable 5 lane — independent PR

Claude owns the artifact store, artifact router, HUD artifact rail/renderers, artifact
tests, route/OpenAPI snapshots, generated frontend API schema, and mobile/PARITY.md.
Claude must not touch any Codex-owned runtime file above or BACKLOG.md.

The first Claude slice deliberately stops before injecting artifact handles into the
agent prompt. That integration follows after both PRs merge.

## Architecture

### 1. Provider-neutral tool protocol

New module agents/core/llm/tool_protocol.py defines immutable value objects:

- ToolSpec: name, description, JSON input schema.
- ToolCall: provider call id, name, parsed arguments, and optional parse error.
- ToolTurn: assistant content, ordered tool calls, and finish reason.

LLMBackend gains a non-abstract generate_tool_turn method. Its default implementation
falls back to generate and returns a final ToolTurn, so every existing backend and test
double remains source-compatible.

LMStudioBackend overrides generate_tool_turn and uses the OpenAI-compatible tools
request/response shape. Invalid JSON arguments are represented as a parse error and are
never executed.

GuardrailsEngine proxies supports_tools and implements generate_tool_turn. It scans and
applies the configured policy to string message content before the provider call and to
the final assistant content afterward. Tool execution remains governed separately by
ToolRPC.

### 2. Bounded iterative runtime

New AgentToolRuntime receives a ToolRPCServer plus live setting callables. On each run it:

1. Builds system and user messages.
2. Converts the ToolRPC allowlist into ToolSpec objects.
3. Consumes one IterationBudget unit per model turn.
4. Calls generate_tool_turn.
5. Returns immediately when the model produces no tool calls.
6. Executes independent calls from one model turn concurrently through
   ToolRPCServer.handle.
7. Appends assistant tool-call messages and ordered tool-result messages.
8. Continues until a final answer or the configured cap.

Tool results are JSON encoded and bounded with the existing 50 KB output helper before
they re-enter model context. Non-JSON handler results become an explicit
non_json_result failure instead of leaking a Python representation. Secret values are
already scrubbed by ToolRPCServer.

The trusted caller supplies agent_id directly to the runtime; model-produced arguments
cannot select or override identity. ToolRPC uses that identity for the contract, Action
Kernel, approval task, and audit record. A shared process-wide ToolRPC server therefore
does not collapse every tool call to agent="jarvis".

Each handler has a 30-second timeout and the whole loop has a 120-second wall deadline.
The existing process-wide kernel loop detector remains a separate fleet safety net; the
new IterationBudget is per turn.

The runtime emits structured best-effort lifecycle events:

- tool_requested
- tool_started
- tool_result
- tool_failed
- tool_loop_exhausted

This PR provides the callback contract but does not yet alter the browser SSE envelope.

### 3. Shared agent generation seam

Agent gains generate_response, which is used by both Agent.process and the orchestrator's
streamed chat path.

- When the runtime is enabled and the selected backend supports tools, it runs the tool
  loop and emits the final answer through on_token once.
- Otherwise it preserves the current generate/generate_stream behavior.

AutonomyCoordinator creates one AgentToolRuntime after it creates the existing ToolRPC
server, attaches it to every loaded agent, and registers JSON schemas/descriptions for
the existing echo and time tools.

### 4. Live settings

Two runtime settings are added:

- llm.tool_loop_enabled: false
- llm.tool_loop_max_iterations: 8

The enabled and cap values are read through callables at turn time, so the existing
settings watcher can change them without restarting Jarvis. A malformed cap is pinned
to a safe range of 1 through 32.

## Data flow

1. User turn enters the existing orchestrator and security/context pipeline.
2. Existing routing selects an agent, backend, and model.
3. Agent.generate_response chooses the default generation path or AgentToolRuntime.
4. The provider requests a named ToolRPC tool.
5. ToolRPC applies allowlist, contract, Action Kernel, approval, secret scrub, and audit.
6. The bounded result returns to the model as a tool message.
7. The model produces another tool request or a final answer.
8. The existing persistence, cognition, and response path stores the final answer.

## Error handling

- Backend without tool support: use the existing one-shot/streaming path.
- Provider/network failure: preserve the existing degraded-reply behavior.
- Unknown tool: feed tool_not_allowed to the model; never improvise an execution path.
- Invalid arguments: feed bad_tool_arguments; never call the handler.
- Gated tool: feed approval_required with the task id when available; never run inline.
- Approval required: stop the loop immediately after one enqueue so a retry cannot
  create duplicate approval tasks.
- Approved gated execution: re-check the Action Kernel/kill switch immediately before
  invoking the handler, not only before enqueue.
- Handler failure: feed tool_error without raw exception details.
- Handler timeout: feed tool_timeout; never wait forever.
- Whole-loop timeout: return an honest bounded-stop message.
- Non-JSON result: feed non_json_result; never stringify arbitrary objects into context.
- Output too large: truncate explicitly with the existing head/tail marker.
- Iteration cap: return an honest bounded-stop message and emit tool_loop_exhausted.
- Event callback failure: log and continue; observability cannot break execution.

## Security invariants

- Model tool names are untrusted input and must match the ToolRPC allowlist exactly.
- Agent identity comes from the selected Agent object, never from model output.
- Tool arguments never bypass ToolRPC.
- Mutating/external tools remain gated and Action-Kernel mediated.
- Tool results are secret-scrubbed and output-bounded before returning to the model.
- The feature is default-off and local LM Studio is the only provider enabled in Wave 1.
- Strict-local agent routing remains unchanged.
- No tool-call content is persisted as a fake user or assistant turn; only the final
  answer follows the current conversation persistence path.
- ToolRPC events use the durable IntentLog-compatible audit sink; the SQLite scanner
  AuditLogger is not used as a generic tool event sink.

## Tests

TDD coverage must prove:

1. Provider-neutral fallback returns a final ToolTurn and does not break old backends.
2. LM Studio sends valid tool schemas and parses ordered tool calls.
3. Invalid argument JSON never reaches a ToolRPC handler.
4. A scripted model can call echo, receive the result, and produce a final answer.
5. Multiple read-only calls in one turn execute concurrently and results retain order.
6. Unknown, failed, and approval-required tool results are fed back honestly.
7. Approval-required stops after one enqueue and approved execution rechecks the kernel.
8. Trusted agent identity reaches contract, approval, kernel, and audit context.
9. Per-tool and whole-loop deadlines terminate hanging work.
10. The iteration/call caps terminate a repeating or fan-out model.
11. Tool result text is JSON-only and output-bounded.
12. Disabled runtime preserves the exact existing generate/generate_stream path.
13. Enabled normal Agent.process and streamed orchestrator generation use the same seam.
14. Guardrails still scan provider input/output while tool mode is active.
15. Existing Agent, LLM, ToolRPC, kernel, stream, route, and full offline suites remain
    green.

## Risk and rollback

Primary risks are provider-format drift, guardrail bypass, untrusted identity,
unbounded waits, duplicate approvals, accidental default enablement, and divergent
streamed/non-streamed behavior. Tests target each boundary and the runtime is
default-off.

Rollback is a single feature-branch revert. Operational rollback requires only setting
llm.tool_loop_enabled=false; the original generation path remains in place.

## Merge order

1. Codex Agent Runtime v2 Wave 1 and Claude Artifact Workspace Wave 1 may develop in
   parallel because their file sets are disjoint.
2. Either PR may merge first.
3. After both merge, a small integration PR adds artifact handles to chat turns and emits
   runtime artifact/tool lifecycle events to the HUD rail.
4. Managed process and browser/build tooling follows on top of the proven runtime and
   artifact contracts.
