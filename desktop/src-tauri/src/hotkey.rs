//! H179 — the Quick Entry hotkey: one global accelerator that opens the floating chat
//! with its composer focused, from anywhere on the system.
//!
//! Std only (the pytest suite compiles it with `rustc --test`). The owner picks the
//! accelerator with `NERVA_DESKTOP_QUICK_ENTRY`; unset means
//! `CommandOrControl+Shift+Space`, and `off` turns it off. A value is canonicalised
//! (modifier aliases, one order, one key) and refused unless it carries a real
//! modifier: Shift alone would swallow ordinary typing and Escape is how every
//! window says "cancel". When another program already holds the accelerator the shell
//! leaves Quick Entry off and says so; it never takes a shortcut by force.
//!
//! The hotkey only shows the window. The prompt goes out through the floating chat's
//! normal send, under the HUD's own session, and is never submitted or approved for
//! the owner.

pub const ENV: &str = "NERVA_DESKTOP_QUICK_ENTRY";
pub const DEFAULT: &str = "CommandOrControl+Shift+Space";

const MODIFIERS: [(&str, &[&str]); 5] = [
    (
        "CommandOrControl",
        &[
            "commandorcontrol",
            "cmdorctrl",
            "cmdorcontrol",
            "commandorctrl",
        ],
    ),
    ("Control", &["control", "ctrl"]),
    ("Alt", &["alt", "option"]),
    ("Super", &["super", "cmd", "command", "meta"]),
    ("Shift", &["shift"]),
];

const NAMED_KEYS: [&str; 13] = [
    "Space",
    "Enter",
    "Tab",
    "Backquote",
    "Slash",
    "Backslash",
    "Period",
    "Comma",
    "Semicolon",
    "Quote",
    "Minus",
    "Equal",
    "BracketLeft",
];

fn key(raw: &str) -> Result<String, String> {
    let lower = raw.to_ascii_lowercase();
    if lower == "escape" || lower == "esc" {
        return Err("Escape cannot be the Quick Entry key".into());
    }
    if raw.len() == 1 && raw.as_bytes()[0].is_ascii_alphanumeric() {
        return Ok(raw.to_ascii_uppercase());
    }
    if let Some(number) = lower.strip_prefix('f') {
        if !number.starts_with('0') && number.len() <= 2 {
            if let Ok(n) = number.parse::<u8>() {
                if (1..=24).contains(&n) {
                    return Ok(format!("F{n}"));
                }
            }
        }
    }
    NAMED_KEYS
        .iter()
        .find(|k| k.eq_ignore_ascii_case(raw))
        .map(|k| k.to_string())
        .ok_or_else(|| format!("{raw:?} is not a key Quick Entry accepts"))
}

/// The canonical accelerator, or why it is refused.
pub fn canonical(raw: &str) -> Result<String, String> {
    let raw = raw.trim();
    if raw.is_empty() || raw.len() > 64 {
        return Err(
            "an accelerator is one key with modifiers, e.g. CommandOrControl+Shift+Space".into(),
        );
    }
    let mut held = [false; 5];
    let mut main_key: Option<String> = None;
    for part in raw.split('+').map(str::trim) {
        if part.is_empty() {
            return Err(format!("{raw:?} has an empty part"));
        }
        let lower = part.to_ascii_lowercase();
        if let Some(i) = MODIFIERS
            .iter()
            .position(|(_, aliases)| aliases.contains(&lower.as_str()))
        {
            if held[i] {
                return Err(format!("{raw:?} names {} twice", MODIFIERS[i].0));
            }
            held[i] = true;
            continue;
        }
        if main_key.is_some() {
            return Err(format!("{raw:?} has more than one key"));
        }
        main_key = Some(key(part)?);
    }
    let main_key = main_key.ok_or_else(|| format!("{raw:?} has no key"))?;
    // Shift (index 4) alone is not a modifier for this purpose.
    if !held[..4].iter().any(|h| *h) {
        return Err(format!(
            "{raw:?} needs CommandOrControl, Control, Alt or Super; Shift alone would capture typing"
        ));
    }
    let mut out: Vec<String> = MODIFIERS
        .iter()
        .zip(held)
        .filter(|(_, h)| *h)
        .map(|((name, _), _)| name.to_string())
        .collect();
    out.push(main_key);
    Ok(out.join("+"))
}

/// The owner's setting: `Ok(None)` is off.
pub fn parse(value: Option<&str>) -> Result<Option<String>, String> {
    match value.map(str::trim) {
        None => Ok(Some(DEFAULT.to_string())),
        Some(v)
            if v.eq_ignore_ascii_case("off") || v.eq_ignore_ascii_case("none") || v.is_empty() =>
        {
            Ok(None)
        }
        Some(v) => canonical(v)
            .map(Some)
            .map_err(|why| format!("{ENV}: {why}; Quick Entry is off")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_default_is_command_or_control_shift_space() {
        assert_eq!(parse(None), Ok(Some(DEFAULT.to_string())));
        assert_eq!(canonical(DEFAULT), Ok(DEFAULT.to_string()));
    }

    #[test]
    fn off_turns_it_off() {
        for v in ["off", "OFF", "none", " "] {
            assert_eq!(parse(Some(v)), Ok(None), "{v}");
        }
    }

    #[test]
    fn aliases_and_order_are_canonicalised() {
        assert_eq!(canonical("shift+cmdorctrl+space"), Ok(DEFAULT.to_string()));
        assert_eq!(canonical("Ctrl + Alt + k"), Ok("Control+Alt+K".to_string()));
        assert_eq!(canonical("option+cmd+F12"), Ok("Alt+Super+F12".to_string()));
        assert_eq!(canonical("meta+1"), Ok("Super+1".to_string()));
        assert_eq!(
            canonical("ctrl+backquote"),
            Ok("Control+Backquote".to_string())
        );
    }

    #[test]
    fn a_real_modifier_is_required_and_escape_is_refused() {
        for bad in [
            "Space",
            "Shift+Space",
            "Shift+A",
            "F5",
            "Ctrl+Escape",
            "Ctrl+Esc",
            "Ctrl+Shift",
            "Ctrl+A+B",
            "Ctrl+Ctrl+A",
            "Ctrl++A",
            "Ctrl+F0",
            "Ctrl+F25",
            "Ctrl+F05",
            "Ctrl+PrintScreen",
            "Ctrl+é",
            "",
        ] {
            assert!(canonical(bad).is_err(), "{bad}");
        }
        let err = parse(Some("Shift+A")).unwrap_err();
        assert!(err.contains(ENV) && err.contains("Quick Entry is off"));
    }
}
