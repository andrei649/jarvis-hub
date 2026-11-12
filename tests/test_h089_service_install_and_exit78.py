"""H089 — the gateway process under a service manager.

What the owner can do and observe:

* every refused configuration that no restart can cure leaves with 78, which the shipped
  units do not respawn on: a boot guard (open bind without a token, an unguarded channel, a
  mistyped posture flag, a guard in the lifespan that uvicorn swallowed), a refused profile;
  a ``.env`` refusal is retried once and is 78 when it repeats;
* under the launchd agent (no "do not restart on 78" there) a permanent refusal leaves 0;
* ``nerva service install|uninstall|show`` writes a systemd user unit or a launchd agent
  for this checkout, never replaces or follows a file it did not write, and only runs fixed
  manager commands when asked (``--now``).
"""
from __future__ import annotations

import io
import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.cli import service_install as si
from agents.core import boot_guards, boot_refusal
from agents.core.env_alias import ConfigurationRefused

# ── exit 78 ──────────────────────────────────────────────────────────────────────

def test_an_open_bind_without_a_token_is_a_permanent_refusal(monkeypatch):
    for name in ("JARVIS_USER_TOKEN", "JARVIS_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_ADMIN_TOKEN",
                 "JARVIS_ALLOW_INSECURE_BIND", "NERVA_ALLOW_INSECURE_BIND"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as stopped:
        boot_guards.assert_safe_bind("0.0.0.0")
    assert isinstance(stopped.value, ConfigurationRefused)
    assert stopped.value.exit_status == 78
    assert "without authentication" in str(stopped.value.code)   # the old text, unchanged
    assert boot_guards.last_refusal() is stopped.value


def test_a_mistyped_posture_flag_is_a_permanent_refusal():
    with pytest.raises(ConfigurationRefused) as stopped:
        boot_guards.assert_parseable_posture_flags({"JARVIS_CHANNEL_OPEN": "maybe"})
    assert stopped.value.exit_status == 78


def test_a_plain_systemexit_from_a_lifespan_guard_becomes_permanent(monkeypatch):
    import agents.core.proxy_trust as proxy_trust

    def refuse(*_a, **_k):
        raise SystemExit("Refusing to start: JARVIS_TRUSTED_PROXIES is not a CIDR list")

    monkeypatch.setattr(proxy_trust, "assert_parseable_trusted_proxies", refuse)
    monkeypatch.setattr(boot_guards, "assert_parseable_posture_flags", lambda *a, **k: None)
    with pytest.raises(ConfigurationRefused) as stopped:
        boot_guards.enforce_boot_posture()
    assert stopped.value.exit_status == 78
    assert "TRUSTED_PROXIES" in str(stopped.value)
    assert boot_guards.last_refusal() is stopped.value


def test_a_numeric_systemexit_passes_through_unchanged(monkeypatch):
    def stop():
        raise SystemExit(3)

    with pytest.raises(SystemExit) as stopped:
        boot_guards._permanent_refusals(stop)()
    assert not isinstance(stopped.value, ConfigurationRefused) and stopped.value.code == 3


def test_a_dotenv_refusal_is_retried_once_then_permanent(tmp_path):
    marker = tmp_path / "boot-refusal.json"
    refused = ConfigurationRefused("JARVIS_HOME in .env names ${UNSET}", permanent=False)
    assert boot_refusal.exit_status(refused, path=marker, now=1000.0, wrapper="") == 1
    assert boot_refusal.exit_status(refused, path=marker, now=1060.0, wrapper="") == 78
    other = ConfigurationRefused("another refusal", permanent=False)
    assert boot_refusal.exit_status(other, path=marker, now=1070.0, wrapper="") == 1
    # outside the window it is a fresh, retried refusal again
    assert boot_refusal.exit_status(other, path=marker, now=1070.0 + 3600, wrapper="") == 1
    # a start that got past the configuration forgets it
    boot_refusal.clear(marker)
    assert not marker.exists()
    assert boot_refusal.exit_status(other, path=marker, now=9000.0, wrapper="") == 1
    assert "another refusal" not in marker.read_text()     # only a digest is kept


def test_a_permanent_refusal_never_touches_the_marker(tmp_path):
    marker = tmp_path / "boot-refusal.json"
    assert boot_refusal.exit_status(ConfigurationRefused("x", permanent=True), path=marker, wrapper="") == 78
    assert not marker.exists()


def test_a_corrupt_or_linked_marker_is_ignored(tmp_path):
    marker = tmp_path / "boot-refusal.json"
    marker.write_text("{not json")
    assert boot_refusal.exit_status(ConfigurationRefused("y"), path=marker, now=5.0, wrapper="") == 1
    target = tmp_path / "elsewhere.json"
    target.write_text('{"digest": "x", "at": 5}')
    marker.unlink()
    marker.symlink_to(target)
    assert boot_refusal.exit_status(ConfigurationRefused("y"), path=marker, now=6.0, wrapper="") == 1


def test_under_launchd_a_permanent_refusal_leaves_zero(tmp_path):
    assert boot_refusal.exit_status(ConfigurationRefused("z", permanent=True),
                                    path=tmp_path / "m.json", wrapper="launchd") == 0
    assert boot_refusal.exit_status(ConfigurationRefused("z", permanent=True),
                                    path=tmp_path / "m.json", wrapper="nssm") == 78


def test_a_server_whose_lifespan_refused_leaves_78(monkeypatch, tmp_path):
    import serve

    monkeypatch.setattr(serve, "_restart_path", lambda environ=None: None)
    monkeypatch.setattr(boot_refusal, "_marker", lambda path: tmp_path / "m.json")
    monkeypatch.delenv("NERVA_SERVICE_WRAPPER", raising=False)

    class _Refused:
        started = False

        def run(self):
            boot_guards._refuse("Refusing to start: the telegram bot would answer any sender.")

    with pytest.raises(SystemExit) as stopped:
        serve.run_server(_Refused())
    assert stopped.value.code == 78

    class _Crashed:
        started = False

        def run(self):
            boot_guards._LAST_REFUSAL.clear()

    with pytest.raises(SystemExit) as stopped:
        serve.run_server(_Crashed())
    assert stopped.value.code == serve.STARTUP_FAILED_EXIT


# ── nerva service ────────────────────────────────────────────────────────────────

ROOT = Path("/opt/my nerva/50%off")


def test_the_user_unit_quotes_paths_and_does_not_restart_on_78():
    unit = si.systemd_user_unit("/opt/my nerva/.venv/bin/py$thon", ROOT)
    assert "RestartPreventExitStatus=78" in unit and "Restart=on-failure" in unit
    assert "Type=notify" in unit and "WantedBy=default.target" in unit
    assert 'ExecStart="/opt/my nerva/.venv/bin/py$$thon" "/opt/my nerva/50%%off/serve.py"' in unit
    assert "WorkingDirectory=/opt/my nerva/50%%off" in unit
    assert si.MARKER in unit


def test_a_control_character_in_a_path_is_refused():
    with pytest.raises(si.ServiceError):
        si.systemd_user_unit("/usr/bin/python3", Path("/opt/x\nExecStartPre=/bin/rm"))


def test_the_launchd_agent():
    data = plistlib.loads(si.launchd_plist("/usr/bin/python3", ROOT, Path("/data/logs")))
    assert data["Label"] == si.LAUNCHD_LABEL
    assert data["ProgramArguments"] == ["/usr/bin/python3", str(ROOT / "serve.py")]
    assert data["KeepAlive"] == {"SuccessfulExit": False} and data["RunAtLoad"] is True
    assert data["EnvironmentVariables"] == {"NERVA_SERVICE_WRAPPER": "launchd"}
    assert data["StandardErrorPath"] == "/data/logs/service.err.log"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("NERVA_PROFILE", raising=False)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "serve.py").write_text("# hub\n")
    return tmp_path, checkout


def _ctx(environ=None):
    out, err = io.StringIO(), io.StringIO()
    ctx = SimpleNamespace(environ=environ if environ is not None else dict(os.environ), out=out, err=err,
                          say=lambda text="": out.write(text + "\n"))
    return ctx


def _ns(action, **kw):
    return SimpleNamespace(action=action, dry_run=kw.get("dry_run", False), force=kw.get("force", False),
                           now=kw.get("now", False))


def test_install_show_uninstall_on_linux(home, monkeypatch):
    tmp, checkout = home
    monkeypatch.setattr("agents.core.service_status.systemctl_path", lambda **_: "/usr/bin/systemctl")
    ran = []

    def runner(argv):
        ran.append(argv)
        return 0, ""

    ctx = _ctx()
    assert si.run(_ns("install", dry_run=True, now=True), ctx, platform="linux", python="/usr/bin/python3",
                  root=checkout, runner=runner) == 0
    unit = tmp / ".config/systemd/user/jarvis-hub.service"
    assert not unit.exists() and ran == []
    assert "would run: /usr/bin/systemctl --user enable --now jarvis-hub.service" in ctx.out.getvalue()

    ctx = _ctx()
    assert si.run(_ns("install", now=True), ctx, platform="linux", python="/usr/bin/python3",
                  root=checkout, runner=runner) == 0
    assert unit.is_file() and oct(unit.stat().st_mode & 0o777) == "0o644"
    assert ran == [["/usr/bin/systemctl", "--user", "daemon-reload"],
                   ["/usr/bin/systemctl", "--user", "enable", "--now", "jarvis-hub.service"]]
    assert "enable-linger" in ctx.out.getvalue()

    ctx = _ctx()
    si.run(_ns("show"), ctx, platform="linux", runner=runner)
    assert "installed:" in ctx.out.getvalue()

    ran.clear()
    ctx = _ctx()
    assert si.run(_ns("uninstall"), ctx, platform="linux", runner=runner) == 0
    assert not unit.exists()
    assert ran[0] == ["/usr/bin/systemctl", "--user", "disable", "--now", "jarvis-hub.service"]


def test_install_refuses_a_foreign_file_and_a_link(home, monkeypatch):
    tmp, checkout = home
    unit = tmp / ".config/systemd/user/jarvis-hub.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Service]\nExecStart=/somebody/else\n")
    ctx = _ctx()
    assert si.run(_ns("install"), ctx, platform="linux", python="/usr/bin/python3", root=checkout) == 1
    assert "was not written by this command" in ctx.err.getvalue()
    assert unit.read_text() == "[Service]\nExecStart=/somebody/else\n"
    ctx = _ctx()
    assert si.run(_ns("uninstall"), ctx, platform="linux") == 1 and unit.exists()
    # --force replaces it
    assert si.run(_ns("install", force=True), _ctx(), platform="linux", python="/usr/bin/python3",
                  root=checkout) == 0
    assert si.MARKER in unit.read_text()

    unit.unlink()
    victim = tmp / "victim"
    victim.write_text("keep")
    unit.symlink_to(victim)
    ctx = _ctx()
    assert si.run(_ns("install", force=True), ctx, platform="linux", python="/usr/bin/python3",
                  root=checkout) == 1
    assert "is a link" in ctx.err.getvalue() and victim.read_text() == "keep"


def test_install_on_macos_writes_the_agent(home):
    tmp, checkout = home
    ctx = _ctx()
    assert si.run(_ns("install"), ctx, platform="darwin", python="/usr/bin/python3", root=checkout) == 0
    plist = tmp / "Library/LaunchAgents/ai.nerva.hub.plist"
    data = plistlib.loads(plist.read_bytes())
    assert data["WorkingDirectory"] == str(checkout)
    assert (tmp / "data" / "logs").is_dir()
    assert "launchctl bootstrap gui/" in ctx.out.getvalue()


def test_a_profile_and_windows_are_refused(home):
    _tmp, checkout = home
    ctx = _ctx({**os.environ, "JARVIS_PROFILE": "work"})
    assert si.run(_ns("install"), ctx, platform="linux", python="/usr/bin/python3", root=checkout) == 1
    assert "default profile only" in ctx.err.getvalue()
    ctx = _ctx()
    assert si.run(_ns("install"), ctx, platform="win32") == 2
    assert "install-service.ps1" in ctx.err.getvalue()


def test_the_verb_is_wired_into_nerva(home):
    from agents.cli import nerva

    out, err = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ=dict(os.environ), out=out, err=err)
    code = nerva.main(["service", "show"], context=ctx)
    assert code in (0, 2)
