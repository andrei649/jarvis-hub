# Adding a tool to the agent

How to give the model a new built-in tool: the skill-or-tool decision, the files to
touch, the contract a handler keeps, and how to check it from the CLI. The tool loop
that calls your tool is described in [agent-loop.md](agent-loop.md); this page is the
how-to.

References below use `path::Symbol` and are checked by
`tests/test_h652_developer_docs.py`, so a rename that leaves this page behind fails a
test instead of misleading the next reader.

## Skill or tool?

Most new capabilities should be a **skill**, not a tool. A tool is code inside the hub
that every turn's schema pays for, that the approval and profile machinery has to know
about, and that only a release can change. A skill is text, or a small command
module, that the owner can install, switch off, sign and review.

**Make it a skill when**

- it can be said as instructions plus the tools the agent already has (`file_read`,
  `terminal_run`, `web_search`, `web_extract`, `execute_code`, ...);
- it wraps an external CLI or API the agent can reach through `terminal_run` or
  `web_extract`;
- it needs no Python integration of its own and no credential handling inside the
  hub;
- examples: a git workflow, a research recipe, a PDF procedure, a report format.

A Markdown skill is a `SKILL.md` (frontmatter or heading dialect, checked by
`agents/core/skills/validate.py::validate_skill_md`); the model reads it through
`skills_list` / `skill_view` (`agents/core/skills/tools.py::register_skill_tools`). A
command skill is `skills/<name>/SKILL.md` plus `skills/<name>/main.py` (see the "Add a
skill" recipe in `docs/ARCHITECTURE.md`). `nerva skills lint PATH` checks one before you
ship it.

**Make it a tool when**

- it needs end-to-end integration: API keys from the vault, auth flows, a driver, a
  device;
- it needs custom processing that must run exactly the same way every time (parsing,
  validation, a state machine) rather than be re-derived by the model;
- it handles binary data, streaming or real-time events (images, audio, a camera);
- it acts on the hub's own state (the canvas, memory, the session's checklist) where
  the owner needs the approval queue, the audit log and the tool profiles to apply;
- examples in the tree: `canvas_point` (`agents/core/pointer_tool.py`), `todo`
  (`agents/core/todo_tool.py`), `memory` (`agents/core/memory_tool.py`), the file
  tools (`agents/core/file_tools.py`).

**Not a built-in at all** when the capability is third-party code: that is a
declarative extension (`docs/EXTENSIONS.md`, `nerva extensions doctor|consent|activate`),
proved inside the acquisition sandbox before its tools appear, or an MCP server. The
host never imports third-party code.

## The two places you touch

1. **A module, `agents/core/<name>_tool.py`**, holding the name, the description, the
   JSON schema and a `register_<name>_tool(server, ...)` function that calls
   `agents/core/tool_rpc.py::ToolRPCServer.register_tool`. Mirror
   `agents/core/pointer_tool.py::register_pointer_tool`: module constants
   `TOOL_NAME`, `CAPABILITY_ID`, `DESCRIPTION`, `INPUT_SCHEMA`; the live objects the
   handler needs are passed in as zero-argument getters (read on every call, so a
   store that is replaced or switched off is never held stale).
2. **One call in the wiring**, inside
   `agents/core/autonomy_coordinator.py::AutonomyCoordinator._wire_agent_tool_runtime`,
   next to `register_todo_tool`, `register_memory_tool`, `register_skill_tools` and
   `register_pointer_tool`. Import inside the method, as they do, so boot does not
   pay for a tool that is never wired.

Then, depending on what the tool is:

- **A job toolset.** If scheduled jobs should be able to name it, add it to a group in
  `agents/core/job_toolsets.py::CATALOG` (Nerva's equivalent of Hermes'
  `toolsets.py`).
- **Who is offered it.** `agents/core/tool_profiles.py` decides per agent × surface ×
  principal. A gated tool reaches the owner at the operator surface only by default;
  a tool that touches the owner's HUD, memory or skills stays off inbound/guest turns
  unless the owner names it in `llm.guest_tools`. A session-scoped tool goes in
  `agents/core/tool_profiles.py::SESSION_SCOPED_TOOLS`; an owner-only one in
  `agents/core/tool_profiles.py::OWNER_OPERATOR_TOOLS`. Regenerate the pinned offer
  with `python tests/test_tool_profiles.py --update` and review the diff: a tool
  reaching a surface you did not intend is exactly what that snapshot is for.
- **A per-agent narrowing.** An agent's `tools:` list in `agents.yaml` (names or
  globs) narrows the posture further; it never widens it.

## The registration contract

`ToolRPCServer.register_tool(name, handler, *, gated, description, input_schema, ...)`:

| argument | what it decides |
|---|---|
| `gated` | `True` = external or mutating. The call never runs in the turn: it is enqueued as an ask-tier task, the model gets `{"ok": false, "reason": "approval_required", "task_id": ...}`, and the handler runs from `ToolRPCServer.execute` only after the owner approves. `False` = runs inline. |
| `input_schema` | JSON Schema the model sees. Use `"additionalProperties": false` and `required`; arguments that are not strict JSON objects are refused as `bad_tool_arguments` before your handler runs. |
| `capability_id` | A unique machine id (`tool:<name>`), read by the capability registry and planning. |
| `untrusted_output` | `True` when the result is content from outside the box (a page, a search hit). The loop fences it as data and raises the turn's taint, so an action built from it queues for approval. |
| `max_result_bytes` | How much of the context window one result may take before it is spilled to a file the model can page back with `file_read` (`agents/core/tool_result_store.py`). |
| `parallel_safe` | `False` makes every call a barrier the loop runs alone (a writer two concurrent calls could interleave on). Undeclared stays concurrent for an ungated tool and fails closed (barrier) for a gated one. |
| `schema_overrides` | A zero-argument hook that narrows the advertised schema to what this install can do now (registered targets, rooms with a speaker). The handler still checks every call. |
| `classifier`, `gated_intake`, `gated_review`, `trusted_execution`, `consent_revision` | Gated-tool refinements: label a class of call on the approval card, or take over intake for a trusted tool. Read the docstring before using them; `register_tool` refuses inconsistent combinations. |

**The handler.** `async def handler(args: dict) -> dict` (a sync function runs on a
worker thread). Return a JSON-able dict; the server wraps it as
`{"ok": true, "tool": name, "result": ...}` and strips invisible Unicode tag
characters. For an expected refusal return your own `{"ok": False, "reason": "<machine_reason>", ...}`
(see `canvas_point`'s `tip_or_tour` / `canvas_unavailable`): the loop's stall detector
reads failures by shape (`agents/core/tool_loop_guardrails.py::classify_failure`), so a
named reason lets it tell "same call failed again" from progress. An exception is not
the end of the world either: it becomes `{"ok": false, "reason": "tool_error", "error": "<one bounded, secret-scrubbed line>"}`
and is logged, but a raised error is a bug report, not a protocol.

**Whose call is it.** Read the turn's identity at call time, never from arguments:
`agents/core/tool_rpc.py::current_tool_actor` for the agent,
`agents/core/action_origin.py::current_action_origin` for whether an untrusted source
is in the turn, and the posture getter the coordinator passes in for owner / guest /
system. A tool that writes something another viewer will read marks it untrusted when
the turn was (see `pointer_tool._untrusted`).

## Tests

Write `tests/test_<name>_tool.py`, offline: a real `ToolRPCServer`, your register
function with fake getters, and `await server.handle({"tool": name, "args": {...}})`.
Pin: the schema the model sees, every refusal reason, the gated/ungated decision, and
the untrusted mark. `tests/test_h309_pointer.py` is a complete small example. To prove
the model can call it end to end, drive `agents/core/agent_runtime.py::AgentToolRuntime`
with a scripted backend that returns a `ToolTurn` carrying your `ToolCall`, as
`tests/test_agent_runtime_v2.py` does.

## Check it on a running hub

- `nerva inspect jarvis --section tools` — is it offered, to whom, gated or not, and
  which names were withheld for that principal (`--as guest`, `--as inbound`, ...).
- `nerva prompt-size` — what its schema costs every call.
- `nerva chat "use the <name> tool to ..."` with `llm.tool_loop_enabled` on, then
  `nerva tools -n 20` for the loop's trail (requested, started, result or failed).
- `nerva approvals list` for a gated tool's pending card.
- With `NERVA_SAVE_TRAJECTORIES=1`, `nerva sessions export <session> --sharegpt` shows
  the whole turn: your call's arguments, the result as the model read it, and the reply
  (`agents/core/trajectory.py`).

## Checklist

- [ ] It really is a tool, not a skill or an extension (the rule above).
- [ ] `agents/core/<name>_tool.py` with constants, schema and `register_<name>_tool`.
- [ ] Wired in `_wire_agent_tool_runtime`; job toolset entry if jobs may use it.
- [ ] `gated` / `untrusted_output` / `parallel_safe` declared on purpose.
- [ ] Refusals are `{"ok": False, "reason": ...}` dicts with machine reasons.
- [ ] `tests/_snapshots/tool_profiles.json` regenerated and the diff reviewed.
- [ ] Offline tests for schema, refusals and identity.
- [ ] A row in `docs/ARCHITECTURE.md`'s module index.
