# Agent Runtime v2 Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a default-off, bounded LM Studio tool-calling loop that executes only the
existing governed ToolRPC allowlist and is shared by normal and streamed Jarvis turns.

**Architecture:** A provider-neutral tool protocol sits beside LLMBackend. LM Studio
implements the OpenAI-compatible tool-call shape, AgentToolRuntime owns the bounded
model→tool→observation loop, ToolRPC remains the only execution boundary, and Agent
exposes one generation seam used by both Agent.process and streamed orchestration.

**Tech Stack:** Python 3.12+, asyncio, dataclasses, httpx, FastAPI settings store, pytest.

## Global Constraints

- Existing generation behavior must remain byte-identical while llm.tool_loop_enabled is false.
- Only LM Studio advertises tool support in Wave 1.
- Every requested tool must pass through ToolRPCServer.handle.
- Unknown or malformed calls never reach a handler.
- Gated tools retain contract, Action Kernel, approval, secret-scrub, and audit behavior.
- Tool results re-entering model context are explicitly bounded to 50,000 UTF-8 bytes.
- Tool model turns are capped to 1–32 iterations; default is 8.
- No new routes, files/shell/browser tools, cloud tool calling, or artifact integration.
- Follow TDD: each behavior test must fail for the expected missing-feature reason before implementation.

---

### Task 1: Provider-neutral tool protocol and backend fallback

**Files:**
- Create: agents/core/llm/tool_protocol.py
- Modify: agents/core/llm/base.py:257-330
- Test: tests/test_llm_tool_protocol.py

**Interfaces:**
- Produces: ToolSpec.as_openai() -> dict
- Produces: ToolCall.as_openai() -> dict
- Produces: ToolTurn.as_assistant_message() -> dict
- Produces: parse_openai_tool_calls(raw_calls) -> tuple[ToolCall, ...]
- Produces: LLMBackend.generate_tool_turn(...) -> ToolTurn

- [ ] **Step 1: Write failing value-object and fallback tests**

Add tests that import the new module, assert the exact OpenAI schema shape, preserve the
provider's raw argument string, mark invalid JSON without raising, and verify a minimal
LLMBackend subclass that implements only generate can call generate_tool_turn:

    class _TextBackend(LLMBackend):
        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            return "plain answer"

    turn = await _TextBackend().generate_tool_turn(
        model="m",
        messages=[{"role": "system", "content": "sys"},
                  {"role": "user", "content": "hello"}],
        tools=[],
    )
    assert turn.content == "plain answer"
    assert turn.tool_calls == ()

For invalid arguments:

    calls = parse_openai_tool_calls([{
        "id": "call-1",
        "function": {"name": "echo", "arguments": "{broken"},
    }])
    assert calls[0].arguments is None
    assert calls[0].parse_error == "invalid_json"
    assert calls[0].raw_arguments == "{broken"

- [ ] **Step 2: Run the focused test and verify RED**

Run:

    python -m pytest tests/test_llm_tool_protocol.py -q

Expected: collection fails because agents.core.llm.tool_protocol does not exist.

- [ ] **Step 3: Implement the immutable protocol values**

Create dataclasses with these exact public fields:

    @dataclass(frozen=True)
    class ToolSpec:
        name: str
        description: str = ""
        input_schema: dict[str, Any] = field(
            default_factory=lambda: {"type": "object", "properties": {}}
        )

    @dataclass(frozen=True)
    class ToolCall:
        id: str
        name: str
        raw_arguments: str = "{}"
        arguments: Optional[dict[str, Any]] = field(default_factory=dict)
        parse_error: Optional[str] = None

    @dataclass(frozen=True)
    class ToolTurn:
        content: str = ""
        tool_calls: tuple[ToolCall, ...] = ()
        finish_reason: Optional[str] = None

ToolSpec.as_openai must return:

    {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        },
    }

ToolCall.as_openai must preserve raw_arguments. ToolTurn.as_assistant_message must include
content and tool_calls only when calls exist.

- [ ] **Step 4: Add the source-compatible LLMBackend fallback**

Set supports_tools = False on LLMBackend. Add a non-abstract generate_tool_turn method
whose signature accepts model, messages, tools, max_tokens, and temperature. It extracts
the joined system content plus the last user/tool content, calls generate, and wraps the
string in ToolTurn. Do not add a new abstract method.

- [ ] **Step 5: Run focused and compatibility tests**

Run:

    python -m pytest tests/test_llm_tool_protocol.py tests/test_llm_warmup.py tests/test_hybrid_router.py -q

Expected: all pass.

- [ ] **Step 6: Commit**

    git add agents/core/llm/tool_protocol.py agents/core/llm/base.py tests/test_llm_tool_protocol.py
    git commit -m "feat(runtime): add provider-neutral tool protocol"

---

### Task 2: LM Studio tool-call transport

**Files:**
- Modify: agents/core/llm/base.py:331-451
- Test: tests/test_llm_tool_protocol.py

**Interfaces:**
- Consumes: ToolSpec and parse_openai_tool_calls from Task 1.
- Produces: LMStudioBackend.supports_tools = True.
- Produces: LMStudioBackend.generate_tool_turn(...) -> ToolTurn.

- [ ] **Step 1: Add failing LM Studio request/parse tests**

Inject a fake async client that records POST JSON and returns:

    {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-echo",
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "arguments": "{\"value\":\"hi\"}",
                    },
                }],
            },
        }],
    }

Assert payload.tools contains ToolSpec.as_openai(), payload.messages is unchanged,
payload.tool_choice == "auto", and the returned ToolCall has parsed arguments.

Add a second test proving a content-only response becomes a final ToolTurn and a third
proving malformed tool arguments are returned as parse_error rather than executed.

- [ ] **Step 2: Run the LM Studio tests and verify RED**

Run:

    python -m pytest tests/test_llm_tool_protocol.py -q

Expected: fails because LMStudioBackend does not advertise or implement tool turns.

- [ ] **Step 3: Implement LM Studio generate_tool_turn**

Build the existing chat-completions payload with messages, temperature, stream=False,
tools, and tool_choice="auto". Omit max_tokens in auto mode exactly like generate.
Parse choices[0].message.content, message.tool_calls, and finish_reason into ToolTurn.
On request failure, return ToolTurn(content=local_backend_degraded_reply(...)).

- [ ] **Step 4: Run protocol, thinking, and graceful-down tests**

Run:

    python -m pytest tests/test_llm_tool_protocol.py tests/test_llm_thinking_leak.py tests/test_llm_down_graceful.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add agents/core/llm/base.py tests/test_llm_tool_protocol.py
    git commit -m "feat(runtime): add LM Studio tool-call transport"

---

### Task 3: Guardrails tool-turn mediation

**Files:**
- Modify: agents/core/security/guardrails.py:19-125
- Test: tests/test_llm_tool_protocol.py
- Test: tests/test_guardrails_generate_kwargs.py

**Interfaces:**
- Consumes: backend.generate_tool_turn from Tasks 1–2.
- Produces: GuardrailsEngine.supports_tools property.
- Produces: GuardrailsEngine.generate_tool_turn(...) -> ToolTurn.

- [ ] **Step 1: Add failing guardrail tool-mode tests**

Use a recording tool backend with supports_tools=True. In REDACT mode, send system and
user message content containing alice@example.com. Assert the backend never sees the
address and an assistant content response containing the address is also redacted.
Assert tool call ids/names/raw arguments remain structurally intact.

Add a proxy test:

    assert GuardrailsEngine(_ToolBackend()).supports_tools is True
    assert GuardrailsEngine(_TextBackend()).supports_tools is False

- [ ] **Step 2: Run the tests and verify RED**

Run:

    python -m pytest tests/test_llm_tool_protocol.py tests/test_guardrails_generate_kwargs.py -q

Expected: fails because GuardrailsEngine has no supports_tools/generate_tool_turn.

- [ ] **Step 3: Implement guarded tool turns**

Add a supports_tools property that reads the wrapped backend. Clone each message before
scanning; apply the existing input policy only when content is a string. Delegate to the
backend. Apply the existing output policy to ToolTurn.content and return a dataclasses
replace result so tool calls are unchanged.

- [ ] **Step 4: Run all guardrail tests**

Run:

    python -m pytest tests/test_guardrails_generate_kwargs.py tests/test_security_scanner.py tests/test_llm_tool_protocol.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add agents/core/security/guardrails.py tests/test_llm_tool_protocol.py tests/test_guardrails_generate_kwargs.py
    git commit -m "feat(runtime): guard tool-enabled model turns"

---

### Task 4: ToolRPC model schemas without changing execution

**Files:**
- Modify: agents/core/tool_rpc.py:75-105
- Test: tests/test_tool_rpc_h20_1.py
- Test: tests/test_agent_runtime_v2.py

**Interfaces:**
- Produces: ToolRPCServer.register_tool(name, handler, gated=False, description="", input_schema=None).
- Produces: ToolRPCServer.tools() records with name, gated, description, input_schema.

- [ ] **Step 1: Add failing schema metadata tests**

Register:

    server.register_tool(
        "echo",
        echo,
        description="Return the provided values.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

Assert tools()[0] includes the exact description and schema. Assert an omitted schema
defaults to an object with empty properties and existing name/gated projections remain
unchanged.

- [ ] **Step 2: Run ToolRPC tests and verify RED**

Run:

    python -m pytest tests/test_tool_rpc_h20_1.py -q

Expected: schema test fails because register_tool rejects the new keywords.

- [ ] **Step 3: Extend registration metadata only**

Copy input_schema on registration and return a new copy from tools so callers cannot
mutate the allowlist metadata. Do not change handle, execute, gating, kernel, scrub, or
audit logic.

- [ ] **Step 4: Run the full ToolRPC and kernel slice**

Run:

    python -m pytest tests/test_tool_rpc_h20_1.py tests/test_tool_rpc_runtime.py tests/test_tool_rpc_kernel_wave.py tests/test_action_auth_matrix.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add agents/core/tool_rpc.py tests/test_tool_rpc_h20_1.py
    git commit -m "feat(runtime): describe ToolRPC model tools"

---

### Task 5: Bounded AgentToolRuntime

**Files:**
- Create: agents/core/agent_runtime.py
- Test: tests/test_agent_runtime_v2.py

**Interfaces:**
- Consumes: ToolRPCServer, ToolSpec, ToolCall, ToolTurn, IterationBudget, truncate_text.
- Produces: AgentToolRuntime.can_run(backend) -> bool.
- Produces: AgentToolRuntime.run(...) -> str.
- Produces: ToolEventSink callback receiving dict lifecycle events.

- [ ] **Step 1: Write the failing echo-loop test**

Create a scripted backend whose first ToolTurn requests echo and whose second returns
"Echo completed". Register a real async ToolRPC echo handler. Assert:

- handler receives {"value": "hi"};
- second provider call sees an assistant tool_calls message followed by a role=tool
  message containing the successful ToolRPC response;
- runtime returns "Echo completed";
- events include tool_requested, tool_started, and tool_result.

- [ ] **Step 2: Run the single test and verify RED**

Run:

    python -m pytest tests/test_agent_runtime_v2.py::test_runtime_executes_tool_and_continues_to_final_answer -q

Expected: collection fails because agents.core.agent_runtime does not exist.

- [ ] **Step 3: Implement the minimal sequential loop**

Create AgentToolRuntime with constructor:

    def __init__(
        self,
        server: ToolRPCServer,
        *,
        enabled: Callable[[], bool] = lambda: False,
        max_iterations: Callable[[], int] = lambda: 8,
        max_tool_calls_per_turn: int = 8,
        max_result_bytes: int = 50_000,
    ) -> None

can_run returns true only when enabled(), backend.supports_tools, and server.tools() are
all truthy. run builds messages, converts ToolRPC metadata to ToolSpec, consumes an
IterationBudget, calls generate_tool_turn, executes through server.handle, appends the
assistant/tool messages, and returns final content.

- [ ] **Step 4: Run the echo test and verify GREEN**

Run the same test. Expected: pass.

- [ ] **Step 5: Add failing safety and concurrency tests**

Add one behavior per test:

- invalid arguments produce bad_tool_arguments and never invoke the handler;
- unknown tool produces tool_not_allowed and returns to the model;
- gated tool produces approval_required and never invokes the handler;
- handler exception produces tool_error without exception text;
- two read-only handlers block on a shared asyncio.Event, proving concurrent execution;
- tool result larger than 50,000 bytes contains the explicit truncation note;
- repeating tool requests stop at the configured iteration cap;
- more than eight calls in one turn receive too_many_tool_calls for overflow calls;
- a raising event sink is swallowed and the final answer still returns.

- [ ] **Step 6: Run safety tests and verify RED**

Run:

    python -m pytest tests/test_agent_runtime_v2.py -q

Expected: the newly added behaviors fail until implemented.

- [ ] **Step 7: Complete bounded parallel execution**

Use asyncio.gather for accepted calls from one turn and preserve input order in appended
tool messages. For parse errors and overflow calls, construct local failure dictionaries
without calling ToolRPC. Serialize with json.dumps(ensure_ascii=False, default=str) and
truncate_text. Clamp the live iteration setting to 1–32.

Use this exact exhausted reply shape:

    "I stopped the tool loop after {limit} model turns because it reached the safety limit."

Event callback results may be synchronous or awaitable and must never break execution.

- [ ] **Step 8: Run runtime and ToolRPC tests**

Run:

    python -m pytest tests/test_agent_runtime_v2.py tests/test_tool_rpc_h20_1.py tests/test_tool_rpc_kernel_wave.py -q

Expected: all pass.

- [ ] **Step 9: Commit**

    git add agents/core/agent_runtime.py tests/test_agent_runtime_v2.py
    git commit -m "feat(runtime): add bounded governed tool loop"

---

### Task 6: Shared Agent generation seam

**Files:**
- Modify: agents/core/agent.py:35-196
- Modify: agents/core/orchestrator.py:1180-1205
- Test: tests/test_agent_runtime_v2.py
- Test: tests/test_agents_integration.py

**Interfaces:**
- Consumes: optional Agent.tool_runtime.
- Produces: Agent.generate_response(backend, model, prompt, system, max_tokens, temperature, on_token=None) -> str.

- [ ] **Step 1: Add failing disabled/enabled Agent tests**

Disabled case: attach a runtime whose enabled callable returns false and assert the
existing fake backend generate method is called exactly once.

Enabled case: attach a scripted tool runtime/backend and assert Agent.process completes
the tool loop.

Streaming case: call Agent.generate_response with on_token and assert tool mode calls the
sink once with only the final answer, while disabled mode retains backend.generate_stream.

- [ ] **Step 2: Run Agent tests and verify RED**

Run:

    python -m pytest tests/test_agent_runtime_v2.py tests/test_agents_integration.py -q

Expected: fails because Agent has no tool_runtime/generate_response seam.

- [ ] **Step 3: Implement Agent.generate_response**

Initialize self.tool_runtime = None. If runtime.can_run(backend), call runtime.run and
emit the final answer to on_token, awaiting it when needed. Otherwise retain the current
generate_stream when on_token exists and generate when it does not.

Replace Agent.process's direct backend.generate call with generate_response inside the
existing residency/checkpoint/timing block.

- [ ] **Step 4: Route streamed orchestration through the same seam**

Replace only the current direct generate/generate_stream branch in
Orchestrator._handle_input_stream with:

    response = await agent.generate_response(
        backend=backend,
        model=model,
        prompt=prompt,
        system=system_prompt,
        max_tokens=eff_max_tokens,
        temperature=temperature,
        on_token=on_token,
    )

Do not change routing, context caching, persistence, cognition, or SSE framing.

- [ ] **Step 5: Run Agent and stream regression tests**

Run:

    python -m pytest tests/test_agent_runtime_v2.py tests/test_agents_integration.py tests/test_stream_abort_no_persist.py tests/test_orchestrator_process_record.py -q

Expected: all pass.

- [ ] **Step 6: Commit**

    git add agents/core/agent.py agents/core/orchestrator.py tests/test_agent_runtime_v2.py tests/test_agents_integration.py
    git commit -m "feat(runtime): share tool generation across agent paths"

---

### Task 7: Production wiring and live settings

**Files:**
- Modify: agents/core/settings_db.py:115-135
- Modify: agents/core/autonomy_coordinator.py:288-312
- Test: tests/test_agent_runtime_v2.py
- Test: tests/test_settings_db.py

**Interfaces:**
- Consumes: AgentToolRuntime and existing orchestrator ToolRPC server.
- Produces: llm.tool_loop_enabled default false.
- Produces: llm.tool_loop_max_iterations default 8.
- Produces: every loaded agent receives the same AgentToolRuntime instance.

- [ ] **Step 1: Add failing settings and wiring tests**

Assert the seeded settings values are false and 8. Build the smallest fake orchestrator
accepted by AutonomyCoordinator.build_executor, or extract a focused private
_wire_agent_tool_runtime helper if the full executor fixture is disproportionate.

Assert:

- echo and time expose descriptions and closed JSON schemas;
- every fake agent receives one shared runtime;
- changing fake get_setting from false to true changes runtime.can_run without rebuilding.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

    python -m pytest tests/test_agent_runtime_v2.py tests/test_settings_db.py -q

Expected: new settings/wiring assertions fail.

- [ ] **Step 3: Seed settings and wire the runtime**

Add:

    dict(category="llm", key="tool_loop_enabled", value=False,
         label="Agent tool loop (experimental)", kind="toggle"),
    dict(category="llm", key="tool_loop_max_iterations", value=8,
         label="Agent tool-loop model-turn cap", kind="number"),

In AutonomyCoordinator, register echo and time with exact descriptions and schemas, build
one AgentToolRuntime with live get_setting callables, assign it to
self._orch.agent_tool_runtime and every self._orch.agents value.

- [ ] **Step 4: Run runtime/settings/autonomy regressions**

Run:

    python -m pytest tests/test_agent_runtime_v2.py tests/test_settings_db.py tests/test_tool_rpc_h20_1.py tests/test_autonomy_worker.py -q

Expected: all pass.

- [ ] **Step 5: Commit**

    git add agents/core/settings_db.py agents/core/autonomy_coordinator.py tests/test_agent_runtime_v2.py tests/test_settings_db.py
    git commit -m "feat(runtime): wire default-off agent tool loop"

---

### Task 8: Tracker truth, compatibility verification, and PR evidence

**Files:**
- Modify: BACKLOG.md
- Modify: STATUS.md only if its current-known-gaps wording is changed by this PR.
- Modify: docs/superpowers/plans/2026-07-10-agent-runtime-v2-wave1.md

**Interfaces:**
- Produces: honest tracker state that distinguishes the runtime foundation from future
  file/process/browser/artifact tools.

- [ ] **Step 1: Update BACKLOG without claiming full Hermes parity**

Add a new approved P0 item for Agent Runtime v2 Wave 1. Mark only the shipped slice:
provider-neutral protocol, LM Studio tool transport, governed echo/time loop, shared
normal/stream seam, default-off setting, and tests.

Explicitly leave file/process/browser/build/media tools and browser SSE tool events open.
Do not re-mark H20.1–H20.6 as fully end-to-end.

- [ ] **Step 2: Run formatting and targeted verification**

Run:

    python -m ruff check agents/core/agent_runtime.py agents/core/llm/tool_protocol.py agents/core/llm/base.py agents/core/security/guardrails.py agents/core/tool_rpc.py agents/core/agent.py agents/core/orchestrator.py agents/core/autonomy_coordinator.py tests/test_agent_runtime_v2.py tests/test_llm_tool_protocol.py

Run:

    python -m pytest -q tests/test_agent_runtime_v2.py tests/test_llm_tool_protocol.py tests/test_agents_integration.py tests/test_guardrails_generate_kwargs.py tests/test_hybrid_router.py tests/test_llm_thinking_leak.py tests/test_llm_down_graceful.py tests/test_tool_rpc_h20_1.py tests/test_tool_rpc_runtime.py tests/test_tool_rpc_kernel_wave.py tests/test_kernel_authorize.py tests/test_kernel_budget.py tests/test_kernel_loop_breaker_wave.py tests/test_stream_abort_no_persist.py tests/test_orchestrator_process_record.py tests/test_settings_db.py

Expected: ruff exits 0; all selected tests pass with zero failures.

- [ ] **Step 3: Run the full offline suite**

Run:

    python -m pytest tests/ -q

Expected: exit 0. Record exact passed/skipped counts and any warnings.

- [ ] **Step 4: Verify default-off behavior with a focused reality harness**

Use an in-process fake LM Studio HTTP transport rather than a network model:

- disabled setting produces the exact legacy single generate request without tools;
- enabled setting produces one tools payload, one ToolRPC echo result, then a final answer;
- no unknown/gated handler executes;
- the final answer persists once.

Add this to tests/test_agent_runtime_v2.py if not already covered and run that file fresh.

- [ ] **Step 5: Review the complete diff and ownership**

Run:

    git diff --check origin/main...HEAD
    git diff --stat origin/main...HEAD
    git status --short

Confirm no Claude-owned artifact/frontend/mobile file is changed.

- [ ] **Step 6: Commit tracker updates**

    git add BACKLOG.md STATUS.md docs/superpowers/plans/2026-07-10-agent-runtime-v2-wave1.md
    git commit -m "docs: track Agent Runtime v2 wave 1"

- [ ] **Step 7: Request code review and prepare a draft PR**

Use superpowers:requesting-code-review before publishing. Push the feature branch, create
a draft PR to main, include exact verification results, security invariants, default-off
rollback, and note the independent Claude artifact PR plus the merge-independent file
ownership.
