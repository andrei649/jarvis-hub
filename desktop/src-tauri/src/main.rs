//! Native local HUD and bounded floating-chat window management.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod deeplink;
mod geometry;
mod hotkey;
mod hub;
mod hub_policy;
mod indicator;
mod notify;
mod policy;
mod throttling;
use geometry::{recover_scaled, Rect};
use policy::Action;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::utils::config::BackgroundThrottlingPolicy;
use tauri::{
    Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// The HUD's origin; every window and every page the shell opens is on it.
const HUD_ORIGIN: &str = "http://127.0.0.1:8080";

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct Capabilities {
    compositor: &'static str,
    positioning: bool,
    always_on_top: bool,
    transparency: bool,
    native_frost: bool,
    click_through: bool,
    global_shortcut: bool,
    game_overlay: bool,
    move_to_pointer: bool,
}
impl Capabilities {
    fn detect() -> Self {
        let wayland = cfg!(target_os = "linux")
            && (std::env::var("XDG_SESSION_TYPE").is_ok_and(|v| v == "wayland")
                || std::env::var_os("WAYLAND_DISPLAY").is_some());
        Self {
            compositor: if cfg!(target_os = "macos") {
                "Cocoa"
            } else if cfg!(target_os = "windows") {
                "Win32"
            } else if wayland {
                "Wayland"
            } else {
                "X11"
            },
            positioning: !wayland,
            always_on_top: !wayland,
            transparency: false,
            native_frost: false,
            click_through: false,
            global_shortcut: false,
            game_overlay: false,
            move_to_pointer: false,
        }
    }
}
fn verify(window: &WebviewWindow) -> Result<(), String> {
    if policy::allowed(window.label(), &window.url().map_err(|e| e.to_string())?) {
        Ok(())
    } else {
        Err("Desktop actions require the local HUD window".into())
    }
}
#[tauri::command]
fn desktop_capabilities(
    window: WebviewWindow,
    caps: tauri::State<Capabilities>,
    shell: tauri::State<Shell>,
) -> Result<Capabilities, String> {
    verify(&window)?;
    let mut caps = caps.inner().clone();
    caps.global_shortcut = shell.quick_entry.load(Ordering::SeqCst);
    Ok(caps)
}

/// What the shell holds beyond the windows: whether the HUD is open yet, a page asked
/// for before it was (a link that launched the app), Quick Entry, and the notifications
/// already shown.
#[derive(Default)]
struct Shell {
    windows_open: AtomicBool,
    pending: Mutex<Option<String>>,
    quick_entry: AtomicBool,
    seen: Mutex<notify::Seen>,
}

/// Bring the main window to a HUD page (`/v2/...`). The page must pass the same route
/// policy as a navigation the window makes itself; before the HUD is open it waits.
fn open_hud(app: &tauri::AppHandle, path: &str) -> Result<(), String> {
    let url: tauri::Url = format!("{HUD_ORIGIN}{path}")
        .parse()
        .map_err(|_| "not a HUD page".to_string())?;
    if !policy::allowed("main", &url) {
        return Err("not a HUD page".into());
    }
    let shell = app.state::<Shell>();
    if !shell.windows_open.load(Ordering::SeqCst) {
        *shell.pending.lock().unwrap() = Some(path.to_string());
        return Ok(());
    }
    let main = app
        .get_webview_window("main")
        .ok_or("Main window unavailable")?;
    main.navigate(url).map_err(|e| e.to_string())?;
    main.show().map_err(|e| e.to_string())?;
    main.unminimize().map_err(|e| e.to_string())?;
    main.set_focus().map_err(|e| e.to_string())
}

/// H183: a `nerva://` link opens a HUD page and nothing else. The link is untrusted;
/// only a refusal reason is logged, never the link (it can be long and is not ours).
fn handle_link(app: &tauri::AppHandle, raw: &str) {
    match deeplink::parse(raw) {
        Ok(link) => {
            if let Err(e) = open_hud(app, &deeplink::hud_path(&link)) {
                eprintln!("nerva:// link not opened: {e}");
            }
        }
        Err(why) => eprintln!("nerva:// link refused: {why}"),
    }
}

/// H181: a HUD window that saw a new decision asks the shell to tell the owner. The
/// notification only opens the Decision Inbox; nothing is approved or denied from it.
#[tauri::command]
fn desktop_notify(
    window: WebviewWindow,
    shell: tauri::State<'_, Shell>,
    kind: String,
    id: String,
    title: String,
    body: String,
) -> Result<bool, String> {
    verify(&window)?;
    if window.label() != "main" {
        return Err("Notifications come from the main HUD window".into());
    }
    if !notify::enabled(std::env::var(notify::ENV).ok().as_deref()) {
        return Ok(false);
    }
    let request = notify::validate(&kind, &id, &title, &body)?;
    if !shell.seen.lock().unwrap().first(&request) {
        return Ok(false);
    }
    // The owner is looking at the HUD already: the card is in front of them.
    if window.is_visible().unwrap_or(false) && window.is_focused().unwrap_or(false) {
        return Ok(false);
    }
    show_notification(window.app_handle().clone(), request);
    Ok(true)
}

fn show_notification(app: tauri::AppHandle, request: notify::Request) {
    let mut note = notify_rust::Notification::new();
    note.appname("Nerva")
        .summary(&request.title)
        .body(&request.body);
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        // freedesktop notifications carry actions and report the click; elsewhere the
        // notification is informational and the tray and HUD are the way in.
        note.action("default", notify::ACTION_REVIEW_LABEL);
        for (id, label) in notify::ACTIONS {
            note.action(id, label);
        }
        let path = request.kind.hud_path();
        std::thread::spawn(move || match note.show() {
            Ok(handle) => handle.wait_for_action(|action| {
                if action == "default" || action == notify::ACTION_REVIEW {
                    let app2 = app.clone();
                    let _ = app.run_on_main_thread(move || {
                        if let Err(e) = open_hud(&app2, path) {
                            eprintln!("Decision Inbox not opened: {e}");
                        }
                    });
                }
            }),
            Err(e) => eprintln!("Notification not shown: {e}"),
        });
    }
    #[cfg(not(all(unix, not(target_os = "macos"))))]
    {
        let _ = app;
        std::thread::spawn(move || {
            if let Err(e) = note.show() {
                eprintln!("Notification not shown: {e}");
            }
        });
    }
}

/// H179: the Quick Entry hotkey toggles the floating chat with its composer focused.
fn quick_entry(app: &tauri::AppHandle) {
    let Some(floating) = app.get_webview_window("floating") else {
        return; // the HUD is not open yet
    };
    let open = floating.is_visible().unwrap_or(false) && floating.is_focused().unwrap_or(false);
    let result = if open {
        action(app, Action::Hide)
    } else {
        action(app, Action::Show).and_then(|_| {
            floating
                .eval("window.dispatchEvent(new Event('nerva-desktop-quick-entry'))")
                .map_err(|e| e.to_string())
        })
    };
    if let Err(e) = result {
        eprintln!("Quick Entry failed: {e}");
    }
}

fn register_quick_entry(app: &tauri::AppHandle) {
    let accelerator = match hotkey::parse(std::env::var(hotkey::ENV).ok().as_deref()) {
        Ok(Some(a)) => a,
        Ok(None) => return,
        Err(why) => {
            eprintln!("{why}");
            return;
        }
    };
    if app.state::<Capabilities>().compositor == "Wayland" {
        eprintln!("Quick Entry: Wayland compositors do not grant global shortcuts; it is off");
        return;
    }
    let registered =
        app.global_shortcut()
            .on_shortcut(accelerator.as_str(), |app, _shortcut, event| {
                if event.state == ShortcutState::Pressed {
                    quick_entry(app);
                }
            });
    match registered {
        Ok(()) => app
            .state::<Shell>()
            .quick_entry
            .store(true, Ordering::SeqCst),
        // Another program holds it: leave Quick Entry off rather than fight for it.
        Err(e) => eprintln!("Quick Entry: {accelerator} is not available ({e}); it is off"),
    }
}
fn geometry_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app
        .path()
        .app_config_dir()
        .map_err(|e| e.to_string())?
        .join("floating-geometry.json"))
}
fn save_geometry(window: &WebviewWindow) -> Result<(), String> {
    let pos = window.outer_position().map_err(|e| e.to_string())?;
    let size = window.inner_size().map_err(|e| e.to_string())?;
    let rect = Rect {
        x: pos.x as f64,
        y: pos.y as f64,
        width: size.width as f64,
        height: size.height as f64,
    };
    let path = geometry_path(window.app_handle())?;
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    let temp = path.with_extension("tmp");
    std::fs::write(&temp, serde_json::to_vec(&rect).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    std::fs::rename(temp, path).map_err(|e| e.to_string())
}
fn restore_geometry(window: &WebviewWindow, reset: bool) -> Result<(), String> {
    let saved = if reset {
        None
    } else {
        geometry_path(window.app_handle())
            .ok()
            .and_then(|p| std::fs::read(p).ok())
            .and_then(|s| serde_json::from_slice(&s).ok())
    };
    let monitors: Vec<_> = window
        .available_monitors()
        .map_err(|e| e.to_string())?
        .iter()
        .map(|m| {
            let r = m.work_area();
            Rect {
                x: r.position.x as f64,
                y: r.position.y as f64,
                width: r.size.width as f64,
                height: r.size.height as f64,
            }
        })
        .collect();
    let rect = recover_scaled(
        saved,
        &monitors,
        window.scale_factor().map_err(|e| e.to_string())?,
    );
    window
        .set_size(PhysicalSize::new(rect.width as u32, rect.height as u32))
        .map_err(|e| e.to_string())?;
    if window.app_handle().state::<Capabilities>().positioning {
        window
            .set_position(PhysicalPosition::new(rect.x as i32, rect.y as i32))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn action(app: &tauri::AppHandle, action: Action) -> Result<(), String> {
    let floating = app
        .get_webview_window("floating")
        .ok_or("Floating window unavailable")?;
    match action {
        Action::Show | Action::Reset => {
            restore_geometry(&floating, matches!(action, Action::Reset))?;
            floating.show().map_err(|e| e.to_string())?;
            floating.set_focus().map_err(|e| e.to_string())?;
        }
        Action::Hide => {
            save_geometry(&floating)?;
            floating.hide().map_err(|e| e.to_string())?;
        }
        Action::Handoff => {
            let main = app
                .get_webview_window("main")
                .ok_or("Main window unavailable")?;
            main.show().map_err(|e| e.to_string())?;
            main.unminimize().map_err(|e| e.to_string())?;
            main.eval("window.dispatchEvent(new Event('nerva-desktop-handoff'))")
                .map_err(|e| e.to_string())?;
            main.set_focus().map_err(|e| e.to_string())?;
            save_geometry(&floating)?;
            floating.hide().map_err(|e| e.to_string())?;
        }
        Action::Drag => floating.start_dragging().map_err(|e| e.to_string())?,
        Action::Resize => floating
            .as_ref()
            .window()
            .start_resize_dragging(tauri_runtime::ResizeDirection::SouthEast)
            .map_err(|e| e.to_string())?,
    }
    Ok(())
}
#[tauri::command]
fn desktop_action(window: WebviewWindow, action: Action) -> Result<(), String> {
    verify(&window)?;
    action_impl(&window, action)
}
/// H222: the tray icon's id, so the listening indicator can find it.
const TRAY_ID: &str = "nerva";
/// A HUD window reports whether Nerva is listening; the tray shows the loudest window's
/// state. Read-only: the tray only says it, nothing here opens or closes a mic.
#[tauri::command]
fn desktop_listening(
    window: WebviewWindow,
    board: tauri::State<'_, indicator::Board>,
    state: String,
) -> Result<(), String> {
    verify(&window)?;
    let shown = board.report(window.label(), indicator::parse(&state)?);
    let tray = window
        .app_handle()
        .tray_by_id(TRAY_ID)
        .ok_or_else(|| "tray icon unavailable".to_string())?;
    tray.set_tooltip(Some(shown.tooltip()))
        .map_err(|e| e.to_string())?;
    tray.set_title(shown.title()).map_err(|e| e.to_string())
}
fn action_impl(window: &WebviewWindow, requested: Action) -> Result<(), String> {
    if window.label() != "floating"
        && matches!(
            requested,
            Action::Drag | Action::Resize | Action::Hide | Action::Handoff
        )
    {
        return Err("This control belongs to the floating window".into());
    }
    action(window.app_handle(), requested)
}
/// Open the two HUD windows. Called once, after the hub answers `/readyz` (H171), so
/// the HUD never opens on a connection error while the hub is still starting.
fn open_windows(app: &tauri::AppHandle) -> tauri::Result<()> {
    if app.get_webview_window("main").is_some() {
        return Ok(());
    }
    // H182: a HUD in the background keeps reading a streaming reply.
    let throttle = match throttling::from_env() {
        throttling::Throttling::Disabled => BackgroundThrottlingPolicy::Disabled,
        throttling::Throttling::Throttle => BackgroundThrottlingPolicy::Throttle,
        throttling::Throttling::Suspend => BackgroundThrottlingPolicy::Suspend,
    };
    WebviewWindowBuilder::new(
        app,
        "main",
        WebviewUrl::External(format!("{HUD_ORIGIN}/v2/").parse().expect("HUD URL")),
    )
    .title("Nerva")
    .inner_size(1280., 820.)
    .background_throttling(throttle.clone())
    .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
    .on_navigation(|url| policy::allowed("main", url))
    .build()?;
    let floating = WebviewWindowBuilder::new(
        app,
        "floating",
        WebviewUrl::External(
            format!("{HUD_ORIGIN}/v2/?desktop=floating")
                .parse()
                .expect("HUD URL"),
        ),
    )
    .title("Nerva floating chat")
    .inner_size(420., 620.)
    .visible(false)
    .decorations(false)
    .resizable(true)
    .always_on_top(app.state::<Capabilities>().always_on_top)
    .background_throttling(throttle)
    .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
    .on_navigation(|url| policy::allowed("floating", url))
    .build()?;
    let handle = app.clone();
    floating.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            if let Some(w) = handle.get_webview_window("floating") {
                if let Err(e) = save_geometry(&w) {
                    eprintln!("Floating layout not saved: {e}");
                }
                let _ = w.hide();
            }
        }
        if matches!(
            event,
            tauri::WindowEvent::Moved(_) | tauri::WindowEvent::Resized(_)
        ) {
            if let Some(w) = handle.get_webview_window("floating") {
                if w.is_visible().unwrap_or(false) {
                    if let Err(e) = save_geometry(&w) {
                        eprintln!("Floating layout not saved: {e}");
                    }
                }
            }
        }
    });
    let shell = app.state::<Shell>();
    shell.windows_open.store(true, Ordering::SeqCst);
    // A link that launched the app waited for the HUD.
    let pending = shell.pending.lock().unwrap().take();
    if let Some(path) = pending {
        if let Err(e) = open_hud(app, &path) {
            eprintln!("nerva:// link not opened: {e}");
        }
    }
    Ok(())
}

/// H171: find or start the hub off the main thread, then open the HUD.
fn start_hub_then_hud(app: &tauri::AppHandle) {
    let handle = app.clone();
    std::thread::spawn(move || {
        let owner = handle.state::<hub::Owner>();
        match owner.ensure() {
            Ok(hub::Outcome::Owned) => eprintln!("Nerva hub ready (started by this app)"),
            Ok(hub::Outcome::External) => eprintln!("Nerva hub ready (already running)"),
            Err(why) => {
                eprintln!("Nerva hub not ready: {why}");
                let _ = notify_rust::Notification::new()
                    .appname("Nerva")
                    .summary("Nerva could not reach its hub")
                    .body(&notify::clean(&why, 200))
                    .show();
            }
        }
        // Open the HUD either way: once the hub answers, a reload brings it back, and
        // the tray stays the way to quit.
        let opener = handle.clone();
        let _ = handle.run_on_main_thread(move || {
            if let Err(e) = open_windows(&opener) {
                eprintln!("HUD windows not opened: {e}");
            }
            register_quick_entry(&opener);
        });
    });
}

fn main() {
    tauri::Builder::default()
        // First, so a second launch (and the link it carries) goes to this instance.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.show();
                let _ = main.unminimize();
                let _ = main.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(Capabilities::detect())
        .manage(indicator::Board::default())
        .manage(Shell::default())
        .invoke_handler(tauri::generate_handler![
            desktop_action,
            desktop_capabilities,
            desktop_listening,
            desktop_notify
        ])
        .setup(|app| {
            let data_dir = app.path().app_data_dir()?;
            let log_dir = app.path().app_log_dir()?;
            app.manage(hub::Owner::new(data_dir, log_dir));
            // H183: nerva:// links. The installer registers the scheme; Linux and a
            // Windows dev build register it at runtime as well.
            #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
            if let Err(e) = app.deep_link().register_all() {
                eprintln!("nerva:// scheme not registered: {e}");
            }
            let links = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    handle_link(&links, url.as_str());
                }
            });
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                for url in urls {
                    handle_link(app.handle(), url.as_str());
                }
            }
            use tauri::menu::{Menu, MenuItem};
            let menu = Menu::with_items(
                app,
                &[
                    &MenuItem::with_id(app, "show", "Float chat", true, None::<&str>)?,
                    &MenuItem::with_id(app, "hide", "Hide floating chat", true, None::<&str>)?,
                    &MenuItem::with_id(app, "handoff", "Open Nerva", true, None::<&str>)?,
                    &MenuItem::with_id(app, "reset", "Reset floating layout", true, None::<&str>)?,
                    &MenuItem::with_id(app, "quit", "Quit Nerva", true, None::<&str>)?,
                ],
            )?;
            tauri::tray::TrayIconBuilder::with_id(TRAY_ID)
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Nerva")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| {
                    if event.id.as_ref() == "quit" {
                        app.exit(0);
                        return;
                    }
                    let requested = match event.id.as_ref() {
                        "show" => Action::Show,
                        "hide" => Action::Hide,
                        "reset" => Action::Reset,
                        "handoff" => Action::Handoff,
                        _ => return,
                    };
                    if let Err(e) = action(app, requested) {
                        eprintln!("Desktop action failed: {e}");
                    }
                })
                .build(app)?;
            start_hub_then_hud(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Nerva desktop")
        .run(|app, event| {
            // H171: stop the hub this app started, and only that one.
            if let tauri::RunEvent::Exit = event {
                if let Some(owner) = app.try_state::<hub::Owner>() {
                    owner.release();
                }
            }
        });
}
