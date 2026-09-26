//! H182 — whether a HUD window in the background keeps running a streaming turn.
//!
//! A webview that loses focus is throttled, then suspended, by default (macOS 14+ honours
//! the policy; Linux and Windows ignore it). A suspended HUD stops reading the reply
//! stream, and the hub cancels a turn whose reader is gone. So the shell turns
//! throttling off unless the owner asks for it back with
//! `NERVA_DESKTOP_BACKGROUND_THROTTLING=throttle` or `=suspend` (to save battery).

pub const ENV: &str = "NERVA_DESKTOP_BACKGROUND_THROTTLING";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Throttling {
    Disabled,
    Throttle,
    Suspend,
}

/// The owner's choice. Unset or blank is `Disabled`; anything else unknown is refused
/// (the caller falls back to `Disabled` and says so).
pub fn parse(value: Option<&str>) -> Result<Throttling, String> {
    let Some(raw) = value else {
        return Ok(Throttling::Disabled);
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "" | "disabled" => Ok(Throttling::Disabled),
        "throttle" => Ok(Throttling::Throttle),
        "suspend" => Ok(Throttling::Suspend),
        other => Err(format!(
            "{ENV}={other:?} is not one of disabled, throttle, suspend; using disabled"
        )),
    }
}

/// The policy from the environment, with a line on stderr for a value it did not know.
pub fn from_env() -> Throttling {
    let value = std::env::var(ENV).ok();
    parse(value.as_deref()).unwrap_or_else(|why| {
        eprintln!("{why}");
        Throttling::Disabled
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unset_or_blank_keeps_a_background_turn_running() {
        assert_eq!(parse(None), Ok(Throttling::Disabled));
        assert_eq!(parse(Some("")), Ok(Throttling::Disabled));
        assert_eq!(parse(Some("  ")), Ok(Throttling::Disabled));
        assert_eq!(parse(Some("disabled")), Ok(Throttling::Disabled));
    }

    #[test]
    fn the_owner_can_ask_for_throttling_back() {
        assert_eq!(parse(Some("throttle")), Ok(Throttling::Throttle));
        assert_eq!(parse(Some(" Suspend ")), Ok(Throttling::Suspend));
        assert_eq!(parse(Some("THROTTLE")), Ok(Throttling::Throttle));
    }

    #[test]
    fn an_unknown_value_is_refused_by_name() {
        let err = parse(Some("sometimes")).unwrap_err();
        assert!(
            err.contains(ENV) && err.contains("\"sometimes\"") && err.contains("using disabled")
        );
    }
}
