"""Only boolean true proves the smoke succeeded; no child interpreter is executed."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap


def smoke(stdout, *, returncode=0, stderr=''):
    return bootstrap.run_install_smoke(Path('/never/executed'), Path('/unused'),
        run=lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr))


@pytest.mark.parametrize('ok', ['false', 1, {'error': 'failed'}, False, None, 0, [], ''])
def test_only_boolean_true_is_success(ok):
    with pytest.raises(bootstrap.BootstrapError) as exc:
        smoke(json.dumps({'ok': ok}))
    assert exc.value.reason == 'smoke_failed'


def test_missing_success_flag_is_failure():
    with pytest.raises(bootstrap.BootstrapError) as exc:
        smoke('{}')
    assert exc.value.reason == 'smoke_failed'


def test_true_payload_and_leading_noise_are_preserved():
    payload = {'ok': True, 'agents': 17, 'ready_status': 200}
    assert smoke('starting smoke\n' + json.dumps(payload)) == payload


def test_nonzero_exit_wins_over_true_payload():
    with pytest.raises(bootstrap.BootstrapError) as exc:
        smoke('{"ok":true}', returncode=2, stderr='failed\nreason\n')
    assert exc.value.reason == 'smoke_failed'
    assert exc.value.detail == 'reason'


@pytest.mark.parametrize('stdout', ['not json', '{bad json'])
def test_parse_errors_remain_named(stdout):
    with pytest.raises(bootstrap.BootstrapError) as exc:
        smoke(stdout)
    assert exc.value.reason == 'smoke_output_unparseable'
