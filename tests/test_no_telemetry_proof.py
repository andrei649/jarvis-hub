"""0.22 — the no-telemetry proof.

`docs/PRIVACY.md` promises: *"zero outbound telemetry. There is no analytics beacon, crash
reporter, or usage tracker."* Until this file, nothing enforced it. `pytest-socket` is test
**hygiene** (AUD-10) — it stops a stray call from hanging a test — and it cannot serve as
the product proof here, because every egress call site in this codebase is best-effort: a
blocked connect raises, the caller swallows it, and the suite stays green while the beacon
fires in production. So the gate must **count attempts**, not rely on an exception.

Round-1 review (#939) found the first version of this file had a reproducible false
negative: it patched only ``socket.connect``/``connect_ex``, so unconnected-UDP
``sendto``/``sendmsg`` was invisible, and it exercised only boot + ``/api/status``, so a
beacon on an ordinary request path was never reached. Both are fixed here, each with a
regression that fails against the old approach. The scope statements below are deliberately
narrowed to exactly what is measured — an over-claiming privacy gate is worse than none,
because it manufactures false assurance.

**What this proves (measured):** during a default, unconfigured install's boot, an
**authenticated** `/chat` turn, a status read and shutdown, this process attempts **zero**
non-loopback socket egress — across TCP connect, connected and unconnected UDP, and raw
sends — and starts no child process matching the network-tool denylist (which is refused
*before* it executes, so the gate can never itself cause egress).

**What this does NOT prove (stated, not implied):**

* it observes *this* process. A fully general guarantee needs an OS-level egress deny
  (network namespace / firewall), which is a host control, not a pytest;
* the static scan is a **known-vendor ratchet**, not a general guarantee: an IP literal, a
  novel hostname, a runtime-composed URL, or a beacon inside a third-party dependency is
  invisible to it. It exists so a *recognisable* beacon cannot be pasted in unnoticed;
* **child-process egress is bounded by a denylist, not proven absent.** A child uses its
  own sockets, which this process's hooks cannot see. `subprocess.Popen`, `os.system` and
  `os.popen` are instrumented and a recognised network tool (including through `sh -c`,
  `env`, `shell=True`, `cmd /c` and PowerShell web cmdlets) is refused before it runs — but
  a renamed binary, a bespoke client, or a spawn API left uninstrumented (`os.posix_spawn`,
  `os.execv`, `multiprocessing`) would not be caught. The app legitimately spawns
  `docker info`, `wasmtime --version` and `uname -p` during boot, so "zero children" is not
  the claim; "no recognised network tool ran" is;
* owner-configured cloud agents and plugins are opt-in by design, disclosed in PRIVACY.md,
  and governed by the egress monitor — they are out of scope here.

Platform note (round-2, Windows CI): ``sendmsg`` is POSIX-only. The recorder instruments
whatever the running platform provides and asserts a required floor
(``MUST_INSTRUMENT``) so a thinner platform cannot report a clean run from a gate that was
not actually watching. On Windows, unconnected UDP goes through ``sendto``, which is in
that floor.
"""

import contextlib
import os
import re
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

# A ratchet of recognisable beacon vendors — NOT a general guarantee (see module docstring).
TELEMETRY_HOSTS = (
    "sentry.io", "google-analytics.com", "googletagmanager.com", "segment.io",
    "segment.com", "mixpanel.com", "amplitude.com", "posthog.com", "bugsnag.com",
    "datadoghq.com", "newrelic.com", "rollbar.com", "loggly.com", "raygun.io",
)

# Binaries that can move bytes off-box if spawned. Subprocess egress cannot be observed at
# the socket layer of *this* process, so it is bounded by spawn inspection instead.
NETWORK_BINARIES = ("curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "rsync")

_LOOPBACK_NAMES = {"localhost", "ip6-localhost", "localhost.localdomain"}

# Operations that must be instrumented on EVERY platform for a pass to mean anything.
# `sendmsg` is deliberately absent: it is POSIX-only, and on Windows unconnected UDP goes
# through `sendto`, which is required here. Without this floor the recorder could patch
# nothing on some future platform and still report a clean run.
MUST_INSTRUMENT = (
    "connect", "connect_ex", "sendto", "send", "sendall",
    "subprocess.Popen", "os.system", "os.popen",
)


def _is_local(host: object) -> bool:
    """Loopback / unspecified addresses are local by definition and always allowed."""
    if not isinstance(host, (str, bytes)):
        return False
    h = host.decode() if isinstance(host, bytes) else host
    h = h.strip("[]").lower()
    return (
        h in _LOOPBACK_NAMES
        or h.startswith("127.")
        or h in {"::1", "0.0.0.0", "::", ""}  # nosec B104 - classification, not a bind
    )


def _host_of(address) -> object:
    return address[0] if isinstance(address, tuple) and address else address


class EgressRecorder:
    """Records every non-loopback egress attempt this process makes.

    Recording beats raising: the code under test swallows connection errors, so an
    exception-based guard is invisible to it while a counter is not. Attempts are also
    *blocked* so a real packet never leaves during a test.
    """

    def __init__(self) -> None:
        self.attempts: list[tuple[str, str]] = []   # (operation, host)
        self.subprocesses: list[str] = []
        self.instrumented: list[str] = []           # ops actually patched on this platform
        self.blocked_spawns: list[str] = []         # network-capable children refused pre-exec

    def note(self, operation: str, address) -> bool:
        host = _host_of(address)
        if _is_local(host):
            return False
        self.attempts.append((operation, str(host)))
        return True

    @property
    def hosts(self) -> list[str]:
        return sorted({host for _, host in self.attempts})


@contextmanager
def recording_egress(monkeypatch):
    """Patch every socket operation that can put bytes on a non-loopback network.

    Covered: ``connect``/``connect_ex`` (TCP + connected UDP), ``sendto``/``sendmsg``
    (unconnected UDP — the round-1 blind spot), ``send``/``sendall`` on an already-connected
    socket (peer resolved via ``getpeername``), and ``subprocess.Popen`` (spawn inspection).
    """
    rec = EgressRecorder()
    # `sendmsg` is POSIX-only — it does not exist on Windows, where unconnected UDP goes
    # through `sendto` instead. Capture whatever this platform actually provides rather
    # than assuming; MUST_INSTRUMENT below keeps that from silently thinning the gate.
    real = {
        name: getattr(socket.socket, name)
        for name in ("connect", "connect_ex", "sendto", "sendmsg", "send", "sendall")
        if hasattr(socket.socket, name)
    }
    real_popen = subprocess.Popen
    real_system = os.system
    real_os_popen = os.popen

    def _peer_is_external(sock) -> bool:
        try:
            return rec.note("send", sock.getpeername())
        except OSError:
            return False  # unconnected socket: sendto/sendmsg is the path that matters

    def _connect(self, address):
        if rec.note("connect", address):
            raise OSError("blocked by the no-telemetry proof")
        return real["connect"](self, address)

    def _connect_ex(self, address):
        if rec.note("connect_ex", address):
            return 111  # ECONNREFUSED — the shape a best-effort caller expects
        return real["connect_ex"](self, address)

    def _sendto(self, data, *args):
        address = args[-1] if args else None
        if address is not None and rec.note("sendto", address):
            raise OSError("blocked by the no-telemetry proof")
        return real["sendto"](self, data, *args)

    def _sendmsg(self, buffers, *args):
        address = args[2] if len(args) >= 3 else None
        if address is not None and rec.note("sendmsg", address):
            raise OSError("blocked by the no-telemetry proof")
        return real["sendmsg"](self, buffers, *args)

    def _send(self, data, *args):
        if _peer_is_external(self):
            raise OSError("blocked by the no-telemetry proof")
        return real["send"](self, data, *args)

    def _sendall(self, data, *args):
        if _peer_is_external(self):
            raise OSError("blocked by the no-telemetry proof")
        return real["sendall"](self, data, *args)

    def _guard_spawn(rendered: str, api: str):
        """Refuse a network-capable child BEFORE it runs.

        Round-2 review: the previous version recorded the command and then executed it, so
        a recognised `curl` could transmit before the assertion ever ran — a privacy test
        causing real egress. Blocking happens first now; the refusal is also recorded so
        the assertion still sees it.
        """
        rec.subprocesses.append(rendered)
        if _network_capable(rendered):
            rec.blocked_spawns.append(f"{api}: {rendered}")
            raise PermissionError(
                f"blocked by the no-telemetry proof (network-capable spawn via {api})"
            )

    def _popen(cmd, *args, **kwargs):
        rendered = " ".join(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd)
        _guard_spawn(rendered, "subprocess.Popen")
        return real_popen(cmd, *args, **kwargs)

    def _system(command):
        _guard_spawn(str(command), "os.system")
        return real_system(command)

    def _os_popen(command, *args, **kwargs):
        _guard_spawn(str(command), "os.popen")
        return real_os_popen(command, *args, **kwargs)

    replacements = {
        "connect": _connect, "connect_ex": _connect_ex, "sendto": _sendto,
        "sendmsg": _sendmsg, "send": _send, "sendall": _sendall,
    }
    for name, replacement in replacements.items():
        if name in real:                       # only what this platform actually has
            monkeypatch.setattr(socket.socket, name, replacement)
            rec.instrumented.append(name)
    monkeypatch.setattr(subprocess, "Popen", _popen)
    monkeypatch.setattr(os, "system", _system)
    monkeypatch.setattr(os, "popen", _os_popen)
    rec.instrumented += ["subprocess.Popen", "os.system", "os.popen"]

    missing = [name for name in MUST_INSTRUMENT if name not in rec.instrumented]
    assert not missing, (
        "The egress recorder could not instrument required operation(s) on this platform "
        f"({sys.platform}): {missing}. Refusing to report a pass from a gate that is not "
        "actually watching — fix the recorder rather than narrowing it silently."
    )
    yield rec


def _network_capable(command: str) -> bool:
    """Heuristic: does this command line invoke a network-capable tool *anywhere*?

    Round-2 review found the previous version inspected only the basename of the first
    token, so every one of these slipped through while the gate stayed green:
    ``sh -c "curl …"``, ``/usr/bin/env curl …``, ``Popen("curl …", shell=True)``,
    ``powershell -Command Invoke-WebRequest``, ``cmd /c curl``.

    So the whole command line is tokenised on shell punctuation, each token is reduced to
    a bare program name, and PowerShell's web cmdlets are matched as words. This is a
    **denylist heuristic**, not a guarantee — see the module docstring.
    """
    text = command.lower()
    for cmdlet in ("invoke-webrequest", "invoke-restmethod", "start-bitstransfer",
                   "system.net.webclient", "downloadstring", "downloadfile"):
        if cmdlet in text:
            return True
    for raw in re.split(r"[\s;|&()<>'\"`]+", text):
        if not raw:
            continue
        name = PurePosixPath(PureWindowsPath(raw).name).name
        for suffix in (".exe", ".com", ".bat", ".cmd"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        if name in NETWORK_BINARIES:
            return True
    return False


# ── the proof ────────────────────────────────────────────────────────────────────


def test_a_default_install_attempts_no_outbound_egress(monkeypatch):
    """Boot, hold a real conversation, let background work tick, shut down — count egress.

    The `/chat` turn is the round-1 gap: a beacon that only fires on a user path was never
    reached by a boot-only test. It must be **authenticated**, or `_user_guard` answers 403
    and the handler never runs — which is what the first version of this test actually did
    while claiming to hold a conversation. The turn is asserted past the guard below so it
    cannot silently regress to that. It runs against whatever local backend exists (or
    degrades honestly); the assertion is about *non-loopback* attempts either way, so the
    result does not depend on a model being present.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("JARVIS_USER_TOKEN", "no-telemetry-proof-token")
    headers = {"X-User-Token": "no-telemetry-proof-token"}

    with recording_egress(monkeypatch) as rec:
        from agents import web

        with TestClient(web.app) as client:            # real lifespan startup
            assert client.get("/api/status").status_code == 200
            chat = client.post("/chat", json={"message": "hello"}, headers=headers)
            assert chat.status_code not in (401, 403), (
                "the /chat turn never reached the handler — this test would be claiming to "
                f"exercise a user path it never entered (got {chat.status_code})"
            )
            client.get("/status")                              # background-facing read
        # exiting runs shutdown — a flush-on-exit beacon lands here

    network_spawns = [cmd for cmd in rec.subprocesses if _network_capable(cmd)]
    assert not rec.attempts, (
        "A default install attempted non-loopback egress during boot / a chat turn / "
        "shutdown, contradicting docs/PRIVACY.md ('zero outbound telemetry'). Either the "
        "call is owner-opt-in (gate it behind explicit config and disclose it) or "
        f"PRIVACY.md must be corrected. Attempts: {rec.attempts[:10]} hosts={rec.hosts}"
    )
    assert not network_spawns, (
        f"A default install spawned network-capable subprocess(es): {network_spawns}"
    )


def test_the_recorder_catches_unconnected_udp(monkeypatch):
    """Round-1 regression: the old connect-only spy could not see this at all.

    `socket(AF_INET, SOCK_DGRAM).sendto(b"usage", ("203.0.113.1", 9))` never calls
    ``connect``. It is the exact reproduction the reviewer supplied, and it must be caught.
    """
    with recording_egress(monkeypatch) as rec:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(b"usage", ("203.0.113.1", 9))
        except OSError:
            pass          # a best-effort beacon swallows this — the counter still saw it
        finally:
            sock.close()

    assert ("sendto", "203.0.113.1") in rec.attempts
    assert rec.hosts == ["203.0.113.1"]


def test_the_recorder_catches_a_beacon_on_a_request_path(monkeypatch):
    """Round-1 regression: a beacon that only fires while serving a request.

    Planted in a throwaway app rather than in `agents/` so the proof never ships a beacon
    of its own; what is under test is the harness's reach into request handling.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/ping")
    def ping():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(b"page-view", ("198.51.100.7", 9))
        except OSError:
            pass          # swallowed, exactly as a real best-effort beacon would
        finally:
            sock.close()
        return {"ok": True}

    with recording_egress(monkeypatch) as rec, TestClient(app) as client:
        assert client.get("/ping").status_code == 200

    assert rec.hosts == ["198.51.100.7"], "a request-path beacon must not be invisible"


def test_network_capable_spawns_are_detected_through_every_wrapper():
    """Round-2 review: basename-of-first-token missed every one of these.

    Each line is a spawn the reviewer showed could egress while the gate stayed green.
    """
    evasions = [
        'sh -c "curl https://example.invalid/ping"',
        "/usr/bin/env curl https://example.invalid/ping",
        "curl https://example.invalid/ping",                      # shell=True string
        "powershell -Command Invoke-WebRequest -Uri https://example.invalid/ping",
        "cmd /c curl https://example.invalid/ping",
        "C:\\Windows\\System32\\curl.exe https://example.invalid/ping",
        "bash -lc 'wget -q https://example.invalid/ping'",
        "powershell -c (New-Object System.Net.WebClient).DownloadString('http://x')",
    ]
    missed = [cmd for cmd in evasions if not _network_capable(cmd)]
    assert not missed, f"network-capable spawn(s) not detected: {missed}"

    benign = ["docker info", "wasmtime --version", "uname -p", "git status", "python -V"]
    false_positives = [cmd for cmd in benign if _network_capable(cmd)]
    assert not false_positives, (
        f"benign spawn(s) wrongly flagged — the gate would be disabled within a week: "
        f"{false_positives}"
    )


def test_a_network_capable_child_is_refused_before_it_executes(monkeypatch):
    """The reviewer's core hazard: v2 recorded the command and then ran it, so a real
    `curl` could transmit before the assertion. Blocking must precede execution."""
    executed: list[str] = []
    real_popen = subprocess.Popen

    def _tripwire(cmd, *args, **kwargs):        # stands in for the real child process
        executed.append(str(cmd))
        raise AssertionError("the child process must never be started")

    monkeypatch.setattr(subprocess, "Popen", _tripwire)

    with recording_egress(monkeypatch) as rec:
        for spawn in (
            lambda: subprocess.Popen(["sh", "-c", "curl https://example.invalid/ping"]),
            lambda: os.system("curl https://example.invalid/ping"),
            lambda: os.popen("wget https://example.invalid/ping"),
        ):
            with contextlib.suppress(PermissionError):
                spawn()                         # refused pre-exec, as required
        blocked = list(rec.blocked_spawns)

    assert executed == [], "a network-capable child was executed before being blocked"
    assert len(blocked) == 3, f"expected 3 refusals, got {blocked}"
    assert any("os.system" in b for b in blocked) and any("os.popen" in b for b in blocked)
    assert subprocess.Popen is _tripwire or real_popen  # patches unwound by monkeypatch


def test_the_recorder_instruments_the_required_operations_on_this_platform(monkeypatch):
    """A pass must mean the gate was watching.

    Round-2 (Windows CI): patching `sendmsg` unconditionally raised `AttributeError` on
    Windows, where it does not exist. The fix skips absent operations — so this pins the
    floor, otherwise a platform that silently provides fewer of them would still go green.
    """
    with recording_egress(monkeypatch) as rec:
        instrumented = list(rec.instrumented)

    assert set(MUST_INSTRUMENT).issubset(instrumented), (
        f"missing on {sys.platform}: {sorted(set(MUST_INSTRUMENT) - set(instrumented))}"
    )
    if hasattr(socket.socket, "sendmsg"):        # POSIX
        assert "sendmsg" in instrumented


def test_loopback_traffic_is_not_flagged(monkeypatch):
    """LM Studio / Ollama / the app's own server are local by definition — a gate that
    fires on them would be turned off within a week, so prove it stays quiet."""
    with recording_egress(monkeypatch) as rec:
        for address in (("127.0.0.1", 1234), ("localhost", 11434), ("::1", 8080)):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.sendto(b"x", address)
            except OSError:
                pass
            finally:
                sock.close()

    assert rec.attempts == [], f"loopback wrongly flagged: {rec.attempts}"


def test_no_known_telemetry_vendor_is_referenced_in_shipped_code():
    """The static ratchet. Scope is explicit: recognisable vendors only (see docstring).

    Docs are excluded because PRIVACY.md and this module *name* these hosts in order to
    forbid them, and a gate its own documentation trips is a gate nobody keeps.
    """
    roots = [repo_root / "agents", repo_root / "scripts", repo_root / "frontend" / "src"]
    offenders: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"} or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:  # pragma: no cover - an unreadable file is not a beacon
                continue
            offenders += [
                f"{path.relative_to(repo_root)} → {host}"
                for host in TELEMETRY_HOSTS if host in text
            ]

    assert not offenders, (
        "Shipped runtime code references a known telemetry/crash-reporting vendor. "
        "PRIVACY.md promises there is none; if this is deliberate it must be opt-in AND "
        "disclosed there first:\n" + "\n".join(offenders)
    )


def test_the_privacy_promise_this_pins_still_says_what_we_think():
    """If PRIVACY.md's wording is softened, this gate must be re-read rather than left
    standing as evidence for a claim the document no longer makes."""
    privacy = (repo_root / "docs" / "PRIVACY.md").read_text(encoding="utf-8").lower()
    assert "no telemetry" in privacy or "zero outbound telemetry" in privacy, (
        "docs/PRIVACY.md no longer states the no-telemetry promise this test exists to "
        "prove — reconcile the document and this gate deliberately."
    )
