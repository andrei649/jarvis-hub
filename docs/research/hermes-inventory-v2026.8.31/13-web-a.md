# Web dashboard pages: Chat, Sessions, Files, Analytics, Models

This shard inventories five routes of the Hermes Agent web dashboard SPA (`web/src`, served by `hermes dashboard` → `hermes_cli/web_server.py`, v2026.8.31): `/chat` (`pages/ChatPage.tsx` + `components/ChatSidebar.tsx`, `components/ChatSessionList.tsx`, `components/ModelPickerDialog.tsx`, `components/ReasoningPicker.tsx`, `components/ModelReloadConfirm.tsx`), `/sessions` (`pages/SessionsPage.tsx` + `components/Markdown.tsx`, `components/PlatformsCard.tsx`, `components/DeleteConfirmDialog.tsx`), `/files` (`pages/FilesPage.tsx`), `/analytics` (`pages/AnalyticsPage.tsx`) and `/models` (`pages/ModelsPage.tsx` + `components/ConfirmDialog.tsx`). For every page it lists the layout, every button/input/toggle/menu/dialog/keyboard shortcut/empty-state/error string (quoted verbatim, with `i18n:` keys from `web/src/i18n/en.ts` where the string is translated), the REST/WebSocket endpoints each page calls (`web/src/lib/api.ts` + the FastAPI handlers in `hermes_cli/web_server.py` and `hermes_cli/web_routers/sessions.py`), realtime channels, and browser storage keys. Evidence was cross-checked against the live crawl (`hermes_inv/web_crawl/_chat.json`, `_sessions.json`, `_files.json`, `_analytics.json`, `_models.json`) and live GET responses (`hermes_inv/api_live/get_all.json`).

Deliberately left to sibling shards: the app shell (sidebar nav, header, theme/language switchers, profile switcher, gateway status strip, memory/disk banners — `App.tsx`), the other dashboard pages (Logs, Cron, Skills, Plugins, MCP, Channels, Webhooks, Pairing, Profiles, Config, Keys, System, Docs, Kanban, Achievements), the dashboard auth gate (`/login`, OAuth, cookies), and — crucially — everything rendered *inside* the terminal on the Chat page: the Ink TUI (`ui-tui/`) composer, slash popover, attachments, tool-call rows, approval/clarify/sudo prompts, todo panel, voice — those are TUI-shard features that the dashboard merely displays through xterm.js. Handoffs are listed at the end.

---

## A. Chat page (`/chat`)

### Chat page (persistent embedded-terminal host)  `id: web-a.chat.page`
- **Surface:** Web dashboard
- **Where:** Sidebar nav link `CHAT` (`i18n: app.nav.chat` = "Chat", `App.tsx:139-143` `CHAT_NAV_ITEM`), URL `/chat`; page `<h1>` "Chat" (`i18n: app.nav.chat`, resolved by `lib/resolve-page-title.ts:4`). Crawl `_chat.json` confirms heading "Chat".
- **What it does:** Embeds the full Hermes terminal UI (`hermes --tui`) inside the dashboard using xterm.js, connected to a server-side pseudo-terminal over WebSocket. The whole conversation experience (typing prompts, slash commands, tool output, approvals) happens inside this terminal pane.
- **How it works:** `App.tsx:178-184` registers `/chat` with an empty `ChatRouteSink` so the router owns the URL, while the real `<ChatPage isActive={isChatRoute}/>` is rendered *outside* `<Routes>` (`App.tsx:813`) inside a `div` that flips between `flex flex-1 flex-col` and `hidden` (`App.tsx:800-830`), so the PTY, WebSocket and xterm instance survive navigation to other tabs. Mount is deferred until the first `/chat` visit via the sticky latch `latchChatActivation(prev, isActive)` (`lib/chat-activation.ts:603`, `App.tsx:405-408`, `ChatPage.tsx:197-200`). Data flow (header comment `ChatPage.tsx:1-17`): keystrokes → `term.onData` → WebSocket `/api/pty` → FastAPI `pty_ws` (`web_server.py:17422`) → POSIX PTY (`hermes_cli/pty_bridge.py`) → `node ui-tui/dist/entry.js` → `tui_gateway` + `AIAgent`; PTY bytes flow back as binary WS frames into `term.write`. The page container is `flex min-h-0 flex-1 flex-col gap-2`; the terminal wrapper (`termWrapRef`) is a rounded dark box with `boxShadow 0 8px 32px rgba(0,0,0,0.4)` and background = theme `terminalBackground` (`ChatPage.tsx:1815-1826`). `PageHeaderProvider` gives the chat route a non-scrolling `overflow-hidden` main (`contexts/PageHeaderProvider.tsx:131-136`).
- **Inputs / options:** URL query params: `?resume=<session_id>` (resume a session — entry `web-a.chat.resume`), `?learn=<text>` (entry `web-a.chat.learn-seed`), `?profile=<name>` (global management profile — entry `web-a.chat.profile-scope`). Everything else is keyboard input into the terminal (hidden `<textarea>` with `aria-label="Terminal input"` per crawl) and the buttons enumerated in the entries below.
- **Outputs / side effects:** Spawns a `hermes --tui` child process on the server (one per browser tab channel), keeps it alive across tab switches; writes `localStorage["hermes.pty.token.chat"]` and `localStorage["hermes-chat-panel-collapsed"]`.
- **Config / env:** Server flag `_DASHBOARD_EMBEDDED_CHAT_ENABLED = True` (`web_server.py:659`) injected as `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` (`web_server.py:17919`); SPA reads `isDashboardEmbeddedChatEnabled()` which always returns `true` (`lib/dashboard-flags.ts:22-24`). Theme keys `terminalBackground` / `terminalForeground` (`themes/types.ts:182-185`).
- **Edge cases / guards:** A plugin manifest with `tab.override: "/chat"` suppresses the built-in host entirely (`App.tsx:430-455`, `chatOverriddenByPlugin`); while plugin manifests are still loading the page shows `RouteFallback label="Loading chat…"`. On native Windows the server closes the PTY socket with code 1011 after printing a WSL banner (entry `web-a.chat.windows-unavailable`). While hidden (`display:none`) the terminal skips refits (`syncTerminalMetrics` bails when `clientWidth<=0`, `ChatPage.tsx:931-940`) and refits on return via a double-rAF (`ChatPage.tsx:1590-1630`); focus is only stolen back into xterm if nothing else in the page holds focus.
- **Rebuild notes:** Minimal spec: a React page that mounts xterm.js, opens a WS to a PTY endpoint, forwards bytes both ways, and stays mounted-but-hidden on other routes. A better version would render a native structured chat (messages, tool cards) from the JSON-RPC gateway (`/api/ws`) instead of mirroring ANSI, keeping the terminal as an optional "raw" view.

### xterm.js terminal pane  `id: web-a.chat.terminal`
- **Surface:** Web dashboard
- **Where:** `/chat` → main pane (`div.hermes-chat-xterm-host`, `ChatPage.tsx:1827-1830`).
- **What it does:** Renders the PTY's ANSI stream as a terminal with 5000 lines of browser-side scrollback, responsive font sizing, theme-aware colors and WebGL rendering on wide layouts.
- **How it works:** `new Terminal({...})` at `ChatPage.tsx:534-561` with options: `allowProposedApi:true`, `cursorBlink:true`, `fontFamily:"'JetBrains Mono', 'Cascadia Mono', 'Fira Code', 'MesloLGS NF', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace"`, `fontSize` from `terminalFontSizeForWidth()` (`ChatPage.tsx:163-171`: `<300px→7`, `<360→8`, `<420→9`, `<520→10`, `<720→11`, `<1024→12`, else `14`), `lineHeight` `1.02` below 1024px else `1.15` (`ChatPage.tsx:173-175`), `letterSpacing:0`, `fontWeight:"400"`, `fontWeightBold:"700"`, `macOptionIsMeta:true`, `macOptionClickForcesSelection:true`, `rightClickSelectsWord:true`, `scrollback:5000`, `theme` = `buildTerminalTheme(bg,fg)` (`ChatPage.tsx:133-142`: background, foreground, cursor=fg, cursorAccent=bg, selectionBackground=fg+"44" alpha). Addons: `FitAddon`, `Unicode11Addon` (`term.unicode.activeVersion="11"`), `WebLinksAddon`, `WebglAddon` only when host width ≥768px (`ChatPage.tsx:890-902`; falls back on context loss / error with console warning `[hermes-chat] WebGL renderer unavailable; falling back to default`). Width tier measured from host `clientWidth`, falling back to `min(innerWidth, visualViewport.width, documentElement.clientWidth)` (`terminalTierWidthPx`, `ChatPage.tsx:151-161`). Resize pipeline: `ResizeObserver` on host → rAF-coalesced `syncTerminalMetrics()` (`ChatPage.tsx:931-970`) which re-tiers font, calls `fit.fit()`, refreshes rows, and sends `\x1b[RESIZE:<cols>;<rows>]` when the font changed; `window resize` → 60ms debounce; a double-rAF authoritative fit after mount (`ChatPage.tsx:1027-1040`). `term.onResize` always sends the RESIZE escape (`ChatPage.tsx:1487-1491`). Textarea attributes forced: `autocomplete=off`, `autocorrect=off`, `autocapitalize=off`, `spellcheck=false` (`ChatPage.tsx:860-864`). Live theme change updates `term.options.theme` (`ChatPage.tsx:1697-1702`).
- **Inputs / options:** Mouse wheel (custom handler, entry `web-a.chat.mouse-report-drop`); mouse selection; keyboard (all keys forwarded except the shortcuts in `web-a.chat.clipboard-shortcuts` and `web-a.chat.word-delete-shortcuts`).
- **Outputs / side effects:** `\x1b[RESIZE:cols;rows]` control string sent over the PTY socket (consumed server-side by `_RESIZE_RE` `web_server.py:16121`, never written to the PTY; calls `bridge.resize(cols,rows)`, clamped to 1..2000 cols / 1..1000 rows in `pty_bridge.py:52-58`).
- **Config / env:** theme `terminalBackground` (default `#000000`), `terminalForeground` (default `#f0e6d2`) (`ChatPage.tsx:130-131`).
- **Edge cases / guards:** WebGL is skipped on narrow hosts because the device-pixel atlas renders glyphs visibly larger than `fontSize`; `fit()` errors are swallowed; hidden hosts (0×0) are never fitted.
- **Rebuild notes:** xterm.js + fit + unicode11 + weblinks + optional webgl, a font-tier function keyed on container width, and a `RESIZE` side-channel. Better: negotiate cell metrics with the server once and let the TUI render at DPR-aware sizes; expose font size as a user setting.

### PTY WebSocket transport (`/api/pty`)  `id: web-a.chat.pty-websocket`
- **Surface:** API
- **Where:** `WEBSOCKET /api/pty` (`routes_static.txt`; handler `pty_ws` `web_server.py:17422-17590`); opened by `ChatPage.tsx:1178-1200` via `api.buildWsUrl("/api/pty", params)`.
- **What it does:** Bridges one browser terminal to one `hermes --tui` process behind a pseudo-terminal, streaming bytes both ways and honouring resize.
- **How it works:** Client builds the URL with `buildHermesWebSocketUrl` (`apps/shared/src/websocket-url.ts:135`; `ws:`/`wss:` derived from page protocol, base path prefix from `window.__HERMES_BASE_PATH__`) and an auth param (`token` in loopback mode, single-use `ticket` in gated mode — entry `web-a.chat.ws-auth`). Query params sent (`ChatPage.tsx:1163-1175`): `channel` (per-mount id, `generateChannelId` `ChatPage.tsx:116-125`: `chat-<uuid>` when a scope exists else `chat-fresh-<uuid>`), `resume` (when `?resume=` in URL), `fresh=1` (after "Start new session"/"New chat"), `attach` (keep-alive token), `profile` (management profile). Server: validates auth → host/origin → peer (`web_server.py:17436-17456`), `ws.accept()`, checks `_PTY_BRIDGE_AVAILABLE`, reads `resume`/`profile`/`channel`/`fresh`, resolves the implicit active session (entry `web-a.chat.active-session-fallback`), resolves argv/cwd/env via `_resolve_chat_argv_async` (`web_server.py:16724`, serialised by a per-app lock and run in a thread because it may `npm install`/build the TUI), then either the legacy 1:1 pump (`_legacy_pump` `web_server.py:16140`, used when no `attach` param) or the keep-alive registry (`PTY_REGISTRY.attach_or_spawn`). Writer loop: `ws.receive()`; text or bytes; `\x1b[RESIZE:c;r]` handled locally; everything else `session.bridge.write(raw)`. PTY output arrives as **binary** frames; the only **text** frames are the one-off JSON control frame `{"type":"resume","id":...}` and ANSI error banners. Client decodes with a streaming `TextDecoder` (`ChatPage.tsx:1285-1324`).
- **Inputs / options:** Query: `channel`, `resume`, `fresh` (`1|true|yes|on`), `attach`, `profile`, plus auth `token`/`ticket`. Messages: raw keystrokes (string), `\x1b[RESIZE:<cols>;<rows>]`.
- **Outputs / side effects:** Spawns `node ui-tui/dist/entry.js` (argv from `_make_tui_argv`, `hermes_cli/main.py`) with cwd `ui-tui/` and an env built by `build_subprocess_env(scrub_secrets=False, inherit_profile_home=True)` plus: `HERMES_TUI_DISABLE_MOUSE=1`, `HERMES_TUI_INLINE=1`, `COLORTERM=truecolor`, `HERMES_TUI_DASHBOARD=1`, `NODE_ENV=production`, optional `HERMES_TUI_RESUME=<latest descendant id>`, `HERMES_TUI_SIDECAR_URL=ws://host:port/api/pub?token|internal=…&channel=…`, `HERMES_TUI_ACTIVE_SESSION_FILE=<tmp json>`, `HERMES_TUI_GATEWAY_URL=ws://host:port/api/ws?token|internal=…` (skipped for profile-scoped chats), and `HERMES_HOME=<profile dir>` when scoped (`_resolve_chat_argv` `web_server.py:16521-16660`).
- **Config / env:** `HERMES_DASHBOARD_WS_HOST` (override host the child dials, `web_server.py:16680-16695`); bind host/port from `app.state.bound_host/bound_port`.
- **Edge cases / guards:** Close codes: `4404` embedded chat disabled, `4401` auth (`reason` = `auth: no_credential|token_mismatch|ticket_invalid|internal_invalid`), `4403` host/origin mismatch, `4408` peer not loopback (loopback bind only), `1011` after an ANSI "Chat unavailable: …" / "Chat failed to start: …" text frame (missing PTY bridge, unknown profile → HTTPException detail, `SystemExit` when node/npm missing, `PtyUnavailableError`, `RegistryFull`), `4410` process exited, `4409` superseded by another tab. Close reasons are clamped to 123 bytes (`_ws_close_reason`). Channel ids must match `^[A-Za-z0-9._-]{1,128}$` (`_VALID_CHANNEL_RE` `web_server.py:16225`). PTY reads use a 0.2s chunk timeout and 0.05s idle backoff (`web_server.py:16122-16126`).
- **Rebuild notes:** WS endpoint that spawns a PTY child, forwards bytes, and consumes an in-band resize escape; distinct close codes per failure class. Better: use a structured framing (e.g. msgpack `{t:"out"|"in"|"resize"|"ctl"}`) instead of sniffing text vs binary frames, and add backpressure/flow control.

### Keep-alive PTY attach token & registry  `id: web-a.chat.keepalive-attach`
- **Surface:** Web dashboard / API / Core
- **Where:** Invisible; `localStorage["hermes.pty.token.chat"]` (`ChatPage.tsx:89-110` `ptyAttachToken(rotate)`), server `PTY_REGISTRY` (`web_server.py:16132-16137`), `hermes_cli/pty_session.py`.
- **What it does:** Lets a browser refresh, sleep/wake or transient network drop reattach to the *same* still-running agent process instead of spawning a new one; a deliberate "new session" rotates the token so the old process is not reattached.
- **How it works:** Client mints a 16-byte hex token once per browser (`crypto.getRandomValues`) and stores it in localStorage; `rotate=true` (forced-fresh start) mints a new one. Sent as `?attach=`. Server composes the registry key `attach\0profile\0registry_resume` when a resume/profile is present (`web_server.py:17513-17518`). `PtySessionRegistry(ttl=30*60, max_sessions=16, buffer_cap=1 MiB, read_timeout=0.2)`: `attach_or_spawn(key, spawn)` reaps idle sessions, reuses a living session, evicts the oldest idle when full else raises `RegistryFull`; each `PtySession` runs one drain task that appends PTY output into a `RingBuffer` (keeps last 1 MiB) and forwards to the attached socket. `attach(ws, force_redraw)` closes a previously attached socket with `4409`, replays the buffer snapshot and, when reusing (`force_redraw=not created`), writes `\x0c` (Ctrl-L, `TUI_FORCE_REDRAW`) so the TUI repaints a full frame (`pty_session.py:82-103`; TUI handles Ctrl-L via `forceRedraw` in `ui-tui/src/app/useInputHandlers.ts:670-675`). `detach` marks `last_detached_at`; `run_reaper` every 60s closes dead or idle-past-TTL sessions. On child EOF the drain task closes the socket with `4410`.
- **Inputs / options:** none user-visible; `attach` query param.
- **Outputs / side effects:** Up to 16 concurrent keep-alive PTY processes per dashboard process; idle processes survive 30 minutes after the last detach.
- **Config / env:** constants only (`ttl=1800s`, `max_sessions=16`, `buffer_cap=1048576`).
- **Edge cases / guards:** Without `attach` the legacy pump kills the PTY on disconnect. Two tabs sharing one localStorage token supersede each other (`4409` → the older tab shows the disconnected overlay quietly). Buffer truncation is tracked (`RingBuffer.truncated`).
- **Rebuild notes:** Token-keyed process registry with ring-buffered output and TTL reaping. Better: persist the token server-side per user and offer a "sessions running" list with explicit kill.

### PTY close-code handling and banners  `id: web-a.chat.close-codes-banners`
- **Surface:** Web dashboard
- **Where:** `/chat` → warning banner strip above the terminal (`ChatPage.tsx:1810-1814`), terminal-inline grey lines, browser console.
- **What it does:** Translates every WebSocket close into a specific user-facing message or recovery path.
- **How it works:** `ws.onclose` (`ChatPage.tsx:1326-1420`) logs `[chat] PTY WebSocket closed code=<n> reason=<r>` then branches: `4401` → in loopback mode reload the page once (`maybeReloadForLoopbackWsAuthFailure`, `lib/dashboard-auth-reload.ts:937`, guarded by `sessionStorage["hermes.tokenReloadAttempted"]`), else state `closed` + banner "Auth failed (<reason>). Reload to refresh the session." or "Auth failed. Reload the page to refresh the session token."; `4403` → "Refused: <reason>." or "Refused: request host/origin doesn't match the dashboard."; `4404` → "Chat websocket unavailable: <reason>." or "Chat websocket unavailable on this server."; `4408` → "Refused: <reason>." or "Refused: your client isn't permitted (server bound to localhost only)."; `1011` → state `closed`, no banner (server already wrote an ANSI error); `4410` → writes grey `[session ended]` into the terminal, state `ended`; `4409` → state `closed` silently; not-clean or `1001`/`1006` → `scheduleReconnect(code)`; any other clean close → grey `[session ended (code N)]` + state `ended`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Banner text (`border-warning` strip), terminal lines, `ptyState` transitions (`connecting|open|reconnecting|closed|ended`, `lib/pty-reconnect.ts:2-7`).
- **Config / env:** `window.__HERMES_AUTH_REQUIRED__` decides whether a 4401 triggers the one-shot reload.
- **Edge cases / guards:** The initial banner "Session token unavailable. Open this page through `hermes dashboard`, not directly." is set at construction when neither `__HERMES_SESSION_TOKEN__` nor `__HERMES_AUTH_REQUIRED__` is present (`ChatPage.tsx:213-219`) and the effect never opens a socket.
- **Rebuild notes:** Map close codes → {message, recoverable?}. Better: show a single status pill with a "details" popover and an explicit "copy diagnostics" action.

### Automatic reconnect + "Reconnect now" overlay  `id: web-a.chat.reconnect`
- **Surface:** Web dashboard
- **Where:** `/chat` → overlay at top-right of the terminal (`ChatPage.tsx:1833-1853`): text "Chat is reconnecting." or "Chat disconnected." and button **"Reconnect now"** (`aria-label="Reconnect chat"`, RotateCcw icon); banner "Chat connection interrupted (code N). Reconnecting..." (`ChatPage.tsx:1706-1711`).
- **What it does:** Recovers from transient drops with exponential backoff, re-tries when the tab regains visibility/focus/network, and offers a manual retry.
- **How it works:** `scheduleReconnect(code)` (`ChatPage.tsx:1140-1156`): attempt = min(prev+1, 5), delay = min(250·2^(attempt−1), 3000) ms, sets state `reconnecting`, bumps `reconnectNonce` (a dependency of the connect effect, which tears down and rebuilds xterm+socket). Ticket phase timeout `PTY_TICKET_TIMEOUT_MS=8000` and CONNECTING timeout `PTY_CONNECTING_TIMEOUT_MS=8000` force-close a wedged socket so `onclose` routes into backoff (`lib/pty-reconnect.ts:20-27`, `ChatPage.tsx:1120-1139, 1200-1213`). Page-resume path: listeners on `visibilitychange`, `pageshow`, `focus`, `online` (`ChatPage.tsx:1668-1685`) call `shouldReconnectPtyOnPageResume({isActive, visibilityState, online, socketReadyState, ptyState, connectInFlight})` (`lib/pty-reconnect.ts:53-90`) throttled by `PTY_RESUME_RECONNECT_THROTTLE_MS=1000`. Manual `reconnectPty()` (`ChatPage.tsx:257-268`) resets attempt counter and state. Input typed while not `open` is swallowed and a one-time yellow line `[Chat is reconnecting. Input will resume when connected.]` is printed (`PTY_RECONNECT_INPUT_MESSAGE`, `ChatPage.tsx:1450-1459`).
- **Inputs / options:** Button "Reconnect now".
- **Outputs / side effects:** New `/api/pty` connection with the same `attach` token (conversation continues in place).
- **Config / env:** n/a.
- **Edge cases / guards:** Overlay shows for `reconnecting`, or `closed` without a banner; no auto-reconnect when state is `ended` or a terminal banner is displayed.
- **Rebuild notes:** Backoff + resume-event reconnect + manual button. Better: surface attempt count/next retry time and keep a small offline input buffer to replay.

### "Session ended." overlay and "Start new session"  `id: web-a.chat.session-ended`
- **Surface:** Web dashboard
- **Where:** `/chat` → centred overlay over the terminal: text "Session ended." and button **"Start new session"** (`aria-label="Start a new chat session"`, `ChatPage.tsx:1870-1884`).
- **What it does:** When the agent process exits (user typed `/exit`, or the TUI ended the session), offers an in-place restart without a page refresh.
- **How it works:** State `ended` set by close codes `4410` or a clean close (entry `web-a.chat.close-codes-banners`). `startFreshPty()` (`ChatPage.tsx:269-280`) sets `forceFreshPtyRef=true`, resets counters/banners, state `connecting`, bumps `reconnectNonce`; the connect effect then sends `fresh=1` and a *rotated* attach token so the old PTY is not reattached.
- **Inputs / options:** Button "Start new session".
- **Outputs / side effects:** New `hermes --tui` process; the `?resume` param is preserved (only `startFreshDashboardChat` clears it).
- **Config / env:** n/a.
- **Edge cases / guards:** z-index 30 overlay blocks terminal input until clicked.
- **Rebuild notes:** Detect child exit, render a restart CTA. Better: show the exit reason/exit code and a "resume last session" alternative.

### Resume a session in chat (`?resume=`)  `id: web-a.chat.resume`
- **Surface:** Web dashboard
- **Where:** `/chat?resume=<session_id>` — reached from Sessions page "Resume in Chat" (`i18n: sessions.resumeInChat`), from the chat side panel session list, or by deep link. Overlay text "Please wait while the conversation loads…" (`PTY_RESUME_LOADING_MESSAGE`, `lib/pty-resume-loading.ts:104`).
- **What it does:** Reopens an earlier conversation inside the terminal, replaying its transcript, keeping the viewport pinned to the bottom during replay and hiding the blank window behind a wait notice.
- **How it works:** `resumeParam` is part of the PTY identity: `channel` memo depends on it (`ChatPage.tsx:375-378`) so changing it tears down and respawns the terminal. Two pre-flight fetches: `api.getSessionDetail(resume, profile)` for the title (`ChatPage.tsx:388-401`) and `api.getSessionLatestDescendant(resume, profile)` which rewrites `?resume=` to the newest child session id with `replace:true` (`ChatPage.tsx:403-426`; server `_session_latest_descendant` `web_server.py` follows `/model` child sessions). Server sets `HERMES_TUI_RESUME` (also resolved to the latest descendant, `web_server.py:16634-16644`). Client: `beginResumeReplay()` (`ChatPage.tsx:1258-1283`) pins `stickToBottomRef`, starts a `PTY_RESUME_SANITIZE_WINDOW_MS=30000` erase-suppression window, sets `resumeHydrating` with a `PTY_RESUME_LOADING_MAX_MS=30000` cap. Every chunk goes through `PtyResumeSanitizer.next()` (`lib/pty-resume-sanitizer.ts:743-790`): collapses runs of ≥50 blank lines to `\r\n\r\n`, strips `ESC[K`/`ESC[X` while suppressing, buffers partial CSI and trailing newline runs across frames; `flush()` on close drops a dangling escape. `shouldFollowPtyOutput(resume, stick)` decides whether `term.write(...,cb)` scrolls to bottom; `term.onScroll` releases the pin when `viewportY < baseY` (`lib/pty-scroll.ts:377-394`). First non-empty rendered chunk ends hydration (`shouldFinishResumeHydrationOnChunk`).
- **Inputs / options:** Query `resume`.
- **Outputs / side effects:** Page header title becomes the session title (entry `web-a.chat.session-title-header`); URL rewritten to the latest descendant.
- **Config / env:** `sessions.max_resume_messages` (config, default 20000 — governs how much the TUI replays; observed in live `/api/config`).
- **Edge cases / guards:** Overlay only while `ptyState` is `connecting|open` and hydrating (`shouldShowResumeLoadingOverlay`); `onclose` flushes sanitizer; a resumed socket starts pinned to bottom on `onopen`.
- **Rebuild notes:** Treat resume id as part of the terminal identity; sanitize the replay burst; pin-then-release scrolling. Better: have the server send a pre-rendered transcript snapshot instead of replaying differential ANSI.

### Implicit active-session fallback (per-channel breadcrumb)  `id: web-a.chat.active-session-fallback`
- **Surface:** Core / API
- **Where:** Invisible; `pty_ws` (`web_server.py:17471-17486`), `_active_session_file_for_channel` (`web_server.py:16813-16845`), TUI writer `writeActiveSessionFile` (`ui-tui/src/app/useSessionLifecycle.ts:46-56`).
- **What it does:** After an unexpected browser socket close, reconnecting on the same channel automatically resumes whatever session the TUI had open even without `?resume=`.
- **How it works:** Server allocates a temp file `hermes-pty-active-*.json` per channel id (mode 0600 written by the TUI as `{"session_id": "..."}` whenever it creates/resumes/switches sessions) and passes it as `HERMES_TUI_ACTIVE_SESSION_FILE`. On a new `/api/pty` connect with no `resume` and no `fresh=1`, the server reads that file and, if present, sends the text control frame `{"type":"resume","id":"<sid>"}` before any PTY bytes; `fresh=1` deletes the file. Client `parseResumeControlMessage` (`lib/pty-scroll.ts:406-422`) sets `effectiveResume` and starts the replay treatment.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Temp files under the OS temp dir per channel for the dashboard process lifetime.
- **Config / env:** n/a.
- **Edge cases / guards:** Only text frames that parse to `{type:"resume", id:string}` are treated as control; all other text frames are written to the terminal.
- **Rebuild notes:** A tiny out-of-band breadcrumb file bridging two processes. Better: report the active session over the sidecar event channel instead of a temp file.

### "copy last response" floating button  `id: web-a.chat.copy-last-response`
- **Surface:** Web dashboard
- **Where:** `/chat` → bottom-right of the terminal: ghost button with Copy icon, label "copy last response" (becomes "copied" for 1.5 s; label hidden below 400px width), `title="Copy last assistant response as raw markdown"`, `aria-label="Copy last assistant response"` (`ChatPage.tsx:1888-1910`). Crawl confirms text "copy last response".
- **What it does:** Copies the last assistant message as raw markdown to the system clipboard.
- **How it works:** `handleCopyLast` (`ChatPage.tsx:490-506`) sends the string `/copy` over the PTY socket, then `\r` 100 ms later (so Ink's tokenizer sees a keypress burst then Return); the TUI's `/copy` command emits an OSC 52 escape which the page's OSC 52 handler decodes (base64 → UTF-8) and writes via `copyTextToClipboard` (`lib/clipboard.ts:949-1004`: `navigator.clipboard.writeText` in secure contexts, else hidden `<textarea>` + `document.execCommand("copy")`). Then refocuses the terminal.
- **Inputs / options:** Click. Accessible names carried by the single button, verbatim: `title="Copy last assistant response as raw markdown"` (`i18n: web_live.chat.button.copy_last_assistant_response_as_raw_markdown`, `ChatPage.tsx:1889`) and `aria-label="Copy last assistant response"` (`i18n: web_live.chat.button.copy_last_assistant_response`, `ChatPage.tsx:1890`); visible label "copy last response" (`i18n: web_live.chat.button.copy_last_response`) / "copied".
- **Outputs / side effects:** Clipboard write; `copyState` "copied" label.
- **Config / env:** n/a.
- **Edge cases / guards:** No-op unless the socket is OPEN; OSC 52 "read" (`?`) or empty payloads are ignored so the TUI cannot read the clipboard (`ChatPage.tsx:590-615`).
- **Rebuild notes:** Drive a TUI command and intercept OSC 52. Better: fetch the last assistant message from the gateway API and copy directly, with a rendered/raw toggle.

### Clipboard keyboard shortcuts (copy / paste / OSC 52)  `id: web-a.chat.clipboard-shortcuts`
- **Surface:** Web dashboard
- **Where:** `/chat` terminal, `term.attachCustomKeyEventHandler` (`ChatPage.tsx:685-795`), OSC 52 handler (`ChatPage.tsx:590-615`), host `paste`/`dragover`/`drop` listeners (`ChatPage.tsx:665-667`).
- **What it does:** Provides four clipboard paths: selection copy via Ctrl/Cmd+C, Ctrl/Cmd+Shift+C, paste via Ctrl/Cmd+V and Ctrl/Cmd+Shift+V (image-aware), and OSC 52 writes from the TUI.
- **How it works:** `resolvePtyKeyboardShortcut(ev, isMac, hasSelection)` (`lib/pty-keyboard-shortcuts.ts:291-326`) returns `copy` for Cmd+C (mac, no ctrl) / Ctrl+C (others, no alt/meta) **only when xterm has a selection**; without a selection Ctrl+C reaches the TUI as SIGINT. Ctrl/Cmd+Shift+C also copies. Copy uses `copyTextToClipboard(selection)` synchronously in the keydown (preserves user activation), then `term.clearSelection()`. Paste: Ctrl/Cmd+V (bare) and Ctrl/Cmd+Shift+V both `preventDefault` and run `navigator.clipboard.read()`; any `image/*` item becomes a `File("clipboard.<ext>")` and goes through image upload (entry `web-a.chat.image-paste-drop`); otherwise `readText()` → `term.paste(text)`. Right-click selects the word under the pointer; holding Option (macOS) / Alt forces native selection even when the TUI enables mouse tracking (`macOptionClickForcesSelection`). Bare DOM `paste` events on the host are only intercepted when they carry image files.
- **Inputs / options:** Keys: `Ctrl+C`/`Cmd+C` (with selection), `Ctrl+Shift+C`/`Cmd+Shift+C`, `Ctrl+V`/`Cmd+V`, `Ctrl+Shift+V`/`Cmd+Shift+V`; right-click; Option/Alt-drag.
- **Outputs / side effects:** Clipboard read/write; console warnings `[dashboard clipboard] direct copy failed`, `[dashboard clipboard] OSC 52 write failed`, `[dashboard clipboard] malformed OSC 52 payload`, `[dashboard clipboard] paste failed: …`.
- **Config / env:** n/a.
- **Edge cases / guards:** Insecure (plain-HTTP) contexts fall back to `execCommand`; `navigator.clipboard.read` may be unavailable → text-only paste. Ctrl+W is *not* remapped (browser reserved).
- **Rebuild notes:** Custom key handler that short-circuits copy/paste before xterm; OSC 52 write-only. Better: a visible "Paste image" affordance and a clipboard permission prompt explainer.

### Word-delete shortcuts (Ctrl+Backspace / Ctrl+Delete)  `id: web-a.chat.word-delete-shortcuts`
- **Surface:** Web dashboard
- **Where:** `/chat` terminal keydown handler (`ChatPage.tsx:717-735`).
- **What it does:** Makes Ctrl+Backspace delete the previous word and Ctrl+Delete delete the next word in the TUI composer.
- **How it works:** `resolvePtyKeyboardShortcut` returns `delete-word-backward` for Ctrl+Backspace (no shift/alt/meta) → sends `\x17` (Ctrl-W, readline unix-word-rubout); `delete-word-forward` for Ctrl+Delete → sends `\x1bd` (Alt-d, kill-word). Sending goes through `sendPtyShortcutSequence(ws, ptyState, seq)` (`lib/pty-keyboard-shortcuts.ts:331-343`) which requires socket OPEN and state `open`.
- **Inputs / options:** `Ctrl+Backspace`, `Ctrl+Delete`.
- **Outputs / side effects:** Control bytes on the PTY.
- **Config / env:** n/a.
- **Edge cases / guards:** Ctrl+W itself cannot be captured in a browser tab (closes the tab) — the desktop app is recommended for that muscle memory.
- **Rebuild notes:** Map browser chords to readline sequences. Better: configurable keymap.

### Image paste / drag-and-drop upload → `/image`  `id: web-a.chat.image-paste-drop`
- **Surface:** Web dashboard
- **Where:** `/chat` terminal host: paste (Ctrl/Cmd+V, context-menu paste) and drag-drop of image files (`ChatPage.tsx:617-668`); banner errors "Image upload failed: <message>" and "Image uploaded, but chat is not connected — try again.".
- **What it does:** Lets the user attach images from the browser clipboard or desktop by uploading the bytes to the server and then typing `/image <path>` into the TUI for each file.
- **How it works:** `imageFilesFromTransfer(DataTransfer)` (`lib/chatImagePaste.ts:463-486`) collects `image/*` items/files (deduped by name+type+size+lastModified); `transferMayContainImage` gates `dragover` (`dropEffect="copy"`). `uploadChatImage(file, profile)` (`lib/chatImagePaste.ts:545-587`) rejects empty blobs and files >25 MiB ("image too large (max 25 MB)"), reads a data URL, POSTs JSON `{data_url, filename}` to `/api/chat/image-upload?profile=…` via `authedFetch`, expects `{path,bytes,name,mime_type}`. `driveImageAttach(paths)` then sends `/image <path>`, waits 100 ms, sends `\r`, waits 40 ms, per file, and refocuses the terminal.
- **Inputs / options:** Paste; drop; MIME→ext map `png,jpg,gif,webp,bmp` (`IMAGE_MIME_EXT`).
- **Outputs / side effects:** Files written under `<HERMES_HOME or profile home>/images/dashboard_<YYYYmmdd_HHMMSS>_<hex4>_<stem><ext>`; `/image` commands typed into the TUI (the TUI shows an attachment chip — TUI shard).
- **Config / env:** `profile` query scopes the target home.
- **Edge cases / guards:** Uploads abort on unmount (`imageUploadDisposed`); if the socket is not OPEN after upload the banner says the image is uploaded but not attached.
- **Rebuild notes:** Upload-then-command pattern. Better: send attachments through the gateway session API and render thumbnails in a native composer.

### `POST /api/chat/image-upload`  `id: web-a.chat.image-upload-api`
- **Surface:** API
- **Where:** `POST /api/chat/image-upload[?profile=<name>]` (`web_server.py:2781-2828`).
- **What it does:** Persists a base64 data-URL image into the images directory the TUI's `/image` command can read.
- **How it works:** Body model `ChatImageUpload{data_url:str, filename?:str}`. `_decode_chat_image_upload` (`web_server.py:2767-2778`): `_decode_data_url` (must start `data:`, contain `,`, `;base64`; strict base64; ≤100 MiB), MIME must start `image/`, size ≤ `_CHAT_IMAGE_UPLOAD_MAX_BYTES` 25 MiB ("Image is too large; cap is 25 MB" → 413), extension sniffed from magic bytes (PNG/JPEG/GIF87a/GIF89a/BMP/RIFF-WEBP) and must be in `{.png,.jpg,.jpeg,.gif,.webp,.bmp}` else 400 "Unsupported image type". Filename sanitised (`_sanitize_chat_image_filename`: basename only, control chars → `_`, strip dots; then `[^A-Za-z0-9_.-]+`→`_`, default `pasted-image`). Written to `<home>/images/dashboard_<ts>_<token_hex(4)>_<stem><ext>` inside `_profile_scope(profile)` in a worker thread.
- **Inputs / options:** `data_url`, `filename`, query `profile`.
- **Outputs / side effects:** `{ok:true, path, name, bytes, mime_type}`; 403 "Image directory is not writable", 500 "Could not create image directory: …"/"Could not write image: …".
- **Config / env:** `HERMES_HOME`, profile dirs.
- **Edge cases / guards:** Extension is derived from content, never from the declared MIME/filename.
- **Rebuild notes:** Validate by magic bytes, cap size, sanitise names, scope to profile home.

### `?learn=<text>` seed → `/learn` command  `id: web-a.chat.learn-seed`
- **Surface:** Web dashboard
- **Where:** `/chat?learn=<text>` (set by the Skills page "Learn a skill" panel); handled in `ws.onopen` (`ChatPage.tsx:1238-1256`).
- **What it does:** When the terminal connects, automatically types `/learn <text>` + Enter so the agent starts learning a skill from the given text.
- **How it works:** Reads `searchParams.get("learn")`, removes the param from the URL (`replace:true`), and after an 800 ms delay (so Ink's composer has mounted) sends `` `/learn ${text}`.trim() + "\r" `` over the socket. `/learn` resolves via `command.dispatch` in the TUI/gateway as a normal agent turn (`tui_gateway/methods_tools.py:617` handles `learn`).
- **Inputs / options:** Query `learn`.
- **Outputs / side effects:** One agent turn started.
- **Config / env:** n/a.
- **Edge cases / guards:** Send failures are swallowed ("user can retype"); only runs once per socket open.
- **Rebuild notes:** URL-param-to-command bridge. Better: a generic `?cmd=` seed with confirmation.

### Mobile IME / replacement-input normalisation  `id: web-a.chat.mobile-input`
- **Surface:** Web dashboard
- **Where:** `/chat` terminal textarea listeners (`ChatPage.tsx:866-887`), `forwardPtyData` (`ChatPage.tsx:1441-1481`), `createPtyCompositionForwarder` (`lib/pty-composition.ts`), IME guard (`ChatPage.tsx:843-848`).
- **What it does:** Makes typing on phone keyboards (Gboard word replacement, autocorrect, CJK/Cyrillic IME) produce correct text in the TUI instead of duplicated or dropped characters.
- **How it works:** `beforeinput` with `inputType` in `{insertReplacementText, insertFromComposition, insertCompositionText}` or (mobile UA and `insertText` with >1 chars) arms a `MOBILE_REPLACEMENT_WINDOW_MS=350` window (`lib/pty-mobile-input.ts:218-231`). Within it, `normalizePtyMobileInput(data, currentLine, active)` (`lib/pty-mobile-input.ts:258-279`) detects when the incoming text is a re-emission of the tracked input line (case-insensitive prefix or repeated last word), collapses a duplicated final word (≥2 chars), and sends `DEL×len(line) + replacementLine` so the TUI line is rewritten. `updatePtyInputLine` tracks the composer line locally (resets on `\r`/`\n`/`Ctrl-U`/any ESC sequence). `compositionend` text is forwarded via a 16 ms deferred fallback unless xterm already emitted the same `onData` (`pty-composition.ts:629-676`). A capture-phase keydown listener stops propagation of `keyCode 229`/`key "Process"` so React's root delegation cannot break xterm's IME handling (#52111).
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** Rewritten byte sequences on the PTY.
- **Config / env:** n/a.
- **Edge cases / guards:** Composed text sent via the fallback bypasses the replacement window (`useMobileReplacement=false`).
- **Rebuild notes:** Track the visible input line client-side and diff against IME replacements. Better: let the TUI expose a line-edit RPC so the browser sets the composer text directly.

### Soft-keyboard inset (mobile viewport)  `id: web-a.chat.keyboard-inset`
- **Surface:** Web dashboard
- **Where:** `/chat` on phones; `syncKeyboardInset` (`ChatPage.tsx:992-1020`), visualViewport listeners attached only while active (`ChatPage.tsx:1548-1568`), `lib/keyboard-inset.ts`.
- **What it does:** Keeps the TUI input line visible above the on-screen keyboard on iOS/Android.
- **How it works:** `computeKeyboardInset({height, offsetTop}, innerHeight)` = `round(layoutHeight − vv.height − vv.offsetTop)`, treated as 0 below `KEYBOARD_INSET_MIN_PX=80` (`keyboard-inset.ts:853-864`). The inset is applied as `paddingBottom` on the terminal wrapper, which shrinks the host → ResizeObserver refit → RESIZE to PTY → Ink redraws above the keyboard; `term.scrollToBottom()` keeps the input line in view; `shouldPinScroll(inset>0)` pins `window.scrollTo(0,0)`. `index.html:7-8` sets `viewport … interactive-widget=resizes-content` so Android Chrome 108+ resizes natively (inset ≈ 0 there).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Wrapper padding; reset to "" on deactivation/unmount.
- **Config / env:** n/a.
- **Edge cases / guards:** Listeners are attached only while `/chat` is the active route so the scroll pin does not fire on other pages' inputs.
- **Rebuild notes:** visualViewport-driven bottom padding. Better: CSS `env(keyboard-inset-height)` when supported.

### Mouse-report suppression & wheel scrolling  `id: web-a.chat.mouse-report-drop`
- **Surface:** Web dashboard
- **Where:** `/chat` terminal: `attachCustomWheelEventHandler` (`ChatPage.tsx:797-810`), `SGR_MOUSE_RE` filter (`ChatPage.tsx:1440-1449`).
- **What it does:** Mouse wheel scrolls the browser-side scrollback (5000 lines) instead of being sent to the TUI; any SGR mouse report xterm emits is dropped so stray bytes never appear in the composer.
- **How it works:** Wheel: `step = max(1, round(|deltaY|/50))`, `term.scrollLines(±step)`, `preventDefault`. Data: `/^\x1b\[<(\d+);(\d+);(\d+)([Mm])$/` matches are swallowed before the blocked-input check. Server side sets `HERMES_TUI_DISABLE_MOUSE=1` and `HERMES_TUI_INLINE=1` so the TUI runs in inline (non-alternate-screen) mode and does not enable mouse tracking (`web_server.py:16606-16612`; consumed in `ui-tui/src/config/env.ts:46,63`).
- **Inputs / options:** Wheel; trackpad.
- **Outputs / side effects:** n/a.
- **Config / env:** `HERMES_TUI_DISABLE_MOUSE`, `HERMES_TUI_INLINE` (child env).
- **Edge cases / guards:** `deltaY===0` events pass through.
- **Rebuild notes:** Disable terminal mouse mode and scroll xterm locally. Better: hybrid — forward wheel to the TUI only when an overlay/picker is open.

### Desktop chat side panel (collapse / "panel")  `id: web-a.chat.side-panel`
- **Surface:** Web dashboard
- **Where:** `/chat` at ≥1024px: right column `#chat-side-panel` (`role="complementary"`, `aria-label="Model & tools"` = `t.app.modelToolsSheetTitle + " " + t.app.modelToolsSheetSubtitle`, `i18n: app.modelToolsSheetTitle`="Model", `app.modelToolsSheetSubtitle`="& tools"), width `lg:w-60`. Header row: icon button **X** `aria-label="Collapse chat side panel"`, `title="Collapse side panel"` (`ChatPage.tsx:1944-1956`). When collapsed: floating top-right button with PanelRight icon and label "panel", `title="Show side panel (model + sessions)"`, `aria-label="Show chat side panel"` (`ChatPage.tsx:1911-1935`). Crawl confirms "Collapse chat side panel".
- **What it does:** Shows/hides the model card, reasoning picker and session switcher next to the terminal; remembers the choice.
- **How it works:** `chatPanelCollapsed` state initialised from `localStorage["hermes-chat-panel-collapsed"] === "1"`; `toggleChatPanel` writes `"1"|"0"` (`ChatPage.tsx:311-322`). Panel renders `<ChatSidebar>` (fixed) and `<ChatSessionList>` (fills remaining height) (`ChatPage.tsx:1957-1976`). Below 1024px (`narrow`, `matchMedia("(max-width: 1023px)")`) the column is replaced by the mobile sheet.
- **Inputs / options:** Buttons "Collapse side panel" (X) and "panel". Accessible names, verbatim: the X icon button is `aria-label="Collapse chat side panel"` (`i18n: web_live.chat.button.collapse_chat_side_panel`, `ChatPage.tsx:1950`) with `title="Collapse side panel"` (`i18n: web_live.chat.button.collapse_side_panel`, `ChatPage.tsx:1951`); the collapsed-state floating button is `aria-label="Show chat side panel"` with `title="Show side panel (model + sessions)"` and visible label "panel" (`ChatPage.tsx:1911-1935`) — these three have no live-crawl catalog key because the button only renders while collapsed.
- **Outputs / side effects:** `localStorage["hermes-chat-panel-collapsed"]`.
- **Config / env:** n/a.
- **Edge cases / guards:** Collapsing does not disconnect the sidebar sockets (component unmounts → sockets close; reopening reconnects).
- **Rebuild notes:** Persisted collapse toggle. Better: resizable splitter.

### Mobile "Model & tools" sheet  `id: web-a.chat.mobile-model-tools-sheet`
- **Surface:** Web dashboard
- **Where:** `/chat` below 1024px: page-header end-slot button with PanelRight icon and label "Model & tools" (`aria-expanded`, `aria-controls="chat-side-panel"`, `ChatPage.tsx:462-486`); right-side sheet portaled to `document.body` (`ChatPage.tsx:1720-1800`): title "Model" / "& tools" (two lines), close icon button `aria-label="Close model and tools"` (`i18n: app.closeModelTools`), full-screen backdrop button with the same aria-label.
- **What it does:** Gives phones access to the model picker, reasoning picker and session list in a slide-in sheet.
- **How it works:** `mobilePanelOpen = isActive && mobilePanelOpenRaw` (derived so leaving the route releases the body scroll lock); opening sets `document.body.style.overflow="hidden"` and an `Escape` keydown closes (`ChatPage.tsx:436-448`); resizing to ≥1024px force-closes (`ChatPage.tsx:450-458`). Sheet: fixed, `w-64`, `z-[60]`, `translate-x-full` when closed, contains `<ChatSidebar>` then `<ChatSessionList onPicked={closeMobilePanel}>`. The header button is only written into the header slot while `/chat` is active AND narrow (`useLayoutEffect` `ChatPage.tsx:462-486`) to avoid clobbering other pages' header buttons.
- **Inputs / options:** Header button "Model & tools"; close X; backdrop tap; `Escape`.
- **Outputs / side effects:** Body scroll lock while open.
- **Config / env:** n/a.
- **Edge cases / guards:** Picking a session in the list closes the sheet.
- **Rebuild notes:** Portaled drawer with escape/backdrop close. Better: swipe-to-dismiss.

### Chat sidebar — model card and connection badge  `id: web-a.chat.sidebar-model-card`
- **Surface:** Web dashboard
- **Where:** Side panel → first `Card`: small label "model", a ghost button showing the model short name (last `/` segment; "—" when unknown) with a ChevronDown, `title` = full model string or "switch model" when unknown (`ChatSidebar.tsx:451-482`); right-aligned `Badge` with connection state text `idle|connecting|live|closed|error` (`STATE_LABEL` `ChatSidebar.tsx:69-75`; tones secondary/warning/success/secondary/destructive). Crawl shows "MODEL — live".
- **What it does:** Shows which model new chats will use and whether the sidebar's JSON-RPC sidecar is connected; clicking the name opens the model picker.
- **How it works:** `refreshEffectiveModel` (`ChatSidebar.tsx:157-171`) calls `api.getModelInfo(profile)` → `GET /api/model/info?profile=` and uses `model` + `capabilities.supports_reasoning`; re-read on mount, on `version` bump, after picker close/apply. The badge state comes from `GatewayClient.onState` (entry `web-a.chat.sidebar-sidecar-ws`).
- **Inputs / options:** Button (model name) → opens `ModelPickerDialog`.
- **Outputs / side effects:** none directly.
- **Config / env:** `model.default` / `model.provider` in the profile's `config.yaml`.
- **Edge cases / guards:** Deliberately does *not* use the sidecar's `session.info.model` (a stale one-time snapshot); falls back to it only when REST yields nothing.
- **Rebuild notes:** REST-backed model badge + WS state pill.

### Chat sidebar — JSON-RPC sidecar (`/api/ws`)  `id: web-a.chat.sidebar-sidecar-ws`
- **Surface:** API / Web dashboard
- **Where:** Opened by `ChatSidebar.tsx:187-236` through `GatewayClient` (`lib/gatewayClient.ts:33-62`, extends `JsonRpcGatewayClient` from `apps/shared`); server `gateway_ws` (`web_server.py:17618-17643`) → `tui_gateway.ws.handle_ws`.
- **What it does:** A lightweight second connection used only for the live/closed badge and credential warnings; it creates a throwaway gateway session that is reaped on disconnect.
- **How it works:** URL `ws(s)://<host><base>/api/ws?token=…|ticket=…` (`buildWsAuthParam`). After `connect()` it sends `session.create` with `sidecarSessionCreateParams(profile)` = `{close_on_disconnect:true, source:"tool", profile?}` (`ChatSidebar.tsx:104-110`). Subscribes to events `session.info` (`{cwd, model, provider, credential_warning, title}` merged into `info`) and `error` (`payload.message` → banner). Newline-delimited JSON-RPC, request ids prefixed `w`. Server rejects with `4403` when embedded chat disabled or host/origin/peer not allowed, `4401` on bad credential; the authenticated identity is stamped on the socket for privileged RPCs. A `version` counter rebuilds the client on manual reconnect or when `channel`/`profile` change (`ChatSidebar.tsx:177-186`).
- **Inputs / options:** n/a (button "reconnect events feed" also rebuilds this client).
- **Outputs / side effects:** One extra gateway session (`source: tool`) per open chat tab; `info.credential_warning` shown in the red banner card.
- **Config / env:** n/a.
- **Edge cases / guards:** Errors show `e.message` in the banner; the terminal keeps working regardless.
- **Rebuild notes:** Optional status sidecar. Better: reuse the PTY child's gateway session instead of a second one.

### Chat sidebar — events feed (`/api/pub` → `/api/events`)  `id: web-a.chat.sidebar-events-feed`
- **Surface:** API / Web dashboard
- **Where:** Subscriber opened at `ChatSidebar.tsx:246-395` (`buildWsUrl("/api/events", {channel})`); publisher is the PTY child (`tui_gateway.entry` via `HERMES_TUI_SIDECAR_URL`) hitting `pub_ws` (`web_server.py:17657-17682`); `events_ws` (`web_server.py:17685-17720`); fan-out `_broadcast_event` (`web_server.py:16791-16803`). Banner card (red, AlertCircle) with button **"reconnect events feed"** (RefreshCw icon, `ChatSidebar.tsx:522-534`).
- **What it does:** Delivers every dispatcher event emitted by the terminal's gateway to the React sidebar on the same channel; the sidebar uses `session.info` (live title) and `dashboard.new_session_requested`.
- **How it works:** Frames are JSON-RPC envelopes `{method:"event", params:{type, payload}}`; `session.info` → `titleFromSessionInfoPayload` → `onSessionTitleChange`; `dashboard.new_session_requested` → `onDashboardNewSessionRequest` (= `startFreshDashboardChat`). Reconnect policy (`lib/events-reconnect.ts`): base 1 s doubling to 30 s cap, max 15 attempts, connect timeout 15 s (covers ticket minting), auth codes `4401`/`4403` terminal, `1000` not retried, everything else retried. Banner strings (only ever overwriting its own messages, `isEventsFeedMessage` = startsWith "events feed "): "events feed disconnected — the chat title may not update", "events feed disconnected — reconnecting in Ns…", "events feed rejected (<code>) — reload the page", "events feed disconnected — gave up after 15 attempts, reload the page". Server: `/api/pub` requires a valid `channel` (`4400` otherwise), relays each `receive_text()` to all subscribers; `/api/events` registers the socket in `app.state` channel map and blocks on `receive_text()` until disconnect.
- **Inputs / options:** Button "reconnect events feed".
- **Outputs / side effects:** Page header title updates; fresh chat on new-session request.
- **Config / env:** n/a.
- **Edge cases / guards:** Tickets are re-minted on every attempt (single-use, 30 s TTL); superseded sockets' late close events are ignored via generation counters; `4401` in loopback mode triggers the one-shot page reload.
- **Rebuild notes:** Pub/sub relay keyed by channel. Better: multiplex events over the sidecar socket and include tool-call/todo events in the sidebar UI (the file header still describes a "tool-call list" that is no longer rendered).

### Chat sidebar — reasoning effort picker  `id: web-a.chat.sidebar-reasoning-picker`
- **Surface:** Web dashboard
- **Where:** Side panel → Card shown only when `capabilities.supports_reasoning` is true: Brain icon + label "reasoning" and a `Select` (`components/ReasoningPicker.tsx:107-124`).
- **What it does:** Sets `agent.reasoning_effort` in the profile's config so the next chat session uses that thinking level.
- **How it works:** On mount / model change / `refreshKey` bump it reads `api.getConfig(profile)` and normalises `agent.reasoning_effort` (`normalizeEffort`: empty/unknown → `medium`). On select: optimistic set, read-modify-write the whole config via `api.saveConfig({...cfg, agent:{...agent, reasoning_effort}}, profile)` (`PUT /api/config?profile=`), revert on failure, then `onChanged(effort)` → sidebar notice "Reasoning effort set to <effort>. Run /new or refresh the page to apply it to this chat." (`ChatSidebar.tsx:496-500`).
- **Inputs / options:** Options (`lib/reasoning-effort.ts:107-116`): `none` "Off (no thinking)", `minimal` "Minimal", `low` "Low", `medium` "Medium", `high` "High", `xhigh` "Extra High", `max` "Max", `ultra` "Ultra". Disabled until loaded or while saving.
- **Outputs / side effects:** `config.yaml` key `agent.reasoning_effort`.
- **Config / env:** `agent.reasoning_effort`.
- **Edge cases / guards:** Same value re-selected is a no-op; the running session is not changed (TUI `/reasoning` does that).
- **Rebuild notes:** Config-backed select. Better: apply live via a gateway RPC.

### Chat sidebar — notices (model / reasoning applied on next session)  `id: web-a.chat.sidebar-model-notice`
- **Surface:** Web dashboard
- **Where:** Side panel → warning Card (AlertCircle) (`ChatSidebar.tsx:503-512`).
- **What it does:** Tells the user that a config change was saved but the running chat keeps its model until `/new` or reload.
- **How it works:** `modelNotice` set to "Model set to <short>. Run /new or refresh the page to apply it to this chat." when the reload confirm is cancelled (`ChatSidebar.tsx:572-581`) or "Reasoning effort set to …" from the picker; cleared on reconnect or new picker apply.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Inline notice. Better: an "Apply now" button that runs `/new`.

### Chat sidebar — model picker (switch main model from chat)  `id: web-a.chat.sidebar-model-picker`
- **Surface:** Web dashboard
- **Where:** Side panel model button → `ModelPickerDialog` with default title "Switch Model" and `alwaysGlobal` (`ChatSidebar.tsx:538-570`); dialog anatomy in entry `web-a.models.model-picker-dialog`.
- **What it does:** Changes the profile's main model over REST and offers to reload the page so a fresh chat boots with it.
- **How it works:** `loader={() => api.getModelOptions(profile)}`; `onApply` → `api.setModelAssignment({confirm_expensive_model, scope:"main", provider, model}, profile)` (`POST /api/model/set`); if `confirm_required` the dialog shows the expensive-model confirm; otherwise `refreshEffectiveModel()` and `setPendingReloadModel(short)` → `ModelReloadConfirm` (entry `web-a.chat.model-reload-confirm`). Closing the dialog also refreshes the badge.
- **Inputs / options:** see picker entry.
- **Outputs / side effects:** `config.yaml` `model.provider`/`model.default` (+ `base_url`/`key_env` handling — entry `web-a.models.api.model-set`).
- **Config / env:** n/a.
- **Edge cases / guards:** The sidecar `config.set` RPC path exists in the dialog but is not used here (comment `ChatSidebar.tsx:540-542`).
- **Rebuild notes:** Shared picker in standalone mode.

### "Switch model?" reload confirmation  `id: web-a.chat.model-reload-confirm`
- **Surface:** Web dashboard
- **Where:** `components/ModelReloadConfirm.tsx` — `ConfirmDialog` titled "Switch model?", body "Switching to <model> starts a fresh chat. Your current chat stays in your Sessions list and the agent's memory is kept. Reload now to apply it?" (Models page passes its own description), buttons "Cancel" / "Reload".
- **What it does:** After a main-model change, asks before a full page reload (which spawns a fresh PTY booting from the new config).
- **How it works:** `open = model !== null`; Confirm → `window.location.reload()`; Cancel → caller sets the "Model set to …" notice. Built on `ConfirmDialog` (entry `web-a.shared.confirm-dialog`).
- **Inputs / options:** "Reload", "Cancel", `Escape`, backdrop click.
- **Outputs / side effects:** Full reload.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Confirm-before-reload.

### Chat session switcher (side panel "SESSIONS" list)  `id: web-a.chat.session-list`
- **Surface:** Web dashboard
- **Where:** Side panel → header "Sessions" (`i18n: sessions.title`, rendered uppercase "SESSIONS"), icon button Refresh (`aria-label`/`title` = `i18n: common.refresh` "Refresh", spins while loading), outlined button **"New chat"** (`i18n: sessions.newChat`, MessageSquarePlus icon), then a scrollable list of `ListItem` rows (`components/ChatSessionList.tsx`). Empty state "No sessions yet" (`i18n: sessions.noSessions`); loading "Loading..." (`i18n: common.loading`) with spinner; error row (AlertCircle + message) with button "Retry" (`i18n: common.retry`). Crawl: "SESSIONS New chat No sessions yet".
- **What it does:** Lists the 30 most recent sessions of the active profile and switches the terminal to one, or starts a fresh chat.
- **How it works:** `api.getSessions(30, 0, profile, "recent")` → `GET /api/sessions?limit=30&offset=0&order=recent[&profile=]`; monotonic request token drops stale responses. Row label = `title` (unless "Untitled") else `preview` else "Untitled session" (`i18n: sessions.untitledSession`); meta line = `timeAgo(last_active)` · "<n> msgs" (when >0) · `source` (when not `cli`). Active row (`aria-current="true"`, `border-l-2 border-primary`) is the current `?resume`. Pick → `setSearchParams(resume=id)` (push, not replace) unless already active; "New chat" → `onNewChat` = `startFreshDashboardChat` (deletes `resume`, forces fresh PTY with rotated attach token, `ChatPage.tsx:283-299`).
- **Inputs / options:** Refresh button; "New chat"; row click.
- **Outputs / side effects:** URL `?resume=` change → terminal respawn; refetch on mount, profile change, Refresh.
- **Config / env:** management profile.
- **Edge cases / guards:** Read-only surface — delete/rename/export live on the Sessions page (component header comment).
- **Rebuild notes:** Recent-list + deep-link switch. Better: live refresh via events, search box, pinned sessions.

### `dashboard.new_session_requested` (TUI idle-exit hotkey → fresh chat)  `id: web-a.chat.new-session-request-event`
- **Surface:** Core / TUI → Web dashboard
- **Where:** Emitted by the TUI when the user presses Ctrl+C or Ctrl+D on an idle composer in dashboard mode (`ui-tui/src/app/useInputHandlers.ts:653-669`, `DASHBOARD_TUI_MODE` from `HERMES_TUI_DASHBOARD`), published through `/api/pub`, consumed in `ChatSidebar.tsx:414-416`.
- **What it does:** Instead of killing the terminal, an idle Ctrl+C/Ctrl+D in the embedded chat starts a fresh dashboard chat.
- **How it works:** Payload `{reason:"idle_exit_hotkey"}` with `session_id`; sidebar calls `startFreshDashboardChat` (clear `resume`, `fresh=1`, rotated token).
- **Inputs / options:** `Ctrl+C` (idle, no selection), `Ctrl+D` inside the terminal.
- **Outputs / side effects:** New PTY child.
- **Config / env:** `HERMES_TUI_DASHBOARD=1`.
- **Edge cases / guards:** Ctrl+C during a live turn interrupts the turn instead; Ctrl+C with input clears the input (`useInputHandlers.ts:640-651`).
- **Rebuild notes:** Event-driven restart. Better: confirm before discarding a long unsaved session.

### Live session title in the page header  `id: web-a.chat.session-title-header`
- **Surface:** Web dashboard
- **Where:** Header `<h1>` on `/chat` (replaces "Chat" with the session title).
- **What it does:** Shows the current conversation's title as the page title while chatting.
- **How it works:** `usePageHeader().setTitle(title)` when active (`ChatPage.tsx:381-389`); title sourced from `GET /api/sessions/{resume}` (`normalizeSessionTitle`) and updated live from `session.info` events (`titleFromSessionInfoPayload`, `lib/chat-title.ts`). Scoped by `titleScope = channel\0reconnectNonce` so stale titles from a previous PTY are ignored. Cleared when the route deactivates.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty/whitespace titles → null (falls back to "Chat").
- **Rebuild notes:** Header title override hook.

### Profile-scoped chat  `id: web-a.chat.profile-scope`
- **Surface:** Web dashboard / Core
- **Where:** Global profile switcher (App shell; `contexts/ProfileProvider.tsx`) → `?profile=<name>`; `ChatPage.tsx:371-378` (`useProfileScope`), `_resolve_chat_argv` profile branch (`web_server.py:16556-16585`).
- **What it does:** Runs the embedded chat under a different Hermes profile (its own config, keys, skills, memory, sessions) than the dashboard process.
- **How it works:** `channel` memo depends on `scopedProfile`, so switching profiles remounts the terminal (fresh scoped session). `profile` is sent on `/api/pty`; server resolves the profile dir (`_resolve_profile_dir`, unknown → "Chat unavailable: …" + 1011), sets `HERMES_HOME=<profile dir>` in the child env, re-applies that profile's terminal config bridge (`apply_terminal_config_to_env` inside `_config_profile_scope`), and **skips** `HERMES_TUI_GATEWAY_URL` so the child spawns its own gateway. Sidebar, session list, model info, reasoning picker and image upload all pass the same `profile`.
- **Inputs / options:** Profile switcher (out of scope) / `?profile=`.
- **Outputs / side effects:** Separate PTY registry key (`attach\0profile\0resume`).
- **Config / env:** `HERMES_HOME`, profile dirs under `~/.hermes/profiles/<name>`.
- **Edge cases / guards:** `profile=current` is treated as unscoped.
- **Rebuild notes:** Env-based profile isolation per child.

### Terminal theme colours  `id: web-a.chat.theme-terminal-colors`
- **Surface:** Config / Web dashboard
- **Where:** Dashboard theme YAML/JSON fields `terminalBackground`, `terminalForeground` (`themes/types.ts:180-185`), applied at `ChatPage.tsx:357-363`.
- **What it does:** Lets a dashboard theme recolour the terminal chrome (background, foreground, cursor, selection).
- **How it works:** `useTheme().theme.terminalBackground ?? "#000000"`, `terminalForeground ?? "#f0e6d2"`; `buildTerminalTheme` derives cursor/cursorAccent/selection; live updates through `term.options.theme`.
- **Inputs / options:** Theme picker (app shell).
- **Outputs / side effects:** Wrapper background uses the same colour; the "copy last response"/"panel" buttons use `terminalFg` as text colour.
- **Config / env:** `dashboard.theme` (config, live value "default").
- **Edge cases / guards:** Only 7-char hex gets the `44` alpha selection; otherwise the raw value is used.
- **Rebuild notes:** Two theme tokens → xterm theme.

### Plugin slots on the Chat page  `id: web-a.chat.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `<PluginSlot name="chat:top"/>` (`ChatPage.tsx:1808`) above the banner and `<PluginSlot name="chat:bottom"/>` (`ChatPage.tsx:1978`) below the terminal row.
- **What it does:** Lets dashboard plugins inject React content above/below the terminal.
- **How it works:** `@/plugins` slot registry (plugins shard).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** n/a.
- **Rebuild notes:** Named slot components.

### What runs inside the terminal (TUI child process contract)  `id: web-a.chat.tui-inside-terminal`
- **Surface:** Core / TUI
- **Where:** Everything visible inside the xterm pane: Hermes banner, composer, slash popover, model picker overlay, tool rows, markdown, thinking blocks, todo panel, clarify/sudo/approval prompts, voice — rendered by `ui-tui/src` (components listed at `ui-tui/src/components/*`: `textInput.tsx`, `todoPanel.tsx`, `modelPicker.tsx`, `prompts.tsx`, `streamingAssistant.tsx`, `thinking.tsx`, `queuedMessages.tsx`, `skillsHub.tsx`, `pluginsHub.tsx`, `agentsOverlay.tsx`, `billingOverlay.tsx`, `subscriptionOverlay.tsx`, `petPicker.tsx`, …).
- **What it does:** The dashboard Chat page is a byte-for-byte mirror of `hermes --tui`; every TUI feature ships automatically (per `hermes_cli/pty_bridge.py` module docstring).
- **How it works:** Env contract set by `_resolve_chat_argv` (entry `web-a.chat.pty-websocket`): `HERMES_TUI_DASHBOARD=1` (enables dashboard-mode behaviours such as the idle-exit hotkey event), `HERMES_TUI_INLINE=1` (inline rendering so xterm scrollback works), `HERMES_TUI_DISABLE_MOUSE=1`, `COLORTERM=truecolor`, `HERMES_TUI_RESUME`, `HERMES_TUI_GATEWAY_URL`, `HERMES_TUI_SIDECAR_URL`, `HERMES_TUI_ACTIVE_SESSION_FILE`, `NODE_ENV=production`. Commands the dashboard itself types: `/copy`, `/image <path>`, `/learn <text>`; `\x0c` (Ctrl-L) for redraw.
- **Inputs / options:** All TUI keys/commands — documented by the TUI shard.
- **Outputs / side effects:** n/a here.
- **Config / env:** as above.
- **Edge cases / guards:** First launch may run `npm install`/build ("Installing TUI dependencies…"), serialised by `_get_chat_argv_lock`.
- **Rebuild notes:** Reuse the terminal UI unchanged; pass behaviour flags through env. (See Handoffs.)

### WebSocket auth & boundary gates (token / ticket / internal, host-origin, peer)  `id: web-a.chat.ws-auth`
- **Surface:** API
- **Where:** `_ws_auth_reason` (`web_server.py:16396-16505`), `_ws_auth_mode` (`16366`), `_ws_host_origin_reason` (`16302`), `_ws_client_reason` (`16232`), `POST /api/auth/ws-ticket` (client `getWsTicket` `lib/api.ts:206-215`), `buildWsAuthParam` (`lib/api.ts:222-229`).
- **What it does:** Authenticates and fences every dashboard WebSocket (`/api/pty`, `/api/ws`, `/api/pub`, `/api/events`).
- **How it works:** Modes: `loopback` (default bind 127.0.0.1) and `insecure` (non-loopback bind with `--insecure`) accept `?token=<_SESSION_TOKEN>` (constant-time compare; the token is injected into `index.html` as `window.__HERMES_SESSION_TOKEN__` and rotates on every server restart); `gated` (public bind with OAuth gate) rejects `?token=` and accepts `?ticket=<single-use, 30 s TTL>` minted by `POST /api/auth/ws-ticket` (cookie auth), or `?internal=<process-lifetime credential>` used only by server-spawned children (PTY child → `/api/ws`, `/api/pub`). A gateway sub-protocol form `hermes-gateway-v1` + `hermes-gateway-ticket.<ticket>` is also parsed. Host/Origin guard: `Host` header must match the bound host (or `trusted_public_hosts`); an `Origin` with http(s) scheme must match too; non-web origins (Electron `file://`, `null`) pass. Peer guard (loopback bind, no auth): client IP must be loopback (`127.0.0.1`, `::1`, `localhost`, `testclient`); missing peer → rejected fail-closed.
- **Inputs / options:** Query `token`, `ticket`, `internal`.
- **Outputs / side effects:** Audit log entries on rejection; close codes 4401/4403/4408.
- **Config / env:** `dashboard.trusted_proxies`, `dashboard.public_url`, `dashboard.oauth.*`, `dashboard.basic_auth.*` (config); `--host`, `--insecure` CLI flags (CLI shard).
- **Edge cases / guards:** Reason strings are machine-parseable (`no_credential`, `token_mismatch`, `ticket_invalid`, `internal_invalid`, `host_mismatch host=… bound=…`, `origin_mismatch origin=… bound=…`, `peer_not_loopback peer=… bound=…`, `missing_or_empty_peer`).
- **Rebuild notes:** Three credential classes + rebinding guard. Better: signed short-lived JWT in the `Sec-WebSocket-Protocol` header for all clients.

### "Session token unavailable" banner  `id: web-a.chat.token-missing-banner`
- **Surface:** Web dashboard
- **Where:** `/chat` warning strip: "Session token unavailable. Open this page through `hermes dashboard`, not directly." (`ChatPage.tsx:213-219`).
- **What it does:** Explains why chat cannot connect when the SPA was loaded without the server-injected token (e.g. opened from a static build).
- **How it works:** Lazy state initialiser checks `!window.__HERMES_SESSION_TOKEN__ && !window.__HERMES_AUTH_REQUIRED__`; the connect effect bails (`ChatPage.tsx:520-527`).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** In gated mode the token is absent by design and the ticket path is used instead.
- **Rebuild notes:** Preflight check.

### Embedded-chat feature flag  `id: web-a.chat.embedded-flag`
- **Surface:** Config / Web dashboard
- **Where:** `window.__HERMES_DASHBOARD_EMBEDDED_CHAT__` injected by `web_server.py:17919,17927` and by `web/vite.config.ts:32,57` in dev; `isDashboardEmbeddedChatEnabled()` (`lib/dashboard-flags.ts`), `_DASHBOARD_EMBEDDED_CHAT_ENABLED` (`web_server.py:659`).
- **What it does:** Historically toggled the Chat tab and `/api/ws`, `/api/pty` endpoints; now hard-wired to `true` on both sides and kept as a seam.
- **How it works:** `App.tsx:403` adds the `CHAT` nav item and the `/chat` route only when true; `SessionsPage.tsx:876` shows "Resume in Chat" only when true; server closes `/api/pty` with `4404`, `/api/ws`/`/api/pub`/`/api/events` with `4403` when false.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** Not user-configurable in v2026.8.31.
- **Rebuild notes:** Keep as a build-time constant.

### Windows: embedded chat unavailable banner  `id: web-a.chat.windows-unavailable`
- **Surface:** Web dashboard / Core
- **Where:** Terminal text on connect (`web_server.py:17461-17469`): red "Chat unavailable: the embedded terminal requires a POSIX PTY, which native Windows Python doesn't provide." and yellow "Install Hermes inside WSL2 to use the dashboard's /chat tab — the rest of the dashboard works here.", then close `1011`.
- **What it does:** Explains that the terminal needs a POSIX PTY (or `pywinpty`, see `hermes_cli/win_pty_bridge.py` import at `web_server.py:16097-16104`) on native Windows.
- **How it works:** `_PTY_BRIDGE_AVAILABLE` false → text frame + close.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** On Windows with `pywinpty` installed the ConPTY bridge is used instead (same public surface).
- **Rebuild notes:** Platform capability probe with a helpful message.

---

## B. Sessions page (`/sessions`)

### Sessions page (overview + history of conversations)  `id: web-a.sessions.page`
- **Surface:** Web dashboard
- **Where:** Sidebar nav `SESSIONS` (`i18n: app.nav.sessions` "Sessions", `App.tsx:187-192`), URL `/sessions` (also the target of the root redirect `/` and of the "Gateway Status / Active Sessions" status link, `resolve-page-title.ts:34`); header `<h1>` "Sessions" (`i18n: sessions.title`) followed by a secondary `Badge` with the total session count (`SessionsPage.tsx:995-1008`, crawl shows "Sessions 0"); header end-slot button "Prune old sessions".
- **What it does:** Central place to browse, search, inspect, rename, export, import, delete and prune conversation sessions across every source (CLI/TUI, Telegram, Discord, cron, API…), plus a live overview of connected messaging platforms.
- **How it works:** `pages/SessionsPage.tsx:815-2077`. Initial `loading=true` renders a centred spinner. Data: `loadSessions(page)` → `GET /api/sessions?limit=20&offset=<page*20>&order=created` + source filters; `loadStats()` → `GET /api/sessions/stats`; `refreshEmptyCount()` → `GET /api/sessions/empty/count`; overview poll every 5 s (`GET /api/status` + `GET /api/sessions?limit=50&offset=0…`) which also detects sessions created by other processes (`shouldRefreshSessions(prevNewest, newest)`, `lib/session-refresh.ts`) and silently refreshes the current page. Layout (top→bottom): plugin slot `sessions:top`, toast, hidden file input, dialogs, stats strip, alerts, system-action log, control bar (category segmented, source menu, view segmented, search, "Delete empty", "Import sessions", compact pagination), bulk-selection bar, list or overview, bottom pagination, plugin slot `sessions:bottom`.
- **Inputs / options:** enumerated in the entries below.
- **Outputs / side effects:** Polling traffic every 5 s while mounted.
- **Config / env:** management profile (`?profile=`) scopes every call (`lib/api.ts:70-95` includes `/api/status`; session endpoints receive `profile` explicitly via `appendProfileParam`). Server config `sessions.*` (`auto_prune`, `retention_days`, `auto_archive`, `auto_archive_days`, `vacuum_after_prune`, `min_vacuum_interval_days`, `min_interval_hours`, `write_json_snapshots`, `fts_optimize_notice`, `cjk_fts`, `search_slow_ms`, `max_resume_messages`, `max_export_messages`) governs store maintenance (live `/api/config`).
- **Edge cases / guards:** `GET /api/sessions` triggers `_maybe_auto_archive_for_profile` (config `sessions.auto_archive`) before listing (`web_routers/sessions.py:139`). List rows omit `system_prompt`/`model_config` unless `full=1`.
- **Rebuild notes:** Paginated list + FTS search + polling overview. Better: server push (SSE) for new sessions, virtualised list, column sort.

### Session store stats strip  `id: web-a.sessions.stats-strip`
- **Surface:** Web dashboard
- **Where:** Top of `/sessions`: five figures with captions "Total", "Active in store", "Archived", "Messages", and "Sources" (only when `by_source` non-empty) (`SessionsPage.tsx:1681-1716`). Crawl: "0 Total 0 Active in store 0 Archived 0 Messages".
- **What it does:** Mirrors `hermes sessions stats` in the UI.
- **How it works:** `GET /api/sessions/stats[?profile=]` (`web_routers/sessions.py:565-594`) → `{total, active_store, archived, messages, by_source}` where `total=session_count(include_archived)`, `active_store=session_count(include_archived=False)`, `archived=session_count(archived_only)`, `messages=message_count()`, `by_source=session_count_by_source(include_archived, exclude_children)`. Refreshed after delete/rename/import/prune.
- **Inputs / options:** none. **Outputs / side effects:** none.
- **Config / env:** profile.
- **Edge cases / guards:** `by_source` failures are swallowed → `{}`.
- **Rebuild notes:** One COUNT-per-figure endpoint.

### Gateway / platform alerts  `id: web-a.sessions.alerts`
- **Surface:** Web dashboard
- **Where:** Red alert box (AlertTriangle) under the stats strip (`SessionsPage.tsx:1718-1738`).
- **What it does:** Surfaces "Gateway failed to start" (`i18n: status.gatewayFailedToStart`, detail = `gateway_exit_reason`) and per-platform "<Name> error" / "<Name> disconnected" (`i18n: status.platformError` "error", `status.platformDisconnected` "disconnected", detail = `error_message`).
- **How it works:** From `GET /api/status`: `gateway_state === "startup_failed"`; `gateway_platforms[name].state in {"fatal","disconnected"}`.
- **Inputs / options:** none. **Outputs / side effects:** none. **Config / env:** n/a.
- **Edge cases / guards:** Hidden when no alerts.
- **Rebuild notes:** Derive alerts from the status payload.

### System action log panel (restart / update progress)  `id: web-a.sessions.system-action-log`
- **Surface:** Web dashboard
- **Where:** Bordered panel on `/sessions` while a system action is active (`SessionsPage.tsx:1740-1802`): spinner/check/warning icon, label "Restart Gateway" (`i18n: status.restartGateway`) or "Update Hermes" (`i18n: status.updateHermes`), Badge "Running" (`status.running`) / "Finished" (`status.actionFinished`) / "Action failed (<code>)" (`status.actionFailed`) / "Loading..." (`common.loading`), close icon button `aria-label` "Close" (`common.close`), and a `<pre>` log (auto-scrolled) showing `actionStatus.lines` or "Waiting for output…" (`status.waitingForOutput`).
- **What it does:** Shows the streaming log of the sidebar's "Restart Gateway" / "Update Hermes" actions on this page.
- **How it works:** `useSystemActions()` (`contexts/SystemActions.tsx`): `runAction` POSTs `/api/gateway/restart` or `/api/hermes/update`, then polls `GET /api/actions/<gateway-restart|hermes-update>/status?lines=200` every 1.5 s; `dismissLog` clears. Update responses with `ok:false` show a toast with `message` + `update_command` instead.
- **Inputs / options:** Close button.
- **Outputs / side effects:** none on this page (actions are triggered from the app sidebar — app-shell shard).
- **Config / env:** `can_update_hermes` in status.
- **Edge cases / guards:** Transient poll errors keep polling.
- **Rebuild notes:** Poll-based action log.

### Category filter — Chats / Automation / All  `id: web-a.sessions.category-filter`
- **Surface:** Web dashboard
- **Where:** Control bar `Segmented` (radio buttons) "Chats" (`i18n: sessions.filterChats`), "Automation" (`sessions.filterAutomation`), "All" (`sessions.filterAll`) (`SessionsPage.tsx:1807-1817`). Crawl: role=radio buttons "Chats", "Automation", "All".
- **What it does:** Splits sessions into human chats vs automated runs.
- **How it works:** `AUTOMATION_SESSION_SOURCES = ["cron","tool","api_server","acp","hermes_flow","vulcan_delegate","webhook"]` (`SessionsPage.tsx:100-108`). Query mapping (`sessionQueryOptions`, `SessionsPage.tsx:907-935`): `chats` → `exclude_sources=<automation list>`; `automation` → exclude every known non-automation source (from stats `by_source`) or `sources=<automation list>` when none are known; `all` → no filter. Changing category resets page to 0, collapses the expanded row, closes the source menu and clears selection. Default `chats`.
- **Inputs / options:** three radio options.
- **Outputs / side effects:** Refetch list, overview and search.
- **Config / env:** n/a.
- **Edge cases / guards:** Per-category source selections are remembered independently (`sourceSelectionsByCategory`).
- **Rebuild notes:** Source-class taxonomy → include/exclude params.

### Source filter dropdown  `id: web-a.sessions.source-filter-menu`
- **Surface:** Web dashboard
- **Where:** Control bar outlined button (ListFilter icon, ChevronDown rotates when open), `aria-label="Session source"` (`i18n: sessions.sourceFilter`), label text "Any chat source" / "Any automation source" / "Any source" (`i18n: sessions.anySource`) by default, "No sources" when everything is unchecked, "<Source>" for one, "<n> sources" for several (`SessionsPage.tsx:958-981, 1819-1901`). Popover: header "Chat sources" / "Automation sources" / "Session source" (`sessions.sourceFilter`) + ghost button "Clear" (`common.clear`, shown only when a custom selection exists); rows = `Checkbox` (`aria-label="Session source: <Label>"`) + button with source icon, label, and count. Crawl: "Any chat source".
- **What it does:** Multi-select which session sources to show within the current category.
- **How it works:** Options come from `stats.by_source` sorted by count desc then label, plus any pinned selections with count 0; filtered to the category (`sourceBelongsToCategory`). Labels via `sourceLabel()` (`SessionsPage.tsx:128-167`): `api_server`→"API server", `acp`→"ACP", `cli`→"CLI", `tui`→"TUI", `telegram`→"Telegram", `discord`→"Discord", `slack`→"Slack", `whatsapp`→"WhatsApp", `whatsapp_cloud`→"WhatsApp Cloud", `sms`→"SMS", `cron`→"Cron", `tool`→"Tool", `hermes_flow`→"Hermes Flow", `vulcan_delegate`→"Vulcan delegate", `webhook`→"Webhook", default = Title Case of `_`-split. Icons/colours from `SOURCE_CONFIG` (`SessionsPage.tsx:78-98`: cli/tui Terminal, telegram/signal/matrix/sms MessageCircle, discord Hash, slack/email MessageSquare, whatsapp/whatsapp_cloud/api_server/webhook Globe, cron Clock, tool/hermes_flow/vulcan_delegate Play, acp Database). Selection → query: 0 selected → `exclude_sources=<all known>` (or sentinel `source=__hermes_dashboard_no_matching_source__`), 1 → `source=<x>`, n → `exclude_sources=<rest>`. Outside `pointerdown` closes the menu.
- **Inputs / options:** Toggle button; per-source checkboxes; "Clear".
- **Outputs / side effects:** Refetch; page reset to 0.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty option list shows the menu title as placeholder text.
- **Rebuild notes:** Count-annotated multi-select. Better: type-to-filter and "only" action per row.

### View switch — Overview / History  `id: web-a.sessions.view-switch`
- **Surface:** Web dashboard
- **Where:** Control bar `Segmented` "Overview" (`i18n: sessions.overview`) / "History" (`i18n: sessions.history`) (`SessionsPage.tsx:1903-1914`); shown only when there is something to overview (connected platforms or recent sessions) and no search is active.
- **What it does:** Toggles between the dashboard-style overview (platforms + recent sessions) and the paginated history list.
- **How it works:** `view` state default `"overview"`; `showList = view==="list" || isSearching || !showOverviewTab`. Typing a search switches to `list`. Switching clears selection.
- **Inputs / options:** two radio options.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** On a fresh install (no platforms, no sessions) the toggle is hidden and the list shows directly (matches crawl).
- **Rebuild notes:** Two-view toggle.

### Full-text session search  `id: web-a.sessions.search`
- **Surface:** Web dashboard
- **Where:** Control bar input placeholder "Search message content..." (`i18n: sessions.searchPlaceholder`), Search icon (spinner while searching), clear button **X** `aria-label="Clear"` (`common.clear`) when non-empty (`SessionsPage.tsx:1916-1941`). Results render as normal session rows plus a highlighted snippet line; matching message bubbles get a warning ring and a "match" Badge (`i18n: common.match`) and the first hit is scrolled into view.
- **What it does:** Searches session ids and message contents (SQLite FTS5) with prefix matching and lineage-deduped results.
- **How it works:** 300 ms debounce → `api.searchSessions(q, sessionQueryOptions)` → `GET /api/sessions/search?q=…[&source|sources|exclude_sources][&profile]` (`web_routers/sessions.py:206-429`): id matches first (`search_sessions_by_id`, snippet = preview or "Session ID: <id>"), then FTS with auto `*` suffix on unquoted tokens, over-fetch `max(limit*5,50)`, dedupe by compression-lineage root, resolve to the lineage tip, limit clamped 1..100 (default 20). Response `{results:[SessionSearchResult]}` with `session_id`, `snippet` (matches wrapped in `>>>…<<<`), `role`, `session_started`, `lineage_root` plus the rich session row. `SnippetHighlight` (`SessionsPage.tsx:171-196`) turns `>>>x<<<` into `<mark>`; `MessageBubble` highlights any whitespace-separated term case-insensitively inside `Markdown` text nodes (`components/Markdown.tsx` `HighlightedText`); `MessageList` scrolls to the first `[data-search-hit]` after 50 ms.
- **Inputs / options:** Text; `X` clear.
- **Outputs / side effects:** Replaces the paginated list with results (pagination hidden); "Delete empty" and "Import sessions" hidden while searching.
- **Config / env:** `sessions.cjk_fts`, `sessions.search_slow_ms`, `sessions.fts_optimize_notice` (server).
- **Edge cases / guards:** Empty/whitespace query → `{results:[]}`; errors → results cleared silently.
- **Rebuild notes:** Debounced FTS with snippet markers. Better: result count, "next hit" navigation inside a transcript, filters by role.

### "Delete empty (N)" button + confirmation  `id: web-a.sessions.delete-empty`
- **Surface:** Web dashboard
- **Where:** Control bar outlined destructive button (Eraser icon) "Delete empty (<count>)" (`i18n: sessions.deleteEmpty` "Delete empty", `aria-label`/`title` same), shown only in list view, not searching, and `emptyCount>0` (`SessionsPage.tsx:1943-1958`). Dialog: title "Delete empty sessions?" (`sessions.deleteEmptyConfirmTitle`), body "This permanently removes {count} sessions that have no messages. Active and archived sessions are skipped. This cannot be undone." (`sessions.deleteEmptyConfirmMessage`), buttons "Cancel" / "Delete" (`DeleteConfirmDialog`).
- **What it does:** Bulk-removes sessions that own no message rows.
- **How it works:** Count from `GET /api/sessions/empty/count` (`web_routers/sessions.py:511-526`); confirm → `DELETE /api/sessions/empty[?profile]` (`529-562`, `db.delete_empty_sessions()` — skips active (`ended_at IS NULL`) and archived; children orphaned) → toast "{count} empty sessions deleted" (`sessions.emptySessionsDeleted`) or "Failed to delete empty sessions" (`sessions.failedToDeleteEmpty`); then reload page + count.
- **Inputs / options:** Button; dialog Confirm/Cancel/Escape.
- **Outputs / side effects:** DB rows deleted (on-disk transcripts cleaned by the next prune pass).
- **Config / env:** profile.
- **Edge cases / guards:** "Empty" = zero rows in `messages` (soft-archived rows count as content, #95868).
- **Rebuild notes:** Count endpoint gating a destructive action.

### Import sessions (JSON / JSONL)  `id: web-a.sessions.import`
- **Surface:** Web dashboard
- **Where:** Control bar outlined button (Upload icon / spinner) "Import sessions", `aria-label="Import exported sessions"`, `title="Import exported session JSON or JSONL"` (`SessionsPage.tsx:1960-1975`); hidden `<input type=file accept=".json,.jsonl,application/json,application/x-ndjson">` (`1579-1585`).
- **What it does:** Restores sessions previously exported from the dashboard/CLI into the current profile's store.
- **How it works:** `parseImportSessions(text)` (`lib/session-import.ts`): accepts a single object, an array, `{sessions:[...]}`, or JSONL (one object per line); errors "File is empty", "Expected exported session JSON or JSONL". `api.importSessions(sessions)` → `POST /api/sessions/import` body `{sessions, profile}` (`web_routers/sessions.py:485-508`; body streamed with cap `_SESSION_IMPORT_MAX_BYTES` 25 MiB → 413 "Session import payload is too large"; `db.import_sessions`). Toast "Import complete: <n> imported[; <n> skipped][; <n> detached from missing parents]" (`importSummary`) or "Import failed: <error>"; then reload list/stats/count.
- **Inputs / options:** One file (first of the FileList).
- **Outputs / side effects:** New DB rows; response `{ok, imported, skipped, detached, imported_ids, skipped_ids, errors}`.
- **Config / env:** profile.
- **Edge cases / guards:** Button disabled while importing; input value reset after each run.
- **Rebuild notes:** Client-side parse + JSON POST. Better: multipart streaming for big archives, dry-run preview.

### Pagination (compact + full)  `id: web-a.sessions.pagination`
- **Surface:** Web dashboard
- **Where:** Compact control (right of the control bar) and full control under the list (`SessionsPagination`, `SessionsPage.tsx:767-813`): icon buttons ChevronLeft `aria-label="Previous page"` (`i18n: sessions.previousPage`) and ChevronRight `aria-label="Next page"` (`sessions.nextPage`), text "Page <n> of <m>" (`common.page`, `common.of`), and in full mode a range "<from>–<to> of <total>".
- **What it does:** Pages through sessions 20 at a time.
- **How it works:** `PAGE_SIZE=20`; shown when `total > 20` and not searching; `goToPage` clears bulk selection.
- **Inputs / options:** Prev/Next (disabled at bounds).
- **Outputs / side effects:** `GET /api/sessions?offset=…`.
- **Config / env:** server caps `limit` at 100.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Offset pagination. Better: keyset pagination + page-size selector.

### Bulk select & delete  `id: web-a.sessions.bulk-select`
- **Surface:** Web dashboard
- **Where:** Per-row `Checkbox` `aria-label="Select session"` (`i18n: sessions.selectSession`); selection bar (`role="region"`, `aria-label="{count} selected"`) with text "{count} selected" (`sessions.selectedCount`), ghost buttons "Select all on this page" (`sessions.selectAllOnPage`, shown while some visible rows are unselected) and "Clear selection" (`sessions.clearSelection`), and outlined destructive "Delete {count}" (`sessions.deleteSelected`) (`SessionsPage.tsx:1990-2053`). Dialog "Delete {count} sessions?" / "This permanently removes {count} selected sessions and all their messages. This cannot be undone." (`sessions.deleteSelectedConfirmTitle/Message`).
- **What it does:** Multi-select rows (with shift-click ranges) and delete them in one request.
- **How it works:** `selectedIds: Set<string>`; `handleSelectClick(event, index, visibleList)` (`SessionsPage.tsx:1322-1359`): shift-click extends from the last non-shift anchor to the clicked index, applying the clicked row's new state to the whole range (Gmail semantics); anchor always updated. Selection is cleared on page change, search input, view switch, category/source change. Confirm → `POST /api/sessions/bulk-delete` `{ids, profile}` (`web_routers/sessions.py:432-482`; max 500 ids → 400; unknown ids skipped; active/archived rows ARE deleted) → toast "{count} sessions deleted" (`sessions.selectedSessionsDeleted`) / "Failed to delete selected sessions".
- **Inputs / options:** Checkbox click / Space; Shift+click; three bar buttons; dialog.
- **Outputs / side effects:** Rows removed optimistically then list reloaded.
- **Config / env:** profile.
- **Edge cases / guards:** Selected rows get `border-primary/40 bg-primary/[0.06]` (beats the live styling).
- **Rebuild notes:** Set-based selection with range anchor.

### Session row (list item anatomy)  `id: web-a.sessions.row`
- **Surface:** Web dashboard
- **Where:** Each list entry (`SessionRow`, `SessionsPage.tsx:465-761`): checkbox; source icon; title (bold) or `preview.slice(0,60)` (muted italic) or "Untitled session" (`i18n: sessions.untitledSession`); green Badge "Live" (`common.live`, pulsing dot) when `is_active`; meta line "<model short> · <n> msgs · <n> tools · <timeAgo>" (`common.msgs`, `common.tools`); optional search snippet; action cluster (desktop right / mobile below): outline Badge with icon + source label (or "local"), and buttons Resume in Chat, Rename, Export, Delete (entries below). Clicking the row toggles the transcript.
- **What it does:** Summarises one session and hosts per-row actions.
- **How it works:** `SessionInfo` (`lib/api.ts:587-602`): `id, source, model, title, started_at, ended_at, last_active, is_active, message_count, tool_call_count, input_tokens, output_tokens, preview, parent_session_id`. `is_active` computed server-side = `ended_at IS NULL` and `now − last_active < 300 s`. Source lookup tries the full `source` then the prefix before `:`. `timeAgo` (`lib/utils.ts:22-29`): "just now", "<m>m ago", "<h>h ago", "yesterday", "<d>d ago". Container border: selected > active (`border-success/30`) > default.
- **Inputs / options:** Row click (expand), checkbox, 4 buttons.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Title "Untitled" is treated as no title.
- **Rebuild notes:** Row = summary + actions + expandable transcript.

### Row action — Resume in Chat  `id: web-a.sessions.row.resume-in-chat`
- **Surface:** Web dashboard
- **Where:** Row ghost icon button (Play) `aria-label`/`title` "Resume in Chat" (`i18n: sessions.resumeInChat`) (`SessionsPage.tsx:531-545`).
- **What it does:** Opens the session in the embedded terminal.
- **How it works:** `navigate("/chat?resume=<id>")`; shown only when `isDashboardEmbeddedChatEnabled()`.
- **Inputs / options:** Click. **Outputs / side effects:** Route change (see `web-a.chat.resume`). **Config / env:** n/a. **Edge cases / guards:** `stopPropagation` so the row does not expand.
- **Rebuild notes:** Deep link.

### Row action — Rename (inline)  `id: web-a.sessions.row.rename`
- **Surface:** Web dashboard
- **Where:** Row ghost icon button (Pencil) `aria-label`/`title` "Rename session" → inline `Input` placeholder "Session title" with icon buttons Check `aria-label`/`title` "Save title" and X "Cancel rename" (`SessionsPage.tsx:547-564, 640-683`).
- **What it does:** Edits the session title in place.
- **How it works:** `Enter` submits, `Escape` cancels; unchanged/empty value just closes. `api.renameSession(id, title)` → `PATCH /api/sessions/<id>` `{title, profile}` (`web_routers/sessions.py:792-845`, `db.set_session_title`; 400 on invalid/too long/duplicate title, 404 unknown). Toast "Session renamed" / "Failed to rename session"; list and overview updated optimistically; stats reloaded.
- **Inputs / options:** Text input; Save; Cancel; Enter; Escape.
- **Outputs / side effects:** DB title.
- **Config / env:** profile.
- **Edge cases / guards:** Same PATCH also accepts `archived`, `hidden`, `pinned`, `unread` (not exposed on this page).
- **Rebuild notes:** Inline editable title.

### Row action — Export session JSON  `id: web-a.sessions.row.export`
- **Surface:** Web dashboard
- **Where:** Row ghost icon button (Download) `aria-label="Export session"`, `title="Export session JSON"` (`SessionsPage.tsx:566-578`).
- **What it does:** Downloads the session (metadata + all messages) as `session-<id>.json`.
- **How it works:** `fetch(api.exportSessionUrl(id))` with `X-Hermes-Session-Token` header + `credentials:"include"` (`SessionsPage.tsx:1468-1493`) → `GET /api/sessions/<id>/export[?profile]` (`web_routers/sessions.py:848-907`): `StreamingResponse` of `{...session, "messages":[...]}` using keyset pagination in 500-row pages; blob → object URL → anchor click. Error toast "Failed to export session".
- **Inputs / options:** Click.
- **Outputs / side effects:** Browser download.
- **Config / env:** `sessions.max_export_messages` (server).
- **Edge cases / guards:** 404 when the id is unknown.
- **Rebuild notes:** Streamed JSON export.

### Row action — Delete session  `id: web-a.sessions.row.delete`
- **Surface:** Web dashboard
- **Where:** Row ghost destructive icon button (Trash2) `aria-label="Delete session"` (`i18n: sessions.deleteSession`) (`SessionsPage.tsx:580-591`); dialog title "Delete session?" (`sessions.confirmDeleteTitle`), body `"<title>" — This permanently removes the conversation and all of its messages. This cannot be undone.` (`sessions.confirmDeleteMessage`, title prefix only when titled), buttons "Cancel"/"Delete".
- **What it does:** Deletes one session.
- **How it works:** `useConfirmDelete` hook (`@nous-research/ui`) → `api.deleteSession(id)` → `DELETE /api/sessions/<id>[?profile]` (`web_routers/sessions.py:719-744`; already-absent id → `{ok:true, already_absent:true}`); toast "Session deleted" (`sessions.sessionDeleted`) / "Failed to delete session" (`sessions.failedToDelete`); row removed, total decremented, empty count and stats refreshed.
- **Inputs / options:** Button; dialog.
- **Outputs / side effects:** DB row + messages deleted; children orphaned.
- **Config / env:** profile.
- **Edge cases / guards:** Corrupt store → 503 "Session store is corrupt (database disk image is malformed)…" (`_resolve_session_id`).
- **Rebuild notes:** Confirmed single delete.

### Expandable transcript (message bubbles)  `id: web-a.sessions.row.expand-transcript`
- **Surface:** Web dashboard
- **Where:** Click a row → panel below it (`SessionsPage.tsx:739-758`): spinner while loading, error text, "No messages" (`i18n: sessions.noMessages`), or `MessageList` (max-height 600px, scrollable). Each `MessageBubble` (`294-429`): role label "User" / "Assistant" / "System" / "Tool" (`i18n: sessions.roles.*`; tool messages show "Tool: <tool_name>"), optional "match" Badge, `timeAgo(timestamp)`, body (system → plain pre-wrap text; others → `Markdown`), and `ToolCallBlock`s.
- **What it does:** Shows the last 500 messages of a session with markdown rendering, collapsible tool calls and clearly-labelled context-compaction handoffs.
- **How it works:** `api.getSessionMessages(id)` → `GET /api/sessions/<id>/messages?limit=500&order=latest` (`web_routers/sessions.py:643-716`: resolves id/prefix, follows `resolve_resume_session_id`, pages max 500, projects compaction summaries via `project_compaction_message_for_display` adding `display_content`/`display_kind:"hidden"`). Response `{session_id, messages:[{role, content, tool_calls?, tool_name?, tool_call_id?, timestamp?}], pagination:{limit, offset, order, returned}}`. `ToolCallBlock` (`198-238`): ListItem with Chevron, tool name (mono), call id, `aria-label="Expand|Collapse tool call <name>"`, expands to pretty-printed JSON args. Compaction: messages starting with "[CONTEXT COMPACTION — REFERENCE ONLY]", "[CONTEXT COMPACTION - REFERENCE ONLY]" or "[CONTEXT SUMMARY]:" render as muted italic "Context handoff"; if the end marker "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---" is present the remainder is split into its own normally-styled bubble (`253-291, 344-370`).
- **Inputs / options:** Row click; tool-call toggles.
- **Outputs / side effects:** Messages cached per row until collapse/unmount.
- **Config / env:** n/a.
- **Edge cases / guards:** `include_compacted=false` by default; only the latest page is shown (no "load more").
- **Rebuild notes:** Lazy transcript with role styling. Better: virtualised full history with "load older", copy per message, render `display_content`.

### Markdown renderer (session transcripts)  `id: web-a.sessions.markdown-renderer`
- **Surface:** Web dashboard
- **Where:** `components/Markdown.tsx` used by `MessageBubble`.
- **What it does:** Lightweight, dependency-free markdown → React for assistant/user text with search-term highlighting and an optional streaming caret.
- **How it works:** `parseBlocks` (`Markdown.tsx:57-141`): fenced code (```` ```lang ````), headings `#`–`####`, horizontal rules (`---`/`***`/`___`), unordered lists (`-`,`*`,`+`), ordered lists (`1.`/`1)`), paragraphs. `parseInline` (`210-256`) priority: `` `code` `` > `[text](url)` > `**bold**` > `*italic*` > bare `http(s)://` URL > newline (`<br>`). Links render only for `http:`, `https:`, `mailto:` (others degrade to text — XSS guard), `target=_blank rel=noreferrer`. `HighlightedText` wraps case-insensitive matches of `highlightTerms` in `<mark>`. `streaming` prop appends a pulsing caret to the last block.
- **Inputs / options:** props `content`, `highlightTerms`, `streaming`.
- **Outputs / side effects:** n/a. **Config / env:** n/a.
- **Edge cases / guards:** Not CommonMark (no nested lists, tables, blockquotes, images).
- **Rebuild notes:** Regex block/inline parser. Better: a real CommonMark+GFM renderer with sanitisation.

### "Prune old sessions" dialog  `id: web-a.sessions.prune-dialog`
- **Surface:** Web dashboard
- **Where:** Header end-slot outlined button (Archive icon) "Prune old sessions" (`SessionsPage.tsx:1010-1024`); `Dialog` (`1627-1679`): title "Prune old sessions", description "Permanently remove archived sessions whose last activity is older than the given number of days. Active sessions are never pruned.", label "Older than (days)" with number `Input` id `prune-days` (min 0, default "90", Enter submits), footer buttons "Cancel" (`common.cancel`) and destructive "Prune" (spinner while running).
- **What it does:** Deletes ended sessions older than N days.
- **How it works:** `handlePrune` (`SessionsPage.tsx:1494-1513`): validates integer ≥0 else toast "Enter a valid number of days"; `api.pruneSessions(days)` → `POST /api/sessions/prune` `{older_than_days, source?, profile}` (`web_routers/sessions.py:910-913` → `_prune_sessions` `web_server.py:12606-12700`: `older_than_days<1` without a window → 400; all `SessionPrune` filters ANDed; `archived=False` unless `include_archived`; open sessions counted as `skipped_open`; `dry_run` returns candidates). Toast via `formatSessionPruneResult`: "Pruned <n> session(s)" [+ ". Skipped <n> open session(s); prune only removes ended sessions."] or "Failed to prune sessions"; list reset to page 0, stats reloaded.
- **Inputs / options:** Number input; Prune; Cancel; Enter.
- **Outputs / side effects:** DB deletes.
- **Config / env:** `sessions.retention_days` (CLI auto-prune default 90), `sessions.vacuum_after_prune`.
- **Edge cases / guards:** The API supports many more filters (`source, started_before/after, title_like, end_reason, cwd_prefix, min/max_messages, model_like, provider, user_id, chat_id, chat_type, branch_like, min/max_tokens, min/max_cost, min/max_tool_calls, include_archived, dry_run`) than the UI exposes.
- **Rebuild notes:** Days-based prune with open-session protection. Better: dry-run preview listing candidates.

### Overview view — Recent Sessions card  `id: web-a.sessions.overview`
- **Surface:** Web dashboard
- **Where:** Overview mode (`SessionsPage.tsx:2105-2170`): `PlatformsCard` (when platforms exist) then a Card titled "Recent Sessions" (`i18n: status.recentSessions`, Clock icon) listing up to 5 non-active sessions: title / `preview.slice(0,60)` / "Untitled" (`common.untitled`), meta "<model> · <n> msgs · <timeAgo>", preview paragraph when titled, and an outline Badge (Database icon) with the source label or "local".
- **What it does:** At-a-glance status of channels and latest conversations.
- **How it works:** From the 5 s overview poll (`GET /api/sessions?limit=50…` filtered `!is_active`).
- **Inputs / options:** none (rows are not clickable).
- **Outputs / side effects:** none. **Config / env:** n/a.
- **Edge cases / guards:** Hidden entirely when there is nothing to show.
- **Rebuild notes:** Static summary. Better: clickable rows.

### Connected Platforms card  `id: web-a.sessions.platforms-card`
- **Surface:** Web dashboard
- **Where:** `components/PlatformsCard.tsx`: Card title "Connected Platforms" (`i18n: status.connectedPlatforms`, Radio icon); per platform row: state icon (Wifi connected / AlertTriangle fatal / PowerOff disabled / WifiOff otherwise), capitalised name, optional `error_message`, "Last update: <isoTimeAgo>" (`status.lastUpdate`), and a Badge "Connected" (`status.connected`, success + pulse) / "Disconnected" (`status.disconnected`, warning) / "Disabled" (`status.disabled`, outline) / "Error" (`status.error`, destructive) / raw state.
- **What it does:** Shows gateway messaging platform health.
- **How it works:** `status.gateway_platforms: Record<name, {state, updated_at, error_code?, error_message?}>` from `GET /api/status`; `isoTimeAgo` (`lib/utils.ts:32-39`).
- **Inputs / options:** none. **Outputs / side effects:** none. **Config / env:** n/a.
- **Edge cases / guards:** Unknown states render the raw string with outline tone.
- **Rebuild notes:** Status list.

### Empty states  `id: web-a.sessions.empty-states`
- **Surface:** Web dashboard
- **Where:** List area (`SessionsPage.tsx:2055-2071`): Clock icon + "No sessions match your search" (`i18n: sessions.noMatch`) when searching; "No sessions in this filter" (`sessions.noSessionsInFilter`) when a source selection or non-chat category is active; otherwise "No sessions yet" (`sessions.noSessions`) with sub-text "Start a conversation to see it here" (`sessions.startConversation`). Crawl confirms the last pair.
- **What it does:** Explains why the list is empty.
- **How it works:** Conditional on `search`, `selectedSources`, `sessionCategory`.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** n/a.
- **Rebuild notes:** Context-aware empty copy.

### Overview poll & cross-process refresh  `id: web-a.sessions.auto-refresh-poll`
- **Surface:** Web dashboard
- **Where:** Invisible (`SessionsPage.tsx:1130-1167`).
- **What it does:** Keeps status, platform cards and the list fresh while a CLI/gateway in another process creates sessions.
- **How it works:** `setInterval(loadOverview, 5000)`; `loadOverview` fetches `/api/status` and `/api/sessions?limit=50` with the same filters; when the head session id changes vs the last seen id (`shouldRefreshSessions`), `loadSessions(currentPage, silent=true)` refreshes without the spinner. First poll only sets the baseline.
- **Inputs / options:** none. **Outputs / side effects:** 2 requests / 5 s. **Config / env:** n/a.
- **Edge cases / guards:** Null ids (empty DB) never trigger a refresh.
- **Rebuild notes:** Head-id change detection. Better: SSE/WS push.

### `GET /api/sessions` (list)  `id: web-a.sessions.api.list`
- **Surface:** API
- **Where:** `web_routers/sessions.py:90-203` (`list_router`); client `api.getSessions(limit, offset, profile|options, order)` (`lib/api.ts:376-389`).
- **What it does:** Paginated, filterable session listing with computed `is_active`, ownership stamp and archived/pinned booleans.
- **How it works:** Query params: `limit` (0..100, default 20), `offset` (≥0), `min_messages` (default 0), `archived` (`exclude`|`only`|`include`, default exclude; else 400), `order` (`created`|`recent`; else 400), `source`, `sources` (comma list), `exclude_sources` (comma list), `cwd_prefix`, `full` (bool; include `system_prompt`/`model_config`), `profile`. Calls `db.list_sessions_rich(... include_pinned=True, compact_rows=!full)` and `db.session_count(... exclude_children=True)`. Each row gets `is_active`, `profile` (serving profile), `is_default_profile`, `archived`, `pinned`.
- **Inputs / options:** as above.
- **Outputs / side effects:** `{sessions:[...], total, limit, offset}` (live: `{"sessions":[],"total":0,"limit":20,"offset":0}`).
- **Config / env:** `sessions.auto_archive*` (runs the auto-archive sweep first).
- **Edge cases / guards:** 500 "Internal server error" on unexpected failures.
- **Rebuild notes:** Standard list endpoint with include/exclude source sets.

### `GET /api/sessions/{id}` and `/latest-descendant`  `id: web-a.sessions.api.detail-latest-descendant`
- **Surface:** API
- **Where:** `web_routers/sessions.py:597-640`; clients `api.getSessionDetail`, `api.getSessionLatestDescendant` (`lib/api.ts:397-407`).
- **What it does:** Detail row for one session (used for the chat header title) and resolution of a session to its newest child (used by chat resume).
- **How it works:** Detail resolves exact id or unique prefix (`_resolve_session_id`), 404 "Session not found", stamps `profile`/`is_default_profile`. Latest-descendant returns `{requested_session_id, session_id, path:[...], changed}` following child sessions created by `/model` (`_session_latest_descendant`).
- **Inputs / options:** path `session_id`, query `profile`.
- **Outputs / side effects:** none.
- **Config / env:** profile.
- **Edge cases / guards:** 503 on corrupt store.
- **Rebuild notes:** Prefix-resolving detail + lineage tip.

### Session mutation & maintenance endpoints  `id: web-a.sessions.api.mutations`
- **Surface:** API
- **Where:** `web_routers/sessions.py` (`manage_router`): `DELETE /api/sessions/{id}` (719), `PATCH /api/sessions/{id}` (792), `POST /api/sessions/bulk-delete` (432), `GET /api/sessions/empty/count` (511), `DELETE /api/sessions/empty` (529), `GET /api/sessions/stats` (565), `GET /api/sessions/{id}/export` (848), `POST /api/sessions/import` (485), `POST /api/sessions/prune` (910), `POST /api/sessions/owner-backfill` (747).
- **What it does:** Backs every destructive/maintenance action on the page (documented per feature above); `owner-backfill` is a migration endpoint not called by this page.
- **How it works:** Request bodies (`hermes_cli/web_models.py`): `BulkDeleteSessions{ids:[str], profile?}`, `SessionRename{title?, archived?, hidden?, pinned?, unread?, profile?}` (400 "Nothing to update…" when all absent), `SessionImport{sessions:[obj], profile?}`, `SessionPrune{older_than_days=90, source?, profile?, started_before?, started_after?, title_like?, end_reason?, cwd_prefix?, min_messages?, max_messages?, model_like?, provider?, user_id?, chat_id?, chat_type?, branch_like?, min_tokens?, max_tokens?, min_cost?, max_cost?, min_tool_calls?, max_tool_calls?, include_archived=false, dry_run=false}`, `SessionOwnerBackfill{profile?}` → `{ok, stamped, profile}`. All DB work runs in threads (`asyncio.to_thread`).
- **Inputs / options:** as above.
- **Outputs / side effects:** `{ok:true}` / `{ok:true, deleted:n}` / `{ok:true, title:"…"[, archived, hidden, pinned, unread]}` / `{ok, removed, skipped_open[, matched, sessions…]}`.
- **Config / env:** profile.
- **Edge cases / guards:** bulk-delete cap 500; import cap 25 MiB; prune `older_than_days<1` → 400 unless a date window is given; DELETE is idempotent.
- **Rebuild notes:** Thread-offloaded SQLite mutations with explicit safety contracts.

### Plugin slots on the Sessions page  `id: web-a.sessions.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `<PluginSlot name="sessions:top"/>` (`SessionsPage.tsx:1577`) and `<PluginSlot name="sessions:bottom"/>` (`2174`).
- **What it does:** Plugin injection points above and below the page content.
- **How it works:** Plugin slot registry (plugins shard).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** n/a.
- **Rebuild notes:** Named slots.


---

## C. Files page (`/files`)

### Files page (managed-file browser)  `id: web-a.files.page`
- **Surface:** Web dashboard
- **Where:** Sidebar nav link `FILES` (`App.tsx:193` `{ path: "/files", label: "Files", icon: FolderOpen }` — label is a hard-coded literal, **no i18n key**; the sidebar CSS uppercases it, so the crawl reads `"FILES"`), URL `/files`; page `<h1>` "Files" (`lib/resolve-page-title.ts:22` `BUILTIN_LITERAL["/files"] = "Files"`). Crawl `_files.json` state `initial` confirms `{"tag":"H1","text":"Files"}`.
- **What it does:** A two-pane-less, single-column file manager for the machine the gateway runs on: browse a directory, upload files (button / drag-drop), create folders, download files, delete files and folders.
- **How it works:** `pages/FilesPage.tsx:78-525`, lazily imported (`App.tsx:83`, route table `App.tsx:159`). One React state object per concern: `currentPath` (requested dir, `undefined` = server default), `pathInput` (text of the path bar), `listing: ManagedFilesResponse | null`, `loading`, `uploading`, `draggingFiles`, `creating`, `createDialogOpen`, `deleting`, `folderName`, `pendingDelete: ManagedFileEntry | null`, `error: string | null`. Load: `load(path=currentPath)` (`:101-117`) → `api.listFiles(path)` → `GET /api/files[?path=…]`; on success it stores the *server-canonicalised* path back into both `currentPath` and `pathInput`, on failure it sets `error = String(e)`. An effect re-runs `load` on every `currentPath` change (`:119-124`). Derived values (`:96-99`): `activePath = listing?.path ?? currentPath ?? ""`, `canChangePath = listing?.can_change_path ?? false`, `canUpload = Boolean(activePath) && !uploading`, `headerPath = displayPath(listing?.locked_root ?? listing?.path ?? currentPath)` where `displayPath` (`:70-72`) falls back to the literal `"Files"` when the path is blank. There is **no** localStorage, no polling, no WebSocket — the page is entirely request/response and only refetches when the user acts.
- **Inputs / options:** Path bar `<Input aria-label="Path" placeholder="Path">` + `GO` submit (only when `can_change_path`), header `Refresh files` icon button, `UPLOAD`, `CREATE`, the drop-zone button `Upload files`, the `..` parent row, per-row name button, per-row `Open <name>` / `Download <name>` and `Delete <name>` icon buttons, the "Create folder" dialog (`Folder name` input, `Cancel`, `Create`), the delete confirmation (`Delete`, `Cancel`). No keyboard shortcuts beyond `Enter` in the two text inputs.
- **Outputs / side effects:** Reads and writes real files on the server host inside the managed root; browser downloads via a synthetic `<a download>` click; toasts.
- **Config / env:** `HERMES_DASHBOARD_FILES_ROOT` (env, locks + defaults the browsable root, `web_server.py:2191`); `HERMES_HOME` = `/opt/data` forces the hosted lock (`web_server.py:2578-2589`, `_HOSTED_MANAGED_FILES_ROOT = Path("/opt/data")`, `:2208`). No dotted config key gates the page and the nav item is always shown.
- **Edge cases / guards:** Every string on the page is hard-coded English — the Files page is **not** internationalised (the only translated strings it renders are `Delete` / `Cancel` inside `DeleteConfirmDialog`, `i18n: common.delete` / `common.cancel`). All server errors surface either as the red banner (list failures) or as a toast (`Create failed: …`, `Upload failed: …`, `Download failed: …`, `Delete failed: …`). No profile scoping: `/api/files` is **not** in `PROFILE_SCOPED_PREFIXES` (`lib/api.ts:70-93`), so the header profile switcher does not change what you browse.
- **Rebuild notes:** Minimal spec: `GET /api/files?path=` returning `{path,parent,entries[],root,locked_root,can_change_path}` plus mkdir/upload/read/delete; a flat grid with four columns and per-row actions. A better version would add rename/move, multi-select with bulk delete, an in-browser text/image/PDF preview (the backend already has `/api/fs/preview`), a breadcrumb instead of a raw path box, sortable columns, and progress bars for large uploads.

### Header path badge  `id: web-a.files.header-badge`
- **Surface:** Web dashboard
- **Where:** Page header, immediately after the `Files` title — an outline `Badge` whose text and `title=` tooltip are the current path (crawl tooltip: `{"title":"/root","text":"/root"}`).
- **What it does:** Shows which directory the listing is for (or the locked root when the deployment pins one), truncated to `max-w-[22rem]`.
- **How it works:** `FilesPage.tsx:126-131` pushes the badge into the shared page header through `usePageHeader().setAfterTitle(...)`; content = `headerPath` = `listing.locked_root ?? listing.path ?? currentPath`, falling back to the literal `"Files"` when empty (`:70-72,99`). Cleared on unmount (`:146-149`).
- **Inputs / options:** none (display only; hover shows the untruncated path).
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** In hosted/locked mode it deliberately shows the *root*, not the directory you are inside.
- **Rebuild notes:** Title-adjacent chip bound to the response's canonical path.

### "Refresh files" button  `id: web-a.files.refresh`
- **Surface:** Web dashboard
- **Where:** Page header, right-hand end — ghost icon button, `aria-label="Refresh files"`, icon `RefreshCw` (swapped for a `Spinner` while loading).
- **What it does:** Re-fetches the current directory listing.
- **How it works:** `FilesPage.tsx:132-145` → `setEnd(<Button … onClick={() => void load()} disabled={loading} aria-label="Refresh files">)`; `load()` with no argument reuses `currentPath`.
- **Inputs / options:** click only.
- **Outputs / side effects:** one `GET /api/files?path=<current>`; clears `error` at the start of the request.
- **Config / env:** n/a.
- **Edge cases / guards:** disabled while `loading`; nothing auto-refreshes, so this is the only way to see files another process created.
- **Rebuild notes:** Idempotent re-GET. Better: a filesystem watcher pushing changes over the events channel.

### Path bar (`Path` input + `GO`)  `id: web-a.files.path-bar`
- **Surface:** Web dashboard
- **Where:** Top-left of the page body, a `<form>` containing `<Input aria-label="Path" placeholder="Path" class="h-9 min-w-0 flex-1 font-mono">` and a submit button labelled `Go` (rendered uppercase → crawl text `"GO"`).
- **What it does:** Jump directly to any absolute directory on the host.
- **How it works:** `FilesPage.tsx:276-294`. Rendered **only** when `listing.can_change_path === true` (unlocked/local policy). Submit → `goToPath()` (`:158-165`): trims the value; empty → toast `Path required` (type `error`) and abort; otherwise `await load(nextPath)`. The value is re-synced to the server's canonical path after every successful load (`:109`).
- **Inputs / options:** free text; `Enter` submits (native form submit); the `GO` button submits.
- **Outputs / side effects:** `GET /api/files?path=<typed>`; on failure the red error banner shows e.g. `403: Path outside managed files root`, `404: Path not found`, `400: Path is not a directory`, `400: Path must be absolute`, `400: Path cannot contain '..'`.
- **Config / env:** hidden when `HERMES_DASHBOARD_FILES_ROOT` is set or `HERMES_HOME` resolves to `/opt/data`.
- **Edge cases / guards:** `~` is expanded server-side (`Path(text).expanduser()`, `web_server.py:2666`); relative paths are rejected with 400 in unlocked mode but resolved against the root in locked mode; NUL bytes → `400 Invalid path` (`_path_text`, `web_server.py:2563-2567`).
- **Rebuild notes:** Text box → canonicalising GET. Better: path autocompletion and a clickable breadcrumb.

### Read-only path line (locked deployments)  `id: web-a.files.path-readonly`
- **Surface:** Web dashboard
- **Where:** Same slot as the path bar, when `can_change_path === false` — a truncating mono line showing `activePath` with a `title=` tooltip.
- **What it does:** Tells the user where they are when the deployment forbids arbitrary navigation.
- **How it works:** `FilesPage.tsx:295-299`.
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** appears when `HERMES_DASHBOARD_FILES_ROOT` is set, or `HERMES_HOME` == the container default `/opt/data`.
- **Edge cases / guards:** navigation is still possible by clicking directory rows and the `..` row (bounded by `locked_root`).
- **Rebuild notes:** Conditional swap of the editable control for static text.

### `UPLOAD` button  `id: web-a.files.upload-button`
- **Surface:** Web dashboard
- **Where:** Top-right button group, small outlined button, prefix icon `Upload` (a `Spinner` while uploading), label `Upload` (CSS-uppercased → `"UPLOAD"`).
- **What it does:** Opens the OS file picker and uploads the chosen files into the current directory.
- **How it works:** `FilesPage.tsx:301-311` → `fileInputRef.current?.click()` on the hidden `<input type="file" multiple class="hidden">` (`:267-273`), whose `onChange` calls `uploadFiles(files)` (`:191-206`). `uploadFiles` loops **sequentially** over `Array.from(files)` calling `api.uploadFile(joinPath(activePath, file.name), file, true)` → `POST /api/files/upload-stream` as `multipart/form-data` with fields `path`, `overwrite="true"`, `file`. After the loop: toast `` `${files.length} file${files.length === 1 ? "" : "s"} uploaded` `` (e.g. `1 file uploaded`, `3 files uploaded`), then `load()`; the hidden input's `value` is reset so re-picking the same file fires `change` again.
- **Inputs / options:** multi-file selection; `overwrite` is hard-wired to `true` (existing files are replaced without asking).
- **Outputs / side effects:** files written under the current directory; success/error toast; listing refresh.
- **Config / env:** n/a.
- **Edge cases / guards:** disabled when `!canUpload` (no `activePath`, or an upload already in flight). A failure aborts the remaining files in the batch and toasts `` `Upload failed: ${e}` `` (e.g. `Upload failed: Error: 413: File is too large`). Server cap 100 MiB (`_MANAGED_FILE_MAX_BYTES`, `web_server.py:2192`); 409 `A directory already exists at that path`.
- **Rebuild notes:** Hidden input + streamed multipart POST. Better: parallel/queued uploads with per-file progress, resumable chunking, and an overwrite prompt.

### `CREATE` button (new folder)  `id: web-a.files.create-button`
- **Surface:** Web dashboard
- **Where:** Top-right button group, next to `UPLOAD` — small outlined button, prefix icon `FolderPlus`, label `Create` (→ `"CREATE"`).
- **What it does:** Opens the "Create folder" dialog.
- **How it works:** `FilesPage.tsx:312-322` → `setCreateDialogOpen(true)`.
- **Inputs / options:** click.
- **Outputs / side effects:** opens the modal described in `web-a.files.create-dialog`.
- **Config / env:** n/a.
- **Edge cases / guards:** `disabled={!activePath}` — greyed out until the first listing resolves.
- **Rebuild notes:** Modal trigger.

### Drop zone ("DROP FILES HERE")  `id: web-a.files.dropzone`
- **Surface:** Web dashboard
- **Where:** Full-width dashed box under the toolbar; `aria-label="Upload files"`; three text spans: the state title, the current path in mono, and (≥`sm` breakpoint) the right-hand hint `Choose files`. Crawl accessible name: `"DROP FILES HERE /root CHOOSE FILES"`.
- **What it does:** Drag files onto it (or click it) to upload them into the current directory.
- **How it works:** `FilesPage.tsx:326-357`. The title span renders exactly one of three literals (`:347`): `Uploading` while `uploading`, `Release to upload` while `draggingFiles`, otherwise `Drop files here` (CSS `uppercase`). The sub-line is `activePath || "Loading"`. Drag tracking uses a depth counter so nested children don't flicker the highlight: `handleDragEnter` (`:208-213`) increments `dragDepthRef` and sets `draggingFiles`, `handleDragLeave` (`:221-228`) decrements and clears at 0, `handleDragOver` (`:215-219`) sets `dataTransfer.dropEffect = "copy"`, `handleDrop` (`:230-236`) resets the counter and calls `uploadFiles(event.dataTransfer.files)`. `transferHasFiles` (`:74-76`) requires `"Files"` in `dataTransfer.types`, so dragged text/links are ignored. Clicking the box opens the same hidden file input as `UPLOAD`.
- **Inputs / options:** dragenter / dragover / dragleave / drop / click.
- **Outputs / side effects:** same as `UPLOAD` (sequential `POST /api/files/upload-stream`, toast, refresh).
- **Config / env:** n/a.
- **Edge cases / guards:** `disabled={!canUpload}` with `disabled:cursor-not-allowed disabled:opacity-60`; all drag handlers early-return when `!canUpload` or the transfer has no files; while dragging the box turns `border-primary bg-primary/10`. Directory drops are not supported (only `dataTransfer.files`).
- **Rebuild notes:** Depth-counted drag state + shared upload path. Better: accept dropped folders via `webkitGetAsEntry`, show per-file rows with progress and cancel.

### Hidden multi-file input  `id: web-a.files.hidden-file-input`
- **Surface:** Web dashboard
- **Where:** Invisible `<input type="file" multiple class="hidden">` at the top of the page (crawl: `{"kind":"input","visible":false,"type":"file"}`).
- **What it does:** The actual OS file picker behind both `UPLOAD` and the drop zone's click.
- **How it works:** `FilesPage.tsx:267-273`; `onChange` → `uploadFiles(event.currentTarget.files)`; `fileInputRef.current.value = ""` in the upload `finally` block (`:204`) so selecting the same file twice still fires.
- **Inputs / options:** `multiple`; no `accept` filter — any file type.
- **Outputs / side effects:** as `UPLOAD`.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Standard hidden-input pattern.

### File table header row  `id: web-a.files.table-header`
- **Surface:** Web dashboard
- **Where:** First row of the listing card: four columns `Name`, `Size`, `Modified`, `Actions` (right-aligned), rendered uppercase with `tracking-[0.08em]` → crawl body text `NAME / SIZE / MODIFIED / ACTIONS`.
- **What it does:** Labels the grid columns.
- **How it works:** `FilesPage.tsx:367-372`; grid template `minmax(12rem,1fr) 7rem 10rem 5.5rem`, `min-w-[42rem]` inside a horizontally scrollable `CardContent` (`overflow-x-auto p-0`, `:360`).
- **Inputs / options:** none — headers are **not** clickable, there is no sorting UI.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** ordering is fixed by the server: directories first, then case-insensitive name (`web_server.py:2851`).
- **Rebuild notes:** Static grid header. Better: click-to-sort with a persisted preference.

### `..` parent-directory row  `id: web-a.files.parent-row`
- **Surface:** Web dashboard
- **Where:** First data row when the server returns a non-null `parent`; a full-width button showing an `ArrowUp` icon and the literal text `..`.
- **What it does:** Navigates one directory up.
- **How it works:** `FilesPage.tsx:374-388` → `setCurrentPath(listing.parent ?? undefined)`, which re-triggers the load effect. The server omits `parent` at the filesystem root and at `locked_root` (`web_server.py:2853-2855`), so the row disappears exactly where going up is not allowed.
- **Inputs / options:** click.
- **Outputs / side effects:** `GET /api/files?path=<parent>`.
- **Config / env:** n/a.
- **Edge cases / guards:** hidden when `parent` is null.
- **Rebuild notes:** Server-computed parent instead of client-side string surgery — this is what makes the locked-root boundary safe.

### File / directory row  `id: web-a.files.row`
- **Surface:** Web dashboard
- **Where:** One grid row per `entries[]` item: name button (folder icon in `text-warning` for directories, file icon in `text-text-tertiary` otherwise) → size → modified → action buttons.
- **What it does:** Shows a single entry and is the primary click target: clicking a directory name opens it, clicking a file name downloads it.
- **How it works:** `FilesPage.tsx:398-453`, `key={entry.path}`. Name button `onClick={() => (entry.is_directory ? openDirectory(entry) : void downloadFile(entry))}` (`:405`). Size cell = `formatBytes(entry.size)` (`:53-59`): `null` → `"-"`, `<1024` → `"<n> B"`, `<1 MiB` → `"<n.n> KB"`, `<1 GiB` → `"<n.n> MB"`, else `"<n.n> GB"` (one decimal, binary units). Modified cell = `Intl.DateTimeFormat(undefined, {dateStyle:"medium", timeStyle:"short"})` over `entry.mtime * 1000` (`:40-43,417`), or `"-"` when `mtime` is not finite — browser locale + timezone, e.g. `Aug 28, 2026, 6:38 PM`.
- **Inputs / options:** name button (the whole `<button type="button">` at `FilesPage.tsx:402-414` = icon + `<span className="truncate">{entry.name}</span>` at `:413`; **no i18n key** — the accessible name is the raw filesystem entry name); the two action buttons documented below. Live crawl of the default root `/root` (`hermes_inv/web_crawl/_files.json`, state `initial`) shows one name button per entry, verbatim, in the server's sort order (directories first, then files, each case-insensitively by name): `.aws`, `.bun`, `.cache`, `.cargo`, `.ccr`, `.claude`, `.config`, `.gradle`, `.hermes`, `.launchpadlib`, `.local`, `.npm`, `.pki`, `.rustup`, `.ssh` (directories → `openDirectory`), then `.bashrc`, `.boto`, `.claude.json`, `.gitconfig`, `.profile`, `.wget-hsts`, `.zshrc` (files → `downloadFile`).
- **Outputs / side effects:** navigation or download.
- **Config / env:** n/a.
- **Edge cases / guards:** hovering tints the row (`hover:bg-background/35`); long names truncate; there is no context menu, no drag-to-move, no rename.
- **Rebuild notes:** Server sends `{name, path, is_directory, size, mtime, mime_type}`; the client formats only. Better: type-aware icons from `mime_type`, inline preview on hover, and a right-click menu.

### Row action — Open directory  `id: web-a.files.row.open`
- **Surface:** Web dashboard
- **Where:** Right-hand action cell of a directory row — ghost icon button with `FolderOpen`, `aria-label="Open <name>"` (crawl: `Open .aws`, `Open .cache`, …).
- **What it does:** Descends into that folder.
- **How it works:** `FilesPage.tsx:420-429` → `openDirectory(entry)` (`:152-156`) → `setCurrentPath(entry.path)` (guarded by `entry.is_directory`).
- **Inputs / options:** click. The label is the hard-coded English template `` aria-label={`Open ${entry.name}`} `` (`FilesPage.tsx:426`) — **not** internationalised, so it stays English in every locale. Complete list of the instances rendered by the live install at the default root `/root` (`hermes_inv/web_crawl/_files.json`, state `initial`, 15 directory rows): `Open .aws`, `Open .bun`, `Open .cache`, `Open .cargo`, `Open .ccr`, `Open .claude`, `Open .config`, `Open .gradle`, `Open .hermes`, `Open .launchpadlib`, `Open .local`, `Open .npm`, `Open .pki`, `Open .rustup`, `Open .ssh`.
- **Outputs / side effects:** `GET /api/files?path=<dir>`.
- **Config / env:** n/a.
- **Edge cases / guards:** only rendered for directories; a 403 from an unreadable directory shows in the error banner as `403: Directory is not readable`.
- **Rebuild notes:** Duplicate of the name click, kept for discoverability.

### Row action — Download file  `id: web-a.files.row.download`
- **Surface:** Web dashboard
- **Where:** Right-hand action cell of a file row — ghost icon button with `Download`, `aria-label="Download <name>"` (crawl: `Download .bashrc`, `Download .zshrc`, …).
- **What it does:** Downloads the file to the browser.
- **How it works:** `FilesPage.tsx:430-440` → `downloadFile(entry)` (`:238-246`): `api.readFile(entry.path)` → `GET /api/files/read?path=…` returns `{name, path, size, mime_type, data_url, root, locked_root, can_change_path}` where `data_url` is `data:<mime>;base64,<…>` of the **whole file**; then `downloadDataUrl(file.data_url, file.name)` (`:61-68`) creates a temporary `<a href=dataUrl download=name>`, appends it to `document.body`, clicks it and removes it.
- **Inputs / options:** click (the name button does the same). The label is the hard-coded English template `` aria-label={`Download ${entry.name}`} `` (`FilesPage.tsx:436`) — **not** internationalised. Complete list of the instances rendered by the live install at the default root `/root` (`hermes_inv/web_crawl/_files.json`, state `initial`, 7 file rows): `Download .bashrc`, `Download .boto`, `Download .claude.json`, `Download .gitconfig`, `Download .profile`, `Download .wget-hsts`, `Download .zshrc`.
- **Outputs / side effects:** a browser download; on failure a toast `` `Download failed: ${e}` ``.
- **Config / env:** n/a.
- **Edge cases / guards:** the whole file is base64-buffered in memory on both sides; server rejects >100 MiB with `413 File is too large`, non-files with `400 Path is not a file`, and credential files with `403 Access to sensitive files is not allowed`. Note the page does **not** use the streaming `GET /api/files/download` / `/api/files/stream` routes — those exist for the desktop app and media playback.
- **Rebuild notes:** Better: link straight at `/api/files/download?path=…&token=…` (already implemented server-side) to avoid the base64 round-trip entirely.

### Row action — Delete  `id: web-a.files.row.delete`
- **Surface:** Web dashboard
- **Where:** Last action button on every row — ghost icon button with `Trash2` in `text-destructive`, `aria-label="Delete <name>"` (crawl: `Delete .aws`, `Delete .bashrc`, …).
- **What it does:** Asks for confirmation, then permanently deletes the file or the folder and its contents.
- **How it works:** `FilesPage.tsx:441-450` → `setPendingDelete(entry)` opens `DeleteConfirmDialog`; `confirmDelete()` (`:248-261`) calls `api.deleteFile(pendingDelete.path, pendingDelete.is_directory)` → `DELETE /api/files` with JSON `{path, recursive}` where `recursive` = *is_directory* (so folder deletes are always recursive), then toast `Deleted` (success), `setPendingDelete(null)`, `load()`.
- **Inputs / options:** click → dialog → `Delete` / `Cancel`. The button label is the hard-coded English template `` aria-label={`Delete ${entry.name}`} `` (`FilesPage.tsx:446`) and the dialog title the matching `` `Delete ${pendingDelete.name}?` `` (`FilesPage.tsx:517`) — neither is internationalised. Complete list of the button instances rendered by the live install at the default root `/root` (`hermes_inv/web_crawl/_files.json`, state `initial`, all 22 rows): `Delete .aws`, `Delete .bun`, `Delete .cache`, `Delete .cargo`, `Delete .ccr`, `Delete .claude`, `Delete .config`, `Delete .gradle`, `Delete .hermes`, `Delete .launchpadlib`, `Delete .local`, `Delete .npm`, `Delete .pki`, `Delete .rustup`, `Delete .ssh`, `Delete .bashrc`, `Delete .boto`, `Delete .claude.json`, `Delete .gitconfig`, `Delete .profile`, `Delete .wget-hsts`, `Delete .zshrc` — each opening the confirm dialog titled `Delete .aws?` … `Delete .zshrc?` respectively.
- **Outputs / side effects:** `shutil.rmtree` (directory) or `Path.unlink` (file) on the server (`web_server.py:3108-3117`); toast `Deleted` or `` `Delete failed: ${e}` ``.
- **Config / env:** n/a.
- **Edge cases / guards:** server refuses `400 Cannot delete the managed files root` and `400 Cannot delete the filesystem root`; `404 Path not found`; OS errors map to 409 for a non-empty dir without `recursive`, else 500 `Could not delete path: …`. There is **no** trash/undo.
- **Rebuild notes:** Confirm-then-DELETE. Better: move to a trash directory with a restore window, and refuse deletes outside an explicit workspace.

### "Create folder" dialog  `id: web-a.files.create-dialog`
- **Surface:** Web dashboard
- **Where:** Modal (`max-w-sm`) opened by `CREATE`. Title `Create folder`; description `Target: <activePath>` (or `Target: Loading` before the first listing); body input with placeholder `Folder name`; footer buttons `Cancel` (outlined) and `Create` (prefix `FolderPlus`, or `Spinner` while creating).
- **What it does:** Creates a sub-directory of the current directory.
- **How it works:** `FilesPage.tsx:460-509`. `createDirectory()` (`:167-189`): no `activePath` → toast `Directory unavailable` (error); empty trimmed name → toast `Folder name required` (error); otherwise `api.createDirectory(joinPath(activePath, name))` → `POST /api/files/mkdir` `{path}`; on success clears the name, closes the dialog, toasts `Folder created` (success) and reloads; on failure toasts `` `Create failed: ${e}` ``. `joinPath` (`:45-51`) strips leading slashes/backslashes from the typed name and picks `\` as the separator only when the base already looks like a Windows path (`base.includes("\\") && !base.includes("/")`).
- **Inputs / options:** the text input (`autoFocus`, `Enter` submits via `onKeyDown`), `Cancel`, `Create`. Clicking the overlay / pressing `Escape` also closes it, unless `creating` is true (`onOpenChange` returns early, `:463`), and closing always clears the typed name (`:465`).
- **Outputs / side effects:** `mkdir(parents=True, exist_ok=True)` on the server; listing refresh.
- **Config / env:** n/a.
- **Edge cases / guards:** nested names like `a/b/c` are allowed and create the whole chain (`parents=True`); a leading `/` is stripped client-side so the folder is always created *inside* the current directory; `409 A file already exists at that path`; `403 Directory is not writable`.
- **Rebuild notes:** Trivial modal + POST. Better: inline "new folder" row with rename-in-place, and a duplicate-name check before submitting.

### Delete confirmation dialog  `id: web-a.files.delete-dialog`
- **Surface:** Web dashboard
- **Where:** Destructive alert dialog. Title `Delete <name>?` (or `Delete item?` when nothing is pending); description `This removes the folder and everything inside it.` for directories, `This removes the file.` for files; buttons `Delete` (destructive, `i18n: common.delete`) and `Cancel` (`i18n: common.cancel`); a warning-triangle glyph in the header.
- **What it does:** Guards the irreversible delete.
- **How it works:** `FilesPage.tsx:511-522` renders `components/DeleteConfirmDialog.tsx:4-29`, a thin wrapper over `@nous-research/ui` `ConfirmDialog` with `destructive` set and default labels `t.common.delete` / `t.common.cancel`. The primitive is Radix `AlertDialog` (`node_modules/@nous-research/ui/src/ui/components/confirm-dialog.tsx:28-118`): while `loading` both buttons are disabled and the confirm label is replaced by `…`; dismissing without confirming calls `onCancel`.
- **Inputs / options:** `Delete`, `Cancel`, `Escape`, overlay click.
- **Outputs / side effects:** see `web-a.files.row.delete`.
- **Config / env:** n/a.
- **Edge cases / guards:** shared by many dashboard pages, so the wording is generic; the loading state prevents double-submit.
- **Rebuild notes:** Reusable destructive-confirm primitive with an ellipsis busy label.

### Toasts  `id: web-a.files.toasts`
- **Surface:** Web dashboard
- **Where:** Portaled to `document.body`, `fixed top-16 right-4 z-50`, `role="status" aria-live="polite"`, uppercase mono text; green (`success`) or red (`error`).
- **What it does:** Reports the outcome of every mutating action.
- **How it works:** `useToast()` (`node_modules/@nous-research/ui/src/hooks/use-toast.ts:5-28`) with the default 3000 ms auto-dismiss; `<Toast toast={toast}/>` (`FilesPage.tsx:265`) animates in/out over 200 ms (`toast-in` / `toast-out`).
- **Inputs / options:** none (no close button, no stacking — a new toast replaces the previous one and restarts the timer).
- **Outputs / side effects:** transient UI only.
- **Config / env:** n/a.
- **Edge cases / guards:** Complete list of Files-page toast messages, verbatim: `Path required` (error), `Directory unavailable` (error), `Folder name required` (error), `Folder created` (success), `` `Create failed: ${e}` `` (error), `` `${n} file uploaded` `` / `` `${n} files uploaded` `` (success), `` `Upload failed: ${e}` `` (error), `` `Download failed: ${e}` `` (error), `Deleted` (success), `` `Delete failed: ${e}` `` (error). `${e}` is the raw `Error` object stringified, so it reads `Error: 413: File is too large`.
- **Rebuild notes:** Single-slot toast host. Better: a queue with dismiss buttons and retry actions.

### Loading / empty / error states  `id: web-a.files.states`
- **Surface:** Web dashboard
- **Where:** Inside the listing card.
- **What it does:** Covers the three non-happy states.
- **How it works:** (1) **Loading** — while `loading && !listing`: a centred `Spinner` plus the literal `Loading files...` (`FilesPage.tsx:390-394`). Note the three ASCII dots, not an ellipsis character. (2) **Empty** — `listing.entries.length === 0`: centred `No files` (`:395-396`). (3) **Error** — a red banner above the header row (`border-b border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive`) whose text is `String(e)` from the failed load, e.g. `Error: 403: Path outside managed files root` (`:361-365`, set at `:112`). The banner persists until the next load attempt clears it.
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** a refresh that fails keeps the previous listing visible under the banner (`listing` is not cleared on error).
- **Rebuild notes:** Three literal states. Better: skeleton rows, a retry button in the banner, and typed error codes instead of stringified exceptions.

### `GET /api/files` (list directory)  `id: web-a.files.api.list`
- **Surface:** API
- **Where:** `hermes_cli/web_server.py:2830-2861`; client `api.listFiles` (`lib/api.ts:471-474`).
- **What it does:** Lists one directory under the managed-files policy.
- **How it works:** `_resolve_managed_path(path, request)` → policy + canonical target; 404 `Path not found` if missing, 400 `Path is not a directory` if not a dir; `os.scandir` filtered by `_is_sensitive_path`; each entry via `_managed_file_entry` (`:2696-2719`) → `{name, path, is_directory, size (None for dirs), mtime, mime_type (guessed, None for dirs)}`; sorted directories-first then `name.lower()`; `parent` = `str(target.parent)` unless the target is the filesystem root or equals `locked_root`.
- **Inputs / options:** query `path` (optional; omitted → `policy.default_path`, i.e. `Path.home()` unlocked or the locked root).
- **Outputs / side effects:** `{path, parent, entries[], root, locked_root, can_change_path}` (`_managed_response_meta`, `:2688-2694`; `root` and `locked_root` are the same string or both `null`). Read-only.
- **Config / env:** `HERMES_DASHBOARD_FILES_ROOT`; `HERMES_HOME`.
- **Edge cases / guards:** 403 `Directory is not readable` (PermissionError), 500 `Could not read directory: <err>`, 403 `Path outside managed files root`, 400 `Path must be absolute` / `Path cannot contain '..'` / `Invalid path` (NUL byte).
- **Rebuild notes:** Canonicalise → policy-check → scandir → filter → sort.

### `GET /api/files/read` (base64 read)  `id: web-a.files.api.read`
- **Surface:** API
- **Where:** `web_server.py:2863-2896`; client `api.readFile` (`lib/api.ts:475-478`).
- **What it does:** Returns a whole file as a base64 `data:` URL so the browser can download it without a second authenticated request.
- **How it works:** Policy resolve → 404 `File not found` → 400 `Path is not a file` → 403 `Access to sensitive files is not allowed` (`_is_sensitive_path`) → 413 `File is too large` above 100 MiB → `mimetypes.guess_type` (fallback `application/octet-stream`) → `base64.b64encode(target.read_bytes())`.
- **Inputs / options:** query `path` (required).
- **Outputs / side effects:** `{name, path, size, mime_type, data_url, root, locked_root, can_change_path}`.
- **Config / env:** as above.
- **Edge cases / guards:** 403 `File is not readable`, 500 `Could not stat file: …` / `Could not read file: …`. Memory cost ≈ 2.33× file size.
- **Rebuild notes:** Keep for small files only; prefer the streaming route.

### `GET /api/files/download` (attachment stream)  `id: web-a.files.api.download`
- **Surface:** API
- **Where:** `web_server.py:2934-2957` (not called by the Files page; used by the desktop app and by links).
- **What it does:** Streams a managed file as a download.
- **How it works:** `_managed_file_response(..., content_disposition_type="attachment")` → Starlette `FileResponse` with range support. When the request's `Sec-Fetch-Dest` header is `audio` or `video` it flips to `inline` **and** enforces `media_only`, adding `X-Content-Type-Options: nosniff`.
- **Inputs / options:** query `path`; additionally accepts the session token as `?token=` because `"/api/files/download"` is the sole member of `_QUERY_TOKEN_API_PATHS` (`web_server.py:725`).
- **Outputs / side effects:** file bytes.
- **Config / env:** as above.
- **Edge cases / guards:** 404 / 400 / 403 / 413 as for read; 415 `Unsupported media type` when a media subresource asks for a non-media extension.
- **Rebuild notes:** One shared `_managed_file_response` builder parameterised by disposition.

### `GET|HEAD /api/files/stream` (inline media, Range)  `id: web-a.files.api.stream`
- **Surface:** API
- **Where:** `web_server.py:2959-2976`.
- **What it does:** Serves managed audio/video inline with HTTP Range so `<audio>`/`<video>` can seek — added because Electron's Chromium rejects attachment responses as media sources.
- **How it works:** Same `_managed_file_response` with `content_disposition_type="inline", media_only=True`.
- **Inputs / options:** query `path`; `GET` and `HEAD`.
- **Outputs / side effects:** file bytes / headers only.
- **Config / env:** `_STREAMABLE_MEDIA_EXTENSIONS` = `.avi .flac .m4a .mkv .mov .mp3 .mp4 .ogg .opus .wav .webm` (`web_server.py:2193-2207`).
- **Edge cases / guards:** 415 for any other extension; 100 MiB cap applies.
- **Rebuild notes:** Separate inline route rather than content-negotiating the download route.

### `POST /api/files/upload` (legacy base64 upload)  `id: web-a.files.api.upload-json`
- **Surface:** API
- **Where:** `web_server.py:2978-3011`. **Superseded** — the SPA no longer calls it (see the comment at `lib/api.ts:480-485`).
- **What it does:** Writes a file from a base64 data URL in a JSON body.
- **How it works:** `_resolve_managed_path(..., for_write=True)`; 409 `A directory already exists at that path`; 409 `File already exists` when `overwrite` is false; `_decode_data_url` (`:2722-2736`) requires a `data:` prefix and `;base64` (400 `Upload payload must be a data URL` / `Upload payload must be base64 encoded` / `Upload payload is not valid base64`), enforces 413 `File is too large`; then `mkdir(parents=True)` + `write_bytes`.
- **Inputs / options:** JSON `{path, data_url, overwrite}` (`ManagedFileUpload`).
- **Outputs / side effects:** `{ok, entry, path, root, locked_root, can_change_path}`.
- **Config / env:** as above.
- **Edge cases / guards:** buffers the whole file twice in memory; inflates the body ~33 %; the reason NS-501 502'd behind proxies.
- **Rebuild notes:** Keep only for tiny payloads; the streaming sibling is the real path.

### `POST /api/files/upload-stream` (chunked multipart upload)  `id: web-a.files.api.upload-stream`
- **Surface:** API
- **Where:** `web_server.py:3013-3075`; client `api.uploadFile` (`lib/api.ts:479-493`).
- **What it does:** The upload path the Files page actually uses: streams the request body to disk in 1 MiB chunks and atomically renames it into place.
- **How it works:** FastAPI `File(...)` + `Form(...)`; policy resolve for write; 409 guards as above; `tempfile.mkstemp(prefix=f".{target.name}.", suffix=".upload", dir=target.parent)` then a `while` loop of `await file.read(1 MiB)` accumulating `total` and raising 413 `File is too large` as soon as the cap is crossed; `os.replace(tmp, target)`. The `finally` block unlinks the temp file on **every** non-success exit including `asyncio.CancelledError` (browser aborts) and always `await file.close()`.
- **Inputs / options:** multipart fields `file` (the bytes), `path` (string, required), `overwrite` (bool, default `true`). The client never sets `Content-Type` so the browser supplies the boundary.
- **Outputs / side effects:** `{ok:true, entry:{…}, path, root, locked_root, can_change_path}`; a `.<name>.*.upload` temp file exists transiently beside the target.
- **Config / env:** `_UPLOAD_CHUNK_BYTES = 1 MiB` (`:3011`), `_MANAGED_FILE_MAX_BYTES = 100 MiB`.
- **Edge cases / guards:** 403 `File is not writable`, 500 `Could not create parent directory: …` / `Could not write file: …`; a partial upload never clobbers the existing file.
- **Rebuild notes:** Temp-file + `os.replace` is the whole trick. Better: content-hash dedupe, resumable ranges, and a per-request quota.

### `POST /api/files/mkdir`  `id: web-a.files.api.mkdir`
- **Surface:** API
- **Where:** `web_server.py:3077-3096`; client `api.createDirectory` (`lib/api.ts:494-499`).
- **What it does:** Creates a directory (and any missing parents) inside the managed root.
- **How it works:** write-mode policy resolve; 409 `A file already exists at that path`; `target.mkdir(parents=True, exist_ok=True)`.
- **Inputs / options:** JSON `{path}` (`ManagedDirectoryCreate`).
- **Outputs / side effects:** `{ok:true, entry, path, root, locked_root, can_change_path}`.
- **Config / env:** as above.
- **Edge cases / guards:** 403 `Directory is not writable`, 500 `Could not create directory: …`; idempotent (`exist_ok=True`).
- **Rebuild notes:** One-liner behind the policy.

### `DELETE /api/files`  `id: web-a.files.api.delete`
- **Surface:** API
- **Where:** `web_server.py:3098-3120`; client `api.deleteFile` (`lib/api.ts:500-505`).
- **What it does:** Deletes a file, an empty directory, or (with `recursive`) a whole tree.
- **How it works:** Read-mode policy resolve (note: **not** `for_write`); refuses `target == policy.locked_root` (400 `Cannot delete the managed files root`) and `target.parent == target` (400 `Cannot delete the filesystem root`); 404 `Path not found`; then `shutil.rmtree` / `Path.rmdir` / `Path.unlink`.
- **Inputs / options:** JSON `{path, recursive}` (`ManagedFileDelete`; the SPA sets `recursive = entry.is_directory`).
- **Outputs / side effects:** `{ok:true, path, root, locked_root, can_change_path}`; permanent data loss.
- **Config / env:** as above.
- **Edge cases / guards:** OSError → 409 when the target is a non-empty directory and `recursive` is false, else 500 `Could not delete path: …`. The sensitive-file denylist does **not** apply to deletes (it is explicitly documented as read-side only, `web_server.py:2296-2315`), so a `.env` you cannot list can still be deleted by exact path.
- **Rebuild notes:** Better: apply the sensitive-path guard to writes too, and require a typed confirmation for recursive deletes.

### Managed-files root policy (locked vs. browsable)  `id: web-a.files.policy`
- **Surface:** Core
- **Where:** `web_server.py:2211-2215` (`ManagedFilesPolicy` dataclass), `:2628-2648` (`_managed_files_policy`), `:2650-2686` (`_resolve_managed_path`).
- **What it does:** Decides which directory tree the Files page may see and whether the user may type an arbitrary path.
- **How it works:** Three cases, in order. (1) `HERMES_DASHBOARD_FILES_ROOT` set → `ManagedFilesPolicy(default_path=root, locked_root=root, can_change_path=False)` and the root is created if missing (`_ensure_managed_root`). (2) Otherwise, if the installation's Hermes root resolves to `/opt/data` (`_default_hermes_root_is_opt_data`, `:2578-2589` — the container/hosted layout) → locked to `/opt/data`. (3) Otherwise → `default_path = Path.home()`, `locked_root = None`, `can_change_path = True`. `_resolve_managed_path` then: rejects NUL bytes (400 `Invalid path`), maps `""`/`"."`/`"/"` to the locked root, expands `~`, resolves relative paths against the root in locked mode (400 `Path must be absolute` when unlocked), rejects any `..` component, canonicalises with `resolve()`, and finally enforces `_path_is_under(root, resolved)` → 403 `Path outside managed files root`.
- **Inputs / options:** n/a (server-side).
- **Outputs / side effects:** `root` / `locked_root` / `can_change_path` echoed on every managed-file response and used by the SPA to hide the path bar.
- **Config / env:** `HERMES_DASHBOARD_FILES_ROOT`, `HERMES_HOME`.
- **Edge cases / guards:** Remote/OAuth access does **not** by itself lock the root — a local install exposed through the auth gate still browses `$HOME` (comment at `:2634-2638`). `_path_is_under` compares against the *resolved* path, so symlinks escaping the root are blocked.
- **Rebuild notes:** Resolve-then-contain is the only safe order. Better: per-user roots, an explicit allowlist of trees, and a read-only mode flag.

### Sensitive-file exclusion (credential denylist)  `id: web-a.files.sensitive-guard`
- **Surface:** Core
- **Where:** `web_server.py:2244-2315`.
- **What it does:** Hides credential files and credential directories from listing, read and download so the dashboard file browser cannot exfiltrate secrets (issue #57505).
- **How it works:** `_is_sensitive_filename` (case-insensitive) matches `.env`, any `.env.<suffix>`, `.envrc`, plus the basename set `_SENSITIVE_MANAGED_FILE_BASENAMES` = `auth.json`, `auth.lock`, `credentials`, `config.yaml`, `.anthropic_oauth.json`, `google_token.json`, `google_oauth_pending.json`, `google_oauth.json`, `webhook_subscriptions.json`, `bws_cache.json`, `bws_cache.enc.json`, `.git-credentials`. `_is_sensitive_path` additionally returns true when **any** path component (case-insensitive) is in `_SENSITIVE_MANAGED_DIR_NAMES` = `mcp-tokens`, `pairing`. Applied at `/api/files` (filter), `/api/files/read`, and `_managed_file_response` (download/stream).
- **Inputs / options:** n/a.
- **Outputs / side effects:** matching entries silently vanish from listings; direct reads return 403 `Access to sensitive files is not allowed`.
- **Config / env:** the lists are hard-coded, mirroring `agent.file_safety.get_read_block_error` and `gateway.platforms.base._ROOT_CREDENTIAL_FILES` / `_ROOT_CREDENTIAL_DIRS`.
- **Edge cases / guards:** Read-side only — upload, mkdir and delete are **not** filtered (documented at `:2308-2314`). Note `config.yaml` is denied by basename anywhere in the tree, so a legitimate project `config.yaml` is also invisible.
- **Rebuild notes:** Denylist by basename + path component, case-insensitive, applied at every read call site. Better: an allowlist-driven workspace root plus content-based secret detection, and the same guard on writes.

### Plugin slots on the Files page  `id: web-a.files.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `<PluginSlot name="files:top"/>` (`FilesPage.tsx:266`, directly under the toast host) and `<PluginSlot name="files:bottom"/>` (`:458`, between the listing card and the dialogs).
- **What it does:** Injection points where dashboard plugins can render extra UI on this page.
- **How it works:** Plugin slot registry (`@/plugins`) — documented in the plugins shard.
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** n/a.
- **Rebuild notes:** Named render slots around the page body.

---

## D. Analytics page (`/analytics`)

### Analytics page (token & skill usage)  `id: web-a.analytics.page`
- **Surface:** Web dashboard
- **Where:** Sidebar nav link `ANALYTICS` (`App.tsx:194-199` `{ path:"/analytics", labelKey:"analytics", label:"Analytics", icon: BarChart3 }`, `i18n: app.nav.analytics` = "Analytics"), URL `/analytics`; page `<h1>` "Analytics" (`lib/resolve-page-title.ts:6` → `t.app.nav.analytics`). Crawl `_analytics.json` confirms `H1 = "Analytics"`.
- **What it does:** Shows a local, self-reported estimate of LLM token usage over the last 7/30/90 days: headline totals, a stacked daily bar chart, a per-day table, a per-model table and a top-skills table. It is off by default and replaced by a warning card explaining why the numbers are unreliable.
- **How it works:** `pages/AnalyticsPage.tsx:406-604`, lazy-imported (`App.tsx:86`, route `App.tsx:160`). Mount order: (1) an effect calls `api.getConfig()` and sets `showTokens = cfg.dashboard.show_token_analytics === true`, defaulting to `false` on any error (`:419-427`); (2) `load()` (`:429-438`) early-returns unless `showTokens`, then `api.getAnalytics(days)` → `GET /api/analytics/usage?days=<n>&profile=<p>`; (3) a `useEffect` re-runs `load` whenever `days` or `showTokens` change (`:480-482`). State: `days` (default `30`), `data: AnalyticsResponse | null`, `loading` (starts `true`), `error`, `showTokens: boolean | null` (`null` = config not answered yet, so neither branch renders). Body layout (`:485-602`): plugin slot → hidden-card (when off) → spinner → error card → a `lg:grid-cols-2` row of [`Stats` card | `TokenBarChart`] → `DailyTable` → `ModelTable` → `SkillTable` → empty-state card → plugin slot. Nothing is persisted: the selected period resets to 30 days on every mount, there is no localStorage and no auto-refresh timer.
- **Inputs / options:** period buttons `7d` / `30d` / `90d`, the refresh icon button, the sortable column headers of the three tables, hover on chart bars. No text inputs, no keyboard shortcuts.
- **Outputs / side effects:** read-only; two GETs (`/api/config`, `/api/analytics/usage`).
- **Config / env:** `dashboard.show_token_analytics` (bool, **default `false`** — `hermes_cli/config_defaults.py:1696`) gates the whole page *and* the sidebar entry (`App.tsx:412-466`: the nav item is filtered out when the flag is off, but the route itself stays registered so `/analytics` is still reachable by URL). `/api/analytics` is in `PROFILE_SCOPED_PREFIXES` (`lib/api.ts:76`), so the header profile switcher re-scopes the numbers via `?profile=`.
- **Edge cases / guards:** With the flag off the page never calls `/api/analytics/usage` at all. The empty-state card is rendered from `data && …lengths===0` **outside** the `showTokens &&` guard, so it can only appear when data was actually fetched. `days` is clamped server-side to 1-365.
- **Rebuild notes:** Minimal spec: one GET returning `{daily[], by_model[], by_task[], totals{}, skills{}, tools[]}` and a period switch; render four cards. A better version would reconcile against provider billing APIs, include cache-write and auxiliary usage in the headline (the data is already in `by_task`), show cost in currency, and let the user export CSV.

### "Token analytics hidden" explanation card  `id: web-a.analytics.hidden-card`
- **Surface:** Web dashboard
- **Where:** The only content when `dashboard.show_token_analytics` is false. `<h2>` `Token analytics hidden` (CSS-uppercased → crawl `"TOKEN ANALYTICS HIDDEN"`), three paragraphs, and an inline link `Config` → `/config`.
- **What it does:** Explains why the numbers are hidden and how to turn them on.
- **How it works:** `AnalyticsPage.tsx:488-523`. Verbatim body (three `<p>` blocks, with `usage` and `dashboard.show_token_analytics: true` in mono): (1) "The token, cost, and per-day analytics on this page are a local debug estimate. They only count successful main-agent responses with a usable `usage` block, and silently exclude auxiliary calls (context compression, title generation, vision, session search, web extract, smart approvals, MCP routing, plugin LLM access) plus provider-side retries and fallback attempts. Cache writes are missing entirely." (2) "On models with heavy auxiliary traffic (Kimi K2.6, MiniMax M2.7) the local total can be 10x–100x lower than what your provider bills. Hiding these numbers is safer than letting them look authoritative." (3) "Check your provider dashboard (OpenRouter, Anthropic, etc.) for actual usage and billing. To re-enable the local debug estimate anyway, set `dashboard.show_token_analytics: true` in Config."
- **Inputs / options:** the `Config` link (plain `<a href="/config" class="underline">`, so it does a full page navigation rather than a client-side route change).
- **Outputs / side effects:** none.
- **Config / env:** `dashboard.show_token_analytics`.
- **Edge cases / guards:** All of this text is **hard-coded English**, not in `i18n/en.ts` — a mechanical string checker will find it only in `AnalyticsPage.tsx:493-518`. When the card shows, the period/refresh controls are removed from the header (`setAfterTitle(null)` at `:446`).
- **Rebuild notes:** Honest-by-default gating: hide a misleading metric behind a flag and say why. A better version would show the *complete* number (main + aux + cache) so it never needs hiding.

### Period selector — `7d` / `30d` / `90d`  `id: web-a.analytics.period`
- **Surface:** Web dashboard
- **Where:** Page header, immediately after the "Analytics" title (the `afterTitle` slot). Three small buttons labelled exactly `7d`, `30d`, `90d`.
- **What it does:** Chooses the analytics window; the active one is the filled (non-outlined) button.
- **How it works:** `AnalyticsPage.tsx:28-32` (`PERIODS = [{label:"7d",days:7},{label:"30d",days:30},{label:"90d",days:90}]`), rendered at `:448-458` inside a `useLayoutEffect` that repopulates the header slot on every relevant state change (`:440-478`). `outlined={days !== p.days}` conveys selection — the comment at `:441-444` says the period badge was deliberately removed as redundant. Clicking sets `days`, which re-runs `load()`.
- **Inputs / options:** exactly three buttons; there is no custom range, no "all time".
- **Outputs / side effects:** `GET /api/analytics/usage?days=7|30|90`; the "Total Sessions" stat's per-day average divides by the same `days`.
- **Config / env:** `i18n:` none — the labels are literals.
- **Edge cases / guards:** the selection is not persisted; server clamps `days` to `1..365` (`web_server.py:15884`).
- **Rebuild notes:** Three presets bound to one query param. Better: a date-range picker plus comparison against the previous period.

### Analytics refresh button  `id: web-a.analytics.refresh`
- **Surface:** Web dashboard
- **Where:** Header, right of the period buttons — ghost icon button, `aria-label` = `Refresh` (`i18n: common.refresh`), icon `RefreshCw`, replaced by a `Spinner` while loading.
- **What it does:** Re-runs the analytics query for the current period.
- **How it works:** `AnalyticsPage.tsx:459-469` → `onClick={load}`; `disabled={loading}`.
- **Inputs / options:** click.
- **Outputs / side effects:** one GET; clears `error` first.
- **Config / env:** n/a.
- **Edge cases / guards:** hidden entirely when `showTokens === false`.
- **Rebuild notes:** Same pattern as every other dashboard page's refresh.

### Totals card (`Stats`)  `id: web-a.analytics.totals`
- **Surface:** Web dashboard
- **Where:** Left half of the first row. Five dotted-leader rows, label on the right, value on the left.
- **What it does:** Headline numbers for the selected period.
- **How it works:** `AnalyticsPage.tsx:542-574` feeds `@nous-research/ui` `Stats` (`node_modules/@nous-research/ui/src/ui/components/stats.tsx:7-45`, which draws a 100-dot leader between value and label). The five items, in order: (1) label `Total Tokens` (`i18n: analytics.totalTokens`), value `formatTokens(totals.total_input + totals.total_output)`; (2) `Input` (`i18n: analytics.input`) = `formatTokens(total_input)`; (3) `Output` (`i18n: analytics.output`) = `formatTokens(total_output)`; (4) `Total Sessions` (`i18n: analytics.totalSessions`) = `` `${total_sessions} (~${(total_sessions/days).toFixed(1)}/day avg)` `` where the suffix is `i18n: analytics.perDayAvg` = "/day avg"; (5) `API Calls` (`i18n: analytics.apiCalls`) = `total_api_calls`, falling back to `daily.reduce((s,d)=>s+d.sessions,0)` when the field is null. `formatTokens` (`:36-40`): `≥1e6 → "<n.n>M"`, `≥1e3 → "<n.n>K"`, else the raw integer.
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** SQLite `SUM()` over zero rows returns `NULL`, which JSON-serialises to `null`; `formatTokens(null)` then produces the string `"null"` — visible on a fresh install (live `/api/analytics/usage` returns `"total_input": null`). `total_sessions / days` is `0.0` for an empty DB.
- **Rebuild notes:** Coalesce sums to 0 server-side. Better: show cost, cache reads and reasoning tokens (all present in `totals`) instead of dropping them.

### "Daily Token Usage" stacked bar chart  `id: web-a.analytics.chart`
- **Surface:** Web dashboard
- **Where:** Right half of the first row. Card title `Daily Token Usage` (`i18n: analytics.dailyTokenUsage`) with a `BarChart3` icon; a legend with two swatches labelled `Input` (`i18n: analytics.input`) and `Output` (`i18n: analytics.output`); the 160 px-tall bar strip; and a three-label date axis underneath.
- **What it does:** One bar per day, input tokens stacked above output tokens, scaled to the busiest day.
- **How it works:** `AnalyticsPage.tsx:130-233`. Returns `null` when `daily.length === 0` (so the card vanishes rather than showing an empty frame). `maxTokens = Math.max(...daily.map(d => d.input+d.output), 1)`. Each day is a `flex-1` column of fixed height `CHART_HEIGHT_PX = 160` (`:34`); the input segment height is `round(input/max*160)` but at least `1` px when the day has any tokens, the output segment `round(output/max*160)` with a 1 px floor when `output_tokens > 0`. Colours come from CSS custom properties `--series-input-token` (default `#ffe6cb`) and `--series-output-token` (default `#34d399`) — `index.css:86-88`, re-bound per theme by `themes/context.tsx:160-161` from the theme keys `inputTokenAccent` / `outputTokenAccent`. Bars use `color-mix(in srgb, var(--series-…-token) 70%, transparent)`. The axis row prints `formatDate(daily[0].day)`, the middle day (only when `daily.length > 2`), and `formatDate(daily[last].day)` (only when `length > 1`). `formatDate` (`:42-49`) parses `"<YYYY-MM-DD>T00:00:00"` in local time and renders `toLocaleDateString(undefined,{month:"short",day:"numeric"})`, e.g. `Sep 5`.
- **Inputs / options:** hover a column → a tooltip card appears above it (`hidden group-hover:block`, `pointer-events-none`) with four lines: the bold date, `Input: <tokens>`, `Output: <tokens>`, `Total: <tokens>` (labels `i18n: analytics.input` / `analytics.output` / `analytics.total`, values via `formatTokens`).
- **Outputs / side effects:** none.
- **Config / env:** theme keys `inputTokenAccent`, `outputTokenAccent`.
- **Edge cases / guards:** Days with zero usage still occupy a column but draw no pixels; missing days are simply absent (the SQL groups by observed days, it does not fill gaps), so the x-axis is not uniform in time. No y-axis, no gridlines, no values on the bars.
- **Rebuild notes:** Pure-CSS stacked bars, no chart library. Better: fill missing days with zeros, add a y-axis and a cost overlay, and make bars keyboard-focusable so the tooltip is accessible.

### "Daily Breakdown" table  `id: web-a.analytics.daily-table`
- **Surface:** Web dashboard
- **Where:** Below the first row. Card title `Daily Breakdown` (`i18n: analytics.dailyBreakdown`) with a `TrendingUp` icon.
- **What it does:** One row per day with the session count and input/output tokens.
- **How it works:** `AnalyticsPage.tsx:235-292`. Returns `null` when there are no days. Columns (all sortable, see `web-a.analytics.sorting`): `Date` (`i18n: analytics.date`, sort key `day`, left aligned), `Sessions` (`i18n: sessions.title`, key `sessions`), `Input` (`i18n: analytics.input`, key `input_tokens`, coloured `--series-input-token`), `Output` (`i18n: analytics.output`, key `output_tokens`, coloured `--series-output-token`). Default sort `day` descending. Cells: `formatDate(d.day)`, raw `d.sessions`, `formatTokens(d.input_tokens)`, `formatTokens(d.output_tokens)`.
- **Inputs / options:** four clickable headers; rows are not clickable.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** wrapped in `overflow-x-auto`; `estimated_cost`, `actual_cost`, `cache_read_tokens`, `reasoning_tokens` and `api_calls` are present in the payload but **not rendered**.
- **Rebuild notes:** Client-side sorted table over the same array the chart uses.

### "Per-Model Breakdown" table  `id: web-a.analytics.model-table`
- **Surface:** Web dashboard
- **Where:** Third card. Title `Per-Model Breakdown` (`i18n: analytics.perModelBreakdown`) with a `Cpu` icon.
- **What it does:** Tokens and session counts per model id for the period.
- **How it works:** `AnalyticsPage.tsx:294-349`. Hidden when `by_model` is empty. Columns: `Model` (`i18n: analytics.model`, key `model`, rendered in `font-mono-ui text-xs`), `Sessions` (`i18n: sessions.title`, key `sessions`), `Tokens` (`i18n: analytics.tokens`, key `input_tokens`) whose cell is `formatTokens(input)` in the input colour, then the literal `" / "`, then `formatTokens(output)` in the output colour. Default sort `input_tokens` descending. The rows include auxiliary-only models: the backend merges `session_model_usage` task rows into `by_model` via `_merge_aux_into_by_model` (`web_server.py:15734-15779`), so a vision- or compression-only model gets its own row (issue #23270).
- **Inputs / options:** three clickable headers.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** sorting by `Tokens` actually sorts by `input_tokens` alone, not by the displayed input+output sum; the per-model `estimated_cost`, `api_calls` and `aux_tasks` fields are not rendered here (the Models page shows them).
- **Rebuild notes:** Better: sort on the composite total and expand a row to reveal its `aux_tasks` breakdown.

### "Top Skills" table  `id: web-a.analytics.skill-table`
- **Surface:** Web dashboard
- **Where:** Fourth card. Title `Top Skills` (`i18n: analytics.topSkills`) with a `Brain` icon.
- **What it does:** Which skills the agent loaded and managed most, and when each was last used.
- **How it works:** `AnalyticsPage.tsx:351-404`. Hidden when `skills.top_skills` is empty. Columns: `Skill` (`i18n: analytics.skill`, key `skill`, mono), `Agent Loaded` (`i18n: analytics.loads`, key `view_count`), `Agent Managed` (`i18n: analytics.edits`, key `manage_count`), `Total` (`i18n: analytics.total`, key `total_count`), `Last Used` (`i18n: analytics.lastUsed`, key `last_used_at`). Default sort `total_count` descending. The last cell renders `timeAgo(skill.last_used_at)` or the em-dash `—` when null. `timeAgo` (`lib/utils.ts:18-25`) returns `just now` (<60 s), `<n>m ago`, `<n>h ago`, `yesterday` (<48 h), else `<n>d ago`.
- **Inputs / options:** five clickable headers.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** the payload also carries `percentage` and a `skills.summary` object (`total_skill_loads`, `total_skill_edits`, `total_skill_actions`, `distinct_skills_used`) — **neither is rendered** anywhere on this page. Data comes from `agent.insights.InsightsEngine(db).get_usage_breakdown(days)`.
- **Rebuild notes:** Better: surface the summary counters and link each skill row to the Skills page.

### Sortable column headers  `id: web-a.analytics.sorting`
- **Surface:** Web dashboard
- **Where:** Every `<th>` in the three tables — the label followed by a sort glyph, with a hover background (`hover:bg-muted/40`).
- **What it does:** Click a header to sort by that column; click again to flip the direction.
- **How it works:** `useTableSort` hook (`AnalyticsPage.tsx:55-89`) keeps `sortKey`/`sortDir` and returns a memoised copy sorted with a generic comparator: `null`/`undefined` values always sink to the bottom regardless of direction (`:68-69`); equal values return 0; otherwise `a > b ? 1 : -1` flipped by direction. `toggle(key)` (`:76-86`) flips direction when the key is unchanged, otherwise switches key and resets to `desc`. `SortHeader` (`:91-126`) shows `ArrowUp` when active+asc, `ArrowDown` when active+desc, and a dimmed `ArrowUpDown` when inactive.
- **Inputs / options:** click on any header cell (whole `<th>` is the target, `cursor-pointer select-none`).
- **Outputs / side effects:** local re-render only; the sort is not persisted and resets on remount or period change.
- **Config / env:** n/a.
- **Edge cases / guards:** string columns sort lexicographically (`day` strings are ISO so this is also chronological; `model` and `skill` sort by codepoint, case-sensitively). No `aria-sort` attribute and the header is a `<th>`, not a button, so it is not keyboard reachable.
- **Rebuild notes:** ~30-line generic hook. Better: make headers real buttons with `aria-sort`, and add a numeric-aware comparator.

### Loading, error and empty states  `id: web-a.analytics.states`
- **Surface:** Web dashboard
- **Where:** Centre of the page body.
- **What it does:** Covers the three non-happy states.
- **How it works:** (1) **Loading** — `showTokens && loading && !data`: a centred `Spinner className="text-2xl text-primary"` in a `py-24` block (`AnalyticsPage.tsx:525-529`); subsequent refreshes keep the old data on screen. (2) **Error** — `showTokens && error`: a card with the stringified exception centred in `text-sm text-destructive` (`:531-537`), e.g. `Error: 500: …`. (3) **Empty** — when `data` exists and `daily`, `by_model` and `skills.top_skills` are all empty: a card with a 40 %-opacity `BarChart3` icon, the line `No usage data for this period` (`i18n: analytics.noUsageData`) and the sub-line `Start a session to see analytics here` (`i18n: analytics.startSession`) (`:585-600`).
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** With an empty DB the totals card still renders above the empty-state card, showing `null` tokens and `0 (~0.0/day avg)` sessions — the empty check does not suppress it.
- **Rebuild notes:** Better: suppress the totals card when everything is empty, and give the error card a retry button.

### `GET /api/analytics/usage`  `id: web-a.analytics.api.usage`
- **Surface:** API
- **Where:** `hermes_cli/web_server.py:15882-15891` (route) → `_get_usage_analytics` (`:15810-15879`); client `api.getAnalytics(days, profile)` (`lib/api.ts:513-516`).
- **What it does:** Aggregates the session store into daily, per-model, per-aux-task, total, skill and tool usage for the last `days` days.
- **How it works:** Runs in a worker thread (`asyncio.to_thread`). Opens the profile's session DB read-only (`_open_session_db_for_profile`, `:12512`); `cutoff = time.time() - days*86400`. Four SQL passes over the `sessions` table plus one over `session_model_usage`: (a) daily — `GROUP BY date(started_at,'unixepoch')` summing `input_tokens, output_tokens, cache_read_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd`, `COUNT(*) AS sessions`, `SUM(api_call_count)`; (b) per-model — same window, `model IS NOT NULL`, ordered by input+output desc; (c) `_aux_usage_rows` (`:15701-15731`) reads `session_model_usage` rows with `task != ''` grouped by `(model, task, billing_provider)` and returns `[]` if the table predates the `task` column; `_merge_aux_into_by_model` (`:15734-15779`) folds them in add-only and attaches an `aux_tasks[]` array per model; (d) totals across the window; (e) `InsightsEngine(db).get_usage_breakdown(days=days)` supplies `skills` and `tools`.
- **Inputs / options:** query `days` (int, default 30, `ge=1 le=365` — out-of-range → FastAPI 422), `profile` (optional, auto-appended by `withManagementProfile`).
- **Outputs / side effects:** `{daily[], by_model[], by_task[], totals{}, period_days, skills:{summary,top_skills}, tools[]}`. Read-only. Live empty-install response is recorded in `hermes_inv/api_live/get_all.json` under `/api/analytics/usage`.
- **Config / env:** the DB is `<profile home>/sessions.db`; not gated by `show_token_analytics` server-side (the flag is a UI-only gate).
- **Edge cases / guards:** `SUM()` over no rows yields `null` for every token field; `_aux_task_summary` (`:15782-15807`) builds `by_task` with a `models[]` list per task; the whole aux path is wrapped in `try/except` so an old schema degrades silently.
- **Rebuild notes:** One thread-offloaded read-only SQLite query set. Better: precomputed rollup tables and `COALESCE(...,0)` on every SUM.

### `by_task` and `tools` payload (fetched, never rendered here)  `id: web-a.analytics.unused-payload`
- **Surface:** API
- **Where:** `web_server.py:15869-15878`; consumed elsewhere (desktop "Capabilities" page aggregates `tools` per toolset, per the code comment at `:15876-15877`).
- **What it does:** `by_task` answers "what is compression / vision / title generation costing me" across models; `tools` gives per-tool-name call counts.
- **How it works:** `by_task` = `_aux_task_summary(aux_rows)` → `[{task, input_tokens, output_tokens, estimated_cost, api_calls, models:[…]}]` sorted by total tokens desc. `tools` comes straight from `InsightsEngine.get_usage_breakdown`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** transferred to the browser on every analytics load and discarded — `AnalyticsPage.tsx` never reads `data.by_task` or `data.tools`, and the TypeScript `AnalyticsResponse` interface (`lib/api.ts:2143-2160`) does not even declare them.
- **Config / env:** n/a.
- **Edge cases / guards:** the aux tasks observed in the code are `context compression`, `title generation`, `vision`, `session search`, `web extract`, `smart approvals`, `MCP routing`, `plugin LLM access` (enumerated in the hidden-card copy).
- **Rebuild notes:** A "where did the tokens go" card is one map over `by_task` away — this is the single highest-value missing widget on the page.

### Plugin slots on the Analytics page  `id: web-a.analytics.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `<PluginSlot name="analytics:top"/>` (`AnalyticsPage.tsx:486`) and `<PluginSlot name="analytics:bottom"/>` (`:601`).
- **What it does:** Injection points above and below the analytics cards.
- **How it works:** Plugin slot registry (plugins shard).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** both render even when the page content is the "Token analytics hidden" card.
- **Rebuild notes:** Named slots.

---

## E. Models page (`/models`)

### Models page (model settings + per-model usage)  `id: web-a.models.page`
- **Surface:** Web dashboard
- **Where:** Sidebar nav link `MODELS` (`App.tsx:200-205` `{ path:"/models", labelKey:"models", label:"Models", icon: Cpu }`, `i18n: app.nav.models` = "Models"), URL `/models`; `<h1>` "Models" (`lib/resolve-page-title.ts:7`). Crawl `_models.json` confirms `H1 = "Models"` and `H3 = "MODEL SETTINGS"`.
- **What it does:** The dashboard's model control panel: pick the main model, override the 11 auxiliary task models, configure Mixture-of-Agents presets, and browse a card per model actually used in the last 7/30/90 days with tokens, cost, capabilities and a "Use as" assignment menu.
- **How it works:** `pages/ModelsPage.tsx:1131-1367`, lazy-imported (`App.tsx:87`, route `App.tsx:161`). State: `days` (default 30), `data: ModelsAnalyticsResponse|null`, `aux: AuxiliaryModelsResponse|null`, `loading` (starts true), `error`, `saveKey` (a monotonic counter used as `refreshKey` to force child remounts after a save), `showTokens` (from `dashboard.show_token_analytics`, default false). `load()` (`:1160-1174`) runs `Promise.all([api.getModelsAnalytics(days), api.getAuxiliaryModels().catch(() => null)])` so a broken aux config still renders the usage cards. `onAssigned()` (`:1176-1180`) refetches aux and bumps `saveKey`. Layout (`:1240-1358`): plugin slot → a `lg:grid-cols-2` row of [`ModelSettingsPanel` | totals `Stats` card] → loading spinner → error card → a responsive card grid (`md:grid-cols-2 xl:grid-cols-3`) of `ModelCard`s, or the empty-state card → plugin slot.
- **Inputs / options:** period buttons `7D`/`30D`/`90D`, header refresh, `CHANGE` (main model), `CONFIGURE` (auxiliary), `CONFIGURE` (Mixture of Agents), and per-card `Use as` menus. Full enumeration in the entries below.
- **Outputs / side effects:** Writes `~/.hermes/config.yaml` keys `model.*`, `auxiliary.<task>.*` and `moa.*` through `POST /api/model/set` and `PUT /api/model/moa`. Everything applies to **new** sessions only.
- **Config / env:** `dashboard.show_token_analytics` (default `false`) hides the token/cost UI; `/api/model/info`, `/api/model/set`, `/api/model/auxiliary`, `/api/model/options` are profile-scoped (`lib/api.ts:85-89`) so the header profile switcher retargets both the reads and the writes — except `/api/model/moa`, which `api.getMoaModels()`/`saveMoaModels()` call **without** a profile param and which is not in `PROFILE_SCOPED_PREFIXES`, so MoA always edits the dashboard process's own profile.
- **Edge cases / guards:** A focus/`visibilitychange` listener (`:1220-1238`, throttled to one call per second, only when `document.visibilityState === "visible"`) refetches the assignments, because `/model --global`, the Config page and the CLI can change them behind the page's back. Analytics are *not* refetched on focus. `days` is not persisted.
- **Rebuild notes:** Minimal spec: `GET /api/analytics/models?days=` for the cards, `GET /api/model/auxiliary` for the current pins, `POST /api/model/set` to write them. A better version would show live provider pricing next to each card, warn when an aux pin points at an unauthenticated provider, and let the user drag a model onto a task slot.

### Period selector — `7D` / `30D` / `90D`  `id: web-a.models.period`
- **Surface:** Web dashboard
- **Where:** Page header after the "Models" title. Three small buttons whose DOM text is `7d`, `30d`, `90d` and which carry `className="uppercase"` → crawl reads `"7D"`, `"30D"`, `"90D"`.
- **What it does:** Picks the analytics window for the model cards and the totals card.
- **How it works:** `ModelsPage.tsx:46-50` (`PERIODS`), rendered at `:1186-1198` via `usePageHeader().setAfterTitle` inside a `useLayoutEffect`. Active period = the filled (non-`outlined`) button.
- **Inputs / options:** three buttons. Note this is the same `PERIODS` array as the Analytics page but with `className="uppercase"` added here.
- **Outputs / side effects:** `GET /api/analytics/models?days=…` + a re-fetch of `/api/model/auxiliary` (both are inside `load`).
- **Config / env:** n/a.
- **Edge cases / guards:** unlike Analytics, these controls are shown even when `show_token_analytics` is off (the page still has non-token content).
- **Rebuild notes:** Three presets → one query param.

### Models refresh button  `id: web-a.models.refresh`
- **Surface:** Web dashboard
- **Where:** Header, right of the period buttons — ghost icon button, `aria-label` = `Refresh` (`i18n: common.refresh`), `RefreshCw` icon / `Spinner` while loading.
- **What it does:** Re-runs both the analytics query and the auxiliary-assignment read.
- **How it works:** `ModelsPage.tsx:1199-1209` → `onClick={load}`, `disabled={loading}`.
- **Inputs / options:** click.
- **Outputs / side effects:** two GETs.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### "Model Settings" card  `id: web-a.models.settings-card`
- **Surface:** Web dashboard
- **Where:** Left card of the top row. Header: a `Settings2` icon, the title `Model Settings` (`<h3>`, CSS-uppercased → crawl `"MODEL SETTINGS"`) and the muted note `applies to new sessions`. Body: three rows — `Main model`, `Auxiliary tasks`, `Mixture of Agents` — each with a label, a mono status line and a right-hand button.
- **What it does:** The persistent-configuration half of the page: what model the agent uses by default, what the side-jobs use, and how the MoA virtual provider is composed.
- **How it works:** `ModelsPage.tsx:928-1122` (`ModelSettingsPanel`). It receives `aux` and `refreshKey` from the page and owns four pieces of local state: `auxModalOpen`, `moaModalOpen`, `moa: MoaConfigResponse|null` (loaded by an effect keyed on `refreshKey`: `api.getMoaModels().then(setMoa).catch(() => setMoa(null))`, `:949-951`), `picker: PickerTarget|null`, and `pendingReloadModel: string|null`. `applyAssignment` (`:953-975`) wraps `api.setModelAssignment` and calls `onSaved()` only when the response does **not** ask for confirmation.
- **Inputs / options:** the three rows' buttons (`CHANGE`, `CONFIGURE`, `CONFIGURE`).
- **Outputs / side effects:** opens the picker / the two modals.
- **Config / env:** n/a.
- **Edge cases / guards:** all three labels and the header note are hard-coded English (no i18n keys).
- **Rebuild notes:** A settings card that reads current values from one endpoint and writes through another.

### "Main model" row + `CHANGE`  `id: web-a.models.main-row`
- **Surface:** Web dashboard
- **Where:** First row of the Model Settings card. A `Star` icon, the label `Main model` (uppercased → `MAIN MODEL`), a mono line `<provider> · <model>` — each half replaced by the literal `(unset)` when empty, and the ` · ` separator only printed when both are non-empty (so a fresh install shows `(unset)(unset)`, exactly as the crawl captured). Right-hand filled button `Change` (→ `CHANGE`).
- **What it does:** Shows and changes the profile's default model.
- **How it works:** `ModelsPage.tsx:998-1024`; values come from `aux.main.provider` / `aux.main.model` (`GET /api/model/auxiliary` reads `config.yaml` `model.provider` and `model.default` falling back to `model.name`, `web_server.py:7612-7621`). `Change` sets `picker = {kind:"main"}` → `ModelPickerDialog` titled `Set Main Model` with `alwaysGlobal` and `loader={api.getModelOptions}` (`:1064-1085`). On apply it calls `applyAssignment({scope:"main", task:"", provider, model, confirmExpensiveModel})`; when the response is not `confirm_required` it sets `pendingReloadModel = model.split("/").slice(-1)[0]` (the short name), which opens the `ModelReloadConfirm` dialog.
- **Inputs / options:** the `CHANGE` button, then everything inside the picker (see `web-a.models.model-picker-dialog`).
- **Outputs / side effects:** `POST /api/model/set` writes `model.provider`, `model.default`, and — when the provider entry has one — `model.base_url` and `model.key_env`/`model.api_key`; then the reload prompt.
- **Config / env:** `model.provider`, `model.default`, `model.base_url`, `model.key_env`, `model.api_key`.
- **Edge cases / guards:** switching the main model never clears auxiliary pins; the response's `stale_aux[]` array reports aux slots still pinned to a different provider — **the Models page ignores it** (it is typed in `lib/api.ts:2508-2510` but never read here). Same for `gateway_tools` and `cron_model_impact`.
- **Rebuild notes:** Better: surface `stale_aux` as a "these helper tasks still use provider X — reset?" nudge, which is exactly what the backend comment says the field is for.

### "Auxiliary tasks" row + `CONFIGURE`  `id: web-a.models.aux-row`
- **Surface:** Web dashboard
- **Where:** Second row of the Model Settings card. `Cpu` icon, label `Auxiliary tasks` (→ `AUXILIARY TASKS`), a mono summary line, and an outlined `Configure` button (→ `CONFIGURE`).
- **What it does:** Summarises how many of the 11 auxiliary slots are overridden and opens the Auxiliary Tasks modal.
- **How it works:** `ModelsPage.tsx:1026-1052`. `auxOverrideCount = aux.tasks.filter(a => a.provider && a.provider !== "auto").length` (`:977-979`). Summary text (`:1038-1041`): when there is at least one override, `` `${n} override${n>1?"s":""} · ${11-n} auto` `` (e.g. `2 overrides · 9 auto`); otherwise `` `${AUX_TASKS.length} tasks · all auto` `` → `11 tasks · all auto` (matches the crawl).
- **Inputs / options:** the `CONFIGURE` button.
- **Outputs / side effects:** opens `AuxiliaryTasksModal`.
- **Config / env:** `auxiliary.<task>.provider` / `.model` / `.base_url`.
- **Edge cases / guards:** the count is derived client-side from the 11 slots the server always returns, so it never desyncs from the modal.
- **Rebuild notes:** Count-and-open row.

### "Mixture of Agents" row + `CONFIGURE`  `id: web-a.models.moa-row`
- **Surface:** Web dashboard
- **Where:** Third row of the Model Settings card. `Brain` icon, label `Mixture of Agents` (→ `MIXTURE OF AGENTS`), a mono summary, outlined `Configure` button.
- **What it does:** Summarises the MoA composition and opens the preset editor.
- **How it works:** `ModelsPage.tsx:1054-1080`. Summary (`:1066-1069`): when `moa` is loaded, `` `${n} reference${n===1?"":"s"} · ${aggregator.provider}/${shortModelName(aggregator.model)}` `` — e.g. the crawl's `2 references · openrouter/claude-opus-4.8` (note `shortModelName` strips the `anthropic/` vendor prefix from `anthropic/claude-opus-4.8`); when the GET failed, the literal `not loaded` and the button is `disabled`.
- **Inputs / options:** the `CONFIGURE` button (disabled while `moa` is null).
- **Outputs / side effects:** opens `MoaModelsModal`.
- **Config / env:** `moa.*` in `config.yaml`.
- **Edge cases / guards:** the summary reads the **top-level** `reference_models` / `aggregator` (the normalised active-preset projection), not the currently selected preset in the modal.
- **Rebuild notes:** Summary + modal.

### Totals card (Models page)  `id: web-a.models.totals`
- **Surface:** Web dashboard
- **Where:** Right card of the top row (rendered only once `data` has arrived). A `Stats` list with dotted leaders.
- **What it does:** Period headline numbers across all models.
- **How it works:** `ModelsPage.tsx:1249-1359`. Two different item lists depending on `showTokens` (`:1255-1338`). **With tokens:** `Models Used` (`i18n: models.modelsUsed`) = `totals.distinct_models`; `Total Tokens` (`i18n: analytics.totalTokens`) = `formatTokens(total_input + total_output)`; `Input` (`i18n: analytics.input`); `Output` (`i18n: analytics.output`); `Est. Cost` (`i18n: models.estimatedCost`) = `formatCost(total_estimated_cost)`; `Total Sessions` (`i18n: analytics.totalSessions`). **Without tokens:** only `Models Used` and `Total Sessions`. `formatCost` (`:73-78`): `≥1 → "$n.nn"`, `≥0.01 → "$n.nnn"`, `>0 → "$n.nnnn"`, else the literal `$0`. A wrapper div forces the `Stats` grid to `grid-cols-[auto_minmax(0,1fr)_auto]` so long values don't blow out the card (`:1252`).
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** `dashboard.show_token_analytics`.
- **Edge cases / guards:** same `null`-from-`SUM()` issue as Analytics — but it only bites in the `showTokens` branch, and the two always-shown fields (`distinct_models`, `total_sessions`) use `COUNT(...)`, which is never null.
- **Rebuild notes:** Two stat lists behind one flag.

### "Token & cost analytics are hidden…" note  `id: web-a.models.hidden-note`
- **Surface:** Web dashboard
- **Where:** Under the totals `Stats` list, shown when `dashboard.show_token_analytics` is false.
- **What it does:** Explains why the token and cost fields are missing and how to turn them on.
- **How it works:** `ModelsPage.tsx:1340-1350`. Verbatim: "Token & cost analytics are hidden because the local counts exclude auxiliary calls (compression, vision, web extract, …) and provider retries, so they diverge from your provider bill. Enable `dashboard.show_token_analytics` in Config to show the local debug estimate anyway." — with `dashboard.show_token_analytics` in mono and `Config` as `<a href="/config" class="underline">`.
- **Inputs / options:** the `Config` link (full page navigation).
- **Outputs / side effects:** none.
- **Config / env:** `dashboard.show_token_analytics`.
- **Edge cases / guards:** hard-coded English, distinct wording from the Analytics page's card — both must be found by a string checker.
- **Rebuild notes:** Same honesty gate as Analytics, shorter copy.

### Model card  `id: web-a.models.card`
- **Surface:** Web dashboard
- **Where:** One `Card` per entry in `data.models`, in a `md:grid-cols-2 xl:grid-cols-3` grid, ordered by total tokens descending (server-side). Header line: `#<rank>` in mono, the short model name, optional `main` chip, optional `aux · <task>` chip; second line: provider `Badge`, `<n>K ctx`, `<n>K out`; right side: a token or session count and the `Use as` button. Body: token bar, a 3-up stat row, a footer line, capability chips.
- **What it does:** Everything the dashboard knows about one model that was actually used, plus the controls to promote it.
- **How it works:** `ModelsPage.tsx:365-524` (`ModelCard`), keyed `` `${m.model}:${m.provider}` ``, `rank = i+1`. `provider = entry.provider || modelVendor(entry.model)` (`:80-92`: the substring before the first `/`). `isMain` compares provider **and** model against `aux.main`; `mainAuxTask` is the `task` of the first aux assignment whose provider+model match. When `isMain`, the card gets `ring-1 ring-primary/40`. Header right side: when `showTokens` it shows `formatTokens(input+output)` over the label `tokens` (`i18n: models.tokens`); otherwise, and only when `entry.sessions > 0`, it shows the session count over `sessions` (`i18n: models.sessions`). Context metadata uses `formatTokenCount` (`lib/format.ts:5-9` — same K/M scaling but drops a trailing `.0` for exact multiples), so a 200 000-token window renders `200K ctx`. Footer (`:495-509`): when `showTokens` and `estimated_cost > 0`, a `DollarSign` icon + `formatCost(...)`; when `showTokens` and `tool_calls > 0`, a `Zap` icon + `<n> tool calls` (`i18n: models.toolCalls`); right-aligned, when `last_used_at > 0`, `timeAgo(last_used_at)`.
- **Inputs / options:** the `Use as` menu (own entry). Nothing else on the card is clickable.
- **Outputs / side effects:** none by itself.
- **Config / env:** `dashboard.show_token_analytics` hides the token bar, the 3-up row, the cost and the tool-call chips.
- **Edge cases / guards:** with tokens hidden and `sessions === 0` (an aux-only model), the header's right column shows only the `Use as` button. The `main` chip only lights up when the provider string matches exactly — an entry whose `provider` came from `modelVendor()` rather than `billing_provider` will not match a config that stores an aggregator slug.
- **Rebuild notes:** One dense card per row of the analytics response. Better: click-through to that model's sessions, and a per-card "test this model" action.

### Model card — 3-up stat row  `id: web-a.models.card.stats`
- **Surface:** Web dashboard
- **Where:** Inside a model card, under the token bar; only when `showTokens`. Three centred columns.
- **What it does:** Sessions, average tokens per session, and API-call count for that model.
- **How it works:** `ModelsPage.tsx:472-494`. Column 1: `entry.sessions` over the label `sessions` (`i18n: models.sessions`). Column 2: `formatTokens(entry.avg_tokens_per_session)` over `avg/session` (`i18n: models.avgPerSession`). Column 3: `entry.api_calls > 0 ? formatTokens(entry.api_calls) : "—"` over `API calls` (`i18n: models.apiCalls`).
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** `avg_tokens_per_session` is a float from SQL `AVG()`, so `formatTokens` can print a long decimal for values under 1000.
- **Rebuild notes:** Round the average before formatting.

### Model card — token bar  `id: web-a.models.card.tokenbar`
- **Surface:** Web dashboard
- **Where:** Top of the model card body, when `showTokens`. A single stacked horizontal bar plus a dot legend under it.
- **What it does:** Shows the split of that model's tokens across cache-read, reasoning, input and output.
- **How it works:** `ModelsPage.tsx:94-160` (`TokenBar`). `total = input + output + cacheRead + reasoning`; returns `null` when total is 0. Four segments in fixed order, filtered to those with a value > 0: `Cache Read` (`#60a5fa`, Tailwind blue-400), `Reasoning` (`#c084fc`, purple-400), `Input` (`var(--series-input-token)`), `Output` (`var(--series-output-token)`). Each segment's width is `value/total*100%`, its background is `color-mix(in srgb, <color> 70%, transparent)`, and it carries a stepped overlay (`repeating-linear-gradient(to right, transparent 0 0.4rem, currentColor 0.4rem calc(0.4rem + 1px))` at 30 % opacity). The legend prints a 1.5×1.5 rounded dot in the solid colour followed by `` `${label} ${formatTokens(value)}` `` — e.g. `Input 1.2M`, `Output 340.5K`, `Cache Read 88K`, `Reasoning 12K`.
- **Inputs / options:** none (no hover tooltip here, unlike the Analytics chart).
- **Outputs / side effects:** none.
- **Config / env:** theme keys `inputTokenAccent` / `outputTokenAccent`; the cache-read and reasoning colours are hard-coded hex and do **not** follow the theme.
- **Edge cases / guards:** a segment worth <0.5 % of the total is still rendered but may round to sub-pixel width.
- **Rebuild notes:** Proportional flex segments. Better: theme the other two series too and add per-segment tooltips.

### Model card — capability chips  `id: web-a.models.card.capabilities`
- **Surface:** Web dashboard
- **Where:** Last line of a model card. Up to four chips: `Tools`, `Vision`, `Reasoning`, and the raw `model_family` string.
- **What it does:** Shows what the model can do, from the models.dev catalog.
- **How it works:** `ModelsPage.tsx:162-198` (`CapabilityBadges`), returns `null` when none of the four are set. `Tools` = green chip with a `Wrench` icon when `capabilities.supports_tools`; `Vision` = blue chip with `Eye` when `supports_vision`; `Reasoning` = purple chip with `Brain` when `supports_reasoning`; the fourth is a plain muted chip containing `capabilities.model_family` verbatim (e.g. `claude`, `gpt`). Capabilities are filled in server-side by `agent.models_dev.get_model_capabilities(provider, model)` (`web_server.py:16193-16209`), which also supplies `context_window` and `max_output_tokens` for the header line; a lookup failure is swallowed and yields `{}`.
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** the three labels are hard-coded English, not i18n; an unknown model shows no chips at all.
- **Rebuild notes:** Chip row driven by a capability lookup. Better: show pricing, knowledge cutoff and modality from the same catalog.

### `Use as` menu (per card)  `id: web-a.models.use-as-menu`
- **Surface:** Web dashboard
- **Where:** Top-right of every model card — a small outlined button reading `Use as` with a `ChevronDown`, opening a 220 px-wide dropdown anchored `right-0 top-full`.
- **What it does:** Assigns this card's model to the main slot or to any auxiliary task, without opening the picker.
- **How it works:** `ModelsPage.tsx:204-359` (`UseAsMenu`). Menu contents, in order: (1) a `Star`-prefixed item `Main model`, showing the word `current` in primary colour on the right when this card is the main model; (2) a non-clickable section header `Auxiliary task`; (3) an item `All auxiliary tasks` (assigns every slot at once, `task: ""`); (4) one item per entry of `AUX_TASKS` — `Vision`, `Compression`, `Skills Hub`, `Approval`, `MCP`, `Title Gen`, `Review`, `Triage Specifier`, `Kanban Decomposer`, `Profile Describer`, `Curator` — each showing `current` when `mainAuxTask` equals that key; (5) an error strip at the bottom when an assignment fails. `assign(scope, task, confirmExpensiveModel)` (`:228-264`) refuses with the local error `Missing provider/model` when either is empty, then calls `api.setModelAssignment({confirm_expensive_model, scope, provider, model, task})`; a `confirm_required` response opens the expensive-model dialog instead of closing the menu; success calls `onAssigned()` and closes. Outside-click closing is a `mousedown` listener that ignores anything inside `[data-use-as-menu]` (`:266-275`).
- **Inputs / options:** the toggle button (disabled while busy, shows a `Spinner` prefix), 13 menu items (1 main + 1 "all aux" + 11 tasks), and the confirm dialog's two buttons.
- **Outputs / side effects:** `POST /api/model/set`; on success the page refetches `/api/model/auxiliary` and bumps `refreshKey`. Assigning "main" from here does **not** offer the reload prompt (unlike the `CHANGE` button).
- **Config / env:** `model.*` / `auxiliary.<task>.*`.
- **Edge cases / guards:** `AUX_TASKS` (`ModelsPage.tsx:53-65`) carries the comment "Must match `_AUX_TASK_SLOTS` in hermes_cli/web_server.py" — the backend list is at `web_server.py:7403-7415` and an unknown slot returns `400 unknown auxiliary task: <slug>`. There is no Escape handler and no focus trap on this dropdown.
- **Rebuild notes:** Data-driven dropdown over a fixed task vocabulary shared with the server. Better: keep the two lists in one generated file, and offer the reload prompt here too.

### "Expensive Model Warning" dialog  `id: web-a.models.expensive-confirm`
- **Surface:** Web dashboard
- **Where:** Raised from the `Use as` menu and from inside `ModelPickerDialog`. Destructive `ConfirmDialog` with title `Expensive Model Warning`, the server's message as the description, buttons `Switch anyway` and `Cancel`.
- **What it does:** Makes the user acknowledge a model with unusually high known pricing before it is saved.
- **How it works:** `ModelsPage.tsx:343-358` and `ModelPickerDialog.tsx:473-488`. `POST /api/model/set` runs `hermes_cli.model_selection_guards.combined_selection_warning(model, provider=…, base_url=…)` **before** touching config when `confirm_expensive_model` is falsy (`web_server.py:7742-7762`), and on a hit returns `{ok:false, confirm_required:true, confirm_message:"…"}` without writing anything. The client stores the pending choice, and confirming re-issues the same request with `confirm_expensive_model: true`. Fallback description when the server sends none: `This model has unusually high known pricing.` (`ModelsPage.tsx:254-255`, `ModelPickerDialog.tsx:293-295` which also tries `result.warning` first).
- **Inputs / options:** `Switch anyway`, `Cancel`, `Escape`, backdrop click.
- **Outputs / side effects:** second POST that writes config, or nothing.
- **Config / env:** n/a.
- **Edge cases / guards:** the pricing lookup can hit models.dev, so it runs in a thread; any exception makes `warning = None` and the assignment proceeds unchallenged.
- **Rebuild notes:** Two-phase write with a server-computed veto — the important part is that phase one has no side effects.

### "Auxiliary Tasks" modal  `id: web-a.models.aux-modal`
- **Surface:** Web dashboard
- **Where:** Full-screen overlay opened by the second `CONFIGURE`. Header: `<h2>` `Auxiliary Tasks`, a `Reset all to auto` button, a close `X` (`aria-label="Close"`), and the explanatory paragraph. Body: 11 rows. Panel is `max-w-2xl max-h-[80vh]`.
- **What it does:** Per-task model overrides for the agent's 11 side-jobs.
- **How it works:** `ModelsPage.tsx:551-697` (`AuxiliaryTasksModal`). Header copy verbatim: "Auxiliary tasks handle side-jobs like vision, session search, and compression. `auto` means "use the main model". Override per-task when you want a cheap/fast model for a specific job." (the word `auto` is in mono, the inner quotes are `&quot;`). Each row (`:628-663`) shows `t.label` (bold) + `t.hint` (muted) on the first line and a mono status line that is either the literal `auto (use main model)` or `` `${provider} · ${model || "(provider default)"}` ``, with an outlined `Change` button on the right. A task counts as auto when there is no entry, `provider === "auto"`, or `provider` is empty (`:632-633`). `Change` opens a `ModelPickerDialog` titled `` `Set Auxiliary: ${label}` `` with `alwaysGlobal`, whose `onApply` posts `{scope:"auxiliary", task:<key>, provider, model, confirm_expensive_model}`. Modal behaviour comes from `useModalBehavior` (`hooks/useModalBehavior.ts:11-43`): Escape closes, `document.body.style.overflow` is locked to `hidden`, and focus is restored to the previously focused element on close; clicking the backdrop (target === currentTarget) also closes.
- **Inputs / options:** `Reset all to auto`, the close `X`, 11 × `Change`, Escape, backdrop click; plus everything inside the nested picker and the reset confirmation.
- **Outputs / side effects:** `POST /api/model/set` per change; `onSaved()` refetches the assignments.
- **Config / env:** `auxiliary.vision.*`, `auxiliary.compression.*`, `auxiliary.skills_hub.*`, `auxiliary.approval.*`, `auxiliary.mcp.*`, `auxiliary.title_generation.*`, `auxiliary.review.*`, `auxiliary.triage_specifier.*`, `auxiliary.kanban_decomposer.*`, `auxiliary.profile_describer.*`, `auxiliary.curator.*` (each with `provider`, `model`, optional `base_url` / `api_key`).
- **Edge cases / guards:** this modal is **not** portaled to `document.body` (unlike the picker and the MoA modal) — it renders inline with `z-[100]`; the nested `ModelPickerDialog` is portaled, so it still stacks correctly. Escape closes the aux modal even while the picker is open (there is no `shouldCloseOuterModalOnEscape` guard here, unlike the MoA modal).
- **Rebuild notes:** A table of named slots each pointing at "auto or an explicit (provider, model)". A better version would show what each task actually cost last period (the data is in `by_task`) and warn when a pin points at an unauthenticated provider.

### The 11 auxiliary task slots  `id: web-a.models.aux-tasks`
- **Surface:** Config
- **Where:** Rows of the Auxiliary Tasks modal and items of every `Use as` menu; defined in `ModelsPage.tsx:53-65` and mirrored server-side in `hermes_cli/web_server.py:7403-7415` (`_AUX_TASK_SLOTS`).
- **What it does:** Names the eleven side-jobs that can run on a different model from the main agent.
- **How it works:** Each entry is `{key, label, hint}`, listed here verbatim and in order: `vision` → `Vision` / "Image analysis"; `compression` → `Compression` / "Context compaction"; `skills_hub` → `Skills Hub` / "Skill search"; `approval` → `Approval` / "Smart auto-approve"; `mcp` → `MCP` / "MCP tool routing"; `title_generation` → `Title Gen` / "Session titles"; `review` → `Review` / "/review subagent"; `triage_specifier` → `Triage Specifier` / "Kanban spec fleshing"; `kanban_decomposer` → `Kanban Decomposer` / "Task decomposition"; `profile_describer` → `Profile Describer` / "Auto profile descriptions"; `curator` → `Curator` / "Skill-usage review".
- **Inputs / options:** n/a (data).
- **Outputs / side effects:** `GET /api/model/auxiliary` always returns exactly these 11 in this order, defaulting each to `{provider:"auto", model:"", base_url:""}` (live response in `hermes_inv/api_live/get_all.json`).
- **Config / env:** `auxiliary.<key>.provider|model|base_url|api_key`.
- **Edge cases / guards:** the labels/hints exist only in the web SPA — the server knows only the keys, so a new slot must be added in both places.
- **Rebuild notes:** Keep the slot vocabulary in one shared schema so the UI cannot drift from the resolver.

### "Reset auxiliary models" confirmation  `id: web-a.models.aux-reset`
- **Surface:** Web dashboard
- **Where:** Auxiliary Tasks modal header → `Reset all to auto` → destructive `ConfirmDialog` titled `Reset auxiliary models`, description `Reset every auxiliary task to 'auto'? This overrides any per-task overrides you've set.`, buttons `Reset all` and `Cancel`.
- **What it does:** Clears every per-task override so all side-jobs follow the main model again.
- **How it works:** `ModelsPage.tsx:565-580` + `:686-695`. Confirm → `api.setModelAssignment({scope:"auxiliary", task:"__reset__", provider:"", model:""})`. Server-side (`web_server.py:7943-7959`) it walks all 11 slots, sets `provider = "auto"` and `model = ""`, pops `base_url`, and calls `clear_model_endpoint_credentials(slot_cfg)` to drop any stored key, keeping every other field, then saves and returns `{ok:true, scope:"auxiliary", reset:true}`.
- **Inputs / options:** `Reset all`, `Cancel`, Escape, backdrop.
- **Outputs / side effects:** rewrites the whole `auxiliary:` block of `config.yaml`.
- **Edge cases / guards:** `__reset__` is the only `task` value that bypasses the "provider required for auxiliary" 400 check; while `resetBusy` the header button shows a `Spinner` and the confirm's label becomes `…`.
- **Rebuild notes:** A sentinel task value is a compact way to express "clear all" over the same endpoint; a dedicated DELETE would be cleaner.

### "Configure Mixture of Agents presets" modal  `id: web-a.models.moa-modal`
- **Surface:** Web dashboard
- **Where:** Portaled overlay opened by the third `CONFIGURE`. `<h2>` `Configure Mixture of Agents presets`, an intro paragraph, a preset toolbar, a `Reference models` list, an `Aggregator` row, an error line and the `Cancel` / `Save` footer. Panel `max-w-2xl max-h-[85vh]`.
- **What it does:** Edits the MoA virtual provider: named presets, each with a set of reference models that produce perspectives and one aggregator that actually answers and calls tools.
- **How it works:** `ModelsPage.tsx:698-926` (`MoaModelsModal`). It edits a local `draft` copy of the whole `MoaConfigResponse` and only writes on `Save` (`api.saveMoaModels(draft)` → `PUT /api/model/moa`), then hands the normalised result back through `onSaved(next)` and closes. `selected` starts at `config.default_preset` or the first preset key or the literal `"default"`. Intro copy verbatim: "Presets appear as models under the Mixture of Agents provider. References produce perspectives; the aggregator is the acting model that answers and calls tools." Slot labels use `slotLabel(slot) = `${slot.provider || "(provider)"} · ${slot.model || "(model)"}``. Rendered through `createPortal(..., document.body)` with `DASHBOARD_MODAL_BACKDROP` / `DASHBOARD_MODAL_PANEL` (`lib/dashboard-modal-shell.ts:15-19`) because the dashboard column's `relative z-2` would otherwise trap a `z-[100]` fixed child under the sidebar.
- **Inputs / options:** the preset `<select>`; `Set default`; `Delete`; the `new preset name` text input; `Add preset`; per-reference `Switch` toggle, `Change`, `Remove`; `Add reference model`; aggregator `Change`; `Cancel`; `Save`. All enumerated in the entries below.
- **Outputs / side effects:** `PUT /api/model/moa` merges the normalised config into `config.yaml`'s `moa:` block (`web_server.py:7645-7717`).
- **Config / env:** `moa.default_preset`, `moa.active_preset`, `moa.presets.<name>.{reference_models,aggregator,reference_temperature,aggregator_temperature,reference_timeout,degraded_reference_policy,max_tokens,reference_max_tokens,fanout,enabled}`.
- **Edge cases / guards:** Escape is routed through `shouldCloseOuterModalOnEscape(picker !== null)` (`lib/dashboard-modal-shell.ts:25-28`) so the nested model picker owns the key while it is open; the backdrop uses `onMouseDown` (not `onClick`) so a drag that ends on the backdrop does not close the modal. `if (!preset) return null` bails when the selected preset vanished. The modal edits only a subset of the schema — `reference_temperature`, `aggregator_temperature`, `reference_timeout`, `degraded_reference_policy`, `max_tokens`, `reference_max_tokens` and `fanout` are round-tripped untouched (documented in `lib/api.ts:2445,2461-2464`).
- **Rebuild notes:** Draft-then-save modal over a nested config object. A better version would expose the temperature/timeout/fanout fields it currently only round-trips, and validate before enabling `Save`.

### MoA preset toolbar  `id: web-a.models.moa-presets`
- **Surface:** Web dashboard
- **Where:** First row inside the MoA modal: a `<select>` of preset names, then `Set default`, `Delete`, a text input placeholder `new preset name`, and `Add preset`. Below it a line reading `Default: <name>` with the name in mono.
- **What it does:** Creates, selects, renames-by-copy, deletes and defaults the MoA presets.
- **How it works:** `ModelsPage.tsx:823-846`. `<select>` sets `selected`. `Set default` sets `draft.default_preset = selected` (local only until Save). `Delete` (`deletePreset`, `:783-801`) is disabled when only one preset exists; it removes the key, moves `default_preset` to the first remaining preset if it pointed at the deleted one, and clears `active_preset` if it did. `Add preset` (`addPreset`, `:760-781`) is disabled while the trimmed name is empty or already taken; it seeds the new preset from the currently selected one (or from the top-level fields when none exists), copies `reference_models` by value, sets `default_preset` if it was empty, selects the new preset and clears the input.
- **Inputs / options:** the `<select>` (one `<option>` per preset name), `Set default`, `Delete`, the `new preset name` input, `Add preset`.
- **Outputs / side effects:** local draft only until `Save`.
- **Config / env:** `moa.presets`, `moa.default_preset`, `moa.active_preset`.
- **Edge cases / guards:** presets appear as *models* under the `moa` provider in the picker — the live `/api/model/options` shows the provider `moa` / "Mixture of Agents" with `models: ["default"]` and the warning "Aggregator acts as the selected model; references provide analysis before each call."
- **Rebuild notes:** Named-preset CRUD on a client-side draft; there is no rename (delete + add is the workaround).

### MoA reference-model rows  `id: web-a.models.moa-references`
- **Surface:** Web dashboard
- **Where:** Section headed `Reference models` inside the MoA modal. One bordered row per slot: a `Switch`, the mono `provider · model` label, a `Change` button and a `Remove` button. Below the list, an `Add reference model` button.
- **What it does:** Chooses which models contribute perspectives before each aggregator call, and which of them are active.
- **How it works:** `ModelsPage.tsx:852-878`. The `Switch` writes `slot.enabled = checked === true`; a disabled slot renders at `opacity-60`. `Change` opens the nested picker for `{kind:"reference", index}`. `Remove` is disabled when only one reference remains and filters that index out. `Add reference model` appends a copy of the current **aggregator** slot with `enabled: true` — so a new reference starts out identical to the aggregator and must be changed. Row keys embed provider+model+index so duplicates don't collide.
- **Inputs / options:** per row: 1 toggle, `Change`, `Remove`; plus `Add reference model`.
- **Outputs / side effects:** local draft.
- **Config / env:** `moa.presets.<name>.reference_models[]` (`{provider, model, enabled?, reasoning_effort?}`).
- **Edge cases / guards:** the picker rejects the `moa` provider itself with the inline error `MoA presets can't reference or aggregate the Mixture of Agents provider (no recursive MoA).` (`:909-911`).
- **Rebuild notes:** List-of-slots editor with add/remove/toggle. Better: drag to reorder and a per-slot reasoning-effort control (the field already round-trips).

### MoA aggregator row  `id: web-a.models.moa-aggregator`
- **Surface:** Web dashboard
- **Where:** Section headed `Aggregator` inside the MoA modal: one row with the mono `provider · model` label and a `Change` button.
- **What it does:** Picks the model that actually answers the user and calls tools, using the references' perspectives as input.
- **How it works:** `ModelsPage.tsx:880-887`; `Change` opens the nested picker for `{kind:"aggregator"}`, whose apply sets `preset.aggregator = {provider, model}` in the draft.
- **Inputs / options:** the `Change` button.
- **Outputs / side effects:** local draft.
- **Config / env:** `moa.presets.<name>.aggregator`.
- **Edge cases / guards:** same no-recursive-MoA rejection as references; the aggregator has no enable toggle (it is always required).
- **Rebuild notes:** Single-slot editor.

### MoA nested model picker  `id: web-a.models.moa-picker`
- **Surface:** Web dashboard
- **Where:** `ModelPickerDialog` titled `Select MoA Model`, raised from either a reference row's or the aggregator's `Change`.
- **What it does:** Chooses a provider+model for one MoA slot.
- **How it works:** `ModelsPage.tsx:902-923`. `loader={api.getModelOptions}`, `alwaysGlobal`. Its `key` includes `refreshKey`, the selected preset, the slot kind and the reference index so switching slots remounts a fresh picker. `onApply` writes straight into the draft (no network call) — unless the chosen provider is `moa` (case-insensitive), in which case it sets the modal's `error` and leaves the draft alone.
- **Inputs / options:** the picker's own controls (see `web-a.models.model-picker-dialog`).
- **Outputs / side effects:** local draft only; nothing is persisted until the MoA modal's `Save`.
- **Config / env:** n/a.
- **Edge cases / guards:** because `onApply` returns `void` (never a `confirm_required` object), the expensive-model warning does **not** fire for MoA slots — the check happens only on `POST /api/model/set`.
- **Rebuild notes:** Reusing the picker in "pure selection" mode by giving it a no-op `onApply` is the cheapest way to get one picker for both writes and drafts.

### MoA `Save` / `Cancel`  `id: web-a.models.moa-save`
- **Surface:** Web dashboard
- **Where:** Footer of the MoA modal, right-aligned: ghost `Cancel`, filled `Save` (label becomes `Saving…` while busy). Above them, a red one-line error when a save or a picker rejection occurred.
- **What it does:** Persists or discards the whole draft.
- **How it works:** `ModelsPage.tsx:889-899`; `save()` (`:745-758`) calls `api.saveMoaModels(draft)` → `PUT /api/model/moa`, then `onSaved(saved)` (which replaces the panel's `moa` state and calls the page's `onAssigned`) and `onClose()`. Errors are caught into the local `error` string.
- **Inputs / options:** `Cancel` (disabled while busy), `Save` (disabled while busy).
- **Outputs / side effects:** `PUT /api/model/moa`.
- **Config / env:** n/a.
- **Edge cases / guards:** a 422 from the server's `validate_moa_payload` surfaces verbatim as `Error: 422: Invalid MoA config: <problems>`.
- **Rebuild notes:** Draft/commit with an inline error line.

### `ModelPickerDialog` (shared two-stage model picker)  `id: web-a.models.model-picker-dialog`
- **Surface:** Web dashboard
- **Where:** `components/ModelPickerDialog.tsx` — used by the Models page (`Set Main Model`, `Set Auxiliary: <label>`, `Select MoA Model`), the chat sidebar (`Switch Model`, entry `web-a.chat.sidebar-model-picker`), the Config page and the profile builder. A portaled `role="dialog" aria-modal="true"` overlay, panel `max-w-3xl max-h-[80vh]`, two columns (`200px` providers | models).
- **What it does:** Pick a provider, then a model, then apply the choice — either by writing config (standalone mode) or by emitting a `/model` slash command (chat mode).
- **How it works:** Two invocation modes documented at `ModelPickerDialog.tsx:17-35`. **Standalone** (`loader` + `onApply` present, which is how every Models-page use works): options come from `GET /api/model/options?include_unconfigured=1[&profile=][&refresh=1]`, and `onApply({confirmExpensiveModel, provider, model, persistGlobal})` does the write. **Chat** (`gw` + `sessionId`): options come from the `model.options` JSON-RPC and the apply goes through `config.set` with value `` `${model} --provider ${slug}${global}` ``; a third fallback emits `` `/model ${model} --provider ${slug}${global}` `` through `onSubmit`. Anatomy top-to-bottom: a close `X` button (`aria-label="Close"`) pinned top-right; a header with the `title` (default `Switch Model`) and a mono subline `current: <model> · <provider slug>` (or `current: (unknown)` when the response has no model); a search `Input` (`autoFocus`, placeholder `Filter providers and models…`, with a `Search` icon); the provider column; the model column; a footer.
- **Inputs / options:** the filter input; provider rows (click to select); model rows (single click selects, **double click** applies immediately); the footer's `Persist globally (otherwise this session only)` checkbox (`id="model-picker-persist-global"`, hidden when `alwaysGlobal` — the Models page always passes `alwaysGlobal`, so it instead shows the static text `Saves to config.yaml — applies to new sessions.`); `Refresh Models` (outlined, with a `RefreshCw` icon or `Spinner`); `Cancel`; `Switch` (the confirm button, shows a `Spinner` while applying). Keyboard: `Escape` closes (a window-level `keydown` listener, `:195-204`); clicking the backdrop closes; there are no arrow-key list shortcuts.
- **Outputs / side effects:** whatever `onApply` does; `Refresh Models` re-requests with `refresh=1`, which busts the per-provider model-id disk cache so every row re-fetches its live catalog (normal opens stay on the 1 h cache — `web_server.py:7467-7470`).
- **Config / env:** `GET /api/model/options` params `profile`, `refresh`, `include_unconfigured`, `explicit_only`.
- **Edge cases / guards:** `closedRef` suppresses state updates after unmount. A `503 Restart required: …` is returned when the dashboard process is running stale code (`_dashboard_code_skew_guard`). The dialog opens with the current provider preselected (`is_current`, else the first row) and no model selected, so `Switch` starts disabled (`canConfirm = !!selectedProvider && !!selectedModel && !applying`).
- **Rebuild notes:** Two-column picker + one options endpoint whose shape matches the TUI's JSON-RPC 1:1 — that shape-sharing is what lets the same component serve four surfaces. A better version would add keyboard navigation, remember the last provider, and show price/context per model row.

### Model picker — provider column  `id: web-a.models.picker-providers`
- **Surface:** Web dashboard
- **Where:** Left 200 px column of `ModelPickerDialog`. One `ListItem` per provider: the display name (bold, truncated) with a `current` tag when it is the active provider, and a mono subline `<slug> · <n> models`.
- **What it does:** Stage 1 of the picker.
- **How it works:** `ModelPickerDialog.tsx:498-560`. The list is fuzzy-ranked over `` `${name} ${slug} ${models.join(" ")}` `` so typing a *model* name surfaces its provider (`:226-236`); with an empty query, providers that have models are floated above those with none (a fresh install lists ~40 providers of which only a couple are configured). Selecting a provider clears the selected model. The active row gets `border-l-primary`.
- **Inputs / options:** click a row.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** three literal states — `loading…` (with a spinner) while the request is in flight, the error string in red, and, when the ranked list is empty, `no matches` if a query is typed, `no authenticated providers` when there are genuinely zero providers, else `no matches` (`:525-533`). `total_models` is preferred over `models.length` for the count, so a provider can advertise more models than it lists.
- **Rebuild notes:** Rank providers by their models too — that one detail is what makes a single search box work across both columns.

### Model picker — model column  `id: web-a.models.picker-models`
- **Surface:** Web dashboard
- **Where:** Right column. One `ListItem` per model id, mono, with a `Check` icon (transparent unless selected) and a `current` tag on the active model.
- **What it does:** Stage 2 of the picker.
- **How it works:** `ModelPickerDialog.tsx:566-636`. Models are fuzzy-ranked with `modelSearchText` as the haystack, which appends search-only aliases for brand-less wire ids (`lib/model-search-text.ts:11-16`: `k3` → also matches "kimi-k3"/"kimi"; `x-preview-f-free` → also "ox-alpha"/"ox") without changing the id that is sent. Matched characters are underlined in primary colour by `HighlightedText` (`:651-679`), with alias-range positions filtered out. When the query matched the selected provider by *name/slug only* and none of its models, the model list falls back to unfiltered (`queryMatchesProviderOnly`, `lib/model-picker-filter.ts:10-23`) — so typing "aws" to find "AWS Build" does not empty its Claude model list.
- **Inputs / options:** single click selects; **double click** selects *and* applies immediately (`onDoubleClick={() => onConfirm(m)}`, `:620`).
- **Outputs / side effects:** none until applied.
- **Config / env:** n/a.
- **Edge cases / guards:** with no provider chosen the column reads `pick a provider →`; with a provider chosen the empty text is `no models match your filter` when the provider has models but none match, otherwise `no models listed for this provider`. A provider-level `warning` string (e.g. missing credentials) renders as a red strip above the list.
- **Rebuild notes:** Fuzzy subsequence ranking with highlight positions (`lib/fuzzy.ts` — scores exact > prefix > word-boundary > contiguous > early, and is a deliberate copy of `ui-tui/src/lib/fuzzy.ts`).

### `ConfirmDialog` (dashboard-wide confirm primitive)  `id: web-a.shared.confirm-dialog`
- **Surface:** Web dashboard
- **Where:** `components/ConfirmDialog.tsx` — the Models page's expensive-model, aux-reset and model-reload dialogs, plus many other pages. Portaled to `document.body` at `z-[200]` (above the `z-[100]` modal band), panel `max-w-md`.
- **What it does:** A modal yes/no with an optional destructive treatment.
- **How it works:** `ConfirmDialog.tsx:19-122`. Props: `open`, `title`, `description?`, `destructive=false`, `loading=false`, `confirmLabel="Confirm"`, `cancelLabel="Cancel"`, `onConfirm`, `onCancel`. On open it focuses the button carrying `[data-confirm]`, installs a document-level `Escape` → `onCancel` handler, sets `document.body.style.overflow = "hidden"`, and on close restores both the overflow and the previously focused element. Backdrop click (target === currentTarget) cancels. `destructive` adds an `AlertTriangle` glyph and makes the confirm button destructive. The description renders `whitespace-pre-line`, so server messages keep their line breaks. While `loading`, both buttons are disabled and the confirm label becomes `…`.
- **Inputs / options:** confirm button, cancel button, `Escape`, backdrop click.
- **Outputs / side effects:** none of its own.
- **Config / env:** n/a.
- **Edge cases / guards:** distinct from `@nous-research/ui`'s Radix-based `ConfirmDialog` that `components/DeleteConfirmDialog.tsx` wraps — the dashboard has two confirm primitives with the same name; this one is hand-rolled and its labels default to English literals rather than i18n keys.
- **Rebuild notes:** ~100 lines: portal, focus management, scroll lock, Escape. Better: consolidate the two implementations and give the hand-rolled one a focus trap.

### `GET /api/analytics/models`  `id: web-a.models.api.analytics`
- **Surface:** API
- **Where:** `hermes_cli/web_server.py:16070` (route) → `_get_models_analytics` (`:15894-16068`); client `api.getModelsAnalytics(days, profile)` (`lib/api.ts:518-521`).
- **What it does:** Rich per-model breakdown for the card grid, including models.dev capability metadata.
- **How it works:** Read-only profile DB. One `GROUP BY model, billing_provider` over `sessions` where `started_at > cutoff AND model IS NOT NULL AND model != ''`, summing `input_tokens, output_tokens, cache_read_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd`, plus `COUNT(*) sessions`, `SUM(api_call_count)`, `SUM(tool_call_count)`, `MAX(started_at) last_used_at`, `AVG(input+output) avg_tokens_per_session`. Auxiliary rows from `_aux_usage_rows` are appended as their own `(model, provider)` rows carrying an extra `aux_task` field so aux-only models appear (issue #23270). A de-duplication pass (`:16041-16062` region) folds a *usage-free* session-only row into the single accounted provider row for the same model — the fix for the "duplicate 0 tokens / — API calls card" bug — recomputing `sessions`, `last_used_at` and `avg_tokens_per_session`. Rows are re-sorted by input+output desc. For each row `agent.models_dev.get_model_capabilities(provider, model)` supplies `{supports_tools, supports_vision, supports_reasoning, context_window, max_output_tokens, model_family}` (`{}` on any failure). A final query builds `totals` including `COUNT(DISTINCT model) AS distinct_models`.
- **Inputs / options:** query `days` (default 30 — note: **not** clamped here, unlike `/api/analytics/usage`), `profile`.
- **Outputs / side effects:** `{models:[…], totals:{distinct_models,total_input,total_output,total_cache_read,total_reasoning,total_estimated_cost,total_actual_cost,total_sessions,total_api_calls}, period_days}`. Read-only.
- **Config / env:** the profile's `sessions.db`.
- **Edge cases / guards:** `aux_task` is returned on aux rows but the SPA's `ModelsAnalyticsModelEntry` type does not declare it and no card shows it. Empty-DB totals carry `null` token sums (live response recorded in `hermes_inv/api_live/get_all.json`).
- **Rebuild notes:** Better: clamp `days` like the sibling route, and expose `aux_task` on the card so a compression-only model reads as such.

### `GET /api/model/auxiliary`  `id: web-a.models.api.auxiliary`
- **Surface:** API
- **Where:** `web_server.py:7578-7626`; client `api.getAuxiliaryModels(profile)` (`lib/api.ts:548-551`).
- **What it does:** Returns the current auxiliary pins plus the main model, from `config.yaml`.
- **How it works:** Reads the config inside `_profile_scope(profile)` so the Models page reads the same profile `/api/model/set` writes; emits exactly one entry per `_AUX_TASK_SLOTS` member, defaulting `provider` to `"auto"` and `model`/`base_url` to `""`; `main` is `{provider: model.provider, model: model.default ?? model.name}`, or `{provider:"", model:str(model_cfg)}` when `model:` is a bare scalar.
- **Inputs / options:** query `profile`.
- **Outputs / side effects:** `{tasks:[11], main:{provider,model}}`. Read-only.
- **Config / env:** `auxiliary.*`, `model.provider`, `model.default`, `model.name`.
- **Edge cases / guards:** any exception → `500 Failed to read auxiliary config`; the page's `load()` catches this to `null` so the usage cards still render.
- **Rebuild notes:** Always return every slot, defaulted — the UI then needs no "missing key" branch.

### `POST /api/model/set`  `id: web-a.models.api.model-set`
- **Surface:** API
- **Where:** `web_server.py:7719-7776` (async wrapper) → `_apply_model_assignment_sync` (`:7780-8003`); client `api.setModelAssignment(body, profile)` (`lib/api.ts:559-571`).
- **What it does:** The single write endpoint behind every model assignment in the dashboard: main slot, one aux slot, all aux slots, or reset-all.
- **How it works:** Validates `scope ∈ {main, auxiliary}` (else `400 scope must be 'main' or 'auxiliary'`). Phase 1 (no side effects): unless `confirm_expensive_model`, `combined_selection_warning(model, provider, base_url)` runs in a thread and, on a hit, returns `{ok:false, confirm_required:true, confirm_message}` **without writing**. Phase 2 runs `_apply_model_assignment_sync` in a thread inside `_profile_scope(body.profile or profile)` — the comment at `:7737-7740` notes the profile lock must never be held across an `await`. **scope=main:** requires provider and model (`400 provider and model required for main`); `_normalize_main_model_assignment` canonicalises the pair; a `providers.<slug>.base_url` fills an empty `base_url`; credential handling carries a *pointer* (`model.key_env` from the raw config) rather than a resolved secret, and only falls back to `model.api_key` when the raw yaml itself stores a literal — issue #88990; switching to the `nous` provider additionally runs `apply_nous_managed_defaults` to route unconfigured tools through the Nous Tool Gateway (purely additive, reported back as `gateway_tools`); a `custom`/`local` provider with a `base_url` also registers a named `custom_providers` entry (dedup by base_url). It then computes `stale_aux[]` (aux slots pinned to a provider other than the new main) and `cron_model_impact`. **scope=auxiliary:** `task="__reset__"` resets all 11 slots; otherwise `provider` is required (`400 provider required for auxiliary`), `targets = [task]` or all 11 when `task` is empty, an unknown slot yields `400 unknown auxiliary task: <slug>`, each slot gets `provider`/`model`, keeps `base_url`+`api_key` when a `base_url` was supplied, and otherwise drops the endpoint credentials when the provider actually changed and is not `custom`.
- **Inputs / options:** JSON body `ModelAssignment`: `scope` ("main"|"auxiliary"), `provider`, `model`, `task` (aux slot / `""` for all / `"__reset__"`), `base_url?`, `api_key?`, `confirm_expensive_model?`, `profile?`; plus the query param `profile`.
- **Outputs / side effects:** rewrites `~/.hermes/config.yaml`. Main returns `{ok:true, scope:"main", provider, model, base_url, gateway_tools[], stale_aux[], cron_model_impact}`; aux returns `{ok:true, scope:"auxiliary", tasks:[…], provider, model}`; reset returns `{ok:true, scope:"auxiliary", reset:true}`.
- **Config / env:** `model.*`, `auxiliary.*`, `providers.*`, `custom_providers.*`.
- **Edge cases / guards:** the docstring is explicit that this applies to **new** sessions only — a running chat PTY keeps its model until it is rebuilt, which is why the UI offers a page reload. Any unexpected exception → `500 Failed to save model assignment`.
- **Rebuild notes:** One endpoint, four write shapes, a no-side-effect confirmation phase, and credentials stored as pointers. Better: return the resulting effective config so the client need not refetch.

### `GET /api/model/options`  `id: web-a.models.api.options`
- **Surface:** API
- **Where:** `web_server.py:7449-7498`; client `api.getModelOptions(profileOrOptions)` (`lib/api.ts:528-547`).
- **What it does:** Feeds the picker: every provider plus its curated model list, auth state and setup warnings. The response shape matches the TUI's `model.options` JSON-RPC 1:1.
- **How it works:** `_dashboard_code_skew_guard()` first (503 `Restart required: …` when the process is running stale code after an update), then `build_model_options_payload(load_picker_context(), explicit_only, include_unconfigured, refresh)` from `hermes_cli.inventory`, run via `run_in_threadpool` inside `_profile_scope(profile)`.
- **Inputs / options:** query `profile`, `refresh` (bool — busts the per-provider model-id disk cache; the picker's `Refresh Models` sets it, normal opens stay on the 1 h cache), `include_unconfigured` (bool — the dashboard client always sets `1` so the full provider universe with setup affordances is returned; the backend defaults to the configured subset for desktop chat pickers, #56974), `explicit_only` (bool). The web client always appends `include_unconfigured=1` and only adds `profile`/`refresh=1` when supplied.
- **Outputs / side effects:** `{model, provider, providers:[{slug, name, is_current, is_user_defined, models[], total_models, source, authenticated, auth_type?, warning?, capabilities{model:{fast,reasoning}}, featured_models[]}]}` — see the live sample in `hermes_inv/api_live/get_all.json` (e.g. the virtual `moa` provider and `copilot` with 17 models). Read-only apart from cache writes on `refresh`.
- **Config / env:** provider auth from the profile's `.env` and `providers:` / `custom_providers:` config.
- **Edge cases / guards:** any other exception → `500 Failed to list model options`.
- **Rebuild notes:** One payload builder shared by REST and JSON-RPC so the TUI and web pickers can never disagree.

### `GET /api/model/moa` and `PUT /api/model/moa`  `id: web-a.models.api.moa`
- **Surface:** API
- **Where:** `web_server.py:7629-7643` (GET) and `:7645-7717` (PUT); clients `api.getMoaModels()` / `api.saveMoaModels(body)` (`lib/api.ts:552-558`).
- **What it does:** Reads and writes the Mixture-of-Agents preset configuration.
- **How it works:** GET returns `normalize_moa_config(cfg["moa"])` — a normalised object carrying both the named `presets` map and a flattened top-level projection of the active/default preset (`reference_models`, `aggregator`, temperatures, `reference_timeout`, `degraded_reference_policy`, `max_tokens`, `reference_max_tokens`, `fanout`, `enabled`, `privacy_filter`). PUT builds `raw` from `body.presets` (or synthesises a single preset from the flat fields), drops unset optional slot keys so saved slots stay minimal (`{provider, model}`), then runs `validate_moa_payload(raw)` and **rejects** with `422 Invalid MoA config: <problems>` rather than repairing — the comment at `:7702-7709` explains that `normalize_moa_config` silently swaps an incomplete preset for hardcoded defaults, which is right at read time but silent data loss at write time (#64156, desktop autosave of a half-filled slot). The normalised result is merged with `cfg.setdefault("moa", {}).update(normalized)` so hand-edited keys not declared in the payload model (e.g. `save_traces`, `trace_dir`) survive a GUI save (#58819).
- **Inputs / options:** GET query `profile`; PUT body `MoaConfigPayload` (`default_preset`, `active_preset`, `presets{}`, plus the flat fallback fields and an optional `profile`), query `profile`.
- **Outputs / side effects:** PUT writes `config.yaml`'s `moa:` block and returns `{ok:true, ...normalized}`.
- **Config / env:** `moa.*`.
- **Edge cases / guards:** the SPA never passes a profile to either call, so from the dashboard MoA always targets the dashboard process's own profile even when the header profile switcher points elsewhere — a real read/write asymmetry the other model routes were explicitly fixed for. Errors → `500 Failed to read MoA config` / `500 Failed to save MoA config`.
- **Rebuild notes:** Reject-don't-repair on write, tolerate-and-normalise on read — a good rule for any hand-editable config with a GUI.

### Loading, error and empty states (Models page)  `id: web-a.models.states`
- **Surface:** Web dashboard
- **Where:** Below the top row.
- **What it does:** Covers the three non-happy states.
- **How it works:** (1) **Loading** — `loading && !data`: a centred `Spinner className="text-2xl text-primary"` in a `py-24` block (`ModelsPage.tsx:1362-1366` region / `:1313-1317` in the render order). (2) **Error** — a card with the stringified exception in `text-sm text-destructive text-center`. (3) **Empty** — when `data.models.length === 0`: a card with a 40 %-opacity `Cpu` icon, the line `No model usage data for this period` (`i18n: models.noModelsData`) and the sub-line `Start a session to see model data here` (`i18n: models.startSession`) — exactly what the crawl captured.
- **Inputs / options:** none.
- **Outputs / side effects:** none.
- **Config / env:** n/a.
- **Edge cases / guards:** the Model Settings card and the totals card still render above the empty state, so the page is never blank; the error card does not hide the settings panel either, which means model assignment still works when the analytics query fails.
- **Rebuild notes:** Keep the control surface alive when the data surface fails — that separation is the useful bit.

### Assignment refresh on window focus  `id: web-a.models.focus-refresh`
- **Surface:** Web dashboard
- **Where:** Invisible; fires when the browser tab regains focus or becomes visible.
- **What it does:** Re-reads the model assignments so the page reflects changes made from the chat's `/model --global`, the Config page or the CLI.
- **How it works:** `ModelsPage.tsx:1220-1238`. Listeners on `window.focus` and `document.visibilitychange`; the handler returns early unless `document.visibilityState === "visible"` and throttles to at most one call per 1000 ms via a closure variable; it calls `refreshAux()` (`GET /api/model/auxiliary`, errors swallowed).
- **Inputs / options:** n/a.
- **Outputs / side effects:** one GET.
- **Config / env:** n/a.
- **Edge cases / guards:** analytics are deliberately **not** refetched (they are expensive and change slowly); the MoA config is also not refetched (it only reloads when `refreshKey` changes).
- **Rebuild notes:** Focus-refetch for state a sibling surface can mutate. Better: a server-sent event on config change so every open surface updates immediately.

### Plugin slots on the Models page  `id: web-a.models.plugin-slots`
- **Surface:** Web dashboard
- **Where:** `<PluginSlot name="models:top"/>` (`ModelsPage.tsx:1241`) and `<PluginSlot name="models:bottom"/>` (`:1356`).
- **What it does:** Injection points above and below the page content.
- **How it works:** Plugin slot registry (plugins shard).
- **Inputs / options:** n/a. **Outputs / side effects:** n/a. **Config / env:** n/a. **Edge cases / guards:** n/a.
- **Rebuild notes:** Named slots.

---

## F. Catalogued strings with no rendering site on these pages

### Orphan i18n strings in the `analytics` catalog  `id: web-a.analytics.orphan-strings`
- **Surface:** Web dashboard
- **Where:** `web/src/i18n/en.ts:204` `period: "Period:"`, `:225` `acrossModels: "across {count} models"`, `:226` `inOut: "{input} in / {output} out"` — translated in every locale (`de.ts:200-201`, `es.ts:200-201`, `ga.ts:200-201`, `zh.ts:198-199`, and the `period` key alongside them).
- **What it does:** Nothing at v2026.8.31 — no component in `web/src` reads `t.analytics.period`, `t.analytics.acrossModels` or `t.analytics.inOut`.
- **How it works:** Verified by grepping every `.ts`/`.tsx` under `web/src` outside `i18n/`: the only hits are the catalog definitions themselves. `Period:` is the label the period selector used before it was moved into the page header and reduced to three unlabelled buttons (`AnalyticsPage.tsx:441-444` documents that the redundant period badge was removed); `across {count} models` and `{input} in / {output} out` are the interpolated sublines of a stat layout that the current `Stats` component does not render.
- **Inputs / options:** n/a.
- **Outputs / side effects:** none — they are shipped in the bundle but never displayed.
- **Config / env:** n/a.
- **Edge cases / guards:** listed here so a mechanical string checker over the i18n catalogs finds a home for every key rather than reporting three unexplained misses.
- **Rebuild notes:** Delete them, or restore the labelled period control and the compact per-model subline they were written for.

## Handoffs

- `/api/fs/list`, `/api/fs/preview`, `/api/fs/read-text`, `/api/fs/write-text` and the `_FS_*` size caps (`web_server.py:2317-2400`, `:3200+`) — a second, richer filesystem API with previews and a spot editor, used by the desktop app's file explorer, not by the dashboard Files page.
- `GET /api/files/download`'s `?token=` query-auth path and `_QUERY_TOKEN_API_PATHS` (`web_server.py:725`) — dashboard auth shard.
- `GET /api/model/info` and `GET /api/model/recommended-default` (`web_server.py:7313`, `:7501`) — consumed by the chat sidebar badge and by GUI onboarding, not by these five pages.
- `cron_model_impact` / `resolve_cron_model_drift_defaults` / `build_cron_model_impact` returned by `POST /api/model/set` — Cron page shard.
- `gateway_tools` and `apply_nous_managed_defaults` (Nous Tool Gateway auto-routing on a main-provider switch to `nous`) — providers/tools shard.
- `hermes_cli/moa_config.py` `normalize_moa_config` / `validate_moa_payload` and the full MoA runtime (fan-out cadence, degraded-reference policy, trace saving) — MoA/core shard.
- `hermes_cli/inventory.build_model_options_payload` / `load_picker_context` and the provider-catalog/auth model behind `/api/model/options` — providers shard.
- `agent.insights.InsightsEngine.get_usage_breakdown` (source of `skills` and `tools` in `/api/analytics/usage`) — core insights shard.
- `agent.models_dev.get_model_capabilities` and the models.dev catalog — core shard.
- The `tools[]` array in `/api/analytics/usage`, aggregated per toolset by the desktop "Capabilities" page — desktop shard.
- `dashboard.show_token_analytics` as a **Config-page field** (label, category, description from `/api/config/schema`) — config shard; this shard documents only its effect on `/analytics` and `/models`.
- The sidebar filtering that hides the `ANALYTICS` nav item when `dashboard.show_token_analytics` is false (`App.tsx:412-466`) — app-shell shard.
- `@nous-research/ui` primitives themselves (`Button`, `Card`, `Badge`, `Switch`, `Stats`, `ListItem`, `Checkbox`, `Input`, `Label`, `Spinner`, `Toast`, `Dialog`, `confirm-dialog`) — design-system shard.
- `PluginSlot` and the dashboard-plugin registry backing `files:top`/`files:bottom`, `analytics:top`/`analytics:bottom`, `models:top`/`models:bottom` — plugins shard.
- `lib/fuzzy.ts` and its authoritative twin `ui-tui/src/lib/fuzzy.ts` (plus `hermes_cli/model_search.py`) — the ranking algorithm is shared with the TUI picker; TUI shard owns the tests.
