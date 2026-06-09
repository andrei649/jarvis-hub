# Jarvis Hub — Desktop shell (H11.1, Tauri v2)

A thin native desktop wrapper around the existing web HUD — **no new backend**.
It opens a native window pointed at the local server (`http://127.0.0.1:8080`),
adds a tray icon, and supports auto-start.

> **Source only.** This is built **host-side** with the Rust + Tauri toolchain;
> it is intentionally not built in CI (no Rust runner). The Python backend and
> its tests are unaffected.

## Prerequisites (host)
- Rust (`rustup`) + the [Tauri v2 prerequisites](https://v2.tauri.app/start/prerequisites/)
- `cargo install tauri-cli --version '^2'`
- An app icon at `src-tauri/icons/icon.png`

## Run / build
```bash
# 1. start the Jarvis backend (serves the HUD on :8080)
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080

# 2. dev run
cd desktop && cargo tauri dev

# 3. package a native installer (Win/macOS/Linux)
cd desktop && cargo tauri build
```

## Layout
- `src-tauri/tauri.conf.json` — window (loads the HUD URL), tray, bundle config
- `src-tauri/src/main.rs` — app entry; tray + wake-word listener hook in `setup()`
- `src-tauri/Cargo.toml` — Tauri v2 + autostart plugin
- `src-tauri/build.rs` — Tauri build script

Alternative to running the HUD in a browser; complements the Expo mobile client (H18).
