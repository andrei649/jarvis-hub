# Nerva desktop shell and floating chat (H178)

The Tauri host loads the existing local HUD at `http://127.0.0.1:8080/v2/`.
Start your Nerva backend first. The desktop app does not start a backend or a daemon.

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
Only `desktop_action` (finite show/hide/reset/handoff/drag/resize) and
`desktop_capabilities` are exposed; no generic filesystem, shell, navigation, capture
or accessibility commands are granted. New windows and navigation outside `/v2` are refused.

## Support and remaining work

Host compilation and native UI validation were performed on macOS; Windows/Linux
packaging and physical monitor disconnect/reconnect remain unverified. One native
capability object identifies Cocoa, Win32, X11 or Wayland. Wayland placement and
topmost requests are explicitly unsupported; the compositor controls them. Other
platforms request topmost but cannot promise priority over exclusive fullscreen apps.
Transparency, native frost, click-through, game-overlay watching, global shortcuts,
move-to-pointer and underlying-window context capture are not implemented. No new
autostart or wake-word service is installed. H178 remains partial against the full
Hermes overlay surface, and this feature is intentionally desktop-only.
