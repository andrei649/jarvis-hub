"""V57 bounded, read-only venv ownership scan contracts."""

import os
import sys

from scripts import venv_ownership


def _venv(tmp_path):
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return root


def test_current_owned_environment_passes_with_external_python_link(tmp_path):
    root = _venv(tmp_path)
    (root / "bin" / "python").symlink_to(sys.executable)
    (root / "lib64").symlink_to("lib", target_is_directory=True)

    result = venv_ownership.preflight_venv(root)

    assert result == {"ok": True, "state": "checked", "reason": None}


def test_active_managed_interpreter_link_may_target_a_different_uid(monkeypatch, tmp_path):
    root = _venv(tmp_path)
    target = os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)
    link = root / "bin" / "python"
    link.symlink_to(target)
    real_stat = os.stat
    foreign_uid = os.geteuid() + 17

    def stat_with_foreign_target(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(link):
            fields = list(result)
            fields[4] = foreign_uid
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(venv_ownership.os, "stat", stat_with_foreign_target)

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is True


def test_arbitrary_foreign_owned_python_link_is_refused(monkeypatch, tmp_path):
    root = _venv(tmp_path)
    external = tmp_path / "other-python"
    external.write_text("not executed", encoding="utf-8")
    link = root / "bin" / "python3.12"
    link.symlink_to(external)
    real_stat = os.stat
    foreign_uid = os.geteuid() + 17

    def stat_with_foreign_target(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(link):
            fields = list(result)
            fields[4] = foreign_uid
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(venv_ownership.os, "stat", stat_with_foreign_target)

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is False
    assert "outward symlink" in result["reason"]


def test_outward_package_directory_symlink_is_refused(tmp_path):
    root = _venv(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "lib" / "python3.12" / "site-packages" / "external").symlink_to(
        outside, target_is_directory=True)

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is False
    assert "outward symlink" in result["reason"]


def test_symlink_cycle_is_refused_with_a_named_result(tmp_path):
    root = _venv(tmp_path)
    loop = root / "lib" / "python3.12" / "site-packages" / "loop"
    loop.symlink_to(loop)

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is False and result["state"] == "refused"
    assert "symlink target cannot be inspected" in result["reason"]


def test_traversal_budget_is_enforced_before_scan_can_grow_unbounded(tmp_path):
    root = _venv(tmp_path)
    for index in range(8):
        (root / f"item-{index}").write_text("x", encoding="utf-8")

    result = venv_ownership.preflight_venv(root, max_entries=4)

    assert result["ok"] is False and result["state"] == "refused"
    assert result["reason"] == "environment traversal budget exceeded"


def test_scan_error_fails_closed(monkeypatch, tmp_path):
    root = _venv(tmp_path)
    real_scandir = os.scandir

    def scandir(path):
        if os.fspath(path) == os.fspath(root / "lib"):
            raise PermissionError("modeled unreadable directory")
        return real_scandir(path)

    monkeypatch.setattr(venv_ownership.os, "scandir", scandir)

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is False and "cannot be scanned" in result["reason"]


def test_windows_reports_unchecked_without_claiming_acl_parity(monkeypatch, tmp_path):
    root = _venv(tmp_path)
    monkeypatch.setattr(venv_ownership.os, "name", "nt")

    result = venv_ownership.preflight_venv(root)

    assert result["ok"] is True
    assert result["state"] == "ownership_unchecked_windows"
    assert "ACL" in result["reason"]
