# Telegram platform adapter — every feature

This shard documents the complete Telegram surface of Hermes Agent v2026.8.31: the bundled
platform plugin at `plugins/platforms/telegram/` (`adapter.py` 11 296 lines, `inline_picker.py`,
`telegram_ids.py`, `telegram_network.py`, `plugin.yaml`), the Telegram-only parts of the gateway
runner (`gateway/run.py` topic lanes, auto-rename, System-topic pinning), the Telegram command-menu
builder in `hermes_cli/commands.py`, the setup wizard (`hermes_cli/setup.py::_setup_telegram`) and
managed-bot QR onboarding (`hermes_cli/telegram_managed_bot.py`), plus every user-facing string and
config key documented in `website/docs/user-guide/messaging/telegram.md` and `locales/en.yaml`.
It deliberately leaves to sibling shards: the generic slash-command catalogue and dispatch
(`gw-slash`), cross-platform gateway core (`gw-core`), the shared `BasePlatformAdapter` /
stream-consumer machinery, other platform adapters, the web dashboard, the CLI tree, and the global
config-key catalogue — only Telegram-specific behaviour of those systems is described here.

---

## 1. Plugin registration, dependencies and setup

### Telegram platform plugin manifest  `id: platform-telegram.plugin-manifest`
- **Surface:** Config
- **Where:** `plugins/platforms/telegram/plugin.yaml`; surfaces in `hermes plugins list` and the dashboard Plugins page as label **`Telegram`**.
- **What it does:** Declares the bundled Telegram platform plugin, its required and optional environment variables, and the prompts the setup UI shows for each.
- **How it works:** `plugins/platforms/telegram/plugin.yaml:1-35`. Fields: `name: telegram-platform`, `label: Telegram`, `kind: platform`, `version: 1.0.0`, `author: NousResearch`, and a `description` reading "Telegram gateway adapter for Hermes Agent. Connects to Telegram via python-telegram-bot and relays messages between Telegram chats/groups/topics and the Hermes agent. Supports threads/topics, streaming edits, native media, inline keyboards, slash commands, fallback network transport (direct-IP failover), notification modes, mention gating, and per-user/chat allowlists." `plugins/platforms/telegram/__init__.py:1-3` re-exports `register` from `adapter.py`.
- **Inputs / options:** `requires_env`: **`TELEGRAM_BOT_TOKEN`** — description "Telegram bot token from @BotFather", prompt "Telegram bot token", url `https://t.me/BotFather`, `password: true`. `optional_env`: **`TELEGRAM_ALLOWED_USERS`** (description "Comma-separated Telegram user IDs allowed to talk to the bot", prompt "Allowed users (comma-separated)"), **`TELEGRAM_ALLOW_ALL_USERS`** (description "Allow any Telegram user to trigger the bot (dev only)", prompt "Allow all users? (true/false)"), **`TELEGRAM_HOME_CHANNEL`** (description "Default chat ID for cron / notification delivery", prompt "Home channel ID"), **`TELEGRAM_HOME_CHANNEL_NAME`** (description "Display name for the Telegram home channel", prompt "Home channel display name").
- **Outputs / side effects:** The plugin loader reads this manifest to decide whether the platform is configurable and which env prompts to render; nothing is written.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_ALLOW_ALL_USERS`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_HOME_CHANNEL_NAME`.
- **Edge cases / guards:** `password: true` means the token is masked in every prompt/echo; a manifest parse failure disables the plugin entirely.
- **Rebuild notes:** A YAML manifest with `name/label/kind/version/description/author`, plus `requires_env`/`optional_env` lists of `{name, description, prompt, url?, password}`. A better version would declare capability flags (rich messages, drafts, topics) so surfaces can gate UI without importing the adapter.

### `register(ctx)` — platform registration contract  `id: platform-telegram.register`
- **Surface:** Core
- **Where:** Called by the Hermes plugin system at gateway/CLI boot; the resulting platform appears everywhere as `telegram` with emoji **✈️**.
- **What it does:** Registers the Telegram platform with the gateway registry: adapter factory, dependency probes, connectivity test, setup wizard, YAML→env translator, allowlist env names, cron delivery var, standalone sender, message length and emoji.
- **How it works:** `plugins/platforms/telegram/adapter.py:11276-11296`. `ctx.register_platform(...)` with: `name="telegram"`, `label="Telegram"`, `adapter_factory=_build_adapter`, `check_fn=telegram_deps_present`, `ensure_deps_fn=check_telegram_requirements`, `is_connected=_is_connected`, `required_env=["TELEGRAM_BOT_TOKEN"]`, `install_hint="Run `hermes setup` to install Telegram support."`, `setup_fn=interactive_setup`, `apply_yaml_config_fn=_apply_yaml_config`, `allowed_users_env="TELEGRAM_ALLOWED_USERS"`, `allow_all_env="TELEGRAM_ALLOW_ALL_USERS"`, `cron_deliver_env_var="TELEGRAM_HOME_CHANNEL"`, `standalone_sender_fn=_standalone_send`, `max_message_length=4096`, `emoji="✈️"`, `allow_update_command=True`.
- **Inputs / options:** All 17 keyword arguments above.
- **Outputs / side effects:** Telegram becomes selectable in `hermes gateway setup`, `/platforms`, cron `deliver=telegram`, the dashboard, and `hermes update --gateway` (because `allow_update_command=True`).
- **Config / env:** n/a (registration-time only).
- **Edge cases / guards:** The comment block at `adapter.py:11029-11041` records that this replaced the hard-coded `Platform.TELEGRAM` branches in `gateway/run.py`, `gateway/config.py`, `hermes_cli/{setup,gateway}.py`, and `tools/send_message_tool.py`.
- **Rebuild notes:** One registration call carrying every per-platform hook; a better version would also register capability descriptors (supports drafts/rich/topics/reactions) instead of `hasattr` probes scattered through the adapter.

### Lazy install of `python-telegram-bot`  `id: platform-telegram.lazy-deps`
- **Surface:** CLI | Core
- **Where:** Triggered on `create_adapter()` when the SDK is missing; failure prints "python-telegram-bot not installed. Run: pip install python-telegram-bot" in the gateway log.
- **What it does:** Detects whether `python-telegram-bot` is importable; if not, installs it on demand and rebinds every SDK symbol so the adapter works without a restart.
- **How it works:** `adapter.py:160-200` does the guarded import (`Update, Bot, Message, InlineKeyboardButton, InlineKeyboardMarkup`, optional `LinkPreviewOptions`, `telegram.ext.{Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler, MessageHandler, ContextTypes, TypeHandler, filters}`, `telegram.constants.{ParseMode, ChatType}`, `telegram.request.HTTPXRequest`) setting `TELEGRAM_AVAILABLE`. `telegram_deps_present()` (`adapter.py:353-362`) is the PASSIVE probe registered as `check_fn`. `check_telegram_requirements()` (`adapter.py:364-425`) is the ACTIVE `ensure_deps_fn`: calls `tools.lazy_deps.ensure("platform.telegram", prompt=False)`, re-imports, and rebinds ~17 module globals.
- **Inputs / options:** none (no flags).
- **Outputs / side effects:** pip install into the Hermes environment; `TELEGRAM_AVAILABLE` flips to True.
- **Config / env:** n/a.
- **Edge cases / guards:** When the SDK is absent, `ContextTypes` is replaced with a `_MockContextTypes` stub whose `DEFAULT_TYPE = Any` so the class body still imports; `connect()` fails fast with fatal code `missing_dependency` (retryable=False).
- **Rebuild notes:** Split passive detection from active install; never install from a status display. A better version would pin the SDK version range and report it in `/status`.

### Telegram "connected" check  `id: platform-telegram.is-connected`
- **Surface:** Core | Config
- **Where:** Drives whether Telegram shows as configured in `hermes gateway status`, `/platforms`, and the registry-driven plugin-enable pass.
- **What it does:** Reports Telegram as connected only when a bot token is configured — not merely because the SDK is installed.
- **How it works:** `adapter.py:11081-11095`. Reads `config.token`; falls back to `hermes_cli.gateway.get_env_value("TELEGRAM_BOT_TOKEN")`; returns `bool(str(token).strip())`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** none.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `platforms.telegram.token`.
- **Edge cases / guards:** Without this, any machine with `python-telegram-bot` installed would auto-enable Telegram.
- **Rebuild notes:** Gate connectivity on credentials, not libraries.

### `hermes gateway setup` → Telegram wizard  `id: platform-telegram.setup-wizard`
- **Surface:** CLI
- **Where:** `hermes gateway setup` (or `hermes setup`) → choose **Telegram**; header printed as **`Telegram`**.
- **What it does:** Walks the user through bot creation (automatic QR or manual token), user allowlist, and home channel, writing everything to `~/.hermes/.env`.
- **How it works:** `adapter.py:11135-11144` `interactive_setup()` lazily calls `hermes_cli.setup._setup_telegram()` (`hermes_cli/setup.py:2027-2124`). Flow: if `TELEGRAM_BOT_TOKEN` already exists → prints "Telegram: already configured" and asks "Reconfigure Telegram?" (default No); on No, if `TELEGRAM_ALLOWED_USERS` is empty it prints "⚠️  Telegram has no user allowlist - anyone can use your bot!" and asks "Add allowed users now?" (default Yes) with hint "   To find your Telegram user ID: message @userinfobot" and prompt "Allowed user IDs (comma-separated)", then "Telegram allowlist configured".
- **Inputs / options:** Method menu — "How would you like to create your Telegram bot?", "  [1] Automatic (recommended)" / "      Scan a QR code → confirm in Telegram → done." / "      No token copy-paste needed.", "  [2] Manual" / "      Create a bot via @BotFather yourself and paste the token."; prompt **"Choice [1/2]"** default `1`. Then: "Telegram bot token" (password prompt), "Allow this Telegram account to use the bot?" (default Yes), "Additional allowed user IDs (comma-separated, optional)", "Allowed user IDs (comma-separated, leave empty for open access)", "Use your user ID ({id}) as the home channel?" (default Yes), "Home channel ID (or leave empty to set later with /set-home in Telegram)", "Home channel ID (leave empty to set later)".
- **Outputs / side effects:** Writes `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL` via `save_env_value` into `~/.hermes/.env`. Success lines: "Telegram token saved", "Telegram allowlist configured - only listed users can use the bot", "Telegram home channel set to {id}". Warnings: "⚠️  No allowlist set - anyone who finds your bot can use it!". Security block: "🔒 Security: Restrict who can use your bot" / "   To find your Telegram user ID:" / "   1. Message @userinfobot on Telegram" / "   2. It will reply with your numeric ID (e.g., 123456789)". Home-channel block: "📬 Home Channel: where Hermes delivers cron job results," / "   cross-platform messages, and notifications." / "   For Telegram DMs, this is your user ID (same as above)." / "   You can also set this later by typing /set-home in your Telegram chat."
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL`.
- **Edge cases / guards:** Token must match `^\d+:[A-Za-z0-9_-]{30,}$` (`hermes_cli/setup.py:1975-1979`); a bad token reprints "Invalid token format. Expected: <numeric_id>:<alphanumeric_hash> (e.g., 123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ)" and re-prompts. An automatic result with an invalid token prints "Automatic setup returned an invalid Telegram bot token." and falls back with "Falling back to manual setup...".
- **Rebuild notes:** Wizard = existing-config short circuit → creation-method menu → token validation loop → allowlist → home channel. A better version would call `getMe` immediately to confirm the token and display the bot's `@username` before writing anything.

### Automatic bot creation via QR (Managed Bots onboarding)  `id: platform-telegram.setup-auto-qr`
- **Surface:** CLI
- **Where:** `hermes gateway setup` → Telegram → Choice `1`.
- **What it does:** Creates a user-owned Telegram bot without BotFather copy/paste: Hermes asks a Nous-hosted onboarding service for a pairing, renders a QR code, and the user confirms "Create Bot" in Telegram; the token is then fetched once and stored locally.
- **How it works:** `hermes_cli/telegram_managed_bot.py`. `create_pairing()` (l.166-205) POSTs `{"bot_name": "Hermes Agent"}` to `{API}/v1/telegram/pairings` (10s timeout) expecting `pairing_id`, `poll_token`, `suggested_username`, `deep_link`, optional `qr_payload`/`expires_at`. `poll_pairing_result_once()` (l.208-236) GETs `{API}/v1/telegram/pairings/{pairing_id}` with `Authorization: Bearer <poll_token>`, requiring `status == "ready"` and a token matching `^\d+:[A-Za-z0-9_-]{30,}$`; also returns `bot_username` and `owner_user_id`. `auto_setup_telegram_bot_result()` (l.279-342) drives the loop with a 2 s `POLL_INTERVAL` and 180 s `DEFAULT_POLL_TIMEOUT`, drawing a braille spinner `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`. `render_qr_terminal()` uses the optional `qrcode` package (`ERROR_CORRECT_L`, `box_size=1`, `border=1`, `print_ascii(invert=True)`).
- **Inputs / options:** `api_url` (default `https://setup.hermes-agent.nousresearch.com`, override env **`TELEGRAM_ONBOARDING_URL`**), `manager_bot` (default `HermesSetupBot`), `profile_name`, `poll_timeout`. Helpers: `generate_username_slug(length=16)` over alphabet `abcdefghijklmnopqrstuvwxyz234567` (80 bits), `generate_bot_username()` → `hermes_<slug>_bot`, `generate_deep_link()` → `https://t.me/newbot/<manager>/<username>[?name=…]`, `generate_pairing_nonce()` → 16 random bytes hex.
- **Outputs / side effects:** Console output: "  Contacting Hermes Telegram onboarding service: {url}", "  ✓ Pairing created", "  Rendering QR code...", "  Scan this QR code with your phone, or open the link below:", the QR block or "  (Install 'qrcode' for a scannable QR code: pip install qrcode)", "  Link: {deep_link}", "  When Telegram opens, tap 'Create Bot' to confirm.", "  (You can edit the bot display name before confirming)", the spinner line "  {char} Waiting for bot creation... ({n}s remaining) ", then either "  ✓ Bot created successfully!" or "  ✗ Timed out waiting for bot creation." + "    The bot may still be created — check Telegram." + "    You can paste the token manually below, or re-run setup.". Failure to reach the service prints "  ✗ Could not reach the Hermes Telegram onboarding service." + "    Try the manual setup instead, or check your network."
- **Config / env:** `TELEGRAM_ONBOARDING_URL`.
- **Edge cases / guards:** Any `httpx.HTTPError`/`ValueError` during polling is swallowed and retried until the deadline; non-200/201 create responses return `None`; a `poll_token` is only ever used as a bearer credential; `owner_user_id` is validated as a positive decimal (bools rejected).
- **Rebuild notes:** Pairing service issues `{pairing_id, poll_token, deep_link}`; client renders QR + polls with the bearer token until `status=ready`. A better version would use server-sent events instead of 2 s polling and would let the user pick the bot display name in the terminal.

### Manual bot creation via @BotFather  `id: platform-telegram.botfather-newbot`
- **Surface:** Docs
- **Where:** `website/docs/user-guide/messaging/telegram.md:11-27` — "Step 1: Create a Bot via BotFather".
- **What it does:** Documents the five-step BotFather flow that yields the API token Hermes needs.
- **How it works:** Search **@BotFather** / open `t.me/BotFather` → send `/newbot` → choose a **display name** (e.g. "Hermes Agent") → choose a **username** ending in `bot` (e.g. `my_hermes_bot`) → BotFather replies with a token shaped `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`.
- **Inputs / options:** BotFather commands `/newbot`, `/revoke`, `/token`.
- **Outputs / side effects:** A bot token that must be written to `TELEGRAM_BOT_TOKEN`.
- **Config / env:** `TELEGRAM_BOT_TOKEN`.
- **Edge cases / guards:** Doc warning: "Keep your bot token secret. Anyone with this token can control your bot. If it leaks, revoke it immediately via `/revoke` in BotFather."
- **Rebuild notes:** n/a (external provider flow).

### BotFather customization commands  `id: platform-telegram.botfather-customize`
- **Surface:** Docs
- **Where:** `telegram.md:29-49` — "Step 2: Customize Your Bot (Optional)".
- **What it does:** Lists the BotFather commands that change how the bot presents itself, plus a suggested starter `/setcommands` payload.
- **How it works:** Table of five commands: `/setdescription` — "The "What can this bot do?" text shown before a user starts chatting"; `/setabouttext` — "Short text on the bot's profile page"; `/setuserpic` — "Upload an avatar for your bot"; `/setcommands` — "Define the command menu (the `/` button in chat)"; `/setprivacy` — "Control whether the bot sees all group messages (see Step 3)". Suggested starter set: `help - Show help information`, `new - Start a new conversation`, `sethome - Set this chat as the home channel`.
- **Inputs / options:** the five commands above; also `/setinline` (inline picker) and `/setprivacy_policy` (`telegram.md:948`) documented elsewhere in the page.
- **Outputs / side effects:** Changes the bot's global Telegram profile.
- **Config / env:** n/a.
- **Edge cases / guards:** Hermes overwrites the `/setcommands` menu itself on every connect (see `platform-telegram.command-menu`), so a manual `/setcommands` list is transient.
- **Rebuild notes:** n/a.

### Group privacy mode  `id: platform-telegram.privacy-mode`
- **Surface:** Docs
- **Where:** `telegram.md:126-151` — "Step 3: Privacy Mode (Critical for Groups)".
- **What it does:** Explains that Telegram bots default to privacy mode ON and what that hides, plus two ways to fix it.
- **How it works:** With privacy ON the bot sees only: messages starting with `/`, direct replies to the bot's own messages, service messages (member joins/leaves, pinned messages…), and messages in channels where the bot is an admin. With privacy OFF it receives every group message. Disable via **@BotFather** → `/mybots` → select bot → **Bot Settings → Group Privacy → Turn off**.
- **Inputs / options:** BotFather `/setprivacy`, `/mybots`.
- **Outputs / side effects:** Determines which updates Telegram delivers at all — Hermes gating can never see what Telegram withholds.
- **Config / env:** n/a.
- **Edge cases / guards:** Doc warning: "**You must remove and re-add the bot to any group** after changing the privacy setting. Telegram caches the privacy state when a bot joins a group, and it will not update until the bot is removed and re-added." Doc tip: promoting the bot to **group admin** also delivers all messages regardless of privacy mode.
- **Rebuild notes:** n/a (Telegram-side setting). A better version would call `getChatMember` at connect and warn in the log when the bot is neither admin nor privacy-off in an allowlisted group.

### Finding your Telegram user ID  `id: platform-telegram.find-user-id`
- **Surface:** Docs
- **Where:** `telegram.md:179-187` — "Step 4: Find Your User ID".
- **What it does:** Tells the operator how to obtain the numeric user ID required by `TELEGRAM_ALLOWED_USERS`.
- **How it works:** "Method 1 (recommended):" message [@userinfobot](https://t.me/userinfobot); "Method 2:" message [@get_id_bot](https://t.me/get_id_bot).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `TELEGRAM_ALLOWED_USERS`.
- **Edge cases / guards:** Doc stresses the ID is **not** the username; group chat IDs are negative (e.g. `-1001234567890`) and a personal DM chat ID equals the user ID.
- **Rebuild notes:** A better version would print the caller's own user id on the first unauthorized DM, which Hermes already knows.

### Single-token exclusivity lock  `id: platform-telegram.platform-lock`
- **Surface:** Core
- **Where:** Acquired inside `connect()`; a second gateway with the same token refuses to start.
- **What it does:** Prevents two Hermes processes from long-polling the same bot token (which Telegram answers with 409 Conflict).
- **How it works:** `adapter.py:4516-4517` — `self._acquire_platform_lock('telegram-bot-token', self.config.token, 'Telegram bot token')`; returns False (no connect) if the lock is held. Released in `disconnect()` (`adapter.py:5225`) *before* the rest of teardown, and on any connect exception (`adapter.py:5040`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** A lock entry keyed by token; connect returns False when contended.
- **Config / env:** `TELEGRAM_BOT_TOKEN`.
- **Edge cases / guards:** The lock is released first in `disconnect()` so a wedged HTTP close cannot block the reconnect watcher (#80598).
- **Rebuild notes:** Hash the token for the lock key; a better version would also detect a foreign process holding the token by inspecting `getUpdates` conflicts and naming the competing host.

---

## 2. Connection: polling, webhook and transport

### Long polling (default transport)  `id: platform-telegram.polling-mode`
- **Surface:** Gateway/Telegram
- **Where:** Default when `TELEGRAM_WEBHOOK_URL` is unset; log line `[telegram] Connected to Telegram (polling mode)`.
- **What it does:** Opens an outbound `getUpdates` long-poll to Telegram and feeds every update into the PTB handler chain.
- **How it works:** `adapter.py:4942-4996`. Clears any stale webhook first (`_delete_webhook_best_effort`), installs `_polling_error_callback`, then `_start_polling_resilient(drop_pending_updates=not is_reconnect, error_callback=…, require_progress=not is_reconnect)`. `_start_polling_once` (`adapter.py:2706-2768`) calls `app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=…, error_callback=…)` bounded by `_UPDATER_START_TIMEOUT = 30.0` s. A dedicated `HTTPXRequest` is used for `getUpdates` (separate pool from the general request), instrumented by `_instrument_polling_request` so successful round-trips are observed.
- **Inputs / options:** `is_reconnect` (bool) — cold boot drops the server-side queue, watcher reconnect preserves it (#46621).
- **Outputs / side effects:** Updates dispatched to handlers; polling generation counter incremented; `_send_path_degraded` cleared once the first successful `getUpdates` returns.
- **Config / env:** `HERMES_TELEGRAM_HTTP_POOL_SIZE` (512), `HERMES_TELEGRAM_HTTP_POOL_TIMEOUT` (8.0), `HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT` (10.0), `HERMES_TELEGRAM_HTTP_READ_TIMEOUT` (20.0), `HERMES_TELEGRAM_HTTP_WRITE_TIMEOUT` (20.0), `HERMES_TELEGRAM_INIT_TIMEOUT` (30.0).
- **Edge cases / guards:** Cold start uses a strict readiness gate (`_INITIAL_POLLING_PROGRESS_TIMEOUT = 60.0` s) and raises `OSError("Telegram getUpdates made no progress within 60s during initial connect — failing startup so the gateway retries with a fresh adapter (#67498)")` so GatewayRunner disposes the partial adapter; reconnects degrade to background recovery with the log "Connected in degraded Telegram mode: gateway is alive, polling will be retried in the background".
- **Rebuild notes:** Long-poll on a dedicated connection pool, track a monotonically increasing "generation" per start, and only call the transport healthy after a real `getUpdates` 200. A better version would expose polling health as a metric rather than only a log line.

### Webhook mode  `id: platform-telegram.webhook-mode`
- **Surface:** Gateway/Telegram | Env
- **Where:** Enabled by setting `TELEGRAM_WEBHOOK_URL`; log `[telegram] Connected to Telegram (webhook mode)` and `Webhook server listening on {host}:{port}{path}`.
- **What it does:** Runs an inbound HTTP server that Telegram pushes updates to, so cloud hosts can suspend the machine between messages.
- **How it works:** `adapter.py:4864-4941`. Reads `TELEGRAM_WEBHOOK_URL`; port from `env_int("TELEGRAM_WEBHOOK_PORT", 8443)`; bind host from `TELEGRAM_WEBHOOK_HOST` or `platforms.telegram.extra.webhook_host` (default `""` → tornado opens one socket per address family, IPv4+IPv6); secret via profile-scoped `agent.secret_scope.get_secret("TELEGRAM_WEBHOOK_SECRET")` falling back to `os.getenv`. Path is `urlparse(webhook_url).path or "/telegram"`. Calls `app.updater.start_webhook(listen=…, port=…, url_path=…, webhook_url=…, secret_token=…, allowed_updates=Update.ALL_TYPES, drop_pending_updates=not is_reconnect)`. Sets `_webhook_mode=True`, `_polling_progress_accepting=False`, `_send_path_degraded=False`.
- **Inputs / options:** `TELEGRAM_WEBHOOK_URL` (required to enable), `TELEGRAM_WEBHOOK_SECRET` (required), `TELEGRAM_WEBHOOK_PORT` (default 8443), `TELEGRAM_WEBHOOK_HOST` / `extra.webhook_host` (default all interfaces).
- **Outputs / side effects:** Binds a local TCP listener; registers the webhook with Telegram; no polling heartbeat is started (there is no long-poll socket to wedge), but a dedicated `_bot_identity_refresh_loop` is.
- **Config / env:** the four env vars above; `platforms.telegram.extra.webhook_host`.
- **Edge cases / guards:** Missing `TELEGRAM_WEBHOOK_SECRET` raises with the verbatim message: "TELEGRAM_WEBHOOK_SECRET is required when TELEGRAM_WEBHOOK_URL is set. Without it, the webhook endpoint accepts forged updates from anyone who can reach it — see https://github.com/NousResearch/hermes-agent/security/advisories/GHSA-3vpc-7q5r-276h.\n\nGenerate a secret and set it in your .env:\n  export TELEGRAM_WEBHOOK_SECRET=\"$(openssl rand -hex 32)\"\n\nThen register it with Telegram when setting the webhook via setWebhook's secret_token parameter." Old builds bound IPv4-only (`0.0.0.0`), breaking IPv6-only private networks (Fly.io 6PN) — the default is now dual-stack.
- **Rebuild notes:** Fail closed on a missing shared secret; extract the URL path from the public URL; bind dual-stack by default. A better version would verify the registered webhook with `getWebhookInfo` after start and log a mismatch.

### Polling vs webhook comparison table  `id: platform-telegram.transport-comparison`
- **Surface:** Docs
- **Where:** `telegram.md:270-275`.
- **What it does:** Tells the operator which transport to pick.
- **How it works:** Rows — Direction: "Gateway → Telegram (outbound)" vs "Telegram → Gateway (inbound)"; Best for: "Local, always-on servers" vs "Cloud platforms with auto-wake"; Setup: "No extra config" vs "Set `TELEGRAM_WEBHOOK_URL`"; Idle cost: "Machine must stay running" vs "Machine can sleep between messages".
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** Fly.io example (`telegram.md:295-322`) sets `fly secrets set TELEGRAM_WEBHOOK_URL=…` / `TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)` and exposes `internal_port = 8443` behind `port = 443` with `handlers = ["tls", "http"]`.
- **Rebuild notes:** n/a.

### Custom Bot API base URL (local telegram-bot-api server)  `id: platform-telegram.base-url`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.base_url` / `base_file_url` in `~/.hermes/config.yaml`; log "Using custom Telegram base_url: {url}".
- **What it does:** Points python-telegram-bot at a self-hosted `telegram-bot-api` daemon, which raises the 20 MB `getFile` ceiling to 2 GB and can bypass an unreachable `api.telegram.org`.
- **How it works:** `adapter.py:4521-4530` — `builder.base_url(custom_base_url)` and `builder.base_file_url(extra.get("base_file_url", custom_base_url))`. Presence of `base_url` alone lifts the internal cap: `adapter.py:857-864` sets `self._max_doc_bytes = 2*1024*1024*1024` instead of `20*1024*1024`.
- **Inputs / options:** `extra.base_url` (e.g. `http://127.0.0.1:8081/bot`), `extra.base_file_url` (e.g. `http://127.0.0.1:8081/file/bot`), `extra.local_mode`.
- **Outputs / side effects:** All Bot API traffic goes to the local server; the size-limit message becomes "Maximum: 2048 MB.".
- **Config / env:** `platforms.telegram.extra.base_url`, `.base_file_url`, `.local_mode`; server side `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_LOCAL`.
- **Edge cases / guards:** Docs (`telegram.md:420-547`) require: MTProto credentials from my.telegram.org/apps; `curl "https://api.telegram.org/bot<TOKEN>/logOut"` once (expect `{"ok":true,"result":true}`); binding the container to `127.0.0.1` ("**Never expose port 8081 to the public internet.**"); and the caution "Use `platforms.telegram.extra`, not `telegram.extra`" — keys under a top-level `telegram.extra` block are silently dropped.
- **Rebuild notes:** One config key both selects the endpoint and lifts the size cap. A better version would probe `getMe` against the custom base URL at connect and report the effective file ceiling in `/status`.

### `local_mode` — read Telegram files from disk  `id: platform-telegram.local-mode`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.local_mode: true`; log "Using Telegram local_mode (read files from disk)".
- **What it does:** Tells PTB that `getFile` returns absolute filesystem paths (as `telegram-bot-api --local` does) so downloads read from disk instead of issuing an HTTP GET.
- **How it works:** `adapter.py:4536-4538` — `builder.local_mode(True)`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** `download_as_bytearray()` reads local files.
- **Config / env:** `platforms.telegram.extra.local_mode`.
- **Edge cases / guards:** If Hermes cannot `stat` the returned path, PTB silently falls back to HTTP `getFile`, which `--local` answers with 404; symptom documented as `[Telegram] Failed to cache voice: Not Found` / `telegram.error.InvalidToken: Not Found` (`telegram.md:530-537`). Requires the same absolute path on both hosts (NFS/CIFS) and matching uid ownership.
- **Rebuild notes:** Only enable disk reads when the path is verified readable; a better version would stat one file at connect and downgrade to HTTP with a warning instead of failing per-message.

### HTTP client tuning (pools and timeouts)  `id: platform-telegram.http-tuning`
- **Surface:** Env
- **Where:** Environment variables read at connect.
- **What it does:** Overrides python-telegram-bot's aggressive HTTP defaults so flaky networks don't exhaust the connection pool.
- **How it works:** `adapter.py:4543-4572`. `request_kwargs` = `connection_pool_size` ← `HERMES_TELEGRAM_HTTP_POOL_SIZE` (default **512**), `pool_timeout` ← `HERMES_TELEGRAM_HTTP_POOL_TIMEOUT` (**8.0**), `connect_timeout` ← `HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT` (**10.0**), `read_timeout` ← `HERMES_TELEGRAM_HTTP_READ_TIMEOUT` (**20.0**), `write_timeout` ← `HERMES_TELEGRAM_HTTP_WRITE_TIMEOUT` (**20.0**), and a hard-coded `media_write_timeout = 60.0` (PTB routes file-carrying requests here, so the plain write timeout never applied to uploads). Media *reads* use `_MEDIA_SEND_READ_TIMEOUT = 60.0` (`adapter.py:257`) because Telegram transcodes video before answering `sendVideo`.
- **Inputs / options:** the five env vars; all parsed with a `try/except` fallback to the default.
- **Outputs / side effects:** Shapes every Bot API request.
- **Config / env:** as listed.
- **Edge cases / guards:** Keepalive limits are injected via `gateway.platforms._http_client_limits.platform_httpx_limits()`; the `getUpdates` pool gets `max_keepalive_connections=0` so a long-poll never reuses a socket from a previous poll, while the general pool keeps reusable keepalive sockets (`adapter.py:4586-4608`).
- **Rebuild notes:** Two pools (updates vs general), no keepalive on the updates pool, a longer write budget for uploads. A better version would expose these as config keys too, not env-only.

### Fallback-IP transport with DNS-over-HTTPS discovery  `id: platform-telegram.fallback-ips`
- **Surface:** Env | Config
- **Where:** Automatic; logs "Discovering Telegram API fallback IPs via DNS-over-HTTPS…", "Auto-discovered Telegram fallback IPs: {list}", "Telegram fallback IPs active: {list}".
- **What it does:** Reaches `api.telegram.org` over known IPv4 literals first (preserving Host header and TLS SNI) so a blackholed IPv6 route or a poisoned local resolver cannot wedge connect.
- **How it works:** `adapter.py:4624-4672` + `telegram_network.py`. Order: explicit `extra.fallback_ips` / `TELEGRAM_FALLBACK_IPS` → `discover_fallback_ips()` (Google `https://dns.google/resolve` and Cloudflare `https://cloudflare-dns.com/dns-query` with `Accept: application/dns-json`, `_DOH_TIMEOUT = 4.0` s, A records only) → hardcoded `SEED_FALLBACK_IPS = ["149.154.166.110", "149.154.167.220"]`. `TelegramFallbackTransport` (`telegram_network.py:86-239`) tries IPv4 literals first and the dual-stack hostname last, rewrites the request with `_rewrite_request_for_ip` (URL host ← IP, `headers["host"]` ← original host, `extensions["sni_hostname"]` ← original host), and becomes "sticky" on the first success ("Using sticky IPv4 Telegram API path {ip} (dual-stack hostname tried last — #87015)"). Failed pools are closed and discarded (`_reset_fallback`, `_reset_primary`) to avoid CLOSE_WAIT fd leaks (#63311); `_POOL_LIMITS = httpx.Limits(max_connections=8, max_keepalive_connections=4)`.
- **Inputs / options:** `TELEGRAM_FALLBACK_IPS` (comma-separated), `platforms.telegram.extra.fallback_ips` (list or comma string), `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS` (`1|true|yes|on` → log "Telegram fallback-IP transport disabled via env"), `HERMES_TELEGRAM_FALLBACK_DISCOVERY_TIMEOUT` (seconds, default **5.0**, min 0).
- **Outputs / side effects:** Two `TelegramFallbackTransport` instances (general + getUpdates), each with `socket_options=tcp_keepalive_socket_options()`.
- **Config / env:** as listed; also `network.force_ipv4: true` is suggested in the docs.
- **Edge cases / guards:** `_normalize_fallback_ips` rejects non-IPv4, private, loopback, link-local and unspecified addresses with "Ignoring private/internal Telegram fallback IP: {ip}" / "Ignoring non-IPv4 Telegram fallback IP: {ip}" / "Ignoring invalid Telegram fallback IP: {raw}". Discovery timeout falls back to the seed list with "Telegram fallback-IP discovery failed after {n}s; using seed IPv4 Telegram API IPs so a blackholed IPv6 hostname path cannot hang initialize() (#87015)". Only `httpx.ConnectTimeout`/`ConnectError` are retryable; anything else propagates immediately. A sticky path that fails re-walks the list ("Sticky Telegram path {ip} failed; re-walking IPv4 literals before the hostname"). httpx ignores client-level `limits` when a custom transport is supplied, so limits are passed into the transport instead (#58790).
- **Rebuild notes:** Custom `AsyncBaseTransport` that rewrites host+SNI per candidate IP, with sticky selection and per-IP pool disposal. A better version would health-check candidates in parallel (Happy-Eyeballs style) rather than sequentially.

### TCP keepalive on Telegram sockets  `id: platform-telegram.tcp-keepalive`
- **Surface:** Core
- **Where:** Applied to every fallback-transport socket.
- **What it does:** Makes a half-open/CLOSE-WAIT long-poll socket error out instead of blocking `getUpdates` forever (notably on Windows, which does not enable `SO_KEEPALIVE` by default).
- **How it works:** `telegram_network.py:34-53` `tcp_keepalive_socket_options()` returns `[(SOL_SOCKET, SO_KEEPALIVE, 1)]` plus, when the interpreter exposes them, `(IPPROTO_TCP, TCP_KEEPIDLE|TCP_KEEPALIVE, 30)`, `(IPPROTO_TCP, TCP_KEEPINTVL, 10)`, `(IPPROTO_TCP, TCP_KEEPCNT, 3)`.
- **Inputs / options:** n/a. **Outputs / side effects:** socket options on new connections.
- **Config / env:** n/a.
- **Edge cases / guards:** Options absent on a platform are simply skipped.
- **Rebuild notes:** Always set `SO_KEEPALIVE`; treat idle/interval/count as best-effort.

### Telegram-specific proxy  `id: platform-telegram.proxy`
- **Surface:** Env | Config
- **Where:** `telegram.proxy_url` in config.yaml, or `TELEGRAM_PROXY`; log "Proxy detected; passing explicitly to HTTPXRequest: {url}".
- **What it does:** Routes all Telegram traffic (primary and fallback transports) through an HTTP/HTTPS/SOCKS5 proxy.
- **How it works:** `adapter.py:4666` `resolve_proxy_url("TELEGRAM_PROXY", target_hosts=["api.telegram.org", *fallback_ips])`; when a proxy is found the fallback transport is skipped and both `HTTPXRequest` instances get `proxy=proxy_url`. `telegram_network.py:80-83` `_resolve_proxy_url` re-resolves the same var for the transport. `adapter.py:11225-11226` bridges `telegram.proxy_url` from YAML into `TELEGRAM_PROXY` when the env var is unset.
- **Inputs / options:** `TELEGRAM_PROXY`, `telegram.proxy_url`. Documented supported schemes: `http://`, `https://`, `socks5://`. Fallback chain when unset: `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, plus lowercase variants, plus macOS system-proxy auto-detection.
- **Outputs / side effects:** All Bot API and file traffic proxied.
- **Config / env:** as listed.
- **Edge cases / guards:** `TELEGRAM_PROXY` takes priority over generic proxy env vars; when a proxy is configured the direct-IP fallback branch is not used.
- **Rebuild notes:** Platform-scoped proxy var overriding the generic one, applied to every transport the platform builds.

### Connect retry ladder and total watchdog  `id: platform-telegram.connect-retry`
- **Surface:** Core
- **Where:** Gateway startup; logs "Connecting to Telegram (attempt {n}/8)…".
- **What it does:** Retries `Application.initialize()` up to 8 times with a bounded per-attempt deadline and an overall watchdog, rebuilding the PTB Application between attempts.
- **How it works:** `adapter.py:4744-4860`. `_max_connect = 8`; `_init_timeout = HERMES_TELEGRAM_INIT_TIMEOUT` (default 30.0 s); total deadline `= now + _init_timeout*8 + 120.0`. Each attempt awaits `self._app.initialize()` through `_await_with_thread_deadline` with `on_abandon=_shutdown_abandoned_app` (releases the half-built httpx pool). Backoff between attempts `min(2**attempt, 15)` s. On any failed attempt the Application is rebuilt from the same builder and `_register_handlers` re-runs so the group-99 observer stays in lockstep (#64176).
- **Inputs / options:** `HERMES_TELEGRAM_INIT_TIMEOUT`.
- **Outputs / side effects:** Log lines "Connect attempt {n}/8 timed out after {s}s — retrying in {w}s", "Connect attempt {n}/8 failed: {err} — retrying in {w}s", "Connect attempt {n}/8 interrupted by {ExcName} — propagating".
- **Config / env:** `HERMES_TELEGRAM_INIT_TIMEOUT`, plus the HTTP timeouts above.
- **Edge cases / guards:** Exhaustion raises `OSError("Telegram initialization timed out after 8 attempts (30s each). Check network connectivity to api.telegram.org or set HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT to a lower value.")`; the total watchdog raises the longer variant naming `HERMES_TELEGRAM_INIT_TIMEOUT`. `BaseException` is caught last so `CancelledError` is logged then re-raised.
- **Rebuild notes:** Per-attempt wall-clock deadline (thread timer, not `asyncio.wait_for`, because httpcore shields cancellation), abandon-and-rebuild on timeout, plus a total watchdog. A better version would surface the attempt count in `/status`.

### Wall-clock deadline helper (`_await_with_thread_deadline`)  `id: platform-telegram.thread-deadline`
- **Surface:** Core
- **Where:** Internal; used at 9 call sites (initialize, start_polling, updater.stop, drains, deleteWebhook, discovery).
- **What it does:** Awaits a coroutine with a deadline enforced by a thread timer, so a blocked event loop or a cancellation-shielded `anyio` scope cannot hang the caller forever.
- **How it works:** `adapter.py:69-93` wraps `agent.deadline.run_bounded_async(awaitable, timeout, label="telegram-init", on_abandon=…)` and re-raises `asyncio.TimeoutError` on expiry (the PTB retry ladder catches that). `_shutdown_abandoned_app` (`adapter.py:132-163`) closes the abandoned app's `Bot._request` transports directly because PTB's `shutdown()` is gated on `_initialized`. `_consume_abandoned_task` (`adapter.py:59-66`) observes the detached task's exception.
- **Inputs / options:** `awaitable`, `timeout`, `on_abandon`.
- **Outputs / side effects:** Detached cleanup tasks; debug log "Abandoned Telegram init task failed after timeout".
- **Config / env:** n/a.
- **Edge cases / guards:** Deliberately not `asyncio.wait_for`, which waits for cancellation to escape shielded scopes (#58236/#63309).
- **Rebuild notes:** Any long-poll SDK integration needs a deadline that does not depend on loop timers.

### `deleteWebhook` before polling  `id: platform-telegram.delete-webhook`
- **Surface:** Core
- **Where:** Polling connect path.
- **What it does:** Clears a previously registered webhook so polling actually receives updates.
- **How it works:** `adapter.py:2873-2908` `_delete_webhook_best_effort(require_success=not is_reconnect)` calls `bot.delete_webhook(drop_pending_updates=False)` bounded by `_UPDATER_START_TIMEOUT` (30 s).
- **Inputs / options:** `require_success` (True on cold boot).
- **Outputs / side effects:** Removes the webhook registration at Telegram.
- **Config / env:** n/a.
- **Edge cases / guards:** On cold boot a network failure raises `OSError("Telegram deleteWebhook did not complete during initial connect")` so the runner rebuilds; on reconnect it logs "deleteWebhook failed with a recoverable network error; continuing to polling so getUpdates/retry can recover: {err}" and sets `_send_path_degraded = True`. Non-network exceptions always propagate.
- **Rebuild notes:** Always clear the webhook before polling; fail closed on cold boot only.

### Polling generations and progress verifier  `id: platform-telegram.polling-generation`
- **Surface:** Core
- **Where:** Internal health machinery; log "Telegram polling confirmed healthy: getUpdates progressing (generation {n})".
- **What it does:** Treats each `start_polling()` as a numbered generation that is only considered healthy after one confirmed `getUpdates` HTTP 200 with `{"ok": true, "result": …}`.
- **How it works:** `_begin_polling_generation` (`adapter.py:2593-2616`) bumps `_polling_generation`, makes a fresh `asyncio.Event`, sets `_send_path_degraded=True` and records `_polling_generation_started_monotonic`. `_instrument_polling_request` (`adapter.py:2672-2704`) re-tags the request instance to a `__slots__ = ()` subclass overriding `do_request` (monkey-patching fails on Python 3.13 slotted instances, #64482); `_observe_polling_request_result` parses the payload with the request's own `parse_json_payload` and calls `_record_polling_progress`, which resets `_polling_network_error_count`, clears `_send_path_degraded`, and stamps `_polling_last_progress_monotonic`. `_verify_polling_after_reconnect` (`adapter.py:3472-3561`) waits `_POLLING_PROGRESS_TIMEOUT = 60.0` s for that event and, if it never fires, probes `get_me()` (10 s) to classify the failure before scheduling recovery.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `send()` short-circuits with `SendResult(success=False, error="send_path_degraded", retryable=True)` while degraded so cron falls through to standalone delivery.
- **Config / env:** n/a.
- **Edge cases / guards:** A `ContextVar` (`_POLLING_GENERATION_CONTEXT`) carries the generation into the request wrapper; progress from an older generation is ignored. Verifier bails out if teardown started, a newer generation began, or the event object was swapped.
- **Rebuild notes:** Never trust "start_polling returned" as health; require one observed successful poll per generation.

### Polling heartbeat (CLOSE-WAIT detector)  `id: platform-telegram.polling-heartbeat`
- **Surface:** Core
- **Where:** Background task started at connect in polling mode only.
- **What it does:** Probes `get_me()` every 90 s on the *general* request path so a dead long-poll socket that never raises is still detected.
- **How it works:** `adapter.py:3184-3301`. `HEARTBEAT_INTERVAL = 90` s, `PROBE_TIMEOUT = 15` s. Each tick: (1) force-escalate a recovery task that has been in flight longer than `_POLLING_ERROR_TASK_STUCK_TIMEOUT = 300.0` s ("Telegram reconnect task wedged for {n}s with no ladder progress; forcing retryable-fatal so the gateway reconnects instead of staying silently deaf."), (2) `await asyncio.wait_for(bot.get_me(), 15)` and adopt the reported `@username`, (3) `_probe_pending_updates`, (4) `_check_polling_stall`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** May schedule `_handle_polling_network_error` via `_schedule_polling_recovery(reason="heartbeat probe")`.
- **Config / env:** n/a.
- **Edge cases / guards:** Not started in webhook mode; exits if `bot.get_me` is absent (torn-down app / test double); non-connectivity errors (e.g. TelegramError 401) are ignored so PTB's own handlers surface them.
- **Rebuild notes:** Probe on a different connection pool than the long poll, otherwise the probe inherits the same wedge.

### Pending-update probe (wedged consumer detector)  `id: platform-telegram.pending-probe`
- **Surface:** Core
- **Where:** Inside the heartbeat; logs "Telegram polling heartbeat: {n} update(s) queued but not consumed (stuck probe {k}/2)".
- **What it does:** Uses `getWebhookInfo().pending_update_count` to notice that Telegram has queued updates the running poller is not consuming, and restarts polling after two consecutive stuck probes.
- **How it works:** `adapter.py:3303-3409`. Skipped in webhook mode or while a recovery task is in flight. If `updater.running` is False it counts instead as a stopped updater ("Telegram polling heartbeat: updater stopped while in polling mode (stuck probe {k}/2)" → "Telegram updater is not running (long-poll task gone); triggering polling restart", #55769). Otherwise a non-zero `pending_update_count` twice in a row triggers "getUpdates consumer appears wedged (queue not draining); triggering polling restart" and feeds `RuntimeError("getUpdates consumer wedged: pending updates not draining")` into the network-error ladder.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Polling restart via the shared ladder.
- **Config / env:** n/a.
- **Edge cases / guards:** Debounced over two probes so a single in-flight update never trips recovery; a failed `getWebhookInfo` is ignored (the `get_me` path will catch real connectivity loss).
- **Rebuild notes:** `pending_update_count` is the only signal that distinguishes "healthy send path, dead receive path".

### Polling stall watchdog  `id: platform-telegram.polling-stall`
- **Surface:** Core
- **Where:** Inside the heartbeat; logs "Telegram polling stalled: no getUpdates progress for {n}s (generation {g}). Rebuilding the long-poll consumer through the reconnect ladder instead of staying silently deaf."
- **What it does:** Escalates when no `getUpdates` round-trip has completed for `_POLLING_STALL_TIMEOUT = 150.0` s, even though the queue is empty and `get_me()` is healthy.
- **How it works:** `adapter.py:3411-3470`. Compares `time.monotonic()` against `_polling_last_progress_monotonic` (or `_polling_generation_started_monotonic` when no round-trip ever completed) and feeds `RuntimeError("getUpdates made no progress for {n}s (polling stall watchdog)")` into `_handle_polling_network_error`.
- **Inputs / options:** n/a. **Outputs / side effects:** reconnect ladder entry.
- **Config / env:** n/a.
- **Edge cases / guards:** Skipped in webhook mode, under fatal error, during teardown, or while a recovery task is running. Threshold ≈3× Telegram's ~50 s long-poll window (#92991).
- **Rebuild notes:** A "last successful poll" timestamp plus a generous multiple of the server's poll window catches wedges no other probe can see.

### 409 Conflict recovery ladder  `id: platform-telegram.conflict-recovery`
- **Surface:** Core
- **Where:** Automatic; logs "Telegram polling conflict ({n}/5) — previous session still held open on Telegram's servers. Waiting {d}s for it to expire. Error: {err}".
- **What it does:** Recovers from `Conflict: terminated by other getUpdates request` (a killed predecessor gateway whose long-poll has not expired server-side, or a genuinely duplicate bot instance).
- **How it works:** `adapter.py:3626-3817`. `MAX_CONFLICT_RETRIES = 5`; `RETRY_DELAY = 10 + count*10` → 20 s, 30 s, 40 s, 50 s, 60 s. Steps per retry: synchronously disarm PTB's internal retry loop (`_disarm_ptb_retry_loop`), bounded `updater.stop()`, sleep, `_drain_polling_connections()`, then `_start_polling_once(drop_pending_updates=True)` (True is required: it tells Telegram to terminate the competing session, #75017). `_looks_like_polling_conflict` (`adapter.py:1825-1832`) matches class name `Conflict`, "terminated by other getupdates request", or "another bot instance is running".
- **Inputs / options:** n/a.
- **Outputs / side effects:** On exhaustion sets fatal code `telegram_polling_conflict` (retryable=False) with the verbatim message "Telegram polling could not recover after 5 retries ({total}s total wait). The previous gateway session is still held open on Telegram's servers, or another process is using the same bot token. To recover: ensure no other Hermes or OpenClaw instance is running with this token, then restart the gateway with 'hermes gateway restart'."
- **Config / env:** n/a.
- **Edge cases / guards:** `_disarm_ptb_retry_loop` (`adapter.py:3563-3624`) sets PTB's private polling `stop_event` — probing both `_Updater__polling_task_stop_event` and `_polling_task_stop_event` — because PTB's `network_retry_loop(max_retries=-1)` would otherwise keep polling concurrently with our restart and generate a fresh 409 every ~31 s. Only the first transition to fatal notifies the runner (`_already_fatal` snapshot). A `stop()` timeout escalates instead to retryable-fatal.
- **Rebuild notes:** Stop the SDK's own retry loop synchronously inside the error callback before scheduling async recovery, and pass `drop_pending_updates=True` on the conflict retry only.

### Network-error reconnect ladder  `id: platform-telegram.network-ladder`
- **Surface:** Core
- **Where:** Automatic; logs "Telegram network error (attempt {n}/10), reconnecting in {d}s. Error: {err}".
- **What it does:** Restores polling after transient transport loss (sleep/wake, Wi-Fi switch, VPN reconnect) with exponential backoff, escalating to a gateway restart if it never recovers.
- **How it works:** `adapter.py:3041-3182`. `MAX_NETWORK_RETRIES = 10`, `BASE_DELAY = 5`, `MAX_DELAY = 60` → 5, 10, 20, 40, 60, 60… Steps: sleep, bounded `updater.stop()` (`_UPDATER_STOP_TIMEOUT = 15.0`), drain the general pool if the error was a confirmed httpx pool timeout, `_drain_polling_connections()`, `_start_polling_once(drop_pending_updates=False)`. Chained retries reassign `_polling_error_task` so the reentrancy guard stays accurate.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Success logs "Telegram polling restarted after network error (attempt {n}); health pending getUpdates progress". Exhaustion sets retryable fatal `telegram_network_error` with "Telegram polling could not reconnect after 10 network error retries. Escalating to gateway recovery."
- **Config / env:** n/a.
- **Edge cases / guards:** A `stop()` timeout sets retryable fatal with "Telegram updater.stop() did not finish before the network-recovery deadline; rebuilding the adapter instead of reusing an Updater whose lifecycle lock may still be held." `self._app` is captured once so a concurrent `disconnect()` cannot swap in `None` mid-sequence (#55992).
- **Rebuild notes:** Bound every teardown await; capture the app reference; re-arm the guard on chained retries.

### Connection-pool drains  `id: platform-telegram.pool-drains`
- **Surface:** Core
- **Where:** Internal, during reconnect; logs "Polling request pool drained before reconnect" / "General request pool drained after Telegram pool timeout".
- **What it does:** Resets wedged httpx pools so `Pool timeout: All connections in the connection pool are occupied.` cannot persist across reconnects.
- **How it works:** `_drain_polling_connections` (`adapter.py:2473-2534`) shuts down and re-initializes only `Bot._request[0]` (the getUpdates request) so concurrent sends are untouched, each step bounded by `_DRAIN_TIMEOUT = 15.0` s. If shutdown was abandoned, `_orphan_and_rebuild_polling_client` (`adapter.py:2536-2591`) swaps in a fresh `httpx.AsyncClient` via `polling_req._build_client()` and closes the old one in a detached bounded task ("Replaced wedged getUpdates HTTP client after drain timeout (likely CLOSE-WAIT socket)"). `_drain_general_connections_after_pool_timeout` (`adapter.py:2802-2843`) does the same for `_request[1]` under `_general_request_drain_lock`, but only after a *confirmed* pool timeout (which PTB states was not sent).
- **Inputs / options:** n/a. **Outputs / side effects:** new HTTP clients.
- **Config / env:** n/a.
- **Edge cases / guards:** `HTTPXRequest.initialize()` only rebuilds when `client.is_closed`, so an abandoned `aclose()` would leave the dead socket in use (#87057) — hence the explicit client swap. PTB 22.x internal tuple `(get_updates_request, general_request)` is accessed directly; the code notes to review on PTB 23+.
- **Rebuild notes:** Separate pools make it safe to reset the receive path without disturbing in-flight sends.

### Transport error classifiers  `id: platform-telegram.error-classifiers`
- **Surface:** Core
- **Where:** Internal.
- **What it does:** Decides whether a Telegram exception is transient (retry), permanent-auth (fatal), a conflict, a connect timeout, or a pool timeout.
- **How it works:** `_looks_like_polling_conflict` (l.1825), `_looks_like_auth_error` (l.1834-1852: `InvalidToken` / `Forbidden` by TYPE only, never message text), `_looks_like_network_error` (l.1854-1877: excludes `BadRequest`/`InvalidToken`/`Forbidden`/`RetryAfter`, includes `NetworkError`/`TimedOut`/`ConnectionError`/`OSError`), `_looks_like_connect_timeout` (l.1879-1892), `_looks_like_pool_timeout` (l.1894-1914), `_is_bad_request_error` (l.1729-1738), `_is_thread_not_found_error` (l.1684-1686). All timeout classifiers walk the full `__cause__`/`__context__` graph via `_iter_exception_graph` (l.96-119) with an identity-based cycle guard.
- **Inputs / options:** an exception. **Outputs / side effects:** booleans.
- **Config / env:** n/a.
- **Edge cases / guards:** A generic `TimedOut` may have reached Telegram, so it is NOT retried; a wrapped `ConnectTimeout` or `PoolTimeout` is explicitly "not sent" and therefore safe to retry.
- **Rebuild notes:** Classify by exception type and by the wrapped cause chain; never by message text for auth.

### Fatal-error surfacing and handoff  `id: platform-telegram.fatal-errors`
- **Surface:** Core
- **Where:** `hermes gateway status`, gateway logs, and the runner's reconnect decision.
- **What it does:** Distinguishes permanently broken credentials from transient failures so the gateway stops retrying a dead token.
- **How it works:** `adapter.py:5039-5060`. `_looks_like_auth_error` → fatal code **`telegram_auth_error`**, retryable=False, message "Telegram bot token rejected: {err}. The token is invalid or was revoked — generate a new one with @BotFather and update TELEGRAM_BOT_TOKEN." Otherwise fatal code **`telegram_connect_error`**, retryable=True, message "Telegram startup failed: {err}". Other codes: `missing_dependency` ("python-telegram-bot not installed"), `missing_credentials` ("No bot token configured"), `telegram_polling_conflict`, `telegram_network_error`. `_set_fatal_error` (`adapter.py:914-930`) also sets `_drop_delayed_deliveries` and, on a non-retryable fatal, clears the held-inbound queue with "[Telegram] Non-retryable fatal ({code}); discarding {n} held inbound message(s)". `_handoff_polling_fatal_error` (`adapter.py:3819-3834`) detaches the current task from the tracked fields so teardown cannot cancel the notifier.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Runner reconnect/shutdown decisions; status display.
- **Config / env:** n/a.
- **Edge cases / guards:** Every error string passes through `_redact_telegram_error_text` (`adapter.py:29-39`), which calls `agent.redact.redact_sensitive_text(text, force=True)` and, on failure, returns the literal `<telegram error redacted>` — so a bot token embedded in a URL never reaches logs.
- **Rebuild notes:** Two-axis error model (code + retryable) plus mandatory redaction of transport error text.

### Graceful disconnect  `id: platform-telegram.disconnect`
- **Surface:** Core
- **Where:** `hermes gateway stop`, restarts, adapter replacement; final log "Disconnected from Telegram".
- **What it does:** Tears the adapter down in a fixed order with per-step deadlines so no half-dead socket can hang shutdown.
- **How it works:** `adapter.py:5210-5361`. Order: `_mark_disconnected()` → set `_polling_teardown_started`, stop accepting progress, bump generation, set `_send_path_degraded` → release the token lock → cancel+await the polling error task and progress verifier (`_DISCONNECT_STEP_TIMEOUT = 2.0` s each) → cancel post-connect housekeeping → cancel the polling heartbeat → cancel the webhook identity-refresh loop → write the "Offline" status indicator → `_cancel_pending_delivery_tasks()` → `updater.stop()` (`_UPDATER_STOP_TIMEOUT = 15.0`) → `app.stop()` → `app.shutdown()` → null out `_app`/`_bot`. Each await goes through `_await_disconnect_step` (`adapter.py:5169-5208`), which detaches on timeout and logs "{step} timed out after {t}s during disconnect; continuing teardown".
- **Inputs / options:** n/a.
- **Outputs / side effects:** Cancels every background task; salvages buffered inbound events into the hold queue.
- **Config / env:** n/a.
- **Edge cases / guards:** `asyncio.wait` does not cancel its futures when itself cancelled, so an outer cancellation explicitly cancels the inner task before re-raising (#80598). Under a permanent fatal, pending batches are discarded with "[Telegram] Non-retryable fatal teardown; discarding {n} pending inbound batch(es)".
- **Rebuild notes:** Detach-on-timeout rather than cancel-and-wait, and release shared locks first.

### Held-inbound queue and redispatch  `id: platform-telegram.held-inbound`
- **Surface:** Core
- **Where:** Internal; logs "[Telegram] Holding inbound ({where}, {n} chars, queue={k}) - will redispatch on reconnect" and "[Telegram] Redispatching {n} held inbound message(s)".
- **What it does:** Preserves inbound messages that arrive during a disconnect window instead of silently dropping them (PTB has already advanced the polling offset, so Telegram never redelivers).
- **How it works:** `_hold_inbound_event` (`adapter.py:1035-1094`) appends to `_held_inbound_events` (cap `HELD_INBOUND_MAX = 64`, oldest dropped with "[Telegram] Held-inbound queue full ({max}); dropping oldest ({n} chars)"), dedupes by object identity. `_schedule_held_inbound_redispatch` (l.999-1033) owns exactly one tracked drain task. `_redispatch_held_inbound` (l.1096-1185) re-calls `handle_message` per event; on mid-drain disconnect/cancel/failure it re-holds the current event and the remainder with `where` values `redispatch-interrupted` / `redispatch-cancelled` / `redispatch-failed` (the failure path sets `allow_followup_schedule = False` to avoid a poison-event tight loop).
- **Inputs / options:** `where` labels used at 9 sites: `text-enqueue`, `text-flush`, `text-flush-cancelled`, `photo-enqueue`, `photo-flush`, `photo-flush-cancelled`, `media-group-enqueue`, `media-group-flush`, `media-group-flush-cancelled`, plus teardown salvage labels `text-batch-teardown`, `photo-batch-teardown`, `media-group-teardown`.
- **Outputs / side effects:** Messages delivered late rather than lost.
- **Config / env:** n/a.
- **Edge cases / guards:** Permanent fatal discards instead of holding ("[Telegram] Discarding inbound under non-retryable fatal ({where}, {n} chars)"); drains never run while `_drop_delayed_deliveries` is set.
- **Rebuild notes:** Any adapter whose SDK acks updates before dispatch needs this queue. A better version would persist the queue to disk so a process crash does not lose it.

### Send-time reconnect wait / adapter replacement  `id: platform-telegram.send-reconnect-wait`
- **Surface:** Core
- **Where:** `send()` when the transport is momentarily down; logs "[telegram] Not connected — waiting for reconnection (up to 15s)" and "[telegram] Reconnected after {n}s".
- **What it does:** Holds a finished reply for up to 15 s across a transient drop instead of failing it into the delivery ledger for hours.
- **How it works:** `_wait_for_reconnection` (`adapter.py:953-983`) polls every `_RECONNECT_POLL_INTERVAL = 0.5` s up to `_RECONNECT_WAIT_SECONDS = 15.0`; `_replacement_telegram_adapter` (`adapter.py:938-951`) looks up `runner.adapters[Platform.TELEGRAM]` and, if the reconnect watcher installed a *different* live adapter, `send()` delegates to it.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Either a real send or `SendResult(success=False, error="Not connected", retryable=…)`. Log on failure: "[telegram] Still not connected after 15s".
- **Config / env:** n/a.
- **Edge cases / guards:** A permanent fatal short-circuits the wait and returns `retryable=False`.
- **Rebuild notes:** Look up the live adapter through the runner registry, not only `self`.

### Bot identity tracking (BotFather rename)  `id: platform-telegram.bot-identity`
- **Surface:** Core
- **Where:** Affects every mention/routing comparison; logs "Telegram bot username changed: @old -> @new (mention routing now follows the new handle)".
- **What it does:** Keeps the bot's live `@username` current so a rename in BotFather does not silently break mention routing until restart.
- **How it works:** `_current_bot_username` (`adapter.py:9110-9124`) prefers `_bot_username_observed` over PTB's `Bot.username` cache. `_note_bot_username` (l.9126-9141) records and logs changes. `_observe_bot_identity_from_message` (l.9143-9163) learns the handle from messages Telegram says the bot authored (`from_user` or `reply_to_message.from_user` with a matching bot id) — trusted only on id match. `_refresh_bot_identity(force=…)` (l.9178-9201) calls `get_me()` bounded by `_BOT_IDENTITY_PROBE_TIMEOUT = 15.0`, TTL-guarded by `_BOT_IDENTITY_TTL_SECONDS = 300.0` via `_bot_identity_is_fresh`. `_schedule_bot_identity_recheck` (l.9350-9375) fires a background refresh exactly when routing is about to discard a message whose explicit bot mentions exclude us. Webhook mode runs `_bot_identity_refresh_loop` (l.4139-4161) every TTL; polling mode rides the heartbeat's `get_me()`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Updated `_bot_username_observed`, `_bot_identity_checked_at`.
- **Config / env:** n/a.
- **Edge cases / guards:** `_bot_identity_checked_at` is `None` (never `0.0`) when unchecked, because monotonic clocks on a freshly booted host start near zero and `0.0` would read as "just checked". Docs: "Renaming the bot's `@username` in BotFather is picked up automatically … Collectible (Fragment) usernames that don't end in `bot` are supported too."
- **Rebuild notes:** Observe identity from the update stream first, probe only on a TTL and on routing misses.

### Online/Offline status indicator  `id: platform-telegram.status-indicator`
- **Surface:** Config
- **Where:** The bot's **short description** (the line under its name on its profile page); log "Set bot status indicator to '{text}'".
- **What it does:** Because Bot API exposes no presence dot for bots, Hermes writes "Online" on connect and "Offline" on clean shutdown into the bot's short description.
- **How it works:** `adapter.py:5062-5089` `_set_status_indicator(online)` calls `bot.set_my_short_description(short_description=text[:120])`. Enabled by `extra.status_indicator`; texts from `extra.status_online` (default `"Online"`) and `extra.status_offline` (default `"Offline"`) — read in `__init__` at `adapter.py:842-850`. Invoked from post-connect housekeeping (online) and from `disconnect()` (offline).
- **Inputs / options:** `platforms.telegram.extra.status_indicator` (bool, default false), `.status_online` (string), `.status_offline` (string). Doc example uses `status_online: "🟢 Online"` / `status_offline: "🔴 Offline"`.
- **Outputs / side effects:** Mutates the bot's **global** profile, visible to every user.
- **Config / env:** as listed.
- **Edge cases / guards:** Truncated to Telegram's 120-char short-description cap; all failures swallowed at debug level; a hard crash leaves the last-known status (documented limitation); off by default because it is a global mutation.
- **Rebuild notes:** Use the only writable profile field as a presence proxy, cap it, and make it opt-in.

### Post-connect housekeeping task  `id: platform-telegram.post-connect`
- **Surface:** Core
- **Where:** Background task started right after connect returns.
- **What it does:** Moves the three slow Bot API calls (command-menu registration, status indicator, DM-topic setup) off the connect path so a stalled call cannot blow the gateway connect timeout (#46298).
- **How it works:** `_start_post_connect_housekeeping` (`adapter.py:4163-4174`, idempotent) → `_run_post_connect_housekeeping` (l.4176-4250). Each step is individually try/excepted and non-fatal.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `setMyCommands` for three scopes, `setMyShortDescription`, `createForumTopic` per configured DM topic.
- **Config / env:** n/a.
- **Edge cases / guards:** Cancelled during `disconnect()` with step name "post-connect cancel"; `CancelledError` re-raised.
- **Rebuild notes:** Connect should return as soon as the transport is up; everything cosmetic belongs in a cancellable follow-up task.

---

## 3. Command menu, inline picker and handler registration

### Bot command menu registration (`setMyCommands`)  `id: platform-telegram.command-menu`
- **Surface:** Gateway/Telegram
- **Where:** The `/` button in every Telegram chat with the bot; log "set_my_commands OK for scope {Scope} ({n} cmds)".
- **What it does:** Publishes Hermes' slash commands to Telegram's autocomplete menu on every gateway connect, for three scopes at once.
- **How it works:** `adapter.py:4184-4227`. Imports `BotCommand`, `BotCommandScopeAllPrivateChats`, `BotCommandScopeAllGroupChats`, `BotCommandScopeDefault`; builds the list via `hermes_cli.commands.telegram_menu_commands(max_commands=telegram_menu_max_commands())`; calls `bot.set_my_commands(bot_commands, scope=scope_cls())` for **`BotCommandScopeDefault`**, **`BotCommandScopeAllPrivateChats`** and **`BotCommandScopeAllGroupChats`** independently (Telegram picks the narrowest matching scope per chat).
- **Inputs / options:** none at runtime; shaped by `platforms.telegram.extra.command_menu`.
- **Outputs / side effects:** Overwrites the bot's command menu at Telegram. Per-scope failure logs "set_my_commands FAILED for scope {Scope}: {err}"; overflow logs "Telegram menu: {n} commands registered, {h} hidden (over {max} limit). Use /commands for full list."; a total failure logs "Could not register Telegram command menu: {err}".
- **Config / env:** `platforms.telegram.extra.command_menu.{max_commands,priority_mode,priority}`.
- **Edge cases / guards:** Telegram allows 100 BotCommands but has an undocumented ~4 KB payload limit; Hermes defaults to 60. Forum topics do not inherit `AllGroupChats` and are handled lazily (see next entry).
- **Rebuild notes:** Register all three scopes independently and tolerate per-scope failures; derive the list from one central registry so new commands appear automatically.

### Telegram menu command builder and cap  `id: platform-telegram.menu-builder`
- **Surface:** Config | Core
- **Where:** `platforms.telegram.extra.command_menu` in `~/.hermes/config.yaml`.
- **What it does:** Selects, sanitizes, prioritizes and caps the command list that goes into the Telegram menu.
- **How it works:** `hermes_cli/commands.py`. `telegram_bot_commands(include_plugins=True)` (l.719-752) walks `COMMAND_REGISTRY`, skips aliases, keeps arg-taking built-ins (their handlers print usage), excludes arg-requiring *plugin* commands, and sanitizes names. `_sanitize_telegram_name` (l.952-964): lowercase → `-`→`_` → strip anything outside `[a-z0-9_]` → collapse `_{2,}` → strip leading/trailing `_`; `_CMD_NAME_LIMIT = 32` with collision-avoiding truncation (`_clamp_command_names`, l.966+: truncate to 32, on collision use 31 chars + digit `0`-`9`, drop after 10 collisions). `telegram_menu_commands(max_commands)` (l.1157-1195) combines core commands (`source="core"`), plugin commands, and skill commands from `_collect_gateway_skill_entries(platform="telegram", max_slots=None, reserved_names=…, desc_limit=40, sanitize_name=…)`, applies `_prioritize_telegram_menu_candidates`, cuts to the cap, and returns `(menu, hidden_count + overflow_count)`.
- **Inputs / options:** `command_menu.max_commands` (int, default **60**, clamped to `1..100`), `command_menu.priority_mode` ∈ {`prepend` (default), `append`, `replace`}, `command_menu.priority` (list of command names, or a single string). Built-in priority list `_TELEGRAM_MENU_PRIORITY` (l.764-792), in order: `help`, `new`, `stop`, `status`, `egress`, `resume`, `sessions`, `model`, `debug`, `restart`, `update`, `verbose`, `commands`, `approve`, `deny`, `queue`, `steer`, `bg`, `btw`, `reasoning`, `usage`, `platforms`, `platform`, `profile`, `whoami`.
- **Outputs / side effects:** The published menu; `hidden_count` reported in the log.
- **Config / env:** `platforms.telegram.extra.command_menu.*`.
- **Edge cases / guards:** Ranking (`_prioritize_telegram_menu_candidates`, l.885-950) is a 3-tuple sort `(tier, index, stable_index)` whose tiers differ per mode: `replace` → configured first then everything; `append` → core defaults, then configured, then rest; `prepend` (default) → configured, then core defaults, then rest. Priority is matched against both the raw and the clamped name so a configured long command survives clamping. User-installed hub skills are excluded (reachable via `/skills`); skills disabled for platform `"telegram"` via `hermes skills config` are excluded entirely. Docs note that before this change skills were always trimmed first and alphabetically.
- **Rebuild notes:** Single ranked candidate list (core+plugin+skill) with a configurable priority overlay applied *before* the cap. A better version would let the menu differ per scope (DM vs group).

### Lazy command registration for forum supergroups  `id: platform-telegram.forum-commands`
- **Surface:** Gateway/Telegram
- **Where:** First message received from any forum supergroup; log "Lazy-registered {n} commands for forum chat {chat_id}".
- **What it does:** Registers the command menu with `BotCommandScopeChat(chat_id)` because Telegram forum topics do not inherit the `AllGroupChats` scope.
- **How it works:** `_ensure_forum_commands` (`adapter.py:9873-9896`), guarded by `self._forum_lock` (an `asyncio.Lock`) and memoized in `self._forum_command_registered: set[int]`. Called from `_handle_text_message` and `_handle_command`.
- **Inputs / options:** n/a (triggered by `chat.is_forum`).
- **Outputs / side effects:** One `setMyCommands` per forum chat per gateway lifetime.
- **Config / env:** same `command_menu` config.
- **Edge cases / guards:** Failure logs "Forum command lazy-registration failed: {err}" and is non-fatal; non-forum chats return immediately.
- **Rebuild notes:** Cache the per-chat registration; do it lazily so a bot in 200 forums does not make 200 API calls at boot.

### Inline command picker (`@botname <query>`)  `id: platform-telegram.inline-picker`
- **Surface:** Gateway/Telegram
- **Where:** Type `@yourbotname ` followed by a search term in ANY Telegram chat (even ones the bot is not in).
- **What it does:** Gives uncapped, searchable access to every Hermes command and installed skill; tapping a result sends the command text as the user.
- **How it works:** `adapter.py:7305-7390` `_handle_inline_query` + `plugins/platforms/telegram/inline_picker.py`. `collect_inline_catalog()` (l.42-93) merges `telegram_bot_commands()` (core, deduped first) with `_collect_gateway_skill_entries(platform="telegram", max_slots=None, reserved_names=…, desc_limit=100, sanitize_name=_sanitize_telegram_name)`. `filter_catalog()` (l.96-119) ranks prefix-match > name-substring > description-substring, treating `-` and `_` as equivalent and stripping a leading `/`; an empty term returns the browse view in collection order. `build_inline_results(query, offset, page_size=50)` (l.122-166) splits the query on the first whitespace: token 0 filters, the remainder becomes the command's argument. Each result dict is `{"id": f"{start}:{name}"[:64], "title": f"/{name}", "description": desc[:100], "message_text": f"/{name} {args}"[:4096]}`; the adapter converts them into `InlineQueryResultArticle(id, title, description, input_message_content=InputTextMessageContent(message_text))` and calls `inline_query.answer(articles, cache_time=10, is_personal=True, next_offset=…)`.
- **Inputs / options:** the typed query; Telegram's `offset` string for pagination. Constants: `PAGE_SIZE = 50` (Telegram's per-answer max), `CACHE_TIME_SECONDS = 10`.
- **Outputs / side effects:** Tapping a result sends a normal `/command …` message from the user, which dispatches through the standard command path — the handler only ever *offers* text, so it is read-only by construction.
- **Config / env:** none; requires BotFather `/setinline` once.
- **Edge cases / guards:** Unauthorized users get an empty answer (`inline_query.answer([], cache_time=10, is_personal=True)`) so the installed-skill catalog is not leaked — inline queries arrive from any chat. Authorization reuses `_is_callback_user_authorized(user_id, chat_id=user_id, chat_type="private", user_name=…)`. `is_personal=True` prevents Telegram from sharing cached pages across users. `next_offset=""` is Telegram's stop signal. Any exception is swallowed at debug ("inline picker answer failed" / "inline picker empty answer failed" / "inline picker auth check failed").
- **Rebuild notes:** Compute results per keystroke from the live registry, paginate with an integer offset in the opaque cursor, mark results personal, and return an empty list for unauthorized users. A better version would rank by recent usage and show the skill's source (core/plugin/skill) in the description.

### BotFather `/setinline` prerequisite  `id: platform-telegram.setinline`
- **Surface:** Docs
- **Where:** `telegram.md:110-124` — "Inline command picker: search every command (no cap)".
- **What it does:** Documents the one-time enablement of inline mode.
- **How it works:** "**One-time setup:** inline mode is off by default for every Telegram bot. Enable it in [@BotFather](https://t.me/BotFather) with `/setinline` (pick your bot, set any placeholder text, e.g. `Search commands and skills...`). Until then, Telegram never delivers inline queries and the picker stays inert." Examples given: `@yourbotname plan            → tap the /plan result to send it`, `@yourbotname plan migrate auth to OIDC   → sends /plan migrate auth to OIDC`, `@yourbotname pdf             → finds skills matching "pdf" by name or description`.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** The `InlineQueryHandler` is registered unconditionally because it is inert until Telegram delivers `inline_query` updates.
- **Rebuild notes:** n/a.

### PTB handler registration  `id: platform-telegram.handlers`
- **Surface:** Core
- **Where:** Internal — single registration site used by both first connect and the transient-init rebuild.
- **What it does:** Wires every update type to its Hermes handler in a deterministic order.
- **How it works:** `_register_handlers(app)` (`adapter.py:4434-4468`) registers, in order: `MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text_message)`; `MessageHandler(filters.COMMAND, _handle_command)`; `MessageHandler(filters.LOCATION | filters.VENUE (falling back to LOCATION), _handle_location_message)`; `MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.Sticker.ALL, _handle_media_message)`; `CallbackQueryHandler(_handle_callback_query)`; `InlineQueryHandler(_handle_inline_query)`; and `TypeHandler(Update, _on_platform_update)` in **group=99**. Plugin-provided handlers are wired BEFORE the core ones via `self._wire_plugin_handlers(self._app)` (`adapter.py:4736`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Update dispatch.
- **Config / env:** n/a.
- **Edge cases / guards:** Group 99 keeps the platform-event observer alongside, never displacing, the core handlers (#64176). PTB dispatches only the first matching handler per group, so pattern-scoped plugin handlers take precedence for their own updates.
- **Rebuild notes:** One registration function called from every code path that builds an Application, so a rebuild cannot lose a handler.

### Plugin-provided Telegram handlers  `id: platform-telegram.plugin-handlers`
- **Surface:** Core
- **Where:** Plugins call `ctx.register_telegram_handler(...)` (alias of `ctx.register_platform_handler("telegram", ...)`).
- **What it does:** Lets a plugin install its own python-telegram-bot handlers (e.g. pattern-scoped `CallbackQueryHandler`s) ahead of the core handlers.
- **How it works:** `adapter.py:4729-4736`. Factories receive `(application, adapter)`.
- **Inputs / options:** handler factory callables.
- **Outputs / side effects:** Extra handlers on the PTB Application.
- **Config / env:** n/a.
- **Edge cases / guards:** Because PTB dispatches the first matching handler in a group, an over-broad plugin handler can swallow core traffic.
- **Rebuild notes:** Register extension handlers first but require them to be pattern-scoped.

### `gateway_platform_event` observer (reactions, edits)  `id: platform-telegram.platform-event`
- **Surface:** Core
- **Where:** Fires the `gateway_platform_event` lifecycle hook for plugins.
- **What it does:** Normalizes selected inbound Telegram updates into an SDK-free envelope and hands them to the gateway-owned post-auth boundary.
- **How it works:** `_on_platform_update` (`adapter.py:4252-4286`) returns early unless `hermes_cli.lifecycle.has_hook("gateway_platform_event")`. `_normalize_platform_event` (l.4315-4329) supports exactly two types today: `message_reaction` → `_normalize_reaction_event` (l.4331-4380) producing `{"platform": "telegram", "event_type": "reaction", "payload": {"emojis": [...≤64 items, each ≤64 chars], "custom_emoji_ids": [...≤128 chars], "chat_id": str[:128], "message_id": str[:128], "thread_id": None}}`; `edited_message` → `_normalize_message_edited_event` (l.4382-4432) producing `{"event_type": "message_edited", "payload": {"chat_id", "message_id", "thread_id" (only when `is_topic_message`), "text" (text or caption, ≤8192 chars), "edited_at" (ISO 8601, ≤64 chars)}}`. Auth sources come from `_source_for_platform_event_auth` (l.4288-4313) → `_source_from_reaction_for_auth` (l.1314-1366) or `_source_from_message_for_auth`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Plugin hook invocation.
- **Config / env:** n/a.
- **Edge cases / guards:** Every unsupported update type returns `None`; missing actor/chat/message identities raise `ValueError` so the post-auth boundary fails closed; raw PTB objects never leave the boundary; all exceptions are swallowed at debug ("gateway_platform_event normalize error" / "gateway_platform_event dispatch error").
- **Rebuild notes:** Normalize to a versioned, additive payload contract per event type and authorize before dispatch.

---

## 4. Outbound messaging

### `send()` — MarkdownV2 message delivery with chunking  `id: platform-telegram.send`
- **Surface:** Core
- **Where:** Every agent reply, tool-progress bubble and notification in Telegram.
- **What it does:** Formats the agent's markdown to Telegram MarkdownV2, splits it at 4 096 UTF-16 code units, sends each chunk with topic/reply routing, and retries transport failures.
- **How it works:** `adapter.py:5383-5738`. Order: (1) not-connected → replacement adapter / reconnect wait; (2) `_send_path_degraded` → `SendResult(success=False, error="send_path_degraded", retryable=True)`; (3) whitespace-only content → `SendResult(success=True, message_id=None)` (avoids Telegram 400 empty-text); (4) rich fast path (`_should_attempt_rich`); (5) `format_message()` then `truncate_message(formatted, 4096, len_fn=utf16_len)`; chunk indicators ` (1/2)` are re-escaped to ` \(1/2\)` and moved off code-fence lines; (6) per chunk, compute reply/thread routing, then `bot.send_message(chat_id=normalize_telegram_chat_id(chat_id), text=chunk, parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=…, **thread_kwargs, **link_preview_kwargs, **notification_kwargs)`; on a parse/markdown error retry the same chunk as `_strip_mdv2(chunk)` with `parse_mode=None`; (7) re-trigger typing unless this is the final reply.
- **Inputs / options:** `chat_id`, `content`, `reply_to`, `metadata` (`thread_id` / `message_thread_id`, `direct_messages_topic_id` / `telegram_direct_messages_topic_id`, `telegram_reply_to_message_id`, `telegram_dm_topic_reply_fallback`, `telegram_dm_topic_created_for_send`, `notify`, `expect_edits`).
- **Outputs / side effects:** `SendResult(success=True, message_id=<first id>, raw_response={"message_ids": [...], "requested_thread_id": …, "thread_fallback": bool})`. Class constants: `MAX_MESSAGE_LENGTH = 4096`, `supports_code_blocks = True`, `splits_long_messages = True`, `message_len_fn = utf16_len`.
- **Config / env:** `platforms.telegram.extra.disable_link_previews`, `display.platforms.telegram.notifications`, `reply_to_mode`.
- **Edge cases / guards:** Inner retry loop runs 3 attempts with 1 s/2 s backoff for network errors; `TimedOut` is not retried unless it wraps a ConnectTimeout or PoolTimeout; a pool timeout drains the general pool first; `message_too_long` returns `SendResult(success=False, error="message_too_long", error_kind="too_long")` so the stream consumer takes over; flood control caps inline sleeping at `_FLOOD_INLINE_WAIT_CAP_SECS = 5.0` and otherwise returns `SendResult(success=False, error=f"flood_control:{wait}", retry_after=wait)` (a 97-minute penalty once froze inbound on every platform, #91969); "Thread {id} not found" is retried once with the same thread id, then without `message_thread_id` after pruning the stale binding; "message to be replied not found" drops the reply anchor (and, for DM-topic fallback sends, the topic id too).
- **Rebuild notes:** Chunk by UTF-16 length, escape chunk indicators, retry markdown→plain once, and separate "not sent" timeouts from "maybe sent" timeouts. A better version would batch chunks into one album-like flow and expose per-chunk ids to the caller.

### `format_message()` — Markdown → Telegram MarkdownV2  `id: platform-telegram.format-message`
- **Surface:** Core
- **Where:** Applied to every non-rich outgoing message, edit, caption and picker title.
- **What it does:** Converts the agent's standard Markdown into Telegram MarkdownV2, protecting code spans and escaping every reserved character.
- **How it works:** `adapter.py:8712-8882`, 12 numbered steps: (0) `convert_table_to_bullets()` rewrites GFM pipe tables; (1) protect fenced blocks ```` ```lang\n…``` ```` (escaping `\` and `` ` `` inside per spec) behind `\x00PH{n}\x00` placeholders; (2) protect inline `` `code` `` (escaping `\`); (3) convert `[text](url)` — display escaped, URL only escapes `)` and `\`; (4) `#{1,6} Title` → `*Title*` (stripping redundant `**` inside); (5) `**bold**` → `*bold*`; (6) `*italic*` → `_italic_` using `[^*\n]+` so bullet lists are safe; (7) `~~strike~~` → `~strike~`; (8) `||spoiler||` preserved; (9) blockquotes `^((?:\*\*)?>{1,3}) (.+)$` preserved, with expandable-quote handling when the prefix starts with `**` and the content ends with `||`; (10) escape everything remaining with `_MDV2_ESCAPE_RE = ([_*\[\]()~\`>#\+\-=|{}.!\\])`; (11) restore placeholders in reverse insertion order (nested placeholders resolve correctly); (12) safety net that escapes bare `( ) { }` outside code spans, skipping already-escaped chars, the `(` of a link, and the `)` closing a link URL (depth-scanned up to 2 000 chars back).
- **Inputs / options:** `content: str`.
- **Outputs / side effects:** MarkdownV2 string.
- **Config / env:** n/a.
- **Edge cases / guards:** `_strip_mdv2` (`adapter.py:433-457`) is the inverse used on fallback: removes escape backslashes, `**bold**`, `*bold*`, `_italic_` (word-boundary guarded so `snake_case` survives), `~strike~`, `||spoiler||`. `_separate_chunk_indicator_from_fence` (l.460-472) moves a ``` ``` \(1/2\)``` indicator onto its own line after the closing fence so Telegram still parses MarkdownV2.
- **Rebuild notes:** Placeholder-protect code first, convert constructs, escape the remainder, restore in reverse order, then run a bracket safety net. A better version would emit HTML (fewer escaping traps) or use entity offsets directly.

### Markdown table normalization  `id: platform-telegram.tables`
- **Surface:** Core
- **Where:** Any agent reply containing a GFM pipe table on the MarkdownV2 path.
- **What it does:** Rewrites pipe tables into readable bullet groups (or an aligned fenced code block for wide tables) because MarkdownV2 has no table syntax.
- **How it works:** Imported at `adapter.py:487-491` from `gateway.platforms.helpers` as `_wrap_markdown_tables = convert_table_to_bullets` (`gateway/platforms/helpers.py:379-419`): walks lines, skips fenced regions, detects a header row followed by a `TABLE_SEPARATOR_RE` delimiter, collects contiguous `is_table_row` lines, and replaces the block with `_render_table_block(...)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Docs describe the two shapes: "**Small tables** are flattened into **row-group bullets** — each row becomes a readable bulleted list under the column headings. Good for 2–4 columns and short cells." and "**Larger or wider tables** fall back to a **fenced code block** with aligned columns so nothing collapses."
- **Config / env:** Documented toggle `telegram.pretty_tables: false` (default `true`) to force the always-code-block behaviour (`telegram.md:1001`).
- **Edge cases / guards:** Tables inside fenced code blocks are left alone; when the rich path is used the table is sent as raw markdown instead and renders natively.
- **Rebuild notes:** Detect header+delimiter+rows, choose bullets vs code block by column count/width.

### `edit_message()` — streaming edits and finalization  `id: platform-telegram.edit-message`
- **Surface:** Core
- **Where:** Progressive streaming updates and the final formatted reply.
- **What it does:** Edits a previously sent message; mid-stream edits are plain text, the finalize edit applies MarkdownV2 (or rich), and oversized content is split across continuation messages.
- **How it works:** `adapter.py:5774-5975`. `finalize=True` + rich-eligible → `_try_edit_rich` first. Pre-flight: if `utf16_len(content) > 4096` and `finalize` → `_edit_overflow_split`; if not finalize → truncate to one chunk and dedupe against `_last_overflow_preview[(chat_id, message_id)]`. Non-finalize edits call `edit_message_text(text=content)` with no parse mode; finalize edits call it with `parse_mode=ParseMode.MARKDOWN_V2` on `format_message(content)` and fall back to `_strip_mdv2(content)` plain text on a formatting error.
- **Inputs / options:** `chat_id`, `message_id`, `content`, `finalize` (bool), `metadata`.
- **Outputs / side effects:** `SendResult(success=True, message_id=…)`, possibly with `continuation_message_ids`.
- **Config / env:** n/a.
- **Edge cases / guards:** `"Message is not modified"` is treated as success everywhere. Class flags: `REQUIRES_EDIT_FINALIZE = True` (so the stream consumer does not short-circuit an unchanged final edit and skip MarkdownV2 conversion, #25710); `FALLBACK_ON_FINAL_EDIT_FLOOD = True` (a flood on the final edit goes straight to the fallback path); `RESEND_FINAL_ON_EMPTY_STREAM_FALLBACK = True` (empty-tail fallbacks are committed as a fresh final message). Flood control: waits inline up to 5 s ("Telegram flood control, waiting {n}s"), otherwise returns the `flood_control:{wait}` failure. Transient markers that mark a failure retryable: `connecterror`, `connect error`, `connection error`, `networkerror`, `network error`, `timed out`, `readtimeout`, `writetimeout`, `server disconnected`, `temporarily unavailable`, `temporary failure`, `httpx`.
- **Rebuild notes:** Mid-stream edits must never split (splitting moves the edit target and causes infinite duplication, #48648); only the final edit splits.

### Saturated-preview deduplication  `id: platform-telegram.overflow-dedup`
- **Surface:** Core
- **Where:** Long streaming replies past the 4 096-char preview cap.
- **What it does:** Stops re-sending an identical truncated preview once a stream saturates the cap, so Telegram's flood budget is not burned on visual no-ops.
- **How it works:** `adapter.py:5820-5845` and `5901-5912`. `_last_overflow_preview: Dict[(chat_id, message_id), str]`; when the truncated text equals the cached value the method returns `SendResult(success=True, message_id=message_id)` without an API call. The entry is popped on `finalize` and when content shrinks back under the cap.
- **Inputs / options:** n/a. **Outputs / side effects:** fewer Bot API calls.
- **Config / env:** n/a.
- **Edge cases / guards:** Without it, ~1 edit/0.8 s for the rest of a long stream trips flood control with 200 s+ penalties and hangs final delivery.
- **Rebuild notes:** Cache the last rendered preview per (chat, message) and skip identical writes.

### Oversized-edit split into continuation messages  `id: platform-telegram.overflow-split`
- **Surface:** Core
- **Where:** Final replies longer than 4 096 UTF-16 units delivered through the edit path.
- **What it does:** Edits the existing message with chunk 1 and posts the rest as replies chained to the previous chunk, so the user sees one contiguous block.
- **How it works:** `_edit_overflow_split` (`adapter.py:5992-6192`). Chunk 1 via `edit_message_text` (MarkdownV2 with plain fallback on finalize); each remaining chunk via `bot.send_message` with `reply_to_message_id=<previous chunk>` and the same thread/link-preview/notification kwargs, trying `(True, False)` for MarkdownV2-then-plain when finalizing (streaming previews stay raw). Returns `SendResult(success=True, message_id=<last chunk id>, continuation_message_ids=(...))`.
- **Inputs / options:** `chat_id`, `message_id`, `content`, `finalize`, `metadata`.
- **Outputs / side effects:** Multiple new Telegram messages; debug log "Overflow split delivered {n} chunks; last_id={id}".
- **Config / env:** n/a.
- **Edge cases / guards:** `"reply message not found"` retries once without the anchor (dropping the topic id too for DM-topic fallback sends). A failed continuation returns `SendResult(success=False, message_id=<last delivered>, error="overflow_continuation_failed", retryable=True, raw_response={"partial_overflow": True, "delivered_chunks": n, "total_chunks": m, "last_message_id": …, "delivered_prefix": …, "continuation_message_ids": (...)})` so the gateway knows exactly how much of the answer landed; log "Overflow split: stopped at {n}/{m} chunks delivered". A failure on the FIRST chunk returns a plain failure.
- **Rebuild notes:** Report partial delivery explicitly (delivered prefix + ids) instead of a boolean.

### `send_or_update_status()` — status bubbles edited in place  `id: platform-telegram.status-bubble`
- **Surface:** Core
- **Where:** Recurring agent status callbacks ("Compressing context…", "Calling tool…").
- **What it does:** Keeps one message per `(chat_id, status_key)` and edits it instead of appending a new bubble every time.
- **How it works:** `adapter.py:5740-5772`. `_status_message_ids: Dict[(chat_id, status_key), message_id]`; first call sends and caches, later calls `edit_message(..., finalize=True)`; a failed edit drops the cache entry and sends fresh, re-caching the new id (#30045).
- **Inputs / options:** `chat_id`, `status_key`, `content`, `metadata`.
- **Outputs / side effects:** One durable bubble per status key.
- **Config / env:** none — documented as "No config required — this is the default Telegram behavior."
- **Edge cases / guards:** Distinct `status_key` values get their own messages; distinct chats never collide; adapters without this method fall through to plain `send()`.
- **Rebuild notes:** Key the cache by (chat, semantic key) and treat an edit failure as a cache miss.

### `delete_message()`  `id: platform-telegram.delete-message`
- **Surface:** Core
- **Where:** Stream consumer's fresh-final cleanup (removing a stale preview after the completed reply is re-sent).
- **What it does:** Deletes a bot-posted message.
- **How it works:** `adapter.py:6194-6217` → `bot.delete_message(chat_id=normalize_telegram_chat_id(chat_id), message_id=int(message_id))`; returns bool.
- **Inputs / options:** `chat_id`, `message_id`. **Outputs / side effects:** message removed.
- **Config / env:** n/a.
- **Edge cases / guards:** Bot API allows deleting bot messages for 48 hours; failures are non-fatal and logged at debug ("Failed to delete Telegram message {id}: {err}").
- **Rebuild notes:** n/a.

### Native draft streaming (`sendMessageDraft`)  `id: platform-telegram.draft-streaming`
- **Surface:** Core | Config
- **Where:** DMs only; controlled by `gateway.streaming.transport`.
- **What it does:** Streams the in-progress reply as Telegram's animated ephemeral draft preview rather than editing a real message.
- **How it works:** `supports_draft_streaming(chat_type, metadata)` (`adapter.py:6219-6244`) returns True only when `self._bot` exposes `send_message_draft` (PTB ≥ 22.6) and `chat_type` ∈ {`dm`, `private`} — Bot API 9.5 restricts drafts to private chats. `send_draft(chat_id, draft_id, content, metadata)` (l.6246-6343): rich draft fast path first, then trim to 4 096, then try `(True, False)` MarkdownV2→plain, calling `bot.send_message_draft(chat_id=…, draft_id=int(draft_id), text=…, parse_mode=…, **thread_kwargs)`. Reusing the same `draft_id` animates the preview.
- **Inputs / options:** `gateway.streaming.enabled` (bool) and `gateway.streaming.transport` ∈ {**`auto`** (default: drafts on supported chats, edit elsewhere), **`draft`** (force drafts, log a downgrade and fall back for groups/topics), **`edit`** (legacy progressive `editMessageText` everywhere), **`off`** (no progressive updates)}.
- **Outputs / side effects:** `SendResult(success=True, message_id=None)` — drafts have no message id. Failure returns `SendResult(success=False, error="draft_rejected" | "api_unavailable" | <redacted error>)`.
- **Config / env:** `gateway.streaming.enabled`, `gateway.streaming.transport`.
- **Edge cases / guards:** A `BadRequest` on the MarkdownV2 attempt retries once as plain text; anything else propagates so the caller degrades to edit-based streaming for the rest of the response. When `rich_messages` is on but `rich_drafts` is off and the text needs rich rendering, the draft is sent RAW (`draft_modes = (False,)`) so the legacy formatter does not flatten tables in the preview. Telegram has no API to promote a draft into a message — the final `sendMessage`/`sendRichMessage` is what persists.
- **Rebuild notes:** Treat drafts as ephemeral frames with no ids; degrade per response, not per frame, on hard failures.

### Rich Messages (Bot API 10.1 `sendRichMessage`)  `id: platform-telegram.rich-messages`
- **Surface:** Config | Core
- **Where:** `platforms.telegram.extra.rich_messages: true`.
- **What it does:** Sends the agent's RAW markdown through Telegram's native rich-message endpoint so tables, task lists, `<details>` and block math render natively instead of being degraded.
- **How it works:** `_try_send_rich` (`adapter.py:2234-2339`) posts `bot.do_api_request("sendRichMessage", api_kwargs={"chat_id": …, "rich_message": {"markdown": …}, …})`. `_rich_message_payload` (l.2134-2149) builds `InputRichMessage` from raw markdown after `_rich_normalize_linebreaks` (l.506-... ) converts single `\n` into Markdown hard breaks (two trailing spaces) everywhere except protected regions matched by `_RICH_PROTECTED_REGION_RE` (fenced code blocks and GFM pipe-table blocks). Reply anchors use `reply_parameters={"message_id": id}` (the legacy scalar is silently ignored by the API). Successful sends record the raw content in `gateway.rich_sent_store` keyed by (chat_id, message_id).
- **Inputs / options:** `extra.rich_messages` (default **false**), `extra.rich_drafts` (default **false**).
- **Outputs / side effects:** A natively rendered message; `SendResult(success=True, message_id=…)`.
- **Config / env:** `platforms.telegram.extra.rich_messages`, `.rich_drafts`; system-prompt side effect via `TELEGRAM_RICH_MESSAGES_HINT`.
- **Edge cases / guards:** Eligibility (`_rich_eligible`, l.2063-2082) requires: enabled, not latched off, non-empty content, `_needs_rich_rendering(content)` true, NOT a TDesktop crash shape, NOT a CJK garble shape, ≤ `RICH_MESSAGE_MAX_CHARS = 32768`, and `_bot_supports_rich()` (i.e. `do_api_request` is a coroutine function). `_should_attempt_rich` additionally requires `metadata["expect_edits"]` to be falsy. `_needs_rich_rendering` (l.2037-2057) triggers only on: a table separator line, a GFM task list `^\s*[-*]\s+\[[ xX]\]\s+`, a `<details>`/`<summary>` line, or `$$` block math — ordinary prose stays on MarkdownV2 for consistent font weight. `_has_telegram_desktop_details_math_crash_shape` (l.2011-2025) skips math inside `<details>` (crashes Telegram Desktop 6.9.1, tdesktop#30808). `_has_telegram_desktop_cjk_rich_garble_shape` (l.2027-2035) skips CJK content (Hiragana/Katakana `぀-ヿ`, CJK Ext-A `㐀-䶿`, CJK `一-鿿`, Hangul `가-힯`, CJK Compat `豈-﫿`, `\U00020000-\U000323af`) because TDesktop leaves overlapping draft glyph artifacts (#47653). `_is_rich_capability_error` (l.2151-2171) latches `_rich_send_disabled` on `EndpointNotFound`/`InvalidToken`/`AttributeError`/`TypeError`/`NotImplementedError`/HTTP 404/"method … not found"/"no such method". `_is_rich_fallback_error` (l.2173-2186) additionally accepts `BadRequest`, "unsupported", "not implemented". Transient/unknown errors return a failure with retry semantics and are NEVER legacy-resent (duplicate risk).
- **Rebuild notes:** Opt-in rich rendering, content-shape gating, per-client crash blocklists, and a strict "permanent → fall back / transient → fail" error contract. A better version would query client capabilities instead of hard-coded shape blocklists.

### Rich draft frames (`sendRichMessageDraft`)  `id: platform-telegram.rich-drafts`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.rich_drafts: true`.
- **What it does:** Renders the live streaming preview with the same rich markdown the final message will use.
- **How it works:** `_should_attempt_rich_draft` (`adapter.py:2421-2433`) and `_try_send_rich_draft` (l.2435-2471) → `bot.do_api_request("sendRichMessageDraft", api_kwargs={"chat_id", "draft_id", "rich_message", **thread_kwargs})`.
- **Inputs / options:** `extra.rich_drafts` (default false); requires `extra.rich_messages` true.
- **Outputs / side effects:** an animated rich preview frame; returns bool.
- **Config / env:** as listed.
- **Edge cases / guards:** Off by default because "Telegram macOS / Desktop can leave Bot API 10.1 rich draft frames visually overlaid until the chat is redrawn". A capability error latches `_rich_draft_disabled`; a transient error just falls back to the plain draft for that frame. When `rich_messages` is on and `rich_drafts` off, native draft *transport* is kept but rich *rendering* is skipped.
- **Rebuild notes:** Separate the transport decision from the rendering decision.

### Rich edit finalize (`editMessageText` + `rich_message`)  `id: platform-telegram.rich-edit`
- **Surface:** Core
- **Where:** Finalization of an edit-based stream whose content warrants rich rendering.
- **What it does:** Upgrades a plain streamed preview to a rich message in place, avoiding a fresh send + delete (which produced duplicate previews, #46206).
- **How it works:** `_try_edit_rich` (`adapter.py:2341-2419`) posts `editMessageText` with `{"chat_id", "message_id", "rich_message"}` and, when configured, `link_preview_options`. Topic routing keys are deliberately NOT forwarded (edits target chat+message; forwarding `message_thread_id`/`direct_messages_topic_id` makes Telegram reject the rich edit). Successful edits also record into `rich_sent_store`.
- **Inputs / options:** `chat_id`, `message_id`, `content`, `metadata`.
- **Outputs / side effects:** In-place rich rendering.
- **Config / env:** same as rich messages.
- **Edge cases / guards:** `"not modified"` is treated as success on both the permanent and transient branches. `prefers_fresh_final_streaming()` (l.2092-2113) returns True only for private DM-topic lanes (`telegram_dm_topic_reply_fallback` or an explicit `direct_messages_topic_id`) where Telegram rejects a rich edit of a plain preview — there a fresh `sendRichMessage` + preview delete is the only way to keep native tables. `streaming_overflow_limit()` (l.2115-2132) raises the stream-consumer accumulation cap from 4 096 to `RICH_MESSAGE_MAX_CHARS` when rich is available.
- **Rebuild notes:** Prefer in-place upgrade; only use send+delete where the API refuses the edit.

### Rich reply echo store  `id: platform-telegram.rich-sent-store`
- **Surface:** Core
- **Where:** Internal (`gateway/rich_sent_store.py`), consumed when a user replies to a rich message.
- **What it does:** Remembers the raw markdown of every rich message Hermes sent so a reply to it can carry the quoted text into the agent's context, since Telegram does not echo rich content in `reply_to_message`.
- **How it works:** `rich_sent_store.record(chat_id, message_id, content)` at `adapter.py:2331-2335` and `2414-2418`; `rich_sent_store.lookup(chat_id, reply_to_id)` at `adapter.py:10918-10924` as the last fallback after `_extract_rich_reply_text`.
- **Inputs / options:** n/a. **Outputs / side effects:** a persisted map.
- **Config / env:** n/a.
- **Edge cases / guards:** Every call is wrapped in a bare `except Exception: pass`.
- **Rebuild notes:** Keep a send-time index of anything the platform will not echo back.

### Rich-message flattening of Telegram's own echo  `id: platform-telegram.rich-flatten`
- **Surface:** Core
- **Where:** Building the reply context for a message that replies to a rich message.
- **What it does:** Converts Telegram's structured `rich_message.blocks` echo back into plain text.
- **How it works:** `_extract_rich_reply_text` (`adapter.py:10764-10779`) reads `reply_to_message.api_kwargs["rich_message"]["blocks"]` and flattens with `_flatten_rich_blocks` (l.10728-10762 — handles `type: "list"` items with optional `label`, otherwise flattens `block["text"]`) and `_flatten_rich_inline_text` (l.10710-10726 — recurses through strings, lists, and dicts with `text`/`children`).
- **Inputs / options:** n/a. **Outputs / side effects:** plaintext or None.
- **Config / env:** n/a.
- **Edge cases / guards:** All failures return None; the local `rich_sent_store` is the fallback.
- **Rebuild notes:** n/a.

### Link-preview suppression  `id: platform-telegram.link-previews`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.disable_link_previews: true` (also bridged from `telegram.disable_link_previews`).
- **What it does:** Stops Telegram from auto-generating URL previews on every bot message.
- **How it works:** `_link_preview_kwargs` (`adapter.py:1950-1955`) returns `{"link_preview_options": LinkPreviewOptions(is_disabled=True)}` when the SDK exposes it, else the legacy `{"disable_web_page_preview": True}`. Applied to `send`, overflow continuations, all inline-keyboard sends, and rich payloads (`{"link_preview_options": {"is_disabled": True}}`).
- **Inputs / options:** boolean; coerced from strings `true/1/yes/on` / `false/0/no/off` by `_coerce_bool_extra` (l.1916-1927).
- **Outputs / side effects:** No preview cards.
- **Config / env:** `platforms.telegram.extra.disable_link_previews`; the standalone sender reads the same key.
- **Edge cases / guards:** Not applied to media sends (they have no preview).
- **Rebuild notes:** One helper returning kwargs, spread at every send site.

### Notification modes (`important` / `all`)  `id: platform-telegram.notifications`
- **Surface:** Config | Env
- **Where:** `display.platforms.telegram.notifications` in config.yaml, or `HERMES_TELEGRAM_NOTIFICATIONS`.
- **What it does:** Suppresses push notifications for tool progress, streaming and status messages so only meaningful events ring the phone.
- **How it works:** `_notification_kwargs(metadata)` (`adapter.py:1187-1200`) returns `{"disable_notification": True}` whenever the mode is `important` and `metadata["notify"]` is falsy. `_resolve_notifications_mode()` (l.11044-11067) reads `HERMES_TELEGRAM_NOTIFICATIONS` first, then `display.platforms.telegram.notifications`, defaulting to `important`; `_build_adapter` (l.11070-11078) applies it after construction.
- **Inputs / options:** `important` (default) — "Only **final responses**, **approval prompts**, and **slash-command confirmations** ring"; `all` — "Every outgoing message fires a push notification. Legacy behavior".
- **Outputs / side effects:** `disable_notification` on nearly every send.
- **Config / env:** `HERMES_TELEGRAM_NOTIFICATIONS`, `display.platforms.telegram.notifications`.
- **Edge cases / guards:** Unknown values log "Unknown telegram notifications mode '{v}', defaulting to 'important' (valid: all, important)".
- **Rebuild notes:** Carry an explicit `notify` flag in send metadata rather than inferring importance at the adapter.

### Typing indicator with per-chat cooldown  `id: platform-telegram.typing`
- **Surface:** Core
- **Where:** The "…typing" bubble in the chat.
- **What it does:** Sends `sendChatAction(typing)` while the agent works, re-arming after each intermediate message, and backs off per chat when Telegram starts failing.
- **How it works:** `send_typing` (`adapter.py:8636-8676`) calls `bot.send_chat_action(chat_id=…, action="typing", message_thread_id=_message_thread_id_for_typing(thread_id))`. `_message_thread_id_for_typing` (l.1671-1682) deliberately PRESERVES thread id `"1"` (the forum General topic) — unlike `_message_thread_id_for_send`, which maps it to `None` — because `sendChatAction` needs it to place the bubble in General. Cooldown: `_is_transient_typing_error` (l.8593-8609) matches a `retry_after` attribute, status 429 or ≥500, or the substrings `too many requests`, `rate limit`, `timed out`, `timeout`, `temporar`, or `OSError`/`TimeoutError`/`ConnectionError`/`asyncio.TimeoutError`; `_record_typing_cooldown` (l.8611-8622) sets `until = loop.time() + clamp(retry_after or extra.typing_cooldown_seconds, 1.0, 300.0)`.
- **Inputs / options:** `platforms.telegram.extra.typing_cooldown_seconds` (default **30.0**, clamped 1.0–300.0).
- **Outputs / side effects:** Typing bubble; failures logged at debug only.
- **Config / env:** `platforms.telegram.extra.typing_cooldown_seconds`.
- **Edge cases / guards:** For DM-topic lanes a rejected `message_thread_id` retries once without it so the bubble at least shows in the main DM view. Typing is deliberately NOT re-armed after the FINAL reply (`metadata["notify"]`), because Telegram exposes no stop-typing API and the ~5 s timer would leave the bubble lingering after the answer (#48678). `resume_typing_for_chat(chat_id)` is called after an inline approval button resolves.
- **Rebuild notes:** Re-arm typing after every intermediate send, never after the final one; back off per chat on 429/5xx.

### Reply-anchor mode (`reply_to_mode`)  `id: platform-telegram.reply-to-mode`
- **Surface:** Config | Env
- **Where:** `telegram.reply_to_mode` / `platforms.telegram.extra.reply_to_mode` / `TELEGRAM_REPLY_TO_MODE`.
- **What it does:** Controls whether outgoing chunks quote the user's message: not at all, only the first chunk, or every chunk.
- **How it works:** `_should_thread_reply(reply_to, chunk_index)` (`adapter.py:5363-5381`): `off` → never; `all` → always; `first` (default) → `chunk_index == 0`. Set in `__init__` from `config.reply_to_mode` (l.707). YAML→env bridge at `adapter.py:11228-11234` maps `reply_to_mode: false` to the string `"off"`.
- **Inputs / options:** `off` | `first` (default) | `all`; also accepts YAML `false` → `off`.
- **Outputs / side effects:** `reply_to_message_id` on sends.
- **Config / env:** `TELEGRAM_REPLY_TO_MODE`, `telegram.reply_to_mode`, `platforms.telegram.extra.reply_to_mode`.
- **Edge cases / guards:** On DM-topic fallback sends, `off` suppresses the anchor but keeps `message_thread_id` so the message still lands in the right topic (`_thread_kwargs_for_send`, l.1609-1611); this is an explicit opt-in to "message_thread_id alone is enough" and disables the fail-loud anchor requirement.
- **Rebuild notes:** Three-valued setting evaluated per chunk index.

### Thread / topic routing kwargs  `id: platform-telegram.thread-routing`
- **Surface:** Core
- **Where:** Every outgoing message, media send and draft.
- **What it does:** Decides whether a send carries `message_thread_id` (forum/private topic), `direct_messages_topic_id` (true Bot API DM topic), a reply anchor, or nothing.
- **How it works:** `_thread_kwargs_for_send` (`adapter.py:1582-1638`). Rules: (a) with `telegram_dm_topic_reply_fallback` and `reply_to_mode == "off"` → `{"message_thread_id": …}` only; (b) with the fallback flag and a resolvable anchor → `{"message_thread_id": …}`; (c) with the fallback flag and NO anchor (synthetic/resumed sends: loop wakeups, watch notifications, restart-resumed follow-ups) → prefer the Hermes topic `message_thread_id`, else `{"message_thread_id": None, "direct_messages_topic_id": int(...)}`, else `{}` (#87051); (d) with an explicit `direct_messages_topic_id` and no fallback flag → `{"message_thread_id": None, "direct_messages_topic_id": int(...)}`; (e) otherwise `{"message_thread_id": _message_thread_id_for_send(thread_id)}`. `_message_thread_id_for_send` (l.1665-1669) maps a missing id or the General topic id `"1"` to `None` (Telegram rejects `message_thread_id=1` on sends). `_thread_kwargs_for_draft` (l.1640-1663) reuses the same computation and strips `None` values. Metadata readers: `_metadata_thread_id` (`thread_id` or `message_thread_id`), `_metadata_direct_messages_topic_id` (`direct_messages_topic_id` or `telegram_direct_messages_topic_id`), `_metadata_reply_to_message_id` (`telegram_reply_to_message_id`).
- **Inputs / options:** metadata keys listed above; class constant `_GENERAL_TOPIC_THREAD_ID = "1"`.
- **Outputs / side effects:** send kwargs.
- **Config / env:** n/a.
- **Edge cases / guards:** `_is_private_dm_topic_send` (l.1542-1561) identifies Hermes-created private topic lanes; when such a send has no anchor and `reply_to_mode != "off"` and no `direct_messages_topic_id`, `send()` refuses with `SendResult(success=False, error="Telegram DM topic delivery requires a reply anchor; refusing to send outside the requested topic", retryable=False)` rather than leaking the message into the root DM.
- **Rebuild notes:** Model topic routing as a single pure function returning kwargs, with an explicit fail-loud path rather than a silent fallback to the root chat.

### Stale-topic recovery on send  `id: platform-telegram.thread-not-found`
- **Surface:** Core
- **Where:** Any send into a topic Telegram has deleted; logs "Thread {id} not found, retrying once with same thread_id" then "Thread {id} not found, retrying without message_thread_id".
- **What it does:** Survives a deleted forum/DM topic by retrying once (Telegram emits one-off flakes), then sending to the chat root and pruning the stale binding.
- **How it works:** `send()` (`adapter.py:5554-5590`) and `_send_message_with_thread_fallback` (l.6345-6382) for control-style sends (approvals, pickers, update prompts). `_prune_stale_dm_topic_binding` (l.1688-1727) calls `session_store._db.delete_telegram_topic_binding(chat_id, thread_id)` so `gateway.run._recover_telegram_topic_thread_id` stops steering future inbound messages at the dead thread (#31501); logs "Pruned stale Telegram DM topic binding chat={c} thread={t} (Bot API: thread not found)".
- **Inputs / options:** n/a. **Outputs / side effects:** DB row deleted; message delivered to the chat root.
- **Config / env:** n/a.
- **Edge cases / guards:** For private DM-topic sends and `telegram_dm_topic_created_for_send` sends the failure is returned as non-retryable instead of silently relocating the message. `_send_with_dm_topic_reply_anchor_retry` (l.1784-1816) applies the same idea to media: on a qualifying BadRequest it rewinds the file handle (`reset_media`) and retries without `reply_to_message_id`, `message_thread_id` and `direct_messages_topic_id`.
- **Rebuild notes:** Retry once (flake), then degrade and clean up persistent state.

### Telegram chat-id normalization (`@username` targets)  `id: platform-telegram.chat-id`
- **Surface:** Core
- **Where:** Every Bot API call in the adapter.
- **What it does:** Accepts both numeric chat ids (including negative supergroup/channel ids) and `@username` strings without crashing.
- **How it works:** `plugins/platforms/telegram/telegram_ids.py`. `normalize_telegram_chat_id(chat_id)` returns `int` when parseable, else the stripped string. `telegram_chat_id_key(chat_id)` gives a stable string key for dicts/persistence. `looks_like_telegram_username(chat_id)` matches `@[A-Za-z0-9_]{4,32}` in full. `parse_telegram_username_target(target_ref)` returns the value when it is a username target, else `None`.
- **Inputs / options:** any chat-id-shaped value.
- **Outputs / side effects:** `int | str`.
- **Config / env:** n/a.
- **Edge cases / guards:** A bare `int(chat_id)` used to raise `ValueError: invalid literal for int()` on public-channel `@username` targets.
- **Rebuild notes:** Normalize once at the boundary; never call `int()` on a user-supplied chat reference.

### `get_chat_info()`  `id: platform-telegram.chat-info`
- **Surface:** Core
- **Where:** Channel directory / session naming.
- **What it does:** Resolves a chat id to a display name and a Hermes chat type.
- **How it works:** `adapter.py:8678-8710` → `bot.get_chat(...)`; maps `ChatType.GROUP` → `group`, `ChatType.SUPERGROUP` → `group` (or `forum` when `chat.is_forum`), `ChatType.CHANNEL` → `channel`, else `dm`. Returns `{"name": chat.title or chat.full_name or str(chat_id), "type": …, "username": chat.username, "is_forum": bool}`.
- **Inputs / options:** `chat_id`.
- **Outputs / side effects:** dict; on failure returns `{"name": str(chat_id), "type": "dm", "error": str(e)}` and logs "Failed to get Telegram chat info for {id}: {err}"; when disconnected returns `{"name": "Unknown", "type": "dm"}`.
- **Config / env:** n/a.
- **Edge cases / guards:** none beyond the above.
- **Rebuild notes:** n/a.

---

## 5. Inline keyboards: approvals, confirmations, clarify and pickers

### Update prompt buttons (`✓ Yes` / `✗ No`)  `id: platform-telegram.update-prompt`
- **Surface:** Gateway/Telegram
- **Where:** Any chat, while `hermes update --gateway` runs and the updater needs an answer. Message body: `⚕ *Update needs your input:*` followed by the prompt and, when a default exists, ` (default: <default>)`. Buttons: **`✓ Yes`**, **`✗ No`**.
- **What it does:** Asks the operator a yes/no question raised by the self-update flow (stash restore, config migration) and feeds the answer back to the waiting update process.
- **How it works:** `send_update_prompt(chat_id, prompt, default="", session_key="", metadata=None)` at `plugins/platforms/telegram/adapter.py:6384-6425`. Text is `self.format_message(f"⚕ *Update needs your input:*\n\n{prompt}{default_hint}")`, `parse_mode=ParseMode.MARKDOWN_V2`, keyboard `InlineKeyboardMarkup([[InlineKeyboardButton("✓ Yes", callback_data="update_prompt:y"), InlineKeyboardButton("✗ No", callback_data="update_prompt:n")]])`, sent through `_send_message_with_thread_fallback` with `reply_to_message_id` + `_thread_kwargs_for_send(...)` + `_link_preview_kwargs()`. The tap is handled in `_handle_callback_query` (`adapter.py:7733-7770`): it answers `Sent '<y|n>' to the update process.`, edits the message to `⚕ Update prompt answered: *Yes|No*`, then writes the single character to `<HERMES_HOME>/.update_response` via a `.tmp` file + `Path.replace()` (atomic).
- **Inputs / options:** `chat_id`, `prompt`, `default`, `session_key` (unused for state), `metadata` (`thread_id`, `telegram_reply_to_message_id`, `direct_messages_topic_id`). Buttons: `✓ Yes` (`update_prompt:y`), `✗ No` (`update_prompt:n`).
- **Outputs / side effects:** `SendResult(success=True, message_id=…)`; on tap, `~/.hermes/.update_response` contains `y` or `n`; log `Telegram update prompt answered '%s' by user %s`.
- **Config / env:** none beyond the platform's; home dir from `hermes_constants.get_hermes_home()`.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`. Unauthorized tapper → answer `⛔ You are not authorized to answer update prompts.` Send failure logs `send_update_prompt failed: …` (redacted) and returns a failed `SendResult`. Edit failure is swallowed. File-write failure logs `Failed to write update response from callback: …`.
- **Rebuild notes:** Two callback tokens + an atomic single-byte file the updater polls. A better version would pass a nonce so a stale prompt cannot answer a newer update run.

### Exec approval prompt (`✅ Allow Once` / `✅ Session` / `✅ Always` / `❌ Deny`)  `id: platform-telegram.exec-approval`
- **Surface:** Gateway/Telegram
- **Where:** The chat where a dangerous command was proposed. HTML body starts `⚠️ <b>Command Approval Required</b>` then the command inside `<pre>…</pre>`; when the smart-deny path applies it appends `<b>Smart DENY:</b> owner override applies to this one operation only.` Buttons in 2-per-row layout: **`✅ Allow Once`**, **`✅ Session`**, **`✅ Always`**, **`❌ Deny`**.
- **What it does:** Renders a tap-to-approve prompt for a command the agent wants to run; the tap unblocks the waiting agent thread exactly like the text `/approve` flow.
- **How it works:** `send_exec_approval(chat_id, command, session_key, description="dangerous command", metadata=None, allow_permanent=True, allow_session=True, smart_denied=False)` at `adapter.py:6437-6511`. Text comes from the shared `self._format_exec_approval(command, description, smart_denied)` core, parameterised by the Telegram class attrs at `adapter.py:6427-6435`: `_EA_HEADER = "⚠️ <b>Command Approval Required</b>\n\n"`, `_EA_CODE_OPEN = "<pre>"`, `_EA_CODE_CLOSE = "</pre>\n\n"`, `_EA_SMART_DENY_LINE`, `_EA_CMD_BUDGET = 3800`, and `_ea_escape = html.escape`. A process-local `itertools.count(1)` (`self._approval_counter`) mints `approval_id`; callback data is `ea:once:<id>`, `ea:session:<id>`, `ea:always:<id>`, `ea:deny:<id>`. Buttons are chunked `rows = [buttons[i:i+2] …]` so labels do not truncate on mobile. Sent with `parse_mode=ParseMode.HTML`. `self._approval_state[approval_id] = session_key` records the pending approval.
- **Inputs / options:** `allow_session=False` removes `✅ Session` and `✅ Always`; `allow_permanent=False` removes `✅ Always`; `smart_denied=True` removes both and appends the smart-deny line (leaving `✅ Allow Once` + `❌ Deny`).
- **Outputs / side effects:** In-memory `_approval_state` entry; message with buttons.
- **Config / env:** n/a (approval policy lives in the tools layer).
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`; exceptions log `send_exec_approval failed: …` with redacted text.
- **Rebuild notes:** Short monotonic ids in callback data (Telegram caps `callback_data` at 64 bytes) + a server-side map to the session key; never put the command itself in callback data.

### Exec approval tap handling  `id: platform-telegram.approval-callback`
- **Surface:** Gateway/Telegram
- **Where:** Tapping any `ea:` button. Toast texts: `Invalid approval data.`, `⛔ You are not authorized to approve commands.`, `This approval has already been resolved.`, `✅ Approved once`, `✅ Approved for session`, `✅ Approved permanently`, `❌ Denied`, `⌛ Approval expired`.
- **What it does:** Authorizes the tapper, resolves the pending approval, rewrites the message to show who decided what, and resumes the typing indicator.
- **How it works:** `adapter.py:7432-7513`. Parses `data.split(":", 2)` → `(prefix, choice, approval_id)`; non-integer id → `Invalid approval data.` Authorization via `_is_callback_user_authorized(caller_id, chat_id=…, chat_type=…, thread_id=…, user_name=…)`. `session_key = self._approval_state.pop(approval_id, None)`; missing → `This approval has already been resolved.` Resolution happens BEFORE rendering: `from tools.approval import resolve_gateway_approval; count = resolve_gateway_approval(session_key, choice)` and logs `Telegram button resolved %d approval(s) for session %s (choice=%s, user=%s)`. When `count` is truthy the message is edited to `"<label> by <first_name>"` via `format_message(...)` + MarkdownV2; when `count == 0` the label is `⌛ Approval expired` and the body reads `⌛ Approval expired — no command was waiting. It already timed out (and was denied) or was resolved elsewhere.` Finally, on a resolved tap, `self.resume_typing_for_chat(str(chat_id))` re-arms typing (the gateway paused it when the approval was sent).
- **Inputs / options:** choices `once`, `session`, `always`, `deny`.
- **Outputs / side effects:** Agent thread unblocked; buttons removed (`reply_markup=None`); typing resumed.
- **Config / env:** n/a.
- **Edge cases / guards:** `resolve_gateway_approval` failure logs `Failed to resolve gateway approval from Telegram button: …` and forces `count = 0` (so the message never lies about approving). Edit failures are non-fatal.
- **Rebuild notes:** Resolve first, render from the resolver's return value — never render optimistically.

### Slash-command confirmation prompt (`✅ Approve Once` / `🔒 Always Approve` / `❌ Cancel`)  `id: platform-telegram.slash-confirm`
- **Surface:** Gateway/Telegram
- **Where:** Chat where a gated slash command (e.g. `/reload-mcp`) was typed. Buttons row 1: **`✅ Approve Once`**, **`🔒 Always Approve`**; row 2: **`❌ Cancel`**.
- **What it does:** Asks the user to confirm a slash command that mutates gateway state before it runs.
- **How it works:** `send_slash_confirm(chat_id, title, message, session_key, confirm_id, metadata=None)` at `adapter.py:6513-6559`. Body is `self.format_message(self._truncate_preview(message, 3800))` in MarkdownV2. Callback data: `sc:once:<confirm_id>`, `sc:always:<confirm_id>`, `sc:cancel:<confirm_id>`. Records `self._slash_confirm_state[confirm_id] = session_key`. The tap path (`adapter.py:7515-7616`) authorizes, pops the state, answers with the label (`✅ Approved once` / `🔒 Always approve` / `❌ Cancelled`), edits the message to `"<label> by <first_name>"`, then calls `tools.slash_confirm.resolve(session_key, confirm_id, choice)`; if that returns text it is sent as a follow-up in the same chat AND the same topic — for private chats with a `message_thread_id` it re-sends with `reply_to_message_id = <prompt message id>` plus `_thread_kwargs_for_send(..., {"thread_id": …, "telegram_dm_topic_reply_fallback": True}, …)`, otherwise with plain thread kwargs.
- **Inputs / options:** `title` (unused in the rendered body — the body is `message`), `message`, `confirm_id`.
- **Outputs / side effects:** Follow-up message with the command's result; `_slash_confirm_state` entry removed.
- **Config / env:** n/a.
- **Edge cases / guards:** Unauthorized → `⛔ You are not authorized to answer this prompt.`; already resolved → `This prompt has already been resolved.`; resolve failure logs `slash-confirm callback failed: …` with traceback. Not connected → `SendResult(success=False, error="Not connected")`.
- **Rebuild notes:** Keep the confirm id opaque and short; inherit the prompt's topic for the follow-up so results do not leak into the DM root.

### Clarify prompt with numbered buttons  `id: platform-telegram.clarify`
- **Surface:** Gateway/Telegram
- **Where:** Wherever the agent calls the `clarify` tool. Body: `❓ <question>` (HTML-escaped) followed by a numbered option list `1. <choice>`, `2. <choice>`, …; buttons: one per choice labelled `1`, `2`, `3`, … (one per row), then **`✏️ Other (type answer)`**.
- **What it does:** Turns an agent question into tappable choices; the numeric labels stay short while the full option text is readable in the message body.
- **How it works:** `send_clarify(chat_id, question, choices, clarify_id, session_key, metadata=None)` at `adapter.py:6561-6641`. Multi-choice mode builds `option_lines = "\n".join(f"{i+1}. {html.escape(str(c))}")` and rows of `InlineKeyboardButton(str(idx+1), callback_data=f"cl:{clarify_id}:{idx}")` plus a final `InlineKeyboardButton("✏️ Other (type answer)", callback_data=f"cl:{clarify_id}:other")`. Open-ended mode (`choices` empty/None) renders the question as plain text with NO buttons — the gateway's text intercept captures the next message. `parse_mode=ParseMode.HTML`. Registers `self._clarify_state[clarify_id] = session_key`. Note this send uses `_reply_to_message_id_for_send(None, metadata)` WITHOUT `reply_to_mode`, i.e. the anchor is always attempted.
- **Inputs / options:** `choices` list (any length; callback data kept short because Telegram caps it at 64 bytes), `clarify_id`, `session_key`.
- **Outputs / side effects:** Message with keyboard; in-memory clarify state.
- **Config / env:** timeout comes from `agent.clarify_timeout` (default `600` seconds) — documented at `website/docs/user-guide/messaging/telegram.md:1290-1301`.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`; failures log `send_clarify failed: …`.
- **Rebuild notes:** Body carries the long text, buttons carry indexes; always offer a free-text escape hatch.

### Clarify tap handling and `✏️ Other` capture  `id: platform-telegram.clarify-callback`
- **Surface:** Gateway/Telegram
- **Where:** Tapping a clarify button. Toasts: `⛔ You are not authorized to answer this prompt.`, `This prompt has already been resolved.`, `✏️ Type your answer in the chat.`, `Invalid choice.`, `✓ <chosen text, first 60 chars>`.
- **What it does:** Resolves the clarify with the chosen option text, or flips the entry into "await typed answer" mode.
- **How it works:** `adapter.py:7618-7731`. Data shape `cl:<clarify_id>:<idx|other>`. Auth via `_is_callback_user_authorized`. For `other`: `tools.clarify_gateway.mark_awaiting_text(clarify_id)`; when it returns False (entry evicted by `clarify_timeout` or gateway restart) the state is popped and `_notify_clarify_expired` runs; on success the message is edited to `❓ <original text>\n\n<i>Awaiting typed response from <name>…</i>` (HTML). For a numeric choice the text is looked up from `tools.clarify_gateway._entries[clarify_id].choices[idx]`, falling back to the literal `choice <idx+1>` if the entry vanished, then `resolve_gateway_clarify(clarify_id, resolved_text)`; on success the message becomes `❓ <question>\n\n<b><name>:</b> <chosen text>` and the log line `Telegram clarify button resolved (id=%s, choice=%r, user=%s)` is written; on failure `_notify_clarify_expired` runs and `Telegram clarify button: resolve_gateway_clarify returned False (id=%s)` is logged at warning.
- **Inputs / options:** `idx` integer or the literal `other`.
- **Outputs / side effects:** Agent unblocked with the chosen string; keyboard removed.
- **Config / env:** `agent.clarify_timeout`.
- **Edge cases / guards:** `mark_awaiting_text` exception logs `mark_awaiting_text failed: …`; the `_clarify_state` entry is deliberately NOT popped on the `other` path until the answer arrives.
- **Rebuild notes:** Resolve from the authoritative entry, not from the button label, so a re-rendered message cannot desync the answer.

### Expired-clarify notice  `id: platform-telegram.clarify-expired`
- **Surface:** Gateway/Telegram
- **Where:** Tap on a clarify button whose entry is gone. Toast: `⚠️ This prompt expired — please /retry.` Message becomes `❓ <question>\n\n<i>⚠️ This question expired or the session reset — please /retry.</i>`.
- **What it does:** Tells the user their tap arrived too late instead of leaving a misleading ✓.
- **How it works:** `_notify_clarify_expired(query, user_display)` at `adapter.py:7280-7303`; both the `answer()` and the `edit_message_text()` are wrapped in bare `try/except`.
- **Inputs / options:** n/a. **Outputs / side effects:** Toast + edited message, buttons removed.
- **Config / env:** n/a.
- **Edge cases / guards:** Fires from both the numeric and the `other` path.
- **Rebuild notes:** Any timed prompt needs an explicit expired rendering.

### Interactive model picker (`/model` with no argument)  `id: platform-telegram.model-picker`
- **Surface:** Gateway/Telegram
- **Where:** Send `/model` in any Telegram chat. First screen (MarkdownV2): `⚙ *Model Configuration*`, `Current model: \`<model or 'unknown'>\``, `Provider: <provider label>`, `Select a provider:<page info>`.
- **What it does:** Two-step drill-down keyboard (provider → model) that switches the session's model by editing one message in place.
- **How it works:** `send_model_picker(chat_id, providers, current_model, current_provider, session_key, on_model_selected, metadata=None)` at `adapter.py:6643-6715`. Provider labels come from `hermes_cli.providers.get_label` (identity fallback when the import fails). The keyboard is built by `_build_provider_keyboard(providers, 0)`. State is stored per chat in `self._model_picker_state[str(chat_id)] = {"msg_id", "providers", "session_key", "on_model_selected", "current_model", "current_provider", "provider_page"}`.
- **Inputs / options:** `providers` is a list of dicts with `slug`, `name`, `models`, `total_models`, `is_current`; `on_model_selected(chat_id, model_id, provider_slug)` is the async apply callback.
- **Outputs / side effects:** One message that is edited through the whole flow; picker state per chat.
- **Config / env:** n/a. Docs: `telegram.md:1138-1149`.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`; failures log `send_model_picker failed: …`. Typing `/model <name>` (optionally `--global`) skips the picker entirely.
- **Rebuild notes:** Store picker state keyed by chat and edit one message; never post a new message per navigation step.

### Provider keyboard with family folding and pagination  `id: platform-telegram.provider-keyboard`
- **Surface:** Gateway/Telegram
- **Where:** First page of the `/model` picker. Buttons: `<Provider name> (<model count>)` (prefixed `✓ ` when current), family rows `<Family label> ▸ (<total count>)`, a nav row `◀ Prev` / `<page+1>/<total>` / `Next ▶`, and a final row **`✗ Cancel`**.
- **What it does:** Renders up to 10 provider buttons per page, folding provider families (Kimi/Moonshot, MiniMax, xAI Grok, …) into one drill-down button so the keyboard stays short.
- **How it works:** `_build_provider_keyboard(providers, page=0)` at `adapter.py:6840-6905`; `_PROVIDER_PAGE_SIZE = 10` (`adapter.py:6715`). Grouping uses `hermes_cli.models.group_providers([slug…])`, which returns rows of `{"kind": "group", "group_id", "label", "members"}` or `{"kind": …, "slug"}` — the same fold the CLI `hermes model` picker uses. Group buttons carry `mpg:<group_id>`, single providers `mp:<slug>`. Buttons are laid out two per row via `[page_buttons[i:i+2] …]`; pagination buttons are `mpv:<page-1>` / `mpv:<page+1>` and the counter button is the inert `mx:noop`. Paging metadata comes from the shared `self._format_choice_page(buttons, page, size)` → `{"page", "total_pages", "start", "page_info"}`.
- **Inputs / options:** `page` index.
- **Outputs / side effects:** `(InlineKeyboardMarkup, page_info_text)`.
- **Config / env:** n/a.
- **Edge cases / guards:** When `group_providers` cannot be imported, every provider renders as its own button. A family whose members are not in `by_slug` is skipped. The nav row only appears when `total_pages > 1`.
- **Rebuild notes:** Fold families first, then paginate the folded list — folding after paging produces ragged pages.

### Model keyboard with pagination  `id: platform-telegram.model-keyboard`
- **Surface:** Gateway/Telegram
- **Where:** Second page of the `/model` picker: `⚙ *Model Configuration*`, `Provider: *<name>*<page info>`, `Select a model:` plus (when the provider has more models than were shipped) `_<N> more available — type \`/model <name>\` directly_`. Buttons: model short names, nav row `◀ Prev` / `<page+1>/<total>` / `Next ▶`, then a row of **`◀ Back`** and **`✗ Cancel`**.
- **What it does:** Lists 8 models per page as tappable buttons.
- **How it works:** `_build_model_keyboard(models, page)` at `adapter.py:6907-6943`; `_MODEL_PAGE_SIZE = 8` (`adapter.py:6838`). Labels strip any `vendor/` prefix (`model_id.split("/")[-1]`) and truncate to 38 chars as `short[:35] + "..."`. Callback data is `mm:<absolute index>` (page start + offset), nav is `mg:<page>`, back is `mb`, cancel is `mx`.
- **Inputs / options:** `models` list of ids, `page`.
- **Outputs / side effects:** `(InlineKeyboardMarkup, page_info_text)`.
- **Config / env:** n/a.
- **Edge cases / guards:** Absolute indexes keep `mm:` valid across pages; the counter button uses `mx:noop` which falls through to the catch-all `query.answer()`.
- **Rebuild notes:** Encode the ABSOLUTE index in callback data so pagination never mis-selects.

### Model picker callback router  `id: platform-telegram.model-picker-callback`
- **Surface:** Gateway/Telegram
- **Where:** Every tap inside the `/model` picker. Toasts: `Picker expired — use /model again.`, `Provider not found.`, `Invalid page.`, `Invalid selection.`, `Invalid model index.`, `Picker expired.`, `Group not found.`, `Confirm model selection`, `Model switched!`, `Switch failed.`; cancel replaces the body with `Model selection cancelled.`
- **What it does:** Implements every branch of the picker: provider select, model select, page navigation (models and providers), family drill-down, back, cancel, and expensive-model confirmation.
- **How it works:** `_handle_model_picker_callback(query, data, chat_id)` at `adapter.py:6945-7278`. Branches by prefix: `mp:` provider selected → stores `selected_provider`, `selected_provider_name`, `model_list`, `model_page=0` and edits to the model keyboard; `mg:` model page; `mpv:` provider page; `mc:` confirmed expensive switch; `mm:` model selected; `mpg:` provider family expansion (members read from `hermes_cli.models.PROVIDER_GROUPS[group_id] → (label, desc, member_slugs)`, rendered two per row with `◀ Back` / `✗ Cancel`, header `Provider family: *<label>*`); `mb` back to the provider list at the remembered `provider_page`; `mx` cancel (pops state, edits to `Model selection cancelled.`); anything else (e.g. `mx:noop`) → bare `query.answer()`.
- **Inputs / options:** callback data prefixes `mp:`, `mpg:`, `mpv:`, `mm:`, `mc:`, `mg:`, `mb`, `mx`.
- **Outputs / side effects:** Calls `on_model_selected(chat_id, model_id, provider_slug)`; edits the message to the callback's returned text; pops `_model_picker_state[chat_id]` after a switch or cancel.
- **Config / env:** n/a.
- **Edge cases / guards:** Missing state → `Picker expired — use /model again.` A failing callback logs `Model picker switch failed: %s`, renders `Error switching model: <exc>` and answers `Switch failed.` MarkdownV2 edit failure retries the same text with `parse_mode=None`; a second failure is swallowed.
- **Rebuild notes:** One state dict per chat, one message edited in place, prefix-routed callbacks; keep every branch answering the callback query so Telegram stops the spinner.

### Expensive-model confirmation (`Switch anyway`)  `id: platform-telegram.model-price-guard`
- **Surface:** Gateway/Telegram
- **Where:** After tapping a model whose selection triggers a warning. Body: `⚠ *<warning.title>*` then `<warning.message>`. Buttons: **`Switch anyway`** (row 1), **`◀ Back`** and **`✗ Cancel`** (row 2). Toast: `Confirm model selection`.
- **What it does:** Interposes a confirmation step before switching to a model flagged by the pricing/selection guards.
- **How it works:** `adapter.py:7112-7147`. `hermes_cli.model_selection_guards.combined_selection_warning(model_id, provider=provider_slug)` is called through `asyncio.to_thread` because a cache miss can hit models.dev / a `/models` endpoint. A non-None warning rewrites the keyboard with `mc:<idx>` ("Switch anyway"), `mb`, `mx` and returns without switching.
- **Inputs / options:** implicit (the selected model index).
- **Outputs / side effects:** none until `mc:` is tapped.
- **Config / env:** governed by the model-selection-guard config (sibling shard).
- **Edge cases / guards:** Any exception computing the warning is swallowed (`warning = None`) and the switch proceeds — the guard fails open.
- **Rebuild notes:** Compute the warning off the event loop; encode the pending index in the confirm button.

### Generic choice picker (`/reasoning`, `/fast`)  `id: platform-telegram.choice-picker`
- **Surface:** Gateway/Telegram
- **Where:** Commands that offer a flat finite set of values. Title is rendered via `format_message(title)`; buttons are the choice labels, two per row, with `✓ ` prefixed on the current value.
- **What it does:** One-tap selection from a flat list — the single-level companion to the model picker.
- **How it works:** `send_choice_picker(chat_id, title, choices, session_key, on_choice_selected, metadata=None)` at `adapter.py:6717-6778`. Each choice is `{"value": str, "label": str, "is_current": bool}`; callback data is `cp:<index>`. State: `self._choice_picker_state[str(chat_id)] = {"msg_id", "choices", "session_key", "on_choice_selected"}`.
- **Inputs / options:** `choices` list; empty list → `SendResult(success=False, error="No choices")`.
- **Outputs / side effects:** Message with keyboard; picker state per chat.
- **Config / env:** n/a.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`; failures log `send_choice_picker failed: …`.
- **Rebuild notes:** Index-based callback data + a per-chat state map; mark the current value with a check.

### Choice picker tap handling  `id: platform-telegram.choice-picker-callback`
- **Surface:** Gateway/Telegram
- **Where:** Tapping a `cp:` button. Toasts: `Picker expired — run the command again.`, `⛔ You are not authorized to change this setting.`, `Invalid selection.`, `Picker expired.`
- **What it does:** Applies the tapped value through the registered callback and replaces the message with the result.
- **How it works:** `_handle_choice_picker_callback(query, data, chat_id)` at `adapter.py:6780-6836`. Same authorization gate as approvals (`_is_callback_user_authorized`) so an unauthorized member of a shared group cannot flip settings through someone else's picker. `idx = int(data[3:])`; out-of-range/non-numeric → `Invalid selection.` Then `result_text = await callback(chat_id, str(choice.get("value") or ""))`, the message is edited to `format_message(result_text)` (MarkdownV2, buttons cleared), with a plain-text retry on parse failure, and the state entry is popped.
- **Inputs / options:** `cp:<index>`.
- **Outputs / side effects:** Setting applied; message replaced.
- **Config / env:** n/a.
- **Edge cases / guards:** Callback exception logs `Choice picker selection failed: %s` and renders `Error applying selection: <exc>`.
- **Rebuild notes:** Identical shape to the model picker's leaf branch — share the code.

### Gmail-triage action buttons (`gt:<verb>:<arg>`)  `id: platform-telegram.gmail-triage-callback`
- **Surface:** Gateway/Telegram
- **Where:** Inline buttons attached to gmail-triage digest messages. Toast labels on success: `✓ sent draft`, `✓ archived`, `✓ drafted reply`, `✓ marked spam`, `✓ muted`, `✓ muted domain`, `✓ trusted`, `✓ trusted domain`, `✓ marked VIP`, `✓ marked VIP domain`.
- **What it does:** Runs a shell script from `~/.hermes/scripts/gmail-triage/` for the tapped verb and annotates the message with the outcome.
- **How it works:** `_GT_VERB_DISPATCH` (`adapter.py:7772-7790`) maps verb → `(script-name, extra-args, success-label, is_state)`: `send`→`send-draft.sh` `[]`; `archive`→`archive.sh` `[]`; `draft`→`draft-blank.sh` `[]`; `spam`→`spam.sh` `[]`; `mute`→`mute-add.sh` `["email"]`; `mute-domain`→`mute-add.sh` `["domain"]`; `trust`→`trusted-ops-add.sh` `["email"]`; `trust-domain`→`trusted-ops-add.sh` `["domain"]`; `vip`→`vip-add.sh` `["email"]`; `vip-domain`→`vip-add.sh` `["domain"]`. `_handle_gmail_triage_callback` (`adapter.py:7792-7884`) authorizes the tapper, resolves `~/.hermes/scripts/gmail-triage/<script>`, and runs `[script, arg, *extra_args]` via `asyncio.create_subprocess_exec` with a **60 s** `wait_for` timeout. On rc==0 it appends `\n— <label> by <first_name>` to the message; sticky state verbs (`is_state=True`: mute/trust/vip and their domain variants) KEEP the keyboard so more actions can be stacked, one-shot verbs (`send`, `archive`, `draft`, `spam`) strip it with `reply_markup=None`.
- **Inputs / options:** callback data `gt:<verb>:<arg>` (arg is the email address or domain).
- **Outputs / side effects:** Script side effects (Gmail API calls, rule files); edited message.
- **Config / env:** scripts must exist under `~/.hermes/scripts/gmail-triage/`.
- **Edge cases / guards:** Malformed data → `Invalid gmail-triage data.`; unauthorized → `⛔ You are not authorized to act on this email.`; unknown verb → `Unknown verb: <verb>`; missing script → `❌ <script>.sh missing` plus log `gmail-triage script missing: %s`; non-zero exit → `❌ <verb> failed: <last stderr line, 80 chars>`; timeout → `❌ <verb> timed out`; other exception → `❌ <verb> error: <exc>`. Note `_Path.home()/".hermes"` is used here rather than `HERMES_HOME`.
- **Rebuild notes:** Verb table → script, with a state/one-shot flag deciding whether the keyboard survives; always bound the subprocess.

### Callback query router and authorization  `id: platform-telegram.callback-router`
- **Surface:** Core
- **Where:** Every inline-button tap on any Telegram message the bot sent.
- **What it does:** Routes `callback_query` updates to the right handler by data prefix and enforces per-tap authorization.
- **How it works:** `_handle_callback_query(update, context)` at `adapter.py:7392-7770`. Order of checks: (1) empty query/data → return; (2) `mp:`/`mpg:`/`mpv:`/`mm:`/`mc:`/`mb`/`mx`/`mg:` → model picker; (3) `cp:` → choice picker; (4) `gt:` → gmail triage; (5) `ea:` → exec approval; (6) `sc:` → slash confirm; (7) `cl:` → clarify; (8) `update_prompt:` → update prompt; anything else returns silently. Context extracted once at the top: `query.message.chat_id`, `query.message.chat.type`, `query.message.message_thread_id`, `query.from_user.first_name`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Per-branch (see the individual entries).
- **Config / env:** n/a.
- **Edge cases / guards:** Model/choice-picker branches require `query.message` to resolve a chat id, otherwise they silently return.
- **Rebuild notes:** Prefix routing with a fixed order; extract chat/thread/user context once so each branch authorizes identically.

### Inline-button authorization (`_is_callback_user_authorized`)  `id: platform-telegram.callback-auth`
- **Surface:** Core
- **Where:** Guards approvals, slash confirms, clarify taps, choice pickers, gmail-triage actions, update prompts and inline queries.
- **What it does:** Decides whether the person who tapped a button may perform the gated action, using the gateway's full auth chain when available and a fail-closed env allowlist otherwise.
- **How it works:** `adapter.py:1202-1252`. Empty user id → False. Preferred path: `runner = self._message_handler.__self__`, `auth_fn = runner._is_user_authorized`, called with a synthesized `SessionSource(platform=Platform.TELEGRAM, chat_id=chat_id or user_id, chat_type=…, user_id=…, user_name=…, thread_id=…)`. Chat-type normalization: `private`→`dm`; `supergroup`→`forum` when a thread id is present else `group`; default `dm`. Fallback path (import/exception, logged at debug as `Falling back to env-only callback auth for user %s`): read `_scoped_gate_env("TELEGRAM_ALLOWED_USERS")`; empty → allow only when `_scoped_gate_env("GATEWAY_ALLOW_ALL_USERS")` is `true|1|yes`; otherwise allow when the id is in the comma list or the list contains `*`.
- **Inputs / options:** `user_id`, `chat_id`, `chat_type`, `thread_id`, `user_name`.
- **Outputs / side effects:** boolean.
- **Config / env:** `TELEGRAM_ALLOWED_USERS`, `GATEWAY_ALLOW_ALL_USERS` (both read per-profile through `_scoped_gate_env`).
- **Edge cases / guards:** Fail-closed by design (#24457): an empty allowlist denies unless allow-all is explicitly set.
- **Rebuild notes:** Authorize the TAPPER, not the message owner; never assume the button is only visible to its requester.

---

## 6. Outbound media

### `send_voice()` — native voice bubbles and audio files  `id: platform-telegram.send-voice`
- **Surface:** Core
- **Where:** Any TTS reply or `MEDIA:` audio path; the user sees a round playable voice bubble (Ogg/Opus) or a rectangular audio player (MP3/M4A).
- **What it does:** Delivers audio as `sendVoice` for Ogg/Opus, `sendAudio` for MP3/M4A, and falls back to document delivery for anything else — transcoding to Ogg/Opus first when the caller explicitly asked for a voice bubble.
- **How it works:** `adapter.py:7927-8106`. (a) Missing file → `SendResult(success=False, error=self._missing_media_path_error("Audio", path))`. (b) When `kwargs["is_voice"]` is set (from the `[[audio_as_voice]]` marker) and the extension is not `.ogg`/`.opus`, `gateway.platforms.base.transcode_to_ogg_opus(path)` runs in a thread; failure logs `voice transcode unavailable for %s — sending original format (install ffmpeg for voice bubbles)`. (c) Duration is computed locally with `_probe_voice_duration_seconds` in a thread and passed as `duration=` because Telegram drops it for clips over roughly 5 minutes (they otherwise show `0:00`). (d) Caption variants: the MarkdownV2 render is tried first when `utf16_len(formatted) <= 1024`, then the raw `caption[:1024]` with `parse_mode=None`; a caption error containing `parse` or `entit` retries the next variant after `audio_file.seek(0)`, anything else re-raises. (e) The actual call goes through `_send_with_dm_topic_reply_anchor_retry(self._bot.send_voice, {...}, metadata, reply_to_id, "voice", reset_media=lambda: audio_file.seek(0))` with `read_timeout=_MEDIA_SEND_READ_TIMEOUT` (**60.0 s**, `adapter.py:594`), thread kwargs and notification kwargs. (f) `.mp3`/`.m4a` take the `send_audio` branch (single caption variant, `caption[:1024]`, no parse mode). (g) Everything else delegates to `self.send_document(...)`. (h) `finally:` unlinks the transcoded temp file.
- **Inputs / options:** `chat_id`, `audio_path`, `caption`, `reply_to`, `metadata`, `**kwargs` (`is_voice`).
- **Outputs / side effects:** Voice/audio/document message; temp transcode file deleted.
- **Config / env:** ffmpeg presence for Edge-TTS Opus conversion (`telegram.md:401-418`); `tts.provider`.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`. Any unhandled exception logs `Failed to send Telegram voice/audio, falling back to base adapter: …` and delegates to `super().send_voice(...)`. If every caption variant fails the last parse error is re-raised (or `RuntimeError("Telegram send_voice failed for all caption variants")`).
- **Rebuild notes:** Ogg/Opus only for voice bubbles; probe duration yourself; degrade caption formatting rather than dropping the message.

### Outgoing audio duration probe  `id: platform-telegram.voice-duration`
- **Surface:** Core
- **Where:** Every outgoing voice/audio send.
- **What it does:** Reads a clip's length locally so the Telegram player shows the real time instead of `0:00`.
- **How it works:** `_probe_voice_duration_seconds(path)` at `adapter.py:293-347` with `_coerce_duration_seconds` at `adapter.py:284-291` (rounds to whole positive seconds, else `None`). Order: stdlib `wave` for `.wav` (`getnframes()/getframerate()`), then `mutagen.File(path).info.length`, then `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 <path>` with a 5 s subprocess timeout. All three are optional; when none work it returns `None` and the caller omits `duration`.
- **Inputs / options:** file path.
- **Outputs / side effects:** integer seconds or `None`. Blocking — always called via `asyncio.to_thread`.
- **Config / env:** optional `mutagen`, optional `ffprobe` on PATH.
- **Edge cases / guards:** every step wrapped in `try/except`; mirrors `gateway.run._probe_audio_duration`.
- **Rebuild notes:** Three-tier probe, cheapest first, never fatal.

### `send_multiple_images()` — native albums (media groups)  `id: platform-telegram.media-group-send`
- **Surface:** Core
- **Where:** Replies that carry several images; Telegram renders them as one album.
- **What it does:** Bundles up to 10 photos per `sendMediaGroup` call, chunking larger batches, and peels animated GIFs out to the per-image path.
- **How it works:** `adapter.py:8108-8242`. Animations are detected with `self._is_animation_url(url)` (skipped for `file://` inputs) and routed to `super().send_multiple_images(chat_id, animations, metadata, human_delay=…)`. Remaining photos are chunked by `CHUNK = 10`; between chunks it sleeps `human_delay` when > 0. `file://` URLs are `urllib.parse.unquote`d, existence-checked (missing → log `Skipping missing image in media group: %s`) and opened as byte streams; remote URLs are passed straight to `InputMediaPhoto(media=url, caption=alt_text[:1024])`. Each chunk logs `Sending media group of %d photo(s) (chunk %d/%d)` and is sent via `_send_with_dm_topic_reply_anchor_retry(self._bot.send_media_group, {...}, …, "media group", reset_media=_reset_opened_files)` with `read_timeout=60.0`. All opened handles are closed in `finally`.
- **Inputs / options:** `images` list of `(url, alt_text)` tuples; `metadata`; `human_delay` seconds.
- **Outputs / side effects:** One album message per chunk.
- **Config / env:** n/a.
- **Edge cases / guards:** Missing `InputMediaPhoto` (SDK too old) logs `InputMediaPhoto unavailable, falling back to per-image send: %s` and delegates to the base loop. A chunk failure logs `send_media_group failed (chunk %d/%d), falling back to per-image: …` and re-sends that chunk one image at a time. Empty `media` list is skipped.
- **Rebuild notes:** 10-item album cap, GIFs excluded, per-chunk fallback rather than per-batch.

### `send_image_file()` — local photo with document fallback  `id: platform-telegram.send-image-file`
- **Surface:** Core
- **Where:** Any local image the agent emits (`MEDIA:/path.png`, screenshots, charts).
- **What it does:** Sends a local file as a Telegram photo, degrading to a document when Telegram refuses the dimensions, and to plain text as a last resort.
- **How it works:** `adapter.py:8244-8336`. Missing file → `_missing_media_path_error("Image", path)`. Otherwise `self._bot.send_photo` with `photo=<file handle>`, `caption=caption[:1024]`, `read_timeout=60.0`, thread + notification kwargs, wrapped in `_send_with_dm_topic_reply_anchor_retry(..., "photo", reset_media=lambda: image_file.seek(0))`. On failure it inspects the error text for `Photo_invalid_dimensions` / `PHOTO_INVALID_DIMENSIONS`: that case logs at INFO (`Image dimensions exceed Telegram photo limits, sending as document: %s`), everything else at WARNING (`Failed to send Telegram local image as photo, trying document fallback: …`). Both fall through to `self.send_document(..., file_name=os.path.basename(path))`; if the document also fails it logs `Failed to send Telegram local image as document, falling back to base adapter: …` and calls `super().send_image_file(...)`.
- **Inputs / options:** `chat_id`, `image_path`, `caption`, `reply_to`, `metadata`, `**kwargs`.
- **Outputs / side effects:** Photo or document message.
- **Config / env:** n/a.
- **Edge cases / guards:** Documents have no dimension limit, only the size limit (50 MB public API for sends).
- **Rebuild notes:** Photo → document → text ladder, with the dimension case logged as expected rather than as an error.

### `send_document()` — file attachments  `id: platform-telegram.send-document`
- **Surface:** Core
- **Where:** `MEDIA:` paths that are not images/video/audio, `/save` exports, oversized images.
- **What it does:** Uploads a local file as a native Telegram document with an explicit display filename.
- **How it works:** `adapter.py:8338-8391`. Missing file → `_missing_media_path_error("File", path)`. `display_name = file_name or os.path.basename(file_path)`; call is `self._bot.send_document` with `document=<handle>`, `filename=display_name`, `caption=caption[:1024]`, `read_timeout=60.0`, thread + notification kwargs, through `_send_with_dm_topic_reply_anchor_retry(..., "document", reset_media=lambda: f.seek(0))`.
- **Inputs / options:** `chat_id`, `file_path`, `caption`, `file_name`, `reply_to`, `metadata`, `**kwargs`.
- **Outputs / side effects:** Document message.
- **Config / env:** n/a.
- **Edge cases / guards:** Failure logs `Failed to send document: …` (redacted) and delegates to `super().send_document(...)`.
- **Rebuild notes:** Always pass an explicit filename — Telegram otherwise shows the temp name.

### `send_video()`  `id: platform-telegram.send-video`
- **Surface:** Core
- **Where:** `MEDIA:` video paths.
- **What it does:** Sends a local video file as a native Telegram video message.
- **How it works:** `adapter.py:8393-8442`; same shape as `send_document` but `self._bot.send_video` with `video=<handle>`, label `"video"`. Missing file → `_missing_media_path_error("Video", path)`.
- **Inputs / options:** `chat_id`, `video_path`, `caption`, `reply_to`, `metadata`, `**kwargs`.
- **Outputs / side effects:** Video message.
- **Config / env:** n/a.
- **Edge cases / guards:** Failure logs `Failed to send video: …` and delegates to `super().send_video(...)`.
- **Rebuild notes:** n/a.

### `send_image()` — remote URL photo with upload fallback  `id: platform-telegram.send-image-url`
- **Surface:** Core
- **Where:** Images the agent references by URL.
- **What it does:** Asks Telegram to fetch the URL itself (fast, works up to ~5 MB); if that fails it downloads the bytes through an SSRF-safe client and uploads them (up to ~10 MB); if that also fails it posts the URL as text.
- **How it works:** `adapter.py:8444-8543`. Pre-flight `tools.url_safety.is_safe_url(image_url)`; a blocked URL logs `Blocked unsafe image URL (SSRF protection)` and immediately delegates to `super().send_image(...)`. Step 1 sends `photo=image_url` (label `"URL photo"`). On failure it logs `URL-based send_photo failed, trying file upload: …` and step 2 uses `tools.url_safety.create_ssrf_safe_async_client(timeout=30.0, event_hooks={"response": [gateway.platforms.base._ssrf_redirect_guard]})`, `resp.raise_for_status()`, then re-sends with `photo=<bytes>` (label `"uploaded photo"`).
- **Inputs / options:** `chat_id`, `image_url`, `caption`, `reply_to`, `metadata`.
- **Outputs / side effects:** Photo message, or a text message with the URL.
- **Config / env:** SSRF allow/deny policy from `tools.url_safety`.
- **Edge cases / guards:** Second failure logs `File upload send_photo also failed: …` with traceback before the text fallback. Redirects are re-validated by the redirect guard.
- **Rebuild notes:** Validate before fetching AND on every redirect; never hand an unvalidated URL to the platform either.

### `send_animation()` — inline-playing GIFs  `id: platform-telegram.send-animation`
- **Surface:** Core
- **Where:** Animated GIF URLs in agent replies.
- **What it does:** Sends the GIF via `sendAnimation` so Telegram auto-plays it inline; falls back to a still photo.
- **How it works:** `adapter.py:8545-8592`; `self._bot.send_animation` with `animation=<url>`, `caption[:1024]`, `read_timeout=60.0`, label `"animation"`. On failure logs `Failed to send Telegram animation, falling back to photo: …` and calls `self.send_image(chat_id, animation_url, caption, reply_to, metadata=metadata)` (which itself has the URL → upload → text ladder).
- **Inputs / options:** `chat_id`, `animation_url`, `caption`, `reply_to`, `metadata`.
- **Outputs / side effects:** Animation or photo message.
- **Config / env:** n/a.
- **Edge cases / guards:** Not connected → `SendResult(success=False, error="Not connected")`.
- **Rebuild notes:** GIFs cannot ride in a media group — send them individually.

### Inbound media size guard and limits  `id: platform-telegram.media-size-guard`
- **Surface:** Core | Config
- **Where:** Every inbound voice, audio, video and document. Agent-visible note: `[Telegram <label> skipped: file size <N.N> MB exceeds the <M> MB limit. Ask the user to send a smaller file.]`; documents get `The document is too large or its size could not be verified. Maximum: <M> MB.`; observed group attachments get `[Observed Telegram attachment too large or unverifiable. Maximum: <M> MB.]`.
- **What it does:** Refuses to download attachments above the effective ceiling and tells both the agent and (for documents) the user why.
- **How it works:** `_telegram_media_size_allowed(source, label)` at `adapter.py:7913-7925` reads `self._max_doc_bytes`, treats a missing/zero `file_size` as allowed, and otherwise compares. `_telegram_media_too_large_note(label, file_size, max_bytes)` at `adapter.py:7901-7911` formats the note with `limit_mb = max(1, max_bytes // (1024*1024))` and `size_mb = file_size / (1024*1024)` rendered as `f"{size_mb:.1f} MB"` (or `unknown size`). The ceiling itself is set in `__init__` (`adapter.py:869-876`): **20 MB** by default (the public Bot API `getFile` cap), or **2 GB** when `platforms.telegram.extra.base_url` is set (a locally hosted `telegram-bot-api` server). The document path checks the limit BEFORE the image-document branch so images cannot bypass it (`adapter.py:10357-10366`).
- **Inputs / options:** any Telegram file-bearing object with `.file_size`.
- **Outputs / side effects:** `(allowed: bool, note: Optional[str])`; skipped downloads still dispatch a turn carrying the note.
- **Config / env:** `platforms.telegram.extra.base_url`.
- **Edge cases / guards:** A zero/unknown `file_size` is allowed through for voice/audio/video but REJECTED for documents (`not doc.file_size or doc.file_size > limit`), which is deliberately stricter.
- **Rebuild notes:** Check the declared size before downloading; make the limit a function of the API endpoint in use.

### Missing-media path error with Docker hint  `id: platform-telegram.missing-media-path`
- **Surface:** Core
- **Where:** Returned as `SendResult.error` when a `MEDIA:` path does not exist on the gateway host: `<label> file not found: <path>` plus, for sandbox-shaped paths, ` (path may only exist inside the Docker sandbox. Bind-mount a host directory and emit the host-visible path in MEDIA: for gateway file delivery.)`.
- **What it does:** Turns the most common media-delivery failure into an actionable message.
- **How it works:** `_missing_media_path_error(label, path)` at `adapter.py:7886-7899`; the hint is appended when the path starts with `/workspace/`, `/output/` or `/outputs/`. Labels used: `Audio`, `Image`, `File`, `Video`.
- **Inputs / options:** label, path.
- **Outputs / side effects:** error string only.
- **Config / env:** related docs `telegram.md:216-247` (`terminal.backend: docker`, `docker_volumes`).
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Detect the container-only path shapes and say exactly what to change.

### Flood-control inline wait cap  `id: platform-telegram.flood-cap`
- **Surface:** Core
- **Where:** Every send/edit that hits Telegram's `RetryAfter`. Returned error string: `flood_control:<wait seconds>`.
- **What it does:** Refuses to sleep inline on long flood penalties, handing the wait back to the caller's retry machinery instead of pinning a worker.
- **How it works:** `_FLOOD_INLINE_WAIT_CAP_SECS = 5.0` (`adapter.py:250-257`) and `_flood_cap_result(wait)` (`adapter.py:260-266`) returning `SendResult(success=False, error=f"flood_control:{wait}", retry_after=float(wait))`. Waits at or below the cap are slept inline; longer server penalties fail closed so the delivery ledger / streaming fallback owns the retry (a 97-minute penalty on the boot path once froze inbound on every platform, #91969).
- **Inputs / options:** the `retry_after` seconds Telegram reports.
- **Outputs / side effects:** failed `SendResult` carrying `retry_after`.
- **Config / env:** n/a.
- **Edge cases / guards:** `FALLBACK_ON_FINAL_EDIT_FLOOD = True` (`adapter.py:648-651`) makes a flood on the turn-final edit skip retries and go straight to the fallback path.
- **Rebuild notes:** Never sleep an unbounded server-supplied delay inside a request coroutine.

### `MEDIA:` attachment delivery — supported extensions  `id: platform-telegram.media-tag`
- **Surface:** Docs | Gateway/Telegram
- **Where:** `website/docs/user-guide/messaging/telegram.md:248-262`; the agent emits `MEDIA:/path/to/file` in its reply.
- **What it does:** Documents which file types the gateway ships as native Telegram attachments.
- **How it works:** The gateway extracts `MEDIA:` tags from replies and dispatches to the adapter's typed senders. Documented table: **Images** `png`, `jpg`, `jpeg`, `gif`, `webp`, `bmp`, `tiff`, `svg`; **Audio** `mp3`, `wav`, `ogg`, `m4a`, `opus`, `flac`, `aac`; **Video** `mp4`, `mov`, `webm`, `mkv`, `avi`; **Documents** `pdf`, `txt`, `md`, `csv`, `json`, `xml`, `html`, `yaml`, `yml`, `log`; **Office** `docx`, `xlsx`, `pptx`, `odt`, `ods`, `odp`; **Archives** `zip`, `rar`, `7z`, `tar`, `gz`, `bz2`; **Books / packages** `epub`, `apk`, `ipa`.
- **Inputs / options:** the `MEDIA:` tag.
- **Outputs / side effects:** native attachment on Telegram; link/plain-text fallback on platforms without native support.
- **Config / env:** `terminal.backend: docker` + `terminal.docker_volumes` when the file is produced inside a sandbox.
- **Edge cases / guards:** The path must be readable by the gateway process, not just inside the container.
- **Rebuild notes:** A single reply-side tag that maps extension → typed send call keeps the agent free of platform knowledge.

---

## 7. Inbound gating: allowlists, mentions, groups vs DMs

### Intake authorization prefilter  `id: platform-telegram.intake-auth`
- **Surface:** Core
- **Where:** Runs before anything else on every inbound text, command, media and location update. Log line: `[Telegram] Blocked unauthorized user %s in chat %s` (media path logs `Blocked media from unauthorized user %s in chat %s` at INFO).
- **What it does:** Rejects messages from unauthorized senders before batching, event construction, observed-transcript writes or agent dispatch, so a removed user cannot inject prompt content anywhere.
- **How it works:** `_is_user_authorized_from_message(message)` at `adapter.py:1414-1518`. Builds the auth source with `_source_from_message_for_auth` (`adapter.py:1254-1312`), which prefers `from_user` and falls back to `sender_chat` for channel posts, normalizes `private→dm` and `supergroup→forum|group`, and keeps a `thread_id` only for real forum/DM topics. Decision order: (1) no `user_id` at all → `True` (service messages defer to the cold path); (2) adapter-level `config.extra["group_allow_from"]` (group/forum/channel) or `config.extra["allow_from"]` (DM) coerced by `gateway.authz_mixin._coerce_allow_set`, `*` allowed — when present this is the sole authority; (3) an INSTANCE-level `_is_callback_user_authorized` override (tests only, read from `self.__dict__`); (4) the runner chain — prefers the registered `_authorization_check` callback (`self._is_sender_authorized(user_id, chat_type=…, chat_id=…)`) over `self._message_handler.__self__._is_user_authorized(source)`, and returns `True` early when `_telegram_auth_env_configured()` is False so unknown DMs still reach pairing; (5) env-only fallback on `TELEGRAM_ALLOWED_USERS` (empty → allow). Finally, an unauthorized DM still passes when `_should_pass_unauthorized_dm_for_pairing(source)` is true.
- **Inputs / options:** `config.extra.allow_from`, `config.extra.group_allow_from`.
- **Outputs / side effects:** boolean; rejected updates are dropped silently (log only).
- **Config / env:** `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_GROUP_ALLOWED_USERS`, `TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_ALLOW_ALL_USERS`, `GATEWAY_ALLOWED_USERS`, `GATEWAY_ALLOW_ALL_USERS` — the exact tuple checked by `_telegram_auth_env_configured()` (`adapter.py:1368-1378`).
- **Edge cases / guards:** `_handle_command` runs `_should_process_message` BEFORE the auth check while text/media/location run auth first — an ordering asymmetry visible at `adapter.py:9941-9951`. Auth failures inside the runner chain log `Falling back to env-only auth for user %s` at debug.
- **Rebuild notes:** Authorize at intake, before any state write; keep an explicit "no allowlist configured" path so first-contact pairing still works.

### Unauthorized-DM pairing passthrough  `id: platform-telegram.pairing-passthrough`
- **Surface:** Core
- **Where:** First DM from an unknown user when DM pairing is enabled.
- **What it does:** Lets an unauthorized DM through the intake prefilter so the gateway's pairing handshake can run instead of silently dropping the message.
- **How it works:** `_should_pass_unauthorized_dm_for_pairing(source)` at `adapter.py:1380-1412`. Only for `chat_type == "dm"`. Prefers `runner._get_unauthorized_dm_behavior(Platform.TELEGRAM, profile=source.profile) == "pair"`; on exception logs `Failed to resolve unauthorized DM behavior; falling back to adapter-local override` and falls back to `str(config.extra["unauthorized_dm_behavior"]).lower() == "pair"`.
- **Inputs / options:** `platforms.telegram.extra.unauthorized_dm_behavior` (`pair` | other values).
- **Outputs / side effects:** message continues to the normal gating path.
- **Config / env:** `platforms.telegram.extra.unauthorized_dm_behavior`.
- **Edge cases / guards:** Group and channel sources never pass.
- **Rebuild notes:** Pairing must be reachable even with an allowlist configured, but only for DMs and only on explicit opt-in.

### `require_mention` — group trigger gate  `id: platform-telegram.require-mention`
- **Surface:** Config | Env
- **Where:** `telegram.require_mention` in `config.yaml`, `platforms.telegram.extra.require_mention`, or `TELEGRAM_REQUIRE_MENTION`.
- **What it does:** When on, the bot ignores ordinary group chatter and only answers when it is explicitly addressed.
- **How it works:** `_telegram_require_mention()` at `adapter.py:8886-8894`: reads `config.extra["require_mention"]` (strings coerced via `{"true","1","yes","on"}`), else `os.getenv("TELEGRAM_REQUIRE_MENTION", "false")`. Consumed by `_should_process_message`. Accepted triggers when on (documented at `telegram.md:552-560`): a reply to one of the bot's messages, an `@botusername` mention, `/command@botusername`, or a `mention_patterns` regex match.
- **Inputs / options:** boolean (`true`/`false`/`1`/`0`/`yes`/`on`).
- **Outputs / side effects:** gating only. Default **false** (open groups, previous behaviour).
- **Config / env:** `TELEGRAM_REQUIRE_MENTION`, `telegram.require_mention`, `platforms.telegram.extra.require_mention`. The YAML bridge also honours a top-level `require_mention` (`adapter.py:11180-11183`).
- **Edge cases / guards:** Slash commands get NO special treatment under `require_mention` — they must pass the same gate (which `/cmd@botname` and `@botname /cmd` both do).
- **Rebuild notes:** One boolean, evaluated after the allowlists and before the reply/mention/wake-word ladder.

### Bot-mention detection (entities first)  `id: platform-telegram.mention-detect`
- **Surface:** Core
- **Where:** Every group message when `require_mention`, `guest_mode` or exclusive routing is active.
- **What it does:** Decides whether this specific message addresses THIS bot, using Telegram's server-parsed entities rather than substring matching.
- **How it works:** `_message_mentions_bot(message)` at `adapter.py:9294-9348`. Iterates `(text, entities)` and `(caption, caption_entities)`. Accepts: `mention` entities whose text equals `@<current username>`; `text_mention` entities whose `user.id == bot.id` (users without a public handle); `bot_command` entities of the form `/cmd@botname` whose `@…` suffix matches (Telegram emits ONE `bot_command` entity, no separate mention — dropping this would break `/new`, `/reset`, `/help` in every `require_mention` group, #15415). Entity spans are extracted with `_telegram_entity_text(source_text, offset, length)` (`adapter.py:9282-9292`) which slices UTF-16 code units (`encode("utf-16-le")`, `offset*2 : (offset+length)*2`). If no entity matched, it falls back to `_extract_bot_mention_usernames(message, bot_username)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** boolean.
- **Config / env:** n/a.
- **Edge cases / guards:** Substring matches like `foo@hermes_bot.example` are NOT mentions (#12545); entities also handle handles inside URLs, code blocks and quotes correctly.
- **Rebuild notes:** Use the platform's own entity offsets, and slice by UTF-16 units — Python string indexes are wrong for emoji-bearing text.

### Foreign bot-handle extraction  `id: platform-telegram.bot-handle-extract`
- **Surface:** Core
- **Where:** Multi-bot groups; feeds `exclusive_bot_mentions`.
- **What it does:** Collects the set of bot usernames a message addresses, so a message meant for another bot can be ignored.
- **How it works:** `_extract_bot_mention_usernames(message, self_username="")` at `adapter.py:9212-9280`. A handle counts as bot-shaped when it equals our own handle (identity match — collectible Fragment usernames such as `@jarvis` need not end in `bot`) or matches `_FOREIGN_BOT_HANDLE_RE = re.compile(r"[a-z0-9_]{2,29}bot", re.IGNORECASE)` in full (`adapter.py:9207-9210`). Entities of type `mention` contribute the stripped handle; `bot_command` entities contribute the `@…` suffix. A narrow entity-less fallback scans raw text with `(?i)(?<![A-Za-z0-9_\`/])@([A-Za-z0-9_]{2,31})\b`, but ONLY when Telegram supplied no entities for that source (so malformed/URL/code spans are not rescued).
- **Inputs / options:** message, own username.
- **Outputs / side effects:** `set[str]` of lowercase handles.
- **Config / env:** n/a.
- **Edge cases / guards:** Human `@handles` never suppress routing because they are not bot-shaped.
- **Rebuild notes:** Match your own handle by identity, foreign handles by shape.

### `exclusive_bot_mentions` — deterministic multi-bot routing  `id: platform-telegram.exclusive-mentions`
- **Surface:** Config | Env
- **Where:** `telegram.exclusive_bot_mentions` / `platforms.telegram.extra.exclusive_bot_mentions` / `TELEGRAM_EXCLUSIVE_BOT_MENTIONS`. Default **true**.
- **What it does:** When a group message explicitly names one or more bots and none of them is this bot, this bot ignores the message — even if it is a reply to one of its own messages or matches a wake word.
- **How it works:** `_telegram_exclusive_bot_mentions()` at `adapter.py:8921-8929` (env default `"true"`); `_explicit_bot_mentions_exclude_self(message)` at `adapter.py:9377-9407` computes `mentioned = _extract_bot_mention_usernames(...)` and returns `bool(mentioned) and own not in mentioned`. When it excludes self it also fires `_schedule_bot_identity_recheck()` so a stale handle after a BotFather rename self-corrects. Checked in both `_should_process_message` (`adapter.py:9843-9844`) and `_should_observe_unmentioned_group_message` (`adapter.py:9464-9465`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** gating; possible background `getMe`.
- **Config / env:** `TELEGRAM_EXCLUSIVE_BOT_MENTIONS`, YAML bridge at `adapter.py:11186-11187`.
- **Edge cases / guards:** Set to `false` only for legacy groups where mentions should not override reply/wake-word triggers (`telegram.md:566-584`). Each profile needs its own bot token — Telegram rejects concurrent polling for one token.
- **Rebuild notes:** Treat explicit handles as an exclusive routing hint, and re-verify your own identity when you are about to drop a message because of it.

### `mention_patterns` — regex wake words  `id: platform-telegram.mention-patterns`
- **Surface:** Config | Env
- **Where:** `telegram.mention_patterns` (list) or `TELEGRAM_MENTION_PATTERNS` (JSON array, newline list, or comma list).
- **What it does:** Lets a group trigger the bot with a spoken name (`^\s*chompy\b`) instead of an `@mention`.
- **How it works:** `_compile_mention_patterns()` at `adapter.py:9039-9065`: reads `config.extra["mention_patterns"]`, else parses `TELEGRAM_MENTION_PATTERNS` as JSON, falling back to newline-split then comma-split; delegates to the shared `compile_mention_patterns(patterns, log_prefix=self.name, platform_label="telegram", display_label="Telegram", logger_=logger)`. Matching is `_message_matches_mention_patterns` (`adapter.py:9409-9418`) which runs `pattern.search()` over both `text` and `caption`.
- **Inputs / options:** any Python regex; matching is case-insensitive; anchor with `^` for prefix-only.
- **Outputs / side effects:** gating.
- **Config / env:** `TELEGRAM_MENTION_PATTERNS`; YAML bridge JSON-encodes the list (`adapter.py:11184-11185`).
- **Edge cases / guards:** Invalid regexes are logged and skipped, never fatal (`telegram.md:642-648`). Returns `[]` early when unset, before touching `self.name` (so bare test adapters work).
- **Rebuild notes:** Compile once at construction; check text and caption.

### `guest_mode` — @mention bypass for non-allowlisted groups  `id: platform-telegram.guest-mode`
- **Surface:** Config | Env
- **Where:** `telegram.guest_mode` / `platforms.telegram.extra.guest_mode` / `TELEGRAM_GUEST_MODE`. Default **false**.
- **What it does:** Allows a group that is NOT in `allowed_chats` to trigger the bot, but only through an explicit @mention, every turn.
- **How it works:** `_telegram_guest_mode()` at `adapter.py:8912-8920`; `_is_guest_mention(message)` at `adapter.py:9420-9426` = guest mode on AND `_message_mentions_bot(message)`. In `_should_process_message` the guest mention is resolved once (`adapter.py:9848`) and used as the sole bypass when `allowed and chat_id_str not in allowed` (`adapter.py:9853-9856`).
- **Inputs / options:** boolean.
- **Outputs / side effects:** gating only — no session stickiness, so the bot never auto-engages in a guest thread it was not pinged into.
- **Config / env:** `TELEGRAM_GUEST_MODE`; YAML bridge `adapter.py:11190-11191`; docs `telegram.md:1066-1092`.
- **Edge cases / guards:** Replies and wake words do NOT bypass `allowed_chats`; only the explicit mention does.
- **Rebuild notes:** Keep the bypass to one message at a time.

### `free_response_chats` — per-chat mention exemption  `id: platform-telegram.free-response-chats`
- **Surface:** Config | Env
- **Where:** `platforms.telegram.extra.free_response_chats` (list or CSV) / `TELEGRAM_FREE_RESPONSE_CHATS`.
- **What it does:** Marks whole chats where the bot answers every message even though `require_mention` is on globally.
- **How it works:** `_telegram_free_response_chats()` at `adapter.py:8930-8937`; list or comma-separated string → `set[str]`; env read through `_scoped_gate_env` so multiplex profiles do not borrow each other's lists. Checked at `adapter.py:9858-9859`, and it also suppresses observe-mode (`adapter.py:9475-9476`).
- **Inputs / options:** chat ids as strings (groups are negative).
- **Outputs / side effects:** gating.
- **Config / env:** `TELEGRAM_FREE_RESPONSE_CHATS`; YAML bridge seeds BOTH `extras["free_response_chats"]` and the env var (`adapter.py:11194-11200`).
- **Edge cases / guards:** Under multiplex the env bridge is skipped entirely (`_skip_env_bridge`) so a secondary profile's list never pins the process env.
- **Rebuild notes:** Accept list-or-CSV everywhere; read gate env vars through a profile-scoped accessor.

### `free_response_topics` — per-topic mention exemption  `id: platform-telegram.free-response-topics`
- **Surface:** Config | Env
- **Where:** `platforms.telegram.extra.free_response_topics` / `TELEGRAM_FREE_RESPONSE_TOPICS`; entries are `"<chat_id>:<thread_id>"`.
- **What it does:** Opens exactly one forum topic for free responses instead of the whole chat.
- **How it works:** `_telegram_free_response_topics()` at `adapter.py:8938-8950`; `_telegram_is_free_response_topic(message)` at `adapter.py:8952-8962` builds `f"{chat_id}:{thread_id or '1'}"` from `_effective_message_thread_id`, normalizing a missing thread id to the General topic `1`.
- **Inputs / options:** list or CSV of `chat:thread` pairs.
- **Outputs / side effects:** gating.
- **Config / env:** `TELEGRAM_FREE_RESPONSE_TOPICS`; YAML bridge at `adapter.py:11201-11206` plus an `extras` seed via the `_key` loop at `adapter.py:11242-11244`.
- **Edge cases / guards:** Also suppresses observe-mode for that topic.
- **Rebuild notes:** Compose the composite key with the same normalizer the router uses.

### `allowed_chats` — group response allowlist  `id: platform-telegram.allowed-chats`
- **Surface:** Config | Env
- **Where:** `platforms.telegram.extra.allowed_chats` / `TELEGRAM_ALLOWED_CHATS`.
- **What it does:** When non-empty, group/supergroup messages from chats outside the list are silently ignored (DMs are never filtered).
- **How it works:** `_telegram_allowed_chats()` at `adapter.py:8964-8977`; enforced at `adapter.py:9853-9856` as a hard gate whose only exception is a guest mention.
- **Inputs / options:** list or CSV of chat ids; empty means no restriction.
- **Outputs / side effects:** gating.
- **Config / env:** `TELEGRAM_ALLOWED_CHATS`; the YAML bridge deliberately does NOT seed `extras` (the shared-key loop in `gateway/config.py` already bridges it with the original type) — see the note at `adapter.py:11207-11215`.
- **Edge cases / guards:** Replies and wake words do not bypass it.
- **Rebuild notes:** Keep response allowlists separate from authorization allowlists.

### `group_allowed_chats` / `group_allow_from` — group authorization allowlists  `id: platform-telegram.group-allowlists`
- **Surface:** Config | Env
- **Where:** `platforms.telegram.extra.group_allowed_chats`, `platforms.telegram.extra.group_allow_from`, `TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_GROUP_ALLOWED_USERS`; documented at `telegram.md:1015-1064`.
- **What it does:** Two orthogonal group gates — a sender-scoped allowlist that grants group access without DM access, and a chat-scoped allowlist where group membership itself is the access signal.
- **How it works:** `_telegram_group_allowed_chats()` at `adapter.py:8979-8986`; `group_allow_from` is consumed by the intake prefilter (`adapter.py:1439-1447`) as the sole authority for group/forum/channel sources. `_telegram_observe_allowed_chats()` (`adapter.py:8988-9001`) intersects `group_allowed_chats` with `allowed_chats` when the latter is set, and is the allowlist observe-mode requires.
- **Inputs / options:** lists or CSV; `*` allows any sender/chat.
- **Outputs / side effects:** authorization decisions.
- **Config / env:** `TELEGRAM_ALLOWED_USERS` covers all chat types; `TELEGRAM_GROUP_ALLOWED_USERS` only groups/forums; `TELEGRAM_GROUP_ALLOWED_CHATS` authorizes every member of the listed chats.
- **Edge cases / guards:** Backward compatibility (documented, PR #17686): chat-ID-shaped values (leading `-`) placed in `TELEGRAM_GROUP_ALLOWED_USERS` are still honoured as chat ids with a one-time deprecation warning.
- **Rebuild notes:** Split sender-scope from chat-scope from day one; keep a migration path for the merged legacy variable.

### `allowed_topics` — forum topic allowlist  `id: platform-telegram.allowed-topics`
- **Surface:** Config | Env
- **Where:** `platforms.telegram.extra.allowed_topics` / `TELEGRAM_ALLOWED_TOPICS`.
- **What it does:** Restricts the bot to specific forum topics inside a group; messages from other topics are dropped.
- **How it works:** `_telegram_allowed_topics()` at `adapter.py:9003-9016`; checked first in `_should_process_message` (`adapter.py:9827-9831`) and in observe-mode (`adapter.py:9448-9453`), normalizing a missing `message_thread_id` to `1` (General) before comparing.
- **Inputs / options:** list or CSV of thread ids as strings.
- **Outputs / side effects:** gating. DMs are never filtered by topic.
- **Config / env:** `TELEGRAM_ALLOWED_TOPICS`; YAML bridge at `adapter.py:11216-11222`.
- **Edge cases / guards:** Uses `_effective_message_thread_id` in `_should_process_message` but the RAW `message_thread_id` in `_should_observe_unmentioned_group_message` (`adapter.py:9448`).
- **Rebuild notes:** Normalize General-topic identity once, in one helper.

### `ignored_threads` — hard topic mute  `id: platform-telegram.ignored-threads`
- **Surface:** Config | Env
- **Where:** `telegram.ignored_threads` / `platforms.telegram.extra.ignored_threads` / `TELEGRAM_IGNORED_THREADS`.
- **What it does:** Keeps the bot silent in specific forum topics even when the chat would otherwise allow free responses or mention triggers.
- **How it works:** `_telegram_ignored_threads()` at `adapter.py:9018-9037` parses list or CSV into `set[int]`, logging `Ignoring invalid Telegram thread id: %r` for unparsable entries. Enforced before the mention/free-response ladder in `_should_process_message` (`adapter.py:9834-9839`) and in observe-mode (`adapter.py:9455-9460`).
- **Inputs / options:** integers or numeric strings (the docs example mixes `31` and `"42"`).
- **Outputs / side effects:** gating.
- **Config / env:** `TELEGRAM_IGNORED_THREADS`; YAML bridge seeds both extras and env (`adapter.py:11223-11229`).
- **Edge cases / guards:** A non-numeric inbound `message_thread_id` logs `Ignoring non-numeric Telegram message_thread_id: %r` and does not mute.
- **Rebuild notes:** Apply mutes before every allow rule.

### `observe_unmentioned_group_messages` — silent group context  `id: platform-telegram.observe-mode`
- **Surface:** Config | Env
- **Where:** `telegram.observe_unmentioned_group_messages` (legacy alias `ingest_unmentioned_group_messages`) / `TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES`. Default **false**.
- **What it does:** With `require_mention` on, ordinary group chatter is written into the session transcript as context (never dispatched), so a later @mention can refer to it.
- **How it works:** `_telegram_observe_unmentioned_group_messages()` at `adapter.py:8895-8910`. `_should_observe_unmentioned_group_message(message)` at `adapter.py:9436-9487` requires, in order: not our own message; observe enabled; a group chat; topic passes `allowed_topics`; thread not in `ignored_threads`; not excluded by `exclusive_bot_mentions`; chat present in `_telegram_observe_allowed_chats()` (an explicit `group_allowed_chats` entry is mandatory); NOT a free-response chat/topic; `require_mention` on; not a reply to the bot; no bot mention; no wake-word match. `_observe_unmentioned_group_message` (`adapter.py:9727-9760`) then builds the event, replaces the source with the chat/topic-scoped shared source (`user_id=None, user_name=None, user_id_alt=None`, `adapter.py:9489-9491`), calls `store.get_or_create_session(shared_source)` and appends `{"role": "user", "content": "[<sender>|<user_id>]\n<text>", "timestamp": <ISO-8601 UTC>, "observed": True, "message_id": …}` to the transcript, logging `Telegram group message observed (no bot trigger): chat=%s from=%s`.
- **Inputs / options:** boolean.
- **Outputs / side effects:** transcript rows flagged `observed: True`; no agent run.
- **Config / env:** `TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES`; YAML bridge at `adapter.py:11192-11193` and the extras loop at `adapter.py:11242-11244`.
- **Edge cases / guards:** Observed rows are replayed as a SEPARATE context block, not as user turns — `gateway/run.py:1730-1743` `_uses_telegram_observed_group_context` detects the marker `observed Telegram group context` in the channel prompt and splits them out under the headers `[Observed Telegram group context - context only, not requests]` and `[Current addressed message - answer only this unless it explicitly asks you to use the observed context]` (`gateway/run.py:1731-1733`).
- **Rebuild notes:** Store observations under a shared chat-scoped session so a later trigger from a different user still sees them; mark rows so the run path can present them as context, not requests.

### Observed-group attribution and channel prompt  `id: platform-telegram.observe-attribution`
- **Surface:** Core
- **Where:** Triggered group turns in a chat where observe-mode is active.
- **What it does:** Rewrites the triggering message the same way observed rows are written (`[name|id]` prefix, shared source) and appends an explanatory channel prompt so the model knows what the observed block is.
- **How it works:** `_apply_telegram_group_observe_attribution(event)` at `adapter.py:9510-9541`. Prompt text (`adapter.py:9498-9508`): `"You are handling a Telegram group chat message.\n- Your identity: user_id=<bot id>, @-mention name in this group=@<username>\n- observed Telegram group context may be provided in a separate context-only block before the current message; it is not necessarily addressed to you.\n- Treat only the current new message as a request explicitly directed at you, and use observed context only when the current message asks for it."` Attributed text format: `f"[{sender}|{user_id}]\n{text}"` (`adapter.py:9493-9496`).
- **Inputs / options:** the built `MessageEvent`.
- **Outputs / side effects:** replaced `text`, `source`, and `channel_prompt`.
- **Config / env:** same as observe mode.
- **Edge cases / guards:** `MessageType.COMMAND` events keep their ORIGINAL source (with `user_id`) and only get the channel prompt — anonymising them would make `SlashAccessPolicy.is_admin(None)` deny admin commands like `/new`.
- **Rebuild notes:** Keep identity on command events; anonymise only the shared conversational context.

### `_should_process_message()` — the full group decision ladder  `id: platform-telegram.should-process`
- **Surface:** Core
- **Where:** Every inbound text, command, media and location update.
- **What it does:** Single decision point for "does this message get a reply?".
- **How it works:** `adapter.py:9779-9871`, in exact order: (1) `_observe_bot_identity_from_message(message)` learns the live handle first; (2) own message → False; (3) not a group → True (DM fast path, before topic checks); (4) `allowed_topics` check on `_effective_message_thread_id`; (5) `ignored_threads` check; (6) a second `not self._is_group_chat(...)` block handles root-DM `ignore_root_dm`; (7) `exclusive_bot_mentions` exclusion → False; (8) resolve `guest_mention` once; (9) `allowed_chats` hard gate → returns `guest_mention`; (10) guest mention → True; (11) `free_response_chats` → True; (12) `free_response_topics` → True; (13) `require_mention` off → True; (14) reply to the bot → True; (15) `_message_mentions_bot` (skipped when guest mode already evaluated it) → True; (16) `_message_matches_mention_patterns`.
- **Inputs / options:** `is_command` flag (only used by the `ignore_root_dm` branch).
- **Outputs / side effects:** boolean.
- **Config / env:** every gate listed in this section.
- **Edge cases / guards:** Steps 3 and 6 are both "not a group" checks — step 6 is only reachable for DMs, which is where `ignore_root_dm` applies.
- **Rebuild notes:** Encode the ladder as one readable function with the mutes first, the hard allowlist next, and the triggers last.

### `ignore_root_dm` — DM lobby for topic users  `id: platform-telegram.ignore-root-dm`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.ignore_root_dm: true` alongside `dm_topics`.
- **What it does:** Turns the root DM into a lobby for users who have configured DM topics — ordinary messages there are silently ignored while system commands still work.
- **How it works:** `adapter.py:9841-9846`: when the message has no thread id, `config.extra["ignore_root_dm"]` is truthy, the message is NOT a command, and the chat id is in `self._dm_topic_chat_ids` (precomputed in `__init__` at `adapter.py:864-868` from `dm_topics`), the message is dropped.
- **Inputs / options:** boolean.
- **Outputs / side effects:** gating.
- **Config / env:** `platforms.telegram.extra.ignore_root_dm`, `platforms.telegram.extra.dm_topics`; docs `telegram.md:711-731`.
- **Edge cases / guards:** Strictly per-chat — users without configured topics are unaffected. Commands (`/start`, `/help`, `/status`, …) always pass.
- **Rebuild notes:** Gate on "this user has topics" so the lobby never traps someone who never opted in.

### Own-message filter  `id: platform-telegram.own-message`
- **Surface:** Core
- **Where:** Groups/supergroups where `getUpdates` echoes the bot's own posts.
- **What it does:** Drops the bot's own messages so they are not counted as incoming unread messages in the Hermes inbox.
- **How it works:** `_is_own_message(message)` at `adapter.py:9762-9777` compares `message.from_user.id` to `self._bot.id`. Called from `_should_process_message` and `_should_observe_unmentioned_group_message`.
- **Inputs / options:** n/a. **Outputs / side effects:** boolean.
- **Config / env:** n/a.
- **Edge cases / guards:** Fixes #52363 (outbound messages counted as unread inbound).
- **Rebuild notes:** Always filter self-echo before any accounting.

### Trigger-text cleanup (`@botname` stripping)  `id: platform-telegram.clean-trigger`
- **Surface:** Core
- **Where:** Text and command events after gating.
- **What it does:** Removes the leading `@botname` (plus trailing `,`/`:`/`-` and whitespace) so the agent sees the request, not the address.
- **How it works:** `_clean_bot_trigger_text(text)` at `adapter.py:9428-9434`: `re.sub(rf"(?i)@{re.escape(username)}\b[,:\-]*\s*", "", text).strip()`, returning the original text when the result is empty.
- **Inputs / options:** the raw text/caption.
- **Outputs / side effects:** `event.text`.
- **Config / env:** n/a.
- **Edge cases / guards:** A message that is ONLY a mention keeps its original text rather than becoming empty.
- **Rebuild notes:** Strip every occurrence, not just the prefix, but never produce an empty prompt.

### Live bot-handle tracking from inbound messages  `id: platform-telegram.identity-observe`
- **Surface:** Core
- **Where:** Invisible; keeps mention routing correct after a BotFather rename.
- **What it does:** Learns the bot's current `@username` from inbound updates so mention comparisons keep matching without an extra `getMe`.
- **How it works:** `_current_bot_username()` (`adapter.py:9110-9124`) prefers `self._bot_username_observed` over PTB's cached `Bot.username`; `_note_bot_username(username)` (`adapter.py:9126-9142`) records it and logs real renames; `_observe_bot_identity_from_message(message)` (`adapter.py:9143-9163`) reads the handle Telegram stamps on our own messages and on `reply_to_message`; `_bot_identity_is_fresh()` / `_refresh_bot_identity(force=False)` (`adapter.py:9165-9203`) bound `getMe` calls to one per `_BOT_IDENTITY_TTL_SECONDS = 300.0` with `_BOT_IDENTITY_PROBE_TIMEOUT = 15.0`; `_schedule_bot_identity_recheck()` (`adapter.py:9350-9375`) fires a TTL-guarded background refresh when routing is about to discard a message whose named bots exclude us.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `getMe` traffic bounded to one call per 5 minutes; debug log `Telegram identity refresh failed (keeping @%s): %s`.
- **Config / env:** n/a.
- **Edge cases / guards:** `_bot_identity_checked_at` is `None` (never `0.0`) so a freshly booted host does not read as "checked just now". The refresh task is tracked in `self._background_tasks` and discarded on completion.
- **Rebuild notes:** Never trust an SDK's cached identity for routing decisions; re-check exactly when a routing decision depends on it.

### Thread-id normalization (`_effective_message_thread_id`)  `id: platform-telegram.thread-normalize`
- **Surface:** Core
- **Where:** Gating, session keys, skill binding and outbound routing all read this one value.
- **What it does:** Converts Telegram's ambiguous `message_thread_id` into a routable topic id, or `None`.
- **How it works:** `adapter.py:9075-9108`. With a raw value present: keep it for forum supergroups, for group/supergroup messages flagged `is_topic_message`, and for private chats flagged `is_topic_message`; otherwise return `None` (plain group/DM replies carry a reply-UI anchor id in `message_thread_id` that is NOT a routing id, #3206). With no raw value: forum groups return `_GENERAL_TOPIC_THREAD_ID = "1"` so replies go back to General (#22423); everything else returns `None`.
- **Inputs / options:** a `Message`.
- **Outputs / side effects:** `Optional[str]`.
- **Config / env:** n/a.
- **Edge cases / guards:** Sends map `"1"` back to `None` (`_message_thread_id_for_send`) but typing keeps it (`_message_thread_id_for_typing`).
- **Rebuild notes:** One normalizer used by every consumer; document the General-topic asymmetry.

### Channel posts and `effective_message`  `id: platform-telegram.channel-posts`
- **Surface:** Core
- **Where:** Broadcast channels where the bot is an admin.
- **What it does:** Makes handlers read `update.effective_message` so channel posts (delivered as `update.channel_post`) are not consumed without building an event.
- **How it works:** `_effective_update_message(update)` at `adapter.py:9898-9906` returns `update.effective_message or update.message`. Used by `_handle_text_message`, `_handle_command` and `_handle_location_message`. Channel sources are authorized via `sender_chat` in `_source_from_message_for_auth`, and `_build_message_event` maps `ChatType.CHANNEL` to `chat_type="channel"` with `user_id = chat.id` and `user_name = chat.title`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** channel posts route like normal messages.
- **Config / env:** n/a.
- **Edge cases / guards:** `_handle_media_message` still reads `update.message` directly, so channel media posts are not processed.
- **Rebuild notes:** Use the SDK's `effective_message` everywhere or nowhere.

---

## 8. Inbound handling: batching, media ingestion, stickers, events

### Text message handler  `id: platform-telegram.handle-text`
- **Surface:** Core
- **Where:** Every non-command text message the bot receives.
- **What it does:** Authorizes, gates, cleans the trigger text, attaches replied-to media, applies observe attribution, and hands the event to the text batcher.
- **How it works:** `_handle_text_message(update, context)` at `adapter.py:9908-9939`. Order: `_effective_update_message` → bail when there is no `.text`; `_is_user_authorized_from_message` (log `Blocked unauthorized user %s in chat %s`); `_should_process_message` (falling through to `_observe_unmentioned_group_message(msg, MessageType.TEXT, update_id=…)` when observe-mode applies); `_ensure_forum_commands(update.message)`; `_build_message_event(msg, MessageType.TEXT, update_id=update.update_id)`; `event.text = self._clean_bot_trigger_text(event.text)`; `await self._cache_replied_media(msg, event)`; `_apply_telegram_group_observe_attribution(event)`; `self._enqueue_text_event(event)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** buffered event; possible observed transcript row.
- **Config / env:** all gating keys from section 7.
- **Edge cases / guards:** `_ensure_forum_commands` is called with `update.message` here (not the effective message), so a channel post cannot trigger forum registration.
- **Rebuild notes:** Keep the order auth → gate → build → batch; never build an event for an unauthorized sender.

### Command message handler  `id: platform-telegram.handle-command`
- **Surface:** Core
- **Where:** Every message Telegram tags with a `bot_command` entity (`/help`, `/model`, `/topic`, skill commands…).
- **What it does:** Runs the same gates as text, then dispatches immediately — unless the command is near Telegram's 4096-char split point, in which case it joins the text batch so continuation chunks merge in first.
- **How it works:** `_handle_command(update, context)` at `adapter.py:9941-9973`. Note the inverted order versus text: `_should_process_message(msg, is_command=True)` runs BEFORE `_is_user_authorized_from_message`. Then `_ensure_forum_commands(msg)`, `_build_message_event(msg, MessageType.COMMAND, …)`, trigger-text cleanup, `_cache_replied_media`, observe attribution, and finally: `if len(event.text or "") >= self._SPLIT_THRESHOLD: self._enqueue_text_event(event); return` else `await self.handle_message(event)`. `_SPLIT_THRESHOLD = 4000` (`adapter.py:626-628`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** immediate dispatch or buffered event.
- **Config / env:** n/a.
- **Edge cases / guards:** Short control commands (`/stop`, `/approve`) are never delayed. A long `/queue <huge prompt>` would otherwise orphan its continuation, which would then interrupt the running agent.
- **Rebuild notes:** Route only near-limit commands through the batcher.

### Location and venue pins  `id: platform-telegram.handle-location`
- **Surface:** Core
- **Where:** User taps 📎 → Location (or shares a venue). The agent receives a synthetic text turn.
- **What it does:** Converts a location/venue message into a text prompt with coordinates, a map link and an instruction to ask what the user wants nearby.
- **How it works:** `_handle_location_message(update, context)` at `adapter.py:9975-10020`. Reads `msg.venue.location` when a venue is present, else `msg.location`; requires both `latitude` and `longitude`. Builds exactly these lines: `[The user shared a location pin.]`, then (venue only) `Venue: <title>` and `Address: <address>`, then `latitude: <lat>`, `longitude: <lon>`, `Map: https://www.google.com/maps/search/?api=1&query=<lat>,<lon>`, `Ask what they'd like to find nearby (restaurants, cafes, etc.) and any preferences.` The event is `MessageType.LOCATION`, gets observe attribution and dispatches immediately.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one agent turn.
- **Config / env:** n/a.
- **Edge cases / guards:** Unauthorized senders are blocked first; skipped group pins can be observed (`MessageType.LOCATION`); a location without coordinates is dropped silently. Registration uses `filters.LOCATION | filters.VENUE`, falling back to `filters.LOCATION` alone on SDKs without `VENUE`.
- **Rebuild notes:** Emit a machine-readable coordinate line plus a human map link, and tell the model what to do next.

### Text batching (Telegram client-side splits)  `id: platform-telegram.text-batching`
- **Surface:** Core | Env
- **Where:** Invisible; makes a long pasted message arrive as ONE agent turn. Log: `[Telegram] Flushing text batch %s (%d chars)`.
- **What it does:** Buffers rapid successive text messages from the same session and concatenates them before dispatch, with adaptive delays so short messages still feel instant.
- **How it works:** `_text_batch_key(event)` (`adapter.py:10026-10040`) applies `_apply_topic_recovery(event)` first, then `gateway.session.build_session_key(source, group_sessions_per_user=extra.get("group_sessions_per_user", True), thread_sessions_per_user=extra.get("thread_sessions_per_user", False), profile=self._session_key_profile(source))`. `_enqueue_text_event` (`adapter.py:10042-10076`) stores or appends (`existing.text = f"{existing.text}\n{event.text}"`), records `_last_chunk_len`, merges `media_urls`/`media_types`, cancels the prior flush task and starts a new one. `_flush_text_batch(key)` (`adapter.py:10078-10131`) picks the delay tier: last chunk ≥ `_SPLIT_THRESHOLD` (4000) → `_text_batch_split_delay_seconds`; total ≤ `_TEXT_BATCH_FAST_LEN` (320) → `min(cap, _TEXT_BATCH_FAST_DELAY_S=0.18)`; total ≤ `_TEXT_BATCH_SHORT_LEN` (1024) → `min(cap, _TEXT_BATCH_SHORT_DELAY_S=0.24)`; else the cap. Constants at `adapter.py:663-668`.
- **Inputs / options:** `HERMES_TELEGRAM_TEXT_BATCH_DELAY_SECONDS` (default **0.3**, clamped 0.08–2.0) and `HERMES_TELEGRAM_TEXT_BATCH_SPLIT_DELAY_SECONDS` (default **1.0**, clamped `[cap, 4.0]`), both read via `_env_float_clamped` (`adapter.py:669-695`) which rejects NaN/Inf.
- **Outputs / side effects:** one merged `MessageEvent` per quiet period.
- **Config / env:** the two env vars above; `group_sessions_per_user`, `thread_sessions_per_user`.
- **Edge cases / guards:** When the adapter is disconnected the event is held instead (`_hold_inbound_event(event, where="text-enqueue"|"text-flush")`); a cancellation after the pop but before dispatch holds the event with `where="text-flush-cancelled"` and re-raises, so nothing is silently lost.
- **Rebuild notes:** Debounce per session key with adaptive tiers; never drop a buffered event on cancel.

### Photo burst batching  `id: platform-telegram.photo-batching`
- **Surface:** Core | Env
- **Where:** Sending several photos quickly (not as an album). Log: `[Telegram] Flushing photo batch %s with %d image(s)`.
- **What it does:** Merges a burst of separate photo messages into a single event so the agent is not interrupted by each image.
- **How it works:** `_photo_batch_key(event, msg)` (`adapter.py:10137-10149`) = session key + `:album:<media_group_id>` when present, else `:photo-burst`. `_enqueue_photo_event` (`adapter.py:10175-10194`) extends `media_urls`/`media_types` and merges captions with the base `_merge_caption` (line-by-line dedupe). `_flush_photo_batch` (`adapter.py:10151-10173`) sleeps `self._media_batch_delay_seconds` then dispatches.
- **Inputs / options:** `HERMES_TELEGRAM_MEDIA_BATCH_DELAY_SECONDS` (default **0.8**, `adapter.py:759`).
- **Outputs / side effects:** one event with N media paths.
- **Config / env:** as above.
- **Edge cases / guards:** Same hold-on-disconnect and hold-on-cancel behaviour as the text batcher (`where="photo-enqueue"|"photo-flush"|"photo-flush-cancelled"`).
- **Rebuild notes:** Key bursts by session and album id so two albums never merge.

### Album (media group) debounce  `id: platform-telegram.media-group-inbound`
- **Surface:** Core
- **Where:** Sending an album; Telegram delivers each item as a separate update sharing `media_group_id`.
- **What it does:** Waits briefly and merges all album items into one logical event so the second image does not interrupt the first turn.
- **How it works:** `_queue_media_group_event(media_group_id, event)` (`adapter.py:10496-10523`) and `_flush_media_group_event` (`adapter.py:10525-10546`) with `MEDIA_GROUP_WAIT_SECONDS = 0.8` (`adapter.py:630`). Each new item cancels the prior flush task; media lists are extended and captions merged via `_merge_caption`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one event carrying every album item.
- **Config / env:** n/a (fixed 0.8 s).
- **Edge cases / guards:** Held on disconnect (`where="media-group-enqueue"|"media-group-flush"|"media-group-flush-cancelled"`).
- **Rebuild notes:** Debounce on the platform's own album id, not on timing alone.

### Inbound media handler (photos, voice, audio, video, documents)  `id: platform-telegram.handle-media`
- **Surface:** Core
- **Where:** Any attachment sent to the bot. Cache logs: `[Telegram] Cached user photo at %s`, `Cached user voice at %s`, `Cached user audio at %s`, `Cached user video at %s`, `Cached user image-document at %s`, `Cached user video document at %s`, `Cached user %s at %s (%s)`.
- **What it does:** Downloads each attachment into Hermes's local cache (so tools can read it after Telegram's ~1 h file URLs expire), classifies it, injects text content for text-like documents, and routes photos through the batchers.
- **How it works:** `_handle_media_message(update, context)` at `adapter.py:10196-10494`. Auth first, then `_should_process_message` (with an observe branch that caches media via `_cache_observed_media`). `msg_type = self._media_message_type(msg)` (`adapter.py:9543-9555`: sticker → STICKER, photo → PHOTO, video → VIDEO, audio → AUDIO, voice → VOICE, else DOCUMENT). Caption becomes `event.text` after `_clean_bot_trigger_text`. Branches: **sticker** → `_handle_sticker` then immediate dispatch; **photo** → largest `PhotoSize` (`msg.photo[-1]`), `download_as_bytearray()`, extension sniffed from `file_obj.file_path` among `.png/.webp/.gif/.jpeg/.jpg` (default `.jpg`), `cache_image_from_bytes`, then album queue or photo batch; **voice** → size guard, `cache_audio_from_bytes(ext=".ogg")`, `media_types=["audio/ogg"]`; **audio** → size guard, `cache_audio_from_bytes(ext=".mp3")`, `["audio/mp3"]`; **video** → size guard, extension from `SUPPORTED_VIDEO_TYPES` (`.mp4→video/mp4`, `.mov→video/quicktime`, `.webm→video/webm`, `.mkv→video/x-matroska`, `.avi→video/x-msvideo`), `cache_video_from_bytes`; **document** → extension from filename else reverse-lookup from MIME (`_TELEGRAM_IMAGE_MIME_TO_EXT` at `adapter.py:267-280`, then `SUPPORTED_DOCUMENT_TYPES`), size check FIRST, then image-documents (`ext in {.png,.jpg,.jpeg,.webp,.gif}` or `mime.startswith("image/")`) routed to the photo path with `message_type = PHOTO`, then video documents, then the generic `cache_media_bytes(raw_bytes, filename=…, mime_type=…)` path which tags unknown types `application/octet-stream`. Text-like documents (`ext in _TEXT_INJECT_EXTENSIONS` — `.txt .md .markdown .csv .tsv .log .json .jsonl .ndjson .xml .yaml .yml .toml .ini .cfg .conf .env .properties .html .htm .css .scss .sass .less .py .pyi .js .mjs .cjs .ts .tsx .jsx .sh .bash .zsh .fish .ps1 .bat .c .h .cpp .cc .hpp .cs .java .kt .go .rs .rb .php .pl .lua .r .jl .swift .m .scala .clj .ex .exs .erl .sql .graphql .proto .tf .hcl .dockerfile .makefile .cmake .gradle .rst .tex .srt .vtt .diff .patch` — or `mime.startswith("text/")`) up to `MAX_TEXT_INJECT_BYTES = 100 * 1024` are decoded as UTF-8 and prepended as `[Content of <sanitised name>]:\n<text>`; the display name is sanitised with `re.sub(r'[^\w.\- ]', '_', name)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** files under the Hermes cache dirs (`cache/images`, `cache/audio`, `cache/videos`, `cache/documents`); one `MessageEvent` with `media_urls`/`media_types`.
- **Config / env:** `_max_doc_bytes` (20 MB, or 2 GB with `extra.base_url`).
- **Edge cases / guards:** Any file type is accepted — "authorization to message the agent is the gate, not the file extension". Image documents that fail validation return `Image document '<name>' could not be read as an image.`; a failed `cache_media_bytes` returns `Document '<name>' could not be cached.`; binary files are surfaced as a cached path only (no inline injection) because a blind UTF-8 decode would false-positive on PDF/zip/docx headers. Every download failure routes to `_surface_media_cache_failure`. The dead `SUPPORTED_IMAGE_DOCUMENT_TYPES` branch is documented as unreachable in a code comment (`adapter.py:10412-10416`).
- **Rebuild notes:** Cache first, classify second, inject text only for allow-listed text extensions; never let an image bypass the document size limit by taking the image path.

### Media download failure surfacing  `id: platform-telegram.media-failure`
- **Surface:** Core
- **Where:** Telegram CDN download errors. The user gets a reply: `⚠️ Couldn't download your <kind>( (<name>))? (<ExceptionClass>). Please try sending it again.` The agent gets `[The user attempted to send a <kind>( (<name>))? but it could not be downloaded (<ExceptionClass>); they have been asked to retry.]`
- **What it does:** Makes a failed attachment visible on both ends instead of dispatching a silently empty turn.
- **How it works:** `_surface_media_cache_failure(msg, event, kind, exc, display_name=None)` at `adapter.py:9686-9725`; `msg.reply_text(...)` for the user and `_append_observed_note(event.text, note)` for the agent. Kinds used: `photo`, `voice message`, `audio file`, `video file`, `attachment`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one Telegram reply; modified `event.text`.
- **Config / env:** n/a.
- **Edge cases / guards:** A failing reply logs `Failed to notify user about %s cache failure: %s`. No new event fields are added (structured events deferred, #23045).
- **Rebuild notes:** Never let a download failure become an empty turn.

### Observed-group media caching  `id: platform-telegram.observed-media`
- **Surface:** Core
- **Where:** Attachments in group messages that do not trigger the bot but are being observed. Log: `[Telegram] Cached observed group %s at %s`.
- **What it does:** Downloads passive group attachments into the media cache and annotates the observed transcript row with a context note.
- **How it works:** `_cache_observed_media(msg, event)` at `adapter.py:9557-9613`. Source resolution via `_observed_media_source(msg)` (`adapter.py:9663-9677`): photo → `msg.photo[-1]` kind `image`; video → `video/mp4` kind `video`; voice → `voice.ogg`, `audio/ogg`, kind `audio`; audio → its `file_name`, kind `audio`; document → filename + lowercased mime, kind `None`. Size is bounded by `_max_doc_bytes`; failures append `[Observed Telegram attachment too large or unverifiable. Maximum: <N> MB.]` and log `Observed group attachment skipped (size=%s)`. On success `gateway.platforms.base.cache_media_bytes(...)` returns a record whose `kind` sets `event.message_type` (image→PHOTO, video→VIDEO, audio→AUDIO) and whose `context_note()` is appended to the text. A `None` result appends `[Observed Telegram attachment could not be read, not cached.]`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** cached file; annotated observed row.
- **Config / env:** `_max_doc_bytes`.
- **Edge cases / guards:** Download errors log `Failed to cache observed group media: …` and return without a note.
- **Rebuild notes:** Same size ceiling as the addressed path; annotate rather than silently drop.

### Replied-to media caching  `id: platform-telegram.replied-media`
- **Surface:** Core
- **Where:** Replying to an image/file with a question. Note appended to the turn: `[Replied-to <kind> '<display name>' saved at: <path>]`. Log: `[Telegram] Cached replied-to %s at %s`.
- **What it does:** Pulls the attachment from the message being replied to into the current turn, so "what does this say?" works.
- **How it works:** `_cache_replied_media(msg, event)` at `adapter.py:9615-9661`; reuses `_observed_media_source(reply_msg)` and `cache_media_bytes`, APPENDS to `event.media_urls`/`media_types`, and only sets `event.message_type` when this is the first attachment.
- **Inputs / options:** n/a.
- **Outputs / side effects:** extra media path on the event.
- **Config / env:** `_max_doc_bytes`.
- **Edge cases / guards:** Silently skips when the replied-to message has no media, when the size is unknown/oversized, or when caching fails (logged as `Failed to cache replied-to media: …`).
- **Rebuild notes:** Append rather than replace so a reply-with-photo carries both.

### Sticker understanding with vision + cache  `id: platform-telegram.stickers`
- **Surface:** Core
- **Where:** Any sticker sent to the bot. Injected text: `[The user sent a sticker <emoji> from "<set>"~ It shows: "<description>" (=^.w.^=)]`; animated/video stickers get `[The user sent an animated sticker <emoji>~ I can't see animated ones yet, but the emoji suggests: <emoji>]` or `[The user sent an animated sticker~ I can't see animated ones yet]`.
- **What it does:** Describes static stickers through the vision tool so the agent understands them, and caches descriptions by Telegram's stable `file_unique_id`.
- **How it works:** `_handle_sticker(msg, event)` at `adapter.py:10548-10611`. Animated/video stickers short-circuit to `build_animated_sticker_injection(emoji)`. Otherwise `get_cached_description(file_unique_id)` is consulted (log `Sticker cache hit: %s`); on a miss the WEBP is downloaded, cached with `cache_image_from_bytes(ext=".webp")` (log `Analyzing sticker at %s`), and analysed by `tools.vision_tools.vision_analyze_tool(image_url=cached_path, user_prompt=STICKER_VISION_PROMPT)`. `STICKER_VISION_PROMPT` (`gateway/sticker_cache.py:22-26`) is `"Describe this sticker in 1-2 sentences. Focus on what it depicts -- character, action, emotion. Be concise and objective."` Successful results are stored via `cache_sticker_description(file_unique_id, description, emoji, set_name)` in `~/.hermes/sticker_cache.json` (atomic write with `mkstemp` + `fsync` + `os.replace`, `gateway/sticker_cache.py:38-56`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** `~/.hermes/sticker_cache.json` entries `{description, emoji, set_name, …}`; cached WEBP file.
- **Config / env:** vision provider config (sibling shard).
- **Edge cases / guards:** Vision failure or any exception (`Sticker analysis error: …`) falls back to `a sticker with emoji <emoji>` or `a sticker`.
- **Rebuild notes:** Key the cache on the platform's stable sticker id, not the file id; keep the prompt short to bound token cost.

### `_build_message_event()` — inbound event construction  `id: platform-telegram.build-event`
- **Surface:** Core
- **Where:** Every inbound message.
- **What it does:** Converts a Telegram `Message` into Hermes's platform-neutral `MessageEvent`, resolving chat type, topic identity, skill binding, reply context and channel prompt.
- **How it works:** `adapter.py:10781-10949`. Chat type: `group`/`supergroup` → `group`, `channel` → `channel`, else `dm`. `thread_id_str = _effective_message_thread_id(message)`. For DM topics it calls `_get_dm_topic_info(chat.id, thread_id)` to fill `chat_topic` and `topic_skill`, and inspects `message.forum_topic_created.name` to discover topics created outside the config (caching them via `_cache_dm_topic_from_message`). For group topics it reads `config.extra["group_topics"]`, accepting BOTH the list shape `[{"chat_id":…, "topics":[…]}]` and the legacy mapping shape `{"-100…": [ … ]}`, matching on `thread_id`. The source is built with `self.build_source(chat_id, chat_name=chat.title or chat.full_name, chat_type, user_id (falling back to chat.id for dm/channel), user_name (user.full_name, else chat.full_name for DMs / chat.title for channels), thread_id, chat_topic, message_id, is_bot)`. Reply context prefers Telegram's native partial quote `message.quote.text` (so quoting one line of a long message does not inject the whole message, #22619), then `reply_to_message.text or .caption`, then `_extract_rich_reply_text(reply_to_message)` (flattening Telegram's own `rich_message` echo), then `gateway.rich_sent_store.lookup(chat_id, reply_to_id)`. Channel prompt comes from `gateway.platforms.base.resolve_channel_prompt(config.extra, thread_id or chat_id, chat_id if thread_id else None)`. Returns `MessageEvent(text=message.text or "", message_type, source, raw_message, message_id, platform_update_id=update_id, reply_to_message_id, reply_to_text, auto_skill=topic_skill, channel_prompt, timestamp=message.date)`.
- **Inputs / options:** `message`, `msg_type`, `update_id`.
- **Outputs / side effects:** a `MessageEvent`.
- **Config / env:** `platforms.telegram.extra.group_topics`, `platforms.telegram.extra.dm_topics`, `telegram.channel_prompts`.
- **Edge cases / guards:** `platform_update_id` is threaded through so `/restart` can record the triggering offset and the new process can advance past it (preventing `/restart` from being redelivered when PTB's graceful-shutdown ACK fails).
- **Rebuild notes:** Carry the update id; prefer the platform's partial quote; resolve skill binding at event-build time so the session sees it on turn one.

### Per-channel and per-topic prompts  `id: platform-telegram.channel-prompts`
- **Surface:** Config
- **Where:** `telegram.channel_prompts` in `config.yaml`, keyed by chat id (group/supergroup) or forum topic id; documented at `telegram.md:1247-1268`.
- **What it does:** Injects an ephemeral system prompt for specific Telegram groups or topics on every turn without ever persisting it to the transcript.
- **How it works:** `_build_message_event` calls `resolve_channel_prompt(self.config.extra, thread_id_str or chat_id_str, chat_id_str if thread_id_str else None)` (`adapter.py:10921-10928`) — the topic-level entry wins, with the group-level entry as fallback.
- **Inputs / options:** mapping of id → prompt text.
- **Outputs / side effects:** `event.channel_prompt`.
- **Config / env:** `telegram.channel_prompts` (numeric YAML keys are normalized to strings).
- **Edge cases / guards:** A group with no entry gets no channel prompt; observe-mode appends its own prompt to whatever this resolves.
- **Rebuild notes:** Two-level lookup (topic then chat), runtime injection only.

### Message reactions as processing feedback  `id: platform-telegram.reactions`
- **Surface:** Config | Env
- **Where:** `telegram.reactions: true` or `TELEGRAM_REACTIONS=true`. The user sees 👀 while the bot works, then 👍 or 👎.
- **What it does:** Marks the user's message with an in-progress reaction and swaps it for a success/failure reaction when the turn ends.
- **How it works:** `_reactions_enabled()` at `adapter.py:10951-10953` — `os.getenv("TELEGRAM_REACTIONS", "false").lower() not in {"false", "0", "no"}`. `on_processing_start(event)` (`adapter.py:10991-10998`) sets `\U0001f440` (👀). `on_processing_complete(event, outcome)` (`adapter.py:11000-11026`) sets `\U0001f44d` (👍) on `ProcessingOutcome.SUCCESS`, `\U0001f44e` (👎) otherwise, and on `ProcessingOutcome.CANCELLED` calls `_clear_reactions` so a `/stop` does not leave 👀 hanging forever. `_set_reaction` (`adapter.py:10955-10968`) calls `bot.set_message_reaction(chat_id, message_id, reaction=emoji)`; `_clear_reactions` (`adapter.py:10970-10989`) calls it with `reaction=None`, the documented Bot API way to remove all bot reactions (equivalent to Bot API 10.0's `deleteMessageReaction` but available in PTB 22.6).
- **Inputs / options:** boolean.
- **Outputs / side effects:** reactions on the user's message.
- **Config / env:** `TELEGRAM_REACTIONS`, `telegram.reactions` (YAML bridge at `adapter.py:11230-11231`). Default **off**.
- **Edge cases / guards:** Failures are logged at debug only (`set_message_reaction failed (%s): …`, `clear reactions failed: …`) — a group where the bot lacks reaction permission simply keeps working. Unlike Discord, Telegram REPLACES all bot reactions in one call, so 👀→👍 is atomic.
- **Rebuild notes:** One call per state change; explicitly clear on cancellation.

---

## 9. Topics: operator DM topics, group topics, and user-driven multi-session mode

### Operator-curated Private Chat Topics (`extra.dm_topics`)  `id: platform-telegram.dm-topics-config`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.dm_topics` in `~/.hermes/config.yaml`; documented at `telegram.md:650-741`.
- **What it does:** Declares a fixed set of forum topics inside the operator's 1-on-1 DM with the bot, each an isolated session with an optional auto-loaded skill.
- **How it works:** Shape: a list of `{chat_id: <int>, topics: [{name, icon_color?, icon_custom_emoji_id?, skill?, thread_id?}]}`. Loaded in `__init__` into `self._dm_topics_config` and `self._dm_topic_chat_ids` (`adapter.py:860-868`), materialised by `_setup_dm_topics()` at connect time. Each topic maps to the session key `agent:main:telegram:dm:{chat_id}:{thread_id}`.
- **Inputs / options:** field table (from the docs): `name` **required** — topic display name; `icon_color` optional integer (docs examples `7322096`, `9367192`, `16766590`); `icon_custom_emoji_id` optional custom emoji id; `skill` optional skill to auto-load on new sessions in the topic; `thread_id` auto-populated after creation, "don't set manually".
- **Outputs / side effects:** topics created in Telegram; `thread_id` written back into `config.yaml`.
- **Config / env:** `platforms.telegram.extra.dm_topics`, `platforms.telegram.extra.ignore_root_dm`.
- **Edge cases / guards:** Prerequisite (client-side, cannot be automated): the user must open the DM, tap the bot's name, and enable **Topics**; otherwise startup logs `The chat is not a forum` and topic creation is skipped.
- **Rebuild notes:** Config declares intent, the adapter reconciles it against the platform and writes back the ids it learns.

### `_create_dm_topic()` — createForumTopic in a DM  `id: platform-telegram.create-dm-topic`
- **Surface:** Core
- **Where:** Startup topic setup, `/topic` System topic, `ensure_dm_topic`, session handoffs.
- **What it does:** Creates a forum topic in a private chat using Bot API 9.4's `createForumTopic` and returns its `message_thread_id`.
- **How it works:** `adapter.py:3836-3885`. kwargs: `chat_id`, `name`, optional `icon_color`, optional `icon_custom_emoji_id`. Success logs `Created DM topic '%s' in chat %s -> thread_id=%s`.
- **Inputs / options:** `chat_id: int`, `name: str`, `icon_color: Optional[int]`, `icon_custom_emoji_id: Optional[str]`.
- **Outputs / side effects:** `Optional[int]` thread id.
- **Config / env:** n/a.
- **Edge cases / guards:** Error text containing `topic_name_duplicate` or `already` logs `DM topic '%s' already exists in chat %s (will be mapped from incoming messages)`; `not a forum` / `forums_disabled` logs the full remediation sentence `Cannot create DM topic '%s' in chat %s: Topics mode is not enabled. The user must open the DM with this bot in Telegram, tap the bot name at the top, and enable 'Topics' in chat settings before topics can be created.`; anything else logs `Failed to create DM topic '%s' in chat %s: <redacted>`. Telegram exposes no "list topics" API, so duplicates are recovered from inbound messages instead.
- **Rebuild notes:** Classify the three failure modes distinctly — only one of them is actionable by the user.

### `ensure_dm_topic()` / `create_handoff_thread()`  `id: platform-telegram.ensure-dm-topic`
- **Surface:** Core
- **Where:** Named delivery targets (`telegram:<chat>:<topic name>`), session handoffs.
- **What it does:** Returns the thread id for a named DM topic, creating and persisting it when it does not exist yet.
- **How it works:** `ensure_dm_topic(chat_id, topic_name, force_create=False)` at `adapter.py:3905-3956`: cache hit on `f"{chat_id}:{name}"` returns immediately (unless `force_create`); otherwise it looks the topic up in `_dm_topics_config`, returns a persisted `thread_id` when present, and finally creates the topic (carrying `icon_color`/`icon_custom_emoji_id` from config), updates the cache, and calls `_persist_dm_topic_thread_id(..., replace_existing=force_create)`. `create_handoff_thread(parent_chat_id, name)` at `adapter.py:3887-3903` is the thin wrapper used for session handoffs; it returns the id as a string or `None`.
- **Inputs / options:** `chat_id`, `topic_name`, `force_create`.
- **Outputs / side effects:** possible topic creation + config write.
- **Config / env:** `platforms.telegram.extra.dm_topics`.
- **Edge cases / guards:** Blank names and non-integer chat ids return `None`. A chat/topic entry missing from config is APPENDED to `_dm_topics_config` in memory before creation.
- **Rebuild notes:** Cache → config → create, and always persist what you create.

### `rename_dm_topic()`  `id: platform-telegram.rename-dm-topic`
- **Surface:** Core
- **Where:** Auto-rename after a session title is generated.
- **What it does:** Renames a forum topic via `editForumTopic`.
- **How it works:** `adapter.py:3958-3979`; coerces `chat_id` to int when possible, calls `bot.edit_forum_topic(chat_id, message_thread_id=int(thread_id), name=name)` and logs `Renamed DM topic in chat %s thread_id=%s -> '%s'`.
- **Inputs / options:** `chat_id`, `thread_id`, `name`.
- **Outputs / side effects:** topic renamed in Telegram.
- **Config / env:** n/a.
- **Edge cases / guards:** Exceptions propagate to the caller (`_rename_telegram_topic_for_session_title` swallows them at debug).
- **Rebuild notes:** n/a.

### `thread_id` write-back into `config.yaml`  `id: platform-telegram.persist-thread-id`
- **Surface:** Core | Config
- **Where:** After any topic creation. Log: `Persisted thread_id=%s for topic '%s' in config.yaml`.
- **What it does:** Saves the created topic's `thread_id` back into `platforms.telegram.extra.dm_topics` so restarts do not recreate topics.
- **How it works:** `_persist_dm_topic_thread_id(chat_id, topic_name, thread_id, replace_existing=False)` at `adapter.py:3981-4053`. Loads `<HERMES_HOME>/config.yaml` with `yaml.safe_load`, walks/creates `platforms → telegram → extra → dm_topics`, updates the matching topic (or appends a new `{name, thread_id}` entry, or a whole new chat entry), and writes with `hermes_cli.config.atomic_config_write(path, config, default_flow_style=False, sort_keys=False)`.
- **Inputs / options:** `replace_existing` forces an overwrite of an existing `thread_id`.
- **Outputs / side effects:** `~/.hermes/config.yaml` rewritten atomically.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Missing config file logs `Config file not found at %s, cannot persist thread_id` and returns; only writes when something actually changed; all failures log `Failed to persist thread_id to config: …` with traceback.
- **Rebuild notes:** Atomic write, no-op when unchanged, and never reorder the user's YAML (`sort_keys=False`).

### `_setup_dm_topics()` — startup reconciliation and seed message  `id: platform-telegram.setup-dm-topics`
- **Surface:** Core
- **Where:** Post-connect housekeeping. Logs: `Setting up %d DM topic(s) for chat %s`, `DM topic loaded from config: %s -> thread_id=%s`, `DM topic cached: %s -> thread_id=%s`.
- **What it does:** Loads persisted topics into the cache and creates the ones that have no `thread_id`, then posts a seed message so the topic is visible in the Telegram client.
- **How it works:** `adapter.py:4055-4137`. Iterates `_dm_topics_config`; a topic with an existing `thread_id` is only cached; a topic without one is created via `_create_dm_topic(chat_id=normalize_telegram_chat_id(chat_id), name, icon_color, icon_custom_emoji_id)`, cached, persisted, and then seeded with `bot.send_message(chat_id, message_thread_id=thread_id, text=f"\U0001f4cc {topic_name}")` — i.e. the literal text `📌 <topic name>` — because Telegram hides empty topics in the client UI.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Telegram topics + one seed message each; config write-back.
- **Config / env:** `platforms.telegram.extra.dm_topics`.
- **Edge cases / guards:** Returns immediately when no topics are configured; entries missing `chat_id` or `topics` are skipped; a failing seed message logs `Could not send seed message to topic '%s': %s` at debug.
- **Rebuild notes:** Seed new threads so they are discoverable; never re-create a topic you already have an id for.

### Hot reload and discovery of DM topics  `id: platform-telegram.dm-topics-hotload`
- **Surface:** Core
- **Where:** Any inbound DM in a topic Hermes does not know yet. Logs: `Hot-loaded DM topic from config: %s -> thread_id=%s`, `Cached DM topic from message: %s -> thread_id=%s`.
- **What it does:** Picks up topics added to `config.yaml` (or created out-of-band) without restarting the gateway.
- **How it works:** `_reload_dm_topics_from_config()` at `adapter.py:10613-10659` re-reads through `hermes_cli.config.load_config_readonly()` (honouring the managed-scope overlay and `${VAR}` expansion), rebuilds `_dm_topics_config` and `_dm_topic_chat_ids`, and caches any new `name → thread_id` pairs. `_get_dm_topic_info(chat_id, thread_id)` (`adapter.py:10661-10698`) checks the cache, calls the reload on a miss, then checks again, returning the topic's config dict (or `{"name": …}` when only the name is known) or `None`. `_cache_dm_topic_from_message(chat_id, thread_id, topic_name)` (`adapter.py:10700-10709`) records topics discovered from `forum_topic_created` service messages.
- **Inputs / options:** n/a.
- **Outputs / side effects:** in-memory caches updated.
- **Config / env:** `platforms.telegram.extra.dm_topics`.
- **Edge cases / guards:** Removing all topics from config clears both caches. Failures log `Failed to reload dm_topics from config: %s` at debug.
- **Rebuild notes:** Reload on cache miss rather than on a timer.

### Group forum topic skill binding (`extra.group_topics`)  `id: platform-telegram.group-topics`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.group_topics`; documented at `telegram.md:880-943`.
- **What it does:** Auto-loads a skill when messages arrive in a specific supergroup forum topic (session isolation per topic already exists for free).
- **How it works:** Read inside `_build_message_event` (`adapter.py:10831-10861`), setting `chat_topic` and `auto_skill` when `chat_id` and `thread_id` match. Both shapes are accepted: the documented list `[{chat_id, topics: [{name?, thread_id, skill?}]}]` and the legacy operator-edited mapping `{"-100…": [{thread_id: …, …}]}`.
- **Inputs / options:** field table (docs): `chat_id` **required** (supergroup id, negative, `-100…` prefix); `name` optional label (informational); `thread_id` **required** (visible in `t.me/c/<group_id>/<thread_id>` links); `skill` optional.
- **Outputs / side effects:** `event.auto_skill`.
- **Config / env:** `platforms.telegram.extra.group_topics`.
- **Edge cases / guards:** Unmapped `thread_id`/`chat_id` values fall through silently — no error, no skill. Unlike DM topics, Hermes never creates group topics (`icon_color` and friends do not apply) and `thread_id` must be set manually.
- **Rebuild notes:** Accept both the list and mapping shapes; matching must use the same normalized thread id as routing.

### Multi-session DM mode — `/topic`  `id: platform-telegram.topic-command`
- **Surface:** Gateway/Telegram
- **Where:** `/topic` in a Telegram DM. Sub-forms documented at `telegram.md:747-758`: `/topic` (root, not yet enabled) → activate; `/topic` (root, already on) → status; `/topic` (inside a topic) → binding info; `/topic help`; `/topic off`; `/topic <session-id>` (inside a topic) → restore.
- **What it does:** Turns a DM into a ChatGPT-style multi-session workspace where every Telegram topic is an independent Hermes session.
- **How it works:** `GatewayRunner._handle_topic_command(event, args)` at `gateway/slash_commands.py:4909-4994`. Guards: non-Telegram or non-DM → `i18n: gateway.topic.not_telegram_dm` = "The /topic command is only available in Telegram private chats."; no session DB → `format_session_db_unavailable(...)`; `_is_user_authorized(source)` false → `i18n: gateway.topic.unauthorized` = "You are not authorized to use /topic on this bot." Argument parsing: `help|?|-h|--help` → `_telegram_topic_help_text()`; `off|disable|stop` → `_disable_telegram_topic_mode_for_chat`; any other argument requires a `thread_id` (else `i18n: gateway.topic.restore_needs_topic`) and routes to `_restore_telegram_topic_session`. Activation path: `_get_telegram_topic_capabilities(source)` → `has_topics_enabled is False` sends the BotFather screenshot (debounced) and returns `i18n: gateway.topic.topics_disabled`; `allows_users_to_create_topics is False` returns `i18n: gateway.topic.topics_user_disallowed`; otherwise `session_db.enable_telegram_topic_mode(chat_id, user_id, has_topics_enabled, allows_users_to_create_topics)` (failure → `i18n: gateway.topic.enable_failed` = "Failed to enable Telegram topic mode: {error}"). With no `thread_id` it then calls `_ensure_telegram_system_topic(source)` and returns `_telegram_topic_root_status_message(source)`; inside a topic it returns `i18n: gateway.topic.bound_status` when a binding exists, else `i18n: gateway.topic.thread_ready`.
- **Inputs / options:** `help`, `?`, `-h`, `--help`, `off`, `disable`, `stop`, `<session-id>`, or no argument.
- **Outputs / side effects:** rows in `telegram_dm_topic_mode` and `telegram_dm_topic_bindings` in `state.db`; a pinned System topic; a screenshot upload.
- **Config / env:** none; the SQLite migration is opt-in and runs on the first `/topic` call, never at gateway startup.
- **Edge cases / guards:** Verbatim locale strings (`locales/en.yaml:377-388`): `not_telegram_dm`, `no_session_db` ("Session database not available."), `unauthorized`, `restore_needs_topic` ("To restore a session, first create or open a Telegram topic, then send /topic <session-id> inside that topic. To create a new topic, open All Messages and send any message there."), `topics_disabled` ("Telegram topics are not enabled for this bot yet.\n\nHow to enable them:\n1. Open @BotFather.\n2. Choose your bot.\n3. Open Bot Settings → Threads Settings.\n4. Turn on Threaded Mode and make sure users are allowed to create new threads.\n\nThen send /topic again."), `topics_user_disallowed` ("Telegram topics are enabled, but users are not allowed to create topics.\n\nOpen @BotFather → choose your bot → Bot Settings → Threads Settings, then turn off 'Disallow users to create new threads'.\n\nThen send /topic again."), `enable_failed`, `bound_status` ("This topic is linked to:\nSession: {label}\nID: {session_id}\n\nUse /new to replace this topic with a fresh session.\nFor parallel work, open All Messages and send a message there to create another topic."), `thread_ready` ("Telegram multi-session topics are enabled.\n\nThis topic will be used as an independent Hermes session. Use /new to replace this topic's current session. For parallel work, open All Messages and send a message there to create another topic."), `untitled_session` ("Untitled session").
- **Rebuild notes:** Verify platform capabilities before enabling; persist activation per (chat, user); make the migration lazy so untouched installs keep a clean DB.

### `/topic help` text  `id: platform-telegram.topic-help`
- **Surface:** Gateway/Telegram
- **Where:** `/topic help`.
- **What it does:** Prints inline usage for multi-session DM mode.
- **How it works:** `_telegram_topic_help_text()` at `gateway/run.py:25192-25212`. Verbatim: `"/topic — enable multi-session DM mode (one bot, many parallel chats)"`, blank, `"Usage:"`, `"  /topic             Enable topic mode, or show status if already on"`, `"  /topic help        Show this message"`, `"  /topic off         Disable topic mode and clear topic bindings"`, `"  /topic <id>        Inside a topic: restore a previous session by ID"`, blank, `"How it works:"`, `"1. Run /topic once in this DM — Hermes checks BotFather Threads"`, `"   Settings are enabled and flips on multi-session mode."`, `"2. Tap All Messages at the top of the bot and send any message."`, `"   Telegram creates a new topic for that message; each topic is"`, `"   an independent Hermes session (fresh history, fresh context)."`, `"3. The root DM becomes a system lobby — send /topic, /status,"`, `"   /help, /usage there. Normal prompts go in a topic."`, `"4. /new inside a topic resets just that topic's session."`, `"5. /topic <id> inside a topic restores an old session into it."`.
- **Inputs / options:** n/a. **Outputs / side effects:** text reply.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Topic capability probe (`getMe` flags)  `id: platform-telegram.topic-capabilities`
- **Surface:** Core
- **Where:** Every `/topic` activation attempt.
- **What it does:** Reads `has_topics_enabled` and `allows_users_to_create_topics` from `getMe` so activation only happens when BotFather's Threads Settings allow it.
- **How it works:** `_get_telegram_topic_capabilities(source)` at `gateway/run.py:24664-24690`. Returns `{"checked": False}` when there is no bot or no `get_me`; otherwise `{"checked": True, "has_topics_enabled": …, "allows_users_to_create_topics": …}` where `_field(name)` reads the attribute, then `me.api_kwargs[name]`, then `me[name]` — so the flags work on SDK versions that have not modelled them yet.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one `getMe` call.
- **Config / env:** BotFather → Bot Settings → Threads Settings (`telegram.md:773-781`).
- **Edge cases / guards:** Any exception logs `Failed to fetch Telegram getMe topic capabilities` at debug and returns `{"checked": False}`, which lets activation proceed.
- **Rebuild notes:** Read unmodelled API fields from the raw payload so the feature is not gated on an SDK release.

### BotFather Threads-Settings screenshot  `id: platform-telegram.topic-setup-image`
- **Surface:** Gateway/Telegram
- **Where:** Sent when `/topic` finds threads disabled. Caption: `BotFather → Bot Settings → Threads Settings`.
- **What it does:** Uploads a bundled screenshot showing exactly which BotFather toggles to flip.
- **How it works:** `_send_telegram_topic_setup_image(source)` at `gateway/run.py:24733-24749`; image is `gateway/assets/telegram-botfather-threads-settings.jpg`, sent through `adapter.send_image_file(...)` with the caption above and the source's thread id when present. Rate-limited by `_should_send_telegram_capability_hint` (`gateway/run.py:25173-25190`) with `_TELEGRAM_CAPABILITY_HINT_COOLDOWN_S = 300.0` (one send per 5 minutes per chat).
- **Inputs / options:** n/a.
- **Outputs / side effects:** photo upload.
- **Config / env:** n/a.
- **Edge cases / guards:** Missing asset file or a missing `send_image_file` method → silent no-op; failures log `Failed to send Telegram topic setup image` at debug.
- **Rebuild notes:** Ship the screenshot with the code and debounce it.

### System topic creation and pinning  `id: platform-telegram.system-topic`
- **Surface:** Gateway/Telegram
- **Where:** Right after `/topic` activation from the root DM. The topic is named **`System`** and its first message reads `System topic for Hermes commands and status.`
- **What it does:** Creates a dedicated topic for status/commands and pins its intro message.
- **How it works:** `_ensure_telegram_system_topic(source)` at `gateway/run.py:24692-24731`: `adapter._create_dm_topic(int(chat_id), "System")`, then `adapter.send(chat_id, "System topic for Hermes commands and status.", metadata={"thread_id": str(thread_id)})`, then `bot.pin_chat_message(chat_id=int(chat_id), message_id=int(message_id), disable_notification=True)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** one topic, one pinned message.
- **Config / env:** n/a.
- **Edge cases / guards:** Every step is best-effort — `Failed to create Telegram System topic`, `Failed to send Telegram System topic intro`, `Failed to pin Telegram System topic intro` are debug-only, and each missing prerequisite (`thread_id`, `message_id`, `pin_chat_message`) returns early.
- **Rebuild notes:** Pin silently (`disable_notification=True`).

### Topic lanes, root lobby and lobby reminder  `id: platform-telegram.topic-lane`
- **Surface:** Gateway/Telegram
- **Where:** After activation, the root DM answers non-command prompts with the lobby reminder instead of running the agent.
- **What it does:** Splits a topic-mode DM into "lanes" (real topics = independent sessions) and a "lobby" (root/General = system commands only).
- **How it works:** `gateway/run.py:8427-8523`. `_telegram_topic_mode_enabled(source)` reads `session_db.is_telegram_topic_mode_enabled(chat_id, user_id)` and only honours a literal `True`. `_TELEGRAM_GENERAL_TOPIC_IDS = frozenset({"", "1"})` treats both the missing thread id and General as root. `_is_telegram_topic_root_lobby` / `_is_telegram_topic_lane` classify a source. `_should_send_telegram_lobby_reminder` rate-limits the reminder with `_TELEGRAM_LOBBY_REMINDER_COOLDOWN_S = 30.0` per chat. Messages: lobby reminder (`_telegram_topic_root_lobby_message`, run.py:8496-8504) = `"This main chat is reserved for system commands.\n\nTo start a new Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for that message; each topic works as an independent Hermes session."`; `/new` in the root (`_telegram_topic_root_new_message`, run.py:8505-8513) = `"To start a new parallel Hermes chat, open the All Messages topic at the top of this bot interface and send any message there. Telegram will create a new topic for it.\n\nEach topic is an independent Hermes session. Use /new inside an existing topic only if you want to replace that topic's current session."`; `/new` inside a topic (`_telegram_topic_new_header`, run.py:8514-8523) = `"Started a new Hermes session in this topic.\n\nTip: for parallel work, open All Messages and send a message there to create a separate topic instead of using /new here. /new replaces the session attached to the current topic."`
- **Inputs / options:** n/a.
- **Outputs / side effects:** replies instead of agent runs in the lobby.
- **Config / env:** none (state lives in `state.db`).
- **Edge cases / guards:** Reminder cooldown resets when topic mode is disabled. A user with ten queued root prompts gets one reminder.
- **Rebuild notes:** Treat the missing thread id and the General id as the same lane.

### Topic ↔ session bindings  `id: platform-telegram.topic-bindings`
- **Surface:** Core
- **Where:** SQLite tables `telegram_dm_topic_mode(chat_id, user_id, enabled, …)` and `telegram_dm_topic_bindings(chat_id, thread_id, session_id, …)` in `~/.hermes/state.db`.
- **What it does:** Persists which Hermes session each Telegram topic owns, so reopening a topic after a restart resumes the right conversation.
- **How it works:** `_record_telegram_topic_binding(source, session_entry)` (`gateway/run.py:8524-8541`) calls `session_db.bind_telegram_topic(chat_id, thread_id, user_id, session_key, session_id)`. `_sync_telegram_topic_binding(source, session_entry, reason=…)` (`gateway/run.py:8543-8567`) re-points the row whenever compression rotates `session_id` mid-turn — without it the next inbound message reloads the oversized parent transcript and retriggers preflight compression, sometimes in a loop (#20470, #29712, #33414). It is called from the turn paths at `gateway/run.py:7138`, `20549`, `21767`, `22313`, `22551`. `ON DELETE CASCADE` on `session_id` means pruning a session clears its binding.
- **Inputs / options:** n/a.
- **Outputs / side effects:** DB rows.
- **Config / env:** n/a.
- **Edge cases / guards:** Failures log `telegram topic binding refresh failed (%s)` at debug. The adapter also prunes stale bindings on a `thread not found` send error (`_prune_stale_dm_topic_binding`).
- **Rebuild notes:** Re-sync the binding on every session-id rotation, not only at session creation.

### Lobby-shaped reply recovery (`_recover_telegram_topic_thread_id`)  `id: platform-telegram.topic-recovery`
- **Surface:** Core
- **Where:** Installed on the adapter via `adapter.set_topic_recovery_fn(...)` (`gateway/run.py:13893`, `15710`, `16839`); log `telegram topic recovery: chat=%s user=%s %r -> %s`.
- **What it does:** Pins a reply that arrived without a usable thread id back to the user's most recent bound topic, so the conversation does not fall into the lobby.
- **How it works:** `gateway/run.py:8569-8620`. Only for Telegram DMs with topic mode on. A NON-lobby unknown thread id is left alone (it is most likely a brand-new topic; rewriting it would hijack an older lane). For lobby-shaped ids it reads `session_db.list_telegram_topic_bindings_for_chat(chat_id)` (newest first) and returns the newest binding belonging to this `user_id`. `_normalize_source_for_session_key(source)` (`gateway/run.py:8622-8650`) applies the same recovery when session-scoped commands (`/model`, `/reasoning`) derive their override key, so storage and read keys match (#30479). The adapter applies it in `_text_batch_key` via `_apply_topic_recovery(event)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** rewritten `source.thread_id`.
- **Config / env:** n/a.
- **Edge cases / guards:** Read failures log `topic-recover: read failed` at debug and return `None`.
- **Rebuild notes:** Recover only lobby-shaped ids; a brand-new lane must stay itself.

### Topic auto-rename from the session title  `id: platform-telegram.topic-auto-rename`
- **Surface:** Gateway/Telegram | Config
- **Where:** After Hermes auto-titles a topic's session, the Telegram topic name changes to match (e.g. "New Topic" → "Database migration plan").
- **What it does:** Keeps the topic list readable by naming each topic after its conversation.
- **How it works:** `_schedule_telegram_topic_title_rename(source, session_id, title)` (`gateway/run.py:25134-25171`) schedules the coroutine on the gateway loop with `safe_schedule_threadsafe` (log `Telegram topic title rename failed to schedule` / `Telegram topic title rename failed`); it is invoked from the auto-title path at `gateway/run.py:5718-5722`. `_rename_telegram_topic_for_session_title` (`gateway/run.py:25026-25109`) requires a topic lane, honours the disable flag, SKIPS operator-declared topics (detected by a dict-shaped `type(adapter)._get_dm_topic_info(...)` result), verifies the binding still points at `session_id`, then calls `adapter.rename_dm_topic(...)`, falling back to `bot.edit_forum_topic` / `bot.editForumTopic` with int-then-raw argument coercion. `_sanitize_telegram_topic_title(title)` (`gateway/run.py:24751-24761`) collapses whitespace, defaults to `Hermes Chat` when empty, and truncates to `cleaned[:117].rstrip() + "..."` beyond 120 characters.
- **Inputs / options:** `gateway.platforms.telegram.extra.disable_topic_auto_rename` (default false) read by `_telegram_topic_auto_rename_disabled` (`gateway/run.py:25111-25132`, accepting bool or the strings `1|true|yes|on`).
- **Outputs / side effects:** topic renamed.
- **Config / env:** `platforms.telegram.extra.disable_topic_auto_rename`; also bridged through `_apply_yaml_config` extras (`adapter.py:11177-11178`).
- **Edge cases / guards:** Best-effort — failures log at debug and never break the session. `/bg` background sessions do not trigger auto-rename of the owning topic. Operator `dm_topics` names are never overwritten.
- **Rebuild notes:** Verify the binding before renaming so a rotated session cannot rename someone else's topic.

### `/topic off`  `id: platform-telegram.topic-off`
- **Surface:** Gateway/Telegram
- **Where:** `/topic off` (also `disable`, `stop`) in the root DM.
- **What it does:** Disables multi-session mode and clears the chat's topic bindings; existing Telegram topics are left in place.
- **How it works:** `_disable_telegram_topic_mode_for_chat(source)` at `gateway/run.py:25214-25248`. Replies `Multi-session topic mode is not currently enabled for this chat.` when it was never on; otherwise `session_db.disable_telegram_topic_mode(chat_id=…)`, resets the `_telegram_lobby_reminder_ts` / `_telegram_capability_hint_ts` debounce entries for the chat, and returns `"Multi-session topic mode is now OFF for this chat.\n\nExisting topics in Telegram aren't removed — they'll just stop being gated as independent sessions. The root DM works as a normal Hermes chat again. Run /topic to re-enable later."`
- **Inputs / options:** n/a.
- **Outputs / side effects:** `telegram_dm_topic_mode.enabled = 0`, bindings cleared.
- **Config / env:** n/a. Manual cleanup SQL is documented at `telegram.md:869-874`.
- **Edge cases / guards:** Failures log `Failed to disable Telegram topic mode` and return `Failed to disable topic mode: <exc>`; no session DB → `format_session_db_unavailable(...)`; missing chat id → `Could not determine chat ID.`
- **Rebuild notes:** Reset debounce state on disable so the next activation is not silently muted.

### `/topic` root status and restorable sessions  `id: platform-telegram.topic-status`
- **Surface:** Gateway/Telegram
- **Where:** `/topic` with no argument in the root DM after activation.
- **What it does:** Explains how to create topics and lists up to 10 previous Telegram sessions that are not yet bound to a topic.
- **How it works:** `_telegram_topic_root_status_message(source)` at `gateway/run.py:25251-25294`. Fixed lines: `"Telegram multi-session topics are enabled."`, blank, `"To create a new Hermes chat, open All Messages at the top of this bot interface and send any message there. Telegram will create a new topic for it."`, blank. Then `session_db.list_unlinked_telegram_sessions_for_user(chat_id, user_id, limit=10)`; with results it prints `"Previous unlinked sessions:"` and one line per session `- <title|Untitled session> — \`<session id>\`( — <preview>)?`, followed by `"To restore one:"`, `"1. Create or open a topic. To create a new one, open All Messages and send any message there."`, `"2. Send /topic <session-id> inside that topic."`, `"Example: Send /topic <first id> inside a topic."`; with no results it prints `"No previous unlinked Telegram sessions found."` and the same two-step instructions under `"To restore a previous session later:"`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** text reply.
- **Config / env:** n/a.
- **Edge cases / guards:** A failing listing logs `Failed to list unlinked Telegram sessions` at debug and renders the empty branch.
- **Rebuild notes:** Show the exact command to copy, including a filled-in example id.

### `/topic <session-id>` — restore a session into a topic  `id: platform-telegram.topic-restore`
- **Surface:** Gateway/Telegram
- **Where:** Inside a topic. Replies: `Session not found: <id>`, `That session is not a Telegram session and cannot be restored into this topic.`, `That session does not belong to this Telegram user.`, `That session is already linked to another Telegram topic.`, `Session restored: <title>` (plus `\n\nLast Hermes message:\n<text>`).
- **What it does:** Binds the current Telegram topic to an existing Hermes session instead of starting a fresh one, and replays the last assistant message for context.
- **How it works:** `_restore_telegram_topic_session(event, raw_session_id)` at `gateway/run.py:25297-25350`. `session_db.resolve_session_id(raw)` accepts a unique prefix; then `get_session`, checks `source == "telegram"` and `user_id == source.user_id`; `is_telegram_session_linked_to_topic(session_id)` combined with the current binding rejects sessions already owned by another topic; `bind_telegram_topic(..., managed_mode="restored")` writes the row (a `ValueError` containing `already linked` is converted to the friendly message). The last assistant message is found by scanning `get_messages(session_id)` in reverse through `project_compaction_message_for_display`.
- **Inputs / options:** session id or unique prefix.
- **Outputs / side effects:** binding row with `managed_mode="restored"`.
- **Config / env:** n/a.
- **Edge cases / guards:** Restoring requires being inside a topic (`gateway.topic.restore_needs_topic` otherwise).
- **Rebuild notes:** Enforce ownership and single-binding invariants in the DB layer, not only in the command.

### DM-topic reply metadata for synthetic sends  `id: platform-telegram.dm-topic-metadata`
- **Surface:** Core
- **Where:** Cron deliveries, goal continuations, watch notifications, restart-resumed follow-ups — any send that has routing state but no inbound message.
- **What it does:** Adds the Telegram-specific metadata that makes a synthetic message land inside the right private DM topic.
- **How it works:** `_thread_metadata_for_target(...)` at `gateway/run.py:25720-25753` starts from `{"thread_id": thread_id}` and, when `_is_telegram_dm_topic_target(...)` is true, adds `telegram_dm_topic_reply_fallback: True`, `direct_messages_topic_id: <thread id>` (for ids other than `""`/`"1"`), and `telegram_reply_to_message_id` when an anchor exists. `_is_telegram_dm_topic_target(platform, chat_id, thread_id, chat_type=None, adapter=None)` (`gateway/run.py:25755-25780`) returns True for `chat_type == "dm"`, otherwise consults `type(adapter)._get_dm_topic_info(adapter, chat_id, thread_id)` and requires a dict-shaped result.
- **Inputs / options:** platform, chat id, thread id, chat type, reply anchor, adapter.
- **Outputs / side effects:** the metadata dict consumed by `_thread_kwargs_for_send`.
- **Config / env:** n/a.
- **Edge cases / guards:** Resolving `_get_dm_topic_info` on the CLASS (not the instance) prevents `MagicMock` test doubles from being mistaken for real topics; lookup errors log `Failed to inspect Telegram DM topic metadata` at debug.
- **Rebuild notes:** Carry topic identity explicitly in metadata; do not rely on a reply anchor that synthetic sends do not have.

### Home channel and cron topic override  `id: platform-telegram.home-channel`
- **Surface:** Env | Config
- **Where:** `/sethome` in any Telegram chat, or `TELEGRAM_HOME_CHANNEL` / `TELEGRAM_HOME_CHANNEL_NAME` in `~/.hermes/.env`; `telegram.md:347-370`.
- **What it does:** Designates the chat where scheduled tasks deliver their output, with a Telegram-only override for the topic cron posts land in.
- **How it works:** `TELEGRAM_HOME_CHANNEL` is registered as `cron_deliver_env_var` for the platform. `gateway/config.py:2032` reads `TELEGRAM_HOME_CHANNEL_THREAD_ID` into the home target's `thread_id`. `cron/scheduler.py:2308-2356` `_get_home_target_thread_id("telegram")` checks `TELEGRAM_CRON_THREAD_ID` FIRST (profile-scoped via `agent.secret_scope.get_secret`), then `<ENV>_THREAD_ID`, then a legacy alias, then the `config.yaml` home-channel block (only when the chat id itself did not come from env).
- **Inputs / options:** `TELEGRAM_HOME_CHANNEL` (chat id; groups are negative, e.g. `-1001234567890`; a personal DM chat id equals the user id), `TELEGRAM_HOME_CHANNEL_NAME` (display name), `TELEGRAM_HOME_CHANNEL_THREAD_ID`, `TELEGRAM_CRON_THREAD_ID`.
- **Outputs / side effects:** cron deliveries routed to a specific chat/topic.
- **Config / env:** the four variables above.
- **Edge cases / guards:** With topic mode enabled, cron output delivered to the root DM lands in the system-only lobby where replies open no session — the documented fix is a dedicated `Cron` topic plus `TELEGRAM_CRON_THREAD_ID` (#24409). Explicit `telegram:chat:thread` cron targets bypass the override.
- **Rebuild notes:** Give scheduled delivery its own thread override; the "home" target and the "cron" target are not the same question.

---

## 10. Configuration bridge, plugin glue and documented behaviour

### YAML → env / extras bridge (`_apply_yaml_config`)  `id: platform-telegram.yaml-bridge`
- **Surface:** Config
- **Where:** Runs when the gateway loads `config.yaml`; translates the `telegram:` block into `TELEGRAM_*` env vars and `PlatformConfig.extra` entries.
- **What it does:** Makes every documented `telegram.*` YAML key work, while env vars keep precedence and multiplex profiles do not leak their allowlists into the process environment.
- **How it works:** `_apply_yaml_config(yaml_cfg, telegram_cfg)` at `adapter.py:11147-11274`. Multiplex guard: `_skip_env_bridge = is_multiplex_active() and current_secret_scope() is not None` (`adapter.py:11160-11170`) — authorization gates are then seeded only into `extras`, never into `os.environ` (first-writer-wins would pin one profile's list for all, the Telegram mirror of #72348). Keys handled, in order: `disable_topic_auto_rename` → extras; `require_mention` (falling back to the top-level `yaml_cfg["require_mention"]`) → `TELEGRAM_REQUIRE_MENTION`; `mention_patterns` → `TELEGRAM_MENTION_PATTERNS` (JSON-encoded); `exclusive_bot_mentions` → `TELEGRAM_EXCLUSIVE_BOT_MENTIONS`; `allow_bots` → `TELEGRAM_ALLOW_BOTS`; `guest_mode` → `TELEGRAM_GUEST_MODE`; `observe_unmentioned_group_messages` → `TELEGRAM_OBSERVE_UNMENTIONED_GROUP_MESSAGES`; `free_response_chats` → extras + `TELEGRAM_FREE_RESPONSE_CHATS`; `free_response_topics` → `TELEGRAM_FREE_RESPONSE_TOPICS`; `allowed_chats` → `TELEGRAM_ALLOWED_CHATS` (no extras seed — the shared-key loop in `gateway/config.py` already bridges it with the original type); `allowed_topics` → `TELEGRAM_ALLOWED_TOPICS` (no extras seed); `ignored_threads` → extras + `TELEGRAM_IGNORED_THREADS`; `reactions` → `TELEGRAM_REACTIONS`; `proxy_url` → `TELEGRAM_PROXY`; `reply_to_mode` (top-level or nested in `extra`) → `TELEGRAM_REPLY_TO_MODE` with `False` mapped to the string `"off"`; `allow_from` → `TELEGRAM_ALLOWED_USERS`; `group_allow_from` → `TELEGRAM_GROUP_ALLOWED_USERS`; `group_allowed_chats` → `TELEGRAM_GROUP_ALLOWED_CHATS` (no extras seed). Then `guest_mode`, `disable_link_previews`, `observe_unmentioned_group_messages`, `free_response_topics` are seeded into extras, and every other key from the nested `extra:` block is passed through EXCEPT the generic merge keys `{reply_prefix, reply_in_thread, reply_to_mode, unauthorized_dm_behavior, notice_delivery, require_mention, channel_skill_bindings, channel_prompts, gateway_restart_notification, allow_from, allow_admin_from, dm_policy, group_policy}`, which `_merge_platform_map` in `gateway/config.py` already merges with correct top-level-over-nested precedence.
- **Inputs / options:** every key listed above; lists are joined with `,` before being written to env.
- **Outputs / side effects:** environment variables set (only when not already present), and a dict of extras merged into `PlatformConfig.extra` (or `None` when empty).
- **Config / env:** all `TELEGRAM_*` variables named above.
- **Edge cases / guards:** Env always wins (`if … and not os.getenv(...)`). Re-emitting the generic merge keys would clobber the correct precedence, hence the exclusion set.
- **Rebuild notes:** One translator per platform with an explicit exclusion list; never write authorization state to process-global env under multi-profile hosting.

### Standalone (out-of-process) sender  `id: platform-telegram.standalone-send`
- **Surface:** Core
- **Where:** `deliver=telegram` cron jobs and any delivery that runs without a live gateway adapter.
- **What it does:** Sends a Telegram message straight over the REST API, so scheduled delivery works when cron runs in a separate process.
- **How it works:** `_standalone_send(pconfig, chat_id, message, *, thread_id=None, media_files=None, force_document=False)` at `adapter.py:11098-11133`. Token comes from `pconfig.token`, else `agent.secret_scope.get_secret("TELEGRAM_BOT_TOKEN", "")` (profile-scoped, so a multiplex profile does not borrow another profile's env-bridged token). `disable_link_previews` is read from `pconfig.extra`. It then delegates to `tools.send_message_tool._send_telegram(token, chat_id, message, media_files=…, thread_id=…, disable_link_previews=…, force_document=…)`, which already handles chunking, threads, media, retries and parse-mode fallback.
- **Inputs / options:** `chat_id`, `message`, `thread_id`, `media_files`, `force_document`.
- **Outputs / side effects:** message delivered without touching the gateway.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `platforms.telegram.extra.disable_link_previews`.
- **Edge cases / guards:** Registered as `standalone_sender_fn` in `register(ctx)`.
- **Rebuild notes:** Keep a dependency-light REST sender for out-of-process delivery, and read secrets through the profile scope.

### Connected check and adapter factory  `id: platform-telegram.connected-factory`
- **Surface:** Core
- **Where:** Platform status displays, `gateway/config.py`'s plugin-enable pass, `hermes gateway status`.
- **What it does:** Reports Telegram as configured only when a bot token exists, and applies the notification mode when constructing the adapter.
- **How it works:** `_is_connected(config)` at `adapter.py:11081-11096` reads `config.token`, falling back to `hermes_cli.gateway.get_env_value("TELEGRAM_BOT_TOKEN")`, and returns `bool(str(token).strip())` — without this, the registry would enable Telegram on any machine that merely has `python-telegram-bot` installed. `_build_adapter(config)` at `adapter.py:11070-11079` constructs `TelegramAdapter(config)` then sets `adapter._notifications_mode = _resolve_notifications_mode()` (falling back to `"important"` on any exception), preserving the post-construction step that used to live in `gateway/run.py::_create_adapter()`.
- **Inputs / options:** a `PlatformConfig`.
- **Outputs / side effects:** boolean / adapter instance.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `HERMES_TELEGRAM_NOTIFICATIONS`, `display.platforms.telegram.notifications`.
- **Edge cases / guards:** SDK presence (`telegram_deps_present`) and token presence are deliberately separate checks.
- **Rebuild notes:** Separate "can we import it" from "is it configured"; factories should apply post-construction config in one place.

### Telegram-safe command mentions in help text  `id: platform-telegram.command-mention-rewrite`
- **Surface:** Core
- **Where:** Any gateway-generated text that mentions slash commands, rendered for Telegram.
- **What it does:** Rewrites `/some-command` mentions to Telegram's allowed command shape (lowercase letters, digits, underscores) so they stay clickable.
- **How it works:** `_telegramize_command_mentions(text, platform)` at `gateway/run.py:1257-1275`: returns unchanged text for every non-Telegram platform, otherwise substitutes each match of `_TELEGRAM_COMMAND_MENTION_RE` with `/` + `hermes_cli.commands._sanitize_telegram_name(name)`, keeping the original text when sanitisation yields an empty name.
- **Inputs / options:** the rendered text and the target platform.
- **Outputs / side effects:** rewritten string.
- **Config / env:** n/a.
- **Edge cases / guards:** Only the Telegram rendering changes; other platforms keep hyphens (`gateway/run.py:19387` notes the same constraint for the command menu).
- **Rebuild notes:** Normalize command mentions at render time, per platform.

### Streaming transport selection for Telegram  `id: platform-telegram.streaming-transport`
- **Surface:** Config | Docs
- **Where:** `gateway.streaming.enabled` + `gateway.streaming.transport` in `config.yaml`; documented at `telegram.md:951-977`.
- **What it does:** Chooses between Telegram's native draft streaming (Bot API 9.5 `sendMessageDraft`) and the legacy progressive `editMessageText` path.
- **How it works:** Four documented values: **`auto` (default)** — "Native draft streaming on supported chats (currently Telegram DMs); legacy edit-based path otherwise. Falls back gracefully if a draft frame fails."; **`draft`** — "Force native drafts. Logs a downgrade and falls back to edit if the chat doesn't support drafts (e.g. groups/topics)."; **`edit`** — "Legacy progressive `editMessageText` polling for every chat type."; **`off`** — "Disable streaming entirely (final reply only, no progressive updates)." The adapter side is `supports_draft_streaming()` / `send_draft()` (`adapter.py:6219-6343`) plus the rich-draft variants.
- **Inputs / options:** `auto` | `draft` | `edit` | `off`.
- **Outputs / side effects:** either an animated draft preview that clears on completion (drafts have no message id, so the final answer is what stays in history) or a normal message edited progressively.
- **Config / env:** `gateway.streaming.enabled`, `gateway.streaming.transport`.
- **Edge cases / guards:** Telegram restricts `sendMessageDraft` to private chats, so groups/supergroups/forum topics always take the edit path; any draft failure (transient network error, server rejection, older `python-telegram-bot`) flips that response back to edits for the rest of the stream, and the next response retries drafts.
- **Rebuild notes:** Per-response transport latching with a documented downgrade path.

### Group chat usage rules (documented)  `id: platform-telegram.group-usage-docs`
- **Surface:** Docs
- **Where:** `telegram.md:549-565`.
- **What it does:** States the complete set of group behaviours an operator must know.
- **How it works:** The bulleted list, verbatim in substance: privacy mode determines what the bot can see; `TELEGRAM_ALLOWED_USERS` still applies in groups; `telegram.require_mention: true` stops replies to ordinary chatter; with it, accepted triggers are replies to the bot's messages, `@botusername` mentions, `/command@botusername`, and `telegram.mention_patterns` matches; `telegram.exclusive_bot_mentions` (default on) keeps multi-bot routing deterministic; a BotFather `@username` rename is picked up automatically without a gateway restart, including collectible (Fragment) handles that do not end in `bot`; `telegram.ignored_threads` mutes specific forum topics; leaving `require_mention` unset keeps the previous open-group behaviour.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `TELEGRAM_ALLOWED_USERS`, `telegram.require_mention`, `telegram.mention_patterns`, `telegram.exclusive_bot_mentions`, `telegram.ignored_threads`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Running several Hermes bots in one group  `id: platform-telegram.multi-bot`
- **Surface:** Docs
- **Where:** `telegram.md:566-598`.
- **What it does:** Explains the one-token-per-profile rule and the recommended config for deterministic routing.
- **How it works:** "create one Telegram bot token per profile and start one gateway per profile. Do not reuse the same bot token in multiple running gateways; Telegram will reject concurrent polling for the same token." Recommended config: `telegram: require_mention: true`, `exclusive_bot_mentions: true`, `mention_patterns: []`. With it, `@research_bot @ops_bot summarize this` is processed by those two bots only. Profile operation: `hermes gateway start|status|stop` for the default profile and `hermes -p <profile> gateway start|status|stop` for named profiles, driven by a shell loop for a fleet.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** `telegram.require_mention`, `telegram.exclusive_bot_mentions`, `telegram.mention_patterns`.
- **Edge cases / guards:** `exclusive_bot_mentions: false` is only for legacy groups where mentions should not override reply/wake-word triggers.
- **Rebuild notes:** n/a.

### Troubleshooting: works in DMs but not groups  `id: platform-telegram.group-troubleshooting`
- **Surface:** Docs
- **Where:** `telegram.md:599-622`.
- **What it does:** Gives the ordered checklist for a silent group bot.
- **How it works:** Five steps, verbatim in substance: (1) Telegram delivery — turn off BotFather privacy mode, promote the bot to admin, or mention it directly; (2) rejoin after changing privacy — remove and re-add the bot, since Telegram may keep the old delivery behaviour for existing memberships; (3) Hermes authorization — the sender must be in `TELEGRAM_ALLOWED_USERS` or `TELEGRAM_GROUP_ALLOWED_USERS`, or the chat in `TELEGRAM_GROUP_ALLOWED_CHATS`; (4) mention filters under `require_mention`; (5) multi-bot routing — unique token per profile, keep `exclusive_bot_mentions` on. Plus: negative chat ids are normal, and belong in `TELEGRAM_GROUP_ALLOWED_CHATS`, not the sender allowlist.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a.
- **Config / env:** the three allowlist variables.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### General troubleshooting table  `id: platform-telegram.troubleshooting-table`
- **Surface:** Docs
- **Where:** `telegram.md:1270-1280`.
- **What it does:** Maps seven common symptoms to fixes.
- **How it works:** Rows: **Bot not responding at all** → "Verify `TELEGRAM_BOT_TOKEN` is correct. Check `hermes gateway` logs for errors."; **Bot responds with "unauthorized"** → "Your user ID is not in `TELEGRAM_ALLOWED_USERS`. Double-check with @userinfobot."; **Bot ignores group messages** → "Privacy mode is likely on. Disable it (Step 3) or make the bot a group admin. **Remember to remove and re-add the bot after changing privacy.**"; **Voice messages not transcribed** → "Verify STT is available: install `faster-whisper` for local transcription, or set `GROQ_API_KEY` / `VOICE_TOOLS_OPENAI_KEY` in `~/.hermes/.env`."; **Voice replies are files, not bubbles** → "Install `ffmpeg` (needed for Edge TTS Opus conversion)."; **Bot token revoked/invalid** → "Generate a new token via `/revoke` then `/newbot` or `/token` in BotFather. Update your `.env` file."; **Webhook not receiving updates** → "Verify `TELEGRAM_WEBHOOK_URL` is publicly reachable (test with `curl`). Ensure your platform/reverse proxy routes inbound HTTPS traffic from the URL's port to the local listen port configured by `TELEGRAM_WEBHOOK_PORT` (they do not need to be the same number). Ensure SSL/TLS is active — Telegram only sends to HTTPS URLs. Check firewall rules."
- **Inputs / options:** n/a. **Outputs / side effects:** n/a.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `GROQ_API_KEY`, `VOICE_TOOLS_OPENAI_KEY`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_PORT`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Incoming voice → speech-to-text  `id: platform-telegram.stt-incoming`
- **Surface:** Docs | Config
- **Where:** `telegram.md:372-400`; the user sends a voice note and the agent receives text (or a file path).
- **What it does:** Transcribes Telegram voice messages with the configured STT provider, or — when STT is disabled — hands the agent the cached audio path instead.
- **How it works:** The adapter caches the voice note as `.ogg` (`cache_audio_from_bytes`) and the gateway transcribes it. Providers documented: `local` (`faster-whisper`, no API key), `groq` (Groq Whisper, `GROQ_API_KEY`), `openai` (OpenAI Whisper, `VOICE_TOOLS_OPENAI_KEY`). With `stt.enabled: false` the file is still downloaded but not transcribed and the agent sees the marker `[The user sent a voice message: /home/<user>/.hermes/cache/audio/<hash>.ogg]` (built at `gateway/run.py:26710-26713`, with a `(duration: …)` suffix when known).
- **Inputs / options:** `stt.enabled`, `stt` provider settings.
- **Outputs / side effects:** cached audio file; transcript text or a path marker.
- **Config / env:** `GROQ_API_KEY`, `VOICE_TOOLS_OPENAI_KEY`, `stt.enabled`.
- **Edge cases / guards:** The extension reflects the original format (`.ogg` for voice notes, `.mp3`/`.m4a`/… for audio attachments); pairs with the local Bot API server to lift the 20 MB `getFile` ceiling to 2 GB for long recordings.
- **Rebuild notes:** Always cache the raw audio even when transcribing, so tools can re-process it.

### Outgoing TTS voice bubbles  `id: platform-telegram.tts-outgoing`
- **Surface:** Docs | Config
- **Where:** `telegram.md:401-418`.
- **What it does:** Delivers agent-generated speech as round, inline-playable Telegram voice bubbles.
- **How it works:** OpenAI and ElevenLabs produce Opus natively; Edge TTS (the default free provider) outputs MP3 and needs **ffmpeg** (`sudo apt install ffmpeg` / `brew install ffmpeg`) so the adapter's `transcode_to_ogg_opus` step can produce a bubble. Without ffmpeg the audio is sent as a regular audio file (still playable, rectangular player).
- **Inputs / options:** `tts.provider`.
- **Outputs / side effects:** voice or audio message.
- **Config / env:** `tts.provider`.
- **Edge cases / guards:** See `platform-telegram.send-voice` for the transcode/fallback mechanics.
- **Rebuild notes:** n/a.

### Slash-command access control on Telegram  `id: platform-telegram.slash-access`
- **Surface:** Config | Docs
- **Where:** `gateway.platforms.telegram.extra.allow_admin_from`, `user_allowed_commands`, `group_allow_admin_from`, `group_user_allowed_commands`; documented at `telegram.md:1094-1136`.
- **What it does:** Splits the Telegram allowlist into admins (all slash commands) and regular users (only explicitly enabled commands).
- **How it works:** Documented behaviour: a user in `allow_admin_from` for a scope (DM or group) can run every registered slash command, built-in and plugin, through the live registry; a user in `allow_from` but not in the admin list can only run the commands in `user_allowed_commands` plus the always-allowed floor **`/help`** and **`/whoami`**; plain chat is unaffected; if `allow_admin_from` is unset for a scope, gating is disabled for that scope (backward compatible); DM admin status does not imply group admin status; if only `group_allow_admin_from` is set, the DM scope stays unrestricted. `/whoami` reports the active scope, the tier (admin / user / unrestricted) and the runnable commands.
- **Inputs / options:** four list-valued keys, plus the existing `allow_from`.
- **Outputs / side effects:** command-level authorization.
- **Config / env:** the keys above (enforcement lives in `gateway/slash_access.py`).
- **Edge cases / guards:** Observe-mode deliberately keeps `user_id` on COMMAND events so admin checks still work in groups (see `platform-telegram.observe-attribution`).
- **Rebuild notes:** Per-scope admin lists with an always-allowed floor.

### BotFather privacy policy requirement  `id: platform-telegram.privacy-policy`
- **Surface:** Docs
- **Where:** `telegram.md:947-948`.
- **What it does:** Notes that Telegram now requires bots to have a privacy policy.
- **How it works:** "Set one via BotFather with `/setprivacy_policy`, or Telegram may auto-generate a placeholder. This is particularly important if your bot is public-facing."
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Security guidance  `id: platform-telegram.security-docs`
- **Surface:** Docs
- **Where:** `telegram.md:1337-1345`.
- **What it does:** States the two hard security rules for a Telegram deployment.
- **How it works:** Warning box: "Always set `TELEGRAM_ALLOWED_USERS` to restrict who can interact with your bot. Without it, the gateway denies all users by default as a safety measure." Plus: "Never share your bot token publicly. If compromised, revoke it immediately via BotFather's `/revoke` command." Points at the Security documentation and at DM pairing as a dynamic alternative to allowlists.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a.
- **Config / env:** `TELEGRAM_ALLOWED_USERS`.
- **Edge cases / guards:** Matches the fail-closed default in `_is_callback_user_authorized`.
- **Rebuild notes:** n/a.

### Documented-but-unimplemented: pin incoming user message during a turn  `id: platform-telegram.pin-incoming-doc`
- **Surface:** Docs
- **Where:** `telegram.md:1333-1335`: "When a user sends a message that triggers an agent turn, the Telegram adapter pins that incoming message for the duration of the turn and unpins it when the response is finished — a lightweight visual indicator that the bot is actively working on the message rather than ignoring it. The pin uses `disable_notification=true` to avoid extra pings. No config required."
- **What it does:** Documented as an automatic pin/unpin around each agent turn.
- **How it works:** **Not found in the v2026.8.31 code.** The only `pin_chat_message` call in the tree is `_ensure_telegram_system_topic` (`gateway/run.py:24722-24729`), and `plugins/platforms/telegram/adapter.py` contains no pin/unpin call at all (grep for `pin_chat_message`/`unpin` over `gateway/*.py` and `plugins/platforms/telegram/*.py` returns only that one site). The visible in-progress signal that IS implemented is the 👀 reaction (`platform-telegram.reactions`).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a (documented only).
- **Config / env:** "No config required" per the docs.
- **Edge cases / guards:** Treat this as a documentation/implementation discrepancy when reimplementing — either build the pin or drop the paragraph.
- **Rebuild notes:** If rebuilt: pin with `disable_notification=True` on turn start, unpin in a `finally` so an interrupted turn cannot leave a permanent pin.

### DM Topics vs multi-session mode — comparison  `id: platform-telegram.topics-comparison`
- **Surface:** Docs
- **Where:** `telegram.md:760-772`.
- **What it does:** Tells operators which of the two topic systems to use.
- **How it works:** Table rows: **Who activates it** — Operator in `config.yaml` vs End user by sending `/topic`; **Topic list** — Fixed set declared in config vs User creates/deletes freely; **Topic names** — Chosen by operator vs Chosen by user, auto-renamed to the Hermes session title; **Root DM behavior** — Normal chat (lobby if `ignore_root_dm: true`) vs Becomes a system lobby (non-command messages rejected); **Primary use case** — Permanent workspaces with optional skill binding vs Ad-hoc parallel sessions; **Persistence** — `extra.dm_topics` in config vs `telegram_dm_topic_mode` + `telegram_dm_topic_bindings` SQLite tables. Both can coexist on the same bot.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a.
- **Config / env:** `platforms.telegram.extra.dm_topics`, `state.db`.
- **Edge cases / guards:** Operator-declared topics are never auto-renamed even when multi-session mode is on.
- **Rebuild notes:** n/a.

### Downgrade behaviour for multi-session topics  `id: platform-telegram.topic-downgrade`
- **Surface:** Docs
- **Where:** `telegram.md:876-878`.
- **What it does:** Documents what happens when Hermes is downgraded below the `/topic` feature.
- **How it works:** "the feature simply stops working — the `telegram_dm_topic_mode` and `telegram_dm_topic_bindings` tables remain in `state.db` but are ignored by older code. DMs revert to the native per-thread isolation (each `message_thread_id` still gets its own session via `build_session_key`), so your existing Telegram topics keep working as parallel sessions. The root DM is no longer a lobby — messages there go into the agent like they used to. Re-upgrading reactivates multi-session mode exactly where it was."
- **Inputs / options:** n/a. **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Additive-only schema is what makes the downgrade safe.
- **Rebuild notes:** Keep new state in additive side tables so a rollback degrades instead of breaking.

### `/start` — platform ping, never a command  `id: platform-telegram.start`
- **Surface:** Gateway/Telegram
- **Where:** Telegram sends `/start` when a user opens the bot for the first time or follows a `t.me/<bot>?start=…` deep link. The bot replies with NOTHING.
- **What it does:** Swallows the launch ping so it does not dump `/help`, interrupt a running agent, or queue text.
- **How it works:** Declared in `hermes_cli/commands.py:149-150` as `CommandDef("start", "Acknowledge platform start pings without a reply", "Session", gateway_only=True, busy_policy="dispatch", busy_handler="start")`. Idle path: `gateway/run.py:19011-19013` returns `""` and logs `Ignoring /start platform ping for session %s`. Busy path: `_busy_start_command` (`gateway/run.py:17868-17873`, registered in the busy-handler map at `gateway/run.py:17806`) returns `""` and logs `Ignoring /start platform ping for active session %s`, explicitly documented as "Telegram sends /start for bot launches/deep-links. Treat it as a platform ping, not a user command".
- **Inputs / options:** any deep-link payload after `/start` is ignored.
- **Outputs / side effects:** an empty reply (no message sent).
- **Config / env:** n/a.
- **Edge cases / guards:** `busy_policy="dispatch"` means it is handled even while the agent is mid-turn, without interrupting it. In a topic-mode root lobby it also passes as a command (`ignore_root_dm` only drops non-commands).
- **Rebuild notes:** Every platform has a launch ping — absorb it explicitly rather than letting it fall through to the agent.

### DM pairing writes into `TELEGRAM_ALLOWED_USERS`  `id: platform-telegram.pairing-allowlist`
- **Surface:** Core | Config
- **Where:** Approving a Telegram pairing code (`hermes pairing approve …` / dashboard) also adds the user to the operator's allowlist.
- **What it does:** Keeps the operator's own allowlist the single visible source of truth instead of letting it drift from an opaque `approved.json`.
- **How it works:** `gateway/pairing.py:99-101` maps `"telegram" → "TELEGRAM_ALLOWED_USERS"` in `_PLATFORM_ALLOWLIST_ENV`; approving writes the user id into that variable and revoking removes it (#23778). Platforms absent from the map, or with no allowlist configured, keep the pairing store as the sole grant record, honoured by the authz union. The pairing directory is `~/.hermes/platforms/pairing`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `TELEGRAM_ALLOWED_USERS` updated in `~/.hermes/.env`; pairing store rows.
- **Config / env:** `TELEGRAM_ALLOWED_USERS`, `platforms.telegram.extra.unauthorized_dm_behavior`.
- **Edge cases / guards:** The adapter's intake prefilter lets unauthorized DMs through specifically so this handshake can happen (`platform-telegram.pairing-passthrough`).
- **Rebuild notes:** Reflect dynamic grants back into the static config the operator edits.

### `TELEGRAM_ALLOW_BOTS` — admitting other bots  `id: platform-telegram.allow-bots`
- **Surface:** Env | Config
- **Where:** `telegram.allow_bots` in `config.yaml` (bridged at `adapter.py:11188-11189`) or `TELEGRAM_ALLOW_BOTS`.
- **What it does:** Lets messages from OTHER bots reach the agent, bypassing the human allowlist.
- **How it works:** `gateway/authz_mixin.py:603-612`: when `source.is_bot` is true and `_platform_gate_env("TELEGRAM_ALLOW_BOTS", "none").lower().strip()` is `mentions` or `all`, authorization returns True immediately — checked BEFORE the "no user id" guard, because some platforms deliver bot traffic without a user id. `is_bot` is set on the source by `_build_message_event` from `user.is_bot` (`adapter.py:10884`).
- **Inputs / options:** `none` (default) | `mentions` | `all`.
- **Outputs / side effects:** authorization decision.
- **Config / env:** `TELEGRAM_ALLOW_BOTS`, `telegram.allow_bots`.
- **Edge cases / guards:** Read through the profile-scoped `_platform_gate_env`, like every other gate.
- **Rebuild notes:** Keep bot admission a separate, three-valued knob — never a side effect of the human allowlist.

### Telegram display defaults (tool progress, heartbeats, streaming)  `id: platform-telegram.display-defaults`
- **Surface:** Config
- **Where:** `display.platforms.telegram.*` in `config.yaml`; the dashboard Config page renders `display.platforms.telegram.streaming` as **`Display → Platforms → Telegram → Streaming`** (boolean, default `true`).
- **What it does:** Tunes how chatty the bot is on Telegram — by default quiet about individual tool calls but still sending mid-turn commentary and heartbeats.
- **How it works:** `gateway/display_config.py:121-134` sets the Telegram platform defaults as `{**_TIER_HIGH, "tool_progress": "off", "busy_ack_detail": False}`, where `_TIER_HIGH` (l.81-89) is `{"tool_progress": "all", "show_reasoning": False, "tool_preview_length": 40, "streaming": None, "interim_assistant_messages": True, "long_running_notifications": True, "busy_ack_detail": True}`. Resolution order (module docstring, l.6-14): `display.platforms.<platform>.<key>` → `display.<key>` → platform default → global default; `display.streaming` is CLI-only, so gateway streaming follows the top-level `streaming` config unless the per-platform override is set.
- **Inputs / options:** overridable keys include `tool_progress` (`all`/`new`/`off`), `tool_progress_grouping` (`accumulate`/`separate`), `show_reasoning`, `reasoning_style` (`code`/`blockquote`/`subtext`), `tool_preview_length`, `streaming`, `interim_assistant_messages`, `long_running_notifications`, `busy_ack_detail`, `busy_steer_ack_enabled`, `cleanup_progress`.
- **Outputs / side effects:** message volume and content on Telegram.
- **Config / env:** `display.platforms.telegram.*`, `display.*`.
- **Edge cases / guards:** The comment at `display_config.py:122-129` explains the reasoning: Telegram is usually a mobile inbox, so per-tool progress is off but heartbeats stay on — "Otherwise it looks like 'typing...' for 30 minutes with nothing happening." `cleanup_progress` (default false, `display_config.py:56-62`) deletes progress/status bubbles after a successful final response on platforms that support deletion, explicitly naming Telegram; failed runs keep the bubbles as breadcrumbs.
- **Rebuild notes:** Per-platform display tiers with an explicit override chain; default mobile surfaces to quiet-but-alive.

### Telegram settings on the dashboard Config page  `id: platform-telegram.dashboard-fields`
- **Surface:** Web dashboard
- **Where:** Config page; live `GET /api/config/schema` exposes exactly five Telegram-related fields.
- **What it does:** Lets an operator flip the most common Telegram switches from the browser.
- **How it works:** From the live schema dump (`hermes_inv/api_live/config_schema.json`): `display.platforms.telegram.streaming` — label/description **`Display → Platforms → Telegram → Streaming`**, type `boolean`, category `display`, default `true`; `telegram.reactions` — **`Telegram → Reactions`**, boolean, default `false`; `telegram.allowed_chats` — **`Telegram → Allowed Chats`**, string, default `""`; `telegram.extra.rich_messages` — **`Telegram → Extra → Rich Messages`**, boolean, default `false`; `telegram.extra.rich_drafts` — **`Telegram → Extra → Rich Drafts`**, boolean, default `false`.
- **Inputs / options:** the five fields above.
- **Outputs / side effects:** writes into `~/.hermes/config.yaml`.
- **Config / env:** as listed.
- **Edge cases / guards:** The four `telegram.*` fields are reported with `"category": "discord"` in the live schema — a mis-categorisation that groups them under the Discord section of the Config page. Every other Telegram key (allowlists, topics, mention gating, transport tuning) is YAML/env-only.
- **Rebuild notes:** Derive the settings UI from the same registry the adapter reads, and assign categories per key prefix rather than by hand.

### Telegram session-key knobs  `id: platform-telegram.session-keying`
- **Surface:** Config
- **Where:** `platforms.telegram.extra.group_sessions_per_user`, `platforms.telegram.extra.thread_sessions_per_user`.
- **What it does:** Decide whether each group member gets their own session and whether each thread splits per user — which in turn defines the batching keys the adapter uses.
- **How it works:** Read in `_text_batch_key` (`adapter.py:10031-10039`) and `_photo_batch_key` (`adapter.py:10142-10148`) and passed to `gateway.session.build_session_key(source, group_sessions_per_user=extra.get("group_sessions_per_user", True), thread_sessions_per_user=extra.get("thread_sessions_per_user", False), profile=self._session_key_profile(source))`. Defaults: `group_sessions_per_user=True`, `thread_sessions_per_user=False`. DM topics produce keys of the form `agent:main:telegram:dm:{chat_id}:{thread_id}` (docs `telegram.md:704-709`).
- **Inputs / options:** two booleans.
- **Outputs / side effects:** session isolation and batch grouping.
- **Config / env:** the two keys above.
- **Edge cases / guards:** Batching and dispatch MUST use the same key, which is why `_text_batch_key` applies topic recovery first.
- **Rebuild notes:** Derive batch keys from the session key, never from raw chat ids.

---


## 11. Remaining internals (routing, coercion, drop-guard)

### Single-send routing for the rich path  `id: platform-telegram.single-send-routing`
- **Surface:** Core
- **Where:** Internal; runs before every rich-message send to decide the anchor and topic kwargs.
- **What it does:** Mirrors `send()`'s chunk-0 routing block for the one-shot rich path, and refuses to guess when a private DM-topic send has no usable anchor.
- **How it works:** `_compute_single_send_routing(chat_id, reply_to, metadata, thread_id)` at `adapter.py:2188-2232`. Computes `metadata_reply_to = _metadata_reply_to_message_id(metadata)`, `private_dm_topic_send = _is_private_dm_topic_send(...)`, and `dm_topic_reply_to_off` (private topic + `reply_to_mode == "off"` + `metadata["telegram_dm_topic_reply_fallback"]`). The anchor source is `reply_to` or, for private DM topics, the metadata anchor. Threading: private DM topics require a non-None anchor and `reply_to_mode != "off"`; everything else defers to `_should_thread_reply(source, 0)`. Returns `(reply_to_id, thread_kwargs)`, or **`None`** when a private DM-topic send has no anchor, no `off` opt-out and no `direct_messages_topic_id` — signalling "skip rich, let the legacy path emit the canonical fail-loud `SendResult`".
- **Inputs / options:** `chat_id`, `reply_to`, `metadata`, `thread_id`.
- **Outputs / side effects:** routing tuple or `None`.
- **Config / env:** `reply_to_mode`.
- **Edge cases / guards:** Keeping ONE source of the refusal message (the legacy path) is deliberate, so rich and legacy cannot drift.
- **Rebuild notes:** When two code paths can refuse, let only one own the refusal text.

### Extra-value coercion helpers  `id: platform-telegram.extra-coercion`
- **Surface:** Config
- **Where:** Every `platforms.telegram.extra.*` boolean/float the adapter reads.
- **What it does:** Accepts YAML booleans, YAML numbers and quoted strings interchangeably, with clamping and safe defaults.
- **How it works:** `_coerce_bool_extra(key, default=False)` at `adapter.py:1916-1927`: `None` → default; strings `true|1|yes|on` → True, `false|0|no|off` → False, anything else → default; other types → `bool(value)`. `_coerce_float_extra(key, default, *, min_value=None, max_value=None)` at `adapter.py:1929-1948`: `None` or unparsable → default, then clamped. `_env_float_clamped(name, default, *, min_value, max_value)` at `adapter.py:669-695` does the same for env vars and additionally rejects NaN/Inf (`math.isfinite`) so the value is always safe for `asyncio.sleep()`.
- **Inputs / options:** the key name, default and bounds.
- **Outputs / side effects:** coerced value.
- **Config / env:** consumers include `disable_link_previews`, `rich_messages`, `rich_drafts`, `typing_cooldown_seconds`, `HERMES_TELEGRAM_TEXT_BATCH_DELAY_SECONDS`, `HERMES_TELEGRAM_TEXT_BATCH_SPLIT_DELAY_SECONDS`.
- **Edge cases / guards:** An unrecognised string never becomes `True` by accident — it falls back to the documented default.
- **Rebuild notes:** One coercion helper per type, used everywhere; never call `bool()` on a raw YAML string.

### Delayed-delivery drop guard  `id: platform-telegram.drop-guard`
- **Surface:** Core
- **Where:** Checked by every buffered flush (text, photo, media group) and by the enqueue paths.
- **What it does:** Stops a buffered event from dispatching after teardown or a fatal error has started, without destroying it.
- **How it works:** `_should_drop_delayed_delivery()` at `adapter.py:985-997` returns `self._drop_delayed_deliveries`, set during disconnect/fatal handling and cleared in `_mark_connected` (`adapter.py:903-908`). Because buffered flushes sit behind an `asyncio.sleep()`, a disconnect can win the race; dispatching then would spawn an agent on a torn-down session and produce stale or duplicate deliveries. Callers must NOT destroy the event — PTB has already advanced the polling offset so Telegram will never redeliver — and instead call `_hold_inbound_event(event, where=…)` for redispatch on reconnect (a permanent fatal discards explicitly).
- **Inputs / options:** n/a.
- **Outputs / side effects:** boolean; drives the held-inbound queue.
- **Config / env:** n/a.
- **Edge cases / guards:** `HELD_INBOUND_MAX = 64` (`adapter.py:631-633`) bounds memory during extended outages, dropping oldest first.
- **Rebuild notes:** Guard + hold, never guard + discard, whenever the transport has already acknowledged the update.

---

## Handoffs

- `gw-slash`: the full slash-command catalogue and dispatch (`gateway/slash_commands.py`, 57 `_handle_*_command` handlers) — only `/topic`, `/start` and the Telegram-specific rendering of `/model`, `/reasoning`, `/fast` are covered here.
- `gw-core`: `BasePlatformAdapter`, `stream_consumer`, delivery ledger, `resolve_channel_prompt`, `cache_*_from_bytes` / `cache_media_bytes`, `transcode_to_ogg_opus`, `build_session_key`, pairing store internals, `tools.approval` / `tools.clarify_gateway` / `tools.slash_confirm` primitives, STT/TTS pipelines.
- `gw-core` / `providers`: `hermes_cli.models.group_providers` + `PROVIDER_GROUPS`, `hermes_cli.providers.get_label`, `hermes_cli.model_selection_guards.combined_selection_warning` — the data behind the Telegram model picker.
- `config-a` / `config-b`: the global config-key catalogue; this shard documents only Telegram-scoped keys.
- `web-*`: the dashboard Config page mechanics; this shard lists only the five Telegram fields it exposes.
- `cli-*`: `hermes gateway setup|start|status|stop`, `hermes -p <profile>`, `hermes pairing`, `hermes sessions`, `hermes update --gateway`.
- `optional`: the `gmail-triage` skill that generates the `gt:` inline keyboards and ships the scripts under `~/.hermes/scripts/gmail-triage/`.
- `tools`: `tools/send_message_tool.py::_send_telegram` (the standalone REST sender), `tools/vision_tools.py::vision_analyze_tool` (sticker descriptions), `tools/url_safety.py` (SSRF guards).
- `platforms-a` / `platforms-b`: every non-Telegram adapter, including the Discord/Slack analogues referenced in code comments.
