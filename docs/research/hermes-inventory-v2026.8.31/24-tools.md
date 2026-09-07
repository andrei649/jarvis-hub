# Tools (83) and Toolsets (59)

This shard is the exhaustive catalogue of every tool the Hermes Agent v2026.8.31 registry exposes to a
model (83 entries as returned by `tools.registry.registry.get_all_entries()` after
`discover_builtin_tools()`), every toolset defined in `toolsets.py` (59 static entries), and the registry
/ budget / guardrail machinery that decides which of them a given turn actually sees. Every tool entry
transcribes the *complete* JSON schema (name, type, enum, default, required, description) plus the
implementation, availability check, result caps and side effects read from the real source.
It deliberately leaves to sibling shards: the `hermes tools` curses UI and `/tools` slash command (CLI
shard), the Config-page toggles and `tools.*` config keys (config shard), the MCP server plumbing and
plugin loader (their own shards), and the deep provider matrices for browser / vision / image / video /
TTS backends (media shard) — this shard still lists all of those tools' parameters and gates.

Primary sources: `tools/registry.py`, `toolsets.py`, `tools/*.py` (83 `registry.register(...)` call
sites), `tools/budget_config.py`, `tools/tool_output_limits.py`, `agent/tool_guardrails.py`,
`agent/tool_result_classification.py`, `hermes_cli/toolset_scope.py`, plus the live dumps
`hermes_inv/tools_full.json` and `hermes_inv/tools_toolsets.json`.

---

## Part 0 — Registry, dispatch and budget mechanics

### Tool registry (`registry.register`)  `id: tools.registry-register`
- **Surface:** Core
- **Where:** `tools/registry.py:763` — every tool module calls `registry.register(...)` at module import time; nothing else declares tools.
- **What it does:** Declares one tool: its name, toolset membership, JSON schema, handler callable, availability check, env requirements, async flag, emoji, per-tool result cap and optional dynamic-schema hook. `model_tools.py` queries this registry instead of keeping parallel tables.
- **How it works:** `ToolEntry` (`tools/registry.py:1004`) is a `__slots__` record with fields `name, toolset, schema, handler, check_fn, requires_env, is_async, description, emoji, max_result_size_chars, dynamic_schema_overrides`. The registry singleton (`tools/registry.py:1290` `registry = ToolRegistry()`) keeps `self._tools` (process-global built-ins) plus `self._scoped_tools[scope]` overlays keyed on the resolved HERMES_HOME (`current_scope_key()` → `hermes_constants.hermes_home_key()`), merged by `_merged_tools()` with the scoped overlay winning. Every mutation bumps a monotonic `self._generation` counter that outside memos (e.g. `toolsets._resolve_toolset_memo`) key on. A `threading.RLock` serialises mutations so MCP refreshes cannot tear a reader's snapshot.
- **Inputs / options:** `name` (str), `toolset` (str), `schema` (dict, OpenAI function schema), `handler` (callable `(args, **kw)`), `check_fn` (callable → bool, default None), `requires_env` (list[str], default None→`[]`), `is_async` (bool, default False), `description` (str, default `""`→falls back to `schema["description"]`), `emoji` (str, default `""`), `max_result_size_chars` (int|float|None), `dynamic_schema_overrides` (zero-arg callable → dict), `override` (bool, default False), `scope` (str|None).
- **Outputs / side effects:** Inserts/replaces `target[name]`; records `self._toolset_checks[toolset] = check_fn` the first time a global toolset registers a check (used only for banner classification); increments `_generation`. Rejected registrations log at ERROR and return without mutating.
- **Config / env:** `plugins.entries.<plugin_id>.allow_tool_override: true` in config.yaml is the operator opt-in for plugin overrides. `HERMES_HOME` selects the scope key.
- **Edge cases / guards:** (a) A plugin registering a name that exists globally, in a scope, without `override=True` → logged `Tool registration REJECTED: plugin %r attempted to shadow global tool %r without override=True` and silently dropped. (b) With `override=True` but no `allow_tool_override` opt-in → `PermissionError`. (c) Cross-toolset shadowing without `override=True` → rejected with `Tool registration REJECTED: '%s' (toolset '%s') would shadow existing tool from toolset '%s'`. (d) Plugin ownership is bound to where the handler was *defined* (`handler.__globals__["__name__"]`), so lambdas/partials/wrappers cannot launder authorization (`_callable_module`, `tools/registry.py:667`). (e) A plugin module active in two profiles raises `PermissionError` from `_plugin_scope_of`.
- **Rebuild notes:** A dict of immutable entries + a generation counter + a lock is the whole mechanism; the value-add is the authorization model (define-site ownership, per-profile overlays, explicit override opt-in). A better version would make `ToolEntry` a frozen dataclass with a declared result contract and would validate schemas against JSON-Schema at register time instead of at first dispatch.

### Tool deregistration and restore  `id: tools.registry-deregister`
- **Surface:** Core
- **Where:** `tools/registry.py:868` (`deregister`), `tools/registry.py:955` (`restore_registration`), `tools/registry.py:545` (`snapshot_registration`).
- **What it does:** Removes a tool from the registry (used by MCP `notifications/tools/list_changed` nuke-and-repave and by plugin unload), or CAS-restores a previous entry.
- **How it works:** `deregister(name)` resolves the caller module via frame inspection (`_caller_module`, two frames up) because it has no handler to bind to. Toolsets whose name starts with `mcp-` are exempt from the ownership check. When the last tool of a toolset goes, its `_toolset_checks` entry and every alias pointing at it are dropped. `restore_registration(name, current, previous, scope=)` only restores when `target.get(name) is current` (identity check) so a newer registration from another plugin/profile is left alone, then rebuilds the affected toolsets' `check_fn` from surviving entries.
- **Inputs / options:** `deregister(name)`. `snapshot_registration(name, *, scope=None)` → local `ToolEntry` or None (no global fallback). `restore_registration(name, current, previous, *, scope=None)` → bool.
- **Outputs / side effects:** Mutates `_tools`/`_scoped_tools`, `_toolset_checks`, `_toolset_aliases`; bumps `_generation`; logs `Deregistered tool: %s` / `Restored tool registration: %s` at DEBUG.
- **Config / env:** `plugins.entries.<plugin>.allow_tool_override`.
- **Edge cases / guards:** A scoped plugin trying to deregister a process-global tool → `PermissionError: Scoped plugin module ... cannot deregister process-global tool ...`. A plugin deregistering a tool it does not own without opt-in → `PermissionError` and ERROR log naming the config key.
- **Rebuild notes:** Model plugin lifecycle as snapshot→register→restore triples; the identity CAS is what makes concurrent plugin reloads safe.

### Plugin tool-override policy  `id: tools.registry-plugin-override-policy`
- **Surface:** Core
- **Where:** `tools/registry.py:598` `register_plugin_override_policy`, `:614` `snapshot_plugin_override_policy`, `:624` `restore_plugin_override_policy`, `:645` `_plugin_override_allowed`, `:731` `plugin_scope_for_module`, `:735` `plugin_scope_for_callable`.
- **What it does:** Binds a plugin module namespace to the operator's current opt-in for replacing built-in tools, with identity-bearing generations so unload/reload can revoke a stale authorization.
- **How it works:** `_plugin_override_policy[(scope, namespace)] = _PluginOverridePolicy(allowed)`; `_plugin_module_scopes[namespace] = {scopes}` stays durable after the policy is removed so delayed callbacks remain profile-confined. `_plugin_namespace_of_module` resolves the longest matching registered namespace, and defensively treats anything under `hermes_plugins.` as plugin code (first two dotted segments).
- **Inputs / options:** `module_namespace` (str), `allowed` (bool), `scope` (str|None).
- **Outputs / side effects:** In-memory policy table only.
- **Config / env:** `plugins.entries.<plugin_id>.allow_tool_override`.
- **Edge cases / guards:** `restore_plugin_override_policy` returns False if the stored policy is not the same object (another generation won).
- **Rebuild notes:** Capability tokens keyed on (profile, plugin) with object identity are a clean way to express revocable authorization without a global mutable bool.

### Toolset aliases  `id: tools.registry-toolset-alias`
- **Surface:** Core
- **Where:** `tools/registry.py:572` `register_toolset_alias`, `:585` `get_registered_toolset_aliases`, `:590` `get_toolset_alias_target`.
- **What it does:** Maps a display alias (e.g. an MCP server name) onto a canonical registry toolset name (e.g. `mcp-<server>`), so `--toolsets <alias>` resolves.
- **How it works:** `self._toolset_aliases[alias] = toolset`; a collision logs `Toolset alias collision: '%s' (%s) overwritten by %s` and takes the newer value. `toolsets.get_toolset()` consumes aliases to synthesize `{"description": "MCP server '<alias>' tools", "tools": registry.get_tool_names_for_toolset(canonical), "includes": []}`.
- **Inputs / options:** `alias` (str), `toolset` (str).
- **Outputs / side effects:** Alias table; `_generation` bump; aliases are purged when the target toolset loses its last tool.
- **Config / env:** n/a
- **Edge cases / guards:** `toolsets.validate_toolset()` accepts alias names; `get_toolset(name, include_registry=False)` returns None for aliases (they have no static counterpart).
- **Rebuild notes:** Keep aliases out of the canonical set and resolve at lookup time; that keeps `get_toolset_names()` free of duplicates.

### Availability checks + TTL cache (`check_fn`)  `id: tools.registry-check-fn-cache`
- **Surface:** Core
- **Where:** `tools/registry.py:245`–`:445` (`_CHECK_FN_TTL_SECONDS`, `_check_fn_cached`, `invalidate_check_fn_cache`, `get_cached_check_fn_result`, `no_cache_check_fn`, `check_fn_cache_scope`).
- **What it does:** Runs each tool's `check_fn()` to decide whether the tool is offered this turn, caching the verdict ~30 s and absorbing transient probe failures.
- **How it works:** `_CHECK_FN_TTL_SECONDS = 30.0`; `_CHECK_FN_FAILURE_GRACE_SECONDS = 60.0`; `_CHECK_FN_CACHE_MAX = 512`. Cache key is `(fn, scope)`. A failure within 60 s of a recorded success is treated as a flake: the last-good `True` is served and the failure is NOT cached (logged `check_fn %s failed (%s) within %.0fs of last success; treating as transient and keeping tool(s) available`). Otherwise the failure is cached and logged `check_fn %s %s; dependent tools will be unavailable this turn`. `check_fn_cache_scope()` returns `CHECK_FN_CACHE_BYPASS` (`""`) when the session has all three of `HERMES_SESSION_ID`, `HERMES_BROWSER_CONTROL_PRINCIPAL`, `HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY` set (bound browser-control request), returns `None` for single-profile processes, and the resolved HERMES_HOME override path under multiplex; any failure to resolve identity fails closed to bypass. `no_cache_check_fn(fn)` marks a local config-backed probe as never cached.
- **Inputs / options:** n/a (internal). `invalidate_check_fn_cache()` after `hermes tools enable`. `get_cached_check_fn_result(fn)` reads without probing (dashboard panels).
- **Outputs / side effects:** In-process caches `_check_fn_cache`, `_check_fn_last_good`; WARNING logs.
- **Config / env:** `HERMES_HOME`, `HERMES_SESSION_ID`, `HERMES_BROWSER_CONTROL_PRINCIPAL`, `HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY`.
- **Edge cases / guards:** An exception inside a `check_fn` is caught, logged with `exc_info`, and treated as False (subject to grace). Pruning drops entries past TTL/grace and hard-caps both dicts at 512.
- **Rebuild notes:** Probe caching with a "last-known-good grace window" is the key trick — it prevents a flaky `docker version` timeout from silently stripping the whole file+terminal toolset from a subagent mid-run.

### Schema assembly (`get_definitions`) and dynamic schemas  `id: tools.registry-get-definitions`
- **Surface:** Core
- **Where:** `tools/registry.py:997`.
- **What it does:** Turns a set of tool names into the OpenAI-format `[{"type":"function","function":{…}}]` array sent to the model, filtered by availability and patched by runtime overrides.
- **How it works:** Iterates `sorted(tool_names)`; skips entries whose cached `check_fn` is False (logging `Tool %s unavailable (check failed)` at DEBUG unless `quiet=True`); forces `schema["name"] = entry.name`; then, if `entry.dynamic_schema_overrides` is set, calls it and shallow-merges the returned dict over the schema. An exception in the override hook logs `dynamic_schema_overrides for tool %s raised %s; using static schema` and falls back to the static schema.
- **Inputs / options:** `tool_names: Set[str]`, `quiet: bool = False`.
- **Outputs / side effects:** Returns a list of function definitions. No mutation.
- **Config / env:** Callers (`model_tools.get_tool_definitions`) memoize on config.yaml mtime+size, so config changes invalidate.
- **Edge cases / guards:** Tools registered with a dynamic hook in v2026.8.31: `browser_exec` (`_dynamic_schema_overrides`, `tools/browser_use_cli.py`), `delegate_task` (`_build_dynamic_schema_overrides`), `image_generate` (`_build_dynamic_image_schema`), `video_generate` (`_build_dynamic_video_schema`), `memory` (`_build_memory_schema_overrides`), `patch` (`_patch_schema_overrides`), `read_file` (`_read_file_schema_overrides`). 7 of 83.
- **Rebuild notes:** Keep the override hook zero-arg and shallow-merged; anything deeper makes schema caching unreliable.

### Tool dispatch and result contract  `id: tools.registry-dispatch`
- **Surface:** Core
- **Where:** `tools/registry.py:1104` (`_normalize_handler_result`), `:1136` (`dispatch`).
- **What it does:** Executes a tool handler by name, bridging async handlers, normalising the return value, and converting every exception into a JSON `{"error": …}` string.
- **How it works:** `dispatch(name, args, *, scope=None, **kwargs)` looks up the entry; if `entry.is_async` it calls `model_tools._run_async(entry.handler(args, **kwargs))`, else calls the handler directly. Results must be either a `str` or the multimodal envelope `{"_multimodal": True, "content": [...]}`; anything else is logged `Tool %s handler returned unsupported result type: %s` and returned as `tool_error(..., error_type="tool_result_contract", tool=…, result_type=…)`. Exceptions produce `Tool execution failed: <Type>: <msg>` routed through `model_tools._sanitize_tool_error` (strips framing tokens/CDATA/fences) before `tool_error`.
- **Inputs / options:** `name`, `args` dict, `scope`, arbitrary `**kwargs` forwarded to the handler (commonly `task_id`, `session_id`, `callback`, `store`, `db`, `current_session_id`, `parent_agent`).
- **Outputs / side effects:** JSON string or multimodal dict. `Unknown tool: {name}` for an unregistered name.
- **Config / env:** n/a
- **Edge cases / guards:** Error bodies are bounded: `_MAX_TOOL_ERROR_CHARS = 2048` with marker `"… [truncated]"`, logs keep `_MAX_LOGGED_ERROR_CHARS = 8192`. `_bound_json_error_result` additionally trims an oversized `"error"` field in handlers that serialised the exception themselves.
- **Rebuild notes:** Two return shapes only (string | multimodal envelope) keeps logging/budgeting/persistence simple; bound error text at the dispatch boundary so retries can't stack unbounded exception dumps into context.

### Per-tool / per-turn result budget  `id: tools.registry-result-budget`
- **Surface:** Core
- **Where:** `tools/budget_config.py`; consumed by `tools/tool_result_storage.py` and `registry.get_max_result_size` (`tools/registry.py:1194`).
- **What it does:** Decides when a tool result is too large to keep inline: oversized results are persisted to disk and replaced by a preview.
- **How it works:** Priority in `BudgetConfig.resolve_threshold(tool_name)`: pinned → `tool_overrides` → `mcp_` prefix → registry per-tool `max_result_size_chars` (capped at `default_result_size`) → default. `PINNED_THRESHOLDS = {"read_file": inf}` (prevents persist→read→persist loops). Defaults: `DEFAULT_RESULT_SIZE_CHARS = 100_000`, `DEFAULT_TURN_BUDGET_CHARS = 200_000`, `DEFAULT_PREVIEW_SIZE_CHARS = 1_500`, `DEFAULT_MCP_RESULT_SIZE_CHARS = 50_000`, `MCP_TOOL_PREFIX = "mcp_"`. `budget_for_context_window(context_length)` scales: `window_chars = context_length * 4`, per-result `15%`, per-turn `30%`, clamped between floors `_MIN_RESULT_SIZE_CHARS = 8_000` / `_MIN_TURN_BUDGET_CHARS = 16_000` and the historical defaults as caps.
- **Inputs / options:** `BudgetConfig(default_result_size, turn_budget, preview_size, mcp_result_size, tool_overrides)`.
- **Outputs / side effects:** Threshold numbers only; the storage layer does the spilling.
- **Config / env:** `tool_budget.mcp_result_size_chars` (positive int; anything else falls back to 50 000).
- **Edge cases / guards:** Tools that register `max_result_size_chars=100000` in v2026.8.31: `execute_code`, `patch`, `read_file`, `search_files`, `terminal`, `web_extract`, `web_search`, `write_file`, `x_search` (9 of 83). All other tools use the default.
- **Rebuild notes:** Scale the cap to the model's context window, not to a fixed constant, and always spill rather than truncate so the full payload stays recoverable.

### Tool-output truncation limits  `id: tools.registry-output-limits`
- **Surface:** Config
- **Where:** `tools/tool_output_limits.py`.
- **What it does:** Central, config-tunable truncation numbers shared by `terminal` (stdout cap) and `read_file` (pagination + per-line cap).
- **How it works:** `get_tool_output_limits()` reads the `tool_output` block from config once and caches it for the process (`_cached_limits`); any error falls back to defaults. Helpers `get_max_bytes()`, `get_max_lines()`, `get_max_line_length()`; `_reset_tool_output_limits_cache()` for tests/hot reload. Non-int or non-positive values fall back per key (`_coerce_positive_int`).
- **Inputs / options:** n/a (read-only API).
- **Outputs / side effects:** Dict `{"max_bytes", "max_lines", "max_line_length"}`.
- **Config / env:** `tool_output.max_bytes` (default 50 000 — `terminal_tool.MAX_OUTPUT_CHARS`), `tool_output.max_lines` (default 2000 — `file_operations.MAX_LINES`), `tool_output.max_line_length` (default 2000).
- **Edge cases / guards:** Never raises; cached for the process lifetime, so a live config edit needs a restart (or the test reset hook).
- **Rebuild notes:** One module owning the constants beats duplicating them in each tool file; make the cache invalidate on config mtime instead of process lifetime.

### Tool-call loop guardrails  `id: tools.guardrails-loop`
- **Surface:** Core
- **Where:** `agent/tool_guardrails.py` (854 lines); config block `tool_loop_guardrails` parsed by `ToolCallGuardrailConfig.from_mapping` (`agent/tool_guardrails.py:127`).
- **What it does:** Watches per-turn tool calls and decides when to warn the model about repeated failures / no-progress loops, and (opt-in) when to hard-stop the turn.
- **How it works:** Classifies tools into `IDEMPOTENT_TOOL_NAMES` (read_file, search_files, web_search, web_extract, session_search, browser_snapshot, browser_console, browser_get_images, mcp_filesystem_read_file, mcp_filesystem_read_text_file, mcp_filesystem_read_multiple_files, mcp_filesystem_list_directory, mcp_filesystem_list_directory_with_sizes, mcp_filesystem_directory_tree, mcp_filesystem_get_file_info, mcp_filesystem_search_files) and `MUTATING_TOOL_NAMES` (terminal, execute_code, write_file, patch, todo, memory, skill_manage, browser_click, browser_type, browser_press, browser_scroll, browser_navigate, send_message, cronjob, delegate_task, process). Pollers are exempt from the identical-call notice: `STALL_GUARD_REPEATABLE_TOOLS = {"process"}` plus any name ending in `_get_result` or `_poll`. The notice fires on the 3rd consecutive identical call (`STALL_GUARD_IDENTICAL_CALL_THRESHOLD = 3`); from the 2nd byte-identical result, payloads ≥ `IDENTICAL_RESULT_STUB_MIN_CHARS = 512` are replaced by a reference stub carrying the first 120 chars of canonical args (`_RESULT_STUB_ARGS_PREVIEW_CHARS`), and error results are never stubbed.
- **Inputs / options:** Config fields: `warnings_enabled` (default true), `hard_stop_enabled` (default false), `warn_after.exact_failure` (2), `hard_stop_after.exact_failure` (5), `warn_after.same_tool_failure` (3), `hard_stop_after.same_tool_failure` (8), `warn_after.no_progress` (2), `hard_stop_after.no_progress` (5), plus `idempotent_tools`, `mutating_tools`, `loop_caps`.
- **Outputs / side effects:** Decisions only — the module is side-effect free; runtime code turns them into guidance text, synthetic tool results, or turn halts.
- **Config / env:** `tool_loop_guardrails.*` in config.yaml.
- **Edge cases / guards:** Warnings never block execution; hard stops are opt-in so interactive CLI/TUI sessions only get a nudge.
- **Rebuild notes:** Hash (tool, canonical args, result) per turn; warn at 3, stub duplicate payloads at 2, and never stub errors — the model must see each fresh failure verbatim.

### Tool result classification (side-effect / mutation)  `id: tools.result-classification`
- **Surface:** Core
- **Where:** `agent/tool_result_classification.py` (40 lines).
- **What it does:** Answers two questions the interrupt/checkpoint machinery needs: "is it safe to discard this dangling tool call?" and "did this file write actually land?"
- **How it works:** `NO_EFFECT_TOOL_NAMES = {read_file, search_files, session_search, skill_view, skills_list, web_extract, web_search, vision_analyze, browser_snapshot, browser_get_images, browser_console, read_terminal}` — `tool_may_have_side_effect(name)` is simply `name not in` that set, so unknown / plugin / MCP tools stay effect-capable by default. `FILE_MUTATING_TOOL_NAMES = {write_file, patch}`; `file_mutation_result_landed(name, result)` JSON-parses the result and returns True when `write_file` produced a `bytes_written` key or `patch` produced `success: true`, and False on any error field or parse failure.
- **Inputs / options:** `tool_name: str`, `result: Any`.
- **Outputs / side effects:** Booleans only.
- **Config / env:** n/a
- **Edge cases / guards:** Fail-safe direction: unknown tools are assumed to have effects; an unparseable result is assumed not to have landed.
- **Rebuild notes:** Keep the allowlist tiny and explicit; defaulting to "might have side effects" is what makes interrupt-and-resume safe.

### Per-platform toolset scope restrictions  `id: tools.toolset-scope`
- **Surface:** Core
- **Where:** `hermes_cli/toolset_scope.py` (20 lines).
- **What it does:** Declares which toolsets are only valid on specific platforms, so config validation and runtime resolution agree.
- **How it works:** `_TOOLSET_PLATFORM_RESTRICTIONS = {"discord": {"discord"}, "discord_admin": {"discord"}}`; `toolset_allowed_for_platform(ts_key, platform)` returns True when the toolset has no restriction entry, else `platform in allowed`.
- **Inputs / options:** `ts_key: str`, `platform: str`.
- **Outputs / side effects:** Boolean.
- **Config / env:** n/a
- **Edge cases / guards:** Only two toolsets are restricted in v2026.8.31; every other toolset is available on every platform.
- **Rebuild notes:** Keep the restriction table separate from tool resolution so a config linter and the runtime can share one policy.

### Toolset resolution (`resolve_toolset`)  `id: tools.toolset-resolve`
- **Surface:** Core
- **Where:** `toolsets.py:735` (`resolve_toolset`), `:637` (`get_toolset`), `:857` (`resolve_multiple_toolsets`), `:897` (`get_all_toolsets`), `:922` (`get_toolset_names`), `:946` (`validate_toolset`), `:962` (`create_custom_toolset`), `:984` (`get_toolset_info`), `:704` (`bundle_non_core_tools`).
- **What it does:** Expands a toolset name into the flat list of tool names it grants, following `includes` recursively and merging plugin/MCP tools registered into that toolset.
- **How it works:** `get_toolset(name, include_registry=True)` merges the static `TOOLSETS[name]["tools"]` with `registry.get_tool_names_for_toolset(name)`; with `include_registry=False` it returns only the static copy (used by platform reverse-mapping so a registry-added tool cannot drop a toolset from inference, issue #49622). Names `all` / `*` expand to the union of every toolset. Cycles and diamonds return `[]` silently. An unknown `hermes-<x>` name auto-synthesizes `_HERMES_CORE_TOOLS` plus registry tools of toolset `<x>` when `gateway.platform_registry.platform_registry.is_registered(x)`. Results are memoized in `_resolve_toolset_memo` keyed `(name, include_registry, id(registry), registry._generation)`, cleared when it reaches 256 entries. `bundle_non_core_tools(name)` returns a `hermes-*` bundle's non-core delta so disabling a bundle doesn't strip shared core tools (#33924).
- **Inputs / options:** `resolve_toolset(name, visited=None, *, include_registry=True)`; `resolve_multiple_toolsets(list)`; `create_custom_toolset(name, description, tools=None, includes=None)`; `get_toolset_info(name)` → `{name, description, direct_tools, includes, resolved_tools, tool_count, is_composite}`.
- **Outputs / side effects:** Sorted list of tool names; `create_custom_toolset` mutates the module-level `TOOLSETS` dict at runtime.
- **Config / env:** `toolsets:` list and `custom_toolsets:` map in config.yaml; `hermes chat --toolsets a,b,c`.
- **Edge cases / guards:** `validate_toolset` accepts `all`, `*`, any static name, any plugin toolset name, and any registered alias. `TOOLSETS["coding"]` carries `"posture": True` marking it as a per-session posture toolset never auto-recovered into per-platform tool config.
- **Rebuild notes:** Composition + a generation-keyed memo is enough; the subtle bit is `include_registry=False` for reverse inference and the core-preserving `bundle_non_core_tools` subtraction.

---

## Part 1 — Tools (83)

Ordered alphabetically by tool name (as `registry.get_all_tool_names()` returns them), with two
deliberate groupings: the 14 `kanban_*` tools are preceded by one shared entry covering their common
gating and board resolution, and `write_file` is placed beside its `file`-toolset siblings.

### annotate_preview  `id: tools.tool-annotate-preview`
- **Surface:** Tool
- **Where:** Model-callable tool `annotate_preview`, toolset `desktop_ui`, emoji 🔖. Only present in Hermes desktop-app sessions.
- **What it does:** Draws a LASTING outline (optionally captioned) around one element in the desktop preview pane's page, or freezes the whole visible field, or removes one/all marks. Unlike `drive_preview`'s transient move-marks, annotations persist until removed.
- **How it works:** `tools/annotate_preview_tool.py:41` `annotate_preview_tool()`. `ACTIONS = ("add","hold","remove","clear")`; wire verbs `WIRE = {"add":"pin","hold":"hold","remove":"unpin","clear":"unpin"}` (clear = unpin with no target = "all"). It rides the same `preview.act` renderer bridge as `drive_preview` — the tool builds a payload `{action, ref, selector, text}` (dropping None values; `ref`/`selector` are stripped for `clear`/`hold`) and calls the platform-injected `callback` (`kw["callback"]`, wired by `tui_gateway`). The renderer resolves `@e`-style refs and owns the overlay. Marks are bound to elements, not coordinates, so they ride scroll/reflow and die with their element; navigation clears them. Registered at `tools/annotate_preview_tool.py:127`.
- **Inputs / options:** `action` (string, optional, enum `add`|`hold`|`remove`|`clear`, "Defaults to 'add'."); `ref` (string, optional, "Ref from drive_preview elements."); `selector` (string, optional, "CSS selector fallback. Prefer ref."); `label` (string, optional, "Optional caption, e.g. 'cheapest'."). `required: []`.
- **Outputs / side effects:** Renderer overlay changes in the preview pane. Returns the renderer's JSON verbatim, or `{"text": "<raw>"}` when the answer is not JSON.
- **Config / env:** No config keys. Availability is decided by the `desktop_ui` toolset being folded in by `tui_gateway/server.py::_load_enabled_toolsets` for desktop-sourced sessions. `HERMES_UI_SESSION_ID` routes the event to the owning window (`tools/desktop_ui.py:38`).
- **Edge cases / guards:** No callback → `{"error":"annotate_preview is only available in the Hermes desktop app."}`. Invalid action → `action must be one of: add, hold, remove, clear.`. `add`/`remove` without `ref` or `selector` → `<verb> needs a ref from drive_preview action='elements' (e.g. 'btn-sign-in') or a CSS selector.`. Empty/timed-out renderer answer → `The annotation timed out, or no GUI window answered. Open a page with open_preview first.` Callback exception → `Failed to annotate the in-app browser: <exc>`.
- **Rebuild notes:** One overlay channel, element-bound marks, four verbs. A better version would persist annotations across navigation when the element can be re-resolved, and expose them as readable state so the model can list what it has marked.

### apply_layout  `id: tools.tool-apply-layout`
- **Surface:** Tool
- **Where:** Model-callable tool `apply_layout`, toolset `desktop_ui`, emoji 🧱. Desktop app only.
- **What it does:** Applies a saved layout preset to the Hermes desktop workspace (rearranges panes) when the user asks for it.
- **How it works:** `tools/apply_layout_tool.py:28` `apply_layout_tool(preset)` → `desktop_ui.emit("layout.apply", {"preset": name})` (`tools/desktop_ui.py:31`). The renderer resolves the preset id against its layouts registry (core presets + plugin presets + user-saved presets are one list) and applies the tree through the same code path as the layout picker. Only the active window's session may act, so a background turn cannot rearrange the user's desktop. Preset ids are deliberately free-form; the renderer answers with the applied id/title or, for an unknown id, the list of available ids so the model can self-correct without a listing tool. Registered at `tools/apply_layout_tool.py:65`.
- **Inputs / options:** `preset` (string, REQUIRED) — "Layout preset id to apply (e.g. 'default', 'focus', 'terminal-deck', 'quad', or a user/plugin preset id)." Built-ins named in the description: `default` (chat + sidebars), `focus` (chat only), `terminal-deck`, `quad`.
- **Outputs / side effects:** Desktop pane tree changes. Returns `{"success": true, "preset": "<name>"}`.
- **Config / env:** none; `HERMES_UI_SESSION_ID` window routing.
- **Edge cases / guards:** Empty preset → `preset is required — a layout preset id, e.g. 'default' or 'focus'.`. No emitter (non-desktop) → `Layout apply is only available in the Hermes desktop app.`. Emit exception → `Failed to apply layout '<name>': <exc>`. To reveal ONE pane the description tells the model to use `focus_pane` instead.
- **Edge cases / guards (registry vs toolsets.py):** `apply_layout` registers into toolset `desktop_ui` but is NOT listed in `TOOLSETS["desktop_ui"]["tools"]` (`toolsets.py:257`); it only reaches an agent through `get_toolset()`'s registry merge. Documented discrepancy.
- **Rebuild notes:** Fire-and-forget emit + a free-form id namespace shared by core/plugin/user presets; error responses that enumerate valid ids are the cheap alternative to a second discovery tool.

### browser_back  `id: tools.tool-browser-back`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_back`, toolset `browser`, emoji ◀️.
- **What it does:** Navigates the automated browser back one entry in history.
- **How it works:** `tools/browser_tool.py:4660` `browser_back(task_id)`; registered at `tools/browser_tool.py:6437` behind `routed_browser_handler("browser_back", args, fallback=…, task_id=…, session_id=…)` (`tools/browser_extension_router.py`). The router decides per invocation whether an attached browser-extension controller executes the command or the legacy backend does; once a controller is selected the legacy backend is never retried. Availability: `check_browser_back_requirements()` → `check_browser_routed_requirements("browser_back")` → `check_browser_requirements() or extension_controller_available("browser_back")` (`tools/browser_tool.py:6338`).
- **Inputs / options:** none (`properties: {}`, `required: []`).
- **Outputs / side effects:** Browser history moves; returns the post-navigation page state as JSON.
- **Config / env:** `browser.backend`, `browser.cdp_url`, `browser.cloud_provider`, `browser.extension_control.enabled` (default false); `BROWSER_CDP_URL`.
- **Edge cases / guards:** Description states "Requires browser_navigate to be called first." Hidden entirely when `browser.backend` resolves to Browser Use CLI mode (`_is_browser_use_cli_mode()` → `check_browser_requirements()` returns False).
- **Rebuild notes:** Keep history as a backend verb rather than re-navigating a stored URL — SPA history entries are not URLs.

### browser_cdp  `id: tools.tool-browser-cdp`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_cdp`, toolset `browser-cdp` (note: NOT `browser`), emoji 🧪.
- **What it does:** Sends a raw Chrome DevTools Protocol command — the escape hatch for browser operations the dedicated `browser_*` tools do not cover.
- **How it works:** `tools/browser_cdp_tool.py` (744-line module); handler registered at `tools/browser_cdp_tool.py:743` via `routed_browser_handler("browser_cdp", …)`. Availability `_browser_cdp_check()` (`tools/browser_cdp_tool.py:710`) requires `check_browser_requirements()` AND a raw (no-I/O) CDP override URL from `_get_cdp_override_raw()` — i.e. `/browser connect` having set `BROWSER_CDP_URL`, or `browser.cdp_url` in config.yaml. Calls without `frame_id` are stateless and independent (no session/event persistence); with `frame_id` the call is routed through the CDP supervisor's live session for that out-of-process iframe, which is the only reliable path on Browserbase where per-call signed URLs rotate.
- **Inputs / options:** `method` (string, REQUIRED) — "CDP method name, e.g. 'Target.getTargets', 'Runtime.evaluate', 'Page.handleJavaScriptDialog'."; `params` (object, optional) — "Method-specific parameters as a JSON object. Omit or pass {} for methods that take no parameters."; `target_id` (string, optional) — tab id from `Target.getTargets`, mutually exclusive with `frame_id`; `frame_id` (string, optional) — OOPIF frame id from `browser_snapshot.frame_tree.children[]` where `is_oopif=true`; `timeout` (number, optional, default `30`) — "Timeout in seconds (default 30, max 300)."
- **Outputs / side effects:** Whatever the CDP method returns, as JSON. Side effects are the CDP method's own (navigation, cookies, dialog handling, viewport overrides…).
- **Config / env:** `browser.cdp_url`; `BROWSER_CDP_URL` (set by `/browser connect`).
- **Edge cases / guards:** Usage rules from the schema description: browser-level methods (`Target.*`, `Browser.*`, `Storage.*`) omit both ids; page-level methods (`Page.*`, `Runtime.*`, `DOM.*`, `Emulation.*`, tab-scoped `Network.*`) pass `target_id`; cross-origin iframe scope passes `frame_id`. Not wired for cloud backends (Browserbase, Browser Use, Firecrawl) live-session routing; Camofox is REST-only and will never support CDP. If the tool appears at all, an endpoint is already reachable.
- **Rebuild notes:** Gate the escape hatch on a *raw* (non-probing) endpoint check so schema assembly never blocks on HTTP; route iframe-scoped calls through a persistent supervisor connection.

### browser_click  `id: tools.tool-browser-click`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_click`, toolset `browser`, emoji 👆.
- **What it does:** Clicks the element identified by a snapshot ref id.
- **How it works:** `tools/browser_tool.py:4513` `browser_click(ref, task_id)`; registered `tools/browser_tool.py:6398` through `routed_browser_handler`. Gate: `check_browser_click_requirements()` → `check_browser_routed_requirements("browser_click")`.
- **Inputs / options:** `ref` (string, REQUIRED) — "The element reference from the snapshot (e.g., '@e5', '@e12')".
- **Outputs / side effects:** Page interaction; JSON result describing the click outcome / new page state.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate and browser_snapshot to be called first." Ref ids are shown in square brackets in snapshot output. Classified as a MUTATING tool by `agent/tool_guardrails.py` (loop guardrails treat repeats as mutations, not idempotent reads).
- **Rebuild notes:** Ref-based addressing (stable per snapshot) instead of CSS selectors is what makes multi-step page work reliable for an LLM.

### browser_console  `id: tools.tool-browser-console`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_console`, toolset `browser`, emoji 🖥️.
- **What it does:** Returns the page's console output (`console.log/warn/error/info`) and uncaught JS exceptions; with `expression`, evaluates JavaScript in the page context and returns the JSON-serialised result.
- **How it works:** `tools/browser_tool.py:4763` `browser_console(clear, expression, task_id)`; registered `tools/browser_tool.py:6490` via `routed_browser_handler`. Gate: `check_browser_requirements` (the plain one, not the routed variant).
- **Inputs / options:** `clear` (boolean, optional, default `False`) — "If true, clear the message buffers after reading"; `expression` (string, optional) — "JavaScript expression to evaluate in the page context. Runs in the browser like DevTools console — full access to DOM, window, document. Return values are serialized to JSON. Example: 'document.title' or 'document.querySelectorAll(\"a\").length'".
- **Outputs / side effects:** Console buffer contents; with `clear=true` the buffers are emptied (a real side effect). Evaluated expressions can mutate the page.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate to be called first." Listed in both `IDEMPOTENT_TOOL_NAMES` (guardrails) and `NO_EFFECT_TOOL_NAMES` (result classification) despite `clear`/`expression` being able to mutate — a deliberate optimisation for the common read-only use.
- **Rebuild notes:** Bundling "read console" and "eval JS" into one tool halves the schema cost; a better version would separate the mutating eval path so the guardrail classification stays honest.

### browser_dialog  `id: tools.tool-browser-dialog`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_dialog`, toolset `browser-cdp`, emoji 💬.
- **What it does:** Accepts or dismisses a native JavaScript dialog (`alert` / `confirm` / `prompt` / `beforeunload`) currently blocking the page.
- **How it works:** `tools/browser_dialog_tool.py`, handler registered at `:136`; direct handler (no extension router). Availability `_browser_dialog_check()` (`tools/browser_dialog_tool.py:120`) delegates to `tools.browser_cdp_tool._browser_cdp_check` so `browser_cdp` and `browser_dialog` appear and disappear together. Workflow: `browser_snapshot` surfaces open dialogs in its `pending_dialogs` field with `id`, `type`, `message`; this tool then answers one.
- **Inputs / options:** `action` (string, REQUIRED, enum `accept`|`dismiss`) — "'accept' clicks OK / returns the prompt text. 'dismiss' clicks Cancel / returns null from prompt(). For ``beforeunload`` dialogs: 'accept' allows the navigation, 'dismiss' keeps the page."; `prompt_text` (string, optional) — "Response string for a ``prompt()`` dialog. Ignored for other dialog types. Defaults to empty string."; `dialog_id` (string, optional) — "Specific dialog to respond to, from ``browser_snapshot.pending_dialogs[].id``. Required only when multiple dialogs are queued."
- **Outputs / side effects:** Unblocks the page; JSON outcome.
- **Config / env:** `browser.cdp_url`; `BROWSER_CDP_URL`.
- **Edge cases / guards:** Only present when a CDP-capable backend is attached — Browserbase sessions, a local Chromium-family browser via `/browser connect`, or `browser.cdp_url`. Not available on Camofox (REST-only) or the default Playwright local browser (CDP port hidden).
- **Rebuild notes:** Surface pending dialogs in the snapshot rather than requiring a poll; a dialog that blocks the page must be discoverable from the tool the model already calls.

### browser_exec  `id: tools.tool-browser-exec`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_exec`, toolset `browser-use`, emoji 🌐. Replaces the whole `browser_*` surface when the Browser Use CLI backend is active (the default when the CLI is runnable).
- **What it does:** Runs arbitrary Python (stdlib + pre-imported browser helpers) against a persistent Browser Use CLI session; stdout comes back in the result.
- **How it works:** `tools/browser_use_cli.py` (1000+ lines), registered at `:1056` with `check_fn=is_browser_use_cli_mode` (`:216`) and `dynamic_schema_overrides=_dynamic_schema_overrides` (the description mutates to report install state — the live dump ends with "(The browser-use CLI is not installed yet. Install it with `uv tool install browser-use`.)"). `is_browser_use_cli_mode()` returns False when Camofox is active; otherwise returns `backend == "browser-use"` when `browser.backend` is set, True when a legacy Browser-Use cloud config is present, and otherwise True when `_find_cli()` locates a runnable CLI (installed binary or `uvx`). Browser session and workspace persist across calls; the Python interpreter does NOT (fresh each call). Workspace dir is `$BH_AGENT_WORKSPACE`, echoed as `workspace` in every result; functions in `agent_helpers.py` there are auto-imported. Handler also accepts an undocumented `local` boolean (`args.get("local", False)`) not present in the published schema.
- **Inputs / options:** `code` (string, REQUIRED) — "Python code to execute using the pre-imported browser helpers. Use print(...) for any data you need back."; `session` (string, optional) — "Named isolated browser session — its own daemon and (on cloud backends) own browser, so concurrent tasks don't share tabs. Reuse the same name on every related call; omit for the shared default session."; `timeout_s` (integer, optional, default `300`) — "Max seconds to wait for the code to finish (default 300, max 1800)." Pre-imported helpers named in the schema: `new_tab(url)`, `goto_url(url)`, `wait_for_load()`, `page_info()`, `js(expr)`, `fill_input(selector, text)`, `click_at_xy(x, y)`, `capture_screenshot()`, `cdp('Domain.method', **kwargs)`, `ensure_real_tab()`.
- **Outputs / side effects:** stdout of the executed code; files written into `$BH_AGENT_WORKSPACE`; real browser navigation/interaction. The first comment line of `code` (max 60 chars) is used verbatim as the UI step label.
- **Config / env:** `browser.backend` (`""` default → Browser Use when runnable; `browser-use`; `off` for built-in tools), `BH_AGENT_WORKSPACE`.
- **Edge cases / guards:** Schema instructs: batch each sub-procedure into one call; prefer several medium calls appending to workspace files over one giant call so progress survives timeouts; for "all N items" tasks append batches to JSON/CSV and aggregate in Python; `js('() => {...}')` returns the uncalled function — wrap as `js('(() => {...})()')`; login walls → stop and ask the user, never guess credentials. `cdp('Accessibility.getFullAXTree')['nodes']` is thousands of nodes — filter in Python before printing.
- **Rebuild notes:** A code-execution browser tool collapses N round-trips into one; the two design rules that make it work are (a) persistent browser + ephemeral interpreter, and (b) a durable workspace directory so partial progress survives a timeout.

### browser_get_images  `id: tools.tool-browser-get-images`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_get_images`, toolset `browser`, emoji 🖼️.
- **What it does:** Lists every image on the current page with its URL and alt text, so the model can pick one to hand to `vision_analyze`.
- **How it works:** `tools/browser_tool.py:5338` `browser_get_images(task_id)`; registered `:6464` via `routed_browser_handler`; gate `check_browser_requirements`.
- **Inputs / options:** none.
- **Outputs / side effects:** JSON list of `{url, alt}`-shaped entries. No page mutation.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate to be called first." In both `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Trivial but valuable: it turns "look at that picture" into a two-tool pipeline without screenshots.

### browser_navigate  `id: tools.tool-browser-navigate`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_navigate`, toolset `browser`, emoji 🌐.
- **What it does:** Opens a URL in the automated browser, initialising the session, and returns a compact page snapshot with interactive elements and ref ids.
- **How it works:** `tools/browser_tool.py:4175` `browser_navigate(url, task_id)`; registered `:6371` via `routed_browser_handler`; gate `check_browser_navigate_requirements` → routed. Because navigate already returns a compact snapshot, a follow-up `browser_snapshot` is unnecessary.
- **Inputs / options:** `url` (string, REQUIRED) — "The URL to navigate to (e.g., 'https://example.com')".
- **Outputs / side effects:** Launches/reuses the browser session; loads the page; returns snapshot JSON.
- **Config / env:** `browser.backend`, `browser.cloud_provider`, `browser.cdp_url`, `browser.extension_control.enabled`.
- **Edge cases / guards:** The description actively steers away from the browser: prefer `web_search`/`web_extract` for simple retrieval; for plain-text endpoints (`.md`, `.txt`, `.json`, `.yaml`, `.yml`, `.csv`, `.xml`, `raw.githubusercontent.com`, any documented API endpoint) prefer `curl` via `terminal` or `web_extract`. Classified MUTATING in the loop guardrails.
- **Rebuild notes:** Returning the snapshot from navigate (instead of forcing a second call) is a measurable round-trip saving; putting the "don't use me for X" guidance in the tool description is how you keep an expensive tool from being the default.

### browser_press  `id: tools.tool-browser-press`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_press`, toolset `browser`, emoji ⌨️.
- **What it does:** Presses a single keyboard key in the page — form submission (Enter), focus movement (Tab), shortcuts.
- **How it works:** `tools/browser_tool.py:4711` `browser_press(key, task_id)`; registered `:6450` via `routed_browser_handler`; gate `check_browser_press_requirements` → routed.
- **Inputs / options:** `key` (string, REQUIRED) — "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')".
- **Outputs / side effects:** Keystroke delivered to the page; JSON result.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate to be called first." MUTATING in guardrails.
- **Rebuild notes:** Accept Playwright-style key names verbatim so the model can reuse familiar identifiers.

### browser_scroll  `id: tools.tool-browser-scroll`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_scroll`, toolset `browser`, emoji 📜.
- **What it does:** Scrolls the page up or down to reveal content outside the viewport.
- **How it works:** `tools/browser_tool.py:4611` `browser_scroll(direction, task_id)` (handler defaults `direction` to `"down"`); registered `:6424` via `routed_browser_handler`; gate `check_browser_scroll_requirements` → routed.
- **Inputs / options:** `direction` (string, REQUIRED, enum `up`|`down`) — "Direction to scroll".
- **Outputs / side effects:** Viewport moves; JSON result.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate to be called first." MUTATING in guardrails. No pixel-amount parameter (unlike the desktop `drive_preview` scroll, which has `amount` and `to`).
- **Rebuild notes:** A two-value enum keeps the schema cheap; add `amount`/`to` only if page-level jumps are needed.

### browser_snapshot  `id: tools.tool-browser-snapshot`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_snapshot`, toolset `browser`, emoji 📸.
- **What it does:** Returns a text snapshot of the current page's accessibility tree with `@e1`-style ref ids for `browser_click` / `browser_type`.
- **How it works:** `tools/browser_tool.py:4409` `browser_snapshot(full, task_id, user_task)` — note the handler also forwards `kw["user_task"]`, used to steer LLM summarisation. Registered `:6384` via `routed_browser_handler`; gate `check_browser_snapshot_requirements` → routed. Size handling: `DEFAULT_SNAPSHOT_THRESHOLD = 15000` (`tools/browser_tool.py:290`, deliberately aligned with `web_tools.DEFAULT_EXTRACT_CHAR_LIMIT`), `SNAPSHOT_SUMMARIZE_THRESHOLD = DEFAULT_SNAPSHOT_THRESHOLD` (`:295`), `MAX_STORED_SNAPSHOT_CHARS = 2_000_000` (`:301`). Over-threshold snapshots are truncated or LLM-summarised and the complete snapshot is written to a file whose path is included in the output for paging with `read_file`; the stored copy itself is cut at 2 000 000 chars with a `[... stored copy truncated at 2,000,000 chars …]` marker (`:4046`). When a CDP supervisor is attached the snapshot additionally carries `pending_dialogs` and `frame_tree` fields consumed by `browser_dialog` and `browser_cdp`.
- **Inputs / options:** `full` (boolean, optional, default `False`) — "If true, returns complete page content. If false (default), returns compact view with interactive elements only."
- **Outputs / side effects:** Snapshot text/JSON; possibly a snapshot file on disk.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate first." In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Spill-to-file plus an in-band path beats truncation; keep the summarisation threshold identical to the web-extract limit so the model learns one number.

### browser_type  `id: tools.tool-browser-type`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_type`, toolset `browser`, emoji ⌨️.
- **What it does:** Clears an input field addressed by ref id and types new text into it.
- **How it works:** `tools/browser_tool.py:4553` `browser_type(ref, text, task_id)`; registered `:6411` via `routed_browser_handler`; gate `check_browser_type_requirements` → routed.
- **Inputs / options:** `ref` (string, REQUIRED) — "The element reference from the snapshot (e.g., '@e3')"; `text` (string, REQUIRED) — "The text to type into the field".
- **Outputs / side effects:** Field content replaced; JSON result.
- **Config / env:** as `browser_back`.
- **Edge cases / guards:** "Requires browser_navigate and browser_snapshot to be called first." Always clears first — there is no append mode. MUTATING in guardrails.
- **Rebuild notes:** Clear-then-type is the right default for LLM form filling; an explicit `append` flag would be the only worthwhile addition.

### browser_vision  `id: tools.tool-browser-vision`
- **Surface:** Tool
- **Where:** Model-callable tool `browser_vision`, toolset `browser`, emoji 👁️.
- **What it does:** Screenshots the current page and lets the agent inspect it visually — CAPTCHAs, visual verification, layout questions the text snapshot misses.
- **How it works:** `tools/browser_tool.py:5412` `browser_vision(question, annotate, task_id)` returning `str | Dict[str, Any]` (the multimodal envelope). Registered `:6477` via `routed_browser_handler`. Gate `check_browser_vision_requirements()` (`tools/browser_tool.py:6243`) requires BOTH `check_browser_requirements()` AND `tools.vision_tools.check_vision_requirements()` — without the second check the tool stayed listed with no vision provider and failed with `unknown variant 'image_url', expected 'text'` (issue #31179). When the active model has native vision the screenshot is attached to context directly and inspected on the next turn; otherwise Hermes falls back to an auxiliary vision model and returns a text analysis.
- **Inputs / options:** `question` (string, REQUIRED) — "What you want to know about the page visually. Be specific about what you're looking for."; `annotate` (boolean, optional, default `False`) — "If true, overlay numbered [N] labels on interactive elements. Each [N] maps to ref @eN for subsequent browser commands. Useful for QA and spatial reasoning about page layout."
- **Outputs / side effects:** A screenshot file; the result includes `screenshot_path`, and the model can share it with the user by writing `MEDIA:<screenshot_path>` in its response.
- **Config / env:** `auxiliary.vision.provider` and the vision fallback chain (main provider → openrouter → nous); browser config as above.
- **Edge cases / guards:** "Requires browser_navigate to be called first."
- **Rebuild notes:** Two availability conditions (browser AND vision) must both gate the schema; the `[N]`→`@eN` annotation mapping is what lets a vision model hand coordinates back to the text tools.

### clarify  `id: tools.tool-clarify`
- **Surface:** Tool
- **Where:** Model-callable tool `clarify`, toolset `clarify`, emoji ❓.
- **What it does:** Asks the user 1–5 questions (single-select, multi-select, or open-ended) and blocks until they answer.
- **How it works:** `tools/clarify_tool.py` (21.5 KB); registered `:503`. `check_clarify_requirements()` (`:432`) always returns True. The handler accepts both the modern batched shape and the legacy singular shape: `clarify_tool(question=args.get("question",""), choices=args.get("choices"), multi_select=args.get("multi_select", False), questions=args.get("questions"), callback=kw.get("callback"))` — `question`/`choices`/`multi_select` are legacy top-level args NOT present in the published schema. Constants `MAX_QUESTIONS = 5` and `MAX_CHOICES = 4` are interpolated into the description. Delivery goes through the platform's blocking-prompt bridge (the same one `read_terminal` uses); on messaging platforms `tools/clarify_gateway.py` renders the form.
- **Inputs / options:** `questions` (array, REQUIRED, minItems 1, maxItems 5) — items are objects with `question` (string, REQUIRED), `choices` (array), `multi_select` (boolean). Schema description: "The question(s). Each: question text (options excluded), optional choices (recommended first; omit for free-text), optional multi_select. Responses come back in question order with the question text echoed."
- **Outputs / side effects:** `{responses: [...]}` in question order, plus `timed_out: true` if the user stopped part-way. The UI marks the first choice "(Recommended)" and auto-appends an "Other" free-text row for single-select.
- **Config / env:** n/a (always available); the surface that renders the form is platform-specific.
- **Edge cases / guards:** Up to 4 choices per single-select question. Options must live in `choices`, never enumerated in the question text ("options written into the question are dead prose the user can't click"). Independent questions belong in ONE call; dependent ones must be asked separately. Explicitly NOT for dangerous-command confirmation — the `terminal` tool owns that. `hermes-acp` and `hermes-api-server` drop this tool because they have no interactive UI.
- **Rebuild notes:** Batch the form, echo the question text with each response, and mark the recommended option — the three things that turn "ask the user" from a stall into a decision.

### close_terminal  `id: tools.tool-close-terminal`
- **Surface:** Tool
- **Where:** Model-callable tool `close_terminal`, toolset `desktop_ui`, emoji 🖥️. Desktop app only.
- **What it does:** Drops the read-only terminal tab that mirrors one `terminal(background=true)` process in the desktop GUI, without killing the process.
- **How it works:** `tools/close_terminal_tool.py:21` `close_terminal_tool(process_id)` → `process_registry.request_close_terminal(pid)` (`tools/process_registry.py`), whose `on_close` sink the desktop gateway wires to emit a `terminal.close` renderer event. Registered `:56`, no `check_fn`.
- **Inputs / options:** `process_id` (string, REQUIRED) — "The background process's session id (from terminal(background=true) output or process(action='list')) whose tab should be closed."
- **Outputs / side effects:** The tab disappears; the process keeps running and its output keeps buffering; the user can reopen the tab from the status stack. Returns the process registry's JSON verdict.
- **Config / env:** none.
- **Edge cases / guards:** Empty id → `process_id is required (the background process whose tab to close).` To actually stop the process the description directs the model to `process(action='kill')`.
- **Rebuild notes:** Separating "hide the view" from "kill the process" is the whole point; make the distinction explicit in the tool description or models will conflate them.

### computer_use  `id: tools.tool-computer-use`
- **Surface:** Tool
- **Where:** Model-callable tool `computer_use`, toolset `computer_use`, no emoji (falls back to the registry default ⚡).
- **What it does:** Universal desktop control (screenshot, mouse, keyboard, scroll, drag, app/window listing) through the external `cua-driver` binary, deliberately WITHOUT stealing the user's cursor or keyboard focus.
- **How it works:** Shim `tools/computer_use_tool.py:20` registers the tool; the implementation is the `tools/computer_use/` package (`schema.py` → `COMPUTER_USE_SCHEMA`, `tool.py` → `handle_computer_use`, `cua_backend.py`). Availability `check_computer_use_requirements()` (`tools/computer_use/tool.py:1678`) requires `sys.platform in ("darwin","win32","linux")` AND `cua_driver_binary_available()`. Action classes: `_SAFE_ACTIONS = {capture, wait, list_apps, list_windows}` (always allowed, no approval) and `_DESTRUCTIVE_ACTIONS = {click, double_click, right_click, middle_click, drag, scroll, type, key, set_value, focus_app}` (approval-gated). Approval (`_request_approval`, `tools/computer_use/tool.py:591`) is scoped by `(action, "foreground"|"background")` AND by `session_id`, so a prior background approval never silently authorises a foreground focus change (issue #67052); verdicts are `approve_once`, `approve_session`, `always_approve` (sets `_session_auto_approve[sid]`, covers foreground too), `timeout` (returns "approval prompt timed out — the user did not respond. Silence is not consent; do not retry without the user."), anything else → `{"error":"denied by user","action":…}`. With no approval callback wired, CLI-level approval defaults to allow and the gateway's normal tool-approval infra handles it one layer out. `bring_to_front` gets its own separate approval scope. Hermes's `--yolo`/`-z` approval bypass maps onto Cua's immutable driver mode and emits a one-time warning per session ("computer_use: approval bypass (--yolo / -z) escalated the cua-driver … session. Runtime approval prompts are disabled and the driver's …").
- **Inputs / options:** `action` (string, REQUIRED, enum `capture`, `click`, `double_click`, `right_click`, `middle_click`, `drag`, `scroll`, `type`, `key`, `set_value`, `wait`, `list_apps`, `list_windows`, `focus_app`) — "Which action to perform. `capture` is free (no side effects). All other actions require approval unless auto-approved. Use `set_value` for select/popup elements and sliders — it selects the matching option directly without opening the native menu (no focus steal)."; `mode` (string, optional, enum `som`|`vision`|`ax`) — "`som` (default) is a screenshot with numbered overlays on every interactable element plus the AX tree … `vision` is a plain screenshot. `ax` is the accessibility tree only (no image; useful for text-only models)."; `app` (string, optional) — app name or bundle ID; omitted = frontmost window; `app='screen'` = composited full-screen grab (image only, no clickable elements); `app='desktop'` = the OS desktop/shell surface with its elements; `pid` (integer, optional) — exact process target for `capture`; `window_id` (integer, optional) — exact native window target for `capture`; `element` (integer, optional) — "The 1-based SOM index returned by the last `capture(mode='som')` call. Strongly preferred over raw coordinates."; `coordinate` (array of integer, optional, minItems 2, maxItems 2) — "Pixel coordinates [x, y] relative to the captured window screenshot (top-left origin)."; `button` (string, optional, enum `left`|`right`|`middle`, defaults to left); `modifiers` (array of string, optional, item enum `cmd`, `shift`, `option`, `alt`, `ctrl`, `fn`, `win`, `windows`, `super`, `meta`); `from_element` (integer, optional); `to_element` (integer, optional); `from_coordinate` (array[int], minItems 2, maxItems 2); `to_coordinate` (array[int], minItems 2, maxItems 2); `direction` (string, optional, enum `up`|`down`|`left`|`right`); `amount` (integer, optional) — "Scroll wheel ticks. Default 3."; `value` (string, optional) — for `set_value`, the option display label (e.g. 'Blue') or numeric/string value; `text` (string, optional) — text to type (respects current layout); `keys` (string, optional) — "Key combo, e.g. 'cmd+s', 'ctrl+alt+t', 'return', 'escape', 'tab'. Use '+' to combine."; `seconds` (number, optional) — "Seconds to wait. Max 30."; `raise_window` (boolean, optional) — only for `focus_app`; true brings the window to front (DISRUPTS the user); default false; `delivery_mode` (string, optional, enum `background`|`foreground`) — `background` (DEFAULT) delivers without raising or stealing focus, `foreground` briefly fronts the window then restores focus and needs its own approval; `bring_to_front` (boolean, optional) — only valid with `delivery_mode='foreground'`; invokes cua-driver's standalone `bring_to_front` tool with a separate approval scope; default false; `capture_after` (boolean, optional) — take a follow-up capture after the action and include it in the response.
- **Outputs / side effects:** Real input delivered to the desktop; screenshots (SOM overlays / plain / AX tree) returned to the model; each result carries a `verdict` telling the model the next step (e.g. escalate to foreground).
- **Config / env:** cua-driver binary on `$PATH` (or env override). Approval state is keyed on the gateway `session_key` set per turn by `tools/approval.py::set_current_session_key`.
- **Edge cases / guards:** `_BLOCKED_KEY_COMBOS` are rejected regardless of approval level: `cmd+shift+backspace` (empty trash), `cmd+option+backspace` (force delete), `cmd+ctrl+q` (lock screen), `cmd+shift+q` (log out), `cmd+option+shift+q` (force log out), `win+l`, `ctrl+option+delete`, `ctrl+option+del`, `option+f4`. `_KEY_ALIASES` canonicalise `command→cmd`, `control→ctrl`, `alt→option`, `⌘→cmd`, `⌥→option`, `windows→win`, `super→win`, `meta→win` before the block check. Linux support is headed/X11 (Wayland via XWayland); `hermes computer-use doctor` reports blocked checks (e.g. missing `DISPLAY`).
- **Rebuild notes:** Two lists (safe vs destructive), an approval scope that includes delivery mode, and a hard block list that no approval can lift. The SOM (set-of-mark) capture mode — numbered overlays mapped to 1-based indices — is what lets a non-computer-use model drive a desktop.

### cronjob  `id: tools.tool-cronjob`
- **Surface:** Tool
- **Where:** Model-callable tool `cronjob`, toolset `cronjob`, emoji ⏰.
- **What it does:** Creates, lists, updates, pauses, resumes, removes and immediately runs scheduled jobs. Jobs run in a fresh session with no chat context and deliver their final response as a one-way message.
- **How it works:** `tools/cronjob_tools.py` (99 KB); handler `_cronjob_handler` registered at `:2105`, forwarding `task_id` and `session_id`. Availability `check_cronjob_requirements()` (`:2038`) returns True when any of `HERMES_INTERACTIVE`, `HERMES_GATEWAY_SESSION`, `HERMES_EXEC_ASK` is an explicitly truthy env string (`1`, `true`, `yes`, `on` — via `utils.env_var_enabled`); false-like values leave the tool off. The scheduler is internal (JSON file-based, ticked by the gateway) — no system crontab is required.
- **Inputs / options:** `action` (string, REQUIRED) — "One of: create, list, update, pause, resume, remove, run. When action=create, the 'schedule' and 'prompt' fields are REQUIRED."; `job_id` (string) — required for update/pause/resume/remove/run; `prompt` (string) — create: full self-contained prompt; run: transient context for that fire only (never persisted); `schedule` (string) — REQUIRED for create, five accepted forms: (1) recurring interval `'30m'`, `'every 2h'`, `'every hour'`; (2) explicit one-shot by duration `'in 30m'`, `'in 2h'`; (3) natural day/time `'every monday 9am'`, `'weekdays at 9am'`, `'every day at 9am'`; (4) cron syntax `'0 9 * * *'`; (5) absolute one-shot ISO timestamp `'2026-06-01T09:00:00'`; `name` (string) — human-friendly name; `repeat` (integer) — repeat count (default: once for one-shot, forever for recurring); `deliver` (string) — where output is posted: omit = the chat/topic the job was created from; `'local'` (save only), `'all'` (every connected home channel, resolved at fire time), `'bot-chat'` or `'bot-chat:<profile>'`, or `platform:chat_id:thread_id` e.g. `'telegram:-1001234567890:17585'`; comma-combine like `'origin,all'`; `skills` (array of string) — ordered skill names loaded before the prompt, `[]` clears on update; `script` (string) — script run each tick whose stdout is injected as context; relative paths resolve under `<HERMES_HOME>/scripts/`; `.sh`/`.bash` run via bash, everything else via Python; `''` clears on update; `monitor` (string) — change detector gating the agent: an http(s) URL fetched each tick or a script path; identical output skips the agent run entirely, changed output wakes it with a diff; first tick is always a baseline run; incompatible with `no_agent`; `''` clears; `no_agent` (boolean, default `False`) — no LLM: the scheduler runs `script` (then required) and delivers stdout verbatim, empty stdout sends nothing (watchdog pattern); `context_from` (array of string) — job IDs whose latest completed output is injected as context each run (chaining), `[]` clears; `continuity` (boolean, default false) — each run sees the job's OWN previous output so it can dedupe/continue; `enabled_toolsets` (array of string) — restrict the job's agent to these toolsets to cut token overhead, `[]` clears; `workdir` (string) — absolute existing path to run from; injects that directory's AGENTS.md/context files and anchors terminal/file tools there; `''` clears; `attach_to_session` (boolean) — makes the delivery CONTINUABLE (threads on thread-capable platforms, mirrored to DM elsewhere); scope is the job's own conversation only; broadcast targets are never attached; no effect when `deliver='local'`.
- **Outputs / side effects:** Job records persisted by the internal scheduler; `action='run'` returns a handle immediately and the outcome re-enters the conversation asynchronously; deliveries post messages on the configured channels.
- **Config / env:** `HERMES_INTERACTIVE`, `HERMES_GATEWAY_SESSION`, `HERMES_EXEC_ASK`; `<HERMES_HOME>/scripts/` for relative script/monitor paths.
- **Edge cases / guards:** "always list first — never guess job IDs". Cron runs are autonomous and cannot ask questions; the agent's FINAL RESPONSE is what gets delivered. The description warns to prefer updating an existing job over creating near-duplicates, and never to wait/poll on `action='run'`. `monitor` output must be deterministic (no timestamps) or every tick looks changed. Children spawned by `delegate_task` cannot call `cronjob` (see the delegate description's restrictions rule).
- **Rebuild notes:** Five schedule grammars in one string field, plus three orthogonal gating mechanisms (`script` for context, `monitor` for change detection, `no_agent` for LLM-free watchdogs) is a lot of power for one tool; the `continuity` / `context_from` split (own previous output vs another job's) is the design detail worth copying.

### delegate_task  `id: tools.tool-delegate-task`
- **Surface:** Tool
- **Where:** Model-callable tool `delegate_task`, toolset `delegation`, emoji 🔀.
- **What it does:** Spawns one or more subagents with isolated contexts, terminal sessions and toolsets; only each child's final summary returns to the parent. Also provides live control (list / steer / stop) of running children.
- **How it works:** `tools/delegate_tool.py` (236 KB), registered at `:5238`. `check_delegate_requirements()` (`:1225`) always returns True. `dynamic_schema_overrides=_build_dynamic_schema_overrides` (`:5066`) rewrites `description` and `parameters.properties.tasks.description` on EVERY `get_definitions()` pass so the model sees the user's real limits: `_build_tasks_param_description()` interpolates `delegation.max_concurrent_children`, and `_build_top_level_description()` renders one of two child-restriction clauses depending on whether `_get_max_spawn_depth() >= 2 and _get_orchestrator_enabled()`. With orchestration available: "Children cannot call clarify, memory, or cronjob. / Children can themselves delegate while depth remains (max_spawn_depth=N); the runtime derives this from depth automatically."; otherwise: "Children cannot call delegate_task, clarify, memory, or cronjob." Background policy: `_model_background_value(args, parent_agent)` returns `not (parent_agent._delegate_depth > 0)` — top-level delegations always run in the background; an orchestrator subagent's delegation runs synchronously because it needs its workers within its own turn. `_strip_model_hidden_task_fields` removes `acp_command` / `acp_args` from every task dict before dispatch.
- **Inputs / options (advertised):** `tasks` (array, optional at schema level but "Required when spawning", minItems 1, no maxItems — the runtime limit is `delegation.max_concurrent_children`, default 3) — items are objects with `goal` (string, REQUIRED) "What this subagent should accomplish. Be specific and self-contained — it knows nothing about your conversation history.", `context` (string) "Background THIS child needs: file paths, error messages, constraints. Each child sees only its own context — repeat shared background in every task that needs it.", `output_schema` (object) "Optional JSON Schema this child's final answer must validate against (told to the child up front; parent validates with one bounded correction retry; result gains schema_valid, plus schema_errors on failure). Keep it forgiving — require only fields you will read."; `action` (string, enum `spawn`|`list`|`steer`|`stop`, default `spawn`); `subagent_id` (string) — target for steer/stop; `message` (string) — the steer text, appended to the child's next tool result mid-run.
- **Inputs / options (accepted but deliberately unadvertised):** top-level `goal` (string), `context` (string), `output_schema` (object) — the legacy single-goal shape, wrapped into a one-entry batch at dispatch; `max_iterations`; per-task and top-level `role` (ignored — delegation capability is depth-derived); `background` (ignored); per-task `acp_command` / `acp_args` (stripped from model input). Source comments explicitly say "do not re-add these to the schema".
- **Outputs / side effects:** Spawn returns immediately with live transcript paths; the consolidated result (results in task order) re-enters the conversation on its own. Children get their own conversation, terminal session and toolset.
- **Config / env:** `delegation.max_concurrent_children` (default 3), `delegation.max_spawn_depth`, `delegation.orchestrator_enabled`.
- **Edge cases / guards:** From the generated description — DO NOT USE FOR: mechanical multi-step work with no reasoning (→ `execute_code`), a single tool call (→ call it directly), tasks needing user interaction (subagents cannot ask questions), durable work that must survive the session (→ `cronjob` or `terminal(background=True, notify=True)`; `/stop`, `/new` or process exit discards running subagents). RULES include: children know nothing of the conversation, so pass required output language/tone/style in `context`; child summaries are SELF-REPORTS not verified facts — for external side effects require a verifiable handle (URL, ID, absolute path) and verify it yourself. Kanban tools are stripped/disabled for delegated children (`_is_delegated_child_context()` in `tools/kanban_tools.py`). MUTATING in the loop guardrails.
- **Rebuild notes:** The dynamic description is the crucial trick — telling the model the *user's* concurrency and depth limits at schema-assembly time prevents confabulated nesting. Live steer/stop on a running child, with the steer text injected into the child's next tool result, is the differentiator over fire-and-forget subagents.

### desktop_preview  `id: tools.tool-desktop-preview`
- **Surface:** Tool
- **Where:** Model-callable tool `desktop_preview`, toolset `desktop_ui`, emoji 🖼️. Desktop app only.
- **What it does:** Controls the preview pane beside the chat: open a URL / localhost dev server / file path, close the pane or one tab, or read what the pane currently shows.
- **How it works:** `tools/preview_tool.py`, registered `:79` with handler `_handle_preview` and no `check_fn`. Consolidation of the former `open_preview` / `close_preview` / `read_preview` tools (issue #95681): those three modules survive as helper code with a comment "Registration removed: consolidated into the `preview` tool" at `tools/open_preview_tool.py:87`, `tools/close_preview_tool.py:58`, `tools/read_preview_tool.py:84`. `open` → `open_preview_tool(url, label)`; `close` → `desktop_ui.emit("preview.close", {"url": target})` after `_normalize_target()`; `read` is NOT handled here — it is dispatched at the agent level through `agent.read_preview_callback` (`agent_runtime_helpers`), because it needs the GUI callback; calling it through the registry handler returns `preview read must run inside a desktop session (no GUI callback here).`
- **Inputs / options:** `action` (string, REQUIRED, enum `open`|`close`|`read`); `url` (string) — "open: the target. close: one tab (omit for the whole pane)."; `label` (string) — "open: optional tab label."; `start` (integer) — "read: 0-indexed char offset."; `count` (integer) — "read: chars to return (capped per read)."
- **Outputs / side effects:** open → the pane shows the target for the current window only. close → `{"success": true, "closed": "<target or 'all'>"}`. read → `{kind, url, title, text, start, end, total_chars}`; a Browser tab's `text` is the rendered page's visible text paged with `start`/`count` (char offsets); a file tab answers identity only (the model must use `read_file` for content).
- **Config / env:** none; `HERMES_UI_SESSION_ID` routes the emit.
- **Edge cases / guards:** No emitter → `The preview pane is only available in the Hermes desktop app.` Emit exception → `Failed to close the preview: <exc>`. Unknown action → `action must be one of: open, close, read.`
- **Rebuild notes:** Collapsing three near-identical tools into one action enum saved ~366 tokens of schema; keep the read path on the agent-level callback so it can block for a renderer answer.

### desktop_project  `id: tools.tool-desktop-project`
- **Surface:** Tool
- **Where:** Model-callable tool `desktop_project`, toolset `project`, no emoji. GUI/desktop sessions only.
- **What it does:** Creates, switches between and lists desktop Projects — the named, folder-anchored workspaces the desktop sidebar groups sessions into.
- **How it works:** `tools/project_tools.py`, registered `:157` with handler `_handle_project` and no `check_fn`; consolidation of the former `project_create` / `project_list` / `project_switch` (issue #95681, 244 → ~145 tokens). Storage is the per-profile `projects.db` accessed through `hermes_cli.projects_db` (`connect_closing`, `list_projects`, `create_project`, `set_active`, `get_active_id`, `get_project`, `find_by_primary_path`). `set_project_workspace_callback(fn)` is wired by `tui_gateway` at session wiring; on create/switch, `_apply_workspace(task_id, primary_path, name)` re-anchors the live session's cwd and refreshes the sidebar. The DB write is the durable part — in CLI/messaging contexts the callback is None and only the DB changes. `_resolve(conn, token)` matches exact id / slug / name first, then case-insensitive slug / name.
- **Inputs / options:** `action` (string, REQUIRED, enum `create`|`switch`|`list`); `name` (string) — "create: human name. switch: name, slug, or id."; `path` (string) — "create: repo/folder to anchor to." (expanded with `os.path.expanduser` + `os.path.abspath`).
- **Outputs / side effects:** `list` → `{"active_id": …, "projects": [{id, slug, name, primary_path, active}]}`. `create`/`switch` → `{"success": true, id, slug, name, primary_path}`; the active project changes and the chat's workspace moves.
- **Config / env:** per-profile `projects.db` under HERMES_HOME.
- **Edge cases / guards:** Empty name on create → `{"success": false, "error": "name is required"}`. Idempotent create: if the folder already belongs to a project, that project is re-activated instead of minting a duplicate (issue #75820 — duplicates rendered N identical sidebar subtrees). `switch` with no match → `{"success": false, "error": "no project matching '<token>'"}`. Unknown action → `action must be one of: create, switch, list.` Deliberately kept out of `_HERMES_CORE_TOOLS` so no CLI/messaging/cron schema carries it.
- **Rebuild notes:** Make workspace moves an explicit tool rather than a side effect of `cd`; make create idempotent on the anchor path.
- **Docs discrepancy:** `website/docs/reference/toolsets-reference.md` still lists the `project` toolset as `project_create`, `project_list`, `project_switch` — three tools that no longer exist. The live registry has exactly one: `desktop_project`.

### discord  `id: tools.tool-discord`
- **Surface:** Tool
- **Where:** Model-callable tool `discord`, toolset `discord`, no emoji. Only offered on the `discord` platform (`hermes_cli/toolset_scope.py`).
- **What it does:** Read-and-participate Discord actions: search members, fetch recent messages, create a public thread.
- **How it works:** `tools/discord_tool.py` (40 KB); handler `_make_handler(discord_core)` registered at `:1100` with `requires_env=["DISCORD_BOT_TOKEN"]`. Availability `check_discord_tool_requirements()` (`:977`) is `bool(_get_bot_token())`. Shared dispatcher `_run_discord_action(action, valid_actions, tool_label, guild_id, channel_id, user_id, role_id, message_id, query, name, limit=50, before, after, auto_archive_duration=1440)` hits the Discord REST API.
- **Inputs / options:** `action` (string, REQUIRED, enum `search_members`|`fetch_messages`|`create_thread`); `guild_id` (string) — "Discord server (guild) ID."; `channel_id` (string) — "Discord channel ID."; `user_id` (string) — "Discord user ID."; `role_id` (string) — "Discord role ID."; `message_id` (string) — "Discord message ID."; `query` (string) — "Member name prefix to search for (search_members)."; `name` (string) — "New thread name (create_thread)."; `limit` (integer, minimum 1, maximum 100) — "Max results (default 50). Applies to fetch_messages, search_members."; `before` (string) — "Snowflake ID for reverse pagination (fetch_messages)."; `after` (string) — "Snowflake ID for forward pagination (fetch_messages)."; `auto_archive_duration` (integer, enum `60`, `1440`, `4320`, `10080`) — "Thread archive duration in minutes (create_thread, default 1440)." Note the `discord` and `discord_admin` schemas share one parameter block, so several fields are inert for a given action.
- **Outputs / side effects:** Message lists / member lists as JSON; `create_thread` creates a real public thread.
- **Config / env:** `DISCORD_BOT_TOKEN`.
- **Edge cases / guards:** `toolset_allowed_for_platform("discord", platform)` restricts this toolset to `platform == "discord"`. The description tells the model to use the `channel_id` from the current conversation context and to use `search_members` to resolve names to IDs.
- **Rebuild notes:** One shared parameter block across two action-enum tools halves schema cost but leaks irrelevant fields; a better version would use per-action `oneOf` branches.

### discord_admin  `id: tools.tool-discord-admin`
- **Surface:** Tool
- **Where:** Model-callable tool `discord_admin`, toolset `discord_admin`, no emoji. Discord platform only.
- **What it does:** Server management via the Discord REST API: enumerate guilds/channels/roles/members/pins, pin/unpin/delete messages, add/remove roles.
- **How it works:** `tools/discord_tool.py`, handler `_make_handler(discord_admin_handler)` registered at `:1109`, `requires_env=["DISCORD_BOT_TOKEN"]`, same `check_discord_tool_requirements` gate and same `_run_discord_action` dispatcher.
- **Inputs / options:** `action` (string, REQUIRED, enum, 12 values with their documented signatures): `list_guilds()` — list servers the bot is in; `server_info(guild_id)` — server details + member counts; `list_channels(guild_id)` — all channels grouped by category; `channel_info(channel_id)`; `list_roles(guild_id)` — roles sorted by position; `member_info(guild_id, user_id)`; `list_pins(channel_id)`; `pin_message(channel_id, message_id)`; `unpin_message(channel_id, message_id)`; `delete_message(channel_id, message_id)`; `add_role(guild_id, user_id, role_id)`; `remove_role(guild_id, user_id, role_id)`. Plus the shared block: `guild_id`, `channel_id`, `user_id`, `role_id`, `message_id`, `query`, `name`, `limit` (1–100, default 50), `before`, `after`, `auto_archive_duration` (enum 60/1440/4320/10080).
- **Outputs / side effects:** Real moderation effects: pinned/unpinned/deleted messages, role assignments.
- **Config / env:** `DISCORD_BOT_TOKEN`.
- **Edge cases / guards:** "Call list_guilds first to discover guild_ids, then list_channels for channel_ids. Runtime errors will tell you if the bot lacks a specific per-guild permission (e.g. MANAGE_ROLES for add_role)." Platform-restricted to `discord`.
- **Rebuild notes:** Splitting read-and-participate (`discord`) from moderation (`discord_admin`) into separate toolsets is what makes the destructive half separately disableable.

### drive_preview  `id: tools.tool-drive-preview`
- **Surface:** Tool
- **Where:** Model-callable tool `drive_preview`, toolset `desktop_ui`, emoji 🖱️. Desktop app only.
- **What it does:** Interacts with the page open in the desktop preview pane — inventory elements, click, hover, type, scroll, press keys, history — so the agent drives the same page the user is watching.
- **How it works:** `tools/drive_preview_tool.py:56` `drive_preview_tool(...)`, registered `:201`, no `check_fn`. Round-trips the gateway blocking-prompt bridge: `tui_gateway` emits `preview.act.request`, the renderer injects an interaction engine into the pane's webview and answers `preview.act.respond`. `ACTIONS = ("elements","click","hover","type","scroll","press","strobe","back","forward","reload")`; `SCROLL_TO = ("top","bottom")`; `NEEDS_TARGET = ("click","hover","type","press")` (scroll is deliberately absent — bare scroll moves the page). Element refs are semantic (`btn-sign-in`, `inp-email`), last as long as the page is open including across re-renders that destroy and rebuild the element, and only navigation retires them. After the first full inventory the renderer answers with a DELTA (`added` in full, `changed` as ref + moved fields, `removed`/`rebound` as ref lists) rather than re-sending the whole inventory.
- **Inputs / options:** `action` (string, REQUIRED, enum `elements`, `click`, `hover`, `type`, `scroll`, `press`, `strobe`, `back`, `forward`, `reload`) — "Start with 'elements'."; `ref` (string) — "Element ref from an earlier elements call."; `selector` (string) — "CSS selector fallback. Prefer ref."; `text` (string) — "type: the text."; `submit` (boolean) — "type: press Enter + submit the form after."; `key` (string) — "press: key name ('Enter', 'Escape', 'ArrowDown')."; `amount` (integer) — "scroll: pixels (negative = up; default ~one screen)."; `to` (string, enum `top`|`bottom`) — "scroll: jump to top/bottom instead."; `max` (integer) — "elements: cap the inventory." (mapped to the handler's `limit`); `full` (boolean) — "elements: full re-read instead of a delta. Rarely needed."
- **Outputs / side effects:** Real input on the page (pointer travels, hover menus open); moves draw live and fade. Returns the renderer's JSON verbatim or `{"text": …}`.
- **Config / env:** none; `HERMES_UI_SESSION_ID` routing.
- **Edge cases / guards:** No callback → `drive_preview is only available in the Hermes desktop app.` Invalid action → `action must be one of: …`. Targeted verbs without ref/selector → `<verb> needs a ref from action='elements' (e.g. 'btn-sign-in') or a CSS selector.` `type` without text → `type needs the text to enter.` `press` without key → `press needs a key, e.g. 'Enter' or 'Escape'.` Bad `to` → `to must be one of: top, bottom.` Non-integer `amount`/`max` → `amount and max must be integers.` Empty renderer answer → `The action timed out, or no GUI window answered. Open a page with open_preview first.` `strobe` is a visual flourish only — one call runs a multi-second burst and the description forbids looping it.
- **Rebuild notes:** Semantic, re-render-surviving refs plus delta responses is the design that makes multi-turn page driving affordable. The renderer telling the model "this ref is stale, call elements again" beats silently acting on whatever now occupies the spot.

### execute_code  `id: tools.tool-execute-code`
- **Surface:** Tool
- **Where:** Model-callable tool `execute_code`, toolset `code_execution`, emoji 🐍, `max_result_size_chars=100_000`.
- **What it does:** Runs Python that calls Hermes tools programmatically inside a persistent session kernel — for 3+ tool calls with logic between them (filtering big outputs before they enter context, branching, loops).
- **How it works:** `tools/code_execution_tool.py` (103 KB) + `tools/code_kernel.py` / `code_kernel_remote.py`; schema built by `build_execute_code_schema()`, handler `_execute_code_handler` registered at `:2478`. Availability `check_sandbox_requirements()` (`:356`): requires `SANDBOX_AVAILABLE` (POSIX, for Unix domain sockets) and, when `terminal_tool._get_env_config()["env_type"] == "vercel_sandbox"`, `_check_vercel_sandbox_requirements(config)`. Tools are exposed to the script through a generated `hermes_tools` module whose stubs marshal args over an RPC socket. Kernel state (variables, imports, loaded data) survives across calls; a timed-out or interrupted call loses it.
- **Inputs / options:** `code` (string, REQUIRED) — "Python code to execute. Import tools with `from hermes_tools import web_search, terminal, ...` and print your final result to stdout."; `reset` (boolean, optional) — "Discard the kernel's persistent state and start fresh before running this code."
- **Callable tool surface inside the script (from the schema, verbatim signatures):** `web_search(query: str, limit: int = 5) -> dict` returning `{"data": {"web": [{"url","title","description"}, ...]}}`; `web_extract(urls: list[str], char_limit: int = None) -> dict` returning `{"results": [{"url","title","content","error"}, ...]}` with markdown content, no LLM summarisation, pages over `char_limit` (default 15000) head+tail truncated with the full text stored on disk (path in the content footer); `read_file(path: str, offset: int = 1, limit: int = 2000) -> dict` (1-indexed) returning `{"content": "...", "total_lines": N}`; `write_file(path: str, content: str) -> dict` (always overwrites the entire file); `search_files(pattern: str, target="content", path=".", file_glob=None, limit=50) -> dict` returning `{"matches": [...]}`; `patch(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict`; `terminal(command: str, timeout=None, workdir=None) -> dict` (foreground only, no background/pty) returning `{"output": "...", "exit_code": N}`. Built-in helpers with no import: `json_parse(text)` (tolerant `json.loads` for terminal output), `shell_quote(s)` (`shlex.quote`), `retry(fn, max_attempts=3, delay=2)` (exponential backoff).
- **Outputs / side effects:** stdout of the script; every side effect of the tools it calls. Stdout over 50 KB shows head/tail inline and the FULL text is auto-saved to a file whose path rides in the result.
- **Config / env:** `VIRTUAL_ENV` / `CONDA_PREFIX` select the interpreter (project venv/conda python when active — matching `terminal()`; otherwise Hermes's own python with stdlib plus Hermes's deps). Scripts run in the session's working directory. Terminal env config (`env_type`) decides the sandbox path.
- **Edge cases / guards:** Limits stated in the schema: 5-minute timeout, max 50 tool calls per `execute_code` call. `_execute_code_handler` recovers two common model errors: passing `command` instead of `code` → "execute_code received a 'command' parameter, but it requires Python source in 'code'. Use terminal(command=...) for shell commands; for Python, retry as execute_code(code=...)."; passing a non-string `code` → "execute_code received a <type> in 'code', but it requires Python source as a string. Retry as execute_code(code=\"...\")." MUTATING in the loop guardrails.
- **Rebuild notes:** The generated `hermes_tools` shim + RPC socket is the mechanism; the value is the persistent kernel plus the "print your final result" contract. A better version would stream stdout back incrementally and let the model resume a timed-out kernel instead of losing state.

### feishu_doc_read  `id: tools.tool-feishu-doc-read`
- **Surface:** Tool
- **Where:** Model-callable tool `feishu_doc_read`, toolset `feishu_doc`, emoji 📄, `requires_env=[]`. Only reachable on the `hermes-feishu` platform toolset, and in practice only from the Feishu document-comment intelligent-reply handler.
- **What it does:** Reads the content of a Feishu/Lark document by its document token.
- **How it works:** `tools/feishu_doc_tool.py`, handler `_handle_feishu_doc_read` registered at `:128`. Availability `_check_feishu()` (`:54`) uses `importlib.util.find_spec("lark_oapi") is not None` rather than a real import — the SDK eagerly loads websockets/dispatcher/all api/v2 models and costs ~5 s, and this probe fires at every `hermes` startup. The real import happens in the handler. The lark client is injected per-thread by the Feishu comment event handler (`get_client()`); requests go through `BaseRequest.builder().http_method(...).uri(...).token_types({AccessTokenType.TENANT})`.
- **Inputs / options:** `doc_token` (string, REQUIRED) — "The document token (from the document URL or comment context)."
- **Outputs / side effects:** Document text as JSON. No writes.
- **Config / env:** Feishu/Lark app credentials held by the gateway adapter; `lark_oapi` Python package must be installed.
- **Edge cases / guards:** Empty token → `doc_token is required`. No injected client → `Feishu client not available (not in a Feishu comment context)`.
- **Rebuild notes:** `find_spec` instead of `import` for availability probes is a general lesson — a 5-second SDK import on every CLI start is a real regression.

### feishu_drive_add_comment  `id: tools.tool-feishu-drive-add-comment`
- **Surface:** Tool
- **Where:** Model-callable tool `feishu_drive_add_comment`, toolset `feishu_drive`, emoji ✉️, `requires_env=[]`.
- **What it does:** Adds a whole-document comment to a Feishu/Lark drive file.
- **How it works:** `tools/feishu_drive_tool.py`, handler `_handle_add_comment` registered at `:421`; gate `_check_feishu` (`:30`, `find_spec("lark_oapi")`). Uses the thread-local lark client injected by `feishu_comment` via `set_client()` and `_do_request(client, method, uri, paths, queries, body)` with tenant access token.
- **Inputs / options:** `file_token` (string, REQUIRED) — "The document file token."; `content` (string, REQUIRED) — "The comment text content (plain text only, no markdown)."; `file_type` (string, optional, default `docx`) — "File type (default: docx)."
- **Outputs / side effects:** Creates a real comment on the document.
- **Config / env:** `lark_oapi` installed; tenant credentials via the gateway.
- **Edge cases / guards:** Plain text only — markdown is not rendered. Requires a Feishu comment context for the thread-local client.
- **Rebuild notes:** Thread-local client injection keeps the tool free of credential handling; the cost is that it only works inside the handler's thread.

### feishu_drive_list_comment_replies  `id: tools.tool-feishu-drive-list-comment-replies`
- **Surface:** Tool
- **Where:** Model-callable tool `feishu_drive_list_comment_replies`, toolset `feishu_drive`, emoji 💬.
- **What it does:** Lists the replies under one comment on a Feishu/Lark document.
- **How it works:** `tools/feishu_drive_tool.py`, handler `_handle_list_replies` registered at `:397`; gate `_check_feishu`.
- **Inputs / options:** `file_token` (string, REQUIRED); `comment_id` (string, REQUIRED) — "The comment ID to list replies for."; `file_type` (string, default `docx`); `page_size` (integer, default `100`) — "Number of replies per page (max 100)."; `page_token` (string) — "Pagination token for next page."
- **Outputs / side effects:** Read-only; JSON page of replies plus a continuation token.
- **Config / env:** as above.
- **Edge cases / guards:** `page_size` max 100.
- **Rebuild notes:** Standard cursor pagination; expose the next token verbatim so the model can page without state.

### feishu_drive_list_comments  `id: tools.tool-feishu-drive-list-comments`
- **Surface:** Tool
- **Where:** Model-callable tool `feishu_drive_list_comments`, toolset `feishu_drive`, emoji 💬.
- **What it does:** Lists comments on a Feishu/Lark document, optionally only whole-document ones.
- **How it works:** `tools/feishu_drive_tool.py`, handler `_handle_list_comments` registered at `:385`; gate `_check_feishu`.
- **Inputs / options:** `file_token` (string, REQUIRED); `file_type` (string, default `docx`); `is_whole` (boolean, default `False`) — "If true, only return whole-document comments."; `page_size` (integer, default `100`, max 100); `page_token` (string).
- **Outputs / side effects:** Read-only JSON list.
- **Config / env:** as above.
- **Edge cases / guards:** `page_size` max 100.
- **Rebuild notes:** n/a — thin API mirror.

### feishu_drive_reply_comment  `id: tools.tool-feishu-drive-reply-comment`
- **Surface:** Tool
- **Where:** Model-callable tool `feishu_drive_reply_comment`, toolset `feishu_drive`, emoji ✉️.
- **What it does:** Posts a reply under an existing Feishu/Lark document comment.
- **How it works:** `tools/feishu_drive_tool.py`, handler `_handle_reply_comment` registered at `:409`; gate `_check_feishu`.
- **Inputs / options:** `file_token` (string, REQUIRED); `comment_id` (string, REQUIRED) — "The comment ID to reply to."; `content` (string, REQUIRED) — "The reply text content (plain text only, no markdown)."; `file_type` (string, default `docx`).
- **Outputs / side effects:** Creates a real reply on the document.
- **Config / env:** as above.
- **Edge cases / guards:** Plain text only.
- **Rebuild notes:** n/a.

### focus_pane  `id: tools.tool-focus-pane`
- **Surface:** Tool
- **Where:** Model-callable tool `focus_pane`, toolset `desktop_ui`, emoji 🪟. Desktop app only.
- **What it does:** Reveals and focuses one Hermes desktop pane when the user asks to see it.
- **How it works:** `tools/focus_pane_tool.py:22` `focus_pane_tool(pane)` → `desktop_ui.emit("pane.reveal", {"pane": name})`; registered `:57`, no `check_fn`. `PANES = ("chat","files","terminal","review","sessions")`; the renderer runs each pane's own reveal path and only acts on the active window, so a background turn never moves the user's focus.
- **Inputs / options:** `pane` (string, REQUIRED, enum `chat`|`files`|`terminal`|`review`|`sessions`) — "Which pane to reveal." (`review` is the git-diff pane).
- **Outputs / side effects:** Pane revealed/focused. Returns `{"success": true, "pane": "<name>"}`.
- **Config / env:** none; `HERMES_UI_SESSION_ID` routing.
- **Edge cases / guards:** Bad pane → `pane must be one of: chat, files, terminal, review, sessions.` No emitter → `Pane focus is only available in the Hermes desktop app.` Exception → `Failed to focus the <name> pane: <exc>`. Description redirects URL/file display to `desktop_preview`, and `apply_layout` redirects multi-pane rearrangement here.
- **Rebuild notes:** Restricting the emit to the active window is the guard that keeps a background agent from hijacking the user's screen.

### ha_call_service  `id: tools.tool-ha-call-service`
- **Surface:** Tool
- **Where:** Model-callable tool `ha_call_service`, toolset `homeassistant`, emoji 🏠.
- **What it does:** Calls a Home Assistant service to control a device (turn on/off, set temperature, open covers, set volume…).
- **How it works:** `tools/homeassistant_tool.py`, handler `_handle_call_service` registered at `:507`; gate `_check_ha_available()` (`:345`) = `bool(get_secret("HASS_TOKEN"))`. REST call to `/api/services/{domain}/{service}` with `Authorization: Bearer <HASS_TOKEN>` and `Content-Type: application/json`. Base URL from `get_secret("HASS_URL", "http://homeassistant.local:8123")` with trailing slashes stripped.
- **Inputs / options:** `domain` (string, REQUIRED) — "Service domain (e.g. 'light', 'switch', 'climate', 'cover', 'media_player', 'fan', 'scene', 'script')."; `service` (string, REQUIRED) — "Service name (e.g. 'turn_on', 'turn_off', 'toggle', 'set_temperature', 'set_hvac_mode', 'open_cover', 'close_cover', 'set_volume_level')."; `entity_id` (string, optional) — "Target entity ID (e.g. 'light.living_room'). Some services (like scene.turn_on) may not need this."; `data` (string, optional) — "Additional service data as a JSON string. Examples: {\"brightness\": 255, \"color_name\": \"blue\"} for lights, {\"temperature\": 22, \"hvac_mode\": \"heat\"} for climate, {\"volume_level\": 0.5} for media players."
- **Outputs / side effects:** Real device state changes in the user's home.
- **Config / env:** `HASS_TOKEN` (long-lived access token, required), `HASS_URL` (default `http://homeassistant.local:8123`).
- **Edge cases / guards:** Security layer in `tools/homeassistant_tool.py:41-62`: `_ENTITY_ID_RE = ^[a-z_][a-z0-9_]*\.[a-z0-9_]+$`; `_SERVICE_NAME_RE = ^[a-z][a-z0-9_]*$` for both domain and service — no slashes or dots, because they are interpolated into the URL path and arbitrary strings would enable SSRF via traversal (`domain="../../api/config"`) or blocked-domain bypass (`domain="shell_command/../light"`). `_BLOCKED_DOMAINS = {shell_command, command_line, python_script, pyscript, hassio, rest_command}` — arbitrary shell/code execution on the HA host, addon/host shutdown, and SSRF vectors. The comment is explicit: "HA provides zero service-level access control; all safety must be in our layer."
- **Rebuild notes:** Any tool that interpolates model-supplied strings into a URL path needs a strict character-class regex AND a denylist of dangerous domains; validating one without the other leaves a bypass.

### ha_get_state  `id: tools.tool-ha-get-state`
- **Surface:** Tool
- **Where:** Model-callable tool `ha_get_state`, toolset `homeassistant`, emoji 🏠.
- **What it does:** Returns the full state of one Home Assistant entity including all attributes.
- **How it works:** `tools/homeassistant_tool.py`, handler `_handle_get_state` registered at `:489`; gate `_check_ha_available`. REST `GET /api/states/{entity_id}`.
- **Inputs / options:** `entity_id` (string, REQUIRED) — "The entity ID to query (e.g. 'light.living_room', 'climate.thermostat', 'sensor.temperature')."
- **Outputs / side effects:** Read-only JSON: state plus attributes (brightness, colour, temperature setpoint, sensor readings…).
- **Config / env:** `HASS_TOKEN`, `HASS_URL`.
- **Edge cases / guards:** `entity_id` validated against `_ENTITY_ID_RE`.
- **Rebuild notes:** n/a.

### ha_list_entities  `id: tools.tool-ha-list-entities`
- **Surface:** Tool
- **Where:** Model-callable tool `ha_list_entities`, toolset `homeassistant`, emoji 🏠.
- **What it does:** Lists Home Assistant entities, optionally filtered by domain or by area/room name.
- **How it works:** `tools/homeassistant_tool.py`, handler `_handle_list_entities` registered at `:480`; gate `_check_ha_available`. `_filter_and_summarize(states, domain, area)` filters raw `/api/states` by `entity_id.startswith(f"{domain}.")` and by a lowercase substring match of `area` against entity friendly names, then returns a compact summary rather than the raw payload.
- **Inputs / options:** `domain` (string, optional) — "Entity domain to filter by (e.g. 'light', 'switch', 'climate', 'sensor', 'binary_sensor', 'cover', 'fan', 'media_player'). Omit to list all entities."; `area` (string, optional) — "Area/room name to filter by (e.g. 'living room', 'kitchen'). Matches against entity friendly names. Omit to list all."
- **Outputs / side effects:** Read-only compact JSON summary.
- **Config / env:** `HASS_TOKEN`, `HASS_URL`.
- **Edge cases / guards:** Area matching is a friendly-name heuristic, not the HA area registry.
- **Rebuild notes:** Summarising before returning is what keeps a 500-entity home from filling the context window; a better version would query the HA area registry instead of string-matching names.

### ha_list_services  `id: tools.tool-ha-list-services`
- **Surface:** Tool
- **Where:** Model-callable tool `ha_list_services`, toolset `homeassistant`, emoji 🏠.
- **What it does:** Lists available Home Assistant services (actions) and the parameters each accepts, so the model can discover how to control entities it found.
- **How it works:** `tools/homeassistant_tool.py`, handler `_handle_list_services` registered at `:498`; gate `_check_ha_available`. REST `GET /api/services`, optionally filtered by domain.
- **Inputs / options:** `domain` (string, optional) — "Filter by domain (e.g. 'light', 'climate', 'switch'). Omit to list services for all domains."
- **Outputs / side effects:** Read-only JSON.
- **Config / env:** `HASS_TOKEN`, `HASS_URL`.
- **Edge cases / guards:** Blocked domains are still discoverable here but rejected by `ha_call_service`.
- **Rebuild notes:** Pair a discovery tool with the action tool so the model never has to guess service names; filter the discovery output by the same denylist the action tool enforces.

### image_generate  `id: tools.tool-image-generate`
- **Surface:** Tool
- **Where:** Model-callable tool `image_generate`, toolset `image_gen`, emoji 🎨, `requires_env=[]`.
- **What it does:** Generates an image from a text prompt (and, when the active model supports it, edits/transforms an existing image or uses reference images).
- **How it works:** `tools/image_generation_tool.py` (85 KB); handler `_handle_image_generate` registered at `:2144`; gate `check_image_generation_requirements()` (`:1470`) returns True when `check_fal_api_key()` succeeds AND the lazy `fal_client` import works; otherwise it reads the configured provider and, unless it is unset / `fal` / the Nous-managed provider, probes exactly that plugin provider via `agent.image_gen_registry.get_provider(configured).is_available()` after `hermes_cli.plugins._ensure_plugins_discovered()`. Merely possessing a cloud key must not opt a user into a paid backend. `dynamic_schema_overrides=_build_dynamic_image_schema` (`:2076`) rewrites BOTH the description and the parameter set from the active model's declared capabilities: `modalities`, `max_reference_images`, `supports_upscale`. Arguments a model cannot honour are not advertised; the handler still accepts them for replay compatibility and answers with a capability error.
- **Inputs / options (always present):** `prompt` (string, REQUIRED) — "The text prompt describing the desired image (text-to-image) or the edit to apply (image-to-image). Be detailed and descriptive."; `aspect_ratio` (string, optional, enum `landscape`|`square`|`portrait`, default `landscape`) — "'landscape' is 16:9 wide, 'portrait' is 16:9 tall, 'square' is 1:1."
- **Inputs / options (conditionally injected by the dynamic schema):** `image_url` (string) — added when the active model's modalities include `image`: "Source image to edit/transform (image-to-image). A public URL or an absolute local file path from the conversation. Omit for text-to-image."; `reference_image_urls` (array of string, maxItems = the model's `max_reference_images`) — added when `max_reference_images > 1`: "Up to N additional reference images (style, character, or composition) guiding an edit. URLs or absolute local paths."; `upscale` (boolean) — added when `supports_upscale`: "Post-generation high-resolution pass (~2x, extra cost/latency), off by default. A creative enhancer that can alter fine detail (rendered text, faces) — use only when resolution matters more than fidelity."
- **Description variants:** with edit support — "Generate high-quality images from text prompts, or edit / transform an existing image by passing image_url. Returns the result in the `image` field — a URL or an absolute file path; reference it in your response using the current platform's file-delivery convention." Without — the clause becomes " (text-to-image only — the active model cannot edit existing images)". The static placeholder in the registry dump reads "Generate images from text prompts. The active model's edit/reference capabilities are rendered at serving time."
- **Outputs / side effects:** The result's `image` field carries a URL or an absolute local file path; the file is written to disk for local providers. Costs money on paid backends.
- **Config / env:** FAL credentials (`check_fal_api_key`, `tools/fal_common.py`); the configured image provider key read by `_read_configured_image_provider()`; plugin providers registered in `agent/image_gen_registry.py`. Deeper provider matrix belongs to the media shard.
- **Edge cases / guards:** Capability coverage is contract-tested: all in-tree FAL catalog entries carry edit/refs/upscale metadata, and the plugin provider ABC's `capabilities()` default fails closed to text-only.
- **Rebuild notes:** Rendering the *parameter set* (not just the description) from live provider capabilities is the strongest idea here — the model literally cannot ask for an edit on a text-only backend. Keep the handler permissive for replayed transcripts.

### Kanban tools — shared gating and board resolution  `id: tools.kanban-shared`
- **Surface:** Tool
- **Where:** All 14 `kanban_*` tools, toolset `kanban`, defined in `tools/kanban_tools.py` (98 KB), registered `:2356`–`:2473`.
- **What it does:** Explains once the availability gate, board resolution, and delegated-child rejection that every kanban tool shares, so the per-tool entries below do not repeat it.
- **How it works:** Two `check_fn`s. `_check_kanban_mode()` (`:103`) — lifecycle tools: returns False in a `delegate_task` child context; True when `HERMES_KANBAN_TASK` is set AND `_is_dispatcher_owned_worker()`; otherwise `_profile_has_kanban_toolset()` (literally `"kanban" in load_config().get("toolsets", [])`). `_check_kanban_orchestrator_mode()` (`:122`) — board-routing tools (`kanban_list`, `kanban_unblock`): False for delegated children, False for dispatcher-spawned workers, else `_profile_has_kanban_toolset()`. `_is_dispatcher_owned_worker()` (`:74`) delegates to `agent.delegation_context.is_dispatcher_owned_worker_context()` and is False both for delegate_task children and for cron jobs fired in-process from a worker — "whenever HERMES_KANBAN_* is present but not ours". `_reject_delegated_child_mutation(tool_name)` (`:83`) returns the error `"<tool> refused: delegate_task child agents are not Kanban run owners. Return findings to the parent agent; the dispatcher worker or an explicitly configured Kanban orchestrator must perform board mutations."` Board resolution `_connect(board=None)` (`:224`): explicit `board` slug → `kanban_db.connect(board=…)`; otherwise the legacy chain `HERMES_KANBAN_DB` env → `HERMES_KANBAN_BOARD` env → the `current` symlink under the kanban home → `default`. `_default_task_id(arg)` falls back to `HERMES_KANBAN_TASK` unless the caller is a delegated child or a non-dispatcher-owned worker.
- **Inputs / options:** Every kanban tool takes `board` (string, optional) with the identical description: "Kanban board slug to target. When omitted, the call resolves the active board the usual way: HERMES_KANBAN_DB env → HERMES_KANBAN_BOARD env → the 'current' symlink under the kanban home → 'default'. Pass an explicit slug only when the caller (e.g. a Telegram routing layer) needs to override the env-pinned active board for this one call." Twelve of the fourteen also take `task_id` (string, optional) — "Task id. If omitted, defaults to HERMES_KANBAN_TASK from the env (the task the dispatcher spawned you to work on)"; `kanban_comment` and `kanban_unblock` make `task_id` REQUIRED, and `kanban_link` uses `parent_id`/`child_id` instead.
- **Outputs / side effects:** SQLite board files under the kanban home (one per board slug), a per-task attachments directory, an append-only event log, and dispatcher-visible status transitions.
- **Config / env:** `toolsets:` must list `kanban` for orchestrator profiles; `kanban.dispatch_in_gateway` decides whether the dispatcher runs inside the gateway (default true); `HERMES_KANBAN_TASK`, `HERMES_KANBAN_DB`, `HERMES_KANBAN_BOARD`, `HERMES_TENANT`.
- **Edge cases / guards:** The `all`/`*` toolset wildcard does NOT enable kanban — the toolset must be named explicitly (documented in `toolsets-reference.md`). Constants: `KANBAN_LIST_DEFAULT_LIMIT = 50`, `KANBAN_LIST_MAX_LIMIT = 200`, `_MAX_ATTACH_URL_REDIRECTS = 5`, `kanban_db.KANBAN_ATTACHMENT_MAX_BYTES` (25 MB), `_GOAL_MODE_BLOCK_ALLOWED_KINDS = {"dependency","needs_input"}`.
- **Rebuild notes:** Two gates (worker vs orchestrator) built from the same three signals, plus an explicit rejection for delegated children, is what keeps a subagent from mutating shared board state through inherited env vars.

### kanban_attach  `id: tools.tool-kanban-attach`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_attach`, toolset `kanban`, emoji 📎; registered `tools/kanban_tools.py:2428`, handler `_handle_attach`, gate `_check_kanban_mode`.
- **What it does:** Attaches a file to a task by passing its bytes inline as base64; stored as a real attachment under the task's attachments dir, not as a comment link.
- **How it works:** Decodes `content_base64`, strips directory components from `filename` (only the leaf is kept), writes into the task's attachments directory via `hermes_cli.kanban_db`, capped at `KANBAN_ATTACHMENT_MAX_BYTES` (25 MB decoded).
- **Inputs / options:** `task_id` (string, optional — env default); `filename` (string, REQUIRED) — "File name to store it under (e.g. 'report.pdf'). Directory components are stripped; only the leaf is kept."; `content_base64` (string, REQUIRED) — "The file contents, base64-encoded. Max 25 MB decoded."; `content_type` (string, optional) — "Optional MIME type (e.g. 'application/pdf')."; `board` (string, optional).
- **Outputs / side effects:** A file on disk under the task's attachments dir; an attachment row; an event.
- **Config / env:** kanban home, board env chain.
- **Edge cases / guards:** 25 MB decoded cap; path-traversal defence via leaf-only filenames; delegated children rejected. The description steers to `kanban_attach_url` when only a URL is available.
- **Rebuild notes:** Leaf-only filenames plus a hard byte cap are the two guards an inline-bytes upload tool must have.

### kanban_attach_url  `id: tools.tool-kanban-attach-url`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_attach_url`, toolset `kanban`, emoji 📎; registered `:2437`, handler `_handle_attach_url`, gate `_check_kanban_mode`.
- **What it does:** Downloads a file server-side from an http(s) URL and stores it as a real task attachment.
- **How it works:** `_download_url_with_cap(url, kb.KANBAN_ATTACHMENT_MAX_BYTES)` (`tools/kanban_tools.py:1274`) streams the body with a hard byte cap and follows at most `_MAX_ATTACH_URL_REDIRECTS = 5` redirects (`:1177`, loop at `:1203`). Filename defaults to the URL path's leaf; content type defaults to the server's `Content-Type`.
- **Inputs / options:** `task_id` (string, optional); `url` (string, REQUIRED) — "http(s) URL to fetch and store."; `filename` (string, optional) — "Optional name to store it under. Defaults to the URL path's leaf component."; `content_type` (string, optional) — "Optional MIME type override. Defaults to the Content-Type the server returns."; `board` (string, optional).
- **Outputs / side effects:** Outbound HTTP request from the Hermes host; a stored attachment.
- **Config / env:** kanban home, board env chain.
- **Edge cases / guards:** Only `http`/`https` URLs are accepted; 25 MB cap; max 5 redirects; delegated children rejected.
- **Rebuild notes:** Cap the stream, not the final file, and bound redirects — an unbounded server-side fetch is both a DoS and an SSRF surface.

### kanban_attachments  `id: tools.tool-kanban-attachments`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_attachments`, toolset `kanban`, emoji 📎; registered `:2446`, handler `_handle_attachments`, gate `_check_kanban_mode`.
- **What it does:** Lists the files attached to a task.
- **How it works:** Reads the attachment rows for the resolved task and board.
- **Inputs / options:** `task_id` (string, optional); `board` (string, optional).
- **Outputs / side effects:** Read-only. Returns per attachment: `id`, `filename`, `content_type`, `size`, who uploaded it, and the absolute on-disk path the agent can read with `read_file`.
- **Config / env:** kanban home, board env chain.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Returning the absolute path (not just an id) is what lets the agent chain straight into `read_file`.

### kanban_block  `id: tools.tool-kanban-block`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_block`, toolset `kanban`, emoji ⏸; registered `:2383`, handler `_handle_block`, gate `_check_kanban_mode`.
- **What it does:** Stops work on the task and routes it according to WHY the worker is stuck.
- **How it works:** `kind` selects the routing: `dependency` → the task goes to `todo` and auto-resumes when the blocking task finishes (no human needed); `needs_input`, `capability`, `transient` all surface to a human. `reason` is shown on the board. Repeated unblock/re-block cycles for the same reason auto-escalate the task to `triage` (block-loop accounting). In `goal_mode` runs only `_GOAL_MODE_BLOCK_ALLOWED_KINDS = {"dependency","needs_input"}` are accepted.
- **Inputs / options:** `task_id` (string, optional); `reason` (string, REQUIRED) — "What you need answered or what stopped you, in one or two sentences. Don't paste the whole conversation; the human has the board and can ask follow-ups via comments."; `kind` (string, optional, enum `dependency`|`needs_input`|`capability`|`transient`) — "'dependency' waits in todo and resumes automatically; the others surface to a human. Omit only if none apply."; `board` (string, optional).
- **Outputs / side effects:** Task status change; board notification; event log entry.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Use for genuine blockers only — don't block on things you can resolve yourself." Review handoffs must use `kanban_request_review` instead so they do not count toward unblock-loop detection. Delegated children rejected.
- **Rebuild notes:** Typing the blocker (`kind`) is what turns a blocked column into a routable queue; dependency blocks that auto-resume are the highest-value case.

### kanban_comment  `id: tools.tool-kanban-comment`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_comment`, toolset `kanban`, emoji 💬; registered `:2419`, handler `_handle_comment`, gate `_check_kanban_mode`.
- **What it does:** Appends a comment to a task's thread — durable notes that outlive this run.
- **How it works:** Writes a comment row on the addressed task; comment threads are per-task, so a worker may comment on another task's thread.
- **Inputs / options:** `task_id` (string, REQUIRED — no env default here) — "Required (may be your own task or another's — comment threads are per-task)."; `body` (string, REQUIRED) — "Markdown-supported comment body."; `board` (string, optional).
- **Outputs / side effects:** A persisted comment visible on the dashboard and to downstream workers.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Ephemeral reasoning doesn't belong here — use your normal response instead." Delegated children rejected.
- **Rebuild notes:** Making `task_id` required (unlike its siblings) is deliberate — commenting on someone else's card must be an explicit act.

### kanban_complete  `id: tools.tool-kanban-complete`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_complete`, toolset `kanban`, emoji ✔; registered `:2374`, handler `_handle_complete`, gate `_check_kanban_mode`.
- **What it does:** Marks the worker's task done with a structured handoff for downstream workers and humans.
- **How it works:** Requires at least one of `summary` or `result`. `created_cards` ids are VERIFIED by the kernel — each id must exist and have been created by this worker's profile; any phantom id blocks the completion with an error listing what went wrong, auditable in the task's events. `artifacts` paths must exist on disk at completion; the gateway notifier uploads each as a native attachment to the subscribed chat (images embed inline, everything else uploads as a file). Files inside a managed scratch workspace are copied to durable task attachments before cleanup; a missing declared scratch artifact keeps the task in-flight so the worker can fix the path and retry. In `goal_mode`, completion is additionally gated by the auxiliary judge — but only when `_goal_judge_available()` (`:233`) confirms a judge client is reachable, because `judge_goal` is fail-open and an unreachable judge would otherwise wedge every goal-mode worker forever.
- **Inputs / options:** `task_id` (string, optional); `summary` (string, optional) — "Human-readable handoff, 1-3 sentences. Appears in Run History on the dashboard and in downstream workers' context."; `metadata` (object, optional) — "Free-form dict of structured facts about this attempt — {\"changed_files\": [...], \"tests_run\": 12, \"findings\": [...]}."; `result` (string, optional) — "Short result log line (legacy field, maps to task.result)."; `created_cards` (array of string, optional) — verified manifest of ids created via `kanban_create` this run, "do not invent or remember ids from prose"; `artifacts` (array of string, optional) — absolute paths to deliverable files, e.g. `["/tmp/q3-revenue.png", "/tmp/report.pdf"]`; `board` (string, optional).
- **Outputs / side effects:** Task moves to `done`; run history entry; artifact uploads to the subscriber's chat; child tasks whose parents are now all done auto-promote to `ready`.
- **Config / env:** board env chain; goal-judge auxiliary client config.
- **Edge cases / guards:** Neither `summary` nor `result` → error. Phantom `created_cards` id → completion refused. Missing scratch artifact → task stays in flight. Delegated children rejected.
- **Rebuild notes:** Verifying the ids a worker claims to have created is a cheap, high-value integrity check; so is refusing completion when a declared deliverable does not exist on disk.

### kanban_create  `id: tools.tool-kanban-create`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_create`, toolset `kanban`, emoji ➕; registered `:2455`, handler `_handle_create`, gate `_check_kanban_mode`.
- **What it does:** Creates a new kanban task, optionally as a child of the current one — the fan-out primitive for orchestrator workers.
- **How it works:** Writes a task row; the dispatcher picks it up on its next tick and spawns the assigned profile. Parents gate promotion: the new task stays in `todo` until every parent reaches `done`, then auto-promotes to `ready`.
- **Inputs / options:** `title` (string, REQUIRED); `assignee` (string, REQUIRED) — "Profile name that should execute this task (e.g. 'researcher-a', 'reviewer', 'writer'). Required — tasks without an assignee are never dispatched."; `body` (string) — "Opening post: full spec, acceptance criteria, links."; `parents` (array of string) — "Parent task ids… Typical fan-in: list all the researcher task ids when creating a synthesizer task."; `tenant` (string) — "Optional namespace for multi-project isolation. Defaults to HERMES_TENANT env if set."; `priority` (integer) — "Dispatcher tiebreaker. Higher = picked sooner when multiple ready tasks share an assignee."; `workspace_kind` (string, enum `scratch`|`dir`|`worktree`) — "'scratch' (fresh tmp dir, default), 'dir' (shared directory, requires absolute workspace_path), 'worktree' (git worktree)."; `workspace_path` (string) — "Absolute path for 'dir' or 'worktree' workspace. Relative paths are rejected at dispatch."; `project` (string) — "Optional project id or slug… the task becomes a git worktree under the project's primary repo with a deterministic branch (project slug + task id), instead of a random branch."; `triage` (boolean) — lands in `triage` instead of `todo` for a specifier profile to flesh out; `idempotency_key` (string) — "If a non-archived task with this key already exists, return that task's id instead of creating a duplicate."; `max_runtime_seconds` (integer) — "When exceeded, the dispatcher SIGTERMs the worker and re-queues the task with outcome='timed_out'."; `initial_status` (string, enum `running`|`blocked`) — "'blocked' for tasks that require immediate human ops (R3 gate)… Defaults to 'running'."; `skills` (array of string) — "Skill names to force-load into the dispatched worker… must match skills installed on the assignee's profile."; `goal_mode` (boolean) — "after each turn an auxiliary judge checks the worker's response against this card's title/body; if the work isn't done and budget remains, the worker keeps going in the same session… Defaults to false."; `goal_max_turns` (integer) — "Turn budget for goal_mode workers… Defaults to the goal-engine default (20)."; `model` (string) — pin the worker's model; `provider` (string) — "Provider the 'model' belongs to (e.g. 'openrouter', 'anthropic', 'nous')… Requires 'model'."; `board` (string).
- **Outputs / side effects:** A new task id (returned), picked up by the dispatcher; possibly a git worktree and branch.
- **Config / env:** `HERMES_TENANT`; board env chain; dispatcher config (`kanban.dispatch_in_gateway`).
- **Edge cases / guards:** Relative `workspace_path` rejected at dispatch. `provider` without `model` is invalid. Delegated children rejected.
- **Rebuild notes:** `idempotency_key` + parent-gated promotion + per-task runtime cap are the three fields that make agent fan-out survivable in production.

### kanban_heartbeat  `id: tools.tool-kanban-heartbeat`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_heartbeat`, toolset `kanban`, emoji 💓; registered `:2410`, handler `_handle_heartbeat`, gate `_check_kanban_mode`.
- **What it does:** Signals liveness during a long operation so humans can distinguish "working" from "hung" without PID checks.
- **How it works:** Writes a heartbeat event on the task; pure side effect, no state change.
- **Inputs / options:** `task_id` (string, optional); `note` (string, optional) — "Optional short note describing current progress. Shown in the event log."; `board` (string, optional).
- **Outputs / side effects:** An event-log row.
- **Config / env:** board env chain.
- **Edge cases / guards:** Description asks for a call "every few minutes" during training / encoding / large crawls. Delegated children rejected.
- **Rebuild notes:** An explicit heartbeat with an optional progress note is far more useful to a human than process liveness.

### kanban_link  `id: tools.tool-kanban-link`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_link`, toolset `kanban`, emoji 🔗; registered `:2473`, handler `_handle_link`, gate `_check_kanban_mode`.
- **What it does:** Adds a parent→child dependency edge between two existing tasks.
- **How it works:** Inserts a dependency row; the child will not promote to `ready` until all parents are `done`.
- **Inputs / options:** `parent_id` (string, REQUIRED); `child_id` (string, REQUIRED); `board` (string, optional). No `task_id`.
- **Outputs / side effects:** Dependency edge; promotion gating changes.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Cycles and self-links are rejected." Delegated children rejected.
- **Rebuild notes:** Post-hoc linking (rather than only at create time) is what lets an orchestrator restructure a plan mid-flight.

### kanban_list  `id: tools.tool-kanban-list`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_list`, toolset `kanban`, emoji 📋; registered `:2365`, handler `_handle_list`, gate `_check_kanban_orchestrator_mode` (ORCHESTRATOR-ONLY).
- **What it does:** Lists task summaries so an orchestrator profile can discover work to route.
- **How it works:** Recomputes ready tasks before listing (matching the CLI), then returns compact rows. `KANBAN_LIST_DEFAULT_LIMIT = 50`, `KANBAN_LIST_MAX_LIMIT = 200`, with truncation metadata in the response.
- **Inputs / options:** `assignee` (string, optional) — assignee/profile filter; `status` (string, optional, enum `triage`|`todo`|`ready`|`running`|`blocked`|`done`|`archived`); `tenant` (string, optional); `include_archived` (boolean, optional, default false); `limit` (integer, optional, default 50, max 200); `board` (string, optional).
- **Outputs / side effects:** Read-only rows: ids, title, status, assignee, priority, parent/child ids, and counts.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Orchestrator-only — dispatcher-spawned task workers never see this tool." (`_check_kanban_orchestrator_mode` returns False when `HERMES_KANBAN_TASK` is set and the process is a dispatcher-owned worker.)
- **Rebuild notes:** Hiding board enumeration from workers is a deliberate least-privilege choice, not an oversight.

### kanban_request_changes  `id: tools.tool-kanban-request-changes`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_request_changes`, toolset `kanban`, emoji ↩; registered `:2401`, handler `_handle_request_changes`, gate `_check_kanban_mode`.
- **What it does:** Reviewer verdict that returns the current review run to the original implementer with concrete required changes.
- **How it works:** Closes the review run, reapplies parent dependency gating, and requeues the task — deliberately WITHOUT using block-loop accounting, so a review round trip never counts toward auto-escalation to triage.
- **Inputs / options:** `task_id` (string, optional); `reason` (string, REQUIRED) — "Specific, actionable changes the implementer must make before requesting another review."; `board` (string, optional).
- **Outputs / side effects:** Task requeued to the implementer; review run closed; event log entry.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Only use from a task claimed from the review column; use kanban_block only for a genuine external blocker." Delegated children rejected.
- **Rebuild notes:** Review rejection and external blocking must be different verbs with different accounting, or healthy review cycles get mistaken for stuck work.

### kanban_request_review  `id: tools.tool-kanban-request-review`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_request_review`, toolset `kanban`, emoji 👀; registered `:2392`, handler `_handle_request_review`, gate `_check_kanban_mode`.
- **What it does:** Hands the task off for review — implementation, self-review and verification are complete and a human or reviewer profile should look before it is marked done.
- **How it works:** Moves the task to the `review` column and notifies the subscriber. Explicitly NOT a blocker: it never counts toward unblock-loop detection, so a task can cycle through review across follow-ups without being falsely escalated to triage. With `reviewer` set, the task is reassigned to that profile before review dispatch.
- **Inputs / options:** `task_id` (string, optional); `summary` (string, REQUIRED) — "What was implemented and how it was verified, in one or two sentences — shown to the reviewer. Don't paste the whole diff; the reviewer has the board and the PR."; `reviewer` (string, optional) — "Optional reviewer profile."; `metadata` (object, optional) — "Optional structured handoff facts for the reviewer, such as changed_files, tests_run, commit, or decisions."; `board` (string, optional).
- **Outputs / side effects:** Column move, reassignment, subscriber notification.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Use this instead of blocking with a free-form 'review-required:' reason." Delegated children rejected.
- **Rebuild notes:** First-class review as its own column and verb is the difference between a board that models a workflow and one that models a to-do list.

### kanban_show  `id: tools.tool-kanban-show`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_show`, toolset `kanban`, emoji 📋; registered `:2356`, handler `_handle_show`, gate `_check_kanban_mode`.
- **What it does:** Reads a task's full state so a worker can (re)orient itself before starting, especially on retries.
- **How it works:** Assembles title, body, assignee, parent-task handoffs, this worker's prior attempts on the task if any, comments, and recent events — plus a pre-formatted `worker_context` string the agent is told to include verbatim in its reasoning.
- **Inputs / options:** `task_id` (string, optional); `board` (string, optional).
- **Outputs / side effects:** Read-only JSON including `worker_context`.
- **Config / env:** board env chain.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Shipping a ready-to-paste `worker_context` block removes the model's need to re-serialise board state itself — a cheap way to make retries deterministic.

### kanban_unblock  `id: tools.tool-kanban-unblock`
- **Surface:** Tool
- **Where:** Model-callable tool `kanban_unblock`, toolset `kanban`, emoji ▶; registered `:2464`, handler `_handle_unblock`, gate `_check_kanban_orchestrator_mode` (ORCHESTRATOR-ONLY).
- **What it does:** Unblocks a blocked kanban task.
- **How it works:** Moves the task to `ready` when all parents are `done`, or to `todo` while any parent remains open.
- **Inputs / options:** `task_id` (string, REQUIRED) — "Blocked task id to move to ready or parent-gated todo."; `board` (string, optional).
- **Outputs / side effects:** Status transition; event log entry; the dispatcher may pick the task up on its next tick.
- **Config / env:** board env chain.
- **Edge cases / guards:** "Orchestrator-only — only profiles with the kanban toolset can unblock routed work; dispatcher-spawned task workers never see this tool." Delegated children rejected.
- **Rebuild notes:** Unblocking must respect parent gating rather than jumping straight to ready, or a dependency graph silently degrades into a flat queue.

### memory  `id: tools.tool-memory`
- **Surface:** Tool
- **Where:** Model-callable tool `memory`, toolset `memory`, emoji 🧠.
- **What it does:** Saves durable facts to persistent cross-session memory (two stores: `memory` = the agent's own notes, `user` = the user profile). Memory is injected into every future turn.
- **How it works:** `tools/memory_tool.py` (62 KB), registered `:1375`; handler forwards `kw["store"]` (the `MemoryStore`). Gate `check_memory_requirements()` (`:1208`) snapshots `get_builtin_memory_store_flags()` into a contextvar `_memory_surface_flags` and returns `flags[0] or flags[1]` — i.e. available when either built-in store is enabled. `dynamic_schema_overrides=_build_memory_schema_overrides` then NARROWS the advertised `target` enum to the enabled stores and rewrites the TARGETS paragraph accordingly: with only `memory`, "TARGET: only 'memory' is enabled for personal notes (environment, conventions, tool quirks, lessons)."; with only `user`, "TARGET: only 'user' is enabled for user profile facts (name, role, preferences, style)." Batch semantics: an `operations` array applies ATOMICALLY and the character limit is checked only on the FINAL result, so one call can remove/replace stale entries to free room AND add new ones even when the add alone would overflow. `_memory_target_error(store, target)` returns `Invalid memory target '<t>'. Use 'memory' or 'user'.` or `Built-in <MEMORY.md|USER.md> writes are disabled in memory config.`
- **Inputs / options:** `target` (string, REQUIRED, enum `memory`|`user` — narrowed at serving time) — "Which memory store: 'memory' for personal notes, 'user' for user profile."; `action` (string, optional, enum `add`|`replace`|`remove`) — "The action to perform (single-op shape). Omit when using 'operations'."; `content` (string, optional) — "The entry content. Required for 'add' and 'replace' (single-op shape). Alias: 'new_text' is also accepted (mirrors old_text)."; `old_text` (string, optional) — "REQUIRED for 'replace' and 'remove' (single-op shape): a short unique substring identifying the existing entry to modify. Omit only for 'add'."; `new_text` (string, optional) — "Alias for 'content' (single-op shape)… if both are set, 'content' wins."; `operations` (array, optional) — items are objects `{action (REQUIRED, enum add|replace|remove), content (alias new_text), new_text, old_text}`; "Batch shape: a list of operations applied atomically in one call against the final char budget."
- **Outputs / side effects:** Writes `MEMORY.md` / `USER.md` under the profile's Hermes home. The response reports current/limit chars and confirms completion — the description explicitly says "one batch call finishes the update, so don't repeat it".
- **Config / env:** `memory.*` config decides which built-in stores are enabled (`get_builtin_memory_store_flags`); memory-provider plugins (e.g. Honcho) inject their own tools through `MemoryManager` rather than this toolset.
- **Edge cases / guards:** When full, an add is rejected with the current entries shown, and the model is told to reissue as ONE batch that removes/shortens and adds together. Guidance: save proactively on preferences, corrections, personal details, stable environment/convention/workflow facts; priority "user preferences & corrections > environment facts > procedures"; SKIP trivial/obvious info, easily re-discovered facts, raw data dumps, task progress, completed-work logs, temporary TODO state (use `session_search`); reusable procedures belong in a skill. Children spawned by `delegate_task` cannot call `memory`. MUTATING in the loop guardrails.
- **Rebuild notes:** Atomic batch with the size check on the FINAL state is the key design — it is the only way a full memory can be edited without a dead-end rejection loop. Narrowing the `target` enum from live config prevents the model from writing to a disabled store.

### patch  `id: tools.tool-patch`
- **Surface:** Tool
- **Where:** Model-callable tool `patch`, toolset `file`, emoji 🔧, `max_result_size_chars=100_000`.
- **What it does:** Targeted find-and-replace edits in files, with fuzzy matching so minor whitespace/indentation differences do not break the edit.
- **How it works:** `tools/file_tools.py` (134 KB) + `tools/fuzzy_match.py` (49 KB, "9 strategies") + `tools/patch_parser.py`; handler `_handle_patch` registered `:2923`; gate `_check_file_reqs` → `tools.check_file_requirements()` → `terminal_tool.check_terminal_requirements()` (file tools require the terminal backend to be available). Returns a unified diff and auto-runs syntax checks after editing. `dynamic_schema_overrides=_patch_schema_overrides` layers a second edit mode onto the schema when `_is_openai_family_main()` (`tools/file_tools.py:2779`) — provider in `{openai, openai-chat, openai-codex, azure-openai, codex}`, or on aggregators (openrouter/nous/azure) a model slug matching `gpt-*` / o-series / codex. That population was trained on the V4A `apply_patch` dialect; the check fails closed to the universal replace-only schema.
- **Inputs / options (always):** `path` (string, REQUIRED) — "File path to edit."; `old_string` (string, REQUIRED) — "Exact text to find and replace. Must be unique in the file unless replace_all=true. Include surrounding context lines to ensure uniqueness."; `new_string` (string, REQUIRED) — "Changed replacement text; it must differ from old_string. Pass empty string '' to delete the matched text."; `replace_all` (boolean, optional, default `False`).
- **Inputs / options (OpenAI-family only, injected):** `mode` (string, enum `replace`|`patch`, default `replace`, and it becomes the sole `required` field) — "'replace' (default): requires path + old_string + new_string. 'patch': requires patch content only."; `patch` (string) — "REQUIRED when mode='patch'. V4A format patch content. Format:\n*** Begin Patch\n*** Update File: path/to/file\n@@ context hint @@\n context line\n-removed line\n+added line\n*** End Patch". The description also changes to `_PATCH_V4A_DESCRIPTION` documenting both modes.
- **Outputs / side effects:** File modified on disk; unified diff returned; syntax check results. `file_mutation_result_landed("patch", result)` treats `success: true` as proof the write landed.
- **Config / env:** `tool_output.*` limits; main provider/model (for the V4A mode).
- **Edge cases / guards:** `new_string` must differ from `old_string`. Non-unique `old_string` without `replace_all` is an error. In `FILE_MUTATING_TOOL_NAMES` and `MUTATING_TOOL_NAMES`.
- **Rebuild notes:** Serving a different edit dialect to the model family that was trained on it — decided by provider/model family, failing closed — is a genuinely clever adaptation. Nine fuzzy-match strategies are what make LLM-authored `old_string` values usable.

### process  `id: tools.tool-process`
- **Surface:** Tool
- **Where:** Model-callable tool `process`, toolset `terminal`, emoji ⚙️. No `check_fn` (always available once the toolset is on).
- **What it does:** Manages background processes started by `terminal(background=true)`: poll, read logs, wait, write to stdin, kill.
- **How it works:** `tools/process_registry.py` (158 KB, 3491 lines); handler `_handle_process` registered `:3485`. Session ids look like `proc_4dae56ca81f6` and any unique prefix resolves.
- **Inputs / options:** `action` (string, REQUIRED, enum `list`|`poll`|`log`|`wait`|`kill`|`write`|`submit`|`close`); `session_id` (string, optional) — "From terminal background output; any unique prefix works ('4dae' for proc_4dae56ca81f6). Required except for 'list'."; `data` (string, optional) — "Stdin text for write/submit."; `timeout` (integer, optional, minimum 1) — "Max seconds for 'wait'."; `offset` (integer, optional) — "Log line offset (default: last 200)."; `limit` (integer, optional, minimum 1) — "Max log lines."
- **Action semantics (verbatim):** poll = "status + new output"; log = "full output, paged"; wait = "block until exit or timeout (partial output on timeout)"; "write vs submit: submit appends Enter — use it to answer prompts; write sends raw bytes, no newline"; close = "EOF stdin"; kill = "terminate".
- **Outputs / side effects:** Process control (stdin writes, termination); log excerpts.
- **Config / env:** none directly.
- **Edge cases / guards:** `process` is the ONLY member of `STALL_GUARD_REPEATABLE_TOOLS` (`agent/tool_guardrails.py:63`) — repeated identical `process(action="poll")` calls never trigger the identical-call loop notice, because polling for external progress is legitimate. Simultaneously listed in `MUTATING_TOOL_NAMES`.
- **Rebuild notes:** The `write`/`submit` split (raw bytes vs bytes+Enter) is the detail that makes interactive prompts answerable; exempting the poller from loop detection is required or the guardrail fights the feature.

### react_to_message  `id: tools.tool-react-to-message`
- **Surface:** Tool
- **Where:** Model-callable tool `react_to_message`, toolset `desktop_ui`, emoji 💛. Desktop app only, and additionally behind a user toggle.
- **What it does:** Attaches (or retracts) a single-emoji reaction on a message — the agent's equivalent of the user's tapback.
- **How it works:** `tools/react_to_message_tool.py:98` `react_to_message_tool(emoji, message_row_id, messages_back)`; registered `:182`. Session key from `HERMES_SESSION_KEY` or `HERMES_SESSION_ID` (`gateway.session_context.get_session_env`). Opens `hermes_state.SessionDB`; when no `message_row_id` is given it resolves `db.latest_message_row_id(session_key, role="user", offset=messages_back)`; otherwise reads the row's role via `db.get_message_role`. Writes with `db.set_message_reaction(session_key, row_id, emoji or None, author="agent")` — one reaction per author per message. Then emits `message.reaction` with `{row_id, reactions, role}` so the renderer paints it live without waiting for a resume (`role` lets the renderer match a live message that has not learned its durable row id yet). A missing bridge is NOT an error: the reaction is persisted either way. Gate `check_react_requirements()` (`:119`) reads `display.message_reactions` from `load_config_readonly()` — the desktop's Settings → Appearance switch, mirrored into the CONNECTED gateway's config so it reads correctly for local, SSH, URL or cloud backends.
- **Inputs / options:** `emoji` (string, REQUIRED) — "The emoji to react with (e.g. '❤️', '😂', '👍'). Pass an empty string to remove your reaction."; `message_row_id` (integer, optional) — "Optional. The specific message to react to. Omit to react to the user's latest message, which is almost always what you want."; `messages_back` (integer, optional) — "Optional. React to an EARLIER user message: 1 = the one before the latest, 2 = two before, and so on. For when something lands late — the joke you only got after answering."
- **Outputs / side effects:** A persisted reaction row; a live renderer paint. Returns `{"success": true, "row_id": N, "reactions": {…}}`.
- **Config / env:** `display.message_reactions` (boolean, default false — the tool is unavailable until switched on); `HERMES_SESSION_KEY` / `HERMES_SESSION_ID` / `HERMES_UI_SESSION_ID`.
- **Edge cases / guards:** No session key → `No active session — reactions need a persisted conversation.` No SessionDB → `Session storage is unavailable.` No user message at that offset → `No user message found N back.` / `No user message to react to yet.` Row not in this conversation → `Message <id> is not part of this conversation.` Write failure → `Failed to set the reaction: <exc>`. Behavioural rule in the description: "NEVER narrate or explain a reaction… the emoji appearing on the bubble is the whole point".
- **Rebuild notes:** Defaulting the target to "the message that triggered this turn" (with `messages_back` for retroactive reactions) removes row-id threading from the model's job entirely.

### read_file  `id: tools.tool-read-file`
- **Surface:** Tool
- **Where:** Model-callable tool `read_file`, toolset `file`, emoji 📖, `max_result_size_chars=100_000`, and the ONLY entry in `PINNED_THRESHOLDS` (`float("inf")`) so its results are never persisted-and-previewed.
- **What it does:** Reads a text file with line numbers and pagination, auto-extracting readable text from common document formats.
- **How it works:** `tools/file_tools.py` schema at `:2670`ff, handler `_handle_read_file` registered `:2899`; gate `_check_file_reqs`. Output format is `LINE_NUM|CONTENT`. Extraction goes through `tools/read_extract.py` (31 KB) — firecrawl-anydoc is a core bundled dependency, so its absence is a broken install rather than a configuration, and a teaching error carries the pip-install fix. `dynamic_schema_overrides=_read_file_schema_overrides` performs a ONE-WORD capability upgrade: `"PDF (text layer)"` → `"PDF (scanned or text)"` when `read_extract.hosted_ocr_available()` finds a trusted OCR route (config/env probe only, no network at schema-build time); compaction's tool refresh (#97073) picks up a key added mid-session. Scanned-page teaching lives in the response-time NEEDS-OCR warning, not the schema.
- **Inputs / options:** `path` (string, REQUIRED) — "Path to the file to read (absolute, relative, or ~/path)"; `offset` (integer, optional, default `1`, minimum 1) — "Line number to start reading from (1-indexed, default: 1)"; `limit` (integer, optional, default `2000`, maximum `2000`) — "Maximum number of lines to read (default: 2000, max: 2000). Reads are additionally capped at a ~100K-character budget with a next_offset continuation."
- **Outputs / side effects:** Read-only. Line-numbered text; `next_offset` when truncated on a line boundary; suggested similar filenames when the path is not found.
- **Config / env:** `tool_output.max_lines` (default 2000) and `tool_output.max_line_length` (default 2000) via `tools/tool_output_limits.py`.
- **Edge cases / guards:** Auto-extracted formats named in the schema: `.ipynb`, Office (`.docx`/`.xlsx`/`.pptx` and legacy `.doc`/`.ppt`/`.xls`), PDF (text layer, or scanned when OCR is available), OpenDocument, RTF, EPUB. "Cannot read images/binary — use vision_analyze for images." In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`. The `inf` pinned threshold exists specifically to prevent infinite persist→read→persist loops.
- **Rebuild notes:** Pinning the reader's spill threshold to infinity is a non-obvious requirement of any spill-to-disk design; and a one-word, config-probed schema mutation is a cheap way to keep capability claims honest.

### read_terminal  `id: tools.tool-read-terminal`
- **Surface:** Tool
- **Where:** Model-callable tool `read_terminal`, toolset `desktop_ui`, emoji 🖥️. Desktop app only.
- **What it does:** Reads the in-app terminal pane beside the chat, including scrollback paging.
- **How it works:** `tools/read_terminal_tool.py:20` `read_terminal_tool(start_line, count, callback)`; registered `:77`. The buffer lives in the desktop renderer (xterm.js), so the tool round-trips the gateway blocking-prompt bridge: `tui_gateway` emits `terminal.read.request`, the renderer answers `terminal.read.respond`. Window arguments are coerced with floors: `start` ≥ 0, `count` ≥ 1.
- **Inputs / options:** `start_line` (integer, optional) — "0-indexed first line (0 = oldest). Omit for the visible screen."; `count` (integer, optional) — "Lines to read from start_line. Defaults to the visible row count."
- **Outputs / side effects:** Read-only. JSON `{total_lines, start, end, viewport_rows, cursor_row, text}`, or `{"text": "<raw>"}` when the renderer's answer is not JSON.
- **Config / env:** none; `HERMES_UI_SESSION_ID` routing.
- **Edge cases / guards:** No callback → `read_terminal is only available in the Hermes desktop app.` Non-integer window args → `start_line and count must be integers.` Empty answer → `No in-app terminal is open, or the read timed out.` Callback exception → `Failed to read terminal: <exc>`. In `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Returning `cursor_row` and `viewport_rows` alongside the text lets the model reason about what the user can actually see.

### read_window_below  `id: tools.tool-read-window-below`
- **Surface:** Tool
- **Where:** Model-callable tool `read_window_below`, toolset `desktop_ui`, emoji 🪟. Desktop app only.
- **What it does:** Identifies the OS window sitting directly behind the Hermes desktop window — what the user is actually working in.
- **How it works:** `tools/read_window_tool.py:18` `read_window_below_tool(callback)`; registered `:60`. Round-trips the blocking-prompt bridge: `tui_gateway` emits `window.read.request`, the renderer asks its Electron main process (which owns native window enumeration) and answers `window.read.respond`.
- **Inputs / options:** none (`properties: {}`).
- **Outputs / side effects:** Read-only metadata: `{window: {app, title, bounds, id}, frontmost, platform}`. "Metadata only; never captures pixels."
- **Config / env:** none.
- **Edge cases / guards:** No callback → `read_window_below is only available in the Hermes desktop app.` No answer → `Could not determine the window underneath (the desktop app did not answer, or window enumeration is unavailable on this system).` `title` may be empty when the OS withholds it, noted in a `note` field; where windows cannot be enumerated at all the result is `{error, platform}` and the description tells the model to relay it rather than retry. Callback exception → `Failed to read the window below: <exc>`.
- **Rebuild notes:** Explicitly promising "never captures pixels" in the tool description is the right way to make an ambient-awareness capability acceptable.

### search_files  `id: tools.tool-search-files`
- **Surface:** Tool
- **Where:** Model-callable tool `search_files`, toolset `file`, emoji 🔎, `max_result_size_chars=100_000`.
- **What it does:** Searches file contents by regex (ripgrep-backed) or finds files by glob — the replacement for `grep`/`rg`/`find`/`ls` in the terminal.
- **How it works:** `tools/file_tools.py`, handler `_handle_search_files` registered `:2924`; gate `_check_file_reqs`. File-search results are sorted by modification time. On macOS, broad searches above the user home automatically skip TCC-protected folders — Desktop, Documents, Downloads, Library, Movies, Music, Pictures — and the description tells the model to target one directly when access is intentional.
- **Inputs / options:** `pattern` (string, REQUIRED) — "Regex pattern for content search, or glob pattern (e.g., '*.py') for file search"; `target` (string, optional, enum `content`|`files`, default `content`); `path` (string, optional, default `.`) — "Directory or file to search in (default: current working directory)"; `file_glob` (string, optional) — "Filter files by pattern in grep mode (e.g., '*.py' to only search Python files)"; `limit` (integer, optional, default `50`); `offset` (integer, optional, default `0`) — "Skip first N results for pagination"; `output_mode` (string, optional, enum `content`|`files_only`|`count`, default `content`) — "'content' shows matching lines with line numbers, 'files_only' lists file paths, 'count' shows match counts per file"; `context` (integer, optional, default `0`) — "Number of context lines before and after each match (grep mode only)".
- **Outputs / side effects:** Read-only search results.
- **Config / env:** none directly.
- **Edge cases / guards:** In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`. macOS TCC skip list as above.
- **Rebuild notes:** Folding "grep" and "find" into one tool with a `target` switch, plus mtime-sorted file results, replaces four shell commands with one bounded, paginated call.

### write_file  `id: tools.tool-write-file`
- **Surface:** Tool
- **Where:** Model-callable tool `write_file`, toolset `file`, emoji ✍️, `max_result_size_chars=100_000`.
- **What it does:** Writes content to a file, completely replacing existing content and creating parent directories automatically.
- **How it works:** `tools/file_tools.py` schema at `:2705`ff, handler `_handle_write_file` registered `:2900`; gate `_check_file_reqs`. Auto-runs syntax checks on `.py`/`.json`/`.yaml`/`.toml` and other linted languages, surfacing ONLY new errors introduced by this write (pre-existing errors are filtered out). The result's `verified: true` means the on-disk content hash was confirmed — the description explicitly instructs the model NOT to re-read the file to check the write landed.
- **Inputs / options (advertised):** `path` (string, REQUIRED) — "Path to the file to write (will be created if it doesn't exist, overwritten if it does)"; `content` (string, REQUIRED) — "Complete content to write to the file".
- **Inputs / options (accepted, deliberately unadvertised):** `cross_profile` (boolean) — now bypasses only the #32049 sandbox-mirror lost-write guards, whose rejection error teaches its use; the cross-profile guard it was named for was removed (profiles are not isolated, maintainer decision).
- **Outputs / side effects:** File created/overwritten; parent dirs created; `bytes_written` in the result (the field `file_mutation_result_landed` checks); syntax-check findings.
- **Config / env:** none directly.
- **Edge cases / guards:** OVERWRITES the whole file — the description points at `patch` for targeted edits. In `FILE_MUTATING_TOOL_NAMES` and `MUTATING_TOOL_NAMES`.
- **Rebuild notes:** Returning a verified content hash and telling the model not to re-read is a measurable turn saving; filtering syntax errors down to newly-introduced ones is what keeps the signal usable in a messy repo.

### session_search  `id: tools.tool-session-search`
- **Surface:** Tool
- **Where:** Model-callable tool `session_search`, toolset `session_search`, emoji 🔍.
- **What it does:** Searches past Hermes sessions with SQLite FTS5, or reads/scrolls inside one. Results are actual DB messages — no LLM summarisation.
- **How it works:** `tools/session_search_tool.py` (52 KB), registered `:1254`; handler forwards `kw["db"]` and `kw["current_session_id"]`. Gate `check_session_search_requirements()` (`:1136`) checks `hermes_state._default_db_path().parent.exists()`. Four call shapes picked by argument combination: `query` = discovery (top-N matching sessions, top result fully hydrated); `session_id` + `around_message_id` = scroll (window around an anchor); `session_id` alone = read a whole session (how an `@session:<profile>/<id>` link is resolved — split on `/` into profile + id); no args = browse recent sessions.
- **Inputs / options:** `query` (string, optional) — "Search query (discovery shape). Keywords, phrases, or boolean expressions… Ignored when session_id + around_message_id are set (scroll shape)."; `limit` (integer, optional, default `3`) — "Discovery shape only. Max sessions to return (default 3, max 10). Bump to 5–10 when the topic likely spans several sessions…"; `sort` (string, optional, enum `newest`|`oldest`) — "Temporal bias on top of FTS5 ranking: omit for relevance-only (exploratory recall), 'newest' for \"where did we leave X\", 'oldest' for \"how did X start\"."; `detail` (string, optional, enum `adaptive`|`full`, default `adaptive`) — "'adaptive' fully hydrates the top-ranked result and returns only the exact anchor message for lower-ranked results. 'full' returns bookends and the complete anchored window for every result."; `session_id` (string, optional) — "Scroll shape. Session to read inside… Must be paired with around_message_id."; `around_message_id` (integer, optional) — "use match_message_id from a discovery result, or any id from a prior window."; `window` (integer, optional, default `5`) — "Messages to return on each side of the anchor (anchor itself always included). Clamped to [1, 20]."; `role_filter` (string, optional) — "Comma-separated roles to include. Discovery defaults to 'user,assistant' (tool output is usually noise). Pass 'user,assistant,tool' to include tool output… or 'tool' to search tool output only."; `profile` (string, optional) — "Read sessions from another Hermes profile's database (read-only)."
- **Outputs / side effects:** Read-only DB rows; each result carries a `link` value the model is told to write verbatim inline (it renders as a titled link) and a `match_message_id` for scrolling.
- **Config / env:** the SQLite session DB under HERMES_HOME; cross-profile reads via `profile`.
- **Edge cases / guards:** "Searches conversation history ONLY — when the user gave a direct source (URL, file, contact, live system), inspect that first; never conclude 'not found' from history alone." In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** One tool with four shapes selected by argument presence is cheaper than four tools; `detail: adaptive` (hydrate only the top hit) is the trick that keeps discovery affordable.

### setup_mcp  `id: tools.tool-setup-mcp`
- **Surface:** Tool
- **Where:** Model-callable tool `setup_mcp`, toolset `desktop_ui`, emoji 🔌. Desktop app only.
- **What it does:** Proposes an MCP server to the user as an inline consent card (install a catalog entry, re-enable a disabled server, or run OAuth) and blocks until they act.
- **How it works:** `tools/setup_mcp_tool.py:21` `setup_mcp_tool(server, action, reason, callback)`; registered `:107`, no `check_fn`. Round-trips the blocking-prompt bridge: `tui_gateway` emits `mcp.setup.request`; the renderer walks the user through the flow via the existing REST endpoints (catalog install, enable, OAuth) and answers `mcp.setup.respond`. `_ACTIONS = ("install","enable","authorize")`.
- **Inputs / options:** `server` (string, REQUIRED) — "Catalog name (install) or mcp_servers config name (enable/authorize)."; `action` (string, optional, enum `install`|`enable`|`authorize`) — "Defaults to install."; `reason` (string, optional) — "One sentence on the card: why this helps right now."
- **Outputs / side effects:** May install/enable an MCP server or complete an OAuth flow, mutating `mcp_servers` config. Returns the renderer's JSON, or `{"status":"unanswered","server":…,"note":"The user did not respond to the setup card. Do not retry immediately; continue without the server or ask in chat."}` on timeout, or `{"status":"error","detail":…}` for a non-JSON answer. An explicit decline arrives as `{"status": "declined"}`.
- **Config / env:** `mcp_servers` in config.yaml.
- **Edge cases / guards:** No callback → an error naming the terminal fallbacks: "Use the terminal instead: `hermes mcp install <name>` for catalog entries, `hermes mcp login <name>` for OAuth." Empty server → `server is required — the catalog or config name of the MCP server.` Bad action → `action must be one of install, enable, authorize.` Behavioural rules: "Never hand-edit mcp_servers config for them — always use this tool. Never re-ask after a decline."
- **Rebuild notes:** Distinguishing "declined" from "unanswered" in the return shape is what lets the model behave correctly in both cases without guessing.

### skill_manage  `id: tools.tool-skill-manage`
- **Surface:** Tool
- **Where:** Model-callable tool `skill_manage`, toolset `skills`, emoji 📝. No `check_fn`.
- **What it does:** Creates, patches and deletes skills (the agent's procedural memory) and their supporting files, as one atomic operations array.
- **How it works:** `tools/skill_manager_tool.py` (90 KB, 2220 lines), registered `:2201`; handler forwards `task_id` and `session_id`. Atomicity: "any failure rolls every touched skill back". New skills land in `<HERMES_HOME>/skills/`; existing skills are modified wherever they live (including external dirs from `skills.external_dirs`). `patch` uses the same matching semantics as the `patch` tool. Supporting-file paths are relative to the skill's own directory and the first segment must be one of `references/`, `templates/`, `scripts/`, `assets/`.
- **Inputs / options:** `operations` (array, REQUIRED) — "Ordered ops; each names its target skill." Item fields: `name` (string, REQUIRED) — "Skill name (lowercase, hyphens/underscores, max 64 chars); an existing skill's name unless creating."; `action` (string, REQUIRED, enum `create`|`patch`|`delete`|`write_file`|`remove_file`); `content` (string) — "Full SKILL.md text (YAML frontmatter + markdown body) for create, or a full rewrite on patch."; `category` (string) — "Optional category subdir for create (e.g. 'devops')."; `old_string` (string) — "Text to find (patch; same matching semantics as the patch tool)."; `new_string` (string) — "Replacement (patch); empty string deletes the match."; `replace_all` (boolean) — "patch: replace all occurrences (default false)."; `file_path` (string) — "Path RELATIVE to the skill's own directory, e.g. 'references/api.md' — no leading slash, never absolute. write_file/remove_file: required; first segment references/, templates/, scripts/, or assets/. patch: optional (default SKILL.md)."; `file_content` (string) — "Content for write_file."
- **Inputs / options (accepted, legacy singular shape):** the handler also accepts top-level `action`, `name`, `content`, `category`, `file_path`, `file_content`, `old_string`, `new_string`, `replace_all`, `absorbed_into` — none of which appear in the published schema.
- **Outputs / side effects:** SKILL.md files and supporting files created/edited/removed on disk; skill ledger / usage bookkeeping (`tools/skill_ledger.py`, `tools/skill_usage.py`, `tools/skill_provenance.py`); lint feedback (`tools/skill_linter.py`); guard checks (`tools/skills_guard.py`, `tools/skills_ast_audit.py`).
- **Config / env:** `<HERMES_HOME>/skills/`, `skills.external_dirs`.
- **Edge cases / guards:** `create` must precede that skill's other ops in the array. `delete` must be the sole op. Naming rule for discoverability: "Keep the description's first 57 chars a self-contained trigger: 'Use when <trigger>. <one-line behavior>.'" MUTATING in the loop guardrails.
- **Rebuild notes:** Atomic multi-skill edits with rollback, plus a constrained supporting-file namespace, are what let an agent safely edit its own procedural memory. The 57-character trigger rule is a concrete, checkable convention worth stealing.

### skill_view  `id: tools.tool-skill-view`
- **Surface:** Tool
- **Where:** Model-callable tool `skill_view`, toolset `skills`, emoji 📚.
- **What it does:** Loads a skill's full SKILL.md content, or one of its linked files (references, templates, scripts).
- **How it works:** `tools/skills_tool.py` (86 KB), handler `_skill_view_with_bump` registered `:2184` (the "bump" records skill usage). Gate `check_skills_requirements()` (`:565`) always returns True — "the directory is created on first use if needed". The first call returns SKILL.md plus a `linked_files` dict listing available references/templates/scripts; a second call with `file_path` fetches one of them. `_get_category_from_path` derives a category from the directory structure (e.g. `~/.hermes/skills/mlops/axolotl/SKILL.md` → `mlops`), checking the active profile skills dir first and then `skills.external_dirs`.
- **Inputs / options:** `name` (string, REQUIRED) — "The skill name (use skills_list to see available skills). For plugin-provided skills, use the qualified form 'plugin:skill' (e.g. 'superpowers:writing-plans')."; `file_path` (string, optional) — "OPTIONAL: Path to a linked file within the skill (e.g., 'references/api.md', 'templates/config.yaml', 'scripts/validate.py'). Omit to get the main SKILL.md content."
- **Outputs / side effects:** Read-only content; a usage bump in the skill ledger.
- **Config / env:** `<HERMES_HOME>/skills/`, `skills.external_dirs`.
- **Edge cases / guards:** In `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Returning `linked_files` with the first read turns skills into a two-level progressive-disclosure format without a directory-listing tool.

### skills_list  `id: tools.tool-skills-list`
- **Surface:** Tool
- **Where:** Model-callable tool `skills_list`, toolset `skills`, emoji 📚.
- **What it does:** Lists available skills as name + description pairs.
- **How it works:** `tools/skills_tool.py`, registered `:2021`; handler `skills_list(category=…, task_id=kw["task_id"])`; gate `check_skills_requirements` (always True).
- **Inputs / options:** `category` (string, optional) — "Optional category filter to narrow results".
- **Outputs / side effects:** Read-only list.
- **Config / env:** `<HERMES_HOME>/skills/`, `skills.external_dirs`.
- **Edge cases / guards:** In `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Name+description only (never bodies) is the whole point — the list must stay cheap enough to hold in every turn.

### terminal  `id: tools.tool-terminal`
- **Surface:** Tool
- **Where:** Model-callable tool `terminal`, toolset `terminal`, emoji 💻, `max_result_size_chars=100_000`.
- **What it does:** Executes shell commands, foreground or background, with optional PTY and completion notifications.
- **How it works:** `tools/terminal_tool.py` (191 KB, 4223 lines); handler `_handle_terminal` registered `:4215`. Gate `check_terminal_requirements()` (`:3942`) branches on `_get_env_config()["env_type"]`: `local` → True; `docker` → `find_docker()` then `docker version` with a 5 s timeout and `stdin=DEVNULL`; `singularity` → `apptainer`/`singularity --version` with a 5 s timeout; `ssh` → requires `ssh_host` and `ssh_user`; plus `vercel_sandbox` (checked by `_check_vercel_sandbox_requirements`). Filesystem, cwd and exported environment variables persist between calls. Dangerous-command approval lives here (`tools/approval.py`, 271 KB) — the `clarify` tool's description explicitly defers confirmation to it. Output is auto-truncated with the full text saved to a file, capped by `tool_output.max_bytes` (default 50 000).
- **Inputs / options:** `command` (string, REQUIRED) — "The shell command to execute"; `background` (boolean, optional, default `False`) — "Run in the background, returning a session_id. Pair with notify=true for anything with a defined end (tests, builds, deploys)… Only servers/watchers/daemons that never exit should stay silent."; `timeout` (integer, optional, minimum 1) — "Max seconds to wait (default: 180, foreground max: 600). Returns INSTANTLY when command finishes… Foreground timeout above 600s is rejected; use background=true for longer commands."; `workdir` (string, optional) — "Working directory for this command (absolute path). Defaults to the session working directory."; `pty` (boolean, optional, default `False`) — "With background=true: run in a pseudo-terminal for interactive CLI tools (Codex, Claude Code, Python REPL). Local backend only."; `notify` (any type, optional) — "notify=true fires exactly one notification when the process exits… notify=['pattern', ...] instead notifies when a line matches a pattern — ONLY for one-shot readiness signals on processes that never exit (e.g. ['Application startup complete']); rate-limited and auto-disabled if it over-fires. Omit for silent daemons."
- **Outputs / side effects:** Command execution with all its effects; a `cwd` field the model is told to trust after `cd`/`pushd`; a `session_id` for background runs; a mirrored read-only terminal tab in the desktop GUI (closable with `close_terminal`); notifications.
- **Config / env:** `tool_output.max_bytes` (default 50 000, was `terminal_tool.MAX_OUTPUT_CHARS`); the terminal environment config (`env_type`: local / docker / singularity / ssh / vercel_sandbox and its parameters); approval config.
- **Edge cases / guards:** Anti-pattern list in the description: do NOT use `cat`/`head`/`tail` (use `read_file`), `grep`/`rg`/`find`/`ls` (use `search_files`), `sed`/`awk` (use `patch`), or `echo`/heredoc file creation (use `write_file`); "never pipe through tail/head to shorten" the output. After starting a server, verify readiness with a health check in a separate call — "no blind sleep loops". PTY is local-backend only. MUTATING in the loop guardrails; effect-capable in the result classification.
- **Rebuild notes:** Foreground returning instantly on completion (so a generous timeout costs nothing) plus `notify` on background exit removes almost all polling. Steering the model away from shell equivalents of first-class tools, in the tool description itself, is what keeps the structured tools in use.

### text_to_speech  `id: tools.tool-text-to-speech`
- **Surface:** Tool
- **Where:** Model-callable tool `text_to_speech`, toolset `tts`, emoji 🔊.
- **What it does:** Converts text to speech audio and returns a `MEDIA:` path the platform delivers as native audio.
- **How it works:** `tools/tts_tool.py` (180 KB, 4552 lines) plus `tools/tts_streaming.py`, `tools/tts_text_normalize.py`, `tools/neutts_synth.py`; registered `:4540`. Gate `check_tts_requirements()` (`:3717`) resolves the configured provider and checks exactly that one: a command provider config → True; `edge` → `_import_edge_tts()` or fall back to `_check_neutts_available()`; `elevenlabs` → SDK import plus `_resolve_provider_key("ELEVENLABS_API_KEY", "elevenlabs")`; `openai` → `importlib.util.find_spec("openai")`; and so on per provider. "Unrelated cloud credentials do not make the default Edge backend usable."
- **Inputs / options:** `text` (string, REQUIRED) — "Provider-specific per-request character caps apply automatically (OpenAI 4096, xAI 15000, MiniMax 10000, ElevenLabs 5k-40k depending on model); longer input is split into ordered chunks without silent truncation."; `output_path` (string, optional) — "Defaults to `<HERMES_HOME>/audio_cache/<timestamp>.mp3`"; `speed` (number, optional) — "Playback speed multiplier. 1.0 = normal, 0.5 = very slow (language learning), 2.0 = fast. Range: 0.25-4.0. Overrides the speed configured in config.yaml."; `instructions` (string, optional) — "Optional voice-design guidance: tone, emotion, pacing, accent, whispering, impressions (e.g. 'Speak in a cheerful, excited whisper'). Forwarded to the OpenAI backend (gpt-4o-mini-tts and OpenAI-compatible voice-design servers). Silently ignored by backends that don't support it."; `provider` (string, optional) — "Accepts built-in names (edge, openai, elevenlabs, minimax, xai, mistral, gemini, neutts, kittentts, piper), user-declared command provider names from tts.providers.<name>, or plugin-registered names."
- **Outputs / side effects:** An audio file on disk (default `<HERMES_HOME>/audio_cache/`, or `~/voice-memos/` in CLI mode) and a `MEDIA:` path. Compatible providers render as a voice bubble on Telegram; otherwise audio is sent as a regular attachment.
- **Config / env:** `tts.provider`, `tts.providers.<name>` (custom command providers), per-provider API keys (`ELEVENLABS_API_KEY`, …), `tts.speed`. Provider detail belongs to the media shard.
- **Edge cases / guards:** "Voice and provider are user-configured … not model-selected" — the `provider` argument exists as an override, not a routine choice. Long text is chunked, never silently truncated.
- **Rebuild notes:** Availability must mirror the dispatch path exactly (check only the resolved provider), or the tool advertises itself and then fails; chunking with ordered output beats a hard character limit.

### tip  `id: tools.tool-tip`
- **Surface:** Tool
- **Where:** Model-callable tool `tip`, toolset `desktop_ui`, emoji 💡. Desktop app only, ungated.
- **What it does:** Points at one element in the desktop UI with a small arrow bubble and one line of text — the quiet, chrome-free sibling of `tour`.
- **How it works:** `tools/tip_tool.py:31` `tip_tool(text, selector, title, side)` → `desktop_ui.emit("tip.show", payload)`; registered `:98`. Fire-and-forget (unlike `tour`, which blocks on a round-trip) because a tip is not a question and blocking would stall the reply it belongs to. Uses the same durable `data-tour` handles and the same discovery call (`tour(action="targets")`), but no scrim, no spotlight, no Next/Prev. `SIDES = ("top","right","bottom","left")`.
- **Inputs / options:** `text` (string, REQUIRED) — "The one-sentence bubble text."; `selector` (string, REQUIRED) — "Selector from tour targets."; `title` (string, optional) — "Optional heading."; `side` (string, optional, enum `top`|`right`|`bottom`|`left`) — "Omit for 'top'; flips at screen edges."
- **Outputs / side effects:** One bubble on screen (a new tip replaces the last). Returns `{"success": true, "selector": "<selector>"}`.
- **Config / env:** none. The desktop Settings → Appearance switch governs the app's own idle tip rotation, NOT this tool, which Hermes raises mid-conversation in answer to something the user said.
- **Edge cases / guards:** Empty text → `tip needs text — the one line the bubble says.` Empty selector → `tip needs a selector to point at. Call tour(action='targets') to see what's on screen and prefer a target reporting stable: true.` Bad side → `side must be one of: top, right, bottom, left.` No emitter → `tip is only available in the Hermes desktop app.` Emit exception → `Failed to show the tip: <exc>`. Usage rules: one tip at a time; say the same thing in chat too — "the bubble is a pointer, not the message"; sparingly, because "a bubble every turn stops being read".
- **Rebuild notes:** Fire-and-forget for decorations, blocking round-trip only for things whose success the model must know — that split keeps latency honest.

### todo  `id: tools.tool-todo`
- **Surface:** Tool
- **Where:** Model-callable tool `todo`, toolset `todo`, emoji 📋.
- **What it does:** Manages the session's task checklist; always returns the full current list.
- **How it works:** `tools/todo_tool.py` (17 KB, 450 lines), registered `:442`; handler forwards `kw["store"]`. Gate `check_todo_requirements()` (`:369`) always returns True. Behavioural guidance is deliberately baked into the static schema description so it is cached and never changes mid-conversation; the item shape and merge semantics live ONLY in the parameter schema (issue #95681 diet).
- **Inputs / options:** `todos` (array, optional) — "Task items to write." Item objects: `id` (string, REQUIRED); `content` (string, REQUIRED) — "Task description"; `status` (string, REQUIRED, enum `pending`|`in_progress`|`completed`|`cancelled`); `parent` (string) — "Optional id of another item, making this a nested subtask. Omit for top-level."; `merge` (boolean, optional, default `False`) — "true: update existing items by id, add new ones. false (default): replace the entire list with a fresh plan."
- **Outputs / side effects:** Session-scoped todo state; the full list is returned on every call. Calling with no parameters reads the current list.
- **Config / env:** none.
- **Edge cases / guards:** Rules from the description: use for complex tasks with 3+ steps or multiple user-provided tasks; "For 'all N items' tasks, enumerate every instance as its own checklist item so none are silently dropped"; list order is priority; only ONE item `in_progress` at a time; break large phases into subtasks via `parent`; "Mark an item completed only after the work is verified done, never based on intent. If something fails, cancel it and add a revised item." MUTATING in the loop guardrails.
- **Rebuild notes:** Replace-by-default with an opt-in `merge` avoids the classic drift where the model forgets items; requiring one `in_progress` is what makes the list readable as a status.

### tour  `id: tools.tool-tour`
- **Surface:** Tool
- **Where:** Model-callable tool `tour`, toolset `desktop_ui`, emoji 🧭. Desktop app only, ungated.
- **What it does:** Runs a guided tour in the desktop GUI — dims the screen, highlights an element, attaches a titled popover — either one step at a time (agent-paced) or as a step list the user pages with Next/Prev.
- **How it works:** `tools/tour_tool.py:36` `tour_tool(...)`; registered `:182`. No baked-in tour definitions: the agent discovers targets, then highlights any element by CSS selector with its own title/text. Two surfaces share one engine (driver.js in the renderer): `surface="app"` (Hermes's own DOM) and `surface="preview"` (the page loaded in the in-app browser/preview pane, so any web app can be toured). Round-trips the blocking-prompt bridge: `tui_gateway` emits `tour.request`, the renderer drives driver.js (injecting it into the preview webview when needed) and answers `tour.respond` so the agent knows whether the selector matched. `ACTIONS = ("targets","show","start","next","prev","stop")`, `SURFACES = ("app","preview")`, `SIDES = ("top","right","bottom","left")`.
- **Inputs / options:** `action` (string, REQUIRED, enum `targets`|`show`|`start`|`next`|`prev`|`stop`) — "targets first; show narrates; start hands over."; `surface` (string, optional, enum `app`|`preview`) — "'app' (default) or 'preview'."; `selector` (string, optional) — "show: selector from targets (prefer stable). Omit = centered narration."; `title` (string, optional) — "show: popover title."; `text` (string, optional) — "show: popover body."; `side` (string, optional, enum `top`|`right`|`bottom`|`left`) — "show: popover side; omit to auto-place."; `steps` (array, optional) — "start: ordered steps.", items are objects with `selector` ("Element to highlight; omit = centered narration."), `title` ("Popover title."), `text` ("Popover body."), `side` (enum top/right/bottom/left, "Popover side; omit to auto-place."); `step_index` (integer, optional) — "start: 0-indexed first step."
- **Outputs / side effects:** Screen dimming + highlight overlay in the desktop app or the preview webview. Returns the renderer's JSON (including whether the selector matched).
- **Config / env:** none; `HERMES_UI_SESSION_ID` routing.
- **Edge cases / guards:** No callback → `tour is only available in the Hermes desktop app.` Bad action/surface/side → `<field> must be one of: …`. `show` with no selector, title or text → `show needs a selector (and/or title/text for the popover).` `start` without a non-empty list → `start needs a non-empty steps array.`; a non-dict step → `steps[i] must be an object.`; an empty step → `steps[i] needs a selector and/or title/text.` No answer → `The tour request timed out, or no GUI window answered. For surface='preview' open a page in the preview pane first.` Usage rule: always call `action='targets'` first and prefer targets marked `stable: true` (their selectors survive re-renders).
- **Rebuild notes:** A generic tour engine plus a target-discovery call beats hard-coded tours, because the UI can change without breaking the agent; marking selectors `stable` is what makes discovery actionable.

### video_analyze  `id: tools.tool-video-analyze`
- **Surface:** Tool
- **Where:** Model-callable tool `video_analyze`, toolset `video`, emoji 🎬, **async handler**. Opt-in: `video` is not in the default toolset.
- **What it does:** Sends a video (URL or local path) to a video-capable multimodal model and answers a question about it.
- **How it works:** `tools/vision_tools.py` (96 KB), handler `_handle_video_analyze` registered `:2309`, `is_async=True`; gate `check_vision_requirements` (shared with `vision_analyze`).
- **Inputs / options:** `video_url` (string, REQUIRED) — "Video URL (http/https) or local file path to analyze."; `question` (string, REQUIRED) — "Your specific question about the video. The AI will describe what happens in the video and answer your question."
- **Outputs / side effects:** A text answer. Network upload of the video to the provider.
- **Config / env:** `auxiliary.vision.provider` and the vision fallback chain; provider matrix in the media shard.
- **Edge cases / guards:** Supported formats named in the schema: mp4, webm, mov, avi, mkv, mpeg. "large videos (>20 MB) may be slow; max ~50 MB." For images the description redirects to `vision_analyze`. Not in `NO_EFFECT_TOOL_NAMES`, so an interrupted call is treated as possibly effectful.
- **Rebuild notes:** Keep video behind an opt-in toolset — the cost and latency profile is nothing like image analysis.

### video_generate  `id: tools.tool-video-generate`
- **Surface:** Tool
- **Where:** Model-callable tool `video_generate`, toolset `video_gen`, emoji 🎬, `requires_env=[]`. The most schema-dynamic tool in the codebase.
- **What it does:** Generates a video from a text prompt, animates a still image, or guides generation with reference images — through whichever backend the user configured.
- **How it works:** `tools/video_generation_tool.py` (23 KB, 614 lines); handler `_handle_video_generate` registered `:604`. Gate `check_video_generation_requirements()` (`:154`) runs `hermes_cli.plugins._ensure_plugins_discovered()` then returns True if ANY provider in `agent.video_gen_registry.list_providers()` reports `is_available()`. `dynamic_schema_overrides=_build_dynamic_video_schema` rebuilds BOTH description and parameters from the resolved provider + model at every `get_definitions()` call. Static base description in the registry dump is the placeholder "(rebuilt at get_definitions() time — see _build_dynamic_video_schema)". With NO provider available, the schema collapses to `{prompt}` only and the description appends "No video backend is available. Calls will return an error until the user picks one via `hermes tools` → Video Generation."
- **Inputs / options (static base schema):** `prompt` (string, REQUIRED) — "Text instruction describing the desired video, motion, subject, style, camera movement, etc."; `duration` (integer, optional) — "Desired video duration in seconds. Providers clamp to their supported range. Omit for the provider default."; `aspect_ratio` (string, optional, enum `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, `3:2`, `2:3`, default `16:9`); `resolution` (string, optional, enum `480p`, `540p`, `720p`, `1080p`, default `720p`); `model` (string, optional) — "Optional model override; defaults to the configured ``video_gen.model``. Unknown models are rejected."
- **Inputs / options (conditionally injected):** `image_url` (string) — when the model's modalities include `image`: "Public HTTPS URL of a still image to animate (image-to-video). Omit for text-to-video."; `reference_image_urls` (array of string, maxItems = `caps["max_reference_images"]`) — "Up to N public HTTPS reference image URLs (style or character refs)."; `negative_prompt` (string) — when `supports_negative_prompt`: "Content to avoid in the output."; `audio` (boolean) — when `supports_audio`: "Enable native audio generation (affects pricing tier)."; `seed` (integer) — when `supports_seed`: "Seed for reproducible outputs."; `upscale` (boolean) — when `supports_upscale`: "High-resolution pass via the backend's video upscaler (~2x, extra cost/latency). Omit for native resolution." `duration` gains `minimum`/`maximum` and the description "Video duration in seconds (N-M). Omit for the provider default." when the model declares bounds; `aspect_ratio` and `resolution` enums tighten to the backend's declared sets.
- **Description clauses injected at serving time:** model caveats from `_format_model_caveats`; "- image-to-video only: image_url is REQUIRED" when the model cannot do text-to-video; "- text-to-video only (no image input)" when it cannot do image-to-video; for the xAI provider "- chaining: for edit/extend pass the public HTTPS MP4 in `video` or `public_url` from the prior Imagine result (files-cdn). For image-to-video / reference-to-video pass public image URLs the same way" plus a "- storage: …" notice from `tools.xai_http.xai_storage_notice_text("video_gen")`; "- audio: native stereo audio is generated with every video (always on; no toggle) — describe the desired sound in the prompt" when `audio_always_on`.
- **Base description (`_GENERIC_DESCRIPTION`, `tools/video_generation_tool.py:387`):** "Generate a video from a text prompt (text-to-video), animate a still image (image-to-video), or guide generation with reference images. Pass `image_url` to animate an image or `reference_image_urls` for reference-to-video. Video edit/extend workflows are not part of this unified surface; use a dedicated provider-specific tool when one is available. The backend and model family are user-configured via `hermes tools` → Video Generation; the agent does not pick them. Long-running generations may take 30 seconds to several minutes — the call blocks until the video is ready. Returns the result in the `video` field — either an HTTP URL or an absolute file path…"
- **Outputs / side effects:** The `video` field carries an HTTP URL or an absolute file path; the call BLOCKS until the video is ready (30 s to several minutes). Costs money.
- **Config / env:** `video_gen.provider`, `video_gen.model`; provider plugin credentials.
- **Edge cases / guards:** "Unknown models are rejected." The handler still accepts unadvertised args for replay compatibility — providers clamp or ignore them.
- **Rebuild notes:** This is the reference implementation of capability-derived schemas: enums, numeric bounds, optional parameters AND description caveats all come from the live backend. Copy the fail-safe: with no provider, advertise only `prompt` and say so in the description.

### vision_analyze  `id: tools.tool-vision-analyze`
- **Surface:** Tool
- **Where:** Model-callable tool `vision_analyze`, toolset `vision`, emoji 👁️, **async handler**.
- **What it does:** Loads an image into the conversation so the model can see it (or, without native vision, returns an auxiliary model's analysis).
- **How it works:** `tools/vision_tools.py`, handler `_handle_vision_analyze` registered `:1892`, `is_async=True`. Gate `check_vision_requirements()` (`:1720`) mirrors the runtime fallback chain of `call_llm(task="vision")`: inside `aux_probe_mode()` (avoids paying for real SDK client construction — openai import plus httpx/SSL setup — on the gating path) it tries `resolve_vision_provider_client()` and, if that yields no client, retries with `provider="auto"` (main provider → openrouter → nous). Without the auto-fallback step the tool disappeared whenever the explicitly configured provider name was unresolvable (issue #31179). Image loading is handled by `tools/image_source.py`.
- **Inputs / options:** `image_url` (string, REQUIRED) — "Image URL (http/https), local file path, or data: URL to load."; `question` (string, REQUIRED) — "Your question or request about the image."; `region` (array of integer, optional, minItems 4, maxItems 4) — "Optional [x1, y1, x2, y2] crop in ORIGINAL-image pixel coordinates, applied before any downscaling — the crop keeps full resolution. Load the full image first, then re-call with a region to zoom into small text or fine detail."
- **Outputs / side effects:** The image enters the conversation (multimodal envelope) or a text analysis is returned.
- **Config / env:** `auxiliary.vision.provider`; the auto chain main → openrouter → nous.
- **Edge cases / guards:** In `NO_EFFECT_TOOL_NAMES`. The `region` crop is applied BEFORE downscaling, which is what makes zooming into small text actually work.
- **Rebuild notes:** Gate on the same resolution chain the runtime uses, in a probe mode that skips client construction; and expose a pre-downscale crop rather than telling the model to "look closer".

### web_extract  `id: tools.tool-web-extract`
- **Surface:** Tool
- **Where:** Model-callable tool `web_extract`, toolset `web`, emoji 📄, **async handler**, `max_result_size_chars=100_000`, `requires_env=_web_requires_env()`.
- **What it does:** Extracts clean page content (markdown/text, no LLM summarisation) from up to 5 URLs, including PDFs.
- **How it works:** `tools/web_tools.py` (75 KB, 1698 lines), registered `:1684`; the handler hard-slices `args["urls"][:5]` and always passes format `"markdown"`. Gate `check_web_api_key()` (`:1508`): the configured `web.backend` if `_is_backend_available(...)`; else any built-in backend in `_LEGACY_WEB_BACKENDS` with credentials; else a plugin-registered provider that is either keyed-available (`is_available`) or keyless-capable (`is_keyless_available` — the Exa/Parallel anonymous free tiers serve zero-credential installs), with plugin discovery forced first because `check_fn` fires at registration time before any dispatch. Caching lives in `tools/web_result_cache.py`; URL safety in `tools/url_safety.py` (34 KB) and `tools/website_policy.py`.
- **Inputs / options:** `urls` (array of string, REQUIRED, maxItems 5) — "List of URLs to extract content from (max 5 URLs per call)"; `char_limit` (integer, optional, minimum 2000) — "Optional per-page character budget sent back (default 15000). Pages larger than this are head+tail truncated with the full text stored to disk. Raise it when you need more of a long page inline."
- **Outputs / side effects:** Markdown content per URL. Pages within the budget return whole; larger pages return a head+tail window with a footer giving the saved file's path and the `read_file` call to page through the omitted middle. Inline images appear as `[IMAGE: alt]` placeholders; real image URLs are kept as links.
- **Config / env:** `web.backend`; per-backend API keys; the default char budget 15000 (`DEFAULT_EXTRACT_CHAR_LIMIT`, deliberately equal to the browser snapshot threshold).
- **Edge cases / guards:** "If a URL fails or times out, use the browser tool instead." In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`.
- **Rebuild notes:** Head+tail with an on-disk full copy and an explicit "here is the read_file call" footer is strictly better than truncation; capping at 5 URLs per call keeps a single tool result inside the budget.

### web_search  `id: tools.tool-web-search`
- **Surface:** Tool
- **Where:** Model-callable tool `web_search`, toolset `web` (and a member of the `search`, `browser`, and every `hermes-*` toolset), emoji 🔍, `max_result_size_chars=100_000`, `requires_env=_web_requires_env()`.
- **What it does:** Searches the web through the configured backend and returns titles, URLs and descriptions.
- **How it works:** `tools/web_tools.py`, registered `:1674`; handler `web_search_tool(query, limit=args.get("limit", 5))`. Same `check_web_api_key` gate as `web_extract`. The query is passed through to the backend unchanged, so backend-supported operators work.
- **Inputs / options:** `query` (string, REQUIRED) — "The search query to look up on the web. You may include backend-supported operators such as site:example.com, filetype:pdf, intitle:word, -term, or \"exact phrase\"."; `limit` (integer, optional, default `5`, minimum 1, maximum 100) — "Maximum number of results to return. Defaults to 5."
- **Outputs / side effects:** Search results as JSON (`{"data": {"web": [{"url","title","description"}, …]}}` per the `execute_code` stub documentation).
- **Config / env:** `web.backend` and per-backend keys; plugin-registered search providers.
- **Edge cases / guards:** In `IDEMPOTENT_TOOL_NAMES` and `NO_EFFECT_TOOL_NAMES`. It is the one non-browser tool included in the `browser` toolset, "as a fallback for quick lookups".
- **Rebuild notes:** Documenting which operators MAY work (rather than promising them) is the honest framing for a pass-through query.

### x_search  `id: tools.tool-x-search`
- **Surface:** Tool
- **Where:** Model-callable tool `x_search`, toolset `x_search`, emoji 🐦, `requires_env=["XAI_API_KEY"]`, `max_result_size_chars=100_000`. Off by default.
- **What it does:** Searches X (Twitter) posts, profiles and threads through xAI's built-in `x_search` Responses tool — read-only public discovery.
- **How it works:** `tools/x_search_tool.py` (21 KB, 563 lines), handler `_handle_x_search` registered `:554`. Gate `check_x_search_requirements()` (`:155`) calls `resolve_xai_http_credentials()` (which routes through `hermes_cli.auth.resolve_xai_oauth_runtime_credentials` and auto-refreshes an expiring OAuth token) and requires a non-empty `api_key`, so a successful check implies a usable bearer. `_normalize_handles()` strips `@` and whitespace and raises `"<field> supports at most MAX_HANDLES handles"` past the cap (10 per the schema).
- **Inputs / options:** `query` (string, REQUIRED) — "What to look up on X."; `allowed_x_handles` (array of string, optional) — "Optional list of X handles to include exclusively (max 10)."; `excluded_x_handles` (array of string, optional) — "Optional list of X handles to exclude (max 10)."; `from_date` (string, optional) — "Optional start date in YYYY-MM-DD format."; `to_date` (string, optional) — "Optional end date in YYYY-MM-DD format."; `enable_image_understanding` (boolean, optional, default `False`) — "Whether xAI should analyze images attached to matching X posts."; `enable_video_understanding` (boolean, optional, default `False`) — "Whether xAI should analyze videos attached to matching X posts."
- **Outputs / side effects:** Search results from xAI; billable API usage.
- **Config / env:** `XAI_API_KEY` or SuperGrok OAuth credentials; enabled via `hermes tools` → "X (Twitter) Search".
- **Edge cases / guards:** Explicitly read-only: "Do not use it to post, reply, like, DM, upload media, delete, or inspect the user's authenticated X account — those require a separate authenticated X API surface outside this tool." The toolset description points at the `xurl` skill for authenticated reads and account actions.
- **Rebuild notes:** Stating the negative capability list in the description is what stops a model from trying to post through a read-only search tool.

### xai_video_edit  `id: tools.tool-xai-video-edit`
- **Surface:** Tool
- **Where:** Model-callable tool `xai_video_edit`, toolset `video_gen`, emoji literally the string `"video"` (not an emoji character — a registry-data oddity), `requires_env=[]`.
- **What it does:** Edits an existing video with xAI Imagine — a provider-specific workflow deliberately kept out of the unified `video_generate` surface.
- **How it works:** `tools/xai_video_tools.py` (6.3 KB, 209 lines), handler `_handle_xai_video_edit` registered `:189`. Gate `_check_xai_video_requirements()` (`:27`) = `_configured_for_xai_video() and has_xai_video_credentials()`. When the provider is not configured, `_provider_not_configured_error()` returns `{"success": false, "error": "xAI video edit/extend tools require `video_gen.provider` to be configured as `xai` via `hermes tools` -> Video Generation."}`. HTTP through `tools/xai_http.py`.
- **Inputs / options:** `prompt` (string, REQUIRED) — "Instruction for how xAI should modify the source video."; `video_url` (string, REQUIRED) — "Public HTTPS MP4 URL of the source video — the `video` or `public_url` from a prior xAI Imagine result."; `model` (string, optional) — "Optional xAI Imagine model override."
- **Outputs / side effects:** A new video URL/file; billable xAI usage.
- **Config / env:** `video_gen.provider: xai`; xAI credentials.
- **Edge cases / guards:** `video_url` must be a public HTTPS MP4 from a prior Imagine result on files-cdn — arbitrary URLs are not supported. `_clean_string` / `_coerce_int` normalise inputs (a bool is not accepted as an int).
- **Rebuild notes:** Keeping provider-specific verbs as separate, separately-gated tools (instead of stuffing modes into the unified tool) keeps the unified schema portable.

### xai_video_extend  `id: tools.tool-xai-video-extend`
- **Surface:** Tool
- **Where:** Model-callable tool `xai_video_extend`, toolset `video_gen`, emoji `"video"`, `requires_env=[]`.
- **What it does:** Extends an existing xAI Imagine video with additional generated footage.
- **How it works:** `tools/xai_video_tools.py`, handler `_handle_xai_video_extend` registered `:200`; same `_check_xai_video_requirements` gate and same not-configured error.
- **Inputs / options:** `prompt` (string, REQUIRED) — "Instruction for how xAI should continue the source video."; `video_url` (string, REQUIRED) — "Public HTTPS MP4 URL of the source video — the `video` or `public_url` from a prior xAI Imagine result."; `duration` (integer, optional) — "Desired extension duration in seconds. xAI clamps this to its supported range."; `model` (string, optional) — "Optional xAI Imagine model override."
- **Outputs / side effects:** A new, longer video; billable xAI usage.
- **Config / env:** `video_gen.provider: xai`; xAI credentials.
- **Edge cases / guards:** As `xai_video_edit`.
- **Rebuild notes:** n/a — the sibling's notes apply.

### yb_query_group_info  `id: tools.tool-yb-query-group-info`
- **Surface:** Tool
- **Where:** Model-callable tool `yb_query_group_info`, registry toolset `hermes-yuanbao` (module constant `_TOOLSET`), emoji 👥, **async handler**.
- **What it does:** Queries basic info about a Yuanbao group (called "派/Pai" in the app): group name, owner, member count.
- **How it works:** `tools/yuanbao_tools.py` (27 KB, 737 lines), handler `_handle_yb_query_group_info` registered `:502`, `is_async=True`. Gate `_check_yuanbao()` (`:420`): True when `gateway.session_context.get_session_env("HERMES_SESSION_PLATFORM") == "yuanbao"`, else `_get_active_adapter() is not None`.
- **Inputs / options:** `group_code` (string, REQUIRED) — "The unique group identifier (group_code)."
- **Outputs / side effects:** Read-only JSON.
- **Config / env:** Yuanbao gateway adapter credentials; `HERMES_SESSION_PLATFORM`.
- **Edge cases / guards:** Only meaningful inside a Yuanbao gateway session.
- **Registry vs toolsets.py discrepancy:** the tool registers into toolset `hermes-yuanbao`, while `toolsets.py` also defines a separate static `yuanbao` toolset listing the same five `yb_*` tools. `TOOLSETS["yuanbao"]["tools"]` therefore names tools that the registry attributes to `hermes-yuanbao`; only the platform bundle actually resolves them at runtime. `toolsets-reference.md` documents the `yuanbao` toolset name.
- **Rebuild notes:** n/a — thin API mirror.

### yb_query_group_members  `id: tools.tool-yb-query-group-members`
- **Surface:** Tool
- **Where:** Model-callable tool `yb_query_group_members`, registry toolset `hermes-yuanbao`, emoji 📋, async.
- **What it does:** Queries a Yuanbao group's members — find a user by name, list bots (including Yuanbao AI), or list everyone.
- **How it works:** `tools/yuanbao_tools.py`, handler `_handle_yb_query_group_members` registered `:528` (defaults `action` to `list_all`, `name` to `""`, `mention` to False); gate `_check_yuanbao`.
- **Inputs / options:** `group_code` (string, REQUIRED); `action` (string, REQUIRED, enum `find`|`list_bots`|`list_all`) — "find — search a user by name (use when you need to @mention or look up someone); list_bots — list bots and Yuanbao AI assistants; list_all — list all members."; `name` (string, optional) — "User name to search (partial match, case-insensitive). Required for 'find'."; `mention` (boolean, optional) — "Set to true when you need to @mention/at someone in your reply. The response will include the exact @mention format to use."
- **Outputs / side effects:** Read-only JSON; with `mention: true` the response includes the exact @mention string to paste.
- **Config / env:** as above.
- **Edge cases / guards:** "IMPORTANT: You MUST call this tool before @mentioning any user, because you need the exact nickname to construct the @mention format."
- **Rebuild notes:** Returning the ready-to-paste mention token (rather than raw ids) is what stops broken @mentions.

### yb_search_sticker  `id: tools.tool-yb-search-sticker`
- **Surface:** Tool
- **Where:** Model-callable tool `yb_search_sticker`, registry toolset `hermes-yuanbao`, emoji 🔍, async.
- **What it does:** Searches the built-in Yuanbao sticker (TIM face / 表情包) catalogue by keyword.
- **How it works:** `tools/yuanbao_tools.py`, handler `_handle_yb_search_sticker` registered `:654`; gate `_check_yuanbao`.
- **Inputs / options:** `query` (string, optional) — "Search keyword (Chinese or English, e.g. '666', '比心', 'cool', '吃瓜'). Empty string returns the first N stickers."; `limit` (integer, optional) — "Max number of candidates to return (default 10, max 50)."
- **Outputs / side effects:** Read-only list of candidates with `sticker_id`, name and description.
- **Config / env:** as above.
- **Edge cases / guards:** "Sticker = 贴纸 = TIM face — NOT a message reaction." Meant to be called BEFORE `yb_send_sticker` to discover the right id.
- **Rebuild notes:** A discovery tool for an opaque id space is mandatory when the model cannot enumerate it.

### yb_send_dm  `id: tools.tool-yb-send-dm`
- **Surface:** Tool
- **Where:** Model-callable tool `yb_send_dm`, registry toolset `hermes-yuanbao`, emoji ✉️, async.
- **What it does:** Sends a private/direct message to a user in a Yuanbao group, optionally with media attachments.
- **How it works:** `tools/yuanbao_tools.py`, handler `_handle_yb_send_dm` registered `:580`; gate `_check_yuanbao`. `group_code` is resolved from the explicit argument first, then from session context. The tool looks the user up by name in the group member list itself when `user_id` is not given.
- **Inputs / options:** `group_code` (string, optional) — "The group where the target user belongs. Extract from chat_id: 'group:328306697' → '328306697'. Required when user_id is not provided."; `name` (string, optional) — "Target user's display name (partial match, case-insensitive). Required when user_id is not provided."; `message` (string, optional) — "The message text to send as a DM. Can be empty if only sending media."; `user_id` (string, optional) — "Target user's account ID. If provided, skips the member lookup."; `media_files` (array, optional) — items are objects `{path (string, REQUIRED) "Absolute local file path of the media to send.", is_voice (boolean) "Whether this file is a voice message (default false)."}`; "Images (.jpg/.png/.gif/.webp/.bmp) are sent as image messages; other files are sent as document attachments."
- **Outputs / side effects:** A real DM is sent, with optional uploads. `required: []` — nothing is schema-required, so validity is enforced at runtime.
- **Config / env:** as above.
- **Edge cases / guards:** Either `user_id` or (`group_code` + `name`) must be supplied. Note this is the only agent-callable outbound-messaging tool in the built-in set — the toolsets module states that agents otherwise do NOT get a `send_message` tool, because outbound platform messaging happens outside the agent loop.
- **Rebuild notes:** Doing the name→id lookup inside the send tool saves a round trip but makes the failure modes ambiguous; return the resolved identity in the result so the model can verify who it messaged.

### yb_send_sticker  `id: tools.tool-yb-send-sticker`
- **Surface:** Tool
- **Where:** Model-callable tool `yb_send_sticker`, registry toolset `hermes-yuanbao`, emoji 🎨, async.
- **What it does:** Sends a built-in sticker (TIMFaceElem / 贴纸表情) to the current Yuanbao chat.
- **How it works:** `tools/yuanbao_tools.py`, handler `_handle_yb_send_sticker` registered `:691`; gate `_check_yuanbao`.
- **Inputs / options:** `sticker` (string, optional) — "Sticker name (e.g. '六六六', '比心', 'ok') or numeric sticker_id (e.g. '278'). Empty string sends a random built-in sticker."; `chat_id` (string, optional) — "Target chat. Defaults to the current session. Format: 'direct:{account_id}', 'group:{group_code}', or bare account_id."; `reply_to` (string, optional) — "Optional ref_msg_id to quote-reply (group chat only)."
- **Outputs / side effects:** A sticker message is posted.
- **Config / env:** as above.
- **Edge cases / guards:** Strong anti-pattern warning in the description: "DO NOT draw a PNG via execute_code / Pillow / matplotlib and then call send_image_file — that produces a fake 'sticker' image instead of a real TIM face and is the WRONG path."
- **Rebuild notes:** When a model has a plausible-but-wrong path to the same-looking result, naming that path explicitly in the tool description is the cheapest fix.

---

## Part 2 — Toolsets (59 static + 2 registry-only)

All 59 entries of `TOOLSETS` in `toolsets.py`, plus the two toolsets that exist only in the registry
(`browser-cdp`, `browser-use`). "Resolved" counts are live from
`toolsets.resolve_toolset(name)` on this v2026.8.31 install with all 83 built-in tools registered and no
plugins loaded. A user selects toolsets with `hermes chat --toolsets a,b,c`, the `toolsets:` list in
config.yaml, `custom_toolsets:`, the `hermes tools` curses UI, or in-session `/tools enable|disable <name>`.

### Toolset `web`  `id: tools.toolset-web`
- **Surface:** Toolset
- **Where:** `toolsets.py:104`. Selectable as `web`.
- **What it does:** Web research and content extraction.
- **How it works:** Static tools `["web_search", "web_extract"]`, no includes. Resolves to 2 tools. Description: "Web research and content extraction tools".
- **Inputs / options:** n/a (a named bundle).
- **Outputs / side effects:** Adds `web_search` and `web_extract` to the model's schema when their shared `check_web_api_key` gate passes.
- **Config / env:** `web.backend` + per-backend keys decide runtime availability.
- **Edge cases / guards:** Included by `debugging` and `safe`.
- **Rebuild notes:** Search and extract belong together; a separate `search` bundle exists for extract-free deployments.

### Toolset `search`  `id: tools.toolset-search`
- **Surface:** Toolset
- **Where:** `toolsets.py:110`. Selectable as `search`.
- **What it does:** Web search only, without content extraction/scraping.
- **How it works:** Static tools `["web_search"]`, no includes. Resolves to 1 tool. Description: "Web search only (no content extraction/scraping)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds only `web_search`.
- **Config / env:** as `web`.
- **Edge cases / guards:** No registry tools register into `search` directly (it borrows `web_search` from the `web` toolset's registration), so `registry.get_tool_names_for_toolset("search")` is empty and the static list is what resolves.
- **Rebuild notes:** A scraping-free variant is the right lever for policy-constrained deployments.

### Toolset `x_search`  `id: tools.toolset-x-search`
- **Surface:** Toolset
- **Where:** `toolsets.py:116`. Selectable as `x_search`; UI label "X (Twitter) Search" in `hermes tools`.
- **What it does:** Read-only public X (Twitter) discovery via xAI's built-in `x_search` Responses tool.
- **How it works:** Static tools `["x_search"]`. Resolves to 1 tool. Description (verbatim): "Search X (Twitter) posts and threads via xAI's built-in x_search Responses tool. Read-only public X discovery; use the xurl skill for authenticated X API reads and account actions. Available when xAI credentials are configured (SuperGrok OAuth or XAI_API_KEY). Off by default; enable in `hermes tools` → X (Twitter) Search."
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `x_search` when xAI credentials resolve.
- **Config / env:** `XAI_API_KEY` or SuperGrok OAuth.
- **Edge cases / guards:** Off by default — it is not in `_HERMES_CORE_TOOLS`, so no platform bundle carries it.
- **Rebuild notes:** Naming the alternative (the `xurl` skill) inside the toolset description is how you keep a read-only tool from being misread as full account access.

### Toolset `vision`  `id: tools.toolset-vision`
- **Surface:** Toolset
- **Where:** `toolsets.py:130`.
- **What it does:** Image analysis.
- **How it works:** Static tools `["vision_analyze"]`. Resolves to 1. Description: "Image analysis and vision tools".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `vision_analyze`.
- **Config / env:** `auxiliary.vision.provider` + the auto fallback chain.
- **Edge cases / guards:** Included by `safe`; `vision_analyze` is also in `_HERMES_CORE_TOOLS` and the `coding` posture.
- **Rebuild notes:** n/a

### Toolset `video`  `id: tools.toolset-video`
- **Surface:** Toolset
- **Where:** `toolsets.py:136`.
- **What it does:** Video analysis / understanding.
- **How it works:** Static tools `["video_analyze"]`. Resolves to 1. Description: "Video analysis and understanding tools (opt-in, not in default toolset)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `video_analyze`.
- **Config / env:** vision provider chain.
- **Edge cases / guards:** Deliberately NOT in `_HERMES_CORE_TOOLS` — must be added explicitly via `--toolsets`.
- **Rebuild notes:** Opt-in is right for a tool whose per-call cost and latency are an order of magnitude above its neighbours.

### Toolset `image_gen`  `id: tools.toolset-image-gen`
- **Surface:** Toolset
- **Where:** `toolsets.py:142`.
- **What it does:** Text-to-image (and, where supported, image-to-image) generation.
- **How it works:** Static tools `["image_generate"]`. Resolves to 1. Description: "Creative generation tools (images)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `image_generate`.
- **Config / env:** FAL credentials or an explicitly configured plugin image provider.
- **Edge cases / guards:** Included by `safe`; present in `_HERMES_CORE_TOOLS` (so every messaging platform has it) but NOT in the `coding` posture or `hermes-acp`.
- **Rebuild notes:** n/a

### Toolset `video_gen`  `id: tools.toolset-video-gen`
- **Surface:** Toolset
- **Where:** `toolsets.py:148`.
- **What it does:** Video generation, plus provider-specific edit/extend workflows.
- **How it works:** Static tools `["video_generate", "xai_video_edit", "xai_video_extend"]`. Resolves to 3. Description (verbatim): "Video generation tools. Single ``video_generate`` tool covers text-to-video (prompt only) and image-to-video (prompt + image_url), plus reference-to-video. Provider-specific edit/extend workflows may appear as separate tools. Configure via ``hermes tools`` → Video Generation."
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds up to three tools; the two xAI ones only when `video_gen.provider` is `xai` and credentials exist.
- **Config / env:** `video_gen.provider`, `video_gen.model`.
- **Edge cases / guards:** Not in `_HERMES_CORE_TOOLS` — opt-in.
- **Rebuild notes:** One portable tool plus separately-gated provider verbs is the right shape for a heterogeneous backend space.

### Toolset `computer_use`  `id: tools.toolset-computer-use`
- **Surface:** Toolset
- **Where:** `toolsets.py:161`.
- **What it does:** Background desktop control via cua-driver.
- **How it works:** Static tools `["computer_use"]`. Resolves to 1. Description (verbatim): "Background desktop control via cua-driver (macOS/Windows/Linux) — screenshots, mouse, keyboard, scroll, drag. Does NOT steal the user's cursor or keyboard focus. Works with any tool-capable model."
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `computer_use` when the platform is macOS/Windows/Linux and the `cua-driver` binary is available.
- **Config / env:** cua-driver on PATH; approval config.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS` (so every platform bundle lists it) but dropped by `hermes-acp` and `hermes-api-server`.
- **Rebuild notes:** n/a

### Toolset `terminal`  `id: tools.toolset-terminal`
- **Surface:** Toolset
- **Where:** `toolsets.py:170`.
- **What it does:** Shell command execution and background process management.
- **How it works:** Static tools `["terminal", "process"]`. Resolves to 2. Description: "Terminal/command execution and process management tools".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `terminal` and `process`.
- **Config / env:** the terminal environment config (`env_type`: local / docker / singularity / ssh / vercel_sandbox).
- **Edge cases / guards:** `terminal` carries a `check_fn`; `process` does not, so `registry.is_toolset_available("terminal")` is True whenever either tool is exposable (`_toolset_has_exposable_tools`). Also gates the `file` toolset indirectly, since `check_file_requirements()` delegates to `check_terminal_requirements()`.
- **Rebuild notes:** Bundling the process manager with the shell is essential — background execution is useless without it.

### Toolset `skills`  `id: tools.toolset-skills`
- **Surface:** Toolset
- **Where:** `toolsets.py:176`.
- **What it does:** Skill browsing, reading and CRUD.
- **How it works:** Static tools `["skills_list", "skill_view", "skill_manage"]`. Resolves to 3. Description: "Access, create, edit, and manage skill documents with specialized instructions and knowledge".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds three tools; `skills_list` and `skill_view` carry `check_skills_requirements` (always True), `skill_manage` has no check.
- **Config / env:** `<HERMES_HOME>/skills/`, `skills.external_dirs`.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS` and the `coding` posture.
- **Rebuild notes:** Read and write in one toolset is defensible only because skills are the agent's own memory; a stricter build would split `skill_manage` out.

### Toolset `browser`  `id: tools.toolset-browser`
- **Surface:** Toolset
- **Where:** `toolsets.py:182`.
- **What it does:** Browser automation for web interaction.
- **How it works:** Static tools (14, verbatim order): `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`, `browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec`, `web_search`. Resolves to 14. Description: "Browser automation for web interaction (navigate, click, type, scroll, iframes, hold-click) with web search for finding URLs".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds up to 14 tools; each is independently `check_fn`-gated.
- **Config / env:** `browser.backend`, `browser.cloud_provider`, `browser.cdp_url`, `browser.extension_control.enabled`; `BROWSER_CDP_URL`.
- **Edge cases / guards:** The static list spans THREE registry toolsets — `browser` (10 tools), `browser-cdp` (`browser_cdp`, `browser_dialog`), `browser-use` (`browser_exec`) — plus `web` (`web_search`). Disabling the registry toolset `browser` therefore does not remove the CDP or Browser-Use tools; they must be disabled by their own registry toolset names. In Browser-Use CLI mode `check_browser_requirements()` returns False for all ten `browser` tools and `browser_cdp`/`browser_dialog`, leaving only `browser_exec` and `web_search`.
- **Rebuild notes:** Keep the composite user-facing bundle separate from the registry toolsets that gate availability, but make the mismatch visible in the UI — otherwise "disable browser" does not do what the name promises.

### Toolset `browser-cdp` (registry-only)  `id: tools.toolset-browser-cdp`
- **Surface:** Toolset
- **Where:** Not in `TOOLSETS`; created implicitly by `registry.register(..., toolset="browser-cdp")` in `tools/browser_cdp_tool.py:743` and `tools/browser_dialog_tool.py:136`.
- **What it does:** Groups the two CDP-gated browser tools so they appear and disappear together.
- **How it works:** `toolsets.get_toolset("browser-cdp")` falls through the static lookup and, because the name is in `_get_plugin_toolset_names()`, synthesizes `{"description": "Plugin toolset: browser-cdp", "tools": ["browser_cdp", "browser_dialog"], "includes": []}`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Appears in `get_toolset_names()` (61 names vs 59 static) and in `hermes tools`.
- **Config / env:** `browser.cdp_url` / `BROWSER_CDP_URL`.
- **Edge cases / guards:** Its synthesized description literally says "Plugin toolset" even though these are built-ins — a cosmetic bug worth noting.
- **Rebuild notes:** If a registry toolset is a first-class concept, give it a static description; the "Plugin toolset: X" fallback mislabels built-ins.

### Toolset `browser-use` (registry-only)  `id: tools.toolset-browser-use`
- **Surface:** Toolset
- **Where:** Not in `TOOLSETS`; created by `registry.register(..., toolset="browser-use")` in `tools/browser_use_cli.py:1056`.
- **What it does:** Holds the single `browser_exec` tool that replaces the entire built-in browser surface when the Browser Use CLI backend is active.
- **How it works:** Same synthesized-view path as `browser-cdp`; resolves to `["browser_exec"]`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `browser_exec` when `is_browser_use_cli_mode()` is True.
- **Config / env:** `browser.backend` (`""` default → Browser Use when the CLI is runnable; `browser-use`; `off`).
- **Edge cases / guards:** Mutually exclusive in practice with the `browser` registry toolset — the two `check_fn` families invert each other.
- **Rebuild notes:** Two mutually exclusive backends expressed as two toolsets with inverse gates is clean; documenting the exclusivity in both descriptions would be cleaner.

### Toolset `cronjob`  `id: tools.toolset-cronjob`
- **Surface:** Toolset
- **Where:** `toolsets.py:194`.
- **What it does:** Scheduled-task management.
- **How it works:** Static tools `["cronjob"]`. Resolves to 1. Description: "Cronjob management tool - create, list, update, pause, resume, remove, and trigger scheduled tasks".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `cronjob` when one of `HERMES_INTERACTIVE`, `HERMES_GATEWAY_SESSION`, `HERMES_EXEC_ASK` is truthy.
- **Config / env:** those three env vars; the internal JSON scheduler under HERMES_HOME.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS` and in `hermes-api-server`, but not in `hermes-acp` or the `coding` posture.
- **Rebuild notes:** n/a

### Toolset `file`  `id: tools.toolset-file`
- **Surface:** Toolset
- **Where:** `toolsets.py:200`.
- **What it does:** File reading, writing, patching and searching.
- **How it works:** Static tools `["read_file", "write_file", "patch", "search_files"]`. Resolves to 4. Description: "File manipulation tools: read, write, patch (with fuzzy matching), and search (content + files)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds four tools, all gated by `_check_file_reqs` → `check_terminal_requirements()`.
- **Config / env:** the terminal environment config; `tool_output.*`.
- **Edge cases / guards:** Included by `debugging`. All four register `max_result_size_chars=100_000`; `read_file` is additionally pinned to `inf` in `PINNED_THRESHOLDS`.
- **Rebuild notes:** Tying file availability to the terminal backend is what keeps a Docker/SSH/sandbox environment coherent — the files the tools see must be the files the shell sees.

### Toolset `tts`  `id: tools.toolset-tts`
- **Surface:** Toolset
- **Where:** `toolsets.py:206`.
- **What it does:** Text-to-speech audio generation.
- **How it works:** Static tools `["text_to_speech"]`. Resolves to 1. Description: "Text-to-speech: convert text to audio with Edge TTS (free), ElevenLabs, OpenAI, or xAI".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `text_to_speech` when the resolved provider passes its own check.
- **Config / env:** `tts.provider`, `tts.providers.<name>`, per-provider keys.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`; dropped by `hermes-acp`, `hermes-api-server` and the `coding` posture.
- **Rebuild notes:** n/a

### Toolset `todo`  `id: tools.toolset-todo`
- **Surface:** Toolset
- **Where:** `toolsets.py:212`.
- **What it does:** In-session task planning and tracking.
- **How it works:** Static tools `["todo"]`. Resolves to 1. Description: "Task planning and tracking for multi-step work".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `todo` (always available).
- **Config / env:** none.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`, the `coding` posture, `hermes-acp` and `hermes-api-server`.
- **Rebuild notes:** n/a

### Toolset `memory`  `id: tools.toolset-memory`
- **Surface:** Toolset
- **Where:** `toolsets.py:218`.
- **What it does:** Persistent cross-session memory.
- **How it works:** Static tools `["memory"]`. Resolves to 1. Description: "Persistent memory across sessions (personal notes + user profile)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `memory` when at least one built-in store is enabled.
- **Config / env:** `memory.*`.
- **Edge cases / guards:** A source comment records that the former `honcho` toolset was REMOVED — Honcho is now a memory-provider plugin whose tools are injected via `MemoryManager`, not through the toolset system (`toolsets.py:285`). `delegate_task` children cannot call `memory`.
- **Rebuild notes:** Memory providers as plugins that inject tools through a manager, rather than as toolsets, is the cleaner factoring the codebase migrated to.

### Toolset `context_engine`  `id: tools.toolset-context-engine`
- **Surface:** Toolset
- **Where:** `toolsets.py:224`.
- **What it does:** Placeholder bundle for tools an active context-engine plugin exposes at runtime.
- **How it works:** Static tools `[]`, no includes. Resolves to 0 on a stock install. Description: "Runtime tools exposed by the active context engine".
- **Inputs / options:** n/a
- **Outputs / side effects:** Nothing until a plugin registers tools into the `context_engine` toolset, which `get_toolset()`'s registry merge then folds in.
- **Config / env:** the active context-engine plugin.
- **Edge cases / guards:** Empty toolsets are legal; `_toolset_has_exposable_tools` returns False for them, so the toolset reports unavailable.
- **Rebuild notes:** Declaring an empty, named extension point in the static table (rather than letting plugins invent a name) is what makes the toolset selectable before the plugin loads.

### Toolset `session_search`  `id: tools.toolset-session-search`
- **Surface:** Toolset
- **Where:** `toolsets.py:230`.
- **What it does:** Search and recall of past conversations.
- **How it works:** Static tools `["session_search"]`. Resolves to 1. Description: "Search and recall past conversations with summarization".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `session_search` when the SQLite session DB directory exists.
- **Config / env:** the session DB under HERMES_HOME.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`, `coding`, `hermes-acp`, `hermes-api-server`. Note the description says "with summarization" while the tool's own description says "no LLM" — a wording inconsistency.
- **Rebuild notes:** n/a

### Toolset `project`  `id: tools.toolset-project`
- **Surface:** Toolset
- **Where:** `toolsets.py:236`.
- **What it does:** Desktop Projects — create/switch named workspaces.
- **How it works:** Static tools `["desktop_project"]`. Resolves to 1. Description: "Desktop Projects — create/switch named workspaces (GUI sessions only)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `desktop_project`.
- **Config / env:** per-profile `projects.db`.
- **Edge cases / guards:** Deliberately kept OUT of `_HERMES_CORE_TOOLS`; folded in only by the GUI gateway (`tui_gateway/server.py::_load_enabled_toolsets`) for desktop-sourced sessions, because the tools only make sense where a GUI can follow the move.
- **Docs discrepancy:** `toolsets-reference.md` documents this toolset as `project_create`, `project_list`, `project_switch` — three tools that were consolidated into `desktop_project`.
- **Rebuild notes:** Gate GUI-only affordances on the SESSION SOURCE, not on a process env var — a desktop client can be driving a remote backend.

### Toolset `bot_room`  `id: tools.toolset-bot-room`
- **Surface:** Toolset
- **Where:** `toolsets.py:242`.
- **What it does:** Placeholder for verified text-only Group Chat turn capabilities.
- **How it works:** Static tools `[]`, no includes. Resolves to 0. Description: "Verified text-only Group Chat turn capabilities".
- **Inputs / options:** n/a
- **Outputs / side effects:** None on a stock install; the machinery lives in `tools/bot_mode_dm.py`, `tools/bot_mode_probe.py`, `tools/bot_relay.py`, `tools/bot_failure_reasons.py` which register no tools.
- **Config / env:** Group Chat / bot-mode configuration.
- **Edge cases / guards:** Selecting it grants nothing on its own.
- **Rebuild notes:** An empty named toolset used as a capability MARKER (rather than a tool bundle) is a legitimate pattern, but it should be documented as such.

### Toolset `desktop_ui`  `id: tools.toolset-desktop-ui`
- **Surface:** Toolset
- **Where:** `toolsets.py:257`.
- **What it does:** Affordances that exist only because a GUI renderer is on the other end of the connection — in-app terminal/browser panes, pane focus, reactions, tours, tips, MCP consent cards.
- **How it works:** Static tools (11, verbatim order): `read_terminal`, `close_terminal`, `desktop_preview`, `drive_preview`, `annotate_preview`, `read_window_below`, `focus_pane`, `react_to_message`, `setup_mcp`, `tour`, `tip`. Registry merge adds a 12th, `apply_layout`, so `resolve_toolset("desktop_ui")` returns 12. Description: "Desktop GUI affordances — in-app terminal/browser panes, pane focus, reactions (GUI sessions only)". All of these reach the renderer through `tools/desktop_ui.py::emit` (fire-and-forget) or the gateway's blocking-prompt callback (`kw["callback"]`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds up to 12 tools for desktop-sourced sessions only.
- **Config / env:** `HERMES_UI_SESSION_ID` routes events to the owning window; `display.message_reactions` additionally gates `react_to_message`.
- **Edge cases / guards:** Enabled by the GUI gateway for a session whose SOURCE is the desktop app (`tui_gateway/server.py::_load_enabled_toolsets`), explicitly NOT by a process env var — the source comment explains that "was this process spawned by Electron?" is the wrong question and silently strips these tools from every remote gateway. Never present on CLI, TUI, messaging or cron sessions.
- **Docs discrepancy:** `toolsets-reference.md` lists `close_preview`, `open_preview`, `read_preview` (consolidated into `desktop_preview`) and omits `apply_layout`, `desktop_preview`, `setup_mcp`, `tip`.
- **Rebuild notes:** Client-capability toolsets must be keyed on the connection's client identity, not the server process's environment.

### Toolset `clarify`  `id: tools.toolset-clarify`
- **Surface:** Toolset
- **Where:** `toolsets.py:268`.
- **What it does:** Asking the user clarifying questions.
- **How it works:** Static tools `["clarify"]`. Resolves to 1. Description: "Ask the user clarifying questions (multiple-choice or open-ended)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `clarify` (always available at the registry level; the surface that renders the form is platform-specific).
- **Config / env:** none.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`, the `coding` posture and `hermes-webhook`; dropped by `hermes-acp` and `hermes-api-server` (no interactive UI). `delegate_task` children cannot call it.
- **Rebuild notes:** n/a

### Toolset `code_execution`  `id: tools.toolset-code-execution`
- **Surface:** Toolset
- **Where:** `toolsets.py:274`.
- **What it does:** Running Python that calls Hermes tools programmatically.
- **How it works:** Static tools `["execute_code"]`. Resolves to 1. Description: "Run Python scripts that call tools programmatically (reduces LLM round trips)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `execute_code` on POSIX hosts with a satisfied sandbox config.
- **Config / env:** the terminal `env_type` (Vercel sandbox has its own requirements check).
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`, `coding`, `hermes-acp`, `hermes-api-server`.
- **Rebuild notes:** n/a

### Toolset `delegation`  `id: tools.toolset-delegation`
- **Surface:** Toolset
- **Where:** `toolsets.py:280`.
- **What it does:** Spawning subagents with isolated context.
- **How it works:** Static tools `["delegate_task"]`. Resolves to 1. Description: "Spawn subagents with isolated context for complex subtasks".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `delegate_task` (always available).
- **Config / env:** `delegation.max_concurrent_children`, `delegation.max_spawn_depth`, `delegation.orchestrator_enabled`.
- **Edge cases / guards:** In `_HERMES_CORE_TOOLS`, `coding`, `hermes-acp`, `hermes-api-server`. Children may not re-delegate unless nesting is enabled and depth remains.
- **Rebuild notes:** n/a

### Toolset `homeassistant`  `id: tools.toolset-homeassistant`
- **Surface:** Toolset
- **Where:** `toolsets.py:290`.
- **What it does:** Home Assistant smart-home control and monitoring.
- **How it works:** Static tools `["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"]`. Resolves to 4. Description: "Home Assistant smart home control and monitoring".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds four tools when `HASS_TOKEN` is set.
- **Config / env:** `HASS_TOKEN`, `HASS_URL`.
- **Edge cases / guards:** All four are in `_HERMES_CORE_TOOLS`; `hermes-cron`'s comment names `homeassistant` (with `moa`) as a `_DEFAULT_OFF_TOOLSET` excluded by `_get_platform_tools()` unless the user explicitly enables it.
- **Rebuild notes:** Credential-gated toolsets should stay in the core list but off by default — that way `hermes tools` can show them as "configure me" rather than hiding them.

### Toolset `kanban`  `id: tools.toolset-kanban`
- **Surface:** Toolset
- **Where:** `toolsets.py:296`.
- **What it does:** Multi-agent coordination through a shared kanban board.
- **How it works:** Static tools (14, verbatim order): `kanban_show`, `kanban_list`, `kanban_complete`, `kanban_block`, `kanban_request_review`, `kanban_request_changes`, `kanban_heartbeat`, `kanban_comment`, `kanban_create`, `kanban_link`, `kanban_unblock`, `kanban_attach`, `kanban_attach_url`, `kanban_attachments`. Resolves to 14. Description (verbatim): "Kanban multi-agent coordination — only active when the agent is spawned by the kanban dispatcher (HERMES_KANBAN_TASK env set). The dispatcher runs inside the gateway by default; see `kanban.dispatch_in_gateway` in config.yaml. Lets workers mark tasks done with structured handoffs, enter first-class review (request_review — not a block), return review changes, block for human input, heartbeat during long ops, comment on threads, attach files, and (for orchestrators) list, unblock, and fan out tasks."
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds up to 14 tools; 12 gated by `_check_kanban_mode`, `kanban_list` and `kanban_unblock` by `_check_kanban_orchestrator_mode`.
- **Config / env:** `toolsets:` must literally contain `kanban`; `kanban.dispatch_in_gateway`; `HERMES_KANBAN_TASK`, `HERMES_KANBAN_DB`, `HERMES_KANBAN_BOARD`, `HERMES_TENANT`.
- **Edge cases / guards:** Workflow-gated: `all`/`*` does NOT enable it. `delegate_task` children have it stripped from their schema and runtime-rejected even with inherited `HERMES_KANBAN_*` env vars.
- **Rebuild notes:** Some toolsets need an opt-in that a wildcard cannot satisfy; encoding that as a separate "workflow-gated" class (distinct from capability-gated) is the honest way to express it.

### Toolset `discord`  `id: tools.toolset-discord`
- **Surface:** Toolset
- **Where:** `toolsets.py:318`.
- **What it does:** Discord read-and-participate actions.
- **How it works:** Static tools `["discord"]`. Resolves to 1. Description: "Discord read and participate tools (fetch messages, search members, create threads)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `discord` when `DISCORD_BOT_TOKEN` is set.
- **Config / env:** `DISCORD_BOT_TOKEN`.
- **Edge cases / guards:** Platform-restricted by `hermes_cli/toolset_scope.py`: `_TOOLSET_PLATFORM_RESTRICTIONS["discord"] = {"discord"}` — available only on the discord platform. Folded into `hermes-discord`.
- **Rebuild notes:** n/a

### Toolset `discord_admin`  `id: tools.toolset-discord-admin`
- **Surface:** Toolset
- **Where:** `toolsets.py:324`.
- **What it does:** Discord server management (moderation).
- **How it works:** Static tools `["discord_admin"]`. Resolves to 1. Description: "Discord server management (list channels/roles, pin messages, assign roles)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `discord_admin` when `DISCORD_BOT_TOKEN` is set.
- **Config / env:** `DISCORD_BOT_TOKEN`; the bot's per-guild Discord permissions.
- **Edge cases / guards:** Platform-restricted to `discord` by `_TOOLSET_PLATFORM_RESTRICTIONS`. Folded into `hermes-discord`.
- **Rebuild notes:** Separating moderation from participation into two toolsets is what allows a read-only Discord deployment.

### Toolset `yuanbao`  `id: tools.toolset-yuanbao`
- **Surface:** Toolset
- **Where:** `toolsets.py:330`.
- **What it does:** Yuanbao platform actions — group info, member queries, DM, stickers.
- **How it works:** Static tools `["yb_query_group_info", "yb_query_group_members", "yb_send_dm", "yb_search_sticker", "yb_send_sticker"]`. Resolves to 5. Description: "Yuanbao platform tools - group info, member queries, DM, stickers".
- **Inputs / options:** n/a
- **Outputs / side effects:** Names five tools.
- **Config / env:** the Yuanbao gateway adapter; `HERMES_SESSION_PLATFORM`.
- **Edge cases / guards:** **Registry mismatch:** the five tools actually register under toolset `hermes-yuanbao` (module constant `_TOOLSET` in `tools/yuanbao_tools.py`), so `registry.get_tool_names_for_toolset("yuanbao")` is empty and `hermes tools` gating on the registry toolset name will not match this static bundle. Selecting `yuanbao` still resolves the five names statically, but the availability check `is_toolset_available("yuanbao")` sees no entries.
- **Rebuild notes:** A static toolset and the registry toolset its tools register into must share one name, or availability and selection disagree.

### Toolset `feishu_doc`  `id: tools.toolset-feishu-doc`
- **Surface:** Toolset
- **Where:** `toolsets.py:342`.
- **What it does:** Reading Feishu/Lark document content.
- **How it works:** Static tools `["feishu_doc_read"]`. Resolves to 1. Description: "Read Feishu/Lark document content".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds `feishu_doc_read` when `lark_oapi` is importable.
- **Config / env:** `lark_oapi` package; Feishu tenant credentials at the gateway.
- **Edge cases / guards:** Folded into `hermes-feishu`; used by the document-comment intelligent-reply handler, not the regular chat adapter.
- **Rebuild notes:** n/a

### Toolset `feishu_drive`  `id: tools.toolset-feishu-drive`
- **Surface:** Toolset
- **Where:** `toolsets.py:348`.
- **What it does:** Feishu/Lark document comment operations.
- **How it works:** Static tools `["feishu_drive_list_comments", "feishu_drive_list_comment_replies", "feishu_drive_reply_comment", "feishu_drive_add_comment"]`. Resolves to 4. Description: "Feishu/Lark document comment operations (list, reply, add)".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds four tools when `lark_oapi` is importable.
- **Config / env:** as `feishu_doc`.
- **Edge cases / guards:** Scoped to the comment agent; not exposed on `hermes-cli` or other messaging toolsets except through `hermes-feishu`.
- **Rebuild notes:** n/a

### Toolset `spotify`  `id: tools.toolset-spotify`
- **Surface:** Toolset
- **Where:** `toolsets.py:357`.
- **What it does:** Native Spotify playback, search, playlist, album and library control.
- **How it works:** Static tools `["spotify_playback", "spotify_devices", "spotify_queue", "spotify_search", "spotify_playlists", "spotify_albums", "spotify_library"]`. Resolves to 7 names. Description: "Native Spotify playback, search, playlist, album, and library tools".
- **Inputs / options:** n/a
- **Outputs / side effects:** Names seven tools.
- **Config / env:** Spotify OAuth credentials held by the bundled `spotify` plugin.
- **Edge cases / guards:** **No tool in the built-in registry registers into `spotify`** on this install — the seven tools are registered by the bundled `spotify` plugin at load time (`toolsets-reference.md`: "Registered by the bundled `spotify` plugin"). With no plugins loaded, `is_toolset_available("spotify")` is False and the seven names resolve to nothing at dispatch. These seven tools are consequently NOT part of the 83-tool built-in registry and have no per-tool entry in Part 1.
- **Rebuild notes:** Declaring a plugin's toolset statically (so it is selectable before the plugin loads) is useful, but the UI must distinguish "declared but unloaded" from "available".

### Toolset `debugging`  `id: tools.toolset-debugging`
- **Surface:** Toolset
- **Where:** `toolsets.py:365`. COMPOSITE.
- **What it does:** Debugging/troubleshooting bundle.
- **How it works:** Static tools `["terminal", "process"]` plus `includes: ["web", "file"]`. Resolves to 8: `terminal`, `process`, `web_search`, `web_extract`, `read_file`, `write_file`, `patch`, `search_files`. Description: "Debugging and troubleshooting toolkit".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds the union of those bundles.
- **Config / env:** inherits the constituent toolsets' gates.
- **Edge cases / guards:** `resolve_toolset` shares one `visited` set across sibling includes, so diamond dependencies resolve once and cycles return `[]` silently.
- **Rebuild notes:** n/a

### Toolset `safe`  `id: tools.toolset-safe`
- **Surface:** Toolset
- **Where:** `toolsets.py:371`. COMPOSITE.
- **What it does:** Read-only research plus media generation, with no terminal, no file writes and no code execution.
- **How it works:** Static tools `[]` plus `includes: ["web", "vision", "image_gen"]`. Resolves to 4: `web_search`, `web_extract`, `vision_analyze`, `image_generate`. Description: "Safe toolkit without terminal access".
- **Inputs / options:** n/a
- **Outputs / side effects:** Adds four tools.
- **Config / env:** inherits.
- **Edge cases / guards:** `image_generate` costs money, so "safe" means "cannot touch the host", not "free".
- **Rebuild notes:** A composite that is defined only by its includes documents intent better than a flat list.

### Toolset `coding`  `id: tools.toolset-coding`
- **Surface:** Toolset
- **Where:** `toolsets.py:383`. POSTURE toolset (`"posture": True`).
- **What it does:** The coding posture for base Hermes (CLI/TUI/desktop/ACP) — everything you reach for while pairing on code, and nothing else.
- **How it works:** Static tools (31, verbatim order): `web_search`, `web_extract`, `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `vision_analyze`, `skills_list`, `skill_view`, `skill_manage`, `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`, `browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec`, `todo`, `memory`, `session_search`, `clarify`, `execute_code`, `delegate_task`. Resolves to 31. Description: "Coding-focused toolset: files, terminal, search, web docs, skills, todo, delegate, vision, browser". Auto-selected in a code workspace by `agent/coding_context.py`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Drops messaging, tts, image_gen, spotify, home-assistant, cron and computer-use relative to `hermes-cli`.
- **Config / env:** selected per session by `agent/coding_context.py`.
- **Edge cases / guards:** `"posture": True` marks it as never auto-recovered into per-platform tool config (see the non-configurable-toolset recovery loop in `hermes_cli/tools_config.py`). The GUI pane/browser affordances are deliberately absent: they belong to the client surface, so the GUI gateway folds `desktop_ui` in alongside this posture for desktop-sourced sessions.
- **Rebuild notes:** Distinguishing a *posture* (chosen per session by context) from a *platform bundle* (persisted per platform) prevents the auto-selected set from silently becoming the user's saved configuration.

### `_HERMES_CORE_TOOLS` — the shared platform tool list  `id: tools.toolset-core-list`
- **Surface:** Core
- **Where:** `toolsets.py:31`. Not selectable by name; it is the Python list every `hermes-*` platform bundle is built from.
- **What it does:** Defines, once, the 53 tools every CLI and messaging-platform toolset shares, so editing one list updates all platforms simultaneously.
- **How it works:** The list, in source order and with the source's own grouping comments: Web — `web_search`, `web_extract`; Terminal + process management — `terminal`, `process`; File manipulation — `read_file`, `write_file`, `patch`, `search_files`; Vision + image generation — `vision_analyze`, `image_generate`; Skills — `skills_list`, `skill_view`, `skill_manage`; Browser automation — `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`, `browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec` ("replaces other tools when browser.backend is 'browser-use'"); Text-to-speech — `text_to_speech`; Planning & memory — `todo`, `memory`; Session history search — `session_search`; Clarifying questions — `clarify`; Code execution + delegation — `execute_code`, `delegate_task`; Cronjob management — `cronjob`; Home Assistant — `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`; Kanban — `kanban_show`, `kanban_list`, `kanban_complete`, `kanban_block`, `kanban_request_review`, `kanban_request_changes`, `kanban_heartbeat`, `kanban_comment`, `kanban_create`, `kanban_link`, `kanban_unblock`, `kanban_attach`, `kanban_attach_url`, `kanban_attachments`; Computer use — `computer_use`. Total 53.
- **Inputs / options:** n/a
- **Outputs / side effects:** Every bundle that uses it resolves to 53 tools plus its own extras.
- **Config / env:** n/a
- **Edge cases / guards:** Three families are deliberately EXCLUDED with in-source rationale: the desktop GUI affordances (`desktop_ui`) and the Project tools (`project`), because "they only work where a GUI renderer can answer them" and are enabled solely by the GUI gateway for desktop-sourced sessions; and an agent-callable `send_message`, because "outbound platform messaging is handled outside the agent loop (cron delivery, the gateway kanban notifier, and the `hermes send` CLI), not by the model deciding to send on its own". `bundle_non_core_tools(name)` (`toolsets.py:704`) exists so that disabling a `hermes-*` bundle subtracts only its non-core delta — subtracting the whole bundle would strip terminal/read_file/… shared by every other enabled toolset and empty the model's tool list (#33924).
- **Rebuild notes:** One shared constant plus a "non-core delta" subtraction routine is the minimum needed to make per-platform bundles disable-able without cross-damage.

### Toolset `hermes-acp`  `id: tools.toolset-hermes-acp`
- **Surface:** Toolset
- **Where:** `toolsets.py:416`. Platform bundle for editor integrations.
- **What it does:** Coding-focused tools for VS Code / Zed / JetBrains, without messaging, audio or interactive-UI tools.
- **How it works:** An explicit 30-tool list (NOT `_HERMES_CORE_TOOLS`): `web_search`, `web_extract`, `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `vision_analyze`, `skills_list`, `skill_view`, `skill_manage`, `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`, `browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec`, `todo`, `memory`, `session_search`, `execute_code`, `delegate_task`. Resolves to 30. Description: "Editor integration (VS Code, Zed, JetBrains) — coding-focused tools without messaging, audio, or clarify UI".
- **Inputs / options:** n/a
- **Outputs / side effects:** 30 tools.
- **Config / env:** the ACP surface.
- **Edge cases / guards:** Relative to `hermes-cli` it drops `clarify`, `cronjob`, `image_generate`, `text_to_speech`, `computer_use`, all four Home Assistant tools and all fourteen kanban tools. Compared with the `coding` posture it additionally drops `clarify`.
- **Rebuild notes:** n/a

### Toolset `hermes-api-server`  `id: tools.toolset-hermes-api-server`
- **Surface:** Toolset
- **Where:** `toolsets.py:437`. Platform bundle for the OpenAI-compatible HTTP API server.
- **What it does:** Full agent tools over HTTP, minus anything requiring interactive UI.
- **How it works:** An explicit 36-tool list: the 30 of `hermes-acp` plus `image_generate`, `cronjob`, `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`. Resolves to 36. Description: "OpenAI-compatible API server — full agent tools accessible via HTTP (no interactive UI tools like clarify or send_message)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 36 tools.
- **Config / env:** the API-server platform.
- **Edge cases / guards:** Drops `clarify`, `text_to_speech`, `computer_use` and the kanban tools relative to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-cli`  `id: tools.toolset-hermes-cli`
- **Surface:** Toolset
- **Where:** `toolsets.py:479`. The default for interactive CLI sessions.
- **What it does:** The full interactive CLI toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS` exactly. Resolves to 53. Description: "Full interactive CLI toolset - all default tools plus cronjob management".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools, each independently `check_fn`-gated at runtime.
- **Config / env:** `toolsets: [hermes-cli]` in config.yaml.
- **Edge cases / guards:** GUI affordances (`desktop_ui`) and Projects (`project`) are added on top by the GUI gateway for desktop sessions; `coding` may replace this posture in a code workspace.
- **Rebuild notes:** n/a

### Toolset `hermes-cron`  `id: tools.toolset-hermes-cron`
- **Surface:** Toolset
- **Where:** `toolsets.py:485`. Default toolset for cron-fired sessions.
- **What it does:** The cron scheduler's default agent toolset, mirroring `hermes-cli`.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Default cron toolset - same core tools as hermes-cli; gated by `hermes tools`".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools before per-platform filtering.
- **Config / env:** filtered down by `hermes tools` per platform; `_DEFAULT_OFF_TOOLSETS` (named in the source comment as `moa`, `homeassistant`) are excluded by `_get_platform_tools()` unless explicitly enabled.
- **Edge cases / guards:** A cron job can further restrict itself with the `cronjob` tool's `enabled_toolsets` argument.
- **Rebuild notes:** n/a

### Toolset `hermes-telegram`  `id: tools.toolset-hermes-telegram`
- **Surface:** Toolset
- **Where:** `toolsets.py:493`.
- **What it does:** Telegram bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Telegram bot toolset - full access for personal use (terminal has safety checks)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Telegram gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`; the "safety checks" referred to are the `terminal` tool's dangerous-command approval.
- **Rebuild notes:** n/a

### Toolset `hermes-discord`  `id: tools.toolset-hermes-discord`
- **Surface:** Toolset
- **Where:** `toolsets.py:498`.
- **What it does:** Discord bot toolset.
- **How it works:** `_HERMES_CORE_TOOLS + ["discord", "discord_admin"]`. Resolves to 55. Description: "Discord bot toolset - full access (terminal has safety checks via dangerous command approval)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 55 tools.
- **Config / env:** `DISCORD_BOT_TOKEN`.
- **Edge cases / guards:** The only bundle whose extras are platform-restricted by `hermes_cli/toolset_scope.py`.
- **Rebuild notes:** n/a

### Toolset `hermes-whatsapp`  `id: tools.toolset-hermes-whatsapp`
- **Surface:** Toolset
- **Where:** `toolsets.py:507`.
- **What it does:** WhatsApp bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "WhatsApp bot toolset - similar to Telegram (personal messaging, more trusted)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** WhatsApp gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-slack`  `id: tools.toolset-hermes-slack`
- **Surface:** Toolset
- **Where:** `toolsets.py:512`.
- **What it does:** Slack bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Slack bot toolset - full access for workspace use (terminal has safety checks)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Slack gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-signal`  `id: tools.toolset-hermes-signal`
- **Surface:** Toolset
- **Where:** `toolsets.py:522`.
- **What it does:** Signal bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Signal bot toolset - encrypted messaging platform (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Signal gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-bluebubbles`  `id: tools.toolset-hermes-bluebubbles`
- **Surface:** Toolset
- **Where:** `toolsets.py:528`.
- **What it does:** BlueBubbles iMessage bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "BlueBubbles iMessage bot toolset - Apple iMessage via local BlueBubbles server".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** BlueBubbles server config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-homeassistant`  `id: tools.toolset-hermes-homeassistant`
- **Surface:** Toolset
- **Where:** `toolsets.py:534`.
- **What it does:** Home Assistant bot toolset — smart-home event monitoring and control.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Home Assistant bot toolset - smart home event monitoring and control".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** `HASS_TOKEN`, `HASS_URL`.
- **Edge cases / guards:** Identical to `hermes-cli` — the four HA tools are already in the core list and activate when `HASS_TOKEN` is set.
- **Rebuild notes:** n/a

### Toolset `hermes-email`  `id: tools.toolset-hermes-email`
- **Surface:** Toolset
- **Where:** `toolsets.py:540`.
- **What it does:** Email bot toolset (IMAP/SMTP).
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Email bot toolset - interact with Hermes via email (IMAP/SMTP)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** email gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-mattermost`  `id: tools.toolset-hermes-mattermost`
- **Surface:** Toolset
- **Where:** `toolsets.py:546`.
- **What it does:** Mattermost bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Mattermost bot toolset - self-hosted team messaging (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Mattermost gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-matrix`  `id: tools.toolset-hermes-matrix`
- **Surface:** Toolset
- **Where:** `toolsets.py:552`.
- **What it does:** Matrix bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Matrix bot toolset - decentralized encrypted messaging (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Matrix gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-dingtalk`  `id: tools.toolset-hermes-dingtalk`
- **Surface:** Toolset
- **Where:** `toolsets.py:558`.
- **What it does:** DingTalk bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "DingTalk bot toolset - enterprise messaging platform (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** DingTalk gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-feishu`  `id: tools.toolset-hermes-feishu`
- **Surface:** Toolset
- **Where:** `toolsets.py:564`.
- **What it does:** Feishu/Lark bot toolset.
- **How it works:** `_HERMES_CORE_TOOLS + ["feishu_doc_read", "feishu_drive_list_comments", "feishu_drive_list_comment_replies", "feishu_drive_reply_comment", "feishu_drive_add_comment"]`. Resolves to 58. Description: "Feishu/Lark bot toolset - enterprise messaging via Feishu/Lark (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 58 tools.
- **Config / env:** Feishu tenant credentials; `lark_oapi`.
- **Edge cases / guards:** The five extras are only used by the document-comment handler, not the regular chat adapter.
- **Rebuild notes:** n/a

### Toolset `hermes-weixin`  `id: tools.toolset-hermes-weixin`
- **Surface:** Toolset
- **Where:** `toolsets.py:576`.
- **What it does:** Weixin (personal WeChat via iLink) bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "Weixin bot toolset - personal WeChat messaging via iLink (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** iLink gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-qqbot`  `id: tools.toolset-hermes-qqbot`
- **Surface:** Toolset
- **Where:** `toolsets.py:582`.
- **What it does:** QQ bot toolset (Official Bot API v2).
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "QQBot toolset - QQ messaging via Official Bot API v2 (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** QQBot gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-wecom`  `id: tools.toolset-hermes-wecom`
- **Surface:** Toolset
- **Where:** `toolsets.py:588`.
- **What it does:** WeCom (enterprise WeChat) bot toolset.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "WeCom bot toolset - enterprise WeChat messaging (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** WeCom gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-wecom-callback`  `id: tools.toolset-hermes-wecom-callback`
- **Surface:** Toolset
- **Where:** `toolsets.py:594`.
- **What it does:** WeCom callback toolset for enterprise self-built apps.
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "WeCom callback toolset - enterprise self-built app messaging (full access)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** WeCom callback gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-yuanbao`  `id: tools.toolset-hermes-yuanbao`
- **Surface:** Toolset
- **Where:** `toolsets.py:600`. The only bundle carrying a `"module"` key.
- **What it does:** Yuanbao bot toolset.
- **How it works:** `_HERMES_CORE_TOOLS + ["yb_query_group_info", "yb_query_group_members", "yb_send_dm", "yb_search_sticker", "yb_send_sticker"]`, plus `"module": "tools.yuanbao_tools"`. Resolves to 58. Description (verbatim, mixed-language): "Yuanbao Bot 元宝消息平台工具集 - 群信息、成员查询、私聊、贴纸表情".
- **Inputs / options:** n/a
- **Outputs / side effects:** 58 tools.
- **Config / env:** Yuanbao gateway adapter; `HERMES_SESSION_PLATFORM=yuanbao`.
- **Edge cases / guards:** This is also the REGISTRY toolset the five `yb_*` tools register into, which is why they resolve here but not under the static `yuanbao` toolset. The `"module"` key is unique in `TOOLSETS` and is not read by `get_toolset`/`resolve_toolset`.
- **Rebuild notes:** Registering platform-specific tools directly into the platform bundle's registry name (rather than a separate feature toolset) is the pattern that actually works — the `yuanbao` static toolset is the vestige.

### Toolset `hermes-sms`  `id: tools.toolset-hermes-sms`
- **Surface:** Toolset
- **Where:** `toolsets.py:615`.
- **What it does:** SMS bot toolset (Twilio).
- **How it works:** `tools = _HERMES_CORE_TOOLS`. Resolves to 53. Description: "SMS bot toolset - interact with Hermes via SMS (Twilio)".
- **Inputs / options:** n/a
- **Outputs / side effects:** 53 tools.
- **Config / env:** Twilio gateway config.
- **Edge cases / guards:** Identical to `hermes-cli`.
- **Rebuild notes:** n/a

### Toolset `hermes-webhook`  `id: tools.toolset-hermes-webhook`
- **Surface:** Toolset
- **Where:** `toolsets.py:620`; the tool list is `_HERMES_WEBHOOK_SAFE_TOOLS` at `toolsets.py:92`.
- **What it does:** The deliberately constrained toolset for webhook-triggered runs.
- **How it works:** `tools = _HERMES_WEBHOOK_SAFE_TOOLS = ["web_search", "web_extract", "vision_analyze", "clarify"]`. Resolves to 4. Description: "Webhook toolset - receive and process external webhook events".
- **Inputs / options:** n/a
- **Outputs / side effects:** 4 tools; no terminal, file, browser, code-execution or delegation access.
- **Config / env:** webhook gateway config.
- **Edge cases / guards:** The source rationale (`toolsets.py:88`) is explicit: "Webhook events may originate from untrusted third-party content (for example, public PR titles/comments). Keep the default webhook toolset intentionally constrained to avoid local file/system execution by prompt injection."
- **Rebuild notes:** Tie the tool surface to the trust level of the INPUT, not to the deployment. This four-tool list is the model of a prompt-injection-resistant default.

### Toolset `hermes-gateway`  `id: tools.toolset-hermes-gateway`
- **Surface:** Toolset
- **Where:** `toolsets.py:625`. COMPOSITE — the only bundle that includes other bundles.
- **What it does:** The internal gateway orchestrator toolset — the union of every messaging platform's tools, for when the gateway must accept any message source.
- **How it works:** Static tools `[]` plus `includes` (19, verbatim order): `hermes-telegram`, `hermes-discord`, `hermes-whatsapp`, `hermes-slack`, `hermes-signal`, `hermes-bluebubbles`, `hermes-homeassistant`, `hermes-email`, `hermes-sms`, `hermes-mattermost`, `hermes-matrix`, `hermes-dingtalk`, `hermes-feishu`, `hermes-wecom`, `hermes-wecom-callback`, `hermes-weixin`, `hermes-qqbot`, `hermes-webhook`, `hermes-yuanbao`. Resolves to 65 = the 53 core + `discord` + `discord_admin` + 5 feishu + 5 yuanbao. Description: "Gateway toolset - union of all messaging platform tools".
- **Inputs / options:** n/a
- **Outputs / side effects:** 65 tools.
- **Config / env:** gateway config.
- **Edge cases / guards:** Bundle nesting is one level deep in practice — only `hermes-gateway` includes other bundles and those leaves do not nest further, which is why `bundle_non_core_tools` does a single `includes` pass. `hermes-acp`, `hermes-api-server`, `hermes-cli` and `hermes-cron` are NOT included.
- **Rebuild notes:** A union bundle is fine as long as the composition depth stays bounded and every subtraction path knows the bound.

---

## Part 3 — Cross-check against the shipped docs

`website/docs/reference/tools-reference.md` (375 lines) and
`website/docs/reference/toolsets-reference.md` (170 lines) are the shipped documentation for this
surface. Both are partly stale against the v2026.8.31 registry. Every divergence found:

### Doc discrepancy: `project` toolset lists three removed tools  `id: tools.docdiff-project-tools`
- **Surface:** Docs
- **Where:** `website/docs/reference/tools-reference.md:152-162` and `toolsets-reference.md` "Core Toolsets" table row `project`.
- **What it does:** Documents `project_create`, `project_list`, `project_switch` as three separate tools.
- **How it works:** They were consolidated into the single `desktop_project` tool with an `action` enum (`tools/project_tools.py:157`, issue #95681, "244 -> ~145 tok").
- **Inputs / options:** n/a
- **Outputs / side effects:** A reader following the docs will call tools that do not exist.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Generate the tool table from the registry rather than hand-maintaining it.

### Doc discrepancy: `desktop_ui` table lists removed tools and omits four live ones  `id: tools.docdiff-desktop-ui-tools`
- **Surface:** Docs
- **Where:** `tools-reference.md:189-209` and the `desktop_ui` row of `toolsets-reference.md`.
- **What it does:** Lists `open_preview`, `close_preview`, `read_preview` (all consolidated into `desktop_preview`; their modules carry the comment "Registration removed: consolidated into the `preview` tool (#95681)").
- **How it works:** The live `desktop_ui` registry toolset contains `read_terminal`, `close_terminal`, `desktop_preview`, `drive_preview`, `annotate_preview`, `read_window_below`, `focus_pane`, `react_to_message`, `setup_mcp`, `tour`, `tip`, `apply_layout`. Missing from the docs: `desktop_preview`, `setup_mcp`, `apply_layout` (and `tip` is in `tools-reference.md` but not in the `toolsets-reference.md` row).
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** As above.

### Doc discrepancy: `browser_cdp` / `browser_dialog` toolset attribution  `id: tools.docdiff-browser-cdp-toolset`
- **Surface:** Docs
- **Where:** `tools-reference.md:32-40` — "These two tools live in the `browser` toolset".
- **What it does:** Claims both tools are in the `browser` registry toolset.
- **How it works:** They register into the registry toolset `browser-cdp` (`tools/browser_cdp_tool.py:744`, `tools/browser_dialog_tool.py:137`). They are only in the *static composite* `TOOLSETS["browser"]` list. The distinction matters because `hermes tools` and `is_toolset_available()` operate on registry toolset names.
- **Inputs / options:** n/a
- **Outputs / side effects:** Disabling the `browser` registry toolset does not remove them.
- **Config / env:** n/a
- **Edge cases / guards:** The docs also say CDP availability includes "Camofox"; the live `_browser_cdp_check` and the tool description both state Camofox is REST-only and will never support CDP.
- **Rebuild notes:** n/a

### Doc discrepancy: `browser_exec` missing from the browser table  `id: tools.docdiff-browser-exec-missing`
- **Surface:** Docs
- **Where:** `tools-reference.md:17-31` (`browser` toolset table).
- **What it does:** The table lists 10 tools and omits `browser_exec` entirely, even though `TOOLSETS["browser"]` includes it and the Browser-Use CLI backend is the DEFAULT when the CLI is runnable.
- **How it works:** `browser_exec` registers into the `browser-use` registry toolset (`tools/browser_use_cli.py:1056`).
- **Inputs / options:** n/a
- **Outputs / side effects:** The docs describe the non-default browser stack as if it were the only one.
- **Config / env:** `browser.backend`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Doc discrepancy: `discord` / `discord_admin` action lists  `id: tools.docdiff-discord-actions`
- **Surface:** Docs
- **Where:** `tools-reference.md:333-348`.
- **What it does:** Documents `discord` actions "`search_members`, `fetch_messages`, `send_message`, `react`, `fetch_channel`, `list_channels`, and more", and `discord_admin` as able to "create/edit/delete channels, manage role grants, timeouts, kicks, and bans".
- **How it works:** The live `discord` schema enum is exactly `["search_members", "fetch_messages", "create_thread"]`; the live `discord_admin` enum is exactly `["list_guilds", "server_info", "list_channels", "channel_info", "list_roles", "member_info", "list_pins", "pin_message", "unpin_message", "delete_message", "add_role", "remove_role"]` — no channel creation, no timeouts, kicks or bans.
- **Inputs / options:** n/a
- **Outputs / side effects:** The docs overstate the moderation surface.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Doc discrepancy: `terminal` parameter named `notify_on_complete`  `id: tools.docdiff-terminal-notify`
- **Surface:** Docs
- **Where:** `tools-reference.md:182-188` (`terminal` toolset table).
- **What it does:** Documents "Set `notify_on_complete=true` (with `background=true`)".
- **How it works:** The live parameter is `notify` (untyped in the schema), accepting `true` or a list of patterns. There is no `notify_on_complete` field. The doc row also says "Execute shell commands on a Linux environment", while the live description says the host OS/shell/backend are stated in the environment section and commands must be written for THAT platform.
- **Inputs / options:** n/a
- **Outputs / side effects:** A model following the docs would send an unknown argument.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Doc discrepancy: `clarify` question `id` field  `id: tools.docdiff-clarify-id`
- **Surface:** Docs
- **Where:** `tools-reference.md:47-57` ("Asking multiple questions at once").
- **What it does:** States "with each question's `id` (when supplied) echoed back".
- **How it works:** The live per-question item schema has exactly three properties: `question`, `choices`, `multi_select`. There is no `id`.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The rest of that doc section (per-surface behaviour, `timed_out`) matches the live tool.
- **Rebuild notes:** n/a

### Doc discrepancy: `spotify` toolset in the static table with no built-in tools  `id: tools.docdiff-spotify`
- **Surface:** Docs
- **Where:** `toolsets.py:357` and `tools-reference.md:349-362`.
- **What it does:** `TOOLSETS["spotify"]` names seven tools and the docs table describes them, but the built-in registry has none of them on a stock install.
- **How it works:** They are registered by the bundled `spotify` plugin (`hermes auth spotify` for OAuth). This is why the built-in tool count is 83 and not 90.
- **Inputs / options:** n/a
- **Outputs / side effects:** `is_toolset_available("spotify")` is False without the plugin.
- **Config / env:** Spotify OAuth.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Doc/code discrepancy: `yuanbao` static toolset vs `hermes-yuanbao` registry toolset  `id: tools.docdiff-yuanbao-toolset`
- **Surface:** Docs
- **Where:** `toolsets.py:330` (`yuanbao`) vs `tools/yuanbao_tools.py` `_TOOLSET = "hermes-yuanbao"`; `toolsets-reference.md` documents `yuanbao`, `tools-reference.md:363` documents `hermes-yuanbao`.
- **What it does:** Two names for one set of five tools; the static `yuanbao` toolset resolves the names but has zero registry entries.
- **How it works:** See `tools.toolset-yuanbao`.
- **Inputs / options:** n/a
- **Outputs / side effects:** `hermes tools` gating on the registry name will not find `yuanbao`.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Doc discrepancy: `hermes-cli` documented as including `send_message`-class messaging  `id: tools.docdiff-send-message`
- **Surface:** Docs
- **Where:** `toolsets-reference.md` platform table; `tools-reference.md` `hermes-api-server` row mentions "no interactive UI tools like clarify or send_message".
- **What it does:** Implies a `send_message` tool exists in some bundles.
- **How it works:** `toolsets.py:404` states plainly: "agents do NOT get an agent-callable send_message tool — outbound platform messaging is handled outside the agent loop (cron delivery, the gateway kanban notifier, and the `hermes send` CLI)". No `send_message` tool is registered; `tools/send_message_tool.py` (112 KB) exists but registers nothing into the registry. `agent/tool_guardrails.py` still lists `send_message` in `MUTATING_TOOL_NAMES` — a vestigial entry.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The one exception is `yb_send_dm`, which does send platform messages.
- **Rebuild notes:** n/a

### Documented environment requirements for `web_search` / `web_extract`  `id: tools.docdiff-web-env`
- **Surface:** Docs
- **Where:** `tools-reference.md:314-320` — "EXA_API_KEY or PARALLEL_API_KEY or FIRECRAWL_API_KEY or KEENABLE_API_KEY".
- **What it does:** Lists four env vars; the live `requires_env` metadata (`tools/web_tools.py:573` `_web_requires_env()`) returns nine: `EXA_API_KEY`, `PARALLEL_API_KEY`, `KEENABLE_API_KEY`, `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL`, `FIRECRAWL_GATEWAY_URL`, `TOOL_GATEWAY_DOMAIN`, `TOOL_GATEWAY_SCHEME`, `TOOL_GATEWAY_USER_TOKEN`.
- **How it works:** The gateway vars are always reported as metadata strings so the registry lights the tools up when they are set; gating them on `managed_nous_tools_enabled()` used to cost a synchronous HTTP refresh against the Nous portal at every CLI startup. `_LEGACY_WEB_BACKENDS = {"parallel", "firecrawl", "exa", "searxng", "brave-free", "ddgs", "xai", "keenable"}`.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** as listed.
- **Edge cases / guards:** Exa and Parallel have keyless anonymous free tiers (`is_keyless_available`), so zero-credential installs can still search.
- **Rebuild notes:** n/a

---

## Handoffs

- CLI shard: `hermes tools` (the curses per-platform tool toggler), `hermes chat --toolsets`, `/tools list|enable|disable`, `/browser connect|use off`, `hermes mcp install|login|catalog`, `hermes computer-use doctor`, `hermes auth spotify`, `hermes send`.
- Config shard: `tool_budget.mcp_result_size_chars`, `tool_output.max_bytes|max_lines|max_line_length`, `tool_loop_guardrails.*`, `toolsets:`, `custom_toolsets:`, `plugins.entries.<id>.allow_tool_override`, `delegation.*`, `kanban.dispatch_in_gateway`, `display.message_reactions`, `browser.*`, `web.backend`, `tts.*`, `video_gen.*`, `memory.*`, `skills.external_dirs`.
- Media shard: provider matrices and backends behind `browser_*` (agent-browser, Lightpanda, Camofox, Browserbase, Browser Use, Firecrawl), `vision_analyze`/`video_analyze` (auxiliary vision chain), `image_generate` (FAL catalog + plugin providers), `video_generate` (xAI Imagine, FAL Veo 3.1 / Pixverse v6 / Kling O3), `text_to_speech` (edge, openai, elevenlabs, minimax, xai, mistral, gemini, neutts, kittentts, piper + command providers), and `tools/transcription_tools.py` / `voice_mode.py` / `wake_word.py`.
- MCP shard: `tools/mcp_tool.py` (386 KB), `mcp_oauth*.py`, `mcp_schema_cache.py`, `mcp_stdio_watchdog.py`, the `mcp-<server>` dynamic toolsets, the `mcp_` tool-name prefix and its 50 000-char budget, and `registry.deregister`'s `mcp-` exemption.
- Plugins shard: `plugins/` and `optional-mcps/`, the bundled `spotify` plugin's seven tools, `plugins/web/<vendor>/provider.py`, `plugins/video_gen/<name>/`, `agent/image_gen_registry.py`, `agent/video_gen_registry.py`, `hermes_cli/plugins.py`, `tools/plugin_guard.py`.
- Skills shard: `tools/skills_hub.py` (198 KB), `skills_sync*.py`, `skill_ledger.py`, `skill_usage.py`, `skills_guard.py`, `skill_linter.py`, `optional-skills/`, and the `xurl` skill referenced by `x_search`.
- Gateway/platform shard: `gateway/platform_registry.py` (the `hermes-<platform>` auto-synthesis path), `tui_gateway/server.py::_load_enabled_toolsets` (which folds `desktop_ui` / `project` into desktop-sourced sessions), `gateway/browser_control_broker.py` and the browser-extension control lane, `tools/clarify_gateway.py`.
- Approvals/security shard: `tools/approval.py` (271 KB), `write_approval.py`, `url_safety.py`, `threat_patterns.py`, `tirith_security.py`, `self_repo_guard.py`, `path_security.py`, `website_policy.py`, `osv_check.py`, and the dangerous-command approval flow behind `terminal`.
- Agent-core shard: `tools/tool_result_storage.py` (the spill/preview implementation), `agent/tool_executor.py` (2931 lines), `agent/stall_guards.py`, `tools/checkpoint_manager.py`, `tools/interrupt.py`, `tools/hook_output_spill.py`, `tools/schema_sanitizer.py`, `tools/tool_search.py`, `tools/managed_tool_gateway.py`.
