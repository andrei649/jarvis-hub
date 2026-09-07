# Platform adapters A — Discord, Slack, WhatsApp, Matrix, Mattermost, Microsoft Teams, Google Chat, Email

This shard is the exhaustive inventory of eight Hermes Agent gateway platform adapters shipped as plugins under
`plugins/platforms/{discord,slack,whatsapp,matrix,mattermost,teams,google_chat,email}` plus the standalone
`plugins/teams_pipeline` (Microsoft Teams meeting pipeline) and the two agent-facing Discord toolsets
(`discord`, `discord_admin`). For each platform it documents: the plugin manifest, the interactive setup wizard,
every credential and env var, every config key, mention/authorization gating, threads, reactions, slash/app
commands, buttons/modals/cards, voice, media and file handling, streaming/edit behaviour, admin surfaces,
limits, and every user-visible string emitted by the adapter.
Deliberately left to sibling shards: Telegram and the other platform adapters (`telegram`, `signal`, `irc`,
`line`, `sms`, `wecom`, `feishu`, `dingtalk`, `simplex`, `ntfy`, `a2a`, `raft`, `photon`, `buzz`, `qqbot`,
`weixin`, `yuanbao`, `bluebubbles`, `whatsapp_cloud`, `api_server`, `webhook`, `msgraph_webhook`,
`homeassistant`, `open-webui`, `relay`) → `platforms-b`; the gateway core, session model, slash-command
dispatcher and `hermes gateway` CLI → `gw-core` / `gw-slash` / `cli-*`; the shared `BasePlatformAdapter`
contract → `gw-core`.

---

## 1. Discord

### Discord platform adapter  `id: platforms-a.discord`
- **Surface:** Platform:discord
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Discord"** (emoji 🎮); runs inside `hermes gateway`. In Discord itself: DMs with the bot, guild text channels, threads, forum channels and voice channels.
- **What it does:** Connects Hermes to Discord as a bot over the discord.py Gateway WebSocket + REST, relaying guild/DM messages into the Hermes agent pipeline and posting replies back. Adds native slash commands, button-based approvals, auto-threading, reactions, voice-channel presence and native file uploads.
- **How it works:** `plugins/platforms/discord/adapter.py:1034` defines `DiscordAdapter(BasePlatformAdapter)`. `register(ctx)` at `plugins/platforms/discord/adapter.py:10594` calls `ctx.register_platform(name="discord", label="Discord", adapter_factory=_build_adapter, check_fn=discord_deps_present, ensure_deps_fn=check_discord_requirements, is_connected=_is_connected, required_env=["DISCORD_BOT_TOKEN"], install_hint="Run `hermes setup` to install Discord support.", setup_fn=interactive_setup, apply_yaml_config_fn=_apply_yaml_config, allowed_users_env="DISCORD_ALLOWED_USERS", allow_all_env="DISCORD_ALLOW_ALL_USERS", cron_deliver_env_var="DISCORD_HOME_CHANNEL", standalone_sender_fn=_standalone_send, max_message_length=2000, emoji="🎮", allow_update_command=True)`. Manifest: `plugins/platforms/discord/plugin.yaml:1` (`name: discord-platform`, `label: Discord`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). `connect()` at `:1274` logs in with `DISCORD_BOT_TOKEN`, requests the **Message Content Intent** always and the **Server Members Intent** when the allowlist contains usernames or `DISCORD_ALLOWED_ROLES` is set (`_needs_server_members_intent` at `:276`). Inbound messages land in `_handle_message()` at `:8097` via `_dispatch_discord_message` at `:1633`; admission is decided by `_discord_message_admission` at `:1559`. Class constants at `:1049`: `MAX_MESSAGE_LENGTH = 2000`, `_SPLIT_THRESHOLD = 1900`, `MAX_SPLIT_MESSAGES = 8`, `supports_code_blocks = True`, `splits_long_messages = True`, `VOICE_TIMEOUT = 300`, `PLAYBACK_TIMEOUT = 120`, `PLAYBACK_TIMEOUT_PADDING = 30`. State on disk: `~/.hermes/gateway/discord_command_sync_state.json`, `~/.hermes/gateway/discord_nonconversational_messages.json`, `~/.hermes/gateway/discord_message_recovery.db`, media cache `~/.hermes/cache/documents/`.
- **Inputs / options:** Env: `DISCORD_BOT_TOKEN` (required), `DISCORD_ALLOWED_USERS`, `DISCORD_ALLOWED_ROLES`, `DISCORD_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`, `DISCORD_HOME_CHANNEL`, `DISCORD_HOME_CHANNEL_NAME`, `DISCORD_COMMAND_SYNC_POLICY`, `DISCORD_REQUIRE_MENTION`, `DISCORD_THREAD_REQUIRE_MENTION`, `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_IGNORE_NO_MENTION`, `DISCORD_AUTO_THREAD`, `DISCORD_ALLOW_BOTS`, `DISCORD_REACTIONS`, `DISCORD_IGNORED_CHANNELS`, `DISCORD_ALLOWED_CHANNELS`, `DISCORD_NO_THREAD_CHANNELS`, `DISCORD_HISTORY_BACKFILL`, `DISCORD_HISTORY_BACKFILL_LIMIT`, `DISCORD_REPLY_TO_MODE`, `DISCORD_ALLOW_MENTION_EVERYONE`, `DISCORD_ALLOW_MENTION_ROLES`, `DISCORD_ALLOW_MENTION_USERS`, `DISCORD_ALLOW_MENTION_REPLIED_USER`, `DISCORD_PROXY`, `DISCORD_ALLOW_ANY_ATTACHMENT`, `DISCORD_MAX_ATTACHMENT_BYTES`, `DISCORD_APPROVAL_MENTIONS`, `DISCORD_HIDE_SLASH_COMMANDS`, `HERMES_DISCORD_TEXT_BATCH_DELAY_SECONDS`, `HERMES_DISCORD_TEXT_BATCH_SPLIT_DELAY_SECONDS`. Config: the whole `discord:` block in `~/.hermes/config.yaml` (enumerated in the per-feature entries below).
- **Outputs / side effects:** Bot appears online in Discord; posts messages/embeds/files/threads; writes the state files listed above; registers up to 100 global application commands.
- **Config / env:** `discord.*` (26 leaf keys in `config_defaults.json`), `display.platforms.discord.streaming`, `display.platforms.discord.reasoning_style`, `group_sessions_per_user`, `gateway.platforms.discord.extra.*`.
- **Edge cases / guards:** Fails **closed** — with no `DISCORD_ALLOWED_USERS`, no `DISCORD_ALLOWED_ROLES`, no `DISCORD_ALLOWED_CHANNELS` and no allow-all flag, every inbound message is denied and the gateway log emits `No Discord access policy configured; inbound Discord messages will be denied by default.` (`_warn_if_fail_closed_default` at `:5123`). `PrivilegedIntentsRequired` on connect produces the guidance text built by `_format_privileged_intents_guidance` at `:292`. Bot-to-bot topologies are explicitly unsupported (`DISCORD_ALLOW_BOTS` default `"none"`). Split replies are capped at 8 messages.
- **Rebuild notes:** Minimal spec: discord.py `commands.Bot` with `intents.message_content=True`; on `on_message`, run allow/deny gates → mention gate → session key → agent → chunked `channel.send()` at 2000 chars. A better version would make the intent requirement self-diagnosing at setup time by calling `GET /applications/@me` and refusing to save a token whose application lacks Message Content, and would replace the 100-command global registration with per-guild lazily-synced commands.

### Discord interactive setup wizard  `id: platforms-a.discord-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Discord**; also reachable as the platform plugin's `setup_fn`.
- **What it does:** Walks the operator through creating the bot, pasting the token, setting an allowlist, and optionally choosing a home channel.
- **How it works:** `interactive_setup()` at `plugins/platforms/discord/adapter.py:10301`. Uses `hermes_cli.cli_output.{print_header,print_info,print_success,prompt,prompt_yes_no}` and `hermes_cli.config.{get_env_value,save_env_value,remove_env_value}`. If `DISCORD_BOT_TOKEN` already exists it prints `Discord: already configured` and asks `Reconfigure Discord?` (default No); declining still offers to add an allowlist when none is set. User IDs are normalised by `_clean_discord_user_ids()` at `:10287` (which calls `_clean_discord_id` at `:403` to strip `<@…>` wrappers).
- **Inputs / options:** Verbatim prompts and info lines, in order:
  - header `Discord`
  - `Discord: already configured`
  - `Reconfigure Discord?` (yes/no, default `False`)
  - `⚠️  Discord has no user allowlist. With the fail-closed default, messages are denied unless you configure allowed users, roles, or channels, or set DISCORD_ALLOW_ALL_USERS=true.`
  - `Add allowed users now?` (yes/no, default `True`)
  - `   To find Discord ID: Enable Developer Mode, right-click name → Copy ID`
  - `Allowed user IDs (comma-separated)`
  - `Discord allowlist configured`
  - `Create a bot at https://discord.com/developers/applications`
  - `On Bot → Privileged Gateway Intents, enable:`
  - `  - Message Content Intent (required — without it Discord rejects the connection)`
  - `  - Server Members Intent (required if you use usernames or role allowlists)`
  - `Save Changes in the Developer Portal before starting the gateway.`
  - `Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/discord`
  - `Discord bot token` (password prompt)
  - `Discord token saved`
  - `🔒 Security: Restrict who can use your bot`
  - `   To find your Discord user ID:`
  - `   1. Enable Developer Mode in Discord settings`
  - `   2. Right-click your name → Copy ID`
  - `   You can also use Discord usernames (resolved on gateway start).`
  - `Allowed user IDs or usernames (comma-separated, leave empty for open access)`
  - `⚠️  No allowlist set. Discord will deny messages until you set DISCORD_ALLOWED_USERS, DISCORD_ALLOWED_ROLES, DISCORD_ALLOWED_CHANNELS, or DISCORD_ALLOW_ALL_USERS=true for open access.`
  - `📬 Home Channel: where Hermes delivers cron job results,`
  - `   cross-platform messages, and notifications.`
  - `   To get a channel ID: right-click a channel → Copy Channel ID`
  - `   (requires Developer Mode in Discord settings)`
  - `   You can also set this later by typing /set-home in a Discord channel.`
  - `Home channel ID (leave empty to set later with /set-home)`
  - `Home channel cleared.`
- **Outputs / side effects:** Writes `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL` into `~/.hermes/.env`; removes `DISCORD_HOME_CHANNEL` when the answer is blank.
- **Config / env:** Writes only `.env` keys; no config.yaml changes.
- **Edge cases / guards:** Empty token aborts without writing anything. Usernames (non-numeric) are accepted and resolved at gateway start by `_resolve_allowed_usernames()` at `:5691`.
- **Rebuild notes:** A guided credential wizard that writes dotenv keys and validates IDs. A better version would fetch `GET /users/@me` with the entered token to confirm it works and print the bot's name, and would generate the OAuth2 invite URL (with the correct permission integer) for the operator to click.

### Discord manifest credentials (`requires_env` / `optional_env`)  `id: platforms-a.discord-manifest-env`
- **Surface:** Config
- **Where:** `hermes config` UI → Discord platform env-var section (injected by the platform-plugin env-var injector in `hermes_cli/config.py`).
- **What it does:** Declares the credentials and optional env vars the Discord plugin advertises so the config UI can prompt for them with descriptions and links.
- **How it works:** `plugins/platforms/discord/plugin.yaml:12-34`.
- **Inputs / options:** `requires_env`: `DISCORD_BOT_TOKEN` — description `"Discord bot token"`, prompt `"Discord bot token"`, url `https://discord.com/developers/applications`, `password: true`. `optional_env`: `DISCORD_ALLOWED_USERS` (`"Comma-separated Discord user IDs allowed to talk to the bot"` / prompt `"Allowed users (comma-separated)"`), `DISCORD_ALLOW_ALL_USERS` (`"Allow any Discord user to trigger the bot (dev only)"` / prompt `"Allow all users? (true/false)"`), `DISCORD_HOME_CHANNEL` (`"Default channel ID for cron / notification delivery"` / prompt `"Home channel ID"`), `DISCORD_HOME_CHANNEL_NAME` (`"Display name for the Discord home channel"` / prompt `"Home channel display name"`).
- **Outputs / side effects:** Values written to `~/.hermes/.env`.
- **Config / env:** As listed.
- **Edge cases / guards:** `password: true` masks the token field.
- **Rebuild notes:** A YAML manifest schema of `{name, description, prompt, url, password}` per var. Better: add `validate` regex and a `test` callback per var.

### Discord mention gating (require_mention / free-response / ignored / allowed channels)  `id: platforms-a.discord-mention-gating`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord:` block; equivalent `DISCORD_*` env vars. User-visible effect: whether the bot answers without an `@mention`.
- **What it does:** Decides, per message, whether Hermes should respond at all in a guild channel or thread.
- **How it works:** Precedence implemented in `_handle_message()` (`plugins/platforms/discord/adapter.py:8097`) with helpers `_get_allowed_channels()` `:6671`, `_get_ignored_channels()` `:6675`, `_get_no_thread_channels()` `:6679`, `_discord_free_response_channels()` `:6738`, `_discord_require_mention()` `:6560`, `_discord_thread_require_mention()` `:6867`, `_self_is_explicitly_mentioned()` `:6772`, `_raw_mentioned_user_ids()` `:6761`, `_discord_channel_keys()` `:6823`. Order: ignored channels (silent, highest priority) → allowed-channel whitelist → free-response → thread shortcut → `require_mention`. `DISCORD_IGNORE_NO_MENTION` (config `slack.ignore_other_user_mentions`'s Discord twin) keeps the bot silent when a message mentions other users but not the bot. Threads inherit their parent channel's classification.
- **Inputs / options:** `discord.require_mention` (bool, default `true`), `discord.thread_require_mention` (bool, default `false`), `discord.free_response_channels` (comma string **or** YAML list, default `""`), `discord.allowed_channels` (default `""`), `discord.ignored_channels` (list, default `[]`), `discord.no_thread_channels` (list, default `[]`), `discord.bots_require_inline_mention` (bool, default `false`, `:6797`), env `DISCORD_REQUIRE_MENTION`, `DISCORD_THREAD_REQUIRE_MENTION`, `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_IGNORE_NO_MENTION` (default `true`), `DISCORD_IGNORED_CHANNELS`, `DISCORD_ALLOWED_CHANNELS`, `DISCORD_NO_THREAD_CHANNELS`, `DISCORD_ALLOW_BOTS` (`none` | `mentions` | `all`, default `none`, `_get_allow_bots()` `:6734`).
- **Outputs / side effects:** No response at all when gated out; free-response channels additionally skip auto-threading and history backfill.
- **Config / env:** As above. Env always wins over config.yaml (`_apply_yaml_config` at `:10387` only sets env vars that are not already set).
- **Edge cases / guards:** DMs always respond regardless of `require_mention`. A thread whose parent is in `ignored_channels` is also ignored. `DISCORD_ALLOW_BOTS` other than `"none"` is documented as an unsupported topology for bot↔bot chat because Discord auto-mentions the replied-to author, producing an ack loop with no circuit breaker.
- **Rebuild notes:** Implement as an ordered rule chain returning `(respond: bool, reason: str)` so the decision is loggable. A better version would expose the decision trace via a `/whyquiet` debug command instead of leaving operators to guess which of six settings silenced the bot.

### Discord auto-threading  `id: platforms-a.discord-auto-thread`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.auto_thread`; visible as a new Discord thread spawned off your `@mention`.
- **What it does:** Creates a fresh thread for every `@mention` in a regular text channel so each conversation gets its own isolated session.
- **How it works:** `_auto_create_thread()` at `plugins/platforms/discord/adapter.py:7257` calls `_create_thread()` at `:7162`; the thread title comes from `_derive_auto_thread_name()` at `:7237` (first line of the message, markdown heading prefix stripped, capped at 100 chars). Once a thread exists the bot answers every subsequent message in it without a mention, unless `thread_require_mention` is on.
- **Inputs / options:** `discord.auto_thread` (bool, default `true`), env `DISCORD_AUTO_THREAD`; bypassed for channels in `discord.free_response_channels` and `discord.no_thread_channels`, and for messages already inside threads or DMs.
- **Outputs / side effects:** A new Discord public thread; the reply is posted inside it. Thread name ≤ 100 chars.
- **Config / env:** `discord.auto_thread`, `discord.no_thread_channels`, `discord.free_response_channels`, `DISCORD_AUTO_THREAD`, `DISCORD_NO_THREAD_CHANNELS`.
- **Edge cases / guards:** Requires the **Send Messages in Threads** permission; forum channels always create threads regardless (see forum entry).
- **Rebuild notes:** `message.create_thread(name=..., auto_archive_duration=1440)` then reply into it. A better version would reuse an existing recent thread from the same author instead of spawning one per mention.

### `/thread` — create a thread and start a session in it  `id: platforms-a.discord-slash-thread`
- **Surface:** Platform:discord
- **Where:** Discord `/` menu → **`/thread`**, description **"Create a new thread and start a Hermes session in it"**.
- **What it does:** Creates a named thread on the current channel and optionally seeds it with a first message to Hermes.
- **How it works:** Registered at `plugins/platforms/discord/adapter.py:5997`; handler `_handle_thread_create_slash()` at `:6450`, which defers **after** the auth gate so rejected invokers still get an ephemeral rejection, then `_dispatch_thread_session()` at `:6501`.
- **Inputs / options:** `name` (string, required) — describe text **"Thread name"**; `message` (string, default `""`) — **"Optional first message to send to Hermes in the thread"**; `auto_archive_duration` (int, default `1440`) — **"Auto-archive in minutes (60, 1440, 4320, 10080)"**.
- **Outputs / side effects:** New Discord thread; a session bound to that thread; optional first agent turn.
- **Config / env:** Slash access control (`allow_admin_from` / `user_allowed_commands`) applies.
- **Edge cases / guards:** Auth checked before `defer()`. Invalid archive durations are rejected by Discord.
- **Rebuild notes:** Thin wrapper over the REST `POST /channels/{id}/threads`. Better: let the command accept `private: bool` and invite specific members.

### Discord native slash commands (built-in set)  `id: platforms-a.discord-slash-builtin`
- **Surface:** Platform:discord
- **Where:** Discord's `/` autocomplete menu, globally registered for the bot application.
- **What it does:** Exposes Hermes's gateway commands as first-class Discord Application Commands with typed options and choice dropdowns.
- **How it works:** `_register_slash_commands()` at `plugins/platforms/discord/adapter.py:5844`. Each handler forwards to `_run_simple_slash()` at `:5784`, which builds a `MessageEvent` via `_build_slash_event()` at `:6401` and dispatches it through the normal gateway slash pipeline. Native commands are registered first so they always survive the 100-command cap (`_DISCORD_MAX_APP_COMMANDS = 100` at `:85`; one slot is reserved for `/skill`, so `slot_cap = 99`).
- **Inputs / options:** Every explicitly-declared command, with its Discord description string verbatim and its options:
  1. **`/new`** — "Start a new conversation". No options. Ack text `New conversation started~`.
  2. **`/reset`** — "Reset your Hermes session". No options. Ack `Session reset~`.
  3. **`/model`** — "Show or change the model". Option `name` (string, optional): "Model name (e.g. anthropic/claude-sonnet-4). Leave empty to see current."
  4. **`/reasoning`** — "Show/change reasoning effort, or toggle showing it". Option `effort` (string, optional): "Pick a level, reset the override, or show/hide reasoning. Leave empty to see current." Choices (label → value): `none — disable reasoning`→`none`, `minimal`→`minimal`, `low`→`low`, `medium`→`medium`, `high`→`high`, `xhigh`→`xhigh`, `max`→`max`, `ultra — maximum reasoning`→`ultra`, `reset — clear this session's override`→`reset`, `show — reveal reasoning in replies`→`show`, `hide — hide reasoning from replies`→`hide`.
  5. **`/personality`** — "Set a personality". Option `name` (string, optional): "Personality name. Leave empty to list available."
  6. **`/retry`** — "Retry your last message". Ack `Retrying~`.
  7. **`/undo`** — "Remove the last exchange". No ack text.
  8. **`/status`** — "Show Hermes session status". Ack `Status sent~`.
  9. **`/sethome`** — "Set this chat as the home channel".
  10. **`/stop`** — "Stop the running Hermes agent". Ack `Stop requested~`.
  11. **`/steer`** — "Inject a message after the next tool call (no interrupt)". Option `prompt` (string, required): "Text to inject into the agent's next tool result".
  12. **`/plan`** — "Write a markdown implementation plan (no execution)". Option `task` (string, optional): "What to plan. Leave empty to infer from the conversation."
  13. **`/compress`** — "Compress conversation context".
  14. **`/title`** — "Set or show the session title". Option `name` (string, optional): "Session title. Leave empty to show current."
  15. **`/resume`** — "Resume a previously-named session". Option `name` (string, optional): "Session name to resume. Leave empty to list sessions."
  16. **`/usage`** — "Show token usage for this session".
  17. **`/help`** — "Show available commands".
  18. **`/insights`** — "Show usage insights and analytics". Option `days` (int, default `7`): "Number of days to analyze (default: 7)".
  19. **`/reload-mcp`** — "Reload MCP servers from config".
  20. **`/reload-skills`** — "Re-scan ~/.hermes/skills/ for new or removed skills".
  21. **`/voice`** — "Toggle voice reply mode". Option `mode` (string, optional): "Voice mode: join, channel, leave, on, tts, off, or status". Choices: `join — join your voice channel`→`join`, `channel — join your voice channel (alias)`→`channel`, `leave — leave voice channel`→`leave`, `on — voice reply to voice messages`→`on`, `tts — voice reply to all messages`→`tts`, `off — text only`→`off`, `status — show current mode`→`status`.
  22. **`/update`** — "Update Hermes Agent to the latest version". Ack `Update initiated~`.
  23. **`/restart`** — "Gracefully restart the Hermes gateway". Ack `Restart requested~`.
  24. **`/approve`** — "Approve a pending dangerous command". Option `scope` (string, optional): "Optional: 'all', 'session', 'always', 'all session', 'all always'".
  25. **`/deny`** — "Deny a pending dangerous command". Option `scope` (string, optional): "Optional: 'all' to deny all pending commands".
  26. **`/thread`** — see `platforms-a.discord-slash-thread`.
  27. **`/queue`** — "Queue a prompt for the next turn (doesn't interrupt)". Option `prompt` (string, required): "The prompt to queue". Ack `Queued for the next turn.`
  28. **`/bg`** — "Run a prompt in a separate background session". Option `prompt` (string, required): "The prompt to run in the background". Ack `Background task started~`.
  29. **`/btw`** — "Ask a side question about the current conversation". Option `question` (string, required): "The side question to answer without interrupting". Ack `Side question dispatched~`.
  30. **`/skill`** — see `platforms-a.discord-slash-skill`.
  Plus auto-registered commands: every entry of `hermes_cli.commands.COMMAND_REGISTRY` for which `_is_gateway_available(cmd_def, config_overrides)` is true and whose lowercase 32-char name is not already taken; and every plugin command from `_iter_plugin_command_entries()`. Auto commands get either no options or a single `args` string option described as `Arguments: <args_hint>` (truncated to 100 chars); descriptions default to `Run /<name>` and are truncated to 100 chars.
- **Outputs / side effects:** Commands are synced to Discord globally at startup; each invocation produces an ephemeral ack (when an ack string is given) followed by the normal gateway response in the channel.
- **Config / env:** `DISCORD_COMMAND_SYNC_POLICY`, `gateway.platforms.discord.extra.slash_commands` (bool, default `true`), `DISCORD_HIDE_SLASH_COMMANDS`.
- **Edge cases / guards:** Over the 100-command cap, lower-priority commands are skipped and the log warns: `[%s] Reached Discord's limit of %d slash commands; skipped %d lower-priority command(s) to keep the command sync working. Disable slash commands you don't need or trim installed plugins to surface them all.` A single over-limit command would otherwise make Discord reject the whole batch (error 30032). Names are lowercased and clamped to 32 chars; registration failures (e.g. name conflicts with a group) are silently skipped.
- **Rebuild notes:** Build a `CommandTree`, register hard-coded commands first, then reflect the generic registry, then sync. A better version would sync per-guild for instant propagation and would surface the dropped-command list in `/help` instead of only in logs.

### `/skill` — run an installed skill via autocomplete  `id: platforms-a.discord-slash-skill`
- **Surface:** Platform:discord
- **Where:** Discord `/` menu → **`/skill`**, description **"Run a Hermes skill"**.
- **What it does:** Runs any installed Hermes skill from Discord, with live prefix-filtered autocomplete over the skill catalog.
- **How it works:** `_register_skill_group()` at `plugins/platforms/discord/adapter.py:6206`. Deliberately ONE flat command (not `/skill <category> <name>`) because Discord enforces an ~8000-byte per-command payload limit and the nested layout produced ~14 KB with ~75 skills, which made `tree.sync()` reject the entire batch. Autocomplete options are fetched dynamically and do not count against the registration budget, so this scales to thousands of skills. Catalog state lives in `self._skill_entries` / `self._skill_lookup`, populated by `_refresh_skill_catalog_state()` at `:6343` from `hermes_cli.commands.discord_skill_commands_by_category(reserved_names=…)`; `refresh_skill_group()` at `:6369` re-runs it after `/reload-skills` with no `tree.sync()` needed.
- **Inputs / options:** `name` (string, required, autocompleted) — describe **"Which skill to run"**; `args` (string, optional) — **"Optional arguments for the skill"**. Autocomplete matches the typed prefix against both the skill name and its description, formats each entry as `"<name> — <description>"` truncated to 100 chars (with `...`), and returns at most 25 choices.
- **Outputs / side effects:** Dispatches `<skill command key> <args>` through `_run_simple_slash`. Unknown names produce the ephemeral message `Unknown skill: \`<name>\`. Start typing for autocomplete suggestions.`
- **Config / env:** Skills installed under `~/.hermes/skills/`.
- **Edge cases / guards:** Authorization is evaluated **before** the skill lookup so authorized and unauthorized users cannot probe the catalog via error text; the autocomplete callback returns `[]` (never an ephemeral error) for unauthorized users so typing does not produce a barrage of popups, and it never raises. Skills whose names clash with reserved command names are filtered out and counted in `_skill_group_hidden_count`, logged as `[%s] %d skill(s) filtered out of /skill (name clamp / reserved)`. Startup logs `[%s] Registered /skill command with %d skill(s) via autocomplete`; refresh logs `[%s] Refreshed /skill autocomplete: %d skill(s) available (%d filtered)`; failures log `[%s] Failed to register /skill command: %s`.
- **Rebuild notes:** One command + dynamic autocomplete beats N commands whenever the catalog is user-extensible. A better version would rank autocomplete by recent usage and show the skill's category as the choice description.

### Discord slash-command sync policy  `id: platforms-a.discord-command-sync-policy`
- **Surface:** Env
- **Where:** `~/.hermes/.env` → `DISCORD_COMMAND_SYNC_POLICY`.
- **What it does:** Controls how Hermes reconciles its slash commands with Discord's global command list at startup.
- **How it works:** `_get_discord_command_sync_policy()` at `plugins/platforms/discord/adapter.py:3135` (valid set `_DISCORD_COMMAND_SYNC_POLICIES = {"safe", "bulk", "off"}` at `:73`); `_safe_sync_slash_commands()` at `:3238` diffs the desired payload against the existing commands using `_canonicalize_app_command_payload()` `:3147`, `_existing_command_to_payload()` `:3179`, `_canonicalize_app_command_option()` `:3202`, `_patchable_app_command_payload()` `:3229` and `_normalize_permissions()` `:3172`, recreating commands whose metadata cannot be PATCHed. A fingerprint of the desired set (`_desired_command_sync_fingerprint()` `:2247`) is persisted in `~/.hermes/gateway/discord_command_sync_state.json` (`_command_sync_state_path()` `:2216`) so an unchanged set skips the sync entirely (`_command_sync_skip_reason()` `:2259`). Mutations are spaced by `_DISCORD_COMMAND_SYNC_MUTATION_INTERVAL_SECONDS = 4.5` (`:78`, `_sleep_between_command_sync_mutations()` `:2403`) and rate limits are absorbed with a sleep capped at `_DISCORD_COMMAND_SYNC_MAX_RATE_LIMIT_SLEEP_SECONDS = 30.0` (`:79`), extracted by `_extract_discord_retry_after()` `:2318` / `_is_discord_rate_limit()` `:2342`.
- **Inputs / options:** `"safe"` (default) — diff and patch only what changed, recreating when Discord metadata can't be patched; `"bulk"` — legacy `tree.sync()`; `"off"` — skip startup sync entirely.
- **Outputs / side effects:** Global application commands created/updated/deleted; state file records attempts (`_record_command_sync_attempt` `:2278`), rate limits (`_record_command_sync_rate_limit` `:2291`) and successes (`_record_command_sync_success` `:2307`), keyed per application ID (`_command_sync_state_key` `:2244`).
- **Config / env:** `DISCORD_COMMAND_SYNC_POLICY`, `gateway.platforms.discord.extra.slash_commands`.
- **Edge cases / guards:** Set `slash_commands: false` on follower gateways when several Hermes instances share one Discord application, otherwise the last startup wins and registrations flap.
- **Rebuild notes:** Keep a content hash of the command set on disk and skip the API round-trip when unchanged. A better version would use Discord's `PUT` bulk-overwrite only when the diff exceeds N changes, and expose a `hermes gateway discord sync --dry-run`.

### Discord slash-command access control (admin vs user tiers)  `id: platforms-a.discord-slash-access`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `gateway.platforms.discord.extra.{allow_from, allow_admin_from, user_allowed_commands, group_allow_admin_from, group_user_allowed_commands}`.
- **What it does:** Splits the allowlist into admins (all slash commands) and regular users (only an explicit command list plus a floor of `/help` and `/whoami`).
- **How it works:** `_evaluate_slash_authorization()` at `plugins/platforms/discord/adapter.py:5161` returns `(allowed, reason)`; `_check_slash_authorization()` `:5266` wraps it and calls `_reject_slash()` `:5283` on failure. DM scope and guild-channel scope have separate admin lists.
- **Inputs / options:** `allow_from` (list of user IDs), `allow_admin_from` (list), `user_allowed_commands` (list of command names without the leading slash), `group_allow_admin_from` (list), `group_user_allowed_commands` (list).
- **Outputs / side effects:** Unauthorized invocations get the ephemeral reply **`You're not authorized to use this command.`**, a `logger.warning` `[Discord] Unauthorized slash attempt: user=%s id=%s channel=%s guild=%s cmd=%r reason=%r`, and a best-effort cross-platform admin alert.
- **Config / env:** As listed. `/whoami` reports the active scope, tier (admin / user / unrestricted) and the runnable command list.
- **Edge cases / guards:** Backwards compatible — if `allow_admin_from` is unset for a scope, gating is disabled for that scope. Plain chat is never gated by this. DM admin status does not imply guild admin status.
- **Rebuild notes:** Two-tier ACL evaluated per interaction, with a hard floor of self-describing commands. A better version would support role IDs in the admin list and per-command allow expressions.

### Discord unauthorized-slash admin alert  `id: platforms-a.discord-unauthorized-alert`
- **Surface:** Platform:discord
- **Where:** Delivered to the operator's Telegram home channel, or Slack home channel as fallback.
- **What it does:** Notifies the gateway operator on another platform whenever someone tries a slash command they are not allowed to run.
- **How it works:** `_notify_unauthorized_slash()` at `plugins/platforms/discord/adapter.py:5332`, fired as a detached `asyncio.create_task` from `_reject_slash`. Tries `Platform.TELEGRAM` then `Platform.SLACK`, each requiring a configured home channel; a `SendResult(success=False)` continues the chain rather than counting as delivered.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Message text, verbatim: `⚠️ Unauthorized Discord slash attempt` / `User: <name> (<id>)` / `Channel: <chan_id> (guild <guild_id>)` / `Command: <command_text>` / `Reason: <reason>`.
- **Config / env:** `TELEGRAM_HOME_CHANNEL`, `SLACK_HOME_CHANNEL`.
- **Edge cases / guards:** Silent no-op when no other platform is configured with a home channel; never blocks the interaction handler.
- **Rebuild notes:** Fire-and-forget fan-out over configured home channels. Better: rate-limit per user so a bot spamming a command cannot flood the operator.

### Discord slash-command visibility hiding  `id: platforms-a.discord-hide-slash`
- **Surface:** Env
- **Where:** `~/.hermes/.env` → `DISCORD_HIDE_SLASH_COMMANDS=true`.
- **What it does:** Hides every Hermes slash command from non-admin guild members in Discord's own `/` picker.
- **How it works:** `_apply_owner_only_visibility()` at `plugins/platforms/discord/adapter.py:6169` sets `default_member_permissions = discord.Permissions(0)` on every registered command, which Discord interprets as "Administrator only". Server admins can re-grant per user/role via **Server Settings → Integrations → \<bot\> → Permissions**.
- **Inputs / options:** Truthy values accepted: `true`, `1`, `yes`, `on` (case-insensitive, stripped).
- **Outputs / side effects:** Log line `[Discord] Hid %d slash command(s) from non-admin guild members (opt-in defense in depth via DISCORD_HIDE_SLASH_COMMANDS).`; on failure `[Discord] _apply_owner_only_visibility: cannot build Permissions(0): %s` or `[Discord] Could not set default_permissions on %r: %s`.
- **Config / env:** `DISCORD_HIDE_SLASH_COMMANDS` (default `false`).
- **Edge cases / guards:** Purely cosmetic — the authoritative gate remains `_check_slash_authorization` on every invocation, which also catches stale clients, mistaken role grants and direct API calls.
- **Rebuild notes:** UI-hiding must never be the only gate. Better: compute per-user visibility from the actual allowlist rather than an all-or-nothing admin flag.

### Discord interactive model picker  `id: platforms-a.discord-model-picker`
- **Surface:** Platform:discord
- **Where:** Send **`/model`** with no arguments in a Discord channel.
- **What it does:** Opens a two-step dropdown (provider → model) for switching the session's model, with a confirmation step for expensive models.
- **How it works:** `send_model_picker()` at `plugins/platforms/discord/adapter.py:7805` builds `ModelPickerView` (defined at `_define_discord_view_classes` + 387, i.e. `plugins/platforms/discord/adapter.py:9194`). Timeout 120 s. Option labels truncated by `_truncate_discord_component_text()` `:215` to `_DISCORD_SELECT_FIELD_LIMIT = 100`; at most `_DISCORD_SELECT_MAX_OPTIONS = 25` options per select and `_DISCORD_SELECT_MAX_ROWS = 5` select rows (`_DISCORD_MODEL_SELECT_CAPACITY` `:91`).
- **Inputs / options:** Step 1 — Select with placeholder **`Choose a provider...`**, `custom_id="model_provider_select"`; Button **`Cancel`** (red, `custom_id="model_cancel"`). Step 2 — Select(s) with placeholder `"<placeholder_base><suffix>..."`, `custom_id="model_model_select_<idx>"`; Button **`◀ Back`** (grey, `custom_id="model_back"`); Button **`Cancel`** (red, `custom_id="model_cancel2"`). Expensive-model confirmation — Button **`Switch anyway`** (red, `custom_id="model_expensive_confirm"`); Button **`Cancel`** (grey, `custom_id="model_expensive_cancel"`).
- **Outputs / side effects:** Embeds titled **`⚙ Model Configuration`**, **`⚙ Switching Model`**, **`⚙ Model Switched`**, and a warning embed titled `⚠ <warning.title>`. The message is edited in place as the user navigates.
- **Config / env:** Model/provider registry from the Hermes config; `DISCORD_ALLOWED_USERS` gates who may interact.
- **Edge cases / guards:** Only authorized users can operate the picker; picker times out after 120 seconds; typing `/model <name>` directly bypasses it. Providers and models are each capped at 25 entries per dropdown.
- **Rebuild notes:** Two-level select drill-down with in-place message edits and a price-confirmation interstitial. A better version would paginate beyond 25 and show context window / price per entry in the option description.

### Discord generic choice picker (`/reasoning`, `/fast`)  `id: platforms-a.discord-choice-picker`
- **Surface:** Platform:discord
- **Where:** Rendered when a finite-choice gateway command is invoked without an argument.
- **What it does:** Shows one dropdown of options for single-level choice commands.
- **How it works:** `send_choice_picker()` at `plugins/platforms/discord/adapter.py:7867` builds `ChoicePickerView` (`:9555` region). Timeout 120 s; options capped at `_DISCORD_SELECT_MAX_OPTIONS = 25`.
- **Inputs / options:** Select placeholder **`Choose an option...`**; each option gets `label` (truncated to 100), `value`, and the description **`current`** when `choice["is_current"]` is set.
- **Outputs / side effects:** Calls the supplied `on_choice_selected(channel_id, value)` coroutine and posts its returned text.
- **Config / env:** Auth mirrors `ExecApprovalView` (adapter allowlist + roles).
- **Edge cases / guards:** Unauthorized clicks get the ephemeral message **`⛔ You are not authorized to change this setting.`**; a second selection after resolution silently defers.
- **Rebuild notes:** Single select + callback. Better: support multi-select and an inline "why" description per option.

### Discord exec-approval buttons  `id: platforms-a.discord-exec-approval`
- **Surface:** Platform:discord
- **Where:** Posted in the channel/thread when the agent requests approval for a dangerous command.
- **What it does:** Renders a four-button approval prompt that unblocks the waiting agent thread — the button equivalent of typing `/approve`.
- **How it works:** `send_exec_approval()` at `plugins/platforms/discord/adapter.py:7490` posts plain content **and** an embed (embeds can be invisible or visually detached on web/mobile, so the command and reason must appear in the content block too). `ExecApprovalView` (`:8820`) calls `tools.approval.resolve_gateway_approval(session_key, choice)`. Timeout comes from `_read_discord_prompt_timeout()` `:1003` — config `approvals.discord_prompt_timeout`, default `_DISCORD_PROMPT_TIMEOUT_DEFAULT = 300`, clamped to `[_DISCORD_PROMPT_TIMEOUT_MIN = 30, _DISCORD_PROMPT_TIMEOUT_MAX = 900]` (Discord interaction tokens expire at ~15 min). Admin gating resolved by `_resolve_exec_approval_admin_gate()` `:8772`; base admission by `_component_check_auth()` `:8684`.
- **Inputs / options:** Buttons: **`Allow Once`** (green → `once`), **`Allow Session`** (grey → `session`), **`Always Allow`** (blurple → `always`), **`Deny`** (red → `deny`). `allow_session=False` or `smart_denied=True` removes **Allow Session** and **Always Allow**; `allow_permanent=False` removes **Always Allow**.
- **Outputs / side effects:** Message content, verbatim: `⚠️ **Command Approval Required**` / `Do you want Hermes to run this command?` / `**Requested command:**` + a ```bash fenced block + `**Reason:** <reason>`; when `smart_denied`, an extra line `**Smart DENY:** owner override applies to this one operation only.` Embed title **`⚠️ Command Approval Required`** (orange), field name **`Reason`**. On resolution the embed recolours and the footer becomes `Approved once by <name>` / `Approved for session by <name>` / `Approved permanently by <name>` / `Denied by <name>`; all buttons disable. If the approval already timed out the footer becomes **`⌛ Approval expired — command was not run (already timed out or resolved elsewhere)`** in dark grey. On view timeout the footer becomes **`⏱ Prompt expired — no action taken`**.
- **Config / env:** `approvals.discord_prompt_timeout`, `discord.approval_mentions` / `DISCORD_APPROVAL_MENTIONS` (default `false`), `gateway.platforms.discord.extra.allow_admin_from`, `require_admin_for_exec_approval`.
- **Edge cases / guards:** Repeat clicks get **`This approval has already been resolved~`**; unauthorized clicks get **`You're not authorized to approve commands~`**. When `require_admin_for_exec_approval` is on but no admins are configured the buttons are dead for everyone and the log warns: `[Discord] require_admin_for_exec_approval is enabled but no admins are configured (allow_admin_from is empty) — exec approval buttons are disabled for everyone. Add admin user IDs under the discord platform's allow_admin_from, or disable the toggle.` Reason text is budgeted to 300 chars (`... [truncated]`); command text is budgeted against `MAX_MESSAGE_LENGTH` in content and 4088 chars in the embed description.
- **Rebuild notes:** Resolve the agent's wait FIRST, then render the outcome — otherwise a late click can claim "Approved" for a command that already timed out. A better version would show a diff/dry-run preview of the command's effect next to the buttons.

### Discord approval mentions  `id: platforms-a.discord-approval-mentions`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.approval_mentions` (bridged to `DISCORD_APPROVAL_MENTIONS`).
- **What it does:** Prefixes exec-approval prompts with `@` mentions of the allowlisted users so they get a push notification.
- **How it works:** `_approval_mention_content()` at `plugins/platforms/discord/adapter.py:7476` — only numeric allowlist entries are mentioned, joined as `<@id>`; when set, `send_exec_approval` also passes `discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False)`.
- **Inputs / options:** Boolean, default `false` (`config_defaults.json`: `discord.approval_mentions = false`).
- **Outputs / side effects:** A mention line above the approval prompt.
- **Config / env:** `discord.approval_mentions`, `DISCORD_APPROVAL_MENTIONS`.
- **Edge cases / guards:** Returns `None` (no mention) when disabled or when no numeric allowlist entries exist, so username-based allowlists never ping.
- **Rebuild notes:** Opt-in pinging with an explicit allowed-mentions mask. Better: ping only the user whose turn triggered the approval.

### Discord slash-confirmation buttons  `id: platforms-a.discord-slash-confirm`
- **Surface:** Platform:discord
- **Where:** Shown by `/reload-mcp` and any command routed through `GatewayRunner._request_slash_confirm`.
- **What it does:** Three-button confirmation for slash commands with side effects.
- **How it works:** `send_slash_confirm()` at `plugins/platforms/discord/adapter.py:7592`; `SlashConfirmView` at `:8983`. Resolution calls `tools.slash_confirm.resolve(session_key, confirm_id, choice)` and posts any returned text as a followup. Timeout `_read_discord_prompt_timeout()` (default 300 s).
- **Inputs / options:** Buttons **`Approve Once`** (green → `once`), **`Always Approve`** (blurple → `always`), **`Cancel`** (red → `cancel`).
- **Outputs / side effects:** Embed footer becomes `Approved once by <name>` / `Always approved by <name>` / `Cancelled by <name>`; buttons disable; log `Discord button resolved slash-confirm for session %s (choice=%s, user=%s)`.
- **Config / env:** `approvals.discord_prompt_timeout`.
- **Edge cases / guards:** Repeat click → **`This prompt has already been resolved~`**; unauthorized → **`You're not authorized to answer this prompt~`**; timeout footer **`⏱ Prompt expired — no action taken`**.
- **Rebuild notes:** Same shape as exec approval minus the session scope. Better: show what "Always" persists and where.

### Discord update prompt buttons  `id: platforms-a.discord-update-prompt`
- **Surface:** Platform:discord
- **Where:** Shown during a `hermes update` run initiated from Discord (`/update`).
- **What it does:** Yes/No buttons that answer the updater's interactive question from Discord.
- **How it works:** `send_update_prompt()` at `plugins/platforms/discord/adapter.py:7763`; `UpdatePromptView` at `:9098`. Writes the answer atomically to `<HERMES_HOME>/.update_response` (temp file + `replace`) which the detached update process polls.
- **Inputs / options:** Buttons **`Yes`** (green, emoji `✓` → writes `y`), **`No`** (red, emoji `✗` → writes `n`).
- **Outputs / side effects:** `~/.hermes/.update_response` written; embed footer `Yes by <name>` / `No by <name>`; log `Discord update prompt answered '%s' by %s`; on failure `Failed to write update response: %s`.
- **Config / env:** `HERMES_HOME`; timeout `_read_discord_prompt_timeout()` (default 300 s, matching the updater's own 5-minute timeout).
- **Edge cases / guards:** Second click → **`Already answered~`**; unauthorized → **`You're not authorized~`**; timeout footer **`⏱ Prompt expired — no action taken`**.
- **Rebuild notes:** File-based IPC between the gateway and the detached updater. A better version would use a unix socket or the gateway's own IPC so the answer cannot be lost to a stale file.

### Discord clarify prompt buttons  `id: platforms-a.discord-clarify`
- **Surface:** Platform:discord
- **Where:** Posted in-channel when the agent calls the `clarify` tool with preset choices.
- **What it does:** Renders one button per choice plus an "Other" escape hatch so the user answers a clarifying question with a click.
- **How it works:** `send_clarify()` at `plugins/platforms/discord/adapter.py:7636`; `ClarifyChoiceView` at `:9648`. A numeric click resolves via `tools.clarify_gateway.resolve_gateway_clarify(clarify_id, resolved_text)` — the canonical choice text is read back from `tools.clarify_gateway._entries` so the original value round-trips rather than the possibly-truncated button label. "Other" calls `mark_awaiting_text(clarify_id)` so the next user message in the session becomes the answer, without popping the entry.
- **Inputs / options:** Up to **24** choice buttons (primary style), labelled `"<n>. <choice>"` with `custom_id=f"clarify:{clarify_id}:{index}"`; plus **`✏️ Other (type answer)`** (secondary, `custom_id=f"clarify:{clarify_id}:other"`). Label truncation budget is `_DISCORD_BUTTON_LABEL_LIMIT = 80` UTF-16 units minus the `"n. "` prefix, cut preferentially at (1) the last space in the trailing half of the budget, (2) the latest soft boundary among `-`, `,`, `.`, `)` in the trailing half, (3) a hard cut, then suffixed with `…` (`_DISCORD_ELLIPSIS`).
- **Outputs / side effects:** On answer the embed turns green with footer `Answered by <display_name>: <choice>`; on "Other" it turns blue with footer `Awaiting typed response from <display_name>…`; all buttons disable. Logs `Discord clarify button resolved (id=%s, choice=%r, user=%s, ok=%s)`.
- **Config / env:** `agent.clarify_timeout` (default 600 s) for the agent-side wait; view timeout `_read_discord_prompt_timeout()`.
- **Edge cases / guards:** Repeat click → **`This prompt has already been answered~`**; unauthorized → **`You're not authorized to answer this prompt~`**; open-ended clarify calls (no preset choices) skip buttons entirely and just capture the next message; view timeout footer **`⏱ Prompt expired — no action taken`**; if the agent times out it unblocks with a sentinel rather than hanging.
- **Rebuild notes:** Buttons + a text-capture fallback flag on the pending entry. A better version would render >24 choices as a select menu automatically and support multi-select clarifies.

### Discord processing reactions (👀 / ✅ / ❌)  `id: platforms-a.discord-reactions`
- **Surface:** Platform:discord
- **Where:** Emoji reactions added directly to the user's own Discord message.
- **What it does:** Gives lightweight visual feedback that Hermes saw the message, finished, or errored.
- **How it works:** `_reactions_enabled()` at `plugins/platforms/discord/adapter.py:3352`; `on_processing_start()` `:3356` adds 👀, `on_processing_complete()` `:3368` swaps to ✅ or ❌ via `_add_reaction()` `:3330` / `_remove_reaction()` `:3341`.
- **Inputs / options:** `discord.reactions` (bool, default `true`), env `DISCORD_REACTIONS`.
- **Outputs / side effects:** Reactions on the triggering message; also recorded via `_record_discord_processing_start()` `:2987` and `_record_discord_processing_complete()` `:3005` in the recovery DB.
- **Config / env:** `discord.reactions`, `DISCORD_REACTIONS`.
- **Edge cases / guards:** Requires the **Add Reactions** permission; disable if the bot's role lacks it or the reactions are distracting.
- **Rebuild notes:** Three reaction states keyed to lifecycle events. Better: a fourth "queued" state and a progress reaction that ticks with tool calls.

### Discord history backfill  `id: platforms-a.discord-history-backfill`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.history_backfill` / `discord.history_backfill_limit`.
- **What it does:** When mentioned, prepends recent channel scrollback (since the bot's last response) to the user message so the bot has the context it missed while un-mentioned.
- **How it works:** `_discord_history_backfill()` `:6886`, `_discord_history_backfill_limit()` `:6895`, `_fetch_channel_context()` `:6915`. Scans backwards through `channel.history()`, stopping at the bot's own last message. Non-conversational bot output is filtered out by `_DiscordNonConversationalMessageTracker` (`:336`, persisted at `~/.hermes/gateway/discord_nonconversational_messages.json`, max tracked ids `_MAX_TRACKED`), `_metadata_marks_nonconversational()` `:390` and `_looks_like_nonconversational_history_message()` `:397` (pattern list `_DISCORD_NONCONVERSATIONAL_HISTORY_MESSAGE_PATTERNS` at `:108`, metadata keys `_DISCORD_NONCONVERSATIONAL_METADATA_KEYS` at `:96`).
- **Inputs / options:** `discord.history_backfill` (bool, default `true`), `discord.history_backfill_limit` (int, default `50`), env `DISCORD_HISTORY_BACKFILL`, `DISCORD_HISTORY_BACKFILL_LIMIT`.
- **Outputs / side effects:** A context block prepended to the prompt; nothing persisted to Discord.
- **Config / env:** As above.
- **Edge cases / guards:** Skipped in DMs (no mention gap), in free-response channels, and in the bot's own auto-created threads. In threads the scan covers the thread only, because Discord's `channel.history()` on a thread does not return parent-channel messages. Messages that arrive *while* the bot is processing are not captured — documented as an accepted simplification.
- **Rebuild notes:** Backward scan bounded by (a) the bot's last message and (b) a hard message cap. A better version would capture messages arriving mid-turn and fold them into the same turn.

### Discord missed-message backfill (reconnect recovery)  `id: platforms-a.discord-missed-backfill`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.missed_message_backfill.*`.
- **What it does:** After a Discord reconnect, replays messages that were sent while the gateway was disconnected, running them through the normal authorization/mention/dispatch path.
- **How it works:** `_missed_message_backfill_enabled()` `:2484`, `_missed_message_backfill_channels()` `:2495`, `_missed_message_backfill_window_seconds()` `:2517`, `_missed_message_backfill_limit()` `:2530`, `_missed_message_backfill_max_dispatches()` `:2543`, task started by `_ensure_missed_message_backfill_task()` `:2556`, body `_run_missed_message_backfill()` `:2572`, candidate iteration `_iter_missed_message_backfill_candidates()` `:2716` and `_iter_channel_and_thread_messages()` `:2768`, dispatch `_dispatch_recovered_message()` `:2686`, eligibility `_should_backfill_discord_message()` `:2846`. A per-profile SQLite ledger at `~/.hermes/gateway/discord_message_recovery.db` (`_discord_recovery_db_path()` `:2908`) records seen messages (`_record_discord_message_seen` `:2933`), attempts (`_record_recovery_attempt` `:2966`), responses (`_record_discord_response` `:3024`), scan starts/completions (`_record_recovery_scan_start` `:3111`, `_record_recovery_scan_complete` `:3124`) and per-channel cursors (`_discord_recovery_cursor` `:2814`, `_advance_discord_recovery_cursor` `:2827`), preventing an already-answered message from being replayed after a later restart (`_discord_message_is_persistently_complete` `:3078`, `_discord_message_has_active_claim` `:3091`).
- **Inputs / options:** `discord.missed_message_backfill.enabled` (bool, default `false`), `.channels` (list or `"*"`, default `""` → falls back to `discord.free_response_channels`), `.window_seconds` (int, default `21600` = 6 h), `.limit` (int, default `100`, global scan cap per reconnect), `.max_dispatches` (int, default `10`, recovery dispatch cap per reconnect).
- **Outputs / side effects:** Replayed messages produce normal agent responses; the SQLite ledger grows.
- **Config / env:** `discord.missed_message_backfill.*`.
- **Edge cases / guards:** Down-notice messages are recognised by `_is_down_notice_content()` `:2862` and messages that already got a real (non-down-notice) bot response are skipped via `_message_has_non_down_bot_response()` `:2870`. `"*"` scans every reachable server text channel — use sparingly.
- **Rebuild notes:** Durable per-channel cursor + idempotency ledger keyed by message id. A better version would use Discord's resume/session-id semantics first and fall back to scanning only for the gap the resume could not cover.

### Discord gateway WebSocket liveness watchdog  `id: platforms-a.discord-ws-liveness`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.websocket_*` keys. Invisible until it triggers a reconnect.
- **What it does:** Detects a Discord Gateway WebSocket that is silently dead even while REST still returns 200, and forces one retryable fatal event so the gateway's reconnect watcher builds a fresh adapter.
- **How it works:** `_start_liveness_probe()` `:1909`, `_read_websocket_health()` `:1926` (combines ready state, client/socket closure state, socket openness, heartbeat-ACK age and finite heartbeat latency), `_liveness_loop()` `:1969`, `_notify_liveness_fatal_error()` `:2023`, `_cancel_liveness_task()` `:2075`. Transport abort helper `_abort_discord_websocket_transport()` `:220`.
- **Inputs / options:** `discord.websocket_liveness_interval_seconds` (default `15`), `discord.websocket_liveness_failure_threshold` (default `2`), `discord.websocket_heartbeat_ack_max_age_seconds` (default `60`), `discord.websocket_max_latency_seconds` (default `30`). Legacy aliases `liveness_interval_seconds` / `liveness_failure_threshold` remain accepted but no longer mean REST probing.
- **Outputs / side effects:** One retryable fatal event after N consecutive unhealthy samples; no second unbounded reconnect loop inside the adapter.
- **Config / env:** As above; ready-wait timeout from `_discord_ready_timeout_seconds()` `:558`.
- **Edge cases / guards:** A successful REST response (including `fetch_user()` → HTTP 200) is explicitly not treated as proof of Gateway liveness.
- **Rebuild notes:** Sample heartbeat ACK age + socket state on a timer; escalate only after consecutive failures. A better version would export the health samples as metrics so flapping links are visible before they cause outages.

### Discord mention control (allowed mentions)  `id: platforms-a.discord-mention-control`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.allow_mentions.*`; env `DISCORD_ALLOW_MENTION_*`.
- **What it does:** Stops the bot from pinging `@everyone`, `@here` or roles even when its generated text contains those tokens.
- **How it works:** `_build_allowed_mentions()` at `plugins/platforms/discord/adapter.py:523` (inner `_b(name, default)` at `:544` reads the env booleans) builds a `discord.AllowedMentions` mask attached to every send.
- **Inputs / options:** `discord.allow_mentions.everyone` (default `false` / `DISCORD_ALLOW_MENTION_EVERYONE`), `.roles` (default `false` / `DISCORD_ALLOW_MENTION_ROLES`), `.users` (default `true` / `DISCORD_ALLOW_MENTION_USERS`), `.replied_user` (default `true` / `DISCORD_ALLOW_MENTION_REPLIED_USER`).
- **Outputs / side effects:** Suppressed pings; the text still renders as `@everyone` but notifies nobody.
- **Config / env:** As above; env wins over config.yaml.
- **Edge cases / guards:** Docs warn that an LLM easily emits `@everyone` in ordinary prose — leave `everyone` and `roles` at `false` unless there is a specific reason.
- **Rebuild notes:** Always attach an explicit allowed-mentions mask rather than relying on content sanitisation. Better: strip the literal tokens too, so the message does not visually alarm readers.

### Discord role-based access control  `id: platforms-a.discord-role-auth`
- **Surface:** Env
- **Where:** `~/.hermes/.env` → `DISCORD_ALLOWED_ROLES`; plus `~/.hermes/config.yaml` → `discord.dm_role_auth_guild`.
- **What it does:** Authorizes any guild member holding one of the listed role IDs, so access follows the role rather than an individual allowlist.
- **How it works:** `_get_allowed_roles()` `:6696`, `resolved_allowlist_user_ids()` `:6704`, `_is_allowed_user()` `:5007`. Setting `DISCORD_ALLOWED_ROLES` auto-enables the Server Members Intent on connect (`_needs_server_members_intent()` `:276`). For DMs, `_read_dm_role_auth_guild()` at `:957` reads `discord.dm_role_auth_guild` from config.yaml only (never `.env`, per the repo policy that `.env` holds secrets only) and scans that guild for the user's roles; invalid/empty/non-positive values return `None`, keeping DM role auth disabled.
- **Inputs / options:** `DISCORD_ALLOWED_ROLES` (comma-separated role IDs); `discord.dm_role_auth_guild` (int or numeric string, default `""`).
- **Outputs / side effects:** Authorization decision only.
- **Config / env:** As above; combines with `DISCORD_ALLOWED_USERS` using OR semantics.
- **Edge cases / guards:** Role **IDs**, not names — obtained via User Settings → Advanced → Developer Mode ON, then right-click role → **Copy Role ID**. DM fallback scans mutual guilds. Pairing-approved users are handled separately by `_is_pairing_approved_user()` `:4995`.
- **Rebuild notes:** OR-combine user and role allowlists; require the members intent when roles are used. Better: cache role membership with a short TTL to avoid per-message member fetches.

### Discord per-channel ephemeral prompts  `id: platforms-a.discord-channel-prompts`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.channel_prompts`.
- **What it does:** Injects a channel-specific system prompt on every turn in that channel or thread, without persisting it to transcript history.
- **How it works:** `_resolve_channel_prompt()` at `plugins/platforms/discord/adapter.py:6555` delegating to `gateway.platforms.base.resolve_channel_prompt(self.config.extra, channel_id, parent_id)`.
- **Inputs / options:** Mapping of channel/thread ID (string) → prompt text (multi-line). Default `{}`.
- **Outputs / side effects:** Prompt text prepended ephemerally at runtime.
- **Config / env:** `discord.channel_prompts`.
- **Edge cases / guards:** Exact thread/channel ID matches win; a thread or forum post with no explicit entry falls back to its parent channel/forum ID. Changes take effect on the next turn with no history rewrite.
- **Rebuild notes:** A dict lookup with parent fallback, applied as a system message that is never written back into the transcript. Better: support glob/category matching and a per-prompt token budget.

### Discord channel→skill bindings  `id: platforms-a.discord-channel-skills`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `gateway.platforms.discord.extra.channel_skill_bindings`.
- **What it does:** Automatically activates a named set of skills for conversations in specific channels or forums.
- **How it works:** `_resolve_channel_skills()` at `plugins/platforms/discord/adapter.py:6543` → `gateway.platforms.base.resolve_channel_skills(self.config.extra, channel_id, parent_id)`.
- **Inputs / options:** YAML list of `{id: "<channel id>", skills: ["skill-a", "skill-b"]}`.
- **Outputs / side effects:** The named skills are auto-loaded for turns in that channel; forum threads inherit their forum's bindings via `parent_id`.
- **Config / env:** `gateway.platforms.discord.extra.channel_skill_bindings`.
- **Edge cases / guards:** Returns `None` when no binding matches (skills unchanged).
- **Rebuild notes:** Channel-keyed skill preload with parent inheritance. Better: allow role- and user-scoped bindings too.

### Discord home channel & `/sethome`  `id: platforms-a.discord-home-channel`
- **Surface:** Platform:discord
- **Where:** Discord `/` menu → **`/sethome`** ("Set this chat as the home channel"); or `.env` keys `DISCORD_HOME_CHANNEL` / `DISCORD_HOME_CHANNEL_NAME`.
- **What it does:** Designates the channel that receives proactive messages — cron job output, reminders, notifications and cross-platform relays.
- **How it works:** `/sethome` routes through `_run_simple_slash(interaction, "/sethome")`; the platform registration declares `cron_deliver_env_var="DISCORD_HOME_CHANNEL"` (`plugins/platforms/discord/adapter.py:10594`). Out-of-process cron uses `standalone_sender_fn=_standalone_send`.
- **Inputs / options:** `DISCORD_HOME_CHANNEL` (channel ID), `DISCORD_HOME_CHANNEL_NAME` (display name, default `"Home"`). The setup wizard also mentions typing `/set-home` in a channel.
- **Outputs / side effects:** `.env` updated; cron jobs with `deliver=discord` land in that channel.
- **Config / env:** As above.
- **Edge cases / guards:** Without a live adapter (e.g. `hermes cron` standalone), delivery falls back to the REST standalone sender; without `standalone_sender_fn` such jobs would fail with "No live adapter".
- **Rebuild notes:** One env var + a slash command that writes it. Better: support multiple named delivery targets (`home`, `alerts`, `reports`).

### Discord standalone (out-of-process) sender  `id: platforms-a.discord-standalone-send`
- **Surface:** Core
- **Where:** Invoked by `tools/send_message_tool._send_via_adapter` when no live `DiscordAdapter` exists in the process (e.g. `hermes cron` running standalone).
- **What it does:** Sends Discord messages/files directly over the REST API, reproducing the live adapter's forum/thread/multipart behaviour.
- **How it works:** `_standalone_send` and helpers in `plugins/platforms/discord/adapter.py:9904`+ — `_remember_channel_is_forum()` `:9904`, `_probe_is_forum_cached()` `:9908`, `_derive_forum_thread_name()` `:9912`, `_standalone_sanitize_error()` `:9922`, `_standalone_close_response()` `:9938`, `_standalone_response_encoding()` `:9985`. Process-local cache `_DISCORD_CHANNEL_TYPE_PROBE_CACHE`; body limits `_DISCORD_STANDALONE_JSON_BODY_LIMIT_BYTES = 1 MiB` and `_DISCORD_STANDALONE_ERROR_BODY_LIMIT_BYTES = 8 KiB`.
- **Inputs / options:** Channel ID, message content, optional attachments.
- **Outputs / side effects:** REST calls to `https://discord.com/api`; forum channels get a new thread per send.
- **Config / env:** `DISCORD_BOT_TOKEN`.
- **Edge cases / guards:** Error bodies are sanitised before logging so tokens are never echoed; forum detection is cached per process to avoid re-probing.
- **Rebuild notes:** Keep the standalone path in the same module as the adapter so the two implementations cannot drift. Better: share one transport layer between live and standalone modes.

### Discord media sending (inline `MEDIA:` tags)  `id: platforms-a.discord-media-send`
- **Surface:** Platform:discord
- **Where:** Emitted by the agent inside its reply as `MEDIA:/path/to/file`; the tag is stripped and the file uploaded.
- **What it does:** Uploads images, GIFs, video, audio/voice and documents as native Discord attachments.
- **How it works:** `_send_file_attachment()` `:3963`, `send_image_file()` `:5382`, `send_image()` `:5399`, `send_animation()` `:5481`, `send_video()` `:5553`, `send_document()` `:5570`, `send_multiple_images()` `:4036`, `send_voice()` `:4184`, `play_tts()` `:4166`; image fetch follows `_DISCORD_IMAGE_REDIRECT_STATUSES = {301,302,303,307,308}` up to `_DISCORD_IMAGE_MAX_REDIRECTS = 10` (`:100`).
- **Inputs / options:** Per media type: PNG/JPG/WebP → native image attachment with inline preview; animated GIF → `send_animation` uploads as `animation.gif` so Discord plays it inline instead of showing a static thumbnail; MP4/MOV → `send_video` (native player); audio/voice → `send_voice` (native voice message when possible, otherwise a file attachment); PDF/ZIP/docx/etc. → `send_document` (attachment with download button).
- **Outputs / side effects:** Files uploaded to Discord; on HTTP 413 the adapter falls back to posting a link to the local cache path rather than failing silently.
- **Config / env:** Discord's per-upload limit depends on the server boost tier (25 MB free, up to 500 MB).
- **Edge cases / guards:** 413 fallback as above; forum channels attach files to the starter message of a new thread (`_forum_post_file()` `:3653`).
- **Rebuild notes:** Parse `MEDIA:` tags out of the reply, dispatch by extension/MIME, and always keep a link fallback. Better: chunk-upload large files or auto-transcode above the tier limit.

### Discord attachment ingestion (arbitrary file types)  `id: platforms-a.discord-attachments`
- **Surface:** Platform:discord
- **Where:** Any file a user drags into a Discord chat with the bot.
- **What it does:** Accepts any uploaded file type, caches it locally, and hands the agent either the decoded text or a local path it can inspect with tools.
- **How it works:** `_read_attachment_bytes()` `:7989`, `_cache_discord_image()` `:8025`, `_cache_discord_audio()` `:8044`, `_cache_discord_document()` `:8063`; voice-message detection via `_is_discord_voice_message_attachment()` `:6607`. Files land in `~/.hermes/cache/documents/` and are surfaced as a `DOCUMENT`-typed message event. Sandbox path translation uses `to_agent_visible_cache_path` for Docker/Modal terminals.
- **Inputs / options:** `discord.max_attachment_bytes` (int, default `33554432` = 32 MiB; `0` = unlimited), env `DISCORD_MAX_ATTACHMENT_BYTES`; legacy `discord.allow_any_attachment` / `DISCORD_ALLOW_ANY_ATTACHMENT` (default `false`) is now a **no-op** kept only so existing configs do not error (`_discord_allow_any_attachment()` `:6569`, `_discord_max_attachment_bytes()` `:6584`).
- **Outputs / side effects:** Cached file on disk; small UTF-8-decodable files (text, code, config, HTML, CSS, JSON, YAML) have their contents auto-injected into the prompt up to **100 KiB**; binary files become a path-pointing context note only.
- **Config / env:** As above.
- **Edge cases / guards:** Known types keep their precise MIME; unknown types fall back to the upload's reported content type or `application/octet-stream`. Authorization to message the bot is the only gate — not the file extension. Disabling the cap means a multi-GB upload is buffered through memory while caching to disk, so it is documented as trusted-single-user-only.
- **Rebuild notes:** Download → cache → classify → inject-or-point. A better version would stream to disk instead of buffering in memory, making `0` (unlimited) safe.

### Discord forum-channel support  `id: platforms-a.discord-forum`
- **Surface:** Platform:discord
- **Where:** Discord forum channels (channel type 15).
- **What it does:** Lets Hermes post into forum channels, which cannot accept plain messages, by creating a new forum thread per send.
- **How it works:** `_send_to_forum()` at `plugins/platforms/discord/adapter.py:3595`, `_forum_post_file()` `:3653`, `_is_forum_parent()` `:7925`, `_get_parent_channel_id()` `:7915`. Detection is three-layered: the channel directory cache, then a process-local probe cache (`_probe_is_forum_cached` / `_remember_channel_is_forum`), then a live `GET /channels/{id}` probe whose result is memoized for the process lifetime.
- **Inputs / options:** n/a — automatic on any send to a forum channel.
- **Outputs / side effects:** A new forum thread per send. Thread name is derived from the first line of the message (markdown heading prefix stripped, capped at 100 chars); for attachment-only messages the filename is used instead. Attachments ride along on the starter message — no separate upload step and no partial sends.
- **Config / env:** n/a.
- **Edge cases / guards:** Successive sends to the same forum produce separate threads (one call, one thread). Forums created after the bot started are picked up by refreshing the directory (`/channels refresh` where exposed, or a gateway restart).
- **Rebuild notes:** Detect `channel.type == 15` and route to `POST /channels/{id}/threads` with a `message` payload. Better: reuse an open thread for a continuing conversation instead of creating a new one per send.

### Discord voice messages (STT / TTS)  `id: platforms-a.discord-voice-messages`
- **Surface:** Platform:discord
- **Where:** Discord voice messages sent to the bot; `/voice tts` for spoken replies.
- **What it does:** Transcribes inbound Discord voice messages and optionally replies with spoken audio.
- **How it works:** Voice attachments are recognised by `_is_discord_voice_message_attachment()` `:6607` and cached by `_cache_discord_audio()` `:8044`; transcription uses the configured STT provider. Outbound speech: `play_tts()` `:4166` and `send_voice()` `:4184`.
- **Inputs / options:** `/voice on` — voice reply to voice messages; `/voice tts` — voice reply to all messages; `/voice off` — text only; `/voice status` — show current mode.
- **Outputs / side effects:** Native Discord voice messages when possible, otherwise audio file attachments.
- **Config / env:** STT providers: local `faster-whisper` (no key), Groq Whisper (`GROQ_API_KEY`), OpenAI Whisper (`VOICE_TOOLS_OPENAI_KEY`).
- **Edge cases / guards:** Falls back to a file attachment when a native voice message cannot be constructed.
- **Rebuild notes:** Detect the voice-message attachment flag, download the ogg/opus, transcribe, and reply with a waveform-carrying voice message. Better: stream partial transcripts so long voice notes do not stall the turn.

### Discord voice-channel presence (join / listen / speak)  `id: platforms-a.discord-voice-channel`
- **Surface:** Platform:discord
- **Where:** `/voice join` (alias `/voice channel`) and `/voice leave` from a Discord text channel while you are in a voice channel.
- **What it does:** Makes Hermes join a Discord voice channel, listen to the users speaking, transcribe them, and talk back.
- **How it works:** `join_voice_channel()` `:4556`, `leave_voice_channel()` `:4613`, `play_in_voice_channel()` `:4649`, `get_user_voice_channel()` `:4745`, `is_in_voice_channel()` `:4812`, `get_voice_channel_info()` `:4817`, `get_voice_channel_context()` `:4868`, `_voice_listen_loop()` `:4893`, `_process_voice_input()` `:4938`. Receive path: `VoiceReceiver` at `:572` installs a speaking hook (`_install_speaking_hook()` `:657`), maps SSRC→user (`map_ssrc()` `:653`, `_infer_user_for_ssrc()` `:838`), decodes packets (`_on_packet()` `:694`), detects silence (`check_silence()` `:864`), flushes pending audio (`flush_pending()` `:897`) and writes WAV via `pcm_to_wav()` `:922`; `start()` `:617`, `stop()` `:629`, `pause()` `:643`, `resume()` `:646`. Idle timers: `_cancel_voice_timeout()` `:4757`, `_reset_voice_timeout()` `:4762`, `_voice_timeout_handler()` `:4773`. Playback duration is probed by `_probe_audio_duration_seconds()` `:4374` and the effective wait computed by `_playback_timeout_for_audio()` `:4409`. On Windows the bundled Opus library is located by `_find_discord_windows_bundled_opus()` `:316`; ffmpeg helpers live in `plugins/platforms/discord/ffmpeg_utils.py`.
- **Inputs / options:** `discord.voice_channel_inactivity_timeout_seconds` (default `300`; `0` = stay until an explicit `/voice leave` or manual disconnect), `discord.voice_playback_timeout_seconds` (default `120`, a floor rather than a hard cap — long clips wait `duration + 30 s` via `PLAYBACK_TIMEOUT_PADDING`). Loaders: `_load_voice_timeout()` `:4352`, `_load_playback_timeout()` `:4360`, `_voice_timeout_limit()` `:4368`, `_playback_timeout_limit()` `:4371`, `_load_discord_int_config()` `:4340`.
- **Outputs / side effects:** The bot appears in the voice channel; transcribed speech becomes agent turns; TTS is played back into the channel.
- **Config / env:** As above; STT/TTS provider config; `plugins/platforms/discord/recovery.py` handles voice reconnection.
- **Edge cases / guards:** Only allowed user IDs are captured by `VoiceReceiver(allowed_user_ids=…)`. discord.py plays only one audio stream per connection — see the voice-FX mixer entry.
- **Rebuild notes:** Voice receive requires an RTP/Opus decode path plus SSRC→user mapping from the speaking event. A better version would run continuous VAD-driven streaming ASR instead of silence-delimited buffers.

### Discord voice audio effects (ambient bed + verbal acks)  `id: platforms-a.discord-voice-fx`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `discord.voice_fx.*`.
- **What it does:** Gives voice-channel mode a conversational feel — a short spoken acknowledgement before the bot starts working and a subtle ambient "thinking" bed underneath tool execution, with the speech ducking the ambient down and swelling it back.
- **How it works:** `plugins/platforms/discord/voice_mixer.py` (387 lines) implements a software mixer because discord.py plays only one audio stream per connection; the mixer sums ambient loop + acknowledgements + TTS into that single stream so they overlap instead of cutting each other off. Adapter glue: `_load_voice_fx_config()` `:4300`, `_get_ambient_pcm()` `:4417`, `_install_voice_mixer()` `:4443`, `_lead_silence_bytes()` `:4473`, `play_ack_in_voice()` `:4494`, `voice_mixer_active()` `:4551`.
- **Inputs / options:** `discord.voice_fx.enabled` (bool, default `false` — master switch), `.ambient_enabled` (default `true`), `.ambient_path` (string, default `""` → built-in synthesised pad; any file ffmpeg can decode, looped seamlessly), `.ambient_gain` (float, default `0.18`, range 0.0–1.0), `.duck_gain` (default `0.06`, ambient loudness while the bot speaks), `.speech_gain` (default `1.0`), `.ack_enabled` (default `true`), `.ack_phrases` (list, default `["Let me look into that.", "One moment.", "Checking on that now.", "Give me a sec.", "On it."]`; set to `[]` to disable the spoken ack).
- **Outputs / side effects:** Mixed audio in the voice channel.
- **Config / env:** All settings live in `config.yaml` (not `.env`) because they are behavioural, not secrets.
- **Edge cases / guards:** The acknowledgement fires at most once per turn, only when the bot is in a voice channel and the mixer is active, and uses the configured TTS provider. When `voice_fx.enabled` is `false` playback uses the original one-shot path and nothing changes.
- **Rebuild notes:** One PCM mixing bus with per-source gain and a ducking envelope. A better version would crossfade the ambient bed and support per-guild profiles.

### Discord platform events (edit / delete / thread create / thread update)  `id: platforms-a.discord-platform-events`
- **Surface:** Core
- **Where:** Emitted to the gateway's platform-event bus when subscribers exist; not directly user-visible.
- **What it does:** Surfaces Discord message edits, deletions and thread lifecycle changes as structured Hermes platform events.
- **How it works:** `_platform_events_subscribed()` `:1715` gates the work; `_on_platform_message_edit()` `:1724`, `_on_platform_message_delete()` `:1772`, `_on_platform_thread_create()` `:1817`, `_on_platform_thread_update()` `:1853`; sources built by `_source_for_platform_event()` `:1668` and dispatched by `_fire_platform_event()` `:1698`; channel/thread identity from `_thread_id_and_chat_for_channel()` `:1653`.
- **Inputs / options:** n/a — driven by Discord gateway events.
- **Outputs / side effects:** Platform events consumed by subscribers (automations, observers).
- **Config / env:** n/a.
- **Edge cases / guards:** All handlers no-op when nothing is subscribed, so unsubscribed installs pay no cost.
- **Rebuild notes:** Wire discord.py's `on_message_edit`, `on_message_delete`, `on_thread_create`, `on_thread_update` to a generic event bus. Better: include the before/after diff so subscribers do not have to re-fetch.

### Discord text batching (streamed chunk smoothing)  `id: platforms-a.discord-text-batching`
- **Surface:** Env
- **Where:** `~/.hermes/.env` → `HERMES_DISCORD_TEXT_BATCH_DELAY_SECONDS`, `HERMES_DISCORD_TEXT_BATCH_SPLIT_DELAY_SECONDS`.
- **What it does:** Buffers streamed text chunks briefly before flushing so the channel does not fill with one-line messages.
- **How it works:** `_text_batch_key()` `:8593`, `_enqueue_text_event()` `:8610`, `_flush_text_batch()` `:8638`, deadline from `_text_batch_flush_deadline_seconds()` `:2133`.
- **Inputs / options:** `HERMES_DISCORD_TEXT_BATCH_DELAY_SECONDS` (default `0.6`) — grace window before flushing a queued chunk; `HERMES_DISCORD_TEXT_BATCH_SPLIT_DELAY_SECONDS` (default `2.0`) — delay between split chunks when one message exceeds Discord's length limit.
- **Outputs / side effects:** Fewer, larger Discord messages.
- **Config / env:** As above.
- **Edge cases / guards:** Combined with `MAX_SPLIT_MESSAGES = 8`: chunks beyond the cap are replaced by a short notice (added after an incident that delivered 60,698 chars as 31 messages).
- **Rebuild notes:** Coalesce by (channel, session) key with a debounce timer. Better: edit a single message in place rather than posting more messages.

### Discord message editing & overflow splitting  `id: platforms-a.discord-edit-overflow`
- **Surface:** Core
- **Where:** Streaming/edit updates to an already-posted Discord message.
- **What it does:** Edits a previously sent message and, when the new content exceeds 2000 chars, splits it across follow-up messages instead of failing.
- **How it works:** `edit_message()` at `plugins/platforms/discord/adapter.py:3737`, `_is_length_overflow_error()` `:3839`, `_edit_overflow_split()` `:3852`, `_cap_split_chunks()` `:3415`, `send()` `:3438`, reply references from `_message_reference_from_ids()` `:3386` and `_reply_reference_for_send()` `:3401`.
- **Inputs / options:** `DISCORD_REPLY_TO_MODE` — `"off"` (never reply-reference), `"first"` (default; reply-reference on the first chunk only), `"all"` (every chunk).
- **Outputs / side effects:** Edited and/or additional Discord messages.
- **Config / env:** `DISCORD_REPLY_TO_MODE`, `display.platforms.discord.streaming` (default `false`).
- **Edge cases / guards:** `MAX_SPLIT_MESSAGES = 8` caps the number of split deliveries; overflow detection is by error shape, not by pre-measuring.
- **Rebuild notes:** Try the edit, catch the 50035 length error, then split. Better: pre-measure in UTF-16 units to avoid the failed round-trip.

### Discord reasoning display style  `id: platforms-a.discord-reasoning-style`
- **Surface:** Config
- **Where:** `~/.hermes/config.yaml` → `display.platforms.discord.reasoning_style`.
- **What it does:** Chooses how the model's reasoning block renders in Discord.
- **How it works:** Read by the shared display layer; Discord's default differs from other platforms.
- **Inputs / options:** `subtext` (Discord default — uses Discord's native `-# ` small grey metadata text so reasoning stays visually secondary), `blockquote` (renders as a `>` quote), `code` (fenced code block; the default on other platforms).
- **Outputs / side effects:** Long reasoning is collapsed to the first **15 lines**.
- **Config / env:** `display.platforms.discord.reasoning_style`; related `display.tool_progress` (`off` | `new` | `all` | `verbose`, default `all`; `all` truncates tool calls to 40 characters in gateway messages) and `display.tool_progress_command` (bool, default `false` — enables the `/verbose` slash command that cycles `off → new → all → verbose → off`).
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Per-platform render strategy for a secondary content channel. Better: make the collapse threshold configurable and add a "show more" interaction.

### Discord proxy support  `id: platforms-a.discord-proxy`
- **Surface:** Env
- **Where:** `~/.hermes/.env` → `DISCORD_PROXY`.
- **What it does:** Routes all Discord connections (HTTP, WebSocket, REST) through a proxy.
- **How it works:** Read during `connect()` (`plugins/platforms/discord/adapter.py:1274`) and applied to the discord.py client; overrides `HTTPS_PROXY` / `ALL_PROXY`.
- **Inputs / options:** URL with scheme `http://`, `https://` or `socks5://`.
- **Outputs / side effects:** All Discord traffic traverses the proxy.
- **Config / env:** `DISCORD_PROXY`, falling back to `HTTPS_PROXY` / `ALL_PROXY`.
- **Edge cases / guards:** socks5 requires the corresponding aiohttp/socks extras.
- **Rebuild notes:** One proxy URL applied to both the REST session and the WS connector. Better: allow separate REST and WS proxies and per-proxy auth.

### `discord` tool (agent-facing server participation)  `id: platforms-a.discord-tool`
- **Surface:** Tool
- **Where:** Toolset `discord`; visible to the model as the tool named `discord`.
- **What it does:** Lets the agent read and participate in a Discord server: search members, fetch recent messages, and create threads.
- **How it works:** `tools/discord_tool.py` calls the Discord REST API v10 directly (`DISCORD_API_BASE = "https://discord.com/api/v10"`) with the bot token from `agent.secret_scope.get_secret`, independent of the gateway adapter's client. Schema is filtered twice: (1) by privileged intents detected from `GET /applications/@me` at schema-build time (application flag bits `_FLAG_GATEWAY_GUILD_MEMBERS = 1<<14`, `_FLAG_GATEWAY_GUILD_MEMBERS_LIMITED = 1<<15`, `_FLAG_GATEWAY_MESSAGE_CONTENT = 1<<18`, `_FLAG_GATEWAY_MESSAGE_CONTENT_LIMITED = 1<<19`) — actions needing an unavailable intent are hidden, while `fetch_messages` stays but its description is annotated when MESSAGE_CONTENT is missing; (2) by the config allowlist `discord.server_actions` (`_load_allowed_actions_config()` at `tools/discord_tool.py:704`). Registered with `check_fn: check_discord_tool_requirements`, `is_async: false`, empty emoji. Response body cap `_DISCORD_RESPONSE_BODY_MAX_BYTES = 4 MiB`, error body cap `_DISCORD_ERROR_BODY_MAX_BYTES = 64 KiB`.
- **Inputs / options:** `action` (required enum): `search_members`, `fetch_messages`, `create_thread`. Parameters: `guild_id` ("Discord server (guild) ID."), `channel_id` ("Discord channel ID."), `user_id` ("Discord user ID."), `role_id` ("Discord role ID."), `message_id` ("Discord message ID."), `query` ("Member name prefix to search for (search_members)."), `name` ("New thread name (create_thread)."), `limit` (integer 1–100, "Max results (default 50). Applies to fetch_messages, search_members."), `before` ("Snowflake ID for reverse pagination (fetch_messages)."), `after` ("Snowflake ID for forward pagination (fetch_messages)."), `auto_archive_duration` (enum 60 | 1440 | 4320 | 10080, "Thread archive duration in minutes (create_thread, default 1440)."). Description text advises: "Use the channel_id from the current conversation context. Use search_members to look up user IDs by name prefix."
- **Outputs / side effects:** JSON tool results; `create_thread` creates a real Discord thread.
- **Config / env:** `DISCORD_BOT_TOKEN`; `discord.server_actions` (comma string or YAML list, default `""` = all intent-available actions).
- **Edge cases / guards:** Missing token → `tool_error("DISCORD_BOT_TOKEN not configured.")`. Unknown action → `tool_error(f"Unknown action: {action}", available_actions=…)`. Config-denied action → `Action '<action>' is disabled by config (discord.server_actions). Allowed: <list or <none>>` (a defense-in-depth re-check even though the schema was already filtered, in case of a stale cached schema). Missing required params → `Missing required parameters for '<action>': <names>`. Per-guild permissions (e.g. MANAGE_ROLES) are **not** pre-checked — Discord's 403 is mapped to actionable guidance by `_enrich_403`. Unknown names in `discord.server_actions` are dropped with the log `discord.server_actions: unknown action(s) ignored: %s. Known: %s`; an unexpected type logs `discord.server_actions: unexpected type %s; ignoring.`
- **Rebuild notes:** Action-dispatch tool over a REST API with intent- and config-based schema filtering. A better version would pre-check per-guild permissions from the bot's member object so failures surface before the call.

### `discord_admin` tool (agent-facing server management)  `id: platforms-a.discord-admin-tool`
- **Surface:** Tool
- **Where:** Toolset `discord_admin`; tool name `discord_admin`.
- **What it does:** Lets the agent inspect and manage a Discord server: list guilds/channels/roles, look up members, pin/unpin/delete messages, and add/remove roles.
- **How it works:** Same module and gating as `platforms-a.discord-tool` (`tools/discord_tool.py`, shared handler at `:~1000`, shared `check_fn: check_discord_tool_requirements`). Required-parameter map `_REQUIRED_PARAMS` (`:~690`) — `pin_message`: `[channel_id, message_id]`; `unpin_message`: `[channel_id, message_id]`; `delete_message`: `[channel_id, message_id]`; `create_thread`: `[channel_id, name]`; `add_role`: `[guild_id, user_id, role_id]`; `remove_role`: `[guild_id, user_id, role_id]`.
- **Inputs / options:** `action` (required enum, 12 values with their documented semantics): `list_guilds()` — list servers the bot is in; `server_info(guild_id)` — server details + member counts; `list_channels(guild_id)` — all channels grouped by category; `channel_info(channel_id)` — single channel details; `list_roles(guild_id)` — roles sorted by position; `member_info(guild_id, user_id)` — lookup a specific member; `list_pins(channel_id)` — pinned messages in a channel; `pin_message(channel_id, message_id)`; `unpin_message(channel_id, message_id)`; `delete_message(channel_id, message_id)`; `add_role(guild_id, user_id, role_id)`; `remove_role(guild_id, user_id, role_id)`. Same parameter set as the `discord` tool: `guild_id`, `channel_id`, `user_id`, `role_id`, `message_id`, `query`, `name`, `limit` (1–100, default 50), `before`, `after`, `auto_archive_duration` (60 | 1440 | 4320 | 10080). Description advises: "Call list_guilds first to discover guild_ids, then list_channels for channel_ids. Runtime errors will tell you if the bot lacks a specific per-guild permission (e.g. MANAGE_ROLES for add_role)."
- **Outputs / side effects:** Destructive actions really delete messages and change role assignments in Discord.
- **Config / env:** `DISCORD_BOT_TOKEN`, `discord.server_actions`.
- **Edge cases / guards:** `search_members` and `member_info` are hidden when the bot lacks the GUILD_MEMBERS intent (`_INTENT_GATED_MEMBERS`). Per-guild permissions surface as 403s enriched into guidance. Same config allowlist re-check as the `discord` tool.
- **Rebuild notes:** Keep destructive admin actions in a separate toolset so they can be withheld from untrusted sessions. A better version would require an exec-approval prompt for `delete_message`, `add_role` and `remove_role`.


---

## 2. Slack

### Slack platform adapter  `id: platforms-a.slack`
- **Surface:** Platform:slack
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Slack"** (emoji 💼); runs inside `hermes gateway`. In Slack itself: 1:1 DMs (Messages tab), group DMs (MPIMs), public channels (`C…`), private channels (`G…`), threads, and the Agent/Assistant DM surface.
- **What it does:** Connects Hermes to one or more Slack workspaces as a bot over **Socket Mode** (WebSocket — no public URL needed), relaying DM/channel/thread messages into the Hermes agent and posting replies back. Adds every Hermes command as a native slash command, Block Kit approval/clarify buttons, working-state status lines, native streaming, native task cards, reactions and file uploads.
- **How it works:** `plugins/platforms/slack/adapter.py:1105` defines `SlackAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/slack/adapter.py:9888` calls `ctx.register_platform(name="slack", label="Slack", adapter_factory=_build_adapter, check_fn=slack_deps_present, ensure_deps_fn=check_slack_requirements, is_connected=_is_connected, required_env=["SLACK_BOT_TOKEN","SLACK_APP_TOKEN"], install_hint="Run `hermes setup` to install Slack support.", setup_fn=interactive_setup, apply_yaml_config_fn=_apply_yaml_config, allowed_users_env="SLACK_ALLOWED_USERS", allow_all_env="SLACK_ALLOW_ALL_USERS", cron_deliver_env_var="SLACK_HOME_CHANNEL", standalone_sender_fn=_standalone_send, max_message_length=39000, emoji="💼", allow_update_command=True)`. Manifest `plugins/platforms/slack/plugin.yaml:1` (`name: slack-platform`, `label: Slack`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). Library: `slack-bolt` `AsyncApp` + `AsyncSocketModeHandler` (`slack_deps_present` at `:337`, `check_slack_requirements` at `:360`). Class constants at `:1122`: `MAX_MESSAGE_LENGTH = 39000`, `supports_code_blocks = True`, `supports_status_text = True`, `splits_long_messages = True`, `typed_command_prefix = "!"`, `supports_inchannel_continuable = True`. Inbound: `@self._app.event("message")` at `:2213` → `_handle_slack_message()`. Dedup window `_slack_dedup_ttl_seconds()` at `:987` = **3600 s** default (covers Socket Mode replay after reconnect), override `SLACK_DEDUP_TTL_SECONDS`.
- **Inputs / options:** Env: `SLACK_BOT_TOKEN` (required; comma-separated list for multi-workspace), `SLACK_APP_TOKEN` (required, `xapp-`, scope `connections:write`), `SLACK_ALLOWED_USERS`, `SLACK_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`, `GATEWAY_ALLOWED_USERS`, `SLACK_HOME_CHANNEL`, `SLACK_HOME_CHANNEL_NAME`, `SLACK_REQUIRE_MENTION`, `SLACK_STRICT_MENTION`, `SLACK_IGNORE_OTHER_USER_MENTIONS`, `SLACK_THREAD_REQUIRE_MENTION`, `SLACK_REQUIRE_MENTION_CHANNELS`, `SLACK_FREE_RESPONSE_CHANNELS`, `SLACK_ALLOWED_CHANNELS`, `SLACK_IGNORED_CHANNELS`, `SLACK_DISABLE_DMS`, `SLACK_ALLOW_BOTS`, `SLACK_REACTIONS`, `SLACK_REACTION_TRIGGERS`, `SLACK_REACTION_TRIGGER_TARGET`, `SLACK_MENTION_PATTERNS`, `SLACK_DEDUP_TTL_SECONDS`. Config: `slack.*` block plus `platforms.slack.*` / `platforms.slack.extra.*`.
- **Outputs / side effects:** Bot online in every configured workspace; posts messages, files, ephemeral slash replies, Block Kit prompts, reactions and status lines; reads/writes `~/.hermes/slack_tokens.json` (OAuth token file), `~/.hermes/slack-manifest.json` (generated manifest), media cache under `~/.hermes/cache/`.
- **Config / env:** `slack.require_mention` (default `true`), `slack.free_response_channels` (`""`), `slack.allowed_channels` (`""`), `slack.require_mention_channels` (`""`), `slack.ignore_other_user_mentions` (`false`), `slack.thread_require_mention` (`false`), `display.platforms.slack.streaming` (`false`), `display.live_status`, `group_sessions_per_user`, `unauthorized_dm_behavior`, `stt_enabled`, plus all `platforms.slack.extra.*` keys documented below.
- **Edge cases / guards:** Fails **closed** — without `SLACK_ALLOWED_USERS` (and without an allow-all flag) all inbound messages are denied. 1:1 DMs are exempt from `allowed_channels`; **group DMs (MPIMs) are not**. Slack refuses native slash commands inside threads ("*/queue is not supported in threads. Sorry!*"), hence the `!` prefix. Bolt returns HTTP 404 for unhandled events and never acks — a catch-all `@self._app.event(re.compile(r".*"))` at `:2300` acks everything else so Slack does not auto-disable Event Subscriptions after crossing its 95%/60-min failure threshold.
- **Rebuild notes:** Minimal spec: `slack_bolt.async_app.AsyncApp(token=xoxb)` + `AsyncSocketModeHandler(app, xapp)`; on `message`, run dedup → channel allow/deny → mention gate → session key → agent → `chat_postMessage` (chunked at 39 000). A better version would use Slack's OAuth install flow instead of pasted tokens and hold per-workspace sockets so one workspace's rate limits cannot stall the others.

### Slack interactive setup wizard  `id: platforms-a.slack-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Slack**; also the plugin's `setup_fn`.
- **What it does:** Generates and writes the Slack app manifest, walks the operator through creating the app, collects the two tokens, sets an allowlist, and optionally sets a home channel.
- **How it works:** `interactive_setup()` at `plugins/platforms/slack/adapter.py:9682`; helper `_write_slack_manifest_and_instruct()` at `:9701` calls `hermes_cli.slack_cli._build_full_manifest(bot_name="Hermes", bot_description="Your Hermes agent on Slack")` and writes `<HERMES_HOME>/slack-manifest.json` (JSON, `indent=2`, `ensure_ascii=False`, trailing newline). Uses `hermes_cli.cli_output.{prompt,prompt_yes_no,print_header,print_info,print_success,print_warning}` and `hermes_cli.config.{get_env_value,save_env_value,remove_env_value}`.
- **Inputs / options:** Verbatim strings in order:
  - header `Slack`
  - `Slack: already configured` (only when `SLACK_BOT_TOKEN` exists)
  - `Reconfigure Slack?` (yes/no, default `False`)
  - `Regenerate the Slack app manifest with the latest command list? (recommended after `hermes update`)` (yes/no, default `True`) — offered when declining reconfigure
  - `Steps to create a Slack app:`
  - `   1. Go to https://api.slack.com/apps → Create New App`
  - `      Pick 'From an app manifest' — we'll generate one for you below.`
  - `   2. Enable Socket Mode: Settings → Socket Mode → Enable`
  - `      • Create an App-Level Token with 'connections:write' scope`
  - `   3. Install to Workspace: Settings → Install App`
  - `   4. After installing, invite the bot to channels: /invite @YourBot`
  - `   Full guide: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack/`
  - `Slack app manifest written to: <path>` / `   Paste it into https://api.slack.com/apps → your app → Features → App Manifest → Edit, then Save.  Slack will prompt to reinstall if scopes or slash commands changed.` / `   Re-run `hermes slack manifest --write` anytime to refresh after Hermes adds new commands.` / on failure `Could not write Slack manifest: <err>`
  - prompt `Slack Bot Token (xoxb-...)` (password, aborts the wizard when empty)
  - prompt `Slack App Token (xapp-...)` (password, optional)
  - `Slack tokens saved`
  - `🔒 Security: Restrict who can use your bot`
  - `   To find a Member ID: click a user's name → View full profile → ⋮ → Copy member ID`
  - prompt `Allowed user IDs (comma-separated, leave empty to deny everyone except paired users)`
  - `Slack allowlist configured` OR `⚠️  No Slack allowlist set - unpaired users will be denied by default.` + `   Set SLACK_ALLOW_ALL_USERS=true or GATEWAY_ALLOW_ALL_USERS=true only if you intentionally want open workspace access.`
  - `📬 Home Channel: where Hermes delivers cron job results,` / `   cross-platform messages, and notifications.` / `   To get a channel ID: open the channel in Slack, then right-click` / `   the channel name → Copy link — the ID starts with C (e.g. C01ABC2DE3F).` / `   You can also set this later by typing /set-home in a Slack channel.`
  - prompt `Home channel ID (leave empty to set later with /set-home)`
  - `Home channel cleared.` (when previously set and now blank)
- **Outputs / side effects:** Writes `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_USERS` (spaces stripped), `SLACK_HOME_CHANNEL` into `~/.hermes/.env`; writes `~/.hermes/slack-manifest.json`.
- **Config / env:** as above.
- **Edge cases / guards:** Manifest generation failure is non-fatal (`print_warning`). Blank bot token returns immediately without saving anything.
- **Rebuild notes:** A prompt sequence over an env writer, with a manifest generator so the operator never clicks through scopes/events/slash commands. A better version would call `apps.manifest.create` with a Slack configuration token so the app is created programmatically.

### Slack app manifest generation  `id: platforms-a.slack-manifest`
- **Surface:** CLI (Slack-scoped)
- **Where:** `hermes slack manifest [--agent-view] [--write] [--slashes-only] [--long-description "…"] [--long-description-file <path>]`; documented at `website/docs/user-guide/messaging/slack.md:37`.
- **What it does:** Emits a Slack app-manifest JSON that declares every Hermes command as a slash command, every required OAuth scope, every bot event subscription, and enables Socket Mode — so a whole app can be created by pasting one blob.
- **How it works:** `hermes_cli/slack_cli.py::_build_full_manifest()` (invoked from `plugins/platforms/slack/adapter.py:9709`); the slash list comes from `hermes_cli.commands.slack_native_slashes()`, the same generator the adapter's runtime matcher uses (`plugins/platforms/slack/adapter.py:2325`). `--write` targets `<HERMES_HOME>/slack-manifest.json`. `--agent-view` produces Slack's **Agent** messaging experience (subscribes `message.im`, `app_home_opened`, `app_context_changed`); without it the legacy Assistant view is produced.
- **Inputs / options:** `--agent-view`, `--write`, `--slashes-only` (emits only the `features.slash_commands` array; mutually exclusive with the long-description options), `--long-description "<text>"`, `--long-description-file <path>` (UTF-8 text/Markdown, contents preserved exactly, Slack's 175–4 000-character range; mutually exclusive with `--long-description`).
- **Outputs / side effects:** JSON on stdout, or `~/.hermes/slack-manifest.json` with `--write`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Agent view **cannot be reverted** to Assistant view; users may need a hard refresh of Slack after switching. In Socket Mode Slack routes the command over the socket regardless of the manifest `url`, but a slash command absent from the manifest is never delivered.
- **Rebuild notes:** Template a manifest from the command registry + a fixed scope/event list. Full flag semantics and output shape are documented in `cli-b.slack.manifest` / `cli-b.slack.native-slashes`. A better version would diff the live app manifest against the generated one and print only what changed.

### Slack OAuth scopes required by Hermes  `id: platforms-a.slack-scopes`
- **Surface:** Docs / Platform:slack
- **Where:** Slack app → **Features → OAuth & Permissions → Scopes → Bot Token Scopes**; table in `website/docs/user-guide/messaging/slack.md:83`.
- **What it does:** Declares the exact bot-token scopes that make each Hermes Slack capability work.
- **How it works:** Emitted into the generated manifest; missing scopes surface at connect time via `_warn_if_missing_group_dm_scopes()` (`plugins/platforms/slack/adapter.py:1912`), which inspects the `x-oauth-scopes` header on the `auth.test` response, and at runtime via `_describe_slack_api_error()` (`:1658`) / `_describe_slack_download_failure()` (`:1700`).
- **Inputs / options:** Required scopes, verbatim with purposes: `chat:write` — "Send messages as the bot"; `app_mentions:read` — "Detect when @mentioned in channels"; `channels:history` — "Read messages in public channels the bot is in"; `channels:read` — "List and get info about public channels"; `groups:history` — "Read messages in private channels the bot is invited to"; `im:history` — "Read direct message history"; `im:read` — "View basic DM info"; `im:write` — "Open and manage DMs"; `mpim:history` — "Read group direct message (multi-person DM) history"; `mpim:read` — "View basic group DM info"; `users:read` — "Look up user information"; `files:read` — "Read and download attached files, including voice notes/audio"; `files:write` — "Upload files (images, audio, documents)". Optional: `groups:read` — "List and get info about private channels"; `assistant:write` — required for the working-state status line; `reactions:read` — required for reaction triggers.
- **Outputs / side effects:** n/a (Slack-side app configuration).
- **Config / env:** n/a.
- **Edge cases / guards:** Doc caution verbatim: "Without `channels:history` and `groups:history`, the bot **will not receive messages in channels** — it will only work in DMs. Without `files:read`, Hermes can chat but **cannot reliably read user-uploaded attachments**. These are the most commonly missed scopes." Any scope change requires **reinstalling** the app.
- **Rebuild notes:** Ship the scope list as data next to the manifest generator, and assert it against `auth.test`'s `x-oauth-scopes` at connect. A better version would emit a per-capability readiness table in `hermes gateway status`.

### Slack bot event subscriptions  `id: platforms-a.slack-events`
- **Surface:** Platform:slack
- **Where:** Slack app → **Features → Event Subscriptions → Subscribe to bot events**; table at `website/docs/user-guide/messaging/slack.md:138`; runtime handlers at `plugins/platforms/slack/adapter.py:2212–2310`.
- **What it does:** Defines which Slack events reach Hermes and which handler each one runs.
- **How it works:** Handlers registered on the Bolt `AsyncApp` in `connect()`, in this order (first matching listener wins): `message` → `_handle_slack_message(event, body)` (`:2213`); `app_mention` → same pipeline, deduped by shared event ts (`:2224`); `app_home_opened` → `_handle_app_home_opened` (`:2228`); `app_context_changed` → `_handle_app_context_changed` (`:2232`); `file_shared` → `_handle_slack_file_shared` (`:2239`); `file_created` → no-op ack (`:2243`); `file_change` → no-op ack (`:2247`); `reaction_added` → `_handle_slack_reaction(event)` (`:2257`); `reaction_removed` → `_handle_slack_reaction(event, removed=True)` (`:2261`); `assistant_thread_started` → `_handle_assistant_thread_lifecycle_event` (`:2265`); `assistant_thread_context_changed` → same (`:2269`); catch-all `re.compile(r".*")` → debug-log + ack (`:2300`).
- **Inputs / options:** Manifest-declared events with verbatim doc labels: `message.im` — **Yes** — "Bot receives direct messages"; `message.mpim` — **Yes** — "Bot receives messages in **group DMs** (multi-person DMs) it's added to"; `message.channels` — **Yes** — "Bot receives messages in **public** channels it's added to"; `message.groups` — **Recommended** — "Bot receives messages in **private** channels it's invited to"; `app_mention` — **Yes** — "Prevents Bolt SDK errors when bot is @mentioned". Agent view additionally subscribes `app_home_opened` and `app_context_changed`. Reaction triggers additionally need `reaction_added` / `reaction_removed`.
- **Outputs / side effects:** Every envelope is acked with HTTP 200, including unhandled types.
- **Config / env:** n/a.
- **Edge cases / guards:** Verbatim catch-all debug line: `[Slack] Ignoring unhandled event type=%s (no listener registered; subscribed events not handled by Hermes can be removed from the Slack app manifest via `hermes slack manifest`)`. Doc danger box: "If the bot works in DMs but **not in channels**, you almost certainly forgot to add `message.channels` … and/or `message.groups`."
- **Rebuild notes:** Register named listeners then a catch-all ack; never leave an envelope un-acked. A better version would auto-prune manifest subscriptions to only the events the build actually handles.

### Slack Messages tab (DM enablement)  `id: platforms-a.slack-messages-tab`
- **Surface:** Platform:slack
- **Where:** Slack app → **Features → App Home → Show Tabs → Messages Tab**; documented at `website/docs/user-guide/messaging/slack.md:160`.
- **What it does:** Turns on the DM surface so users can message the bot at all.
- **How it works:** Pure Slack app configuration; the generated manifest sets it. Without it Slack shows **"Sending messages to this app has been turned off"** and never delivers a DM event.
- **Inputs / options:** Toggle **Messages Tab** to ON; checkbox **"Allow users to send Slash commands and messages from the messages tab"**.
- **Outputs / side effects:** DMs to the bot become possible.
- **Config / env:** n/a.
- **Edge cases / guards:** Doc danger box verbatim: "Even with all the correct scopes and event subscriptions, Slack will not allow users to send direct messages to the bot unless the Messages Tab is enabled. This is a Slack platform requirement, not a Hermes configuration issue."
- **Rebuild notes:** Set `features.app_home.messages_tab_enabled` + `messages_tab_read_only_enabled: false` in the manifest. A better version would probe `apps.manifest.export` at connect and warn when the tab is off.

### Slack native slash commands (whole command registry)  `id: platforms-a.slack-slash`
- **Surface:** Platform:slack
- **Where:** Type `/` in any Slack message box — the autocomplete lists every Hermes command (`/btw`, `/stop`, `/new`, `/model`, `/help`, `/status`, `/queue`, `/bg`, `/set-home`, …).
- **What it does:** Every entry in Hermes' `COMMAND_REGISTRY` is a real Slack slash command; typing it runs the gateway command and returns the reply privately.
- **How it works:** One regex matcher covers all of them — `plugins/platforms/slack/adapter.py:2325` builds `_slash_pattern = re.compile(r"^/(?:" + "|".join(re.escape(n) for n in _slash_names) + r")$")` from `hermes_cli.commands.slack_native_slashes()`; `@self._app.command(_slash_pattern)` (`:2337`) acks with `response_type="ephemeral"` and text ``Running `/{slash}`…`` then calls `_handle_slash_command(command)`. Fallback pattern when the registry is empty: `^/hermes$`.
- **Inputs / options:** Any registered command name; arguments follow the command (`/model gpt-5.4`). The legacy `/hermes <subcommand>` form still routes identically (`/hermes bg run the tests` ≡ `/bg run the tests`), and free-form text after `/hermes` is treated as a regular message.
- **Outputs / side effects:** Ephemeral ack ``Running `/<cmd>`…`` replaced in place by the command's reply.
- **Config / env:** Requires the slash commands to be declared in the Slack app manifest.
- **Edge cases / guards:** Slack never delivers a slash command that the manifest does not declare, and never delivers *any* slash inside a thread; use the `!` prefix there.
- **Rebuild notes:** Generate slash declarations from the command registry and dispatch via one regex listener. A better version would register only the commands available to the caller's permission tier so autocomplete stops advertising admin commands.

### Slack `!command` bang prefix (commands inside threads)  `id: platforms-a.slack-bang-prefix`
- **Surface:** Platform:slack
- **Where:** Any Slack message, especially thread replies: `!queue`, `!stop`, `!model gpt-5.4`, `!approve`, `!deny`, `@Hermes !stop`.
- **What it does:** Provides an alternate command prefix that works where Slack blocks native slashes (threads).
- **How it works:** `typed_command_prefix = "!"` (`plugins/platforms/slack/adapter.py:1131`); `_rewrite_known_bang_command()` at `:445` rewrites a **leading** `!` to `/` only when the first token matches a known command, then `_handle_slack_message` dispatches it as a command.
- **Inputs / options:** `!<command> [args]`; tolerated with leading whitespace and behind a bot mention (`@Hermes !stop`).
- **Outputs / side effects:** Replies as a normal (visible) message in the same thread — not ephemeral.
- **Config / env:** n/a.
- **Edge cases / guards:** Only the first token is checked, so `!nice work` passes through to the agent unchanged. Slack's own refusal text when a native slash is typed in a thread is verbatim: "*/queue is not supported in threads. Sorry!*" — there is no app-side setting that re-enables it.
- **Rebuild notes:** Match `^\s*(?:<@BOT>\s*)?!(\w[\w-]*)\b` against the command registry and rewrite to `/`. A better version would let operators pick the prefix character.

### Slack ephemeral slash replies  `id: platforms-a.slack-slash-ephemeral`
- **Surface:** Platform:slack
- **Where:** Reply to any native slash command; Slack labels it **"Only visible to you"**.
- **What it does:** Delivers slash-command output privately so command noise never hits the channel, replacing the "Running /cmd…" placeholder in place.
- **How it works:** `_send_slash_ephemeral()` at `plugins/platforms/slack/adapter.py:1787` POSTs to the command's `response_url` with `{"response_type": "ephemeral", "replace_original": idx == 0, "text": chunk}` (aiohttp, `trust_env=True`, 10 s total timeout). Context storage: `_slash_command_contexts` keyed `(team_id, channel_id, user_id)`, TTL `_SLASH_CTX_TTL = 120.0` s (`:1744`), matched via the `_slash_user_id` ContextVar in `_pop_slash_context()` (`:1750`). Fallback `_post_ephemeral_fallback()` at `:1859` uses `chat.postEphemeral` (no `replace_original`, no 5-post cap).
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Up to `_MAX_RESPONSE_URL_POSTS = 5` POSTs per `response_url`; extra chunks are dropped with the verbatim notice appended to the last kept chunk: `\n\n_[Reply truncated: {dropped} more part(s) exceeded Slack's ephemeral reply limit.]_`.
- **Config / env:** n/a.
- **Edge cases / guards:** A slash reply is **never** posted publicly as a fallback — the second path is also ephemeral. `response_url` is valid 30 min Slack-side but Hermes discards contexts after 120 s. Commands typed as regular messages (`!cmd` in threads, `@Hermes /cmd`) reply as normal visible messages instead. Non-200 responses log `[Slack] response_url POST returned %s: %s` (body truncated to 200 chars) and return `success=False` so `send()` can fall back.
- **Rebuild notes:** Keep a short-TTL map from (team, channel, user) → response_url and swap the ack. A better version would use Slack's `chat.postEphemeral` `blocks` so long output can collapse behind an expander instead of being truncated.

### Slack exec-approval buttons  `id: platforms-a.slack-exec-approval`
- **Surface:** Platform:slack
- **Where:** Approval prompt posted into the thread; title line `:warning: *Command Approval Required*`; buttons **"Allow Once"**, **"Allow Session"**, **"Always Allow"**, **"Deny"**.
- **What it does:** Renders dangerous-command / `execute_code` approval requests as Block Kit buttons that unblock the waiting agent thread.
- **How it works:** `send_exec_approval()` at `plugins/platforms/slack/adapter.py:7155`. Header `":warning: *Command Approval Required*\n"`, plus `"*Smart DENY:* owner override applies to this one operation only.\n"` when `smart_denied`; body ` ```<cmd_preview>``` ` and `Reason: <description[:500]>`; the preview is budgeted against Slack's 3 000-char section cap (`budget = 3000 - len(header) - len(reason) - len("``````\n") - len("...")`). Notification fallback text: `⚠️ Command approval required: {cmd_preview[:100]}`. Buttons carry `action_id` `hermes_approve_once` (style `primary`), `hermes_approve_session`, `hermes_approve_always`, `hermes_deny` (style `danger`), `value = session_key`. Handler `_handle_approval_action()` at `:7653` maps action → `once|session|always|deny` and calls `tools.approval.resolve_gateway_approval(session_key, choice)`.
- **Inputs / options:** Four buttons; `allow_session=False` hides "Allow Session" and "Always Allow", `allow_permanent=False` hides "Always Allow", `smart_denied=True` leaves only "Allow Once" + "Deny". Text equivalents: `!approve` / `!deny` (the thread-safe form the text fallback instructs).
- **Outputs / side effects:** The prompt message is rewritten via `chat.update` to a section (original text, clipped to 3 000 chars) + a context line: `✅ Approved once by {user}`, `✅ Approved for session by {user}`, `✅ Approved permanently by {user}`, `❌ Denied by {user}`, or `Resolved by {user}`. Log line: `Slack button resolved %d approval(s) for session %s (choice=%s, user=%s)`.
- **Config / env:** `SLACK_ALLOWED_USERS` (button clicks are re-authorized independently of the message path).
- **Edge cases / guards:** Double-click guard is an atomic pop on `_approval_resolved` (checked against both the workspace-scoped marker and the bare ts). Approval is resolved **before** rendering, so a late click shows verbatim `⌛ Approval expired — command was not run (already timed out or resolved elsewhere)` rather than falsely claiming success. Unauthorized clicks log `[Slack] Unauthorized approval click by %s (%s) - ignoring` and do nothing. Oversized blocks would fail with `invalid_blocks`, so the gateway falls back to a plain-text prompt with no buttons.
- **Rebuild notes:** Post an actions block whose button values are the session key; resolve first, render second. A better version would show the requesting tool and a diff/preview instead of raw command text, and expire the buttons visually on timeout.

### Slack slash-confirm buttons  `id: platforms-a.slack-slash-confirm`
- **Surface:** Platform:slack
- **Where:** Confirmation prompt for gated slash commands; buttons **"Approve Once"**, **"Always Approve"**, **"Cancel"**.
- **What it does:** Renders a generic three-option confirmation for a slash command that needs explicit consent.
- **How it works:** `send_slash_confirm()` at `plugins/platforms/slack/adapter.py:7259`; body `*{title[:150]}*\n\n{message}` budgeted to 3 000 chars; button `value` packs `"{session_key}|{confirm_id}"`; action IDs `hermes_confirm_once` (primary), `hermes_confirm_always`, `hermes_confirm_cancel` (danger). Handler `_handle_slash_confirm_action()` (`:7510`) calls `tools.slash_confirm.resolve(session_key, confirm_id, choice)` and posts any returned follow-up text into the same thread.
- **Inputs / options:** Three buttons. Default title when none given: `Confirm`.
- **Outputs / side effects:** Message updated to context line `✅ Approved once by {user}` / `🔒 Always approved by {user}` / `❌ Cancelled by {user}` / `Resolved by {user}`. Notification fallback text `{title or 'Confirm'}: {body[:100]}`.
- **Config / env:** interactive-user authorization (see `platforms-a.slack-interactive-auth`).
- **Edge cases / guards:** Malformed value (no `|`) logs `[Slack] Malformed slash-confirm value: %s` and aborts. Original section text is clipped to 3 000 chars before `chat.update` because Slack re-escapes `&<>` in the interaction payload and can inflate it past the limit.
- **Rebuild notes:** Encode both ids in the button value; resolve via the shared confirm primitive. A better version would carry an expiry timestamp in the value so a stale click is distinguishable from an unknown id.

### Slack clarify prompts (one-tap buttons)  `id: platforms-a.slack-clarify`
- **Surface:** Platform:slack
- **Where:** Any multiple-choice question from the `clarify` tool; one button per option plus **"✏️ Other…"**.
- **What it does:** Turns the agent's multiple-choice question into tappable Block Kit buttons; "Other" switches to free-text mode so the next typed message becomes the answer.
- **How it works:** `send_clarify()` at `plugins/platforms/slack/adapter.py:7342`. Question rendered as `❓ {question}` with `&`, `<`, `>` escaped to `&amp;`, `&lt;`, `&gt;`; body budgeted to 3 000 chars. Choice buttons: `action_id = f"hermes_clarify_choice_{idx}"`, `value = f"{clarify_id}|{idx}"`, label = choice text clipped to 75 chars (fallback label `Option {idx+1}`); the last element is `{"text": "✏️ Other…", "action_id": "hermes_clarify_other", "value": f"{clarify_id}|other"}`. Elements are chunked into actions blocks of 5. Handler `_handle_clarify_action()` at `:7818`; matcher `re.compile(r"^hermes_clarify_choice_\d+$")` plus `hermes_clarify_other` (`:2370`). Open-ended clarify (no choices) delegates to the base adapter, which renders a plain question and arms the gateway's text-intercept.
- **Inputs / options:** Up to 4 choices (the `clarify` tool's cap) + Other = 5, matching Slack's 5-element actions-block limit; a longer list degrades by chunking rather than 400ing.
- **Outputs / side effects:** On a choice tap the message is rewritten to context `✅ {user}: {resolved_text}`; on "Other" to `✏️ Awaiting typed answer from {user}…`; on an expired/evicted entry to `⏳ This prompt expired — please send a new request. (by {user})`. Log lines: `Slack button resolved clarify (id=%s, choice_index=%d, user=%s)` at INFO, the choice text only at DEBUG (`Slack clarify choice text (id=%s): %.100r`).
- **Config / env:** Works regardless of the `rich_blocks` setting; no configuration needed.
- **Edge cases / guards:** Double-click guard via atomic pop on `_clarify_resolved[msg_ts]`. Unauthorized clicks log `[Slack] Unauthorized clarify click by %s (%s) - ignoring`. Malformed value logs `[Slack] Malformed clarify value: %s`; a non-integer token logs `[Slack] Invalid clarify choice token: %s`. Falls back to the positional label `choice {idx+1}` if the registry entry is gone.
- **Rebuild notes:** Buttons whose values pack `clarify_id|index`; "Other" flips the entry into a text-capture state resolved by the platform-agnostic intercept. A better version would render >5 choices as a static select menu instead of chunked button rows.

### Slack feedback buttons (Good/Bad Response)  `id: platforms-a.slack-feedback-buttons`
- **Surface:** Platform:slack
- **Where:** Appended to the final Block Kit reply; buttons **"Good Response"** and **"Bad Response"** (accessibility labels "Submit positive feedback on this response" / "Submit negative feedback on this response").
- **What it does:** Adds Slack-native AI feedback controls to final agent replies.
- **How it works:** `_feedback_block()` at `plugins/platforms/slack/adapter.py:4219` returns `{"type": "context_actions", "elements": [{"type": "feedback_buttons", "action_id": "hermes_feedback", "positive_button": {...,"value": "positive"}, "negative_button": {...,"value": "negative"}}]}`. `_append_feedback_block()` (`:4245`) appends it only when blocks exist, the feature is enabled, and the block count is < 50. Handler `_handle_feedback_action()` (`:7638`) acks and logs `[Slack] Feedback button clicked: value=%s user=%s channel=%s ts=%s`.
- **Inputs / options:** Two buttons.
- **Outputs / side effects:** A log line only — no persisted feedback store.
- **Config / env:** `platforms.slack.extra.feedback_buttons` (default `false`); requires `rich_blocks: true` (or `markdown_blocks`) because it only attaches to a blocks payload. Truthy values: `1`, `true`, `yes`, `on`.
- **Edge cases / guards:** Silently skipped when there are already 50 blocks or when no blocks are being sent.
- **Rebuild notes:** One `context_actions` block appended to the final blocks list. A better version would persist the rating against the turn id so it can drive evaluation.

### Slack Block Kit rich rendering (`rich_blocks`)  `id: platforms-a.slack-rich-blocks`
- **Surface:** Config (Platform:slack)
- **Where:** `platforms.slack.extra.rich_blocks: true` in `~/.hermes/config.yaml`; visible as headers, dividers, nested lists and native tables in agent replies.
- **What it does:** Renders the final agent message as structured Block Kit blocks — section headers, dividers, true nested lists via `rich_text`, and native Block Kit tables — instead of flat mrkdwn.
- **How it works:** `plugins/platforms/slack/block_kit.py` — a pure function `render_blocks(text, mrkdwn_fn=…)` at `block_kit.py:368`. Hard limits transcribed at `block_kit.py:35`: `MAX_BLOCKS = 50`, `MAX_SECTION_TEXT = 3000`, `MAX_HEADER_TEXT = 150`, `MAX_TABLE_ROWS = 100`, `MAX_TABLE_COLS = 20`, `MAX_TABLE_CHARS = 10000` (aggregate across all cells). Line classifiers: `_HR_RE` `^\s{0,3}([-*_])(?:\s*\1){2,}\s*$`, `_HEADER_RE` `^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$`, `_FENCE_RE` `^\s*(`{3,}|~{3,})(.*)$`, `_ORDERED_RE` `^(\s*)(\d+)[.)]\s+(.*)$`, `_BULLET_RE` `^(\s*)[-*+]\s+(.*)$`, `_QUOTE_RE` `^\s{0,3}>\s?(.*)$`, `_TABLE_SEP_RE` `^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$`. Inline: `_INLINE_CODE_RE`, `_LINK_RE`, `_BOLD_RE`, `_ITALIC_RE`, `_STRIKE_RE`. Block builders: `_header_block`, `_divider_block`, `_preformatted_block`, `_quote_block`, `_list_block`, `_section_block`, `_table_block`, `_render_table`, `_split_text`, `_clamp_text_obj`, `sanitize_blocks`. Selected by `_maybe_blocks()` at `plugins/platforms/slack/adapter.py:4253`, which prefers `markdown_blocks` (Slack's native `markdown` block, raw standard markdown) over the local renderer.
- **Inputs / options:** `platforms.slack.extra.rich_blocks` (bool, default `false`); `platforms.slack.extra.markdown_blocks` (Slack-native `markdown` block, takes precedence — `_markdown_blocks_enabled()` at `:4171`, payload built by `_markdown_block_payload()` at `:4199`).
- **Outputs / side effects:** Messages sent with `blocks=` **plus** a plain-text `text=` fallback (always, for notifications/screen readers/old clients).
- **Config / env:** `platforms.slack.extra.rich_blocks`, `platforms.slack.extra.markdown_blocks`, `platforms.slack.extra.feedback_buttons`.
- **Edge cases / guards:** `render_blocks` never raises — any unexpected input returns `None` and the caller uses plain text. A table over Slack's limits or that will not parse falls back to aligned monospace `rich_text_preformatted`. Block-payload rejections are detected by `_is_block_payload_rejection()` (`:4132`) and retried as plain text. No app reinstall is required — this is a send-side change only.
- **Rebuild notes:** A markdown→Block Kit compiler with hard caps and a total-failure escape hatch; always pair `blocks` with `text`. A better version would stream Block Kit incrementally instead of only on finalize.

### Slack mrkdwn formatting & table alignment  `id: platforms-a.slack-mrkdwn`
- **Surface:** Platform:slack
- **Where:** Every plain-text agent reply.
- **What it does:** Translates standard markdown to Slack's mrkdwn dialect and turns GFM pipe tables into column-aligned monospace blocks.
- **How it works:** `format_message()` at `plugins/platforms/slack/adapter.py:4285`. Order: (1) `_wrap_markdown_tables()` (`:258`) detects pipe tables via `_is_table_row` (`:203`) and `_align_table` (`:230`) using CJK-aware display width `_disp_width` (`:209`) and `_pad` (`:214`), wrapping them in ``` fences; (2) protected regions (fenced + inline code) are extracted so their contents are never rewritten; (3) headers/bold/italic/links are converted to mrkdwn; (4) broadcast mentions are escaped **before** entity protection so model output cannot trigger `@here`/`@channel` notifications by default. Inbound direction: `_extract_text_from_slack_blocks` (`:524`), `_extract_text_from_slack_attachments` (`:598`), `_render_slack_inline_element` (`:484`), `_unescape_slack_entities` (`:668`), `_serialize_slack_blocks_for_agent` (`:753`, capped at `max_chars=6000` with the suffix `\n... [truncated]`), `_extract_urls_from_slack_blocks` (`:830`), `_normalize_slack_text_for_dedupe` (`:681`), `_render_message_text` (`:7931`).
- **Inputs / options:** n/a (always on).
- **Outputs / side effects:** mrkdwn text sent as the `text` field.
- **Config / env:** `platforms.slack.extra.rich_blocks` bypasses the flat path for the final message but `format_message` is still used as the fallback and as `mrkdwn_fn` inside the renderer.
- **Edge cases / guards:** Markdown parsing silently truncates on unbalanced markup, hence the protected-region extraction. Slack renders `*bold*` (single asterisk) and `_italic_`, unlike GFM.
- **Rebuild notes:** Protect code spans, then regex-translate the remaining markdown; align pipe tables with wcwidth. A better version would emit `rich_text` for inline formatting so links keep their labels without mrkdwn escaping quirks.

### Slack working-state status line (`typing_status_text`)  `id: platforms-a.slack-status-line`
- **Surface:** Platform:slack
- **Where:** Footer beneath the reply composer — "*BotName* is thinking…".
- **What it does:** Shows a status line next to the bot name while the agent works, customizable per platform.
- **How it works:** `send_typing()`/status refresh at `plugins/platforms/slack/adapter.py:3587` calls `assistant.threads.setStatus` with the resolved status. Priority: per-chat live-status phrase (`self._status_text[chat_id]`) → `config.typing_status_text` → heartbeat/default. Heartbeat: once a turn has run ≥ 30 s the default becomes `still working… ({m}m{ss}s)` or `still working… ({s}s)`; below 30 s it is `is thinking...`. State is tracked in `_active_status_threads` keyed `(team_id, channel_id, thread_ts)` with `{"thread_ts", "team_id", "started"}`; the start time survives refreshes so elapsed time is monotonic. Eviction is oldest-thread-ts-first above `_ACTIVE_STATUS_THREADS_MAX`. `stop_typing()` at `:3688` clears it.
- **Inputs / options:** `platforms.slack.typing_status_text` (default `"is thinking..."`), `platforms.slack.typing_indicator: false` disables it entirely.
- **Outputs / side effects:** A Slack status line; auto-clears when the bot replies to the thread.
- **Config / env:** `platforms.slack.typing_status_text`, `platforms.slack.typing_indicator`. The same key name governs Google Chat (`platforms.google_chat.typing_status_text`, default `"Hermes is thinking…"`) but there it is a real posted message.
- **Edge cases / guards:** Requires the `assistant:write` scope — without it the call fails silently (`logger.debug("[Slack] assistant.threads.setStatus failed: %s", e)`) and Slack shows its own rotating placeholders ("Finding answers…", "Reviewing findings…") which Hermes cannot control. Status can only be set in a thread context — `if not thread_ts: return`. Suppressed entirely in ignored channels with `[Slack] Suppressed typing/status in configured ignored channel %s`.
- **Rebuild notes:** Call `assistant.threads.setStatus` on the reply thread and clear on finalize. A better version would degrade to a placeholder message edit when the scope is absent, so the user still sees progress.

### Slack live per-tool status (`display.live_status`)  `id: platforms-a.slack-live-status`
- **Surface:** Config (Platform:slack)
- **Where:** Same footer status line; shows what the agent is doing right now — "is running pytest tests/…", "is reading docs/api.md…", "is searching the web for slack api limits…".
- **What it does:** Replaces the static status text with a live verb+argument phrase per tool call, reverting to the static text between calls.
- **How it works:** The gateway feeds per-tool phrases into `self._status_text[chat_id]`, consumed by the status path at `plugins/platforms/slack/adapter.py:3665`; enabled by `supports_status_text = True` (`:1125`). It rides the existing status-refresh cadence, so it costs no extra Slack API calls.
- **Inputs / options:** `display.live_status` values: `full` (default — verb + argument preview), `verb` (verb only, hides commands/paths — for shared or customer-facing channels), `off` (static text). Settable globally (`display.live_status`) or per platform (`display.platforms.slack.live_status`).
- **Outputs / side effects:** Ephemeral status text only — nothing is left in the channel.
- **Config / env:** `display.live_status`, `display.platforms.slack.live_status`.
- **Edge cases / guards:** Requires the `assistant:write` scope, same as the static line. Works even with `tool_progress: off` (Slack's default).
- **Rebuild notes:** Push tool-start/tool-end phrases into the status setter. A better version would redact secrets in the argument preview rather than relying on the coarse `verb` mode.

### Slack native streaming (live-typing replies)  `id: platforms-a.slack-native-streaming`
- **Surface:** Platform:slack
- **Where:** Any streaming-enabled reply — the message types itself out live.
- **What it does:** Uses Slack's Agents & AI Apps streaming surface (`chat.startStream` / `chat.appendStream` / `chat.stopStream`) so the reply renders as live typing instead of edit-based progressive updates.
- **How it works:** `supports_draft_streaming()` at `plugins/platforms/slack/adapter.py:3358` returns `self._app is not None` unless `self._native_stream_unsupported` is latched or unfurl controls are configured. `send_draft()` at `:3381` starts the stream on the first frame for a `(chat, draft_id)` and appends only deltas thereafter (the API is append-only); `_strip_stream_cursor()` (`:3373`) removes the consumer's trailing cursor glyph (`_STREAM_CURSOR_GLYPHS`). The streamed message **is** the final message — it is sealed with `chat.stopStream` rather than duplicated by a final post; opt-in Block Kit is applied to the sealed message.
- **Inputs / options:** `streaming.enabled: true` with transport `auto` or `draft`. No Slack-specific configuration.
- **Outputs / side effects:** One live-typing message per turn.
- **Config / env:** `streaming.enabled`, `streaming.transport`, `display.platforms.slack.streaming` (default `false`).
- **Edge cases / guards:** If the Slack app lacks AI features or the `assistant:write` scope, the first failure is cached in `_native_stream_unsupported` and Hermes falls back to edit-based streaming with a single log warning naming the fix. Explicitly configured `unfurl_links` / `unfurl_media` force the edit-based transport because the `chat.*Stream` contract has no unfurl controls (`_slack_unfurl_kwargs` at `:82`).
- **Rebuild notes:** Start/append/stop with monotonic accumulation and a one-shot capability latch. A better version would negotiate the capability at connect (`apps.manifest` / a probe call) instead of latching on the first live failure.

### Slack native task cards (live tool progress)  `id: platforms-a.slack-native-task-cards`
- **Surface:** Config (Platform:slack)
- **Where:** `platforms.slack.extra.native_task_cards: true`; renders one Slack plan/task card per turn with one row per tool call.
- **What it does:** Shows live tool calls as Slack-native plan/task cards (the same UI Slack's own AI features use) with per-task running/complete/error states updating in place.
- **How it works:** `native_task_cards_enabled()` at `plugins/platforms/slack/adapter.py:2749` (also accepts the camelCase alias `nativeTaskCards` and the nested form `platforms.slack.extra.streaming.progress.native_task_cards`). `send_native_task_card_progress()` at `:2780` keys a `_NativeTaskCardStream` (`:349`) by `(team_id, channel_id, thread_ts)` via `_native_task_card_key()` (`:2767`), guards with an `asyncio.Lock`, and starts the stream with `{"channel", "thread_ts", "task_display_mode": "plan"}` plus optional `recipient_team_id` / `recipient_user_id` pulled from metadata. Card title default: `"Hermes is working"`.
- **Inputs / options:** `platforms.slack.extra.native_task_cards` (bool, default `false`); `title` (default `"Hermes is working"`), `tasks` (list of `{…}` rows), `reply_to`, `metadata`, `fallback_text`.
- **Outputs / side effects:** One live card per thread per turn; stopped exactly once at finalize, including on interrupt/disconnect, so no dangling live indicator is left behind.
- **Config / env:** `platforms.slack.extra.native_task_cards`; independent of `tool_progress`.
- **Edge cases / guards:** Returns `SendResult(success=False, error="Not connected")` with no app, `"No tasks"` for an empty list, `"No Slack thread target"` when no thread ts can be resolved, `"Progress stream already stopped"` on a stopped stream. If the native stream cannot start or update, Hermes falls back to a single continuously edited text message. Concurrent calls to the same tool are correlated by real tool-call ID so parallel `web_search` calls each get their own row.
- **Rebuild notes:** One stream object per thread with a lock and a `stopped` flag; correlate rows by tool-call id. A better version would surface per-task durations and let the user cancel a running task from the card.

### Slack Agent view / suggested prompts  `id: platforms-a.slack-suggested-prompts`
- **Surface:** Config (Platform:slack)
- **Where:** Pinned at the top of the Agent view's Messages tab in a DM with the bot.
- **What it does:** Offers up to four one-tap starter prompts when a user opens the bot's DM.
- **How it works:** `_assistant_suggested_prompts()` at `plugins/platforms/slack/adapter.py:5256` accepts either `[{title, message}, …]` or `{title: "...", prompts: [{title, message}, …]}`; each title is clipped to 75 chars, invalid rows are ignored, and the list is hard-capped at 4. `_set_assistant_suggested_prompts()` (`:5289`) calls `assistant.threads.setSuggestedPrompts` with `channel_id`, `prompts`, optional `title`, optional `thread_ts`. Triggered from the Agent-view lifecycle (`app_home_opened` with `tab == "messages"` → `_seed_agent_dm_session`, `:5410`) and the Assistant-view lifecycle (`assistant_thread_started`).
- **Inputs / options:** `platforms.slack.extra.suggested_prompts` (default `[]`).
- **Outputs / side effects:** Prompt chips appear in the DM; failures are swallowed at DEBUG (`[Slack] assistant.threads.setSuggestedPrompts failed: %s`).
- **Config / env:** `platforms.slack.extra.suggested_prompts`.
- **Edge cases / guards:** No prompts → no API call. `app_home_opened` is only a lifecycle signal — no welcome message is sent and the agent loop is **not** entered from it.
- **Rebuild notes:** Validate and cap the list, then set it on the DM open event. A better version would rotate prompts based on recent usage or the workspace's installed skills.

### Slack Agent/Assistant thread titles  `id: platforms-a.slack-thread-titles`
- **Surface:** Config (Platform:slack)
- **Where:** The thread name shown in Slack's Agent/Assistant DM sidebar.
- **What it does:** Names each Agent/Assistant DM thread after the first user message.
- **How it works:** `_assistant_thread_title_enabled()` at `plugins/platforms/slack/adapter.py:5320` (default `True`; falsy strings `0`, `false`, `no`, `off`). `_set_assistant_thread_title()` (`:5326`) normalizes whitespace, skips titles starting with `/` (commands), clips to 80 chars with `title[:77].rstrip() + "..."`, and calls `assistant.threads.setTitle`. Titled threads are remembered in `_titled_assistant_threads` (workspace-scoped key `(team_id, channel_id, thread_ts)`) and evicted oldest-thread-ts-first above `_TITLED_ASSISTANT_THREADS_MAX`.
- **Inputs / options:** `platforms.slack.extra.assistant_thread_titles` (default `true`).
- **Outputs / side effects:** One `assistant.threads.setTitle` call per thread, at most once.
- **Config / env:** `platforms.slack.extra.assistant_thread_titles`.
- **Edge cases / guards:** Failure is logged at DEBUG (`[Slack] assistant.threads.setTitle failed: %s`) and the guard set is **not** updated, so a later message can retry.
- **Rebuild notes:** Title once from the first non-command message. A better version would re-title after a few turns using a model-generated summary.

### Slack Agent view context (`app_context_changed`)  `id: platforms-a.slack-agent-context`
- **Surface:** Platform:slack
- **Where:** Invisible — Slack tells Hermes which channel the user is currently viewing while chatting in the Agent DM.
- **What it does:** Supplies the user's active Slack context to the turn as a label so the agent knows what the user is looking at.
- **How it works:** `@self._app.event("app_context_changed")` (`plugins/platforms/slack/adapter.py:2232`) → `_handle_app_context_changed`; context is cached by `_cache_agent_view_context()` (`:5058`) keyed `_agent_view_context_key(team_id, user_id)` (`:5052`) and read back per event by `_agent_view_context_for_event()` (`:5081`). Assistant-view equivalents: `_extract_assistant_thread_metadata()` (`:5160`), `_cache_assistant_thread_metadata()` (`:5203`), `_lookup_assistant_thread_metadata()` (`:5226`). The value lands on the session source as `chat_topic` / `context_channel_id` (`:5399`).
- **Inputs / options:** n/a (Slack-driven).
- **Outputs / side effects:** Session metadata only.
- **Config / env:** Requires the Agent-view manifest (`hermes slack manifest --agent-view`).
- **Edge cases / guards:** Doc statement verbatim: "Hermes only supplies that context as a label; it does not read the viewed channel's history."
- **Rebuild notes:** Cache `(team, user) → context_channel_id` and attach it to the session source. A better version would offer to pull the viewed channel's recent history on explicit user consent.

### Slack mention & trigger gating (six composable options)  `id: platforms-a.slack-mention-gating`
- **Surface:** Config (Platform:slack)
- **Where:** `slack:` block in `~/.hermes/config.yaml`, or the matching `SLACK_*` env vars.
- **What it does:** Decides which Slack messages wake the agent, composing six independent gates over channels, threads and group DMs.
- **How it works:** `_slack_require_mention()` at `plugins/platforms/slack/adapter.py:9051` (explicit-false parsing: unrecognised/empty keeps gating **on**); `_slack_strict_mention()` (`:9070`, truthy parsing); `_slack_ignore_other_user_mentions()` (`:9087`); `_slack_thread_require_mention()` (`:9110`); `_slack_free_response_channels()` (`:9162`, list or CSV, non-list scalars coerced with `str()`); `_slack_require_mention_channels()` (`:9211`); `_slack_allowed_channels()` (`:9194`); `_slack_disable_dms()` (`:9180`); `_slack_message_addressed_to_other_user()` (`:9131`, regex `^\s*<@([^>|\s]+)(?:\|[^>]*)?>` — only a **leading** mention counts); `_slack_message_mentions_self()` (`:9147`, matches both `<@U123>` and `<@U123|name>`); `_slack_mention_patterns()` (`:9230`) + `_slack_message_matches_mention_patterns()` (`:9278`). YAML→env translation in `_apply_yaml_config()` (`:9801`), guarded by `not os.getenv(...)` so explicit env vars always win.
- **Inputs / options:** Complete option table (question / default / scope, verbatim from the docs):
  - `require_mention` — "Do **top-level channel messages** need an @mention?" — default `true` — all channels — env `SLACK_REQUIRE_MENTION`.
  - `free_response_channels` — "Which channels are exempt from `require_mention`?" — default none — listed channels — env `SLACK_FREE_RESPONSE_CHANNELS`.
  - `require_mention_channels` — "Which channels ALWAYS need an @mention, even when `require_mention` is `false` or the channel is free-response? Wins over both." — default none — env `SLACK_REQUIRE_MENTION_CHANNELS`.
  - `thread_require_mention` — "Do **thread replies** need an @mention, even when top-level messages don't? Mentioned threads are not remembered." — default `false` — threads only — env `SLACK_THREAD_REQUIRE_MENTION`.
  - `strict_mention` — "Does **every** channel message (top-level and thread) need a fresh @mention? Disables all auto-follow: mentioned-thread memory, bot-reply follow-ups, active-session resume." — default `false` — all channels + threads — env `SLACK_STRICT_MENTION`.
  - `ignore_other_user_mentions` — "Should a message that **opens by @mentioning someone else** (`@rasha can you take this?`) be skipped? Overrides free-response and thread auto-follow; mid-sentence references still reach the bot." — default `false` — channels + group DMs — env `SLACK_IGNORE_OTHER_USER_MENTIONS`.
  - `mention_patterns` — regex wake words (e.g. `- "hey hermes"`, `- "hermes,"`), accepted as a YAML list, a single string, or `SLACK_MENTION_PATTERNS` as a JSON list or newline/comma-separated values; compiled with `re.IGNORECASE` and cached on the instance.
  - `reply_prefix` — "Text prepended to every outgoing message" (default `""`).
- **Outputs / side effects:** Messages are either dispatched or silently dropped.
- **Config / env:** `slack.require_mention`, `slack.strict_mention`, `slack.ignore_other_user_mentions`, `slack.thread_require_mention`, `slack.free_response_channels`, `slack.require_mention_channels`, `slack.mention_patterns`, `slack.reply_prefix` + the `SLACK_*` equivalents.
- **Edge cases / guards:** 1:1 DMs always respond and are unaffected by all of these. Group DMs (MPIMs, IDs starting with `G`) are shared surfaces and obey channel rules — including `allowed_channels` — and get `:eyes:`/`:white_check_mark:` reactions only when actually `@mentioned`. Broadcast tokens (`@here`, `@channel`) and channel references (`<#C…>`) address the room, not a person, so `ignore_other_user_mentions` never skips them. Invalid regexes log `[Slack] Invalid mention pattern %r: %s`; a non-list/str value logs `[Slack] mention_patterns must be a list or string; got %s`; a successful load logs `[Slack] Loaded %d mention pattern(s)`.
- **Rebuild notes:** Model each gate as a pure predicate over (channel type, thread state, text, bot uids) and run them in a fixed order: allowlist → ignored → DM policy → addressed-to-other → per-channel force-mention → free-response → mention/pattern → thread auto-follow. A better version would expose a `/why` command that explains why a given message was or wasn't answered.

### Slack channel allowlist (`allowed_channels`)  `id: platforms-a.slack-allowed-channels`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.allowed_channels` (YAML list) or `SLACK_ALLOWED_CHANNELS` (comma-separated).
- **What it does:** Restricts the bot to a fixed set of Slack channels; messages from any other channel are silently ignored even when the bot is `@mentioned`.
- **How it works:** `_slack_allowed_channels()` at `plugins/platforms/slack/adapter.py:9194` returns a set from a list or CSV. The check runs **before** any other gating (mention requirement, `free_response_channels`).
- **Inputs / options:** Channel IDs — `C…` (public), `G…` (private/MPIM), `D…` (DM). Empty/unset means no restriction.
- **Outputs / side effects:** Non-listed channels drop messages before session lookup.
- **Config / env:** `slack.allowed_channels`, `SLACK_ALLOWED_CHANNELS`.
- **Edge cases / guards:** **1:1 DMs are exempt** so authorized users can always reach the bot. **Group DMs (MPIMs) are not exempt** — an MPIM must be listed by its `G…` ID. Look IDs up via "Open channel details" → "About".
- **Rebuild notes:** A set membership test at the top of the admission chain. A better version would accept channel *names* and resolve them once at connect.

### Slack ignored-channels blacklist  `id: platforms-a.slack-ignored-channels`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.ignored_channels` / `SLACK_IGNORED_CHANNELS`.
- **What it does:** Blacklists channels where the bot must never respond, never react and never show a status line.
- **How it works:** `_slack_ignored_channels()` at `plugins/platforms/slack/adapter.py:2716` (cached set) and `_is_ignored_channel()` at `:2727`. Enforced in the message path, the file-share fallback (`[Slack] Ignoring file_shared event in configured ignored channel %s`), `send_typing` (`[Slack] Suppressed typing/status in configured ignored channel %s`) and `stop_typing` (`[Slack] Suppressed status clear in configured ignored channel %s`).
- **Inputs / options:** YAML list or comma-separated channel IDs.
- **Outputs / side effects:** Complete silence in the listed channels.
- **Config / env:** `slack.ignored_channels`, `SLACK_IGNORED_CHANNELS`.
- **Edge cases / guards:** The blacklist wins over `free_response_channels` and over an explicit mention.
- **Rebuild notes:** A second set test alongside the allowlist. A better version would also suppress outbound cron/notification delivery to those channels.

### Slack DM disable (`disable_dms`)  `id: platforms-a.slack-disable-dms`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.disable_dms` / `SLACK_DISABLE_DMS`.
- **What it does:** Makes the bot ignore all incoming 1:1 DMs, leaving only channel surfaces active.
- **How it works:** `_slack_disable_dms()` at `plugins/platforms/slack/adapter.py:9180`; truthy strings `true`, `1`, `yes`, `on`. Default `False` for backward compatibility.
- **Inputs / options:** boolean (config or env).
- **Outputs / side effects:** DM events dropped.
- **Config / env:** `slack.disable_dms`, `SLACK_DISABLE_DMS`.
- **Edge cases / guards:** Independent of `allowed_channels`, which never filters 1:1 DMs.
- **Rebuild notes:** One boolean checked on `channel_type == "im"`. A better version would post a one-time "DMs are disabled, use #channel" ephemeral instead of silence.

### Slack `allow_bots` — accepting messages from other bots  `id: platforms-a.slack-allow-bots`
- **Surface:** Config (Platform:slack)
- **Where:** `platforms.slack.extra.allow_bots` or `SLACK_ALLOW_BOTS`.
- **What it does:** Controls whether messages authored by other Slack bots/apps (including Workflow Builder posts) reach the agent — the switch that makes multi-agent workspaces possible without ack/status loops.
- **How it works:** `_slack_allow_bots()` at `plugins/platforms/slack/adapter.py:3830` normalizes the value; `_event_declares_bot_sender()` at `:3841` detects labeled bot messages (`bot_id`, `subtype: bot_message`) and app-originated events; unlabeled bot *users* are probed via `users.info` in `_resolve_user_is_bot()` (`:4697`, workspace-scoped cache `(team_id, user_id)`, checks `is_bot`, `is_workflow_bot`, `profile.bot_id`).
- **Inputs / options:** Exactly three values — `"none"` (default; ignore all bot/app-authored messages), `"mentions"` (accept a bot message only when **that message itself** @mentions this bot, in its text or its Block Kit blocks — checked by `_collect_slack_block_mentions()` at `:388` and `_slack_mention_detection_text()` at `:427`), `"all"` (accept every bot message except the bot's own). Unknown values are treated as `none`. The config key wins when both config and env are set.
- **Outputs / side effects:** Admits or drops peer-bot turns.
- **Config / env:** `platforms.slack.extra.allow_bots`, `SLACK_ALLOW_BOTS`.
- **Edge cases / guards:** In `mentions` mode thread history does **not** count — a bot mentioned earlier in a thread, replies to the bot's own messages, and active thread sessions do **not** admit later unmentioned peer-bot messages; this is what breaks agent-to-agent loops. Hermes always ignores its own bot user in every mode. Human messages are unaffected. Avoid `all` unless every peer bot's own reply policy is loop-safe.
- **Rebuild notes:** Three-valued enum evaluated per message against a fresh mention check, never against thread state. A better version would add a per-turn budget so even `all` cannot loop indefinitely.

### Slack peer-agent smoke check  `id: platforms-a.slack-peer-smoke`
- **Surface:** CLI / Docs
- **Where:** `uv run --frozen pytest -q tests/gateway/test_slack_peer_agent_smoke.py -o addopts=''`
- **What it does:** Verifies the multi-bot routing profile (`require_mention: true`, `strict_mention: true`, `allow_bots: mentions`, `allowed_channels: ""`) still holds after config changes, deploys or restarts.
- **How it works:** In-process synthetic Slack events only — no live Slack messages, no real bot tokens required by default. Documented at `website/docs/user-guide/messaging/slack.md:748`.
- **Inputs / options:** n/a (a pytest target).
- **Outputs / side effects:** Pass/fail with named failure buckets.
- **Config / env:** the four profile keys above.
- **Edge cases / guards:** Failure buckets, verbatim: `config:` — "`test_peer_agent_smoke_preflight_contract` caught a profile mismatch (`require_mention`, `strict_mention`, `allow_bots`, or `allowed_channels`)"; `platform_connectivity:` — "the adapter/client was not initialized, so routing smoke is not a trustworthy signal yet"; `bot_identity:` — "the adapter never resolved its bot user ID, so current-message mention checks cannot work"; `routing_logic:` — "the Slack adapter regressed on one of the peer-agent invariants (human mention routing, peer-bot ignore, explicit peer mention admit, or passive ack/status/error suppression)". If the target passes but a live workspace still misroutes, investigate token/workspace connectivity outside the routing logic.
- **Rebuild notes:** Assert the config contract first, then replay synthetic events through the admission chain. A better version would ship the same checks as a `hermes gateway doctor --slack` runtime command.

### Slack reaction triggers  `id: platforms-a.slack-reaction-triggers`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.reaction_triggers` / `SLACK_REACTION_TRIGGERS`; optional handoff target `slack.reaction_trigger_target` / `SLACK_REACTION_TRIGGER_TARGET`.
- **What it does:** Routes emoji reactions into the agent loop as real turns, so "react 👍 to proceed" workflows and emoji handoffs work end-to-end.
- **How it works:** `_handle_slack_reaction()` at `plugins/platforms/slack/adapter.py:5531` synthesizes a message event with text `reaction:added:<emoji>` / `reaction:removed:<emoji>`, the reactor as `user`, the reacted-to message's `thread_ts`, `_hermes_force_process: True` (skips the mention requirement), `_hermes_reaction: {name, action, reacted_to_ts, event_ts}`, and the reaction's own `event_ts` as the synthetic ts (so dedup treats it as a distinct event). `_slack_reaction_triggers()` at `:5717` returns `None` (disabled), an **empty set** (all emoji, bot's own messages only) or a **non-empty set** (exactly these emoji names, on any message). `_slack_reaction_trigger_target()` at `:5748` parses `C123` or `C123:<thread_ts>`. Emoji translation map `_REACTION_EMOJI_MAP` at `:5513`: `thumbsup`→👍, `+1`→👍, `thumbsdown`→👎, `-1`→👎, `white_check_mark`→✅, `heavy_check_mark`→✅, `x`→❌, `no_entry`→⛔, `warning`→⚠️, `rotating_light`→🚨, `eyes`→👀, `rocket`→🚀, `tada`→🎉, `fire`→🔥, `wave`→👋. Unknown names pass through as-is (e.g. `reaction:added:custom-emoji`).
- **Inputs / options:** `reaction_triggers`: `false`/absent (default, acked and dropped), `true`/`all`/`*`/`1`/`yes`/`on` (all emoji, own messages only), or an explicit emoji-name list (e.g. `[white_check_mark, thumbsup, task]`, or a comma/whitespace-separated string in the env var). `reaction_trigger_target`: `C0123456789` (respond top-level in that channel) or `C0123456789:1710000000.000100` (respond in that thread).
- **Outputs / side effects:** A normal agent turn threaded under the reacted-to message, or in the configured handoff target. With a channel-only target the turn is top-level there (`_hermes_no_thread_response: True`) and the source channel is recorded as `_hermes_reaction_source_channel`.
- **Config / env:** `slack.reaction_triggers`, `slack.reaction_trigger_target`, `SLACK_REACTION_TRIGGERS`, `SLACK_REACTION_TRIGGER_TARGET`. Requires the `reactions:read` scope and the `reaction_added`/`reaction_removed` bot events (regenerate the manifest with `hermes slack manifest`).
- **Edge cases / guards:** Self-reactions (the bot's own `:eyes:` lifecycle marker) are dropped to prevent feedback loops. File-targeted reactions are ignored — only `item.type == "message"` is forwarded. Without an explicit allowlist, reactions on messages **not sent by this bot** are dropped (verified via `item_user` or a `conversations.replies` lookup). The reactor becomes the message's user so `_is_user_authorized` and `allowed_channels` apply exactly as for typed messages. Independently of the opt-in, every non-self reaction on a message item fires the gateway hooks `reaction:added` / `reaction:removed` with payload `{platform, event_name, reaction, user_id, item_user_id, item_type, channel_id, message_ts, team_id, event_ts, raw_event}`.
- **Rebuild notes:** Synthesize a message event from the reaction and reuse the whole admission chain. A better version would let the operator map specific emoji to specific skills or commands rather than to a generic text turn.

### Slack lifecycle reactions (`:eyes:` / `:white_check_mark:`)  `id: platforms-a.slack-lifecycle-reactions`
- **Surface:** Platform:slack
- **Where:** On the user's own message: 👀 while the agent works, ✅ when it finishes.
- **What it does:** Marks message processing state with reactions when the status line is unavailable.
- **How it works:** `_reactions_enabled()` at `plugins/platforms/slack/adapter.py:4477`; `_add_reaction(channel_id, ts, "white_check_mark", team_id)` at `:4511`.
- **Inputs / options:** `slack.reactions` / `SLACK_REACTIONS` (boolean).
- **Outputs / side effects:** `reactions.add` calls on the inbound message.
- **Config / env:** `slack.reactions`, `SLACK_REACTIONS`.
- **Edge cases / guards:** In group DMs (MPIMs) the bot only adds them when it is actually `@mentioned`. The bot's own reactions never feed back into reaction triggers.
- **Rebuild notes:** Add on admission, replace on completion. A better version would add a third marker for errored turns.

### Slack thread & reply behaviour  `id: platforms-a.slack-threading`
- **Surface:** Config (Platform:slack)
- **Where:** `platforms.slack.reply_to_mode` and `platforms.slack.extra.reply_in_thread` / `reply_broadcast`.
- **What it does:** Controls whether replies open a thread, whether every chunk threads, and whether thread replies are also broadcast to the channel.
- **How it works:** `_resolve_thread_ts()` at `plugins/platforms/slack/adapter.py:3858` decides the thread ts for a send; with `reply_in_thread: false` it returns `None` for top-level channel messages, which also switches the inbound session bucket to `(platform, channel_id, None)` (whole-channel), enabling `supports_inchannel_continuable`. Thread session keys are built by `_build_thread_session_key()` (`:8608`); watermarks by `_thread_watermark_key()` (`:8669`), `_get_thread_watermark()` (`:8719`), `_set_thread_watermark()` (`:8745`); rehydration by `_thread_rehydration_key()` (`:8672`) and `_mark_thread_rehydration_checked()` (`:8690`); active-session detection by `_has_active_session_for_thread()` (`:8779`). Thread context is cached in `_ThreadContextCache` (`:317`).
- **Inputs / options:**
  - `platforms.slack.reply_to_mode` — `"off"` ("never thread replies to the original message"), `"first"` (default — "first chunk threads to user's message"), `"all"` ("all chunks thread to user's message").
  - `platforms.slack.extra.reply_in_thread` — default `true`; when `false`, channel messages get direct channel replies. "Messages inside existing threads still reply in-thread."
  - `platforms.slack.extra.reply_broadcast` — default `false`; Slack's "Also send to channel". "Only the first chunk of the first reply is broadcast."
  - `platforms.slack.extra.cron_continuable_surface` — `"thread"` (default) or `"in_channel"`; resolved by `_cron_continuable_surface()` at `:3774`.
- **Outputs / side effects:** `chat.postMessage` with or without `thread_ts` / `reply_broadcast`.
- **Config / env:** the four keys above.
- **Edge cases / guards:** `_warn_if_inchannel_without_flat_reply()` at `:3793` warns at connect when `cron_continuable_surface: in_channel` is set without `reply_in_thread: false`. DM top-level threads can be treated as separate sessions — `_dm_top_level_threads_as_sessions()` at `:3760`.
- **Rebuild notes:** One `_resolve_thread_ts` function consulted by every send path, plus a matching inbound session-key rule so the two halves cannot drift. A better version would let `reply_to_mode` be set per channel.

### Slack link/media unfurl control  `id: platforms-a.slack-unfurl`
- **Surface:** Config (Platform:slack)
- **Where:** `platforms.slack.extra.unfurl_links` / `platforms.slack.extra.unfurl_media`.
- **What it does:** Suppresses Slack's automatic link-preview and media-preview cards without changing or removing clickable links from the message text.
- **How it works:** `_slack_unfurl_kwargs()` at `plugins/platforms/slack/adapter.py:82` returns only the keys explicitly configured, so omitting either key keeps Slack's default for that preview type; the resulting kwargs ride on `chat.postMessage`.
- **Inputs / options:** `unfurl_links: false`, `unfurl_media: false` (either or both; omit to keep Slack's default).
- **Outputs / side effects:** Preview cards suppressed.
- **Config / env:** `platforms.slack.extra.unfurl_links`, `platforms.slack.extra.unfurl_media`.
- **Edge cases / guards:** When **either** unfurl key is set: media captions are posted as a separate message *before* the file (Slack's upload API cannot carry unfurl controls), and native draft streaming falls back to edit-based delivery (`supports_draft_streaming()` returns `False`, `:3358`).
- **Rebuild notes:** Emit unfurl kwargs only when explicitly configured — a tri-state, not a boolean. A better version would apply unfurl controls to the upload path via a follow-up `chat.update`.

### Slack multi-workspace support  `id: platforms-a.slack-multiworkspace`
- **Surface:** Config (Platform:slack)
- **Where:** `SLACK_BOT_TOKEN=xoxb-a,xoxb-b,xoxb-c` or `platforms.slack.token: "xoxb-a,xoxb-b"`; plus `~/.hermes/slack_tokens.json`.
- **What it does:** Connects one gateway to several Slack workspaces at once, each authenticated with its own bot user ID.
- **How it works:** Each token is authenticated via `auth.test` at connect (`plugins/platforms/slack/adapter.py:2160`ff), logging `[Slack] Authenticated as @%s in workspace %s (team: %s)`. The gateway maps `team_id → AsyncWebClient` (`self._team_clients`) and `team_id → bot_user_id` (`self._team_bot_user_ids`) / `team_id → bot name` (`self._team_bot_names`). `_get_client(chat_id, team_id)` at `:2641` picks the right client; `_remember_channel_team()` (`:1410`) caches `channel_id → team_id`; `_event_team_id()` (`:5118`) and `_metadata_team_id()` (`:2588`) resolve the team from an event/metadata; `_workspace_event_id()` (`:2618`), `_workspace_message_marker()` (`:2623`) and `_workspace_thread_key()` (`:5038`) namespace all per-message state by team so identical Slack-local ids in two workspaces never collide. `scope_id_for_chat()` (`:2627`) exposes the team as the session scope.
- **Inputs / options:** Comma-separated tokens in `SLACK_BOT_TOKEN` or `platforms.slack.token`; a single `SLACK_APP_TOKEN` for Socket Mode. OAuth token file `~/.hermes/slack_tokens.json` — a JSON object mapping team IDs to `{"token": "xoxb-…", "team_name": "My Workspace"}`; merged with env tokens and deduplicated.
- **Outputs / side effects:** One Socket Mode connection (from the **first**/primary token) plus N Web API clients.
- **Config / env:** `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `platforms.slack.token`, `~/.hermes/slack_tokens.json`.
- **Edge cases / guards:** The primary `bot_user_id` (from the first token) is used for backward compatibility with features expecting a single bot identity. Duplicate tokens are deduplicated automatically.
- **Rebuild notes:** Keep a `team_id → client` map and key every cache by `(team_id, …)`. A better version would open one socket per workspace so a single workspace's socket failure does not affect the others.

### Slack Socket Mode connection & watchdog  `id: platforms-a.slack-socket-watchdog`
- **Surface:** Platform:slack (Core)
- **Where:** Invisible — keeps the WebSocket alive.
- **What it does:** Starts the Socket Mode handler and restarts it when the connection goes stale, so the bot does not silently stop receiving events.
- **How it works:** `_start_socket_mode_handler()` at `plugins/platforms/slack/adapter.py:1439`; staleness detected by `_socket_ping_pong_stale()` (`:1512`); watchdog wired by `_ensure_socket_watchdog()` (`:1620`) with completion callbacks `_on_socket_watchdog_done()` (`:1600`) and `_on_socket_mode_task_done()` (`:1626`). Teardown cancels the handler task plus the client's internal tasks listed in `_SOCKET_CLIENT_TASK_ATTRS` (`:912`) with `_SOCKET_TASK_CANCEL_TIMEOUT_S = 3.0` (`:920`). Bring-up is atomic: `_running` only flips to `True` after the handler is alive, and any failure tears down what started and leaves `_running = False` so the platform lock is released cleanly.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Reconnects; Slack replays un-acked events on reconnect, which the 1-hour dedup TTL absorbs.
- **Config / env:** `SLACK_DEDUP_TTL_SECONDS`.
- **Edge cases / guards:** Bolt auto-reconnects but unstable connections cause lag (doc troubleshooting row: "Socket disconnects frequently | Check your network; Bolt auto-reconnects but unstable connections cause lag").
- **Rebuild notes:** Track last ping/pong; restart the handler when the gap exceeds a threshold; dedup on reconnect. A better version would surface connection health in `hermes gateway status`.

### Slack connect-time diagnostics  `id: platforms-a.slack-connect-diagnostics`
- **Surface:** Platform:slack
- **Where:** Gateway log at startup.
- **What it does:** Detects the three misconfigurations that produce *silence* rather than an error, and warns about them at connect.
- **How it works:** `_warn_if_missing_group_dm_scopes()` at `plugins/platforms/slack/adapter.py:1912` inspects the `x-oauth-scopes` header on the `auth.test` response — a missing `message.mpim` subscription or `mpim:history` scope delivers *nothing*, so connect time is the only place it can be detected. `_warn_if_not_bot_token()` at `:1957` warns when the configured token is not a bot token. `_warn_if_inchannel_without_flat_reply()` at `:3793` warns when `cron_continuable_surface: in_channel` is configured without `reply_in_thread: false`. Runtime API failures are humanised by `_describe_slack_api_error()` (`:1658`) and download failures by `_describe_slack_download_failure()` (`:1700`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Log warnings only.
- **Config / env:** n/a.
- **Edge cases / guards:** Scope/auth/permission failures on attachments are also surfaced **in chat** so the user sees why an upload could not be read.
- **Rebuild notes:** Inspect `auth.test` headers and the configured YAML at connect; never assume silence means "working". A better version would post a one-time DM to the operator listing every missing scope/event.

### Slack voice messages (STT in / TTS out)  `id: platforms-a.slack-voice`
- **Surface:** Platform:slack
- **Where:** Slack's "record a clip" voice messages and any audio upload; TTS replies arrive as audio file attachments.
- **What it does:** Transcribes incoming voice/audio into the agent turn and can reply with synthesized audio.
- **How it works:** `_is_slack_voice_clip()` at `plugins/platforms/slack/adapter.py:1087` and `_resolve_slack_audio_ext()` at `:1061` pick a file extension that matches the *actual container bytes*, because OpenAI-family STT sniffs the container from the filename extension. Maps transcribed verbatim — `_SLACK_AUDIO_MIME_TO_EXT` (`:1017`): `audio/ogg`→`.ogg`, `audio/opus`→`.ogg`, `audio/mpeg`→`.mp3`, `audio/mp3`→`.mp3`, `audio/wav`→`.wav`, `audio/x-wav`→`.wav`, `audio/webm`→`.webm`, `audio/mp4`→`.m4a`, `audio/x-m4a`→`.m4a`, `audio/m4a`→`.m4a`, `audio/aac`→`.m4a`, `audio/flac`→`.flac`, `audio/x-flac`→`.flac`. `_SLACK_STT_SUPPORTED_EXTS` (`:1041`): `.mp3 .mp4 .mpeg .mpga .m4a .wav .webm .ogg .aac .flac`. `_SLACK_EXT_TO_AUDIO_MIME` (`:1049`) re-labels a `video/mp4`-mislabeled voice clip back onto the audio path (default `audio/mp4`).
- **Inputs / options:** n/a — automatic for audio files.
- **Outputs / side effects:** Audio cached under the media cache dir; transcript becomes the turn text; TTS replies uploaded as files.
- **Config / env:** `stt_enabled` (global, default `true`); STT providers — local `faster-whisper`, Groq Whisper (`GROQ_API_KEY`), OpenAI Whisper (`VOICE_TOOLS_OPENAI_KEY`).
- **Edge cases / guards:** Slack's in-app clips are MP4/AAC (`audio/mp4`, filename `audio_message*.mp4`), **not** Ogg — caching them as `.ogg` makes transcription fail outright. `files:read` is required to download them.
- **Rebuild notes:** Map mimetype → extension from the container, not the label, and validate the extension against the STT backend's accepted set. A better version would sniff magic bytes rather than trusting Slack's mimetype at all.

### Slack file attachments & uploads  `id: platforms-a.slack-files`
- **Surface:** Platform:slack
- **Where:** Any file dropped into a Slack message; agent replies with `MEDIA:<path>` upload as native Slack file shares.
- **What it does:** Ingests user-uploaded images/documents/audio/video into the turn, and uploads agent-produced media back as native Slack files.
- **How it works:** Inbound files arrive on the `message` event; the `file_shared` lifecycle fallback (`_handle_slack_file_shared()` at `plugins/platforms/slack/adapter.py:5786`) covers video shares that do not surface as `message.files`: it calls `files.info`, filters to `mimetype.startswith("video/")`, locates the share ts in `file_obj["shares"]`, sleeps `0.75` s to let the normal `message.file_share` event win the dedup race, then synthesizes a `file_share` message event. Download tokens are resolved by `_resolve_download_token()` (`:8870`) and Slack CDN URLs recognised by `_is_slack_cdn_url()` (`:8853`). Outbound: `send_image_file()` at `:4750` and the other send paths; uploaded files are tracked by `_record_uploaded_file_thread()` (`:4089`); retryable upload errors are classified by `_is_retryable_upload_error()` (`:4104`). File markers in agent-visible text come from `_slack_file_marker()` (`:172`).
- **Inputs / options:** `MEDIA:<path>` lines in agent output (images, PDFs, documents). A short message accompanying a single attachment rides as the file's caption instead of a separate message.
- **Outputs / side effects:** Native Slack file shares; missing files are reported **per file** as warnings rather than failing the whole send.
- **Config / env:** Requires `files:read` (inbound) and `files:write` (outbound).
- **Edge cases / guards:** With unfurl controls configured, captions are posted as a separate message *before* the file. Scope/auth/permission failures surface in chat via `_describe_slack_download_failure()` (`:1700`).
- **Rebuild notes:** Use `files.getUploadURLExternal` + `files.completeUploadExternal`; keep the `file_shared` fallback for video. A better version would stream large uploads instead of buffering.

### Slack home channel & cron delivery targeting  `id: platforms-a.slack-home-channel`
- **Surface:** Config (Platform:slack)
- **Where:** `SLACK_HOME_CHANNEL` (channel ID) / `SLACK_HOME_CHANNEL_NAME`; also settable in-chat with `/set-home`.
- **What it does:** Names the default channel for cron results, cross-platform messages and proactive notifications, and defines the three cron delivery target shapes.
- **How it works:** Registered as `cron_deliver_env_var="SLACK_HOME_CHANNEL"` (`plugins/platforms/slack/adapter.py:9914`). Bare user IDs are resolved to a DM conversation by `_ensure_dm_conversation()`; the module-level cache `_slack_dm_cache` (`:9303`) is keyed `"{token}:{user_id}"` with `_SLACK_DM_CACHE_MAX = 5000` and trimmed oldest-insertion-first by `_trim_slack_dm_cache()` (`:9307`).
- **Inputs / options:** `deliver:` values — `slack` → the home channel; `slack:C0123456789` → a specific channel by ID; `slack:U0123456789` → that user's **DM** (requires `im:write`). To find a channel ID: right-click the channel name → **View channel details** → the Channel ID is at the bottom.
- **Outputs / side effects:** Scheduled messages posted to the target; `MEDIA:` attachments in cron output upload as native Slack file shares to the same target.
- **Config / env:** `SLACK_HOME_CHANNEL`, `SLACK_HOME_CHANNEL_NAME`.
- **Edge cases / guards:** The bot must be invited to the channel (`/invite @Hermes Agent`). Delivery works even when the cron process is not co-located with the gateway — see the standalone sender below.
- **Rebuild notes:** One env var + a `platform:target` parser with user→DM resolution. A better version would validate the channel at save time and report "bot not in channel" immediately.

### Slack standalone (out-of-process) sender  `id: platforms-a.slack-standalone-send`
- **Surface:** Core (Platform:slack)
- **Where:** Invisible — used when cron or `send_message` runs outside the gateway process.
- **What it does:** Delivers a Slack message via the Web API without a live adapter, so `deliver=slack` cron jobs do not fail with "No live adapter".
- **How it works:** `_standalone_send()` at `plugins/platforms/slack/adapter.py:9401`, registered as `standalone_sender_fn` (`:9918`). Formats with the same mrkdwn helper (`_format_mrkdwn()` at `:9485`; failure logs `Failed to apply Slack mrkdwn formatting in _standalone_send`), resolves bare user IDs to DMs via `_slack_dm_cache`, and posts with `SLACK_BOT_TOKEN`.
- **Inputs / options:** Target shapes `C…`/`G…` (channel), `D…` (DM conversation), `U…`/`W…` (bare user ID → resolved to a DM on every send path — text, media and interactive prompts alike).
- **Outputs / side effects:** Real Slack messages and file shares.
- **Config / env:** `SLACK_BOT_TOKEN`.
- **Edge cases / guards:** Empty/whitespace messages are skipped with the debug line `[Slack] _standalone_send: skipping empty/whitespace message`.
- **Rebuild notes:** A stateless `chat.postMessage` helper sharing the formatter with the adapter. A better version would reuse the OAuth token file so multi-workspace cron targets work without env tokens.

### Slack `send_message` tool targets  `id: platforms-a.slack-send-message-targets`
- **Surface:** Tool (Platform:slack)
- **Where:** The agent's `send_message` tool with a Slack target.
- **What it does:** Lets the agent post text, media and interactive prompts to any Slack channel, DM conversation or user.
- **How it works:** Routed through the adapter's send paths (or `_standalone_send` out of process); user IDs are resolved to DM conversations on every path.
- **Inputs / options:** Target shapes: channel ID (`C…`/`G…`), DM conversation (`D…`), bare user ID (`U…`/`W…`). `MEDIA:<path>` attachments (images, PDFs, documents) upload as native file shares.
- **Outputs / side effects:** Messages/files in Slack; a short message accompanying a single attachment becomes the file's caption.
- **Config / env:** `SLACK_BOT_TOKEN`, `im:write` for user-ID targets.
- **Edge cases / guards:** Missing files are reported per file as warnings rather than failing the whole send.
- **Rebuild notes:** Normalize every target shape at one seam before dispatch. A better version would resolve `#channel-name` and `@display-name` too.

### Slack per-channel prompts  `id: platforms-a.slack-channel-prompts`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.channel_prompts` in `~/.hermes/config.yaml`, keyed by Slack channel ID.
- **What it does:** Injects an ephemeral system prompt on every turn in a specific channel, so a channel can have its own persona/constraints.
- **How it works:** Applied at API-call time via the per-turn `channel_prompt` seam — never persisted to transcript history, so changes take effect immediately and per-conversation prompt caching is not broken. The same seam carries the bot-identity prompt built by `_build_identity_prompt()` (`plugins/platforms/slack/adapter.py:4664`).
- **Inputs / options:** A YAML mapping of channel ID → prompt text (multi-line block scalars supported).
- **Outputs / side effects:** No persisted state.
- **Config / env:** `slack.channel_prompts`.
- **Edge cases / guards:** Keys must be channel IDs (channel details → "About" → bottom), not names.
- **Rebuild notes:** A dict lookup injected as a system message at call time only. A better version would allow per-thread overrides and a `/prompt` command to set one live.

### Slack bot-identity prompt  `id: platforms-a.slack-identity-prompt`
- **Surface:** Core (Platform:slack)
- **Where:** Invisible — injected as an ephemeral system line on every Slack turn.
- **What it does:** Tells the agent its own Slack handle so it can distinguish a mention of itself from a mention of another participant with a similar name.
- **How it works:** `_build_identity_prompt(team_id)` at `plugins/platforms/slack/adapter.py:4664`, resolving the name from `self._team_bot_names[team_id]` then `self._bot_display_name`; empty name → empty prompt. Verbatim text: `You are connected to this Slack workspace as the bot "@{name}". The adapter already applied mention and channel routing; treat every delivered turn as intentionally routed to you. Your routing mention "@{name}" may have been stripped from the visible text — do not reject or ignore a message solely because "@{name}" is absent. In messages, each line is prefixed with the sender's name, and visible mentions are shown as @DisplayName; a mention of any other participant is not a mention of you, even if their name is similar.`
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** One extra ephemeral system line per turn; not persisted.
- **Config / env:** n/a.
- **Edge cases / guards:** Rendered per workspace so a multi-workspace gateway names the right handle in each.
- **Rebuild notes:** Inject identity through the same ephemeral seam as channel prompts so it never poisons the cached history. A better version would also list the bot's aliases and the channel's other bot participants.

### Slack per-channel skill bindings  `id: platforms-a.slack-channel-skills`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.channel_skill_bindings` in `~/.hermes/config.yaml`.
- **What it does:** Auto-loads one or more skills whenever a new session starts in a specific channel or DM, so a channel can be dedicated to a purpose (flashcards, support triage, a domain Q&A bot).
- **What it does not do:** Unlike per-channel prompts (injected every turn), a binding injects the skill content as a user message at **session start** only — it becomes part of the conversation history and is not reloaded on later turns.
- **How it works:** Matched by channel ID; for threaded messages in a bound channel the thread inherits the parent channel's binding.
- **Inputs / options:** A YAML list of rows; each row has `id: "<channel or DM id>"` plus either `skills: [<name>, …]` (loaded in order) or the short form `skill: <name>`. Documented example verbatim: `- id: "D0ATH9TQ0G6"` / `skills:` / `- german-flashcards`; `- id: "C01RESEARCH"` / `skills:` / `- arxiv` / `- writing-plans`; `- id: "C02SUPPORT"` / `skill: hubspot-on-demand`.
- **Outputs / side effects:** Skill content prepended to the session as a user message.
- **Config / env:** `slack.channel_skill_bindings`.
- **Edge cases / guards:** Changing a binding takes effect only after `/new` or an auto-reset, because loading happens at session start. Combine with `channel_prompts` for per-channel tone on top of the skill's instructions.
- **Rebuild notes:** Look up bindings on session creation, resolve thread → parent channel, and inject skill bodies in list order. A better version would hot-reload the binding on config change instead of requiring `/new`.

### Slack session isolation (`group_sessions_per_user`)  `id: platforms-a.slack-session-isolation`
- **Surface:** Config
- **Where:** Global `group_sessions_per_user` in `~/.hermes/config.yaml`.
- **What it does:** Decides whether each user in a shared Slack channel gets their own conversation session or the whole channel shares one.
- **How it works:** Consumed by the gateway's session-key construction; the Slack adapter contributes `user_id`, `channel_id`, `thread_id` and `scope_id` (team) via `build_source()` / `_build_thread_session_key()` (`plugins/platforms/slack/adapter.py:8608`).
- **Inputs / options:** `true` (default — "each user in a shared channel gets their own isolated conversation session"), `false` (collaborative — the entire channel shares one session).
- **Outputs / side effects:** Session rows in the gateway store.
- **Config / env:** `group_sessions_per_user` (global; applies to Slack and all other platforms).
- **Edge cases / guards:** With `false`, "users share context growth and token costs, and one user's `/reset` clears the session for everyone."
- **Rebuild notes:** Make the user id an optional component of the session key. A better version would allow per-channel selection instead of one global switch.

### Slack unauthorized-user handling  `id: platforms-a.slack-unauthorized`
- **Surface:** Config (Platform:slack)
- **Where:** `slack.unauthorized_dm_behavior` (platform) or the global `unauthorized_dm_behavior`.
- **What it does:** Decides what happens when a user who is not in `SLACK_ALLOWED_USERS` DMs the bot.
- **How it works:** Early rejection in the message path at `plugins/platforms/slack/adapter.py:6323` — unauthorized users are rejected **before** thread lookups and name resolution, logging `[Slack] Early reject of unauthorized user %s in channel %s`.
- **Inputs / options:** `"pair"` (default — "prompt them for a pairing code"), `"ignore"` ("silently drop the message").
- **Outputs / side effects:** A pairing prompt or silence.
- **Config / env:** `slack.unauthorized_dm_behavior` (takes precedence) and the global `unauthorized_dm_behavior`.
- **Edge cases / guards:** Interactive button clicks are authorized separately (see below) because they bypass the message auth flow.
- **Rebuild notes:** Check the allowlist first in the admission chain. A better version would rate-limit pairing prompts per user to prevent prompt spam.

### Slack interactive-click authorization  `id: platforms-a.slack-interactive-auth`
- **Surface:** Core (Platform:slack)
- **Where:** Every Block Kit button click (approval, slash-confirm, clarify).
- **What it does:** Re-checks that the clicking user is authorized, because button clicks bypass the normal message auth flow in `gateway/run.py`.
- **How it works:** `_is_interactive_user_authorized(user_id, *, channel_id="", user_name=None, team_id="")` at `plugins/platforms/slack/adapter.py:7449`; an empty/blank user id returns `False`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Unauthorized clicks are silently ignored with a warning log — `[Slack] Unauthorized approval click by %s (%s) - ignoring`, `[Slack] Unauthorized slash-confirm click by %s (%s) - ignoring`, `[Slack] Unauthorized clarify click by %s (%s) - ignoring`.
- **Config / env:** `SLACK_ALLOWED_USERS`, `SLACK_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`.
- **Edge cases / guards:** The click is **not** acknowledged back to the clicker beyond Bolt's `ack()`, so an unauthorized user sees the buttons simply do nothing.
- **Rebuild notes:** Never trust that an interaction came from the same user the prompt was posted for. A better version would show an ephemeral "you're not authorized" so the user is not left guessing.

### Slack plugin action & native handler registration  `id: platforms-a.slack-plugin-handlers`
- **Surface:** Core (Platform:slack)
- **Where:** Plugin authors: `ctx.register_slack_action_handler(action_id, cb)` and `ctx.register_platform_handler("slack", factory)`.
- **What it does:** Lets other Hermes plugins add their own Block Kit action handlers and full Bolt listeners to the Slack app.
- **How it works:** At `plugins/platforms/slack/adapter.py:2386` the adapter pulls `get_plugin_manager().get_slack_action_handlers()` and wires each into `AsyncApp` before Socket Mode starts, so Bolt's matcher knows them at dispatch time. Each callback is wrapped by `_make_wrapper(cb, plugin_name)` (`:2400`) with signature `(ack, body, action)`; any exception is caught, logged as `[Slack] Plugin '%s' action handler raised: %s`, and a best-effort `ack()` is still sent. `_wire_plugin_handlers(self._app)` (`:2434`) hands the raw `AsyncApp` to generic platform-handler factories — the full `app.event()` / `app.action()` / `app.command()` surface, not just Block Kit actions.
- **Inputs / options:** `action_id` (string) + async callback `(ack, body, action)`; or a factory receiving the `AsyncApp`.
- **Outputs / side effects:** Logs `[Slack] Registered plugin action handler %s (from %s)` (DEBUG) and `[Slack] Wired %d plugin action handler(s)` (INFO). Load failures log `[Slack] Could not load plugin action handlers: %s`.
- **Config / env:** n/a.
- **Edge cases / guards:** Loop variables must not be captured as default args — Bolt inspects listener signatures with `inspect.signature` and passes `None` for unrecognised parameter names, which would silently clobber them; hence the closure factory.
- **Rebuild notes:** Register plugin listeners before the socket starts and wrap them so a plugin cannot take the gateway down. A better version would namespace plugin action IDs to prevent collisions.

### Slack history rehydration & thread watermarks  `id: platforms-a.slack-thread-rehydration`
- **Surface:** Core (Platform:slack)
- **Where:** Invisible — when the bot is pulled into an existing thread.
- **What it does:** Fetches the thread's prior messages so the agent has context, and remembers how far it has read so the same history is not replayed.
- **How it works:** `_ThreadContextCache` at `plugins/platforms/slack/adapter.py:317`; watermark helpers `_thread_watermark_key()` (`:8669`), `_get_thread_watermark()` (`:8719`), `_set_thread_watermark()` (`:8745`); one-shot rehydration guard `_thread_rehydration_key()` (`:8672`) / `_mark_thread_rehydration_checked()` (`:8690`); active-session probe `_has_active_session_for_thread()` (`:8779`). Fetched messages are rendered by `_render_message_text()` (`:7931`), which starts from `text`, strips bot mentions and appends rich-text content plus actionable URLs from `blocks` — bounded by what the blocks contain, unlike `_serialize_slack_blocks_for_agent()` which can emit up to 6 000 chars of JSON per message. Bot message timestamps are bounded by `_trim_bot_message_timestamps()` (`:1361`), mentioned threads by `_trim_mentioned_threads()` (`:1367`), and generic maps by `_trim_oldest_dict_entries()` (`:1375`) / `_discard_oldest_slack_timestamps()` (`:1352`) / `_discard_oldest_by_thread_ts()` (`:1391`), all ordered by `_slack_timestamp_sort_key()` (`:1331`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** In-memory caches only.
- **Config / env:** n/a.
- **Edge cases / guards:** Every cache is size-bounded with oldest-first eviction so a busy workspace cannot grow them without limit.
- **Rebuild notes:** Rehydrate once per thread, then track a watermark ts. A better version would persist watermarks so a gateway restart does not re-read the thread.

### Slack troubleshooting matrix  `id: platforms-a.slack-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/slack.md:997`.
- **What it does:** Maps each observed Slack failure to its fix — the diagnostic table an operator reads first.
- **How it works:** Static documentation; each row corresponds to a scope/event/invite requirement enforced Slack-side.
- **Inputs / options:** Rows, verbatim (Problem → Solution): "Bot doesn't respond to DMs" → "Verify `message.im` is in your event subscriptions and the app is reinstalled"; "Bot works in DMs but not in channels" → "**Most common issue.** Add `message.channels` and `message.groups` to event subscriptions, reinstall the app, and invite the bot to the channel with `/invite @Hermes Agent`"; "Bot doesn't respond to @mentions in channels" → "1) Check `message.channels` event is subscribed. 2) Bot must be invited to the channel. 3) Ensure `channels:history` scope is added. 4) Reinstall the app after scope/event changes"; "Bot ignores messages in private channels" → "Add both the `message.groups` event subscription and `groups:history` scope, then reinstall the app and `/invite` the bot"; "Bot doesn't respond in group DMs (multi-person DMs)" → "Add the `message.mpim` event subscription and the `mpim:history` scope (plus `mpim:read`), then **reinstall** the app…"; "\"Sending messages to this app has been turned off\" in DMs" → "Enable the **Messages Tab** in App Home settings (see Step 5)"; "\"not_authed\" or \"invalid_auth\" errors" → "Regenerate your Bot Token and App Token, update `.env`"; "Bot responds but can't post in a channel" → "Invite the bot to the channel with `/invite @Hermes Agent`"; "Bot can chat but can't read uploaded images/files" → "Add `files:read`, then **reinstall** the app. Hermes now surfaces attachment access diagnostics in-chat when Slack returns scope/auth/permission failures."; "`missing_scope` error" → "Add the required scope in OAuth & Permissions, then **reinstall** the app"; "Socket disconnects frequently" → "Check your network; Bolt auto-reconnects but unstable connections cause lag"; "Changed scopes/events but nothing changed" → "You **must reinstall** the app to your workspace after any scope or event subscription change". Quick checklist items 1–8, verbatim: "✅ `message.channels` event is subscribed (for public channels)", "✅ `message.groups` event is subscribed (for private channels)", "✅ `app_mention` event is subscribed", "✅ `channels:history` scope is added (for public channels)", "✅ `groups:history` scope is added (for private channels)", "✅ App was **reinstalled** after adding scopes/events", "✅ Bot was **invited** to the channel (`/invite @Hermes Agent`)", "✅ You are **@mentioning** the bot in your message".
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Security section verbatim: "**Always set `SLACK_ALLOWED_USERS`** … Without this setting, the gateway will **deny all messages** by default as a safety measure." Tokens live in `~/.hermes/.env` with mode `600`; Socket Mode exposes no public endpoint.
- **Rebuild notes:** Encode each row as a runtime check so the product can print the fix instead of the doc. A better version would ship `hermes gateway doctor --slack` that performs all eight checklist checks live.

### Slack Codex reasoning-effort caution  `id: platforms-a.slack-codex-effort`
- **Surface:** Docs / Config
- **Where:** Tip box at `website/docs/user-guide/messaging/slack.md:232`.
- **What it does:** Warns that `xhigh` reasoning effort can consume an entire turn in hidden reasoning, producing no visible assistant text in a Slack peer-agent channel.
- **How it works:** Documentation-level guidance; Hermes suppresses the resulting incomplete-turn warnings from the thread and keeps the diagnostics in gateway logs.
- **Inputs / options:** `agent.reasoning_effort` — prefer `high` or lower for Codex-backed Slack peer-agent channels.
- **Outputs / side effects:** Warning text stays out of the Slack thread.
- **Config / env:** `agent.reasoning_effort`.
- **Edge cases / guards:** Applies specifically to Codex-backed models.
- **Rebuild notes:** Detect a turn that produced only reasoning and emit a single "no visible output" note. A better version would auto-lower effort after one such turn.

---

## 3. WhatsApp (Baileys bridge)

### WhatsApp platform adapter (Baileys bridge)  `id: platforms-a.whatsapp`
- **Surface:** Platform:whatsapp
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"WhatsApp"** (emoji 💬), paired with `hermes whatsapp`; runs inside `hermes gateway`. In WhatsApp itself: 1:1 chats, group chats, and (in self-chat mode) the user's own "Message yourself" chat.
- **What it does:** Connects Hermes to a personal WhatsApp account through a bundled **Node.js Baileys bridge** that emulates a WhatsApp Web linked device — no Meta developer account, no Business verification, no public URL. The Python adapter talks to the bridge over local HTTP.
- **How it works:** `plugins/platforms/whatsapp/adapter.py:421` defines `WhatsAppAdapter(WhatsAppBehaviorMixin, BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/whatsapp/adapter.py:1953` calls `ctx.register_platform(name="whatsapp", label="WhatsApp", adapter_factory=_build_adapter, check_fn=check_whatsapp_requirements, is_connected=_is_connected, required_env=["WHATSAPP_ENABLED"], install_hint="WhatsApp requires a Node.js bridge — see the WhatsApp messaging docs", setup_fn=interactive_setup, apply_yaml_config_fn=_apply_yaml_config, allowed_users_env="WHATSAPP_ALLOWED_USERS", allow_all_env="WHATSAPP_ALLOW_ALL_USERS", cron_deliver_env_var="WHATSAPP_HOME_CHANNEL", standalone_sender_fn=_standalone_send, max_message_length=4096, emoji="💬", allow_update_command=True)`. Manifest `plugins/platforms/whatsapp/plugin.yaml:1` (`name: whatsapp-platform`, `label: WhatsApp`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). Shared behaviour (gating, mention parsing, markdown conversion, chunking) lives in `gateway/platforms/whatsapp_common.py:64` `WhatsAppBehaviorMixin` — also used by the Cloud API adapter. `MAX_MESSAGE_LENGTH = 4096` (`whatsapp_common.py:76`, "practical UX limit, not protocol max. WhatsApp allows ~65K but long messages are unreadable on mobile"), `supports_code_blocks = True`, `splits_long_messages = True`, `_SPLIT_THRESHOLD = 6000` (`adapter.py:1436`). Every `WHATSAPP_*` env read goes through `_wenv()` (`adapter.py:37`) → `agent.secret_scope.get_secret` so multiplexed profiles see their own credentials instead of falling back to `"self-chat"` and rejecting everything.
- **Inputs / options:** Env: `WHATSAPP_ENABLED` (required), `WHATSAPP_MODE` (`bot` | `self-chat`, default `self-chat`), `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_ALLOW_FROM`, `WHATSAPP_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`, `WHATSAPP_DM_POLICY`, `WHATSAPP_GROUP_POLICY`, `WHATSAPP_GROUP_ALLOWED_USERS`, `WHATSAPP_GROUP_ALLOW_FROM`, `WHATSAPP_REQUIRE_MENTION`, `WHATSAPP_MENTION_PATTERNS`, `WHATSAPP_FREE_RESPONSE_CHATS`, `WHATSAPP_HOME_CHANNEL`, `WHATSAPP_HOME_CHANNEL_NAME`, `WHATSAPP_DEBUG`, `WHATSAPP_FORWARD_OWNER_MESSAGES`, `WHATSAPP_REPLY_PREFIX`, `WHATSAPP_MAX_MESSAGE_LENGTH`, `WHATSAPP_CHUNK_DELAY_MS`, `WHATSAPP_SEND_TIMEOUT_MS`, `WHATSAPP_SEND_READ_RECEIPTS`, `WHATSAPP_NPM_INSTALL_TIMEOUT`. Config: `whatsapp:` block plus `gateway.platforms.whatsapp.extra.*`.
- **Outputs / side effects:** Spawns and supervises a Node.js child process; writes `~/.hermes/platforms/whatsapp/session/` (Baileys credentials), `~/.hermes/platforms/whatsapp/bridge.log`, a bridge PID file, and media into the profile-aware image/audio/video/document cache dirs.
- **Config / env:** `whatsapp.require_mention`, `whatsapp.mention_patterns`, `whatsapp.free_response_chats`, `whatsapp.dm_policy`, `whatsapp.allow_from`, `whatsapp.group_policy`, `whatsapp.group_allow_from`, `whatsapp.reply_prefix`, `whatsapp.send_read_receipts`, `whatsapp.unauthorized_dm_behavior`, `gateway.platforms.whatsapp.extra.{bridge_port,bridge_script,session_path,text_batch_delay_seconds,text_batch_split_delay_seconds}`.
- **Edge cases / guards:** Documented warning verbatim: "WhatsApp does **not** officially support third-party bots outside the Business API. Using a third-party bridge carries a small risk of account restrictions." Mitigations, verbatim: "**Use a dedicated phone number** for the bot (not your personal number)", "**Don't send bulk/spam messages** — keep usage conversational", "**Don't automate outbound messaging** to people who haven't messaged first". Also: "WhatsApp periodically updates their Web protocol, which can temporarily break compatibility with third-party bridges." Without an allowlist, allow-all flag, or `*`, all inbound messages are denied.
- **Rebuild notes:** Minimal spec: a Node process holding a Baileys socket, exposing `/health`, `/messages`, `/send`, `/send-media`, `/send-poll`, `/send-location`, `/edit`, `/typing`, `/read`, `/chat/<jid>`; a Python poller draining `/messages` every second. A better version would replace HTTP polling with a WebSocket or SSE push channel so latency is not floor-bounded at 1 s.

### WhatsApp two modes (`bot` vs `self-chat`)  `id: platforms-a.whatsapp-modes`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `WHATSAPP_MODE` in `~/.hermes/.env`; chosen in the `hermes whatsapp` wizard.
- **What it does:** Chooses whether the bot lives on a dedicated phone number that people message directly, or inside the operator's own account via the "Message yourself" chat.
- **How it works:** Read by `_wenv("WHATSAPP_MODE", "self-chat")` (`plugins/platforms/whatsapp/adapter.py:724`) and passed to the bridge as `--mode <whatsapp_mode>` (`:783`). The mode also gates the reply prefix — `_effective_reply_prefix()` at `gateway/platforms/whatsapp_common.py:103` returns `""` for any mode other than `self-chat`.
- **Inputs / options:** Table verbatim from the docs — **Separate bot number** (recommended): "Dedicate a phone number to the bot. People message that number directly." Best for "Clean UX, multiple users, lower ban risk". **Personal self-chat**: "Use your own WhatsApp. You message yourself to talk to the agent." Best for "Quick setup, single user, testing".
- **Outputs / side effects:** Bridge behaviour and prefix differ.
- **Config / env:** `WHATSAPP_MODE` = `bot` | `self-chat`.
- **Edge cases / guards:** Bot mode needs a phone number not already registered with WhatsApp; documented options are **Google Voice** (free, US only, verify via SMS through the Google Voice app), a **Prepaid SIM** ($5–15 one-time; number must stay active — "make a call every 90 days"), and **VoIP services** (free–$5/month; "Some VoIP numbers are blocked by WhatsApp — try a few if the first doesn't work").
- **Rebuild notes:** One mode flag that switches the "is this message for me" rule between `fromMe` and `to == bot_jid`. A better version would auto-detect the mode from the paired account's own JID.

### WhatsApp interactive setup wizard  `id: platforms-a.whatsapp-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **WhatsApp**.
- **What it does:** Enables the adapter, captures an allowlist and an optional home chat.
- **How it works:** `interactive_setup()` at `plugins/platforms/whatsapp/adapter.py:1842`.
- **Inputs / options:** Verbatim strings in order:
  - header `WhatsApp`
  - `WhatsApp uses a local Node.js bridge (WhatsApp Web client).`
  - `Start the bridge separately; the gateway connects to it over HTTP.`
  - `WhatsApp: already enabled` (when `WHATSAPP_ENABLED` is `true`/`1`/`yes`)
  - `Reconfigure WhatsApp?` (yes/no, default `False`)
  - `Enable WhatsApp?` (yes/no, default `True`) → `WhatsApp enabled` or `WhatsApp left disabled` (and returns)
  - prompt `Allowed user IDs (comma-separated, leave empty for no allowlist)` → `WhatsApp allowlist configured`
  - prompt `Home chat ID for cron delivery (leave empty to skip)` → clears with `Home channel cleared.`
- **Outputs / side effects:** Writes `WHATSAPP_ENABLED` (`true`/`false`), `WHATSAPP_ALLOWED_USERS` (spaces stripped), `WHATSAPP_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** Declining `Enable WhatsApp?` writes `false` and exits — it does not leave the key unset. Pairing (the QR flow) is a **separate** command, `hermes whatsapp` (documented in `cli-b.whatsapp`).
- **Rebuild notes:** A three-prompt env writer. A better version would run the QR pairing inline instead of pointing at a second command.

### WhatsApp QR pairing / session persistence  `id: platforms-a.whatsapp-pairing`
- **Surface:** CLI (Platform:whatsapp)
- **Where:** `hermes whatsapp`; on the phone: **Settings → Linked Devices → Link a Device**.
- **What it does:** Links the Hermes bridge to a WhatsApp account by displaying a QR code in the terminal and saving the resulting session.
- **How it works:** The wizard (1) asks which mode you want (**bot** or **self-chat**), (2) installs bridge dependencies if needed, (3) displays a QR code in the terminal, (4) waits for the scan. Session data is written to `~/.hermes/platforms/whatsapp/session` (default from `get_hermes_dir("platforms/whatsapp/session", "whatsapp/session")`, `plugins/platforms/whatsapp/adapter.py:466`). The gateway then reuses that session automatically.
- **Inputs / options:** Terminal QR scan; no flags on the platform side (see `cli-b.whatsapp` for the command's own options).
- **Outputs / side effects:** `~/.hermes/platforms/whatsapp/session/` containing encryption keys and device credentials.
- **Config / env:** `gateway.platforms.whatsapp.extra.session_path` overrides the location.
- **Edge cases / guards:** "If the QR code looks garbled, make sure your terminal is at least 60 columns wide and supports Unicode." QR codes refresh every ~20 seconds; on timeout, restart `hermes whatsapp`. Sessions survive restarts. **"Do not share or commit this session directory — it grants full access to the WhatsApp account"**; recommended `chmod 700 ~/.hermes/platforms/whatsapp/session`. Re-pair by re-running `hermes whatsapp` after a phone reset, WhatsApp update, or manual unlink; temporary disconnections (network blips, phone briefly offline) are handled automatically by the bridge's reconnection logic.
- **Rebuild notes:** Render Baileys' QR string with a terminal QR encoder and persist `authState` to disk. A better version would also support Baileys' pairing-code flow so no camera is needed.

### WhatsApp bridge lifecycle & supervision  `id: platforms-a.whatsapp-bridge-lifecycle`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — gateway startup; console lines prefixed `[whatsapp]`.
- **What it does:** Installs bridge dependencies, reuses or restarts a running bridge, spawns the Node process in its own process group, waits for WhatsApp to connect, and cleans up orphans.
- **How it works:** `connect()` at `plugins/platforms/whatsapp/adapter.py:~600`. Sequence: (1) `npm install` when the dependency stamp does not match the `package.json` hash; (2) `mkdir -p` the session dir; (3) probe `GET http://127.0.0.1:<port>/health` (2 s timeout) — reuse only if `status == "connected"` **and** the **staleness handshake** passes: the bridge's reported `scriptHash` must equal `_file_content_hash(bridge.js)` (first 16 hex chars of SHA-256, `:382`) **and** its reported `sendReadReceipts` must match the configured value; (4) otherwise `_kill_stale_bridge_by_pidfile()` (`:212`) + `_kill_port_process()` (`:124`) then `sleep 1`; (5) `subprocess.Popen([node, bridge.js, "--port", <port>, "--session", <path>, "--mode", <mode>], stdout=bridge.log, stderr=bridge.log, env=bridge_env, **windows_detach_popen_kwargs())`; (6) write the PID file (`_write_bridge_pidfile`, `:261`); (7) Phase 1 — poll `/health` for up to 15 s for the HTTP server; (8) Phase 2 — poll up to 15 s more for `status: connected`; (9) create a persistent `aiohttp.ClientSession` and start `_poll_messages()`; (10) `_wire_plugin_handlers(None)`.
- **Inputs / options:** `gateway.platforms.whatsapp.extra.bridge_port` (default `3000`), `bridge_script` (default `<bridge_dir>/bridge.js`), `session_path`. Bridge dir resolved by `resolve_whatsapp_bridge_dir()` (`gateway/platforms/whatsapp_common.py:506`), which mirrors the bridge source into `HERMES_HOME` when the install tree is read-only (e.g. Docker `/opt/hermes`).
- **Outputs / side effects:** Console lines verbatim: `[whatsapp] Dependencies installed`, `[whatsapp] npm install failed: <stderr>`, `[whatsapp] Failed to install dependencies: <e>`, `[whatsapp] Using existing bridge (status: <status>)`, `[whatsapp] Running bridge is stale (<reason>), restarting`, `[whatsapp] Bridge found but not connected (status: <status>), restarting`, `[whatsapp] Bridge process died (exit code <rc>)`, `[whatsapp] Check log: <path>`, `[whatsapp] Bridge HTTP server did not start in 15s`, `[whatsapp] Bridge HTTP ready, waiting for WhatsApp connection...`, `[whatsapp] Bridge ready (status: connected)`, `[whatsapp] ⚠ WhatsApp not connected after 30s`, `[whatsapp]   Bridge log: <path>`, `[whatsapp]   If session expired, re-pair: hermes whatsapp`, `[whatsapp] Bridge started on port <port>`, `[whatsapp] Poll error: <e>`. Stale reason strings: `running=<hash|unversioned>, disk=<hash>` or `send_read_receipts config changed`.
- **Config / env:** Env injected into the child: `WHATSAPP_REPLY_PREFIX`, `WHATSAPP_SEND_READ_RECEIPTS`, `WHATSAPP_MODE`, then (when set) `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_ALLOW_FROM`, `WHATSAPP_DM_POLICY`, `WHATSAPP_GROUP_POLICY`, `WHATSAPP_GROUP_ALLOWED_USERS`, `WHATSAPP_GROUP_ALLOW_FROM`, `WHATSAPP_REQUIRE_MENTION`, `WHATSAPP_MENTION_PATTERNS`, `WHATSAPP_FREE_RESPONSE_CHATS`, `WHATSAPP_DEBUG`, `WHATSAPP_FORWARD_OWNER_MESSAGES`, `WHATSAPP_MAX_MESSAGE_LENGTH`, `WHATSAPP_CHUNK_DELAY_MS`, `WHATSAPP_SEND_TIMEOUT_MS`, plus `HERMES_IMAGE_CACHE_DIR`, `HERMES_AUDIO_CACHE_DIR`, `HERMES_DOCUMENT_CACHE_DIR` (profile-aware so the bridge writes media where Python reads it).
- **Edge cases / guards:** Port-kill is **fail-closed**: `_listener_pids_on_port()` (`:65`) matches only LISTEN sockets (`lsof -ti tcp:<port> -sTCP:LISTEN`, falling back to `ss -ltnHp "sport = :<port>"`) — a bare `lsof -i :PORT` would also return *clients* and SIGTERM an unrelated browser; `_pid_looks_like_node_bridge()` (`:103`) then requires the live process to actually be a `node` executable via psutil, refusing the kill on any ambiguity (process gone, unreadable cmdline). `_bridge_pid_is_ours()` (`:181`) checks the PID file against the session path and expected start time. `_terminate_bridge_process()` (`:277`) handles graceful vs forced termination. Windows uses `netstat` + `taskkill` with `windows_hide_flags`. npm-install failure sets a non-retryable fatal error `whatsapp_npm_install_failed` with the message `WhatsApp bridge npm install failed. Run `cd <bridge_dir> && <npm> install` manually, then restart `hermes gateway`.` `_shutting_down` distinguishes an intentional SIGTERM (return codes −15 / −2 / 0) from a real crash so a graceful restart does not emit "Fatal whatsapp adapter error".
- **Rebuild notes:** Version the bridge by content hash and refuse to reuse a mismatched process; verify any PID before killing it. A better version would run the bridge under a supervisor with backoff instead of re-deriving liveness at each connect.

### WhatsApp bridge media-path validation  `id: platforms-a.whatsapp-bridge-path-guard`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — every inbound media file the bridge reports.
- **What it does:** Refuses absolute file paths handed back by the bridge that do not resolve inside a Hermes media cache directory, so a compromised or buggy bridge cannot make the agent read `/etc/passwd`.
- **How it works:** `_is_allowed_bridge_path(url)` at `plugins/platforms/whatsapp/adapter.py:341` resolves the path (following symlinks) and requires `Path(url).resolve().is_relative_to()` one of `get_image_cache_dir()`, `get_audio_cache_dir()`, `get_video_cache_dir()`, `get_document_cache_dir()` — resolved per call via the getters (not import-time constants) so it follows the active profile override, and covering both the canonical `cache/<kind>` layout and the legacy `<kind>_cache` layout.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Rejections print verbatim `[whatsapp] Rejected bridge image path outside cache dir: <url>` / `... bridge audio path ...` / `... bridge document path ...` / `... bridge video path ...`; accepted paths print `[whatsapp] Using bridge-cached image: <url>` (and the audio/document/video equivalents).
- **Config / env:** `HERMES_IMAGE_CACHE_DIR`, `HERMES_AUDIO_CACHE_DIR`, `HERMES_DOCUMENT_CACHE_DIR`.
- **Edge cases / guards:** `OSError`/`ValueError` during resolution returns `False` (fail closed).
- **Rebuild notes:** Never attach a subprocess-supplied path without a containment check against a fixed root set. A better version would have the bridge return opaque handles the adapter dereferences itself.

### WhatsApp DM policy  `id: platforms-a.whatsapp-dm-policy`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `whatsapp.dm_policy` in `~/.hermes/config.yaml` or `WHATSAPP_DM_POLICY`.
- **What it does:** Decides which 1:1 WhatsApp senders may reach the agent at all.
- **How it works:** `_is_dm_intake_allowed()` at `gateway/platforms/whatsapp_common.py:264` (intake / pairing handshake) and `_is_dm_allowed()` at `:254` (strict authorization — "pairing does not imply access"). Default `"pairing"` (`plugins/platforms/whatsapp/adapter.py:471`). The allowlist source precedence is `config.extra["allow_from"]` → `config.extra["allowFrom"]` → `WHATSAPP_ALLOWED_USERS`, selected by **key presence** so an explicit `allow_from: []` stays authoritative; the winning source is remembered in `_dm_allowlist_source` and re-read live by `_live_dm_allow_from()` (`whatsapp_common.py:157`) so pairing approve/revoke takes effect without a restart (a removed key means an empty allowlist, never a revival of the construction-time snapshot).
- **Inputs / options:** Four values — `"open"` (any sender, but only when opted in via `WHATSAPP_ALLOW_ALL_USERS` or `GATEWAY_ALLOW_ALL_USERS`), `"allowlist"` (only `allow_from` / `WHATSAPP_ALLOWED_USERS`), `"disabled"` (no DMs at all), `"pairing"` (default — intake allowed so the pairing handshake can run, but not authorization).
- **Outputs / side effects:** Admission or silence/pairing prompt.
- **Config / env:** `whatsapp.dm_policy`, `whatsapp.allow_from`, `WHATSAPP_DM_POLICY`, `WHATSAPP_ALLOWED_USERS`, `WHATSAPP_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`. `enforces_own_access_policy` is `True` (`whatsapp_common.py:98`) — WhatsApp gates access at intake rather than in the generic gateway path.
- **Edge cases / guards:** `WHATSAPP_ALLOWED_USERS=*` allows all senders (equivalent to `WHATSAPP_ALLOW_ALL_USERS=true`), consistent with Signal group allowlists. Phone numbers are configured **with country code and without `+` or spaces**.
- **Rebuild notes:** Separate *intake* from *authorization* so a pairing handshake can run without granting access. A better version would expire pairing grants automatically.

### WhatsApp group policy & group gating  `id: platforms-a.whatsapp-group-policy`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `whatsapp.group_policy` / `WHATSAPP_GROUP_POLICY`, `whatsapp.group_allow_from` / `WHATSAPP_GROUP_ALLOWED_USERS`.
- **What it does:** Decides which WhatsApp groups the bot participates in, and whether a mention is required inside them.
- **How it works:** `_is_group_allowed()` at `gateway/platforms/whatsapp_common.py:279`; group message gating in `_should_process_message()` at `:390`. Order for a group message: broadcast check → group policy → free-response chat → `require_mention` off → body starts with `/` → reply-to-bot → mentions-bot → mention patterns.
- **Inputs / options:** `group_policy`: `"open"` (all groups), `"allowlist"` (only `group_allow_from` JIDs), `"disabled"`, `"pairing"` (returns **False** — pairing is not a group concept). Default `"pairing"` (i.e. groups are off until configured). `whatsapp.require_mention` (default `false` via `WHATSAPP_REQUIRE_MENTION`), `whatsapp.free_response_chats` (list or CSV of chat IDs), `whatsapp.mention_patterns` (list, single string, `WHATSAPP_MENTION_PATTERNS` as a JSON list or newline/comma-separated values; compiled `re.IGNORECASE`).
- **Outputs / side effects:** Group messages admitted or dropped.
- **Config / env:** the six keys above.
- **Edge cases / guards:** DMs that pass the policy gate are **always** processed — mention rules apply to groups only. A body starting with `/` always passes the mention gate so commands work. Bot mention detection (`_message_mentions_bot()`, `:351`) checks `mentionedIds` against `botIds` and, failing that, looks for the bare id (or `@<bare id>`) inside the body; `_clean_bot_mention_text()` (`:377`) strips `@<bare-id>` plus trailing `,:-` from the text before it reaches the agent. Invalid regex patterns log `[whatsapp] Invalid WhatsApp mention pattern %r: %s`; a wrong type logs `[whatsapp] whatsapp mention_patterns must be a list or string; got %s`; success logs `[whatsapp] Loaded %d WhatsApp mention pattern(s)`.
- **Rebuild notes:** Two independent policies (DM, group) plus a mention gate that only applies to groups. A better version would allow per-group mention settings instead of a single global flag.

### WhatsApp LID ↔ phone-number allowlist matching  `id: platforms-a.whatsapp-lid-matching`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — every allowlist comparison.
- **What it does:** Makes an allowlist written with phone numbers match senders WhatsApp delivers in LID form (and vice versa), so a known contact is not silently rejected.
- **How it works:** `_matches_whatsapp_allowlist(candidate, allow_from)` at `gateway/platforms/whatsapp_common.py:216`. Fast path: exact membership. Otherwise both the candidate and each allowlist entry are expanded through `gateway.whatsapp_identity.expand_whatsapp_aliases()` / `normalize_whatsapp_identifier()`, which read the bridge's `lid-mapping-*.json` files — the same helper the gateway authz and session-key paths use. `_normalize_whatsapp_id()` (`:181`) rewrites the first `:` to `@` for device-suffixed JIDs.
- **Inputs / options:** Allowlist entries may be phone numbers, LIDs, full `@g.us` group JIDs, or the wildcard `*`.
- **Outputs / side effects:** Boolean admission.
- **Config / env:** n/a.
- **Edge cases / guards:** An empty allowlist returns `False`. `*` as an entry returns `True` for anything.
- **Rebuild notes:** Normalize identifiers through the bridge's own mapping file on both sides of the comparison. A better version would refresh the LID map on demand when a comparison misses.

### WhatsApp broadcast/status/channel suppression  `id: platforms-a.whatsapp-broadcast-guard`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — Status updates (Stories) and Channel/Newsletter posts.
- **What it does:** Never lets the agent reply to WhatsApp pseudo-chats that are not real conversations.
- **How it works:** `_is_broadcast_chat(chat_id)` at `gateway/platforms/whatsapp_common.py:190` returns `True` for the exact id `status@broadcast` and for any id ending in `@broadcast` or `@newsletter` (case-insensitive). Checked first in `_should_process_message()`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Those messages are dropped before any policy check.
- **Config / env:** n/a.
- **Edge cases / guards:** Also applies in self-chat mode where the bridge may surface these as `fromMe` events. Rationale, verbatim: "answering a Story update spams the contact's status feed, and Channel posts aren't addressable in the first place."
- **Rebuild notes:** A suffix check ahead of everything else. A better version would let an operator opt in to reading (but never replying to) Channel posts.

### WhatsApp reply prefix (`⚕ *Hermes Agent*`)  `id: platforms-a.whatsapp-reply-prefix`
- **Surface:** Config (Platform:whatsapp)
- **Where:** Prefixed to every outgoing message in self-chat mode; default `⚕ *Hermes Agent*\n────────────\n`.
- **What it does:** Marks agent replies inside a self-chat so they are visually distinguishable from the user's own typed messages.
- **How it works:** `DEFAULT_REPLY_PREFIX` at `gateway/platforms/whatsapp_common.py:78`; `_effective_reply_prefix()` at `:103` — returns `""` unless `WHATSAPP_MODE == "self-chat"`, then prefers `config.extra["reply_prefix"]`, then `WHATSAPP_REPLY_PREFIX`, then the default; literal `\n` sequences are converted to real newlines. `_outgoing_chunk_limit()` at `:120` reserves room for the prefix: `max(1024, MAX_MESSAGE_LENGTH - len(prefix))`. The value is also injected into the bridge subprocess environment so the Node side uses the same prefix.
- **Inputs / options:** `whatsapp.reply_prefix: ""` (empty string disables the header) or a custom value such as `"🤖 *My Bot*\n──────\n"`.
- **Outputs / side effects:** Every reply carries the prefix; chunk size shrinks accordingly.
- **Config / env:** `whatsapp.reply_prefix`, `WHATSAPP_REPLY_PREFIX`, `WHATSAPP_MODE`.
- **Edge cases / guards:** The chunk limit never drops below 1 024 characters even with an absurdly long prefix, leaving room for `truncate_message`'s pagination indicator and code-fence repair.
- **Rebuild notes:** Compute the effective chunk size from the prefix length, not from the raw limit. A better version would drop the prefix on continuation chunks so it appears once per reply.

### WhatsApp outbound text sanitization  `id: platforms-a.whatsapp-sanitize`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — every outgoing message.
- **What it does:** Strips invisible unicode that WhatsApp renders as mojibake-looking prefixes and normalizes odd spaces.
- **How it works:** `_sanitize_outbound_text()` at `gateway/platforms/whatsapp_common.py:83`. `_OUTBOUND_INVISIBLE_CHARS_RE = [​⁠⁣﻿]` removed; `_OUTBOUND_ODD_SPACE_RE = [  ᠎ -   　]` replaced with a plain space. Runs first inside `format_message()`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Cleaner rendering.
- **Config / env:** n/a.
- **Edge cases / guards:** Normal text and emoji joiners are intentionally left intact.
- **Rebuild notes:** Two regex substitutions at the top of the formatter. A better version would also normalize the RTL/LTR marks that flip mixed-script messages.

### WhatsApp markdown → WhatsApp formatting  `id: platforms-a.whatsapp-markdown`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Every agent reply.
- **What it does:** Converts standard markdown to WhatsApp's native formatting dialect.
- **How it works:** `format_message()` at `gateway/platforms/whatsapp_common.py:425`, six steps: (1) sanitize; (2) protect fenced code with the placeholder `\x00FENCE<n>\x00` (`re.sub(r"```[\s\S]*?```", …)`); (3) protect inline code with `\x00CODE<n>\x00` (`re.sub(r"`[^`\n]+`", …)`); (4) convert — italic `(?<!\*)\*(?!\s|\*)([^*\n]*?\S[^*\n]*?)\*(?!\*)` → `_\1_` **before** bold so `**bold**` is not mis-italicized, bold `\*\*(.+?)\*\*` → `*\1*` and `__(.+?)__` → `*\1*`, strikethrough `~~(.+?)~~` → `~\1~`, `_text_` left as-is; (5) headers `^#{1,6}\s+(.+)$` (MULTILINE) → `*Header*` with any already-produced `*…*` wrapper stripped so `# **Title**` becomes `*Title*` not `**Title**`; (6) links `\[([^\]]+)\]\(([^)]+)\)` → `text (url)`; then restore the protected regions.
- **Inputs / options:** n/a (always on).
- **Outputs / side effects:** WhatsApp-formatted text. Conversion table, verbatim: `**bold**`→`*bold*`; `~~strikethrough~~`→`~strikethrough~`; `# Heading`→`*Heading*` ("Bold text (no native headings)"); `[link text](url)`→`link text (url)`.
- **Config / env:** n/a.
- **Edge cases / guards:** "Code blocks and inline code are preserved as-is since WhatsApp supports triple-backtick formatting natively."
- **Rebuild notes:** Placeholder-protect code, then ordered regex conversion (italic before bold). A better version would use a real markdown AST so nested emphasis survives.

### WhatsApp message chunking & streaming  `id: platforms-a.whatsapp-chunking`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Every long reply.
- **What it does:** Splits long responses into multiple messages and edits messages in place while the model streams.
- **How it works:** `splits_long_messages = True` (`plugins/platforms/whatsapp/adapter.py:451`); chunking via `truncate_message()` against `_outgoing_chunk_limit()`. Edits go to the bridge's `/edit` endpoint (`adapter.py:1056`). Docs: "WhatsApp supports **streaming (progressive) responses** — the bot edits its message in real-time as the AI generates text, just like Discord and Telegram. Internally, WhatsApp is classified as a TIER_MEDIUM platform for delivery capabilities."
- **Inputs / options:** `WHATSAPP_MAX_MESSAGE_LENGTH`, `WHATSAPP_CHUNK_DELAY_MS`, `WHATSAPP_SEND_TIMEOUT_MS` (all forwarded to the bridge).
- **Outputs / side effects:** Sequential messages at ~4 096 characters per chunk.
- **Config / env:** the three env vars above.
- **Edge cases / guards:** "You don't need to configure anything — the gateway handles splitting and sends chunks sequentially."
- **Rebuild notes:** Chunk on the prefix-adjusted limit and pace sends. A better version would split on paragraph boundaries rather than a hard character count.

### WhatsApp text batching (debounce)  `id: platforms-a.whatsapp-batching`
- **Surface:** Config (Platform:whatsapp)
- **Where:** Invisible — rapid bursts of inbound messages.
- **What it does:** Buffers successive text messages from the same chat and dispatches them as one combined request after a quiet period, so a forwarded batch or paste-split does not trigger one agent invocation per fragment.
- **How it works:** `_enqueue_text_event()` at `plugins/platforms/whatsapp/adapter.py:1449` keys the buffer by `_text_batch_key()` (`:1439`, the session key from `gateway.session.build_session_key` with `group_sessions_per_user` / `thread_sessions_per_user` from `config.extra`), concatenating texts with `\n` and extending `media_urls` / `media_types`; each new message cancels and reschedules `_flush_text_batch()` (`:1479`). The flush delay is `text_batch_split_delay_seconds` when the **last** chunk was ≥ `_SPLIT_THRESHOLD` (6 000 chars), otherwise `text_batch_delay_seconds`. `_coerce_float_extra()` (`:530`) guards NaN/Inf/unparseable values since the value is fed straight to `asyncio.sleep`.
- **Inputs / options:** `gateway.platforms.whatsapp.extra.text_batch_delay_seconds` (default `5.0` — "quiet period before flushing a batch"), `gateway.platforms.whatsapp.extra.text_batch_split_delay_seconds` (default `10.0` — "extended delay near the split threshold"). Set `text_batch_delay_seconds: 0` to dispatch each message immediately (disables batching).
- **Outputs / side effects:** One combined `MessageEvent` per burst.
- **Config / env:** the two keys above.
- **Edge cases / guards:** Only `MessageType.TEXT` events are batched (`_poll_messages()` at `:1394`); media events dispatch immediately.
- **Rebuild notes:** A per-session debounce timer that concatenates events. A better version would flush early when the batch already looks like a complete question.

### WhatsApp native polls  `id: platforms-a.whatsapp-polls`
- **Surface:** Platform:whatsapp / Tool
- **Where:** A real WhatsApp poll bubble (question + tappable options).
- **What it does:** Lets the agent send a native single- or multi-select WhatsApp poll; votes flow back into the conversation.
- **How it works:** `send_poll()` at `plugins/platforms/whatsapp/adapter.py:1121` POSTs to `http://127.0.0.1:<port>/send-poll` with `{"chatId": to_whatsapp_jid(chat_id), "question": …, "options": [...], "selectableCount": n}` and a 30 s timeout.
- **Inputs / options:** `chat_id`, `question`, `options` (list of strings), `selectable_count` (default `1`).
- **Outputs / side effects:** `SendResult(success=True, message_id=data["messageId"], raw_response=data)`; a non-200 returns the response body as the error.
- **Config / env:** n/a.
- **Edge cases / guards:** Docstring is explicit: "This is a low-level transport primitive only. Gateway approval UX must remain gateway-owned and add text fallback plus explicit confirmation semantics before approval prompts are ever mapped onto polls." Documented as "Approval prompts are **never** mapped onto polls." Returns `"Not connected"` without a running bridge, and a bridge-exit message when the managed bridge has died.
- **Rebuild notes:** A thin POST wrapper over the bridge. A better version would surface per-option vote counts back to the agent.

### WhatsApp clarify-as-poll  `id: platforms-a.whatsapp-clarify-poll`
- **Surface:** Platform:whatsapp
- **Where:** Any multiple-choice `clarify` question — rendered as a native single-select poll.
- **What it does:** Turns the agent's multiple-choice question into a tappable WhatsApp poll; selecting an option answers the question.
- **How it works:** `send_clarify()` at `plugins/platforms/whatsapp/adapter.py:1164`. Choices are stripped and empties dropped; when `2 <= len(clean_choices) <= 12` it calls `send_poll(..., selectable_count=1)`. When Baileys later emits a `poll_update` with the selected option as message text, the normal clarify **text-intercept** resolves the pending question and the blocked agent continues.
- **Inputs / options:** 2–12 choices route to a poll; anything else (including open-ended clarifies) falls through to the base text implementation.
- **Outputs / side effects:** A poll bubble, or a plain text question.
- **Config / env:** n/a.
- **Edge cases / guards:** A failed poll send logs `[whatsapp] Native WhatsApp clarify poll failed; falling back to text: %s` and degrades to the text prompt.
- **Rebuild notes:** Map choices → poll options and let the existing text intercept resolve the vote. A better version would resolve directly from the `poll_update` payload instead of round-tripping through text.

### WhatsApp location pins  `id: platforms-a.whatsapp-location`
- **Surface:** Platform:whatsapp / Tool
- **Where:** A native WhatsApp location bubble; incoming shared locations (including live locations) reach the agent as location messages.
- **What it does:** Sends and receives WhatsApp location pins.
- **How it works:** Outbound `send_location()` at `plugins/platforms/whatsapp/adapter.py:1205` POSTs `{"chatId", "latitude", "longitude", optional "name", optional "address"}` to `/send-location` (30 s timeout). Inbound: `_build_message_event()` (`:1495`) maps bridge `mediaType` `"location"` and `"live_location"` to `MessageType.LOCATION`.
- **Inputs / options:** `latitude` (float), `longitude` (float), `name`, `address`, `reply_to`, `metadata`.
- **Outputs / side effects:** A location bubble; `SendResult` with the bridge's `messageId`.
- **Config / env:** n/a.
- **Edge cases / guards:** Same not-connected / bridge-exit guards as the other send paths.
- **Rebuild notes:** Pass-through to the bridge. A better version would keep live-location updates flowing to the agent as a stream instead of one-shot events.

### WhatsApp media send (`/send-media`)  `id: platforms-a.whatsapp-send-media`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Any agent reply containing media; TTS replies.
- **What it does:** Uploads a local file to a WhatsApp chat as an image, video, audio/voice note, sticker or document with an optional caption.
- **How it works:** `_send_media_file()` at `plugins/platforms/whatsapp/adapter.py:1079` POSTs `{"chatId", "filePath", "mediaType", optional "caption", optional "fileName"}` to `/send-media` with a **120 s** timeout. The media type is chosen by `_bridge_media_type(file_path, is_voice, force_document)` at `:1719` using the extension sets `_WA_IMAGE_EXTS = {.jpg, .jpeg, .png, .webp, .gif}`, `_WA_VIDEO_EXTS = {.mp4, .mov, .avi, .mkv, .webm, .3gp}`, `_WA_AUDIO_EXTS = {.ogg, .opus, .mp3, .wav, .m4a, .flac}` (`:1714`).
- **Inputs / options:** `file_path`, `media_type`, `caption`, `file_name`; `is_voice` and `force_document` flags feeding the type mapper.
- **Outputs / side effects:** A native WhatsApp attachment. Missing file → `SendResult(success=False, error=f"File not found: {file_path}")`.
- **Config / env:** n/a.
- **Edge cases / guards:** When a short message accompanies a single attachment it rides as the `/send-media` `caption` instead of being posted as a separate `/send` message beforehand (`:1757`).
- **Rebuild notes:** Extension→type mapping with a document fallback. A better version would sniff the file's magic bytes rather than trusting the extension.

### WhatsApp inbound media handling & document text injection  `id: platforms-a.whatsapp-inbound-media`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — every inbound photo, video, voice note, audio file, sticker, location or document.
- **What it does:** Downloads or validates inbound media into the local cache, classifies it, and inlines the text of readable documents so the agent can read them without a tool call.
- **How it works:** `_build_message_event()` at `plugins/platforms/whatsapp/adapter.py:1487`. Type mapping from the bridge's `mediaType`: `"location"`/`"live_location"` → `LOCATION`; `"sticker"` → `STICKER`; else when `hasMedia` — `"image"` → `PHOTO`, `"video"` → `VIDEO`, `"ptt"` → `VOICE` (WhatsApp voice note), `"audio"` → `AUDIO`, otherwise `DOCUMENT`. HTTP URLs are fetched with `cache_image_from_url(url, ext=".jpg")` / `cache_audio_from_url(url, ext=".ogg")`; absolute paths must pass `_is_allowed_bridge_path`. MIME defaults: `image/jpeg`, `audio/ogg` (voice) or `audio/mpeg` (audio), `video/mp4`, `SUPPORTED_DOCUMENT_TYPES.get(ext, "application/octet-stream")` for documents, `"unknown"` otherwise. Document text injection: for extensions `.txt .md .csv .json .xml .yaml .yml .log .py .js .ts .html .css`, files up to `MAX_TEXT_INJECT_BYTES = 100 * 1024` are read (`errors="replace"`) and prepended as `[Content of <display_name>]:\n<content>` (the `doc_<hex>_` prefix is stripped from the display name).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Console lines verbatim: `[whatsapp] Cached user image: <path>`, `[whatsapp] Failed to cache image: <e>`, `[whatsapp] Cached user audio: <path>`, `[whatsapp] Failed to cache audio: <e>`, `[whatsapp] Using bridge-cached image|audio|document|video: <url>`, `[whatsapp] Rejected bridge image|audio|document|video path outside cache dir: <url>`, `[whatsapp] Skipping text injection for <path> (<size> bytes > 102400)`, `[whatsapp] Injected text content from: <path>`, `[whatsapp] Failed to read document text: <e>`, `[whatsapp] Error building event: <e>`.
- **Config / env:** `HERMES_IMAGE_CACHE_DIR`, `HERMES_AUDIO_CACHE_DIR`, `HERMES_DOCUMENT_CACHE_DIR`.
- **Edge cases / guards:** The bridge synthesizes the placeholder body `[ptt received]` for captionless voice notes; the adapter blanks it (`body = ""`) so the agent answers the audio rather than the placeholder. Quoted messages are kept in structured fields only (`reply_to_message_id`, `reply_to_text`, `reply_to_author_id`, `reply_to_is_own_message`) — the `[Replying to: …]` pointer is rendered once by `GatewayRunner._prepare_inbound_message_text`, so pre-rendering here would double the quote. The 100 KB injection cap matches Telegram/Discord/Slack.
- **Rebuild notes:** Cache first, classify second, inject readable text third. A better version would inject a summary plus a handle for large documents instead of skipping them entirely.

### WhatsApp voice messages (STT / TTS)  `id: platforms-a.whatsapp-voice`
- **Surface:** Platform:whatsapp
- **Where:** WhatsApp voice notes in, MP3 attachments out.
- **What it does:** Transcribes inbound voice notes and can answer with synthesized speech.
- **How it works:** Inbound `ptt` media becomes `MessageType.VOICE` and is cached as `.ogg`; the gateway's STT stage transcribes it. Outbound TTS is delivered through `_send_media_file()` as an audio attachment.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Transcript text in the turn; MP3 attachments in the chat.
- **Config / env:** `stt_enabled`; STT providers — local `faster-whisper`, Groq Whisper (`GROQ_API_KEY`), OpenAI Whisper (`VOICE_TOOLS_OPENAI_KEY`).
- **Edge cases / guards:** WhatsApp voice notes are `.ogg` opus.
- **Rebuild notes:** Cache with the right extension and hand off to the shared STT stage. A better version would send replies as real WhatsApp voice notes (`ptt: true`) rather than plain audio files.

### WhatsApp read receipts (`send_read_receipts`)  `id: platforms-a.whatsapp-read-receipts`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `whatsapp.send_read_receipts` in `~/.hermes/config.yaml`; visible as blue ticks on the sender's phone.
- **What it does:** Marks policy-accepted inbound messages as read.
- **How it works:** `_send_read_receipt()` at `plugins/platforms/whatsapp/adapter.py:1411` POSTs `{"key": <readReceiptKey>}` to `/read` (5 s timeout), fired via `asyncio.create_task` from the poll loop so a slow bridge cannot delay dispatch. The flag is also passed to the bridge as `WHATSAPP_SEND_READ_RECEIPTS` and reported back in `/health` as `sendReadReceipts`.
- **Inputs / options:** `whatsapp.send_read_receipts: true|false` (default `false`); accepts booleans or the strings `1`, `true`, `yes`, `on`.
- **Outputs / side effects:** Blue ticks. Failures log `[whatsapp] WhatsApp read receipt failed with HTTP %s` or `[whatsapp] WhatsApp read receipt failed: %s`.
- **Config / env:** `whatsapp.send_read_receipts`, `WHATSAPP_SEND_READ_RECEIPTS`.
- **Edge cases / guards:** Only messages that pass DM/group/mention filtering are marked — "Rejected messages (e.g., from non-allowlisted senders) are not marked read. Disabled by default for privacy." Changing the setting **restarts the bridge subprocess** on the next connection (it is part of the staleness handshake).
- **Rebuild notes:** Send the receipt after admission, never before. A better version would also support typing-then-read ordering to look more natural.

### WhatsApp typing indicator  `id: platforms-a.whatsapp-typing`
- **Surface:** Core (Platform:whatsapp)
- **Where:** The "typing…" presence in the chat.
- **What it does:** Shows a typing indicator while the agent works.
- **How it works:** POSTs `{"chatId": to_whatsapp_jid(chat_id)}` to `/typing` with a 5 s timeout (`plugins/platforms/whatsapp/adapter.py:1336`), wrapped in `async with` — a bare `await session.post(...)` would leave the response alive until GC, holding its TCP socket in `CLOSE_WAIT`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Presence update; failures are ignored.
- **Config / env:** n/a.
- **Edge cases / guards:** All exceptions are swallowed ("Ignore typing indicator failures").
- **Rebuild notes:** Fire-and-forget presence POST with a short timeout. A better version would refresh the presence periodically so it does not lapse on long turns.

### WhatsApp owner-message forwarding (`[owner reply]`)  `id: platforms-a.whatsapp-owner-messages`
- **Surface:** Config (Platform:whatsapp)
- **Where:** Invisible — messages the human owner types from their own linked device inside a chat the bot also watches.
- **What it does:** Lets plugins and the agent see that the human owner just replied in a customer chat, without confusing it with the bot's own echo.
- **How it works:** The bridge sets `fromOwner: true` on inbound `fromMe` messages that look owner-typed (a linked-device send, **not** an echo of the adapter's own `/send`). The adapter sets `metadata["whatsapp_from_owner"] = True` and prefixes `MessageEvent.text` with the constant `_OWNER_REPLY_PREFIX = "[owner reply] "` (`plugins/platforms/whatsapp/adapter.py:62`) so the marker survives any downstream failure — e.g. handover-rule errors that bypass `silent_ingest`.
- **Inputs / options:** `WHATSAPP_FORWARD_OWNER_MESSAGES` (bridge-layer gate).
- **Outputs / side effects:** `metadata.whatsapp_from_owner` plus the text prefix.
- **Config / env:** `WHATSAPP_FORWARD_OWNER_MESSAGES`.
- **Edge cases / guards:** The prefix is only added when it is not already present. Metadata + text tagging are unconditional when the flag is present, so a future producer can set it without adapter changes.
- **Rebuild notes:** Distinguish "sent by us" from "sent by the human on another device" at the bridge and tag both metadata and text. A better version would carry the owner's device id so multi-operator chats can be attributed.

### WhatsApp native message metadata passthrough  `id: platforms-a.whatsapp-native-metadata`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — `MessageEvent.metadata`.
- **What it does:** Surfaces the bridge's native WhatsApp message type and its raw metadata to plugins.
- **How it works:** `_build_message_event()` at `plugins/platforms/whatsapp/adapter.py:1651` sets `metadata["whatsapp_native_type"] = data["nativeType"]` when present and `metadata["whatsapp_native"] = data["nativeMetadata"]` when it is a non-empty dict.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Extra metadata keys.
- **Config / env:** n/a.
- **Edge cases / guards:** Non-dict `nativeMetadata` is ignored.
- **Rebuild notes:** Pass unknown native types through untouched rather than dropping them. A better version would type these payloads so plugins can rely on their shape.

### WhatsApp chat info lookup  `id: platforms-a.whatsapp-chat-info`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — session naming and group detection.
- **What it does:** Resolves a chat's display name, type and participant list from the bridge.
- **How it works:** `get_chat_info()` at `plugins/platforms/whatsapp/adapter.py:1344` GETs `/chat/<jid>` (10 s timeout) and returns `{"name", "type": "group"|"dm", "participants": [...]}`.
- **Inputs / options:** `chat_id`.
- **Outputs / side effects:** Falls back to `{"name": chat_id, "type": "dm"}` on any failure; not-connected returns `{"name": "Unknown", "type": "dm"}`. Failures log `Could not get WhatsApp chat info for %s: %s` at DEBUG.
- **Config / env:** n/a.
- **Edge cases / guards:** Never raises.
- **Rebuild notes:** One GET with a safe default. A better version would cache chat metadata with a TTL.

### WhatsApp home chat & cron delivery  `id: platforms-a.whatsapp-home-channel`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `WHATSAPP_HOME_CHANNEL` / `WHATSAPP_HOME_CHANNEL_NAME`.
- **What it does:** Names the default WhatsApp chat for cron results and proactive notifications.
- **How it works:** Registered as `cron_deliver_env_var="WHATSAPP_HOME_CHANNEL"` (`plugins/platforms/whatsapp/adapter.py:1971`).
- **Inputs / options:** A WhatsApp chat ID / JID.
- **Outputs / side effects:** Scheduled messages delivered there.
- **Config / env:** `WHATSAPP_HOME_CHANNEL`, `WHATSAPP_HOME_CHANNEL_NAME`.
- **Edge cases / guards:** Delivery out of process uses the standalone sender below.
- **Rebuild notes:** One env var consulted by the cron dispatcher. A better version would validate the JID at save time.

### WhatsApp standalone (out-of-process) sender  `id: platforms-a.whatsapp-standalone-send`
- **Surface:** Core (Platform:whatsapp)
- **Where:** Invisible — cron or `send_message` running outside the gateway process.
- **What it does:** Posts text and media to a WhatsApp chat by talking directly to the running bridge.
- **How it works:** `_standalone_send()` at `plugins/platforms/whatsapp/adapter.py:1745`, registered as `standalone_sender_fn`. Per chunk it (1) POSTs text to `http://localhost:<bridge_port>/send` — skipped when the chunk is media-only — then (2) POSTs each media file to `/send-media`; a short message accompanying a single attachment rides as the `caption` instead of a preceding `/send`.
- **Inputs / options:** `bridge_port` from `extra` (default `3000`); `MEDIA:<path>` entries in the message.
- **Outputs / side effects:** Real WhatsApp messages/attachments.
- **Config / env:** `gateway.platforms.whatsapp.extra.bridge_port`.
- **Edge cases / guards:** Requires the bridge to already be running (WhatsApp auth lives entirely in the Node process, so there is no token the Python side could use on its own).
- **Rebuild notes:** Reuse the bridge as the single send seam for both in- and out-of-process callers. A better version would fall back to starting the bridge when it is not running.

### WhatsApp unauthorized-DM behaviour  `id: platforms-a.whatsapp-unauthorized`
- **Surface:** Config (Platform:whatsapp)
- **Where:** `whatsapp.unauthorized_dm_behavior` (platform) or the global `unauthorized_dm_behavior`.
- **What it does:** Decides whether an unknown WhatsApp sender gets a pairing code or is silently ignored.
- **How it works:** The platform key overrides the global one; consumed by the gateway's pairing path once `dm_policy` has allowed intake.
- **Inputs / options:** `pair` (global default — "Unknown DM senders get a pairing code"), `ignore` ("makes WhatsApp stay silent for unauthorized DMs, which is usually the better choice for a private number").
- **Outputs / side effects:** A pairing prompt or silence.
- **Config / env:** `whatsapp.unauthorized_dm_behavior`, `unauthorized_dm_behavior`.
- **Edge cases / guards:** Troubleshooting row verbatim: "Bot replies to strangers with a pairing code | Set `whatsapp.unauthorized_dm_behavior: ignore` in `~/.hermes/config.yaml` if you want unauthorized DMs to be silently ignored instead."
- **Rebuild notes:** A per-platform override of a global enum. A better version would add a `pair-once` mode that stops re-prompting the same number.

### WhatsApp troubleshooting matrix  `id: platforms-a.whatsapp-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/whatsapp.md:243`.
- **What it does:** Maps each observed WhatsApp failure to its fix.
- **How it works:** Static documentation mirroring the bridge's real failure modes.
- **Inputs / options:** Rows verbatim (Problem → Solution): "**QR code not scanning**" → "Ensure terminal is wide enough (60+ columns). Try a different terminal. Make sure you're scanning from the correct WhatsApp account (bot number, not personal)."; "**QR code expires**" → "QR codes refresh every ~20 seconds. If it times out, restart `hermes whatsapp`."; "**Session not persisting**" → "Check that `~/.hermes/platforms/whatsapp/session` exists and is writable. If containerized, mount it as a persistent volume."; "**Logged out unexpectedly**" → "WhatsApp unlinks devices after long inactivity. Keep the phone on and connected to the network, then re-pair with `hermes whatsapp` if needed."; "**Bridge crashes or reconnect loops**" → "Restart the gateway, update Hermes, and re-pair if the session was invalidated by a WhatsApp protocol change."; "**Bot stops working after WhatsApp update**" → "Update Hermes to get the latest bridge version, then re-pair."; "**macOS: \"Node.js not installed\" but node works in terminal**" → "launchd services don't inherit your shell PATH. Run `hermes gateway install` to re-snapshot your current PATH into the plist, then `hermes gateway start`."; "**Messages not being received**" → "Verify `WHATSAPP_ALLOWED_USERS` includes the sender's number (with country code, no `+` or spaces), or set it to `*` to allow everyone. Set `WHATSAPP_DEBUG=true` in `.env` and restart the gateway to see raw message events in `bridge.log`."; "**Bot replies to strangers with a pairing code**" → "Set `whatsapp.unauthorized_dm_behavior: ignore` …".
- **Outputs / side effects:** n/a.
- **Config / env:** `WHATSAPP_DEBUG`.
- **Edge cases / guards:** Security guidance verbatim: "The `~/.hermes/platforms/whatsapp/session` directory contains full session credentials — protect it like a password"; "Set file permissions: `chmod 700 ~/.hermes/platforms/whatsapp/session`"; "Use a **dedicated phone number** for the bot to isolate risk from your personal account"; "If you suspect compromise, unlink the device from WhatsApp → Settings → Linked Devices"; "Phone numbers in logs are partially redacted, but review your log retention policy".
- **Rebuild notes:** Ship the checks as runtime diagnostics. A better version would surface bridge health and last-connect state in `hermes gateway status`.

---

## 4. Matrix

### Matrix platform adapter  `id: platforms-a.matrix`
- **Surface:** Platform:matrix
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Matrix"** (emoji 🔐); runs inside `hermes gateway`. In Matrix itself: DM rooms, group rooms, MSC3440 threads, on any homeserver (Synapse, Conduit, Dendrite, matrix.org).
- **What it does:** Connects Hermes to any Matrix homeserver over the `mautrix` SDK, relaying room and DM events into the agent and posting formatted (HTML + plain) replies, with optional end-to-end encryption, threads, reaction controls, media and voice.
- **How it works:** `plugins/platforms/matrix/adapter.py:1173` defines `MatrixAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/matrix/adapter.py:5444` calls `ctx.register_platform(name="matrix", label="Matrix", adapter_factory=_build_adapter, check_fn=matrix_deps_present, ensure_deps_fn=ensure_matrix_deps, is_connected=_is_connected, required_env=["MATRIX_HOMESERVER","MATRIX_ACCESS_TOKEN"], install_hint="pip install 'mautrix[encryption]'", setup_fn=interactive_setup, apply_yaml_config_fn=_apply_yaml_config, allowed_users_env="MATRIX_ALLOWED_USERS", allow_all_env="MATRIX_ALLOW_ALL_USERS", cron_deliver_env_var="MATRIX_HOME_ROOM", standalone_sender_fn=_standalone_send, max_message_length=DEFAULT_MAX_MESSAGE_LENGTH, emoji="🔐", allow_update_command=True)`. Manifest `plugins/platforms/matrix/plugin.yaml:1` (`name: matrix-platform`, `label: Matrix`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). Message size: `DEFAULT_MAX_MESSAGE_LENGTH = 16000`, `MATRIX_MAX_MESSAGE_LENGTH_CEILING = 65535`, resolved by `_resolve_max_message_length()` (`:569`) which clamps to `max(500, min(value, 65535))` and reads `extra.max_message_length` → `MATRIX_MAX_MESSAGE_LENGTH` → the platform registry entry → the default. Store: `_STORE_DIR = get_hermes_dir("platforms/matrix/store", "matrix/store")` with `_CRYPTO_DB_PATH = <store>/crypto.db` (`:600`). Startup filter: `_STARTUP_GRACE_SECONDS = 5` (`:604`). Sync: an explicit loop that calls `client.handle_sync()` on the initial **and** every incremental sync response (a bare `client.sync()` would leave sends working while inbound never reaches `_on_room_message`), retrying every 5 s on error, while keeping Hermes's own background maintenance tasks (joined-room tracking, invite handling, E2EE key share). `_is_duplicate_event()` (`:1383`) tracks event IDs in a bounded deque + set. `_create_matrix_session(proxy_url)` (`:753`) builds the HTTP session with proxy support.
- **Inputs / options:** Env, verbatim from the module docstring (`plugins/platforms/matrix/adapter.py:7-50`): `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`, `MATRIX_USER_ID`, `MATRIX_PASSWORD`, `MATRIX_ENCRYPTION`, `MATRIX_E2EE_MODE`, `MATRIX_DEVICE_ID`, `MATRIX_PROXY`, `MATRIX_ALLOWED_USERS`, `MATRIX_ALLOWED_ROOMS`, `MATRIX_HOME_ROOM`, `MATRIX_REACTIONS`, `MATRIX_REQUIRE_MENTION`, `MATRIX_FREE_RESPONSE_ROOMS`, `MATRIX_IGNORE_USER_PATTERNS`, `MATRIX_PROCESS_NOTICES`, `MATRIX_ALLOW_ROOM_MENTIONS`, `MATRIX_TOOLS_ALLOW_REDACTION`, `MATRIX_TOOLS_ALLOW_INVITES`, `MATRIX_TOOLS_ALLOW_ROOM_CREATE`, `MATRIX_AUTO_THREAD`, `MATRIX_DM_AUTO_THREAD`, `MATRIX_RECOVERY_KEY`, `MATRIX_DM_MENTION_THREADS`, `MATRIX_ALLOW_PUBLIC_ROOMS`, `MATRIX_MAX_MESSAGE_LENGTH`, `MATRIX_APPROVAL_REQUIRE_SENDER`, `MATRIX_APPROVAL_TIMEOUT_SECONDS`. Also read in code: `MATRIX_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`, `MATRIX_THREAD_REQUIRE_MENTION`, `MATRIX_SESSION_SCOPE`, `MATRIX_MAX_MEDIA_BYTES`, `MATRIX_ROOM_IDENTITY_TTL_SECONDS`, `MATRIX_RECOVERY_KEY_OUTPUT_FILE`, `HERMES_MATRIX_TEXT_BATCH_DELAY_SECONDS`, `HERMES_MATRIX_TEXT_BATCH_SPLIT_DELAY_SECONDS`.
- **Outputs / side effects:** Joins rooms, posts `m.text` / `m.image` / `m.audio` / `m.video` / `m.file` events, reactions, redactions, typing notifications and read receipts; writes `~/.hermes/platforms/matrix/store/` (sync state + `crypto.db`).
- **Config / env:** `matrix.require_mention` (default `true`), `matrix.free_response_rooms` (`""`), `matrix.allowed_rooms` (`""`), `matrix.allowed_users`, `matrix.ignore_user_patterns`, `matrix.process_notices`, `matrix.session_scope`, `matrix.auto_thread`, `matrix.dm_mention_threads`, `matrix.max_message_length`, `group_sessions_per_user`.
- **Edge cases / guards:** Hermes always ignores its own events, Matrix appservice-style users whose localpart starts with `_`, duplicate event IDs, old startup events, edit replacement events, and `m.notice` events by default. Inbound media must use `mxc://` content URIs — arbitrary HTTP(S) media URLs in Matrix events are rejected "to avoid turning a federated room into an unrestricted downloader". Security warning verbatim: "Always set `MATRIX_ALLOWED_USERS` and, for shared/private deployments, `MATRIX_ALLOWED_ROOMS`. Without them, anyone who can message the bot in a joined room may trigger the agent."
- **Rebuild notes:** Minimal spec: mautrix `Client` with an explicit sync loop that dispatches through `handle_sync()`, an event-ID dedup ring, a startup-time filter, and a send path that emits `format`/`formatted_body` HTML alongside the plain body. A better version would persist the sync token so a restart resumes exactly instead of relying on a grace window.

### Matrix capability matrix  `id: platforms-a.matrix-capabilities`
- **Surface:** Docs / Core
- **Where:** `website/docs/user-guide/messaging/matrix.md:32`; produced in code by `get_matrix_capabilities()`.
- **What it does:** Declares, as data, which Matrix features the adapter supports — the table the docs render and release checks assert against.
- **How it works:** `_MATRIX_CAPABILITIES` at `plugins/platforms/matrix/adapter.py:653`, returned as a copy by `get_matrix_capabilities()` (`:673`).
- **Inputs / options:** The complete map, verbatim: `text: yes`, `threads: yes`, `reactions: yes`, `approvals: yes`, `model picker: yes`, `thinking panes: yes`, `images: yes`, `multiple images: yes`, `files: yes`, `voice/audio: yes`, `video: yes`, `E2EE: off / optional / required`, `diagnostics: yes`.
- **Outputs / side effects:** A dict.
- **Config / env:** n/a.
- **Edge cases / guards:** E2EE is mode-based rather than a boolean "because deployments choose whether encrypted rooms are disabled, opportunistic, or required".
- **Rebuild notes:** Keep the capability table in code and render docs from it. A better version would generate the table for every adapter so cross-platform gaps are visible at a glance.

### Matrix interactive setup wizard  `id: platforms-a.matrix-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Matrix**.
- **What it does:** Collects the homeserver URL and credentials (token or password), optionally enables E2EE and installs its dependencies, sets an allowlist and a home room.
- **How it works:** `interactive_setup()` at `plugins/platforms/matrix/adapter.py:5272`. E2EE installs are attempted first through `tools.lazy_deps.ensure("platform.matrix", prompt=False)` and fall back to `hermes_cli.tools_config._pip_install([matrix_pkg])`.
- **Inputs / options:** Verbatim strings in order:
  - header `Matrix`
  - `Matrix: already configured` (when `MATRIX_ACCESS_TOKEN` or `MATRIX_PASSWORD` exists) + `Reconfigure Matrix?` (yes/no, default `False`)
  - `Works with any Matrix homeserver (Synapse, Conduit, Dendrite, or matrix.org).`
  - `   1. Create a bot user on your homeserver, or use your own account`
  - `   2. Get an access token from Element, or provide user ID + password`
  - prompt `Homeserver URL (e.g. https://matrix.example.org)` (trailing `/` stripped on save)
  - `Auth: provide an access token (recommended), or user ID + password.`
  - prompt `Access token (leave empty for password login)` (password)
  - token path → prompt `User ID (@bot:server — optional, will be auto-detected)`, then `Matrix access token saved`
  - password path → prompt `User ID (@bot:server)`, prompt `Password` (password), then `Matrix credentials saved`
  - `Enable end-to-end encryption (E2EE)?` (yes/no, default `False`) → `E2EE enabled`
  - `Installing <mautrix|mautrix[encryption]> (+ N runtime deps)...` → `<pkg> installed` or `Install failed — run manually: pip install 'mautrix[encryption]' asyncpg aiosqlite Markdown aiohttp-socks` + `  Error: <exc>`; the non-lazy fallback prints `Installing <pkg>...` and on failure `Install failed — run manually: uv pip install '<pkg>' asyncpg aiosqlite Markdown aiohttp-socks`
  - `🔒 Security: Restrict who can use your bot`
  - `   Matrix user IDs look like @username:server`
  - prompt `Allowed user IDs (comma-separated, leave empty for open access)` → `Matrix allowlist configured` or `⚠️  No allowlist set - anyone who can message the bot can use it!`
  - `📬 Home Room: where Hermes delivers cron job results and notifications.`
  - `   Room IDs look like !abc123:server (shown in Element room settings)`
  - `   You can also set this later by typing /set-home in a Matrix room.`
  - `Leave blank to clear a previously saved home room (cron / notifications).`
  - prompt `Home room ID (leave empty to set later with /set-home)` → `Home room cleared.` when blanked
- **Outputs / side effects:** Writes `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN` or `MATRIX_PASSWORD`, `MATRIX_USER_ID`, `MATRIX_ENCRYPTION`, `MATRIX_ALLOWED_USERS`, `MATRIX_HOME_ROOM`.
- **Config / env:** as above.
- **Edge cases / guards:** The allowlist / home-room block only runs when a token or password was captured.
- **Rebuild notes:** Prompt sequence + optional dependency install. A better version would verify the token with `/_matrix/client/v3/account/whoami` before saving it.

### Matrix E2EE modes  `id: platforms-a.matrix-e2ee`
- **Surface:** Config (Platform:matrix)
- **Where:** `MATRIX_E2EE_MODE` in `~/.hermes/.env` (legacy: `MATRIX_ENCRYPTION=true`).
- **What it does:** Chooses whether the bot participates in end-to-end-encrypted Matrix rooms, and whether it fails closed when crypto is unavailable.
- **How it works:** `_resolve_e2ee_mode(extra)` at `plugins/platforms/matrix/adapter.py:819` prefers `extra["e2ee_mode"]` / `MATRIX_E2EE_MODE`, else maps legacy `extra["encryption"]` / `MATRIX_ENCRYPTION` truthiness to `required`. `_normalize_e2ee_mode()` (`:809`) accepts `required`/`require`/`true`/`1`/`yes`/`on` → `"required"`, `optional`/`prefer`/`preferred` → `"optional"`, anything else → `"off"`. `_check_e2ee_deps()` (`:786`) requires **four** imports — `mautrix.crypto.OlmMachine`, `mautrix.crypto.store.asyncpg.PgCryptoStore` (which also drives the SQLite backend in mautrix 0.21), `asyncpg` (for the upgrade-table machinery), and `aiosqlite` (for the `sqlite:///` URL passed to `Database.create`) — otherwise encrypted rooms fail at connect with a confusing `No module named 'asyncpg'`. Crypto state is wrapped by `_CryptoStateStore` (`:1105`). Install hint constant `_E2EE_INSTALL_HINT` (`:608`): `Install with: pip install 'mautrix[encryption]' asyncpg aiosqlite  (requires libolm C library)`.
- **Inputs / options:** `off` — "Do not initialize Matrix E2EE."; `optional` — "Try E2EE when dependencies are available, but keep unencrypted rooms working if crypto cannot initialize."; `required` — "Fail closed if E2EE dependencies or crypto setup are not available."
- **Outputs / side effects:** Encryption keys stored in `~/.hermes/platforms/matrix/store/` (legacy installs: `~/.hermes/matrix/store/`); device keys uploaded on first connection; incoming messages decrypted and outgoing encrypted automatically; encrypted rooms auto-joined on invite.
- **Config / env:** `MATRIX_E2EE_MODE`, `MATRIX_ENCRYPTION`, `MATRIX_DEVICE_ID` (stable device ID for E2EE persistence across restarts).
- **Edge cases / guards:** System requirements: `libolm` (`sudo apt install libolm-dev` / `brew install libolm` / `sudo dnf install libolm-devel`) plus `pip install 'mautrix[encryption]'` or `uv pip install -e ".[matrix]"`. Deleting `crypto.db` loses the encryption identity and restarting with the same device ID does **not** fully recover — the homeserver still holds one-time keys signed with the old identity key; Hermes detects this and refuses to enable E2EE, logging verbatim `device XXXX has stale one-time keys on the server signed with a previous identity key`. Recovery: generate a new access token (fresh device ID), or manually delete the device rows (`e2e_device_keys_json`, `e2e_one_time_keys_json`, `e2e_fallback_keys_json`, `devices`) from Synapse and `rm -f ~/.hermes/platforms/matrix/store/crypto.db*`; then `/discardsession` in Element. Without `mautrix[encryption]` or `libolm` the bot falls back to a plain unencrypted client with a log warning. macOS ARM64 cannot compile `libolm` — the `hermes-agent[matrix]` extra is Linux-gated; use Proxy Mode.
- **Rebuild notes:** A tri-state mode with an explicit dependency probe covering every import the connect path touches. A better version would run the probe at config-save time so `required` never surprises at startup.

### Matrix cross-signing verification (`MATRIX_RECOVERY_KEY`)  `id: platforms-a.matrix-cross-signing`
- **Surface:** Config (Platform:matrix)
- **Where:** `MATRIX_RECOVERY_KEY` in `~/.hermes/.env`; the key comes from Element → **Settings → Security & Privacy → Encryption →** your recovery key (also called the "Security Key").
- **What it does:** Lets the bot self-sign its own device on startup so other Matrix clients keep sharing encryption sessions with it after a device-key rotation.
- **How it works:** `_scoped_recovery_key()` at `plugins/platforms/matrix/adapter.py:921` reads the key through `agent.secret_scope.get_secret` so a multiplexed profile gets its **own** key (a bare `os.getenv` would resolve the default profile's key and fail with "Key MAC does not match"); an `UnscopedSecretError` falls back to `os.environ`, which in that context is the profile's own value. On each startup, when the key is set, Hermes imports cross-signing keys from the homeserver's secure secret storage and signs the current device — idempotent and safe to leave enabled permanently.
- **Inputs / options:** `MATRIX_RECOVERY_KEY=EsT...`; `MATRIX_RECOVERY_KEY_OUTPUT_FILE=/secure/path/matrix-recovery-key.txt`.
- **Outputs / side effects:** When Hermes **bootstraps a new** recovery key it never logs the raw key. `_write_matrix_recovery_key_output_file()` (`:840`) creates the file with `os.O_WRONLY | os.O_CREAT | os.O_EXCL` and mode `0600` and never overwrites. `_get_matrix_recovery_key_output_target()` (`:866`) returns the reasons `not_configured`, `exists`, or `unusable: <exc>`. `_handle_generated_matrix_recovery_key()` (`:881`) emits one of three warnings, verbatim: `Matrix: bootstrapped cross-signing for %s. Recovery key output file already exists; refusing to overwrite. Store the generated key securely and set MATRIX_RECOVERY_KEY for future restarts.`; `Matrix: bootstrapped cross-signing for %s, but failed to write MATRIX_RECOVERY_KEY_OUTPUT_FILE: %s. Store the generated key securely and set MATRIX_RECOVERY_KEY for future restarts.`; `Matrix: bootstrapped cross-signing for %s. A new recovery key was written to %s with mode 0600. Move it to your secret store and set MATRIX_RECOVERY_KEY for future restarts.`; and when no output file is configured, `Matrix: bootstrapped cross-signing for %s. A new recovery key was generated but will not be logged. Set MATRIX_RECOVERY_KEY_OUTPUT_FILE to write it once with mode 0600, or configure MATRIX_RECOVERY_KEY from your Matrix client before future restarts.`
- **Config / env:** `MATRIX_RECOVERY_KEY`, `MATRIX_RECOVERY_KEY_OUTPUT_FILE`.
- **Edge cases / guards:** Recovery keys are never written to logs or diagnostics — `_redact_matrix_value()` (`:832`) returns `"***"` for any non-empty value.
- **Rebuild notes:** Read the key scope-aware, sign once at startup, and write generated keys with `O_EXCL` + `0600`. A better version would offer an interactive one-time verification flow instead of requiring the recovery key at all.

### Matrix mention & threading configuration  `id: platforms-a.matrix-mention-threading`
- **Surface:** Config (Platform:matrix)
- **Where:** `matrix:` block in `~/.hermes/config.yaml` or the matching `MATRIX_*` env vars.
- **What it does:** Controls when the bot answers in rooms, whether it creates threads, and which users/rooms may trigger it.
- **How it works:** `_parse_require_mention()` at `plugins/platforms/matrix/adapter.py:1397` (explicit-false parsing — `false`/`0`/`no`/`off` disable; default `true`); `_parse_thread_require_mention()` at `:1416` (truthy parsing — `true`/`1`/`yes`/`on`; default `false`); `_is_bot_mentioned()` at `:4918`; `_strip_mention()` at `:4951`; `_matches_ignored_user_pattern()` at `:3183`; `_is_allowed_matrix_room()` at `:3187`; `_is_self_sender()` at `:3127`; `_is_system_or_bridge_sender()` at `:3147`. YAML→env translation in `_apply_yaml_config()` (`:5376`), env always winning.
- **Inputs / options:** Complete YAML block with defaults, verbatim from the docs:
  - `require_mention: true` — "Require @mention in rooms (default: true)" — env `MATRIX_REQUIRE_MENTION`
  - `allowed_users:` — "Matrix users allowed to trigger agent turns" (e.g. `- "@alice:matrix.org"`) — env `MATRIX_ALLOWED_USERS`
  - `allowed_rooms:` — "Matrix rooms allowed to trigger agent turns" (e.g. `- "!abc123:matrix.org"`) — env `MATRIX_ALLOWED_ROOMS`
  - `free_response_rooms:` — "Rooms exempt from mention requirement" — env `MATRIX_FREE_RESPONSE_ROOMS`
  - `ignore_user_patterns:` — "Bridge/appservice ghost users to ignore" (e.g. `- "^@telegram_"`, `- "^@whatsapp_"`) — env `MATRIX_IGNORE_USER_PATTERNS`
  - `process_notices: false` — "Ignore m.notice by default" — env `MATRIX_PROCESS_NOTICES`
  - `session_scope: room` — "auto|room|thread; room is recommended for project rooms" — env `MATRIX_SESSION_SCOPE`
  - `auto_thread: true` — "Auto-create threads for responses (default: true)" — env `MATRIX_AUTO_THREAD`
  - `dm_mention_threads: false` — "Create thread when @mentioned in DM (default: false)" — env `MATRIX_DM_MENTION_THREADS`
  - `max_message_length: 16000` — "Outbound chunk size in chars (default: 16000, max: 65535)" — env `MATRIX_MAX_MESSAGE_LENGTH`
  - env-only: `MATRIX_DM_AUTO_THREAD` (default `false`), `MATRIX_THREAD_REQUIRE_MENTION` (default `false`), `MATRIX_REACTIONS=true`, `MATRIX_ALLOW_ROOM_MENTIONS=false`
- **Outputs / side effects:** Admission decisions and thread creation.
- **Config / env:** as enumerated.
- **Edge cases / guards:** Behaviour table, verbatim: **DMs** — "Hermes responds to every message. No `@mention` needed. Each DM has its own session."; **Rooms** — "By default, Hermes requires an `@mention` to respond… Room invites are auto-accepted."; **Threads** — "Hermes supports Matrix threads (MSC3440)… Threads where the bot has already participated do not require a mention."; **Auto-threading** — "By default, Hermes auto-creates a thread for each message it responds to in a room… `MATRIX_DM_AUTO_THREAD=true` (default false) to also auto-create threads for DM messages — this is distinct from `MATRIX_DM_MENTION_THREADS`, which only starts a thread when the bot is `@mentioned` in a DM."; **Shared rooms** — "By default, Hermes isolates session history per user inside the room." Upgrade note: installs predating `MATRIX_REQUIRE_MENTION` answered every room message; set `MATRIX_REQUIRE_MENTION=false` to preserve that. Invalid ignore patterns log `Matrix: ignoring invalid MATRIX_IGNORE_USER_PATTERNS entry %r: %s`.
- **Rebuild notes:** Independent gates for sender allowlist, room allowlist, ghost-user patterns, notices, and the mention/thread rules. A better version would let `session_scope` be set per room.

### Matrix session scope (`MATRIX_SESSION_SCOPE`)  `id: platforms-a.matrix-session-scope`
- **Surface:** Config (Platform:matrix)
- **Where:** `matrix.session_scope` / `MATRIX_SESSION_SCOPE`.
- **What it does:** Chooses how unthreaded room messages map onto sessions — the key setting for using one bot across several project rooms.
- **How it works:** Combined with `group_sessions_per_user` (which controls whether users inside a room share the lane) to build the session key.
- **Inputs / options:** Three values, verbatim: `auto` — "Backward-compatible default. Existing `MATRIX_AUTO_THREAD` behavior controls synthetic threads."; `room` — "Unthreaded room messages stay in one stable room session. Real Matrix threads still use their thread root."; `thread` — "Unthreaded room messages synthesize a thread/session from the triggering event ID." Recommended project-room profile: `MATRIX_SESSION_SCOPE=room` + `MATRIX_AUTO_THREAD=false`.
- **Outputs / side effects:** Session keys; `/status` shows the current Matrix room/session scope.
- **Config / env:** `MATRIX_SESSION_SCOPE`, `MATRIX_AUTO_THREAD`, `group_sessions_per_user`.
- **Edge cases / guards:** Hermes includes the current Matrix room name, room ID, topic, message ID and a room-boundary note in the agent prompt. `/resume` "will not silently resume a named session from another Matrix room unless you explicitly use `/resume --cross-room <session name>`". Default session model: each DM gets its own session, each thread its own session namespace, each user in a shared room their own session inside that room. With `group_sessions_per_user: false` "users share context growth and token costs, one person's long tool-heavy task can bloat everyone else's context, and one person's in-flight run can interrupt another person's follow-up in the same room".
- **Rebuild notes:** Make the room/thread lane and the per-user split two orthogonal settings. A better version would name sessions after the room so `/resume` lists them readably.

### Matrix room identity & prompt context  `id: platforms-a.matrix-room-identity`
- **Surface:** Core (Platform:matrix)
- **Where:** Invisible — injected into the agent prompt and used for routing.
- **What it does:** Resolves a room's human identity (name, topic, alias, member count, DM-ness) and feeds it to the agent so it knows which project room it is in.
- **How it works:** `MatrixRoomIdentity` dataclass at `plugins/platforms/matrix/adapter.py:494` — frozen, fields `room_id`, `room_name`, `room_topic`, `canonical_alias`, `server_name`, `joined_member_count`, `is_direct_account_data`, `display_name`, `has_explicit_name`, `chat_type`, `conflict` (default `False`). Cached by `_cache_room_identity()` (`:4663`) with a TTL from `MATRIX_ROOM_IDENTITY_TTL_SECONDS`; state values read via `_state_event_value()` (`:4572`); server derived by `_room_server_name()` (`:4657`).
- **Inputs / options:** `MATRIX_ROOM_IDENTITY_TTL_SECONDS`.
- **Outputs / side effects:** Prompt context and session naming; `conflict` marks ambiguous display names.
- **Config / env:** `MATRIX_ROOM_IDENTITY_TTL_SECONDS`.
- **Edge cases / guards:** Falls back to the room ID when there is no explicit name.
- **Rebuild notes:** Cache room state with a TTL and expose it as one immutable record. A better version would invalidate the cache on `m.room.name`/`m.room.topic` state events instead of waiting for the TTL.

### Matrix `!command` alias normalization  `id: platforms-a.matrix-bang-commands`
- **Surface:** Platform:matrix
- **Where:** Any Matrix message: `!commands`, `!model`, `!model gpt-5.5 --provider openrouter`, `!queue continue with the next task`, `!stop`, `!sethome`, `!approve`, `!deny`.
- **What it does:** Lets Matrix clients that swallow `/` local commands still reach Hermes commands, without turning ordinary exclamations into commands.
- **How it works:** `_MATRIX_BANG_COMMAND_RE = re.compile(r"^!([A-Za-z][A-Za-z0-9_-]*)(?=$|\s)(.*)$", re.DOTALL)` at `plugins/platforms/matrix/adapter.py:278`; `_resolve_matrix_bang_command(name)` (`:284`) resolves the token **only** when it is a gateway command, a registered plugin command, or an installed skill command; `_normalize_matrix_bang_command(text)` (`:335`) rewrites it to the `/` form.
- **Inputs / options:** Any known command name after `!`.
- **Outputs / side effects:** The message dispatches as the equivalent slash command.
- **Config / env:** n/a.
- **Edge cases / guards:** Verbatim: "Hermes only normalizes `!command` when the command is known to the gateway, a registered plugin command, or an installed skill command. Ordinary exclamations such as `!important` remain normal chat messages."
- **Rebuild notes:** Resolve against the live command registry, not a static list. A better version would also accept a configurable prefix per room.

### Matrix reaction-based exec approval  `id: platforms-a.matrix-exec-approval`
- **Surface:** Platform:matrix
- **Where:** An approval message in the room, with the bot's own reactions ✅ 🌀 ♾️ ❌ pre-attached; text form `!approve` / `!approve session` / `!approve always` / `!deny`.
- **What it does:** Asks for approval of a dangerous command; the user answers by clicking one of the bot's reactions or typing the bang command.
- **How it works:** `send_exec_approval()` at `plugins/platforms/matrix/adapter.py:2649`. Message body: the formatted command block, then (when `smart_denied`) `Smart DENY: owner override applies to this one operation only.\n`, else `Reply `!approve session` to approve this pattern for the session, ` and/or ``!approve always` to approve permanently, `; then `Reply `!approve` to execute once, or `!deny` to cancel.` and `You can also click the reaction to approve:` followed by the legend lines `✅ = approve once`, `🌀 = approve for this session`, `♾️ = approve always`, `❎ = deny`. The bot then adds reactions: `("✅","❌")` when `allow_session=False`, `("✅","🌀","❌")` when `allow_permanent=False`, otherwise `("✅","🌀","♾️","❌")`. Pending prompts are tracked by `_MatrixApprovalPrompt` (`:511`) in `_approval_prompts_by_event` (event id → prompt) and `_approval_prompt_by_session` (session key → event id), with the bot's own reaction event IDs recorded in `bot_reaction_events` for later cleanup. Reaction→choice map at `:1343`: `"✅"→once`, `"🌀"→session`, `"♾️"→always`, `"♾"→always`, `"♾️"→always`, `"♾"→always`, `"❌"→deny`, `"❎"→deny`.
- **Inputs / options:** Four reactions plus the text forms; `allow_permanent`, `allow_session`, `smart_denied` control which appear.
- **Outputs / side effects:** The agent thread is unblocked; the bot's own reactions are redacted afterwards via `_schedule_reaction_redaction()` (`:3942`).
- **Config / env:** `MATRIX_APPROVAL_TIMEOUT_SECONDS` (default `300`, non-integer values fall back to 300), `MATRIX_APPROVAL_REQUIRE_SENDER` (default `true`).
- **Edge cases / guards:** `_matrix_prompt_expired()` (`:4154`) enforces the timeout; a superseded prompt for the same session is dropped from the event map. With `MATRIX_APPROVAL_REQUIRE_SENDER=true` (default) only the original requester may operate the prompt when Hermes knows who requested the action; set it to `false` to let "any authorized Matrix user in the room" operate it. Reaction failures are logged at DEBUG (`Matrix: failed to add approval reaction %s: %s`).
- **Rebuild notes:** Pre-seed the bot's own reactions as clickable buttons and map emoji → decision. A better version would edit the prompt in place to show the decision, as Slack does, instead of only redacting reactions.

### Matrix reaction-based model picker  `id: platforms-a.matrix-model-picker`
- **Surface:** Platform:matrix
- **Where:** The `/model` (or `!model`) reply — a message headed **"⚙ **Model Configuration**"** with numbered-keycap reactions.
- **What it does:** Lists the authenticated models across providers and lets the user pick one by reacting.
- **How it works:** `send_model_picker()` at `plugins/platforms/matrix/adapter.py:2721`. Flattens `providers` into at most `len(_MATRIX_MODEL_PICKER_REACTIONS)` = **10** choices. Message lines, verbatim: `⚙ **Model Configuration**`, `Current model: \`<model>\`` (or `unknown`), `Provider: <label>` (or `unknown`), blank line, `React to choose a model:`, then one line per choice `<emoji> \`<model_id>\` — <provider_name>`. Reaction set `_MATRIX_MODEL_PICKER_REACTIONS` (`:635`): `1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟`. Prompt tracked by `_MatrixModelPickerPrompt` (`:533`) in `_model_picker_prompts_by_event`.
- **Inputs / options:** Up to 10 model choices; the provider label comes from `hermes_cli.providers.get_label(current_provider)`.
- **Outputs / side effects:** Calls `on_model_selected` with `(model_id, provider_slug)`.
- **Config / env:** `MATRIX_APPROVAL_TIMEOUT_SECONDS`, `MATRIX_APPROVAL_REQUIRE_SENDER`.
- **Edge cases / guards:** With no choices the bot sends the plain message `No authenticated models are available for this session.` Reaction-add failures log `Matrix: failed to add model picker reaction %s: %s`.
- **Rebuild notes:** Flatten providers → keycap emoji and store an emoji→choice map per prompt. A better version would paginate beyond 10 models rather than truncating.

### Matrix reaction-based choice picker (`/reasoning`, `/fast`)  `id: platforms-a.matrix-choice-picker`
- **Surface:** Platform:matrix
- **Where:** The reply to `/reasoning` or `/fast` — a titled list with keycap and lettered-square reactions.
- **What it does:** Generic single-level picker for any list of choices; the current value is marked.
- **How it works:** `send_choice_picker()` at `plugins/platforms/matrix/adapter.py:2802`. Each choice dict is `{"value": str, "label": str, "is_current": bool}`; a current choice is rendered as `<label> ← current`. Lines: the title, a blank line, one `<emoji> <label>` per choice, a blank line, then `React to choose.` Reaction set `_MATRIX_CHOICE_PICKER_REACTIONS` (`:651`) = the 10 model-picker keycaps plus `🅰️` and `🅱️` — 12 slots, because "/reasoning, /fast can need more than 10 slots (8 effort levels + none + reset/show/hide = 12)". Prompt tracked by `_MatrixChoicePickerPrompt` (`:548`) in `_choice_picker_prompts_by_event`.
- **Inputs / options:** Up to 12 choices; extras are dropped.
- **Outputs / side effects:** Calls `on_choice_selected(value)`.
- **Config / env:** `MATRIX_APPROVAL_TIMEOUT_SECONDS`, `MATRIX_APPROVAL_REQUIRE_SENDER`.
- **Edge cases / guards:** No usable choices → `SendResult(success=False, error="No choices")`. Failures log `Matrix: failed to add choice picker reaction %s: %s`.
- **Rebuild notes:** Share the picker machinery between model and generic choices. A better version would use one code path for approvals too.

### Matrix processing-lifecycle reactions  `id: platforms-a.matrix-lifecycle-reactions`
- **Surface:** Config (Platform:matrix)
- **Where:** 👀 / ✅ / ❌ on the inbound message.
- **What it does:** Marks message processing state with reactions.
- **How it works:** Gated by `MATRIX_REACTIONS` (default `true`); reactions are sent with `_send_reaction()` and later removed by `_schedule_reaction_redaction()` (`plugins/platforms/matrix/adapter.py:3942`).
- **Inputs / options:** `MATRIX_REACTIONS=false` disables them.
- **Outputs / side effects:** `m.reaction` events and their redactions.
- **Config / env:** `MATRIX_REACTIONS`.
- **Edge cases / guards:** Tip verbatim: "`MATRIX_REACTIONS=false` turns off the processing-lifecycle emoji reactions (👀/✅/❌) the bot posts on inbound messages. Useful for rooms where reaction events are noisy or aren't supported by all participating clients."
- **Rebuild notes:** Add on admission, replace/redact on completion. A better version would collapse the pair into a single edited reaction.

### Matrix markdown → HTML rendering & sanitizer  `id: platforms-a.matrix-html`
- **Surface:** Core (Platform:matrix)
- **Where:** Every formatted reply (`format: org.matrix.custom.html` + `formatted_body`).
- **What it does:** Renders the agent's markdown to Matrix-compatible HTML and strips anything unsafe before it reaches a client.
- **How it works:** `format_message()` at `plugins/platforms/matrix/adapter.py:2862` is a pass-through except it strips image markdown (`!\[([^\]]*)\]\(([^)]+)\)` → the bare URL) because media is uploaded separately. `_markdown_to_html()` (`:5005`) runs the Markdown library with `_markdown_to_html_fallback()` (`:5049`) as a backup, `_sanitize_link_url()` (`:5040`) for hrefs, and `_pre_sanitize_matrix_markdown()` (`:960`) which removes `<script>`/`<style>` blocks, every `on*=` handler attribute, and any `href`/`src` carrying a `javascript:`, `data:` or `vbscript:` scheme **before** Markdown can escape them. `_sanitize_matrix_html()` (`:939`) then runs `_MatrixHtmlSanitizer` (`:414`), an allowlist HTMLParser; on any exception it falls back to escaping the entire input. `_build_text_message_content()` (`:4814`) assembles the event content (default msgtype `m.text`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Sanitized `formatted_body`.
- **Config / env:** n/a.
- **Edge cases / guards:** `_ALLOWED_TAGS` (verbatim): `a b blockquote br code del em h1 h2 h3 h4 h5 h6 hr i li ol p pre s strike strong table tbody td th thead tr ul`; `_VOID_TAGS`: `br hr`. Only two attributes survive: `href` on `<a>` (scheme restricted to `http`, `https`, `matrix`, `mailto`; control characters `\x00-\x1f\x7f` stripped) and `class` on `<code>` matching exactly `language-[A-Za-z0-9_+.-]{1,64}`. Any attribute starting with `on` is dropped. `<script>`/`<style>` content is skipped entirely via a depth counter.
- **Rebuild notes:** Two-stage defence — pre-sanitize the source, then allowlist-parse the rendered HTML, with total escaping as the last resort. A better version would use a maintained sanitizer library and add `img` support with `mxc://`-only sources.

### Matrix outbound mentions & `@room` guard  `id: platforms-a.matrix-mentions-out`
- **Surface:** Config (Platform:matrix)
- **Where:** Any reply that names a Matrix user ID; `@room` notifications.
- **What it does:** Turns explicit Matrix IDs in the agent's output into structured mention pills, while refusing to wake the whole room unless explicitly allowed.
- **How it works:** `_OUTBOUND_MENTION_RE = re.compile(r"(?<![\w/])(@[0-9A-Za-z._=/-]+:[0-9A-Za-z.-]+(?::\d+)?)")` at `plugins/platforms/matrix/adapter.py:606`. `_extract_outbound_mentions()` (`:4857`), `_has_outbound_room_mention()` (`:4869`), `_inject_outbound_mention_links()` (`:4874`), `_protect_outbound_mention_regions()` (`:4891`).
- **Inputs / options:** `MATRIX_ALLOW_ROOM_MENTIONS` (default `false`).
- **Outputs / side effects:** `m.mentions` on the event; matrix.to pills in the HTML body.
- **Config / env:** `MATRIX_ALLOW_ROOM_MENTIONS`.
- **Edge cases / guards:** Tip verbatim: "Hermes sends structured Matrix user mentions for explicit Matrix IDs such as `@alice:example.org`. Room-wide `@room` notifications are disabled by default; set `MATRIX_ALLOW_ROOM_MENTIONS=true` only in rooms where the bot is allowed to notify everyone."
- **Rebuild notes:** Regex-detect fully qualified MXIDs, build `m.mentions`, and gate `@room` behind an explicit flag. A better version would resolve display names to MXIDs so the agent can mention people by name.

### Matrix reply-fallback handling  `id: platforms-a.matrix-reply-fallback`
- **Surface:** Core (Platform:matrix)
- **Where:** Invisible — inbound replies that carry Matrix's legacy quote block.
- **What it does:** Separates the quoted-original prefix from the user's actual reply text so the agent does not see the quote twice.
- **How it works:** `_MATRIX_REPLY_FALLBACK_PILL_RE = re.compile(r"^>\s*<(@[^>]+)>\s*(.*)$")` at `plugins/platforms/matrix/adapter.py:358`; `_extract_reply_fallback(body)` (`:361`) returns `(quoted_sender, quoted_text)`; `_strip_reply_fallback(body)` (`:391`) removes it.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Clean reply text plus structured reply metadata.
- **Config / env:** n/a.
- **Edge cases / guards:** Only the leading `> <@user:server> …` block form is matched.
- **Rebuild notes:** Strip the fallback, keep the relation. A better version would prefer `m.in_reply_to` entirely and ignore the fallback body.

### Matrix media handling & limits  `id: platforms-a.matrix-media`
- **Surface:** Platform:matrix
- **Where:** Images, files, audio and video in either direction.
- **What it does:** Uploads and downloads Matrix media through the content repository API, with a hard size cap and an `mxc://`-only inbound rule.
- **How it works:** `_mxc_to_http()` at `plugins/platforms/matrix/adapter.py:4998` converts content URIs for download; `_redact_url_for_log()` (`:949`) strips query/fragment before logging signed media links; SSRF protection via `_ssrf_redirect_guard` imported from `gateway.platforms.base`. Caption-vs-filename detection: `_looks_like_matrix_image_filename()` (`:678`) and `_looks_like_matrix_media_filename()` (`:703`) treat a bare filename body as transport noise rather than user text. Extension sets — `_MATRIX_IMAGE_FILENAME_EXTS` (`:615`): `.jpg .jpeg .png .gif .webp .bmp .svg .heic .heif .avif`; `_MATRIX_MEDIA_FILENAME_EXTS` (`:630`): `.ogg .oga .opus .m4a .mp3 .wav .flac .aac .amr .mp4 .webm .mov .mkv`.
- **Inputs / options:** `MATRIX_MAX_MEDIA_BYTES` (default **100 MB**; the doc example sets `104857600`).
- **Outputs / side effects:** `m.image` / `m.audio` / `m.video` / `m.file` events. "Multiple generated images are sent as one ordered logical batch, preserving captions and thread context across the batch."
- **Config / env:** `MATRIX_MAX_MEDIA_BYTES`.
- **Edge cases / guards:** "By default, Matrix media over 100 MB is rejected before upload/download." "Inbound media must use Matrix `mxc://` content URIs. Hermes rejects arbitrary HTTP(S) media URLs in Matrix events to avoid turning a federated room into an unrestricted downloader."
- **Rebuild notes:** Enforce the cap before the transfer, not after. A better version would stream to disk with a running byte counter so a lying `Content-Length` cannot exceed the cap.

### Matrix native voice messages (MSC3245)  `id: platforms-a.matrix-voice`
- **Surface:** Platform:matrix
- **Where:** TTS replies render as native voice bubbles in Element; inbound voice messages are transcribed.
- **What it does:** Tags outgoing voice with `org.matrix.msc3245.voice` (plus duration and waveform) so clients show a real voice bubble instead of a generic audio attachment, and recognises inbound MSC3245 audio for STT.
- **How it works:** `_matrix_voice_metadata_for_file(path)` at `plugins/platforms/matrix/adapter.py:147` — best-effort: `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <path>` (10 s timeout) yields `metadata["duration"]` in **milliseconds**; `ffmpeg -v error -i <path> -ac 1 -ar 8000 -f s16le -` (15 s timeout) yields a `_MATRIX_VOICE_WAVEFORM_BINS = 30`-bin MSC1767 waveform, each bin `min(1024, int(peak / 32767 * 1024))`, byte-swapped on big-endian hosts. `_matrix_transcode_voice_to_ogg(path)` (`:225`) produces a **new** temporary `.ogg` with `ffmpeg -v error -y -i <path> -acodec libopus -ac 1 -b:a 48k -vbr on -application voip -compression_level 10 <out>` (30 s timeout); the caller owns cleanup, and `None` means "send the original file".
- **Inputs / options:** n/a — "No configuration is needed — this works automatically."
- **Outputs / side effects:** `m.audio` events carrying the MSC3245 flag, duration and waveform; a temp `.ogg` file when transcoding succeeds.
- **Config / env:** Requires `ffprobe`/`ffmpeg` on `PATH` for metadata and transcoding; STT providers as elsewhere.
- **Edge cases / guards:** "Metadata extraction is deliberately best-effort: media delivery must still work on systems without ffprobe/ffmpeg." Failures log at DEBUG: `Matrix: failed to probe voice duration for %s`, `Matrix: failed to build voice waveform for %s`, `Matrix: voice transcode to Ogg/Opus failed for %s`. Blocking subprocess work must be called via `asyncio.to_thread`. The temp file is unlinked when the transcode fails or produces zero bytes.
- **Rebuild notes:** Transcode to Ogg/Opus mono 48 kbps VBR voip, attach duration + a 30-bin waveform, set the MSC3245 flag. A better version would compute the waveform from the transcoded Opus instead of a second decode pass.

### Matrix text batching  `id: platforms-a.matrix-batching`
- **Surface:** Env (Platform:matrix)
- **Where:** Invisible — rapid successive Matrix messages.
- **What it does:** Merges messages sent in quick succession into one agent turn (Matrix clients split long messages around 4 000 chars).
- **How it works:** `_text_batch_key()` at `plugins/platforms/matrix/adapter.py:4269`, `_enqueue_text_event()` at `:4284`; delays read at `:1332`.
- **Inputs / options:** `HERMES_MATRIX_TEXT_BATCH_DELAY_SECONDS` (default `0.6`), `HERMES_MATRIX_TEXT_BATCH_SPLIT_DELAY_SECONDS` (default `2.0`).
- **Outputs / side effects:** One merged `MessageEvent`.
- **Config / env:** the two env vars above.
- **Edge cases / guards:** Values are parsed with a bare `float()` — a malformed value raises at construction (unlike WhatsApp's guarded `_coerce_float_extra`).
- **Rebuild notes:** Per-session debounce with a longer window when the last chunk looks like a client-side split. A better version would guard the float parse the way the WhatsApp adapter does.

### Matrix startup grace filter (clock-skew guard)  `id: platforms-a.matrix-startup-grace`
- **Surface:** Core (Platform:matrix)
- **Where:** Invisible — the first sync after startup.
- **What it does:** Ignores events replayed from the initial sync so a restart does not re-answer old messages.
- **How it works:** `_STARTUP_GRACE_SECONDS = 5` (`plugins/platforms/matrix/adapter.py:604`); the filter is `event_ts < startup_ts - 5`, with `_matrix_event_timestamp_seconds()` (`:733`) normalizing the event timestamp.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Old events dropped before the handler.
- **Config / env:** n/a.
- **Edge cases / guards:** **Clock skew failure mode:** when the host clock is ahead of real time every incoming event looks "older than startup" and is dropped — "the bot appears connected but never replies". Symptom, verbatim: gateway log shows `Matrix: dropped N live events as 'too old' more than 30s after startup`. Fix: sync the host clock with NTP (`sudo timedatectl set-ntp true`; `timedatectl status`; macOS `sudo sntp -sS time.apple.com`) and restart the bot.
- **Rebuild notes:** Prefer the sync token over a wall-clock window. A better version would persist `next_batch` and drop the time filter entirely.

### Matrix invite auto-join  `id: platforms-a.matrix-auto-join`
- **Surface:** Platform:matrix
- **Where:** Invite the bot's Matrix user to any room — it joins and starts responding.
- **What it does:** Automatically accepts room invites, including invites to encrypted rooms.
- **How it works:** `_schedule_invite_join()` at `plugins/platforms/matrix/adapter.py:3856` and `_schedule_pending_invite_joins(sync_data)` at `:3886`, driven from the sync loop.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The bot joins the room; joined rooms are tracked in `self._joined_rooms`.
- **Config / env:** `MATRIX_ALLOWED_ROOMS` still gates whether messages from a joined room can trigger a turn.
- **Edge cases / guards:** Tip verbatim: "The bot automatically joins rooms when invited. Just invite the bot's Matrix user to any room and it will join and start responding." A joined bot can only decrypt messages sent **after** it joined.
- **Rebuild notes:** Drain `invite` from each sync payload and join asynchronously. A better version would refuse invites from rooms not on the allowlist rather than joining and then ignoring them.

### Matrix room allowlist (`allowed_rooms`)  `id: platforms-a.matrix-allowed-rooms`
- **Surface:** Config (Platform:matrix)
- **Where:** `matrix.allowed_rooms` (YAML list) or `MATRIX_ALLOWED_ROOMS` (comma-separated).
- **What it does:** Restricts the bot to a fixed set of Matrix rooms; messages from any other room are silently ignored, even if the bot is mentioned.
- **How it works:** `_is_allowed_matrix_room()` at `plugins/platforms/matrix/adapter.py:3187`; the set is built in `__init__` from `self._allowed_rooms`. The check runs **before** any other gating (mention requirement, sender allowlist).
- **Inputs / options:** Internal room IDs (`!abc...:server`), **not** aliases (`#room:server`).
- **Outputs / side effects:** Messages dropped before session lookup.
- **Config / env:** `matrix.allowed_rooms`, `MATRIX_ALLOWED_ROOMS`.
- **Edge cases / guards:** "**DMs (direct chat rooms) are exempt** from this filter, so authorized users can always reach the bot one-on-one." Empty/unset means no restriction. To find a room ID: Element → room → **Settings → Advanced → Internal room ID** (starts with `!`). Matrix tools are also constrained: "If `MATRIX_ALLOWED_ROOMS` is set, Matrix tools may only target those rooms."
- **Rebuild notes:** A set test at the head of the admission chain with a DM exemption. A better version would resolve aliases to IDs at startup so operators can configure `#room:server`.

### Matrix bridge/appservice loop protection  `id: platforms-a.matrix-bridge-guard`
- **Surface:** Config (Platform:matrix)
- **Where:** `matrix.ignore_user_patterns` / `MATRIX_IGNORE_USER_PATTERNS`, `matrix.process_notices` / `MATRIX_PROCESS_NOTICES`.
- **What it does:** Stops bridge ghosts and appservice puppets from feeding the bot's own output back to it as a new user message.
- **How it works:** `_is_self_sender()` at `plugins/platforms/matrix/adapter.py:3127`, `_is_system_or_bridge_sender()` at `:3147` (localparts starting with `_`), `_matches_ignored_user_pattern()` at `:3183` (compiled regexes from the comma-separated list).
- **Inputs / options:** `MATRIX_IGNORE_USER_PATTERNS='^@telegram_,^@slack_,^@whatsapp_'`; `MATRIX_PROCESS_NOTICES=true` ("Only enable notices when a trusted human workflow really sends `m.notice`").
- **Outputs / side effects:** Matching senders and, by default, all `m.notice` events are dropped.
- **Config / env:** the two keys above.
- **Edge cases / guards:** Always-on protections, verbatim: "Hermes always ignores its own events, Matrix appservice-style users whose localpart starts with `_`, duplicate event IDs, old startup events, edit replacement events, and `m.notice` events by default." Troubleshooting: "Keep bridge ghosts out of `MATRIX_ALLOWED_USERS`, add a matching `MATRIX_IGNORE_USER_PATTERNS` entry, and leave `MATRIX_PROCESS_NOTICES=false` unless notices are part of a trusted workflow."
- **Rebuild notes:** Combine a hard-coded appservice rule with operator regexes. A better version would auto-learn ghost prefixes from the room's appservice registration.

### Matrix diagnostics (`get_diagnostics`)  `id: platforms-a.matrix-diagnostics`
- **Surface:** Core (Platform:matrix)
- **Where:** Gateway diagnostics output.
- **What it does:** Reports Matrix readiness — auth, sync, E2EE, policy and media limits — with every secret redacted.
- **How it works:** `get_diagnostics()` at `plugins/platforms/matrix/adapter.py:2262`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Exact returned shape: `{"platform": "matrix", "homeserver": …, "auth": {"access_token_present", "password_present", "token_preview" ("***" or ""), "user_id", "device_id_present", "device_id_preview"}, "sync": {"connected", "joined_room_count", "last_sync_age_seconds"}, "e2ee": {"mode", "enabled", "deps_available", "crypto_store_path", "recovery_key_configured"}, "policy": {"allowed_user_count", "allowed_room_count", "ignored_user_pattern_count", "require_mention", "free_response_room_count", "allow_room_mentions", "process_notices", "allow_public_rooms"}, "media": {"max_media_bytes"}}`.
- **Config / env:** reflects all of the Matrix config keys.
- **Edge cases / guards:** "Diagnostics and debug payloads redact Matrix access tokens, recovery keys, device identifiers, and message bodies" — `_redact_matrix_value()` returns `"***"` for any non-empty value; counts are reported instead of the values themselves.
- **Rebuild notes:** Emit counts and presence flags, never values. A better version would include the last sync error and the number of undecryptable events.

### Matrix presence, typing and read receipts  `id: platforms-a.matrix-presence`
- **Surface:** Core (Platform:matrix)
- **Where:** The "typing…" indicator and read markers in the room.
- **What it does:** Signals that the bot is working and marks processed messages as read.
- **How it works:** `send_typing()` at `plugins/platforms/matrix/adapter.py:2314` calls `client.set_typing(RoomID(chat_id), timeout=30000)`; `stop_typing()` at `:2325` calls it with `timeout=0`. `_background_read_receipt(room_id, event_id)` at `:4337` posts the read receipt off the critical path. Presence uses `PresenceState` (`ONLINE` / `OFFLINE` / `UNAVAILABLE`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** `m.typing` and `m.receipt` events.
- **Config / env:** n/a.
- **Edge cases / guards:** Both typing calls swallow every exception.
- **Rebuild notes:** 30 s typing timeout refreshed while the turn runs; clear on finalize. A better version would refresh rather than rely on a single 30 s window.

### Matrix message editing (`m.replace`)  `id: platforms-a.matrix-edit`
- **Surface:** Core (Platform:matrix)
- **Where:** Progressive/streaming replies and thinking panes.
- **What it does:** Updates an already-sent message in place instead of posting a new one.
- **How it works:** `edit_message(chat_id, message_id, content, *, finalize=False)` at `plugins/platforms/matrix/adapter.py:2334` formats the content, builds a new `m.text` content block via `_build_text_message_content()` and sends it with an `m.replace` relation applied by `_apply_relation_metadata()` (`:4832`).
- **Inputs / options:** `finalize` marks the last edit of a stream.
- **Outputs / side effects:** An `m.room.message` event carrying `m.new_content` + `m.relates_to: {rel_type: m.replace}`.
- **Config / env:** n/a.
- **Edge cases / guards:** Inbound edit replacement events are ignored so the bot never re-answers an edited message.
- **Rebuild notes:** Always send both the fallback body and `m.new_content`. A better version would coalesce rapid edits to stay under homeserver rate limits.

### Matrix thinking / tool-activity panes  `id: platforms-a.matrix-thinking-panes`
- **Surface:** Platform:matrix
- **Where:** A threaded, editable message showing reasoning and tool activity while the agent works.
- **What it does:** Keeps progress updates out of the main room timeline by putting them in an edited thread message.
- **How it works:** Declared in `_MATRIX_CAPABILITIES` as `"thinking panes": "yes"`; implemented on top of the thread relation + `m.replace` edit path (`_apply_relation_metadata`, `edit_message`). Active when gateway progress is enabled.
- **Inputs / options:** Governed by the gateway's progress/`tool_progress` settings.
- **Outputs / side effects:** One threaded pane per turn, continuously edited.
- **Config / env:** gateway progress settings; `MATRIX_AUTO_THREAD`.
- **Edge cases / guards:** Doc statement verbatim: "Matrix uses threaded, editable thinking/tool-activity panes when gateway progress is enabled, so updates do not flood the main room timeline."
- **Rebuild notes:** One edited event per turn inside the reply thread. A better version would collapse completed tool rows into a summary line.

### Matrix history fetch & serialization  `id: platforms-a.matrix-history`
- **Surface:** Core (Platform:matrix)
- **Where:** Invisible — thread/room context loading.
- **What it does:** Pulls prior room events and renders them into agent-readable text.
- **How it works:** `_serialize_history_event(event)` at `plugins/platforms/matrix/adapter.py:4492`; pagination uses `PaginationDirection.BACKWARD` / `FORWARD`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A list of serialized dicts.
- **Config / env:** n/a.
- **Edge cases / guards:** Events the bot cannot decrypt are skipped.
- **Rebuild notes:** Paginate with `/messages` and render each event type explicitly. A better version would cache the rendered history per thread.

### Matrix home room & `/sethome`  `id: platforms-a.matrix-home-room`
- **Surface:** Config (Platform:matrix)
- **Where:** `MATRIX_HOME_ROOM` in `~/.hermes/.env`, or type `/sethome` (or `!sethome`) in any room where the bot is present.
- **What it does:** Designates the room where the bot sends cron output, reminders and notifications.
- **How it works:** Registered as `cron_deliver_env_var="MATRIX_HOME_ROOM"` (`plugins/platforms/matrix/adapter.py:5462`).
- **Inputs / options:** A room ID like `!abc123def456:matrix.example.org`.
- **Outputs / side effects:** Proactive messages land in that room.
- **Config / env:** `MATRIX_HOME_ROOM`.
- **Edge cases / guards:** "If your Matrix client intercepts slash commands, type `!sethome` instead."
- **Rebuild notes:** One env var writable from chat. A better version would verify the bot is joined to the room before accepting it.

### Matrix standalone (out-of-process) sender  `id: platforms-a.matrix-standalone-send`
- **Surface:** Core (Platform:matrix)
- **Where:** Invisible — cron or `send_message` outside the gateway process.
- **What it does:** Sends a Matrix message using the configured homeserver and access token without a live adapter.
- **How it works:** `_standalone_send()` registered as `standalone_sender_fn` at `plugins/platforms/matrix/adapter.py:5463`; uses the client-server API directly with `MATRIX_ACCESS_TOKEN`.
- **Inputs / options:** Room ID target.
- **Outputs / side effects:** A real Matrix event.
- **Config / env:** `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`.
- **Edge cases / guards:** Cannot send into encrypted rooms — that needs the crypto store held by the live adapter.
- **Rebuild notes:** A plain `PUT /_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}`. A better version would detect an encrypted room and refuse loudly instead of posting an unencrypted event.

### Matrix proxy support (`MATRIX_PROXY`)  `id: platforms-a.matrix-proxy`
- **Surface:** Env (Platform:matrix)
- **Where:** `MATRIX_PROXY` in `~/.hermes/.env`.
- **What it does:** Routes all Matrix HTTP traffic through an HTTP(S) or SOCKS proxy.
- **How it works:** `_create_matrix_session(proxy_url)` at `plugins/platforms/matrix/adapter.py:753`, using `resolve_proxy_url` / `proxy_kwargs_for_aiohttp` from `gateway.platforms.base`; SOCKS requires `aiohttp-socks`.
- **Inputs / options:** An `http://`, `https://` or `socks5://` URL.
- **Outputs / side effects:** All homeserver traffic traverses the proxy.
- **Config / env:** `MATRIX_PROXY`, falling back to the generic proxy env vars.
- **Edge cases / guards:** `aiohttp-socks` is listed in the E2EE manual-install hint.
- **Rebuild notes:** One session factory that all requests share. A better version would allow a separate proxy for media downloads.

### Matrix proxy mode (E2EE on macOS)  `id: platforms-a.matrix-proxy-mode`
- **Surface:** Config (Gateway/Platform:matrix)
- **Where:** `GATEWAY_PROXY_URL` / `GATEWAY_PROXY_KEY` on a thin container gateway; `API_SERVER_*` on the host.
- **What it does:** Splits the deployment so Matrix + E2EE run in a Linux Docker container while the actual agent (sessions, memory, skills, local files) runs natively on macOS — because `libolm` does not compile on macOS ARM64.
- **How it works:** The container runs `hermes gateway` with only the Matrix adapter; on an inbound message it decrypts and forwards the text over HTTP to the host's `api_server` adapter at `/v1/chat/completions`; the host runs the agent and streams back; the container encrypts and posts the reply. Session continuity uses the `X-Hermes-Session-Id` header. All sessions are unified — "CLI, Matrix, Telegram, and any other platform share the same memory and conversation history."
- **Inputs / options:** Container side — `GATEWAY_PROXY_URL` ("URL of the remote Hermes API server (e.g., `http://192.168.1.100:8642`)"), `GATEWAY_PROXY_KEY` ("Bearer token for authentication (must match `API_SERVER_KEY` on the host)"), `gateway.proxy_url` ("Same as `GATEWAY_PROXY_URL` but in `config.yaml`"). Host side — `API_SERVER_ENABLED` ("Set to `true`"), `API_SERVER_KEY` ("Bearer token (shared with the container)"), `API_SERVER_HOST` ("Set to `0.0.0.0` for network access"), `API_SERVER_PORT` ("Port number (default: `8642`)"). Container also needs `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ALLOWED_USERS`, `MATRIX_ENCRYPTION`, `MATRIX_DEVICE_ID`, and a volume mount `./matrix-store:/root/.hermes/platforms/matrix/store`.
- **Outputs / side effects:** No LLM API keys are needed in the container ("No API keys for OpenRouter, Anthropic, or any inference provider").
- **Config / env:** as enumerated.
- **Edge cases / guards:** Documented v1 limitations, verbatim: "Tool progress messages from the remote agent are not relayed back — the user sees the streamed final response only, not individual tool calls. Dangerous command approval prompts are handled on the host side, not relayed to the Matrix user." `API_SERVER_KEY` is required for non-loopback binding. Verify reachability from the VM with `curl http://<mac-ip>:8642/health`. Proxy mode is **not** Matrix-specific: "set `GATEWAY_PROXY_URL` on any gateway instance and it will forward to the remote agent instead of running one locally."
- **Rebuild notes:** Make the adapter layer and the agent layer separable behind one HTTP contract. A better version would relay tool progress and approval prompts over the same channel.

### Matrix commands surface  `id: platforms-a.matrix-commands`
- **Surface:** Platform:matrix
- **Where:** Any Matrix room or DM.
- **What it does:** Exposes the same gateway command set Hermes offers on other platforms.
- **How it works:** Commands are dispatched from message text; the `!` alias resolves through `_resolve_matrix_bang_command`.
- **Inputs / options:** Named in the docs, verbatim: `/commands`, `/model`, `/stop`, `/queue`, `/steer`, `/goal`, `/subgoal`, `/bg`, `/btw`, `/tasks`, `/yolo` — plus `/sethome`, `/status`, `/resume` (with `--cross-room`), and every other gateway command. Bang examples: `!commands`, `!model`, `!model gpt-5.5 --provider openrouter`, `!queue continue with the next task`, `!stop`.
- **Outputs / side effects:** Command replies in the room/thread.
- **Config / env:** n/a.
- **Edge cases / guards:** "Some Matrix clients reserve leading `/` for local client commands and may not send unknown slash commands to the room."
- **Rebuild notes:** One dispatcher fed by both prefixes. The full per-command inventory lives in the `gw-slash` shard.

### Matrix Tools & controls (documented toolset)  `id: platforms-a.matrix-tools`
- **Surface:** Tool (Platform:matrix)
- **Where:** Documented at `website/docs/user-guide/messaging/matrix.md:409` as Matrix-context-only tools.
- **What it does:** Documented to let the agent react, redact, create rooms, invite users, fetch history and set presence from inside a Matrix conversation.
- **How it works:** The documentation names six tools — `matrix_send_reaction`, `matrix_redact_message`, `matrix_create_room`, `matrix_invite_user`, `matrix_fetch_history`, `matrix_set_presence` — "scoped to Matrix contexts and not available in non-Matrix toolsets". The gating env vars they describe **are** present in the adapter's documented env surface (`plugins/platforms/matrix/adapter.py:34-38`), and the adapter imports the primitives these tools would need (`RoomCreatePreset`, `PresenceState`, `PaginationDirection`, `_serialize_history_event`, `_send_reaction`, `_schedule_reaction_redaction`). No module registering tools with these names was found in the v2026.8.31 tree, and none appear in `tools_full.json` (83 tools) or `tools_toolsets.json` (59 toolsets) — see Handoffs.
- **Inputs / options:** Per the docs: redaction requires `MATRIX_TOOLS_ALLOW_REDACTION=true`, invites require `MATRIX_TOOLS_ALLOW_INVITES=true`, room creation requires `MATRIX_TOOLS_ALLOW_ROOM_CREATE=true`, and public room creation additionally requires `MATRIX_ALLOW_PUBLIC_ROOMS=true`. "If `MATRIX_ALLOWED_ROOMS` is set, Matrix tools may only target those rooms."
- **Outputs / side effects:** Real Matrix state changes (reactions, redactions, room creation, invites, presence).
- **Config / env:** `MATRIX_TOOLS_ALLOW_REDACTION`, `MATRIX_TOOLS_ALLOW_INVITES`, `MATRIX_TOOLS_ALLOW_ROOM_CREATE`, `MATRIX_ALLOW_PUBLIC_ROOMS`, `MATRIX_ALLOWED_ROOMS` — all default `false`/unset ("Admin-style tools are disabled by default").
- **Edge cases / guards:** All four admin capabilities are opt-in; the room allowlist constrains targets.
- **Rebuild notes:** Gate every state-changing Matrix tool behind its own env flag plus the room allowlist. A better version would require an exec-approval prompt for redaction and invites rather than a static flag.

### Matrix troubleshooting matrix  `id: platforms-a.matrix-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/matrix.md:575` and `:858`.
- **What it does:** Maps each observed Matrix failure to its cause and fix.
- **How it works:** Static documentation matching the adapter's real failure modes.
- **Inputs / options:** Entries, verbatim (Heading → Cause → Fix):
  - "Bot is not responding to messages" → "The bot hasn't joined the room, `MATRIX_ALLOWED_USERS` doesn't include your User ID, `MATRIX_ALLOWED_ROOMS` doesn't include the room, or a room message did not mention the bot." → invite the bot, verify the allowlists, mention the bot or add the room to `MATRIX_FREE_RESPONSE_ROOMS`, restart the gateway.
  - "Bot joins rooms but silently drops every message (clock skew)" → host clock ahead of real time vs the 5 s startup grace filter → sync with NTP.
  - "\"Failed to authenticate\" / \"whoami failed\" on startup" → wrong token or homeserver URL → verify with `curl -H "Authorization: Bearer YOUR_TOKEN" https://your-server/_matrix/client/v3/account/whoami`.
  - "\"mautrix not installed\" error" → `pip install 'mautrix[encryption]'` or `cd ~/.hermes/hermes-agent && uv pip install -e ".[matrix]"`.
  - "Encryption errors / \"could not decrypt event\"" → verify `libolm`, set `MATRIX_ENCRYPTION=true`, trust the bot's device in Element → Sessions, and note "If the bot just joined an encrypted room, it can only decrypt messages sent *after* it joined."
  - "Upgrading from a previous version with E2EE" → the old `matrix-nio`/serialization-based state is incompatible with the SQLite crypto store; the client caches old device keys and refuses to share the session ("This is a Matrix security feature -- clients treat changed identity keys for the same device as suspicious").
  - "Bot connects and sends, but ignores inbound messages" → a raw `client.sync()` poll that never calls `handle_sync()` → Hermes's explicit sync loop calls `client.handle_sync()` on the initial and every incremental sync; "If inbound messages still fail after a gateway restart, verify handlers are registered before the first sync and check logs for `sync event dispatch error`."
  - "Sync issues / bot falls behind" → long tool executions or a slow homeserver → the sync loop retries every 5 seconds on error.
  - "Bot is offline" → the gateway isn't running or failed to connect.
  - "\"User not allowed\" / Bot ignores you" → add your full `@user:server` ID to `MATRIX_ALLOWED_USERS`.
  - "Bot ignores an entire room" → add the room ID to `MATRIX_ALLOWED_ROOMS` or remove the allowlist.
  - "Bridge messages loop or echo" → keep bridge ghosts out of `MATRIX_ALLOWED_USERS`, add `MATRIX_IGNORE_USER_PATTERNS`, leave `MATRIX_PROCESS_NOTICES=false`.
- **Outputs / side effects:** n/a.
- **Config / env:** all Matrix keys.
- **Edge cases / guards:** Notes section verbatim: "**Any homeserver**", "**Federation**: … just add their full `@user:server` IDs to `MATRIX_ALLOWED_USERS`", "**Auto-join**: The bot automatically accepts room invites and joins", "**Media support**: … uploaded to your homeserver using the Matrix content repository API", "**Native voice messages (MSC3245)**".
- **Rebuild notes:** Turn each row into a startup self-check. A better version would ship a `hermes gateway doctor --matrix` that runs whoami, checks the clock, and reports crypto-store health.

---

## 5. Mattermost

### Mattermost platform adapter  `id: platforms-a.mattermost`
- **Surface:** Platform:mattermost
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Mattermost"** (emoji 💬); runs inside `hermes gateway`. In Mattermost itself: DMs, group DMs, public channels, private channels and threads (CRT), on any self-hosted or cloud instance (Team Edition or Enterprise).
- **What it does:** Connects Hermes to a Mattermost server over the **v4 REST API** plus the **WebSocket event stream**, relaying channel/DM posts into the agent and posting replies, files and thread replies back. No Mattermost client library is required — only `aiohttp`, already a Hermes dependency.
- **How it works:** `plugins/platforms/mattermost/adapter.py:113` defines `MattermostAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/mattermost/adapter.py:1302` calls `ctx.register_platform(name="mattermost", label="Mattermost", adapter_factory=_build_adapter, check_fn=check_mattermost_requirements, validate_config=validate_mattermost_config, is_connected=_is_connected, required_env=["MATTERMOST_URL","MATTERMOST_TOKEN"], install_hint="pip install aiohttp", setup_fn=interactive_setup, apply_yaml_config_fn=_apply_yaml_config, allowed_users_env="MATTERMOST_ALLOWED_USERS", allow_all_env="MATTERMOST_ALLOW_ALL_USERS", cron_deliver_env_var="MATTERMOST_HOME_CHANNEL", standalone_sender_fn=_standalone_send, max_message_length=MAX_POST_LENGTH, emoji="💬", allow_update_command=True)`. Manifest `plugins/platforms/mattermost/plugin.yaml:1` (`name: mattermost-platform`, `label: Mattermost`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). `MAX_POST_LENGTH = 4000` (`:61`) — "server default is 16383, but 4000 is the practical limit for readable messages". `_CHANNEL_TYPE_MAP` (`:64`): `"D"→dm`, `"G"→group`, `"P"→group` (private channel treated as group), `"O"→channel`. `connect()` (`:310`) opens an `aiohttp.ClientSession` (30 s total timeout), calls `GET users/me` to verify credentials and learn `_bot_user_id` / `_bot_username` (logging `Mattermost: authenticated as @%s (%s) on %s`), then starts `_ws_loop()` and `_wire_plugin_handlers(None)`. Credentials are read scope-aware by `_get_scoped_secret()` (`:37`).
- **Inputs / options:** Env: `MATTERMOST_URL` (required), `MATTERMOST_TOKEN` (required), `MATTERMOST_ALLOWED_USERS`, `MATTERMOST_ALLOW_ALL_USERS`, `MATTERMOST_HOME_CHANNEL`, `MATTERMOST_REPLY_MODE`, `MATTERMOST_REQUIRE_MENTION`, `MATTERMOST_FREE_RESPONSE_CHANNELS`, `MATTERMOST_ALLOWED_CHANNELS`, `MATTERMOST_PROXY`. Config: `mattermost.*` and `gateway.platforms.mattermost.extra.{url,reply_mode,allowed_channels,channel_prompts}`.
- **Outputs / side effects:** Posts, edits, file uploads and typing indicators through `/api/v4/…`; no local state beyond the in-memory dedup cache.
- **Config / env:** `mattermost.require_mention` (default `true`), `mattermost.free_response_channels` (`""`), `mattermost.allowed_channels` (`""`), `mattermost.channel_prompts`, `group_sessions_per_user`.
- **Edge cases / guards:** Every API path is checked for `..` before use — `MM API path traversal blocked: %s` (`_api_get` `:159`, `_api_post` `:177`, `_api_put` `:259`). Security warning verbatim: "Always set `MATTERMOST_ALLOWED_USERS` to restrict who can interact with the bot. Without it, the gateway denies all users by default as a safety measure."
- **Rebuild notes:** Minimal spec: `GET /api/v4/users/me` for identity, `wss://…/api/v4/websocket` with an `authentication_challenge` frame for events, `POST /api/v4/posts` for replies (chunked at 4 000), `POST /api/v4/files` for attachments. A better version would use the `client_id`-based WebSocket sequence numbers to detect and recover missed events instead of relying on reconnect alone.

### Mattermost interactive setup wizard  `id: platforms-a.mattermost-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Mattermost**.
- **What it does:** Collects the server URL and bot token, captures a user allowlist and an optional home channel.
- **How it works:** `interactive_setup()` at `plugins/platforms/mattermost/adapter.py:1166`.
- **Inputs / options:** Verbatim strings in order:
  - header `Mattermost`
  - `Mattermost: already configured` + `Reconfigure Mattermost?` (yes/no, default `False`)
  - `Works with any self-hosted Mattermost instance.`
  - `   1. In Mattermost: Integrations → Bot Accounts → Add Bot Account`
  - `   2. Copy the bot token`
  - prompt `Mattermost server URL (e.g. https://mm.example.com)` (trailing `/` stripped)
  - prompt `Bot token` (password; empty aborts the wizard) → `Mattermost token saved`
  - `🔒 Security: Restrict who can use your bot`
  - `   To find your user ID: click your avatar → Profile`
  - `   or use the API: GET /api/v4/users/me`
  - prompt `Allowed user IDs (comma-separated, leave empty for open access)` → `Mattermost allowlist configured` or `⚠️  No allowlist set - anyone who can message the bot can use it!`
  - `📬 Home Channel: where Hermes delivers cron job results and notifications.`
  - `   To get a channel ID: click channel name → View Info → copy the ID`
  - `   You can also set this later by typing /set-home in a Mattermost channel.`
  - prompt `Home channel ID (leave empty to set later with /set-home)` → `Home channel cleared.` when blanked
  - `   Open config in your editor:  hermes config edit`
- **Outputs / side effects:** Writes `MATTERMOST_URL`, `MATTERMOST_TOKEN`, `MATTERMOST_ALLOWED_USERS` (spaces stripped), `MATTERMOST_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** An empty bot token aborts before anything else is saved.
- **Rebuild notes:** Prompt sequence over an env writer. A better version would call `GET /api/v4/users/me` inline to confirm the token before saving.

### Mattermost bot account creation (server-side setup)  `id: platforms-a.mattermost-bot-account`
- **Surface:** Docs / Platform:mattermost
- **Where:** Mattermost **System Console → Integrations → Bot Accounts**, then **☰ menu → Integrations → Bot Accounts → Add Bot Account**.
- **What it does:** The server-side steps that produce the token Hermes needs.
- **How it works:** Documented at `website/docs/user-guide/messaging/mattermost.md:56`.
- **Inputs / options:** Step 1 — log in as a **System Admin**; **System Console → Integrations → Bot Accounts**; set **Enable Bot Account Creation** to **true**; click **Save**. Step 2 — **☰** menu (top-left) → **Integrations** → **Bot Accounts** → **Add Bot Account**; fill in **Username** (e.g. `hermes`), **Display Name** (e.g. `Hermes Agent`), **Description** (optional), **Role** (`Member` is sufficient); click **Create Bot Account**; copy the displayed **bot token**. Step 3 — open the channel → click the channel name → **Add Members** → search the bot username and add it. Step 4 — click your **avatar** (top-left) → **Profile**; the User ID is a 26-character alphanumeric string such as `3uo8dkh1p7g1mfk49ear5fzs5c`; alternatively `curl -H "Authorization: Bearer YOUR_TOKEN" https://your-mattermost-server/api/v4/users/me | jq .id`. Channel ID: click the channel name → **View Info**.
- **Outputs / side effects:** A bot account and its token.
- **Config / env:** `MATTERMOST_TOKEN`, `MATTERMOST_ALLOWED_USERS`.
- **Edge cases / guards:** Warning verbatim: "The bot token is only displayed once when you create the bot account. If you lose it, you'll need to regenerate it from the bot account settings." Alternative: a **personal access token** via **Profile → Security → Personal Access Tokens → Create Token** — "useful if you want Hermes to post as your own user rather than a separate bot user". Warning verbatim: "Your User ID is **not** your username."
- **Rebuild notes:** Document both the bot-account and PAT paths. A better version would offer a one-click admin URL that pre-fills the bot form.

### Mattermost WebSocket event loop & reconnect  `id: platforms-a.mattermost-ws`
- **Surface:** Core (Platform:mattermost)
- **Where:** Invisible — the real-time event channel.
- **What it does:** Keeps a live WebSocket to the Mattermost server, authenticates on it, dispatches `posted` events, and reconnects with exponential backoff.
- **How it works:** `_ws_loop()` at `plugins/platforms/mattermost/adapter.py:740` and `_ws_connect_and_listen()` at `:784`. The URL is derived by `re.sub(r"^http", "ws", base_url) + "/api/v4/websocket"` (so `https://` → `wss://`), opened with `heartbeat=30.0`, then authenticated by sending `{"seq": 1, "action": "authentication_challenge", "data": {"token": <token>}}`. Backoff constants at `:74`: `_RECONNECT_BASE_DELAY = 2.0`, `_RECONNECT_MAX_DELAY = 60.0`, `_RECONNECT_JITTER = 0.2` — the sleep is `delay + delay*0.2*random()` and `delay = min(delay*2, 60)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Log lines verbatim: `Mattermost: connecting to %s`, `Mattermost: WebSocket connected and authenticated`, `Mattermost: WebSocket closed (%s)`, `Mattermost WS error: %s — reconnecting in %.0fs`, `Mattermost: disconnected`.
- **Config / env:** n/a.
- **Edge cases / guards:** A `WSServerHandshakeError` with status **401 or 403** is treated as permanent: it stops reconnecting and raises a **non-retryable fatal error** `mattermost_auth_error` with the message `Mattermost WebSocket authentication rejected (HTTP {status}). The bot token is invalid, revoked, or lacks permission — check MATTERMOST_TOKEN and the bot account in the System Console.`, then calls `_notify_fatal_error()` — deliberately type-based only, because the old substring fallback misclassified transient errors whose message merely contained "401". Without this the listener would die silently while `is_connected()` still reported healthy. Only `posted` events are processed; every other event type returns immediately.
- **Rebuild notes:** Backoff with jitter, plus a hard stop on 401/403 that escalates instead of looping. A better version would resubscribe and replay missed posts via `GET /channels/{id}/posts?since=` after a reconnect.

### Mattermost inbound message handling  `id: platforms-a.mattermost-inbound`
- **Surface:** Core (Platform:mattermost)
- **Where:** Invisible — every `posted` WebSocket event.
- **What it does:** Turns a Mattermost post into a Hermes `MessageEvent`, applying dedup, self/system filtering, channel and mention gating, mention stripping, thread resolution and attachment download.
- **How it works:** `_handle_ws_event(event)` at `plugins/platforms/mattermost/adapter.py:825`. Order: (1) event type must be `posted`; (2) `data["post"]` JSON-decoded; (3) drop when `post["user_id"] == self._bot_user_id`; (4) drop when `post["type"]` is truthy (system posts); (5) `MessageDeduplicator.is_duplicate(post_id)`; (6) for non-`D` channels — `allowed_channels` whitelist, then `require_mention` / `free_response_channels`, then mention stripping; (7) thread id = `post["root_id"]` or, in `thread` reply mode for non-DMs, the post's own id; (8) message type detection; (9) attachment download; (10) per-channel prompt resolution; (11) `handle_message(msg_event)`.
- **Inputs / options:** Mention patterns are exactly two: `f"@{self._bot_username}"` and `f"@{self._bot_user_id}"`, matched case-insensitively anywhere in the text, and both stripped from the text with `re.sub(re.escape(pattern), "", …, flags=re.IGNORECASE).strip()` when present.
- **Outputs / side effects:** Debug logs verbatim: `Mattermost: ignoring message in non-allowed channel: %s`, `Mattermost: skipping non-DM message without @mention (channel=%s)`.
- **Config / env:** `MATTERMOST_ALLOWED_CHANNELS` / `mattermost.allowed_channels`, `MATTERMOST_REQUIRE_MENTION`, `MATTERMOST_FREE_RESPONSE_CHANNELS`, `MATTERMOST_REPLY_MODE`.
- **Edge cases / guards:** `require_mention` uses explicit-false parsing (`false`/`0`/`no` disable; default `true`). A message whose text starts with `/` (after leading whitespace is stripped) becomes `MessageType.COMMAND`. `sender_name` falls back from `data["sender_name"]` (leading `@` stripped) to the raw user id.
- **Rebuild notes:** Fixed admission order with the channel whitelist first. A better version would use the server's own mention metadata rather than substring matching the username.

### Mattermost reply mode (`thread` vs `off`)  `id: platforms-a.mattermost-reply-mode`
- **Surface:** Config (Platform:mattermost)
- **Where:** `MATTERMOST_REPLY_MODE` in `~/.hermes/.env` or `mattermost.reply_mode` / `extra.reply_mode`.
- **What it does:** Chooses whether Hermes replies flat in the channel or nested in a thread under the triggering post.
- **How it works:** `self._reply_mode` at `plugins/platforms/mattermost/adapter.py:139` (`extra.reply_mode` → `MATTERMOST_REPLY_MODE` → `"off"`, lowercased). `_thread_root_for_send()` (`:205`) returns `None` unless the mode is `thread`, else resolves `reply_to` / `metadata["thread_id"]` / `metadata["root_id"]` through `_resolve_root_id()` (`:370`), which fetches `GET posts/{post_id}` and returns that post's own `root_id` when it is itself a reply — because "Mattermost requires root_id to be the *root* post of a thread… Using a reply's own ID as root_id causes 'Invalid RootId parameter' errors."
- **Inputs / options:** Two values, verbatim: `off` (default) — "Hermes posts flat messages in the channel, like a normal user."; `thread` — "Hermes replies in a thread under your original message. Keeps channels clean when there's lots of back-and-forth."
- **Outputs / side effects:** `root_id` present or absent on the `POST /posts` payload.
- **Config / env:** `MATTERMOST_REPLY_MODE`, `extra.reply_mode`.
- **Edge cases / guards:** In `thread` mode a top-level channel post is itself a valid root for progress updates.
- **Rebuild notes:** Always resolve a post id to its thread root before using it as `root_id`. A better version would cache the post→root mapping to save one API call per send.

### Mattermost broken-thread-root fallback  `id: platforms-a.mattermost-thread-fallback`
- **Surface:** Core (Platform:mattermost)
- **Where:** Visible only on failure — a channel post prefixed **"⚠️ Mattermost thread delivery failed; posting final reply in channel."**
- **What it does:** Guarantees that a notify-worthy final reply is not lost when the thread root has become invalid; it re-posts flat with an explicit warning.
- **How it works:** `_post_preserving_thread()` at `plugins/platforms/mattermost/adapter.py:231`. The retry only runs when: the first post failed, the payload had a `root_id`, `metadata["notify"]` is set, and `_last_post_failure_is_broken_thread_root()` (`:220`) is true. That predicate requires the last status to be **400 or 404** *and* the body to contain both a root-ish marker (`root_id`, `rootid`, `root id`, `thread`, `post`) and a broken-ness marker (`invalid`, `not found`, `does not exist`, `missing`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** A flat channel post whose message is prefixed verbatim `⚠️ Mattermost thread delivery failed; posting final reply in channel.\n\n`; warning log `Mattermost: falling back to flat channel delivery for notify-worthy post in %s`.
- **Config / env:** n/a.
- **Edge cases / guards:** Deliberately narrow — a generic 400 without those markers does **not** trigger the fallback, so a transient failure is not silently converted into a channel-wide post.
- **Rebuild notes:** Classify the failure precisely before changing delivery semantics, and tell the user you did. A better version would re-resolve the root and retry threaded once before going flat.

### Mattermost channel allowlist (`allowed_channels`)  `id: platforms-a.mattermost-allowed-channels`
- **Surface:** Config (Platform:mattermost)
- **Where:** `mattermost.allowed_channels` (YAML list) or `MATTERMOST_ALLOWED_CHANNELS` (comma-separated).
- **What it does:** Restricts the bot to a fixed set of channels; messages elsewhere are silently ignored even when the bot is `@mentioned`.
- **How it works:** Evaluated inline in `_handle_ws_event()` at `plugins/platforms/mattermost/adapter.py:868` — `config.extra["allowed_channels"]` first, then `MATTERMOST_ALLOWED_CHANNELS`; a list or a comma-separated string both become a set. The check runs **before** mention gating.
- **Inputs / options:** 26-character channel IDs.
- **Outputs / side effects:** Non-listed channels drop messages with `Mattermost: ignoring message in non-allowed channel: %s`.
- **Config / env:** `mattermost.allowed_channels`, `MATTERMOST_ALLOWED_CHANNELS`.
- **Edge cases / guards:** "**DMs are exempt** from this filter" — the whole block only runs for `channel_type_raw != "D"`. Empty/unset means no restriction.
- **Rebuild notes:** Set membership ahead of everything else. A better version would accept channel names and resolve them at connect.

### Mattermost mention behaviour  `id: platforms-a.mattermost-mentions`
- **Surface:** Config (Platform:mattermost)
- **Where:** `MATTERMOST_REQUIRE_MENTION`, `MATTERMOST_FREE_RESPONSE_CHANNELS`.
- **What it does:** Decides whether channel messages need an `@mention`, and which channels are exempt.
- **How it works:** See `platforms-a.mattermost-inbound`; the mention is stripped from the text before the agent sees it.
- **Inputs / options:** Table verbatim: `MATTERMOST_REQUIRE_MENTION` — default `true` — "Set to `false` to respond to all messages in channels (DMs always work)."; `MATTERMOST_FREE_RESPONSE_CHANNELS` — default *(none)* — "Comma-separated channel IDs where the bot responds without `@mention`, even when require_mention is true."
- **Outputs / side effects:** Admission or a debug-logged skip.
- **Config / env:** `mattermost.require_mention`, `mattermost.free_response_channels` and the env equivalents (YAML bridged by `_apply_yaml_config()` at `:1235`, env winning).
- **Edge cases / guards:** "When the bot is `@mentioned`, the mention is automatically stripped from the message before processing." DMs never require a mention.
- **Rebuild notes:** Two settings, one gate, with mention stripping. A better version would honour Mattermost's `@channel`/`@here` and keyword-mention settings too.

### Mattermost outbound mention suppression  `id: platforms-a.mattermost-disable-mentions`
- **Surface:** Core (Platform:mattermost)
- **Where:** Invisible — every post and edit Hermes makes.
- **What it does:** Stops the bot's own output from firing Mattermost notifications when it echoes an `@name`.
- **How it works:** `_with_mentions_disabled(payload)` at `plugins/platforms/mattermost/adapter.py:79` merges `_MATTERMOST_DISABLE_MENTIONS_PROPS = {"disable_mentions": True}` (`:71`) into the payload's `props`, preserving any existing props. Applied in `send()` (`:396`) and `edit_message()` (`:441`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** `props.disable_mentions = true` on every post.
- **Config / env:** n/a.
- **Edge cases / guards:** Applied unconditionally — there is no opt-out.
- **Rebuild notes:** Set the flag at the single send seam, not per call site. A better version would make it configurable for bots that legitimately need to page people.

### Mattermost file attachments (in and out)  `id: platforms-a.mattermost-files`
- **Surface:** Platform:mattermost
- **Where:** Files dropped into a Mattermost post; agent replies with images, documents, audio or video.
- **What it does:** Downloads inbound attachments into the local cache (because the URLs need auth headers downstream tools do not have) and uploads outbound media as native Mattermost attachments.
- **How it works:** Inbound — for each `post["file_ids"]`, `GET files/{fid}/info` gives the name and `mime_type`, then `GET /api/v4/files/{fid}` with the bearer header (30 s timeout) fetches the bytes, which are cached by `cache_image_from_bytes` (image/*), `cache_audio_from_bytes` (audio/*) or `cache_document_from_bytes` (everything else). Outbound — `_upload_file(channel_id, file_data, filename, content_type)` (`:281`) POSTs multipart `channel_id` + `files` to `/api/v4/files` (60 s timeout) and returns `file_infos[0]["id"]`, which is then attached to a post as `file_ids`. Helpers: `_send_url_as_file()` (`:534`), `_send_local_file()` (`:598`), `send_image()` (`:454`), `send_image_file()` (`:467`), `send_document()` (`:480`), `send_voice()` (`:494`), `send_video()` (`:507`).
- **Inputs / options:** `file_path`/`image_url`, `caption`, `reply_to`, `file_name`, `metadata`.
- **Outputs / side effects:** Native Mattermost attachments. Failures log `MM file upload → %s: %s`, `Mattermost: failed to download file %s: HTTP %s`, `Mattermost: error downloading file %s: %s`, `Mattermost: local file not found, skipping: %s`; returns `SendResult(success=False, error="File upload failed")` / `"Failed to post with file"`.
- **Config / env:** n/a.
- **Edge cases / guards:** Inbound message type is upgraded from `TEXT` to `PHOTO` / `VOICE` / `DOCUMENT` based on the downloaded MIME types.
- **Rebuild notes:** Download with the bot token and hand the agent a local path, never a signed URL. A better version would stream uploads instead of reading whole files into memory.

### Mattermost multi-image batching (5 per post)  `id: platforms-a.mattermost-multi-image`
- **Surface:** Core (Platform:mattermost)
- **Where:** Replies containing several generated images.
- **What it does:** Uploads several images and attaches them to as few posts as possible, respecting Mattermost's cap.
- **How it works:** `send_multiple_images()` at `plugins/platforms/mattermost/adapter.py:639`. `CHUNK = 5` (`:661`) — "Mattermost post file_ids cap". Each image is uploaded individually (the file API is one-at-a-time), then one post per chunk references all its `file_ids`. Sources may be `file://` paths or HTTP(S) URLs; the filename falls back to `image_url.rsplit("/",1)[-1].split("?")[0]` or `f"image_{n}.png"`.
- **Inputs / options:** A list of image URLs/paths plus an optional caption.
- **Outputs / side effects:** One post per group of up to 5 images.
- **Config / env:** n/a.
- **Edge cases / guards:** A chunk whose uploads all fail is skipped rather than posting an empty message.
- **Rebuild notes:** Upload serially, group by the platform's attachment cap. A better version would upload in parallel with a bounded semaphore.

### Mattermost typing indicator  `id: platforms-a.mattermost-typing`
- **Surface:** Core (Platform:mattermost)
- **Where:** The "is typing…" indicator in the channel.
- **What it does:** Signals that the bot is working.
- **How it works:** `send_typing()` at `plugins/platforms/mattermost/adapter.py:432` POSTs `{"channel_id": chat_id}` to `users/{bot_user_id}/typing`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A typing event.
- **Config / env:** n/a.
- **Edge cases / guards:** Failures are logged by `_api_post` but not surfaced.
- **Rebuild notes:** One POST per refresh interval. A better version would stop sending it once a progress message exists.

### Mattermost message editing  `id: platforms-a.mattermost-edit`
- **Surface:** Core (Platform:mattermost)
- **Where:** Progressive/streaming replies.
- **What it does:** Patches an existing post in place.
- **How it works:** `edit_message()` at `plugins/platforms/mattermost/adapter.py:441` PUTs `_with_mentions_disabled({"message": formatted})` to `posts/{message_id}/patch`.
- **Inputs / options:** `finalize` flag (accepted, not used to change the request).
- **Outputs / side effects:** The post is updated; `SendResult(success=False, error="Failed to edit post")` on failure.
- **Config / env:** n/a.
- **Edge cases / guards:** Mentions stay disabled on edits too.
- **Rebuild notes:** `PUT /posts/{id}/patch` with just the message field. A better version would coalesce rapid edits to respect server rate limits.

### Mattermost markdown formatting  `id: platforms-a.mattermost-format`
- **Surface:** Core (Platform:mattermost)
- **Where:** Every outgoing post.
- **What it does:** Strips image markdown into plain links, since files are uploaded separately; the rest of the markdown passes through (Mattermost renders GFM natively).
- **How it works:** `format_message()` at `plugins/platforms/mattermost/adapter.py:520`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Cleaned message text.
- **Config / env:** n/a.
- **Edge cases / guards:** Chunking uses `truncate_message(formatted, MAX_POST_LENGTH)` at 4 000 characters.
- **Rebuild notes:** Strip only what the platform cannot render. A better version would convert image markdown into actual uploads instead of dropping to a link.

### Mattermost per-channel prompts  `id: platforms-a.mattermost-channel-prompts`
- **Surface:** Config (Platform:mattermost)
- **Where:** `mattermost.channel_prompts` in `~/.hermes/config.yaml`, keyed by channel ID.
- **What it does:** Injects an ephemeral system prompt on every turn in a specific channel.
- **How it works:** `resolve_channel_prompt(self.config.extra, channel_id, None)` from `gateway.platforms.base`, called at `plugins/platforms/mattermost/adapter.py:1000` and attached to the `MessageEvent` as `channel_prompt`.
- **Inputs / options:** YAML mapping of channel ID → prompt text (block scalars supported).
- **Outputs / side effects:** No persisted state — "injected at runtime on every turn — never persisted to transcript history — so changes take effect immediately".
- **Config / env:** `mattermost.channel_prompts`.
- **Edge cases / guards:** "Keys are Mattermost channel IDs (find them in the channel URL or via the API)."
- **Rebuild notes:** Resolve at event-build time and carry it on the event. A better version would support thread-level overrides.

### Mattermost home channel & cron delivery  `id: platforms-a.mattermost-home-channel`
- **Surface:** Config (Platform:mattermost)
- **Where:** `MATTERMOST_HOME_CHANNEL` in `~/.hermes/.env`, or `/sethome` in any channel where the bot is present.
- **What it does:** Names the channel that receives cron output, reminders and notifications.
- **How it works:** Registered as `cron_deliver_env_var="MATTERMOST_HOME_CHANNEL"` (`plugins/platforms/mattermost/adapter.py:1329`).
- **Inputs / options:** A 26-character channel ID (e.g. `abc123def456ghi789jkl012mn`), found via channel name → **View Info**.
- **Outputs / side effects:** Proactive messages posted there.
- **Config / env:** `MATTERMOST_HOME_CHANNEL`.
- **Edge cases / guards:** The bot must be a member of the channel.
- **Rebuild notes:** One env var settable from chat. A better version would verify membership before accepting it.

### Mattermost standalone (out-of-process) sender  `id: platforms-a.mattermost-standalone-send`
- **Surface:** Core (Platform:mattermost)
- **Where:** Invisible — cron or `send_message` outside the gateway process.
- **What it does:** Posts a message (optionally threaded, optionally with attachments) straight to the Mattermost v4 REST API without a live adapter.
- **How it works:** `_standalone_send(pconfig, chat_id, message, *, thread_id=None, media_files=None, force_document=False)` at `plugins/platforms/mattermost/adapter.py:1026`. Two phases: upload each media file to `POST /api/v4/files` as multipart (`channel_id` + `files`) collecting `file_infos[].id`, then `POST /api/v4/posts` with `{"channel_id", "message"}` plus `root_id` (when `thread_id` is given) and `file_ids` (when uploads succeeded).
- **Inputs / options:** `chat_id`, `message`, `thread_id`, `media_files` (paths or `{"path": …}` dicts), `force_document` — "accepted for signature parity with other standalone senders but unused — Mattermost stores every uploaded file as a generic attachment regardless".
- **Outputs / side effects:** Returns `{"success": True, "platform": "mattermost", "chat_id": …, "message_id": …}` or `{"error": …}`. Error strings verbatim: `aiohttp not installed. Run: pip install aiohttp`; `Mattermost standalone send: MATTERMOST_URL and MATTERMOST_TOKEN must both be set`; `Mattermost file upload failed ({status}): {body[:400]}`; `Mattermost API error ({status}): {body[:400]}`; `Mattermost send failed (network): {exc}`; `Mattermost send failed: {exc}`.
- **Config / env:** `pconfig.extra["url"]` or `MATTERMOST_URL`; `pconfig.token` or `MATTERMOST_TOKEN` (read scope-aware).
- **Edge cases / guards:** Media paths that do not exist are skipped silently; only HTTP 200/201 count as success.
- **Rebuild notes:** Upload-then-post, with the same field names as the adapter. A better version would share one send implementation between the adapter and the standalone path.

### Mattermost troubleshooting matrix  `id: platforms-a.mattermost-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/mattermost.md:255`.
- **What it does:** Maps each observed Mattermost failure to its cause and fix.
- **How it works:** Static documentation matching the adapter's failure modes.
- **Inputs / options:** Entries verbatim (Heading → Cause → Fix):
  - "Bot is not responding to messages" → "The bot is not a member of the channel, or `MATTERMOST_ALLOWED_USERS` doesn't include your User ID." → add the bot to the channel, verify the allowlist, restart the gateway.
  - "403 Forbidden errors" → "The bot token is invalid, or the bot doesn't have permission to post in the channel." → check `MATTERMOST_TOKEN`, confirm the bot account is not deactivated, verify channel membership; for a PAT ensure the account has the required permissions.
  - "WebSocket disconnects / reconnection loops" → "Network instability, Mattermost server restarts, or firewall/proxy issues with WebSocket connections." → "The adapter automatically reconnects with exponential backoff (2s → 60s)"; reverse proxies need WebSocket upgrade headers — the doc gives the nginx block `location /api/v4/websocket { proxy_pass http://mattermost-backend; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 600s; }`.
  - "\"Failed to authenticate\" on startup" → wrong token or URL → verify with `curl -H "Authorization: Bearer YOUR_TOKEN" https://your-server/api/v4/users/me`.
  - "Bot is offline" → the gateway isn't running or failed to connect.
  - "\"User not allowed\" / Bot ignores you" → "Your User ID isn't in `MATTERMOST_ALLOWED_USERS`… Remember: the User ID is a 26-character alphanumeric string, not your `@username`."
- **Outputs / side effects:** n/a.
- **Config / env:** all Mattermost keys.
- **Edge cases / guards:** Notes verbatim: "**Self-hosted friendly**: Works with any self-hosted Mattermost instance. No Mattermost Cloud account or subscription required."; "**No extra dependencies**: The adapter uses `aiohttp` for HTTP and WebSocket, which is already included with Hermes Agent."; "**Team Edition compatible**: Works with both Mattermost Team Edition (free) and Enterprise Edition."
- **Rebuild notes:** Encode the checks as startup diagnostics. A better version would probe the WebSocket path through the reverse proxy at connect and name the nginx fix itself.

---

## 6. Microsoft Teams

### Microsoft Teams platform adapter  `id: platforms-a.teams`
- **Surface:** Platform:teams
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Microsoft Teams"** (emoji 💼); runs inside `hermes gateway`, listening on `http://<host>:3978/api/messages`. In Teams itself: personal chats (DMs), group chats and channel posts.
- **What it does:** Connects Hermes to Microsoft Teams through the **Bot Framework**, receiving activities on a public HTTPS webhook (via a tunnel or reverse proxy) and replying with markdown messages, attachments and Adaptive Cards.
- **How it works:** `plugins/platforms/teams/adapter.py:795` defines `TeamsAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/teams/adapter.py:1628` calls `ctx.register_platform(name="teams", label="Microsoft Teams", adapter_factory=lambda cfg: TeamsAdapter(cfg), check_fn=check_requirements, ensure_deps_fn=check_teams_requirements, validate_config=validate_config, is_connected=is_connected, required_env=["TEAMS_CLIENT_ID","TEAMS_CLIENT_SECRET","TEAMS_TENANT_ID"], install_hint=_install_hint(), setup_fn=interactive_setup, env_enablement_fn=_env_enablement, cron_deliver_env_var="TEAMS_HOME_CHANNEL", standalone_sender_fn=_standalone_send, allowed_users_env="TEAMS_ALLOWED_USERS", allow_all_env="TEAMS_ALLOW_ALL_USERS", max_message_length=28000, emoji="💼", allow_update_command=True, platform_hint=…)`. Manifest `plugins/platforms/teams/plugin.yaml:1` (`name: teams-platform`, `label: Microsoft Teams`, `kind: platform`, `version: 1.0.0`, `author: Aamir Jawaid`). `connect()` (`:825`) builds an `aiohttp.web.Application(client_max_size=_MAX_BODY_BYTES)` (1 MiB) with a `GET /health` route returning `ok`, constructs `App(client_id, client_secret, tenant_id, http_server_adapter=_AiohttpBridgeAdapter(aiohttp_app), client=ClientOptions(headers={"User-Agent": "Hermes"}))`, registers `@app.on_message` → `_on_message` and `@app.on_card_action` → `_on_card_action`, wires plugin handlers, calls `app.initialize()` (which registers `POST /api/messages` on the aiohttp app via the bridge), then starts an `AppRunner` + `TCPSite`. Constants: `_DEFAULT_PORT = 3978` (`:140`), `_MAX_BODY_BYTES = 1_048_576` (`:143`), `_DEFAULT_HOST = None` (`:149`), `_WEBHOOK_PATH = "/api/messages"` (`:150`).
- **Inputs / options:** Env table verbatim: `TEAMS_CLIENT_ID` — "Azure AD App (client) ID"; `TEAMS_CLIENT_SECRET` — "Azure AD client secret"; `TEAMS_TENANT_ID` — "Azure AD tenant ID"; `TEAMS_ALLOWED_USERS` — "Comma-separated AAD object IDs allowed to use the bot"; `TEAMS_ALLOW_ALL_USERS` — "Set `true` to skip the allowlist and allow anyone"; `TEAMS_HOME_CHANNEL` — "Conversation ID for cron/proactive message delivery"; `TEAMS_HOME_CHANNEL_NAME` — "Display name for the home channel"; `TEAMS_PORT` — "Webhook port (default: `3978`)". Also read: `TEAMS_HOST` (bind host; manifest description "default: unset → dual-stack, all interfaces IPv4+IPv6"), `TEAMS_SERVICE_URL`, `TEAMS_GRAPH_ACCESS_TOKEN`, `TEAMS_DELIVERY_MODE`, `TEAMS_INCOMING_WEBHOOK_URL`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`, `TEAMS_CHAT_ID`. Config: `platforms.teams.enabled` plus `platforms.teams.extra.{client_id, client_secret, tenant_id, port, host, service_url, home_channel, delivery_mode, incoming_webhook_url, team_id, channel_id, chat_id, access_token, meeting_pipeline}`.
- **Outputs / side effects:** Binds a local HTTP listener; posts activities and Adaptive Cards through the Bot Framework connector. Startup log verbatim: `[teams] Webhook server listening on %s:%d%s` (host rendered as `* (all interfaces, IPv4+IPv6)` when unset); shutdown `[teams] Disconnected`.
- **Config / env:** as enumerated; `platform_hint` sent to the model verbatim: "You are chatting via Microsoft Teams. Teams renders a subset of markdown — bold (**text**), italic (*text*), and inline code (`code`) work, but complex tables or raw HTML do not. Keep responses clear and professional."
- **Edge cases / guards:** `_DEFAULT_HOST = None` makes aiohttp bind **one socket per address family (IPv4 + IPv6)** — the old hardcoded `"0.0.0.0"` bound IPv4 only and was unreachable on IPv6-only private networks (e.g. Fly.io 6PN). Fatal errors set by `connect()`: `MISSING_SDK` (`microsoft-teams-apps could not be installed. Run: <python> -m pip install microsoft-teams-apps` / `aiohttp not installed. Run: <python> -m pip install aiohttp`, both non-retryable), `MISSING_CREDENTIALS` (`TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET, and TEAMS_TENANT_ID are all required`, non-retryable), `CONNECT_FAILED` (`Teams connection failed: <e>`, retryable). Teams delivers @mentions as `<at>BotName</at>` tags, stripped by `re.sub(r"<at>[^<]*</at>\s*", "", text).strip()`.
- **Rebuild notes:** Minimal spec: an aiohttp server exposing `POST /api/messages` + `GET /health`, a Bot Framework `App` bound to it, `on_message` → agent, `on_card_action` → approval resolution. A better version would validate the incoming JWT itself rather than relying entirely on the SDK, and would expose the tunnel URL check as a startup diagnostic.

### Teams lazy dependency install  `id: platforms-a.teams-lazy-deps`
- **Surface:** Core (Platform:teams)
- **Where:** First gateway start with Teams enabled.
- **What it does:** Installs the Microsoft Teams SDK into Hermes' own venv rather than failing, and gives a copy-pasteable manual command that works on PEP 668 systems.
- **How it works:** Two functions, deliberately separated: `check_requirements()` at `plugins/platforms/teams/adapter.py:439` is the **PASSIVE** probe (`TEAMS_SDK_AVAILABLE and AIOHTTP_AVAILABLE`, never installs — safe for status displays), registered as `check_fn`; `check_teams_requirements()` at `:725` is the **ACTIVE** lazy installer, registered as `ensure_deps_fn` and run by `create_adapter()` when the passive probe fails. `connect()` re-runs it defensively and gates on `App is None or ClientOptions is None` rather than the `find_spec`-based `TEAMS_SDK_AVAILABLE` flag, which can be `True` from the `microsoft_teams` namespace package without symbols ever being bound. `_install_hint()` (`:1609`) derives the command from `tools.lazy_deps.feature_install_command("platform.teams", venv_pip=True)` so a CVE pin bump never leaves the string stale, falling back to `f"{sys.executable} -m pip install microsoft-teams-apps aiohttp"`; the rendered hint is `Teams SDK missing — restart the gateway to auto-install, or run: <cmd>`. Third-party dotenv loading during the SDK import is suppressed by `_suppress_third_party_dotenv()` (`:701`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Packages installed into the Hermes venv.
- **Config / env:** n/a.
- **Edge cases / guards:** Doc note verbatim: "do **not** use system `pip install` on Ubuntu 24.04 — that hits PEP 668 `externally-managed-environment`"; manual install `~/.hermes/hermes-agent/venv/bin/pip install microsoft-teams-apps aiohttp` or `uv sync --extra teams`. For source/local installs: `uv sync --extra teams` / `uv pip install -e ".[teams]"`.
- **Rebuild notes:** Separate the "is it installed?" probe from the "install it" action so status calls never mutate the environment. A better version would pin and verify the SDK version at import.

### Teams interactive setup wizard  `id: platforms-a.teams-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Microsoft Teams**.
- **What it does:** Walks the operator through the Teams CLI bot registration and collects the three Azure AD credentials plus an allowlist.
- **How it works:** `interactive_setup()` at `plugins/platforms/teams/adapter.py:1536`.
- **Inputs / options:** Verbatim strings in order:
  - `Teams: already configured (app ID: <TEAMS_CLIENT_ID>)` + `Reconfigure Teams?` (yes/no, default `False`)
  - `You'll need the Teams CLI. If you haven't already:`
  - `  npm install -g @microsoft/teams.cli@preview`
  - `  teams login`
  - `Then expose port 3978 publicly (devtunnel / ngrok / cloudflared),`
  - `and create your bot:`
  - `  teams app create --name "Hermes" --endpoint "https://<tunnel>/api/messages"`
  - `The CLI will print CLIENT_ID, CLIENT_SECRET, and TENANT_ID. Paste them below.`
  - prompt `Client ID` (defaults to the existing value) → on empty: `Client ID is required — skipping Teams setup`
  - prompt `Client secret` (password, defaults to existing) → on empty: `Client secret is required — skipping Teams setup`
  - prompt `Tenant ID` (defaults to existing) → on empty: `Tenant ID is required — skipping Teams setup`
  - `To find your AAD object ID for the allowlist: teams status --verbose`
  - `Restrict access to specific users? (recommended)` (yes/no, default `True`)
    - yes → prompt `Allowed AAD object IDs (comma-separated)` (defaults to existing) → `Allowlist configured`, or writes an empty `TEAMS_ALLOWED_USERS` when blank
    - no → writes `TEAMS_ALLOW_ALL_USERS=true` and warns `⚠️  Open access — anyone who can message the bot can command it.`
  - `Teams configuration saved to ~/.hermes/.env`
  - `Install the app in Teams:  teams app install --id <teamsAppId>`
  - `Restart the gateway:       hermes gateway restart`
- **Outputs / side effects:** Writes `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, `TEAMS_TENANT_ID`, and either `TEAMS_ALLOWED_USERS` or `TEAMS_ALLOW_ALL_USERS`.
- **Config / env:** as above.
- **Edge cases / guards:** Any missing credential aborts the wizard with the corresponding warning, leaving earlier values saved.
- **Rebuild notes:** Prompt sequence keyed to an external CLI's output. A better version would shell out to `teams app create` itself and read the JSON back.

### Teams bot registration via the Teams CLI  `id: platforms-a.teams-cli-registration`
- **Surface:** Docs / CLI (external)
- **Where:** A terminal, using `@microsoft/teams.cli`.
- **What it does:** Registers the bot with Microsoft (no Azure portal needed), exposes the webhook publicly, and installs the app into Teams.
- **How it works:** Documented at `website/docs/user-guide/messaging/teams.md:36`.
- **Inputs / options:** Commands verbatim:
  - `npm install -g @microsoft/teams.cli@preview`
  - `teams login`
  - `teams status --verbose` — "To verify your login and find your own AAD object ID (needed for `TEAMS_ALLOWED_USERS`)"
  - Tunnels: `devtunnel create hermes-bot --allow-anonymous`; `devtunnel port create hermes-bot -p 3978 --protocol http`; `devtunnel host hermes-bot`; `ngrok http 3978`; `cloudflared tunnel --url http://localhost:3978`
  - `teams app create --name "Hermes" --endpoint "https://<your-tunnel-url>/api/messages"`
  - `teams app get <teamsAppId> --install-link`
  - `teams app update --id <teamsAppId> --endpoint "https://your-domain.com/api/messages"`
  - Health check: `curl http://localhost:3978/health` → returns `ok`
- **Outputs / side effects:** A registered bot with `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID` and an install link.
- **Config / env:** `TEAMS_PORT` changes the port used everywhere above.
- **Edge cases / guards:** "The public tunnel URL uses HTTPS, but Hermes' local webhook listener uses plain HTTP. The tunnel terminates TLS and forwards HTTP to port `3978`; do not configure the local tunnel port as HTTPS." "Save the client secret — it won't be shown again."
- **Rebuild notes:** Depend on the vendor CLI for registration; keep the endpoint path fixed at `/api/messages`. A better version would detect a running tunnel and offer to register the endpoint automatically.

### Teams Adaptive Card approval prompts  `id: platforms-a.teams-approval-cards`
- **Surface:** Platform:teams
- **Where:** An Adaptive Card in the chat, headed **"⚠️ Command Approval Required"**, with buttons **"Allow Once"**, **"Allow Session"**, **"Always Allow"**, **"Deny"**.
- **What it does:** Asks for approval of a dangerous command with tappable card buttons instead of typing `/approve`, and replaces the card with the decision.
- **How it works:** `send_exec_approval()` at `plugins/platforms/teams/adapter.py:1291`. Card body: `TextBlock("⚠️ Command Approval Required", wrap=True, weight="Bolder")`, `TextBlock("```\n<cmd_preview>\n```", wrap=True)` with `cmd_preview = command[:2000] + "..."` when longer, `TextBlock(f"Reason: {description}", wrap=True, isSubtle=True)`, plus `TextBlock("Smart DENY: owner override applies to this one operation only.", wrap=True)` when `smart_denied`. Buttons are `ExecuteAction(title=…, verb="hermes_approve", data={session_key, cmd (truncated to 200 + "..."), desc, hermes_action}, style=…)` — `"Allow Once"` (`approve_once`, style `positive`), `"Allow Session"` (`approve_session`), `"Always Allow"` (`approve_always`), `"Deny"` (`deny`, style `destructive`). Card version `1.4`. Clicks land in `_on_card_action()` (`:1198`), which maps `approve_once|approve_session|approve_always|deny` → `once|session|always|deny` and calls `tools.approval.resolve_gateway_approval(session_key, choice)`. Sending uses `_send_card()` (`:1186`), which prefers a stored `ConversationReference` (cached per conversation id in `_conv_refs` on every inbound message) so approval cards can be sent proactively.
- **Inputs / options:** Four buttons; `allow_session=False` / `allow_permanent=False` / `smart_denied=True` remove the middle buttons exactly as on the other platforms.
- **Outputs / side effects:** The card is replaced by an `AdaptiveCardActionCardResponse` whose body repeats the command/reason plus a bold decision line — labels verbatim: `✅ Allowed (once)`, `✅ Allowed (session)`, `✅ Always allowed`, `❌ Denied`. An already-resolved or expired approval renders `⚠️ Approval already resolved or expired.` (checked with `tools.approval.has_blocking_approval`).
- **Config / env:** `TEAMS_ALLOWED_USERS`, `TEAMS_ALLOW_ALL_USERS`.
- **Edge cases / guards:** **Default-deny on card clicks.** Without `TEAMS_ALLOW_ALL_USERS=true`, an empty `TEAMS_ALLOWED_USERS` rejects every click with the message `⛔ Approval buttons require TEAMS_ALLOWED_USERS to be configured.` and the log `[teams] card action rejected: TEAMS_ALLOWED_USERS not configured and TEAMS_ALLOW_ALL_USERS not set — default deny` — without this "any Teams user who could message the bot could approve dangerous commands". A clicker not on the allowlist (matched on `aad_object_id`, falling back to `id`; `*` allows all) gets `⛔ Not authorized.` and the log `[teams] Unauthorized card action by %s — ignoring`. Missing `hermes_action`/`session_key` or an unknown action returns `Unknown action.` Send failures log `[teams] send_exec_approval failed: %s` and return `retryable=True`.
- **Rebuild notes:** Carry the session key and a truncated command in the button data so the response card can be rebuilt without server state, and default-deny when no allowlist exists. A better version would sign the button data so a crafted `Action.Execute` payload cannot spoof a session key.

### Teams inbound message handling  `id: platforms-a.teams-inbound`
- **Surface:** Core (Platform:teams)
- **Where:** Invisible — every Bot Framework message activity.
- **What it does:** Filters, deduplicates, strips mentions, classifies the conversation and downloads attachments, then dispatches to the agent.
- **How it works:** `_on_message(ctx)` at `plugins/platforms/teams/adapter.py:1014`. Order: (1) drop when `activity.from_.id == self._app.id`; (2) `MessageDeduplicator.is_duplicate(activity.id)`; (3) cache `ctx.conversation_ref` under `activity.conversation.id` in `_conv_refs` for proactive sends; (4) strip `<at>…</at>` mention tags; (5) map `conversation.conversation_type` — `"personal"` → `dm`, `"groupChat"` → `group`, `"channel"` → `channel`, anything else → `dm`; (6) build the source with `user_id = from_.aad_object_id or from_.id`, `user_name = from_.name`, `guild_id = conversation.tenant_id or self._tenant_id`; (7) process attachments.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A `MessageEvent` with `media_urls` / `media_types` / `media_kinds`.
- **Config / env:** n/a.
- **Edge cases / guards:** Attachment payloads that are **not** files are skipped explicitly: `text/html` and `text/plain` without a `content_url` (Teams mirrors the message body as a `text/html` attachment on **every** message), and anything whose content type starts with `application/vnd.microsoft.card` (adaptive/hero cards). `application/vnd.microsoft.teams.file.download.info` attachments carry a pre-authenticated SharePoint `downloadUrl` plus the real `fileType`; the filename falls back to `document.<fileType>` or `document`. Unsupported document types log `[teams] Unsupported document type for attachment '%s', skipping`; caching failures log `[teams] Failed to cache file attachment '%s': %s`.
- **Rebuild notes:** Skip the body-mirroring attachment and the card attachments before doing any network work. A better version would use `activity.entities` mention data instead of regex-stripping `<at>` tags.

### Teams attachment download & Bot Framework token  `id: platforms-a.teams-attachments`
- **Surface:** Core (Platform:teams)
- **Where:** Invisible — inline/pasted images and file attachments.
- **What it does:** Downloads Teams attachments safely, acquiring the bot's own bearer token for Bot Framework connector URLs that are not pre-authenticated.
- **How it works:** `_fetch_attachment_bytes(url, timeout=30.0)` at `plugins/platforms/teams/adapter.py:977`: rejects unsafe URLs via `tools.url_safety.is_safe_url` (`Blocked unsafe attachment URL (SSRF protection)`), adds `User-Agent: Mozilla/5.0 (compatible; HermesAgent/1.0)`, and — only when `_is_botframework_attachment_url(url)` — adds `Authorization: Bearer <bot token>`; the request runs through `create_ssrf_safe_async_client(follow_redirects=True, event_hooks={"response": [_ssrf_redirect_guard]})` and the body is read with `_read_httpx_body_with_limit(response, media_type="attachment")` so "a lying Content-Length must not OOM the gateway". `_get_botframework_token()` (`:930`) POSTs `grant_type=client_credentials`, `client_id`, `client_secret`, `scope=https://api.botframework.com/.default` to `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token` (httpx, 15 s), caching the token until ~5 minutes before expiry and serializing refreshes with a **lazily created** `asyncio.Lock` (creating it in `__init__` would bind it to the wrong event loop on Python < 3.10).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Cached media files; token acquisition failures log `[teams] Could not acquire Bot Framework token for attachment: %s` and the download proceeds unauthenticated.
- **Config / env:** `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, `TEAMS_TENANT_ID` (missing any raises `Missing TEAMS_CLIENT_ID/SECRET/TENANT_ID for attachment auth`).
- **Edge cases / guards:** `_is_botframework_attachment_url()` (`:517`) is an **exact host match** against `_ALLOWED_TEAMS_SERVICE_HOSTS` plus `scheme == "https"` and port in `(None, 443)` — the comment is explicit that a suffix match would be unsafe because "any Azure customer can register `<name>.trafficmanager.net` Traffic Manager profiles", so a lookalike host must never receive the bot's bearer token; new Bot Framework regions are allowlist additions, not predicate changes. SharePoint `downloadUrl`s are pre-authed and get no header.
- **Rebuild notes:** Attach credentials only to an exact-match host allowlist, and stream with a size cap. A better version would scope the token per-attachment host rather than reusing one connector token.

### Teams service-URL allowlist & conversation-ID validation  `id: platforms-a.teams-service-url-guard`
- **Surface:** Core (Platform:teams)
- **Where:** Invisible — outbound Bot Framework calls, especially from the standalone sender.
- **What it does:** Blocks SSRF and token exfiltration through a tampered `TEAMS_SERVICE_URL`, and stops a hostile conversation ID from escaping the URL path.
- **How it works:** `_DEFAULT_TEAMS_SERVICE_URL = "https://smba.trafficmanager.net/teams/"` (`plugins/platforms/teams/adapter.py:506`); `_ALLOWED_TEAMS_SERVICE_HOSTS = frozenset({"smba.trafficmanager.net", "smba.infra.gov.teams.microsoft.us"})` (`:511`); `_validate_teams_service_url(raw)` (`:548`) requires `https://` and an allowlisted host, and appends a trailing slash so callers can append `v3/conversations/...` without doubling. `_TEAMS_CONV_ID_RE = re.compile(r"^[A-Za-z0-9:@\-_.]+$")` (`:545`) — "Real values combine digits, colons, hyphens, dots, '@', and the `thread.skype` / `thread.tacv2` suffixes; reject anything outside this set so a hostile value cannot path-traverse out of `/v3/conversations/<id>/activities`."
- **Inputs / options:** `TEAMS_SERVICE_URL` or `extra.service_url` — needed for regional/government tenants (e.g. `https://smba.infra.gov.teams.microsoft.us/`).
- **Outputs / side effects:** A normalized URL, or a refusal.
- **Config / env:** `TEAMS_SERVICE_URL`, `platforms.teams.extra.service_url`.
- **Edge cases / guards:** The standalone sender returns `Teams standalone send: TEAMS_SERVICE_URL host is not on the Bot Framework allowlist; expected one of ['smba.infra.gov.teams.microsoft.us', 'smba.trafficmanager.net']`, `Teams standalone send: chat_id contains characters outside the Bot Framework conversation ID set`, and `Teams standalone send: TEAMS_TENANT_ID contains characters outside the expected set`.
- **Rebuild notes:** Allowlist hosts, validate every path segment against a character class, never string-concatenate untrusted IDs into a URL. A better version would percent-encode the conversation id as well as validating it.

### Teams send & threaded reply fallback  `id: platforms-a.teams-send`
- **Surface:** Core (Platform:teams)
- **Where:** Every reply.
- **What it does:** Sends chunked markdown activities, attempting a threaded reply when a numeric `reply_to` is available and falling back to a flat send when Teams rejects it.
- **How it works:** `send()` at `plugins/platforms/teams/adapter.py:1345`. For each chunk from `truncate_message(formatted)`: when `reply_to` is a non-zero digit string it tries `self._app.reply(chat_id, reply_to, chunk)`; **any** exception falls back to `self._app.send(chat_id, chunk)` with the debug log `Teams reply() failed, falling back to flat send: %s` — "Group chats 400 on threaded sends; the Teams SDK doesn't expose typed HTTP errors, so fall back on any exception". Max message length is 28 000 characters ("Teams supports up to ~28 KB per message").
- **Inputs / options:** `chat_id`, `content`, `reply_to`, `metadata`.
- **Outputs / side effects:** One or more activities; `SendResult(success=False, error=…, retryable=True)` on failure, `SendResult(success=False, error="Teams app not initialized")` when not connected.
- **Config / env:** n/a.
- **Edge cases / guards:** A `reply_to` that is not a digit string, or is `"0"`, always sends flat.
- **Rebuild notes:** Try threaded, degrade to flat, never lose the message. A better version would remember per-conversation whether threading works instead of retrying every time.

### Teams typing indicator & media attachments  `id: platforms-a.teams-typing-media`
- **Surface:** Core (Platform:teams)
- **Where:** The typing indicator in the chat; agent replies containing media.
- **What it does:** Sends a typing activity while working and uploads media as Teams attachments.
- **How it works:** `send_typing()` at `plugins/platforms/teams/adapter.py:1381` sends a `TypingActivityInput()` through `self._app.send`, swallowing every exception. `_send_media_attachment()` (`:1386`) handles media sources.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Typing activities and attachment activities.
- **Config / env:** n/a.
- **Edge cases / guards:** No-op when the app is not initialized.
- **Rebuild notes:** Fire-and-forget typing activity. A better version would refresh it on the Bot Framework's ~few-second decay.

### Teams env-enablement seeding  `id: platforms-a.teams-env-enablement`
- **Surface:** Core (Platform:teams)
- **Where:** Invisible — gateway config load, before adapter construction.
- **What it does:** Makes an env-only Teams setup show up in `hermes gateway status` and `get_connected_platforms()` without instantiating the Teams SDK.
- **How it works:** `_env_enablement()` at `plugins/platforms/teams/adapter.py:463`, registered as `env_enablement_fn`. Returns `None` unless all three of `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET` (read scope-aware via `_get_scoped_secret`) and `TEAMS_TENANT_ID` are set; otherwise seeds `{"client_id", "client_secret", "tenant_id"}` plus optional `port` (from `TEAMS_PORT`, ignored when not an int), `service_url` (from `TEAMS_SERVICE_URL`) and `home_channel` (`{"chat_id": TEAMS_HOME_CHANNEL, "name": TEAMS_HOME_CHANNEL_NAME or "Home"}`). "The special `home_channel` key in the returned dict becomes a proper `HomeChannel` dataclass on the `PlatformConfig` via the core hook."
- **Inputs / options:** the env vars above.
- **Outputs / side effects:** A seeded `PlatformConfig.extra`.
- **Config / env:** `TEAMS_*`.
- **Edge cases / guards:** `validate_config()` (`:449`) and `is_connected()` (`:458`) both require the same three credentials, preferring env over `extra`.
- **Rebuild notes:** Seed config from env before the adapter exists so status is honest without side effects. A better version would also report the last webhook delivery time.

### Teams standalone (out-of-process) sender  `id: platforms-a.teams-standalone-send`
- **Surface:** Core (Platform:teams)
- **Where:** Invisible — `deliver=teams` cron jobs running outside the gateway process.
- **What it does:** Mints a Bot Framework token and POSTs one message activity directly, so cron delivery does not fail with "No live adapter for platform".
- **How it works:** `_standalone_send(pconfig, chat_id, message, *, thread_id=None, media_files=None, force_document=False)` at `plugins/platforms/teams/adapter.py:571`. Token: `POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token` with `grant_type=client_credentials`, `client_id`, `client_secret`, `scope=https://api.botframework.com/.default`. Activity: `POST {service_url}v3/conversations/{chat_id}/activities` with `{"type": "message", "text": message, "textFormat": "markdown"}` and the bearer header. Both requests use a **per-request** `aiohttp.ClientTimeout(total=15.0)` "so a slow STS endpoint cannot starve the subsequent activity POST of its budget"; the session uses `trust_env=True`.
- **Inputs / options:** `chat_id` (the conversation ID, required), `message`, `thread_id`, `media_files`, `force_document`. The latter two are "accepted for signature parity but not implemented for the standalone path; messages with attachments will send as text-only. The live adapter handles attachments via the SDK."
- **Outputs / side effects:** Returns `{"success": True, "message_id": …}` or `{"error": …}`. Error strings verbatim: `Teams standalone send: TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET, and TEAMS_TENANT_ID are all required`; `Teams standalone send: TEAMS_SERVICE_URL host is not on the Bot Framework allowlist; expected one of [...]`; `Teams standalone send: chat_id (conversation ID) is required`; `Teams standalone send: chat_id contains characters outside the Bot Framework conversation ID set`; `Teams standalone send: TEAMS_TENANT_ID contains characters outside the expected set`; `Teams standalone send: aiohttp not installed`; `Teams standalone send: token request failed ({status}): {body[:300]}`; `Teams standalone send: token response missing access_token`; `Teams standalone send: activity post failed ({status}): {body[:300]}`; `Teams standalone send failed: {e}`.
- **Config / env:** `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, `TEAMS_TENANT_ID`, `TEAMS_HOME_CHANNEL` (the conversation ID), optional `TEAMS_SERVICE_URL`.
- **Edge cases / guards:** `asyncio.CancelledError` is re-raised rather than swallowed.
- **Rebuild notes:** Validate both the host and the conversation id before minting a token. A better version would reuse a cached token across cron runs instead of re-authenticating each time.

### Teams production deployment (reverse proxy)  `id: platforms-a.teams-production`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/teams.md:235`.
- **What it does:** Describes how to run the Teams webhook behind a permanent public HTTPS endpoint.
- **How it works:** "terminate TLS at a reverse proxy and forward requests to the plain HTTP Hermes listener, normally `http://127.0.0.1:3978`", then register the proxy's public endpoint with `teams app create --name "Hermes" --endpoint "https://your-domain.com/api/messages"` or update an existing bot with `teams app update --id <teamsAppId> --endpoint "https://your-domain.com/api/messages"`.
- **Inputs / options:** `TEAMS_PORT`, `TEAMS_HOST`.
- **Outputs / side effects:** n/a.
- **Config / env:** `TEAMS_PORT`, `TEAMS_HOST`.
- **Edge cases / guards:** "Make sure the public HTTPS endpoint is reachable from the internet and uses a valid TLS certificate. Teams rejects self-signed certificates. Keep the Hermes listener behind the proxy; port `3978` does not serve HTTPS itself."
- **Rebuild notes:** Never serve TLS from the adapter. A better version would emit a startup warning when the configured endpoint host resolves to localhost.

### Teams troubleshooting matrix  `id: platforms-a.teams-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/teams.md:255`.
- **What it does:** Maps each observed Teams failure to its fix.
- **How it works:** Static documentation matching the adapter's failure modes.
- **Inputs / options:** Rows verbatim (Problem → Solution):
  - "`Can't find a suitable configuration file` from `docker compose`" → "You are not in the repo that has `docker-compose.yml`, or you are on a native install — use `hermes gateway restart` instead, or `cd` into the clone first"
  - "`requirements not met` / `Teams SDK missing` / `No adapter available for teams`" → "Restart gateway so lazy-install can run, or install into the **Hermes venv**: `~/.hermes/hermes-agent/venv/bin/pip install microsoft-teams-apps aiohttp`. System `pip` fails on Ubuntu 24.04 (PEP 668) and would not affect the service anyway"
  - "`health` endpoint works but bot doesn't respond" → "Check that your tunnel is still running and the bot's messaging endpoint matches the tunnel URL"
  - "Logs show `\"UNKNOWN / HTTP/1.0\" 400` when Teams sends a message" → "The tunnel or reverse proxy is forwarding HTTPS to Hermes' plain HTTP listener. Terminate TLS at the proxy and forward HTTP to port `3978`"
  - "`KeyError: 'teams'` in logs" → "Restart the container — this is fixed in the current version"
  - "Bot responds with auth errors" → "Verify `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, and `TEAMS_TENANT_ID` are all set correctly"
  - "`No inference provider configured`" → "Check that `ANTHROPIC_API_KEY` (or another provider key) is set in `~/.hermes/.env`"
  - "Bot receives messages but ignores them" → "Your AAD object ID may not be in `TEAMS_ALLOWED_USERS`. Run `teams status --verbose` to find it"
  - "Tunnel URL changes on restart" → "devtunnel URLs are persistent if you use a named tunnel (`devtunnel create hermes-bot`). ngrok and cloudflared generate a new URL each run unless you have a paid plan — update the bot endpoint with `teams app update` when it changes"
  - "Teams shows \"This bot is not responding\"" → "The webhook returned an error. Check `docker logs hermes` / `hermes gateway status -l` for tracebacks"
  - "`[teams] Failed to connect` in logs" → "The SDK failed to authenticate. Double-check your credentials and that the tenant ID matches the account you used in `teams login`"
- **Outputs / side effects:** n/a.
- **Config / env:** all Teams keys.
- **Edge cases / guards:** Security notes verbatim: "**Always set `TEAMS_ALLOWED_USERS`** with the AAD object IDs of authorized users. Without this, anyone who can find or install your bot can interact with it."; "Treat `TEAMS_CLIENT_SECRET` like a password — rotate it periodically via the Azure portal or Teams CLI."; "Store credentials in `~/.hermes/.env` with permissions `600` (`chmod 600 ~/.hermes/.env`)"; "The bot only accepts messages from users in `TEAMS_ALLOWED_USERS`; unauthorized messages are silently dropped"; "Your public endpoint (`/api/messages`) is authenticated by the Teams Bot Framework — requests without valid JWTs are rejected".
- **Rebuild notes:** Ship the checks as startup diagnostics. A better version would probe the registered endpoint from outside and report the actual HTTP status.

---

## 7. Microsoft Teams meeting pipeline (`teams_pipeline` plugin)

### Teams meeting pipeline plugin  `id: platforms-a.teams-pipeline`
- **Surface:** Platform:teams (standalone plugin)
- **Where:** Enabled with `hermes plugins enable teams_pipeline` or `plugins.enabled: [teams_pipeline]` in `config.yaml`; operated with `hermes teams-pipeline …`.
- **What it does:** Ingests Microsoft Graph meeting webhook events, resolves each meeting, prefers transcript artifacts (falling back to recording download plus STT), summarizes, and writes the summary to Notion, Linear and/or Microsoft Teams.
- **How it works:** `plugins/teams_pipeline/plugin.yaml:1` (`name: teams_pipeline`, `version: 0.1.0`, `kind: standalone`, `author: NousResearch`, `platforms: [linux, macos, windows]`, description "Microsoft Teams meeting pipeline plugin with durable runtime state and operator CLI flows for Graph-backed transcript-first meeting summaries."). `register(ctx)` at `plugins/teams_pipeline/__init__.py:12` registers **only** a CLI command — `ctx.register_cli_command(name="teams-pipeline", help="Inspect and operate the Microsoft Teams meeting pipeline", setup_fn=register_cli, handler_fn=teams_pipeline_command, description="Operator CLI for the Microsoft Teams meeting pipeline. Lists jobs, inspects stored runs, replays jobs, validates Graph setup, and maintains Graph subscriptions.")`; the module docstring is explicit: "Registers only operator-facing CLI surfaces. The agent should invoke these via the terminal tool; no model tools are added by this plugin." Modules: `pipeline.py` (`TeamsMeetingPipeline` at `:273`, `TeamsPipelineConfig` at `:81`, `NotionWriter` at `:111`, `LinearWriter` at `:208`), `models.py` (`GraphSubscription` `:39`, `TeamsMeetingRef` `:95`, `MeetingArtifact` `:135`, `TeamsMeetingSummaryPayload` `:198`, `TeamsMeetingPipelineJob` `:271`), `store.py` (`TeamsPipelineStore` `:38`), `meetings.py`, `subscriptions.py`, `runtime.py`, `cli.py`. Documented flow: "1. receives Microsoft Graph webhook events 2. resolves the meeting and prefers transcript artifacts first 3. falls back to recording download plus STT when no usable transcript is available 4. stores durable job state and sink records locally 5. can write summaries to Notion, Linear, and Microsoft Teams".
- **Inputs / options:** Env: `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`, `MSGRAPH_WEBHOOK_ENABLED`, `MSGRAPH_WEBHOOK_PORT`, `MSGRAPH_WEBHOOK_CLIENT_STATE`, `MSGRAPH_WEBHOOK_ACCEPTED_RESOURCES`. Config under `platforms.teams.extra.meeting_pipeline` — `TeamsPipelineConfig` fields (`pipeline.py:81`): `transcript_preferred` (default `True`), `transcript_required` (`False`), `transcription_fallback` (`True`), `stt_model` (`None`, alias `sttModel`), `ffmpeg_extract_audio` (`True`), `transcript_min_chars` (`80`), `tmp_dir` (`None`, alias `tmpDir`), `notion` (`None`), `linear` (`None`), `teams_delivery` (`None`, alias `teamsDelivery`). Job states: `TERMINAL_PIPELINE_STATES = {"completed", "failed", "retry_scheduled"}` (`pipeline.py:42`) plus `ACTIVE_PIPELINE_STATES` (`:43`).
- **Outputs / side effects:** Durable JSON state at `~/.hermes/<...>/teams_pipeline_store.json` (`DEFAULT_TEAMS_PIPELINE_STORE_FILENAME`, `store.py:18`, path resolved by `resolve_teams_pipeline_store_path()` `:25`) holding jobs, subscriptions, notification receipts, event timestamps and sink records; summaries posted to the configured sinks.
- **Config / env:** as enumerated; prerequisites documented as "a working Hermes install", the Teams bot setup for outbound delivery, "Microsoft Graph application credentials", "a public HTTPS URL that Microsoft Graph can call for webhook delivery", and "`ffmpeg` installed if you want recording-plus-STT fallback".
- **Edge cases / guards:** Errors are typed — `TeamsPipelineError` (`pipeline.py:56`), `TeamsPipelineRetryableError` (`:60`), `TeamsPipelineSinkError` (`:64`), `TeamsPipelineArtifactNotFoundError` (`:68`, a retryable subclass). Notification receipts are deduplicated by `TeamsPipelineStore.build_notification_receipt_key()` (`store.py:108`). If the plugin is not enabled, the `teams.extra` delivery settings "are inert — they only wire up when the pipeline runtime binds to the Graph webhook ingress".
- **Rebuild notes:** Minimal spec: a webhook ingress that enqueues durable jobs, a resolver that prefers transcripts, a summarizer, and pluggable sinks — all keyed by a dedupe key so a redelivered Graph notification is a no-op. A better version would move the JSON store to SQLite and make sink writes idempotent by remote id.

### `hermes teams-pipeline` operator CLI  `id: platforms-a.teams-pipeline-cli`
- **Surface:** CLI
- **Where:** `hermes teams-pipeline <action> [...]`.
- **What it does:** Lists, inspects and replays pipeline jobs; dry-runs meeting artifact resolution; creates, lists, renews, deletes and maintains Microsoft Graph subscriptions; checks Graph token health; validates the whole configuration.
- **How it works:** `register_cli(subparser)` at `plugins/teams_pipeline/cli.py:31` builds the subparsers; `teams_pipeline_command(args)` at `:96` dispatches. Store path for every store-backed action comes from `--store-path` or `resolve_teams_pipeline_store_path()`.
- **Inputs / options:** Every sub-command and flag:
  - **`list`** (alias `ls`) — "List recent Teams pipeline jobs" — `--limit` (int, default `20`, clamped to `max(1, min(limit, 100))`), `--status` (string, case-insensitive filter), `--store-path`. Sorts by `updated_at` descending.
  - **`show <job_id>`** — "Show a stored Teams pipeline job" — `--store-path`.
  - **`run <job_id>`** (alias `replay`) — "Replay a stored Teams pipeline job" — `--store-path`.
  - **`fetch`** (alias `test`) — "Dry-run meeting artifact resolution" — `--meeting-id`, `--join-web-url`, `--organizer-user-id` (help: "Microsoft Entra user ID for organizer-scoped online meeting lookup"), `--tenant-id`, `--call-record-id`.
  - **`subscriptions`** (alias `subs`) — "List Graph subscriptions" — `--store-path`.
  - **`subscribe`** — "Create a Microsoft Graph subscription" — `--resource` (**required**), `--notification-url` (**required**), `--change-type` (default derived per resource), `--expiration` (default: now + 1 hour, ISO-8601 Z), `--client-state`, `--lifecycle-notification-url`, `--latest-supported-tls-version` (default `v1_2`), `--store-path`.
  - **`renew-subscription <subscription_id>`** — "Renew a Microsoft Graph subscription" — `--expiration` (**required**), `--store-path`.
  - **`delete-subscription <subscription_id>`** — "Delete a Microsoft Graph subscription" — `--store-path`.
  - **`maintain-subscriptions`** — "Renew near-expiry managed subscriptions" — `--renew-within-hours` (int, default `24`), `--extend-hours` (int, default `24`), `--dry-run` (flag), `--store-path`, `--client-state`.
  - **`token-health`** (alias `token`) — "Inspect Graph token health" — `--force-refresh` (flag).
  - **`validate`** — "Validate Teams pipeline configuration snapshot" — `--store-path`.
- **Outputs / side effects:** `list` prints `No Teams meeting pipeline jobs found.` or `\n{N} Teams pipeline job(s):\n` followed per job by `  ◆ <job_id>`, `    status: …`, `    meeting: …` (or `unknown`), `    strategy: …`, `    updated: …`, `    error: …`. `show` prints the job as indented sorted JSON with the transcript replaced by `transcript_preview` (first 240 chars) via `_compact_job()` (`:174`); unknown ids print `Unknown job: <id>`; a missing id prints `job_id is required`. `fetch` prints JSON with `meeting_ref`, `transcript_available`, `transcript_artifact`, `transcript_preview` (240 chars), `recording_count`, `recordings` (first 5), `call_record`; missing inputs print `meeting_id or join_web_url is required`. `subscriptions` prints `No Microsoft Graph subscriptions found.` or `\n{N} Microsoft Graph subscription(s):\n` then per subscription `  ◆ <id|unknown>`, `    resource: …`, `    changeType: …`, `    expires: …`, `    notify: …`. `subscribe`, `renew-subscription`, `delete-subscription`, `maintain-subscriptions`, `token-health` and `validate` all print indented sorted JSON. With no action the command prints `Usage: hermes teams-pipeline {list|show|run|fetch|subscriptions|subscribe|renew-subscription|delete-subscription|maintain-subscriptions|token-health|validate}` and exits **2**; an unknown action prints `Unknown teams-pipeline action: <action>` and exits **2**; `renew-subscription` without both args prints `subscription_id and --expiration are required`; `delete-subscription` without an id prints `subscription_id is required`.
- **Config / env:** `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`.
- **Edge cases / guards:** A `MicrosoftGraphConfigError` anywhere prints the setup hint verbatim and exits **1**: `\n  Microsoft Graph is not configured. Add these to <HERMES_HOME>/.env:\n\n    MSGRAPH_TENANT_ID=...\n    MSGRAPH_CLIENT_ID=...\n    MSGRAPH_CLIENT_SECRET=...\n\n  Then restart the gateway or rerun this command.\n`. `_default_change_type_for_resource()` (`:163`) returns `created` for resources starting with `communications/onlinemeetings/getalltranscripts`, `communications/onlinemeetings/getallrecordings` or `communications/callrecords`, and `updated` otherwise. `subscriptions` also syncs every listed subscription back into the local store, ignoring per-record failures.
- **Rebuild notes:** One argparse group over a JSON store plus a Graph client, printing JSON for machine use and bullet lists for humans. A better version would add `--json` to every sub-command so the human format is never parsed by scripts.

### Teams meeting summary delivery (`TeamsSummaryWriter`)  `id: platforms-a.teams-summary-delivery`
- **Surface:** Config (Platform:teams)
- **Where:** `platforms.teams.extra.delivery_mode` and its companions; the summary appears as a Teams message in a chat or channel.
- **What it does:** Posts a finished meeting summary into Teams — either through a static Incoming Webhook URL or through Microsoft Graph under the bot's identity.
- **How it works:** `TeamsSummaryWriter` at `plugins/platforms/teams/adapter.py:188` — deliberately inside the Teams platform plugin "so the meeting-pipeline PR can reuse one Teams integration surface instead of introducing a second adapter". `write_summary(payload, config, existing_record)` (`:207`): returns the existing record unchanged unless `force_resend` is truthy; resolves the mode from `delivery_mode`/`mode`, and when unset infers `incoming_webhook` if `incoming_webhook_url` is present, else `graph` if `chat_id` or (`team_id` and `channel_id`) are present; anything else raises `Teams delivery_mode must be 'incoming_webhook' or 'graph'.` `_resolve_delivery_config()` (`:233`) layers `platform_config.extra` → `platform_config.token` as `access_token` → `platform_config.home_channel.chat_id` as `channel_id` → the passed config → env defaults (`TEAMS_DELIVERY_MODE`, `TEAMS_INCOMING_WEBHOOK_URL`, `TEAMS_GRAPH_ACCESS_TOKEN`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`, `TEAMS_CHAT_ID`). Incoming-webhook mode (`:257`) POSTs `{"text": <markdown>}` with httpx (20 s) and raises for status. Graph mode (`:280`) posts `{"body": {"contentType": "html", "content": <html>}}` to `/chats/{chat_id}/messages` or `/teams/{team_id}/channels/{channel_id}/messages` (both URL-quoted with `safe=''`) via `MicrosoftGraphClient`, built by `_build_graph_client()` (`:324`) from a static `access_token` (wrapped in `_StaticAccessTokenProvider`, `:172`) or `MicrosoftGraphTokenProvider.from_env()`.
- **Inputs / options:** `delivery_mode: "graph" | "incoming_webhook"`; graph targets — `chat_id` ("post into a Teams chat") **or** `team_id` + `channel_id` **or** `team_id` + the platform `home_channel` fallback; `access_token` ("optional; falls back to `MSGRAPH_*` app credentials"); `incoming_webhook_url` for webhook mode; `force_resend`.
- **Outputs / side effects:** Incoming-webhook mode returns `{"delivery_mode": "incoming_webhook", "webhook_url", "status_code", "delivered": True}`. Graph mode returns `{"delivery_mode": "graph", "target_type": "chat"|"channel", …ids…, "message_id", "web_url"}`. Rendering: `_render_summary_markdown()` (`:342`) emits `**<title>**`, blank, `Summary: <text or "No summary available.">`, blank, `Key decisions:` + bullets, blank, `Action items:` + bullets, blank, `Risks:` + bullets — with `- None` when a list is empty; `_render_summary_html()` (`:359`) emits `<h2>title</h2>` then `<h3>Summary|Key decisions|Action items|Risks</h3>` with `<p>` for the summary, `<ul><li>…</li></ul>` for lists and `<p>None</p>` when empty, everything HTML-escaped. `_title()` (`:380`) falls back to `Meeting <meeting_id or 'summary'>`.
- **Config / env:** `TEAMS_DELIVERY_MODE`, `TEAMS_INCOMING_WEBHOOK_URL`, `TEAMS_GRAPH_ACCESS_TOKEN`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`, `TEAMS_CHAT_ID`; `platforms.teams.extra.*`.
- **Edge cases / guards:** Trade-off table verbatim — `incoming_webhook`: use when "Simple 'post a summary into this channel' with a static Teams-generated URL", trade-off "No reply threading, no reactions, shows as the webhook's configured identity"; `graph`: use for "Threaded channel posts or 1:1/group chat posts under the bot's identity via Microsoft Graph", trade-off "Requires the Graph app registration with `ChannelMessage.Send` (channel) or `Chat.ReadWrite.All` (chat) application permissions". Missing values raise `TEAMS_INCOMING_WEBHOOK_URL is required for incoming_webhook mode.` or `Graph delivery mode requires chat_id, or both team_id and channel_id.` `_StaticAccessTokenProvider` raises `TEAMS_GRAPH_ACCESS_TOKEN is required for graph delivery mode.` when empty.
- **Rebuild notes:** One writer class with two transports and a shared renderer, layered config resolution ending at env. A better version would record the posted message id so a re-run edits instead of duplicating.

### Teams pipeline `validate` configuration snapshot  `id: platforms-a.teams-pipeline-validate`
- **Surface:** CLI
- **Where:** `hermes teams-pipeline validate`.
- **What it does:** Prints a machine-readable readiness snapshot of Graph credentials, the webhook listener, Teams delivery configuration and the local store.
- **How it works:** `_validate_configuration_snapshot(store)` at `plugins/teams_pipeline/cli.py:198`. Loads the gateway config, looks up `Platform.MSGRAPH_WEBHOOK` and `Platform("teams")`, and builds the result.
- **Inputs / options:** `--store-path`.
- **Outputs / side effects:** JSON with keys `ok`, `issues`, `warnings`, `graph_config` (`{tenant_id, client_id, client_secret}` booleans), `webhook_enabled`, `teams_enabled`, `teams_delivery_mode`, `store_path`, `store_stats`. Issue strings verbatim: `Microsoft Graph app-only credentials are incomplete.`; `MSGRAPH_WEBHOOK_ENABLED is not enabled.`; `TEAMS_INCOMING_WEBHOOK_URL is required for incoming_webhook mode.`; and for graph mode, `<key> is required for graph delivery mode.` where `<key>` is one of `TEAMS_GRAPH_ACCESS_TOKEN or complete MSGRAPH_* app credentials`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`. Warning strings verbatim: `Teams outbound delivery is disabled.`; `TEAMS_DELIVERY_MODE is not set.`
- **Config / env:** `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`, `MSGRAPH_WEBHOOK_ENABLED`, `platforms.teams.*`.
- **Edge cases / guards:** `ok` is `not issues` — warnings do not fail the check. The channel check accepts `channel_id`, `chat_id`, or the Teams platform's `home_channel`.
- **Rebuild notes:** Emit issues and warnings as separate lists with a single boolean verdict. A better version would also make one live Graph call to prove the credentials actually work.

### Graph subscription lifecycle & 72-hour expiry  `id: platforms-a.teams-pipeline-subscriptions`
- **Surface:** CLI / Docs
- **Where:** `hermes teams-pipeline subscribe | subscriptions | renew-subscription | delete-subscription | maintain-subscriptions`.
- **What it does:** Creates and keeps alive the Microsoft Graph webhook subscriptions that feed the pipeline — Graph caps them at 72 hours and never auto-renews.
- **How it works:** `_cmd_subscribe()` (`plugins/teams_pipeline/cli.py:378`) POSTs `/subscriptions` with `{"changeType", "notificationUrl", "resource", "expirationDateTime", "latestSupportedTlsVersion"}` plus optional `clientState` and `lifecycleNotificationUrl`; `_cmd_renew_subscription()` (`:405`) PATCHes `/subscriptions/{id}` with `{"expirationDateTime": …}`; `_cmd_delete_subscription()` (`:424`) DELETEs it and removes the local record; `_cmd_maintain_subscriptions()` (`:435`) delegates to `maintain_graph_subscriptions(client, store, renew_within_hours, extend_hours, dry_run, client_state)` in `plugins/teams_pipeline/subscriptions.py`. Every create/renew/list syncs the record into the store via `_sync_subscription_record()` (`:184`), normalizing through `GraphSubscription.from_dict(...).to_dict()`, setting `status` and stamping `latest_renewal_at` on renewals.
- **Inputs / options:** Documented example resources: `communications/onlineMeetings/getAllTranscripts`, `communications/onlineMeetings/getAllRecordings`; notification URL e.g. `https://ops.example.com/msgraph/webhook`; `--client-state "$MSGRAPH_WEBHOOK_CLIENT_STATE"`.
- **Outputs / side effects:** Real Graph subscriptions plus local records.
- **Config / env:** `MSGRAPH_*`, `MSGRAPH_WEBHOOK_CLIENT_STATE`.
- **Edge cases / guards:** Doc warning verbatim: "Microsoft Graph caps webhook subscriptions at 72 hours and will not auto-renew them. You MUST schedule `hermes teams-pipeline maintain-subscriptions` before going live, or notifications will silently stop three days after any manual subscription creation." Three scheduling options are documented (Hermes cron, systemd timer, plain crontab). Default expiration on `subscribe` is only **1 hour** from now unless `--expiration` is given.
- **Rebuild notes:** Persist every subscription locally and run a renewal job well inside the provider's cap. A better version would auto-register the renewal cron at `subscribe` time.

### Graph webhook listener wiring (`msgraph_webhook`)  `id: platforms-a.teams-pipeline-webhook-config`
- **Surface:** Config (Platform:msgraph_webhook)
- **Where:** `MSGRAPH_WEBHOOK_*` env vars and `platforms.msgraph_webhook` in `config.yaml`; endpoints `/msgraph/webhook` and `/health`.
- **What it does:** Receives the Graph notifications that start pipeline jobs. Documented here because the pipeline cannot run without it; the adapter itself belongs to a sibling shard.
- **How it works:** Documented at `website/docs/user-guide/messaging/teams-meetings.md:70`. The bind host comes from the platform's `extra.host` in `config.yaml` — "there is no `MSGRAPH_WEBHOOK_HOST` env var".
- **Inputs / options:** `MSGRAPH_WEBHOOK_ENABLED=true`, `MSGRAPH_WEBHOOK_PORT=8646`, `MSGRAPH_WEBHOOK_CLIENT_STATE=<random-shared-secret>`, `MSGRAPH_WEBHOOK_ACCEPTED_RESOURCES=communications/onlineMeetings`; YAML `platforms.msgraph_webhook.extra.{host, port, client_state, accepted_resources, allowed_source_cidrs}`.
- **Outputs / side effects:** A local HTTP listener; health check `curl http://localhost:8646/health`.
- **Config / env:** as enumerated.
- **Edge cases / guards:** "If you bind the listener to a non-loopback host such as `0.0.0.0`, you must also set `allowed_source_cidrs` to Microsoft's webhook egress ranges. Loopback binds (`127.0.0.1` / `::1`) are the intended dev-tunnel and local reverse-proxy setup."
- **Rebuild notes:** Validate `clientState` on every notification and restrict source CIDRs on non-loopback binds. Full adapter details are in the sibling `platforms-b` shard (`msgraph_webhook`).

---

## 8. Google Chat

### Google Chat platform adapter  `id: platforms-a.google-chat`
- **Surface:** Platform:google_chat
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Google Chat"** (emoji 💬); runs inside `hermes gateway`. In Google Chat itself: 1:1 DMs and group spaces, with threads.
- **What it does:** Connects Hermes to Google Chat as a Workspace app. Inbound events arrive either over an **authenticated HTTP callback** or a **Cloud Pub/Sub pull subscription** (no public URL needed); outbound messages go through the **Chat REST API** (`chat.googleapis.com`).
- **How it works:** `plugins/platforms/google_chat/adapter.py:625` defines `GoogleChatAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/google_chat/adapter.py:3685` calls `ctx.register_platform(name="google_chat", label="Google Chat", adapter_factory=lambda cfg: GoogleChatAdapter(cfg), check_fn=_check_for_registry, validate_config=_validate_config, is_connected=_is_connected, required_env=["GOOGLE_CHAT_SERVICE_ACCOUNT_JSON"], install_hint="Run `hermes setup` to install Google Chat support.", setup_fn=interactive_setup, env_enablement_fn=_env_enablement, cron_deliver_env_var="GOOGLE_CHAT_HOME_CHANNEL", standalone_sender_fn=_standalone_send, allowed_users_env="GOOGLE_CHAT_ALLOWED_USERS", allow_all_env="GOOGLE_CHAT_ALLOW_ALL_USERS", max_message_length=4000, emoji="💬", allow_update_command=True, platform_hint=…)`. Manifest `plugins/platforms/google_chat/plugin.yaml:1` (`name: google_chat-platform`, `label: Google Chat`, `kind: platform`, `version: 1.0.0`, `author: Ramón Fernández`). Heavy Google imports are deferred — `_load_google_modules()` (`:131`) rebinds the module globals `httplib2`, `pubsub_v1`, `gax_exceptions`, `service_account`, `AuthorizedHttp`, `build_service`, `HttpError`, `MediaFileUpload` on first use, because eager imports "added ~110ms wall and ~33MB RSS to *every* CLI invocation". Concurrency: the Pub/Sub `SubscriberClient` callback runs on a background thread, so `_on_pubsub_message()` (`:1368`) uses `asyncio.run_coroutine_threadsafe` + `add_done_callback` (`_submit_on_loop`, `:891`) and **never** `.result()`, "that would block the callback thread and saturate the Pub/Sub executor under load"; all outbound REST calls go through `asyncio.to_thread` because googleapiclient is synchronous.
- **Inputs / options:** Env — `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON` (required; path or inline JSON; falls back to `GOOGLE_APPLICATION_CREDENTIALS`; leave empty for ADC on Cloud Run/GCE), `GOOGLE_CHAT_HTTP_EVENTS_URL`, `GOOGLE_CHAT_HTTP_EVENTS_AUDIENCE`, `GOOGLE_CHAT_HTTP_EVENTS_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_CHAT_PROJECT_ID` (falls back to `GOOGLE_CLOUD_PROJECT`), `GOOGLE_CHAT_SUBSCRIPTION_NAME` / `GOOGLE_CHAT_SUBSCRIPTION`, `GOOGLE_CHAT_ALLOWED_USERS`, `GOOGLE_CHAT_ALLOW_ALL_USERS`, `GOOGLE_CHAT_HOME_CHANNEL`, `GOOGLE_CHAT_HOME_CHANNEL_NAME`, `GOOGLE_CHAT_MAX_MESSAGES`, `GOOGLE_CHAT_MAX_BYTES`, `GOOGLE_CHAT_BOOTSTRAP_SPACES`, `GOOGLE_CHAT_DEBUG_RAW`, `HERMES_HOME`. Config: `platforms.google_chat.{enabled, typing_status_text, typing_indicator}` and `platforms.google_chat.extra.*`.
- **Outputs / side effects:** Posts, patches and deletes Chat messages; caches the bot's own `users/{id}`; writes a thread-count store and, for the OAuth flow, per-user token files under `~/.hermes/`.
- **Config / env:** as enumerated. Overview table verbatim: **Libraries** `google-cloud-pubsub`, `google-api-python-client`, `google-auth`; **Inbound transport** "Cloud Pub/Sub pull subscription (no public endpoint)"; **Outbound transport** "Chat REST API (`chat.googleapis.com`)"; **Authentication** "Service Account JSON with `roles/pubsub.subscriber` on the subscription"; **User identification** "Chat resource names (`users/{id}`) + email".
- **Edge cases / guards:** Note verbatim: "Google Chat is part of Google Workspace… Gmail-only accounts cannot host Chat apps." Constants: `_MAX_TEXT_LENGTH = 4000` (`:230`, "Google Chat text-message size limit is 4096; leave margin"), `_RATE_LIMIT_WARN_THRESHOLD = 5` (`:233`), `_CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot", "https://www.googleapis.com/auth/pubsub"]` (`:224`), `_SUBSCRIPTION_PATH_RE = ^projects/(?P<project>[^/]+)/subscriptions/(?P<sub>[^/]+)$` (`:209`), `_GCHAT_CHAT_ID_RE = ^(?:spaces|users)/[A-Za-z0-9_-]+$` (`:3530`) — "anything else means a tampered chat_id trying to break out of the REST URL path (path traversal, `?` query injection, `#` fragment truncation)".
- **Rebuild notes:** Minimal spec: a Pub/Sub streaming pull (or an authenticated HTTPS callback) feeding a MESSAGE-only dispatcher, plus `spaces.messages.create/patch/delete` for output, with the reply thread taken from `message.thread.name`. A better version would support Chat's newer `spaces.messages.list` so the agent can read history it did not receive live.

### Google Chat model-facing platform hint  `id: platforms-a.google-chat-platform-hint`
- **Surface:** Core (Platform:google_chat)
- **Where:** Invisible — appended to the agent's system prompt on Google Chat turns.
- **What it does:** Tells the model exactly what Google Chat can and cannot render, and what the adapter does not support, so it stops promising impossible things.
- **How it works:** `platform_hint=` on the registration at `plugins/platforms/google_chat/adapter.py:3728`.
- **Inputs / options:** The full text, verbatim: "You are on Google Chat. Limited markdown subset is rendered: *bold*, _italic_, ~strike~, `code`. No headings or lists. Message size limit: 4000 characters; longer responses are split across multiple messages. You are in a space (DM or group). Images render inline; audio, video, and document attachments render as download cards (no native voice/video UI). To send files, include MEDIA:/absolute/path/to/file in your response. Native file attachments require the user to run /setup-files once in their own DM — until they do, file requests fall back to a text notice with the host path. Do NOT generate interactive Card v2 buttons — Google Chat interactivity is not yet supported by this gateway; ask for typed confirmations instead. While you are generating a response, a 'Hermes is thinking…' marker message appears in the space and is deleted once your response is ready. You do NOT have access to Google Chat-specific APIs — you cannot search space history, list space members, or manage spaces. Do not promise to perform these actions; explain that you can only read messages sent directly to you and respond in the same space/thread."
- **Outputs / side effects:** Prompt text only.
- **Config / env:** n/a.
- **Edge cases / guards:** The hint says the marker is "deleted"; the implementation actually **patches** it in place (`send_typing` docstring at `:2638`) — a small doc/behaviour drift worth noting for a reimplementation.
- **Rebuild notes:** Ship platform limitations as a prompt fragment next to the adapter that enforces them. A better version would generate the hint from the capability declaration so the two cannot drift.

### Google Chat GCP setup (project, APIs, SA, Pub/Sub, IAM)  `id: platforms-a.google-chat-gcp-setup`
- **Surface:** Docs / Platform:google_chat
- **Where:** Google Cloud console and the Google Chat API configuration page.
- **What it does:** The exact server-side steps that make the integration work.
- **How it works:** Documented at `website/docs/user-guide/messaging/google_chat.md:37`.
- **Inputs / options:** Steps verbatim:
  - **Step 1** — create or pick a GCP project; note the project ID (e.g. `my-chat-bot-123`).
  - **Step 2** — **APIs & Services → Library**, enable **Google Chat API** and **Cloud Pub/Sub API**.
  - **Step 3** — **IAM & Admin → Service Accounts → Create Service Account**; name `hermes-chat-bot`; "Skip the 'Grant this service account access to project' step… do **NOT** grant project-level Pub/Sub roles"; then **Keys → Add Key → Create new key → JSON**, saved e.g. at `~/.hermes/google-chat-sa.json`, `chmod 600`.
  - **Step 4** — **Pub/Sub → Topics → Create topic**, Topic ID `hermes-chat-events`; then a **Pull** subscription `hermes-chat-events-sub` with **Message retention: 7 days** "(so backlog survives a hermes restart)".
  - **Step 5** — on the **topic**: principal `chat-api-push@system.gserviceaccount.com`, role `Pub/Sub Publisher`. "Without this, Google Chat cannot publish events to your topic and your bot will never receive anything."
  - **Step 6** — on the **subscription**: your SA as `Pub/Sub Subscriber`, plus `Pub/Sub Viewer` "— Hermes calls `subscription.get()` at startup as a reachability check".
  - **Step 7** — **APIs & Services → Google Chat API → Configuration**: **App name**, **Avatar URL** (any public PNG), **Description**, **Functionality** = enable **Receive 1:1 messages** and **Join spaces and group conversations**, **Connection settings** = **Cloud Pub/Sub** with topic `projects/<your-project>/topics/hermes-chat-events`, **Visibility** restricted to your workspace.
  - **Step 8** — install the bot in a test space; "The first time you message it, Google sends an `ADDED_TO_SPACE` event that Hermes uses to cache the bot's own `users/{id}` for self-message filtering."
- **Outputs / side effects:** A working topic/subscription pair and an SA key.
- **Config / env:** `GOOGLE_CHAT_PROJECT_ID`, `GOOGLE_CHAT_SUBSCRIPTION_NAME`, `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON`.
- **Edge cases / guards:** Dependency install is done through the plugin's own installer: `python -m plugins.platforms.google_chat.oauth --install-deps` — "It applies the same pinned security floors used by the runtime checks."
- **Rebuild notes:** Two IAM bindings (publisher on the topic, subscriber+viewer on the subscription) are the whole trick. A better version would offer a `gcloud` script that performs all six steps.

### Google Chat interactive setup wizard  `id: platforms-a.google-chat-setup`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → select **Google Chat**.
- **What it does:** Prints the GCP walkthrough and collects the project, subscription, SA key, allowlist and home space.
- **How it works:** `interactive_setup()` at `plugins/platforms/google_chat/adapter.py:3434`.
- **Inputs / options:** Verbatim strings in order:
  - `Google Chat: already configured (subscription: <GOOGLE_CHAT_SUBSCRIPTION_NAME>)` + `Reconfigure Google Chat?` (yes/no, default `False`)
  - `Google Chat needs a GCP project, a Pub/Sub topic + subscription,`
  - `and a Service Account with Pub/Sub Subscriber on the subscription.`
  - `Walkthrough:`
  - `  1. Create or select a GCP project; enable Google Chat API + Cloud Pub/Sub API.`
  - `  2. Create a Service Account (no project-level IAM role needed).`
  - `  3. Create a Pub/Sub topic (e.g. hermes-chat-events) and a Pull subscription.`
  - `  4. On the TOPIC: add chat-api-push@system.gserviceaccount.com as Pub/Sub Publisher.`
  - `  5. On the SUBSCRIPTION: grant your Service Account Pub/Sub Subscriber.`
  - `  6. Download the Service Account JSON key.`
  - `  7. Google Chat API console → Configuration: connection = Cloud Pub/Sub,`
  - `     point at the topic, enable 1:1 + group, restrict visibility.`
  - `  8. Install the bot in a space (fires ADDED_TO_SPACE and resolves its user_id).`
  - `Full guide: website/docs/user-guide/messaging/google_chat.md`
  - prompt `GCP project ID (e.g. my-project)` → on empty `Project ID is required — skipping Google Chat setup`
  - prompt `Pub/Sub subscription (projects/<proj>/subscriptions/<sub>)` → on empty `Subscription is required — skipping Google Chat setup`
  - prompt `Path to Service Account JSON (or inline JSON)` (password)
  - `Restrict access to specific users? (recommended)` (yes/no, default `True`) → prompt `Allowed user emails (comma-separated)` → `Allowlist configured`; declining writes `GOOGLE_CHAT_ALLOW_ALL_USERS=true` and warns `⚠️  Open access — anyone who can DM the bot can command it.`
  - prompt `Home space for cron/notification delivery (e.g. spaces/AAAA, or empty)`
  - `Google Chat configuration saved to ~/.hermes/.env`
  - `Restart the gateway: hermes gateway restart`
- **Outputs / side effects:** Writes `GOOGLE_CHAT_PROJECT_ID`, `GOOGLE_CHAT_SUBSCRIPTION_NAME`, `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON`, `GOOGLE_CHAT_ALLOWED_USERS` or `GOOGLE_CHAT_ALLOW_ALL_USERS`, `GOOGLE_CHAT_HOME_CHANNEL`.
- **Config / env:** as above.
- **Edge cases / guards:** Every prompt is pre-filled with the existing env value.
- **Rebuild notes:** Print the console walkthrough, then capture the four identifiers it produces. A better version would verify the subscription with a live `subscription.get()` before saving.

### Google Chat inbound transports (Pub/Sub pull and HTTP events)  `id: platforms-a.google-chat-inbound`
- **Surface:** Config (Platform:google_chat)
- **Where:** Invisible — the two ways events reach Hermes.
- **What it does:** Receives Chat events either by pulling a Cloud Pub/Sub subscription (no public URL) or by accepting Google-signed HTTP callbacks on an authenticated endpoint.
- **How it works:** Pub/Sub: `_on_pubsub_message(message)` at `plugins/platforms/google_chat/adapter.py:1368` parses the envelope, deduplicates, submits the coroutine onto the loop with `_submit_on_loop()` (`:891`, which checks `_loop_accepts_callbacks()` at `:888` and logs failures via `_log_background_failure()` at `:881`) and acks. Flow control is configured from `GOOGLE_CHAT_MAX_MESSAGES` / `GOOGLE_CHAT_MAX_BYTES`. HTTP events: `verify_http_event_request(auth_header)` at `:1522` requires a `Bearer ` prefix, verifies the Google-signed ID token against the configured audience with `_verify_google_id_token()` (`:118`, backed by `_CachedGoogleAuthRequest` at `:81` with a 300-second certs TTL, `_GOOGLE_ID_TOKEN_CERTS_TTL_SECONDS`), then requires the token's `email` claim to be in the comma-separated `GOOGLE_CHAT_HTTP_EVENTS_SERVICE_ACCOUNT_EMAIL` set. Envelope routing: `_extract_message_payload()` (`:1257`) accepts both the Chat shape `{"type": "MESSAGE", "message": {...}, "space": {...}}` and the flat shape `{"event_type": "MESSAGE", "sender_email": "...", "text": "...", ...}`; only `MESSAGE` dispatches to the agent.
- **Inputs / options:** `GOOGLE_CHAT_SUBSCRIPTION_NAME` / `GOOGLE_CHAT_SUBSCRIPTION`, `GOOGLE_CHAT_PROJECT_ID`, `GOOGLE_CHAT_MAX_MESSAGES` ("Pub/Sub FlowControl; 1 serializes commands per session"), `GOOGLE_CHAT_MAX_BYTES` ("16 MiB — cap on in-flight message bytes"), `GOOGLE_CHAT_HTTP_EVENTS_URL`, `GOOGLE_CHAT_HTTP_EVENTS_AUDIENCE` ("Defaults to GOOGLE_CHAT_HTTP_EVENTS_URL"), `GOOGLE_CHAT_HTTP_EVENTS_SERVICE_ACCOUNT_EMAIL`.
- **Outputs / side effects:** Connect log verbatim shape: `[GoogleChat] Connected; project=<id>, subscription=<redacted>, bot_user_id=users/XXXX, flow_control(msgs=1, bytes=16777216)`.
- **Config / env:** as enumerated.
- **Edge cases / guards:** HTTP verification failure reasons, verbatim: `google_chat_http_events_not_configured`, `missing_google_bearer`, `invalid_google_bearer`, `unexpected_google_bearer_identity`; verification failures log `[GoogleChat] HTTP event bearer verification failed: %s` with the message redacted. Pub/Sub is at-least-once, hence the dedup step before dispatch. Repeated `[GoogleChat] Pub/Sub stream died` messages indicate rotated SA credentials or a deleted subscription; "After 10 attempts the adapter marks itself fatal."
- **Rebuild notes:** Verify the ID token's signature **and** its `email` claim against an explicit allowlist; never trust the audience alone. A better version would expose both transports simultaneously with a single dedup ring so a migration needs no downtime.

### Google Chat event-type routing  `id: platforms-a.google-chat-events`
- **Surface:** Core (Platform:google_chat)
- **Where:** Invisible — every inbound envelope.
- **What it does:** Routes the four Chat event types: only `MESSAGE` reaches the agent.
- **How it works:** Module docstring at `plugins/platforms/google_chat/adapter.py:30-35` and the dispatcher at `:1300`/`:1426`. `MESSAGE` → `_dispatch_message`; `ADDED_TO_SPACE` → caches the bot's own resource name ("belt-and-suspenders on top of eager resolution in connect()") and logs `[GoogleChat] ADDED_TO_SPACE %s`; `REMOVED_FROM_SPACE` → logs `[GoogleChat] REMOVED_FROM_SPACE %s`; `CARD_CLICKED` → acked (and used by the clarify card flow). The bot's own id is persisted by `_save_cached_bot_id()` (`:932`) at `_bot_id_cache_path()` (`:917`) and reloaded by `_load_cached_bot_id()` (`:922`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Cached bot id; agent turns for `MESSAGE` only.
- **Config / env:** `GOOGLE_CHAT_BOOTSTRAP_SPACES` seeds known spaces.
- **Edge cases / guards:** Non-`MESSAGE` envelopes are acked so Pub/Sub does not redeliver them forever.
- **Rebuild notes:** Ack everything, dispatch one type. A better version would use `REMOVED_FROM_SPACE` to purge sessions for that space.

### Google Chat working-state marker ("Hermes is thinking…")  `id: platforms-a.google-chat-typing-marker`
- **Surface:** Config (Platform:google_chat)
- **Where:** A **real posted message** in the space reading **"Hermes is thinking…"**, which is then edited in place into the reply.
- **What it does:** Shows that the agent is working, without leaving a "message deleted" tombstone — the marker becomes the answer.
- **How it works:** `send_typing()` at `plugins/platforms/google_chat/adapter.py:2638` posts `{"text": config.typing_status_text or "Hermes is thinking…"}` into the **user's thread** (resolved the same way `send()` does, because `messages.patch` cannot change a message's `thread` — it is immutable on update; creating the marker top-level would strand the whole response outside the user's thread). `send()` then PATCHes that message with the real response; `on_processing_complete` patches it on failure or cancellation. Cancellation safety: `base.py`'s `_keep_typing` wraps this in `asyncio.wait_for(..., timeout=1.5)`, so the create is run as a **background task** awaited with `asyncio.shield` and the slot is reserved by an in-flight `asyncio.Event` (`_typing_card_inflight`) — otherwise a slow create would leave an untracked orphan card in the space forever plus a second card. A concurrent caller waits up to 5 s on that Event. `_TYPING_CONSUMED_SENTINEL = "<consumed>"` (`:294`) is left in `_typing_messages` after the patch so (a) `send_typing` will not create a fresh card in the window before the base class cancels its typing task, and (b) `stop_typing` skips the API delete — "otherwise the safety-net cleanup at base.py:_process_message_background would delete the response we just patched and leave a tombstone".
- **Inputs / options:** `platforms.google_chat.typing_status_text` (default `"Hermes is thinking…"`, doc example `"is pouncing… 🐾"`); `platforms.google_chat.typing_indicator: false` disables the marker entirely.
- **Outputs / side effects:** One real Chat message per turn, patched into the reply.
- **Config / env:** `platforms.google_chat.typing_status_text`, `platforms.google_chat.typing_indicator`.
- **Edge cases / guards:** Doc note verbatim: "Unlike Slack's ephemeral status line, this is a **real posted message** that gets edited in place with the response — so whatever you set here briefly appears in the chat as a normal message."
- **Rebuild notes:** Create the placeholder in the correct thread, reserve the slot before the API call, and patch instead of delete-and-repost. A better version would use Chat's own typing indicator if one ever ships.

### Google Chat formatting & message splitting  `id: platforms-a.google-chat-format`
- **Surface:** Core (Platform:google_chat)
- **Where:** Every reply.
- **What it does:** Converts the agent's markdown into Google Chat's limited subset and splits long responses.
- **How it works:** `format_message()` at `plugins/platforms/google_chat/adapter.py:2405` (classmethod); `_chunk_text()` at `:2364` splits against `_MAX_TEXT_LENGTH = 4000`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Multiple messages when the response exceeds 4 000 characters.
- **Config / env:** n/a.
- **Edge cases / guards:** Capability table verbatim — **Supported**: "`*bold*`, `_italic_`, `~strike~`, `` `code` ``", "Inline images via URL", "Native file attachments (after `/setup-files` — see Step 10)". **Not supported**: "Headings, lists", "Interactive Card v2 buttons (v1 of this gateway)", "Native voice notes / circular video notes".
- **Rebuild notes:** Translate to the four supported inline markers and drop everything else. A better version would render unsupported structures (tables, lists) as monospace blocks rather than dropping the markup.

### Google Chat threads & per-thread sessions  `id: platforms-a.google-chat-threads`
- **Surface:** Core (Platform:google_chat)
- **Where:** Replies inside a Chat thread.
- **What it does:** Detects the user's thread and replies inside it, giving each thread its own Hermes session.
- **How it works:** `_resolve_thread_id(reply_to, metadata, chat_id)` at `plugins/platforms/google_chat/adapter.py:2484` reads `message.thread.name`; the same resolution is used by `send()`, `send_typing()` and the `/setup-files` replies. Space type mapping at `:1836`: `"dm"` when `spaceType` is `DIRECT_MESSAGE` or `DM`, else `"group"`. `_ThreadCountStore` (`:515`) persists a per-`(chat_id, thread_name)` message counter to disk (`load()` `:551`, `get()` `:592`, `incr()` `:596`, `_save()` `:606`), incremented on each outbound message.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Replies carry `{"thread": {"name": <thread>}}`; the thread-count store file is updated.
- **Config / env:** n/a.
- **Edge cases / guards:** Doc statement verbatim: "when a user replies inside a thread, Hermes detects the `thread.name` and posts its reply in the same thread, so each thread gets a separate Hermes session."
- **Rebuild notes:** Thread name in, thread name out — and resolve it once for every send path. A better version would let the operator choose thread-per-turn vs. one thread per space.

### Google Chat clarify cards (Card v2 buttons)  `id: platforms-a.google-chat-clarify-card`
- **Surface:** Platform:google_chat
- **Where:** A native Card v2 headed **"Question"**, body `❓ <question>`, with one button per choice plus **"Other / type answer"**.
- **What it does:** Renders the agent's multiple-choice clarify question as tappable card buttons instead of a numbered text list.
- **How it works:** `send_clarify()` at `plugins/platforms/google_chat/adapter.py:2190`. Each choice becomes `{"text": <label>, "action": "hermes_clarify", "parameters": {"clarify_id": …, "choice": <choice text>}}` with the label clipped to 80 characters (`choice[:77] + "..."` when longer); the final button uses `"choice": "__other__"`. The spec is compiled by `card_spec_to_cards_v2()` (`:475`) with `card_id = f"clarify-{clarify_id}"`, one section containing a `text` widget and a `buttons` widget; `_widget_to_chat()` (`:411`) and `_button_to_chat()` (`:395`) do the conversion, and `_CARD_WIDGET_TYPES` (`:244`) enumerates the supported widget types: `text`, `text_paragraph`, `decorated_text`, `buttons`, `button_list`, `selection`, `selection_input`, `image`, `divider`. On success the pending clarify is recorded in `_clarify_state[clarify_id] = session_key`; `CARD_CLICKED` events route the choice back into the waiting session.
- **Inputs / options:** The choice list; no configuration.
- **Outputs / side effects:** A card message; button clicks resolve the clarify.
- **Config / env:** n/a — "No configuration needed."
- **Edge cases / guards:** Falls back to the base text clarify when there are no choices, when every choice is blank, or when the card send fails. Note the tension with the platform hint, which tells the model **not** to generate Card v2 buttons — cards are adapter-generated only.
- **Rebuild notes:** Build a card spec in a neutral shape and compile it to the vendor format at the edge. A better version would also render approval prompts as cards once general interactivity lands.

### Google Chat `/setup-files` — per-user OAuth for native attachments  `id: platforms-a.google-chat-setup-files`
- **Surface:** Platform:google_chat (in-chat command)
- **Where:** Typed by each user in their **own DM** with the bot: `/setup-files`, `/setup-files start`, `/setup-files revoke`, `/setup-files <CODE_OR_URL>`.
- **What it does:** Grants the bot permission to upload real Chat file attachments **as that user**, because Google Chat's `media.upload` endpoint rejects service-account auth outright.
- **How it works:** Intercepted **before** the agent by `_dispatch_message()` (`plugins/platforms/google_chat/adapter.py:1567`) and handled at `:1596`. The sender's email (lowercased, stripped) is the per-user OAuth key; when absent it falls back to the legacy single-user path. Helper module `plugins/platforms/google_chat/oauth.py` provides `load_user_credentials(email)` (`:186`), `refresh_or_none()` (`:254`), `build_user_chat_service()` (`:287`), `list_authorized_emails()` (`:298`), `store_client_secret(path)` (`:442`), `get_auth_url(email)` (`:518`), `exchange_auth_code(code, email)` (`:545`), `revoke(email)` (`:620`), `check_auth(email)` (`:423`), `install_deps()` (`:397`), with `_REDIRECT_URI = "http://localhost:1"` (`:178`) and email sanitization `_EMAIL_FS_RE = [^a-z0-9._@-]+` (`:114`). Sub-command handlers capture the helper's stdout via `contextlib.redirect_stdout` inside `asyncio.to_thread` so nothing prints to the gateway terminal.
- **Inputs / options:** Four forms, documented in the handler docstring verbatim: `/setup-files` → "show status + next step"; `/setup-files start` → "print OAuth URL"; `/setup-files revoke` → "revoke and delete stored token"; `/setup-files <CODE_OR_URL>` → "exchange auth code for token". Host-side one-time step: `python -m plugins.platforms.google_chat.oauth --client-secret /path/to/client_secret.json` (per profile: `hermes -p <profile> python -m plugins.platforms.google_chat.oauth --client-secret …`); dependency install `python -m plugins.platforms.google_chat.oauth --install-deps`.
- **Outputs / side effects:** In-chat replies, verbatim:
  - authorized — `✅ Native attachment delivery is **active** for `<email or "shared (legacy)">`.\nToken: `<token path>`\nSend `/setup-files revoke` to disable.`
  - no client secret — `🔧 Native attachment delivery is **not configured**.\n**Step 1 (one-time, on the host):** create OAuth client credentials at https://console.cloud.google.com/apis/credentials → *Create credentials* → *OAuth client ID* → *Desktop app*. Download the JSON. Then on the host run:\n```\npython -m plugins.platforms.google_chat.oauth --client-secret /path/to/client_secret.json\n```\n**Step 2:** come back here and send `/setup-files start`.`
  - secret present, not authorized — `🔧 Client credentials are stored but you haven't authorized yet. Send `/setup-files start` to begin.`
  - `start` without a secret — `⚠️ No client credentials stored for this profile. Send `/setup-files` (no args) for setup instructions.`
  - `start` success — `1. Open this URL in your browser and authorize:\n<auth_url>\n\n2. After clicking *Allow*, your browser will fail to load `http://localhost:1/?...&code=...`. That's expected.\n\n3. Copy the entire failed URL from the browser's URL bar and paste it back here as: `/setup-files <PASTE_URL>` (or just the `code=...` value).\n\nTip: the URL contains your access grant — keep it private.`
  - `start` failure — `❌ Couldn't generate the OAuth URL. Check the gateway logs and verify the client_secret.json is valid.` or `❌ Error: <exc>`
  - `revoke` — `✅ Done.\n```\n<output>\n```` or `❌ Error revoking: <exc>`
  - exchange failure — `❌ Token exchange failed. The code may have expired or the URL is malformed. Send `/setup-files start` to get a fresh OAuth URL.` or `❌ Error: <exc>`
  - Logs: `[GoogleChat] /setup-files reply send failed`, `[GoogleChat] /setup-files start failed: %s`, `[GoogleChat] /setup-files revoke failed: %s`, `[GoogleChat] /setup-files exchange failed: %s`.
- **Config / env:** Client secret at `~/.hermes/google_chat_user_client_secret.json` (**profile-scoped, not shared across profiles**); per-user tokens at `~/.hermes/google_chat_user_tokens/<sanitized_email>.json`; legacy single-user token at `~/.hermes/google_chat_user_token.json`.
- **Edge cases / guards:** Exactly **one** scope is requested — `chat.messages.create` — "That covers both `media.upload` and the `messages.create` that references the uploaded `attachmentDataRef`. No Drive, no broader Chat scopes — this is least-privilege on purpose." Revoke is scoped to the caller: "Bob revoking shouldn't break Alice's per-user token nor wipe the shared legacy fallback"; the in-memory caches `_user_creds_by_email` / `_user_chat_api_by_email` are evicted for that key only. A 401/403 from one user's token evicts only that user's cache (`_invalidate_user_creds()` at `:3104`, `_is_app_auth_attachment_error()` at `:2990`). After a successful exchange the credentials are reloaded into the adapter **without a gateway restart**. Auth codes are single-use and short-lived. Tokens are plain JSON — "filesystem permissions are the protection — same model as the SA key file". When no token exists the bot posts a text notice with the host path instead of the file, telling the asker to run `/setup-files` (`:1064`: "Each user runs /setup-files once in their own DM …").
- **Rebuild notes:** Keep the upload identity per-user, key tokens by sanitized email, and make the whole grant flow runnable from inside the chat. A better version would use a real loopback redirect server instead of asking users to paste a failed URL.

### Google Chat attachment download SSRF guard  `id: platforms-a.google-chat-attachment-guard`
- **Surface:** Core (Platform:google_chat)
- **Where:** Invisible — inbound user attachments.
- **What it does:** Refuses to attach the Service Account bearer token to any download URL that is not an HTTPS Google-owned host.
- **How it works:** `_is_google_owned_host(url)` at `plugins/platforms/google_chat/adapter.py:325` checks `scheme == "https"` and the host against `_TRUSTED_ATTACHMENT_HOSTS` (`:313`): `googleapis.com`, `chat.google.com`, `drive.google.com`, `docs.google.com`, `lh3.googleusercontent.com`, `lh4.googleusercontent.com`, `lh5.googleusercontent.com`, `lh6.googleusercontent.com`. Rationale in code: "Anything else gets rejected … to block SSRF scenarios where a crafted event points downloadUri at a non-Google endpoint (e.g. the GCE/GKE metadata service at 169.254.169.254) and the bot's Service Account bearer token would be attached to the outbound request."
- **Inputs / options:** n/a.
- **Outputs / side effects:** Rejection before the HTTP request is made.
- **Config / env:** n/a.
- **Edge cases / guards:** `_mime_for_message_type(mime)` (`:368`) classifies the downloaded media.
- **Rebuild notes:** Check the host **before** building the authorized request. A better version would strip the Authorization header on redirect rather than only validating the initial URL.

### Google Chat outbound retry & rate-limit handling  `id: platforms-a.google-chat-retry`
- **Surface:** Core (Platform:google_chat)
- **Where:** Invisible — every outbound Chat REST call.
- **What it does:** Retries transient failures with bounded exponential backoff and warns when a space is repeatedly rate-limited.
- **How it works:** Constants at `plugins/platforms/google_chat/adapter.py:239`: `_RETRY_MAX_ATTEMPTS = 3`, `_RETRY_BASE_DELAY = 1.0`, `_RETRY_MAX_DELAY = 8.0`, `_RETRY_JITTER = 0.3`, `_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}`. `_is_retryable_error(exc)` (`:257`) reads `exc.resp.status` when present; otherwise it falls back to text heuristics — retry on `"timeout"`/`"timed out"`, on `"connection"` combined with `"reset"`/`"refused"`/`"aborted"`, and on `"broken pipe"`/`"remote disconnected"`. "Authentication errors (401/403), client errors (4xx other than 429), and well-formed non-retryable failures are NOT retried — those indicate a misconfiguration or revoked token, not a hiccup." Rate-limit hits per space are counted against `_RATE_LIMIT_WARN_THRESHOLD = 5`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Retries and warning logs.
- **Config / env:** n/a.
- **Edge cases / guards:** Doc note verbatim: "The Chat API's default quotas allow 60 messages per space per minute… the adapter retries with exponential backoff — but you'll still see user-visible latency."
- **Rebuild notes:** Classify by HTTP status first, text second, and never retry auth failures. A better version would honour `Retry-After` when Google sends it.

### Google Chat log redaction & debug envelope dump  `id: platforms-a.google-chat-redaction`
- **Surface:** Env (Platform:google_chat)
- **Where:** Gateway logs.
- **What it does:** Strips service-account emails, subscription paths and topic paths from log output, and lets an operator dump raw envelopes at DEBUG through the same filter.
- **How it works:** `_redact_sensitive(text)` at `plugins/platforms/google_chat/adapter.py:341`; the docs note the redaction is shared with `agent/redact.py`. `GOOGLE_CHAT_DEBUG_RAW=1` enables the envelope dump, "routes through the same redaction filter and logs at DEBUG level".
- **Inputs / options:** `GOOGLE_CHAT_DEBUG_RAW`.
- **Outputs / side effects:** Redacted log lines; the connect line prints `subscription=<redacted>`.
- **Config / env:** `GOOGLE_CHAT_DEBUG_RAW`.
- **Edge cases / guards:** Redaction also applies to bearer-verification error messages.
- **Rebuild notes:** Route every log through one redactor, including the debug dump. A better version would redact by structured field rather than regex over rendered text.

### Google Chat home space, cron delivery & standalone sender  `id: platforms-a.google-chat-home-standalone`
- **Surface:** Config / Core (Platform:google_chat)
- **Where:** `GOOGLE_CHAT_HOME_CHANNEL` (e.g. `spaces/AAAA…`), `GOOGLE_CHAT_HOME_CHANNEL_NAME`.
- **What it does:** Names the default space for cron output and notifications, and delivers there even when cron runs in a separate process.
- **How it works:** `cron_deliver_env_var="GOOGLE_CHAT_HOME_CHANNEL"` and `standalone_sender_fn=_standalone_send` on the registration (`plugins/platforms/google_chat/adapter.py:3714`/`:3719`); `_env_enablement()` (`:3381`) seeds `PlatformConfig.extra` + `home_channel` from env so an env-only setup shows in `gateway status` and `get_connected_platforms()`.
- **Inputs / options:** A `spaces/<id>` or `users/<id>` resource name.
- **Outputs / side effects:** Cron/notification messages posted through the Chat REST API.
- **Config / env:** `GOOGLE_CHAT_HOME_CHANNEL`, `GOOGLE_CHAT_HOME_CHANNEL_NAME`, `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON`.
- **Edge cases / guards:** Every chat id is validated against `_GCHAT_CHAT_ID_RE` before it is interpolated into a REST path.
- **Rebuild notes:** Validate the resource name, then POST `spaces/<id>/messages`. A better version would resolve a human-readable space name to its resource id at save time.

### Google Chat troubleshooting matrix  `id: platforms-a.google-chat-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/google_chat.md:326`.
- **What it does:** Maps each observed Google Chat failure to its cause and fix.
- **How it works:** Static documentation matching the adapter's failure modes.
- **Inputs / options:** Entries verbatim:
  - "**Bot stays silent after sending \"hola.\"**" → "1. Check the Pub/Sub subscription has undelivered messages in the console. If it does, Hermes isn't authenticated — verify `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON` and that the SA is listed as `Pub/Sub Subscriber` on the subscription. 2. If the subscription has zero messages, Google Chat isn't publishing. Double-check the IAM binding on the **topic**: `chat-api-push@system.gserviceaccount.com` must have `Pub/Sub Publisher`. 3. Check `hermes gateway` logs for `[GoogleChat] Connected`. If you see `[GoogleChat] Config validation failed`, the error message tells you which env var to fix."
  - "**Bot replies but an error message appears instead of the agent's answer.**" → "Check logs for `[GoogleChat] Pub/Sub stream died` — if these repeat, your SA credentials may have been rotated or the subscription deleted. After 10 attempts the adapter marks itself fatal."
  - "**\"403 Forbidden\" on every outbound message.**" → "The bot was removed from the space, or you revoked it in the Chat API console. Re-install it in the space (the next `ADDED_TO_SPACE` event will re-enable messaging automatically)."
  - "**Too many \"Rate limit hit\" warnings.**" → the 60-messages-per-space-per-minute quota; "Consider concise responses or raising the quota in the GCP console."
  - "**Bot keeps posting the \"/setup-files\" notice instead of files.**" → "The asker has no per-user OAuth token and there's no legacy fallback… After the exchange completes the next file request uploads natively without a gateway restart."
  - "**`/setup-files start` says \"No client credentials stored.\"**" → "The one-time setup wasn't done *for this profile* (the client secret is profile-scoped…)".
  - "**`/setup-files <PASTED_URL>` says \"Token exchange failed.\"**" → "The auth code is single-use and short-lived (typically a few minutes). Send `/setup-files start` to get a fresh URL and retry."
- **Outputs / side effects:** n/a.
- **Config / env:** all Google Chat keys.
- **Edge cases / guards:** Security notes verbatim: "**Service Account scope**: the adapter requests `chat.bot` and `pubsub` scopes. IAM should be the actual enforcement — grant your SA the minimum (`roles/pubsub.subscriber` + `roles/pubsub.viewer` on the subscription), not project-level or org-level Pub/Sub roles."; "**Attachment download protection**"; "**Redaction**"; "**Compliance**: if you plan to connect this bot to a regulated workspace (anything with a data-residency or AI-governance policy), get that approval before the first install."; "**User OAuth scope**".
- **Rebuild notes:** Turn each row into a startup or runtime check. A better version would surface Pub/Sub backlog depth in `hermes gateway status`.

---

## 9. Email (IMAP/SMTP)

### Email platform adapter  `id: platforms-a.email`
- **Surface:** Platform:email
- **Where:** Enabled by `hermes gateway setup` → platform list entry **"Email"** (emoji 📧); runs inside `hermes gateway`. For the user: send an email to the agent's address and it replies in-thread — no special client or bot API needed.
- **What it does:** Polls an IMAP mailbox for unseen messages, turns each into an agent turn, and replies over SMTP with correct threading headers and optional file attachments.
- **How it works:** `plugins/platforms/email/adapter.py:529` defines `EmailAdapter(BasePlatformAdapter)`; `register(ctx)` at `plugins/platforms/email/adapter.py:1494` calls `ctx.register_platform(name="email", label="Email", adapter_factory=_build_adapter, check_fn=check_email_requirements, is_connected=_is_connected, required_env=["EMAIL_ADDRESS","EMAIL_PASSWORD","EMAIL_SMTP_HOST"], install_hint="Email uses the Python stdlib (smtplib/imaplib) — no extra deps", allowed_users_env="EMAIL_ALLOWED_USERS", allow_all_env="EMAIL_ALLOW_ALL_USERS", cron_deliver_env_var="EMAIL_HOME_ADDRESS", standalone_sender_fn=_standalone_send, max_message_length=50_000, pii_safe=True, emoji="📧", allow_update_command=True)`. Note there is **no `setup_fn`** — the interactive wizard for Email lives in the core setup flow, unlike the other adapters in this shard. Manifest `plugins/platforms/email/plugin.yaml:1` (`name: email-platform`, `label: Email`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`). `MAX_MESSAGE_LENGTH = 50_000` (`:110`, "Gmail-safe max length per email body"), `SMTP_CONNECT_TIMEOUT = 30` (`:112`). Credentials are read scope-aware through `_get_esecret()` (`:55`, aliased `_get_secret`), `_esecret_int()` (`:78`) and `_esecret_bool()` (`:89`). `connect()` (`:672`) validates the four required settings, tests IMAP and SMTP, marks existing inbox messages seen, then starts `_poll_loop()` (`:815`).
- **Inputs / options:** Complete env table verbatim (Variable | Required | Default | Description): `EMAIL_ADDRESS` | Yes | — | "Agent's email address"; `EMAIL_PASSWORD` | Yes | — | "Email password or app password"; `EMAIL_IMAP_HOST` | Yes | — | "IMAP server host (e.g., `imap.gmail.com`)"; `EMAIL_SMTP_HOST` | Yes | — | "SMTP server host (e.g., `smtp.gmail.com`)"; `EMAIL_IMAP_PORT` | No | `993` | "IMAP server port"; `EMAIL_SMTP_PORT` | No | `587` | "SMTP server port"; `EMAIL_POLL_INTERVAL` | No | `15` | "Seconds between inbox checks"; `EMAIL_ALLOWED_USERS` | No | — | "Comma-separated allowed sender addresses"; `EMAIL_HOME_ADDRESS` | No | — | "Default delivery target for cron jobs"; `EMAIL_ALLOW_ALL_USERS` | No | `false` | "Allow all senders (not recommended)". Also read: `EMAIL_TRUST_FROM_HEADER`, `EMAIL_AUTHSERV_ID`, `GATEWAY_ALLOWED_USERS`, `GATEWAY_ALLOW_ALL_USERS`. Config: `platforms.email.extra.{address, imap_host, smtp_host, skip_attachments, require_authenticated_sender, authserv_id}`, `platforms.email.unauthorized_dm_behavior`.
- **Outputs / side effects:** Outgoing SMTP mail; attachments cached locally; no persistent local state beyond the in-process seen-UID set and snapshot.
- **Config / env:** as enumerated. `pii_safe=True` is declared on the registration.
- **Edge cases / guards:** Startup sequence documented verbatim: "1. Tests IMAP and SMTP connections 2. Marks all existing inbox messages as 'seen' (only processes new emails) 3. Starts polling for new messages". Missing configuration produces the **non-retryable** fatal error `email_missing_configuration` with the message `Not configured — missing <names>. Set it via `hermes gateway setup` (env) or platforms.email in config.yaml.` — deliberately non-retryable because "A blank-but-present env var (e.g. `EMAIL_IMAP_HOST=`) used to slip past the startup gate and drive an indefinite retry loop that leaked memory until the host OOM-killed". `check_email_requirements()` (`:228`) treats blank/whitespace-only values as missing.
- **Rebuild notes:** Minimal spec: `IMAP4_SSL` + `UID SEARCH UNSEEN` on a timer, one `MessageEvent` per message, `smtplib` reply with `In-Reply-To`/`References`. A better version would use IMAP IDLE instead of polling and would keep the seen-UID watermark on disk.

### Email provider setup (Gmail / Outlook / other)  `id: platforms-a.email-provider-setup`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/email.md:26`.
- **What it does:** The provider-side steps needed before Hermes can log in.
- **How it works:** Static documentation.
- **Inputs / options:** Prerequisites verbatim: "**A dedicated email account** for your Hermes agent (don't use your personal email)"; "**IMAP enabled** on the email account"; "**An app password** if using Gmail or another provider with 2FA". **Gmail Setup**: "1. Enable 2-Factor Authentication on your Google Account 2. Go to [App Passwords](https://myaccount.google.com/apppasswords) 3. Create a new App Password (select \"Mail\" or \"Other\") 4. Copy the 16-character password — you'll use this instead of your regular password". **Outlook / Microsoft 365**: "1. Go to [Security Settings](https://account.microsoft.com/security) 2. Enable 2FA if not already active 3. Create an App Password under \"Additional security options\" 4. IMAP host: `outlook.office365.com`, SMTP host: `smtp.office365.com`". **Other Providers**: check for "IMAP host and port (usually port 993 with SSL)", "SMTP host and port (usually port 587 with STARTTLS)", "Whether app passwords are required".
- **Outputs / side effects:** n/a.
- **Config / env:** `EMAIL_*`.
- **Edge cases / guards:** Info box verbatim: "This page covers the Email gateway adapter, which uses Python's built-in `imaplib`, `smtplib`, and `email` modules. No additional packages or external services are required for this gateway path." The adapter is explicitly distinct from the bundled **Himalaya email skill**: the gateway adapter is for "Let people email the Hermes agent and receive replies" with "None beyond an IMAP/SMTP email account"; the skill is for "Let the agent inspect, compose, move, and manage mailbox messages from terminal tools" and needs the "`himalaya` CLI and `~/.config/himalaya/config.toml`".
- **Rebuild notes:** Document app passwords prominently — they are the single most common setup failure. A better version would support OAuth (XOAUTH2) for Gmail/Microsoft instead of app passwords.

### Email IMAP polling & seen-UID tracking  `id: platforms-a.email-polling`
- **Surface:** Core (Platform:email)
- **Where:** Invisible — the inbox poll loop.
- **What it does:** Fetches unseen messages on an interval, tracks which UIDs it has already processed, and escalates a genuinely failed check instead of treating it as "nothing new".
- **How it works:** `_poll_loop()` at `plugins/platforms/email/adapter.py:815` calls `_check_inbox()` (`:826`) every `EMAIL_POLL_INTERVAL` seconds. `_check_inbox` runs `_fetch_new_messages()` (`:853`) in an executor thread, dispatches whatever came back **before** escalating any failure ("on a mid-batch exception `_fetch_new_messages` returns the partial results, and dropping them here would lose those messages"), then — if `_last_fetch_failed` — raises the **retryable** fatal error `email_imap_fetch_failed` and calls `_notify_fatal_error()` so the gateway's reconnect/backoff/status machinery re-establishes the mailbox. `_fetch_new_messages` opens `IMAP4_SSL(host, port, timeout=30)`, logs in, sends the RFC 2971 `ID` command, selects `INBOX`, runs `UID SEARCH UNSEEN`, and fetches each UID with `(RFC822)`. UID bookkeeping: `_seen_uids` (a set), capped at `_seen_uids_max = 2000` and halved by `_trim_seen_uids()` (`:610`) keeping the numerically highest half ("IMAP UIDs are monotonically increasing integers… old UIDs are safe to drop because new messages always have higher UIDs and IMAP's UNSEEN flag prevents re-delivery regardless"). A class-level `_seen_uids_snapshot: Dict[str, set]` (`:539`) keyed by account address survives adapter recreation, because "The gateway's reconnect watcher builds a FRESH adapter instance for each retry; without this, `connect(is_reconnect=True)` would re-mark the entire mailbox seen and silently skip every message that arrived during the outage" — same-process only by design.
- **Inputs / options:** `EMAIL_POLL_INTERVAL` (default `15`).
- **Outputs / side effects:** Log lines verbatim: `[Email] IMAP fetch error: %s`, `[Email] Poll error: %s`, `[Email] Unexpected IMAP response structure for UID %s, skipping`, `[Email] Non-bytes IMAP payload for UID %s, skipping`, `[Email] Failed to process message UID %s, skipping: %s`, `[Email] Trimmed seen UIDs to %d entries`, `[Email] New message from %s: %s`, `[Email] Adapter initialized for %s`, `[Email] Connected as <address>`, `[Email] Disconnected.`
- **Config / env:** `EMAIL_POLL_INTERVAL`, `EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`.
- **Edge cases / guards:** A UID is marked seen **after** a response arrives but **before** parsing, so a garbage response is skipped once rather than retried forever, while a connection failure leaves the rest of the batch eligible for the next poll. A per-message try/except means "one poison message (unparseable headers, pathological attachment, DNS hiccup in SPF/DKIM verification) must not abort the batch or escalate to a reconnect". `_close_imap()` (`:115`) guarantees the socket dies even when `logout()` raises `IMAP4.abort` — which is **not** an `OSError`, so `imaplib`'s own guard does not catch it. `_send_imap_id()` (`:194`) sends `ID ("name" "hermes-agent" "version" "<ver>" "vendor" "NousResearch" "support-email" "noreply@nousresearch.com")` because "163/NetEase mailbox after LOGIN: without it, every UID SEARCH/FETCH returns `BYE Unsafe Login` and disconnects"; failures are swallowed with `[Email] IMAP ID command not accepted: %s`.
- **Rebuild notes:** Mark seen after the fetch, guard each message, and keep a cross-instance snapshot for reconnects. A better version would persist the watermark so a process restart does not re-baseline the mailbox.

### Email sender authentication (SPF/DKIM/DMARC)  `id: platforms-a.email-sender-auth`
- **Surface:** Config (Platform:email)
- **Where:** Invisible — every inbound message when an allowlist is in effect.
- **What it does:** Refuses to trust the `From:` header for authorization unless the receiving mail server's `Authentication-Results` proves the From domain is authenticated — closing the spoofing hole GHSA-rxqh-5572-8m77.
- **How it works:** `_verify_sender_authentication(msg, from_addr, *, authserv_id="")` at `plugins/platforms/email/adapter.py:389`. Rationale verbatim: "The `From:` header is attacker-controlled and is never authenticated by IMAP delivery, so an allowlist keyed on `From:` alone is trivially spoofable… The only trustworthy signal is the `Authentication-Results` header that the *receiving* mail server (the one we IMAP into) stamps after running SPF/DKIM/DMARC. That header is prepended by our own server, so the topmost instance is the one we trust; any `Authentication-Results` an attacker injected into the body of their message sorts below it." Only the **first** `Authentication-Results` header is used, and when `authserv_id` is configured the header must come from that authserv-id (matched with `_domains_aligned`). Parsers: `_AUTH_METHOD_RE = \b(dmarc|dkim|spf)\s*=\s*([a-z]+)` (`:378`), `_AUTH_PROP_RE = \b(header\.from|header\.d|smtp\.mailfrom|smtp\.from|envelope-from)\s*=\s*([^\s;]+)` (`:383`). Alignment uses `_domains_aligned()` (`:359`) — relaxed DMARC alignment, "exact equality or that one domain is a dot-suffix of the other". Three accept paths, in order: `dmarc=pass` (returns reason `dmarc=pass`), `spf=pass` with the envelope domain aligned (`spf=pass aligned`), `dkim=pass` with `header.d` aligned (`dkim=pass aligned`). Enforcement in `_dispatch_message()` (`:1057`) applies **only** when `require_authenticated_sender` is on **and** an allowlist is in effect **and** allow-all is off — because "if no allowlist is configured the gateway default-denies everyone anyway, and if allow-all is on the operator already accepts any sender".
- **Inputs / options:** `platforms.email.require_authenticated_sender` (default **`true`**, fail-closed) or the env mirror `EMAIL_TRUST_FROM_HEADER=true` (which sets it to `false`); `platforms.email.authserv_id` / `EMAIL_AUTHSERV_ID` (defaults to the From-domain of the agent's own address).
- **Outputs / side effects:** Rejected messages log the full guidance verbatim: `[Email] Dropping sender with unauthenticated From: %s (%s). If your mail server does not stamp Authentication-Results, set platforms.email.require_authenticated_sender: false (or EMAIL_TRUST_FROM_HEADER=true) to accept the risk.`
- **Config / env:** `platforms.email.require_authenticated_sender`, `EMAIL_TRUST_FROM_HEADER`, `platforms.email.authserv_id`, `EMAIL_AUTHSERV_ID`.
- **Edge cases / guards:** Failure reasons returned verbatim: `missing From domain`, `no Authentication-Results header` (fail-closed), `no Authentication-Results from trusted authserv-id`, `authentication failed (<first 120 chars of the header>)`. `_allow_all_senders()` (`:988`) and `_allowlist_in_effect()` (`:1003`) resolve both the per-platform and the global (`GATEWAY_*`) flags.
- **Rebuild notes:** Trust only the topmost `Authentication-Results` from your own server, pin it to an authserv-id, and fail closed when it is absent. A better version would verify DKIM signatures locally rather than trusting the receiving server's stamp.

### Email automated-sender suppression  `id: platforms-a.email-automated-senders`
- **Surface:** Core (Platform:email)
- **Where:** Invisible — every inbound message, checked twice (at parse and at dispatch).
- **What it does:** Silently ignores mail from noreply/bulk/automated sources so the agent never gets into a mail loop with a mailer-daemon.
- **How it works:** `_is_automated_sender(address, headers)` at `plugins/platforms/email/adapter.py:217`, called from `_parse_fetched_message()` and again from `_dispatch_message()`.
- **Inputs / options:** Address patterns `_NOREPLY_PATTERNS` (`:95`), verbatim and complete: `noreply`, `no-reply`, `no_reply`, `donotreply`, `do-not-reply`, `mailer-daemon`, `postmaster`, `bounce`, `notifications@`, `automated@`, `auto-confirm`, `auto-reply`, `automailer` — matched as substrings of the lowercased address. Header rules `_AUTOMATED_HEADERS` (`:102`): `Auto-Submitted` (any value other than `no`), `Precedence` (`bulk`, `list` or `junk`), `X-Auto-Response-Suppress` (any value), `List-Unsubscribe` (any value).
- **Outputs / side effects:** Debug logs `[Email] Skipping automated sender: %s` and `[Email] Dropping automated sender at dispatch: %s`.
- **Config / env:** n/a — not configurable.
- **Edge cases / guards:** Self-messages (`sender_addr == self._address.lower()`) are dropped separately "to prevent reply loops".
- **Rebuild notes:** Check both the address and the RFC headers, and check again at dispatch. A better version would let operators add their own patterns and would honour `Return-Path: <>`.

### Email access control & allowlist  `id: platforms-a.email-access-control`
- **Surface:** Config (Platform:email)
- **Where:** `EMAIL_ALLOWED_USERS` in `~/.hermes/.env`.
- **What it does:** Decides which senders the agent will answer — stricter by default than the chat platforms.
- **How it works:** Enforced early in `_dispatch_message()` (`plugins/platforms/email/adapter.py:1033`) so the adapter never builds a `MessageEvent` (and thus thread context) for a sender the gateway will refuse — "Without this early guard, a race between dispatch and authorization can result in the adapter sending a reply even though the handler returned None."
- **Inputs / options:** Four documented behaviours, verbatim: "1. **`EMAIL_ALLOWED_USERS` set** → only emails from those addresses are processed 2. **No allowlist set** → unknown senders are ignored silently 3. **`EMAIL_ALLOW_ALL_USERS=true`** → any sender is accepted (use with caution) 4. **`platforms.email.unauthorized_dm_behavior: pair`** → unknown senders receive a pairing code". Also honoured: `GATEWAY_ALLOWED_USERS` / `GATEWAY_ALLOW_ALL_USERS`; truthy values are `true`, `1`, `yes`.
- **Outputs / side effects:** Debug logs `[Email] Dropping sender at dispatch — EMAIL_ALLOWED_USERS is unset and open access is not opted in: %s` and `[Email] Dropping non-allowlisted sender at dispatch: %s`.
- **Config / env:** `EMAIL_ALLOWED_USERS`, `EMAIL_ALLOW_ALL_USERS`, `GATEWAY_ALLOWED_USERS`, `GATEWAY_ALLOW_ALL_USERS`, `platforms.email.unauthorized_dm_behavior`.
- **Edge cases / guards:** Warning verbatim: "**Use a dedicated inbox and configure `EMAIL_ALLOWED_USERS` for normal operation.** Email pairing is opt-in because shared inboxes often contain unrelated unread messages, and Hermes should not reply to those contacts by default."
- **Rebuild notes:** Reject before constructing any per-sender state. A better version would support domain wildcards (`*@company.com`).

### Email body extraction & HTML stripping  `id: platforms-a.email-body`
- **Surface:** Core (Platform:email)
- **Where:** Invisible — turning the MIME message into turn text.
- **What it does:** Pulls the plain-text body out of any MIME structure, decodes headers, and strips HTML when there is no text part.
- **How it works:** `_extract_text_body(msg)` at `plugins/platforms/email/adapter.py:296`; `_strip_html(html)` at `:331`; `_decode_header_value(raw)` at `:277` (RFC 2047); `_safe_decode(payload, charset)` at `:257` using `_CHARSET_ALIASES` (`:241`); `_extract_email_address(raw)` at `:345`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The turn text. The subject is prefixed as `[Subject: <subject>]\n\n<body>` unless the subject already starts with `Re:` — "**Reply emails** (subject starting with `Re:`) skip the subject prefix — the thread context is already established". An empty body becomes the literal `(empty email)`.
- **Config / env:** n/a.
- **Edge cases / guards:** "**HTML-only emails** have tags stripped for plain text extraction." Charset aliases handle mislabelled encodings.
- **Rebuild notes:** Prefer `text/plain`, fall back to stripped `text/html`, and decode RFC 2047 headers everywhere. A better version would preserve list/link structure when converting HTML.

### Email attachment ingestion  `id: platforms-a.email-attachments-in`
- **Surface:** Config (Platform:email)
- **Where:** Files attached to an inbound email.
- **What it does:** Caches inbound attachments locally so the vision tool and file tools can use them, or skips them entirely for malware/bandwidth reasons.
- **How it works:** `_extract_attachments(msg, skip_attachments=False)` at `plugins/platforms/email/adapter.py:469`. Walks the MIME parts, keeping only parts whose `Content-Disposition` contains `attachment` or `inline`, and skipping `text/plain` / `text/html` body parts that are not explicit attachments. The filename comes from `get_filename()` (RFC 2047-decoded) or `attachment.<subtype>`. Images — extension in `_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}` (`:192`) — go through `cache_image_from_bytes(payload, ext)`, which validates magic bytes; everything else goes through `cache_document_from_bytes(payload, filename)`. Each entry is `{"path", "filename", "type": "image"|"document", "media_type": <content type>}`.
- **Inputs / options:** `platforms.email.skip_attachments: true` — "When enabled, attachment and inline parts are skipped before payload decoding. The email body text is still processed normally."
- **Outputs / side effects:** Cached files; the message type is set to `PHOTO` for images and `DOCUMENT` for documents.
- **Config / env:** `platforms.email.skip_attachments` (default `false`).
- **Edge cases / guards:** An image whose bytes fail the magic-byte check is skipped with the debug log `Skipping non-image attachment %s (invalid magic bytes)`. For **mixed** attachments `DOCUMENT` wins over `PHOTO`, because "run.py's image handling keys off the per-path image/* mime type regardless of message_type, but document-context injection gates strictly on MessageType.DOCUMENT — so DOCUMENT is the only classification that surfaces both". Parts with an empty decoded payload are skipped.
- **Rebuild notes:** Validate image bytes, not just extensions, and pick the message type that surfaces every attachment kind. A better version would enforce a per-message total attachment size cap.

### Email reply threading  `id: platforms-a.email-threading`
- **Surface:** Core (Platform:email)
- **Where:** Every outgoing reply.
- **What it does:** Keeps the reply in the same mail thread, with a correct subject and standard threading headers.
- **How it works:** `_send_email(to_addr, body, reply_to_msg_id)` at `plugins/platforms/email/adapter.py:1160`, run in an executor thread from `send()` (`:1136`). Per-recipient thread context is stored in `_thread_context[sender_addr] = {"subject", "message_id"}` at dispatch time. Headers set: `From`, `To`, `Subject` (`Re: <subject>`, added only when it does not already start with `Re:` — no double `Re: Re:`), `In-Reply-To` and `References` (both set to the original Message-ID), `Date` (`formatdate(localtime=True)`), and a generated `Message-ID` of the form `<hermes-<12 hex chars>@<domain>>` where the domain comes from `_message_id_domain()` (`:1150`, falling back to `localhost` when `EMAIL_ADDRESS` lacks an `@`). Body is attached as `MIMEText(body, "plain", "utf-8")`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One SMTP message; log `[Email] Sent reply to %s (subject: %s)`; send failures log `[Email] Send failed to %s: %s` and return `SendResult(success=False, error=…)`. Default subject when there is no context: `Hermes Agent` → sent as `Re: Hermes Agent`.
- **Config / env:** n/a.
- **Edge cases / guards:** Documented caveat: "The adapter uses In-Reply-To headers. Some email clients (especially web-based) may not thread correctly with automated messages."
- **Rebuild notes:** Store subject + Message-ID per correspondent and reuse them on reply. A better version would accumulate the full `References` chain instead of only the immediate parent.

### Email SMTP connection & IPv4 fallback  `id: platforms-a.email-smtp`
- **Surface:** Core (Platform:email)
- **Where:** Invisible — every outgoing message.
- **What it does:** Establishes an encrypted SMTP connection with the right protocol for the port, retrying over IPv4 when an unreachable IPv6 address would otherwise hang until the timeout.
- **How it works:** `_connect_smtp()` at `plugins/platforms/email/adapter.py:630`. Port **465** uses implicit TLS (`SMTP_SSL`); every other port uses `SMTP` + `STARTTLS`, both with `ssl.create_default_context()` and `timeout=SMTP_CONNECT_TIMEOUT` (30 s). On `socket.timeout` / `TimeoutError` / `ConnectionError` / `OSError` — but **not** `ssl.SSLError`, which is re-raised — it retries through `_IPv4SMTP` (`:168`) / `_IPv4SMTP_SSL` (`:178`), whose `_get_socket` uses `_create_ipv4_connection()` (`:137`). That helper "mirrors `socket.create_connection` but constrains DNS resolution to `AF_INET`. It avoids mutating process-global socket functions, which matters because email sends run in executor threads." With no IPv4 address it raises `OSError(f"No IPv4 address found for {host}:{port}")`.
- **Inputs / options:** `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT` (default `587`).
- **Outputs / side effects:** A connected, TLS-established SMTP object ready for `login()`.
- **Config / env:** `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`.
- **Edge cases / guards:** TLS verification errors are never retried. SMTP failures at connect set the **retryable** fatal error `email_smtp_connect_error` with `SMTP connection to <host> failed: <e>`.
- **Rebuild notes:** Subclass the SMTP client to override socket creation rather than monkey-patching `socket.create_connection` — thread safety depends on it. A better version would try both families concurrently (Happy Eyeballs) instead of serially.

### Email outbound attachments  `id: platforms-a.email-attachments-out`
- **Surface:** Platform:email
- **Where:** Agent replies containing `MEDIA:/path/to/file`.
- **What it does:** Attaches agent-produced files to the outgoing email.
- **How it works:** `_send_email_with_attachment()` at `plugins/platforms/email/adapter.py:1354` (single) and `_send_email_with_attachments()` at `:1275` (multiple), both building a `MIMEMultipart` with `MIMEBase` parts encoded via `email.encoders`. `send_multiple_images()` (`:1221`) attaches `file://` images directly (URL-decoding the path with `urllib.parse.unquote`) and appends remote URLs to the body as `Image: <url>` instead, matching `send_image()` (`:1204`) which appends `\n\nImage: <url>` to the caption. There is "No hard cap — email clients handle dozens of attachments fine, subject to SMTP message size limits."
- **Inputs / options:** `MEDIA:/absolute/path/to/file` lines in the agent's response.
- **Outputs / side effects:** A multipart email. Missing local files log `[Email] Skipping missing image: %s`; a failed multi-image send logs `[Email] Multi-image send failed, falling back: %s` and delegates to the base implementation.
- **Config / env:** n/a.
- **Edge cases / guards:** The email adapter never downloads remote images — it links them.
- **Rebuild notes:** Attach local files, link remote ones, and always keep a fallback path. A better version would inline images with `cid:` references so they render in the body.

### Email typing indicator (no-op)  `id: platforms-a.email-typing`
- **Surface:** Core (Platform:email)
- **Where:** n/a — nothing is shown.
- **What it does:** Nothing; email has no typing indicator.
- **How it works:** `send_typing()` at `plugins/platforms/email/adapter.py:1202` — an empty coroutine with the docstring "Email has no typing indicator — no-op."
- **Inputs / options:** n/a.
- **Outputs / side effects:** None.
- **Config / env:** n/a.
- **Edge cases / guards:** Implemented explicitly so the base class's typing timer has a valid target.
- **Rebuild notes:** Always implement the optional hooks as no-ops rather than leaving them unimplemented. A better version would send an auto-acknowledgement mail for long-running turns.

### Email home address & standalone sender  `id: platforms-a.email-home-standalone`
- **Surface:** Config / Core (Platform:email)
- **Where:** `EMAIL_HOME_ADDRESS` in `~/.hermes/.env`.
- **What it does:** Names the default recipient for cron output and notifications, and delivers there even when cron runs outside the gateway process.
- **How it works:** `cron_deliver_env_var="EMAIL_HOME_ADDRESS"` and `standalone_sender_fn=_standalone_send` (`plugins/platforms/email/adapter.py:1429`) on the registration.
- **Inputs / options:** A single email address.
- **Outputs / side effects:** Cron results emailed to that address.
- **Config / env:** `EMAIL_HOME_ADDRESS`, plus the SMTP credentials.
- **Edge cases / guards:** Uses the same SMTP path (and therefore the same TLS/IPv4 behaviour) as the adapter.
- **Rebuild notes:** One env var + a stdlib SMTP send. A better version would batch multiple cron results into one digest mail.

### Email troubleshooting matrix  `id: platforms-a.email-troubleshooting`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/email.md:169`.
- **What it does:** Maps each observed email failure to its fix.
- **How it works:** Static documentation.
- **Inputs / options:** Rows verbatim (Problem → Solution):
  - "**\"IMAP connection failed\"** at startup" → "Verify `EMAIL_IMAP_HOST` and `EMAIL_IMAP_PORT`. Ensure IMAP is enabled on the account. For Gmail, enable it in Settings → Forwarding and POP/IMAP."
  - "**\"SMTP connection failed\"** at startup" → "Verify `EMAIL_SMTP_HOST` and `EMAIL_SMTP_PORT`. Check that your password is correct (use App Password for Gmail)."
  - "**Messages not received**" → "Check `EMAIL_ALLOWED_USERS` includes the sender's email. Check spam folder — some providers flag automated replies."
  - "**\"Authentication failed\"**" → "For Gmail, you must use an App Password, not your regular password. Ensure 2FA is enabled first."
  - "**Duplicate replies**" → "Ensure only one gateway instance is running. Check `hermes gateway status`."
  - "**Slow response**" → "The default poll interval is 15 seconds. Reduce with `EMAIL_POLL_INTERVAL=5` for faster response (but more IMAP connections)."
  - "**Replies not threading**" → "The adapter uses In-Reply-To headers. Some email clients (especially web-based) may not thread correctly with automated messages."
- **Outputs / side effects:** n/a.
- **Config / env:** all `EMAIL_*` keys.
- **Edge cases / guards:** Security notes verbatim: "**Use a dedicated email account.** Don't use your personal email — the agent stores the password in `.env` and has full inbox access via IMAP."; "Use **App Passwords** instead of your main password (required for Gmail with 2FA)"; "Set `EMAIL_ALLOWED_USERS` to restrict who can interact with the agent"; "The password is stored in `~/.hermes/.env` — protect this file (`chmod 600`)"; "IMAP uses SSL (port 993) and SMTP uses STARTTLS (port 587) by default — connections are encrypted".
- **Rebuild notes:** Convert the first two rows into startup probes that name the failing setting. A better version would run an end-to-end self-test that mails the home address at first start.

---

## Handoffs

- Telegram adapter (`plugins/platforms/telegram`) — covered by the `platform-telegram` shard.
- All other platform adapters (`signal`, `irc`, `line`, `sms`, `wecom`, `feishu`, `dingtalk`, `simplex`, `ntfy`, `a2a`, `raft`, `photon`, `buzz`, `qqbot`, `weixin`, `yuanbao`, `bluebubbles`, `whatsapp_cloud`, `api_server`, `webhook`, `msgraph_webhook`, `homeassistant`, `open-webui`, `relay`) — `platforms-b`.
- `msgraph_webhook` adapter internals (bind host, `client_state` verification, `allowed_source_cidrs`, `/msgraph/webhook` handler) — `platforms-b`; only its pipeline-facing configuration is documented here.
- `hermes slack manifest` full flag/output surface — `cli-b.slack.manifest` and `cli-b.slack.native-slashes`.
- `hermes whatsapp` QR-pairing command surface — `cli-b.whatsapp`; `hermes whatsapp-cloud` — `cli-b.whatsapp-cloud`.
- `hermes gateway setup` per-platform wizard entries — `cli-b.gateway.setup.{slack,whatsapp,matrix,mattermost,teams,google_chat,email}`; only the plugin-side `setup_fn` bodies are documented here.
- Config-page rendering of `slack.*`, `matrix.*`, `mattermost.*` keys — `config-b`; env-var reference entries for every `SLACK_*`/`MATRIX_*`/`MATTERMOST_*`/`WHATSAPP_*`/`TEAMS_*`/`GOOGLE_CHAT_*`/`EMAIL_*` variable — `env-vars`.
- Gateway core: `BasePlatformAdapter` contract, `MessageDeduplicator`, `build_session_key`, `resolve_channel_prompt`, `_wire_plugin_handlers`, fatal-error hooks, cron dispatch, `send_message` tool dispatch, `unauthorized_dm_behavior` pairing flow — `gw-core`.
- Slash-command registry and per-command semantics (`/btw`, `/stop`, `/model`, `/queue`, `/steer`, `/goal`, `/subgoal`, `/bg`, `/tasks`, `/yolo`, `/set-home`, `/sethome`, `/resume --cross-room`, …) — `gw-slash`.
- `tools/approval.py`, `tools/slash_confirm.py`, `tools/clarify_gateway.py` primitives that the platform prompts resolve against — `tools`.
- `tools/microsoft_graph_auth.py` / `tools/microsoft_graph_client.py` (used by `TeamsSummaryWriter` and the Teams pipeline) — `tools`.
- `gateway/whatsapp_identity.py` LID↔phone mapping helper — `gw-core`.
- Bundled Himalaya email skill (`email-himalaya`) — `skills-core`; the Email gateway adapter here is a separate surface.
- `GATEWAY_PROXY_URL` / `GATEWAY_PROXY_KEY` thin-gateway proxy mode and the `api_server` platform it forwards to — `platforms-b` / `gw-core`; documented here only as the Matrix E2EE-on-macOS deployment.
- **Unresolved:** the six Matrix agent tools named in `website/docs/user-guide/messaging/matrix.md:409` (`matrix_send_reaction`, `matrix_redact_message`, `matrix_create_room`, `matrix_invite_user`, `matrix_fetch_history`, `matrix_set_presence`) are documented and their `MATRIX_TOOLS_ALLOW_*` gates exist in the adapter's env surface, but no registering module was found in the v2026.8.31 tree and none appear in `tools_full.json` (83 tools) or `tools_toolsets.json` (59 toolsets) — either they are registered dynamically in a path this inventory did not exercise, or the docs describe an unshipped feature.
