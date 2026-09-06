# Configuration keys A — General, Agent, Terminal, Display, Delegation, Memory, Compression, Security, Browser, Voice, Text-to-Speech, Speech-to-Text, Logging

This shard documents every `config.yaml` key that the Hermes web dashboard Config page (`/config`) files under its first thirteen tabs — `General` (25), `Agent` (102), `Terminal` (31), `Display` (87), `Delegation` (15), `Memory` (7 in the live schema; the page hides `memory.provider` so it shows 6), `Compression` (32), `Security` (31), `Browser` (25), `Voice` (14), `Text-to-Speech` (30), `Speech-to-Text` (26) and `Logging` (3) — 428 keys in total, as served by `GET /api/config/schema` on the live v2026.8.31 install. Each entry gives the dotted key, the label the dashboard renders, the field type/options, the shipped default from `hermes_cli/config_defaults.py`, what the key changes at runtime (with `path:line` citations into the real readers), the related environment variable, and rebuild notes.
It deliberately leaves to sibling shards: the remaining Config tabs (`Discord`, `Auxiliary`, `Bedrock`, `Curator`, `Database`, `Desktop`, `Gateway`, `Kanban`, `Loops`, `Lsp`, `Matrix`, `Mattermost`, `Moa`, `Model_catalog`, `Monitoring`, `Openrouter`, `Proxy` (the 5 non-security proxy keys), `Secrets`, `Sessions`, `Slack`, `Streaming`, `Tool_loop_guardrails`, `Tool_output`, `Tools`, `Vertex`, `Wake_word`, `Web`, `X_search`), the Config page chrome itself (Save/YAML/Import/Export/Reset buttons, search box), the `hermes config` CLI sub-commands, the slash commands that flip these keys at runtime, and keys that exist in `DEFAULT_CONFIG` as dicts/lists-of-dicts and therefore never surface as schema fields (`providers`, `credential_pool_strategies`, `agent.reasoning_overrides`, `terminal.docker_env`, `display.status_phrases`, `display.platforms.<x>.<other>`, `compression.model_thresholds`, `tts.providers`, `stt.providers`, `personalities`, `quick_commands`, `platform_hints`, `hooks`, `honcho`, `onboarding.seen`, `mcp_servers`).
Shared mechanics (how a key becomes a dashboard field, how labels are generated, how values are saved) are given once in the first entry and not repeated.

## Shared mechanics

### Config page field model (applies to every key below)  `id: config-a.config-page-field-model`
- **Surface:** Web dashboard | Config | API
- **Where:** `Web dashboard → CONFIG` (nav link text `CONFIG`, href `/config`, `i18n: app.nav.config = "Config"`) → left rail `FILTERS` / `SECTIONS` (`i18n: config.filters`, `config.sections`) → one tab button per category, rendered as `<CategoryName> <count>` (e.g. `General 25`, `Agent 102`, `Terminal 31`, `Display 87`, `Delegation 15`, `Memory 6`, `Compression 32`, `Security 31`, `Browser 25`, `Voice 14`, `Text-to-Speech 30`, `Speech-to-Text 26`, `Logging 3`; names come from `i18n: config.categories.*` in `web/src/i18n/en.ts` — `general: "General"`, `agent: "Agent"`, `terminal: "Terminal"`, `display: "Display"`, `delegation: "Delegation"`, `memory: "Memory"`, `compression: "Compression"`, `security: "Security"`, `browser: "Browser"`, `voice: "Voice"`, `tts: "Text-to-Speech"`, `stt: "Speech-to-Text"`, `logging: "Logging"`). The card header repeats the tab name plus a badge `N field(s)` (`i18n: config.fields = "field{s}"`).
- **What it does:** Turns every scalar leaf of `DEFAULT_CONFIG` into an editable form field, grouped into tabs, and writes the edited object back to `~/.hermes/config.yaml` on `SAVE`.
- **How it works:** `hermes_cli/web_server.py:1529-1567` `_build_schema_from_config()` walks `DEFAULT_CONFIG` recursively; each non-dict leaf becomes `{type, description, category}`. `type` is inferred from the Python default (`_infer_type` at `web_server.py:1515`: bool→`boolean`, int/float→`number`, list→`list`, dict→`object`, else `string`). `description` defaults to the key path with `.`→` → ` and `_`→` ` then `.title()` (so `agent.max_turns` renders "Agent → Max Turns"); `category` is the first path segment (top-level scalars go to `general`). `_SCHEMA_OVERRIDES` (`web_server.py:1271-1436`) replaces type/description/options for ~30 keys (all `select` fields below come from there). `_CATEGORY_MERGE` (`web_server.py:1439-1500`) folds small sections into big tabs: `privacy`,`approvals`,`telemetry`,`proxy`→`security`; `context`,`skills`,`cron`,`network`,`models_dev`,`checkpoints`,`code_execution`,`prompt_caching`,`bot_mode`,`goals`,`onboarding`,`mcp`,`computer_use`,`plugins`,`runtime`→`agent`; `human_delay`,`dashboard`→`display`; `updates`,`doctor`,`session`→`general`. `_CATEGORY_ORDER` (`web_server.py:1503-1507`) fixes tab order. `model_context_length` is a virtual field injected right after `model` (`web_server.py:1570-1577`). `GET /api/config/schema` (`web_server.py:7285-7292`) re-computes `tts.provider`/`stt.provider`/`memory.provider`/`terminal.backend` option lists per request (`_schema_with_dynamic_provider_options`, `web_server.py:1718`). The SPA (`web/src/pages/ConfigPage.tsx:170-201`) loads `/api/config`, `/api/config/schema`, `/api/config/defaults`, `/api/config/raw`; it deletes `memory.provider` from the form (`ConfigPage.tsx:181`). Each field is drawn by `web/src/components/AutoField.tsx`: label = last key segment with `_`→space and each word capitalised (`AutoField.tsx:97-98`; the theme renders it uppercase, so the crawl shows `MAX TURNS`); under the label a `FieldHint` shows the dotted key path (only for nested keys) and the schema description (`AutoField.tsx:6-18`). `boolean`→`Switch` (role `switch`); `select`→`Select` combobox listing `options` (empty option shown as `(none)`); `number`→`<input type="number">` (empty → 0); `list`→text input with placeholder `comma-separated values` split on commas; `text`→textarea; everything else→plain text input; dict/list-of-dict values→nested `NestedValueEditor` (`AutoField.tsx:40-91`). Within a tab, a dim section divider shows the sub-section name when a key's first segment differs from the tab name (e.g. `session`, `updates`, `doctor` inside General; `checkpoints`, `skills`, `cron` inside Agent) — `ConfigPage.tsx:381-419`. Saving: `SAVE` → `PUT /api/config` with the whole object; `YAML` mode edits the raw file via `/api/config/raw`.
- **Inputs / options:** per-field widgets listed above; page-level controls (`Search...` box, `Export config as JSON`, `Import config from JSON`, `Reset <Tab> to defaults`, `YAML`/`Form` toggle, `SAVE`) are documented by the web-dashboard shard.
- **Outputs / side effects:** writes `~/.hermes/config.yaml` (profile-scoped via `?profile=`); many keys are also readable/writable with `hermes config get|set|unset <dotted.key>`; the gateway hot-reloads some sections (compression, model context length) on the next message.
- **Config / env:** n/a (meta entry).
- **Edge cases / guards:** `_config_version` is skipped; keys whose default is a dict (`agent.reasoning_overrides`, `terminal.docker_env`, …) never appear; `stt.provider` has an override entry but no seeded default so it is absent from the schema (see STT section); `number` inputs write `0` when cleared, which for keys whose default is `null` (e.g. `agent.max_turns`) changes semantics — see individual entries.
- **Rebuild notes:** Generate a JSON schema from a defaults tree + an override table + a category merge map; render generic widgets by type. A better version would carry min/max/unit/enum metadata and per-key "requires restart" flags in the schema instead of leaving that knowledge in code comments.

## General (25 fields)

### Model  `id: config-a.model`
- **Surface:** Config | CLI | Web dashboard
- **Where:** Config page tab `General` → label `MODEL`, description `Default model (e.g. anthropic/claude-sonnet-4.6)` (override at `hermes_cli/web_server.py:1282`); `config.yaml` key `model` (also accepts the nested form `model: {default: …, provider: …, base_url: …}` — `cli-config.yaml.example:44-46`); `hermes config set model <id>`.
- **What it does:** Names the default chat model for every surface (CLI, TUI, gateway, cron) unless overridden per invocation (`--model`) or per session (`/model`).
- **How it works:** `DEFAULT_CONFIG["model"] = ""` (`config_defaults.py:8`). The web normaliser flattens the nested `model:` dict into the top-level string for the form (`_normalize_config_for_web`, `web_server.py:7262`). Readers: `hermes_constants.py:1497-1502` resolves `model.default` or `model.model`; `model_tools.py:712-715`; `cli.py:155-158`. Provider/base_url/api_key live in the nested dict (out of this shard).
- **Inputs / options:** free string, e.g. `anthropic/claude-opus-4.6`, `openrouter/…`, `qwen3.5:397b`; the Models page offers pickers.
- **Outputs / side effects:** sets which model id is sent on API calls; drives context-length auto-detection.
- **Config / env:** `model` (nested `model.default`); env `HERMES_MODEL` overrides at runtime.
- **Edge cases / guards:** empty string = provider default / onboarding picks one; `/model` in a session persists to config only with `--global`.
- **Rebuild notes:** Single string setting resolved through provider registry. Better: validate against the live model catalog and show pricing/context in the field.

### Model context length  `id: config-a.model_context_length`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `MODEL CONTEXT LENGTH`, description `Context window override (0 = auto-detect from model metadata)` (`web_server.py:1287-1291`). Virtual field: not a `DEFAULT_CONFIG` key; the SPA reads/writes it and the normaliser maps it to `model.context_length` in `config.yaml`.
- **What it does:** Pins the total context window (input+output tokens) used for compression triggers and request validation when auto-detection is wrong.
- **How it works:** Injected after `model` in `CONFIG_SCHEMA` (`web_server.py:1570-1577`). Runtime resolution `agent.model_metadata.get_model_context_length` (`hermes_cli/model_switch.py:1385-1417`, `tui_gateway/server.py:12882`) prefers the config override, then models.dev metadata. Editing it on a running gateway takes effect next message (docs `configuration.md` "Gateway hot-reload").
- **Inputs / options:** integer tokens; `0`/empty = auto.
- **Outputs / side effects:** changes compaction threshold arithmetic (`compression.threshold × context_length`).
- **Config / env:** `model.context_length`.
- **Edge cases / guards:** distinct from `max_tokens` (output cap) — `cli-config.yaml.example:98-117`.
- **Rebuild notes:** One integer override layered over provider metadata. Better: show the auto-detected value next to the override.

### Fallback providers  `id: config-a.fallback_providers`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `FALLBACK PROVIDERS`, placeholder `comma-separated values`; `config.yaml` `fallback_providers` (list).
- **What it does:** Ordered list of provider/model entries tried when the primary model call fails (rate-limit, connectivity, payment).
- **How it works:** Default `[]` (`config_defaults.py:10`). Consumed by `agent/agent_init.py:1573` (modern list format vs legacy `fallback_model`), `agent/auxiliary_client.py:6081-6110` (also used as the `auto` fallback chain for auxiliary tasks), `tui_gateway/server.py:8571`. Each entry is a dict `{provider, model, base_url, api_key, reasoning_echo}`; the generic list widget can only round-trip plain strings, so real editing happens in YAML.
- **Inputs / options:** list of entries; per-entry keys `provider`, `model`, `base_url`, `api_key`, `reasoning_echo`.
- **Outputs / side effects:** provider switch mid-conversation on failure; `agent.api_max_retries` governs how many retries precede the switch.
- **Config / env:** `fallback_providers`; legacy `fallback_model`.
- **Edge cases / guards:** the dashboard list input splits on commas and would flatten dict entries — edit in YAML mode.
- **Rebuild notes:** Ordered failover chain. Better: structured editor with per-entry health status.

### Toolsets  `id: config-a.toolsets`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `TOOLSETS`, placeholder `comma-separated values`; `config.yaml` `toolsets`.
- **What it does:** Legacy global toolset list (default `["hermes-cli"]`).
- **How it works:** `config_defaults.py:12`. `cli-config.yaml.example:1352-1355` states the top-level `toolsets` key is deprecated and ignored in favour of `platform_toolsets` (managed by `hermes tools`); `batch_runner.py:318-330` still samples `toolsets` for batch runs.
- **Inputs / options:** toolset names (`web`, `terminal`, `file`, `browser`, `vision`, `image_gen`, `skills`, `todo`, `memory`, `session_search`, `tts`, `cronjob`, presets `hermes-cli`, `hermes-telegram`, …).
- **Outputs / side effects:** none on the interactive CLI/gateway (deprecated).
- **Config / env:** `toolsets`; `hermes chat --toolsets a,b` per run.
- **Edge cases / guards:** Deprecated — use `platform_toolsets` / `agent.disabled_toolsets`.
- **Rebuild notes:** Keep one authoritative per-platform allowlist; drop the legacy global list.

### Max concurrent sessions  `id: config-a.max_concurrent_sessions`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `MAX CONCURRENT SESSIONS` (type `string` because the default is `null`); `config.yaml` `max_concurrent_sessions`.
- **What it does:** Global cap on simultaneously *active* chat sessions across CLI, TUI/dashboard and messaging; `null`/`0` = unbounded.
- **How it works:** `config_defaults.py:30`. Resolved by `hermes_cli/active_sessions.py:62-76` (`resolve_max_concurrent_sessions`: top-level key wins, else `gateway.max_concurrent_sessions`), coerced by `coerce_max_concurrent_sessions` (`active_sessions.py:30-56`: bool/negative/non-int → warning + None). A slot is taken on a session's first turn, tracked in a local runtime lease file; `hermes status` shows holders (`hermes_cli/status.py:665-676`). Fails open if the lease registry cannot be read/locked. Gateway dataclass field `gateway/config.py:973`.
- **Inputs / options:** positive integer; `null`/`0` disables.
- **Outputs / side effects:** new sessions beyond the cap receive a limit message naming the surfaces holding slots.
- **Config / env:** `max_concurrent_sessions` (fallback `gateway.max_concurrent_sessions`).
- **Edge cases / guards:** best-effort, single host/profile only; not for a shared `$HERMES_HOME` across machines.
- **Rebuild notes:** Lease file + counter. Better: per-surface quotas and queueing instead of a hard error.

### Max live sessions  `id: config-a.max_live_sessions`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `MAX LIVE SESSIONS`; `config.yaml` `max_live_sessions` (number, default `16`).
- **What it does:** Soft LRU cap on in-memory TUI/desktop/dashboard sessions held by the TUI gateway; beyond it, least-recently-active *detached* sessions are evicted from memory (re-resumed from disk when reopened).
- **How it works:** `config_defaults.py:35`; `tui_gateway/server.py:1873-1905` `_max_live_sessions()` reads the top-level key, falls back to `gateway.max_live_sessions`, coerces with `coerce_max_concurrent_sessions(key="max_live_sessions")`, and evicts only sessions with no live client.
- **Inputs / options:** integer; `0`/`null` disables.
- **Outputs / side effects:** memory bounded; evicted sessions stay on disk.
- **Config / env:** `max_live_sessions` (fallback `gateway.max_live_sessions`).
- **Edge cases / guards:** never evicts attached sessions.
- **Rebuild notes:** LRU over session objects keyed by last activity. Better: evict by measured memory, not count (see `agent.agent_cache.memory_high_mb`).

### Session → Terminal continue  `id: config-a.session.terminal_continue`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section divider `session` → label `TERMINAL CONTINUE`, key path `session.terminal_continue`, description `Session → Terminal Continue` (switch); `config.yaml` `session.terminal_continue` (default `true`).
- **What it does:** Makes a bare `hermes -c` / `--continue` resume the session that belongs to *this terminal* (tmux pane, kitty window, wezterm pane, tty) instead of the globally most-recent session.
- **How it works:** Each CLI session writes a breadcrumb file under `$HERMES_HOME/terminal-sessions/<terminal-id>` (`hermes_cli/terminal_breadcrumbs.py:13`); gate `terminal_breadcrumbs.py:79-83` reads the key; `cli.py:13758` and `hermes_cli/main.py:1929` fall back to latest-session when false.
- **Inputs / options:** boolean.
- **Outputs / side effects:** breadcrumb files under `~/.hermes/terminal-sessions/`.
- **Config / env:** `session.terminal_continue`.
- **Edge cases / guards:** terminals without a stable id fall back to latest.
- **Rebuild notes:** Map terminal identity → last session id. Better: also key by cwd/project.

### Context file max chars  `id: config-a.context_file_max_chars`
- **Surface:** Config
- **Where:** Config page tab `General` → label `CONTEXT FILE MAX CHARS` (type `string`, default `null`); `config.yaml` `context_file_max_chars`.
- **What it does:** Hard cap (characters) on each automatic context file (`SOUL.md`, `AGENTS.md`, `CLAUDE.md`, `.hermes.md`, `.cursorrules`) before head/tail truncation; `null` = dynamic cap scaled to the model window (floor 20K, ceiling 500K).
- **How it works:** `config_defaults.py:725-729`; `agent/prompt_builder.py:1453-1471` `_get_context_file_max_chars()`: explicit positive value wins, else `_dynamic_context_file_max_chars(context_length)` (`prompt_builder.py:1438`), else 20K constant; applied at `prompt_builder.py:2167`.
- **Inputs / options:** positive integer or `null`.
- **Outputs / side effects:** truncation warnings surfaced to the user by `run_agent`.
- **Config / env:** `context_file_max_chars`.
- **Edge cases / guards:** independent of `read_file` limits (`file_read_max_chars`, `tool_output.*`).
- **Rebuild notes:** Character budget with smart head/tail truncation. Better: token-aware budget per file with priorities.

### File read max chars  `id: config-a.file_read_max_chars`
- **Surface:** Config | Tool
- **Where:** Config page tab `General` → label `FILE READ MAX CHARS` (number, default `100000`); `config.yaml` `file_read_max_chars`.
- **What it does:** Maximum characters a single `read_file` call may return; larger reads are rejected with guidance to use `offset`+`limit`.
- **How it works:** `config_defaults.py:734`; `tools/file_tools.py:63-82` reads it on first call and caches. Reads are deduplicated automatically (unchanged region → stub) and the dedupe resets on compression.
- **Inputs / options:** integer (docs suggest 200000 for 200K+ models, 30000 for 16K locals).
- **Outputs / side effects:** tool error text instead of content when exceeded.
- **Config / env:** `file_read_max_chars`.
- **Edge cases / guards:** ≈25–35K tokens at 100K chars.
- **Rebuild notes:** Size gate on a file tool. Better: scale automatically from the active model's context window.

### MCP discovery timeout / single-query discovery timeout  `id: config-a.mcp_discovery_timeout`
- **Surface:** Config
- **Where:** Config page tab `General` → labels `MCP DISCOVERY TIMEOUT` (number, default `1.5`) and `MCP SINGLE QUERY DISCOVERY TIMEOUT` (number, default `15.0`); `config.yaml` `mcp_discovery_timeout`, `mcp_single_query_discovery_timeout`.
- **What it does:** Seconds the first agent build waits for background MCP server discovery before snapshotting the tool list — interactive sessions use the small bound, one-shot runs (`hermes -q/-z`) use the larger one because they have no between-turn refresh.
- **How it works:** `config_defaults.py:735-759`; `hermes_cli/mcp_startup.py:127-188` picks the key by mode and `thread.join(timeout)`s; the wait returns as soon as discovery completes. Also read by `acp_adapter/session.py:674`, `tui_gateway/entry.py:269`, `tui_gateway/server.py:8810`. Servers that miss the window are picked up on the next turn by `agent/turn_context.py`.
- **Inputs / options:** floats (seconds).
- **Outputs / side effects:** affects first-response latency only.
- **Config / env:** `mcp_discovery_timeout`, `mcp_single_query_discovery_timeout`.
- **Edge cases / guards:** with no MCP servers the wait is ~0 s regardless.
- **Rebuild notes:** Bounded join on a discovery thread. Better: stream late-arriving tools into the running turn.

### Prefill messages file  `id: config-a.prefill_messages_file`
- **Surface:** Config
- **Where:** Config page tab `General` → label `PREFILL MESSAGES FILE` (string, default `""`); `config.yaml` `prefill_messages_file` (legacy `agent.prefill_messages_file`).
- **What it does:** Path to a JSON array of `{role, content}` messages injected at the start of every API call for few-shot priming; never saved to sessions, logs or trajectories.
- **How it works:** `config_defaults.py:2170-2173`; resolver `cli.py:372-387` (top-level wins, `agent.prefill_messages_file` fallback); `batch_runner.py:1332-1339` loads the file and validates it is a list.
- **Inputs / options:** filesystem path.
- **Outputs / side effects:** extra input tokens every call.
- **Config / env:** `prefill_messages_file`.
- **Edge cases / guards:** non-array JSON → error; `agent/background_review.py:1193` notes it is not applied to the background review fork.
- **Rebuild notes:** Ephemeral message prefix loaded from disk. Better: per-profile/per-platform prefills with caching-aware placement.

### Timezone  `id: config-a.timezone`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `General` → label `TIMEZONE`, description `IANA timezone (e.g. America/New_York). Blank uses the system timezone.` — searchable, clearable select of every `zoneinfo.available_timezones()` entry plus `localtime` (`web_server.py:1260-1278`); `config.yaml` `timezone` (default `""`).
- **What it does:** Overrides server-local time for log timestamps, cron scheduling and the system-prompt time injection.
- **How it works:** `config_defaults.py:2380-2382`; bridged to the environment by the gateway per turn together with `agent.max_turns` / `redact_secrets` (`gateway/run.py:2361-2380` managed-overlay comment); env `HERMES_TIMEZONE` is the documented override.
- **Inputs / options:** any IANA id; empty = system.
- **Outputs / side effects:** changes displayed/scheduled times.
- **Config / env:** `timezone`; env `HERMES_TIMEZONE`.
- **Edge cases / guards:** invalid names fall back to system time; managed-scope can pin it.
- **Rebuild notes:** One tz string threaded to logging, scheduler and prompt. Better: per-user timezone in group chats.

### Command allowlist  `id: config-a.command_allowlist`
- **Surface:** Config | Security
- **Where:** Config page tab `General` → label `COMMAND ALLOWLIST` (list); `config.yaml` `command_allowlist` (default `[]`).
- **What it does:** Permanently approved dangerous-command patterns, populated when the user chooses "always" on an approval prompt.
- **How it works:** `config_defaults.py:2607-2608`; proposed/managed by `hermes approvals` (`hermes_cli/subcommands/approvals.py:22-47` proposes entries from past approvals in the session DB); consulted by `tools/approval.py` before prompting; migration tooling merges OpenClaw patterns (`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py:1338-1387`).
- **Inputs / options:** list of pattern keys.
- **Outputs / side effects:** matching commands skip the approval prompt.
- **Config / env:** `command_allowlist`.
- **Edge cases / guards:** `approvals.deny` and the hardline blocklist still win.
- **Rebuild notes:** Persisted allowlist of pattern keys. Better: expiring entries and per-project scoping.

### Hooks auto accept  `id: config-a.hooks_auto_accept`
- **Surface:** Config | Security
- **Where:** Config page tab `General` → label `HOOKS AUTO ACCEPT` (switch, default `false`); `config.yaml` `hooks_auto_accept`.
- **What it does:** Auto-accepts shell-hook registrations (`hooks:` block) without the first-use TTY consent prompt — needed for gateway/cron/headless runs.
- **How it works:** `config_defaults.py:2647-2651`; `agent/shell_hooks.py:260-311,1065-1072` checks `--accept-hooks`, `HERMES_ACCEPT_HOOKS=1`, then this key; approvals persist in `~/.hermes/shell-hooks-allowlist.json`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** new hook commands run without confirmation.
- **Config / env:** `hooks_auto_accept`; env `HERMES_ACCEPT_HOOKS`; flag `--accept-hooks`.
- **Edge cases / guards:** security-relevant — any hook script in config runs unprompted.
- **Rebuild notes:** Consent bypass flag. Better: allowlist by script hash rather than blanket accept.

### Doctor → Live probe timeout  `id: config-a.doctor.live_probe_timeout`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section `doctor` → label `LIVE PROBE TIMEOUT`, key `doctor.live_probe_timeout` (number, default `10`).
- **What it does:** Per-probe timeout (seconds) for `hermes doctor --live` real-call backend probes (Firecrawl/FAL/browser/MCP/TTS/STT).
- **How it works:** `config_defaults.py:3502-3506`; `hermes_cli/doctor_live.py:9,277`.
- **Inputs / options:** number.
- **Outputs / side effects:** none beyond doctor output.
- **Config / env:** `doctor.live_probe_timeout`.
- **Edge cases / guards:** only with `--live`.
- **Rebuild notes:** Timeout constant for diagnostics.

### Updates → Pre-update backup / Backup keep  `id: config-a.updates.pre_update_backup`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section `updates` → labels `PRE UPDATE BACKUP` (string, default `quick`) and `BACKUP KEEP` (number, default `5`); keys `updates.pre_update_backup`, `updates.backup_keep`.
- **What it does:** Chooses the safety backup taken before `hermes update`: `quick` snapshots critical small state files (pairing JSONs, cron jobs, config.yaml, .env, auth.json, per-profile DBs) into `<HERMES_HOME>/state-snapshots/` (files > 1 GiB skipped); `full` adds a `hermes backup`-style zip of the whole home into `<HERMES_HOME>/backups/` (restorable with `hermes import`); `off` disables both. `backup_keep` = number of full zips retained (floored at 1; quick snapshot always keeps exactly 1).
- **How it works:** `config_defaults.py:3509-3541`; `hermes_cli/update_cmd.py:4607-4614` (unknown value → `quick` with a warning), `update_cmd.py:4763` reads `backup_keep`, `update_cmd.py:4808`; `hermes_cli/backup.py:2224`. Legacy booleans honoured: `true`→`full`, `false`→`off`. Flags `--backup` (force full) / `--no-backup` (force off) for one run (`hermes_cli/subcommands/update.py:49-55`).
- **Inputs / options:** `quick` | `full` | `off` (| legacy `true`/`false`); integer keep count.
- **Outputs / side effects:** files under `~/.hermes/state-snapshots/` and `~/.hermes/backups/`; restore via `/snapshot` or `hermes import`.
- **Config / env:** `updates.pre_update_backup`, `updates.backup_keep`.
- **Edge cases / guards:** `full` can add minutes on large homes.
- **Rebuild notes:** Pre-mutation snapshot with retention. Better: incremental/deduplicated snapshots.

### Updates → Non-interactive local changes  `id: config-a.updates.non_interactive_local_changes`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section `updates` → label `NON INTERACTIVE LOCAL CHANGES`, select `stash` | `discard`, description `When the chat app / gateway updates Hermes (no terminal prompt), what to do with uncommitted local source edits. 'stash' keeps them and re-applies them after the update; 'discard' throws them away. Terminal updates always ask, regardless of this setting.` (`web_server.py:1410-1419`); default `stash`.
- **What it does:** Policy for uncommitted edits in the git checkout when `hermes update` runs without a TTY (desktop button, gateway `/update`, `--yes`).
- **How it works:** `config_defaults.py:3542-3557`; `hermes_cli/update_cmd.py:2803-2839,7854-7872,8819`: auto-stash, pull, then restore (`stash`) or drop the stash (`discard`; stash-and-drop, never `reset --hard`/`clean -fd`, so ignored paths survive).
- **Inputs / options:** `stash` | `discard`.
- **Outputs / side effects:** git stash entries in the source tree.
- **Config / env:** `updates.non_interactive_local_changes`.
- **Edge cases / guards:** interactive updates always prompt; tracked `package-lock.json` churn is restored before stashing.
- **Rebuild notes:** Two-mode dirty-tree policy. Better: show the diff in the desktop confirm dialog.

### Updates → Auto switch parked branch / Parked branch strategy  `id: config-a.updates.auto_switch_parked_branch`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section `updates` → labels `AUTO SWITCH PARKED BRANCH` (switch, default `true`) and `PARKED BRANCH STRATEGY` (string, default `switch`); keys `updates.auto_switch_parked_branch`, `updates.parked_branch_strategy`.
- **What it does:** When the source checkout is parked on a feature branch and the tree is clean, `hermes update` either switches back to the update target (`switch`, commits stay on the branch, loud notice) or merges `origin/<target>` into the branch (`update_in_place`, safety tag `pre-update-<stamp>`, conflict aborts cleanly). `auto_switch_parked_branch: false` never switches. A dirty tree always skips the code update with a warning.
- **How it works:** `config_defaults.py:3558-3596`; `hermes_cli/update_cmd.py:1374-1446` (opt-out), `7848,8279-8336` (strategy); `hermes update --switch-branch` overrides `update_in_place` for one run (`hermes_cli/subcommands/update.py:92`).
- **Inputs / options:** boolean; `switch` | `update_in_place`.
- **Outputs / side effects:** git checkout/merge in the install tree.
- **Config / env:** `updates.auto_switch_parked_branch`, `updates.parked_branch_strategy`.
- **Edge cases / guards:** designed after the 2026-08-17 incident where "✓ Code updated!" printed on a stale branch.
- **Rebuild notes:** Branch-state machine for self-updates. Better: detect the parked branch's upstream PR and offer rebase.

### Updates → Refresh cua-driver  `id: config-a.updates.refresh_cua_driver`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → section `updates` → label `REFRESH CUA DRIVER`, description `Refresh an already-installed cua-driver during hermes update. Disable this on non-admin macOS accounts where /Applications is not writable.` (`web_server.py:1420-1427`); switch, default `true`.
- **What it does:** Lets `hermes update` re-run the macOS cua-driver installer when the driver is already installed.
- **How it works:** `config_defaults.py:3597-3600`; `hermes_cli/update_cmd.py:9411`. Best-effort, macOS only.
- **Inputs / options:** boolean.
- **Outputs / side effects:** may rewrite `/Applications/CuaDriver.app`.
- **Config / env:** `updates.refresh_cua_driver`.
- **Edge cases / guards:** no-op off macOS.
- **Rebuild notes:** Post-update hook toggle.

### Paste collapse thresholds  `id: config-a.paste_collapse_threshold`
- **Surface:** Config | CLI
- **Where:** Config page tab `General` → labels `PASTE COLLAPSE THRESHOLD` (number, default `5`), `PASTE COLLAPSE THRESHOLD FALLBACK` (number, default `5`), `PASTE COLLAPSE CHAR THRESHOLD` (number, default `2000`); keys `paste_collapse_threshold`, `paste_collapse_threshold_fallback`, `paste_collapse_char_threshold`.
- **What it does:** In the classic CLI, a pasted block with at least N lines (bracketed-paste path: `paste_collapse_threshold`; non-bracketed fallback path: `paste_collapse_threshold_fallback`) or at least `paste_collapse_char_threshold` characters on one line collapses into a file reference instead of flooding the prompt. `0` disables the char guard.
- **How it works:** `config_defaults.py:3765-3771`; `cli.py:19625-19626` (bracketed paste) and `cli.py:19796-19797` (fallback).
- **Inputs / options:** integers.
- **Outputs / side effects:** pasted text stored to a temp file and referenced in the message.
- **Config / env:** the three keys above.
- **Edge cases / guards:** catches "8000 chars of minified JSON on one line".
- **Rebuild notes:** Paste-size heuristics. Better: preview the collapsed paste inline with expand.

## Agent (102 fields)

### Runtime → Nofile soft limit  `id: config-a.runtime.nofile_soft_limit`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → section `runtime` → label `NOFILE SOFT LIMIT`, key `runtime.nofile_soft_limit` (number, default `4096`).
- **What it does:** Raises the process `RLIMIT_NOFILE` soft limit for long-running server surfaces (gateway, `hermes serve --isolated`) at startup.
- **How it works:** `config_defaults.py:22-27`; `hermes_cli/resource_limits.py:23-86` resolves the target, clamps it to the OS hard limit, never lowers an already-higher soft limit; `0`/`false`/`null` disables. Windows/sandboxes continue silently when the limit cannot change.
- **Inputs / options:** integer; `0`/`false`/`null` = off.
- **Outputs / side effects:** `setrlimit` call at boot.
- **Config / env:** `runtime.nofile_soft_limit`.
- **Edge cases / guards:** clamp to hard limit; no effect on Windows.
- **Rebuild notes:** One `setrlimit` at boot. Better: warn when file-descriptor usage nears the limit.

### Agent → Max turns  `id: config-a.agent.max_turns`
- **Surface:** Config | CLI
- **Where:** Config page tab `Agent` → label `MAX TURNS`, key `agent.max_turns` (type `string` because default `null`); `config.yaml` `agent.max_turns`.
- **What it does:** Cap on tool-calling iterations per conversation turn. Unlimited by default; a positive integer caps it; `"none"`/`"null"`/`"unlimited"`/`"infinite"`/`"infinity"`/`"inf"`/`"∞"`/`0`/`-1` all mean unlimited.
- **How it works:** `config_defaults.py:46-50`; normalised by `hermes_cli/config.py:3341-3366` `resolve_turn_limit()` (returns `sys.maxsize` sentinel for unlimited, always ≥ 1); the gateway bridges the raw value into the `HERMES_MAX_ITERATIONS` env var per turn (`gateway/run.py:2361-2413`, `2795-2797`), cron reads it at `cron/scheduler.py:6038-6041`, CLI at `cli.py:604`. On exhaustion the agent gets one wrap-up message plus a grace call (docs "Iteration Budget"); no 70%/90% pressure warnings.
- **Inputs / options:** integer or one of the unlimited spellings.
- **Outputs / side effects:** ends the loop when reached; `hermes_cli/dump.py:238` lists it as an "interesting override".
- **Config / env:** `agent.max_turns`; env `HERMES_MAX_ITERATIONS` (bridged; a stale env value is overridden by config each turn).
- **Edge cases / guards:** the dashboard number widget writes `0` when cleared = unlimited (same as null).
- **Rebuild notes:** Iteration counter with sentinel. Better: budget by tokens/cost rather than iterations.

### Agent → Run budget seconds  `id: config-a.agent.run_budget_seconds`
- **Surface:** Config | CLI
- **Where:** Config page tab `Agent` → label `RUN BUDGET SECONDS`, key `agent.run_budget_seconds` (string, default `null`); CLI equivalent `hermes chat --run-budget N`.
- **What it does:** Optional wall-clock budget per conversation run: at 80 % elapsed a one-time wrap-up notice is appended to the newest tool result, and implicit non-streaming stale timeouts are capped to `max(60, remaining × 0.5)`.
- **How it works:** `config_defaults.py:51-56`; `agent/agent_init.py:1027-1029,2008-2012` (`_normalize_run_budget_seconds`), `agent/conversation_loop.py:120,205,2232`. Dormant when unset (no clock reads). Explicit `stale_timeout_seconds` always wins over the cap.
- **Inputs / options:** positive number of seconds; `null` = off.
- **Outputs / side effects:** injected system-style notice; tightened timeouts.
- **Config / env:** `agent.run_budget_seconds`; CLI `--run-budget`.
- **Edge cases / guards:** resets on each user message; only tightens, never raises timeouts.
- **Rebuild notes:** Deadline-aware loop with a single wrap-up nudge. Better: expose remaining budget to the model as a tool.

### Agent → Gateway timeout  `id: config-a.agent.gateway_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `GATEWAY TIMEOUT`, key `agent.gateway_timeout` (number, default `1800`).
- **What it does:** Inactivity timeout (seconds) for gateway agent runs — fires only when the agent has been completely idle (no tool calls, no API tokens) for this long; `0` = unlimited.
- **How it works:** `config_defaults.py:57-61`; bridged to env `HERMES_AGENT_TIMEOUT` at `gateway/run.py:2798-2799`; consumed at `gateway/run.py:31026-31033` (`_float_env("HERMES_AGENT_TIMEOUT", 1800)`; non-positive → None). Error text points users here (`gateway/run.py:31309`).
- **Inputs / options:** seconds.
- **Outputs / side effects:** kills the turn with a timeout message.
- **Config / env:** `agent.gateway_timeout`; env `HERMES_AGENT_TIMEOUT` (env takes precedence).
- **Edge cases / guards:** distinct from `session_stall_timeout` (notify-only) and `gateway_notify_interval` (heartbeats).
- **Rebuild notes:** Idle watchdog on an activity clock.

### Agent → Gateway turn lease timeout  `id: config-a.agent.gateway_turn_lease_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `GATEWAY TURN LEASE TIMEOUT`, key `agent.gateway_turn_lease_timeout` (number, default `5`).
- **What it does:** Max seconds an inbound message whose alias routing key resolves to a session already holding a turn lease waits before being rejected with a "resend" notice (never run unserialised, never auto-requeued).
- **How it works:** `config_defaults.py:62-69`; default pulled from `DEFAULT_CONFIG` at `gateway/run.py:2646`; bridged to `HERMES_TURN_LEASE_TIMEOUT` (`gateway/run.py:2800-2803`). Non-positive → 5 s.
- **Inputs / options:** seconds.
- **Outputs / side effects:** rejection notice to the user.
- **Config / env:** `agent.gateway_turn_lease_timeout`; env `HERMES_TURN_LEASE_TIMEOUT`.
- **Edge cases / guards:** keep short — Telegram dispatches updates sequentially so a waiter delays unrelated topics.
- **Rebuild notes:** Per-session lease with bounded wait. Better: durable queue with idempotency keys so the message can be requeued.

### Agent → Agent cache → Max size / Idle TTL  `id: config-a.agent.agent_cache.max_size`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → labels `MAX SIZE` (key `agent.agent_cache.max_size`, number, default `128`) and `IDLE TTL SECS` (key `agent.agent_cache.idle_ttl_secs`, number, default `3600`).
- **What it does:** Bounds the gateway's per-session `AIAgent` cache by entry count (LRU) and by idle time.
- **How it works:** `config_defaults.py:70-80`; defaults referenced at `gateway/run.py:78-79`. Each cached agent keeps a warm prompt prefix plus the full transcript, so the cache trades memory for cost.
- **Inputs / options:** integers.
- **Outputs / side effects:** evicted agents reload from the persisted session on next turn.
- **Config / env:** `agent.agent_cache.max_size`, `agent.agent_cache.idle_ttl_secs`.
- **Edge cases / guards:** neither bound knows bytes — see the memory budget entry.
- **Rebuild notes:** LRU + TTL map.

### Agent → Agent cache → Memory high MB / Max evictions per pass / Protect recent  `id: config-a.agent.agent_cache.memory_high_mb`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → labels `MEMORY HIGH MB` (key `agent.agent_cache.memory_high_mb`, string, default `auto`), `MAX EVICTIONS PER PASS` (`agent.agent_cache.max_evictions_per_pass`, number, default `16`), `PROTECT RECENT` (`agent.agent_cache.protect_recent`, number, default `8`).
- **What it does:** Anonymous-RSS budget above which the gateway sheds least-recently-used transcripts; `auto` derives it from the cgroup memory limit (or total RAM); a number sets it; `0`/`off` disables. `max_evictions_per_pass` bounds one pressure pass; `protect_recent` MRU sessions are never touched.
- **How it works:** `config_defaults.py:81-95`; `gateway/agent_cache_pressure.py:200-217` (`resolve_memory_high_mb`, `_positive_int`). Mid-turn sessions and sessions with unflushed transcripts are never shed; eviction logs at WARNING with measured RSS.
- **Inputs / options:** number/`auto`/`0`; integers.
- **Outputs / side effects:** WARNING log `Agent cache pressure: anon RSS … over budget … — evicting N LRU session(s)`.
- **Config / env:** the three keys above.
- **Edge cases / guards:** respects systemd `MemoryMax`/`MemoryHigh` via cgroup detection.
- **Rebuild notes:** RSS sampler + LRU shedding. Better: per-session memory accounting.

### Agent → Restart drain timeout  `id: config-a.agent.restart_drain_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `RESTART DRAIN TIMEOUT`, key `agent.restart_drain_timeout` (number, default `0`).
- **What it does:** Force-interrupt budget (seconds) once gateway `stop()`/drain has begun (SIGTERM, external stop, final phase of in-band restart). `0` = interrupt immediately.
- **How it works:** `config_defaults.py:96-106`; default from `DEFAULT_CONFIG` at `gateway/restart.py:25`; bridged to `HERMES_RESTART_DRAIN_TIMEOUT` (`gateway/run.py:2807`); `gateway/shutdown_watchdog.py:44` adds a leash beyond it; `hermes_cli/gateway.py:312-313,5127,5528-5539`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** in-flight chat turns interrupted and announced; resumed on the user's next message.
- **Config / env:** `agent.restart_drain_timeout`; env `HERMES_RESTART_DRAIN_TIMEOUT`.
- **Edge cases / guards:** keep under systemd `TimeoutStopSec` or risk SIGKILL mid-cleanup; prefer `restart_after_turn_timeout` for graceful restarts.
- **Rebuild notes:** Two-phase shutdown (wait, then force).

### Agent → Cron drain timeout  `id: config-a.agent.cron_drain_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `CRON DRAIN TIMEOUT`, key `agent.cron_drain_timeout` (number, default `30`).
- **What it does:** Cron-only floor under the stop/drain wait so an in-flight cron run is not recorded as a permanent failure in `jobs.json` when the gateway restarts; `0` = opt out (cron drains on `restart_drain_timeout`).
- **How it works:** `config_defaults.py:107-116`; `gateway/restart.py:49`; read via `cfg_get(cfg, "agent", "cron_drain_timeout")` at `gateway/run.py:10416`; clamped at runtime to the shutdown-watchdog leash minus teardown headroom (raising past ~50 s needs a matching `TimeoutStopSec`).
- **Inputs / options:** seconds.
- **Outputs / side effects:** delays restart while cron jobs finish.
- **Config / env:** `agent.cron_drain_timeout`.
- **Edge cases / guards:** warning at `gateway/run.py:13489` suggests shortening both drain keys when shutdown is slow.
- **Rebuild notes:** Separate drain floor for unattended work.

### Agent → Restart after turn timeout  `id: config-a.agent.restart_after_turn_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `RESTART AFTER TURN TIMEOUT`, key `agent.restart_after_turn_timeout` (number, default `1800`).
- **What it does:** For in-band restarts (`/restart`, SIGUSR1) the gateway refuses new work and waits up to this many seconds for active agents/cron/api runs to finish before entering `stop()`; `0` = legacy immediate stop.
- **How it works:** `config_defaults.py:117-127`; `gateway/restart.py:38`; `gateway/run.py:10393`; `hermes_cli/gateway.py:312,5939-5940`; tip text `hermes_cli/tips.py:295`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** restart may block until the turn ends.
- **Config / env:** `agent.restart_after_turn_timeout`.
- **Edge cases / guards:** 30 min default is a safety valve for wedged agents, not a target latency.
- **Rebuild notes:** Graceful-restart barrier.

### Agent → Build wait timeout  `id: config-a.agent.build_wait_timeout`
- **Surface:** Config | Gateway/Telegram | TUI
- **Where:** Config page tab `Agent` → label `BUILD WAIT TIMEOUT`, key `agent.build_wait_timeout` (number, default `600`).
- **What it does:** Upper bound (seconds) a submitted prompt waits for the deferred agent build (MCP discovery, model metadata, skills scan) before failing with a visible error; a progress notice is emitted past 30 s.
- **How it works:** `config_defaults.py:128-136`; `tui_gateway/server.py:3123-3161`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** error to the client on a hung build.
- **Config / env:** `agent.build_wait_timeout`.
- **Edge cases / guards:** raise for deployments with many slow MCP servers.
- **Rebuild notes:** Bounded wait on a build future.

### Agent → API max retries  `id: config-a.agent.api_max_retries`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `API MAX RETRIES`, key `agent.api_max_retries` (number, default `3`).
- **What it does:** Hermes-level retry attempts for API errors (connection drops, provider timeouts, 5xx) before the failure surfaces / fallback providers engage (the OpenAI SDK's own `max_retries=2` sits underneath).
- **How it works:** `config_defaults.py:137-145`; `agent/agent_init.py:2092`; tip `hermes_cli/tips.py:296`.
- **Inputs / options:** integer; docs suggest `0` for instant failover with fallback providers.
- **Outputs / side effects:** more/less retry latency.
- **Config / env:** `agent.api_max_retries`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Retry loop wrapper with backoff.

### Agent → Empty response guard  `id: config-a.agent.empty_response_guard`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `ENABLED` (key `agent.empty_response_guard.enabled`, switch, default `true`) and `COST THRESHOLD USD` (key `agent.empty_response_guard.cost_threshold_usd`, number, default `0.25`).
- **What it does:** Stops the empty-response retry loop from re-billing deterministic empties: when the estimated input cost of one empty attempt ≥ threshold, the retry budget drops from 3 to 1. Disabled → legacy fixed 3 retries.
- **How it works:** `config_defaults.py:146-162`; `agent/empty_response_guard.py:108` reads the threshold. Fails open on ambiguous evidence (missing usage, any generated tokens, model/provider change mid-streak).
- **Inputs / options:** boolean; USD float.
- **Outputs / side effects:** fewer expensive retries.
- **Config / env:** the two keys.
- **Edge cases / guards:** unknown pricing leaves the budget untouched.
- **Rebuild notes:** Cost-aware retry budget.

### Agent → Service tier  `id: config-a.agent.service_tier`
- **Surface:** Config | Provider
- **Where:** Config page tab `Agent` → label `SERVICE TIER`, description `API service tier (OpenAI/Anthropic)`, select `` (none) | `auto` | `default` | `flex` (`web_server.py:1400-1404`); default `""`.
- **What it does:** Sends the provider `service_tier` request parameter (OpenAI flex/priority processing, Anthropic tiers).
- **How it works:** `config_defaults.py:163`; `agent/agent_init.py:588,970`; the TUI/desktop fast-mode toggle rewrites it (`tui_gateway/server.py:14303-14314`: `fast` → `priority`, else None); `agent/agent_init.py:412` notes extra_body overrides are dropped on some paths.
- **Inputs / options:** `""`, `auto`, `default`, `flex` (the TUI also writes `priority`).
- **Outputs / side effects:** request field on API calls; affects billing/latency.
- **Config / env:** `agent.service_tier`.
- **Edge cases / guards:** only providers that understand the field honour it.
- **Rebuild notes:** Pass-through request parameter.

### Agent → Tool use enforcement  `id: config-a.agent.tool_use_enforcement`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `TOOL USE ENFORCEMENT`, key `agent.tool_use_enforcement` (string, default `auto`).
- **What it does:** Injects system-prompt guidance telling the model to actually call tools instead of describing intended actions. `auto` = models matching `gpt`, `codex`, `gemini`, `gemma`, `grok`, `glm`, `qwen`, `deepseek`; `true`/`false` force; a list of substrings matches by name. Gemini/Gemma additionally get "Google operational guidance".
- **How it works:** `config_defaults.py:164-169`; `agent/system_prompt.py:561`; four-mode parser mirrored in `agent/agent_runtime_helpers.py:4523`; listed in `hermes_cli/dump.py:240`.
- **Inputs / options:** `auto` | `true` | `false` | `["substr", …]`.
- **Outputs / side effects:** extra cached system-prompt block.
- **Config / env:** `agent.tool_use_enforcement`.
- **Edge cases / guards:** Claude excluded from auto.
- **Rebuild notes:** Model-family keyed prompt block. Better: measure "described-not-called" rate and auto-enable.

### Agent → Execution guidance  `id: config-a.agent.execution_guidance`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `EXECUTION GUIDANCE`, key `agent.execution_guidance` (string, default `auto`).
- **What it does:** Injects an execution-discipline block (tool persistence, mandatory tool use for arithmetic/system facts, external-write read-back, count reconciliation, literal preservation of identifiers, verification-gated completion). `auto` matches `gpt`, `codex`, `grok`, `deepseek`, `kimi`, `qwen`, `glm`, `minimax`, `mimo`, `mistral` (`EXECUTION_GUIDANCE_MODELS`, `agent/prompt_builder.py:436-439`).
- **How it works:** `config_defaults.py:170-179`; `agent/prompt_builder.py:424-434,527`; `agent/system_prompt.py:594`. Chosen once at session start so the prompt stays byte-stable.
- **Inputs / options:** `auto` | `true` | `false` | list of substrings.
- **Outputs / side effects:** cached prompt block.
- **Config / env:** `agent.execution_guidance`.
- **Edge cases / guards:** independent of `tool_use_enforcement`.
- **Rebuild notes:** Same pattern as above.

### Agent → Intent-ack continuation  `id: config-a.agent.intent_ack_continuation`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `INTENT ACK CONTINUATION`, key `agent.intent_ack_continuation` (string, default `auto`).
- **What it does:** When the model opens a turn by narrating an action ("I'll go check the logs…") but emits no tool call, intercept the turn end, inject a "continue now, execute the tools" nudge and loop (max 2 nudges/turn). `auto` = only on the `codex_responses` api_mode; `true` = all api_modes; `false` = never; list = model substrings.
- **How it works:** `config_defaults.py:180-190`; `agent/agent_runtime_helpers.py:4392`.
- **Inputs / options:** `auto` | `true` | `false` | list.
- **Outputs / side effects:** extra API call per nudge.
- **Config / env:** `agent.intent_ack_continuation`.
- **Edge cases / guards:** corrective sibling of `tool_use_enforcement` (preventive).
- **Rebuild notes:** Turn-end interceptor with bounded re-prompts.

### Agent → Stall guards  `id: config-a.agent.stall_guards`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `STALL GUARDS`, key `agent.stall_guards` (switch, default `true`).
- **What it does:** Enables (1) an identical-call loop breaker that appends a notice when the same tool is called 3+ times with identical args *and* results (never blocks; pollers `process`, `*_get_result`, `*_poll` exempt), (2) a continue-intent recovery re-prompt when the model ends saying it will continue, and (3) result-reference stubbing of byte-identical duplicate results (≥512 chars, non-error, non-multimodal).
- **How it works:** `config_defaults.py:191-200`; `run_agent.py:8475-8514`; `agent/tool_guardrails.py:65-87,345`; `agent/agent_runtime_helpers.py:4482`; `agent/conversation_loop.py:8314`.
- **Inputs / options:** boolean (disables all three together).
- **Outputs / side effects:** notices added at result construction (cache-safe).
- **Config / env:** `agent.stall_guards`.
- **Edge cases / guards:** complements `tool_loop_guardrails.*` (other shard).
- **Rebuild notes:** Duplicate detector over (tool, args, result) triples.

### Agent → Task completion guidance / Parallel tool call guidance  `id: config-a.agent.task_completion_guidance`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `TASK COMPLETION GUIDANCE` (key `agent.task_completion_guidance`, switch, default `true`) and `PARALLEL TOOL CALL GUIDANCE` (key `agent.parallel_tool_call_guidance`, switch, default `true`).
- **What it does:** Two universal short prompt blocks for all models: "finish the job" (don't stop at stubs, don't fabricate when blocked; ~80 tokens) and "batch independent tool calls into one turn" (~70 tokens).
- **How it works:** `config_defaults.py:201-218`; `agent/system_prompt.py:504` and `:515`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** cached system prompt size.
- **Config / env:** the two keys.
- **Edge cases / guards:** none.
- **Rebuild notes:** Static prompt toggles.

### Agent → Environment probe / Bot mode protocol / Environment hint  `id: config-a.agent.environment_probe`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `ENVIRONMENT PROBE` (key `agent.environment_probe`, switch, default `true`), `BOT MODE PROTOCOL` (key `agent.bot_mode_protocol`, switch, default `true`), `ENVIRONMENT HINT` (key `agent.environment_hint`, string, default `""`).
- **What it does:** `environment_probe` surfaces Python/pip/uv/PEP-668 anomalies in the system prompt (zero tokens when clean; skipped for docker/modal/ssh backends). `bot_mode_protocol` adds the Bot Mode teammate-messaging section (silent unless the profile is desktop-managed). `environment_hint` appends an embedder-supplied environment description to the prompt's environment-hints block (sandbox runner / managed platform explanation of proxies, credentials, mounts).
- **How it works:** `config_defaults.py:219-236`; `tools/env_probe.py:27`, `agent/system_prompt.py:716`; `tools/bot_mode_probe.py:27`, `agent/system_prompt.py:734`; `agent/prompt_builder.py:1406-1416` (env var `HERMES_ENVIRONMENT_HINT` wins over config).
- **Inputs / options:** booleans; free text.
- **Outputs / side effects:** prompt content.
- **Config / env:** the three keys; env `HERMES_ENVIRONMENT_HINT`.
- **Edge cases / guards:** hint does not touch the identity slot (`SOUL.md`).
- **Rebuild notes:** Prompt-assembly toggles + injectable host note.

### Agent → Coding context / Coding instructions  `id: config-a.agent.coding_context`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `CODING CONTEXT` (key `agent.coding_context`, string, default `auto`) and `CODING INSTRUCTIONS` (key `agent.coding_instructions`, string, default `""`).
- **What it does:** Coding posture on interactive coding surfaces (CLI, TUI, desktop, ACP) inside a code workspace: adds a coding operating brief + live git/workspace snapshot. `auto` = prompt-only when interactive AND cwd is a code workspace; `focus` = auto + collapse the toolset to the lean coding set (+ enabled MCP servers) + demote non-coding skill categories to names-only; `on` = force everywhere; `off` = disable. `coding_instructions` (string or list) is appended to the brief as a stable extra system block (cache-safe, next session).
- **How it works:** `config_defaults.py:237-260`; `agent/coding_context.py:39,337,359-373,486-493`; `tui_gateway/server.py:6030`; `agent/verify/recipes.py:9-11`, `agent/verification_stop.py:162`.
- **Inputs / options:** `auto` | `focus` | `on` | `off`; string or list of strings.
- **Outputs / side effects:** prompt block; in `focus`, a reduced toolset.
- **Config / env:** `agent.coding_context`, `agent.coding_instructions`.
- **Edge cases / guards:** messaging platforms unaffected in `auto`.
- **Rebuild notes:** Workspace detector + prompt overlay. Better: per-repo instructions file precedence display.

### Agent → Verify guidance / Max verify nudges / Verify on stop  `id: config-a.agent.verify_on_stop`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `VERIFY GUIDANCE` (key `agent.verify_guidance`, switch, default `true`), `MAX VERIFY NUDGES` (key `agent.max_verify_nudges`, number, default `3`), `VERIFY ON STOP` (key `agent.verify_on_stop`, switch, default `false`).
- **What it does:** Verification closure: with `verify_on_stop` on, a turn that edited code in a workspace without fresh verification evidence (test/build/lint run) is not accepted as final — a synthetic follow-up asks the agent to verify or explain. Accepts `true`, `false`, or `"auto"` (on for CLI/TUI/desktop and programmatic callers, off for messaging). `verify_guidance` adds creative-UI/clean-diff guidance to the nudge; `max_verify_nudges` caps consecutive `pre_verify` "continue" nudges per turn (built-in + hooks).
- **How it works:** `config_defaults.py:261-280`; `agent/verification_stop.py:99`; `agent/verify_hooks.py:47`; `hermes_cli/plugins.py:190`; migrations v31/v32 forced it off on existing installs (`hermes_cli/config_migrations.py:546-581`). Doc/markdown/skill-only edits never fire it.
- **Inputs / options:** boolean; integer; `true`|`false`|`"auto"`.
- **Outputs / side effects:** extra turn(s) after code edits.
- **Config / env:** the three keys; env `HERMES_VERIFY_ON_STOP` (1/0) overrides config.
- **Edge cases / guards:** bounded loop via `max_verify_nudges`.
- **Rebuild notes:** Passive verification ledger + stop-gate. Better: auto-detect the project's test command and run it.

### Agent → Gateway timeout warning  `id: config-a.agent.gateway_timeout_warning`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `GATEWAY TIMEOUT WARNING`, key `agent.gateway_timeout_warning` (number, default `900`).
- **What it does:** Staged inactivity warning sent once per run at this threshold before `gateway_timeout` escalates; `0` disables.
- **How it works:** `config_defaults.py:281-285`; bridged to `HERMES_AGENT_TIMEOUT_WARNING` (`gateway/run.py:2804-2805`), consumed at `gateway/run.py:31034-31036`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** one warning message to the chat.
- **Config / env:** `agent.gateway_timeout_warning`; env `HERMES_AGENT_TIMEOUT_WARNING`.
- **Edge cases / guards:** does not interrupt the agent.
- **Rebuild notes:** Pre-timeout notice.

### Agent → Clarify timeout  `id: config-a.agent.clarify_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `CLARIFY TIMEOUT`, key `agent.clarify_timeout` (number, default `3600`).
- **What it does:** Max seconds the gateway blocks an agent waiting for a `clarify` tool answer; on expiry the agent unblocks with `[user did not respond within Xm]`. `0`/negative = unlimited. CLI clarify blocks indefinitely and ignores it.
- **How it works:** `config_defaults.py:286-297`; `tools/clarify_gateway.py:538-565` (legacy top-level `clarify.timeout` honoured if explicitly set); `agent/tool_executor.py:834`; `hermes_cli/cli_agent_setup_mixin.py:30`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** releases the running-agent guard.
- **Config / env:** `agent.clarify_timeout` (legacy `clarify.timeout`).
- **Edge cases / guards:** old 600 s default evicted entries mid-think (#32762).
- **Rebuild notes:** Timed wait on a pending-question registry.

### Agent → Gateway notify interval  `id: config-a.agent.gateway_notify_interval`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `GATEWAY NOTIFY INTERVAL`, key `agent.gateway_notify_interval` (number, default `180`).
- **What it does:** Cadence (seconds) of the "⏳ Working — N min" heartbeat on messaging platforms; `0` disables.
- **How it works:** `config_defaults.py:298-306`; bridged to `HERMES_AGENT_NOTIFY_INTERVAL` (`gateway/run.py:2806`), consumed at `gateway/run.py:30876-30888` together with the per-platform `long_running_notifications` display setting (edit-in-place where supported).
- **Inputs / options:** seconds.
- **Outputs / side effects:** periodic status messages.
- **Config / env:** `agent.gateway_notify_interval`; env `HERMES_AGENT_NOTIFY_INTERVAL`.
- **Edge cases / guards:** silenced per platform by `display.platforms.<p>.long_running_notifications: false`.
- **Rebuild notes:** Timer-driven heartbeat editing one bubble.

### Agent → Session stall timeout  `id: config-a.agent.session_stall_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `SESSION STALL TIMEOUT`, key `agent.session_stall_timeout` (number, default `300`).
- **What it does:** Notify-only watchdog: when a busy session has a pending inbound follow-up and the agent activity clock is idle this long, log a WARNING and send `⚠️ Agent session appears stalled (last activity N min ago). Try /new to reset.` once per stall episode. `0` disables.
- **How it works:** `config_defaults.py:307-317`; bridged to `HERMES_SESSION_STALL_TIMEOUT` (`gateway/run.py:2808-2811`); `gateway/run.py:14314,15319`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** one chat notice; never kills the turn.
- **Config / env:** `agent.session_stall_timeout`; env `HERMES_SESSION_STALL_TIMEOUT`.
- **Edge cases / guards:** scope is per in-process `AIAgent`, not a global detector.
- **Rebuild notes:** Idle-clock notifier gated on queued input.

### Agent → Reconnect attention after  `id: config-a.agent.reconnect_attention_after`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `RECONNECT ATTENTION AFTER`, key `agent.reconnect_attention_after` (number, default `7200`).
- **What it does:** A platform continuously failing/reconnecting this long gets `needs_attention: true` + `retrying_since` in gateway runtime status (`hermes status`) and a WARNING log; retries never stop. `0` disables.
- **How it works:** `config_defaults.py:318-323`; bridged to internal env `HERMES_RECONNECT_ATTENTION_AFTER_SECONDS` (`gateway/run.py:2812-2818`); `gateway/run.py:4649`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** status flag; clears on reconnect.
- **Config / env:** `agent.reconnect_attention_after`.
- **Edge cases / guards:** terminal auth errors (revoked tokens, missing intents) are marked fatal instead.
- **Rebuild notes:** Retry-duration threshold flag.

### Agent → Gateway auto-continue freshness  `id: config-a.agent.gateway_auto_continue_freshness`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → label `GATEWAY AUTO CONTINUE FRESHNESS`, key `agent.gateway_auto_continue_freshness` (number, default `3600`).
- **What it does:** Max age (seconds) of the last persisted transcript row for which, after a crash/restart mid-run, the next user message still gets the `[System note: your previous turn was interrupted — process the unfinished tool result(s) first]` prefix. `0` = always inject.
- **How it works:** `config_defaults.py:324-338`; `gateway/session.py:35-46`; `gateway/run.py:1294,1360`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** prepended system note.
- **Config / env:** `agent.gateway_auto_continue_freshness`.
- **Edge cases / guards:** prevents stale markers reviving unrelated old tasks.
- **Rebuild notes:** Age gate on a resume marker.

### Agent → Gateway startup restore drain timeout / warmup timeout  `id: config-a.agent.gateway_startup_restore_drain_timeout`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → labels `GATEWAY STARTUP RESTORE DRAIN TIMEOUT` (key `agent.gateway_startup_restore_drain_timeout`, number, default `30`) and `GATEWAY STARTUP WARMUP TIMEOUT` (key `agent.gateway_startup_warmup_timeout`, number, default `20`).
- **What it does:** Bound how long the boot-time inbound gate stays shut: (a) waiting for auto-resumed turns to finish (inbound messages are queued meanwhile; on timeout the gate opens and the resume turn continues in background); (b) warming turn prerequisites (`run_agent` imports, tool schemas + availability probes, context-file tier) so the first message is not served with a skeleton prompt. `0` disables each bound/warm-up.
- **How it works:** `config_defaults.py:339-364`; `gateway/run.py:1302,1315,1391,1416`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** boot latency vs. correctness of the first reply.
- **Config / env:** the two keys.
- **Edge cases / guards:** duplicate-agent protection unaffected (resume slot claimed synchronously).
- **Rebuild notes:** Startup gate with two bounded phases.

### Agent → Local stream stale timeout  `id: config-a.agent.local_stream_stale_timeout`
- **Surface:** Config | Provider
- **Where:** Config page tab `Agent` → label `LOCAL STREAM STALE TIMEOUT`, key `agent.local_stream_stale_timeout` (number, default `900`).
- **What it does:** Finite stale-stream ceiling for local providers (Ollama, oMLX, llama-cpp) replacing the former infinite disable; applies when the base stale timeout is at its 180 s default and a local endpoint is detected.
- **How it works:** `config_defaults.py:365-370`; `agent/chat_completion_helpers.py:5223`; env `HERMES_LOCAL_STREAM_STALE_TIMEOUT` escape hatch. See docs "API Timeouts" table (socket read `HERMES_STREAM_READ_TIMEOUT` 120 s→1800 s local; stale stream `HERMES_STREAM_STALE_TIMEOUT` 180 s).
- **Inputs / options:** seconds.
- **Outputs / side effects:** a wedged local server eventually trips the detector.
- **Config / env:** `agent.local_stream_stale_timeout`; env `HERMES_LOCAL_STREAM_STALE_TIMEOUT`.
- **Edge cases / guards:** explicit `HERMES_STREAM_STALE_TIMEOUT` overrides.
- **Rebuild notes:** Endpoint-class-specific timeout ceiling.

### Agent → Image input mode  `id: config-a.agent.image_input_mode`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → label `IMAGE INPUT MODE`, key `agent.image_input_mode` (string, default `auto`).
- **What it does:** How user-attached images reach the main model: `auto` = if `auxiliary.vision` is explicitly configured route through it, else attach natively when the model reports `supports_vision`, else text via `vision_analyze`; `native` = always attach pixels (last-chance text fallback for non-vision models); `text` = always pre-analyse and prepend a description.
- **How it works:** `config_defaults.py:371-386`; `agent/image_routing.py:16-40,455` (`decide_image_input_mode`, once per message turn). Affects gateway platforms, TUI and CLI `/attach`; `vision_analyze` stays available as a tool regardless.
- **Inputs / options:** `auto` | `native` | `text`.
- **Outputs / side effects:** multimodal vs text-only API payloads.
- **Config / env:** `agent.image_input_mode`.
- **Edge cases / guards:** maintainer decision 2026-08-28 prefers a named aux vision model over native.
- **Rebuild notes:** Capability-driven router. Better: per-image size/quality policy.

### Agent → Disabled toolsets  `id: config-a.agent.disabled_toolsets`
- **Surface:** Config | Toolset
- **Where:** Config page tab `Agent` → label `DISABLED TOOLSETS`, key `agent.disabled_toolsets` (list, default `[]`).
- **What it does:** Global hard-suppression list applied after per-platform `platform_toolsets`, so a toolset listed here is removed everywhere (e.g. `memory` also drops `MEMORY_GUIDANCE`, `web` removes `web_search`/`web_extract`).
- **How it works:** `config_defaults.py:387`; `hermes_cli/tools_config.py:2618,2910,3021-3032`; `hermes_cli/setup.py:3477-3483`; `tools/mcp_tool.py:8193`; `model_tools.py:482` warns when a platform-bundle name is listed.
- **Inputs / options:** toolset names.
- **Outputs / side effects:** tools absent from every session.
- **Config / env:** `agent.disabled_toolsets`.
- **Edge cases / guards:** empty list = no-op.
- **Rebuild notes:** Subtractive allowlist layer.

### Agent → Reasoning echo  `id: config-a.agent.reasoning_echo`
- **Surface:** Config | Provider
- **Where:** Config page tab `Agent` → label `REASONING ECHO`, key `agent.reasoning_echo` (switch, default `false`).
- **What it does:** Opt-in to preserve assistant `reasoning_content` when replaying history for custom providers/gateways that proxy thinking-mode models (DeepSeek, Kimi/Moonshot, Xiaomi MiMo are auto-detected by host). Strict providers (Mistral, Groq, Cerebras) reject the field with HTTP 400, hence default off.
- **How it works:** `config_defaults.py:388-406` (comment says set `reasoning_echo: true` on the `model:` entry or a `fallback_providers:` entry); readers `run_agent.py:7889-7925` (`_reasoning_echo_opt_in` reads `model.reasoning_echo`) and `agent/chat_completion_helpers.py:2739` (per-fallback flag). The schema key lives under `agent.*` because the default dict seeds it there; the runtime primary read is `model.reasoning_echo`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** `reasoning_content` retained in replayed assistant messages.
- **Config / env:** `agent.reasoning_echo` (schema) / `model.reasoning_echo` (runtime) / `fallback_providers[].reasoning_echo`.
- **Edge cases / guards:** unresolved: the schema key and the primary runtime read location differ (see Handoffs/unresolved).
- **Rebuild notes:** Provider-capability flag. Better: probe the endpoint once and cache.

### Checkpoints → Enabled / Max snapshots / Max total size / Max file size  `id: config-a.checkpoints.enabled`
- **Surface:** Config | CLI
- **Where:** Config page tab `Agent` → section `checkpoints` → labels `ENABLED` (key `checkpoints.enabled`, switch, default `false`), `MAX SNAPSHOTS` (`checkpoints.max_snapshots`, number, default `20`), `MAX TOTAL SIZE MB` (`checkpoints.max_total_size_mb`, number, default `500`), `MAX FILE SIZE MB` (`checkpoints.max_file_size_mb`, number, default `10`).
- **What it does:** Opt-in filesystem checkpoints: once per conversation turn (on the first `write_file`/`patch`) the working directory is snapshotted into a single shared shadow git store under `~/.hermes/checkpoints/`; `/rollback` restores. `max_snapshots` per working directory (ref rewrite + GC), `max_total_size_mb` global ceiling (oldest per project dropped round-robin; `0` = no cap), `max_file_size_mb` skips large files when staging (`0` = no filter).
- **How it works:** `config_defaults.py:681-704`; keys enumerated for the agent-cache signature at `gateway/run.py:28121-28124`; `hermes_cli/setup.py:3534` writes `enabled=false` during setup; `hermes chat --checkpoints` enables per run.
- **Inputs / options:** boolean; integers (MB).
- **Outputs / side effects:** git objects under `~/.hermes/checkpoints/`.
- **Config / env:** the four keys; flag `--checkpoints`; env `HERMES_CHECKPOINT_TIMEOUT` (documented).
- **Edge cases / guards:** v2 defaults changed enabled True→False, max_snapshots 50→20.
- **Rebuild notes:** Shadow git repo per project with pruning. Better: content-addressed dedupe across projects.

### Checkpoints → Auto prune / Retention days / Min interval hours  `id: config-a.checkpoints.auto_prune`
- **Surface:** Config | CLI
- **Where:** Config page tab `Agent` → section `checkpoints` → labels `AUTO PRUNE` (key `checkpoints.auto_prune`, switch, default `true`), `RETENTION DAYS` (`checkpoints.retention_days`, number, default `7`), `MIN INTERVAL HOURS` (`checkpoints.min_interval_hours`, number, default `24`).
- **What it does:** Startup maintenance sweep (at most once per `min_interval_hours`): deletes project entries untouched for `retention_days`, GCs the shared store, enforces `max_total_size_mb`, deletes `legacy-*` archives older than `retention_days`. Never deletes orphan entries (workdir missing) — that needs `hermes checkpoints prune` (`--keep-orphans` to skip).
- **How it works:** `config_defaults.py:705-727`; `gateway/run.py:7770-7785` and `cli.py:2660-2696,5643` (idempotent via `.last_prune` marker); also `hermes_cli/web_server.py:12562`.
- **Inputs / options:** boolean; integers.
- **Outputs / side effects:** deletions under `~/.hermes/checkpoints/`.
- **Config / env:** the three keys.
- **Edge cases / guards:** unattended sweep never guesses about unmounted volumes.
- **Rebuild notes:** Time-gated GC pass.

### MCP → Auto reload on config change  `id: config-a.mcp.auto_reload_on_config_change`
- **Surface:** Config | CLI
- **Where:** Config page tab `Agent` → section `mcp` → label `AUTO RELOAD ON CONFIG CHANGE`, key `mcp.auto_reload_on_config_change` (switch, default `true`).
- **What it does:** When the CLI file watcher sees `mcp_servers:` change, automatically rebuild MCP connections (true) or only print guidance to run `/reload-mcp` (false). Every automatic reload rebuilds the tool surface and invalidates the provider prompt cache.
- **How it works:** `config_defaults.py:763-777`; `cli.py:14403-14467`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** tool list rebuild; next message re-sends the full prefix.
- **Config / env:** `mcp.auto_reload_on_config_change`.
- **Edge cases / guards:** `approvals.mcp_reload_confirm` gates the manual reload prompt.
- **Rebuild notes:** File watcher → reload policy.

### Prompt caching → Cache TTL  `id: config-a.prompt_caching.cache_ttl`
- **Surface:** Config | Provider
- **Where:** Config page tab `Agent` → section `prompt caching` → label `CACHE TTL`, key `prompt_caching.cache_ttl` (string, default `5m`).
- **What it does:** Anthropic-style `cache_control` breakpoint TTL for Claude via native Anthropic, OpenRouter and Nous Portal: `"5m"` or `"1h"`; other non-falsy values are ignored (5m used); falsy values (`false`, `null`, `off`, `disabled`, `no`, `none`) disable prompt caching entirely.
- **How it works:** `config_defaults.py:1054-1060`; `agent/agent_init.py:987`; `agent/agent_runtime_helpers.py:2164-2274,2398`; `agent/moa_loop.py:429`. Qwen Cloud clamps to 5 m upstream.
- **Inputs / options:** `5m` | `1h` | falsy.
- **Outputs / side effects:** cached-read pricing on repeated prefixes.
- **Config / env:** `prompt_caching.cache_ttl`.
- **Edge cases / guards:** Bedrock/Azure fall back to provider defaults.
- **Rebuild notes:** TTL selector for cache breakpoints.

### Context → Engine  `id: config-a.context.engine`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Agent` → section `context` → label `ENGINE`, description `Context management engine`, select `default` | `custom` (`web_server.py:1385-1389`); `config.yaml` `context.engine` (default `compressor`).
- **What it does:** Selects the context-window management engine: built-in `compressor` (lossy summarisation) or an installed plugin name (e.g. `lcm` — Lossless Context Management) from `plugins/context_engine/<name>/` or `~/.hermes/plugins/`.
- **How it works:** `config_defaults.py:2040-2044`; `agent/agent_init.py:2683`; `agent/context_engine.py:9`; `plugins/context_engine/__init__.py:9`; `hermes plugins` → Provider Plugins → Context Engine reads/writes it (`hermes_cli/plugins_cmd.py:2076-2096`).
- **Inputs / options:** the dashboard select offers `default`/`custom` (mismatch with the real values `compressor`/`<plugin>` — see unresolved).
- **Outputs / side effects:** engine swap at agent init.
- **Config / env:** `context.engine`.
- **Edge cases / guards:** plugin engines are never auto-activated.
- **Rebuild notes:** Strategy selection by name. Better: schema options populated from installed engines.

### Context → Memory trim  `id: config-a.context.memory_trim`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `ENABLED` (key `context.memory_trim.enabled`, switch, default `true`), `COOLDOWN SECONDS` (`context.memory_trim.cooldown_seconds`, number, default `60.0`), `LOG EVERY N` (`context.memory_trim.log_every_n`, number, default `1`), `INFO LOG MIN DELTA MB` (`context.memory_trim.info_log_min_delta_mb`, number, default `0.0`).
- **What it does:** Returns freed glibc allocator pages (`malloc_trim`) after long-running agent/TUI cleanup boundaries, with a cooldown between calls; INFO logs every Nth periodic trim and only when the RSS delta exceeds the MB threshold (force paths always log).
- **How it works:** `config_defaults.py:2045-2056`; `hermes_cli/mem_trim.py:54-57`. No-op on unsupported platforms.
- **Inputs / options:** boolean; floats/ints.
- **Outputs / side effects:** lower RSS; log lines.
- **Config / env:** the four keys.
- **Edge cases / guards:** Linux/glibc only.
- **Rebuild notes:** Rate-limited `malloc_trim(0)`.

### Goals → Max turns  `id: config-a.goals.max_turns`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → section `goals` → label `MAX TURNS`, key `goals.max_turns` (number, default `20`).
- **What it does:** Max continuation turns a standing `/goal` may drive (judge call after each turn decides "satisfied?"; failures fail open) before Hermes auto-pauses and asks for `/goal resume`.
- **How it works:** `config_defaults.py:2183-2195`; read via the relay/goal runtime (`agent/relay_runtime.py:208-215,1455-1462`).
- **Inputs / options:** integer.
- **Outputs / side effects:** auto-pause message.
- **Config / env:** `goals.max_turns`.
- **Edge cases / guards:** protects against judge false negatives and unbounded spend.
- **Rebuild notes:** Ralph-style loop with a turn ceiling.

### Skills → External dirs / Project discovery / Trusted project dirs  `id: config-a.skills.external_dirs`
- **Surface:** Config | Skill
- **Where:** Config page tab `Agent` → section `skills` → labels `EXTERNAL DIRS` (key `skills.external_dirs`, list, default `[]`), `PROJECT DISCOVERY` (`skills.project_discovery`, switch, default `true`), `TRUSTED PROJECT DIRS` (`skills.trusted_project_dirs`, list, default `[]`).
- **What it does:** `external_dirs` adds read-only skill directories (expanded `~`/`${VAR}`, local skills win on name collision). `project_discovery` enables sourcing `<root>/.hermes/skills/` and `<root>/.agents/skills/` inside a git checkout as the highest-precedence tier — but only when the root is in `trusted_project_dirs` (managed by `hermes skills trust`/`untrust`).
- **How it works:** `config_defaults.py:2249-2262`; `agent/skill_utils.py:534,647,711-766,913-980`; `agent/prompt_builder.py:1778`; `hermes_cli/main.py:13039`; `tui_gateway/methods_tools.py:1240`.
- **Inputs / options:** lists of paths; boolean.
- **Outputs / side effects:** additional skills in the prompt index; an "untrusted skills" notice when discovery finds a non-trusted repo.
- **Config / env:** the three keys.
- **Edge cases / guards:** external dirs are never written to.
- **Rebuild notes:** Tiered skill search path with trust list.

### Skills → Template vars / Inline shell / Inline shell timeout  `id: config-a.skills.template_vars`
- **Surface:** Config | Skill
- **Where:** Config page tab `Agent` → labels `TEMPLATE VARS` (key `skills.template_vars`, switch, default `true`), `INLINE SHELL` (`skills.inline_shell`, switch, default `false`), `INLINE SHELL TIMEOUT` (`skills.inline_shell_timeout`, number, default `10`).
- **What it does:** Substitute `${HERMES_SKILL_DIR}` and `${HERMES_SESSION_ID}` in `SKILL.md`; optionally pre-execute `` !`cmd` `` snippets and inline their stdout (off by default — runs skill-author code on the host without approval); per-snippet timeout.
- **How it works:** `config_defaults.py:2263-2277`; `agent/skill_preprocessing.py:139-142`; `agent/skill_commands.py:328-331`.
- **Inputs / options:** booleans; seconds.
- **Outputs / side effects:** dynamic content in skill messages.
- **Config / env:** the three keys.
- **Edge cases / guards:** enable inline shell only for trusted skill sources.
- **Rebuild notes:** Template expansion + optional command inlining.

### Skills → Guard agent-created / Tier-1 advisory / Write approval / Ledger  `id: config-a.skills.write_approval`
- **Surface:** Config | Skill | Security
- **Where:** Config page tab `Agent` → labels `GUARD AGENT CREATED` (key `skills.guard_agent_created`, switch, default `false`), `TIER1 ADVISORY` (`skills.tier1_advisory`, switch, default `true`), `WRITE APPROVAL` (`skills.write_approval`, switch, default `false`), `LEDGER` (`skills.ledger`, switch, default `true`).
- **What it does:** `guard_agent_created` runs the keyword/pattern security scanner on skills the agent writes via `skill_manage` (hub installs are always scanned). `tier1_advisory` runs NVIDIA SkillEvaluator Tier-1 on `hermes skills install` when the `skillevaluator` binary is on PATH (informational; secrets findings in red). `write_approval` stages every agent skill write under `~/.hermes/pending/skills/` for `/skills pending|diff <id>|approve <id>|reject <id>` (`/skills approval on|off` toggles). `ledger` appends every skill mutation to `~/.hermes/skills/.curator_ledger.jsonl` with content-addressed blobs under `~/.hermes/.curator_backups/blobs/` (enables `hermes curator ledger`/`rollback`).
- **How it works:** `config_defaults.py:2278-2329`; `tools/skill_manager_tool.py:118-148`, `tools/skills_guard.py:76`; `tools/skillevaluator_scan.py:33,123`, `hermes_cli/skills_hub.py:109`; `gateway/slash_commands.py:4037-4068`, `hermes_cli/commands.py:328`; `tools/skill_ledger.py:113-118`, `hermes_cli/curator.py:578`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** approval prompts / staged files / JSONL ledger.
- **Config / env:** the four keys.
- **Edge cases / guards:** ledger failures never block a mutation.
- **Rebuild notes:** Write gate + audit trail for agent-authored procedures.

### Plugins → Hook callback timeout  `id: config-a.plugins.hook_callback_timeout`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → section `plugins` → label `HOOK CALLBACK TIMEOUT`, description `Wall-clock cap (seconds) for timeout-bounded in-process Python plugin hook callbacks (hot-path observers + pre_tool_call). Timed-out pre_tool_call fails closed. 0 disables the cap; values above 600 are clamped. Caller-thread hooks such as subagent_stop are never moved onto a timeout worker.` (`web_server.py:1432-1435`); number, default `30`.
- **What it does:** Bounds in-process Python plugin hook callbacks; shell hooks keep their own per-entry `timeout`.
- **How it works:** `config_defaults.py:2631-2641`; `hermes_cli/plugins.py:3667-3708,5575` (non-number/negative → default, >600 clamped).
- **Inputs / options:** seconds (0–600).
- **Outputs / side effects:** timed-out `pre_tool_call` blocks the tool call.
- **Config / env:** `plugins.hook_callback_timeout`.
- **Edge cases / guards:** `plugins.enabled`/`disabled` allow-lists are intentionally not in `DEFAULT_CONFIG`.
- **Rebuild notes:** Worker-thread timeout for hooks.

### Cron → Allow agent scheduling / Preflight / Model drift guard  `id: config-a.cron.allow_agent_scheduling`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → section `cron` → labels `ALLOW AGENT SCHEDULING` (key `cron.allow_agent_scheduling`, switch, default `false`), `PREFLIGHT` (`cron.preflight`, switch, default `true`), `MODEL DRIFT GUARD` (`cron.model_drift_guard`, switch, default `true`).
- **What it does:** `allow_agent_scheduling` lets cron-spawned agents use the `cronjob` toolset (the "cron-librarian" pattern; interactive toolsets stay denied). `preflight` validates provider key, attached skills and delivery platforms before building agent machinery; a failing job is recorded `last_status=blocked_config` with one alert and no LLM call. `model_drift_guard` fails closed when an unpinned job's current global model/provider differs from its creation-time snapshot.
- **How it works:** `config_defaults.py:2707-2732`; `cron/scheduler.py:543` (scheduling), `5086,6076-6127` (preflight; only literal `false` disables); `hermes_cli/config.py:5217` (drift guard).
- **Inputs / options:** booleans.
- **Outputs / side effects:** job status fields in `~/.hermes/cron/jobs.json`.
- **Config / env:** the three keys.
- **Edge cases / guards:** `cron.model` set → drift guard does not engage on the model axis.
- **Rebuild notes:** Policy gates evaluated at dispatch.

### Cron → Model / Model provider / Provider  `id: config-a.cron.model`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `MODEL` (key `cron.model`, string, default `""`), `MODEL PROVIDER` (`cron.model_provider`, string, default `""`), `PROVIDER` (`cron.provider`, string, default `""`).
- **What it does:** Axis A — inference model for cron jobs (`per-job pin > cron.model > model.default`) and its paired inference provider. Axis B — `cron.provider` names the SCHEDULER provider deciding *when* a job fires: empty = built-in in-process 60 s ticker; `chronos` = NAS-mediated managed cron for scale-to-zero deployments; unknown/unavailable → built-in.
- **How it works:** `config_defaults.py:2733-2758`; `cron/scheduler.py:147,5928-5939,6151,6253`; `hermes_cli/config.py:5224`; `cron/scheduler_provider.py:18,479-532`; `plugins/cron_providers/chronos/__init__.py:21`.
- **Inputs / options:** model id; provider name; scheduler plugin name.
- **Outputs / side effects:** cron spend no longer shadows chat `/model` switches.
- **Config / env:** the three keys.
- **Edge cases / guards:** providers that lack `multiplex_profiles` fall back to built-in.
- **Rebuild notes:** Two independent axes (what model / what trigger).

### Cron → Chronos (portal URL / callback URL / expected audience / NAS JWKS URL)  `id: config-a.cron.chronos`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `PORTAL URL` (key `cron.chronos.portal_url`, string, default `https://portal.nousresearch.com`), `CALLBACK URL` (`cron.chronos.callback_url`, string, default `""`), `EXPECTED AUDIENCE` (`cron.chronos.expected_audience`, string, default `""`), `NAS JWKS URL` (`cron.chronos.nas_jwks_url`, string, default `""`).
- **What it does:** Non-secret settings for the Chronos managed-cron provider: NAS/portal base URL used to arm/cancel one-shots (and expected JWT issuer), this agent's public base URL that NAS POSTs to (`{callback_url}/api/cron/fire`; empty → Chronos unavailable → built-in ticker), the expected JWT audience (`agent:{instance_id}`), and the JWKS URL for verifying inbound fire JWTs (empty → the fire endpoint refuses all tokens).
- **How it works:** `config_defaults.py:2759-2778`; `plugins/cron_providers/chronos/__init__.py:72-99`; verifiers `gateway/platforms/api_server.py:6869-6871`, `hermes_cli/web_routers/cron.py:169-171`.
- **Inputs / options:** URLs/strings.
- **Outputs / side effects:** outbound provision calls reuse the Nous Portal token; inbound `/api/cron/fire`.
- **Config / env:** the four keys.
- **Edge cases / guards:** only consulted when `cron.provider == "chronos"`.
- **Rebuild notes:** Externally-triggered scheduler with signed callbacks.

### Cron → Wrap response / Mirror delivery  `id: config-a.cron.wrap_response`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → labels `WRAP RESPONSE` (key `cron.wrap_response`, switch, default `true`) and `MIRROR DELIVERY` (`cron.mirror_delivery`, switch, default `false`).
- **What it does:** `wrap_response` wraps delivered cron output with a header (task name) and footer ("The agent cannot see this message"). `mirror_delivery` makes deliveries continuable: on thread-capable platforms a dedicated thread is opened via `create_handoff_thread` and its session seeded; on DM-only platforms the brief is mirrored into the origin DM session. Per-job `attach_to_session` overrides.
- **How it works:** `config_defaults.py:2779-2803`; `cron/scheduler.py:3100-3106` and `1682-1770,3165`; `cron/jobs.py:2439`; `tools/cronjob_tools.py:349`; rides `gateway.mirror.mirror_to_session`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** extra thread/session rows.
- **Config / env:** the two keys.
- **Edge cases / guards:** only the origin chat is mirrored, never fan-out targets.
- **Rebuild notes:** Delivery framing + continuation seeding.

### Cron → Max parallel jobs / Output retention  `id: config-a.cron.max_parallel_jobs`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `MAX PARALLEL JOBS` (key `cron.max_parallel_jobs`, string, default `null`) and `OUTPUT RETENTION` (`cron.output_retention`, number, default `50`).
- **What it does:** Max due jobs run in parallel per tick (`null`/`0` unbounded, `1` serial) and how many recent `.md` output files `save_job_output` keeps per job (`≤0` disables pruning).
- **How it works:** `config_defaults.py:2804-2813`; `cron/scheduler.py:8040`; `cron/jobs.py:4211`.
- **Inputs / options:** integers.
- **Outputs / side effects:** files under `~/.hermes/cron/`.
- **Config / env:** `cron.max_parallel_jobs` (env `HERMES_CRON_MAX_PARALLEL`), `cron.output_retention`.
- **Edge cases / guards:** thread count still bounds parallelism.
- **Rebuild notes:** Semaphore + file rotation.

### Cron → Script timeout / Session DB timeout / Media send timeout  `id: config-a.cron.script_timeout_seconds`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → labels `SCRIPT TIMEOUT SECONDS` (key `cron.script_timeout_seconds`, number, default `3600`), `SESSION DB TIMEOUT SECONDS` (`cron.session_db_timeout_seconds`, number, default `10`), `MEDIA SEND TIMEOUT SECONDS` (`cron.media_send_timeout_seconds`, number, default `300`).
- **What it does:** Timeout for no-agent cron scripts; bound on `SessionDB()` init inside cron jobs (a wedged `sqlite3.connect` would otherwise hang the dispatch guard; `0` = unlimited); per-attachment timeout when delivering media through a live gateway adapter.
- **How it works:** `config_defaults.py:2814-2832`; `cron/scheduler.py:3951` (also `gateway/platforms/webhook.py:236` reuses the name), `4005-4028`, `2961,3970`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** job failures on expiry.
- **Config / env:** the keys; env `HERMES_CRON_SCRIPT_TIMEOUT`, `HERMES_CRON_SESSION_DB_TIMEOUT`, `HERMES_CRON_MEDIA_SEND_TIMEOUT`.
- **Edge cases / guards:** keep in sync with `cron.scheduler._DEFAULT_*` constants.
- **Rebuild notes:** Three independent deadlines.

### Bot mode → Envelope TTL / Turn wait  `id: config-a.bot_mode.envelope_ttl_seconds`
- **Surface:** Config | Desktop app
- **Where:** Config page tab `Agent` → section `bot mode` → labels `ENVELOPE TTL SECONDS` (key `bot_mode.envelope_ttl_seconds`, number, default `900`) and `TURN WAIT SECONDS` (`bot_mode.turn_wait_seconds`, number, default `120`).
- **What it does:** Bot-relay tuning: an envelope older than the TTL is not delivered when the Desktop drains the outbox (sender gets `queued_expired`; `0` disables drain-time expiry, the 6 h stale sweep still applies); a second delivery into a busy target profile queues behind the current turn up to `turn_wait_seconds` before failing with `target_busy` (per-profile cross-process file lock).
- **How it works:** `config_defaults.py:2921-2936`; `tools/bot_relay.py:71,249-260,356,587-638`; `tui_gateway/methods_bot_relay.py:119`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** structured error replies.
- **Config / env:** the two keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Outbox with TTL + per-target lock.

### Code execution → Mode / Kernel idle timeout / Max session kernels  `id: config-a.code_execution.mode`
- **Surface:** Config | Tool
- **Where:** Config page tab `Agent` → section `code execution` → labels `MODE` (key `code_execution.mode`, string, default `project`), `KERNEL IDLE TIMEOUT` (`code_execution.kernel_idle_timeout`, number, default `1800`), `MAX SESSION KERNELS` (`code_execution.max_session_kernels`, number, default `4`).
- **What it does:** `mode`: `project` runs `execute_code` scripts in the session cwd with the active venv/conda python (project deps and relative paths resolve); `strict` runs in an isolated temp dir with `sys.executable`. Env scrubbing (`*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_CREDENTIAL`, `*_PASSWD`, `*_AUTH`) and the tool whitelist apply in both. Local execution always uses persistent session kernels (variables/imports survive across calls; `reset=true` discards); kernels are reaped after `kernel_idle_timeout` s idle and capped process-wide at `max_session_kernels` (LRU). Remote backends run per-call.
- **How it works:** `config_defaults.py:2937-2991`; `tools/code_execution_tool.py:2056-2099,2340`; `tools/code_kernel.py:280-281`. A leftover `kernel_mode` key is ignored.
- **Inputs / options:** `project` | `strict`; seconds; integer.
- **Outputs / side effects:** child python processes.
- **Config / env:** the three keys (plus `code_execution.timeout`, `max_tool_calls` in the Tools shard).
- **Edge cases / guards:** timed-out/interrupted cell kills the kernel; per-cell RPC authority rebinding.
- **Rebuild notes:** Persistent kernel pool with LRU and idle reaper.

### Models.dev → URL  `id: config-a.models_dev.url`
- **Surface:** Config | Provider
- **Where:** Config page tab `Agent` → section `models dev` → label `URL`, key `models_dev.url` (string, default `""` = `https://models.dev/api.json`).
- **What it does:** Mirror override for the models.dev catalog used for context-length/capability metadata.
- **How it works:** `config_defaults.py:3118-3120`; `agent/models_dev.py:34,285-292`.
- **Inputs / options:** URL.
- **Outputs / side effects:** network fetch target.
- **Config / env:** `models_dev.url`.
- **Edge cases / guards:** falls back to the in-repo snapshot on network failure.
- **Rebuild notes:** Catalog URL override.

### Network → Force IPv4  `id: config-a.network.force_ipv4`
- **Surface:** Config | Core
- **Where:** Config page tab `Agent` → section `network` → label `FORCE IPV4`, key `network.force_ipv4` (switch, default `false`).
- **What it does:** Skips IPv6 (AAAA) resolution for outbound connections by monkey-patching `socket` — fixes hangs on hosts with broken IPv6.
- **How it works:** `config_defaults.py:3123-3129`; `hermes_constants.py:1695`; applied early in `hermes_cli/main.py:775-790` (managed overlay wins).
- **Inputs / options:** boolean.
- **Outputs / side effects:** process-wide socket behaviour.
- **Config / env:** `network.force_ipv4`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** `getaddrinfo` family filter.

### Onboarding → Profile build  `id: config-a.onboarding.profile_build`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Agent` → section `onboarding` → label `PROFILE BUILD`, key `onboarding.profile_build` (string, default `ask`).
- **What it does:** On the very first gateway message ever, `ask` offers (consent-gated, opt-in) to build a user profile; `off` shows a plain intro. Fires at most once, latched under `onboarding.seen`.
- **How it works:** `config_defaults.py:3483-3492`; `agent/onboarding.py:154`; `gateway/run.py:21981`.
- **Inputs / options:** `ask` | `off`.
- **Outputs / side effects:** latch written to `onboarding.seen`.
- **Config / env:** `onboarding.profile_build`.
- **Edge cases / guards:** unknown values behave as `ask`; wipe the `onboarding` section to re-see hints.
- **Rebuild notes:** One-shot onboarding offer.

### Computer use → CUA telemetry / Max image dimension / Capture-after mode  `id: config-a.computer_use.cua_telemetry`
- **Surface:** Config | Tool
- **Where:** Config page tab `Agent` → section `computer use` → labels `CUA TELEMETRY` (key `computer_use.cua_telemetry`, switch, default `false`), `MAX IMAGE DIMENSION` (`computer_use.max_image_dimension`, number, default `1456`), `CAPTURE AFTER MODE` (`computer_use.capture_after_mode`, string, default `som`).
- **What it does:** Telemetry opt-in for the upstream cua-driver (off → Hermes sets `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` for every invocation); cap on driver screenshot longest edge via `set_config` at session start (`0` disables); mode for capture_after follow-ups: `som` (screenshot + overlays), `ax` (elements only, no PNG), `vision` (pixels only).
- **How it works:** `config_defaults.py:3774-3791`; `tools/computer_use/cua_backend.py:275-282,346`; `tools/computer_use/tool.py:1251`; `hermes_cli/tools_config.py:796`.
- **Inputs / options:** boolean; pixels; `som`|`ax`|`vision`.
- **Outputs / side effects:** child env var; payload sizes.
- **Config / env:** the three keys.
- **Edge cases / guards:** unreadable config falls safe to telemetry-off.
- **Rebuild notes:** Driver launch options.

### Computer use → No overlay / Permission mode / Capability manifest / Allow unsigned driver  `id: config-a.computer_use.permission_mode`
- **Surface:** Config | Tool | Security
- **Where:** Config page tab `Agent` → labels `NO OVERLAY` (key `computer_use.no_overlay`, string, default `null`), `PERMISSION MODE` (`computer_use.permission_mode`, string, default `standard`), `CAPABILITY MANIFEST` (`computer_use.capability_manifest`, string, default `""`), `ALLOW UNSIGNED DRIVER` (`computer_use.allow_unsigned_driver`, switch, default `false`).
- **What it does:** `no_overlay`: `null` auto-detects (overlay off on macOS, headless/WSL2 Linux and Linux X11; on for Windows and Wayland), `true` always passes `--no-overlay` (+ `set_agent_cursor_enabled(false)`), `false` keeps the cursor. `permission_mode`: `standard` (cua-driver's own approval boundary) or `bounded` (no runtime prompts; anything outside the reviewed `capability_manifest` fails closed; Hermes passes `--capability-manifest` and `--approve-capability-manifest`). `unrestricted` is deliberately not accepted from config (bound to the per-session YOLO toggle). `allow_unsigned_driver` (macOS) permits launching an ad-hoc-signed `CuaDriver.app` for the private-session daemon.
- **How it works:** `config_defaults.py:3792-3832`; `tools/computer_use/cua_backend.py:236-270,289-302,582-625,671-718,922`; `tools/computer_use/tool.py:230,268`.
- **Inputs / options:** `null`/`true`/`false`; `standard`|`bounded`; path; boolean.
- **Outputs / side effects:** driver CLI flags.
- **Config / env:** the four keys.
- **Edge cases / guards:** unknown permission modes fall closed to `standard`; legacy v1/v2 manifests rejected for bounded mode.
- **Rebuild notes:** Config → driver flag mapping with fail-closed defaults.

## Terminal (31 fields)

Every `terminal.*` key is bridged to an environment variable of the form `TERMINAL_<KEY_UPPERCASE>` at CLI/gateway start (`hermes_cli/config.py:3790-3824` `TERMINAL_CONFIG_ENV_MAP`, `cli.py:660-700`, `gateway/run.py:2702-2711`); lists/dicts are JSON-encoded. The env var is what `tools/terminal_tool.py` and `tools/environments/*` actually read, so setting the env var directly overrides config.

### Terminal → Backend  `id: config-a.terminal.backend`
- **Surface:** Config | Web dashboard | Tool
- **Where:** Config page tab `Terminal` → label `BACKEND`, description `Terminal execution backend`, select `local` | `docker` | `ssh` | `modal` | `daytona` | `vercel_sandbox` | `singularity` (`web_server.py:1292-1296`; plugin terminal backends are appended per request, `web_server.py:1750-1760`); default `local`.
- **What it does:** Chooses where every `terminal`, `process`, file-tool and `execute_code` call runs: the host, a hardened Docker container, a remote SSH host, a Modal sandbox, a Daytona workspace, a Vercel Sandbox microVM, or a Singularity/Apptainer container.
- **How it works:** `config_defaults.py:389`; env `TERMINAL_ENV`; registry `agent/terminal_env_provider.py:9-82`, `agent/terminal_env_registry.py:13`; `tools/terminal_tool.py:1708-1723`. Docker = one long-lived labelled container shared across sessions/processes (labels `hermes-agent=1`, `hermes-task-id`, `hermes-profile`), torn down only per `docker_persist_across_processes`/reapers; hardening `--cap-drop ALL` (+DAC_OVERRIDE, CHOWN, FOWNER), `no-new-privileges`, `--pids-limit 256`, tmpfs `/tmp` 512 MB, `/var/tmp` 256 MB, `/run` 64 MB. SSH needs `TERMINAL_SSH_HOST`/`TERMINAL_SSH_USER` (+`_PORT`, `_KEY`, `_PERSISTENT`), uses ControlMaster. Modal needs `MODAL_TOKEN_ID`+`MODAL_TOKEN_SECRET` or `~/.modal.toml`; snapshots tracked in `~/.hermes/modal_snapshots.json`. Daytona needs `DAYTONA_API_KEY`; disk max 10 GiB. Vercel needs `pip install 'hermes-agent[vercel]'` + `VERCEL_TOKEN`/`VERCEL_PROJECT_ID`/`VERCEL_TEAM_ID` (or short-lived `VERCEL_OIDC_TOKEN`). Singularity needs `apptainer`/`singularity`; `docker://` images converted to SIF; scratch dir order `TERMINAL_SCRATCH_DIR` → `TERMINAL_SANDBOX_DIR/singularity` → `/scratch/$USER/hermes-agent` → `~/.hermes/sandboxes/singularity`; `--containall --no-home`. SSH/Modal/Daytona sync `~/.hermes/` state into the sandbox and back on teardown (3 retries, 2 GiB extract cap).
- **Inputs / options:** the seven built-ins plus plugin names.
- **Outputs / side effects:** containers/sandboxes created; `HERMES_DOCKER_BINARY` can force podman.
- **Config / env:** `terminal.backend`; env `TERMINAL_ENV`.
- **Edge cases / guards:** `hermes doctor` checks each backend's prerequisites; `proxy.enforce_on_docker` can refuse Docker starts.
- **Rebuild notes:** Strategy interface (`execute`, `cleanup`, file ops) with per-backend adapters. Better: per-session backend selection and capability matrix in the UI.

### Terminal → Modal mode  `id: config-a.terminal.modal_mode`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Terminal` → label `MODAL MODE`, description `Modal sandbox mode`, select `sandbox` | `function` (`web_server.py:1302-1306`); default `auto`.
- **What it does:** Selects direct vs. Nous-managed Modal usage; setup writes `managed`/`direct` (`hermes_cli/setup.py:1545-1573`), and `normalize_modal_mode` maps the spellings.
- **How it works:** `config_defaults.py:390`; env `TERMINAL_MODAL_MODE` (`setup.py:1757`); `tools/environments/__init__.py:6`.
- **Inputs / options:** dashboard offers `sandbox`/`function`; setup writes `auto`/`managed`/`direct` (mismatch noted as unresolved).
- **Outputs / side effects:** Modal client path.
- **Config / env:** `terminal.modal_mode`; env `TERMINAL_MODAL_MODE`.
- **Edge cases / guards:** only relevant when `backend: modal`.
- **Rebuild notes:** Mode enum for a cloud backend.

### Terminal → Degraded mode  `id: config-a.terminal.degraded_mode`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → label `DEGRADED MODE`, key `terminal.degraded_mode` (string, default `warn`).
- **What it does:** On connection-class infrastructure failures of remote backends (SSH host unreachable, Docker daemon down): `warn` returns a structured degraded tool result with reason + retry hint so the model can adapt; `fail` keeps the historical error + traceback.
- **How it works:** `config_defaults.py:391-396`; `tools/environments/base.py:78`; `tools/terminal_tool.py:3867`; env `TERMINAL_DEGRADED_MODE`.
- **Inputs / options:** `warn` | `fail`.
- **Outputs / side effects:** tool result shape.
- **Config / env:** `terminal.degraded_mode`; env `TERMINAL_DEGRADED_MODE`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Error-shaping switch.

### Terminal → Cwd / Temp dir  `id: config-a.terminal.cwd`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → labels `CWD` (key `terminal.cwd`, string, default `.`) and `TEMP DIR` (`terminal.temp_dir`, string, default `""`).
- **What it does:** `cwd` = working directory for gateway/messaging/cron runs (CLI always uses its launch dir); placeholders `.`, `auto`, `cwd` resolve to the home dir. `temp_dir` = root for session temp artifacts (background logs/pid/exit files, code-execution sandboxes, spilled tool results): empty → honour `TMPDIR`/`TMP`/`TEMP`, else a managed dir at `~/.hermes/cache/terminal` auto-pruned after 72 h (hourly by gateway housekeeping, once per process on CLI); user-set paths are never pruned and must be existing absolute POSIX paths.
- **How it works:** `config_defaults.py:397-407`; `gateway/cwd_placeholder.py:1-3`, `agent/runtime_cwd.py:4`, `tui_gateway/server.py:2405-2412`, `agent/prompt_builder.py:2447`; `tools/environments/local.py:67,2020-2057`.
- **Inputs / options:** paths.
- **Outputs / side effects:** subprocess cwd; temp files.
- **Config / env:** `terminal.cwd` (env `TERMINAL_CWD`; legacy `MESSAGING_CWD`), `terminal.temp_dir` (env `TERMINAL_TEMP_DIR`).
- **Edge cases / guards:** `/tmp` deliberately avoided (small tmpfs on Arch-like distros).
- **Rebuild notes:** Resolve cwd per surface; managed temp root with TTL sweep.

### Terminal → Font family  `id: config-a.terminal.font_family`
- **Surface:** Config | Desktop app
- **Where:** Config page tab `Terminal` → label `FONT FAMILY`, key `terminal.font_family` (string, default `""`); Desktop `Settings → Appearance → Terminal Font`.
- **What it does:** CSS `font-family` for the desktop app's embedded xterm.js terminal (one installed family such as `MesloLGS NF`, or a CSS stack); Hermes appends its bundled `'JetBrains Mono', 'Cascadia Code', 'SF Mono', Menlo, Consolas, monospace` fallback; empty keeps the default.
- **How it works:** `config_defaults.py:408-415`; read only by the desktop: `apps/desktop/src/app/settings/terminal-font-setting.tsx:25,89`, `apps/desktop/src/app/session/hooks/use-hermes-config.ts:141`. No Python reader.
- **Inputs / options:** font name / CSS stack.
- **Outputs / side effects:** desktop rendering only.
- **Config / env:** `terminal.font_family`.
- **Edge cases / guards:** no font download or system-font permission needed.
- **Rebuild notes:** Pass-through style setting.

### Terminal → Timeout  `id: config-a.terminal.timeout`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → label `TIMEOUT`, key `terminal.timeout` (number, default `180`).
- **What it does:** Per-command timeout (seconds) for the `terminal` tool on every backend.
- **How it works:** `config_defaults.py:416`; env `TERMINAL_TIMEOUT` (`hermes_cli/config.py:3795`).
- **Inputs / options:** seconds.
- **Outputs / side effects:** command killed with a timeout result.
- **Config / env:** `terminal.timeout`; env `TERMINAL_TIMEOUT`.
- **Edge cases / guards:** background processes are unaffected.
- **Rebuild notes:** Subprocess deadline.

### Terminal → Daemon term grace / One-shot completion wait  `id: config-a.terminal.daemon_term_grace_seconds`
- **Surface:** Config | Tool | CLI
- **Where:** Config page tab `Terminal` → labels `DAEMON TERM GRACE SECONDS` (key `terminal.daemon_term_grace_seconds`, number, default `2.0`) and `ONESHOT COMPLETION WAIT SECONDS` (`terminal.oneshot_completion_wait_seconds`, number, default `600.0`).
- **What it does:** Grace between SIGTERM and an escalated SIGKILL when terminating a host process tree (browser daemons etc.; `0` = SIGTERM only, floored at 0). One-shot CLI runs (`-q/-Q/-z`) that exit while `notify_on_complete=true` background processes are still running linger up to this bound so Bot Mode handoff replies are not lost (`0` disables; plain daemons are never waited on).
- **How it works:** `config_defaults.py:417-434`; `tools/process_registry.py:883-911` and `:1746-1837`; `cli.py:1441`.
- **Inputs / options:** seconds.
- **Outputs / side effects:** process signals; delayed process exit.
- **Config / env:** the two keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Escalating kill + exit linger.

### Terminal → Env passthrough  `id: config-a.terminal.env_passthrough`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → label `ENV PASSTHROUGH`, key `terminal.env_passthrough` (list, default `[]`).
- **What it does:** Names of environment variables forwarded into sandboxed execution (`terminal` and `execute_code`) beyond skill-declared `required_environment_variables`.
- **How it works:** `config_defaults.py:435-438`; `tools/env_passthrough.py:13,136`; `tools/code_execution_tool.py:1741`.
- **Inputs / options:** list of names.
- **Outputs / side effects:** secrets visible inside sandboxes.
- **Config / env:** `terminal.env_passthrough`.
- **Edge cases / guards:** kernel env is frozen at spawn — pass `reset=true` after changes.
- **Rebuild notes:** Allowlist filter on the child env.

### Terminal → Home mode  `id: config-a.terminal.home_mode`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → label `HOME MODE`, key `terminal.home_mode` (string, default `auto`).
- **What it does:** `HOME` policy for tool subprocesses: `auto` = host keeps the real OS-user HOME, containers use `{HERMES_HOME}/home`; `real` = force the real HOME; `profile` = force `{HERMES_HOME}/home` when it exists (strict per-profile CLI-config isolation — `~/.ssh`, `~/.gitconfig`, gh/az/npm logins invisible unless initialised there). `HERMES_REAL_HOME` is always exported for scripts.
- **How it works:** `config_defaults.py:439-446`; `hermes_constants.py:1258-1296` `get_subprocess_home()` (aliases `isolated`/`profile_home` → `profile`, `host`/`user`/`real_home` → `real`); env `TERMINAL_HOME_MODE`.
- **Inputs / options:** `auto` | `real` | `profile`.
- **Outputs / side effects:** `HOME` in child processes only (never the system HOME).
- **Config / env:** `terminal.home_mode`; env `TERMINAL_HOME_MODE`, `HERMES_REAL_HOME`.
- **Edge cases / guards:** repairs a parent process that started with HOME pointed at a profile home.
- **Rebuild notes:** Three-way HOME resolver.

### Terminal → Shell init files / Auto source bashrc  `id: config-a.terminal.shell_init_files`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → labels `SHELL INIT FILES` (key `terminal.shell_init_files`, list, default `[]`) and `AUTO SOURCE BASHRC` (`terminal.auto_source_bashrc`, switch, default `true`).
- **What it does:** Extra files (`~`/`${VAR}` expanded, missing skipped) sourced in the login shell that builds the per-session environment snapshot (nvm, pyenv, asdf, zsh files). When the list is empty and the snapshot shell is bash, `auto_source_bashrc` sources `~/.profile`, `~/.bash_profile`, `~/.bashrc` in that order (bash skips bashrc in non-interactive login mode).
- **How it works:** `config_defaults.py:447-473`; `tools/environments/local.py:1886-1889`.
- **Inputs / options:** list of paths; boolean.
- **Outputs / side effects:** PATH/functions/aliases captured into the snapshot.
- **Config / env:** the two keys.
- **Edge cases / guards:** disable if an rc file hard-exits on TTY checks.
- **Rebuild notes:** Login-shell env capture with explicit sources.

### Terminal → Container images (docker / singularity / modal / daytona)  `id: config-a.terminal.docker_image`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → labels `DOCKER IMAGE` (key `terminal.docker_image`, default `nikolaik/python-nodejs:python3.11-nodejs20`), `SINGULARITY IMAGE` (`terminal.singularity_image`, default `docker://nikolaik/python-nodejs:python3.11-nodejs20`), `MODAL IMAGE` (`terminal.modal_image`, default `nikolaik/python-nodejs:python3.11-nodejs20`), `DAYTONA IMAGE` (`terminal.daytona_image`, same default).
- **What it does:** Base image for each container backend.
- **How it works:** `config_defaults.py:474,482-484`; `tools/terminal_tool.py:1441-1442,1840-1842,2302-2306`; `tools/code_execution_tool.py:906-910`; `agent/prompt_builder.py:1210-1212` (image mentioned in the prompt); `batch_runner.py:306-308`. RL/benchmark environments register per-task overrides via `register_task_env_overrides()`.
- **Inputs / options:** image references.
- **Outputs / side effects:** image pulls.
- **Config / env:** the four keys; env `TERMINAL_DOCKER_IMAGE`, `TERMINAL_SINGULARITY_IMAGE`, `TERMINAL_MODAL_IMAGE`, `TERMINAL_DAYTONA_IMAGE`.
- **Edge cases / guards:** a shared Docker container keeps the image of whichever profile created it.
- **Rebuild notes:** Per-backend image setting.

### Terminal → Docker forward env  `id: config-a.terminal.docker_forward_env`
- **Surface:** Config | Tool | Security
- **Where:** Config page tab `Terminal` → label `DOCKER FORWARD ENV`, key `terminal.docker_forward_env` (list, default `[]`).
- **What it does:** Host env vars (resolved from the shell first, then `~/.hermes/.env`) forwarded into the Docker container; skills' `required_environment_variables` are merged automatically. Contrast `terminal.docker_env` (literal `KEY=value` dict, not a schema field).
- **How it works:** `config_defaults.py:475-481`; `tools/terminal_tool.py:1839,1936,1976`; `tools/file_tools.py:1535`; `agent/prompt_builder.py:1238`.
- **Inputs / options:** list of names.
- **Outputs / side effects:** credentials visible inside the container.
- **Config / env:** `terminal.docker_forward_env` (env `TERMINAL_DOCKER_FORWARD_ENV` JSON array); `terminal.docker_env` (env `TERMINAL_DOCKER_ENV` JSON dict).
- **Edge cases / guards:** forward only what you accept exposing to agent commands.
- **Rebuild notes:** Env allowlist for containers.

### Terminal → Vercel runtime  `id: config-a.terminal.vercel_runtime`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Terminal` → label `VERCEL RUNTIME`, description `Vercel Sandbox runtime`, select `node24` | `node22` | `python3.13` (`web_server.py:1297-1301`); default `node24`.
- **What it does:** Runtime for the `vercel_sandbox` backend.
- **How it works:** `config_defaults.py:485-487`; env `TERMINAL_VERCEL_RUNTIME` (`hermes_cli/setup.py:1759`); synced with `_SUPPORTED_VERCEL_RUNTIMES` in `terminal_tool.py`.
- **Inputs / options:** the three runtimes.
- **Outputs / side effects:** sandbox creation parameter.
- **Config / env:** `terminal.vercel_runtime`; env `TERMINAL_VERCEL_RUNTIME`.
- **Edge cases / guards:** only for `backend: vercel_sandbox`.
- **Rebuild notes:** Enum.

### Terminal → Container CPU / Memory / Disk / Persistent  `id: config-a.terminal.container_cpu`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → labels `CONTAINER CPU` (key `terminal.container_cpu`, number, default `1`), `CONTAINER MEMORY` (`terminal.container_memory`, number, default `5120` MB), `CONTAINER DISK` (`terminal.container_disk`, number, default `51200` MB), `CONTAINER PERSISTENT` (`terminal.container_persistent`, switch, default `true`).
- **What it does:** Resource limits for docker/singularity/modal/daytona/vercel_sandbox (ignored for local/ssh; `0` = unlimited for cpu/memory on Docker). `container_persistent`: Docker `true` = one long-lived shared container with persisted `/workspace` + `/root`, `false` = fresh container per session; Modal/Vercel = snapshot/restore filesystem; Daytona = stop/resume instead of delete; Singularity = writable overlay persists.
- **How it works:** `config_defaults.py:488-492`; `tools/terminal_tool.py:1864-1865,1928-1929,1971-1972`; `hermes_cli/status.py:468`; `hermes_cli/setup.py:811-867`; `hermes_cli/doctor.py:2419` (Vercel rejects non-default disk).
- **Inputs / options:** numbers; boolean.
- **Outputs / side effects:** container run flags; snapshot files.
- **Config / env:** the four keys; env `TERMINAL_CONTAINER_CPU`, `TERMINAL_CONTAINER_MEMORY`, `TERMINAL_CONTAINER_DISK`, `TERMINAL_CONTAINER_PERSISTENT`.
- **Edge cases / guards:** Daytona caps disk at 10 GiB (warning); `container_disk` needs overlay2 on XFS+pquota for Docker; persistence never preserves live processes/PID space on cloud sandboxes.
- **Rebuild notes:** Resource spec + persistence policy per backend.

### Terminal → Docker volumes / Mount cwd to workspace  `id: config-a.terminal.docker_volumes`
- **Surface:** Config | Tool | Security
- **Where:** Config page tab `Terminal` → labels `DOCKER VOLUMES` (key `terminal.docker_volumes`, list, default `[]`) and `DOCKER MOUNT CWD TO WORKSPACE` (`terminal.docker_mount_cwd_to_workspace`, switch, default `false`).
- **What it does:** Bind mounts in Docker `-v` syntax (`host:container[:ro]`), e.g. `/home/user/.hermes/cache/documents:/output` for gateway `MEDIA:` exports (emit the host path). `docker_mount_cwd_to_workspace` mounts the launch cwd (or the session's attached workspace when `container_persistent: false`) at `/workspace` — off by default because it weakens isolation.
- **How it works:** `config_defaults.py:493-506`; `tools/terminal_tool.py:381,1868,1934`; `tools/file_tools.py:1534`; `tools/code_execution_tool.py:926`; `agent/prompt_builder.py:1236-1237`.
- **Inputs / options:** list of mount strings; boolean.
- **Outputs / side effects:** host directories exposed to the sandbox.
- **Config / env:** the keys; env `TERMINAL_DOCKER_VOLUMES` (JSON array), `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE`.
- **Edge cases / guards:** YAML duplicate keys silently override — merge into one list.
- **Rebuild notes:** Mount list + opt-in cwd mount.

### Terminal → Docker network / Extra args / Shm size  `id: config-a.terminal.docker_network`
- **Surface:** Config | Tool | Security
- **Where:** Config page tab `Terminal` → labels `DOCKER NETWORK` (key `terminal.docker_network`, switch, default `true`), `DOCKER EXTRA ARGS` (`terminal.docker_extra_args`, list, default `[]`), `DOCKER SHM SIZE` (`terminal.docker_shm_size`, string, default `1g`).
- **What it does:** `docker_network: false` runs the container with `--network=none` (air-gapped; flipping it recreates an existing networked container, losing background processes). `docker_extra_args` are appended verbatim last to `docker run` (`--gpus=all`, `--add-host`, `--cap-add SETUID`, …) and can silently weaken hardening. `docker_shm_size` sets `/dev/shm` (Docker's 64 MB default breaks Chromium/Playwright and PyTorch DataLoader; `""`/`"0"` omits the flag).
- **How it works:** `config_defaults.py:507-516`; `tools/terminal_tool.py:1871,1872,1939,1941`; `tools/environments/docker.py:394`.
- **Inputs / options:** boolean; list of strings; size string.
- **Outputs / side effects:** `docker run` flags.
- **Config / env:** the keys; env `TERMINAL_DOCKER_NETWORK`, `TERMINAL_DOCKER_EXTRA_ARGS` (JSON array), `TERMINAL_DOCKER_SHM_SIZE`.
- **Edge cases / guards:** prefer `docker_network` over `--network=none` via extra args.
- **Rebuild notes:** Flag composition with a documented override order.

### Terminal → Docker run as host user / Shared container key  `id: config-a.terminal.docker_run_as_host_user`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → labels `DOCKER RUN AS HOST USER` (key `terminal.docker_run_as_host_user`, switch, default `false`) and `DOCKER SHARED CONTAINER KEY` (`terminal.docker_shared_container_key`, string, default `""`).
- **What it does:** `docker_run_as_host_user` appends `--user $(id -u):$(id -g)` so files written to bind mounts are owned by the host user (SETUID/SETGID caps omitted; the container can no longer `apt install`). `docker_shared_container_key` opts trusted profiles into one shared container identity: the `hermes-profile` label becomes a digest-suffixed derivation of the key; the first profile to start defines image/volumes/shm.
- **How it works:** `config_defaults.py:517-527`; `tools/terminal_tool.py:1870,1938,2012,1516`; `tools/code_execution_tool.py:927`; `tools/file_tools.py:1536`.
- **Inputs / options:** boolean; string.
- **Outputs / side effects:** container uid; container label.
- **Config / env:** the keys; env `TERMINAL_DOCKER_RUN_AS_HOST_USER`, `TERMINAL_DOCKER_SHARED_CONTAINER_KEY`.
- **Edge cases / guards:** similar-looking keys never collide (digest suffix).
- **Rebuild notes:** uid mapping + identity label.

### Terminal → Persistent shell  `id: config-a.terminal.persistent_shell`
- **Surface:** Config | Tool
- **Where:** Config page tab `Terminal` → label `PERSISTENT SHELL`, key `terminal.persistent_shell` (switch, default `true`).
- **What it does:** Keeps one long-lived `bash -l` alive across `execute()` calls so cwd, exported and shell variables survive between commands. Default on for non-local backends (SSH, where it also removes per-command connection overhead); local is opt-in only via env `TERMINAL_LOCAL_PERSISTENT=true`.
- **How it works:** `config_defaults.py:528-532`; `tools/terminal_tool.py:1854`; precedence config → `TERMINAL_SSH_PERSISTENT` → `TERMINAL_LOCAL_PERSISTENT`; listed in `hermes_cli/dump.py:244`. Commands needing `stdin_data` or sudo fall back to one-shot mode (stdin is occupied by the IPC protocol).
- **Inputs / options:** boolean.
- **Outputs / side effects:** persistent remote/local shell process communicating via temp files.
- **Config / env:** `terminal.persistent_shell`; env `TERMINAL_PERSISTENT_SHELL`, `TERMINAL_SSH_PERSISTENT`, `TERMINAL_LOCAL_PERSISTENT`.
- **Edge cases / guards:** `hermes config set terminal.persistent_shell false` disables.
- **Rebuild notes:** Long-lived shell with file-based IPC and one-shot fallback.

## Display (87 fields)

The `Display` tab holds 64 `display.*` keys plus the merged `dashboard.*` (20) and `human_delay.*` (3) sections. Gateway-side display settings resolve through `gateway/display_config.py` (global `display.<key>` → per-platform `display.platforms.<platform>.<key>` → shipped per-platform tier defaults, `display_config.py:138-182,240`); CLI-side settings are read from `CLI_CONFIG["display"]` in `cli.py:5232-5326`.

### Display → Compact  `id: config-a.display.compact`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → label `COMPACT`, key `display.compact` (switch, default `false`).
- **What it does:** Compact single-line banner instead of the full ASCII banner with tool/skill summary; denser output.
- **How it works:** `config_defaults.py:1399`; `cli.py:5232` (constructor arg overrides config); tip `hermes_cli/tips.py:111`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** CLI chrome only.
- **Config / env:** `display.compact`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Banner mode flag.

### Display → Personality  `id: config-a.display.personality`
- **Surface:** Config | CLI | TUI | Desktop app
- **Where:** Config page tab `Display` → label `PERSONALITY`, key `display.personality` (string, default `""`); runtime `/personality <name>`.
- **What it does:** Holds the NAME of the selected personality overlay (built-ins `helpful`, `concise`, `technical`, `creative`, `teacher`, `kawaii`, `catgirl`, `pirate`, `shakespeare`, `surfer`, `noir`, `uwu`, `philosopher`, `hype`, or a custom entry from top-level `personalities:`); empty = no overlay. Authoritative since PR #81946 — never stored in `agent.system_prompt`.
- **How it works:** `config_defaults.py:1400`; `hermes_cli/personality.py:15-23,153-177` (atomic YAML round-trip write); `gateway/run.py:10020`; `tui_gateway/server.py:7408` warns on unknown names.
- **Inputs / options:** personality name.
- **Outputs / side effects:** system-prompt overlay.
- **Config / env:** `display.personality`; custom definitions in `personalities` (out of shard).
- **Edge cases / guards:** unknown name → ignored with warning.
- **Rebuild notes:** Name → prompt-block lookup.

### Display → Resume display / Resume recap tuning  `id: config-a.display.resume_display`
- **Surface:** Config | Web dashboard | CLI
- **Where:** Config page tab `Display` → labels `RESUME DISPLAY` (description `How resumed sessions display history`, select `minimal` | `full` | `off`, `web_server.py:1370-1374`; default `full`), `RESUME EXCHANGES` (`display.resume_exchanges`, number, default `10`), `RESUME MAX USER CHARS` (`display.resume_max_user_chars`, default `300`), `RESUME MAX ASSISTANT CHARS` (`display.resume_max_assistant_chars`, default `200`), `RESUME MAX ASSISTANT LINES` (`display.resume_max_assistant_lines`, default `3`), `RESUME SKIP TOOL ONLY` (`display.resume_skip_tool_only`, switch, default `true`).
- **What it does:** Controls the recap printed on `/resume`/`hermes -c` startup: full history, a one-liner, or nothing; how many user+assistant pairs to show; truncation of user text and of non-last assistant text/lines; and whether tool-call-only assistant entries (`[2 tool calls: terminal, read_file]`) are skipped.
- **How it works:** `config_defaults.py:1401-1416`; `cli.py:5257`; `hermes_cli/cli_agent_setup_mixin.py:801-805`; defaults mirrored in `cli.py:497-501`; tip `hermes_cli/tips.py:113`.
- **Inputs / options:** enum; integers; boolean.
- **Outputs / side effects:** scrollback text only.
- **Config / env:** the six keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Recap renderer with budget knobs.

### Display → Busy input mode / Busy steer ack  `id: config-a.display.busy_input_mode`
- **Surface:** Config | Web dashboard | CLI | Gateway/Telegram
- **Where:** Config page tab `Display` → labels `BUSY INPUT MODE` (description `Input behavior while agent is running`, select `interrupt` | `queue` | `steer`, `web_server.py:1375-1379`; default `interrupt`) and `BUSY STEER ACK ENABLED` (`display.busy_steer_ack_enabled`, switch, default `true`); runtime `/busy <mode>`.
- **What it does:** What Enter/new messages do while the agent runs: `interrupt` redirects, `queue` holds the message for the next turn, `steer` injects it mid-run after the next tool call (falls back to `queue` if not running or images attached). `busy_steer_ack_enabled: false` hides the "Steered into current run" bubble (steering still happens). Ctrl+C / `/stop` always interrupt.
- **How it works:** `config_defaults.py:1417-1421`; `gateway/run.py:10265-10305`, `gateway/slash_commands.py:4307`, `hermes_cli/cli_commands_mixin.py:3907`, `tui_gateway/server.py:10193,14335`; steer ack `gateway/display_config.py:54,286`, `gateway/run.py:2856-2860,11200`.
- **Inputs / options:** enum; boolean.
- **Outputs / side effects:** message routing during a turn.
- **Config / env:** the two keys; env `HERMES_GATEWAY_BUSY_INPUT_MODE`, `HERMES_GATEWAY_BUSY_ACK_ENABLED` (documented).
- **Edge cases / guards:** steer carries text only.
- **Rebuild notes:** Input policy state machine.

### Display → CLI multiline shortcuts  `id: config-a.display.cli_multiline_shortcuts`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → label `CLI MULTILINE SHORTCUTS`, key `display.cli_multiline_shortcuts` (switch, default `true`).
- **What it does:** Beyond Alt+Enter, Ctrl+J inserts a newline, a trailing backslash + Enter continues the draft, and supporting terminals are asked to report Shift+Enter distinctly. `false` restores the legacy Ctrl+J submit fallback for odd POSIX PTYs whose Enter arrives as LF.
- **How it works:** `config_defaults.py:1422-1428`; `cli.py:4471-4547,18737`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** key bindings.
- **Config / env:** `display.cli_multiline_shortcuts`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Keybinding profile toggle.

### Display → Interface  `id: config-a.display.interface`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Display` → label `INTERFACE`, key `display.interface` (string, default `cli`).
- **What it does:** Which interface bare `hermes` / `hermes chat` launches: `cli` (prompt_toolkit REPL) or `tui` (Ink TUI).
- **How it works:** `config_defaults.py:1429-1434`; `hermes_cli/main.py:275-325,3120-3160` precedence: `--cli` > `--tui` > no TTY → classic > `HERMES_TUI=1` > this key > classic. `hermes_cli/_parser.py:93-94` help text.
- **Inputs / options:** `cli` | `tui`.
- **Outputs / side effects:** launcher choice.
- **Config / env:** `display.interface`; env `HERMES_TUI`.
- **Edge cases / guards:** never hijacks non-TTY invocations (kanban/cron `chat -q`).
- **Rebuild notes:** Launch resolver with TTY gate.

### Display → TUI auto-resume recent / TUI agents nudge  `id: config-a.display.tui_auto_resume_recent`
- **Surface:** Config | TUI
- **Where:** Config page tab `Display` → labels `TUI AUTO RESUME RECENT` (key `display.tui_auto_resume_recent`, switch, default `false`) and `TUI AGENTS NUDGE` (`display.tui_agents_nudge`, switch, default `true`).
- **What it does:** `hermes --tui` auto-resumes the most recent human-facing session on launch (`HERMES_TUI_RESUME=<id>` always wins); and shows a one-time hint (`subagents working · /agents to watch live`) the first time a turn delegates.
- **How it works:** `config_defaults.py:1435-1444`; read by the TUI: `ui-tui/src/app/createGatewayEventHandler.ts:517-538,717-725`, types `ui-tui/src/gatewayTypes.ts:105-106`; `tui_gateway/methods_session.py:288`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** TUI behaviour only.
- **Config / env:** the two keys; env `HERMES_TUI_RESUME`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Client-side preference flags served via `config.get`.

### Display → Bell on complete  `id: config-a.display.bell_on_complete`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → label `BELL ON COMPLETE`, key `display.bell_on_complete` (switch, default `false`).
- **What it does:** Rings the terminal bell when a response finishes (works over SSH).
- **How it works:** `config_defaults.py:1445`; `cli.py:5259`; tip `hermes_cli/tips.py:108`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** `\a`.
- **Config / env:** `display.bell_on_complete`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Trivial.

### Display → Show reasoning / Reasoning full  `id: config-a.display.show_reasoning`
- **Surface:** Config | CLI | TUI | Gateway/Telegram
- **Where:** Config page tab `Display` → labels `SHOW REASONING` (key `display.show_reasoning`, switch, default `true`) and `REASONING FULL` (`display.reasoning_full`, switch, default `false`); runtime `/reasoning show|hide`.
- **What it does:** Stream the model's thinking live before the response (default on because thinking phases can take tens of seconds); the post-response "Reasoning" recap box collapses to the first 10 lines unless `reasoning_full` is true.
- **How it works:** `config_defaults.py:1446-1455`; `cli.py:5264`, `hermes_cli/cli_commands_mixin.py:3825-3848` (persists both), `tui_gateway/server.py:5957-5959,14568`, `tui_gateway/methods_config.py:269`, `gateway/run.py:10255`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** visible reasoning text.
- **Config / env:** the two keys.
- **Edge cases / guards:** live streaming is always full.
- **Rebuild notes:** Display gate on the reasoning channel.

### Display → Memory notifications  `id: config-a.display.memory_notifications`
- **Surface:** Config | Gateway/Telegram | TUI
- **Where:** Config page tab `Display` → label `MEMORY NOTIFICATIONS`, key `display.memory_notifications` (string, default `on`).
- **What it does:** Background self-improvement review notices in chat: `off` (review still runs), `on` (generic `💾 Memory updated`), `verbose` (compact content preview). Per-platform override `display.platforms.<p>.memory_notifications`.
- **How it works:** `config_defaults.py:1456-1461`; `gateway/run.py:6385-6389`; `tui_gateway/server.py:3401,5966-5972,9254`.
- **Inputs / options:** `off` | `on` | `verbose`.
- **Outputs / side effects:** chat notices.
- **Config / env:** `display.memory_notifications`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Verbosity enum.

### Display → Background process notifications  `id: config-a.display.background_process_notifications`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Display` → label `BACKGROUND PROCESS NOTIFICATIONS`, key `display.background_process_notifications` (string, default `concise`).
- **What it does:** How chatty the process watcher is for `terminal(background=true, notify_on_complete=true)`: `concise` (one-line status; failures append an output tail), `all` (running-output updates + final raw output), `result` (final raw output only), `error` (final raw output only on non-zero exit), `off`.
- **How it works:** `config_defaults.py:1462-1470`; `gateway/run.py:10486,27045,27868`; migration set `all`→`concise` (`hermes_cli/config_migrations.py:726-733`).
- **Inputs / options:** the five modes.
- **Outputs / side effects:** watcher messages.
- **Config / env:** `display.background_process_notifications`.
- **Edge cases / guards:** subagent child processes are additionally gated by `delegation.surface_child_process_notifications`.
- **Rebuild notes:** Verbosity enum on a process watcher.

### Display → Streaming  `id: config-a.display.streaming`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → label `STREAMING`, key `display.streaming` (switch, default `false`).
- **What it does:** CLI-only: stream tokens into the response box as they arrive instead of waiting for the full reply; tool calls still captured silently; falls back if the provider can't stream. Gateway streaming is the separate `streaming.enabled` master switch (Streaming shard) plus `display.platforms.<p>.streaming`.
- **How it works:** `config_defaults.py:1471`; `cli.py:5287-5288`; `gateway/display_config.py:12,240` explicitly skips `display.streaming` for gateways; `agent/chat_completion_helpers.py:5175` suggests disabling on slow non-stream providers; `hermes_cli/dump.py:249`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** token-by-token render.
- **Config / env:** `display.streaming`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Streaming renderer toggle.

### Display → Timestamps / Timestamp format  `id: config-a.display.timestamps`
- **Surface:** Config | CLI | TUI | Desktop app
- **Where:** Config page tab `Display` → labels `TIMESTAMPS` (key `display.timestamps`, switch, default `false`) and `TIMESTAMP FORMAT` (`display.timestamp_format`, string, default `%H:%M`); runtime `/timestamps`.
- **What it does:** Prefix user/assistant labels (CLI), TUI rows and the desktop transcript with a strftime-formatted time.
- **How it works:** `config_defaults.py:1472-1473`; `cli.py:5290-5291`; `hermes_cli/cli_commands_mixin.py:3728-3768`; `tui_gateway/server.py:9677` persists authoring time for the desktop.
- **Inputs / options:** boolean; strftime string (e.g. `%b-%d %H:%M`).
- **Outputs / side effects:** display only.
- **Config / env:** the two keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Format string setting.

### Display → Final response markdown  `id: config-a.display.final_response_markdown`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → label `FINAL RESPONSE MARKDOWN`, key `display.final_response_markdown` (string, default `strip`).
- **What it does:** How the classic CLI prints the final answer: `render` (rich markdown), `strip` (remove markdown syntax; tables still realigned), `raw`.
- **How it works:** `config_defaults.py:1474`; `cli.py:5292-5296` (invalid → `strip`), applied at `cli.py:8475-8502` (`_strip_markdown_syntax`, `realign_markdown_tables`).
- **Inputs / options:** `render` | `strip` | `raw`.
- **Outputs / side effects:** terminal text.
- **Config / env:** `display.final_response_markdown`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Output post-processor enum.

### Display → Persistent output / Max lines / Rebuild scrollback on redraw / Persist prompts  `id: config-a.display.persistent_output`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → labels `PERSISTENT OUTPUT` (key `display.persistent_output`, switch, default `true`), `PERSISTENT OUTPUT MAX LINES` (`display.persistent_output_max_lines`, number, default `200`), `CLI REBUILD SCROLLBACK ON REDRAW` (`display.cli_rebuild_scrollback_on_redraw`, switch, default `false`), `PERSIST PROMPTS` (`display.persist_prompts`, switch, default `true`).
- **What it does:** Preserve recent CLI output across Ctrl+L, `/redraw` and resize full-screen clears (up to N lines); optionally also wipe terminal scrollback (CSI 3J) on such redraws for terminals/tmux that stamp stale chrome; print a one-line summary of resolved modal prompts (approval/clarify) into scrollback so the question and decision survive panel repaint.
- **How it works:** `config_defaults.py:1475-1490`; `cli.py:5266-5267,6142,16059-16063`.
- **Inputs / options:** booleans; integer.
- **Outputs / side effects:** terminal replay behaviour.
- **Config / env:** the four keys.
- **Edge cases / guards:** disable persistent output if an emulator misbehaves with replayed scrollback.
- **Rebuild notes:** Scrollback buffer with replay on clear.

### Display → Inline diffs / File mutation verifier / Turn completion explainer / Credits notices  `id: config-a.display.inline_diffs`
- **Surface:** Config | CLI | Core
- **Where:** Config page tab `Display` → labels `INLINE DIFFS` (key `display.inline_diffs`, switch, default `true`), `FILE MUTATION VERIFIER` (`display.file_mutation_verifier`, switch, default `true`), `TURN COMPLETION EXPLAINER` (`display.turn_completion_explainer`, switch, default `true`), `CREDITS NOTICES` (`display.credits_notices`, switch, default `true`).
- **What it does:** Inline diff previews for `write_file`/`patch`/`skill_manage` in the CLI. Verifier footer (`⚠️ File-mutation verifier: N file(s) were NOT modified this turn …` with per-file reasons) appended when a write/patch failed and was never superseded. Explainer line appended when a turn ends abnormally with no usable reply (empty after retries, truncated stream, pending tool result, iteration/budget limit) replacing the bare `(empty)` sentinel. Nous credits status-bar notices (usage bands, grant-spent, depleted/restored; `/usage` still works when off).
- **How it works:** `config_defaults.py:1491-1514`; `cli.py:5298-5299`; `run_agent.py:3764,3874,4370`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** response footers / status bar notices.
- **Config / env:** the four keys; env `HERMES_FILE_MUTATION_VERIFIER=0` disables the verifier.
- **Edge cases / guards:** verifier only fires for failures still outstanding at turn end.
- **Rebuild notes:** Post-turn integrity annotations.

### Display → Show cost / Battery  `id: config-a.display.show_cost`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Display` → labels `SHOW COST` (key `display.show_cost`, switch, default `false`) and `BATTERY` (`display.battery`, switch, default `false`); runtime `/battery`.
- **What it does:** Show an estimated `$` cost segment in the CLI status bar; show a colour-coded battery read-out as the first status-bar element (no-op without a battery).
- **How it works:** `config_defaults.py:1515-1519`; battery `cli.py:5792-5793,6367-6403`, `tui_gateway/server.py:14719`. `show_cost` appears in the TUI wire type (`ui-tui/src/gatewayTypes.ts:89`) but no Python/TUI reader was found by grep in v2026.8.31 (listed as unresolved).
- **Inputs / options:** booleans.
- **Outputs / side effects:** status-bar segments.
- **Config / env:** the two keys.
- **Edge cases / guards:** `status_bar.fields` must also include `battery`.
- **Rebuild notes:** Status-bar segment toggles.

### Display → Focus view / Focus saved tool progress  `id: config-a.display.focus_view`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Display` → labels `FOCUS VIEW` (key `display.focus_view`, switch, default `false`) and `FOCUS SAVED TOOL PROGRESS` (`display.focus_saved_tool_progress`, string, default `all`); runtime `/focus on|off`.
- **What it does:** Display-only reduced-output mode: pins `tool_progress` to `off`, stashes the previous mode in `focus_saved_tool_progress`, prints `⋯ N tool lines hidden · /focus off to show` after each turn and pins a `◉ focus` badge in the status bar; never changes what is sent to the model.
- **How it works:** `config_defaults.py:1520-1528`; `hermes_cli/focus_view.py:32`; `cli.py:5242`; `tui_gateway/server.py:14398-14407`.
- **Inputs / options:** boolean; tool-progress mode name (`off`|`new`|`all`|`verbose`|`log`).
- **Outputs / side effects:** suppressed tool lines on screen.
- **Config / env:** the two keys.
- **Edge cases / guards:** cycling `/verbose` while focused hands the mode back and clears the badge.
- **Rebuild notes:** Mode overlay with saved-state restore.

### Display → Skin  `id: config-a.display.skin`
- **Surface:** Config | Web dashboard | CLI
- **Where:** Config page tab `Display` → label `SKIN`, description `CLI visual theme`, select `default` | `ares` | `mono` | `slate` (`web_server.py:1360-1364`); default `default`; runtime `/skin <name>`, `hermes skin`.
- **What it does:** CLI visual theme (banner colours, spinner faces/verbs/wings, tool prefix, response label, branding). Built-ins also include `daylight`, `warm-lightmode`, `poseidon`, `sisyphus`, `charizard`; custom skins are YAML files in `~/.hermes/skins/<name>.yaml` (schema: `colors.*`, `spinner.*`, `branding.*`, `tool_prefix`).
- **How it works:** `config_defaults.py:1529`; `hermes_cli/skin_engine.py:141`; `hermes_cli/skin_cmd.py:35-38`; `hermes_cli/cli_commands_mixin.py:3431`; `hermes_cli/config.py:5956-5961` bumps the skin file mtime so a running CLI applies it; `tui_gateway/server.py:4957`.
- **Inputs / options:** any built-in or custom skin name (the dashboard select lists only four).
- **Outputs / side effects:** colours/strings in CLI.
- **Config / env:** `display.skin`; env `HERMES_TUI_THEME` for the TUI (documented).
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Theme loader with YAML overrides.

### Display → Language  `id: config-a.display.language`
- **Surface:** Config | CLI | Gateway/Telegram
- **Where:** Config page tab `Display` → label `LANGUAGE`, key `display.language` (string, default `en`).
- **What it does:** UI language for static messages (CLI approval prompt, some gateway slash replies such as restart-drain notices, "approval expired", "goal cleared"); not agent replies, logs, tool output or command descriptions. Supported: `en`, `zh`, `zh-hant`, `ja`, `de`, `es`, `fr`, `tr`, `uk`, `af`, `ko`, `it`, `ga`, `pt`, `ru`, `hu`; unknown → `en`.
- **How it works:** `config_defaults.py:1530-1534`; `agent/i18n.py:25,192-214` (read once per process; reload hook); catalogs in `locales/*.yaml`.
- **Inputs / options:** language code.
- **Outputs / side effects:** translated static strings.
- **Config / env:** `display.language`; env `HERMES_LANGUAGE` overrides.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Locale catalog lookup.

### Display → TUI status indicator / CLI refresh interval  `id: config-a.display.tui_status_indicator`
- **Surface:** Config | TUI | CLI
- **Where:** Config page tab `Display` → labels `TUI STATUS INDICATOR` (key `display.tui_status_indicator`, string, default `kaomoji`) and `CLI REFRESH INTERVAL` (`display.cli_refresh_interval`, number, default `1.0`); runtime `/indicator <style>`.
- **What it does:** TUI busy-indicator style: `kaomoji`, `emoji`, `unicode` (braille spinner), `ascii`. Seconds between prompt_toolkit redraws when idle in the classic CLI (keeps wall-clock status-bar fields ticking; `0` disables if it fights auto-scroll).
- **How it works:** `config_defaults.py:1535-1545`; `hermes_cli/cli_commands_mixin.py:3930-3953`, `tui_gateway/methods_config.py:226`, `tui_gateway/server.py:14781`, `ui-tui/src/app/useConfigSync.ts:298`; `cli.py:20776-20782`.
- **Inputs / options:** enum; float seconds.
- **Outputs / side effects:** spinner glyphs; redraw timer.
- **Config / env:** the two keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Cosmetic enum + refresh timer.

### Display → User message preview  `id: config-a.display.user_message_preview`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → labels `FIRST LINES` (key `display.user_message_preview.first_lines`, number, default `2`) and `LAST LINES` (`display.user_message_preview.last_lines`, number, default `2`).
- **What it does:** How many leading/trailing lines of a submitted multi-line user message the CLI echoes back into scrollback.
- **How it works:** `config_defaults.py:1546-1549`; `cli.py:5322-5326`; `hermes_cli/config.py:5023-5024` (shown by `hermes config`).
- **Inputs / options:** integers.
- **Outputs / side effects:** scrollback echo.
- **Config / env:** the two keys.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Head/tail preview.

### Display → Interim assistant messages / Show commentary  `id: config-a.display.interim_assistant_messages`
- **Surface:** Config | Gateway/Telegram | Desktop app
- **Where:** Config page tab `Display` → labels `INTERIM ASSISTANT MESSAGES` (key `display.interim_assistant_messages`, switch, default `true`) and `SHOW COMMENTARY` (`display.show_commentary`, switch, default `true`).
- **What it does:** Gateway: send completed mid-turn assistant status messages as separate chat messages; Desktop: keep mid-turn narration in the transcript instead of collapsing to the final message. `show_commentary`: deliver Codex Responses models' commentary channel as visible mid-turn updates (else it falls back to the reasoning channel, visible only with `show_reasoning`).
- **How it works:** `config_defaults.py:1550-1556`; `tui_gateway/server.py:601,8333,13043`; `agent/agent_init.py:1809`, `agent/codex_runtime.py:638`, `run_agent.py:6716`.
- **Inputs / options:** booleans.
- **Outputs / side effects:** extra chat messages.
- **Config / env:** the two keys.
- **Edge cases / guards:** independent of `tool_progress` and gateway streaming.
- **Rebuild notes:** Interim-message channel gates.

### Display → Tool progress command / Tool preview length / Friendly tool labels  `id: config-a.display.tool_progress_command`
- **Surface:** Config | Gateway/Telegram | CLI
- **Where:** Config page tab `Display` → labels `TOOL PROGRESS COMMAND` (key `display.tool_progress_command`, switch, default `false`), `TOOL PREVIEW LENGTH` (`display.tool_preview_length`, number, default `0`), `FRIENDLY TOOL LABELS` (`display.friendly_tool_labels`, switch, default `true`).
- **What it does:** Expose `/verbose` on messaging platforms (CLI-only by default; the command cycles `tool_progress` and saves to config). Max chars for tool-call previews (`0` = full paths/commands). Human-phrased tool status labels (`Searching the web for …`, `Reading <file>`, `Browsing <url>`) for built-in tools in the CLI spinner and gateway/desktop progress; plugin/MCP tools keep the raw preview.
- **How it works:** `config_defaults.py:1557-1568`; `gateway/slash_commands.py:4214-4229`, `hermes_cli/commands.py:282`, `gateway/run.py:4785`; `agent/display.py:111,683,1553`; `cli.py:810,818`.
- **Inputs / options:** boolean; integer; boolean.
- **Outputs / side effects:** command availability; preview text.
- **Config / env:** the three keys; env `HERMES_TOOL_PROGRESS`, `HERMES_TOOL_PROGRESS_MODE` (documented, for the mode itself).
- **Edge cases / guards:** `display.tool_progress` (`off`|`new`|`all`|`verbose`|`log`) and `display.tool_progress_overrides` (deprecated) are not seeded in `DEFAULT_CONFIG` and so are not schema fields — see Handoffs.
- **Rebuild notes:** Progress-feed presentation options.

### Display → Turn summary / Spinner token flow  `id: config-a.display.turn_summary`
- **Surface:** Config | CLI
- **Where:** Config page tab `Display` → labels `TURN SUMMARY` (key `display.turn_summary`, switch, default `true`) and `SPINNER TOKEN FLOW` (`display.spinner_token_flow`, switch, default `true`).
- **What it does:** After each interactive CLI turn print one dim accounting line (`⋯ 12.4s · edited 2 files +18 -3 · read 4 files · ran 3 commands`; failed calls not counted; four verb segments max + `+N more`; nothing for tool-less turns). Append cumulative turn output tokens to the spinner timer (`⚡ Reading cli.py  (  2.3s · ↓ 1.2k tok)`).
- **How it works:** `config_defaults.py:1569-1578`; `cli.py:5301-5307,6960,21076`; `agent/turn_summary.py:264`. Suppressed in quiet mode, when `tool_progress` is `off`, in `-Q` batch runs and on gateway surfaces.
- **Inputs / options:** booleans.
- **Outputs / side effects:** CLI chrome.
- **Config / env:** the two keys.
- **Edge cases / guards:** line deltas only when the tool result reports a diff (`patch`).
- **Rebuild notes:** Tally observed from the tool-progress feed.

### Display → Tool progress grouping / Reasoning style / Ephemeral system TTL  `id: config-a.display.tool_progress_grouping`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Display` → labels `TOOL PROGRESS GROUPING` (key `display.tool_progress_grouping`, string, default `accumulate`), `REASONING STYLE` (`display.reasoning_style`, string, default `code`), `EPHEMERAL SYSTEM TTL` (`display.ephemeral_system_ttl`, number, default `0`).
- **What it does:** On editing-capable platforms, `accumulate` edits one progress bubble in place, `separate` sends one message per tool. Reasoning summary rendering: `code` (💭 fenced block), `blockquote` (`> `), `subtext` (`-# ` Discord small text; Discord defaults to `subtext`). Auto-delete system-notice replies (`✨ New session started!`, `♻ Restarting gateway…`, `⚡ Stopped…`) after N seconds on platforms supporting deletion (Telegram); `0` disables. Per-platform overrides via `display.platforms.<p>.*`.
- **How it works:** `config_defaults.py:1579-1611`; `gateway/display_config.py:35,42,138,311-314`, `gateway/run.py:22363,30231`; `gateway/platforms/base.py:2781,4291` (`EphemeralReply`).
- **Inputs / options:** `accumulate`|`separate`; `code`|`blockquote`|`subtext`; seconds.
- **Outputs / side effects:** message shapes; deletions.
- **Config / env:** the three keys.
- **Edge cases / guards:** only slash-command replies are ephemeral, never agent content.
- **Rebuild notes:** Platform-aware rendering options.

### Display → Platforms → streaming (telegram / discord / slack / wecom)  `id: config-a.display.platforms.streaming`
- **Surface:** Config | Gateway/Telegram | Web dashboard
- **Where:** Config page tab `Display` → labels `STREAMING` ×4 with key paths `display.platforms.telegram.streaming` (default `true`), `display.platforms.discord.streaming` (`false`), `display.platforms.slack.streaming` (`false`), `display.platforms.wecom.streaming` (`true`); also toggled from the dashboard `Channels` page.
- **What it does:** Per-platform gap-fillers for gateway streaming once the master `streaming.enabled` is on: Telegram (native `sendMessageDraft`) and WeCom (`msgtype: stream`) stream by default; Discord/Slack (edit-based, flickery) do not.
- **How it works:** `config_defaults.py:1612-1635`; `gateway/display_config.py:182` (`wecom` tier), platform adapters read `extra.get("streaming")` (e.g. `plugins/platforms/slack/adapter.py:2756`). User values win over shipped defaults (deep-merge).
- **Inputs / options:** booleans; other platform keys (`signal`, `whatsapp`, `matrix`, `mattermost`, `email`, `sms`, `homeassistant`, `dingtalk`, `feishu`, `weixin`, `bluebubbles`, `qqbot`) accept the same sub-keys (`tool_progress`, `streaming`, `memory_notifications`, `reasoning_style`, `tool_progress_grouping`, `runtime_footer`, `status_phrases`, `cleanup_progress`, `busy_ack_detail`, `long_running_notifications`, `interim_assistant_messages`) but only these four seeded leaves are schema fields.
- **Outputs / side effects:** progressive edits vs whole replies.
- **Config / env:** the four keys + `streaming.enabled` (Streaming shard).
- **Edge cases / guards:** no effect while `streaming.enabled: false`.
- **Rebuild notes:** Per-platform override map over global defaults.

### Display → Runtime footer (enabled / fields)  `id: config-a.display.runtime_footer`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Display` → labels `ENABLED` (key `display.runtime_footer.enabled`, switch, default `false`) and `FIELDS` (`display.runtime_footer.fields`, list, default `model, context_pct, cwd`); runtime `/footer`.
- **What it does:** Append a runtime-context footer (e.g. `model · 68% · ~/projects/hermes`) to the FINAL message of each gateway turn; fields in order: `model` (vendor prefix dropped), `context_pct`, `latency` (opt-in, `22s`/`1m05s`), `cwd` (home-relative); unavailable fields are skipped.
- **How it works:** `config_defaults.py:1636-1642`; `gateway/run.py:22385`; `gateway/slash_commands.py:4353-4409`; `hermes_cli/cli_commands_mixin.py:3675-3718`.
- **Inputs / options:** boolean; ordered list of field names.
- **Outputs / side effects:** footer text.
- **Config / env:** the two keys; per-platform `display.platforms.<p>.runtime_footer`.
- **Edge cases / guards:** interim updates never get the footer.
- **Rebuild notes:** Footer formatter with field registry.

### Display → Status bar fields  `id: config-a.display.status_bar.fields`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Display` → label `FIELDS`, key `display.status_bar.fields` (list, default `[]`).
- **What it does:** Visibility filter for the CLI/TUI status bar: empty = default set (everything except `total_tokens`); otherwise only the listed fields, in built-in order. Available: `model`, `context_detail`, `context_pct`, `cache_hit`, `latency`, `tps`, `compressions`, `bg_tasks`, `bg_processes`, `bg_subagents`, `goal`, `duration`, `prompt_elapsed`, `idle_since`, `focus`, `yolo`, `stash`, `battery`, `title`, `total_tokens`.
- **How it works:** `config_defaults.py:1643-1645`; `cli.py:7438`; TUI status rule renders `cache_hit`/`latency`/`tps` as width-budgeted tail segments (◎/◷/↑) at ≥96/104/110 columns. Narrow terminals still drop wide-only fields; `latency`/`tps` hidden until API calls recorded; `battery`/`title` also need their own toggles.
- **Inputs / options:** list of field names.
- **Outputs / side effects:** status bar contents (next session start).
- **Config / env:** `display.status_bar.fields`.
- **Edge cases / guards:** visibility only, not ordering.
- **Rebuild notes:** Field allowlist over a fixed layout.

### Display → Copy shortcut  `id: config-a.display.copy_shortcut`
- **Surface:** Config
- **Where:** Config page tab `Display` → label `COPY SHORTCUT`, key `display.copy_shortcut` (string, default `auto`).
- **What it does:** Declared as the copy-to-clipboard shortcut preference: `auto` (platform default) | `ctrl_c` | `ctrl_shift_c` | `disabled`.
- **How it works:** `config_defaults.py:1646` is the only occurrence in the repository (no Python, TUI or desktop reader found by grep) — a declared-but-unread key in v2026.8.31.
- **Inputs / options:** the four strings.
- **Outputs / side effects:** none observed.
- **Config / env:** `display.copy_shortcut`.
- **Edge cases / guards:** unresolved (see end of file).
- **Rebuild notes:** If implemented, map to a terminal keybinding for copying the last response.

### Display → Pet (enabled / slug / render mode / scale / unicode cols)  `id: config-a.display.pet`
- **Surface:** Config | CLI | TUI | Desktop app
- **Where:** Config page tab `Display` → labels `ENABLED` (key `display.pet.enabled`, switch, default `false`), `SLUG` (`display.pet.slug`, string, default `""`), `RENDER MODE` (`display.pet.render_mode`, string, default `auto`), `SCALE` (`display.pet.scale`, number, default `0.33`), `UNICODE COLS` (`display.pet.unicode_cols`, number, default `0`); CLI `hermes pets` (`install`, `use`, `scale`, …), `/pet`, `/pet toggle`, desktop pet picker/slider.
- **What it does:** Petdex animated mascot that reacts to agent activity. `slug` picks an installed pet from `~/.hermes/pets/` (empty → first installed). `render_mode`: `auto` (detect kitty/iTerm2/sixel, else unicode half-blocks; VS Code terminal forced to unicode) | `kitty` | `iterm` | `sixel` | `unicode` | `off`. `scale` is the master size scalar relative to native 192×208 frames (desktop pixels and terminal column width derive from it); `unicode_cols` pins the terminal width (`0` = derive from scale).
- **How it works:** `config_defaults.py:1647-1674`; `hermes_cli/pets.py:86-138,164,264-267,342-360,496`; `agent/pet/store.py:12,141`; `agent/pet/render.py:40-66,112`; `agent/pet/constants.py:28`; `tui_gateway/server.py:11150`, `tui_gateway/methods_session.py:1865,2179-2193`; `cli.py:7086`.
- **Inputs / options:** boolean; slug; enum; float (clamped); integer.
- **Outputs / side effects:** sprite frames in the terminal/desktop; no effect on prompt caching.
- **Config / env:** the five keys.
- **Edge cases / guards:** half-block fallback clamps to a legibility floor.
- **Rebuild notes:** Sprite renderer with protocol detection.

### Display → Dashboard theme  `id: config-a.dashboard.theme`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Display 87` → sub-section divider `dashboard` → label `THEME`, hint line `dashboard.theme`, description `Web dashboard visual theme` (select). Also flipped from the top bar theme button (`aria-label="Switch theme"`, text e.g. `HERMES TEAL`, `title="Switch theme: Hermes Teal"`), which POSTs the pick.
- **What it does:** Chooses the colour scheme the web dashboard SPA renders with.
- **How it works:** Override entry `hermes_cli/web_server.py:1364-1368` (`type: select`, options list). Read on `GET` of the theme endpoint at `web_server.py:17757` and `web_server.py:18306` (`cfg_get(config, "dashboard", "theme", default="default")`); the theme switcher writes `config["dashboard"]["theme"] = body.name` (`web_server.py:18336`) and answers `{"ok": True, "theme": body.name}` (`web_server.py:18338`). A separate font override id lives beside it (`_FONT_DEFAULT_ID = "theme"`, `web_server.py:18348`, meaning "use the theme's font"). TUI has its own parallel `theme` key handling (`tui_gateway/server.py:14722`, `tui_gateway/methods_config.py:331`).
- **Inputs / options:** exactly six select values — `default`, `midnight`, `ember`, `mono`, `cyberpunk`, `rose`.
- **Outputs / side effects:** writes `dashboard.theme` in `~/.hermes/config.yaml`; the SPA re-renders with the new palette; unknown values are coerced rather than 400'd (same defensive pattern as the font id, `web_server.py:18376`).
- **Config / env:** `dashboard.theme`. No env var.
- **Edge cases / guards:** this is the *web* theme; the CLI/TUI theme is `display.skin` (options `default`, `ares`, `mono`, `slate`) — two different keys with overlapping value names.
- **Rebuild notes:** Store a palette id, serve it with the config, apply as a CSS class on the root. A better version would allow a user-supplied palette file and preview the palette in the picker.

### Display → Dashboard turn isolation (+ compute-host heartbeat / respawn max)  `id: config-a.dashboard.turn_isolation`
- **Surface:** Config | Web dashboard | Desktop app | Core
- **Where:** Config page tab `Display 87` → `dashboard` → labels `TURN ISOLATION` (`dashboard.turn_isolation`, switch, default `false`), `COMPUTE HOST HEARTBEAT SECS` (`dashboard.compute_host_heartbeat_secs`, number, default `15`), `COMPUTE HOST RESPAWN MAX` (`dashboard.compute_host_respawn_max`, number, default `3`).
- **What it does:** Moves agent turns out of the gateway process into one persistent "compute host" subprocess, so a crashing/leaking turn cannot take the dashboard/desktop WS server with it. The other two keys tune that supervisor's liveness heartbeat and how many times it may be respawned.
- **How it works:** `config_defaults.py:1677-1681` ("Runtime reads these through the raw config loader, so `tui_gateway.server` also owns explicit defaults"). Gate: `tui_gateway/server.py:2589` `return bool(isolation_cfg.get("turn_isolation"))`; the supervisor is constructed with `heartbeat_secs=int(isolation_cfg.get("compute_host_heartbeat_secs") or 15)` and `respawn_max=int(isolation_cfg.get("compute_host_respawn_max") or 3)` (`tui_gateway/server.py:2612-2613`). Docstrings: `tui_gateway/host_supervisor.py:4` and `tui_gateway/compute_host.py:5`. The values are echoed back in a status payload with `is_truthy_value(dashboard.get("turn_isolation"), …)` / `_coerce_int_config_value(dashboard.get("compute_host_heartbeat_secs"), …)` / `…("compute_host_respawn_max")` (`tui_gateway/server.py:4457-4467`). When isolation is on, RPC replies carry `"turn_isolation": True` — streaming start (`server.py:2843`), session methods (`methods_session.py:2922,2933`), interrupt (`methods_session.py:3396`), tool reload (`methods_tools.py:134`). The certification harness `scripts/iso-certify.py:34,115-117,588` writes exactly these three keys into a scratch `HERMES_HOME` (`--set dashboard.turn_isolation`).
- **Inputs / options:** boolean; positive integers (seconds; count).
- **Outputs / side effects:** spawns/keeps a compute-host subprocess; adds `turn_isolation: true` to RPC results; a dead host is respawned up to `compute_host_respawn_max` times.
- **Config / env:** `dashboard.turn_isolation`, `dashboard.compute_host_heartbeat_secs`, `dashboard.compute_host_respawn_max`. No env vars.
- **Edge cases / guards:** `or 15` / `or 3` means `0` falls back to the default rather than meaning "never"; respawns beyond the max leave the host down.
- **Rebuild notes:** Process supervisor with a heartbeat watchdog and bounded restarts, gated by one flag. A better version would expose per-turn resource limits and surface the respawn count in the UI.

### Display → Show token analytics  `id: config-a.dashboard.show_token_analytics`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Display 87` → `dashboard` → label `SHOW TOKEN ANALYTICS` (switch, default `false`). Governs the `Analytics` nav item and the token/cost blocks on the `Models` page.
- **What it does:** Re-enables the local token/cost analytics surfaces that ship hidden because the numbers are a local lower-bound estimate, not billing.
- **How it works:** Declared at `config_defaults.py:1682-1697` with a long rationale comment: the estimate only counts successful main-agent responses with usable `response.usage` and silently excludes auxiliary calls (context compression, title generation, vision, session search, web extract, smart approval, MCP routing, plugin LLM access), provider-side retries, fallback attempts, calls whose usage block did not return, and cache writes; on models with heavy auxiliary traffic (named: Kimi K2.6, MiniMax M2.7) the local total can be 10x–100x below the provider bill. There is **no Python reader** — it is consumed only by the SPA: `web/src/App.tsx:412-424` (`setShowTokenAnalytics(dash.show_token_analytics === true)` gates the Analytics nav item), `web/src/pages/AnalyticsPage.tsx:411-424` plus the on-page hint at `AnalyticsPage.tsx:516` naming `dashboard.show_token_analytics: true`, and `web/src/pages/ModelsPage.tsx:1133-1145` with its hint at `ModelsPage.tsx:1308`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** shows/hides the Analytics nav entry, token bars and cost figures.
- **Config / env:** `dashboard.show_token_analytics`. No env var.
- **Edge cases / guards:** strict `=== true` comparison — a truthy string such as `"yes"` does not enable it.
- **Rebuild notes:** Boolean feature flag read client-side from the config payload. A better version would label the numbers "local estimate" inline and reconcile against provider billing APIs where available.

### Display → Dashboard trusted proxies  `id: config-a.dashboard.trusted_proxies`
- **Surface:** Config | Web dashboard | API
- **Where:** Config page tab `Display 87` → `dashboard` → label `TRUSTED PROXIES` (list field, placeholder `comma-separated values`, default `[]`).
- **What it does:** Lists reverse-proxy IPs/CIDRs allowed to set `X-Forwarded-Proto` / `X-Forwarded-For`; everything else's forwarding headers are ignored so clients cannot spoof scheme or source address.
- **How it works:** `config_defaults.py:1698-1703`. Read at `hermes_cli/web_server.py:19504` (`configured = dashboard_config.get("trusted_proxies", [])`); validation rejects a non-list with `"dashboard.trusted_proxies must be a list of IP addresses or CIDR networks; …"` (`web_server.py:19511`), logs `"Ignoring invalid dashboard.trusted_proxies entry %r; expected an IP …"` (`web_server.py:19521`) and `"Ignoring unsafe dashboard.trusted_proxies entry %r; use a bounded IP …"` (`web_server.py:19538`). Loopback stays trusted automatically.
- **Inputs / options:** list of IPv4/IPv6 addresses or bounded CIDR networks.
- **Outputs / side effects:** decides whether forwarded scheme/client-IP are honoured for a request.
- **Config / env:** `dashboard.trusted_proxies`. No env var.
- **Edge cases / guards:** wildcards and `/0` networks are rejected; invalid entries are skipped with a warning rather than failing startup.
- **Rebuild notes:** Parse into `ipaddress` networks once at boot, check `request.client.host` membership before trusting `X-Forwarded-*`. A better version would also support a proxy-depth count and `Forwarded:` RFC 7239 parsing.

### Display → Dashboard WebSocket keepalive + orphan reaping  `id: config-a.dashboard.ws_keepalive`
- **Surface:** Config | Web dashboard | Desktop app
- **Where:** Config page tab `Display 87` → `dashboard` → labels `WS PING INTERVAL` (`dashboard.ws_ping_interval`, number, default `20.0`), `WS PING TIMEOUT` (`dashboard.ws_ping_timeout`, number, default `20.0`), `WS ORPHAN REAP GRACE S` (`dashboard.ws_orphan_reap_grace_s`, number, default `20.0`), `STARTUP ORPHAN SWEEP` (`dashboard.startup_orphan_sweep`, switch, default `true`).
- **What it does:** Tunes WebSocket liveness for the dashboard/desktop server and what happens to sessions whose client disconnected: how often to ping, how long to wait for a pong, the grace window before an orphaned session is interrupted/reaped, and whether to sweep sessions left open by a dead gateway at boot.
- **How it works:** `config_defaults.py:1704-1727`. Ping settings apply to **non-loopback binds only** — loopback always disables the protocol ping so an event-loop stall cannot kill a healthy local connection: `ws_ping_interval=None if _is_loopback else _ws_ping_setting("ws_ping_interval")`, same for the timeout (`hermes_cli/web_server.py:19823-19824`; comment at `19789-19790` cites issue #79635). Orphan grace: `tui_gateway/server.py:186-196` reads `"ws_orphan_reap_grace_s"` (the `HERMES_TUI_WS_ORPHAN_REAP_GRACE_S` env var remains an internal back-compat override; `0` disables the reap and parks forever). Startup sweep: `tui_gateway/server.py:1966-1978` — `"``dashboard.startup_orphan_sweep`` (default on). Fail-open on errors."`; on every gateway boot (stdio TUI and the desktop/dashboard WS sidecar) `tui`/`desktop`/`subagent` rows whose start time *and* newest message are both older than the session TTL (`HERMES_TUI_SESSION_TTL_S`, default 6h) are closed with `end_reason='startup_orphan_reap'` (`server.py:2183`). Messaging-gateway sessions (telegram, discord, …) are never swept, live in-memory sessions are excluded, and swept sessions stay resumable.
- **Inputs / options:** floats (seconds) ×3; boolean ×1.
- **Outputs / side effects:** WebSocket ping frames; interrupted/ended sessions; DB rows gain `ended_at` and `end_reason='startup_orphan_reap'`.
- **Config / env:** `dashboard.ws_ping_interval`, `dashboard.ws_ping_timeout`, `dashboard.ws_orphan_reap_grace_s` (env `HERMES_TUI_WS_ORPHAN_REAP_GRACE_S`), `dashboard.startup_orphan_sweep` (TTL from `HERMES_TUI_SESSION_TTL_S`).
- **Edge cases / guards:** ping keys are ignored on loopback; the in-process grace timer cannot survive a gateway restart, which is precisely why the startup sweep exists; sweep failures fail open (nothing is closed).
- **Rebuild notes:** Ping/pong keepalive with a disconnect grace timer plus a boot-time reconciliation pass over "active" rows. A better version would record the reap decision per row with the evidence (last message time, TTL) for auditability.

### Display → Dashboard OAuth gate (client id / portal URL)  `id: config-a.dashboard.oauth`
- **Surface:** Config | Web dashboard | Provider
- **Where:** Config page tab `Display 87` → `dashboard` → sub-object fields `CLIENT ID` (`dashboard.oauth.client_id`, string, default `""`) and `PORTAL URL` (`dashboard.oauth.portal_url`, string, default `""`).
- **What it does:** Configures the bundled Nous Portal OAuth provider that gates the dashboard when it is bound with `--host` and not `--insecure`.
- **How it works:** `config_defaults.py:1728-1746`. Read by `plugins/dashboard_auth/nous/__init__.py` — precedence documented at `:578` (env `HERMES_DASHBOARD_OAUTH_CLIENT_ID` first, then `dashboard.oauth.client_id` in config.yaml) and `:593` for `portal_url` (`_load_config_oauth_section().get("portal_url", "")`, `:600`); when both are empty the plugin registers no provider and logs `"dashboard.oauth.client_id in config.yaml is empty)…"` (`:636`) / `"as an env var or under dashboard.oauth.client_id in …"` (`:640`). `portal_url` blank falls back to the plugin default `https://portal.nousresearch.com`. Prefix resolution mirrors the same precedence (`hermes_cli/dashboard_auth/prefix.py:209`). The env-override path is what Fly.io platform-secret injection uses to push the per-deploy client id at provisioning time.
- **Inputs / options:** `client_id` — the `agent:{instance_id}` value Portal provisions; `portal_url` — an https base URL.
- **Outputs / side effects:** registers (or does not register) the OAuth password/identity provider; determines the OAuth `redirect_uri` base.
- **Config / env:** `dashboard.oauth.client_id` (env `HERMES_DASHBOARD_OAUTH_CLIENT_ID`), `dashboard.oauth.portal_url` (env `HERMES_DASHBOARD_PORTAL_URL`). Non-empty env wins.
- **Edge cases / guards:** empty `client_id` = plugin no-op (no provider registered); loopback / `--insecure` deploys are unaffected.
- **Rebuild notes:** OIDC client config with env-over-file precedence and a default issuer. A better version would auto-discover the issuer's metadata document and validate the redirect URI at startup.

### Display → Dashboard basic auth (username / password hash / password)  `id: config-a.dashboard.basic_auth.credentials`
- **Surface:** Config | Web dashboard | Provider
- **Where:** Config page tab `Display 87` → `dashboard` → `USERNAME` (`dashboard.basic_auth.username`, string, `""`), `PASSWORD HASH` (`dashboard.basic_auth.password_hash`, string, `""`), `PASSWORD` (`dashboard.basic_auth.password`, string, `""`).
- **What it does:** Turns on the bundled "just put a password on my dashboard" provider — a self-hosted username/password gate that needs no OAuth IdP.
- **How it works:** `config_defaults.py:1747-1782`. The `dashboard_auth/basic` plugin registers a password provider only when `username` plus either `password_hash` (preferred, no plaintext at rest) or `password` (plaintext, hashed in memory at load) are set: `plugins/dashboard_auth/basic/__init__.py:408` reads `("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", section, "username")`, `:411` `(… "_PASSWORD_HASH", section, "password_hash")`; refusal messages at `:422` (`"dashboard.basic_auth.username is not set (and …"`) and `:433` (`"dashboard.basic_auth.username is set but neither password_hash …"`), plus the production advice `"For production, precompute dashboard.basic_auth.password_hash "` (`:464`). The server-side hint in the bind guard reads `"  • Password: set dashboard.basic_auth.username + "` (`hermes_cli/web_server.py:19695`) and the readiness check is `_ba.get("password_hash") or _ba.get("password")` (`web_server.py:19720`). `hermes_cli/main.py:11854` writes `basic["password_hash"] = password_hash` when the CLI provisions one. Hash format is scrypt (`scrypt$…`); compute one with `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"`.
- **Inputs / options:** three strings.
- **Outputs / side effects:** a login form gate on the dashboard; credentials persisted in `config.yaml` (hash strongly preferred).
- **Config / env:** `dashboard.basic_auth.username` (env `HERMES_DASHBOARD_BASIC_AUTH_USERNAME`), `.password_hash` (env `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`), `.password` (env `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`); non-empty env wins.
- **Edge cases / guards:** empty `username` keeps the plugin a complete no-op; plaintext `password` is hashed in memory but still sits in the YAML file.
- **Rebuild notes:** scrypt-hashed single-user credential + a session cookie. A better version would support multiple users, rate-limit login attempts and never accept a plaintext password key at all.

### Display → Dashboard basic-auth session signing (secret / TTL)  `id: config-a.dashboard.basic_auth.session`
- **Surface:** Config | Web dashboard | Provider
- **Where:** Config page tab `Display 87` → `dashboard` → `SECRET` (`dashboard.basic_auth.secret`, string, `""`), `SESSION TTL SECONDS` (`dashboard.basic_auth.session_ttl_seconds`, number, `0`).
- **What it does:** Sets the HMAC key used to sign the stateless session tokens the basic-auth provider mints, and how long those tokens live.
- **How it works:** `config_defaults.py:1770-1781`. When `secret` is empty a random per-process key is generated — fine for a single process, but sessions then do not survive a restart or span multiple workers; set an explicit 32+ random bytes (base64/hex/raw) for stable multi-worker sessions. TTL read at `plugins/dashboard_auth/basic/__init__.py:417` (`"HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS", section, "session_ttl_seconds"`); `0` means "plugin default (12h)".
- **Inputs / options:** free string (key material); integer seconds (`0` = 12 hours).
- **Outputs / side effects:** signed session tokens accepted/rejected across restarts and workers.
- **Config / env:** `dashboard.basic_auth.secret` (env `HERMES_DASHBOARD_BASIC_AUTH_SECRET`), `dashboard.basic_auth.session_ttl_seconds` (env `HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS`).
- **Edge cases / guards:** rotating the secret invalidates every outstanding session; storing it in `config.yaml` puts a credential in a non-secret file (the project's own ".env is for secrets" rule argues for the env var).
- **Rebuild notes:** HMAC-signed stateless token with an expiry claim. A better version would keep a key ring so a rotation does not log everybody out at once.

### Display → Dashboard drain auth (scope / minimum secret length)  `id: config-a.dashboard.drain_auth`
- **Surface:** Config | Web dashboard | API | Provider
- **Where:** Config page tab `Display 87` → `dashboard` → `SCOPE` (`dashboard.drain_auth.scope`, string, default `drain`), `MIN SECRET CHARS` (`dashboard.drain_auth.min_secret_chars`, number, default `43`).
- **What it does:** Behaviour knobs for the bundled `dashboard_auth/drain` plugin — the non-interactive service-credential lane used to drain an agent before shutdown. `scope` is the capability label stamped on the verified principal; `min_secret_chars` is the entropy bar the presented secret must clear.
- **How it works:** `config_defaults.py:1783-1798`. The secret itself is deliberately **not** configured here — it is provisioned by nous-account-service at deploy time via the `HERMES_DASHBOARD_DRAIN_SECRET` env var. The plugin is a no-op unless that env var is set to a ≥256-bit secret; a weak secret is rejected at registration (fail-closed) and the drain endpoint stays disabled. Reader: `plugins/dashboard_auth/drain/__init__.py:253` `min_chars = int(section.get("min_secret_chars", _DEFAULT_MIN_SECRET_CHARS))`. `43` url-safe-base64 characters ≈ 256 bits.
- **Inputs / options:** free string scope label; integer character count.
- **Outputs / side effects:** enables/disables the drain endpoint; attaches the scope to the authenticated principal.
- **Config / env:** `dashboard.drain_auth.scope`, `dashboard.drain_auth.min_secret_chars`; secret via `HERMES_DASHBOARD_DRAIN_SECRET`.
- **Edge cases / guards:** lowering `min_secret_chars` weakens a security control; without the env secret the whole lane stays off regardless of these values.
- **Rebuild notes:** Bearer-token auth with a length/entropy floor checked at registration. A better version would require a signed, audience-scoped JWT rather than a shared bearer string.

### Display → Dashboard public URL  `id: config-a.dashboard.public_url`
- **Surface:** Config | Web dashboard
- **Where:** Config page tab `Display 87` → `dashboard` → label `PUBLIC URL` (`dashboard.public_url`, string, default `""`).
- **What it does:** Declares the dashboard's complete public address (scheme + host + optional path prefix, e.g. `https://example.com/hermes`) for deployments behind reverse proxies that do not forward `X-Forwarded-*` reliably.
- **How it works:** `config_defaults.py:1799-1812`. When set it is the sole authority for building the OAuth `redirect_uri`; its exact hostname is also trusted by the HTTP Host / WebSocket Origin guards (`hermes_cli/web_server.py:777` "Return the exact hostname declared by ``dashboard.public_url``") and, when non-loopback, it **engages the ticket-only auth gate even if the backend binds to loopback** (`web_server.py:827,846`). With it set, `X-Forwarded-Prefix` is IGNORED on the OAuth path (the operator has declared the URL; stacking would double-prefix). Startup messaging: `web_server.py:19607-19703` — the desktop-owned loopback backend note (`19614`), the "on loopback the ONLY trigger is dashboard.public_url" comment (`19660`), the `f"dashboard.public_url is set to "` error (`19675`), the remediation `"proxy), remove dashboard.public_url from config.yaml "` (`19682`), and `"local-only use, bind 127.0.0.1 and leave dashboard.public_url "` (`19703`). `hermes_cli/main.py:11746,11783` mention it in the bind hardening path. Prefix module: `hermes_cli/dashboard_auth/prefix.py:10`.
- **Inputs / options:** an absolute `http(s)://host[/prefix]` URL.
- **Outputs / side effects:** changes the OAuth redirect target, the accepted Host/Origin, and whether the auth gate engages.
- **Config / env:** `dashboard.public_url` (env `HERMES_DASHBOARD_PUBLIC_URL`).
- **Edge cases / guards:** validation rejects values without an `http(s)://` scheme or without a host and any string containing quote / angle-bracket / whitespace / control characters; a malformed value silently falls through to request reconstruction rather than breaking login.
- **Rebuild notes:** One canonical external-origin string that overrides header reconstruction. A better version would surface the effective reconstructed URL in the health endpoint so operators can see what the server believes it is.

### Display → Human delay (mode / min ms / max ms)  `id: config-a.human_delay`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Display 87` → sub-section divider `human delay` → `MODE` (`human_delay.mode`, select, description `Simulated typing delay mode`, default `off`), `MIN MS` (`human_delay.min_ms`, number, default `800`), `MAX MS` (`human_delay.max_ms`, number, default `2500`).
- **What it does:** Intended to pace gateway replies like a human typing — a random sleep before/between outgoing chat messages.
- **How it works:** Keys declared at `config_defaults.py:2028-2032`; select override at `hermes_cli/web_server.py:1389-1393`; category merged into `display` at `web_server.py:1457`. **The implementation reads environment variables, not these keys**: `gateway/platforms/base.py:6462-6487` `_get_human_delay()` reads `HERMES_HUMAN_DELAY_MODE` (`"off"` default | `"natural"` | `"custom"`), `HERMES_HUMAN_DELAY_MIN_MS` (default 800) and `HERMES_HUMAN_DELAY_MAX_MS` (default 2500), returning `random.uniform(min/1000, max/1000)`; `natural` hardcodes 800–2500 and `custom` uses the two env vars, tolerating malformed values by falling back to the defaults. The delay is applied when sending: `base.py:4608,4625-4626` (`await asyncio.sleep(human_delay)`) and `base.py:6887,6897,6939,6951-6952,6994-6995`. Signal explicitly ignores it (`gateway/platforms/signal.py:1306-1313`). A repo-wide grep finds no bridge from `human_delay.*` to those env vars, and the schema's option list (`off`/`typing`/`fixed`) does not match the implementation's vocabulary (`off`/`natural`/`custom`) — so in v2026.8.31 editing these three fields has no runtime effect. `hermes_cli/tips.py:313` still advertises them ("human_delay.mode in config simulates human typing speed — configurable min_ms/max_ms range."). The OpenClaw migration script maps `humanDelay.minMs`/`maxMs` into these keys (`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py:2490,2492`).
- **Inputs / options:** `mode` select — `off`, `typing`, `fixed`; `min_ms`, `max_ms` integers (milliseconds). Env equivalents: `off`, `natural`, `custom`.
- **Outputs / side effects:** (via env) an `asyncio.sleep` before each outgoing gateway message.
- **Config / env:** `human_delay.mode`, `human_delay.min_ms`, `human_delay.max_ms`; env `HERMES_HUMAN_DELAY_MODE`, `HERMES_HUMAN_DELAY_MIN_MS`, `HERMES_HUMAN_DELAY_MAX_MS` (documented in `.env.example:435-437` and `website/docs/reference/environment-variables.md:810-812`).
- **Edge cases / guards:** config/env vocabulary mismatch (see above — recorded under Unresolved); Signal ignores the delay entirely; the delay lengthens every reply, including error notices.
- **Rebuild notes:** Sample a uniform delay in `[min,max]` and sleep before send. A better version would read one source of truth (config, with env override), scale the delay by message length, and never delay error/first-token output.

## Delegation (15 fields)

The `Delegation` tab holds exactly the 15 scalar leaves of the `delegation:` block. The dict-valued `delegation.request_overrides` (`config_defaults.py:2103-2112`) is *not* a schema field — per-child API kwargs such as `service_tier` and an `extra_body` sub-dict (e.g. `{"extra_body": {"provider": {"sort": "throughput"}}}` to route OpenRouter children to the fastest provider) are edited in the YAML view only; they merge OVER runtime/parent-derived overrides on all three resolution branches, with `extra_body` deep-merged one level.

### Delegation → Model / Provider  `id: config-a.delegation.model`
- **Surface:** Config | Tool | CLI
- **Where:** Config page tab `Delegation 15` → labels `MODEL` (`delegation.model`, string, default `""`) and `PROVIDER` (`delegation.provider`, string, default `""`). Also reported by `hermes config get delegation.model`.
- **What it does:** Overrides the provider:model that `delegate_task` subagents run on, so children can use a cheaper/faster model than the parent. Empty = inherit the parent's model / provider + credentials.
- **How it works:** `config_defaults.py:2086-2091`. Resolution runs through the same runtime provider machinery as CLI/gateway startup, so every configured provider (OpenRouter, Nous, Z.ai, Kimi, …) works. `tools/delegate_tool.py:1942` — "When override_provider is set (e.g. delegation.provider: minimax-cn)…"; `:1983,:1998` an explicit pin means the parent-derived constraints are not applied; `:3914` "When delegation.provider is configured, this resolves the full credential…"; `:4702` the same for the fallback branch; the user-facing hint is `"delegation.provider / delegation.model in config.yaml."` (`:5027`). The review engine honours the same pins (`agent/review_engine.py:17`). `hermes_cli/xai_retirement.py:68,104` audits `delegation.model` when retiring xAI models. `tools/process_registry.py:3058` prints `hermes config get delegation.model` in guidance. Tip text: `hermes_cli/tips.py:310`.
- **Inputs / options:** free strings — a model id (e.g. `google/gemini-3-flash-preview`) and a provider name (e.g. `openrouter`).
- **Outputs / side effects:** every subagent API call goes to the named model/provider; parent stays on its own model.
- **Config / env:** `delegation.model`, `delegation.provider`. No dedicated env vars (provider credentials come from the normal provider env vars).
- **Edge cases / guards:** setting `provider` without `model` inherits the parent model on that provider; an unresolvable provider raises with the hint at `delegate_tool.py:4869`.
- **Rebuild notes:** A second model-resolution context keyed "delegation", falling back to the parent's. A better version would allow per-role (orchestrator vs leaf) model pins and per-task cost budgets.

### Delegation → Base URL / API key / API mode  `id: config-a.delegation.base_url`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → `BASE URL` (`delegation.base_url`, string, `""`), `API KEY` (`delegation.api_key`, string, `""`), `API MODE` (`delegation.api_mode`, string, `""`).
- **What it does:** Points subagents at a direct OpenAI-compatible endpoint instead of a named provider, with its own key and wire protocol.
- **How it works:** `config_defaults.py:2092-2098` (`api_key` "falls back to OPENAI_API_KEY"; mirrored in `cli.py:542`). `tools/delegate_tool.py:4694-4695` — "If ``delegation.base_url`` is configured, subagents use that direct OpenAI-compatible endpoint. ``delegation.api_key`` overrides the key"; when `api_key` is unset the resolver returns `None` so `_build_child_agent` reuses the parent key rather than forcing duplication (`:4759-4764`). Unregistered endpoints are a special case (`:4583,:4607`). `api_mode` values: `chat_completions`, `codex_responses`, `anthropic_messages`; empty = auto-detect from the URL (e.g. an `/anthropic` suffix ⇒ `anthropic_messages`) — "Explicit delegation.api_mode in config always wins" (`:4791`). Runtime-resolution failure logs `"delegation.base_url: runtime resolution for provider '%s' …"` (`:4818`) and the terminal error suggests `"or set delegation.base_url/delegation.api_key for a direct endpoint. "` (`:4869`).
- **Inputs / options:** URL string; key string; `api_mode` ∈ {`chat_completions`, `codex_responses`, `anthropic_messages`, `""`}.
- **Outputs / side effects:** subagent HTTP calls go to the given endpoint with the given protocol framing.
- **Config / env:** `delegation.base_url`, `delegation.api_key` (falls back to `OPENAI_API_KEY`), `delegation.api_mode`.
- **Edge cases / guards:** a non-standard endpoint the URL heuristic cannot classify needs `api_mode` set explicitly, otherwise requests are framed wrongly; the key sits in plaintext in `config.yaml`.
- **Rebuild notes:** Endpoint tuple (url, key, protocol) with URL-based protocol sniffing. A better version would probe `/models` once and cache the detected protocol, and read the key from the secret store.

### Delegation → Inherit MCP toolsets  `id: config-a.delegation.inherit_mcp_toolsets`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `INHERIT MCP TOOLSETS` (switch, default `true`).
- **What it does:** When `delegate_task` narrows a child's toolsets explicitly (e.g. `toolsets=["web","browser"]`), still keep any MCP toolsets the parent already had enabled.
- **How it works:** `config_defaults.py:2113-2119`. Reader: `tools/delegate_tool.py:1087-1090` `_get_inherit_mcp_toolsets()` → `is_truthy_value(cfg.get("inherit_mcp_toolsets"), default=True)`; `_is_mcp_toolset_name()` (`:1092+`) recognises canonical MCP toolsets and their registered aliases. `false` = strict intersection (narrowing removes MCP tools too).
- **Inputs / options:** boolean.
- **Outputs / side effects:** child agent tool surface (and therefore its system-prompt tool schemas).
- **Config / env:** `delegation.inherit_mcp_toolsets`.
- **Edge cases / guards:** on by default so narrowing expresses "I want these extras" rather than silently stripping MCP tools.
- **Rebuild notes:** Union the requested toolsets with the parent's MCP toolsets unless strict mode. A better version would let the caller say `strict=true` per call instead of only globally.

### Delegation → Max iterations  `id: config-a.delegation.max_iterations`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `MAX ITERATIONS` (number, default `250`).
- **What it does:** Per-subagent tool-call/iteration budget — each child gets its own budget, independent of the parent's `agent.max_iterations`.
- **How it works:** `config_defaults.py:2120-2121`. `agent/iteration_budget.py:6,23,25` documents the split; `tools/delegate_tool.py:1861` and `:3908` (`"using delegation.max_iterations=%s from config"`). A config migration raised the default from 50 to 250 and prints `"  ✓ Raised delegation.max_iterations from 50 to 250 — subagents "` … `"finishes instead of truncating. Set delegation.max_iterations "` (`hermes_cli/config_migrations.py:740-763`), recording `"delegation.max_iterations=250 (was: 50)"` in `results["config_added"]` (`:758`).
- **Inputs / options:** positive integer.
- **Outputs / side effects:** a child that exhausts the budget returns a truncated result instead of continuing.
- **Config / env:** `delegation.max_iterations`.
- **Edge cases / guards:** total work is `max_iterations × number of children`, so raising it multiplies cost.
- **Rebuild notes:** Per-child loop counter checked before each API call. A better version would budget tokens/cost rather than iteration count.

### Delegation → Max summary chars  `id: config-a.delegation.max_summary_chars`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `MAX SUMMARY CHARS` (number, default `24000`).
- **What it does:** Hard per-summary character ceiling on what a subagent returns into the parent's context, layered on top of a dynamic headroom budget. `0` disables the hard ceiling (the dynamic budget still applies).
- **How it works:** `config_defaults.py:2122-2140`. Subagent summaries return verbatim, so a batch fan-out of N children can blow the parent window and trigger a compression/429 death spiral; `delegate_task` sizes each summary against the parent's *remaining* context headroom split across the batch. When it must trim, the full text is spilled to `~/.hermes/cache/delegation/` (mounted into remote backends) and the in-context summary becomes a head+tail window plus a footer with the exact `read_file` offset to page the omitted middle — the same convention `web_extract` uses for large pages, so nothing is lost. Reader: `tools/delegate_tool.py:2520` ("the static ``delegation.max_summary_chars`` ceiling (0 = disabled)") and `:2536` `static_ceiling = int(cfg.get("max_summary_chars", DEFAULT_MAX_SUMMARY_CHARS))`.
- **Inputs / options:** non-negative integer (characters).
- **Outputs / side effects:** truncated summaries plus spill files under `~/.hermes/cache/delegation/`.
- **Config / env:** `delegation.max_summary_chars`.
- **Edge cases / guards:** belt-and-suspenders for models that ignore "be concise"; the dynamic budget can bite first.
- **Rebuild notes:** min(dynamic headroom share, static ceiling), spill + pointer on overflow. A better version would summarise the overflow instead of windowing it.

### Delegation → Child timeout seconds  `id: config-a.delegation.child_timeout_seconds`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `CHILD TIMEOUT SECONDS` (number, default `0`).
- **What it does:** Optional wall-clock cap per child agent. `0` (default) = no timeout — children fail only from real errors (API, tools, iteration budget), never a delegation stopwatch.
- **How it works:** `config_defaults.py:2142-2147`. `tools/delegate_tool.py:989-1013` `"""Read delegation.child_timeout_seconds from config."""`, `:1003` "Set ``delegation.child_timeout_seconds`` to a positive number to opt back", `:1007` `val = cfg.get("child_timeout_seconds")`, and the validation warning `"delegation.child_timeout_seconds=%r is not a valid number; "` (`:1013`). Floor 30s. Comments at `:1166` and `:1181` note it stays an optional hard cap on top of the normal failure paths.
- **Inputs / options:** integer/float seconds; `0` = off; positive values floored at 30.
- **Outputs / side effects:** a child exceeding the cap is aborted and reports a timeout.
- **Config / env:** `delegation.child_timeout_seconds`.
- **Edge cases / guards:** values between 1 and 29 are raised to 30; non-numeric values log a warning and fall back to off.
- **Rebuild notes:** Deadline passed into the child's run loop. A better version would checkpoint partial work before aborting so the parent still gets what the child found.

### Delegation → Reasoning effort  `id: config-a.delegation.reasoning_effort`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `REASONING EFFORT`, description `Reasoning effort for delegated subagents` (select, default `""`).
- **What it does:** Independently sets thinking depth for subagents, so children can think less (or more) than the parent.
- **How it works:** Override with the option list at `hermes_cli/web_server.py:1404-1408`. Declared at `config_defaults.py:2148-2149` where the comment lists `"ultra", "max", "xhigh", "high", "medium", "low", "minimal", "none"` (empty = inherit). Unknown values log `"Unknown delegation.reasoning_effort '%s', inheriting parent level"` (`tools/delegate_tool.py:1972`). The parent's own level comes from `agent.reasoning_effort` (`hermes_constants.py:1515`). Tip: `hermes_cli/tips.py:311`.
- **Inputs / options:** the eight select values rendered by the dashboard — `` (empty, shown as `(none)`), `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. The config comment additionally names `none` as accepted YAML.
- **Outputs / side effects:** the reasoning parameter sent on each child API call.
- **Config / env:** `delegation.reasoning_effort`.
- **Edge cases / guards:** the dashboard's option list and the config comment differ (`none` is absent from the dropdown); providers that do not support reasoning ignore the value.
- **Rebuild notes:** Map an effort label to per-provider reasoning params, defaulting to the parent's. A better version would auto-pick the effort from the delegated task's complexity.

### Delegation → Max concurrent children  `id: config-a.delegation.max_concurrent_children`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → label `MAX CONCURRENT CHILDREN` (number, default `10`).
- **What it does:** One unified concurrency cap: max parallel children per batch AND max concurrent background (`background=true`) delegation units. Dispatches beyond the cap fall back to synchronous execution.
- **How it works:** `config_defaults.py:2151-2155`. `tools/delegate_tool.py:903-929` `_get_max_concurrent_children()` reads `cfg.get("max_concurrent_children")` (`:913`), warns once per process above 10 with `"delegation.max_concurrent_children=%d: each child consumes API tokens "` (`:922`, one-shot flag documented at `:124-126`) and rejects garbage with `"delegation.max_concurrent_children=%r is not a valid integer; "` (`:929`). `:965-985` documents that it replaces the deprecated `max_async_children` and emits a one-time deprecation warning (`"delegation.max_concurrent_children now caps background "`, `:982`). `hermes_cli/doctor.py:528` carries the rename pair `("delegation", "max_async_children", "delegation.max_concurrent_children")`; migrations print `f"delegation.max_concurrent_children={old_async_i} "` (`config_migrations.py:615`) and record `"delegation.max_concurrent_children=10 (was: 3)"` (`:789`). Floor of 1, no ceiling.
- **Inputs / options:** integer ≥ 1.
- **Outputs / side effects:** semaphore width for child execution; excess dispatches run synchronously.
- **Config / env:** `delegation.max_concurrent_children` (legacy alias `delegation.max_async_children`, migrated).
- **Edge cases / guards:** each concurrent child multiplies token spend and provider rate-limit pressure; the TUI can stall for seconds when the cap is saturated (`delegate_tool.py:2187`).
- **Rebuild notes:** One semaphore shared by batch and background paths, with graceful degradation to sync. A better version would make the cap adaptive to observed provider 429s.

### Delegation → Max spawn depth / Orchestrator enabled  `id: config-a.delegation.max_spawn_depth`
- **Surface:** Config | Tool
- **Where:** Config page tab `Delegation 15` → `MAX SPAWN DEPTH` (`delegation.max_spawn_depth`, number, default `1`) and `ORCHESTRATOR ENABLED` (`delegation.orchestrator_enabled`, switch, default `true`).
- **What it does:** Controls nested delegation. Depth `1` (default) is flat: the parent spawns children and those children cannot spawn. `2` unlocks orchestrator→leaf, `3+` deeper. The kill switch silently forces `role="orchestrator"` back to `"leaf"` when off.
- **How it works:** `config_defaults.py:2156-2161` ("Floored at 1, no upper ceiling — raise deliberately, each level multiplies API cost"). `tools/delegate_tool.py:1030-1066` `_get_max_spawn_depth()`: depth 0 = parent; `max_spawn_depth = N` means agents at depths `0..N-1` may spawn and depth N is the leaf floor; a missing value returns `MAX_DEPTH`, a non-integer logs `"delegation.max_spawn_depth=%r is not a valid integer; using default %d"`, and values below `_MIN_SPAWN_DEPTH` log `"delegation.max_spawn_depth=%d below floor %d; using %d"`. `_get_orchestrator_enabled()` (`:1069-1082`) accepts real booleans and the YAML strings `true`/`1`/`yes`/`on`, defaulting to `True`. The gate is applied at `:1745-1746` — `orchestrator_ok = _get_orchestrator_enabled() and child_depth < max_spawn`. With depth ≥ 2 the `role="orchestrator"` child keeps the delegation toolset instead of having it stripped by `_strip_blocked_tools`.
- **Inputs / options:** integer ≥ 1; boolean (or the four truthy strings).
- **Outputs / side effects:** whether a child receives the delegation toolset; how deep the agent tree may grow.
- **Config / env:** `delegation.max_spawn_depth`, `delegation.orchestrator_enabled`.
- **Edge cases / guards:** no upper ceiling — an unbounded depth combined with `max_concurrent_children` can fan out exponentially; the kill switch is silent (the orchestrator role is downgraded, not rejected).
- **Rebuild notes:** Depth counter carried on the child context + a per-role toolset policy. A better version would enforce a global live-agent budget across the whole tree rather than only per level.

### Delegation → Subagent auto approve  `id: config-a.delegation.subagent_auto_approve`
- **Surface:** Config | Security
- **Where:** Config page tab `Delegation 15` → label `SUBAGENT AUTO APPROVE` (switch, default `false`).
- **What it does:** Decides how a subagent resolves a dangerous-command approval prompt it can never show to a human: auto-deny (default) or auto-approve "once".
- **How it works:** `config_defaults.py:2162-2172`. The rationale is a deadlock: the parent's prompt_toolkit TUI owns stdin, so a thread-local `input()` from the subagent worker would freeze the parent UI. Subagent threads therefore ALWAYS resolve approvals non-interactively — `false` auto-denies with a `logger.warning` audit line, `true` auto-approves once with a `logger.warning` audit line.
- **Inputs / options:** boolean.
- **Outputs / side effects:** the subagent's dangerous command runs or is denied; either way a warning-level audit line is written to `~/.hermes/logs/agent.log`.
- **Config / env:** `delegation.subagent_auto_approve`.
- **Edge cases / guards:** flip to `true` only for trusted unattended pipelines (cron, batch automation) — it removes human review for everything a child does; the hardline blocklist and `approvals.deny` still apply.
- **Rebuild notes:** Non-interactive approval resolver bound to the child context with a mandatory audit line. A better version would forward the prompt to the parent's approval queue instead of deciding blindly.

### Delegation → Surface child process notifications  `id: config-a.delegation.surface_child_process_notifications`
- **Surface:** Config | Gateway/Telegram | Display
- **Where:** Config page tab `Delegation 15` → label `SURFACE CHILD PROCESS NOTIFICATIONS` (switch, default `false`).
- **What it does:** Restores delivery of background-process notifications (`notify_on_complete`, `watch_pattern`) started by subagents into the parent conversation. Off by default so "npm ci finished" walls do not interrupt chat.
- **How it works:** `config_defaults.py:2173-2182`. Background processes started by subagents carry task ids prefixed `sa-`; children consume their own waits, so anything outliving the child routes to the PARENT conversation, which needs a durable consumer. By default those parent-facing notifications are suppressed — the child's consolidated delegation result is the deliverable. Async-delegation *results* are never suppressed regardless of this key. When on, notifications are delivered with subagent attribution lines.
- **Inputs / options:** boolean.
- **Outputs / side effects:** extra chat/TUI messages in the parent session.
- **Config / env:** `delegation.surface_child_process_notifications`.
- **Edge cases / guards:** interacts with `display.background_process_notifications` (the global switch) — both must allow delivery.
- **Rebuild notes:** Tag notifications with their originating agent and filter on a policy flag. A better version would batch child notifications into one digest attached to the delegation result.

## Memory (7 schema fields; the page renders 6)

The live schema carries 7 `memory.*` fields. `web/src/pages/ConfigPage.tsx:181` deletes `memory.provider` from the form (it is chosen on the Plugins page instead), so the tab button reads `Memory 6`. All 7 are documented here.

### Memory → Memory enabled / User profile enabled  `id: config-a.memory.enabled_flags`
- **Surface:** Config | Core | CLI
- **Where:** Config page tab `Memory 6` → labels `MEMORY ENABLED` (`memory.memory_enabled`, switch, default `true`) and `USER PROFILE ENABLED` (`memory.user_profile_enabled`, switch, default `true`). Documented in `website/docs/user-guide/configuration.md:723-733`.
- **What it does:** Two independent switches for the built-in bounded memory: the curated fact store and the user-profile block, both injected into the system prompt.
- **How it works:** `config_defaults.py:2057-2059`. Store flags are resolved by `get_builtin_memory_store_flags` and read at `tools/memory_tool.py:1202-1203` — `is_truthy_value(section.get("memory_enabled"), default=True)` and `is_truthy_value(section.get("user_profile_enabled"), default=True)`. `agent/agent_init.py:1881-1894` sets `agent._memory_enabled` / `agent._user_profile_enabled` and only constructs the `MemoryStore` (then `load_from_disk()`) when at least one is on; the whole block is wrapped in `except Exception: pass` ("Memory is optional -- don't break agent init"). Setup wizard writes both to `False` together (`hermes_cli/setup.py:3530-3531`); the memory-setup screen reads them at `hermes_cli/memory_setup.py:486-487`.
- **Inputs / options:** boolean ×2.
- **Outputs / side effects:** presence/absence of the memory + profile sections in the system prompt; whether `~/.hermes/memory*` files are loaded/written.
- **Config / env:** `memory.memory_enabled`, `memory.user_profile_enabled`.
- **Edge cases / guards:** to disable memory entirely use `memory_enabled: false`, not the write-approval gate; disabling both skips `MemoryStore` construction so memory tools have nothing to write to.
- **Rebuild notes:** Two booleans gating two prompt sections and one store. A better version would let each be scoped per-project as well as globally.

### Memory → Write approval  `id: config-a.memory.write_approval`
- **Surface:** Config | Security | Gateway/Telegram | CLI
- **Where:** Config page tab `Memory 6` → label `WRITE APPROVAL` (switch, default `false`). Runtime toggle: `/memory approval on|off`. Review queue: `/memory pending`, `/memory approve <id>`, `/memory reject <id>`.
- **What it does:** Requires human approval before any memory write (add/replace/remove) lands — for BOTH foreground agent turns and the background self-improvement review fork.
- **How it works:** `config_defaults.py:2060-2073`. `tools/write_approval.py` is the shared gate: `CONFIG_KEY = "write_approval"` (`:67`), the subsystem enable flag is named in the comment `"enable flag (e.g. ``memory.memory_enabled: false``)"` (`:66`), and the staged-write message is `"Staged for approval (memory.write_approval is on). "` (`:309`). Foreground writes prompt inline (entries are small enough to review in a chat bubble); background-review writes are staged instead of committed because a daemon thread cannot block on a prompt. Slash toggle writes it back: `gateway/slash_commands.py:4013` `user_config.setdefault("memory", {})["write_approval"] = bool(enabled)` (the parallel skills gate is at `:4068`). A config migration maps the old `memory.write_mode: approve` to this boolean (`hermes_cli/config_migrations.py:497-501`). Docs: `website/docs/user-guide/configuration.md:733`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** inline approval prompts; a pending queue reviewable with the `/memory` sub-commands; unapproved writes never reach the store.
- **Config / env:** `memory.write_approval`.
- **Edge cases / guards:** background-review writes can only be staged, never prompted; rejecting leaves the store unchanged.
- **Rebuild notes:** A staging table plus an approval verb, with different UX for interactive vs daemon callers. A better version would show a diff of the memory block before/after and allow inline editing at approval time.

### Memory → Memory char limit / User char limit  `id: config-a.memory.char_limits`
- **Surface:** Config | Core
- **Where:** Config page tab `Memory 6` → `MEMORY CHAR LIMIT` (`memory.memory_char_limit`, number, default `2200`) and `USER CHAR LIMIT` (`memory.user_char_limit`, number, default `1375`).
- **What it does:** Caps how many characters of curated memory and of user profile can be injected into the system prompt (defaults ≈ 800 and ≈ 500 tokens at 2.75 chars/token).
- **How it works:** `config_defaults.py:2074-2075`. Applied when constructing the store: `agent/agent_init.py:1889-1890` (`memory_char_limit=mem_config.get("memory_char_limit", 2200)`, `user_char_limit=mem_config.get("user_char_limit", 1375)`); re-read inside the tool at `tools/memory_tool.py:934-935`, whose docstring at `:917-918` explains that an approval applied without a live agent still honours the user's `memory.memory_char_limit` / `memory.user_char_limit` overrides. `hermes_cli/config.py:3092` notes user-set values such as `memory.user_char_limit: 2200` survive default merging. The migration importer reads the same keys (`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py:891-892`).
- **Inputs / options:** positive integers (characters).
- **Outputs / side effects:** memory writes that would exceed the cap are trimmed/refused; system-prompt size.
- **Config / env:** `memory.memory_char_limit`, `memory.user_char_limit`.
- **Edge cases / guards:** these are character caps, not token caps — the token cost varies by tokenizer and language; raising them enlarges every request's prefix.
- **Rebuild notes:** Two byte budgets enforced at write and at prompt assembly. A better version would budget in tokens using the active model's tokenizer and evict least-recently-useful entries.

### Memory → Nudge interval  `id: config-a.memory.nudge_interval`
- **Surface:** Config | Core
- **Where:** Config page tab `Memory 6` → label `NUDGE INTERVAL` (number, default `10`).
- **What it does:** How often (in turns) the built-in periodic memory review fires — the "should I remember anything from this?" nudge.
- **How it works:** `config_defaults.py:2076-2079`; read once at agent init: `agent/agent_init.py:1885` `agent._memory_nudge_interval = int(mem_config.get("nudge_interval", 10))`. The comment notes external providers with automatic turn/session extraction can set this to `0` and keep the small local store reserved for explicit high-frequency operational facts.
- **Inputs / options:** non-negative integer (turns); `0` disables the periodic review.
- **Outputs / side effects:** an extra prompt/consideration every N turns; possible memory writes.
- **Config / env:** `memory.nudge_interval`.
- **Edge cases / guards:** read at init only — changing it mid-session needs a new agent build.
- **Rebuild notes:** Turn counter modulo N triggering a review step. A better version would trigger on content novelty rather than a fixed cadence.

### Memory → Provider  `id: config-a.memory.provider`
- **Surface:** Config | Plugin | Web dashboard
- **Where:** Present in `GET /api/config/schema` as `memory.provider` (select, description `Memory provider plugin`, default `""`) but **deleted from the Config form** by `web/src/pages/ConfigPage.tsx:181`; the user picks a provider on the Plugins page or with `hermes config set memory.provider <name>` (the Honcho CLI prints exactly that: `plugins/memory/honcho/cli.py:1014`).
- **What it does:** Activates one external memory provider plugin alongside the built-in store. Empty = built-in only.
- **How it works:** Declared at `config_defaults.py:2080-2084` (comment lists `"openviking", "mem0", "hindsight", "holographic", "retaindb", "byterover"`; "Only ONE external provider is allowed at a time"). The schema's options are computed live per request by `_memory_provider_options()` (`hermes_cli/web_server.py:1241-1259`): a **directory scan only** (no provider imports, safe at import time), `""` always first, falling back to `["honcho"]` if discovery fails, then de-duplicated preserving order; the literal `builtin` alias is deliberately not offered because `_normalize_memory_provider_name` maps legacy `builtin`/`built-in`/`none` back to `""` (#49513). Activation: `agent/agent_init.py:1899-1905` reads `mem_config.get("provider", "")` to select the plugin; the plugin package documents the key at `plugins/memory/__init__.py:23,254,686`; multi-provider misuse raises `"allowed at a time. Configure which one via memory.provider "` (`agent/memory_manager.py:490`). Plugin installers write the key themselves — `plugins/memory/openviking/__init__.py:2023` (`config["memory"]["provider"] = "openviking"`), `plugins/memory/honcho/cli.py:1009`. Byterover additionally reads `memory.<provider>` and `memory.provider_config` (`plugins/memory/byterover/__init__.py:68`).
- **Inputs / options:** the live install's discovered provider names — on this checkout: `` (built-in only), `byterover`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory`.
- **Outputs / side effects:** instantiates `agent._memory_manager` with that plugin; memory reads/writes route through it.
- **Config / env:** `memory.provider` plus each plugin's own `memory.<name>.*` block and API-key env vars.
- **Edge cases / guards:** a plugin named here but not installed is silently dropped (`agent/agent_init.py:75`); only one external provider may be active.
- **Rebuild notes:** Plugin registry keyed by a single provider name, discovered by directory scan. A better version would allow layered providers (a fast local cache plus a remote store) with an explicit merge policy.

## Compression (32 fields)

All 32 keys live under `compression:` so the tab shows no sub-section dividers. The dict-valued `compression.model_thresholds` (`config_defaults.py:1027-1037`) is not a schema field — per-model threshold overrides are substring-matched against the model name (longest match wins) and edited in the YAML view. Docs reference: `website/docs/user-guide/configuration.md:861-975`. Editing `model.context_length` or any `compression.*` key on a running gateway takes effect on the **next message** — the cached-agent signature includes these keys (`gateway/run.py:28099-28118` lists the watched tuples), no restart or `/reset` needed.

### Compression → Enabled  `id: config-a.compression.enabled`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → label `ENABLED` (switch, default `true`).
- **What it does:** Master switch for automatic context compaction. Off means the conversation is never auto-compacted; you must run `/compact` (or `/compress`) yourself.
- **How it works:** `config_defaults.py:826`. It disables ALL automatic compaction including the native/server-side paths (`agent/native_compaction.py:190`) and the Codex responses adapter kill switch (`agent/codex_responses_adapter.py:542`). User-facing strings: `run_agent.py:1098,1109` (`"(compression.enabled: false). Use /compact to compress history or "`), `acp_adapter/server.py:2458` (`"Auto-compaction is disabled (compression.enabled: false); "`), and the conversation loop's two notices at `agent/conversation_loop.py:5425,5461,5476` (`"(compression.enabled: false). Run /compress to compact manually, "`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** long sessions eventually hit provider context-length errors instead of compacting.
- **Config / env:** `compression.enabled`. No env var — "All compression settings live in `config.yaml` (no environment variables)" (`configuration.md:864`).
- **Edge cases / guards:** manual `/compress` still works when disabled; gateway session hygiene's message-count valve is a separate path.
- **Rebuild notes:** One boolean checked before every auto-compaction trigger. A better version would degrade to a cheap deterministic prune rather than doing nothing.

### Compression → Checkpoint required  `id: config-a.compression.checkpoint_required`
- **Surface:** Config | Core | Security
- **Where:** Config page tab `Compression 32` → label `CHECKPOINT REQUIRED` (switch, default `false`).
- **What it does:** Fails closed before any lossy compaction unless an active memory provider confirms checkpoint-API compatibility and completes the checkpoint first.
- **How it works:** `config_defaults.py:827-830`. Enforcement: `agent/agent_init.py:527-531` raises `"BLOCKED_MISSING_PREREQUISITE: compression.checkpoint_required "` … `"cannot be guaranteed. Disable compression.checkpoint_required "`; `agent/agent_init.py:2283` reads `is_truthy_value(_compression_cfg.get("checkpoint_required"), default=False)`. It also blocks server-side native compaction (`agent/native_compaction.py:163,194` — "server-side compaction is a lossy…") and post-turn micro-compaction (`agent/agent_init.py:2841-2849`). Gateway paths: `gateway/run.py:748` ("``compression.checkpoint_required`` demands it") and `:21181-21192`; the slash surface reads it at `gateway/slash_commands.py:4692`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** compaction is refused (with a `BLOCKED_MISSING_PREREQUISITE` error) when no compatible memory provider can checkpoint.
- **Config / env:** `compression.checkpoint_required`.
- **Edge cases / guards:** turning it on without a checkpoint-capable memory provider effectively disables compaction and the session will hit the context wall.
- **Rebuild notes:** Pre-compaction hook that must return "checkpointed" before the lossy rewrite proceeds. A better version would fall back to a local durable snapshot when no provider supports checkpointing.

### Compression → Progress notices  `id: config-a.compression.progress_notices`
- **Surface:** Config | Gateway/Telegram | Display
- **Where:** Config page tab `Compression 32` → label `PROGRESS NOTICES` (switch, default `false`).
- **What it does:** Opt-in delivery of *routine* compression progress statuses to chat platforms (Telegram, Discord, Slack, …). Default keeps automatic compaction silent-by-design on chat surfaces, with server-side logging only.
- **How it works:** `config_defaults.py:831-839` (issue #52995). `gateway/run.py:513` and `:541` — "Reads ``compression.progress_notices`` from the gateway's raw YAML config"; the parse at `:551` is `str(compression_cfg.get("progress_notices", False)).strip().lower() in {…}`; the opt-in comment at `:1042`. Hot-reload tuple at `gateway/run.py:28099`. When true you see: the "Compacting context…" start notice, preflight/pre-API compression triggers, idle compaction, retry progress ("Compressed 30 → 12 messages, retrying…") and the "Context compaction complete" notice. The gate is scoped to compression statuses only — unrelated operational noise (auxiliary model failures, provider rate-limit chatter) stays suppressed either way.
- **Inputs / options:** boolean (string forms accepted).
- **Outputs / side effects:** extra chat messages during compaction.
- **Config / env:** `compression.progress_notices`.
- **Edge cases / guards:** compression **failure** notices and manual `/compress` feedback are always visible regardless of this setting; takes effect on the next message on a running gateway.
- **Rebuild notes:** Severity/topic filter on the status channel. A better version would coalesce the lifecycle into one editable status message per compaction.

### Compression → Threshold / Threshold tokens  `id: config-a.compression.threshold`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `THRESHOLD` (`compression.threshold`, number, default `0.50`) and `THRESHOLD TOKENS` (`compression.threshold_tokens`, string in the schema because the default is `null`, default `null`).
- **What it does:** When compaction fires. `threshold` is the fraction of the context window that must be used; `threshold_tokens` is an optional absolute token cap — with both set, compression triggers at the **lower** of the two.
- **How it works:** `config_defaults.py:840-848`. Ratio read: `agent/agent_init.py:2107` `compression_threshold = float(_compression_cfg.get("threshold", 0.50))`; default resolution for the TUI at `tui_gateway/server.py:6720`; the aux client documents "global ``compression.threshold`` (default 50%, ~450K)" and the per-model override return contract at `agent/auxiliary_client.py:814,901`. Absolute cap read at `agent/agent_init.py:2274` (`_compression_cfg.get("threshold_tokens")`) and applied in the compressor at `agent/context_compressor.py:2527,3405` ("Apply absolute token cap (compression.threshold_tokens)"), clamped to the model's context length at apply time so an over-large value is safe. Models with context windows below 512K are floored at `0.75` (raise-only) so compaction does not fire with half the window free; set above 0.75 to override the floor. `hermes_cli/setup.py:1782,1861-1871` writes/prints it (`f"Context compression threshold set to {config['compression'].get('threshold', 0.50)}"`); `hermes_cli/config.py:5072` prints `f"  Threshold:    {compression.get('threshold', 0.50) * 100:.0f}%"`. Hot-reload tuples at `gateway/run.py:28102`.
- **Inputs / options:** float in (0,1]; integer tokens or `null`.
- **Outputs / side effects:** the trigger point of every automatic compaction; the arithmetic `threshold × context_length` also defines the post-compression target with `target_ratio`.
- **Config / env:** `compression.threshold`, `compression.threshold_tokens`.
- **Edge cases / guards:** the small-context 0.75 floor is raise-only and also applies on top of `model_thresholds` overrides; the absolute cap survives model switches and fallback activations, which is the point (a 1M→400K switch would otherwise move the absolute trigger).
- **Rebuild notes:** `trigger = min(ratio × window, absolute_cap)` with a small-window floor. A better version would learn the trigger from observed per-model failure points instead of a fixed ratio.

### Compression → Target ratio / Tail mode  `id: config-a.compression.target_ratio`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `TARGET RATIO` (`compression.target_ratio`, number, default `0.20`) and `TAIL MODE` (`compression.tail_mode`, string, default `lean`).
- **What it does:** `target_ratio` is the fraction of the threshold preserved as the recent verbatim tail after a compaction. `tail_mode` picks the retention policy that produces that tail.
- **How it works:** `config_defaults.py:849-863`. `target_ratio` read at `agent/agent_init.py:2153` and defaulted for the TUI at `tui_gateway/server.py:6867`; printed as `f"  Target ratio: {compression.get('target_ratio', 0.20) * 100:.0f}% of threshold preserved"` (`hermes_cli/config.py:5081`). `tail_mode` read at `agent/agent_init.py:2163` (`str(_compression_cfg.get("tail_mode", "lean")).strip().lower()`; comment at `:2155`) and `tui_gateway/server.py:6825-6826`; the compressor branches on it at `agent/context_compressor.py:2539,3047,4794,4983`. Modes (issue #87326): `lean` (default) = a clamped 2.5 %-of-window tail (10K floor / 25K cap) plus chunked digests, a mechanical anchor index, verbatim user messages and `session_search` recovery pointers in the summary — ~3× fewer retained tokens after compaction at the cost of a few extra summarizer calls at the boundary (docs say all from ONE auxiliary summarizer call); `legacy` = the pre-#87326 `0.20 × threshold` verbatim tail (100–240K tokens on big-window or raised-threshold setups). Hot-reload tuples `gateway/run.py:28112-28113`.
- **Inputs / options:** float in (0,1); string `lean` | `legacy`.
- **Outputs / side effects:** how many tokens survive each compaction and what the summary contains.
- **Config / env:** `compression.target_ratio`, `compression.tail_mode`.
- **Edge cases / guards:** `tail_mode` is a plain string field (not a select) so a typo silently falls into the non-`lean` branch; `target_ratio` mainly matters in `legacy` mode.
- **Rebuild notes:** Two policies behind one enum, sharing a token budget computation. A better version would size the tail by semantic boundaries (last complete task) rather than a fixed percentage.

### Compression → Protect last N / Protect first N / Min tail user messages  `id: config-a.compression.protect_last_n`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `PROTECT LAST N` (`compression.protect_last_n`, number, default `20`), `MIN TAIL USER MESSAGES` (`compression.min_tail_user_messages`, number, default `1`), `PROTECT FIRST N` (`compression.protect_first_n`, number, default `3`).
- **What it does:** Pins messages against compaction: the last N messages, the first N non-system messages, and a guaranteed number of *real* (actionable) user turns inside the uncompressed tail.
- **How it works:** `config_defaults.py:864-871` and `:1000-1006`. `protect_last_n` read at `agent/agent_init.py:2154`, defaulted for the TUI at `tui_gateway/server.py:6854-6856`, consulted by the context-switch guard at `hermes_cli/context_switch_guard.py:39`, and printed as `f"  Protect last: {compression.get('protect_last_n', 20)} messages"` (`hermes_cli/config.py:5082`). `min_tail_user_messages` read at `agent/agent_init.py:2170` (comment `:2165`), enforced in `agent/context_compressor.py:6816,6829`, TUI default at `tui_gateway/server.py:6859-6861`, seeded in `cli.py:478`; raising it to e.g. 3 keeps the last 3 real user turns verbatim when bulky tool outputs fill the tail budget. `protect_first_n` read at `agent/agent_init.py:2254` (`max(0, int(_compression_cfg.get("protect_first_n", 3)))`), added to the guard's protected count at `hermes_cli/context_switch_guard.py:38`, printed as `f"  Protect first: {compression.get('protect_first_n', 3)} non-system head messages"` (`hermes_cli/config.py:5083`). The system prompt is always implicitly protected on top of `protect_first_n`. Hot-reload tuples `gateway/run.py:28114,28118`.
- **Inputs / options:** non-negative integers ×3.
- **Outputs / side effects:** which messages survive verbatim through every summarizer pass.
- **Config / env:** `compression.protect_last_n`, `compression.min_tail_user_messages`, `compression.protect_first_n`.
- **Edge cases / guards:** `protect_first_n: 0` pins nothing but the system prompt + rolling summary + tail — the recommended setting for long-running rolling-compaction sessions; large pins reduce how much compaction can actually reclaim.
- **Rebuild notes:** Three index-based pin sets unioned before choosing the middle window to summarise. A better version would pin by relevance (goal statement, active constraints) rather than by position.

### Compression → Max attempts / Abort on summary failure  `id: config-a.compression.max_attempts`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `MAX ATTEMPTS` (`compression.max_attempts`, number, default `3`) and `ABORT ON SUMMARY FAILURE` (`compression.abort_on_summary_failure`, switch, default `false`).
- **What it does:** How many compression retry rounds a turn takes before giving up with "max compression attempts reached", and whether a failed summary aborts the compaction entirely instead of dropping the middle window behind a placeholder.
- **How it works:** `config_defaults.py:872-877` and `:988-999`. `max_attempts` read at `agent/agent_init.py:2197` (`_raw_max_attempts = _compression_cfg.get("max_attempts", 3)`; comment at `:2187`), validated `>= 1` and hard-capped at 10 (`:2216` uses the same parser semantics for the sibling key); the loop consults it at `agent/conversation_loop.py:2043` and the turn context at `agent/turn_context.py:1144,1257` ("``compression.max_attempts`` cap (floor 1) in every case"). Raise it (e.g. 6) for tool-schema-heavy sessions where 3 rounds cannot clear the request estimate. `abort_on_summary_failure` read at `agent/agent_init.py:2257`; the compressor documents it at `agent/context_compressor.py:8031` and emits `"(compression.abort_on_summary_failure=true). "` (`:8118`). With it on, an auto-compression whose aux LLM errored / returned non-JSON / timed out preserves messages unchanged and the session "freezes" at its current size until the user runs `/compress` (which bypasses the failure cooldown) or `/new`.
- **Inputs / options:** integer 1–10; boolean.
- **Outputs / side effects:** repeated summarizer calls; either a placeholder-bearing compaction (default) or a frozen session (abort mode).
- **Config / env:** `compression.max_attempts`, `compression.abort_on_summary_failure`.
- **Edge cases / guards:** values above 10 are clamped; `abort_on_summary_failure` trades silent context loss for a stuck session — pick which failure you prefer.
- **Rebuild notes:** Bounded retry loop with a terminal policy switch. A better version would retry against a different auxiliary model automatically before choosing either failure mode.

### Compression → Proactive prune (tokens / min result chars / min reclaim tokens)  `id: config-a.compression.proactive_prune`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `PROACTIVE PRUNE TOKENS` (`compression.proactive_prune_tokens`, number, default `0`), `PROACTIVE PRUNE MIN RESULT CHARS` (`compression.proactive_prune_min_result_chars`, number, default `8000`), `PROACTIVE PRUNE MIN RECLAIM TOKENS` (`compression.proactive_prune_min_reclaim_tokens`, number, default `4096`).
- **What it does:** Opt-in, deterministic, **no-LLM** prune of old tool-result payloads that runs independently of `threshold`. On large-window models the ~50 % threshold rarely fires, so bulky terminal dumps / file reads / web extracts ride along in history and are re-sent every turn; the prune dedupes identical results, summarizes older oversized ones and truncates large tool-call arguments.
- **How it works:** `config_defaults.py:878-905`. Readers in `agent/agent_init.py`: `:2236` `max(0, _parse_prune_int(_compression_cfg.get("proactive_prune_tokens", 0), 0))`, `:2239` `_compression_cfg.get("proactive_prune_min_result_chars", 8000)`, `:2244` `_compression_cfg.get("proactive_prune_min_reclaim_tokens", 4096)`; TUI defaults at `tui_gateway/server.py:6839-6851`; hot-reload tuples `gateway/run.py:28115-28117`. `min_result_chars` is clamped to `>= 200` so a generated summary cannot itself be re-summarized. `min_reclaim_tokens` gates the commit: a prune only commits when it reclaims at least that many tokens (measured on the pruned output), then waits for a full trigger-sized token runway to regrow before rearming — because each committed prune rewrites already-sent history and breaks the provider prompt-cache prefix, and this keeps those breaks episodic. Recent messages are protected by `protect_last_n`. Full outputs stay recoverable from the session store.
- **Inputs / options:** integer tokens (`0` = off; docs suggest `48000` to enable); integer chars (≥ 200); integer tokens (`0` = no minimum-savings gate).
- **Outputs / side effects:** rewritten history with shortened tool results; a broken prompt-cache prefix on the next request.
- **Config / env:** the three `compression.proactive_prune_*` keys.
- **Edge cases / guards:** built-in `compressor` engine only — other context engines inherit a no-op; runs independently of `compression.threshold` but still respects `protect_last_n`.
- **Rebuild notes:** Deterministic pass over tool-result messages with dedupe/truncate/summarize rules and a commit gate on measured savings. A better version would keep a content-addressed store so a pruned result can be re-inflated on demand instead of only via `read_file`.

### Compression → Micro-compaction (enable / cadence / defrag threshold)  `id: config-a.compression.micro_compact`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `MICRO COMPACT` (`compression.micro_compact`, switch, default `false`), `MICRO COMPACT EVERY N TURNS` (`compression.micro_compact_every_n_turns`, number, default `1`), `MICRO COMPACT DEFRAG THRESHOLD TOKENS` (`compression.micro_compact_defrag_threshold_tokens`, number, default `2000`).
- **What it does:** After each completed turn, folds the oldest un-absorbed exchange into a rolling summary — amortizing compression cost instead of paying it in one batch stall. The cadence key sets how often a pass runs; the defrag key re-summarizes the rolling summary itself once it grows past N tokens.
- **How it works:** `config_defaults.py:906-931`. Readers: `agent/agent_init.py:2306` (`is_truthy_value(_compression_cfg.get("micro_compact"), default=False)`), `:2314` (`_parse_prune_int(_compression_cfg.get("micro_compact_every_n_turns", 1), 1)`, clamped `>= 1`, ignored unless `micro_compact` is true), `:2321` (`micro_compact_defrag_threshold_tokens`, default 2000). The compaction boundary comment is at `agent/context_compressor.py:3462` ("Operators opt in via `compression.micro_compact: true`"). Reporting tool: `scripts/micro_compaction_report.py:87` prints `"It may be disabled (compression.micro_compact), or no session"`. Hot-reload tuples `gateway/run.py:28109-28111`. Default off because a pass rewrites already-sent history and therefore breaks the provider prompt-cache prefix EVERY turn — exactly the per-turn cache break `proactive_prune_min_reclaim_tokens` exists to avoid. See `docs/micro-compaction.md`.
- **Inputs / options:** boolean; integer ≥ 1 (turns); integer tokens.
- **Outputs / side effects:** a rolling summary message maintained in the transcript; one prompt-cache break per pass.
- **Config / env:** the three `compression.micro_compact*` keys.
- **Edge cases / guards:** enable only when you have measured that the amortized stall is worth more than the cached-prefix discount; cadence `5` trades reclaim rate for one-fifth of the breaks.
- **Rebuild notes:** Post-turn hook that folds message[k] into a summary slot and re-summarizes the slot past a size bound. A better version would batch several turns into one pass sized to the provider's cache-block granularity.

### Compression → Hygiene hard message limit  `id: config-a.compression.hygiene_hard_message_limit`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Compression 32` → label `HYGIENE HARD MESSAGE LIMIT` (number, default `5000`).
- **What it does:** Gateway-only, count-based pre-compression safety valve: force a compression when a session exceeds this many messages, regardless of token accounting.
- **How it works:** `config_defaults.py:932`. Read at `gateway/run.py:20887` (`_raw_hard_limit = _comp_cfg.get("hygiene_hard_message_limit")`) with the rationale comment at `:21034`. It exists to break a death spiral: when API calls keep disconnecting on an oversized session the gateway never receives token-usage data, so the token threshold cannot fire, so the transcript keeps growing and disconnects get worse. Message count is always known, so this floor fires on it alone.
- **Inputs / options:** positive integer (messages).
- **Outputs / side effects:** forces a hygiene compression before the next agent turn.
- **Config / env:** `compression.hygiene_hard_message_limit`.
- **Edge cases / guards:** default 5000 is far above a normal session, including 1M-window models doing thousands of short turns (they hit the token threshold long before); raise for unusual platforms, lower to compress more aggressively. Takes effect on the next message on a running gateway.
- **Rebuild notes:** Count-based fallback trigger beside the token-based one. A better version would also track byte size so a few enormous messages trip it too.

### Compression → Hygiene timing (inactivity / total ceiling / turn hold / failure cooldown)  `id: config-a.compression.hygiene_timing`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Compression 32` → `HYGIENE TIMEOUT SECONDS` (`compression.hygiene_timeout_seconds`, number, default `30`), `HYGIENE TOTAL CEILING SECONDS` (`compression.hygiene_total_ceiling_seconds`, number, default `600`), `HYGIENE MAX TURN HOLD SECONDS` (`compression.hygiene_max_turn_hold_seconds`, number, default `10`), `HYGIENE FAILURE COOLDOWN SECONDS` (`compression.hygiene_failure_cooldown_seconds`, number, default `300`).
- **What it does:** Four budgets around the gateway's pre-agent hygiene compression: how long it may be silent, how long it may run at all, how long an arriving user turn is held for it, and how long to skip retrying after it fails.
- **How it works:** `config_defaults.py:933-957`. All four are read in one block in `gateway/run.py`: `:20895` `_raw_timeout = _comp_cfg.get("hygiene_timeout_seconds")`, `:20903` `_raw_ceiling = _comp_cfg.get("hygiene_total_ceiling_seconds")`, `:20916` `_raw_turn_hold = _comp_cfg.get("hygiene_max_turn_hold_seconds")`, `:20924` `_raw_cooldown = _comp_cfg.get("hygiene_failure_cooldown_seconds")`. `hygiene_timeout_seconds` is an **inactivity** budget, not wall clock: the summary call streams, so each arriving token extends the deadline and only a silent/hung call is cut off. `hygiene_total_ceiling_seconds` bounds the total wait even while tokens move, clamped to `>= hygiene_timeout_seconds`. `hygiene_max_turn_hold_seconds` bounds *user-visible* latency once real input is waiting — deliberately well under chat-transport idle timeouts (Telegram ≈ 30 s); on expiry the turn proceeds uncompressed (an availability boundary, not a failure) while the compression worker keeps running detached with its commit fenced (`CompressionCommitFence`) so it cannot overwrite turns appended after the wait was abandoned. `hygiene_failure_cooldown_seconds` is the **first rung** of an escalating per-session ladder — consecutive failures wait 1×, 3×, then 9× this value, capped at one hour; a run that actually shrinks the transcript resets it. Escalation is per-session and process-local (a gateway restart resets the rung while the cooldown deadline itself survives). `/compress`, `/reset` or a healthy later turn can recover the session. Docs: `configuration.md:869-874` region.
- **Inputs / options:** four positive integers (seconds).
- **Outputs / side effects:** warnings to the user, uncompressed turns, skipped hygiene attempts.
- **Config / env:** the four `compression.hygiene_*` keys.
- **Edge cases / guards:** the ceiling is clamped up to the inactivity budget; the turn-hold budget can leave a turn uncompressed even though compression eventually succeeds.
- **Rebuild notes:** Progress-aware watchdog (idle budget + absolute ceiling) plus a separate user-latency budget and an exponential failure backoff. A better version would stream a "still compacting" heartbeat to the transport so the connection never idles out.

### Compression → Context timeout seconds / Context total ceiling seconds  `id: config-a.compression.context_timeout_seconds`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → `CONTEXT TIMEOUT SECONDS` (`compression.context_timeout_seconds`, number, default `120`) and `CONTEXT TOTAL CEILING SECONDS` (`compression.context_total_ceiling_seconds`, number, default `600`).
- **What it does:** The same two-budget pattern for the **in-agent** `compress_context` path (conversation loop, preflight compaction, manual `/compress`): an inactivity budget and an absolute pre-commit ceiling.
- **How it works:** `config_defaults.py:958-987`. Both read in `agent/conversation_compression.py`: `:1112` `raw_idle = cfg.get("context_timeout_seconds")`, `:1120` `raw_ceiling = cfg.get("context_total_ceiling_seconds")`; module docstring at `:32` ("``compression.context_timeout_seconds > 0``), the WHOLE compression pass —"). Streamed summary tokens extend the wait; only a silent worker is cut off. On timeout Hermes retries the summary once against the first entry of `auxiliary.compression.fallback_chain` (using that entry's own `timeout` when declared) — a stalled route never raises, so the auxiliary client's own fallback handling cannot see it; only if that also fails, or no fallback chain exists, does it skip compaction, keep the messages and warn. `0` disables the owned wrapper (callers that already pass a `commit_fence`, e.g. gateway hygiene, never use this path). The ceiling is clamped to `>= context_timeout_seconds` when the idle budget is > 0 and bounds only the **pre-commit** (summary/stream) phase: an already-started SessionDB commit is never abandoned mid-flight; an overrun is logged (WARNING, escalating to ERROR on repeat), surfaced through the user-visible warning channel, and the host keeps waiting in bounded increments.
- **Inputs / options:** two integers (seconds); `context_timeout_seconds: 0` disables the wrapper.
- **Outputs / side effects:** compaction skipped with a warning, or an overrun warning while the commit finishes.
- **Config / env:** `compression.context_timeout_seconds`, `compression.context_total_ceiling_seconds`.
- **Edge cases / guards:** gateway hygiene is not double-wrapped by these; the commit phase is deliberately not abortable (transcript-divergence risk).
- **Rebuild notes:** Same watchdog as hygiene but scoped to the in-agent call, with an explicit non-abortable commit region. A better version would make the commit itself resumable so the ceiling could apply end-to-end.

### Compression → Codex gpt-5.5 autoraise (+ notice)  `id: config-a.compression.codex_gpt55_autoraise`
- **Surface:** Config | Core | Provider
- **Where:** Config page tab `Compression 32` → `CODEX GPT55 AUTORAISE` (`compression.codex_gpt55_autoraise`, switch, default `true`) and `CODEX GPT55 AUTORAISE NOTICE` (`compression.codex_gpt55_autoraise_notice`, switch, default `true`).
- **What it does:** On the ChatGPT Codex OAuth route, raises the compaction trigger for gpt-5.4 / gpt-5.5 / gpt-5.6 to 85 % (instead of the global `threshold`), because Codex hard-caps those families at a 272K window and the default 50 % would compact at ~136K and waste half the usable context. The second key shows/hides the one-time banner announcing that.
- **How it works:** `config_defaults.py:963-982` (historical key name kept for compatibility). Readers: `agent/agent_init.py:2117` (`_compression_cfg.get("codex_gpt55_autoraise", True)`) and `:2120` (`…_notice`, with the display-gate comment at `:3107`); TUI at `tui_gateway/server.py:6742`; the opt-out hint printed to the user is `f"  Opt back out: hermes config set compression.codex_gpt55_autoraise false"` (`agent/agent_init.py:306`); the aux client references the key at `agent/auxiliary_client.py:807`. Hot-reload tuple `gateway/run.py:28103`.
- **Inputs / options:** boolean ×2.
- **Outputs / side effects:** a per-route 0.85 threshold override; a one-time CLI/gateway banner.
- **Config / env:** `compression.codex_gpt55_autoraise`, `compression.codex_gpt55_autoraise_notice`.
- **Edge cases / guards:** only the exact Codex OAuth route is affected — the same models on OpenAI's direct API, OpenRouter and Copilot keep the global threshold; setting the notice key false keeps the autoraise but silences the banner.
- **Rebuild notes:** Route+model-family special case in threshold resolution, plus a one-shot notice ledger. A better version would derive the threshold from the route's advertised usable window instead of hardcoding a family list.

### Compression → Codex app-server auto  `id: config-a.compression.codex_app_server_auto`
- **Surface:** Config | Core | Provider
- **Where:** Config page tab `Compression 32` → label `CODEX APP SERVER AUTO` (string, default `native`).
- **What it does:** Chooses who compacts the thread when Hermes runs against the codex CLI runtime (app-server transport), where the codex agent owns the real thread context and Hermes' summarizer cannot shrink it.
- **How it works:** `config_defaults.py:983-991` (issue #36801). Read + validated at `agent/agent_init.py:2326` (`_compression_cfg.get("codex_app_server_auto", "native") or "native"`) with the warning `"Invalid compression.codex_app_server_auto=%r; using 'native'. "` (`:2330`); the gateway reads it at `gateway/run.py:21125` and documents the mode contract at `:349` ("only ``hermes``…"); the compaction path branches at `agent/conversation_compression.py:3172`; `/compress` semantics under this mode are documented at `gateway/slash_commands.py:4460`. Hot-reload tuple `gateway/run.py:28104`.
- **Inputs / options:** three strings — `native` (codex decides when to compact its own thread; default), `hermes` (Hermes' compression threshold triggers `thread/compact/start`), `off` (never auto-trigger; codex may still compact natively).
- **Outputs / side effects:** whether Hermes issues a `thread/compact/start` RPC to the codex app server.
- **Config / env:** `compression.codex_app_server_auto`.
- **Edge cases / guards:** plain string field (no select) — an invalid value logs a warning and falls back to `native`.
- **Rebuild notes:** Delegate-vs-drive switch for an external runtime's own compaction API. A better version would read the runtime's reported context usage and choose automatically.

### Compression → Codex responses native (+ compact threshold)  `id: config-a.compression.codex_responses_native`
- **Surface:** Config | Core | Provider
- **Where:** Config page tab `Compression 32` → `CODEX RESPONSES NATIVE` (`compression.codex_responses_native`, switch, default `false`) and `CODEX RESPONSES COMPACT THRESHOLD` (`compression.codex_responses_compact_threshold`, string in schema because the default is `null`, default `null`).
- **What it does:** Opts into OpenAI's **server-side** compaction on the Responses API, and optionally pins the absolute input-token count at which the server should compact.
- **How it works:** `config_defaults.py:992-1000`. It engages ONLY for gpt-5.6-family models on `api.openai.com` or the ChatGPT Codex backend; every other route/model is unaffected, and Hermes' local compression stays armed as the fallback. Readers: `agent/agent_init.py:2343` (`_compression_cfg.get("codex_responses_native", False)`) and `:2345` (`_native_threshold_raw = _compression_cfg.get("codex_responses_compact_threshold")`) with the validation warning `"Invalid compression.codex_responses_compact_threshold=%r; "` (`:2356`); mirrored in the TUI at `tui_gateway/server.py:6792` and `:6795` (`"codex_responses_compact_threshold", 200_000`) with the same warning at `:6805`; the native path reads the resolved value at `agent/native_compaction.py:216-217`. Hot-reload tuples `gateway/run.py:28105-28106`. `None` follows the resolved local compression trigger with a safety margin; explicit values only clamp *downward* so the server compacts first.
- **Inputs / options:** boolean; integer input tokens or `null`.
- **Outputs / side effects:** compaction happens server-side (no local summarizer call, no local rewrite) when it engages.
- **Config / env:** `compression.codex_responses_native`, `compression.codex_responses_compact_threshold`.
- **Edge cases / guards:** `compression.checkpoint_required` blocks native compaction (it is a lossy server rewrite); a threshold above the local trigger is ignored (downward-only clamp).
- **Rebuild notes:** Feature flag + optional absolute trigger passed through to the provider's compaction parameter, with local compaction retained as fallback. A better version would report which side actually compacted in the turn summary.

### Compression → In place  `id: config-a.compression.in_place`
- **Surface:** Config | Core
- **Where:** Config page tab `Compression 32` → label `IN PLACE` (switch, default `true`).
- **What it does:** Keeps the session id stable across compaction. `true` rewrites the message list and rebuilds the system prompt without rotating the id; `false` restores the legacy behaviour where each compaction creates a new session linked to the old one.
- **How it works:** `config_defaults.py:1010-1026` (issue #38763; default `True` since commit `2107b86024`). Read at `agent/agent_init.py:2298` (`is_truthy_value(_compression_cfg.get("in_place"), default=True)`; the comment at `:2293` requires the default to match `DEFAULT_CONFIG`). Compaction path at `agent/conversation_compression.py:3249` and `:5193` (`"in_place": in_place` on the emitted event — hooks see the mode via the `in_place` field on `session:compress`). Gateway at `gateway/run.py:7058`; slash surface at `gateway/slash_commands.py:4771`. Rotation-only machinery lives at `agent/prompt_cache_scope.py:3` ("legacy ``compression.in_place: false`` mode") and `agent/transports/codex.py:764`; provider plugins account for the stable id at `plugins/model-providers/openrouter/__init__.py:135` and `plugins/model-providers/nous/__init__.py:56`; the codex runtime forces `{"in_place": False}` in one path (`agent/codex_runtime.py:323`); `hermes_cli/dump.py:248` includes it in dumps.
- **Inputs / options:** boolean.
- **Outputs / side effects:** with `true`, one durable session id for the conversation's whole life — no `parent_session_id` chain, no `name #2` / `#3` renumbering; pre-compaction turns are soft-archived under the same id (`active=0, compacted=1`), still searchable via `session_search` and recoverable, not deleted.
- **Config / env:** `compression.in_place`.
- **Edge cases / guards:** eliminates a named bug cluster (#33618 `/goal` loss, #14238 lost response, #33907 orphans, #45117 search gaps, #42228 null cwd); flipping to `false` reintroduces it.
- **Rebuild notes:** Compaction as an in-row rewrite with a soft-archive flag rather than a new row. A better version would keep a versioned transcript so any compaction can be undone.

### Compression → Idle compact after seconds  `id: config-a.compression.idle_compact_after_seconds`
- **Surface:** Config | Core | Gateway/Telegram
- **Where:** Config page tab `Compression 32` → label `IDLE COMPACT AFTER SECONDS` (number, default `0`).
- **What it does:** Opt-in **time-based** trigger: a session resumed after at least this many seconds of inactivity compacts its accumulated history up front, before the first reply.
- **How it works:** `config_defaults.py:1038-1050`. Read at `agent/agent_init.py:2365` (`max(0, int(_compression_cfg.get("idle_compact_after_seconds", 0)))`) and in the TUI at `tui_gateway/server.py:6813` (`idle_raw = compression.get("idle_compact_after_seconds", 0)`), where it is one of the two "extra" compression keys carried through the settings bridge (`tui_gateway/server.py:6691` — `for extra in ("idle_compact_after_seconds", "tail_mode")`). It complements (does not replace) the size-based `threshold`. Skipped when the context is already at or below the post-compression target (`threshold × target_ratio`), and it honours the same failure-cooldown / anti-thrash / per-session-lock guards as every automatic compaction. Docs example: `idle_compact_after_seconds: 1800` compacts after 30 minutes idle.
- **Inputs / options:** non-negative integer seconds; `0` = disabled.
- **Outputs / side effects:** a compaction (and its summarizer cost) before the first reply of a resumed session.
- **Config / env:** `compression.idle_compact_after_seconds`.
- **Edge cases / guards:** adds latency to the first reply after a long gap; never fires on an already-small context.
- **Rebuild notes:** Compare `now - last_message_at` on resume and trigger the normal compaction path. A better version would compact in the background during the idle period instead of on the user's first message.

## Security (31 fields)

The `Security` tab merges five top-level config blocks (`hermes_cli/web_server.py:1439-1500` `_CATEGORY_MERGE`): `privacy`, `approvals`, `security`, `telemetry` and the three security-relevant `proxy` keys (the other five `proxy.*` keys keep their own `Proxy` tab and belong to a sibling shard). Inside the tab, `ConfigPage.tsx:388-419` draws a divider named after the first path segment whenever it differs from the tab id — so the reader sees `privacy`, `approvals`, `telemetry` and `proxy` dividers, while `security.*` fields have none.

### Security → Privacy → Redact PII  `id: config-a.privacy.redact_pii`
- **Surface:** Config | Gateway/Telegram | Security
- **Where:** Config page tab `Security 31` → divider `privacy` → label `REDACT PII` (switch, default `false`).
- **What it does:** Hashes user IDs and strips phone numbers from the context sent to the LLM.
- **How it works:** `config_defaults.py:1814-1816`. Re-read **per message** by the gateway: `gateway/run.py:20602` ("Read privacy.redact_pii from config (re-read per message)") and `:20619` `_redact_pii = bool((_pcfg.get("privacy") or {}).get("redact_pii", False))`. Included in support dumps as the tuple `("privacy", "redact_pii")` (`hermes_cli/dump.py:252`). Tip text: `hermes_cli/tips.py:119` ("Set privacy.redact_pii: true to hash user IDs and phone numbers before sending to the LLM.").
- **Inputs / options:** boolean.
- **Outputs / side effects:** identifiers in the prompt become hashes; phone numbers disappear.
- **Config / env:** `privacy.redact_pii`. No env var.
- **Edge cases / guards:** it changes what the model sees, so the agent can no longer address a user by their platform id; it does not redact PII the user types into message bodies beyond phone numbers.
- **Rebuild notes:** Pre-send transform over the message list with a stable hash for ids. A better version would use a configurable detector set (emails, addresses, card numbers) and keep a reversible mapping so replies can be re-personalised.

### Security → Approvals → Mode  `id: config-a.approvals.mode`
- **Surface:** Config | Security | CLI | Gateway/Telegram
- **Where:** Config page tab `Security 31` → divider `approvals` → label `MODE`, description `Dangerous command approval mode` (select, default `smart`).
- **What it does:** How dangerous commands are gated: `manual` always asks a human, `smart` asks an LLM guardian first and escalates only when needed, `off` bypasses Hermes approval prompts entirely.
- **How it works:** Select override at `hermes_cli/web_server.py:1378-1382`; declared at `config_defaults.py:2558`. `tools/approval.py:3435-3448` `_get_approval_config()` returns the live `approvals` sub-dict via `load_config_readonly` (callers must not mutate it); `:3450-3463` `_get_approval_mode()` first honours a hosted-room execution policy (`gateway.hosted_room_execution_policy.current_room_execution_policy().approval_mode`) and otherwise `_normalize_approval_mode(_get_approval_config().get("mode", "manual"))` — note the in-code fallback is `manual` while `DEFAULT_CONFIG` seeds `smart`. `off` participates in the three-source bypass check `is_approval_bypass_active_for_session()` (`:3466-3484`): process-scoped `--yolo` / `HERMES_YOLO_MODE` (frozen at import time so a mid-process skill cannot flip it — a prompt-injection escalation path), the session-scoped gateway `/yolo` toggle, and `approvals.mode: off`. Used at `tools/approval.py:4780,5476`; the Codex runtime honours it at `agent/codex_runtime.py:736` and the app-server session at `agent/transports/codex_app_server_session.py:1064`; the TUI resolves its own effective mode at `tui_gateway/server.py:5842`; `utils.py:702` notes `approvals.mode: off` round-trips back as `False`; the gateway startup check warns `"Gateway approvals.mode=manual with no automated risk "` (`gateway/run.py:7694`).
- **Inputs / options:** exactly three select values — `manual`, `smart`, `off`.
- **Outputs / side effects:** whether a dangerous command prompts, is auto-judged, or runs unchecked.
- **Config / env:** `approvals.mode`; related env `HERMES_YOLO_MODE`; CLI flag `--yolo`; slash `/yolo`.
- **Edge cases / guards:** the hardline blocklist and `approvals.deny` still block even under `off`/`--yolo`; hosted-room policy overrides the config value.
- **Rebuild notes:** Three-way policy consulted by one gate function, with a frozen process-level bypass. A better version would add a per-tool policy matrix instead of one global mode.

### Security → Approvals → Timeout  `id: config-a.approvals.timeout`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → `approvals` → label `TIMEOUT` (number, default `300`).
- **What it does:** How long (seconds) Hermes waits for a human to answer an approval prompt before failing closed.
- **How it works:** `config_defaults.py:2559`. `tools/approval.py:3494-3532` `_get_approval_timeout()`: `raw = int(_get_approval_config().get("timeout", 300))`, non-numeric → 300, then clamped to `agent.deadline.MAX_SAFE_TIMEOUT_S` (~1 year) with the warning `"approvals.timeout=%s exceeds the platform-safe maximum; clamping to %ss"`. The clamp exists because a very large value overflows `time_t` inside `Thread.join(timeout=…)` / `Lock.acquire(timeout=…)` on macOS and previously crashed every parallel tool batch with `OverflowError` (#83220); the fallback cap is `365*24*3600` and it fails CLOSED. The tool executor derives its own bound from this value plus a margin (`agent/tool_executor.py:136-162`; a configured value above 360 s must extend the gate) and a mid-process change applies from the next batch (`:152`). The Codex app-server session names the same gate (`agent/transports/codex_app_server_session.py:1066`). The default was raised from 60 s because gateway approvals arrive as push notifications a user may not see for minutes.
- **Inputs / options:** positive integer seconds.
- **Outputs / side effects:** an unanswered prompt denies the command.
- **Config / env:** `approvals.timeout`.
- **Edge cases / guards:** clamped at ~1 year; parallel tool batches size their own wait from it.
- **Rebuild notes:** One timeout constant read at each prompt with a platform-safe clamp. A better version would keep the request pending out-of-band (a queue the user can answer later) instead of denying on expiry.

### Security → Approvals → Cron / Single-query / Unattended mode  `id: config-a.approvals.noninteractive_modes`
- **Surface:** Config | Security | CLI | Gateway/Telegram
- **Where:** Config page tab `Security 31` → `approvals` → `CRON MODE` (`approvals.cron_mode`, string, default `deny`), `SINGLE QUERY MODE` (`approvals.single_query_mode`, string, default `deny`), `UNATTENDED MODE` (`approvals.unattended_mode`, string, default `deny`).
- **What it does:** How approvals resolve in the three contexts where no human is watching: scheduled cron runs, one-shot `hermes -q/-z` invocations, and unattended gateway sessions. All three default to denying.
- **How it works:** `config_defaults.py:2560-2562`. Readers use the same shape: `mode = str(cfg_get(config, "approvals", "cron_mode", default="deny")).lower().strip()` (`tools/approval.py:3539`), `…"single_query_mode"…` (`:3552`), `…"unattended_mode"…` (`:3571`); each accepts the approve-synonyms set `{"approve", "off", "allow", "yes"}`. Policy comments: `:271-272` (unattended and cron are governed by config, "never by an" interactive resolve), `:329` and `:339`. Denial messages tell the user exactly what to flip — `"approvals.cron_mode: approve in config.yaml."` (`:4151,4238,4887,4906,4933`), `"approvals.single_query_mode: approve in config.yaml."` (`:4158,4245,4819,4841,4869`; the branch comment at `:3833,4795`, the approve path log at `:3854`), `"set approvals.unattended_mode: approve in "` (`:3881,4953,4971,4993`) and the session-scoped note `"approvals.unattended_mode: approve only if sessions on "` (`:5539`, branch comment `:5528`, issues #37284/#87509).
- **Inputs / options:** free strings; `deny` (default) or any of `approve` / `off` / `allow` / `yes`.
- **Outputs / side effects:** dangerous commands in those contexts either run unsupervised or are refused with a message naming the key.
- **Config / env:** `approvals.cron_mode`, `approvals.single_query_mode`, `approvals.unattended_mode`.
- **Edge cases / guards:** plain string fields (no select), so a typo silently means "deny"; the hardline blocklist still applies in approve mode.
- **Rebuild notes:** One resolver per non-interactive context reading its own key, defaulting closed. A better version would let each context carry an allowlist of command patterns instead of a binary approve/deny.

### Security → Approvals → Smart policy  `id: config-a.approvals.smart_policy`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → `approvals` → label `SMART POLICY` (string, default `""`).
- **What it does:** Operator-customisable extra rules appended to the smart-approval guardian's SYSTEM prompt — e.g. "Always ESCALATE commands touching /etc" or "APPROVE docker compose restarts under ~/deploys".
- **How it works:** `config_defaults.py:2563-2570` (inspired by ChatGPT Work's customizable auto-review guardian policy). `tools/approval.py:3628` documents it ("``approvals.smart_policy`` (string, default empty) lets operators append") and `:3634` reads it — `policy = _get_approval_config().get("smart_policy", "")`; the append site is `:3698` ("Operator-customizable policy (approvals.smart_policy). Appended to").
- **Inputs / options:** free multi-line string (rendered as a plain text input in the form; use the YAML view for long policies).
- **Outputs / side effects:** changes the guardian model's verdicts; no direct disk/network effect.
- **Config / env:** `approvals.smart_policy`.
- **Edge cases / guards:** it lands in the guardian's **system** prompt (a trusted channel) — text here is an instruction to the judge, so a badly worded policy can systematically approve dangerous work.
- **Rebuild notes:** Concatenate operator text into the judge's system prompt. A better version would compile the policy into deterministic pre-checks (path globs, command patterns) so it is not left to a model's discretion.

### Security → Approvals → Denial breaker threshold  `id: config-a.approvals.denial_breaker_threshold`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → `approvals` → label `DENIAL BREAKER THRESHOLD` (number, default `3`).
- **What it does:** Consecutive-denial circuit breaker: after N guardian DENY verdicts in a row within one session, the deny message returned to the model escalates from "Do NOT retry" to a hard-stop instruction (report to the user / ask for a manual run or `/approve`).
- **How it works:** `config_defaults.py:2571-2577` (inspired by ChatGPT Work's auto-review circuit breaker). `tools/approval.py:2741` comments the mechanism, `:2754` is the docstring `"""Read ``approvals.denial_breaker_threshold`` from config.` and `:2760` the read — `int(_get_approval_config().get("denial_breaker_threshold", 3))`. Any approval resets the count. `0` disables the breaker.
- **Inputs / options:** non-negative integer; `0` = disabled.
- **Outputs / side effects:** the text of the tool-result the model receives on denial.
- **Config / env:** `approvals.denial_breaker_threshold`.
- **Edge cases / guards:** counts only consecutive DENY verdicts in the same session; smart mode only.
- **Rebuild notes:** Per-session denial counter selecting between two denial message templates. A better version would also stop re-invoking the guardian once tripped, saving the judge call.

### Security → Approvals → Deny  `id: config-a.approvals.deny`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → `approvals` → label `DENY` (list field, placeholder `comma-separated values`, default `[]`).
- **What it does:** User-defined unconditional block rules — fnmatch globs matched against terminal commands. A match blocks the command **before** the `--yolo` / `/yolo` / `mode: off` bypass, making it the user-editable counterpart to the code-shipped hardline blocklist.
- **How it works:** `config_defaults.py:2578-2588`. `tools/approval.py:795-833`: `"""Return the matching ``approvals.deny`` glob, or None.` (`:795`), the semantics note at `:797`, the block-result builder at `:827`, and the user-visible message `f"'{pattern}' (approvals.deny in config.yaml). It cannot be "` (`:833`). Patterns are case-insensitive and must be quoted in YAML when they start with `*` or contain `{}`/`!`/`:` sequences; the shipped example is `deny: ["git push --force*", "*curl*|*sh*"]`. The Claude-settings importer maps `permissions.deny` Bash rules into this key (`hermes_cli/agent_import.py:23,689`); `hermes_cli/config.py:4006` protects it from managed-scope override surprises ("including security-critical ``approvals.deny``"); `hermes_cli/subcommands/approvals.py:84` lists it in the precedence explanation ("hardline blocklist, user approvals.deny rules, dangerous-pattern ").
- **Inputs / options:** list of fnmatch glob strings.
- **Outputs / side effects:** the command never runs; the model receives a block message naming the matched pattern.
- **Config / env:** `approvals.deny`.
- **Edge cases / guards:** matched against the command string, so shell tricks (variable expansion, base64) can evade a naive glob; the comma-splitting list widget makes patterns containing commas awkward — use the YAML view.
- **Rebuild notes:** Case-insensitive fnmatch list checked first in the gate. A better version would match on a parsed command AST (binary + args) instead of the raw string.

### Security → Approvals → MCP reload confirm  `id: config-a.approvals.mcp_reload_confirm`
- **Surface:** Config | Security | CLI | TUI | Gateway/Telegram
- **Where:** Config page tab `Security 31` → `approvals` → label `MCP RELOAD CONFIRM` (switch, default `true`). Surfaced as the confirmation prompt on `/reload-mcp`.
- **What it does:** Asks before rebuilding the MCP tool set for the active session, because a reload invalidates the provider prompt cache (tool schemas are baked into the system prompt) and the next message re-sends full input tokens.
- **How it works:** `config_defaults.py:2589-2596`. Readers: `gateway/slash_commands.py:5915` `confirm_required = bool(approvals.get("mcp_reload_confirm", True))` (docstring `:5901`), `tui_gateway/methods_tools.py:104` (comment `:89`), `cli.py:14651` (docstring `:14641-14643`). Clicking "Always Approve" persists the opt-out: `save_config_value("approvals.mcp_reload_confirm", False)` at `gateway/slash_commands.py:5931`, `cli.py:14690` (which then prints `"   Re-enable via `approvals.mcp_reload_confirm: true` in config.yaml."`, `:14692`), and `tui_gateway/server.py:15515` `_save_cfg("approvals.mcp_reload_confirm", False)`.
- **Inputs / options:** boolean; at the prompt: Approve Once / Always Approve / Cancel.
- **Outputs / side effects:** rebuilt tool surface + invalidated prompt cache; "Always Approve" writes `false` into `config.yaml`.
- **Config / env:** `approvals.mcp_reload_confirm`.
- **Edge cases / guards:** the automatic watcher-driven reload is governed separately by `mcp.auto_reload_on_config_change`; when that is off the watcher only prints guidance to run `/reload-mcp`.
- **Rebuild notes:** Confirm-with-remember prompt writing the answer back to config. A better version would show the estimated token cost of the cache break in the prompt.

### Security → Approvals → Destructive slash confirm  `id: config-a.approvals.destructive_slash_confirm`
- **Surface:** Config | Security | CLI | TUI | Gateway/Telegram
- **Where:** Config page tab `Security 31` → `approvals` → label `DESTRUCTIVE SLASH CONFIRM` (switch, default `true`). Surfaced on `/clear`, `/new`, `/reset`, `/undo`.
- **What it does:** Asks before a destructive session slash command discards conversation state.
- **How it works:** `config_defaults.py:2597-2607`. Three-option prompt (Approve Once / Always Approve / Cancel) routed through `tools.slash_confirm` — native yes/no buttons on Telegram, Discord and Slack; text fallback elsewhere. Readers: `gateway/run.py:25516` `confirm_required = bool(approvals.get("destructive_slash_confirm", True))` (docstring `:25498-25506` documenting the `always` branch), `cli.py:14591` (docstring `:14558-14562`). "Always Approve" persists `save_config_value("approvals.destructive_slash_confirm", False)` (`gateway/run.py:25536`, `cli.py:14624`), after which the CLI prints `"   Re-enable via `approvals.destructive_slash_confirm: true` in config.yaml."` (`cli.py:14626`). The TUI honours the same setting for its `/clear`, `/new` and `/reset` modal; `HERMES_TUI_NO_CONFIRM=1` force-skips that modal regardless of the configured value. A self-serve note at `cli.py:14510` explains the flow lets users opt out without hand-editing the key.
- **Inputs / options:** boolean; prompt buttons Approve Once / Always Approve / Cancel.
- **Outputs / side effects:** conversation state is discarded or preserved; "Always Approve" writes `false`.
- **Config / env:** `approvals.destructive_slash_confirm`; env `HERMES_TUI_NO_CONFIRM=1` (TUI modal only).
- **Edge cases / guards:** the env override skips the modal even when the key is `true`; `/undo` is included in the guarded set.
- **Rebuild notes:** Shared confirm helper with a platform-native yes/no widget and a persist-the-answer branch. A better version would make the destructive action undoable (a trash bin) instead of confirming it.

### Security → Allow private URLs  `id: config-a.security.allow_private_urls`
- **Surface:** Config | Security | Tool
- **Where:** Config page tab `Security 31` → label `ALLOW PRIVATE URLS` (`security.allow_private_urls`, switch, default `false`).
- **What it does:** Globally disables the SSRF guard so tools may fetch private/internal IPs (localhost, 192.168.x.x, …) — needed for OpenWrt boxes, internal proxies, VPN-reachable services.
- **How it works:** `config_defaults.py:2659`. Central check `tools/url_safety.py`: module note at `:8` ("The check can be globally disabled via ``security.allow_private_urls: true``"), precedence list at `:225-226` (env first, then `security.allow_private_urls`, then the legacy `browser.allow_private_urls`), reads at `:263-272` (`sec.get("allow_private_urls")` then `browser.get("allow_private_urls")`, both via `is_truthy_value(..., default=False)`), the allow-path at `:421` and the log line `"Allowing private/internal resolution (security.allow_private_urls=true): %s"` (`:504`). The web result cache is only reachable with it enabled (`tools/web_result_cache.py:324`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** DNS results resolving to private ranges are accepted instead of blocked.
- **Config / env:** `security.allow_private_urls`; env `HERMES_ALLOW_PRIVATE_URLS`; legacy fallback key `browser.allow_private_urls`.
- **Edge cases / guards:** this is the main SSRF protection — enabling it lets a prompt-injected page steer the agent at cloud metadata endpoints (169.254.169.254) and LAN admin panels.
- **Rebuild notes:** Resolve then check the resolved IP against private/link-local/loopback ranges before connecting, with one global override. A better version would take an explicit allowlist of internal hosts rather than an all-or-nothing switch.

### Security → Redact secrets  `id: config-a.security.redact_secrets`
- **Surface:** Config | Security | CLI
- **Where:** Config page tab `Security 31` → label `REDACT SECRETS` (`security.redact_secrets`, switch, default `true`).
- **What it does:** Master switch for secret redaction across logs, exports, share archives and (partly) the model-facing context.
- **How it works:** `config_defaults.py:2660`. `agent/redact.py:72` ("can opt out via `security.redact_secrets: false` in config.yaml"), `:796` ("Enabled by default. Disable via security.redact_secrets: false in config.yaml."), and `:1134` documents that `force=True` bypasses the global preference. Consumers: the debug bundle (`hermes_cli/debug.py:429` — the local on-disk log file is treated separately), markdown session export (`hermes_cli/session_export_md.py:226`; an explicit `--redact` export overrides), profile share archives (`hermes_cli/profiles.py:2188` — `security.redact_secrets` / `HERMES_REDACT_SECRETS`), and the chat-completion helper (`agent/chat_completion_helpers.py:2394`, issue #19798). The Langfuse observability plugin redacts unconditionally, even with this off (`plugins/observability/langfuse/__init__.py:158`). The value is bridged into the environment at startup: `cli.py:765` reads `security_config.get("redact_secrets")` and exports `HERMES_REDACT_SECRETS` (`cli.py:~766`); also read at `gateway/run.py:2869`, `hermes_cli/main.py:802` (early boot) and `hermes_cli/config.py:4264`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** `sk-…`-shaped strings and other detected secrets become placeholders in logs/exports.
- **Config / env:** `security.redact_secrets` → env `HERMES_REDACT_SECRETS` (exported as a lowercase string).
- **Edge cases / guards:** turning it off leaves credentials in `~/.hermes/logs/` and in any exported transcript; some paths (Langfuse) redact regardless.
- **Rebuild notes:** Regex/entropy detector applied at every egress point, with one global switch and a per-call `force`. A better version would tokenise known credentials at load time so redaction is exact rather than heuristic.

### Security → Allow data-training tiers non-interactive  `id: config-a.security.allow_data_training_tiers_noninteractive`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → label `ALLOW DATA TRAINING TIERS NONINTERACTIVE` (switch, default `false`).
- **What it does:** Persisted acknowledgement that lets a non-interactive run proceed with a model override whose provider tier permits training on prompts/completions.
- **How it works:** `config_defaults.py:2661-2664`. Read at `hermes_cli/main.py:1209` (`security_cfg.get("allow_data_training_tiers_noninteractive") is True`) inside the startup guard, whose messages are `"security.allow_data_training_tiers_noninteractive is true.\n"` (`:1219`) and `"security.allow_data_training_tiers_noninteractive to true "` (`:1233`). The startup guard still prints the full warning on every run and never bypasses cost guards.
- **Inputs / options:** boolean (strict `is True` comparison).
- **Outputs / side effects:** a non-interactive run continues instead of aborting.
- **Config / env:** `security.allow_data_training_tiers_noninteractive`.
- **Edge cases / guards:** strict identity check — the string `"true"` does not enable it; the warning is printed regardless.
- **Rebuild notes:** Persisted per-machine consent flag consulted only on the non-interactive path. A better version would record which tier was acknowledged and when, and re-prompt when the tier changes.

### Security → Approval transport / Transport fallback  `id: config-a.security.approval.transport`
- **Surface:** Config | Security | Plugin
- **Where:** Config page tab `Security 31` → `TRANSPORT` (`security.approval.transport`, string, default `builtin`) and `TRANSPORT FALLBACK` (`security.approval.transport_fallback`, string, default `deny`).
- **What it does:** Chooses how a human approval prompt is *presented*. `builtin` keeps the CLI/TUI/gateway/ACP surfaces; naming a plugin routes presentation there. The fallback decides what happens when the plugin times out, errors or returns an invalid response.
- **How it works:** `config_defaults.py:2665-2676`. `tools/approval.py:4302-4316` `_get_approval_transport_config()` reads `((config.get("security") or {}).get("approval") or {})`, taking `transport` (defaulting to `"builtin"`) and `transport_fallback`, and returns `(selected or "builtin", "builtin" if fallback == "builtin" else None)` — i.e. **only the literal string `builtin` enables a fallback; anything else (including the default `deny`) means fail closed**. An unreadable/malformed selection returns the sentinel `("config-error", None)` so a prompt is never silently materialised on a built-in surface the operator may not be watching (`:4313-4315`). Plugin discovery is forced before the first approval so an explicitly selected transport is not mistaken for unavailable (`:4295-4300`). The plugin contract is documented at `hermes_cli/plugins.py:1744` ("``security.approval.transport: <name>``. It receives a host-created,").
- **Inputs / options:** transport name string (`builtin` or a plugin name); fallback string (`deny` default; only `builtin` changes behaviour).
- **Outputs / side effects:** where the approval prompt appears; on transport failure, a denial (or a built-in prompt if fallback is `builtin`).
- **Config / env:** `security.approval.transport`, `security.approval.transport_fallback`.
- **Edge cases / guards:** "This is presentation only: plugins cannot detect, suppress, or auto-approve commands outside a correlated human response" (`config_defaults.py:2669-2671`). Both are plain string fields — a typo in `transport` yields an unavailable transport and, with the default fallback, a denial.
- **Rebuild notes:** Pluggable prompt presenter behind a correlation id, fail-closed by default. A better version would let several transports race (phone push + terminal) with the first correlated answer winning.

### Security → Protected instruction files (+ extra patterns)  `id: config-a.security.protected_instruction_files`
- **Surface:** Config | Security | Tool
- **Where:** Config page tab `Security 31` → `PROTECTED INSTRUCTION FILES` (`security.protected_instruction_files`, switch, default `true`) and `PROTECTED INSTRUCTION EXTRA PATTERNS` (`security.protected_instruction_extra_patterns`, list, default `[]`).
- **What it does:** Forces human approval for any write to an agent-instruction file — `AGENTS.md`, `CLAUDE.md`, `SOUL.md`, `.cursorrules`, project-local `.hermes` config — **even under auto-approve / yolo**. The list adds extra fnmatch globs matched against the file's basename (e.g. `*.mdc`).
- **How it works:** `config_defaults.py:2677-2680`. Both read side by side in the file tool: `tools/file_tools.py:777` `enabled = cfg_get(cfg, "security", "protected_instruction_files", …)` and `:779` `extra = cfg_get(cfg, "security", "protected_instruction_extra_patterns", …)`.
- **Inputs / options:** boolean; list of basename globs.
- **Outputs / side effects:** an approval prompt (or denial in non-interactive contexts) before the write lands.
- **Config / env:** `security.protected_instruction_files`, `security.protected_instruction_extra_patterns`.
- **Edge cases / guards:** patterns match the **basename**, not the path, so `docs/*.md` will not work; disabling the switch lets a prompt-injected agent rewrite its own instructions.
- **Rebuild notes:** Path/basename classifier consulted in the write path before the approval bypass. A better version would diff the proposed instruction change and require approval only for semantic edits.

### Security → Tirith scanner (enabled / path / timeout / fail-open)  `id: config-a.security.tirith`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → `TIRITH ENABLED` (`security.tirith_enabled`, switch, default `true`), `TIRITH PATH` (`security.tirith_path`, string, default `tirith`), `TIRITH TIMEOUT` (`security.tirith_timeout`, number, default `5`), `TIRITH FAIL OPEN` (`security.tirith_fail_open`, switch, default `true`).
- **What it does:** Pre-exec security scanning of commands by the external `tirith` binary: whether to run it, where it lives, how long to wait, and whether an erroring/missing scanner blocks the command or lets it through.
- **How it works:** `config_defaults.py:2657,2681-2684` ("Pre-exec security scanning via tirith"). `tools/tirith_security.py:71-86` builds the effective config with env-over-config precedence: defaults `{"tirith_enabled": True, "tirith_path": "tirith", "tirith_timeout": 5, "tirith_fail_open": True}` (`:71-74`) then `_env_bool("TIRITH_ENABLED", cfg.get("tirith_enabled", …))` (`:83`), `os.getenv("TIRITH_BIN", cfg.get("tirith_path", …))` (`:84`), `_env_int("TIRITH_TIMEOUT", cfg.get("tirith_timeout", …))` (`:85`), `_env_bool("TIRITH_FAIL_OPEN", cfg.get("tirith_fail_open", …))` (`:86`); the path is resolved at `:661,762` and the timeout/fail-open applied at `:763-764`. Approval integration reads the same keys per context: `tools/approval.py:4855,4920,4979,5018` (`_sec.get("tirith_enabled", True)`) and `:4856,4921,4980,5020` (`_sec.get("tirith_fail_open", True)`), with fail-closed messages `"imported and security.tirith_fail_open is false, "` (`:4864,4929,4988`) and `"Because security.tirith_fail_open is false, this "` (`:5033`); the "Tirith not installed" branches are commented at `:4845,4910`. The CLI reads it at `cli.py:8816`; the gateway startup check warns `"assessor (security.tirith_enabled is false and "` … `"them in chat. Enable security.tirith_enabled or configure "` (`gateway/run.py:7690-7698`). Tip: `hermes_cli/tips.py:465`.
- **Inputs / options:** boolean; path/binary-name string; integer seconds; boolean.
- **Outputs / side effects:** a subprocess scan per candidate command; a verdict that can block execution.
- **Config / env:** `security.tirith_enabled` (env `TIRITH_ENABLED`), `security.tirith_path` (env `TIRITH_BIN`), `security.tirith_timeout` (env `TIRITH_TIMEOUT`), `security.tirith_fail_open` (env `TIRITH_FAIL_OPEN`). Env wins.
- **Edge cases / guards:** default fail-**open** means a missing/broken scanner does not block anything — set `false` for a fail-closed posture; the timeout adds latency to every scanned command.
- **Rebuild notes:** Optional external scanner invoked with a timeout, with an explicit open/closed failure policy. A better version would cache verdicts per command hash and stream partial results so the timeout rarely bites.

### Security → Website blocklist (enabled / domains / shared files)  `id: config-a.security.website_blocklist`
- **Surface:** Config | Security | Tool
- **Where:** Config page tab `Security 31` → `ENABLED` (`security.website_blocklist.enabled`, switch, default `false`), `DOMAINS` (`security.website_blocklist.domains`, list, default `[]`), `SHARED FILES` (`security.website_blocklist.shared_files`, list, default `[]`).
- **What it does:** Blocks named domains from every web tool (fetch, extract, browser). `domains` holds inline rules; `shared_files` points at additional rule files.
- **How it works:** `config_defaults.py:2685-2689`. `tools/website_policy.py:25-29` holds `_DEFAULT_WEBSITE_BLOCKLIST = {"enabled": False, "domains": [], "shared_files": []}`; the policy is parsed and cached for `_CACHE_TTL_SECONDS = 30.0` behind a lock so a 50-URL extract does not re-parse `config.yaml` 51 times (`:31-40`). Validation raises `WebsitePolicyError` with the exact key names: `"security.website_blocklist.domains must be a list"` (`:159`), `"security.website_blocklist.shared_files must be a list"` (`:163`), `"security.website_blocklist.enabled must be a boolean"` (`:167`). Rules are normalised and de-duplicated into `{"pattern": …, "source": "config"}` entries (`:170+`). Tip: `hermes_cli/tips.py:122`.
- **Inputs / options:** boolean; list of domain rules; list of file paths.
- **Outputs / side effects:** matching URLs are refused by web/browser tools.
- **Config / env:** the three `security.website_blocklist.*` keys.
- **Edge cases / guards:** note the internal default for `enabled` when the key is absent from a policy dict is `True` (`website_policy.py:165`) while `DEFAULT_CONFIG` seeds `False` — the merged config always supplies the key, so the effective default is off; a 30-second cache means edits take up to half a minute to apply; a malformed value raises rather than failing open.
- **Rebuild notes:** Cached rule set (inline + files) checked against the request host. A better version would support allowlist mode and per-tool scoping.

### Security → Acked advisories  `id: config-a.security.acked_advisories`
- **Surface:** Config | Security | CLI
- **Where:** Config page tab `Security 31` → label `ACKED ADVISORIES` (list, default `[]`). Written by `hermes doctor --ack <id>`.
- **What it does:** Records supply-chain security advisories the user has read and acted on (uninstalled the compromised package, rotated credentials) so they stop triggering the startup banner.
- **How it works:** `config_defaults.py:2690-2697`. `hermes_cli/security_advisories.py:17` ("``config.security.acked_advisories`` and survives restart"), `:194` ("Acks live under ``security.acked_advisories`` in config.yaml as a list of"), read at `:216` (`raw = sec.get("acked_advisories") or []`) and appended at `:238-243` (`existing = sec.get("acked_advisories") or []` → `sec["acked_advisories"] = existing`). The advisory catalog itself lives in that module.
- **Inputs / options:** list of advisory id strings; remove by editing the list directly.
- **Outputs / side effects:** the startup advisory banner stops showing for those ids.
- **Config / env:** `security.acked_advisories`.
- **Edge cases / guards:** acking does not remediate anything — it only silences the notice.
- **Rebuild notes:** Set of acknowledged ids compared against a shipped catalog at boot. A better version would verify the remediation (package version check) before allowing the ack.

### Security → Allow lazy installs  `id: config-a.security.allow_lazy_installs`
- **Surface:** Config | Security | Core
- **Where:** Config page tab `Security 31` → label `ALLOW LAZY INSTALLS` (switch, default `true`).
- **What it does:** Lets Hermes install opt-in backend packages from PyPI on first use — e.g. pulling `elevenlabs` the first time the user picks ElevenLabs as their TTS provider.
- **How it works:** `config_defaults.py:2698-2706`. Central gate `tools/lazy_deps.py:527` — `if not bool(sec.get("allow_lazy_installs", True)):`. Consumers that document the dependence: `plugins/memory/mem0/__init__.py:269`, `plugins/memory/supermemory/__init__.py:284` (which also notes the sealed-Docker case), `agent/azure_identity_adapter.py:276,329` and its message `"installs (security.allow_lazy_installs: true in "` (`:354`), and the OTLP exporter (`agent/monitoring/otlp_exporter.py:42,245` — "gated by security.allow_lazy_installs and TTY-prompted"). The updater's failure path names it as the most common reason a component is missing (`hermes_cli/update_cmd.py:3730`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** `pip install` runs at runtime and mutates the active environment.
- **Config / env:** `security.allow_lazy_installs`.
- **Edge cases / guards:** set `false` for restricted networks, audited environments or air-gapped systems — then every optional backend needs an explicit `pip install`; installs are additionally TTY-prompted in some paths.
- **Rebuild notes:** One boolean checked by a single `ensure(package)` helper. A better version would install into an isolated per-feature virtualenv with a pinned hash instead of the live environment.

### Security → Telemetry → Shared metrics enabled  `id: config-a.telemetry.shared_metrics.enabled`
- **Surface:** Config | Security
- **Where:** Config page tab `Security 31` → divider `telemetry` → label `ENABLED` (`telemetry.shared_metrics.enabled`, switch, default `false`).
- **What it does:** Opt-in collection of privacy-safe aggregate metrics, written **only** to this profile's local telemetry directory.
- **How it works:** `config_defaults.py:3493-3500` — "Privacy-safe aggregate metrics written only to this profile's local telemetry directory. Collection is opt-in and no remote sink exists." Schema note: `hermes_cli/web_server.py:1483` — "`telemetry.shared_metrics.enabled` is the only schema-surfaced telemetry" key (the rest of the `telemetry` tree is not exposed as fields).
- **Inputs / options:** boolean.
- **Outputs / side effects:** metric files under the profile's local telemetry directory; nothing is transmitted.
- **Config / env:** `telemetry.shared_metrics.enabled`.
- **Edge cases / guards:** despite the name "shared", there is no remote sink in this release — the data stays on disk.
- **Rebuild notes:** Local aggregate counters behind an opt-in flag. A better version would document the exact metric schema and offer an explicit export command rather than implying sharing.

### Security → Proxy (egress firewall enable / credential source / Docker enforcement)  `id: config-a.proxy.security_keys`
- **Surface:** Config | Security | CLI
- **Where:** Config page tab `Security 31` → divider `proxy` → `ENABLED` (`proxy.enabled`, switch, default `false`, description `Docker-only egress credential firewall. Requires \`hermes egress setup\` and \`hermes egress start\`; Modal/SSH/Daytona are not wired yet.`), `CREDENTIAL SOURCE` (`proxy.credential_source`, select, default `env`, description `Where iron-proxy loads real upstream secrets at start time`), `ENFORCE ON DOCKER` (`proxy.enforce_on_docker`, switch, default `true`, description `Refuse Docker sandboxes when egress is enabled but not configured/running`). These three are re-categorised into `security` by their overrides (`hermes_cli/web_server.py:1309-1326`); the other five `proxy.*` keys stay on the `Proxy` tab (sibling shard).
- **What it does:** Routes sandbox egress through a managed `iron-proxy` subprocess so the sandbox only ever holds opaque proxy tokens while iron-proxy swaps in real API credentials at the egress boundary; picks where those real secrets come from; and decides whether Docker sandboxes may start at all when the proxy is enabled but not running.
- **How it works:** `config_defaults.py:3826-3856`. `enabled` is a master switch — when false iron-proxy is never started, no docker mounts are added, no binaries are auto-installed (a complete no-op). `hermes_cli/proxy_cli.py:9` (`disable  — flip ``proxy.enabled`` to False (does not stop a running proxy)`), `:552` (`"[yellow]proxy.enabled is false — run `hermes egress setup` "`), `:828` (`"proxy.enabled was already false."`), `:832` (`"✓ proxy.enabled set to false"`). `credential_source`: `env` = the process environment (what a Bitwarden integration already populates); `bitwarden` = refetch via `bws secret list` on each proxy restart so rotation in the Bitwarden web app propagates without touching `.env` (requires `secrets.bitwarden.enabled`); readers/writers at `hermes_cli/proxy_cli.py:447-464,562,739,785` and the refusal `"[red]✗ Refusing to start: proxy.credential_source is "` (`:584`). `enforce_on_docker` is read fail-safe at `tools/environments/docker.py:610-614` (`bool((_load_cfg().get("proxy") or {}).get("enforce_on_docker", default))`) and applied at `:444,467,1194,1260`, with the startup refusal `"proxy.enabled is true but iron-proxy is not configured. "` (`:471`); the setup wizard seeds it (`hermes_cli/setup.py:1503`, `proxy_cli.py:440`) and the status table prints `Docker enforce` (`proxy_cli.py:740,786`).
- **Inputs / options:** boolean; select `env` | `bitwarden`; boolean.
- **Outputs / side effects:** an iron-proxy subprocess, docker mounts and `HTTPS_PROXY` in the sandbox; a refused `docker run` when enforcement trips.
- **Config / env:** `proxy.enabled`, `proxy.credential_source`, `proxy.enforce_on_docker`; the Bitwarden path additionally needs the BWS access token / project id (see `secrets.bitwarden.*`, sibling shard).
- **Edge cases / guards:** Docker-only in this release — Modal/SSH/Daytona are not wired; `enforce_on_docker: false` falls back to direct outbound **with real credentials inside the sandbox** (the legacy posture); disabling `proxy.enabled` does not stop an already-running proxy.
- **Rebuild notes:** A local MITM proxy holding the real keys, handing the sandbox opaque tokens, plus a start-time guard on the sandbox backend. A better version would extend the same boundary to every remote backend and attest the proxy's CA to the sandbox.

## Browser (25 fields)

All 25 keys live under `browser:` (including the `camofox` and `extension_control` sub-objects, which the schema flattens into dotted leaves), so the tab shows no sub-section dividers. `browser.cloud_provider` and the per-provider blocks are plugin-owned and do not appear here.

### Browser → Backend  `id: config-a.browser.backend`
- **Surface:** Config | Tool | CLI
- **Where:** Config page tab `Browser 25` → label `BACKEND` (string, default `""`). Runtime equivalent: `/browser use off`.
- **What it does:** Chooses the browser tool implementation: Browser Use mode (one `browser_exec` tool driving the Browser Use CLI 3.0 over any CDP backend) or the built-in browser tools (`browser_navigate`, `browser_click`, …).
- **How it works:** `config_defaults.py:574-584`. `""` (default) = Browser Use mode when the `browser-use` CLI (or `uvx`) is available, otherwise the built-in tools; Camofox setups always keep the built-in tools (no CDP surface). Module docs: `tools/browser_use_cli.py:3` ("When browser.backend is \"browser-use\", the model gets ``browser_exec`` tool"), `:219-221` ("Browser Use mode is the DEFAULT: an unset ``browser.backend`` (\"\") enables … Set ``browser.backend: off`` (or ``/browser use off``) for the built-in"), `:225` (Camofox is not a `browser.backend` value — it is Firefox-based with a custom HTTP API and no CDP), and the one-time notice ending `"or `browser.backend: off` in config.yaml to silence this."` (`:286`). The provider-selection registry treats `browser.backend` as the category's selection key (`tools/tool_backend_helpers.py:306`), and `toolsets.py:54` notes the toolset "replaces other tools when browser.backend is \"browser-use\"".
- **Inputs / options:** three strings — `""` (auto), `browser-use` (force Browser Use mode), `off` (force the built-in tools).
- **Outputs / side effects:** which browser tools appear in the model's tool list (and therefore the system prompt).
- **Config / env:** `browser.backend`.
- **Edge cases / guards:** plain string field, not a select; an unavailable Browser Use CLI silently degrades to the built-in tools; Camofox overrides the choice.
- **Rebuild notes:** Capability probe + explicit override selecting between two tool families. A better version would expose both families simultaneously and let the model pick per task.

### Browser → Engine  `id: config-a.browser.engine`
- **Surface:** Config | Tool | Env
- **Where:** Config page tab `Browser 25` → label `ENGINE` (string, default `auto`).
- **What it does:** Picks the local browser engine for both drivers: `auto` = Chrome (default), `lightpanda` = Lightpanda (faster navigation, no screenshots), `chrome` = explicitly request Chrome.
- **How it works:** `config_defaults.py:592-604`. In Browser Use mode `lightpanda` makes Hermes spawn `lightpanda serve` per session and point `browser_exec` at it (`tools/browser_use_cli.py:513` "Only when ``browser.engine`` is ``lightpanda`` and nothing with higher"); with the built-in tools it is passed as `--engine <value>` to agent-browser v0.25.3+ with automatic Chrome fallback. Cached read at `tools/browser_tool.py:1046-1067` ("Reads ``config[\"browser\"][\"engine\"]`` once and caches the result"); also read at `hermes_cli/tools_config.py:4197` (`str(cfg_get(config, "browser", "engine") or "auto").strip().lower()`) and seeded in `cli.py:469`. Failure messages: `tools/browser_lightpanda.py:209-215` ("browser.engine is 'lightpanda' but Lightpanda has no Windows build. Set browser.engine to auto (or run Hermes under WSL2).", and the no-binary variant ending "or set browser.engine to auto.") and `tools/browser_use_cli.py:535,542` ("Lightpanda could not be started: … Set browser.engine to auto ", "Lightpanda session returned no CDP endpoint. Set browser.engine ").
- **Inputs / options:** three strings — `auto`, `lightpanda`, `chrome`.
- **Outputs / side effects:** which browser binary is launched.
- **Config / env:** `browser.engine`; env `AGENT_BROWSER_ENGINE`.
- **Edge cases / guards:** ignored while a cloud provider, Camofox, `browser.cdp_url` or `browser.use_real_profile` is active — `/browser status` and `hermes doctor` say so; Lightpanda has no Windows build and cannot load a Chromium profile (so it is incompatible with `use_real_profile`, `tools/browser_tool.py:1165`).
- **Rebuild notes:** Engine enum resolved once per process with capability-based veto rules. A better version would report the effective engine (and why) in every browser tool result.

### Browser → Inactivity timeout / Command timeout  `id: config-a.browser.timeouts`
- **Surface:** Config | Tool | Env
- **Where:** Config page tab `Browser 25` → `INACTIVITY TIMEOUT` (`browser.inactivity_timeout`, number, default `120`) and `COMMAND TIMEOUT` (`browser.command_timeout`, number, default `30`).
- **What it does:** Auto-cleans idle browser sessions after N seconds, and caps how long a single browser command (screenshot, navigate, …) may take.
- **How it works:** `config_defaults.py:585-587`. Inactivity: default sourced from `DEFAULT_CONFIG` at `tools/browser_tool.py:2153` and read at `:2162` (`val = cfg_get(cfg, "browser", "inactivity_timeout")`); bridged to the environment at startup — `cli.py:713-719` maps `{"inactivity_timeout": "BROWSER_INACTIVITY_TIMEOUT"}` and unconditionally exports it. Command timeout: `tools/browser_tool.py:327-339` ("Reads ``config[\"browser\"][\"command_timeout\"]`` and falls back to" … `val = cfg_get(cfg, "browser", "command_timeout")`), documented on the tool at `:3708` ("``browser.command_timeout`` from config (default 30s)"), and mirrored for Camofox at `tools/browser_camofox.py:61-79` (`"""Return ``browser.command_timeout`` from config, falling back to 30s.` and the debug line `"Could not read browser.command_timeout: %s"`).
- **Inputs / options:** two integers (seconds).
- **Outputs / side effects:** browser processes/sessions are torn down; commands abort with a timeout error.
- **Config / env:** `browser.inactivity_timeout` (env `BROWSER_INACTIVITY_TIMEOUT`, exported from config on every start), `browser.command_timeout`.
- **Edge cases / guards:** the idle reaper still applies in headed mode; a too-small command timeout breaks slow-loading pages.
- **Rebuild notes:** Idle timer per session plus a per-command deadline. A better version would scale the command timeout by operation type (navigate vs click).

### Browser → Snapshot threshold  `id: config-a.browser.snapshot_threshold`
- **Surface:** Config | Tool
- **Where:** Config page tab `Browser 25` → label `SNAPSHOT THRESHOLD` (number, default `15000`).
- **What it does:** Maximum characters of an accessibility/page snapshot returned inline; larger snapshots are truncated and stored for paged retrieval.
- **How it works:** `config_defaults.py:588` ("Max chars before snapshot truncate-and-store (min 1000)"). Read at `tools/browser_tool.py:379` (`val = cfg_get(cfg, "browser", "snapshot_threshold")`) with the failure debug `"Could not read browser.snapshot_threshold: %s"` (`:383`); the constant is documented at `:289` and the tool docstring points at it (`:4082`); the truncate-and-store site is `:4479`.
- **Inputs / options:** integer characters, minimum 1000.
- **Outputs / side effects:** truncated tool output plus a stored full snapshot the model can page.
- **Config / env:** `browser.snapshot_threshold`.
- **Edge cases / guards:** values below 1000 are floored; raising it inflates context usage on every snapshot.
- **Rebuild notes:** Length cap with spill-to-store and a retrieval pointer. A better version would return a semantically pruned tree (interactive elements first) rather than a character prefix.

### Browser → Record sessions  `id: config-a.browser.record_sessions`
- **Surface:** Config | Tool
- **Where:** Config page tab `Browser 25` → label `RECORD SESSIONS` (switch, default `false`).
- **What it does:** Auto-records browser sessions as WebM videos.
- **How it works:** `config_defaults.py:589`; seeded in `cli.py:468`. Read at `tools/browser_tool.py:5298` — `record_enabled = cfg_get(cfg, "browser", "record_sessions", default=False)` inside the function documented at `:5290` (`"""Start recording if browser.record_sessions is enabled in config."""`). Tip: `hermes_cli/tips.py:120`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** WebM files written per session.
- **Config / env:** `browser.record_sessions`.
- **Edge cases / guards:** recordings can capture logged-in pages and credentials typed into forms — treat the output directory as sensitive; disk usage grows per session.
- **Rebuild notes:** Enable the driver's video-capture option per context. A better version would auto-expire recordings and redact password fields.

### Browser → Headed  `id: config-a.browser.headed`
- **Surface:** Config | Tool | Env
- **Where:** Config page tab `Browser 25` → label `HEADED`, description `Run the local browser in headed mode (visible window). Also keeps the window open between turns; idle sessions are still reaped after browser.inactivity_timeout.` (switch, default `false`).
- **What it does:** Launches Chromium with a visible window and skips per-turn cleanup so the window persists between turns.
- **How it works:** Override with that description at `hermes_cli/web_server.py:1427-1431`; declared at `config_defaults.py:590`. Read at `tools/browser_tool.py:1098-1115` — "Reads ``config[\"browser\"][\"headed\"]`` with ``AGENT_BROWSER_HEADED`` env" (`:1098`), `val = cfg.get("browser", {}).get("headed")` (`:1111`), failure debug `"Could not read browser.headed from config: %s"` (`:1115`); the wider effect is noted at `:1800` ("browser.headed / AGENT_BROWSER_HEADED toggle the rest of the browser").
- **Inputs / options:** boolean.
- **Outputs / side effects:** a visible browser window that survives between turns; more memory held.
- **Config / env:** `browser.headed`; env `AGENT_BROWSER_HEADED`.
- **Edge cases / guards:** the idle reaper still closes the window after `browser.inactivity_timeout`; headless-only hosts (no display) will fail to launch.
- **Rebuild notes:** Pass `headless=false` and skip per-turn context teardown. A better version would attach the visible window to a screencast the dashboard can show.

### Browser → Allow private URLs / Auto-local for private URLs  `id: config-a.browser.private_urls`
- **Surface:** Config | Security | Tool
- **Where:** Config page tab `Browser 25` → `ALLOW PRIVATE URLS` (`browser.allow_private_urls`, switch, default `false`) and `AUTO LOCAL FOR PRIVATE URLS` (`browser.auto_local_for_private_urls`, switch, default `true`).
- **What it does:** The first is the legacy per-browser SSRF override (allow navigating to localhost / 192.168.x.x / …). The second, when a **cloud** browser provider is configured, auto-spawns a local Chromium for LAN/localhost URLs instead of sending them to the cloud.
- **How it works:** `config_defaults.py:591,605`. Private-URL precedence (`tools/url_safety.py:225-226`): env → `security.allow_private_urls` → `browser.allow_private_urls` (legacy / backward compat), read at `:266` and `:272`; the browser-side reader is `tools/browser_tool.py:2070-2098` ("Reads ``config[\"browser\"][\"allow_private_urls\"]``. Single-profile calls" … `browser_cfg.get("allow_private_urls")`), with the global opt-out comment at `:4215`. Auto-local routing: `tools/browser_tool.py:1477-1495` ("Reads ``browser.auto_local_for_private_urls`` once (default ``True``) and" … `if isinstance(browser_cfg, dict) and "auto_local_for_private_urls" in browser_cfg`), the routing condition at `:1981` and the log `"set browser.auto_local_for_private_urls: false to disable)"` (`:4276`). Both appear in support dumps (`hermes_cli/dump.py:245`).
- **Inputs / options:** boolean ×2.
- **Outputs / side effects:** private URLs are fetched or refused; LAN URLs are handled by a locally spawned Chromium rather than the cloud provider.
- **Config / env:** `browser.allow_private_urls` (superseded by `security.allow_private_urls` / `HERMES_ALLOW_PRIVATE_URLS`), `browser.auto_local_for_private_urls`.
- **Edge cases / guards:** `auto_local_for_private_urls` is a privacy feature (your LAN URLs never leave the machine) as much as a reachability one; disabling it while using a cloud provider sends internal hostnames to a third party.
- **Rebuild notes:** Classify the target IP, then route to the local or remote driver. A better version would let the operator declare which internal CIDRs are "local-only" instead of inferring.

### Browser → CDP URL  `id: config-a.browser.cdp_url`
- **Surface:** Config | Tool | Env | CLI
- **Where:** Config page tab `Browser 25` → label `CDP URL` (string, default `""`). Runtime equivalent: `/browser connect <url>`.
- **What it does:** A persistent Chrome DevTools Protocol endpoint to attach to an existing Chromium/Chrome instead of launching one.
- **How it works:** `config_defaults.py:606`. Precedence documented at `tools/browser_cdp_tool.py:175` (env `BROWSER_CDP_URL` first, then `browser.cdp_url` in `config.yaml`), module note at `:8`; the dialog tool requires one of the three sources (`tools/browser_dialog_tool.py:10,44` — `"``/browser connect``, or ``browser.cdp_url`` in config.yaml. "`). Camofox honours both the transient connect and the persistent key (`tools/browser_camofox.py:98-130`, read at `:109` `str(browser_cfg.get("cdp_url", "") or "").strip()`); the TUI notes the same precedence at `tui_gateway/server.py:17617`. Cloud providers return their own `cdp_url` from `agent/browser_provider.py:28,99` and the provider plugins (`plugins/browser/browserbase/provider.py:214`, `plugins/browser/firecrawl/provider.py:115`, `plugins/browser/browser_use/provider.py:286`).
- **Inputs / options:** a `ws://`/`http://` CDP endpoint string.
- **Outputs / side effects:** the agent drives an existing browser (with its cookies and logins).
- **Config / env:** `browser.cdp_url`; env `BROWSER_CDP_URL`; slash `/browser connect`.
- **Edge cases / guards:** overrides `browser.engine`; attaching to a personal browser exposes every logged-in session to the agent.
- **Rebuild notes:** Optional attach-URL taking precedence over launch. A better version would verify the target's identity/profile before attaching and show which profile is in use.

### Browser → Real profile (use / autoclose / pin)  `id: config-a.browser.real_profile`
- **Surface:** Config | Security | Tool | Desktop app
- **Where:** Config page tab `Browser 25` → `USE REAL PROFILE` (`browser.use_real_profile`, switch, default `false`), `REAL PROFILE AUTOCLOSE` (`browser.real_profile_autoclose`, switch, default `false`), `REAL PROFILE PIN` (`browser.real_profile_pin`, string, default `""`). Also "Toggle in the desktop Settings → Browser section".
- **What it does:** Consent to browse with the user's REAL logins. When on, local browsing runs on a Hermes-managed **snapshot** of the user's active default-Chromium profile — cookies, logins and preferences copied in and re-synced when a fresh session launches — driven by Hermes' packaged Chromium. The autoclose key arms an "offer to close the browser" flow when the profile is locked; the pin fixes *which* source profile directory is snapshotted.
- **How it works:** `config_defaults.py:607-651`. Only the active profile (`Local State → profile.last_used`) is copied; the snapshot lives in a non-default dir (`~/.hermes/browser-profile/`) so it sidesteps Chrome 136+'s block on debugging the default profile and never contends with the user's running browser. Turning the switch back off **deletes** the snapshot store so copied credentials do not outlive consent. Only Chromium-family default browsers are supported (Chrome, Edge, Brave, Brave Origin, Chromium); a non-Chromium default (e.g. Firefox) fails closed with a clear message. Readers: `tools/browser_tool.py:1505-1516` ("Reads ``browser.use_real_profile`` (default False) on EVERY call — it is a" … `return bool(browser_cfg.get("use_real_profile", False))`), with veto messages at `:1165` ("browser.use_real_profile is on (Lightpanda cannot load a Chromium profile)"), `:1669` ("browser.use_real_profile is on, but browser.engine is set to "), `:1692`/`:1705` (default browser is not / is a non-Chromium family). It also gates the `browser_exec` `local` argument, which forces a real-profile local session even under a cloud backend (`tools/browser_use_cli.py:666,775-776` — `"local=true was requested but browser.use_real_profile is off. Enable it in config.yaml (browser.use_real_profile: true) or "`). Autoclose: `hermes_cli/browser_connect.py:809-820` (`"""Whether browser.real_profile_autoclose consent is on (config read).` → `bool(browser_cfg.get("real_profile_autoclose", False))`), the capability note at `:960` and the guidance `"browser.real_profile_autoclose to let Hermes offer to close it "` (`:977`). It does NOT auto-kill: on Windows a running Chrome/Edge/Brave locks its cookie DB deny-all, so when the profile is locked the snapshot always blocks and the agent asks first; only on approval does it run `hermes browser close-profile` (terminating the browser process tree bound to that profile, losing unsaved tabs) and retry — still locked afterwards means it stays blocked, with no loop and no auto-kill. No effect on macOS/Linux (copy-while-running works). Pin: `hermes_cli/browser_connect.py:763-799` (`"""Pinned source profile dir name from ``browser.real_profile_pin``.` → `pin = browser_cfg.get("real_profile_pin")`) with the fail-closed error `f"browser.real_profile_pin is set to '{pin}' but that profile "`.
- **Inputs / options:** boolean; boolean; profile directory name string (e.g. `Profile 2`).
- **Outputs / side effects:** a credential snapshot under `~/.hermes/browser-profile/` (deleted when consent is withdrawn); possibly a terminated browser process tree on approval.
- **Config / env:** `browser.use_real_profile`, `browser.real_profile_autoclose`, `browser.real_profile_pin`.
- **Edge cases / guards:** a pin naming a non-existent directory FAILS CLOSED with a fixable message rather than silently falling back to last-used — the point is that "last-used roulette" can hand the agent the wrong identity on a machine with work + personal profiles; incompatible with Lightpanda; on Windows the profile lock is the common failure.
- **Rebuild notes:** Copy-on-launch profile snapshot in a non-default directory, driven by a bundled browser, with consent-scoped lifetime. A better version would copy only the cookie jars for domains the task needs, and show the user exactly which identities were exposed.

### Browser → Allow unsafe evaluate / Restrict evaluate  `id: config-a.browser.evaluate_guards`
- **Surface:** Config | Security | Tool
- **Where:** Config page tab `Browser 25` → `ALLOW UNSAFE EVALUATE` (`browser.allow_unsafe_evaluate`, switch, default `false`) and `RESTRICT EVALUATE` (`browser.restrict_evaluate`, switch, default `false`).
- **What it does:** Governs `browser_console(expression=…)`. `restrict_evaluate` is an opt-in denylist blocking sensitive JS primitives (cookies / storage / clipboard / network / form values); `allow_unsafe_evaluate` is a legacy override that bypasses that denylist entirely.
- **How it works:** `config_defaults.py:652-653`. Readers are adjacent: `tools/browser_tool.py:4950` `is_truthy_value(cfg_get(cfg, "browser", "allow_unsafe_evaluate"), default=False)` (debug at `:4952`, semantics at `:4968` — "``browser.allow_unsafe_evaluate: true`` overrides it back off") and `:4974` `is_truthy_value(cfg_get(cfg, "browser", "restrict_evaluate"), default=False)` (debug `:4976`). The denylist is documented at `:4944` (a separate sensitive-primitive denylist applies "even if ``browser.restrict_evaluate`` is set"), `:5038` ("The denylist is opt-in (``browser.restrict_evaluate: true``) because it") and the block message `f"JavaScript primitive ({reason}) while browser.restrict_evaluate is "` … `"browser.restrict_evaluate: false in config.yaml to allow "` (`:5053-5056`). Users on a logged-in profile are the intended opt-in audience (`:4967`).
- **Inputs / options:** boolean ×2.
- **Outputs / side effects:** `browser_console` expressions run or are refused with a reason.
- **Config / env:** `browser.allow_unsafe_evaluate`, `browser.restrict_evaluate`.
- **Edge cases / guards:** both default off, so by default arbitrary JS runs in the page — enable `restrict_evaluate` when browsing with real logins; `allow_unsafe_evaluate` re-opens everything, so setting both is contradictory and the unsafe flag wins.
- **Rebuild notes:** AST/substring denylist over the evaluated expression with a legacy escape hatch. A better version would run the expression in an isolated world with an explicit capability grant per primitive.

### Browser → Dialog policy / Dialog timeout  `id: config-a.browser.dialog_policy`
- **Surface:** Config | Tool
- **Where:** Config page tab `Browser 25` → `DIALOG POLICY` (`browser.dialog_policy`, string, default `must_respond`) and `DIALOG TIMEOUT S` (`browser.dialog_timeout_s`, number, default `300`).
- **What it does:** How JavaScript dialogs (`alert`/`confirm`/`prompt`/`beforeunload`) are handled by the CDP supervisor, and the safety auto-dismiss deadline under `must_respond`.
- **How it works:** `config_defaults.py:654-661`. The CDP supervisor does dialog + frame detection over a persistent WebSocket and is active only when a CDP-capable backend is attached (Browserbase or local Chrome via `/browser connect`) — see `website/docs/developer-guide/browser-supervisor.md`. Both keys are read together by `_get_dialog_policy_config()` (`tools/browser_tool.py:620-653`): it imports `DEFAULT_DIALOG_POLICY`, `DEFAULT_DIALOG_TIMEOUT_S` and `_VALID_POLICIES` from `tools/browser_supervisor.py`, reads the raw config (`read_raw_config()`), coerces `policy = str(browser_cfg.get("dialog_policy") or DEFAULT_DIALOG_POLICY)`, logs `"Invalid browser.dialog_policy=%r; using default"` for anything outside `_VALID_POLICIES`, then parses `dialog_timeout_s` as a float, replacing `<= 0` and non-numeric values with the default; every failure path returns the two defaults. The tuple is passed to the supervisor at `:694` (`dialog_timeout_s=timeout_s`).
- **Inputs / options:** three policy strings — `must_respond` (default: the agent must answer the dialog), `auto_dismiss`, `auto_accept`; timeout in seconds (> 0).
- **Outputs / side effects:** dialogs are answered, dismissed or accepted; under `must_respond` an unanswered dialog is auto-dismissed after the timeout so the page cannot wedge.
- **Config / env:** `browser.dialog_policy`, `browser.dialog_timeout_s`.
- **Edge cases / guards:** plain string field — a typo falls back to `must_respond` with a debug log; the whole feature is inert without a CDP-capable backend; `auto_accept` will accept `confirm()` prompts a hostile page raises.
- **Rebuild notes:** CDP `Page.javascriptDialogOpening` handler with a policy switch and a watchdog. A better version would surface the dialog text to the user for a real decision on `must_respond`.

### Browser → Camofox identity (managed persistence / user id / session key / adopt existing tab)  `id: config-a.browser.camofox.identity`
- **Surface:** Config | Tool | Env
- **Where:** Config page tab `Browser 25` → `MANAGED PERSISTENCE` (`browser.camofox.managed_persistence`, switch, default `false`), `USER ID` (`browser.camofox.user_id`, string, `""`), `SESSION KEY` (`browser.camofox.session_key`, string, `""`), `ADOPT EXISTING TAB` (`browser.camofox.adopt_existing_tab`, switch, default `false`).
- **What it does:** Controls how Hermes identifies itself to a Camofox (Firefox-based, custom HTTP API) server: a stable profile-scoped userId mapped to a persistent Firefox profile, an externally managed identity when another app owns the visible browser, and whether to rehydrate an existing tab instead of creating a new one.
- **How it works:** `config_defaults.py:662-676`. `managed_persistence` → `tools/browser_camofox.py:201-203` (`"""… Controlled by ``browser.camofox.managed_persistence`` in config.yaml.` → `bool(_get_camofox_config().get("managed_persistence"))`), consulted again at `:399` and combined with an identity override at `:459` (`bool(camofox_cfg.get("managed_persistence")) or _camofox_identity_override(task_id, camofox_cfg)`). When false, each session gets a random userId (ephemeral). `user_id` / `session_key` are the optional externally managed identity, mirrored by the `CAMOFOX_USER_ID` / `CAMOFOX_SESSION_KEY` env vars (`env_vars_doc`). `adopt_existing_tab` → `tools/browser_camofox.py:245` (`bool(camofox_cfg.get("adopt_existing_tab"))`), used at `:346` (`if session.get("tab_id") or not session.get("adopt_existing_tab")`) and propagated into the session payload at `:397,406,414`; env `CAMOFOX_ADOPT_EXISTING_TAB`.
- **Inputs / options:** boolean; two strings; boolean.
- **Outputs / side effects:** which remote Firefox profile/tab the agent drives.
- **Config / env:** the four `browser.camofox.*` keys; env `CAMOFOX_URL`, `CAMOFOX_API_KEY`, `CAMOFOX_USER_ID`, `CAMOFOX_SESSION_KEY`, `CAMOFOX_ADOPT_EXISTING_TAB`.
- **Edge cases / guards:** Camofox is not a `browser.backend` value — it is selected by pointing `CAMOFOX_URL` at a server, and it always keeps the built-in browser tools (no CDP surface); a persistent userId means the browsing identity is durable across sessions.
- **Rebuild notes:** Stable-vs-ephemeral identity token sent to a remote browser service, plus tab reuse. A better version would namespace the identity per project so work and personal browsing never share a profile.

### Browser → Camofox loopback rewriting (rewrite loopback URLs / host alias)  `id: config-a.browser.camofox.loopback`
- **Surface:** Config | Tool
- **Where:** Config page tab `Browser 25` → `REWRITE LOOPBACK URLS` (`browser.camofox.rewrite_loopback_urls`, switch, default `false`) and `LOOPBACK HOST ALIAS` (`browser.camofox.loopback_host_alias`, string, default `host.docker.internal`).
- **What it does:** Docker-hosted Camofox opens page URLs from **inside** the container, so `localhost` means the container. When enabled, loopback page URLs (`localhost`, `127.0.0.1`, `::1`) are rewritten to a host alias while `CAMOFOX_URL` itself is left unchanged.
- **How it works:** `config_defaults.py:671-675`. Readers: `tools/browser_camofox.py:263` (`bool(camofox_cfg.get("rewrite_loopback_urls"))`) and `:270` (`or str(camofox_cfg.get("loopback_host_alias") or "").strip()`); both seeded in `cli.py:471-472`.
- **Inputs / options:** boolean; hostname string.
- **Outputs / side effects:** the URL the remote browser actually navigates to differs from the one the agent asked for.
- **Config / env:** `browser.camofox.rewrite_loopback_urls`, `browser.camofox.loopback_host_alias`.
- **Edge cases / guards:** the alias must resolve inside the container (`host.docker.internal` needs `--add-host` on Linux); rewriting silently changes the origin, which can break cookie/CORS expectations.
- **Rebuild notes:** URL host substitution applied only to page navigations. A better version would detect the container's gateway address automatically instead of hardcoding an alias.

### Browser → Extension control (enabled / developer mode)  `id: config-a.browser.extension_control`
- **Surface:** Config | Security | Gateway/Telegram | API
- **Where:** Config page tab `Browser 25` → `ENABLED` (`browser.extension_control.enabled`, switch, default `false`) and `DEVELOPER MODE` (`browser.extension_control.developer_mode`, switch, default `false`).
- **What it does:** Opens the authenticated browser-extension controller lane: an extension registered through the gateway can become the exact controller for a session's `browser_*` tools (fail-closed once bound). Developer mode additionally unlocks the privileged capabilities `browser_cdp` and `browser_evaluate`.
- **How it works:** `config_defaults.py:677-687`. Gate checks: `tui_gateway/methods_browser_control.py:145` ("the ``browser.extension_control.enabled`` feature flag is on") with the refusal string `"browser.extension_control.enabled is not set"` (`:161`); router default at `tools/browser_extension_router.py:13` ("default: ``browser.extension_control.enabled`` is false unless explicitly"); API server gating at `gateway/platforms/api_server.py:2225,3375,3740` ("Reads ``browser.extension_control.enabled`` from the global config") and `:3891` (the registration route body). Developer mode: `gateway/browser_control_broker.py:111` (the capability is available only when the extension "runs in Developer Mode (``browser.extension_control.developer_mode``) AND" …), read at `:151-173` (`extension_control.get("developer_mode", False) is True`) and echoed to the client at `api_server.py:3382` (`"developer_mode": self._browser_control_developer_mode()`).
- **Inputs / options:** boolean ×2.
- **Outputs / side effects:** an external extension gains control of the session's browser tools; with developer mode, raw CDP and JS evaluation.
- **Config / env:** `browser.extension_control.enabled`, `browser.extension_control.developer_mode`.
- **Edge cases / guards:** local API registration additionally requires the API-server bearer key; binding is fail-closed (once an extension is the controller, the built-in driver is not used); `developer_mode` is described as "never negotiable without it" — the privileged capabilities cannot be obtained any other way; strict `is True` comparison on developer mode.
- **Rebuild notes:** Capability-scoped controller registration behind a bearer key and two flags. A better version would show the user which extension holds control and let them revoke it from the dashboard.

## Voice (14 fields)

All 14 keys live under `voice:`. The neighbouring `wake_word:` block ("Hey Hermes" hands-free hotword, `config_defaults.py:1984-2026`) is a separate `Wake_word` tab and belongs to a sibling shard.

### Voice → Record key  `id: config-a.voice.record_key`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Voice 14` → label `RECORD KEY` (string, default `ctrl+b`). Shown by `/voice status`.
- **What it does:** The push-to-talk key that starts/stops voice recording in the CLI and TUI.
- **How it works:** `config_defaults.py:1967`. `hermes_cli/voice.py:88-106` is a shape-safe lookup (`"""Shape-safe ``cfg.voice.record_key`` lookup.` — a naive `.get("voice", {}).get("record_key")` chain raises when `voice` is not a dict, `:93`), `:110` coerces it into prompt_toolkit's `c-x` / `a-x` format, and `:198` renders it for `/voice status` in CLI-friendly form. `cli.py:19482` wires the binding ("Voice push-to-talk key: configurable via config.yaml (voice.record_key)"), warns `"voice.record_key %r uses a TUI-only modifier (super/win); "` (`:19507`), and re-reads it when the key changes mid-session (`:19519`, Copilot round-13 on #19835); the label cache is populated from the raw value at `cli.py:7390`. The TUI reads it at `tui_gateway/server.py:16862` (`_voice_cfg_dict().get("record_key")`) and echoes it in voice state payloads at `:17334,17392,17414`. Tip: `hermes_cli/tips.py:325`.
- **Inputs / options:** a key description string such as `ctrl+b`, `alt+v`, `super+space` (super/win is TUI-only).
- **Outputs / side effects:** the keybinding registered in the prompt/TUI input layer; the hint shown in `/voice status`.
- **Config / env:** `voice.record_key`.
- **Edge cases / guards:** super/win modifiers warn and do not bind in the CLI; a malformed `voice` section is tolerated by the shape-safe reader.
- **Rebuild notes:** One key-description string parsed into the input layer's binding format, re-read on change. A better version would validate the binding against the terminal's real capabilities at set time.

### Voice → Submit mode  `id: config-a.voice.submit_mode`
- **Surface:** Config | TUI
- **Where:** Config page tab `Voice 14` → label `SUBMIT MODE` (string, default `direct`).
- **What it does:** In the TUI, whether a finished transcription is submitted immediately (`direct`) or left in the input box as an editable draft (`draft`).
- **How it works:** `config_defaults.py:1968`. Validated by the config validator: `hermes_cli/config.py:2295-2306` — the section header comment `# ── voice.submit_mode: direct | draft ──…`, the presence check `if isinstance(voice_cfg, dict) and "submit_mode" in voice_cfg` (`:2297`), the read at `:2298`, and the error pair `f"voice.submit_mode must be 'direct' or 'draft', got {submit_mode!r}"` / `"Set voice.submit_mode to direct (submit immediately) or draft (edit before sending)"` (`:2305-2306`).
- **Inputs / options:** two strings — `direct`, `draft`.
- **Outputs / side effects:** the transcript is sent, or placed in the editor.
- **Config / env:** `voice.submit_mode`.
- **Edge cases / guards:** an invalid value is a hard config-validation error (not a silent fallback); it is a plain string field in the form, so the validator is the only guard.
- **Rebuild notes:** Two-branch post-transcription action. A better version would auto-choose draft when the transcript's confidence is low.

### Voice → Max recording seconds  `id: config-a.voice.max_recording_seconds`
- **Surface:** Config | CLI | TUI | Tool
- **Where:** Config page tab `Voice 14` → label `MAX RECORDING SECONDS` (number, default `120`).
- **What it does:** Hard cap on a single recording's length.
- **How it works:** `config_defaults.py:1969`. `tools/voice_mode.py:850` ("Hard cap on total recording length, wired from voice.max_recording_seconds"), `:861` (applied by the CLI before each recording), `:985` ("3. Hard cap on total recording length (voice.max_recording_seconds)"). CLI read: `cli.py:15173,15180` (`_max_rec = voice_cfg.get("max_recording_seconds")`); TUI read: `tui_gateway/server.py:17530,17534` (`max_rec = voice_cfg.get("max_recording_seconds")`). `hermes_cli/voice.py:460` notes any non-positive or non-numeric value is ignored.
- **Inputs / options:** positive integer seconds.
- **Outputs / side effects:** recording stops and the audio captured so far is transcribed.
- **Config / env:** `voice.max_recording_seconds`.
- **Edge cases / guards:** non-positive/non-numeric values fall back to the default; long caps mean long uploads and higher per-minute STT billing.
- **Rebuild notes:** Timer that stops the capture stream. A better version would chunk long recordings into streamed partial transcriptions instead of one hard cut.

### Voice → Auto TTS  `id: config-a.voice.auto_tts`
- **Surface:** Config | Gateway/Telegram | CLI
- **Where:** Config page tab `Voice 14` → label `AUTO TTS` (switch, default `false`). Runtime override: `/voice on|tts`.
- **What it does:** Global default for speaking replies aloud without an explicit per-session opt-in.
- **How it works:** `config_defaults.py:1970`. `gateway/run.py:8140-8146` pushes the global default onto the adapter at gateway startup (`(_full_cfg.get("voice") or {}).get("auto_tts", False)` → `_auto_tts_default`, documented at `:8109,8127`) and re-syncs on connect (`:24051`). The adapter resolves per message: an explicit `/voice on|tts` opt-in wins, otherwise the global default (`gateway/platforms/base.py:3241,3570-3572,6661`). CLI read: `cli.py:15702` (`if voice_config.get("auto_tts", False):`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** every reply also produces synthesized audio (and the TTS provider's cost/latency).
- **Config / env:** `voice.auto_tts`.
- **Edge cases / guards:** a session-level `/voice` toggle overrides the global default in both directions; the value is pushed at gateway start so a change needs a reconnect/restart to reach adapters.
- **Rebuild notes:** Global default merged with a per-session override at send time. A better version would speak only replies above a usefulness threshold (or when the user's last input was voice).

### Voice → Client direct  `id: config-a.voice.client_direct`
- **Surface:** Config | Desktop app | Web dashboard
- **Where:** Config page tab `Voice 14` → label `CLIENT DIRECT` (switch, default `true`).
- **What it does:** Lets desktop/remote clients call the profile's STT/TTS providers **directly** — config plus key fetched over the authenticated REST channel at voice-session start — instead of relaying audio through the gateway. `false` = always relay.
- **How it works:** `config_defaults.py:1971-1976`. Gate documented at `hermes_cli/web_server.py:5414` ("Gate: ``voice.client_direct`` in config.yaml (default true)") and `tools/voice_client_config.py:28` ("Config gate: ``voice.client_direct`` (config.yaml, default ``true``)"), read at `:62` (`value = voice_cfg.get("client_direct", True)`); when off the helper returns the relay decision `_relay("voice.client_direct disabled")` (`:323`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** the client receives provider config **and an API key** over REST and talks to the STT/TTS provider itself; audio does not traverse the gateway.
- **Config / env:** `voice.client_direct`.
- **Edge cases / guards:** direct mode hands a provider credential to the client process — set `false` when the client is less trusted than the gateway host; relaying costs an extra hop in both directions.
- **Rebuild notes:** Capability negotiation at session start returning either provider credentials or a relay endpoint. A better version would mint a short-lived scoped token instead of shipping the real key.

### Voice → Beep enabled / Beep volume / Thinking sound  `id: config-a.voice.sounds`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Voice 14` → `BEEP ENABLED` (`voice.beep_enabled`, switch, default `true`), `BEEP VOLUME` (`voice.beep_volume`, number, default `0.3`), `THINKING SOUND` (`voice.thinking_sound`, switch, default `true`).
- **What it does:** Record start/stop beeps in CLI voice mode, their amplitude, and a calm ambient bubble sound played while the agent works during a voice chat (its volume follows `beep_volume`).
- **How it works:** `config_defaults.py:1977-1979`. Beeps: `hermes_cli/voice.py:261-270` (`"""CLI parity: voice.beep_enabled in config.yaml (default True)."""` → `is_truthy_value(voice_cfg.get("beep_enabled", True), default=True)`), same read in `cli.py:15658`. Volume: `tools/voice_mode.py:447-459` (`"""Read ``voice.beep_volume`` from config.yaml; clamps to 0.0-1.0.` → `raw = voice_cfg.get("beep_volume", _DEFAULT_BEEP_VOLUME)`). Thinking sound: `tools/voice_mode.py:538` ("volume-scaled by voice.beep_volume, gated by voice.thinking_sound (default"), `:578-586` (`"""Config gate: ``voice.thinking_sound`` (default True)."""` → `is_truthy_value(voice_cfg.get("thinking_sound", True), default=True)`); the TUI gates it at `tui_gateway/server.py:12989` ("voice.thinking_sound config-gates it; macOS TCC handled inside") and the CLI stops it as soon as the turn ends (`cli.py:17223`).
- **Inputs / options:** boolean; float 0.0–1.0 (clamped); boolean.
- **Outputs / side effects:** audio played on the local output device.
- **Config / env:** `voice.beep_enabled`, `voice.beep_volume`, `voice.thinking_sound`.
- **Edge cases / guards:** volume is clamped to 0.0–1.0; the default 0.3 preserves the previously hardcoded level; macOS microphone/TCC permission handling happens inside the sound path.
- **Rebuild notes:** Three small audio cues behind two booleans and one gain. A better version would duck the ambient sound when TTS starts instead of relying on a fixed gain.

### Voice → Silence threshold / Silence duration  `id: config-a.voice.silence`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Voice 14` → `SILENCE THRESHOLD` (`voice.silence_threshold`, number, default `200`) and `SILENCE DURATION` (`voice.silence_duration`, number, default `3.0`).
- **What it does:** Voice-activity auto-stop: RMS below `silence_threshold` (scale 0–32767) counts as silence, and `silence_duration` seconds of continuous silence ends the recording.
- **How it works:** `config_defaults.py:1980-1981`. Read as a pair in both surfaces: `cli.py:15165-15166` (`_threshold = voice_cfg.get("silence_threshold")`, `_duration = voice_cfg.get("silence_duration")`) and `tui_gateway/server.py:17474-17475` (`threshold = voice_cfg.get("silence_threshold")`, `duration = voice_cfg.get("silence_duration")`).
- **Inputs / options:** integer RMS 0–32767; float seconds.
- **Outputs / side effects:** recording ends automatically and transcription starts.
- **Config / env:** `voice.silence_threshold`, `voice.silence_duration`.
- **Edge cases / guards:** a noisy room needs a higher threshold or the recording never auto-stops; a very low duration truncates natural pauses mid-sentence.
- **Rebuild notes:** RMS window comparison with a hysteresis timer. A better version would use the same VAD model as the local STT path instead of a raw amplitude gate.

### Voice → Barge-in (enable / grace seconds / threshold multiplier)  `id: config-a.voice.barge_in`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Voice 14` → `BARGE IN` (`voice.barge_in`, switch, default `true`), `BARGE IN GRACE SECONDS` (`voice.barge_in_grace_seconds`, number, default `0.5`), `BARGE IN THRESHOLD MULTIPLIER` (`voice.barge_in_threshold_multiplier`, number, default `3.0`).
- **What it does:** Interrupts the agent and stops TTS when the user starts talking. The grace window suppresses false trips right after playback starts (the onset transient) — the mic itself stays live for the whole turn. The multiplier sets the speech trigger as `quiet-room floor × multiplier`, where the floor is calibrated BEFORE playback so it is never measured against speaker bleed.
- **How it works:** `config_defaults.py:1982-1984`. Enable read: `cli.py:15526` (`if not (isinstance(voice_cfg, dict) and voice_cfg.get("barge_in", True))`) and `tui_gateway/server.py:12981,16591,16839` (`_voice_mode_enabled() and _voice_cfg_dict().get("barge_in", True)`). Grace: `cli.py:15539` and `tui_gateway/server.py:16703` — both `int(float(cfg.get("barge_in_grace_seconds", 0.5)) * 1000)` (converted to ms). Multiplier: `cli.py:15535` and `tui_gateway/server.py:16699` — `float(cfg.get("barge_in_threshold_multiplier", 0) or 0)` (note the read-site default is `0`, i.e. "no multiplier", while `DEFAULT_CONFIG` supplies `3.0`).
- **Inputs / options:** boolean; float seconds; float multiplier.
- **Outputs / side effects:** TTS playback stops and the agent turn is interrupted.
- **Config / env:** `voice.barge_in`, `voice.barge_in_grace_seconds`, `voice.barge_in_threshold_multiplier`.
- **Edge cases / guards:** speaker bleed on laptop microphones is the classic false-trigger source — hence the pre-playback floor calibration and the grace window; a multiplier of 0 in a hand-written config disables the threshold logic.
- **Rebuild notes:** Calibrate a noise floor before playback, arm after a grace delay, trip on `floor × multiplier`. A better version would use acoustic echo cancellation so the multiplier heuristic is unnecessary.

### Voice → Stop phrases  `id: config-a.voice.stop_phrases`
- **Surface:** Config | CLI | TUI
- **Where:** Config page tab `Voice 14` → label `STOP PHRASES` (list, default `["stop"]`, placeholder `comma-separated values`).
- **What it does:** Saying EXACTLY one of these phrases (and nothing else) ends the voice chat instead of being sent to the agent.
- **How it works:** `config_defaults.py:1985-1988`. `tools/voice_mode.py:1271-1280` (`"""Return the configured ``voice.stop_phrases`` list (default: ("stop",)).` → `raw = voice_cfg.get("stop_phrases", DEFAULT_VOICE_STOP_PHRASES)`), semantics at `:1301` ("the agent. Configure via ``voice.stop_phrases`` in config.yaml") and the hint sourced from the first entry at `:1387`. The CLI shows the spoken-stop hint from the first entry (`cli.py:15720`) and applies the same exact-match semantics to *typed* input so longer typed messages are unaffected (`cli.py:15740`); the TUI renders custom phrases in its hint (`tui_gateway/server.py:17362`); `hermes_cli/voice.py:464` documents the bare-phrase behaviour.
- **Inputs / options:** list of phrases; matching is case-insensitive with surrounding punctuation ignored; `[]` disables the feature.
- **Outputs / side effects:** the voice session ends; the phrase is not sent to the model.
- **Config / env:** `voice.stop_phrases`.
- **Edge cases / guards:** exact match only — "stop please" is sent to the agent; a common word like "stop" inside a longer sentence is safe for the same reason.
- **Rebuild notes:** Normalised exact-match set checked before dispatch. A better version would accept a short wake-style phrase model so "hermes stop" also works without false positives.

## Text-to-Speech (30 fields)

The `Text-to-Speech` tab flattens `tts:` and its per-provider sub-objects. Every provider additionally supports an optional `max_text_length:` per-request input-character cap that is **not** seeded in `DEFAULT_CONFIG` and therefore not a schema field — omit it to use the provider's documented limit: OpenAI 4096, xAI 15000, MiniMax 10000, ElevenLabs 5k–40k (model-aware), Gemini 32000, Edge 5000, Mistral 4000, NeuTTS/KittenTTS 2000 (`config_defaults.py:1818-1822`). The `tts.providers.<name>` command-type registry (PR #17843) is a dict and likewise not a schema field.

### Text-to-Speech → Provider  `id: config-a.tts.provider`
- **Surface:** Config | Tool | CLI
- **Where:** Config page tab `Text-to-Speech 30` → label `PROVIDER`, description `Text-to-speech provider` (select, default `edge`). Also set by `hermes tools` (the TTS picker row).
- **What it does:** Chooses which backend services every `text_to_speech` call.
- **How it works:** Select override at `hermes_cli/web_server.py:1328-1332`; declared at `config_defaults.py:1824-1826` where the comment lists the pinnable values `"edge" (free) | "elevenlabs" (premium) | "openai" | "xai" | "minimax" | "mistral" | "gemini" | "deepinfra" | "neutts" (local) | "kittentts" (local) | "piper" (local)`. Resolution: `tools/tts_tool.py:650-664` `_get_provider()` — `(tts_config.get("provider") or DEFAULT_PROVIDER).lower().strip()`, with the docstring "Inference credentials do not imply consent to paid speech generation. Users opt into cloud TTS by setting ``tts.provider`` (normally through ``hermes tools``); otherwise the historical Edge backend remains active"; the managed selection `tts.provider: nous` ("Nous Subscription") is serviced by the OpenAI implementation, routed through the managed openai-audio gateway by `_resolve_openai_audio_client_config`. The provider abstraction is `agent/tts_provider.py:8-10,75,248` (a stable short identifier plus the `tts.providers.<name>.voice_compatible` mirror). The picker writes it: `hermes_cli/tools_config.py:3527` ("Selecting this row writes ``tts.provider: <name>``"), `:4675`, `:4699` (`_set_selection("tts", "provider", provider["tts_provider"])`), and equality-checks it at `:4154,4182`.
- **Inputs / options:** the ten select values served by the schema — `edge`, `elevenlabs`, `openai`, `xai`, `minimax`, `mistral`, `gemini`, `neutts`, `kittentts`, `piper`. The config comment additionally documents `deepinfra` (which has its own settings block below) and the managed value `nous`.
- **Outputs / side effects:** which HTTP API or local model synthesizes audio; which per-provider sub-block below is consulted.
- **Config / env:** `tts.provider`; each provider's own API key env var (`ELEVENLABS_API_KEY`, `DEEPINFRA_API_KEY`, …).
- **Edge cases / guards:** the dropdown omits `deepinfra` and `nous` even though both are supported — set those in the YAML view; picking a cloud provider may trigger a lazy `pip install` gated by `security.allow_lazy_installs`.
- **Rebuild notes:** One provider id selecting an implementation class, defaulting to a free local/Edge backend. A better version would probe credentials and fall back automatically with an explicit notice.

### Text-to-Speech → Edge voice  `id: config-a.tts.edge.voice`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → label `VOICE` under the Edge block (`tts.edge.voice`, string, default `en-US-AriaNeural`).
- **What it does:** Picks the Microsoft Edge (free) neural voice.
- **How it works:** `config_defaults.py:1827-1830`; the comment names popular alternatives — `AriaNeural`, `JennyNeural`, `AndrewNeural`, `BrianNeural`, `SoniaNeural`. The OpenClaw migration maps its edge voice into `tts_data["edge"] = {"voice": edge_voice.strip()}` (`optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py:1942`).
- **Inputs / options:** any Edge TTS voice id string (locale-prefixed, e.g. `en-GB-SoniaNeural`).
- **Outputs / side effects:** the timbre/locale of generated speech.
- **Config / env:** `tts.edge.voice`. Edge needs no API key (hence "free").
- **Edge cases / guards:** an unknown voice id fails at synthesis time; Edge's documented per-request cap is 5000 characters.
- **Rebuild notes:** Pass the voice id to the Edge TTS websocket call. A better version would list available voices in the picker with audio previews.

### Text-to-Speech → ElevenLabs voice id / model id  `id: config-a.tts.elevenlabs`
- **Surface:** Config | Tool | Web dashboard
- **Where:** Config page tab `Text-to-Speech 30` → `VOICE ID` (`tts.elevenlabs.voice_id`, string, default `pNInz6obpgDQGcFmaJgB` — "Adam") and `MODEL ID` (`tts.elevenlabs.model_id`, string, default `eleven_multilingual_v2`).
- **What it does:** Selects the ElevenLabs voice and synthesis model.
- **How it works:** `config_defaults.py:1831-1834`. Readers: `tools/tts_tool.py:1774-1775` (`voice_id = el_config.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID)`, `model_id = el_config.get("model_id", DEFAULT_ELEVENLABS_MODEL_ID)`), the streaming path `tools/tts_streaming.py:242,245` (`self.section.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID)`, `self.section.get("model_id", DEFAULT_ELEVENLABS_STREAMING_MODEL_ID)` — note streaming has its own default model), the provider-level helper `tools/tts_tool.py:447` (`(prov_cfg or {}).get("model_id") or DEFAULT_ELEVENLABS_MODEL_ID`) and the client-direct payload `tools/voice_client_config.py:274` (`el.get("model_id") or tts.DEFAULT_ELEVENLABS_MODEL_ID`). The dashboard offers a voice dropdown fed by `hermes_cli/web_server.py:5469` ("The desktop UI uses this for the ``tts.elevenlabs.voice_id`` dropdown"), built from `{"voice_id": …, "name": …}` records (`web_server.py:5437,5535-5540`). `hermes_cli/config.py:2824-2825` notes the config merge recurses, so a user who overrides only `tts.elevenlabs.voice_id` keeps the default `tts.elevenlabs.model_id`.
- **Inputs / options:** an ElevenLabs voice id string; a model id string (e.g. `eleven_multilingual_v2`).
- **Outputs / side effects:** the ElevenLabs API request body.
- **Config / env:** `tts.elevenlabs.voice_id`, `tts.elevenlabs.model_id`; env `ELEVENLABS_API_KEY`.
- **Edge cases / guards:** the per-request character cap is model-aware (5k–40k); the streaming path may use a different default model than the batch path.
- **Rebuild notes:** Two ids in the request body plus a voices-list endpoint for the picker. A better version would validate the voice id against the account's voices at save time.

### Text-to-Speech → OpenAI model / voice  `id: config-a.tts.openai`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.openai.model`, string, default `gpt-4o-mini-tts`) and `VOICE` (`tts.openai.voice`, string, default `alloy`).
- **What it does:** Selects the OpenAI speech model and voice (also used for the managed "Nous Subscription" route).
- **How it works:** `config_defaults.py:1835-1841`. The comment enumerates the voices available on `gpt-4o-mini-tts`: `alloy`, `ash`, `ballad`, `cedar`, `coral`, `echo`, `fable`, `marin`, `nova`, `onyx`, `sage`, `shimmer`, `verse` — and notes the `tts-1` era stopped at `alloy`/`echo`/`fable`/`onyx`/`nova`/`shimmer`. Readers documented on the synthesis function: `tools/tts_tool.py:1842-1843` ("model: Model id. When None, reads ``tts.openai.model``." / "voice: Voice id. When None, reads ``tts.openai.voice``."). A user's `tts.openai.model` set for *direct* OpenAI (e.g. `tts-1-hd`) is specifically called out at `:218` because the managed route supports a different model set.
- **Inputs / options:** model id string (e.g. `gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`); one of the 13 voice names above.
- **Outputs / side effects:** the OpenAI `/audio/speech` request.
- **Config / env:** `tts.openai.model`, `tts.openai.voice`; `OPENAI_API_KEY` (or the managed openai-audio gateway when `tts.provider: nous`).
- **Edge cases / guards:** a `tts-1`-era voice name on a `gpt-4o-mini-tts` request (and vice versa) can fail; OpenAI's documented per-request cap is 4096 characters.
- **Rebuild notes:** Model+voice pair in the speech request. A better version would gate the voice list on the selected model in the UI.

### Text-to-Speech → Gemini model / voice / audio tags / persona prompt file  `id: config-a.tts.gemini`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.gemini.model`, string, default `gemini-2.5-flash-preview-tts`), `VOICE` (`tts.gemini.voice`, string, default `Kore`), `AUDIO TAGS` (`tts.gemini.audio_tags`, switch, default `false`), `PERSONA PROMPT FILE` (`tts.gemini.persona_prompt_file`, string, default `""`).
- **What it does:** Gemini TTS model and voice, plus two expressiveness controls: an LLM rewrite pass that inserts freeform square-bracket audio tags into the TTS script, and an optional local file of performance direction.
- **How it works:** `config_defaults.py:1842-1856`. `audio_tags`: when true, Gemini 3.1 TTS uses a **hidden auxiliary-model rewrite pass** to insert the tags; visible chat replies are unchanged — read at `tools/tts_tool.py:2494` (`raw = gemini_config.get("audio_tags")`). `persona_prompt_file`: an optional local Markdown/text file with performance direction which may include `AUDIO PROFILE`, `SCENE`, `DIRECTOR'S NOTES`, `SAMPLE CONTEXT` and either a `{transcript}` placeholder or no transcript section (Hermes appends the live transcript when absent) — read at `tools/tts_tool.py:2456` (`raw = gemini_config.get("persona_prompt_file")`).
- **Inputs / options:** model id string; voice name string (default `Kore`); boolean; filesystem path string.
- **Outputs / side effects:** an extra auxiliary LLM call per utterance when `audio_tags` is on; the persona text is prepended to the TTS prompt.
- **Config / env:** the four `tts.gemini.*` keys; the Gemini API key env var.
- **Edge cases / guards:** `audio_tags` costs an additional model call per spoken message; a missing persona file path is ignored/errors at synthesis; Gemini's documented per-request cap is 32000 characters.
- **Rebuild notes:** Optional prompt-rewrite stage plus a prompt-prefix file feeding a TTS model that accepts direction. A better version would cache the rewrite for repeated phrases and expose the tag vocabulary in the UI.

### Text-to-Speech → xAI voice / language / speed / auto speech tags  `id: config-a.tts.xai.voice`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `VOICE ID` (`tts.xai.voice_id`, string, default `eve`), `LANGUAGE` (`tts.xai.language`, string, default `en`), `SPEED` (`tts.xai.speed`, number, default `1.0`), `AUTO SPEECH TAGS` (`tts.xai.auto_speech_tags`, switch, default `false`).
- **What it does:** xAI voice selection and delivery: which voice, which language, playback speed, and whether to insert expressive audio tags via an LLM rewrite.
- **How it works:** `config_defaults.py:1857-1865`. `voice_id` — a built-in name or a custom voice id (the comment links `https://docs.x.ai/developers/model-capabilities/audio/custom-voices`), read at `tools/tts_tool.py:2120` (`str(xai_config.get("voice_id", DEFAULT_XAI_VOICE_ID)).strip() or DEFAULT_XAI_VOICE_ID`) and in the streaming path at `tools/tts_streaming.py:452,462`; the setup wizard writes it (`hermes_cli/setup.py:1320` — `config.setdefault("tts", {}).setdefault("xai", {})["voice_id"] = voice_id.strip()`). `language` is a BCP-47 code (`"en"`, `"pt-BR"`) or `"auto"`. `speed` is 0.7–1.5 playback speed and `tts.xai.speed` overrides a global `tts.speed` (`tools/tts_tool.py:2128`). `auto_speech_tags` is read with a legacy alias: `xai_config.get("auto_speech_tags", xai_config.get("speech_tags"))` (`tools/tts_tool.py:2125`).
- **Inputs / options:** voice id string; BCP-47 language or `auto`; float 0.7–1.5; boolean (legacy key `speech_tags` still honoured).
- **Outputs / side effects:** the xAI speech request body; an extra rewrite call when tags are on.
- **Config / env:** the four keys; the xAI API key env var.
- **Edge cases / guards:** speeds outside 0.7–1.5 are outside the documented range; xAI's documented per-request cap is 15000 characters.
- **Rebuild notes:** Voice/lang/speed triple plus an optional tag-insertion pass. A better version would expose the tag vocabulary and preview the effect.

### Text-to-Speech → xAI audio format (streaming latency / sample rate / bit rate)  `id: config-a.tts.xai.audio_format`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `OPTIMIZE STREAMING LATENCY` (`tts.xai.optimize_streaming_latency`, number, default `0`), `SAMPLE RATE` (`tts.xai.sample_rate`, number, default `24000`), `BIT RATE` (`tts.xai.bit_rate`, number, default `128000`).
- **What it does:** Audio-quality/latency trade-offs for the xAI backend.
- **How it works:** `config_defaults.py:1862-1864`. `optimize_streaming_latency` is 0–2, xAI-specific, trading quality for lower latency — read at `tools/tts_tool.py:2140-2144` (with a fallback to a top-level `tts_config.get("optimize_streaming_latency")`) and written into the payload at `:2201`. `sample_rate` (22050 / 24000 / 44100 / 48000) at `:2122` (`int(xai_config.get("sample_rate", DEFAULT_XAI_SAMPLE_RATE))`) and `bit_rate` (MP3 bitrate; only applies when `codec=mp3`) at `:2123`; both land in the request's `output_format` object (`:2186,2188`).
- **Inputs / options:** integer 0–2; integer sample rate from {22050, 24000, 44100, 48000}; integer bits/second.
- **Outputs / side effects:** the `output_format` block of the xAI request; audio fidelity and first-byte latency.
- **Config / env:** the three keys.
- **Edge cases / guards:** `bit_rate` is ignored unless the codec is MP3; unusual sample rates may be rejected by the API.
- **Rebuild notes:** Pass-through audio-format parameters. A better version would pick the format from the playback device's capabilities.

### Text-to-Speech → Mistral model / voice id  `id: config-a.tts.mistral`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.mistral.model`, string, default `voxtral-mini-tts-2603`) and `VOICE ID` (`tts.mistral.voice_id`, string, default `c69964a6-ab8b-4f8a-9465-ec0925096ec8` — "Paul - Neutral").
- **What it does:** Selects the Mistral (Voxtral) TTS model and voice.
- **How it works:** `config_defaults.py:1866-1869` (the default voice id is annotated `# Paul - Neutral`). The provider block is consumed by the generic per-provider section reader in `tools/tts_tool.py` (the same `section.get("voice_id"…)` / model pattern the ElevenLabs and xAI paths use).
- **Inputs / options:** model id string; voice UUID string.
- **Outputs / side effects:** the Mistral speech request.
- **Config / env:** `tts.mistral.model`, `tts.mistral.voice_id`; the Mistral API key env var.
- **Edge cases / guards:** Mistral's documented per-request cap is 4000 characters; the `mistralai` PyPI package was quarantined after a malicious 2.4.6 release on 2026-05-12 (see the STT provider note), which is why `mistral` is missing from the STT provider dropdown.
- **Rebuild notes:** Model + voice UUID in the request. A better version would fetch the account's voice catalog for the picker.

### Text-to-Speech → MiniMax model / voice id  `id: config-a.tts.minimax`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.minimax.model`, string, default `speech-02-hd`) and `VOICE ID` (`tts.minimax.voice_id`, string, default `English_expressive_narrator`).
- **What it does:** Selects the MiniMax speech model and voice.
- **How it works:** `config_defaults.py:1870-1873`. MiniMax is region-bound: `tools/tts_tool.py:668-680` defines the frozen `_MiniMaxTTSRuntime` dataclass carrying `region`, `endpoint`, `credential_source` and an `api_key` excluded from `repr` "so diagnostics cannot expose it accidentally".
- **Inputs / options:** model id string; voice name string.
- **Outputs / side effects:** the MiniMax speech request against the resolved regional endpoint.
- **Config / env:** `tts.minimax.model`, `tts.minimax.voice_id`; the MiniMax API key env var (region-specific).
- **Edge cases / guards:** MiniMax's documented per-request cap is 10000 characters; the wrong regional credential fails at the endpoint.
- **Rebuild notes:** Model + voice with a region-resolved endpoint and a repr-safe credential holder. A better version would auto-detect the account's region from the key.

### Text-to-Speech → KittenTTS model / voice  `id: config-a.tts.kittentts`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.kittentts.model`, string, default `KittenML/kitten-tts-nano-0.8-int8`) and `VOICE` (`tts.kittentts.voice`, string, default `Jasper`).
- **What it does:** Local (offline) TTS via KittenTTS — which quantised model to load and which speaker to use.
- **How it works:** `config_defaults.py:1874-1877`; the model comment gives the size ladder — `nano 25MB; micro 41MB; mini 80MB`.
- **Inputs / options:** a HuggingFace model repo id; a voice/speaker name.
- **Outputs / side effects:** downloads the model on first use (subject to `security.allow_lazy_installs` for the Python package) and synthesizes locally — no network per utterance.
- **Config / env:** `tts.kittentts.model`, `tts.kittentts.voice`.
- **Edge cases / guards:** NeuTTS/KittenTTS documented per-request cap is 2000 characters; larger models trade RAM for quality.
- **Rebuild notes:** Local ONNX/torch model id + speaker id. A better version would ship a size/quality picker with measured RTF (real-time factor) per model.

### Text-to-Speech → NeuTTS (reference audio / reference text / model / device)  `id: config-a.tts.neutts`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `REF AUDIO` (`tts.neutts.ref_audio`, string, `""`), `REF TEXT` (`tts.neutts.ref_text`, string, `""`), `MODEL` (`tts.neutts.model`, string, default `neuphonic/neutts-air-q4-gguf`), `DEVICE` (`tts.neutts.device`, string, default `cpu`).
- **What it does:** Local voice-cloning TTS: a reference audio clip plus its transcript define the voice; the model repo and compute device define how it runs.
- **How it works:** `config_defaults.py:1878-1883`. Readers: `tools/tts_tool.py:2823` (`ref_audio = neutts_config.get("ref_audio", "") or _default_neutts_ref_audio()`), `:2824` (`ref_text = neutts_config.get("ref_text", "") or _default_neutts_ref_text()`) — empty means the bundled default voice — and `:2826` (`device = neutts_config.get("device", "cpu")`). The TUI's prompt tooling formats reference values as `@file:` references (`tui_gateway/methods_prompt.py:1361`).
- **Inputs / options:** path to a reference audio file; path to its transcript; a HuggingFace model repo id; device string `cpu` | `cuda` | `mps`.
- **Outputs / side effects:** local synthesis in the cloned voice; model weights downloaded on first use.
- **Config / env:** the four `tts.neutts.*` keys.
- **Edge cases / guards:** cloning someone's voice from a reference clip has obvious consent implications; `cuda`/`mps` require the matching runtime; per-request cap 2000 characters.
- **Rebuild notes:** Reference-conditioned local TTS with a device selector and bundled defaults. A better version would verify the reference transcript matches the audio and warn on consent.

### Text-to-Speech → Piper voice  `id: config-a.tts.piper.voice`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → label `VOICE` under the Piper block (`tts.piper.voice`, string, default `en_US-lessac-medium`).
- **What it does:** Local Piper TTS voice — a voice name downloaded on first use, or an absolute path to a pre-downloaded `.onnx` file.
- **How it works:** `config_defaults.py:1884-1896`; the full voice list is linked as `https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md`. The setup UI prints `"    Switch voices by setting tts.piper.voice in ~/.hermes/config.yaml"` (`hermes_cli/tools_config.py:2264`). **Commented-out (not seeded, therefore not schema fields) Piper knobs in `config_defaults.py:1890-1896`:** `voices_dir` (override the voice cache dir; default `~/.hermes/cache/piper-voices/`), `use_cuda` (requires `onnxruntime-gpu`), `length_scale` (`2.0` = twice as slow), `noise_scale` (`0.667`), `noise_w_scale` (`0.8`), `volume` (`1.0`), `normalize_audio` (`True`) — all settable by hand in `config.yaml`.
- **Inputs / options:** a Piper voice name (e.g. `en_US-lessac-medium`) or an absolute `.onnx` path.
- **Outputs / side effects:** downloads the voice into `~/.hermes/cache/piper-voices/` on first use; synthesizes locally.
- **Config / env:** `tts.piper.voice` (plus the six commented-out siblings above).
- **Edge cases / guards:** an unknown voice name fails at download time; the hidden knobs have no UI so they are easy to lose track of.
- **Rebuild notes:** Voice-name-or-path resolution with a cache dir. A better version would surface the hidden prosody knobs in the schema instead of leaving them commented out.

### Text-to-Speech → DeepInfra model / voice  `id: config-a.tts.deepinfra`
- **Surface:** Config | Tool
- **Where:** Config page tab `Text-to-Speech 30` → `MODEL` (`tts.deepinfra.model`, string, default `""`) and `VOICE` (`tts.deepinfra.voice`, string, default `default`).
- **What it does:** DeepInfra-hosted TTS. An empty model means "first tts-tagged model from the live catalog".
- **How it works:** `config_defaults.py:1897-1901`; the commented-out `base_url` sibling ("override DEEPINFRA_BASE_URL for TTS only") is not a schema field. The failure hint names the key: `"under tts.deepinfra.model, or check connectivity to "` (`tools/tts_tool.py:1971`).
- **Inputs / options:** model id string (empty = auto from catalog); voice name string.
- **Outputs / side effects:** a DeepInfra speech request; a catalog lookup when the model is empty.
- **Config / env:** `tts.deepinfra.model`, `tts.deepinfra.voice`; env `DEEPINFRA_API_KEY`, `DEEPINFRA_BASE_URL` (plus the hand-written `tts.deepinfra.base_url` override).
- **Edge cases / guards:** `deepinfra` is documented as a valid `tts.provider` value but is absent from the provider dropdown — set it in the YAML view; auto-selection depends on the catalog being reachable.
- **Rebuild notes:** Catalog-backed model selection with a per-category base-URL override. A better version would cache the catalog choice and show which model was auto-picked.

## Speech-to-Text (26 fields)

The `Speech-to-Text` tab flattens `stt:` and its per-provider sub-objects. **`stt.provider` is deliberately absent from the schema**: `_SCHEMA_OVERRIDES` declares it (`hermes_cli/web_server.py:1333-1339`, select with options `["local", "groq", "openai", "xai", "elevenlabs"]` and the comment "`mistral` temporarily removed — mistralai PyPI package quarantined (malicious 2.4.6 release on 2026-05-12). Restore once available"), but `_build_schema_from_config` only emits fields that exist as leaves in `DEFAULT_CONFIG`, and `stt.provider` is deliberately not seeded (`config_defaults.py:1905-1910`): "Strict selection semantics treat a stored stt.provider as an explicit user pick; seeding \"local\" here made a fresh install indistinguishable from a user choice. The autodetect ladder covers unset." Valid hand-written values are `local` | `groq` | `openai` (Whisper API) | `mistral` (Voxtral Transcribe) | `elevenlabs` (Scribe) | `deepinfra`, plus the internal `local_command` and the managed `nous`. The selection ladder lives in `tools/transcription_tools.py:1018-1080+`: when nothing is set, auto-detect tries **local > groq (free) > openai (paid)**; a merged-config `"local"` is not proof of a user pick, so `read_selection("stt")` is consulted against the raw `config.yaml` and, when the raw file holds nothing, the autodetect branch is taken anyway (`:1035-1048`); an explicit `local` falls back through `_HAS_FASTER_WHISPER` → `_has_local_command()` → `_try_lazy_install_stt()` → `"none"` with the warning "STT provider 'local' configured but unavailable (install faster-whisper or set HERMES_LOCAL_STT_COMMAND)"; `local_command` falls back to `local`; the managed `nous` value is rewritten to `openai` and routed through the managed openai-audio gateway (`:1028-1032`).

### Speech-to-Text → Enabled  `id: config-a.stt.enabled`
- **Surface:** Config | Tool | Gateway/Telegram
- **Where:** Config page tab `Speech-to-Text 26` → label `ENABLED` (switch, default `true`).
- **What it does:** Master switch for speech-to-text. Off means voice messages are not transcribed at all.
- **How it works:** `config_defaults.py:1903`. The selection ladder short-circuits on it: `tools/transcription_tools.py:1022` `if not is_stt_enabled(stt_config): return "none"`; the tool refuses with `"STT is disabled in config.yaml (stt.enabled: false)."` (`:2985`) and voice-mode diagnostics print `"STT provider: DISABLED in config (stt.enabled: false)"` (`tools/voice_mode.py:2308`). The gateway reads it while building its config view (`gateway/config.py:1211`). It is also the toolset's own enable switch rather than a `platform_toolsets` entry (`hermes_cli/tools_config.py:165`, `hermes_cli/web_routers/tools.py:104`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** voice messages are ignored/refused; the transcription tool reports "none" as its provider.
- **Config / env:** `stt.enabled`.
- **Edge cases / guards:** disabling STT also disables the voice chat loop's input side; the toolset row in `hermes tools` reflects this key rather than a separate toggle.
- **Rebuild notes:** One boolean checked first in provider resolution. A better version would distinguish "disabled" from "no provider available" in the user-facing message.

### Speech-to-Text → Echo transcripts  `id: config-a.stt.echo_transcripts`
- **Surface:** Config | Gateway/Telegram
- **Where:** Config page tab `Speech-to-Text 26` → label `ECHO TRANSCRIPTS` (switch, default `true`).
- **What it does:** When a gateway voice message is transcribed for the agent, also echo the raw transcript back to the user as a 🎙️ message. Set false to keep STT for the agent while suppressing that user-facing echo.
- **How it works:** `config_defaults.py:1904-1907`. Read at `gateway/config.py:1215` (`data.get("stt", {}).get("echo_transcripts")`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** an extra chat message containing the transcript, prefixed with the 🎙️ emoji.
- **Config / env:** `stt.echo_transcripts`.
- **Edge cases / guards:** the echo is how a user notices a mis-transcription — disabling it makes STT errors invisible until the reply is wrong.
- **Rebuild notes:** Optional echo of the transcript before dispatch. A better version would show the transcript with a one-tap "fix" affordance rather than a plain echo.

### Speech-to-Text → Language (global)  `id: config-a.stt.language`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → label `LANGUAGE` (string, default `en`).
- **What it does:** Global language hint applied to EVERY provider unless a per-provider `language` overrides it.
- **How it works:** `config_defaults.py:1911-1916` — the default is `"en"` rather than empty because Whisper auto-detection frequently misidentifies short/accented clips, which reads to users as "STT transcribed the wrong language"; set `""` to restore auto-detect. Precedence is uniform across providers, documented per branch in `tools/transcription_tools.py`: `:192` ("2. ``stt.language`` — global default for every provider"), `:2107` (local: hook override > `stt.local.language` > `stt.language` > env var), `:2192` (`stt.language` (config.yaml) > `HERMES_LOCAL_STT_LANGUAGE` (env)), `:2207` (groq), `:2282` (generic `stt.<provider>.language`), `:2409` (mistral), `:2500` (xai), `:2633` (elevenlabs `language(_code)`).
- **Inputs / options:** a language code string (`en`, `es`, `zh`, `uk`, …) or `""` for auto-detect.
- **Outputs / side effects:** the `language` parameter on every transcription request.
- **Config / env:** `stt.language`; env `HERMES_LOCAL_STT_LANGUAGE` (lowest precedence, local path).
- **Edge cases / guards:** a wrong pin is worse than auto-detect for multilingual users; ElevenLabs uses ISO-639-3 style codes (`eng`, `spa`, `fra`) in its own key, not the two-letter codes used here.
- **Rebuild notes:** One hint threaded through every provider adapter with a per-provider override slot. A better version would detect the language once per session and pin it adaptively.

### Speech-to-Text → Cloud silence trim (enable / threshold dB / keep ms)  `id: config-a.stt.cloud_trim`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `CLOUD TRIM SILENCE` (`stt.cloud_trim_silence`, switch, default `true`), `CLOUD TRIM THRESHOLD DB` (`stt.cloud_trim_threshold_db`, number, default `-40`), `CLOUD TRIM KEEP MS` (`stt.cloud_trim_keep_ms`, number, default `300`).
- **What it does:** Client-side pre-upload silence trimming for the **cloud** providers (groq / openai / mistral / xai / elevenlabs / deepinfra). Local whisper gets Silero VAD instead; cloud endpoints would otherwise receive raw audio, where silence inflates upload time, per-audio-minute billing and hallucination risk.
- **How it works:** `config_defaults.py:1917-1924`. Implemented with ffmpeg's `silenceremove` filter, keeping `stt.cloud_trim_keep_ms` of every pause so pacing stays natural (`tools/transcription_tools.py:2778`); any failure uploads the original audio unchanged. Readers: `:2842` `enabled = is_truthy_value(cfg.get("cloud_trim_silence", True), default=True)`, `:2844` `threshold_db = int(cfg.get("cloud_trim_threshold_db", _CLOUD_TRIM_THRESHOLD_DB_DEFAULT))`, `:2848` `keep_ms = int(cfg.get("cloud_trim_keep_ms", _CLOUD_TRIM_KEEP_MS_DEFAULT))`; the disable path is documented at `:2781` (`- ``stt.cloud_trim_silence: false```).
- **Inputs / options:** boolean; integer dBFS (audio quieter than this counts as silence); integer milliseconds of each pause preserved.
- **Outputs / side effects:** a shorter audio file is uploaded; billing and latency drop.
- **Config / env:** the three `stt.cloud_trim_*` keys.
- **Edge cases / guards:** requires ffmpeg on PATH — without it the trim silently no-ops and the original is uploaded; too aggressive a threshold clips quiet speech.
- **Rebuild notes:** ffmpeg `silenceremove` pre-pass with a fail-open fallback. A better version would run VAD once and reuse the decision for both trimming and endpointing.

### Speech-to-Text → Local model / language / initial prompt  `id: config-a.stt.local.model`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `MODEL` (`stt.local.model`, select, description `Local faster-whisper model size`, default `base`), `LANGUAGE` (`stt.local.language`, string, default `""`), `INITIAL PROMPT` (`stt.local.initial_prompt`, string, default `""`).
- **What it does:** The offline faster-whisper path: which model size to load, an optional language pin for it alone, and an initial prompt that biases decoding (useful for names/jargon).
- **How it works:** Select override at `hermes_cli/web_server.py:1340-1344`; declared at `config_defaults.py:1925-1928`. Model fallback warning: `tools/transcription_tools.py:324` — `"provider. Falling back to '%s'. Set stt.local.model to a valid "`; the CLI prefers `stt.local.model` for the local provider (`cli.py:15235`) and the setup UI prints `"    Change via stt.local.model in ~/.hermes/config.yaml"` (`hermes_cli/tools_config.py:2208`). `initial_prompt` is read at `tools/transcription_tools.py:1871-1873` (`initial_prompt = local_cfg.get("initial_prompt")` → `kwargs["initial_prompt"] = initial_prompt`) and re-applied at `:1989`. Language precedence for this path is hook override > `stt.local.language` > `stt.language` > `HERMES_LOCAL_STT_LANGUAGE` (`:2107,2192`).
- **Inputs / options:** model select with exactly five values — `tiny`, `base`, `small`, `medium`, `large-v3`; language code string (empty = fall through to `stt.language`); free-text initial prompt.
- **Outputs / side effects:** model weights downloaded/loaded into RAM; decoding biased by the prompt.
- **Config / env:** `stt.local.model`, `stt.local.language`, `stt.local.initial_prompt`; env `HERMES_LOCAL_STT_COMMAND` (external command backend), `HERMES_LOCAL_STT_LANGUAGE`.
- **Edge cases / guards:** an invalid model name warns and falls back; larger models trade RAM/latency for accuracy; `initial_prompt` text can leak into the transcript if the audio is near-silent.
- **Rebuild notes:** faster-whisper model-size enum plus decoder kwargs. A better version would auto-pick the model size from available RAM and measured latency.

### Speech-to-Text → Local VAD (enable / min silence ms)  `id: config-a.stt.local.vad`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `VAD` (`stt.local.vad`, switch, default `true`) and `VAD MIN SILENCE MS` (`stt.local.vad_min_silence_ms`, number, default `500`).
- **What it does:** Silero voice-activity filtering in front of local whisper so silence never reaches the model, and the minimum silence length that splits speech into chunks.
- **How it works:** `config_defaults.py:1929-1932` — part of the "Anti-hallucination hardening (faster-whisper decodes junk tokens from silence/noise without these)" group; `false` restores the old raw behaviour (better for music/ambient capture). The rationale comment is at `tools/transcription_tools.py:1812` ("reaches the model. ``stt.local.vad: false`` restores raw behavior"); readers at `:1839` (`vad_enabled = local_cfg.get("vad", True)`) and `:1846` (`local_cfg.get("vad_min_silence_ms", _VAD_MIN_SILENCE_MS_DEFAULT)`).
- **Inputs / options:** boolean; integer milliseconds.
- **Outputs / side effects:** silent regions are dropped before decoding; segment boundaries change.
- **Config / env:** `stt.local.vad`, `stt.local.vad_min_silence_ms`.
- **Edge cases / guards:** with VAD off, faster-whisper reliably hallucinates text from silence; too small a min-silence over-splits speech.
- **Rebuild notes:** Silero VAD pre-filter with a configurable split threshold. A better version would reuse the same VAD for the recorder's auto-stop.

### Speech-to-Text → Local hallucination filters (no-speech prob / logprob)  `id: config-a.stt.local.thresholds`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `NO SPEECH PROB THRESHOLD` (`stt.local.no_speech_prob_threshold`, number, default `0.6`) and `LOGPROB THRESHOLD` (`stt.local.logprob_threshold`, number, default `-1.0`).
- **What it does:** The two-condition drop rule for a decoded segment: discard it only if its `no_speech_prob` is ABOVE the first threshold **AND** its `avg_logprob` is BELOW the second — both must hit.
- **How it works:** `config_defaults.py:1933-1934` (the two comment lines spell out the conjunction). Readers: `tools/transcription_tools.py:1882` (`local_cfg.get("no_speech_prob_threshold", _NO_SPEECH_PROB_THRESHOLD_DEFAULT)`) and `:1887` (`float(local_cfg.get("logprob_threshold", _LOGPROB_THRESHOLD_DEFAULT))`).
- **Inputs / options:** float probability 0–1; float average log-probability (negative).
- **Outputs / side effects:** low-confidence segments are removed from the transcript.
- **Config / env:** `stt.local.no_speech_prob_threshold`, `stt.local.logprob_threshold`.
- **Edge cases / guards:** because both conditions must hit, loosening either one alone lets more junk through; too strict a pair drops quiet real speech.
- **Rebuild notes:** Per-segment confidence gate combining two whisper outputs. A better version would surface dropped segments as a "low confidence" marker rather than deleting them silently.

### Speech-to-Text → Local unload after idle seconds  `id: config-a.stt.local.unload_after_idle_seconds`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → label `UNLOAD AFTER IDLE SECONDS` (number, default `0`).
- **What it does:** Releases the loaded local whisper model from memory after this many seconds of idleness. `0` = never (default).
- **How it works:** `config_defaults.py:1935`. Read at `tools/transcription_tools.py:1683` (`val = int(local_cfg.get("unload_after_idle_seconds", 0))`); the docstring at `:1713` notes a change to `stt.local.unload_after_idle_seconds` "takes effect within one check" interval rather than immediately.
- **Inputs / options:** non-negative integer seconds; the comment's example is `300` (release after 5 min idle).
- **Outputs / side effects:** the model's RAM is freed; the next transcription pays the load latency again.
- **Config / env:** `stt.local.unload_after_idle_seconds`.
- **Edge cases / guards:** reload latency on a `large-v3` model is significant — set this only on memory-constrained hosts.
- **Rebuild notes:** Idle timer around a lazily-loaded model handle. A better version would unload under memory pressure rather than on a fixed timer.

### Speech-to-Text → Groq model / language  `id: config-a.stt.groq`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `MODEL` (`stt.groq.model`, select, description `Groq Whisper model`, default `whisper-large-v3-turbo`) and `LANGUAGE` (`stt.groq.language`, string, default `""`).
- **What it does:** Groq-hosted Whisper: which model, and an optional per-provider language pin.
- **How it works:** Select override at `hermes_cli/web_server.py:1345-1349`; declared at `config_defaults.py:1936-1939`. Language precedence for this branch is documented at `tools/transcription_tools.py:2191` ("``pre_transcription`` hook override > ``stt.groq.language`` >") and `:2207` (hook override > `stt.groq.language` > `stt.language` > env). Groq is the free tier in the autodetect ladder (local > groq > openai) and requires `GROQ_API_KEY` (`transcription_tools.py:1078`).
- **Inputs / options:** model select with exactly three values — `whisper-large-v3-turbo`, `whisper-large-v3`, `distil-whisper-large-v3-en`; language code string (empty = fall through).
- **Outputs / side effects:** the Groq transcription request.
- **Config / env:** `stt.groq.model`, `stt.groq.language`; env `GROQ_API_KEY`.
- **Edge cases / guards:** `distil-whisper-large-v3-en` is English-only — pairing it with a non-English language pin will not work.
- **Rebuild notes:** Model enum + optional language in the multipart request. A better version would map the language pin to a model that supports it.

### Speech-to-Text → OpenAI model / language  `id: config-a.stt.openai`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `MODEL` (`stt.openai.model`, select, description `OpenAI transcription model`, default `whisper-1`) and `LANGUAGE` (`stt.openai.language`, string, default `""`).
- **What it does:** OpenAI-hosted transcription (also the implementation behind the managed "Nous Subscription" STT route).
- **How it works:** Select override at `hermes_cli/web_server.py:1350-1354`; declared at `config_defaults.py:1940-1943`. Provider plugins read their own model key rather than a shared one — the comment at `tools/transcription_tools.py:3145` names `stt.openai.model` and `stt.mistral.model` as that pattern; the `nous` selection is serviced by this provider through `_resolve_openai_audio_client_config` and the fallback branch at `:3176` (`if provider_key == "none" and str(stt_config.get("provider") or "") == "openai" and _HAS_OPENAI`).
- **Inputs / options:** model select with exactly four values — `whisper-1`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `gpt-transcribe`; language code string.
- **Outputs / side effects:** the OpenAI `/audio/transcriptions` request.
- **Config / env:** `stt.openai.model`, `stt.openai.language`; env `OPENAI_API_KEY` (or the managed gateway).
- **Edge cases / guards:** openai is the paid last rung of the autodetect ladder; the `gpt-4o-*-transcribe` models have different response shapes than `whisper-1`.
- **Rebuild notes:** Model enum + language in the transcription request. A better version would expose the streaming transcription endpoint for lower latency.

### Speech-to-Text → Mistral model / language  `id: config-a.stt.mistral`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `MODEL` (`stt.mistral.model`, string, default `voxtral-mini-latest`) and `LANGUAGE` (`stt.mistral.language`, string, default `""`).
- **What it does:** Mistral Voxtral Transcribe: which Voxtral model, and an optional per-provider language pin.
- **How it works:** `config_defaults.py:1944-1947`; the model comment lists `voxtral-mini-latest, voxtral-mini-2602`. Language precedence documented at `tools/transcription_tools.py:2408` ("Language: hook override > stt.mistral.language >"); the per-plugin model-key pattern is noted at `:3145`.
- **Inputs / options:** model id string (`voxtral-mini-latest` | `voxtral-mini-2602`); language code string.
- **Outputs / side effects:** the Mistral transcription request.
- **Config / env:** `stt.mistral.model`, `stt.mistral.language`; the Mistral API key env var.
- **Edge cases / guards:** `mistral` is a valid `stt.provider` value in the config comment but is **removed from the schema's provider dropdown** because the `mistralai` PyPI package was quarantined after a malicious 2.4.6 release on 2026-05-12 (`hermes_cli/web_server.py:1335-1337`) — set it by hand only if you have vetted the package.
- **Rebuild notes:** Model + language in the request. A better version would pin the client library to a verified hash given the quarantine history.

### Speech-to-Text → xAI language  `id: config-a.stt.xai.language`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → label `LANGUAGE` under the xAI block (`stt.xai.language`, string, default `""`).
- **What it does:** Optional per-provider language pin for xAI transcription. There is no `stt.xai.model` key — the model is fixed by the provider implementation.
- **How it works:** `config_defaults.py:1948-1950`. Precedence documented at `tools/transcription_tools.py:2500` ("Language: hook override > stt.xai.language > stt.language > env."). The xAI branch also honours a `diarize` flag read from the same section (`:2505` — `is_truthy_value(xai_config.get("diarize", False))`, applied at `:2517`), which is **not** seeded in `DEFAULT_CONFIG` and therefore is not a schema field; add `stt.xai.diarize: true` by hand to enable it.
- **Inputs / options:** language code string; (hand-written) `stt.xai.diarize` boolean.
- **Outputs / side effects:** the xAI transcription request's `language` (and optionally `diarize`) fields.
- **Config / env:** `stt.xai.language`; the xAI API key env var.
- **Edge cases / guards:** `xai` is offered in the provider dropdown but has no model key here; the undeclared `diarize` sibling is easy to miss.
- **Rebuild notes:** Optional language field per provider. A better version would seed every provider's supported extras so they all appear in the schema.

### Speech-to-Text → ElevenLabs Scribe (model / language code / audio events / diarize)  `id: config-a.stt.elevenlabs`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → `MODEL ID` (`stt.elevenlabs.model_id`, select, description `ElevenLabs Scribe model`, default `scribe_v2`), `LANGUAGE CODE` (`stt.elevenlabs.language_code`, string, default `""`), `TAG AUDIO EVENTS` (`stt.elevenlabs.tag_audio_events`, switch, default `false`), `DIARIZE` (`stt.elevenlabs.diarize`, switch, default `false`).
- **What it does:** ElevenLabs Scribe transcription: model version, language pin, whether to tag non-speech audio events, and whether to label speakers.
- **How it works:** Select override at `hermes_cli/web_server.py:1355-1359`; declared at `config_defaults.py:1951-1956`. Readers in `tools/transcription_tools.py`: the section is fetched with an extra key list `"elevenlabs", stt_config, extra_keys=("language_code",)` (`:2635`, mirrored in the client-direct payload at `tools/voice_client_config.py:100`), then `data["language_code"] = language_code` (`:2649`), `tag_audio_events = is_truthy_value(elevenlabs_config.get("tag_audio_events", False))` (`:2637`) → `"tag_audio_events": "true" if tag_audio_events else "false"` (`:2645`), and `diarize = is_truthy_value(elevenlabs_config.get("diarize", False))` (`:2638`) → `"diarize": "true" if diarize else "false"` (`:2646`). Language precedence at `:2633` ("hook override > stt.elevenlabs.language(_code) > stt.language"). Note the model key is `model_id` here — `hermes_cli/tools_config.py:4622` encodes that exception as `_STT_MODEL_CONFIG_KEY = {"elevenlabs": "model_id"}`.
- **Inputs / options:** model select with exactly two values — `scribe_v2`, `scribe_v1`; ISO-639-3 style language code string (`eng`, `spa`, `fra`, … — note this differs from the two-letter codes used elsewhere); boolean ×2.
- **Outputs / side effects:** the Scribe request's form fields; transcripts gain event tags and/or speaker labels.
- **Config / env:** the four `stt.elevenlabs.*` keys; env `ELEVENLABS_API_KEY`.
- **Edge cases / guards:** the language-code vocabulary differs from `stt.language`; booleans are serialised as the strings `"true"`/`"false"` in the multipart body.
- **Rebuild notes:** Provider-specific field names mapped from a common config shape. A better version would normalise language codes across providers so one global pin always works.

### Speech-to-Text → DeepInfra model  `id: config-a.stt.deepinfra.model`
- **Surface:** Config | Tool
- **Where:** Config page tab `Speech-to-Text 26` → label `MODEL` under the DeepInfra block (`stt.deepinfra.model`, string, default `""`).
- **What it does:** DeepInfra-hosted transcription; an empty value means "first stt-tagged model from the live catalog".
- **How it works:** `config_defaults.py:1957-1960`; the commented-out `base_url` sibling ("override DEEPINFRA_BASE_URL for STT only") is not a schema field. The failure hint names the key: `"config.yaml under stt.deepinfra.model, or check "` (`tools/transcription_tools.py:2748`).
- **Inputs / options:** model id string (empty = auto from catalog).
- **Outputs / side effects:** the DeepInfra transcription request; a catalog lookup when empty.
- **Config / env:** `stt.deepinfra.model`; env `DEEPINFRA_API_KEY`, `DEEPINFRA_BASE_URL` (plus the hand-written `stt.deepinfra.base_url`).
- **Edge cases / guards:** `deepinfra` is a documented `stt.provider` value but is absent from the provider dropdown — set it in the YAML view; there is no `stt.deepinfra.language` key, so the global `stt.language` applies.
- **Rebuild notes:** Catalog-backed model auto-selection with an explicit override. A better version would report which model was auto-selected in the transcription result.

## Logging (3 fields)

### Logging → Level  `id: config-a.logging.level`
- **Surface:** Config | Core
- **Where:** Config page tab `Logging 3` → label `LEVEL`, description `Log level for agent.log` (select, default `INFO`).
- **What it does:** Minimum severity written to `~/.hermes/logs/agent.log`.
- **How it works:** Select override at `hermes_cli/web_server.py:1394-1398`; declared at `config_defaults.py:3037-3043` with the section comment "Logging — controls file logging to ~/.hermes/logs/. agent.log captures INFO+ (all agent activity); errors.log captures WARNING+". `hermes_logging.py:286-288` documents the parameter ("Accepts any standard Python level name (``\"DEBUG\"``, ``\"INFO\"``, ``\"WARNING\"``). Defaults to ``\"INFO\"`` or the value from config.yaml ``logging.level``") and the config is read at `hermes_logging.py:950-966`, which opens `config.yaml` directly with `fast_safe_load`, applies the managed-scope overlay (`from hermes_cli import managed_scope; managed_scope.apply_managed_overlay(cfg)`, fail-open) so an administrator can pin `logging.*`, and returns the `(level, max_size_mb, backup_count)` triple. `mode` selects extra files: `"gateway"` adds `gateway.log` (gateway-component records only) and `"gui"` adds `gui.log` (`hermes_logging.py:295-300`). The test harness pins `{"logging": {"level": "WARNING"}}` (`scripts/tool_search_livetest.py:295`).
- **Inputs / options:** select with exactly four values — `DEBUG`, `INFO`, `WARNING`, `ERROR` (the docstring names the first three; any standard Python level name is accepted from YAML).
- **Outputs / side effects:** volume and detail of `~/.hermes/logs/agent.log`; `errors.log` always keeps WARNING+.
- **Config / env:** `logging.level`. Read directly from `config.yaml` at logging-setup time (before the normal config cache), so no env carrier.
- **Edge cases / guards:** `DEBUG` can log request/response detail — combine with `security.redact_secrets: true`; an administrator's managed overlay can pin the level.
- **Rebuild notes:** Level string mapped to the file handler's level at setup. A better version would allow per-module levels and a runtime `/loglevel` without a restart.

### Logging → Max size MB / Backup count  `id: config-a.logging.rotation`
- **Surface:** Config | Core
- **Where:** Config page tab `Logging 3` → `MAX SIZE MB` (`logging.max_size_mb`, number, default `5`) and `BACKUP COUNT` (`logging.backup_count`, number, default `3`).
- **What it does:** Rotation policy for the log files: rotate each file at N megabytes and keep N rotated backups.
- **How it works:** `config_defaults.py:3040-3041`. Documented at `hermes_logging.py:289-295` ("Maximum size of each log file in megabytes before rotation. Defaults to 5 or the value from config.yaml ``logging.max_size_mb``" / "Number of rotated backup files to keep. Defaults to 3 or the value from config.yaml ``logging.backup_count``") and read together with the level at `hermes_logging.py:964-965` (`log_cfg.get("max_size_mb")`, `log_cfg.get("backup_count")`) — the same managed-overlay path as the level.
- **Inputs / options:** two positive integers (megabytes; file count).
- **Outputs / side effects:** at most `(backup_count + 1) × max_size_mb` MB per log file family under `~/.hermes/logs/`.
- **Config / env:** `logging.max_size_mb`, `logging.backup_count`.
- **Edge cases / guards:** applies per log file (`agent.log`, `errors.log`, and `gateway.log`/`gui.log` when those modes are active), so total disk use is a multiple of the nominal cap; changes take effect on the next process start.
- **Rebuild notes:** `RotatingFileHandler(maxBytes, backupCount)`. A better version would add time-based rotation and optional compression of rotated files.

## Unresolved / declared-but-inert keys found in this shard

These are recorded so a rebuild does not faithfully re-implement a dead wire. Each was verified with a repository-wide grep on the v2026.8.31 checkout.

1. **`display.copy_shortcut`** — declared at `config_defaults.py:1646` with the values `auto` / `ctrl_c` / `ctrl_shift_c` / `disabled`; that line is the only occurrence in the repository. No Python, TUI or desktop reader exists.
2. **`human_delay.mode` / `human_delay.min_ms` / `human_delay.max_ms`** — declared (`config_defaults.py:2028-2032`), schema-overridden (`web_server.py:1389-1393`) and advertised in tips (`hermes_cli/tips.py:313`), but the only implementation (`gateway/platforms/base.py:6462-6487`) reads `HERMES_HUMAN_DELAY_MODE` / `_MIN_MS` / `_MAX_MS` from the environment, and its mode vocabulary is `off` / `natural` / `custom` while the dropdown offers `off` / `typing` / `fixed`. Nothing bridges config → env. Editing the fields has no runtime effect in this release.
3. **`stt.provider`** — has a `_SCHEMA_OVERRIDES` entry (`web_server.py:1333-1339`) but is deliberately not seeded in `DEFAULT_CONFIG`, so `_build_schema_from_config` never emits it and the Config page has no field for it. It must be set in the YAML view or with `hermes tools`. Its dropdown would have listed `local`, `groq`, `openai`, `xai`, `elevenlabs` (mistral withdrawn after the 2026-05-12 `mistralai` 2.4.6 supply-chain incident) — while `deepinfra`, `local_command` and the managed `nous` are supported by the code but not by that list.
4. **`stt.xai.diarize`** — read at `tools/transcription_tools.py:2505` and applied at `:2517`, but not present in `DEFAULT_CONFIG`, so it never appears as a Config field. Hand-write it under `stt.xai:`.
5. **`tts.<provider>.max_text_length`** — documented as supported for every TTS provider (`config_defaults.py:1818-1822`) but not seeded, so it is YAML-only.
6. **`tts.piper.voices_dir` / `use_cuda` / `length_scale` / `noise_scale` / `noise_w_scale` / `volume` / `normalize_audio`** — shipped commented out (`config_defaults.py:1890-1896`); functional in YAML, invisible in the schema.
7. **Default drift between `DEFAULT_CONFIG` and read-site fallbacks** (harmless while the merged config always supplies the key, but it changes behaviour for any caller that reads a raw/partial config): `approvals.mode` seeds `smart` while `_get_approval_mode()` falls back to `"manual"` (`tools/approval.py:3462`); `security.website_blocklist.enabled` seeds `False` while `tools/website_policy.py:165` treats a missing key as `True`; `voice.barge_in_threshold_multiplier` seeds `3.0` while both read sites default to `0` (`cli.py:15535`, `tui_gateway/server.py:16699`).
8. **`dashboard.show_token_analytics`** has no Python reader at all — it is consumed only by the SPA (`web/src/App.tsx`, `AnalyticsPage.tsx`, `ModelsPage.tsx`) with a strict `=== true` comparison, so truthy strings do not enable it.

## Handoffs

- `Proxy` tab — the five non-security `proxy.*` keys (`tunnel_port`, `auto_install`, `allow_env_fallback`, `upstream_deny_cidrs`, `extra_allowed_hosts`, `config_defaults.py:3838-3884`) belong to the sibling config shard.
- `Wake_word` tab — the 14 `wake_word.*` keys ("Hey Hermes" hotword: `enabled`, `surface`, `input_device`, `capture`, `provider`, `phrase`, `sensitivity`, `confirmation_frames`, `start_new_session`, `profile_routing`, `openwakeword.model`, `openwakeword.inference_framework`, `sherpa.model_dir`, `porcupine.keyword`, `config_defaults.py:1984-2026`) sit next to Voice but are their own category.
- `Auxiliary` tab (115 fields) — including `auxiliary.compression.model` / `provider` / `base_url` / `fallback_chain`, which are the summarizer half of the Compression story documented here.
- Dict-valued config that never becomes a schema field: `compression.model_thresholds`, `delegation.request_overrides`, `tts.providers.<name>` (the command-type TTS provider registry, PR #17843), `stt.providers.<name>`, `security`-adjacent `command_allowlist`, `hooks`, `platform_hints`.
- CLI surfaces that write the keys documented here: `hermes egress setup|start|status|disable` (`hermes_cli/proxy_cli.py`), `hermes doctor --ack <id>`, `hermes tools` (TTS/STT provider pickers), `hermes browser close-profile`, `hermes config get|set|unset`, `hermes plugins`.
- Slash commands that flip these keys at runtime: `/memory approval on|off`, `/voice on|tts`, `/voice status`, `/browser use off`, `/browser connect <url>`, `/browser status`, `/compress`, `/compact`, `/yolo`, `/approve`, `/reload-mcp`, `/clear`, `/new`, `/reset`, `/undo`, `/pet`, `/goal`, `/wake`.
- Dashboard auth plugins referenced by the `dashboard.*` keys: `plugins/dashboard_auth/nous`, `plugins/dashboard_auth/basic`, `plugins/dashboard_auth/drain` — their plugin-level behaviour (login pages, token minting, the drain endpoint) belongs to the plugins/web shards.
- Memory provider plugins selectable through `memory.provider` (`byterover`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory`) and their own `memory.<name>.*` config blocks.
- The Config page chrome itself — `Search...`, `Export config as JSON`, `Import config from JSON`, `Reset <Tab> to defaults`, the `YAML` / form toggle and `SAVE` — plus `GET /api/config`, `/api/config/schema`, `/api/config/defaults`, `/api/config/raw` and `PUT /api/config`.
- `scripts/iso-certify.py` — the turn-isolation certification harness that drives `dashboard.turn_isolation` and the two compute-host keys in a scratch `HERMES_HOME`.
- Environment-variable reference: `website/docs/reference/environment-variables.md` documents 671 variables, including every env carrier named in this shard.
