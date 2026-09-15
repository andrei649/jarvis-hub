pub fn allowed(label: &str, url: &tauri::Url) -> bool {
    matches!(label, "main" | "floating")
        && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(8080)
        && url.username().is_empty()
        && url.password().is_none()
        && matches!(url.path(), "/v2" | "/v2/")
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
    fn development_origin_has_its_local_capability() {
        // Tauri classifies build.devUrl as local, even though it is an HTTP URL.
        // The command independently verifies the exact HUD URL in both builds.
        let cap: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/desktop.json")).unwrap();
        assert_eq!(cap["local"], true);
        assert_eq!(cap["permissions"].as_array().unwrap().len(), 2);
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
