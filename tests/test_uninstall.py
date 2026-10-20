"""Provable software uninstall (0.22 — the appliance install/update tail).

Mirrors the `test_forget_export_purge_parity.py` discipline for the software side of the
same promise: `data_purge` proves a forget erases everything an export can reveal about
the user's *content*; this proves `uninstall` removes everything the installers put on
disk for the *software*, and nothing else — the data root is never touched unless the
caller explicitly opts into `--purge-data`.
"""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agents.core import uninstall as un

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every UNINSTALL_TARGETS entry must trace to a concrete line in the installer that
# actually creates it. This is a drift guard for the targets already named here — not
# proof no new installer-created artifact could ever escape uninstall (see the module
# docstring); a marker going missing means an installer stopped creating that target and
# the row in UNINSTALL_TARGETS is now dead weight (or the marker itself went stale).
INSTALL_MARKERS = {
    # install.sh / INSTALL.bat hand the venv step to scripts/bootstrap.py (ensure_venv),
    # so the marker for .venv lives there.
    ".venv": ("scripts/bootstrap.py", 'VENV_DIR = ".venv"'),
    "worldview/node_modules": ("install.sh", "cd worldview && npm install"),
    "worldview/.env": ("install.sh", "worldview/.env.example"),
    "worldview/backend-api/.env": ("install.sh", "worldview/backend-api/.env.example"),
    "worldview/frontend/.env.local": ("install.sh", "worldview/frontend/.env.local.example"),
    "worldview/ingestion-workers/.env": ("INSTALL.bat", "worldview\\ingestion-workers\\.env.example"),
    "worldview/ingestion-workers/.venv": ("INSTALL.bat", "worldview\\ingestion-workers\\.venv"),
}


def test_every_target_traces_to_an_installer():
    assert set(INSTALL_MARKERS) == set(un.UNINSTALL_TARGETS), (
        "UNINSTALL_TARGETS and the installer marker map have drifted apart — keep them "
        "in lockstep in tests/test_uninstall.py"
    )
    texts = {
        name: (REPO_ROOT / name).read_text(encoding="utf-8")
        for name in {script for script, _ in INSTALL_MARKERS.values()}
    }
    missing = [
        target for target, (script, marker) in INSTALL_MARKERS.items()
        if marker not in texts[script]
    ]
    assert not missing, (
        f"installer no longer creates: {missing} — drop from UNINSTALL_TARGETS "
        "(agents/core/uninstall.py) or fix the stale marker"
    )


@pytest.fixture()
def app_root(tmp_path):
    root = tmp_path / "app"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "worldview" / "node_modules" / "some-pkg").mkdir(parents=True)
    (root / "worldview" / ".env").write_text("KEY=1\n", encoding="utf-8")
    (root / "worldview" / "backend-api").mkdir(parents=True)
    (root / "worldview" / "backend-api" / ".env").write_text("KEY=2\n", encoding="utf-8")
    (root / "worldview" / "frontend").mkdir(parents=True)
    (root / "worldview" / "frontend" / ".env.local").write_text("KEY=3\n", encoding="utf-8")
    # ingestion-workers targets intentionally left absent — Linux-only installer path.
    # Sibling content that must survive any uninstall, no matter what.
    (root / "memory_logs").mkdir()
    (root / "memory_logs" / "settings.db").write_text("not-a-real-db", encoding="utf-8")
    (root / "agents" / "core").mkdir(parents=True)
    (root / "agents" / "core" / "uninstall.py").write_text("# source\n", encoding="utf-8")
    return root


def test_plan_reports_existing_and_absent(app_root):
    plan = un.plan_uninstall(app_root)
    by_path = {t["path"]: t for t in plan["targets"]}
    assert by_path[".venv"]["exists"] is True
    assert by_path[".venv"]["kind"] == "dir"
    assert by_path["worldview/.env"]["kind"] == "file"
    assert by_path["worldview/ingestion-workers/.venv"]["exists"] is False
    assert by_path["worldview/ingestion-workers/.venv"]["kind"] == "absent"


def test_run_removes_only_installer_targets(app_root):
    report = un.run_uninstall(app_root)
    assert report["ok"] is True
    assert set(report["removed"]) == {
        ".venv", "worldview/node_modules", "worldview/.env",
        "worldview/backend-api/.env", "worldview/frontend/.env.local",
    }
    assert set(report["already_absent"]) == {
        "worldview/ingestion-workers/.env", "worldview/ingestion-workers/.venv",
    }
    assert not (app_root / ".venv").exists()
    assert not (app_root / "worldview" / "node_modules").exists()
    assert not (app_root / "worldview" / ".env").exists()
    # Untouched: source tree and the user's data root.
    assert (app_root / "agents" / "core" / "uninstall.py").exists()
    assert (app_root / "memory_logs" / "settings.db").read_text() == "not-a-real-db"


def test_run_is_idempotent(app_root):
    first = un.run_uninstall(app_root)
    assert first["ok"] is True
    second = un.run_uninstall(app_root)
    assert second["ok"] is True
    assert second["removed"] == []
    assert set(second["already_absent"]) == set(un.UNINSTALL_TARGETS)


def test_purge_data_is_opt_in_and_delegated(app_root, monkeypatch):
    calls = []

    def fake_purge(*, source_root, backup_first, memory):
        calls.append({"source_root": source_root, "backup_first": backup_first, "memory": memory})
        return {"ok": True, "total_rows": 0}

    monkeypatch.setattr("agents.core.data_purge.purge_data", fake_purge)

    without = un.run_uninstall(app_root)
    assert "data_purge" not in without
    assert calls == []

    with_purge = un.run_uninstall(app_root, purge_data=True, data_source_root=str(app_root / "memory_logs"))
    assert with_purge["data_purge"] == {"ok": True, "total_rows": 0}
    assert calls == [{
        "source_root": str(app_root / "memory_logs"), "backup_first": True, "memory": True,
    }]


def test_purge_data_runs_before_targets_are_removed(app_root, monkeypatch):
    """The venv (and its dependencies, e.g. cryptography for the backup) must still be
    on disk when data_purge runs — see run_uninstall's docstring for why."""
    seen_venv_present = []

    def fake_purge(*, source_root, backup_first, memory):
        seen_venv_present.append((app_root / ".venv").exists())
        return {"ok": True, "total_rows": 0}

    monkeypatch.setattr("agents.core.data_purge.purge_data", fake_purge)
    un.run_uninstall(app_root, purge_data=True)
    assert seen_venv_present == [True]
    assert not (app_root / ".venv").exists()  # still removed afterward


def test_purge_error_aborts_before_any_target_is_removed(app_root, monkeypatch):
    from agents.core.data_purge import PurgeError

    def raising_purge(*, source_root, backup_first, memory):
        raise PurgeError("pre-forget backup failed verification")

    monkeypatch.setattr("agents.core.data_purge.purge_data", raising_purge)
    with pytest.raises(PurgeError):
        un.run_uninstall(app_root, purge_data=True)
    # Nothing removed — the software install is left intact to retry.
    assert (app_root / ".venv").exists()
    assert (app_root / "worldview" / "node_modules").exists()


def test_cli_purge_error_reported_cleanly(app_root, monkeypatch, capsys):
    from agents.core.data_purge import PurgeError

    def raising_purge(*, source_root, backup_first, memory):
        raise PurgeError("pre-forget backup failed verification")

    monkeypatch.setattr("agents.core.data_purge.purge_data", raising_purge)
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_path()}",
                   "--root", str(app_root)])
    assert rc == 1
    assert "uninstall aborted" in capsys.readouterr().out
    assert (app_root / ".venv").exists()


def test_cli_refuses_without_confirm(capsys):
    rc = un._main([])
    assert rc == 2
    assert "--confirm" in capsys.readouterr().out


def test_cli_confirm_runs_and_prints_json(app_root, capsys):
    rc = un._main(["--confirm", "--root", str(app_root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert not (app_root / ".venv").exists()


# ── H014: dry run, typed purge confirmation, desktop app, `nerva uninstall` ─────────────


def _data_name() -> str:
    from agents.core.paths import data_root
    return data_root().name


def _data_path() -> str:
    """--yes-purge takes the data root's full path (binds a script to one machine's root)."""
    from agents.core.paths import data_root
    return str(data_root())


class _Tty(io.StringIO):
    """A stdin that claims to be a terminal, holding what the owner types."""

    def isatty(self):
        return True


def _snapshot(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _fake_purge(calls):
    def fake(*, source_root, backup_first, memory):
        calls.append(backup_first)
        return {"ok": True, "total_rows": 0}
    return fake


def test_plan_reports_purge_flag_and_data_root(app_root):
    assert un.plan_uninstall(app_root)["purge_data"] is False
    assert "data_root" not in un.plan_uninstall(app_root)
    plan = un.plan_uninstall(app_root, purge_data=True, data_source_root=str(app_root / "memory_logs"))
    assert plan["purge_data"] is True
    assert plan["data_root"] == str(app_root / "memory_logs")


def test_cli_dry_run_prints_plan_and_removes_nothing(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    before = _snapshot(app_root)
    out = io.StringIO()
    # No --confirm and no typed name needed: a dry run decides nothing.
    rc = un._main(["--dry-run", "--purge-data", "--root", str(app_root)], out=out)
    assert rc == 0
    plan = json.loads(out.getvalue())
    assert plan["dry_run"] is True
    assert plan["purge_data"] is True
    from agents.core.paths import data_root
    assert plan["data_root"] == str(data_root())
    by_path = {t["path"]: t for t in plan["targets"]}
    assert by_path[".venv"]["exists"] is True
    assert by_path["worldview/ingestion-workers/.venv"]["exists"] is False
    assert _snapshot(app_root) == before
    assert calls == []


def test_cli_dry_run_without_purge_says_data_is_kept(app_root):
    out = io.StringIO()
    assert un._main(["--dry-run", "--root", str(app_root)], out=out) == 0
    plan = json.loads(out.getvalue())
    assert plan["purge_data"] is False
    assert "desktop" not in plan
    assert (app_root / ".venv").exists()


def test_cli_purge_needs_typed_name_when_not_a_terminal(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", "--root", str(app_root)], out=out, inp=io.StringIO(""))
    assert rc == 2
    assert f"--yes-purge={_data_path()}" in out.getvalue()
    assert calls == []
    assert (app_root / ".venv").exists()  # a refused purge removes no software either


def test_cli_purge_wrong_yes_purge_is_refused(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", "--yes-purge=not-it", "--root", str(app_root)], out=out)
    assert rc == 2
    assert "is not the data root's absolute path" in out.getvalue()
    assert calls == []
    assert (app_root / ".venv").exists()


def test_cli_purge_right_yes_purge_runs(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_path()}",
                   "--root", str(app_root)], out=out)
    assert rc == 0
    assert calls == [True]
    assert json.loads(out.getvalue())["data_purge"]["ok"] is True
    assert not (app_root / ".venv").exists()


def test_cli_purge_interactive_typed_name(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", "--root", str(app_root)],
                  out=out, inp=_Tty("yes\n"))
    assert rc == 2
    assert "Type the folder name" in out.getvalue()
    assert "purge cancelled" in out.getvalue()
    assert calls == [] and (app_root / ".venv").exists()

    rc = un._main(["--confirm", "--purge-data", "--root", str(app_root)],
                  out=io.StringIO(), inp=_Tty(_data_name() + "\n"))
    assert rc == 0
    assert calls == [True]


def test_desktop_identity_matches_tauri_config():
    conf = json.loads((REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["productName"] == un.DESKTOP_PRODUCT_NAME
    assert conf["identifier"] == un.DESKTOP_IDENTIFIER
    cargo = (REPO_ROOT / "desktop" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert f'name = "{un.DESKTOP_BINARY}"' in cargo


def test_desktop_macos_app_and_caches_removed(app_root, tmp_path):
    home, sysroot = tmp_path / "home", tmp_path / "sys"
    app = sysroot / "Applications" / "Jarvis Hub.app" / "Contents"
    app.mkdir(parents=True)
    caches = home / "Library" / "Caches" / "com.jarvis.hub"
    caches.mkdir(parents=True)
    other = home / "Library" / "Caches" / "com.other.app"
    other.mkdir(parents=True)
    desktop = {"platform": "darwin", "home": home, "environ": {}, "system_root": sysroot}

    plan = un.plan_uninstall(app_root, gui=True, desktop=desktop)
    existing = {r["path"] for r in plan["desktop"] if r["exists"]}
    assert existing == {str(sysroot / "Applications" / "Jarvis Hub.app"), str(caches)}

    report = un.run_uninstall(app_root, gui=True, desktop=desktop)
    assert report["ok"] is True
    assert set(report["desktop"]["removed"]) == existing
    assert not (sysroot / "Applications" / "Jarvis Hub.app").exists()
    assert not caches.exists()
    assert other.exists()
    assert (app_root / "memory_logs" / "settings.db").exists()


def test_desktop_windows_nsis_uninstaller_and_msi_manual(app_root, tmp_path):
    local, roaming, pf = tmp_path / "Local", tmp_path / "Roaming", tmp_path / "PF"
    nsis = local / "Jarvis Hub"
    nsis.mkdir(parents=True)
    (nsis / "uninstall.exe").write_bytes(b"MZ")
    (pf / "Jarvis Hub").mkdir(parents=True)  # MSI: no uninstall.exe
    (local / "com.jarvis.hub" / "EBWebView").mkdir(parents=True)
    lnk = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Jarvis Hub.lnk"
    lnk.parent.mkdir(parents=True)
    lnk.write_text("lnk")
    desktop = {"platform": "win32", "home": tmp_path, "system_root": tmp_path,
               "environ": {"LOCALAPPDATA": str(local), "APPDATA": str(roaming), "ProgramFiles": str(pf)}}
    ran = []
    report = un.run_uninstall(app_root, gui=True, desktop=desktop,
                              runner=lambda argv: ran.append(argv) or 0)
    # `_?=<dir>` makes NSIS run in place and wait, instead of relaunching from %TEMP%
    # and exiting 0 before anything is gone.
    assert ran == [[str(nsis / "uninstall.exe"), "/S", f"_?={nsis}"]]
    assert str(nsis) in report["desktop"]["removed"]
    assert not nsis.exists()  # the uninstall.exe `_?=` leaves behind is removed too
    assert not (local / "com.jarvis.hub").exists() and not lnk.exists()
    assert report["desktop"]["manual"] == [{
        "path": str(pf / "Jarvis Hub"),
        "hint": "remove 'Jarvis Hub' in Settings > Apps (MSI install)",
    }]
    assert (pf / "Jarvis Hub").exists()
    assert report["ok"] is True


def test_desktop_failed_uninstaller_makes_ok_false(app_root, tmp_path):
    nsis = tmp_path / "Local" / "Jarvis Hub"
    nsis.mkdir(parents=True)
    (nsis / "uninstall.exe").write_bytes(b"MZ")
    desktop = {"platform": "win32", "home": tmp_path, "environ": {"LOCALAPPDATA": str(tmp_path / "Local")}}
    report = un.run_uninstall(app_root, gui=True, desktop=desktop, runner=lambda argv: 1)
    assert report["ok"] is False
    assert str(nsis) in report["not_removed"]


def test_desktop_linux_appimage_xdg_and_package_manager(app_root, tmp_path):
    home, sysroot = tmp_path / "home", tmp_path / "sys"
    (sysroot / "usr" / "bin").mkdir(parents=True)
    (sysroot / "usr" / "bin" / "jarvis-hub-desktop").write_text("elf")
    apps = home / "Applications"
    apps.mkdir(parents=True)
    (apps / "jarvis-hub_0.9.2_amd64.AppImage").write_text("img")
    (apps / "other-tool.AppImage").write_text("img")
    (home / ".local" / "share" / "com.jarvis.hub").mkdir(parents=True)
    desktop = {"platform": "linux", "home": home, "environ": {}, "system_root": sysroot}
    report = un.run_uninstall(app_root, gui=True, desktop=desktop)
    assert report["ok"] is True
    assert not (apps / "jarvis-hub_0.9.2_amd64.AppImage").exists()
    assert (apps / "other-tool.AppImage").exists()
    assert not (home / ".local" / "share" / "com.jarvis.hub").exists()
    (manual,) = report["desktop"]["manual"]
    assert manual["path"] == str(sysroot / "usr" / "bin" / "jarvis-hub-desktop")
    assert "apt remove jarvis-hub" in manual["hint"]
    assert (sysroot / "usr" / "bin" / "jarvis-hub-desktop").exists()


def test_cli_gui_flag_reaches_desktop_removal(app_root, monkeypatch):
    seen = []
    monkeypatch.setattr(un, "desktop_app_targets", lambda **kw: seen.append(kw) or [])
    out = io.StringIO()
    assert un._main(["--dry-run", "--gui", "--root", str(app_root)], out=out) == 0
    assert json.loads(out.getvalue())["desktop"] == []
    out = io.StringIO()
    assert un._main(["--confirm", "--gui", "--root", str(app_root)], out=out) == 0
    assert json.loads(out.getvalue())["desktop"] == {"removed": [], "manual": [], "not_removed": []}
    assert len(seen) == 2


def _ctx(out, inp=""):
    from agents.cli.nerva import Context
    return Context(environ={}, out=out, err=io.StringIO(), inp=io.StringIO(inp))


def test_nerva_uninstall_verb_delegates(app_root, monkeypatch):
    from agents.cli.nerva import main

    out = io.StringIO()
    assert main(["uninstall", "--dry-run", "--root", str(app_root)], context=_ctx(out)) == 0
    assert json.loads(out.getvalue())["dry_run"] is True
    assert (app_root / ".venv").exists()

    out = io.StringIO()
    assert main(["uninstall", "--root", str(app_root)], context=_ctx(out)) == 2
    assert "--confirm" in out.getvalue()

    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    rc = main(["uninstall", "--confirm", "--purge-data", "--root", str(app_root)],
              context=_ctx(io.StringIO()))
    assert rc == 2 and calls == []
    rc = main(["uninstall", "--confirm", "--purge-data", "--yes-purge", _data_path(),
               "--root", str(app_root)], context=_ctx(io.StringIO()))
    assert rc == 0 and calls == [True]
    assert not (app_root / ".venv").exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_uninstall_sh_dry_run_passes_through(tmp_path):
    """The shell wrapper's --dry-run reaches the module and removes nothing."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python3").symlink_to(sys.executable)
    before = (REPO_ROOT / ".venv").exists()
    home = tmp_path / "home"
    home.mkdir()
    # Host-independent: --gui probes the desktop paths under HOME/XDG, so point them at tmp.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("XDG_") and k not in ("JARVIS_USER_HOME", "JARVIS_PROFILE")}
    env.update({"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(home),
                "XDG_DATA_HOME": str(home / "d"), "XDG_CACHE_HOME": str(home / "c"),
                "XDG_CONFIG_HOME": str(home / "f")})
    res = subprocess.run(["bash", str(REPO_ROOT / "uninstall.sh"), "--dry-run", "--purge-data", "--gui"],
                         capture_output=True, text=True, env=env, timeout=120, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    plan = json.loads(res.stdout[res.stdout.index("{"):res.stdout.rindex("}") + 1])
    assert plan["dry_run"] is True and plan["purge_data"] is True and "desktop" in plan
    assert all(r["path"].startswith(str(home)) or r["path"].startswith("/usr/bin/")
               or r["role"] == "source_build" for r in plan["desktop"])
    assert {r["path"] for r in plan["desktop"] if r["role"] == "source_build"} == {
        str(REPO_ROOT / "desktop" / "src-tauri" / "target")}
    assert "nothing was removed" in res.stdout
    assert (REPO_ROOT / ".venv").exists() == before


def test_wrappers_forward_new_flags():
    sh = (REPO_ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "--yes-purge=*" in sh and '"--yes-purge=$YES_PURGE"' in sh
    assert "ARGS+=(--gui)" in sh and "ARGS=(--dry-run)" in sh
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    assert '"/DRYRUN" (set "DRYRUN=--dry-run" & set "KNOWN=1")' in bat
    assert '"/GUI" (set "GUIFLAG=1" & set "KNOWN=1")' in bat
    assert "agents.core.uninstall --dry-run !GUI! !PURGEDATA!" in bat
    assert "agents.core.uninstall --confirm !GUI! !PURGEDATA! !YESPURGE! !NOBACKUP!" in bat



# ── review round 1 (H014 r1) ─────────────────────────────────────


def _nsis(tmp_path):
    local = tmp_path / "Local"
    nsis = local / "Jarvis Hub"
    nsis.mkdir(parents=True)
    (nsis / "uninstall.exe").write_bytes(b"MZ")
    (nsis / "jarvis-hub-desktop.exe").write_bytes(b"MZ")
    return nsis, {"platform": "win32", "home": tmp_path, "environ": {"LOCALAPPDATA": str(local)}}


def test_desktop_nsis_exit0_but_dir_left_is_not_removed(app_root, tmp_path, monkeypatch):
    """An exit code of 0 is not proof: the path is re-checked before it is called removed."""
    nsis, desktop = _nsis(tmp_path)
    monkeypatch.setattr(un.shutil, "rmtree", lambda *a, **k: None)  # leftovers survive
    report = un.run_uninstall(app_root, gui=True, desktop=desktop, runner=lambda argv: 0)
    assert str(nsis) not in report["desktop"]["removed"]
    assert str(nsis) in report["not_removed"]
    assert report["ok"] is False


def test_desktop_nsis_in_place_run_then_leftover_removed(app_root, tmp_path):
    nsis, desktop = _nsis(tmp_path)

    def nsis_like(argv):  # what `uninstall.exe /S _?=<dir>` does: everything but itself
        assert argv[-1] == f"_?={nsis}"
        (nsis / "jarvis-hub-desktop.exe").unlink()
        return 0

    report = un.run_uninstall(app_root, gui=True, desktop=desktop, runner=nsis_like)
    assert report["ok"] is True and str(nsis) in report["desktop"]["removed"]
    assert not nsis.exists()


def test_default_runner_keeps_nsis_inplace_token_unquoted(monkeypatch):
    """NSIS only honours `_?=` unquoted and last, even when the dir has a space."""
    seen = []

    class _R:
        returncode = 0

    import subprocess as _sp
    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: seen.append(cmd) or _R())
    assert un._default_runner([r"C:\x\Jarvis Hub\uninstall.exe", "/S", r"_?=C:\x\Jarvis Hub"],
                              windows=True) == 0
    assert seen == [r'"C:\x\Jarvis Hub\uninstall.exe" /S _?=C:\x\Jarvis Hub']


def test_default_runner_missing_tool_is_127():
    assert un._default_runner(["/definitely/not/here-nerva-tool"], windows=False) == 127


def test_desktop_macos_prefs_httpstorages_logs_listed_and_removed(app_root, tmp_path):
    home = tmp_path / "home"
    lib = home / "Library"
    extra = [lib / "Preferences" / "com.jarvis.hub.plist", lib / "HTTPStorages" / "com.jarvis.hub",
             lib / "Logs" / "com.jarvis.hub"]
    extra[0].parent.mkdir(parents=True)
    extra[0].write_text("plist")
    extra[1].mkdir(parents=True)
    extra[2].mkdir(parents=True)
    desktop = {"platform": "darwin", "home": home, "environ": {}, "system_root": tmp_path / "sys"}
    plan = un.plan_uninstall(app_root, gui=True, desktop=desktop)
    assert {str(p) for p in extra} <= {r["path"] for r in plan["desktop"] if r["exists"]}
    report = un.run_uninstall(app_root, gui=True, desktop=desktop)
    assert report["ok"] is True
    assert not any(p.exists() for p in extra)


def test_desktop_linux_appimage_integration_and_menu_refresh(app_root, tmp_path):
    home, data = tmp_path / "home", tmp_path / "xdgdata"
    apps = data / "applications"
    apps.mkdir(parents=True)
    ours = apps / "appimagekit_0123abcd-jarvis-hub.desktop"
    ours.write_text("[Desktop Entry]")
    theirs = apps / "org.gnome.Terminal.desktop"
    theirs.write_text("[Desktop Entry]")
    icons = data / "icons" / "hicolor" / "128x128" / "apps"
    icons.mkdir(parents=True)
    icon = icons / "appimagekit_0123abcd_jarvis-hub.png"
    icon.write_bytes(b"png")
    other_icon = icons / "firefox.png"
    other_icon.write_bytes(b"png")
    desktop = {"platform": "linux", "home": home, "system_root": tmp_path / "sys",
               "environ": {"XDG_DATA_HOME": str(data)}}
    ran = []
    report = un.run_uninstall(app_root, gui=True, desktop=desktop, runner=lambda a: ran.append(a) or 0)
    assert not ours.exists() and not icon.exists()
    assert theirs.exists() and other_icon.exists()
    assert ran == [["update-desktop-database", str(apps)]]
    assert report["desktop"]["menu_cache"] == "refreshed"
    assert report["ok"] is True


def test_desktop_menu_refresh_missing_tool_is_not_a_failure(app_root, tmp_path):
    data = tmp_path / "xdgdata"
    (data / "applications").mkdir(parents=True)
    (data / "applications" / "jarvis-hub.desktop").write_text("[Desktop Entry]")
    desktop = {"platform": "linux", "home": tmp_path / "home", "system_root": tmp_path / "sys",
               "environ": {"XDG_DATA_HOME": str(data)}}
    report = un.run_uninstall(app_root, gui=True, desktop=desktop, runner=lambda a: 127)
    assert report["desktop"]["menu_cache"] == "skipped: update-desktop-database not found"
    assert report["ok"] is True


def test_gui_only_removes_desktop_and_keeps_engine(app_root, tmp_path, monkeypatch):
    """Hermes' `uninstall --gui`: the desktop shell goes, the engine and data stay."""
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    home = tmp_path / "home"
    (home / ".cache" / "com.jarvis.hub").mkdir(parents=True)
    real = un.desktop_app_targets
    monkeypatch.setattr(un, "desktop_app_targets", lambda **kw: real(
        platform="linux", home=home, environ={}, system_root=tmp_path / "sys"))
    out = io.StringIO()
    assert un._main(["--confirm", "--gui-only", "--root", str(app_root)], out=out) == 0
    report = json.loads(out.getvalue())
    assert report["gui_only"] is True
    assert str(home / ".cache" / "com.jarvis.hub") in report["desktop"]["removed"]
    assert "removed" not in report  # no engine target was even considered
    assert (app_root / ".venv").exists() and (app_root / "worldview" / "node_modules").exists()
    assert not (home / ".cache" / "com.jarvis.hub").exists()
    assert calls == []


def test_gui_only_dry_run_plan_has_no_engine_targets(app_root):
    out = io.StringIO()
    assert un._main(["--dry-run", "--gui-only", "--root", str(app_root)], out=out) == 0
    plan = json.loads(out.getvalue())
    assert plan["gui_only"] is True and "desktop" in plan and "targets" not in plan


def test_gui_only_refuses_purge_data(app_root):
    out = io.StringIO()
    rc = un._main(["--confirm", "--gui-only", "--purge-data", "--root", str(app_root)], out=out)
    assert rc == 2 and "--gui-only" in out.getvalue()
    assert (app_root / ".venv").exists()


def test_gui_summary_probe_needs_no_confirm(tmp_path, monkeypatch):
    home = tmp_path / "home"
    apps = home / "Applications"
    apps.mkdir(parents=True)
    img = apps / "jarvis-hub_1.0_amd64.AppImage"
    img.write_text("img")
    (home / ".config" / "com.jarvis.hub").mkdir(parents=True)
    kw = {"platform": "linux", "home": home, "environ": {}, "system_root": tmp_path / "sys"}
    summary = un.gui_summary(**kw)
    assert summary["installed"] is True
    assert summary["app_paths"] == [str(img)]
    assert summary["userdata_paths"] == [str(home / ".config" / "com.jarvis.hub")]
    assert summary["manual"] == []
    img.unlink()
    assert un.gui_summary(**kw)["installed"] is False

    monkeypatch.setattr(un, "gui_summary", lambda **k: {"installed": False})
    out = io.StringIO()
    assert un._main(["--gui-summary"], out=out) == 0
    assert json.loads(out.getvalue()) == {"installed": False}


def test_partial_data_purge_makes_ok_false(app_root, monkeypatch):
    def fake(*, source_root, backup_first, memory):
        return {"ok": False, "not_erased": ["x.db"]}
    monkeypatch.setattr("agents.core.data_purge.purge_data", fake)
    report = un.run_uninstall(app_root, purge_data=True)
    assert report["ok"] is False
    assert "data_purge" in report["not_removed"]
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_path()}", "--root", str(app_root)],
                  out=out)
    assert rc == 1


def test_dry_run_refused_profile_reports_instead_of_crashing(app_root, monkeypatch):
    monkeypatch.setenv("JARVIS_PROFILE", "NOT A NAME!")
    out = io.StringIO()
    assert un._main(["--dry-run", "--purge-data", "--root", str(app_root)], out=out) == 0
    plan = json.loads(out.getvalue())
    assert "data_root" not in plan and "JARVIS_PROFILE" in plan["data_root_error"]


def test_purge_refused_profile_exits_2(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    monkeypatch.setenv("JARVIS_PROFILE", "NOT A NAME!")
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", "--yes-purge=x", "--root", str(app_root)], out=out)
    assert rc == 2 and "JARVIS_PROFILE" in out.getvalue()
    assert calls == [] and (app_root / ".venv").exists()


def test_yes_purge_bare_folder_name_is_not_enough(app_root, monkeypatch):
    """The folder name ('memory', 'memory_logs') is the same on every machine: a script
    must name the actual data root it means to erase."""
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_name()}", "--root", str(app_root)],
                  out=out)
    assert rc == 2 and calls == []
    assert "absolute path" in out.getvalue()


def test_yes_purge_without_purge_data_is_refused(app_root):
    out = io.StringIO()
    rc = un._main(["--confirm", f"--yes-purge={_data_path()}", "--root", str(app_root)], out=out)
    assert rc == 2 and "--purge-data" in out.getvalue()
    assert (app_root / ".venv").exists()


def test_purge_plan_and_prompt_name_what_survives(app_root, tmp_path, monkeypatch):
    uh = tmp_path / "Nerva"
    (uh / "skills").mkdir(parents=True)
    (uh / "souls").mkdir()
    (uh / ".env").write_text("OPENAI_API_KEY=x\n")
    monkeypatch.setenv("JARVIS_USER_HOME", str(uh))
    plan = un.plan_uninstall(app_root, purge_data=True)
    assert plan["kept_after_purge"] == [str(uh / ".env"), str(uh / "skills"), str(uh / "souls")]
    out = io.StringIO()
    un._main(["--confirm", "--purge-data", "--root", str(app_root)], out=out, inp=_Tty("no\n"))
    assert str(uh / ".env") in out.getvalue() and "NOT erased" in out.getvalue()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_uninstall_sh_unknown_option_refuses(tmp_path):
    """A mistyped `--dryrun --confirm` must not fall through to a real uninstall."""
    bash = shutil.which("bash")
    bindir = tmp_path / "bin"  # dirname only, no python: if the check is missing, it fails safe
    bindir.mkdir()
    (bindir / "dirname").symlink_to(shutil.which("dirname"))
    res = subprocess.run([bash, str(REPO_ROOT / "uninstall.sh"), "--dryrun", "--confirm"],
                         capture_output=True, text=True, timeout=60, check=False,
                         env={**os.environ, "PATH": str(bindir)})
    assert res.returncode == 2, res.stdout + res.stderr
    assert "unknown option: --dryrun" in res.stderr


def test_wrappers_forward_round1_flags():
    sh = (REPO_ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "ARGS+=(--gui-only)" in sh and "ARGS=(--gui-summary)" in sh
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    assert '"/GUIONLY" (set "GUIONLY=1" & set "KNOWN=1")' in bat
    assert '"/GUISUMMARY" (set "GUISUMMARY=1" & set "KNOWN=1")' in bat
    # batch for-loops split on '=', so the non-interactive confirmation comes from an env var
    assert 'if defined NERVA_YES_PURGE if defined PURGEDATA set "YESPURGE="--yes-purge=!NERVA_YES_PURGE!""' in bat
    assert "agents.core.uninstall --confirm !GUI! !PURGEDATA! !YESPURGE! !NOBACKUP!" in bat


def test_nerva_uninstall_verb_forwards_gui_only_and_summary(monkeypatch):
    from agents.cli.nerva import main

    seen = []
    monkeypatch.setattr(un, "_main", lambda argv, **kw: seen.append(argv) or 0)
    assert main(["uninstall", "--gui-summary"], context=_ctx(io.StringIO())) == 0
    assert main(["uninstall", "--confirm", "--gui-only"], context=_ctx(io.StringIO())) == 0
    assert seen == [["--gui-summary"], ["--confirm", "--gui-only"]]


# ── round 2: source-built desktop app, BAT refusal/precedence, engine probe, absolute --yes-purge
def _fake_source_build(root: Path, *, windows: bool = False) -> Path:
    """What `cargo run` / `cargo tauri build` in desktop/src-tauri leave behind."""
    target = root / "desktop" / "src-tauri" / "target"
    rel = target / "release"
    rel.mkdir(parents=True)
    (rel / ("jarvis-hub-desktop.exe" if windows else "jarvis-hub-desktop")).write_text("ELF")
    (rel / "bundle" / "deb").mkdir(parents=True)
    (rel / "bundle" / "deb" / "jarvis-hub_0.9.2_amd64.deb").write_text("deb")
    (target / "debug" / "deps").mkdir(parents=True)
    return target


def _linux_desktop(tmp_path):
    return {"platform": "linux", "home": tmp_path / "home", "environ": {},
            "system_root": tmp_path / "sys"}


def test_source_built_target_listed_in_gui_only_dry_run(app_root, tmp_path, monkeypatch):
    target = _fake_source_build(app_root)
    real = un.desktop_app_targets
    monkeypatch.setattr(un, "desktop_app_targets",
                        lambda **kw: real(**{**kw, **_linux_desktop(tmp_path)}))
    out = io.StringIO()
    assert un._main(["--dry-run", "--gui-only", "--root", str(app_root)], out=out) == 0
    rows = {r["path"]: r for r in json.loads(out.getvalue())["desktop"]}
    assert rows[str(target)]["exists"] is True and rows[str(target)]["action"] == "remove"
    assert rows[str(target)]["role"] == "source_build"
    assert target.exists()


def test_gui_only_removes_source_build_and_keeps_engine(app_root, tmp_path, monkeypatch):
    target = _fake_source_build(app_root)
    real = un.desktop_app_targets
    monkeypatch.setattr(un, "desktop_app_targets",
                        lambda **kw: real(**{**kw, **_linux_desktop(tmp_path)}))
    out = io.StringIO()
    assert un._main(["--confirm", "--gui-only", "--root", str(app_root)], out=out) == 0
    report = json.loads(out.getvalue())
    assert str(target) in report["desktop"]["removed"] and report["ok"] is True
    assert not target.exists()
    assert (app_root / "desktop" / "src-tauri").is_dir()  # the source itself stays
    assert (app_root / ".venv").exists() and (app_root / "worldview" / "node_modules").exists()


def test_full_gui_uninstall_also_removes_source_build(app_root, tmp_path):
    target = _fake_source_build(app_root)
    report = un.run_uninstall(app_root, gui=True, desktop=_linux_desktop(tmp_path))
    assert str(target) in report["desktop"]["removed"] and not target.exists()


def test_gui_summary_detects_source_build(app_root, tmp_path, monkeypatch):
    target = _fake_source_build(app_root)
    real = un.desktop_app_targets
    monkeypatch.setattr(un, "desktop_app_targets",
                        lambda **kw: real(**{**kw, **_linux_desktop(tmp_path)}))
    out = io.StringIO()
    assert un._main(["--gui-summary", "--root", str(app_root)], out=out) == 0
    s = json.loads(out.getvalue())
    assert s["installed"] is True and s["app_paths"] == []
    assert str(target / "release" / "jarvis-hub-desktop") in s["source_built_paths"]
    assert str(target / "release" / "bundle") in s["source_built_paths"]


def test_gui_summary_windows_source_build_exe(app_root, tmp_path):
    target = _fake_source_build(app_root, windows=True)
    s = un.gui_summary(platform="win32", home=tmp_path / "home", environ={}, app_root=app_root)
    assert s["installed"] is True
    assert str(target / "release" / "jarvis-hub-desktop.exe") in s["source_built_paths"]


def test_gui_summary_empty_target_is_not_installed(app_root, tmp_path):
    (app_root / "desktop" / "src-tauri" / "target" / "debug" / "deps").mkdir(parents=True)
    s = un.gui_summary(**_linux_desktop(tmp_path), app_root=app_root)
    # an aborted `cargo check` leaves target/ but no app: listed for cleanup, not "installed"
    assert s["installed"] is False and s["source_built_paths"] == []
    rows = {r["path"]: r for r in un.desktop_app_targets(**_linux_desktop(tmp_path), app_root=app_root)}
    assert rows[str(app_root / "desktop" / "src-tauri" / "target")]["exists"] is True


def test_gui_summary_reports_engine_platform_and_root(app_root, tmp_path):
    s = un.gui_summary(**_linux_desktop(tmp_path), app_root=app_root)
    assert s["engine_installed"] is True and s["platform"] == "linux"
    assert s["app_root"] == str(app_root)
    shutil.rmtree(app_root / ".venv")
    assert un.gui_summary(**_linux_desktop(tmp_path), app_root=app_root)["engine_installed"] is True
    shutil.rmtree(app_root / "worldview" / "node_modules")
    assert un.gui_summary(**_linux_desktop(tmp_path), app_root=app_root)["engine_installed"] is False


@pytest.mark.parametrize("value", ["memory_logs", "./memory_logs", "memory_logs/"])
def test_yes_purge_relative_path_is_refused_even_when_it_resolves(tmp_path, monkeypatch, value):
    """The wrappers cd into the repo root first, so a relative `memory_logs` resolves to the
    real default data root — still a constant, so it must be refused."""
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    data = tmp_path / "memory_logs"
    data.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "app"
    (root / ".venv").mkdir(parents=True)
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={value}", "--root", str(root)], out=out)
    assert rc == 2 and calls == [], out.getvalue()
    assert "absolute" in out.getvalue()
    assert (root / ".venv").exists()
    # the absolute path of the same root is accepted
    out = io.StringIO()
    assert un._main(["--confirm", "--purge-data", f"--yes-purge={data}", "--root", str(root)],
                    out=out) == 0
    assert calls == [True]


def _bat_loop(bat: str) -> str:
    start = bat.index("for %%A in (%*) do (")
    return bat[start:bat.index("\n)\n", start)]


def test_bat_refuses_unknown_options_before_any_prompt():
    """`UNINSTALL.bat /DRYRN /CONFIRM` must not fall through to a real uninstall."""
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    loop = _bat_loop(bat)
    assert 'set "KNOWN=0"' in loop
    switches = ["/CONFIRM", "/DRYRUN", "/GUI", "/GUIONLY", "/GUISUMMARY", "/PURGEDATA", "/NOBACKUP"]
    for sw in switches:
        line = next(ln for ln in loop.splitlines() if f'"{sw}"' in ln)
        # the KNOWN marker must sit inside the if's parentheses, or `&` runs it unconditionally
        assert line.strip().startswith(f'if /I "%%~A"=="{sw}" (') and 'set "KNOWN=1"' in line, line
    assert 'if "!KNOWN!"=="0" (' in loop
    assert "[ERROR] unknown option %%~A - nothing was removed" in loop
    assert "exit /b 2" in loop
    # the refusal happens inside the parse loop, i.e. before the Continue? prompt
    assert bat.index("exit /b 2") < bat.index("Continue? [y/N]")


def test_bat_guionly_takes_precedence_over_gui():
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    loop = _bat_loop(bat)
    assert 'set "GUIONLY=1"' in loop and 'set "GUIFLAG=1"' in loop
    assert "GUI=--gui" not in loop  # order of switches can no longer decide the mode
    assert 'if defined GUIONLY (set "GUI=--gui-only") else if defined GUIFLAG set "GUI=--gui"' in bat


def test_bat_propagates_exit_code():
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    assert 'set "RC=!errorlevel!"' in bat
    assert bat.rstrip().endswith("endlocal & exit /b %RC%")


# ── round 3: BAT Python detection must not read a parse-time %errorlevel%


def _bat_python_detection(bat: str) -> str:
    start = bat.index("REM --- Find Python")
    return bat[start:bat.index("\n:havepy\n", start)]


def test_bat_python_detection_never_uses_parse_time_errorlevel():
    """cmd expands %errorlevel% once for a whole parenthesised block, so a nested
    `where python` check inside the `where py` else-branch always saw py's failure: hosts
    with only `python` on PATH fell back to .venv's own interpreter (which then cannot
    delete .venv) or reported "no Python found". Each probe must be tested on its own."""
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    assert "%errorlevel%" not in bat.lower()
    det = _bat_python_detection(bat)
    # every probe decides on its own exit status (&&) and jumps out flat — no nesting
    py_probe = 'py -3 -c "import sys" >nul 2>&1 && (set "PY=py -3" & goto :havepy)'
    python_probe = 'python -c "import sys" >nul 2>&1 && (set "PY=python" & goto :havepy)'
    assert py_probe in det
    assert python_probe in det
    assert det.index(py_probe) < det.index(python_probe) < det.index(r".venv\Scripts\python.exe")
    assert "else (" not in det
    # the PY value may hold a launcher argument ("py -3"), so it must not be quoted as one exe
    assert '"!PY!"' not in bat
    assert "!PY! -m agents.core.uninstall --confirm" in bat


def test_bat_warns_when_only_the_venv_interpreter_is_available():
    """Running from .venv\\Scripts\\python.exe locks it on Windows: the user must be told
    that .venv may be left behind (the module then reports it in not_removed)."""
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    det = _bat_python_detection(bat)
    venv_at = det.index(r'set "PY=.venv\Scripts\python.exe"')
    assert "[WARNING]" in det[venv_at:]
    assert "no Python found" in det[venv_at:]
