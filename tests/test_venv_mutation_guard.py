"""Owner mismatch modeled through stat; never chown or execute pip."""
import os
import sys
from pathlib import Path

import pytest

from agents.core import hub_update_apply as update


@pytest.fixture
def foreign_venv(tmp_path, monkeypatch):
    env = tmp_path / '.venv'
    (env / 'bin').mkdir(parents=True)
    python = env / 'bin' / 'python'
    python.write_text('not executed')
    package = env / 'lib' / 'python3.12' / 'site-packages' / 'pkg.py'
    package.parent.mkdir(parents=True)
    package.write_text('existing package')
    stat = os.stat
    lstat = os.lstat
    def wrapped(fn):
        def call(path, *args, **kwargs):
            result = fn(path, *args, **kwargs)
            if Path(path) == package:
                fields = list(result)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return result
        return call
    monkeypatch.setattr(os, 'stat', wrapped(stat))
    monkeypatch.setattr(os, 'lstat', wrapped(lstat))
    assert package.lstat().st_uid != os.getuid()
    monkeypatch.setattr(sys, 'prefix', str(env))
    monkeypatch.setattr(sys, 'base_prefix', '/trusted/system')
    monkeypatch.setattr(sys, 'executable', str(python))
    (tmp_path / 'requirements-beta.lock').write_text('pkg==1.0 --hash=sha256:' + '0'*64 + '\n')
    return tmp_path, python


def test_update_refuses_pip_install_in_foreign_owned_venv(foreign_venv, monkeypatch):
    root, _ = foreign_venv
    monkeypatch.setattr(update.hub_update, 'repo_root', lambda: root)
    calls = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))
    assert update.install_dependencies(lambda _: None) is False
    assert calls == []


def test_rollback_refuses_pip_uninstall_in_foreign_owned_venv(foreign_venv, monkeypatch):
    calls = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))
    assert update.uninstall_packages(['pkg'], lambda _: None) is False
    assert calls == []


def test_updater_refuses_non_venv_interpreter_before_pip(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'prefix', '/trusted/system')
    monkeypatch.setattr(sys, 'base_prefix', '/trusted/system')
    monkeypatch.setattr(update.hub_update, 'repo_root', lambda: tmp_path)
    (tmp_path / 'requirements-beta.lock').write_text(
        'pkg==1.0 --hash=sha256:' + '0' * 64 + '\n', encoding='utf-8')
    calls = []
    lines = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))

    assert update.install_dependencies(lines.append) is False
    assert calls == []
    assert any('not inside a virtual environment' in line for line in lines)


def test_updater_refuses_non_venv_interpreter_before_uninstall(monkeypatch):
    monkeypatch.setattr(sys, 'prefix', '/trusted/system')
    monkeypatch.setattr(sys, 'base_prefix', '/trusted/system')
    calls = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))

    assert update.uninstall_packages(['pkg'], lambda _: None) is False
    assert calls == []


def test_owned_active_external_venv_allows_locked_install(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'external-env'))
    monkeypatch.setattr(sys, 'base_prefix', '/trusted/system')
    (tmp_path / 'requirements-beta.lock').write_text(
        'pkg==1.0 --hash=sha256:' + '0' * 64 + '\n', encoding='utf-8')
    monkeypatch.setattr(update.hub_update, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(update, 'preflight_venv', lambda root: {
        'ok': True, 'state': 'checked', 'reason': None})
    calls = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))

    assert update.install_dependencies(lambda _: None) is True
    assert len(calls) == 1 and calls[0][0][1:4] == ['-m', 'pip', 'install']


def test_external_active_venv_and_windows_limitation_are_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'external-env'))
    monkeypatch.setattr(sys, 'base_prefix', '/trusted/system')
    (tmp_path / 'requirements-beta.lock').write_text(
        'pkg==1.0 --hash=sha256:' + '0' * 64 + '\n', encoding='utf-8')
    monkeypatch.setattr(update, 'preflight_venv', lambda _root: {
        'ok': True, 'state': 'ownership_unchecked_windows',
        'reason': 'Windows ACL ownership inspection is not implemented'})
    calls = []
    lines = []
    monkeypatch.setattr(update, '_run_command', lambda *args: calls.append(args) or (0, ''))

    assert update.install_dependencies(lines.append) is True
    assert len(calls) == 1
    assert any('without ACL parity' in line for line in lines)


def test_bootstrap_refuses_real_foreign_owned_tree_before_pip(foreign_venv):
    from scripts import bootstrap
    root, python = foreign_venv
    calls = []
    with pytest.raises(bootstrap.BootstrapError, match="owned by another UID"):
        bootstrap.pip_install_locked(python, root, run=lambda *a, **k: calls.append(a))
    assert calls == []
