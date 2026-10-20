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
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_name()}",
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
    assert f"--yes-purge={_data_name()}" in out.getvalue()
    assert calls == []
    assert (app_root / ".venv").exists()  # a refused purge removes no software either


def test_cli_purge_wrong_yes_purge_is_refused(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", "--yes-purge=not-it", "--root", str(app_root)], out=out)
    assert rc == 2
    assert "does not match" in out.getvalue()
    assert calls == []
    assert (app_root / ".venv").exists()


def test_cli_purge_right_yes_purge_runs(app_root, monkeypatch):
    calls = []
    monkeypatch.setattr("agents.core.data_purge.purge_data", _fake_purge(calls))
    out = io.StringIO()
    rc = un._main(["--confirm", "--purge-data", f"--yes-purge={_data_name()}",
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
    assert ran == [[str(nsis / "uninstall.exe"), "/S"]]
    assert str(nsis) in report["desktop"]["removed"]
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
    rc = main(["uninstall", "--confirm", "--purge-data", "--yes-purge", _data_name(),
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
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    res = subprocess.run(["bash", str(REPO_ROOT / "uninstall.sh"), "--dry-run", "--purge-data", "--gui"],
                         capture_output=True, text=True, env=env, timeout=120, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    plan = json.loads(res.stdout[res.stdout.index("{"):res.stdout.rindex("}") + 1])
    assert plan["dry_run"] is True and plan["purge_data"] is True and "desktop" in plan
    assert "nothing was removed" in res.stdout
    assert (REPO_ROOT / ".venv").exists() == before


def test_wrappers_forward_new_flags():
    sh = (REPO_ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "--yes-purge=*" in sh and '"--yes-purge=$YES_PURGE"' in sh
    assert "ARGS+=(--gui)" in sh and "ARGS=(--dry-run)" in sh
    bat = (REPO_ROOT / "UNINSTALL.bat").read_text(encoding="utf-8")
    assert '"/DRYRUN" set "DRYRUN=--dry-run"' in bat
    assert '"/GUI" set "GUI=--gui"' in bat
    assert "agents.core.uninstall --dry-run !GUI! !PURGEDATA!" in bat
    assert "agents.core.uninstall --confirm !GUI! !PURGEDATA! !NOBACKUP!" in bat
