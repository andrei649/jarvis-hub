//! H171 — the desktop shell owns the hub process it starts, and only that one.
//!
//! Pure policy, std only (the pytest suite compiles it with `rustc --test`, no GUI
//! libraries needed). `main.rs` supplies the observations (is a recorded process still
//! the one we started? does the hub answer?) and carries out the plan.
//!
//! * **Resolve**: `NERVA_DESKTOP_HUB=external` never starts a hub; otherwise the
//!   checkout comes from `NERVA_DESKTOP_HUB_DIR`, else the first ancestor of the
//!   executable or the working directory that holds `serve.py` and `agents/web.py`.
//!   The interpreter is that checkout's `.venv` (the one `install.sh` / `INSTALL.bat`
//!   make); without it the shell refuses to guess a system Python.
//! * **Ownership record**: pid, the process's start time and a per-launch nonce,
//!   written atomically next to the shell's data. A pid alone is not proof — pids are
//!   reused — so the shell acts on a record only while the live process at that pid
//!   still has the recorded start time and executable.
//! * **Claim**: a recorded process that is still ours is adopted again (never killed
//!   while healthy). A record whose process is gone is dropped. A hub the shell did not
//!   start is used, never killed. Only an empty port leads to a spawn.
//! * **Reap**: an adopted orphan that never becomes ready within the boot timeout is
//!   stopped, and only then is a fresh hub started.
//! * **Ready**: the HUD windows open only after `GET /readyz` answers 200.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const ENV_MODE: &str = "NERVA_DESKTOP_HUB";
pub const ENV_DIR: &str = "NERVA_DESKTOP_HUB_DIR";
pub const RECORD_FILE: &str = "hub-ownership.txt";
const RECORD_MAX_BYTES: usize = 4096;

/// What the shell may do about a missing hub.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mode {
    /// Start one from the resolved checkout when nothing answers.
    Spawn,
    /// Never start one; wait for a hub the owner runs (start.sh, a service).
    External,
}

pub fn parse_mode(value: Option<&str>) -> Result<Mode, String> {
    match value.map(|v| v.trim().to_ascii_lowercase()) {
        None => Ok(Mode::Spawn),
        Some(v) if v.is_empty() || v == "spawn" || v == "auto" => Ok(Mode::Spawn),
        Some(v) if v == "external" || v == "off" => Ok(Mode::External),
        Some(other) => Err(format!(
            "{ENV_MODE}={other:?} is not one of spawn, external; using spawn"
        )),
    }
}

/// How to start a hub: the interpreter and the checkout it runs `serve.py` in.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Launch {
    pub python: PathBuf,
    pub dir: PathBuf,
}

fn is_checkout(dir: &Path, exists: &dyn Fn(&Path) -> bool) -> bool {
    exists(&dir.join("serve.py")) && exists(&dir.join("agents").join("web.py"))
}

fn venv_python(dir: &Path, windows: bool) -> PathBuf {
    if windows {
        dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        dir.join(".venv").join("bin").join("python")
    }
}

/// The resolution ladder. `explicit` is `NERVA_DESKTOP_HUB_DIR`; `starts` are the
/// executable's and the working directory's paths, searched upward.
pub fn resolve(
    explicit: Option<&Path>,
    starts: &[PathBuf],
    windows: bool,
    exists: &dyn Fn(&Path) -> bool,
) -> Result<Launch, String> {
    let dir = if let Some(dir) = explicit {
        if !is_checkout(dir, exists) {
            return Err(format!(
                "{ENV_DIR}={} has no serve.py and agents/web.py",
                dir.display()
            ));
        }
        dir.to_path_buf()
    } else {
        starts
            .iter()
            .flat_map(|start| start.ancestors())
            .find(|dir| is_checkout(dir, exists))
            .map(Path::to_path_buf)
            .ok_or_else(|| {
                format!("no Nerva checkout found; set {ENV_DIR} or start the hub yourself")
            })?
    };
    let python = venv_python(&dir, windows);
    if !exists(&python) {
        return Err(format!(
            "{} has no .venv; run install.sh (INSTALL.bat on Windows) first",
            dir.display()
        ));
    }
    Ok(Launch { python, dir })
}

/// The shell's proof that it started a process.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Record {
    pub pid: u32,
    /// The process's start time as the OS reports it (seconds since the epoch).
    pub started: u64,
    /// A fresh random value per launch; it names the launch in logs and the record.
    pub nonce: String,
    /// The interpreter that was started, compared against the live process.
    pub exe: PathBuf,
    /// The shell process that owns the hub now. While it is alive (a second copy of
    /// the app started without the single-instance hand-off) the hub is not adopted
    /// again, so only one shell ever stops it.
    pub shell: u32,
}

impl Record {
    pub fn encode(&self) -> String {
        format!(
            "version=1\npid={}\nstarted={}\nnonce={}\nexe={}\nshell={}\n",
            self.pid,
            self.started,
            self.nonce,
            self.exe.display(),
            self.shell
        )
    }

    /// Strict: every field once, nothing unknown, a bounded size. A record that does
    /// not parse is treated as absent, so it can never make the shell kill anything.
    pub fn decode(text: &str) -> Option<Record> {
        if text.len() > RECORD_MAX_BYTES {
            return None;
        }
        let (mut version, mut pid, mut started, mut nonce, mut exe, mut shell) =
            (None, None, None, None, None, None);
        for line in text.lines() {
            if line.is_empty() {
                continue;
            }
            let (key, value) = line.split_once('=')?;
            let slot = match key {
                "version" => &mut version,
                "pid" => &mut pid,
                "started" => &mut started,
                "nonce" => &mut nonce,
                "exe" => &mut exe,
                "shell" => &mut shell,
                _ => return None,
            };
            if slot.replace(value.to_string()).is_some() {
                return None;
            }
        }
        if version.as_deref() != Some("1") {
            return None;
        }
        let pid: u32 = pid?.parse().ok().filter(|p| *p > 1)?;
        let started: u64 = started?.parse().ok()?;
        let nonce = nonce.filter(|n| valid_nonce(n))?;
        let exe = PathBuf::from(exe.filter(|e| !e.is_empty())?);
        let shell: u32 = shell?.parse().ok()?;
        Some(Record {
            pid,
            started,
            nonce,
            exe,
            shell,
        })
    }
}

pub fn valid_nonce(nonce: &str) -> bool {
    nonce.len() == 32 && nonce.bytes().all(|b| b.is_ascii_hexdigit())
}

/// A nonce from the OS's randomness where it is a file (Unix), mixed with the clock
/// and pid elsewhere. It is an identifier, not a secret.
pub fn new_nonce() -> String {
    let mut bytes = [0u8; 16];
    let filled = std::fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .is_ok();
    if !filled {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let seed = t ^ ((std::process::id() as u128) << 64);
        bytes.copy_from_slice(&seed.to_le_bytes());
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// What the shell saw at launch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Observed {
    /// A record exists and parses.
    pub record: bool,
    /// The recorded pid is alive with the recorded start time and executable.
    pub record_alive: bool,
    /// The shell that owns that hub is another live process.
    pub owner_alive: bool,
    /// Something accepts connections on the hub's port.
    pub port_open: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Plan {
    /// Our process from an earlier launch: keep it, wait for it, own it again.
    Adopt,
    /// A hub we did not start: use it, never stop it.
    UseExternal,
    /// Nothing answers: start one (or, in external mode, wait for the owner's).
    Spawn,
    Wait,
}

/// The claim policy. A stale record (process gone or pid reused) is dropped by the
/// caller before or after this decision; it never leads to a kill. A hub another live
/// shell owns is used like an external one.
pub fn plan(seen: Observed, mode: &Mode) -> Plan {
    if seen.record && seen.record_alive && !seen.owner_alive {
        return Plan::Adopt;
    }
    if seen.port_open {
        return Plan::UseExternal;
    }
    match mode {
        Mode::Spawn => Plan::Spawn,
        Mode::External => Plan::Wait,
    }
}

/// Whether the shell may stop the process at `pid` on quit or reap: only with a
/// record whose start time and executable still match the live process.
pub fn may_stop(record: &Record, live_started: Option<u64>, live_exe: Option<&Path>) -> bool {
    live_started == Some(record.started) && live_exe.is_some_and(|exe| same_exe(exe, &record.exe))
}

fn same_exe(live: &Path, recorded: &Path) -> bool {
    // A venv interpreter is often a symlink to the base interpreter, and the OS
    // reports the resolved file; accept either spelling of the recorded one.
    live == recorded
        || std::fs::canonicalize(recorded)
            .map(|r| r == live)
            .unwrap_or(false)
        || std::fs::canonicalize(live)
            .ok()
            .zip(std::fs::canonicalize(recorded).ok())
            .is_some_and(|(a, b)| a == b)
}

/// One readiness probe: `GET /readyz` on the loopback hub, true only for a 200.
pub fn ready(addr: SocketAddr, timeout: Duration) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, timeout) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!(
        "GET /readyz HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut head = [0u8; 64];
    let mut got = 0;
    while got < 12 {
        match stream.read(&mut head[got..]) {
            Ok(0) | Err(_) => break,
            Ok(n) => got += n,
        }
    }
    status_is_ok(&head[..got])
}

fn status_is_ok(head: &[u8]) -> bool {
    let line = String::from_utf8_lossy(head);
    let mut parts = line.split(' ');
    matches!(parts.next(), Some("HTTP/1.1" | "HTTP/1.0")) && parts.next() == Some("200")
}

pub fn port_open(addr: SocketAddr, timeout: Duration) -> bool {
    TcpStream::connect_timeout(&addr, timeout).is_ok()
}

/// Poll `ready` until it answers or `deadline` passes; `alive` stops the wait early
/// when the process the shell is waiting for has exited.
pub fn wait_ready(
    addr: SocketAddr,
    deadline: Duration,
    step: Duration,
    alive: &mut dyn FnMut() -> bool,
) -> bool {
    let start = std::time::Instant::now();
    loop {
        if ready(addr, Duration::from_secs(2)) {
            return true;
        }
        if start.elapsed() >= deadline || !alive() {
            return false;
        }
        std::thread::sleep(step);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;
    use std::net::TcpListener;

    fn fs(paths: &[&str]) -> impl Fn(&Path) -> bool {
        let set: HashSet<PathBuf> = paths.iter().map(PathBuf::from).collect();
        move |p: &Path| set.contains(p)
    }

    #[test]
    fn mode_defaults_to_spawn_and_refuses_unknown_values() {
        assert_eq!(parse_mode(None), Ok(Mode::Spawn));
        assert_eq!(parse_mode(Some(" ")), Ok(Mode::Spawn));
        assert_eq!(parse_mode(Some("External")), Ok(Mode::External));
        assert_eq!(parse_mode(Some("off")), Ok(Mode::External));
        assert!(parse_mode(Some("maybe")).unwrap_err().contains(ENV_MODE));
    }

    #[test]
    fn resolution_finds_the_checkout_above_the_executable() {
        let exists = fs(&[
            "/src/nerva/serve.py",
            "/src/nerva/agents/web.py",
            "/src/nerva/.venv/bin/python",
        ]);
        let got = resolve(
            None,
            &[PathBuf::from("/src/nerva/desktop/src-tauri/target/debug")],
            false,
            &exists,
        )
        .unwrap();
        assert_eq!(got.dir, PathBuf::from("/src/nerva"));
        assert_eq!(got.python, PathBuf::from("/src/nerva/.venv/bin/python"));
    }

    #[test]
    fn an_explicit_directory_wins_and_must_be_a_checkout() {
        let exists = fs(&[
            "/a/serve.py",
            "/a/agents/web.py",
            "/a/.venv/bin/python",
            "/b/serve.py",
            "/b/agents/web.py",
            "/b/.venv/bin/python",
        ]);
        let got = resolve(
            Some(Path::new("/b")),
            &[PathBuf::from("/a/x")],
            false,
            &exists,
        )
        .unwrap();
        assert_eq!(got.dir, PathBuf::from("/b"));
        let err = resolve(
            Some(Path::new("/c")),
            &[PathBuf::from("/a/x")],
            false,
            &exists,
        )
        .unwrap_err();
        assert!(err.contains(ENV_DIR));
    }

    #[test]
    fn no_venv_means_no_guessing_a_system_python() {
        let exists = fs(&["/a/serve.py", "/a/agents/web.py"]);
        let err = resolve(None, &[PathBuf::from("/a")], false, &exists).unwrap_err();
        assert!(err.contains("install.sh"));
        let exists = fs(&[
            "/a/serve.py",
            "/a/agents/web.py",
            "/a/.venv/Scripts/python.exe",
        ]);
        assert!(resolve(None, &[PathBuf::from("/a")], true, &exists).is_ok());
        assert!(resolve(None, &[PathBuf::from("/nowhere")], false, &fs(&[])).is_err());
    }

    fn record() -> Record {
        Record {
            pid: 4242,
            started: 1_700_000_000,
            nonce: "0123456789abcdef0123456789abcdef".into(),
            exe: PathBuf::from("/src/nerva/.venv/bin/python"),
            shell: 777,
        }
    }

    #[test]
    fn the_record_round_trips() {
        assert_eq!(Record::decode(&record().encode()), Some(record()));
    }

    #[test]
    fn a_malformed_record_is_absent_and_can_never_lead_to_a_kill() {
        let good = record().encode();
        for bad in [
            String::new(),
            good.replace("version=1", "version=2"),
            good.replace("pid=4242", "pid=1"),
            good.replace("pid=4242", "pid=-3"),
            good.replace("pid=4242", "pid=x"),
            good.replace("0123456789abcdef0123456789abcdef", "short"),
            good.replace("exe=/src/nerva/.venv/bin/python", "exe="),
            good.replace("shell=777\n", ""),
            good.replace("shell=777", "shell=x"),
            format!("{good}pid=7\n"),
            format!("{good}extra=1\n"),
            format!("{good}garbage\n"),
            "x".repeat(RECORD_MAX_BYTES + 1),
        ] {
            assert_eq!(Record::decode(&bad), None, "{bad:?}");
        }
    }

    #[test]
    fn nonces_are_fresh_hex() {
        let (a, b) = (new_nonce(), new_nonce());
        assert!(valid_nonce(&a) && valid_nonce(&b));
        assert_ne!(a, b);
    }

    #[test]
    fn the_claim_policy_never_spawns_over_a_listener_and_readopts_its_own() {
        let seen = |record, record_alive, port_open| Observed {
            record,
            record_alive,
            owner_alive: false,
            port_open,
        };
        // Ours from an earlier launch, healthy or still booting: adopt, never kill.
        assert_eq!(plan(seen(true, true, true), &Mode::Spawn), Plan::Adopt);
        assert_eq!(plan(seen(true, true, false), &Mode::External), Plan::Adopt);
        // Someone else's hub, with or without a stale record: use it, never kill it.
        assert_eq!(
            plan(seen(false, false, true), &Mode::Spawn),
            Plan::UseExternal
        );
        assert_eq!(
            plan(seen(true, false, true), &Mode::Spawn),
            Plan::UseExternal
        );
        // An empty port: start one, unless the owner said external.
        assert_eq!(plan(seen(true, false, false), &Mode::Spawn), Plan::Spawn);
        assert_eq!(plan(seen(false, false, false), &Mode::External), Plan::Wait);
        // A second copy of the app while the first still owns the hub: use, never adopt.
        let twin = Observed {
            owner_alive: true,
            ..seen(true, true, true)
        };
        assert_eq!(plan(twin, &Mode::Spawn), Plan::UseExternal);
    }

    #[test]
    fn stopping_requires_the_recorded_start_time_and_executable() {
        let r = record();
        assert!(may_stop(&r, Some(r.started), Some(&r.exe)));
        // pid reused by another program, or by another python started later.
        assert!(!may_stop(&r, Some(r.started + 1), Some(&r.exe)));
        assert!(!may_stop(
            &r,
            Some(r.started),
            Some(Path::new("/usr/bin/bash"))
        ));
        assert!(!may_stop(&r, None, Some(&r.exe)));
        assert!(!may_stop(&r, Some(r.started), None));
    }

    fn serve_once(reply: &'static [u8]) -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            if let Ok((mut s, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let n = s.read(&mut buf).unwrap_or(0);
                let req = String::from_utf8_lossy(&buf[..n]);
                assert!(req.starts_with("GET /readyz HTTP/1.1\r\n"), "{req}");
                let _ = s.write_all(reply);
            }
        });
        addr
    }

    #[test]
    fn readiness_is_a_200_from_readyz_and_nothing_else() {
        assert!(ready(
            serve_once(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}"),
            Duration::from_secs(2)
        ));
        assert!(!ready(
            serve_once(b"HTTP/1.1 503 Service Unavailable\r\n\r\n"),
            Duration::from_secs(2)
        ));
        assert!(!ready(serve_once(b"garbage"), Duration::from_secs(2)));
        // Nothing listening.
        let addr = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap();
        assert!(!ready(addr, Duration::from_millis(300)));
        assert!(!port_open(addr, Duration::from_millis(300)));
    }

    #[test]
    fn waiting_stops_when_the_process_exits() {
        let addr = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap();
        let start = std::time::Instant::now();
        let ok = wait_ready(
            addr,
            Duration::from_secs(30),
            Duration::from_millis(10),
            &mut || false,
        );
        assert!(!ok);
        assert!(start.elapsed() < Duration::from_secs(10));
    }
}
