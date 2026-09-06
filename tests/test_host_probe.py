"""op-host-probe — the host capability probe and its honest-refusal vocabulary.

Hermetic: every OS call, importer and environment is injected; no OS
permission is touched and no subprocess is spawned (the D-Bus portal query is
exercised through a fake runner that pins the argv and the absence of a shell).

Claims pinned:
  * the platform classifier (windows / macos / linux-x11 / linux-wayland /
    headless) with Wayland winning over Xwayland's DISPLAY;
  * macOS: ``AXIsProcessTrustedWithOptions`` is asked with the prompt option
    OFF and the requesting APIs are never called (spy); an untrusted process
    → ``accessibility_permission_missing``; no capture → ``screen_recording_permission_missing``;
  * Wayland: portal version < 2 or no python-libei → ``wayland_input_unavailable``;
    unknown portal and no grim → ``wayland_capture_unavailable``;
  * headless → ``desktop_platform_unsupported``; Windows without either UIA
    backend → ``desktop_dependency_unavailable``;
  * refusals are a closed vocabulary (constructor refuses anything else);
  * the fingerprint is canonical and moves only when a fact moves;
  * ``calls={}`` makes no OS call at all and reports every permission unknown;
  * flags are reported, never enforced (JARVIS_DESKTOP_HOST=1 changes no refusal);
  * the route is user-guarded, runs the probe, and reports ``probe_failed``
    without exception text when the probe itself blows up.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import host_probe as hp
from agents.core.routers import host_probe as routes
from agents.core.routers._deps import user_guard

SPEC_VOCABULARY = {
    "desktop_platform_unsupported",
    "accessibility_permission_missing",
    "screen_recording_permission_missing",
    "wayland_input_unavailable",
    "wayland_capture_unavailable",
    "atspi_unavailable",
    "target_elevated",
    "desktop_dependency_unavailable",
    "local_vlm_not_proven_local",
}


def _importer(*present: str):
    """A ``find_spec`` stand-in: returns a truthy spec for *present* module names."""
    def find(name):
        return object() if name in present else None
    return find


def _which(*present: str):
    return lambda tool: f"/usr/bin/{tool}" if tool in present else None


def _calls(**overrides):
    calls = {"which": _which()}
    calls.update(overrides)
    return calls


# ── vocabulary ───────────────────────────────────────────────────────────────

def test_refusal_vocabulary_is_exactly_the_spec_set():
    assert frozenset(SPEC_VOCABULARY) == hp.REFUSAL_REASONS
    assert set(hp.REFUSAL_HINTS) == SPEC_VOCABULARY
    assert all(hint and "\n" not in hint for hint in hp.REFUSAL_HINTS.values())


def test_dep_names_are_the_seven_optional_libraries_in_order():
    assert hp.DEP_NAMES == ("pywinauto", "uiautomation", "pyobjc", "gi_atspi", "libei", "playwright", "mss")
    assert set(hp.DEP_MODULES) == set(hp.DEP_NAMES)


# ── platform detection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("sys_platform,env,expected", [
    ("win32", {}, "windows"),
    ("cygwin", {}, "windows"),
    ("darwin", {}, "macos"),
    ("linux", {"XDG_SESSION_TYPE": "wayland"}, "linux-wayland"),
    ("linux", {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "linux-wayland"),   # Xwayland
    ("linux", {"XDG_SESSION_TYPE": "x11"}, "linux-x11"),
    ("linux", {"DISPLAY": ":1"}, "linux-x11"),
    ("linux", {}, "headless"),
    ("linux", {"XDG_SESSION_TYPE": "tty"}, "headless"),
    ("freebsd14", {"DISPLAY": ":0"}, "linux-x11"),
])
def test_detect_desktop_platform_matrix(sys_platform, env, expected):
    assert hp.detect_desktop_platform(env, sys_platform) == expected


def test_detect_reads_os_environ_and_sys_platform_by_default(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert hp.detect_desktop_platform() == "headless"
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert hp.detect_desktop_platform() == "linux-wayland"


# ── headless / windows ───────────────────────────────────────────────────────

def test_headless_refuses_platform_and_touches_no_permission_call():
    touched = []
    calls = _calls(
        ax_is_process_trusted=lambda: touched.append("ax"),
        portal_remote_desktop_version=lambda **_: touched.append("portal"),
        vlm_proven_local=lambda **_: touched.append("vlm"),
    )
    probe = hp.probe_host({}, _importer(), calls, sys_platform="linux")
    assert probe.platform == "headless"
    assert probe.refusals == ("desktop_platform_unsupported",)
    assert touched == []
    assert probe.ok is False
    assert hp.desktop_operator_available(probe) is False


def test_windows_without_either_uia_backend_is_a_dependency_refusal():
    probe = hp.probe_host({}, _importer("mss"), _calls(process_elevated=lambda: False), sys_platform="win32")
    assert probe.platform == "windows"
    assert probe.refusals == ("desktop_dependency_unavailable",)
    assert probe.deps["pywinauto"] is False and probe.deps["uiautomation"] is False


@pytest.mark.parametrize("backend", ["pywinauto", "uiautomation"])
def test_windows_with_one_uia_backend_is_available(backend):
    probe = hp.probe_host({}, _importer(backend, "mss"), _calls(process_elevated=lambda: False), sys_platform="win32")
    assert probe.refusals == ()
    assert probe.ok is True
    assert hp.desktop_operator_available(probe) is True
    assert probe.permissions["process_elevated"] is False


def test_windows_elevated_process_is_a_warning_not_a_refusal():
    probe = hp.probe_host({}, _importer("pywinauto"), _calls(process_elevated=lambda: True), sys_platform="win32")
    assert probe.refusals == ()
    assert "process_elevated:nerva_runs_elevated" in probe.warnings
    assert "capture_fallback:pil_imagegrab" in probe.warnings   # no mss → PIL fallback disclosed


# ── macOS ────────────────────────────────────────────────────────────────────

def test_macos_untrusted_process_refuses_accessibility_permission_missing():
    calls = _calls(ax_is_process_trusted=lambda: False, cg_preflight_screen_capture=lambda: True)
    probe = hp.probe_host({}, _importer("ApplicationServices"), calls, sys_platform="darwin")
    assert probe.platform == "macos"
    assert probe.deps["pyobjc"] is True
    assert probe.refusals == ("accessibility_permission_missing",)
    assert probe.permissions["accessibility_trusted"] is False
    assert probe.permissions["screen_capture"] is True


def test_macos_no_screen_capture_refuses_screen_recording_permission_missing():
    calls = _calls(ax_is_process_trusted=lambda: True, cg_preflight_screen_capture=lambda: False)
    probe = hp.probe_host({}, _importer("ApplicationServices"), calls, sys_platform="darwin")
    assert probe.refusals == ("screen_recording_permission_missing",)


def test_macos_without_pyobjc_reports_permissions_unknown_not_missing():
    probe = hp.probe_host({}, _importer(), _calls(), sys_platform="darwin")
    assert probe.refusals == ("desktop_dependency_unavailable",)
    assert probe.permissions["accessibility_trusted"] is None
    assert probe.permissions["screen_capture"] is None
    assert "accessibility_trusted:unknown" in probe.warnings


def test_macos_default_calls_never_prompt(monkeypatch):
    """The default seams ask the silent preflight APIs with prompt=False and
    never touch the requesting variants (spy modules in sys.modules)."""
    seen = {}

    def ax_with_options(options):
        seen["options"] = dict(options)
        return False

    def never(*_a, **_k):
        raise AssertionError("a permission-requesting API was called by the probe")

    fake_as = types.ModuleType("ApplicationServices")
    fake_as.AXIsProcessTrustedWithOptions = ax_with_options
    fake_as.kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
    fake_as.AXIsProcessTrusted = never
    fake_quartz = types.ModuleType("Quartz")
    fake_quartz.CGPreflightScreenCaptureAccess = lambda: False
    fake_quartz.CGRequestScreenCaptureAccess = never
    monkeypatch.setitem(sys.modules, "ApplicationServices", fake_as)
    monkeypatch.setitem(sys.modules, "Quartz", fake_quartz)

    probe = hp.probe_host({}, _importer("ApplicationServices"), sys_platform="darwin")

    assert seen["options"] == {"AXTrustedCheckOptionPrompt": False}
    assert probe.refusals == ("accessibility_permission_missing", "screen_recording_permission_missing")
    src = Path(hp.__file__).read_text(encoding="utf-8")
    assert "CGRequestScreenCaptureAccess" not in src.split('"""', 2)[2]   # only named in the docstring
    assert "kAXTrustedCheckOptionPrompt: True" not in src


def test_default_ax_call_returns_unknown_when_pyobjc_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "ApplicationServices", None)   # import → ImportError
    monkeypatch.setitem(sys.modules, "Quartz", None)
    assert hp._ax_is_process_trusted() is None
    assert hp._cg_preflight_screen_capture() is None


# ── Linux ────────────────────────────────────────────────────────────────────

def _wayland(env=None):
    return {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", **(env or {})}


def test_wayland_portal_below_v2_refuses_input():
    calls = _calls(which=_which("grim"), portal_remote_desktop_version=lambda **_: 1)
    probe = hp.probe_host(_wayland(), _importer("gi", "libei"), calls, sys_platform="linux")
    assert probe.platform == "linux-wayland"
    assert probe.permissions["portal_remote_desktop_version"] == 1
    assert probe.refusals == ("wayland_input_unavailable",)


def test_wayland_without_libei_refuses_input_even_with_portal_v2():
    calls = _calls(which=_which("grim"), portal_remote_desktop_version=lambda **_: 2)
    probe = hp.probe_host(_wayland(), _importer("gi"), calls, sys_platform="linux")
    assert probe.refusals == ("wayland_input_unavailable",)


def test_wayland_unknown_portal_and_no_grim_refuses_capture_too():
    calls = _calls(portal_remote_desktop_version=lambda **_: None)
    probe = hp.probe_host(_wayland(), _importer("gi", "libei", "mss"), calls, sys_platform="linux")
    assert probe.refusals == ("wayland_input_unavailable", "wayland_capture_unavailable")
    assert "mss_present:x11_only_grabber" in probe.warnings


def test_wayland_with_libei_portal_v2_and_atspi_is_available():
    calls = _calls(which=_which("grim", "gdbus"), portal_remote_desktop_version=lambda **_: 2,
                   uinput_writable=lambda: False)
    probe = hp.probe_host(_wayland(), _importer("gi", "libei"), calls, sys_platform="linux")
    assert probe.refusals == ()
    assert probe.binaries == {"xdotool": False, "grim": True, "gdbus": True, "busctl": False}


def test_wayland_portal_call_receives_the_probe_env():
    seen = {}

    def portal(**kwargs):
        seen.update(kwargs)
        return 2

    env = _wayland({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/x"})
    hp.probe_host(env, _importer("gi", "libei"), _calls(portal_remote_desktop_version=portal), sys_platform="linux")
    assert seen["env"] is env


def test_linux_x11_without_gi_refuses_atspi_and_discloses_missing_xdotool():
    probe = hp.probe_host({"DISPLAY": ":0"}, _importer("mss"), _calls(), sys_platform="linux")
    assert probe.platform == "linux-x11"
    assert probe.refusals == ("atspi_unavailable",)
    assert "x11_input_tool_missing:xdotool" in probe.warnings
    assert probe.permissions["portal_remote_desktop_version"] is None


def test_uinput_writable_is_reported_and_flagged_refused_by_policy():
    calls = _calls(which=_which("xdotool"), uinput_writable=lambda: True)
    probe = hp.probe_host({"DISPLAY": ":0"}, _importer("gi", "mss"), calls, sys_platform="linux")
    assert probe.refusals == ()
    assert probe.permissions["uinput_writable"] is True
    assert "uinput_writable:refused_by_policy" in probe.warnings


# ── the D-Bus portal query: argv only, no shell, timeout ─────────────────────

@pytest.mark.parametrize("text,expected", [
    ("(<uint32 2>,)\n", 2),
    ("u 1\n", 1),
    ("(<uint32 12>,)", 12),
    ("Error: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown", None),
    ("", None),
    (None, None),
])
def test_parse_portal_version(text, expected):
    assert hp.parse_portal_version(text) == expected


def test_portal_query_without_a_session_bus_never_spawns():
    def runner(*_a, **_k):
        raise AssertionError("spawned without a session bus")
    assert hp.portal_remote_desktop_version(env={}, which=_which("gdbus"), runner=runner) is None


def test_portal_query_pins_argv_no_shell_and_a_timeout():
    seen = []

    def runner(argv, **kwargs):
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="(<uint32 2>,)\n", stderr="")

    env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
    assert hp.portal_remote_desktop_version(env=env, which=_which("gdbus", "busctl"), runner=runner) == 2
    assert len(seen) == 1
    argv, kwargs = seen[0]
    assert isinstance(argv, list) and argv[0] == "gdbus"
    assert "org.freedesktop.portal.RemoteDesktop" in argv and argv[-1] == "version"
    assert "shell" not in kwargs
    assert kwargs["timeout"] == pytest.approx(3.0)
    assert kwargs["check"] is False


def test_portal_query_falls_back_to_busctl_and_swallows_runner_errors():
    seen = []

    def runner(argv, **kwargs):
        seen.append(argv[0])
        if argv[0] == "gdbus":
            raise subprocess.TimeoutExpired(argv, 3.0)
        return subprocess.CompletedProcess(argv, 0, stdout="u 2\n", stderr="")

    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert hp.portal_remote_desktop_version(env=env, which=_which("gdbus", "busctl"), runner=runner) == 2
    assert seen == ["gdbus", "busctl"]


def test_portal_query_with_no_client_tool_is_unknown():
    def runner(*_a, **_k):
        raise AssertionError("no tool, nothing to spawn")
    env = {"DBUS_SESSION_BUS_ADDRESS": "unix:abstract=x"}
    assert hp.portal_remote_desktop_version(env=env, which=_which(), runner=runner) is None


# ── VLM locality is reported per host, vetoes only the visual route ──────────

def test_remote_vlm_refuses_local_vlm_not_proven_local_but_not_the_desktop():
    calls = _calls(process_elevated=lambda: False, vlm_proven_local=lambda **_: False)
    probe = hp.probe_host({}, _importer("pywinauto"), calls, sys_platform="win32")
    assert probe.refusals == ("local_vlm_not_proven_local",)
    assert probe.ok is False
    assert hp.desktop_operator_available(probe) is True


def test_unconfigured_vlm_is_unknown_not_a_refusal():
    calls = _calls(process_elevated=lambda: False, vlm_proven_local=lambda **_: None)
    probe = hp.probe_host({}, _importer("pywinauto"), calls, sys_platform="win32")
    assert probe.refusals == ()
    assert probe.permissions["vlm_proven_local"] is None


def test_default_vlm_call_uses_the_real_resolver(monkeypatch):
    monkeypatch.delenv("JARVIS_VLM_BACKEND", raising=False)
    monkeypatch.delenv("JARVIS_VLM_URL", raising=False)
    assert hp._vlm_proven_local({}) is None
    assert hp._vlm_proven_local({"JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://10.0.0.5:8000",
                                 "JARVIS_VLM_MODEL": "m"}) is False
    assert hp._vlm_proven_local({"JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://127.0.0.1:8000",
                                 "JARVIS_VLM_MODEL": "m"}) is True


# ── injection discipline ─────────────────────────────────────────────────────

def test_empty_calls_means_no_os_call_and_every_permission_unknown():
    probe = hp.probe_host(_wayland(), _importer("gi", "libei"), {}, sys_platform="linux")
    assert probe.permissions["portal_remote_desktop_version"] is None
    assert probe.permissions["process_elevated"] is None
    assert probe.permissions["uinput_writable"] is None
    assert probe.permissions["vlm_proven_local"] is None
    assert all(v is False for v in probe.binaries.values())
    assert "wayland_input_unavailable" in probe.refusals


def test_a_raising_call_or_importer_is_a_fact_not_a_crash():
    def boom(**_):
        raise RuntimeError("dbus exploded")

    def broken_importer(name):
        raise ValueError("broken parent package")

    probe = hp.probe_host(_wayland(), broken_importer, _calls(portal_remote_desktop_version=boom), sys_platform="linux")
    assert all(v is False for v in probe.deps.values())
    assert probe.permissions["portal_remote_desktop_version"] is None


def test_flags_are_reported_never_enforced():
    env = {"JARVIS_DESKTOP_HOST": "1", "JARVIS_DESKTOP_ISOLATED": "true", "JARVIS_PLAYWRIGHT_HOST": "no"}
    on = hp.probe_host(env, _importer(), _calls(), sys_platform="linux")
    off = hp.probe_host({}, _importer(), _calls(), sys_platform="linux")
    assert on.flags == {"JARVIS_DESKTOP_HOST": True, "JARVIS_DESKTOP_ISOLATED": True,
                        "JARVIS_PLAYWRIGHT_HOST": False, "JARVIS_TERMINAL_LOCAL_HOST": False}
    assert on.refusals == off.refusals == ("desktop_platform_unsupported",)


def test_probe_host_defaults_run_on_this_ci_box_without_prompting(monkeypatch):
    """The real defaults on a headless runner: a platform verdict, seven bool
    deps, and no exception — the probe is safe to call from a route."""
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    probe = hp.probe_host()
    assert probe.platform in hp.PLATFORMS
    assert tuple(probe.deps) == hp.DEP_NAMES
    assert all(type(v) is bool for v in probe.deps.values())
    assert len(probe.fingerprint) == 64


# ── the contract object ──────────────────────────────────────────────────────

def _deps(**present):
    return {name: bool(present.get(name, False)) for name in hp.DEP_NAMES}


def test_host_probe_rejects_refusals_outside_the_vocabulary():
    with pytest.raises(hp.HostProbeError, match="vocabulary"):
        hp.HostProbe(platform="macos", deps=_deps(), permissions={}, refusals=("made_up_reason",))
    with pytest.raises(hp.HostProbeError, match="platform"):
        hp.HostProbe(platform="amiga", deps=_deps(), permissions={})
    with pytest.raises(hp.HostProbeError, match="DEP_NAMES"):
        hp.HostProbe(platform="macos", deps={"pywinauto": True}, permissions={})
    with pytest.raises(hp.HostProbeError, match="unique"):
        hp.HostProbe(platform="macos", deps=_deps(), permissions={},
                     refusals=("atspi_unavailable", "atspi_unavailable"))
    probe = hp.HostProbe(platform="macos", deps=_deps(), permissions={})
    with pytest.raises(hp.HostProbeError):
        probe.refuses("made_up_reason")


def test_host_probe_is_frozen_and_fingerprint_moves_only_with_facts():
    a = hp.HostProbe(platform="linux-x11", deps=_deps(gi_atspi=True), permissions={"x": 1}, refusals=())
    b = hp.HostProbe(platform="linux-x11", deps=_deps(gi_atspi=True), permissions={"x": 1}, refusals=())
    c = hp.HostProbe(platform="linux-x11", deps=_deps(gi_atspi=False), permissions={"x": 1},
                     refusals=("atspi_unavailable",))
    assert a.fingerprint == b.fingerprint != c.fingerprint
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.platform = "macos"   # type: ignore[misc]
    d = c.to_dict()
    assert d["ok"] is False and d["refusals"] == ["atspi_unavailable"]
    assert d["hints"] == {"atspi_unavailable": hp.REFUSAL_HINTS["atspi_unavailable"]}
    assert d["fingerprint"] == c.fingerprint


import dataclasses  # noqa: E402  (used by the frozen-instance assertion above)

# ── the route ────────────────────────────────────────────────────────────────

def _app(guard=None):
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[user_guard] = guard or (lambda: None)
    return application


def test_route_is_user_guarded():
    async def _deny():
        raise HTTPException(status_code=401, detail="user token required")
    r = TestClient(_app(_deny)).get("/api/host/probe")
    assert r.status_code == 401


def test_route_round_trip_returns_the_probe_verbatim(monkeypatch):
    calls = _calls(ax_is_process_trusted=lambda: False, cg_preflight_screen_capture=lambda: True,
                   vlm_proven_local=lambda **_: None)
    monkeypatch.setattr(
        routes, "_probe",
        lambda: hp.probe_host({"JARVIS_DESKTOP_HOST": "1"}, _importer("ApplicationServices"), calls,
                              sys_platform="darwin"),
    )
    r = TestClient(_app()).get("/api/host/probe")
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("no-cache")
    body = r.json()
    assert body["probed"] is True and body["ok"] is False
    assert body["platform"] == "macos"
    assert body["refusals"] == ["accessibility_permission_missing"]
    assert body["hints"]["accessibility_permission_missing"] == hp.REFUSAL_HINTS["accessibility_permission_missing"]
    assert body["permissions"]["accessibility_trusted"] is False
    assert body["deps"]["pyobjc"] is True
    assert body["flags"]["JARVIS_DESKTOP_HOST"] is True
    assert body["vocabulary"] == sorted(SPEC_VOCABULARY)
    assert set(body["vocabulary_hints"]) == SPEC_VOCABULARY
    assert isinstance(body["probed_at"], float) and len(body["fingerprint"]) == 64


def test_route_reports_probe_failed_without_exception_text(monkeypatch):
    def boom():
        raise RuntimeError("secret /path/to/thing")
    monkeypatch.setattr(routes, "_probe", boom)
    r = TestClient(_app()).get("/api/host/probe")
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": False, "probed": False, "reason": "probe_failed",
                    "vocabulary": sorted(SPEC_VOCABULARY), "probed_at": body["probed_at"]}
    assert "secret" not in r.text and "/path/to" not in r.text


def test_route_default_probe_is_the_real_probe_run_off_the_loop():
    """No monkeypatch: the route runs ``probe_host`` for real (headless CI box)."""
    r = TestClient(_app()).get("/api/host/probe")
    assert r.status_code == 200
    body = r.json()
    assert body["probed"] is True
    assert body["platform"] in hp.PLATFORMS
    assert tuple(body["deps"]) == hp.DEP_NAMES
