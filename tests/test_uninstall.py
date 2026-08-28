"""Provable software uninstall (0.22 — the appliance install/update tail).

Mirrors the `test_forget_export_purge_parity.py` discipline for the software side of the
same promise: `data_purge` proves a forget erases everything an export can reveal about
the user's *content*; this proves `uninstall` removes everything the installers put on
disk for the *software*, and nothing else — the data root is never touched unless the
caller explicitly opts into `--purge-data`.
"""
import json
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
    ".venv": ("install.sh", "python3 -m venv .venv"),
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
    rc = un._main(["--confirm", "--purge-data", "--root", str(app_root)])
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
