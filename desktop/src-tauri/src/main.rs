//! Native local HUD and bounded floating-chat window management.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod geometry;
mod indicator;
mod policy;
mod throttling;
use geometry::{recover_scaled, Rect};
use policy::Action;
use tauri::utils::config::BackgroundThrottlingPolicy;
use tauri::{
    Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};

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
) -> Result<Capabilities, String> {
    verify(&window)?;
    Ok(caps.inner().clone())
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
fn main() {
    tauri::Builder::default()
        .manage(Capabilities::detect())
        .manage(indicator::Board::default())
        .invoke_handler(tauri::generate_handler![
            desktop_action,
            desktop_capabilities,
            desktop_listening
        ])
        .setup(|app| {
            // H182: a HUD in the background keeps reading a streaming reply.
            let throttle = match throttling::from_env() {
                throttling::Throttling::Disabled => BackgroundThrottlingPolicy::Disabled,
                throttling::Throttling::Throttle => BackgroundThrottlingPolicy::Throttle,
                throttling::Throttling::Suspend => BackgroundThrottlingPolicy::Suspend,
            };
            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External("http://127.0.0.1:8080/v2/".parse()?),
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
                WebviewUrl::External("http://127.0.0.1:8080/v2/?desktop=floating".parse()?),
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
            let handle = app.handle().clone();
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
        .run(tauri::generate_context!())
        .expect("error while running Nerva desktop");
}
