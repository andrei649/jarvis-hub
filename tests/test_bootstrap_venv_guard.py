"""Bootstrap wiring only; helper verdicts are fixtures, candidate Python is never run."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'bootstrap.py'


@pytest.fixture
def fixture(tmp_path):
    trusted = tmp_path / 'installer' / 'scripts'
    trusted.mkdir(parents=True)
    (trusted / 'bootstrap.py').write_text(SOURCE.read_text())
    helper = trusted / 'venv_ownership.py'
    helper.write_text("def preflight_venv(root):\n    return {'ok':False, 'state':'refused', 'reason':'foreign_owner'}\n")
    spec = importlib.util.spec_from_file_location('bootstrap_guard_fixture', trusted / 'bootstrap.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'target'
    root.mkdir()
    (root / 'requirements-beta.lock').write_text('pkg==1.0 --hash=sha256:' + '0'*64)
    return module, root, helper


@pytest.mark.parametrize('existing_python', [False, True])
def test_existing_tree_refused_before_reuse_or_rebuild(fixture, existing_python):
    module, root, _ = fixture
    target = module.venv_python(root)
    target.parent.mkdir(parents=True)
    if existing_python:
        target.write_text('never run')
    calls = []
    with pytest.raises(module.BootstrapError, match='foreign_owner'):
        module.ensure_venv(root, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_pip_refused_even_when_called_directly(fixture):
    module, root, _ = fixture
    calls = []
    with pytest.raises(module.BootstrapError, match='foreign_owner'):
        module.pip_install_locked(module.venv_python(root), root, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_unrelated_interpreter_refused_before_runner(fixture):
    module, root, _ = fixture
    calls = []
    with pytest.raises(module.BootstrapError, match='venv_interpreter_mismatch'):
        module.pip_install_locked(Path('/another/env/bin/python'), root, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_target_cannot_supply_replacement_guard(fixture):
    module, root, _ = fixture
    (root / 'scripts').mkdir()
    (root / 'scripts' / 'venv_ownership.py').write_text("raise AssertionError('untrusted guard executed')")
    with pytest.raises(module.BootstrapError, match='foreign_owner'):
        module.pip_install_locked(module.venv_python(root), root, run=lambda *a, **k: pytest.fail('pip reached'))


def test_windows_unchecked_is_explicit_and_preserves_pip_args(fixture, capsys):
    module, root, helper = fixture
    helper.write_text("def preflight_venv(root):\n    return {'ok':True, 'state':'ownership_unchecked_windows', 'reason':'unsupported'}\n")
    calls = []
    module.pip_install_locked(module.venv_python(root), root,
                             run=lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=0))
    assert 'ownership unchecked on Windows' in capsys.readouterr().err
    assert '--require-hashes' in calls[0]
    assert calls[0][0] == str(module.venv_python(root))
