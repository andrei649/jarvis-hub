"""Review controls stop before server construction and use private temporary data."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "serve.py"


def run_failure(tmp_path, target, kind, *, predecessor=False):
    injector = tmp_path / 'injector'
    injector.mkdir()
    source = f'''
import sys
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec
class MissingAttribute(Loader):
    def create_module(self, spec): return None
    def exec_module(self, module): pass
class Failure(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != {target!r}: return None
        if {kind!r} == 'attribute': return ModuleSpec(fullname, MissingAttribute())
        if {kind!r} == 'unnamed': raise ImportError('unnamed fixture')
        if {kind!r} == 'external': raise ImportError('external fixture', name='fastapi')
        if {kind!r} == 'near': raise ModuleNotFoundError('near fixture', name='agents_extra')
        raise ModuleNotFoundError('missing fixture', name=fullname)
sys.meta_path.insert(0, Failure())
'''
    (injector / 'sitecustomize.py').write_text(source)
    env = dict(os.environ)
    for name in ('JARVIS_PROFILE', 'NERVA_PROFILE', 'NERVA_RESTART_PREDECESSOR',
                 'JARVIS_SELF_RESTART', 'NERVA_SELF_RESTART', 'NOTIFY_SOCKET', 'WATCHDOG_USEC'):
        env.pop(name, None)
    env.update(JARVIS_HOME=str(tmp_path / 'home'), PYTHONPATH=f'{injector}{os.pathsep}{REPO}')
    if predecessor:
        env['NERVA_RESTART_PREDECESSOR'] = '1234567'
    return subprocess.run([sys.executable, str(SOURCE)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=30)


def test_missing_first_party_attribute_is_not_misreported_as_missing_module(tmp_path):
    result = run_failure(tmp_path, 'agents.core.sd_notify', 'attribute')
    assert result.returncode == 1
    assert 'first-party startup import failed: agents.core.sd_notify' in result.stderr
    assert "ImportError: cannot import name 'continue_restart_keepalive'" in result.stderr
    assert 'ModuleNotFoundError' not in result.stderr
    assert 'Traceback (most recent call last)' in result.stderr


@pytest.mark.parametrize('kind', ['unnamed', 'external', 'near'])
def test_unclassified_or_external_import_errors_keep_original_without_hint(tmp_path, kind):
    result = run_failure(tmp_path, 'agents.core.sd_notify', kind)
    assert result.returncode == 1
    assert 'first-party startup import failed' not in result.stderr
    assert f'{kind if kind != "near" else "near"} fixture' in result.stderr
    assert 'Traceback (most recent call last)' in result.stderr


def test_restore_bootstrap_import_failure_gets_hint_without_starting_server(tmp_path):
    result = run_failure(tmp_path, 'agents.core.backup', 'missing')
    assert result.returncode == 1
    # Python's from-package import converts a missing child to this parent ImportError.
    assert 'first-party startup import failed: agents.core:' in result.stderr
    assert "ImportError: cannot import name 'backup'" in result.stderr
    assert 'Nerva starting at http://' not in result.stdout


def test_predecessor_bootstrap_import_failure_gets_hint_without_waiting(tmp_path):
    result = run_failure(tmp_path, 'agents.core.install_identity', 'missing', predecessor=True)
    assert result.returncode == 1
    assert 'first-party startup import failed: agents.core.install_identity' in result.stderr
    assert 'ModuleNotFoundError: missing fixture' in result.stderr
    assert 'Nerva starting at http://' not in result.stdout
