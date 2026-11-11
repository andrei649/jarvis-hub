//! H171 — the desktop shell owns the hub process it starts, and only that one.
//!
//! Pure policy, std only (the pytest suite compiles it with `rustc --test`, no GUI
//! libraries needed). `main.rs` supplies the observations (is a recorded process still
//! the one we started? does the hub answer?) and carries out the plan.
//!
//! * **Resolve**: `NERVA_DESKTOP_HUB=external` never starts a hub. Otherwise the
//!   checkout is named, never searched for: `NERVA_DESKTOP_HUB_DIR`, else the one line
//!   of `hub-dir.txt` in the app's config directory, else — for a development run only —
//!   the fixed layout `<checkout>/desktop/src-tauri/target/{debug,release}/<exe>`. The
//!   working directory is never consulted and no other ancestor of the executable is
//!   searched (an AppImage runs from a mount under the shared temp directory).
//! * **Trust**: before anything runs, the checkout and every ancestor up to `/` must
//!   belong to root or the current user and be writable by nobody else (a sticky,
//!   world-writable directory such as `/tmp` is refused); `serve.py`, `agents/`, `.venv`
//!   and `.venv/bin` must stay inside the checkout; the interpreter `.venv/bin/python`
//!   points to may be the system or a pyenv Python, but it and its whole path must pass
//!   the same ownership check. The interpreter is that checkout's `.venv` (the one
//!   `install.sh` / `INSTALL.bat` make); without it the shell refuses to guess a system
//!   Python. A refusal says why and nothing is started.
//! * **Ownership record**: pid, the process's start time, the interpreter, the owning
//!   shell's pid and a per-launch nonce (a label for logs; it proves nothing), written
//!   atomically and readable only by the owner. A pid alone is not proof — pids are
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
/// The per-user setting naming the checkout, in the app's config directory.
pub const DIR_FILE: &str = "hub-dir.txt";
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

/// The fixed development layout: a shell built inside its own checkout, at
/// `<checkout>/desktop/src-tauri/target/{debug,release}/<exe>`. Nothing else above the
/// executable is ever considered.
pub fn dev_checkout(exe: &Path) -> Option<PathBuf> {
    let name = |p: &Path| p.file_name().and_then(|n| n.to_str()).map(str::to_string);
    let profile = exe.parent()?;
    if !matches!(name(profile)?.as_str(), "debug" | "release") {
        return None;
    }
    let target = profile.parent()?;
    let tauri = target.parent()?;
    let desktop = tauri.parent()?;
    if name(target)? != "target" || name(tauri)? != "src-tauri" || name(desktop)? != "desktop" {
        return None;
    }
    desktop.parent().map(Path::to_path_buf)
}

/// The one line of `hub-dir.txt`: an absolute path, nothing else.
pub fn parse_dir_file(text: &str) -> Result<PathBuf, String> {
    let line = text.trim();
    if line.is_empty() || line.len() > 4096 || line.contains('\n') || line.contains('\0') {
        return Err(format!("{DIR_FILE} must hold one absolute path"));
    }
    let path = PathBuf::from(line);
    if !path.is_absolute() {
        return Err(format!("{DIR_FILE} must hold one absolute path"));
    }
    Ok(path)
}

/// The resolution ladder. `explicit` is `NERVA_DESKTOP_HUB_DIR` or `hub-dir.txt`;
/// `exes` are the shell's executable paths, used only for the fixed dev layout.
pub fn resolve(
    explicit: Option<&Path>,
    exes: &[PathBuf],
    windows: bool,
    exists: &dyn Fn(&Path) -> bool,
) -> Result<Launch, String> {
    let dir = if let Some(dir) = explicit {
        if !dir.is_absolute() {
            return Err(format!("{ENV_DIR} must be an absolute path"));
        }
        if !is_checkout(dir, exists) {
            return Err(format!(
                "{ENV_DIR}={} has no serve.py and agents/web.py",
                dir.display()
            ));
        }
        dir.to_path_buf()
    } else {
        exes.iter()
            .filter_map(|exe| dev_checkout(exe))
            .find(|dir| is_checkout(dir, exists))
            .ok_or_else(|| {
                format!(
                    "no Nerva checkout is configured; start the hub yourself (start.sh) or set \
                     {ENV_DIR} (or put the path in {DIR_FILE} in the app's config folder)"
                )
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

/// `path` (resolved) and every ancestor up to `/` belong to root or `uid` and are
/// writable by nobody else. A sticky world-writable directory (`/tmp`) is refused too:
/// anyone can create a name in it.
#[cfg(unix)]
pub fn trusted_path(path: &Path, uid: u32) -> Result<(), String> {
    use std::os::unix::fs::MetadataExt;
    let real = std::fs::canonicalize(path).map_err(|e| format!("{}: {e}", path.display()))?;
    for p in real.ancestors() {
        let meta = std::fs::metadata(p).map_err(|e| format!("{}: {e}", p.display()))?;
        if meta.uid() != 0 && meta.uid() != uid {
            return Err(format!("{} belongs to another user", p.display()));
        }
        if meta.mode() & 0o022 != 0 {
            return Err(format!(
                "{} is writable by other users (group or world)",
                p.display()
            ));
        }
    }
    Ok(())
}

/// Whether the shell may run this checkout's interpreter. Checked before every spawn;
/// the error names the path that failed. Unix only: Windows ACLs are not inspected
/// (the checkout must still be named explicitly or be the dev layout).
#[cfg(unix)]
pub fn check_launch(launch: &Launch, uid: u32) -> Result<(), String> {
    let dir =
        std::fs::canonicalize(&launch.dir).map_err(|e| format!("{}: {e}", launch.dir.display()))?;
    for rel in ["serve.py", "agents", "agents/web.py", ".venv", ".venv/bin"] {
        let real = std::fs::canonicalize(dir.join(rel))
            .map_err(|e| format!("{}: {e}", dir.join(rel).display()))?;
        if !real.starts_with(&dir) {
            return Err(format!(
                "{} resolves outside the checkout ({})",
                dir.join(rel).display(),
                real.display()
            ));
        }
    }
    trusted_path(&dir, uid)?;
    for rel in ["serve.py", "agents", "agents/web.py", ".venv", ".venv/bin"] {
        trusted_path(&dir.join(rel), uid)?;
    }
    // The venv's python is usually a link to the system or a pyenv interpreter; what it
    // resolves to must pass the same check (root's /usr/bin/python3 does).
    trusted_path(&launch.python, uid)
        .map_err(|why| format!("the interpreter {}: {why}", launch.python.display()))
}

/// The shell's proof that it started a process.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Record {
    pub pid: u32,
    /// The process's start time as the OS reports it (seconds since the epoch).
    pub started: u64,
    /// A fresh random value per launch: a label for the launch in logs and the record.
    /// It is not verified and proves nothing; the start time and executable do.
    pub nonce: String,
    /// The interpreter that was started, compared against the live process.
    pub exe: PathBuf,
    /// The shell process that owns the hub now. While it is alive (a second copy of
    /// the app started without the single-instance hand-off) the hub is not adopted
    /// again, so only one shell ever stops it.
    pub shell: u32,
}

impl Record {
    /// `None` when a field would break the line format (a newline in the path).
    pub fn encode(&self) -> Option<String> {
        let exe = self.exe.to_str()?;
        if exe.is_empty() || exe.contains(['\n', '\r', '\0']) || !valid_nonce(&self.nonce) {
            return None;
        }
        Some(format!(
            "version=1\npid={}\nstarted={}\nnonce={}\nexe={}\nshell={}\n",
            self.pid, self.started, self.nonce, exe, self.shell
        ))
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
    fn only_the_fixed_dev_layout_is_found_from_the_executable() {
        assert_eq!(
            dev_checkout(Path::new(
                "/src/nerva/desktop/src-tauri/target/release/nerva"
            )),
            Some(PathBuf::from("/src/nerva"))
        );
        for exe in [
            "/usr/bin/jarvis-hub-desktop",
            "/tmp/.mount_NervaAbC/usr/bin/jarvis-hub-desktop",
            "/src/nerva/desktop/src-tauri/target/debug/deps/x",
            "/src/nerva/desktop/x/target/debug/x",
            "/src/nerva/other/src-tauri/target/debug/x",
            "/target/debug/x",
        ] {
            assert_eq!(dev_checkout(Path::new(exe)), None, "{exe}");
        }
    }

    #[test]
    fn a_planted_checkout_above_an_installed_shell_or_in_the_cwd_is_never_used() {
        // AppImage: the exe lives in $TMPDIR/.mount_*/usr/bin; /tmp holds planted files.
        let exists = fs(&[
            "/tmp/serve.py",
            "/tmp/agents/web.py",
            "/tmp/.venv/bin/python",
            "/home/u/Downloads/pkg/serve.py",
            "/home/u/Downloads/pkg/agents/web.py",
            "/home/u/Downloads/pkg/.venv/bin/python",
        ]);
        for starts in [
            vec![PathBuf::from(
                "/tmp/.mount_NervaAbC123/usr/bin/jarvis-hub-desktop",
            )],
            vec![
                PathBuf::from("/usr/bin/jarvis-hub-desktop"),
                PathBuf::from("/home/u/Downloads/pkg/sub"),
                PathBuf::from("/home/u/Downloads/pkg"),
            ],
        ] {
            assert!(
                resolve(None, &starts, false, &exists).is_err(),
                "{starts:?}"
            );
        }
        assert!(resolve(Some(Path::new("relative/dir")), &[], false, &exists).is_err());
    }

    #[test]
    fn the_dir_file_holds_one_absolute_path() {
        assert_eq!(
            parse_dir_file(" /src/nerva \n"),
            Ok(PathBuf::from("/src/nerva"))
        );
        for bad in ["", "relative", "/a\n/b", "/a\0"] {
            assert!(parse_dir_file(bad).is_err(), "{bad:?}");
        }
    }

    #[cfg(unix)]
    fn my_uid(dir: &Path) -> u32 {
        use std::os::unix::fs::MetadataExt;
        let probe = dir.join("uid-probe");
        std::fs::write(&probe, b"").unwrap();
        std::fs::metadata(&probe).unwrap().uid()
    }

    #[cfg(unix)]
    #[test]
    fn shared_or_foreign_directories_are_not_trusted() {
        use std::os::unix::fs::PermissionsExt;
        let base = std::env::temp_dir().join(format!("hp-trust-{}", new_nonce()));
        std::fs::create_dir_all(&base).unwrap();
        let uid = my_uid(&base);
        // root's system directories are fine for root and for a user alike.
        assert!(trusted_path(Path::new("/"), uid).is_ok());
        assert!(trusted_path(Path::new("/"), uid + 12345).is_ok());
        // A world-writable directory is refused, and so is anything beneath it.
        let open = base.join("open");
        std::fs::create_dir_all(open.join("inner")).unwrap();
        std::fs::set_permissions(&open, std::fs::Permissions::from_mode(0o1777)).unwrap();
        let err = trusted_path(&open.join("inner"), uid).unwrap_err();
        assert!(err.contains("writable by other users"), "{err}");
        let _ = std::fs::remove_dir_all(&base);
    }

    #[cfg(unix)]
    #[test]
    fn a_venv_linked_outside_the_checkout_is_refused() {
        let base = std::env::temp_dir().join(format!("hp-venv-{}", new_nonce()));
        let dir = base.join("checkout");
        let elsewhere = base.join("elsewhere");
        std::fs::create_dir_all(dir.join("agents")).unwrap();
        std::fs::create_dir_all(elsewhere.join("bin")).unwrap();
        std::fs::write(dir.join("serve.py"), b"").unwrap();
        std::fs::write(dir.join("agents/web.py"), b"").unwrap();
        std::fs::write(elsewhere.join("bin/python"), b"").unwrap();
        std::os::unix::fs::symlink(&elsewhere, dir.join(".venv")).unwrap();
        let uid = my_uid(&base);
        let launch = Launch {
            python: dir.join(".venv/bin/python"),
            dir: dir.clone(),
        };
        let err = check_launch(&launch, uid).unwrap_err();
        assert!(err.contains("outside the checkout"), "{err}");
        // In the shared temp directory the checkout itself is refused as well.
        std::fs::remove_file(dir.join(".venv")).unwrap();
        std::fs::create_dir_all(dir.join(".venv/bin")).unwrap();
        std::fs::write(dir.join(".venv/bin/python"), b"").unwrap();
        let err = check_launch(&launch, uid).unwrap_err();
        assert!(err.contains("writable by other users"), "{err}");
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn the_dev_layout_resolves_its_own_checkout() {
        let exists = fs(&[
            "/src/nerva/serve.py",
            "/src/nerva/agents/web.py",
            "/src/nerva/.venv/bin/python",
        ]);
        let got = resolve(
            None,
            &[PathBuf::from(
                "/src/nerva/desktop/src-tauri/target/debug/jarvis-hub-desktop",
            )],
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
        let err = resolve(Some(Path::new("/a")), &[], false, &exists).unwrap_err();
        assert!(err.contains("install.sh"));
        let exists = fs(&[
            "/a/serve.py",
            "/a/agents/web.py",
            "/a/.venv/Scripts/python.exe",
        ]);
        assert!(resolve(Some(Path::new("/a")), &[], true, &exists).is_ok());
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
        assert_eq!(Record::decode(&record().encode().unwrap()), Some(record()));
        // A field that would break the line format is never written.
        let mut bad = record();
        bad.exe = PathBuf::from("/x\npid=1");
        assert_eq!(bad.encode(), None);
    }

    #[test]
    fn a_malformed_record_is_absent_and_can_never_lead_to_a_kill() {
        let good = record().encode().unwrap();
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
