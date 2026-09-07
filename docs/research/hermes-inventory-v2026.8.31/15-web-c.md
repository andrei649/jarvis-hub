# Web dashboard — Channels, Webhooks, Pairing, Profiles, Config, Keys/Env, System, Docs, Login

This shard documents nine routes of the Hermes Agent web dashboard SPA (`web/`, served by
`hermes_cli/web_server.py` on `hermes web`/`hermes dashboard`): `/channels`, `/webhooks`,
`/pairing`, `/profiles`, `/profiles/new` (Profile Builder wizard), `/config`, `/env` (labelled
"Keys"), `/system`, `/docs`, plus the server-rendered `/login` page and the auth round trip that
guards every other route. Every visible label, button, toggle, placeholder, badge, toast and
confirm-dialog string on those pages is enumerated here verbatim, together with the REST call it
makes and the file:line that renders it.
Deliberately left to sibling shards: Chat/Sessions/Files/Models/Logs/Cron/Skills/Plugins/MCP/
Analytics pages and the app shell (sidebar, header, theme/language switchers, profile switcher,
status strip) → `web-a` / `web-b`; the *semantics* of individual config keys and env vars →
`config-a` / `config-b`; the CLI commands the pages mirror → `cli-a` / `cli-b`; gateway platform
adapters themselves → the gateway shards. Here only the PAGE mechanics are documented.

---

## 1. Channels page (`/channels`)

### Channels page  `id: web-c.channels.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `CHANNELS` (href `/channels`); page `<h1>` reads "Channels".
- **What it does:** One card per messaging platform Hermes can connect to (33 in v2026.8.31). Each card shows live connection state, an enable/disable switch, a "Test" probe and a "CONFIGURE" modal that writes the platform's credentials into `~/.hermes/.env`.
- **How it works:** `web/src/pages/ChannelsPage.tsx:132` (`ChannelsPage`) loads `GET /api/messaging/platforms` via `api.getMessagingPlatforms()` (`web/src/lib/api.ts:877`) on mount (`ChannelsPage.tsx:161-173`). The response is `{env_path, gateway_start_command, platforms[]}` built by `hermes_cli/web_server.py:10648` `get_messaging_platforms()`; each platform payload is produced by `_messaging_platform_payload()` (`web_server.py:9610`) from the catalog `_messaging_platform_catalog()` (`web_server.py:9396`), which merges `gateway.config.Platform` enum members (minus `local`) with plugin adapters from `gateway.platform_registry.platform_registry.plugin_entries()`, sorts by `_PLATFORM_ORDER`, and attaches per-platform UI metadata from `_PLATFORM_OVERRIDES`. Live connection state comes from `gateway_state.json` (`read_runtime_status`) combined with `resolve_gateway_liveness()` (health probe → PID probe → runtime status). Page state is entirely client-side React state; nothing is cached to localStorage.
- **Inputs / options:** Page-header button "RESTART GATEWAY" (see `web-c.channels.restart-header`); per card: enable `Switch` (`aria-label="Enable <platform name>"`), "Test" button, "CONFIGURE" button (absent for Telegram), plus the Telegram and WhatsApp inline onboarding panels. Config modal fields are per-platform (documented in each platform entry below).
- **Outputs / side effects:** Reads only until the user acts. Saving writes env keys through `PUT /api/messaging/platforms/{id}` → `save_env_value()` into the profile's `.env`; toggling writes `platforms.<id>.enabled` into `config.yaml` via `_write_platform_enabled()` → `write_platform_config_field()` (`web_server.py:9780`).
- **Config / env:** Reads/writes `platforms.<platform_id>.enabled` in `config.yaml` and all platform credential env vars in `.env`. Path shown to the user comes from `env_path` (`get_env_path()`).
- **Edge cases / guards:** While loading, the whole page is a centred `Spinner` (`ChannelsPage.tsx:295-301`). `gatewayRunning` is derived from `platforms[0].gateway_running` (`ChannelsPage.tsx:157`) — with zero platforms the banner logic treats the gateway as stopped. Enabling a port-binding platform on a non-default profile while `gateway.multiplex_profiles` is on returns HTTP 409 with an explanatory message (`web_server.py:10680` `_multiplex_port_binding_conflict`).
- **Rebuild notes:** Model a channel as `{id, name, description, docs_url, env_vars[{key,required,is_set,redacted_value,description,prompt,help,url,is_password,advanced}], enabled, configured, gateway_running, state, error_code, error_message, updated_at, home_channel}`. Render card = status icon + name + state badge + description + switch + Test + Configure. A better version would apply credentials without a gateway restart (hot-reload the adapter) and show a per-channel live message counter.

### Channels → page header "RESTART GATEWAY"  `id: web-c.channels.restart-header`
- **Surface:** Web dashboard
- **Where:** `/channels` → page header, right side; label "Restart gateway" rendered uppercase (`className="uppercase"`), so it appears as "RESTART GATEWAY". While in flight the label becomes "Restarting…".
- **What it does:** Restarts the Hermes gateway process so newly saved channel credentials/toggles take effect.
- **How it works:** `ChannelsPage.tsx:262-286` `handleRestart()` → `api.restartGateway()` → `POST /api/gateway/restart`. On success it toasts "Gateway restarting…", clears the `restartNeeded` banner and re-runs `load()` after a 4000 ms `setTimeout`. Registered into the shared page header via `usePageHeader().setEnd` in a `useLayoutEffect` (`ChannelsPage.tsx:288-301`).
- **Inputs / options:** Single click; disabled while `restarting` is true; prefix icon swaps `RotateCw` → `Spinner`.
- **Outputs / side effects:** Restarts the gateway process; toast "Gateway restarting…" (success) or "Failed to restart: <error>" (error).
- **Config / env:** n/a
- **Edge cases / guards:** No confirm dialog on this page (unlike the sidebar's "Restart Gateway" which confirms with `status.restartGatewayConfirmTitle`). Failure leaves `restartNeeded` set.
- **Rebuild notes:** Fire-and-forget POST plus an optimistic 4 s refresh. Better: stream the restart's stdout/exit code (the WhatsApp/Telegram panels already poll `GET /api/actions/gateway-restart/status`) and surface it inline.

### Channels → "Changes are saved. Restart the gateway for them to take effect." banner  `id: web-c.channels.restart-banner`
- **Surface:** Web dashboard
- **Where:** `/channels`, top of the page, warning-bordered card. Text: "Changes are saved. Restart the gateway for them to take effect."; button label "Restart now" (uppercase → "RESTART NOW"), "Restarting…" while busy.
- **What it does:** Tells the user a channel edit is persisted but not live, and offers a one-click restart.
- **How it works:** `ChannelsPage.tsx:309-331`. Rendered when the local `restartNeeded` flag is true; the flag is set by `handleSave()` (`:216`), `handleToggle()` (`:236`), and by the Telegram/WhatsApp panels via `onRestartNeeded`. `AlertTriangle` icon, `Card className="border-warning/50"`.
- **Inputs / options:** "Restart now" button → same `handleRestart()` as the header button.
- **Outputs / side effects:** Same as `web-c.channels.restart-header`.
- **Config / env:** n/a
- **Edge cases / guards:** Purely client-side state — a page reload clears it even if a restart is still required.
- **Rebuild notes:** Track "config dirty since gateway start" server-side (compare `.env` mtime to gateway start time) so the banner survives reloads.

### Channels → "The gateway is not running." banner  `id: web-c.channels.gateway-stopped-banner`
- **Surface:** Web dashboard
- **Where:** `/channels`, below the restart banner. Full text: "The gateway is not running. Configure channels here, then start the gateway with `hermes gateway start` (or the Restart button above)."
- **What it does:** Explains that channel edits are inert until the gateway runs, and shows the exact start command.
- **How it works:** `ChannelsPage.tsx:333-347`. Shown when `!gatewayRunning && !restartNeeded`. The command string is `gatewayStartCommand` from the API response (`_gateway_display_command(profile, "start")`, `web_server.py:10662`) — it becomes `hermes --profile <name> gateway start` for a non-default profile. `WifiOff` icon.
- **Inputs / options:** None (informational).
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** Hidden while the restart banner is visible so the two don't stack.
- **Rebuild notes:** Include a copy-to-clipboard affordance on the command; the current version renders it as plain `<code>`.

### Channels → configured-count summary line  `id: web-c.channels.summary`
- **Surface:** Web dashboard
- **Where:** `/channels`, above the card list. Text: "{n} of {total} channels configured. Credentials are written to `<env_path>`; the gateway connects each enabled channel on its next restart."
- **What it does:** Counts how many platform cards report `configured: true` and names the `.env` file that receives credentials.
- **How it works:** `ChannelsPage.tsx:349-354`; `configured` is `useMemo(() => platforms.filter(p => p.configured).length)` (`:293-296`). `envPath` defaults to the literal string `"~/.hermes/.env"` when the API omits it (`ChannelsPage.tsx:136`, `:167`).
- **Inputs / options:** None.
- **Outputs / side effects:** None.
- **Config / env:** Displays the resolved `.env` path (profile-scoped when a management profile is selected).
- **Edge cases / guards:** `configured` for a scoped profile is computed from the profile's own `.env` only, never the root install's `os.environ` (`web_server.py:9690-9700`).
- **Rebuild notes:** Trivial; keep the env-path disclosure — it is the only place the dashboard tells the user where secrets land.

### Channels → platform card anatomy  `id: web-c.channels.card`
- **Surface:** Web dashboard
- **Where:** `/channels` → one `Card` per platform, in catalog order.
- **What it does:** Shows a platform's name, state badge, description, any error message, and the three controls (enable switch, "Test", "CONFIGURE").
- **How it works:** `ChannelsPage.tsx:516-621`. Icon selection: `CheckCircle2` when `state === "connected"`, `AlertTriangle` when `state` is `"fatal"` or `"startup_failed"`, else `Radio` (`:521-527`). Colour: `text-success` / `text-destructive` / `text-muted-foreground`. Name uses `font-mondwest normal-case`. Badge from `stateBadge()` (`:56`). `platform.error_message` renders in `text-destructive` beneath the description.
- **Inputs / options:** (1) `Switch` with `aria-label="Enable <platform.name>"` — 33 such switches, one per card; while toggling it is replaced by a `Spinner`. (2) Ghost button "Test" (33 instances) with `PlugZap` icon. (3) Primary button "CONFIGURE" (`Settings2` icon) — rendered for every platform **except** `telegram` (32 instances). (4) Telegram cards additionally render `TelegramOnboardingPanel`; WhatsApp cards render `WhatsAppOnboardingPanel`.
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/{id}` `{enabled}`; optimistically sets local `state` to `"pending_restart"` (enabling) or `"disabled"` (disabling) and raises `restartNeeded`. Test → `POST /api/messaging/platforms/{id}/test`, result toasted as "`<name>`: `<message>`". Configure → opens the modal.
- **Config / env:** `platforms.<id>.enabled`.
- **Edge cases / guards:** Toggle errors toast "Error: `<e>`" and leave the switch at its previous value (no optimistic rollback beyond not applying the change). `testingId`/`togglingId` guard double clicks per card.
- **Rebuild notes:** Keep the switch optimistic but reconcile from a follow-up GET; the current code only rewrites local state.

### Channels → connection-state badges  `id: web-c.channels.state-badges`
- **Surface:** Web dashboard
- **Where:** `/channels` → badge to the right of each platform name.
- **What it does:** Translates the backend's state vocabulary into a coloured badge.
- **How it works:** `STATE_BADGE` map at `ChannelsPage.tsx:43-56`; unknown states fall through to `{tone:"outline", label:<raw state>}` (`:58-60`). State is computed server-side in `_messaging_platform_payload()` (`web_server.py:9705-9730`).
- **Inputs / options:** The complete vocabulary, verbatim label → tone:
  - `connected` → "Connected" (success)
  - `pending_restart` → "Restart to apply" (warning)
  - `gateway_stopped` → "Gateway stopped" (warning)
  - `startup_failed` → "Start failed" (destructive)
  - `disconnected` → "Disconnected" (warning)
  - `not_configured` → "Not configured" (outline)
  - `disabled` → "Disabled" (secondary)
  - `fatal` → "Error" (destructive)
  - anything else → the raw state string (outline)
- **Outputs / side effects:** Display only.
- **Config / env:** n/a
- **Edge cases / guards:** Server precedence: not enabled → `disabled`; enabled but missing required env → `not_configured`; gateway running with no runtime state → `pending_restart`; gateway down with `gateway_state == "startup_failed"` → `startup_failed`; gateway down otherwise → `gateway_stopped`. Otherwise the adapter's own runtime state (`connected`/`disconnected`/`fatal`) wins.
- **Rebuild notes:** Keep the server as the single source of the state ladder — the historical bug was two endpoints disagreeing (`web_server.py:9622-9631`).

### Channels → "Configure <platform>" modal  `id: web-c.channels.config-modal`
- **Surface:** Web dashboard
- **Where:** `/channels` → card → "CONFIGURE". Modal title is "Configure `<platform.name>`", except Telegram whose modal (reached via "MANUAL SETUP") is titled "Use your own Telegram bot".
- **What it does:** Collects the platform's credentials/settings and saves them to `.env`, enabling the platform in the same request.
- **How it works:** `ChannelsPage.tsx:353-507`. `openConfig()` (`:176-184`) seeds `draftEnv` with an empty string per `env_var` so blank means "keep existing". `handleSave()` (`:186-229`) filters to non-blank trimmed values, refuses an all-blank submit, checks required-and-unset fields, runs `validateMessagingEnvField()` per field, then `PUT /api/messaging/platforms/{id}` with `{env, enabled: true}`. Modal behaviour (Escape to close, focus trap, scroll lock) comes from `useModalBehavior({open, onClose})` (`web/src/hooks/useModalBehavior.ts`). Backdrop click closes.
- **Inputs / options:** Header: docs link labelled "Setup guide" (Telegram: "BotFather guide") linking to `platform.docs_url`, with `ExternalLink` icon; close button `aria-label="Close"` (X icon). Body: the platform description paragraph, then one field per `env_var` — `<Label>` = `field.prompt || field.key`, suffixed " *" when `field.required`; an `Info` icon with `title`/`aria-label` = `field.help` when help text exists; `field.description` as sub-label; an `<Input>` with `id="field-<KEY>"`, `type="password"` when `field.is_password` else `"text"`, placeholder = `field.redacted_value` or the literal "•••••• (set — leave blank to keep)" when already set, else the raw env key name; inline `text-destructive` error under the field when validation fails. Footer: ghost "Cancel", primary "Save & enable" (uppercase → "SAVE & ENABLE"; "Saving…" while in flight).
- **Outputs / side effects:** On success: toast "`<name>` saved", modal closes, `restartNeeded` set, list reloaded. Writes the submitted keys to `.env`, sets `platforms.<id>.enabled = true` in `config.yaml`, and the server logs `Messaging platform updated: platform=… env_keys=[…]` (names only, never values).
- **Config / env:** Every key listed in the platform's `env_vars` (enumerated per platform below).
- **Edge cases / guards:** Empty submit → toast "Nothing to save — fill in at least one field." Missing required → toast "`<prompt or key>` is required". Validation failures → toast "Fix the highlighted fields before saving." Server rejects any key not in the platform's `allowed_env` set with HTTP 400 "`<KEY>` is not configurable for `<name>`". Server-side `_validate_messaging_env_value()` (`web_server.py:4856`) re-checks values.
- **Rebuild notes:** The blank-means-keep contract is the important part: never send empty strings, or you erase stored secrets. A better version would offer per-field "clear" (the API already supports `clear_env`, which this modal never uses).

### Channels → client-side field validation  `id: web-c.channels.field-validation`
- **Surface:** Web dashboard
- **Where:** `/channels` → config modal, inline error text under a field.
- **What it does:** Rejects malformed tokens/IDs before they reach the server.
- **How it works:** `validateMessagingEnvField()` at `ChannelsPage.tsx:69-108`, with regexes at `:62-68`.
- **Inputs / options:** The complete rule set:
  - `TELEGRAM_BOT_TOKEN` must match `/^\d+:[A-Za-z0-9_-]{30,}$/`; else "Paste the complete token from @BotFather (for example, 123456789:ABC…)."
  - `TELEGRAM_ALLOWED_USERS`: every comma-separated part must match `/^\d+$/`; else "`<part>` is not a numeric Telegram user ID."
  - `SLACK_BOT_TOKEN` must start with `xoxb-`; else "`<prompt or key>` must start with xoxb-"
  - `SLACK_APP_TOKEN` must start with `xapp-`; else "`<prompt or key>` must start with xapp-"
  - `SLACK_ALLOWED_USERS`: each non-empty part must be `*` or match `/^[UW][A-Z0-9]{2,}$/`; else "`<part>` does not look like a Slack member ID. Use IDs like U01ABC2DEF3."
  - Empty/blank values are always accepted (they mean "keep existing").
- **Outputs / side effects:** Sets `fieldErrors[key]`, marks the input `aria-invalid`, blocks the save.
- **Config / env:** n/a
- **Edge cases / guards:** Mirrors the gateway's own parsing for Slack allowlists (empty entries dropped, `*` wildcard honoured — see `gateway/platforms/slack.py`).
- **Rebuild notes:** Duplicate the validation server-side too (Hermes does, in `_validate_messaging_env_value`), because the modal is not the only writer.

### Channels → Telegram onboarding panel ("Choose how to connect your Telegram bot")  `id: web-c.channels.telegram-panel`
- **Surface:** Web dashboard
- **Where:** `/channels` → Telegram card → inline panel below the card header. Headline "Choose how to connect your Telegram bot"; sub-line "Both options connect a bot you control and save its credentials only to this Hermes installation." Two columns: left "Quick setup" with a green badge "recommended"; right "Use your own bot".
- **What it does:** Offers a QR-driven bot creation flow (Hermes creates the bot via a pairing broker and auto-detects the owner's numeric user ID) or a manual BotFather token entry.
- **How it works:** `ChannelsPage.tsx:1047-1438` (`TelegramOnboardingPanel`). Quick setup: `start()` (`:1147-1168`) → `POST /api/messaging/telegram/onboarding/start` with `{bot_name: "Hermes Agent"}`; the returned `qr_payload` is rendered with the `qrcode` npm package (`QRCode.toDataURL(payload, {errorCorrectionLevel:"M", margin:1, width:224})`). Phase machine: `idle → starting → waiting → ready → applying`. While `waiting`, `GET /api/messaging/telegram/onboarding/{pairing_id}` is polled every 2000 ms (first poll after 1200 ms) until `status === "ready"`, which yields `bot_username` and optionally `owner_user_id` (auto-added to the allowlist when it matches `/^\d+$/`).
- **Inputs / options:** Left column: paragraph "Scan a QR code and confirm in Telegram. Hermes creates the bot and detects your Telegram user ID automatically."; button "Create with QR" (uppercase → "CREATE WITH QR"; "Starting…" while starting), disabled unless `phase === "idle"`. Right column: paragraph "Create a bot with @BotFather, or connect one you already have, by entering its token and choosing who can use it."; outlined button "Manual setup" (uppercase → "MANUAL SETUP", `Bot` icon) which opens the standard config modal. When `platform.configured`: footnote "Telegram credentials are already configured. A new QR setup or bot token will replace the current bot when you save." When `phase !== "idle"`: footnote "Finish or cancel the current QR setup before switching methods."
- **Outputs / side effects:** Starting creates a server-side pairing session; applying writes `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS` and enables the platform; cancelling issues `DELETE /api/messaging/telegram/onboarding/{pairing_id}`.
- **Config / env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `platforms.telegram.enabled`.
- **Edge cases / guards:** A poll error whose message contains ` 410 ` plus one of `expired|claimed|gone` (`isTerminalTelegramOnboardingError`, `:120-123`), or an elapsed `expires_at`, resets the flow with the error "Telegram pairing expired. Start a new QR setup to try again." Other poll errors show "Still waiting for Telegram. Retrying after: `<error>`" and keep polling every 2 s. The Telegram card has **no** "CONFIGURE" button — manual setup is reached only through this panel.
- **Rebuild notes:** Model it as an out-of-band pairing broker: server mints a `pairing_id` + deep link, the user confirms in the messenger, the server hands back the bot token. Reproduce the terminal-vs-transient error split or the UI will spin forever on an expired session.

### Channels → Telegram QR pane ("Ready" / allowed-users editor)  `id: web-c.channels.telegram-qr`
- **Surface:** Web dashboard
- **Where:** `/channels` → Telegram card → appears once a QR setup starts, as a two-column block (details left, QR right).
- **What it does:** Displays the pairing QR + deep link, then (after the bot is ready) lets the user curate the allowed Telegram user-ID list before saving.
- **How it works:** `ChannelsPage.tsx:1303-1438`. QR `<img alt="Telegram setup QR code">` at 224 px (`h-56 w-56 bg-white p-2`). A 1 s `setInterval` (`tick`) re-renders the countdown; `formatExpiry()` (`:111-118`) renders `m:ss` or the literal "expired".
- **Inputs / options:**
  - Badge "Ready" (success) once `phase === "ready"`; the bot handle renders as `@<botUsername>` in `font-courier`.
  - Section label "Allowed users"; badge "owner detected" (success) when the auto-detected owner ID is in the list.
  - Each allowed ID is a removable chip button (click removes it; `X` icon).
  - Empty-state text: "Add at least one Telegram user ID."
  - `<Input placeholder="Telegram user ID">` + outlined button "Add" (`Check` icon) → `addAllowedId()`; non-numeric input sets the error "Allowed Telegram user IDs must be numeric."
  - Buttons "Save and restart" (uppercase; "Saving…" while applying, `Save` icon) and ghost "Cancel".
  - QR column: expiry badge (`destructive` tone when "expired", else `outline`), badge "waiting" (warning) while polling, anchor "Open Telegram" (`ExternalLink`, `href = setup.deep_link`, `target="_blank"`), ghost "Cancel".
- **Outputs / side effects:** `apply()` (`:1216-1254`) → `POST /api/messaging/telegram/onboarding/{id}/apply` `{allowed_user_ids}`. On `restart_started` → toast "Telegram saved; gateway restarting…", clears `restartNeeded`, reloads after 4 s and starts `watchRestartOutcome()`. When the response omits `restart_started` but sets `needs_restart`, the page falls back to `POST /api/gateway/restart` itself. Otherwise toast "Telegram saved; gateway restart failed`[: <restart_error>]`".
- **Config / env:** As above.
- **Edge cases / guards:** Applying with an empty allowlist is refused client-side with "Add at least one allowed Telegram user ID." `watchRestartOutcome()` (`:1189-1208`) polls `GET /api/actions/gateway-restart/status?lines=5` up to 20 times at 1.5 s intervals; a non-zero, non-null `exit_code` re-raises the manual-restart banner and toasts "Gateway restart failed (exit `<code>`) — restart manually". A still-running child at the end counts as success (no-service installs keep the gateway in the foreground).
- **Rebuild notes:** The countdown + terminal-error handling are the fiddly parts; everything else is a chip editor over a string list.

### Channels → WhatsApp onboarding panel ("Pair with QR")  `id: web-c.channels.whatsapp-panel`
- **Surface:** Web dashboard
- **Where:** `/channels` → WhatsApp card → inline panel.
- **What it does:** Links a WhatsApp account to the bundled whatsmeow bridge by showing a Linked-Devices QR code, then saves the mode + allowlist and restarts the gateway.
- **How it works:** `ChannelsPage.tsx:639-1045` (`WhatsAppOnboardingPanel`). `start()` → `POST /api/messaging/whatsapp/onboarding/start` `{mode, allowed_users}`; QR rendered at 240 px, `margin: 3`. Phase machine `idle → starting → waiting → connected → applying`. Polling: `GET /api/messaging/whatsapp/onboarding/{pairing_id}` on a 1500 ms timer (first poll after 1000 ms); the QR is re-rendered whenever `qr_payload` changes (WhatsApp rotates it). Server statuses: `starting | installing | waiting | connected | error | expired | cancelled` (`api.ts:2010`). Session TTL is 600 s (`_WHATSAPP_ONBOARDING_TTL_SECONDS`, `web_server.py:9787`).
- **Inputs / options:**
  - Button "Pair with QR" (uppercase → "PAIR WITH QR", `QrCode` icon; "Starting…" while starting), disabled during `starting`/`waiting`/`applying`.
  - Note "Existing WhatsApp settings are configured." when `platform.configured`.
  - Field group label "Mode" with two buttons: "Bot" and "Self-chat" (the inactive one is `outlined`); disabled during `waiting`/`applying`. Initial value comes from the saved `WHATSAPP_MODE` (`platform.whatsapp_setup.mode`), defaulting to `bot`.
  - `<Label htmlFor="whatsapp-allowed-users">Allowed WhatsApp numbers</Label>` + `<Input id="whatsapp-allowed-users" placeholder="15551234567,15557654321">`.
  - When a session is live: status badges — "Connected" (success) once linked, else the status word "preparing" (status `installing`) / "starting" (status `starting`) / "waiting"; plus the `m:ss` expiry badge.
  - Buttons "Save and restart" (uppercase, `Save` icon; "Saving…") and ghost "Cancel" (two Cancel buttons — one in the detail column, one under the QR).
  - Link "Open chat link" (`ExternalLink`) to `https://wa.me/<account_phone>` when the linked account's phone is known.
- **Outputs / side effects:** `apply()` → `POST /api/messaging/whatsapp/onboarding/{id}/apply` `{mode, allowed_users}` → writes `WHATSAPP_ENABLED`/`WHATSAPP_MODE`/`WHATSAPP_ALLOWED_USERS`, enables `platforms.whatsapp.enabled` (`web_server.py:10244`), and spawns a gateway restart. Toasts: "WhatsApp saved; gateway restarting…" or "WhatsApp saved; gateway restart failed`[: <error>]`".
- **Config / env:** `WHATSAPP_ENABLED`, `WHATSAPP_MODE`, `WHATSAPP_DM_POLICY`, `WHATSAPP_ALLOWED_USERS`, `platforms.whatsapp.enabled`.
- **Edge cases / guards:** Help text switches by phase — connected/applying: "WhatsApp is linked but Hermes is not listening yet. Save and restart the gateway to finish setup."; `installing`: "Preparing the WhatsApp bridge. The QR code will appear here when it is ready."; `starting`: "Starting the WhatsApp pairing bridge. The QR code will appear here when it is ready."; otherwise: "Open WhatsApp on your phone, then go to Linked Devices and scan from there. This QR is not a browser URL." Waiting-phase footnote: "After saving, unknown DMs use Hermes pairing codes unless their number is already allowed." and, under the QR, "Scan with WhatsApp Linked Devices, not the camera app." Terminal errors (HTTP 410 + `expired|gone`, or elapsed `expires_at`) reset with "WhatsApp QR setup expired. Start a new QR setup to try again."; transient errors show "Still waiting for WhatsApp. Retrying after: `<e>`". While no QR is available the pane shows a spinner with "Waiting for WhatsApp to provide a QR code…"; once linked it shows a "Linked" badge plus the account label or "Existing WhatsApp session found".
- **Rebuild notes:** Post-link instructions are computed (`ChannelsPage.tsx:840-866`): heading "Linked as `<+phone|name|id>`" or "WhatsApp device linked"; detail "This is the WhatsApp account Hermes is now logged into." (when phone/id known) else "Hermes is logged into the WhatsApp account that scanned the QR code."; then an ordered list — (1) "Save and restart the gateway."; (2) self-chat: "After the restart, open Message Yourself on the linked account and send Hermes a message." / bot: "After the restart, start a chat from another WhatsApp account with the linked account and send Hermes a message."; (3) allowlist guidance — self-chat with no numbers typed and none saved: "Self-chat mode will allow the linked account automatically when you save."; nothing typed but numbers already saved: "Hermes will keep the saved WhatsApp allowlist."; otherwise: "If no allowed numbers were entered, Hermes replies with a pairing code. Approve it from the dashboard Pairing page." Reimplement all three branches — they are the only place the pairing/allowlist interaction is explained.

### Channels → Telegram card  `id: web-c.channels.telegram`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Telegram"; enable `Switch` with `aria-label="Enable Telegram"`, ghost button "Test".
- **What it does:** Run Hermes from Telegram DMs, groups, and topics. Catalog id `telegram`.
- **How it works:** Catalog entry built by `_build_catalog_entry("telegram", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://core.telegram.org/bots/features#botfather`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.telegram.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 2 field(s):
  - `TELEGRAM_BOT_TOKEN` — label "Telegram bot token" * (required, password input (masked), field link → `https://t.me/BotFather`). Description shown under the label: "Complete Telegram bot token created by @BotFather (numeric bot ID followed by a colon and secret)".
  - `TELEGRAM_ALLOWED_USERS` — label "Allowed Telegram user IDs (comma-separated)" (optional, plain text input, field link → `https://t.me/userinfobot`). Description shown under the label: "Optional comma-separated numeric Telegram user IDs allowed immediately; leave blank to approve new users through DM pairing".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/telegram` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Telegram saved"; "Test" → `POST /api/messaging/platforms/telegram/test` and a toast "Telegram: <message>".
- **Config / env:** `platforms.telegram.enabled`; env keys: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "Telegram is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Telegram is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Telegram is the only card WITHOUT a 'CONFIGURE' button; its manual form is reached through the panel's 'MANUAL SETUP' button and the modal is titled "Use your own Telegram bot" with a "BotFather guide" link. The panel also offers the QR quick-setup flow.
- **Rebuild notes:** Declare the platform as `{id:"telegram", name:"Telegram", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Discord card  `id: web-c.channels.discord`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Discord"; enable `Switch` with `aria-label="Enable Discord"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to Discord DMs, channels, and threads. Catalog id `discord`.
- **How it works:** Catalog entry built by `_build_catalog_entry("discord", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://discord.com/developers/applications`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.discord.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 2 field(s):
  - `DISCORD_BOT_TOKEN` — label "Discord bot token" * (required, password input (masked), field link → `https://discord.com/developers/applications`). Description shown under the label: "Discord bot token from Developer Portal".
  - `DISCORD_ALLOWED_USERS` — label "Allowed Discord user IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated Discord user IDs allowed to use the bot".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/discord` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Discord saved"; "Test" → `POST /api/messaging/platforms/discord/test` and a toast "Discord: <message>".
- **Config / env:** `platforms.discord.enabled`; env keys: `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "Discord is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Discord is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"discord", name:"Discord", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Slack card  `id: web-c.channels.slack`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Slack"; enable `Switch` with `aria-label="Enable Slack"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes from Slack via Socket Mode. Add allowed Slack member IDs so connected bots can respond. Catalog id `slack`.
- **How it works:** Catalog entry built by `_build_catalog_entry("slack", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://api.slack.com/apps`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.slack.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `SLACK_BOT_TOKEN` — label "Slack Bot Token (xoxb-...)" * (required, password input (masked), field link → `https://api.slack.com/apps`). Description shown under the label: "Slack bot token (xoxb-). Get from OAuth & Permissions after installing your app. Required scopes: chat:write, app_mentions:read, channels:history, groups:history, im:history, im:read, im:write, mpim:history, mpim:read, users:read, files:read, files:write". Help tooltip (Info icon): "In your Slack app, add the required bot scopes, install the app to the workspace, then copy OAuth & Permissions > Bot User OAuth Token.".
  - `SLACK_APP_TOKEN` — label "Slack App Token (xapp-...)" * (required, password input (masked), field link → `https://api.slack.com/apps`). Description shown under the label: "Slack app-level token (xapp-) for Socket Mode. Get from Basic Information → App-Level Tokens. Also ensure Event Subscriptions include: message.im, message.channels, message.groups, message.mpim, app_mention". Help tooltip (Info icon): "In your Slack app, enable Socket Mode, then create Basic Information > App-Level Tokens with the connections:write scope.".
  - `SLACK_ALLOWED_USERS` — label "Allowed Slack member IDs" (optional, plain text input, field link → `https://api.slack.com/apps`). Description shown under the label: "Comma-separated Slack member IDs allowed to use Hermes, e.g. U01ABC2DEF3. Without this, Slack may connect but deny messages by default.". Help tooltip (Info icon): "In Slack, open your profile, choose More or the three-dot menu, then Copy member ID. Add multiple IDs comma-separated.".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/slack` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Slack saved"; "Test" → `POST /api/messaging/platforms/slack/test` and a toast "Slack: <message>".
- **Config / env:** `platforms.slack.enabled`; env keys: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "Slack is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Slack is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Client-side validation enforces the `xoxb-` / `xapp-` token prefixes and `[UW][A-Z0-9]{2,}` member-ID shape (see web-c.channels.field-validation).
- **Rebuild notes:** Declare the platform as `{id:"slack", name:"Slack", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Mattermost card  `id: web-c.channels.mattermost`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Mattermost"; enable `Switch` with `aria-label="Enable Mattermost"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to Mattermost channels and direct messages. Catalog id `mattermost`.
- **How it works:** Catalog entry built by `_build_catalog_entry("mattermost", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://mattermost.com/deploy/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.mattermost.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `MATTERMOST_URL` — label "Mattermost server URL" * (required, plain text input, field link → `https://mattermost.com/deploy/`). Description shown under the label: "Mattermost server URL (e.g. https://mm.example.com)".
  - `MATTERMOST_TOKEN` — label "Mattermost bot token" * (required, password input (masked)). Description shown under the label: "Mattermost bot token or personal access token".
  - `MATTERMOST_ALLOWED_USERS` — label "Allowed Mattermost user IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated Mattermost user IDs allowed to use the bot".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/mattermost` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Mattermost saved"; "Test" → `POST /api/messaging/platforms/mattermost/test` and a toast "Mattermost: <message>".
- **Config / env:** `platforms.mattermost.enabled`; env keys: `MATTERMOST_URL`, `MATTERMOST_TOKEN`, `MATTERMOST_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "Mattermost is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Mattermost is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"mattermost", name:"Mattermost", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Matrix card  `id: web-c.channels.matrix`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Matrix"; enable `Switch` with `aria-label="Enable Matrix"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes in Matrix rooms and direct messages. Catalog id `matrix`.
- **How it works:** Catalog entry built by `_build_catalog_entry("matrix", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://matrix.org/ecosystem/servers/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.matrix.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 7 field(s):
  - `MATRIX_HOMESERVER` — label "Matrix homeserver URL" * (required, plain text input, field link → `https://matrix.org/ecosystem/servers/`). Description shown under the label: "Matrix homeserver URL (e.g. https://matrix.example.org)".
  - `MATRIX_ACCESS_TOKEN` — label "Matrix access token" * (required, password input (masked)). Description shown under the label: "Matrix access token (preferred over password login)".
  - `MATRIX_USER_ID` — label "Matrix user ID (@user:server)" * (required, plain text input). Description shown under the label: "Matrix user ID (e.g. @hermes:example.org)".
  - `MATRIX_ALLOWED_USERS` — label "Allowed Matrix user IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated Matrix user IDs allowed to use the bot (@user:server format)".
  - `MATRIX_DEVICE_ID` — label "Matrix device ID (stable across restarts)" (optional, advanced, plain text input). Description shown under the label: "Stable Matrix device ID for E2EE persistence across restarts (e.g. HERMES_BOT)".
  - `MATRIX_PASSWORD` — label "Matrix password" (optional, password input (masked)). Description shown under the label: "Matrix account password (alternative to MATRIX_ACCESS_TOKEN)".
  - `MATRIX_RECOVERY_KEY` — label "Matrix recovery key" (optional, advanced, password input (masked)). Description shown under the label: "Matrix recovery key for cross-signing verification after device key rotation (from Element: Settings → Security → Recovery Key)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/matrix` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Matrix saved"; "Test" → `POST /api/messaging/platforms/matrix/test` and a toast "Matrix: <message>".
- **Config / env:** `platforms.matrix.enabled`; env keys: `MATRIX_HOMESERVER`, `MATRIX_ACCESS_TOKEN`, `MATRIX_USER_ID`, `MATRIX_ALLOWED_USERS`, `MATRIX_DEVICE_ID`, `MATRIX_PASSWORD`, `MATRIX_RECOVERY_KEY`.
- **Edge cases / guards:** "Test" returns, in order: "Matrix is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Matrix is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"matrix", name:"Matrix", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → WhatsApp card  `id: web-c.channels.whatsapp`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "WhatsApp"; enable `Switch` with `aria-label="Enable WhatsApp"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes through the bundled WhatsApp bridge with QR-based auth. Catalog id `whatsapp`.
- **How it works:** Catalog entry built by `_build_catalog_entry("whatsapp", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://github.com/tulir/whatsmeow`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.whatsapp.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 4 field(s):
  - `WHATSAPP_ENABLED` — label "Enable WhatsApp? (true/false)" (optional, plain text input). Description shown under the label: "Enable the WhatsApp adapter (requires the Node.js bridge running)".
  - `WHATSAPP_MODE` — label "WhatsApp mode" (optional, advanced, plain text input). Description shown under the label: "WhatsApp bridge mode".
  - `WHATSAPP_DM_POLICY` — label "WhatsApp DM policy" (optional, advanced, plain text input). Description shown under the label: "How WhatsApp direct messages are authorized".
  - `WHATSAPP_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated WhatsApp user IDs allowed to talk to the bot".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/whatsapp` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "WhatsApp saved"; "Test" → `POST /api/messaging/platforms/whatsapp/test` and a toast "WhatsApp: <message>".
- **Config / env:** `platforms.whatsapp.enabled`; env keys: `WHATSAPP_ENABLED`, `WHATSAPP_MODE`, `WHATSAPP_DM_POLICY`, `WHATSAPP_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "WhatsApp is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "WhatsApp is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Renders the inline WhatsApp QR panel in addition to the standard Configure modal (see web-c.channels.whatsapp-panel). Server also exposes `whatsapp_setup: {mode, allowed_users_set, home_channel_set}` which pre-selects the Mode buttons.
- **Rebuild notes:** Declare the platform as `{id:"whatsapp", name:"WhatsApp", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Signal card  `id: web-c.channels.signal`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Signal"; enable `Switch` with `aria-label="Enable Signal"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect through a signal-cli REST bridge. Catalog id `signal`.
- **How it works:** Catalog entry built by `_build_catalog_entry("signal", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://github.com/bbernhard/signal-cli-rest-api`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.signal.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `SIGNAL_HTTP_URL` — label "Signal bridge URL" * (required, plain text input, field link → `https://github.com/bbernhard/signal-cli-rest-api`). Description shown under the label: "signal-cli REST API base URL, e.g. http://127.0.0.1:8080".
  - `SIGNAL_ACCOUNT` — label "Signal account" * (required, plain text input). Description shown under the label: "Signal account phone number registered with the bridge".
  - `SIGNAL_ALLOWED_USERS` — label "Allowed Signal users" (optional, plain text input). Description shown under the label: "Comma-separated Signal users allowed to use the bot".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/signal` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Signal saved"; "Test" → `POST /api/messaging/platforms/signal/test` and a toast "Signal: <message>".
- **Config / env:** `platforms.signal.enabled`; env keys: `SIGNAL_HTTP_URL`, `SIGNAL_ACCOUNT`, `SIGNAL_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "Signal is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Signal is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"signal", name:"Signal", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → BlueBubbles (iMessage) card  `id: web-c.channels.bluebubbles`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "BlueBubbles (iMessage)"; enable `Switch` with `aria-label="Enable BlueBubbles (iMessage)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes through iMessage via a BlueBubbles server. Catalog id `bluebubbles`.
- **How it works:** Catalog entry built by `_build_catalog_entry("bluebubbles", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://bluebubbles.app/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.bluebubbles.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `BLUEBUBBLES_SERVER_URL` — label "BlueBubbles server URL" * (required, plain text input, field link → `https://bluebubbles.app/`). Description shown under the label: "BlueBubbles server URL for iMessage integration (e.g. http://192.168.1.10:1234)".
  - `BLUEBUBBLES_PASSWORD` — label "BlueBubbles server password" * (required, password input (masked)). Description shown under the label: "BlueBubbles server password (from BlueBubbles Server → Settings → API)".
  - `BLUEBUBBLES_ALLOWED_USERS` — label "Allowed iMessage addresses (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated iMessage addresses (email or phone) allowed to use the bot".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/bluebubbles` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "BlueBubbles (iMessage) saved"; "Test" → `POST /api/messaging/platforms/bluebubbles/test` and a toast "BlueBubbles (iMessage): <message>".
- **Config / env:** `platforms.bluebubbles.enabled`; env keys: `BLUEBUBBLES_SERVER_URL`, `BLUEBUBBLES_PASSWORD`, `BLUEBUBBLES_ALLOWED_USERS`.
- **Edge cases / guards:** "Test" returns, in order: "BlueBubbles (iMessage) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "BlueBubbles (iMessage) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"bluebubbles", name:"BlueBubbles (iMessage)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Home Assistant card  `id: web-c.channels.homeassistant`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Home Assistant"; enable `Switch` with `aria-label="Enable Home Assistant"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Control your smart home from Hermes via Home Assistant. Catalog id `homeassistant`.
- **How it works:** Catalog entry built by `_build_catalog_entry("homeassistant", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://www.home-assistant.io/docs/authentication/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.homeassistant.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 2 field(s):
  - `HASS_URL` — label "Home Assistant URL" * (required, plain text input). Description shown under the label: "Home Assistant base URL (default: http://homeassistant.local:8123)".
  - `HASS_TOKEN` — label "Home Assistant Long-Lived Access Token" * (required, password input (masked)). Description shown under the label: "Home Assistant Long-Lived Access Token".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/homeassistant` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Home Assistant saved"; "Test" → `POST /api/messaging/platforms/homeassistant/test` and a toast "Home Assistant: <message>".
- **Config / env:** `platforms.homeassistant.enabled`; env keys: `HASS_URL`, `HASS_TOKEN`.
- **Edge cases / guards:** "Test" returns, in order: "Home Assistant is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Home Assistant is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"homeassistant", name:"Home Assistant", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Email card  `id: web-c.channels.email`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Email"; enable `Switch` with `aria-label="Enable Email"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Talk to Hermes through an IMAP/SMTP mailbox. Catalog id `email`.
- **How it works:** Catalog entry built by `_build_catalog_entry("email", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.email.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 6 field(s):
  - `EMAIL_ADDRESS` — label "Email address" * (required, plain text input). Description shown under the label: "Email account address".
  - `EMAIL_PASSWORD` — label "Email password" * (required, password input (masked)). Description shown under the label: "Email account password / app password".
  - `EMAIL_IMAP_HOST` — label "IMAP host" * (required, plain text input). Description shown under the label: "IMAP host for inbound polling (e.g. imap.gmail.com)".
  - `EMAIL_SMTP_HOST` — label "SMTP host" * (required, plain text input). Description shown under the label: "SMTP host (e.g. smtp.gmail.com)".
  - `EMAIL_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated email addresses allowed to talk to the bot".
  - `EMAIL_SMTP_PORT` — label "SMTP port" (optional, plain text input). Description shown under the label: "SMTP port (default 587)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/email` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Email saved"; "Test" → `POST /api/messaging/platforms/email/test` and a toast "Email: <message>".
- **Config / env:** `platforms.email.enabled`; env keys: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_IMAP_HOST`, `EMAIL_SMTP_HOST`, `EMAIL_ALLOWED_USERS`, `EMAIL_SMTP_PORT`.
- **Edge cases / guards:** "Test" returns, in order: "Email is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Email is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"email", name:"Email", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → SMS (Twilio) card  `id: web-c.channels.sms`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "SMS (Twilio)"; enable `Switch` with `aria-label="Enable SMS (Twilio)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Send and receive text messages via Twilio. Catalog id `sms`.
- **How it works:** Catalog entry built by `_build_catalog_entry("sms", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://www.twilio.com/console`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.sms.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `TWILIO_ACCOUNT_SID` — label "Twilio Account SID" * (required, plain text input, field link → `https://www.twilio.com/`). Description shown under the label: "Twilio Account SID".
  - `TWILIO_AUTH_TOKEN` — label "Twilio Auth Token" * (required, password input (masked)). Description shown under the label: "Twilio Auth Token".
  - `TWILIO_PHONE_NUMBER` — label "Twilio phone number" (optional, plain text input). Description shown under the label: "Twilio phone number (SMS-capable, E.164 format)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/sms` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "SMS (Twilio) saved"; "Test" → `POST /api/messaging/platforms/sms/test` and a toast "SMS (Twilio): <message>".
- **Config / env:** `platforms.sms.enabled`; env keys: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`.
- **Edge cases / guards:** "Test" returns, in order: "SMS (Twilio) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "SMS (Twilio) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"sms", name:"SMS (Twilio)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → DingTalk card  `id: web-c.channels.dingtalk`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "DingTalk"; enable `Switch` with `aria-label="Enable DingTalk"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to DingTalk groups (钉钉). Catalog id `dingtalk`.
- **How it works:** Catalog entry built by `_build_catalog_entry("dingtalk", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://open.dingtalk.com/document/orgapp/the-robot-development-process`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.dingtalk.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 4 field(s):
  - `DINGTALK_CLIENT_ID` — label "DingTalk Client ID (app key)" * (required, plain text input, field link → `https://open-dev.dingtalk.com`). Description shown under the label: "DingTalk app key (Client ID)".
  - `DINGTALK_CLIENT_SECRET` — label "DingTalk Client Secret" * (required, password input (masked), field link → `https://open-dev.dingtalk.com`). Description shown under the label: "DingTalk app secret (Client Secret)".
  - `DINGTALK_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated staff/sender IDs allowed to talk to the bot (* = any)".
  - `DINGTALK_WEBHOOK_URL` — label "DingTalk robot webhook URL (optional)" (optional, plain text input). Description shown under the label: "Static robot webhook URL for cross-platform / cron delivery".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/dingtalk` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "DingTalk saved"; "Test" → `POST /api/messaging/platforms/dingtalk/test` and a toast "DingTalk: <message>".
- **Config / env:** `platforms.dingtalk.enabled`; env keys: `DINGTALK_CLIENT_ID`, `DINGTALK_CLIENT_SECRET`, `DINGTALK_ALLOWED_USERS`, `DINGTALK_WEBHOOK_URL`.
- **Edge cases / guards:** "Test" returns, in order: "DingTalk is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "DingTalk is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"dingtalk", name:"DingTalk", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Feishu / Lark card  `id: web-c.channels.feishu`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Feishu / Lark"; enable `Switch` with `aria-label="Enable Feishu / Lark"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes inside Feishu / Lark. Catalog id `feishu`.
- **How it works:** Catalog entry built by `_build_catalog_entry("feishu", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/intro`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.feishu.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 6 field(s):
  - `FEISHU_APP_ID` — label "Feishu App ID" * (required, plain text input, field link → `https://open.feishu.cn/`). Description shown under the label: "Feishu/Lark app ID".
  - `FEISHU_APP_SECRET` — label "Feishu App Secret" * (required, password input (masked), field link → `https://open.feishu.cn/`). Description shown under the label: "Feishu/Lark app secret".
  - `FEISHU_ENCRYPT_KEY` — label "Encrypt key" (optional, password input (masked)). Description shown under the label: "Feishu / Lark encrypt key".
  - `FEISHU_VERIFICATION_TOKEN` — label "Verification token" (optional, password input (masked)). Description shown under the label: "Feishu / Lark verification token".
  - `FEISHU_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated Feishu user IDs allowed to talk to the bot".
  - `FEISHU_DOMAIN` — label "Domain (feishu/lark)" (optional, plain text input). Description shown under the label: "Domain: 'feishu' (China) or 'lark' (International)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/feishu` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Feishu / Lark saved"; "Test" → `POST /api/messaging/platforms/feishu/test` and a toast "Feishu / Lark: <message>".
- **Config / env:** `platforms.feishu.enabled`; env keys: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_ENCRYPT_KEY`, `FEISHU_VERIFICATION_TOKEN`, `FEISHU_ALLOWED_USERS`, `FEISHU_DOMAIN`.
- **Edge cases / guards:** "Test" returns, in order: "Feishu / Lark is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Feishu / Lark is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"feishu", name:"Feishu / Lark", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Google Chat card  `id: web-c.channels.google-chat`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Google Chat"; enable `Switch` with `aria-label="Enable Google Chat"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to Google Chat via Cloud Pub/Sub. Catalog id `google_chat`.
- **How it works:** Catalog entry built by `_build_catalog_entry("google_chat", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/google_chat`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.google_chat.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 7 field(s):
  - `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON` — label "Path to SA JSON (or empty for ADC)" * (required, password input (masked)). Description shown under the label: "Path to Service Account JSON key (or inline JSON). Leave empty to use Application Default Credentials on Cloud Run / GCE. Falls back to GOOGLE_APPLICATION_CREDENTIALS.".
  - `GOOGLE_CHAT_ALLOWED_USERS` — label "Allowed user emails (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated user emails allowed to interact with the bot.".
  - `GOOGLE_CHAT_HTTP_EVENTS_AUDIENCE` — label "HTTP events token audience" (optional, plain text input). Description shown under the label: "Expected audience for Google-signed HTTP event bearer tokens. Defaults to GOOGLE_CHAT_HTTP_EVENTS_URL.".
  - `GOOGLE_CHAT_HTTP_EVENTS_SERVICE_ACCOUNT_EMAIL` — label "HTTP events service account email" (optional, plain text input). Description shown under the label: "Expected Google service account email for HTTP event bearer tokens.".
  - `GOOGLE_CHAT_HTTP_EVENTS_URL` — label "HTTP events callback URL" (optional, plain text input). Description shown under the label: "Authenticated HTTP endpoint for Chat message events.".
  - `GOOGLE_CHAT_PROJECT_ID` — label "GCP project ID" (optional, plain text input, field link → `https://console.cloud.google.com/`). Description shown under the label: "GCP project ID for optional Pub/Sub inbound mode. Falls back to GOOGLE_CLOUD_PROJECT.".
  - `GOOGLE_CHAT_SUBSCRIPTION_NAME` — label "Pub/Sub subscription name" (optional, plain text input). Description shown under the label: "Optional Pub/Sub subscription path for pull-mode inbound events.".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/google_chat` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Google Chat saved"; "Test" → `POST /api/messaging/platforms/google_chat/test` and a toast "Google Chat: <message>".
- **Config / env:** `platforms.google_chat.enabled`; env keys: `GOOGLE_CHAT_SERVICE_ACCOUNT_JSON`, `GOOGLE_CHAT_ALLOWED_USERS`, `GOOGLE_CHAT_HTTP_EVENTS_AUDIENCE`, `GOOGLE_CHAT_HTTP_EVENTS_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_CHAT_HTTP_EVENTS_URL`, `GOOGLE_CHAT_PROJECT_ID`, `GOOGLE_CHAT_SUBSCRIPTION_NAME`.
- **Edge cases / guards:** "Test" returns, in order: "Google Chat is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Google Chat is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"google_chat", name:"Google Chat", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → WeCom (group bot) card  `id: web-c.channels.wecom`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "WeCom (group bot)"; enable `Switch` with `aria-label="Enable WeCom (group bot)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Send-only WeCom group bot via webhook. Catalog id `wecom`.
- **How it works:** Catalog entry built by `_build_catalog_entry("wecom", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://developer.work.weixin.qq.com/document/path/91770`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.wecom.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 2 field(s):
  - `WECOM_BOT_ID` — label "WeCom bot ID" * (required, plain text input). Description shown under the label: "WeCom Smart Robot bot ID".
  - `WECOM_SECRET` — label "WeCom secret" (optional, password input (masked)). Description shown under the label: "WeCom Smart Robot secret".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/wecom` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "WeCom (group bot) saved"; "Test" → `POST /api/messaging/platforms/wecom/test` and a toast "WeCom (group bot): <message>".
- **Config / env:** `platforms.wecom.enabled`; env keys: `WECOM_BOT_ID`, `WECOM_SECRET`.
- **Edge cases / guards:** "Test" returns, in order: "WeCom (group bot) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "WeCom (group bot) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"wecom", name:"WeCom (group bot)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → WeCom (app) card  `id: web-c.channels.wecom-callback`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "WeCom (app)"; enable `Switch` with `aria-label="Enable WeCom (app)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Two-way WeCom integration via callback app. Catalog id `wecom_callback`.
- **How it works:** Catalog entry built by `_build_catalog_entry("wecom_callback", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://developer.work.weixin.qq.com/document/path/90930`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.wecom_callback.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 5 field(s):
  - `WECOM_CALLBACK_CORP_ID` — label "WeCom callback corp ID" * (required, plain text input). Description shown under the label: "WeCom callback-mode corp ID (self-built apps)".
  - `WECOM_CALLBACK_CORP_SECRET` — label "WeCom callback corp secret" * (required, password input (masked)). Description shown under the label: "WeCom callback-mode corp secret".
  - `WECOM_CALLBACK_AGENT_ID` — label "WeCom callback agent ID" * (required, plain text input). Description shown under the label: "WeCom callback-mode agent ID".
  - `WECOM_CALLBACK_TOKEN` — label "WeCom callback token" (optional, password input (masked)). Description shown under the label: "WeCom callback verification token".
  - `WECOM_CALLBACK_ENCODING_AES_KEY` — label "WeCom callback EncodingAESKey" (optional, password input (masked)). Description shown under the label: "WeCom callback EncodingAESKey for message crypto".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/wecom_callback` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "WeCom (app) saved"; "Test" → `POST /api/messaging/platforms/wecom_callback/test` and a toast "WeCom (app): <message>".
- **Config / env:** `platforms.wecom_callback.enabled`; env keys: `WECOM_CALLBACK_CORP_ID`, `WECOM_CALLBACK_CORP_SECRET`, `WECOM_CALLBACK_AGENT_ID`, `WECOM_CALLBACK_TOKEN`, `WECOM_CALLBACK_ENCODING_AES_KEY`.
- **Edge cases / guards:** "Test" returns, in order: "WeCom (app) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "WeCom (app) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"wecom_callback", name:"WeCom (app)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Weixin / WeChat (Personal) card  `id: web-c.channels.weixin`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Weixin / WeChat (Personal)"; enable `Switch` with `aria-label="Enable Weixin / WeChat (Personal)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect a personal WeChat account through Tencent's iLink Bot API. Catalog id `weixin`.
- **How it works:** Catalog entry built by `_build_catalog_entry("weixin", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/weixin/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.weixin.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `WEIXIN_ACCOUNT_ID` — label "iLink Bot account ID" * (required, plain text input). Description shown under the label: "iLink Bot account ID obtained through QR login in hermes gateway setup".
  - `WEIXIN_TOKEN` — label "iLink Bot token" * (required, password input (masked)). Description shown under the label: "iLink Bot token obtained through QR login in hermes gateway setup".
  - `WEIXIN_BASE_URL` — label "iLink API base URL" (optional, plain text input). Description shown under the label: "iLink API base URL saved by QR login (default: https://ilinkai.weixin.qq.com)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/weixin` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Weixin / WeChat (Personal) saved"; "Test" → `POST /api/messaging/platforms/weixin/test` and a toast "Weixin / WeChat (Personal): <message>".
- **Config / env:** `platforms.weixin.enabled`; env keys: `WEIXIN_ACCOUNT_ID`, `WEIXIN_TOKEN`, `WEIXIN_BASE_URL`.
- **Edge cases / guards:** "Test" returns, in order: "Weixin / WeChat (Personal) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Weixin / WeChat (Personal) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"weixin", name:"Weixin / WeChat (Personal)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → QQ Bot card  `id: web-c.channels.qqbot`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "QQ Bot"; enable `Switch` with `aria-label="Enable QQ Bot"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to a QQ Bot from the QQ Open Platform. Catalog id `qqbot`.
- **How it works:** Catalog entry built by `_build_catalog_entry("qqbot", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://q.qq.com`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.qqbot.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 5 field(s):
  - `QQ_APP_ID` — label "QQ App ID" * (required, plain text input, field link → `https://q.qq.com`). Description shown under the label: "QQ Bot App ID from QQ Open Platform (q.qq.com)".
  - `QQ_CLIENT_SECRET` — label "QQ Client Secret" * (required, password input (masked)). Description shown under the label: "QQ Bot Client Secret from QQ Open Platform".
  - `QQ_ALLOWED_USERS` — label "QQ Allowed Users" (optional, plain text input). Description shown under the label: "Comma-separated QQ user IDs allowed to use the bot".
  - `QQ_GROUP_ALLOWED_USERS` — label "QQ Group Allowed Users" (optional, plain text input). Description shown under the label: "Comma-separated QQ group IDs allowed to interact with the bot".
  - `QQ_SANDBOX` — label "QQ Sandbox Mode" (optional, plain text input). Description shown under the label: "Enable QQ sandbox mode for development testing (true/false)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/qqbot` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "QQ Bot saved"; "Test" → `POST /api/messaging/platforms/qqbot/test` and a toast "QQ Bot: <message>".
- **Config / env:** `platforms.qqbot.enabled`; env keys: `QQ_APP_ID`, `QQ_CLIENT_SECRET`, `QQ_ALLOWED_USERS`, `QQ_GROUP_ALLOWED_USERS`, `QQ_SANDBOX`.
- **Edge cases / guards:** "Test" returns, in order: "QQ Bot is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "QQ Bot is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"qqbot", name:"QQ Bot", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Yuanbao (元宝) card  `id: web-c.channels.yuanbao`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Yuanbao (元宝)"; enable `Switch` with `aria-label="Enable Yuanbao (元宝)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to Tencent Yuanbao. Catalog id `yuanbao`.
- **How it works:** Catalog entry built by `_build_catalog_entry("yuanbao", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. No `docs_url` in the catalog, so the modal header shows no "Setup guide" link. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.yuanbao.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" — the catalog exposes **no** env fields for this platform, so the modal body contains only the description paragraph, "Cancel" and "SAVE & ENABLE".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/yuanbao` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Yuanbao (元宝) saved"; "Test" → `POST /api/messaging/platforms/yuanbao/test` and a toast "Yuanbao (元宝): <message>".
- **Config / env:** `platforms.yuanbao.enabled`; env keys: (none).
- **Edge cases / guards:** "Test" returns, in order: "Yuanbao (元宝) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Yuanbao (元宝) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). The catalog entry exposes no env vars, so the Configure modal renders only the description and the Cancel / 'SAVE & ENABLE' footer; pressing save with nothing filled toasts "Nothing to save — fill in at least one field." Configure it from config.yaml / the CLI instead.
- **Rebuild notes:** Declare the platform as `{id:"yuanbao", name:"Yuanbao (元宝)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → API server card  `id: web-c.channels.api-server`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "API server"; enable `Switch` with `aria-label="Enable API server"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Expose Hermes as an OpenAI-compatible HTTP API for tools like Open WebUI. Catalog id `api_server`.
- **How it works:** Catalog entry built by `_build_catalog_entry("api_server", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.api_server.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 5 field(s):
  - `API_SERVER_ENABLED` — label "Enable API server (true/false)" (optional, advanced, plain text input). Description shown under the label: "Enable the OpenAI-compatible API server (true/false). Allows frontends like Open WebUI, LobeChat, etc. to connect.".
  - `API_SERVER_KEY` — label "API server auth key" (optional, advanced, password input (masked)). Description shown under the label: "Bearer token for API server authentication. Required whenever the API server is enabled; server refuses to start without it.".
  - `API_SERVER_PORT` — label "API server port" (optional, advanced, plain text input). Description shown under the label: "Port for the API server (default: 8642).".
  - `API_SERVER_HOST` — label "API server host" (optional, advanced, plain text input). Description shown under the label: "Host/bind address for the API server (default: 127.0.0.1). API_SERVER_KEY is still required even on loopback binds.".
  - `API_SERVER_MODEL_NAME` — label "API server model name" (optional, advanced, plain text input). Description shown under the label: "Model name advertised on /v1/models. Defaults to the profile name (or 'hermes-agent' for the default profile). Useful for multi-user setups with OpenWebUI.".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/api_server` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "API server saved"; "Test" → `POST /api/messaging/platforms/api_server/test` and a toast "API server: <message>".
- **Config / env:** `platforms.api_server.enabled`; env keys: `API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_PORT`, `API_SERVER_HOST`, `API_SERVER_MODEL_NAME`.
- **Edge cases / guards:** "Test" returns, in order: "API server is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "API server is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). All five fields are marked `advanced`. The server refuses to start the API server without `API_SERVER_KEY`, even on a loopback bind. This platform binds its own port, so enabling it on a non-default profile while `gateway.multiplex_profiles` is on returns HTTP 409.
- **Rebuild notes:** Declare the platform as `{id:"api_server", name:"API server", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Webhooks card  `id: web-c.channels.webhook`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Webhooks"; enable `Switch` with `aria-label="Enable Webhooks"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Receive events from GitHub, GitLab, and other webhook sources. Catalog id `webhook`.
- **How it works:** Catalog entry built by `_build_catalog_entry("webhook", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.webhook.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 3 field(s):
  - `WEBHOOK_ENABLED` — label "Enable webhooks (true/false)" (optional, plain text input). Description shown under the label: "Enable the webhook platform adapter for receiving events from GitHub, GitLab, etc.".
  - `WEBHOOK_PORT` — label "Webhook port" (optional, plain text input). Description shown under the label: "Port for the webhook HTTP server (default: 8644).".
  - `WEBHOOK_SECRET` — label "Webhook secret" (optional, password input (masked)). Description shown under the label: "Global HMAC secret for webhook signature validation (overridable per route in config.yaml).".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/webhook` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Webhooks saved"; "Test" → `POST /api/messaging/platforms/webhook/test` and a toast "Webhooks: <message>".
- **Config / env:** `platforms.webhook.enabled`; env keys: `WEBHOOK_ENABLED`, `WEBHOOK_PORT`, `WEBHOOK_SECRET`.
- **Edge cases / guards:** "Test" returns, in order: "Webhooks is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Webhooks is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Binds its own listener port → subject to the multiplex 409 guard. The `/webhooks` page (see web-c.webhooks.*) is the richer surface for per-route management; this card only toggles the adapter and sets the port/global secret.
- **Rebuild notes:** Declare the platform as `{id:"webhook", name:"Webhooks", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → A2A card  `id: web-c.channels.a2a`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "A2A"; enable `Switch` with `aria-label="Enable A2A"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** No extra packages needed (stdlib only) Catalog id `a2a`.
- **How it works:** Catalog entry built by `_build_catalog_entry("a2a", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. No `docs_url` in the catalog, so the modal header shows no "Setup guide" link. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.a2a.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 5 field(s):
  - `A2A_AGENT_NAME` — label "A2A agent name" (optional, plain text input). Description shown under the label: "Name advertised on this agent's Agent Card (default: hostname-derived).".
  - `A2A_BEARER_TOKEN` — label "A2A shared bearer token (or empty for localhost-only)" (optional, password input (masked)). Description shown under the label: "Shared bearer token for inbound A2A calls (identity falls back to caller IP). With no token of any kind => bind to 127.0.0.1 only (no remote access).".
  - `A2A_HOST` — label "A2A bind host (default 127.0.0.1)" (optional, plain text input). Description shown under the label: "Inbound bind host. Defaults to 127.0.0.1; only widens to 0.0.0.0 when a bearer token is set AND you opt in here.".
  - `A2A_PEER_TOKENS` — label "A2A per-peer tokens (name:token, comma-separated; or empty)" (optional, password input (masked)). Description shown under the label: "Per-peer bearer tokens ('alice:tok1,bob:tok2'). Each remote agent gets its own credential; the matched name is the authenticated identity used for rate limiting, trust, and audit.".
  - `A2A_PORT` — label "A2A port (default 9900)" (optional, plain text input). Description shown under the label: "Inbound A2A server port (default 9900).".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/a2a` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "A2A saved"; "Test" → `POST /api/messaging/platforms/a2a/test` and a toast "A2A: <message>".
- **Config / env:** `platforms.a2a.enabled`; env keys: `A2A_AGENT_NAME`, `A2A_BEARER_TOKEN`, `A2A_HOST`, `A2A_PEER_TOKENS`, `A2A_PORT`.
- **Edge cases / guards:** "Test" returns, in order: "A2A is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "A2A is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Binds an inbound port (default 9900); subject to the multiplex 409 guard. Security ladder is encoded in the field descriptions: no token of any kind ⇒ 127.0.0.1-only bind.
- **Rebuild notes:** Declare the platform as `{id:"a2a", name:"A2A", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Buzz card  `id: web-c.channels.buzz`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Buzz"; enable `Switch` with `aria-label="Enable Buzz"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Requires the buzz CLI binary (https://github.com/block/buzz) on PATH or at BUZZ_CLI_PATH Catalog id `buzz`.
- **How it works:** Catalog entry built by `_build_catalog_entry("buzz", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. No `docs_url` in the catalog, so the modal header shows no "Setup guide" link. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.buzz.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 10 field(s):
  - `BUZZ_RELAY_URL` — label "Buzz relay URL" * (required, plain text input). Description shown under the label: "Base URL of the Buzz community relay (e.g. https://mycommunity.communities.buzz.xyz)".
  - `BUZZ_PRIVATE_KEY` — label "Nostr private key (nsec or hex)" * (required, password input (masked)). Description shown under the label: "Nostr private key for the agent's Buzz identity (nsec or hex) — the only Buzz secret".
  - `BUZZ_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated npubs or hex pubkeys allowed to talk to the agent".
  - `BUZZ_AUTH_TAG` — label "NIP-OA auth tag JSON (or empty)" (optional, plain text input). Description shown under the label: "Optional NIP-OA owner-attestation auth tag JSON for NIP-42 WebSocket auth".
  - `BUZZ_CHANNELS` — label "Channel UUIDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated channel UUIDs to watch (default: all joined channels)".
  - `BUZZ_CLI_PATH` — label "buzz CLI path (or empty)" (optional, plain text input). Description shown under the label: "Path to the buzz CLI binary (default: 'buzz' on PATH, then ~/bin/buzz)".
  - `BUZZ_CREDENTIALS_FILE` — label "Credentials file path (or empty)" (optional, plain text input). Description shown under the label: "JSON credentials file holding the nsec (fallback when BUZZ_PRIVATE_KEY is unset)".
  - `BUZZ_POLL_INTERVAL` — label "Poll interval seconds" (optional, plain text input). Description shown under the label: "Seconds between inbound poll sweeps (default: 4)".
  - `BUZZ_REPLY_IN_THREAD` — label "Reply in thread? (true/false)" (optional, plain text input). Description shown under the label: "Thread replies under the triggering message (true/false, default: true); false posts flat to the channel timeline".
  - `BUZZ_TRANSPORT` — label "Transport (auto/websocket/poll)" (optional, plain text input). Description shown under the label: "Inbound transport: auto (WebSocket w/ poll fallback, default), websocket, or poll".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/buzz` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Buzz saved"; "Test" → `POST /api/messaging/platforms/buzz/test` and a toast "Buzz: <message>".
- **Config / env:** `platforms.buzz.enabled`; env keys: `BUZZ_RELAY_URL`, `BUZZ_PRIVATE_KEY`, `BUZZ_ALLOWED_USERS`, `BUZZ_AUTH_TAG`, `BUZZ_CHANNELS`, `BUZZ_CLI_PATH`, `BUZZ_CREDENTIALS_FILE`, `BUZZ_POLL_INTERVAL`, `BUZZ_REPLY_IN_THREAD`, `BUZZ_TRANSPORT`.
- **Edge cases / guards:** "Test" returns, in order: "Buzz is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Buzz is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"buzz", name:"Buzz", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → iMessage via Photon card  `id: web-c.channels.photon`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "iMessage via Photon"; enable `Switch` with `aria-label="Enable iMessage via Photon"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes through iMessage via Photon's managed Spectrum platform. Catalog id `photon`.
- **How it works:** Catalog entry built by `_build_catalog_entry("photon", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/photon`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.photon.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 13 field(s):
  - `PHOTON_PROJECT_ID` — label "Photon Spectrum project id" * (required, plain text input, field link → `https://app.photon.codes/`). Description shown under the label: "Spectrum project id (the project's spectrumProjectId; set by `hermes photon setup`)".
  - `PHOTON_PROJECT_SECRET` — label "Photon project secret" * (required, password input (masked), field link → `https://app.photon.codes/`). Description shown under the label: "Project secret paired with the Spectrum project id (set by `hermes photon setup`)".
  - `PHOTON_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated E.164 phone numbers allowed to talk to the bot".
  - `PHOTON_DASHBOARD_HOST` — label "Dashboard host" (optional, plain text input). Description shown under the label: "Photon Dashboard API host (default https://app.photon.codes)".
  - `PHOTON_MARKDOWN` — label "Render replies as markdown? (true/false)" (optional, plain text input). Description shown under the label: "Send agent replies as markdown — iMessage renders it natively, other Spectrum platforms degrade to plain text (true/false, default true)".
  - `PHOTON_MENTION_PATTERNS` — label "Group mention patterns" (optional, plain text input). Description shown under the label: "Mention wake-word regexes for group chats (JSON list or comma/newline-separated; defaults to Hermes wake words)".
  - `PHOTON_NODE_BIN` — label "Node executable path" (optional, plain text input). Description shown under the label: "Path to the node binary (default: shutil.which('node'))".
  - `PHOTON_REACTIONS` — label "Enable reaction tapbacks? (true/false)" (optional, plain text input). Description shown under the label: "Tapback 👀/👍/👎 on messages as processing status and route tapbacks on bot messages to the agent (true/false, default false)".
  - `PHOTON_READ_RECEIPTS` — label "Send read receipts? (true/false)" (optional, plain text input). Description shown under the label: "Mark inbound iMessages read after forwarding to Hermes (true/false, default true)".
  - `PHOTON_SIDECAR_AUTOSTART` — label "Auto-start the sidecar?" (optional, plain text input). Description shown under the label: "Spawn the Node sidecar on connect (true/false, default true)".
  - `PHOTON_SIDECAR_PORT` — label "Sidecar control port" (optional, plain text input). Description shown under the label: "Loopback port for the Node sidecar control + inbound channel (default 8789)".
  - `PHOTON_SPECTRUM_HOST` — label "Spectrum API host" (optional, plain text input). Description shown under the label: "Photon Spectrum API host (default https://spectrum.photon.codes)".
  - `PHOTON_TELEMETRY` — label "Enable Spectrum telemetry? (true/false)" (optional, plain text input). Description shown under the label: "Enable Spectrum SDK telemetry in the sidecar (true/false, default false; toggle with `hermes photon telemetry on|off`)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/photon` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "iMessage via Photon saved"; "Test" → `POST /api/messaging/platforms/photon/test` and a toast "iMessage via Photon: <message>".
- **Config / env:** `platforms.photon.enabled`; env keys: `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET`, `PHOTON_ALLOWED_USERS`, `PHOTON_DASHBOARD_HOST`, `PHOTON_MARKDOWN`, `PHOTON_MENTION_PATTERNS`, `PHOTON_NODE_BIN`, `PHOTON_REACTIONS`, `PHOTON_READ_RECEIPTS`, `PHOTON_SIDECAR_AUTOSTART`, `PHOTON_SIDECAR_PORT`, `PHOTON_SPECTRUM_HOST`, `PHOTON_TELEMETRY`.
- **Edge cases / guards:** "Test" returns, in order: "iMessage via Photon is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "iMessage via Photon is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"photon", name:"iMessage via Photon", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → IRC card  `id: web-c.channels.irc`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "IRC"; enable `Switch` with `aria-label="Enable IRC"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Relay messages between an IRC channel (or DMs) and Hermes. Catalog id `irc`.
- **How it works:** Catalog entry built by `_build_catalog_entry("irc", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/irc`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.irc.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 8 field(s):
  - `IRC_SERVER` — label "IRC server" * (required, plain text input). Description shown under the label: "IRC server hostname (e.g. irc.libera.chat)".
  - `IRC_CHANNEL` — label "IRC channel" * (required, plain text input). Description shown under the label: "IRC channel to join (e.g. #hermes)".
  - `IRC_NICKNAME` — label "IRC nickname" * (required, plain text input). Description shown under the label: "Bot nickname on IRC (default: hermes-bot)".
  - `IRC_ALLOWED_USERS` — label "Allowed nicks (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated IRC nicks allowed to talk to the bot".
  - `IRC_NICKSERV_PASSWORD` — label "NickServ password" (optional, advanced, password input (masked)). Description shown under the label: "NickServ password for nick identification".
  - `IRC_PORT` — label "IRC port" (optional, plain text input). Description shown under the label: "IRC server port (default: 6697 with TLS, 6667 without)".
  - `IRC_SERVER_PASSWORD` — label "IRC server password" (optional, advanced, password input (masked)). Description shown under the label: "IRC server password (if required)".
  - `IRC_USE_TLS` — label "Use TLS? (true/false)" (optional, plain text input). Description shown under the label: "Use TLS for the IRC connection (1/true/yes to enable, default: true on port 6697)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/irc` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "IRC saved"; "Test" → `POST /api/messaging/platforms/irc/test` and a toast "IRC: <message>".
- **Config / env:** `platforms.irc.enabled`; env keys: `IRC_SERVER`, `IRC_CHANNEL`, `IRC_NICKNAME`, `IRC_ALLOWED_USERS`, `IRC_NICKSERV_PASSWORD`, `IRC_PORT`, `IRC_SERVER_PASSWORD`, `IRC_USE_TLS`.
- **Edge cases / guards:** "Test" returns, in order: "IRC is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "IRC is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"irc", name:"IRC", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → LINE card  `id: web-c.channels.line`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "LINE"; enable `Switch` with `aria-label="Enable LINE"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes from LINE via the LINE Messaging API webhook. Catalog id `line`.
- **How it works:** Catalog entry built by `_build_catalog_entry("line", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/line`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.line.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 9 field(s):
  - `LINE_CHANNEL_ACCESS_TOKEN` — label "LINE channel access token" * (required, password input (masked), field link → `https://developers.line.biz/console/`). Description shown under the label: "LINE channel long-lived access token (LINE Developers Console > Messaging API > Channel access token)".
  - `LINE_CHANNEL_SECRET` — label "LINE channel secret" * (required, password input (masked), field link → `https://developers.line.biz/console/`). Description shown under the label: "LINE channel secret (used for HMAC-SHA256 webhook signature verification)".
  - `LINE_ALLOWED_GROUPS` — label "Allowed group IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated LINE group IDs the bot will respond in (C-prefixed)".
  - `LINE_ALLOWED_ROOMS` — label "Allowed room IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated LINE room IDs the bot will respond in (R-prefixed)".
  - `LINE_ALLOWED_USERS` — label "Allowed user IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated LINE user IDs allowed to DM the bot (U-prefixed)".
  - `LINE_HOST` — label "Webhook host" (optional, plain text input). Description shown under the label: "Webhook bind host (default: unset → dual-stack, all interfaces IPv4+IPv6)".
  - `LINE_PORT` — label "Webhook port" (optional, plain text input). Description shown under the label: "Webhook listen port (default: 8646)".
  - `LINE_PUBLIC_URL` — label "Public HTTPS base URL" (optional, plain text input). Description shown under the label: "Public HTTPS base URL for serving images/audio/video to LINE (e.g. https://my-tunnel.example.com). Required for media sending when the bind address is not directly reachable.".
  - `LINE_SLOW_RESPONSE_THRESHOLD` — label "Slow response threshold (seconds)" (optional, plain text input). Description shown under the label: "Seconds before the slow-LLM postback button fires (default: 45; set 0 to disable and always Push-fallback)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/line` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "LINE saved"; "Test" → `POST /api/messaging/platforms/line/test` and a toast "LINE: <message>".
- **Config / env:** `platforms.line.enabled`; env keys: `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `LINE_ALLOWED_GROUPS`, `LINE_ALLOWED_ROOMS`, `LINE_ALLOWED_USERS`, `LINE_HOST`, `LINE_PORT`, `LINE_PUBLIC_URL`, `LINE_SLOW_RESPONSE_THRESHOLD`.
- **Edge cases / guards:** "Test" returns, in order: "LINE is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "LINE is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Binds a webhook port (default 8646); subject to the multiplex 409 guard.
- **Rebuild notes:** Declare the platform as `{id:"line", name:"LINE", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Microsoft Graph Webhook card  `id: web-c.channels.msgraph-webhook`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Microsoft Graph Webhook"; enable `Switch` with `aria-label="Enable Microsoft Graph Webhook"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Receive Microsoft Graph change notifications (Teams meetings, Outlook, …). Catalog id `msgraph_webhook`.
- **How it works:** Catalog entry built by `_build_catalog_entry("msgraph_webhook", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/msgraph-webhook`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.msgraph_webhook.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" — the catalog exposes **no** env fields for this platform, so the modal body contains only the description paragraph, "Cancel" and "SAVE & ENABLE".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/msgraph_webhook` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Microsoft Graph Webhook saved"; "Test" → `POST /api/messaging/platforms/msgraph_webhook/test` and a toast "Microsoft Graph Webhook: <message>".
- **Config / env:** `platforms.msgraph_webhook.enabled`; env keys: (none).
- **Edge cases / guards:** "Test" returns, in order: "Microsoft Graph Webhook is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Microsoft Graph Webhook is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). No env vars in the catalog → the Configure modal has no fields (same empty-modal caveat as Yuanbao).
- **Rebuild notes:** Declare the platform as `{id:"msgraph_webhook", name:"Microsoft Graph Webhook", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Microsoft Teams card  `id: web-c.channels.teams`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Microsoft Teams"; enable `Switch` with `aria-label="Enable Microsoft Teams"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Connect Hermes to Microsoft Teams chats via the Bot Framework. Catalog id `teams`.
- **How it works:** Catalog entry built by `_build_catalog_entry("teams", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/teams`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.teams.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 6 field(s):
  - `TEAMS_CLIENT_ID` — label "Teams / Azure AD client ID" * (required, plain text input, field link → `https://portal.azure.com/`). Description shown under the label: "Azure AD application (Bot Framework) client ID".
  - `TEAMS_CLIENT_SECRET` — label "Teams / Azure AD client secret" * (required, password input (masked), field link → `https://portal.azure.com/`). Description shown under the label: "Azure AD application client secret".
  - `TEAMS_TENANT_ID` — label "Teams / Azure AD tenant ID" * (required, plain text input). Description shown under the label: "Azure AD tenant ID hosting the bot application".
  - `TEAMS_ALLOWED_USERS` — label "Allowed users (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated Teams user IDs / UPNs allowed to talk to the bot".
  - `TEAMS_HOST` — label "Webhook host" (optional, plain text input). Description shown under the label: "Webhook bind host (default: unset → dual-stack, all interfaces IPv4+IPv6)".
  - `TEAMS_PORT` — label "Webhook port" (optional, plain text input). Description shown under the label: "Webhook listen port (Bot Framework default: 3978)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/teams` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Microsoft Teams saved"; "Test" → `POST /api/messaging/platforms/teams/test` and a toast "Microsoft Teams: <message>".
- **Config / env:** `platforms.teams.enabled`; env keys: `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, `TEAMS_TENANT_ID`, `TEAMS_ALLOWED_USERS`, `TEAMS_HOST`, `TEAMS_PORT`.
- **Edge cases / guards:** "Test" returns, in order: "Microsoft Teams is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Microsoft Teams is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Binds a webhook port (Bot Framework default 3978); subject to the multiplex 409 guard.
- **Rebuild notes:** Declare the platform as `{id:"teams", name:"Microsoft Teams", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → ntfy card  `id: web-c.channels.ntfy`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "ntfy"; enable `Switch` with `aria-label="Enable ntfy"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Chat with Hermes over ntfy push topics (ntfy.sh or self-hosted). Catalog id `ntfy`.
- **How it works:** Catalog entry built by `_build_catalog_entry("ntfy", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/ntfy`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.ntfy.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 6 field(s):
  - `NTFY_TOPIC` — label "ntfy subscribe topic" * (required, plain text input). Description shown under the label: "Topic name to subscribe to (e.g. hermes-in)".
  - `NTFY_ALLOWED_USERS` — label "Allowed topic names (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated topic names allowed (allowlist)".
  - `NTFY_MARKDOWN` — label "Enable markdown formatting? (true/false)" (optional, plain text input). Description shown under the label: "Send replies with X-Markdown: true header (true/false, default: false)".
  - `NTFY_PUBLISH_TOPIC` — label "ntfy publish topic (or empty)" (optional, plain text input). Description shown under the label: "Topic to publish replies to (defaults to NTFY_TOPIC)".
  - `NTFY_SERVER_URL` — label "ntfy server URL" (optional, plain text input). Description shown under the label: "ntfy server URL (default: https://ntfy.sh)".
  - `NTFY_TOKEN` — label "ntfy auth token (or empty)" (optional, password input (masked)). Description shown under the label: "Bearer token or 'user:pass' for Basic auth (optional)".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/ntfy` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "ntfy saved"; "Test" → `POST /api/messaging/platforms/ntfy/test` and a toast "ntfy: <message>".
- **Config / env:** `platforms.ntfy.enabled`; env keys: `NTFY_TOPIC`, `NTFY_ALLOWED_USERS`, `NTFY_MARKDOWN`, `NTFY_PUBLISH_TOPIC`, `NTFY_SERVER_URL`, `NTFY_TOKEN`.
- **Edge cases / guards:** "Test" returns, in order: "ntfy is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "ntfy is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"ntfy", name:"ntfy", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Raft card  `id: web-c.channels.raft`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Raft"; enable `Switch` with `aria-label="Enable Raft"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Join a Raft workspace as an external agent. Catalog id `raft`.
- **How it works:** Catalog entry built by `_build_catalog_entry("raft", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/raft`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.raft.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 1 field(s):
  - `RAFT_PROFILE` — label "Raft agent profile" * (required, plain text input). Description shown under the label: "Raft agent profile slug — auto-enables the adapter when set".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/raft` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Raft saved"; "Test" → `POST /api/messaging/platforms/raft/test` and a toast "Raft: <message>".
- **Config / env:** `platforms.raft.enabled`; env keys: `RAFT_PROFILE`.
- **Edge cases / guards:** "Test" returns, in order: "Raft is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Raft is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"raft", name:"Raft", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → Relay (experimental) card  `id: web-c.channels.relay`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "Relay (experimental)"; enable `Switch` with `aria-label="Enable Relay (experimental)"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Generic relay adapter fronted by the Hermes Relay connector. Catalog id `relay`.
- **How it works:** Catalog entry built by `_build_catalog_entry("relay", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. No `docs_url` in the catalog, so the modal header shows no "Setup guide" link. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.relay.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" — the catalog exposes **no** env fields for this platform, so the modal body contains only the description paragraph, "Cancel" and "SAVE & ENABLE".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/relay` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "Relay (experimental) saved"; "Test" → `POST /api/messaging/platforms/relay/test` and a toast "Relay (experimental): <message>".
- **Config / env:** `platforms.relay.enabled`; env keys: (none).
- **Edge cases / guards:** "Test" returns, in order: "Relay (experimental) is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "Relay (experimental) is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Marked experimental and exposes no env vars → empty Configure modal.
- **Rebuild notes:** Declare the platform as `{id:"relay", name:"Relay (experimental)", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → SimpleX Chat card  `id: web-c.channels.simplex`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "SimpleX Chat"; enable `Switch` with `aria-label="Enable SimpleX Chat"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Talk to Hermes over SimpleX Chat via a local simplex-chat daemon. Catalog id `simplex`.
- **How it works:** Catalog entry built by `_build_catalog_entry("simplex", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/simplex`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.simplex.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" → modal with 4 field(s):
  - `SIMPLEX_WS_URL` — label "SimpleX daemon WebSocket URL" * (required, plain text input). Description shown under the label: "WebSocket URL of the simplex-chat daemon (e.g. ws://127.0.0.1:5225)".
  - `SIMPLEX_ALLOWED_USERS` — label "Allowed contact IDs (comma-separated)" (optional, plain text input). Description shown under the label: "Comma-separated SimpleX contact IDs allowed to talk to the bot".
  - `SIMPLEX_AUTO_ACCEPT` — label "Auto-accept contact requests? (true/false)" (optional, plain text input). Description shown under the label: "Auto-accept incoming contact requests (default: true)".
  - `SIMPLEX_GROUP_ALLOWED` — label "Allowed group IDs (comma-separated, or '*' for any)" (optional, plain text input). Description shown under the label: "Comma-separated SimpleX group IDs the bot should participate in, or '*' to allow any group. Omit to ignore group messages entirely (safer default — a bot in a group otherwise processes every member's traffic).".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/simplex` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "SimpleX Chat saved"; "Test" → `POST /api/messaging/platforms/simplex/test` and a toast "SimpleX Chat: <message>".
- **Config / env:** `platforms.simplex.enabled`; env keys: `SIMPLEX_WS_URL`, `SIMPLEX_ALLOWED_USERS`, `SIMPLEX_AUTO_ACCEPT`, `SIMPLEX_GROUP_ALLOWED`.
- **Edge cases / guards:** "Test" returns, in order: "SimpleX Chat is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "SimpleX Chat is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`).
- **Rebuild notes:** Declare the platform as `{id:"simplex", name:"SimpleX Chat", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

### Channels → WhatsApp Cloud API card  `id: web-c.channels.whatsapp-cloud`
- **Surface:** Web dashboard
- **Where:** `/channels` → platform card headed "WhatsApp Cloud API"; enable `Switch` with `aria-label="Enable WhatsApp Cloud API"`, ghost button "Test", primary button "CONFIGURE".
- **What it does:** Use Hermes via Meta's hosted WhatsApp Cloud API (no local bridge). Catalog id `whatsapp_cloud`.
- **How it works:** Catalog entry built by `_build_catalog_entry("whatsapp_cloud", …)` inside `_messaging_platform_catalog()` (`hermes_cli/web_server.py:9396`); rendered by the generic card loop at `web/src/pages/ChannelsPage.tsx:515-620`. Docs link in the modal header points to `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp-cloud`. Credentials are read from / written to the profile's `.env`; the enable flag lives at `platforms.whatsapp_cloud.enabled` in `config.yaml`.
- **Inputs / options:** Enable switch, "Test", "CONFIGURE" — the catalog exposes **no** env fields for this platform, so the modal body contains only the description paragraph, "Cancel" and "SAVE & ENABLE".
- **Outputs / side effects:** Switch → `PUT /api/messaging/platforms/whatsapp_cloud` `{"enabled": true|false}`; modal save → same route with `{"env": {…}, "enabled": true}` then toast "WhatsApp Cloud API saved"; "Test" → `POST /api/messaging/platforms/whatsapp_cloud/test` and a toast "WhatsApp Cloud API: <message>".
- **Config / env:** `platforms.whatsapp_cloud.enabled`; env keys: (none).
- **Edge cases / guards:** "Test" returns, in order: "WhatsApp Cloud API is disabled. Enable it, then restart the gateway." → "Missing required setup: <keys>" / "Platform setup is incomplete." → "Gateway is not running. Restart the gateway to connect this platform." → "WhatsApp Cloud API is connected." → the adapter's `error_message` → "Setup looks complete, but the gateway has not reported a connection yet. Restart the gateway." (`web_server.py:10803-10865`). Exposes no env vars through the catalog in this build → empty Configure modal; configure it via config.yaml / environment instead.
- **Rebuild notes:** Declare the platform as `{id:"whatsapp_cloud", name:"WhatsApp Cloud API", description, docs_url, required_env:[…], env_vars:[…]}` and let one generic card + modal render every platform; per-platform code should exist only where a bespoke onboarding flow does (Telegram, WhatsApp). A better version would validate credentials at save time (live API ping) instead of deferring the truth to a gateway restart.

---

## 2. Webhooks page (`/webhooks`)

### Webhooks page  `id: web-c.webhooks.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `WEBHOOKS` (href `/webhooks`); page `<h1>` "Webhooks".
- **What it does:** Enables the gateway's inbound webhook receiver and manages the list of webhook subscriptions (each with its own URL and HMAC secret) that turn incoming HTTP events into agent runs or direct channel deliveries.
- **How it works:** `web/src/pages/WebhooksPage.tsx:59` (`WebhooksPage`). `loadWebhooks()` (`:93-99`) calls `api.getWebhooks()` → `GET /api/webhooks`, returning `{enabled: bool, base_url: string, subscriptions: WebhookRoute[]}` (live sample: `{"enabled": false, "base_url": "http://localhost:8644", "subscriptions": []}`). A `WebhookRoute` is `{name, description, events[], deliver, deliver_only, prompt, skills[], created_at, url, secret_set, enabled}` (`web/src/lib/api.ts:1615-1627`). Subscriptions are persisted in `config.yaml` under the webhook platform's routes; the receiver hot-reloads them.
- **Inputs / options:** Page-header button "New subscription"; the "Enable webhooks" card; per-subscription "Disable"/"Enable" and delete buttons; the create modal (see below).
- **Outputs / side effects:** Creates/deletes/toggles webhook routes; can trigger a gateway restart.
- **Config / env:** `WEBHOOK_ENABLED`, `WEBHOOK_PORT` (default 8644), `WEBHOOK_SECRET`; `platforms.webhook.enabled`; per-route entries in `config.yaml`.
- **Edge cases / guards:** Whole page is a `Spinner` while loading (`:274-280`). A load failure toasts "Failed to load webhooks".
- **Rebuild notes:** Two-level model — a platform-level on/off that needs a gateway restart, and route-level CRUD that hot-reloads. Keep them visually distinct or users restart for nothing.

### Webhooks → "New subscription" (page-header button)  `id: web-c.webhooks.new-button`
- **Surface:** Web dashboard
- **Where:** `/webhooks` → page header, right side. Label "New subscription" rendered uppercase ("NEW SUBSCRIPTION"), `Plus` icon.
- **What it does:** Opens the create-subscription modal.
- **How it works:** `WebhooksPage.tsx:254-272`; registered with `usePageHeader().setEnd`. Clicking clears `created` and sets `createModalOpen`.
- **Inputs / options:** Click only.
- **Outputs / side effects:** Opens the modal.
- **Config / env:** n/a
- **Edge cases / guards:** `disabled={!enabled || enabling}` — you cannot create a subscription until the webhook platform itself is enabled.
- **Rebuild notes:** Allow creating routes while the receiver is off (they persist anyway) and simply warn — the current gating forces an unnecessary restart-first ordering.

### Webhooks → "Webhook receiver disabled" card  `id: web-c.webhooks.enable-card`
- **Surface:** Web dashboard
- **Where:** `/webhooks` → top card, shown when `data.enabled === false`. Title "Webhook receiver disabled"; body "Webhooks are their own gateway platform. Enable them here to accept incoming HTTP events; chat channels are only needed when a subscription delivers to Telegram, Discord, Slack, or another channel."; button "Enable webhooks" (uppercase; "Enabling…" while busy).
- **What it does:** Turns on the webhook gateway platform and restarts the gateway in one click.
- **How it works:** `WebhooksPage.tsx:462-488` + `handleEnableWebhooks()` (`:151-175`) → `POST /api/webhooks/enable`. Response `WebhookEnableResponse` = `{ok, platform:"webhook", enabled:true, needs_restart, restart_started?, restart_action?, restart_pid?, restart_error?}`.
- **Inputs / options:** Single button; `Webhook` icon (`Spinner` while enabling).
- **Outputs / side effects:** Sets `platforms.webhook.enabled = true` (and `WEBHOOK_ENABLED`), spawns `hermes gateway restart`. On `restart_started` → banner + toast "Webhooks enabled; gateway restarting…", reload after 4000 ms, `watchRestartOutcome()` starts. Otherwise → banner "Gateway restart failed`[: <restart_error>]`" and toast "Webhooks enabled; gateway restart failed`[…]`".
- **Config / env:** `platforms.webhook.enabled`, `WEBHOOK_ENABLED`.
- **Edge cases / guards:** Failure of the enable call itself toasts "Failed to enable webhooks: `<e>`".
- **Rebuild notes:** Same restart-watch loop as Channels — factor it into one shared hook rather than three copies (`ChannelsPage` has two, `WebhooksPage` one).

### Webhooks → restart banners  `id: web-c.webhooks.restart-banners`
- **Surface:** Web dashboard
- **Where:** `/webhooks`, below the enable card. Two mutually exclusive banners.
- **What it does:** Reports an in-flight restart, or that a restart is still required/failed.
- **How it works:** `WebhooksPage.tsx:490-520`. Info banner (`RotateCw` icon) renders `restartMessage` — set to "Gateway restarting…" by `handleRestart()` or "Webhooks enabled; gateway restarting…" by `handleEnableWebhooks()` — only while `!restartNeeded`. Warning banner (`AlertTriangle`) renders `restartError` or the default "Webhooks are enabled, but the gateway still needs a restart before the receiver can come online." with a "Restart gateway" button ("Restarting…" while busy).
- **Inputs / options:** "Restart gateway" button → `handleRestart()` (`:132-149`) → `POST /api/gateway/restart`.
- **Outputs / side effects:** Restarts the gateway; toast "Gateway restarting…" / "Failed to restart: `<e>`".
- **Config / env:** n/a
- **Edge cases / guards:** `watchRestartOutcome()` (`:105-130`) polls `GET /api/actions/gateway-restart/status?lines=5` 20× at 1.5 s; a non-zero, non-null exit code sets `restartError` to "Gateway restart failed with exit `<code>`." and toasts "Gateway restart failed (exit `<code>`) — restart manually"; a clean exit clears both banners. Fetch errors during the restart window are swallowed ("The dashboard may briefly lose its connection while the gateway restarts").
- **Rebuild notes:** Distinguish "restart in progress" from "restart needed" — collapsing them (as many dashboards do) hides failures.

### Webhooks → "New subscription" modal  `id: web-c.webhooks.create-modal`
- **Surface:** Web dashboard
- **Where:** `/webhooks` → header button → modal titled "New subscription".
- **What it does:** Creates a webhook route, then shows its URL and one-time HMAC secret.
- **How it works:** `WebhooksPage.tsx:302-460`. `handleCreate()` (`:186-214`) POSTs `/api/webhooks` with `{name, description?, events?, deliver, deliver_only, prompt?}` (`WebhookCreate` also supports `skills[]` and `deliver_chat_id`, which this modal does not expose). The response is `WebhookRoute & {secret}`; the modal switches to the "created" view. `useModalBehavior` supplies Escape-to-close/focus trap; backdrop click closes; close button `aria-label="Close"`.
- **Inputs / options (form view, top to bottom):**
  - `Name` — `<Input id="webhook-name" autoFocus placeholder="e.g. github-push">`.
  - `Description` — `<Input id="webhook-description" placeholder="What this webhook does (optional)">`.
  - `Events` — `<Input id="webhook-events" placeholder="comma-separated, leave empty for all">`; split on `,`, trimmed, empties dropped.
  - `Deliver to` — `<Select id="webhook-deliver">` with exactly six options: `log` → "Log" (default), `telegram` → "Telegram", `discord` → "Discord", `slack` → "Slack", `email` → "Email", `github_comment` → "GitHub comment".
  - `Deliver only` — `<input id="webhook-deliver-only" type="checkbox">` with inline label "Skip the agent, deliver payload directly".
  - `Prompt` — `<textarea id="webhook-prompt" placeholder="Instructions for the agent when this webhook fires (optional)">`.
  - Submit button "Create" (uppercase; "Creating…" while in flight).
- **Inputs / options (created view):** Paragraph "Subscription created. Copy the secret now — it is only shown once."; field `Webhook URL` with the URL in `font-mono` and a copy icon button (`title`/`aria-label` "Copy", flips to a `Check` icon for 1500 ms); field `Secret (shown once)` in a warning-tinted box with its own copy button; button "Done" (uppercase) which closes the modal.
- **Outputs / side effects:** Creates the route in config, toasts "Created ✓", resets the form, reloads the list. The secret is returned exactly once.
- **Config / env:** Route entries under the webhook platform in `config.yaml`; the route's own secret (falls back to `WEBHOOK_SECRET` when unset).
- **Edge cases / guards:** Empty/blank name → toast "Name required" and no request. Create failure → toast "Failed to create: `<e>`". Copy silently no-ops when the clipboard write fails (`copyTextToClipboard` returns false).
- **Rebuild notes:** Show-once secrets need an explicit "I copied it" affordance; here "Done" is the only exit and the secret is unrecoverable afterwards (regenerate by recreating the route).

### Webhooks → "Subscriptions (n)" list  `id: web-c.webhooks.list`
- **Surface:** Web dashboard
- **Where:** `/webhooks` → section heading "Subscriptions ({count})" — rendered live as "Subscriptions (0)" on a fresh install, "Subscriptions (1)", "Subscriptions (2)", … — with a `Webhook` icon; helper line "Subscription changes hot-reload once the webhook receiver is running. Disabled subscriptions reject incoming events."; empty state "No webhook subscriptions yet."
- **What it does:** Lists every webhook route with its delivery target, event filter, URL and per-route controls.
- **How it works:** `WebhooksPage.tsx:522-609`. Each row renders name, badges, description, event badges, the URL with a copy button, and the action buttons. Disabled rows get `opacity-60`.
- **Inputs / options:** Per row — badge showing `sub.deliver` (outline); badge "deliver only" (secondary) when `deliver_only`; badge "disabled" (warning) when `!enabled`; event badges, or a single badge "(all)" when `events` is empty; URL copy button (`title`/`aria-label` "Copy"); ghost button "Disable" (when enabled) / "Enable" (when disabled), uppercase, disabled while that row is toggling; destructive icon button `title`/`aria-label` "Delete" (`Trash2`).
- **Outputs / side effects:** Toggle → `PUT /api/webhooks/{name}/enabled` `{enabled}` → toast `Enabled: "<name>"` or `Disabled: "<name>"`, then reload. Delete → confirm dialog, then `DELETE /api/webhooks/{name}` → toast `Deleted: "<name>"`, then reload.
- **Config / env:** n/a
- **Edge cases / guards:** Delete goes through `DeleteConfirmDialog` titled "Delete webhook" with description `"<name>" — this will permanently remove this webhook subscription.` (or the generic "This will permanently remove this webhook subscription." when the name is missing). Toggle/delete errors toast "Error: `<e>`".
- **Rebuild notes:** `secret_set`, `skills[]`, `created_at` and `prompt` are returned by the API but never rendered — a better version would show last-delivery time, a delivery counter and a "rotate secret" action.

---

## 3. Pairing page (`/pairing`)

### Pairing page  `id: web-c.pairing.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `PAIRING` (href `/pairing`); page `<h1>` "Pairing".
- **What it does:** Approves or revokes the messaging users allowed to talk to the agent. When a chat platform has no static allowlist, unknown senders get a pairing code and land here as pending requests.
- **How it works:** `web/src/pages/PairingPage.tsx:30`. `loadPairing()` (`:39-48`) calls `api.getPairing()` → `GET /api/pairing` → `{pending: PairingUser[], approved: PairingUser[]}` where `PairingUser = {platform, user_id, user_name?, request_id?, age_minutes?}` (`api.ts:1602`). Rows are keyed `"<platform>:<user_id>"` by `getUserKey()` (`:16-18`); `splitUserKey()` (`:20-24`) splits on the first `:` so user IDs containing colons survive. Display name is `user_name || user_id` (`getUserLabel`, `:26-28`).
- **Inputs / options:** Page-header "Clear pending" button; per pending row an "Approve" button; per approved row a "Revoke" icon button.
- **Outputs / side effects:** Writes the platform allowlists/whitelists used by the gateway.
- **Config / env:** Per-platform `*_ALLOWED_USERS` semantics and the profile's pairing store. Mutating calls send `profile: getManagementProfile()` in the JSON **body** (not the query string) — `api.ts:1102-1126` notes that otherwise an approval lands in the wrong profile.
- **Edge cases / guards:** Whole page is a `Spinner` while loading (`:126-132`). A load failure toasts "Failed to load pairing requests".
- **Rebuild notes:** Keep the composite `platform:user_id` key and the body-carried profile; both were bug fixes. A better version would show the pairing code itself and the originating message.

### Pairing → "Clear pending" (page-header button)  `id: web-c.pairing.clear-pending`
- **Surface:** Web dashboard
- **Where:** `/pairing` → page header, right side. Label "Clear pending" rendered uppercase; `Trash2` icon (`Spinner` while clearing).
- **What it does:** Deletes every pending pairing request in one shot.
- **How it works:** `PairingPage.tsx:72-84` + `:108-124`. Uses a native `window.confirm("Clear all pending pairing requests?")` — the only native confirm on these pages — then `api.clearPendingPairing()` → `POST /api/pairing/clear-pending` → `{ok, cleared}`.
- **Inputs / options:** Click; disabled while `clearing`.
- **Outputs / side effects:** Toast "Cleared `<n>` pending request(s)" then reload; failure toasts "Error: `<e>`".
- **Config / env:** n/a
- **Edge cases / guards:** Unlike the other mutations this endpoint does **not** carry the management profile in its body, so it acts on the dashboard's own profile.
- **Rebuild notes:** Replace `window.confirm` with the design-system `ConfirmDialog` used everywhere else, and scope it to the managed profile.

### Pairing → "Pending requests (n)" section  `id: web-c.pairing.pending`
- **Surface:** Web dashboard
- **Where:** `/pairing` → first section. Heading "Pending requests ({count})" — rendered live as "Pending requests (0)" when nothing is queued, "Pending requests (1)", "Pending requests (2)", … — with a `Users` icon; empty state card "No pending pairing requests".
- **What it does:** Lists users awaiting approval, with their platform, display name, raw ID and request age.
- **How it works:** `PairingPage.tsx:157-215`. Each row: `Badge tone="outline"` with `user.platform`; the display label; a muted line showing `user.user_id` and, when `age_minutes` is a number, "`<n>`m ago".
- **Inputs / options:** Button "Approve" per row (uppercase, `Check` icon → `Spinner` while approving); disabled when that row is approving **or** when `user.request_id` is missing.
- **Outputs / side effects:** `api.approvePairing(platform, request_id)` → `POST /api/pairing/approve` `{platform, request_id, profile?}` → toast `Approved: "<label>"` then reload.
- **Config / env:** Adds the user to the platform's approved list for the managed profile.
- **Edge cases / guards:** Clicking with no `request_id` toasts "Missing pairing request" and does nothing. Errors toast "Error: `<e>`".
- **Rebuild notes:** Approvals are keyed by `request_id`, not user id — a request can expire, so surface the age prominently (this UI does, in minutes).

### Pairing → "Approved users (n)" section  `id: web-c.pairing.approved`
- **Surface:** Web dashboard
- **Where:** `/pairing` → second section. Heading "Approved users ({count})" — rendered live as "Approved users (0)" on a fresh install, "Approved users (1)", "Approved users (2)", … — with a `ShieldCheck` icon; empty state card "No approved users".
- **What it does:** Lists currently allowed users per platform and lets you revoke them.
- **How it works:** `PairingPage.tsx:218-270`. Row: platform badge + `user.user_id` as the primary line, `user.user_name` (when present) as a muted sub-line.
- **Inputs / options:** Ghost icon button with `title`/`aria-label` "Revoke", `X` icon, `text-destructive`.
- **Outputs / side effects:** Opens `DeleteConfirmDialog` titled "Revoke access", description `"<label>" will lose access. This cannot be undone.` (fallback "This user will lose access. This cannot be undone."), confirm label "Revoke". Confirming calls `api.revokePairing(platform, user_id)` → `POST /api/pairing/revoke` `{platform, user_id, profile?}` → toast `Revoked: "<label>"` then reload.
- **Config / env:** Removes the user from the platform's approved list for the managed profile.
- **Edge cases / guards:** Revoke errors toast "Error: `<e>`" and re-throw so the dialog stays open with its loading state cleared. `useConfirmDelete` holds the pending key so the dialog text can look the user up in `approved`.
- **Rebuild notes:** The revoke key is `platform:user_id`, split on the first colon only — important for Matrix (`@user:server`) and email-style IDs.

---

## 4. Profiles page (`/profiles`)

### Profiles page  `id: web-c.profiles.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `PROFILES` (href `/profiles`); page `<h1>` "Profiles" (i18n `app.nav.profiles`).
- **What it does:** Lists every Hermes profile (an isolated `HERMES_HOME` with its own config, keys, memories, sessions, skills and cron jobs), shows which one is active, and offers per-profile actions (activate, change model, edit description, edit SOUL.md, manage skills, copy CLI command, rename, delete).
- **How it works:** `web/src/pages/ProfilesPage.tsx:256`. `load()` (`:396-408`) runs `Promise.all([api.getProfiles(), api.getActiveProfile().catch(() => null)])` → `GET /api/profiles` (`{profiles: ProfileInfo[]}`) and `GET /api/profiles/active` (`{active, current}`). `ProfileInfo` = `{name, path, is_default, model, provider, has_env, skill_count, gateway_running, description, description_auto, display_name?, distribution_name, distribution_version, distribution_source, has_alias}` (`api.ts:2176`). A profile counts as active when `activeInfo.active === p.name`, or when `activeInfo.active === "default"` and `p.is_default` (`:415-423`). Cards render in a responsive grid (1 / 2 / 3 columns).
- **Inputs / options:** Page header: "BUILD" (outlined) and "CREATE"; per card: the "⋯" actions menu, inline rename editor; a single modal dialog hosts the model/description/SOUL editors.
- **Outputs / side effects:** Creates/renames/deletes profile directories, writes `SOUL.md`, descriptions and model assignments, and switches the dashboard's managed profile.
- **Config / env:** Each profile is a directory under the profiles root; `p.path` is shown verbatim on the card.
- **Edge cases / guards:** Loading state renders a Braille unicode spinner from the `unicode-animations` package (`ProfilesLoadingSpinner`, `:54-80`) inside `aria-busy="true" aria-live="polite"` with an `sr-only` "Loading..." label; it freezes on frame 0 when `prefers-reduced-motion: reduce` matches. Load failure toasts "Error: <e>".
- **Rebuild notes:** Profile = directory + name; keep `active` (what CLI/gateway will use) separate from `current` (what this dashboard process is running as) — the banner shows both.

### Profiles → "BUILD" (page-header button)  `id: web-c.profiles.build-button`
- **Surface:** Web dashboard
- **Where:** `/profiles` → page header, left of "CREATE". Label "Build", uppercase, outlined.
- **What it does:** Opens the full five-step Profile Builder wizard at `/profiles/new`.
- **How it works:** `ProfilesPage.tsx:751-772` → `navigate("/profiles/new")`.
- **Inputs / options:** Click only.
- **Outputs / side effects:** Client-side route change.
- **Config / env:** n/a
- **Edge cases / guards:** Not disabled at any point.
- **Rebuild notes:** Two creation paths (quick modal + wizard) is deliberate: the modal clones, the wizard builds from scratch with model/skills/MCP selection.

### Profiles → "CREATE" / "New Profile" modal  `id: web-c.profiles.create-modal`
- **Surface:** Web dashboard
- **Where:** `/profiles` → page header "CREATE" (i18n `common.create`) → modal titled "New Profile" (i18n `profiles.newProfile`).
- **What it does:** Creates a profile in one dialog, optionally cloning another profile's config, with an optional description and model.
- **How it works:** `ProfilesPage.tsx:800-967` + `handleCreate()` (`:423-465`) → `POST /api/profiles` with `{name, clone_from, clone_all, no_skills, description?, provider?, model?}`. Model choices are lazily fetched the first time the modal opens (`loadModelChoices()`, `:372-395` → `GET /api/model/options?include_unconfigured=1`) and flattened to `{provider: prov.slug, model, label: "<prov.name> · <model>"}`; the `<Select>` option value is a composite key made of the provider slug, a U+0000 separator and the model id (`modelKey()`, `ProfilesPage.tsx:369-370`).
- **Inputs / options:**
  - Close button `aria-label="Close"`.
  - `Name` (i18n `profiles.name`) — `<Input id="profile-name" autoFocus placeholder="e.g. coder, writer, etc.">`; Enter submits; `aria-invalid` when non-empty and failing `PROFILE_NAME_RE`. Helper text below: "Lowercase letters, digits, _ and - only; must start with a letter or digit; up to 64 characters." (i18n `profiles.nameRule`).
  - `Clone config from` (i18n `profiles.cloneFrom`) — `<Select id="clone-from">`; first option "None (blank)" (i18n `profiles.cloneFromNone`, value `""` → `clone_from: null`), then one option per existing profile name. Default selection is `"default"`.
  - `Description (optional)` — `<textarea id="profile-description" placeholder="What is this profile good at? Used to route kanban tasks by role.">`.
  - `Model (optional)` — `<Select id="profile-model">`; the placeholder option reads "Loading models…" while the list is still loading and "Inherit from clone / default" once loaded; then one option per provider·model. When the list loads empty, the note "No authenticated providers — set a key first" appears.
  - Fieldset legend "Advanced options" with two checkboxes: `clone-all` labelled "Clone everything (memories, sessions, skills, state)" (disabled unless cloning) and `no-skills` labelled "Don't seed bundled skills" (disabled while cloning).
  - Submit button "Create" (uppercase; "Creating..." while in flight).
- **Outputs / side effects:** Creates the profile directory; toast "Created: <name>". If a model was picked but `res.model_set === false`, a second error toast: "Profile created, but the model could not be saved — set it from the profile editor." Form resets (name, description, `noSkills=false`, `cloneAll=false`, `cloneFrom="default"`, model choice cleared), modal closes, list reloads.
- **Config / env:** New profile directory; its `config.yaml` model/provider when picked.
- **Edge cases / guards:** Empty name → toast "Name is required" (i18n `profiles.nameRequired`). Name failing `/^[a-z0-9][a-z0-9_-]{0,63}$/` (mirrors `hermes_cli/profiles.py::_PROFILE_ID_RE`) → toast "Invalid profile name: <nameRule>". `clone_all` is only sent when actually cloning; `no_skills` only when not cloning (`:436-449`).
- **Rebuild notes:** Enforce the name regex on both sides and make clone/no-skills mutually exclusive in the UI, as here — the combination is meaningless.

### Profiles → active-profile banner  `id: web-c.profiles.active-banner`
- **Surface:** Web dashboard
- **Where:** `/profiles`, card above the list. Text: "Active profile: <name>" with a green `Check` icon; when the dashboard's own profile differs, "(<current>)" in mono is appended.
- **What it does:** Names the profile new CLI/gateway runs will use, and (when different) the profile this dashboard process is itself running as.
- **How it works:** `ProfilesPage.tsx:968-991`, fed by `GET /api/profiles/active` → `{active, current}`.
- **Inputs / options:** None.
- **Outputs / side effects:** None.
- **Config / env:** The active-profile pointer file managed by `hermes_cli/profiles.py`.
- **Edge cases / guards:** Hidden entirely when `/api/profiles/active` fails (the call is `.catch(() => null)`).
- **Rebuild notes:** The active/current split is the subtlety — a dashboard can manage a profile it is not running as.

### Profiles → profile card  `id: web-c.profiles.card`
- **Surface:** Web dashboard
- **Where:** `/profiles` → "Profiles ({count})" section (i18n `profiles.allProfiles`, `Users` icon); empty state "No profiles found." (i18n `profiles.noProfiles`).
- **What it does:** Summarises one profile: name, badges, gateway state, description, model, skill count and on-disk path.
- **How it works:** `ProfilesPage.tsx:1016-1221`.
- **Inputs / options / displayed fields:**
  - Title: `display_name (name)` when `display_name` is non-blank, else just `name`.
  - Badges: "active" (success, i18n `profiles.activeBadge`) when active; "default" (secondary, i18n `profiles.defaultBadge`) when `is_default`; "alias" (outline, i18n `profiles.aliasBadge`) when `has_alias`; "env" (outline, i18n `profiles.hasEnv`) when `has_env`; a `Package`-icon badge showing `distribution_name` followed by `@<distribution_version>` when a version is present.
  - Status dot + text: "Gateway running" (green) or "Gateway stopped" (muted).
  - Description line (`line-clamp-2`), italic muted "No description" when empty; a warning badge "review" (i18n `profiles.reviewBadge`) when the description was auto-generated (`description_auto`).
  - Footer lines: "Model: <model> (<provider>)" when a model is set; "Skills: <skill_count>"; the profile `path` in mono.
  - "⋯" actions button (`title`/`aria-label` "Actions", `aria-haspopup="menu"`).
- **Outputs / side effects:** Display only; actions live in the menu.
- **Config / env:** n/a
- **Edge cases / guards:** Renaming replaces the whole card body with the inline rename editor.
- **Rebuild notes:** `distribution_*` marks profiles installed from a distribution bundle — surface it, since those profiles are managed content.

### Profiles → card "⋯" actions menu  `id: web-c.profiles.actions-menu`
- **Surface:** Web dashboard
- **Where:** `/profiles` → any card → top-right "⋯" button (`MoreVertical`) → dropdown `role="menu"`.
- **What it does:** Holds every per-profile action so the card stays clean.
- **How it works:** `ProfilesPage.tsx:88-244` (`ProfileActionsMenu`). Hand-rolled dropdown: a `mousedown` listener on `window` closes it when the click lands outside *this* container (matching `[data-profile-actions]` generally would have kept sibling menus open). Selecting an item runs the action then closes the menu.
- **Inputs / options — every menu item, in order:**
  1. "Set as active" (`Check` icon, i18n `profiles.setActive`) — rendered only when the profile is **not** already active; disabled while a set-active request is in flight.
  2. "Change model" (i18n `profiles.editModel`) — icon `Cpu`, or `ChevronDown` when that editor is already open (re-selecting collapses it).
  3. "Edit description" (i18n `profiles.editDescription`) — icon `AlignLeft` / `ChevronDown`.
  4. "Edit SOUL.md" (i18n `profiles.editSoul`) — icon is a bold letter "S" (`aria-hidden`) / `ChevronDown`.
  5. "Manage skills & tools" (`Package` icon, i18n `profiles.manageSkills`) — navigates to `/skills?profile=<name>`.
  6. "Copy CLI command" (`Terminal` icon, i18n `profiles.openInTerminal`).
  7. "Rename" (`Pencil` icon, i18n `profiles.rename`) — hidden for the default profile; separated by a top border.
  8. "Delete" (`Trash2` icon, i18n `common.delete`, destructive styling) — hidden for the default profile.
- **Outputs / side effects:** Per item, see the dedicated entries below.
- **Config / env:** n/a
- **Edge cases / guards:** The default profile can be activated, re-modelled, described, SOUL-edited and copied, but never renamed or deleted.
- **Rebuild notes:** Menu items double as toggles for the inline editors — the chevron swap is the only affordance signalling that, which is worth improving.

### Profiles → "Set as active"  `id: web-c.profiles.set-active`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Set as active".
- **What it does:** Makes this profile the one new CLI runs and the gateway use, and points the dashboard's profile scope at it.
- **How it works:** `handleSetActive()` (`ProfilesPage.tsx:495-516`) → `POST /api/profiles/active` `{name}` → `{ok, active}`. The canonical `active` value returned by the backend (not the raw input) is fed into `useProfileScope().setProfile(active)` and merged into `activeInfo`.
- **Inputs / options:** Click.
- **Outputs / side effects:** Toast: "Active profile set: <active> — Dashboard switched to manage <active>. New CLI/gateway runs will use this profile too." Errors toast "Error: <e>".
- **Config / env:** The active-profile pointer; the dashboard's `profile` query parameter for all subsequent profile-scoped API calls.
- **Edge cases / guards:** The menu item is hidden for the already-active profile and disabled while in flight.
- **Rebuild notes:** Trusting the server's normalised name is important — aliases and case differences would otherwise desync the scope.

### Profiles → "Change model" editor  `id: web-c.profiles.model-editor`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Change model" → modal titled "Change model · <profile>".
- **What it does:** Assigns a provider+model to that profile.
- **How it works:** `openModelEditor()` (`ProfilesPage.tsx:648-662`) pre-selects the current composite key and lazily loads the choices; `handleSaveModel()` (`:663-687`) → `PUT /api/profiles/{name}/model` `{provider, model}`. The three editors (model/description/SOUL) share one modal; `editorKind` decides the body (`:689-704`).
- **Inputs / options:** `<Select>` with placeholder "Loading models…" (while loading) or "Select a model", listing every "<provider name> · <model>" pair; button "Save" (uppercase; "Saving..." while saving), disabled until a valid choice is selected. Close button `aria-label="Close"`; backdrop click and Escape close.
- **Outputs / side effects:** Toast "Model updated: <model>"; the card's model line updates optimistically; the editor closes.
- **Config / env:** The profile's `config.yaml` model/provider keys.
- **Edge cases / guards:** When the loaded model list is empty the body is just the note "No authenticated providers — set a key first".
- **Rebuild notes:** The `<Select>` value packs provider and model into one string separated by U+0000 so provider/model names containing `/` or `:` cannot collide; keep that trick.

### Profiles → "Edit description" editor (+ "Auto-generate")  `id: web-c.profiles.description-editor`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Edit description" → modal titled "Description · <profile>".
- **What it does:** Sets the free-text role description used to route kanban tasks to the right profile, either typed or generated by the agent.
- **How it works:** `openDescEditor()` (`:566-580`), `handleSaveDesc()` (`:581-613`) → `PUT /api/profiles/{name}/description` `{description}` → `{ok, description, description_auto}`; `handleAutoDescribe()` (`:614-646`) → `POST /api/profiles/{name}/describe-auto` `{overwrite: true}` → `ProfileDescribeAutoResult {ok, reason, description, description_auto}`. `activeDescRequest` / `descSavingCount` / `describingCount` refs guard against out-of-order responses and concurrent requests.
- **Inputs / options:** Section label "Description"; ghost button "Auto-generate" (`Sparkles` icon; label becomes "Generating…" while running, and the button is disabled then); `<textarea id="profile-desc-editor" placeholder="What is this profile good at? Used to route kanban tasks by role.">`; button "Save" (uppercase; "Saving...").
- **Outputs / side effects:** Toast "Description saved: <name>" on both save and successful auto-generate; the card's description and its "review" badge update in place.
- **Config / env:** Persisted with the profile; `description_auto` marks machine-written text so the card can badge it "review".
- **Edge cases / guards:** A failed auto-generate toasts "Could not generate description: <reason>". Late responses are dropped if the user has since opened a different profile's editor.
- **Rebuild notes:** Keep the `description_auto` flag: it is what lets the UI nudge the user to review a generated description.

### Profiles → "Edit SOUL.md" editor  `id: web-c.profiles.soul-editor`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Edit SOUL.md" → modal titled "SOUL.md (personality / system prompt) · <profile>".
- **What it does:** Edits the profile's `SOUL.md` — its personality / system-prompt file.
- **How it works:** `openSoulEditor()` (`:525-551`) → `GET /api/profiles/{name}/soul` → `{content, exists}`; `handleSaveSoul()` (`:552-565`) → `PUT /api/profiles/{name}/soul` `{content}`. `activeSoulRequest` ref discards stale responses.
- **Inputs / options:** Label "SOUL.md (personality / system prompt)"; `<textarea id="profile-soul-editor" placeholder="# How this agent should behave…">` (min-height 280 px, monospace, the modal body scrolls); button "Save" (uppercase; "Saving...").
- **Outputs / side effects:** Writes `<profile>/SOUL.md`; toast "SOUL.md saved: <name>"; the editor closes.
- **Config / env:** `SOUL.md` inside the profile directory.
- **Edge cases / guards:** Load errors toast "Error: <e>" only if the editor is still showing that profile. The editor opens with an empty textarea until the GET resolves.
- **Rebuild notes:** i18n exposes `profiles.saveSoul` ("Save SOUL") but the button actually renders the generic `common.save`; a rebuild should either use the specific string or drop it.

### Profiles → "Copy CLI command"  `id: web-c.profiles.copy-command`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Copy CLI command" (`Terminal` icon).
- **What it does:** Copies the shell command that runs Hermes under that profile to the clipboard.
- **How it works:** `handleCopyTerminalCommand()` (`ProfilesPage.tsx:704-718`) → `GET /api/profiles/{name}/setup-command` → `{command}` → `copyTextToClipboard()` (`web/src/lib/clipboard.ts`).
- **Inputs / options:** Click.
- **Outputs / side effects:** Toast "Copied to clipboard: <command>" (i18n `profiles.commandCopied`) or, when the clipboard write fails, "Could not copy: <command>" (i18n `profiles.copyFailed`) — either way the command text is shown so it can be selected manually. A failed fetch toasts "Error: <e>".
- **Config / env:** n/a
- **Edge cases / guards:** Clipboard access is blocked on non-secure origins; the error toast is the fallback path.
- **Rebuild notes:** Always echo the command in the failure toast — that is the only recovery in a locked-down browser.

### Profiles → inline rename  `id: web-c.profiles.rename`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Rename" → the card body is replaced by an inline editor.
- **What it does:** Renames a profile (and its directory).
- **How it works:** `ProfilesPage.tsx:1021-1065` for the editor; `handleRenameSubmit()` (`:472-493`) → `PATCH /api/profiles/{name}` `{new_name}` → `{ok, name, path}`.
- **Inputs / options:** Auto-focused `<Input>` pre-filled with the current name; Enter submits; Escape cancels; helper line shows the name rule in muted text, or in destructive red prefixed "Invalid profile name: " when the typed value is invalid; buttons "Save" and ghost "Cancel".
- **Outputs / side effects:** Toast "Renamed: <old> → <new>"; the list reloads.
- **Config / env:** Moves the profile directory.
- **Edge cases / guards:** Empty input or an unchanged name silently cancels. Invalid names toast "Invalid profile name: <nameRule>". The menu item does not exist for the default profile.
- **Rebuild notes:** Validate client-side against the same regex before the PATCH; a rename that fails halfway is the worst case, so make the server move atomically.

### Profiles → delete profile  `id: web-c.profiles.delete`
- **Surface:** Web dashboard
- **Where:** `/profiles` → card → "⋯" → "Delete" → confirm dialog titled "Delete profile?" (i18n `profiles.confirmDeleteTitle`).
- **What it does:** Permanently deletes a profile and everything inside it.
- **How it works:** `useConfirmDelete` at `ProfilesPage.tsx:720-736`; confirm → `DELETE /api/profiles/{name}`.
- **Inputs / options:** Dialog buttons from `DeleteConfirmDialog` (Cancel / destructive confirm).
- **Outputs / side effects:** Removes the profile directory; toast "Deleted: <name>"; list reloads. Errors toast "Error: <e>" and re-throw so the dialog reports failure.
- **Config / env:** n/a
- **Edge cases / guards:** Dialog body is "This permanently deletes profile '<name>' — config, keys, memories, sessions, skills, cron jobs. Cannot be undone." (i18n `profiles.confirmDeleteMessage`); when that profile's gateway is running, a second paragraph is appended: "This profile's gateway is running — it will be stopped." (i18n `profiles.gatewayRunningWarning`). The default profile has no Delete item.
- **Rebuild notes:** Enumerate exactly what is destroyed in the confirm text — this dialog does, and that is the right pattern for irreversible directory deletion.

---

## 5. Profile Builder wizard (`/profiles/new`)

### Profile Builder page  `id: web-c.builder.page`
- **Surface:** Web dashboard
- **Where:** `/profiles` → "BUILD", or the URL `/profiles/new`. Page heading "New profile"; a ghost "Cancel" button top-right returns to `/profiles`. (The app-shell page title for this route is the literal "Profiles/new" — `resolvePageTitle()` has no entry for `/profiles/new` and falls back to capitalising the path segment, `web/src/lib/resolve-page-title.ts:51-55`.)
- **What it does:** A five-step wizard that composes name, description, model, skill selection (built-in + hub) and MCP servers, then creates the whole profile in a single `POST /api/profiles`.
- **How it works:** `web/src/pages/ProfileBuilderPage.tsx:60`. `STEPS` (`:32-38`) = `identity | model | skills | mcp | review`. Nothing touches disk until "Create profile"; `handleCreate()` (`:227-264`) sends `{name, clone_from: null, description?, provider?, model?, mcp_servers?, keep_skills?, hub_skills?}`. Skills use REPLACE semantics: the server seeds the default bundle then disables every seeded skill absent from `keep_skills`; omitting `keep_skills` (the "start from full bundle" toggle) keeps everything.
- **Inputs / options:** Stepper buttons "1. Identity", "2. Model", "3. Skills", "4. MCPs", "5. Review" (each clickable to jump; steps 2-5 are disabled and shown at 50 % opacity until the name is valid); "Back" (ghost, disabled on step 1); "Next" (disabled while step 1's name is invalid); on the review step "Next" is replaced by "Create profile" ("Creating…" while in flight).
- **Outputs / side effects:** Creates the profile, spawns hub-skill installs, writes MCP servers, then navigates to `/profiles`. Toast: `Profile "<n>" created` or `Profile "<n>" created — <k> hub skills installing` (singular "skill" when k is 1). Failure toasts "Create failed: <e>".
- **Config / env:** New profile directory, its `config.yaml` (model, MCP servers), `.env` (MCP bearer tokens), and the disabled-skills list.
- **Edge cases / guards:** Submitting with an invalid name toasts "Invalid profile name (lowercase, digits, - and _)" and jumps back to the Identity step. `PROFILE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/` (`:28`).
- **Rebuild notes:** One atomic create call for everything is the design win — no half-built profiles. Hub installs are the only async tail, and the toast says so.

### Profile Builder → step 1 "Identity"  `id: web-c.builder.step-identity`
- **Surface:** Web dashboard
- **Where:** `/profiles/new` → step "1. Identity".
- **What it does:** Collects the profile's name and optional description.
- **How it works:** `ProfileBuilderPage.tsx:317-346`.
- **Inputs / options:** two text inputs. (1) `pb-name` — label "Profile name", placeholder "coder" (markup: `<Label htmlFor="pb-name">` + `<Input id="pb-name">`). (2) `pb-desc` — label "Description (optional)", placeholder "What this agent profile is for" (markup: `<Label htmlFor="pb-desc">` + `<Input id="pb-desc">`). Both placeholders verbatim: "coder" and "What this agent profile is for".
- **Outputs / side effects:** Local state only.
- **Config / env:** n/a
- **Edge cases / guards:** A non-empty invalid name shows the destructive helper "Lowercase letters, digits, hyphens and underscores; must start with a letter or digit." and blocks both "Next" and the later stepper buttons.
- **Rebuild notes:** Gate the whole wizard on step-1 validity, as here — every later step keys off the name.

### Profile Builder → step 2 "Model"  `id: web-c.builder.step-model`
- **Surface:** Web dashboard
- **Where:** `/profiles/new` → step "2. Model".
- **What it does:** Picks the provider+model pair for the new profile, or defers it.
- **How it works:** `ProfileBuilderPage.tsx:348-389`; `loadModels()` (`:98-120`) fetches `GET /api/model/options?include_unconfigured=1` on first entry to the step and flattens providers × models into `{provider, model, label: "<name> · <model>"}`.
- **Inputs / options:** Intro line "Pick the model+provider for this profile. Skip to use the default."; `<Input placeholder="Filter models…">` (case-insensitive substring match on the label); a scrollable radio-style list whose first row is "Use default (set later)" followed by one button per model labelled "<provider name> · <model>"; the selected row is highlighted `bg-primary/10`.
- **Outputs / side effects:** Local state only.
- **Config / env:** Sent as `provider` + `model` in the create call.
- **Edge cases / guards:** While loading, the list is replaced by "Loading models…". A fetch failure yields an empty list (only the "Use default (set later)" row remains).
- **Rebuild notes:** A filter box plus a flat list scales better than nested provider accordions when a user has dozens of providers.

### Profile Builder → step 3 "Skills"  `id: web-c.builder.step-skills`
- **Surface:** Web dashboard
- **Where:** `/profiles/new` → step "3. Skills".
- **What it does:** Chooses which bundled skills stay enabled in the new profile and queues extra skills from the skills hub.
- **How it works:** `ProfileBuilderPage.tsx:391-504`; `loadSkills()` (`:122-136`) fetches `GET /api/skills` on first entry and seeds the keep-set with every currently-enabled skill name. `runHubSearch()` (`:140-150`) calls `api.searchSkillsHub(query, "all", 20)`.
- **Inputs / options:**
  - Checkbox labelled "Start from the full default skill bundle (recommended)" — checked by default; when checked no `keep_skills` list is sent.
  - When unchecked: helper "Choose which built-in / optional skills to keep active. Unchecked skills are disabled in the new profile."; `<Input placeholder="Filter skills…">` (matches name, description or category); a scrollable checkbox list where each row shows the skill name, a secondary badge with its category, and its description.
  - Hub block: `<Label>Add from the skills hub</Label>`; `<Input placeholder="Search the hub (e.g. linear, hyperliquid)…">` (Enter triggers search); outlined button "Search" ("Searching…" while in flight, disabled then).
  - Hub results: per row the skill name, a secondary badge with its `source`, its description, and a ghost "Add" button.
  - Queued hub skills render as removable badges with an "×" button whose `aria-label` is "Remove <name>".
- **Outputs / side effects:** Local state; contributes `keep_skills[]` and `hub_skills[]` (identifiers) to the create call.
- **Config / env:** Skill enable/disable state inside the new profile; hub installs run asynchronously after creation.
- **Edge cases / guards:** While the skill list loads, "Loading skills…" is shown; a failed load leaves an empty list. An empty/blank hub query is ignored. Adding the same hub identifier twice is a no-op.
- **Rebuild notes:** "Replace" semantics (seed then disable) avoids re-implementing the bundle; keep the recommended default of keeping everything.

### Profile Builder → step 4 "MCPs"  `id: web-c.builder.step-mcp`
- **Surface:** Web dashboard
- **Where:** `/profiles/new` → step "4. MCPs". Section heading "MCP servers".
- **What it does:** Declares MCP servers (HTTP/SSE or stdio) to write into the new profile's config.
- **How it works:** `ProfileBuilderPage.tsx:506-695`. The draft is a `McpServerDraft` from `web/src/lib/mcp-server-create.ts`; "Add server" runs `buildMcpServerCreate(draft)`, which validates and normalises it (throwing a message the toast surfaces), then upserts by name into the server list and resets the draft.
- **Inputs / options:**
  - Intro "Add MCP servers to give this profile access to external tools and data."; live counter "<n> configured" (`aria-live="polite"`).
  - Sub-heading "Add server".
  - `<Label htmlFor="pb-mcp-name">Server name</Label>` + `<Input id="pb-mcp-name" placeholder="Enter server name">`.
  - `Transport` — a two-button group (`role="group" aria-label="MCP transport"`) with exactly two options: "HTTP/SSE" (value `http`) and "stdio" (value `stdio`); `aria-pressed` marks the active one. Switching clears the fields belonging to the other transport.
  - HTTP branch: `<Label htmlFor="pb-mcp-url">URL</Label>` + `<Input id="pb-mcp-url" placeholder="https://example.com/mcp">`; `Authentication` three-button group (`aria-label="HTTP authentication"`) — "None" (`none`), "Bearer token" (`header`), "OAuth" (`oauth`). Choosing "Bearer token" reveals `<Label htmlFor="pb-mcp-bearer-token">Bearer token</Label>` + `<Input id="pb-mcp-bearer-token" type="password" autoComplete="new-password" placeholder="Token or Bearer token">` and the note "Stored in the new profile's .env; config.yaml keeps only an environment-variable reference." Choosing "OAuth" shows the note "After creating the profile, open its MCP page and use Authenticate to complete OAuth."
  - stdio branch: `<Label htmlFor="pb-mcp-command">Command</Label>` + `<Input id="pb-mcp-command" placeholder="npx">`; `<Label htmlFor="pb-mcp-args">Arguments</Label>` + `<Input id="pb-mcp-args" placeholder="-y @modelcontextprotocol/server">`; `<Label htmlFor="pb-mcp-env">Environment (KEY=VALUE per line)</Label>` + a `<textarea id="pb-mcp-env">` whose placeholder is two lines, "API_KEY=secret" then "DEBUG=1".
  - Button "Add server".
  - Added-server rows: name, an outline badge "HTTP" or "stdio", an outline badge "auth: bearer" / "auth: oauth" when auth is set, the URL or the command plus args joined by spaces, and a destructive ghost "Remove" button.
- **Outputs / side effects:** Local list; sent as `mcp_servers[]` in the create call, which writes them to the new profile's `config.yaml` (and `.env` for bearer tokens).
- **Config / env:** New profile's MCP config; `.env` entry for a bearer token.
- **Edge cases / guards:** Invalid drafts toast the validator's message, or "Invalid MCP server" for a non-`Error` throw. Adding a server whose name already exists replaces the earlier entry.
- **Rebuild notes:** Never write a bearer token into `config.yaml` — the env-reference indirection here is the pattern to copy.

### Profile Builder → step 5 "Review"  `id: web-c.builder.step-review`
- **Surface:** Web dashboard
- **Where:** `/profiles/new` → step "5. Review".
- **What it does:** Shows exactly what will be created before the single write.
- **How it works:** `ProfileBuilderPage.tsx:696-737`; rows are rendered by the local `ReviewRow` component (`:826-834`) as a fixed-width label column plus value.
- **Inputs / options / rows:**
  - "Name" → the trimmed name, or an em dash.
  - "Description" → the trimmed description, or an em dash.
  - "Model" → the picked "<provider> · <model>" label, or "Default (set later)".
  - "Skills" → "Full default bundle" when keep-all is on, else "<n> built-in/optional kept" with " + <k> hub" appended when hub skills are queued.
  - When keep-all is off and hub skills exist, an extra indented line "Hub: <comma-separated names>".
  - When keep-all is on and hub skills exist, an extra row "Hub skills" → the comma-separated names.
  - "MCP servers" → comma-separated names, or "None".
- **Outputs / side effects:** None until "Create profile" is pressed.
- **Config / env:** n/a
- **Edge cases / guards:** "Create profile" stays disabled while creating or while the name is invalid.
- **Rebuild notes:** A literal echo of the payload is the cheapest way to make a multi-step wizard trustworthy.

---

## 6. Config page (`/config`)

Page mechanics only — the meaning of individual keys belongs to the config shards.

### Config page  `id: web-c.config.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `CONFIG` (href `/config`); page `<h1>` "Config" (i18n `app.nav.config`).
- **What it does:** A generated settings form over the whole of `config.yaml`: a left rail of 41 categories with field counts, a search box, per-type field widgets, plus JSON export/import, scoped reset-to-defaults and a raw-YAML editor.
- **How it works:** `web/src/pages/ConfigPage.tsx:104`. On mount it fires five requests (`:164-203`): `GET /api/config` (current values, profile-scoped), `GET /api/config/schema` (`{fields, category_order}`), `GET /api/config/defaults`, `GET /api/config/raw` (`{yaml, path}`) and `GET /api/status` (fallback `config_path`). The live schema has **785 fields**; the page deletes exactly one — `memory.provider` — because the Plugins page owns that setting (`ConfigPage.tsx:170-181`), leaving 784 rendered. Values are read/written into a nested object with `getNestedValue`/`setNestedValue` (`web/src/lib/nested.ts`) keyed by the dotted schema key. Nothing is persisted until Save.
- **Inputs / options:** Header search box; export / import / reset icon buttons; the `YAML`/`Form` toggle; `SAVE`; the category rail; and one widget per field.
- **Outputs / side effects:** `PUT /api/config` `{config}` (form mode) or `PUT /api/config/raw` `{yaml_text}` (YAML mode); a JSON file download on export.
- **Config / env:** Every key in `config.yaml`; the resolved path is displayed at the top.
- **Edge cases / guards:** While either `config` or `schema` is null the page is a centred `Spinner` (`:370-376`). Each of the five loads swallows its own error (`.catch(() => {})`), so a partial failure silently degrades the page.
- **Rebuild notes:** Schema-driven forms need three parallel documents — current values, defaults, and field metadata — plus a raw escape hatch. That is exactly this page. A better version would show a per-field "modified from default" marker and a diff preview before saving.

### Config → config-path header line  `id: web-c.config.path-line`
- **Surface:** Web dashboard
- **Where:** `/config`, top-left, a `Settings2` icon followed by the path in a `<code>` chip.
- **What it does:** Shows which `config.yaml` the page is editing.
- **How it works:** `ConfigPage.tsx:438-444`. Prefers `path` from `GET /api/config/raw` because that call is profile-scoped (`fetchJSON` appends `?profile=`), falling back to `/api/status`'s machine-global `config_path`, and finally to the literal i18n string `config.configPath` = "~/.hermes/config.yaml".
- **Inputs / options:** None (not selectable as a control; plain text).
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** Under the global profile switcher, `/api/status`'s path is the wrong profile's — hence the ordering.
- **Rebuild notes:** Always show the file you are about to overwrite when a page has a raw-edit mode.

### Config → search box  `id: web-c.config.search`
- **Surface:** Web dashboard
- **Where:** `/config` → page header, right side; `<Input placeholder="Search...">` (i18n `common.search`) with a `Search` icon and, once non-empty, a clear button (`aria-label` "Clear", i18n `common.clear`, `X` icon).
- **What it does:** Filters the entire 784-field schema and replaces the category view with a flat "Search Results" card.
- **How it works:** `ConfigPage.tsx:128-156` (header injection) and `:252-268` (`searchMatchedFields`). A field matches when the lower-cased query is a substring of: the full dotted key; the last key segment with underscores replaced by spaces; the field's `category`; or the field's `description`.
- **Inputs / options:** Free text; the clear button.
- **Outputs / side effects:** Switches the right pane to the search view; also re-scopes the reset button (see below). Selecting a category clears the query.
- **Config / env:** n/a
- **Edge cases / guards:** `isSearching` is true only when the trimmed query is non-empty. No matches renders `No fields match "<query>"` (i18n `config.noFieldsMatch`).
- **Rebuild notes:** Searching descriptions as well as keys is what makes an 800-key form usable; keep it.

### Config → "Export config as JSON"  `id: web-c.config.export`
- **Surface:** Web dashboard
- **Where:** `/config` → toolbar (right of the path line); ghost icon button, `Download` icon, `title`/`aria-label` "Export config as JSON" (i18n `config.exportConfig`).
- **What it does:** Downloads the current in-form config as a JSON file.
- **How it works:** `handleExport()` (`ConfigPage.tsx:340-351`): `JSON.stringify(config, null, 2)` → `Blob` (`application/json`) → object URL → a synthetic `<a download="hermes-config.json">` click → `URL.revokeObjectURL`.
- **Inputs / options:** Click.
- **Outputs / side effects:** Saves `hermes-config.json` to the browser's download location. Exports the **in-memory form state**, including unsaved edits.
- **Config / env:** n/a
- **Edge cases / guards:** No-ops when config has not loaded.
- **Rebuild notes:** Exporting unsaved state is a subtle trap — label it, or export the persisted document instead.

### Config → "Import config from JSON"  `id: web-c.config.import`
- **Surface:** Web dashboard
- **Where:** `/config` → toolbar; ghost icon button, `Upload` icon, `title`/`aria-label` "Import config from JSON" (i18n `config.importConfig`). Backed by a hidden `<input type="file" accept=".json">`.
- **What it does:** Replaces the whole form state with a JSON file's contents.
- **How it works:** `handleImport()` (`ConfigPage.tsx:353-367`): `FileReader.readAsText` → `JSON.parse` → `setConfig(imported)`.
- **Inputs / options:** One `.json` file from the OS file picker.
- **Outputs / side effects:** Toast "Config imported — review and save" (i18n `config.configImported`). Nothing is written until Save.
- **Config / env:** n/a
- **Edge cases / guards:** A parse failure toasts "Invalid JSON file" (i18n `config.invalidJson`). The import is a wholesale replace — keys missing from the file disappear from the form (and from `config.yaml` on save).
- **Rebuild notes:** Merge rather than replace, or at minimum diff the import against the current document before applying.

### Config → "Reset <scope> to defaults"  `id: web-c.config.reset`
- **Surface:** Web dashboard
- **Where:** `/config` → toolbar; ghost icon button, `RotateCcw` icon. Its `title`/`aria-label` is built from i18n `config.resetScopeTooltip` = "Reset {scope} to defaults" — e.g. "Reset General to defaults" or "Reset Search Results to defaults". Hidden entirely in YAML mode.
- **What it does:** Resets only the fields the user is currently looking at (the active category, or the search matches) to their defaults, in the form.
- **How it works:** `handleReset()` (`ConfigPage.tsx:308-319`) picks the scope then opens a `ConfirmDialog`; `executeReset()` (`:321-338`) walks the scoped fields writing `getNestedValue(defaults, key)` into the form state.
- **Inputs / options:** Click → confirm dialog with title from i18n `config.confirmResetScope` = "Reset all {scope} settings to their defaults? This only updates the form — changes aren't written to config.yaml until you press Save.", description "This will reset `<n>` field(s) to their default values.", destructive styling, confirm label "Reset to defaults" (i18n `config.resetDefaults`).
- **Outputs / side effects:** Form-only mutation; toast from i18n `config.resetScopeToast` = "{scope} reset to defaults — review and Save to persist".
- **Config / env:** Defaults come from `GET /api/config/defaults`.
- **Edge cases / guards:** No-ops when the scope has zero fields or when defaults/config have not loaded. The scoping is a deliberate fix: the button sits beside the category rail and previously wiped the entire `config.yaml` (source comment cites the report by @ykmfb001, `ConfigPage.tsx:310-315`).
- **Rebuild notes:** Scope destructive actions to what the user can see, and say in the dialog that nothing is written until Save.

### Config → "YAML" / "Form" mode toggle  `id: web-c.config.yaml-toggle`
- **Surface:** Web dashboard
- **Where:** `/config` → toolbar, right of a vertical divider. Button label is "YAML" (with a `Code` icon) while in form mode and "Form" (i18n `common.form`, `FormInput` icon) while in YAML mode; the button is `outlined` in form mode.
- **What it does:** Swaps the generated form for a raw `config.yaml` text editor.
- **How it works:** `ConfigPage.tsx:495-502`; entering YAML mode triggers `GET /api/config/raw` (`:213-222`) and shows a `Spinner` while loading.
- **Inputs / options:** Click.
- **Outputs / side effects:** Changes which Save handler the SAVE button uses.
- **Config / env:** n/a
- **Edge cases / guards:** A failed raw load toasts "Failed to load raw config" (i18n `config.failedToLoadRaw`) and leaves the textarea empty — saving then would blank the file.
- **Rebuild notes:** Guard the raw editor against saving an empty buffer after a failed load.

### Config → raw YAML editor  `id: web-c.config.yaml-editor`
- **Surface:** Web dashboard
- **Where:** `/config` → YAML mode → card titled "Raw YAML Configuration" (i18n `config.rawYaml`, `FileText` icon) containing one full-width `<textarea>` (min-height 600 px, monospace, `spellCheck={false}`).
- **What it does:** Lets the user edit `config.yaml` as text, including keys the schema does not describe.
- **How it works:** `ConfigPage.tsx:526-548`; `handleYamlSave()` (`:292-306`) → `PUT /api/config/raw` `{yaml_text}`, then re-fetches `GET /api/config` so the form view reflects the new document.
- **Inputs / options:** Free text; the toolbar SAVE button.
- **Outputs / side effects:** Overwrites `config.yaml` wholesale. Toast "YAML config saved" (i18n `config.yamlConfigSaved`) or "Failed to save YAML: `<e>`" (i18n `config.failedToSaveYaml`).
- **Config / env:** The whole `config.yaml` for the managed profile.
- **Edge cases / guards:** No client-side YAML validation — invalid YAML is rejected by the server. There is no confirmation and no backup.
- **Rebuild notes:** Add client-side YAML parsing and a diff-vs-disk view; a raw editor with no validation is the sharpest edge on this page.

### Config → "SAVE"  `id: web-c.config.save`
- **Surface:** Web dashboard
- **Where:** `/config` → toolbar, rightmost. Label "Save" (i18n `common.save`) rendered uppercase; "Saving..." (i18n `common.saving`) while in flight.
- **What it does:** Persists the current form (or YAML buffer) to `config.yaml`.
- **How it works:** Form mode → `handleSave()` (`ConfigPage.tsx:279-290`) → `PUT /api/config` `{config}` (profile-scoped). YAML mode → `handleYamlSave()`.
- **Inputs / options:** Click; disabled while saving.
- **Outputs / side effects:** Toast "Configuration saved" (i18n `config.configSaved`) or "Failed to save: `<e>`" (i18n `config.failedToSave`). Most keys only take effect on the next agent/gateway start.
- **Config / env:** All of `config.yaml`.
- **Edge cases / guards:** The form PUT sends the entire config document, so a concurrent edit elsewhere is overwritten (last write wins). No dirty-state indicator and no navigation guard — leaving the page discards edits silently.
- **Rebuild notes:** Send a patch (changed keys only) with an ETag/mtime precondition instead of the whole document.

### Config → category rail ("Filters" / "Sections")  `id: web-c.config.category-rail`
- **Surface:** Web dashboard
- **Where:** `/config` → left sidebar (a horizontal scroller on small screens). Header "Filters" (i18n `config.filters`, `Filter` icon) is the `aside`'s `aria-label`; sub-heading "Sections" (i18n `config.sections`); then one row per category showing an icon, the category label and its field count.
- **What it does:** Selects which slice of the schema the right pane shows.
- **How it works:** `ConfigPage.tsx:551-601`. Category ordering = `category_order` from the API filtered to categories that actually occur, then any remaining categories sorted alphabetically (`:225-235`). Counts are computed from the schema (`:238-246`). Labels come from i18n `config.categories.<key>` when present, else the raw key with its first letter capitalised (`prettyCategoryName`, `:158-162`). Icons come from `CATEGORY_ICONS` (`:59-87`), defaulting to `FileQuestion`.
- **Inputs / options — every row, exactly as rendered live (label + count):** "General 25", "Agent 102", "Terminal 31", "Display 87", "Delegation 15", "Memory 6", "Compression 32", "Security 31", "Browser 25", "Voice 14", "Text-to-Speech 30", "Speech-to-Text 26", "Logging 3", "Discord 37", "Auxiliary 115", "Bedrock 8", "Curator 10", "Database 3", "Desktop 11", "Gateway 22", "Kanban 16", "Loops 4", "Lsp 5", "Matrix 3", "Mattermost 3", "Moa 10", "Model_catalog 3", "Monitoring 11", "Openrouter 3", "Proxy 5", "Secrets 15", "Sessions 13", "Slack 6", "Streaming 6", "Tool_loop_guardrails 10", "Tool_output 3", "Tools 6", "Vertex 2", "Wake_word 14", "Web 9", "X_search 4" — 41 rows, 784 fields.
- **Outputs / side effects:** Clicking a row clears the search query and sets the active category.
- **Config / env:** `category_order` = `["general","agent","terminal","display","delegation","memory","compression","security","browser","voice","tts","stt","logging","discord","auxiliary"]`; the remaining 26 categories are appended alphabetically.
- **Edge cases / guards:** "Memory" shows 6 rather than the schema's 7 because `memory.provider` is deleted client-side. Categories outside `category_order` have no i18n label, so they render title-cased raw keys including underscores ("Model_catalog", "Tool_loop_guardrails", "Wake_word", "X_search"). Icons exist for `bedrock`, `curator`, `kanban`, `model_catalog`, `openrouter`, `sessions`, `tool_loop_guardrails`, `tool_output`, `updates` and the 15 ordered categories; every other category falls back to `FileQuestion`. (`updates` has an icon but no fields in this build.)
- **Rebuild notes:** Complete icon map (category → lucide icon): general→Settings, agent→Bot, terminal→Monitor, display→Palette, delegation→Users, memory→Brain, compression→Package, security→Lock, browser→Globe, voice→Mic, tts→Volume2, stt→Ear, logging→ClipboardList, discord→MessageCircle, auxiliary→Wrench, bedrock→Cloud, curator→Sparkles, kanban→LayoutDashboard, model_catalog→BookOpen, openrouter→Route, sessions→History, tool_loop_guardrails→Shield, tool_output→FileOutput, updates→RefreshCw, everything else→FileQuestion. Translate the remaining 26 category keys — the untranslated raw keys are the most visible rough edge on the page.

### Config → active-category field card  `id: web-c.config.category-card`
- **Surface:** Web dashboard
- **Where:** `/config` → right pane (form mode, no search). Card header shows the category icon, the pretty category name, and a secondary badge "`<n>` field" / "`<n>` fields" (i18n `config.fields` = "field{s}", pluralised by substituting "s" when the count is not 1).
- **What it does:** Renders every field of the selected category as an editable widget.
- **How it works:** `ConfigPage.tsx:631-656`; `activeFields` (`:271-276`) filters the schema by `category`. Rendering is delegated to `renderFields()` (`:379-431`).
- **Inputs / options:** The widgets themselves (see `web-c.config.field-widgets`), plus automatic sub-section separators: when consecutive keys change their first dotted segment and that segment differs from the active category name, a divider row is emitted showing the segment with underscores replaced by spaces (`:412-419`).
- **Outputs / side effects:** Edits mutate the in-memory config; nothing persists until Save.
- **Config / env:** n/a
- **Edge cases / guards:** Field order is the schema's own object order, not alphabetical.
- **Rebuild notes:** The implicit "first segment = sub-section" grouping is free structure from dotted keys; reuse it.

### Config → "Search Results" card  `id: web-c.config.search-card`
- **Surface:** Web dashboard
- **Where:** `/config` → right pane while the search box is non-empty. Card header: `Search` icon + "Search Results" (i18n `config.searchResults`) and a secondary badge with the match count and the same "field{s}" pluralisation.
- **What it does:** Shows matching fields from every category in one flat list, grouped by category headings.
- **How it works:** `ConfigPage.tsx:604-630` with `renderFields(searchMatchedFields, true)`; in this mode each category change emits a heading row with the category icon and pretty name plus a horizontal rule (`:400-411`).
- **Inputs / options:** The field widgets.
- **Outputs / side effects:** Same as the category card.
- **Config / env:** n/a
- **Edge cases / guards:** Zero matches renders `No fields match "<query>"` centred and muted.
- **Rebuild notes:** Keeping the category label visible in search results is what stops users editing the wrong `enabled` flag.

### Config → field widgets by schema type  `id: web-c.config.field-widgets`
- **Surface:** Web dashboard
- **Where:** `/config` → any field row. Every widget renders a label (the last dotted segment with underscores turned into spaces and each word capitalised), then a hint block: the full dotted key in monospace `text-text-tertiary`, then the schema `description` in `text-text-secondary`.
- **What it does:** Maps a schema field type to an input control.
- **How it works:** `web/src/components/AutoField.tsx:85-199`. Live type distribution across the 785 schema fields: `string` 285, `number` 244, `boolean` 204, `list` 30, `select` 22.
- **Inputs / options — every branch, in evaluation order:**
  1. **Object / array-of-objects** (checked before the type at all — when the *current value* is a plain object, or an array containing an object): a bordered block with the label, the hint, and a recursive `NestedValueEditor` (`AutoField.tsx:31-83`). Objects render one labelled row per key (label = the raw sub-key); arrays render rows labelled "Item 1", "Item 2", …; leaves become plain text `<Input>`s. Scalars are stringified with `formatScalar()` (strings as-is, numbers/booleans via `String()`, anything else `JSON.stringify`). Every edit writes back a **string**, so numbers and booleans nested inside objects are silently retyped.
  2. **`type: "boolean"`** → a right-aligned `Switch`, checked on the value's truthiness.
  3. **`type: "select"`** → a `<Select>` listing `schema.options` verbatim; an empty-string option renders with the literal placeholder text "(none)".
  4. **`type: "number"`** → `<Input type="number">`; an emptied field writes the number `0`; non-numeric input is ignored (the previous value stays).
  5. **`type: "text"`** → a `<textarea>` (min-height 80 px).
  6. **`type: "list"`** → a single-line `<Input placeholder="comma-separated values">`; the displayed value is `value.join(", ")`; on change the text is split on `,`, each part trimmed, and empty parts dropped.
  7. **Fallback (including `type: "string"`)** → a plain text `<Input>`.
- **Outputs / side effects:** Calls `onChange(v)`, which writes into the nested config object via `setNestedValue`.
- **Config / env:** Driven entirely by `GET /api/config/schema`, whose per-field record carries at least `type`, `category`, `description` and (for selects) `options`.
- **Edge cases / guards:** The number widget cannot express "unset" — clearing it yields `0`. The list widget cannot express a value containing a comma. The nested editor stringifies everything, which can change a value's type on save. Boolean uses truthiness, so the string `"false"` reads as true.
- **Rebuild notes:** Type-drive the widget from the schema, not from the runtime value — the object-first branch here is why nested numbers become strings. Add a min/max/step from the schema for numbers, a proper tag editor for lists, and a tri-state (unset) affordance so defaults can be restored per field.

### Config → plugin slots  `id: web-c.config.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `/config` — an invisible extension point above the toolbar and below the form.
- **What it does:** Lets a dashboard plugin inject UI into the Config page.
- **How it works:** `<PluginSlot name="config:top" />` (`ConfigPage.tsx:435`) and `<PluginSlot name="config:bottom" />` (`:660`), rendered by `web/src/plugins`.
- **Inputs / options:** Slot names `config:top`, `config:bottom`.
- **Outputs / side effects:** Whatever the plugin renders.
- **Config / env:** Plugins are discovered from `~/.hermes/plugins` and served under `dashboard-plugins/`.
- **Edge cases / guards:** Load failures surface as the shared strings "Could not load this plugin's script. Check the Network tab (dashboard-plugins/…) and the server's plugin path." (i18n `common.pluginLoadFailed`) and "The plugin's script did not call register(), or the script errored. Open the browser console for details." (i18n `common.pluginNotRegistered`).
- **Rebuild notes:** Named slots per page are cheap and make third-party settings panels possible without forking the page. (The Docs and Env pages carry the same pair: `docs:top`/`docs:bottom`, `env:top`/`env:bottom`.)

---

## 7. Keys page (`/env`)

### Keys page  `id: web-c.env.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `KEYS` (href `/env`, i18n `app.nav.keys`); page `<h1>` "Keys".
- **What it does:** Manages every API key, token and secret Hermes reads from `~/.hermes/.env`: OAuth provider logins, LLM provider keys grouped by vendor, tool keys, gateway-wide messaging settings, general settings, and arbitrary user-added custom keys.
- **How it works:** `web/src/pages/EnvPage.tsx:610` (`EnvPage`). On mount it calls `api.getEnvVars()` → `GET /api/env`, a flat map of `KEY -> EnvVarInfo {is_set, redacted_value, description, url, category, is_password, tools[], advanced, channel_managed, provider, provider_label, custom}`. The live catalog has **340 entries**: 95 `provider`, 198 `messaging`, 39 `tool`, 4 `setting`, 4 `skill`. Provider keys are bucketed into vendor groups by key prefix (`PROVIDER_GROUPS`, `EnvPage.tsx:48-70`); everything with `channel_managed: true` is hidden because the Channels page owns it (server side: `_channel_managed_env_keys()`, `hermes_cli/web_server.py:9457`).
- **Inputs / options:** Section jump-nav in the page header; the "Hide Advanced"/"Show Advanced" toggle; the OAuth card; provider group accordions; three category cards; the custom-keys card with its add form.
- **Outputs / side effects:** `PUT /api/env` `{key, value}` to set, `DELETE /api/env` `{key}` to clear, `POST /api/env/reveal` `{key}` to read a plaintext value. All writes hit `~/.hermes/.env` immediately.
- **Config / env:** The profile's `.env` file (path shown as the literal `~/.hermes/.env` in the intro line).
- **Edge cases / guards:** Whole page is a `Spinner` until `/api/env` resolves; a failed load leaves the page spinning forever (the catch is empty). The 4 `skill`-category keys (`NOTION_API_KEY`, `LINEAR_API_KEY`, `AIRTABLE_API_KEY`, `TENOR_API_KEY`) are returned by the API but rendered by **no** section — the page only iterates `provider` plus `["tool","messaging","setting"]` plus `custom` (`EnvPage.tsx:801-876`), so they are unreachable from this UI and must be set via the CLI, the raw `.env` or the custom-key form.
- **Rebuild notes:** Model an env key as `{key, category, description, url, is_password, advanced, tools[], channel_managed, is_set, redacted_value}` and let the page be a pure renderer over that catalog. A better version would iterate every category present in the payload rather than a hard-coded list, and would surface `provider`/`provider_label` (returned but unused here).

### Keys → page intro line  `id: web-c.env.intro`
- **Surface:** Web dashboard
- **Where:** `/env`, above the OAuth card. Two lines: "Manage API keys and secrets stored in `~/.hermes/.env`" (i18n `env.description` plus a literal `<code>` chip) and, in smaller tertiary text, "Changes are saved to disk immediately. Active sessions pick up new keys automatically." (i18n `env.changesNote`).
- **What it does:** States where secrets live and that writes are immediate.
- **How it works:** `EnvPage.tsx:902-911`.
- **Inputs / options:** None.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** The `~/.hermes/.env` string is hard-coded in the JSX, so under a non-default profile it does not reflect the real path (unlike the Channels page, which shows the resolved `env_path`).
- **Rebuild notes:** Show the resolved path; this literal is misleading under profiles.

### Keys → "Show Advanced" / "Hide Advanced" toggle  `id: web-c.env.advanced-toggle`
- **Surface:** Web dashboard
- **Where:** `/env`, right of the intro line. Outlined button; label "Hide Advanced" (i18n `env.hideAdvanced`) when advanced keys are shown, "Show Advanced" (i18n `env.showAdvanced`) when hidden.
- **What it does:** Filters out env vars flagged `advanced: true` from the provider groups and the three category cards.
- **How it works:** `EnvPage.tsx:616` initialises `showAdvanced` to **true** ("Show all providers by default"), so the button reads "Hide Advanced" on first paint. The flag is applied in the `useMemo` at `:801-876`.
- **Inputs / options:** Click.
- **Outputs / side effects:** Local state only; not persisted.
- **Config / env:** n/a
- **Edge cases / guards:** Hiding advanced keys can empty a whole provider group; the group header still renders with its (filtered) count. The custom-keys card is unaffected.
- **Rebuild notes:** Persist the preference; every reload resets it to "everything visible", which defeats the purpose of the flag.

### Keys → section jump navigation  `id: web-c.env.jump-nav`
- **Surface:** Web dashboard
- **Where:** `/env` → page header, immediately after the title (`aria-label="Jump to section"`). Buttons rendered live: "OAUTH", "PROVIDERS", "TOOLS", "GATEWAY", "SETTINGS", "CUSTOM KEYS" (uppercased by CSS).
- **What it does:** Smooth-scrolls to a section anchor.
- **How it works:** `EnvPage.tsx:628-676`. The list is `[{id:"section-oauth", label:"OAuth"}, {id:"section-providers", label:"Providers"}]` plus, for each of `tool`/`messaging`/`setting` that has at least one non-`channel_managed` entry, a button labelled from `CATEGORY_LABELS` = `{tool: "Tools", messaging: t.common.gateway ("Gateway"), setting: "Settings"}`; finally "Custom Keys" (i18n `env.customTitle`), always present because it carries the add-key form. Each click runs `document.getElementById(id).scrollIntoView({behavior:"smooth", block:"start"})`.
- **Inputs / options:** Six buttons (in this build).
- **Outputs / side effects:** Scrolls the page.
- **Config / env:** n/a
- **Edge cases / guards:** The jump-nav labels deliberately differ from the card titles: the nav says "Tools"/"Settings" while the cards are headed "Keys" (i18n `app.nav.keys`) and "Config" (i18n `app.nav.config`) — `CATEGORY_LABELS` (nav) and `CATEGORY_META_LABELS` (cards) are separate maps (`EnvPage.tsx:630-634` vs `:839-843`).
- **Rebuild notes:** Use one label map for both, or the nav and the section it scrolls to will keep disagreeing.

### Keys → "Provider Logins (OAuth)" card  `id: web-c.env.oauth-card`
- **Surface:** Web dashboard
- **Where:** `/env` → first card, anchor `#section-oauth`. Title "Provider Logins (OAuth)" (i18n `oauth.providerLogins`, `ShieldCheck` icon); description from i18n `oauth.description` = "{connected} of {total} OAuth providers connected. Use Login for dashboard-supported flows; CLI commands remain available for external or fallback setup."; a ghost refresh icon button `aria-label="Refresh"` (i18n `common.refresh`, `RefreshCw` → `Spinner` while loading).
- **What it does:** Shows every OAuth-capable provider, whether it is connected, and lets you start or tear down a login without leaving the browser.
- **How it works:** `web/src/components/OAuthProvidersCard.tsx:52`. `GET /api/providers/oauth` → `{providers: OAuthProvider[]}` where each is `{id, name, flow: "pkce"|"device_code"|"external", cli_command, docs_url, disconnect_hint, disconnect_command, disconnectable, status:{logged_in, source, source_label, token_preview, expires_at, has_refresh_token, last_refresh?, error?}}`.
- **Inputs / options — per provider row:** a `ShieldCheck` (connected) or `ShieldOff` icon; the provider name; an outline badge with the flow label from i18n `oauth.flowLabels` — "Browser login (PKCE)" (`pkce`), "Device code" (`device_code`), "External CLI" (`external`); a success badge "Connected" when logged in; a destructive badge "Expired" when the token's `expires_at` is past; otherwise an outline badge "expires in {time}" where time is rendered as `<n>m`, `<n>h` or `<n>d`. When connected, a mono line "token `<token_preview>` · `<source_label>`". When not connected: the sentence built from i18n `oauth.notConnected` ("Not connected. Use Login when available, or run {command} in a terminal.") with the command spliced out, followed by the `cli_command` in `<code>` and a copy button labelled "Copy" (i18n `oauth.cli`) that flips to "Copied ✓" (i18n `oauth.copied`). A `status.error` renders in destructive text. Right side: an `ExternalLink` icon button linking to `docs_url` with `title="Open <name> docs"`; a primary "LOGIN" button (i18n `oauth.login`) when not connected and the flow is not `external`; an outlined "DISCONNECT" button (i18n `oauth.disconnect`) when connected and the flow is not `external`; for a connected `external` provider, the italic note "Managed externally" (i18n `oauth.managedExternally`) with a `Terminal` icon.
- **Outputs / side effects:** "LOGIN" opens the OAuth modal. "DISCONNECT" opens a `ConfirmDialog` titled "Disconnect `<name>`?" with description "This will remove the stored OAuth tokens for `<name>`. You will need to re-authenticate to use it again." and confirm label "Disconnect"; confirming calls `DELETE /api/providers/oauth/{id}` and toasts "`<name>` disconnected".
- **Config / env:** Token storage is provider-specific (e.g. `auth.json` in the Hermes home, or an external CLI's credential file).
- **Edge cases / guards:** Empty provider list renders "No OAuth-capable providers detected." (i18n `oauth.noProviders`). A load failure surfaces the toast "Failed to load providers: `<e>`". A disconnect failure toasts "Disconnect failed: `<e>`".
- **Rebuild notes:** Three flow kinds with different UI affordances (in-browser PKCE, device code, delegated CLI) is the right abstraction; `disconnectable`/`disconnect_command`/`disconnect_hint` are returned by the API but this card does not use them — a better version would show the hint instead of hiding the button.

### Keys → OAuth providers, live roster  `id: web-c.env.oauth-providers`
- **Surface:** Web dashboard
- **Where:** `/env` → "PROVIDER LOGINS (OAUTH)" card rows.
- **What it does:** Enumerates the eight providers this build advertises.
- **How it works:** Server list from `GET /api/providers/oauth` (`hermes_cli/web_server.py:10868` onward).
- **Inputs / options — every provider row, verbatim:**
  1. **"Nous Portal"** — id `nous`, flow `device_code` (badge "Device code"), CLI `hermes auth add nous`, docs `https://portal.nousresearch.com`, source label "Nous Portal", disconnectable. Shows a "LOGIN" button.
  2. **"ChatGPT or Codex Subscription"** — id `openai-codex`, flow `device_code`, CLI `hermes auth add openai-codex`, docs `https://platform.openai.com/docs`, source label "OpenAI Codex", disconnectable. Shows "LOGIN".
  3. **"Qwen (via Qwen CLI)"** — id `qwen-oauth`, flow `external` (badge "External CLI"), CLI `hermes auth add qwen-oauth`, docs `https://github.com/QwenLM/qwen-code`, source label "Qwen CLI", `disconnectable: false`, hint "Managed by that provider's CLI; remove it there." No LOGIN/DISCONNECT button (external flow).
  4. **"MiniMax (OAuth)"** — id `minimax-oauth`, flow `device_code`, CLI `hermes auth add minimax-oauth`, docs `https://www.minimax.io`, source label "MiniMax (global)", has refresh token, disconnectable. Shows "LOGIN".
  5. **"xAI Grok OAuth (SuperGrok / Premium+)"** — id `xai-oauth`, flow `device_code`, CLI `hermes auth add xai-oauth`, docs `https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth`, source is the Hermes home `auth.json`, has refresh token, disconnectable. Shows "LOGIN".
  6. **"GitHub Copilot (ACP)"** — id `copilot-acp`, flow `external`, CLI `copilot /login`, docs `https://docs.github.com/en/copilot`, source label "Managed by the GitHub Copilot CLI", not disconnectable.
  7. **"Anthropic API Key"** — id `anthropic`, flow `external`, CLI `hermes auth add anthropic`, docs `https://docs.claude.com/en/api/getting-started`, disconnectable.
  8. **"Anthropic OAuth: Required Extra Usage Credits to Use Subscription"** — id `claude-code`, flow `external`, CLI `claude setup-token`, docs `https://docs.claude.com/en/docs/claude-code`, `disconnectable: false`, hint "Managed outside Hermes — run the disconnect command to remove it.", disconnect command `rm -f ~/.claude/.credentials.json`.
- **Outputs / side effects:** Per row, see the card entry.
- **Config / env:** n/a
- **Edge cases / guards:** Rows 3, 6, 7 and 8 are `external`, so the dashboard shows no in-browser login — only the copyable CLI command.
- **Rebuild notes:** Deliberately delegating subscription-style OAuth to a vendor CLI (rather than reimplementing it) keeps the dashboard out of credential-custody it cannot honour.

### Keys → OAuth login modal  `id: web-c.env.oauth-modal`
- **Surface:** Web dashboard
- **Where:** `/env` → OAuth card → "LOGIN" → modal titled "Connect `<provider name>`" (i18n `oauth.connect`).
- **What it does:** Runs a device-code or PKCE OAuth flow entirely from the dashboard.
- **How it works:** `web/src/components/OAuthLoginModal.tsx:28`. On mount it POSTs `/api/providers/oauth/{id}/start` (empty JSON body) and receives a discriminated union: `{session_id, flow:"pkce", auth_url, expires_in}` or `{session_id, flow:"device_code", user_code, verification_url, expires_in, poll_interval}`. It immediately `window.open()`s `auth_url` (PKCE) or `verification_url` (device code) in a new tab. Phases: `idle → starting → awaiting_user | polling → submitting → approved | error`. Device-code flow polls `GET /api/providers/oauth/{id}/poll/{session_id}` every **2000 ms** (a fixed interval — the server's `poll_interval` is not used) until `status` is `approved`, or any non-`pending` status errors out. A 1 s countdown ticks `expires_in` down and errors at zero.
- **Inputs / options:**
  - Close button `aria-label="Close"` (i18n `common.close`); backdrop click closes.
  - Sub-line "Session expires in {time}" (i18n `oauth.sessionExpires`), time formatted `m:ss`.
  - Starting phase: spinner + "Initiating login flow…" (i18n `oauth.initiatingLogin`).
  - PKCE phase: an ordered list — "A new tab opened to claude.ai. Sign in and click Authorize." / "Copy the authorization code shown after authorizing." / "Paste it below and submit." (i18n `oauth.pkceStep1..3`); an auto-focused `<Input placeholder="Paste authorization code (with #state suffix is fine)">` (i18n `oauth.pasteCode`) where Enter submits; a link "Re-open auth page" (i18n `oauth.reOpenAuth`, `ExternalLink`); a button "Submit code" (i18n `oauth.submitCode`), disabled while the field is blank.
  - Submitting phase: spinner + "Exchanging code for tokens…" (i18n `oauth.exchangingCode`).
  - Device-code phase: "A new tab opened. Enter this code if prompted:" (i18n `oauth.enterCodePrompt`); the user code in 2xl monospace with wide tracking; an outlined button "Copy code" (i18n `oauth.copyCode`, `Copy` icon) that becomes "Copied ✓" with a `Check` icon for 2000 ms; a link "Re-open verification page" (i18n `oauth.reOpenVerification`); a footer with a spinner and "Waiting for you to authorize in the browser…" (i18n `oauth.waitingAuth`).
  - Approved phase: a `Check` icon and "Connected! Closing…" (i18n `oauth.connectedClosing`); the modal auto-closes after 1500 ms.
  - Error phase: the message in a destructive box (falling back to "Login failed." — i18n `oauth.loginFailed`), plus buttons "Close" and "Retry" (i18n `common.retry`); Retry cancels the old session and starts a fresh one.
- **Outputs / side effects:** `POST /api/providers/oauth/{id}/start`; `POST /api/providers/oauth/{id}/submit` `{session_id, code}` (PKCE); `GET …/poll/{session_id}` (device code); `DELETE /api/providers/oauth/sessions/{session_id}` when the modal is closed before completion or on Retry. Success toasts "`<provider name>` connected" and refreshes the provider list.
- **Config / env:** Tokens are written by the server into the profile's auth store.
- **Edge cases / guards:** A failed copy shows "Could not copy automatically. Select the code and copy it manually." (i18n `oauth.copyFailed`). Countdown expiry sets the error "Session expired. Click Retry to start a new login." (i18n `oauth.sessionExpired`). Poll failures error out with "Polling failed: `<e>`"; a start failure with "Failed to start login: `<e>`"; a submit failure with "Submit failed: `<e>`" or the server's `message` (default "Token exchange failed"). Poll statuses the server can return: `pending | approved | denied | expired | error`.
- **Rebuild notes:** The server holds the OAuth session and the browser only polls an opaque `session_id` — no client secret or PKCE verifier ever reaches the page. Copy that split. Honour the server's `poll_interval` instead of hard-coding 2 s.

### Keys → "LLM PROVIDERS" card  `id: web-c.env.providers-card`
- **Surface:** Web dashboard
- **Where:** `/env` → second card, anchor `#section-providers`. Title "LLM Providers" (i18n `env.llmProviders`, `Zap` icon); description from i18n `env.providersConfigured` = "{configured} of {total} providers configured" (a group counts as configured when any key in it is set).
- **What it does:** Groups all 95 `provider`-category env vars into 16 collapsible vendor accordions.
- **How it works:** `EnvPage.tsx:916-937` for the card; `ProviderGroupCard` at `:339-482`. Grouping is by key prefix via `PROVIDER_GROUPS` (`:48-70`); anything unmatched lands in a group literally named "Other" (rendered through i18n `common.other`, "Other"). Groups are sorted by the hard-coded priority in that table. Inside an expanded group, keys are rendered in three passes: those ending `_API_KEY` or `_TOKEN`, then those ending `_BASE_URL`, then the rest.
- **Inputs / options — the 16 group rows, in render order (each is a clickable header with `aria-expanded`, a `ChevronRight`/`ChevronDown`, the group name, a success badge "`<n>` set" when any key is configured, an optional "Get key" link taken from the first API-key row that has a URL, and a count chip "`<n>` key(s)" using i18n `env.keysCount`):**
  - **"Nous Portal"** — row label "Nous Portal" (no "Get key" link), count chip "1 key". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `NOUS_BASE_URL` [advanced] — "Nous Portal base URL override".
  - **"Anthropic"** — row label "Anthropic" (no "Get key" link), count chip "3 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `ANTHROPIC_API_KEY` [masked] [advanced] — "anthropic API key".
    - `ANTHROPIC_TOKEN` [masked] [advanced] — "anthropic API key".
    - `ANTHROPIC_BASE_URL` [advanced] — "Anthropic base URL override".
  - **"DashScope (Qwen)"** — row label "DashScope (Qwen)", "Get key" link → `https://modelstudio.console.alibabacloud.com/`, count chip "4 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `DASHSCOPE_API_KEY` [masked] — "Alibaba Cloud DashScope API key (Qwen + multi-provider models)". Link: `https://modelstudio.console.alibabacloud.com/`.
    - `DASHSCOPE_BASE_URL` [advanced] — "Custom DashScope base URL (default: coding-intl OpenAI-compat endpoint)".
    - `HERMES_QWEN_BASE_URL` [advanced] — "Qwen Portal base URL override (default: https://portal.qwen.ai/v1)".
    - `DASHSCOPE_CN_BASE_URL` [advanced] — "Alibaba Cloud DashScope (China) base URL override".
  - **"DeepSeek"** — row label "DeepSeek", "Get key" link → `https://platform.deepseek.com/api_keys`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `DEEPSEEK_API_KEY` [masked] — "DeepSeek API key for direct DeepSeek access". Link: `https://platform.deepseek.com/api_keys`.
    - `DEEPSEEK_BASE_URL` [advanced] — "Custom DeepSeek API base URL (advanced)".
  - **"Gemini"** — row label "Gemini", "Get key" link → `https://aistudio.google.com/app/apikey`, count chip "3 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `GOOGLE_API_KEY` [masked] [advanced] — "Google AI Studio API key (also recognized as GEMINI_API_KEY)". Link: `https://aistudio.google.com/app/apikey`.
    - `GEMINI_API_KEY` [masked] [advanced] — "Google AI Studio API key (alias for GOOGLE_API_KEY)". Link: `https://aistudio.google.com/app/apikey`.
    - `GEMINI_BASE_URL` [advanced] — "Google AI Studio base URL override".
  - **"GLM / Z.AI"** — row label "GLM / Z.AI", "Get key" link → `https://z.ai/`, count chip "4 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `GLM_API_KEY` [masked] [advanced] — "Z.AI / GLM API key (also recognized as ZAI_API_KEY / Z_AI_API_KEY)". Link: `https://z.ai/`.
    - `ZAI_API_KEY` [masked] [advanced] — "Z.AI API key (alias for GLM_API_KEY)". Link: `https://z.ai/`.
    - `Z_AI_API_KEY` [masked] [advanced] — "Z.AI API key (alias for GLM_API_KEY)". Link: `https://z.ai/`.
    - `GLM_BASE_URL` [advanced] — "Z.AI / GLM base URL override".
  - **"Hugging Face"** — row label "Hugging Face", "Get key" link → `https://huggingface.co/settings/tokens`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `HF_TOKEN` [masked] — "Hugging Face token for Inference Providers (20+ open models via router.huggingface.co)". Link: `https://huggingface.co/settings/tokens`.
    - `HF_BASE_URL` [advanced] — "Hugging Face Inference Providers base URL override".
  - **"Kimi / Moonshot"** — row label "Kimi / Moonshot", "Get key" link → `https://platform.moonshot.cn/`, count chip "4 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `KIMI_API_KEY` [masked] [advanced] — "Kimi / Moonshot API key". Link: `https://platform.moonshot.cn/`.
    - `KIMI_CN_API_KEY` [masked] [advanced] — "Kimi / Moonshot China API key". Link: `https://platform.moonshot.cn/`.
    - `KIMI_CODING_API_KEY` [masked] [advanced] — "kimi-coding API key". Link: `https://platform.moonshot.cn/`.
    - `KIMI_BASE_URL` [advanced] — "Kimi / Moonshot base URL override".
  - **"MiniMax"** — row label "MiniMax", "Get key" link → `https://www.minimax.io/`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `MINIMAX_API_KEY` [masked] [advanced] — "MiniMax API key (international)". Link: `https://www.minimax.io/`.
    - `MINIMAX_BASE_URL` [advanced] — "MiniMax base URL override".
  - **"MiniMax (China)"** — row label "MiniMax (China)", "Get key" link → `https://www.minimaxi.com/`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `MINIMAX_CN_API_KEY` [masked] [advanced] — "MiniMax API key (China endpoint)". Link: `https://www.minimaxi.com/`.
    - `MINIMAX_CN_BASE_URL` [advanced] — "MiniMax (China) base URL override".
  - **"OpenCode Go"** — row label "OpenCode Go", "Get key" link → `https://opencode.ai/auth`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `OPENCODE_GO_API_KEY` [masked] [advanced] — "OpenCode Go API key ($10/month subscription for open models)". Link: `https://opencode.ai/auth`.
    - `OPENCODE_GO_BASE_URL` [advanced] — "OpenCode Go base URL override".
  - **"OpenCode Zen"** — row label "OpenCode Zen", "Get key" link → `https://opencode.ai/auth`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `OPENCODE_ZEN_API_KEY` [masked] [advanced] — "OpenCode Zen API key (pay-as-you-go access to curated models)". Link: `https://opencode.ai/auth`.
    - `OPENCODE_ZEN_BASE_URL` [advanced] — "OpenCode Zen base URL override".
  - **"OpenRouter"** — row label "OpenRouter", "Get key" link → `https://openrouter.ai/keys`, count chip "1 key". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `OPENROUTER_API_KEY` [masked] [advanced] — "OpenRouter API key (for vision, web scraping helpers, and MoA)". Link: `https://openrouter.ai/keys`. Tools that need it: vision_analyze.
  - **"Xiaomi MiMo"** — row label "Xiaomi MiMo", "Get key" link → `https://platform.xiaomimimo.com`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `XIAOMI_API_KEY` [masked] — "Xiaomi MiMo API key for MiMo models (mimo-v2.5-pro, mimo-v2.5, mimo-v2-pro, mimo-v2-omni, mimo-v2-flash)". Link: `https://platform.xiaomimimo.com`.
    - `XIAOMI_BASE_URL` [advanced] — "Xiaomi MiMo base URL override (default: https://api.xiaomimimo.com/v1)".
  - **"Upstage Solar"** — row label "Upstage Solar", "Get key" link → `https://console.upstage.ai/api-keys`, count chip "2 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `UPSTAGE_API_KEY` [masked] — "Upstage API key for Solar LLM models". Link: `https://console.upstage.ai/api-keys`.
    - `UPSTAGE_BASE_URL` [advanced] — "Upstage base URL override (default: https://api.upstage.ai/v1)".
  - **"Other"** — row label "Other", "Get key" link → `https://console.x.ai/`, count chip "59 keys". Keys, in render order (API keys/tokens first, then base URLs, then the rest):
    - `XAI_API_KEY` [masked] [advanced] — "xAI API key". Link: `https://console.x.ai/`.
    - `NVIDIA_API_KEY` [masked] [advanced] — "NVIDIA NIM API key (build.nvidia.com or local NIM endpoint)". Link: `https://build.nvidia.com/`.
    - `LM_API_KEY` [masked] [advanced] — "LM Studio bearer token for auth-enabled local servers".
    - `STEPFUN_API_KEY` [masked] [advanced] — "StepFun Step Plan API key". Link: `https://platform.stepfun.com/`.
    - `ARCEEAI_API_KEY` [masked] [advanced] — "Arcee AI API key". Link: `https://chat.arcee.ai/`.
    - `GMI_API_KEY` [masked] [advanced] — "GMI Cloud API key". Link: `https://www.gmicloud.ai/`.
    - `ACTUAL_API_KEY` [masked] [advanced] — "Actual Computer inference key (ac_...)". Link: `https://actual.inc/user/keys`.
    - `FIREWORKS_API_KEY` [masked] [advanced] — "Fireworks AI API key". Link: `https://app.fireworks.ai/settings/users/api-keys`.
    - `COMMANDCODE_API_KEY` [masked] [advanced] — "CommandCode API key (GOAT/Pro/Max/Provider plans — 30+ models via one key)". Link: `https://commandcode.ai/studio/`.
    - `OLLAMA_API_KEY` [masked] [advanced] — "Ollama Cloud API key (ollama.com — cloud-hosted open models)". Link: `https://ollama.com/settings`.
    - `AZURE_FOUNDRY_API_KEY` [masked] — "Azure Foundry API key for custom Azure endpoints". Link: `https://ai.azure.com/`.
    - `AI_GATEWAY_API_KEY` [masked] [advanced] — "ai-gateway API key".
    - `ALIBABA_TOKEN_PLAN_API_KEY` [masked] [advanced] — "Alibaba Cloud (Token Plan) API key". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `ALIBABA_CODING_PLAN_API_KEY` [masked] [advanced] — "Alibaba Cloud (Coding Plan) API key". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `CLAUDE_CODE_OAUTH_TOKEN` [masked] [advanced] — "anthropic API key".
    - `DEEPINFRA_API_KEY` [masked] [advanced] — "DeepInfra API key". Link: `https://deepinfra.com/dash/api_keys`.
    - `KILOCODE_API_KEY` [masked] [advanced] — "kilocode API key".
    - `MODEL_API_KEY` [masked] [advanced] — "Meta Model API API key". Link: `https://developer.meta.com/ai/`.
    - `META_API_KEY` [masked] [advanced] — "Meta Model API API key". Link: `https://developer.meta.com/ai/`.
    - `META_MODEL_API_KEY` [masked] [advanced] — "Meta Model API API key". Link: `https://developer.meta.com/ai/`.
    - `NEBIUS_API_KEY` [masked] [advanced] — "Nebius Token Factory API key". Link: `https://tokenfactory.nebius.com/`.
    - `NEBIUS_TOKEN_FACTORY_API_KEY` [masked] [advanced] — "Nebius Token Factory API key". Link: `https://tokenfactory.nebius.com/`.
    - `NOVITA_API_KEY` [masked] [advanced] — "NovitaAI API key". Link: `https://novita.ai/settings/key-management`.
    - `RAMP_ROUTER_API_KEY` [masked] [advanced] — "Ramp Router API key". Link: `https://app.router.com/keys`.
    - `ROUTER_API_KEY` [masked] [advanced] — "Ramp Router API key". Link: `https://app.router.com/keys`.
    - `OPENAI_API_KEY` [masked] — "OpenAI API (api.openai.com, API key)".
    - `TOKENHUB_API_KEY` [masked] — "Tencent TokenHub (Hy4 preview via tokenhub.tencentmaas.com)".
    - `TOKENPLAN_API_KEY` [masked] — "Tencent TokenPlan (Hy4 preview via api.lkeap.cloud.tencent.com, Anthropic Messages)".
    - `COPILOT_GITHUB_TOKEN` [masked] — "GitHub Copilot (Uses GITHUB_TOKEN or gh auth token)".
    - `GH_TOKEN` [masked] — "GitHub Copilot (Uses GITHUB_TOKEN or gh auth token)".
    - `XAI_BASE_URL` [advanced] — "xAI base URL override".
    - `NVIDIA_BASE_URL` [advanced] — "NVIDIA NIM base URL override (e.g. http://localhost:8000/v1 for local NIM)".
    - `LM_BASE_URL` [advanced] — "LM Studio base URL override".
    - `STEPFUN_BASE_URL` [advanced] — "StepFun Step Plan base URL override".
    - `ARCEE_BASE_URL` [advanced] — "Arcee AI base URL override".
    - `GMI_BASE_URL` [advanced] — "GMI Cloud base URL override".
    - `ACTUAL_BASE_URL` [advanced] — "Actual Computer base URL override (set to http://127.0.0.1:8080 for the local offline daemon)".
    - `OLLAMA_BASE_URL` [advanced] — "Ollama Cloud base URL override (default: https://ollama.com/v1)".
    - `AZURE_FOUNDRY_BASE_URL` [advanced] — "Azure Foundry base URL (set via 'hermes model' for endpoint-specific config)".
    - `ALIBABA_TOKEN_PLAN_BASE_URL` [advanced] — "Alibaba Cloud (Token Plan) base URL override". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `ALIBABA_TOKEN_PLAN_CN_BASE_URL` [advanced] — "Alibaba Cloud (Token Plan, China) base URL override". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `ALIBABA_CODING_PLAN_BASE_URL` [advanced] — "Alibaba Cloud (Coding Plan) base URL override". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `ALIBABA_CODING_PLAN_CN_BASE_URL` [advanced] — "Alibaba Cloud (Coding Plan, China) base URL override". Link: `https://help.aliyun.com/zh/model-studio/`.
    - `COMMANDCODE_BASE_URL` [advanced] — "CommandCode base URL override". Link: `https://commandcode.ai/`.
    - `COMMANDCODE_ANTHROPIC_BASE_URL` [advanced] — "CommandCode (Anthropic) base URL override". Link: `https://commandcode.ai/`.
    - `DEEPINFRA_BASE_URL` [advanced] — "DeepInfra base URL override". Link: `https://deepinfra.com/dash/api_keys`.
    - `META_BASE_URL` [advanced] — "Meta Model API base URL override". Link: `https://developer.meta.com/ai/`.
    - `NEBIUS_BASE_URL` [advanced] — "Nebius Token Factory base URL override". Link: `https://tokenfactory.nebius.com/`.
    - `NOVITA_BASE_URL` [advanced] — "NovitaAI base URL override". Link: `https://novita.ai/settings/key-management`.
    - `RAMP_ROUTER_BASE_URL` [advanced] — "Ramp Router base URL override". Link: `https://app.router.com/keys`.
    - `OPENAI_BASE_URL` [advanced] — "OpenAI API base URL override".
    - `TOKENHUB_BASE_URL` [advanced] — "Tencent TokenHub base URL override".
    - `TOKENPLAN_BASE_URL` [advanced] — "Tencent TokenPlan base URL override".
    - `COPILOT_API_BASE_URL` [advanced] — "GitHub Copilot base URL override".
    - `KILOCODE_BASE_URL` [advanced] — "Kilo Code base URL override".
    - `AI_GATEWAY_BASE_URL` [advanced] — "Vercel AI Gateway base URL override".
    - `VERTEX_CREDENTIALS_PATH` [advanced] — "Path to a Google Cloud service account JSON for Vertex AI (Gemini). Vertex uses OAuth2, not a static API key — this points at the credentials Hermes mints short-lived tokens from. Falls back to GOOGLE_APPLICATION_CREDENTIALS, then to ADC (gcloud auth application-default login). Set project/region under vertex: in config.yaml.". Link: `https://cloud.google.com/iam/docs/keys-create-delete`.
    - `AWS_REGION` [advanced] — "AWS region for Bedrock API calls (e.g. us-east-1, eu-central-1)". Link: `https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html`.
    - `AWS_PROFILE` [advanced] — "AWS named profile for Bedrock authentication (from ~/.aws/credentials)".
- **Outputs / side effects:** Expanding a group is local state only; editing a row writes through `PUT /api/env`.
- **Config / env:** All 95 `provider`-category keys listed above.
- **Edge cases / guards:** Groups are collapsed on first paint, so the crawl sees 16 header buttons and no per-key controls until one is expanded. The "Other" bucket holds 59 keys — every provider without a prefix entry in `PROVIDER_GROUPS` (OpenAI, xAI, Vertex, Bedrock/AWS, Azure Foundry, Ollama, Fireworks, DeepInfra, Novita, Nebius, Meta, NVIDIA, StepFun, ArceeAI, GMI, Actual, LM, KiloCode, CommandCode, Copilot/GitHub, TokenHub, TokenPlan, Ramp Router, AI Gateway, Alibaba token/coding plans, …), which makes it by far the least usable card on the page.
- **Rebuild notes:** Derive the grouping from the API's own `provider` / `provider_label` fields (already returned per key) instead of a hard-coded prefix table — then "Other" disappears and new providers group themselves.

### Keys → provider group row (expanded)  `id: web-c.env.provider-group-row`
- **Surface:** Web dashboard
- **Where:** `/env` → "LLM PROVIDERS" → click any group header.
- **What it does:** Reveals that vendor's keys as compact editable rows.
- **How it works:** `ProviderGroupCard` renders each key with `<EnvVarRow compact>` (`EnvPage.tsx:426-479`).
- **Inputs / options:** Per unset key (compact row): the key name in monospace, its description in muted text (hidden below the `sm` breakpoint), an optional "Get key" link (i18n `env.getKey`) with an `ExternalLink` icon, and an outlined "Set" button (i18n `common.set`, `Pencil` icon). Per set key the row expands to the full form (see `web-c.env.var-row`).
- **Outputs / side effects:** Clicking "Set" opens the inline edit input for that key.
- **Config / env:** n/a
- **Edge cases / guards:** The group header's "Get key" link stops event propagation so it does not toggle the accordion (`EnvPage.tsx:417`).
- **Rebuild notes:** Two row densities (compact for unset, full for set/editing) keeps a 95-key page scannable; worth copying.

### Keys → env var row (full form)  `id: web-c.env.var-row`
- **Surface:** Web dashboard
- **Where:** `/env` → any section → a key that is set, or any key being edited.
- **What it does:** Shows a key's state and value, and provides reveal / replace / clear / save / cancel.
- **How it works:** `EnvVarRow` at `EnvPage.tsx:102-331`.
- **Inputs / options:**
  - Header: the key name as a monospace `<Label>`; a badge reading "Set" (success tone, i18n `common.set`) or "Not set" (outline tone, i18n `env.notSet`); an optional "Get key" link with an `ExternalLink` icon.
  - The key's `description` as a muted paragraph.
  - When the catalog lists dependent tools, one secondary badge per tool name (from `info.tools`).
  - Read mode: a bordered value box showing `redacted_value` (or the literal `---` when unset, and again `---` as the fallback when redaction is missing); when set, a ghost icon button toggling reveal — `title` is "Show real value" (i18n `env.showValue`) or "Hide value" (i18n `env.hideValue`) and `aria-label` is "Reveal `<KEY>`" / "Hide `<KEY>`", with `Eye`/`EyeOff` icons; an outlined button "Replace" (i18n `common.replace`) when set or "Set" when unset, `Pencil` icon; when set, an outlined destructive button "Clear" (i18n `common.clear`, `Trash2` icon) that shows "..." while the request is in flight.
  - Edit mode: an auto-focused `<Input type="text">` whose placeholder is either "Enter value..." (i18n `env.enterValue`) or, when replacing, "Replace current value ({preview})" (i18n `env.replaceCurrentValue`) with the redacted value spliced in; a "Save" button (`Save` icon, disabled while empty or saving, "..." while saving) and an outlined "Cancel" button (`X` icon).
- **Outputs / side effects:** Save → `PUT /api/env` `{key, value}`; local state optimistically flips `is_set` to true and sets `redacted_value` to the first four plus last four characters joined by "..."; toast "`<KEY>` saved". Reveal → `POST /api/env/reveal` `{key}` → `{key, value}`, held only in component state; clicking again hides it. Clear → confirm dialog then `DELETE /api/env` `{key}` → toast "`<KEY>` removed" and the row is pruned by `removeDeletedEnvVarFromState()` (`web/src/lib/env-state.ts`).
- **Config / env:** The key itself in `.env`.
- **Edge cases / guards:** Save errors toast "Failed to save `<KEY>`: `<e>`"; reveal errors toast "Failed to reveal `<KEY>`"; delete errors toast "Failed to remove `<KEY>`: `<e>`" and re-throw. Editing is keyed by the presence of the key in the `edits` map, so an empty string means "editing with a blank field", not "no edit". Revealed plaintext is `select-all` styled and stays in memory until toggled off or the row is saved/cleared.
- **Rebuild notes:** Never ship the plaintext in the list payload — a dedicated reveal endpoint (as here) keeps secrets out of the initial page load and gives the server an audit point.

### Keys → clear-key confirmation  `id: web-c.env.clear-confirm`
- **Surface:** Web dashboard
- **Where:** `/env` → any set key → "Clear" → dialog titled "Clear this key?" (i18n `env.confirmClearTitle`).
- **What it does:** Guards the destructive removal of a stored secret.
- **How it works:** `EnvPage.tsx:891-901` with `useConfirmDelete`.
- **Inputs / options:** Dialog description is "`<KEY>` — `<description>`. The stored value for this variable will be removed from your .env file. This cannot be undone from the UI." (the key/description prefix is dropped when the pending key is unknown, leaving just i18n `env.confirmClearMessage`). Cancel / destructive confirm buttons come from `DeleteConfirmDialog`.
- **Outputs / side effects:** `DELETE /api/env` `{key}`.
- **Config / env:** n/a
- **Edge cases / guards:** While the dialog is open every row's Clear button is disabled (`clearDialogOpen` is threaded down to each row).
- **Rebuild notes:** Naming the key *and* its purpose in the confirm text is the right level of friction for secret deletion.

### Keys → category cards ("KEYS", "GATEWAY", "CONFIG")  `id: web-c.env.category-cards`
- **Surface:** Web dashboard
- **Where:** `/env` → three cards after the providers card, anchors `#section-tool`, `#section-messaging`, `#section-setting`.
- **What it does:** Groups the non-provider env vars into tool keys, gateway-wide messaging settings, and general settings.
- **How it works:** `EnvCategoryCard` at `EnvPage.tsx:1011-1108`; the section list is built at `:834-869`.
- **Inputs / options — per card:** an icon (`tool` → `KeyRound`, `messaging` → `MessageSquare`, `setting` → `Settings`); a title from `CATEGORY_META_LABELS` = `{tool: "Keys", messaging: "Gateway", setting: "Config"}`; a description "`<set>` of `<total>` configured" (i18n `common.of` / `common.configured`); for the messaging card an extra tertiary hint (i18n `common.gatewayHint`): "Messaging platforms, the API server and webhooks are configured on the Channels page. These are gateway-wide settings (proxy/relay mode and the global allowlist)."; a "Show more"/"Show less" text button (i18n `env.showMore` / `env.showLess`, `aria-expanded`) rendered only when unset keys exist. Set keys always render as full rows; unset keys render only while expanded.
- **Outputs / side effects:** Same row semantics as `web-c.env.var-row`.
- **Config / env:** The keys enumerated in the three entries below.
- **Edge cases / guards:** `showAll` initialises to `true` when nothing in the section is configured, so a fresh install shows every row expanded (the live crawl therefore contains 39 + 69 + 3 "Set" buttons). A card with zero entries is skipped entirely.
- **Rebuild notes:** "Show only what is configured, expandable to everything" is the right default for a 200-row settings surface.

### Keys → "KEYS" card contents (tool keys)  `id: web-c.env.tools-keys`
- **Surface:** Web dashboard
- **Where:** `/env` → card titled "Keys" (heading renders uppercase "KEYS"), anchor `#section-tool`, jump-nav button "TOOLS".
- **What it does:** Holds the 39 tool/service credentials the agent's tools read.
- **How it works:** All `/api/env` entries with `category: "tool"` (none are `channel_managed`).
- **Inputs / options — every key, in API order:**
  - `EXA_API_KEY` [masked] — "Exa API key for AI-native web search and contents". Link: `https://exa.ai/`. Tools: web_search, web_extract.
  - `PARALLEL_API_KEY` [masked] — "Parallel API key for AI-native web search and extract". Link: `https://parallel.ai/`. Tools: web_search, web_extract.
  - `FIRECRAWL_API_KEY` [masked] — "Firecrawl API key for web search and scraping". Link: `https://firecrawl.dev/`. Tools: web_search, web_extract.
  - `FIRECRAWL_API_URL` [advanced] — "Firecrawl API URL for self-hosted instances (optional)".
  - `FIRECRAWL_GATEWAY_URL` [advanced] — "Exact Firecrawl tool-gateway origin override for Nous Subscribers only (optional)".
  - `TOOL_GATEWAY_DOMAIN` [advanced] — "Shared tool-gateway domain suffix for Nous Subscribers only, used to derive vendor hosts, e.g. nousresearch.com -> firecrawl-gateway.nousresearch.com".
  - `TOOL_GATEWAY_SCHEME` [advanced] — "Shared tool-gateway URL scheme for Nous Subscribers only, used to derive vendor hosts (`https` by default, set `http` for local gateway testing)".
  - `TOOL_GATEWAY_USER_TOKEN` [masked] [advanced] — "Explicit Nous Subscriber access token for tool-gateway requests (optional; otherwise read from the Hermes auth store)".
  - `KEENABLE_API_KEY` [masked] — "Keenable API key for fast independent-index web search and page fetch (optional — keyless free tier works without it)". Link: `https://keenable.ai`. Tools: web_search, web_extract.
  - `SEARXNG_URL` — "URL of your SearXNG instance for free self-hosted web search". Link: `https://searxng.github.io/searxng/`. Tools: web_search.
  - `BRAVE_SEARCH_API_KEY` [masked] — "Brave Search API subscription token (free tier: 2,000 queries/mo)". Link: `https://brave.com/search/api/`. Tools: web_search.
  - `BROWSERBASE_API_KEY` [masked] — "Browserbase API key for cloud browser (optional — local browser works without this)". Link: `https://browserbase.com/`. Tools: browser_navigate, browser_click.
  - `BROWSERBASE_PROJECT_ID` — "Browserbase project ID (optional — only needed for cloud browser)". Link: `https://browserbase.com/`. Tools: browser_navigate, browser_click.
  - `BROWSER_USE_API_KEY` [masked] — "Browser Use API key for cloud browser (optional — local browser works without this)". Link: `https://browser-use.com/`. Tools: browser_navigate, browser_click.
  - `FIRECRAWL_BROWSER_TTL` — "Firecrawl browser session TTL in seconds (optional, default 300)". Tools: browser_navigate, browser_click.
  - `AGENT_BROWSER_ENGINE` [advanced] — "Local browser engine: auto (default Chrome), lightpanda (faster, no screenshots; Browser Use mode spawns lightpanda serve), chrome". Link: `https://lightpanda.io/docs/run-locally/installation/one-liner`. Tools: browser_exec, browser_navigate, browser_snapshot, browser_click, browser_vision.
  - `CAMOFOX_URL` — "Camofox browser server URL for local anti-detection browsing (e.g. http://localhost:9377)". Link: `https://github.com/jo-inc/camofox-browser`. Tools: browser_navigate, browser_click.
  - `CAMOFOX_API_KEY` [masked] [advanced] — "Optional bearer token sent as Authorization header to a remote/authenticated Camofox server". Link: `https://github.com/jo-inc/camofox-browser`. Tools: browser_navigate, browser_click.
  - `FAL_KEY` [masked] — "FAL API key for image and video generation". Link: `https://fal.ai/`. Tools: image_generate, video_generate.
  - `KREA_API_KEY` [masked] — "Krea API key for Krea 2 image generation (Medium + Large)". Link: `https://www.krea.ai/settings/api-tokens`. Tools: image_generate.
  - `VOICE_TOOLS_OPENAI_KEY` [masked] — "OpenAI API key for voice transcription (Whisper) and OpenAI TTS". Link: `https://platform.openai.com/api-keys`. Tools: voice_transcription, openai_tts.
  - `ELEVENLABS_API_KEY` [masked] — "ElevenLabs API key for premium text-to-speech voices and Scribe transcription". Link: `https://elevenlabs.io/`. Tools: elevenlabs_tts, voice_transcription.
  - `MISTRAL_API_KEY` [masked] — "Mistral API key for Voxtral TTS and transcription (STT)". Link: `https://console.mistral.ai/`.
  - `PORCUPINE_ACCESS_KEY` [masked] — "Picovoice access key for the Porcupine 'Hey Hermes' wake word engine (optional; openWakeWord is the free default)". Link: `https://console.picovoice.ai/`.
  - `GITHUB_TOKEN` [masked] — "GitHub token for Skills Hub (higher API rate limits, skill publish)". Link: `https://github.com/settings/tokens`.
  - `HONCHO_API_KEY` [masked] — "Honcho API key for AI-native persistent memory". Link: `https://app.honcho.dev`. Tools: honcho_context.
  - `HONCHO_BASE_URL` — "Base URL for self-hosted Honcho instances (no API key needed)".
  - `HINDSIGHT_API_KEY` [masked] — "Hindsight API key for graph-aware persistent memory". Link: `https://hindsight.vectorize.io`. Tools: hindsight_recall.
  - `HINDSIGHT_API_URL` [advanced] — "Base URL for the Hindsight API (default: https://api.hindsight.vectorize.io)".
  - `SUPERMEMORY_API_KEY` [masked] — "Supermemory API key for conversation-scoped persistent memory". Link: `https://supermemory.ai`. Tools: supermemory_search.
  - `MEM0_API_KEY` [masked] — "Mem0 Platform API key for semantic persistent memory". Link: `https://app.mem0.ai`. Tools: mem0_search.
  - `RETAINDB_API_KEY` [masked] — "RetainDB API key for persistent memory". Link: `https://retaindb.com`. Tools: retaindb_search.
  - `RETAINDB_BASE_URL` [advanced] — "Base URL for self-hosted RetainDB instances (default: https://api.retaindb.com)".
  - `BRV_API_KEY` [masked] — "ByteRover API key (optional, for cloud sync — local-first by default)". Link: `https://app.byterover.dev`. Tools: brv_query.
  - `OPENVIKING_API_KEY` [masked] — "OpenViking API key (leave blank for local dev mode)". Tools: viking_search.
  - `OPENVIKING_ENDPOINT` [advanced] — "OpenViking server URL (default: http://127.0.0.1:1933)".
  - `HERMES_LANGFUSE_PUBLIC_KEY` — "Langfuse project public key (pk-lf-...)". Link: `https://cloud.langfuse.com`.
  - `HERMES_LANGFUSE_SECRET_KEY` [masked] — "Langfuse project secret key (sk-lf-...)". Link: `https://cloud.langfuse.com`.
  - `HERMES_LANGFUSE_BASE_URL` [advanced] — "Langfuse server URL (default: https://cloud.langfuse.com)".
- **Outputs / side effects:** Set/replace/clear/reveal per row (see `web-c.env.var-row`).
- **Config / env:** These 39 keys in `.env`.
- **Edge cases / guards:** `AGENT_BROWSER_ENGINE`, `FIRECRAWL_BROWSER_TTL`, `SEARXNG_URL`, `HONCHO_BASE_URL`, `HINDSIGHT_API_URL`, `RETAINDB_BASE_URL`, `OPENVIKING_ENDPOINT`, `FIRECRAWL_API_URL`, `FIRECRAWL_GATEWAY_URL`, `TOOL_GATEWAY_DOMAIN`, `TOOL_GATEWAY_SCHEME` and `HERMES_LANGFUSE_BASE_URL` are configuration rather than secrets, yet share the same masked/reveal row chrome when flagged `is_password`.
- **Rebuild notes:** The `tools[]` array per key (rendered as badges) is what lets a user see *which tool stops working* without a key — keep that link.

### Keys → "GATEWAY" card contents (cross-cutting messaging settings)  `id: web-c.env.gateway-keys`
- **Surface:** Web dashboard
- **Where:** `/env` → card titled "Gateway" (heading "GATEWAY"), anchor `#section-messaging`, jump-nav button "GATEWAY".
- **What it does:** Holds the 69 messaging-category env vars that are **not** owned by a Channels platform card — home-channel pointers, allow-all switches, mention/thread policies and the gateway proxy/relay settings.
- **How it works:** All `/api/env` entries with `category: "messaging"` and `channel_managed: false`. The other 129 messaging keys are hidden here because they appear on a Channels platform card.
- **Inputs / options — every key, in API order:**
  - `TELEGRAM_PROXY` — "Proxy URL for Telegram connections (overrides HTTPS_PROXY). Supports http://, https://, socks5://".
  - `DISCORD_REPLY_TO_MODE` — "Discord reply threading mode: 'off' (no reply references), 'first' (reply on first message only, default), 'all' (reply on every chunk)".
  - `MATTERMOST_REQUIRE_MENTION` — "Require @mention in Mattermost channels (default: true). Set to false to respond to all messages.".
  - `MATTERMOST_FREE_RESPONSE_CHANNELS` — "Comma-separated Mattermost channel IDs where bot responds without @mention".
  - `MATRIX_REQUIRE_MENTION` [advanced] — "Require @mention in Matrix rooms (default: true). Set to false to respond to all messages.".
  - `MATRIX_FREE_RESPONSE_ROOMS` [advanced] — "Comma-separated Matrix room IDs where bot responds without @mention".
  - `MATRIX_AUTO_THREAD` [advanced] — "Auto-create threads for messages in Matrix rooms (default: true)".
  - `MATRIX_DM_AUTO_THREAD` [advanced] — "Auto-create threads for DM messages in Matrix (default: false)".
  - `BLUEBUBBLES_ALLOW_ALL_USERS` — "Allow all BlueBubbles users without allowlist".
  - `QQ_ALLOW_ALL_USERS` — "Allow all QQ users without an allowlist (true/false)".
  - `QQBOT_HOME_CHANNEL` — "Default QQ channel/group for cron delivery and notifications".
  - `QQBOT_HOME_CHANNEL_NAME` — "Display name for the QQ home channel".
  - `GATEWAY_ALLOW_ALL_USERS` [advanced] — "Allow all users to interact with messaging bots (true/false). Default: false.".
  - `GATEWAY_PROXY_URL` [advanced] — "URL of a remote Hermes API server to forward messages to (proxy mode). When set, the gateway handles platform I/O only — all agent work is delegated to the remote server. Use for Docker E2EE containers that relay to a host agent. Also configurable via gateway.proxy_url in config.yaml.".
  - `GATEWAY_PROXY_KEY` [masked] [advanced] — "Bearer token for authenticating with the remote Hermes API server (proxy mode). Must match the API_SERVER_KEY on the remote host.".
  - `IRC_ALLOW_ALL_USERS` — "Allow anyone in the channel to talk to the bot (dev only)".
  - `IRC_HOME_CHANNEL` — "Channel for cron / notification delivery (defaults to IRC_CHANNEL)".
  - `TEAMS_ALLOW_ALL_USERS` — "Allow any Teams user to trigger the bot (dev only)".
  - `TEAMS_HOME_CHANNEL` — "Default chat/channel ID for cron / notification delivery".
  - `TEAMS_HOME_CHANNEL_NAME` — "Display name for the Teams home channel".
  - `DISCORD_ALLOW_ALL_USERS` — "Allow any Discord user to trigger the bot (dev only)".
  - `DISCORD_HOME_CHANNEL` — "Default channel ID for cron / notification delivery".
  - `DISCORD_HOME_CHANNEL_NAME` — "Display name for the Discord home channel".
  - `MATTERMOST_ALLOW_ALL_USERS` — "Allow any Mattermost user to trigger the bot (dev only)".
  - `MATTERMOST_HOME_CHANNEL` — "Default channel ID for cron / notification delivery".
  - `MATTERMOST_REPLY_MODE` — "How replies are sent: 'thread' (nested) or 'off' (flat). Default: off.".
  - `MATTERMOST_ALLOWED_CHANNELS` — "If set, the bot only responds in these channels (whitelist).".
  - `NTFY_ALLOW_ALL_USERS` — "Allow any topic to talk to the bot (dev only — disables allowlist)".
  - `NTFY_HOME_CHANNEL` — "Default topic for cron / notification delivery".
  - `NTFY_HOME_CHANNEL_NAME` — "Human label for the home channel (defaults to the topic name)".
  - `SMS_ALLOWED_USERS` — "Comma-separated phone numbers allowed to talk to the bot".
  - `SMS_HOME_CHANNEL` — "Default phone number for cron / notification delivery".
  - `GOOGLE_CHAT_HOME_CHANNEL` — "Default space for cron / notification delivery (e.g. spaces/AAAA...).".
  - `FEISHU_ALLOW_ALL_USERS` — "Allow any Feishu user to trigger the bot (dev only)".
  - `FEISHU_HOME_CHANNEL` — "Default chat ID for cron / notification delivery".
  - `FEISHU_HOME_CHANNEL_NAME` — "Display name for the Feishu home channel".
  - `TELEGRAM_ALLOW_ALL_USERS` — "Allow any Telegram user to trigger the bot (dev only)".
  - `TELEGRAM_HOME_CHANNEL` — "Default chat ID for cron / notification delivery".
  - `TELEGRAM_HOME_CHANNEL_NAME` — "Display name for the Telegram home channel".
  - `DINGTALK_HOME_CHANNEL` — "Default conversation ID for cron / notification delivery".
  - `DINGTALK_HOME_CHANNEL_NAME` — "Display name for the DingTalk home channel".
  - `WECOM_WEBSOCKET_URL` — "WeCom Smart Robot WebSocket URL".
  - `WECOM_HOME_CHANNEL` — "Default chat ID for cron / notification delivery".
  - `WECOM_ALLOWED_USERS` — "Comma-separated WeCom user IDs allowed to talk to the bot".
  - `A2A_ALLOW_ALL_USERS` — "Allow any authenticated A2A peer to reach the agent (dev only).".
  - `A2A_HOME_CHANNEL` — "Task/context id used as the cron / notification delivery target for deliver=a2a.".
  - `WHATSAPP_ALLOW_ALL_USERS` — "Allow any WhatsApp user to trigger the bot (dev only)".
  - `WHATSAPP_HOME_CHANNEL` — "Default chat ID for cron / notification delivery".
  - `WHATSAPP_HOME_CHANNEL_NAME` — "Display name for the WhatsApp home channel".
  - `MATRIX_ALLOW_ALL_USERS` — "Allow any Matrix user to trigger the bot (dev only)".
  - `MATRIX_HOME_CHANNEL` — "Default room ID for cron / notification delivery".
  - `MATRIX_HOME_CHANNEL_NAME` — "Display name for the Matrix home room".
  - `EMAIL_HOME_ADDRESS` — "Default address for cron / notification delivery".
  - `PHOTON_ALLOW_ALL_USERS` — "Allow any sender to trigger the bot (dev only — disables allowlist)".
  - `PHOTON_REQUIRE_MENTION` — "Ignore group-chat messages unless they match a mention wake word (true/false, default false)".
  - `PHOTON_HOME_CHANNEL` — "Default Photon target for cron / notification delivery: Spectrum space id, DM GUID, or bare E.164 phone number".
  - `PHOTON_HOME_CHANNEL_NAME` — "Human label for the home channel".
  - `SLACK_ALLOW_ALL_USERS` — "Allow any Slack user to trigger the bot (dev only)".
  - `SLACK_HOME_CHANNEL` — "Default channel ID for cron / notification delivery (starts with C)".
  - `SLACK_HOME_CHANNEL_NAME` — "Display name for the Slack home channel".
  - `SLACK_THREAD_REQUIRE_MENTION` — "Require an explicit @mention for Slack thread replies while preserving top-level free response channels".
  - `LINE_ALLOW_ALL_USERS` — "Allow any LINE user to talk to the bot (dev only — disables allowlist)".
  - `LINE_HOME_CHANNEL` — "Default user/group/room ID for cron / notification delivery".
  - `BUZZ_HOME_CHANNEL` — "Channel UUID for cron / notification delivery (defaults to the first watched channel)".
  - `BUZZ_ALLOW_ALL_USERS` — "Allow any community member to talk to the agent (true/false)".
  - `SIMPLEX_ALLOW_ALL_USERS` — "Allow any contact to talk to the bot (dev only — disables allowlist)".
  - `SIMPLEX_HOME_CHANNEL` — "Default contact/group ID for cron / notification delivery".
  - `SIMPLEX_HOME_CHANNEL_NAME` — "Human label for the home channel (defaults to the ID)".
  - `HERMES_SIMPLEX_TEXT_BATCH_DELAY` — "Quiet-period seconds (default: 0.8) used to concatenate rapid-fire inbound text messages into a single MessageEvent — same pattern as Telegram's text batching.".
- **Outputs / side effects:** Set/replace/clear/reveal per row.
- **Config / env:** These 69 keys in `.env`.
- **Edge cases / guards:** The card hint explicitly redirects platform credentials to the Channels page. `GATEWAY_ALLOW_ALL_USERS`, `GATEWAY_PROXY_URL` and `GATEWAY_PROXY_KEY` are the genuinely gateway-wide ones; the rest are per-platform behaviour flags that simply were not claimed by a platform card.
- **Rebuild notes:** The split between "credential" (Channels) and "behaviour" (Keys) is derived from `channel_managed`, which is itself derived from each platform's `env_vars` list — so adding a key to a platform card automatically removes it from here. Keep that single source.

### Keys → "CONFIG" card contents (general settings)  `id: web-c.env.settings-keys`
- **Surface:** Web dashboard
- **Where:** `/env` → card titled "Config" (heading "CONFIG"), anchor `#section-setting`, jump-nav button "SETTINGS".
- **What it does:** Holds the three general-purpose `setting`-category env vars.
- **How it works:** All `/api/env` entries with `category: "setting"` and `channel_managed: false` (one of the four `setting` keys is channel-managed and therefore hidden).
- **Inputs / options — every key:**
  - `SUDO_PASSWORD` [masked] — "Sudo password for terminal commands requiring root access; set to an explicit empty string to try empty without prompting".
  - `HERMES_PREFILL_MESSAGES_FILE` — "Path to JSON file with ephemeral prefill messages for few-shot priming".
  - `HERMES_EPHEMERAL_SYSTEM_PROMPT` — "Ephemeral system prompt injected at API-call time (never persisted to sessions)".
- **Outputs / side effects:** Set/replace/clear/reveal per row.
- **Config / env:** These three keys in `.env`.
- **Edge cases / guards:** `SUDO_PASSWORD` is a masked row like any other secret; there is no extra confirmation for storing a sudo password in plaintext `.env`.
- **Rebuild notes:** Treat OS-credential keys as a distinct, louder class than API keys.

### Keys → "CUSTOM KEYS" card  `id: web-c.env.custom-keys`
- **Surface:** Web dashboard
- **Where:** `/env` → last card, anchor `#section-custom`. Title "Custom Keys" (i18n `env.customTitle`, `KeyRound` icon); description "`<n>` custom key(s) set" (i18n `env.customConfigured`, "{count} custom key{s} set"); hint "Arbitrary environment variables stored in your .env that Hermes doesn't recognise. Use these to inject env vars for skills, MCP servers, or your own tooling." (i18n `env.customHint`).
- **What it does:** Lists env vars present in `.env` that match no catalog entry, and lets the user add new arbitrary variables.
- **How it works:** `CustomKeysCard` at `EnvPage.tsx:495-593`. Entries are the `/api/env` rows with `category: "custom"` and `channel_managed: false`, sorted alphabetically (`:869-872`). `handleAddKey()` (`:778-799`) does **not** call the API: it inserts a synthetic unset row into local state (`{is_set:false, redacted_value:null, description:"", url:null, category:"custom", is_password:true, tools:[], advanced:false, custom:true}`) and opens it for editing; the value is only persisted when the user types one and presses Save, which uses the normal `PUT /api/env` path.
- **Inputs / options:** Existing custom keys render as full `EnvVarRow`s. The add form is a dashed-border block with the label "Add a custom key" (i18n `env.addCustomKey`), an `<Input>` whose `aria-label` is "Variable name" (i18n `env.customKeyName`) and whose placeholder is "e.g. MY_SERVICE_API_KEY" (i18n `env.customKeyNamePlaceholder`), Enter to submit, and a primary "Add" button (i18n `env.add`, `Plus` icon).
- **Outputs / side effects:** After Save, the backend surfaces the key back as a custom row so it survives a reload.
- **Config / env:** Arbitrary keys in `.env`.
- **Edge cases / guards:** The typed name is trimmed and **upper-cased** before validation. It must match `ENV_VAR_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/` (a mirror of `hermes_cli/config.py::_ENV_VAR_NAME_RE`); a non-empty invalid name shows the destructive helper "Use letters, numbers and underscores only (must start with a letter or underscore)." (i18n `env.invalidKeyName`) and the "Add" button stays disabled. Adding a name already being edited is a no-op. In the live crawl the "Add" button renders `disabled` because the field is empty.
- **Rebuild notes:** Deferring the write until a value exists avoids littering `.env` with empty keys; upper-casing on the client matches shell convention but silently rewrites the user's input, which is worth signalling.

### Keys → plugin slots  `id: web-c.env.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `/env` — extension points at the very top and very bottom of the page.
- **What it does:** Lets a dashboard plugin add UI to the Keys page.
- **How it works:** `<PluginSlot name="env:top" />` (`EnvPage.tsx:888`) and `<PluginSlot name="env:bottom" />` (`:986`).
- **Inputs / options:** Slot names `env:top`, `env:bottom`.
- **Outputs / side effects:** Whatever the plugin renders.
- **Config / env:** n/a
- **Edge cases / guards:** Same plugin load/registration failure strings as the Config page.
- **Rebuild notes:** A plugin that adds its own secret should register here rather than forking the page.

---

## 8. System page (`/system`)

### System page  `id: web-c.system.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `SYSTEM` (href `/system`, i18n `app.system`); page `<h1>` "System". Nine sections in this order: "Host", "Nous Portal", "Skill curator", "Gateway", "Memory", "Credential pool", "Operations", "Checkpoints", "Shell hooks".
- **What it does:** The admin panel: host metrics and Hermes updates, Nous Portal status, the skill curator, gateway start/stop/restart, built-in memory files, a rotating credential pool, one-click maintenance operations (doctor, audit, backup/restore, dumps, debug share), rollback checkpoints, and shell hooks.
- **How it works:** `web/src/pages/SystemPage.tsx:193`. `loadAll()` (`:256-286`) fires nine requests with `Promise.allSettled` so a single failure never blanks the page: `GET /api/status`, `GET /api/system/stats`, `GET /api/memory`, `GET /api/credentials/pool`, `GET /api/ops/checkpoints`, `GET /api/ops/hooks`, `GET /api/curator`, `GET /api/portal`, and a *cached* `GET /api/hermes/update/check`. Long-running work is spawned server-side as a named "action" whose stdout is tailed by `ActionLogViewer`.
- **Inputs / options:** Everything enumerated in the section entries below.
- **Outputs / side effects:** Spawns child processes, writes backups, restores archives, edits `config.yaml` hooks, deletes memory files and checkpoints, uploads debug pastes.
- **Config / env:** `curator.*`, hooks in `config.yaml`, credential pool storage, `MEMORY.md` / `USER.md` in the Hermes home.
- **Edge cases / guards:** Whole page is a `Spinner` until every settled promise resolves. Every destructive action goes through a `ConfirmDialog` / `DeleteConfirmDialog`.
- **Rebuild notes:** The "spawn a named action, tail its log over HTTP polling" pattern (`POST /api/ops/<x>` → `{name}`, then `GET /api/actions/<name>/status?lines=N`) is the backbone of this page; implement that first and every operation becomes three lines.

### System → live action log viewer  `id: web-c.system.action-log`
- **Surface:** Web dashboard
- **Where:** `/system` → appears as a card at the top of the page whenever an action is running (doctor, security audit, backup, import, skills update, checkpoint prune, gateway start/stop/restart, config migrate, prompt size, support dump, hermes update).
- **What it does:** Streams the spawned command's output and its exit status.
- **How it works:** `ActionLogViewer` at `SystemPage.tsx:99-163`. Polls `GET /api/actions/<name>/status?lines=400` every **1200 ms** while `running` is true; stops on exit and calls `onComplete(action, exit_code)`.
- **Inputs / options:** A close button with `aria-label="Close log"` (`X` icon).
- **Outputs / side effects:** Renders the action name in monospace, a badge "running" (warning) while live, then "done" (success) when `exit_code === 0` or "exit `<code>`" (destructive) otherwise; the tail itself in a scrollable `<pre>` (max height 288 px), showing the literal "Starting…" until the first lines arrive.
- **Config / env:** n/a
- **Edge cases / guards:** A fetch error stops the poll and flips the badge out of "running" without an exit code. `onComplete` fires exactly once (guarded by a ref) — the backup flow uses it to enable the download button only on a zero exit.
- **Rebuild notes:** Polling a bounded tail is simpler and more restart-tolerant than a websocket here; keep the once-only completion callback.

### System → "Host" section  `id: web-c.system.host`
- **Surface:** Web dashboard
- **Where:** `/system` → first section, heading "Host" (`Server` icon).
- **What it does:** Shows host and runtime facts plus the Hermes version and update state.
- **How it works:** `SystemPage.tsx:822-956`, fed by `GET /api/system/stats` (`SystemStats`) and the cached update check.
- **Inputs / options / displayed fields (each with a small uppercase caption):** "OS" (`os` + `os_release`), "ARCH" (`arch`), "HOST" (`hostname`), "PYTHON" (`python_impl` + `python_version`), "HERMES" (`v<hermes_version>` plus an update badge), "CPU" (`Cpu` icon; "`<n>` cores" and, when available, " · `<pct>`%"), "MEMORY" (used / total and percent, rendered with `formatBytes`), "DISK" (`HardDrive` icon; used / total and percent), "UPTIME" (`formatDuration`: `<d>d <h>h <m>m`, `<h>h <m>m`, or `<m>m`), "LOAD AVG" (three numbers to two decimals joined by " / ").
- **Outputs / side effects:** Display only, plus the two update buttons below.
- **Config / env:** n/a
- **Edge cases / guards:** When `psutil` is absent the note "Install the psutil extra for CPU / memory / disk metrics." replaces those metrics. `MEMORY`, `DISK`, `UPTIME` and `LOAD AVG` rows are omitted entirely when the corresponding field is missing. The whole update sub-row is hidden when `status.can_update_hermes === false`.
- **Rebuild notes:** `formatBytes` uses 1024-based units with one decimal (B / KB / MB / GB); `formatDuration` drops zero-valued leading units. Reuse both.

### System → "Check for updates" / "Update now"  `id: web-c.system.update`
- **Surface:** Web dashboard
- **Where:** `/system` → "Host" card footer (above a top border). Ghost button "Check for updates" (`RotateCw` icon → `Spinner`); primary button "Update now" (`Download` icon) appears only when an update is available *and* applicable.
- **What it does:** Re-checks the release feed and, when possible, runs `hermes update` and restarts the gateway.
- **How it works:** `checkForUpdate(force)` (`SystemPage.tsx:513-543`) → `GET /api/hermes/update/check[?force=true]` → `UpdateCheckResponse {update_available, behind, can_apply, update_command, message, …}`. `applyUpdate()` (`:545-569`) → `POST /api/hermes/update` → `ActionResponse`, then tails the action.
- **Inputs / options:** Two buttons; a confirm dialog on "Update now".
- **Outputs / side effects:** Version badge in the Host grid: warning badge "`<n>` behind" (or "update available" when `behind` is 0/absent) when an update exists, success badge "latest" when `behind === 0`. Forced checks toast "Update available — `<n>` commits behind" / "Update available" / "You're on the latest version" / the server's `message`. Confirm dialog title "Update Hermes?"; description is either "This will run 'hermes update' (`<update_command>`) and pull `<n>` new commits. The gateway restarts when the update finishes; the current session keeps its prompt cache until then." or "This will run 'hermes update' (`<update_command>`) and restart the gateway when it finishes."; confirm label "Update now". Applying toasts "Update started" and opens the action log.
- **Config / env:** n/a
- **Edge cases / guards:** When `can_apply` is false but an update exists, the buttons are replaced by the hint "Update with `<update_command>`". When `can_update_hermes === false` the whole block is hidden and `applyUpdate()` short-circuits with the toast "Hermes updates are managed outside this dashboard." A non-ok response toasts the server `message` or "Updates don't apply from this dashboard." Check failures toast "Update check failed: `<e>`"; apply failures "Update failed: `<e>`". The live crawl (a git checkout) showed the badge "5333 behind".
- **Rebuild notes:** Separating "an update exists" from "this install can apply it" (`can_apply` / `can_update_hermes`) is what makes the page honest on package-manager installs.

### System → "Nous Portal" section  `id: web-c.system.portal`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Nous Portal" (`Globe` icon).
- **What it does:** Shows Nous Portal login state, the active inference provider, and which capabilities the Tool Gateway routes.
- **How it works:** `SystemPage.tsx:958-1006`, fed by `GET /api/portal` → `PortalStatus {logged_in, provider, subscription_url, features[{label, state}]}`.
- **Inputs / options:** A badge reading "logged in" (success) or "not logged in" (secondary); the line "inference provider: `<provider>`" when set; a right-aligned link "Manage subscription" → `portal.subscription_url` or the fallback `https://portal.nousresearch.com/manage-subscription`; a "TOOL GATEWAY ROUTING" list of `label` → `state` rows.
- **Outputs / side effects:** Display + one external link.
- **Config / env:** Portal credentials live outside this page (set by `hermes portal`).
- **Edge cases / guards:** When not logged in, the footnote "Log in with `hermes portal`." appears. The feature list is hidden when empty. Live example rows: "Web tools / not configured", "Image generation / not configured", "Video generation / not configured", "OpenAI TTS / Edge TTS", "Speech-to-text / not configured", "Browser automation / Local browser", "Modal execution / local".
- **Rebuild notes:** A per-capability routing table (what runs locally vs through the subscription) is far more useful than a single "subscribed" flag.

### System → "Skill curator" section  `id: web-c.system.curator`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Skill curator" (`Sparkles` icon).
- **What it does:** Shows and controls the background job that reviews and prunes the agent's skills.
- **How it works:** `SystemPage.tsx:1008-1043`; `GET /api/curator` → `CuratorStatus {enabled, paused, interval_hours, last_run_at}`. `toggleCuratorPaused()` (`:309-318`) → `PUT /api/curator/paused` `{paused}`. "Run now" → `POST /api/curator/run` via the shared `runOp()` helper (`:384-393`).
- **Inputs / options:** Status badge — "paused" (warning) when paused, "active" (success) when enabled, "disabled" (secondary) otherwise; a schedule line "every `<n>`h" plus " · last run `<localised timestamp>`" or " · never run"; ghost button "Pause"/"Resume"; ghost button "Run now" (`Play` icon).
- **Outputs / side effects:** Toasts "Curator paused" / "Curator resumed"; failures toast "Curator toggle failed: `<e>`". "Run now" toasts "Curator review started" (or "Curator review failed: `<e>`") and opens the action log.
- **Config / env:** The `curator.*` config category (10 keys).
- **Edge cases / guards:** The button label is derived only from `paused`, so it reads "Pause" even when the curator is `enabled: false`.
- **Rebuild notes:** Three states (disabled / active / paused) but only a two-way button — a rebuild should disable the toggle when the curator is off in config.

### System → "Gateway" section  `id: web-c.system.gateway`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Gateway" (`Power` icon).
- **What it does:** Starts, restarts or stops the gateway process.
- **How it works:** `SystemPage.tsx:1045-1091`; `runGateway(verb)` (`:289-307`) calls `POST /api/gateway/start` / `POST /api/gateway/stop` / `POST /api/gateway/restart`, sets the tailed action to `gateway-start` / `gateway-stop` / `gateway-restart`, and re-runs `loadAll()` after 3000 ms.
- **Inputs / options:** Badge "running" (success) / "stopped" (secondary); a line showing `status.gateway_state` (or an em dash) plus " · pid `<gateway_pid>`" when known; three buttons — "START" (`Play` icon, disabled while running), "RESTART" (`RotateCw` icon, always enabled), "STOP" (ghost, warning-coloured, `Power` icon, disabled while stopped).
- **Outputs / side effects:** Toast "Gateway `<verb>` started"; failures toast "Gateway `<verb>` failed: `<e>`". The action log tails the spawned command.
- **Config / env:** n/a
- **Edge cases / guards:** No confirmation on stop; the 3 s reload can race a slow start, leaving a stale badge until the next load.
- **Rebuild notes:** These three buttons plus the action log are the whole gateway lifecycle surface in the dashboard; the header "Restart Gateway" button (app shell) duplicates only the restart.

### System → "Memory" section  `id: web-c.system.memory`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Memory" (`Brain` icon).
- **What it does:** Reports the active external memory provider and lets the user erase the built-in memory files.
- **How it works:** `SystemPage.tsx:1093-1144`; `GET /api/memory` → `MemoryStatus {active, providers[{name, status, …}], builtin_files:{memory, user}}`. `resetMemory(target)` → `POST /api/memory/reset` `{target}` → `{ok, deleted[]}`.
- **Inputs / options:** Read-only line "External provider: `<memory.active or "built-in only">`" in monospace; a status badge for the active provider mapping `ready` → "ready" (success), `needs_config` → "needs setup" (warning), `unavailable` → "unavailable" (destructive), `missing` → "missing" (destructive); two links to the Plugins page — "Change in Plugins →" and, right-aligned, "Provider setup: configure in Plugins"; a size line "Built-in files — MEMORY.md: `<bytes>` · USER.md: `<bytes>`"; three destructive ghost buttons "Reset MEMORY.md", "Reset USER.md", "Reset all".
- **Outputs / side effects:** Each reset opens a `DeleteConfirmDialog` titled "Reset memory" with description "This permanently erases the selected built-in memory files. This cannot be undone."; confirming toasts "Reset: `<comma-separated deleted files>`" (or "Reset: nothing") and reloads. Failures toast "Reset failed: `<e>`".
- **Config / env:** `memory.provider` — deliberately **not** editable here (the dropdown was removed in the admin-panel refresh; the Plugins page owns it, and the Config page hides the key for the same reason).
- **Edge cases / guards:** When the active provider's status is `missing`, a destructive banner appears: "The configured provider is no longer installed. Switch to built-in memory or configure another provider in Plugins."
- **Rebuild notes:** One owner per setting: the memory provider is editable on exactly one page, and the other two link to it. Copy that discipline.

### System → "Credential pool" section  `id: web-c.system.credential-pool`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Credential pool" (`KeyRound` icon).
- **What it does:** Stores multiple API keys per provider so the agent can rotate through them (rate-limit spreading / failover).
- **How it works:** `SystemPage.tsx:1146-1195`; `GET /api/credentials/pool` → `{providers: CredentialPoolProvider[]}` where each entry is `{index, id, label, auth_type, source, priority, last_status, request_count, …}`. `addCredential()` (`:343-364`) → `POST /api/credentials/pool`; removal → `DELETE /api/credentials/pool/{provider}/{index}`.
- **Inputs / options:** Add form — `<Label htmlFor="cred-provider">Provider</Label>` + `<Input id="cred-provider" placeholder="openrouter">` (pre-filled with `openrouter`); `<Label htmlFor="cred-key">API key</Label>` + `<Input id="cred-key" type="password" placeholder="sk-…">`; `<Label htmlFor="cred-label">Label</Label>` + `<Input id="cred-label" placeholder="optional">`; button "Add key" (uppercase → "ADD KEY", `Spinner` prefix while adding). Existing entries render grouped under an uppercase provider heading, each row showing the entry `label`, its `token_preview` in monospace, an outline badge with `auth_type`, a secondary badge with `last_status` when present, and a destructive icon button `aria-label="Remove credential"` (`Trash2`).
- **Outputs / side effects:** Add toasts "Credential added" and clears the key/label fields; failures toast "Failed to add credential: `<e>`". Remove opens a `DeleteConfirmDialog` titled "Remove credential" with description "Remove this pooled API key? The agent will no longer rotate through it."; success toasts "Credential removed", failure "Failed to remove: `<e>`".
- **Config / env:** The pooled-credential store (separate from `.env`).
- **Edge cases / guards:** Submitting with a blank provider or key toasts "Provider and API key required". Empty pool shows "No pooled credentials. Add one above to enable key rotation." The delete key is the composite string `"<provider>|<index>"`, split on the first `|`. `priority` and `request_count` are returned by the API but not rendered.
- **Rebuild notes:** Index-addressed removal is fragile if the server re-orders entries between load and delete; prefer the stable `id` the API already returns.

### System → "Operations" quick actions  `id: web-c.system.operations`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Operations" (`Activity` icon) → first card, a wrapped row of seven ghost buttons.
- **What it does:** Runs the maintenance and diagnostic commands, each as a tailed background action.
- **How it works:** `SystemPage.tsx:1197-1225`; all but the first go through `runOp(fn, label)` (`:384-393`), which POSTs, stores the returned action name and toasts "`<label>` started" (failure: "`<label>` failed: `<e>`").
- **Inputs / options — all seven buttons, in order:**
  1. "Open console" (`Terminal` icon) — opens the Hermes Console modal (no HTTP call).
  2. "Run doctor" (`Stethoscope` icon) → `POST /api/ops/doctor`, label "Doctor".
  3. "Security audit" (`ShieldCheck` icon) → `POST /api/ops/security-audit`, label "Security audit".
  4. "Update skills" (`RotateCw` icon) → `POST /api/skills/hub/update`, label "Skills update".
  5. "Prompt size" (`Activity` icon) → `POST /api/ops/prompt-size`, label "Prompt size".
  6. "Support dump" (`Database` icon) → `POST /api/ops/dump`, label "Support dump".
  7. "Migrate config" (`RotateCw` icon) → `POST /api/ops/config-migrate`, label "Config migrate".
- **Outputs / side effects:** Each spawns a server-side process whose output appears in the action log card.
- **Config / env:** n/a
- **Edge cases / guards:** No confirmation on any of them; "Migrate config" rewrites `config.yaml` with no dialog.
- **Rebuild notes:** Config migration mutates the config file — it belongs behind the same confirm as the restore flow.

### System → "Open console" (Hermes Console modal)  `id: web-c.system.console`
- **Surface:** Web dashboard
- **Where:** `/system` → Operations → "Open console" → a full-screen modal titled "Hermes Console" with a `Terminal` glyph, a connection badge, the profile name in monospace, and a close button `aria-label="Close console"`.
- **What it does:** An in-browser terminal that runs `hermes` CLI commands against the managed profile over a websocket.
- **How it works:** `web/src/components/HermesConsoleModal.tsx:101`. Renders an `@xterm/xterm` `Terminal` (with `FitAddon`, `Unicode11Addon` at unicode version 11, and `WebLinksAddon`) into a portal on `document.body`. Connects to `api.buildWsUrl("/api/console", {profile})`. The wire protocol is JSON frames: **server → client** `ready {profile, prompt}`, `output {data, stream}`, `error {message}`, `confirm_required {command, message, prompt}`, `complete {status, prompt}`, `clear`, `pong`; **client → server** `input {line}`, `confirm {command}`, `cancel`. Connection states: `connecting | ready | running | closed | error`, badged secondary / success / warning / destructive.
- **Inputs / options — keyboard handling (`handleInputData`, `:212-263`):**
  - Up arrow (`ESC [ A`) / Down arrow (`ESC [ B`) — walk the command history (kept to the last 200 entries; walking past the newest clears the line).
  - `Ctrl+C` (``) — prints `^C`; cancels a running command or a pending confirmation, otherwise redraws the prompt.
  - `Ctrl+L` (``) — clears the screen and redraws the prompt.
  - Enter (`\r` or `\n`) — submits the current line.
  - Backspace (`` or `\b`) — deletes one character.
  - A bare `ESC` (`\x1b`) is swallowed; every other printable character (>= space, plus tab) is echoed.
  - While a command is running any keystroke rings the bell (`\x07`) instead of typing.
  - At a `confirm_required` prompt the input prompt becomes "Confirm? [y/N] " and only "y"/"yes" (case-insensitive) confirms; anything else cancels.
- **Outputs / side effects:** Runs real CLI commands on the host with the dashboard's privileges. The default prompt is "hermes> " (overridable by the `ready`/`complete` frames). Terminal options: 13 px, line height 1.25, 3000-line scrollback, cursor blink, `macOptionIsMeta`, and a font stack of JetBrains Mono → Cascadia Mono → Fira Code → MesloLGS NF → Source Code Pro → Menlo → Consolas → DejaVu Sans Mono → monospace. Colours follow the dashboard theme's `terminalBackground` / `terminalForeground` (defaults `#000000` / `#f0e6d2`) plus a fixed 16-colour ANSI palette.
- **Config / env:** Scoped to the dashboard's managed profile (`useProfileScope`), sent as a `profile` query parameter.
- **Edge cases / guards:** Messages written into the terminal: "Connecting to Hermes Console..." (dim), "Console is not connected." (red) when the socket is not open, "Malformed console frame." (red), "Console websocket error." (red), "Command timed out." (red) on `complete {status:"timeout"}`, "Cancelled." (yellow) on `complete {status:"cancelled"}`, "Console unavailable: `<err>`" (red) when the URL build fails, and on close either "Console connection failed before the server handshake. Check that this dashboard is connected to a backend with /api/console." (code 1006 before any `ready` frame) or "Console closed (`<code>`).`<reason>`". A `complete {status:"exit"}` closes the socket and sets state `closed`. `maybeReloadForLoopbackWsAuthFailure(code)` reloads the page when the close code indicates a stale loopback session token.
- **Rebuild notes:** Line editing lives in the browser and only whole lines cross the wire — that keeps the server side a simple command dispatcher and makes the confirmation handshake explicit. Do not turn this into a raw PTY unless you also gate it behind stronger auth.

### System → "Full backup" (create + download)  `id: web-c.system.backup`
- **Surface:** Web dashboard
- **Where:** `/system` → Operations → second card, group labelled "Full backup".
- **What it does:** Creates a complete Hermes backup archive and offers it as a browser download.
- **How it works:** `runDashboardBackup()` (`SystemPage.tsx:394-404`) → `POST /api/ops/backup` `{output}` → `{name, archive}`; the archive path is held as `pendingBackupArchive` and only promoted to downloadable when the action log reports exit code 0 (`handleActionComplete`, `:406-417`). `downloadBackup()` (`:420-439`) does an authed `GET /api/ops/backup/download?archive=<path>`, turns the response into a blob and clicks a synthetic `<a download>`.
- **Inputs / options:** Ghost button "Create backup" (`Database` icon); ghost button "Download backup" (`Download` icon → `Spinner`), disabled until an archive is ready; a truncated filename label whose `title` is the full archive path, showing "No backup created yet" when none exists (`backupFileName()` takes the last path segment).
- **Outputs / side effects:** Writes an archive under the Hermes home's `backups/` directory; toasts "Backup started", then "Backup ready to download" on success. Download failures toast "Download failed: `<e>`".
- **Config / env:** n/a
- **Edge cases / guards:** A non-zero exit clears the pending archive so the download button never offers a broken file.
- **Rebuild notes:** Gating the download on the action's exit code (rather than on the POST returning) is the correct sequencing — copy it.

### System → "Restore from backup upload"  `id: web-c.system.restore-upload`
- **Surface:** Web dashboard
- **Where:** `/system` → Operations → second card, group labelled "Restore from backup upload".
- **What it does:** Uploads a backup zip from the browser and restores it over the live installation.
- **How it works:** A hidden `<input type="file" accept=".zip,application/zip,application/x-zip-compressed">` at `SystemPage.tsx:671-680`; `runBackupImport({kind:"upload", file})` (`:448-465`) → `api.runImportUpload(file, true)` → `POST /api/ops/import-upload` as multipart `FormData` with fields `force` and `file`.
- **Inputs / options:** Ghost button "Choose restore zip" (`Upload` icon) opening the OS file picker; a truncated filename label reading "No backup archive selected" until a file is chosen; ghost button "Restore upload", disabled until a file is selected or while importing.
- **Outputs / side effects:** Opens the restore confirm dialog; on confirm, toasts "Import started", opens the action log, and clears the chosen file. Failures toast "Import failed: `<e>`".
- **Config / env:** Overwrites config, skills, sessions and data in the Hermes home.
- **Edge cases / guards:** `force: true` is always sent, deliberately: the spawned `hermes import` runs with stdin at `/dev/null`, so its interactive "Continue? [y/N]" prompt would auto-abort — the dashboard owns the consent instead (source comment, `SystemPage.tsx:212-218`).
- **Rebuild notes:** When a UI takes over a CLI's confirmation, say so in code and make the UI dialog at least as loud as the CLI prompt was.

### System → "Restore from backups path"  `id: web-c.system.restore-path`
- **Surface:** Web dashboard
- **Where:** `/system` → Operations → second card, group labelled "Restore from backups path".
- **What it does:** Restores from an archive already on the server's filesystem.
- **How it works:** `SystemPage.tsx:1299-1326`; `runBackupImport({kind:"path", path})` → `POST /api/ops/import` `{archive, force: true}`.
- **Inputs / options:** one text input `import-path` — label "Restore from backups path", placeholder "$HERMES_HOME/backups/hermes-backup.zip" (verbatim, dollar-sign and slashes included; markup: `<Label htmlFor="import-path">` + `<Input id="import-path">`); ghost button "Restore path", disabled while the trimmed path is empty or an import is running.
- **Outputs / side effects:** Same as the upload path.
- **Config / env:** n/a
- **Edge cases / guards:** No client-side validation that the path exists; failures surface only in the toast and the action log.
- **Rebuild notes:** Offer a server-side listing of `backups/` instead of free-text path entry.

### System → "Restore full Hermes backup?" confirmation  `id: web-c.system.restore-confirm`
- **Surface:** Web dashboard
- **Where:** `/system` → either restore button → destructive `ConfirmDialog`.
- **What it does:** Takes explicit consent before overwriting the installation.
- **How it works:** `SystemPage.tsx:1328-1344`.
- **Inputs / options:** Title "Restore full Hermes backup?"; description "This will overwrite your current Hermes configuration, skills, sessions, and data with the contents of `<archive name or path>`. This cannot be undone." (the target is rendered by `backupImportLabel()`, falling back to the literal "the archive"); confirm label "Restore" (destructive), cancel label "Cancel".
- **Outputs / side effects:** Confirming starts the import.
- **Config / env:** n/a
- **Edge cases / guards:** One dialog serves both restore paths; the description names the actual file so the two cannot be confused.
- **Rebuild notes:** Naming the exact archive in the confirm text is the only defence against restoring the wrong backup.

### System → "Share debug report"  `id: web-c.system.debug-share`
- **Surface:** Web dashboard
- **Where:** `/system` → Operations → third card. Title "Share debug report" (`Share2` icon); body "Uploads system info + logs to a public paste service and returns links to send the Hermes team. Pastes auto-delete after 6 hours."
- **What it does:** Uploads a diagnostic bundle to a paste service and returns copyable links.
- **How it works:** `runDebugShare()` (`SystemPage.tsx:491-511`) → `POST /api/ops/debug-share` `{redact, lines: 200}` → `DebugShareResponse {urls: {label: url}, redacted, auto_delete_seconds, failures[]}`. Unlike the other operations this is a foreground call whose result is rendered inline rather than tailed as a log.
- **Inputs / options:** Primary button "Generate share link" (`Share2` icon; "Uploading…" while in flight, disabled then); checkbox `id="share-redact"` labelled "Redact credential-shaped tokens before upload (recommended)", checked by default and disabled while uploading; once a result exists, a ghost "Copy all" button (shown only when more than one URL came back) that copies "`<label>`: `<url>`" lines joined by newlines; per URL a row with a `Link2` icon, the label in monospace, the URL as a link opening in a new tab, and a copy icon button with `aria-label="Copy <label> link"`.
- **Outputs / side effects:** Toast "Uploaded `<n>` pastes" (singular "paste" when n is 1), with " (redacted)" appended when redaction ran. Result header shows a success badge "uploaded", then either an outline badge "redacted" or a warning badge "not redacted", then a `Clock` icon and "auto-deletes in `<h>`h" (seconds rounded to hours). Copy buttons flip to a `Check` icon for 1500 ms. Failures toast "Debug share failed: `<e>`"; clipboard failures toast "Couldn't copy to clipboard".
- **Config / env:** n/a
- **Edge cases / guards:** Partial upload failures render "Some logs failed to upload: `<failures joined by "; ">`" in destructive text. Unchecking redaction uploads raw logs to a **public** paste service — the warning badge is the only signal afterwards.
- **Rebuild notes:** Default-on redaction plus a visible "not redacted" badge is the minimum for a feature that publishes logs; a stronger version would refuse to upload unredacted content without a second confirmation.

### System → "Checkpoints" section  `id: web-c.system.checkpoints`
- **Surface:** Web dashboard
- **Where:** `/system` → section heading "Checkpoints" (`Database` icon).
- **What it does:** Reports the size of the rollback checkpoint shadow store and lets the user delete it.
- **How it works:** `SystemPage.tsx:1466-1482`; `GET /api/ops/checkpoints` → `CheckpointsResponse {sessions[], total_bytes}`; prune → `POST /api/ops/checkpoints/prune` → a tailed action.
- **Inputs / options:** A summary line "`<n>` session(s) · `<bytes>`"; a destructive ghost button "Prune" (`Trash2` icon), disabled when there are no sessions.
- **Outputs / side effects:** `DeleteConfirmDialog` titled "Prune checkpoints" with description "Delete the rollback checkpoint shadow store? Existing /rollback points will be lost."; confirming toasts "Checkpoint prune started" and opens the action log. Failure toasts "Prune failed: `<e>`".
- **Config / env:** The checkpoint shadow store inside the Hermes home.
- **Edge cases / guards:** Prune is all-or-nothing; there is no per-session prune in this UI even though the API returns the session list.
- **Rebuild notes:** Surface the per-session breakdown the API already returns and allow selective pruning.

### System → "Shell hooks" section  `id: web-c.system.hooks`
- **Surface:** Web dashboard
- **Where:** `/system` → last section, heading "Shell hooks" (`Terminal` icon) with a "NEW HOOK" button on the right.
- **What it does:** Lists configured shell hooks — external commands the agent runs at lifecycle points — with their approval state, and allows removal.
- **How it works:** `SystemPage.tsx:1484-1537`; `GET /api/ops/hooks` → `HooksResponse {hooks: HookEntry[], valid_events[]}`; delete → `DELETE /api/ops/hooks` `{event, command}`.
- **Inputs / options:** Per hook row — an outline badge with the hook `event`; "matcher: `<matcher>`" when set; the `command` in truncated monospace; a destructive badge "not executable" when `executable === false`; a badge "allowed" (success) or "not approved" (warning); a destructive icon button `aria-label="Remove hook"` (`Trash2`). Empty state card: "No shell hooks configured."
- **Outputs / side effects:** Delete opens a `DeleteConfirmDialog` titled "Remove shell hook" with description "Remove this hook from config and revoke its consent? It stops firing on the next restart."; success toasts "Hook removed", failure "Failed to remove hook: `<e>`".
- **Config / env:** Hook definitions plus their consent records in `config.yaml`.
- **Edge cases / guards:** The delete key is `"<event>|<command>"` split on the **first** `|`, so a command containing `|` still round-trips.
- **Rebuild notes:** Separating "configured" from "approved" (consent) is the safety model here — a hook can exist without being allowed to run.

### System → "New shell hook" modal  `id: web-c.system.new-hook`
- **Surface:** Web dashboard
- **Where:** `/system` → "Shell hooks" → "NEW HOOK" (`Plus` icon) → modal titled "New shell hook".
- **What it does:** Registers a command to run at a lifecycle event, optionally granting it consent immediately.
- **How it works:** `SystemPage.tsx:712-813`; `createHook()` (`:585-611`) → `POST /api/ops/hooks` `{event, command, matcher?, timeout?, approve}`.
- **Inputs / options:**
  - Close button `aria-label="Close"`; backdrop click and Escape close (`useModalBehavior`).
  - `<Label htmlFor="hook-event">Event</Label>` + `<Select id="hook-event">` populated from `hooks.valid_events`, falling back to the built-in list `HOOK_EVENTS_FALLBACK` (`SystemPage.tsx:167-174`): `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, `on_session_start`, `on_session_end`. Default selection `pre_tool_call`.
  - `<Label htmlFor="hook-command">Command (absolute path)</Label>` + `<Input id="hook-command" autoFocus placeholder="/usr/local/bin/my-hook.sh">`.
  - `<Label htmlFor="hook-matcher">Matcher (optional)</Label>` + `<Input id="hook-matcher" placeholder="e.g. terminal">`.
  - `<Label htmlFor="hook-timeout">Timeout (s)</Label>` + `<Input id="hook-timeout" placeholder="10">` (sent as a `Number` when non-blank).
  - Checkbox `id="hook-approve"` (checked by default) labelled "Approve now (grant consent so it fires; otherwise it stays configured but inactive)".
  - Warning paragraph: "Shell hooks run arbitrary commands on this host. Only add scripts you trust. Takes effect on the next gateway/session restart."
  - Submit button "Create hook" (uppercase; "Creating" with a `Spinner` while in flight).
- **Outputs / side effects:** Writes the hook (and, when approved, its consent) into `config.yaml`; toast "Hook created"; the command/matcher/timeout fields reset and the modal closes.
- **Config / env:** `config.yaml` hooks section.
- **Edge cases / guards:** A blank command toasts "Command is required" and blocks the request. Failures toast "Failed to create hook: `<e>`". A non-numeric timeout becomes `NaN` client-side and is sent as-is — the server must reject it.
- **Rebuild notes:** Two-step arming (configure + approve) with an explicit "only add scripts you trust" warning is the right shape for arbitrary code execution; validate the timeout numerically before sending.

---

## 9. Documentation page (`/docs`)

### Documentation page  `id: web-c.docs.page`
- **Surface:** Web dashboard
- **Where:** Sidebar → `DOCUMENTATION` (href `/docs`, i18n `app.nav.documentation`); page `<h1>` renders "Documentation" (`resolvePageTitle()` maps `/docs` to i18n `app.nav.documentation`, `web/src/lib/resolve-page-title.ts:14`).
- **What it does:** Embeds the public Hermes documentation site inside the dashboard so the user never leaves the app to read it.
- **How it works:** `web/src/pages/DocsPage.tsx:18`. A single `<iframe title="Documentation" src="https://hermes-agent.nousresearch.com/docs/">` (the URL is exported as `HERMES_DOCS_URL`, `DocsPage.tsx:8`) filling the page. Sandbox attribute: `allow-scripts allow-same-origin allow-popups allow-forms`; `referrerPolicy="no-referrer-when-downgrade"`. The iframe is forced to `[color-scheme:light] bg-white` because the Docusaurus site paints over a transparent body and would render near-invisible text under the dashboard's dark themes (source comment, `:52-61`).
- **Inputs / options:** The embedded docs site's own navigation, plus the page-header link (below). No dashboard-side controls.
- **Outputs / side effects:** Network requests to the public docs host.
- **Config / env:** n/a
- **Edge cases / guards:** The page is **not** a Swagger/OpenAPI viewer — it is the marketing/user documentation site. It requires internet access; offline installs get an empty frame with no fallback message. The recorded Playwright crawl of `/docs` came back with an empty document (no headings, buttons, links or body text) and a re-probe during this inventory produced `ERR_CONNECTION_RESET` on the page assets — the embedded docs host is external and unreachable from the inventory sandbox, so nothing paints.
- **Rebuild notes:** An iframe to hosted docs is a two-line feature; the only non-obvious parts are the forced light colour scheme and the sandbox list. A better version would ship the docs locally (or cache them) so the page still works offline, and would deep-link the iframe to the page matching the dashboard route the user came from.

### Documentation → "Open documentation in a new tab"  `id: web-c.docs.open-external`
- **Surface:** Web dashboard
- **Where:** `/docs` → page header, right side. An anchor styled as an outlined button with an `ExternalLink` icon and the label "Open documentation in a new tab" (i18n `app.openDocumentation`), rendered uppercase with wide tracking.
- **What it does:** Opens the documentation site in a real browser tab, outside the iframe.
- **How it works:** `DocsPage.tsx:22-37`; injected into the shared page header via `usePageHeader().setEnd` and removed on unmount. `href={HERMES_DOCS_URL}`, `target="_blank"`, `rel="noopener noreferrer"`.
- **Inputs / options:** Click.
- **Outputs / side effects:** Opens `https://hermes-agent.nousresearch.com/docs/`.
- **Config / env:** n/a
- **Edge cases / guards:** No URL configuration — the docs host is hard-coded.
- **Rebuild notes:** Make the docs base URL configurable so self-hosted/air-gapped deployments can point it at their own mirror.

### Documentation → plugin slots  `id: web-c.docs.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `/docs` — above and below the iframe.
- **What it does:** Extension points for dashboard plugins.
- **How it works:** `<PluginSlot name="docs:top" />` (`DocsPage.tsx:46`) and `<PluginSlot name="docs:bottom" />` (`:66`).
- **Inputs / options:** Slot names `docs:top`, `docs:bottom`.
- **Outputs / side effects:** Whatever the plugin renders.
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** A plugin could use `docs:top` to add its own documentation tab.

---

## 10. Login and the dashboard auth gate

### Sign-in page (`/login`)  `id: web-c.login.page`
- **Surface:** Web dashboard
- **Where:** `GET /login` (server-rendered, not part of the React SPA). Browser title "Sign in — Hermes Agent". Content: the wordmark "Nous · Research" (a square amber dot separates the two words), a card with `<h1>Sign in</h1>`, the sub-line "Choose a sign-in method to continue to the Hermes Agent dashboard.", the provider list, and the footer "Public bind · Auth required" flanked by two hairline rules.
- **What it does:** Offers one button (or form) per registered interactive auth provider; it is the entry point whenever the dashboard's auth gate is engaged.
- **How it works:** `hermes_cli/dashboard_auth/login_page.py:461` `render_login_html(next_path)` fills `_LOGIN_HTML_TEMPLATE` (`:35-320`). Providers come from `list_session_providers()` (registry entries whose `supports_session` is true). The route is `hermes_cli/dashboard_auth/routes.py:133` `login_page()`, which validates the `next=` query parameter with `_validate_post_login_target()` and returns the HTML with `Cache-Control: no-store, no-cache, must-revalidate`. The page deliberately loads **no** React bundle and no session token; it does load the brand fonts from `/fonts/` (`Collapse-Regular.woff2`, `Collapse-Bold.woff2`, `RulesCompressed-Regular.woff2`, `RulesCompressed-Medium.woff2`), which the gate allowlists pre-auth.
- **Inputs / options:** Per OAuth provider, an anchor with `class="provider-btn"` labelled "Sign in with `<display name>`" pointing at `/auth/login?provider=<name>[&next=<url-encoded path>]`. Per password provider, a `<form class="provider-form" data-provider="<name>" autocomplete="on">` containing: a title "Sign in with `<display name>`"; a hidden `next` input; a labelled field "Username" (`<input type="text" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required>`); a labelled field "Password" (`<input type="password" name="password" autocomplete="current-password" required>`); an empty `div.form-error[role=alert][hidden]`; and a submit `<button class="provider-btn" type="submit">Sign in</button>`.
- **Outputs / side effects:** OAuth buttons start a 302 round trip to the IDP; password forms POST JSON to `/auth/password-login` and navigate on success.
- **Config / env:** The registered dashboard-auth providers (the bundled Nous provider lives in `plugins/dashboard-auth-nous/`; third parties register via the plugin hook `ctx.register_dashboard_auth_provider`).
- **Edge cases / guards:** The `class="provider-btn"` name is contractually stable — `tests/hermes_cli/test_dashboard_auth_401_reauth.py` extracts the anchor href to walk the flow (source docstring, `login_page.py:17-20`). The inline password script is emitted **only** when at least one provider reports `supports_password`, preserving a no-JavaScript login page for OAuth-only deployments. `next_path` is URL-encoded then HTML-escaped as defence in depth.
- **Rebuild notes:** Styling constants, in case the page is rebuilt: background `#170d02`, accent `#ffac02`, foreground `#ffffff`; buttons are square (`border-radius: 0`) with the DS bevel `inset 1px 1px 0 rgba(255,255,255,.5), inset -1px -1px 0 rgba(0,0,0,.5)`, uppercase with `letter-spacing: .2em`, `:hover` brightness 1.08 and `:active` full invert; the card sits on a dot-grid backdrop (`repeating-conic-gradient` at 3 px) with a radial amber glow; the panel animates in with a 0.6 s `slide-up`, disabled under `prefers-reduced-motion: reduce`. A login page that does not depend on the app bundle is the right call — it still works when the SPA build is missing.

### Sign-in unavailable page  `id: web-c.login.unavailable`
- **Surface:** Web dashboard
- **Where:** `GET /login` when zero interactive providers are registered. Browser title "Sign-in unavailable — Hermes Agent"; `<h1>` "Sign-in unavailable".
- **What it does:** Explains why nobody can sign in and how to fix it.
- **How it works:** `login_page.py:322-404` (`_EMPTY_HTML`), returned by `render_login_html()` when `list_session_providers()` is empty.
- **Inputs / options:** One link, "dashboard authentication documentation" → `https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard#authentication-gated-mode`.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** Body text, verbatim: "This dashboard is bound to a non-loopback host but no authentication providers are available." / "Configure the bundled username/password provider or an OAuth provider. See the dashboard authentication documentation for setup instructions." / "For auth-free local use, bind to `127.0.0.1` and connect through an SSH tunnel or Tailscale." This is exactly what the live crawl of `/login` captured on the inventory instance, which runs in loopback mode with no providers registered.
- **Rebuild notes:** Failing closed with an explanation beats failing open; keep the three-sentence structure (what happened / how to configure / the local escape hatch).

### Login → OAuth round trip (`/auth/login` → IDP → `/auth/callback`)  `id: web-c.login.oauth-roundtrip`
- **Surface:** API
- **Where:** Started by a "Sign in with …" button on `/login`.
- **What it does:** Redirects to the identity provider, then exchanges the returned code for session cookies.
- **How it works:** `routes.py:183` `auth_login(provider, next)` looks the provider up, rejects unknown or non-session providers with 404, and — if the provider is a password provider — bounces straight back to `/login[?next=…]`. Otherwise it calls `provider.start_login(redirect_uri=…)` and 302s to `ls.redirect_url`, setting the PKCE cookie. The cookie payload always carries `provider=<name>` (prepended when the provider did not include it) and, when present, `;next=<url-encoded path>` — the only server-controlled channel that survives the IDP round trip, since real IDPs echo back only `code` and `state`. `routes.py:427` `auth_callback(code, state)` completes the exchange and sets the session cookies.
- **Inputs / options:** Query parameters `provider` (required) and `next` (optional).
- **Outputs / side effects:** Cookies `hermes_session_at` (access token), `hermes_session_rt` (refresh token), `hermes_session_provider`, and the short-lived `hermes_session_pkce` (PKCE state + CSRF nonce + provider + next). Names gain a `__Secure-` prefix over HTTPS (`cookies.py:78-93`). Audit events `LOGIN_START` and `LOGIN_FAILURE` are written by `dashboard_auth/audit.py`.
- **Config / env:** Redirect URI reconstruction honours `X-Forwarded-*` headers and the `X-Forwarded-Prefix` reverse-proxy prefix (`dashboard_auth/prefix.py`).
- **Edge cases / guards:** A provider that cannot be reached raises 503 "Provider unreachable: `<e>`" and logs `LOGIN_FAILURE reason=provider_unreachable`. `next` is validated by `_validate_post_login_target()` (`routes.py:610-641`) both before it enters the cookie and again after the callback: it must start with a single `/`, must not start with `//`, must not target `/login`, `/auth/` or `/api/auth/`, and must not be `/api` or start with `/api/` (a redirect to an API endpoint would dump raw JSON into the address bar and is indistinguishable from a weaponised redirect).
- **Rebuild notes:** Carrying `next` in a server-set cookie rather than the query string is the load-bearing trick; re-validate it on the way out, not just on the way in.

### Login → username/password sign-in (`POST /auth/password-login`)  `id: web-c.login.password`
- **Surface:** API
- **Where:** Submitted by the `/login` page's password form (via `fetch`, not a native form POST).
- **What it does:** Verifies credentials against a password-capable provider and mints browser session cookies.
- **How it works:** `routes.py:699` `auth_password_login(body)`. Body is `{provider, username, password, next}`. On success it sets the same session cookies as the OAuth callback and returns JSON `{"ok": true, "next": <path>}` — a 302 would be followed opaquely by `fetch`, so the client navigates itself. The inline page script (`login_page.py:415-458`) attaches one delegated submit handler to every `form.provider-form`, reads the provider from the form's `data-provider` attribute (not from field ordering), disables the submit button while in flight, and on success does `window.location.assign(data.next || "/")`.
- **Inputs / options:** JSON fields `provider`, `username`, `password`, `next`.
- **Outputs / side effects:** Session cookies; audit `LOGIN_FAILURE` entries with reasons `rate_limited` / `unknown_password_provider`.
- **Config / env:** n/a
- **Edge cases / guards:** A per-IP sliding-window rate limiter allows **10 attempts per 60 seconds** (`_PW_RATE_MAX_ATTEMPTS = 10`, `_PW_RATE_WINDOW_SEC = 60.0`, `routes.py:657-659`); requests with no discernible client IP share one bucket (fail-safe toward throttling). Failure modes are deliberately generic so the endpoint cannot be used as a username or provider-enumeration oracle: unknown provider *or* a provider without password support → 404 "Unknown provider"; bad credentials → 401; backing store unreachable → 503; too many attempts → 429 "Too many login attempts. Try again shortly." The client script maps those to the user-visible strings "Too many attempts. Please wait and try again." (429), "Invalid username or password." (401), "Sign-in failed. Please try again." (any other non-ok) and "Network error. Please try again." (fetch rejection). RFC 8252 native-app branch: when the PKCE cookie carries a `broker=` handle (set by `/auth/native/authorize`), success mints a one-time loopback code instead of browser cookies, and the provider recorded in that cookie must equal the submitted provider — enforced *before* credentials are verified so a flow started for provider A cannot be completed with provider B's credentials.
- **Rebuild notes:** Uniform 404/401 responses, a pre-verification provider check on the native branch, and an in-process rate limiter are all cheap; reimplement all three. Note the limiter is process-local and resets on restart — it is defence in depth over the provider's own constant-time verify, not the only line.

### Login → sign out (`POST /auth/logout`)  `id: web-c.login.logout`
- **Surface:** API
- **Where:** Triggered from the dashboard shell's sign-out affordance (the endpoint itself is public so the gate cannot trap a user with an expired session).
- **What it does:** Revokes the refresh token where possible and clears every session cookie.
- **How it works:** `routes.py:875` `auth_logout()`. Reads the session cookies, then calls `provider.revoke_session(refresh_token=rt)` on **every** registered provider (best-effort; exceptions are logged, never raised) so a session minted by any provider is revoked correctly. Writes an audit `LOGOUT` event with the provider, user id and client IP, then 302s to `<prefix>/login`, clearing the session cookies and the PKCE cookie.
- **Inputs / options:** None (no body).
- **Outputs / side effects:** Clears `hermes_session_at`, `hermes_session_rt`, `hermes_session_provider` and `hermes_session_pkce`; redirects to the login page.
- **Config / env:** n/a
- **Edge cases / guards:** Revocation failures never block the logout — the cookies are cleared regardless.
- **Rebuild notes:** Always clear locally even when remote revocation fails; the reverse leaves users unable to log out of a broken IDP.

### Login → provider list for the login bootstrap (`GET /api/auth/providers`)  `id: web-c.login.providers-api`
- **Surface:** API
- **Where:** Public endpoint used to bootstrap a login UI (the SPA and desktop clients).
- **What it does:** Lists the interactive sign-in options.
- **How it works:** `routes.py:153`. Returns `{"providers": [{"name", "display_name", "supports_password"}]}` from `list_session_providers()`.
- **Inputs / options:** None.
- **Outputs / side effects:** JSON only.
- **Config / env:** n/a
- **Edge cases / guards:** Fails **closed** with HTTP 503 `{"detail": "no auth providers registered"}` when zero providers exist. Token-only credentials (e.g. a drain token) are deliberately excluded — they are not sign-in options.
- **Rebuild notes:** Keep the session/token provider split (`list_session_providers()` vs `list_token_providers()`); mixing them lets a machine credential appear as a human sign-in button.

### Login → session identity probe (`GET /api/auth/me`)  `id: web-c.login.me`
- **Surface:** API
- **Where:** Called by the SPA after login to learn who is signed in.
- **What it does:** Returns the verified session as JSON.
- **How it works:** `routes.py:911`. Reads `request.state.session` (populated by the gate middleware) and returns `{user_id, email, display_name, org_id, provider, expires_at}`; 401 when absent.
- **Inputs / options:** None.
- **Outputs / side effects:** JSON only.
- **Config / env:** n/a
- **Edge cases / guards:** Auth-required — it is not in the public allowlist.
- **Rebuild notes:** Six fields is the right size for an identity probe; do not leak tokens here.

### Login → WebSocket upgrade ticket (`POST /api/auth/ws-ticket`)  `id: web-c.login.ws-ticket`
- **Surface:** API
- **Where:** Called transparently by the SPA before opening any dashboard websocket in gated mode.
- **What it does:** Mints a short-lived, single-use ticket that authenticates a WS upgrade, because browsers cannot set an `Authorization` header on a WebSocket handshake.
- **How it works:** `routes.py:932`; `mint_ticket(user_id, provider)` from `dashboard_auth/ws_tickets.py`. TTL is **30 seconds** and each ticket is single-use, so one ticket per socket is the expected pattern. The client appends it as `?ticket=` to `/api/pty`, `/api/console`, `/api/ws`, `/api/pub` or `/api/events`.
- **Inputs / options:** None (identity comes from the session).
- **Outputs / side effects:** Audit event `WS_TICKET_MINTED`.
- **Config / env:** The SPA chooses ticket-vs-token mode from the server-injected `window.__HERMES_AUTH_REQUIRED__` flag (`web/src/lib/api.ts:34-39`).
- **Edge cases / guards:** 401 when no session is present (defensive — the middleware should already have rejected).
- **Rebuild notes:** Short-TTL single-use tickets are the standard fix for cookie-less WS auth; keep the TTL well under a minute.

### Login → the auth gate (which routes are public)  `id: web-c.login.gate`
- **Surface:** Core
- **Where:** Enforced on every request by `gated_auth_middleware` (`hermes_cli/dashboard_auth/middleware.py:323`).
- **What it does:** Engages only when the dashboard binds to a non-loopback host without `--insecure`; then every request must carry a verified session, except an explicit allowlist.
- **How it works:** `_path_is_public()` (`middleware.py:68-86`) unions two sources. Exact matches come from `PUBLIC_API_PATHS` (`dashboard_auth/public_paths.py:33-60`); prefix matches from `_GATE_PUBLIC_PREFIXES` (`middleware.py:49-66`), compared with `path == prefix or path.startswith(prefix)` so `/assets/` matches `/assets/foo.css` but not `/assetsleak`.
- **Inputs / options — the complete allowlists:**
  - Exact public API paths (8): `/api/health`, `/api/status`, `/api/config/defaults`, `/api/config/schema`, `/api/model/info`, `/api/dashboard/themes`, `/api/dashboard/plugins`, `/api/cron/fire` — eight entries in total, each justified inline (liveness probes; read-only schema/defaults feeds for the Config page; read-only model metadata; theme and plugin manifests for the skin engine; and the Chronos cron-fire webhook, which carries its own NAS-minted JWT with `purpose=cron_fire` as the real auth).
  - Public prefixes (15): `/auth/login`, `/auth/callback`, `/auth/native/authorize`, `/auth/native/token`, `/auth/native/refresh`, `/auth/password-login`, `/auth/logout`, `/login`, `/api/auth/providers`, `/api/mcp/oauth/callback/`, `/assets/`, `/favicon.ico`, `/ds-assets/`, `/fonts/`, `/fonts-terminal/`.
- **Outputs / side effects:** Unauthenticated requests get `_unauth_response()` (`middleware.py:112`): `/api/*` paths receive a 401 JSON envelope carrying `login_url` (with a `next=` query) so the SPA's global 401 handler can `window.location.assign(body.login_url)`; every other path receives a 302 to `<prefix>/login?next=<path>`. Reasons recorded: `no_cookie`, `invalid_or_expired_session`.
- **Config / env:** Under a reverse proxy setting `X-Forwarded-Prefix: /hermes`, `login_url` becomes `/hermes/login?next=…` (`dashboard_auth/prefix.py`). The gate also honours `X-Forwarded-For` for client-IP attribution.
- **Edge cases / guards:** A cookie's `provider=` hint is a hint only — `_ordered_session_providers()` (`middleware.py:96-110`) stably sorts the hinted provider first but still scans the rest, so a renamed or removed provider does not lock users out. The `public_paths.py` docstring records the acceptance test for adding an entry: it must be safe to expose to external uptime probes, to the SPA before login, and to anyone who curls the hostname.
- **Rebuild notes:** Sharing one allowlist between both middlewares (the loopback token gate in `web_server.py` and this OAuth gate) is the fix for a real production bug where `/api/status` was public under one and 401 under the other, breaking the portal's liveness probe. Never keep two copies.

### Login → loopback session-token mode  `id: web-c.login.loopback-token`
- **Surface:** Core
- **Where:** The default mode when the dashboard binds to a loopback address, or whenever `--insecure` is passed. No `/login` page is involved.
- **What it does:** Authenticates the browser with an ephemeral per-process token instead of an OAuth session.
- **How it works:** `hermes_cli/web_server.py:581-602`. `_resolve_session_token()` reads `HERMES_DASHBOARD_SESSION_TOKEN` from the environment or generates `secrets.token_urlsafe(32)`. The token is injected into the served `index.html` as `window.__HERMES_SESSION_TOKEN__` — never fetched over the API — and the SPA echoes it back in the header `X-Hermes-Session-Token` (`_SESSION_HEADER_NAME`, `web_server.py:593`; client side `SESSION_HEADER` at `web/src/lib/api.ts:41`). A legacy `Authorization: Bearer <token>` form is also accepted, and comparisons use `hmac.compare_digest`. WebSockets in this mode append `?token=<token>` instead of a ticket.
- **Inputs / options:** Header `X-Hermes-Session-Token: <token>` (or `Authorization: Bearer <token>`); WS query parameter `token`. Env `HERMES_DASHBOARD_SESSION_TOKEN` pins the value (used by the Electron app and by `--ssh-session-token` spawns).
- **Outputs / side effects:** Grants full dashboard access.
- **Config / env:** `HERMES_DASHBOARD_SESSION_TOKEN`; the CLI's `--insecure` and `--ssh-session-token` flags.
- **Edge cases / guards:** The same `PUBLIC_API_PATHS` allowlist applies, so `/api/status` and friends answer without the header. `authedFetch()` (`api.ts:249-264`) attaches the header for binary downloads and uploads but deliberately skips the global 401-to-login redirect, because binary endpoints are not navigation targets. `dashboard-auth-reload.ts` reloads the page once when a loopback websocket closes with an auth failure code, on the assumption that the injected token has been rotated by a server restart.
- **Rebuild notes:** Injecting the token into the HTML (rather than exposing an endpoint that hands it out) is what keeps loopback mode safe against a curl from another local user's browser context; keep the constant-time compare.

### Login → native-app authorize (`GET /auth/native/authorize`)  `id: web-c.login.native-authorize`
- **Surface:** API
- **Where:** Opened in the **system browser** by the Hermes desktop app; it lands the user on the same `/login` page (or straight at the IDP) documented above.
- **What it does:** Starts an RFC 8252 native-app sign-in so the desktop never has to host credentials in an embedded webview.
- **How it works:** `hermes_cli/dashboard_auth/routes.py:290`. Query parameters `provider`, `code_challenge`, `code_challenge_method`, `redirect_uri`, `state`. It stashes a pending "broker" authorization, then hands off to the existing upstream PKCE round trip (`provider.start_login` → IDP → `/auth/callback`), carrying the broker state inside the very same `hermes_session_pkce` cookie the browser flow uses. For a `supports_password` provider there is no upstream IDP, so it redirects to the interactive `/login` form instead — which is the point: it moves sign-in into the system browser where OS password managers can autofill.
- **Inputs / options:** `provider` (may be empty when exactly one brokerable session provider is registered, which auto-selects it), `code_challenge` (required), `code_challenge_method` (must be `S256`), `redirect_uri` (required, loopback), `state` (CSRF).
- **Outputs / side effects:** A pending broker authorization plus a 302 to the IDP or to `/login`. On completion the browser is bounced to the desktop's loopback `redirect_uri` carrying `code` and `state`; **no** session cookie is set for the desktop.
- **Config / env:** n/a
- **Edge cases / guards:** `code_challenge_method` other than `S256` → 400 "code_challenge_method must be S256" (RFC 7636 disallows `plain` for native apps). Missing challenge → 400 "code_challenge required". `_validate_loopback_redirect_uri()` (`routes.py:254-287`) accepts only `http://` with a host of exactly `127.0.0.1` or `::1`; `localhost` is deliberately rejected (RFC 8252 §8.3 — the name can resolve off-loopback through the hosts file or a hostile resolver). Errors: 400 "redirect_uri required", "native redirect_uri must be http:// on the loopback interface", "native redirect_uri host must be a loopback IP literal (127.0.0.1 / ::1)". The route is public, so this validation is a security boundary — without it an attacker could turn the gateway's authenticated callback into an open redirect that leaks a live authorization code.
- **Rebuild notes:** Reuse the browser flow's cookie as the broker channel rather than inventing a second one; and treat the loopback-literal check as mandatory, not ergonomics.

### Login → native-app token exchange (`POST /auth/native/token`)  `id: web-c.login.native-token`
- **Surface:** API
- **Where:** Called by the desktop app's loopback listener after it catches the `?code=` redirect.
- **What it does:** Swaps the one-time loopback code plus the PKCE verifier for bearer tokens the desktop stores in the OS keychain.
- **How it works:** `routes.py:974`. Body `{code, code_verifier}`; `native_flow.redeem_code()` verifies `SHA256(code_verifier) == code_challenge` (captured at authorize time) and consumes the code.
- **Inputs / options:** JSON `code`, `code_verifier`.
- **Outputs / side effects:** Returns `{access_token, refresh_token, token_type: "Bearer", expires_at, provider, user_id}` in the **body**; no cookie is set. Audit events `NATIVE_TOKEN_SUCCESS` / `NATIVE_TOKEN_FAILURE`.
- **Config / env:** The desktop authenticates every later request with `Authorization: Bearer <access_token>`.
- **Edge cases / guards:** Unknown, expired, already-redeemed codes and PKCE mismatches all return the same generic 400 "Invalid or expired authorization code." — and the code is consumed on **every** path, so there is neither a verifier oracle nor a replay window.
- **Rebuild notes:** Consume-on-every-path is the detail that makes the generic error actually safe; without it, timing/replay reveals which half failed.

### Login → native-app refresh (`POST /auth/native/refresh`)  `id: web-c.login.native-refresh`
- **Surface:** API
- **Where:** Called by the desktop app when its access token nears expiry.
- **What it does:** Rotates a desktop-held refresh token without any cookie involvement.
- **How it works:** `routes.py:1028`. Body `{refresh_token, provider?}`. Mirrors the gate middleware's `_attempt_refresh` provider stacking: the named provider is tried first (stable sort), then every other session provider, until one rotates.
- **Inputs / options:** JSON `refresh_token` (required), `provider` (optional hint).
- **Outputs / side effects:** Returns the new access/refresh pair in the body.
- **Edge cases / guards:** Missing token → 400 "refresh_token required". Every provider rejecting the token (dead, expired, or reuse detected) → 401 `session_expired`, the signal for the desktop to start a fresh native login. If no provider rotated and at least one IDP was unreachable → 503.
- **Config / env:** n/a
- **Rebuild notes:** Distinguishing "your token is dead, log in again" (401) from "the IDP is down, retry" (503) is what stops a transient outage from logging every desktop user out.

### Web dashboard → unused i18n strings in this shard's pages  `id: web-c.misc.dead-strings`
- **Surface:** Web dashboard
- **Where:** Defined in `web/src/i18n/en.ts` (and every translated locale) but referenced by no component.
- **What it does:** Nothing — they are dead entries a mechanical string-to-UI checker will otherwise flag as missing coverage.
- **How it works:** Verified by grepping the whole `web/src` tree for each key and its text.
- **Inputs / options:** The three keys, verbatim:
  - `profiles.distribution` = "Distribution" (`en.ts:368`) — the profile card renders the distribution badge from `p.distribution_name` directly and never uses this label.
  - `env.notConfigured` = "{count} not configured" (`en.ts:497`) — the Keys page counts configured items instead ("{configured} of {total} providers configured", "`<n>` of `<n>` configured").
  - `oauth.copyCliCommand` = "Copy CLI command (for external / fallback)" (`en.ts:541`) — the OAuth card's copy button uses the shorter `oauth.cli` ("Copy") instead.
- **Outputs / side effects:** None.
- **Config / env:** n/a
- **Edge cases / guards:** `profiles.saveSoul` ("Save SOUL") is likewise defined but unused — the SOUL editor's button renders `common.save`. Translators pay for all four.
- **Rebuild notes:** Add a lint step that fails when a locale key has no reference in the source tree; four dead strings in one catalog is a symptom, not an accident.

---

## Handoffs

- App shell chrome visible on every page in this shard — sidebar nav links (`CHAT`, `SESSIONS`, `FILES`, `MODELS`, `LOGS`, `CRON`, `SKILLS`, `PLUGINS`, `MCP`, `CHANNELS`, `WEBHOOKS`, `PAIRING`, `PROFILES`, `CONFIG`, `KEYS`, `SYSTEM`, `DOCUMENTATION`, plugin tabs `KANBAN` / `ACHIEVEMENTS`), the `Collapse` / `Open navigation` / `Close navigation` buttons, the "Gateway Status:" and "Active Sessions:" strip, the header "Restart Gateway" and "Update Hermes" buttons with their confirm dialogs (i18n `status.*`), the theme switcher ("HERMES TEAL", `aria-label="Switch theme"`), the language switcher ("EN", `aria-label="Switch language"`), the version line "v0.21.0" and the "Nous Research" footer → web-a / web-b.
- The global profile switcher, `ProfileScopeBanner` and the `app.managingProfileBanner` string ("Managing profile “{name}” — config, keys, skills, MCPs, model, and new chats apply to that profile.") that scopes every API call on these pages → web-a / web-b.
- Memory-pressure and disk banners (`app.memoryOomRestartBanner`, `app.memoryCriticalBanner`, `app.memoryElevatedBanner`, `app.diskCriticalBanner`, `app.diskElevatedBanner`, `app.dismiss`) → web-a / web-b.
- `/skills` page, including the `?profile=<name>` deep link opened by the Profiles card's "Manage skills & tools" action, and the skills-hub search/install endpoints the Profile Builder calls (`/api/skills/hub/search`, `/api/skills/hub/install`, `/api/skills/hub/update`) → skills shard.
- `/plugins` page, which owns `memory.provider` and `context.engine` (both deliberately removed from the Config and System pages) plus the memory-provider setup wizard (`/api/memory/providers/*`) → plugins shard.
- `/mcp` page and its "Authenticate" OAuth flow (`/api/mcp/oauth/flows/*`, `/api/mcp/servers/{name}/auth`, the public `/api/mcp/oauth/callback/` prefix) — the Profile Builder only queues MCP definitions → mcp shard.
- `/models` page and `GET /api/model/options` (`include_unconfigured=1`), the source of the model lists in the profile create modal, the profile model editor and Profile Builder step 2 → models shard.
- `/cron` page and `POST /api/cron/fire` (allowlisted past the auth gate because it carries its own NAS-minted `purpose=cron_fire` JWT) → cron shard.
- Per-key semantics of the 785 config-schema fields and the 340 env-var catalog entries → config-a / config-b.
- CLI commands surfaced as copyable strings on these pages: `hermes gateway start`, `hermes auth add <provider>`, `claude setup-token`, `copilot /login`, `hermes portal`, `hermes update`, `hermes import`, and the per-profile command returned by `/api/profiles/{name}/setup-command` → cli-a / cli-b.
- Gateway platform adapters behind the 33 Channels cards (Telegram/WhatsApp bridges, the API server, the webhook receiver, A2A, Buzz, Photon, …) and the `gateway.multiplex_profiles` port-binding rule that produces the 409 on the Channels toggle → gateway shard.
- The Electron desktop app's client side of the RFC 8252 native flow (system-browser launch, loopback listener, OS-keychain token storage) → desktop shard.
- `/api/pty`, `/api/ws`, `/api/pub`, `/api/events` — the other websockets that consume the `ws-ticket` documented here → web-a / web-b.
- The dashboard-plugin runtime (`PluginSlot`, `/api/dashboard/plugins`, `dashboard-plugins/` serving, the `common.pluginLoadFailed` / `common.pluginNotRegistered` strings) → plugins shard.
- `hermes_cli/dashboard_auth/audit.py` event taxonomy (`LOGIN_START`, `LOGIN_FAILURE`, `LOGOUT`, `WS_TICKET_MINTED`, `NATIVE_TOKEN_SUCCESS`, `NATIVE_TOKEN_FAILURE`) and the audit-log sink → core/security shard.
