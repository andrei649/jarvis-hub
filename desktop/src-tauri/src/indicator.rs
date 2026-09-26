//! H222 — whether Nerva is listening, shown on the tray icon outside the HUD windows.
//!
//! Each HUD window reports the loudest of the hub's listening state (its voice
//! pipeline and satellites) and its own browser mic. The board keeps one state per
//! window and the tray shows the loudest: a menu-bar title while a mic is open
//! (macOS; Linux shows it next to the icon, Windows has no title) and a tooltip that
//! names the state (macOS and Windows; Linux has no tooltip). The surface is
//! read-only: nothing here opens or closes a mic.

use std::sync::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Listening {
    Off,
    Armed,
    Listening,
    Thinking,
    Speaking,
}

impl Listening {
    /// Loudest first: an open mic outranks everything else.
    fn rank(self) -> u8 {
        match self {
            Listening::Listening => 4,
            Listening::Armed => 3,
            Listening::Thinking => 2,
            Listening::Speaking => 1,
            Listening::Off => 0,
        }
    }

    pub fn tooltip(self) -> &'static str {
        match self {
            Listening::Off => "Nerva",
            Listening::Armed => "Nerva — mic open for the wake word",
            Listening::Listening => "Nerva — listening",
            Listening::Thinking => "Nerva — thinking",
            Listening::Speaking => "Nerva — speaking",
        }
    }

    /// Only an open mic earns room in the menu bar.
    pub fn title(self) -> Option<&'static str> {
        match self {
            Listening::Listening => Some("● listening"),
            Listening::Armed => Some("○ wake word"),
            _ => None,
        }
    }
}

/// A state name from the HUD; anything else is refused.
pub fn parse(state: &str) -> Result<Listening, String> {
    match state {
        "off" => Ok(Listening::Off),
        "armed" => Ok(Listening::Armed),
        "listening" => Ok(Listening::Listening),
        "thinking" => Ok(Listening::Thinking),
        "speaking" => Ok(Listening::Speaking),
        _ => Err("unknown listening state".to_string()),
    }
}

/// One state per reporting window; the tray shows the loudest.
#[derive(Default)]
pub struct Board {
    windows: Mutex<Vec<(String, Listening)>>,
}

impl Board {
    /// Record *label*'s state and return what the tray should now show.
    pub fn report(&self, label: &str, state: Listening) -> Listening {
        let mut windows = self.windows.lock().unwrap_or_else(|e| e.into_inner());
        windows.retain(|(l, _)| l != label);
        windows.push((label.to_string(), state)); // one entry per window; Off ranks lowest
        windows
            .iter()
            .map(|(_, s)| *s)
            .max_by_key(|s| s.rank())
            .unwrap_or(Listening::Off)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_known_states_are_accepted() {
        assert_eq!(parse("listening"), Ok(Listening::Listening));
        assert_eq!(parse("armed"), Ok(Listening::Armed));
        assert_eq!(parse("thinking"), Ok(Listening::Thinking));
        assert_eq!(parse("speaking"), Ok(Listening::Speaking));
        assert_eq!(parse("off"), Ok(Listening::Off));
        for bad in ["", "Listening", "on", "listening ", "mute"] {
            assert!(parse(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn the_tray_names_the_state_and_titles_only_an_open_mic() {
        assert_eq!(Listening::Listening.title(), Some("● listening"));
        assert_eq!(Listening::Armed.title(), Some("○ wake word"));
        assert_eq!(Listening::Thinking.title(), None);
        assert_eq!(Listening::Speaking.title(), None);
        assert_eq!(Listening::Off.title(), None);
        assert_eq!(Listening::Off.tooltip(), "Nerva");
        assert_eq!(Listening::Listening.tooltip(), "Nerva — listening");
        assert_eq!(
            Listening::Armed.tooltip(),
            "Nerva — mic open for the wake word"
        );
    }

    #[test]
    fn the_loudest_window_wins_and_a_window_going_quiet_drops_out() {
        let board = Board::default();
        assert_eq!(
            board.report("main", Listening::Thinking),
            Listening::Thinking
        );
        assert_eq!(board.report("floating", Listening::Armed), Listening::Armed);
        assert_eq!(
            board.report("main", Listening::Listening),
            Listening::Listening
        );
        assert_eq!(board.report("main", Listening::Off), Listening::Armed);
        assert_eq!(
            board.report("floating", Listening::Speaking),
            Listening::Speaking
        );
        assert_eq!(board.report("floating", Listening::Off), Listening::Off);
    }
}
