use std::sync::OnceLock;

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct HudRoutes {
    main: Vec<String>,
    floating: Vec<String>,
}

fn registered_path(label: &str, path: &str) -> bool {
    // Generated from the frontend registries; its sync test must pass whenever
    // routes change. Parse once and deny every path if the bundled data is invalid.
    static ROUTES: OnceLock<Option<HudRoutes>> = OnceLock::new();
    let Some(routes) =
        ROUTES.get_or_init(|| serde_json::from_str(include_str!("../hud-routes.json")).ok())
    else {
        return false;
    };
    match label {
        "main" => routes.main.iter().any(|route| route == path),
        "floating" => routes.floating.iter().any(|route| route == path),
        _ => false,
    }
}

pub fn allowed(label: &str, url: &tauri::Url) -> bool {
    matches!(label, "main" | "floating")
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(8080)
        && url.username().is_empty()
        && url.password().is_none()
        && registered_path(label, url.path())
}
#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Action {
    Show,
    Hide,
    Reset,
    Handoff,
    Drag,
    Resize,
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_our_two_windows_and_exact_local_hud() {
        for label in ["main", "floating"] {
            assert!(allowed(
                label,
                &"http://127.0.0.1:8080/v2/?desktop=floating"
                    .parse()
                    .unwrap()
            ));
        }
        for url in [
            "https://127.0.0.1:8080/v2/",
            "http://127.0.0.1:8081/v2/",
            "http://localhost:8080/v2/",
            "http://127.0.0.1:8080/",
            "http://evil.test/v2/",
            "http://user@127.0.0.1:8080/v2/",
        ] {
            assert!(!allowed("main", &url.parse().unwrap()), "{url}");
        }
        assert!(!allowed(
            "other",
            &"http://127.0.0.1:8080/v2/".parse().unwrap()
        ));
    }
    #[test]
    fn canonical_hud_routes_keep_native_controls_available() {
        for path in [
            "/v2/chat",
            "/v2/memory",
            "/v2/world",
            "/v2/console/decision-inbox",
        ] {
            let url = format!("http://127.0.0.1:8080{path}?demo=1#anchor")
                .parse()
                .unwrap();
            assert!(allowed("main", &url), "{path}");
        }
        assert!(allowed(
            "floating",
            &"http://127.0.0.1:8080/v2/chat?desktop=floating"
                .parse()
                .unwrap()
        ));
    }
    #[test]
    fn every_registered_route_is_allowed_only_for_its_window() {
        let routes: HudRoutes = serde_json::from_str(include_str!("../hud-routes.json")).unwrap();
        assert_eq!(routes.floating.len(), 4);
        for path in &routes.main {
            let url = format!("http://127.0.0.1:8080{path}?demo=1#anchor")
                .parse()
                .unwrap();
            assert!(allowed("main", &url), "{path}");
            assert_eq!(
                allowed("floating", &url),
                routes.floating.contains(path),
                "{path}"
            );
            assert!(!allowed("other", &url), "{path}");
        }
    }
    #[test]
    fn routing_does_not_admit_unknown_paths_assets_or_other_origins() {
        for path in [
            "/",
            "/api/status",
            "/v20/chat",
            "/v2/unknown",
            "/v2/chat/extra",
            "/v2/console/unknown",
            "/v2/assets/index.js",
            "/v2/sw-v2.js",
            "/v2/%63hat",
            "/v2//chat",
            "/v2/console/decision-inbox/extra",
        ] {
            for label in ["main", "floating"] {
                let url = format!("http://127.0.0.1:8080{path}").parse().unwrap();
                assert!(!allowed(label, &url), "{label}: {path}");
            }
        }
        for base in [
            "https://127.0.0.1:8080",
            "http://127.0.0.1:8081",
            "http://localhost:8080",
            "http://evil.test:8080",
            "http://127.0.0.1.evil.test:8080",
            "http://user@127.0.0.1:8080",
            "http://:secret@127.0.0.1:8080",
        ] {
            for label in ["main", "floating"] {
                assert!(
                    !allowed(label, &format!("{base}/v2/chat").parse().unwrap()),
                    "{base}"
                );
            }
        }
    }
    #[test]
    fn development_origin_has_its_local_capability() {
        // Tauri classifies build.devUrl as local, even though it is an HTTP URL.
        // The command independently verifies the exact HUD URL in both builds.
        let cap: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/desktop.json")).unwrap();
        assert_eq!(cap["local"], true);
        assert_eq!(cap["windows"], serde_json::json!(["main", "floating"]));
        assert_eq!(
            cap["permissions"],
            serde_json::json!(["allow-desktop-action", "allow-desktop-capabilities"])
        );
        assert_eq!(
            cap["remote"]["urls"],
            serde_json::json!(["http://127.0.0.1:8080/v2", "http://127.0.0.1:8080/v2/*"])
        );
    }
    #[test]
    fn no_arbitrary_native_actions() {
        for s in [
            "shell",
            "capture",
            "close",
            "navigate",
            "read",
            "setposition",
        ] {
            assert!(serde_json::from_value::<Action>(serde_json::json!(s)).is_err());
        }
    }
}
