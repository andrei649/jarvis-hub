//! H181 — native OS notifications for decisions waiting on the owner.
//!
//! Std only (the pytest suite compiles it with `rustc --test`). The HUD window, which
//! holds the owner's session, notices a new pending approval and asks the shell to say
//! so with `desktop_notify`. The shell never sees a credential and never reads the hub
//! on its own.
//!
//! A notification can only **open** the decision: its click and its single action
//! ("Review in Nerva") bring the main window to the Decision Inbox, where the owner
//! approves or denies through the HUD's normal card and the hub's normal decision
//! route. There is no approve or deny button on the notification, so nothing is ever
//! decided from outside the HUD.
//!
//! Requests are validated (a fixed kind, a bounded id, bounded single-line text) and
//! deduplicated by kind and id, so a reloaded HUD does not repeat itself.
//! `NERVA_DESKTOP_NOTIFICATIONS=off` turns them off.

use std::collections::{HashSet, VecDeque};
use std::time::{Duration, Instant};

pub const ENV: &str = "NERVA_DESKTOP_NOTIFICATIONS";
pub const ACTION_REVIEW: &str = "review";
pub const ACTION_REVIEW_LABEL: &str = "Review in Nerva";
/// The only actions a notification carries. Opening is the only thing they do.
pub const ACTIONS: [(&str, &str); 1] = [(ACTION_REVIEW, ACTION_REVIEW_LABEL)];
const TITLE_MAX: usize = 80;
const BODY_MAX: usize = 200;
const SEEN_MAX: usize = 256;
/// At most this many notifications per minute; the rest are dropped (the inbox has them).
pub const PER_MINUTE: usize = 6;
/// At most this many notifications waiting for a click at once (one thread each).
pub const MAX_WAITING: usize = 8;

/// A sliding one-minute budget, so a misbehaving page cannot flood the desktop.
#[derive(Default)]
pub struct Budget {
    shown: VecDeque<Instant>,
}

impl Budget {
    pub fn allow(&mut self, now: Instant) -> bool {
        while self
            .shown
            .front()
            .is_some_and(|t| now.duration_since(*t) >= Duration::from_secs(60))
        {
            self.shown.pop_front();
        }
        if self.shown.len() >= PER_MINUTE {
            return false;
        }
        self.shown.push_back(now);
        true
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Approval,
}

impl Kind {
    /// Where a click or the action takes the main window.
    pub fn hud_path(self) -> &'static str {
        match self {
            Kind::Approval => "/v2/console/decision-inbox",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub kind: Kind,
    pub id: String,
    pub title: String,
    pub body: String,
}

pub fn enabled(value: Option<&str>) -> bool {
    !matches!(
        value.map(|v| v.trim().to_ascii_lowercase()).as_deref(),
        Some("off" | "0" | "false" | "no")
    )
}

fn valid_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.' | b':'))
}

/// One line, no control or bidi-override characters and no `<`, `>` or `&` (freedesktop
/// servers read the body as markup, so a title could otherwise carry a link or tags),
/// at most `max` characters.
pub fn clean(text: &str, max: usize) -> String {
    let words: Vec<String> = text
        .split(|c: char| {
            c.is_control()
                || c.is_whitespace()
                || matches!(c, '<' | '>' | '&')
                || matches!(c, '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}' | '\u{200E}' | '\u{200F}')
        })
        .filter(|w| !w.is_empty())
        .map(str::to_string)
        .collect();
    let line = words.join(" ");
    if line.chars().count() <= max {
        return line;
    }
    let mut out: String = line.chars().take(max.saturating_sub(1)).collect();
    out.push('…');
    out
}

pub fn validate(kind: &str, id: &str, title: &str, body: &str) -> Result<Request, String> {
    let kind = match kind {
        "approval" => Kind::Approval,
        _ => return Err("unknown notification kind".into()),
    };
    if !valid_id(id) {
        return Err("invalid notification id".into());
    }
    let mut title = clean(title, TITLE_MAX);
    if title.is_empty() {
        title = "Nerva needs a decision".into();
    }
    Ok(Request {
        kind,
        id: id.to_string(),
        title,
        body: clean(body, BODY_MAX),
    })
}

/// The kinds and ids already shown, oldest forgotten first.
#[derive(Default)]
pub struct Seen {
    order: VecDeque<String>,
    set: HashSet<String>,
}

impl Seen {
    /// True the first time a (kind, id) is offered.
    pub fn first(&mut self, request: &Request) -> bool {
        let key = format!("{:?}:{}", request.kind, request.id);
        if self.set.contains(&key) {
            return false;
        }
        if self.order.len() == SEEN_MAX {
            if let Some(old) = self.order.pop_front() {
                self.set.remove(&old);
            }
        }
        self.order.push_back(key.clone());
        self.set.insert(key);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_approval_kind_and_bounded_ids_pass() {
        assert!(validate("approval", "task_01:abc-2.x", "t", "b").is_ok());
        assert!(validate("approve", "a", "t", "b").is_err());
        assert!(validate("", "a", "t", "b").is_err());
        for id in ["", "a b", "a/b", "<script>", "a'b", &"x".repeat(129)] {
            assert!(validate("approval", id, "t", "b").is_err(), "{id}");
        }
    }

    #[test]
    fn text_is_one_bounded_line_without_controls() {
        let r = validate("approval", "a", "", "line\none\u{202E}evil\t\u{7}x").unwrap();
        assert_eq!(r.title, "Nerva needs a decision");
        assert_eq!(r.body, "line one evil x");
        let long = validate("approval", "a", &"t".repeat(500), &"é".repeat(500)).unwrap();
        assert_eq!(long.title.chars().count(), TITLE_MAX);
        assert!(long.title.ends_with('…'));
        assert_eq!(long.body.chars().count(), BODY_MAX);
        assert_eq!(clean("  a   b  ", 10), "a b");
    }

    #[test]
    fn a_notification_can_only_open_the_decision_never_decide_it() {
        assert_eq!(ACTIONS.len(), 1);
        for (id, label) in ACTIONS {
            let both = format!("{id} {label}").to_ascii_lowercase();
            for word in ["approve", "deny", "allow", "reject", "accept"] {
                assert!(!both.contains(word), "{both}");
            }
        }
        assert_eq!(Kind::Approval.hud_path(), "/v2/console/decision-inbox");
    }

    #[test]
    fn duplicates_are_shown_once_and_memory_is_bounded() {
        let mut seen = Seen::default();
        let r = validate("approval", "a", "t", "b").unwrap();
        assert!(seen.first(&r));
        assert!(!seen.first(&r));
        for i in 0..SEEN_MAX {
            seen.first(&validate("approval", &format!("n{i}"), "t", "b").unwrap());
        }
        assert!(seen.order.len() <= SEEN_MAX && seen.set.len() == seen.order.len());
        assert!(seen.first(&r), "the oldest is forgotten");
    }

    #[test]
    fn markup_cannot_reach_a_freedesktop_body() {
        let r = validate(
            "approval",
            "x1",
            "<b>t</b>",
            "<a href=\"https://evil.test\">Open Nerva</a> <b>urgent</b> &amp;",
        )
        .unwrap();
        for text in [&r.title, &r.body] {
            assert!(!text.contains(['<', '>', '&']), "{text}");
        }
        assert_eq!(r.title, "b t /b");
    }

    #[test]
    fn a_flood_is_cut_to_the_per_minute_budget() {
        let mut budget = Budget::default();
        let start = Instant::now();
        for _ in 0..PER_MINUTE {
            assert!(budget.allow(start));
        }
        assert!(!budget.allow(start + Duration::from_secs(30)));
        assert!(budget.allow(start + Duration::from_secs(61)));
    }

    #[test]
    fn the_owner_can_turn_them_off() {
        assert!(enabled(None));
        assert!(enabled(Some("on")));
        for v in ["off", "OFF", "0", "false", "no"] {
            assert!(!enabled(Some(v)), "{v}");
        }
    }
}
