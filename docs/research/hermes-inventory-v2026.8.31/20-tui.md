# TUI (`ui-tui`) + `tui_gateway`

This shard covers the Hermes terminal UI shipped in `ui-tui/` (an Ink/React app run by Node,
launched from the Python CLI as `hermes --tui`) and the Python JSON-RPC-over-stdio/WebSocket
server in `tui_gateway/` that the TUI (and the Electron desktop app, and the dashboard's Chat
tab) talk to. It documents launch/bootstrap, chrome & layout, every overlay, every hotkey,
every TUI-owned slash command, the widget SDK, themes/skins, content tables (faces, verbs,
fortunes, charms, placeholders), and all 199 `tui_gateway` JSON-RPC methods.
Deliberately left to sibling shards: the Electron desktop shell itself (`apps/desktop`, shard
`desktop-*`), the web dashboard SPA (`web/`, shard `web-*`), the classic CLI REPL and
`hermes <cmd>` surface (shards `cli-*`), gateway/Telegram slash commands and platform adapters
(`gw-*`, `platform-*`), tools/toolsets (`tools`), and config keys as a catalog (`config-*`) —
those are cross-referenced here only where the TUI reads or writes them.

---

## 1. Launch, bootstrap and process lifecycle

### Launch the TUI  `id: tui.launch`
- **Surface:** CLI
- **Where:** shell — `hermes --tui`; also `hermes chat --tui`; documented at `website/docs/user-guide/tui.md:13-52`.
- **What it does:** Starts the modern terminal UI instead of the classic REPL. Same Python runtime, same sessions, same slash commands; the UI is a Node subprocess.
- **How it works:** `hermes_cli/main.py:_launch_tui()` (`hermes_cli/main.py:2860+`) builds a child env via `tools.environments.local.build_subprocess_env(scrub_secrets=False, inherit_profile_home=True)`, applies `apply_terminal_config_to_env()`, creates a temp "active session" JSON file, then `_make_tui_argv()` (`hermes_cli/main.py:2555`) resolves the argv and cwd. It runs `subprocess.call(argv, cwd=cwd, env=env)` (NOT exec) so it can print an exit summary and clean up. `tui_dir = PROJECT_ROOT / "ui-tui"`.
- **Inputs / options:** `--tui` (force TUI), `--cli` (force classic REPL for one invocation), `--dev` (run TypeScript source via `tsx` instead of the esbuild bundle), `-c` / `--continue` (resume latest TUI session, falling back to the latest classic session), `-r <id|title>` / `--resume <id|title|latest>`, `--in <dir>` (scope `--resume latest` to a project dir), plus every shared `hermes` flag that `_launch_tui()` forwards: `model=`, `provider=`, `toolsets=`, `skills=`, `verbose`, `quiet`, `query=`, `image=`, `worktree`, `checkpoints`, `pass_session_id`, `max_turns=`, `accept_hooks`.
- **Outputs / side effects:** Spawns Node; writes `HERMES_TUI_ACTIVE_SESSION_FILE` (a `tempfile.mkstemp(prefix="hermes-tui-active-session-", suffix=".json")`) which the child updates with the live session id; unlinks it on exit; prints the exit summary via `_print_tui_exit_summary()`; on exit code 42 relaunches `hermes update`; on `--worktree`, creates and later cleans up a git worktree via `cli._setup_worktree()` / `cli._cleanup_worktree()`.
- **Config / env:** `display.interface: cli|tui` (persistent default, `hermes_cli/main.py:_config_default_interface_early()` at `:284`); `HERMES_TUI=1` (per-shell force, `_wants_tui_early()` at `:314`). Env exported to the child: `HERMES_TUI_ACTIVE_SESSION_FILE`, `NODE_ENV` (`development` when `--dev`, else `production`), `HERMES_PYTHON_SRC_ROOT`, `HERMES_CWD`, `HERMES_PYTHON`, `HERMES_MODEL`+`HERMES_INFERENCE_MODEL` (from `--model`), `HERMES_TUI_PROVIDER`+`HERMES_INFERENCE_PROVIDER`, `HERMES_TUI_TOOLSETS` (comma-joined), `HERMES_TUI_SKILLS`, `HERMES_TUI_QUERY`, `HERMES_TUI_IMAGE`, `HERMES_TUI_CHECKPOINTS=1`, `HERMES_TUI_PASS_SESSION_ID=1`, `HERMES_TUI_MAX_TURNS`, `HERMES_TUI_TOOL_PROGRESS` (`verbose`/`off`), `HERMES_ACCEPT_HOOKS=1`, `NODE_OPTIONS` (with `--max-old-space-size=…`), `HERMES_TUI_RESUME` (explicitly `env.pop()`ed first so a stale exported value can't hijack a plain launch), `TERMINAL_CWD` (worktree).
- **Edge cases / guards:** Requires Node ≥ 20 and a TTY; piping stdin falls back to single-query mode. Explicit flags always beat `display.interface`. If the TUI can't launch (no Node, missing bundle, TTY issue) Hermes prints a diagnostic and falls back to the CLI. `KeyboardInterrupt` during the child call is mapped to exit code 130.
- **Rebuild notes:** Spawn a Node child with an inherited-but-augmented env, a temp active-session file, and a heap cap; map a magic exit code to "self-update". A better version would keep the Node process warm across `hermes` invocations (a daemon) so launch is instant, and would stream a structured bootstrap-progress channel instead of printing "Installing TUI dependencies…".

### TUI bundle resolution: prebuilt vs. build-from-source  `id: tui.bundle-resolution`
- **Surface:** CLI
- **Where:** internal, during `hermes --tui`; user-visible messages "Installing TUI dependencies…", "npm install failed.", "TUI build failed.", "TUI dev prebuild failed.", "<bin> not found — install Node.js to use the TUI."
- **What it does:** Decides whether to run a shipped prebuilt bundle, an externally supplied bundle, or to `npm install` + `esbuild` from the checkout.
- **How it works:** `hermes_cli/main.py:_make_tui_argv()` (`:2555`) in order: (1) if not `--dev` and `HERMES_TUI_DIR` is set and `<dir>/dist/entry.js` is a file → `[node, --expose-gc, <dir>/dist/entry.js]`; (1b) `_find_bundled_tui()` (`:2480`) → `hermes_cli/tui_dist/entry.js` if present; (2) otherwise `_ensure_tui_workspace(tui_dir)` (`:2515`), then `_tui_need_npm_install()` (`:2225`) → `npm install [--workspace ui-tui] --include=dev --silent --no-fund --no-audit --progress=false` run from `_workspace_root(tui_dir)`, with `maybe_repair_npm_engine()` retry on EBADENGINE; then `npm run build` (esbuild, `ui-tui/scripts/build.mjs`) unless a Termux freshness check (`_tui_need_rebuild()`, `:2392`, comparing `dist/entry.js` mtime against `_iter_tui_build_inputs()`) says the bundle is fresh; finally `[node, --expose-gc, ui-tui/dist/entry.js]`. `--dev` instead prebuilds `ui-tui/packages/hermes-ink` (`npm run build`) then runs `ui-tui/node_modules/.bin/tsx src/entry.tsx` (falling back to `npm start`).
- **Inputs / options:** `--dev`; env `HERMES_TUI_DIR` (external prebuild dir, must contain `dist/entry.js`), `HERMES_NODE` (explicit node binary), `HERMES_QUIET` (suppresses "Installing TUI dependencies…").
- **Outputs / side effects:** Creates/updates `ui-tui/node_modules`, `ui-tui/dist/entry.js`, `ui-tui/packages/hermes-ink/dist/*`. Exits 1 on install/build failure after printing the last 30 lines of combined output.
- **Config / env:** `HERMES_TUI_DIR`, `HERMES_NODE`, `HERMES_QUIET`, `NODE_ENV`.
- **Edge cases / guards:** `--dev` + `HERMES_TUI_DIR` is refused with "Error: --dev is incompatible with HERMES_TUI_DIR=…". Missing `ui-tui/` triggers `_restore_tui_workspace()` (`:2488`, `git restore -- ui-tui`) and, failing that, a message telling the user to run `git restore -- ui-tui`. `npm install --workspace ui-tui` is skipped when `ui-tui/` has its own lockfile (curl install). Prebuilt-bundle detection deliberately runs BEFORE the workspace check so a Docker/Nix image with no `ui-tui/` still works (issue #56665).
- **Rebuild notes:** Order the resolution external-prebuilt → bundled-prebuilt → build-from-source, and never require the source tree when a bundle exists. A better version would ship a content-hash manifest so the freshness check is not mtime-based, and would install into a shared per-version cache instead of the checkout.

### Node heap sizing (cgroup-aware)  `id: tui.heap-sizing`
- **Surface:** CLI / Env
- **Where:** internal; visible only as `NODE_OPTIONS=--max-old-space-size=<mb>` in the child env.
- **What it does:** Picks a V8 old-space cap that fits the container so the cgroup OOM-killer never SIGKILLs Node silently.
- **How it works:** `hermes_cli/main.py:_read_cgroup_memory_limit()` reads `/sys/fs/cgroup/memory.max` (v2) then `/sys/fs/cgroup/memory/memory.limit_in_bytes` (v1); literal `max`, `<=0`, or `>= 1<<50` bytes mean "unconstrained". `_resolve_tui_heap_mb(default_mb=8192)` returns 8192 when unconstrained, otherwise `int(limit_mb * 0.75)` clamped with `max(1536, sized)` when `limit_mb > 2048` (below that the raw sized value is used). Token-level merge: an existing user `--max-old-space-size=` in `NODE_OPTIONS` is respected. `--expose-gc` is passed as an argv flag (Node rejects it inside `NODE_OPTIONS`).
- **Inputs / options:** n/a (automatic); user override by exporting `NODE_OPTIONS=--max-old-space-size=N`.
- **Outputs / side effects:** Sets `NODE_OPTIONS` in the child env.
- **Config / env:** `NODE_OPTIONS`.
- **Edge cases / guards:** Floor 1536 MB (below that V8 GC-thrashes); never exceeds 8192.
- **Rebuild notes:** Read the cgroup limit, take 75%, clamp to [1536, 8192]. A better version would also watch `memory.current` at runtime and shed transcript history under pressure instead of only exiting.

### Update from inside the TUI (exit code 42)  `id: tui.exit-code-42`
- **Surface:** TUI / CLI
- **Where:** TUI slash command `/update`; user sees `exiting TUI to run update...` then, in the shell, `⚕ Launching update...`.
- **What it does:** Quits the TUI and re-execs `hermes update` so the user sees update output directly.
- **How it works:** `ui-tui/src/app/slash/commands/core.ts:149-164` prints the notice then `setTimeout(() => ctx.session.dieWithCode(42), 100)`. Python: `_launch_tui()` checks `if code == 42:` and calls `hermes_cli.relaunch.relaunch(["update"], preserve_inherited=False)` so `--tui` is not carried into the update subcommand.
- **Inputs / options:** none.
- **Outputs / side effects:** TUI unmounts, gateway child is killed, `hermes update` runs in the same terminal.
- **Config / env:** n/a.
- **Edge cases / guards:** Refused in dashboard chat mode with `DASHBOARD_UPDATE_DISABLED_MESSAGE` = `"update is disabled in hosted dashboard chat — the hosted environment is managed separately"` (`core.ts:89-90`).
- **Rebuild notes:** Reserve a magic exit code for "parent, do X". A better version would hand the parent a small JSON intent file so more than one post-exit action is expressible.

### Exit summary + active-session hand-off file  `id: tui.exit-summary`
- **Surface:** CLI
- **Where:** printed in the shell after the TUI quits (exit code 0 or 130).
- **What it does:** Tells the user how to resume the session they just left.
- **How it works:** `_read_tui_active_session_file(path)` (`hermes_cli/main.py:1961`) reads the temp JSON the Node child writes (env `HERMES_TUI_ACTIVE_SESSION_FILE`); `_print_tui_exit_summary(resume_session_id, active_session_file)` (`:1972`) prints the resume hint. The file is unlinked in the `finally` block.
- **Inputs / options:** n/a.
- **Outputs / side effects:** stdout lines; temp file deleted.
- **Config / env:** `HERMES_TUI_ACTIVE_SESSION_FILE`.
- **Edge cases / guards:** Only printed for exit codes `{0, 130}` — a crash or the update path (42) prints nothing.
- **Rebuild notes:** Have the UI write its live session id to a parent-provided path; print a resume hint on clean exit.

### Node entry guards and terminal hygiene  `id: tui.entry-guards`
- **Surface:** TUI
- **Where:** process start; user-visible line `hermes-tui: no TTY` when stdin is not a TTY.
- **What it does:** Refuses to start without a TTY, resets leftover terminal modes, clears the screen, and installs crash/signal/OOM handlers.
- **How it works:** `ui-tui/src/entry.tsx:17-20` `if (!process.stdin.isTTY) { console.log('hermes-tui: no TTY'); process.exit(0) }`. `resetTerminalModes()` (`src/lib/terminalModes.ts`) runs immediately and again in a `process.on('exit')` backstop (`entry.tsx:38-40`) so DEC mouse tracking `?1000/1002/1003/1006` never leaks into the parent shell (issue #28419). Screen clear: `\x1b[2J\x1b[H\x1b[3J` on desktop, a bare `\n` on Termux (`entry.tsx:45-49`). `setupGracefulExit()` (`src/lib/gracefulExit.ts`) registers cleanups (reset modes + `gw.kill('graceful-exit-cleanup')`), an `onError(scope, err)` that records `recordParentLifecycle()` breadcrumbs and exits after 5 consecutive `EIO`/`EPIPE` write failures, and an `onSignal` that logs `hermes-tui lifecycle: received <SIG>`. `ignoredSignals: DASHBOARD_TUI_MODE ? ['SIGINT'] : []`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** stderr lifecycle lines; `[tui-parent]` breadcrumbs via `src/lib/parentLog.ts`.
- **Config / env:** `HERMES_TUI_DASHBOARD` (ignores SIGINT), `HERMES_HEAPDUMP_ON_START=1` (writes a heap dump at boot).
- **Edge cases / guards:** Dead PTY (terminal closed / SSH dropped without SIGHUP) turns every write into EIO/EPIPE; the 5-in-a-row counter forces `process.exit(1)` instead of zombie-ing.
- **Rebuild notes:** Always reset DEC private modes on every exit path including `process.exit()`; count consecutive stream errors and bail.

### Memory monitor and auto heap dump  `id: tui.memory-monitor`
- **Surface:** TUI
- **Where:** stderr lines such as `hermes-tui: <level> memory (<bytes>) — auto heap dump → <path>`, `hermes-tui: heap climbing fast (<bytes>) — a large tool output or long session may be straining memory`, `hermes-tui lifecycle: memory critical exit heap=… rss=…`, `hermes-tui: exiting to avoid OOM; restart to recover`.
- **What it does:** Watches V8 heap growth, writes heap snapshots at warn/high/critical thresholds, and exits 137 before Node fatal-OOMs.
- **How it works:** `startMemoryMonitor()` (`src/lib/memoryMonitor.ts`) polls `process.memoryUsage()`; callbacks `onWarn` (breadcrumb + stderr), `onHigh` (`dumpNotice`), `onCritical` (breadcrumb `memory-critical process.exit(137) heap=… rss=… dump=…`, reset modes, stderr, `process.exit(137)`). `performHeapDump('manual'|…)` (`src/lib/memory.ts`) writes a `.heapsnapshot` plus a diagnostics file. `process.on('beforeExit', () => stopMemoryMonitor())`.
- **Inputs / options:** slash `/heapdump` and `/mem` (see below) drive the same primitives.
- **Outputs / side effects:** `<HERMES_HEAPDUMP_DIR>/*.heapsnapshot` + a diagnostics JSON; exit code 137.
- **Config / env:** `HERMES_HEAPDUMP_DIR`, `HERMES_HEAPDUMP_ON_START=1`.
- **Edge cases / guards:** 137 closes the gateway child's stdin → the gateway logs a clean EOF, not SIGTERM; the breadcrumb is the only way to attribute the death to OOM.
- **Rebuild notes:** Sample RSS+heap on an interval, classify warn/high/critical, snapshot at each, exit before the fatal.

### Inline (non-alternate-screen) rendering  `id: tui.inline-mode`
- **Surface:** TUI / Env
- **Where:** invisible switch; effect is that the TUI renders in the primary buffer and the host terminal keeps scrollback.
- **What it does:** Skips Ink's `AlternateScreen` so rows scrolled off the top land in the terminal's native scrollback.
- **How it works:** `src/config/env.ts:63-71` `INLINE_MODE = parseToggle(process.env.HERMES_TUI_INLINE) ?? TERMUX_TUI_MODE`. `src/components/appLayout.tsx:535-536` picks `Shell = INLINE_MODE ? Fragment : AlternateScreen` and only passes `mouseTracking` to the AlternateScreen.
- **Inputs / options:** `HERMES_TUI_INLINE=0|1|true|false|yes|no|on|off`.
- **Outputs / side effects:** No alt-screen enter/leave; scrollback preserved.
- **Config / env:** `HERMES_TUI_INLINE`.
- **Edge cases / guards:** Defaults ON under Termux (`isTermuxTuiMode()`, `src/lib/termux.ts`) because users background/foreground the app and need copyable scrollback.
- **Rebuild notes:** Make alt-screen a boolean at the render root; keep the composer anchored by flex flow either way.

### Termux mode  `id: tui.termux-mode`
- **Surface:** TUI / Env
- **Where:** Android/Termux launches.
- **What it does:** Adapts the TUI for touch terminals: mouse tracking off by default, inline rendering on, no screen clear, narrower composer metrics, scoped npm install and a build-freshness check.
- **How it works:** `src/lib/termux.ts:isTermuxTuiMode()` → `TERMUX_TUI_MODE` (`src/config/env.ts:26`). Effects: `entry.tsx:45` prints `\n` instead of clearing; `MOUSE_TRACKING` boot default becomes `'off'` (`env.ts:48-50`); `INLINE_MODE` defaults true; `composerPromptText(..., TERMUX_TUI_MODE, cols)` and `stableComposerColumns(cols, promptWidth, TERMUX_TUI_MODE)` (`src/lib/inputMetrics.ts`) shrink the prompt. Python: `_is_termux_startup_environment()` scopes `npm install` via `_termux_workspace_install_context()` and gates the esbuild rebuild on `_tui_need_rebuild()`.
- **Inputs / options:** n/a (auto-detected).
- **Outputs / side effects:** Different boot defaults only.
- **Config / env:** `HERMES_TUI_MOUSE_TRACKING`, `HERMES_TUI_INLINE` override the Termux defaults.
- **Edge cases / guards:** Touch selection breaks when terminal mouse protocols are armed — hence mouse-off by default.
- **Rebuild notes:** Detect the platform once at boot and flip a small set of defaults; never hardcode desktop assumptions in the render tree.

### Dashboard-embedded TUI mode  `id: tui.dashboard-mode`
- **Surface:** TUI / Web dashboard
- **Where:** the dashboard's "Chat" tab (`hermes dashboard` → `/chat`).
- **What it does:** Runs the same TUI as a PTY child inside the dashboard web server, attached to the dashboard's own in-process `tui_gateway` over a loopback WebSocket `/api/ws`.
- **How it works:** `DASHBOARD_TUI_MODE = truthy(process.env.HERMES_TUI_DASHBOARD)` (`src/config/env.ts:57`). The dashboard injects `HERMES_TUI_GATEWAY_URL` so the child attaches over WS instead of spawning its own gateway (`website/docs/user-guide/tui.md:284-292`). SIGINT is ignored (`entry.tsx:110`), `/exit` `/quit` `/update` are refused.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Chat renders in the browser terminal emulator.
- **Config / env:** `HERMES_TUI_DASHBOARD=1`, `HERMES_TUI_GATEWAY_URL` (internal only — pointing it at the OpenAI-compatible `hermes gateway` port 404s because that server does not serve `/api/ws`).
- **Edge cases / guards:** No in-page restart path after the PTY child exits, hence the SIGINT/exit guards; the keyboard idle-exit auto-starts a fresh chat instead of dying.
- **Rebuild notes:** Give the embedded instance a distinct mode flag and disable every "kill the process" affordance in it.

### Auto-resume on launch  `id: tui.auto-resume`
- **Surface:** Env
- **Where:** `export HERMES_TUI_RESUME=1` or `HERMES_TUI_RESUME=<session-id>` before `hermes --tui`.
- **What it does:** Re-attaches to the most recent TUI session (or a named one) on every launch — useful when SSH drops.
- **How it works:** `STARTUP_RESUME_ID = (process.env.HERMES_TUI_RESUME ?? '').trim()` (`src/config/env.ts:28`), consumed by `src/app/useSessionLifecycle.ts` at connect. Python clears any inherited value and re-sets it only from the argparse-resolved `--resume`.
- **Inputs / options:** `HERMES_TUI_RESUME=1` (latest) or a session id.
- **Outputs / side effects:** Session resume handshake at boot (`status` shows `resuming…`).
- **Config / env:** `HERMES_TUI_RESUME`.
- **Edge cases / guards:** `--resume <id>` on the command line overrides it for that launch.
- **Rebuild notes:** One env var, two meanings (`1` = latest, otherwise an id); always let an explicit flag win.

### Startup query / startup image  `id: tui.startup-query`
- **Surface:** Env / CLI
- **Where:** `hermes --tui --query "..."`, `hermes --tui --image path.png`.
- **What it does:** Pre-fills and auto-sends a first prompt, and/or attaches an image, as soon as the session is ready.
- **How it works:** `STARTUP_QUERY` / `STARTUP_IMAGE` (`src/config/env.ts:29-30`) from `HERMES_TUI_QUERY` / `HERMES_TUI_IMAGE`, set by `_launch_tui(query=…, image=…)`.
- **Inputs / options:** any string / any path.
- **Outputs / side effects:** The prompt is queued (non-blocking input) and sends the moment the agent comes online.
- **Config / env:** `HERMES_TUI_QUERY`, `HERMES_TUI_IMAGE`.
- **Edge cases / guards:** Empty/whitespace values are trimmed to `''` and ignored.
- **Rebuild notes:** Treat the startup prompt as an ordinary queued message so the "type before ready" path is exercised by the same code.

### FPS overlay  `id: tui.fps-overlay`
- **Surface:** TUI / Env
- **Where:** bottom-right of the app, right-aligned above the status bar; enabled with `HERMES_TUI_FPS=1`.
- **What it does:** Shows the real render rate fed by Ink's `onFrame` callback (not a synthetic timer).
- **How it works:** `SHOW_FPS = truthy(process.env.HERMES_TUI_FPS)` (`src/config/env.ts:75`); `entry.tsx:150-165` attaches `onFrame` only when `logFrameEvent` (`src/lib/perfPane.tsx`) or `trackFrame` (`src/lib/fpsStore.ts`) exist, so the default path skips timing entirely. `src/components/fpsOverlay.tsx` renders the value; `appLayout.tsx:576-580` places it in a `justifyContent="flex-end" paddingRight={1}` box.
- **Inputs / options:** none (display-only).
- **Outputs / side effects:** One extra row.
- **Config / env:** `HERMES_TUI_FPS`.
- **Edge cases / guards:** Hidden entirely when `overlay.agents` or `overlay.journey` take over the screen.
- **Rebuild notes:** Instrument the renderer's own frame callback; never sample with a separate interval — that measures the timer, not the UI.

### Perf pane / frame logging  `id: tui.perf-pane`
- **Surface:** TUI / Env
- **Where:** wraps each major pane (`PerfPane id="agents" | "journey" | "transcript" | "prompt" | "composer"`, `appLayout.tsx:544-575`).
- **What it does:** Attributes render cost to a named region so slow panes are identifiable.
- **How it works:** `src/lib/perfPane.tsx` exports `PerfPane` and `logFrameEvent`; both are undefined unless their env flag is on, so the production tree pays nothing.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Frame log lines.
- **Config / env:** the perf env flag read in `src/lib/perfPane.tsx`.
- **Edge cases / guards:** `onFrame` is only attached when at least one consumer exists.
- **Rebuild notes:** Make instrumentation a compile-away no-op by default.

### Force truecolor  `id: tui.force-truecolor`
- **Surface:** Env
- **Where:** must be the very first import (`entry.tsx:4`).
- **What it does:** Nudges chalk / supports-color into 24-bit mode before either package initializes.
- **How it works:** `src/lib/forceTruecolor.ts` sets the relevant env before chalk reads it; test at `src/__tests__/forceTruecolor.test.ts`.
- **Inputs / options:** the truecolor env flag (`HERMES_TUI_FORCE_TRUECOLOR`-family) read in `forceTruecolor.ts`.
- **Outputs / side effects:** All theme colors emit as 24-bit SGR.
- **Config / env:** see above.
- **Edge cases / guards:** Import order is load-bearing — importing chalk first defeats it.
- **Rebuild notes:** Set color-depth env before any color library loads.

### Hyperlink click → open in browser  `id: tui.hyperlink-click`
- **Surface:** TUI
- **Where:** clicking any `<Link>` cell in the transcript/overlays.
- **What it does:** Opens the URL in the user's default browser.
- **How it works:** `entry.tsx:174-176` passes `onHyperlinkClick: url => { openExternalUrl(url) }` into `ink.render()`; `src/lib/openExternalUrl.ts` (158 lines) picks the platform opener. Needed because the TUI's mouse tracking captures the click before Terminal.app's own URL detection.
- **Inputs / options:** mouse click on a link cell.
- **Outputs / side effects:** Spawns the OS URL handler.
- **Config / env:** n/a.
- **Edge cases / guards:** Only fires when mouse tracking is on.
- **Rebuild notes:** Own the click, then delegate to the OS opener; don't rely on the terminal's own link detection when you grab the mouse.

### Ink render options  `id: tui.ink-render-options`
- **Surface:** TUI / Core
- **Where:** `entry.tsx:167-177`.
- **What it does:** Mounts `<App gw={gw} />` with `exitOnCtrlC: false`, the optional `onFrame`, and `onHyperlinkClick`.
- **How it works:** `@hermes/ink` is a vendored fork of Ink living at `ui-tui/packages/hermes-ink` (custom reconciler, yoga layout, DEC/OSC termio parser, mouse + selection + scrollbox + alternate-screen support). `exitOnCtrlC: false` hands Ctrl+C to the app's own handler (`useInputHandlers`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** The render loop.
- **Config / env:** n/a.
- **Edge cases / guards:** Ctrl+C semantics are entirely app-owned (copy / clear draft / interrupt / exit).
- **Rebuild notes:** Never let the renderer own Ctrl+C in an app with a multi-meaning Ctrl+C.

---

## 2. Keyboard & mouse bindings

The canonical, user-visible list lives in `ui-tui/src/content/hotkeys.ts` and is rendered verbatim
under the `Hotkeys` section of `/help`. `action` = `Cmd` on macOS, `Ctrl` elsewhere; `paste` =
`Cmd` on macOS, `Alt` elsewhere (`hotkeys.ts:3-4`). Every row below is transcribed exactly.

### Hotkey — copy selection (macOS)  `id: tui.hotkey-cmd-c-mac`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → row `Cmd+C` / `copy selection` (macOS only, `hotkeys.ts:8`).
- **What it does:** Copies the current mouse-drag selection to the system clipboard.
- **How it works:** `useInputHandlers` `isCopyShortcut(key, ch)` (`src/lib/platform.ts:40-51`) → `terminal.selection.copySelection()`, which routes through hermes-ink's `setClipboard()` (pbcopy on macOS, wl-copy/xclip on Linux, tmux buffer, OSC 52 fallback). With no terminal selection it falls back to the composer's own input selection (`handleInputSelectionClipboard(sel, 'copy')`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** System clipboard write.
- **Config / env:** `HERMES_TUI_FORCE_OSC52=1` forces the escape-sequence path.
- **Edge cases / guards:** On macOS with no selection this is a deliberate no-op (`platform.ts` / `useInputHandlers.ts:606-608`) so Ctrl+C stays interrupt. `isCopyShortcut` also accepts the VS Code/Cursor/Windsurf CSI-u shape (`isMac && key.ctrl && (key.meta || key.super)`).
- **Rebuild notes:** Resolve copy against terminal selection first, composer selection second; never swallow the key when neither exists.

### Hotkey — `Ctrl+C` (clear draft / interrupt / exit)  `id: tui.hotkey-ctrl-c`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → macOS row `Ctrl+C` / `clear draft / interrupt / exit`; non-mac row `Ctrl+C` / `copy selection / clear draft / interrupt / exit`; remote-shell row adds `Cmd+C` / `copy selection when forwarded by the terminal` (`hotkeys.ts:6-16`).
- **What it does:** One key, three meanings resolved in a fixed order: a non-empty composer is cleared; otherwise a running turn is interrupted; otherwise the app exits.
- **How it works:** `resolveCtrlCComposerAction({busy, hasDraft, hasSession})` (`src/app/useInputHandlers.ts:72-86`) returns `'clear' | 'interrupt' | 'exit'` — draft always wins, then `busy && hasSession` → interrupt via `turnController.interruptTurn({appendMessage, gw, sid, sys})`, else `handleIdleHotkeyExit()`. While an overlay is open Ctrl+C instead runs `cancelOverlayFromCtrlC()`, which walks the overlay stack in this exact order: `clarify` → answer `''`; `approval` → `approval.respond {choice:'deny'}` and turn outcome `denied`; `sudo`/`secret` → `dismissSensitivePrompt()`; `modelPicker`; `petPicker`; `billing`; `subscription`; `skillsHub`; `pluginsHub`; `sessions`; `agents`; `journey`; `widget` → `closeWidget()` (`useInputHandlers.ts:211-265`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Composer cleared, or `session.interrupt` RPC, or process exit; in dashboard mode it instead publishes a local `dashboard.new_session_requested` event with `payload {reason:'idle_exit_hotkey'}` and prints `starting a fresh dashboard chat...`.
- **Config / env:** `HERMES_TUI_DASHBOARD`.
- **Edge cases / guards:** `shouldAllowIdleHotkeyExit(dashboardTuiMode)` returns false in dashboard mode so Ctrl+C can never brick the browser tab. Ink is mounted with `exitOnCtrlC: false` so the app owns the key.
- **Rebuild notes:** Encode the three-way resolution in one pure function so it is testable; route overlay dismissal through a single ordered walker.

### Hotkey — exit (`Cmd+D` / `Ctrl+D`)  `id: tui.hotkey-exit`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `<Cmd|Ctrl>+D` / `exit` (`hotkeys.ts:20`).
- **What it does:** Quits the TUI.
- **How it works:** `isAction(key, ch, 'd')` → `handleIdleHotkeyExit(actions, DASHBOARD_TUI_MODE, …)` (`useInputHandlers.ts:663-671`), which calls `actions.die()` (gateway kill + Ink unmount + `process.exit`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Process exit; the parent prints the resume summary.
- **Config / env:** `HERMES_TUI_DASHBOARD` (converts it into "start a fresh dashboard chat").
- **Edge cases / guards:** Same dashboard guard as Ctrl+C.
- **Rebuild notes:** Share one exit path so terminal-mode cleanup can't be bypassed.

### Hotkey — open `$EDITOR` (`Cmd/Ctrl+G`, `Alt+G`)  `id: tui.hotkey-editor`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `<Cmd|Ctrl>+G / Alt+G` / `open $EDITOR (Alt+G fallback for VSCode/Cursor)` (`hotkeys.ts:21`). Also reachable as `/prompt` (alias `/compose`) and, per the docs, `Ctrl+X Ctrl+E`.
- **What it does:** Opens the current composer buffer in `$EDITOR` for multi-line composition; save-and-exit sends the contents back into the composer.
- **How it works:** `useInputHandlers.ts:687-691` matches `ch === 'g' && (isAction(...) || key.meta)` then `cActions.openEditor()`; `src/lib/editor.ts` writes a temp file, suspends Ink (`withInkSuspended`), spawns the editor, reads the file back. Failure prints `failed to open editor: <msg>`.
- **Inputs / options:** none; `$EDITOR` / `$VISUAL` decide the program.
- **Outputs / side effects:** Temp file created and removed; composer value replaced.
- **Config / env:** `EDITOR`, `VISUAL`.
- **Edge cases / guards:** VS Code / Cursor bind the primary chord to "Find Next" before the TUI sees it, hence the `Alt+G` (meta+g) fallback; `/terminal-setup` can install IDE keybindings that fix this.
- **Rebuild notes:** Suspend the renderer, restore terminal modes, spawn the editor on the real TTY, then resume.

### Hotkey — redraw / repaint (`Cmd/Ctrl+L`)  `id: tui.hotkey-redraw`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `<Cmd|Ctrl>+L` / `redraw / repaint` (`hotkeys.ts:22`). Also `/redraw`.
- **What it does:** Clears the selection and forces a full repaint of the Ink tree.
- **How it works:** `isAction(key, ch, 'l')` → `clearSelection(); forceRedraw(terminal.stdout ?? process.stdout)` (`useInputHandlers.ts:673-678`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Full repaint.
- **Config / env:** n/a.
- **Edge cases / guards:** Reserved — `voice.record_key` refuses to bind `ctrl+l` (`platform.ts:_RESERVED_CTRL_CHARS`).
- **Rebuild notes:** Expose a renderer-level "invalidate everything" that also drops the differential-update cache.

### Hotkey — paste text / image (`Cmd+V` / `Alt+V`, `/paste`)  `id: tui.hotkey-paste`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `<Cmd|Alt>+V / /paste` / `paste text; /paste attaches clipboard image` (`hotkeys.ts:23`).
- **What it does:** Pastes clipboard text into the composer; when the clipboard holds an image (or the pasted payload resolves to one), attaches it instead.
- **How it works:** `src/components/textInput.tsx:1360-1380` matches raw sequences `\x1bv`, `\x1bV`, `\x16` (Ctrl+V) or macOS `isActionMod + 'v'`; it first calls the registered paste callback (`emitPaste({hotkey:true})`), and on macOS falls back to `readClipboardText()` → `pastePlainText()`. Bracketed paste (`\x1b[200~…`) is handled in the printable branch (`textInput.tsx:1560+`) via `emitPaste({bracketed:true, …})`. `src/lib/clipboard.ts` (202 lines) implements native reads/writes; `src/lib/osc52.ts` the escape-sequence fallback; `src/domain/attachments.ts` normalizes image/file paths.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Composer text insertion, or an image attachment chip; long pastes collapse inline (see `tui.paste-collapse`).
- **Config / env:** `HERMES_TUI_FORCE_OSC52`.
- **Edge cases / guards:** A configured voice `record_key` of `…+v` wins over paste (`shouldPassThroughToGlobalHandler`, `textInput.tsx:1352`). CRLF is normalized to LF.
- **Rebuild notes:** Handle three paste transports (bracketed paste, hotkey + native clipboard read, OSC52) behind one `emitPaste` and normalize newlines once.

### Hotkey — `Esc Esc` discard draft  `id: tui.hotkey-double-esc`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `Esc Esc` / `discard draft (recall with ↑)` (`hotkeys.ts:24`).
- **What it does:** Two Escapes within 500 ms clear the composer and push the discarded text onto input history so `↑` recalls it.
- **How it works:** `useInputHandlers.ts:363-383`: `lastEscRef` timestamp compared against `DOUBLE_ESC_MS = 500` (`src/config/timing.ts:20`); on a double with non-empty input it calls `cActions.pushHistory(input)` (when the text is non-blank) then `cActions.clearIn()`. Deliberately placed ABOVE the `isBlocked` early-return so an overlay cannot swallow it.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Composer cleared; history entry appended.
- **Config / env:** n/a.
- **Edge cases / guards:** Single Esc is used for: voice chord (if bound to `…+escape`), queue-edit cancel, selection clear, pager close, sessions-overlay close, secret/sudo cancel — in that priority order (`useInputHandlers.ts:552-565`).
- **Rebuild notes:** Debounce window ~500 ms; store the discarded draft so it is recoverable.

### Hotkey — `Tab` apply completion  `id: tui.hotkey-tab`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `Tab` / `apply completion` (`hotkeys.ts:25`).
- **What it does:** Applies the highlighted completion row into the composer.
- **How it works:** `useInputHandlers.ts:716-724` → `applyCompletion(input, row.text, compReplace)` (`src/domain/slash.ts:253-257`), which drops the row's leading `/` when the character before `compReplace` is already `/`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Composer value replaced from `compReplace` onward.
- **Config / env:** n/a.
- **Edge cases / guards:** Only when `completions.length` is non-zero; `Shift+Tab` with no completions toggles YOLO instead.
- **Rebuild notes:** Keep a `compReplace` index alongside the rows so replacement is exact, not a prefix guess.

### Hotkey — `↑` / `↓` (completions / queue edit / history)  `id: tui.hotkey-arrows`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `↑/↓` / `completions / queue edit / history` (`hotkeys.ts:26`).
- **What it does:** Cycles the completion menu when it is open; otherwise walks the queued-message list; otherwise walks input history; inside a multi-line draft it moves the caret between lines.
- **How it works:** Priority in `useInputHandlers.ts`: (1) `completions.length && input && historyIdx === null` → `setCompIdx` wrap-around (`:494-500`); (2) `Shift+↑/↓` → transcript scroll by one row (`:531-537`); (3) plain `↑` with no line above the caret → `cycleQueue(1) || cycleHistory(-1)` (`:567-579`); (4) plain `↓` with no line below or an active history index → `cycleQueue(-1) || cycleHistory(1)` (`:581-591`). `cycleQueue` sets `queueEditIdx` and loads the queued text into the composer; `cycleHistory` stashes the live draft in `historyDraftRef` before the first step back and restores it when walking past the newest entry. Inside `TextInput`, `lineNav()` handles caret movement first (`textInput.tsx:1395-1407`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Composer value replaced; `queueEditIdx` set/cleared.
- **Config / env:** n/a.
- **Edge cases / guards:** Caret-position aware — `getInputSelection()` is consulted so `↑` inside a wrapped multi-line draft moves the caret rather than jumping to history.
- **Rebuild notes:** Layer completions → scroll → queue → history and check caret line context before stealing the arrow.

### Hotkey — `Ctrl+X` (session switcher / delete queued / cut)  `id: tui.hotkey-ctrl-x`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `Ctrl+X` / `open live session switcher (deletes queued message while editing)` (`hotkeys.ts:27`).
- **What it does:** Three meanings in order: cut an active composer selection; delete the queued message currently being edited; otherwise open the live session switcher.
- **How it works:** `useInputHandlers.ts:611-623`: `handleInputSelectionClipboard(getInputSelection(), 'cut')` → if `queueEditIdx !== null` `cActions.removeQueue(idx)` + `clearIn()` → else `patchOverlayState({ sessions: true })`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Clipboard write / queue mutation / overlay open.
- **Config / env:** n/a.
- **Edge cases / guards:** `Esc` cancels a queue edit without deleting. `ctrl+x` is deliberately allowed as a `voice.record_key` value because it is only claimed during queue-edit (`platform.ts:152`).
- **Rebuild notes:** Order the three meanings most-specific-first and document the Esc escape hatch in the queue header.

### Hotkey — `Ctrl+O` open model picker  `id: tui.hotkey-ctrl-o`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` → `Ctrl+O` / `open model picker (keeps your draft; applies to next turn mid-stream)` (`hotkeys.ts:28`).
- **What it does:** Opens the same overlay `/model` opens, without disturbing the typed draft.
- **How it works:** `useInputHandlers.ts:630-632` → `patchOverlayState({ modelPicker: true })`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Overlay opens; picking a model issues `config.set {key:'model', session_id}`, which mid-turn is queued and applied at the next turn start (`deferred: true`).
- **Config / env:** n/a.
- **Edge cases / guards:** Works mid-stream — there is no busy guard for model changes (unlike session switching).
- **Rebuild notes:** Never require clearing the composer to reach a picker.

### Hotkey — line/word editing chords  `id: tui.hotkey-editing`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` rows `<Cmd|Ctrl>+A/E` / `home / end of line`; `<Cmd|Ctrl>+Z / <Cmd|Ctrl>+Y` / `undo / redo input edits`; `<Cmd|Ctrl>+W` / `delete word`; `<Cmd|Ctrl>+U/K` / `kill to line start / end (repeat across lines)`; `<Cmd|Ctrl>+←/→` / `jump word`; `Home/End` / `start / end of line` (`hotkeys.ts:29-34`).
- **What it does:** Full readline-style editing inside the composer.
- **How it works:** `src/components/textInput.tsx:1428-1560`. `mod = isActionMod(k)`; `wordMod = mod || k.meta`. Bindings: `mod+z` → undo (`swap(undo, redo)`); `mod+y` or `mod+shift+z` → redo; macOS `mod+a` → `selectAll()`; `actionHome = k.home || (!isMac && mod && 'a') || isMacActionFallback(k,'a')`; `actionEnd = k.end || (mod && 'e') || isMacActionFallback(k,'e')`; `actionDeleteToStart = (mod && 'u') || isMacActionFallback(k,'u')` → `killToLineStart`; `actionKillToEnd = (mod && 'k') || isMacActionFallback(k,'k')` → `killToLineEnd`; `actionDeleteWord = (mod && 'w') || isMacActionFallback(k,'w')`; `wordMod + 'b'` → `wordLeft`; `wordMod + 'f'` → `wordRight`; `wordMod + 'd'` → `deleteWordForward` (readline kill-word; also the web dashboard's Ctrl+Delete → `ESC d`); `←/→` with `wordMod` jump by word, plain collapse a selection to its edge; `Backspace` with `isLineKillModifier(k)` (Cmd+Backspace) → `killToLineStart`, with `wordMod` → delete word back, else a fast single-char backspace that writes `"\b \b"` directly and calls `noteCursorAdvance()` to keep Ink's cursor model in sync; forward `Delete` mirrors this with `killToLineEnd` / `deleteWordForward`. Holding `Shift` with any motion extends the selection (`moveCursor(c, k.shift)`).
- **Inputs / options:** All chords above.
- **Outputs / side effects:** Composer value/cursor/selection mutations; undo/redo ring.
- **Config / env:** n/a.
- **Edge cases / guards:** `isMacActionFallback` accepts raw `Ctrl+A/E/U/K/W` on macOS because some terminals rewrite Cmd navigation into readline control keys. `Ctrl+U`/`Ctrl+K` repeat across lines.
- **Rebuild notes:** Implement kill-to-start/end as line-local operations so repeats walk lines; keep a fast-path for the common single-char backspace that writes bytes directly.

### Hotkey — newline vs. submit  `id: tui.hotkey-newline`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` rows `Shift+Enter / Alt+Enter` / `insert newline` and `\+Enter` / `multi-line continuation (fallback)` (`hotkeys.ts:35-36`).
- **What it does:** Enter submits; Shift+Enter / Alt+Enter insert a literal newline; a trailing backslash before Enter is the terminal-agnostic fallback.
- **How it works:** `textInput.tsx:1414-1427`: on `k.return` it computes `valueForReturnSubmit(value, cursor, inp, range)` and `shouldInsertNewlineOnReturn(k, sequence)`; insert → `commit(ins(pending.value, pending.cursor, '\n'), pending.cursor+1)`, else `cbSubmit.current?.(pending.value)`.
- **Inputs / options:** `Enter`, `Shift+Enter`, `Alt+Enter`, `\` + `Enter`.
- **Outputs / side effects:** Submit or newline.
- **Config / env:** n/a.
- **Edge cases / guards:** Terminals that cannot distinguish Shift+Enter need the `\`+Enter fallback; `/terminal-setup` installs VS Code/Cursor/Windsurf bindings that make `Cmd+Enter` work.
- **Rebuild notes:** Detect the modifier from the raw escape sequence, not only the decoded key flags.

### Hotkey — inline shell (`!<cmd>` and `{!<cmd>}`)  `id: tui.hotkey-shell`
- **Surface:** TUI
- **Where:** `/help` → `Hotkeys` rows `!<cmd>` / `run a shell command (e.g. !ls, !git status)` and `{!<cmd>}` / `interpolate shell output inline (e.g. "branch is {!git branch --show-current}")` (`hotkeys.ts:37-38`).
- **What it does:** A composer line starting with `!` runs as a shell command instead of a prompt; `{!cmd}` anywhere in a prompt is replaced by that command's stdout before sending.
- **How it works:** The composer detects the leading `!` and paints the prompt glyph in `theme.color.shellDollar` (`appLayout.tsx:281, 409-411`); interpolation lives in `src/protocol/interpolation.ts` and the submission path (`src/app/submissionCore.ts`, `src/app/useSubmission.ts`).
- **Inputs / options:** any shell command string.
- **Outputs / side effects:** Command output enters the transcript / the outgoing message.
- **Config / env:** shell resolution follows the backend's `run_command` tool policy.
- **Edge cases / guards:** Approval/permission policy still applies on the backend side.
- **Rebuild notes:** Detect the mode at keystroke time so the prompt glyph can recolor and give visual feedback before Enter.

### Hotkey — `Shift+Tab` toggle YOLO  `id: tui.hotkey-shift-tab`
- **Surface:** TUI
- **Where:** composer, when no completion menu is open. Prints `yolo on` / `yolo off` / `failed to toggle yolo` / `yolo needs an active session`.
- **What it does:** Flips per-session auto-approval without spending a turn (claude-code parity).
- **How it works:** `useInputHandlers.ts:694-714` → `config.set {key:'yolo', session_id}`; `r.value === '1'` → `yolo on`, `'0'` → `yolo off`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Session-scoped YOLO flag; the status bar and startup banner show `⚠ YOLO`.
- **Config / env:** `HERMES_YOLO_MODE=1`, `hermes --yolo`, `/yolo`.
- **Edge cases / guards:** Requires an active session. `gateway.rpc` swallows errors with its own `sys()` line and resolves `null`, so the handler only speaks on a real response.
- **Rebuild notes:** Make the dangerous mode both keyboard-cheap and permanently visible.

### Hotkey — `Ctrl+B` voice push-to-talk  `id: tui.hotkey-voice`
- **Surface:** TUI
- **Where:** composer; default binding `Ctrl+B`, configurable. Messages: `voice: mode is off — enable with /voice on`, `voice: still transcribing; try again shortly`, `voice error: <msg>`.
- **What it does:** Starts/stops a VAD-bounded push-to-talk capture that transcribes into the composer.
- **How it works:** `voiceRecordToggle()` (`useInputHandlers.ts:328-357`) → `voice.record {action:'start'|'stop', session_id}`; the badge flips optimistically and is corrected by the gateway's `voice.status` / `voice.transcript` events (handled in `createGatewayEventHandler`). `applyVoiceRecordResponse()` maps `status:'busy'` to the "still transcribing" nudge. The binding comes from `voice.record_key` in `config.yaml`, parsed by `parseVoiceRecordKey()` and matched by `isVoiceToggleKey()` (`src/lib/platform.ts:229-414`). Escape-based chords are checked before the generic Esc handlers (`useInputHandlers.ts:552-554`).
- **Inputs / options:** `voice.record_key` accepts `<mod>+<key>` with mod ∈ {`ctrl`,`control`,`alt`,`option`,`opt`,`super`,`win`,`windows`} and key = one character or one of `space`,`spc`,`enter`,`ret`,`return`,`tab`,`escape`,`esc`,`backspace`,`bs`,`delete`,`del`.
- **Outputs / side effects:** Microphone capture; transcript injected into the composer; `● REC` / `◉` badge in the status bar.
- **Config / env:** `voice.record_key` (default `ctrl+b`), `voice.stop_phrases`, `/voice on|off|tts|status`.
- **Edge cases / guards:** Rejected bindings fall back to `ctrl+b`: multi-modifier chords, no modifier, unknown modifier, `ctrl+c|d|l`, on macOS `super+c|d|l|v` and `alt+c|d|l`, unknown named tokens, and non-string YAML scalars. Shift must be clear at match time. `meta`/`cmd`/`command` are deliberately NOT modifier aliases (ambiguous with Alt on legacy terminals).
- **Rebuild notes:** Validate a configurable binding against the set of keys the app already intercepts, and fall back loudly rather than advertising a dead shortcut.

### Hotkey — `Cmd/Ctrl+K` flush one queued message  `id: tui.hotkey-dequeue`
- **Surface:** TUI
- **Where:** composer, when the queue is non-empty and a session exists.
- **What it does:** Pops the oldest queued message and dispatches it immediately.
- **How it works:** `useInputHandlers.ts:726-733` → `cActions.dequeue()` then `actions.dispatchSubmission(next)` with `setQueueEdit(null)`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A turn starts.
- **Config / env:** n/a.
- **Edge cases / guards:** Shares the chord with kill-to-end-of-line — the queue branch runs after the TextInput has already consumed the key when the composer has focus and content.
- **Rebuild notes:** Keep queue flushing explicit so a user can drain their queue without waiting for the agent.

### Scrolling — wheel, acceleration and precision mode  `id: tui.scroll-wheel`
- **Surface:** TUI
- **Where:** transcript area; mouse wheel, `PageUp`/`PageDown`, `Shift+↑/↓`.
- **What it does:** Scrolls the transcript with claude-code-style acceleration, plus a modifier-held one-row-per-frame precision mode.
- **How it works:** `useInputHandlers.ts:502-546`. Base step `WHEEL_SCROLL_STEP = 1` (`src/config/limits.ts:26`) keeps Ink's DECSTBM fast path live. `computeWheelStep(wheelAccelRef.current, dir, now)` (`src/lib/wheelAccel.ts`, 190 lines) derives a multiplier from inter-event timing; a direction flip resets it and returns `0` (bounce deferral). `computePrecisionWheelStep(precisionWheelRef.current, dir, hasModifier, now)` (`src/lib/precisionWheel.ts`) activates when `key.meta || key.ctrl` (Shift is reserved for selection extension) and coalesces same-frame bursts; entering precision mode reinitialises the accel state. `PageUp/PageDown` scroll half a viewport (`Math.max(4, floor(viewport/2))`). While the agent is busy, scrolling calls `turnController.boostStreamingForScroll()` and schedules `relaxStreaming()` after `TYPING_IDLE_MS = 250`.
- **Inputs / options:** wheel up/down, `Alt`/`Option`/`Ctrl` + wheel, `PageUp`, `PageDown`, `Shift+↑`, `Shift+↓`.
- **Outputs / side effects:** Scroll position; streaming batch cadence temporarily changed (`STREAM_SCROLL_BATCH_MS = 96`).
- **Config / env:** `display.mouse_tracking` gates whether wheel events arrive at all.
- **Edge cases / guards:** Scroll keys explicitly fall through prompt overlays via `shouldFallThroughForScroll(key)` so the user can read context above an approval prompt.
- **Rebuild notes:** Model acceleration on inter-event timing, reset on direction flip, and reserve a modifier for precision.

### Mouse selection & drag  `id: tui.mouse-selection`
- **Surface:** TUI
- **Where:** anywhere in the transcript and composer.
- **What it does:** Drag highlights text with a uniform selection background (not SGR inverse); clicking blank cells clears the selection.
- **How it works:** hermes-ink's `selection.ts` / `NoSelect` / `hit-test.ts`. `appLayout.tsx` wires `onClick={e => e.cellIsBlank && actions.clearSelection()}` on both the transcript ScrollBox and the composer. The composer additionally maps gutter drags into `TextInput` coordinates: `captureInputDrag` (`startAtBeginning()`), `dragFromPromptRow` (`dragAt(localRow, localCol - promptWidth)`), `dragFromSpacer` (`dragAt(0, localCol - promptWidth)`), `endInputDrag` (`end()`) — all guarded on `e.button === 0` and calling `stopImmediatePropagation()` (`appLayout.tsx:297-329`).
- **Inputs / options:** left-button drag; `Esc` clears; `Cmd/Ctrl+C` copies.
- **Outputs / side effects:** Selection state; clipboard on copy.
- **Config / env:** `display.mouse_tracking` (`off|wheel|buttons|all`).
- **Edge cases / guards:** `buttons` (DEC 1002) is required for terminal-side drag; `all` (DEC 1003) adds hover.
- **Rebuild notes:** Use a background-color selection rather than inverse video so themes stay legible.

### Mouse tracking presets  `id: tui.mouse-tracking`
- **Surface:** TUI / Config / Env
- **Where:** `/mouse [on|off|toggle|wheel|buttons|all]` (alias `/scroll`); config `display.mouse_tracking`.
- **What it does:** Chooses which DEC mouse protocols the TUI arms.
- **How it works:** Boot default from `src/config/env.ts:32-50`: `HERMES_TUI_MOUSE_TRACKING` (truthy/falsy) overrides everything, then `HERMES_TUI_DISABLE_MOUSE=1` (legacy kill switch), then Termux → off, desktop → `'all'`. Runtime: `mouseModeFromArg()` (`core.ts:68-74`) maps aliases `all|any|full|on → all`, `button|buttons|click → buttons`, `scroll|wheel → wheel`, `off → off`, bare/`toggle` → flip between `off` and `all`; then `patchUiState({mouseTracking})` and `config.set {key:'mouse', value}`. Modes map to DEC sets: `wheel` = 1000+1006, `buttons` = +1002, `all` = +1003 (`website/docs/user-guide/tui.md:126, 237-243`).
- **Inputs / options:** `on`, `off`, `toggle`, `wheel`, `buttons`, `all`, `any`, `full`, `button`, `click`, `scroll`; bare `/mouse`.
- **Outputs / side effects:** `mouse tracking <mode>` transcript line; `display.mouse_tracking` persisted in `config.yaml`.
- **Config / env:** `display.mouse_tracking` (`off|wheel|buttons|all`, also accepts `true`/`false` for back-compat), `HERMES_TUI_MOUSE_TRACKING`, `HERMES_TUI_DISABLE_MOUSE`.
- **Edge cases / guards:** Inside tmux, hover events (1003) make the terminal spam "No image in clipboard" over the prompt row — `wheel` is the documented fix. Invalid arg prints `usage: /mouse [on|off|toggle|wheel|buttons|all]`.
- **Rebuild notes:** Expose the protocol subsets, not a boolean; hover is the expensive one.

---

## 3. Chrome & layout

### App shell / layout tree  `id: tui.app-layout`
- **Surface:** TUI
- **Where:** the whole screen.
- **What it does:** Composes the TUI into: (optional AlternateScreen) → row of [left ambient rail | main pane | right ambient rail] → PromptZone → ComposerPane → optional FPS row → floating PetPane → ActiveWidgetSlot.
- **How it works:** `src/components/appLayout.tsx:521-590`. The main pane is `AgentsOverlayPane` when `overlay.agents`, `JourneyPane` when `overlay.journey`, else `TranscriptPane` — those two overlays REPLACE the transcript and unmount PromptZone/Composer/Pet entirely. `App` (`src/app.tsx`) wires `useMainApp(gw)` → `{appActions, appComposer, appProgress, appStatus, appTranscript, gateway}` into `AppLayout` inside a `GatewayProvider`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The rendered frame.
- **Config / env:** `HERMES_TUI_INLINE`, `HERMES_TUI_FPS`, `display.mouse_tracking`.
- **Edge cases / guards:** Each pane is wrapped in `PerfPane` with ids `agents`, `journey`, `transcript`, `prompt`, `composer` for frame attribution.
- **Rebuild notes:** Make full-screen overlays replace the main pane rather than stack on it, so their timers and layout cost vanish when closed.

### Transcript pane (virtualised history)  `id: tui.transcript`
- **Surface:** TUI
- **Where:** the main scrolling area.
- **What it does:** Renders the conversation with windowed virtualisation, per-turn separators, an intro banner row, panel rows, and the live streaming tail.
- **How it works:** `TranscriptPane` (`appLayout.tsx:138-272`) puts a `ScrollBox stickyScroll` around `transcript.virtualRows.slice(virtualHistory.start, virtualHistory.end)`, with `topSpacer` / `bottomSpacer` boxes for the unrendered ranges and `measureRef(row.key)` per row. `useVirtualHistory` (`src/hooks/useVirtualHistory.ts`, 689 lines) maintains measured heights (`src/lib/virtualHeights.ts`) and offsets. Row kinds: `intro` → `<Banner>` + `<SessionPanel>`; `panel` → `<Panel>`; everything else → `<MessageLine>` with `prev` computed by `prevRenderedMsg()` (`src/domain/blockLayout.ts`). A `───` separator in `theme.color.border` is inserted above every user message after the first (`appLayout.tsx:200-204`). `MAX_HISTORY = 800` messages (`src/config/limits.ts:20`).
- **Inputs / options:** wheel / PageUp / PageDown / Shift+arrows; click on a blank cell clears the selection.
- **Outputs / side effects:** Scroll position published to `src/lib/viewportStore.ts`.
- **Config / env:** `display.details_mode`, `display.sections.*`, `display.timestamps`, compact mode.
- **Edge cases / guards:** Body columns shrink for the pet gutter and ambient rails: `useGutter = petBox && cols - railCols - petBox.width >= MIN_GUTTER_BODY_COLS (72)`; otherwise `petBandRows` reserves bottom rows. `bodyCols` floor is 28.
- **Rebuild notes:** Measure real row heights and window on them; never estimate, or scrolling drifts.

### Transcript scrollbar  `id: tui.scrollbar`
- **Surface:** TUI
- **Where:** one-column gutter on the right of the transcript.
- **What it does:** Shows scroll position and supports click-to-jump and drag-to-scroll.
- **How it works:** `TranscriptScrollbar` (`appChrome.tsx`, near the end): thumb size `max(1, round(vp*vp/total))`, `travel = max(1, vp - thumb)`, `thumbTop = round(pos / (total-vp) * travel)`. Track glyph `│`, thumb glyph `┃`. `onMouseDown` grabs (offset = click-within-thumb, else half the thumb) and jumps; `onMouseDrag` continues; `onMouseEnter/Leave` set hover; colors from `scrollbarColors(t, hover, dragging)` (`src/components/overlayPrimitives.tsx`).
- **Inputs / options:** click, drag, hover.
- **Outputs / side effects:** `scrollTo()` on the ScrollBox handle.
- **Config / env:** hover requires `display.mouse_tracking: all`.
- **Edge cases / guards:** When there is nothing to scroll it draws NOTHING (the `width={1}` box still reserves the column) — drawn-blank cells composite to a black bar on transparent terminals.
- **Rebuild notes:** Reserve the column always, paint only when scrollable.

### Sticky prompt tracker  `id: tui.sticky-prompt`
- **Surface:** TUI
- **Where:** a single line just above the status rule / composer, prefixed `↳ `.
- **What it does:** While you scroll away from the top of a long turn, keeps the originating user prompt visible.
- **How it works:** `StickyPromptTracker` (`appChrome.tsx`) reads `useViewportSnapshot(scrollRef)` → `{top, bottom, atBottom}` and calls `stickyPromptFromViewport(messages, offsets, top, bottom, atBottom)` (`src/domain/viewport.ts`), pushing the result through `onChange`. `ComposerPane` renders `status.showStickyPrompt ? <Text …>↳ {stickyPrompt}</Text> : <Box height={1} …/>` (`appLayout.tsx:356-364`) so the row height never changes.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One line of chrome.
- **Config / env:** n/a.
- **Edge cases / guards:** Renders nothing (but keeps a 1-row spacer, which doubles as a composer drag target) when at the bottom.
- **Rebuild notes:** Derive it from measured offsets, not from a scroll-percentage guess.

### Status rule (status bar)  `id: tui.status-rule`
- **Surface:** TUI
- **Where:** one row, at the top of the composer block by default (`display.status_bar` / `/statusbar`); `─ ` prefix, `│`-separated segments, right-aligned cwd or session title.
- **What it does:** Shows live agent state, model, context usage and a long tail of optional readouts, shedding segments as the terminal narrows.
- **How it works:** `StatusRule` (`src/components/appChrome.tsx`). Width split by `statusRuleWidths(cols, cwdLabel, minLeftContent)`: separator is 3 cols at width ≥ 24 else 1; the left side reserves `essentialWidth` so the right (cwd/title) yields first. Breakpoints from `statusBarSegments(cols)`: `compactCtx: w<72`, `bar: w>=72`, `duration: w>=76`, `compressions: w>=80`, `voice: w>=84`, `bg: w>=88`, `subagents: w>=92`, `cacheHit: w>=96`, `latency: w>=104`, `tps: w>=110`. A `tailBudget` is consumed in priority order by `fits(w)`; whole segments drop, nothing truncates mid-segment.
- **Inputs / options:** Segments, in render order — `─ ` border; battery `⚡|🔋 NN%`; busy `FaceTicker` OR idle `status` text OR a credits `notice`; `(dev credits)` marker; `│ <model>`; `│ <ctx>`; `│ ◉ focus`; `│ [████░░░░░░] NN%`; `│ <session duration>`; `│ ✓ <idle since>`; `│ cmp N`; `│ ◎ NN%` (cache hit); `│ ◷ N.Ns` (avg latency); `│ ↑ N t/s`; `│ <voiceLabel>`; `│ N session(s)` (clickable); `│ N bg`; `│ ⛓ N`; `│ ↩ resumes when [N ]subagent[s] finish[es]`; `│ Δ N.N¢` (dev credits); ` │ ` + SpawnHud (`⏸ paused`, `d<depth>/<max>`, `⚡<widest>/<cap>+<extra>`, prefixed `⚠ ` at cap); then the right label.
- **Outputs / side effects:** Clicking the `N sessions` count opens the live session switcher (`onSessionCountClick` → `patchOverlayState({sessions:true})`).
- **Config / env:** `display.status_bar` position, `display.status_bar.fields` (a set filtering segment names `battery`, `context_detail`, `context_pct`, `title`, `duration`, `compressions`, `cache_hit`, `latency`, `tps`, `voice`, `bg_tasks`, `bg_subagents`; `null` = show everything), `display.tui_status_indicator`, `HERMES_DEV_CREDITS`.
- **Edge cases / guards:** Context bar color thresholds: `>=95` critical, `>80` bad, `>=50` warn, else good. Compressions color: `>=10` error, `>=5` warn. Cache-hit color: `>=70` good, `>=40` warn. Voice label color: leading `●` → error, `◉` → warn. The focus badge is deliberately pinned (never budget-dropped). `SpawnHud` renders last so overflow truncates the HUD, not the budgeted segments.
- **Rebuild notes:** Reserve essentials, then spend a tail budget in priority order; never truncate mid-segment. A better version would let the user reorder segments, not just hide them.

### Busy indicator styles (`kaomoji` / `emoji` / `unicode` / `ascii`)  `id: tui.indicator-styles`
- **Surface:** TUI / Config
- **Where:** the status rule's leftmost live slot; chosen with `/indicator <style>` or `display.tui_status_indicator`.
- **What it does:** Rotates a glyph (plus a verb and an elapsed clock) while the agent works.
- **How it works:** `renderIndicator(style, tick)` (`appChrome.tsx:49-77`). `kaomoji` cycles `FACES` every `FACE_TICK_MS = 2500`, shows the verb; `emoji` cycles `EMOJI_FRAMES = ['⚕ ','🌀','🤔','✨','🍵','🔮']` every `600 ms`, shows the verb; `ascii` cycles `['|','/','-','\\']` every `100 ms`, shows the verb; `unicode` uses `unicode-animations`' braille spinner at `max(100, spinner.interval)` and hides the verb. `FaceTicker` renders `frame + ' ' + padVerb(verb) + ' · ' + fmtDuration(now-startedAt)`; `padVerb` pads to `VERB_PAD_LEN = max(len(VERBS)) + 1` so the rest of the bar never jitters. Width reservation via `busyIndicatorWidth(style, hasDuration)`.
- **Inputs / options:** `/indicator kaomoji|emoji|unicode|ascii` (bare `/indicator` prints the current value).
- **Outputs / side effects:** `indicator → <style>` line; `display.tui_status_indicator` persisted; `patchUiState({indicatorStyle})` hot-swaps without waiting for the 5 s config mtime poll.
- **Config / env:** `display.tui_status_indicator` (default `kaomoji`).
- **Edge cases / guards:** All timers are disarmed while `$isStatusRuleOccluded` is true (a modal widget, or a floating panel growing up over a top-positioned rule) and re-seed `now` from the wall clock on reveal. A `verbOverride` of `'compacting'` freezes the verb during context compaction and forces the verb visible even in `unicode` style.
- **Rebuild notes:** Pre-measure the widest glyph and the widest verb at module load so the bar never reflows.

### Verb ticker vocabulary  `id: tui.verbs`
- **Surface:** TUI / Docs
- **Where:** the status rule while busy, e.g. `(⌐■_■) pondering…    · 12s`.
- **What it does:** Rotates a "thinking" verb every 2.5 s.
- **How it works:** `src/content/verbs.ts:22-38` — `VERBS = ['pondering','contemplating','musing','cogitating','ruminating','deliberating','mulling','reflecting','processing','reasoning','analyzing','computing','synthesizing','formulating','brainstorming']`. Rendered as `${verb}…` padded to `VERB_PAD_LEN`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Hidden in `unicode` indicator style unless a `verbOverride` is active.
- **Rebuild notes:** Keep the list to one word each and pad to the max width.

### Tool verbs map  `id: tui.tool-verbs`
- **Surface:** TUI
- **Where:** live tool rows, e.g. `reading src/foo.ts`.
- **What it does:** Maps tool names to present-participle verbs for the activity line.
- **How it works:** `src/content/verbs.ts:1-20` — `TOOL_VERBS = { browser:'browsing', clarify:'asking', create_file:'creating', delegate_task:'delegating', delete_file:'deleting', execute_code:'executing', image_generate:'generating', list_files:'listing', memory:'remembering', patch:'patching', read_file:'reading', run_command:'running', search_code:'searching', search_files:'searching', terminal:'terminal', web_extract:'extracting', web_search:'searching', write_file:'writing' }`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Unmapped tools fall back to the tool name.
- **Rebuild notes:** A data table, not a switch; unknown tools degrade to their id.

### Kaomoji face palette  `id: tui.faces`
- **Surface:** TUI
- **Where:** the busy indicator in `kaomoji` style (the default).
- **What it does:** Rotates 15 kaomoji every 2.5 s.
- **How it works:** `src/content/faces.ts:1-17` — `FACES = ['(｡•́︿•̀｡)','(◔_◔)','(¬‿¬)','( •_•)>⌐■-■','(⌐■_■)','(´･_･`)','◉_◉','(°ロ°)','( ˘⌣˘)♡','ヽ(>∀<☆)☆','٩(๑❛ᴗ❛๑)۶','(⊙_⊙)','(¬_¬)','( ͡° ͜ʖ ͡°)','ಠ_ಠ']`. `KAOMOJI_FRAME_WIDTH` is the max `stringWidth` measured once at module load.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.tui_status_indicator`.
- **Edge cases / guards:** Width is measured with a real wcwidth implementation, not `.length`.
- **Rebuild notes:** Measure display width of every frame up front; reserve the max.

### Long-run charms  `id: tui.charms`
- **Surface:** TUI
- **Where:** appended to the activity line when a tool call runs unusually long.
- **What it does:** Rotates reassurance copy during long tool calls.
- **How it works:** `src/content/charms.ts:1` — `LONG_RUN_CHARMS = ['still cooking…', 'polishing edges…', 'asking the void nicely…']`; scheduled by `src/app/useLongRunToolCharms.ts` (69 lines).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Only fires past a duration threshold in `useLongRunToolCharms.ts`.
- **Rebuild notes:** Time-gate the copy so it never appears on fast calls.

### Good-vibes heart  `id: tui.good-vibes-heart`
- **Surface:** TUI
- **Where:** a single `♥` flashed at the right edge of the composer input row.
- **What it does:** Momentary positive feedback: a heart in a random accent/warn/error color for 650 ms.
- **How it works:** `GoodVibesHeart({tick, t})` (`appChrome.tsx`) — a bump of `status.goodVibesTick` picks a random color from `[error, warn, accent]`, sets `active`, and clears it after `setTimeout(..., 650)`. Placed `position="absolute" right={0}` in the input row (`appLayout.tsx:440-442`).
- **Inputs / options:** n/a (driven by the app's own tick).
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** `tick <= 0` renders nothing.
- **Rebuild notes:** One-shot, self-clearing, no layout reflow (absolute position).

### Startup banner (logo + tagline)  `id: tui.banner`
- **Surface:** TUI
- **Where:** the first transcript row of every session (`intro` message kind).
- **What it does:** Paints the Hermes ASCII logo and tagline before the app finishes loading, so the terminal never looks frozen.
- **How it works:** `Banner` (`src/components/branding.tsx:103-191`) picks one of four tiers by available columns: `cols < HIDE_BELOW (34)` → nothing; `cols >= logoWidth + 2` → 6-row block-art logo (`LOGO_ART`, `src/banner.ts:46-53`) with a gradient `[0,0,1,1,2,2]` over `[primary, accent, border, muted]`, plus the tagline `<brand.icon> Nous Research · Messenger of the Digital Gods`; `cols >= COMPACT_FROM (58)` → `CompactBanner`, a 3-row `── <brand.name> ──` rule + centered tagline + a full-width `─` rule; otherwise a 2-row name+tagline where the name drops to its first word below 52 cols and the tagline degrades `TAG_FULL` (≥64) → `TAG_MID` `'Messenger of the Digital Gods'` (≥46) → `TAG_TINY` `'Nous Research'`. All tiers render through a single-column `WidgetGrid`. Custom art: `theme.bannerLogo` / `theme.bannerHero` strings are parsed by `parseRichMarkup()` (`src/banner.ts:5-44`) which understands `[#rrggbb]…[/]`, `[bold #rrggbb]…[/]`, `[dim #rrggbb]…[/]`.
- **Inputs / options:** none (terminal width drives it).
- **Outputs / side effects:** Display only.
- **Config / env:** skin keys `banner_logo`, `banner_hero`, `brand.name`, `brand.icon`, palette `primary`/`accent`/`border`/`muted`.
- **Edge cases / guards:** No `opaque` fill anywhere in the banner — opaque space-fills composite to black bars on transparent terminals; `CompactBanner`'s rules are deliberately NOT bold for the same reason.
- **Rebuild notes:** Four width tiers, gradient by row index, custom-art escape hatch with a tiny markup parser.

### Caduceus hero art  `id: tui.caduceus`
- **Surface:** TUI
- **Where:** left column of the session panel on wide terminals (≥ 90 cols).
- **What it does:** A 15-row braille-art caduceus, gradient-colored.
- **How it works:** `CADUCEUS_ART` (`src/banner.ts:55-71`), gradient `[2,2,1,1,0,0,1,1,2,2,3,3,3,3,3]` over `[primary, accent, border, muted]`; overridable with `theme.bannerHero`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** skin key `banner_hero`.
- **Edge cases / guards:** Hidden on narrow terminals; the model/cwd/session lines it carries move into the info column instead.
- **Rebuild notes:** Keep the hero optional and relocate the data it hosts when it is dropped.

### Session panel  `id: tui.session-panel`
- **Surface:** TUI
- **Where:** boxed panel under the banner at session start (`borderStyle="round"`).
- **What it does:** Summarises the live session: brand + version, model, cwd, session id, and four collapsible sections plus a footer count line.
- **How it works:** `SessionPanel` (`branding.tsx:212-510`). Layout: a `WidgetGrid` with `columns = wide ? [leftW, {fr:1}] : 1` and `gap = 2`, where `leftW = min(artWidth(hero)+4, floor(cols*0.4))` and `wide = cols >= 90 && leftW + 40 < cols`. Wide layout puts the hero + `<model> · Nous Research` + cwd + `Session: <sid>` on the left and centers `<brand.name> v<version> (<release_date>)` on the right; narrow layout hides the hero and repeats model/cwd/session at the top of the info column. Section bodies use `truncLine()` to fit `lineBudget = max(12, w-2)` and append `, …+N`. `strip()` removes a trailing `_tools` from toolset names. `listFade = mix(muted, text, 0.5)`.
- **Inputs / options:** Clickable accordion headers (see below).
- **Outputs / side effects:** Display only; collapse state is per banner instance (a new launch resets to defaults).
- **Config / env:** n/a.
- **Edge cases / guards:** Lazy boot — while `info.lazy` and the lists are empty the Tools section renders `ShimmerRows` shaped like the real content (`SKELETON_ROWS = [[7,30],[7,9],[14,12],[12,12],[7,7],[10,13]]`) and the Skills section an `InlineLoader` labelled `scanning skills`; the footer prints `… tools · … skills` instead of `0 tools · 0 skills`.
- **Rebuild notes:** Shape the skeleton like the real content so nothing pops when data lands.

### Session panel — `Available Tools` section  `id: tui.panel-tools`
- **Surface:** TUI
- **Where:** session panel, header `▾ Available Tools` (open by default).
- **What it does:** Lists enabled toolsets and their member tools.
- **How it works:** `toolsBody()` (`branding.tsx:288-307`): `Object.entries(info.tools).sort()`, first `TOOLSETS_MAX = 8` categories shown as `<name>: <comma list>`, then `(and N more toolsets…)`.
- **Inputs / options:** Click the header (or its `▾`/`▸` chevron) to toggle.
- **Outputs / side effects:** Display only.
- **Config / env:** the session's enabled toolsets.
- **Edge cases / guards:** Open by default because it is the most-checked section at session start.
- **Rebuild notes:** Cap the visible categories and say how many were hidden.

### Session panel — `Available Skills` section  `id: tui.panel-skills`
- **Surface:** TUI
- **Where:** session panel, header `▸ Available Skills (<total>) in <N> categor{y|ies}` (collapsed by default).
- **What it does:** Lists installed skills grouped by category, with a total count.
- **How it works:** `skillsBody()` (`branding.tsx:257-276`): first `SKILLS_MAX = 8` categories, then `(and N more categories…)`; `count` = `flat(info.skills).length`; `suffix` = `in N categor(y|ies)`.
- **Inputs / options:** Click to toggle.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Collapsed by default so dozens of skills don't bloat the banner.
- **Rebuild notes:** Count in the header, detail behind the chevron.

### Session panel — `System Prompt` section  `id: tui.panel-system-prompt`
- **Surface:** TUI
- **Where:** session panel, header `▸ System Prompt — <N,NNN> chars` (collapsed by default). Absent when the prompt is empty.
- **What it does:** Shows the full resolved system prompt.
- **How it works:** `systemBody()` (`branding.tsx:336-343`); `suffix` is `— ${len.toLocaleString()} chars`; empty renders `No system prompt loaded.`
- **Inputs / options:** Click to toggle.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Section is not rendered at all when `sysPromptLen === 0`.
- **Rebuild notes:** Make the exact prompt inspectable from the UI — it is the highest-value debugging surface.

### Session panel — `MCP Servers` section  `id: tui.panel-mcp`
- **Surface:** TUI
- **Where:** session panel, header `▸ MCP Servers (<connected>) connected` (collapsed by default). Absent when no servers are configured.
- **What it does:** Lists each MCP server with its transport and status.
- **How it works:** `mcpBody()` (`branding.tsx:310-332`): each row is `  <name> [<transport>]: ` followed by one of `<N> tool(s)` (connected, `text` color), `disabled` (muted, when `s.disabled || s.status === 'disabled'`), `connecting` (warn), `configured` (muted), or `failed` (error). Header count is `mcpServers.filter(s => s.connected).length` to match the classic CLI banner.
- **Inputs / options:** Click to toggle.
- **Outputs / side effects:** Display only.
- **Config / env:** MCP server config.
- **Edge cases / guards:** Counts CONNECTED servers, not configured-but-disabled ones.
- **Rebuild notes:** Five distinct states, each with its own color; never collapse `failed` and `disabled` into one.

### Session panel footer + update nag  `id: tui.panel-footer`
- **Surface:** TUI
- **Where:** last lines of the session panel.
- **What it does:** Prints `<N> tools · <N> skills[ · <N> MCP] · /help for commands`, plus an update warning and an install warning when applicable.
- **How it works:** `branding.tsx:452-490`. Update nag: `! <N> commit(s) behind - run <info.update_command || 'hermes update'> to update` in `theme.color.warn`. Install warning: `! <info.install_warning>` wrapped.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `info.update_behind`, `info.update_command`, `info.install_warning` from the gateway's session info.
- **Edge cases / guards:** During lazy boot the counts render as `…` rather than `0`.
- **Rebuild notes:** Put the single most useful next action (`/help`) in the footer of the first thing the user sees.

### Accordion primitive  `id: tui.accordion`
- **Surface:** TUI
- **Where:** session panel sections, widget-app accordions.
- **What it does:** The shared expand/collapse control: a clickable header with a `▾`/`▸` chevron, bold accent title, optional `(<count>)` and a muted suffix.
- **How it works:** `src/components/accordion.tsx`. Uncontrolled by default (`defaultOpen`), controlled when `open` is passed; `onToggle` fires either way. Header is a `<Box onClick={toggle}>` so mouse works even in ambient widgets that receive no keys.
- **Inputs / options:** props `children`, `count`, `defaultOpen`, `open`, `onToggle`, `suffix`, `t`, `title`; click anywhere on the header row.
- **Outputs / side effects:** Local (or parent) open state.
- **Config / env:** n/a.
- **Edge cases / guards:** In controlled mode the internal state is not touched.
- **Rebuild notes:** One primitive, both controlled and uncontrolled — otherwise every consumer reinvents chevrons.

### Panel renderer (`transcript.panel`)  `id: tui.panel-renderer`
- **Surface:** TUI
- **Where:** boxed output for `/help`, `/usage`, `/mem`, `/theme-info`, `/skills`, `/rollback`, `/replay`, etc.
- **What it does:** Renders a titled, bordered panel of sections, each with an optional title and any of `rows` (key/value, key padded to 20), `items` (plain lines) or `text` (muted paragraph).
- **How it works:** `Panel` (`branding.tsx:512-548`), `borderStyle="round"`, `paddingX={2} paddingY={1}`, centered bold `primary` title.
- **Inputs / options:** `PanelSection = { title?, rows?: [string,string][], items?: string[], text?: string }`.
- **Outputs / side effects:** A `panel`-kind transcript message.
- **Config / env:** n/a.
- **Edge cases / guards:** Rows use `wrap="truncate"`, so long values clip rather than reflow.
- **Rebuild notes:** One panel shape covering k/v, list and prose keeps every command's output consistent.

### `?` quick-help popover  `id: tui.help-hint`
- **Surface:** TUI
- **Where:** floats above the composer the moment the composer contains exactly `?` and no continuation lines. Header text: `? quick help  ·  type /help for the full panel  ·  backspace to dismiss`.
- **What it does:** A cheat-sheet popover with six common commands and the first eight hotkeys.
- **How it works:** `src/components/helpHint.tsx`; rendered from `appLayout.tsx:383` when `composer.input === '?' && !composer.inputBuf.length`. `COMMON_COMMANDS` (verbatim): `/help` `full list of commands + hotkeys`; `/clear` `start a new session`; `/resume` `switch live or resume past sessions`; `/details` `control transcript detail level`; `/copy` `copy selection or last assistant message`; `/quit` `exit hermes`. `HOTKEY_PREVIEW = HOTKEYS.slice(0, 8)`. Labels are padded to `max(label widths) + 2`.
- **Inputs / options:** type `?`; press Backspace to dismiss.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Absolutely positioned `bottom="100%"` with `opaque` so it paints over the transcript.
- **Rebuild notes:** A single-character discoverability affordance beats a hidden keybinding.

### Composer (prompt input)  `id: tui.composer`
- **Surface:** TUI
- **Where:** bottom block: queued messages → background-task line → sticky prompt → status rule (top position) → ambient dock → floating overlays → input rows → ambient dock (bottom) → status rule (bottom position).
- **What it does:** The text entry surface: prompt glyph, multi-line buffer, placeholder, completions, paste handling, mouse drag selection.
- **How it works:** `ComposerPane` (`appLayout.tsx:274-454`). Prompt text from `composerPromptText(theme.brand.prompt, info.profile_name, isShell, TERMUX_TUI_MODE, cols)` (`src/lib/prompt.ts`); width from `composerPromptWidth()`; input columns from `stableComposerColumns(cols, promptWidth, TERMUX_TUI_MODE)`; height from `inputVisualHeight(input, columns)` (all in `src/lib/inputMetrics.ts`). Continuation lines (`composer.inputBuf`) render above the live row with a blank prompt gutter. The prompt glyph is `theme.color.shellDollar` when the line starts with `!`, `theme.color.prompt` (bold) otherwise.
- **Inputs / options:** Everything in §2; plus `composer.updateInput`, `composer.handleTextPaste`, `composer.submit`, `composer.attachImagePath`, `composer.attachClipboardImage`, `composer.enqueue`, `composer.dequeue`, `composer.openEditor`, `composer.setInput`.
- **Outputs / side effects:** Prompt submission → `prompt.send` RPC; attachments; queue mutations.
- **Config / env:** `display.prompt` glyph/color via skins, `voice.record_key`.
- **Edge cases / guards:** Hidden entirely while `$isBlocked` (an overlay owns input). The whole block is wrapped in `NoSelect` so drag selection there is composer-local, not transcript selection.
- **Rebuild notes:** Compute prompt width and stable columns once per render so typing never rewraps.

### Composer placeholder rotation  `id: tui.placeholders`
- **Surface:** TUI
- **Where:** greyed text in the empty composer.
- **What it does:** Shows one randomly-picked hint per process.
- **How it works:** `src/content/placeholders.ts` — `PLACEHOLDERS = ['Ask me anything…', 'Try "explain this codebase"', 'Try "write a test for…"', 'Try "refactor the auth module"', 'Try "/help" for commands', 'Try "fix the lint errors"', 'Try "how does the config loader work?"']`; `PLACEHOLDER = pick(PLACEHOLDERS)` is evaluated once at module load. While busy the placeholder becomes `Ctrl+C to interrupt…` (`appLayout.tsx:428`). Placeholder color is `theme.color.muted` (deliberately a mid-luminance tone so it reads receded on both light and dark, even when polarity detection is wrong).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Picked once per launch, so it does not flicker between renders.
- **Rebuild notes:** Pick at module load, not per render.

### Queued messages panel  `id: tui.queued-messages`
- **Surface:** TUI
- **Where:** directly above the composer; header `queued (<N>)` and, while editing, `queued (<N>) · editing <i> · Ctrl+X delete · Esc cancel`.
- **What it does:** Shows messages typed while the agent was busy, with a 3-row scroll window and an editable selection.
- **How it works:** `src/components/queuedMessages.tsx`. `QUEUE_WINDOW = 3`; `getQueueWindow(len, editIdx)` centres the window on the edited item (`start = clamp(editIdx-1, 0, len-3)`) and reports `showLead` / `showTail`. Rows render `▸ <n>. <compactPreview(item, max(16, cols-10))>` with the active row in `theme.color.accent`; lead is ` …`, tail is `  …and N more`. Queue state lives in `src/hooks/useQueue.ts`.
- **Inputs / options:** `↑`/`↓` to cycle, `Ctrl+X` to delete the highlighted one, `Esc` to cancel editing, `Cmd/Ctrl+K` to flush the head, `/queue [text]` (alias `/q`) to inspect or enqueue.
- **Outputs / side effects:** Queue array mutations; on session-ready the head is dispatched.
- **Config / env:** `busy` input mode (`/busy queue|steer|interrupt`) decides what Enter does while busy.
- **Edge cases / guards:** Renders nothing when the queue is empty. The window keeps the edited item visible without changing the panel height; `Ctrl+X` is destructive, so it is named in the header while an edit is active.
- **Rebuild notes:** Windowed list with lead/tail markers; make the destructive key visible in the header.

### Background-task counter line  `id: tui.bg-tasks-line`
- **Surface:** TUI
- **Where:** above the composer, `<N> background task[s] running`.
- **What it does:** Reminds you that `/bg` prompts are still executing.
- **How it works:** `appLayout.tsx:350-354` renders when `ui.bgTasks.size > 0`; the set is filled by `/bg` (`patchUiState(state => ({...state, bgTasks: new Set(state.bgTasks).add(task_id)}))`) and drained by gateway events.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only; the status rule also shows `│ N bg`.
- **Config / env:** n/a.
- **Edge cases / guards:** Singular/plural handled.
- **Rebuild notes:** Track task ids in a set so the count is exact after out-of-order completions.

### Session-not-ready hint  `id: tui.not-ready-hint`
- **Surface:** TUI
- **Where:** below the composer, `⚕ <status>` — e.g. `⚕ summoning hermes…`, `⚕ forging session…`, `⚕ starting agent…`.
- **What it does:** Explains why a typed message hasn't sent yet.
- **How it works:** `appLayout.tsx:448` renders when `!composer.empty && !ui.sid`. Initial status is `'summoning hermes…'` (`src/app/uiStore.ts:394`); other documented values are `starting agent…`, `ready`, `thinking…`, `running…`, `interrupted`, `forging session…`, `resuming…` (`website/docs/user-guide/tui.md:204-211`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Only shown while there is unsent text AND no session id.
- **Rebuild notes:** Never block input on readiness; explain the wait instead.

### Masked prompt (password / secret entry)  `id: tui.masked-prompt`
- **Surface:** TUI
- **Where:** in the PromptZone above the composer, when the agent asks for a sudo password or a secret.
- **What it does:** Reads a value without echoing it.
- **How it works:** `src/components/maskedPrompt.tsx` — bold `theme.color.warn` line `<icon> <label>`, optional muted `sub` line, then a `> ` prefix and a `<TextInput mask="*" columns={max(20, cols-6)}>`.
- **Inputs / options:** props `cols`, `icon`, `label`, `onSubmit`, `sub`, `t`; type + Enter to submit.
- **Outputs / side effects:** `sudo.respond {password, request_id}` or `secret.respond {request_id, value}`.
- **Config / env:** n/a.
- **Edge cases / guards:** `Esc` or `Ctrl+C` cancels via `dismissSensitivePrompt()`, which sends an EMPTY value and prints `sudo cancelled` / `secret entry cancelled` so the backend is never left waiting.
- **Rebuild notes:** Always answer the pending request on cancel; a masked prompt that just disappears deadlocks the agent.

### Ambient rails and docks  `id: tui.ambient`
- **Surface:** TUI
- **Where:** left/right vertical rails beside the transcript, and horizontal docks above (`dock-top`) and below (`dock-bottom`) the composer.
- **What it does:** Placement slots for widget-SDK apps and ambient alerts that reserve their own space instead of covering content.
- **How it works:** `AmbientRail side="left"|"right"`, `AmbientDock placement="dock-top"|"dock-bottom"`, `useAmbientRailWidth(side)` (all from `src/sdk/host.tsx`). Rail width is subtracted from the transcript's `bodyCols`. Rails are unmounted while the agents or journey overlay owns the screen.
- **Inputs / options:** a widget app declares its placement.
- **Outputs / side effects:** Layout reservation.
- **Config / env:** n/a.
- **Edge cases / guards:** `ambient` overlays are excluded from `$isStatusRuleOccluded` because they reserve rows rather than covering them.
- **Rebuild notes:** Distinguish "reserves space" from "covers content" — the timer-gating logic depends on it.

### Pet pane (Petdex mascot)  `id: tui.pet-pane`
- **Surface:** TUI
- **Where:** floating in the bottom-right corner, 3 rows above the screen bottom (over the composer).
- **What it does:** Renders an animated pet sprite that reserves no layout rows but keeps transcript text clear of itself.
- **How it works:** `PetPane` (`appLayout.tsx:57-111`). Geometry constants `PET_BOTTOM = 3`, `PET_PAD_LEFT = 2`, `PET_RIGHT = 1`, `PET_GUTTER_GAP = 1`. `usePet()` (`src/app/usePet.ts`, 352 lines) supplies `{enabled, grid, kitty}`; for kitty-protocol images the footprint counts real placeholder cells (`KITTY_PLACEHOLDER = '\u{10eeee}'`) because zero-width diacritics make `String.length` lie. The footprint is published to `$petBox` (`src/app/petFlashStore.ts`) so `TranscriptPane` can choose a right gutter (wide) or a reserved bottom band (narrow). Rendered in a `NoSelect position="absolute"` box; `PetKitty` or `PetSprite` (half-block grid) from `src/components/petSprite.tsx`. Polling logic in `src/lib/petPolling.ts`.
- **Inputs / options:** `/pet` (toggle), `/pet list` (gallery picker), `/pet scale <n>`, `/pet <slug>` (adopt).
- **Outputs / side effects:** `display.pet.enabled` and pet selection persisted via the slash worker.
- **Config / env:** `display.pet.*`.
- **Edge cases / guards:** Renders nothing unless a pet is installed AND enabled AND its footprint is non-zero. Unmounted while the agents overlay is open.
- **Rebuild notes:** Publish the overlay's footprint to a store so the text layout can avoid it without the overlay participating in flex layout.

---

## 4. Prompt zone (in-flow modal prompts)

The PromptZone renders ONE prompt at a time, above the composer, in normal flow (it pushes content
down, it does not cover it). Priority order in `src/components/appOverlays.tsx:58-168`:
`approval` → `billing` → `subscription` → `confirm` → `clarify` → `sudo` → `secret`.
Each is wrapped in a `PromptCell` — a single-cell `WidgetGrid` with `paddingX=1 paddingY=1`.

### Approval prompt  `id: tui.prompt-approval`
- **Surface:** TUI
- **Where:** PromptZone; double-bordered box in `theme.color.warn`. Header: `⚠ approval required · <description>`.
- **What it does:** Asks permission before a guarded tool call runs, showing the exact command.
- **How it works:** `ApprovalPrompt` (`src/components/prompts.tsx:84-144`). The command is split on newlines, each line hard-wrapped with `wrapAnsi(line, max(20, cols-8), {hard:true, trim:false})`, and the first `CMD_PREVIEW_LINES = 10` shown; the rest becomes `… +N more line(s) (full text above)`. Options come from `approvalOptions(req)` (`prompts.tsx:21-31`): `req.choices` filtered to the known set, else `['once','deny']` when `req.smartDenied`, else `['once','session','deny']` when `req.allowPermanent === false` (a tirith warning downgrades "always" to session scope), else the full `['once','session','always','deny']`. Labels (verbatim): `Allow once`, `Allow this session`, `Always allow`, `Deny`. Key dispatch is the pure `approvalAction(ch, key, sel, opts)` (`prompts.tsx:53-82`).
- **Inputs / options:** `↑`/`↓` move; `Enter` confirms; digits `1`..`N` quick-pick; `Esc` = deny; `Ctrl+C` = deny (via the global `cancelOverlayFromCtrlC`). Footer hint verbatim: `↑/↓ select · Enter confirm · 1-<N> quick pick · Esc/Ctrl+C deny`.
- **Outputs / side effects:** `approval.respond {choice, session_id}`; on deny the turn store records `outcome: 'denied'`.
- **Config / env:** approval policy config; `/yolo` and `Shift+Tab` bypass approvals entirely.
- **Edge cases / guards:** The full command must be reviewable — wrapping rather than truncating is deliberate. Scroll keys fall through so the user can read the transcript above the prompt.
- **Rebuild notes:** Keep key dispatch pure and testable; never truncate the thing the user is being asked to authorise.

### Clarify prompt — single question  `id: tui.prompt-clarify`
- **Surface:** TUI
- **Where:** PromptZone; heading `ask <question>` (the word `ask` in `theme.color.accent`).
- **What it does:** Lets the agent ask a multiple-choice or free-text question mid-turn.
- **How it works:** `ClarifyPrompt` (`prompts.tsx:146-415`). With choices it renders `[...choices, 'Other (type your answer)']` as numbered chip rows; selecting the last row (or having no choices at all) switches to a `TextInput` with a `> ` prefix.
- **Inputs / options:** `↑`/`↓` select; `Enter` confirm (or enter typing mode on `Other`); digits `1`..`N` quick-pick; `Esc` exits typing mode, or cancels; `Ctrl+C` cancels (answers `''`). Hints verbatim: choices mode `↑/↓ select · Enter confirm · 1-<N> quick pick · Esc/Ctrl+C cancel`; typing mode `Enter send · Esc back|cancel · ` + (macOS) `Cmd+C copy · Cmd+V paste · Ctrl+C cancel` / (other) `Ctrl+C cancel`.
- **Outputs / side effects:** `clarify.respond`.
- **Config / env:** n/a.
- **Edge cases / guards:** A cancel sends an empty answer so the agent is not left waiting.
- **Rebuild notes:** Always offer an `Other` escape hatch on a choice prompt.

### Clarify prompt — batch questions  `id: tui.prompt-clarify-batch`
- **Surface:** TUI
- **Where:** PromptZone; heading `ask <N> questions`, then a status list with one expanded active question, then `<answered>/<total> answered · <hint>`.
- **What it does:** Asks several questions at once, answerable in any order, with per-question locking.
- **How it works:** `ClarifyPrompt` batch branch (`prompts.tsx:307-373`). `active` walks `req.questions`; `sel` is the cursor inside the active question's choices. Markers: `✓` answered, `▸` active, `·` pending. A locked answer prints on its own indented line in `theme.color.ok`, or italic muted `(skipped)` when empty. `moveActive(delta)` wraps and restores prior state via `clarifyBatchRevisitState(choices, answer)` (`src/lib/text.ts`) — a choice answer puts the cursor back on its row, a typed answer lands on `Other` with the text staged so Enter edits it. A `useEffect` keyed on `req.answers` jumps to the next unanswered question after each lock.
- **Inputs / options:** `Tab` / `Shift+Tab` cycle questions; `↑`/`↓` select within the active question; `Enter` lock; digits quick-pick; `Esc` back/cancel. Hints verbatim: typing → `Enter <confirm and continue|lock answer> · Esc back`; otherwise → `↑/↓ select · Enter <confirm and continue|lock answer> · Tab/Shift+Tab switch question · Esc/Ctrl+C cancel` (the singular phrasing kicks in when exactly one question remains).
- **Outputs / side effects:** `clarify.respond` with a `question_id` per lock; the overlay is re-patched with the updated answers map.
- **Config / env:** n/a.
- **Edge cases / guards:** Open-ended questions (no choices) start typing on any keypress.
- **Rebuild notes:** Let the user answer in any order and re-edit; jump to the next unanswered only when the current one is done.

### Confirm prompt  `id: tui.prompt-confirm`
- **Surface:** TUI
- **Where:** PromptZone; double-bordered box in `theme.color.error` (danger) or `theme.color.warn`. Header `⚠ <title>` or `? <title>`.
- **What it does:** A yes/no gate for destructive local actions (`/clear`, `/new`, expensive model switch).
- **How it works:** `ConfirmPrompt` (`prompts.tsx:417-477`). Row 0 is the cancel label (default `No`), row 1 the confirm label (default `Yes`); selection starts on cancel.
- **Inputs / options:** `↑` selects cancel, `↓` selects confirm, `Enter` runs the selected row, `y` confirms, `n` cancels, `Esc` / `Ctrl+C` cancel. Footer hint verbatim: `↑/↓ select · Enter confirm · Y/N quick · Esc cancel`. Known instances: `/clear` → title `Clear the current session?`, confirm `Yes, clear the session`, cancel `No, keep going`, detail `This ends the current conversation and clears the transcript.`; `/new` → title `Start a new session?`, confirm `Yes, start a new session`; expensive-model switch → title `Expensive model selection`, confirm `Switch anyway`, cancel `Cancel`, detail from `r.confirm_message || r.warning || 'This model has unusually high known pricing.'`.
- **Outputs / side effects:** Runs `req.onConfirm()`; the overlay clears either way.
- **Config / env:** `HERMES_TUI_NO_CONFIRM` (`NO_CONFIRM_DESTRUCTIVE`) and `ui.destructiveSlashConfirm` skip the gate entirely.
- **Edge cases / guards:** Detail text uses `wrap="truncate-end"`.
- **Rebuild notes:** Default the selection to the SAFE row.

### Sudo password prompt  `id: tui.prompt-sudo`
- **Surface:** TUI
- **Where:** PromptZone; `🔐 sudo password required`.
- **What it does:** Collects a sudo password for a privileged command without echoing it.
- **How it works:** `MaskedPrompt` with `icon="🔐"`, `label="sudo password required"` (`appOverlays.tsx:144-150`); submit → `onSudoSubmit`.
- **Inputs / options:** type + `Enter`; `Esc` / `Ctrl+C` cancel.
- **Outputs / side effects:** `sudo.respond {password, request_id}`; cancel sends `password: ''` and prints `sudo cancelled`.
- **Config / env:** n/a.
- **Edge cases / guards:** Masked with `*`.
- **Rebuild notes:** Never log or echo; always answer the request on cancel.

### Secret entry prompt  `id: tui.prompt-secret`
- **Surface:** TUI
- **Where:** PromptZone; `🔑 <overlay.secret.prompt}` with a muted sub-line `for <envVar>`.
- **What it does:** Collects a missing API key / secret for an environment variable the agent needs.
- **How it works:** `MaskedPrompt` with `icon="🔑"`, `label = overlay.secret.prompt`, `sub = "for " + overlay.secret.envVar` (`appOverlays.tsx:152-164`).
- **Inputs / options:** type + `Enter`; `Esc` / `Ctrl+C` cancel.
- **Outputs / side effects:** `secret.respond {request_id, value}`; cancel sends `value: ''` and prints `secret entry cancelled`.
- **Config / env:** the secret lands wherever the backend stores it (typically `~/.hermes/.env`; `/reload` re-reads it).
- **Edge cases / guards:** Masked with `*`.
- **Rebuild notes:** Show WHICH env var is being filled — otherwise the user cannot tell what they are typing into.

---

## 5. Floating overlays (above the composer)

`FloatingOverlays` (`src/components/appOverlays.tsx:170-389`) renders every open floating panel plus
the completion menu into a single-column `WidgetGrid` inside an
`position="absolute" bottom="100%" left={0} right={0}` box, so the stack grows UPWARD over the
transcript. The panel set is `hasFloatingPanel(overlay)` = `modelPicker || pager || petPicker ||
pluginsHub || sessions || skillsHub` (`src/app/overlayStore.ts:535-543`). Each panel sits in a
`FloatBox` — an `alignSelf="flex-start"`, `borderStyle="double"`, `opaque`, `paddingX={1}`,
`marginTop={1}` box (`appChrome.tsx`).

### Slash / argument completion menu  `id: tui.completions`
- **Surface:** TUI
- **Where:** floating panel above the composer, bordered in `theme.color.primary`.
- **What it does:** A two-column dropdown of matching commands/arguments with descriptions.
- **How it works:** `appOverlays.tsx:328-382`. `COMPLETION_WINDOW = 16`; the viewport is FIXED at `min(16, completions.length)` and centred on `compIdx` (`start = clamp(compIdx - 8, 0, len - viewportSize)`) so the dropdown height never bounces per keystroke. The name track auto-sizes to `max(stringWidth(item.display)) + 2` so descriptions align and wrapped description lines stay in their own column. Only the ACTIVE row carries a background chip (`listRowStyle(theme, active)`); descriptions use `theme.color.statusFg` (a neutral gray) when inactive. Row keys include text+display+meta so identical labels don't collide. Completion fetching lives in `src/hooks/useCompletion.ts` and the gateway's `complete.*` methods; ranking uses `rankSlashItems` / `scoreSlashMenuItem` (`src/app/slash/fuzzyScore.ts`).
- **Inputs / options:** `↑`/`↓` cycle (wrap-around); `Tab` applies; `Enter` applies only when it changes the command/argument token (`completionToApplyOnSubmit`, `src/domain/slash.ts:272-284`) — a completion that only appends trailing whitespace does NOT swallow Enter.
- **Outputs / side effects:** Composer value replacement.
- **Config / env:** n/a.
- **Edge cases / guards:** Inline `/skill` references anywhere in prose are completed too — `inlineSlashTrigger()` (`src/domain/slash.ts:224-234`) matches `/\s\/([a-zA-Z][\w-]*)?$/`, deliberately refusing a second `/` so real paths (`/usr/local/bin`, `src/foo/bar`) never trigger it.
- **Rebuild notes:** Fixed-height viewport centred on the cursor; two-column grid; a whitespace-only delta must not consume Enter.

### Pager overlay  `id: tui.pager`
- **Surface:** TUI
- **Where:** floating panel, optional centered bold title, page of lines, then a hint line.
- **What it does:** Pages long command output (`transcript.page(text, title)`) — used by `/status`, `/history`, `/logs`, `/rollback diff`, `/skills`, `/plugins`, `/tools`, and any slash-worker output longer than 180 chars or 2 non-empty lines.
- **How it works:** `appOverlays.tsx:295-326` renders `pager.lines.slice(offset, offset + pagerPageSize)`. `pagerPageSize = max(5, (stdout.rows ?? 24) - 6)` (`useInputHandlers.ts:176`). Key handling is in the global handler (`useInputHandlers.ts:411-469`).
- **Inputs / options:** `↑` / `k` line up; `↓` / `j` line down; `PageUp` / `b` page back; `Enter` / `Space` / `PageDown` page forward (and CLOSE when already at the last page); `g` top; `G` bottom; `Esc` / `q` / `Ctrl+C` close. Hint (verbatim, mid-document): `↑↓/jk line · Enter/Space/PgDn page · b/PgUp back · g/G top/bottom · Esc/q close (<shown>/<total>)`; at the end: `end · ↑↓/jk · b/PgUp back · g top · Esc/q close (<total> lines)`.
- **Outputs / side effects:** Overlay state only.
- **Config / env:** n/a.
- **Edge cases / guards:** Paging forward clamps to `max` rather than overshooting, so the next `↑`/`PgUp` doesn't snap back.
- **Rebuild notes:** less(1)-compatible keys; auto-close on the last page is the affordance people expect.

### Live session switcher  `id: tui.session-switcher`
- **Surface:** TUI
- **Where:** floating panel. Opened by `Ctrl+X`, `/sessions`, `/switch`, `/session`, `/resume`, or clicking the `N sessions` count in the status line.
- **What it does:** Lists live TUI sessions in this process, switches/closes them, starts new ones, and can dispatch a brand-new session with a prompt and a chosen model.
- **How it works:** `src/components/activeSessionSwitcher.tsx` (917 lines), mounted from `appOverlays.tsx:219-239` with `currentSessionId`, `gw`, `maxWidth` and callbacks `onCancel`, `onClose`, `onNew`, `onNewPrompt`, `onResume`, `onSelect`.
- **Inputs / options:** `↑`/`↓` move (mouse clicks select rows too); `Enter` switch to the selected live session; `Ctrl+D` close the selected live session; `Ctrl+N` start a blank live session; `Ctrl+R` refresh the live-session list; `Esc` close; select the `+new` row, type a prompt and press `Enter` to dispatch a new live session; press `Tab` first to choose a model just for that new session (`website/docs/user-guide/tui.md:145-153`).
- **Outputs / side effects:** Session activation/closure; a new session may be created and immediately prompted.
- **Config / env:** n/a.
- **Edge cases / guards:** Lists ONLY sessions live in this TUI process; closed sessions remain saved transcripts reachable via `/resume` or `hermes --tui --resume <id-or-title>`. Switching to a COLD session (`/resume <id>`) closes the current one and is refused while a turn is in flight (`guardBusySessionSwitch('switch sessions')`); creating a new LIVE session is allowed while busy because it does not close anything.
- **Rebuild notes:** Separate "fan out a new live session" (always allowed) from "load a cold session" (guarded) — they have different safety properties.

### Model picker  `id: tui.model-picker`
- **Surface:** TUI
- **Where:** floating panel. Opened by `Ctrl+O`, `/model` (bare), or `/model --refresh`.
- **What it does:** A modal picker of models grouped by provider with cost hints and search.
- **How it works:** `src/components/modelPicker.tsx` (710 lines), mounted from `appOverlays.tsx:241-260` with `gw`, `initialRefresh` (true when the overlay state is `{refresh:true}`), `maxWidth`, `onCancel`, `onSelect`, `sessionId`. Search text normalisation in `src/lib/model-search-text.ts`.
- **Inputs / options:** see `tui.model-picker-keys`.
- **Outputs / side effects:** `config.set {key:'model', session_id, value, confirm_expensive_model}`; mid-turn the gateway queues it and returns `deferred: true` → `model → <value> (applies next turn)`.
- **Config / env:** `model`, provider credential config.
- **Edge cases / guards:** An unusually expensive model returns `confirm_required` with `confirm_message`/`warning` and routes through the confirm prompt; re-issued with `confirm_expensive_model: true`.
- **Rebuild notes:** Group by provider, show price, and never block the picker on a running turn.

### Pet picker (gallery)  `id: tui.pet-picker`
- **Surface:** TUI
- **Where:** floating panel; opened by `/pet list`.
- **What it does:** Browses the available pet sprites and adopts one.
- **How it works:** `src/components/petPicker.tsx` (187 lines), mounted from `appOverlays.tsx:262-271` with `gw`, `maxWidth`, `onClose`.
- **Inputs / options:** arrow navigation + Enter to adopt; `Esc` / `Ctrl+C` / `q` close.
- **Outputs / side effects:** Persists the chosen pet via the gateway; `PetPane` re-renders.
- **Config / env:** `display.pet.*`.
- **Edge cases / guards:** Closed by the global Ctrl+C walker.
- **Rebuild notes:** Preview the sprite in the picker, not just its name.

### Skills hub  `id: tui.skills-hub`
- **Surface:** TUI
- **Where:** floating panel; opened by bare `/skills`.
- **What it does:** Interactive browse/inspect/install surface for skills.
- **How it works:** `src/components/skillsHub.tsx` (301 lines), mounted from `appOverlays.tsx:273-282` with `gw`, `maxWidth`, `onClose`. Backed by the `skills.manage` RPC (`action: 'list'|'inspect'|'search'|'install'|'browse'`).
- **Inputs / options:** arrow/Enter navigation; `Esc` / `q` close (`useOverlayKeys`).
- **Outputs / side effects:** Skill installs write to the skills directory; `/reload-skills` re-scans.
- **Config / env:** skills config.
- **Edge cases / guards:** `/skills <sub>` with an argument bypasses the hub and goes to the typed sub-commands or the slash worker.
- **Rebuild notes:** Make the hub the no-argument default and keep the scriptable text sub-commands.

### Plugins hub  `id: tui.plugins-hub`
- **Surface:** TUI
- **Where:** floating panel; opened by bare `/plugins`.
- **What it does:** View and toggle plugins interactively.
- **How it works:** `src/components/pluginsHub.tsx` (241 lines), mounted from `appOverlays.tsx:284-293`.
- **Inputs / options:** arrow/Enter navigation and toggle; `Esc` / `q` close.
- **Outputs / side effects:** Plugin enable/disable persisted.
- **Config / env:** plugin config.
- **Edge cases / guards:** Any `/plugins <sub>` (enable/disable/list/install/…) falls through to the text slash worker for parity with `hermes plugins`.
- **Rebuild notes:** Keep the interactive hub and the scriptable CLI at parity.

### Billing overlay (`/topup`)  `id: tui.billing-overlay`
- **Surface:** TUI
- **Where:** PromptZone (in-flow, not floating). Opened by `/topup`.
- **What it does:** Shows the Nous balance and drives add-funds, auto-reload and spending-limit flows in-terminal.
- **How it works:** `src/components/billingOverlay.tsx` (950 lines) rendered by `appOverlays.tsx:80-93`. All RPC + error mapping lives in `buildOverlayCtx()` (`src/app/slash/commands/topup.ts:493-564`), which supplies `applyAutoReload(enabled, threshold, topUp)` → `billing.auto_reload`; `charge(amount, idempotencyKey)` → `billing.charge` then `pollCharge()`; `requestRemoteSpending()` → `billing.step_up`; `openPortal(url)`; `refreshState()` → `billing.state`; `sys`; `validate(raw)` → `validateAmount()`. Screens are driven by `overlay.billing.screen` (starts at `'overview'`) and `pendingCharge`.
- **Inputs / options:** overlay-local key routing (the overlay only renders + routes keys); a custom amount is typed and validated.
- **Outputs / side effects:** Real money movement via `billing.charge`; settlement is polled through `driveChargeSettlement()` from `@hermes/shared/charge-settlement`.
- **Config / env:** Nous portal login (`/portal`), `billing.*` server-side state.
- **Edge cases / guards:** Not logged in → `💳 Not logged into Nous Portal — run /portal to log in, then /topup.` See `tui.billing-errors` and `tui.charge-settlement` for the full message tables.
- **Rebuild notes:** Keep every RPC and every error string in the command module, not the view — the view should be a pure renderer.

### Billing amount validation  `id: tui.billing-validate`
- **Surface:** TUI
- **Where:** the custom-amount field in the billing overlay.
- **What it does:** Client-side mirror of the server's amount rules.
- **How it works:** `validateAmount(raw, state)` (`topup.ts:464-486`): strips a leading `$` and whitespace, requires `/^\d+(\.\d{1,2})?$/`, requires `> 0`, and enforces `state.min_usd` / `state.max_usd`.
- **Inputs / options:** any string.
- **Outputs / side effects:** Either `{amount}` or `{error}`.
- **Config / env:** `min_usd`, `max_usd` from `billing.state`.
- **Edge cases / guards:** Error strings verbatim: `Enter a dollar amount, e.g. 100 (max 2 decimal places).`; `Amount must be greater than $0.`; `Minimum is $<min>.`; `Maximum is $<max>.`
- **Rebuild notes:** Validate client-side for latency, but treat the server as authoritative.

### Billing error copy  `id: tui.billing-errors`
- **Surface:** TUI
- **Where:** transcript lines emitted from the billing/subscription flows.
- **What it does:** Maps typed billing error envelopes onto user-facing copy and a portal funnel.
- **How it works:** `renderBillingError(sys, ctx, env)` (`topup.ts:197-331`) switches on `env.error`. Verbatim mapping:
  - `insufficient_scope` → `This needs Remote Spending allowed. Start a top-up to allow it, then retry.`
  - `remote_spending_revoked` → closes the billing overlay immediately, then `An admin stopped remote spending for this terminal.` (when `env.actor === 'admin'`) or `You stopped remote spending for this terminal.`, followed by ` Reconnect to restore — run /portal to re-authorize this terminal.`
  - `session_revoked` → closes the overlay, `Your session was logged out. Run /portal to log in again.`
  - `cli_billing_disabled` / `remote_spending_disabled` → `Remote spending is off for this account — a billing admin can turn it on from the portal's Hermes Agent page.`
  - `role_required` → `Adding funds needs someone with billing permissions (owner, admin, or finance admin), or manage this on the portal.`
  - `consent_required` → `This action needs a one-time card confirmation and consent step on the portal before it can proceed.`
  - `org_access_denied` → `This token isn't bound to an org you can manage. Sign in with the right org, or manage this on the portal.`
  - `upgrade_cap_exceeded` → `🔴 Daily plan-change limit reached (5 per org) — try again tomorrow, or manage this on the portal.`
  - `auto_top_up_disabled_failures` → `Auto-reload was turned off after repeated charge failures. Fix the card issue, then re-enable it from /topup → Auto-reload.`
  - `idempotency_conflict` → `🔴 That charge key was already used for a different amount. Start a fresh top-up.`
  - `no_payment_method` → `💳 No saved card for terminal charges yet. Set one up on the portal (one-time credit buys don't save a reusable card).`
  - `monthly_cap_exceeded` → `🔴 Monthly spend cap reached — $<remainingUsd> headroom left.` or `🔴 Monthly spend cap reached.`
  - `rate_limited` / `temporarily_unavailable` → `🟡 Too many charges right now (try again in ~<N> min). This isn't a payment failure.`
  - `stripe_unavailable` → `🟡 Stripe is having trouble right now — try again shortly (try again in ~<N> min).`
  - default → `🔴 <message || error || 'Billing request failed.'>`
  Any envelope carrying `portal_url` also emits `Portal: <url>`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Transcript lines; two codes also force the overlay closed.
- **Config / env:** n/a.
- **Edge cases / guards:** The raw `billing:manage` scope name is never surfaced — the user-facing concept is "Remote Spending".
- **Rebuild notes:** Type the errors on the wire and keep one exhaustive switch; a default arm keeps new server codes visible.

### Charge settlement polling  `id: tui.charge-settlement`
- **Surface:** TUI
- **Where:** transcript lines after `/topup` submits a charge.
- **What it does:** Polls the charge to a terminal state and reports it.
- **How it works:** `pollCharge(sys, ctx, chargeId, portalUrl)` (`topup.ts:352-429`) drives `driveChargeSettlement({fetchStatus, isCancelled, now, sleep})` from `@hermes/shared/charge-settlement`, with `fetchStatus` calling `billing.charge_status {charge_id}`. Outcomes: `settled` → `✅ $<amount> added.` (or `✅ Credits added.`); `failed` → `renderChargeFailed()`; `refused` → `🔴 Could not check the charge: <message|error|'error'>`; `ambiguous` → the billing error plus `🟡 Your last charge's outcome is unconfirmed — check your balance/history before retrying.`; `timed_out` → `🟡 Still processing after 5 minutes — this is a timeout, not a failure. Check /topup or the portal shortly.` (+ `Portal: <url>`); `cancelled` → silent. Submission itself prints `💳 Charge submitted — confirming settlement…`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Transcript lines only (the charge already happened server-side).
- **Config / env:** n/a.
- **Edge cases / guards:** `renderChargeFailed(reason)` (`topup.ts:431-461`): `authentication_required` → `🔴 Your bank requires verification (3DS). Complete it on the portal to finish this purchase.`; `payment_method_expired` → `🔴 Your card has expired. Update it on the portal.`; `card_declined` → `🔴 Your card was declined. Try another card on the portal.`; `processing_error` → `🔴 The charge didn't go through (processing_error).`; default → `🔴 The charge didn't go through (<reason>).` Every failure appends `Portal: <url>`.
- **Rebuild notes:** Distinguish timeout from failure explicitly; never claim a charge failed when you only failed to observe it.

### Subscription overlay (`/subscription`)  `id: tui.subscription-overlay`
- **Surface:** TUI
- **Where:** PromptZone; opened by `/subscription` (alias `/upgrade`), starting on the `overview` screen.
- **What it does:** Views and changes the Nous subscription plan in-terminal.
- **How it works:** `src/components/subscriptionOverlay.tsx` (1024 lines) rendered by `appOverlays.tsx:95-110`. `buildSubscriptionCtx()` (`src/app/slash/commands/subscription.ts:61-141`) provides: `fetchCard()` → `billing.state` → `card`; `openManageLink(tierId?)` → builds `<portal origin>/manage-subscription?org_id=<id>[&plan=<tier>]` via `buildManageUrl()` and opens it; `openPortal(url)`; `preview(tierId)` → `subscription.preview {subscription_type_id}`; `refreshState()` → `subscription.state`; `requestRemoteSpending()` → `billing.step_up` (carrying the typed denial through); `resume()` → `subscription.resume`; `scheduleCancellation()` → `subscription.change {cancel:true}`; `scheduleChange(tierId)` → `subscription.change {subscription_type_id}`; `upgrade(tierId, idempotencyKey)` → `subscription.upgrade`; `sys`.
- **Inputs / options:** ZERO sub-commands — bare `/subscription` only; navigation is overlay-local.
- **Outputs / side effects:** Plan changes; only the `/upgrade` `charge_now` confirm moves money. Messages: `Opening your subscription page in the browser — finish there, then re-run /subscription.`; `Could not open browser — visit your subscription page manually at <url>`; `Opening the portal in your browser — finish there, then re-run /subscription.`; `Could not open browser — visit <url> to finish.`; `Could not build manage URL — is your portal configured?`
- **Config / env:** portal login state, `portal_url`, `org_id`.
- **Edge cases / guards:** Not logged in → `Not logged into Nous Portal — run /portal to log in, then /subscription.` A malformed `portal_url` returns `null` instead of throwing out of the Ink key handler (which would crash the overlay).
- **Rebuild notes:** Build deep links defensively — a URL parse failure inside a key handler takes the whole UI down.

### Agents overlay (`/agents`, `/tasks`)  `id: tui.agents-overlay`
- **Surface:** TUI
- **Where:** REPLACES the transcript (full pane). Opened by `/agents`, `/tasks`, `/replay [N]`, `/replay load <path>`, `/replay-diff <a> <b>`.
- **What it does:** Live spawn-tree observability: subagent tree with kill/pause controls, per-branch cost/token/file rollups, and turn-by-turn history.
- **How it works:** `src/components/agentsOverlay.tsx` (976 lines), mounted by `AgentsOverlayPane` (`appLayout.tsx:456-469`) with `gw`, `initialHistoryIndex` (from `overlay.agentsInitialHistoryIndex`), `onClose`, `t`. Tree building is `buildSubagentTree()` / `treeTotals()` / `widthByDepth()` (`src/lib/subagentTree.ts`, 351 lines); history snapshots live in `src/app/spawnHistoryStore.ts` (`getSpawnHistory`, `pushDiskSnapshot`, `setDiffPair`); delegation state in `src/app/delegationStore.ts`.
- **Inputs / options:** overlay-local keys; `Ctrl+C` / `Esc` close. From the command line: `/agents pause`, `/agents resume`, `/agents unpause`, `/agents status`; `/replay list|ls`, `/replay load <path>`, `/replay <N>`, `/replay last`; `/replay-diff <a> <b>`.
- **Outputs / side effects:** `delegation.pause {paused}`; `spawn_tree.list`; `spawn_tree.load`.
- **Config / env:** `max_spawn_depth`, `max_concurrent_children` (surfaced as `d<depth>/<max>` and `⚡<width>/<cap>` in the status HUD).
- **Edge cases / guards:** Opening it unmounts PromptZone, ComposerPane and PetPane; `resetFlowOverlays()` deliberately PRESERVES it across turn completions so a finished delegation doesn't close the dashboard.
- **Rebuild notes:** Make the observability view a full pane, keep it open across turns, and back it with both in-memory and on-disk snapshots.

### Journey overlay (`/journey`)  `id: tui.journey-overlay`
- **Surface:** TUI
- **Where:** REPLACES the transcript (full pane). Opened by `/journey`, `/learning`, `/memory-graph`.
- **What it does:** Shows "your learning journey" — skills and memories on a timeline.
- **How it works:** `src/components/journey.tsx` (595 lines), mounted by `JourneyPane` (`appLayout.tsx:471-476`) with `gw`, `onClose`, `t`. The command is a pure overlay open (`src/app/slash/commands/ops.ts:328-336`).
- **Inputs / options:** overlay-local keys; `Ctrl+C` / `Esc` close.
- **Outputs / side effects:** Read-only.
- **Config / env:** memory provider config.
- **Edge cases / guards:** Like the agents overlay it unmounts the composer.
- **Rebuild notes:** Timeline over list; join skills and memories on the same axis.

### Widget slot (modal widget apps)  `id: tui.widget-slot`
- **Surface:** TUI
- **Where:** `ActiveWidgetSlot` at viewport level (outside ComposerPane), so it can anchor a full-screen absolute `Overlay` against the whole terminal.
- **What it does:** Hosts one active widget app at a time; the app owns every keystroke while open.
- **How it works:** `src/sdk/host.tsx:209` (`ActiveWidgetSlot`), rendered last in `AppLayout` (`appLayout.tsx:587`). `dispatchWidgetInput({ch, key})` in the global handler returns true when the widget consumed the key (`useInputHandlers.ts:475-477`); `closeWidget()` is the Ctrl+C path. `src/components/overlay.tsx` (133 lines) is the full-screen absolute overlay primitive.
- **Inputs / options:** whatever the app's `reduce()` declares.
- **Outputs / side effects:** App-specific.
- **Config / env:** n/a.
- **Edge cases / guards:** A modal widget is the only overlay counted as occluding the status rule regardless of the bar's position (`$isStatusRuleOccluded`).
- **Rebuild notes:** "Topmost modal owns input" is best enforced structurally (one active widget), not by a routing table.

---

## 6. Widget SDK and widget apps

### Widget app contract  `id: tui.widget-sdk`
- **Surface:** TUI / Core
- **Where:** `ui-tui/src/sdk/` — the single import surface for a widget app (`src/sdk/index.ts`).
- **What it does:** Lets an app be a self-contained overlay surface with its own state, input reducer and render, composing the same layout/theme primitives every built-in surface uses.
- **How it works:** `WidgetApp<S>` (`src/sdk/types.ts:125-144`) requires `id`, `help`, `init(arg): S | null`, `reduce(state, input): S | null`, `render(ctx): ReactNode`, and optionally `mode` (`'modal'` default | `'ambient'`), `zone` (ambient placement, default `dock-bottom`), `width` (ambient card width in cells, default 44), `usage`. `init` returning `null` refuses the launch and the launcher prints `usage`; `reduce` returning the SAME reference swallows the key unchanged, returning `null` closes the app. `WidgetRenderCtx<S>` carries `{cols, rows, state, t}`. Registration is `defineWidgetApp(app)` in `src/sdk/registry.ts` — a `Map<string, WidgetApp>` where LAST WRITER WINS so a user app can shadow a built-in of the same id; `getWidgetApp(id)`, `removeWidgetApp(id)`, `listWidgetApps()` (id-sorted). The registry IS the catalog: `debugCommands` maps every registered app into a slash command carrying the app's own `help`/`usage` (`src/app/slash/commands/debug.ts:17-27`) and the slash handler falls back to `getWidgetApp(parsed.name)` for apps registered after the static table was built (`createSlashHandler.ts:54-62`).
- **Inputs / options:** the SDK re-exports `Accordion`, `Shimmer`, `ShimmerRows`, `shimmerSegments`, `useShimmerPhase`, `Dialog`, `Overlay`, `OverlayZone`, `OverlayHint`, `windowItems`, `ActionRow`, `chipRowProps`, `listRowStyle`, `MenuRow`, `scrollbarColors`, `useMenu`, `GridAreas`, `WidgetGrid`, `gauge`, `hbars`, `sparkline`, `sparkRows`, `contrastRatio`, `liftForContrast`, `mix`, `relativeLuminance`, `layoutGridAreas`, `layoutWidgetGrid`, `resolveGridTracks`, the grid types, `Theme`/`ThemeColors`, `ActiveWidgetSlot`, `AmbientDock`, `AmbientRail`, `ambientRailWidth`, `closeWidget`, `dispatchWidgetInput`, `launchWidget`, `openWidget`, `updateWidget`, `defineWidgetApp`, `getWidgetApp`, `listWidgetApps`, `ActiveWidget`, `AmbientZone`, `isCtrl`, `WidgetApp`, `WidgetInput`, `WidgetRenderCtx`, `loadUserWidgets`, `UserWidgetLoadResult`, `widgetSdk`, `WidgetSdk`.
- **Outputs / side effects:** Overlay state (`overlay.widget` for modal, `overlay.ambient[]` for ambient).
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** `launchWidget(id, arg)` returns `null` on success or a printable error (`unknown widget app: <id>` / the app's usage). Relaunching an active AMBIENT app with no argument toggles it closed (ambient apps capture no input, so the command is their only dismissal). `updateWidget` patches state only while the app is still in its slot, so a late fetch can never resurrect a closed app. `dispatchWidgetInput` closes the widget if its app disappeared from the registry.
- **Rebuild notes:** Three functions (init/reduce/render) plus a registry that doubles as the command catalog is the whole contract; make the host own placement so apps never position themselves.

### Ambient zones  `id: tui.widget-zones`
- **Surface:** TUI
- **Where:** `AmbientZone` = `'dock-top' | 'dock-bottom' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'` (`src/sdk/types.ts:162`).
- **What it does:** Two placement families — DOCKS are in-flow chrome rows that reserve real rows and never cover content (`dock-top` under the top status bar, `dock-bottom` above the bottom one, each a right-aligned row of cards); FLOATS overlay the transcript margins without reserving layout (absolute against the viewport, GUI-corner style), stacking vertically within a corner.
- **How it works:** `zoneOf(active)` in `src/sdk/host.tsx`; `AmbientDock placement=…` and `AmbientRail side=…` are mounted by `appLayout.tsx`. Floats RESERVE their `width` as a transcript rail (`ambientRailWidth`).
- **Inputs / options:** the app's `zone` and `width`.
- **Outputs / side effects:** Layout reservation.
- **Config / env:** n/a.
- **Edge cases / guards:** Content under a float stays live, so floats suit sparse corners; anything tall belongs in a dock.
- **Rebuild notes:** Name the zones after what the user says ("top right", "above the status bar") and map loosely.

### `/grid-test` widget app  `id: tui.app-grid-test`
- **Surface:** TUI
- **Where:** slash command `/grid-test`; help text `open an interactive widget-grid demo overlay`; listed in `/help` → `TUI` as `/grid-test [cols]x[rows]` / `open the interactive widget-grid demo`.
- **What it does:** An interactive playground for the layout engine — a resizable cell grid with nesting, named areas, a multi-stream mode, and live gap/padding cycling.
- **How it works:** `src/sdk/apps/gridTest.tsx` + `src/components/gridTestOverlay.tsx` (318 lines) + `src/components/gridStreamsDemo.tsx` (364 lines) + state in `src/sdk/apps/gridTestState.ts`. `MAX_SIZE = 12`; `parseSize()` accepts `''` (→ 4×3), `<cols>x<rows>`, or `<cols> <rows>`, clamping each to 1..12; `streams` selects the streams demo. Rendered inside `<Overlay zone="center"><FloatBox>` with `cols = clamp(cols-6, 1, 120)`.
- **Inputs / options:** launch args `/grid-test`, `/grid-test 6x4`, `/grid-test 6 4`, `/grid-test streams`. Keys — `Ctrl+C` close; `d` open the dialog app nested on top; `Esc`/`q` close (or un-zoom when zoomed); `Enter` nest+zoom the active cell; `n` toggle nested; `a` toggle named areas (turns streams off); `s` switch to streams (turns areas off); `g` cycle gap `auto → 0 → 1 → 2 → 3 → auto`; `p` cycle paddingX `auto → 0 → 1 → 2 → auto`; `r` reset to 4×3; `+`/`=` more columns; `-`/`_` fewer columns; `]` more rows; `[` fewer rows; `←`/`h`, `→`/`l`, `↑`/`k`, `↓`/`j` move the cursor (clamped). In STREAMS mode: `Esc`/`q`/`s` leave streams; `Enter` promote the focused stream to main; `r` reset; `←`/`↑`/`h`/`k` previous stream; `→`/`↓`/`l`/`j` next stream (wrapping over `GRID_STREAM_COUNT`).
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** `usage: /grid-test [cols]x[rows]  ·  /grid-test [cols] [rows]  ·  /grid-test streams` on a parse failure. Cursor is re-clamped after every size change.
- **Rebuild notes:** Ship a live demo of your layout engine as a first-class app — it doubles as the regression surface.

### `/dialog-test` widget app  `id: tui.app-dialog-test`
- **Surface:** TUI
- **Where:** slash command `/dialog-test`; help `open a sample dialog overlay with a faked backdrop`; listed in `/help` → `TUI` as `/dialog-test [zone]`.
- **What it does:** Demonstrates the `Overlay` + `Dialog` primitives at any of nine viewport zones with a dimming backdrop.
- **How it works:** `src/sdk/apps/dialogTest.tsx`. Zones (verbatim, in order): `bottom`, `bottom-left`, `bottom-right`, `center`, `left`, `right`, `top`, `top-left`, `top-right`; default `center`. Title `Dialog primitive`, hint `Esc/q/Enter close · Ctrl+C close`, body lines `This is a viewport-level overlay with a backdrop.`, ``, `Zone: <zone>`, `Try: /dialog-test top-right · bottom · left · ...`. Width `min(60, cols - 8)`.
- **Inputs / options:** `/dialog-test [zone]`; keys `Esc`, `q`, `Enter`, `Ctrl+C` all close.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** An unknown zone refuses the launch with `usage: /dialog-test [zone]   zones: bottom, bottom-left, bottom-right, center, left, right, top, top-left, top-right`.
- **Rebuild notes:** A zone enumeration plus a backdrop flag covers essentially every modal placement need.

### `/ticker` widget app  `id: tui.app-ticker`
- **Surface:** TUI
- **Where:** slash command `/ticker [symbol]`; help `fake 1-pip chart with a live sparkline`. Ambient mode.
- **What it does:** A glanceable ambient card with a fake price and a live sparkline.
- **How it works:** `src/sdk/apps/ticker.tsx`. `mode: 'ambient'`; `init(arg)` takes the first whitespace token, uppercases it and truncates to 8 chars, defaulting to `HRMS`. Renders a `Dialog` of width `max(32, POINTS + 6)` containing a delta readout in pips and `sparkline(series)` from `src/lib/charts.ts`.
- **Inputs / options:** `/ticker [symbol]`; usage `usage: /ticker [symbol]`. Re-running `/ticker` with no arg toggles the card away (ambient dismissal).
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Its `reduce` is contract-complete (`Esc`/`q`/`Ctrl+C` → close) even though ambient apps never receive input.
- **Rebuild notes:** Ambient cards need a toggle-off path through their launch command.

### `/weather` widget app  `id: tui.app-weather`
- **Surface:** TUI
- **Where:** slash command `/weather [location]`; help `current conditions with themed ASCII art (wttr.in)`. Ambient mode, renders in the dock.
- **What it does:** Fetches current conditions from wttr.in and renders themed ASCII art beside them.
- **How it works:** `src/sdk/apps/weather.tsx` (203 lines). `init(arg)` kicks an async `load(location)` and returns `{location, phase:{kind:'loading'}}`; the fetch resolves via `updateWidget()`, moving `phase` to a data or `{kind:'error', message}` state.
- **Inputs / options:** `/weather` (blank geolocates by IP), `/weather <location>`; usage `usage: /weather [location]   (blank = geolocate by IP)`. Keys (when reused modally): `r` refresh, `Esc`/`Enter`/`q`/`Ctrl+C` close.
- **Outputs / side effects:** One outbound HTTPS request to wttr.in.
- **Config / env:** n/a.
- **Edge cases / guards:** Errors render in-card rather than throwing; the async result is dropped if the app already closed.
- **Rebuild notes:** `init` → loading state, `updateWidget` → resolved state is the whole async pattern.

### User widget apps (`$HERMES_HOME/tui-widgets/*.mjs`)  `id: tui.user-widgets`
- **Surface:** TUI
- **Where:** drop `<name>.mjs` into `$HERMES_HOME/tui-widgets/` (default `~/.hermes/tui-widgets/`); the app then appears in `/` completions and dispatch automatically.
- **What it does:** Lets Hermes (or the user) author new TUI widgets at runtime, hot-loaded without a restart.
- **How it works:** `src/sdk/userWidgets.ts`. A file must default-export `register(sdk)`; it is imported as plain ESM with a cache-busting `?t=<Date.now()>` so edits reload. `widgetSdk` (the object handed in) exposes exactly: `Accordion`, `Box`, `Dialog`, `GridAreas`, `Overlay`, `React`, `Shimmer`, `ShimmerRows`, `Text`, `WidgetGrid`, `defineWidgetApp`, `gauge`, `h` (= `React.createElement`), `hbars`, `isCtrl`, `openWidget`, `sparkRows`, `sparkline`, `updateWidget`, `useShimmerPhase`. `loadUserWidgets(dir)` scans `*.mjs` sorted, delete-syncs apps whose file vanished (`fileApps` map → `removeWidgetApp`), and returns `{added, errors, loaded, removed}`. `watchUserWidgets()` installs an `fs.watch` on the directory with a 300 ms debounce; if the directory does not exist yet it watches the PARENT for its creation, falling back to a 2 s poll. Every handle is `.unref()`ed so it never keeps the process alive. `onUserWidgets(listener)` lets the app layer announce loads in the transcript.
- **Inputs / options:** `/widgets-reload` forces a rescan and prints `widgets — loaded: <files>` or `widgets — no user widgets found`, appending `<file>: <message>` for each error.
- **Outputs / side effects:** Registry mutations; `[tui-parent]` breadcrumbs `user widgets registered: <ids>` / `user widget <file> failed to load: <message>`.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Trust model matches `~/.hermes/plugins/` — files under HERMES_HOME execute with the TUI's privileges. A load error logs and skips; a broken widget never takes the TUI down. `default export must be register(sdk)` is thrown for a non-function default.
- **Rebuild notes:** Hand the SDK IN rather than expecting the user file to import from the bundle (it has no resolvable path); cache-bust every import; watch the parent directory so the first-ever file hot-loads too.

### `/widgets-reload`  `id: tui.slash-widgets-reload`
- **Surface:** TUI
- **Where:** slash command; help `rescan $HERMES_HOME/tui-widgets and (re)register user widget apps`.
- **What it does:** Forces a user-widget rescan and reports the result.
- **How it works:** `src/app/slash/commands/debug.ts:32-45` → `loadUserWidgets()` then `ctx.transcript.sys('widgets — ' + parts.join(' · '))`.
- **Inputs / options:** none.
- **Outputs / side effects:** Registry mutations; one transcript line.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Redundant in practice because `watchUserWidgets()` hot-loads, but kept as an explicit escape hatch.
- **Rebuild notes:** Keep a manual reload even when you have a watcher — watchers fail silently on network filesystems.

---

## 7. TUI-owned slash commands

Registration order in `ui-tui/src/app/slash/registry.ts:11-20`: `core`, `topup`, `session`,
`subscription`, `ops`, `wake`, `setup`, `debug`. Lookup is case-insensitive over names AND aliases
(`registry.ts:22-25`). Anything not found here falls through to the gateway (see
`tui.slash-dispatch`). Every `help:` string below is transcribed verbatim from source.

### `/help`  `id: tui.slash-help`
- **Surface:** TUI
- **Where:** composer; help `list commands + hotkeys`.
- **What it does:** Prints a categorized panel of every available command plus the hotkey table.
- **How it works:** `src/app/slash/commands/core.ts:93-125`. Sections come from `ctx.local.catalog.categories` (fetched from the gateway's `commands.catalog`), each `{title: cat.name, rows: cat.pairs}`. If `catalog.skillCount` is non-zero it appends `<N> skill commands available — /skills to browse`. Then a hard-coded `TUI` section with rows: `/details [hidden|collapsed|expanded|cycle]` / `set global agent detail visibility mode`; `/details <section> [hidden|collapsed|expanded|reset]` / `override one section (thinking/tools/subagents/activity)`; `/fortune [random|daily]` / `show a random or daily local fortune`; `/grid-test [cols]x[rows]` / `open the interactive widget-grid demo`; `/dialog-test [zone]` / `open a sample dialog overlay with a faked backdrop`. Finally a `Hotkeys` section = the whole `HOTKEYS` table. Panel title is `ctx.ui.theme.brand.helpHeader`.
- **Inputs / options:** none (any argument is ignored).
- **Outputs / side effects:** A `panel` transcript message.
- **Config / env:** skin key `help_header`.
- **Edge cases / guards:** Works before the catalog arrives (the categories list is simply empty).
- **Rebuild notes:** Merge a server-provided catalog with client-only commands and always append the hotkey table.

### `/quit`, `/exit`  `id: tui.slash-quit`
- **Surface:** TUI
- **Where:** composer; help `exit hermes`.
- **What it does:** Exits the TUI.
- **How it works:** `core.ts:127-147` → `ctx.session.die()`.
- **Inputs / options:** none.
- **Outputs / side effects:** Gateway killed, Ink unmounted, terminal modes reset, process exits.
- **Config / env:** `HERMES_TUI_DASHBOARD`.
- **Edge cases / guards:** In dashboard chat it refuses with `exit is disabled in hosted dashboard chat — use /new to start a fresh session` (`DASHBOARD_EXIT_DISABLED_MESSAGE`, `core.ts:86-87`). Unlike the keyboard path it does NOT auto-start a fresh chat.
- **Rebuild notes:** Route every exit through one function so cleanup can't be skipped.

### `/update`  `id: tui.slash-update`
- **Surface:** TUI
- **Where:** composer; help `update Hermes Agent to the latest version (exits TUI)`.
- **What it does:** Exits with code 42 so the Python wrapper execs `hermes update`.
- **How it works:** `core.ts:149-164`; prints `exiting TUI to run update...` then `setTimeout(() => ctx.session.dieWithCode(42), 100)`.
- **Inputs / options:** none.
- **Outputs / side effects:** Process exit 42 → `hermes update` relaunch.
- **Config / env:** `HERMES_TUI_DASHBOARD`.
- **Edge cases / guards:** Refused in dashboard mode with `update is disabled in hosted dashboard chat — the hosted environment is managed separately`.
- **Rebuild notes:** The 100 ms delay lets the notice paint before the unmount.

### `/mouse`, `/scroll`  `id: tui.slash-mouse`
- **Surface:** TUI / Config
- **Where:** composer; help `set mouse tracking preset [on|off|toggle|wheel|buttons|all]`.
- **What it does:** Chooses the DEC mouse-protocol subset at runtime and persists it.
- **How it works:** see `tui.mouse-tracking`. `core.ts:166-183`.
- **Inputs / options:** `on`, `off`, `toggle`, `wheel`, `buttons`, `all`, `any`, `full`, `button`, `click`, `scroll`, or bare.
- **Outputs / side effects:** `mouse tracking <mode>`; `config.set {key:'mouse', value}`.
- **Config / env:** `display.mouse_tracking`.
- **Edge cases / guards:** Unknown arg → `usage: /mouse [on|off|toggle|wheel|buttons|all]`. The state patch is applied immediately and the transcript line is deferred to a microtask so the repaint lands first.
- **Rebuild notes:** n/a (see `tui.mouse-tracking`).

### `/clear`, `/new`  `id: tui.slash-clear`
- **Surface:** TUI
- **Where:** composer; help `start a new session`.
- **What it does:** Ends the current conversation and starts a fresh session; `/new <title>` names it.
- **How it works:** `core.ts:185-217`. Guarded by `ctx.session.guardBusySessionSwitch('switch sessions')`. `isNew = cmd.startsWith('/new')`; the title is the argument (only for `/new`). Commit sets `status: 'forging session…'` then `ctx.session.newSession(isNew ? 'new session started' : undefined, title || undefined)`.
- **Inputs / options:** `/clear`; `/new`; `/new <title>`.
- **Outputs / side effects:** New session id; transcript cleared.
- **Config / env:** `HERMES_TUI_NO_CONFIRM`, `ui.destructiveSlashConfirm`.
- **Edge cases / guards:** Unless confirmation is disabled it opens the confirm prompt — title `Clear the current session?` / `Start a new session?`, detail `This ends the current conversation and clears the transcript.`, confirm `Yes, clear the session` / `Yes, start a new session`, cancel `No, keep going`, `danger: true`.
- **Rebuild notes:** Confirm destructive local state changes, but make the confirmation itself disable-able for scripted use.

### `/redraw`  `id: tui.slash-redraw`
- **Surface:** TUI
- **Where:** composer; help `force a full UI repaint`.
- **What it does:** Forces a full repaint (same as `Cmd/Ctrl+L`).
- **How it works:** `core.ts:219-226` → `forceRedraw(process.stdout)` then `ui redrawn`.
- **Inputs / options:** none.
- **Outputs / side effects:** Repaint + one transcript line.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/status`  `id: tui.slash-status`
- **Surface:** TUI
- **Where:** composer; help `show live session info`.
- **What it does:** Shows the backend's session status report in a pager.
- **How it works:** `core.ts:228-241` → `session.status {session_id}` → `ctx.transcript.page(r.output || '(no status)', 'Status')`.
- **Inputs / options:** none.
- **Outputs / side effects:** Pager overlay.
- **Config / env:** n/a.
- **Edge cases / guards:** No session → `no active session`.
- **Rebuild notes:** n/a.

### `/title`  `id: tui.slash-title`
- **Surface:** TUI
- **Where:** composer; help `set or show current session title`.
- **What it does:** Reads or sets the session title (which then shows as an accent badge at the right edge of the status line).
- **How it works:** `core.ts:243-283`. Bare → `session.title {session_id}` → `title: <t>` or `no title set`. With text → `session.title {session_id, title}` → `patchUiState({sessionTitle})` and `session title set: <title>`; a `pending` response appends ` (queued while session initializes)`.
- **Inputs / options:** `/title`; `/title <text>`.
- **Outputs / side effects:** Session title persisted; status bar right label changes.
- **Config / env:** `display.status_bar.fields` must include `title` for the badge to show.
- **Edge cases / guards:** No session → `no active session`; whitespace-only → `usage: /title <your session title>`.
- **Rebuild notes:** Accept a pending write while the session is still initialising rather than rejecting it.

### `/density`  `id: tui.slash-density`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle compact display`.
- **What it does:** Toggles the compact transcript layout.
- **How it works:** `core.ts:285-300` → `flagFromArg(arg, ui.compact)` → `patchUiState({compact})` + `config.set {key:'density', value:'on'|'off'}`.
- **Inputs / options:** bare (toggle), `on`, `off`, `toggle`.
- **Outputs / side effects:** `density on|off`.
- **Config / env:** `display.density`.
- **Edge cases / guards:** Unknown arg → `usage: /density [on|off|toggle]`.
- **Rebuild notes:** n/a.

### `/details`, `/detail`  `id: tui.slash-details`
- **Surface:** TUI / Config
- **Where:** composer; help `control agent detail visibility (global or per-section)`.
- **What it does:** Sets the global detail mode or overrides one section's visibility.
- **How it works:** `core.ts:302-364`. Bare → `config.get {key:'details_mode'}` then prints `details: <mode>  (<section>=<mode> …)`. `<section> <mode|reset>` → patches `ui.sections` and `config.set {key:'details_mode.<section>', value: mode ?? ''}`, printing `details <section>: <mode|reset>`. A bare mode (or `cycle`/`toggle`) sets the global mode AND stamps every section with it, setting `detailsModeCommandOverride: true`, then `config.set {key:'details_mode'}` and `details: <mode>`.
- **Inputs / options:** modes `hidden`, `collapsed`, `expanded`; cycle words `cycle`, `toggle`; reset words `reset`, `clear`, `default`; sections `thinking`, `tools`, `subagents`, `activity`.
- **Outputs / side effects:** `display.details_mode` and `display.sections.<name>` persisted.
- **Config / env:** `display.details_mode`, `display.sections.{thinking,tools,subagents,activity}`.
- **Edge cases / guards:** Usage strings verbatim — global: `usage: /details [hidden|collapsed|expanded|cycle]  or  /details <section> [hidden|collapsed|expanded|reset]`; section: `usage: /details <section> [hidden|collapsed|expanded|reset]`.
- **Rebuild notes:** Layer explicit override → command override → built-in per-section default → global config (`sectionMode()`, `src/domain/details.ts:353-358`).

### Detail-visibility defaults  `id: tui.details-defaults`
- **Surface:** Config
- **Where:** `display.details_mode` and `display.sections.*`.
- **What it does:** Ships opinionated per-section defaults that stream the turn as a live transcript instead of a wall of chevrons.
- **How it works:** `SECTION_DEFAULTS` (`src/domain/details.ts:307-311`): `thinking: 'expanded'`, `tools: 'expanded'`, `activity: 'hidden'`; `subagents` is unset and falls through to the global `details_mode` (default `collapsed`, `src/app/uiStore.ts:379`). `resolveDetailsMode(d)` falls back through `details_mode` → a `thinking_mode` map (`{collapsed:'collapsed', full:'expanded', truncated:'collapsed'}`) → `'collapsed'`. `resolveSections(raw)` silently drops unknown section names and invalid modes so partial overrides work. `nextDetailsMode` cycles `hidden → collapsed → expanded → hidden`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Which sections render open.
- **Config / env:** `display.details_mode`, `display.sections.*`, legacy `thinking_mode`.
- **Edge cases / guards:** `activity` hidden by default means ambient meta (gateway hints, terminal-parity nudges, background notifications) is suppressed; tool failures still render inline on the failing tool row and ambient errors/warnings surface through a floating-alert backstop when every panel resolves to hidden.
- **Rebuild notes:** Keep the per-section default layer ABOVE the persisted global so an existing config still gets the good defaults, and let an explicit in-session command flatten everything.

### `/fortune`  `id: tui.slash-fortune`
- **Surface:** TUI
- **Where:** composer; help `local fortune`.
- **What it does:** Prints a random or a deterministic daily fortune.
- **How it works:** `core.ts:366-382`. `randomFortune()` / `dailyFortune(sid)` from `src/content/fortunes.ts`. `fromScore(n)`: `rare = n % 20 === 0`; rare picks from `LEGENDARY`, otherwise from `FORTUNES`; output is `🌟 <text>` or `🔮 <text>`. `dailyFortune(seed)` hashes `` `${seed || 'anon'}|${new Date().toDateString()}` `` with FNV-1a (`Math.imul(h ^ c, 16777619) >>> 0`, seed `2166136261`).
- **Inputs / options:** bare or `random`; `daily`, `stable`, `today`.
- **Outputs / side effects:** One transcript line.
- **Config / env:** n/a.
- **Edge cases / guards:** Anything else → `usage: /fortune [random|daily]`.
- **Rebuild notes:** Seed the daily variant on session id + date so it is stable within a day and differs per session.

### Fortune text tables  `id: tui.fortunes`
- **Surface:** TUI
- **Where:** `/fortune` output.
- **What it does:** The 10 ordinary and 3 legendary fortunes.
- **How it works:** `src/content/fortunes.ts:1-18`. `FORTUNES` (verbatim, in order): `you are one clean refactor away from clarity`; `a tiny rename today prevents a huge bug tomorrow`; `your next commit message will be immaculate`; `the edge case you are ignoring is already solved in your head`; `minimal diff, maximal calm`; `today favors bold deletions over new abstractions`; `the right helper is already in your codebase`; `you will ship before overthinking catches up`; `tests are about to save your future self`; `your instincts are correctly suspicious of that one branch`. `LEGENDARY`: `legendary drop: one-line fix, first try`; `legendary drop: every flaky test passes cleanly`; `legendary drop: your diff teaches by itself`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** 1-in-20 chance of a legendary.
- **Rebuild notes:** n/a.

### `/copy`  `id: tui.slash-copy`
- **Surface:** TUI
- **Where:** composer; help `copy selection or assistant message`.
- **What it does:** Copies the current selection, or the Nth (default last) assistant message, to the clipboard.
- **How it works:** `core.ts:384-438`. With no arg and an active composer selection → `ctx.composer.selection.copySelection()` → `copied <N> characters`. Otherwise it filters history to `role === 'assistant'` and picks index `arg ? min(parseInt(arg), len) - 1 : len - 1`. Over SSH (`isRemoteShellSession(process.env)`) it writes OSC52 directly; otherwise it tries the native clipboard first and falls back to OSC52.
- **Inputs / options:** `/copy`; `/copy <number>`.
- **Outputs / side effects:** Clipboard write. Messages: `copied <N> characters`; `clipboard copy failed — try HERMES_TUI_FORCE_OSC52=1 to force the escape sequence`; `usage: /copy [number]`; `nothing to copy — start a conversation first`; `sent OSC52 copy sequence (terminal support required)`; `copied to clipboard`; `copy failed: <error>`.
- **Config / env:** `HERMES_TUI_FORCE_OSC52`, `SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`.
- **Edge cases / guards:** A non-numeric argument is rejected before any clipboard work.
- **Rebuild notes:** Detect remote shells and go straight to OSC52 — a native clipboard write there silently targets the wrong machine.

### `/paste`  `id: tui.slash-paste`
- **Surface:** TUI
- **Where:** composer; help `attach clipboard image`.
- **What it does:** Attaches the image currently on the clipboard to the next message.
- **How it works:** `core.ts:440-444` → `ctx.composer.attachClipboardImage()`.
- **Inputs / options:** none (any argument → `usage: /paste`).
- **Outputs / side effects:** An attachment chip in the composer.
- **Config / env:** n/a.
- **Edge cases / guards:** Text paste is the hotkey path; `/paste` is specifically the image path.
- **Rebuild notes:** n/a.

### `/prompt`, `/compose`  `id: tui.slash-prompt`
- **Surface:** TUI
- **Where:** composer; help `compose your next prompt in $EDITOR (same as Ctrl+G)`.
- **What it does:** Opens the composer buffer in `$EDITOR`.
- **How it works:** `core.ts:446-462`. Any inline text is first dropped into the composer (`ctx.composer.setInput(arg)`) so it carries into the editor, matching the CLI's `/prompt <text>`; then `ctx.composer.openEditor()`.
- **Inputs / options:** `/prompt`; `/prompt <seed text>`.
- **Outputs / side effects:** Editor subprocess; composer value replaced. Failure → `editor failed: <error>`.
- **Config / env:** `EDITOR`, `VISUAL`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/terminal-setup`  `id: tui.slash-terminal-setup`
- **Surface:** TUI
- **Where:** composer; help `configure IDE terminal keybindings for multiline + undo/redo`.
- **What it does:** Installs local VS Code / Cursor / Windsurf terminal keybindings so `Cmd+Enter` and undo/redo behave correctly on macOS.
- **How it works:** `core.ts:464-497` → `configureDetectedTerminalKeybindings()` (auto) or `configureTerminalKeybindings(target)` from `src/lib/terminalSetup.ts` (505 lines). Prints `result.message` and, when `result.success && result.requiresRestart`, also `restart the IDE terminal for the new keybindings to take effect`.
- **Inputs / options:** bare / `auto`, `vscode`, `cursor`, `windsurf`.
- **Outputs / side effects:** Writes the IDE's `keybindings.json`.
- **Config / env:** `TERM_PROGRAM` and friends drive auto-detection.
- **Edge cases / guards:** Anything else → `usage: /terminal-setup [auto|vscode|cursor|windsurf]`; failures → `terminal setup failed: <error>`.
- **Rebuild notes:** Detect the host IDE and patch its keymap rather than telling the user to do it.

### `/logs`  `id: tui.slash-logs`
- **Surface:** TUI
- **Where:** composer; help `view gateway logs`.
- **What it does:** Shows the tail of the gateway child's log buffer.
- **How it works:** `core.ts:499-507` → `ctx.gateway.gw.getLogTail(min(80, max(1, parseInt(arg) || 20)))` → pager titled `Logs`.
- **Inputs / options:** `/logs`; `/logs <N>` (1..80, default 20).
- **Outputs / side effects:** Pager overlay, or `no gateway logs`.
- **Config / env:** n/a.
- **Edge cases / guards:** N is clamped to [1, 80].
- **Rebuild notes:** Keep an in-process ring buffer of the child's stderr — it is the only way to debug a gateway that already died.

### `/history`  `id: tui.slash-history`
- **Surface:** TUI
- **Where:** composer; help `view current transcript (user + assistant messages)`.
- **What it does:** Renders the TUI's OWN transcript (not the persisted one) as a pager.
- **How it works:** `core.ts:509-535`. Filters to `user`/`assistant`, labels each `[You #N]` / `[Hermes #N]`, and clips each body to `max(80, parseInt(arg) || 400)` chars with a trailing `…`. Empty bodies render `(N tool calls)` or `(empty)`.
- **Inputs / options:** `/history`; `/history <preview-chars>` (min 80, default 400).
- **Outputs / side effects:** Pager titled `History`.
- **Config / env:** n/a.
- **Edge cases / guards:** No conversation → `no conversation yet`. Deliberately client-side because the CLI's `/history` runs in a detached slash-worker subprocess that never sees the TUI's turns.
- **Rebuild notes:** When a command has a server implementation that cannot see the client's state, reimplement it client-side rather than shipping a lie.

### `/save`  `id: tui.slash-save`
- **Surface:** TUI
- **Where:** composer; help `save the current transcript to JSON`.
- **What it does:** Writes the conversation to a JSON file.
- **How it works:** `core.ts:537-568` → `session.save {session_id}` → `conversation saved to: <file>` or `failed to save`.
- **Inputs / options:** none.
- **Outputs / side effects:** A JSON file on disk.
- **Config / env:** n/a.
- **Edge cases / guards:** No `user`/`assistant`/`tool` message → `no conversation yet`; no session → `no active session — nothing to save`.
- **Rebuild notes:** n/a.

### `/focus`  `id: tui.slash-focus`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle focus view — show only your prompt and the final response [on|off|status]`.
- **What it does:** Hides intermediate output so only the prompt and the final response render; shows a `◉ focus` badge in the status bar.
- **How it works:** `core.ts:570-602`. `status`/`show`/`?` report without writing; otherwise `flagFromArg` then `patchUiState({focusView})` + `config.set {key:'focus', value:'on'|'off'}`. Python owns the `tool_progress` stash/restore so `/focus off` returns to the user's previous `/verbose` mode.
- **Inputs / options:** bare (toggle), `on`, `off`, `toggle`, `status`, `show`, `?`.
- **Outputs / side effects:** Messages `focus view on — only your prompt and the final response`; `focus view off`; `focus view enabled — just your prompt and the final response`; `focus view disabled`.
- **Config / env:** `display.focus` / the backing `focus` key.
- **Edge cases / guards:** Unknown arg → `usage: /focus [on|off|status]`. The badge is pinned in the status bar and never dropped on narrow terminals — the user must never be in reduced-output mode without seeing it.
- **Rebuild notes:** Any mode that hides information needs an indicator that cannot be responsive-collapsed away.

### `/statusbar`, `/sb`  `id: tui.slash-statusbar`
- **Surface:** TUI / Config
- **Where:** composer; help `status bar position (on|off|top|bottom)`.
- **What it does:** Moves or hides the status rule.
- **How it works:** `core.ts:604-630`. Bare/`toggle` flips between `off` and `top`; `on`/`top` → `top`; `off`/`bottom` → that literal value.
- **Inputs / options:** bare, `toggle`, `on`, `off`, `top`, `bottom`.
- **Outputs / side effects:** `status bar <mode>`; `config.set {key:'statusbar', value}`.
- **Config / env:** `display.status_bar`.
- **Edge cases / guards:** Unknown → `usage: /statusbar [on|off|top|bottom|toggle]`. With `off`, `StatusRulePane` returns null for both slots so its timers are never mounted.
- **Rebuild notes:** n/a.

### `/battery`  `id: tui.slash-battery`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle a color-coded battery indicator in the status bar [on|off|status]`.
- **What it does:** Shows `⚡|🔋 NN%` as the first (pinned) status-bar element, colored by the backend's category.
- **How it works:** `core.ts:632-669`. `status`/`show` fetch `system.battery {}` on demand (so it works even while the poller is off) and print `battery indicator <on|off> — currently ⚡|🔋 NN%` or `… — no battery detected on this machine`. Otherwise `patchUiState({battery, batteryStatus: null when off})` + `config.set {key:'battery'}`. Polling lives in `src/app/useBatteryPoll.ts`; colors in `batteryColor()` (`appChrome.tsx`) — `good` → `statusGood`, `warn` → `statusWarn`, `bad` → `statusBad`, `critical` → `statusCritical`, else muted. An unknown percent renders `--%`, never `null%`.
- **Inputs / options:** bare (toggle), `on`, `off`, `toggle`, `status`, `show`.
- **Outputs / side effects:** `battery indicator on|off`; `display.battery` persisted.
- **Config / env:** `display.battery`, `display.status_bar.fields` must include `battery`.
- **Edge cases / guards:** Unknown arg → `usage: /battery [on|off|status]`. Category coloring is INVERTED relative to the context bar (full = good).
- **Rebuild notes:** n/a.

### `/queue`, `/q`  `id: tui.slash-queue`
- **Surface:** TUI
- **Where:** composer; help `inspect or enqueue a message`.
- **What it does:** Reports the queue depth, or appends a message to the queue.
- **How it works:** `core.ts:671-683`. Bare → `<N> queued message(s)`. With text → `ctx.composer.enqueue(arg)` then `queued: "<first 50 chars>…"`.
- **Inputs / options:** `/queue`; `/queue <text>`.
- **Outputs / side effects:** Queue mutation.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/steer`  `id: tui.slash-steer`
- **Surface:** TUI
- **Where:** composer; help `inject a message after the next tool call (no interrupt)`.
- **What it does:** Delivers a mid-turn nudge that arrives at the next tool-call boundary without interrupting the stream.
- **How it works:** `core.ts:685-721` → `session.steer {session_id, text}`; `r.status === 'queued'` → `steer queued — arrives after next tool call: "<preview>"`, else `steer rejected`.
- **Inputs / options:** `/steer <prompt>`.
- **Outputs / side effects:** Backend steer queue.
- **Config / env:** `/busy steer` makes Enter behave this way by default.
- **Edge cases / guards:** Empty → `usage: /steer <prompt>`. If the agent is idle (or there is no session) it falls back to the ordinary queue with `no active turn — queued for next: "<preview>"` — identical semantics to the gateway handler, so the message is never lost.
- **Rebuild notes:** A steer that cannot be delivered must degrade to a queue, never to a drop.

### `/undo`  `id: tui.slash-undo`
- **Surface:** TUI
- **Where:** composer; help `undo last exchange`.
- **What it does:** Removes the last user+assistant exchange from the session.
- **How it works:** `core.ts:723-742` → `session.undo {session_id}`; on `removed > 0` it also trims the client transcript via `ctx.transcript.trimLastExchange(prev)` and prints `undid <N> messages`.
- **Inputs / options:** none.
- **Outputs / side effects:** Backend history mutation; client transcript trimmed.
- **Config / env:** n/a.
- **Edge cases / guards:** No session or nothing removed → `nothing to undo`.
- **Rebuild notes:** Trim the client view from the server's reported count, not from a local guess.

### `/retry`  `id: tui.slash-retry`
- **Surface:** TUI
- **Where:** composer; help `retry last user message`.
- **What it does:** Undoes the last exchange and resends the previous user message.
- **How it works:** `core.ts:744-769` → `ctx.local.getLastUserMsg()`, then `session.undo` and `ctx.transcript.send(last)`. With no session it just resends.
- **Inputs / options:** none.
- **Outputs / side effects:** A new turn.
- **Config / env:** n/a.
- **Edge cases / guards:** No last message → `nothing to retry`; `removed <= 0` → `nothing to retry`.
- **Rebuild notes:** n/a.

### `/topup`  `id: tui.slash-topup`
- **Surface:** TUI
- **Where:** composer; help `Show your balance and manage billing — add funds, auto-reload, limits`.
- **What it does:** Opens the interactive billing overlay.
- **How it works:** `src/app/slash/commands/topup.ts:566-597` → `billing.state {}` → opens `overlay.billing` at screen `overview` with `pendingCharge: null`.
- **Inputs / options:** ZERO sub-commands — any argument is ignored.
- **Outputs / side effects:** See `tui.billing-overlay`.
- **Config / env:** portal login.
- **Edge cases / guards:** Not logged in → `💳 Not logged into Nous Portal — run /portal to log in, then /topup.`
- **Rebuild notes:** n/a.

### `/subscription`, `/upgrade`  `id: tui.slash-subscription`
- **Surface:** TUI
- **Where:** composer; help `View or change your Nous subscription plan`.
- **What it does:** Opens the subscription overlay.
- **How it works:** `src/app/slash/commands/subscription.ts:143-176` → `subscription.state {}` → opens `overlay.subscription` at screen `overview`.
- **Inputs / options:** ZERO sub-commands.
- **Outputs / side effects:** See `tui.subscription-overlay`.
- **Config / env:** portal login.
- **Edge cases / guards:** Not logged in → `Not logged into Nous Portal — run /portal to log in, then /subscription.`
- **Rebuild notes:** n/a.

### `/bg`, `/background`  `id: tui.slash-bg`
- **Surface:** TUI
- **Where:** composer; help `launch a background prompt`.
- **What it does:** Runs a prompt in the background while the foreground session stays free.
- **How it works:** `src/app/slash/commands/session.ts:80-100` → `prompt.background {session_id, text}` → adds `task_id` to `ui.bgTasks` and prints `bg <task_id> started`.
- **Inputs / options:** `/bg <prompt>`.
- **Outputs / side effects:** Background task; `<N> background task(s) running` above the composer and `│ N bg` in the status bar.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty → `/bg <prompt>`.
- **Rebuild notes:** n/a.

### `/btw`  `id: tui.slash-btw`
- **Surface:** TUI
- **Where:** composer; help `ask a side question about this conversation`.
- **What it does:** Answers a side question from a snapshot of the conversation without polluting the main thread.
- **How it works:** `session.ts:102-120` → `prompt.btw {session_id, text}` → `btw <task_id> — answering from a conversation snapshot`.
- **Inputs / options:** `/btw <question>`.
- **Outputs / side effects:** A background task.
- **Config / env:** n/a.
- **Edge cases / guards:** Empty → `/btw <question>`.
- **Rebuild notes:** n/a.

### `/model`  `id: tui.slash-model`
- **Surface:** TUI / Config
- **Where:** composer; help `change or show model`.
- **What it does:** Opens the model picker, or switches directly to a named model.
- **How it works:** `session.ts:122-180`. Bare → `patchOverlayState({modelPicker: true})`; `--refresh` → `{modelPicker: {refresh: true}}`; otherwise `config.set {key:'model', session_id, value: modelValueForConfigSet(arg), confirm_expensive_model}`. `modelValueForConfigSet` rewrites the TUI-internal `--tui-session` flag into the backend's `--session` via `sessionScopedModelArg()` (`src/domain/slash.ts:190-195`), which also strips duplicate `--global`/`--session` tokens.
- **Inputs / options:** `/model`; `/model --refresh`; `/model <name>`; `/model <name> --session`; `/model <name> --global`.
- **Outputs / side effects:** `model → <value>` or `model → <value> (applies next turn)`; `ui.info.model` patched; `ctx.local.maybeWarn(r)` surfaces any warning.
- **Config / env:** `model`.
- **Edge cases / guards:** NO busy guard — mid-turn the gateway QUEUES the change and returns `deferred: true`. `confirm_required` opens the expensive-model confirm and re-issues with `confirm_expensive_model: true`. A missing `r.value` → `error: invalid response: model switch`.
- **Rebuild notes:** Queue a config change during a turn instead of rejecting it; the user's intent is for the NEXT turn anyway.

### `/sessions`, `/switch`, `/session`, `/resume`  `id: tui.slash-sessions`
- **Surface:** TUI
- **Where:** composer; help `browse, switch, or resume sessions`.
- **What it does:** Opens the live session switcher, creates a new live session, or resumes a session by id/title.
- **How it works:** `session.ts:182-209`. `new` → `ctx.session.newLiveSession()` (allowed while busy — it does not close the current session). Any other argument → `guardBusySessionSwitch('switch sessions')` then `ctx.session.resumeById(trimmed)`. Bare → `patchOverlayState({sessions: true})`.
- **Inputs / options:** `/sessions`; `/sessions new`; `/sessions <id|title>`; `/resume <id|title>`; `/resume latest`.
- **Outputs / side effects:** Overlay open, session creation, or a session swap that closes the current one.
- **Config / env:** n/a.
- **Edge cases / guards:** Resuming a cold session mid-turn is refused by the busy guard.
- **Rebuild notes:** n/a.

### `/image`  `id: tui.slash-image`
- **Surface:** TUI
- **Where:** composer; help `attach an image`.
- **What it does:** Attaches an image from a path to the next message.
- **How it works:** `session.ts:211-215` → `ctx.composer.attachImagePath(arg)`; normalisation in `src/domain/attachments.ts`.
- **Inputs / options:** `/image <path>`.
- **Outputs / side effects:** Attachment chip.
- **Config / env:** `HERMES_TUI_IMAGE` does the same at startup.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/personality`  `id: tui.slash-personality`
- **Surface:** TUI / Config
- **Where:** composer; help `switch personality for this session`.
- **What it does:** Swaps the agent personality for the current session.
- **How it works:** `session.ts:217-236` → `config.set {key:'personality', session_id, value}`; on `history_reset` it calls `ctx.session.resetVisibleHistory(r.info)` and appends ` · transcript cleared`.
- **Inputs / options:** `/personality <name>`.
- **Outputs / side effects:** `personality: <value|default>`; possibly a cleared transcript.
- **Config / env:** `display.personality`.
- **Edge cases / guards:** Bare `/personality` is a no-op (returns immediately).
- **Rebuild notes:** n/a.

### `/compress`  `id: tui.slash-compress`
- **Surface:** TUI
- **Where:** composer; help `compress transcript`.
- **What it does:** Compresses the conversation context, optionally focused on a topic.
- **How it works:** `session.ts:238-290` → `session.compress {session_id, focus_topic?}`. A returned `messages` array replaces the transcript (`toTranscriptMessages`, prefixed with `introMsg(info)` when info is present); `info` and `usage` patch the UI state. Output preference: `r.summary.headline` (prefixed `✓ ` unless `summary.noop`), then indented `summary.token_line` and `summary.note`; else `compressed <N> messages · <K> tok`; else `nothing to compress`.
- **Inputs / options:** `/compress`; `/compress <focus topic>`.
- **Outputs / side effects:** Backend context compression; the status bar's `cmp N` counter increments.
- **Config / env:** auto-compression config.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Return the rebuilt message list from the server so the client view can't drift.

### `/branch`, `/fork`  `id: tui.slash-branch`
- **Surface:** TUI
- **Where:** composer; help `branch the session`.
- **What it does:** Forks the conversation into a new session and switches to it.
- **How it works:** `session.ts:292-312` → `session.branch {name, session_id}`; closes the previous session, sets `ui.sid` to the new id, resets `sessionStartedAt`, prints `branched → <title>`.
- **Inputs / options:** `/branch [name]`, `/fork [name]`.
- **Outputs / side effects:** New session; previous one closed.
- **Config / env:** n/a.
- **Edge cases / guards:** No `session_id` in the response → silent no-op.
- **Rebuild notes:** n/a.

### `/voice`  `id: tui.slash-voice`
- **Surface:** TUI / Config
- **Where:** composer; help `voice mode: [on|off|tts|status]`.
- **What it does:** Enables/disables voice mode and TTS, or reports status.
- **How it works:** `session.ts:314-409` → `voice.toggle {action}`. The response's `record_key` is parsed and pushed into state so `useInputHandlers()` picks up a changed binding immediately (rather than waiting for the ~5 s config mtime poll); the label falls back to `Ctrl+B` for display. Output shapes mirror the CLI: `status` prints `Voice Mode Status`, `  Mode:       ON|OFF`, `  TTS:        ON|OFF`, `  Record key: <label>`, then a blank line, `  Requirements:` and each non-blank line of `r.details` indented four spaces. `tts` prints `Voice TTS enabled.` / `Voice TTS disabled.` `on`/`off` print `Voice mode enabled[ (TTS enabled)]`, `  <RecordKey> to start/stop recording`, an optional backend-sourced `  <stop_hint>`, `  /voice tts  to toggle speech output`, `  /voice off  to disable voice mode`; or `Voice mode disabled.`
- **Inputs / options:** bare (→ `status`), `on`, `off`, `tts`, `status`; any other value also falls back to `status`.
- **Outputs / side effects:** Voice subsystem state; the status bar's voice badge.
- **Config / env:** `voice.record_key`, `voice.stop_phrases` (an empty list disables the spoken-stop hint), STT/TTS provider config.
- **Edge cases / guards:** `record_key` is only pushed into state when the response actually carries it, so an older gateway can't clobber a custom binding back to the default.
- **Rebuild notes:** Render the CONFIGURED key everywhere, never a hardcoded one, and surface provider-availability details in the status output.

### `/pet`  `id: tui.slash-pet`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle / adopt / resize an animated pet`; usage `/pet [toggle | list | scale <n> | <slug>]`.
- **What it does:** Toggles the pet overlay, opens the gallery picker, resizes, or adopts a specific pet.
- **How it works:** `session.ts:411-434`. `list` → `patchOverlayState({petPicker: true})`. Everything else (including bare `/pet` and `/pet toggle`) goes to the slash worker via `slash.exec {command, session_id}`, whose output (or `/pet: no output`) is printed, prefixed `warning: <w>\n` when a warning is present.
- **Inputs / options:** `/pet`; `/pet toggle`; `/pet list`; `/pet scale <n>`; `/pet <slug>`.
- **Outputs / side effects:** `display.pet.enabled` and pet selection persisted.
- **Config / env:** `display.pet.*`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/theme`  `id: tui.slash-theme`
- **Surface:** TUI / Config
- **Where:** composer; help `pin light/dark mode or trust auto-detection (usage: /theme [auto|light|dark])`; usage `/theme [auto|light|dark]`.
- **What it does:** Pins the light/dark polarity or restores auto-detection.
- **How it works:** `session.ts:436-471`. Bare → `config.get {key:'theme'}` → `theme: <value|auto>`. Otherwise `config.set {key:'theme', value}` and — only after the write is confirmed — `applyConfiguredTuiTheme(value)` then `theme → <value>`.
- **Inputs / options:** bare, `auto`, `light`, `dark`.
- **Outputs / side effects:** Live repaint in the new polarity; `theme` persisted.
- **Config / env:** `display.theme`, `HERMES_TUI_THEME`, `COLORFGBG`, OSC 11 probe.
- **Edge cases / guards:** Anything else → `usage: /theme [auto|light|dark]`. Applying only after confirmation is deliberate: a failed write must not leave the session showing a theme that reverts on restart.
- **Rebuild notes:** Confirm-then-apply for anything persisted, optimistic-then-correct only for ephemeral UI state.

### `/skin`  `id: tui.slash-skin`
- **Surface:** TUI / Config
- **Where:** composer; help `switch theme skin (fires skin.changed)`.
- **What it does:** Switches the full color/brand skin, live.
- **How it works:** `session.ts:473-487`. Bare → `config.get {key:'skin'}` → `skin: <value|default>`. Otherwise `config.set {key:'skin', value}` → `skin → <value>`; the backend emits a `skin.changed` event that repaints the TUI.
- **Inputs / options:** `/skin`; `/skin <name>` (e.g. `/skin ares`).
- **Outputs / side effects:** Whole-UI repaint; `display.skin` persisted.
- **Config / env:** `display.skin`.
- **Edge cases / guards:** The TUI honors the banner palette, UI colors, prompt glyph/color, session display, completion menu, selection bg, `tool_prefix` and `help_header` skin keys.
- **Rebuild notes:** Push a `skin.changed` event rather than polling for the change.

### `/indicator`  `id: tui.slash-indicator`
- **Surface:** TUI / Config
- **Where:** composer; help `pick the busy indicator: kaomoji (default), emoji, unicode (braille), or ascii`; usage `/indicator [kaomoji|emoji|unicode|ascii]`.
- **What it does:** Chooses the busy-indicator animation style.
- **How it works:** `session.ts:489-524`. Bare → `config.get {key:'indicator'}` → `indicator: <value|kaomoji>`. Otherwise `config.set {key:'indicator', value}` → `patchUiState({indicatorStyle})` (hot swap, no waiting for the 5 s mtime poll) → `indicator → <value>`.
- **Inputs / options:** bare, `kaomoji`, `emoji`, `unicode`, `ascii`.
- **Outputs / side effects:** `display.tui_status_indicator` persisted.
- **Config / env:** `display.tui_status_indicator`.
- **Edge cases / guards:** Unknown → `usage: /indicator [kaomoji|emoji|unicode|ascii]`.
- **Rebuild notes:** n/a.

### `/yolo`  `id: tui.slash-yolo`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle yolo mode (per-session approvals)`.
- **What it does:** Toggles per-session auto-approval of tool calls.
- **How it works:** `session.ts:526-534` → `config.set {key:'yolo', session_id}` (no value = toggle) → `yolo on` when `r.value === '1'`, else `yolo off`.
- **Inputs / options:** none.
- **Outputs / side effects:** Approval prompts stop firing; `⚠ YOLO` appears in the status bar and the startup banner.
- **Config / env:** `HERMES_YOLO_MODE=1`, `hermes --yolo`.
- **Edge cases / guards:** Also bound to `Shift+Tab`.
- **Rebuild notes:** n/a.

### `/reasoning`  `id: tui.slash-reasoning`
- **Surface:** TUI / Config
- **Where:** composer; help `inspect or set reasoning effort (updates live agent)`.
- **What it does:** Reads or sets reasoning effort, or the show/hide display mode, at session or global scope.
- **How it works:** `session.ts:536-574`. Bare → `config.get {key:'reasoning', session_id}` → `reasoning: <value> · display <display|hide>`. Otherwise `reasoningConfigPayload(arg, sid)` (`session.ts:43-77`) splits out `--global` (scope `global`) and `--session` (scope `session`, the default, accepted for parity with `/model`) and sends `{key:'reasoning', session_id, value, scope?}`. A resulting value of `hide` sets `sections.thinking = 'hidden'` + `showReasoning: false`; `show` sets `expanded` + `true`.
- **Inputs / options:** `/reasoning`; `/reasoning <effort>`; `/reasoning show`; `/reasoning hide`; any of the above with `--session` or `--global`.
- **Outputs / side effects:** `reasoning: <value>`; live agent updated.
- **Config / env:** `reasoning` / `reasoning_effort`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Reuse the `--session`/`--global` scope vocabulary across every scoped setting.

### `/fast`  `id: tui.slash-fast`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle fast mode [normal|fast|status|on|off|toggle]`.
- **What it does:** Switches the model service tier between normal and priority/fast.
- **How it works:** `session.ts:576-618`. Bare/`status` → `config.get {key:'fast', session_id}` → `fast mode: fast|normal`. Otherwise `config.set {key:'fast', session_id, value:mode}` → `fast mode: <next>` and patches `ui.info.fast` / `ui.info.service_tier` (`'priority'` or `''`), which drives the ` fast` suffix on the status bar's model label.
- **Inputs / options:** bare, `status`, `normal`, `fast`, `on`, `off`, `toggle`.
- **Outputs / side effects:** Service tier changed.
- **Config / env:** the `fast` key.
- **Edge cases / guards:** Anything else → `usage: /fast [normal|fast|status|on|off|toggle]`.
- **Rebuild notes:** n/a.

### `/busy`  `id: tui.slash-busy`
- **Surface:** TUI / Config
- **Where:** composer; help `control busy enter mode [queue|steer|interrupt|status]`.
- **What it does:** Decides what pressing Enter does while the agent is running.
- **How it works:** `session.ts:620-653`. Bare/`status` → `config.get {key:'busy'}` → `busy input mode: <value|interrupt>`. Otherwise `config.set {key:'busy', value}` → `busy input mode: <next>`.
- **Inputs / options:** bare, `status`, `queue`, `steer`, `interrupt`.
- **Outputs / side effects:** Enter semantics while busy.
- **Config / env:** the `busy` key; the TUI's own default state is `busyInputMode: 'queue'` (`src/app/uiStore.ts:377`) while the backend reports `interrupt` as its fallback.
- **Edge cases / guards:** Anything else → `usage: /busy [queue|steer|interrupt|status]`.
- **Rebuild notes:** n/a.

### `/verbose`  `id: tui.slash-verbose`
- **Surface:** TUI / Config
- **Where:** composer; help `cycle verbose tool-output mode (updates live agent)`.
- **What it does:** Cycles (or sets) how much tool output the agent prints.
- **How it works:** `session.ts:655-663` → `config.set {key:'verbose', session_id, value: arg || 'cycle'}` → `verbose: <value>`.
- **Inputs / options:** bare (cycle) or an explicit mode string passed straight through.
- **Outputs / side effects:** Live agent tool-progress mode.
- **Config / env:** `HERMES_TUI_TOOL_PROGRESS` sets the launch default (`verbose`/`off`).
- **Edge cases / guards:** `/focus` stashes and restores this mode.
- **Rebuild notes:** n/a.

### `/usage`  `id: tui.slash-usage`
- **Surface:** TUI
- **Where:** composer; help `session usage + Nous credits`.
- **What it does:** Shows a token/cost/context panel plus the Nous balance.
- **How it works:** `session.ts:665-758` → `session.usage {session_id}`. Patches `ui.usage`. Balance: when `r.usage.available` and (`usageBarsText()` produced lines or `status === 'free'`), it renders a `Balance` panel with `Plan: <plan_name|Free>[ · renews <renews_display>]`, the two-bar dollar view (`usageBarsText`, `src/components/overlayPrimitives.tsx`), and a status note — `> Free · free models only. Run /subscription to reach paid models.` or `! Low balance · <total_spendable_display|under $5> left. Run /topup or /subscription.` Otherwise it falls back to a `Nous balance` panel built from `r.credits_lines`. Then, when `r.calls` is non-zero, a `Usage` panel with rows `Model`, `Input tokens`, `Output tokens`, `Total tokens`, `API calls` (locale-formatted), plus `Context: <used> / <max> (<pct>%)` and `Compressions: <N>` when present. Always ends with the CTA `Run /subscription to change plan · /topup to add to your balance`.
- **Inputs / options:** none.
- **Outputs / side effects:** One or two panels plus the CTA.
- **Config / env:** portal login for the balance block.
- **Edge cases / guards:** With zero API calls and no balance block it prints `no API calls yet` before the CTA. The balance block is agent-independent (a portal fetch), so it shows on resumed sessions too.
- **Rebuild notes:** Prefer the structured dollar model over legacy text lines, but keep the fallback so an older backend still shows a balance.

### `/stop`  `id: tui.slash-stop`
- **Surface:** TUI
- **Where:** composer; help `stop background processes`.
- **What it does:** Kills the session's background processes.
- **How it works:** `src/app/slash/commands/ops.ts:65-80` → `process.stop {}` → `stopped <N> background process(es)`.
- **Inputs / options:** none.
- **Outputs / side effects:** Processes terminated.
- **Config / env:** n/a.
- **Edge cases / guards:** Singular/plural handled.
- **Rebuild notes:** n/a.

### `/reload-mcp`, `/reload_mcp`  `id: tui.slash-reload-mcp`
- **Surface:** TUI
- **Where:** composer; help `reload MCP servers in the live session (warns about prompt cache invalidation)`.
- **What it does:** Reconnects MCP servers without restarting the session, behind a confirmation gate.
- **How it works:** `ops.ts:82-127` → `reload.mcp {session_id, confirm?, always?}`. `now`/`approve`/`once`/`yes` set `confirm: true`; `always` also sets `always: true` (persisting `approvals.mcp_reload_confirm = false`). Response `confirm_required` → prints `r.message` or `/reload-mcp requires confirmation`; `reloaded` → `MCP servers reloaded` (or `MCP servers reloaded · future /reload-mcp will run without confirmation` when `always`); anything else → `reload complete`.
- **Inputs / options:** bare, `now`, `approve`, `once`, `yes`, `always`.
- **Outputs / side effects:** MCP reconnection; prompt cache invalidation.
- **Config / env:** `approvals.mcp_reload_confirm`.
- **Edge cases / guards:** The confirmation exists because reloading invalidates the provider prompt cache.
- **Rebuild notes:** Offer `once` and `always` on any confirmation gate.

### `/reload`  `id: tui.slash-reload`
- **Surface:** TUI
- **Where:** composer; help `re-read ~/.hermes/.env into the running gateway (CLI parity)`.
- **What it does:** Re-reads `~/.hermes/.env` so newly added API keys take effect without a restart.
- **How it works:** `ops.ts:129-145` → `reload.env {}` → `reloaded .env (<N> var(s) updated)`.
- **Inputs / options:** none.
- **Outputs / side effects:** The gateway process's environment is updated.
- **Config / env:** `~/.hermes/.env`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/browser`  `id: tui.slash-browser`
- **Surface:** TUI / Config
- **Where:** composer; help `manage browser CDP connection [connect|disconnect|status]`.
- **What it does:** Connects the browser tool to a live Chromium-family browser over the Chrome DevTools Protocol.
- **How it works:** `ops.ts:147-198` → `browser.manage {action, session_id, url?}`. Default `url` for `connect` is `http://127.0.0.1:9222`. Before connecting it prints `checking Chromium-family browser remote debugging at <url>...`. `status` → `browser connected: <url|(url unavailable)>` or `browser not connected (try /browser connect <url> or set browser.cdp_url in config.yaml)`. `disconnect` → `browser disconnected`. A successful connect prints `Browser connected to live Chromium-family browser via CDP`, `Endpoint: <url|(url unavailable)>`, `next browser tool call will use this CDP endpoint`.
- **Inputs / options:** `/browser` (= status), `/browser status`, `/browser connect [url]`, `/browser disconnect`.
- **Outputs / side effects:** CDP attachment for the browser tool.
- **Config / env:** `browser.cdp_url` for a persistent setting.
- **Edge cases / guards:** Anything else → `usage: /browser [connect|disconnect|status] [url] · persistent: set browser.cdp_url in config.yaml`. Without a session the bundled `r.messages` are flushed to the transcript because there is no `browser.progress` event stream to subscribe to.
- **Rebuild notes:** n/a.

### `/rollback`  `id: tui.slash-rollback`
- **Surface:** TUI
- **Where:** composer; help `list, diff, or restore checkpoints`.
- **What it does:** Lists workspace checkpoints, diffs one against the working tree, or restores one (optionally a single file).
- **How it works:** `ops.ts:200-290`. Bare/`list`/`ls` → `rollback.list {session_id}` → a `Rollback checkpoints` panel of rows `<idx>. <hash[0:10]>` / `<timestamp> · <message>` (or `(no metadata)`). `diff <hash>` → `rollback.diff {hash, session_id}` → a pager titled `Rollback diff` containing `stat` and the rendered diff. Otherwise the first token is a hash and the rest is an optional file path → `rollback.restore {hash, session_id, file_path?}` → `rollback restored <file|workspace>: <reason|message|restored_to|'restored'>`, and when `history_removed > 0` the client transcript is trimmed.
- **Inputs / options:** `/rollback`; `/rollback list|ls`; `/rollback diff <checkpoint>`; `/rollback <hash> [file path]`.
- **Outputs / side effects:** Files restored on disk.
- **Config / env:** `checkpoints` enablement (`hermes --tui --checkpoints` sets `HERMES_TUI_CHECKPOINTS=1`).
- **Edge cases / guards:** No session → `no active session — nothing to rollback`; disabled → `checkpoints are not enabled`; none found → `no checkpoints found`; `diff` with no hash → `usage: /rollback diff <checkpoint>`; empty diff → `no changes since this checkpoint`; failure → `rollback failed: <error|message|'unknown error'>`.
- **Rebuild notes:** n/a.

### `/agents`, `/tasks`  `id: tui.slash-agents`
- **Surface:** TUI
- **Where:** composer; help `open the spawn-tree dashboard (live audit + kill/pause controls)`.
- **What it does:** Opens the agents overlay, or pauses/resumes/reports delegation directly.
- **How it works:** `ops.ts:292-326`. `pause`/`resume`/`unpause` → `delegation.pause {paused}` → `applyDelegationStatus({paused})` and `delegation · paused|resumed`. `status` → reads the local store → `delegation · paused|active · caps d<maxSpawnDepth|?>/<maxConcurrentChildren|?>`. Anything else (including bare) → `patchOverlayState({agents:true, agentsInitialHistoryIndex:0})`.
- **Inputs / options:** bare, `pause`, `resume`, `unpause`, `status`.
- **Outputs / side effects:** Delegation gate toggled; overlay opened.
- **Config / env:** `max_spawn_depth`, `max_concurrent_children`.
- **Edge cases / guards:** The explicit sub-commands deliberately skip the overlay so scripts and multi-step flows can drive delegation without entering interactive mode.
- **Rebuild notes:** Give every interactive overlay a non-interactive command path.

### `/journey`, `/learning`, `/memory-graph`  `id: tui.slash-journey`
- **Surface:** TUI
- **Where:** composer; help `open your learning journey — skills + memories on a timeline`.
- **What it does:** Opens the journey overlay.
- **How it works:** `ops.ts:328-336` → `patchOverlayState({journey: true})`.
- **Inputs / options:** none.
- **Outputs / side effects:** Overlay open.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### `/replay`  `id: tui.slash-replay`
- **Surface:** TUI
- **Where:** composer; help `replay a completed spawn tree · `/replay [N|last|list|load <path>]``.
- **What it does:** Re-opens a completed spawn tree in the agents overlay, from memory or from disk.
- **How it works:** `ops.ts:338-422`. `list`/`ls` → `spawn_tree.list {limit: 30, session_id: sid ?? 'default'}` → a panel titled `Archived spawn trees` with rows `<localeString(finished_at*1000)> · <count>×` / `<label|"<count> subagents">\n  <path>`. `load <path>` → `spawn_tree.load {path}` → `pushDiskSnapshot(r, path)` then opens the overlay at history index 1. Bare or `last` → in-memory index 1; a number → that index.
- **Inputs / options:** `/replay`; `/replay last`; `/replay <N>`; `/replay list`; `/replay ls`; `/replay load <path>`.
- **Outputs / side effects:** Overlay open with a specific history index.
- **Config / env:** spawn-tree archive location.
- **Edge cases / guards:** `load` with no path → `usage: /replay load <path>`; empty snapshot → `snapshot empty or unreadable`; no archives → `no archived spawn trees on disk for this session`; no in-memory history → `no completed spawn trees this session · try /replay list`; bad index → `replay: index out of range 1..<N> · use /replay list for disk`.
- **Rebuild notes:** Keep both an in-memory ring and an on-disk archive, and make the index space explicit in the error.

### `/replay-diff`  `id: tui.slash-replay-diff`
- **Surface:** TUI
- **Where:** composer; help `diff two completed spawn trees · `/replay-diff <baseline> <candidate>` (indexes from /replay list or history N)`.
- **What it does:** Compares two archived spawn trees side by side in the agents overlay.
- **How it works:** `ops.ts:424-457` — resolves both tokens against the in-memory history, then `setDiffPair({baseline, candidate})` and opens the overlay at index 0.
- **Inputs / options:** `/replay-diff <a> <b>` (1-based indices).
- **Outputs / side effects:** Overlay open in diff mode.
- **Config / env:** n/a.
- **Edge cases / guards:** Wrong arity → `usage: /replay-diff <a> <b>  (e.g. /replay-diff 1 2 for last two)`; unresolvable → `replay-diff: could not resolve indices · history has <N> entries`.
- **Rebuild notes:** n/a.

### `/reload-skills`, `/reload_skills`  `id: tui.slash-reload-skills`
- **Surface:** TUI
- **Where:** composer; help `re-scan installed skills in the live TUI gateway`.
- **What it does:** Rescans installed skills and refreshes the slash-command catalog.
- **How it works:** `ops.ts:459-491` → `skills.reload {}` → a pager titled `Reload Skills` with `r.output` (or `skills reloaded`), then `commands.catalog {}` → `ctx.local.setCatalog({canon, categories, pairs, skillCount, sub})`.
- **Inputs / options:** none.
- **Outputs / side effects:** Skill registry + completion catalog refreshed.
- **Config / env:** n/a.
- **Edge cases / guards:** A failed catalog refresh is swallowed.
- **Rebuild notes:** Refresh the completion catalog in the same breath as the registry, or completions go stale.

### `/skills`  `id: tui.slash-skills`
- **Surface:** TUI
- **Where:** composer; help `browse, inspect, install skills`.
- **What it does:** Opens the Skills Hub, or runs one of the typed sub-commands.
- **How it works:** `ops.ts:493-670`. Bare → `patchOverlayState({skillsHub: true})`. `list` → `skills.manage {action:'list'}` → a `Skills` panel with one section per category (`{items, title}`) or `no skills available`. `inspect <name>` → `{action:'inspect', query}` → a `Skill` panel with rows `Name`, `Category`, `Path` plus the description, or `unknown skill: <query>`. `search <query>` → `{action:'search', query}` → a `Search: <query>` panel of `[name, description]` rows, or `no results for: <query>`. `install <name-or-url>` → prints `installing <query>…` then `{action:'install', query}` → `installed <name>` or `install failed`. `browse [page]` → prints `fetching community skills (scans 6 sources, may take ~15s)…` then `{action:'browse', page}` → a `Browse Skills[ — p<N>]` panel of `[name[ · trust], description[:160]]` rows plus a footer joining `page <p> of <total_pages>`, `<total> skills total` and `/skills browse <p+1> for more`; empty → `no skills on page <N> (total <T>)`. Any other sub-command goes to the slash worker (`slash.exec`), whose output is paged when longer than 180 chars or 2 non-empty lines.
- **Inputs / options:** `/skills`; `/skills list`; `/skills inspect <name>`; `/skills search <query>`; `/skills install <name|url>`; `/skills browse [page]`; anything else.
- **Outputs / side effects:** Skill installation writes to disk.
- **Config / env:** n/a.
- **Edge cases / guards:** Usage strings verbatim: `usage: /skills inspect <name>`; `usage: /skills search <query>`; `usage: /skills install <name or url>`; `usage: /skills browse [page]  (page must be a positive number)`.
- **Rebuild notes:** n/a.

### `/plugins`  `id: tui.slash-plugins`
- **Surface:** TUI
- **Where:** composer; help `view & toggle plugins (no arg opens the hub; enable/disable <name> for direct toggle)`.
- **What it does:** Opens the Plugins Hub, or forwards a sub-command to the text slash worker.
- **How it works:** `ops.ts:672-698`. Bare → `patchOverlayState({pluginsHub: true})`. Otherwise `slash.exec {command, session_id}` → output printed as a line, or paged (title `Plugins`) when longer than 180 chars / 2 non-empty lines; `/plugins: no output` when empty; a warning is prefixed as `warning: <w>\n`.
- **Inputs / options:** `/plugins`; `/plugins <anything>` (enable/disable/list/install/…).
- **Outputs / side effects:** Plugin state changes.
- **Config / env:** plugin config.
- **Edge cases / guards:** Kept at parity with `hermes plugins`.
- **Rebuild notes:** n/a.

### `/tools`  `id: tui.slash-tools`
- **Surface:** TUI
- **Where:** composer; help `enable or disable tools (client-side history reset on change)`.
- **What it does:** Enables or disables toolsets / individual MCP tools for the session, resetting the visible history when the tool set changes.
- **How it works:** `ops.ts:700-761`. Sub-commands other than `enable`/`disable` go to the slash worker (paged as `Tools` when long). `enable|disable <names…>` → `tools.configure {action, names, session_id}`. On `r.info` it resets `sessionStartedAt` and calls `resetVisibleHistory(r.info)`; then prints, in order, `enabled|disabled: <changed…>`, `unknown toolsets: <unknown…>`, `missing MCP servers: <missing_servers…>`, and `session reset. new tool configuration is active.` when `r.reset`.
- **Inputs / options:** `/tools`; `/tools <anything>`; `/tools enable <name> [name …]`; `/tools disable <name> [name …]`.
- **Outputs / side effects:** Tool availability changes; session history reset.
- **Config / env:** toolset config.
- **Edge cases / guards:** With no names it prints three lines verbatim: `usage: /tools <enable|disable> <name> [name ...]`, `built-in toolset: /tools <enable|disable> web`, `MCP tool: /tools <enable|disable> github:create_issue`.
- **Rebuild notes:** Changing the tool set invalidates the conversation's tool schema — reset the history rather than pretending it is compatible.

### `/wake`  `id: tui.slash-wake`
- **Surface:** TUI / Config
- **Where:** composer; help `toggle the 'Hey Hermes' wake word listener [on|off|status]`; usage `/wake [on|off|status]`.
- **What it does:** Arms or disarms the wake-word listener for this surface and reports its state.
- **How it works:** `src/app/slash/commands/wake.ts`. `on` → `setWakeUserDisabled(false)` then `wake.start {persist: true, surface: 'tui'}` → `wake: listening[ for “<phrase>”][ · <provider>][ · enabled in config]`; failure → `startFailureLine(r)` = `wake: not started — <reason text>[ (owned by <surface>)][ — <hint>]` with reason text mapped from `START_REASON_TEXT`: `disabled` → `disabled (config wake_word.enabled)`, `disabled_for_surface` → `scoped to another surface (config wake_word.surface)`, `not_owner` → `another surface owns the listener`, `owned` → `another surface owns the listener`, `unavailable` → `unavailable`; unknown codes fall through to the raw reason. `off` → `setWakeUserDisabled(true)` then `wake.stop {persist:true}` → `wake: listener off[ · disabled in config]` or `wake: nothing to stop — <this surface doesn’t own the listener | reason | 'not running'>[ · disabled in config]`. `status`/bare → `wake.status {}` → one of: `wake: listening[ for “<phrase>”][ · <provider>]`; `wake: listening… · ⚠ mic delivers only silence[ — <hint>]`; `wake: off here · listener owned by <surface>[ for “<phrase>”][ · <provider>]`; `wake: unavailable[ — <hint>]`; `wake: off[ for “<phrase>”][ · <provider>] · /wake on to arm`.
- **Inputs / options:** bare (= status), `on`, `off`, `status`.
- **Outputs / side effects:** Microphone listener started/stopped; `wake_word.enabled` persisted on explicit gestures only (reconnect auto-arm never persists). `src/app/wakeState.ts` remembers an explicit opt-out so gateway reconnects don't re-arm behind the user's back.
- **Config / env:** `wake_word.enabled`, `wake_word.surface`, `wake_word.phrase`, STT provider config.
- **Edge cases / guards:** Anything else → `usage: /wake [on|off|status]`.
- **Rebuild notes:** Model listener ownership explicitly (one surface at a time) and remember the user's explicit "off" separately from the config value.

### `/setup`  `id: tui.slash-setup`
- **Surface:** TUI
- **Where:** composer; help `run full setup wizard (launches `hermes setup`)`.
- **What it does:** Suspends the TUI, runs the real `hermes setup` wizard on the terminal, then resumes and starts a session.
- **How it works:** `src/app/slash/commands/setup.ts` → `runExternalSetup({args: ['setup', ...arg.split(/\s+/).filter(Boolean)], ctx, done: 'setup complete — starting session…', launcher: launchHermesCommand, suspend: withInkSuspended})`. `src/app/setupHandoff.ts` (54 lines) coordinates the suspend/launch/resume; `src/lib/externalCli.ts` spawns `hermes <args>`; `withInkSuspended` (from `@hermes/ink`) unmounts the render loop and restores the terminal so the wizard owns stdin/stdout.
- **Inputs / options:** `/setup`; `/setup <extra args>` (forwarded verbatim to `hermes setup`).
- **Outputs / side effects:** Config written by the wizard; on completion `setup complete — starting session…` and a session starts.
- **Config / env:** whatever `hermes setup` writes.
- **Edge cases / guards:** Also offered from the "Setup Required" panel (see below).
- **Rebuild notes:** Suspend the TUI and hand the real TTY to the child rather than reimplementing the wizard.

### "Setup Required" panel  `id: tui.setup-required`
- **Surface:** TUI
- **Where:** shown at startup when no model provider is configured. Title verbatim: `Setup Required`.
- **What it does:** Explains that a model provider is missing and offers three ways forward.
- **How it works:** `src/content/setup.ts`. `SETUP_REQUIRED_TITLE = 'Setup Required'`; `buildSetupRequiredSections()` returns a text section `Hermes needs a model provider before the TUI can start a session.` and an `Actions` section with rows: `/model` / `configure provider + model in-place`; `/setup` / `run full first-time setup wizard in-place`; `Ctrl+C` / `exit and run \`hermes setup\` manually`.
- **Inputs / options:** the three actions above.
- **Outputs / side effects:** Display only.
- **Config / env:** provider credentials.
- **Edge cases / guards:** The TUI still starts and accepts typing; only session creation is blocked.
- **Rebuild notes:** Name the missing precondition and give an in-place fix, an interactive fix, and an escape hatch.

### `/heapdump`  `id: tui.slash-heapdump`
- **Surface:** TUI
- **Where:** composer; help `write a V8 heap snapshot + memory diagnostics (see HERMES_HEAPDUMP_DIR)`.
- **What it does:** Writes a heap snapshot and a diagnostics file for OOM debugging.
- **How it works:** `src/app/slash/commands/debug.ts:47-68`. Prints `writing heap dump (heap <X> · rss <Y>)…` then `performHeapDump('manual')` → `heapdump: <heapPath>` and `diagnostics: <diagPath>`, or `heapdump failed: <error|'unknown error'>`.
- **Inputs / options:** none.
- **Outputs / side effects:** Two files on disk.
- **Config / env:** `HERMES_HEAPDUMP_DIR`, `HERMES_HEAPDUMP_ON_START`.
- **Edge cases / guards:** Results are dropped if the session went stale.
- **Rebuild notes:** n/a.

### `/theme-info`  `id: tui.slash-theme-info`
- **Surface:** TUI
- **Where:** composer; help `print live theme diagnostics (background probe, light mode, palette)`.
- **What it does:** Prints exactly what the theme system detected and chose.
- **How it works:** `debug.ts:70-93` → a `Theme` panel with rows: `OSC-11 background` / `terminalBackgroundHex() ?? '(no reply)'`; `HERMES_TUI_BACKGROUND`; `HERMES_TUI_THEME`; `COLORFGBG`; `TERM_PROGRAM` (each `?? '(unset)'`); `detected mode` / `light|dark` from `detectLightMode()`; then `text`, `completionBg`, `selectionBg`, `statusBg` from the live theme.
- **Inputs / options:** none.
- **Outputs / side effects:** One panel.
- **Config / env:** `HERMES_TUI_BACKGROUND`, `HERMES_TUI_THEME`, `COLORFGBG`, `TERM_PROGRAM`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Expose every input to an auto-detection heuristic in one command — otherwise "wrong colors" is unreportable.

### `/mem`  `id: tui.slash-mem`
- **Surface:** TUI
- **Where:** composer; help `print live V8 heap + rss numbers`.
- **What it does:** Prints the process's live memory figures.
- **How it works:** `debug.ts:95-114` → a `Memory` panel with rows `heap used`, `heap total`, `external`, `array buffers`, `rss` (all via `formatBytes`) and `uptime` (`<N>s`).
- **Inputs / options:** none.
- **Outputs / side effects:** One panel.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Slash dispatch and fallback chain  `id: tui.slash-dispatch`
- **Surface:** TUI / Core
- **Where:** every `/…` the user submits.
- **What it does:** Resolves a slash command through TUI-owned commands → widget apps → the gateway's alias/canon catalog (with fuzzy resolution) → `slash.exec` → `command.dispatch`.
- **How it works:** `src/app/createSlashHandler.ts`. Each invocation bumps `slashFlightRef.current`; `stale()` is true when a newer invocation started OR the session id changed, and `guarded`/`guardedErr` drop late results (errors print `error: <rpcErrorMessage(e)>`). Order: (1) `findSlashCommand(parsed.name)` over names+aliases; (2) `getWidgetApp(parsed.name)` → `launchWidget`; (3) `catalog.canon` exact alias match → re-dispatch on the canonical name; (4) tiered fuzzy scoring over `catalog.canon` using `scoreSlashMenuItem` filtered to `score < 3` (name tiers only — description tiers never auto-execute), keeping only the best tier: exactly one match → re-dispatch; more than one → `ambiguous command: <up to 6 comma-joined>[, …]`; (5) `slash.exec {command: cmd.slice(1), session_id}`; (6) on RPC failure, `command.dispatch {arg, name, session_id}`. Dispatch payloads (`asCommandDispatch`, `src/lib/rpc.ts`): `exec`/`plugin` → print `d.output || '(no output)'`; `alias` → re-dispatch `/${d.target}<argTail>`; `skill` → send `d.message` with `d.display` as the projected transcript line, or `/<name>: skill payload missing message`; `send` → optional `d.notice` line then send, or `/<name>: empty message`; `prefill` → optional notice then `ctx.composer.setInput(d.message)`. Plain `slash.exec` output is paged (title = capitalised command name) when longer than 180 chars or 2 non-empty lines, else printed as a line; a `warning` is prefixed as `warning: <w>\n`.
- **Inputs / options:** any `/command [args]`.
- **Outputs / side effects:** Whatever the resolved command does.
- **Config / env:** n/a.
- **Edge cases / guards:** `parseSlashCommand` lowercases the name and joins the rest as `arg` (`src/domain/slash.ts:236-240`). `looksLikeSlashCommand` is `^`-anchored: `/^\/[^\s/]*(?:\s|$)/`. Invalid dispatch shapes → `error: invalid response: command.dispatch`.
- **Rebuild notes:** Client-owned commands first, then a data-driven catalog with tiered fuzzy resolution, then the server; never let a description-only match auto-execute.

### Description-aware fuzzy scoring  `id: tui.slash-fuzzy`
- **Surface:** TUI / Core
- **Where:** the completion menu and the slash-dispatch fallback.
- **What it does:** Ranks commands by name AND by description so `/summary` surfaces a command whose description mentions summaries.
- **How it works:** `src/app/slash/fuzzyScore.ts` (ported from superagent-ai/grok-cli's `src/ui/slash-menu.ts`). `tokenizeSearchText(v)` returns the lowercased whole string plus its `[^a-z0-9]+`-split tokens. `normalizeSlashSearchQuery(q)` trims, strips leading slashes and lowercases. `scoreFields(fields, query, offset)` returns `offset` on an exact match (also matching a `/`-prefixed form), `offset+1` on a prefix match, `offset+2` on a substring match, else `Infinity`. `scoreSlashMenuItem(item, query) = min(scoreFields(id+label+aliases, q, 0), scoreFields(description, q, 3))` — so name tiers are 0/1/2 and description tiers are 3/4/5. `rankSlashItems(items, query, toScoreItem)` filters out `Infinity`, sorts by score then original index (stable), and returns the list untouched for an empty query.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Ordering only.
- **Config / env:** n/a.
- **Edge cases / guards:** Lower score wins; the dispatcher only accepts scores `< 3`.
- **Rebuild notes:** Two tier bands (name 0-2, description 3-5) with one `min()` is enough; stable-sort on the original index so equal scores keep authoring order.

---

## 8. Theme, skins and color

### Theme token model  `id: tui.theme-tokens`
- **Surface:** TUI / Core
- **Where:** `ui-tui/src/theme.ts`.
- **What it does:** Defines every color and brand token the TUI paints with, derived from a small set of identity seeds.
- **How it works:** `ThemeColors` (`theme.ts:5-50`) enumerates, in order: `primary`, `accent`, `border`, `text`, `muted`, `completionBg`, `completionCurrentBg`, `completionMetaBg`, `completionMetaCurrentBg`, `label`, `ok`, `error`, `warn`, `tool` (tool-call markers — the `●` bullet and tool spinner, defaults to `accent`), `thinking` (reasoning body text, defaults to `muted`), `syntaxString`, `syntaxNumber`, `syntaxKeyword`, `syntaxComment`, `prompt`, `sessionLabel`, `sessionBorder`, `statusBg`, `statusFg`, `statusGood`, `statusWarn`, `statusBad`, `statusCritical`, `selectionBg`, `diffAdded`, `diffRemoved`, `diffAddedWord`, `diffRemovedWord`, `shellDollar`. `ThemeBrand` (`theme.ts:52-60`): `name`, `icon`, `prompt`, `welcome`, `goodbye`, `tool`, `helpHeader`. `Theme` = `{color, brand, bannerLogo, bannerHero}`. `buildPalette(seeds, isLight)` (`theme.ts:317-367`) derives everything not explicitly seeded from `deriveTones(seeds)` — a mix ladder against the background — so "dim" is definitionally a derivative of the theme's own base colors and can never be incoherent.
- **Inputs / options:** `ThemeSeeds` (`theme.ts:278-302`): `accent`, `activeRow?`, `bg`, `border?`, `error`, `muted?`, `ok`, `primary`, `prompt?`, `selection?`, `shellDollar`, `statusBad`, `statusCritical`, `statusGood`, `statusWarn`, `surface?`, `text`, `warn`.
- **Outputs / side effects:** The palette every component reads.
- **Config / env:** skins supply the seeds.
- **Edge cases / guards:** `sessionLabel`/`sessionBorder` both track `muted` by design ("same role, same colour", issue #11300). `activeRow` derives as `mix(surface, accent, 0.22)` when a surface was seeded.
- **Rebuild notes:** Seeds → mix ladder → tokens. Enumerating a flat palette invites incoherent "dim" values across skins.

### Default brand tokens  `id: tui.brand`
- **Surface:** TUI
- **Where:** every branded string in the TUI.
- **What it does:** The default (unskinned) brand identity.
- **How it works:** `theme.ts:252-260` — `name: 'Hermes Agent'`, `icon: '⚕'`, `prompt: '❯'`, `welcome: 'Type your message or /help for commands.'`, `goodbye: 'Goodbye! ⚕'`, `tool: '┊'`, `helpHeader: '(^_^)? Commands'`.
- **Inputs / options:** overridable per skin.
- **Outputs / side effects:** Banner name, prompt glyph, `/help` panel title, tool-trail prefix.
- **Config / env:** skin keys `brand.name`, `brand.icon`, `prompt`, `tool_prefix`, `help_header`.
- **Edge cases / guards:** `cleanPromptSymbol()` collapses whitespace and falls back to the default when a skin supplies an empty glyph.
- **Rebuild notes:** Keep the brand tokens separate from the palette so a skin can change one without the other.

### Dark palette seeds  `id: tui.dark-seeds`
- **Surface:** TUI
- **Where:** the default theme.
- **What it does:** The classic Hermes gold-on-navy identity.
- **How it works:** `DARK_SEEDS` (`theme.ts:370-399`), verbatim: `accent: '#FFBF00'`, `activeRow: '#333355'`, `bg: '#101014'`, `border: '#CD7F32'`, `error: '#ef5350'`, `ok: '#4caf50'`, `primary: '#FFD700'`, `prompt: '#FFF8DC'`, `selection: '#3a3a55'`, `shellDollar: '#4dabf7'`, `statusBad: '#FF8C00'`, `statusCritical: '#FF6B6B'`, `statusGood: '#8FBC8F'`, `statusWarn: '#FFD700'`, `surface: '#1a1a2e'`, `text: '#FFF8DC'`, `warn: '#ffa726'`. Diff colors from `DIFF_DARK`: `diffAdded: 'rgb(220,255,220)'`, `diffRemoved: 'rgb(255,220,220)'`, `diffAddedWord: 'rgb(36,138,61)'`, `diffRemovedWord: 'rgb(207,34,46)'`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `DARK_THEME`.
- **Config / env:** n/a.
- **Edge cases / guards:** The navy surfaces are kept as explicit seeds because they are IDENTITY, not derivation drift.
- **Rebuild notes:** n/a.

### Light palette seeds  `id: tui.light-seeds`
- **Surface:** TUI
- **Where:** the light theme.
- **What it does:** Darker golds/ambers that stay legible on white.
- **How it works:** `LIGHT_SEEDS` (`theme.ts:401-416`), verbatim: `accent: '#956E00'`, `bg: '#ffffff'`, `border: '#A56628'`, `error: '#C14240'`, `ok: '#367E39'`, `primary: '#867000'`, `prompt: '#2B2014'`, `shellDollar: '#377BB3'`, `statusBad: '#A65A00'`, `statusCritical: '#B94D4D'`, `statusGood: '#5C7A5C'`, `statusWarn: '#867000'`, `text: '#3D2F13'`, `warn: '#956115'`. Diff colors from `DIFF_LIGHT`: `diffAdded: 'rgb(200,240,200)'`, `diffRemoved: 'rgb(240,200,200)'`, `diffAddedWord: 'rgb(27,94,32)'`, `diffRemovedWord: 'rgb(183,28,28)'`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `LIGHT_THEME`.
- **Config / env:** n/a.
- **Edge cases / guards:** These are exactly `liftForContrast(darkSeed, '#ffffff', 4.5)` — the lifts Cursor's `minimumContrastRatio` always applied — so hosts WITHOUT a contrast pass render the same thing Cursor showed for years.
- **Rebuild notes:** Derive a light palette from the dark one by luminance-clamping at a target contrast, keeping hue and saturation.

### Light-terminal detection  `id: tui.light-detection`
- **Surface:** TUI / Env
- **Where:** boot and on every theme resolve; inspect it with `/theme-info`.
- **What it does:** Decides whether the terminal background is light, and therefore which palette to use.
- **How it works:** `detectLightMode(env, lightDefaultTermPrograms)` (`theme.ts:702-762`) in strict precedence: (1) `HERMES_TUI_LIGHT` truthy/falsy; (2) `HERMES_TUI_THEME` equal to `light` or `dark`; (3) `HERMES_TUI_BACKGROUND` as a background hex → luminance `>= LUMA_LIGHT_THRESHOLD`; (4) `COLORFGBG` — the last `;`-separated field, validated as pure digits, where `7` or `15` means light and any other value in `0..15` is AUTHORITATIVELY dark (so it cannot be overridden by the next rule); (5) a `TERM_PROGRAM` light-default allow-list (empty in production). Anything undecidable stays dark. The OSC 11 background probe feeds `HERMES_TUI_BACKGROUND`-equivalent input via `terminalBackgroundHex()` from `@hermes/ink`. Docs summarise the three user-facing layers as `HERMES_TUI_THEME` → `COLORFGBG` → OSC 11 probe (`website/docs/user-guide/tui.md:161-173`).
- **Inputs / options:** `HERMES_TUI_LIGHT=1|0|true|false`, `HERMES_TUI_THEME=light|dark|<6-char bg hex>`, `HERMES_TUI_BACKGROUND=<hex>`, `COLORFGBG`, `TERM_PROGRAM`.
- **Outputs / side effects:** `DEFAULT_THEME` selection; `/theme auto|light|dark` pins it.
- **Config / env:** as above plus `display.theme`.
- **Edge cases / guards:** A malformed `COLORFGBG='15;'` is rejected by the digit test rather than coerced to `0` (which would look like an authoritative dark slot).
- **Rebuild notes:** Order the signals explicitly, validate before coercing, and default to the safer pole.

### Apple Terminal ANSI-256 normalisation  `id: tui.ansi-normalisation`
- **Surface:** TUI
- **Where:** Apple Terminal on a light profile without truecolor.
- **What it does:** Rewrites foreground tokens to `ansi256(N)` values that stay readable in a 256-color light terminal.
- **How it works:** `shouldNormalizeAnsiLightTheme(env, isLight)` requires `TERM_PROGRAM === 'Apple_Terminal'`, `COLORTERM` not `truecolor`/`24bit`, and light mode. `normalizeThemeForAnsiLightTerminal(theme, env, isLight)` then maps `ANSI_NORMALIZED_FOREGROUNDS = ['text','label','ok','error','warn','prompt','statusFg','statusGood','statusWarn','statusBad','statusCritical','shellDollar','tool']` through `normalizeAnsiForeground()` (rich 8-bit quantisation, falling back to `bestReadableAnsiColor()` when the quantised luminance exceeds `ANSI_LIGHT_MAX_LUMINANCE = 0.72`), and forces `ANSI_MUTED_FOREGROUNDS = ['muted','sessionLabel','sessionBorder','thinking']` to `ansi256(245)` (`ANSI_MUTED_BUCKET`). Constants: `ANSI_LIGHT_TARGET_LUMINANCE = 0.34`, `ANSI_LIGHT_MIN_SATURATION = 0.22`, `XTERM_6_LEVELS = [0,95,135,175,215,255]`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Tokens become `ansi256(N)` strings rather than hex.
- **Config / env:** `TERM_PROGRAM`, `COLORTERM`.
- **Edge cases / guards:** `themeToneHex(tone)` is the inverse — consumers that need a real `#rrggbb` (OSC 10/11) must go through it rather than hex-testing the tone, which would silently skip exactly the terminals that quantized.
- **Rebuild notes:** When you quantize a palette, ship the inverse function too.

### Flash-free theme boot cache  `id: tui.theme-boot`
- **Surface:** TUI
- **Where:** `$HERMES_HOME/tui-theme-boot.json` (default `~/.hermes/tui-theme-boot.json`).
- **What it does:** Persists the last resolved theme so frame one paints correctly instead of flashing default-dark → skin → detected mode.
- **How it works:** `src/lib/themeBoot.ts`. File shape `{version: 1, theme?: Theme, background?: string, mode?: 'dark'|'light'}`. `readBootTheme()` validates `version === 1` and a `looksLikeTheme()` shape (object `color` with string `text` and `primary`, object `brand` with a string `name`) and returns `null` on first launch, damage, or a test run (`VITEST` or `NODE_ENV === 'test'`). `bootTheme` seeds `uiStore`'s initial `theme` (`src/app/uiStore.ts:401` — `bootTheme ?? DEFAULT_THEME`). Writes go through a temp file + `renameSync` for atomicity. The `mode` field exists because a pinned theme would otherwise cache incoherently (a light palette next to the dark PHYSICAL background) and the next launch would flash light → dark → light.
- **Inputs / options:** n/a.
- **Outputs / side effects:** One JSON file.
- **Config / env:** `HERMES_HOME`, `display.tui_theme`.
- **Edge cases / guards:** The cache is a hint, never an authority — explicit env pins beat it and every later signal overwrites it.
- **Rebuild notes:** Cache the RESOLVED output plus the inputs that produced it, so you can tell a stale cache from a valid one.

### Skin loading (`fromSkin`)  `id: tui.skins`
- **Surface:** TUI / Config
- **Where:** `/skin <name>` and `display.skin`.
- **What it does:** Turns a shared skin definition into a TUI `Theme`.
- **How it works:** `fromSkin(...)` (`theme.ts:838+`) consumes `SkinColors` / `SkinBranding` from `@hermes/shared/skin` (the same definitions the desktop and web surfaces use). `skinIsLight(colors, env)` (`theme.ts:832-836`) uses the skin's AUTHORED background luminance when it has one (`>= LUMA_LIGHT_THRESHOLD`), otherwise falls back to `detectLightMode(env)`. `defaultThemeForCurrentBackground(env)` (`theme.ts:808+`) picks light/dark and applies the ANSI normalisation. `applyConfiguredTuiTheme(value)` (exported from `src/app/createGatewayEventHandler.ts`) applies a `/theme` pin live.
- **Inputs / options:** any built-in or custom skin name.
- **Outputs / side effects:** A whole-UI repaint; the boot cache is rewritten.
- **Config / env:** `display.skin`; the TUI honors the banner palette, UI colors, prompt glyph/color, session display, completion menu, selection bg, `tool_prefix` and `help_header` (`website/docs/user-guide/tui.md:64`).
- **Edge cases / guards:** Readability against the real background is the theme engine's job (`ensureContrast` / `liftForContrast`), not the skin's — skins contribute accent IDENTITY only.
- **Rebuild notes:** Separate identity (the skin) from readability (the engine) and enforce contrast in exactly one place.

### Color primitives  `id: tui.color-lib`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/color.ts` (325 lines), re-exported through the widget SDK.
- **What it does:** All generic color math the theme engine and widgets use.
- **How it works:** Exports `parseColor`, `toHex`, `relativeLuminance`, `contrastRatio`, `ensureContrast`, `liftForContrast`, `mix`, `desaturate`, `grayOf`. `ensureContrast` step-mixes a foreground toward the readable pole (black on light, white on dark) until it clears a threshold; `liftForContrast` clamps luminance while keeping hue and saturation.
- **Inputs / options:** hex / `rgb()` strings.
- **Outputs / side effects:** Pure functions.
- **Config / env:** n/a.
- **Edge cases / guards:** `themeToneHex` handles the `ansi256(N)` case.
- **Rebuild notes:** Keep color math in one module so both the theme engine and user widgets share the same definitions.

### Chart primitives  `id: tui.charts`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/charts.ts` (80 lines), re-exported through the widget SDK.
- **What it does:** Text charts for widgets and panels.
- **How it works:** Exports `gauge`, `hbars`, `sparkline`, `sparkRows`.
- **Inputs / options:** numeric series.
- **Outputs / side effects:** Strings.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Shimmer / skeleton loaders  `id: tui.loaders`
- **Surface:** TUI
- **Where:** the session panel's lazy sections and any widget that opts in.
- **What it does:** Animated placeholder rows shaped like the real content.
- **How it works:** `src/components/loaders.tsx` (172 lines) exports `Shimmer`, `ShimmerRows`, `shimmerSegments`, `useShimmerPhase`. `ShimmerRows` takes `rows: readonly (readonly [labelWidth, valueWidth])[]` plus `color` and `highlight`.
- **Inputs / options:** row shape tuples.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Shape skeletons like the content that replaces them.

### Widget grid layout engine  `id: tui.widget-grid`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/widgetGrid.ts` (510 lines) + `src/components/widgetGrid.tsx` (267 lines).
- **What it does:** A CSS-grid-like layout engine for the terminal: fixed and `fr` tracks, gaps, padding, and named areas.
- **How it works:** Exports `layoutWidgetGrid`, `layoutGridAreas`, `resolveGridTracks` and the types `WidgetGridItem`, `WidgetGridLayout`, `WidgetGridLayoutOptions`, `GridAreaItem`, `GridAreasLayout`, `GridAreasOptions`, `GridTrackSize`. The components `WidgetGrid` and `GridAreas` render them. Callers pass `cols`, `columns` (a count or a track list like `[leftW, {fr: 1}]`), `gap`, `rowGap`, `paddingX`, `paddingY`, and `widgets` (each `{id, children}` or `{id, render: width => node}`). Used by the banner, session panel, prompt cells, floating-overlay stack and the `/grid-test` app.
- **Inputs / options:** as above.
- **Outputs / side effects:** Computed cell rectangles.
- **Config / env:** n/a.
- **Edge cases / guards:** With one column the `maxWidth` handed to `render(width)` never binds, so panels keep their intrinsic content-hugging widths.
- **Rebuild notes:** Make every chrome surface a layout-engine surface; multi-column tiling then becomes a track change, not a rewrite.

### Overlay primitives  `id: tui.overlay-primitives`
- **Surface:** Core
- **Where:** `ui-tui/src/components/overlay.tsx` (133 lines), `overlayPrimitives.tsx` (247), `overlayControls.tsx` (50), `overlayScrollbar.tsx` (84).
- **What it does:** The shared building blocks every overlay and widget app composes from.
- **How it works:** `overlay.tsx` exports `Overlay` (viewport-level absolute placement with an optional `backdrop`, `zone` ∈ the nine `OverlayZone`s) and `Dialog` (a titled, hinted, fixed-width box). `overlayPrimitives.tsx` exports `ActionRow`, `chipRowProps(t, active)`, `listRowStyle(t, active)`, `MenuRow`, `scrollbarColors(t, hover, dragging)`, `useMenu`, and `usageBarsText(model)`. `overlayControls.tsx` exports `useOverlayKeys({disabled, onBack, onClose})` — `q` closes, `Esc` goes back if `onBack` is supplied else closes — plus `OverlayHint` (a muted, `truncate-end` line) and the windowing helpers `windowOffset(count, selected, visible)` = `clamp(selected - floor(visible/2), 0, count - visible)` and `windowItems(items, selected, visible)`.
- **Inputs / options:** as above.
- **Outputs / side effects:** Rendered nodes.
- **Config / env:** n/a.
- **Edge cases / guards:** Selection chips come from one function so every list highlights identically.
- **Rebuild notes:** One `useOverlayKeys` shared by every overlay is what makes `Esc`/`q` behave the same everywhere.

---

## 9. Transcript rendering

### Message line renderer  `id: tui.message-line`
- **Surface:** TUI
- **Where:** every transcript row.
- **What it does:** Renders one message with a role gutter glyph, optional timestamp, markdown body, tool trail, todo panel and diff/ANSI handling.
- **How it works:** `src/components/messageLine.tsx` (359 lines). Role chrome from `src/domain/roles.ts`: `assistant` → `{body: text, glyph: brand.tool ('┊'), prefix: border}`; `system` → `{body: '', glyph: '·', prefix: muted}`; `tool` → `{body: muted, glyph: '⚡', prefix: muted}`; `user` → `{body: label, glyph: brand.prompt ('❯'), prefix: label}`. Gutter and body widths come from `transcriptGutterWidth()` / `transcriptBodyWidth()` (`src/lib/inputMetrics.ts`). Long system messages collapse above `SYSTEM_COLLAPSE_CHARS = 400` behind a `▸`/`▾` chevron showing only the first line. Text is bounded by `boundedLiveRenderText()` and sanitised by `sanitizeAnsiForRender()`; text that already contains ANSI (`hasAnsi`) is rendered through `<Ansi>` verbatim rather than re-parsed as markdown. Paste-backed text (`isPasteBackedText`) is shown via `compactPreview`. Continuation rows use `└─ ` in `theme.color.border`.
- **Inputs / options:** props `cols`, `compact`, `detailsMode`, `detailsModeCommandOverride`, `isStreaming`, `liveDetails`, `msg`, `prev`, `reasoningActive`, `sections`, `t`, `timestamps`, `tools`. Clicking a collapsed system message toggles it.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.timestamps`, `display.density`, `display.details_mode`, `display.sections.*`.
- **Edge cases / guards:** `LONG_MSG = 300` and `MAX_HISTORY = 800` from `src/config/limits.ts`.
- **Rebuild notes:** Detect pre-formatted ANSI and pass it through untouched — re-parsing it as markdown corrupts tool output.

### Message timestamps  `id: tui.timestamps`
- **Surface:** TUI / Config
- **Where:** a dim `[HH:MM]` beside the gutter glyph on user and assistant rows.
- **What it does:** Stamps each message with its creation time.
- **How it works:** `fmtMsgTimestamp(createdAt)` (`messageLine.tsx:34-49`) converts a UNIX-seconds value to `[HH:MM]` with zero-padding, returning `null` for non-finite, `<= 0` or invalid dates. Deliberately the same shape as the classic CLI's default `display.timestamp_format` (`"%H:%M"`) so one config key reads identically across surfaces (issue #41531).
- **Inputs / options:** `display.timestamps`.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.timestamps` (default off — `uiStore.ts:398`).
- **Edge cases / guards:** Only user/assistant rows are stamped.
- **Rebuild notes:** n/a.

### Block grouping and blank-line rhythm  `id: tui.block-layout`
- **Surface:** TUI
- **Where:** the vertical spacing between transcript blocks.
- **What it does:** Opens exactly one blank line where the KIND of content changes, so runs of the same kind read as one section.
- **How it works:** `src/domain/blockLayout.ts`. `BlockGroup` = `'user' | 'model' | 'trail' | 'note' | 'diff' | 'slash' | 'event' | 'intro'`; `messageGroup(msg)` maps `kind` (`intro`/`panel` → `intro`, `slash`, `event`, `diff`, `trail`) then role (`user` → `user`, `assistant` → `model`, else `note`). `SELF_SPACED = {diff, event, intro, slash, user}` own their own leading gap; `PAINTS_TRAILING_GAP = {diff, event, user}` already paint a trailing blank line. `hasLeadGap(prev, cur)` is true only when `cur` is not self-spaced, a predecessor exists, the group changed, and the predecessor does not already paint a trailing gap. `blockRenders(msg, ctx)` decides whether a settled block paints anything — a `trail` with no todos and no tools/thinking, or one whose thinking+tools+activity sections all resolve to `hidden`, renders nothing. `prevRenderedMsg(msgAt, index, ctx)` walks backwards to the nearest block that actually renders, so hidden trails are transparent to grouping.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Layout only.
- **Config / env:** `display.details_mode`, `display.sections.*`.
- **Edge cases / guards:** Streaming-safe by construction — the gap depends on the PREDECESSOR's group, never on the live block's own changing content, so the streaming block computes the same gap while streaming as the settled segment does after it flushes.
- **Rebuild notes:** Derive spacing from a predecessor's group and skip invisible blocks; anything keyed on the live block's own content will jitter.

### Markdown renderer  `id: tui.markdown`
- **Surface:** TUI
- **Where:** every assistant message body and any markdown the TUI prints.
- **What it does:** Renders full markdown to styled terminal text — headings, lists, tables, code with syntax highlighting, links, LaTeX math and more.
- **How it works:** `src/components/markdown.tsx` (1178 lines), exported as `Md` (memoized). Block patterns: fenced code `` ```/~~~ `` with an info string (`FENCE_RE`, `FENCE_CLOSE_RE`); horizontal rules `HR_RE` (`^ {0,3}([-*_])(?:\s*\1){2,}\s*$`); ATX headings `HEADING_RE` (`#`..`######` with optional closing hashes); setext underlines `SETEXT_RE`; footnote definitions `FOOTNOTE_RE` (`[^id]: text`); definition lists `DEF_RE` (`: text`); bullets `BULLET_RE` (`-`, `+`, `*`); task list items `TASK_RE` (`[ ]`, `[x]`, `[X]`); ordered lists `NUMBERED_RE` (`1.` or `1)`); blockquotes `QUOTE_RE` (nestable `>`); tables with a `:?-{3,}:?` divider row (`TABLE_DIVIDER_CELL_RE`); display math `$$…$$` and `\[…\]` (`MATH_BLOCK_OPEN_RE` etc., matched only at the START of a trimmed line so prose like `$$x+y$$ followed by more` cannot open an unclosed block); the media directive `MEDIA_LINE_RE` (`MEDIA: <path>`, optionally quoted/backticked) and `AUDIO_DIRECTIVE_RE` (`[[audio_as_voice]]`). Indent depth is `floor(len(indent with tabs→2 spaces)/2)`.
- **Inputs / options:** props `cols`, `compact`, `t`, `text`.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.density` (compact).
- **Edge cases / guards:** Table layout uses `SAFETY_MARGIN = 4`, `MIN_COL_WIDTH = 3`, `COL_GAP = 2`, `TABLE_PADDING_LEFT = 2`. A cross-instance parsed-children cache (`mdCache`) is a `WeakMap<Theme, Map<string, ReactNode[]>>` LRU-bounded at `MD_CACHE_LIMIT = 512` — `useMemo`'s per-instance cache dies on remount, so virtualisation would otherwise re-parse every row that scrolls back into view; theme-keying drops stale palettes automatically.
- **Rebuild notes:** Cache parsed output keyed by (theme, text) outside the component; a virtualised transcript re-mounts constantly.

### Inline markdown tokens  `id: tui.markdown-inline`
- **Surface:** TUI
- **Where:** inside every markdown line.
- **What it does:** Styles inline spans in a fixed priority order.
- **How it works:** `INLINE_RE` (`markdown.tsx:108-131`) is one alternation whose leftmost match wins, ties broken by order. Alternatives with their capture groups and rendering (`MdInline`, `markdown.tsx:551-670`): (1,2) image `![alt](url)` → muted `[image: <alt>] <url>`; (3,4) link `[label](url)` → `ResolvedLink`; (5) autolink `<https://…>` / `<mailto:…>` / bare email → link with `mailto:` stripped from the label; (6) `~~strike~~` → strikethrough, recursive; (7) `` `code` `` → accent + dim, NOT recursive (inline code is verbatim by definition, so regex examples and shell snippets survive); (8) `**bold**`, (9) `__bold__` → bold, recursive; (10) `*italic*`, (11) `_italic_` → italic, recursive; (12) `==highlight==` → `diffAdded` background with `diffAddedWord` foreground, recursive; (13) `[^ref]` → muted `[ref]`; (14) `^superscript^` → muted `^text`; (15) `~sub~` (1–8 alphanumerics only) → muted `_text`; (16) bare `https?://…` URL → link, with trailing `),.;:!?` trimmed into a sibling text node so `see https://x.com/, which…` keeps the comma outside the link; (17) `$inline math$`, (18) `\(inline math\)` → `texToUnicode` in italic accent.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Underscore bold/italic use lookarounds so `snake_case_identifiers` and `dunder__names` are not italicised (`MD_UNDERSCORE_BOLD_RE`, `MD_UNDERSCORE_ITALIC_RE`, plus `MD_DUNDER_IDENTIFIER_RE`). Subscript is capped at 8 alphanumerics so kaomoji-style prose from Kimi/Qwen/GLM (`thing ~! more ~?`) does not pair up. Inline math wins over emphasis at the same start position so `$P=a*b*c$` renders as math instead of corrupting `*b*` into italics; single-character minimums and no-space-adjacent-to-delimiter rules keep `$5 to $10` out of math. The bare-URL alternative is explicitly wrapped in its own group so the math spans below it don't land in `m[16]`.
- **Rebuild notes:** One alternation with ordered alternatives + a dispatcher on which group matched; recurse everywhere except code.

### LaTeX math to Unicode  `id: tui.math-unicode`
- **Surface:** TUI
- **Where:** inline `$…$` / `\(…\)` and display `$$…$$` / `\[…\]` math anywhere in markdown.
- **What it does:** Renders LaTeX math as Unicode-formatted math instead of raw TeX. Always on, nothing to configure; the classic CLI keeps the raw TeX.
- **How it works:** `src/lib/mathUnicode.ts` (783 lines) exports `texToUnicode`, `BOX_OPEN`, `BOX_CLOSE`. Coverage per the code comments: Greek letters, blackboard-bold ℕℤℚℝ, operators, sub/superscripts and fractions. `\boxed{X}` regions are marked with the non-printable U+0001 / U+0002 sentinels; `renderMath()` (`markdown.tsx:17-57`) splits on them and renders the boxed segment `bold inverse` with a one-cell space margin so it reads as a highlighter-pen block. Math is painted in `theme.color.accent` + italic — italic is the disambiguator, because links use accent+underline.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Anything `texToUnicode` doesn't recognise is preserved verbatim, so unfamiliar commands look like their raw LaTeX rather than vanishing; the docs describe unsupported syntax as falling back to the literal TeX wrapped in a code span so it stays copyable.
- **Rebuild notes:** Never drop unrecognised markup — echo it.

### Syntax highlighting  `id: tui.syntax`
- **Surface:** TUI
- **Where:** fenced code blocks.
- **What it does:** Colors code by token class using theme-skinnable tokens.
- **How it works:** `src/lib/syntax.ts` (117 lines) exports `highlightLine(line, lang, theme)` and `isHighlightable(lang)`. Colors come from `syntaxString` (defaults to `accent`), `syntaxNumber` (`text`), `syntaxKeyword` (`border`), `syntaxComment` (`muted`) — all independently skinnable.
- **Inputs / options:** the fence info string selects the language.
- **Outputs / side effects:** Display only.
- **Config / env:** skin keys for the four syntax tokens.
- **Edge cases / guards:** Unknown languages render plain.
- **Rebuild notes:** Give syntax colors their own tokens defaulting to brand tokens, so a skin can restyle code without restyling the UI.

### Link resolution and titles  `id: tui.links`
- **Surface:** TUI
- **Where:** every rendered link.
- **What it does:** Renders links as clickable OSC-8 hyperlinks with a sensible label, resolving page titles where possible.
- **How it works:** `src/lib/externalLink.ts` (440 lines) exports `normalizeExternalUrl`, `urlSlugTitleLabel`, `useLinkTitle`. `markdown.tsx` helpers: `autolinkUrl(raw)` (prefixes `mailto:` for bare emails), `defaultLinkLabel(url)`, `pickAuthoredLabel(label, target)`, `ResolvedLink` / `renderResolvedLink(k, t, url, label?)`. Clicks are handled by the render root's `onHyperlinkClick` → `openExternalUrl`.
- **Inputs / options:** click.
- **Outputs / side effects:** Opens the OS URL handler.
- **Config / env:** n/a.
- **Edge cases / guards:** `supports-hyperlinks` in hermes-ink gates OSC-8 emission.
- **Rebuild notes:** n/a.

### Emoji presentation  `id: tui.emoji`
- **Surface:** TUI
- **Where:** any rendered text.
- **What it does:** Forces emoji presentation (VS16) where a code point would otherwise render as a narrow text glyph, so column math stays correct.
- **How it works:** `src/lib/emoji.ts` (55 lines) exports `ensureEmojiPresentation`, used by `markdown.tsx`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Width is measured with `stringWidth` from hermes-ink, not `String.length`.
- **Rebuild notes:** n/a.

### Incremental streaming markdown  `id: tui.streaming-markdown`
- **Surface:** TUI
- **Where:** the in-flight assistant message.
- **What it does:** Renders markdown incrementally as tokens arrive, so each block is tokenized exactly once and only the tail re-parses per delta.
- **How it works:** `src/components/streamingMarkdown.tsx` (166 lines), component `StreamingMd`. A forward scanner keeps `StreamScanState = {blocks: string[], codeOpen: boolean, mathOpener: '$$' | '\\[' | null, scanned: string, settledLen: number}` in a ref across deltas. `applyLine(state, line)` folds one COMPLETE line into the state: a `` ```/~~~ `` fence toggles `codeOpen`; inside a fence everything else is inert; otherwise `$$` at line start (not also closing on the same line) or `\[` (not also `\]`-closed) opens display math, and a matching closer clears it. Settled top-level blocks are committed at every `"\n\n"` outside a fence into an append-only array, each rendered as its own memoized `<Md>` whose text never changes. Complexity goes from O(blocks²) + an O(total) fence rescan to O(tail) per delta.
- **Inputs / options:** `text`, `t`, plus the `Md` props.
- **Outputs / side effects:** Display only.
- **Config / env:** stream batching from `src/config/timing.ts` — `STREAM_BATCH_MS = 16`, `STREAM_IDLE_BATCH_MS = 16`, `STREAM_SCROLL_BATCH_MS = 96`, `STREAM_TYPING_BATCH_MS = 80`, `TYPING_IDLE_MS = 250`, `REASONING_PULSE_MS = 700`.
- **Edge cases / guards:** Only newline-terminated lines are scanned (a partial trailing line may yet become a fence opener). Blank-line boundaries can never be retroactively merged. An unmatched `$$`/`\[` opener is treated as open FOREVER — more conservative than the full-text renderer, because a committed block is frozen and cannot be un-decided once the closer streams in. State only advances (idempotent under StrictMode); if `text` stops extending `scanned` (turn reuse, or `boundedLiveRenderText` front-trimming a huge reply) the scanner resets and `<Md>`'s LRU absorbs the re-parse. The subtrees MUST stack in a column because the `messageLine.tsx` parent is a default row `Box`.
- **Rebuild notes:** Freeze settled blocks, re-parse only the tail, and keep fence/math state in a ref — a stable-prefix split alone still pays an O(blocks²) cliff.

### Live render budgets  `id: tui.render-budgets`
- **Surface:** TUI / Core
- **Where:** invisible; caps how much text is turned into render nodes.
- **What it does:** Bounds the live streaming tail and the persisted verbose tool trail so a heavy session cannot OOM the Node process.
- **How it works:** `src/config/limits.ts`. `LIVE_RENDER_MAX_CHARS = 16_000`, `LIVE_RENDER_MAX_LINES = 240` bound the streaming tail (`boundedLiveRenderText`). `VERBOSE_TRAIL_MAX_CHARS = 800`, `VERBOSE_TRAIL_MAX_LINES = 12` bound each persisted per-call Args/Result block. `LARGE_PASTE = {lines: 5}`, `LONG_MSG = 300`, `MAX_HISTORY = 800`, `THINKING_COT_MAX = 160`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Truncated previews.
- **Config / env:** n/a.
- **Edge cases / guards:** The verbose-trail cap exists because a browser/large-output session retained ~12 MB of strings that exploded into a few hundred MB of Ink nodes and silently OOM-killed the Node parent (issue #34095). Full output remains in the agent context and the SQLite session — the trail is a glance, not a log.
- **Rebuild notes:** Bound what you turn into a render tree, not just what you store.

### Thinking / reasoning panel  `id: tui.thinking`
- **Surface:** TUI
- **Where:** inside the tool trail; header `▾ Thinking` (bold `text` while live, dim `muted` when settled) plus a dim token-count suffix.
- **What it does:** Streams the model's reasoning inline, with a blinking cursor while live and an auto-collapse when the reasoning phase ends.
- **How it works:** `src/components/thinking.tsx` (1256 lines). `Thinking` renders `thinkingPreview(reasoning, mode, THINKING_COT_MAX)`. `StreamCursor` blinks `▍` every 420 ms while `streaming && visible`. `Spinner({color, variant: 'think'|'tool'})` picks a random spinner from the THINK/TOOL sets and normalises every frame to a single code point. Open state: initial value is `thinkingDefaultExpanded || reasoningAlwaysVisible`; when the effective mode is `collapsed` (and this is not a MoA reference panel) the panel is an AUTO preference — it stays open while `reasoningActive` is true and collapses the moment the reasoning phase ends.
- **Inputs / options:** click the header to toggle; `Shift`-click or `Ctrl`-click expands ALL panels (`expandAll()`).
- **Outputs / side effects:** Display only.
- **Config / env:** `display.sections.thinking` (default `expanded`), `/details thinking …`, `/reasoning show|hide`.
- **Edge cases / guards:** `reasoningAlwaysVisible` marks a MoA reference panel — content the user opted into, not private model reasoning (issue #64657) — and it opens by default and is exempt from auto-collapse.
- **Rebuild notes:** Distinguish "auto" collapse behaviour from an explicit user preference; treat opted-in reference content differently from private reasoning.

### Tool trail  `id: tui.tool-trail`
- **Surface:** TUI
- **Where:** under each assistant turn; chevron sections `▾ Thinking`, `▾ Tool calls (<N>)`, `▾ Progress`, `▾ Spawned`, `▾ Spawn tree`, `▾ Activity`.
- **What it does:** Shows the agent's working area — reasoning, tool calls with results, progress, spawned subagents and ambient activity — as a collapsible tree.
- **How it works:** `ToolTrail` (`thinking.tsx:676+`). Section visibility comes from `sectionMode(name, detailsMode, sections, commandOverride)` for `thinking`, `tools`, `subagents`, `activity`. Tool rows are marked with `● ` in `theme.color.tool`; a result mark of `✗` recolors the row to `theme.color.error`. Activity rows use `✗` (error), `!` (warn) or `·` (info). Tree rails are drawn by `TreeRow`/`TreeTextRow`/`nextTreeRails`. `Chevron({count, onClick, open, suffix, t, title, tone})` renders `▾ `/`▸ ` in `accent` then the title, an optional ` (<count>)`, and a dim `statusFg` suffix; `tone` ∈ `dim|warn|error` picks the title color.
- **Inputs / options:** click any chevron to toggle; `Shift`/`Ctrl`-click to expand everything.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.sections.*`, `display.details_mode`.
- **Edge cases / guards:** When every section resolves to hidden the trail renders nothing and is transparent to block grouping; ambient errors/warnings then surface through a floating-alert backstop.
- **Rebuild notes:** Make an all-hidden trail literally render nothing so the spacing engine can skip it.

### Live assistant streaming area  `id: tui.streaming-assistant`
- **Surface:** TUI
- **Where:** the bottom of the transcript while a turn is running.
- **What it does:** Renders settled stream segments, active tools and the in-flight streaming block as one ordered list so blocks don't jump when they flush into history.
- **How it works:** `StreamingAssistant` (`src/components/streamingAssistant.tsx`). Reads `streamSegments`, `streamPendingTools`, `streaming`, `tools` from the turn store; `groupedSegments()` folds tool-shelf messages together via `appendToolShelfMessage()` (`src/lib/liveProgress.ts`). Blocks in order: each settled segment (`seg:<i>`), then `active-tools` (a `trail` message carrying the live `tools`), then either the `streaming` assistant block or a `pending-tools` trail. The grouping predecessor `prev` starts at `prevMsg` (the last settled history item) and only advances past blocks for which `blockRenders(checkMsg, detailsCtx)` is true — so a trail hidden by `/details` stays transparent here too.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.details_mode`, `display.sections.*`.
- **Edge cases / guards:** Renders nothing when there is no progress area, no streaming text and no active tools.
- **Rebuild notes:** Track the predecessor block, not the live text, so the live area's spacing matches its settled form exactly.

### Todo panel  `id: tui.todo-panel`
- **Surface:** TUI
- **Where:** rendered as a child of the LATEST user-message row so it visually belongs to the prompt and follows it during scroll (`appLayout.tsx:239`). Header: `▾ Todo (<done>/<total>)`, optionally ` · incomplete · <N> still pending|pending/in_progress`.
- **What it does:** Shows the agent's task list as a collapsible, nested checklist.
- **How it works:** `src/components/todoPanel.tsx`. `LiveTodoPanel` binds it to the turn store (`todos`, `todoCollapsed`, `toggleTodoCollapsed`); archived todos in history use local state. Glyphs from `todoGlyph(status)` (`src/lib/todo.ts:5-6`): `completed` → `[x]`, `cancelled` → `[-]`, `in_progress` → `[>]`, everything else → `[ ]`. Tones from `todoTone(status)`: `in_progress` → `active`, `pending` → `body`, else `dim`; colors map to `text` / `statusFg` / `muted`. Nesting from `todoTree(todos)` — a DFS over the `parent` field, parents before children, dangling/cyclic parents degraded to depth 0 and cycle members appended flat so nothing is lost; indentation is `min(depth, 4) * 2` columns. `countPendingTodos()` from `src/lib/liveProgress.ts`.
- **Inputs / options:** click the header to collapse/expand.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Renders nothing with an empty list. `todoTree` mirrors `apps/desktop/src/lib/todos.ts` so both surfaces render the same hierarchy from the same field.
- **Rebuild notes:** Attach the panel to the prompt that produced it, and make the tree walk cycle-safe.

### Subagent tree  `id: tui.subagent-tree`
- **Surface:** Core
- **Where:** the `Spawn tree` trail section, the agents overlay, and the status bar's SpawnHud.
- **What it does:** Builds and measures the delegation tree.
- **How it works:** `src/lib/subagentTree.ts` (351 lines) exports `buildSubagentTree(subagents)`, `treeTotals(tree)` (`descendantCount`, `activeCount`, `maxDepthFromHere`, …), `widthByDepth(tree)` and `hotnessBucket`. `heatColor(node, peak, theme)` maps a node's hotness onto `[border, accent, primary, warn, error]`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `max_spawn_depth`, `max_concurrent_children`.
- **Edge cases / guards:** The concurrency warning uses the WIDEST LEVEL of the tree, not the global active count, because `max_concurrent_children` is a per-parent cap.
- **Rebuild notes:** Compare against the right denominator — a global active count over-warns on multi-orchestrator runs.

### Virtualised history  `id: tui.virtual-history`
- **Surface:** Core
- **Where:** the transcript.
- **What it does:** Renders only the visible window of a long transcript while keeping scrolling exact.
- **How it works:** `src/hooks/useVirtualHistory.ts` (689 lines) with `src/lib/virtualHeights.ts` (162 lines) and `src/lib/viewportStore.ts` (136 lines). Exposes `{start, end, topSpacer, bottomSpacer, offsets, measureRef(key)}`. Row heights are MEASURED (via `measureRef`) rather than estimated, and cached per key; `offsets` feeds the sticky-prompt tracker.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Fewer render nodes.
- **Config / env:** n/a.
- **Edge cases / guards:** Regression tests cover clamping (`virtualHistoryClamp.test.ts`), the offset cache (`virtualHistoryOffsetCache.test.ts`) and height reuse (`useVirtualHistoryHeights.test.ts`).
- **Rebuild notes:** Measure, don't estimate; keep spacers as real boxes so the scroll height is exact.

### Paste collapse  `id: tui.paste-collapse`
- **Surface:** TUI / Config
- **Where:** the composer, when a long snippet is pasted.
- **What it does:** Collapses a large paste to a compact chip instead of flooding the composer.
- **How it works:** `LARGE_PASTE = {lines: 5}` (`src/config/limits.ts:1`); UI state defaults `pasteCollapseLines: 5`, `pasteCollapseChars: 2000` (`src/app/uiStore.ts:388-389`). `isPasteBackedText` / `compactPreview` (`src/lib/text.ts`) render the collapsed form; `src/protocol/paste.ts` and `src/domain/composerHighlights.ts` handle the protocol and highlighting.
- **Inputs / options:** n/a (automatic).
- **Outputs / side effects:** The full text is still sent; only the display collapses.
- **Config / env:** the paste-collapse config keys behind `pasteCollapseLines` / `pasteCollapseChars`.
- **Edge cases / guards:** Bracketed-paste safety — a pasted payload never triggers hotkeys.
- **Rebuild notes:** Collapse the DISPLAY, never the payload.

---

## 10. TUI ↔ gateway transport

### Gateway client (spawn + JSON-RPC over stdio)  `id: tui.gateway-client`
- **Surface:** TUI / Core
- **Where:** invisible; failures show as `gateway.stderr` lines in `/logs` and a `⚠` status.
- **What it does:** Spawns the Python `tui_gateway` as a child process and speaks newline-delimited JSON-RPC to it over stdio.
- **How it works:** `ui-tui/src/gatewayClient.ts` (944 lines), class `GatewayClient extends EventEmitter`. Spawn: `spawn(python, ['-m', 'tui_gateway.entry'], {cwd, env, stdio: ['pipe','pipe','pipe']})` (`gatewayClient.ts:487`). `resolvePython(root)` prefers `HERMES_PYTHON` then `PYTHON`, then `$VIRTUAL_ENV/bin/python`, `$VIRTUAL_ENV/Scripts/python.exe`, `<root>/.venv/bin/python`, `<root>/.venv/bin/python3`, `<root>/venv/bin/python`, `<root>/venv/bin/python3`, falling back to `python` on win32 / `python3` elsewhere. stdout is line-parsed as JSON (a malformed line pushes `[protocol] malformed stdout: <preview>` into the log and publishes `gateway.protocol_error`); stderr lines are truncated at `MAX_LOG_LINE_BYTES = 4096` (`…​ [truncated N bytes]`), pushed into a `CircularBuffer` of `MAX_GATEWAY_LOG_LINES = 200`, and published as `gateway.stderr`. Events arriving before a subscriber attaches are held in a `CircularBuffer` of `MAX_BUFFERED_EVENTS = 2000`. Pending requests are a `Map<string, {id, method, resolve, reject, timeout}>`.
- **Inputs / options:** `gw.request<T>(method, params)`, `gw.getLogTail(n)`, `gw.publishLocalEvent(ev)`, `gw.kill(reason)`, `gw.start()`.
- **Outputs / side effects:** A Python child process; JSON frames on its stdin.
- **Config / env:** `HERMES_PYTHON`, `PYTHON`, `VIRTUAL_ENV`, `HERMES_TUI_STARTUP_TIMEOUT_MS` (default 15000, floor 5000), `HERMES_TUI_RPC_TIMEOUT_MS` (default 120000, floor 30000).
- **Edge cases / guards:** A startup timeout publishes `gateway.start_timeout`. `redactUrl()` strips query strings and `user:pass@` user-info from every URL that reaches a log line or the `gateway.start_timeout` payload, with a regex fallback for URLs the WHATWG parser rejects.
- **Rebuild notes:** Newline-delimited JSON over stdio, a bounded log ring, a bounded pre-subscribe event ring, and redaction on every logged URL.

### Gateway attach mode (WebSocket)  `id: tui.gateway-attach`
- **Surface:** TUI / Web dashboard
- **Where:** internal wiring for the dashboard's Chat tab.
- **What it does:** Instead of spawning its own gateway, the TUI attaches to an existing one over a loopback WebSocket.
- **How it works:** `resolveGatewayAttachUrl()` reads `HERMES_TUI_GATEWAY_URL`; the client then opens a WebSocket (native `WebSocket` when available, else undici's) to that URL and speaks the same JSON-RPC. Frames may be text or binary (`asWireText` decodes `ArrayBuffer`/typed arrays with one hoisted module-level `TextDecoder`, because attach mode drives high-frequency binary frames — tool deltas, reasoning streams — and a per-message decoder would be avoidable GC pressure). WS ready-state constants are mirrored locally (`WS_CONNECTING 0`, `WS_OPEN 1`, `WS_CLOSING 2`, `WS_CLOSED 3`).
- **Inputs / options:** `HERMES_TUI_GATEWAY_URL`.
- **Outputs / side effects:** No child process.
- **Config / env:** `HERMES_TUI_GATEWAY_URL`, `HERMES_TUI_SIDECAR_URL`.
- **Edge cases / guards:** `/api/ws` exists only inside the dashboard server (`hermes_cli/web_server.py`) and is bound to that process's lifetime and auth. The OpenAI-compatible `hermes gateway` / `api_server` platform deliberately does NOT serve it — pointing this env var at that port 404s. There is no general "point any TUI at any standalone gateway port" mode.
- **Rebuild notes:** Keep the control channel out of the model-backend server; they have different auth and lifetime.

### WebSocket heartbeat and reconnect  `id: tui.gateway-heartbeat`
- **Surface:** TUI
- **Where:** invisible; surfaces as a `gateway.reconnecting` event with `{attempt, delay_ms}`.
- **What it does:** Detects silently-dropped sockets and reconnects with exponential backoff.
- **How it works:** `gatewayClient.ts:238-330`. `WS_HEARTBEAT_INTERVAL_MS = 15_000` sends a small JSON-RPC heartbeat the gateway explicitly answers (browser/undici WebSocket exposes no acknowledged ping/pong API); `WS_HEARTBEAT_DEAD_MS = 45_000` without an ack forces close → reconnect, logging `[lifecycle] websocket silent drop detected (heartbeat ack timeout); forcing reconnect`. A failed send logs `[lifecycle] websocket heartbeat send failed; forcing reconnect`. `scheduleReconnect()` uses `min(RECONNECT_BASE_MS * 2**attempts, RECONNECT_MAX_MS)` = `min(1000 * 2^n, 30_000)`, logs `[lifecycle] scheduling gateway reconnect in <ms>ms (attempt <n>)`, publishes `gateway.reconnecting`, and `.unref()`s its timer. `disposed` (set by `kill()`) prevents auto-reconnect after an intentional shutdown.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Reconnect attempts; `src/app/gatewayRecovery.ts` drives the UI-side recovery.
- **Config / env:** n/a.
- **Edge cases / guards:** Healthy idle sockets stay open — only a missing heartbeat ack closes them (issue #32997: macOS sleep / proxy idle timeout / VPN reconnect kill the TCP socket without a `close` event).
- **Rebuild notes:** If the socket API has no acknowledged ping, build one at the application layer.

### Gateway event stream  `id: tui.gateway-events`
- **Surface:** TUI / Core
- **Where:** every live update in the UI.
- **What it does:** Server→client notifications carrying session info, streaming text, tool lifecycle, prompts and lifecycle signals.
- **How it works:** `GatewayEvent` is a discriminated union on `type` (`ui-tui/src/gatewayTypes.ts:621-767`), each frame `{type, session_id?, payload?}`. Handled centrally in `src/app/createGatewayEventHandler.ts` (1512 lines). Full type list, verbatim: `gateway.ready` (`payload {heartbeat?, skin?}`), `skin.changed` (`payload: GatewaySkin`), `session.info` (`payload: SessionInfo`), `thinking.delta` (`{text?}`), `reaction` (`{kind?}`), `message.start`, `status.update` (`{kind?, text?}`), `notification.show`, `notification.clear` (`{key?}`), `billing.step_up.verification`, `voice.status` (`{state?: 'idle'|'listening'|'transcribing'}`), `voice.transcript`, `wake.detected`, `dashboard.new_session_requested` (`{reason?}`), `gateway.stderr` (`{line}`), `gateway.reconnecting` (`{attempt?, delay_ms?}`), `browser.progress`, `gateway.start_timeout`, `gateway.protocol_error` (`{preview?}`), `reasoning.delta`, `reasoning.available`, `moa.reference`, `moa.aggregating` (`{aggregator?}`), `moa.progress`, `moa.phase`, `tool.progress` (`{name?, preview?}`), `tool.generating` (`{name?}`), `tool.start`, `tool.complete`, `clarify.request`, `approval.request`, `sudo.request` (`{request_id}`), `secret.request` (`{env_var, prompt, request_id}`), `secret.expire`, `sudo.expire`, `background.complete` (`{task_id, text}`), `btw.complete` (`{question?, task_id, text}`), `review.summary` (`{text?}`), `subagent.spawn_requested`, `subagent.start`, `subagent.thinking`, `subagent.tool`, `subagent.progress`, `subagent.complete`, `message.delta` (`{rendered?, text?}`), `message.interim`, `message.complete`, `session.usage` (`{usage?}`), `error` (`{message?}`). The gateway also emits `tool.output_risk`, `todo.updated`, `terminal.close`, `voice.interrupted`, `pet.generate.progress`, `pet.hatch.progress`, `preview.restart.progress`, `preview.restart.complete`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** All UI state changes.
- **Config / env:** n/a.
- **Edge cases / guards:** `asGatewayEvent(value)` accepts only non-array objects with a string `type`.
- **Rebuild notes:** One discriminated union, one handler module, one event ring for pre-subscribe frames.

### Event replay / resume-after-reconnect  `id: tui.event-replay`
- **Surface:** Core
- **Where:** internal, after a transport drop.
- **What it does:** Lets a reconnecting client ask for every event newer than the last sequence number it saw, so nothing is lost.
- **How it works:** `tui_gateway/event_replay.py` (125 lines) maintains a per-session replay buffer stamped with a `replay_epoch`; the RPCs `session.events.since {session_id, last_seen}` and `session.events.stats {}` (`tui_gateway/methods_session.py:3696` / `:3727`) serve it. Every event frame carries a sequence so the client can request a delta.
- **Inputs / options:** `last_seen`, `session_id`.
- **Outputs / side effects:** A batch of buffered events.
- **Config / env:** n/a.
- **Edge cases / guards:** The epoch changes when the gateway restarts, telling the client its cursor is void.
- **Rebuild notes:** Sequence every event and keep a bounded replay buffer — reconnect correctness is otherwise impossible.

### Gateway transport abstraction  `id: tui.gateway-transport`
- **Surface:** Core
- **Where:** `tui_gateway/transport.py` (219 lines).
- **What it does:** Decouples the I/O sink from handler logic so one dispatcher serves stdio (`tui_gateway.entry`) and WebSocket (`tui_gateway.ws`) peers.
- **How it works:** A `Transport` Protocol with `write(obj) -> bool`. The active transport for the current request lives in a `contextvars.ContextVar`, so handlers dispatched onto the worker pool still route writes to the right peer. `server.write_json` falls back to a module-level `StdioTransport` (wrapping `_real_stdout` + `_stdout_lock`, resolving the stream lazily through a callback so tests that monkey-patch `server._real_stdout` keep working). `_PEER_GONE_ERRNOS` = `{EPIPE, ECONNRESET, EBADF, ESHUTDOWN, WSAECONNRESET, WSAESHUTDOWN}` (win32 mappings filtered out when absent) — writes failing with these are treated as a clean disconnect; anything else re-raises into the crash log. `TeeTransport` mirrors every emit to a second sink.
- **Inputs / options:** n/a.
- **Outputs / side effects:** JSON frames on stdout or a WS.
- **Config / env:** `HERMES_TUI_GATEWAY_NO_FLUSH` (`1|true|yes|on`) skips the post-write `stream.flush` — ONLY safe when the gateway runs with `-u` or `PYTHONUNBUFFERED=1`, because Python text stdout is fully buffered on a pipe and frames would otherwise accumulate until the TUI hangs waiting for `gateway.ready`.
- **Edge cases / guards:** A half-closed pipe (the Node parent quit mid-emit) can make `flush` block long enough to starve the worker pool — hence the knob.
- **Rebuild notes:** Put the peer in a context variable, not a global, so pooled handlers write to the right client.

### Sidecar event mirror  `id: tui.sidecar`
- **Surface:** Core / Web dashboard
- **Where:** internal; activated by the dashboard's `/api/pty` endpoint when a chat tab passes a `channel` query param.
- **What it does:** Mirrors every dispatcher emit to the dashboard sidebar over a second WebSocket.
- **How it works:** `_install_sidecar_publisher()` (`tui_gateway/entry.py:49-66`) wraps `server._stdio_transport` in a `TeeTransport(stdio, WsPublisherTransport(url))` when `HERMES_TUI_SIDECAR_URL` is set. Client side, `resolveSidecarUrl()` and `sidecarWs` in `gatewayClient.ts`.
- **Inputs / options:** `HERMES_TUI_SIDECAR_URL`.
- **Outputs / side effects:** Duplicate event stream.
- **Config / env:** `HERMES_TUI_SIDECAR_URL`.
- **Edge cases / guards:** Best-effort — a connect failure or a runtime drop falls back to stdio-only.
- **Rebuild notes:** Tee at the transport layer, never in every handler.

### Long-handler thread pool  `id: tui.long-handlers`
- **Surface:** Core
- **Where:** internal; the reason the TUI stays responsive during slow RPCs.
- **What it does:** Routes slow handlers onto a small thread pool so inbound RPCs (notably `approval.respond` and `session.interrupt`) are never left unread in the stdin pipe.
- **How it works:** `_LONG_HANDLERS` (`tui_gateway/server.py:229+`), a frozenset checked at `server.py:3085`. Members, verbatim: `billing.state`, `subscription.state`, `subscription.preview`, `subscription.change`, `subscription.resume`, `subscription.upgrade`, `usage.bars`, `session.usage`, `billing.step_up`, `browser.manage`, `cli.exec`, `complete.path`, `complete.slash`, `llm.oneshot`, `model.options`, `pet.cells`, `pet.gallery`, `pet.generate`, `pet.hatch`, `pet.info`, `pet.select`, `pet.thumb`, `learning.frames`, `plugins.manage`, `reload.mcp`, plus the MCP server test/OAuth RPCs. Everything else stays on the main thread so ordering stays sane on the fast path; `write_json` is `_stdout_lock`-guarded so concurrent response writes are safe.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Concurrency.
- **Config / env:** n/a.
- **Edge cases / guards:** Documented failure modes each member fixes: portal round-trips (billing/subscription/usage), `git ls-files` + whole-repo fuzzy ranking (`complete.path`) and first-call prompt_toolkit imports + a skill-dir scan (`complete.slash`) — issue #21123; the full picker payload build (`model.options`); network fetches and per-frame PNG decode/encode (pet RPCs); MCP shutdown/rediscovery that can block for minutes against a flapping server (`reload.mcp`, serialized by `_mcp_reload_lock`); cold `npx` starts and ~30 s authorization-URL waits (MCP test/OAuth). `prompt.submit` is deliberately NOT in the set.
- **Rebuild notes:** Enumerate the slow handlers explicitly rather than making everything async — ordering on the fast path is worth protecting.

### Gateway shutdown grace  `id: tui.gateway-shutdown`
- **Surface:** Core / Env
- **Where:** internal.
- **What it does:** Bounds how long orderly shutdown may take before the process is force-exited.
- **How it works:** `tui_gateway/entry.py` — `_DEFAULT_SHUTDOWN_GRACE_S = 1.0`, overridable via `HERMES_TUI_GATEWAY_SHUTDOWN_GRACE_S`; after the grace it falls back to `os._exit(0)` so a wedged worker mid-flush cannot strand the process. `install_exit_flush_signal_handlers()` (`server.py:1754`) chains previous handlers per signal so the emit buffer is flushed on the way out.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Process exit.
- **Config / env:** `HERMES_TUI_GATEWAY_SHUTDOWN_GRACE_S`.
- **Edge cases / guards:** 1 s covers thread-pool drain + session finalize on every tested machine; a longer grace also means a longer wait when shutdown actually deadlocks.
- **Rebuild notes:** Always cap orderly shutdown with a hard exit.

### stdin EOF recovery  `id: tui.stdin-recovery`
- **Surface:** Core
- **Where:** internal.
- **What it does:** Distinguishes a spurious stdin EOF from a real parent death so the gateway does not exit prematurely.
- **How it works:** `tui_gateway/_stdin_recovery.py` (151 lines), `handle_spurious_eof(...)`, called from the reader loop in `tui_gateway/entry.py`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Either a retry or a clean exit; the crash log (`tui_gateway_crash.log`) records `=== SIGTERM received ===` / `stdin EOF`, which is how a SIGHUP (terminal/SSH dropped) is told apart from a real SIGTERM.
- **Config / env:** n/a.
- **Edge cases / guards:** A Node OOM `process.exit(137)` closes the child's stdin, so the gateway logs a clean EOF, NOT SIGTERM — the parent's breadcrumb is the only attribution.
- **Rebuild notes:** Log the shutdown REASON on both sides of the pipe.

### Crash log and lifecycle breadcrumbs  `id: tui.crash-log`
- **Surface:** Core
- **Where:** `$HERMES_HOME/tui_gateway_crash.log` and the parent's `[tui-parent]` breadcrumb log.
- **What it does:** Records why either half of the TUI died.
- **How it works:** `_CRASH_LOG` in `tui_gateway/server.py`; `recordParentLifecycle()` in `ui-tui/src/lib/parentLog.ts` (59 lines) on the Node side. Breadcrumb examples: `graceful-exit received signal=<SIG> → killing gateway`; `dead output stream (<code> x<n>) → exiting`; `memory-critical process.exit(137) heap=… rss=… dump=…`; `memory-warning fast heap growth heap=… rss=…`; `user widgets registered: <ids>`; `user widget <file> failed to load: <message>`; `[lifecycle] spawned gateway child pid=… killed=… exitCode=… signal=… python=… cwd=…`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Two log files.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Write a breadcrumb before every intentional exit; a death with no breadcrumb is unattributable.

### Slash worker subprocess  `id: tui.slash-worker`
- **Surface:** Core
- **Where:** internal; backs `slash.exec` for commands the gateway does not implement natively.
- **What it does:** Runs a classic-CLI slash command out-of-process and returns its rendered output.
- **How it works:** `tui_gateway/slash_worker.py` (196 lines), spawned as `tui_gateway.slash_worker`. Fuzzy name resolution lives in `tui_gateway/slash_fuzzy.py` (91 lines).
- **Inputs / options:** `slash.exec {command, session_id}`.
- **Outputs / side effects:** `{output, warning?}` or a `command.dispatch`-shaped payload.
- **Config / env:** n/a.
- **Edge cases / guards:** The worker is detached and never sees the TUI's in-memory turns — which is why `/history` is reimplemented client-side.
- **Rebuild notes:** Isolate legacy command execution in a subprocess, but be explicit about what state it cannot see.

---

## 11. `tui_gateway` JSON-RPC methods

Every method below is registered with the `@method("<name>")` decorator and dispatched by
`tui_gateway/server.py`. Requests are `{id, method, params}`; a handler returns `_ok(rid, {...})`
or `_err(rid, <code>, "<message>")`. 199 methods are registered in total (188 via a literal `@method("…")`, plus 11 `projects.*` methods registered through the `_projects_method` wrapper — see the last group below). Methods listed in
`_LONG_HANDLERS` (see `tui.long-handlers`) run on the RPC thread pool; everything else runs
inline on the reader thread. Result keys and error codes below are transcribed from source.

### `tui_gateway/server.py` — core dispatch, config, wake word, voice  `id: tui.rpcgroup-server`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/server.py` (11 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `server.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `config.set`  `id: tui.rpc-config-set`
- **Surface:** API
- **Where:** JSON-RPC method `config.set` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `config.set` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `server.py:14070`, registered as `@method("config.set")`.
- **Inputs / options:** `always`, `board_slug`, `color`, `confirm_expensive_model`, `cwd`, `description`, `folders`, `icon`, `id`, `is_primary`, `key`, `label`, `name`, `path`, `primary_path`, `profile`, `restore`, `scope`, `session_id`, `slug`, `use`, `value`
- **Outputs / side effects:** `_ok` result keys: `active_id`, `branch`, `confirm_message`, `confirm_required`, `cwd`, `deferred`, `key`, `project`, `scope`, `tool_progress`, `value`, `warning`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4002` ("cwd required"), `4002` ("fast mode is not available for this model"), `4002` ("fast mode is not available without a selected model"), `4002` ("model value required"), `4002` ("unknown approval mode: {value}; pick one of manual|smart|off"), `4002` ("unknown battery value: {value}"), `4002` ("unknown busy mode: {value}"), `4002` ("unknown config key: {key}"), `4002` ("unknown density value: {value}"), `4002` ("unknown details_mode: {value}"), `4002` ("unknown fast mode: {value}"), `4002` ("unknown focus value: {value} (use on|off|status)"), `4002` ("unknown indicator: {raw!r}; pick one of {'|'.join(INDICATOR_STYLES)}"), `4002` ("unknown mouse value: {value}"), `4002` ("unknown reasoning value: {value}"), `4002` ("unknown section: {section}"), `4002` ("unknown statusbar value: {value}"), `4002` ("unknown theme value: {value} (use auto|light|dark)"), `4002` ("unknown thinking_mode: {value}"), `4002` ("unknown verbose mode: {value}"), `4002` ("working directory does not exist: {raw}"), `5001`, `5032`, `5032` ("agent initialization failed"), `5032` ("agent initialization timed out")
- **Rebuild notes:** n/a

### `ping`  `id: tui.rpc-ping`
- **Surface:** API
- **Where:** JSON-RPC method `ping` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Cheapest possible liveness probe for the desktop client.
- **How it works:** `server.py:16979`, registered as `@method("ping")`. Source doc: "Cheapest possible liveness probe for the desktop client. Answered synchronously on the WS reader thread, so it works even while every agent is mid-turn or the GIL is contended — the round-trip only measures socket health, not backend load. A desktop client uses it after sleep/wake to distinguish a half-open TCP connection (no close event, so `connectionState` still reads `open` while every RPC hangs until its per-call timeout) from a genuinely healthy socket, and forces a reconnect in the former case instead of letting the next `prompt.submit` hang."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `pong`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `wake.start`  `id: tui.rpc-wake-start`
- **Surface:** API
- **Where:** JSON-RPC method `wake.start` on the TUI gateway (called by the TUI).
- **What it does:** Arm the wake-word listener for the calling surface ("tui" | "gui").
- **How it works:** `server.py:16994`, registered as `@method("wake.start")`. Source doc: "Arm the wake-word listener for the calling surface ("tui" | "gui"). Idempotent and gated: returns `{started: False, reason}` when the wake word is disabled, scoped to another surface, or its deps/mic aren't ready. `persist: true` marks an explicit user gesture (toggle click, /wake on): when the feature is disabled in config, it flips `wake_word.enabled` on and saves it before arming, so the choice sticks for future sessions. Passive auto-arm callers omit it and keep getting the config-gated refusal."
- **Inputs / options:** `client_capture`, `persist`, `session_id`, `surface`
- **Outputs / side effects:** `_ok` result keys: `capture`, `enabled_persisted`, `frame_length`, `hint`, `owner_surface`, `phrase`, `provider`, `reason`, `sample_rate`, `started`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5026`, `5026` ("wake module unavailable: {e}")
- **Rebuild notes:** n/a

### `wake.stop`  `id: tui.rpc-wake-stop`
- **Surface:** API
- **Where:** JSON-RPC method `wake.stop` on the TUI gateway (called by the TUI).
- **What it does:** Stop this surface's listener.
- **How it works:** `server.py:17143`, registered as `@method("wake.stop")`. Source doc: "Stop this surface's listener. `persist: true` (explicit user gesture) also writes `wake_word.enabled: false` to config.yaml so auto-arm stays off in future sessions — the toggle is the config, not just the live listener."
- **Inputs / options:** `persist`
- **Outputs / side effects:** `_ok` result keys: `disabled_persisted`, `reason`, `stopped`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `wake.pause`  `id: tui.rpc-wake-pause`
- **Surface:** API
- **Where:** JSON-RPC method `wake.pause` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Release the mic (e.g.
- **How it works:** `server.py:17170`, registered as `@method("wake.pause")`. Source doc: "Release the mic (e.g. while the desktop's browser captures audio)."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `paused`, `reason`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `wake.resume`  `id: tui.rpc-wake-resume`
- **Surface:** API
- **Where:** JSON-RPC method `wake.resume` on the TUI gateway (called by the TUI).
- **What it does:** Reclaim the mic after a pause; no-op if the listener isn't armed.
- **How it works:** `server.py:17188`, registered as `@method("wake.resume")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `reason`, `resumed`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `wake.status`  `id: tui.rpc-wake-status`
- **Surface:** API
- **Where:** JSON-RPC method `wake.status` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `wake.status` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `server.py:17200`, registered as `@method("wake.status")`.
- **Inputs / options:** `client_capture`, `surface`
- **Outputs / side effects:** `_ok` result keys: `audio_silent`, `available`, `capture`, `configured_surface`, `enabled`, `frame_length`, `hint`, `input_device`, `listening`, `local_input_available`, `owned_by_caller`, `owner_surface`, `phrase`, `provider`, `sample_rate`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5026`
- **Rebuild notes:** n/a

### `wake.feed`  `id: tui.rpc-wake-feed`
- **Surface:** API
- **Where:** JSON-RPC method `wake.feed` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Push client-captured PCM into the armed wake detector.
- **How it works:** `server.py:17270`, registered as `@method("wake.feed")`. Source doc: "Push client-captured PCM into the armed wake detector. Params: pcm: base64-encoded int16 mono little-endian samples (preferred), OR pcm_b64: alias of pcm Optional: sample_rate: must be 16000 (ignored if missing; mismatched rates rejected) Used when `wake.start` returned `capture: "client"` so remote backends without a microphone can still run openWakeWord on Mac/desktop audio."
- **Inputs / options:** `pcm`, `pcm_b64`, `sample_rate`
- **Outputs / side effects:** `_ok` result keys: `fed`, `reason`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("invalid base64 pcm: {e}"), `4001` ("pcm frame too large"), `4001` ("wake.feed only accepts 16 kHz PCM"), `4001` ("wake.feed requires base64 pcm"), `5026`
- **Rebuild notes:** n/a

### `voice.toggle`  `id: tui.rpc-voice-toggle`
- **Surface:** API
- **Where:** JSON-RPC method `voice.toggle` on the TUI gateway (called by the TUI).
- **What it does:** CLI parity for the ``/voice`` slash command.
- **How it works:** `server.py:17309`, registered as `@method("voice.toggle")`. Source doc: "CLI parity for the `/voice` slash command. Subcommands: * `status` — report mode + TTS flags (default when action is unknown). * `on` / `off` — flip voice *mode* (the umbrella bit). Turning it off also tears down any active continuous recording loop. Does NOT start recording on its own; recording is driven by `voice.record` (Ctrl+B) after mode is on, matching cli.py's enable/Ctrl+B split. * `tts` — toggle speech-output of agent replies. Requires mode on (mirrors CLI's _toggle_voice_tts guard)."
- **Inputs / options:** `action`
- **Outputs / side effects:** `_ok` result keys: `enabled`, `record_key`, `stop_hint`, `tts`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4013` ("unknown voice action: {action}"), `4014` ("enable voice mode first: /voice on")
- **Rebuild notes:** n/a

### `voice.record`  `id: tui.rpc-voice-record`
- **Surface:** API
- **Where:** JSON-RPC method `voice.record` on the TUI gateway (called by the TUI).
- **What it does:** VAD-bounded push-to-talk capture, CLI-parity.
- **How it works:** `server.py:17423`, registered as `@method("voice.record")`. Source doc: "VAD-bounded push-to-talk capture, CLI-parity. `start` begins one VAD-bounded capture and emits `voice.transcript` after silence stops the recorder. `stop` forces transcription of the active buffer, matching classic CLI push-to-talk. The voice wrapper retains no-speech counts across single-shot starts, so three consecutive silent captures emit `voice.transcript` with `no_speech_limit=True`."
- **Inputs / options:** `action`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `reason`, `status`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("voice mode is off — enable with /voice on"), `4019` ("unknown voice action: {action}"), `5025`, `5025` ("voice module not available — install audio dependencies")
- **Rebuild notes:** n/a

### `voice.tts`  `id: tui.rpc-voice-tts`
- **Surface:** API
- **Where:** JSON-RPC method `voice.tts` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `voice.tts` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `server.py:17577`, registered as `@method("voice.tts")`.
- **Inputs / options:** `session_id`, `text`, `url`
- **Outputs / side effects:** `_ok` result keys: `connected`, `messages`, `status`, `url`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("browser url must be a string, got {type(raw_url).__name__}"), `4015` ("invalid port in browser url: {url}"), `4015` ("missing host in browser url: {url}"), `4015` ("unsupported browser url: {url}"), `4020` ("text required"), `5026`, `5026` ("voice module not available"), `5031`, `5031` ("could not reach browser CDP at {url}"), `5031` ("could not reach browser CDP at {url}: {e}")
- **Rebuild notes:** n/a

### `tui_gateway/methods_session.py` — sessions, billing, pets, delegation  `id: tui.rpcgroup-methods-session`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_session.py` (66 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_session.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `session.create`  `id: tui.rpc-session-create`
- **Surface:** API
- **Where:** JSON-RPC method `session.create` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.create` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:15`, registered as `@method("session.create")`.
- **Inputs / options:** `close_on_disconnect`, `cols`, `cwd`, `fast`, `follow_profile_config`, `hidden`, `messages`, `model`, `parent_session_id`, `profile`, `provider`, `reasoning_effort`, `room_plumbing`, `source`, `title`
- **Outputs / side effects:** `_ok` result keys: `branch`, `cwd`, `desktop_contract`, `info`, `lazy`, `message_count`, `messages`, `model`, `profile_name`, `project`, `provider`, `session_id`, `skills`, `stored_session_id`, `tools`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.list`  `id: tui.rpc-session-list`
- **Surface:** API
- **Where:** JSON-RPC method `session.list` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:166`, registered as `@method("session.list")`.
- **Inputs / options:** `include_hidden`, `limit`, `title`
- **Outputs / side effects:** `_ok` result keys: `id`, `message_count`, `preview`, `resolved_id`, `sessions`, `source`, `started_at`, `title`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5006`
- **Rebuild notes:** n/a

### `session.most_recent`  `id: tui.rpc-session-most-recent`
- **Surface:** API
- **Where:** JSON-RPC method `session.most_recent` on the TUI gateway (called by the TUI).
- **What it does:** Return the most recent human-facing session id, or ``None``.
- **How it works:** `methods_session.py:283`, registered as `@method("session.most_recent")`. Source doc: "Return the most recent human-facing session id, or `None`. Mirrors `session.list`'s deny-list behaviour (drops `tool` sub-agent rows and `kanban` worker rows). Used by TUI auto-resume when `display.tui_auto_resume_recent` is on; the field is also handy for any CLI tooling that wants "latest session" without paginating the full list. Contract: a `{"session_id": null}` result means "no eligible session found right now". Errors are also folded into that null-result shape (and logged) so callers don't have to special- case JSON-RPC error envelopes for what is a normal "no answer". Hono"
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `session_id`, `source`, `started_at`, `title`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `project.facts`  `id: tui.rpc-project-facts`
- **Surface:** API
- **Where:** JSON-RPC method `project.facts` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Structured project facts for a cwd — manifests, package manager, the exact verify commands, and context files.
- **How it works:** `methods_session.py:332`, registered as `@method("project.facts")`. Source doc: "Structured project facts for a cwd — manifests, package manager, the exact verify commands, and context files. The same detection the coding-context posture (#43316) bakes into the system prompt, exposed so UIs (the desktop verify surface) consume it instead of re-sniffing. `{"facts": null}` means the cwd isn't a code workspace."
- **Inputs / options:** `cwd`
- **Outputs / side effects:** `_ok` result keys: `facts`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `verification.status`  `id: tui.rpc-verification-status`
- **Surface:** API
- **Where:** JSON-RPC method `verification.status` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Best known coding verification evidence for a cwd/session.
- **How it works:** `methods_session.py:351`, registered as `@method("verification.status")`. Source doc: "Best known coding verification evidence for a cwd/session. Read-only consumer of the core ledger. It never runs checks and never upgrades targeted evidence into a repository-wide guarantee."
- **Inputs / options:** `cwd`, `session_id`, `session_key`
- **Outputs / side effects:** `_ok` result keys: `evidence`, `status`, `verification`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.resume`  `id: tui.rpc-session-resume`
- **Surface:** API
- **Where:** JSON-RPC method `session.resume` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.resume` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:375`, registered as `@method("session.resume")`.
- **Inputs / options:** `close_on_disconnect`, `cols`, `defer_history`, `eager_build`, `lazy`, `omit_messages`, `profile`, `session_id`, `source`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4006` ("session_id required"), `4007` ("session no longer live; retry resume"), `4007` ("session not found"), `4009` ("session disconnect interrupt settling"), `4130`, `5000` ("resume failed: {e}")
- **Rebuild notes:** n/a

### `session.cwd.set`  `id: tui.rpc-session-cwd-set`
- **Surface:** API
- **Where:** JSON-RPC method `session.cwd.set` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `session.cwd.set` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:1106`, registered as `@method("session.cwd.set")`.
- **Inputs / options:** `cwd`, `session_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4009` ("session busy"), `4016` ("cwd required"), `4017`
- **Rebuild notes:** n/a

### `session.workspace.move`  `id: tui.rpc-session-workspace-move`
- **Surface:** API
- **Where:** JSON-RPC method `session.workspace.move` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Re-home a STORED session's workspace into another folder/project.
- **How it works:** `methods_session.py:1131`, registered as `@method("session.workspace.move")`. Source doc: "Re-home a STORED session's workspace into another folder/project. Unlike `session.cwd.set` (which acts on a live runtime session by its UI id), this targets a persisted row by `session_key` so the desktop can fix a session that was created in the wrong directory — no live agent required. The git branch/root columns are REPLACED (not merely enriched), because the whole point of the move is to change which project claims the session; a stale `git_repo_root` would keep it grouped under the project it left. A live agent bound to the row follows through the runtime path too, so its terminal/f"
- **Inputs / options:** `cwd`, `session_key`
- **Outputs / side effects:** `_ok` result keys: `branch`, `cwd`, `git_repo_root`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4007` ("session not found"), `4007` ("session_key required"), `4016` ("cwd required"), `4017`, `4017` ("working directory does not exist: {raw}"), `5007` ("move failed: {e}")
- **Rebuild notes:** n/a

### `session.active_list`  `id: tui.rpc-session-active-list`
- **Surface:** API
- **Where:** JSON-RPC method `session.active_list` on the TUI gateway (called by the TUI).
- **What it does:** Return live TUI sessions in this gateway process.
- **How it works:** `methods_session.py:1206`, registered as `@method("session.active_list")`. Source doc: "Return live TUI sessions in this gateway process. Unlike `session.list` this is not a historical DB browser: it reports only sessions with in-memory agents/workers that the current TUI can switch to without closing siblings."
- **Inputs / options:** `current_session_id`
- **Outputs / side effects:** `_ok` result keys: `sessions`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5036` ("could not enumerate active sessions: {e}")
- **Rebuild notes:** n/a

### `session.activate`  `id: tui.rpc-session-activate`
- **Surface:** API
- **Where:** JSON-RPC method `session.activate` on the TUI gateway (called by the TUI).
- **What it does:** Attach the frontend to an already-live TUI session.
- **How it works:** `methods_session.py:1244`, registered as `@method("session.activate")`. Source doc: "Attach the frontend to an already-live TUI session. This intentionally does not close the previously focused session; it merely returns enough state for Ink to redraw around another live session id."
- **Inputs / options:** `omit_messages`, `session_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.delete`  `id: tui.rpc-session-delete`
- **Surface:** API
- **Where:** JSON-RPC method `session.delete` on the TUI gateway (called by the TUI).
- **What it does:** Delete a stored session and its on-disk transcript files.
- **How it works:** `methods_session.py:1269`, registered as `@method("session.delete")`. Source doc: "Delete a stored session and its on-disk transcript files. Used by the TUI resume picker (`d` key) so users can prune old sessions without dropping to the CLI. Refuses to delete a session that is currently active in this gateway process — those rows are still being written to and removing them out from under the live agent corrupts message ordering and trips FK constraints when the next message append flushes. Honors `params.profile` so app-global remote mode deletes from the focused profile's `state.db` + sessions dir (mirrors `session.resume`)."
- **Inputs / options:** `profile`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `deleted`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4006` ("session_id required"), `4007` ("session not found"), `4023` ("cannot delete an active session"), `5036` ("could not enumerate active sessions: {e}"), `5036` ("delete failed: {e}")
- **Rebuild notes:** n/a

### `session.title`  `id: tui.rpc-session-title`
- **Surface:** API
- **Where:** JSON-RPC method `session.title` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.title` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:1319`, registered as `@method("session.title")`.
- **Inputs / options:** `session_id`, `title`
- **Outputs / side effects:** `_ok` result keys: `pending`, `session_key`, `title`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4021` ("title required"), `4022`, `5007`
- **Rebuild notes:** n/a

### `session.set_hidden`  `id: tui.rpc-session-set-hidden`
- **Surface:** API
- **Where:** JSON-RPC method `session.set_hidden` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Set/clear the generic ``hidden`` flag on a session (and its lineage).
- **How it works:** `methods_session.py:1403`, registered as `@method("session.set_hidden")`. Source doc: "Set/clear the generic `hidden` flag on a session (and its lineage). Mirrors the durable `pinned`/`archived` setters: a hidden session is dropped from the default global Sessions list (`list_sessions_rich` without `include_hidden`) but stays fully resumable by the surface that owns it — for plugins that manage their own sessions and don't want them cluttering the shared recents list. Flips the whole compression chain as a unit in the DB layer. Resolution is two-tier: a LIVE runtime session id first (which also covers the not-yet-persisted draft via the `pending_hidden` deferral), th"
- **Inputs / options:** `hidden`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `hidden`, `session_key`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5007`
- **Rebuild notes:** n/a

### `message.react`  `id: tui.rpc-message-react`
- **Surface:** API
- **Where:** JSON-RPC method `message.react` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Set or clear one author's emoji reaction on a persisted message.
- **How it works:** `methods_session.py:1455`, registered as `@method("message.react")`. Source doc: "Set or clear one author's emoji reaction on a persisted message. iOS Tapback semantics, enforced in the DB layer: one reaction per author per message, re-sending the same emoji retracts it. `emoji: null` clears unconditionally. `row_id` is the durable `messages.id` forwarded by `_history_to_messages` — the renderer's own message ids are ephemeral."
- **Inputs / options:** `author`, `emoji`, `newest_role`, `row_id`
- **Outputs / side effects:** `_ok` result keys: `reactions`, `row_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4023` ("row_id or newest_role required"), `4024` ("emoji must be a non-empty string or null"), `4025` ("author must be 'user' or 'agent'"), `4040` ("message not found in this session"), `4040` ("no message to react to yet"), `5007`
- **Rebuild notes:** n/a

### `llm.oneshot`  `id: tui.rpc-llm-oneshot`
- **Surface:** API
- **Where:** JSON-RPC method `llm.oneshot` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Run a single stateless LLM request outside any conversation.
- **How it works:** `methods_session.py:1508`, registered as `@method("llm.oneshot")`. Source doc: "Run a single stateless LLM request outside any conversation. Generic helper for small generative chores (e.g. a commit message from a diff). Accepts either a named `template` + `variables` or an explicit `instructions` / `input` pair. When `session_id` resolves to a live session the call inherits that agent's model; otherwise it uses the configured auxiliary `task` backend. Never mutates session history, so prompt caching is untouched." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `input`, `instructions`, `max_tokens`, `session_id`, `task`, `temperature`, `template`, `variables`
- **Outputs / side effects:** `_ok` result keys: `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4030` ("llm.oneshot requires a template or instructions/input"), `4031`, `4032`, `5030` ("one-shot generation failed: {e}")
- **Rebuild notes:** n/a

### `handoff.request`  `id: tui.rpc-handoff-request`
- **Surface:** API
- **Where:** JSON-RPC method `handoff.request` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Queue a handoff of this session to a messaging platform.
- **How it works:** `methods_session.py:1567`, registered as `@method("handoff.request")`. Source doc: "Queue a handoff of this session to a messaging platform. Desktop parity with the CLI `/handoff` command: we only write `handoff_state='pending'` onto the persisted session row. The actual transfer is performed by the separate `hermes gateway` process, whose `_handoff_watcher` claims the row, re-binds the session to the platform's home channel, and forges a synthetic turn. The desktop then polls `handoff.state` for the terminal result."
- **Inputs / options:** `platform`
- **Outputs / side effects:** `_ok` result keys: `home_name`, `platform`, `queued`, `session_key`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4009` ("session busy — wait for the current turn to finish, then retry the handoff"), `4023` ("platform required"), `4024` ("unknown platform '{platform_name}'"), `4025` ("platform '{platform_name}' is not configured/enabled in the gateway"), `4026` ("no home channel configured for {platform_name} — set one with "), `4027` ("session is already in flight for handoff — wait for it to settle, then retry"), `5007`, `5021` ("could not load gateway config: {e}")
- **Rebuild notes:** n/a

### `handoff.state`  `id: tui.rpc-handoff-state`
- **Surface:** API
- **Where:** JSON-RPC method `handoff.state` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Poll the handoff state for a session.
- **How it works:** `methods_session.py:1655`, registered as `@method("handoff.state")`. Source doc: "Poll the handoff state for a session. Returns `{state, platform, error}` where `state` is one of `pending|running|completed|failed` (or empty when no handoff record exists). Desktop polls this after `handoff.request`."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `error`, `platform`, `state`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `handoff.fail`  `id: tui.rpc-handoff-fail`
- **Surface:** API
- **Where:** JSON-RPC method `handoff.fail` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Mark a not-yet-claimed handoff as failed so the user can retry.
- **How it works:** `methods_session.py:1682`, registered as `@method("handoff.fail")`. Source doc: "Mark a not-yet-claimed handoff as failed so the user can retry. Desktop calls this when its bounded poll times out. Only PENDING rows are changed (compare-and-swap in `fail_handoff`): once the gateway watcher has claimed the row (`running`) it owns the terminal state — failing it from the waiter races the in-flight dispatch, which later overwrites `failed` → `completed` after the user was already told it failed (split-brain; the delivery actually happened). For a `running` row the caller gets `{"failed": False, "state": "running"}` and should surface "still transferring" instead."
- **Inputs / options:** `error`
- **Outputs / side effects:** `_ok` result keys: `failed`, `state`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.usage`  `id: tui.rpc-session-usage`
- **Surface:** API
- **Where:** JSON-RPC method `session.usage` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.usage` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:1719`, registered as `@method("session.usage")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.context_breakdown`  `id: tui.rpc-session-context-breakdown`
- **Surface:** API
- **Where:** JSON-RPC method `session.context_breakdown` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `session.context_breakdown` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:1743`, registered as `@method("session.context_breakdown")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `categories`, `context_max`, `context_percent`, `context_used`, `estimated_total`, `model`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5000` ("Could not compute context breakdown: {exc}")
- **Rebuild notes:** n/a

### `pet.info`  `id: tui.rpc-pet-info`
- **Surface:** API
- **Where:** JSON-RPC method `pet.info` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Return the active petdex pet for surfaces that render sprites.
- **How it works:** `methods_session.py:1774`, registered as `@method("pet.info")`. Source doc: "Return the active petdex pet for surfaces that render sprites. Shared by the desktop (canvas) and the TUI (half-block). Carries the spritesheet bytes (base64) plus the engine's frame geometry + state-row taxonomy so the renderer is a thin, framework-native consumer. The activity→state decision is mirrored from `agent.pet.state` client-side. Agent-independent (reads config + disk), so it works on any session and before the agent finishes building. Fail-open: returns `enabled=False` on any error rather than erroring the surface." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `knownRevision`
- **Outputs / side effects:** `_ok` result keys: `enabled`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.info.meta`  `id: tui.rpc-pet-info-meta`
- **Surface:** API
- **Where:** JSON-RPC method `pet.info.meta` on the TUI gateway (called by the TUI).
- **What it does:** Cheap active-pet metadata used to avoid full payload refreshes.
- **How it works:** `methods_session.py:1810`, registered as `@method("pet.info.meta")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `displayName`, `enabled`, `scale`, `slug`, `spritesheetRevision`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.cells`  `id: tui.rpc-pet-cells`
- **Surface:** API
- **Where:** JSON-RPC method `pet.cells` on the TUI gateway (called by the TUI).
- **What it does:** Return half-block cell frames for one pet state (TUI renderer).
- **How it works:** `methods_session.py:1833`, registered as `@method("pet.cells")`. Source doc: "Return half-block cell frames for one pet state (TUI renderer). The TUI can't draw a canvas, so the engine downsamples the spritesheet to a grid of half-block cells and the Ink side paints them with native color props. Each cell is `[tr,tg,tb,ta, br,bg,bb,ba]` (top + bottom pixel). Params: `state` (idle/run/review/failed/wave/jump), `cols` (width). Fail-open: `enabled=False` on any problem." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `cols`, `graphics`, `state`
- **Outputs / side effects:** `_ok` result keys: `color`, `cols`, `displayName`, `enabled`, `frameMs`, `frames`, `graphics`, `imageId`, `placeholder`, `rows`, `scale`, `slug`, `state`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.gallery`  `id: tui.rpc-pet-gallery`
- **Surface:** API
- **Where:** JSON-RPC method `pet.gallery` on the TUI gateway (called by the TUI).
- **What it does:** List adoptable pets for the desktop appearance picker.
- **How it works:** `methods_session.py:1938`, registered as `@method("pet.gallery")`. Source doc: "List adoptable pets for the desktop appearance picker. Returns the petdex gallery merged with local install state plus the current config (active slug + enabled). Agent-independent. Fail-open: returns whatever is installed locally if the gallery can't be reached, so the picker still works offline. Param `localOnly` (bool): skip the remote petdex manifest fetch and return only locally-installed pets. The desktop loads this first so the user's own pets render instantly instead of waiting on the (possibly slow) manifest." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `localOnly`
- **Outputs / side effects:** `_ok` result keys: `active`, `enabled`, `pets`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.select`  `id: tui.rpc-pet-select`
- **Surface:** API
- **Where:** JSON-RPC method `pet.select` on the TUI gateway (called by the TUI).
- **What it does:** Adopt a pet from the desktop picker: install (if needed) + activate.
- **How it works:** `methods_session.py:2021`, registered as `@method("pet.select")`. Source doc: "Adopt a pet from the desktop picker: install (if needed) + activate. Params: `slug` (required). Writes `display.pet.*` to config and returns `{ok, slug, displayName}`. The surface re-pulls `pet.info` to render it." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `slug`
- **Outputs / side effects:** `_ok` result keys: `displayName`, `ok`, `slug`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("missing slug"), `5031` ("could not adopt '{slug}': {exc}"), `5031` ("pet.select failed: {exc}")
- **Rebuild notes:** n/a

### `pet.remove`  `id: tui.rpc-pet-remove`
- **Surface:** API
- **Where:** JSON-RPC method `pet.remove` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Uninstall a pet from the desktop picker (delete its on-disk directory).
- **How it works:** `methods_session.py:2048`, registered as `@method("pet.remove")`. Source doc: "Uninstall a pet from the desktop picker (delete its on-disk directory). Params: `slug` (required). If the removed pet was the active one, the display is turned off so nothing tries to render a now-missing sprite. Returns `{ok, slug}` where `ok` reflects whether a directory was deleted."
- **Inputs / options:** `slug`
- **Outputs / side effects:** `_ok` result keys: `ok`, `slug`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("missing slug"), `5031` ("pet.remove failed: {exc}")
- **Rebuild notes:** n/a

### `pet.export`  `id: tui.rpc-pet-export`
- **Surface:** API
- **Where:** JSON-RPC method `pet.export` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Export an installed pet as a re-importable ``.zip`` (pet.json + sprite).
- **How it works:** `methods_session.py:2078`, registered as `@method("pet.export")`. Source doc: "Export an installed pet as a re-importable `.zip` (pet.json + sprite). Params: `slug` (required). Returns `{ok, filename, zipBase64}` — the client decodes the base64 and saves it. Heavy-ish (reads + zips files) but small; runs inline."
- **Inputs / options:** `slug`
- **Outputs / side effects:** `_ok` result keys: `filename`, `ok`, `zipBase64`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("missing slug"), `5031` ("pet.export failed: {exc}")
- **Rebuild notes:** n/a

### `pet.rename`  `id: tui.rpc-pet-rename`
- **Surface:** API
- **Where:** JSON-RPC method `pet.rename` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Rename an installed pet's display name + realign its slug/dir.
- **How it works:** `methods_session.py:2105`, registered as `@method("pet.rename")`. Source doc: "Rename an installed pet's display name + realign its slug/dir. Params: `slug` + `name` (both required). Lets the generate flow hatch with a provisional name and apply the user's chosen name at adopt time. Returns `{ok, slug, displayName}` with the (possibly new) slug."
- **Inputs / options:** `name`, `slug`
- **Outputs / side effects:** `_ok` result keys: `displayName`, `ok`, `slug`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("missing name"), `4004` ("missing slug"), `5031` ("pet.rename failed"), `5031` ("pet.rename failed: {exc}")
- **Rebuild notes:** n/a

### `pet.thumb`  `id: tui.rpc-pet-thumb`
- **Surface:** API
- **Where:** JSON-RPC method `pet.thumb` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Return a small idle-frame PNG (data URI) for one pet — the picker preview.
- **How it works:** `methods_session.py:2143`, registered as `@method("pet.thumb")`. Source doc: "Return a small idle-frame PNG (data URI) for one pet — the picker preview. Cropped + cached server-side so the renderer gets a same-origin data URL instead of a CDN `<img>` (which the desktop CSP / R2 hotlink rules break). Params: `slug` (required), `url` (optional petdex spritesheet URL used only for not-yet-installed pets). Fail-open: `{ok: false}` with no error." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `slug`, `url`
- **Outputs / side effects:** `_ok` result keys: `dataUri`, `ok`, `slug`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("missing slug")
- **Rebuild notes:** n/a

### `pet.disable`  `id: tui.rpc-pet-disable`
- **Surface:** API
- **Where:** JSON-RPC method `pet.disable` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Turn the pet off from the desktop picker (``display.pet.enabled=false``).
- **How it works:** `methods_session.py:2178`, registered as `@method("pet.disable")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `ok`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5031` ("pet.disable failed: {exc}")
- **Rebuild notes:** n/a

### `pet.scale`  `id: tui.rpc-pet-scale`
- **Surface:** API
- **Where:** JSON-RPC method `pet.scale` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Persist ``display.pet.scale`` from the desktop slider.
- **How it works:** `methods_session.py:2192`, registered as `@method("pet.scale")`. Source doc: "Persist `display.pet.scale` from the desktop slider. Params: `scale`. Clamped to the engine bounds. The renderer updates its own `$petInfo` for instant feedback; this just makes the change durable + visible to the other terminal surfaces on their next read."
- **Inputs / options:** `scale`
- **Outputs / side effects:** `_ok` result keys: `ok`, `scale`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004`, `5031` ("pet.scale failed: {exc}")
- **Rebuild notes:** n/a

### `pet.cancel`  `id: tui.rpc-pet-cancel`
- **Surface:** API
- **Where:** JSON-RPC method `pet.cancel` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Signal an in-flight ``pet.generate``/``pet.hatch`` (by token) to stop.
- **How it works:** `methods_session.py:2212`, registered as `@method("pet.cancel")`. Source doc: "Signal an in-flight `pet.generate`/`pet.hatch` (by token) to stop. Best-effort + idempotent: cancelling an unknown/finished token is a no-op. Stays off the worker pool so it lands while a heavy generation is occupying it. Returns `{ok: True}`."
- **Inputs / options:** `token`
- **Outputs / side effects:** `_ok` result keys: `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.generate.status`  `id: tui.rpc-pet-generate-status`
- **Surface:** API
- **Where:** JSON-RPC method `pet.generate.status` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Whether pet generation is possible right now.
- **How it works:** `methods_session.py:2226`, registered as `@method("pet.generate.status")`. Source doc: "Whether pet generation is possible right now. True only when a reference-capable image backend (Nous Portal / OpenRouter / OpenAI gpt-image) is configured — the desktop checks this on open so it can offer setup instead of a dead prompt. Cheap (config + plugin discovery)."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `available`, `providers`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `pet.generate`  `id: tui.rpc-pet-generate`
- **Surface:** API
- **Where:** JSON-RPC method `pet.generate` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Generate candidate base looks for a new pet (the draft/variant step).
- **How it works:** `methods_session.py:2257`, registered as `@method("pet.generate")`. Source doc: "Generate candidate base looks for a new pet (the draft/variant step). Params: `prompt` (required unless `referenceImage` is given), `count` (default 4), `style` (default `auto`), `referenceImage` (optional data URL — a user photo/reference every draft is grounded on, e.g. to make *their* pet). Returns `{ok, token, drafts:[{index, dataUri}]}` — the token keys the staged base images for a later `pet.hatch`. Heavy (network): worker pool." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `count`, `prompt`, `provider`, `referenceImage`, `style`
- **Outputs / side effects:** `_ok` result keys: `drafts`, `ok`, `token`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004`, `4004` ("missing prompt"), `5031`, `5031` ("generation cancelled"), `5031` ("generation produced no usable drafts"), `5031` ("pet.generate failed: {exc}")
- **Rebuild notes:** n/a

### `pet.hatch`  `id: tui.rpc-pet-hatch`
- **Surface:** API
- **Where:** JSON-RPC method `pet.hatch` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Turn a chosen base draft into a full pet — installed but NOT yet active.
- **How it works:** `methods_session.py:2370`, registered as `@method("pet.hatch")`. Source doc: "Turn a chosen base draft into a full pet — installed but NOT yet active. Generation is expensive and the result varies, so hatch produces a *preview* the surface plays (all frames) before the user commits: the pet is written to the store (so it can be rendered + later activated) but the active pet is left untouched. Adopt with `pet.select` or throw it away with `pet.remove`. Params: `token` + `index` (from `pet.generate`), `name` (required), `description` (optional), `prompt` (optional concept for row prompts), `style` (optional). Returns `{ok, slug, displayName, warnings, p" Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `cancelToken`, `description`, `index`, `name`, `prompt`, `provider`, `style`, `token`
- **Outputs / side effects:** `_ok` result keys: `displayName`, `ok`, `pet`, `slug`, `warnings`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("draft expired — generate again"), `4004` ("missing name"), `4004` ("missing token"), `5031`, `5031` ("pet.hatch failed: {exc}")
- **Rebuild notes:** n/a

### `billing.state`  `id: tui.rpc-billing-state`
- **Surface:** API
- **Where:** JSON-RPC method `billing.state` on the TUI gateway (called by the TUI).
- **What it does:** GET /api/billing/state → serialized BillingState (Screen 1 + 5).
- **How it works:** `methods_session.py:2469`, registered as `@method("billing.state")`. Source doc: "GET /api/billing/state → serialized BillingState (Screen 1 + 5). Fail-open like the other billing RPCs: a logged-out / unreachable portal yields {ok:true, logged_in:false}. No scope required for this endpoint." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `error`, `logged_in`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `usage.bars`  `id: tui.rpc-usage-bars`
- **Surface:** API
- **Where:** JSON-RPC method `usage.bars` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Shared dollar usage model (two-bar view) for /usage + /subscription.
- **How it works:** `methods_session.py:2485`, registered as `@method("usage.bars")`. Source doc: "Shared dollar usage model (two-bar view) for /usage + /subscription. Fail-open: logged-out / unreachable portal → {ok:true, available:false}. No scope required (read-only)." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `available`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subscription.state`  `id: tui.rpc-subscription-state`
- **Surface:** API
- **Where:** JSON-RPC method `subscription.state` on the TUI gateway (called by the TUI).
- **What it does:** GET /api/billing/subscription → serialized SubscriptionState.
- **How it works:** `methods_session.py:2500`, registered as `@method("subscription.state")`. Source doc: "GET /api/billing/subscription → serialized SubscriptionState. Fail-open like billing.state: logged-out / unreachable portal → {ok:true, logged_in:false}. No scope required (read-only)." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `error`, `logged_in`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subscription.preview`  `id: tui.rpc-subscription-preview`
- **Surface:** API
- **Where:** JSON-RPC method `subscription.preview` on the TUI gateway (called by the TUI).
- **What it does:** POST /api/billing/subscription/preview → serialized quote or typed error.
- **How it works:** `methods_session.py:2516`, registered as `@method("subscription.preview")`. Source doc: "POST /api/billing/subscription/preview → serialized quote or typed error. params: {subscription_type_id: str}. Chargeless effect quote. Requires billing:manage (live Stripe calls + amounts), so a 403 → insufficient_scope drives the device step-up exactly like the mutations." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `subscription_type_id`
- **Outputs / side effects:** `_ok` result keys: `error`, `message`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subscription.change`  `id: tui.rpc-subscription-change`
- **Surface:** API
- **Where:** JSON-RPC method `subscription.change` on the TUI gateway (called by the TUI).
- **What it does:** PUT /api/billing/subscription/pending-change → {ok, message} or typed error.
- **How it works:** `methods_session.py:2541`, registered as `@method("subscription.change")`. Source doc: "PUT /api/billing/subscription/pending-change → {ok, message} or typed error. params: {subscription_type_id?: str, cancel?: bool}. Schedules a downgrade / same-price change OR a cancellation at period end (chargeless). Requires billing:manage." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `cancel`, `subscription_type_id`
- **Outputs / side effects:** `_ok` result keys: `error`, `message`, `ok`, `payload`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subscription.resume`  `id: tui.rpc-subscription-resume`
- **Surface:** API
- **Where:** JSON-RPC method `subscription.resume` on the TUI gateway (called by the TUI).
- **What it does:** DELETE /api/billing/subscription/pending-change → {ok, message} or typed error.
- **How it works:** `methods_session.py:2564`, registered as `@method("subscription.resume")`. Source doc: "DELETE /api/billing/subscription/pending-change → {ok, message} or typed error. Clears a scheduled downgrade or cancellation (resume / undo). Chargeless, but it re-enables recurring spend → requires billing:manage and honors the kill-switch." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `error`, `message`, `ok`, `payload`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subscription.upgrade`  `id: tui.rpc-subscription-upgrade`
- **Surface:** API
- **Where:** JSON-RPC method `subscription.upgrade` on the TUI gateway (called by the TUI).
- **What it does:** POST /api/billing/subscription/upgrade → {ok, status, ...} or typed error.
- **How it works:** `methods_session.py:2582`, registered as `@method("subscription.upgrade")`. Source doc: "POST /api/billing/subscription/upgrade → {ok, status, ...} or typed error. params: {subscription_type_id: str, idempotency_key?: str}. The single money route: prorate + charge the card on the subscription + flip the plan. SCA / decline come back as status requires_action / payment_failed with a recovery_url to finish in the portal. The idempotency key is minted if absent and echoed so the TUI reuses it on retry of the SAME upgrade. Requires billing:manage." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `idempotency_key`, `subscription_type_id`
- **Outputs / side effects:** `_ok` result keys: `error`, `idempotency_key`, `message`, `ok`, `reason`, `recovery_url`, `status`, `target_tier_name`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `billing.charge`  `id: tui.rpc-billing-charge`
- **Surface:** API
- **Where:** JSON-RPC method `billing.charge` on the TUI gateway (called by the TUI).
- **What it does:** POST /api/billing/charge → {ok, chargeId} or a typed error envelope.
- **How it works:** `methods_session.py:2620`, registered as `@method("billing.charge")`. Source doc: "POST /api/billing/charge → {ok, chargeId} or a typed error envelope. params: {amount_usd: str|number, idempotency_key?: str}. If no key is supplied, the server-side core mints a fresh one and returns it so the TUI can reuse it on retry of the SAME purchase."
- **Inputs / options:** `amount_usd`, `idempotency_key`
- **Outputs / side effects:** `_ok` result keys: `charge_id`, `error`, `idempotency_key`, `message`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `billing.charge_status`  `id: tui.rpc-billing-charge-status`
- **Surface:** API
- **Where:** JSON-RPC method `billing.charge_status` on the TUI gateway (called by the TUI).
- **What it does:** GET /api/billing/charge/{id} → {ok, status, ...} or typed error.
- **How it works:** `methods_session.py:2646`, registered as `@method("billing.charge_status")`. Source doc: "GET /api/billing/charge/{id} → {ok, status, ...} or typed error. The poll. Caller drives the 2s/5-min cadence; this is a single status read."
- **Inputs / options:** `charge_id`
- **Outputs / side effects:** `_ok` result keys: `amount_usd`, `error`, `message`, `ok`, `reason`, `settled_at`, `status`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `billing.auto_reload`  `id: tui.rpc-billing-auto-reload`
- **Surface:** API
- **Where:** JSON-RPC method `billing.auto_reload` on the TUI gateway (called by the TUI).
- **What it does:** PATCH /api/billing/auto-top-up → {ok:true} or typed error (Screen 2).
- **How it works:** `methods_session.py:2675`, registered as `@method("billing.auto_reload")`. Source doc: "PATCH /api/billing/auto-top-up → {ok:true} or typed error (Screen 2). params: {enabled: bool, threshold: number, top_up_amount: number}."
- **Inputs / options:** `enabled`, `threshold`, `top_up_amount`
- **Outputs / side effects:** `_ok` result keys: `error`, `message`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `billing.step_up`  `id: tui.rpc-billing-step-up`
- **Surface:** API
- **Where:** JSON-RPC method `billing.step_up` on the TUI gateway (called by the TUI).
- **What it does:** Run the lazy billing:manage step-up device flow → {ok, granted}.
- **How it works:** `methods_session.py:2697`, registered as `@method("billing.step_up")`. Source doc: "Run the lazy billing:manage step-up device flow → {ok, granted}. Triggered by the TUI after a billing call returns error=insufficient_scope. Returns granted:false when the server silently downscopes (non-admin / unticked). Runs on the thread pool (in _LONG_HANDLERS): the device flow blocks for the whole device-code lifetime (minutes), so it must not stall the main stdin loop. The verification URL/code reach the TUI via an out-of-band `billing.step_up. verification` event (a plain print would be dropped by the JSON-RPC stdout pipe), and the browser is opened TUI-side via openExternalUrl — nev" Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `error`, `granted`, `message`, `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.status`  `id: tui.rpc-session-status`
- **Surface:** API
- **Where:** JSON-RPC method `session.status` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.status` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:2738`, registered as `@method("session.status")`.
- **Inputs / options:** `profile`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `output`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.history`  `id: tui.rpc-session-history`
- **Surface:** API
- **Where:** JSON-RPC method `session.history` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `session.history` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:2814`, registered as `@method("session.history")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `count`, `messages`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.undo`  `id: tui.rpc-session-undo`
- **Surface:** API
- **Where:** JSON-RPC method `session.undo` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.undo` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:2846`, registered as `@method("session.undo")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `removed`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4009` ("session busy — /interrupt the current turn before /undo"), `5008` ("undo: {exc}")
- **Rebuild notes:** n/a

### `session.compress`  `id: tui.rpc-session-compress`
- **Surface:** API
- **Where:** JSON-RPC method `session.compress` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.compress` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:2893`, registered as `@method("session.compress")`.
- **Inputs / options:** `focus_topic`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `after_messages`, `after_tokens`, `before_messages`, `before_tokens`, `compressed`, `host_ack`, `info`, `lock_held`, `message`, `messages`, `removed`, `status`, `summary`, `turn_isolation`, `usage`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4009`, `4009` ("session busy — /interrupt the current turn before /compress"), `5005`, `5019` ("compute-host compress failed: {exc}")
- **Rebuild notes:** n/a

### `session.save`  `id: tui.rpc-session-save`
- **Surface:** API
- **Where:** JSON-RPC method `session.save` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.save` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3065`, registered as `@method("session.save")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `file`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5011`, `5011` ("compute-host session save failed: {exc}"), `5011` ("compute-host session save returned an invalid response"), `5011` ("failed to create save directory {saved_dir}: {e}")
- **Rebuild notes:** n/a

### `session.close`  `id: tui.rpc-session-close`
- **Surface:** API
- **Where:** JSON-RPC method `session.close` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.close` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3137`, registered as `@method("session.close")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `closed`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.branch`  `id: tui.rpc-session-branch`
- **Surface:** API
- **Where:** JSON-RPC method `session.branch` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.branch` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3149`, registered as `@method("session.branch")`.
- **Inputs / options:** `count`, `name`
- **Outputs / side effects:** `_ok` result keys: `info`, `message_count`, `messages`, `parent`, `session_id`, `stored_session_id`, `title`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4008` ("nothing to branch — send a message first"), `5000` ("agent init failed on branch: {e}"), `5008` ("branch failed: {e}")
- **Rebuild notes:** n/a

### `session.interrupt`  `id: tui.rpc-session-interrupt`
- **Surface:** API
- **Where:** JSON-RPC method `session.interrupt` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `session.interrupt` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3371`, registered as `@method("session.interrupt")`.
- **Inputs / options:** `expected_hosted_task_id`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `interrupted`, `status`, `turn_isolation`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5019` ("compute-host interrupt failed: {exc}")
- **Rebuild notes:** n/a

### `delegation.status`  `id: tui.rpc-delegation-status`
- **Surface:** API
- **Where:** JSON-RPC method `delegation.status` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `delegation.status` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3405`, registered as `@method("delegation.status")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `active`, `max_concurrent_children`, `max_spawn_depth`, `paused`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `delegation.pause`  `id: tui.rpc-delegation-pause`
- **Surface:** API
- **Where:** JSON-RPC method `delegation.pause` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `delegation.pause` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3425`, registered as `@method("delegation.pause")`.
- **Inputs / options:** `paused`
- **Outputs / side effects:** `_ok` result keys: `paused`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `subagent.interrupt`  `id: tui.rpc-subagent-interrupt`
- **Surface:** API
- **Where:** JSON-RPC method `subagent.interrupt` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `subagent.interrupt` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3433`, registered as `@method("subagent.interrupt")`.
- **Inputs / options:** `subagent_id`
- **Outputs / side effects:** `_ok` result keys: `found`, `subagent_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4000` ("subagent_id required")
- **Rebuild notes:** n/a

### `subagent.steer`  `id: tui.rpc-subagent-steer`
- **Surface:** API
- **Where:** JSON-RPC method `subagent.steer` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Queue steering text into a live delegated child without stopping it.
- **How it works:** `methods_session.py:3444`, registered as `@method("subagent.steer")`. Source doc: "Queue steering text into a live delegated child without stopping it. The redirection-side mirror of subagent.interrupt: resolves the child in the delegation registry and calls AIAgent.steer(), which appends the text to the child's last tool result at its next iteration boundary — the in-flight tool call is never cut. "queued" is not "delivered": a child already past its final tool batch has no boundary left to drain into, and that race surfaces as `missed_steer` on the parent's completion entry instead of being silently dropped."
- **Inputs / options:** `session_id`, `subagent_id`, `text`
- **Outputs / side effects:** `_ok` result keys: `status`, `subagent_id`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4000` ("subagent_id required"), `4002` ("text is required")
- **Rebuild notes:** n/a

### `spawn_tree.save`  `id: tui.rpc-spawn-tree-save`
- **Surface:** API
- **Where:** JSON-RPC method `spawn_tree.save` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `spawn_tree.save` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3490`, registered as `@method("spawn_tree.save")`.
- **Inputs / options:** `finished_at`, `label`, `session_id`, `started_at`, `subagents`
- **Outputs / side effects:** `_ok` result keys: `path`, `session_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4000` ("subagents list required"), `5000` ("spawn_tree.save failed: {exc}")
- **Rebuild notes:** n/a

### `spawn_tree.list`  `id: tui.rpc-spawn-tree-list`
- **Surface:** API
- **Where:** JSON-RPC method `spawn_tree.list` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `spawn_tree.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3533`, registered as `@method("spawn_tree.list")`.
- **Inputs / options:** `cross_session`, `limit`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `entries`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `spawn_tree.load`  `id: tui.rpc-spawn-tree-load`
- **Surface:** API
- **Where:** JSON-RPC method `spawn_tree.load` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `spawn_tree.load` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3584`, registered as `@method("spawn_tree.load")`.
- **Inputs / options:** `path`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4000` ("path required"), `4030` ("path outside spawn-trees root: {exc}"), `5000` ("spawn_tree.load failed: {exc}")
- **Rebuild notes:** n/a

### `session.steer`  `id: tui.rpc-session-steer`
- **Surface:** API
- **Where:** JSON-RPC method `session.steer` on the TUI gateway (called by the TUI).
- **What it does:** Inject a user message into the next tool result without interrupting.
- **How it works:** `methods_session.py:3608`, registered as `@method("session.steer")`. Source doc: "Inject a user message into the next tool result without interrupting. Mirrors AIAgent.steer(). Safe to call while a turn is running — the text lands on the last tool result of the next tool batch and the model sees it on its next iteration. No interrupt, no new user turn, no role alternation violation."
- **Inputs / options:** `text`
- **Outputs / side effects:** `_ok` result keys: `status`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4002` ("text is required"), `4010` ("agent does not support steer"), `5000` ("steer failed: {exc}")
- **Rebuild notes:** n/a

### `session.redirect`  `id: tui.rpc-session-redirect`
- **Surface:** API
- **Where:** JSON-RPC method `session.redirect` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Redirect the active model turn while preserving valid work/context.
- **How it works:** `methods_session.py:3645`, registered as `@method("session.redirect")`.
- **Inputs / options:** `text`
- **Outputs / side effects:** `_ok` result keys: `status`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4002` ("text is required"), `4010` ("agent does not support active-turn redirect"), `5000` ("redirect failed: {exc}")
- **Rebuild notes:** n/a

### `terminal.resize`  `id: tui.rpc-terminal-resize`
- **Surface:** API
- **Where:** JSON-RPC method `terminal.resize` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `terminal.resize` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_session.py:3687`, registered as `@method("terminal.resize")`.
- **Inputs / options:** `cols`
- **Outputs / side effects:** `_ok` result keys: `cols`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.events.since`  `id: tui.rpc-session-events-since`
- **Surface:** API
- **Where:** JSON-RPC method `session.events.since` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Replay recorded events for a session newer than the client's last-seen seq.
- **How it works:** `methods_session.py:3696`, registered as `@method("session.events.since")`. Source doc: "Replay recorded events for a session newer than the client's last-seen seq. Reconnect contract (desktop / web clients): every event frame now carries `params.seq`. After a WS reconnect the client calls this with its last observed seq; this returns the buffered frames in order so no mid-stream event is lost. Frames older than the ring window report `truncated` so the client knows to refetch history instead of silently accepting a gap."
- **Inputs / options:** `last_seen`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `count`, `epoch`, `events`, `latest_seq`, `truncated`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `session.events.stats`  `id: tui.rpc-session-events-stats`
- **Surface:** API
- **Where:** JSON-RPC method `session.events.stats` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Replay-buffer telemetry (ops/debug).
- **How it works:** `methods_session.py:3727`, registered as `@method("session.events.stats")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `tui_gateway/methods_prompt.py` — prompt submission, attachments, prompt responses  `id: tui.rpcgroup-methods-prompt`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_prompt.py` (23 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_prompt.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `prompt.submit`  `id: tui.rpc-prompt-submit`
- **Surface:** API
- **Where:** JSON-RPC method `prompt.submit` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `prompt.submit` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:288`, registered as `@method("prompt.submit")`.
- **Inputs / options:** `_hosted_task`, `_hosted_terminal_callback`, `confirm_empty_truncate`, `confirm_truncate`, `display_kind`, `interrupted`, `profile`, `queued`, `rebind_survivor_row_ids`, `session_id`, `surface`, `text`, `truncate_before_message_id`, `truncate_before_row_id`, `truncate_before_user_ordinal`
- **Outputs / side effects:** `_ok` result keys: `status`, `survivor_row_id_map`, `survivor_user_row_ids`, `voice_stopped`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("confirm_truncate requires truncate_before_user_ordinal, truncate_before_message_id, or tru"), `4004` ("ordinal-only truncation is unsafe for durable session history; "), `4009` ("subagent still running — wait for it to finish"), `4018` ("target user message is no longer in session history"), `4028` ("truncation would erase the entire session transcript; "), `4029` ("truncation parameters require confirm_truncate=true; "), `4090`, `4091` ("hosted room member session is busy"), `4120` ("hosted room turns require a bot_room session"), `4120` ("invalid hosted room turn proof"), `4121` ("hosted room turns do not support isolated compute workers yet"), `4122`, `5008` ("failed to persist history truncation: {exc}"), `5070` ("disk full: session storage could not be written — free some disk space and try again"), `5071` ("session storage could not be written: {exc}"), `5072` ("session storage unavailable: "), `5122` ("Could not verify this group. Try again after the gateway recovers.")
- **Rebuild notes:** n/a

### `clipboard.paste`  `id: tui.rpc-clipboard-paste`
- **Surface:** API
- **Where:** JSON-RPC method `clipboard.paste` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `clipboard.paste` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1053`, registered as `@method("clipboard.paste")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `attached`, `count`, `message`, `path`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5027` ("clipboard unavailable: {e}")
- **Rebuild notes:** n/a

### `image.attach`  `id: tui.rpc-image-attach`
- **Surface:** API
- **Where:** JSON-RPC method `image.attach` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `image.attach` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1093`, registered as `@method("image.attach")`.
- **Inputs / options:** `path`
- **Outputs / side effects:** `_ok` result keys: `attached`, `count`, `path`, `remainder`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("path required"), `4016` ("image not found: {path_token}"), `4016` ("unsupported image: {image_path.name}"), `5027`
- **Rebuild notes:** n/a

### `image.attach_bytes`  `id: tui.rpc-image-attach-bytes`
- **Surface:** API
- **Where:** JSON-RPC method `image.attach_bytes` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Attach an image to the session from base64 bytes (remote-client path).
- **How it works:** `methods_prompt.py:1136`, registered as `@method("image.attach_bytes")`. Source doc: "Attach an image to the session from base64 bytes (remote-client path). A desktop app or web dashboard running on a DIFFERENT machine than the gateway can't hand us a local path — that file only exists on the client's disk. So it uploads the raw image bytes (base64) and we write them into the gateway's own images dir. The response shape mirrors `image.attach` so the client treats both identically. Params: content_base64 / data (str, required): base64 image bytes. Accepts a `data:image/...;base64,` prefix and embedded whitespace. `data` is an accepted alias for older desktop builds. filena"
- **Inputs / options:** `content_base64`, `data`, `ext`, `filename`
- **Outputs / side effects:** `_ok` result keys: `attached`, `bytes`, `count`, `path`, `remainder`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("content_base64 required"), `4016` ("unsupported image extension: {ext}"), `4017` ("data is not valid base64"), `4017` ("image is empty"), `4018` ("image too large ({len(img_bytes)} bytes; cap is {mb} MB)"), `5027` ("write failed: {e}")
- **Rebuild notes:** n/a

### `pdf.attach`  `id: tui.rpc-pdf-attach`
- **Surface:** API
- **Where:** JSON-RPC method `pdf.attach` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Attach a PDF by rendering each page to PNG and queuing the pages.
- **How it works:** `methods_prompt.py:1197`, registered as `@method("pdf.attach")`. Source doc: "Attach a PDF by rendering each page to PNG and queuing the pages. Anthropic's vision pipeline accepts images, not PDFs, so this runs `pdftoppm` (poppler-utils) at 150 DPI per page and queues each rendered page as an attached image. Accepts either a host `path` (local mode) or base64 `content_base64` (remote upload). Caps at 50 MB / 25 pages per call. Requires `pdftoppm` on $PATH (`apt install poppler-utils`); returns 5028 if missing."
- **Inputs / options:** `content_base64`, `data`, `filename`, `first_page`, `last_page`, `path`
- **Outputs / side effects:** `_ok` result keys: `attached`, `count`, `filename`, `pages`, `pages_attached`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("first_page must be >= 1"), `4015` ("first_page/last_page must be integers"), `4015` ("last_page must be >= first_page"), `4015` ("path or content_base64 required"), `4016` ("PDF not found: {raw_path}"), `4016` ("not a PDF: {Path(resolved).name}"), `4017` ("data is not valid base64"), `4017` ("decoded PDF is empty"), `4017` ("payload is not a PDF (missing %PDF- magic bytes)"), `4018` ("PDF too large ({len(pdf_bytes)} bytes; cap is {mb} MB)"), `4018` ("PDF too large; cap is {mb} MB"), `4019` ("page range exceeds cap of {_PDF_ATTACH_MAX_PAGES} pages per attach call"), `5028` ("pdftoppm failed: "), `5028` ("pdftoppm not installed (poppler-utils package required)"), `5028` ("pdftoppm produced no pages (corrupt PDF?)"), `5028` ("pdftoppm timed out (>120s)")
- **Rebuild notes:** n/a

### `file.attach`  `id: tui.rpc-file-attach`
- **Surface:** API
- **Where:** JSON-RPC method `file.attach` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Stage a non-image file attachment into the session workspace.
- **How it works:** `methods_prompt.py:1323`, registered as `@method("file.attach")`. Source doc: "Stage a non-image file attachment into the session workspace. The image/PDF path renders to vision tiles; this one keeps the file as a readable artifact and returns a workspace-relative `@file:` ref so the agent's file tools (and `agent.context_references`) can read it. Solves the remote-gateway case where the desktop passes a path that only exists on the CLIENT's disk: the client uploads `data_url` bytes and we materialize the file on the gateway. Params: session_id (str, required) path (str): client/host path of the file (used for naming + local-mode gateway-visible resolution). data_u"
- **Inputs / options:** `data_url`, `name`, `path`
- **Outputs / side effects:** `_ok` result keys: `attached`, `name`, `path`, `ref_path`, `ref_text`, `uploaded`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("path or data_url required"), `5028`
- **Rebuild notes:** n/a

### `image.detach`  `id: tui.rpc-image-detach`
- **Surface:** API
- **Where:** JSON-RPC method `image.detach` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `image.detach` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1370`, registered as `@method("image.detach")`.
- **Inputs / options:** `path`
- **Outputs / side effects:** `_ok` result keys: `count`, `detached`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("path required")
- **Rebuild notes:** n/a

### `input.detect_drop`  `id: tui.rpc-input-detect-drop`
- **Surface:** API
- **Where:** JSON-RPC method `input.detect_drop` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `input.detect_drop` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1390`, registered as `@method("input.detect_drop")`.
- **Inputs / options:** `text`
- **Outputs / side effects:** `_ok` result keys: `count`, `is_image`, `matched`, `name`, `path`, `text`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5027`
- **Rebuild notes:** n/a

### `prompt.background`  `id: tui.rpc-prompt-background`
- **Surface:** API
- **Where:** JSON-RPC method `prompt.background` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `prompt.background` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1437`, registered as `@method("prompt.background")`.
- **Inputs / options:** `session_id`, `text`
- **Outputs / side effects:** `_ok` result keys: `task_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4012` ("text required")
- **Rebuild notes:** n/a

### `prompt.btw`  `id: tui.rpc-prompt-btw`
- **Surface:** API
- **Where:** JSON-RPC method `prompt.btw` on the TUI gateway (called by the TUI).
- **What it does:** Answer a side question about the session without touching its history.
- **How it works:** `methods_prompt.py:1499`, registered as `@method("prompt.btw")`. Source doc: "Answer a side question about the session without touching its history. Snapshots the live conversation (in-flight `_session_messages` when a turn is running, else the persisted `session["history"]`) and runs a one-shot auxiliary LLM call against it (`agent/side_question.py`). The session's history, role alternation, and prompt cache are untouched; the answer arrives as a `btw.complete` event."
- **Inputs / options:** `session_id`, `text`
- **Outputs / side effects:** `_ok` result keys: `task_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4012` ("text required")
- **Rebuild notes:** n/a

### `preview.restart`  `id: tui.rpc-preview-restart`
- **Surface:** API
- **Where:** JSON-RPC method `preview.restart` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `preview.restart` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1570`, registered as `@method("preview.restart")`.
- **Inputs / options:** `context`, `cwd`, `session_id`, `url`
- **Outputs / side effects:** `_ok` result keys: `task_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4012` ("url required")
- **Rebuild notes:** n/a

### `clarify.respond`  `id: tui.rpc-clarify-respond`
- **Surface:** API
- **Where:** JSON-RPC method `clarify.respond` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `clarify.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1702`, registered as `@method("clarify.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `terminal.read.respond`  `id: tui.rpc-terminal-read-respond`
- **Surface:** API
- **Where:** JSON-RPC method `terminal.read.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `terminal.read.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1713`, registered as `@method("terminal.read.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `preview.read.respond`  `id: tui.rpc-preview-read-respond`
- **Surface:** API
- **Where:** JSON-RPC method `preview.read.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `preview.read.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1722`, registered as `@method("preview.read.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `preview.act.respond`  `id: tui.rpc-preview-act-respond`
- **Surface:** API
- **Where:** JSON-RPC method `preview.act.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `preview.act.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1730`, registered as `@method("preview.act.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `window.read.respond`  `id: tui.rpc-window-read-respond`
- **Surface:** API
- **Where:** JSON-RPC method `window.read.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `window.read.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1739`, registered as `@method("window.read.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `tour.respond`  `id: tui.rpc-tour-respond`
- **Surface:** API
- **Where:** JSON-RPC method `tour.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `tour.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1748`, registered as `@method("tour.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `mcp.setup.respond`  `id: tui.rpc-mcp-setup-respond`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.setup.respond` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `mcp.setup.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1758`, registered as `@method("mcp.setup.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `sudo.respond`  `id: tui.rpc-sudo-respond`
- **Surface:** API
- **Where:** JSON-RPC method `sudo.respond` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `sudo.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1767`, registered as `@method("sudo.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `secret.respond`  `id: tui.rpc-secret-respond`
- **Surface:** API
- **Where:** JSON-RPC method `secret.respond` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `secret.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1772`, registered as `@method("secret.respond")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `approval.pending`  `id: tui.rpc-approval-pending`
- **Surface:** API
- **Where:** JSON-RPC method `approval.pending` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `approval.pending` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1777`, registered as `@method("approval.pending")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `approvals`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5004`
- **Rebuild notes:** n/a

### `approval.received`  `id: tui.rpc-approval-received`
- **Surface:** API
- **Where:** JSON-RPC method `approval.received` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `approval.received` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1790`, registered as `@method("approval.received")`.
- **Inputs / options:** `request_id`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `acknowledged`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4006` ("request_id required"), `5004`
- **Rebuild notes:** n/a

### `approval.respond`  `id: tui.rpc-approval-respond`
- **Surface:** API
- **Where:** JSON-RPC method `approval.respond` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `approval.respond` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_prompt.py:1854`, registered as `@method("approval.respond")`.
- **Inputs / options:** `all`, `choice`, `request_id`
- **Outputs / side effects:** `_ok` result keys: `resolved`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5004`
- **Rebuild notes:** n/a

### `tui_gateway/methods_tools.py` — tools, slash commands, MCP, plugins, skills, cron  `id: tui.rpcgroup-methods-tools`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_tools.py` (41 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_tools.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `system.battery`  `id: tui.rpc-system-battery`
- **Surface:** API
- **Where:** JSON-RPC method `system.battery` on the TUI gateway (called by the TUI).
- **What it does:** Return the host battery status for the status-bar read-out.
- **How it works:** `methods_tools.py:15`, registered as `@method("system.battery")`. Source doc: "Return the host battery status for the status-bar read-out. Always resolves with a payload; `available: false` means there is no battery (desktop/server/VM) or the read failed. The TUI only polls this while the battery indicator is enabled."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `available`, `category`, `percent`, `plugged`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `process.stop`  `id: tui.rpc-process-stop`
- **Surface:** API
- **Where:** JSON-RPC method `process.stop` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `process.stop` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:40`, registered as `@method("process.stop")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `killed`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5010`
- **Rebuild notes:** n/a

### `process.list`  `id: tui.rpc-process-list`
- **Surface:** API
- **Where:** JSON-RPC method `process.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Session-scoped view of the background process registry (desktop status stack).
- **How it works:** `methods_tools.py:50`, registered as `@method("process.list")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `processes`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5010`
- **Rebuild notes:** n/a

### `process.kill`  `id: tui.rpc-process-kill`
- **Surface:** API
- **Where:** JSON-RPC method `process.kill` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Kill ONE background process — scoped to the caller's session so one window can't reap another session's work (unlike process.stop's kill_all).
- **How it works:** `methods_tools.py:62`, registered as `@method("process.kill")`.
- **Inputs / options:** `process_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4012` ("process_id required"), `4044` ("no such process: {proc_id}"), `5010`
- **Rebuild notes:** n/a

### `reload.mcp`  `id: tui.rpc-reload-mcp`
- **Surface:** API
- **Where:** JSON-RPC method `reload.mcp` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `reload.mcp` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:85`, registered as `@method("reload.mcp")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `confirm`, `rev`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `host_ack`, `message`, `status`, `turn_isolation`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5015`, `5019` ("compute-host reload_mcp failed: {exc}")
- **Rebuild notes:** n/a

### `reload.env`  `id: tui.rpc-reload-env`
- **Surface:** API
- **Where:** JSON-RPC method `reload.env` on the TUI gateway (called by the TUI).
- **What it does:** Re-read ``~/.hermes/.env`` into the gateway process via ``hermes_cli.config.reload_env``, matching classic CLI's ``/reload`` handler.
- **How it works:** `methods_tools.py:235`, registered as `@method("reload.env")`. Source doc: "Re-read `~/.hermes/.env` into the gateway process via `hermes_cli.config.reload_env`, matching classic CLI's `/reload` handler. Newly added API keys take effect on the next agent call without restarting the TUI. The credential pool / provider routing for any *already-constructed* agent does not auto-rebuild — that's the same behaviour as classic CLI's `/reload`. Users who want a brand-new credential resolution should follow with `/new`."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `updated`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5015`
- **Rebuild notes:** n/a

### `commands.catalog`  `id: tui.rpc-commands-catalog`
- **Surface:** API
- **Where:** JSON-RPC method `commands.catalog` on the TUI gateway (called by the TUI).
- **What it does:** Registry-backed slash metadata for the TUI — categorized, no aliases.
- **How it works:** `methods_tools.py:256`, registered as `@method("commands.catalog")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `canon`, `categories`, `commands`, `pairs`, `skill_count`, `skills`, `sub`, `warning`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5020`
- **Rebuild notes:** n/a

### `cli.exec`  `id: tui.rpc-cli-exec`
- **Surface:** API
- **Where:** JSON-RPC method `cli.exec` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Run `python -m hermes_cli.main` with argv; capture stdout/stderr (non-interactive only).
- **How it works:** `methods_tools.py:409`, registered as `@method("cli.exec")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `argv`, `timeout`
- **Outputs / side effects:** `_ok` result keys: `blocked`, `code`, `hint`, `output`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4003` ("argv must be list[str]"), `5016` ("cli.exec: timeout"), `5017`
- **Rebuild notes:** n/a

### `command.resolve`  `id: tui.rpc-command-resolve`
- **Surface:** API
- **Where:** JSON-RPC method `command.resolve` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `command.resolve` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:450`, registered as `@method("command.resolve")`.
- **Inputs / options:** `name`
- **Outputs / side effects:** `_ok` result keys: `canonical`, `category`, `description`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4011` ("unknown command: {params.get('name')}"), `5012`
- **Rebuild notes:** n/a

### `command.dispatch`  `id: tui.rpc-command-dispatch`
- **Surface:** API
- **Where:** JSON-RPC method `command.dispatch` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `command.dispatch` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:470`, registered as `@method("command.dispatch")`.
- **Inputs / options:** `arg`, `name`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `display`, `message`, `name`, `notice`, `output`, `target`, `type`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("no active session"), `4001` ("no active session to compress"), `4001` ("no active session to retry"), `4001` ("no active session to undo"), `4001` ("no session key"), `4001` ("no session key for undo"), `4004`, `4004` ("invalid goal: {exc}"), `4004` ("undo: invalid count {arg_str!r} — use /undo or /undo N"), `4004` ("undo: {exc}"), `4004` ("usage: /focus [on|off|status]"), `4004` ("usage: /queue <prompt>"), `4004` ("usage: /steer <prompt>"), `4009`, `4009` ("session busy — /interrupt the current turn before /compress"), `4009` ("session busy — /interrupt the current turn before /retry"), `4009` ("session busy — /interrupt the current turn before /undo"), `4018`, `4018` ("bundle dispatch failed: {exc}"), `4018` ("failed to load bundle: {bundle_key}"), `4018` ("no previous user message to retry"), `4018` ("no user messages to undo"), `4018` ("not a quick/plugin/bundle/skill command: {name}"), `4018` ("retry cannot safely reconstruct or combine attached media"), `5008` ("retry: failed to persist history: {exc}"), `5008` ("undo: {exc}"), `5009` ("compress failed: {exc}"), `5019` ("compute-host slash.compress failed: {exc}"), `5030` ("goals unavailable: {exc}"), `5030` ("loops unavailable: {exc}"), `5030` ("moa unavailable: {exc}")
- **Rebuild notes:** n/a

### `slash.exec`  `id: tui.rpc-slash-exec`
- **Surface:** API
- **Where:** JSON-RPC method `slash.exec` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `slash.exec` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1167`, registered as `@method("slash.exec")`.
- **Inputs / options:** `command`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `output`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("empty command"), `4018` ("skill command: use command.dispatch for {_cmd_key}"), `4018` ("snapshot restore mutates live config/state; use command.dispatch for /snapshot restore"), `5030`, `5030` ("slash worker start failed: {e}")
- **Rebuild notes:** n/a

### `insights.get`  `id: tui.rpc-insights-get`
- **Surface:** API
- **Where:** JSON-RPC method `insights.get` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `insights.get` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1321`, registered as `@method("insights.get")`.
- **Inputs / options:** `days`
- **Outputs / side effects:** `_ok` result keys: `days`, `messages`, `sessions`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5017`
- **Rebuild notes:** n/a

### `rollback.list`  `id: tui.rpc-rollback-list`
- **Surface:** API
- **Where:** JSON-RPC method `rollback.list` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `rollback.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1346`, registered as `@method("rollback.list")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `checkpoints`, `enabled`, `hash`, `message`, `timestamp`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5020`
- **Rebuild notes:** n/a

### `rollback.restore`  `id: tui.rpc-rollback-restore`
- **Surface:** API
- **Where:** JSON-RPC method `rollback.restore` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `rollback.restore` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1376`, registered as `@method("rollback.restore")`.
- **Inputs / options:** `file_path`, `hash`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4009` ("session busy — /interrupt the current turn before full rollback.restore"), `4014` ("hash required"), `5021`
- **Rebuild notes:** n/a

### `rollback.diff`  `id: tui.rpc-rollback-diff`
- **Surface:** API
- **Where:** JSON-RPC method `rollback.diff` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `rollback.diff` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1434`, registered as `@method("rollback.diff")`.
- **Inputs / options:** `hash`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4014` ("hash required"), `5022`
- **Rebuild notes:** n/a

### `browser.manage`  `id: tui.rpc-browser-manage`
- **Surface:** API
- **Where:** JSON-RPC method `browser.manage` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `browser.manage` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1457`, registered as `@method("browser.manage")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `action`
- **Outputs / side effects:** `_ok` result keys: `connected`, `url`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4015` ("unknown action: {action}")
- **Rebuild notes:** n/a

### `plugins.list`  `id: tui.rpc-plugins-list`
- **Surface:** API
- **Where:** JSON-RPC method `plugins.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `plugins.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1474`, registered as `@method("plugins.list")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `enabled`, `name`, `plugins`, `version`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5032`
- **Rebuild notes:** n/a

### `config.show`  `id: tui.rpc-config-show`
- **Surface:** API
- **Where:** JSON-RPC method `config.show` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `config.show` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1496`, registered as `@method("config.show")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `sections`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5030`
- **Rebuild notes:** n/a

### `tools.list`  `id: tui.rpc-tools-list`
- **Surface:** API
- **Where:** JSON-RPC method `tools.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `tools.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1537`, registered as `@method("tools.list")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `toolsets`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5031`
- **Rebuild notes:** n/a

### `tools.show`  `id: tui.rpc-tools-show`
- **Surface:** API
- **Where:** JSON-RPC method `tools.show` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `tools.show` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1568`, registered as `@method("tools.show")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `name`, `sections`, `tools`, `total`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5034`
- **Rebuild notes:** n/a

### `tools.configure`  `id: tui.rpc-tools-configure`
- **Surface:** API
- **Where:** JSON-RPC method `tools.configure` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `tools.configure` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1611`, registered as `@method("tools.configure")`.
- **Inputs / options:** `action`, `names`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `changed`, `enabled_toolsets`, `info`, `missing_servers`, `reset`, `unknown`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4017` ("unknown tools action: {action}"), `4018` ("names required"), `5035`
- **Rebuild notes:** n/a

### `toolsets.list`  `id: tui.rpc-toolsets-list`
- **Surface:** API
- **Where:** JSON-RPC method `toolsets.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `toolsets.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1680`, registered as `@method("toolsets.list")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `toolsets`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5032`
- **Rebuild notes:** n/a

### `agents.list`  `id: tui.rpc-agents-list`
- **Surface:** API
- **Where:** JSON-RPC method `agents.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `agents.list` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1710`, registered as `@method("agents.list")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `command`, `processes`, `session_id`, `status`, `uptime`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5033`
- **Rebuild notes:** n/a

### `cron.manage`  `id: tui.rpc-cron-manage`
- **Surface:** API
- **Where:** JSON-RPC method `cron.manage` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `cron.manage` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1734`, registered as `@method("cron.manage")`.
- **Inputs / options:** `action`, `continuity`, `deliver`, `include_disabled`, `name`, `profile`, `prompt`, `repeat`, `schedule`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4016` ("unknown cron action: {action}"), `4064` ("profile '{profile}' not found"), `5023`
- **Rebuild notes:** n/a

### `learning.frames`  `id: tui.rpc-learning-frames`
- **Surface:** API
- **Where:** JSON-RPC method `learning.frames` on the TUI gateway (called by the TUI).
- **What it does:** Pre-render the learning timeline for the TUI ``/journey`` overlay.
- **How it works:** `methods_tools.py:1821`, registered as `@method("learning.frames")`. Source doc: "Pre-render the learning timeline for the TUI `/journey` overlay. Returns `frames` (reveal 0→1) plus static legend/summary/bucket metadata, so Ink can render and walk the tree locally without round-tripping the gateway. Shares its renderer with the `hermes journey` CLI." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `cols`, `frames`, `rows`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5000` ("learning.frames failed: {exc}")
- **Rebuild notes:** n/a

### `learning.detail`  `id: tui.rpc-learning-detail`
- **Surface:** API
- **Where:** JSON-RPC method `learning.detail` on the TUI gateway (called by the TUI).
- **What it does:** Current content of a journey node, for an edit prefill.
- **How it works:** `methods_tools.py:1845`, registered as `@method("learning.detail")`.
- **Inputs / options:** `id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5000` ("learning.detail failed: {exc}")
- **Rebuild notes:** n/a

### `learning.delete`  `id: tui.rpc-learning-delete`
- **Surface:** API
- **Where:** JSON-RPC method `learning.delete` on the TUI gateway (called by the TUI).
- **What it does:** Delete a journey node — skills are archived (restorable), memories removed.
- **How it works:** `methods_tools.py:1856`, registered as `@method("learning.delete")`.
- **Inputs / options:** `id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5000` ("learning.delete failed: {exc}")
- **Rebuild notes:** n/a

### `learning.edit`  `id: tui.rpc-learning-edit`
- **Surface:** API
- **Where:** JSON-RPC method `learning.edit` on the TUI gateway (called by the TUI).
- **What it does:** Rewrite a journey node's content (SKILL.md or memory chunk).
- **How it works:** `methods_tools.py:1867`, registered as `@method("learning.edit")`.
- **Inputs / options:** `content`, `id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5000` ("learning.edit failed: {exc}")
- **Rebuild notes:** n/a

### `skills.manage`  `id: tui.rpc-skills-manage`
- **Surface:** API
- **Where:** JSON-RPC method `skills.manage` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `skills.manage` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:1878`, registered as `@method("skills.manage")`.
- **Inputs / options:** `action`, `page`, `page_size`, `profile`, `query`
- **Outputs / side effects:** `_ok` result keys: `description`, `info`, `installed`, `name`, `results`, `skills`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4017` ("unknown skills action: {action}"), `4064` ("profile '{profile}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.catalog`  `id: tui.rpc-mcp-catalog`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.catalog` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Bundled MCP catalog with per-profile install/enable state.
- **How it works:** `methods_tools.py:1962`, registered as `@method("mcp.catalog")`. Source doc: "Bundled MCP catalog with per-profile install/enable state. Params: optional `profile` (defaults to the launch profile). Result: `{servers: [{name, description, installed, enabled, requires: [env keys], transport}]}` — the same catalog `hermes mcp` offers, so capability UIs can present the full menu and know which entries need setup (missing requires) before they'll work."
- **Inputs / options:** `profile`
- **Outputs / side effects:** `_ok` result keys: `servers`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4064` ("profile '{profile}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.list`  `id: tui.rpc-mcp-servers-list`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** List a profile's configured MCP servers.
- **How it works:** `methods_tools.py:2034`, registered as `@method("mcp.servers.list")`. Source doc: "List a profile's configured MCP servers. Params: optional `profile`. Result: `{servers: [{name, transport, url, command, args, env (key names only), auth, oauth_tokens_present, enabled, tools}]}`. Reuses `mcp_config._get_mcp_servers` under the home override."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `servers`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5024`
- **Rebuild notes:** n/a

### `mcp.servers.add`  `id: tui.rpc-mcp-servers-add`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.add` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Add/save an MCP server to a profile's config.yaml.
- **How it works:** `methods_tools.py:2064`, registered as `@method("mcp.servers.add")`. Source doc: "Add/save an MCP server to a profile's config.yaml. Params: optional `profile`, `name` (required), and EITHER: - `preset` (a catalog preset id) → applied via `_apply_mcp_preset`, or - `config` (an mcp_servers entry dict: url/command/args/env/headers/ auth/tools) → saved via `_save_mcp_server`. If `bearer_token` is given (header auth), it is written to the profile's .env via `_save_bearer_auth_token` and only the safe `Authorization` header template is persisted in config.yaml. Result: `{ok: true, name, server: <summary>}`. Duplicate names error."
- **Inputs / options:** `bearer_token`, `config`, `name`, `preset`
- **Outputs / side effects:** `_ok` result keys: `name`, `ok`, `server`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("server '{name}' rejected: suspicious command/args configuration"), `4063` ("config must specify a 'url' (http) or 'command' (stdio), or a valid 'preset'"), `4063` ("name required"), `4090` ("server '{name}' already exists"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.set_api_key`  `id: tui.rpc-mcp-servers-set-api-key`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.set_api_key` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Store a required API key / credential for a server in a profile.
- **How it works:** `methods_tools.py:2137`, registered as `@method("mcp.servers.set_api_key")`. Source doc: "Store a required API key / credential for a server in a profile. Params: optional `profile`, `name` (required), `value` (required, the secret), and optional `env_var` (defaults to the server's canonical `MCP_<NAME>_API_KEY` key). The secret is written to that profile's .env via `save_env_value`; the config.yaml entry is updated to reference it — a header template `Authorization: Bearer ${ENV}` for http servers, or an `env: {VAR: "${ENV}"}` reference for stdio servers — matching how `cmd_mcp_configure` / `_save_bearer_auth_token` wire secrets. Result: `{ok: true, name, env_"
- **Inputs / options:** `env_var`, `name`, `value`
- **Outputs / side effects:** `_ok` result keys: `env_var`, `name`, `ok`, `server`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("malformed server config"), `4063` ("name required"), `4063` ("value is not a valid credential"), `4063` ("value required"), `4064` ("server '{name}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.test`  `id: tui.rpc-mcp-servers-test`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.test` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Probe a profile's MCP server: connect, list tools, disconnect.
- **How it works:** `methods_tools.py:2217`, registered as `@method("mcp.servers.test")`. Source doc: "Probe a profile's MCP server: connect, list tools, disconnect. Params: optional `profile`, `name` (required). Result on success: `{ok: true, tools: [{name, description}], prompts, resources, oauth_tokens_present}`. On failure: `{ok: false, error, tools: [], oauth_needed}`. Reuses `mcp_config._probe_single_server` + `_oauth_tokens_present` — same logic as the /test dashboard route. Runs on the RPC thread pool (see _LONG_HANDLERS): a cold stdio `npx` spawn can block for many seconds." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `name`
- **Outputs / side effects:** `_ok` result keys: `description`, `error`, `name`, `oauth_needed`, `oauth_tokens_present`, `ok`, `prompts`, `resources`, `tools`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("server '{name}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.remove`  `id: tui.rpc-mcp-servers-remove`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.remove` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Remove a server from a profile's config.yaml.
- **How it works:** `methods_tools.py:2296`, registered as `@method("mcp.servers.remove")`. Source doc: "Remove a server from a profile's config.yaml. Params: optional `profile`, `name` (required). Result: `{ok: true, removed: bool}`. Reuses `mcp_config._remove_mcp_server`."
- **Inputs / options:** `name`
- **Outputs / side effects:** `_ok` result keys: `ok`, `removed`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("server '{name}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.oauth.start`  `id: tui.rpc-mcp-servers-oauth-start`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.oauth.start` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Begin a session-backed OAuth flow for an MCP server in a profile.
- **How it works:** `methods_tools.py:2322`, registered as `@method("mcp.servers.oauth.start")`. Source doc: "Begin a session-backed OAuth flow for an MCP server in a profile. Params: optional `profile`, `name` (required), optional `client_redirect_uri`. Result: `{ok: true, session_id, auth_url, flow: "pkce"}`. The client (desktop) opens `auth_url` in the native browser (`window.hermesDesktop.openExternal`) and then polls `mcp.servers.oauth.poll` with the returned `session_id` until `status == "approved"`. This mirrors the provider-OAuth start/poll model (`/api/providers/oauth/{id}/start` + `/poll`): a background worker drives the SAME interactive MCP OAuth machinery `hermes mcp" Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `client_redirect_uri`, `name`
- **Outputs / side effects:** `_ok` result keys: `auth_url`, `flow`, `ok`, `session_id`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001`, `4001` ("stdio servers authenticate via env keys, not OAuth"), `4001` ("this server uses header/API-key auth, not OAuth"), `4063` ("name required"), `4064` ("server '{name}' not found"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.oauth.poll`  `id: tui.rpc-mcp-servers-oauth-poll`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.oauth.poll` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Poll a session-backed MCP OAuth flow.
- **How it works:** `methods_tools.py:2397`, registered as `@method("mcp.servers.oauth.poll")`. Source doc: "Poll a session-backed MCP OAuth flow. Params: optional `profile`, `name` (required), `session_id` (required, from `mcp.servers.oauth.start`). Result: `{ok: true, status: "pending"|"approved"|"error", error_message?, auth_url?, tools?}`. On `approved` the OAuth tokens have been persisted for that server in that profile (verified via `_oauth_tokens_present` inside the worker). The profile scope is applied here too so a same-profile reconnect / token read resolves correctly." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `name`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `ok`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4063` ("session_id required"), `5024`
- **Rebuild notes:** n/a

### `mcp.servers.oauth.callback`  `id: tui.rpc-mcp-servers-oauth-callback`
- **Surface:** API
- **Where:** JSON-RPC method `mcp.servers.oauth.callback` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Relay a client-captured OAuth redirect into a running MCP OAuth flow.
- **How it works:** `methods_tools.py:2430`, registered as `@method("mcp.servers.oauth.callback")`. Source doc: "Relay a client-captured OAuth redirect into a running MCP OAuth flow. Remote-backend companion to `mcp.servers.oauth.start` with `client_redirect_uri`: the desktop app's local loopback listener caught the provider redirect on the user's machine and forwards its query params here. Params: optional `profile`, `name` (required), `session_id` (required), `code`, `state`, `error`. Result: `{ok: true}` once the callback is accepted (state verified inside the flow bridge), or `{ok: false, error_message}` on mismatch/expiry." Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `code`, `error`, `name`, `session_id`, `state`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4063` ("session_id required"), `5024`
- **Rebuild notes:** n/a

### `skills.reload`  `id: tui.rpc-skills-reload`
- **Surface:** API
- **Where:** JSON-RPC method `skills.reload` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `skills.reload` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:2468`, registered as `@method("skills.reload")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `output`, `result`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5025`
- **Rebuild notes:** n/a

### `plugins.manage`  `id: tui.rpc-plugins-manage`
- **Surface:** API
- **Where:** JSON-RPC method `plugins.manage` on the TUI gateway (called by the TUI).
- **What it does:** List installed plugins with activation state, or toggle one on/off.
- **How it works:** `methods_tools.py:2493`, registered as `@method("plugins.manage")`. Source doc: "List installed plugins with activation state, or toggle one on/off. Backs the TUI Plugins Hub. Uses the same disk-discovery + enable/disable primitives as `hermes plugins` / the dashboard, so the three surfaces agree on what's installed and what's enabled. Actions: - `list` → {"plugins": [{name, key, version, description, source, status, portable}], "user_count": N, "bundled_count": M} - `toggle` → flip `key` (or `name`) based on `enable` (bool). Returns the refreshed row plus {"ok", "unchanged"}. - `install` → git-clone into `~/.hermes/plugins/` (non-interactive). Params: `id" Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `action`, `enable`, `force`, `identifier`, `key`, `name`, `repo`
- **Outputs / side effects:** `_ok` result keys: `bundled_count`, `name`, `ok`, `plugin`, `plugins`, `unchanged`, `user_count`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4017` ("unknown plugins action: {action}"), `4019` ("plugins.install requires 'identifier' or 'repo'"), `4019` ("plugins.toggle requires a 'key' or 'name'"), `5026`
- **Rebuild notes:** n/a

### `shell.exec`  `id: tui.rpc-shell-exec`
- **Surface:** API
- **Where:** JSON-RPC method `shell.exec` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `shell.exec` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_tools.py:2627`, registered as `@method("shell.exec")`.
- **Inputs / options:** `command`
- **Outputs / side effects:** `_ok` result keys: `code`, `stderr`, `stdout`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("empty command"), `4005` ("blocked (hardline): {hardline_desc}. Use the agent for dangerous commands."), `4005` ("blocked: {desc}. Use the agent for dangerous commands."), `5001` ("shell.exec unavailable: approval safety module not importable"), `5002` ("command timed out (30s)"), `5003`
- **Rebuild notes:** n/a

### `tui_gateway/methods_config.py` — config reads, projects, setup, diagnostics  `id: tui.rpcgroup-methods-config`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_config.py` (8 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_config.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `projects.discover_repos`  `id: tui.rpc-projects-discover-repos`
- **Surface:** API
- **Where:** JSON-RPC method `projects.discover_repos` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Repos for the desktop overview: scanned-from-disk (cached) ∪ session-derived.
- **How it works:** `methods_config.py:21`, registered as `@method("projects.discover_repos")`.
- **Inputs / options:** `scan`
- **Outputs / side effects:** `_ok` result keys: `discovery_policy`, `repos`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5061`
- **Rebuild notes:** n/a

### `projects.record_repos`  `id: tui.rpc-projects-record-repos`
- **Surface:** API
- **Where:** JSON-RPC method `projects.record_repos` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Persist git repo roots found by the client's filesystem scan, then return the merged repo list.
- **How it works:** `methods_config.py:54`, registered as `@method("projects.record_repos")`. Source doc: "Persist git repo roots found by the client's filesystem scan, then return the merged repo list. The native crawl runs on the desktop (local fs); this caches the result so later reads are instant instead of re-walking disk."
- **Inputs / options:** `discovery_policy`, `repos`
- **Outputs / side effects:** `_ok` result keys: `accepted`, `discovery_policy`, `repos`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5061`
- **Rebuild notes:** n/a

### `projects.tree`  `id: tui.rpc-projects-tree`
- **Surface:** API
- **Where:** JSON-RPC method `projects.tree` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Authoritative project overview: project -> repo -> lane structure with counts + a few preview sessions per project, plus the flat set of session ids claimed by any project (so the desktop excludes them from flat Recents).
- **How it works:** `methods_config.py:119`, registered as `@method("projects.tree")`. Source doc: "Authoritative project overview: project -> repo -> lane structure with counts + a few preview sessions per project, plus the flat set of session ids claimed by any project (so the desktop excludes them from flat Recents). Lanes carry no session rows here; drill-in uses `projects.project_sessions`."
- **Inputs / options:** `preview_limit`, `session_limit`
- **Outputs / side effects:** `_ok` result keys: `active_id`, `projects`, `scoped_session_ids`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5061`
- **Rebuild notes:** n/a

### `projects.project_sessions`  `id: tui.rpc-projects-project-sessions`
- **Surface:** API
- **Where:** JSON-RPC method `projects.project_sessions` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Fully hydrated lanes (repo -> lane -> session rows) for one project, built from the same authoritative grouping as ``projects.tree`` so ids and membership match exactly.
- **How it works:** `methods_config.py:153`, registered as `@method("projects.project_sessions")`. Source doc: "Fully hydrated lanes (repo -> lane -> session rows) for one project, built from the same authoritative grouping as `projects.tree` so ids and membership match exactly. Used when the user enters a project."
- **Inputs / options:** `project_id`, `session_limit`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5061`, `5063` ("project_id required")
- **Rebuild notes:** n/a

### `config.get`  `id: tui.rpc-config-get`
- **Surface:** API
- **Where:** JSON-RPC method `config.get` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `config.get` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_config.py:183`, registered as `@method("config.get")`.
- **Inputs / options:** `cwd`, `key`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `branch`, `config`, `cwd`, `display`, `home`, `mcp_rev`, `model`, `mtime`, `prompt`, `provider`, `providers`, `tool_progress`, `value`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4002` ("unknown config key: {key}"), `5001`, `5013`
- **Rebuild notes:** n/a

### `setup.status`  `id: tui.rpc-setup-status`
- **Surface:** API
- **Where:** JSON-RPC method `setup.status` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `setup.status` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_config.py:381`, registered as `@method("setup.status")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `provider_configured`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5016`
- **Rebuild notes:** n/a

### `setup.runtime_check`  `id: tui.rpc-setup-runtime-check`
- **Surface:** API
- **Where:** JSON-RPC method `setup.runtime_check` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Strict provider check: does the configured/default model actually resolve to a usable runtime? Unlike setup.status (which returns True if ANY provider auth state is discoverable, including indirect fallbacks like ``gh auth token`` for Copilot), this runs the same resolve_runtime_provider() call the agent uses on session creation.
- **How it works:** `methods_config.py:391`, registered as `@method("setup.runtime_check")`. Source doc: "Strict provider check: does the configured/default model actually resolve to a usable runtime? Unlike setup.status (which returns True if ANY provider auth state is discoverable, including indirect fallbacks like `gh auth token` for Copilot), this runs the same resolve_runtime_provider() call the agent uses on session creation. It returns ok=False with the auth error message when the user's configured model cannot actually be served, so UIs can surface onboarding before the user submits a doomed prompt."
- **Inputs / options:** `provider`
- **Outputs / side effects:** `_ok` result keys: `error`, `model`, `ok`, `provider`, `source`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `diagnostics.share_nous`  `id: tui.rpc-diagnostics-share-nous`
- **Surface:** API
- **Where:** JSON-RPC method `diagnostics.share_nous` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Upload a redacted debug bundle to Nous-internal diagnostics storage.
- **How it works:** `methods_config.py:466`, registered as `@method("diagnostics.share_nous")`. Source doc: "Upload a redacted debug bundle to Nous-internal diagnostics storage. Desktop's "Send Diagnostics" action (error card / diagnostics UI). Same collection + force-redaction pipeline as `hermes debug share --nous` (collect_share_bundle → build_nous_bundle → share_to_nous); redaction is NOT client-controllable — this handler always redacts. Params (all optional): - `error_context`: short client-supplied text describing the failure that prompted the report (the error card's layer/code/message blob). Redacted server-side and attached as `error-context.txt`. - `extra_files`: {label → text} of "
- **Inputs / options:** `error_context`, `extra_files`, `log_lines`
- **Outputs / side effects:** `_ok` result keys: `error`, `expires_at`, `ok`, `upload_id`, `view_url`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `tui_gateway/methods_complete.py` — completions and model options  `id: tui.rpcgroup-methods-complete`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_complete.py` (6 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_complete.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `paste.collapse`  `id: tui.rpc-paste-collapse`
- **Surface:** API
- **Where:** JSON-RPC method `paste.collapse` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `paste.collapse` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_complete.py:15`, registered as `@method("paste.collapse")`.
- **Inputs / options:** `text`
- **Outputs / side effects:** `_ok` result keys: `lines`, `path`, `placeholder`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4004` ("empty paste")
- **Rebuild notes:** n/a

### `complete.path`  `id: tui.rpc-complete-path`
- **Surface:** API
- **Where:** JSON-RPC method `complete.path` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `complete.path` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_complete.py:42`, registered as `@method("complete.path")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `word`
- **Outputs / side effects:** `_ok` result keys: `items`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5021`
- **Rebuild notes:** n/a

### `complete.slash`  `id: tui.rpc-complete-slash`
- **Surface:** API
- **Where:** JSON-RPC method `complete.slash` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `complete.slash` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_complete.py:331`, registered as `@method("complete.slash")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `text`
- **Outputs / side effects:** `_ok` result keys: `items`, `replace_from`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5020`
- **Rebuild notes:** n/a

### `model.options`  `id: tui.rpc-model-options`
- **Surface:** API
- **Where:** JSON-RPC method `model.options` on the TUI gateway (called by the TUI).
- **What it does:** Handler for `model.options` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_complete.py:470`, registered as `@method("model.options")`. Runs on the RPC thread pool (`_LONG_HANDLERS`).
- **Inputs / options:** `explicit_only`, `include_unconfigured`, `refresh`, `session_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5033`
- **Rebuild notes:** n/a

### `model.save_key`  `id: tui.rpc-model-save-key`
- **Surface:** API
- **Where:** JSON-RPC method `model.save_key` on the TUI gateway (called by the TUI).
- **What it does:** Save an API key for a provider, then return its refreshed model list.
- **How it works:** `methods_complete.py:493`, registered as `@method("model.save_key")`. Source doc: "Save an API key for a provider, then return its refreshed model list. Params: slug: provider slug (e.g. "deepseek", "xai") api_key: the key value to save Returns the provider dict with models populated (same shape as model.options entries) on success."
- **Inputs / options:** `api_key`, `session_id`, `slug`
- **Outputs / side effects:** `_ok` result keys: `provider`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("slug and api_key are required"), `4002` ("unknown provider: {slug}"), `4003` ("{pconfig.name} uses {pconfig.auth_type} auth — "), `4004` ("no env var defined for {pconfig.name}"), `4006` ("managed install — credentials are read-only"), `5034`
- **Rebuild notes:** n/a

### `model.disconnect`  `id: tui.rpc-model-disconnect`
- **Surface:** API
- **Where:** JSON-RPC method `model.disconnect` on the TUI gateway (called by the TUI).
- **What it does:** Remove credentials for a provider.
- **How it works:** `methods_complete.py:573`, registered as `@method("model.disconnect")`. Source doc: "Remove credentials for a provider. Params: slug: provider slug (e.g. "deepseek", "xai") Returns success status and the provider's slug."
- **Inputs / options:** `slug`
- **Outputs / side effects:** `_ok` result keys: `disconnected`, `name`, `slug`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4001` ("slug is required"), `4005` ("no credentials found for {slug}"), `5035`
- **Rebuild notes:** n/a

### `tui_gateway/methods_profiles.py` — agent profiles  `id: tui.rpcgroup-methods-profiles`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_profiles.py` (6 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_profiles.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `profiles.list`  `id: tui.rpc-profiles-list`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** List Hermes profiles (name, path, model, description, skill count).
- **How it works:** `methods_profiles.py:23`, registered as `@method("profiles.list")`. Source doc: "List Hermes profiles (name, path, model, description, skill count). `include_sessions` (default true) additionally reports each profile's most recent conversation as `last_session` so a roster UI can paint per-agent previews without N follow-up calls. NOTE: helpers must be nested — install() rebinds this handler's __globals__ onto server.py, so module-level names here are invisible."
- **Inputs / options:** `include_sessions`
- **Outputs / side effects:** `_ok` result keys: `bot_mode_protocol`, `profiles`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5061`
- **Rebuild notes:** n/a

### `profiles.create`  `id: tui.rpc-profiles-create`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.create` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Create a profile — the ws twin of POST /api/profiles.
- **How it works:** `methods_profiles.py:340`, registered as `@method("profiles.create")`. Source doc: "Create a profile — the ws twin of POST /api/profiles. Params: `name` (required, lowercase slug), `description`, `clone_from` (source profile; omitted = fresh profile with bundled skills), `clone_all`, `no_skills`, `soul` (SOUL.md content), `model` + `provider` (optional model pin, best-effort), and `mirror_credentials` (default true) — copy the launch profile's `.env` and `auth.json` into the new profile, and inherit its model.provider/model.default when no explicit pin is given. Credential mirroring exists because `create_profile()` deliberately seeds a comment-only `"
- **Inputs / options:** `clone_all`, `clone_from`, `description`, `mirror_credentials`, `model`, `name`, `no_skills`, `provider`, `share_auth`, `soul`
- **Outputs / side effects:** `_ok` result keys: `mirrored`, `model_set`, `name`, `ok`, `path`, `soul_written`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4061` ("name required"), `4062`, `5062`
- **Rebuild notes:** n/a

### `profiles.describe`  `id: tui.rpc-profiles-describe`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.describe` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Full configuration snapshot of one profile, for an editor UI.
- **How it works:** `methods_profiles.py:579`, registered as `@method("profiles.describe")`. Source doc: "Full configuration snapshot of one profile, for an editor UI. Params: `name` (required). Result: `{name, description, soul, model: {provider, default}, skills: [{name, enabled}], toolsets: [{name, description, tool_count, enabled}]}` Skill enablement mirrors the disabled-list model (installed = enabled unless in `skills.disabled`). Toolset enablement reports the profile's `tools.enabled_toolsets` pin, or every toolset enabled when unpinned. All reads are scoped to the profile via the HERMES_HOME override."
- **Inputs / options:** `name`
- **Outputs / side effects:** `_ok` result keys: `default`, `description`, `mcp_servers`, `model`, `name`, `provider`, `skills`, `soul`, `toolsets`, `toolsets_pinned`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("profile '{name}' not found"), `5063`
- **Rebuild notes:** n/a

### `profiles.configure`  `id: tui.rpc-profiles-configure`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.configure` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Apply configuration changes to a profile (editor Save).
- **How it works:** `methods_profiles.py:750`, registered as `@method("profiles.configure")`. Source doc: "Apply configuration changes to a profile (editor Save). Params: `name` (required) plus any of: `description` (str), `soul` (str, full SOUL.md replacement), `model` + `provider` (both required together), `disabled_skills` (list[str], replace semantics), `enabled_toolsets` (list[str], replace semantics; empty list clears the pin so every toolset is enabled again), and `ui_meta_expected_revisions` (dict[str, int], optional compare-and-swap preconditions for keys supplied in `ui_meta`). Each section is applied independently and best-effort; the result reports per-section success "
- **Inputs / options:** `confirm_expensive_model`, `description`, `disabled_skills`, `enabled_mcp_servers`, `enabled_toolsets`, `model`, `name`, `provider`, `soul`, `ui_meta`, `ui_meta_expected_revisions`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("profile '{name}' not found"), `5064`
- **Rebuild notes:** n/a

### `profiles.set_asset`  `id: tui.rpc-profiles-set-asset`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.set_asset` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Store a small binary asset (e.g.
- **How it works:** `methods_profiles.py:1022`, registered as `@method("profiles.set_asset")`. Source doc: "Store a small binary asset (e.g. avatar image) in a profile's dir. Params: `name` (profile), `asset` (currently only `"avatar"`), `data` (data URL or raw base64; PNG/JPEG/WebP; decoded size capped at 2MB), or `clear: true` to delete. Written atomically as `assets/<asset>.<ext>` inside the profile directory — server-side, so every client machine sees the same image via `profiles.get_asset`. Result: `{ok, asset, size}` (`size` 0 on clear)."
- **Inputs / options:** `asset`, `clear`, `data`, `name`
- **Outputs / side effects:** `_ok` result keys: `asset`, `ok`, `removed`, `size`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("profile '{name}' not found"), `4066` ("unknown asset '{asset}' (supported: avatar)"), `4067` ("data required (data URL or base64)"), `4068` ("data is not valid base64"), `4069` ("asset too large ({len(blob)} bytes; max 2MB)"), `4070` ("unsupported image format (PNG/JPEG/WebP only)"), `5065`
- **Rebuild notes:** n/a

### `profiles.get_asset`  `id: tui.rpc-profiles-get-asset`
- **Surface:** API
- **Where:** JSON-RPC method `profiles.get_asset` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Fetch a profile asset as a data URL.
- **How it works:** `methods_profiles.py:1108`, registered as `@method("profiles.get_asset")`. Source doc: "Fetch a profile asset as a data URL. Params: `name` (profile), `asset` (default `"avatar"`). Result: `{found, data?, mime?, size?}` — `found: false` (not an error) when the asset doesn't exist, so roster UIs can probe cheaply."
- **Inputs / options:** `asset`, `name`
- **Outputs / side effects:** `_ok` result keys: `data`, `found`, `mime`, `size`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4063` ("name required"), `4064` ("profile '{name}' not found"), `5066`
- **Rebuild notes:** n/a

### `tui_gateway/methods_groups.py` — hosted rooms (groups)  `id: tui.rpcgroup-methods-groups`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_groups.py` (18 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_groups.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `groups.capabilities`  `id: tui.rpc-groups-capabilities`
- **Surface:** API
- **Where:** JSON-RPC method `groups.capabilities` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Describe the hosted-room protocol implemented by this gateway.
- **How it works:** `methods_groups.py:197`, registered as `@method("groups.capabilities")`.
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `authority_gateway_id`, `driver`, `features`, `max_log_limit`, `methods`, `persistent_process`, `protocol_version`, `room_link`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `groups.peer.invite`  `id: tui.rpc-groups-peer-invite`
- **Surface:** API
- **Where:** JSON-RPC method `groups.peer.invite` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Mint one target-issued room/profile grant for a prospective home.
- **How it works:** `methods_groups.py:290`, registered as `@method("groups.peer.invite")`.
- **Inputs / options:** `authority_epoch`, `authority_gateway_id`, `grant_id`, `home_install_id`, `member_id`, `room_id`, `ttl_seconds`
- **Outputs / side effects:** `_ok` result keys: `catalog`, `endpoint`, `grant`, `target_profile`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4120`
- **Rebuild notes:** n/a

### `groups.peer.revoke`  `id: tui.rpc-groups-peer-revoke`
- **Surface:** API
- **Where:** JSON-RPC method `groups.peer.revoke` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Revoke one target-issued grant using its exact profile scope.
- **How it works:** `methods_groups.py:355`, registered as `@method("groups.peer.revoke")`.
- **Inputs / options:** `grant`
- **Outputs / side effects:** `_ok` result keys: `revoked`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4122`
- **Rebuild notes:** n/a

### `groups.peer.register`  `id: tui.rpc-groups-peer-register`
- **Surface:** API
- **Where:** JSON-RPC method `groups.peer.register` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Register and probe one scoped target route on the room home.
- **How it works:** `methods_groups.py:386`, registered as `@method("groups.peer.register")`.
- **Inputs / options:** `cancellation_scope_id`, `catalog`, `grant`, `member_id`, `room_id`, `target_profile`, `target_url`, `trace_id`
- **Outputs / side effects:** `_ok` result keys: `mode`, `registered`, `target_install_id`, `target_profile`, `transport_security`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4121` ("hosted room driver is unavailable"), `5120`
- **Rebuild notes:** n/a

### `groups.list`  `id: tui.rpc-groups-list`
- **Surface:** API
- **Where:** JSON-RPC method `groups.list` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** List rooms hosted by this gateway.
- **How it works:** `methods_groups.py:479`, registered as `@method("groups.list")`.
- **Inputs / options:** `include_disbanded`, `limit`, `offset`
- **Outputs / side effects:** `_ok` result keys: `next_offset`, `rooms`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5110`
- **Rebuild notes:** n/a

### `groups.create`  `id: tui.rpc-groups-create`
- **Surface:** API
- **Where:** JSON-RPC method `groups.create` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Create a hosted room idempotently.
- **How it works:** `methods_groups.py:509`, registered as `@method("groups.create")`. Source doc: "Create a hosted room idempotently. Required params: `room_id`, `name`, and `members`. Authority is derived from this gateway's stable install identity, never from the client."
- **Inputs / options:** `members`, `name`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `room`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4110`, `4123`, `5111`
- **Rebuild notes:** n/a

### `groups.state`  `id: tui.rpc-groups-state`
- **Surface:** API
- **Where:** JSON-RPC method `groups.state` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Return one hosted room's replay cursor and fenced authority state.
- **How it works:** `methods_groups.py:535`, registered as `@method("groups.state")`.
- **Inputs / options:** `include_disbanded`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `driver_status`, `room`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4114`, `5115`
- **Rebuild notes:** n/a

### `groups.send`  `id: tui.rpc-groups-send`
- **Surface:** API
- **Where:** JSON-RPC method `groups.send` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Append one typed event to a hosted room idempotently.
- **How it works:** `methods_groups.py:565`, registered as `@method("groups.send")`. Source doc: "Append one typed event to a hosted room idempotently. Required params: `room_id`, `event_id`, and object `payload`. Only inert `message.user` events are accepted through this client-facing method. The actor is server-owned rather than trusted from params. Admission is durable; no Bot turn is started by this slice."
- **Inputs / options:** `event_id`, `payload`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `accepted`, `client_event_id`, `driver_started`, `event`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4111`, `4123`, `5112`
- **Rebuild notes:** n/a

### `groups.rename`  `id: tui.rpc-groups-rename`
- **Surface:** API
- **Where:** JSON-RPC method `groups.rename` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Rename one hosted room atomically with its replay event.
- **How it works:** `methods_groups.py:602`, registered as `@method("groups.rename")`.
- **Inputs / options:** `event_id`, `name`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `room`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4117`, `5117`
- **Rebuild notes:** n/a

### `groups.disband`  `id: tui.rpc-groups-disband`
- **Surface:** API
- **Where:** JSON-RPC method `groups.disband` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Permanently tombstone a hosted room id.
- **How it works:** `methods_groups.py:622`, registered as `@method("groups.disband")`.
- **Inputs / options:** `cancel_id`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `tombstone`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4113`, `4123`, `5114`
- **Rebuild notes:** n/a

### `groups.stop`  `id: tui.rpc-groups-stop`
- **Surface:** API
- **Where:** JSON-RPC method `groups.stop` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Durably cancel queued or running work for one hosted room.
- **How it works:** `methods_groups.py:685`, registered as `@method("groups.stop")`.
- **Inputs / options:** `cancel_id`, `room_id`
- **Outputs / side effects:** `_ok` result keys: `cancelled`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4115` ("hosted room driver is unavailable"), `5116`
- **Rebuild notes:** n/a

### `groups.approve`  `id: tui.rpc-groups-approve`
- **Surface:** API
- **Where:** JSON-RPC method `groups.approve` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Resolve one exact approval requested by a local or peer room member.
- **How it works:** `methods_groups.py:702`, registered as `@method("groups.approve")`.
- **Inputs / options:** `choice`, `execution_generation`, `member_id`, `request_id`, `room_id`, `task_id`
- **Outputs / side effects:** `_ok` result keys: `approved`, `result`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4115` ("hosted room driver is unavailable"), `5119`
- **Rebuild notes:** n/a

### `groups.retry`  `id: tui.rpc-groups-retry`
- **Surface:** API
- **Where:** JSON-RPC method `groups.retry` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Retry one indeterminate room task after explicit user confirmation.
- **How it works:** `methods_groups.py:723`, registered as `@method("groups.retry")`.
- **Inputs / options:** `room_id`, `task_id`
- **Outputs / side effects:** `_ok` result keys: `retried`, `task`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4115` ("hosted room driver is unavailable"), `5118`
- **Rebuild notes:** n/a

### `groups.log`  `id: tui.rpc-groups-log`
- **Surface:** API
- **Where:** JSON-RPC method `groups.log` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Return a monotonic room-log delta after ``since_seq``.
- **How it works:** `methods_groups.py:753`, registered as `@method("groups.log")`.
- **Inputs / options:** `include_disbanded`, `limit`, `room_id`, `since_seq`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4112`, `5113`
- **Rebuild notes:** n/a

### `groups.replicate`  `id: tui.rpc-groups-replicate`
- **Surface:** API
- **Where:** JSON-RPC method `groups.replicate` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Persist one authority-stamped replay page into the local replica store.
- **How it works:** `methods_groups.py:774`, registered as `@method("groups.replicate")`. Source doc: "Persist one authority-stamped replay page into the local replica store. `page` is the verbatim `groups.log` result read from the room's authority gateway; ingest is idempotent and refuses sequence gaps and authority-epoch regressions."
- **Inputs / options:** `members`, `page`, `room_id`, `room_name`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4116`, `5116`
- **Rebuild notes:** n/a

### `groups.replica_state`  `id: tui.rpc-groups-replica-state`
- **Surface:** API
- **Where:** JSON-RPC method `groups.replica_state` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Report the local replica's coverage and authority lineage.
- **How it works:** `methods_groups.py:800`, registered as `@method("groups.replica_state")`.
- **Inputs / options:** `room_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4117`, `5117`
- **Rebuild notes:** n/a

### `groups.promote`  `id: tui.rpc-groups-promote`
- **Surface:** API
- **Where:** JSON-RPC method `groups.promote` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Continue a replicated room on THIS gateway at ``epoch + 1``.
- **How it works:** `methods_groups.py:814`, registered as `@method("groups.promote")`. Source doc: "Continue a replicated room on THIS gateway at `epoch + 1`. Requires `confirm: true` — the caller asserts the previous authority can no longer commit (explicit user action; a lease/quorum driver later)."
- **Inputs / options:** `confirm`, `reason`, `room_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4118`, `4118` ("promotion requires confirm=true acknowledging the previous "), `5118`
- **Rebuild notes:** n/a

### `groups.demote`  `id: tui.rpc-groups-demote`
- **Surface:** API
- **Where:** JSON-RPC method `groups.demote` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Fence this gateway's stale room authority against a proven newer epoch.
- **How it works:** `methods_groups.py:846`, registered as `@method("groups.demote")`.
- **Inputs / options:** `observed_epoch`, `observed_gateway_id`, `room_id`
- **Outputs / side effects:** returns `_ok` with no literal result keys at the call site (result built dynamically) or a bare acknowledgement
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4119`, `5119`
- **Rebuild notes:** n/a

### `tui_gateway/methods_images.py` — image generation  `id: tui.rpcgroup-methods-images`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_images.py` (1 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_images.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `image.generate`  `id: tui.rpc-image-generate`
- **Surface:** API
- **Where:** JSON-RPC method `image.generate` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Generate an image with the configured backend.
- **How it works:** `methods_images.py:23`, registered as `@method("image.generate")`. Source doc: "Generate an image with the configured backend. Params: `prompt` (required unless `probe`), `aspect_ratio` (landscape|square|portrait), `probe` (return availability only), `max_bytes` (cap on the returned data URL payload, default 8MB). Result: `{available, success, image, image_data, error}` where `image` is the backend's URL/path and `image_data` is a data URL of the downloaded bytes (omitted when the download fails — callers should fall back to `image`)."
- **Inputs / options:** `aspect_ratio`, `max_bytes`, `probe`, `prompt`
- **Outputs / side effects:** `_ok` result keys: `available`, `error`, `success`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4071` ("prompt required"), `5071`
- **Rebuild notes:** n/a

### `tui_gateway/methods_bot_relay.py` — cross-gateway bot relay  `id: tui.rpcgroup-methods-bot-relay`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_bot_relay.py` (4 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_bot_relay.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `bot_relay.roster.sync`  `id: tui.rpc-bot-relay-roster-sync`
- **Surface:** API
- **Where:** JSON-RPC method `bot_relay.roster.sync` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Replace this gateway's view of agents on OTHER connections.
- **How it works:** `methods_bot_relay.py:34`, registered as `@method("bot_relay.roster.sync")`. Source doc: "Replace this gateway's view of agents on OTHER connections. Params: `agents` — list of rows `{profile, handle, connection_id, connection_label?, title?, description?}`. Rows failing validation are dropped, not fatal. Result: `{count}` (accepted rows)."
- **Inputs / options:** `agents`
- **Outputs / side effects:** `_ok` result keys: `count`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5090`
- **Rebuild notes:** n/a

### `bot_relay.outbox.drain`  `id: tui.rpc-bot-relay-outbox-drain`
- **Surface:** API
- **Where:** JSON-RPC method `bot_relay.outbox.drain` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Claim every pending cross-connection envelope queued on this gateway.
- **How it works:** `methods_bot_relay.py:56`, registered as `@method("bot_relay.outbox.drain")`. Source doc: "Claim every pending cross-connection envelope queued on this gateway. Claimed envelopes move to `claimed/` atomically, so concurrent drains (two Desktop windows) can't double-deliver. Result: `{envelopes}`."
- **Inputs / options:** no `params` keys read
- **Outputs / side effects:** `_ok` result keys: `envelopes`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `5091`
- **Rebuild notes:** n/a

### `bot_relay.deliver`  `id: tui.rpc-bot-relay-deliver`
- **Surface:** API
- **Where:** JSON-RPC method `bot_relay.deliver` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Deliver a relayed DM into a profile's Bot Chat ON THIS GATEWAY.
- **How it works:** `methods_bot_relay.py:76`, registered as `@method("bot_relay.deliver")`. Source doc: "Deliver a relayed DM into a profile's Bot Chat ON THIS GATEWAY. Params: `profile` (target on this install), `message` (already attribution-prefixed by the sender gateway). Runs the same one-turn `hermes -p <profile> chat -c "Bot Chat"` transport local DMs use and returns `{reply}` — the target agent's response text. Blocking by design (the Desktop calls it from its relay worker, off any UI path; the RPC pool keeps it off the WS reader thread)."
- **Inputs / options:** `message`, `profile`
- **Outputs / side effects:** `_ok` result keys: `reply`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4090` ("profile and message required"), `4091` ("message too long"), `4092` ("no profile '{profile}' on this gateway"), `5092` ("delivery turn failed: {detail or proc.returncode}"), `5093` ("delivery turn timed out"), `5094`, `5096`
- **Rebuild notes:** n/a

### `bot_relay.reply`  `id: tui.rpc-bot-relay-reply`
- **Surface:** API
- **Where:** JSON-RPC method `bot_relay.reply` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Write a relayed reply (or delivery error) for a sender-side waiter.
- **How it works:** `methods_bot_relay.py:182`, registered as `@method("bot_relay.reply")`. Source doc: "Write a relayed reply (or delivery error) for a sender-side waiter. Params: `id` (envelope id), `reply` and/or `error`, optional `reason` (typed failure code, see `tools.bot_failure_reasons`)."
- **Inputs / options:** `error`, `id`, `reason`, `reply`
- **Outputs / side effects:** `_ok` result keys: `ok`
- **Config / env:** n/a
- **Edge cases / guards:** `_err` codes: `4093` ("id required"), `4094`, `5095`
- **Rebuild notes:** n/a

### `tui_gateway/methods_browser_control.py` — browser controller broker  `id: tui.rpcgroup-methods-browser-control`
- **Surface:** API
- **Where:** JSON-RPC methods served from `tui_gateway/methods_browser_control.py` (4 methods, listed individually below).
- **What it does:** Groups the RPC methods in this module.
- **How it works:** Each entry is registered at module import via `@method("<name>")`; see `methods_browser_control.py` line numbers per entry.
- **Inputs / options:** n/a (see the individual entries).
- **Outputs / side effects:** n/a (see the individual entries).
- **Config / env:** n/a
- **Edge cases / guards:** n/a
- **Rebuild notes:** n/a

### `browser.controller.register`  `id: tui.rpc-browser-controller-register`
- **Surface:** API
- **Where:** JSON-RPC method `browser.controller.register` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `browser.controller.register` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_browser_control.py:129`, registered as `@method("browser.controller.register")`.
- **Inputs / options:** `browser_profile_id`, `capabilities`, `controller_id`, `protocol_version`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `browser_profile_id`, `capabilities`, `controller_id`, `principal_id`, `profile_id`, `scope`, `session_id`, `transport_family`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `browser.controller.result`  `id: tui.rpc-browser-controller-result`
- **Surface:** API
- **Where:** JSON-RPC method `browser.controller.result` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `browser.controller.result` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_browser_control.py:243`, registered as `@method("browser.controller.result")`.
- **Inputs / options:** `command_id`, `error`, `ok`, `result`, `session_id`
- **Outputs / side effects:** `_ok` result keys: `accepted`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `browser.controller.heartbeat`  `id: tui.rpc-browser-controller-heartbeat`
- **Surface:** API
- **Where:** JSON-RPC method `browser.controller.heartbeat` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `browser.controller.heartbeat` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_browser_control.py:312`, registered as `@method("browser.controller.heartbeat")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `ok`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `browser.controller.detach`  `id: tui.rpc-browser-controller-detach`
- **Surface:** API
- **Where:** JSON-RPC method `browser.controller.detach` on the TUI gateway (called by the desktop app / dashboard chat / other clients).
- **What it does:** Handler for `browser.controller.detach` (no docstring in source; behaviour is defined by the code at the cited line).
- **How it works:** `methods_browser_control.py:347`, registered as `@method("browser.controller.detach")`.
- **Inputs / options:** `session_id`
- **Outputs / side effects:** `_ok` result keys: `detached`
- **Config / env:** n/a
- **Edge cases / guards:** no `_err(rid, …)` call at this handler (errors propagate through the dispatcher's generic handler)
- **Rebuild notes:** n/a

### `tui_gateway/server.py` — projects RPCs (`@_projects_method`)  `id: tui.rpcgroup-projects`
- **Surface:** API
- **Where:** JSON-RPC methods `projects.*` served from `tui_gateway/server.py:14904-14999` (11 methods, listed individually below). They are registered through the `_projects_method(name)` wrapper rather than a bare `@method(...)`, so a source scan for `@method("` alone misses them — the live table (`tui_gateway.server._methods`) holds 199 entries, 188 from `@method` plus these 11.
- **What it does:** First-class, per-profile, multi-folder workspaces ("projects") — create, read, update, archive, delete, and resolve the project owning a cwd.
- **How it works:** `_projects_method(name)` (`server.py:14866-14893`) wraps `@method(name)` and `@_profile_scoped` (binding `params['profile']` so app-global remote mode reads that profile's `projects.db`), opens `hermes_cli.projects_db.connect_closing()`, and calls the handler as `fn(rid, params, pdb, conn)`. `_require_project(pdb, conn, params)` resolves `params['id']` or raises `_NoProject`. `_projects_payload(conn)` returns `{projects: [...], active_id}` with `include_archived=True`.
- **Inputs / options:** every method also accepts `profile`.
- **Outputs / side effects:** Writes to the profile's `projects.db`.
- **Config / env:** `HERMES_HOME`, the active profile.
- **Edge cases / guards:** Unified error mapping — `_E_NO_PROJECT = 5062` ("no such project") for a missing id, `_E_PROJECT_ARG = 5063` for a `ValueError` (bad name/slug), `_E_PROJECTS = 5061` for anything else.
- **Rebuild notes:** One decorator that injects the DB handle and unifies error mapping removes the same six lines from every handler.

### `projects.list`  `id: tui.rpc-projects-list`
- **Surface:** API
- **Where:** JSON-RPC method `projects.list` (desktop project overview).
- **What it does:** Lists every project, including archived ones, plus the active project id.
- **How it works:** `server.py:14904` → `_ok(rid, _projects_payload(conn))`.
- **Inputs / options:** `profile`
- **Outputs / side effects:** `_ok` result keys: `projects`, `active_id`
- **Config / env:** the profile's `projects.db`.
- **Edge cases / guards:** `_err` codes `5061`, `5062` ("no such project"), `5063` via the shared wrapper.
- **Rebuild notes:** n/a

### `projects.get`  `id: tui.rpc-projects-get`
- **Surface:** API
- **Where:** JSON-RPC method `projects.get`.
- **What it does:** Returns one project by id.
- **How it works:** `server.py:14909` → `_require_project(...)` then `_ok(rid, {"project": proj.to_dict()})`.
- **Inputs / options:** `id`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** Missing id → `5062` "no such project".
- **Rebuild notes:** n/a

### `projects.create`  `id: tui.rpc-projects-create`
- **Surface:** API
- **Where:** JSON-RPC method `projects.create`.
- **What it does:** Creates a project, optionally making it active immediately.
- **How it works:** `server.py:14914` → `pdb.create_project(conn, name, slug, folders, primary_path, description, icon, color, board_slug)`, then `pdb.set_active(conn, pid)` when `use` is truthy, then returns the created project.
- **Inputs / options:** `name`, `slug`, `folders`, `primary_path`, `description`, `icon`, `color`, `board_slug`, `use`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project` (or `null`). Writes a new row to `projects.db`.
- **Config / env:** n/a
- **Edge cases / guards:** Bad name/slug → `5063`.
- **Rebuild notes:** n/a

### `projects.update`  `id: tui.rpc-projects-update`
- **Surface:** API
- **Where:** JSON-RPC method `projects.update`.
- **What it does:** Edits a project's presentation metadata.
- **How it works:** `server.py:14933` → `pdb.update_project(conn, proj.id, name, description, icon, color, board_slug)` then returns the refreshed project.
- **Inputs / options:** `id`, `name`, `description`, `icon`, `color`, `board_slug`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** n/a

### `projects.add_folder`  `id: tui.rpc-projects-add-folder`
- **Surface:** API
- **Where:** JSON-RPC method `projects.add_folder`.
- **What it does:** Adds a folder to a project's workspace, optionally as its primary folder.
- **How it works:** `server.py:14948` → `pdb.add_folder(conn, proj.id, path, label=…, is_primary=bool(...))`.
- **Inputs / options:** `id`, `path`, `label`, `is_primary`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** n/a

### `projects.remove_folder`  `id: tui.rpc-projects-remove-folder`
- **Surface:** API
- **Where:** JSON-RPC method `projects.remove_folder`.
- **What it does:** Removes a folder from a project.
- **How it works:** `server.py:14961` → `pdb.remove_folder(conn, proj.id, path)`.
- **Inputs / options:** `id`, `path`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** n/a

### `projects.set_primary`  `id: tui.rpc-projects-set-primary`
- **Surface:** API
- **Where:** JSON-RPC method `projects.set_primary`.
- **What it does:** Marks one of a project's folders as its primary path.
- **How it works:** `server.py:14968` → `pdb.set_primary(conn, proj.id, path)`.
- **Inputs / options:** `id`, `path`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project`
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** n/a

### `projects.archive`  `id: tui.rpc-projects-archive`
- **Surface:** API
- **Where:** JSON-RPC method `projects.archive`.
- **What it does:** Archives a project, or restores it when `restore` is truthy.
- **How it works:** `server.py:14975` → `(pdb.restore_project if params.get("restore") else pdb.archive_project)(conn, proj.id)` then the full payload.
- **Inputs / options:** `id`, `restore`, `profile`
- **Outputs / side effects:** `_ok` result keys: `projects`, `active_id`
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** One method for archive and restore keeps the pair symmetric.

### `projects.delete`  `id: tui.rpc-projects-delete`
- **Surface:** API
- **Where:** JSON-RPC method `projects.delete`.
- **What it does:** Permanently deletes a project.
- **How it works:** `server.py:14982` → `pdb.delete_project(conn, proj.id)` then the full payload.
- **Inputs / options:** `id`, `profile`
- **Outputs / side effects:** `_ok` result keys: `projects`, `active_id`. Removes the row.
- **Config / env:** n/a
- **Edge cases / guards:** `5062` / `5063` / `5061`.
- **Rebuild notes:** n/a

### `projects.set_active`  `id: tui.rpc-projects-set-active`
- **Surface:** API
- **Where:** JSON-RPC method `projects.set_active`.
- **What it does:** Sets (or clears) the active project.
- **How it works:** `server.py:14989` → `pdb.set_active(conn, _require_project(...).id if params.get("id") else None)`.
- **Inputs / options:** `id` (omit or falsy to clear), `profile`
- **Outputs / side effects:** `_ok` result keys: `active_id`
- **Config / env:** n/a
- **Edge cases / guards:** An `id` that resolves to nothing → `5062`.
- **Rebuild notes:** n/a

### `projects.for_cwd`  `id: tui.rpc-projects-for-cwd`
- **Surface:** API
- **Where:** JSON-RPC method `projects.for_cwd`.
- **What it does:** Resolves which project owns a directory, and reports that directory's git branch.
- **How it works:** `server.py:14995` → `_completion_cwd(...)` normalises the cwd, `pdb.project_for_path(conn, cwd)` resolves the project, `_git_branch_for_cwd(cwd)` reads the branch.
- **Inputs / options:** `cwd`, `profile`
- **Outputs / side effects:** `_ok` result keys: `project` (or `null`), `cwd`, `branch`
- **Config / env:** n/a
- **Edge cases / guards:** `_non_workspace_dirs()` (`server.py:15000+`) excludes the filesystem root, the user's home, and the directory homes live in (`/home` on Linux, `/Users` on macOS, `C:\Users` on Windows) — both POSIX spellings are excluded on every host because both are reachable as a cwd anywhere (macOS ships an empty `/home` autofs stub; a container or remote shell hands back Linux paths). Promoting one of these would mint a catch-all project that swallows unplaced sessions.
- **Rebuild notes:** Blocklist the directories that would become catch-all workspaces, on every platform, not just the host's own spellings.

---

## 12. Overlay internals (keys, stages, labels)

### Model picker — provider stage (step 1/2)  `id: tui.model-picker-provider`
- **Surface:** TUI
- **Where:** first screen of the model picker. Header `Select provider (step 1/2)`; sub-lines `Full model IDs on the next step · Enter to continue`, `Current: <model|(unknown)>`, `type to filter · ↑/↓ select` (or `filter: <text>▎` in accent), `warning: <provider warning>`, ` ↑ <N> more`, the rows, ` ↓ <N> more`, `persist: global|session · ^g toggle` (or `persist: session only`).
- **What it does:** Lists model providers with authentication marks, filterable by typing.
- **How it works:** `src/components/modelPicker.tsx:560-630`. `VISIBLE = 12` rows via `windowItems(rows, providerIdx, VISIBLE)`; row text is `` `${authMark} ${name} · ${suffix}` ``; unauthenticated providers render in `theme.color.label` (dimmed). Selected row prefix `▸ `, others two spaces, numbered `<idx+1>. `. Data comes from `model.options {refresh, session_id, include_unconfigured, explicit_only}`.
- **Inputs / options:** `↑`/`↓` select; `Enter` choose; `Ctrl+D` disconnect the highlighted provider (only when `provider.authenticated !== false`); `Ctrl+G` toggle persist scope (only when `allowPersistGlobal`); `Ctrl+U` (raw ``) clear the filter; `Backspace`/`Delete` edit the filter; any printable character filters; `Esc` clears the filter or goes back; `q` closes (only when the filter is empty). Footer hint verbatim: `↑/↓ select · Enter choose · ^d disconnect · Esc clear/back · q close`.
- **Outputs / side effects:** Advances to the model stage, or opens the key/disconnect stages.
- **Config / env:** provider credentials in `~/.hermes/.env`.
- **Edge cases / guards:** `loading models…`; `error: <err>` with `Esc/q cancel`; `no providers available` with `Esc/q cancel`; `no providers match` when a filter excludes everything.
- **Rebuild notes:** Reserve exactly `VISIBLE` rows (padding with blanks) so the panel height never changes while filtering.

### Model picker — model stage (step 2/2)  `id: tui.model-picker-models`
- **Surface:** TUI
- **Where:** second screen. Header `Select model (step 2/2)`; sub-lines `<provider name|(unknown provider)> · Esc back`, the filter line, the warning line, the `↑ N more` / `↓ N more` markers, the persist line.
- **What it does:** Lists the chosen provider's models and switches to the selected one.
- **How it works:** `modelPicker.tsx:632-700`. Row prefix is `▸ ` for the cursor, `* ` for the currently active model, two spaces otherwise; rows are numbered.
- **Inputs / options:** `↑`/`↓`, `Enter` switch, `Esc` clear filter / back, `q` close, `Ctrl+G` persist toggle, `Ctrl+U` clear filter, printable characters filter. Footer hint verbatim: `↑/↓ select · Enter switch · Esc clear/back · q close`, or `Esc back · q close` when the list is empty.
- **Outputs / side effects:** `config.set {key:'model', …}` via `onSelect`.
- **Config / env:** `model`.
- **Edge cases / guards:** `no models match filter`; `no models listed for this provider`.
- **Rebuild notes:** Mark the current selection distinctly from the cursor.

### Model picker — API key stage  `id: tui.model-picker-key`
- **Surface:** TUI
- **Where:** header `Configure <provider name>`; body `Paste your API key below (saved to ~/.hermes/.env)`, then `<KEY_ENV>:` and the masked value.
- **What it does:** Saves a provider API key and immediately refreshes that provider's model list.
- **How it works:** `modelPicker.tsx:466-514` → `model.save_key {slug, api_key, session_id}` (`tui_gateway/methods_complete.py:493`). The value renders as `•` repeated up to 40 characters, or `(empty)`, with a `▎` cursor while not saving.
- **Inputs / options:** printable characters type; `Backspace`/`Delete` erase; `Ctrl+U` clears; `Enter` saves; `Esc` goes back. Footer hint verbatim: `Enter save · Ctrl+U clear · Esc back`.
- **Outputs / side effects:** Writes the key to `~/.hermes/.env`; states `saving…` and `error: <keyError>`.
- **Config / env:** `~/.hermes/.env`.
- **Edge cases / guards:** The key is never echoed in full.
- **Rebuild notes:** Save credentials from the picker itself — sending the user to a config file loses them.

### Model picker — disconnect stage  `id: tui.model-picker-disconnect`
- **Surface:** TUI
- **Where:** header `Disconnect <provider name>?`; body `This removes saved credentials for <provider name>.`
- **What it does:** Removes a provider's stored credentials after a confirmation.
- **How it works:** `modelPicker.tsx:516-550` → `model.disconnect {slug}` (`methods_complete.py:573`).
- **Inputs / options:** `y` or `Enter` confirm; `n` or `Esc` cancel. Footer hint verbatim: `y/Enter confirm · n/Esc cancel`.
- **Outputs / side effects:** Credentials removed.
- **Config / env:** `~/.hermes/.env`.
- **Edge cases / guards:** Only reachable when the provider is authenticated.
- **Rebuild notes:** n/a.

### Skills Hub — category stage  `id: tui.skills-hub-category`
- **Surface:** TUI
- **Where:** header `Skills Hub`; sub-line `select a category`.
- **What it does:** Lists skill categories with per-category counts.
- **How it works:** `src/components/skillsHub.tsx:207-236`. Rows are `` `${category} · ${count} skills` ``, windowed at `VISIBLE = 12`, prefixed `▸ ` / two spaces and numbered.
- **Inputs / options:** `↑`/`↓` select; `Enter` open; digits `1`-`9` and `0` (= 10) quick-pick; `Esc`/`q` cancel. Footer hint verbatim: `↑/↓ select · Enter open · 1-9,0 quick · Esc/q cancel`. Overflow markers ` ↑ <N> more` / ` ↓ <N> more`.
- **Outputs / side effects:** Advances to the skill stage.
- **Config / env:** n/a.
- **Edge cases / guards:** `error: <err>` with `Esc/q cancel`.
- **Rebuild notes:** n/a.

### Skills Hub — skill list stage  `id: tui.skills-hub-list`
- **Surface:** TUI
- **Where:** header `<category name>`; sub-line `<N> skill(s)`.
- **What it does:** Lists the category's skills.
- **How it works:** `skillsHub.tsx:238-268`.
- **Inputs / options:** `↑`/`↓`, `Enter` open, `1`-`9`/`0` quick-pick, `Esc` back, `q` close. Footer hint verbatim: `↑/↓ select · Enter open · 1-9,0 quick · Esc back · q close`, or `Esc back · q close` when empty.
- **Outputs / side effects:** Advances to the detail stage.
- **Config / env:** n/a.
- **Edge cases / guards:** `no skills in this category`.
- **Rebuild notes:** n/a.

### Skills Hub — skill detail stage  `id: tui.skills-hub-detail`
- **Surface:** TUI
- **Where:** header `<skill name>`; lines `<category>`, the description, `path: <path>`.
- **What it does:** Shows one skill's metadata and lets you re-inspect or reinstall it.
- **How it works:** `skillsHub.tsx:271-286` → `skills.manage {action:'inspect'|'install', query}`.
- **Inputs / options:** `i` reinspect; `x` reinstall; `Enter`/`Esc` back; `q` close. Footer hint verbatim: `i reinspect · x reinstall · Enter/Esc back · q close`.
- **Outputs / side effects:** Reinstall writes to disk; states `loading…`, `installing…`, `error: <err>`.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Plugins Hub  `id: tui.plugins-hub-rows`
- **Surface:** TUI
- **Where:** header `Plugins Hub`; sub-line `<N> user plugin(s)[ · +<M> bundled (Tab)]` or `all <N> plugins`.
- **What it does:** Lists installed plugins with their activation state and toggles them.
- **How it works:** `src/components/pluginsHub.tsx`. Row label is `` `${glyph} ${name}${' v'+version}${' [bundled]'}${' ('+status+')'}` `` where `GLYPH = {enabled: '✓', disabled: '✗'}` and anything else falls back to `○` with status text `not enabled`. `VISIBLE = 12`. Backed by `plugins.manage {action, name, enable, …}`.
- **Inputs / options:** `↑`/`↓` select; `Enter` or `Space` toggle; `Tab` switch scope between user-only and all; digits `1`-`9`/`0` quick-pick; `Esc`/`q` close. Footer hint verbatim: `↑/↓ select · Enter/Space toggle · Tab user/all · 1-9,0 quick · Esc/q close`. Overflow marker ` ↓ <N> more`.
- **Outputs / side effects:** Plugin enable/disable persisted; states `updating…`, `error: <err>`.
- **Config / env:** plugin config.
- **Edge cases / guards:** Empty state: `no plugins installed` + `install: hermes plugins install owner/repo` + `Esc/q close`.
- **Rebuild notes:** n/a.

### Pet picker rows  `id: tui.pet-picker-rows`
- **Surface:** TUI
- **Where:** header `Pets`; sub-line `type to filter · <N> pet(s)` or `filter: <query> · <N> pet(s)`.
- **What it does:** Browses adoptable pets and adopts one.
- **How it works:** `src/components/petPicker.tsx`, `VISIBLE = 10`. Row marker: `●` when the pet is the ACTIVE one and pets are enabled, `✓` when installed, blank otherwise; the row shows `<displayName> (<slug>[ · official])` where the `· official` tag marks a curated, not-yet-installed pet. Backed by `pet.gallery {localOnly}` and `pet.select {slug}`.
- **Inputs / options:** `↑`/`↓` select; `Enter` adopt; printable characters filter; `Backspace`/`Delete` edit the filter; `Esc` cancel. Footer hint verbatim: `↑/↓ select · Enter adopt · type to filter · Esc cancel`.
- **Outputs / side effects:** Pet installed/activated; states `adopting…`, `error: <err>`.
- **Config / env:** `display.pet.*`.
- **Edge cases / guards:** `no pets available` / `no pets match "<query>"`; `error: <err>` with `Esc cancel`.
- **Rebuild notes:** n/a.

### Session switcher rows and hints  `id: tui.session-switcher-rows`
- **Surface:** TUI
- **Where:** header `Sessions`; sub-line the session-count label; the `+new` row; then live/history rows.
- **What it does:** Lists live sessions plus a `+new` dispatch row, with per-row and global hotkey hints.
- **How it works:** `src/components/activeSessionSwitcher.tsx`, `VISIBLE = 12`. Hint segments are typed `{role: 'hotkey'|'label'|'text', text}` so the renderer can color hotkeys with `theme.color.accent`, labels with `theme.color.label` and prose with `theme.color.muted` (`orchestratorHintSegmentColor`). `orchestratorContextHintSegments(newSelected)` builds either `New row: type prompt · Enter start · Tab model` or `Session row: Enter switch · Ctrl+D close`; `orchestratorGlobalHotkeyHintSegments` builds `↑↓ move · Ctrl+N new · Ctrl+R refresh · Esc close`. The `+new` row's title is `draftTitleFromPrompt(draft) || 'Start a new live session'`. Backed by `session.active_list {current_session_id}`, `session.activate`, `session.close`, `session.create`, `session.delete`.
- **Inputs / options:** `Esc` close; `Ctrl+N` new; `Ctrl+R` refresh; `Tab` (on the `+new` row) choose a model for the new session; `Ctrl+D` close the selected live session; `d` (without Ctrl, on a history row) delete a stored session; `↑`/`↓` move; `Enter` activate; mouse click selects a row. `isCtrl(letter)` also accepts the raw control character so terminals that send control bytes directly still match.
- **Outputs / side effects:** Session activation / creation / closure / deletion.
- **Config / env:** n/a.
- **Edge cases / guards:** `no other sessions — Enter on +new to start one`; `error: <err>`.
- **Rebuild notes:** Model the hint as typed segments so hotkeys can be styled without parsing the rendered string.

### Agents overlay — list mode  `id: tui.agents-list`
- **Surface:** TUI
- **Where:** full pane. Title `Spawn tree` (plus ` · ⏸ paused`) or, in replay mode, `Replay <i>/<n> · finished <time>` / `Last turn · finished <time>`. Meta line joins the totals summary, a sparkline, `caps d<maxDepth>/<maxConc>` and a model mix like `sonnet×3 · haiku×1` (top 4).
- **What it does:** Shows the live subagent tree as a Gantt strip plus a scrollable row list, with sorting, filtering, history navigation and kill/pause controls.
- **How it works:** `src/components/agentsOverlay.tsx`. `SORT_LABEL = {'depth-first': 'spawn order', 'duration-desc': 'slowest', status: 'status', 'tools-desc': 'busiest'}`; `FILTER_LABEL = {all: 'all', failed: 'failed', leaf: 'leaves', running: 'running'}`; `STATUS_RANK = {error:0, failed:0, interrupted:1, timeout:1, running:2, queued:3, completed:4}`. `GanttStrip` renders at most 6 rows above the list.
- **Inputs / options:** `↑`/`k` and `↓`/`j` move; `g` top; `G` bottom; `Enter`/`→`/`l` open detail; `x` kill the selected subagent; `X` kill its subtree; `p` pause/resume delegation; `s` cycle sort; `f` cycle filter; `[` / `<` previous history snapshot; `]` / `>` next; `q` close; `Esc` close. Footer hint verbatim: `↑↓/jk move · g/G top/bottom · Enter/→ open detail<controlsHint> · s sort:<label> · f filter:<label>[ · [ / ] history <i>/<n>] · q close`, where `controlsHint` is ` · x kill · X subtree · p resume|pause` live, or ` · controls locked` in replay mode.
- **Outputs / side effects:** `subagent.interrupt`, `delegation.pause`; a `flash` line in `theme.color.accent` reports the action.
- **Config / env:** `max_spawn_depth`, `max_concurrent_children`.
- **Edge cases / guards:** Empty: `No subagents this turn. Trigger delegate_task to populate the tree.` Replay snapshots lock the destructive controls.
- **Rebuild notes:** Lock mutating controls when viewing a historical snapshot; say so in the hint.

### Agents overlay — detail mode  `id: tui.agents-detail`
- **Surface:** TUI
- **Where:** full pane, right of / replacing the list.
- **What it does:** Shows one subagent's full record in a scrollable pane with its own scrollbar.
- **How it works:** `agentsOverlay.tsx` — a `ScrollBox` plus `OverlayScrollbar` (`src/components/overlayScrollbar.tsx`).
- **Inputs / options:** `↑`/`k` and `↓`/`j` scroll; `PageUp`/`Ctrl+U` and `PageDown`/`Ctrl+D` page; wheel up/down; `g` top; `G` bottom; `Esc`/`←`/`h` back to the list; `q` close; `x`/`X`/`p` still act on the selection. Footer hint verbatim: `↑↓/jk scroll · PgUp/PgDn page · g/G top/bottom · Esc/← back to list<controlsHint> · q close`.
- **Outputs / side effects:** Same as list mode.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Agents overlay — replay diff view  `id: tui.agents-diff`
- **Surface:** TUI
- **Where:** full pane, entered with `/replay-diff <a> <b>`.
- **What it does:** Compares two archived spawn trees side by side.
- **How it works:** `DiffView` in `agentsOverlay.tsx`, fed by `setDiffPair({baseline, candidate})` from `src/app/spawnHistoryStore.ts`.
- **Inputs / options:** `Esc`/`q` close.
- **Outputs / side effects:** Read-only.
- **Config / env:** n/a.
- **Edge cases / guards:** Rendered instead of the list/detail views whenever a diff pair is set.
- **Rebuild notes:** n/a.

### Journey overlay — timeline  `id: tui.journey-timeline`
- **Surface:** TUI
- **Where:** full pane. Header `✦ Journey` in `theme.color.primary` plus the muted sub-line `learned skills & memories over time`, a legend row of `<glyph> <label>` pairs, a chart, then a chronological item tree.
- **What it does:** Plots learned skills and memories over time and lets you inspect, edit or delete a node.
- **How it works:** `src/components/journey.tsx`. Data comes from `learning.frames {cols, frames, rows}` (`tui_gateway/methods_tools.py:1821`), which pre-renders the timeline server-side (reveal 0→1 frames plus legend/summary/bucket metadata); `learning.detail {id}`, `learning.edit {id, content}` and `learning.delete {id}` back the actions. `MAX_CHART_ROWS` bounds the chart; the list height is `max(3, rows - chartRows - (categories ? 11 : 10))`. Colors come from `src/lib/starmapPalette.ts` (147 lines) via `fadeInk(palette, style, phase)`.
- **Inputs / options:** `↑`/`k` and `↓`/`j` move; `PageUp`/`Ctrl+U` and `PageDown`/`Ctrl+D`/`Space` page; `g` top; `G` bottom; `Enter`/`→`/`l` open a node with a body; `Esc`/`←`/`h` back; `d` delete (confirm with `y`/`Y`); `e` edit; `q` close.
- **Outputs / side effects:** Skills are ARCHIVED (restorable) on delete; memories are removed. Status lines: `delete <label>? y/N` in `theme.color.error`; a notice line in `theme.color.accent`.
- **Config / env:** memory provider config.
- **Edge cases / guards:** The shell state renders `✦ Journey` + `Esc/q close`.
- **Rebuild notes:** Pre-render the chart server-side so the terminal client only paints frames.

### Journey overlay — node detail  `id: tui.journey-detail`
- **Surface:** TUI
- **Where:** full pane after opening a node.
- **What it does:** Shows a node's body and offers edit/delete.
- **How it works:** `journey.tsx:415-445`.
- **Inputs / options:** `↑`/`↓`/`j`/`k` scroll; `PageUp`/`PageDown` page; `e` edit; `d` delete; `Esc`/`←` back; `q` close. Footer hint verbatim: `↑↓/jk scroll · PgUp/PgDn page · e edit · d delete · Esc/← back · q close`.
- **Outputs / side effects:** `learning.edit` / `learning.delete`.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Grid streams demo  `id: tui.grid-streams`
- **Surface:** TUI
- **Where:** `/grid-test streams`, or `s` inside `/grid-test`.
- **What it does:** Renders several simultaneous fake streams in a grid with one promotable "main" pane — a stress test for the layout engine under concurrent updates.
- **How it works:** `src/components/gridStreamsDemo.tsx` (364 lines) with `GRID_STREAM_COUNT` from `src/sdk/apps/gridTestState.ts`. State fields `streams`, `streamFocus`, `streamMain`.
- **Inputs / options:** `←`/`↑`/`h`/`k` previous stream; `→`/`↓`/`l`/`j` next; `Enter` promote the focused stream to main; `r` reset to a 4×3 grid; `Esc`/`q`/`s` leave streams mode.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Focus wraps modulo `GRID_STREAM_COUNT`.
- **Rebuild notes:** n/a.

### Grid test overlay rendering  `id: tui.grid-test-overlay`
- **Surface:** TUI
- **Where:** the body of `/grid-test`.
- **What it does:** Draws the configurable cell grid, its named-areas variant, nesting and zoom.
- **How it works:** `src/components/gridTestOverlay.tsx` (318 lines) rendering `WidgetGrid` / `GridAreas` from the app state `{activeCol, activeRow, areas, cols, rows, gap, paddingX, nested, zoomed, streams, streamFocus, streamMain}`.
- **Inputs / options:** see `tui.app-grid-test`.
- **Outputs / side effects:** Display only.
- **Config / env:** n/a.
- **Edge cases / guards:** Width is clamped to `min(cols - 6, 120)`.
- **Rebuild notes:** n/a.

### Pet sprite renderers  `id: tui.pet-sprite`
- **Surface:** TUI
- **Where:** the pet pane.
- **What it does:** Draws the pet either as a Kitty-graphics image or as a Unicode half-block sprite grid.
- **How it works:** `src/components/petSprite.tsx` (93 lines) exports `PetKitty({color, placeholder})` and `PetSprite({grid})`. Frames come from `pet.cells {state, cols, graphics}` (`tui_gateway/methods_session.py:1833`), which downsamples the spritesheet server-side because the TUI cannot draw a canvas. Polling logic is `src/lib/petPolling.ts` (73 lines); animation state is `src/app/usePet.ts`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `display.pet.enabled`, `display.pet.scale`.
- **Edge cases / guards:** Kitty placeholder cells (`U+10EEEE`) are counted rather than measured with `String.length`, because the zero-width diacritics that address image cells make length lie.
- **Rebuild notes:** Downsample server-side; a terminal client should receive cells, not pixels.

---

## 13. App state, hooks and lifecycle

### UI state store  `id: tui.ui-store`
- **Surface:** Core
- **Where:** `ui-tui/src/app/uiStore.ts`.
- **What it does:** The single nanostores atom holding every piece of global UI state.
- **How it works:** `buildUiState()` (`uiStore.ts:370-403`) — initial values verbatim: `battery: false`, `batteryStatus: null`, `bgTasks: new Set()`, `busy: false`, `busyInputMode: 'queue'`, `compact: false`, `compacting: false`, `destructiveSlashConfirm: true`, `detailsMode: 'collapsed'`, `detailsModeCommandOverride: false`, `focusView: false`, `indicatorStyle: DEFAULT_INDICATOR_STYLE`, `info: null`, `liveSessionCount: 0`, `inlineDiffs: true`, `mouseTracking: MOUSE_TRACKING`, `notice: null`, `pasteCollapseLines: 5`, `pasteCollapseChars: 2000`, `sections: {}`, `sessionTitle: ''`, `showReasoning: false`, `sid: null`, `status: 'summoning hermes…'`, `statusBar: 'top'`, `statusBarFields: null`, `streaming: true`, `timestamps: false`, `theme: bootTheme ?? DEFAULT_THEME`, `usage: ZERO`. Exports `$uiState`, the computed `$uiTheme` and `$uiSessionId`, plus `getUiState()`, `patchUiState(partial | fn)` and `resetUiState()`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Re-renders.
- **Config / env:** every `display.*` key syncs into it.
- **Edge cases / guards:** The theme is seeded from the boot cache so frame one is already correct.
- **Rebuild notes:** One atom + computed selectors avoids prop-drilling and keeps re-renders scoped.

### Overlay state store  `id: tui.overlay-store`
- **Surface:** Core
- **Where:** `ui-tui/src/app/overlayStore.ts`.
- **What it does:** Holds which overlays are open and derives the "input is blocked" and "status rule is occluded" predicates.
- **How it works:** `buildOverlayState()` (`overlayStore.ts:421-440`) fields: `agents: false`, `agentsInitialHistoryIndex: 0`, `approval: null`, `billing: null`, `clarify: null`, `confirm: null`, `ambient: []`, `widget: null`, `journey: false`, `modelPicker: false`, `pager: null`, `petPicker: false`, `pluginsHub: false`, `secret: null`, `sessions: false`, `skillsHub: false`, `subscription: null`, `sudo: null`. `$isBlocked` is true when ANY of `agents, approval, billing, clarify, confirm, journey, modelPicker, pager, petPicker, pluginsHub, secret, sessions, skillsHub, subscription, sudo, widget` is set. `hasFloatingPanel(overlay)` = `modelPicker || pager || petPicker || pluginsHub || sessions || skillsHub`. `$isStatusRuleOccluded` = `widget || (statusBar === 'top' && hasFloatingPanel(overlay))`.
- **Inputs / options:** `patchOverlayState`, `getOverlayState`, `resetOverlayState`, `resetFlowOverlays`.
- **Outputs / side effects:** Overlay visibility; timer gating.
- **Config / env:** n/a.
- **Edge cases / guards:** `resetFlowOverlays()` (called from `turnController.idle()` on every turn completion or interrupt) drops FLOW-scoped overlays (`approval`, `clarify`, `confirm`, `sudo`, `secret`, `pager`) but PRESERVES user-toggled ones (`agents`, `agentsInitialHistoryIndex`, `ambient`, `widget`, `journey`, `modelPicker`, `petPicker`, `pluginsHub`, `sessions`, `skillsHub`) — the old reset-everything behaviour silently closed `/agents` the moment delegation finished. The occlusion predicate deliberately excludes PromptZone flow states (they render in normal flow and push content down rather than covering it), `agents`/`journey` (they unmount the whole ComposerPane subtree, so React's own cleanup clears the intervals), `ambient` (it reserves its own rows), and composer completions (they DO occlude but change on every keystroke, so re-arming a 1 s interval per character would starve the tick).
- **Rebuild notes:** Keep "input blocked" and "chrome covered" as SEPARATE predicates — they answer different questions.

### Turn store and turn controller  `id: tui.turn-controller`
- **Surface:** Core
- **Where:** `ui-tui/src/app/turnStore.ts` (85 lines) and `ui-tui/src/app/turnController.ts` (1105 lines).
- **What it does:** Owns everything that changes during a single agent turn — streaming text, stream segments, pending and active tools, reasoning, subagents, todos — and the interrupt/idle transitions.
- **How it works:** `useTurnSelector(fn)` subscribes a component to one slice. `turnController` exposes `interruptTurn({appendMessage, gw, sid, sys})`, `idle()` (which calls `resetFlowOverlays()`), `boostStreamingForScroll()` and `relaxStreaming()` (which switch the stream batching cadence between `STREAM_BATCH_MS` and `STREAM_SCROLL_BATCH_MS`), plus `patchTurnState()` and `toggleTodoCollapsed()`.
- **Inputs / options:** driven by gateway events.
- **Outputs / side effects:** The live streaming area, the todo panel, the spawn HUD.
- **Config / env:** n/a.
- **Edge cases / guards:** Regression tests: `turnControllerNotice.test.ts`, `turnControllerTodos.test.ts`, `turnStore.test.ts`.
- **Rebuild notes:** Separate per-turn state from session state so a turn teardown cannot clobber session-level UI.

### Gateway event handler  `id: tui.event-handler`
- **Surface:** Core
- **Where:** `ui-tui/src/app/createGatewayEventHandler.ts` (1512 lines).
- **What it does:** The single place every `GatewayEvent` is turned into UI state.
- **How it works:** A large dispatch over `event.type` (see `tui.gateway-events` for the full list). Also exports `applyConfiguredTuiTheme(value)` used by `/theme`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Every store patch.
- **Config / env:** n/a.
- **Edge cases / guards:** Tested by `createGatewayEventHandler.test.ts`.
- **Rebuild notes:** One handler module keeps event semantics auditable.

### Session lifecycle  `id: tui.session-lifecycle`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useSessionLifecycle.ts` (425 lines).
- **What it does:** Creates, resumes, activates, closes and switches sessions, and exposes the busy guard.
- **How it works:** Provides `newSession(notice?, title?)`, `newLiveSession()`, `newPromptSession()`, `resumeById(idOrTitle)`, `activateLiveSession(id)`, `closeLiveSession(id)`, `closeSession(id)`, `resetVisibleHistory(info)`, `setSessionStartedAt(ts)`, `die()`, `dieWithCode(code)` and `guardBusySessionSwitch(action)`. RPCs: `session.create`, `session.resume`, `session.activate`, `session.close`, `session.active_list`, `session.most_recent`. Resume view shaping lives in `src/app/sessionResumeView.ts` (41 lines).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Session churn; `HERMES_TUI_ACTIVE_SESSION_FILE` updates.
- **Config / env:** `HERMES_TUI_RESUME`.
- **Edge cases / guards:** `guardBusySessionSwitch('switch sessions')` refuses a cold-session load mid-turn; creating a new LIVE session is always allowed.
- **Rebuild notes:** n/a.

### Submission pipeline  `id: tui.submission`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useSubmission.ts` (422 lines) and `ui-tui/src/app/submissionCore.ts` (132 lines).
- **What it does:** Turns a composer submit into a `prompt.submit` RPC, handling queueing, steering, interrupting, attachments and shell interpolation.
- **How it works:** `submissionCore.ts` holds the pure decision logic; `useSubmission.ts` wires it to the gateway. `prompt.submit` params include `text`, `session_id`, `queued`, `interrupted`, `display_kind`, `surface`, `profile`, `confirm_truncate`, `confirm_empty_truncate`, `truncate_before_message_id`, `truncate_before_row_id`, `truncate_before_user_ordinal`, `rebind_survivor_row_ids` (`tui_gateway/methods_prompt.py:288`).
- **Inputs / options:** `Enter`, `Cmd/Ctrl+K`, `/queue`, `/steer`.
- **Outputs / side effects:** A turn starts, or a message is queued/steered.
- **Config / env:** the `busy` input mode.
- **Edge cases / guards:** Tested by `submissionCore.test.ts`, `useSubmission.test.ts`, `queueSubmission.test.ts`.
- **Rebuild notes:** Keep the "what should Enter do" decision pure and testable.

### Composer state  `id: tui.composer-state`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useComposerState.ts` (497 lines).
- **What it does:** Owns the composer's value, wrapped-line buffer, queue-edit index, history index, completions and attachment actions.
- **How it works:** Exposes `state` (`input`, `inputBuf`, `empty`, `completions`, `compIdx`, `compReplace`, `queueEditIdx`, `historyIdx`, `cols`), `actions` (`setInput`, `clearIn`, `pushHistory`, `setHistoryIdx`, `setQueueEdit`, `setCompIdx`, `dequeue`, `removeQueue`, `openEditor`) and `refs` (`queueRef`, `historyRef`, `historyDraftRef`). Queue state comes from `src/hooks/useQueue.ts` (111 lines); completions from `src/hooks/useCompletion.ts` (169 lines); input history from `src/hooks/useInputHistory.ts` and `src/lib/history.ts`.
- **Inputs / options:** every composer key.
- **Outputs / side effects:** Composer rendering.
- **Config / env:** n/a.
- **Edge cases / guards:** Tested by `useComposerState.test.ts`, `useQueue.test.ts`, `useCompletion.test.ts`.
- **Rebuild notes:** n/a.

### Config sync  `id: tui.config-sync`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useConfigSync.ts` (404 lines).
- **What it does:** Pulls the live config into UI state and re-polls when `config.yaml`'s mtime changes.
- **How it works:** Calls `config.get`-style reads and maps them onto `patchUiState`; the documented poll interval is ~5 s (cited in the `/indicator`, `/voice` and `/theme` comments as the reason those commands hot-swap state immediately instead of waiting).
- **Inputs / options:** n/a.
- **Outputs / side effects:** UI state matches `config.yaml`.
- **Config / env:** `~/.hermes/config.yaml`.
- **Edge cases / guards:** In-session commands patch state optimistically (or after confirmation) so the UI never lags a poll.
- **Rebuild notes:** mtime-poll the config file and let commands hot-swap; a pure poll makes every setting feel laggy.

### Main app hook  `id: tui.use-main-app`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useMainApp.ts` (1283 lines).
- **What it does:** Wires every store, hook and handler together and returns the props `AppLayout` renders.
- **How it works:** Returns `{appActions, appComposer, appProgress, appStatus, appTranscript, gateway}`. `appActions` includes `clearSelection`, `setStickyPrompt`, `answerApproval`, `answerClarify`, `answerClarifyQuestion`, `answerSecret`, `answerSudo`, `closeLiveSession`, `activateLiveSession`, `onModelSelect`, `newLiveSession`, `newPromptSession`, `resumeById`, `dispatchSubmission`, `appendMessage`, `sys`, `die`.
- **Inputs / options:** the `GatewayClient`.
- **Outputs / side effects:** The whole app.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Other app stores  `id: tui.small-stores`
- **Surface:** Core
- **Where:** `ui-tui/src/app/`.
- **What it does:** Small dedicated stores kept out of the main UI atom.
- **How it works:** `delegationStore.ts` (77 lines) — `$delegationState`, `applyDelegationStatus({paused, maxSpawnDepth, maxConcurrentChildren})`, `getDelegationState()`. `spawnHistoryStore.ts` (159) — `getSpawnHistory()`, `pushDiskSnapshot(result, path)`, `setDiffPair({baseline, candidate})`, type `SpawnSnapshot`. `petFlashStore.ts` (28) — `$petBox` (the pet's published footprint). `inputSelectionStore.ts` (17) — `getInputSelection()` (the composer's own selection range with `copy`/`cut`). `wakeState.ts` (15) — `setWakeUserDisabled(bool)`, remembering an explicit `/wake off` so reconnects don't re-arm. `scroll.ts` (74), `gatewayRecovery.ts` (35), `gatewayContext.tsx` (19), `setupHandoff.ts` (54), `useBatteryPoll.ts` (77), `useLongRunToolCharms.ts` (69), `usePet.ts` (352), `useGitBranch.ts` (72).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Working directory + git branch label  `id: tui.cwd-branch`
- **Surface:** TUI
- **Where:** the right-hand side of the status rule, e.g. `~/projects/hermes-agent (docs/two-week-gap-sweep)`.
- **What it does:** Shows the working directory with the ACTIVE git branch, updating when you `git checkout` in a side terminal.
- **How it works:** `src/hooks/useGitBranch.ts` (72 lines) reads git HEAD with an mtime cache; `src/domain/paths.ts` (68 lines) shortens the path. The label is replaced by the session title once one is set.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Display only.
- **Config / env:** `HERMES_CWD`, `TERMINAL_CWD`.
- **Edge cases / guards:** It truncates from the left on narrow terminals and yields the whole segment before the essentials are squeezed.
- **Rebuild notes:** mtime-cache the git HEAD read — shelling out to `git` per frame is unaffordable.

### Battery polling  `id: tui.battery-poll`
- **Surface:** Core
- **Where:** `ui-tui/src/app/useBatteryPoll.ts`.
- **What it does:** Polls `system.battery` while the indicator is on.
- **How it works:** `system.battery {}` (`tui_gateway/methods_tools.py:15`) always resolves with a payload; `available: false` means no battery. The poller only runs when `ui.battery` is true.
- **Inputs / options:** n/a.
- **Outputs / side effects:** `ui.batteryStatus`.
- **Config / env:** `display.battery`.
- **Edge cases / guards:** `/battery status` fetches on demand so it works with the poller off.
- **Rebuild notes:** n/a.

### Graceful exit and terminal-mode reset  `id: tui.graceful-exit`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/gracefulExit.ts` (67 lines) and `src/lib/terminalModes.ts` (103 lines).
- **What it does:** Guarantees the terminal is left in a sane state on every exit path.
- **How it works:** `setupGracefulExit({cleanups, onError, onSignal, ignoredSignals})` registers signal and error handlers; `resetTerminalModes()` writes the DEC mode resets with `writeSync` so they complete before the process is gone. `src/lib/terminalParity.ts` (78) and `src/lib/terminalSetup.ts` (505) handle IDE keybinding parity.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Terminal state.
- **Config / env:** n/a.
- **Edge cases / guards:** `process.on('exit')` is the final backstop because `die()`/`dieWithCode()` call `process.exit()` after Ink unmounts specifically so it can fire.
- **Rebuild notes:** Reset modes synchronously in an `exit` handler; anything async loses the race.

### Clipboard and OSC 52  `id: tui.clipboard`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/clipboard.ts` (202 lines) and `src/lib/osc52.ts` (76 lines).
- **What it does:** Reads and writes the system clipboard, falling back to the OSC 52 terminal escape.
- **How it works:** `writeClipboardText(text)` / `readClipboardText()` try the native tools (pbcopy on macOS, wl-copy/xclip on Linux, tmux buffers) and return a boolean; `writeOsc52Clipboard(text)` emits the escape sequence. The fallback order mirrors `hermes_cli/clipboard.py` (see its header comment at `hermes_cli/clipboard.py:104`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** Clipboard.
- **Config / env:** `HERMES_TUI_FORCE_OSC52`.
- **Edge cases / guards:** Over SSH (`SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`) the OSC 52 path is used directly, because a native write would target the wrong machine.
- **Rebuild notes:** n/a.

### Text and fuzzy utilities  `id: tui.text-utils`
- **Surface:** Core
- **Where:** `ui-tui/src/lib/text.ts` (420 lines), `fuzzy.ts` (177), `model-search-text.ts` (33), `emoji.ts`, `mathUnicode.ts`, `circularBuffer.ts` (48), `memory.ts` (246), `starmapPalette.ts` (147), `reasoning.ts` (55), `liveProgress.ts` (79), `inputMetrics.ts` (203), `prompt.ts` (36), `editor.ts` (70), `history.ts` (82), `rpc.ts` (52), `billingDialog.ts` (36), `externalCli.ts` (16), `resizeCoalescer.ts` (56).
- **What it does:** The shared helpers the TUI is built from.
- **How it works:** Notable exports — `text.ts`: `pick`, `fmtK`, `flat`, `compactPreview`, `boundedLiveRenderText`, `hasAnsi`, `sanitizeAnsiForRender`, `stripAnsi`, `isPasteBackedText`, `clarifyBatchRevisitState`. `fuzzy.ts`: the fuzzy matcher that `hermes_cli/curses_ui.py:267` documents itself as a faithful port of. `inputMetrics.ts`: `COMPOSER_PROMPT_GAP_WIDTH`, `composerPromptWidth`, `inputVisualHeight`, `stableComposerColumns`, `transcriptBodyWidth`, `transcriptGutterWidth`. `rpc.ts`: `asCommandDispatch`, `rpcErrorMessage`. `resizeCoalescer.ts`: coalesces SIGWINCH bursts to at most one reflow per `RESIZE_COALESCE_MS = 32` (~30 fps) with a trailing edge that always lands the final width.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Pure functions.
- **Config / env:** n/a.
- **Edge cases / guards:** Each has a dedicated vitest file under `src/__tests__/`.
- **Rebuild notes:** Coalesce resize bursts on a trailing edge; reflowing per SIGWINCH stutters a drag-resize.

---

## 14. `tui_gateway` non-RPC subsystems

### Gateway entry point  `id: tui.gw-entry`
- **Surface:** Core
- **Where:** `python -m tui_gateway.entry`.
- **What it does:** The stdio server loop: reads JSON-RPC lines from stdin, dispatches them, writes frames to stdout.
- **How it works:** `tui_gateway/entry.py` (516 lines). Imports `hermes_bootstrap` and calls `harden_import_path()` FIRST so a `utils/`, `proxy/` or `ui/` package in the launch directory cannot shadow Hermes's own top-level modules. Then wires `server.dispatch`, `resolve_skin`, `write_json`, `replay_epoch`, `_CRASH_LOG`, the sidecar publisher, MCP discovery (`ensure_mcp_discovery_started` / `wait_for_mcp_discovery`, whose first agent build briefly joins the thread so fast servers land before the agent snapshots its tool list) and the shutdown grace.
- **Inputs / options:** stdin JSON lines.
- **Outputs / side effects:** stdout JSON frames; stderr diagnostics.
- **Config / env:** `HERMES_TUI_SIDECAR_URL`, `HERMES_TUI_GATEWAY_SHUTDOWN_GRACE_S`, `HERMES_TUI_GATEWAY_NO_FLUSH`.
- **Edge cases / guards:** `_mcp_discovery_enabled` is kept as a flag rather than re-probing config so non-MCP sessions never pay the `tools.mcp_tool` import on the per-agent-build wait path; it also lets the idempotent spawn be re-invoked on later builds so the retry-after-zero-connected allowance can fire.
- **Rebuild notes:** Harden the import path before importing anything else in a tool that runs from arbitrary cwds.

### Gateway WebSocket server  `id: tui.gw-ws`
- **Surface:** Core
- **Where:** `tui_gateway/ws.py` (596 lines); mounted by the dashboard at `/api/ws`.
- **What it does:** Serves the same dispatcher over a WebSocket for the desktop app and the dashboard's chat tab.
- **How it works:** Binds a per-connection transport into the contextvar and answers the same method table.
- **Inputs / options:** WS frames (text or binary).
- **Outputs / side effects:** WS frames.
- **Config / env:** dashboard auth.
- **Edge cases / guards:** Bound to the dashboard process's lifetime and auth; the OpenAI-compatible API server does not serve it.
- **Rebuild notes:** n/a.

### Event publisher  `id: tui.gw-event-publisher`
- **Surface:** Core
- **Where:** `tui_gateway/event_publisher.py` (126 lines).
- **What it does:** Publishes gateway events to a secondary WebSocket sink (`WsPublisherTransport`).
- **How it works:** Used by the sidecar tee.
- **Inputs / options:** an event dict.
- **Outputs / side effects:** WS frames.
- **Config / env:** `HERMES_TUI_SIDECAR_URL`.
- **Edge cases / guards:** Best-effort.
- **Rebuild notes:** n/a.

### Hosted rooms (groups)  `id: tui.gw-hosted-rooms`
- **Surface:** Core / API
- **Where:** `tui_gateway/hosted_room_service.py` (1013), `hosted_room_driver.py` (1599), `hosted_room_peer_http.py` (1037), `hosted_room_peer_transport.py` (368), `hosted_room_server_rpc.py` (213); RPC surface `groups.*` (see §11).
- **What it does:** Implements multi-agent "rooms": a room home gateway holds the authoritative event log; peers replicate it, and authority can be promoted/demoted with epoch fencing.
- **How it works:** `groups.capabilities` describes the protocol; `groups.create`/`send`/`rename`/`disband`/`stop`/`approve`/`retry` mutate a room idempotently by `event_id`; `groups.log {room_id, since_seq, limit}` returns a monotonic delta; `groups.replicate` persists an authority-stamped page into the local replica store; `groups.replica_state` reports coverage and lineage; `groups.promote {room_id, confirm, reason}` continues a replicated room on THIS gateway at `epoch + 1`; `groups.demote {room_id, observed_epoch, observed_gateway_id}` fences a stale authority. Peer routes are minted and revoked with `groups.peer.invite` / `groups.peer.register` / `groups.peer.revoke`.
- **Inputs / options:** see the per-method entries in §11.
- **Outputs / side effects:** A durable room log; cross-install HTTP calls.
- **Config / env:** room/peer configuration.
- **Edge cases / guards:** `groups.promote` requires `confirm: true` — the caller asserts the previous authority can no longer write.
- **Rebuild notes:** Epoch-fenced authority plus an idempotent, sequenced event log is the whole design; everything else is transport.

### Compute host and host supervisor  `id: tui.gw-compute-host`
- **Surface:** Core
- **Where:** `tui_gateway/compute_host.py` (948) and `host_supervisor.py` (598).
- **What it does:** Runs and supervises hosted compute tasks for rooms and remote surfaces.
- **How it works:** `prompt.submit` accepts `_hosted_task` and `_hosted_terminal_callback` params (`methods_prompt.py:288`), and `session.interrupt` accepts `expected_hosted_task_id` — the hosted path threads a task identity through the ordinary session machinery.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Subprocesses and task state.
- **Config / env:** n/a.
- **Edge cases / guards:** `expected_hosted_task_id` makes interrupt idempotent against a task that already finished.
- **Rebuild notes:** n/a.

### Project tree and git probe  `id: tui.gw-project-tree`
- **Surface:** Core
- **Where:** `tui_gateway/project_tree.py` (793) and `git_probe.py` (202).
- **What it does:** Builds the authoritative project → repo → lane structure the desktop overview renders, and probes git state cheaply.
- **How it works:** Backs `projects.tree {preview_limit, session_limit}`, `projects.project_sessions {project_id, session_limit}`, `projects.discover_repos {scan}` and `projects.record_repos {repos, discovery_policy}` — the native filesystem crawl runs on the desktop and its result is cached here so later reads are instant instead of re-walking disk.
- **Inputs / options:** see §11.
- **Outputs / side effects:** A cached repo list.
- **Config / env:** n/a.
- **Edge cases / guards:** `projects.tree` also returns the flat set of session ids claimed by any project so the desktop can exclude them from flat Recents.
- **Rebuild notes:** Do the crawl where the filesystem is, cache the result where the queries are.

### Synthetic turns and turn markers  `id: tui.gw-synthetic-turn`
- **Surface:** Core
- **Where:** `tui_gateway/synthetic_turn.py` (231) and `turn_marker.py` (159).
- **What it does:** Injects turns that did not come from a user keystroke (background tasks, `btw`, room deliveries) into a session's stream, and marks turn boundaries in the event log.
- **How it works:** Used by `prompt.background`, `prompt.btw`, `bot_relay.deliver` and the hosted-room driver.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Session events.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Loop-noise suppression  `id: tui.gw-loop-noise`
- **Surface:** Core
- **Where:** `tui_gateway/loop_noise.py` (83 lines).
- **What it does:** Suppresses repetitive log/event noise from tight agent loops.
- **How it works:** Rate-limits repeated identical emissions.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Fewer duplicate frames.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### MCP OAuth session store  `id: tui.gw-mcp-oauth`
- **Surface:** Core
- **Where:** `tui_gateway/mcp_oauth_sessions.py` (429 lines).
- **What it does:** Holds in-flight MCP OAuth flows so `start`/`poll`/`callback` can span multiple RPCs.
- **How it works:** Backs `mcp.servers.oauth.start {name, client_redirect_uri}`, `mcp.servers.oauth.poll {name, session_id}` and `mcp.servers.oauth.callback {name, session_id, code, state, error}` — the callback variant is the remote-backend companion for clients that capture the redirect themselves. `mcp_rpc_helpers.py` (74) holds the shared helpers.
- **Inputs / options:** see §11.
- **Outputs / side effects:** Stored tokens.
- **Config / env:** profile MCP config.
- **Edge cases / guards:** `oauth.start` can block up to ~30 s waiting for the provider to publish an authorization URL, hence its place in `_LONG_HANDLERS`.
- **Rebuild notes:** n/a.

### Method context helper  `id: tui.gw-method-ctx`
- **Surface:** Core
- **Where:** `tui_gateway/method_ctx.py` (53 lines).
- **What it does:** Carries per-request context (transport, session, profile) to handlers, including pooled ones.
- **How it works:** contextvars, set by the dispatcher before invoking a handler.
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

### Server-side render helper  `id: tui.gw-render`
- **Surface:** Core
- **Where:** `tui_gateway/render.py` (49 lines).
- **What it does:** Renders text the client shows verbatim (panel bodies, rendered diffs).
- **How it works:** Small formatting helpers shared by handlers.
- **Inputs / options:** n/a.
- **Outputs / side effects:** Strings in RPC results.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** n/a.

---

## 15. CLI flags, build tooling and the vendored Ink fork

### `--tui` / `--cli` / `--dev` flags  `id: tui.cli-flags`
- **Surface:** CLI
- **Where:** `hermes --help`, verbatim (live output, `hermes_inv/cli_help/_root.txt:172-176`): `--tui` / `Launch the modern TUI instead of the classic REPL`; `--cli` / `Force the classic prompt_toolkit REPL (overrides display.interface=tui)`; `--dev` / `With --tui: run TypeScript sources via tsx (skip dist build)`.
- **What it does:** Chooses the interactive front-end for one invocation and, with `--dev`, runs the TUI from source.
- **How it works:** Parsed in `hermes_cli/main.py`; `_wants_tui_early(argv)` (`main.py:314`) decides before the heavy imports, consulting `_config_default_interface_early()` (`main.py:284`) which reads `display.interface` with a minimal parser.
- **Inputs / options:** the three flags above. Related flags that the TUI path forwards (from the same help screen): `--resume SESSION, -r SESSION` / `Resume a previous session by ID or title, or pass 'latest' for the most recent session (workspace-scoped, like -c with no name)`; `--continue [SESSION_NAME], -c [SESSION_NAME]` / `Resume a session by name, or the most recent if no name given`; `--in DIR` / `Change into DIR before starting or resuming. Combined with '--resume latest' or -c, the most recent session for DIR's workspace is picked, and the session stays in DIR (skips the recorded-cwd restore).`; `--no-restore-cwd`; `--worktree, -w` / `Run in an isolated git worktree (for parallel agents)`; `--accept-hooks`; `--skills SKILLS`; `--yolo`; `--pass-session-id`; `-t TOOLSETS`; `--provider PROVIDER`; `--reasoning LEVEL`; `--ignore-user-config`; `--ignore-rules`; `--safe-mode`.
- **Outputs / side effects:** Which front-end starts.
- **Config / env:** `display.interface: cli|tui`; `HERMES_TUI=1`.
- **Edge cases / guards:** Documented examples, verbatim: `hermes --tui` / `Launch the modern TUI (or set display.interface: tui)`; `hermes --cli` / `Force the classic REPL (overrides display.interface: tui)`; `hermes --tui --resume latest --in ./dir` / `Resume ./dir's latest session in the TUI`.
- **Rebuild notes:** Resolve the interface choice before the expensive imports so the wrong front-end never pays for the right one's startup.

### TUI bundle build (`npm run build`)  `id: tui.build-script`
- **Surface:** Core
- **Where:** `ui-tui/scripts/build.mjs`, run automatically by `hermes --tui` and manually with `npm run build`.
- **What it does:** Bundles `src/entry.tsx` into a single self-contained `dist/entry.js` that needs no runtime `node_modules`.
- **How it works:** esbuild with a `stub-react-devtools-core` plugin that resolves `react-devtools-core` (only imported when `DEV=true` at runtime for Ink dev mode) to `export default { initialize() {}, connectToDevTools() {} }`, so the bundle never carries the dependency.
- **Inputs / options:** `npm run build`; `npm run build:ink` builds the vendored Ink package first.
- **Outputs / side effects:** `ui-tui/dist/entry.js`.
- **Config / env:** n/a.
- **Edge cases / guards:** The Python launcher rebuilds whenever sources are newer than the dist (desktop always rebuilds; Termux uses the mtime freshness check).
- **Rebuild notes:** A single self-contained bundle removes the "did node_modules survive the update" class of failure entirely.

### Package scripts  `id: tui.npm-scripts`
- **Surface:** Core
- **Where:** `ui-tui/package.json`.
- **What it does:** The contributor commands for the TUI workspace.
- **How it works:** Verbatim: `dev` = `npm run build:ink && tsx --watch src/entry.tsx`; `start` = `tsx src/entry.tsx`; `build` = `node scripts/build.mjs`; `build:ink` = `npm run build --prefix packages/hermes-ink`; `visual` = `node scripts/visual/run.mjs`; `typecheck` = `tsc --noEmit -p tsconfig.json`; `lint` = `eslint src/ packages/`; `lint:fix` = `eslint src/ packages/ --fix`; `fmt` = `prettier --write 'src/**/*.{ts,tsx}' 'packages/**/*.{ts,tsx}'`; `fix` = `npm run lint:fix && npm run fmt`; `check` = `npm run build:ink && npm run typecheck && npm run test && npm run lint`; `test` = `vitest run`; `test:watch` = `vitest`.
- **Inputs / options:** as above.
- **Outputs / side effects:** Build artefacts, lint fixes, test results.
- **Config / env:** n/a.
- **Edge cases / guards:** Dependencies are pinned exactly: `@nanostores/react` 1.1.0, `ink-text-input` 6.0.0, `nanostores` 1.4.2, `react` 19.2.7, `undici` 6.28.0, `unicode-animations` 1.0.3, plus the file-linked `@hermes/ink` and `@hermes/shared`. `overrides` redirects `ink-text-input`'s `ink` dependency to `npm:@hermes/ink@0.0.1` so the vendored fork is the only Ink in the tree. Dev deps: `@types/node` 22.20.1, `@types/react` 19.2.17, `esbuild` 0.28.1, `prettier` 3.9.5, `tsx` 4.23.1, `typescript` 6.0.3, `vitest` 4.1.10.
- **Rebuild notes:** Override the transitive `ink` dependency, or a second copy of the renderer ends up in the bundle.

### Visual regression harness (`npm run visual`)  `id: tui.visual-harness`
- **Surface:** Core
- **Where:** `ui-tui/scripts/visual/{run.mjs,render.tsx,shot.mjs,paths.mjs}`.
- **What it does:** Renders a scene sheet of TUI states and screenshots it, so visual regressions are reviewable.
- **How it works:** `run.mjs` sets `COLORTERM=truecolor` and `FORCE_COLOR=3` itself (instead of POSIX `VAR=x cmd` assignments, which break under the Windows npm command shell — no `cross-env` needed), runs `render.tsx` through `tsx/cli`, then screenshots with Electron resolved from the install tree (the desktop workspace already ships it; a root `npm install` hoists it), overridable with `ELECTRON_BIN`.
- **Inputs / options:** `npm run visual`; env `ELECTRON_BIN`.
- **Outputs / side effects:** Rendered screenshots.
- **Config / env:** `ELECTRON_BIN`, `COLORTERM`, `FORCE_COLOR`.
- **Edge cases / guards:** Exits with the child's status; prints a message when Electron is not installed in the tree.
- **Rebuild notes:** Borrow heavyweight dev tooling from a sibling workspace rather than declaring a second copy.

### Benchmarks and profiling scripts  `id: tui.bench-scripts`
- **Surface:** Core
- **Where:** `ui-tui/scripts/`.
- **What it does:** Measures the two hottest render paths and profiles the whole app.
- **How it works:** `bench-history-scroll.tsx` (transcript scrolling), `bench-streaming-md.tsx` (incremental markdown), `billing-fixtures.tsx` (billing-overlay fixtures for visual review), `profile-tui.mjs` (process profiling).
- **Inputs / options:** run with `tsx`/`node`.
- **Outputs / side effects:** Timing output.
- **Config / env:** n/a.
- **Edge cases / guards:** n/a.
- **Rebuild notes:** Benchmark the paths whose complexity you deliberately optimised, so a regression is measurable rather than felt.

### Vendored Ink fork (`@hermes/ink`)  `id: tui.hermes-ink`
- **Surface:** Core
- **Where:** `ui-tui/packages/hermes-ink/`, imported everywhere as `@hermes/ink`.
- **What it does:** A forked, terminal-focused React renderer with the capabilities upstream Ink lacks: mouse, selection, alternate screen, scroll boxes, a full DEC/OSC parser, and a differential screen writer.
- **How it works:** Notable modules — reconciler (`src/ink/reconciler.ts`, `root.ts`, `renderer.ts`, `render-to-screen.ts`, `render-node-to-output.ts`, `optimizer.ts`, `frame.ts`); layout (`layout/engine.ts`, `layout/node.ts`, `layout/geometry.ts`, `layout/yoga.ts`, plus a TypeScript yoga shim in `native-ts/yoga-layout/`); terminal I/O (`termio/{parser,tokenize,csi,osc,sgr,dec,esc,ansi,types}.ts`, `terminal.ts`, `terminal-querier.ts`, `terminal-background.test.ts`, `parse-keypress.ts`); events (`events/{dispatcher,emitter,event,event-handlers,keyboard-event,mouse-event,paste-event,focus-event,terminal-focus-event,resize-event,click-event,input-event,terminal-event}.ts`); components (`App.tsx`, `AlternateScreen.tsx`, `Box.tsx`, `Text.tsx`, `Button.tsx`, `Link.tsx`, `Newline.tsx`, `NoSelect.tsx`, `RawAnsi.tsx`, `ScrollBox.tsx`, `Spacer.tsx`, `ErrorOverview.tsx`, plus the `AppContext`/`StdinContext`/`ClockContext`/`TerminalSizeContext`/`TerminalFocusContext`/`CursorAdvanceContext`/`CursorDeclarationContext` contexts); hooks (`use-input`, `use-app`, `use-stdin`, `use-stdout`, `use-interval`, `use-animation-frame`, `use-selection`, `use-search-highlight`, `use-cursor-advance`, `use-declared-cursor`, `use-external-process`, `use-tab-status`, `use-terminal-focus`, `use-terminal-title`, `use-terminal-viewport`); text (`wrap-text.ts`, `wrapAnsi.ts`, `measure-text.ts`, `stringWidth.ts`, `widest-line.ts`, `line-width-cache.ts`, `squash-text-nodes.ts`, `bidi.ts`, `tabstops.ts`, `sliceAnsi.ts`, `colorize.ts`, `searchHighlight.ts`); infrastructure (`log-update.ts`, `screen.ts`, `output.ts`, `cursor.ts`, `clearTerminal.ts`, `hit-test.ts`, `focus.ts`, `selection.ts`, `lru.ts`, `node-cache.ts`, `cache-eviction.ts`, `instances.ts`, `devtools.ts`, `warn.ts`, `supports-hyperlinks.ts`, `hyperlinkHover.ts`, `render-border.ts`, `ansi-transition.ts`, `useTerminalNotification.ts`, `terminal-focus-state.ts`, `styles.ts`, `get-max-width.ts`, `constants.ts`, `dom.ts`).
- **Inputs / options:** `ink.render(node, {exitOnCtrlC, onFrame, onHyperlinkClick})`; the exported components and hooks; `forceRedraw(stream)`, `withInkSuspended(fn)`, `terminalBackgroundHex()`, `stringWidth(s)`, `wrapAnsi(...)`, `MouseTrackingMode`, `FrameEvent`, `Key`, `ScrollBoxHandle`.
- **Outputs / side effects:** The rendered terminal frame.
- **Config / env:** n/a.
- **Edge cases / guards:** Extensively regression-tested in place — `app-mouse.test.ts`, `app-mouse-watchdog.test.ts`, `app-rawmode-mouse.test.ts`, `app-stdin-recovery.test.ts`, `absolute-in-zero-height-box.test.tsx`, `ansi-transition.test.ts`, `ink-backpressure.test.ts`, `ink-cursor-advance.test.ts`, `ink-focus-redraw.test.ts`, `ink-resize.test.ts`, `osc-response-chain.test.ts`, `parse-keypress*.test.ts`, `render-border.test.ts`, `scrollBoxRendererBounds` (in the app suite), `selection.test.ts`, `terminal.test.ts`, `wrap-text.test.ts`, `log-update.test.ts`, `hit-test.test.ts`, `colorize.test.ts`, `cmd-shortcuts.test.ts`, `termio/{osc,parser,tokenize}.test.ts`, `Text.test.ts`, `App.focus.test.tsx`.
- **Rebuild notes:** A terminal UI at this level of interactivity needs its own renderer — mouse hit-testing, selection, and differential screen writing are not bolt-ons.

### TUI test suite  `id: tui.tests`
- **Surface:** Core
- **Where:** `ui-tui/src/__tests__/` (about 110 vitest files) plus the in-package Ink tests.
- **What it does:** Locks in the behaviours documented across this shard.
- **How it works:** `npm test` runs `vitest run`. Notable files by area — input/composer: `textInput*.test.ts` (burst input, cursor source of truth, cut, fast echo, kill-line, line-kill, line-nav, pass-through, return action, return burst, right-click, submit-clear, word-delete, wrap), `useInputHandlers`, `inputSelectionClipboard`, `imeVietnameseTelex`, `composerHighlights`, `useComposerState`, `completionApply`, `useCompletion`; slash: `createSlashHandler`, `asCommandDispatch`, `slashParity`, `inlineSlashSkill`, `journeyCommand`, `wakeCommand`, `topupCommand`, `subscriptionCommand`, `usageCommand`; rendering: `markdown`, `streamingMarkdown`, `mathUnicode`, `syntax`, `messageLine`, `blockLayout`, `details`, `reasoning`, `thinkingLiveCollapse`, `thinkingMoaReferenceVisibility`, `emoji`, `charts`, `loaders`, `theme`, `themeBoot`, `forceTruecolor`; scrolling/virtualisation: `scroll`, `viewport`, `viewportStore`, `virtualHeights`, `virtualHistoryClamp`, `virtualHistoryOffsetCache`, `useVirtualHistoryHeights`, `wheelAccel`, `precisionWheel`, `scrollBoxRendererBounds`; session/turn: `turnStore`, `turnControllerNotice`, `turnControllerTodos`, `useSessionLifecycle`, `sessionResumeView`, `activeSessionSwitcher`, `stateIsolation`, `spawnHistoryStore`, `subagentTree`, `moaProgressActivity`, `orchestratorPromptSession`; gateway: `gatewayClient`, `gatewayRecovery`, `createGatewayEventHandler`, `rpc`, `parentLog`, `memoryMonitor`, `gracefulExit`, `bundleNoAsyncEsmDeadlock`; chrome: `appChromeStatusRule`, `appChromeStatusRuleDevCredits`, `appChromeBlockedTimers`, `statusRule`, `statusBarTicker`, `brandingMcpCount`, `helpHint` (via `constants`), `petPane`, `petPolling`, `widgetGrid`, `widgetGridComponent`, `widgetSdk`, `userWidgets`, `weatherApp`, `overlayPrimitives`, `modelPicker`, `subscriptionOverlay`, `billingStepUp`, `approvalAction`, `prompt`, `queueSubmission`, `submissionCore`, `useQueue`, `useConfigSync`, `useBatteryPoll`, `terminalModes`, `terminalParity`, `terminalSetup`, `termux`, `termuxComposerLayout`, `osc52`, `clipboard`, `externalLink`, `platform`, `providers`, `paths`, `attachments`, `messages`, `mergeUsageStable`, `voiceSubmitModeRenderer`, `cursorDriftRegression`.
- **Inputs / options:** `npm test`, `npm run test:watch`, `npm run check`.
- **Outputs / side effects:** Test results.
- **Config / env:** `VITEST` / `NODE_ENV=test` disable the theme boot cache so tests never touch a real `~/.hermes`.
- **Edge cases / guards:** The TS suite has no `HERMES_HOME` isolation fixture, so modules that write under the home directory (notably `themeBoot.ts`) self-disable under `VITEST` / `NODE_ENV=test` rather than relying on the test runner.
- **Rebuild notes:** Every non-obvious behaviour in this shard has a named regression test — that is what makes the subtle rules (Enter vs. completion, gap rhythm, occlusion gating) safe to keep.

### `ui-tui/README.md` — known drift  `id: tui.readme-drift`
- **Surface:** Docs
- **Where:** `ui-tui/README.md`.
- **What it does:** Documents the TUI for contributors — architecture, hotkey tables, interaction rules.
- **How it works:** Accurate for: the entry point and TTY guard, the `python -m tui_gateway.entry` spawn and interpreter resolution order (`HERMES_PYTHON` → `PYTHON` → `$VIRTUAL_ENV/bin/python` → `./.venv/bin/python` → `./venv/bin/python` → `python3` / `python` on Windows), the newline-delimited JSON-RPC transport with stderr captured into an in-memory log ring, the `src/app/` module map, the completion debounce of 60 ms (`/` → `complete.slash`; a trailing token starting with `./`, `../`, `~/`, `/` or `@` → `complete.path`), the queue rules (plain text queues while busy; slash and `!cmd` execute immediately; the queue auto-drains after each assistant response unless an item is being edited; queued drafts keep raw `!cmd` / `{!cmd}` text until sent), `useLongRunToolCharms` firing for tools running longer than 8 s, `spawnHistoryStore` keeping the last 10 finished fan-out snapshots, `gatewayRecovery`'s 3-attempt / 60 s respawn budget, `useConfigSync`'s 5 s config-mtime poll, and input history in `~/.hermes/.hermes_history` (or under `HERMES_HOME`).
- **Inputs / options:** n/a.
- **Outputs / side effects:** n/a.
- **Config / env:** n/a.
- **Edge cases / guards:** Verified DRIFT against the source as of v2026.8.31, listed so a reader does not trust it: (1) it lists `commands/billing.ts` and `commands/credits.ts` in the slash registry, but the actual files are `commands/topup.ts` and `commands/subscription.ts` and the registration order is core → topup → session → subscription → ops → wake → setup → debug (`src/app/slash/registry.ts:11-20`); (2) it says `Ctrl+L` starts a new session — in the shipped code `Cmd/Ctrl+L` is redraw/repaint (`useInputHandlers.ts:673`) and `/clear` is the new-session path; (3) it says `PgUp`/`PgDn` are "left to the terminal emulator; the TUI does not handle them" — the TUI does handle them, scrolling half a viewport (`useInputHandlers.ts:539-546`); (4) it lists approval quick-picks as `o`, `s`, `a`, `d` — the shipped prompt uses digits `1`..`N` (`prompts.tsx:63-67`); (5) it says the resume picker takes `1-9` quick-picks, while the live session switcher's bindings are `Ctrl+N`/`Ctrl+R`/`Ctrl+D`/`Tab`/`Enter`/`Esc`/`d`; (6) it describes clarify prompts as having "no dedicated cancel shortcut", but `Esc` cancels (and exits typing mode first) in `prompts.tsx:220-231`.
- **Rebuild notes:** Generate contributor hotkey tables from `content/hotkeys.ts` and the key handlers rather than maintaining a second prose copy.

### Gateway crash recovery budget  `id: tui.gateway-recovery`
- **Surface:** Core
- **Where:** invisible; a crash-looping gateway ends in the inert "gateway exited" state instead of a spawn storm.
- **What it does:** Caps respawn-and-resume attempts after a gateway death so a startup crash-loop cannot spawn-storm the machine.
- **How it works:** `ui-tui/src/app/gatewayRecovery.ts` — `GATEWAY_RECOVERY_LIMIT = 3` attempts within a sliding `GATEWAY_RECOVERY_WINDOW_MS = 60_000`. `planGatewayRecovery(liveSid, recoverSid, attempts, now)` returns `{attempts, recover, sid}`: `sid = liveSid ?? recoverSid` (the pending recovery target carried across a respawn that died before `gateway.ready`, so a startup crash-loop keeps retrying the SAME session instead of stranding it after one attempt), `recent = attempts.filter(t => now - t < WINDOW)`, `recover = Boolean(sid) && recent.length < LIMIT`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** A respawn + `session.resume`, or the inert exited state.
- **Config / env:** n/a.
- **Edge cases / guards:** Deliberately pure (no refs, no UI) so the bound — including the crash-loop case — is unit-testable (`gatewayRecovery.test.ts`).
- **Rebuild notes:** Budget your retries in a sliding window and keep the decision a pure function.

### Long-running tool charm timer  `id: tui.long-run-timer`
- **Surface:** TUI
- **Where:** the activity trail, e.g. `still cooking… (read_file · 12s)`.
- **What it does:** After a tool has been running for 8 seconds, emits a rotating reassurance line naming the tool and its elapsed time.
- **How it works:** `ui-tui/src/app/useLongRunToolCharms.ts` — `DELAY_MS = 8_000`; the message is `` `${pick(LONG_RUN_CHARMS)} (${toolTrailLabel(tool.name)} · ${Math.round((now - tool.startedAt) / 1000)}s)` ``.
- **Inputs / options:** n/a.
- **Outputs / side effects:** An activity-trail line.
- **Config / env:** `display.sections.activity` (hidden by default, so this is opt-in).
- **Edge cases / guards:** Nothing fires under 8 s.
- **Rebuild notes:** Name the tool and the elapsed seconds — "still working" alone is not reassuring.

### Completion debounce and trigger detection  `id: tui.completion-trigger`
- **Surface:** Core
- **Where:** every keystroke in the composer.
- **What it does:** Decides which completion source to query and rate-limits the query.
- **How it works:** `ui-tui/src/hooks/useCompletion.ts:163` debounces at 60 ms. Input starting with `/` queries `complete.slash {text}` (`tui_gateway/methods_complete.py:331`); a trailing token starting with `./`, `../`, `~/`, `/` or `@` queries `complete.path {word}` (`methods_complete.py:42`, which also serves `@<profile>` agent-profile mentions). Inline `/skill` references anywhere in prose are detected by `inlineSlashTrigger()`.
- **Inputs / options:** n/a.
- **Outputs / side effects:** The completion menu.
- **Config / env:** n/a.
- **Edge cases / guards:** Both completion RPCs run on the gateway thread pool because they can block for seconds (`git ls-files` + whole-repo fuzzy ranking; first-call prompt_toolkit imports + a skill-dir scan).
- **Rebuild notes:** Pick the completion source from the token shape, not from the whole line.

### Input history file  `id: tui.input-history`
- **Surface:** Core / Config
- **Where:** `$HERMES_HOME/.hermes_history` (default `~/.hermes/.hermes_history`).
- **What it does:** Persists submitted prompts so `↑` recalls them across launches.
- **How it works:** `ui-tui/src/lib/history.ts:6-7` — `dir = process.env.HERMES_HOME ?? join(homedir(), '.hermes')`, `file = join(dir, '.hermes_history')`. `cycleHistory` in `useInputHandlers.ts` stashes the live draft in `historyDraftRef` before the first step back and restores it when walking past the newest entry.
- **Inputs / options:** `↑` / `↓`; `Esc Esc` pushes the discarded draft into history.
- **Outputs / side effects:** One file.
- **Config / env:** `HERMES_HOME`.
- **Edge cases / guards:** Shared with the classic CLI, so history carries across front-ends.
- **Rebuild notes:** n/a.

---

## Handoffs

- `hermes_cli/main.py` argument parsing and the full `hermes --help` flag surface belong to the CLI shards (`cli-*`); only the TUI-relevant flags are covered here.
- The dashboard's `/api/pty`, `/api/ws` and Chat tab implementation live in `hermes_cli/web_server.py` and `web/` — shard `web-*`.
- The Electron desktop app (`apps/desktop`) consumes most of the `tui_gateway` RPCs documented in §11 (profiles, projects, pets, MCP servers, groups) — its UI surface belongs to the `desktop-*` shards.
- `@hermes/shared` (`apps/shared`, e.g. `charge-settlement`, `skin`) is shared with the desktop and web surfaces — its own shard should own it.
- The classic CLI slash commands and their gateway handlers (`gateway/slash_commands.py`, `hermes_cli/commands.py` `COMMAND_REGISTRY`) are the source of the catalog the TUI renders — shards `gw-slash` / `cli-*`.
- `hermes_cli/clipboard.py`, `hermes_cli/curses_ui.py` and `hermes_cli/voice.py` are the CLI-side mirrors of TUI modules (clipboard fallback order, fuzzy matcher, `voice.record_key` normalisation) — shards `cli-*`.
- Config keys named here (`display.*`, `voice.*`, `wake_word.*`, `browser.cdp_url`, `approvals.mcp_reload_confirm`) are catalogued in shards `config-a` / `config-b`.
- Every environment variable named here is catalogued in shard `env-vars`.
- Skins as data (built-in skin definitions, the skin file format) belong to the skins/config shards; only the TUI's consumption of them is covered here.
- The `pet` / petdex engine (spritesheets, generation backends, the gallery source) is a backend feature — the TUI only renders it.
- Hosted rooms / groups as a product feature (invitations, membership, the desktop UI) belong elsewhere; §11 and `tui.gw-hosted-rooms` cover only the gateway RPC surface.
