import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap


@pytest.fixture
def env(tmp_path):
    target = bootstrap.venv_python(tmp_path)
    target.parent.mkdir(parents=True)
    target.symlink_to(Path(sys.executable).resolve())
    (tmp_path / '.venv' / 'lib').mkdir()
    (tmp_path / '.venv' / 'lib64').symlink_to('lib', target_is_directory=True)
    (tmp_path / 'requirements-beta.lock').write_text('pkg==1.0 --hash=sha256:' + '0'*64)
    return tmp_path, target


def test_normal_interpreter_links_and_internal_alias_pass_without_execution(env):
    root, python = env
    calls = []
    assert bootstrap.ensure_venv(root, run=lambda *a, **k: pytest.fail('candidate Python executed')) == (python, False)
    bootstrap.pip_install_locked(python, root, run=lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0))
    assert calls[0][0] == str(python)


@pytest.mark.parametrize('kind', ['outward', 'dangling', 'cycle'])
def test_real_unsafe_links_refuse_before_any_candidate_execution(env, tmp_path, kind):
    root, python = env
    link = root / '.venv' / 'lib' / 'packages'
    if kind == 'outward':
        outside = tmp_path / 'external_packages'
        outside.mkdir()
        link.symlink_to(outside, target_is_directory=True)
    elif kind == 'dangling':
        link.symlink_to('missing')
    else:
        link.symlink_to('packages')
    calls = []
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.ensure_venv(root, run=lambda *a, **k: calls.append(a))
    assert calls == []
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.pip_install_locked(python, root, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_real_helper_unreadable_scan_refuses_before_pip(env, monkeypatch):
    root, python = env
    scan = os.scandir
    def denied(path):
        if Path(path) == root / '.venv' / 'lib':
            raise PermissionError('fixture unreadable')
        return scan(path)
    monkeypatch.setattr(os, 'scandir', denied)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.pip_install_locked(python, root, run=lambda *a, **k: pytest.fail('pip reached'))


def test_real_helper_budget_is_named_refusal(env):
    root, _ = env
    helper = Path(bootstrap.__file__).with_name('venv_ownership.py')
    spec = importlib.util.spec_from_file_location('helper_budget', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.preflight_venv(root / '.venv', max_entries=1)
    assert report['ok'] is False
    assert 'budget' in report['reason']
