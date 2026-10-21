# How a turn executes: the agent loop's internals

What happens between the owner's message and the reply, from the orchestrator down to
one tool call, and where each decision lives. The request lifecycle above the agent
(memory, commands, skills, routing, plugin fan-out, synthesis) is in
`docs/ARCHITECTURE.md` §2; this page starts where one agent is asked to answer. For
adding a tool, see [adding-a-tool.md](adding-a-tool.md).

References use `path::Symbol` and are checked by `tests/test_h652_developer_docs.py`.

## 1. From the orchestrator to one agent

`Orchestrator.handle_input` (ARCHITECTURE §2, steps 1–7) ends with each chosen agent
running `agents/core/agent.py::Agent.process`, which builds the prompt (history,
plugin data, recall, RAG) and calls `agents/core/agent.py::Agent.generate_response`.

`generate_response` binds the turn's ambient state, all as context variables, so
everything below reads it without it being passed down:

| bound | by | read by |
|---|---|---|
| the session id | `agents/core/llm/request_context.py::session_scope` | provider caching, the todo tool, trajectories |
| the conversation clock snapshot | `agents/core/conversation_clock.py::clock_scope` | the system prompt's time block, compaction |
| the usage observer | `agents/core/llm/usage_context.py::observer_scope` | the cost meter (every model request of the turn) |
| the trajectory recorder (opt-in) | `agents/core/trajectory.py::capture` | the tool loop's step notes; the saved turn |

It then calls `Agent._generate_response`, which applies the per-model system prompt
and the pinned window, and picks one of two paths:

- **Tool loop** when `agents/core/agent_runtime.py::AgentToolRuntime.can_run` says yes
  (the `llm.tool_loop_enabled` setting, a backend that declares `supports_tools`, a
  non-empty registry, no straggler still running). The runtime is built once, in
  `agents/core/autonomy_coordinator.py::AutonomyCoordinator._wire_agent_tool_runtime`.
- **Plain generation** otherwise: owner steering messages are appended to the
  prompt, then one `backend.generate` (or `generate_stream` with a token callback).

## 2. The tool loop, outside in

`AgentToolRuntime.run` → `run_result` → `_run_turn` → `_run_loop`.

**`run_result`** binds a fresh tool-turn token (each model turn's calls carry it, so a
tool can tell this turn's request from a script's), runs the turn, records the exit for
`agents/core/turn_stops.py` and the trajectory, and returns a
`agents/core/tool_loop_result.py::ToolLoopResult` — the reply plus one
`ToolLoopExitReason`.

**`_run_turn`** resolves the deadline (the caller's `wall_seconds`, clamped to
`WALL_SECONDS_MIN..WALL_SECONDS_CAP`, else the constructor's 120 s) and the effective
context window (an unusable one → `WINDOW_INVALID`), opens the provider-replay scope
(a replay that cannot be honoured → `REPLAY_REFUSED`), and runs the loop as a child
task in a copied context. The loop itself first checks the conversation clock it
inherited (`agents/core/conversation_clock.py::clock_scope`): a clock whose owning turn
has already ended → `TURN_REVOKED`, so work started late never runs on a finished turn. On the deadline it returns `DEADLINE`; a child that ignores
cancellation is detached and blocks `can_run` until it ends, so orphans never pile up.
Whatever untrusted-content taint the loop raised is carried back to the caller's
context (`_carry_turn_taint`).

**`_run_loop`**, before the first model request:

1. **The offer.** `self._server.tools()` is the registry; `_profiled` applies
   `agents/core/tool_profiles.py` (agent × surface × principal, the agent's `tools:`
   list, the job toolset) and emits a `tool_profile` event naming what was withheld.
   Nothing offered → `NO_TOOLS`. With registry planning on, an explicit capability
   goal with no registered capability is reported as a gap → `NO_CAPABILITY`.
2. **The transcript.** `[system, user]`, where the system prompt is
   `_guided_system`: the clocked base prompt plus optional operating guidance built
   over the exact offer (never tool authority).
3. **Budgets.** An iteration budget (`llm.tool_loop_max_iterations`, default 8, hard
   cap 32), at most 8 executed calls per model step, an optional per-tool cap, the
   stall observer (`agents/core/tool_loop_guardrails.py::StallObserver`), and the
   result byte budget scaled to the model's real window.

Then, **each iteration**:

1. **Steering.** Messages the owner sent mid-turn
   (`agents/core/steering.py::prepare_steering_rows`) are appended as user rows.
2. **Compaction.** `_compact_context` folds older tool results into bounded envelopes
   until the transcript fits the window. Messages are never dropped or reordered (every
   tool result keeps answering its call — providers validate that); only content
   shrinks, newest iterations last. A transcript that cannot fit → `CONTEXT_REFUSED`.
   A committed fold is the one point a running turn may pick up a changed registry
   (`agents/core/session_refresh.py::refresh_tools`, fails closed → `TOOLS_WITHDRAWN`).
3. **Revocation check.** `before_model_call` (the router's data-handling check) runs
   before every request, so a route revoked mid-turn stops the next request.
4. **The model request.** `backend.generate_tool_turn(messages, tools, ...)` returns a
   `agents/core/llm/tool_protocol.py::ToolTurn`. Every provider's wire format is parsed
   through one fail-closed boundary into `ToolCall`s. Usage is reported to the meter.
5. **No calls → done.** `MODEL_RESPONSE` with the turn's text.
6. **Calls.** Bounded to the per-step cap (+1 overflow call that is answered with a
   refusal), the assistant message is appended, then `_execute_turn_calls`:
   - `plan_tool_batch` splits the step into ordered groups: consecutive parallel-safe
     calls run concurrently, anything else is a barrier that runs alone, in provider
     order;
   - `_execute_one` refuses malformed arguments (`bad_tool_arguments`), a tool outside
     the offer, an over-cap call, and re-checks the execution profile; then
     `_execute_rpc` calls `agents/core/tool_rpc.py::ToolRPCServer.handle` under the
     per-call timeout (30 s) with heartbeats for long calls. A gated tool does not run:
     `handle` enqueues an approval task and answers `approval_required`.
7. **Each result, in call order:**
   - `classify_output` + `_fence_result`: an untrusted result (declared
     `untrusted_output`, injection-flagged, or carrying untrusted provenance) is
     wrapped as DATA and the turn's recall taint rises, so an action built from it
     queues for approval from the **next** iteration on;
   - `_dedupe_result`: a successful result already in the transcript becomes a "same
     as call N" stub;
   - the stall observer sees the call; a repeat or a failure streak adds a
     `stall_notice` to the result (advice), or halts the loop when halting is on;
   - oversized results were already spilled by `_prepare_result` to the result store
     with a `file_read` paging recipe in the preview;
   - image parts ride beside the text only to a backend that reads them;
   - the tool message is appended.
8. **Exits after the step.** Any `approval_required` → `APPROVAL_REQUIRED` (the reply
   names the pending card); a denial breaker → the next request offers no tools, so the
   model's text answer ends the turn (`GUARDIAN_DENIED` if it still asks for a call); a
   per-tool cap hit → `TOOL_CALL_LIMIT`; a stall halt →
   `REPEATED_CALL` / `FAILING_TOOL`.

When the budget runs out: `ITERATION_LIMIT`, with a reply that says so.

## 3. Everything the loop reports

- **Events** (`tool_requested`, `tool_started`, `tool_result` / `tool_failed`,
  `tool_result_untrusted`, `tool_profile`, `tool_batch_planned`,
  `tool_loop_stall_notice`, `tool_offer_refreshed`, ...) go to the agent's sink and
  into `agents/core/observability/tool_events.py`: bounded, in memory, names and
  reasons only — never arguments or results. Read them with `nerva tools` or
  `GET /api/admin/tool-events`.
- **Usage**: every model request's provider-reported tokens, through the usage sink.
- **The exit**: `logger.info("tool_loop_exit ...")` and `turn_stops.record_runtime_stop`.
- **The whole turn**, when the owner opts in with `NERVA_SAVE_TRAJECTORIES=1`: the
  loop notes its guided system prompt (again when a fold rebuilds it), the tool
  definitions it offered as the provider's `tools=` (`note_tools`, right after
  `_specs_for` and again when a fold refreshes the offer — the union, a name's latest
  definition winning), each steering row, each assistant step with its calls, each tool
  result as the model read it, and the exit reason into the active
  `agents/core/trajectory.py::TrajectoryRecorder`. On the plain path
  `Agent._generate_response` re-notes the prompt after folding steering into it, so the
  saved human turn is the one sent. `Agent.generate_response` adds the reply and saves
  one redacted record per turn under `<data root>/trajectories/<session>.jsonl`. Export
  it as ShareGPT with `nerva sessions export <session> --sharegpt` or
  `GET /sessions/{id}/trajectories`: the system turn carries the tools as a Hermes
  `<tools>[{name, description, parameters, required: null}]</tools>` block, every gpt
  turn opens with a (empty) `<think>` block, and one step's parallel results share one
  `tool` turn. `format=messages` adds a `tools` column next to `messages` for SFT chat
  templates.

## 4. Invariants worth knowing before you change the loop

- The loop never executes a tool the turn was not offered, and the offer only narrows
  mid-turn (at a fold), never silently widens.
- Every `tool` message answers the assistant call that produced it; compaction shrinks
  content, it never removes rows.
- Taint escalates only. Nothing in the loop lowers a turn's action origin.
- A gated call's effect happens after approval, in `ToolRPCServer.execute`, not in the
  turn that proposed it.
- An event sink, a usage sink or a trajectory note that fails never fails the turn.
- Tests pin each of these: `tests/test_agent_runtime_v2.py` (loop shape, exits,
  stragglers), `tests/test_tool_result_taint.py` (the fence),
  `tests/test_tool_profiles.py` (the offer), `tests/test_trajectory_export.py` (the
  saved turn).
