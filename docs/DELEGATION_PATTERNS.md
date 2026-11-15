# Sub-Agent Delegation Patterns & Lifecycle API

Nerva provides two governed entry points for delegating bounded work to isolated sub-agents on top of `agents/core/subagents.py` (`SubAgentManager`):

1. **Model-callable tool (`delegate_task`)** — implemented in `agents/core/delegate_tool.py` (opt-in via `llm.delegate_task`, default `false`). Available only to an owner operator turn (`operator/owner`) and dynamically advertises live concurrency slots (`cap`, `active`, `free`), per-turn spawn limits, recursion depth, and child timeout.
2. **Plugin & Extension Lifecycle API (`SubagentLifecycleAPI`)** — implemented in `agents/core/subagent_lifecycle_api.py`. Gives plugins and host workflows a stable Python facade (`spawn`, `spawn_batch`, `list`, `get`, `steer`, `stop`, `collect`, `stats`) without importing `delegate_tool` or touching private `SubAgentManager` internals.

---

## Core Security & Isolation Guarantees

Every sub-agent started through `delegate_task` or `SubagentLifecycleAPI` obeys five non-negotiable rules:

1. **Never more privilege than its parent**: A child's tool allowlist is computed by `child_tool_allowlist(registered, parent_offer, blocked)` — strictly a subset of the parent turn's offered tools minus `DELEGATE_BLOCKED_CAPABILITIES` (no further delegation, no long-term memory writes, no skill proposals, no user prompts/messages, no scheduled jobs, and no board mutations). Any attempt in `SubagentLifecycleAPI` to request a tool outside `parent_offer` or inside the blocked set raises `SubagentLifecycleError("privilege_escalation_refused")`.
2. **Fresh session, zero parent transcript leakage**: Each child runs in `session::<spawn_id>` with only its explicit `goal`, optional `context`, and optional `output_schema`.
3. **Inherited taint & principal**: Children inherit the parent turn's `Principal`, `action_origin` (so tainted recall or web input stays tainted inside the child), and model/locality constraints (`JARVIS_STRICT_LOCAL` / `LOCAL_ONLY_AGENTS`).
4. **Untrusted output fencing**: Everything a child returns to a parent turn is marked `untrusted_output=True`, wrapped inside Nerva's untrusted-data fence, and validated against `output_schema` when supplied.
5. **Conversation-scoped supervision**: `list`, `steer`, `stop`, and `collect` only see and act upon children spawned by the same `(parent_agent, parent_session)`. Agent-origin steers (`origin="agent"`) guide the worker's next step and can never approve human inbox tasks (`SubAgentManager.decide` requires `origin="user"`).

---

## Using `SubagentLifecycleAPI` from a Plugin

```python
from agents.core.subagent_lifecycle_api import SubagentLifecycleAPI

api = SubagentLifecycleAPI.for_orchestrator(
    orch,
    parent_agent="jarvis",
    parent_offer=offered_tool_names,
    session_id=session_id,
    plugin_id="release-auditor",
)

# Inspect live host capacity before fan-out
capacity = api.stats()  # {"cap": 4, "active": 0, "free_slots": 4, ...}
```

---

## Five Canonical Delegation Patterns

### 1. Focused Single Specialist (Context-Isolated Read/Analysis)
Use `spawn(...)` when one sub-problem requires reading large files or search results whose intermediate bytes would pollute the parent's context window.

```python
outcome = await api.spawn(
    "Extract breaking config changes between v1.4 and v1.5",
    context="Inspect docs/CHANGELOG.md and agents/core/settings_db.py",
    output_schema={
        "type": "object",
        "required": ["breaking_keys"],
        "properties": {"breaking_keys": {"type": "array", "items": {"type": "string"}}},
    },
)
```

### 2. Parallel Fan-Out / Fan-In (`spawn_batch`)
Use `spawn_batch(...)` (or `delegate_task` with multiple `tasks`) to investigate independent modules concurrently up to `stats()["free_slots"]`. Keep each item's `context` self-contained so workers never contend on shared state.

```python
batch = await api.spawn_batch([
    {"goal": "Audit auth guards in routers/auth.py", "context": "Focus on token scopes"},
    {"goal": "Audit SSRF checks in http_client.py", "context": "Focus on redirect hops"},
])
```

### 3. Maker-Checker / Read-Only Verifier (`read_only=True`)
Pair an author step with an independent read-only verifier (`read_only=True, confine=repo_path`) that receives only read-only file inspection tools confined to the target directory and cannot mutate files or reach the network.

```python
review = await api.spawn(
    "Verify that every edited route preserves admin_guard",
    read_only=True,
    confine="/path/to/worktree",
)
```

### 4. Background Fire-and-Collect (`background=True` + `collect`)
Start long-running research asynchronously (`background=True`), continue foreground work, and later claim completed results once via `api.collect()` or `delegate_task` with `{"action": "collect"}`.

```python
started = await api.spawn("Index benchmark regressions across logs", background=True)
# ... perform other work ...
finished = await api.collect()
```

### 5. Steerable Iterative Worker (`list` / `steer` / `stop`)
For background sub-agents on steerable runners, inspect progress with `list`, refine direction mid-flight with `steer`, or cancel obsolete work early with `stop` to reclaim concurrency slots.

```python
running = api.list(status="running")
if running:
    child_id = running[0]["id"]
    api.steer(child_id, "Narrow focus to SQLite WAL lock timeouts only.")
    # Or cancel if no longer needed:
    api.stop(child_id, reason="superseded_by_new_scope")
```

For model turns, the same supervision verbs are exposed directly on `delegate_task`:
- `{"action": "list"}`
- `{"action": "steer", "spawn_id": "<id>", "message": "<guidance>"}`
- `{"action": "stop", "spawn_id": "<id>"}`
- `{"action": "collect"}`
