# Gateway Runtime & Chat Behaviours (platform-independent)

This shard documents the Hermes messaging **gateway engine** — the single background process that
owns every chat platform adapter at once: the inbound message pipeline (authorization, pairing,
interception, busy/queue handling, session keying), the outbound rendering pipeline (streaming,
chunking, progress bubbles, sanitization, media/voice), all gateway configuration options in
`gateway/config.py`, and every non-platform module under `gateway/` (lifecycle, watchdogs, drain,
delivery ledger, relay, browser-control broker, kanban watchers, scale-to-zero).
It deliberately leaves to sibling shards: the individual platform adapters (`gateway/platforms/`,
`plugins/platforms/`), the slash-command handlers themselves (`gateway/slash_commands.py`,
`gateway/slash_access.py` command *catalog*), and hosted rooms / runs API (`gateway/hosted_room*.py`,
automation shard). Where a behaviour crosses that line, only the gateway-side half is documented here.

Primary sources: `gateway/run.py` (33 539 lines), `gateway/config.py` (2 907 lines), `gateway/session.py`,
`gateway/stream_consumer.py`, `gateway/display_config.py`, plus every other `gateway/*.py`;
docs `website/docs/user-guide/messaging/index.md`, `website/docs/user-guide/bot-mode.md`,
`website/docs/user-guide/multi-profile-gateways.md`.

---

## 1. Gateway process, startup and configuration loading

### The gateway process  `id: gw-core.gateway-process`
- **Surface:** CLI | Core
- **Where:** `hermes gateway` (foreground), `hermes gateway start|stop|status|install|uninstall|restart`, `hermes gateway setup`; service units `hermes-gateway.service` (Linux user), `hermes-gateway-<profile>.service`, `ai.hermes.gateway.plist` (macOS launchd), `ai.hermes.gateway-<profile>.plist`.
- **What it does:** Runs one long-lived asyncio process that connects every enabled messaging platform adapter, owns the per-chat session store, runs the cron scheduler (60 s tick), and dispatches inbound messages to `AIAgent`.
- **How it works:** `gateway/run.py:32585 start_gateway()` builds `GatewayRunner` (`gateway/run.py:7289`, a class mixing in `GatewayAuthorizationMixin`, `GatewayKanbanWatchersMixin`, `GatewaySlashCommandsMixin`), calls `GatewayRunner.start()` (`gateway/run.py:13414`), then `wait_for_shutdown()` (`:16547`). `main()` at `gateway/run.py:33391` is the module entry point. Housekeeping threads: `_start_gateway_housekeeping` (`:32083`, 60 s interval), `_start_cron_ticker` (`:32273`, 60 s). PID/lock/state files live under `$HERMES_HOME` (`gateway.pid`, `gateway.lock`, `gateway_state.json`, `gateway-locks/`) per `gateway/status.py:38-48`.
- **Inputs / options:** Environment `HERMES_HOME` (selects the install/profile), verbosity argument to `start_gateway(verbosity=…)`, `replace=True` to take over an existing PID. Signals: SIGTERM/SIGINT → `shutdown_signal_handler` (`gateway/run.py:32859`); SIGUSR1 → `restart_signal_handler` (`:32954`).
- **Outputs / side effects:** Writes `gateway.pid`, `gateway.lock`, `gateway_state.json`, `state/gateway.heartbeat`, `state/gateway.lifecycle.json`, logs to `~/.hermes/logs/gateway.log` and `gateway.error.log`; opens the gateway control socket `$HERMES_HOME/gateway.sock`.
- **Config / env:** Everything under `gateway.*`, `streaming.*`, `session_reset.*`, `display.*` in `~/.hermes/config.yaml`; legacy `~/.hermes/gateway.json`.
- **Edge cases / guards:** Exit code 75 (`GATEWAY_SERVICE_RESTART_EXIT_CODE`) asks the supervisor to restart; exit code 78 (`GATEWAY_FATAL_CONFIG_EXIT_CODE`) marks a permanent config failure so s6 stops respawning (`gateway/restart.py:12-19`). Only one gateway may hold the runtime lock per `HERMES_HOME`.
- **Rebuild notes:** One process, N adapters, one session store, one agent-per-session cache, one cron ticker. A better version would make the adapter set hot-reloadable without a process restart and expose a real control RPC instead of file markers.

### Gateway config load order  `id: gw-core.config-load-order`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` (primary), `~/.hermes/gateway.json` (legacy), process environment.
- **What it does:** Merges gateway settings from four layers into one `GatewayConfig` object.
- **How it works:** `load_gateway_config()` (`gateway/config.py:1383`). Order, lowest→highest: (4) built-in dataclass defaults → (3) `~/.hermes/gateway.json` → (2) `~/.hermes/config.yaml` (with `hermes_cli.managed_scope.apply_managed_overlay()` administrator pins applied first) → (1) environment variables via `_apply_env_overrides()` (`gateway/config.py:1983`). Then `_validate_gateway_config()` (`:1921`) sanitizes. A malformed `config.yaml` logs `"Failed to process config.yaml — falling back to .env / gateway.json values."` and continues.
- **Inputs / options:** Every key listed in the entries below. Every gateway top-level key is ALSO accepted nested under `gateway:` (written by `hermes config set gateway.<key> …`); the rule is *top-level key presence wins, nested `gateway.*` is the fallback* — an explicitly-present-but-empty top-level value is never replaced by the nested one.
- **Outputs / side effects:** Some YAML keys are bridged into `os.environ` for adapters (e.g. top-level `require_mention` → `TELEGRAM_REQUIRE_MENTION`), and into `PlatformConfig.extra`.
- **Config / env:** n/a (this *is* the mechanism).
- **Edge cases / guards:** `gateway.json` presence logs `"Loaded legacy … — consider moving settings to config.yaml"`. Plugin platforms get the same shared-key bridging via `PlatformEntry.apply_yaml_config_fn`.
- **Rebuild notes:** Implement a layered dict merge with explicit precedence and a "key present" (not "key truthy") test. A better version would emit a machine-readable provenance map (which layer set each key).

### Shared per-platform config keys bridged into `extra`  `id: gw-core.platform-shared-keys`
- **Surface:** Config
- **Where:** `config.yaml` → `<platform>:` block, or `platforms.<platform>:`, or `gateway.platforms.<platform>:`, or `gateway.<platform>:`.
- **What it does:** Lets a per-platform block carry a fixed set of gateway-level behaviour keys that end up in `PlatformConfig.extra` regardless of which nesting the user chose.
- **How it works:** The "shared-key loop" in `gateway/config.py:1660-1760` iterates every built-in `Platform` plus every registered plugin platform and copies these keys into `extra`.
- **Inputs / options:** `unauthorized_dm_behavior`, `notice_delivery`, `reply_prefix`, `reply_in_thread`, `cron_continuable_surface`, `require_mention`, `send_read_receipts`, `allowed_chats` (Telegram only), `group_allowed_chats` (Telegram only), `allowed_topics` (Telegram only), `free_response_channels`, `mention_patterns`, `exclusive_bot_mentions`, `observe_unmentioned_group_messages` (Telegram only), `dm_policy`, `allow_from`, `allow_admin_from`, `user_allowed_commands`, `group_policy`, `group_allow_from`, `group_allow_admin_from`, `group_user_allowed_commands`, `channel_skill_bindings` (Discord/Slack only), `channel_prompts`, `gateway_restart_notification`, `typing_indicator`, `typing_status_text`, `channel_overrides`, plus `port`/`host`/`secret` for `webhook`/`msgraph_webhook` and `port`/`host`/`key`/`cors_origins`/`model_name` for `api_server`.
- **Outputs / side effects:** `extra["_enabled_explicit"] = True` is stamped whenever the user wrote an explicit `enabled:` so a later env-driven enable pass cannot override an explicit `enabled: false`.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown keys are ignored. `channel_prompts` keys are coerced to strings.
- **Rebuild notes:** Declare a table of (key, applicable-platforms) and drive the bridge from data. A better version would validate unknown keys and warn.

### `Platform` enum & dynamic plugin platforms  `id: gw-core.platform-enum`
- **Surface:** Core | Config
- **Where:** platform names used everywhere in config (`platforms.<name>`), session keys, `/platform` command.
- **What it does:** Names every messaging platform the gateway can serve; plugin platforms become enum members on demand.
- **How it works:** `gateway/config.py:325 class Platform(Enum)`. Built-in members: `local`, `telegram`, `discord`, `whatsapp`, `whatsapp_cloud`, `slack`, `signal`, `mattermost`, `matrix`, `homeassistant`, `email`, `sms`, `dingtalk`, `api_server`, `webhook`, `msgraph_webhook`, `feishu`, `wecom`, `wecom_callback`, `weixin`, `bluebubbles`, `qqbot`, `yuanbao`, `relay` (EXPERIMENTAL). `_missing_()` (`:356`) creates identity-stable pseudo-members only for (a) bundled plugin dirs under `plugins/platforms/<name>/` containing `__init__.py` + `plugin.yaml|plugin.yml`, or (b) names already in `gateway.platform_registry`. Arbitrary strings are rejected so the enum cannot be polluted.
- **Inputs / options:** Any string, lower-cased and stripped.
- **Outputs / side effects:** Cached in `_value2member_map_` / `_member_map_`.
- **Config / env:** n/a
- **Edge cases / guards:** Non-string, blank, or unknown values return `None` → `ValueError` at `Platform(x)`; `GatewayConfig.from_dict` silently skips unknown platform blocks.
- **Rebuild notes:** A registry-backed open enum. A better version would surface a warning for unknown platform blocks in config instead of silent skip.

### Port-binding platform conflict rule  `id: gw-core.port-binding-platforms`
- **Surface:** Config | Core
- **Where:** multiplexed gateways; error text `"Skipping secondary profile '<name>' due to port-binding config error: …"`.
- **What it does:** Prevents two profiles from binding the same TCP port by declaring which platforms own a listener.
- **How it works:** `PORT_BINDING_PLATFORM_VALUES` (`gateway/config.py:437`) = `{webhook, api_server, msgraph_webhook, feishu, wecom_callback, bluebubbles, sms, whatsapp_cloud, line}`. `PORT_BINDING_CONDITIONAL_MODES` (`:452`) = `{"feishu": "webhook"}` — Feishu only binds in `connection_mode: webhook` (default `websocket` = outbound only). `platform_binds_port(value, extra)` (`:458`) is the single predicate used both by gateway startup validation and by the dashboard's pre-write mutation validation.
- **Inputs / options:** platform value string, optional `extra` dict (`connection_mode`).
- **Outputs / side effects:** In multiplex mode a secondary profile enabling one of these is skipped entirely (documented in `multi-profile-gateways.md`), while the default and other healthy profiles keep running.
- **Config / env:** `gateway.multiplex_profiles`.
- **Edge cases / guards:** Only this shared-listener conflict degrades to a skipped profile; security config errors (see `gw-core.own-policy-open-guard`) still abort startup.
- **Rebuild notes:** A single predicate consulted by every writer prevents policy drift; keep it data-driven.

### `HomeChannel` — default destination per platform  `id: gw-core.home-channel`
- **Surface:** Config | Gateway/Telegram
- **Where:** `/sethome` in any chat; `platforms.<name>.home_channel` in config; env `<PLATFORM>_HOME_CHANNEL`, `<PLATFORM>_HOME_CHANNEL_NAME`, `<PLATFORM>_HOME_CHANNEL_THREAD_ID`.
- **What it does:** Records where a bare platform delivery target (e.g. cron `deliver: telegram`) should land.
- **How it works:** `@dataclass HomeChannel` (`gateway/config.py:474`) with fields `platform`, `chat_id`, `name` (default `"Home"`), `thread_id`, `user_id`, `scope_id`. `persist_home_channel(home, enabled_if_new=False)` (`:519`) writes `platforms.<value>.home_channel` into `config.yaml` and only `setdefault`s `enabled: True` when asked — so a Relay-fronted adapter is never falsely enabled.
- **Inputs / options:** `platform`, `chat_id`, `name`, `thread_id`, `user_id`, `scope_id`.
- **Outputs / side effects:** `config.yaml` mutation; thread-aware platforms route the bare target to the exact topic where `/sethome` ran.
- **Config / env:** Per-platform env vars listed above, e.g. `TELEGRAM_HOME_CHANNEL`, `DISCORD_HOME_CHANNEL`, `SLACK_HOME_CHANNEL`, `SIGNAL_HOME_CHANNEL`, `MATTERMOST_HOME_CHANNEL`, `MATRIX_HOME_ROOM`, `EMAIL_HOME_ADDRESS`, `SMS_HOME_CHANNEL`, `WHATSAPP_HOME_CHANNEL`, `WHATSAPP_CLOUD_HOME_CHANNEL`, `DINGTALK_HOME_CHANNEL`, `FEISHU_HOME_CHANNEL`, `WECOM_HOME_CHANNEL`, `WEIXIN_HOME_CHANNEL`, `BLUEBUBBLES_HOME_CHANNEL`, `QQBOT_HOME_CHANNEL` (legacy `QQ_HOME_CHANNEL` accepted with a one-time warning), `YUANBAO_HOME_CHANNEL`.
- **Edge cases / guards:** `user_id`/`scope_id` carry authenticated logical-target provenance for relay egress but the connector remains the authorization boundary.
- **Rebuild notes:** Store (platform, chat, thread) plus a display name; keep persistence separate from enablement.

### `PlatformConfig` — per-platform gateway options  `id: gw-core.platform-config`
- **Surface:** Config
- **Where:** `platforms.<name>` / `gateway.platforms.<name>` in `config.yaml`.
- **What it does:** Holds one platform's credentials, home channel, and gateway-side behaviour flags.
- **How it works:** `@dataclass PlatformConfig` (`gateway/config.py:647`).
- **Inputs / options:** `enabled` (bool, default `False`); `token`; `api_key`; `home_channel`; `reply_to_mode` (`"off"` | `"first"` (default) | `"all"`); `gateway_restart_notification` (bool, default `True`); `typing_indicator` (bool, default `True`); `typing_status_text` (str | None); `channel_overrides` (map channel-id → `ChannelOverride`); `extra` (free-form dict, everything platform-specific).
- **Outputs / side effects:** `to_dict()` emits `enabled`, `extra`, `reply_to_mode`, `gateway_restart_notification`, `typing_indicator`, and optionally `typing_status_text`, `token`, `api_key`, `home_channel`, `channel_overrides`.
- **Config / env:** `TELEGRAM_REPLY_TO_MODE`, `DISCORD_REPLY_TO_MODE` override `reply_to_mode` per platform.
- **Edge cases / guards:** `gateway_restart_notification`, `typing_indicator`, `typing_status_text` are accepted at top level *or* inside `extra` (bridged by the shared-key loop). Booleans go through `_coerce_bool` which accepts `true/1/yes/on` and `false/0/no/off`.
- **Rebuild notes:** Keep credentials, routing, and cosmetics in one per-platform record; accept both nesting shapes to be forgiving.

### Platform "connected" detection  `id: gw-core.platform-connected`
- **Surface:** Core
- **Where:** startup banner "Connected Platforms" list; `get_connected_platforms()`.
- **What it does:** Decides whether an enabled platform is configured well enough to count as connected.
- **How it works:** `GatewayConfig.get_connected_platforms()` (`gateway/config.py:1040`) returns enabled platforms passing `_is_platform_connected` (`:1057`), **sorted by platform value** so the rendered list is byte-stable across restarts (prompt-cache friendliness). Rules: Weixin needs `extra.account_id` AND (`token` or `extra.token`); any platform with `token` or `api_key` passes; otherwise `_PLATFORM_CONNECTED_CHECKERS` (`:900`): `whatsapp_cloud` needs `phone_number_id` + `access_token`; `signal` needs `http_url`; `api_server` needs an `extra.key` passing `has_usable_secret(min_length=16)`; `webhook` always True; `msgraph_webhook` needs non-blank `client_state`; `bluebubbles` needs `server_url` + `password`; `qqbot` needs `app_id` + `client_secret`; `yuanbao` needs `app_id` + `app_secret`; `relay` needs `extra.relay_url` or `extra.url`. Plugin platforms fall through to `platform_registry` `is_connected` → `validate_config` → `True`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Drives the connected-platform list injected into the agent's context.
- **Config / env:** n/a
- **Edge cases / guards:** Plugin discovery (`discover_plugins()`) is forced (idempotent) so direct `GatewayConfig(...)` construction still works.
- **Rebuild notes:** A per-platform predicate table plus a generic token check; always sort output deterministically.

### Empty & placeholder token guards  `id: gw-core.token-validation`
- **Surface:** Core
- **Where:** gateway startup logs.
- **What it does:** Warns on empty bot tokens and refuses to start an adapter whose token is an obvious placeholder.
- **How it works:** `_validate_gateway_config()` (`gateway/config.py:1921`). `PLATFORM_TOKEN_ENV_NAMES` (`:632`) maps `TELEGRAM→TELEGRAM_BOT_TOKEN`, `DISCORD→DISCORD_BOT_TOKEN`, `SLACK→SLACK_BOT_TOKEN`, `MATTERMOST→MATTERMOST_TOKEN`, `MATRIX→MATRIX_ACCESS_TOKEN`, `WEIXIN→WEIXIN_TOKEN`. Empty string → WARNING `"<platform> is enabled but <ENV> is empty. The adapter will likely fail to connect."`. A token failing `hermes_cli.auth.has_usable_secret(token, min_length=4)` → ERROR `"<platform> is enabled but <ENV> is set to a placeholder value ('<first6>...'). Set a real bot token before starting the gateway. The adapter will NOT be started."` and `pconfig.enabled = False`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Disables the platform in memory (config file untouched).
- **Config / env:** the six env vars above.
- **Edge cases / guards:** Also validates `session_reset.at_hour` ∈ 0–23 (else reset to 4, warning) and `idle_minutes > 0` (else 1440, warning).
- **Rebuild notes:** Fail loudly at config-load time rather than at connect time; never start an adapter that cannot authenticate.

---

## 2. `GatewayConfig` — every gateway option

### `platforms` map  `id: gw-core.cfg-platforms`
- **Surface:** Config
- **Where:** `platforms:` (or `gateway.platforms:`) in `~/.hermes/config.yaml`.
- **What it does:** Maps each `Platform` to its `PlatformConfig`.
- **How it works:** `GatewayConfig.platforms` (`gateway/config.py:933`); populated by `from_dict` which skips unknown platform names silently.
- **Inputs / options:** see `gw-core.platform-config`.
- **Outputs / side effects:** determines which adapters the gateway instantiates.
- **Config / env:** per-platform env vars (`gw-core.env-overrides`).
- **Edge cases / guards:** non-dict platform blocks are skipped.
- **Rebuild notes:** dict keyed by platform value.

### `default_reset_policy` / `session_reset`  `id: gw-core.cfg-default-reset-policy`
- **Surface:** Config
- **Where:** `session_reset:` (top level) or `gateway.session_reset:` in `config.yaml`; legacy `default_reset_policy` in `gateway.json`.
- **What it does:** Controls whether and when a chat session loses its context automatically.
- **How it works:** `@dataclass SessionResetPolicy` (`gateway/config.py:539`).
- **Inputs / options:** `mode` — `"none"` (default, never auto-reset), `"daily"`, `"idle"`, `"both"` (whichever fires first); `at_hour` (int 0–23, default `4`, local time, used by daily/both); `idle_minutes` (int, default `1440` = 24 h); `notify` (bool, default `True` — send a chat notice when an auto-reset fires); `notify_exclude_platforms` (tuple, default `("api_server", "webhook")`); `bg_process_max_age_hours` (int, default `24`).
- **Outputs / side effects:** A reset creates a new session entry; the old transcript is retained under its own session id.
- **Config / env:** `SESSION_IDLE_MINUTES`, `SESSION_RESET_HOUR` env overrides (`gateway/config.py:2668-2683`).
- **Edge cases / guards:** Default changed from `"both"` (24 h idle + daily 4 am) to `"none"` in July 2026. A live `terminal(background=true)` process normally pins its session open; a process older than `bg_process_max_age_hours` no longer blocks reset (the process is **not** killed, only ignored). `0` disables the cutoff.
- **Rebuild notes:** Two independent clocks (wall-clock hour, inactivity) with an OR; a liveness guard with an age cap.

### `reset_by_type` / `reset_by_platform`  `id: gw-core.cfg-reset-overrides`
- **Surface:** Config
- **Where:** `reset_by_type:` / `reset_by_platform:` in `~/.hermes/gateway.json` (or config.yaml under the same names).
- **What it does:** Overrides the reset policy per session type (`dm`, `group`, `thread`) or per platform.
- **How it works:** `GatewayConfig.get_reset_policy(platform, session_type)` (`gateway/config.py:1112`) resolves **platform override > type override > default**.
- **Inputs / options:** each value is a full `SessionResetPolicy` dict.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Unknown platform keys are skipped.
- **Rebuild notes:** Three-level lookup with a documented precedence.

### `reset_triggers`  `id: gw-core.cfg-reset-triggers`
- **Surface:** Config | Gateway/Telegram
- **Where:** `reset_triggers:` (top-level or `gateway.reset_triggers`); default `["/new", "/reset"]`.
- **What it does:** Chat texts that start a fresh conversation.
- **How it works:** `GatewayConfig.reset_triggers` (`gateway/config.py:941`).
- **Inputs / options:** list of strings.
- **Outputs / side effects:** matching message resets the session.
- **Config / env:** n/a
- **Edge cases / guards:** `/new` inside a Telegram topic-mode root DM is intercepted first (`gw-core.telegram-topic-lobby`).
- **Rebuild notes:** Keep the list configurable; canonical `/new` should still route through the destructive-confirm path.

### `quick_commands`  `id: gw-core.cfg-quick-commands`
- **Surface:** Config | Gateway/Telegram
- **Where:** `quick_commands:` (top-level or `gateway.quick_commands`) in `config.yaml`; invoked as `/<name>` in any chat.
- **What it does:** User-defined slash commands that bypass the agent loop entirely — either run a shell command or alias another command.
- **How it works:** Dispatch at `gateway/run.py:19697-19749`. `type: exec` → `asyncio.create_subprocess_shell(command, env=build_subprocess_env())` with a **30 s** timeout; stdout (or stderr if stdout empty) is decoded, stripped, run through `agent.redact.redact_sensitive_text`, and returned. `type: alias` → rewrites `event.text` to `/<target> <user args>` and falls through to normal dispatch (also pre-expanded earlier at `:18866` so alias targets reach built-in handlers).
- **Inputs / options:** per entry: `type` (`exec` | `alias`), `command` (for exec), `target` (for alias).
- **Outputs / side effects:** Returns the command output as the chat reply; env is sanitized so gateway API keys are not exposed to the subprocess.
- **Config / env:** n/a
- **Edge cases / guards:** Timeout → `"Quick command timed out (30s)."`; empty output → `"Command returned no output."`; missing `command` → `"Quick command '/<name>' has no command defined."`; missing `target` → `"Quick command '/<name>' has no target defined."`; other `type` → `"Quick command '/<name>' has unsupported type (supported: 'exec', 'alias')."`; non-dict `quick_commands` logs `"Ignoring invalid quick_commands in config.yaml (expected mapping, got <type>)"`. Quick commands are gated by the same admin/user slash-access check using the **raw typed name** (`gateway/run.py:19706`) because they are never in the command registry.
- **Rebuild notes:** Two verbs (exec, alias), sanitized env, hard timeout, redacted output, access-gated by raw name.

### `sessions_dir`  `id: gw-core.cfg-sessions-dir`
- **Surface:** Config
- **Where:** `sessions_dir:`; default `$HERMES_HOME/sessions`.
- **What it does:** Where legacy JSONL session files and the `sessions.json` routing mirror live.
- **How it works:** `gateway/config.py:947`.
- **Inputs / options:** path string.
- **Outputs / side effects:** directory creation on first write.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** primary session storage is SQLite `state.db`; this is the fallback/mirror location.
- **Rebuild notes:** Prefer a single DB; keep the directory only for downgrade safety.

### `write_sessions_json`  `id: gw-core.cfg-write-sessions-json`
- **Surface:** Config
- **Where:** `write_sessions_json:` / `gateway.write_sessions_json:`; default `true`.
- **What it does:** Keeps writing the legacy `sessions.json` mirror of the gateway routing index.
- **How it works:** `gateway/config.py:955`. Primary copy is the `gateway_routing` table in `state.db`.
- **Inputs / options:** bool.
- **Outputs / side effects:** `$HERMES_HOME/sessions/sessions.json`.
- **Config / env:** n/a
- **Edge cases / guards:** set `false` to stop producing the file; external tooling that reads it breaks.
- **Rebuild notes:** Dual-write behind a flag during a storage migration.

### `always_log_local`  `id: gw-core.cfg-always-log-local`
- **Surface:** Config
- **Where:** `always_log_local:` / `gateway.always_log_local:`; default `true`.
- **What it does:** Always saves cron job outputs to local files in addition to platform delivery.
- **How it works:** `gateway/config.py:962`; consumed by `gateway/delivery.py`.
- **Inputs / options:** bool.
- **Outputs / side effects:** files under `$HERMES_HOME`.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Local audit copy of every delivered artifact.

### `filter_silence_narration`  `id: gw-core.cfg-filter-silence-narration`
- **Surface:** Config
- **Where:** `filter_silence_narration:` / `gateway.filter_silence_narration:`; default `true`.
- **What it does:** Drops outbound messages that are pure "silence narration" — `*(silent)*`, `_silent_`, `` `silent` ``, `~silent~`, `(silent)`, a bare `.`, or 🔇 — before they reach the chat.
- **How it works:** `gateway/config.py:970`; regex in `gateway/delivery.py:30`. Substrate-level guard so a persona prompt drift cannot flood bot-to-bot channels.
- **Inputs / options:** bool.
- **Outputs / side effects:** Nothing is sent; the turn still exists in history.
- **Config / env:** n/a
- **Edge cases / guards:** Set `false` for raw passthrough.
- **Rebuild notes:** Separate "model said nothing useful" from the explicit silence-token contract (`gw-core.silence-tokens`).

### `stt_enabled`  `id: gw-core.cfg-stt-enabled`
- **Surface:** Config
- **Where:** `stt.enabled:` or `stt_enabled:` (top-level or under `gateway:`); default `true`.
- **What it does:** Auto-transcribes inbound voice messages before the agent sees them.
- **How it works:** `gateway/config.py:975`; consumed by `_enrich_message_with_transcription` (`gateway/run.py:26679`).
- **Inputs / options:** bool.
- **Outputs / side effects:** the transcript becomes the user message text.
- **Config / env:** n/a
- **Edge cases / guards:** With STT off, a voice message reaches the agent as a media placeholder.
- **Rebuild notes:** Transcribe at ingress so every downstream stage sees text.

### `stt_echo_transcripts`  `id: gw-core.cfg-stt-echo`
- **Surface:** Config
- **Where:** `stt.echo_transcripts:` or `stt_echo_transcripts:`; default `true`.
- **What it does:** Echoes the raw transcript of a voice note back into the chat so the user can see what was heard.
- **How it works:** `gateway/config.py:976`; `_should_echo_stt_transcripts()` (`gateway/run.py:24090`), `_echo_pending_stt_transcripts_once` (`:26860`).
- **Inputs / options:** bool.
- **Outputs / side effects:** one extra chat message per voice input.
- **Config / env:** n/a
- **Edge cases / guards:** Echo is emitted at most once per pending event.
- **Rebuild notes:** Make the echo suppressible without disabling transcription.

### `group_sessions_per_user`  `id: gw-core.cfg-group-sessions-per-user`
- **Surface:** Config
- **Where:** `group_sessions_per_user:` (top-level or `gateway.`); default `true`.
- **What it does:** Gives each participant in a group/channel their own isolated session.
- **How it works:** `gateway/config.py:980`; consumed by `build_session_key` (`gateway/session.py:1090`) — appends the participant id to the key.
- **Inputs / options:** bool.
- **Outputs / side effects:** more sessions, no cross-user context bleed.
- **Config / env:** n/a
- **Edge cases / guards:** Ignored inside threads unless `thread_sessions_per_user` is on.
- **Rebuild notes:** Isolation policy belongs in the key builder, not in the store.

### `thread_sessions_per_user`  `id: gw-core.cfg-thread-sessions-per-user`
- **Surface:** Config
- **Where:** `thread_sessions_per_user:`; default `false`.
- **What it does:** When `false` (default) a thread/topic is a *shared* conversation across all participants; when `true` each participant gets their own thread session.
- **How it works:** `gateway/config.py:981`; `build_session_key` sets `isolate_user = False` whenever an effective thread id exists and this flag is off (`gateway/session.py:1201-1206`).
- **Inputs / options:** bool.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Applies to Telegram forum topics, Discord threads, Slack threads alike.
- **Rebuild notes:** Threads are the natural shared unit; per-user is the exception.

### `max_concurrent_sessions`  `id: gw-core.cfg-max-concurrent-sessions`
- **Surface:** Config
- **Where:** `max_concurrent_sessions:` or `gateway.max_concurrent_sessions:`; default `null` (unlimited).
- **What it does:** Caps how many chat sessions may have a live agent turn simultaneously.
- **How it works:** `gateway/config.py:982`, coerced by `_coerce_optional_positive_int` (`:167`); enforced by `_claim_active_session_slot` (`gateway/run.py:10645`) which returns `_active_session_limit_message` (`:10631`) when full.
- **Inputs / options:** positive int; `0`, negative, or `null` disables.
- **Outputs / side effects:** The rejected user gets a limit message instead of a turn.
- **Config / env:** n/a
- **Edge cases / guards:** Malformed values log `"Ignoring invalid <key>=<value> (expected a positive integer; 0/null disables)"` and disable the cap; `bool` is explicitly rejected.
- **Rebuild notes:** A semaphore keyed by session with a user-visible rejection message.

### `multiplex_profiles`  `id: gw-core.cfg-multiplex-profiles`
- **Surface:** Config
- **Where:** `hermes config set gateway.multiplex_profiles true`; `gateway.multiplex_profiles:` or top-level `multiplex_profiles:`; env `GATEWAY_MULTIPLEX_PROFILES`.
- **What it does:** Makes the default profile's gateway the single inbound process that serves messages for **every** profile on the host.
- **How it works:** `gateway/config.py:1004`; 3-tier chain env > config.yaml > default `False` implemented by `_env_multiplex_profiles_override()` (`:99`). Truthy tokens `{1,true,yes,on}`, falsy `{0,false,no,off}`; blank or unrecognised → `None` (falls through to config, so an unpopulated Fly secret cannot shadow an opt-in) and logs `"Ignoring unrecognized GATEWAY_MULTIPLEX_PROFILES=… (expected one of … or …); falling back to config.yaml."`.
- **Inputs / options:** bool.
- **Outputs / side effects:** Session keys become `agent:<profile>:…` for named profiles (default stays byte-identical `agent:main:…`); HTTP-inbound platforms are served under `/p/<profile>/` on the one listener; a named-profile `hermes gateway start|run` becomes a hard error unless `--force`; one PID/lock; `hermes status -p <name>` slices per profile.
- **Config / env:** `GATEWAY_MULTIPLEX_PROFILES`.
- **Edge cases / guards:** Per-credential platforms still need one token per profile; duplicate `(platform, token)` fails startup naming both profiles. Each profile's `.env` secrets stay isolated — never unioned.
- **Rebuild notes:** Namespace the session keys, route by credential or URL prefix, and keep secret scopes per-profile.

### `multiplex_profile_allowlist`  `id: gw-core.cfg-multiplex-allowlist`
- **Surface:** Config
- **Where:** `gateway.multiplex_profile_allowlist:` (list of profile names); default `null`.
- **What it does:** Restricts which named profiles the multiplexer serves.
- **How it works:** `_normalize_multiplex_profile_allowlist` (`gateway/config.py:46`) — `None` preserves serve-all; a non-list logs `"Invalid gateway.multiplex_profile_allowlist (expected a list, got <type>); serving only the default profile"` and fails safe to `[]`; entries are normalized + validated with `hermes_cli.profiles.normalize_profile_name` / `validate_profile_name`; `"default"` and duplicates are dropped; invalid entries log `"Skipping invalid gateway.multiplex_profile_allowlist entry <repr>"`.
- **Inputs / options:** list of profile names.
- **Outputs / side effects:** The served set also controls `/p/<profile>/` prefixes, runtime status, profile-route eligibility, and which profiles the in-process cron scheduler ticks.
- **Config / env:** n/a
- **Edge cases / guards:** The default profile is always served. A profile outside the allowlist may still run its own standalone gateway. Empty list = default only.
- **Rebuild notes:** Normalize-and-drop rather than reject; fail safe to the smallest set.

### `profile_routes`  `id: gw-core.cfg-profile-routes`
- **Surface:** Config
- **Where:** `gateway.profile_routes:` (or top-level `profile_routes:`) — a list of route dicts.
- **What it does:** Routes specific guilds/channels/threads of a **shared** bot token to different profiles.
- **How it works:** `gateway/profile_routing.py`; parsed by `parse_profile_routes()`, resolved per message by `GatewayRunner._profile_name_for_source` (`gateway/run.py:29996`). Matching priority: `platform+chat_id+thread_id` (specificity 14) > `platform+chat_id` (6) > `platform+guild_id` (2) > no match. All declared fields must hold (AND). Parent-chain matching: a route keyed on a channel also matches threads/forum posts whose `parent_chat_id` is that channel.
- **Inputs / options:** per route: `name` (label), `platform`, `profile` (target), and any of `guild_id`, `chat_id`, `thread_id`.
- **Outputs / side effects:** The routed profile gets full isolation (config, skills, memory, credentials, session namespace).
- **Config / env:** requires `gateway.multiplex_profiles: true` — with multiplexing off routes are ignored.
- **Edge cases / guards:** If an explicit route matches but the target profile is not installed or is outside the allowlist, the gateway **rejects that ingress** (logs the route + target) and does **not** fall back to the default profile — `source.profile_route_rejected = True` and the message is dropped with `"Dropping inbound message because its explicit profile route targets an unserved profile"` (`gateway/run.py:18083`). Traffic matching no route keeps default-profile behaviour. Works on every adapter, not just Discord.
- **Rebuild notes:** Specificity-scored rule matching with a fail-closed miss for explicitly-routed traffic.

### `room_link_url`  `id: gw-core.cfg-room-link-url`
- **Surface:** Config
- **Where:** `room_link_url:` or `gateway.room_link_url:`; default `null`.
- **What it does:** Publishes the public HTTPS endpoint another gateway may use for scoped RoomLink calls.
- **How it works:** `gateway/config.py:1012`; non-string values are coerced to `None`.
- **Inputs / options:** URL string.
- **Outputs / side effects:** Advertises a route; **disabled by default** so an API key alone never exposes one.
- **Config / env:** `HERMES_ROOM_LINK_URL` operator override.
- **Edge cases / guards:** Hosted-rooms detail is a sibling shard's scope.
- **Rebuild notes:** Never derive a public advertisement from the presence of a credential.

### `systemd_watchdog_seconds`  `id: gw-core.cfg-systemd-watchdog`
- **Surface:** Config
- **Where:** `gateway.systemd_watchdog_seconds:` in `~/.hermes/config.yaml`; then `hermes gateway install --force` to regenerate the unit.
- **What it does:** Opt-in systemd event-loop watchdog: a positive value makes the generated unit use `Type=notify`, `NotifyAccess=main` and a matching `WatchdogSec`; Hermes only heartbeats while the asyncio loop is making timely progress, so systemd restarts a wedged process.
- **How it works:** `gateway/config.py:1017`, coerced by `coerce_systemd_watchdog_seconds` (`:206`, clamped to `_SYSTEMD_WATCHDOG_MAX_SECONDS = 2_147_483_647`); heartbeats sent via `gateway/systemd_notify.py`.
- **Inputs / options:** int seconds; `0` (default) keeps `Type=simple` and disables sd_notify.
- **Outputs / side effects:** Regenerated unit file; `WATCHDOG=1` datagrams to `$NOTIFY_SOCKET`.
- **Config / env:** `NOTIFY_SOCKET` (set by systemd; `@abstract` notation translated by `_notify_address`).
- **Edge cases / guards:** Linux/systemd only; an ordinary platform network disconnect is not treated as loop failure. Notification failures are non-fatal.
- **Rebuild notes:** Only heartbeat from *on* the loop, never from a helper thread, or the watchdog is meaningless.

### In-process loop watchdog  `id: gw-core.cfg-loop-watchdog`
- **Surface:** Config
- **Where:** `gateway.loop_watchdog`, `gateway.loop_watchdog_probe_interval_s`, `gateway.loop_watchdog_probe_timeout_s`, `gateway.loop_watchdog_max_strikes` (also accepted top-level).
- **What it does:** A daemon OS thread probes the gateway event loop with `call_soon_threadsafe`; after N consecutive missed probes it dumps all-thread stacks and hard-exits with the service-restart code so the supervisor revives the process.
- **How it works:** `gateway/config.py:1019-1030` + `gateway/shutdown_watchdog.py`; started by `_start_loop_liveness_guards` (`gateway/run.py:13239`), stopped by `_stop_loop_liveness_guards` (`:13284`). Uses an off-loop heartbeat write plus a two-witness probe so the watchdog's own fsync cannot self-trip.
- **Inputs / options:** `loop_watchdog` (bool, default `true`); `loop_watchdog_probe_interval_s` (float, default `30.0`, valid 1.0–3600.0); `loop_watchdog_probe_timeout_s` (float, default `10.0`, valid 1.0–600.0); `loop_watchdog_max_strikes` (int, default `3`, valid 1–1000).
- **Outputs / side effects:** `faulthandler` stack dump + `os._exit(75)`; heartbeat file `$HERMES_HOME/state/gateway.heartbeat` rewritten every ~30 s carrying a `sample_memory()` snapshot.
- **Config / env:** n/a
- **Edge cases / guards:** Out-of-range values silently fall back to the defaults. Default 3 strikes ≈ 90–120 s of sustained block.
- **Rebuild notes:** Probe from a real OS thread; never rely on the loop to detect its own freeze.

### `unauthorized_dm_behavior`  `id: gw-core.cfg-unauthorized-dm-behavior`
- **Surface:** Config
- **Where:** `unauthorized_dm_behavior:` (global, or `gateway.`), or `platforms.<name>.unauthorized_dm_behavior`.
- **What it does:** Decides what an unknown user DMing the bot gets: a pairing code (`"pair"`) or nothing (`"ignore"`).
- **How it works:** `_normalize_unauthorized_dm_behavior` (`gateway/config.py:251`) accepts only `pair`/`ignore`; `GatewayConfig.get_unauthorized_dm_behavior(platform)` (`:1370`) and the richer `GatewayAuthorizationMixin._get_unauthorized_dm_behavior` (`gateway/authz_mixin.py:966`) resolve in order: (1) explicit per-platform value, (2) email defaults to `"ignore"`, (3) explicit global value, (4) adapter DM policy opting into pairing/silent drop, (5) **any** allowlist configured → `"ignore"`, (6) otherwise `"pair"`.
- **Inputs / options:** `"pair"` | `"ignore"`.
- **Outputs / side effects:** Pair mode sends the pairing-code message; ignore mode logs and returns silently.
- **Config / env:** any `<PLATFORM>_ALLOWED_USERS` / `GATEWAY_ALLOWED_USERS` presence flips the default to ignore.
- **Edge cases / guards:** Email is inbox-shaped, so a *global* `pair` does not opt email in — only an explicit `platforms.email.unauthorized_dm_behavior: pair`.
- **Rebuild notes:** Default to pairing only for a genuinely open gateway; presence of an allowlist is itself a signal.

### `notice_delivery`  `id: gw-core.cfg-notice-delivery`
- **Surface:** Config
- **Where:** `platforms.<name>.notice_delivery`; default `"public"`.
- **What it does:** Chooses whether gateway notices (system messages) are delivered publicly in the channel or privately.
- **How it works:** `_normalize_notice_delivery` (`gateway/config.py:260`); `GatewayConfig.get_notice_delivery(platform)` (`:1391`).
- **Inputs / options:** normalized token; default `"public"`.
- **Outputs / side effects:** routing of `_deliver_platform_notice` (`gateway/run.py:17524`).
- **Config / env:** n/a
- **Edge cases / guards:** unknown values fall back to `"public"`.
- **Rebuild notes:** Per-platform notice channel selection.

### `streaming` (StreamingConfig)  `id: gw-core.cfg-streaming`
- **Surface:** Config
- **Where:** `streaming:` (top-level) or `gateway.streaming:`; per-platform override `display.platforms.<platform>.streaming`.
- **What it does:** Turns on progressive, token-by-token delivery of the reply into the chat.
- **How it works:** `@dataclass StreamingConfig` (`gateway/config.py:774`) + `from_dict` (`:800`).
- **Inputs / options:** `enabled` (bool, default `false` — the documented master switch); `transport` (`"auto"` default | `"draft"` | `"edit"` | `"off"`); `mode` (ergonomic alias: sets the transport **and** infers `enabled` — `mode: off` disables, anything else enables; an explicit `enabled` always wins); `edit_interval` (float seconds, default `0.8`); `buffer_threshold` (int chars, default `24`); `cursor` (string, default `" ▉"`); `fresh_final_after_seconds` (float, default `0.0`).
- **Outputs / side effects:** With streaming on, the reply appears as a growing message that is edited in place (or a native Telegram draft) instead of one final send.
- **Config / env:** `DEFAULT_STREAMING_EDIT_INTERVAL = 0.8`, `DEFAULT_STREAMING_BUFFER_THRESHOLD = 24`, `DEFAULT_STREAMING_CURSOR = " ▉"` (`gateway/config.py:768-770`) — tuned for Telegram's ~1 edit/s flood envelope.
- **Edge cases / guards:** YAML 1.1 parses bare `on`/`off` as booleans; `_normalize_transport_token` (`:128`) maps `True→"auto"`, `False→"off"` so `mode: off` really disables. A bare `transport` does **not** imply `enabled`. `fresh_final_after_seconds > 0` delivers the final edit as a *fresh* message when the preview has been visible that long (Telegram only; other platforms ignore it) so the visible timestamp reflects completion.
- **Rebuild notes:** Separate "should we stream" from "how"; normalize YAML booleans before stringifying.

### `session_store_max_age_days`  `id: gw-core.cfg-session-store-max-age`
- **Surface:** Config
- **Where:** `session_store_max_age_days:`; default `90`.
- **What it does:** Prunes `SessionEntry` records older than N days from the in-memory index and `sessions.json`.
- **How it works:** `gateway/config.py:1035`; clamped to `max(value, 0)`, malformed → `90`.
- **Inputs / options:** int days; `0` disables pruning.
- **Outputs / side effects:** Pruning is invisible — a resumed chat simply gets a fresh session, exactly as if the reset policy had fired.
- **Config / env:** n/a
- **Edge cases / guards:** Only the routing index is pruned, not the durable transcripts.
- **Rebuild notes:** Bound the routing index, keep transcripts.

### `gateway.delivery_ledger`  `id: gw-core.cfg-delivery-ledger`
- **Surface:** Config
- **Where:** `gateway.delivery_ledger:` in `config.yaml`; default `true`.
- **What it does:** Master switch for the durable at-least-once redelivery of final agent responses across crashes/restarts.
- **How it works:** `gateway/delivery_ledger.py`; consumed by `_claim_pending_obligations` / `_redeliver_claimed_obligations` (`gateway/run.py:12829`, `:12893`). See `gw-core.delivery-ledger`.
- **Inputs / options:** bool.
- **Outputs / side effects:** Setting `false` restores the old behaviour — in-flight responses are lost on crash.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Ledger the send, not the turn.

### `gateway.platform_connect_timeout`  `id: gw-core.cfg-platform-connect-timeout`
- **Surface:** Config
- **Where:** `gateway.platform_connect_timeout:`; default `30` (seconds).
- **What it does:** Bounds how long a single adapter `connect()` may take before the gateway gives up on it.
- **How it works:** Bridged to an internal env var at `gateway/run.py:2884-2896`; read by `_platform_connect_timeout_secs(platform, initial=…)` (`:8292`) and applied by `_connect_adapter_with_timeout` (`:8321`) / `_connect_initial_adapter_with_timeout` (`:8363`).
- **Inputs / options:** seconds.
- **Outputs / side effects:** A timed-out adapter goes to the reconnect watcher instead of blocking startup.
- **Config / env:** n/a
- **Edge cases / guards:** Separate initial vs. reconnect budgets.
- **Rebuild notes:** Every adapter connect must be time-boxed or one slow platform stalls the whole gateway.

### `gateway.signal_interrupt_grace_timeout`  `id: gw-core.cfg-signal-interrupt-grace`
- **Surface:** Config
- **Where:** `gateway.signal_interrupt_grace_timeout:`; default `1` second.
- **What it does:** Grace period after a shutdown signal interrupts running agents before teardown proceeds.
- **How it works:** `_load_signal_interrupt_grace_timeout()` (`gateway/run.py:10432`); constant mirrored in `gateway/restart.py:27`. A second, fixed `DEFAULT_GATEWAY_POST_INTERRUPT_GRACE_TIMEOUT = 5.0` (`gateway/restart.py:29`) governs `_post_interrupt_grace_timeout()` (`gateway/run.py:10453`).
- **Inputs / options:** seconds.
- **Outputs / side effects:** longer graces let agents flush transcripts.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Interrupt, wait briefly, then force.

### `gateway.max_inbound_media_bytes`  `id: gw-core.cfg-max-inbound-media`
- **Surface:** Config
- **Where:** `gateway.max_inbound_media_bytes:`; default `134217728` (128 MiB).
- **What it does:** Caps the size of an inbound attachment the gateway will download and hand to the agent.
- **How it works:** consumed by the adapters' media-download path (`gateway/platforms/base.py`).
- **Inputs / options:** bytes.
- **Outputs / side effects:** oversized media is rejected instead of downloaded.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Cap at ingress, before the bytes hit disk.

### Media-delivery policy (`gateway.strict`, `media_delivery_allow_dirs`, `trust_recent_files`)  `id: gw-core.cfg-media-policy`
- **Surface:** Config
- **Where:** `gateway.strict:` (default `false`), `gateway.media_delivery_allow_dirs:` (default `[]`), `gateway.trust_recent_files:` (default `true`), `gateway.trust_recent_files_seconds:` (default `600`).
- **What it does:** Governs which local file paths the gateway is allowed to attach to an outbound chat message.
- **How it works:** `gateway/media_policy.py::apply_media_policy_env()` translates these to env vars `HERMES_MEDIA_DELIVERY_STRICT`, `HERMES_MEDIA_ALLOW_DIRS`, `HERMES_MEDIA_TRUST_RECENT_FILES`, which `validate_media_delivery_path` in `gateway/platforms/base.py` reads. The helper is idempotent and is called by gateway startup **and** by every standalone delivery entrypoint (`hermes cron run`, `hermes send`, a standalone cron tick) so manual and scheduled runs filter media under identical policy.
- **Inputs / options:** `strict` bool; `media_delivery_allow_dirs` list of directories; `trust_recent_files` bool; `trust_recent_files_seconds` int.
- **Outputs / side effects:** Disallowed attachments are silently dropped (text is unaffected).
- **Config / env:** An explicitly-set environment variable **wins** over config.yaml; the helper refuses to overwrite a pre-existing env value.
- **Edge cases / guards:** Before this shared helper existed, non-gateway delivery paths used different policy and silently dropped attachments in strict deployments.
- **Rebuild notes:** One policy translator shared by every delivery entrypoint.

### `gateway.message_timestamps.enabled`  `id: gw-core.cfg-message-timestamps`
- **Surface:** Config
- **Where:** `gateway.message_timestamps.enabled:`; default `false`.
- **What it does:** Prepends a human-readable send time (e.g. `[Tue 2026-04-28 13:40:53 CEST]`) to each **user** message *in the model's context* so the agent can reason temporally.
- **How it works:** `_message_timestamps_enabled(user_config)` (`gateway/run.py:1791`); rendering + idempotence in `gateway/message_timestamps.py` — `_HUMAN_TIMESTAMP_RE` matches the current format and `_ISO_TIMESTAMP_RE` the older `[2026-04-13T17:02:06+0200]` form, so replay never accumulates duplicate prefixes.
- **Inputs / options:** bool.
- **Outputs / side effects:** Never added to assistant messages or the system prompt. Persisted transcripts stay clean — the timestamp is stored as message *metadata* regardless of the toggle, so enabling it later also surfaces send-times for past messages.
- **Config / env:** n/a
- **Edge cases / guards:** `coerce_message_timestamp` accepts epoch numbers, datetimes, ISO strings, and both legacy prefix formats.
- **Rebuild notes:** Store the timestamp as metadata; render it at prompt-build time, never into stored content.

### `gateway.scale_to_zero.idle_timeout_minutes`  `id: gw-core.cfg-scale-to-zero-timeout`
- **Surface:** Config
- **Where:** `gateway.scale_to_zero.idle_timeout_minutes:`; default `2`.
- **What it does:** How many minutes of inbound quiet must pass before the gateway self-suspends (hosted/relay deployments).
- **How it works:** `_scale_to_zero_idle_timeout_seconds()` (`gateway/run.py:9316`) + `gateway/scale_to_zero.py`.
- **Inputs / options:** minutes.
- **Outputs / side effects:** After the quiesce the machine suspends itself via the local Fly Machines API socket.
- **Config / env:** Per-instance **enable** is gated solely by the `HERMES_SCALE_TO_ZERO` env stamp (the NAS "Labs" toggle), not by config.
- **Edge cases / guards:** See `gw-core.scale-to-zero` for the full arming predicate.
- **Rebuild notes:** Split "may I scale to zero" (operator stamp) from "when" (user config).

### `gateway.restart_loop_guard.*`  `id: gw-core.cfg-restart-loop-guard`
- **Surface:** Config
- **Where:** `gateway.restart_loop_guard.max_restarts:` (default `3`), `.window_seconds:` (default `60`), `.max_gap_seconds:` (default `300`).
- **What it does:** Circuit breaker that stops auto-resuming a restart-interrupted session when the gateway keeps being killed.
- **How it works:** `gateway/restart_loop_guard.py`; config read by `_restart_loop_guard_config()` (`gateway/run.py:9330`). Each boot with restart-interrupted sessions pending records a timestamp in `$HERMES_HOME/gateway/restart_loop.json`; boots *chain* while consecutive gaps stay within `max_gap_seconds`, so both a ~10 s respawn loop and a slow ~150 s wedge-kill cycle are detected.
- **Inputs / options:** three ints.
- **Outputs / side effects:** When tripped the gateway still starts and serves real inbound messages — it only **skips auto-resume** for that boot, breaking the cycle.
- **Config / env:** n/a
- **Edge cases / guards:** Any read/write failure fails **open** (no false trip) — a broken breaker must never wedge a healthy gateway.
- **Rebuild notes:** Persist the chain across processes; fail open.

### `gateway.respawn_storm.*`  `id: gw-core.cfg-respawn-storm`
- **Surface:** Config
- **Where:** `gateway.respawn_storm.max_starts:` (default `5`), `.window_seconds:` (default `120`).
- **What it does:** Detects a supervisor respawn storm and applies an exponential startup backoff.
- **How it works:** `gateway/status.py:72 record_start_and_check_storm(max_starts, window_s, backoff_cap_s=300.0)` appends the UTC start timestamp to a starts-log, prunes to the window, ring-buffers the file to `max(max_starts*4, 40)` entries, and returns `StormInfo(count, window_s, backoff_s)` when `len(recent) > max_starts`. Backoff = `min(300.0, 5.0 * 2**min(count-max_starts, 6))`.
- **Inputs / options:** two ints (+ internal `backoff_cap_s`).
- **Outputs / side effects:** startup sleeps for `backoff_s`.
- **Config / env:** n/a
- **Edge cases / guards:** Any bookkeeping failure is logged at DEBUG and swallowed — never crashes startup.
- **Rebuild notes:** Sliding-window counter + capped exponential backoff, best-effort.

### `gateway.api_server.max_concurrent_runs`  `id: gw-core.cfg-api-max-runs`
- **Surface:** Config
- **Where:** `gateway.api_server.max_concurrent_runs:`; default `10`.
- **What it does:** Caps simultaneous `/v1/runs` executions on the API-server platform.
- **How it works:** read by the API-server adapter; the gateway's `_active_api_run_count()` (`gateway/run.py:9239`) and `_interrupt_api_server_runs(reason)` (`:9253`) participate in drain/shutdown accounting.
- **Inputs / options:** int.
- **Outputs / side effects:** excess runs are rejected.
- **Config / env:** n/a
- **Edge cases / guards:** API-server route detail belongs to the automation shard.
- **Rebuild notes:** n/a

### Environment-variable overrides for platforms  `id: gw-core.env-overrides`
- **Surface:** Env
- **Where:** process environment / `~/.hermes/.env`.
- **What it does:** Enables and configures each platform from environment alone, overriding `config.yaml`.
- **How it works:** `_apply_env_overrides(config)` (`gateway/config.py:1983`). `_enable_from_env(platform)` creates a `PlatformConfig(enabled=True)` when the credential env var is present, respecting an explicit `enabled: false` marked by `extra["_enabled_explicit"]`.
- **Inputs / options (grouped by platform, exhaustive for the built-ins handled in this function):**
  - **Telegram:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_REPLY_TO_MODE` (`off|first|all`), `TELEGRAM_FALLBACK_IPS`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_HOME_CHANNEL_NAME` (default `Home`), `TELEGRAM_HOME_CHANNEL_THREAD_ID`, `TELEGRAM_REQUIRE_MENTION` (bridged from top-level `require_mention`).
  - **Discord:** `DISCORD_BOT_TOKEN`, `DISCORD_HOME_CHANNEL`, `DISCORD_HOME_CHANNEL_NAME`, `DISCORD_HOME_CHANNEL_THREAD_ID`, `DISCORD_REPLY_TO_MODE`.
  - **WhatsApp (Baileys):** `WHATSAPP_ENABLED` (explicit `false|0|no` disables), `WHATSAPP_HOME_CHANNEL`, `WHATSAPP_HOME_CHANNEL_NAME`, `WHATSAPP_HOME_CHANNEL_THREAD_ID`.
  - **WhatsApp Cloud:** `WHATSAPP_CLOUD_PHONE_NUMBER_ID`, `WHATSAPP_CLOUD_ACCESS_TOKEN`, `WHATSAPP_CLOUD_APP_ID`, `WHATSAPP_CLOUD_APP_SECRET`, `WHATSAPP_CLOUD_WABA_ID`, `WHATSAPP_CLOUD_VERIFY_TOKEN`, `WHATSAPP_CLOUD_WEBHOOK_HOST`, `WHATSAPP_CLOUD_WEBHOOK_PORT`, `WHATSAPP_CLOUD_WEBHOOK_PATH`, `WHATSAPP_CLOUD_API_VERSION`, `WHATSAPP_CLOUD_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **Slack:** `SLACK_BOT_TOKEN`, `SLACK_HOME_CHANNEL`, `SLACK_HOME_CHANNEL_NAME`, `SLACK_HOME_CHANNEL_THREAD_ID`.
  - **Signal:** `SIGNAL_HTTP_URL`, `SIGNAL_ACCOUNT`, `SIGNAL_IGNORE_STORIES` (default `true`), `SIGNAL_REQUIRE_MENTION`, `SIGNAL_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **Mattermost:** `MATTERMOST_TOKEN`, `MATTERMOST_URL`, `MATTERMOST_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **Matrix:** `MATRIX_ACCESS_TOKEN`, `MATRIX_HOMESERVER`, `MATRIX_USER_ID`, `MATRIX_PASSWORD`, `MATRIX_E2EE_MODE`, `MATRIX_ENCRYPTION`, `MATRIX_DEVICE_ID`, `MATRIX_HOME_ROOM(+_NAME,+_THREAD_ID)`.
  - **Home Assistant:** `HASS_TOKEN`, `HASS_URL`.
  - **Email:** `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_IMAP_HOST`, `EMAIL_SMTP_HOST`, `EMAIL_HOME_ADDRESS(+_NAME,+_THREAD_ID)`.
  - **SMS (Twilio):** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `SMS_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **API server:** `API_SERVER_KEY` (must pass `has_usable_secret(min_length=16)`), `API_SERVER_CORS_ORIGINS`, `API_SERVER_PORT`, `API_SERVER_HOST`, `API_SERVER_MODEL_NAME`.
  - **Webhook:** `WEBHOOK_ENABLED`, `WEBHOOK_PORT`, `WEBHOOK_SECRET`.
  - **MS Graph webhook:** `MSGRAPH_WEBHOOK_ENABLED`, `MSGRAPH_WEBHOOK_PORT`, `MSGRAPH_WEBHOOK_CLIENT_STATE`, `MSGRAPH_WEBHOOK_ACCEPTED_RESOURCES`, `MSGRAPH_WEBHOOK_ALLOWED_CIDRS`.
  - **DingTalk:** `DINGTALK_CLIENT_ID`, `DINGTALK_CLIENT_SECRET`, `DINGTALK_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **Feishu/Lark:** `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_DOMAIN` (default `feishu`), `FEISHU_CONNECTION_MODE` (default `websocket`), `FEISHU_ENCRYPT_KEY`, `FEISHU_VERIFICATION_TOKEN`, `FEISHU_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **WeCom:** `WECOM_BOT_ID`, `WECOM_SECRET`, `WECOM_WEBSOCKET_URL`, `WECOM_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **WeCom callback:** `WECOM_CALLBACK_CORP_ID`, `WECOM_CALLBACK_CORP_SECRET`, `WECOM_CALLBACK_AGENT_ID`, `WECOM_CALLBACK_TOKEN`, `WECOM_CALLBACK_ENCODING_AES_KEY`, `WECOM_CALLBACK_HOST`, `WECOM_CALLBACK_PORT` (default `8645`).
  - **Weixin:** `WEIXIN_TOKEN`, `WEIXIN_ACCOUNT_ID`, `WEIXIN_BASE_URL`, `WEIXIN_CDN_BASE_URL`, `WEIXIN_DM_POLICY`, `WEIXIN_GROUP_POLICY`, `WEIXIN_ALLOWED_USERS`, `WEIXIN_GROUP_ALLOWED_USERS`, `WEIXIN_SPLIT_MULTILINE_MESSAGES`, `WEIXIN_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **BlueBubbles:** `BLUEBUBBLES_SERVER_URL`, `BLUEBUBBLES_PASSWORD`, `BLUEBUBBLES_WEBHOOK_HOST` (default `127.0.0.1`), `BLUEBUBBLES_WEBHOOK_PORT` (default `8645`), `BLUEBUBBLES_WEBHOOK_PATH` (default `/bluebubbles-webhook`), `BLUEBUBBLES_SEND_READ_RECEIPTS` (default `true`), `BLUEBUBBLES_REQUIRE_MENTION`, `BLUEBUBBLES_MENTION_PATTERNS`, `BLUEBUBBLES_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **QQ bot:** `QQ_APP_ID`, `QQ_CLIENT_SECRET`, `QQ_ALLOWED_USERS`, `QQ_GROUP_ALLOWED_USERS`, `QQBOT_HOME_CHANNEL` (legacy `QQ_HOME_CHANNEL` accepted with a one-time warning), `QQBOT_HOME_CHANNEL_NAME`, `QQBOT_HOME_CHANNEL_THREAD_ID` / `QQ_HOME_CHANNEL_THREAD_ID`.
  - **Yuanbao:** `YUANBAO_APP_ID` (or legacy `YUANBAO_APP_KEY`), `YUANBAO_APP_SECRET`, `YUANBAO_BOT_ID`, `YUANBAO_WS_URL`, `YUANBAO_API_DOMAIN`, `YUANBAO_ROUTE_ENV`, `YUANBAO_DM_POLICY`, `YUANBAO_DM_ALLOW_FROM`, `YUANBAO_GROUP_POLICY`, `YUANBAO_GROUP_ALLOW_FROM`, `YUANBAO_HOME_CHANNEL(+_NAME,+_THREAD_ID)`.
  - **Session:** `SESSION_IDLE_MINUTES`, `SESSION_RESET_HOUR`.
  - **Relay:** `GATEWAY_RELAY_URL`, `GATEWAY_RELAY_ALLOW_DIRECT_PLATFORMS`.
  - **Multiplex:** `GATEWAY_MULTIPLEX_PROFILES`.
- **Outputs / side effects:** May create `PlatformConfig` entries that were absent from `config.yaml`; seeds `extra` dicts; sets `home_channel`s.
- **Config / env:** n/a
- **Edge cases / guards:** After all built-ins, a **registry-driven enable pass** runs for plugin platforms: it seeds candidate extras from `env_enablement_fn`, consults `is_connected` only for platforms not already enabled, respects an explicit `enabled: false`, and verifies dependencies **last** via a passive `check_fn` probe (never installs). `_enabled_explicit` markers are cleared at the end.
- **Rebuild notes:** Env is the highest-precedence layer; never let env presence override an explicit user `enabled: false`.

### Relay-exclusive mode  `id: gw-core.relay-exclusive`
- **Surface:** Env | Config
- **Where:** `GATEWAY_RELAY_URL` env stamp or `gateway.relay_url` in config; opt-out `GATEWAY_RELAY_ALLOW_DIRECT_PLATFORMS=true`.
- **What it does:** When a connector-fronted relay endpoint is configured, direct platform adapters are suppressed so the connector is the single ingress.
- **How it works:** `gateway/config.py:2841-2880`. The env stamp marks a connector-fronted deployment; deployments that configure relay only via `gateway.relay_url` in config are treated the same way. `getenv` (not raw `os.environ`) is used so multiplexed profiles see their own values.
- **Inputs / options:** URL string; boolean opt-out.
- **Outputs / side effects:** Direct adapters are not started.
- **Config / env:** as above.
- **Edge cases / guards:** EXPERIMENTAL — the relay platform and its descriptor schema may change without deprecation.
- **Rebuild notes:** One ingress owner at a time, with an explicit escape hatch.

---

## 3. Inbound message pipeline (`GatewayRunner._handle_message`)

### The inbound message pipeline  `id: gw-core.message-pipeline`
- **Surface:** Core
- **Where:** every inbound chat message on every platform.
- **What it does:** One ordered gauntlet every message passes before it can become an agent turn.
- **How it works:** `GatewayRunner._handle_message(event)` (`gateway/run.py:18034`). Order, exactly as coded: (1) reset session ContextVars (cross-session leak guard); (2) resolve profile route / drop explicitly-rejected route; (3) mark internal events; (4) Slack ignored-channel guard; (5) startup-restore queueing; (6) scale-to-zero inbound clock stamp; (7) `pre_gateway_dispatch` plugin hook; (8) authorization (`_is_user_authorized_for_source`) + DM pairing; (9) global emergency-stop gate; (10) pending `/update` prompt interception; (11) pending clarify interception; (12) pending slash-confirm interception; (13) stale-running-agent eviction; (14) durable-reaped session eviction; (15) busy fast-path (running agent) → busy slash dispatch / photo batching / Telegram follow-up grace / pending sentinel / drain reply / queue|steer|redirect|interrupt; (16) command resolution + alias expansion; (17) slash access control; (18) `pre_command` + `command:<name>` hooks; (19) built-in command dispatch (`_gateway_plain_command_handlers` and the explicit `canonical == …` chain); (20) drain gate; (21) user quick commands; (22) plugin slash commands; (23) skill bundles → skill slash commands → unknown-command notice; (24) Telegram topic-root lobby reminder; (25) external-drain new-turn gate; (26) active-session slot claim + run generation; (27) `_handle_message_with_agent`; (28) post-turn hooks; (29) `finally`: MoA restore, one-turn model-override restore, durable active-turn clear, running-agent release, turn-lease release.
- **Inputs / options:** a `MessageEvent` carrying `source` (`SessionSource`), `text`, `message_type` (`TEXT`, `PHOTO`, `VOICE`, …), `media_urls`, `media_types`, `message_id`, `internal`, `allow_gateway_control`.
- **Outputs / side effects:** returns the reply string (or `EphemeralReply`, or `None`/`""` for "already handled / say nothing").
- **Config / env:** everything in §2 plus `display.*`.
- **Edge cases / guards:** Internal events (background-process completions, restart replays) skip authorization, the pause gate, the drain gate, and the ignored-channel guard.
- **Rebuild notes:** Make the order explicit and testable; every guard must be able to return "silently handled".

### Cross-session ContextVar leak guard  `id: gw-core.contextvar-reset`
- **Surface:** Core
- **Where:** invisible; first statement of every message handler.
- **What it does:** Prevents a concurrently-arriving message from inheriting another chat's session identity in subprocesses.
- **How it works:** `gateway/run.py:18051-18063` calls `gateway.session_context.reset_session_vars()`. Because each message runs in an asyncio task created with `create_task()` (which snapshots the spawning `Context`), a sibling's already-set `HERMES_SESSION_*` ContextVars would otherwise be inherited until this task binds its own via `_set_session_env`.
- **Inputs / options:** n/a
- **Outputs / side effects:** ContextVars reset to `_UNSET`, so the subprocess-env bridge strips them (safe "no session") instead of leaking a sibling's identity.
- **Config / env:** n/a
- **Edge cases / guards:** Failure is logged at DEBUG and ignored.
- **Rebuild notes:** Task-local session identity + explicit reset at handler entry.

### Session context variables  `id: gw-core.session-context-vars`
- **Surface:** Core | Env
- **Where:** available to tools/subprocesses as environment-shaped names.
- **What it does:** Carries "who/where is this turn" to tools without process-global `os.environ` races.
- **How it works:** `gateway/session_context.py` defines `contextvars.ContextVar`s: `HERMES_SESSION_PLATFORM`, `HERMES_SESSION_SOURCE`, `HERMES_SESSION_CHAT_ID`, `HERMES_SESSION_CHAT_TYPE`, `HERMES_SESSION_CHAT_NAME`, `HERMES_SESSION_THREAD_ID`, `HERMES_SESSION_USER_ID`, `HERMES_SESSION_USER_ID_ALT`, `HERMES_SESSION_USER_NAME`, `HERMES_SESSION_SCOPE_ID`, `HERMES_SESSION_KEY`, `HERMES_SESSION_ID`, `HERMES_UI_SESSION_ID`, `HERMES_SESSION_MESSAGE_ID`, `HERMES_SESSION_PROFILE`, `HERMES_BROWSER_CONTROL_PRINCIPAL`, `HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY`, `HERMES_CRON_SESSION`, `HERMES_SESSION_ASYNC_DELIVERY`, `HERMES_CRON_AUTO_DELIVER_PLATFORM`, `HERMES_CRON_AUTO_DELIVER_CHAT_ID`, `HERMES_CRON_AUTO_DELIVER_THREAD_ID`.
- **Inputs / options:** helper API — `set_session_vars(...)` (returns tokens), `clear_session_vars(tokens)`, `reset_session_vars()`, `get_session_env(name, default="")`, `set_current_session_id(id)`, `scoped_current_session_id(id)`, `session_context_engaged()`, `session_is_messaging_surface()`, `declare_stateless_channel()`, `async_delivery_supported()`.
- **Outputs / side effects:** `set_current_session_id` synchronizes both the ContextVar and `os.environ` (parent-process compatibility).
- **Config / env:** n/a
- **Edge cases / guards:** Once "engaged", ContextVars are authoritative and `_UNSET` means *strip*, not *fall back to os.environ*.
- **Rebuild notes:** Task-local variables with a compatibility read shim; never process globals in a concurrent gateway.

### Slack ignored-channel guard  `id: gw-core.slack-ignored-channels`
- **Surface:** Config | Platform:Slack
- **Where:** Slack `ignored_channels` config; runs before pairing/auth/session state.
- **What it does:** Drops messages from configured Slack channels before any side effect.
- **How it works:** `_is_slack_ignored_channel(config, chat_id)` (`gateway/run.py:1784`) using `_slack_ignored_channels_from_gateway_config` (`:1756`) and `_slack_parent_channel_id` (`:1777`, so a thread inherits its parent channel's ignore); `_csv_or_list_to_set` (`:1744`) accepts a CSV string or a list.
- **Inputs / options:** channel ids (CSV or list).
- **Outputs / side effects:** logs `"Dropping Slack message from configured ignored channel <id>"` and returns `None`.
- **Config / env:** Slack platform config (adapter shard owns the exact key path).
- **Edge cases / guards:** Runs FIRST so an ignored channel can never reach pairing, auth, or session state.
- **Rebuild notes:** Ignore lists must run before anything that mutates state.

### Startup-restore queueing  `id: gw-core.startup-restore-queue`
- **Surface:** Core
- **Where:** the first seconds after a gateway restart.
- **What it does:** Holds real inbound messages while the gateway is replaying restart-interrupted sessions, then replays them in order.
- **How it works:** `_queue_startup_restore_event` (`gateway/run.py:12527`), `_drain_startup_restore_queue` (`:12543`), `_finish_startup_restore` (`:12641`), guarded by `self._startup_restore_in_progress`. Timeout from `_startup_restore_drain_timeout_secs()` (`:1371`). Warm-up of turn machinery: `_start_startup_warmup` (`:12569`), `_warm_turn_prerequisites` (`:12585`), `_await_startup_warmup` (`:12610`), `_warm_turn_machinery_sync` (`:1429`), budget `_startup_warmup_timeout_secs()` (`:1404`).
- **Inputs / options:** n/a
- **Outputs / side effects:** No reply is sent while queued; the message is processed once restore finishes.
- **Config / env:** internal timeouts.
- **Edge cases / guards:** Internal events and replay events themselves bypass the queue.
- **Rebuild notes:** Quiesce ingress during recovery instead of interleaving.

### `pre_gateway_dispatch` plugin hook  `id: gw-core.pre-gateway-dispatch-hook`
- **Surface:** Core
- **Where:** plugin authors; fires for every user-originated inbound message **before authorization**.
- **What it does:** Lets a plugin drop, rewrite, or explicitly allow an inbound message — including from unauthorized senders (e.g. a customer-handover ingest) without triggering pairing.
- **How it works:** `hermes_cli.lifecycle.invoke_hook("pre_gateway_dispatch", event=…, gateway=self, session_store=…)` (`gateway/run.py:18130-18168`). Each returned dict is inspected in order.
- **Inputs / options:** return `{"action": "skip", "reason": …}` → drop with no reply (logs `"pre_gateway_dispatch skip: reason=… platform=… chat=…"`); `{"action": "rewrite", "text": …}` → replace `event.text` and continue (breaks the loop); `{"action": "allow"}` or `None` → normal dispatch.
- **Outputs / side effects:** may replace the event via `dataclasses.replace(event, text=…)`.
- **Config / env:** plugin installation.
- **Edge cases / guards:** Hook exceptions log `"pre_gateway_dispatch invocation failed: …"` and dispatch continues.
- **Rebuild notes:** Give plugins one pre-auth veto/rewrite point and make failures non-fatal.

### User authorization & allowlists  `id: gw-core.authorization`
- **Surface:** Core | Env
- **Where:** every inbound message from a real user.
- **What it does:** Decides whether a sender may talk to the bot at all. **Default: deny.**
- **How it works:** `GatewayAuthorizationMixin._is_user_authorized(source, allow_adapter_delegation=True)` (`gateway/authz_mixin.py:488`). Order: (a) `homeassistant` and `webhook` platforms are always authorized (HASS_TOKEN / HMAC authenticate the connection); (b) relay/upstream delegation — a `source.delivered_via_upstream_relay is True` marker or an adapter declaring `authorization_is_upstream=True`; (c) chat-scoped group allowlists (`TELEGRAM_GROUP_ALLOWED_CHATS`, `QQ_GROUP_ALLOWED_USERS`, then adapter `extra.group_allowed_chats`) — these run **before** the no-user-id guard so anonymous admin posts / channel broadcasts work; (d) `{PLATFORM}_ALLOW_BOTS` ∈ `{mentions, all}` for `DISCORD_ALLOW_BOTS`, `FEISHU_ALLOW_BOTS`, `TELEGRAM_ALLOW_BOTS`, `SLACK_ALLOW_BOTS`; (e) no `user_id` → deny; (f) per-platform allow-all flag; (g) adapter-verified role auth (`source.role_authorized is True`, e.g. `DISCORD_ALLOWED_ROLES`); (h) pairing store approval; (i) env allowlists; (j) adapter `allow_from` / `group_allow_from` / `allowed_users` from config.yaml; (k) `GATEWAY_ALLOW_ALL_USERS`; (l) deny.
- **Inputs / options:** Per-platform user allowlists: `TELEGRAM_ALLOWED_USERS`, `DISCORD_ALLOWED_USERS`, `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_CLOUD_ALLOWED_USERS`, `SLACK_ALLOWED_USERS`, `SIGNAL_ALLOWED_USERS`, `EMAIL_ALLOWED_USERS`, `SMS_ALLOWED_USERS`, `MATTERMOST_ALLOWED_USERS`, `MATRIX_ALLOWED_USERS`, `DINGTALK_ALLOWED_USERS`, `FEISHU_ALLOWED_USERS`, `WECOM_ALLOWED_USERS`, `WECOM_CALLBACK_ALLOWED_USERS`, `WEIXIN_ALLOWED_USERS`, `BLUEBUBBLES_ALLOWED_USERS`, `QQ_ALLOWED_USERS`, `YUANBAO_ALLOWED_USERS`, plus plugin-declared `allowed_users_env`. Group-scoped: `TELEGRAM_GROUP_ALLOWED_USERS`, `TELEGRAM_GROUP_ALLOWED_CHATS`, `QQ_GROUP_ALLOWED_USERS`. Allow-all: `TELEGRAM_ALLOW_ALL_USERS`, `DISCORD_ALLOW_ALL_USERS`, `WHATSAPP_ALLOW_ALL_USERS`, `WHATSAPP_CLOUD_ALLOW_ALL_USERS`, `SLACK_ALLOW_ALL_USERS`, `SIGNAL_ALLOW_ALL_USERS`, `EMAIL_ALLOW_ALL_USERS`, `SMS_ALLOW_ALL_USERS`, `MATTERMOST_ALLOW_ALL_USERS`, `MATRIX_ALLOW_ALL_USERS`, `DINGTALK_ALLOW_ALL_USERS`, `FEISHU_ALLOW_ALL_USERS`, `WECOM_ALLOW_ALL_USERS`, `WECOM_CALLBACK_ALLOW_ALL_USERS`, `WEIXIN_ALLOW_ALL_USERS`, `BLUEBUBBLES_ALLOW_ALL_USERS`, `QQ_ALLOW_ALL_USERS`, `YUANBAO_ALLOW_ALL_USERS`, plus plugin `allow_all_env`. Global: `GATEWAY_ALLOWED_USERS`, `GATEWAY_ALLOW_ALL_USERS`. `"*"` in any list means everyone.
- **Outputs / side effects:** Unauthorized → `"Unauthorized user: <id> (<name>) on <platform>"` WARNING; DM may get a pairing code; group is silently ignored.
- **Config / env:** as above, plus `platforms.<name>.extra.allow_from` / `group_allow_from` / `allowed_users`.
- **Edge cases / guards:** Identity normalization — WhatsApp phone↔LID aliases via `_expand_whatsapp_auth_aliases`; SimpleX matches numeric `contactId` **or** display name; Buzz (Nostr) decodes `npub…` entries to hex; `user@host` also matches the bare local part. With **no** env allowlist configured, an adapter's own policy is trusted only when the effective policy for that chat type is literally `"allowlist"` (never `"open"` or `"pairing"` — trusting `open` was a fail-open bug). Adapter-resolved usernames→ids are unioned in (`resolved_allowlist_user_ids()`) so the per-turn `.env` hot-reload cannot un-authorize an operator. Legacy shim: chat-ID-shaped (`-`-prefixed) values in `TELEGRAM_GROUP_ALLOWED_USERS` are honored as chat ids with a one-time warning.
- **Rebuild notes:** Default-deny, union of explicit grants, normalize identities before comparison, and never treat "the message reached me" as authorization.

### DM pairing  `id: gw-core.dm-pairing`
- **Surface:** Gateway/Telegram | CLI
- **Where:** an unknown user DMs the bot; approval via `hermes pairing approve <platform> <CODE>`.
- **What it does:** Issues a one-time code to an unknown DM sender so the owner can grant access without editing allowlists.
- **How it works:** `gateway/pairing.py` (`PairingStore`), invoked at `gateway/run.py:18192-18232`. Codes: 8 chars from a 32-char unambiguous alphabet (no `0/O/1/I`), `secrets.choice()`; 1-hour expiry; max 3 pending codes per platform; rate limit 1 request per user per 10 minutes; lockout after 5 failed approval attempts (1 hour); files `chmod 0600` under `~/.hermes/pairing/`; codes are never logged to stdout.
- **Inputs / options:** none from the user — the flow is automatic. CLI side: `hermes pairing approve <platform> <code>`, `hermes pairing list`, `hermes pairing revoke <platform> <user_id>`.
- **Outputs / side effects:** The user receives, verbatim:
  `"Hi~ I don't recognize you yet!\n\nHere's your pairing code: \`<CODE>\`\n\nAsk the bot owner to run:\n\`hermes [-p <profile> ]pairing approve <platform> <CODE>\`"`.
  When rate-limited or out of code slots: `"Too many pairing requests right now~ Please try again later!"` and a rate-limit record so subsequent messages are silently ignored.
- **Config / env:** `unauthorized_dm_behavior` must be `"pair"` for this path.
- **Edge cases / guards:** No pairing store → ERROR `"Cannot offer pairing code on <platform>: no pairing store"` and silence. In multiplex gateways the per-profile `PairingStore` is used and the printed command includes `-p <profile>`. Approving a user also writes them into the configured allowlist when one exists, keeping one operator-visible source of truth.
- **Rebuild notes:** Cryptographic short codes, hard expiry, per-user rate limit, lockout, 0600 files, and never log the code.

### Global emergency stop (`hermes pause`) gate  `id: gw-core.estop-gate`
- **Surface:** Core | CLI
- **Where:** any chat while the install is paused.
- **What it does:** Refuses to start **new** agent turns while a global pause is engaged, replying with a short paused notice instead.
- **How it works:** `agent.estop.paused_reply()` consulted at `gateway/run.py:18237-18300`. Placed **after** auth so unauthorized senders cannot probe pause state.
- **Inputs / options:** n/a
- **Outputs / side effects:** returns the paused notice text.
- **Config / env:** `hermes pause` / `/pause off`.
- **Edge cases / guards:** Passthroughs that are **never** blocked: any recognized slash command (`resolve_command()` matches), a session with `update_prompt_pending`, a session whose agent is already running (steering/interrupting in-flight work, which also covers pending clarify and tool approvals), a pending `tools.slash_confirm` prompt, and a pending blocking approval (`tools.approval.has_blocking_approval`). Internal events bypass the gate entirely — pause stops new work, it never kills running work.
- **Rebuild notes:** Pause the *start* of work, never the completion of work; keep control commands alive.

### Pending `/update` prompt interception  `id: gw-core.update-prompt-interception`
- **Surface:** Gateway/Telegram
- **Where:** a chat where `/update` is running and the detached update process asked a question.
- **What it does:** Routes the user's next chat message back to the blocked update subprocess.
- **How it works:** `gateway/run.py:18305-18395`. The update process writes `$HERMES_HOME/.update_prompt.json`; a watcher forwards it to the user; the reply is written atomically to `$HERMES_HOME/.update_response` (`.tmp` + `replace`) and the prompt file is unlinked.
- **Inputs / options:** free text; `/approve` and `/yes` map to `"y"`; `/deny` and `/no` map to `"n"`.
- **Outputs / side effects:** Replies `"✓ Sent \`<label>\` to the update process."` where `<label>` is the response truncated to 20 chars + `…`. On write failure: `"✗ Failed to send response to update process: <err>"`.
- **Config / env:** n/a
- **Edge cases / guards:** A **recognized slash command** during a pending prompt writes an empty response (so `_gateway_prompt` returns the prompt's safe default and the subprocess exits cleanly instead of blocking on stdin for the 30-minute watcher timeout), clears `update_prompt_pending`, and then falls through to normal dispatch. Requires `event.allow_gateway_control`.
- **Rebuild notes:** File-based request/response with atomic writes; always give control commands an escape.

### Pending clarify interception  `id: gw-core.clarify-interception`
- **Surface:** Gateway/Telegram
- **Where:** after the agent calls the `clarify` tool.
- **What it does:** Treats the user's next message as the answer to the open question — by number, by option text, by a comma/space list for multi-select, or as free-form prose.
- **How it works:** `tools.clarify_gateway.get_pending_for_session(key, include_choice_prompts=True)` then `attempt_text_response_for_session(key, text)` at `gateway/run.py:18400-18475`. Reply text is prepared by `_prepare_clarify_reply_text(event)` (`:20137`) which transcribes voice first.
- **Inputs / options:** a number (`2`), several numbers (`1, 3` — "Multiple selections allowed" prompts), the option text, or free-form text. Native buttons on platforms that support them. In the classic CLI/TUI, multi-select renders as checkboxes (Space toggles, Enter submits).
- **Outputs / side effects:** Outcomes: `TEXT_RESOLVED` → the clarify unblocks, the platform typing indicator is resumed via `adapter.resume_typing_for_chat(chat_id)`, and the gateway replies `""` so adapters do not double-post; `TEXT_REJECTED_SELECTION` (selection-shaped but out of range / unparseable) → the clarify stays armed and the gateway replies `""`; `TEXT_REJECTED_PROSE` (native-choice prompt, unmatched prose) → the clarify is resolved with `""` and the message continues through normal busy routing.
- **Config / env:** n/a
- **Edge cases / guards:** Messages starting with `/` are skipped so slash commands still work (the clarify stays pending; on timeout the agent unblocks with an empty response). A voice message that transcribes to nothing keeps the clarify pending and replies `""`. Requires `event.allow_gateway_control`.
- **Rebuild notes:** Three-way outcome (resolved / retry / release) is essential — a native-choice prompt must be able to let prose through without deadlocking a running tool.

### Pending slash-confirm interception  `id: gw-core.slash-confirm-interception`
- **Surface:** Gateway/Telegram
- **Where:** after a destructive slash command (e.g. `/reload-mcp`, `/new`, `/undo`) asks for confirmation.
- **What it does:** Interprets the next message as approve / always / cancel.
- **How it works:** `tools.slash_confirm.get_pending(key)` / `resolve(key, confirm_id, choice)` at `gateway/run.py:18477-18535`.
- **Inputs / options:** `once` ← commands `/approve`, `/yes`, `/ok`, `/confirm` or words `approve`, `approve once`, `once`; `always` ← `/always`, `/remember` or words `always`, `always approve`; `cancel` ← `/cancel`, `/no`, `/deny`, `/nevermind` or words `cancel`, `nevermind`, `no`. Bang-prefixed forms (`!always`, `!cancel`) are accepted verbatim because Slack/Matrix instruct users with `!` when typed `/` is blocked — the reply is normalised with `.lstrip("!/").lower()`.
- **Outputs / side effects:** returns the resolver's text (or `""`).
- **Config / env:** n/a
- **Edge cases / guards:** If a **dangerous-command tool approval** is also pending (`tools.approval.has_blocking_approval`), the tool approval wins and `/approve` unblocks the waiting tool thread instead. An unrelated command clears a stale pending confirm (`clear_if_stale`) so it never blocks normal usage. Requires `event.allow_gateway_control`.
- **Rebuild notes:** Word + command aliases, `!`-prefix tolerance, and a stale-state escape.

### Destructive slash-command confirmation  `id: gw-core.destructive-slash-confirm`
- **Surface:** Gateway/Telegram
- **Where:** `/new` and `/undo` in chat.
- **What it does:** Asks for confirmation before discarding conversation history.
- **How it works:** `_maybe_confirm_destructive_slash(event, command, title, detail, execute)` (`gateway/run.py:25485`) and `_request_slash_confirm` (`:25597`).
- **Inputs / options:** `/new` — title `"/new"`, detail `"This starts a fresh session and discards the current conversation history."`. `/undo [N]` — title `"/undo"`, detail `"This removes the last user/assistant exchange from history."` for N=1, else `"This removes the last <N> user turns from history."` (N parsed from the first argument, floored at 1, non-numeric → 1).
- **Outputs / side effects:** posts a confirm prompt; the real handler runs only after approval.
- **Config / env:** n/a
- **Edge cases / guards:** `/new` in a Telegram topic-mode root DM short-circuits to `_telegram_topic_root_new_message()` before confirmation.
- **Rebuild notes:** Wrap destructive handlers in a generic confirm decorator carrying a human-readable consequence sentence.

### Stale running-agent eviction  `id: gw-core.stale-agent-eviction`
- **Surface:** Core
- **Where:** invisible; unblocks a session whose handler hung or crashed.
- **What it does:** Frees a session that still claims a running agent but has made no progress.
- **How it works:** `gateway/run.py:18540-18600`. Timeout `HERMES_AGENT_TIMEOUT` (default `1800` s) is compared against the agent's **idle** time from `get_activity_summary()` via `gateway.session_stall.resolve_session_idle_seconds_from_activity`, not wall-clock age. When no usable activity clock exists, an emergency wall TTL of `max(timeout*10, 7200)` s applies. The `_AGENT_PENDING_SENTINEL` is never evicted.
- **Inputs / options:** env `HERMES_AGENT_TIMEOUT` (seconds; `0` disables the idle rule).
- **Outputs / side effects:** WARNING `"Evicting stale _running_agents entry for <key> (age: Xs, idle: Ys, timeout: Zs) | last_activity=… (Ns ago) | iteration=i/m"`; the run generation is invalidated (`reason="stale_running_agent_eviction"`) and the turn slot released.
- **Config / env:** `HERMES_AGENT_TIMEOUT`.
- **Edge cases / guards:** A valid activity clock is authoritative — a long but progressing turn is never evicted.
- **Rebuild notes:** Measure idleness, not duration.

### Durable-reaped session eviction  `id: gw-core.reaped-session-eviction`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Heals a session whose durable routing row was ended in `state.db` while the in-memory turn slot stayed alive, so the next message reopens/creates a session instead of queueing into a dead runtime.
- **How it works:** `gateway/run.py:18602-18650` uses the store's lock-held accessors `peek_session_id(key)` and `_is_session_ended_in_db(sid) is True`.
- **Inputs / options:** n/a
- **Outputs / side effects:** WARNING `"Evicting stale _running_agents entry for <key> — durable session <sid> is ended (reaped) in state.db; healing routing on next message"`; run generation invalidated (`reason="reaped_session_eviction"`).
- **Config / env:** n/a
- **Edge cases / guards:** Type-checked so stubbed stores keep the guard inert.
- **Rebuild notes:** Reconcile in-memory turn slots against durable session state on every message.

---

## 4. Busy handling — messaging an agent that is already working

### Busy-input mode (queue / steer / interrupt)  `id: gw-core.busy-input-mode`
- **Surface:** Config | Gateway/Telegram
- **Where:** `display.busy_input_mode:` in `~/.hermes/config.yaml`; per-profile via `display` in a profile's config.
- **What it does:** Chooses what happens when you message the bot while it is still working: redirect the active turn (default), queue the message as the next turn, or steer it into the running turn.
- **How it works:** `_load_busy_input_mode()` (`gateway/run.py:10260`), `_busy_modes_from_config` (`:10297`), `_snapshot_profile_busy_modes` (`:10324`), `_effective_busy_input_mode(source)` (`:10348`) which resolves the profile for the source via `_busy_profile_name_for_source` (`:10336`). Applied on the priority fast-path (`:18740-18860`) and in `_handle_active_session_busy_message` (`:10879`).
- **Inputs / options:** `interrupt` (default — text-only corrections use `agent.redirect()` when the runtime supports it, retaining reasoning and visible partial text as an assistant checkpoint; media/voice or older runtimes fall back to `agent.interrupt()`); `queue` — follow-ups wait and run as the next turn; `steer` — follow-ups are injected into the current run via `agent.steer()`, arriving after the next tool call (falls back to queue semantics if the payload is empty, the agent lacks `steer()`, `steer()` rejects, or the agent has not started).
- **Outputs / side effects:** See `gw-core.busy-ack` for the chat acknowledgment.
- **Config / env:** `display.busy_input_mode`, `display.busy_ack_enabled`, `display.platforms.<platform>.busy_steer_ack_enabled`.
- **Edge cases / guards:** `/stop` remains a hard stop. Running tools finish safely — a redirect is applied at the next tool-result boundary rather than killing the tool.
- **Rebuild notes:** Three distinct semantics (new turn later / inject now / restart now), with graceful downgrade between them.

### Busy acknowledgment message  `id: gw-core.busy-ack`
- **Surface:** Gateway/Telegram
- **Where:** the chat, immediately after you message a busy agent.
- **What it does:** Tells you what happened to your message.
- **How it works:** `_handle_active_session_busy_message` (`gateway/run.py:10879`, ack block at `:11168-11310`). Debounce `_BUSY_ACK_COOLDOWN = 30` seconds per session.
- **Inputs / options:** none (automatic).
- **Outputs / side effects:** Exactly one of these strings (with `<detail>` = `" (<N> min elapsed, iteration <i>/<m>, running: <tool>)"` when `busy_ack_detail` is on, else empty):
  - `"⏩ Steered into current run<detail>. Your message arrives after the next tool call."`
  - `"↪ Redirected current run<detail>. I'll adjust using your correction."`
  - `"⏳ Subagent working<detail> — your message is queued for when it finishes (use /stop to cancel everything)."`
  - `"⏳ Compressing context<detail> — your message is queued for when it finishes (use /stop to cancel everything)."`
  - `"⏳ Queued for the next turn<detail>. I'll respond once the current task finishes."`
  - `"⚡ Interrupting current task<detail>. I'll respond to your message shortly."`
- **Config / env:** `display.busy_ack_enabled` (env bridge `HERMES_GATEWAY_BUSY_ACK_ENABLED`, default `"true"`) suppresses the ack entirely while still processing the input; `display.platforms.<p>.busy_ack_detail` (default `True` globally, `False` for telegram/slack) toggles the `<detail>` suffix; `display.platforms.<p>.busy_steer_ack_enabled` (env `HERMES_GATEWAY_BUSY_STEER_ACK_ENABLED`) suppresses only the steer confirmation.
- **Edge cases / guards:** The disabled check runs **before** the debounce so a never-delivered ack does not stamp the cooldown. Reply anchoring: Telegram DMs in a topic reply to the anchor; other Telegram threads pass `reply_to=None`; elsewhere it replies to the user's message id.
- **Rebuild notes:** One line per outcome, debounce per session, and never let the ack path fail the input handling.

### First-time busy-input tip  `id: gw-core.busy-input-onboarding-tip`
- **Surface:** Gateway/Telegram
- **Where:** appended to the first busy-ack you ever see on an install.
- **What it does:** Explains the queue/interrupt/steer knob once.
- **How it works:** `agent.onboarding.busy_input_hint_gateway(mode)` appended at `gateway/run.py:11274-11300`; the flag `BUSY_INPUT_FLAG` (`onboarding.seen.busy_input_prompt`) is latched into `config.yaml` via `mark_seen()`.
- **Inputs / options:** mode is one of `steer` / `queue` / `redirect` / `interrupt`.
- **Outputs / side effects:** message becomes `"<ack>\n\n💡 First-time tip — …"`.
- **Config / env:** delete `onboarding.seen.busy_input_prompt` from `config.yaml` to see it again.
- **Edge cases / guards:** Fires once per install, across all platforms.
- **Rebuild notes:** Persist onboarding latches in the same config the user edits.

### Busy slash-command dispatch  `id: gw-core.busy-slash-dispatch`
- **Surface:** Gateway/Telegram
- **Where:** any slash command typed while an agent is running.
- **What it does:** Decides per command whether it runs mid-turn, interrupts first, or is politely rejected.
- **How it works:** `_dispatch_busy_slash_command(event, cmd_def, quick_key, source)` (`gateway/run.py:17782`). Resolution order: (1) `cmd_def.busy_handler` special handler; (2) `busy_policy in ("dispatch", "interrupt_then_dispatch")` → the shared plain handler; (3) catch-all reject.
- **Inputs / options:** Special busy handlers: `start`, `stop`, `new`, `queue`, `steer`, `egress`, `goal`, `loop`. Shared plain handlers usable mid-run (`_gateway_plain_command_handlers`, `:17756`): `status`, `context`, `restart`, `approve`, `deny`, `pause`, `agents`, `bg`, `btw`, `kanban`, `subgoal`, `heartbeat`, `busy`, `yolo`, `verbose`, `footer`, `help`, `commands`, `profile`, `update`, `version` (23 entries, exhaustive). `_BUSY_REJECT_TEXT` (`:17749`): `model` → `"Agent is running — wait or /stop first, then switch models."`; `codex-runtime` → `"Agent is running — wait or /stop first, then change runtime."`; `moa` → `"Agent is running — wait or /stop first, then run /moa."`.
- **Outputs / side effects:** Catch-all reply: ``"⏳ Agent is running — `/<name>` can't run mid-turn. Wait for the current response or `/stop` first."``
- **Config / env:** n/a
- **Edge cases / guards:** `/status` and `/context` are dispatched **before** the access gate so users always see session state; `/help` and `/whoami` are the always-allowed floor inside `_check_slash_access`. A `busy_policy` with no mid-run handler logs a WARNING and falls back to the reject text. Rejecting (rather than interrupt-then-discard) exists because Discord-registered slash commands would otherwise interrupt the agent AND be silently discarded, producing a zero-character response.
- **Rebuild notes:** Declare busy behaviour on the command definition, not in an if-chain at the call site.

### `/start` platform ping suppression  `id: gw-core.start-ping`
- **Surface:** Gateway/Telegram
- **Where:** Telegram bot launches and deep-links.
- **What it does:** Ignores `/start` instead of dumping help or interrupting.
- **How it works:** `_busy_start_command` (`gateway/run.py:17868`) and the idle-path branch (`:19012`); both log `"Ignoring /start platform ping …"` and return `""`.
- **Inputs / options:** n/a
- **Outputs / side effects:** nothing is sent.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Treat platform lifecycle pings as noise.

### `/stop` hard stop  `id: gw-core.stop-hard`
- **Surface:** Gateway/Telegram
- **Where:** `/stop` in any chat.
- **What it does:** Kills the current turn and unlocks the session even if the agent thread is wedged.
- **How it works:** `_busy_stop_command` (`gateway/run.py:17880`) → `_interrupt_and_clear_session(key, source, interrupt_reason=_INTERRUPT_REASON_STOP, invalidation_reason="stop_command")` (`:28697`). A soft `agent.interrupt()` alone is insufficient when the executor thread is blocked, so the running-agent slot is force-cleaned.
- **Inputs / options:** none.
- **Outputs / side effects:** `EphemeralReply(t("gateway.stop.stopped"))`; logs `"STOP for session <key> — agent interrupted, session lock released"`. Against the `_AGENT_PENDING_SENTINEL` it returns `EphemeralReply("⚡ Force-stopped. The agent was still starting — session unlocked.")`.
- **Config / env:** n/a
- **Edge cases / guards:** Always reachable — never gated by pause, drain, or busy policy.
- **Rebuild notes:** The escape hatch must not depend on the thing it is escaping.

### `/queue <prompt>` FIFO  `id: gw-core.queue-command`
- **Surface:** Gateway/Telegram
- **Where:** `/queue <prompt>` while the agent is running.
- **What it does:** Queues a full, separate agent turn for after the current one, in FIFO order, without merging.
- **How it works:** `_busy_queue_command` (`gateway/run.py:17914`) builds a fresh `MessageEvent` preserving `media_urls`, `media_types`, `media_text_inlined`, `reply_to_message_id`, `reply_to_text`, `reply_to_author_id`, `reply_to_author_name`, `reply_to_is_own_message`, `auto_skill`, `channel_prompt`, `channel_context`, `internal`, `timestamp`, `raw_message`, `message_id`. Storage: the adapter's `_pending_messages[session_key]` is the single "next-up" slot; the tail goes to `SessionState.conversation.queued_events`. `_enqueue_fifo` (`:9663`), `_promote_queued_event` (`:9677`), `_queue_depth` (`:9708`).
- **Inputs / options:** `<prompt>` text, or no text when the message carries media (a `/queue` caption on an image is valid).
- **Outputs / side effects:** `"Queued for the next turn."` for depth ≤ 1, otherwise `"Queued for the next turn. (<N> queued)"`. With no text and no media: `"Usage: /queue <prompt>"`.
- **Config / env:** n/a
- **Edge cases / guards:** `/new` and `/reset` clear the queue via `_handle_reset_command`. Overflow items are pushed back rather than dropped when no adapter is available.
- **Rebuild notes:** One slot + overflow list, promoted after each drain; never merge queued turns.

### `/steer <prompt>` mid-run injection  `id: gw-core.steer-command`
- **Surface:** Gateway/Telegram
- **Where:** `/steer <prompt>`.
- **What it does:** Injects text into the running agent between tool-call iterations by appending to the last tool result — no interrupt, no new user turn, no role-alternation violation.
- **How it works:** `_busy_steer_command` (`gateway/run.py:17955`) calls `running_agent.steer(text)`. With no agent running, the idle path (`:19620`) strips the prefix and sends the payload as an ordinary message.
- **Inputs / options:** `<prompt>` (required).
- **Outputs / side effects:** Success → ``"⏩ Steer queued — arrives after the next tool call: '<first 60 chars>…'"``. Rejected → `"Steer rejected (empty payload)."`. Exception → `"⚠️ Steer failed: <exc>"`. Agent still starting → `"Agent still starting — /steer queued for the next turn."`. No agent / no `steer()` → `"No active agent — /steer queued for the next turn."`. Empty payload → `"Usage: /steer <prompt>"`. Idle with empty payload → `"Usage: /steer <prompt>  (no agent is running; sending as a normal message)"`.
- **Config / env:** n/a
- **Edge cases / guards:** Every failure mode degrades to the FIFO queue rather than dropping the text.
- **Rebuild notes:** Append to the last tool result so the transcript stays role-valid.

### `/goal` and `/loop` mid-run control verbs  `id: gw-core.busy-goal-loop`
- **Surface:** Gateway/Telegram
- **Where:** `/goal …`, `/loop …` while the agent is running.
- **What it does:** Allows inspection and control verbs mid-run while rejecting a new goal/loop that would race the current turn.
- **How it works:** `_busy_goal_command` (`gateway/run.py:18004`), `_busy_loop_command` (`:18025`).
- **Inputs / options:** `/goal` allowed mid-run: no argument, or exactly `status`, `pause`, `resume`, `clear`, `stop`, `done`, `unwait`, or a first verb of `wait` / `gate`. `/loop` allowed mid-run: no argument, or `status`, `pause`, `resume`, `stop`, `clear`, `cancel`, `help`, `--help`, `-h`.
- **Outputs / side effects:** Rejections: `"Agent is running — use /goal status / pause / clear / wait mid-run, or /stop before setting a new goal."` and `"Agent is running — use /loop status / pause / stop mid-run, or /stop before setting a new loop."`
- **Config / env:** n/a
- **Edge cases / guards:** Gate edits are safe mid-run because gates run at turn boundary.
- **Rebuild notes:** Split the command's verbs into control-plane (safe) and mutation (unsafe) sets.

### Photo-burst batching  `id: gw-core.photo-burst`
- **Surface:** Gateway/Telegram
- **Where:** sending several photos at once while the agent is running.
- **What it does:** Absorbs near-simultaneous photo follow-ups into the pending slot instead of interrupting once per photo.
- **How it works:** `gateway/run.py:18726-18732` — `event.message_type == MessageType.PHOTO` on the busy fast-path calls `merge_pending_message_event(adapter._pending_messages, key, event)` and returns `None`.
- **Inputs / options:** n/a
- **Outputs / side effects:** No ack, no interrupt; the photos join the next turn.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Media bursts are one logical message; batch before deciding to interrupt.

### Telegram follow-up grace window  `id: gw-core.telegram-followup-grace`
- **Surface:** Env | Platform:Telegram
- **Where:** a Telegram text message sent within a few seconds of a turn starting.
- **What it does:** Treats a very fast follow-up as part of the same intent (queue/merge) rather than an interrupt.
- **How it works:** `gateway/run.py:18736-18762`. Window = `HERMES_TELEGRAM_FOLLOWUP_GRACE_SECONDS` (default `3.0`); measured against `SessionState.turn.started_ts`. In `queue` mode the event goes to `_enqueue_fifo`; otherwise `merge_pending_message_event(..., merge_text=True)`.
- **Inputs / options:** env `HERMES_TELEGRAM_FOLLOWUP_GRACE_SECONDS` (float seconds; `0` disables).
- **Outputs / side effects:** logs `"Telegram follow-up arrived %.2fs after run start for <key> — queueing without interrupt"`; nothing sent.
- **Config / env:** as above.
- **Edge cases / guards:** Text messages only, Telegram only.
- **Rebuild notes:** A short debounce at turn start removes most accidental interrupts.

### Pending-agent sentinel  `id: gw-core.pending-sentinel`
- **Surface:** Core
- **Where:** invisible; the window between claiming a session and the real agent existing.
- **What it does:** Reserves the session slot so a second concurrent message cannot spin up a duplicate agent and corrupt the transcript.
- **How it works:** `_AGENT_PENDING_SENTINEL` placed in `SessionState.turn.agent` at `gateway/run.py:19585-19592` before any await; `_persist_active_agents()` records it.
- **Inputs / options:** n/a
- **Outputs / side effects:** Messages arriving while the sentinel holds are merged into the adapter's pending slot; `/stop` clears the sentinel with `"⚡ Force-stopped. The agent was still starting — session unlocked."`.
- **Config / env:** n/a
- **Edge cases / guards:** The sentinel is never subject to stale-eviction (it has no activity summary).
- **Rebuild notes:** Claim before the first await; use a distinguishable sentinel, not `None`.

### Subagent-protection demotion  `id: gw-core.subagent-demotion`
- **Surface:** Core
- **Where:** messaging while the agent is driving `delegate_task` subagents.
- **What it does:** Downgrades an interrupt to a queue so a conversational follow-up cannot destroy minutes of subagent progress.
- **How it works:** `_agent_has_active_subagents(running_agent)` (`gateway/run.py:10675`) checked on both the priority fast-path (`:18800`) and in `_handle_active_session_busy_message`.
- **Inputs / options:** n/a
- **Outputs / side effects:** logs `"PRIORITY interrupt demoted to queue for session <key> because the running agent has active subagents"`; the ack becomes the "⏳ Subagent working…" variant.
- **Config / env:** n/a
- **Edge cases / guards:** `/stop` still reaches its handler as the explicit escape hatch.
- **Rebuild notes:** Interrupts cascade to children; protect expensive fan-out work.

### Compression-protection demotion  `id: gw-core.compression-demotion`
- **Surface:** Core
- **Where:** messaging while context compression is running.
- **What it does:** Queues the follow-up so it does not start a new turn against a session id that compression is about to rotate.
- **How it works:** `await self._session_has_compression_in_flight(session_key)` (`gateway/run.py:10712`), checked at `:18815`.
- **Inputs / options:** n/a
- **Outputs / side effects:** logs `"PRIORITY interrupt demoted to queue for session <key> because context compression is in flight"`; ack becomes "⏳ Compressing context…".
- **Config / env:** n/a
- **Edge cases / guards:** Prevents orphaned compression siblings / forked transcripts.
- **Rebuild notes:** Any operation that rotates the session id must block new turns for its duration.

### Drain replies to busy messages  `id: gw-core.drain-busy-reply`
- **Surface:** Gateway/Telegram
- **Where:** a chat while the gateway is restarting/shutting down.
- **What it does:** Tells the user whether their message was queued for after the restart or refused.
- **How it works:** `gateway/run.py:18766-18776` with `_queue_during_drain_enabled(mode)` (`:9643`) — queueing during drain is enabled only when a restart is requested **and** the busy-input mode is `queue` or `steer` (`interrupt` mode drops). `_status_action_gerund()` (`:9640`) supplies "restarting"/"shutting down"; `_status_action_label()` (`:9637`) the noun form.
- **Inputs / options:** n/a
- **Outputs / side effects:** `"⏳ Gateway <gerund> — queued for the next turn after it comes back."` or `"⏳ Gateway is <gerund> and is not accepting another turn right now."`. On the idle path the message is `"⏳ Gateway is <gerund> and is not accepting new work right now."` (`:19652`).
- **Config / env:** `display.busy_input_mode`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Say what happened to the message, not just that the system is busy.

### External-drain new-turn gate  `id: gw-core.external-drain-gate`
- **Surface:** Web dashboard | Core
- **Where:** during a maintenance drain requested from the dashboard.
- **What it does:** Refuses to *start* a new turn so the in-flight set can only fall to zero.
- **How it works:** `self._external_drain_active` (set by `_drain_control_watcher`, `gateway/run.py:9853`, 1 s poll) gates `:19570-19580`.
- **Inputs / options:** n/a
- **Outputs / side effects:** Reply: `"⏳ This agent is draining for a maintenance action and isn't accepting new turns right now. It'll be back in a moment — please resend shortly."`
- **Config / env:** the marker file `$HERMES_HOME/.drain_request.json` (see `gw-core.drain-control`).
- **Edge cases / guards:** Internal/system events bypass the gate. In-flight turns are untouched. Fully reversible — removing the marker reopens the gate.
- **Rebuild notes:** Stop accepting new work *first*, then poll to zero — eliminates the TOCTOU race.

---

## 5. Command dispatch (gateway-side plumbing)

### Slash-command access control (admin / user tiers)  `id: gw-core.slash-access`
- **Surface:** Config | Gateway/Telegram
- **Where:** `gateway.platforms.<name>.extra.allow_admin_from`, `.user_allowed_commands`, `.group_allow_admin_from`, `.group_user_allowed_commands`; inspected in chat with `/whoami`.
- **What it does:** Of the users allowed to talk to the bot, decides which may run which slash commands — separately for DM and group scope.
- **How it works:** `gateway/slash_access.py` builds a frozen `SlashAccessPolicy(enabled, admin_user_ids, user_allowed_commands)` per (platform, scope); `policy_for_source(config, source)` maps `chat_type` → scope (`_DM_CHAT_TYPES = {"dm", "direct", "private", ""}` → `"dm"`, everything else → `"group"`). `GatewayRunner._check_slash_access(source, canonical_cmd)` (`gateway/run.py:22988`) is called on **both** the cold path (`:18898`) and the running-agent fast path (`:18700`), plus on the raw typed name for quick commands (`:19706`).
- **Inputs / options:** `allow_admin_from` / `group_allow_admin_from` — user-id lists (accept a list, tuple, set, comma-separated string, or a single scalar; entries stringified and stripped). `user_allowed_commands` / `group_user_allowed_commands` — command names (leading `/` stripped). Always-allowed floor: `help`, `whoami` (`_ALWAYS_ALLOWED_FOR_USERS`); this floor is additive — anything listed in `user_allowed_commands` extends it, never restricts it.
- **Outputs / side effects:** Denial reply: `"⛔ /<cmd> is admin-only here. You can run: /a, /b, …[…]. Use /whoami for the full list."` — the preview lists at most 12 commands, appending `…` when truncated. With no allowed commands: `"⛔ /<cmd> is admin-only here. No slash commands are enabled for non-admins on this platform. Ask an admin to add you to allow_admin_from or to set user_allowed_commands."` Also logs `"Slash command /<cmd> denied for <platform>:<user> (not admin, not in user_allowed_commands)"`.
- **Config / env:** as above.
- **Edge cases / guards:** Backward compat — if `allow_admin_from` is unset for a scope, `enabled=False` and every allowed user is treated as admin (`is_admin` returns True), so existing installs are unaffected. DM admin status does **not** imply group admin status. Plain chat is never gated. `/status` and `/context` are dispatched pre-gate on the busy path.
- **Rebuild notes:** Two lists per scope, an always-allowed floor, and opt-in activation keyed on the presence of the admin list.

### `pre_command` and `command:<name>` hooks  `id: gw-core.command-hooks`
- **Surface:** Core
- **Where:** plugin/hook authors; fires for every recognized slash command on the **cold** dispatch path.
- **What it does:** Lets plugins observe or intercept a slash command before core handling.
- **How it works:** `hermes_cli.plugins.fire_pre_command_hook(surface="gateway", command, alias_used, args_raw, session_key, platform)` (`gateway/run.py:18917-18930`, observer-only in v1), then `self.hooks.emit_collect(f"command:{canonical}", hook_ctx)` (`:18939-18981`).
- **Inputs / options:** `hook_ctx` = `{platform, user_id, command, raw_command, args, raw_args}`. A handler may return `{"decision": "allow"|"deny"|"handled"|"rewrite", …}`: `deny` → returns `message` or ``"Command `/<cmd>` was blocked by a hook."``; `handled` → returns `message` or `None`; `rewrite` → sets `event.text = "/<command_name> <raw_args>"` and re-resolves.
- **Outputs / side effects:** may short-circuit the command.
- **Config / env:** n/a
- **Edge cases / guards:** These hooks deliberately do **not** fire on the running-agent intercept path — `/stop`, `/approve`, and busy dispatch are operator escape hatches for a live agent and must not be interferable by a slow or hostile plugin. Hook exceptions are logged at DEBUG and ignored.
- **Rebuild notes:** Observability + veto on the normal path only; keep control-plane operations un-hookable.

### Plugin slash commands  `id: gw-core.plugin-slash-commands`
- **Surface:** Gateway/Telegram
- **Where:** `/<plugin-command>` in chat.
- **What it does:** Routes an unrecognized command to a plugin-registered handler.
- **How it works:** `hermes_cli.plugins.get_plugin_command_handler(command.replace("_", "-"))` (`gateway/run.py:19752-19766`). The underscore→hyphen normalization exists because Telegram's autocomplete uses underscores while plugins register hyphens.
- **Inputs / options:** the raw argument string.
- **Outputs / side effects:** the handler's return value (awaited if a coroutine) becomes the reply.
- **Config / env:** plugin installation.
- **Edge cases / guards:** Dispatch errors log `"Plugin command dispatch failed: …"` and fall through.
- **Rebuild notes:** Normalize the command name once, at the boundary.

### Skill bundle slash commands  `id: gw-core.skill-bundle-commands`
- **Surface:** Gateway/Telegram
- **Where:** `/<bundle-name> [instruction]`.
- **What it does:** Loads several skills at once and turns the message into a bundle-invocation prompt.
- **How it works:** `agent.skill_bundles.resolve_bundle_command_key(command)` then `build_bundle_invocation_message(bundle_key, user_instruction, task_id=session_key, platform=<platform value>)` (`gateway/run.py:19402-19434`). The platform is passed explicitly because bundle loading bypasses the scan-time disabled filter and one gateway serves many platforms.
- **Inputs / options:** bundle name + free-text instruction.
- **Outputs / side effects:** rewrites `event.text` and falls through to normal agent processing; missing skills log `"Bundle <key> skipped missing skills: …"`.
- **Config / env:** skill/bundle configuration.
- **Edge cases / guards:** Bundles take precedence over individual skill commands. Failures log `"Bundle dispatch failed: …"`.
- **Rebuild notes:** Resolve bundle → skills → one seeded user turn.

### Skill slash commands and stacking  `id: gw-core.skill-slash-commands`
- **Surface:** Gateway/Telegram
- **Where:** `/<skill-name> [instruction]`, and stacked `/<skill-a> /<skill-b> <instruction>`.
- **What it does:** Loads a skill (or up to 5 stacked skills) and seeds the agent turn with its content.
- **How it works:** `agent.skill_commands.resolve_skill_command_key`, `get_skill_commands`, `build_skill_invocation_message`, `split_stacked_skill_commands`, `build_stacked_skill_invocation_message` (`gateway/run.py:19437-19515`). The Telegram underscore/hyphen round-trip is handled by `resolve_skill_command_key`.
- **Inputs / options:** skill name(s) + instruction. Up to 5 leading skill tokens are stacked.
- **Outputs / side effects:** rewrites `event.text` and falls through to the agent.
- **Config / env:** `hermes skills config` (per-platform disabled lists).
- **Edge cases / guards:** Per-platform disabled check runs for the leading skill **and** every stacked skill — because `get_skill_commands()` only applies the *global* disabled list at scan time and the cache is process-global. Replies: `"The **<skill>** skill is disabled for <platform>.\nEnable it with: \`hermes skills config\`"` and `"The **<a, b>** skill(s) in this stacked invocation are disabled for <platform>.\nEnable them with: \`hermes skills config\`"`. Stacked build failure → `"Failed to load stacked skills for /<command>."`
- **Rebuild notes:** Per-platform capability filters must be applied at dispatch, not only at cache-build time.

### Unknown-command notice  `id: gw-core.unknown-command`
- **Surface:** Gateway/Telegram
- **Where:** typing a `/command` that is not a built-in, plugin, skill, bundle, or quick command.
- **What it does:** Warns the user instead of silently forwarding the slash text to the model.
- **How it works:** `gateway/run.py:19518-19545`; first `_check_unavailable_skill(command)` (`:3951`) offers actionable guidance for a known-but-disabled or uninstalled skill (which resolves the skill slug from front-matter via `_skill_slug_from_frontmatter`, `:3900`), then the generic notice fires when `command.replace("_","-") not in GATEWAY_KNOWN_COMMANDS`.
- **Inputs / options:** n/a
- **Outputs / side effects:** ``"Unknown command `/<cmd>`. Type /commands to see what's available, or resend without the leading slash to send as a regular message."`` plus WARNING `"Unrecognized slash command /<cmd> from <platform> — replying with unknown-command notice"`.
- **Config / env:** n/a
- **Edge cases / guards:** Prevents the silent-failure class where the model invents a `delegate_task` call from stray slash text.
- **Rebuild notes:** Never forward an unrecognized command to the model as prose.

### Prompt-rewriting commands (`/learn`, `/plan`, `/init`, `/blueprint`)  `id: gw-core.prompt-rewriting-commands`
- **Surface:** Gateway/Telegram
- **Where:** `/learn [description]`, `/plan [task]`, `/init [notes]`, `/blueprint …`.
- **What it does:** Sends an immediate acknowledgment, rewrites the turn into a guidance prompt, and lets the ordinary agent loop do the work — preserving role alternation, working on any backend, with no special engine.
- **How it works:** `gateway/run.py:19125-19240`. `/learn` → `agent.learn_prompt.build_learn_prompt(req)`; `/plan` → `agent.plan_prompt.build_plan_prompt(task)`; `/init` → `hermes_cli.init_command.build_init_prompt_for_cwd(extra=notes)`; `/blueprint` → `_handle_blueprint_command` (`:23197`) whose result may carry `agent_seed`.
- **Inputs / options:** free text after the command.
- **Outputs / side effects:** Acknowledgments sent before the rewrite, verbatim: `"Learning a skill from what you described…"` / `"Learning a skill from this conversation…"`; `"Planning: <first 80 chars>…"` / `"Planning from this conversation's context…"`; `"Updating AGENTS.md from a project scan…"` (when the built prompt contains `UPDATE the existing AGENTS.md`) / `"Generating AGENTS.md from a project scan…"`; for `/blueprint`, the blueprint result's own `text` ("Setting up X…").
- **Config / env:** n/a
- **Edge cases / guards:** Build failure replies `"Could not start /learn — please try again."` / `"Could not start /plan — please try again."` / `"Could not start /init — please try again."`. Ack send failures are logged at DEBUG only.
- **Rebuild notes:** Rewrite-and-fall-through is the cheapest way to add a "mode" command without a second execution engine.

### `/moa <prompt>` one-shot  `id: gw-core.moa-one-shot`
- **Surface:** Gateway/Telegram
- **Where:** `/moa <prompt>`.
- **What it does:** Runs one prompt through the default Mixture-of-Agents preset, then restores the previous model.
- **How it works:** `gateway/run.py:19620-19650`. Loads `moa` config via `hermes_cli.moa_config.normalize_moa_config`, sets `SessionState.conversation.model_override = {"provider": "moa", "model": <default_preset>, "base_url": "moa://local", "api_key": "moa-virtual-provider", "api_mode": "chat_completions"}`, evicts the cached agent, and flags `event._moa_disable_after_turn = True`. `_restore_moa_one_shot` (`:19663`) runs in the handler's `finally` on **every** exit path (success, exception, interrupt) and restores `event._moa_restore_override`.
- **Inputs / options:** `<prompt>` (required; empty → `moa_usage()` text).
- **Outputs / side effects:** the turn runs on the MoA preset.
- **Config / env:** `moa.default_preset` in `config.yaml`.
- **Edge cases / guards:** Preparation failure replies `"Failed to prepare MoA turn."`. To *switch* to a MoA preset for the whole session, pick it from the model picker (MoA presets surface as a virtual "Mixture of Agents" provider).
- **Rebuild notes:** One-shot overrides must be restored in `finally`, or they leak permanently.

### One-turn model override restore (`/model --once`)  `id: gw-core.one-turn-model-restore`
- **Surface:** Core
- **Where:** after a `/model <name> --once` turn.
- **What it does:** Restores the session's previous model override after exactly one turn.
- **How it works:** `_restore_pending_one_turn_model_override(session_key)` (`gateway/run.py:19681`) reads `SessionState.conversation.one_turn_restore`, clears it, and calls `_restore_session_model_override` (`:28414`).
- **Inputs / options:** n/a
- **Outputs / side effects:** override reverted.
- **Config / env:** n/a
- **Edge cases / guards:** Runs in the same `finally` as the MoA restore.
- **Rebuild notes:** Snapshot-and-restore, never "remember to undo".

---

## 6. Sessions, routing and state

### Session key construction  `id: gw-core.session-key`
- **Surface:** Core
- **Where:** invisible; visible in `/status` and in logs as `agent:main:telegram:dm:12345`.
- **What it does:** Deterministically maps a message source to a conversation.
- **How it works:** `build_session_key(source, group_sessions_per_user=True, thread_sessions_per_user=False, profile=None)` — `gateway/session.py:1090`, the single source of truth. Namespace from `_session_key_namespace(profile)` (`:1070`): `None`/`""`/`"default"` → `agent:main` (byte-identical to every key ever generated), named profile → `agent:<profile>`. **DM rules:** `[ns, platform, "dm"]` + Slack `scope_id` (workspace) if present + `chat_id` (+ `thread_id`); with no `chat_id`, the sender's `user_id_alt or user_id` is used (so adapters that omit `chat_id` do not collapse every DM into one shared session); with neither, `thread_id` alone; with none, a bare per-platform key. **Group rules:** `[ns, platform, chat_type_slot]` + Slack `scope_id` + `chat_id` + effective thread id + participant id when isolating. WhatsApp ids are canonicalized through `canonical_whatsapp_identifier` on both DM and group paths so a JID/LID flip does not fork a session.
- **Inputs / options:** `group_sessions_per_user`, `thread_sessions_per_user`, `profile`.
- **Outputs / side effects:** the colon-joined key used by every guard, cache, and store.
- **Config / env:** `group_sessions_per_user`, `thread_sessions_per_user`, `gateway.multiplex_profiles`.
- **Edge cases / guards:** **Discord auto-thread continuity** — a channel-initiating message carries `prospective_thread_id` (the message id, which becomes the thread id); the key uses it and rewrites the `chat_type` slot to `"thread"` so the initiating message and every follow-up inside the thread byte-match ("initiate in channel, continue in thread"). A real `thread_id` always wins. Inside a thread, `isolate_user` is forced off unless `thread_sessions_per_user`.
- **Rebuild notes:** One pure function, no I/O, byte-stable across versions; make the namespace slot carry the profile so old keys are unchanged.

### Runner-side session-key resolution  `id: gw-core.session-key-runner`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Resolves the key through the live session store, with a fallback that reproduces the same namespace.
- **How it works:** `GatewayRunner._session_key_for_source(source)` (`gateway/run.py:8397`) prefers `session_store._generate_session_key(source)`; the fallback mirrors `SessionStore._resolve_profile_for_key` — profile is `None` (legacy `agent:main`) unless multiplexing is on, in which case `source.profile` or `get_active_profile_name() or "default"`.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** `_normalize_source_for_session_key` (`:8623`) applies Telegram DM topic recovery so session-scoped commands (`/model`, `/reasoning`) store their override under the *same* key the next message turn reads.
- **Rebuild notes:** One derivation, two call sites — keep them provably identical.

### Per-channel model / provider / system-prompt overrides  `id: gw-core.channel-overrides`
- **Surface:** Config
- **Where:** `platforms.<name>.channel_overrides.<channel_id>` in `~/.hermes/gateway-config.yaml` / `config.yaml`.
- **What it does:** Runs different channels of one gateway on different models and personas — e.g. a cheap model in `#daily`, a frontier model with a specialist prompt in `#dev`.
- **How it works:** `@dataclass ChannelOverride` (`gateway/config.py:597`) with `model`, `provider`, `system_prompt` (all optional). Lookup by `_get_channel_override(config, platform, chat_id, thread_id=…, parent_id=…)` (`gateway/run.py:4190`) using `_channel_override_lookup_keys` (`:4166`): **exact chat/thread id first, then thread id, then parent channel/forum id** (Discord threads inherit their parent's override), de-duplicated in order. Resolution priority for the model: session `/model` override → `channel_overrides` → global config (`_resolve_session_agent_runtime`, `gateway/run.py:8651`; `_resolve_model_for_channel`, `:10030`; `_get_system_prompt_for_channel`, `:10067`).
- **Inputs / options:** `model`, `provider`, `system_prompt` — any subset; unset fields fall back to the global defaults.
- **Outputs / side effects:** The `system_prompt` override **replaces** the global gateway prompt for that channel and is ephemeral — injected per turn, never stored in history.
- **Config / env:** n/a
- **Edge cases / guards:** A user's `/model` in a chat still wins over the channel default.
- **Rebuild notes:** Longest-match-first key list plus a documented three-level priority.

### Persistent `/model` override across restarts  `id: gw-core.session-model-override`
- **Surface:** Core | Gateway/Telegram
- **Where:** `/model <name>` in a gateway chat.
- **What it does:** Keeps a chat's model choice after a gateway restart.
- **How it works:** `_rehydrate_session_model_override(session_key)` (`gateway/run.py:28288`), `_apply_session_model_override` (`:28356`), `_snapshot_session_model_override` (`:28405`), `_restore_session_model_override` (`:28414`), `_is_intentional_model_switch` (`:28428`), `_sync_session_model_from_agent` (`:8887`). The model/provider choice is persisted to the session store; **credentials are re-resolved at load time and never written to disk**.
- **Inputs / options:** `/model <name>` (session-scoped), `/model <name> --global` (writes through to `config.yaml`), `/model <name> --once` (single turn only), `/model <name> --provider <slug>`.
- **Outputs / side effects:** Rehydrated on first use after a restart. `/new` or `/reset` clears the override.
- **Config / env:** `model.model` in `config.yaml` for the global form.
- **Edge cases / guards:** `gateway/code_skew.py` lets `/model` refuse with a clear "restart the gateway" message when the checkout was updated under a running process, instead of crashing on a stale lazy import.
- **Rebuild notes:** Persist the choice, not the credential.

### Session expiry watcher  `id: gw-core.session-expiry-watcher`
- **Surface:** Core
- **Where:** invisible background loop.
- **What it does:** Applies the reset policies (idle / daily) and prunes stale entries.
- **How it works:** `_session_expiry_watcher(interval=300)` (`gateway/run.py:15011`) — every 5 minutes.
- **Inputs / options:** n/a
- **Outputs / side effects:** Creates fresh sessions; when `SessionResetPolicy.notify` is true and the platform is not in `notify_exclude_platforms`, a reset notice is sent (`_reset_notice_session_info`, `:22924`).
- **Config / env:** `session_reset.*`, `session_store_max_age_days`.
- **Edge cases / guards:** A live background process pins its session open unless older than `bg_process_max_age_hours`.
- **Rebuild notes:** A single periodic sweep beats per-message expiry checks.

### Session stall watcher  `id: gw-core.session-stall-watcher`
- **Surface:** Core | Gateway/Telegram
- **Where:** invisible; produces a one-time notice when a turn stops making progress with a queued follow-up waiting.
- **What it does:** Detects "pending inbound + stale progress" and notifies once.
- **How it works:** `_session_stall_watcher(interval=30.0)` (`gateway/run.py:15428`) → `_check_session_stalls(timeout_seconds)` (`:15244`) using `_session_activity_for_stall` (`:15227`) and `_session_stall_timeout_seconds()` (`:15202`). Policy lives in `gateway/session_stall.py`, which consumes the shared observation contract `AIAgent.get_activity_summary()` / `agent.session_activity` as the **single progress source** — it never invents a parallel clock from turn-start or inbound timestamps.
- **Inputs / options:** n/a
- **Outputs / side effects:** a notify-once message.
- **Config / env:** stall timeout config.
- **Edge cases / guards:** Explicitly *not* process liveness (`shutdown_watchdog`) and *not* an outbound obligation (`delivery_ledger`).
- **Rebuild notes:** One observation contract; separate policy modules per concern.

### Turn lease (per-session-id serialization)  `id: gw-core.turn-lease`
- **Surface:** Core
- **Where:** invisible; surfaces as a "wait and resend" reply in rare alias-key collisions.
- **What it does:** Serializes the `[load history → run → flush]` region per **resolved session_id**, not per routing key.
- **How it works:** `gateway/turn_lease.py`. Busy guards are keyed by routing key, but `switch_session()` makes key→id many-to-one (`/resume` of a named session from a second chat/topic, CLI-continuity rebinding, async-delegation completion pinning, Telegram topic tip-walks). The lease is acquired after session resolution is final (post `switch_session`/tip-walk), immediately before the transcript load, and released in the dispatch layer's `finally` on every exit path. Runner side: `_release_turn_lease(session_key, run_generation)` (`gateway/run.py:28491`), `_rebind_turn_lease` (`:28520`).
- **Inputs / options:** n/a
- **Outputs / side effects:** On timeout (`TurnLeaseTimeoutError`) the reply is `"⏳ Another turn is still running on this session. To protect the transcript, this message was not processed. Wait for the active turn to finish, then resend it."` plus ERROR `"Rejecting turn for routing key <key> on session <sid> after turn-lease timeout; transcript load was not started and the user must resend"`. A contended acquisition logs one WARNING naming the session and both routing keys.
- **Config / env:** n/a
- **Edge cases / guards:** Uncontended everywhere except the alias-key route. Prevents interleaved flushes that would leave a permanent `user;user` alternation wedge.
- **Rebuild notes:** Lock the durable identity, not the addressing key.

### Run generations  `id: gw-core.run-generation`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Lets a late callback from an abandoned turn detect that it no longer owns the session.
- **How it works:** `_begin_session_run_generation(key)` (`gateway/run.py:28646`), `_invalidate_session_run_generation(key, reason)` (`:28661`), `_is_session_run_current(key, gen)` (`:28673`), `_bind_adapter_run_generation` (`:28681`). Release is guarded by `(routing key, run generation)` so an unwind can only free its own lease.
- **Inputs / options:** n/a
- **Outputs / side effects:** Stale progress bubbles, heartbeats and stream edits stop.
- **Config / env:** n/a
- **Edge cases / guards:** The unconditional release in the handler `finally` evicts the zombie left when a session reset bumps the generation mid-flight (which would otherwise lock the session out forever).
- **Rebuild notes:** Monotonic per-session generation counter checked by every async callback.

### Active-session slot claim  `id: gw-core.session-slot-claim`
- **Surface:** Core
- **Where:** invisible; produces the concurrency-limit reply.
- **What it does:** Reserves one of the `max_concurrent_sessions` slots before any await.
- **How it works:** `_claim_active_session_slot(session_key, source)` (`gateway/run.py:10645`) returns `(lease, limit_message)`; `_get_max_concurrent_sessions()` (`:10622`), `_active_session_limit_message(session_key)` (`:10631`). On claim, `SessionState.turn.lease`, `.agent = _AGENT_PENDING_SENTINEL`, `.started_ts = time.time()` are set and `_persist_active_agents()` (`:9777`) writes the snapshot.
- **Inputs / options:** n/a
- **Outputs / side effects:** Logs `"Rejecting new active session <key>: max_concurrent_sessions reached"`; the limit message is returned to the user.
- **Config / env:** `max_concurrent_sessions` / `gateway.max_concurrent_sessions`.
- **Edge cases / guards:** Claim happens **before** hooks, vision enrichment, STT, and hygiene compression — all of which yield.
- **Rebuild notes:** Claim-before-await is the only way to make the guard sound.

### Session state container  `id: gw-core.session-state`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Holds all per-session gateway state in one object with three clearly-scoped lifetimes.
- **How it works:** `gateway/session_state.py`. `SessionState.turn` — cleared at the end of every running turn (`agent`, `started_ts`, `lease`, `busy_ack_ts`, …). `SessionState.conversation` — cleared at conversation boundaries (`/new`, `/resume`, auto-reset, expiry, compression-exhausted reset): `model_override`, `one_turn_restore`, `queued_events`, … `SessionState.persistent` — own lifecycles (`update_prompt_pending`, approval resolution). Runner accessors: `_sessions_map` (`gateway/run.py:7358`), `_session_state` (`:7367`), `_peek_session_state` (`:7376`), `_is_session_running` (`:7383`), `_running_agent_items` (`:7388`); boundary clears `_clear_conversation_scope(key, reason)` (`:28549`) and `_clear_session_boundary_security_state(key)` (`:28602`); turn release `_release_running_agent_state` (`:28434`).
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Replaces ~19 ad-hoc dicts whose hand-copied pop-lists went stale; a wholesale `= {}` reset can no longer discard concurrent sessions' entries.
- **Rebuild notes:** One record per session with explicit scopes and a single `clear()` per scope.

### Per-session agent cache  `id: gw-core.agent-cache`
- **Surface:** Core | Config
- **Where:** invisible; affects latency and memory.
- **What it does:** Keeps one warm `AIAgent` per session so a long conversation reuses its prompt prefix instead of rebuilding the system prompt each turn.
- **How it works:** `_agent_cache_bounds` (`gateway/run.py:29208`), `_agent_cache_cap` (`:29233`), `_agent_cache_idle_ttl` (`:29238`), `_enforce_agent_cache_cap` (`:29387`), `_sweep_idle_cached_agents` (`:29470`), `_evict_cached_agent(key)` (`:29006`), `_init_cached_agent_for_turn` (`:29078`), soft eviction `_commit_memory_before_soft_evict` (`:29105`) → `_commit_then_release_soft` (`:29160`) → `_release_evicted_agent_soft` (`:29171`), config signature `_agent_config_signature` (`:28214`) and cache-busting `_extract_cache_busting_config` (`:28171`) / `_extract_honcho_cache_busting_config` (`:28141`).
- **Inputs / options:** `agent.agent_cache.*` in `config.yaml` (cap, idle TTL).
- **Outputs / side effects:** Evicted agents rebuild from the persisted session on their next turn.
- **Config / env:** `agent.agent_cache`.
- **Edge cases / guards:** LRU cap counts entries, not bytes — see `gw-core.agent-cache-pressure`.
- **Rebuild notes:** Cache the agent, not the transcript; make eviction reconstructible.

### Memory-pressure eviction of cached agents  `id: gw-core.agent-cache-pressure`
- **Surface:** Core | Config
- **Where:** invisible; visible as a log line under memory pressure.
- **What it does:** Sheds warm transcripts when the process's anonymous RSS approaches its cgroup budget.
- **How it works:** `gateway/agent_cache_pressure.py` computes anonymous RSS versus a budget derived from the cgroup limit the gateway actually runs under; `_sweep_agent_cache_under_pressure()` (`gateway/run.py:29243`) plans and `_release_pressure_batch(plan)` (`:29358`) executes soft evictions through the existing path.
- **Inputs / options:** `agent.agent_cache` config.
- **Outputs / side effects:** Transcripts are dropped from memory and rebuilt from the persisted session on the next turn.
- **Config / env:** `agent.agent_cache.*`.
- **Edge cases / guards:** Everything in the module is pure / read-only so it is testable without a gateway.
- **Rebuild notes:** Bound caches by *bytes* against the real container limit, not by entry count.

### Session DB handle recovery  `id: gw-core.session-db-recovery`
- **Surface:** Core
- **Where:** invisible; surfaces as a dashboard health aggregate and a chat warning.
- **What it does:** Keeps a per-path `SessionDB` handle cache that retries with backoff when the database is temporarily unopenable.
- **How it works:** `gateway/session_db_recovery.py`. `_Unavailable(failures, next_retry_at, in_flight)`; retry delay grows from `_INITIAL_RETRY_DELAY_SECONDS = 1.0` to `_MAX_RETRY_DELAY_SECONDS = 60.0`. A privacy-safe aggregate state (`"retrying"`, …) is published per live cache through a `WeakKeyDictionary`. Runner side: `_open_session_db_for_active_scope(raise_on_error=False)` (`gateway/run.py:7838`), `_session_db` property (`:7917`/`:7931`), `close_all_session_db_handles()` (`:7934`), and `_send_session_db_warning_notifications()` (`:26359`).
- **Inputs / options:** n/a
- **Outputs / side effects:** A chat warning when the session DB is degraded.
- **Config / env:** n/a
- **Edge cases / guards:** Handles are weakly referenced so caches do not leak.
- **Rebuild notes:** Exponential-backoff handle cache plus a public aggregate health state.

### Telegram DM topic mode (multi-session DMs)  `id: gw-core.telegram-topic-mode`
- **Surface:** Platform:Telegram | Gateway/Telegram
- **Where:** `/topic` in a Telegram DM.
- **What it does:** Turns one Telegram DM into many parallel Hermes sessions, one per Telegram topic.
- **How it works:** Gateway-side state in the SessionDB (`is_telegram_topic_mode_enabled(chat_id, user_id)`); helpers `_telegram_topic_mode_enabled` (`gateway/run.py:8427`), `_is_telegram_topic_root_lobby` (`:8454`), `_is_telegram_topic_lane` (`:8463`), `_record_telegram_topic_binding` (`:8524`), `_sync_telegram_topic_binding` (`:8543`), `_recover_telegram_topic_thread_id` (`:8569`), `_get_telegram_topic_capabilities` (`:24664`), `_ensure_telegram_system_topic` (`:24692`), `_send_telegram_topic_setup_image` (`:24733`), `_sanitize_telegram_topic_title` (`:24751`), `_rename_telegram_topic_for_session_title` (`:25026`), `_telegram_topic_auto_rename_disabled` (`:25111`), `_schedule_telegram_topic_title_rename` (`:25134`), `_should_send_telegram_capability_hint` (`:25173`), `_disable_telegram_topic_mode_for_chat` (`:25214`), `_telegram_topic_root_status_message` (`:25251`), `_restore_telegram_topic_session` (`:25297`). Telegram's General topic is identified by `_TELEGRAM_GENERAL_TOPIC_IDS = {"", "1"}` (Bot API clients differ: some omit `message_thread_id`, some send `"1"`).
- **Inputs / options:** `/topic` (enable, or show status), `/topic help`, `/topic off`, `/topic <id>` (restore a previous session into the current topic).
- **Outputs / side effects (verbatim strings):**
  - Root-DM lobby reminder: `"This main chat is reserved for system commands.\n\nTo start a new Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for that message; each topic works as an independent Hermes session."`
  - `/new` in the root DM: `"To start a new parallel Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for it.\n\nEach topic is an independent Hermes session. Use /new inside an existing topic only if you want to replace that topic's current session."`
  - Header after `/new` inside a lane: `"Started a new Hermes session in this topic.\n\nTip: for parallel work, open All Messages and send a message there to create a separate topic instead of using /new here. /new replaces the session attached to the current topic."`
  - `/topic help` text (verbatim): `"/topic — enable multi-session DM mode (one bot, many parallel chats)"`, `"Usage:"`, `"  /topic             Enable topic mode, or show status if already on"`, `"  /topic help        Show this message"`, `"  /topic off         Disable topic mode and clear topic bindings"`, `"  /topic <id>        Inside a topic: restore a previous session by ID"`, `"How it works:"`, `"1. Run /topic once in this DM — Hermes checks BotFather Threads"`, `"   Settings are enabled and flips on multi-session mode."`, `"2. Tap All Messages at the top of the bot and send any message."`, `"   Telegram creates a new topic for that message; each topic is"`, `"   an independent Hermes session (fresh history, fresh context)."`, `"3. The root DM becomes a system lobby — send /topic, /status,"`, `"   /help, /usage there. Normal prompts go in a topic."`, `"4. /new inside a topic resets just that topic's session."`, `"5. /topic <id> inside a topic restores an old session into it."`
  - Setup image: `gateway/assets/telegram-botfather-threads-settings.jpg`.
- **Config / env:** BotFather "Threads Settings" must be enabled on the bot.
- **Edge cases / guards:** The lobby reminder is debounced to one message per `_TELEGRAM_LOBBY_REMINDER_COOLDOWN_S = 30.0` seconds per chat (`_should_send_telegram_lobby_reminder`, `:8476`); further lobby prompts return `None`. Topic auto-rename can be disabled per chat.
- **Rebuild notes:** Map platform threads to sessions and make the root a control lobby with an explicit, debounced explanation.

### Discord auto-thread lanes and semantic renaming  `id: gw-core.discord-thread-lanes`
- **Surface:** Platform:Discord | Core
- **Where:** Discord channels configured to auto-thread bot replies.
- **What it does:** Keeps the initiating channel message and the auto-created thread in one session and renames the thread to the session title.
- **How it works:** `_is_discord_auto_thread_lane` (`gateway/run.py:24762`), `_is_relay_discord_channel_lane` (`:24772`), `_relay_auto_thread_info` (`:24787`), `_await_relay_auto_thread_info` (`:24834`), `_sanitize_discord_thread_title` (`:24861`), `_rename_discord_auto_thread_for_session_title` (`:24875`), `_schedule_discord_semantic_thread_rename` (`:24974`). Session continuity comes from `prospective_thread_id` in `build_session_key`.
- **Inputs / options:** n/a
- **Outputs / side effects:** the Discord thread is renamed.
- **Config / env:** Discord adapter config (adapter shard).
- **Edge cases / guards:** Works over the relay lane too, where thread info arrives asynchronously.
- **Rebuild notes:** Key on the prospective thread id so the first message is not orphaned.

### Session mirroring  `id: gw-core.session-mirror`
- **Surface:** Core
- **Where:** invisible; the receiving side's transcript.
- **What it does:** When a message is sent to a platform (via `send_message` or cron delivery), appends a "delivery-mirror" record to the target session's transcript so the receiving-side agent has context about what was sent.
- **How it works:** `gateway/mirror.py::mirror_to_session(platform, chat_id, message_text, source_label="cli", thread_id=None, user_id=None, role="assistant")`. Standalone — works from CLI, cron and gateway contexts without the full `SessionStore`. Reads `~/.hermes/sessions/sessions.json`.
- **Inputs / options:** as listed.
- **Outputs / side effects:** an extra transcript row.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** best-effort.
- **Rebuild notes:** Mirror outbound deliveries so the recipient agent is not blind to what "it" said.

### Channel directory  `id: gw-core.channel-directory`
- **Surface:** Core | Tool
- **Where:** consumed by the `send_message` tool (`action="list"`, and name→id resolution).
- **What it does:** Caches the map of reachable channels/contacts per platform so the agent can address a channel by human-friendly name.
- **How it works:** `gateway/channel_directory.py`; built at gateway startup, refreshed every 5 minutes, saved atomically to `~/.hermes/channel_directory.json` (`atomic_json_write`).
- **Inputs / options:** n/a
- **Outputs / side effects:** the JSON file.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Repeated Slack refresh failures are throttled — warn once per `(team, error detail)` per interval, then DEBUG.
- **Rebuild notes:** Periodic snapshot with atomic write and per-error log throttling.

---

## 7. Outbound rendering, streaming and progress

### Per-platform display-setting resolver  `id: gw-core.display-config`
- **Surface:** Config
- **Where:** `display:` and `display.platforms.<platform>:` in `~/.hermes/config.yaml`.
- **What it does:** Single entry point for every verbosity/presentation setting, with platform-specific overrides and capability-tiered built-in defaults.
- **How it works:** `gateway/display_config.py::resolve_display_setting(user_config, platform_key, setting, fallback=None)`. Order: (1) `display.platforms.<platform>.<key>`; (1b) legacy `display.tool_progress_overrides.<platform>` for `tool_progress` only; (2) `display.<key>` (skipped for `streaming`, which is CLI-only at the global level); (3) `_PLATFORM_DEFAULTS[<platform>][<key>]`; (4) `_GLOBAL_DEFAULTS[<key>]`; else `fallback`. `_normalise()` fixes YAML 1.1 quirks (bare `off` → `False`).
- **Inputs / options — overrideable keys (`OVERRIDEABLE_KEYS`) and global defaults:** `tool_progress` = `"all"`; `tool_progress_grouping` = `"accumulate"`; `show_reasoning` = `False`; `reasoning_style` = `"code"`; `tool_preview_length` = `0`; `streaming` = `None`; `interim_assistant_messages` = `True`; `long_running_notifications` = `True`; `busy_ack_detail` = `True`; `busy_steer_ack_enabled` = `True`; `cleanup_progress` = `False`; `live_status` = `"full"`.
- **Outputs / side effects:** n/a
- **Config / env:** as above; also `display.busy_input_mode`, `display.busy_ack_enabled`, `display.tool_progress_command`, `display.runtime_footer.*`, `display.status_phrases.*`, `display.background_process_notifications`.
- **Edge cases / guards:** A config migration moves the legacy `display.tool_progress_overrides` shape into `display.platforms`.
- **Rebuild notes:** Four-level lookup, one normaliser, one canonical key set for validation.

### Platform display tiers and defaults  `id: gw-core.display-tiers`
- **Surface:** Config
- **Where:** built-in; overridable per platform.
- **What it does:** Gives every platform sensible verbosity out of the box based on whether it supports editing and how public it is.
- **How it works:** `gateway/display_config.py:80-192`.
- **Inputs / options — the four tiers:**
  - `_TIER_HIGH` — `tool_progress: "all"`, `show_reasoning: False`, `tool_preview_length: 40`, `streaming: None` (follow global), `interim_assistant_messages: True`, `long_running_notifications: True`, `busy_ack_detail: True`.
  - `_TIER_MEDIUM` — same but `tool_progress: "new"`.
  - `_TIER_LOW` — `tool_progress: "off"`, `tool_preview_length: 40`, `streaming: False`, `interim_assistant_messages: False`, `long_running_notifications: False`, `busy_ack_detail: False`.
  - `_TIER_MINIMAL` — `tool_progress: "off"`, `tool_preview_length: 0`, `streaming: False`, and all three chatter flags `False`.
- **Per-platform assignment (`_PLATFORM_DEFAULTS`), exhaustive:** `telegram` = HIGH but `tool_progress: "off"`, `busy_ack_detail: False`; `discord` = HIGH with `reasoning_style: "subtext"`; `slack` = MEDIUM but `tool_progress: "off"`, `long_running_notifications: False`, `busy_ack_detail: False`; `mattermost` = MEDIUM; `matrix` = MEDIUM; `feishu` = MEDIUM; `buzz` = MEDIUM; `signal` = LOW; `whatsapp` = MEDIUM (Baileys bridge supports edit); `whatsapp_cloud` = LOW; `photon` = LOW; `bluebubbles` = LOW; `weixin` = LOW; `wecom` = LOW but `streaming: True` (native `msgtype: "stream"` transport); `wecom_callback` = LOW; `dingtalk` = LOW; `email` = MINIMAL; `sms` = MINIMAL; `webhook` = MINIMAL; `homeassistant` = MINIMAL; `api_server` = HIGH with `tool_preview_length: 0`.
- **Outputs / side effects:** n/a
- **Config / env:** `display.platforms.<platform>.<key>` overrides any of these.
- **Edge cases / guards:** Telegram deliberately keeps `interim_assistant_messages` and `long_running_notifications` ON (real mid-turn commentary and a heartbeat are signal) while turning the per-tool breadcrumb stream off.
- **Rebuild notes:** Tier by capability (can edit? public channel?) then tweak per platform.

### `tool_progress` modes  `id: gw-core.tool-progress-modes`
- **Surface:** Config | Gateway/Telegram
- **Where:** `display.tool_progress:` / `display.platforms.<p>.tool_progress:`.
- **What it does:** Controls how much tool activity is echoed to the chat.
- **How it works:** Resolved at `gateway/run.py:30208-30231` (an env override applies only when the key is not configured); consumed in `TurnRunner.progress_callback` (`:4695`) and `send_progress_messages` (`:5207`).
- **Inputs / options:** `off` (nothing); `new` (report only when the tool *changes* — repeats of the same tool are skipped); `all` (every `tool.started`); `verbose` (full argument JSON, and the full command as a fenced code block for `terminal`); `log` (no chat bubbles at all — see `gw-core.tool-progress-log`). `_normalise` maps `False`/`false`/`0`/`no` → `"off"`, `True`/`true`/`1`/`yes`/`on` → `"all"`, and anything outside `{off,new,all,verbose,log}` → `"all"`.
- **Outputs / side effects:** Progress bubbles like `💻 \`ls -la\`...`, `🔍 web_search...`, `📄 web_extract...`, `🐍 execute_code...`. The emoji comes from `agent.display.get_tool_emoji(tool_name, default="⚙️")`. Verbose renders `"<emoji> <tool>(<arg keys>)\n<args json>"` or `"<emoji> <tool>: \"<preview>\""`.
- **Config / env:** `display.tool_preview_length` (`agent.display.get_tool_preview_max_len()`), `display.tool_progress_command` (gates `/verbose` in messaging).
- **Edge cases / guards:** Only `tool.started` events render. The `clarify` tool NEVER renders a progress bubble (the adapter's `send_clarify` *is* the user-facing rendering; a verbose bubble would dump the raw `{"question":…,"choices":[…]}` JSON under the prompt). Bubbles are suppressed once the user has sent `stop`, so a late interrupt does not still render N parallel tool bubbles. `webhook` never gets progress. On markdown-capable adapters (`supports_code_blocks`) a `terminal` command renders as a fenced block with no language tag (Slack mrkdwn would render the tag as a literal first line); consecutive terminal calls drop the repeated `"<emoji> terminal"` header so they read as adjacent blocks; non-verbose modes truncate the first line to `tool_preview_length` (or 40) with `"..."`, appending `" ..."` when the command was multi-line. Repeats are collapsed as `"<msg> (×<N>)"`.
- **Rebuild notes:** Mode enum + per-platform default + a hard exclusion list for tools that render themselves.

### `tool_progress_grouping`  `id: gw-core.tool-progress-grouping`
- **Surface:** Config
- **Where:** `display.tool_progress_grouping:`; default `accumulate`.
- **What it does:** On platforms that support editing, decides whether progress accumulates in one edited bubble or posts one message per tool.
- **How it works:** `resolve_display_setting(..., "tool_progress_grouping")` (`gateway/run.py:30231`); `_normalise` accepts only `accumulate` | `separate`, else `accumulate`.
- **Inputs / options:** `accumulate` (default — edit one bubble in place as tools run); `separate` (one message per tool; pre-v0.9 style, noisier).
- **Outputs / side effects:** n/a
- **Config / env:** only applies where `tool_progress` is already enabled.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `tool_progress: log` — audit file instead of chat  `id: gw-core.tool-progress-log`
- **Surface:** Config
- **Where:** `display.tool_progress: log`.
- **What it does:** Sends **no** progress bubbles; appends one line per tool call to a rotating audit file.
- **How it works:** `gateway/run.py:4756-4767` writes `"<YYYY-MM-DD HH:MM:SS>  <tool>: \"<preview>\""` (trailing whitespace stripped) to `ctx.log_queue`; `log_mode_enabled = progress_mode == "log" and source.platform != Platform.WEBHOOK` (`:30294`). File: `~/.hermes/logs/tool_calls.log`, rotating **5 MB × 3 backups**, run through the same secret-redacting formatter as regular logs.
- **Inputs / options:** n/a
- **Outputs / side effects:** the audit file only.
- **Config / env:** n/a
- **Edge cases / guards:** `_thinking` is excluded. Log mode runs even without a chat progress queue.
- **Rebuild notes:** Same event stream, different sink; always redact.

### `live_status` — text typing-status line  `id: gw-core.live-status`
- **Surface:** Config | Platform:Slack | Platform:Google Chat
- **Where:** `display.live_status:` / `display.platforms.<p>.live_status:`; default `"full"`.
- **What it does:** Renders the current tool as the platform's *text* working-status (Slack's `assistant.threads.setStatus` line, Google Chat's marker message) — independent of progress bubbles and costing no extra API calls.
- **How it works:** `gateway/run.py:4727-4753`. On `tool.started` it calls `agent.display.build_status_phrase(tool_name, args if mode == "full" else None)` and `adapter.set_status_text(chat_id, phrase)`; on `tool.completed` it reverts to the static default with `set_status_text(chat_id, None)`. Plain dict write — safe from the agent's sync worker thread, no event-loop hop.
- **Inputs / options:** `"full"` / `true` (verb + argument preview, e.g. "is running pytest…"); `"verb"` (verb only, "is running…" — keeps file paths and commands out of shared channels); `"off"` / `false` (static text: `typing_status_text` or `"is thinking..."`). `_normalise` maps `true/1/yes/on/all` → `"full"`, `false/0/no` → `"off"`, anything else outside `{full,verb,off}` → `"full"`.
- **Outputs / side effects:** the platform status line.
- **Config / env:** `platforms.<name>.typing_status_text`.
- **Edge cases / guards:** `_thinking` never sets a status. Works even when `tool_progress` is off (Slack's default). Requires the `assistant:write` scope on Slack.
- **Rebuild notes:** Reuse the existing typing refresh cadence to render different text; never add API calls for status.

### Typing indicator  `id: gw-core.typing-indicator`
- **Surface:** Config
- **Where:** `gateway.platforms.<name>.typing_indicator:` (also accepted at top level or inside `extra`); default `true`.
- **What it does:** Shows a live "typing…" bubble (Telegram/Discord/Signal) or the "is thinking…" assistant status (Slack) while the agent processes a message.
- **How it works:** `PlatformConfig.typing_indicator` (`gateway/config.py:668`) drives the per-message `_keep_typing` refresh loop in `gateway/platforms/base.py`.
- **Inputs / options:** bool per platform.
- **Outputs / side effects:** Disabling suppresses only the indicator — delivery is unchanged.
- **Config / env:** n/a
- **Edge cases / guards:** Slack's status uses the Assistant API and briefly disables the compose box while shown, which some users find noisy. The flag is generic — the same key works for every platform. The clarify interception explicitly calls `adapter.resume_typing_for_chat(chat_id)` after resolving so Slack does not go silent until the 3-minute heartbeat.
- **Rebuild notes:** One boolean per platform, applied by a shared refresh loop.

### `typing_status_text`  `id: gw-core.typing-status-text`
- **Surface:** Config
- **Where:** `platforms.<name>.typing_status_text:`; default `null`.
- **What it does:** Custom text for the working-state line on platforms whose typing indicator renders text.
- **How it works:** `PlatformConfig.typing_status_text` (`gateway/config.py:678`).
- **Inputs / options:** any string.
- **Outputs / side effects:** replaces the built-in defaults `"is thinking..."` (Slack) / `"Hermes is thinking…"` (Google Chat).
- **Config / env:** n/a
- **Edge cases / guards:** Platforms with textless indicators (Discord, Telegram, Matrix, …) ignore it.
- **Rebuild notes:** n/a

### Long-running heartbeat  `id: gw-core.long-running-heartbeat`
- **Surface:** Config | Gateway/Telegram
- **Where:** the chat, every few minutes during a long turn.
- **What it does:** A single edit-in-place bubble that says how long the agent has been working, so the user has a heartbeat instead of staring at `typing…`.
- **How it works:** `_notify_long_running()` (`gateway/run.py:30893-30980`). Interval from `HERMES_AGENT_NOTIFY_INTERVAL` / `agent.gateway_notify_interval`, default **180 s** (3 min); `0` disables. The heartbeat message id is remembered so the bubble is **edited** rather than re-sent; a failed edit falls back to a new send and re-captures the id. Guarded by `_should_emit_long_running_notification(session_key, agent, executor_task)` (`:11788`), which stops when the executor is done, the agent is gone, or the session key has been rebound to a different live agent.
- **Inputs / options:** `display.long_running_notifications` = `True` (default) | `False` (`"off"`) | `"generic"`.
- **Outputs / side effects:** Text is `"⏳ Working — <N> min<detail>"` where `<detail>` is `" — iteration <i>/<m>, <current tool or last activity>"`; the iteration part is gated on `busy_ack_detail`. In `"generic"` mode the text is a phrase from the status-phrase catalog instead (`_generic_status_phrase("status")`).
- **Config / env:** `HERMES_AGENT_NOTIFY_INTERVAL`, `agent.gateway_notify_interval`, `display.platforms.<p>.long_running_notifications`, `display.platforms.<p>.busy_ack_detail`.
- **Edge cases / guards:** Registered for cleanup when `cleanup_progress` is on.
- **Rebuild notes:** One editable bubble, ownership-checked before every update.

### Progress bubble cleanup  `id: gw-core.cleanup-progress`
- **Surface:** Config
- **Where:** `display.platforms.<platform>.cleanup_progress:`; default `false`.
- **What it does:** Deletes tool-progress messages, the "still working…" heartbeat, and status-callback bubbles after the final response lands.
- **How it works:** message ids are accumulated in `_cleanup_msg_ids` during the turn (`gateway/run.py:30378` and the heartbeat path) and deleted after delivery.
- **Inputs / options:** bool per platform.
- **Outputs / side effects:** the chat is left with just the question and the answer.
- **Config / env:** n/a
- **Edge cases / guards:** Only platforms whose adapter implements `delete_message` honor it (currently Telegram and Discord). **Failed runs skip cleanup** so the bubbles remain as breadcrumbs.
- **Rebuild notes:** Track ids as you post; skip cleanup on failure.

### Interim assistant messages  `id: gw-core.interim-assistant-messages`
- **Surface:** Config
- **Where:** `display.interim_assistant_messages:` / per platform; default `True` (False on LOW/MINIMAL tiers).
- **What it does:** Relays real mid-turn assistant commentary (the model saying what it is about to do) as chat messages.
- **How it works:** `_interim_metadata` (`gateway/run.py:718`) marks these sends; `_non_conversational_metadata` (`:705`) marks them as not part of the conversation.
- **Inputs / options:** bool (string values `raw`/`verbose` also read as true).
- **Outputs / side effects:** extra chat messages during a turn.
- **Config / env:** n/a
- **Edge cases / guards:** Distinct from tool progress — Telegram keeps this ON while turning tool progress off.
- **Rebuild notes:** Separate "the model spoke" from "a tool started".

### Reasoning display and style  `id: gw-core.reasoning-display`
- **Surface:** Config | Gateway/Telegram
- **Where:** `display.show_reasoning:`, `display.reasoning_style:`; chat command `/reasoning [level|show|hide]`.
- **What it does:** Shows the model's reasoning/thinking summary in chat and chooses how it is formatted.
- **How it works:** `_load_show_reasoning()` (`gateway/run.py:10251`); `_load_reasoning_config(model)` (`:10096`); `_parse_reasoning_command_args(raw)` (`:10113`); `_resolve_session_reasoning_config` (`:10138`); `_set_session_reasoning_override` (`:10167`).
- **Inputs / options:** `show_reasoning` bool (default `False`). `reasoning_style`: `"code"` (default — `💭 **Reasoning:**` + a fenced code block), `"blockquote"` (each line prefixed `"> "`), `"subtext"` (each line prefixed `"-# "`, Discord small grey subtext; Discord's default).
- **Outputs / side effects:** reasoning rendered inline in the reply stream.
- **Config / env:** n/a
- **Edge cases / guards:** The stream consumer strips inline reasoning tags — `<REASONING_SCRATCHPAD>`, `<think>`, `<reasoning>`, `<THINKING>`, `<thinking>`, `<thought>` and their closing forms (`gateway/stream_consumer.py:209-216`), kept in sync with the CLI's tag list.
- **Rebuild notes:** One tag list shared by every surface that strips reasoning.

### Streaming consumer (edit / draft transport)  `id: gw-core.stream-consumer`
- **Surface:** Core
- **Where:** invisible; produces the growing reply bubble.
- **What it does:** Bridges the agent's synchronous `stream_delta_callback` to async platform delivery, buffering and rate-limiting progressive edits of one message.
- **How it works:** `gateway/stream_consumer.py::GatewayStreamConsumer`. `on_delta(text)` is thread-safe and sync, queueing onto a `queue.Queue`; the async `run()` task buffers, rate-limits, and edits. Built by `_build_stream_consumer_config` (`gateway/run.py:29579`). Draft ids come from a class counter seeded with `secrets.randbits(49)` — never zero and never the clock, because `draft_id` is the wire identity for the relay connector's per-`(channel, draft_id)` sealed-stream tombstones which outlive the process.
- **Inputs / options — `StreamConsumerConfig` (`gateway/stream_consumer.py:159`):** `edit_interval` (default `0.8` s); `buffer_threshold` (default `24` chars); `cursor` (default `" ▉"`); `buffer_only` (bool, default `False`); `fresh_final_after_seconds` (float, default `0.0`); `transport` (`"edit"` default at this layer; `"auto"`/`"draft"`/`"edit"`; `"off"` is handled by the gateway before the consumer is built); `chat_type` (hint, e.g. `"dm"`, `"group"`, `"supergroup"`, `"forum"` — gates Telegram's DM-only native drafts). Constructor also takes `metadata`, `on_new_message`, `on_before_finalize`, `initial_reply_to_id`, `run_still_current`.
- **Outputs / side effects:** one progressively-edited platform message (or a native draft), finalized at the end.
- **Config / env:** `streaming.*` and `display.platforms.<p>.streaming`.
- **Edge cases / guards:** After `_MAX_FLOOD_STRIKES = 3` consecutive flood-control failures, progressive edits are permanently disabled for the rest of the stream and the reply is finalized in one send. `_stream_confirmed_final_delivery` (`gateway/run.py:30985`) reconciles the recorded turn-final payload against what was actually edited, because a successful `finalize` is not proof the *content* was final (the tail generated between the last preview snapshot and stream completion may never have reached an API call).
- **Rebuild notes:** Sync-in / async-out queue, time+size flush thresholds, flood-strike backoff, and an explicit final-content reconciliation.

### Structured stream events  `id: gw-core.stream-events`
- **Surface:** Core
- **Where:** invisible; the agent→gateway delivery contract.
- **What it does:** Names *what happened* (message, commentary, segment, tool started/completed) without prescribing *how it is delivered*.
- **How it works:** `gateway/stream_events.py` — plain frozen dataclasses, no behaviour, no platform knowledge, no I/O; cheap to construct on the agent worker thread and safe to hand across the thread/async boundary.
- **Inputs / options:** the typed event vocabulary.
- **Outputs / side effects:** none directly.
- **Config / env:** n/a
- **Edge cases / guards:** Events describe *transport*, never *context* — nothing here is persisted to conversation history, so what the gateway "eats" (e.g. tool chrome on iMessage) never affects the transcript.
- **Rebuild notes:** Typed events + a single sink beats a fan of loosely-typed callbacks that each decide both content and delivery.

### Stream event dispatcher  `id: gw-core.stream-dispatch`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Routes each typed stream event through the adapter's render hooks to the consumer, so tool chrome and streamed text no longer race through independent code paths.
- **How it works:** `gateway/stream_dispatch.py::GatewayEventDispatcher` holds an adapter + the stream consumer (sink) + the resolved per-channel presentation settings (tool-progress mode, preview length). Message/commentary/segment events go to the consumer (native draft on Telegram DMs, edit-in-place elsewhere); tool events are formatted by the adapter, which may return `None` to *eat* the event on platforms that cannot render tool chrome, and the rendered line is enqueued onto the same tool-progress queue the gateway already drains. No platform knowledge, no asyncio — a thin synchronous router callable from the agent's worker thread.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** display settings.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Smart agent emits structured data; smart gateway decides delivery.

### Streaming TTS consumer  `id: gw-core.streaming-tts`
- **Surface:** Core | Platform:Discord
- **Where:** voice-capable adapters (Discord voice channels).
- **What it does:** Starts speaking while the model is still generating, by synthesising completed clauses as they appear.
- **How it works:** `gateway/streaming_tts_consumer.py::StreamingTTSConsumer(adapter, chat_id, tts_config, loop, metadata)`. `on_delta` is synchronous and never blocks the agent thread: deltas go into a `SentenceChunker` and completed clauses onto a thread-safe `queue.Queue`; an asyncio `run()` task drains it, synthesises each clause via a `StreamingTTSProvider`, and writes PCM chunks to the adapter.
- **Inputs / options:** lifecycle — `agent.stream_delta_callback = consumer.on_delta`, then `consumer.finish()`, `await consumer.wait_complete(timeout=10)`, `consumer.abort("cancelled")` (idempotent).
- **Outputs / side effects:** `consumer.suppress_whole_file` tells the turn to skip whole-file auto-TTS.
- **Config / env:** voice/TTS config.
- **Edge cases / guards:** Per-turn state is isolated — each consumer owns its own chunker, queue, handle and flags, so concurrent chats cannot cross-contaminate.
- **Rebuild notes:** Chunk on clause boundaries; never block the generation thread on audio.

### Silence tokens  `id: gw-core.silence-tokens`
- **Surface:** Core
- **Where:** the agent's final response.
- **What it does:** Lets the agent explicitly choose not to reply; the gateway suppresses delivery and sends nothing.
- **How it works:** `gateway/response_filters.py`. Canonical token `SILENT_REPLY_TOKEN = "NO_REPLY"`; `LIVE_GATEWAY_SILENT_MARKERS = {"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"}`. `_canonical_silence_candidate` upper-cases and collapses whitespace; `_strip_edge_silence_punctuation` removes stray edge punctuation without erasing marker structure.
- **Inputs / options:** the whole final response must be the token — whitespace and case are normalized.
- **Outputs / side effects:** Nothing is sent. The assistant silence turn is **kept in the session transcript**, so the conversation still alternates normally (`user → assistant:[SILENT] (stored, not delivered) → user`).
- **Config / env:** n/a
- **Edge cases / guards:** A sentence like ``Use `[SILENT]` when nothing changed`` is delivered normally. Failed turns still surface as errors — failures are never hidden because the text resembles a silence token. Arbitrary empty output remains the error/empty-response path, not silence.
- **Rebuild notes:** Exact whole-response match, small explicit marker list, delivery-only decision.

### Final-response sanitizer  `id: gw-core.final-response-sanitizer`
- **Surface:** Core
- **Where:** every human-facing chat surface.
- **What it does:** Redacts secrets, removes crash-inducing characters, drops cancellation metadata, and turns raw provider errors into short safe categories before anything reaches a chat platform.
- **How it works:** `_sanitize_gateway_final_response(platform, text)` (`gateway/run.py:989`). Programmatic surfaces in `_GATEWAY_RAW_TEXT_PLATFORMS` (CLI/TUI `local` diagnostics, API JSON, webhook payloads) pass raw text through — decided by `_gateway_surface_passes_raw_text(platform)` (`:572`). Otherwise: (1) `agent.message_sanitization._sanitize_surrogates` strips lone UTF-16 surrogates (U+D800–U+DFFF) which crash Telegram's `utf16_len` check and Signal formatting with `UnicodeEncodeError` before any send; (2) a response starting with `INTERRUPT_WAITING_FOR_MODEL_PREFIX` returns `""`; (3) `_redact_gateway_user_facing_secrets`; (4) if `_looks_like_gateway_provider_error` then `_gateway_provider_error_reply`.
- **Inputs / options:** n/a
- **Outputs / side effects:** the delivered text.
- **Config / env:** n/a
- **Edge cases / guards:** This is the last line of defence for legacy/plugin delivery paths that hand over raw text.
- **Rebuild notes:** One sanitizer at the delivery boundary, with an explicit raw-text allowlist.

### Secret redaction on outbound chat  `id: gw-core.secret-redaction`
- **Surface:** Core
- **Where:** every outbound chat message and every approval prompt.
- **What it does:** Masks credentials before they can leave the gateway.
- **How it works:** `_redact_gateway_user_facing_secrets(text)` (`gateway/run.py:844`) delegates to `agent.redact.redact_sensitive_text(text, force=True)` — the same redactor used for logs, tool output and approval prompts — then runs a narrow `_GATEWAY_SECRET_PATTERNS` second pass as belt-and-suspenders. `_redact_approval_command(cmd)` (`:873`) does the same for the raw command string inside an approval prompt.
- **Inputs / options:** n/a
- **Outputs / side effects:** matches replaced with `[REDACTED]`.
- **Config / env:** `force=True` means redaction applies even when `security.redact_secrets` is off.
- **Edge cases / guards:** If the redactor import fails, the local pattern pass still runs — it fails soft, never raw.
- **Rebuild notes:** Delegate to one authoritative redactor and keep a local fallback.

### Provider-error mapping  `id: gw-core.provider-error-mapping`
- **Surface:** Core | Gateway/Telegram
- **Where:** the chat, when the model provider fails.
- **What it does:** Replaces raw HTTP bodies, request ids and policy text with a short user-safe sentence.
- **How it works:** `_looks_like_gateway_provider_error(text)` (`gateway/run.py:966`) requires BOTH (a) the text is short — ≤ 400 chars and ≤ 4 newlines — and (b) an error marker at the *start* (optionally behind a punctuation/symbol prefix), matched by `_GATEWAY_PROVIDER_ERROR_SHAPE_RE` (`:944`) which covers `api (call) failed`, `provider authentication failed`, `non-retryable error`, `rate limited after N retries`, `error code:`, `http NNN`, `incorrect api key`, `invalid api key`, `(x.)(api )connection error|timeout`, `(x.)connect error|timeout`, `connection refused`, `connection reset`, `connection aborted`, `actively refused`, `winerror 10061`, `errno 111`, `all connection attempts failed`. `_gateway_provider_error_reply(text)` (`:917`) then picks the message.
- **Inputs / options:** n/a
- **Outputs / side effects (verbatim):**
  - auth: `"⚠️ Provider authentication failed. Check the configured credentials; raw provider details are in the gateway logs."`
  - policy: `"⚠️ The model provider rejected the request. I kept the raw provider error out of chat; check gateway logs for details or try rephrasing."`
  - rate limit: `"⏱️ The model provider is rate-limiting requests. Please wait a moment and try again."`
  - connection: `"⚠️ The model server is not responding — it looks like the configured model endpoint is not running or is unreachable."`
  - default: `"⚠️ The model provider failed after retries. I kept raw provider details out of chat; check gateway logs for diagnostics."`
- **Config / env:** n/a
- **Edge cases / guards:** The two heuristics together stop assistant prose that merely *mentions* an HTTP code ("HTTP 404 means 'not found' — …") from being rewritten.
- **Rebuild notes:** Shape + position + length heuristics, never a bare substring match.

### Status-message filtering  `id: gw-core.status-message-filter`
- **Surface:** Core
- **Where:** the chat, for agent status callbacks.
- **What it does:** Keeps transient auxiliary/compression chatter out of messaging surfaces while CLI/TUI keeps the raw diagnostic stream.
- **How it works:** `_prepare_gateway_status_message(platform, event_type, message)` (`gateway/run.py:1028`): empty → `None`; raw-text surfaces pass through; otherwise redact, then suppress anything matching `_TELEGRAM_NOISY_STATUS_RE`, then map provider errors. `_status_template_to_regex(template)` (`:497`) derives the matchers from the status-template constants so non-compression noise stays suppressed even when the compression gate is open.
- **Inputs / options:** n/a
- **Outputs / side effects:** filtered status line, or nothing.
- **Config / env:** `compression.progress_notices: true` (`_gateway_compression_progress_notices_enabled()`, `:538`) lets **routine compression progress** statuses through to chat platforms; default `false` keeps the silent-by-design behaviour.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Derive noise matchers from the same constants that generate the messages.

### Runtime footer  `id: gw-core.runtime-footer`
- **Surface:** Config | Gateway/Telegram | CLI
- **Where:** `display.runtime_footer:` in `config.yaml`; toggled in chat or CLI with `/footer [on|off|status]`.
- **What it does:** Appends a compact runtime line (model, context %, cwd) to the FINAL message of a turn. Off by default.
- **How it works:** `gateway/runtime_footer.py`. Per-platform overrides live under `display.platforms.<platform>.runtime_footer`.
- **Inputs / options:** `enabled` (bool, default off); `fields` — an ordered list drawn from `model` (bare model id, vendor prefix dropped, e.g. `gpt-5.4`), `context_pct` (last-call context occupancy as a percent, e.g. `5%`), `latency` (wall-clock turn duration, e.g. `22s`, `1m05s` — **opt-in**, not in the default field set), `cwd` (home-relative working dir, e.g. `~`).
- **Outputs / side effects:** `/footer` replies come from `locales/en.yaml` → `gateway.footer.*`: status `"📎 Runtime footer: **{state}**\nFields: \`{fields}\`\nPlatform: \`{platform}\`"`, usage `"Usage: \`/footer [on|off|status]\`"`, saved `"📎 Runtime footer: **{state}**{example}\n_(saved globally — takes effect on next message)_"`, example line `"\nExample: \`{preview}\`"`, states `"ON"` / `"OFF"`.
- **Config / env:** n/a
- **Edge cases / guards:** A footer whose `fields` are unset renders exactly as before `latency` was added.
- **Rebuild notes:** Ordered field list so users choose both content and order.

### Configurable status phrases  `id: gw-core.status-phrases`
- **Surface:** Config
- **Where:** `gateway/assets/status_phrases.yaml` (built-in); `~/.hermes/status_phrases.yaml`; any `*.yaml` in `~/.hermes/status_phrases/`; or `display.status_phrases.path` + `.mode` in `config.yaml`.
- **What it does:** Supplies the short "still working…" style status lines used by generic heartbeat mode, instead of relaying raw model scratch text.
- **How it works:** `gateway/status_phrases.py`. Conventional paths are auto-loaded; a configured path is resolved **relative to `HERMES_HOME`**.
- **Inputs / options:** `display.status_phrases.path` (relative path to a file or directory); `display.status_phrases.mode` = `append` (default) | `replace`. Phrase files map a surface (`status`, `generic`) to a list of strings.
- **Outputs / side effects:** the phrase pool used by `_generic_status_phrase(surface)`.
- **Config / env:** n/a
- **Edge cases / guards:** Limits — **max 80 phrases per surface, 160 characters each**. Absolute paths and `..` escapes are ignored on purpose so config stays profile-portable and cannot read arbitrary files. Only configured phrase strings are used — raw tool arguments, commands, previews, and reasoning text are **never** interpolated into a phrase.
- **Rebuild notes:** Fixed vocabulary, no interpolation of model-controlled text into status lines.

### Command-mention Telegramization  `id: gw-core.telegramize-command-mentions`
- **Surface:** Core | Platform:Telegram
- **Where:** outbound text mentioning slash commands.
- **What it does:** Rewrites command mentions into the form the platform's autocomplete expects (Telegram's underscored variants).
- **How it works:** `_telegramize_command_mentions(text, platform)` (`gateway/run.py:1257`) with an inner `_replace(match)` (`:1270`).
- **Inputs / options:** n/a
- **Outputs / side effects:** modified outbound text.
- **Config / env:** n/a
- **Edge cases / guards:** Platform-gated.
- **Rebuild notes:** Normalize command spellings at the last possible moment.

### Cron output truncation  `id: gw-core.cron-truncation`
- **Surface:** Core
- **Where:** cron job output delivered to a chat.
- **What it does:** Caps very long cron output for platforms that do not split long messages themselves.
- **How it works:** `gateway/delivery.py:26 MAX_PLATFORM_OUTPUT = 4000` — headroom under Telegram's hard 4096 limit for the "full output saved to …" footer appended on truncation. Adapters advertising `BasePlatformAdapter.splits_long_messages` bypass this entirely and chunk in their own `send()`, preserving the full output.
- **Inputs / options:** n/a
- **Outputs / side effects:** a truncated message plus a pointer to the saved full output.
- **Config / env:** `always_log_local`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Truncate only where the transport cannot chunk; always keep the full artifact.

### Delivery routing  `id: gw-core.delivery-routing`
- **Surface:** Core
- **Where:** cron job outputs and agent responses with explicit targets.
- **What it does:** Resolves where a message goes: an explicit target, a platform home channel, back to the origin, or local files.
- **How it works:** `gateway/delivery.py` — `DeliveryTarget` (`:214`) and `DeliveryRouter.deliver(content, targets, job_id=None, job_name=None, metadata=None)` (`:318`).
- **Inputs / options:** target forms — `"telegram:123456789"` (explicit platform:chat), `"telegram"` (platform home channel), `"origin"` (back to source), `"local"` (save to files).
- **Outputs / side effects:** platform sends and/or local files.
- **Config / env:** `always_log_local`, per-platform `home_channel`.
- **Edge cases / guards:** Silence-narration filtering and dead-target short-circuiting apply here.
- **Rebuild notes:** A tiny target grammar plus one router.

---

## 8. Media, voice, approvals, reactions, background work

### Inbound image handling (native vs. text)  `id: gw-core.image-input-mode`
- **Surface:** Core
- **Where:** sending a photo to the bot.
- **What it does:** Decides whether image pixels are attached to the user turn natively or pre-analysed into a text description.
- **How it works:** `_decide_image_input_mode(source, session_key, user_config, provider, model)` (`gateway/run.py:26535`) resolves the **effective model for this turn** (session `/model` override first, then config) and delegates to `agent.image_routing.decide_image_input_mode(provider, model, cfg, requested_provider=…)`.
- **Inputs / options:** returns `"native"` (attach pixels) or `"text"` (pre-analyse with `vision_analyze` and prepend the description).
- **Outputs / side effects:** in `"text"` mode, `_enrich_message_with_vision(user_text, image_paths)` (`:26608`) analyses each image with a general-purpose prompt and injects both the description **and** the local cache path so the model can immediately understand the image and re-examine it with `vision_analyze` if needed.
- **Config / env:** image-routing config; per-session `/model`.
- **Edge cases / guards:** Any failure falls back to `"text"` with a DEBUG log `"image_routing: decision failed, falling back to text — …"`. Image preprocessing runs before `AIAgent` sets the auxiliary-client globals, hence the explicit session-runtime resolution.
- **Rebuild notes:** Route by the model that will actually run the turn, not the persisted default.

### Media placeholders and document context notes  `id: gw-core.media-placeholders`
- **Surface:** Core
- **Where:** invisible; what the model sees when media has no caption.
- **What it does:** Gives the model a textual stand-in for attachments.
- **How it works:** `_build_media_placeholder(event)` (`gateway/run.py:3515`); `_build_document_context_note(...)` (`:3537`); type probes `_event_media_type_at` (`:3463`), `_event_media_is_image` (`:3473`), `_event_media_is_audio` (`:3488`), `_event_media_is_stt_input` (`:3496`), `_event_media_is_video` (`:3507`); audio duration via `_probe_audio_duration(path)` (`:3588`) formatted by `_format_duration(seconds)` (`:3577`).
- **Inputs / options:** n/a
- **Outputs / side effects:** placeholder text used as the interrupt/queue payload when a media message has no text.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Always give an interrupt/queue path a non-empty payload.

### Auto-appended media tags & history dedup  `id: gw-core.auto-append-media`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Adds `MEDIA:` tags for files the agent produced, without resending files already delivered in this conversation.
- **How it works:** `_collect_auto_append_media_tags(...)` (`gateway/run.py:2089`) deduplicates against `_collect_history_media_paths(agent_history)` (`:2161`, with inner `_add_text_media_paths`, `:2177`).
- **Inputs / options:** n/a
- **Outputs / side effects:** `MEDIA:` directives appended to the response.
- **Config / env:** media policy.
- **Edge cases / guards:** Explicit `MEDIA:` directives written by the model are **never** deduped against prior turns (a user-requested resend is legitimate).
- **Rebuild notes:** Dedup only what you auto-added.

### Post-stream media delivery  `id: gw-core.media-out`
- **Surface:** Core
- **Where:** attachments arriving after a streamed reply.
- **What it does:** Uploads files the model explicitly attached with `MEDIA:` directives once the text has already been streamed.
- **How it works:** `_deliver_media_from_response(response, event, adapter, thread_metadata)` (`gateway/run.py:24185`). `adapter.extract_media(response)` → `BasePlatformAdapter.filter_media_delivery_paths(...)`. Images (`.jpg .jpeg .png .webp .gif`) that are not voice and not forced-document are batched through `adapter.send_multiple_images(chat_id, images, metadata)` with `file://`-quoted URLs. The rest: `should_send_media_as_audio(platform, ext, is_voice)` → `adapter.send_voice(...)`; extensions in `.mp4 .mov .avi .mkv .webm .3gp` → `adapter.send_video(...)`; everything else → `adapter.send_document(...)`.
- **Inputs / options:** `[[as_document]]` anywhere in the response forces image-extension files through `send_document` so original bytes are preserved (Telegram `sendPhoto` recompresses to ~1280 px).
- **Outputs / side effects:** platform uploads.
- **Config / env:** media policy env (`gw-core.cfg-media-policy`).
- **Edge cases / guards:** This rescan is **explicit-only** — unlike the non-streaming path in `gateway/platforms/base.py`, it does NOT run `extract_local_files`, because a bare path in an already-streamed reply is either text the user has seen or stale inspected content; promoting those to uploads sent files the model never asked to deliver. Per-file failures log `"[<adapter>] Post-stream media delivery failed: …"` and continue.
- **Rebuild notes:** Explicit attachment contract post-stream; auto-detection only on the non-streamed path.

### `computer_use` screenshot path repair  `id: gw-core.media-repair`
- **Surface:** Core
- **Where:** invisible; rescues screenshots the model mangled.
- **What it does:** Fixes a `MEDIA:` directive whose `computer_use_<uuid>` screenshot path was rewritten by the model (e.g. `C:\Users\Alice\…` → `/Users/Alice/…`) so delivery-path validation no longer rejects it.
- **How it works:** `gateway/media_repair.py`. Accepted absolute-path prefixes: Windows drive letter, POSIX root, or UNC share (`_ABS_PATH_PREFIX_PATTERN`). Basenames must match `^computer_use_[0-9a-f]{32}\.(png|jpe?g)$` (case-insensitive) and exactly match a canonical screenshot path returned by `computer_use` in the current turn.
- **Inputs / options:** n/a
- **Outputs / side effects:** the directive's path is rewritten.
- **Config / env:** n/a
- **Edge cases / guards:** Deliberately narrow — only rewrites inside a response that *already* carries an explicit `MEDIA:` directive; never auto-attaches captures; normal media path validation still runs after the repair. Shared by the gateway turn path, gateway background tasks, and cron delivery.
- **Rebuild notes:** Match on a server-generated basename, never on a model-supplied directory.

### Voice transcription of inbound audio  `id: gw-core.stt`
- **Surface:** Core
- **Where:** sending a voice note to the bot.
- **What it does:** Transcribes the audio and uses the transcript as the message text, optionally echoing it back.
- **How it works:** `_enrich_message_with_transcription` (`gateway/run.py:26679`), `_pending_event_audio_paths(event)` (`:26821`), `_transcribe_pending_audio_event_once` (`:26830`), `_echo_pending_stt_transcripts_once` (`:26860`), `_transcribe_and_echo_pending_voice(event, adapter, source, text, log_context=…)` (`:26901`). The busy fast-path and the interrupt path both transcribe before building the interrupt payload (`log_context="Voice-priority-interrupt"` / `"Voice-busy-interrupt"`).
- **Inputs / options:** n/a
- **Outputs / side effects:** the transcript becomes the message; when echoing is on it is also posted to the chat.
- **Config / env:** `stt.enabled` / `stt_enabled`; `stt.echo_transcripts` / `stt_echo_transcripts`.
- **Edge cases / guards:** Transcription and echo each run at most **once** per pending event. A voice reply to a pending clarify that transcribes to nothing keeps the clarify armed.
- **Rebuild notes:** Transcribe once, memoize on the event, and make the echo independently switchable.

### Spoken (TTS) replies  `id: gw-core.voice-reply`
- **Surface:** Core | Gateway/Telegram
- **Where:** chats where voice mode is on; `/voice [on|off|tts|join|leave|status]`.
- **What it does:** Speaks the reply as a voice message before (or instead of) the text.
- **How it works:** `_should_send_voice_reply(event, response, agent_messages, already_sent=False)` (`gateway/run.py:24014`) then `_send_voice_reply(event, text)` (`:24094`) using `tools.tts_tool.text_to_speech_tool` and `_strip_markdown_for_tts`. Voice mode is stored per `(platform, chat_id)` by `_voice_key` (`:8052`), loaded by `_load_voice_modes` (`:8056`) and saved by `_save_voice_modes` (`:8082`); synced onto the adapter by `_sync_voice_mode_state_to_adapter` (`:8123`), `_set_adapter_auto_tts_disabled` (`:8091`), `_set_adapter_auto_tts_enabled` (`:8105`).
- **Inputs / options:** chat voice modes `"all"` (speak every reply), `"voice_only"` (speak only when the input was a voice message), `"off"`; when a chat has **no** explicit mode, the config-level `voice.auto_tts` (synced onto the adapter at startup) is the fallback.
- **Outputs / side effects:** an audio message.
- **Config / env:** `voice.auto_tts`.
- **Edge cases / guards:** Never speaks an empty response or one starting with `"Error:"`. Deduped when the agent already called the `text_to_speech` tool **in this turn** (scanned from the last user message onward). Deduped again when the input was voice and the base adapter's auto-TTS already handled it — **unless** streaming already consumed the response (`already_sent=True`), in which case the base adapter has no text and the runner must take over. Skips are logged at DEBUG with mode, adapter flag, chat and platform.
- **Rebuild notes:** Two dedup axes (agent-invoked TTS, adapter auto-TTS) plus a streaming carve-out.

### Discord voice-channel conversations  `id: gw-core.voice-channel`
- **Surface:** Platform:Discord
- **Where:** `/voice join`, `/voice leave` in a Discord guild.
- **What it does:** Lets the agent join a voice channel and converse by speech.
- **How it works:** `_handle_voice_channel_join(event)` (`gateway/run.py:23804`), `_handle_voice_channel_leave(event)` (`:23861`), `_handle_voice_timeout_cleanup(chat_id)` (`:23884`), `_handle_voice_channel_input(...)` (`:23935`), guild resolution `_get_guild_id(event)` (`:23790`), and a per-turn sidecar note `_voice_channel_sidecar_note(event, source, session_key)` (`:28872`).
- **Inputs / options:** `/voice join`, `/voice leave`, `/voice status`.
- **Outputs / side effects:** the bot joins/leaves the voice channel; transcripts drive turns.
- **Config / env:** voice config.
- **Edge cases / guards:** `_is_duplicate_voice_transcript(guild_id, user_id, transcript)` (`:23894`) suppresses repeated recognitions of the same utterance.
- **Rebuild notes:** Dedup transcripts per (guild, user) before creating turns.

### Dangerous-command approval in chat  `id: gw-core.approval-prompt`
- **Surface:** Gateway/Telegram
- **Where:** the chat, when a tool needs approval; answered with `/approve` or `/deny`.
- **What it does:** Asks the owner to authorise a dangerous command, with capability-appropriate choices.
- **How it works:** Text fallback rendered by `_format_exec_approval_fallback(command, description, command_prefix, allow_permanent=True, allow_session=True, smart_denied=False)` (`gateway/run.py:889`); the command is redacted first by `_redact_approval_command` (`:873`). Send outcome classified by `_approval_send_outcome(future, timeout)` (`:1086`).
- **Inputs / options:** the rendered prompt offers, in order: `` `<prefix>approve` `` (this one operation), `` `<prefix>approve session` `` (approve this pattern for the session, only when `allow_session`), `` `<prefix>approve always` `` (approve permanently, only when `allow_session and allow_permanent`), `` `<prefix>deny` ``.
- **Outputs / side effects:** Prompt shape: heading `"⚠️ **Dangerous command requires approval:**"` (or `"⚠️ **Smart DENY — owner override for one operation:**"` when `smart_denied`), then a fenced block containing the command truncated to 200 chars + `"..."`, then `"Reason: <description>"`, then the comma-joined choices ending `", or <last>."`. Replies come from `locales/en.yaml` → `gateway.approve.*` / `gateway.deny.*`, e.g. `"✅ Command approved. The agent is resuming..."`, `"✅ Commands approved ({count} commands). The agent is resuming..."`, `"✅ Command approved (pattern approved for this session). The agent is resuming..."`, `"✅ Command approved (pattern approved permanently). The agent is resuming..."`, `"❌ Command denied."`, `"❌ Commands denied ({count} commands)."`, `"❌ Command denied. Reason relayed to the agent: \"{reason}\""`, `"❌ Command denied (approval was stale)."`, `"No pending command to approve."`, `"No pending command to deny."`, and `"⚠️ Approval expired (agent is no longer waiting). Ask the agent to try again."` (`gateway.approval_expired`).
- **Config / env:** approval/permission config.
- **Edge cases / guards:** Choices are rendered from **capabilities**, never from platform names. `smart_denied` prompts drop the session/permanent options. When a tool approval is pending it takes precedence over a slash-confirm for `/approve`. Bare text ("yes") never approves — only the explicit commands do.
- **Rebuild notes:** Render the choice set from capability flags; redact the command; make the "no pending" and "expired" cases distinct.

### Clarify prompt rendering  `id: gw-core.clarify-render`
- **Surface:** Gateway/Telegram
- **Where:** the chat, when the agent calls the `clarify` tool.
- **What it does:** Renders the question as native buttons where supported, otherwise as a numbered text prompt; supports multi-select.
- **How it works:** `adapter.send_clarify(...)`; gateway-side send/wait helpers `_clarify_send_disposition(fut, session_key, clarify_mod)` (`gateway/run.py:1122`) and `_clarify_send_then_wait(fut, clarify_id, session_key, clarify_mod)` (`:1152`).
- **Inputs / options:** Answer by option number, several numbers separated by commas or spaces (multi-select prompts say `"Multiple selections allowed"`), the option text, or free-form text via the "Other" path. In the classic CLI/TUI, multi-select renders as checkboxes — **Space** toggles, **Enter** submits.
- **Outputs / side effects:** unblocks the waiting tool.
- **Config / env:** n/a
- **Edge cases / guards:** The `clarify` tool never gets a tool-progress bubble (its own rendering is the UI). The platform typing indicator is paused while waiting and explicitly resumed on answer.
- **Rebuild notes:** One prompt abstraction, two renderings (native / numbered text), one answer parser.

### Reaction events → hooks  `id: gw-core.reactions`
- **Surface:** Core
- **Where:** emoji reactions on messages (Discord, Slack, Matrix, DingTalk, Feishu, BlueBubbles, Photon).
- **What it does:** Fans a normalised platform reaction out to the hook registry so user hooks can act on it.
- **How it works:** `GatewayRunner._handle_reaction_event(ctx)` (`gateway/run.py:8935`), registered by adapters via `set_reaction_handler`. The adapter-supplied `event_name` — `"reaction:added"` or `"reaction:removed"` — becomes the hook event, matching the `agent:*` naming scheme.
- **Inputs / options:** the normalised context dict (adapter-supplied, includes `event_name`).
- **Outputs / side effects:** `self.hooks.emit(event_name, ctx)`.
- **Config / env:** hooks under `~/.hermes/hooks/`.
- **Edge cases / guards:** Errors never block the adapter's event loop — the hook contract is non-blocking (`"[Gateway] reaction hook emit failed"` at DEBUG).
- **Rebuild notes:** Normalise at the adapter, fan out through one event bus.

### `/bg` background sessions  `id: gw-core.background-sessions`
- **Surface:** Gateway/Telegram
- **Where:** `/bg <prompt>` in any chat.
- **What it does:** Spawns a separate agent instance with its own isolated session so the main chat stays responsive.
- **How it works:** `_run_background_task(...)` (`gateway/run.py:24377`) → `_run_background_task_inner(...)` (`:24439`); toolsets resolved by `_resolve_enabled_toolsets_for_source` (`:24404`).
- **Inputs / options:** `<prompt>` (required).
- **Outputs / side effects:** Immediate confirmation from `locales/en.yaml` → `gateway.background.started`: `"🔄 Background task started: \"{preview}\"\nTask ID: {task_id}\nYou can keep chatting — results will appear when done."` (task ids look like `bg_143022_a1b2c3`). Usage text (`gateway.background.usage`): `"Usage: /bg <prompt>\nExample: /bg Summarize the top HN stories today\n\nRuns the prompt in a separate session. You can keep chatting — the result will appear here when done."` The result is delivered to the **same chat or channel**, prefixed `"✅ Background task complete"`, or `"❌ Background task failed"` with the error.
- **Config / env:** inherits the current model, provider, toolsets, reasoning settings and provider routing.
- **Edge cases / guards:** The background agent has its own conversation history and no knowledge of the current chat context — it receives only the prompt.
- **Rebuild notes:** Fire-and-forget child session that reports back to the originating chat.

### `/btw` side questions  `id: gw-core.btw`
- **Surface:** Gateway/Telegram
- **Where:** `/btw <question>`.
- **What it does:** Answers a quick side question from a snapshot of the current conversation without interrupting the running work.
- **How it works:** dispatched through `_gateway_plain_command_handlers` → `_handle_btw_command`; strings in `locales/en.yaml` → `gateway.btw.*`.
- **Inputs / options:** `<question>`.
- **Outputs / side effects (verbatim):** usage `"Usage: /btw <question>\nExample: /btw which file was that error in?\n\nAnswers a quick side question about this conversation without interrupting it. For an independent background task, use /bg <prompt>."`; `"No conversation yet — send your question as a normal message instead."`; `"❌ Cannot answer side question: no provider credentials configured."`; started `"💬 Side question: \"{preview}\"\nAnswering from a snapshot of this conversation — the current work continues."`; answer `"💬 /btw: \"{preview}\"\n\n{answer}"`; failure `"❌ /btw failed: \"{preview}\"\n{error}"`.
- **Config / env:** n/a
- **Edge cases / guards:** Safe mid-run (registered as a plain handler usable while busy).
- **Rebuild notes:** Snapshot the transcript, answer out-of-band, never mutate the live session.

### Background-process notifications  `id: gw-core.background-process-notifications`
- **Surface:** Config | Gateway/Telegram
- **Where:** `display.background_process_notifications:` in `config.yaml`, or `HERMES_BACKGROUND_NOTIFICATIONS` env.
- **What it does:** Controls what the chat hears when the agent's `terminal(background=true)` processes emit output or finish.
- **How it works:** `_load_background_notifications_mode()` (`gateway/run.py:10472`); env wins over config; `raw is False` maps to `"off"`. Watchers run in `_run_process_watcher(watcher)` (`:27861`).
- **Inputs / options:** `concise` (default — one-line status message on completion; failures append a short output tail); `all` (running-output updates **and** the final raw-output message); `result` (only the final raw-output completion message, regardless of exit code); `error` (only the final raw-output message when the exit code is non-zero); `off` (no watcher messages at all).
- **Outputs / side effects:** Concise format from `_format_concise_process_notification(session_id, command, exit_code, output, duration_seconds)` (`:4280`): `"✅ Background task finished — \`<cmd>\` (<dur>)"` on success (exit 0 or None), `"❌ Background task failed (exit <N>) — \`<cmd>\` (<dur>)"` on failure. Duration renders as `"<H>h <M>m"` (≥3600 s), `"<M>m <S>s"` (≥60 s), else `"<S>s"`. The command is shortened by `_shorten_command_for_display(command, limit=80)` (`:4272`). On failure, the last **5 non-blank output lines** (capped at **500 characters**, tail-trimmed) are appended in a fenced block. The full output always stays available to the agent via `process(log/wait)`.
- **Config / env:** as above.
- **Edge cases / guards:** An unknown mode logs `"Unknown background_process_notifications '<x>', defaulting to 'concise'"` and uses `concise`.
- **Rebuild notes:** Five modes covering the noise/observability spectrum; keep raw output out of chat by default.

### Watch-pattern and delegation notifications  `id: gw-core.watch-notifications`
- **Surface:** Core | Gateway/Telegram
- **Where:** the chat, when a watched background process matches a pattern or an async delegation completes.
- **What it does:** Injects `[IMPORTANT: …]` notices into the conversation.
- **How it works:** `_format_gateway_process_notification(evt)` (`gateway/run.py:4320`), drained by `_drain_gateway_watch_events(completion_queue)` (`:4358`) and `_drain_watch_notifications(completion_queue)` (`:27040`), injected by `_inject_watch_notification(...)` (`:27060`).
- **Inputs / options:** event types — `watch_disabled` and `watch_overflow_tripped` / `watch_overflow_released` render as `"[IMPORTANT: <message>]"`; `watch_match` renders `"[IMPORTANT: Background process <sid> matched watch pattern \"<pattern>\".\nCommand: <cmd>\nMatched output:\n<output>"` plus `"\n(<N> earlier matches were suppressed by rate limit)"` when suppressed, closed with `"]"`; `async_delegation` reuses `tools.process_registry.format_process_notification(evt)`.
- **Outputs / side effects:** a chat message and a transcript entry.
- **Config / env:** n/a
- **Edge cases / guards:** Unknown event types return `None`.
- **Rebuild notes:** A single `[IMPORTANT: …]` envelope so the model can recognise out-of-band notices.

### Completion-notification coalescing  `id: gw-core.completion-coalescing`
- **Surface:** Core | Gateway/Telegram
- **Where:** the chat, when several background processes finish at once.
- **What it does:** Batches simultaneous completions into one message instead of a burst.
- **How it works:** `_completion_delivery_identity(evt)` (`gateway/run.py:27207`), `_classify_completion_target(parent_session_id)` (`:27227`), `_deliver_completion_notification(...)` (`:27294`), `_completion_notification_batch_key(evt)` (`:27451`), `_format_coalesced_process_completions(entries)` (`:27463`), `_record_coalesced_completion_siblings(events)` (`:27502`), `_flush_process_completion_batch(key)` (`:27517`), `_cancel_process_completion_batch_tasks()` (`:27573`), `_enqueue_process_completion_notification(...)` (`:27598`).
- **Inputs / options:** n/a
- **Outputs / side effects:** one coalesced chat message.
- **Config / env:** n/a
- **Edge cases / guards:** Batch tasks are cancelled on shutdown.
- **Rebuild notes:** Key by delivery identity, hold briefly, flush once.

### Async-delegation watcher  `id: gw-core.async-delegation-watcher`
- **Surface:** Core
- **Where:** invisible; delivers results of async delegated work.
- **What it does:** Polls for finished async delegations and delivers grouped notifications back to the right session.
- **How it works:** `_async_delegation_watcher(interval=2.0)` (`gateway/run.py:27797`), `_enrich_async_delegation_routing(evt)` (`:27641`), `_async_delegation_group_key(evt)` (`:27663`), `_format_coalesced_async_delegations(blocks)` (`:27681`), `_deliver_async_delegation_group(...)` (`:27692`), session resolution `_resolve_async_delegation_session(...)` (`:17566`).
- **Inputs / options:** n/a
- **Outputs / side effects:** chat notifications.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** 2-second poll + grouping key.

### Session wake for stateless adapters  `id: gw-core.wake`
- **Surface:** Core
- **Where:** invisible; how a background completion resumes an existing session.
- **What it does:** Wakes an existing agent session from a background completion event using the right delivery strategy for the adapter.
- **How it works:** `gateway/wake.py`, selected by the adapter's `supports_async_delivery` flag. **Push-capable** adapters (telegram, discord, plugin platforms, …) receive a synthetic `MessageEvent(internal=True)` through `adapter.handle_message`. **Stateless request/response** adapters (the API server, `supports_async_delivery = False`) instead get a self-POST to `/v1/chat/completions` on the in-pod API server carrying the raw session id in the `X-Hermes-Session-Id` header — the exact entry point real turns use — because `handle_message` would run the wake under a `build_session_key()`-derived key (`agent:main:api_server:group:<sid>`) that never matches the raw header key real turns use, landing the wake in a parallel invisible session.
- **Inputs / options:** n/a
- **Outputs / side effects:** the woken turn's result is visible the next time the client polls or reopens the conversation.
- **Config / env:** `API_SERVER_KEY` for the self-POST.
- **Edge cases / guards:** Failures **raise** after bounded retries on transient errors so callers can rewind cursors / retry instead of silently losing the event.
- **Rebuild notes:** Wake through the same entry point the surface's real turns use.

---

## 9. Reliability, lifecycle and operations

### Delivery ledger (durable at-least-once replies)  `id: gw-core.delivery-ledger`
- **Surface:** Core | Config
- **Where:** invisible until a crash; then a `"♻️ Recovered reply — …"` message in the chat.
- **What it does:** Guarantees a produced final response is not silently lost when the gateway crashes or restarts between generating it and the platform confirming receipt.
- **How it works:** `gateway/delivery_ledger.py` writes a small durable row per outbound final response to `state.db` (WAL, owner pid + process-start-time liveness). Three checkpoints around the send: `record_obligation()` → `state='pending'` before any attempt; `mark_attempting()` → `state='attempting'` immediately before the await; `mark_delivered()` → `state='delivered'` only on `SendResult.success`, or `mark_failed()` → `state='failed'` on a definitive rejection. On startup `sweep_recoverable()` claims rows whose owning process is dead; after an adapter reconnects without a process restart, `sweep_failed_for_runtime()` may claim only the same live process's explicitly allowlisted transient failures. Runner side: `_claim_pending_obligations` (`gateway/run.py:12829`), `_redeliver_claimed_obligations` (`:12893`), `_redeliver_pending_obligations` (`:12990`), `_redeliver_failed_obligations_for_platform` (`:13003`), `_clear_resume_pending_for_claimed_obligations` (`:12800`).
- **Inputs / options:** none (automatic).
- **Outputs / side effects:** Semantics: `pending` (send never started) → redelivered as-is, no dup risk. `attempting` (crashed mid-await, platform may or may not have received it) → redelivered with the visible prefix `"♻️ Recovered reply — the gateway restarted during delivery, so this may be a duplicate:\n\n"`. `failed` (definitively rejected once) → also carries a marker. Runtime (no restart) reconnect replays carry `"♻️ Recovered reply — the messaging platform reconnected after the original delivery failed, so this may be a duplicate:\n\n"`.
- **Config / env:** `gateway.delivery_ledger: false` disables it (in-flight responses are then lost on crash).
- **Edge cases / guards:** Bounds (module constants, deliberately not config): `MAX_ATTEMPTS = 3`, `STALE_AFTER_SECONDS = 24 h` freshness, `_RETENTION_SECONDS = 7 days` for delivered rows, `_MAX_ROWS = 500`. Runtime replay is fail-closed: `_RUNTIME_RETRYABLE_ERRORS = {"send_path_degraded"}` only — a blocked bot, bad auth, or missing chat is never retried merely because an adapter reconnected. Ambiguity is always **labelled**, never silently resent.
- **Rebuild notes:** Three states around the send, an honest duplicate marker, bounded retries and retention.

### Dead-target registry  `id: gw-core.dead-targets`
- **Surface:** Core
- **Where:** invisible; stops repeated sends to a deleted group.
- **What it does:** Remembers targets a platform has confirmed are permanently gone so the delivery layer short-circuits them.
- **How it works:** `gateway/dead_targets.py` — a small JSON file under the active profile's `HERMES_HOME`, thread-safe, best-effort. Records only *whole-chat* deaths: the `forbidden` and chat-level `not_found` (`chat not found`) error kinds.
- **Inputs / options:** n/a
- **Outputs / side effects:** subsequent sends to that target are skipped, saving flood-control budget and log noise.
- **Config / env:** `HERMES_HOME` (per-profile).
- **Edge cases / guards:** Self-healing — any successful send to that target clears the flag, so re-adding the bot recovers automatically. **Thread/topic-level `not_found` is deliberately NOT recorded** (adapters already self-heal by retrying without `reply_to`, and a deleted topic does not mean the parent chat is dead). A corrupt or unwritable file degrades to an in-memory-only registry.
- **Rebuild notes:** Negative cache with automatic invalidation on success; scope it narrowly.

### Restart / online notifications  `id: gw-core.restart-notification`
- **Surface:** Config | Gateway/Telegram
- **Where:** each platform's home channel after a gateway restart.
- **What it does:** Sends a one-shot "the agent is back" message.
- **How it works:** `_send_restart_notification()` (`gateway/run.py:26197`) and `_send_home_channel_startup_notifications(...)` (`:26276`), gated per platform by `PlatformConfig.gateway_restart_notification` (default `true`). Pending markers: `_restart_notification_pending()` (`:2291`), `_planned_restart_notification_path()` (`:2296`), `_planned_restart_notification_pending()` (`:2300`), `_clear_planned_restart_notification()` (`:2305`).
- **Inputs / options:** `gateway.platforms.<name>.gateway_restart_notification: false` opts a platform out.
- **Outputs / side effects (verbatim):** `"♻ Gateway restarted successfully. Your session continues."` (`gateway/run.py:26248`) and `"♻️ Gateway online — Hermes is back and ready."` (`:26289`).
- **Config / env:** n/a
- **Edge cases / guards:** Sent **once per restart** regardless of how many sessions were in flight. Disable on noisy or low-priority platforms while keeping it on the primary chat.
- **Rebuild notes:** Marker file + per-platform opt-out.

### Session resume across gateway restarts  `id: gw-core.session-resume`
- **Surface:** Core | Gateway/Telegram
- **Where:** chats whose turn was interrupted by a restart.
- **What it does:** Flags the affected sessions and offers to resume them from the last committed turn on the user's next message.
- **How it works:** Sessions are flagged `restart_interrupted`; on startup `_schedule_resume_pending_sessions(platform=None)` (`gateway/run.py:13064`) schedules auto-resume. `_run_startup_resume_event` (`:12497`), `build_resume_recovery_note(...)` (`:1526`), `_prepare_resume_pending_message(...)` (`:1595`), `_is_fresh_gateway_interruption(...)` (`:1497`), `_should_clear_resume_pending_after_turn(agent_result)` (`:4532`), `_is_stale_restart_redelivery(event)` (`:23078`). Freshness window from `_auto_continue_freshness_window()` (`:1353`).
- **Inputs / options:** none (on by default, no configuration).
- **Outputs / side effects:** The user gets a short heads-up containing `"Send any message after restart and I'll try to resume where you left off."` (`gateway/run.py:11526`); the gateway logs `"Scheduled auto-resume for N restart-interrupted session(s)"` at start.
- **Config / env:** Set `gateway_restart_notification: false` on a platform to suppress the heads-up.
- **Edge cases / guards:** Auto-resume is **skipped** for a boot when the restart-loop guard has tripped (`gw-core.cfg-restart-loop-guard`). Stale redeliveries are detected and dropped. Auto-continue noise is stripped by `_is_auto_continue_noise(content)` (`:2029`) / `_strip_auto_continue_noise(content)` (`:2040`).
- **Rebuild notes:** Flag on interruption, replay on the next real message, and let a breaker skip the replay.

### Shutdown notifications to active sessions  `id: gw-core.shutdown-notifications`
- **Surface:** Gateway/Telegram
- **Where:** chats with in-flight work when the gateway stops.
- **What it does:** Tells users their turn was interrupted rather than leaving them waiting.
- **How it works:** `_notify_active_sessions_of_shutdown()` (`gateway/run.py:11513`), `_notify_interrupted_cron_jobs(job_ids)` (`:11416`), `_drain_active_agents(...)` (`:11325`), `_interrupt_running_agents(reason)` (`:11400`), `_finalize_shutdown_agents(active_agents)` (`:11712`).
- **Inputs / options:** n/a
- **Outputs / side effects:** interruption notices and a resume heads-up.
- **Config / env:** `agent.restart_drain_timeout` (`DEFAULT_GATEWAY_RESTART_DRAIN_TIMEOUT`), `gateway.signal_interrupt_grace_timeout`.
- **Edge cases / guards:** `_increment_restart_failure_counts(active_session_keys)` (`:12019`) and `_suspend_stuck_loop_sessions()` (`:12046`) stop a session that keeps killing the gateway; `_clear_restart_failure_count(key)` (`:12095`) resets on success.
- **Rebuild notes:** Never leave a user staring at a typing indicator that will never resolve.

### Restart machinery  `id: gw-core.restart`
- **Surface:** CLI | Gateway/Telegram
- **Where:** `/restart` in chat, `hermes gateway restart`, SIGUSR1, and the tail of `hermes update`.
- **What it does:** Drains in-flight work then respawns the gateway through the supervisor or a detached child.
- **How it works:** `request_restart(detached=False, via_service=False)` (`gateway/run.py:12447`), `_await_active_work_before_restart()` (`:12349`), `_launch_detached_restart_command()` (`:12118`), `_awaitable_work_count()` (`:12345`), `_wedged_agent_count()` (`:12305`). Constants in `gateway/restart.py`: `GATEWAY_SERVICE_RESTART_EXIT_CODE = 75` (EX_TEMPFAIL — ask the service manager to restart), `GATEWAY_FATAL_CONFIG_EXIT_CODE = 78` (EX_CONFIG — the s6 finish script translates it to 125 so the supervisor stops restarting), `EXTERNAL_GATEWAY_SUPERVISOR_ENV = "HERMES_GATEWAY_EXTERNAL_SUPERVISOR"` (set by `hermes gateway run --external-supervisor`; unlike systemd's `INVOCATION_ID` or launchd's `XPC_SERVICE_NAME` it survives wrappers that replace the child environment, e.g. `sudo env -i`).
- **Inputs / options:** timeouts `_load_restart_drain_timeout()` (`gateway/run.py:10367`), `_load_restart_after_turn_timeout()` (`:10386`), `_load_cron_drain_timeout()` (`:10409`).
- **Outputs / side effects:** `"⏳ Draining {count} active agent(s) before restart..."` (`locales/en.yaml` → `gateway.draining`).
- **Config / env:** `agent.restart_drain_timeout`, `gateway.signal_interrupt_grace_timeout`.
- **Edge cases / guards:** The installed unit uses `KillMode=mixed` + `KillSignal=SIGTERM` and `Restart=always` with `RestartForceExitStatus`. Adding an `ExecStopPost=/bin/kill -9 $MAINPID` drop-in causes an **infinite restart loop** (it fires on every stop, SIGKILLing the freshly spawned instance) — the docs call this out explicitly.
- **Rebuild notes:** Distinguish "restart me" from "stop trying" with distinct exit codes.

### Adapter fatal errors, circuit breaker, pause/resume  `id: gw-core.platform-breaker`
- **Surface:** Gateway/Telegram | CLI
- **Where:** `/platform list`, `/platform pause <name>`, `/platform resume <name>`.
- **What it does:** Isolates a failing platform adapter without taking the gateway down, and lets an operator pause/resume adapters live.
- **How it works:** `_handle_adapter_fatal_error(adapter)` (`gateway/run.py:8951`) → `_queue_retryable_fatal_platform` (`:8979`) / `_handle_adapter_fatal_error_detached` (`:9033`) / `_handle_adapter_fatal_error_impl` (`:9113`). Manual control: `_pause_failed_platform(platform, reason="")` (`:9917`) and `_resume_paused_platform(platform)` (`:9955`). Runtime status per platform via `_update_platform_runtime_status(...)` (`:9885`).
- **Inputs / options:** `/platform list` (shows `running`, `paused`, or `paused-by-breaker` plus the last reason), `/platform pause <name>`, `/platform resume <name>`.
- **Outputs / side effects:** Pausing keeps the adapter loaded and its background loops alive — incoming messages are dropped but the connection stays open so resume is instant. Pause sets `paused=True`, `pause_reason` (default `"auto-paused after repeated failures"`), `next_retry = inf`, and platform state `"paused"`; it logs `"<platform> paused after <N> consecutive failures (<reason>) — fix the underlying issue then run \`/platform resume <platform>\` to retry, or \`hermes gateway restart\` to restart the gateway."` Resume clears the flag, zeroes `attempts`, sets `next_retry = now`, state `"retrying"`, and logs `"<platform> resumed — retrying on next watcher tick"`.
- **Config / env:** n/a
- **Edge cases / guards:** The reconnect watcher does **not** auto-pause: retryable network/DNS failures keep retrying at the backoff cap indefinitely so a transient outage self-heals. The breaker does not auto-resume — a sustained outage should not cause reconnect thrash. When one platform trips, an operator notification is sent to the home channel of another live platform if one is configured.
- **Rebuild notes:** Pause = stop dispatch, keep the connection; resume must be instant.

### Reconnect watcher  `id: gw-core.reconnect-watcher`
- **Surface:** Core
- **Where:** invisible; the gateway log.
- **What it does:** Retries failed platform connections with exponential backoff and escalates a long-failing platform.
- **How it works:** `_platform_reconnect_watcher()` (`gateway/run.py:15600`), spawned by `_spawn_reconnect_watcher(on_give_up=…)` (`:15561`) / `_ensure_reconnect_watcher_running()` (`:15577`); give-up handling `_on_reconnect_watcher_gave_up(name)` (`:15479`) and `_schedule_slow_reconnect_watcher_respawn(attempt=…)` (`:15518`). Backoff `_reconnect_backoff(attempt)` (`:4656`) = `min(30 * 2**(attempt-1), _RECONNECT_BACKOFF_CAP)` → 30 s, 60 s, 120 s, … capped at 5 minutes. Escalation `_reconnect_needs_attention(info, now)` (`:4661`) fires after `_RECONNECT_ATTENTION_AFTER_SECONDS` of **continuous** queueing — `queued_at` is re-stamped each time the platform re-enters the queue, so a platform that reconnects and later fails again starts a fresh clock; `<= 0` disables escalation.
- **Inputs / options:** n/a
- **Outputs / side effects:** a NEEDS_ATTENTION signal on prolonged failure.
- **Config / env:** `gateway.platform_connect_timeout`.
- **Edge cases / guards:** Secondary-profile reconnects have their own scheduling (`_run_secondary_profile_reconnect`, `:16853`; `_schedule_secondary_profile_startup_reconnect`, `:16954`; `_schedule_secondary_profile_reconnect`, `:17023`; `_cancel_secondary_profile_reconnect_tasks`, `:15859`).
- **Rebuild notes:** Exponential backoff with a cap, plus a continuous-failure escalation clock.

### Adapter creation, credential and listener claims  `id: gw-core.adapter-claims`
- **Surface:** Core
- **Where:** startup; fails fast on token or port collisions.
- **What it does:** Prevents two profiles/adapters from polling the same bot token or binding the same listener.
- **How it works:** `_create_adapter(...)` (`gateway/run.py:17350`), `_adapter_credential_claim(...)` (`:17270`), `_adapter_listener_claim(platform, adapter)` (`:17280`), `_adapter_credential_fingerprint(adapter)` (`:17302`), `_make_adapter_auth_check(...)` (`:17481`), `_dispose_unused_adapter(adapter)` (`:4584`), `_platform_has_bot_credential(platform, platform_config)` (`:2617`).
- **Inputs / options:** n/a
- **Outputs / side effects:** Startup fails naming both conflicting profiles when two profiles configure the same `(platform, token)`.
- **Config / env:** per-platform tokens.
- **Edge cases / guards:** `MultiplexConfigError` (`:2438`) and `SecondaryPortBindingConfigError` (`:2447`) carry the two failure classes; a port-binding conflict skips only that secondary profile while a security-config error remains fatal.
- **Rebuild notes:** Claim credentials and listeners in a registry before connecting anything.

### Startup security guard for `open` own-policy platforms  `id: gw-core.own-policy-open-guard`
- **Surface:** Core
- **Where:** gateway startup; aborts with a fatal config error.
- **What it does:** Refuses to start when a network-exposed adapter's own policy is `open` and no allow-all opt-in is configured.
- **How it works:** `_own_policy_open_startup_violation(config)` (`gateway/run.py:3069`) returns the violation string; startup aborts rather than silently dropping the unsafe profile.
- **Inputs / options:** n/a
- **Outputs / side effects:** fatal exit (code 78).
- **Config / env:** `GATEWAY_ALLOW_ALL_USERS` or the platform-specific allow-all flag is the explicit opt-in.
- **Edge cases / guards:** Unlike the port-binding conflict (which skips one profile), this is always fatal — SECURITY.md §2.6 forbids failing open when no allowlist is configured.
- **Rebuild notes:** Security misconfiguration must be fatal, not degraded.

### Drain control marker  `id: gw-core.drain-control`
- **Surface:** Web dashboard | Core
- **Where:** the dashboard's begin/cancel-drain action; marker file `$HERMES_HOME/.drain_request.json`.
- **What it does:** Lets an external process ask a running gateway to stop accepting new turns, without any HTTP control channel into the gateway.
- **How it works:** `gateway/drain_control.py` owns the contract; the watcher is `_drain_control_watcher(interval=1.0)` (`gateway/run.py:9853`) with `_enter_external_drain()` (`:9809`) / `_exit_external_drain()` (`:9829`). Begin-drain writes `{"action": "drain", "requested_at": <iso>, "principal": <str>, "epoch": <instantiation-epoch>, "suppress_notification": <bool>}`; cancel-drain removes the file. Presence of a marker **stamped with the current instantiation epoch** means "external drain active": `gateway_state → "draining"` and new turns are refused; absence — or a marker from a prior instantiation — means not draining.
- **Inputs / options:** the five marker fields above.
- **Outputs / side effects:** `gateway_state.json` flips to `draining`; users get the external-drain reply.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** The **epoch** exists because `HERMES_HOME` is durable (a persistent Fly volume on Hermes Cloud), so a begin-drain marker survives a machine restart — but the actions a drain protects (auto-update, image migrate, env edit, profile change) all restart the machine, which is exactly the signal the drain is over. Reversible: removing the marker reopens the gate.
- **Rebuild notes:** Presence-based marker + instantiation epoch; never trust a durable marker across process lifetimes without one.

### Gateway control socket  `id: gw-core.control-socket`
- **Surface:** Core
- **Where:** `$HERMES_HOME/gateway.sock` (POSIX) or `\\.\pipe\hermes-gateway-<home-hash>` (Windows).
- **What it does:** Gives other local processes (the updater, `hermes serve`/dashboard, the Desktop app) an owned, race-free way to ask the gateway who and what it is — replacing process-table scraping and stale `gateway_state.json` reads.
- **How it works:** `gateway/control_socket.py`. Created at startup, removed on clean shutdown. **A connectable socket with a well-formed `identify` answer IS liveness** — no PID-reuse heuristics. v1 verbs (observation only): `identify` → `pid`, profile label, `hermes_home`, `code_sha`/`code_version`, supervisor kind, served profiles, `start_time`, protocol version; `status` → the live runtime-status payload, answered by the process itself.
- **Inputs / options:** the two verbs, versioned JSON.
- **Outputs / side effects:** JSON responses.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** When the home path is too long for `sun_path` (~104 bytes on macOS/BSD) the socket is bound in the system temp dir and a pointer file `$HERMES_HOME/gateway.sock.path` records the real location; clients follow the pointer transparently. Windows uses a named pipe served on the proactor loop. **Never a TCP port** — filesystem/pipe ACLs are the auth boundary.
- **Rebuild notes:** Owned local socket answering versioned verbs; liveness by connectability, not by PID.

### PID file, runtime lock and gateway state  `id: gw-core.status-pid-lock`
- **Surface:** Core | CLI
- **Where:** `$HERMES_HOME/gateway.pid`, `gateway.lock`, `gateway_state.json`, `gateway-locks/`.
- **What it does:** Detects whether the gateway is running for this `HERMES_HOME`, and prevents two gateways from serving one home.
- **How it works:** `gateway/status.py`. Constants: `_GATEWAY_KIND = "hermes-gateway"`, `_RUNTIME_STATUS_FILE = "gateway_state.json"`, `_LOCKS_DIRNAME = "gateway-locks"`, `_GATEWAY_LOCK_FILENAME = "gateway.lock"`, `_WINDOWS_LOCK_OFFSET = 1024*1024`, `_GATEWAY_RUNNING_PID_CACHE_TTL_SECONDS = 1.0`, `_EPOCH_MIN_PLAUSIBLE = 946684800.0` (2000-01-01Z). Records are validated with `_assert_process_start_time_matches` / `get_process_start_time(pid)` so PID reuse cannot fake liveness. `_profile_label_for_home` validates labels against `^[a-z0-9][a-z0-9_-]{0,63}$`. Public API includes `acquire_gateway_runtime_lock()`, `release_gateway_runtime_lock()`, `owns_gateway_runtime_lock()`, `is_gateway_runtime_lock_active(lock_path)`, `terminate_pid(...)`, `looks_like_gateway_command_line(cmd)`, `looks_like_gateway_runtime_command_line(cmd)`, `scoped_lock_owner_label(record)`, `normalize_updated_at(value)`, `record_start_and_check_storm(...)`.
- **Inputs / options:** n/a
- **Outputs / side effects:** the four files above; runtime status refreshed by `_update_runtime_status(gateway_state=None, exit_reason=None)` (`gateway/run.py:9765`).
- **Config / env:** `HERMES_HOME` — separate homes naturally get separate PID files and service names (`hermes-gateway` for `~/.hermes`, `hermes-gateway-<hash>` otherwise).
- **Edge cases / guards:** `_replace_target_belongs_to_other_profile(existing_pid)` (`gateway/run.py:32402`) and `_looks_like_profile_conflict_from_cmdline(command, our_home)` (`:32522`) stop `--replace` from killing another profile's gateway.
- **Rebuild notes:** PID + process-start-time + an advisory file lock; never PID alone.

### Readiness probes  `id: gw-core.readiness`
- **Surface:** API
- **Where:** authenticated health endpoints.
- **What it does:** Bounded, non-destructive component checks.
- **How it works:** `gateway/readiness.py` — `_probe_state_db(home)` (opens `state.db` read-only and never competes with normal writers; a missing file reports `ok, "not initialized"`), a disk probe with `_DISK_DEGRADED_PERCENT = 90.0`, and a config probe. Results shaped by `_check(status, detail=None, **extra)`.
- **Inputs / options:** n/a
- **Outputs / side effects:** a per-component verdict dict.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Readiness is a component verdict, not user-facing telemetry — nothing renders it directly.
- **Rebuild notes:** Probes must be bounded and side-effect free.

### Disk-status block for `/api/status`  `id: gw-core.disk-status`
- **Surface:** API | Web dashboard
- **Where:** the `disk` block of `GET /api/status`.
- **What it does:** Publishes coarse disk-pressure telemetry so a dashboard or fleet sweep can see a data volume filling up.
- **How it works:** `gateway/disk_status.py` samples live via a single `shutil.disk_usage` (`statvfs`) call — the same thing the readiness probe does per request. No `sampled_at` because there is no staleness dimension. Thresholds combine percent **and** absolute free space, because percent alone misleads in both directions (90 % of 100 GB still leaves 10 GB).
- **Inputs / options:** n/a
- **Outputs / side effects:** MB-granularity numbers, whole-percent usage, and a `pressure` enum.
- **Config / env:** n/a
- **Edge cases / guards:** `/api/status` is an **unauthenticated** liveness probe (`PUBLIC_API_PATHS`), so the block carries only coarse numbers and an enum. An unreadable filesystem degrades to `pressure="unknown"` rather than raising into the endpoint.
- **Rebuild notes:** Public-safe granularity; combine relative and absolute thresholds.

### Memory-status block for `/api/status`  `id: gw-core.memory-status`
- **Surface:** API | Web dashboard
- **Where:** the `memory` block of `GET /api/status`.
- **What it does:** Surfaces memory pressure and suspected OOM kills that would otherwise die in log files.
- **How it works:** `gateway/memory_status.py` distills two already-persisted files — `state/gateway.heartbeat` (rewritten every 30 s by `gateway.shutdown_watchdog.write_loop_heartbeat`, embedding a `gateway.lifecycle_ledger.sample_memory()` snapshot: gateway RSS + system MemAvailable/MemTotal + swap) and the lifecycle sentinel (`gateway.lifecycle_ledger.record_startup` flags `suspected_oom`). No new sampling, no IPC with the gateway process — just two small file reads.
- **Inputs / options:** n/a
- **Outputs / side effects:** MB-granularity numbers, enums, booleans.
- **Config / env:** n/a
- **Edge cases / guards:** Same public-safety class as the disk block. A missing or corrupt file degrades to `pressure="unknown"`.
- **Rebuild notes:** Read side of signals you already persist; do not add a second sampler.

### Memory monitor  `id: gw-core.memory-monitor`
- **Surface:** Config | Core
- **Where:** `agent.log` / `gateway.log`, lines beginning `[MEMORY]`.
- **What it does:** Emits a periodic single-line RSS + Python GC time series so a slow leak is visible.
- **How it works:** `gateway/memory_monitor.py` (ported from cline/cline#10343). A daemon background thread logs a baseline snapshot immediately on start, then one line every N minutes (default **5**), plus a final snapshot on shutdown so "last RSS before exit" is always in the log. Uses `resource` (stdlib, Linux/macOS) first, falling back to `psutil` on Windows.
- **Inputs / options:** `logging.memory_monitor` in `config.yaml`.
- **Outputs / side effects:** grep-friendly `[MEMORY] …` lines.
- **Config / env:** `logging.memory_monitor`.
- **Edge cases / guards:** When neither `resource` nor `psutil` works, a single WARNING is emitted and the monitor disables itself rather than crashing the gateway. Daemon thread — never blocks process exit.
- **Rebuild notes:** One grep-able prefix, a baseline, a final snapshot.

### Lifecycle ledger (unclean-death evidence)  `id: gw-core.lifecycle-ledger`
- **Surface:** Core
- **Where:** `<HERMES_HOME>/state/gateway.lifecycle.json` and `gateway-exit-diag.log`.
- **What it does:** Records *why* the previous gateway life ended — including SIGKILL, kernel OOM, or the whole VM dying, which leave no handler time.
- **How it works:** `gateway/lifecycle_ledger.py`. `record_startup()` reads the sentinel left by the previous life: `phase == "running"` means that life never reached any exit path → it died uncleanly; the finding (including the last heartbeat's memory sample, the closest thing to pre-death telemetry) is appended to `gateway-exit-diag.log` as a `gateway.previous_unclean_exit` record and logged at WARNING; the sentinel is rewritten as `phase=running`. `mark_exited()` rewrites it as `phase=exited` with the exit code and a reason string, wired into `_exit_after_graceful_shutdown` (the single funnel for graceful exits, `gateway/run.py:33467`) and the two `os._exit` sites in `shutdown_watchdog`. `sample_memory()` is the cheap (<1 ms, pure `/proc` reads) snapshot embedded in the 30 s heartbeat.
- **Inputs / options:** n/a
- **Outputs / side effects:** the sentinel and the diag log.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Complements graceful shutdown forensics (who sent SIGTERM) and the exit-path diagnostic log.
- **Rebuild notes:** A "running" sentinel that only a clean exit clears is the cheapest unclean-death detector.

### Shutdown watchdog and loop heartbeat  `id: gw-core.shutdown-watchdog`
- **Surface:** Core
- **Where:** invisible; produces stack dumps and hard exits.
- **What it does:** Four backstops for a frozen event loop, since every asyncio-based recovery path needs the loop that is stuck, and supervisors only restart *dead* processes.
- **How it works:** `gateway/shutdown_watchdog.py`. (1) A plain OS-thread shutdown watchdog armed at `stop()` — if shutdown has not completed within `restart_drain_timeout + grace`, it dumps all-thread stacks via `faulthandler` plus a metadata snapshot, then `os._exit`s so the service manager can revive the process. (2) An event-loop heartbeat file at `<HERMES_HOME>/state/gateway.heartbeat` so external supervision can distinguish "process alive" from "loop frozen" (`gateway_state.json` alone cannot — it only rewrites on transitions/turns). (3) A lifetime thread watchdog that can still diagnose and hard-exit when the loop is too frozen to run its own heartbeat or timeout callbacks. (4) A self-rescheduling floor timer that keeps the loop selector's timeout finite, giving async recovery tasks a chance to resume.
- **Inputs / options:** `DEFAULT_LOOP_WATCHDOG_INTERVAL_S` (30.0), `DEFAULT_LOOP_WATCHDOG_TIMEOUT_S` (10.0), `DEFAULT_LOOP_WATCHDOG_MAX_STRIKES` (3) — overridable by `gateway.loop_watchdog_*`.
- **Outputs / side effects:** stack dumps, heartbeat file, `os._exit`.
- **Config / env:** `gateway.loop_watchdog*`.
- **Edge cases / guards:** Runner glue: `_start_loop_heartbeat_task()` (`gateway/run.py:13384`), `_start_loop_liveness_guards(loop)` (`:13239`), `_stop_loop_liveness_guards()` (`:13284`), `_gateway_loop_exception_handler(...)` (`:810`), `_dump_wedged_turn_stacks(task_id)` (`:3729`), `_watch_gateway_turn_inactivity(...)` (`:3826`), `_abandon_timed_out_gateway_turn(...)` (`:3782`), `_reap_gateway_turn_processes(...)` (`:3648`).
- **Rebuild notes:** Every liveness backstop must live outside the thing it watches.

### Shutdown forensics  `id: gw-core.shutdown-forensics`
- **Surface:** Core
- **Where:** the gateway log and a detached diagnostic file.
- **What it does:** Records who or what triggered a SIGTERM/SIGINT so "the gateway keeps dying" can be diagnosed afterwards.
- **How it works:** `gateway/shutdown_forensics.py`. `snapshot_shutdown_context()` is a fast (<10 ms), non-blocking probe returning a structured dict the synchronous signal handler can log immediately. `spawn_async_diagnostic()` is a fire-and-forget `ps` walk that runs as a **detached subprocess** so it cannot block teardown even if `/proc` is wedged.
- **Inputs / options:** n/a
- **Outputs / side effects:** structured log records.
- **Config / env:** n/a
- **Edge cases / guards:** Anything that needs to wait belongs in the async helper, never in the synchronous probe.
- **Rebuild notes:** Signal handlers must be fast; push the slow evidence-gathering into a detached child.

### Shutdown flush (data-loss prevention)  `id: gw-core.shutdown-flush`
- **Surface:** Core
- **Where:** `<hermes_home>/pending_messages/`.
- **What it does:** Saves messages and live agent transcripts that could not be written to `state.db`, and recovers them on the next startup.
- **How it works:** `gateway/shutdown_flush.py` provides three hooks: `flush_pending_to_file()` — called BEFORE `_pending_messages.clear()` during shutdown, serialising any non-empty pending slots to a JSON file; `recover_pending_to_db()` — called AFTER `runner.start()` on startup, reading the flush files and inserting via `SessionDB.append_message` (so FTS indexing, session metadata and `display_kind` are handled correctly), deleting the file on success; `flush_agent_history_to_file()` — called from `_finalize_shutdown_agents` when `_flush_messages_to_session_db` raises, dumping the live `agent._session_messages` to the same atomic recovery directory.
- **Inputs / options:** n/a
- **Outputs / side effects:** JSON recovery files.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** The motivating failure was FTS5 index corruption blocking `INSERT INTO messages`, after which `.clear()` on shutdown discarded the only surviving copy.
- **Rebuild notes:** Never clear an in-memory buffer that failed to persist without dumping it first.

### cgroup cleanup  `id: gw-core.cgroup-cleanup`
- **Surface:** Core
- **Where:** systemd `ExecStopPost=` for the gateway unit.
- **What it does:** SIGKILLs any process left in the unit's cgroup after the gateway's main process has exited, so orphaned helpers (`adb`, platform bridges) do not block `Restart=always`.
- **How it works:** `gateway/cgroup_cleanup.py` reads `/proc/self/cgroup` (`^0::(.+)$`), then iterates `/sys/fs/cgroup<path>/cgroup.procs` and sends per-PID SIGKILLs.
- **Inputs / options:** n/a
- **Outputs / side effects:** orphaned processes are killed.
- **Config / env:** n/a
- **Edge cases / guards:** Deliberately per-PID rather than writing `1` to `cgroup.kill`, because the kernel returned `EINVAL` on the cgroup-wide kill in the original incident while per-PID signal delivery still worked. Only runs after the main process exits.
- **Rebuild notes:** Clean the cgroup, not just the main PID.

### Code-skew detection  `id: gw-core.code-skew`
- **Surface:** Core | Gateway/Telegram
- **Where:** risky operations such as `/model` switching.
- **What it does:** Detects that the checkout was updated under a long-lived gateway process and refuses with a clear "restart the gateway" message instead of crashing on a cryptic `ImportError`.
- **How it works:** `gateway/code_skew.py` snapshots the checkout revision at startup (via `hermes_cli.main._read_git_revision_fingerprint`, which is worktree-aware and already imported in a gateway process) and compares on demand.
- **Inputs / options:** n/a
- **Outputs / side effects:** a refusal message.
- **Config / env:** n/a
- **Edge cases / guards:** If the revision cannot be read (non-git install, IO error) the boot snapshot stays `None` and skew detection no-ops — it never produces a false positive.
- **Rebuild notes:** `sys.modules` is frozen at boot; guard first-time lazy imports on new code paths.

### Scale-to-zero  `id: gw-core.scale-to-zero`
- **Surface:** Env | Config
- **Where:** hosted/relay deployments only.
- **What it does:** Lets an idle gateway quiesce its relay link and then suspend its own machine.
- **How it works:** `gateway/scale_to_zero.py` plus runner glue: `_scale_to_zero_watcher(interval=30.0)` (`gateway/run.py:9509`), `_scale_to_zero_should_arm()` (`:9391`), `_log_scale_to_zero_not_armed_reason()` (`:9411`), `_scale_to_zero_is_idle()` (`:9449`), `_scale_to_zero_note_real_inbound()` (`:9484`), `_scale_to_zero_has_live_background_work()` (`:9276`), `_scale_to_zero_active_messaging_platforms()` (`:9363`), `_relay_adapter_for_dormancy()` (`:9501`), `_scale_to_zero_self_suspend()` (`:9611`). The gateway self-suspends through the local Fly Machines API socket rather than relying on `autostop:"suspend"` because Fly Proxy judges idleness solely on inbound proxied connections and cannot see an in-flight agent turn (outbound-only LLM traffic).
- **Inputs / options:** arming requires ALL of: the `HERMES_SCALE_TO_ZERO` env stamp (set by the NAS "Labs" toggle — deliberately not a user config key), messaging that is relay-only or absent, and a registered wakeUrl. Idle requires no in-flight agent turn AND no inbound for N minutes AND no live background work.
- **Outputs / side effects:** `go_dormant()` on the relay transport, then machine suspend. Wake is platform-side (autostart on wakeUrl).
- **Config / env:** `HERMES_SCALE_TO_ZERO`, `gateway.scale_to_zero.idle_timeout_minutes` (default 2).
- **Edge cases / guards:** Only real (user-originated) inbound stamps the idle clock — internal/system events (background-process completions, startup-restore replays) are not traffic and would otherwise keep a genuinely idle gateway awake. Suspend only ever fires after the idle predicate holds AND the dormant quiesce completed, closing the buffered-event black hole.
- **Rebuild notes:** Own the suspend decision; never let an external proxy guess your idleness.

### Event hook system  `id: gw-core.hooks`
- **Surface:** Core
- **Where:** `~/.hermes/hooks/<name>/` containing `HOOK.yaml` (metadata: name, description, events list) and `handler.py` (`async def handle(event_type, context)`).
- **What it does:** Fires user handlers at key gateway/agent lifecycle points.
- **How it works:** `gateway/hooks.py` (`HookRegistry`), used by the runner as `self.hooks.emit(...)` / `emit_collect(...)`.
- **Inputs / options — events:** `gateway:startup` (gateway process starts); `session:start` (new session created — first message of a new session); `session:end` (user ran `/new` or `/reset`); `session:reset` (reset completed, new session entry created); `agent:start` (agent begins processing a message); `agent:step` (each turn in the tool-calling loop); `agent:end` (agent finishes); `command:*` (any slash command, wildcard match); plus adapter-supplied `reaction:added` / `reaction:removed`.
- **Outputs / side effects — context dict** for `agent:start` / `agent:end`: `platform` (e.g. `"telegram"`, `"matrix"`, `"slack"`), `user_id`, `chat_id`, `thread_id` (Telegram forum-topic / thread root id as a string, empty when not in a thread), `chat_type` (`"dm"` | `"group"` | `"forum"`, empty if unknown), `session_id`, `message` (inbound text truncated to 500 chars). `agent:end` adds `response` (agent response truncated to 500 chars).
- **Config / env:** hook directories under `~/.hermes/hooks/`.
- **Edge cases / guards:** Errors in hooks are caught and logged but never block the main pipeline.
- **Rebuild notes:** Directory-discovered handlers, one async entry point, failures isolated.

### Platform adapter registry  `id: gw-core.platform-registry`
- **Surface:** Core
- **Where:** plugin authors: `PluginContext.register_platform()`.
- **What it does:** Lets built-in and plugin platform adapters self-register so the gateway can discover and instantiate them without a hardcoded if/elif chain.
- **How it works:** `gateway/platform_registry.py` — `platform_registry.register(PlatformEntry(...))`. Plugin adapters are looked up **first**; if nothing is found the gateway falls through to the legacy `_create_adapter()` chain.
- **Inputs / options — `PlatformEntry` fields used across the gateway:** `name`, `label`, `adapter_factory(cfg)`, `check_fn` (passive dependency probe, never installs), `ensure_deps_fn`, `validate_config(cfg)`, `is_connected(cfg)`, `required_env` (list), `install_hint`, `allowed_users_env`, `allow_all_env`, `env_enablement_fn`, `apply_yaml_config_fn(yaml_cfg, platform_cfg)`, `authorization_is_upstream`. Registry API: `register`, `get(name)`, `is_registered(name)`, `all_entries()`, `plugin_entries()`.
- **Outputs / side effects:** dynamic `Platform` members, config bridging, auth env names, enablement.
- **Config / env:** plugin installation.
- **Edge cases / guards:** The `check_fn` / `ensure_deps_fn` split keeps dependency verification passive at load time so the gateway never installs SDKs during startup.
- **Rebuild notes:** Data-driven adapter registry with explicit capability callbacks.

### Relay (connector-fronted platforms)  `id: gw-core.relay`
- **Surface:** Core | Config
- **Where:** `gateway.relay_url` / `GATEWAY_RELAY_URL`; EXPERIMENTAL.
- **What it does:** One generic gateway adapter fronted by an external connector that owns the platform credentials, so Discord/Telegram/Slack/WhatsApp can be served without the gateway holding any bot token.
- **How it works — modules:** `gateway/relay/__init__.py` (package doc + activation contract), `gateway/relay/adapter.py` (`RelayAdapter`, a `BasePlatformAdapter` subclass implementing `connect`/`disconnect`/`send`/`get_chat_info` plus `MAX_MESSAGE_LENGTH`, `message_len_fn`, `supports_draft_streaming` from the descriptor), `gateway/relay/descriptor.py` (`CapabilityDescriptor` — the handshake payload naming the fronted platform and its char limit, draft-streaming, edit/threading support, markdown dialect, length unit; a wire-serializable projection of `PlatformEntry` plus the per-instance capability methods; evolution is additive-only, gated by `contract_version`), `gateway/relay/transport.py` (the `RelayTransport` protocol surface: lifecycle `connect`/`disconnect`; `handshake` returning the descriptor; `set_inbound_handler` for normalized `MessageEvent`s; `send_outbound` for send/edit/typing actions plus `get_chat_info` and `send_interrupt`), `gateway/relay/ws_transport.py` (the production WebSocket client; newline-delimited JSON frames — gateway→connector `hello`, `outbound`, `interrupt`; connector→gateway `descriptor`, `inbound`, `outbound_result`, `interrupt_inbound`; frame shapes `hello {type, platform, botId}`, `descriptor {type, descriptor}`, `inbound {type, event, bufferId?}`, `outbound {type, requestId, action}`, `outbound_result {type, requestId, result}`), `gateway/relay/auth.py` (gateway half of two HMAC schemes matching the connector's TypeScript byte-for-byte — WS upgrade auth presents `Authorization: Bearer <token>` where `token = base64url(f"{payload}:{exp}:{sig}")`, `sig = HMAC_SHA256(f"{payload}:{exp}", secret)` and `payload == gateway_id`), `gateway/relay/media.py` (media travels **by reference**: `download(url)` GETs a connector-re-hosted attachment to a local temp file because the agent's vision/file tools consume local paths; `upload(path)` POSTs bytes to `/relay/media` and returns a `/relay/media/{id}` reference for a later `send_media` op, so locally-generated artifacts cross without the gateway needing a public URL), `gateway/relay/command_manifest.py` (the gateway DECLARES its slash-command set on the `hello` frame so the connector — which holds the Discord token — can reconcile Discord's global application-command registration: GET → diff → bulk PUT, idempotent, best-effort; it mirrors the native Discord tree name-for-name so the palette is identical between native and relay deployments).
- **Inputs / options:** `extra.relay_url` or `extra.url`.
- **Outputs / side effects:** the gateway sees ordinary `MessageEvent`s and calls `adapter.send`; there is **no** per-platform gateway code.
- **Config / env:** `GATEWAY_RELAY_URL`, `GATEWAY_RELAY_ALLOW_DIRECT_PLATFORMS`, `gateway.relay_url`.
- **Edge cases / guards:** Authorization for relay traffic is delegated to the authenticated upstream (see `gw-core.authorization`) — but only for events actually delivered over the relay WS (`delivered_via_upstream_relay is True`) or whose adapter declares `authorization_is_upstream=True`. EXPERIMENTAL: the transport protocol and descriptor schema may change without a deprecation cycle until ≥2 Class-1 platforms validate them. Formal cross-repo interface: `docs/relay-connector-contract.md`.
- **Rebuild notes:** Negotiate capabilities at handshake, carry media by reference, and keep credentials on exactly one side.

### Browser-control broker  `id: gw-core.browser-control-broker`
- **Surface:** Core
- **Where:** invisible; the in-process heart of browser control.
- **What it does:** Binds an identity-scoped controller (whoever physically drives a browser) to callers (agents talking to it over any transport), without the broker knowing anything about HTTP or WebSocket.
- **How it works:** `gateway/browser_control_broker.py`. Registration tickets are short-lived, single-use, identity-bound and cryptographically random: `mint_ticket` returns an opaque `secrets`-derived value (≥ 32 chars) plus an expiry derived from an injected clock; `consume_ticket` exchanges it exactly once for the `ControllerScope` it was minted for, raising `ControllerTicketInvalid` for unknown, consumed, or expired values. The ticket is the only cross-transport credential minted here — transports decide how to carry it.
- **Inputs / options:** ticket mint/consume, command submit/complete/cancel, observation.
- **Outputs / side effects:** command routing to the bound controller.
- **Config / env:** n/a
- **Edge cases / guards:** By construction a controller is never addressable by a caller that merely resembles the right identity; a command can never be completed twice, cancelled by a stranger, or observed after its owner has gone away. Contract exercised by `tests/gateway/test_browser_control_broker.py`.
- **Rebuild notes:** Make the violations structurally impossible, not merely discouraged.

### Browser-control artifact store  `id: gw-core.browser-control-artifacts`
- **Surface:** Core | API
- **Where:** invisible; screenshots, PDFs and uploads exchanged with a controlled browser.
- **What it does:** One-shot authenticated HTTPS upload/download of bounded browser-control artifacts.
- **How it works:** `gateway/browser_control_artifacts.py` is the transport-neutral store core — it knows nothing about aiohttp; the API-server routes authenticate callers and enforce rate limits, then hand bytes here. `store` assigns a fresh random hex id; `_artifact_path` accepts only `[0-9a-f]{N}` ids and resolves them under a controlled root; SHA-256 validation, exact MIME/size caps, and TTL cleanup apply.
- **Inputs / options:** bytes + declared MIME.
- **Outputs / side effects:** files under the artifact root, referenced by `artifact_id`.
- **Config / env:** n/a
- **Edge cases / guards:** The controller WebSocket is a **command channel, not a file pipe** — frames carry only `artifact_id` strings, making base64 screenshots in control frames structurally impossible. Server-minted ids prevent path traversal. Contract exercised by `tests/gateway/test_browser_control_artifacts.py`.
- **Rebuild notes:** Server-minted ids, a strict id charset, a controlled root, and a TTL.

### Kanban watchers  `id: gw-core.kanban-watchers`
- **Surface:** Core
- **Where:** invisible background loops; delivers kanban notifications and artifacts into chats.
- **What it does:** Subscribes to kanban boards, delivers notifications/artifacts, and drives the multi-agent dispatcher.
- **How it works:** `gateway/kanban_watchers.py` — `GatewayKanbanWatchersMixin`, extracted verbatim from `run.py` (~1 000 LOC) and inherited by `GatewayRunner`, so every `self._kanban_*` call site resolves identically through the MRO. Uses the same logger name (`gateway.run`) as before so extracted log records keep their identity. Messages are localized with `agent.i18n.t`.
- **Inputs / options:** kanban board configuration (owned by the automation shard).
- **Outputs / side effects:** chat notifications and artifact deliveries.
- **Config / env:** kanban config.
- **Edge cases / guards:** Uses only `self` state — a behaviour-neutral move.
- **Rebuild notes:** Mixins are a safe decomposition when the extracted code only touches `self`.

### Turn context and turn runner  `id: gw-core.turn-context`
- **Surface:** Core
- **Where:** invisible; per-turn plumbing.
- **What it does:** Carries all per-turn state shared between `_run_agent_inner` and the `TurnRunner` collaborator that owns the tool-progress callbacks.
- **How it works:** `gateway/turn_context.py` (`TurnContext` dataclass) + `TurnRunner` (`gateway/run.py:4679`). Every local that the old ~250-LOC `progress_callback` and ~353-LOC `send_progress_messages` closures captured became a field. Mutable per-turn state uses single-element list containers (`last_progress_msg`, `repeat_count`, `last_tool`, `last_was_terminal_block`, `long_tool_hint_fired`, `agent_holder`, …) so mutation stays visible exactly as it did through closure cells. `_run_still_current` stays a callable because it captures `self`/`session_key`/`run_generation`.
- **Inputs / options:** `TurnRunner` methods: `progress_callback` (`:4695`), `_send_native_task_card_progress` (`:5011`), `send_progress_messages` (`:5207`), `voice_ack_callback` (`:5568`), `native_tool_start_callback` (`:5595`), `native_tool_complete_callback` (`:5620`), `combined_tool_start_callback` (`:5643`), `_step_callback_sync` (`:5651`), `_event_callback_sync` (`:5678`), `_attach_session_title_callback` (`:5688`), `_status_callback_sync` (`:5745`), `run_sync` (`:5781`).
- **Outputs / side effects:** n/a
- **Config / env:** display settings.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Turn a closure soup into an explicit per-turn record before adding features to it.

### WhatsApp identity canonicalisation  `id: gw-core.whatsapp-identity`
- **Surface:** Core
- **Where:** invisible; authorization and session keys.
- **What it does:** Collapses the same human's LID (`999999999999999@lid`) and phone (`15551234567@s.whatsapp.net`) JID forms to one stable identity.
- **How it works:** `gateway/whatsapp_identity.py` — `normalize_whatsapp_identifier(id)` strips JID/LID/device/plus syntax to the bare numeric identifier; `canonical_whatsapp_identifier(id)` walks the bridge's `lid-mapping-*.json` files and returns a stable canonical identity; `expand_whatsapp_aliases(id)` returns the full alias set for allow-list matching. Single source of truth shared by `gateway/run.py` (authorization) and `gateway/session.py` (session keys) so the two can never drift.
- **Inputs / options:** an identifier in any form.
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** Without this, a bridge alias flip forks one member into two isolated per-user sessions and can drop them from an allowlist.
- **Rebuild notes:** Canonicalise identity once, in a module both the auth and keying paths import.

### `terminal.cwd` placeholder resolution  `id: gw-core.cwd-placeholder`
- **Surface:** Config | Core
- **Where:** `terminal.cwd` in config; env `TERMINAL_CWD`, `MESSAGING_CWD`.
- **What it does:** Decides what working directory gateway-spawned terminal tools get when `terminal.cwd` is unset or a placeholder.
- **How it works:** `gateway/cwd_placeholder.py::resolve_placeholder_terminal_cwd(configured_cwd, terminal_backend, messaging_cwd, docker_mount_cwd_to_workspace, home_fallback)`. `CWD_PLACEHOLDERS = {".", "auto", "cwd"}`. Cases: **local** + placeholder → `MESSAGING_CWD` or `home_fallback`; **docker** + placeholder + mount on + host `MESSAGING_CWD` → the host path (so `terminal_tool` can map `/host/project` → `/workspace`); **docker** + placeholder + mount off → `None` (sandbox default); other non-local backends + placeholder → `None`.
- **Inputs / options:** as above.
- **Outputs / side effects:** sets or leaves `TERMINAL_CWD`.
- **Config / env:** `terminal.cwd`, `terminal.backend`, `MESSAGING_CWD`, `TERMINAL_CWD`.
- **Edge cases / guards:** A non-placeholder configured value always wins. The gateway must not blindly map host `Path.home()` into container backends.
- **Rebuild notes:** Placeholder set + a backend-aware decision table.

### Telegram rich-message reply index  `id: gw-core.rich-sent-store`
- **Surface:** Core | Platform:Telegram
- **Where:** `$HERMES_HOME/state/rich_sent_index.json`.
- **What it does:** Remembers the text of messages sent via Telegram's `sendRichMessage` so a user's reply to one is not blind.
- **How it works:** `gateway/rich_sent_store.py` — `record(chat_id, message_id, text)` at send time; lookup by `reply_to_id` on inbound. Telegram does **not** echo a rich message's content back in `reply_to_message` (verified: `.text`/`.caption` empty, `.api_kwargs` None), so without this index the agent cannot see what was referenced.
- **Inputs / options:** n/a
- **Outputs / side effects:** the JSON index.
- **Config / env:** `HERMES_HOME` (profile-aware via `get_hermes_home()`).
- **Edge cases / guards:** Bounded to `_MAX_ENTRIES = 1000` entries and `_MAX_TEXT_CHARS = 2000` per entry; every operation swallows errors and degrades to a no-op / `None` so it can never break a send or an inbound message.
- **Rebuild notes:** Keep a bounded local index of anything the platform will not echo back.

### Sticker description cache  `id: gw-core.sticker-cache`
- **Surface:** Core | Platform:Telegram
- **Where:** `~/.hermes/sticker_cache.json`.
- **What it does:** Describes Telegram stickers with the vision tool once and reuses the description on every later send of the same sticker.
- **How it works:** `gateway/sticker_cache.py`. Keyed by Telegram's `file_unique_id`; written atomically. Vision prompt (verbatim): `"Describe this sticker in 1-2 sentences. Focus on what it depicts -- character, action, emotion. Be concise and objective."`
- **Inputs / options:** n/a
- **Outputs / side effects:** the JSON cache.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Corrupt/unreadable cache degrades to `{}`.
- **Rebuild notes:** Cache by the platform's stable content id, not by file path.

### Gateway localisation catalog  `id: gw-core.locale-catalog`
- **Surface:** Core | Docs
- **Where:** `locales/<lang>.yaml`.
- **What it does:** Holds the user-facing static messages of the CLI approval prompt and gateway slash-command replies in 17 languages.
- **How it works:** `locales/en.yaml` is the baseline / source of truth (471 lines, 367 keys); keys are dotted paths (`gateway.*`, `approval.*`) and values may contain `{placeholder}` tokens for `str.format`. `tests/agent/test_i18n.py` asserts catalog parity — a new key must be added to EVERY locale file in the same commit.
- **Inputs / options:** available locales: `af`, `ar`, `de`, `en`, `es`, `fr`, `ga`, `hu`, `it`, `ja`, `ko`, `pt`, `ru`, `tr`, `uk`, `zh`, `zh-hant`.
- **Outputs / side effects:** localized chat replies via `agent.i18n.t(key, **kwargs)`.
- **Config / env:** locale selection config.
- **Edge cases / guards:** Deliberately **out of scope** for translation: agent-generated output, log lines, error tracebacks, tool outputs, and slash-command descriptions — see `agent/i18n.py` for the rationale. Model ids, provider names, capability strings and cost figures are identifiers, not prose, and stay untranslated.
- **Rebuild notes:** One baseline catalog, enforced parity, and an explicit non-goal list.

### Systemd sd_notify support  `id: gw-core.systemd-notify`
- **Surface:** Core
- **Where:** systemd units with `Type=notify`.
- **What it does:** Sends `sd_notify` datagrams (READY, WATCHDOG) to systemd.
- **How it works:** `gateway/systemd_notify.py::notify(message)` reads `$NOTIFY_SOCKET`, translating systemd's `@abstract` notation to Python's `"\0"`-prefixed address form (`_notify_address`), and sends one non-blocking datagram. Runner glue: `_start_systemd_watchdog()` (`gateway/run.py:15891`), `_stop_systemd_watchdog()` (`:15907`).
- **Inputs / options:** any sd_notify message string.
- **Outputs / side effects:** returns `False` when `NOTIFY_SOCKET` is unset or the message is empty.
- **Config / env:** `NOTIFY_SOCKET`, `gateway.systemd_watchdog_seconds`.
- **Edge cases / guards:** Notification failures are deliberately non-fatal — a missing socket or older platform must never prevent startup.
- **Rebuild notes:** Optional integration that degrades to a no-op.

### Handoff watcher (cross-instance session handoff)  `id: gw-core.handoff`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Watches configured scopes for handoff requests and processes them, reclaiming stale ones.
- **How it works:** `_handoff_watcher(...)` (`gateway/run.py:14569`), `_process_handoff(...)` (`:14730`), scope list `_handoff_watch_scopes(runner)` (`:2475`), stale reclaim `_reclaim_stale(runner)` (`:2511`), profile scope helper `_profile_runtime_scope(profile_home)` (`:2546`), profile home list `_multiplex_profile_homes(config)` (`:2463`).
- **Inputs / options:** n/a
- **Outputs / side effects:** sessions are handed between instances.
- **Config / env:** multiplex/profile config.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Supervised subprocess spawning  `id: gw-core.supervised-spawn`
- **Surface:** Core
- **Where:** invisible; helper processes owned by the gateway.
- **What it does:** Spawns and restarts helper subprocesses with backoff.
- **How it works:** `_spawn_supervised(...)` (`gateway/run.py:14428`) with `_supervised_backoff(attempt)` (`:14417`).
- **Inputs / options:** n/a
- **Outputs / side effects:** child processes.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Hosted-room worker lifecycle (gateway side)  `id: gw-core.hosted-room-worker`
- **Surface:** Core
- **Where:** invisible.
- **What it does:** Starts, watches and stops the hosted-room worker from within the gateway process.
- **How it works:** `_start_hosted_room_worker_sync()` (`gateway/run.py:13348`), `_ensure_hosted_room_worker()` (`:13364`), `_hosted_room_worker_watcher(interval=1.0)` (`:13367`), `_stop_hosted_room_worker(timeout=5.0)` (`:13374`).
- **Inputs / options:** n/a
- **Outputs / side effects:** worker task lifecycle.
- **Config / env:** hosted-rooms config.
- **Edge cases / guards:** The hosted-rooms feature itself is a sibling shard's scope; only the gateway-side supervision is documented here.
- **Rebuild notes:** n/a

### Plugin message injection  `id: gw-core.plugin-message-injection`
- **Surface:** Core
- **Where:** plugin authors.
- **What it does:** Lets a plugin push a message into a live gateway session from outside the inbound path.
- **How it works:** `_install_plugin_message_injector()` (`gateway/run.py:20255`), `_clear_plugin_message_injector()` (`:20264`), `_schedule_plugin_message_injection(...)` (`:20270`), `_dispatch_plugin_message_injection(...)` (`:20338`).
- **Inputs / options:** plugin-supplied payload.
- **Outputs / side effects:** an injected turn.
- **Config / env:** plugin installation.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Session-hygiene compaction  `id: gw-core.hygiene-compaction`
- **Surface:** Core
- **Where:** invisible; keeps long sessions inside the context window.
- **What it does:** Compresses an over-threshold transcript before the turn calls the model, with cooldowns after failures.
- **How it works:** `run_codex_hygiene_compaction(...)` (`gateway/run.py:317`), `hygiene_compaction_recovered(...)` (`:247`), `_hygiene_cooldown_for_failure(...)` (`:174`), `_record_hygiene_cooldown(...)` (`:464`), `_reset_hygiene_failure_streak(gateway, session_key)` (`:225`), `hygiene_wait_should_extend(...)` (`:445`), `_hygiene_compression_timeout_message(...)` (`:291`), `_seed_hygiene_system_prompt(...)` (`:739`), `_stamp_hygiene_compression_provenance(...)` (`:1484`), and the `HygieneTurnHoldExceeded` exception (`:2451`).
- **Inputs / options:** compression config (`auxiliary.compression.model`).
- **Outputs / side effects:** user-visible strings live in `locales/en.yaml` → `gateway.compress.*`, e.g. `"ℹ️ Context compression deferred — summary still streaming. Continuing without compression this turn."` (`turnhold_deferred`), `"⚠️ Summary generation failed ({error}). {count} historical message(s) were removed and replaced with a placeholder; earlier context is no longer recoverable. Consider checking your auxiliary.compression model configuration."`, `"⚠️ Compression aborted ({error}). No messages were dropped — conversation is unchanged. Run /compress to retry, /reset for a clean session, or check your auxiliary.compression model configuration."`, `"ℹ️ Configured compression model \`{model}\` failed ({error}). Recovered using your main model — context is intact — but you may want to check \`auxiliary.compression.model\` in config.yaml."`
- **Config / env:** `auxiliary.compression.*`, `compression.progress_notices`.
- **Edge cases / guards:** Compression is interrupt-protected; a follow-up arriving mid-compression is demoted to queue (`gw-core.compression-demotion`).
- **Rebuild notes:** Failure cooldowns and an explicit "nothing was dropped" abort message.

---

## 10. Turn runtime, error surfaces and remaining modules

### Empty / failed response normalization  `id: gw-core.empty-response`
- **Surface:** Gateway/Telegram
- **Where:** the chat, whenever a turn produces no visible text.
- **What it does:** Turns silence into an actionable message so a dropped turn is never invisible.
- **How it works:** `_normalize_empty_agent_response(agent_result, response, history_len=0)` (`gateway/run.py:4398`).
- **Inputs / options:** the agent result dict (`failed`, `error`, `failure_reason`, `interrupted`, `api_calls`, `partial`) plus the history length.
- **Outputs / side effects (verbatim, in evaluation order):**
  - Session-persistence failure with a disk cause: `"⚠️ Session storage was temporarily unavailable, so this turn was stopped to protect your conversation history. Please check available disk space, then send your message again."`
  - Other session-persistence failure: `"⚠️ Session storage was temporarily unavailable, so this turn was stopped to protect your conversation history. Your message should already be saved — please send it again in a moment."`
  - Context-window failure (error mentions `context`, `token`, `too large`, `too long`, `exceed`, `payload`, or a `400` with `history_len > 50`): `"⚠️ Session too large for the model's context window.\nUse /compact to compress the conversation, or /reset to start fresh."`
  - Other failure: `"The request failed: <error, first 300 chars>\nTry again or use /reset to start a fresh session."`
  - Interrupted with `api_calls == 0`: `"⚠️ Your message was interrupted before processing started (likely by a recent /stop). Please send it again."`
  - Interrupted with work done: the (empty) response is returned unchanged — the silence is intentional and any queued/interrupting message is delivered by the recursive drain.
  - `api_calls > 0` and hidden-reasoning-incomplete: `""` (silent).
  - `api_calls > 0` and `partial`: `"⚠️ Processing stopped: <error, first 200 chars>. Try again."`
  - `api_calls > 0` otherwise: `"⚠️ Processing completed but no response was generated. This may be a transient error — try sending your message again."`
  - `api_calls == 0`, not failed/interrupted/partial: `"⚠️ Your message wasn't processed (the previous turn was still being cleaned up). Please send it again."`
- **Config / env:** n/a
- **Edge cases / guards:** `error` can be an explicit `None` in the result dict (it is built with `'error': holder.get('error')`), which bypasses `dict.get`'s default — hence the `or "unknown error"` guard, otherwise the user saw `"The request failed: None"`. Suggesting `/reset` on a session-persistence failure would be actively harmful (it destroys context and does not fix the storage problem), so those get a dedicated message. `_is_gateway_hidden_reasoning_incomplete_turn(agent_result)` (`:4508`) detects retry-exhausted turns that produced hidden reasoning but no visible answer.
- **Rebuild notes:** Enumerate every "no text" cause and give each a distinct, actionable sentence.

### Turn model / runtime resolution  `id: gw-core.turn-runtime`
- **Surface:** Core
- **Where:** invisible; picks the model and provider for each turn.
- **What it does:** Resolves which model, provider, credentials and request overrides a turn runs with.
- **How it works:** `_resolve_session_agent_runtime(source, session_key, user_config)` (`gateway/run.py:8651`) — priority session `/model` → `channel_overrides` → global config; `_resolve_turn_agent_config(user_message, model, runtime_kwargs)` (`:8822`); `_resolve_runtime_agent_kwargs()` (`:3152`); `_resolve_gateway_model_context(model)` (`:3252`) returning `_GatewayModelContext` (`:3242`); `_resolve_runtime_agent_kwargs_for_provider(provider)` (`:3358`); `_deep_merge_request_overrides(base, override)` (`:3383`); `_credential_pool_for_provider(provider)` (`:3396`); `_try_resolve_fallback_provider()` (`:3413`); `_resolve_gateway_model(config)` (`:4150`); `_current_max_iterations()` (`:2409`) with `_bridge_max_turns_from_config(home)` (`:2360`).
- **Inputs / options:** n/a
- **Outputs / side effects:** the agent's construction kwargs.
- **Config / env:** `model.model`, per-channel overrides, session overrides, `agent.max_turns`.
- **Edge cases / guards:** `_reload_runtime_env_preserving_config_authority()` (`:2331`) hot-reloads `.env` per turn without letting env clobber config-owned values.
- **Rebuild notes:** One resolver consulted by every path that needs "what model is this turn".

### Fallback provider chain  `id: gw-core.fallback-chain`
- **Surface:** Config
- **Where:** `fallback_providers:` (and legacy `fallback_model:`) in `config.yaml`.
- **What it does:** Automatically retries a turn on the next provider when the primary fails.
- **How it works:** `_load_fallback_model()` (`gateway/run.py:10514`) merges `fallback_providers` with any legacy `fallback_model` entries (`fallback_providers` first) through `get_fallback_chain(cfg)`; `_refresh_fallback_model()` (`:10532`) re-reads from disk for the next agent create/reuse; `_apply_fallback_chain_to_agent(agent, chain)` (`:10580`).
- **Inputs / options:** list of provider/model entries.
- **Outputs / side effects:** the agent carries the chain.
- **Config / env:** `fallback_providers`, `fallback_model`.
- **Edge cases / guards:** Loaded via the canonical gateway loader so the managed overlay and `${VAR}` expansion apply.
- **Rebuild notes:** Refresh the chain per turn so a config edit takes effect without a restart.

### Provider routing (OpenRouter)  `id: gw-core.provider-routing`
- **Surface:** Config
- **Where:** `config.yaml` provider-routing section.
- **What it does:** Passes OpenRouter provider-routing preferences into every gateway turn.
- **How it works:** `_load_provider_routing()` (`gateway/run.py:10502`).
- **Inputs / options:** the routing dict.
- **Outputs / side effects:** included in agent request overrides.
- **Config / env:** provider-routing config.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Priority Processing (`service_tier`)  `id: gw-core.service-tier`
- **Surface:** Config | Gateway/Telegram
- **Where:** `agent.service_tier:` in `config.yaml`; `/fast [normal|fast|status]` in chat.
- **What it does:** Requests OpenAI Priority Processing for gateway turns.
- **How it works:** `_load_service_tier()` (`gateway/run.py:10232`) — accepted values mirror the CLI: `fast` / `priority` / `on` → `"priority"`; `normal` / `default` / `standard` / `off` / `none` / unset → `None`. Per-session override via `_resolve_session_service_tier(...)` (`:10182`) and `_set_session_service_tier_override(...)` (`:10210`).
- **Inputs / options:** `/fast normal`, `/fast fast`, `/fast status`.
- **Outputs / side effects (from `locales/en.yaml` → `gateway.fast.*`):** `"⚡ /fast is only available for OpenAI models that support Priority Processing."`; `"⚡ Priority Processing\n\nCurrent mode: \`{mode}\`\n\n_Usage:_ \`/fast <normal|fast|status>\`"`; `"⚠️ Unknown argument: \`{arg}\`\n\n**Valid options:** normal, fast, status"`; `"⚡ ✓ Priority Processing: **{label}** (saved to config)\n_(takes effect on next message)_"`; `"⚡ ✓ Priority Processing: **{label}** (this session only)"`; labels `"FAST"` / `"NORMAL"`; picker `"⚡ **Priority Processing**\n\nCurrent mode: \`{mode}\`\n\nPick an option:"` with choices `"fast — Priority Processing on"` and `"normal — standard processing"`.
- **Config / env:** `agent.service_tier`.
- **Edge cases / guards:** An unknown value logs `"Unknown service_tier '<x>', ignoring"` and returns `None`.
- **Rebuild notes:** Normalize a small synonym set, warn on the rest.

### Prefill messages  `id: gw-core.prefill-messages`
- **Surface:** Config | Env
- **Where:** `HERMES_PREFILL_MESSAGES_FILE` env, or top-level `prefill_messages_file:` in `config.yaml` (legacy `agent.prefill_messages_file`).
- **What it does:** Injects a fixed set of ephemeral messages at the head of every gateway conversation.
- **How it works:** `_load_prefill_messages()` (`gateway/run.py:9982`). Relative paths resolve from `~/.hermes/`; the file must contain a JSON **array**.
- **Inputs / options:** a JSON array of message dicts.
- **Outputs / side effects:** prepended ephemeral context.
- **Config / env:** as above.
- **Edge cases / guards:** Missing file logs `"Prefill messages file not found: <path>"`; a non-array logs `"Prefill messages file must contain a JSON array: <path>"`; a parse error logs `"Failed to load prefill messages from <path>: <err>"`. All return `[]`.
- **Rebuild notes:** Env first, config second, relative-to-home resolution.

### Ephemeral system prompt  `id: gw-core.ephemeral-system-prompt`
- **Surface:** Config | Env
- **Where:** `HERMES_EPHEMERAL_SYSTEM_PROMPT` env, or `display.personality` / `agent.system_prompt` in `config.yaml`.
- **What it does:** Adds a per-turn system prompt that is never persisted to history.
- **How it works:** `_load_ephemeral_system_prompt()` (`gateway/run.py:10016`) delegating to `hermes_cli.config.resolve_ephemeral_system_prompt_from_config(cfg)`. Change detection for cache purposes via `_ephemeral_change_key(context, redact_pii)` (`:28928`); pinned session context via `_pinned_session_context_prompt(...)` (`:28902`).
- **Inputs / options:** any string.
- **Outputs / side effects:** injected per turn.
- **Config / env:** as above.
- **Edge cases / guards:** Env wins over config.
- **Rebuild notes:** Ephemeral means "not in the transcript" — key the agent cache on it so a change rebuilds the prompt.

### Agent history construction  `id: gw-core.agent-history`
- **Surface:** Core
- **Where:** invisible; what the model actually sees.
- **What it does:** Builds the message list for the turn from the persisted transcript plus the current message and its context.
- **How it works:** `_build_gateway_agent_history(...)` (`gateway/run.py:1811`), `_select_cached_agent_history(...)` (`:1916`), `_build_replay_entry(...)` (`:1659`), `_wrap_current_message_with_observed_context(message, observed_context)` (`:1950`), `_last_transcript_timestamp(history)` (`:1976`), `_preserve_queued_followup_history_offset(...)` (`:4552`), `_refresh_agent_cache_message_count(...)` (`:28781`), sidecar notes `_set_pending_turn_sidecar_notes(key, notes)` (`:28856`) / `_consume_pending_turn_sidecar_notes(key)` (`:28862`), and `_uses_telegram_observed_group_context(channel_prompt)` (`:1730`).
- **Inputs / options:** n/a
- **Outputs / side effects:** the model-facing history.
- **Config / env:** `gateway.message_timestamps.enabled`.
- **Edge cases / guards:** Auto-continue noise is stripped; message timestamps are rendered exactly once.
- **Rebuild notes:** Keep the persisted transcript clean; render presentation concerns at build time.

### Egress proxy mode  `id: gw-core.egress-proxy`
- **Surface:** Config | Env | Gateway/Telegram
- **Where:** `GATEWAY_PROXY_URL` env (convenient for Docker) or `gateway.proxy_url:` in `config.yaml`; inspected in chat with `/egress`.
- **What it does:** Routes agent runs through an external proxy endpoint instead of running them in-process.
- **How it works:** `_get_proxy_url()` (`gateway/run.py:29563`) — env first, then config; trailing `/` stripped. When set, turns go through `_run_agent_via_proxy(...)` (`:29659`) instead of `_run_agent(...)` (`:29944`) / `_run_agent_inner(...)` (`:30120`). `/egress` replies with `hermes_cli.proxy_cli.format_status_text()` (works mid-run too).
- **Inputs / options:** URL string.
- **Outputs / side effects:** all model traffic leaves via the proxy.
- **Config / env:** `GATEWAY_PROXY_URL`, `gateway.proxy_url`.
- **Edge cases / guards:** n/a
- **Rebuild notes:** Same shape as `gateway.relay_url` — configuration, not a feature flag.

### Session context prompt & session store  `id: gw-core.session-store`
- **Surface:** Core
- **Where:** invisible; the "you are talking to X on Telegram in group Y" block in the system prompt.
- **What it does:** Persists conversations and tells the agent where each message came from.
- **How it works:** `gateway/session.py` exports `SessionContext`, `SessionStore`, `SessionResetPolicy`, `build_session_context_prompt`, `build_session_key`. `SessionStore(sessions_dir, config, has_active_processes_fn=None)` uses SQLite (`SessionDB` on `state.db`) for session metadata and message transcripts, falling back to legacy JSONL files when SQLite is unavailable; a fallback-only initial load is reconciled with `state.db` after the handle recovers, before a whole-index save can replace DB rows. `AsyncSessionStore` (`gateway/session.py:1220`) is the async boundary: `__getattr__` wraps every callable in `asyncio.to_thread` so the loop never blocks on the synchronous, thread-safe store. `_DB_UNPINNED` is a sentinel distinguishing "resolve from the active profile scope" from a deliberate `store._db = None` (which selects the JSONL fallback).
- **Inputs / options:** n/a
- **Outputs / side effects:** `state.db` rows, `sessions.json` mirror, JSONL fallback files.
- **Config / env:** `sessions_dir`, `write_sessions_json`, `session_store_max_age_days`.
- **Edge cases / guards:** `_SessionFlight` (`gateway/session.py:1214`) de-duplicates concurrent creation of the same session.
- **Rebuild notes:** Sync store + async wrapper; one key builder; a durable DB with a legacy mirror.

### Session environment binding  `id: gw-core.session-env`
- **Surface:** Core
- **Where:** invisible; what subprocesses and tools see.
- **What it does:** Binds the turn's session identity for the duration of the run and unbinds it afterwards.
- **How it works:** `_set_session_env(context)` (`gateway/run.py:26442`) returns tokens; `_clear_session_env(tokens)` (`:26481`). Executor work runs through `_run_in_executor_with_context(func, *args)` (`:26486`) using `_get_executor()` (`:26497`) and `_shutdown_executor()` (`:26516`) so the ContextVars propagate into worker threads.
- **Inputs / options:** n/a
- **Outputs / side effects:** ContextVars + the `os.environ` compatibility bridge for `HERMES_SESSION_ID`.
- **Config / env:** n/a
- **Edge cases / guards:** Tokens are always cleared, including on exception.
- **Rebuild notes:** Bind/unbind with tokens; propagate the context into every executor.

### Windows venv import bootstrap  `id: gw-core.windows-venv-imports`
- **Surface:** Core
- **Where:** Windows gateways.
- **What it does:** Ensures the venv's site-packages are importable in the gateway process on Windows.
- **How it works:** `_ensure_windows_gateway_venv_imports()` (`gateway/run.py:646`).
- **Inputs / options:** n/a
- **Outputs / side effects:** `sys.path` mutation.
- **Config / env:** `VIRTUAL_ENV`.
- **Edge cases / guards:** No-op on other platforms.
- **Rebuild notes:** n/a

### SSL certificate bootstrap  `id: gw-core.ssl-certs`
- **Surface:** Core
- **Where:** invisible; startup.
- **What it does:** Points the process at a usable CA bundle so platform HTTPS calls work on installs with a broken default trust store.
- **How it works:** `_ensure_ssl_certs()` (`gateway/run.py:2220`).
- **Inputs / options:** n/a
- **Outputs / side effects:** `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` environment.
- **Config / env:** those two variables.
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### Transient network-error classification  `id: gw-core.transient-network-errors`
- **Surface:** Core
- **Where:** invisible; decides retryable vs. fatal adapter failures.
- **What it does:** Classifies an exception as a transient network problem so the reconnect watcher retries instead of giving up.
- **How it works:** `_is_transient_network_error(exc)` (`gateway/run.py:766`).
- **Inputs / options:** any exception.
- **Outputs / side effects:** drives `_queue_retryable_fatal_platform`.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Keep the retryable set explicit and small.

### Loop exception handler  `id: gw-core.loop-exception-handler`
- **Surface:** Core
- **Where:** the gateway log.
- **What it does:** Catches otherwise-unhandled asyncio exceptions so a task crash is diagnosable.
- **How it works:** `_gateway_loop_exception_handler(loop, context)` (`gateway/run.py:810`), installed on the gateway loop.
- **Inputs / options:** n/a
- **Outputs / side effects:** structured log records.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Always install a loop exception handler in a long-lived asyncio process.

### Gateway package public API  `id: gw-core.package-api`
- **Surface:** Core
- **Where:** `from gateway import …`.
- **What it does:** Re-exports the gateway's stable surface for other modules.
- **How it works:** `gateway/__init__.py` `__all__` = `GatewayConfig`, `PlatformConfig`, `HomeChannel`, `load_gateway_config`, `SessionContext`, `SessionStore`, `SessionResetPolicy`, `build_session_context_prompt`, `DeliveryRouter`, `DeliveryTarget`.
- **Inputs / options:** n/a
- **Outputs / side effects:** n/a
- **Config / env:** n/a
- **Edge cases / guards:** The module docstring states the gateway's four responsibilities: session management (persistent conversations with reset policies), dynamic context injection (the agent knows where messages come from), delivery routing (cron job outputs to appropriate channels), and platform-specific toolsets.
- **Rebuild notes:** A small, stable façade over a large package.

### Built-in gateway hooks package  `id: gw-core.builtin-hooks`
- **Surface:** Core
- **Where:** `gateway/builtin_hooks/`.
- **What it does:** Placeholder package for hooks that are always registered by the gateway (currently an empty `__init__.py` documented as `"""Built-in gateway hooks that are always registered."""`).
- **How it works:** `gateway/builtin_hooks/__init__.py`.
- **Inputs / options:** n/a
- **Outputs / side effects:** none in v2026.8.31.
- **Config / env:** n/a
- **Edge cases / guards:** Ships empty — a reimplementation should not assume behaviour here.
- **Rebuild notes:** Reserved extension point.

### Gateway assets  `id: gw-core.assets`
- **Surface:** Core
- **Where:** `gateway/assets/`.
- **What it does:** Ships the two non-code resources the gateway sends or reads.
- **How it works:** `gateway/assets/status_phrases.yaml` — the built-in status-phrase catalog (see `gw-core.status-phrases`); `gateway/assets/telegram-botfather-threads-settings.jpg` — the screenshot sent by `_send_telegram_topic_setup_image` when enabling Telegram topic mode.
- **Inputs / options:** n/a
- **Outputs / side effects:** the image is uploaded to the chat.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** Ship setup screenshots with the code that references them.

---

## 11. Documentation surfaces owned by this shard

### Messaging Gateway overview page  `id: gw-core.docs-messaging-index`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/index.md` — sidebar title **"Messaging Gateway"**.
- **What it does:** The user-facing map of the gateway: platform comparison table, architecture diagram, silence tokens, setup and service commands, chat commands, session management, reset policies, channel overrides, security, redirecting the agent, clarify questions, tool-progress notifications, background sessions, service management, platform toolsets, and multi-platform day-2 operations.
- **How it works:** Docusaurus page, `sidebar_position: 1`.
- **Inputs / options — the Platform Comparison table columns:** Voice (TTS audio replies and/or voice message transcription), Images (send/receive), Files (attachments), Threads (threaded conversations), Reactions (emoji reactions), Typing (indicator while processing), Streaming (progressive message updates via editing). Rows: Telegram, Discord, Slack, Google Chat, WhatsApp, WhatsApp Cloud API, Signal, SMS, Email, Home Assistant, Mattermost, Matrix, DingTalk, Feishu/Lark, WeCom, WeCom Callback, Weixin, BlueBubbles, Photon (iMessage), QQ, Yuanbao, Microsoft Teams, LINE, ntfy, Raft, IRC, Buzz, SimpleX.
- **Outputs / side effects — platform toolset table (verbatim):** CLI `hermes-cli`; Telegram `hermes-telegram`; Discord `hermes-discord`; WhatsApp `hermes-whatsapp`; WhatsApp Cloud API `hermes-whatsapp` (shares the toolset with the Baileys bridge); Slack `hermes-slack`; Google Chat `hermes-google_chat`; Signal `hermes-signal`; SMS `hermes-sms`; Email `hermes-email`; Home Assistant `hermes-homeassistant` (adds `ha_list_entities`, `ha_get_state`, `ha_call_service`, `ha_list_services`); Mattermost `hermes-mattermost`; Matrix `hermes-matrix`; DingTalk `hermes-dingtalk`; Feishu/Lark `hermes-feishu`; WeCom `hermes-wecom`; WeCom Callback `hermes-wecom-callback`; Weixin `hermes-weixin`; BlueBubbles `hermes-bluebubbles`; QQBot `hermes-qqbot`; Yuanbao `hermes-yuanbao`; Microsoft Teams `hermes-teams`; API Server `hermes-api-server` (drops `clarify` and `text_to_speech` — programmatic access has no interactive user); Webhooks `hermes-webhook`; Raft `hermes-raft` (wake-only channel; the agent uses the Raft CLI for message I/O).
- **Config / env:** documents `session_reset`, `channel_overrides`, allowlist env vars, `display.*`, `gateway.systemd_watchdog_seconds`, `gateway.delivery_ledger`, `gateway.message_timestamps.enabled`.
- **Edge cases / guards:** Contains the `:::danger` note against adding an `ExecStopPost` kill drop-in, the headless-VM linger tip, and the "avoid keeping both user and system units installed" warning.
- **Rebuild notes:** Keep the capability matrix generated from the adapters, not hand-maintained.

### Bot Mode documentation  `id: gw-core.docs-bot-mode`
- **Surface:** Docs | Desktop app
- **Where:** `website/docs/user-guide/bot-mode.md` — title **"Bot Mode"**.
- **What it does:** Documents turning Hermes profiles into a roster of named Bots with their own role, model, memory, skills and avatar; group rooms; bot-to-bot messaging; and cross-machine reachability.
- **How it works — the parts this shard owns:** `agent.bot_mode_protocol` in `config.yaml` (default **on**) injects the bot-to-bot messaging protocol into the **canonical Bot Chat** session at prompt-build time — only there, never into regular sessions, group-room member sessions, CLI sessions, or SOUL.md. The `message_agent(target=…, message=…)` tool exists **only** in canonical Bot Chat sessions on Bot-Mode-managed installs; it validates the target against the live roster, auto-prefixes `"Message from 🤖 <sender> (@<sender>):"`, and delivers fire-and-forget (the sender gets an acknowledgement and the reply arrives later as a background completion notification). The message travels as a real parameter — nothing is shell-interpreted, so quotes, `$(...)` and backticks arrive verbatim.
- **Inputs / options:** `message_agent(target="researcher", message="…")`; disambiguation `target="moxie@<connection>"`; peer targets `target="spark/researcher"` or `target="spark"`.
- **Outputs / side effects — typed failure reasons** carried end-to-end and tagged onto the sender's completion notification as `[reason: <code>]`: `provider_auth_or_access`, `provider_quota_limit`, `provider_rate_limit`, `provider_server_error`, `context_overflow`, `missing_config`, `model_unavailable`, `runtime_offline`, `queued_expired`, `delivery_timeout`, `target_busy`, `unknown`.
- **Config / env:** `agent.bot_mode_protocol: true`.
- **Edge cases / guards:** A failed delivery turn is retried **at most once**, and only when a retry can help: transient failures (target runtime offline, delivery timeout, provider rate limit or server error) re-run the same Bot Chat session unchanged; a `context_overflow` failure re-runs the same session after the standard context-compression pass; auth, quota and configuration failures **never** auto-retry. A retried turn never starts a fresh session. Delivery is per-invocation — the receiving Bot picks the message up when it next runs; live interrupt of a Bot mid-conversation is future work.
- **Rebuild notes:** Machine-readable failure codes let a calling agent branch ("sign in again" vs "retry later") instead of parsing provider prose.

### `hermes peer` — gateway-to-gateway messaging  `id: gw-core.peer`
- **Surface:** CLI | Config | Env
- **Where:** `hermes peer add|list|dm|run|status|stop`; config `bot_peers` in `config.yaml`; credentials `HERMES_PEER_<NAME>_KEY` in `~/.hermes/.env`.
- **What it does:** Lets bots on one machine message bots on another machine's gateway with no desktop in the loop.
- **How it works:** Documented in `website/docs/user-guide/bot-mode.md`. `hermes peer dm` delivers into the remote agent's canonical Bot Chat over the peer's existing API server, runs one agent turn there, and prints the reply on stdout — the cross-machine twin of `hermes -p <bot> chat`.
- **Inputs / options:** `hermes peer add <name> --url <http://host:port> --key <API_SERVER_KEY>`; `hermes peer list`; `hermes peer dm <name> < file` and `hermes peer dm <name>/<profile> < file` (body from a file so nothing is shell-interpreted); `hermes peer run <name> --idempotency-key <key> < file`; `hermes peer status <name> <run_id>`; `hermes peer stop <name> <run_id>`.
- **Outputs / side effects:** Once a peer is registered, the Bot Chat protocol automatically includes the peer roster and `message_agent` accepts peer targets; registering or removing a peer refreshes each Bot Chat's protocol on its next message (capability epoch).
- **Config / env:** requires the peer machine to run the `api_server` gateway platform with a strong `API_SERVER_KEY`; reachability is the operator's network problem (LAN, Tailscale, VPN).
- **Edge cases / guards:** Use `peer dm` only for short queries — it holds one HTTP connection until the turn finishes; use `peer run` for long turns (returns a `run_id` immediately, poll with `peer status`, inherit the canonical Bot Chat transcript, and a stable `--idempotency-key` makes a retry return the original run instead of duplicating work). Cross-gateway links are **direct gateway-to-gateway** connections — a gateway behind home NAT can dial out to a public peer (laptop → VPS) but the reverse has no inbound route (VPS → home fails) unless the network provides one.
- **Rebuild notes:** Two verbs (synchronous short / asynchronous long) plus idempotency keys.

### Running many gateways at once  `id: gw-core.docs-multi-profile`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/multi-profile-gateways.md` — title **"Running Many Gateways at Once"**, `sidebar_position: 4`.
- **What it does:** Documents operating multiple profiles as managed services on one machine: the one-process-per-profile default, the opt-in multiplexer, log viewing, keeping the host awake, token-conflict safety, and troubleshooting.
- **How it works:** Documents the config surface covered by `gw-core.cfg-multiplex-profiles`, `gw-core.cfg-multiplex-allowlist`, `gw-core.cfg-profile-routes`, and `gw-core.port-binding-platforms`.
- **Inputs / options — service files:** macOS `~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist`; Linux `~/.config/systemd/user/hermes-gateway-<profile>.service`; the default profile keeps `ai.hermes.gateway.plist` / `hermes-gateway.service`. Per-profile commands: `<profile> gateway run|start|stop|restart|status|install|uninstall` (equivalent to `hermes -p <profile> gateway <action>`). Logs: `~/.hermes/logs/gateway.log`, `gateway.error.log`; named profile `~/.hermes/profiles/<name>/logs/…`; `hermes logs -f`, `hermes -p <name> logs -f`. Identification: `hermes profile list`, `launchctl list | grep hermes`, `systemctl --user list-units 'hermes-gateway-*'`. Keeping awake: macOS `caffeinate` flags `-d` (block display sleep), `-i` (block idle system sleep, default), `-m` (block disk sleep), `-s` (block system sleep, AC-powered Macs only), `-u` (simulate user activity), `-t N` (auto-exit after N seconds), `-w P` (exit when PID P exits); Linux `systemd-inhibit --what=idle:sleep` and `sudo loginctl enable-linger "$USER"`. Health: `hermes doctor`, `hermes -p <profile> doctor`.
- **Outputs / side effects:** Error text for a secondary profile started under a multiplexer: `"The default gateway is running as a profile multiplexer and already serves profile 'coder'. …"` — pass `--force` only to deliberately run a separate process. Port-binding warning: `"Skipping secondary profile 'coder' due to port-binding config error: Profile 'coder' enables port-binding platform(s) webhook, but gateway.multiplex_profiles is on. … Remove these platform entries from profile 'coder's config.yaml or configure them only on the default profile."`
- **Config / env:** `gateway.multiplex_profiles`, `gateway.multiplex_profile_allowlist`, `gateway.profile_routes`.
- **Edge cases / guards:** `/p/<profile>/` prefix authentication follows the profile named in the URL: `/p/coder/...` API requests must use `API_SERVER_KEY` from `~/.hermes/profiles/coder/.env` (the default listener key is rejected); a webhook route targeting `coder` must declare `profile: coder` beside its route-specific `secret` in the **default** profile's `config.yaml`, and that secret is accepted only at `/p/coder/webhooks/<route>`; routes without `profile` remain default-profile routes and are unreachable through a named prefix; named API requests fail closed when the target profile has no `API_SERVER_KEY`; an unknown or unconfigured profile in the prefix returns `404`. macOS `caffeinate` cannot override lid-close sleep. The `"Could not find service in domain for user gui: 501"` error after `stop` → `start` is caught by the CLI, which automatically reloads the plist (`↻ launchd job was unloaded; reloading service definition`).
- **Rebuild notes:** One process per tenant by default; multiplexing as an explicit, reversible opt-in with a single shared listener.

---

## Handoffs

- `gateway/platforms/**` and `plugins/platforms/**` — every individual platform adapter (Telegram, Discord, Slack, WhatsApp/Cloud, Signal, SMS, Email, Home Assistant, Mattermost, Matrix, DingTalk, Feishu, WeCom, WeCom Callback, Weixin, BlueBubbles, Photon, QQ, Yuanbao, Teams, LINE, ntfy, Raft, IRC, Buzz, SimpleX, Google Chat, A2A, webhook, msgraph_webhook, api_server) and their per-platform config keys → platform shard.
- `gateway/slash_commands.py` (6 466 lines, 57 `_handle_*_command` handlers) — the individual slash-command behaviours and their full argument grammars → slash-command shard.
- `website/docs/reference/slash-commands.md` and `hermes_inv/slash_commands.json` → slash-command shard.
- `gateway/hosted_rooms.py`, `hosted_room_discussion.py`, `hosted_room_driver.py`, `hosted_room_execution_policy.py`, `hosted_room_links.py`, `hosted_room_peer.py`, `hosted_room_policy_checkpoint.py`, `hosted_room_replicas.py` → hosted-rooms / automation shard.
- `gateway/platforms/api_server*.py` — the 40 literal `/v1/...` paths (runs, chat completions, hosted rooms, artifacts, browser-control) → automation/API shard.
- Kanban board features themselves (boards, cards, dispatcher policy) — only the gateway-side watcher loops are covered here → automation shard.
- `hermes gateway setup|install|uninstall|start|stop|status|list` CLI flag surfaces → CLI shard.
- `hermes pairing approve|list|revoke` CLI flag surfaces → CLI shard.
- `hermes peer add|list|dm|run|status|stop` CLI flag surfaces → CLI shard (behaviour summarised here from bot-mode.md).
- Bot Mode desktop UI (Bots pane, Routines tile, avatars/blob faces, group rooms, Create-on picker, Settings → Plugins → Bots) → desktop shard.
- `agent/` internals: `AIAgent`, `agent.redact`, `agent.onboarding`, `agent.display`, `agent.i18n`, `agent.image_routing`, `agent.skill_commands`, `agent.skill_bundles`, `agent.estop`, `tools.clarify_gateway`, `tools.approval`, `tools.slash_confirm`, `tools.delegate_tool`, `tools.process_registry` → core/agent and tools shards.
- `display.*` keys that are CLI-only (compact, personality, skin, streaming at the global level) → CLI/config shard.
- Voice-mode feature docs (`/user-guide/features/voice-mode`, `/guides/use-voice-mode-with-hermes`) → features shard.
