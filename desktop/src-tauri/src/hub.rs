//! H171 — carrying out `hub_policy`: observe, spawn, record, adopt, reap, release.
//!
//! The shell never reads, writes or logs the hub's credentials: it starts `serve.py`
//! with the owner's own environment (the hub reads its `.env` itself), probes the
//! unauthenticated `GET /readyz`, and keeps only pid, start time, a launch nonce, the
//! interpreter path and its own pid in its ownership record (mode 0600).
//!
//! Which checkout it may run is named, never searched for, and checked for ownership
//! before every start (`hub_policy::resolve`, `hub_policy::check_launch`). When nothing
//! qualifies the shell starts nothing and tells the owner to start the hub or set
//! `NERVA_DESKTOP_HUB_DIR`.

use crate::hub_policy::{self, Launch, Mode, Observed, Plan, Record};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use sysinfo::{
    Pid, ProcessRefreshKind, ProcessStatus, ProcessesToUpdate, Signal, System, UpdateKind,
};

pub const ADDR: ([u8; 4], u16) = ([127, 0, 0, 1], 8080);
const BOOT_TIMEOUT: Duration = Duration::from_secs(120);
const STOP_GRACE: Duration = Duration::from_secs(10);

/// What the shell owns right now. Managed Tauri state.
pub struct Owner {
    addr: SocketAddr,
    boot_timeout: Duration,
    record_path: PathBuf,
    dir_file: PathBuf,
    log_path: PathBuf,
    record: Mutex<Option<Record>>,
    child: Mutex<Option<Child>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// The shell started (or re-adopted) this hub and stops it on quit.
    Owned,
    /// Someone else's hub; the shell never stops it.
    External,
}

/// The live process at `pid`: its start time and executable.
fn live(pid: u32) -> Option<(u64, Option<PathBuf>)> {
    let mut sys = System::new().ok()?;
    let pid = Pid::from_u32(pid);
    sys.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[pid]),
        true,
        ProcessRefreshKind::nothing().with_exe(UpdateKind::Always),
    );
    // A zombie has already exited; it only waits for its parent to collect it.
    sys.process(pid)
        .filter(|p| p.status() != ProcessStatus::Zombie)
        .map(|p| (p.start_time(), p.exe().map(Path::to_path_buf)))
}

fn still_ours(record: &Record) -> bool {
    match live(record.pid) {
        Some((started, exe)) => hub_policy::may_stop(record, Some(started), exe.as_deref()),
        None => false,
    }
}

impl Owner {
    pub fn new(data_dir: PathBuf, log_dir: PathBuf, config_dir: PathBuf) -> Self {
        Self {
            addr: SocketAddr::from(ADDR),
            boot_timeout: BOOT_TIMEOUT,
            record_path: data_dir.join(hub_policy::RECORD_FILE),
            dir_file: config_dir.join(hub_policy::DIR_FILE),
            log_path: log_dir.join("hub.log"),
            record: Mutex::new(None),
            child: Mutex::new(None),
        }
    }

    fn read_record(&self) -> Option<Record> {
        std::fs::read_to_string(&self.record_path)
            .ok()
            .and_then(|text| Record::decode(&text))
    }

    fn write_record(&self, record: &Record) -> Result<(), String> {
        let parent = self.record_path.parent().ok_or("no data directory")?;
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        let text = record
            .encode()
            .ok_or("the interpreter path cannot be recorded (not UTF-8 or has a newline)")?;
        let temp = self.record_path.with_extension("tmp");
        let _ = std::fs::remove_file(&temp);
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        {
            use std::io::Write;
            let mut file = options.open(&temp).map_err(|e| e.to_string())?;
            file.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
        }
        std::fs::rename(temp, &self.record_path).map_err(|e| e.to_string())
    }

    fn clear_record(&self) {
        let _ = std::fs::remove_file(&self.record_path);
        *self.record.lock().unwrap() = None;
    }

    /// Make sure a hub answers `/readyz`, starting one only when nothing listens.
    /// Blocking: call it off the main thread.
    pub fn ensure(&self) -> Result<Outcome, String> {
        let mode = hub_policy::parse_mode(std::env::var(hub_policy::ENV_MODE).ok().as_deref())
            .unwrap_or_else(|why| {
                eprintln!("{why}");
                Mode::Spawn
            });
        let record = self.read_record();
        let record_alive = record.as_ref().is_some_and(still_ours);
        if record.is_some() && !record_alive {
            // The process is gone or its pid now belongs to something else: forget it,
            // touch nothing.
            self.clear_record();
        }
        let seen = Observed {
            record: record.is_some(),
            record_alive,
            // Another copy of the app that is still running owns it (a reused pid only
            // makes the shell more careful: it then never adopts).
            owner_alive: record
                .as_ref()
                .is_some_and(|r| r.shell != std::process::id() && live(r.shell).is_some()),
            port_open: hub_policy::port_open(self.addr, Duration::from_millis(500)),
        };
        match hub_policy::plan(seen, &mode) {
            Plan::Adopt => {
                let mut record = record.expect("adopt needs a record");
                eprintln!(
                    "Nerva hub: adopting the hub this shell started earlier (pid {})",
                    record.pid
                );
                record.shell = std::process::id();
                self.write_record(&record)?;
                *self.record.lock().unwrap() = Some(record.clone());
                let mut alive = || still_ours(&record);
                if hub_policy::wait_ready(
                    self.addr,
                    self.boot_timeout,
                    Duration::from_millis(500),
                    &mut alive,
                ) {
                    return Ok(Outcome::Owned);
                }
                // An orphan that never became ready: reap it, then start fresh.
                eprintln!("Nerva hub: the earlier hub never became ready; stopping it");
                self.release();
                if mode == Mode::External {
                    return Err("the hub this shell started earlier never became ready".into());
                }
                if hub_policy::port_open(self.addr, Duration::from_millis(500)) {
                    return self.wait_external();
                }
                self.spawn_or_wait()
            }
            Plan::UseExternal | Plan::Wait => self.wait_external(),
            Plan::Spawn => self.spawn_or_wait(),
        }
    }

    /// Start a hub from a checkout that passes every check; otherwise start nothing,
    /// say why, and wait for one the owner starts.
    fn spawn_or_wait(&self) -> Result<Outcome, String> {
        match self.resolve() {
            Ok(launch) => self.spawn(launch),
            Err(why) => {
                eprintln!("Nerva hub: not starting one: {why}");
                let _ = notify_rust::Notification::new()
                    .appname("Nerva")
                    .summary("Start the Nerva hub yourself")
                    .body(&crate::notify::clean(
                        &format!(
                            "Run start.sh, or set {} to your Nerva folder. {why}",
                            hub_policy::ENV_DIR
                        ),
                        200,
                    ))
                    .show();
                self.wait_external()
            }
        }
    }

    fn wait_external(&self) -> Result<Outcome, String> {
        if hub_policy::wait_ready(
            self.addr,
            self.boot_timeout,
            Duration::from_millis(500),
            &mut || true,
        ) {
            Ok(Outcome::External)
        } else {
            Err(format!("no Nerva hub became ready at http://{}", self.addr))
        }
    }

    /// The checkout named by `NERVA_DESKTOP_HUB_DIR`, else by `hub-dir.txt` in the app's
    /// config folder, else the fixed dev layout around the executable — never the
    /// working directory and never any other ancestor — and only if it passes the
    /// ownership checks.
    fn resolve(&self) -> Result<Launch, String> {
        #[cfg(unix)]
        let uid = unsafe { libc::getuid() };
        let explicit = match std::env::var_os(hub_policy::ENV_DIR) {
            Some(dir) => Some(PathBuf::from(dir)),
            None if self.dir_file.exists() => {
                #[cfg(unix)]
                hub_policy::trusted_path(&self.dir_file, uid)
                    .map_err(|why| format!("{}: {why}", hub_policy::DIR_FILE))?;
                let text = std::fs::read_to_string(&self.dir_file)
                    .map_err(|e| format!("{}: {e}", self.dir_file.display()))?;
                Some(hub_policy::parse_dir_file(&text)?)
            }
            None => None,
        };
        let exes: Vec<PathBuf> = std::env::current_exe().into_iter().collect();
        let launch =
            hub_policy::resolve(explicit.as_deref(), &exes, cfg!(windows), &|p: &Path| {
                p.exists()
            })?;
        #[cfg(unix)]
        hub_policy::check_launch(&launch, uid)
            .map_err(|why| format!("{} is not safe to run: {why}", launch.dir.display()))?;
        Ok(launch)
    }

    fn spawn(&self, launch: Launch) -> Result<Outcome, String> {
        if let Some(parent) = self.log_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let log = std::fs::File::create(&self.log_path).map_err(|e| e.to_string())?;
        let err_log = log.try_clone().map_err(|e| e.to_string())?;
        let mut command = Command::new(&launch.python);
        command
            .arg("serve.py")
            .current_dir(&launch.dir)
            .stdin(Stdio::null())
            .stdout(log)
            .stderr(err_log);
        // The same default start.sh / START.bat apply; a HUD choice the owner made wins.
        if std::env::var_os("NERVA_HUD").is_none() && std::env::var_os("JARVIS_HUD").is_none() {
            command.env("JARVIS_HUD", "v2");
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = command
            .spawn()
            .map_err(|e| format!("could not start {}: {e}", launch.python.display()))?;
        let pid = child.id();
        // The OS may need a moment to publish the new process's details.
        let mut details = None;
        for _ in 0..20 {
            if let Some((started, exe)) = live(pid) {
                details = Some((started, exe.unwrap_or_else(|| launch.python.clone())));
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let Some((started, exe)) = details else {
            let _ = child.kill();
            let _ = child.wait();
            return Err("the hub exited as soon as it started; see hub.log".into());
        };
        let record = Record {
            pid,
            started,
            nonce: hub_policy::new_nonce(),
            exe,
            shell: std::process::id(),
        };
        self.write_record(&record)?;
        eprintln!(
            "Nerva hub: started pid {pid} (launch {}), log {}",
            record.nonce,
            self.log_path.display()
        );
        *self.record.lock().unwrap() = Some(record);
        *self.child.lock().unwrap() = Some(child);
        let mut alive = || {
            self.child
                .lock()
                .unwrap()
                .as_mut()
                .is_some_and(|c| matches!(c.try_wait(), Ok(None)))
        };
        if hub_policy::wait_ready(
            self.addr,
            self.boot_timeout,
            Duration::from_millis(500),
            &mut alive,
        ) {
            return Ok(Outcome::Owned);
        }
        self.release();
        // Another hub took the port while ours was starting (ours then exits on the
        // bind): use that one rather than report a failure.
        if hub_policy::port_open(self.addr, Duration::from_millis(500)) {
            return self.wait_external();
        }
        Err(format!(
            "the hub did not become ready; see {}",
            self.log_path.display()
        ))
    }

    /// Stop the hub this shell owns, and only that one: the live process must still
    /// carry the recorded start time and executable. A hub the shell did not start is
    /// never touched.
    pub fn release(&self) {
        let record = self.record.lock().unwrap().clone();
        let mut child = self.child.lock().unwrap().take();
        if let Some(record) = record {
            stop(&record, child.as_mut());
            self.clear_record();
        }
        if let Some(mut child) = child {
            let _ = child.wait();
        }
    }
}

/// Whether the process is still the one we own. Our own child cannot have its pid
/// reused before it is waited for, so it is asked directly; an adopted hub from an
/// earlier launch must still have the recorded start time and executable (a pid whose
/// start time changed is a different process: ours is gone).
fn still_running(record: &Record, child: &mut Option<&mut Child>) -> bool {
    match child {
        Some(c) => matches!(c.try_wait(), Ok(None)),
        None => still_ours(record),
    }
}

fn signal(pid: u32, how: Option<Signal>) -> Option<bool> {
    let mut sys = System::new().ok()?;
    let spid = Pid::from_u32(pid);
    sys.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[spid]),
        true,
        ProcessRefreshKind::nothing(),
    );
    let process = sys.process(spid)?;
    match how {
        Some(sig) => process.kill_with(sig),
        None => Some(process.kill()),
    }
}

/// End it outright, re-checking ownership right before.
fn hard_stop(record: &Record, child: &mut Option<&mut Child>) {
    match child {
        Some(c) => {
            let _ = c.kill();
        }
        None => {
            if still_ours(record) {
                let _ = signal(record.pid, None);
            }
        }
    }
}

fn stop(record: &Record, mut child: Option<&mut Child>) {
    if !still_running(record, &mut child) {
        return;
    }
    // A polite stop first (the hub flushes its stores on SIGTERM); Windows has no
    // equivalent for a windowless child, so it is stopped outright there.
    if signal(record.pid, Some(Signal::Term)).is_none() {
        hard_stop(record, &mut child);
        return;
    }
    let deadline = std::time::Instant::now() + STOP_GRACE;
    while std::time::Instant::now() < deadline {
        if !still_running(record, &mut child) {
            return;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    eprintln!(
        "Nerva hub: pid {} ignored the stop request; ending it",
        record.pid
    );
    hard_stop(record, &mut child);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    /// A stand-in checkout whose `serve.py` answers `/readyz` on a test port.
    fn fake_checkout(root: &Path, port: u16) -> PathBuf {
        let dir = root.join("checkout");
        std::fs::create_dir_all(dir.join("agents")).unwrap();
        std::fs::create_dir_all(dir.join(".venv").join("bin")).unwrap();
        std::fs::write(dir.join("agents").join("web.py"), "").unwrap();
        std::fs::write(
            dir.join("serve.py"),
            format!(
                "import http.server\n\
                 class H(http.server.BaseHTTPRequestHandler):\n\
                 \x20   def do_GET(self):\n\
                 \x20       self.send_response(200 if self.path == '/readyz' else 404)\n\
                 \x20       self.end_headers()\n\
                 http.server.HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n"
            ),
        )
        .unwrap();
        let python = which("python3").expect("python3 on PATH");
        std::os::unix::fs::symlink(python, dir.join(".venv").join("bin").join("python")).unwrap();
        dir
    }

    fn which(name: &str) -> Option<PathBuf> {
        std::env::var_os("PATH")?
            .to_str()?
            .split(':')
            .map(|d| Path::new(d).join(name))
            .find(|p| p.exists())
    }

    /// End to end on a real process: spawn, record, re-adopt after a "crash" of the
    /// shell, stop on quit, and never stop a hub the shell did not start.
    #[test]
    #[cfg(unix)]
    #[ignore = "starts python3; run with --ignored"]
    fn the_shell_starts_adopts_and_stops_only_its_own_hub() {
        // What a runner's umask would otherwise make group-writable (and so refused).
        unsafe { libc::umask(0o022) };
        // Not the shared temp directory: the trust check refuses a checkout under it.
        let home = PathBuf::from(std::env::var_os("HOME").expect("HOME"));
        let root = home
            .join(".cache")
            .join(format!("nerva-hub-test-{}", hub_policy::new_nonce()));
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let dir = fake_checkout(&root, port);
        std::env::set_var(hub_policy::ENV_DIR, &dir);
        std::env::remove_var(hub_policy::ENV_MODE);
        let owner = |timeout| {
            let mut o = Owner::new(root.join("data"), root.join("logs"), root.join("config"));
            o.addr = SocketAddr::from(([127, 0, 0, 1], port));
            o.boot_timeout = timeout;
            o
        };

        let first = owner(Duration::from_secs(20));
        assert_eq!(first.ensure(), Ok(Outcome::Owned));
        let record = first.read_record().expect("an ownership record");
        assert!(still_ours(&record));
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&first.record_path)
                .unwrap()
                .permissions()
                .mode();
            assert_eq!(mode & 0o777, 0o600, "the record is the owner's alone");
        }

        // The shell "crashed": a new shell finds its record and adopts the healthy hub.
        let second = owner(Duration::from_secs(20));
        assert_eq!(second.ensure(), Ok(Outcome::Owned));
        assert_eq!(second.read_record(), Some(record.clone()));

        // Quit stops it and drops the record.
        second.release();
        assert!(second.read_record().is_none());
        assert!(!hub_policy::port_open(
            second.addr,
            Duration::from_millis(300)
        ));
        assert!(live(record.pid).is_none() || !still_ours(&record));

        // A hub someone else runs is used and never stopped.
        let mut theirs = std::process::Command::new(dir.join(".venv/bin/python"))
            .arg("serve.py")
            .current_dir(&dir)
            .spawn()
            .unwrap();
        let third = owner(Duration::from_secs(20));
        assert!(hub_policy::wait_ready(
            third.addr,
            Duration::from_secs(20),
            Duration::from_millis(100),
            &mut || true
        ));
        assert_eq!(third.ensure(), Ok(Outcome::External));
        third.release();
        assert!(
            matches!(theirs.try_wait(), Ok(None)),
            "an external hub survives quit"
        );
        assert!(third.read_record().is_none());

        // A forged record naming that external process (wrong start time) is ignored.
        third
            .write_record(&Record {
                pid: theirs.id(),
                started: 1,
                nonce: hub_policy::new_nonce(),
                exe: dir.join(".venv/bin/python"),
                shell: std::process::id(),
            })
            .unwrap();
        assert_eq!(third.ensure(), Ok(Outcome::External));
        third.release();
        assert!(
            matches!(theirs.try_wait(), Ok(None)),
            "a forged record kills nothing"
        );
        assert!(third.read_record().is_none(), "the stale record is dropped");

        let _ = theirs.kill();
        let _ = theirs.wait();
        std::env::remove_var(hub_policy::ENV_DIR);
        // The same checkout under the shared temp directory is refused: nothing starts.
        let shared =
            std::env::temp_dir().join(format!("nerva-hub-test-{}", hub_policy::new_nonce()));
        let planted = fake_checkout(&shared, port);
        std::env::set_var(hub_policy::ENV_DIR, &planted);
        let why = third.resolve().unwrap_err();
        assert!(why.contains("not safe to run"), "{why}");
        // A per-user hub-dir.txt names the checkout when the variable is unset.
        std::env::remove_var(hub_policy::ENV_DIR);
        std::fs::create_dir_all(root.join("config")).unwrap();
        std::fs::write(
            root.join("config").join(hub_policy::DIR_FILE),
            dir.to_str().unwrap(),
        )
        .unwrap();
        assert_eq!(third.resolve().map(|l| l.dir), Ok(dir.clone()));
        let _ = std::fs::remove_dir_all(&shared);
        let _ = std::fs::remove_dir_all(&root);
    }
}
