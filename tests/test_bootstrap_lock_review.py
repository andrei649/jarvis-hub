import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap


@pytest.fixture
def root(tmp_path):
    python = bootstrap.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.write_text('never executed')
    (tmp_path / bootstrap.LOOSE_REQUIREMENTS).write_text('unlocked-package')
    return tmp_path


@pytest.mark.parametrize('shape', ['missing', 'directory', 'dangling', 'inaccessible'])
def test_lock_failures_never_run_pip(root, monkeypatch, shape):
    lock = root / bootstrap.LOCK_FILE
    if shape == 'directory':
        lock.mkdir()
    elif shape == 'dangling':
        lock.symlink_to('absent')
    elif shape == 'inaccessible':
        original = Path.is_file
        def denied(path):
            if path == lock:
                raise PermissionError('modeled inaccessible parent')
            return original(path)
        monkeypatch.setattr(Path, 'is_file', denied)
    with pytest.raises(bootstrap.BootstrapError) as exc:
        bootstrap.pip_install_locked(bootstrap.venv_python(root), root,
                                    run=lambda *a, **k: pytest.fail('pip ran without locked authority'))
    assert exc.value.reason == ('requirements_missing' if shape == 'missing' else 'requirements_lock_unreadable')


def test_explicit_unlocked_remains_only_opt_in(root):
    calls = []
    args = bootstrap.pip_install_locked(bootstrap.venv_python(root), root, unlocked=True,
        run=lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0))
    assert calls == [args]
    assert '--require-hashes' not in args
    assert args[-1].endswith(bootstrap.LOOSE_REQUIREMENTS)


def test_cli_json_reports_named_lock_refusal_and_failure_status(root, monkeypatch, capsys):
    original = bootstrap.bootstrap
    def run(root_, **kwargs):
        return original(root_, **kwargs, run=lambda *a, **k: pytest.fail('pip reached'),
                        opener=lambda *a, **k: pytest.fail('network reached'))
    monkeypatch.setattr(bootstrap, 'bootstrap', run)
    assert bootstrap.main(['--root', str(root), '--json']) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report['ok'] is False
    assert report['steps'][-1]['step'] == 'deps'
    assert report['steps'][-1]['ok'] is False
    assert report['reason'].startswith('requirements_missing:')
    assert bootstrap.LOCK_FILE in report['reason']
    assert report['runtimes'] == [] and report['smoke'] == {}
