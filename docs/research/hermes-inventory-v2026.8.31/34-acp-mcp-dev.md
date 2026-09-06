# Protocol surfaces — ACP, MCP, OpenAI-compatible API, A2A, LSP, proxy, plugin/hook developer API

This shard documents every surface where Hermes Agent v2026.8.31 speaks a *protocol* to
something outside itself, plus the developer-facing extension contracts. It covers: the ACP
(Agent Client Protocol) server `hermes acp` and its Copilot-ACP *client*; the MCP client
(`hermes mcp …`, `mcp_servers:` config, OAuth/CIMD) and the two MCP *servers* Hermes ships
(`hermes mcp serve`, `agent.transports.hermes_tools_mcp_server`); the OpenAI-compatible
`/v1/chat/completions`, `/v1/responses`, `/v1/models` endpoints of the API-server platform;
the A2A (Agent2Agent v1.0) platform plugin in both directions; the LSP layer (`hermes lsp`);
the OAuth-attaching `hermes proxy`; the plugin developer API (`PluginContext`, manifests,
hooks, middleware, packs, `hermes plugins …`); shell hooks (`hermes hooks …`); shell
completion; and the Nix / Docker / native-extension packaging surfaces.

Deliberately left to sibling shards: the rest of the API-server platform (runs, artifacts,
hosted rooms, browser-control — `platforms-*`), gateway slash commands (`gw-slash`), the
tool catalogue itself (`tools`), providers (`providers`), the web dashboard's MCP/plugin
*pages* (`web-*`), the desktop app's MCP/plugin *pages* (`desktop-*`), and the exhaustive
env-var list (`env-vars`).

---

## 1. ACP — Agent Client Protocol (Hermes as an editor agent)

### Start Hermes in ACP mode  `id: acp-mcp-dev.hermes-acp`
- **Surface:** CLI
- **Where:** `hermes acp` (also the console scripts `hermes-acp` and `python -m acp_adapter`; help text: "Start Hermes Agent in ACP mode for editor integration (VS Code, Zed, JetBrains)").
- **What it does:** Runs Hermes as an ACP JSON-RPC agent over stdio so an ACP-capable editor (Zed, VS Code via an ACP bridge, JetBrains via a bridge, `acp-bridge`) can drive it as its coding agent. stdout carries only ACP frames; every log goes to stderr.
- **How it works:** `hermes_cli/main.py` dispatches to `acp_adapter/entry.py:main()` (`acp_adapter/entry.py:220`). Boot order: import `hermes_bootstrap` first for Windows UTF-8 stdio then `harden_import_path()` so a `utils/`/`proxy/`/`ui/` package in the launch cwd cannot shadow Hermes modules (`acp_adapter/entry.py:18-30`); parse args; `_setup_logging()` installs a stderr `RedactingFormatter` (`agent.redact`) with format `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`, datefmt `"%Y-%m-%d %H:%M:%S"`, level INFO, and silences `httpx`/`httpcore`/`openai` to WARNING (`acp_adapter/entry.py:81-101`); `_load_env()` loads `$HERMES_HOME/.env` via `hermes_cli.env_loader.load_hermes_dotenv` (`acp_adapter/entry.py:104`); the project root is pushed onto `sys.path`; unless `HERMES_ACP_SKIP_CONFIGURED_MCP=1`, `hermes_cli.mcp_startup.start_background_mcp_discovery(thread_name="acp-mcp-discovery")` fires MCP discovery in a daemon thread so the server answers immediately (`acp_adapter/entry.py:260-269`); finally `asyncio.run(acp.run_agent(HermesACPAgent(), use_unstable_protocol=True))` (`acp_adapter/entry.py:273`).
- **Inputs / options:** `-h, --help`; `--accept-hooks` (auto-approve unseen shell hooks without a TTY prompt — same as `HERMES_ACCEPT_HOOKS=1` / `hooks_auto_accept: true`); `--version` (prints `hermes_cli.__version__` and exits); `--check` (imports `acp` and `acp_adapter.server.HermesACPAgent`, prints `Hermes ACP check OK`, exits); `--setup` (re-enters `hermes model` interactive provider/model setup, then, if stdin is a TTY, offers "Install browser tools? Downloads agent-browser (npm) and optionally Playwright Chromium (~400 MB). [y/N] "); `--setup-browser` (idempotent install of agent-browser + Playwright Chromium into `~/.hermes/node/` through `hermes_cli.dep_ensure.ensure_dependency("node")` then `ensure_dependency("browser")`); `--yes, -y` (dest `assume_yes`; skips the ~400 MB Chromium confirmation).
- **Outputs / side effects:** A long-lived stdio JSON-RPC server. `--setup-browser` writes into `~/.hermes/node/`. Sessions are persisted into `$HERMES_HOME/state.db` with `source="acp"`. Exit code 1 on an unhandled crash ("ACP agent crashed" logged with traceback); KeyboardInterrupt logs "Shutting down (KeyboardInterrupt)" and exits 0.
- **Config / env:** `HERMES_HOME`; `HERMES_ACP_SKIP_CONFIGURED_MCP=1` (metadata-only hosts opt out of global MCP startup); `HERMES_ACCEPT_HOOKS`; `hooks_auto_accept`; `mcp_discovery_timeout` (default `1.5`); everything the normal runtime provider resolution reads (`model.default`, `model.provider`, per-provider API keys).
- **Edge cases / guards:** Requires the optional `agent-client-protocol` dependency (`pyproject.toml` `[acp]` extra); `--check` is the supported preflight. Liveness probes (`ping`, `health`, `healthcheck`) still get JSON-RPC `-32601` but their "Background task failed" tracebacks are filtered out of stderr by `_BenignProbeMethodFilter` (`acp_adapter/entry.py:49-78`). A partial `hermes update` that left `hermes_bootstrap` unregistered degrades gracefully (POSIX unaffected, Windows loses UTF-8 stdio setup).
- **Rebuild notes:** Minimal spec — an asyncio stdio JSON-RPC server implementing the ACP agent role, with stdout reserved for frames, logs on stderr, and a synchronous agent driven in a worker thread. A better version would keep the protocol version negotiable per-connection rather than always answering `acp.PROTOCOL_VERSION`, and would expose the MCP-discovery readiness as a session-update so editors can show "tools still loading".

### ACP `initialize` handshake and advertised agent capabilities  `id: acp-mcp-dev.acp-initialize`
- **Surface:** Core
- **What it does:** Answers the editor's `initialize` request with Hermes' protocol version, agent identity and the capability set the editor uses to decide which UI affordances to show.
- **How it works:** `HermesACPAgent.initialize()` (`acp_adapter/server.py:1295-1326`). It logs `"Initialize from %s (protocol v%s)"`, then returns `InitializeResponse(protocol_version=acp.PROTOCOL_VERSION, agent_info=Implementation(name="hermes-agent", version=HERMES_VERSION), agent_capabilities=AgentCapabilities(load_session=True, prompt_capabilities=PromptCapabilities(image=True), session_capabilities=SessionCapabilities(fork=SessionForkCapabilities(), list=SessionListCapabilities(), resume=SessionResumeCapabilities())), auth_methods=build_auth_methods())`.
- **Inputs / options:** `protocol_version: int | None` (ignored for the answer — Hermes always replies with its own `acp.PROTOCOL_VERSION`), `client_capabilities: ClientCapabilities | None`, `client_info: Implementation | None`, plus `**kwargs`.
- **Outputs / side effects:** `InitializeResponse`. Nothing persisted.
- **Config / env:** n/a — `HERMES_VERSION` comes from `hermes_cli.__version__` and falls back to `"0.0.0"` when the import fails (`acp_adapter/server.py:226-228`).
- **Edge cases / guards:** Capabilities are static; `load_session=True` is advertised unconditionally, so an editor may call `session/load` for an id Hermes cannot restore (it answers `None` and logs a warning). `prompt_capabilities.image=True` means the editor may send `ImageContentBlock`s.
- **Rebuild notes:** Reply with a fixed capability struct plus dynamically-built auth methods. A better version would negotiate `protocol_version = min(client, server)` and advertise `audio` only when a transcription backend is actually configured.

### ACP authentication methods  `id: acp-mcp-dev.acp-authenticate`
- **Surface:** Core
- **Where:** Editor "Sign in / configure agent" affordance for the Hermes ACP agent.
- **What it does:** Advertises how the editor can get Hermes authenticated and accepts the editor's `authenticate` call.
- **How it works:** `acp_adapter/auth.py`. `detect_provider()` resolves the live runtime provider via `hermes_cli.runtime_provider.resolve_runtime_provider()` and treats both a non-empty string `api_key` and a *callable* `api_key` (Azure Foundry Entra-ID bearer provider) as valid credentials (`acp_adapter/auth.py:11-33`). `build_auth_methods()` (`acp_adapter/auth.py:41-79`) always appends `TerminalAuthMethod(id="hermes-setup", name="Configure Hermes provider", description="Open Hermes' interactive model/provider setup in a terminal. Use this when Hermes has not been configured on this machine yet.", type="terminal", args=["--setup"])`, and when a provider resolves it *prepends* `AuthMethodAgent(id=<provider>, name="<provider> runtime credentials", description="Authenticate Hermes using the currently configured <provider> runtime credentials.")`. `HermesACPAgent.authenticate()` (`acp_adapter/server.py:1329-1348`) lower-cases/strips `method_id`; for `hermes-setup` it returns `AuthenticateResponse()` only once a provider resolves; otherwise it returns a response only when `method_id == detect_provider()`, else `None`.
- **Inputs / options:** `method_id: str` (`"hermes-setup"` or a provider slug such as `nous`, `openrouter`, `anthropic`, …), plus `**kwargs`.
- **Outputs / side effects:** `AuthenticateResponse()` or `None`. The terminal method makes the editor spawn `hermes acp --setup` in a terminal pane.
- **Config / env:** whatever `resolve_runtime_provider()` reads — `model.provider`, per-provider keys in `~/.hermes/.env`, `~/.hermes/auth.json`.
- **Edge cases / guards:** Non-string `method_id` returns `None`. ACP is stdio + local-trust, so this is API hygiene rather than a security boundary (documented inline at `acp_adapter/server.py:1330-1336`). A fresh Zed install with no credentials still gets a usable method (the terminal one), which is what the official ACP registry validates.
- **Rebuild notes:** Always advertise at least one method; make one of them a "run my setup wizard in a terminal" method so first-run works. A better version would emit an `auth_methods` refresh notification after setup completes instead of requiring a reconnect.

### ACP `session/new`  `id: acp-mcp-dev.acp-session-new`
- **Surface:** Core
- **Where:** Editor "New thread" for the Hermes agent.
- **What it does:** Creates a fresh ACP session bound to the editor's workspace directory and returns its id, model list and mode list.
- **How it works:** `HermesACPAgent.new_session()` (`acp_adapter/server.py:1591-1610`) → `SessionManager.create_session(cwd)` (`acp_adapter/session.py:210-229`): translates the cwd for WSL, mints `uuid4()` as the session id, builds an `AIAgent` via `_make_agent()`, wraps it in `SessionState`, registers the task-scoped cwd override, and persists to `SessionDB`. Then `_register_session_mcp_servers(state, mcp_servers)`, `_schedule_mcp_late_refresh(state)`, `_schedule_available_commands_update()`, `_schedule_usage_update()`.
- **Inputs / options:** `cwd: str` (required), `mcp_servers: list | None` (per-session MCP server declarations from the editor), `**kwargs`.
- **Outputs / side effects:** `NewSessionResponse(session_id, models=<SessionModelState>, modes=<SessionModeState>, field_meta=<provenance meta>)`. A row in `sessions` of `$HERMES_HOME/state.db` with `source="acp"`, `model_config={"cwd": …}`. A task-env cwd override registered through `tools.terminal_tool.register_task_env_overrides`. Log line `"New session %s (cwd=%s)"`.
- **Config / env:** `model.default`, `model.provider`, `mcp_servers.*`, `mcp_discovery_timeout`.
- **Edge cases / guards:** `cwd` is translated when Hermes runs in WSL but the editor is on Windows (`E:\Projects`, `\\wsl.localhost\…` → POSIX) via `hermes_constants.translate_cwd_for_wsl_backend` (`acp_adapter/session.py:29-39`).
- **Rebuild notes:** Create agent + state + DB row + cwd binding atomically, then fire the three "advertise" notifications after the response is queued (`loop.call_soon`) so the client has already routed the session id.

### ACP `session/load` (with in-call history replay)  `id: acp-mcp-dev.acp-session-load`
- **Surface:** Core
- **What it does:** Re-attaches the editor to a previously created ACP session and streams the whole prior transcript back as `session/update` notifications *before* the load response returns.
- **How it works:** `HermesACPAgent.load_session()` (`acp_adapter/server.py:1612-1657`). `SessionManager.update_cwd(session_id, cwd)` restores from `SessionDB` when the session is not in memory; `None` → the method logs `"load_session: session %s not found"` and returns `None`. Otherwise it registers per-session MCP servers, schedules the MCP late refresh, then **awaits** `_replay_session_history(state)` (see `acp-mcp-dev.acp-history-replay`) — deliberately awaited (not `loop.call_soon`) to match Codex / Claude Code / OpenCode / Pi and the Zed client, which register the session-update routing entry before awaiting `loadSession`.
- **Inputs / options:** `cwd: str`, `session_id: str`, `mcp_servers: list | None`, `**kwargs`.
- **Outputs / side effects:** `LoadSessionResponse(models, modes, field_meta)` or `None`; a burst of `session/update` notifications (user/assistant chunks, thoughts, tool calls).
- **Edge cases / guards:** A replay exception never turns a successful load into a JSON-RPC error — it logs `"ACP history replay raised during session/load for %s — load will still succeed, partial transcript may be missing"` and returns normally.
- **Rebuild notes:** Emit history notifications synchronously inside the load request. Deferring them (Hermes briefly did in May 2026) breaks every spec-compliant client that measures notifications against the load response.

### ACP `session/resume`  `id: acp-mcp-dev.acp-session-resume`
- **Surface:** Core
- **What it does:** Like `session/load`, but creates a brand-new session instead of failing when the id is unknown.
- **How it works:** `HermesACPAgent.resume_session()` (`acp_adapter/server.py:1660-1694`). On a miss it logs `"resume_session: session %s not found, creating new"` and calls `create_session(cwd=cwd)`; then registers MCP servers, schedules the late refresh, awaits history replay, schedules commands + usage, returns `ResumeSessionResponse(models, modes, field_meta)`.
- **Inputs / options:** `cwd: str`, `session_id: str`, `mcp_servers: list | None`, `**kwargs`.
- **Outputs / side effects:** Same as load, plus possibly a new DB row.
- **Edge cases / guards:** Replay failures are swallowed with the analogous warning.
- **Rebuild notes:** Resume = load with create-on-miss. Returning a *different* session id than requested is legal here because the response echoes state, not the id.

### ACP `session/fork`  `id: acp-mcp-dev.acp-session-fork`
- **Surface:** Core
- **Where:** Editor "Fork thread" / branch affordance.
- **What it does:** Deep-copies an existing session's message history into a brand-new session id so the user can branch a conversation.
- **How it works:** `HermesACPAgent.fork_session()` (`acp_adapter/server.py:1717-1735`) → `SessionManager.fork_session(session_id, cwd)` (`acp_adapter/session.py:253`). Logs `"Forked session %s -> %s"`. Registers per-session MCP servers on the fork and schedules an available-commands update for the new id.
- **Inputs / options:** `cwd: str`, `session_id: str`, `mcp_servers: list | None`, `**kwargs`.
- **Outputs / side effects:** `ForkSessionResponse(session_id=<new id or "">, models, modes)`; a second `sessions` row; `copy.deepcopy` of history.
- **Edge cases / guards:** When the source session cannot be found, `session_id` comes back as `""` and `models`/`modes` are `None`.
- **Rebuild notes:** Deep-copy history, mint a new id, keep the fork's own cwd. A better version would record `parent_session_id` on the fork so provenance shows the branch point (Hermes uses that column for compression lineage instead).

### ACP `session/list` with cursor pagination  `id: acp-mcp-dev.acp-session-list`
- **Surface:** Core
- **Where:** Editor thread-history picker.
- **What it does:** Lists ACP sessions, optionally filtered to one workspace, 50 per page.
- **How it works:** `HermesACPAgent.list_sessions()` (`acp_adapter/server.py:1737-1774`). `SessionManager.list_sessions(cwd=cwd)` normalises and filters by cwd; the cursor is a previously-returned `session_id` and results resume *after* it (an unknown cursor yields an empty page, never a full-list fallback). Page size `_LIST_SESSIONS_PAGE_SIZE = 50` (`acp_adapter/server.py:236`). Each row becomes `SessionInfo(session_id, cwd, title, updated_at)`; `updated_at` is coerced to `str`. `next_cursor` is the last returned id when more remain.
- **Inputs / options:** `cursor: str | None`, `cwd: str | None`, `**kwargs`.
- **Outputs / side effects:** `ListSessionsResponse(sessions=[SessionInfo…], next_cursor=str|None)`.
- **How titles are built:** `_build_session_title(title, preview, cwd)` (`acp_adapter/session.py:73-82`) → explicit title, else the first-message preview, else the cwd basename, else `"New thread"`.
- **Edge cases / guards:** cwd comparison is normalised through `_normalize_cwd_for_compare` (`acp_adapter/session.py:43-70`): `~` expansion, Windows→WSL drive translation, lower-cased `/mnt/<drive>/`, and `os.path.realpath` so `/var` vs `/private/var` and `/tmp` vs `/private/tmp` on macOS compare equal (ported from PrimeIntellect-ai/prime-agent#628); `OSError` falls back to `normpath`.
- **Rebuild notes:** Keep an opaque cursor = last id, and normalise workspace paths aggressively or macOS/WSL users silently see zero sessions.

### ACP `session/cancel`  `id: acp-mcp-dev.acp-session-cancel`
- **Surface:** Core
- **Where:** Editor "Stop" button during a running turn.
- **What it does:** Interrupts the in-flight agent turn for a session and makes the pending `prompt` answer `stop_reason="cancelled"`.
- **How it works:** `HermesACPAgent.cancel()` (`acp_adapter/server.py:1696-1715`). Under `state.runtime_lock`: if a turn is running it snapshots `state.current_prompt_text` into `state.interrupted_prompt_text`, sets `state.cancel_event`, then calls `request_hard_interrupt(state.agent)`. Logs `"Cancelled session %s"`.
- **Inputs / options:** `session_id: str`, `**kwargs`.
- **Outputs / side effects:** No response payload (notification-shaped). The running `prompt()` returns `PromptResponse(stop_reason="cancelled")`.
- **Edge cases / guards:** The lock is taken so a concurrently-arriving prompt cannot mistake the cancelled turn for redirectable work; interrupt failures are swallowed at debug level.
- **Rebuild notes:** Publish cancellation and hard-stop under one lock; keep the interrupted prompt text so a follow-up turn can reference it.

### ACP `session/prompt` (the core turn)  `id: acp-mcp-dev.acp-prompt`
- **Surface:** Core
- **Where:** The editor's message composer for the Hermes agent.
- **What it does:** Accepts the user's prompt as ACP content blocks, runs one Hermes agent turn in a worker thread, streams thoughts/tool calls/message chunks back as `session/update`s, and returns a stop reason plus token usage.
- **How it works:** `HermesACPAgent.prompt()` (`acp_adapter/server.py:1784+`). Content blocks are flattened by `_content_blocks_to_openai_user_content` (`acp_adapter/tools.py`-adjacent helpers at `acp_adapter/server.py:547`), which handles `TextContentBlock`, `ImageContentBlock` (→ `data:` URL via `_image_data_url`, `acp_adapter/server.py:298`), `ResourceContentBlock` (resource links → `_resource_link_to_parts`, `acp_adapter/server.py:364`), and `EmbeddedResourceContentBlock` (`_embedded_resource_to_parts`, `acp_adapter/server.py:463`); `file://` URIs resolve through `_path_from_file_uri` (`acp_adapter/server.py:302`), text is decoded by `_decode_text_bytes` (`acp_adapter/server.py:337`), MIME sniffing by `_is_text_resource` / `_is_image_resource` / `_guess_image_mime_from_path`. A leading `/word` is first offered to `_handle_slash_command`. The AIAgent runs in a `ThreadPoolExecutor` with `contextvars` pinned to the session cwd; callbacks from `acp_adapter/events.py` bridge to `conn.session_update()`; `tools.approval` gets an ACP-backed approval callback and `acp_adapter.edit_approval` gets a bound requester for the duration of the turn, both restored afterwards.
- **Inputs / options:** `prompt: list[TextContentBlock | ImageContentBlock | AudioContentBlock | ResourceContentBlock | EmbeddedResourceContentBlock]`, `session_id: str`, `**kwargs`.
- **Outputs / side effects:** `PromptResponse(stop_reason="end_turn" | "cancelled" | "refusal", usage=Usage(input_tokens, output_tokens, total_tokens, thought_tokens, cached_read_tokens))` (`acp_adapter/server.py:2206-2219`). Streams `agent_message_chunk`, `agent_thought_chunk`, `tool_call` / `tool_call_update`, `plan`, `available_commands_update`, and a usage update. Persists history to `SessionDB`. Queued prompts (`/queue`) are dispatched by re-entering `prompt()` recursively (`acp_adapter/server.py:2200-2204`).
- **Edge cases / guards:** Unknown `session_id` → `PromptResponse(stop_reason="refusal")` after logging `"prompt: session %s not found"`. Usage is only attached when at least one of `prompt_tokens` / `completion_tokens` / `total_tokens` is non-None.
- **Rebuild notes:** Run the blocking agent off the event loop, bridge callbacks with `run_coroutine_threadsafe`, and always answer with a stop reason. A better version would stream partial tool output rather than one completion block per tool.

### ACP slash-command advertisement (`available_commands_update`)  `id: acp-mcp-dev.acp-available-commands`
- **Surface:** Core
- **Where:** The editor's `/` autocomplete popup inside a Hermes thread.
- **What it does:** Tells the editor which slash commands the Hermes agent understands, with descriptions and free-text input hints.
- **How it works:** `_available_commands()` (`acp_adapter/server.py:2224-2237`) maps the `_ADVERTISED_COMMANDS` tuple (`acp_adapter/server.py:611-650`) into `AvailableCommand(name, description, input=UnstructuredCommandInput(hint=…) | None)`. `_send_available_commands_update()` pushes an `AvailableCommandsUpdate(session_update="available_commands_update", available_commands=[…])`; `_schedule_available_commands_update()` posts it with `loop.call_soon(asyncio.create_task, …)` so it lands after the session response is queued.
- **Inputs / options:** The nine advertised commands, verbatim: `help` — "List available commands"; `model` — "Show current model and provider, or switch models", hint "model name to switch to"; `tools` — "List available tools with descriptions"; `context` — "Show conversation message counts by role"; `reset` — "Clear conversation history"; `compress` — "Compress conversation context"; `steer` — "Inject guidance into the currently running agent turn", hint "guidance for the active turn"; `queue` — "Queue a prompt to run after the current turn finishes", hint "prompt to run next"; `version` — "Show Hermes version".
- **Outputs / side effects:** One `session/update` per session creation/load/resume/fork.
- **Edge cases / guards:** No connection (`self._conn is None`) → silent no-op. Failures log `"Failed to advertise ACP slash commands for session %s"`.
- **Rebuild notes:** Advertise commands as data so the editor can autocomplete; keep the advertised list and the dispatch table in sync (Hermes keeps two structures, `_SLASH_COMMANDS` for `/help` text and `_ADVERTISED_COMMANDS` for the wire).

### ACP slash-command dispatch  `id: acp-mcp-dev.acp-slash-dispatch`
- **Surface:** Core
- **Where:** Typing `/<command>` as the first token of an ACP prompt.
- **What it does:** Intercepts nine headless commands before the text reaches the LLM; anything unrecognised falls through to the model as ordinary prose.
- **How it works:** `_handle_slash_command(text, state)` (`acp_adapter/server.py:2267-2312`) splits on the first whitespace, strips leading `/`, lower-cases, and looks the name up in a dict mapping to `_cmd_help / _cmd_model / _cmd_tools / _cmd_context / _cmd_reset / _cmd_compress / _cmd_steer / _cmd_queue / _cmd_version`. Unknown → `None` (falls through). The handler runs inside `contextvars.copy_context().run(...)` after `agent.runtime_cwd.set_session_cwd(state.cwd)` so `/compress` and `/model` — which rebuild the system prompt via `agent._build_system_prompt` → `resolve_agent_cwd` — cannot bake the Hermes install tree into the cached prompt or leak the cwd into other concurrent ACP sessions.
- **Inputs / options:** command name + everything after the first space as `args`.
- **Outputs / side effects:** Returns a plain-text string streamed back as an `agent_message_chunk`. Errors return `"Error executing /<cmd>: <exception>"` and log at ERROR.
- **Edge cases / guards:** Handlers run on the event-loop thread, so they must not block.
- **Rebuild notes:** Fall through on unknown commands (users legitimately type `/` prose); pin the session cwd inside a *fresh* context per dispatch.

### ACP `/help`  `id: acp-mcp-dev.acp-cmd-help`
- **Surface:** Core
- **Where:** `/help` in an ACP thread.
- **What it does:** Prints the nine commands with their short descriptions and notes that unknown `/commands` go to the model.
- **How it works:** `_cmd_help()` (`acp_adapter/server.py:2316-2323`) renders `_SLASH_COMMANDS` as `  /{cmd:10s}  {desc}` under the header `Available commands:` and appends `Unrecognized /commands are sent to the model as normal messages.`
- **Inputs / options:** none (args ignored).
- **Outputs / side effects:** Text only. The `_SLASH_COMMANDS` descriptions, verbatim: `help` "Show available commands", `model` "Show or change current model", `tools` "List available tools", `context` "Show conversation context info", `reset` "Clear conversation history", `compress` "Compress conversation context", `steer` "Inject guidance into the currently running agent turn", `queue` "Queue a prompt to run after the current turn finishes", `version` "Show Hermes version".
- **Rebuild notes:** Trivially derived from the command table.

### ACP `/model`  `id: acp-mcp-dev.acp-cmd-model`
- **Surface:** Core
- **Where:** `/model` (show) or `/model <name>` (switch) in an ACP thread.
- **What it does:** Shows the session's current model/provider, or switches to another model — rebuilding the underlying `AIAgent`.
- **How it works:** `_cmd_model()` (`acp_adapter/server.py:2325-2346`). With no args: `f"Current model: {model}\nProvider: {provider}"` (provider falls back to `"auto"`). With args: `_resolve_model_selection(args, current_provider or "openrouter")` resolves a `provider:model` pair, then `SessionManager._make_agent(session_id, cwd, model, requested_provider)` mints a fresh agent, `save_session()` persists it, and it answers `f"Model switched to: {new_model}\nProvider: {provider_label}"`.
- **Inputs / options:** optional model name; accepts the `provider:model` encoded form produced by `_encode_model_choice` (`acp_adapter/server.py:713-722`).
- **Outputs / side effects:** New `AIAgent` on the session; `model` column updated in `state.db`; log `"Session %s: model switched to %s"`.
- **Edge cases / guards:** Rebuilding the agent drops in-process runtime state; history survives because it lives on `SessionState`.
- **Rebuild notes:** Keep provider context in the model id string so a bare model name cannot silently switch providers.

### ACP `/tools`  `id: acp-mcp-dev.acp-cmd-tools`
- **Surface:** Core
- **Where:** `/tools` in an ACP thread.
- **What it does:** Lists every tool the session's agent can call, with a truncated description.
- **How it works:** `_cmd_tools()` (`acp_adapter/server.py:2348-2381`). Expands the session's toolsets with `_expand_acp_enabled_toolsets(agent.enabled_toolsets or ["hermes-acp"])`, calls `model_tools.get_tool_definitions(enabled_toolsets=…, quiet_mode=True)`, builds a `SimpleNamespace` tool view and runs `agent.memory_manager.inject_memory_provider_tools()` on it so memory-provider tools appear too. Prints `Available tools (N):` then `  {name}: {desc}` with descriptions truncated to 77 chars + `...`.
- **Inputs / options:** none.
- **Outputs / side effects:** Text only. `"No tools available."` when empty; `"Could not list tools: <err>"` on failure.
- **Rebuild notes:** Resolve tools through the same path the model sees, including provider-injected tools, or the list lies.

### ACP `/context`  `id: acp-mcp-dev.acp-cmd-context`
- **Surface:** Core
- **Where:** `/context` in an ACP thread.
- **What it does:** Reports conversation size, per-role message counts, model/provider, and context-window pressure with compression guidance.
- **How it works:** `_cmd_context()` (`acp_adapter/server.py:2383+`). Counts `state.history` by `role`; reads `context_length` and `threshold_tokens` off `agent.context_compressor` (falling back to `0.80 * context_length` when the threshold is unset); estimates the request size with `agent.model_metadata.estimate_request_tokens_rough(history, system_prompt=agent._cached_system_prompt, tools=agent.tools)`.
- **Inputs / options:** none.
- **Outputs / side effects:** Text. Lines include `Conversation: N messages` (or `Conversation is empty (no messages yet).`) and a `user: …, assistant: …` breakdown.
- **Edge cases / guards:** Token estimation failures degrade to `0` and log at debug.
- **Rebuild notes:** Show both the raw count and the token estimate; users need the estimate to decide whether to `/compress`.

### ACP `/reset`  `id: acp-mcp-dev.acp-cmd-reset`
- **Surface:** Core
- **Where:** `/reset` in an ACP thread.
- **What it does:** Clears the session's conversation history.
- **How it works:** `_cmd_reset()` in `acp_adapter/server.py` (dispatch table at `acp_adapter/server.py:2299`), followed by `SessionManager.save_session()` so the emptied history is persisted.
- **Inputs / options:** none.
- **Outputs / side effects:** `state.history` emptied; the persisted active message set replaced. Archived (compacted) rows are preserved by the `active_only=True` replace path — see `acp-mcp-dev.acp-session-persistence`.
- **Rebuild notes:** Reset should clear the live transcript without destroying compaction archives.

### ACP `/compress`  `id: acp-mcp-dev.acp-cmd-compress`
- **Surface:** Core
- **Where:** `/compress` in an ACP thread.
- **What it does:** Forces a context-compaction pass on the session transcript.
- **How it works:** Dispatches to `_cmd_compress` (`acp_adapter/server.py:2301`), which drives the agent's `ContextCompressor`. Because compaction can rotate the internal Hermes session id, the reply's `_meta` carries updated provenance on the next response (see `acp-mcp-dev.acp-provenance`).
- **Inputs / options:** none.
- **Outputs / side effects:** History replaced with a summary handoff; a new internal session row with `parent_session_id` pointing at the compressed parent whose `end_reason='compression'`.
- **Edge cases / guards:** Runs with the session cwd pinned (see `acp-mcp-dev.acp-slash-dispatch`) precisely because it rebuilds the system prompt.
- **Rebuild notes:** Keep pre-compaction turns as `active=0, compacted=1` rows rather than deleting them.

### ACP `/steer`  `id: acp-mcp-dev.acp-cmd-steer`
- **Surface:** Core
- **Where:** `/steer <guidance>` while a turn is running.
- **What it does:** Injects mid-turn guidance into the agent that is currently executing.
- **How it works:** `_cmd_steer()` (dispatch at `acp_adapter/server.py:2302`) writes the guidance into the running agent's steering channel under `state.runtime_lock`.
- **Inputs / options:** free text after the command (hint: "guidance for the active turn").
- **Outputs / side effects:** Text confirmation; the running turn receives the guidance.
- **Edge cases / guards:** With no turn in flight the guidance has nowhere to go — the command reports that rather than silently dropping it.
- **Rebuild notes:** Steering needs a lock shared with cancel and queue, or a concurrently-arriving cancel races it.

### ACP `/queue`  `id: acp-mcp-dev.acp-cmd-queue`
- **Surface:** Core
- **Where:** `/queue <prompt>` in an ACP thread.
- **What it does:** Queues a prompt to run automatically once the current turn finishes.
- **How it works:** `_cmd_queue()` (`acp_adapter/server.py:2556-2563`) appends to `state.queued_prompts` under `state.runtime_lock` and replies `f"Queued for the next turn. ({depth} queued)"`. At the end of `prompt()` the next queued item is popped and `prompt()` is re-entered with it (`acp_adapter/server.py:2200-2204`).
- **Inputs / options:** free text (hint: "prompt to run next").
- **Outputs / side effects:** Depth-annotated confirmation; a follow-up turn with its own stream of updates.
- **Rebuild notes:** A FIFO on the session plus a drain at end-of-turn; re-entering the same prompt method keeps one code path.

### ACP `/version`  `id: acp-mcp-dev.acp-cmd-version`
- **Surface:** Core
- **Where:** `/version` in an ACP thread.
- **What it does:** Prints `Hermes Agent v<version>`.
- **How it works:** `_cmd_version()` (`acp_adapter/server.py:2565-2566`) returns `f"Hermes Agent v{HERMES_VERSION}"`.
- **Inputs / options:** none.
- **Outputs / side effects:** Text only.
- **Rebuild notes:** n/a.

### ACP `session/set_model`  `id: acp-mcp-dev.acp-set-session-model`
- **Surface:** Core
- **Where:** The editor's model picker for the Hermes thread (Zed shows this as a separate control from modes).
- **What it does:** Switches the session's model through the protocol rather than a slash command.
- **How it works:** `HermesACPAgent.set_session_model()` (`acp_adapter/server.py:2570-2601`). Resolves `(requested_provider, resolved_model)` from `model_id` against the agent's current provider (default `"openrouter"`); when the provider *changes*, `base_url` and `api_mode` are dropped so the new provider's defaults apply, otherwise they are carried over. Rebuilds the agent, saves the session, logs `"Session %s: model switched to %s via provider %s"`.
- **Inputs / options:** `model_id: str` (accepts the `provider:model` encoding), `session_id: str`, `**kwargs`.
- **Outputs / side effects:** `SetSessionModelResponse()`; `None` (+ warning `"Session %s: model switch requested for missing session"`) when the session is unknown.
- **Rebuild notes:** Carrying `base_url`/`api_mode` across a same-provider switch but dropping them on a provider switch is the load-bearing detail.

### ACP model inventory advertised to the editor  `id: acp-mcp-dev.acp-model-state`
- **Surface:** Core
- **Where:** The editor's model dropdown contents.
- **What it does:** Builds the `SessionModelState` (current model + the selectable list) from Hermes' shared model inventory so ACP shows the same catalogue as `hermes model`, the TUI and the dashboard.
- **How it works:** `_build_model_state()` (`acp_adapter/server.py:731+`). Uses `hermes_cli.inventory.load_picker_context()` + `.with_overrides(current_provider, current_model, current_base_url)` and `build_models_payload(..., explicit_only=True, include_unconfigured=False, picker_hints=False, canonical_order=True, pricing=False, capabilities=False, refresh=False, probe_custom_providers=False, probe_current_custom_provider=False, max_models=ACP_MAX_MODELS_PER_PROVIDER)`. Providers are normalised with `hermes_cli.models.normalize_provider`; `ollama` is mapped to `custom:ollama`; rows flagged `native_catalog_empty` are tracked; model choices are encoded by `_encode_model_choice(provider, model)` → `"<provider>:<model>"` (or the bare model when no provider).
- **Inputs / options:** derived from session state; capped per provider by `ACP_MAX_MODELS_PER_PROVIDER`.
- **Outputs / side effects:** `SessionModelState | None` returned inside new/load/resume/fork responses.
- **Edge cases / guards:** Custom providers are not probed (`probe_custom_providers=False`) so the picker never blocks on a dead endpoint; pricing/capability enrichment is off for the same reason.
- **Rebuild notes:** Reuse one inventory across every surface, and encode the provider into the id so the picker is unambiguous.

### ACP session modes (edit-approval policy)  `id: acp-mcp-dev.acp-session-modes`
- **Surface:** Core
- **Where:** The editor's mode selector next to the Hermes thread's model picker.
- **What it does:** Exposes Hermes' file-edit approval policy as three ACP session modes.
- **How it works:** `_session_modes()` (`acp_adapter/server.py:682-707`) returns `SessionModeState(current_mode_id, available_modes=[…])` with exactly three modes: `default` — name "Default", description "Ask before edits."; `accept_edits` — name "Accept Edits", description "Auto-allow workspace and /tmp edits; still asks for sensitive paths."; `dont_ask` — name "Don't Ask", description "Auto-allow file edits for this session except sensitive paths." Modes map to edit-approval policies via `_MODE_TO_EDIT_APPROVAL_POLICY` (`acp_adapter/server.py:658-666`): `default→"ask"`, `accept_edits→"workspace_session"`, `dont_ask→"session"`; the inverse map drives `set_config_option`.
- **Inputs / options:** mode ids `default`, `accept_edits`, `dont_ask`.
- **Outputs / side effects:** `state.mode` is persisted with the session.
- **Edge cases / guards:** An unknown mode id normalises to `default`. Hermes deliberately maps this onto *modes* rather than ACP `config_options` because Zed renders config options in the slot where its model picker lives (comment at `acp_adapter/server.py:684-690`).
- **Rebuild notes:** Map a policy enum onto modes; keep an inverse map so a client that prefers config options still lands on the same state.

### ACP `session/set_mode`  `id: acp-mcp-dev.acp-set-session-mode`
- **Surface:** Core
- **What it does:** Persists the editor's mode choice for the session.
- **How it works:** `set_session_mode()` (`acp_adapter/server.py:2604-2618`): normalises `mode_id` (unknown → `default`), sets `state.mode`, saves the session, logs `"Session %s: mode switched to %s"`, returns `SetSessionModeResponse()`.
- **Inputs / options:** `mode_id: str`, `session_id: str`, `**kwargs`.
- **Outputs / side effects:** `SetSessionModeResponse()` or `None` for a missing session.
- **Rebuild notes:** Normalise unknown ids rather than erroring — ACP clients ship modes ahead of agents.

### ACP `session/set_config_option`  `id: acp-mcp-dev.acp-set-config-option`
- **Surface:** Core
- **What it does:** Accepts arbitrary ACP config-option updates; the one Hermes actually understands is `edit_approval_policy`.
- **How it works:** `set_config_option()` (`acp_adapter/server.py:2620-2641`). When `config_id == "edit_approval_policy"` (constant `_EDIT_APPROVAL_POLICY_CONFIG_ID`, default value `"ask"`), the value is mapped back to a mode via `_EDIT_APPROVAL_POLICY_TO_MODE` and stored as `state.mode`. Any other id is stashed verbatim in `state.config_options` (a dict created on demand). Always answers `SetSessionConfigOptionResponse(config_options=[])`.
- **Inputs / options:** `config_id: str`, `session_id: str`, `value: str`, `**kwargs`. Accepted `edit_approval_policy` values: `ask`, `workspace_session`, `session`.
- **Outputs / side effects:** Session saved; log `"Session %s: config option %s updated"`.
- **Edge cases / guards:** Missing session → `None` + warning. Unknown option ids are stored rather than rejected, so a newer client never fails against an older Hermes.
- **Rebuild notes:** Accept-and-store unknown options; that forward-compat choice is what keeps clients from erroring.

### ACP tool-call rendering (kinds, titles, locations)  `id: acp-mcp-dev.acp-tool-rendering`
- **Surface:** Core
- **Where:** The tool-call cards the editor draws inside a Hermes thread.
- **What it does:** Turns every Hermes tool invocation into an ACP `ToolCallStart` / `ToolCallProgress` with a kind, a human title, file locations, and formatted content.
- **How it works:** `acp_adapter/tools.py`. `TOOL_KIND_MAP` (`acp_adapter/tools.py:24-59`) maps tool → ACP `ToolKind`: `read_file→read`, `write_file→edit`, `patch→edit`, `search_files→search`, `terminal→execute`, `process→execute`, `execute_code→execute`, `todo→other`, `skill_view→read`, `skills_list→read`, `skill_manage→edit`, `web_search→fetch`, `web_extract→fetch`, `browser_navigate→fetch`, `browser_click→execute`, `browser_type→execute`, `browser_snapshot→read`, `browser_vision→read`, `browser_scroll→execute`, `browser_press→execute`, `browser_back→execute`, `browser_get_images→read`, `delegate_task→execute`, `vision_analyze→read`, `image_generate→execute`, `text_to_speech→execute`, `_thinking→think`; everything else defaults to `other` (`get_tool_kind`, `acp_adapter/tools.py:85`). `make_tool_call_id()` mints `tc-<12 hex>`. `build_tool_title()` (`acp_adapter/tools.py:95-190`) has bespoke titles for `terminal` ("terminal: <cmd>", 80-char cap), `read_file` ("read: <path>"), `write_file` ("write: <path>"), `patch` ("patch (<mode>): <path>"), `search_files` ("search: <pattern>"), `web_search` ("web search: <query>"), `web_extract` ("extract: <url> (+N)"), `process` ("process <action>: <sid>"), `delegate_task` ("delegate batch (N tasks)" or "delegate: <goal>"), `session_search` ("session search: <query>" / "recent sessions"), `memory` ("memory <action>: <target>"), `execute_code` ("python: <first line>"), `todo` ("todo (N items)"), `skill_view` ("skill view (name/file)"), `skills_list` ("skills list (<category>)"), `skill_manage` ("skill <action>: <target>", 64-char cap), `browser_navigate` ("navigate: <url>"), `browser_snapshot` ("browser snapshot"), `browser_vision` ("browser vision: <question[:50]>"), `browser_get_images` ("browser images"), `vision_analyze` ("analyze image: <question[:50]>"), `image_generate` ("generate image: <prompt[:50]>"), `cronjob` ("cron <action>: <job_id>"); anything else uses the raw tool name. `extract_locations()` (`acp_adapter/tools.py:1353`) emits `ToolCallLocation(path=args["path"], line=args.get("offset") or args.get("line"))`. `build_tool_start()` (`acp_adapter/tools.py:1058`) wraps `_build_tool_start` in a never-throw guard that degrades to a minimal valid start event. `build_tool_complete()` (`acp_adapter/tools.py:1320`) sets `status="failed"` when `_tool_result_failed()` says so, and suppresses `raw_output` for tools in `_POLISHED_TOOLS` or when the result is already structured JSON.
- **Inputs / options:** tool name + arguments dict + (on completion) the result string, function args and an optional pre-call snapshot.
- **Outputs / side effects:** `session/update` notifications carrying tool cards, diffs, and truncated text (`_truncate_text` default limit 5000 chars, `acp_adapter/tools.py:252`).
- **Per-tool result formatters (all in `acp_adapter/tools.py`):** `_format_todo_result` (265), `_format_read_file_result` (311), `_format_search_files_result` (338), `_format_execute_code_result` (397), `_format_skill_view_result` (443, with `_extract_markdown_headings` at 430, limit 8), `_format_skill_manage_result` (476), `_format_web_search_result` (506), `_format_web_extract_result` (526), `_format_process_result` (557), `_format_delegate_result` (604), `_format_session_search_result` (650), `_format_memory_result` (681), `_format_edit_result` (708), `_format_browser_result` (731), `_format_media_or_cron_result` (757), `_format_structured_value` (770), `_format_generic_structured_result` (860), `_build_polished_completion_content` (912), `_parse_unified_diff_content` (958, with `_strip_diff_prefix` at 951).
- **The `_POLISHED_TOOLS` set (raw output suppressed), verbatim (`acp_adapter/tools.py:62-83`):** `todo`, `memory`, `session_search`, `delegate_task`, `read_file`, `write_file`, `patch`, `search_files`, `terminal`, `process`, `execute_code`, `skill_view`, `skills_list`, `skill_manage`, `web_search`, `web_extract`, `browser_navigate`, `browser_click`, `browser_type`, `browser_press`, `browser_scroll`, `browser_back`, `browser_snapshot`, `browser_console`, `browser_get_images`, `browser_vision`, `vision_analyze`, `image_generate`, `text_to_speech`, `cronjob`, `send_message`, `clarify`, `discord`, `discord_admin`, `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`, `feishu_doc_read`, `feishu_drive_list_comments`, `feishu_drive_list_comment_replies`, `feishu_drive_reply_comment`, `feishu_drive_add_comment`, `kanban_create`, `kanban_show`, `kanban_comment`, `kanban_complete`, `kanban_block`, `kanban_request_review`, `kanban_request_changes`, `kanban_link`, `kanban_heartbeat`, `yb_query_group_info`, `yb_query_group_members`, `yb_search_sticker`, `yb_send_dm`, `yb_send_sticker`.
- **Edge cases / guards:** A malformed tool argument (non-string `command`/`path` from a model that ignored the schema) must never abort the render — hence the guard in `build_tool_start`.
- **Rebuild notes:** Map tools to a small kind enum, give each a bespoke one-line title, and always attach file locations so the editor can deep-link. A better version would stream incremental `tool_call_update`s for long-running commands instead of one completion event.

### ACP duplicate/parallel tool-call correlation (FIFO per tool name)  `id: acp-mcp-dev.acp-toolcall-fifo`
- **Surface:** Core
- **What it does:** Makes completion events attach to the right invocation when the same tool is called twice in one step or in parallel.
- **How it works:** `make_tool_progress_cb` keeps `tool_call_ids: Dict[str, Deque[str]]` — a FIFO queue of ACP tool-call ids per tool *name* (`acp_adapter/events.py:114-182`); a legacy `str` value is upgraded to a one-element deque in place. `make_step_cb` pops from the left when the agent reports the tool finished and deletes the key when the queue empties (`acp_adapter/events.py:209-259`).
- **Inputs / options:** n/a (internal).
- **Outputs / side effects:** Correct card↔result pairing in the editor.
- **Edge cases / guards:** Without the FIFO, completion events land on the wrong card (documented in `website/docs/developer-guide/acp-internals.md`).
- **Rebuild notes:** One queue per name, not one id per name.

### ACP plan panel from the `todo` tool  `id: acp-mcp-dev.acp-plan-updates`
- **Surface:** Core
- **Where:** Zed's first-class task/todo panel for the Hermes thread.
- **What it does:** Translates Hermes' `todo` tool result into a native ACP `plan` session update.
- **How it works:** `_build_plan_update_from_todo_result()` (`acp_adapter/events.py:39-84`). Parses the tool result JSON (tolerating a human hint appended after the object, via `_json_loads_maybe_prefix`, `acp_adapter/events.py:28`), requires a `todos` list, and emits `AgentPlanUpdate(session_update="plan", entries=[PlanEntry(content, priority="medium", status)])`. Status mapping: `pending→pending`, `in_progress→in_progress`, `completed→completed`, `cancelled→completed` with the content prefixed `"[cancelled] "` (ACP plans have no cancelled state, and dropping the entry would lose context on the client's full-list replacement). An empty `todos` list emits `entries=[]`.
- **Inputs / options:** the `todo` tool's result string.
- **Outputs / side effects:** One extra `session/update` right after the `todo` tool-call completion.
- **Edge cases / guards:** Non-dict items and empty `content` are skipped; a non-JSON result yields `None` (no plan update).
- **Rebuild notes:** Plans are full-list replacements — never emit a partial list.

### ACP permission bridge for dangerous commands  `id: acp-mcp-dev.acp-permission-bridge`
- **Surface:** Core
- **Where:** The editor's permission prompt shown when Hermes wants to run a dangerous shell command.
- **What it does:** Converts Hermes' approval prompt into an ACP `session/request_permission` with the right option set, and maps the answer back to Hermes' approval vocabulary.
- **How it works:** `acp_adapter/permissions.py`. `make_approval_callback(request_permission_fn, loop, session_id, timeout=60.0)` returns a *synchronous* callback matching `tools.approval.prompt_dangerous_approval()`'s signature. `_build_permission_options(allow_permanent, allow_session=True, smart_denied=False)` (`acp_adapter/permissions.py:41-79`) builds the list: always `allow_once` (kind `allow_once`, label "Allow once"); plus, when neither `smart_denied` nor `allow_session=False` (`once_only`), `allow_session` (kind `allow_always` because ACP has no session-scoped kind, label "Allow for session"), and — when `allow_permanent` — `allow_always` (kind `allow_always`, label "Allow always"); always `deny` (kind `reject_once`, label "Deny"); plus `deny_always` (kind `reject_always`, label "Deny always") when not `once_only` **and** the installed ACP SDK accepts that kind (probed by `_permission_option_supports_kind`). `_build_permission_tool_call()` builds a `ToolCallUpdate` with id `perm-check-<N>` (monotonic counter), title `"<description>: <command>"` (or just the command), `kind="execute"`, `status="pending"`, content `"<description>\n$ <command>"` (or `"$ <command>"`), and `raw_input={"command":…, "description":…}`. Option → Hermes mapping (`_OPTION_ID_TO_HERMES`, `acp_adapter/permissions.py:21-27`): `allow_once→"once"`, `allow_session→"session"`, `allow_always→"always"`, `deny→"deny"`, `deny_always→"deny"`.
- **Inputs / options:** `command: str`, `description: str`, keyword-only `allow_permanent: bool = True`, `allow_session: bool = True`, `smart_denied: bool = False`, plus `**_`.
- **Outputs / side effects:** Returns one of `"once" | "session" | "always" | "deny" | "timeout"`.
- **Edge cases / guards:** Scheduling failure → `"deny"`. Timeout after 60 s → the future is cancelled, a warning `"Permission request timed out after %ss"` is logged, and `"timeout"` (distinct from a user denial) is returned so callers can say "timed out without user response". An unknown `option_id` logs `"Permission request returned unknown option_id: %s"` and denies. A non-`AllowedOutcome` outcome denies. A gate that re-asks every time (`allow_session=False`, e.g. protected agent-instruction writes) collapses to the same two options as a Smart-DENY override so the editor never offers a scope Hermes discards (#81887).
- **Rebuild notes:** Bridge a blocking approval into an async request with `run_coroutine_threadsafe`; keep a distinct timeout verdict; probe the SDK for optional option kinds so an older client still works.

### ACP pre-execution edit approval (diff preview)  `id: acp-mcp-dev.acp-edit-approval`
- **Surface:** Core
- **Where:** The editor's "Approve edit: `<path>`" diff dialog before `write_file` / `patch` mutates a file.
- **What it does:** Shows the exact diff *before* the edit runs and blocks the tool when the user denies.
- **How it works:** `acp_adapter/edit_approval.py`. A `ContextVar` named `ACP_EDIT_APPROVAL_REQUESTER` holds the requester for the duration of one ACP run (CLI/gateway leave it unset and bypass the guard entirely). `build_edit_proposal(tool_name, arguments)` (`:178`) handles `write_file` (`_proposal_for_write_file`, requires `path` + `content`, reads the old text when the file exists) and `patch` in two modes: `mode="replace"` (`_proposal_for_patch_replace`, applies `tools.fuzzy_match.fuzzy_find_and_replace(old_text, old_string, new_string, replace_all)` to compute the new text; raises when no match) and `mode="patch"` (`_proposal_for_patch_v4a`, extracts paths from a V4A patch body with the regexes `^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(.+)$` and `^\*\*\*\s+Move\s+File:\s*(.+?)\s*->\s*(.+)$`, and surfaces the raw patch text as `new_text`). `maybe_require_edit_approval()` (`:233`) returns `None` to allow, or a JSON error string to block. `build_acp_edit_tool_call()` (`:264`) makes a `ToolCallUpdate` with id `edit-approval-<N>`, title `"Approve edit: <path>"`, `kind="edit"`, `status="pending"`, content `acp.tool_diff_content(path, old_text, new_text)` and `raw_input={"tool":…, "arguments":…}`. `make_acp_edit_approval_requester(request_permission_fn, loop, session_id, timeout=60.0, auto_approve_getter=None)` (`:286`) offers exactly two options: `allow_once` (kind `allow_once`, label "Allow edit") and `deny` (kind `reject_once`, label "Deny"); approval requires `outcome.outcome == "selected"` **and** `option_id == "allow_once"`.
- **Auto-approval policy:** `should_auto_approve_edit(proposal, policy, cwd)` (`:200`). `policy == "ask"` (`AUTO_APPROVE_ASK`) never auto-approves. `"session"` (`AUTO_APPROVE_SESSION`) auto-approves everything except sensitive paths. `"workspace_session"` (`AUTO_APPROVE_WORKSPACE`) auto-approves only under `tempfile.gettempdir()` (resolved, so `/private/tmp` on macOS and the per-user Temp dir on Windows both work) or under the session cwd. Sensitive paths always ask: any path component `.git` or `.ssh`, or a basename in `SENSITIVE_AUTO_APPROVE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}` (`:45`).
- **Inputs / options:** tool name + arguments; policy comes from the session mode (`acp-mcp-dev.acp-session-modes`).
- **Outputs / side effects:** Blocking returns `{"error": "Edit approval denied by ACP client; file was not modified."}`; a proposal that cannot be built returns `{"error": "Edit approval denied: could not prepare diff (<exc>)"}`. Auto-approved edits still render their diff inside `ToolCallStart` (`acp_adapter/events.py:166-179`).
- **Edge cases / guards:** Requester exceptions deny by default; timeouts deny; a non-file path raises `OSError("Cannot edit non-file path: <path>")`.
- **Rebuild notes:** Compute the post-edit text *before* running the tool so the diff is real, and fail closed. A better version would hold a content hash so a file changed between preview and apply re-prompts.

### ACP session provenance `_meta`  `id: acp-mcp-dev.acp-provenance`
- **Surface:** Core
- **Where:** `_meta.hermes.sessionProvenance` on new/load/resume responses.
- **What it does:** Lets an ACP client see how the editor-facing session id relates to Hermes' internal session ids across context-compaction rotations, without parsing status text or reading `state.db`.
- **How it works:** `acp_adapter/provenance.py`. `build_session_provenance(db, acp_session_id, current_hermes_session_id, previous_hermes_session_id=None)` reads the `sessions` row, walks `parent_session_id` up to `_MAX_WALK = 100` hops (cycle-guarded by a `seen` set) to find `rootHermesSessionId`, counts `compressionDepth` as the number of ancestors whose `end_reason == 'compression'`, and sets `sessionKind` to `"continuation"` when the *immediate* parent ended with `end_reason='compression'`, else `"root"`.
- **Outputs / side effects:** `{"hermes": {"sessionProvenance": {acpSessionId, currentHermesSessionId, rootHermesSessionId, parentHermesSessionId, sessionKind, compressionDepth, previousHermesSessionId?, reason?: "compression", creatorKind?: "compression"}}}`. `reason`/`creatorKind` are only added when the internal head rotated during the last turn.
- **Config / env:** none. Nothing new is persisted — every field is derived on demand.
- **Edge cases / guards:** Any DB error returns `None` and the `_meta` is simply omitted.
- **Rebuild notes:** Derive lineage from existing columns; put it under a vendor-namespaced `_meta` key so spec clients ignore it.

### ACP compaction-summary `_meta` markers  `id: acp-mcp-dev.acp-compaction-meta`
- **Surface:** Core
- **Where:** `_meta.hermes.compactionSummary` / `_meta.hermes.containsCompactionSummary` on replayed history chunks.
- **What it does:** Marks which replayed messages are (or contain) a context-compaction handoff summary so the client can style or collapse them without hiding real turns.
- **How it works:** `_history_summary_meta()` (`acp_adapter/server.py:1400-1432`) classifies the text with `ContextCompressor.classify_summary_content(text)`; when classification fails but the in-process `COMPRESSED_SUMMARY_METADATA_KEY` flag is set, it treats it as `"standalone"`. `"standalone"` → `{"hermes": {"compactionSummary": True}}` (the whole chunk is the summary — safe to collapse). `"merged"` → `{"hermes": {"containsCompactionSummary": True}}` (real preserved content followed by the summary — style it, but collapsing would hide content).
- **Outputs / side effects:** `field_meta` on `UserMessageChunk` / `AgentMessageChunk` during replay.
- **Edge cases / guards:** Summaries can be persisted under either `role="user"` or `role="assistant"` (the compressor picks whichever keeps alternation valid), so both roles are checked. Works for DB-reloaded sessions that lost the in-memory flag because classification is content-based.
- **Rebuild notes:** Two distinct keys, not one — a client must never collapse a merged-tail message.

### ACP history replay  `id: acp-mcp-dev.acp-history-replay`
- **Surface:** Core
- **What it does:** Streams a persisted transcript back to the editor as ACP updates: user messages, assistant messages, assistant thoughts, and tool calls with results.
- **How it works:** `_replay_session_history(state)` (`acp_adapter/server.py:1493+`). Text is normalised by `_flatten_history_text` (handles a scalar string, a list of `{"text": …}` parts, or `{"type":"text","content":…}` parts, joining with newlines and trimming; `acp_adapter/server.py:1353-1375`). `_history_message_text` reads `content`; `_history_reasoning_text` reads the first non-empty of `reasoning_content` then `reasoning` (both are live transports — DeepSeek/Moonshot and the chat-completions normalizer write the former, the codex event projector the latter). `_history_message_update` builds `UserMessageChunk` / `AgentMessageChunk` from a `TextContentBlock`; `_history_thought_update` uses `acp.update_agent_thought_text`. Tool calls are decoded by `_history_tool_call_name_args` (reads `function.name`/`function.arguments`, tolerating a JSON string or a raw fallback `{"raw": …}`) and `_history_tool_call_id` (first of `id`, `call_id`, `tool_call_id`).
- **Outputs / side effects:** A burst of `session/update` notifications inside the load/resume request.
- **Edge cases / guards:** Per-notification failures are caught inside the replay so one corrupt message cannot abort the transcript.
- **Rebuild notes:** Normalise every historical content shape you have ever persisted; a replay that throws is worse than a replay that skips.

### ACP usage and session-info updates  `id: acp-mcp-dev.acp-usage-update`
- **Surface:** Core
- **Where:** The editor's token/context meter for the thread.
- **What it does:** Pushes the session's token usage and session metadata to the client outside the request/response cycle.
- **How it works:** `_send_usage_update(state)` (`acp_adapter/server.py:1032`) and `_send_session_info_update(...)` (`acp_adapter/server.py:1071`), scheduled by `_schedule_usage_update()` after session creation/load/resume and awaited at the end of `prompt()`.
- **Outputs / side effects:** `session/update` notifications; also `Usage(input_tokens, output_tokens, total_tokens, thought_tokens, cached_read_tokens)` returned on `PromptResponse`.
- **Rebuild notes:** Report cached-read tokens separately — a client that adds them into input tokens misreports cost.

### ACP per-session MCP servers + late refresh  `id: acp-mcp-dev.acp-session-mcp`
- **Surface:** Core
- **Where:** The `mcpServers` array an editor sends on `session/new`, `session/load`, `session/resume`, `session/fork`.
- **What it does:** Lets the editor hand Hermes MCP servers that exist only for that session, on top of the ones in `config.yaml`, and picks up slow servers after the session has already started.
- **How it works:** `_register_session_mcp_servers(state, mcp_servers)` (`acp_adapter/server.py:1126+`) registers the editor-declared servers and expands the session's toolsets with `_expand_acp_enabled_toolsets(toolsets, mcp_server_names)` (`acp_adapter/session.py:140-155`), which appends a `mcp-<server_name>` toolset per server on top of the base `hermes-acp` toolset. Registration happens via `asyncio.to_thread` so the loop is not blocked. `_schedule_mcp_late_refresh(state)` re-reads the registry after discovery finishes, because the agent snapshots tools once at build time. At agent build, `hermes_cli.mcp_startup.ensure_mcp_discovery_before_agent_build()` does a bounded join on the background discovery thread (bounded by `mcp_discovery_timeout`, default ~1.5 s) and restarts discovery if the entry-point spawn never ran or ended with zero connected servers (`acp_adapter/session.py:670-694`).
- **Inputs / options:** the ACP `mcpServers` array; plus every enabled `mcp_servers.<name>` in `config.yaml` (filtered by `enabled is not False`, `acp_adapter/session.py:625-629`).
- **Outputs / side effects:** Extra toolsets on the session's agent; MCP subprocesses/HTTP sessions started.
- **Config / env:** `mcp_servers.*`, `mcp_discovery_timeout`, `HERMES_ACP_SKIP_CONFIGURED_MCP`.
- **Edge cases / guards:** A dead server cannot block session creation because the wait is bounded; servers that miss the bound arrive via the late refresh.
- **Rebuild notes:** Snapshot-at-build plus a late refresh is the whole trick; without the refresh a slow server is invisible for the entire session.

### ACP session persistence into `state.db`  `id: acp-mcp-dev.acp-session-persistence`
- **Surface:** Core
- **What it does:** Stores ACP sessions in the shared Hermes session database so they survive process restarts, show up in `session_search`, and can be reloaded by id.
- **How it works:** `SessionManager._get_db()` lazily builds `hermes_state.SessionDB(db_path=get_hermes_home()/"state.db")`, resolving `HERMES_HOME` on every call rather than trusting an import-time constant (`acp_adapter/session.py:401-421`). `_persist(state)` (`acp_adapter/session.py:423-506`) creates the row with `source="acp"`, `model=<str>`, `model_config={"cwd": …}` on first write, otherwise calls `update_session_meta(session_id, json.dumps({"cwd", "provider"?, "base_url"?, "api_mode"?}), model)`. Messages: when the agent owns persistence to the *same* DB (`agent._session_db is db and agent._session_db_created`), Hermes writes nothing — the agent already appended incrementally and `archive_and_compact()` preserved pre-compaction turns as `active=0, compacted=1` rows. Otherwise it calls `db.replace_messages(session_id, history, active_only=True)`, which replaces only the live set so archived rows survive a model switch or `/restore` (which mint an agent with `_session_db_created=False`). `_restore()` (`:509`) reloads a session and recreates the `AIAgent`; `_delete_persisted()` (`:589`) removes one.
- **Outputs / side effects:** Rows in `sessions` and `messages` of `$HERMES_HOME/state.db`.
- **Edge cases / guards:** `active_only=True` is unconditional by design — an existence probe (`has_archived_messages`) would fail *open* into the destructive full replace on any DB error and can race a concurrent `archive_and_compact` (the failure mode #80216's `/retry` fix avoids). Model values are coerced with `str()` so a test double cannot poison the column. All persistence failures are warnings, never exceptions.
- **Rebuild notes:** Never do a full-history replace next to an incremental writer; scope the replace to the active set.

### ACP working-directory binding and WSL translation  `id: acp-mcp-dev.acp-cwd`
- **Surface:** Core
- **What it does:** Makes file and terminal tools operate relative to the editor's workspace, including when the editor is on Windows and Hermes runs inside WSL.
- **How it works:** `_translate_acp_cwd(cwd)` calls `hermes_constants.translate_cwd_for_wsl_backend` so `E:\Projects` / `\\wsl.localhost\…` become POSIX paths (`acp_adapter/session.py:29-39`). `_register_task_cwd(task_id, cwd)` calls `tools.terminal_tool.register_task_env_overrides(task_id, {"cwd": <translated>})` (`acp_adapter/session.py:123-137`); `_clear_task_cwd` removes it (`:158`). The agent additionally gets `agent.session_cwd = cwd` so the lazily-spawned Codex app-server session starts from the editor workspace rather than the Hermes daemon's process cwd, and `agent._print_fn = _acp_stderr_print` so any incidental human-readable output goes to stderr instead of corrupting the ACP wire (`acp_adapter/session.py:690-696`, helper at `:112-121`).
- **Outputs / side effects:** Task-scoped env overrides in the terminal tool registry.
- **Edge cases / guards:** Failures to register/clear the override are debug-logged only.
- **Rebuild notes:** Bind cwd per session id, not process-wide, or two editor windows fight.

### `hermes-acp` toolset  `id: acp-mcp-dev.acp-toolset`
- **Surface:** Toolset
- **Where:** `toolsets.py` → `hermes-acp`; also visible in `hermes tools`.
- **What it does:** Defines the coding-focused tool surface an ACP session gets — no messaging, audio, or clarify UI.
- **How it works:** Registered as `hermes-acp` with description "Editor integration (VS Code, Zed, JetBrains) — coding-focused tools without messaging, audio, or clarify UI" and no `includes`.
- **Inputs / options:** The 29 tools, verbatim: `web_search`, `web_extract`, `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `vision_analyze`, `skills_list`, `skill_view`, `skill_manage`, `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_press`, `browser_get_images`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog`, `browser_exec`, `todo`, `memory`, `session_search`, `execute_code`, `delegate_task`.
- **Outputs / side effects:** Every ACP agent is built with `enabled_toolsets=_expand_acp_enabled_toolsets(["hermes-acp"], mcp_server_names=<configured enabled servers>)`.
- **Rebuild notes:** Editor agents should not get `send_message`/`clarify`/`text_to_speech`; the editor owns that UX.

### ACP benign liveness-probe log filter  `id: acp-mcp-dev.acp-probe-filter`
- **Surface:** Core
- **What it does:** Stops periodic `ping`/`health`/`healthcheck` probes from spamming stderr with tracebacks while keeping the protocol answer intact.
- **How it works:** `_BenignProbeMethodFilter` (`acp_adapter/entry.py:52-78`) drops only `logging` records whose message is exactly `"Background task failed"` **and** whose exception is an `acp.exceptions.RequestError` with `code == -32601` and `data["method"]` in `_BENIGN_PROBE_METHODS = {"ping", "health", "healthcheck"}` (`acp_adapter/entry.py:49`). Everything else — including `method_not_found` for any non-probe method — stays visible.
- **Outputs / side effects:** Quieter stderr; the JSON-RPC `-32601` response is unchanged, which clients like `acp-bridge` already read as "agent alive".
- **Rebuild notes:** Filter the log, never the protocol answer.

### ACP ↔ OpenAI tool bridge (`agent/acp_openai_bridge.py`)  `id: acp-mcp-dev.acp-openai-bridge`
- **Surface:** Core
- **Where:** Used by every Hermes *client* that talks to an ACP agent as if it were an OpenAI chat backend (`agent/copilot_acp_client.py`, and ACP CLIs configured as Hermes providers).
- **What it does:** ACP has no OpenAI-style `tools`/`tool_calls` channel, so this module carries tool schemas *into* the prompt as text and parses tool calls back *out* of the response text.
- **How it works:** `render_tool_bridge_sections(tools, tool_choice=None, allowlist=None)` (`agent/acp_openai_bridge.py:188-208`) flattens OpenAI `tools` into `{name, description, parameters}` specs via `tool_specs_from_openai_tools` (optionally filtered by an allowlist) and emits one section containing `TOOL_CALL_CONTRACT` + the JSON specs, plus an optional `"Tool choice hint: <json>"` section. `TOOL_CALL_CONTRACT` verbatim (`:52-56`): "Available tools (OpenAI function schema). When using a tool, emit ONLY <tool_call>{...}</tool_call> with one JSON object containing id/type/function{name,arguments}. arguments must be a JSON string." `extract_tool_calls_from_text(text)` (`:211-287`) first scans `TOOL_CALL_BLOCK_RE = <tool_call>\s*(\{.*?\})\s*</tool_call>` (DOTALL); only when that finds nothing does it fall back to the bare-JSON `TOOL_CALL_JSON_RE`. Consumed spans are merged and stripped so the assistant message never shows raw JSON. Missing/blank ids become `acp_call_<n>`; non-string `arguments` are re-serialised. `completion_to_stream_chunks(completion)` (`:82-134`) re-shapes a one-shot ACP response into two OpenAI stream chunks (a delta chunk carrying `role`, `content`, `tool_calls`, `reasoning_content`, `reasoning`, `finish_reason`, then a usage-only chunk) inside a `StreamChunks` list subclass that also copies every other response-level attribute (e.g. `hermes_projected_messages`, consumed by `agent/provider_projection.py`) so nothing is lost on the `stream=True` path.
- **Inputs / options:** `tools: list[dict] | None`, `tool_choice: Any`, `allowlist: Iterable[str] | None`; `text: str`; `completion: SimpleNamespace`.
- **Outputs / side effects:** `(tool_calls, cleaned_text)`; `StreamChunks`; prompt sections. Exports `TOOL_CALL_BLOCK_RE`, `TOOL_CALL_JSON_RE`, `TOOL_CALL_CONTRACT`, `StreamChunks`, `build_openai_tool_call`, `tool_specs_from_openai_tools`, `render_tool_bridge_sections`, `extract_tool_calls_from_text`, `completion_to_stream_chunks`.
- **Edge cases / guards:** Malformed spec entries are skipped. Allowlisting exists because a CLI that is itself an autonomous agent must only be offered Hermes' *agent-level* tools — re-offering the overlapping read/edit/execute tools makes Hermes re-run work the agent already did (`agent/acp_openai_bridge.py:25-30`).
- **Rebuild notes:** Prompt-carried tool schemas + regex extraction is the only way to bridge a text-only agent protocol into a function-calling loop; always strip the consumed blocks from the visible text.

### GitHub Copilot ACP client (Hermes as an ACP *client*)  `id: acp-mcp-dev.copilot-acp-client`
- **Surface:** Provider
- **Where:** Selected as a Hermes model backend; marker base URL `acp://copilot`.
- **What it does:** Lets Hermes use the GitHub Copilot CLI (`copilot --acp --stdio`) as a chat-style backend by driving it over ACP and shaping the result like an OpenAI completion.
- **How it works:** `agent/copilot_acp_client.py`. Command resolution: `HERMES_COPILOT_ACP_COMMAND` → `COPILOT_CLI_PATH` → `"copilot"` (`:59-64`); args from `HERMES_COPILOT_ACP_ARGS` (shlex-split) else `["--acp", "--stdio"]` (`:67-70`). Before spawning, `_acp_supported()` (`:82-126`) runs `<command> --help` with a 5 s timeout and searches the help text for `(?:^|[\s\[])--acp(?:[\s=\],]|$)`; the verdict is cached per binary path (only definitive True/False, so a CLI installed mid-session is still picked up), and only probed when `--acp` is actually in the args. Environment: `hermes_subprocess_env(inherit_credentials=True)` (a model-driving CLI legitimately needs LLM provider credentials, but Tier-1 secrets — gateway bot tokens, GitHub auth, infra — are still stripped, #29157) plus a resolved `HOME` (`$HOME` → `expanduser("~")` → `pwd.getpwuid` → `/tmp`) and `apply_subprocess_home_env` (`:128-162`). The JSON-RPC dance (`:474-580`): `initialize` with `{"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": true, "writeTextFile": true}}, "clientInfo": {"name": "hermes-agent", "title": "Hermes Agent", "version": "0.0.0"}}`, then `session/new` with `{"cwd": <resolved cwd>, "mcpServers": []}`, then `session/prompt` with a single text part. Server→client messages (`_handle_server_message`, `:583+`): `session/update` accumulates `agent_message_chunk` text into the response and `agent_thought_chunk` text into reasoning; `session/request_permission` is answered `{"outcome": {"outcome": "cancelled"}}` (always denied — there is no human channel); `fs/read_text_file` is served from disk, confined to the session cwd by `_ensure_path_within_cwd`, blocked by `agent.file_safety.get_read_block_error`, honouring `line`/`limit` slicing, and redacted with `agent.redact.redact_sensitive_text(content, force=True)`; `fs/write_text_file` is served but denied by `get_write_denied_error` and additionally **fails closed** for any path where `is_write_approval_required` is true ("Write denied: '<path>' requires interactive approval and cannot be written through the ACP file bridge."); any other method returns `-32601` "ACP client method '<method>' is not supported by Hermes yet."
- **Inputs / options:** constructor `api_key` (default `"copilot-acp"`), `command`/`args`, `acp_command`, `acp_args`, `acp_cwd` (default resolved `os.getcwd()`); `_DEFAULT_TIMEOUT_SECONDS = 900.0`.
- **Outputs / side effects:** An OpenAI-shaped completion (`model` defaults to `"copilot-acp"`); files read/written inside the session cwd; a short-lived `copilot` subprocess per request.
- **Config / env:** `HERMES_COPILOT_ACP_COMMAND`, `COPILOT_CLI_PATH`, `HERMES_COPILOT_ACP_ARGS`, `HOME`, `HERMES_HOME`.
- **Edge cases / guards:** When the probe says `--acp` is unsupported, Hermes fast-fails instead of hanging for `child_timeout_seconds` (`:406-414`). When stderr matches the deprecated `gh copilot` extension banner — it must contain `"gh-copilot"` **and** one of `"has been deprecated"` / `"no commands will be executed"` (`:43-56`) — the error explains how to install `@github/copilot`, how to point `HERMES_COPILOT_ACP_COMMAND` at it, and offers the non-ACP `copilot` provider as an alternative. Timeouts raise `TimeoutError("Timed out waiting for Copilot ACP response to <method>.")`.
- **Rebuild notes:** Probe before spawn, deny permissions, confine and redact the fs bridge, and keep a one-shot session per request. A better version would keep the session warm across turns and surface permission requests to the operator instead of auto-denying.

---

## 2. MCP — Model Context Protocol (Hermes as a client)

### `hermes mcp` — MCP command group  `id: acp-mcp-dev.mcp-root`
- **Surface:** CLI
- **Where:** `hermes mcp [--accept-hooks] {serve,add,remove,rm,list,ls,test,configure,config,login,reauth,picker,catalog,install}`.
- **What it does:** One command group for managing MCP server connections and for running Hermes itself as an MCP server. Bare `hermes mcp` (no subcommand) opens the interactive picker.
- **How it works:** Parser built in `hermes_cli/main.py`; handlers in `hermes_cli/mcp_config.py` (`mcp_command()` at `hermes_cli/mcp_config.py:1142`), `hermes_cli/mcp_catalog.py`, `hermes_cli/mcp_picker.py`, and `mcp_serve.py`. `hermes_cli/main.py:12523` marks `"mcp": ("mcp_action", {"serve"})` so `serve` is treated as an early/lightweight action.
- **Inputs / options:** `-h, --help`; `--accept-hooks`; the 13 subcommand names above (with aliases `rm`→`remove`, `ls`→`list`, `config`→`configure`).
- **Outputs / side effects:** Depends on subcommand; the persistent state is `mcp_servers.*` in `~/.hermes/config.yaml`, secrets in `~/.hermes/.env`, and OAuth tokens in `~/.hermes/mcp-tokens/`.
- **Description text, verbatim:** "Manage MCP server connections and run Hermes as an MCP server. MCP servers provide additional tools via the Model Context Protocol. Use 'hermes mcp add' to connect to a new server, or 'hermes mcp serve' to expose Hermes conversations over MCP."
- **Rebuild notes:** Keep add/remove/list/test/configure/login as the core five; everything else is UX sugar over the same config file.

### `hermes mcp add` — discovery-first install  `id: acp-mcp-dev.mcp-add`
- **Surface:** CLI
- **Where:** `hermes mcp add <name> [--url URL] [--command MCP_COMMAND] [--args ...] [--auth {oauth,header}] [--preset PRESET] [--connect-timeout N] [--env KEY=VALUE ...]`.
- **What it does:** Adds an MCP server to `config.yaml`, connecting to it first so the user can see (and prune) the tools it exposes before saving.
- **How it works:** `cmd_mcp_add()` (`hermes_cli/mcp_config.py:438-635`). Order: parse `--env` assignments (`_parse_env_assignments`, validates `KEY=VALUE` and the name regex `^[A-Za-z_][A-Za-z0-9_]*$`); apply a preset when transport flags are omitted (`_apply_mcp_preset`); reject `--env` for URL servers ("--env is only supported for stdio MCP servers (--command or stdio presets)"); require a transport; confirm overwrite when the name exists; build the entry; run `hermes_cli.mcp_security.validate_mcp_server_entry(name, cfg)` and refuse to save on any finding ("Server '<name>' was NOT saved due to suspicious configuration."); then auth; then probe; then tool selection; then save with `enabled: true`.
- **Inputs / options:** positional `name` (used as the config key); `--url URL` (HTTP/SSE endpoint); `--command MCP_COMMAND` (stdio command, e.g. `npx`; argparse `dest="mcp_command"`); `--args ...` (`nargs=argparse.REMAINDER`, must be last; a leading `--` is stripped); `--auth {oauth,header}`; `--preset PRESET` (known presets: `codex` → `{"command": "codex", "args": ["mcp-server"]}`, `hermes_cli/mcp_config.py:36-42`); `--connect-timeout CONNECT_TIMEOUT` (seconds for the initial connection and tool discovery); `--env [KEY=VALUE ...]`.
- **Auth flow:** With `--auth oauth` on a URL server it calls `tools.mcp_oauth_manager.get_manager().get_or_build_provider(name, url, cfg.get("oauth"))` and stores `auth: oauth` ("OAuth configured (tokens will be acquired on first connection)"); on failure it warns "OAuth setup failed — MCP SDK auth module not available" / "OAuth error: …" and offers "Continue without authentication?". With `--auth header` (or no `--auth`) on a URL server it asks "Does this server require authentication?", prompts for "API key / Bearer token" (hidden), strips a pasted `Bearer ` prefix (`_strip_bearer_prefix`, #37792), writes the secret to `.env` under `MCP_<NAME>_API_KEY` (`_env_key_for_server`: uppercase, non-alphanumerics → `_`, stripped), and stores `headers: {"Authorization": "Bearer ${MCP_<NAME>_API_KEY}"}` in `config.yaml`.
- **Tool selection:** After a successful probe it prints `Connected! Found N tool(s) from '<name>':` and the tool/description table, then asks `Enable all N tools? [Y/n/select]:`. `n`/`no` → "Cancelled — server not saved."; `s`/`select` → a curses checklist (`hermes_cli.curses_ui.curses_checklist`) with everything pre-selected, writing the chosen names to `tools.include`; anything else enables all (no filter written).
- **Outputs / side effects:** `Saved '<name>' to <hermes home>/config.yaml (N/M tools enabled)` and "Start a new session to use these tools." A failed connect offers "Save config anyway (you can test later)?" and, if accepted, writes the entry with `enabled: false` plus the hint `Fix the issue, then: hermes mcp test <name>`. A server that connects but reports no tools warns "Server connected but reported no tools." and offers to save anyway.
- **Config / env:** writes `mcp_servers.<name>` (`url` | `command`+`args`+`env`, `headers`, `auth`, `connect_timeout`, `tools.include`, `enabled`); writes `MCP_<NAME>_API_KEY` into `~/.hermes/.env`.
- **Edge cases / guards:** Ctrl-C / EOF at the enable prompt cancels. `${VAR}` header templates are resolved before probing via `_resolve_mcp_server_config` so a freshly-saved key works immediately.
- **Rebuild notes:** Probe before persisting; store the secret in `.env` and only the interpolation template in the config; validate for shell-persistence/exfil shapes at save time.

### `hermes mcp remove` (alias `rm`)  `id: acp-mcp-dev.mcp-remove`
- **Surface:** CLI
- **Where:** `hermes mcp remove <name>`.
- **What it does:** Deletes an MCP server entry from `config.yaml` and cleans up its OAuth tokens.
- **How it works:** `cmd_mcp_remove()` (`hermes_cli/mcp_config.py:645-675`). Unknown name → `Server '<name>' not found in config.` plus `Available servers: …`. Confirms `Remove server '<name>'?` (default yes), removes the entry, prints `Removed '<name>' from config`, then calls `tools.mcp_oauth_manager.get_manager().remove(name)` so both the on-disk tokens and any provider cached in this process are evicted, printing `Cleaned up OAuth tokens`.
- **Inputs / options:** positional `name`.
- **Outputs / side effects:** `config.yaml` edited; `~/.hermes/mcp-tokens/<name>.json` (and `.cimd-off`) removed.
- **Edge cases / guards:** Token cleanup failures are swallowed.
- **Rebuild notes:** Route token cleanup through the manager, not the filesystem, or an in-process cached provider resurrects the credentials.

### `hermes mcp list` (alias `ls`)  `id: acp-mcp-dev.mcp-list`
- **Surface:** CLI
- **Where:** `hermes mcp list`.
- **What it does:** Prints a table of configured MCP servers with transport, tool-filter summary and enabled status.
- **How it works:** `cmd_mcp_list()` (`hermes_cli/mcp_config.py:677-739`). Header `MCP Servers:` then the columns `Name` (16), `Transport` (30), `Tools` (12), `Status` (10) with a box-drawing rule. Transport is the URL (truncated at 25 + `...`) for HTTP servers, or `<command> <first two args>` for stdio, else `?`. Tools shows `N selected` when `tools.include` is a list, `-N excluded` when only `tools.exclude` is, else `all`. Status is a green `✓ enabled` or dim `✗ disabled`; a string `enabled` value is parsed as true for `{"true","1","yes"}`.
- **Inputs / options:** none.
- **Outputs / side effects:** stdout only. With nothing configured it prints "No MCP servers configured." plus `hermes mcp add <name> --url <endpoint>` and `hermes mcp add <name> --command <cmd> --args <args...>`.
- **Rebuild notes:** Read-only; never connect.

### `hermes mcp test`  `id: acp-mcp-dev.mcp-test`
- **Surface:** CLI
- **Where:** `hermes mcp test <name>`.
- **What it does:** Connects to one configured server, times the connect, and lists the tools it discovers.
- **How it works:** `cmd_mcp_test()` (`hermes_cli/mcp_config.py:746-806`). Prints `Testing '<name>'...`, then `Transport: HTTP → <url>` or `Transport: stdio → <command>`; then auth: `Auth: OAuth 2.1 PKCE` when `auth: oauth`, or each header whose name contains `key`/`auth` masked as `<first4>***<last4>` (or `***` when ≤8 chars) after resolving `${VAR}` / `${env:VAR}`, or `Auth: none`. Then `_probe_single_server()` with a monotonic timer.
- **Inputs / options:** positional `name`.
- **Outputs / side effects:** `Connected (<ms>ms)` + `Tools discovered: N` + the tool/description list (descriptions truncated at 55 chars), or `Connection failed (<ms>ms): <error>`.
- **Edge cases / guards:** Unknown server → `Server '<name>' not found in config.` + `Available: …`.
- **Rebuild notes:** Mask credentials in the diagnostic output; report connect latency so a slow server is visible.

### `hermes mcp configure` (alias `config`)  `id: acp-mcp-dev.mcp-configure`
- **Surface:** CLI
- **Where:** `hermes mcp configure <name>`.
- **What it does:** Re-opens the tool checklist for an already-configured server so the user can change which of its tools are exposed.
- **How it works:** `cmd_mcp_configure()` (`hermes_cli/mcp_config.py:987+`). Hard-requires a TTY: without one it prints `Error: 'hermes mcp configure' requires an interactive terminal.` to stderr and exits 1. Re-probes the server, renders the curses checklist pre-selecting the currently-included tools, and rewrites `tools.include`.
- **Inputs / options:** positional `name`.
- **Outputs / side effects:** `mcp_servers.<name>.tools.include` rewritten.
- **Edge cases / guards:** Unknown name → error + `Available: …`.
- **Rebuild notes:** Re-probe rather than trusting the last cached list, so newly added server tools appear.

### `hermes mcp login`  `id: acp-mcp-dev.mcp-login`
- **Surface:** CLI
- **Where:** `hermes mcp login <name>`.
- **What it does:** Forces a fresh OAuth flow for one server — wiping cached tokens on disk *and* in the running process — and verifies a token actually landed.
- **How it works:** `cmd_mcp_login()` → `_reauth_oauth_server()` (`hermes_cli/mcp_config.py:810-908`). Requires `url` and `auth: oauth` (otherwise `Server '<name>' has no URL — not an OAuth-capable server` / `Server '<name>' is not configured for OAuth (auth=<value>)` plus "Use `hermes mcp remove` + `hermes mcp add` to reconfigure auth."). Calls `get_manager().remove(name)`, then re-probes inside `tools.mcp_oauth.force_interactive_oauth()` (so a non-TTY desktop/agent-spawned terminal can still open a browser) with a connect timeout of `max(server connect_timeout, 315.0)` seconds — the 300 s OAuth callback window plus headroom, matching the dashboard path.
- **Inputs / options:** positional `name`.
- **Outputs / side effects:** Browser opened; `~/.hermes/mcp-tokens/<name>.json` written; `Authenticated — N tool(s) available` or `Authenticated (server reported no tools)`. Also clears any recorded CIMD rejection so a corrected document gets another chance.
- **Edge cases / guards:** A clean probe is *not* proof of auth — some servers (Google Drive) serve `initialize` + `tools/list` without auth. `_oauth_tokens_present(name)` must confirm a token on disk, otherwise it warns "Server responded, but no OAuth token was obtained — authentication did not complete." and prints a copy-pasteable `mcp_servers:` snippet showing where to put a manually-created `oauth.client_id` / `oauth.client_secret`, ending with `Then re-run `hermes mcp login <name>`.`. Errors are humanised through `tools.mcp_oauth.humanize_oauth_registration_error`.
- **Rebuild notes:** Verify the token file, never the probe result.

### `hermes mcp reauth`  `id: acp-mcp-dev.mcp-reauth`
- **Surface:** CLI
- **Where:** `hermes mcp reauth [<name>] [--all]`.
- **What it does:** Re-authenticates one OAuth MCP server (identical to `login`) or every configured OAuth server, strictly one at a time.
- **How it works:** `cmd_mcp_reauth()` (`hermes_cli/mcp_config.py:935-984`). `--all` selects every server with `auth == "oauth"` and a `url`, prints `Re-authenticating N OAuth server(s) one at a time...`, then loops with a `── <name> ──` banner per server, ending with `Re-authenticated X/N server(s)`.
- **Inputs / options:** optional positional `name`; `--all`.
- **Outputs / side effects:** Same as login, per server.
- **Edge cases / guards:** Serial by design — a human can only complete one browser flow at a time, so concurrency would open N tabs and time out N−1 (GH#36767). With neither name nor `--all`: `Specify a server name, or use --all to re-auth every OAuth server.` + `Usage: hermes mcp reauth <name>   |   hermes mcp reauth --all`. No OAuth servers → `No OAuth-based MCP servers found in config.`
- **Rebuild notes:** Serialise; report a success ratio.

### `hermes mcp picker` (and bare `hermes mcp`)  `id: acp-mcp-dev.mcp-picker`
- **Surface:** CLI
- **Where:** `hermes mcp picker` or just `hermes mcp`.
- **What it does:** An arrow-key catalogue browser that lists every Nous-approved MCP plus the user's own custom servers, and routes ENTER to the right action for that row's state.
- **How it works:** `hermes_cli/mcp_picker.py`. Rows unify catalog entries (`hermes_cli.mcp_catalog.list_catalog`) and custom entries from `mcp_servers`. Status badges, verbatim (`hermes_cli/mcp_picker.py:43-48`): `available` (not installed), `installed (disabled)`, `enabled`, `custom — enabled`, `custom — disabled`. ENTER behaviour by state: not installed → install (clone/bootstrap if needed, prompt for credentials); installed but disabled → enable; installed and enabled → a submenu of *configure tools / disable / uninstall / reinstall*; custom row → a submenu of *configure tools / enable / disable / remove*. The picker loops until ESC/`q`.
- **Inputs / options:** arrow keys, ENTER, ESC/`q`; uses `hermes_cli.curses_ui.curses_single_select` and `hermes_cli.cli_output.prompt_yes_no`.
- **Outputs / side effects:** Same config/env writes as `add`/`remove`/`configure`.
- **Edge cases / guards:** Catalog parse problems surface through `catalog_diagnostics()` (per-entry `future_manifest` / `invalid` reasons).
- **Rebuild notes:** One list, two row kinds, state-dependent action — that is the whole UX.

### `hermes mcp catalog`  `id: acp-mcp-dev.mcp-catalog`
- **Surface:** CLI
- **Where:** `hermes mcp catalog`.
- **What it does:** Prints the Nous-approved MCP catalogue (65 entries in v2026.8.31) alongside the user's configured servers, with an install hint.
- **How it works:** `hermes_cli/mcp_catalog.py`. Entries are directories under `optional-mcps/<name>/` resolved by `get_optional_mcps_dir(Path(__file__).parent.parent / "optional-mcps")` (`hermes_cli/mcp_catalog.py:172`); presence in that directory *is* approval (merged via PR review). Output columns: `Name` (18), `Status` (24), `Description`. `_CATALOG_DIAGNOSTICS` records per-entry `future_manifest` / `invalid` problems (`hermes_cli/mcp_catalog.py:386-420`).
- **Inputs / options:** none.
- **Outputs / side effects:** stdout; footer `Install: hermes mcp install <name>    Picker: hermes mcp`.
- **Edge cases / guards:** An entry whose `manifest_version` is newer than this Hermes is reported as `future_manifest` rather than crashing the listing.
- **Rebuild notes:** Directory-as-registry with a YAML manifest per entry; keep approval a review artifact, not a runtime fetch. *(The 65 individual catalogue entries are documented in the `optional` shard.)*

### `hermes mcp install`  `id: acp-mcp-dev.mcp-install`
- **Surface:** CLI
- **Where:** `hermes mcp install <identifier>` (e.g. `hermes mcp install n8n`).
- **What it does:** One-click install of a catalogue MCP: writes the server entry from the manifest, prompts for any credentials, probes for tools and offers the tool checklist.
- **How it works:** `hermes_cli.mcp_catalog.install_entry()`; `get_entry(name)` accepts a bare name or the `official/<name>` prefix (`hermes_cli/mcp_catalog.py:424-426`).
- **Inputs / options:** positional `identifier` — "Catalog entry name (or `official/<name>`)".
- **Outputs / side effects:** `mcp_servers.<name>` written; any `post_install` text from the manifest printed.
- **Edge cases / guards:** `CatalogError` for an unknown identifier.
- **Rebuild notes:** Make the manifest carry transport + auth + optional `tools.default_enabled` + `post_install` prose so install is data-driven.

### `mcp_servers` root config shape  `id: acp-mcp-dev.mcp-config-root`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `mcp_servers:` mapping of server name → entry; reference page `website/docs/reference/mcp-config-reference.md`.
- **What it does:** Declares every MCP server Hermes connects to at startup, and how its tools are filtered.
- **How it works:** Loaded by `tools/mcp_tool.py:_load_mcp_config()` (`:5759`), filtered by `_filter_suspicious_mcp_servers()` (`:5732`), then `register_mcp_servers()` (`:7639`) spawns one long-lived asyncio Task per server on a dedicated background event loop (`_ensure_mcp_loop`, `:5496`) in a daemon thread; tool calls are scheduled onto it with `run_coroutine_threadsafe` (`_run_on_mcp_loop`, `:5564`). Server state is protected by a module `_lock`.
- **Inputs / options:** the per-key entries documented individually below.
- **Outputs / side effects:** One `mcp-<server>` runtime toolset per server with tools named `mcp__<server>__<tool>`.
- **Edge cases / guards:** If filtering removes every server-native tool *and* no utility tool is registered, Hermes does not create an empty runtime toolset for that server.
- **Rebuild notes:** One background loop + one task per server, with the transport context opened and closed in the same task (anyio requires it).

### MCP server key: `command`  `id: acp-mcp-dev.mcp-key-command`
- **Surface:** Config
- **What it does:** The executable to launch for a stdio MCP server.
- **How it works:** Resolved by `_resolve_stdio_command(command, env)` (`tools/mcp_tool.py:1001`) and, on POSIX, wrapped by `_wrap_command_with_watchdog` (`:1069`) into `python3 -m tools.mcp_stdio_watchdog --ppid <pid> -- <command> <args…>`.
- **Inputs / options:** string.
- **Edge cases / guards:** Shell-interpreter commands (`bash`, `sh`, `zsh`, `dash`, `fish`, `cmd`, `cmd.exe`, `powershell`, `powershell.exe`, `pwsh`, `pwsh.exe`) whose inline script matches the egress or persistence patterns are refused — see `acp-mcp-dev.mcp-security-validator`.
- **Rebuild notes:** Never pass the command through a shell; always argv.

### MCP server key: `args`  `id: acp-mcp-dev.mcp-key-args`
- **Surface:** Config
- **What it does:** Argument list for the stdio command.
- **Inputs / options:** list of strings; `${VAR}` / `${env:VAR}` / context variables are interpolated.
- **Rebuild notes:** Keep it a list, never a string — a string invites shell splitting.

### MCP server key: `env`  `id: acp-mcp-dev.mcp-key-env`
- **Surface:** Config
- **What it does:** Extra environment variables for a stdio subprocess.
- **How it works:** `_build_safe_env(user_env)` (`tools/mcp_tool.py:735`) starts from an allowlist, not from the parent environment: `_SAFE_ENV_KEYS = {PATH, HOME, USER, LANG, LC_ALL, TERM, SHELL, TMPDIR}` (`:619-621`) plus, case-insensitively on Windows, `_SAFE_ENV_KEYS_CASE_INSENSITIVE` = `ALLUSERSPROFILE, APPDATA, COMMONPROGRAMFILES, COMMONPROGRAMFILES(X86), COMMONPROGRAMW6432, COMPUTERNAME, COMSPEC, HOMEDRIVE, HOMEPATH, LOCALAPPDATA, NUMBER_OF_PROCESSORS, OS, PATHEXT, PROCESSOR_ARCHITECTURE, PROGRAMDATA, PROGRAMFILES, PROGRAMFILES(X86), PROGRAMW6432, PUBLIC, SYSTEMDRIVE, SYSTEMROOT, TEMP, TMP, USERDOMAIN, USERNAME, USERPROFILE, WINDIR` (`:623-653`), then merges the user's `env`.
- **Inputs / options:** mapping of name → value (values support `${VAR}` interpolation).
- **Edge cases / guards:** `--env` on `hermes mcp add` is rejected for URL servers. Portable Agent-Plugin `mcp.json` `env` values are *visible package data*, not secret storage.
- **Rebuild notes:** Allowlist the inherited environment; a stdio MCP server should not see your provider keys by default.

### MCP server key: `url`  `id: acp-mcp-dev.mcp-key-url`
- **Surface:** Config
- **What it does:** The remote MCP endpoint for an HTTP/Streamable-HTTP (or SSE) server.
- **How it works:** Validated by `_validate_remote_mcp_url(server_name, url)` (`tools/mcp_tool.py:1459`), which raises `InvalidMcpUrlError`; a non-MCP endpoint raises `NonMcpEndpointError` (`:1365`).
- **Inputs / options:** string URL.
- **Edge cases / guards:** Portable Agent-Plugin v1 `streamable-http` entries additionally require an absolute http(s) URL with no userinfo and no fragment, and plain HTTP only for `localhost`/loopback.
- **Rebuild notes:** Validate the URL before opening a socket, and refuse a bare origin.

### MCP server key: `headers`  `id: acp-mcp-dev.mcp-key-headers`
- **Surface:** Config
- **What it does:** Extra HTTP headers for a remote server (typically `Authorization`).
- **How it works:** Values are `${VAR}`-interpolated at connect time. A redirect-header stripper (`_make_redirect_header_stripper`, `tools/mcp_tool.py:1659`) removes configured headers when a redirect crosses origins.
- **Inputs / options:** mapping name → value.
- **Edge cases / guards:** `hermes mcp add --auth header` writes the *template* `Authorization: Bearer ${MCP_<NAME>_API_KEY}` and puts the secret in `.env`.
- **Rebuild notes:** Never forward auth headers across a cross-origin redirect.

### MCP server key: `identity_header`  `id: acp-mcp-dev.mcp-key-identity-header`
- **Surface:** Config
- **What it does:** Attaches a per-user identity header to this server's HTTP/SSE requests.
- **How it works:** `_resolve_identity_header()` / `_apply_identity_header()` (`tools/mcp_tool.py:1584-1657`). Shape: `identity_header: {name: "X-User-Id", value_from: "static"|"profile", value: "alice"}`. `value_from` defaults to `static` and then requires a non-empty string `value`; `profile` resolves once at connect time to `hermes_cli.profiles.get_active_profile_name()`.
- **Inputs / options:** `name` (required, non-empty string), `value_from` (`static` | `profile`, default `static`), `value` (required for `static`).
- **Edge cases / guards:** An explicit `headers` entry with the same name (any casing) wins. Every invalid shape warns and is ignored — an identity header must never break the connection. No per-call mutation.
- **Rebuild notes:** Resolve once at connect; make explicit headers authoritative.

### MCP server key: `ssl_verify`  `id: acp-mcp-dev.mcp-key-ssl-verify`
- **Surface:** Config
- **What it does:** Controls TLS verification for HTTP/SSE servers.
- **Inputs / options:** `true` (default, system CAs), `false` (disables verification — insecure), or a string path to a custom CA bundle in PEM form (supports `~`).
- **Edge cases / guards:** `false` disables server certificate verification entirely — documented as "Don't use this with real services."
- **Rebuild notes:** Accept bool-or-path in one key; it is the shape users copy from `requests`/`httpx`.

### MCP server key: `client_cert` / `client_key` (mTLS)  `id: acp-mcp-dev.mcp-key-client-cert`
- **Surface:** Config
- **What it does:** Presents a client certificate to servers that require mTLS.
- **How it works:** `_resolve_client_cert(server_name, config)` (`tools/mcp_tool.py:1511`).
- **Inputs / options:** `client_cert` as a string (path to a PEM containing cert + key), a two-element list `[cert, key]`, or a three-element list `[cert, key, password]` for an encrypted key; `client_key` as a separate string path when `client_cert` is a string.
- **Edge cases / guards:** `~` is expanded; a missing file fails fast at connect time with a server-scoped error. Works on both Streamable HTTP and SSE.
- **Rebuild notes:** Support all three list arities — that is what real deployments need.

### MCP server key: `enabled`  `id: acp-mcp-dev.mcp-key-enabled`
- **Surface:** Config
- **What it does:** Skips the server entirely when false: no connection attempt, no discovery, no tool registration; the config stays in place for later.
- **Inputs / options:** bool (default `true`); the CLI list view also parses the strings `true`/`1`/`yes`.
- **Rebuild notes:** Disable ≠ delete; users park servers.

### MCP server key: `timeout`  `id: acp-mcp-dev.mcp-key-timeout`
- **Surface:** Config
- **What it does:** Per-tool-call timeout in seconds.
- **How it works:** `_resolve_tool_timeout(config)` (`tools/mcp_tool.py:558`); `_DEFAULT_TOOL_TIMEOUT = 300` (`:555`).
- **Inputs / options:** number of seconds (default `300`).
- **Rebuild notes:** Separate the call timeout from the connect timeout; they have different failure modes.

### MCP server key: `connect_timeout`  `id: acp-mcp-dev.mcp-key-connect-timeout`
- **Surface:** Config
- **What it does:** Initial connection + discovery timeout in seconds.
- **How it works:** `_DEFAULT_CONNECT_TIMEOUT = 60` (`tools/mcp_tool.py:581`). `hermes mcp login` floors it at 315 s so a human can complete a browser OAuth round-trip.
- **Inputs / options:** number of seconds (default `60`); also settable per-add with `--connect-timeout`.
- **Rebuild notes:** OAuth-capable servers need a much larger connect bound than plain ones.

### MCP server key: `protocol` (era negotiation)  `id: acp-mcp-dev.mcp-key-protocol`
- **Surface:** Config
- **What it does:** Chooses whether Hermes opens with the legacy `initialize` handshake or the MCP 2026-07-28 stateless `server/discover` probe.
- **How it works:** `MCPServerTask._negotiate_session()` (`tools/mcp_tool.py:2529-2607`). `auto` (default) tries `initialize` first and falls back to `discover()` only when the server signals modern-only (`UnsupportedProtocolVersion` `-32022` per `_JSONRPC_UNSUPPORTED_PROTOCOL_VERSION` at `:800`, or `initialize` missing with `-32601` per `_JSONRPC_METHOD_NOT_FOUND` at `:794`); this is deliberately the reverse of the SDK's discover-first auto mode because nearly every deployed server still speaks the handshake era, so initialize-first costs zero extra round-trips. `stateless` (aliases `modern`, `2026-07-28`) probes `discover()` first with one legacy retry on any MCPError. `legacy` (alias `handshake`) uses the handshake only, with no fallback. `LATEST_PROTOCOL_VERSION = "2025-03-26"` and `LATEST_HANDSHAKE_VERSION` are defined at `tools/mcp_tool.py:260-267`.
- **Inputs / options:** `auto` | `stateless` | `modern` | `2026-07-28` | `legacy` | `handshake`.
- **Edge cases / guards:** An unknown value warns `MCP server '<name>': unknown protocol=<v> — treating as 'auto' (valid: auto, stateless, legacy)`. A legacy SDK generation with no `session.discover` re-raises instead of falling back. Both result types expose `.capabilities`, so downstream gates work either way.
- **Rebuild notes:** Handshake-first + narrow fallback beats discover-first when the installed base is old.

### MCP server key: `supports_parallel_tool_calls`  `id: acp-mcp-dev.mcp-key-parallel`
- **Surface:** Config
- **What it does:** Opts a server's tools into concurrent execution.
- **How it works:** Read by `is_mcp_tool_parallel_safe(tool_name)` (`tools/mcp_tool.py:7939`).
- **Inputs / options:** bool (default `false`).
- **Edge cases / guards:** Off by default because an MCP session is a single JSON-RPC pipe and many servers are not re-entrant.
- **Rebuild notes:** Make concurrency opt-in per server, never global.

### MCP server key: `skip_preflight`  `id: acp-mcp-dev.mcp-key-skip-preflight`
- **Surface:** Config
- **What it does:** Bypasses the fail-fast content-type probe for a valid Streamable-HTTP endpoint whose HEAD/GET answers a non-MCP content type but which serves real MCP over POST.
- **How it works:** Guard at `tools/mcp_tool.py:4002`: the preflight runs only when `transport != "sse"`, `skip_preflight` is falsy, the server is not yet ready, and `auth_type != "oauth"`.
- **Inputs / options:** bool (default `false`), HTTP servers only.
- **Rebuild notes:** Preflight is a UX nicety; always give it an escape hatch.

### MCP server key: `transport`  `id: acp-mcp-dev.mcp-key-transport`
- **Surface:** Config
- **What it does:** Selects the SSE transport instead of Streamable HTTP for a `url` server.
- **Inputs / options:** `sse` (the only meaningful value; unset = Streamable HTTP).
- **Edge cases / guards:** SSE endpoints are also detected by the `/sse` URL suffix in catalogue manifests. Portable Agent-Plugin v1 `sse` entries are reported and skipped.
- **Rebuild notes:** Keep both transports; a lot of deployed servers are still SSE.

### MCP server key: `keepalive_interval`  `id: acp-mcp-dev.mcp-key-keepalive`
- **Surface:** Config
- **What it does:** Liveness-ping cadence, so servers that garbage-collect idle sessions do not silently drop Hermes.
- **How it works:** `_DEFAULT_KEEPALIVE_INTERVAL = 180`, `_MIN_KEEPALIVE_INTERVAL = 5` (`tools/mcp_tool.py:610-611`).
- **Inputs / options:** seconds (default `180`, floored at `5`). Example from the module docstring: `10` for the Unreal Engine editor MCP whose session TTL is ~15 s.
- **Rebuild notes:** Set the ping below the server's session TTL, and clamp the floor so a user cannot DoS their own server.

### MCP server keys: `idle_timeout_seconds` / `max_lifetime_seconds` (stdio recycling)  `id: acp-mcp-dev.mcp-key-lifecycle`
- **Surface:** Config
- **What it does:** Recycles a stdio MCP subprocess after it has been idle for N seconds, or after it has been alive for N seconds.
- **How it works:** `_get_lifecycle_seconds(config, key)` (`tools/mcp_tool.py:7020-7039`) reads the key at the top level *or* nested under a `lifecycle:` mapping; `0` disables, negative warns and is ignored, non-numeric warns `MCP config <key> must be a number of seconds; ignoring <raw>`. `MCPServerTask.mark_tool_call()` stamps `_last_tool_call_at`; `_is_recycled_stdio()` reports an intentional recycle; `_RECYCLED_RECONNECT_TIMEOUT = 15.0` (`:590`) bounds the reconnect.
- **Inputs / options:** `idle_timeout_seconds: <n>`, `max_lifetime_seconds: <n>`, or `lifecycle: {idle_timeout_seconds: …, max_lifetime_seconds: …}`; both default off.
- **Rebuild notes:** Accept the same key at two nesting levels — users copy both shapes from the docs.

### MCP `tools.include` / `tools.exclude` filtering  `id: acp-mcp-dev.mcp-key-tools-filter`
- **Surface:** Config
- **What it does:** Whitelists or blacklists which server-native MCP tools get registered.
- **How it works:** `_normalize_name_filter(value, label)` (`tools/mcp_tool.py:6968`) accepts a string or list; `matches_name_filter(tool_name, patterns)` (`:6985`) matches exact names *or* fnmatch-style globs (`*_radar_*`, `get_zones_*`). Precedence: if both are set, `include` wins entirely.
- **Inputs / options:** `include: [names or globs]`, `exclude: [names or globs]`.
- **Edge cases / guards:** Filters match the **original** MCP tool names (with hyphens/dots), not the sanitized registry names.
- **Rebuild notes:** Globs plus exact names in one field; document that include beats exclude rather than intersecting them.

### MCP `tools.resources` / `tools.prompts` utility-tool policy  `id: acp-mcp-dev.mcp-key-utility-policy`
- **Surface:** Config
- **What it does:** Enables or disables the four utility wrappers Hermes can register per server.
- **How it works:** `_parse_boolish(value, default=True)` (`tools/mcp_tool.py:7004`); `_select_utility_schemas(server_name, server, config)` (`:7078`) additionally requires the *capability* to be present on the server's initialize/discover result — `_UTILITY_CAPABILITY_ATTRS` maps `list_resources`/`read_resource` → `resources` and `list_prompts`/`get_prompt` → `prompts` (`:7058+`). Without this gate, tools-only servers (e.g. Context7's `@upstash/context7-mcp`) got all four stubs registered and every call returned `-32601 Method not found`, which made the model conclude the server was broken (#18051).
- **Inputs / options:** `resources: true|false` (default true), `prompts: true|false` (default true).
- **Edge cases / guards:** It is normal to enable prompts and see no prompt utilities — the server simply does not implement them.
- **Rebuild notes:** Gate on advertised capabilities, not on config alone.

### MCP utility tool: `mcp__<server>__list_resources`  `id: acp-mcp-dev.mcp-tool-list-resources`
- **Surface:** Tool
- **What it does:** Lists the resources an MCP server exposes.
- **How it works:** Schema built in `_build_utility_schemas()` (`tools/mcp_tool.py:6896-6966`) with description `List available resources from MCP server '<server>'`; handler from `_make_list_resources_handler(server_name, tool_timeout)` (`:6420`). Paginated via `_paginate_full_list` with `_MCP_LIST_MAX_PAGES = 50` (`:926`).
- **Inputs / options:** none (`{"type": "object", "properties": {}}`).
- **Outputs / side effects:** the resource list.
- **Rebuild notes:** Cap `nextCursor` loops or a misbehaving server spins discovery forever.

### MCP utility tool: `mcp__<server>__read_resource`  `id: acp-mcp-dev.mcp-tool-read-resource`
- **Surface:** Tool
- **What it does:** Reads one resource by URI from an MCP server.
- **How it works:** Description `Read a resource by URI from MCP server '<server>'`; handler `_make_read_resource_handler` (`tools/mcp_tool.py:6479`). Blocks are rendered by `_render_mcp_resource_block` (`:1276`); embedded images are cached by `_cache_mcp_image_block` (`:1144`) and audio by `_cache_mcp_audio_block` (`:1236`); filenames by `_mcp_resource_filename(uri, mime_type)` (`:1201`).
- **Inputs / options:** `uri: string` (required) — "URI of the resource to read".
- **Edge cases / guards:** `_MCP_RESOURCE_MAX_BYTES = 50 * 1024 * 1024` (`:1194`) caps a single resource.
- **Rebuild notes:** Cache binary blocks to disk and hand the model a path, not megabytes of base64.

### MCP utility tool: `mcp__<server>__list_prompts`  `id: acp-mcp-dev.mcp-tool-list-prompts`
- **Surface:** Tool
- **What it does:** Lists the prompts an MCP server exposes.
- **How it works:** Description `List available prompts from MCP server '<server>'`; handler `_make_list_prompts_handler` (`tools/mcp_tool.py:6540`).
- **Inputs / options:** none.
- **Rebuild notes:** n/a.

### MCP utility tool: `mcp__<server>__get_prompt`  `id: acp-mcp-dev.mcp-tool-get-prompt`
- **Surface:** Tool
- **What it does:** Fetches one named prompt (optionally with arguments) from an MCP server.
- **How it works:** Description `Get a prompt by name from MCP server '<server>'`; handler `_make_get_prompt_handler` (`tools/mcp_tool.py:6601`).
- **Inputs / options:** `name: string` (required) — "Name of the prompt to retrieve"; `arguments: object` (optional, `additionalProperties: true`) — "Optional arguments to pass to the prompt".
- **Rebuild notes:** n/a.

### MCP tool naming and sanitization  `id: acp-mcp-dev.mcp-tool-naming`
- **Surface:** Core
- **What it does:** Gives every MCP tool a globally unique, provider-legal registry name.
- **How it works:** `MCP_TOOL_NAME_PREFIX = "mcp__"`, `_MCP_NAME_DELIM = "__"` (`tools/mcp_tool.py:6859-6860`); `mcp_prefixed_tool_name(server, tool)` produces `mcp__<sanitizedServer>__<sanitizedTool>` (`:6863`). `sanitize_mcp_name_component(value)` (`:6841`) replaces every character outside `[A-Za-z0-9_]` with `_` (preserving the historical hyphen→underscore behaviour).
- **Inputs / options:** server name + tool name.
- **Outputs / side effects:** e.g. server `my-api` + tool `list-items.v2` → `mcp__my_api__list_items_v2`.
- **Edge cases / guards:** The double-underscore delimiter matches Claude Code / Codex / OpenCode (anomalyco/opencode #33533) and the Anthropic-OAuth wire form (`_MCP_TOOL_PREFIX` in `anthropic_adapter.py`), removing a single→double rewrite that path used to perform. Filters still use the *original* names.
- **Rebuild notes:** Sanitize to the function-calling identifier charset before registering, or providers reject the whole tool list.

### MCP `auth: oauth` — OAuth 2.1 with PKCE  `id: acp-mcp-dev.mcp-oauth`
- **Surface:** Config
- **What it does:** Runs the MCP SDK's OAuth 2.1 PKCE flow for a remote server: metadata discovery, client identification, token exchange and refresh.
- **How it works:** `tools/mcp_oauth.py` + `tools/mcp_oauth_manager.py`. On first connect a browser window opens; tokens land in `~/.hermes/mcp-tokens/<server>.json` and are reused across sessions; refresh is automatic and re-authorization only happens when refresh fails. HTTP/StreamableHTTP (`url`-based) servers only.
- **Inputs / options:** `auth: oauth` on the server entry, plus the optional `oauth:` sub-block (see below).
- **Outputs / side effects:** `~/.hermes/mcp-tokens/<server>.json`, `~/.hermes/mcp-tokens/<server>.cimd-off`.
- **Edge cases / guards:** `_is_auth_error` / `_handle_auth_error_and_retry` (`tools/mcp_tool.py:4935`, `:4951`) retry once after a 401; `_is_session_expired_error` / `_handle_session_expired_and_retry` (`:5084`, `:5157`) handle expired MCP sessions.
- **Rebuild notes:** Persist tokens per server per profile; refresh transparently; only re-prompt on refresh failure.

### MCP OAuth client identification — CIMD vs DCR  `id: acp-mcp-dev.mcp-oauth-cimd`
- **Surface:** Core
- **What it does:** Identifies Hermes to an authorization server using a Client ID Metadata Document (the mechanism MCP `2026-07-28` adopted in place of Dynamic Client Registration), falling back to DCR when the server does not support it.
- **How it works:** `_CIMD_CLIENT_METADATA_URL = "https://nousresearch.github.io/hermes-agent/docs/oauth/client-metadata.json"` (`tools/mcp_oauth.py:1308-1309`), published from `website/static/oauth/client-metadata.json`. That URL *is* the `client_id`. The SDK sends it only when the server advertises `client_id_metadata_document_supported: true`; otherwise it registers via DCR.
- **Outputs / side effects:** No per-install registration, nothing user-specific.
- **Edge cases / guards:** When a server fetches the document and refuses it at the **token** endpoint (`invalid_client`), Hermes logs the rejection, records `~/.hermes/mcp-tokens/<server>.cimd-off` (`mark_cimd_rejected` / `cimd_rejected`, `tools/mcp_oauth.py:608-638`) and uses DCR for that server from then on. A server that cannot fetch or validate the document at all aborts at the **authorization** endpoint before any redirect — there is no observable signal, so the browser shows an invalid-client error and the login times out after five minutes; the timeout message names the document and points at `cimd: false`. `hermes mcp login <server>` clears the recorded rejection.
- **Rebuild notes:** Record the rejection so you do not re-try CIMD forever, and make the manual re-auth command clear it.

### MCP OAuth pinned callback ports 27890–27894  `id: acp-mcp-dev.mcp-oauth-ports`
- **Surface:** Core
- **What it does:** Pins the OAuth loopback redirect to one of five fixed ports so a CIMD flow's exact-string redirect match can succeed.
- **How it works:** `_CIMD_PORTS = (27890, 27891, 27892, 27893, 27894)` (`tools/mcp_oauth.py:1318`). The port has to be chosen *before* the server's capabilities are known (the redirect URI is fixed at the start of the flow, the metadata arrives partway through), so Hermes pins for any flow that *could* end up using CIMD and reverts to a random high port for the rest. Each pinned port is bound as soon as it is chosen and held until the browser redirect arrives, so two concurrent logins cannot collide; pinned CIMD sockets are never evicted from the reservation pool (`tools/mcp_oauth.py:229-239`).
- **Reverts to a random port when:** the server has been connected to before and its cached metadata does not advertise CIMD; a pre-registered `oauth.client_id`; an `oauth.client_secret`; a custom `oauth.client_name`; a custom `oauth.token_endpoint_auth_method`; an `oauth.redirect_uri` or `oauth.redirect_port` override; a dashboard- or desktop-driven login; an existing client registration on disk; or all five ports being held by other processes.
- **Pins the port when:** the server has never been reached (guessing is the only way CIMD can ever be used on a first login).
- **Rebuild notes:** A small fixed port range + hold-the-socket is the only way to satisfy exact-match redirect URIs without a per-install registration.

### MCP `oauth:` per-server sub-keys  `id: acp-mcp-dev.mcp-key-oauth-block`
- **Surface:** Config
- **What it does:** Overrides how Hermes identifies itself to one server's authorization server.
- **Inputs / options:** `client_metadata_url` (self-hosted CIMD; must be an HTTPS URL *with a path* — no bare origin, no fragment, no userinfo, no `.`/`..` segments — returning `200` and `Content-Type: application/json` with **no redirect**, and its `client_id` must be its own URL; because Hermes still pins 27890–27894 it must declare all ten loopback URIs `http://127.0.0.1:<port>/callback` and `http://localhost:<port>/callback`); `cimd: false` (force DCR); `user_agent` (replaces the HTTP library's default `User-Agent` on **token-endpoint requests only** — authorization-code exchange and refresh — because some authorization servers and WAFs reject `python-httpx/...` there; empty/null ignored; never applied to MCP traffic or OAuth discovery); `client_id`; `client_secret`; `client_name`; `token_endpoint_auth_method`; `redirect_uri`; `redirect_port`.
- **Edge cases / guards:** No other token-request headers are configurable.
- **Rebuild notes:** Every one of these overrides also un-pins the callback port — keep that coupling explicit.

### MCP dashboard-mediated OAuth callback bridge  `id: acp-mcp-dev.mcp-dashboard-oauth`
- **Surface:** Core
- **What it does:** Lets an MCP OAuth flow complete through the already-authenticated web dashboard session instead of a loopback listener, for headless/remote installs.
- **How it works:** `tools/mcp_dashboard_oauth.py`. A `DashboardOAuthFlow` dataclass carries `flow_id`, `server_name`, `profile`, `hermes_home`, `redirect_uri`, `reconnect_live`, `created_at`, `status` (starts `"starting"`), `authorization_url`, `error`, `tools`, and private `expected_state` / callback plumbing with three `threading.Event`s (`_authorization_ready`, `_callback_ready`, `_worker_done`). `publish_authorization_url(url)` parses `state` out of the URL query and refuses a URL with no state (`OAuth authorization URL did not include state`). The MCP SDK still owns discovery, DCR, PKCE, state validation and token exchange — this module only relocates the two human/browser callbacks. `tools/mcp_tool.py:_wrap_with_dashboard_oauth_flow(coro)` (`:5543`) is the wiring point.
- **Outputs / side effects:** Same token files as the loopback flow.
- **Edge cases / guards:** A dashboard-driven login reverts the callback to a random port (see `acp-mcp-dev.mcp-oauth-ports`).
- **Rebuild notes:** Move only the callbacks, never the crypto.

### MCP `sampling:` — server-initiated LLM requests  `id: acp-mcp-dev.mcp-key-sampling`
- **Surface:** Config
- **What it does:** Lets an MCP server ask Hermes to run an LLM completion on its behalf (`sampling/createMessage`), with rate limits, a model allowlist and a token cap.
- **How it works:** `SamplingHandler` (`tools/mcp_tool.py:1770+`), one per server with sampling enabled, passed to `ClientSession` as `sampling_callback`. All state is per-instance (no module globals). The async callback runs on the MCP background loop and offloads the synchronous LLM call with `asyncio.to_thread`. Rate limiting is a 60-second sliding window (`_check_rate_limit`). Model resolution is config override → server hint → default (`_resolve_model`). Stop-reason mapping `_STOP_REASON_MAP = {"stop": "endTurn", "length": "maxTokens", "tool_calls": "toolUse"}`. Metrics tracked: `requests`, `errors`, `tokens_used`, `tool_use_count`.
- **Inputs / options (all under `sampling:`):** `enabled` (default `true`), `model` (override, optional), `max_tokens_cap` (default `4096`), `timeout` (LLM call timeout in seconds, default `30`), `max_rpm` (default `10`), `allowed_models` (list; empty = all), `max_tool_rounds` (default `5`, `0` disables the tool loop), `log_level` (`debug`|`info`|`warning`, default `info` → audit verbosity).
- **Edge cases / guards:** MCP 2026-07-28 deprecates Sampling (SEP-2577, 12-month window; the suggested migration is direct server-side LLM integration). The handler stays functional for the window because handshake-era servers still issue `sampling/createMessage`, but no new capability is added here — modern servers use MRTR (`resultType: "input_required"`) instead.
- **Rebuild notes:** Rate-limit and cap tokens per server; a server that can ask you to call an LLM can also bill you.

### MCP `elicitation:` — server-initiated user input  `id: acp-mcp-dev.mcp-key-elicitation`
- **Surface:** Config
- **What it does:** Lets a server ask the user for structured input mid-tool-call (payment authorization, OAuth confirmation), routed through Hermes' normal approval surface.
- **How it works:** `ElicitationHandler` (`tools/mcp_tool.py:2202+`), passed as `elicitation_callback` (mcp Python SDK ≥ 1.11.0). Form-mode requests are rendered by `_format_elicitation_schema_summary(schema, server_name)` (`:2176`) and routed through `tools.approval.prompt_dangerous_approval`, which surfaces on whichever surface owns the session (CLI, TUI, Telegram, Slack, …). URL-mode requests are declined cleanly with `ElicitResult(action="decline")` and the log line "MCP server '<name>' requested URL-mode elicitation; declining (URL-mode elicitation not implemented)". The schema field is read from *both* `requestedSchema` (mcp 1.x) and `requested_schema` (mcp 2.0) because pydantic aliases do not apply to attribute access — a single-spelling read would silently degrade the prompt to a generic "Approval requested by …" line. Metrics: `requests`, `accepted`, `declined`, `errors`. `_OUTER_TIMEOUT_GRACE_SECONDS = 5` is an asyncio-side safety net above the approval system's own timeout.
- **Inputs / options:** `enabled` (default `true`), `timeout` (seconds, default `300` — mirroring the gateway approval default so async surfaces have time to answer).
- **Edge cases / guards:** Fail-closed — any timeout, exception, or unexpected state returns `decline`/`cancel`, never a silent accept.
- **Rebuild notes:** Reuse the approval surface rather than inventing a second prompt channel; decline modes you have not implemented instead of hanging.

### MCP `trust:` — untrusted-server write gating  `id: acp-mcp-dev.mcp-key-trust`
- **Surface:** Config
- **What it does:** On an `untrusted` server, every write-capable tool call requires explicit user approval before it runs.
- **How it works:** `_normalize_server_trust(value)` (`tools/mcp_tool.py:4608-4627`): `None` → `full`; `"full"` → `full`; `"untrusted"` → `untrusted`; anything else warns `MCP trust: unrecognized trust value <v> — treating as 'untrusted' (valid values: full, untrusted)` and fails closed. `_annotation_read_only_hint(mcp_tool)` (`:4629`) returns True only when `annotations.readOnlyHint is True` (accepting both SDK objects and schema-cache dicts) — missing annotations, missing key, or a truthy non-bool all count as write-capable. `_record_tool_trust_metadata` captures both at discovery. `_trust_gate_check(server, tool)` (`:4662`) calls `tools.approval.request_elicitation_consent` with `surface=f"mcp-trust/{server_name}"` and the message "MCP tool '<tool>' on UNTRUSTED server '<server>' wants to run. This tool is write-capable (no readOnlyHint=true annotation) and may modify external state." plus the detail "Server '<server>' is configured 'trust: untrusted'. Approve to run '<tool>' once, or deny to block it."
- **Inputs / options:** `full` (default) | `untrusted`.
- **Outputs / side effects:** On denial the tool returns "The user did not approve running write-capable MCP tool '<tool>' on untrusted server '<server>'. The command was NOT run. Do not retry without explicit user direction."
- **Edge cases / guards:** Fail-closed — an approval-system exception blocks with "…was blocked: the approval system was unavailable (fail-closed)." `readOnlyHint` is a server-supplied *hint*: a lying server can at most skip approval for tools it claims are read-only, never gain extra access — hence the documented advice to mark any server you do not control `untrusted`.
- **Rebuild notes:** Trust tiers + a per-tool read-only hint + fail-closed normalization is a cheap, effective gate.

### MCP `${VAR}` / `${env:VAR}` and context-variable interpolation  `id: acp-mcp-dev.mcp-interpolation`
- **Surface:** Config
- **What it does:** Lets any string in a server entry reference an environment variable or a workspace/user context value, so secrets stay in `.env` and configs stay portable.
- **How it works:** `_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")` (`tools/mcp_tool.py:673`), `_env_ref_name(ref)` (`:676`) strips a leading `env:` so the Cursor-style `${env:VAR}` resolves to the same variable as `${VAR}`, and `_interpolate_env_vars(value)` (`:5649`) recurses through the entry. Values resolve from the active profile's secret scope, falling back to the process environment; an unset variable keeps its literal placeholder.
- **Context variables (case-sensitive):** `${userHome}` → the current user's home directory; `${workspaceFolder}` → the session workspace root (the session's terminal cwd when known, else the process cwd — `_workspace_folder()`, `tools/mcp_tool.py:689`); `${workspaceFolderBasename}` → its basename; `${pathSeparator}` and `${/}` → `os.sep`. Resolution helper: `_context_var_value(ref)` (`:710`). Anything else falls through to the env-var lookup.
- **Inputs / options:** usable in `env`, `headers`, `args`, `url`, and anywhere else a string appears.
- **Edge cases / guards:** `_warn_hidden_whitespace(server_name, config)` (`:5686`) flags invisible whitespace in values — a classic copy-paste failure.
- **Rebuild notes:** Accept both `${VAR}` and `${env:VAR}` so MCP snippets copied from Cursor/Claude configs work unchanged.

### MCP `hermes://mcp/install` deep link ("Add to Hermes")  `id: acp-mcp-dev.mcp-deeplink`
- **Surface:** Desktop app
- **Where:** A vendor's "Add to Hermes" button → `hermes://mcp/install?name=NAME&config=BASE64`.
- **What it does:** Opens the Hermes desktop app with a pre-filled MCP server config for the user to confirm, mirroring Cursor's `cursor://anysphere.cursor-deeplink/mcp/install`.
- **How it works:** `name` must match `^[A-Za-z0-9._-]{1,64}$`. `config` is the server-config object as base64url-encoded JSON (standard base64 also accepted); the decoded JSON must be an object with either a string `url` (`http://`/`https://` only) or a string `command`, and may carry any documented server key. Payloads over 32 KB are rejected.
- **Inputs / options:** query params `name`, `config`.
- **Outputs / side effects:** A confirmation dialog showing the server name and the full pretty-printed config, with an extra caution for `command`-based servers (which run a local process). Only on explicit confirm is `mcp_servers.<name>` written.
- **Edge cases / guards:** Opening the link never installs anything by itself. Existing server names are never overwritten — the user is asked to rename or cancel.
- **Rebuild notes:** Deep links must be inert until confirmed, size-capped, and scheme-restricted.

### MCP server security validator  `id: acp-mcp-dev.mcp-security-validator`
- **Surface:** Core
- **What it does:** Refuses MCP entries that match three known-malicious shapes, at both save time and spawn time.
- **How it works:** `hermes_cli/mcp_security.py`. `validate_mcp_server_entry(name, entry)` returns a list of warnings; `is_mcp_server_entry_suspicious` is the boolean form. Checks, in order: **(1) hardcoded IOC blocklist** — `_IOC_SUBSTRINGS` (`:80-88`) scanned across command + args + env values, containing the June-2026 `hermes-0day` attacker SSH public key prefix `AAAAC3NzaC1lZDI1NTE5AAAAICBoh1oDC4DnsO1m5mJ4yfEKrQebaFh`, the literal `hermes-0day`, and the source IPs `60.165.167.`, `118.182.244.156`, `61.178.123.196`; one hit returns immediately with `MCP server '<name>' contains a known hermes-0day indicator-of-compromise ('<ioc>')`. **(2) network exfiltration** — only when the command basename is a shell interpreter (`bash, sh, zsh, dash, fish, cmd, cmd.exe, powershell, powershell.exe, pwsh, pwsh.exe`, `:33-45`) and the inline script matches `_EGRESS_PATTERN` (`curl|wget|nc|ncat|socat`, `/dev/tcp/`, `Invoke-WebRequest`, `Invoke-RestMethod`, `System.Net.WebClient`), producing `MCP server '<name>' uses shell interpreter '<cmd>' with network egress in args`, extended with " and exfiltration-shaped arguments" when `_EXFIL_HINT_PATTERN` (`.env`, `--data-binary`, `--data-raw`, `-X POST`, `POST`, `< something`) also matches. **(3) OS persistence** — the inline script matching `_PERSISTENCE_PATTERN` (`authorized_keys`, `.ssh/`, `/etc/ssh`, `/etc/pam.d`, `pam_*.so`, `/etc/sudoers`, `/etc/cron`, `crontab`, `/etc/rc.local`, `/etc/systemd`, `.bashrc`, `.bash_profile`, `.profile`, `.zshrc`) yields the hermes-0day backdoor message.
- **Where it runs:** `_save_mcp_server` (dashboard API + CLI) and `tools.mcp_tool._filter_suspicious_mcp_servers` (`tools/mcp_tool.py:5732`) at discovery / cron / startup, so a hand-edited or pre-planted `config.yaml` is caught before it can execute.
- **Edge cases / guards:** Explicitly **not** a whitelist and **not** a sandbox — legitimate local MCPs may still use custom commands, Python scripts, `npx`, `uvx`.
- **Rebuild notes:** Narrow, high-signal shapes plus a hardcoded IOC list beats a general-purpose "is this command dangerous" heuristic.

### MCP tool-description prompt-injection scanner  `id: acp-mcp-dev.mcp-injection-scan`
- **Surface:** Core
- **What it does:** Warns when an MCP server's tool *description* — text that goes straight into the model's context — looks like a prompt-injection payload.
- **How it works:** `_scan_mcp_description(server_name, tool_name, description)` (`tools/mcp_tool.py:888`) runs ten patterns (`_MCP_INJECTION_PATTERNS`, `:864-886`) and logs `MCP server '<s>' tool '<t>': suspicious description content — <reasons>. Description: <200 chars>`.
- **The ten patterns and their reasons, verbatim:** `ignore\s+(all\s+)?previous\s+instructions` → "prompt override attempt ('ignore previous instructions')"; `you\s+are\s+now\s+a` → "identity override attempt ('you are now a...')"; `your\s+new\s+(task|role|instructions?)\s+(is|are)` → "task override attempt"; `system\s*:\s*` → "system prompt injection attempt"; `<\s*(system|human|assistant)\s*>` → "role tag injection attempt"; `do\s+not\s+(tell|inform|mention|reveal)` → "concealment instruction"; `(curl|wget|fetch)\s+https?://` → "network command in description"; `base64\.(b64decode|decodebytes)` → "base64 decode reference"; `exec\s*\(|eval\s*\(` → "code execution reference"; `import\s+(subprocess|os|shutil|socket)` → "dangerous import reference". All case-insensitive.
- **Outputs / side effects:** Warnings only (the findings list is returned for callers that want to surface them).
- **Rebuild notes:** Scanning descriptions is cheap and catches the whole "rug-pull tool description" class; also strip Unicode tag characters (`tools.ansi_strip.strip_unicode_tags` is applied in `_convert_mcp_schema`).

### MCP result size caps and truncation  `id: acp-mcp-dev.mcp-result-caps`
- **Surface:** Core
- **What it does:** Stops a buggy or malicious MCP server from flooding the agent with a multi-megabyte payload.
- **How it works:** `_MCP_HARD_RESULT_CAP_CHARS = 2_000_000` (`tools/mcp_tool.py:139`) with `_truncate_mcp_text_result(text, max_chars)` (`:142`) using a 40 % head / 60 % tail split. It sits deliberately far *above* the budget layer's 50 K MCP spillover threshold (`tools/budget_config.py`) so ordinary large results reach spillover intact (spilled to disk in full, preview in context) and only pathological multi-MB floods are lossy-truncated. Resources are separately capped at `_MCP_RESOURCE_MAX_BYTES = 50 MiB` (`:1194`).
- **Rebuild notes:** Two tiers — a lossless spill for "large" and a lossy cap for "pathological".

### MCP stdio subprocess stderr redirection  `id: acp-mcp-dev.mcp-stderr-log`
- **Surface:** Core
- **What it does:** Keeps MCP server banners and logs off the user's terminal, where they would corrupt a TUI render.
- **How it works:** Rather than the SDK's default `errlog=sys.stderr`, every stdio MCP subprocess's stderr is redirected into a shared per-profile append-mode log at `~/.hermes/logs/mcp-stderr.log`, opened once per process (`_get_mcp_stderr_log`, `tools/mcp_tool.py:192`) and tagged per server by `_write_stderr_log_header(server_name)` (`:227`). The handle must have a real OS-level `fileno()` because asyncio wires the child's stderr directly to that fd; the fallback is `os.devnull`.
- **Outputs / side effects:** `~/.hermes/logs/mcp-stderr.log`.
- **Rebuild notes:** Never let a child process write to the TTY that a TUI owns.

### MCP stdio parent-death watchdog  `id: acp-mcp-dev.mcp-stdio-watchdog`
- **Surface:** Core
- **Where:** `python3 -m tools.mcp_stdio_watchdog --ppid <original_parent_pid> -- <real_command> <args…>`.
- **What it does:** Guarantees a stdio MCP subprocess (and its own descendants) dies when the Hermes process that spawned it dies hard — `kill -9`, an OS crash, a force-quit of the TUI/desktop app.
- **How it works:** `tools/mcp_stdio_watchdog.py`. Hermes spawns the supervisor instead of the server; the supervisor (1) execs the real command as its own child in its own process group (`start_new_session`), (2) passes stdin/stdout/stderr straight through as a no-op relay (the MCP stdio protocol talks over those pipes, so it must not be a bytes-in-the-middle proxy), (3) polls `os.getppid()` against the recorded parent PID every `_POLL_INTERVAL_S = 2.0` seconds (`_is_orphaned`, `:57`), and (4) on orphaning kills the child's process group with SIGTERM, waits `_TERM_GRACE_S = 3.0`, then SIGKILL (`_terminate_process_group`, `:62`). Standard-library only so it starts fast and cannot itself leak.
- **Inputs / options:** `--ppid <pid>` then `--` then the real argv.
- **Edge cases / guards:** Wrapped only on POSIX (`os.name == "posix"` gate at the wrap site, `tools/mcp_tool.py:1069`); macOS has no `prctl(PR_SET_PDEATHSIG)` equivalent, which is why this exists. Without it, repeated ungraceful restarts pile up N orphans all racing for the same upstream SSE session, producing "Invalid request parameters" / "Received request before initialization was complete" on the *legitimate* new connection. A non-POSIX import degrades to a plain child kill instead of `AttributeError`.
- **Rebuild notes:** A transparent relay supervisor is the portable substitute for `PR_SET_PDEATHSIG`.

### MCP schema cache (lazy startup)  `id: acp-mcp-dev.mcp-schema-cache`
- **Surface:** Core
- **Where:** `$HERMES_HOME/cache/mcp_schema_cache.json` (mode `0o600`).
- **What it does:** Lets Hermes register an MCP server's tools into the agent's tool snapshot without spawning the stdio child at idle dashboard startup.
- **How it works:** `tools/mcp_schema_cache.py`. Entries are keyed by server name and validated against `config_fingerprint(config)` — a 16-hex-char SHA-256 prefix over `{command, args, url, transport, sorted(tools.include), sorted(tools.exclude)}` (`:31-43`). `write_cache_entry(server, fingerprint, tools=…, utility_tools=…, ttl_ms=…, cache_scope=…)` persists after a successful live connect via `utils.atomic_json_write`. `get_cached_entry` returns `None` on a fingerprint mismatch or when an MCP-2026-07-28 SEP-2549 `ttlMs` freshness hint has expired (`(now - written_at) * 1000 >= ttl_ms`); entries without a recorded TTL keep the old never-expires behaviour. `cacheScope` is irrelevant because the cache is per-user local disk, which satisfies even `private`. `clear_cache_entry`, `has_cached_entry`, `tools_from_cache_entry`, `utility_tools_from_cache_entry` round out the API; `tools/mcp_tool.py:_register_from_cache_sync` (`:7435`) is the consumer.
- **Edge cases / guards:** Write-through skips the load-all+rewrite churn when the entry is byte-identical — *except* for TTL'd entries, which always rewrite so `written_at` advances (otherwise the entry would expire at its original write time no matter how many live reconnects confirmed it).
- **Rebuild notes:** Fingerprint the connection-defining fields only; honour the server's TTL hint; keep the file user-only.

### MCP background discovery and bounded waits  `id: acp-mcp-dev.mcp-startup`
- **Surface:** Core
- **What it does:** Starts MCP discovery in the background at process start so the CLI/TUI/ACP server is responsive, then gives it a bounded chance to finish before the first agent is built.
- **How it works:** `hermes_cli/mcp_startup.py`. `_has_configured_mcp_servers()` is a cheap config probe so non-MCP users never import the MCP stack (`:14`). `start_background_mcp_discovery(logger=…, thread_name=…)` (`:32`) spawns one shared daemon thread per process. `_discover_mcp_tools_without_interactive_oauth()` (`:162`) runs discovery with OAuth barred from reading the user's stdin. `_resolve_discovery_timeout()` (`:122`) resolves explicit arg > config > default. `wait_for_mcp_discovery()` (`:175`), `mcp_discovery_in_flight()` (`:197`), `join_mcp_discovery(timeout)` (`:212`), and `ensure_mcp_discovery_before_agent_build()` (`:227`) — which also *restarts* discovery when the entry-point spawn never ran or ended with zero connected servers (the retry-after-zero-connected allowance).
- **Config / env:** `mcp_discovery_timeout` (default `1.5`), `mcp_single_query_discovery_timeout` (default `15.0`), `HERMES_ACP_SKIP_CONFIGURED_MCP`.
- **Rebuild notes:** Fire-and-forget plus a bounded join at the one place where the tool snapshot is taken.

### MCP reconnection, backoff, parking and circuit breaker  `id: acp-mcp-dev.mcp-reconnect`
- **Surface:** Core
- **What it does:** Keeps a flaky MCP server from wedging Hermes or hammering a remote endpoint.
- **How it works (constants, `tools/mcp_tool.py`):** `_MAX_RECONNECT_RETRIES = 5` (`:582`), `_MAX_INITIAL_CONNECT_RETRIES = 3` (`:583`), `_MAX_BACKOFF_SECONDS = 60` (`:584`), `_PARKED_RETRY_INTERVAL = 300` seconds between parked self-probes (`:589`), `_RECYCLED_RECONNECT_TIMEOUT = 15.0` (`:590`), `_BACKOFF_JITTER = 0.2` (±20 %, `:594`) applied by `_jittered(seconds)` (`:597`), `_MCP_LOOP_DRAIN_TIMEOUT = 3.0` (`:616`). Per-server connect-failure cooldown: `_CONNECT_RETRY_BASE_BACKOFF_SEC = 30.0`, `_CONNECT_RETRY_MAX_BACKOFF_SEC = 600.0` with `_record_connect_failure` / `_clear_connect_failure` / `_connect_cooldown_active` (`:4519-4569`). Circuit breaker: `_CIRCUIT_BREAKER_THRESHOLD = 3`, `_CIRCUIT_BREAKER_COOLDOWN_SEC = 60.0` (`:4571-4572`) driven by `_bump_server_error` / `_reset_server_error`. `reconnect_mcp_server(name)` (`:4770`), `_signal_reconnect` (`:4743`), `_wait_for_server_session_ready` (`:4779`), `_signal_reconnect_and_wait` (`:4820`), `_ensure_healthy_or_recycle` (`:6044`).
- **Failure classification:** `_classify_mcp_failure(exc)` (`:1425`), `_unwrap_exception_group` (`:1380`), `_contains_only_cancellation` (`:1418`), `_format_connect_error(exc)` (`:1691`), `_sanitize_error(text)` (`:768`) which strips credentials with `_CREDENTIAL_PATTERN` (GitHub PATs `ghp_…`, OpenAI-style `sk-…`, `Bearer <x>`, `token=`, `key=`, `API_KEY=`, `password=`, `secret=`; `:656-670`).
- **Rebuild notes:** Jittered exponential backoff, a per-server cooldown, and a parked state with slow self-probes — three layers, not one.

### MCP orphan reaper and loop shutdown  `id: acp-mcp-dev.mcp-shutdown`
- **Surface:** Core
- **What it does:** Cleans up MCP subprocesses and the background event loop on exit.
- **How it works:** `shutdown_mcp_servers()` (`tools/mcp_tool.py:8353`) signals each server task to exit its `async with` block *in the task that opened it* (anyio requires it). `_kill_orphaned_mcp_children()` (`:8420`) sweeps leftovers using `_snapshot_child_pids()` (`:5405`) and `_filter_mcp_children(pids)` (`:5446`). `_stop_mcp_loop_if_idle()` (`:8548`) and `_stop_mcp_loop(only_if_idle=…)` (`:8612`) tear the loop down. `hermes_cli/main.py:166-167` calls `shutdown_mcp_servers()` on CLI exit.
- **Rebuild notes:** Close the transport in the opening task; sweep by parentage, not by name.

### MCP discovery lock (multi-process)  `id: acp-mcp-dev.mcp-discovery-lock`
- **Surface:** Core
- **What it does:** Stops two Hermes processes from racing MCP discovery for the same profile.
- **How it works:** `_try_acquire_mcp_discovery_lock()` (`tools/mcp_tool.py:5335`) with `_LockCookie` (`:5270`) and `_acquire_lock_on_fh(fh)` (`:5307`) using an advisory file lock.
- **Rebuild notes:** An advisory lock file per profile is enough; do not block, just skip.

### MCP status and introspection API  `id: acp-mcp-dev.mcp-status-api`
- **Surface:** Core
- **What it does:** Exposes MCP server/tool state to the CLI banner, the dashboard, the TUI and the desktop app.
- **How it works:** `get_mcp_status()` (`tools/mcp_tool.py:7957`), `probe_mcp_server_tools()` (`:8037`), `has_registered_mcp_tools()` (`:8111`), `get_registered_mcp_server_names()` (`:8125`), `refresh_agent_mcp_tools(...)` (`:8140`) with `_reinject_post_build_tools(agent, tools_list, name_set)` (`:8284`), `discover_mcp_tools()` (`:7853`), `register_mcp_servers(servers)` (`:7639`), `_track_mcp_tool_server` / `_forget_mcp_tool_server` (`:7066`, `:7072`).
- **Config / env:** `mcp.auto_reload_on_config_change` (default `true`); `approvals.mcp_reload_confirm` (default `true`); `delegation.inherit_mcp_toolsets` (default `true`); the auxiliary-model block `auxiliary.mcp.provider` (default `"auto"`), `auxiliary.mcp.model` (`""`), `auxiliary.mcp.base_url` (`""`), `auxiliary.mcp.api_key` (`""`), `auxiliary.mcp.timeout` (`30`), `auxiliary.mcp.reasoning_effort` (`""`) — the model used to answer server-initiated sampling requests.
- **Rebuild notes:** One status function feeding every surface keeps the four UIs honest.

### `hermes mcp serve` — Hermes as an MCP server (messaging bridge)  `id: acp-mcp-dev.mcp-serve`
- **Surface:** CLI
- **Where:** `hermes mcp serve [-v|--verbose] [--accept-hooks]`; registered in an MCP client as `{"mcpServers": {"hermes": {"command": "hermes", "args": ["mcp", "serve"]}}}`.
- **What it does:** Runs a stdio MCP server that lets any MCP client (Claude Code, Cursor, Codex, …) list Hermes conversations across every connected messaging platform, read history, fetch attachments, poll/long-poll for live events, send messages, list channels, and answer pending approval requests.
- **How it works:** `mcp_serve.py`. `run_mcp_server(verbose)` (`:1029`) configures logging to **stderr** (DEBUG with `-v`, else WARNING), starts an `EventBridge`, builds the server with `create_mcp_server(event_bridge=bridge)` (`:623`) and runs `await server.run_stdio_async()`, stopping the bridge in a `finally`. The server is `MCPServer("hermes", instructions="Hermes Agent messaging bridge. Use these tools to interact with conversations across Telegram, Discord, Slack, WhatsApp, Signal, Matrix, and other connected platforms.")` (`:631-645`); mcp 2.0 removed `mcp.server.fastmcp`, so the decorator-driven server is now `mcp.server.MCPServer` with the same `@server.tool()` / `run_stdio_async()` surface (docstring → tool description, signature → input schema).
- **Data sources:** `_get_sessions_dir()` → `$HERMES_HOME/sessions`; `_load_sessions_index()` prefers `SessionDB` (`_load_sessions_index_from_db`, `:162`) and falls back to JSON (`_load_sessions_index_from_json`, `:189`); `_load_session_messages(session_id)` (`:85`); `_load_channel_directory()` (`:214`); `_extract_message_content` (`:253`) and `_extract_attachments` (`:265`).
- **Inputs / options:** `-h, --help`; `-v, --verbose` ("Enable verbose logging on stderr"); `--accept-hooks`.
- **Outputs / side effects:** A stdio MCP server exposing 10 tools (9 matching OpenClaw's MCP channel-bridge surface plus the Hermes-specific `channels_list`). Reads `$HERMES_HOME/state.db`; `messages_send` writes to real platforms.
- **Edge cases / guards:** Without the `mcp` package it prints `Error: MCP server requires the 'mcp' package.` + `Install with: <python> -m pip install 'mcp'` to stderr and exits 1. KeyboardInterrupt stops the bridge cleanly.
- **Rebuild notes:** Docstring-and-signature-driven tool definition keeps schema and docs in one place; keep every log on stderr.

### `hermes mcp serve` tool: `conversations_list`  `id: acp-mcp-dev.mcpserve-conversations-list`
- **Surface:** Tool
- **What it does:** Lists active messaging conversations across connected platforms with the session keys other tools need.
- **How it works:** `mcp_serve.py:644-698`. Filters by platform (case-insensitive) and by a `search` substring matched against `display_name`, `chat_name` and the session key; sorts by `updated_at` descending; truncates to `limit`.
- **Inputs / options:** `platform: str | None` — "Filter by platform name (telegram, discord, slack, etc.)"; `limit: int = 50` — coerced by `_coerce_int(default=50, minimum=1, maximum=200)`; `search: str | None` — "Optional text to filter conversations by name".
- **Outputs / side effects:** JSON `{"count": N, "conversations": [{session_key, session_id, platform, chat_type, display_name, chat_name, user_name, updated_at}]}` (indent 2).
- **Rebuild notes:** Return the session key first — every other tool keys off it.

### `hermes mcp serve` tool: `conversation_get`  `id: acp-mcp-dev.mcpserve-conversation-get`
- **Surface:** Tool
- **What it does:** Returns detailed metadata for one conversation.
- **How it works:** `mcp_serve.py:701-729`.
- **Inputs / options:** `session_key: str` — "The session key from conversations_list".
- **Outputs / side effects:** JSON with `session_key, session_id, platform, chat_type, display_name, user_name, chat_name, chat_id, thread_id, updated_at, created_at, input_tokens, output_tokens, total_tokens`; `{"error": "Conversation not found: <key>"}` on a miss.
- **Rebuild notes:** Include token counters — an MCP client using this as a dashboard wants cost.

### `hermes mcp serve` tool: `messages_read`  `id: acp-mcp-dev.mcpserve-messages-read`
- **Surface:** Tool
- **What it does:** Reads the recent user/assistant messages of a conversation in chronological order.
- **How it works:** `mcp_serve.py:734-780`. Keeps only `role in {"user","assistant"}` messages with non-empty extracted content, truncates each `content` to 2000 chars, and returns the last `limit`.
- **Inputs / options:** `session_key: str`; `limit: int = 50` (`_coerce_int`, min 1, max 200) — "Maximum number of messages to return (default 50, most recent)".
- **Outputs / side effects:** JSON `{"session_key", "count", "total_in_session", "messages": [{id, role, content, timestamp}]}`; errors `Conversation not found: <key>` / `No session ID for this conversation` / whatever `_load_session_messages` reports.
- **Rebuild notes:** Cap per-message content, and report `total_in_session` so the client knows it is seeing a tail.

### `hermes mcp serve` tool: `attachments_fetch`  `id: acp-mcp-dev.mcpserve-attachments-fetch`
- **Surface:** Tool
- **What it does:** Lists the non-text attachments (images, media, other non-text blocks) of one message.
- **How it works:** `mcp_serve.py:786-825`; finds the message by string-compared `id`, then `_extract_attachments`.
- **Inputs / options:** `session_key: str`; `message_id: str` — "The message ID from messages_read".
- **Outputs / side effects:** JSON `{"message_id", "count", "attachments"}`; `{"error": "Message not found: <id>"}` on a miss.
- **Rebuild notes:** Key attachments off the message id you already returned from `messages_read`.

### `hermes mcp serve` tool: `events_poll`  `id: acp-mcp-dev.mcpserve-events-poll`
- **Surface:** Tool
- **What it does:** Polls for conversation events since a cursor.
- **How it works:** `mcp_serve.py:833-859` → `EventBridge.poll_events(after_cursor, session_key, limit)` (`:381`).
- **Inputs / options:** `after_cursor: int = 0` (`_coerce_int`, min 0, max 10^18) — "Return events after this cursor (0 for all)"; `session_key: str | None` — "Optional filter to one conversation"; `limit: int = 20` (min 1, max 200).
- **Outputs / side effects:** JSON with the events plus a `next_cursor`. Event types: `message`, `approval_requested`, `approval_resolved`.
- **Rebuild notes:** Monotonic integer cursor + `next_cursor` echo.

### `hermes mcp serve` tool: `events_wait`  `id: acp-mcp-dev.mcpserve-events-wait`
- **Surface:** Tool
- **What it does:** Long-polls: blocks until the next matching event arrives or the timeout expires.
- **How it works:** `mcp_serve.py:862-894` → `EventBridge.wait_for_event(after_cursor, session_key, timeout_ms)` (`:405`) which waits on a `threading.Event`.
- **Inputs / options:** `after_cursor: int = 0` (min 0, max 10^18); `session_key: str | None`; `timeout_ms: int = 30000` (`_coerce_int`, min 0, max 300000 — capped at 5 minutes).
- **Outputs / side effects:** `{"event": {…}}` or `{"event": null, "reason": "timeout"}`.
- **Rebuild notes:** Cap the wait server-side; a client can always re-issue.

### `hermes mcp serve` tool: `messages_send`  `id: acp-mcp-dev.mcpserve-messages-send`
- **Surface:** Tool
- **What it does:** Sends a message to a platform conversation.
- **How it works:** `mcp_serve.py:897-930`; delegates to `tools.send_message_tool.send_message_tool({"action": "send", "target": target, "message": message})`.
- **Inputs / options:** `target: str` — "Platform target in \"platform:identifier\" format"; `message: str` — "The message text to send". Documented examples, verbatim: `target="telegram:6308981865"`, `target="discord:#general"`, `target="slack:#engineering"`. Human-friendly channel names are resolved automatically.
- **Outputs / side effects:** The send-message tool's own result string; a real outbound message. Errors: `{"error": "Both target and message are required"}`, `{"error": "Send message tool not available"}`, `{"error": "Send failed: <exc>"}`.
- **Rebuild notes:** Reuse the agent's own send tool rather than re-implementing platform clients.

### `hermes mcp serve` tool: `channels_list`  `id: acp-mcp-dev.mcpserve-channels-list`
- **Surface:** Tool
- **What it does:** Lists the channels/targets you can send to — the Hermes-specific extra beyond the OpenClaw 9-tool surface.
- **How it works:** `mcp_serve.py:933-981`. Prefers the channel directory (`_load_channel_directory`), iterating `directory["platforms"][<platform>]` lists; falls back to deriving unique `platform:chat_id` targets from the sessions index.
- **Inputs / options:** `platform: str | None` — "Filter by platform name (telegram, discord, slack, etc.)".
- **Outputs / side effects:** JSON `{"count": N, "channels": [{target, platform, name, chat_type}]}`.
- **Rebuild notes:** The `target` strings must be directly usable with `messages_send`.

### `hermes mcp serve` tool: `permissions_list_open`  `id: acp-mcp-dev.mcpserve-permissions-list`
- **Surface:** Tool
- **What it does:** Lists pending approval requests the bridge has observed since it started.
- **How it works:** `mcp_serve.py:986-999` → `EventBridge.list_pending_approvals()` (`:433`), which tracks approvals in memory from the event stream.
- **Inputs / options:** none.
- **Outputs / side effects:** JSON `{"count": N, "approvals": [...]}`.
- **Edge cases / guards:** Live-session only — approvals raised before the bridge connected are not included (stated verbatim in the tool docstring).
- **Rebuild notes:** Say clearly that the list is session-scoped, or clients will treat it as durable.

### `hermes mcp serve` tool: `permissions_respond`  `id: acp-mcp-dev.mcpserve-permissions-respond`
- **Surface:** Tool
- **What it does:** Answers a pending approval request from the MCP client.
- **How it works:** `mcp_serve.py:1002-1020` → `EventBridge.respond_to_approval(id, decision)` (`:441`).
- **Inputs / options:** `id: str` — "The approval ID from permissions_list_open"; `decision: str` — one of `allow-once`, `allow-always`, `deny`.
- **Outputs / side effects:** The bridge's result dict as JSON. An invalid decision returns `{"error": "Invalid decision: <d>. Must be allow-once, allow-always, or deny"}`.
- **Rebuild notes:** Validate the enum in the tool, not only downstream.

### `hermes mcp serve` EventBridge  `id: acp-mcp-dev.mcpserve-event-bridge`
- **Surface:** Core
- **What it does:** Turns SQLite polling into a push-shaped event queue with waiter support — the Hermes equivalent of OpenClaw's WebSocket gateway bridge.
- **How it works:** `mcp_serve.py:335-620`. State: an in-memory `List[QueueEvent]` (`cursor: int`, `type: "message"|"approval_requested"|"approval_resolved"`, `session_key: str`, `data: dict`; `:312-317`), a monotonic cursor, a `threading.Lock`, a `threading.Event` for waiters, a per-session `_last_poll_timestamps` map, an in-memory `_pending_approvals` dict, and an mtime cache (`_state_db_mtime`, `_cached_sessions_index`) so a quiescent `state.db` costs nothing. `start()` spawns the poll thread; `_establish_baseline()` / `_establish_baseline_with_db(db)` (`:469`, `:481`) set the initial watermark; `_poll_loop()` (`:517`) and `_poll_once(db)` (`:537`) do the work; `_enqueue(event)` (`:458`) appends and signals waiters; `stop()` shuts it down. Timestamps are normalised by `_ts_float` (`:320`), which accepts epoch numbers, numeric strings and ISO strings.
- **Rebuild notes:** Poll with an mtime short-circuit and a monotonic cursor; a real push channel can replace the poller without changing the tool contract.

### `hermes-tools` MCP server for the Codex runtime  `id: acp-mcp-dev.hermes-tools-mcp`
- **Surface:** Core
- **Where:** `python -m agent.transports.hermes_tools_mcp_server [-v|--verbose]`; spawned by `CodexAppServerSession.ensure_started()`; registered by Codex as `~/.codex/config.toml [mcp_servers.hermes-tools]`.
- **What it does:** When an `openai/*` turn runs through the codex app-server (which owns the loop and builds its own tool list), this stdio MCP server hands the spawned Codex subprocess a curated subset of Hermes' richer tools so the user keeps Hermes capability inside a Codex turn.
- **How it works:** `agent/transports/hermes_tools_mcp_server.py`. `_build_server()` (`:154`) creates `MCPServer("hermes-tools", instructions="Hermes Agent's tool surface, exposed for use inside a Codex session. Use these for capabilities Codex's built-in toolset doesn't cover: web search/extract, browser automation, subagent delegation, vision, image generation, persistent memory, skills, and cross-session search.")`, pulls authoritative schemas from `model_tools.get_tool_definitions(quiet_mode=True)`, and for each exposed name builds a closure whose `__signature__` is synthesized from the Hermes JSON Schema by `_signature_from_schema(schema)` (`:67`, mapping `string→str, integer→int, number→float, boolean→bool, array→list, object→dict`, required params positional-with-no-default and optional ones `Optional[T] = None`, skipping names starting with `_`). Dispatch filters out `None` values then calls `model_tools.handle_function_call(tool_name, args)`, returning `{"error": …, "tool": …}` JSON on any exception. Registration tries `mcp.add_tool(handler, name=…, description=…)` and falls back to the decorator form on `TypeError` for older SDKs. `main()` (`:253`) logs to **stderr** only (INFO with `-v`/`--verbose`, else WARNING), sets `HERMES_QUIET=1` and `HERMES_REDACT_SECRETS=true` via `setdefault`, and runs `server.run()` (stdio by default). Exit codes: `2` when the `mcp` package is missing, `1` on a crash, `0` on KeyboardInterrupt.
- **Exposed tools (26, verbatim `EXPOSED_TOOLS`, `:112-150`):** `web_search`, `web_extract`, `browser_navigate`, `browser_click`, `browser_type`, `browser_press`, `browser_snapshot`, `browser_scroll`, `browser_back`, `browser_get_images`, `browser_console`, `browser_vision`, `vision_analyze`, `image_generate`, `skill_view`, `skills_list`, `text_to_speech`, `kanban_complete`, `kanban_block`, `kanban_request_review`, `kanban_request_changes`, `kanban_comment`, `kanban_heartbeat`, `kanban_show`, `kanban_list`, `kanban_create`, `kanban_unblock`, `kanban_link`.
- **Deliberately NOT exposed:** `terminal`/shell, `read_file`/`write_file`/`patch`, `search_files`/`process`, `clarify` (Codex has its own equivalents and its own approval UI); `delegate_task`, `memory`, `session_search`, `todo` — these are `_AGENT_LOOP_TOOLS` in `model_tools.py` and require the running `AIAgent`'s mid-loop state, so a stateless MCP callback cannot drive them.
- **Inputs / options:** `-v` / `--verbose`.
- **Outputs / side effects:** Log line `hermes-tools MCP server registered %d/%d tools`; kanban tools write `~/.hermes/kanban.db`. Tools absent from the current registry are skipped with a debug line.
- **Config / env:** `HERMES_KANBAN_TASK` gates the kanban worker-handoff tools (set by the dispatcher when spawning a worker); `kanban_create` / `kanban_unblock` / `kanban_link` are orchestrator-only and gated on that var being *unset*. `HERMES_QUIET`, `HERMES_REDACT_SECRETS`.
- **Edge cases / guards:** Module-level import works without the `mcp` package — the clear error only appears when actually run.
- **Rebuild notes:** Synthesizing `__signature__` from a JSON Schema is the trick that lets a signature-driven SDK expose foreign tools; expose only what the host runtime lacks.

---

## 3. OpenAI-compatible HTTP API (api_server platform)

> Only the three OpenAI-shaped endpoints plus response retrieval/deletion are documented here. The rest of the api_server platform (`/v1/runs*`, `/v1/artifacts*`, `/v1/room-members*`, `/v1/browser-control*`, `/api/sessions*`, `/api/jobs*`, `/health*`, `/v1/capabilities`, `/v1/skills`, `/v1/toolsets`, auth, multiplexing) belongs to the `platforms-*` shards — see Handoffs.

### `POST /v1/chat/completions` — OpenAI Chat Completions  `id: acp-mcp-dev.api-chat-completions`
- **Surface:** API
- **Where:** `http://<host>:8642/v1/chat/completions` (and `/p/<profile>/v1/chat/completions` when `gateway.multiplex_profiles` is on). Any OpenAI-compatible frontend — Open WebUI, LobeChat, LibreChat, AnythingLLM, NextChat, ChatBox — points at `http://localhost:8642/v1` and authenticates with `API_SERVER_KEY`.
- **What it does:** Runs one full Hermes agent turn (tools, approvals, memory and all) and returns the answer in the OpenAI `chat.completion` shape, streaming or not.
- **How it works:** `AmiServerAdapter._handle_chat_completions()` (`gateway/platforms/api_server.py:5045`). Steps: concurrency gate (`_concurrency_limited_response`); parse JSON; require a non-empty `messages` list; split roles — every `system` message is flattened with `_normalize_chat_content` and concatenated with `\n` into an *ephemeral* system prompt layered on top of the core prompt (system messages never carry images), `user`/`assistant` messages go through `_normalize_multimodal_content`; the **last** conversation message becomes `user_message` and everything before it becomes `history`. Session id: when `X-Hermes-Session-Id` is supplied (and authentication is configured) history is loaded from `state.db` via `db.get_messages_as_conversation`; otherwise `_derive_chat_session_id(system_prompt, first_user)` fingerprints the conversation so consecutive Open-WebUI turns map to the same Hermes session. Routing: `_resolve_route(model)` against `gateway.platforms.api_server.extra.model_routes`, plus `_request_agent_overrides(body, virtual_model=self._model_name, allow_bare_model=self._direct_model_requests)`; a conflict between a route and an explicit model/provider yields a 400 via `_request_route_conflict_error`.
- **Inputs / options (request body):** `messages` (required array of `{role, content}`; `role` ∈ `system|user|assistant`; `content` may be a string or an OpenAI multimodal parts array), `model` (matched against `model_routes` aliases and the advertised virtual model), `provider` (Hermes extension — an explicit provider slug is always honoured), `model_options` (Hermes extension — a dict passed through to the agent), `stream` (bool, coerced by `_coerce_request_bool`, default `false`), `tools`, `tool_choice` (included in the idempotency fingerprint).
- **Inputs / options (headers):** `Authorization: Bearer <API_SERVER_KEY>`; `X-Hermes-Session-Id` (continue an existing session — requires an API key to be configured, else **403** "Session continuation requires API key authentication. Configure API_SERVER_KEY to enable this feature."); `X-Hermes-Session-Key` (scopes long-term memory such as Honcho to a stable per-channel identifier, independent of the session id which rotates on `/new`); `Idempotency-Key` (de-duplicates a retry — fingerprint keys: `model`, `provider`, `model_options`, `messages`, `tools`, `tool_choice`, `stream`); `Origin` (CORS).
- **Outputs (non-streaming):** `{"id": "chatcmpl-<29 hex>", "object": "chat.completion", "created": <epoch>, "model": <requested model>, "choices": [{"index": 0, "message": {"role": "assistant", "content": …}, "finish_reason": …}], "usage": {"prompt_tokens", "completion_tokens", "total_tokens"}}`. `finish_reason` is `"length"` when the run was partial and the error text contains "truncat", `"error"` when the run failed or did not complete with an error, else `"stop"` (#22496). When the run was partial/failed/incomplete but text exists, a Hermes extension block is added: `hermes: {completed, partial, failed, error, error_code: "output_truncated"|"agent_error"}`.
- **Response headers:** `X-Hermes-Session-Id` (always), `X-Hermes-Session-Key` (echoed when supplied), and on a degraded run `X-Hermes-Completed: false`, `X-Hermes-Partial: true|false`, `X-Hermes-Error: <redacted, ≤200 chars>`.
- **Outputs (streaming):** `text/event-stream` of `chat.completion.chunk` objects terminated by `data: [DONE]`. Tool activity is also emitted as a **custom** SSE event `event: hermes.tool.progress` whose payload carries `{tool, emoji, label, toolCallId, status}` — `status: "running"` on start (label from `agent.display.build_tool_preview`, emoji from `get_tool_emoji`) and `status: "completed"` on finish. Tools whose name starts with `_` (e.g. `_thinking`) are filtered out, and a `completed` with no matching `running` is dropped so clients never see an uncorrelated event (#16588, superseding the older `tool_progress_callback("tool.started", …)` emit from #6972).
- **Errors:** 400 `Invalid JSON in request body`; 400 `Missing or invalid 'messages' field`; 400 `No user message found in messages`; 400 `Invalid session ID` (control chars `\r\n\0` or a path-traversal-shaped id, checked with `gateway.session._is_path_unsafe`); 400 `Session ID too long` (`_MAX_SESSION_HEADER_LEN`); 403 session-continuation-without-key; 500 `Internal server error: <e>` (`type: server_error`); **502** with `code: "agent_incomplete"` and an `error.hermes` block when there is no usable assistant text *and* the run failed or was partial — so SDK clients raise instead of rendering the internal failure string as `message.content`.
- **Config / env:** `API_SERVER_KEY`; `gateway.platforms.api_server.extra.model_routes` (alias → `{model, provider, …}`); `gateway.platforms.api_server.extra.direct_model_requests` (default `false` — whether a bare `model` with no `provider` overrides the gateway default); `gateway.api_server.max_concurrent_runs` (default `10`, `0` disables); `gateway.multiplex_profiles`; `MAX_REQUEST_BYTES = 10_000_000` (10 MB, enforced on `Content-Length`, `gateway/platforms/api_server.py:268`, `:1308`).
- **Edge cases / guards:** A `None` delta from the agent is a CLI box-close signal, not end-of-stream — forwarding it would truncate the SSE response and make Open WebUI miss the post-tool answer, so it is filtered and completion is detected via `agent_task.done()`. On client disconnect the agent is interrupted through `agent_ref`. Media in the final response is inlined by `_resolve_media_to_data_urls`. Error text is scrubbed by `_redact_api_error_text`.
- **Rebuild notes:** Map (system → ephemeral prompt, last user message → input, rest → history); derive a stable session id from the conversation fingerprint so stateless frontends still get continuity; return OpenAI shapes exactly and put every Hermes extra behind an `hermes` key or an `X-Hermes-*` header. A better version would stream tool calls in the native `tool_calls` delta channel as well as the custom event.

### `POST /v1/responses` — OpenAI Responses API  `id: acp-mcp-dev.api-responses`
- **Surface:** API
- **Where:** `http://<host>:8642/v1/responses` (and the `/p/<profile>/` prefixed form).
- **What it does:** The stateful OpenAI Responses shape: send `input`, optionally chain to a previous response or a named conversation, and get back a `response` object with typed output items.
- **How it works:** `_handle_responses()` (`gateway/platforms/api_server.py:6225`). Normalises `input` (a string → one user message; an array of strings and/or `{role, content}` dicts, each content passed through `_normalize_multimodal_content`); everything but the last input message is appended to history and the last becomes `user_message`. History precedence: explicit `conversation_history` in the body > `previous_response_id` chaining. `conversation` resolves through `_response_store.get_conversation(name)` to the latest response id (a missing conversation is simply new, not an error). `truncation: "auto"` runs `_auto_truncate_response_history`. The session id is reused from the chained response so the dashboard groups the whole conversation under one entry.
- **Inputs / options (body):** `input` (required — string or array), `instructions` (ephemeral system prompt; carried forward from the chained response when omitted), `previous_response_id`, `conversation` (mutually exclusive with `previous_response_id`), `conversation_history` (array of `{role, content}`), `store` (bool, default `true`), `truncation` (`"auto"`), `stream` (bool, default `false`), `model`, `provider`, `model_options`, `tools`.
- **Inputs / options (headers):** `Authorization`, `X-Hermes-Session-Key`, `Idempotency-Key` (fingerprint keys: `input`, `instructions`, `previous_response_id`, `conversation`, `model`, `provider`, `model_options`, `tools`).
- **Outputs (non-streaming):** `{"id": "resp_<28 hex>", "object": "response", "status": "completed", "created_at": <epoch>, "model": …, "output": [<typed items>], "usage": {"input_tokens", "output_tokens", "total_tokens"}}`, with header `X-Hermes-Session-Id` (the *effective* session id, so a compression-driven rotation propagates and chaining does not keep resuming the pre-rotation session) and `X-Hermes-Session-Key` when supplied. Output items are extracted from the current turn only via `_response_messages_turn_start_index` + `_extract_output_items`.
- **Outputs (streaming):** SSE with spec-compliant typed events — `response.created` (initial envelope, `status=in_progress`), `response.output_text.delta`, `response.output_text.done`, `response.output_item.added` / `response.output_item.done` with `item.type == "function_call"` (the `done` event carries the finalized `arguments` string), `response.output_item.added` with `item.type == "function_call_output"` carrying `{call_id, output, status}`, `response.completed` (terminal, full response object with all output items + usage, same payload shape as the non-streaming path), and `response.failed` (terminal, on agent error). SSE headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, plus CORS headers when an `Origin` is present. Function-call arguments longer than the cap are replaced with `"[<n> chars — truncated for response.completed]"` to keep the terminal event under ~100 KB.
- **Storage:** With `store: true` the full response object, the complete conversation history (including tool calls, built by `_build_response_conversation_history`), the `instructions` and the effective `session_id` go into `_response_store`; a named `conversation` is updated to point at the new response id. In streaming mode an `in_progress` snapshot is persisted immediately after `response.created`, and a client disconnect updates it to an `incomplete` snapshot so `GET /v1/responses/{id}` and `previous_response_id` chaining still have something to recover from.
- **Errors:** 400 `Invalid JSON in request body`; 400 `Missing 'input' field`; 400 `'input' must be a string or array`; 400 `Cannot use both 'conversation' and 'previous_response_id'`; 400 `'conversation_history' must be an array of message objects`; 400 `conversation_history[<i>] must have 'role' and 'content' fields`; 400 multimodal validation errors (with `param` pointing at `input[<i>].content` or `conversation_history[<i>].content`); 400 `No user message found in input`; 404 `Previous response not found: <id>`; 500 `Internal server error: <e>`.
- **Config / env:** as for chat completions.
- **Edge cases / guards:** Providing both `conversation_history` and `previous_response_id` logs a debug line and uses the explicit history. A disconnect interrupts the agent (`agent.interrupt()`) before cancelling the asyncio task.
- **Rebuild notes:** Chain by storing the whole history under the response id; always persist the *effective* session id after the run, not the one you minted before it.

### `GET /v1/responses/{response_id}`  `id: acp-mcp-dev.api-get-response`
- **Surface:** API
- **What it does:** Retrieves a stored response object.
- **How it works:** `_handle_get_response()` (`gateway/platforms/api_server.py:6552`): auth check, then `_response_store.get(response_id)`.
- **Inputs / options:** path param `response_id`; `Authorization` header.
- **Outputs / side effects:** the stored `response` object, or 404 `Response not found: <id>`.
- **Rebuild notes:** n/a.

### `DELETE /v1/responses/{response_id}`  `id: acp-mcp-dev.api-delete-response`
- **Surface:** API
- **What it does:** Deletes a stored response.
- **How it works:** `_handle_delete_response()` (`gateway/platforms/api_server.py:6566`).
- **Inputs / options:** path param `response_id`; `Authorization` header.
- **Outputs / side effects:** `{"id": <id>, "object": "response", "deleted": true}`, or 404 `Response not found: <id>`.
- **Rebuild notes:** n/a.

### `GET /v1/models`  `id: acp-mcp-dev.api-models`
- **Surface:** API
- **What it does:** Advertises the stable virtual Hermes model plus every configured `model_routes` alias, in the OpenAI model-list shape.
- **How it works:** `_handle_models()` (`gateway/platforms/api_server.py:3227-3272`). Auth first. Under a `/p/<profile>/` prefix the primary model id follows that profile's config (`self._resolve_model_name("")` when `_api_request_profile` is set) instead of the default adapter's cached `_model_name`. The primary entry is `{"id": <model_name>, "object": "model", "created": <now>, "owned_by": "hermes", "permission": [], "root": <model_name>, "parent": null}`; each alias in `_model_routes` (skipping one equal to the primary) is appended as `{"id": <alias>, "object": "model", "created": <now>, "owned_by": "hermes", "permission": [], "root": route.model or alias, "parent": <model_name>}`.
- **Inputs / options:** `Authorization` header only.
- **Outputs / side effects:** `{"object": "list", "data": [...]}`.
- **Edge cases / guards:** Only the alias and the resolved model name are exposed — never provider credentials.
- **Rebuild notes:** Advertise one stable virtual model so generic clients hardcoding `gpt-4o` still work, and treat that virtual id as "use the gateway default" in `_request_agent_overrides`.

### `GET /api/model/options` — Hermes provider/model inventory  `id: acp-mcp-dev.api-model-options`
- **Surface:** API
- **What it does:** Returns the same provider/model inventory the dashboard and TUI model pickers use, so an external client can sync to the user's real catalogue instead of scraping the single `/v1/models` alias.
- **How it works:** `_handle_model_options()` (`gateway/platforms/api_server.py:3274+`): auth, then `hermes_cli.inventory.build_model_options_payload(load_picker_context(), include_unconfigured=True, refresh=<query>)` run with `asyncio.to_thread` so pricing/catalog fetches stay off aiohttp's loop.
- **Inputs / options:** query `refresh` (bool, default `false`); `Authorization` header.
- **Outputs / side effects:** the inventory payload as JSON.
- **Rebuild notes:** Keep the OpenAI-shaped `/v1/models` and the native inventory as two separate endpoints; they answer different questions.
