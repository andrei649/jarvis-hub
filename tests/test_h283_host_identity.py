"""H283 — Nerva knows what kind of machine it runs on, and tells the model.

One detector (``agents.core.host_identity``) reads the container, WSL, Termux,
supervisor, terminal/multiplexer and machine-id signals Hermes reads, maps each onto a
closed vocabulary, and is the source the skill gates (``skills.visibility``), the
doctor's container check (``host_posture``), the prompt (``environment_hint``) and
``GET /api/host/probe`` all read, so none of them can describe a different machine.
Every OS fact is injected; nothing here depends on the box the suite runs on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents.core import environment_hint as hint_mod  # noqa: E402
from agents.core import host_identity as hi  # noqa: E402
from agents.core import host_posture as hp  # noqa: E402

MACHINE_ID = "0d0af1c2b3a4958677a8b9c0d1e2f3a4"


def _files(present=(), texts=None):
    """``exists``/``read_text`` seams over a fake file system."""
    texts = dict(texts or {})

    def exists(path):
        return path in present or path in texts

    def read_text(path):
        if path in texts:
            return texts[path]
        raise FileNotFoundError(path)

    return exists, read_text


def _detect(env=None, present=(), texts=None, platform="linux", tty=False, stderr=None, tmp=None, **kw):
    exists, read_text = _files(present, texts)
    cgroup = str(tmp / "cgroup") if tmp is not None else "/nonexistent/h283/cgroup"
    return hi.detect(dict(env or {}), exists=exists, read_text=read_text, platform=platform,
                     isatty=lambda: tty, stderr_id=lambda: stderr, windows_guid=lambda: "",
                     files=("/.dockerenv", "/run/.containerenv"), cgroup=cgroup, pid=4242, **kw)


# ── container ───────────────────────────────────────────────────────────────────

def test_a_marker_file_keeps_the_docker_tag_whatever_else_said_container():
    """The skill gate always read `/.dockerenv` as docker: a pod that also has one, or a
    containerd cgroup with one, must not lose the tag a user skill is gated on."""
    pod = _detect({"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, ("/.dockerenv",))
    assert pod.container == "kubernetes" and pod.environment_tags() == {"container", "kubernetes", "docker"}
    bare_pod = _detect({"KUBERNETES_SERVICE_HOST": "10.0.0.1"})
    assert bare_pod.environment_tags() == {"container", "kubernetes"}
    podman = _detect({"container": "lxc"}, ("/run/.containerenv",))
    assert "docker" in podman.environment_tags()
    # the operator's word wins over the marker, tags included
    assert _detect({"JARVIS_CONTAINER": "none"}, ("/.dockerenv",)).environment_tags() == frozenset()
    assert _detect({"JARVIS_CONTAINER": "lxc"}, ("/.dockerenv",)).environment_tags() == {"container", "lxc", "docker"}


def test_nothing_detected_is_a_quiet_identity():
    got = _detect()
    assert (got.container, got.wsl, got.termux, got.supervisor) == ("", "", False, "none")
    assert got.prompt_line() == "" and got.prompt_block() == ""
    assert got.terminal == "none" and got.multiplexer == "none" and got.machine_id == ""


@pytest.mark.parametrize("present,env,kind,evidence", [
    (("/.dockerenv",), {}, "docker", "/.dockerenv"),
    (("/run/.containerenv",), {}, "podman", "/run/.containerenv"),
    ((), {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "kubernetes", "KUBERNETES_SERVICE_HOST"),
    (("/.dockerenv",), {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}, "kubernetes", "KUBERNETES_SERVICE_HOST"),
    ((), {"container": "podman"}, "podman", "container"),
    ((), {"container": "something-new"}, "container", "container"),
    ((), {"JARVIS_CONTAINER": "Docker"}, "docker", "JARVIS_CONTAINER"),
    ((), {"JARVIS_CONTAINER": "yes"}, "container", "JARVIS_CONTAINER"),
    ((), {"JARVIS_CONTAINER": "true"}, "container", "JARVIS_CONTAINER"),
])
def test_container_kinds(present, env, kind, evidence):
    got = _detect(env, present)
    assert (got.container, got.container_evidence) == (kind, evidence)
    assert kind in hi.CONTAINER_KINDS


def test_the_operator_can_say_it_is_not_a_container():
    got = _detect({"JARVIS_CONTAINER": "none"}, ("/.dockerenv",))
    assert got.container == "" and got.prompt_line() == ""


def test_systemds_container_file_names_the_kind():
    got = _detect(texts={hi.SYSTEMD_CONTAINER: "systemd-nspawn\n"})
    assert (got.container, got.container_evidence) == ("nspawn", hi.SYSTEMD_CONTAINER)
    assert _detect(texts={hi.SYSTEMD_CONTAINER: "docker\n"}).container == "docker"


@pytest.mark.parametrize("text,kind", [
    ("12:pids:/docker/abc\n", "docker"),
    ("0::/kubepods/besteffort/pod1\n", "kubernetes"),
    ("1:name=systemd:/machine.slice/libpod-1\n", "podman"),
    ("0::/system.slice/containerd.service\n", "containerd"),
    ("0::/lxc/box\n", "lxc"),
])
def test_the_pid1_cgroup_is_host_postures_own_read(tmp_path, text, kind):
    (tmp_path / "cgroup").write_text(text, encoding="utf-8")
    got = _detect(tmp=tmp_path)
    assert got.container == kind and got.container_evidence.startswith(str(tmp_path / "cgroup"))


def test_a_cgroup_v2_root_with_no_marker_claims_nothing(tmp_path):
    """A private cgroup namespace reads ``0::/``: no evidence, so no claim either way."""
    (tmp_path / "cgroup").write_text("0::/\n", encoding="utf-8")
    got = _detect(tmp=tmp_path)
    assert got.container == "" and "bare" not in got.prompt_line()


# ── WSL and Termux ──────────────────────────────────────────────────────────────

def test_wsl_versions_and_the_distro_name():
    wsl2 = _detect({"WSL_DISTRO_NAME": "Ubuntu-22.04"}, texts={hi.OSRELEASE: "5.15.90.1-microsoft-standard-WSL2\n"})
    assert (wsl2.wsl, wsl2.wsl_distro) == ("wsl2", "Ubuntu-22.04")
    assert "under Windows (WSL 2)" in wsl2.prompt_line() and "Ubuntu" not in wsl2.prompt_line()
    assert _detect(texts={hi.OSRELEASE: "4.4.0-19041-Microsoft\n"}).wsl == "wsl1"
    assert _detect({"WSL_INTEROP": "/run/WSL/1_interop"}).wsl == "wsl"
    hostile = _detect({"WSL_DISTRO_NAME": "Ubu\nntu; rm -rf / " + "x" * 80})
    assert hostile.wsl_distro == "Ubunturm-rf" + "x" * 21 and len(hostile.wsl_distro) == 32
    assert _detect({"WSL_DISTRO_NAME": "Ubuntu"}, platform="darwin").wsl == ""


@pytest.mark.parametrize("env,present", [
    ({"TERMUX_VERSION": "0.118.0"}, ()),
    ({"PREFIX": "/data/data/com.termux/files/usr"}, ()),
    ({}, (hi.TERMUX_HOME,)),
])
def test_termux(env, present):
    got = _detect(env, present)
    assert got.termux and got.prompt_line() == "This hub runs in Termux on Android."


# ── supervisor ──────────────────────────────────────────────────────────────────

def test_systemd_with_the_journal_and_a_watchdog_for_this_pid():
    env = {"NOTIFY_SOCKET": "/run/systemd/notify", "JOURNAL_STREAM": "8:1234", "WATCHDOG_USEC": "60000000",
           "WATCHDOG_PID": "4242", "INVOCATION_ID": "deadbeef"}
    got = _detect(env, stderr=(8, 1234))
    assert (got.supervisor, got.notify_socket, got.journal, got.watchdog_s) == ("systemd", True, True, 60)
    assert got.prompt_line() == ("This hub runs supervised by systemd (logs go to the journal; "
                                 "the unit sets a systemd watchdog).")
    assert "deadbeef" not in json.dumps(got.to_dict())


def test_a_weak_supervisor_signal_is_not_told_to_the_model_as_fact():
    """INVOCATION_ID without a terminal also marks a transient scope (`nohup` from a desktop
    terminal); the s6 directories also exist after `docker exec` into an s6 image. The probe
    keeps both, the prompt claims neither as 'supervised by'."""
    weak = _detect({"INVOCATION_ID": "abc", "TERM": "xterm-256color"}, stderr=(8, 1))
    assert weak.supervisor == "systemd" and not weak.supervisor_confirmed
    assert weak.prompt_line() == "" and "supervised" not in weak.prompt_block()
    s6_dirs = _detect({}, ("/run/s6",))
    assert s6_dirs.supervisor == "s6" and not s6_dirs.supervisor_confirmed
    assert s6_dirs.prompt_line() == "This hub runs alongside an s6 supervision tree."
    assert "supervised by" not in s6_dirs.prompt_line()
    # a strong signal still says it
    assert _detect({"NOTIFY_SOCKET": "/run/x"}).prompt_line() == "This hub runs supervised by systemd."
    mine = _detect({"INVOCATION_ID": "abc", "JOURNAL_STREAM": "8:1"}, stderr=(8, 1))
    assert mine.supervisor_confirmed and "supervised by systemd" in mine.prompt_line()
    assert _detect({"S6_VERSION": "3"}).prompt_line() == "This hub runs supervised by s6."


@pytest.mark.parametrize("usec", ["٦٠٠٠٠٠٠٠", "60_000_000", "+60000000", " -1", "6e7", "", "0"])
def test_the_watchdog_is_read_the_way_sd_notify_reads_it(usec, monkeypatch):
    """One parser: when the heartbeat would never ping, the prompt must not promise a watchdog."""
    from agents.core import sd_notify

    env = {"NOTIFY_SOCKET": "/run/x", "WATCHDOG_USEC": usec}
    assert _detect(env).watchdog_s == 0 and "watchdog" not in _detect(env).prompt_line()
    monkeypatch.setenv("WATCHDOG_USEC", usec)
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert sd_notify.watchdog_seconds() is None


@pytest.mark.parametrize("usec,want", [("60000000", 60), ("500000", 1), ("1500000", 2)])
def test_the_watchdog_agrees_with_the_heartbeat_and_never_rounds_down_to_nothing(usec, want, monkeypatch):
    from agents.core import sd_notify

    got = _detect({"NOTIFY_SOCKET": "/run/x", "WATCHDOG_USEC": usec})
    assert got.watchdog_s == want
    monkeypatch.setenv("WATCHDOG_USEC", usec)
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert sd_notify.watchdog_seconds() is not None


def test_the_journal_is_only_this_stderr_and_the_watchdog_only_this_pid():
    env = {"INVOCATION_ID": "x", "JOURNAL_STREAM": "8:1234", "WATCHDOG_USEC": "60000000", "WATCHDOG_PID": "1"}
    got = _detect(env, stderr=(8, 9999))
    assert got.supervisor == "systemd" and not got.journal and got.watchdog_s == 0
    assert _detect({"INVOCATION_ID": "x", "JOURNAL_STREAM": "garbage"}, stderr=(8, 1)).journal is False


def test_invocation_id_in_an_interactive_shell_is_not_supervision():
    """A terminal emulator that runs as a user service hands its shells INVOCATION_ID."""
    assert _detect({"INVOCATION_ID": "x"}, tty=True).supervisor == "none"
    assert _detect({"NOTIFY_SOCKET": "/run/x"}, tty=True).supervisor == "systemd"


@pytest.mark.parametrize("env,present,want", [
    ({"S6_VERSION": "3.1"}, (), "s6"),
    ({"S6_CMD_ARG0": "/init"}, (), "s6"),
    ({}, ("/run/s6",), "s6"),
    ({}, ("/command/s6-svscan",), "s6"),
    ({"NOTIFY_SOCKET": "/run/x"}, ("/run/s6",), "systemd"),
])
def test_s6(env, present, want):
    got = _detect(env, present)
    assert got.supervisor == want and got.s6


@pytest.mark.parametrize("env,want", [
    ({"LAUNCHD_SOCKET": "/private/tmp/x"}, "launchd"),
    ({"XPC_SERVICE_NAME": "com.nerva.hub"}, "launchd"),
    ({"XPC_SERVICE_NAME": "0"}, "none"),
    ({"XPC_SERVICE_NAME": "application.com.googlecode.iterm2.1234"}, "none"),
])
def test_launchd_on_macos(env, want):
    assert _detect(env, platform="darwin").supervisor == want
    assert _detect(env, platform="linux").supervisor == "none"


# ── terminal and multiplexer ────────────────────────────────────────────────────

@pytest.mark.parametrize("env,terminal", [
    ({"WT_SESSION": "a-guid"}, "windows-terminal"),
    ({"ITERM_SESSION_ID": "w0t0p0:x"}, "iterm2"),
    ({"KITTY_WINDOW_ID": "1"}, "kitty"),
    ({"WEZTERM_PANE": "3"}, "wezterm"),
    ({"GHOSTTY_RESOURCES_DIR": "/usr/share/ghostty"}, "ghostty"),
    ({"TERM_PROGRAM": "Apple_Terminal"}, "apple-terminal"),
    ({"TERM_PROGRAM": "vscode"}, "vscode"),
    ({"TERM_PROGRAM": "SomeNewTerm\x1b]0;pwned\x07"}, "other"),
    ({"TERM": "xterm-256color"}, "other"),
    ({"TERM": "dumb"}, "none"),
    ({}, "none"),
])
def test_terminal_names_are_a_closed_vocabulary(env, terminal):
    got = _detect(env)
    assert got.terminal == terminal and got.terminal in hi.TERMINALS
    dumped = json.dumps(got.to_dict())
    for value in env.values():
        if value not in hi.TERMINALS + hi.TERM_FAMILIES:
            assert value not in dumped


def test_multiplexer_colour_and_background():
    tmux = _detect({"TMUX": "/tmp/tmux-1000/default,1,0", "TERM": "tmux-256color", "TERM_PROGRAM": "tmux",
                    "COLORTERM": "truecolor", "COLORFGBG": "15;0"}, tty=True)
    assert (tmux.multiplexer, tmux.term, tmux.color, tmux.background, tmux.interactive) == \
        ("tmux", "tmux", "truecolor", "dark", True)
    assert tmux.terminal == "other"          # tmux is the multiplexer, not the terminal
    screen = _detect({"STY": "123.pts-0.box", "TERM": "screen", "COLORFGBG": "0;default;15"})
    assert (screen.multiplexer, screen.term, screen.color, screen.background) == ("screen", "screen", "basic", "light")
    assert _detect({"COLORFGBG": "nonsense"}).background == "unknown"
    for got in (tmux, screen):
        row = got.to_dict()
        assert row["multiplexer"] in hi.MULTIPLEXERS and row["term"] in hi.TERM_FAMILIES
        assert row["color"] in hi.COLORS and row["background"] in hi.BACKGROUNDS
        assert "/tmp/tmux" not in json.dumps(row) and "pts-0" not in json.dumps(row)


def test_terminal_facts_never_reach_the_model():
    got = _detect({"TMUX": "x", "WT_SESSION": "y", "NOTIFY_SOCKET": "/run/x"})
    assert got.terminal == "windows-terminal"
    for word in ("tmux", "Windows Terminal", "windows-terminal", "terminal"):
        assert word not in got.prompt_line()


# ── machine id ──────────────────────────────────────────────────────────────────

def test_the_machine_id_is_a_keyed_hash_prefix_never_the_raw_value():
    got = _detect(texts={"/etc/machine-id": MACHINE_ID + "\n"})
    assert got.machine_id_source == "etc" and len(got.machine_id) == 16
    assert got.machine_id == hi.hash_machine_id(MACHINE_ID)
    assert got.machine_id not in MACHINE_ID and MACHINE_ID[:8] not in json.dumps(got.to_dict())
    assert got.machine_id not in got.prompt_line()
    dbus = _detect(texts={"/var/lib/dbus/machine-id": MACHINE_ID})
    assert dbus.machine_id_source == "dbus" and dbus.machine_id == got.machine_id


def test_the_override_wins_and_is_hashed_too():
    got = _detect({"JARVIS_MACHINE_ID": "living-room-nuc"}, texts={"/etc/machine-id": MACHINE_ID})
    assert got.machine_id_source == "override" and "living-room" not in json.dumps(got.to_dict())
    assert got.machine_id == hi.hash_machine_id("living-room-nuc")


def test_a_missing_or_malformed_machine_id_is_none():
    assert _detect().machine_id_source == "none"
    assert _detect(texts={"/etc/machine-id": "not-an-id"}).machine_id == ""
    win = hi.detect({}, exists=lambda p: False, read_text=_files()[1], platform="win32", isatty=lambda: False,
                    stderr_id=lambda: None, windows_guid=lambda: "9F1E2D3C-AAAA-BBBB-CCCC-112233445566",
                    files=(), cgroup="/nonexistent/h283")
    assert win.machine_id_source == "windows" and "9F1E" not in json.dumps(win.to_dict())


# ── the prompt line ─────────────────────────────────────────────────────────────

def test_the_prompt_line_is_bounded_closed_and_never_a_heading():
    got = _detect({"WSL_INTEROP": "x", "TERMUX_VERSION": "1", "NOTIFY_SOCKET": "/run/x", "JOURNAL_STREAM": "1:2",
                   "WATCHDOG_USEC": "1000000"}, ("/.dockerenv",), stderr=(1, 2))
    line = got.prompt_line()
    assert line == ("This hub runs in a Docker container, under Windows (WSL), in Termux on Android, supervised "
                    "by systemd (logs go to the journal; the unit sets a systemd watchdog).")
    assert len(line) <= hi.MAX_PROMPT_LINE and "\n" not in line and not line.startswith("#")
    block = got.prompt_block()
    assert block == f"{hi.PROMPT_HEADER}\n{line}"
    assert "detected by Nerva" in hi.PROMPT_HEADER and hint_mod.HEADER != hi.PROMPT_HEADER


def test_identity_is_computed_once_per_process(monkeypatch):
    calls = []
    monkeypatch.setattr(hi, "detect", lambda: calls.append(1) or hi.HostIdentity(container="docker"))
    hi.identity.cache_clear()
    try:
        assert hi.identity() is hi.identity() and len(calls) == 1
        assert hi.prompt_block() == hi.prompt_block()
    finally:
        hi.identity.cache_clear()


def test_a_detector_bug_never_breaks_the_prompt(monkeypatch):
    def boom():
        raise RuntimeError("bad /proc")
    monkeypatch.setattr(hi, "detect", boom)
    hi.identity.cache_clear()
    try:
        assert hi.identity() == hi.HostIdentity(detected=False) and hi.prompt_block() == ""
    finally:
        hi.identity.cache_clear()


# ── the model is told, apart from the operator's words ──────────────────────────

DOCKER = hi.HostIdentity(container="docker", container_evidence="/.dockerenv", supervisor="systemd")


def test_the_detected_block_reaches_every_agent_apart_from_the_operator_hint(monkeypatch):
    from agents.core.agent import Agent

    monkeypatch.setattr(hi, "identity", lambda: DOCKER)
    monkeypatch.setenv(hint_mod.ENV_NAME, "Headless NUC.")
    agent = Agent("jarvis", {"name": "Jarvis"})
    prompt = agent.system_prompt()
    assert prompt == agent.system_prompt()
    detected = DOCKER.prompt_block()
    operator = f"{hint_mod.HEADER}\nHeadless NUC."
    assert hint_mod.hint_block() == f"{detected}\n\n{operator}"
    contract = (agent.identity or {}).get("content", "")
    persona = (agent.soul or {}).get("content", "")
    assert prompt == "\n\n".join(p for p in (contract, detected, operator, persona) if p)
    # The detected facts are never under the operator's header, nor the hint under Nerva's.
    assert prompt.index(hi.PROMPT_HEADER) < prompt.index(hint_mod.HEADER)
    assert "Headless" not in prompt[: prompt.index(hint_mod.HEADER)]


def test_with_nothing_detected_and_no_hint_the_prompt_is_unchanged(monkeypatch):
    from agents.core.agent import Agent

    monkeypatch.setattr(hi, "identity", lambda: hi.HostIdentity())
    monkeypatch.delenv(hint_mod.ENV_NAME, raising=False)
    agent = Agent("jarvis", {"name": "Jarvis"})
    contract = (agent.identity or {}).get("content", "")
    persona = (agent.soul or {}).get("content", "")
    assert hint_mod.hint_block() == ""
    assert agent.system_prompt() == "\n\n".join(p for p in (contract, persona) if p)


def test_prompt_size_counts_the_detected_block(monkeypatch):
    from agents.core.prompt_size import breakdown

    monkeypatch.setattr(hi, "identity", lambda: DOCKER)
    monkeypatch.delenv(hint_mod.ENV_NAME, raising=False)
    shared = {c.name: c for c in breakdown(agents_root=repo_root / "agents").shared_components()}
    assert shared["host-detected"].chars == len(DOCKER.prompt_block())
    assert "environment-hint" not in shared
    monkeypatch.setattr(hi, "identity", lambda: hi.HostIdentity())
    assert "host-detected" not in {c.name for c in breakdown(agents_root=repo_root / "agents").components}


# ── one detector: the skill gates and the doctor read the same facts ────────────

def test_skill_gates_read_the_same_identity(monkeypatch):
    from agents.core.skills import visibility

    monkeypatch.delenv(visibility.ENV_OVERRIDE, raising=False)
    for host, tags in [
        (hi.HostIdentity(), set()),
        (hi.HostIdentity(container="docker"), {"docker", "container"}),
        (hi.HostIdentity(container="podman"), {"docker", "container"}),
        (hi.HostIdentity(container="kubernetes"), {"kubernetes", "container"}),
        (hi.HostIdentity(s6=True), {"s6"}),
    ]:
        monkeypatch.setattr(hi, "identity", lambda host=host: host)
        assert visibility.host_environments() == frozenset(tags)
    monkeypatch.setattr(visibility.sys, "platform", "linux")
    monkeypatch.setattr(hi, "identity", lambda: hi.HostIdentity(termux=True))
    assert visibility.host_platforms() == frozenset({"linux", "android"})


def test_the_doctors_container_check_reads_the_same_detector(monkeypatch, tmp_path):
    info = tmp_path / "mountinfo"
    info.write_text("1 0 0:1 / / rw - overlay overlay rw\n", encoding="utf-8")
    monkeypatch.setattr(hp, "in_container", lambda **kw: None)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.delenv("JARVIS_CONTAINER", raising=False)
    got = hp.check_container_storage("/app/data", mountinfo=str(info))
    assert got["status"] == "warn" and "KUBERNETES_SERVICE_HOST" in got["detail"]
    monkeypatch.setenv("JARVIS_CONTAINER", "none")
    assert hp.check_container_storage("/app/data", mountinfo=str(info))["reason"] == "not_in_container"


# ── the operator's entry points ─────────────────────────────────────────────────

def _app(guard=None):
    from agents.core.routers import host_probe as routes
    from agents.core.routers._deps import user_guard

    app = FastAPI()
    app.include_router(routes.router)
    if guard is not None:
        app.dependency_overrides[user_guard] = guard
    else:
        app.dependency_overrides[user_guard] = lambda: None
    return app


def test_the_probe_reports_the_identity(monkeypatch):
    from agents.core import host_probe as probe_mod
    from agents.core.routers import host_probe as routes

    host = hi.HostIdentity(container="docker", container_evidence="/.dockerenv", supervisor="systemd",
                           journal=True, watchdog_s=30, terminal="none", machine_id="0123456789abcdef",
                           machine_id_source="etc")
    monkeypatch.setattr(hi, "identity", lambda: host)
    monkeypatch.setattr(routes, "_probe", lambda: probe_mod.probe_host({}, lambda name: False, {},
                                                                        sys_platform="linux"))
    body = TestClient(_app()).get("/api/host/probe").json()
    assert body["probed"] is True
    ident = body["identity"]
    assert ident["container"] == "docker" and ident["supervisor"] == "systemd" and ident["journal"] is True
    assert ident["watchdog_s"] == 30 and ident["machine_id"] == "0123456789abcdef" and ident["wsl"] is None
    assert ident["prompt_line"] == host.prompt_line()


def test_an_identity_failure_never_fails_the_probe(monkeypatch):
    from agents.core import host_probe as probe_mod
    from agents.core.routers import host_probe as routes

    def boom():
        raise RuntimeError("secret /proc path")
    monkeypatch.setattr(hi, "identity", boom)
    monkeypatch.setattr(routes, "_probe", lambda: probe_mod.probe_host({}, lambda name: False, {},
                                                                        sys_platform="linux"))
    r = TestClient(_app()).get("/api/host/probe")
    body = r.json()
    assert body["probed"] is True and body["identity"] == {"detected": False, "reason": "identity_failed"}
    assert "secret" not in r.text


def test_the_probe_with_its_identity_stays_user_guarded():
    def deny():
        raise HTTPException(status_code=401)
    assert TestClient(_app(deny)).get("/api/host/probe").status_code == 401


def test_the_shell_side_reader_prints_this_shells_host(monkeypatch, capsys):
    monkeypatch.setattr(hi, "detect", lambda: hi.HostIdentity(terminal="kitty", multiplexer="tmux"))
    assert hi.main([]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["terminal"] == "kitty" and row["multiplexer"] == "tmux" and row["prompt_line"] == ""


def test_the_module_is_runnable_and_stdlib_only():
    import ast

    tree = ast.parse((repo_root / "agents/core/host_identity.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert imported <= {"__future__", "functools", "hashlib", "hmac", "json", "math", "os", "re", "sys",
                        "collections", "dataclasses", "logging", "socket", "winreg"}


# ── fix round 3: the operator's spellings, a hostile watchdog, one socket parser ────────────

@pytest.mark.parametrize("word", ["none", "0", "false", "no", "off", "disable", "disabled", "False", " OFF "])
def test_every_way_of_saying_off_says_it_is_not_a_container(word):
    """env_config's falsy spellings mean off here too: `JARVIS_CONTAINER=0` on a bare host must not
    tell the model it runs in a container."""
    got = _detect({"JARVIS_CONTAINER": word}, ("/.dockerenv",))
    assert got.container == "" and got.prompt_line() == "" and got.environment_tags() == frozenset()
    assert hi.container_marker.__module__  # the doctor reads the same detector


@pytest.mark.parametrize("word", ["yes please", "banana", "1x"])
def test_an_unknown_word_is_not_a_silent_container(word):
    """Not a recognised kind or a yes: ignored, so the markers decide (here: none, so a bare host)."""
    assert _detect({"JARVIS_CONTAINER": word}).container == ""
    assert _detect({"JARVIS_CONTAINER": word}, ("/.dockerenv",)).container == "docker"


def test_the_doctor_agrees_when_the_operator_says_off(monkeypatch):
    monkeypatch.setenv("JARVIS_CONTAINER", "0")
    assert hi.container_marker() is None


@pytest.mark.parametrize("digits", [400, 5000])
def test_an_oversized_watchdog_is_no_watchdog_and_costs_nothing_else(digits, monkeypatch):
    """int() on 5000 digits is a ValueError and usec / 1e6 on 400 is an OverflowError: either used to
    blank the whole identity (container, WSL, machine id) and, in sd_notify, escape after READY."""
    from agents.core import sd_notify

    big = "9" * digits
    env = {"JARVIS_CONTAINER": "docker", "NOTIFY_SOCKET": "/run/x", "WATCHDOG_USEC": big,
           "WATCHDOG_PID": big, "WSL_DISTRO_NAME": "Ubuntu"}
    got = _detect(env, texts={"/etc/machine-id": MACHINE_ID})
    assert got.container == "docker" and got.wsl == "wsl" and got.machine_id and got.watchdog_s == 0
    assert got.supervisor_confirmed and "watchdog" not in got.prompt_line()
    assert hi.watchdog_deadline({"WATCHDOG_USEC": big}, 1) is None
    assert hi.watchdog_deadline({"WATCHDOG_USEC": "60000000", "WATCHDOG_PID": big}, 1) is None
    monkeypatch.setenv("WATCHDOG_USEC", big)
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert sd_notify.watchdog_seconds() is None


def test_a_sane_watchdog_still_parses():
    assert hi.watchdog_deadline({"WATCHDOG_USEC": "60000000"}, 1) == 60.0
    assert hi.watchdog_deadline({"WATCHDOG_USEC": "60000000", "WATCHDOG_PID": "7"}, 7) == 60.0


def test_a_detector_bug_is_logged_and_reported_as_not_detected(monkeypatch, caplog):
    """No silent bare host: the identity says it could not be detected, the probe and HUD show it."""
    hi.identity.cache_clear()
    try:
        def boom(*a, **k):
            raise RuntimeError("secret /proc path")
        monkeypatch.setattr(hi, "detect", boom)
        with caplog.at_level("WARNING"):
            got = hi.identity()
        assert got.detected is False and got.prompt_line() == "" and got.prompt_block() == ""
        assert got.to_dict() == {"detected": False, "reason": "identity_failed"}
        assert any("host identity" in r.getMessage() for r in caplog.records)
        assert "secret" not in caplog.text
    finally:
        hi.identity.cache_clear()


def test_a_detected_identity_says_so():
    assert _detect().detected is True and _detect().to_dict()["detected"] is True


@pytest.mark.parametrize("value", ["relative/path", "  ", "garbage", "vsock:2:1234", "unix:/run/x"])
def test_a_socket_sd_notify_cannot_use_is_not_supervision(value, monkeypatch):
    """One NOTIFY_SOCKET parser: when sd_notify would be inert the prompt must not say 'supervised'."""
    from agents.core import sd_notify

    got = _detect({"NOTIFY_SOCKET": value})
    assert got.supervisor == "none" and not got.supervisor_confirmed and got.notify_socket is False
    assert "supervised" not in got.prompt_line()
    monkeypatch.setenv("NOTIFY_SOCKET", value)
    assert sd_notify.enabled() is False


@pytest.mark.parametrize("value", ["/run/systemd/notify", " /run/x ", "@abstract"])
def test_a_socket_sd_notify_can_use_is_supervision(value, monkeypatch):
    from agents.core import sd_notify

    got = _detect({"NOTIFY_SOCKET": value})
    assert got.supervisor == "systemd" and got.supervisor_confirmed and got.notify_socket is True
    monkeypatch.setenv("NOTIFY_SOCKET", value)
    assert sd_notify.enabled() is True
    assert hi.notify_address(value) == sd_notify._address()
