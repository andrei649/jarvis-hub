//! H183 — `nerva://` links, parsed strictly and turned into a HUD page, never an effect.
//!
//! Std only (the pytest suite compiles it with `rustc --test`). Any web page or chat
//! message can hand the OS a `nerva://` link, so every link is untrusted input: it
//! must be ASCII, bounded in size, name one known target and carry only that target's
//! parameters, each validated. A link that fails any check does nothing.
//!
//! What a link may do is open a page of the local HUD in the main window:
//!
//! * `nerva://open/chat`, `nerva://open/decision-inbox`, `nerva://open/mcp`
//! * `nerva://mcp/install?name=<catalog name>` opens the MCP install card for a
//!   reviewed catalog entry;
//! * `nerva://mcp/install?name=<name>&config=<base64 JSON>` opens it for a vendor's
//!   server (the Cursor/Hermes `config=` shape, at most 32 KB of base64).
//!
//! The install card (`frontend/src/panels/mcp.tsx`, G9) asks the hub for the plan and
//! shows exactly what would run — the command line or the HTTPS endpoint, the
//! environment, the secret names — and installs only after the owner ticks "I have read
//! what will run" and presses Install; the hub writes only the plan whose digest was
//! shown. A link never installs, connects or starts anything.

pub const SCHEME: &str = "nerva";
/// The whole link, scheme included.
pub const MAX_LINK: usize = 34 * 1024;
/// The same bound the hub's install card and catalog parser apply.
pub const MAX_CONFIG: usize = 32 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Link {
    Open(&'static str),
    McpInstall { name: String },
    McpVendor { name: String, config: String },
}

const OPEN: [(&str, &str); 3] = [
    ("chat", "/v2/chat"),
    ("decision-inbox", "/v2/console/decision-inbox"),
    ("mcp", "/v2/console/mcp"),
];

fn valid_name(name: &str) -> bool {
    (1..=64).contains(&name.len())
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

fn valid_config(config: &str) -> bool {
    (1..=MAX_CONFIG).contains(&config.len())
        && config
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'/' | b'=' | b'-' | b'_'))
}

fn hex(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

/// Percent-decoding to ASCII only. `+` stays `+` (it is a base64 character here, not a
/// space); a decoded control character or non-ASCII byte refuses the link.
fn decode(raw: &str) -> Result<String, String> {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        let b = if bytes[i] == b'%' {
            let (hi, lo) = (bytes.get(i + 1).copied(), bytes.get(i + 2).copied());
            let v = hi
                .and_then(hex)
                .zip(lo.and_then(hex))
                .map(|(h, l)| h * 16 + l)
                .ok_or("bad percent-escape")?;
            i += 3;
            v
        } else {
            i += 1;
            bytes[i - 1]
        };
        if !b.is_ascii() || b.is_ascii_control() {
            return Err("a link parameter may only hold printable ASCII".into());
        }
        out.push(b);
    }
    String::from_utf8(out).map_err(|_| "not ASCII".to_string())
}

fn encode_query_value(value: &str) -> String {
    value
        .bytes()
        .map(|b| {
            if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
                (b as char).to_string()
            } else {
                format!("%{b:02X}")
            }
        })
        .collect()
}

pub fn parse(raw: &str) -> Result<Link, String> {
    if raw.len() > MAX_LINK {
        return Err("the link is too long".into());
    }
    if !raw.bytes().all(|b| b.is_ascii_graphic()) {
        return Err("a link may only hold printable ASCII without spaces".into());
    }
    let (scheme, rest) = raw.split_once("://").ok_or("not a nerva:// link")?;
    if !scheme.eq_ignore_ascii_case(SCHEME) {
        return Err("not a nerva:// link".into());
    }
    if rest.contains('#') {
        return Err("a link may not carry a fragment".into());
    }
    let (target, query) = match rest.split_once('?') {
        Some((t, q)) => (t, Some(q)),
        None => (rest, None),
    };
    let target = target.trim_end_matches('/');
    let mut params: Vec<(String, String)> = Vec::new();
    if let Some(query) = query {
        for pair in query.split('&') {
            let (k, v) = pair.split_once('=').ok_or("a parameter needs a value")?;
            let key = decode(k)?;
            if params.iter().any(|(seen, _)| *seen == key) {
                return Err(format!("{key} appears twice"));
            }
            params.push((key, decode(v)?));
        }
    }
    let get = |key: &str| {
        params
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    };
    let allow_only = |keys: &[&str]| -> Result<(), String> {
        match params.iter().find(|(k, _)| !keys.contains(&k.as_str())) {
            Some((k, _)) => Err(format!("{k} is not a parameter of this link")),
            None => Ok(()),
        }
    };
    if let Some(page) = target.strip_prefix("open/") {
        allow_only(&[])?;
        return OPEN
            .iter()
            .find(|(name, _)| *name == page)
            .map(|(_, path)| Link::Open(path))
            .ok_or_else(|| "unknown page".to_string());
    }
    if target == "mcp/install" {
        allow_only(&["name", "config"])?;
        let name = get("name")
            .filter(|n| valid_name(n))
            .ok_or("an MCP install link needs name= of letters, digits, - and _ (at most 64)")?;
        return match get("config") {
            None => Ok(Link::McpInstall {
                name: name.to_string(),
            }),
            Some(config) if valid_config(config) => Ok(Link::McpVendor {
                name: name.to_string(),
                config: config.to_string(),
            }),
            Some(_) => Err("config= must be base64, at most 32 KB".into()),
        };
    }
    Err("unknown nerva:// link".into())
}

/// The HUD page (path and query on the hub's origin) the link opens.
pub fn hud_path(link: &Link) -> String {
    match link {
        Link::Open(path) => path.to_string(),
        Link::McpInstall { name } => {
            format!("/v2/console/mcp?install={}", encode_query_value(name))
        }
        Link::McpVendor { name, config } => format!(
            "/v2/console/mcp?link={}&config={}",
            encode_query_value(name),
            encode_query_value(config)
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn open_links_name_one_known_page() {
        assert_eq!(parse("nerva://open/chat"), Ok(Link::Open("/v2/chat")));
        assert_eq!(
            parse("NERVA://open/decision-inbox/"),
            Ok(Link::Open("/v2/console/decision-inbox"))
        );
        assert_eq!(
            hud_path(&parse("nerva://open/mcp").unwrap()),
            "/v2/console/mcp"
        );
        for bad in [
            "nerva://open/admin",
            "nerva://open/../api/admin",
            "nerva://open/chat?x=1",
            "nerva://open/chat#x",
            "nerva://open",
            "nerva://",
            "https://open/chat",
            "nervax://open/chat",
            "nerva:open/chat",
        ] {
            assert!(parse(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn a_catalog_install_link_only_opens_the_install_card() {
        let link = parse("nerva://mcp/install?name=linear").unwrap();
        assert_eq!(
            link,
            Link::McpInstall {
                name: "linear".into()
            }
        );
        assert_eq!(hud_path(&link), "/v2/console/mcp?install=linear");
    }

    #[test]
    fn a_vendor_link_keeps_its_config_exactly_for_the_card_to_show() {
        let config = "eyJjb21tYW5kIjoibnB4IiwiYXJncyI6WyIteSIsIkBhY21lL21jcCJdfQ==";
        let link = parse(&format!("nerva://mcp/install?name=acme&config={config}")).unwrap();
        assert_eq!(
            link,
            Link::McpVendor {
                name: "acme".into(),
                config: config.into()
            }
        );
        // Percent-escaped spelling of the same link decodes to the same config, and
        // the HUD query re-encodes + / = so they survive URLSearchParams.
        let escaped = parse("nerva://mcp/install?name=acme&config=ab%2Bc%2F%3D").unwrap();
        assert_eq!(
            hud_path(&escaped),
            "/v2/console/mcp?link=acme&config=ab%2Bc%2F%3D"
        );
        assert_eq!(
            hud_path(&parse("nerva://mcp/install?name=a&config=a+b").unwrap()),
            "/v2/console/mcp?link=a&config=a%2Bb"
        );
    }

    #[test]
    fn install_links_are_validated_and_bounded() {
        let too_big = format!(
            "nerva://mcp/install?name=a&config={}",
            "A".repeat(MAX_CONFIG + 1)
        );
        let way_too_big = format!("nerva://mcp/install?name=a&config={}", "A".repeat(MAX_LINK));
        for bad in [
            "nerva://mcp/install",
            "nerva://mcp/install?name=",
            "nerva://mcp/install?name=a b",
            "nerva://mcp/install?name=a%20b",
            "nerva://mcp/install?name=../x",
            "nerva://mcp/install?name=a&name=b",
            "nerva://mcp/install?name=a&command=rm",
            "nerva://mcp/install?name=a&url=https://evil.test",
            "nerva://mcp/install?name=a&config=",
            "nerva://mcp/install?name=a&config=%00",
            "nerva://mcp/install?name=a&config=a%0Ab",
            "nerva://mcp/install?name=a&config=a%C3%A9",
            "nerva://mcp/install?name=a&config=a%2",
            "nerva://mcp/install?name=a&config={}",
            "nerva://mcp/install?name",
            "nerva://mcp/install?name=a&",
            "nerva://mcp/uninstall?name=a",
            "nerva://mcp/install?name=é",
            &too_big,
            &way_too_big,
        ] {
            assert!(parse(bad).is_err(), "{}", &bad[..bad.len().min(80)]);
        }
        let name64 = "n".repeat(64);
        assert!(parse(&format!("nerva://mcp/install?name={name64}")).is_ok());
        assert!(parse(&format!("nerva://mcp/install?name={name64}n")).is_err());
        let max = format!(
            "nerva://mcp/install?name=a&config={}",
            "A".repeat(MAX_CONFIG)
        );
        assert!(parse(&max).is_ok());
    }

    #[test]
    fn every_hud_path_stays_on_a_registered_page() {
        for raw in [
            "nerva://open/chat",
            "nerva://open/decision-inbox",
            "nerva://open/mcp",
            "nerva://mcp/install?name=x",
            "nerva://mcp/install?name=x&config=QQ==",
        ] {
            let path = hud_path(&parse(raw).unwrap());
            let page = path.split('?').next().unwrap();
            assert!(OPEN.iter().any(|(_, p)| *p == page), "{path}");
            assert!(!path.contains('#') && !path.contains("..") && !path.contains("//"));
        }
    }
}
