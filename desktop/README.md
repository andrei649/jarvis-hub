# Nerva desktop shell and floating chat (H178)

The Tauri host loads the existing local HUD at `http://127.0.0.1:8080/v2/`.

## The hub (H171)

The app owns the hub it starts, and only that one. On launch it:

1. reads its ownership record (`hub-ownership.txt` in the app's data directory, mode
   0600: pid, the process's start time, the interpreter path, the app's own pid and a
   per-launch nonce that only labels the launch in logs). If that process is still
   alive **with the recorded start time and executable**, it is the hub this app
   started before (the app crashed or was killed): the app adopts it again and never
   kills a healthy one. A record whose process is gone, or whose pid now belongs to
   something else, is dropped and touches nothing. A hub another running copy of the
   app owns is used, not adopted.
2. if something already listens on `127.0.0.1:8080` (you ran `start.sh`, a service),
   the app uses it and never stops it.
3. otherwise starts one: `<checkout>/.venv/bin/python serve.py` (Windows:
   `.venv\Scripts\python.exe`). The checkout is **named, never searched for**:
   - `NERVA_DESKTOP_HUB_DIR` (an absolute path), else
   - the one line of `hub-dir.txt` in the app's config folder (Linux
     `~/.config/com.jarvis.hub/`, macOS `~/Library/Application Support/com.jarvis.hub/`,
     Windows `%APPDATA%\com.jarvis.hub\`), else
   - for a development run only, the checkout the app was built in
     (`<checkout>/desktop/src-tauri/target/{debug,release}/<exe>`).

   The working directory is never used and nothing else above the app is searched (an
   AppImage runs from a mount under the shared temp folder, where anyone can plant a
   `serve.py`). Before starting, on Linux and macOS, the checkout and every folder above
   it must belong to you or root and be writable by nobody else (group or world; `/tmp`
   is refused); `serve.py`, `agents/`, `.venv` and `.venv/bin` must stay inside the
   checkout; and the interpreter `.venv/bin/python` points to (often the system or a
   pyenv Python) must pass the same ownership check. Windows ACLs are not inspected.
   If nothing qualifies, nothing is started: the app says why (stderr and a
   notification) and waits for a hub you start. Without a `.venv` it refuses to guess a
   system Python (run `install.sh` first). `JARVIS_HUD=v2` is set as `start.sh` does,
   unless you chose a HUD. Output goes to `hub.log` in the app's log directory.
4. opens the HUD windows only once `GET /readyz` answers 200 (up to two minutes). An
   adopted hub that never becomes ready is stopped (reaped) and a fresh one started.

Quitting stops the hub the app owns (SIGTERM, then a kill after ten seconds). Before
each signal it checks again that the live process still has the recorded start time and
executable; for a hub adopted from an earlier launch a changed start time means the hub
is gone and nothing is signalled. A hub the app did not start keeps running.
`NERVA_DESKTOP_HUB=external` makes the app never start a hub and only wait for yours.
The app reads no hub credential: the hub reads its own `.env`, readiness is the
unauthenticated `/readyz`, and the HUD signs in as in a browser. The hub must listen on
port 8080 (the HUD origin is fixed).

## Quick Entry (H179)

A global hotkey, `CommandOrControl+Shift+Space` by default, shows the floating chat with
the cursor in its composer, from any app; pressing it again while the chat is in front
hides it. Nothing is sent until you press Enter, through the chat's normal path.
`NERVA_DESKTOP_QUICK_ENTRY=Control+Alt+K` picks another accelerator and `=off` turns it
off. An accelerator needs CommandOrControl, Control, Alt or Super (Shift alone would
capture typing) and cannot use Escape. When another program already holds it, or on
Wayland (compositors do not grant global shortcuts), Quick Entry stays off and the app
says so on stderr; `desktop_capabilities` reports `globalShortcut` truthfully.

## Decision notifications (H181)

The main HUD window watches the pending approvals it can already read with your
session (`GET /autonomy/approvals`, every 20 s) and asks the shell (`desktop_notify`)
to show a native notification for each new one, unless the HUD is already in front.
Requests are validated (one kind, a bounded id, one bounded line of text with no
control or bidi characters and no `<`, `>` or `&`, which freedesktop servers read as
markup) and shown once per approval, at most six a minute and at most eight waiting for
a click; the rest stay in the inbox. The notification **only opens** the
Decision Inbox: clicking it, or its single "Review in Nerva" action on Linux, brings the
main window to `/v2/console/decision-inbox`, where you approve or deny on the normal
card through the hub's normal decision route. There is no approve or deny button on a
notification. macOS and Windows show the notification without a click route yet.
`NERVA_DESKTOP_NOTIFICATIONS=off` silences them.

## `nerva://` links (H183)

The installer registers the `nerva` scheme (Linux and a Windows dev build also register
it at runtime); a second launch hands its link to the running app (single instance).
Every link is untrusted input: ASCII only, at most 34 KB, one known target, only that
target's parameters, each validated. A link only opens a HUD page in the main window:

- `nerva://open/chat`, `nerva://open/decision-inbox`, `nerva://open/mcp`
- `nerva://mcp/install?name=<catalog name>` opens the MCP install card for a reviewed
  catalog entry;
- `nerva://mcp/install?name=<name>&config=<base64 JSON>` opens it for a vendor's server
  (the Cursor/Hermes `config=` shape, at most 32 KB).

The install card shows exactly what would run (command line or HTTPS endpoint, env,
secret names) and installs only after you tick "I have read what will run" and press
Install; the hub writes only the plan whose digest was shown. A link never installs,
connects or starts anything, and the shell never logs a link's contents.

## Use

Choose **Float chat** in the main HUD or tray menu. The floating window is frameless,
resizable and requests always-on-top where supported. Drag **NERVA · CHAT** to move it,
drag the bottom-right corner to resize, or choose **Reset layout** to recover it.
**Hide chat** and the native close action hide the window; the tray brings it back.
**Open in app** focuses the normal Chat view. Main-window close also hides to tray;
choose **Quit Nerva** in the tray or the normal application Quit command to exit.

Both windows use the same origin, persistent webview data store, existing HUD token
storage, `/memory` and `/chat/stream`. There is no second backend or session ID.
On focus/handoff and after another window completes a turn, persisted history refreshes;
a pending refresh cannot replace a streaming turn. Hidden windows keep a running turn.
Unsent composer drafts remain in their original window; they are not transferred by handoff.

Layout (physical coordinates and size) is stored in `floating-geometry.json` inside
Tauri's application config directory. Every show/reset clamps against current monitor
work areas; corrupt files fall back to default dimensions, scaled for Retina/DPI.
No conversation or token is written to this layout file.

## Host build

Install Rust and the platform prerequisites for Tauri v2. The checked-in Cargo.lock
pins dependencies and the icon is reused from the existing mobile asset.

```sh
cd desktop/src-tauri
cargo test --jobs 2
cargo check --jobs 2
cargo run --jobs 2
# Optional installer packaging with the separately installed Tauri CLI:
cargo tauri build
```

Build the HUD after frontend edits with `npm --prefix frontend run build` from the
repository root. Its tracked output is served by the backend. A development build
uses Tauri's local devUrl classification; release uses the explicitly scoped HTTP
origin capability. Both independently check the exact HUD URL and expected window.
Only `desktop_action` (finite show/hide/reset/handoff/drag/resize),
`desktop_capabilities`, `desktop_listening` (a HUD window reports one of five
listening states for the tray; it cannot open or close a mic) and `desktop_notify`
(main window only; see above) are exposed; no generic filesystem, shell, navigation,
capture or accessibility commands are granted. The global-shortcut, deep-link and
single-instance plugins are driven from Rust only: the webview gets none of their
JavaScript APIs. New windows are refused. The main window allows
only registered HUD modes, console index and console panels; the floating window allows
only `/v2`, `/v2/`, `/v2/chat` and `/v2/chat/`. Assets and unknown `/v2/*` paths are refused.

**Listening indicator (H222).** The tray icon says whether Nerva is listening while the
HUD windows are hidden or unfocused: the loudest state any HUD window reports (the hub's
voice pipeline and satellites, from `GET /api/voice/listening/stream`, or that window's
own mic). An open mic shows a menu-bar title — `● listening` or `○ wake word` — on macOS
(and next to the icon on Linux; Windows has no tray titles); the tooltip names the state
on macOS and Windows (Linux trays have no tooltip).

**Background throttling (H182).** Both windows run with webview background throttling
off, so a hidden HUD keeps reading a streaming reply (macOS 14+ honours the policy).
`NERVA_DESKTOP_BACKGROUND_THROTTLING=throttle` or `=suspend` asks for it back.

The native allowlist is generated from the frontend route registries. After adding or
removing a mode/panel, run from the repository root (Node 22.6+):

```sh
node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs
node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs --check
```

Commit `desktop/src-tauri/hud-routes.json` with the route change. The frontend
`desktop-route-sync` test checks the entire allowlist against current registry entries;
Rust tests exercise the real `tauri::Url` guard for every path and both window labels.

## Support and remaining work

Host compilation and native UI validation were performed on macOS; Windows/Linux
packaging and physical monitor disconnect/reconnect remain unverified. One native
capability object identifies Cocoa, Win32, X11 or Wayland. Wayland placement and
topmost requests are explicitly unsupported; the compositor controls them. Other
platforms request topmost but cannot promise priority over exclusive fullscreen apps.
Transparency, native frost, click-through, game-overlay watching, move-to-pointer and
underlying-window context capture are not implemented. No new autostart or wake-word
service is installed.

G22 remaining work: a per-profile hub pool (one hub per `JARVIS_PROFILE`, LRU eviction,
idle reaper) and a WebSocket handshake probe (H171); a persisted Quick Entry setting in
the HUD instead of an environment variable (H179); notification click routes on macOS
and Windows, per-kind toggles, a completion sound and a test button in a Notifications
settings page (H181); a separate dev scheme (H183). `cargo test` and `cargo clippy`
ran on Linux with the WebKitGTK development packages; the native windows, tray,
hotkey, notifications and scheme registration were not exercised on a desktop. H178 remains partial against the full
Hermes overlay surface, and this feature is intentionally desktop-only.
