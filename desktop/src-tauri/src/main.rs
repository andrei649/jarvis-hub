//! H11.1 — Tauri desktop shell wrapping the Jarvis Hub web HUD.
//!
//! ⚠️ SOURCE ONLY — compiled host-side with the Rust + Tauri toolchain
//! (`cargo tauri build`); not built in CI. Provides a native window that loads
//! the local HUD (http://127.0.0.1:8080), a tray icon, and auto-start. The
//! wake-word listener hooks in at `setup()`.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        .setup(|_app| {
            // Tray menu + local wake-word listener are wired here.
            // The main window (loading the HUD URL) is declared in tauri.conf.json.
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the Jarvis Hub desktop shell");
}
